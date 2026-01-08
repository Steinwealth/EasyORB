#!/usr/bin/env python3
"""
Prime Stealth Trailing Stop & Take Profit System
===============================================

SINGLE SOURCE OF TRUTH for all position management, stop/TP updates, and exit decisions.
This module is the ONLY component that writes to stops/TP and triggers position closures.

Production-Hardened Features (Chat A+ Review):
- Execution adapter pattern (Demo/Live separation)
- Hysteresis & cooldowns (prevents churn)
- ATR/Spread floor guards (realistic stop distances)
- Gap-risk detection (session boundary protection)
- Partial profit ladder (scale-outs at +3%/+7%)
- Mode-bound trailing profiles (explosive/moon tightening)
- Side-aware math (LONG/SHORT future-proof)
- Concurrency locks (thread-safe)
- Snapshot/restore (persistence on restart)
- Single-brain contract (managers read-only)

Key Features:
- Stealth trailing stops that adapt to market conditions
- Breakeven protection at +0.5% as requested
- Dynamic take profit targets based on volatility
- Hidden stop management (not visible to market)
- Multi-timeframe trailing logic
- Volume-based trailing adjustments
- Momentum-based trailing activation
- Risk-reward optimization
- Integration with existing Prime Trading Manager

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0 (Production-Hardened - Chat A+ Review)
"""

import asyncio
import logging
import time
import math
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import numpy as np
from collections import defaultdict, deque

try:
    from .prime_models import (
        StrategyMode, SignalType, SignalSide, TradeStatus, StopType, TrailingMode,
        MarketRegime, SignalQuality, ConfidenceTier, PrimePosition, PrimeTrade,
        determine_confidence_tier
    )
    from .config_loader import get_config_value
except ImportError:
    from prime_models import (
        StrategyMode, SignalType, SignalSide, TradeStatus, StopType, TrailingMode,
        MarketRegime, SignalQuality, ConfidenceTier, PrimePosition, PrimeTrade,
        determine_confidence_tier
    )
    from config_loader import get_config_value

log = logging.getLogger("prime_stealth_trailing")

# ============================================================================
# EXECUTION ADAPTER PROTOCOL (Demo/Live Separation)
# ============================================================================

class ExecutionAdapter:
    """Protocol for position execution (Demo vs Live)"""
    
    async def close_position(self, position: 'PositionState', reason: str) -> None:
        """Close a position completely"""
        raise NotImplementedError
    
    async def scale_out(self, position: 'PositionState', qty: int, reason: str) -> None:
        """Partial close (scale out)"""
        raise NotImplementedError
    
    async def amend_stop(self, position: 'PositionState', new_stop: float) -> None:
        """Update stop loss (internal tracking only for stealth)"""
        pass  # Stealth stops are internal-only
    
    async def amend_tp(self, position: 'PositionState', new_tp: float) -> None:
        """Update take profit (internal tracking only for stealth)"""
        pass  # Stealth TPs are internal-only

class MockExecutionAdapter(ExecutionAdapter):
    """Mock execution adapter for Demo Mode"""
    
    def __init__(self, mock_executor):
        self.exec = mock_executor
    
    async def close_position(self, position: 'PositionState', reason: str) -> None:
        """Close position in mock executor with accurate P&L data (Rev 00076)"""
        # Rev 00076: Pass exit price and P&L from stealth trailing to mock executor
        if hasattr(self.exec, 'close_position_with_data'):
            await self.exec.close_position_with_data(
                symbol=position.symbol,
                exit_price=position.current_price,  # Accurate current price from stealth trailing
                exit_reason=reason,
                pnl=position.unrealized_pnl  # Accurate P&L from stealth trailing
            )
        elif hasattr(self.exec, 'close_position'):
            # Fallback to old method (will have $0 P&L bug)
            await self.exec.close_position(position.symbol, reason)
        log.info(f"📉 DEMO: Closed {position.symbol} - {reason} (P&L: ${position.unrealized_pnl:+.2f})")
    
    async def scale_out(self, position: 'PositionState', qty: int, reason: str) -> None:
        """Scale out in mock executor"""
        if hasattr(self.exec, 'scale_out'):
            await self.exec.scale_out(position.symbol, qty, reason)
        log.info(f"📉 DEMO: Scaled out {qty} shares of {position.symbol} - {reason}")

class LiveETradeAdapter(ExecutionAdapter):
    """Live ETrade execution adapter - Uses order executor for batch efficiency"""
    
    def __init__(self, etrade_client, order_executor=None):
        self.etrade = etrade_client
        self.order_executor = order_executor  # Optional: for batch exits
    
    async def close_position(self, position: 'PositionState', reason: str) -> None:
        """Close position via ETrade API"""
        try:
            # Use place_order (correct E*TRADE API method)
            await asyncio.to_thread(
                self.etrade.place_order,
                symbol=position.symbol,
                quantity=position.quantity,
                side='SELL' if position.side == SignalSide.LONG else 'BUY',
                order_type='MARKET'
            )
            log.info(f"📉 LIVE: Closed {position.symbol} via ETrade - {reason}")
        except Exception as e:
            log.error(f"❌ Failed to close {position.symbol}: {e}")
    
    async def scale_out(self, position: 'PositionState', qty: int, reason: str) -> None:
        """Partial close via ETrade API"""
        try:
            await asyncio.to_thread(
                self.etrade.place_order,
                symbol=position.symbol,
                quantity=qty,
                side='SELL' if position.side == SignalSide.LONG else 'BUY',
                order_type='MARKET'
            )
            log.info(f"📉 LIVE: Scaled out {qty} shares of {position.symbol} via ETrade - {reason}")
        except Exception as e:
            log.error(f"❌ Failed to scale out {position.symbol}: {e}")

# ============================================================================
# ENUMS
# ============================================================================

class StealthMode(Enum):
    """Stealth trailing stop modes"""
    INACTIVE = "inactive"
    BREAKEVEN = "breakeven"
    TRAILING = "trailing"
    EXPLOSIVE = "explosive"
    MOON = "moon"

class TrailingTrigger(Enum):
    """Trailing stop activation triggers"""
    PRICE_BREAKEVEN = "price_breakeven"
    PRICE_PERCENTAGE = "price_percentage"
    VOLUME_SURGE = "volume_surge"
    MOMENTUM_BREAKOUT = "momentum_breakout"
    TIME_BASED = "time_based"

class ExitReason(Enum):
    """Exit reasons for position closure"""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    BREAKEVEN_PROTECTION = "breakeven_protection"
    TIME_EXIT = "time_exit"
    VOLUME_EXIT = "volume_exit"
    MOMENTUM_EXIT = "momentum_exit"
    GAP_RISK = "gap_risk"
    SCALE_OUT_T1 = "scale_out_t1"
    SCALE_OUT_T2 = "scale_out_t2"
    END_OF_DAY_CLOSE = "end_of_day_close"  # Rev 20251020: Market close exit

# ============================================================================
# MODE-BOUND TRAILING PROFILES
# ============================================================================

# (trailing_multiplier, take_profit_multiplier)
TRAIL_PROFILE = {
    StealthMode.INACTIVE: (1.00, 1.00),
    StealthMode.BREAKEVEN: (1.00, 1.00),
    StealthMode.TRAILING: (1.00, 1.00),      # Base behavior
    StealthMode.EXPLOSIVE: (0.75, 1.10),     # 25% tighter stop, +10% TP
    StealthMode.MOON: (0.60, 1.30)           # 40% tighter stop, +30% TP
}

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class StealthConfig:
    """Stealth trailing stop configuration"""
    # LET WINNERS RUN (Rev 00166 - MAXIMUM PROFIT CAPTURE!)
    # Rev 00167: Lowered thresholds to protect small early profits (WEBL/FNGU analysis Dec 5, 2025)
    # Rev 00191: Increased activation time from 2.0 to 3.5 minutes to prevent premature exits
    breakeven_threshold_pct: float = 0.0075  # 0.75% activation (protect meaningful gains) - Rev 00196: Optimized from 2.0% to 0.75% based on historical data analysis (median activation P&L)
    breakeven_offset_pct: float = 0.002     # 0.2% above entry (locks profit) - Strategy.md line 376
    min_breakeven_activation_minutes: float = 6.4  # Rev 00196: Optimized from 3.5 to 6.4 minutes based on historical data analysis (median activation time)
    
    # Trailing stop parameters (Rev 00180AD - OPTIMIZED FOR TYPICAL DAYS)
    base_trailing_pct: float = 0.015        # 1.5% base trailing ⭐ OPTIMAL (+30.3% weekly)
    min_trailing_pct: float = 0.010         # 1.0% minimum trailing (tight on big moves)
    max_trailing_pct: float = 0.025         # 2.5% maximum trailing (wide on volatile moves)
    
    # Rev 00131: Trailing activation requirements (OPTIMIZED FOR PROFIT CAPTURE)
    # Rev 00167: Lowered thresholds to protect small early profits (WEBL/FNGU analysis Dec 5, 2025)
    # Rev 00191: Increased activation time from 2.0 to 3.5 minutes to prevent premature exits
    # Rev 00192: Increased minimum profit from 0.3% to 0.5% to prevent trailing from activating on tiny moves
    min_trailing_activation_minutes: float = 6.4  # Rev 00196: Optimized from 3.5 to 6.4 minutes based on historical data analysis (median activation time)
    min_profit_for_trailing_pct: float = 0.007   # Rev 00196: Optimized from 0.5% to 0.7% based on historical data analysis (91.1% profit capture vs 75.4% at 0.5%)
    
    # Momentum-based trailing (Rev 00166 - CAPTURE BIG MOVES)
    explosive_trailing_pct: float = 0.040   # 4.0% for explosive moves (WIDER)
    momentum_gain_threshold: float = 0.003  # +0.3% in 15 min = explosive
    momentum_lookback_minutes: float = 15.0  # Check last 15 minutes
    
    # ATR & Spread floor guards (Rev 00131 - OPTIMIZED)
    atr_stop_k: float = 1.0                 # 1.0× ATR minimum stop distance (increased from 0.8×)
    spread_stop_k: float = 0.0025           # 0.25% of price (spread guard)
    gap_risk_threshold: float = 0.02        # 2% gap triggers exit (base - adaptive thresholds used)
    min_gap_risk_activation_minutes: float = 10.0  # Rev 00126: Minimum 10 minutes before gap risk can trigger
    
    # Partial profit ladder (NEW - Chat recommendation)
    scale_out_t1_pct: float = 0.03          # First scale-out at +3%
    scale_out_t2_pct: float = 0.07          # Second scale-out at +7%
    scale_out_t1_qty_pct: float = 0.25      # 25% of position
    scale_out_t2_qty_pct: float = 0.25      # 25% of position
    scale_out_stop_tighten_t1: float = 0.003  # +0.3% above entry after T1
    scale_out_stop_tighten_t2: float = 0.5   # 50% trailing distance after T2
    
    # Volume tightening cooldown (NEW - Chat recommendation)
    volume_tighten_cooldown_sec: float = 10.0   # 10 second cooldown
    volume_hysteresis_pct: float = 0.92         # 92% of peak to relax
    
    # Volume-based protection (ENHANCED SENSITIVITY FOR SELLING SURGES)
    selling_volume_surge_threshold: float = 1.4  # 1.4x average volume for more sensitive selling detection
    volume_stop_tightening_pct: float = 0.8      # 80% stop tightening for better protection
    buyers_volume_surge_threshold: float = 1.3   # 1.3x average volume for buying surge detection
    extreme_selling_volume_threshold: float = 2.2  # 2.2x volume for immediate exit on extreme selling surge
    low_liquidity_exit_threshold: float = 0.5    # 0.5x volume for low liquidity exit
    
    # Dynamic adjustments
    volatility_multiplier: float = 1.5      # ATR-based adjustment
    volume_multiplier: float = 1.2          # Volume-based adjustment
    momentum_multiplier: float = 1.3        # Momentum-based adjustment
    
    # Take profit targets (LET WINNERS RUN - Rev 00162)
    base_take_profit_pct: float = 0.030     # 3.0% base take profit (realistic target)
    trending_take_profit_pct: float = 0.12  # 12% trending moves
    explosive_take_profit_pct: float = 0.25 # 25% explosive moves
    moon_take_profit_pct: float = 0.50      # 50% moon moves
    
    # High confidence adjustments (OPTIMIZED FOR BIGGER POSITIONS)
    high_confidence_threshold: float = 0.90  # 90% confidence threshold (lowered for more opportunities)
    ultra_confidence_threshold: float = 0.95 # 95% confidence threshold (lowered for more opportunities)
    high_confidence_take_profit_multiplier: float = 2.0  # 2.0x take profit for high confidence (vs 1.5x)
    ultra_confidence_take_profit_multiplier: float = 2.5 # 2.5x take profit for ultra confidence (vs 2.0x)
    high_confidence_moon_threshold: float = 0.12  # 12% for moon mode with high confidence (vs 15%)
    ultra_confidence_moon_threshold: float = 0.08  # 8% for moon mode with ultra confidence (vs 10%)
    
    # Time-based exits
    max_holding_hours: float = 4.0          # 4 hours max holding
    momentum_timeout_minutes: float = 30.0  # 30 min momentum timeout
    
    # Profit timeout (Rev 00179 - Updated to 0.1% threshold)
    profit_timeout_hours: float = 2.5       # 2.5 hours timeout for unprotected profitable positions
    profit_timeout_min_pct: float = 0.001   # 0.1% minimum profit to trigger timeout (Rev 00179: lowered from 0.2%)
    
    # Portfolio health guardrails (Rev 00190 - prevent premature bad-day triggers)
    bad_day_min_positions: int = 3           # Require at least 3 open positions
    bad_day_min_runtime_minutes: float = 20  # Or 20 minutes of runtime before evaluating
    
    # Rev 00214: Minimum profit threshold before allowing stop loss exit
    min_profit_for_stop_exit: float = 0.003  # 0.3% minimum profit
    
    # Rev 00215: Minimum sustained profit time before activating breakeven
    min_breakeven_sustained_minutes: float = 2.0  # 2 minutes minimum
    
    # Legacy volume thresholds (deprecated - use extreme_selling_volume_threshold and low_liquidity_exit_threshold)
    volume_surge_threshold: float = 2.0     # Deprecated - use extreme_selling_volume_threshold
    
    # Rev 00156: Volatility-based trailing tiers (CONFIGURABLE)
    trailing_vol_extreme_pct: float = 0.025       # 2.5% for >6% volatility
    trailing_vol_high_pct: float = 0.020          # 2.0% for 3-6% volatility
    trailing_vol_moderate_pct: float = 0.0175     # 1.75% for 2-3% volatility
    trailing_vol_low_pct: float = 0.015           # 1.5% for <2% volatility
    vol_threshold_extreme: float = 6.0            # 6% volatility threshold
    vol_threshold_high: float = 3.0               # 3% volatility threshold
    vol_threshold_moderate: float = 2.0           # 2% volatility threshold
    
    # Rev 00156: Profit-based trailing tiers (CONFIGURABLE)
    trailing_profit_max_pct: float = 0.015        # 1.5% for 12%+ profit
    trailing_profit_high_pct: float = 0.020       # 2.0% for 7-12% profit
    trailing_profit_medium_pct: float = 0.025     # 2.5% for 3-7% profit
    profit_threshold_max: float = 0.12            # 12% profit threshold
    profit_threshold_high: float = 0.07           # 7% profit threshold
    profit_threshold_medium: float = 0.03         # 3% profit threshold
    
    # Rev 00156: Entry bar protection tiers (CONFIGURABLE)
    # Rev 00191: Widened protection percentages to provide more room for normal price action
    entry_bar_protection_extreme_pct: float = 0.090   # 9% for >6% volatility (was 8%)
    entry_bar_protection_high_pct: float = 0.060      # 6% for 3-6% volatility (was 5%)
    entry_bar_protection_moderate_pct: float = 0.035  # 3.5% for 2-3% volatility (was 3%)
    entry_bar_protection_low_pct: float = 0.025       # 2.5% for <2% volatility (was 2%)
    entry_bar_protection_minutes: float = 30.0        # Protection duration (minutes)
    
    # Rev 00156: Gap risk tiers (CONFIGURABLE)
    gap_risk_extreme_pct: float = 0.060          # 6.0% for >6% volatility
    gap_risk_high_pct: float = 0.050             # 5.0% for 3-6% volatility
    gap_risk_moderate_pct: float = 0.040         # 4.0% for 2-3% volatility
    gap_risk_low_pct: float = 0.030              # 3.0% for <2% volatility
    
    # Rev 00156: Stealth offset (CONFIGURABLE)
    stealth_offset_multiplier: float = 0.1           # 10% of trailing distance
    stealth_offset_multiplier_active: float = 0.05   # 5% when trailing active
    
    # Rev 00156: Other thresholds (CONFIGURABLE)
    default_entry_bar_volatility: float = 2.0        # Default entry bar volatility %
    avg_pnl_threshold_aggressive: float = -0.005     # -0.5% for aggressive booting
    profit_protection_threshold: float = 0.005       # 0.5% profit protection
    loss_threshold: float = -0.002                   # -0.2% loss threshold
    
    # Rev 00170: Gap risk profit bonus (CONFIGURABLE - was hardcoded)
    gap_risk_profit_bonus_high_pct: float = 0.03     # 3% bonus for >3% profit positions
    gap_risk_profit_bonus_medium_pct: float = 0.02  # 2% bonus for >1% profit positions
    gap_risk_profit_bonus_threshold_pct: float = 0.01  # 1% profit threshold for medium bonus
    gap_risk_time_weighted_peak_minutes: float = 45.0  # 45 minutes for time-weighted peak (was hardcoded)
    
    # Rev 00170: Volume/price change thresholds (CONFIGURABLE - was hardcoded)
    volume_surge_moderate_threshold: float = 1.6     # 1.6x volume for moderate surge detection
    price_decline_moderate_threshold: float = -0.01  # -1% price decline for moderate surge
    
    # Rev 00170: Profit-based take profit adjustments (CONFIGURABLE - was hardcoded)
    profit_based_tp_moon_pct: float = 0.10          # 10% TP for 12%+ profit (moon tier)
    profit_based_tp_strong_pct: float = 0.05        # 5% TP for 7-12% profit (strong tier)
    profit_based_tp_standard_pct: float = 0.03       # 3% TP for 3-7% profit (standard tier)
    
    # Rev 00170: Position booting score calculation (CONFIGURABLE - was hardcoded)
    booting_pnl_score_base: float = 0.7              # Base score for near-breakeven positions
    booting_pnl_score_range: float = 0.3             # Score range (0.7-1.0)
    booting_pnl_score_divisor: float = 0.005         # Divisor for PnL score calculation
    booting_stagnation_min_pct: float = 0.001        # 0.1% minimum movement for stagnation check
    booting_stagnation_good_pct: float = 0.01        # 1% movement for good stagnation score
    booting_loss_threshold_pct: float = -0.01        # -1% loss threshold for booting protection
    
    # RSI-based exit thresholds (CONFIGURABLE)
    rsi_exit_threshold: float = 45.0                 # RSI < 45 triggers exit check
    rsi_exit_consecutive_ticks: int = 3              # 3 consecutive ticks required
    
    # Portfolio health check thresholds (CONFIGURABLE)
    health_check_win_rate_threshold: float = 35.0    # <35% win rate = red flag
    health_check_avg_pnl_threshold: float = -0.005   # <-0.5% avg P&L = red flag
    health_check_momentum_threshold: float = 40.0    # <40% momentum = red flag
    health_check_peak_threshold: float = 0.008      # <0.8% avg peak = red flag
    
    # Rapid exit thresholds (CONFIGURABLE)
    rapid_exit_no_momentum_minutes: float = 15.0     # 15 minutes
    rapid_exit_no_momentum_peak_threshold: float = 0.003  # <0.3% peak
    rapid_exit_immediate_reversal_min_start: float = 5.0  # 5 minutes
    rapid_exit_immediate_reversal_min_end: float = 10.0  # 10 minutes
    rapid_exit_immediate_reversal_pnl_threshold: float = -0.005  # <-0.5% P&L
    rapid_exit_weak_position_minutes: float = 20.0  # 20 minutes
    rapid_exit_weak_position_pnl_threshold: float = -0.003  # <-0.3% P&L
    rapid_exit_weak_position_peak_threshold: float = 0.002  # <0.2% peak
    
    # Time-based thresholds (CONFIGURABLE)
    time_weighted_peak_first_hour_minutes: float = 60.0  # First hour
    time_weighted_peak_second_hour_minutes: float = 120.0  # Second hour
    rapid_exit_time_limit_minutes: float = 30.0  # Rapid exits only apply for first N minutes
    
    # Rev 00213: Minimum holding time for profitable positions (prevent premature exits)
    min_hold_minutes_profitable: float = 15.0  # Minimum 15 minutes before allowing stop loss exit on profitable positions

@dataclass
class PositionState:
    """Current state of a position for stealth management"""
    symbol: str
    entry_price: float
    current_price: float
    quantity: int
    entry_time: datetime
    last_update: datetime
    highest_price: float
    lowest_price: float
    initial_stop_loss: float
    current_stop_loss: float
    take_profit: float
    side: SignalSide = SignalSide.LONG  # Trade direction (LONG/SHORT future-proof)
    
    # Optional fields with defaults
    breakeven_achieved: bool = False
    trailing_activated: bool = False
    breakeven_stop: Optional[float] = None
    stealth_mode: StealthMode = StealthMode.INACTIVE
    trailing_distance_pct: float = 0.0
    stealth_offset: float = 0.0
    atr: float = 0.0
    volume_ratio: float = 1.0
    momentum: float = 0.0
    volatility: float = 0.0
    confidence: float = 0.0
    quality_score: float = 0.0
    confidence_tier: Optional[ConfidenceTier] = None
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    entry_bar_volatility: float = 2.0  # Rev 00043: Entry bar volatility % for tiered protection
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    current_rsi: float = 50.0  # Current RSI value (added for clarity)
    
    # NEW: Hysteresis & cooldown tracking (Chat recommendation)
    last_tighten_ts: Optional[datetime] = None
    peak_volume_ratio: float = 1.0
    
    # NEW: Partial profit ladder tracking (Chat recommendation)
    orig_qty: int = 0          # Original quantity for scale-outs
    scaled1: bool = False      # First scale-out done
    scaled2: bool = False      # Second scale-out done
    
    # NEW: RSI momentum tracking (prevents false exits)
    consecutive_low_rsi_ticks: int = 0
    
    # NEW: Profit timeout tracking (Rev 00169)
    profit_timeout_start: Optional[datetime] = None  # When position first became profitable
    
    # NEW: Price history for time-weighted peak (Rev 00130)
    price_history: List[Dict[str, Any]] = field(default_factory=list)  # List of {price, timestamp} for time-weighted peak

@dataclass
class StealthDecision:
    """Decision from stealth trailing system"""
    action: str  # "HOLD", "TRAIL", "EXIT", "BREAKEVEN"
    new_stop_loss: Optional[float] = None
    new_take_profit: Optional[float] = None
    exit_reason: Optional[ExitReason] = None
    stealth_mode: Optional[StealthMode] = None
    reasoning: str = ""
    confidence: float = 1.0

@dataclass
class StealthMetrics:
    """Performance metrics for stealth system"""
    total_positions: int = 0
    breakeven_protected: int = 0
    trailing_activated: int = 0
    explosive_captured: int = 0
    moon_captured: int = 0
    
    # Exit analysis
    stop_loss_exits: int = 0
    take_profit_exits: int = 0
    trailing_exits: int = 0
    breakeven_exits: int = 0
    
    # Performance
    total_pnl: float = 0.0
    avg_pnl_per_trade: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    
    # Stealth effectiveness
    stealth_effectiveness: float = 0.0
    profit_capture_efficiency: float = 0.0

# ============================================================================
# PRIME STEALTH TRAILING SYSTEM
# ============================================================================

class PrimeStealthTrailingTP:
    """
    Prime Stealth Trailing Stop & Take Profit System - SINGLE SOURCE OF TRUTH
    
    This is the ONLY module that writes to stops/TP and triggers position closures.
    All other modules (Multi-Strategy Manager, Trade Manager, etc.) are READ-ONLY.
    
    Production-Hardened with Chat A+ recommendations:
    - Execution adapter (Demo/Live separation)
    - Hysteresis & cooldowns (prevents churn)
    - ATR/Spread floor guards (realistic distances)
    - Gap-risk detection (session protection)
    - Partial profit ladder (scale-outs)
    - Side-aware math (LONG/SHORT ready)
    - Concurrency locks (thread-safe)
    - Snapshot/restore (persistence)
    """
    
    def __init__(self, strategy_mode: StrategyMode = StrategyMode.STANDARD,
                 execution_adapter: Optional[ExecutionAdapter] = None,
                 mode: str = "DEMO",
                 alert_manager: Optional[Any] = None):
        self.strategy_mode = strategy_mode
        self.mode = mode
        self.exec = execution_adapter  # Required for automatic execution
        self.alert_manager = alert_manager  # Rev 00117: For exit alerts
        self.config = self._load_stealth_config()
        
        # Position tracking
        self.active_positions: Dict[str, PositionState] = {}
        self.position_history: deque = deque(maxlen=1000)
        self.stealth_metrics = StealthMetrics()
        
        # Concurrency protection (NEW - Chat recommendation)
        self.locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Rev 00146: Global lock for emergency operations to prevent race conditions
        self._emergency_lock = asyncio.Lock()
        
        # Market data cache
        self.market_data_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 60  # 60 seconds
        
        # Performance tracking
        self.daily_stats = {
            'positions_managed': 0,
            'breakeven_activations': 0,
            'trailing_activations': 0,
            'exits_triggered': 0,
            'scale_outs_triggered': 0,
            'total_pnl': 0.0
        }
        
        # Rev 00133: Exit monitoring collector (TEMPORARY - for exit optimization)
        try:
            from .prime_exit_monitoring_collector import get_exit_monitoring_collector
            self.exit_monitor = get_exit_monitoring_collector()
            log.info("✅ Exit monitoring collector initialized (TEMPORARY - for exit optimization)")
        except Exception as e:
            log.warning(f"⚠️ Exit monitoring collector not available: {e}")
            self.exit_monitor = None
        
        log.info(f"⭐ PrimeStealthTrailingTP initialized (SINGLE SOURCE OF TRUTH)")
        log.info(f"   Strategy: {strategy_mode.value}, Mode: {mode}")
        log.info(f"   Execution Adapter: {type(execution_adapter).__name__ if execution_adapter else 'None'}")
        
        # Rev 00154: Log critical configuration values for debugging
        log.info(f"🔧 Stealth Configuration Values:")
        log.info(f"   - Breakeven Threshold: {self.config.breakeven_threshold_pct:.4f} ({self.config.breakeven_threshold_pct*100:.2f}%)")
        log.info(f"   - Breakeven Offset: {self.config.breakeven_offset_pct:.4f} ({self.config.breakeven_offset_pct*100:.2f}%)")
        log.info(f"   - Min Breakeven Activation Minutes: {self.config.min_breakeven_activation_minutes}")
        log.info(f"   - Min Profit for Trailing: {self.config.min_profit_for_trailing_pct:.4f} ({self.config.min_profit_for_trailing_pct*100:.2f}%)")
        log.info(f"   - Min Trailing Activation Minutes: {self.config.min_trailing_activation_minutes}")
        log.info(f"   - Max Holding Hours: {self.config.max_holding_hours}")
        log.info(f"   - Profit Timeout Hours: {self.config.profit_timeout_hours}")
    
    def _load_stealth_config(self) -> StealthConfig:
        """Load stealth configuration from settings (ALIGNED WITH OPTIMIZED DEFAULTS)"""
        return StealthConfig(
            breakeven_threshold_pct=get_config_value("STEALTH_BREAKEVEN_THRESHOLD", 0.0075),  # Rev 00196: Optimized from 2.0% to 0.75% based on historical data analysis (median activation P&L)
            breakeven_offset_pct=get_config_value("STEALTH_BREAKEVEN_OFFSET", 0.002),  # 0.2% (Rev 00155: Matches Strategy.md line 376)
            min_breakeven_activation_minutes=get_config_value("STEALTH_MIN_BREAKEVEN_ACTIVATION_MINUTES", 6.4),  # Rev 00196: Optimized from 3.5 to 6.4 minutes based on historical data analysis (median activation time)
            base_trailing_pct=get_config_value("STEALTH_BASE_TRAILING", 0.015),  # 1.5% base trailing (matches StealthConfig default)
            min_trailing_pct=get_config_value("STEALTH_MIN_TRAILING", 0.010),  # 1.0% minimum trailing (matches StealthConfig default)
            max_trailing_pct=get_config_value("STEALTH_MAX_TRAILING", 0.025),  # 2.5% maximum trailing (matches StealthConfig default)
            volatility_multiplier=get_config_value("STEALTH_VOLATILITY_MULTIPLIER", 1.5),
            volume_multiplier=get_config_value("STEALTH_VOLUME_MULTIPLIER", 1.2),
            momentum_multiplier=get_config_value("STEALTH_MOMENTUM_MULTIPLIER", 1.3),
            base_take_profit_pct=get_config_value("STEALTH_BASE_TAKE_PROFIT", 0.03),  # 3% (Rev 00166 - MAXIMUM CAPTURE)
            explosive_take_profit_pct=get_config_value("STEALTH_EXPLOSIVE_TAKE_PROFIT", 0.25),  # 25% (aligned)
            moon_take_profit_pct=get_config_value("STEALTH_MOON_TAKE_PROFIT", 0.50),  # 50% (aligned)
            high_confidence_threshold=get_config_value("STEALTH_HIGH_CONFIDENCE_THRESHOLD", 0.90),  # 90% (aligned)
            ultra_confidence_threshold=get_config_value("STEALTH_ULTRA_CONFIDENCE_THRESHOLD", 0.95),  # 95% (aligned)
            high_confidence_take_profit_multiplier=get_config_value("STEALTH_HIGH_CONFIDENCE_TP_MULTIPLIER", 2.0),  # 2.0x (aligned)
            ultra_confidence_take_profit_multiplier=get_config_value("STEALTH_ULTRA_CONFIDENCE_TP_MULTIPLIER", 2.5),  # 2.5x (aligned)
            high_confidence_moon_threshold=get_config_value("STEALTH_HIGH_CONFIDENCE_MOON_THRESHOLD", 0.12),  # 12% (aligned)
            ultra_confidence_moon_threshold=get_config_value("STEALTH_ULTRA_CONFIDENCE_MOON_THRESHOLD", 0.08),  # 8% (aligned)
            max_holding_hours=get_config_value("STEALTH_MAX_HOLDING_HOURS", 4.0),
            momentum_timeout_minutes=get_config_value("STEALTH_MOMENTUM_TIMEOUT", 30.0),
            profit_timeout_hours=get_config_value("STEALTH_PROFIT_TIMEOUT_HOURS", 2.5),
            profit_timeout_min_pct=get_config_value("STEALTH_PROFIT_TIMEOUT_MIN_PCT", 0.001),  # Rev 00179: 0.1% threshold
            bad_day_min_positions=get_config_value("STEALTH_BAD_DAY_MIN_POSITIONS", 3),
            bad_day_min_runtime_minutes=get_config_value("STEALTH_BAD_DAY_MIN_RUNTIME_MINUTES", 20.0),
            selling_volume_surge_threshold=get_config_value("STEALTH_SELLING_VOLUME_SURGE", 1.4),
            volume_stop_tightening_pct=get_config_value("STEALTH_VOLUME_TIGHTENING", 0.8),
            buyers_volume_surge_threshold=get_config_value("STEALTH_BUYERS_VOLUME_SURGE", 1.3),
            extreme_selling_volume_threshold=get_config_value("STEALTH_EXTREME_SELLING_VOLUME", 2.2),
            low_liquidity_exit_threshold=get_config_value("STEALTH_LOW_LIQUIDITY_EXIT", 0.5),
            volume_surge_threshold=get_config_value("STEALTH_VOLUME_SURGE_THRESHOLD", 2.0),  # Deprecated
            atr_stop_k=get_config_value("STEALTH_ATR_STOP_K", 1.0),  # Rev 00131: Increased from 0.8 to 1.0× ATR
            spread_stop_k=get_config_value("STEALTH_SPREAD_STOP_K", 0.0025),
            gap_risk_threshold=get_config_value("STEALTH_GAP_RISK_THRESHOLD", 0.02),
            min_gap_risk_activation_minutes=get_config_value("STEALTH_MIN_GAP_RISK_MINUTES", 10.0),  # Rev 00126
            min_trailing_activation_minutes=get_config_value("STEALTH_MIN_TRAILING_ACTIVATION_MINUTES", 6.4),  # Rev 00196: Optimized from 3.5 to 6.4 minutes based on historical data analysis (median activation time)
            min_profit_for_trailing_pct=get_config_value("STEALTH_MIN_PROFIT_FOR_TRAILING", 0.007),  # Rev 00196: Optimized from 0.5% to 0.7% based on historical data analysis (91.1% profit capture vs 75.4% at 0.5%)
            
            # Momentum-based trailing (CONFIGURABLE)
            explosive_trailing_pct=get_config_value("STEALTH_EXPLOSIVE_TRAILING", 0.040),  # 4.0% for explosive moves
            momentum_gain_threshold=get_config_value("STEALTH_MOMENTUM_GAIN_THRESHOLD", 0.003),  # +0.3% in 15 min = explosive
            momentum_lookback_minutes=get_config_value("STEALTH_MOMENTUM_LOOKBACK_MINUTES", 15.0),  # Check last 15 minutes
            
            # Take profit targets (CONFIGURABLE)
            trending_take_profit_pct=get_config_value("STEALTH_TRENDING_TAKE_PROFIT", 0.12),  # 12% trending moves
            
            scale_out_t1_pct=get_config_value("STEALTH_SCALE_T1_PCT", 0.03),
            scale_out_t2_pct=get_config_value("STEALTH_SCALE_T2_PCT", 0.07),
            scale_out_t1_qty_pct=get_config_value("STEALTH_SCALE_T1_QTY", 0.25),
            scale_out_t2_qty_pct=get_config_value("STEALTH_SCALE_T2_QTY", 0.25),
            scale_out_stop_tighten_t1=get_config_value("STEALTH_SCALE_TIGHTEN_T1", 0.003),
            scale_out_stop_tighten_t2=get_config_value("STEALTH_SCALE_TIGHTEN_T2", 0.5),
            volume_tighten_cooldown_sec=get_config_value("STEALTH_VOLUME_COOLDOWN", 10.0),
            volume_hysteresis_pct=get_config_value("STEALTH_VOLUME_HYSTERESIS", 0.92),
            
            # Rev 00156: Volatility-based trailing tiers (CONFIGURABLE)
            trailing_vol_extreme_pct=get_config_value("STEALTH_TRAILING_VOL_EXTREME", 0.025),
            trailing_vol_high_pct=get_config_value("STEALTH_TRAILING_VOL_HIGH", 0.020),
            trailing_vol_moderate_pct=get_config_value("STEALTH_TRAILING_VOL_MODERATE", 0.0175),
            trailing_vol_low_pct=get_config_value("STEALTH_TRAILING_VOL_LOW", 0.015),
            vol_threshold_extreme=get_config_value("STEALTH_VOL_THRESHOLD_EXTREME", 6.0),
            vol_threshold_high=get_config_value("STEALTH_VOL_THRESHOLD_HIGH", 3.0),
            vol_threshold_moderate=get_config_value("STEALTH_VOL_THRESHOLD_MODERATE", 2.0),
            
            # Rev 00156: Profit-based trailing tiers (CONFIGURABLE)
            trailing_profit_max_pct=get_config_value("STEALTH_TRAILING_PROFIT_MAX", 0.015),
            trailing_profit_high_pct=get_config_value("STEALTH_TRAILING_PROFIT_HIGH", 0.020),
            trailing_profit_medium_pct=get_config_value("STEALTH_TRAILING_PROFIT_MEDIUM", 0.025),
            profit_threshold_max=get_config_value("STEALTH_PROFIT_THRESHOLD_MAX", 0.12),
            profit_threshold_high=get_config_value("STEALTH_PROFIT_THRESHOLD_HIGH", 0.07),
            profit_threshold_medium=get_config_value("STEALTH_PROFIT_THRESHOLD_MEDIUM", 0.03),
            
            # Rev 00156: Entry bar protection tiers (CONFIGURABLE)
            entry_bar_protection_extreme_pct=get_config_value("STEALTH_ENTRY_BAR_PROTECTION_EXTREME", 0.080),
            entry_bar_protection_high_pct=get_config_value("STEALTH_ENTRY_BAR_PROTECTION_HIGH", 0.050),
            entry_bar_protection_moderate_pct=get_config_value("STEALTH_ENTRY_BAR_PROTECTION_MODERATE", 0.030),
            entry_bar_protection_low_pct=get_config_value("STEALTH_ENTRY_BAR_PROTECTION_LOW", 0.020),
            entry_bar_protection_minutes=get_config_value("STEALTH_ENTRY_BAR_PROTECTION_MINUTES", 30.0),
            
            # Rev 00156: Gap risk tiers (CONFIGURABLE)
            gap_risk_extreme_pct=get_config_value("STEALTH_GAP_RISK_EXTREME", 0.060),
            gap_risk_high_pct=get_config_value("STEALTH_GAP_RISK_HIGH", 0.050),
            gap_risk_moderate_pct=get_config_value("STEALTH_GAP_RISK_MODERATE", 0.040),
            gap_risk_low_pct=get_config_value("STEALTH_GAP_RISK_LOW", 0.030),
            
            # Rev 00156: Stealth offset (CONFIGURABLE)
            stealth_offset_multiplier=get_config_value("STEALTH_OFFSET_MULTIPLIER", 0.1),
            stealth_offset_multiplier_active=get_config_value("STEALTH_OFFSET_MULTIPLIER_ACTIVE", 0.05),
            
            # Rev 00156: Other thresholds (CONFIGURABLE)
            default_entry_bar_volatility=get_config_value("STEALTH_DEFAULT_ENTRY_BAR_VOLATILITY", 2.0),
            avg_pnl_threshold_aggressive=get_config_value("STEALTH_AVG_PNL_THRESHOLD_AGGRESSIVE", -0.005),
            profit_protection_threshold=get_config_value("STEALTH_PROFIT_PROTECTION_THRESHOLD", 0.005),
            loss_threshold=get_config_value("STEALTH_LOSS_THRESHOLD", -0.002),
            
            # Rev 00170: Gap risk profit bonus (CONFIGURABLE - was hardcoded)
            gap_risk_profit_bonus_high_pct=get_config_value("STEALTH_GAP_RISK_PROFIT_BONUS_HIGH", 0.03),
            gap_risk_profit_bonus_medium_pct=get_config_value("STEALTH_GAP_RISK_PROFIT_BONUS_MEDIUM", 0.02),
            gap_risk_profit_bonus_threshold_pct=get_config_value("STEALTH_GAP_RISK_PROFIT_BONUS_THRESHOLD", 0.01),
            gap_risk_time_weighted_peak_minutes=get_config_value("STEALTH_GAP_RISK_TIME_WEIGHTED_PEAK", 45.0),
            
            # Rev 00170: Volume/price change thresholds (CONFIGURABLE - was hardcoded)
            volume_surge_moderate_threshold=get_config_value("STEALTH_VOLUME_SURGE_MODERATE", 1.6),
            price_decline_moderate_threshold=get_config_value("STEALTH_PRICE_DECLINE_MODERATE", -0.01),
            
            # Rev 00170: Profit-based take profit adjustments (CONFIGURABLE - was hardcoded)
            profit_based_tp_moon_pct=get_config_value("STEALTH_PROFIT_BASED_TP_MOON", 0.10),
            profit_based_tp_strong_pct=get_config_value("STEALTH_PROFIT_BASED_TP_STRONG", 0.05),
            profit_based_tp_standard_pct=get_config_value("STEALTH_PROFIT_BASED_TP_STANDARD", 0.03),
            
            # Rev 00170: Position booting score calculation (CONFIGURABLE - was hardcoded)
            booting_pnl_score_base=get_config_value("STEALTH_BOOTING_PNL_SCORE_BASE", 0.7),
            booting_pnl_score_range=get_config_value("STEALTH_BOOTING_PNL_SCORE_RANGE", 0.3),
            booting_pnl_score_divisor=get_config_value("STEALTH_BOOTING_PNL_SCORE_DIVISOR", 0.005),
            booting_stagnation_min_pct=get_config_value("STEALTH_BOOTING_STAGNATION_MIN", 0.001),
            booting_stagnation_good_pct=get_config_value("STEALTH_BOOTING_STAGNATION_GOOD", 0.01),
            booting_loss_threshold_pct=get_config_value("STEALTH_BOOTING_LOSS_THRESHOLD", -0.01),
            
            # RSI-based exit thresholds (CONFIGURABLE)
            rsi_exit_threshold=get_config_value("STEALTH_RSI_EXIT_THRESHOLD", 45.0),  # RSI < 45 triggers exit check
            rsi_exit_consecutive_ticks=get_config_value("STEALTH_RSI_EXIT_CONSECUTIVE_TICKS", 3),  # 3 consecutive ticks required
            
            # Portfolio health check thresholds (CONFIGURABLE)
            health_check_win_rate_threshold=get_config_value("STEALTH_HEALTH_CHECK_WIN_RATE_THRESHOLD", 35.0),  # <35% win rate = red flag
            health_check_avg_pnl_threshold=get_config_value("STEALTH_HEALTH_CHECK_AVG_PNL_THRESHOLD", -0.005),  # <-0.5% avg P&L = red flag
            health_check_momentum_threshold=get_config_value("STEALTH_HEALTH_CHECK_MOMENTUM_THRESHOLD", 40.0),  # <40% momentum = red flag
            health_check_peak_threshold=get_config_value("STEALTH_HEALTH_CHECK_PEAK_THRESHOLD", 0.008),  # <0.8% avg peak = red flag
            
            # Rapid exit thresholds (CONFIGURABLE)
            rapid_exit_no_momentum_minutes=get_config_value("STEALTH_RAPID_EXIT_NO_MOMENTUM_MINUTES", 15.0),  # 15 minutes
            rapid_exit_no_momentum_peak_threshold=get_config_value("STEALTH_RAPID_EXIT_NO_MOMENTUM_PEAK", 0.003),  # <0.3% peak
            rapid_exit_immediate_reversal_min_start=get_config_value("STEALTH_RAPID_EXIT_IMMEDIATE_START", 5.0),  # 5 minutes
            rapid_exit_immediate_reversal_min_end=get_config_value("STEALTH_RAPID_EXIT_IMMEDIATE_END", 10.0),  # 10 minutes
            rapid_exit_immediate_reversal_pnl_threshold=get_config_value("STEALTH_RAPID_EXIT_IMMEDIATE_PNL", -0.005),  # <-0.5% P&L
            rapid_exit_weak_position_minutes=get_config_value("STEALTH_RAPID_EXIT_WEAK_MINUTES", 20.0),  # 20 minutes
            rapid_exit_weak_position_pnl_threshold=get_config_value("STEALTH_RAPID_EXIT_WEAK_PNL", -0.003),  # <-0.3% P&L
            rapid_exit_weak_position_peak_threshold=get_config_value("STEALTH_RAPID_EXIT_WEAK_PEAK", 0.002),  # <0.2% peak
            
            # Time-based thresholds (CONFIGURABLE)
            time_weighted_peak_first_hour_minutes=get_config_value("STEALTH_TIME_WEIGHTED_PEAK_FIRST_HOUR", 60.0),  # First hour
            time_weighted_peak_second_hour_minutes=get_config_value("STEALTH_TIME_WEIGHTED_PEAK_SECOND_HOUR", 120.0),  # Second hour
            rapid_exit_time_limit_minutes=get_config_value("STEALTH_RAPID_EXIT_TIME_LIMIT_MINUTES", 30.0),  # Rapid exits only apply for first N minutes
            
            # Rev 00213: Minimum holding time for profitable positions
            min_hold_minutes_profitable=get_config_value("STEALTH_MIN_HOLD_MINUTES_PROFITABLE", 15.0),  # Minimum 15 minutes for profitable positions
            
            # Rev 00214: Minimum profit threshold before allowing stop loss exit
            min_profit_for_stop_exit=get_config_value("STEALTH_MIN_PROFIT_FOR_STOP_EXIT", 0.003),  # 0.3% minimum profit
            
            # Rev 00215: Minimum sustained profit time before activating breakeven
            min_breakeven_sustained_minutes=get_config_value("STEALTH_MIN_BREAKEVEN_SUSTAINED_MINUTES", 2.0)  # 2 minutes minimum
        )
    
    # ========================================================================
    # SIDE-AWARE HELPER METHODS (Future-proof for LONG/SHORT)
    # ========================================================================
    
    def _min_stop_distance(self, pos: PositionState) -> float:
        """Calculate minimum stop distance (ATR and spread floor guard)"""
        atr_floor = self.config.atr_stop_k * pos.atr if pos.atr > 0 else 0.0
        spread_floor = self.config.spread_stop_k * pos.current_price
        return max(atr_floor, spread_floor)
    
    def _hit_stop(self, pos: PositionState) -> bool:
        """Check if stop loss hit (side-aware) with opening bar protection"""
        # Rev 00135: Opening bar protection is maintained for the ENTIRE trade
        # initial_stop_loss contains the opening bar protected stop (floor stop)
        # current_stop_loss can move up (for LONG) but never below initial_stop_loss
        # This ensures positions always have protection based on entry bar volatility
        
        # Rev 00182: CRITICAL FIX - Use the TIGHTER stop (higher for LONG, lower for SHORT)
        # When trailing is active, current_stop_loss is higher than initial_stop_loss (for LONG)
        # We want to use the TIGHTER stop (current_stop_loss) to protect profits, not the wider floor stop
        # The opening bar protected stop is stored in initial_stop_loss
        # This is the FLOOR stop - never allow any stop to be tighter than this
        opening_bar_protected_stop = pos.initial_stop_loss
        
        if pos.side == SignalSide.LONG:
            # Rev 00182: For LONG: Use the HIGHER stop (tighter = better profit protection)
            # When trailing is active, current_stop_loss > initial_stop_loss
            # We want to use current_stop_loss (the trailing stop) to protect profits
            # Only fall back to opening_bar_protected_stop if current_stop_loss is somehow lower (shouldn't happen)
            effective_stop = max(pos.current_stop_loss, opening_bar_protected_stop)
            
            # Log if opening bar protection is being used (shouldn't happen when trailing is active)
            if opening_bar_protected_stop > pos.current_stop_loss:
                log.warning(f"⚠️ Opening Bar Protection fallback for {pos.symbol}: Using floor stop ${opening_bar_protected_stop:.2f} (current: ${pos.current_stop_loss:.2f}) - This shouldn't happen when trailing is active!")
            else:
                log.debug(f"🛡️ Using trailing stop for {pos.symbol}: ${pos.current_stop_loss:.2f} (floor: ${opening_bar_protected_stop:.2f})")
            
            return pos.current_price <= effective_stop
        else:  # SHORT
            # For SHORT: Use the LOWER stop (tighter = better profit protection)
            # When trailing is active, current_stop_loss < initial_stop_loss
            # We want to use current_stop_loss (the trailing stop) to protect profits
            effective_stop = min(pos.current_stop_loss, opening_bar_protected_stop)
            
            # Log if opening bar protection is being used (shouldn't happen when trailing is active)
            if opening_bar_protected_stop < pos.current_stop_loss:
                log.warning(f"⚠️ Opening Bar Protection fallback for {pos.symbol}: Using floor stop ${opening_bar_protected_stop:.2f} (current: ${pos.current_stop_loss:.2f}) - This shouldn't happen when trailing is active!")
            else:
                log.debug(f"🛡️ Using trailing stop for {pos.symbol}: ${pos.current_stop_loss:.2f} (floor: ${opening_bar_protected_stop:.2f})")
            
            return pos.current_price >= effective_stop
    
    def _hit_tp(self, pos: PositionState) -> bool:
        """Check if take profit hit (side-aware)"""
        if pos.side == SignalSide.LONG:
            return pos.current_price >= pos.take_profit
        else:  # SHORT
            return pos.current_price <= pos.take_profit
    
    def _apply_trailing_profile(self, mode: StealthMode, trailing_pct: float) -> float:
        """Apply mode-specific trailing profile (tighter for explosive/moon)"""
        mult, _ = TRAIL_PROFILE.get(mode, (1.0, 1.0))
        tightened = trailing_pct * mult
        return max(self.config.min_trailing_pct, min(tightened, self.config.max_trailing_pct))
    
    def _get_tp_multiplier_for_mode(self, mode: StealthMode) -> float:
        """Get TP multiplier for current mode"""
        _, tp_mult = TRAIL_PROFILE.get(mode, (1.0, 1.0))
        return tp_mult
    
    def _scale_targets(self, position: PositionState) -> Tuple[float, float]:
        """Get scale-out targets"""
        return (self.config.scale_out_t1_pct, self.config.scale_out_t2_pct)
    
    # ========================================================================
    # SNAPSHOT & RESTORE (Persistence on restart)
    # ========================================================================
    
    def snapshot(self) -> Dict[str, Any]:
        """Create snapshot of all active positions for persistence"""
        try:
            snapshot_data = {}
            for symbol, pos in self.active_positions.items():
                snapshot_data[symbol] = {
                    'symbol': pos.symbol,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'quantity': pos.quantity,
                    'entry_time': pos.entry_time.isoformat(),
                    'last_update': pos.last_update.isoformat(),
                    'highest_price': pos.highest_price,
                    'lowest_price': pos.lowest_price,
                    'initial_stop_loss': pos.initial_stop_loss,
                    'current_stop_loss': pos.current_stop_loss,
                    'take_profit': pos.take_profit,
                    'side': pos.side.value,
                    'breakeven_achieved': pos.breakeven_achieved,
                    'trailing_activated': pos.trailing_activated,
                    'stealth_mode': pos.stealth_mode.value,
                    'orig_qty': pos.orig_qty,
                    'scaled1': pos.scaled1,
                    'scaled2': pos.scaled2,
                    'peak_volume_ratio': pos.peak_volume_ratio,
                    'confidence': pos.confidence
                }
            return snapshot_data
        except Exception as e:
            log.error(f"Error creating snapshot: {e}")
            return {}
    
    def restore(self, data: Dict[str, Any]) -> None:
        """Restore positions from snapshot"""
        try:
            for symbol, pos_data in data.items():
                # Convert back to PositionState
                pos_data['entry_time'] = datetime.fromisoformat(pos_data['entry_time'])
                pos_data['last_update'] = datetime.fromisoformat(pos_data['last_update'])
                pos_data['side'] = SignalSide(pos_data['side'])
                pos_data['stealth_mode'] = StealthMode(pos_data['stealth_mode'])
                
                # Create PositionState (fill in missing fields with defaults)
                position = PositionState(**pos_data)
                self.active_positions[symbol] = position
            
            log.info(f"✅ Restored {len(data)} positions from snapshot")
        except Exception as e:
            log.error(f"Error restoring snapshot: {e}")
    
    # ========================================================================
    # POSITION MANAGEMENT
    # ========================================================================
    
    async def add_position(self, position: PrimePosition, market_data: Dict[str, Any]) -> bool:
        """
        Add a new position to stealth management
        
        Args:
            position: PrimePosition to manage
            market_data: Current market data for the symbol
            
        Returns:
            bool: True if successfully added, False otherwise
        """
        try:
            symbol = position.symbol
            log.info(f"🔄 Adding position {symbol} to stealth trailing (Trade ID: {position.position_id})")
            
            # Check if position already exists
            if symbol in self.active_positions:
                log.warning(f"⚠️ Position {symbol} already being managed - skipping duplicate addition")
                return False
            
            # Get current market data
            current_price = market_data.get('price', position.entry_price)
            atr = market_data.get('atr', 0.0)
            volume_ratio = market_data.get('volume_ratio', 1.0)
            confidence = getattr(position, 'confidence', 0.0)
            quality_score = getattr(position, 'quality_score', 0.0)
            
            # Rev 00043: Calculate entry bar volatility for tiered protection
            # Try to get from market_data, or estimate from current price (±2% default)
            entry_bar_high = market_data.get('entry_bar_high', current_price * 1.02)
            entry_bar_low = market_data.get('entry_bar_low', current_price * 0.98)
            
            # Also try to get from recent intraday data if available
            if 'intraday_bars' in market_data and len(market_data['intraday_bars']) > 0:
                # Use most recent bar as entry bar
                recent_bar = market_data['intraday_bars'][-1]
                entry_bar_high = recent_bar.get('high', entry_bar_high)
                entry_bar_low = recent_bar.get('low', entry_bar_low)
            
            entry_bar_volatility = ((entry_bar_high - entry_bar_low) / max(entry_bar_low, 1e-9)) * 100 if entry_bar_low > 0 else 2.0
            
            log.info(f"📊 Entry bar volatility for {symbol}: {entry_bar_volatility:.2f}% (High: ${entry_bar_high:.2f}, Low: ${entry_bar_low:.2f})")
            
            # Determine confidence tier
            confidence_tier = determine_confidence_tier(confidence)
            
            # Rev 00135: Apply opening bar protection IMMEDIATELY when position is added
            # Opening bar protection is maintained for the ENTIRE trade (not time-limited)
            # initial_stop_loss will contain the opening bar protected stop (floor stop)
            # Breakeven and trailing stops can move stop up (for LONG) but never below this floor
            # This ensures positions always have protection based on entry bar volatility
            # Rev 00156: All opening bar protection values are now configurable
            # WIDENED for volatile stocks to prevent premature exits
            if entry_bar_volatility > self.config.vol_threshold_extreme:
                opening_bar_stop_pct = self.config.entry_bar_protection_extreme_pct  # Configurable (default 8%)
                protection_level = "EXTREME"
            elif entry_bar_volatility > self.config.vol_threshold_high:
                opening_bar_stop_pct = self.config.entry_bar_protection_high_pct  # Configurable (default 5%)
                protection_level = "HIGH"
            elif entry_bar_volatility > self.config.vol_threshold_moderate:
                opening_bar_stop_pct = self.config.entry_bar_protection_moderate_pct  # Configurable (default 3%)
                protection_level = "MODERATE"
            else:
                opening_bar_stop_pct = self.config.entry_bar_protection_low_pct  # Configurable (default 2%)
                protection_level = "LOW"
            
            # Calculate initial stop with opening bar protection
            # Rev 00143: CRITICAL FIX - Always use opening bar protection when ORB data is available
            # Opening bar protection is based on ACTUAL entry bar volatility, not generic defaults
            # If we have actual ORB data (entry_bar_high/low), prioritize it over passed stop_loss
            has_actual_orb_data = (entry_bar_high != current_price * 1.02) or (entry_bar_low != current_price * 0.98)
            
            if has_actual_orb_data:
                # We have actual ORB data - ALWAYS use opening bar protection (based on real volatility)
                initial_stop = position.entry_price * (1 - opening_bar_stop_pct)
                
                # Rev 00213: CRITICAL FIX - Validate initial stop is not too tight (prevent premature exits)
                # For LONG positions, stop must be at least 2% below entry
                if position.side == SignalSide.LONG:
                    min_stop_distance_pct = 0.02  # Minimum 2% below entry
                    min_stop_price = position.entry_price * (1 - min_stop_distance_pct)
                    if initial_stop > min_stop_price:
                        log.warning(f"⚠️ Initial stop too tight for {symbol}: ${initial_stop:.2f} (should be at least ${min_stop_price:.2f}, {min_stop_distance_pct*100:.0f}% below entry)")
                        initial_stop = min_stop_price
                        log.info(f"✅ Adjusted initial stop to minimum safe distance: ${initial_stop:.2f} ({min_stop_distance_pct*100:.0f}% below entry)")
                
                if position.stop_loss:
                    passed_stop_pct = abs((position.entry_price - position.stop_loss) / position.entry_price)
                    log.info(f"🛡️ Opening Bar Protection ({protection_level}): Using {opening_bar_stop_pct*100:.1f}% stop (${initial_stop:.2f}) based on ACTUAL ORB volatility {entry_bar_volatility:.2f}% (ignoring passed {passed_stop_pct*100:.1f}% stop)")
                else:
                    log.info(f"🛡️ Opening Bar Protection ({protection_level}): Initial stop set to {opening_bar_stop_pct*100:.1f}% below entry (${initial_stop:.2f}) based on ORB volatility {entry_bar_volatility:.2f}%")
            elif position.stop_loss:
                # No actual ORB data - use passed stop_loss if available
                # Calculate passed stop percentage
                passed_stop_pct = abs((position.entry_price - position.stop_loss) / position.entry_price)
                
                # Calculate opening bar protected stop price (estimated from defaults)
                opening_bar_stop_price = position.entry_price * (1 - opening_bar_stop_pct)
                
                # Use the WIDER stop (lower price for long positions = more protection)
                if opening_bar_stop_price < position.stop_loss:
                    # Opening bar protection is WIDER (lower price = more protection) - use it
                    initial_stop = opening_bar_stop_price
                    log.info(f"🛡️ Opening Bar Protection ({protection_level}): Using {opening_bar_stop_pct*100:.1f}% stop (${initial_stop:.2f}) instead of passed {passed_stop_pct*100:.1f}% stop (${position.stop_loss:.2f})")
                else:
                    # Passed stop is WIDER (lower price = more protection) - use it
                    initial_stop = position.stop_loss
                    log.info(f"🛡️ Using passed stop loss: ${initial_stop:.2f} ({passed_stop_pct*100:.1f}%) - wider than opening bar protection")
                
                # Rev 00213: Validate passed stop is not too tight
                if position.side == SignalSide.LONG:
                    min_stop_distance_pct = 0.02  # Minimum 2% below entry
                    min_stop_price = position.entry_price * (1 - min_stop_distance_pct)
                    if initial_stop > min_stop_price:
                        log.warning(f"⚠️ Initial stop too tight for {symbol}: ${initial_stop:.2f} (should be at least ${min_stop_price:.2f}, {min_stop_distance_pct*100:.0f}% below entry)")
                        initial_stop = min_stop_price
                        log.info(f"✅ Adjusted initial stop to minimum safe distance: ${initial_stop:.2f} ({min_stop_distance_pct*100:.0f}% below entry)")
            else:
                # No stop_loss passed and no ORB data - use opening bar protection (estimated)
                initial_stop = position.entry_price * (1 - opening_bar_stop_pct)
                
                # Rev 00213: Validate estimated stop is not too tight
                if position.side == SignalSide.LONG:
                    min_stop_distance_pct = 0.02  # Minimum 2% below entry
                    min_stop_price = position.entry_price * (1 - min_stop_distance_pct)
                    if initial_stop > min_stop_price:
                        log.warning(f"⚠️ Initial stop too tight for {symbol}: ${initial_stop:.2f} (should be at least ${min_stop_price:.2f}, {min_stop_distance_pct*100:.0f}% below entry)")
                        initial_stop = min_stop_price
                        log.info(f"✅ Adjusted initial stop to minimum safe distance: ${initial_stop:.2f} ({min_stop_distance_pct*100:.0f}% below entry)")
                
                log.info(f"🛡️ Opening Bar Protection ({protection_level}): Initial stop set to {opening_bar_stop_pct*100:.1f}% below entry (${initial_stop:.2f}) - estimated volatility")
            
            # Create position state
            position_state = PositionState(
                symbol=symbol,
                entry_price=position.entry_price,
                current_price=current_price,
                quantity=position.quantity,
                entry_time=position.entry_time,
                last_update=datetime.utcnow(),
                highest_price=current_price,
                lowest_price=current_price,
                initial_stop_loss=initial_stop,
                current_stop_loss=initial_stop,  # Rev 00118: Use opening bar protected stop
                take_profit=position.take_profit or (current_price * 1.10),  # 10% default
                side=position.side,  # Initialize from PrimePosition (LONG/SHORT future-proof)
                atr=atr,
                volume_ratio=volume_ratio,
                momentum=0.0,
                volatility=atr / max(current_price, 1e-9) if current_price > 0 else 0.0,
                confidence=confidence,
                quality_score=quality_score,
                confidence_tier=confidence_tier,
                entry_bar_volatility=entry_bar_volatility,  # Rev 00043: For tiered entry bar protection
                # NEW: Initialize tracking fields
                orig_qty=position.quantity,  # For scale-outs
                peak_volume_ratio=volume_ratio,  # For hysteresis
                last_tighten_ts=None,  # For cooldown
                # Rev 00130: Initialize price history with entry price
                price_history=[{'price': current_price, 'timestamp': datetime.utcnow()}]
            )
            
            # Store position
            self.active_positions[symbol] = position_state
            self.stealth_metrics.total_positions += 1
            self.daily_stats['positions_managed'] += 1
            
            log.info(f"✅ Successfully added position {symbol} to stealth management: "
                    f"Entry=${position.entry_price:.2f}, "
                    f"Stop=${position_state.current_stop_loss:.2f}, "
                    f"Target=${position_state.take_profit:.2f}, "
                    f"Quantity={position.quantity}, "
                    f"Trade ID={position.position_id}")
            
            return True
            
        except Exception as e:
            # Rev 00122: Enhanced error logging to identify root causes
            error_type = type(e).__name__
            error_msg = str(e)
            log.error(f"❌ Failed to add position {position.symbol} to stealth management: {error_type}: {error_msg}", exc_info=True)
            
            # Log diagnostic information
            log.error(f"   Position details: symbol={position.symbol}, entry_price={position.entry_price}, "
                     f"quantity={position.quantity}, position_id={getattr(position, 'position_id', 'N/A')}")
            log.error(f"   Market data keys: {list(market_data.keys()) if market_data else 'None'}")
            log.error(f"   Active positions count: {len(self.active_positions)}")
            log.error(f"   Position already exists: {position.symbol in self.active_positions}")
            
            return False
    
    async def update_position(self, symbol: str, market_data: Dict[str, Any]) -> Optional[StealthDecision]:
        """
        Update position with new market data and EXECUTE stealth decision
        
        SINGLE SOURCE OF TRUTH: This method makes AND applies all stop/TP/exit decisions.
        
        Args:
            symbol: Symbol to update
            market_data: Current market data
            
        Returns:
            StealthDecision: Decision that was applied
        """
        # Concurrency protection (Chat recommendation)
        lock = self.locks[symbol]
        async with lock:
            try:
                if symbol not in self.active_positions:
                    return None
                
                position_state = self.active_positions[symbol]
                
                # Update market data with comprehensive features
                current_price = market_data.get('price', position_state.current_price)
                atr = market_data.get('atr', position_state.atr)
                volume_ratio = market_data.get('volume_ratio', position_state.volume_ratio)
                momentum = market_data.get('momentum', 0.0)
                volatility = market_data.get('volatility', position_state.volatility)
                rsi = market_data.get('rsi', 50.0)  # Default to neutral RSI if not provided
                
                # Update position state
                position_state.current_price = current_price
                position_state.atr = atr
                position_state.volume_ratio = volume_ratio
                position_state.momentum = momentum
                position_state.volatility = volatility
                position_state.last_update = datetime.utcnow()
                
                # Update RSI for decision making
                position_state.current_rsi = rsi
                
                # Calculate PnL (BEFORE updating highs/lows for decision making)
                position_state.unrealized_pnl = (current_price - position_state.entry_price) * position_state.quantity
                position_state.unrealized_pnl_pct = (current_price - position_state.entry_price) / position_state.entry_price
                
                # Update max favorable/adverse
                if position_state.unrealized_pnl > position_state.max_favorable:
                    position_state.max_favorable = position_state.unrealized_pnl
                if position_state.unrealized_pnl < position_state.max_adverse:
                    position_state.max_adverse = position_state.unrealized_pnl
                
                # NOTE: Circuit breaker removed (Rev 00046 analysis)
                # Rely on 15-minute portfolio health check (Rev 00044) instead
                
                # Make stealth decision BEFORE updating highest/lowest price
                # This allows trailing to detect new highs correctly
                decision = await self._make_stealth_decision(position_state, market_data)
                
                # SINGLE SOURCE OF TRUTH: Apply decision AND execute (Chat recommendation)
                if decision.action == "EXIT":
                    # Rev 00148: Collect exit monitoring data BEFORE position is removed
                    # This captures the final state before exit
                    if self.exit_monitor:
                        try:
                            trade_id = getattr(position_state, 'trade_id', getattr(position_state, 'position_id', f"{self.mode}_{symbol}_{datetime.utcnow().strftime('%Y%m%d')}"))
                            self.exit_monitor.collect_monitoring_data(
                                symbol=symbol,
                                trade_id=trade_id,
                                position_state=position_state,
                                market_data=market_data,
                                exit_decision_factors={
                                    'would_exit_gap_risk': decision.exit_reason == ExitReason.GAP_RISK,
                                    'would_exit_trailing': decision.exit_reason == ExitReason.TRAILING_STOP,
                                    'would_exit_stop_loss': decision.exit_reason == ExitReason.STOP_LOSS,
                                    'would_exit_rsi': decision.exit_reason == ExitReason.MOMENTUM_EXIT,
                                    'would_exit_volume': decision.exit_reason == ExitReason.VOLUME_EXIT,
                                    'would_exit_timeout': decision.exit_reason == ExitReason.TIME_EXIT
                                }
                            )
                        except Exception as e:
                            log.debug(f"Exit monitoring data collection skipped for {symbol}: {e}")
                    
                    # Execute close via adapter
                    if self.exec:
                        try:
                            await self.exec.close_position(position_state, decision.exit_reason.value if decision.exit_reason else "unknown")
                        except Exception as e:
                            # Rev 00181: If close fails (e.g., trade not found), still remove from stealth trailing
                            # This prevents infinite loops where position keeps trying to close
                            log.warning(f"⚠️ Failed to close {symbol} via execution adapter: {e} - removing from stealth trailing anyway")
                    # Remove from tracking (always remove, even if close failed)
                    await self._remove_position(symbol, decision.exit_reason)
                    return decision
                
                elif decision.action in {"TRAIL", "BREAKEVEN"}:
                    # Update stops/TP (internal tracking)
                    if decision.action == "BREAKEVEN":
                        # Rev 00135: Opening bar protection maintained for ENTIRE trade
                        # Breakeven stop can move stop up (for LONG) but never below opening bar protected stop
                        # initial_stop_loss contains the opening bar protected stop (floor stop)
                        opening_bar_protected_stop = position_state.initial_stop_loss
                        
                        if decision.new_stop_loss:
                            # Rev 00143: FIX - For LONG: Breakeven moves stop UP (higher price = tighter stop = better profit protection)
                            # But it must NEVER go below the floor (opening_bar_protected_stop)
                            # Use max() to ensure stop never goes below floor
                            if position_state.side == SignalSide.LONG:
                                # For LONG: Floor is LOWER price, breakeven is HIGHER price
                                # Use the HIGHER of the two (tighter stop = better protection of profits)
                                final_stop = max(decision.new_stop_loss, opening_bar_protected_stop)
                                if final_stop != decision.new_stop_loss:
                                    log.info(f"🛡️ Opening Bar Protection: Breakeven stop ${decision.new_stop_loss:.2f} adjusted to floor ${opening_bar_protected_stop:.2f} for {symbol}")
                                decision.new_stop_loss = final_stop
                            else:  # SHORT
                                # For SHORT: Floor is HIGHER price, breakeven is LOWER price
                                # Use the LOWER of the two (tighter stop = better protection of profits)
                                final_stop = min(decision.new_stop_loss, opening_bar_protected_stop)
                                if final_stop != decision.new_stop_loss:
                                    log.info(f"🛡️ Opening Bar Protection: Breakeven stop ${decision.new_stop_loss:.2f} adjusted to floor ${opening_bar_protected_stop:.2f} for {symbol}")
                                decision.new_stop_loss = final_stop
                            
                            position_state.breakeven_stop = decision.new_stop_loss
                            position_state.current_stop_loss = decision.new_stop_loss
                            position_state.breakeven_achieved = True
                            position_state.stealth_mode = StealthMode.BREAKEVEN
                            if self.exec:
                                await self.exec.amend_stop(position_state, decision.new_stop_loss)
                            log.info(f"🛡️ BREAKEVEN STOP SET: {symbol} @ ${decision.new_stop_loss:.2f} (locks +{self.config.breakeven_offset_pct:.1%} profit, floor: ${opening_bar_protected_stop:.2f})")
                    elif decision.action == "TRAIL":
                        # Rev 00135: Opening bar protection maintained for ENTIRE trade
                        # Trailing stops can move stop up (for LONG) but never below opening bar protected stop
                        # initial_stop_loss contains the opening bar protected stop (floor stop)
                        opening_bar_protected_stop = position_state.initial_stop_loss
                        
                        # Rev 00144: CRITICAL FIX - Always set trailing_activated when TRAIL action is received
                        # The flag should be set on FIRST activation, not just when stop moves up
                        # This ensures trailing is marked as active even if stop doesn't move on first activation
                        if not position_state.trailing_activated:
                            # First activation - set flag immediately
                            position_state.trailing_activated = True
                            # Rev 00195: CRITICAL FIX - When trailing activates, it REPLACES breakeven
                            # Trailing stops have priority - clear breakeven flag and use trailing stop
                            if position_state.breakeven_achieved:
                                position_state.breakeven_achieved = False
                                log.info(f"🔄 Trailing activated for {symbol}: Replacing breakeven stop with trailing stop (trailing has priority)")
                            log.info(f"✅ TRAILING STOP ACTIVATED: {symbol} (first activation)")
                        
                        if decision.new_stop_loss:
                            # Rev 00143: FIX - For LONG: Trailing moves stop UP (higher price = tighter stop = better profit protection)
                            # But it must NEVER go below the floor (opening_bar_protected_stop)
                            # Use max() to ensure stop never goes below floor
                            if position_state.side == SignalSide.LONG:
                                # For LONG: Floor is LOWER price, trailing is HIGHER price
                                # Use the HIGHER of the two (tighter stop = better protection of profits)
                                final_stop = max(decision.new_stop_loss, opening_bar_protected_stop)
                                if final_stop != decision.new_stop_loss:
                                    log.info(f"🛡️ Opening Bar Protection: Trailing stop ${decision.new_stop_loss:.2f} adjusted to floor ${opening_bar_protected_stop:.2f} for {symbol}")
                                decision.new_stop_loss = final_stop
                            else:  # SHORT
                                # For SHORT: Floor is HIGHER price, trailing is LOWER price
                                # Use the LOWER of the two (tighter stop = better protection of profits)
                                final_stop = min(decision.new_stop_loss, opening_bar_protected_stop)
                                if final_stop != decision.new_stop_loss:
                                    log.info(f"🛡️ Opening Bar Protection: Trailing stop ${decision.new_stop_loss:.2f} adjusted to floor ${opening_bar_protected_stop:.2f} for {symbol}")
                                decision.new_stop_loss = final_stop
                            
                            # Update stop if it's better (higher for LONG, lower for SHORT)
                            should_update = False
                            if position_state.side == SignalSide.LONG:
                                # For LONG: Update if new stop is higher (tighter = better protection)
                                if decision.new_stop_loss > position_state.current_stop_loss:
                                    should_update = True
                            else:  # SHORT
                                # For SHORT: Update if new stop is lower (tighter = better protection)
                                if decision.new_stop_loss < position_state.current_stop_loss:
                                    should_update = True
                            
                            if should_update:
                                position_state.current_stop_loss = decision.new_stop_loss
                                if self.exec:
                                    await self.exec.amend_stop(position_state, decision.new_stop_loss)
                                log.info(f"🛡️ TRAILING STOP UPDATED: {symbol} @ ${decision.new_stop_loss:.2f} (floor: ${opening_bar_protected_stop:.2f})")
                            else:
                                # Rev 00199: Enhanced logging - log stop update attempts even when not updated
                                log.info(f"🛡️ TRAILING STOP MAINTAINED: {symbol} | Current: ${position_state.current_stop_loss:.2f} | New: ${decision.new_stop_loss:.2f} | Price: ${position_state.current_price:.2f} | Peak: ${position_state.highest_price:.2f} (new stop not higher)")
                    
                    if decision.new_take_profit and decision.new_take_profit != position_state.take_profit:
                        position_state.take_profit = decision.new_take_profit
                        if self.exec:
                            await self.exec.amend_tp(position_state, decision.new_take_profit)
                        log.info(f"Take profit updated for {symbol}: ${decision.new_take_profit:.2f}")
                    
                    # Update mode
                    if decision.stealth_mode:
                        position_state.stealth_mode = decision.stealth_mode
                
                # Update price tracking AFTER decision (allows trailing to detect new highs correctly)
                if current_price > position_state.highest_price:
                    position_state.highest_price = current_price
                if current_price < position_state.lowest_price:
                    position_state.lowest_price = current_price
                
                # Rev 00130: Track price history for time-weighted peak (last 30 minutes)
                # Add current price to history with timestamp
                now = datetime.utcnow()
                position_state.price_history.append({
                    'price': current_price,
                    'timestamp': now
                })
                
                # Rev 00148: Collect exit monitoring data AFTER decision is applied and flags are set
                # This ensures breakeven_achieved and trailing_activated flags are correctly captured
                if self.exit_monitor:
                    try:
                        trade_id = getattr(position_state, 'trade_id', getattr(position_state, 'position_id', f"{self.mode}_{symbol}_{datetime.utcnow().strftime('%Y%m%d')}"))
                        self.exit_monitor.collect_monitoring_data(
                            symbol=symbol,
                            trade_id=trade_id,
                            position_state=position_state,
                            market_data=market_data,
                            exit_decision_factors={
                                'would_exit_gap_risk': decision.action == "EXIT" and decision.exit_reason == ExitReason.GAP_RISK,
                                'would_exit_trailing': decision.action == "EXIT" and decision.exit_reason == ExitReason.TRAILING_STOP,
                                'would_exit_stop_loss': decision.action == "EXIT" and decision.exit_reason == ExitReason.STOP_LOSS,
                                'would_exit_rsi': decision.action == "EXIT" and decision.exit_reason == ExitReason.MOMENTUM_EXIT,
                                'would_exit_volume': decision.action == "EXIT" and decision.exit_reason == ExitReason.VOLUME_EXIT,
                                'would_exit_timeout': decision.action == "EXIT" and decision.exit_reason == ExitReason.TIME_EXIT
                            }
                        )
                    except Exception as e:
                        log.debug(f"Exit monitoring data collection skipped for {symbol}: {e}")
                
                # Keep only last 30 minutes of price history (cleanup old entries)
                cutoff_time = now - timedelta(minutes=30)
                position_state.price_history = [
                    entry for entry in position_state.price_history
                    if entry.get('timestamp', now) >= cutoff_time
                ]
                
                return decision
                
            except Exception as e:
                log.error(f"Failed to update position {symbol}: {e}")
                return None
    
    async def _make_stealth_decision(self, position: PositionState, market_data: Dict[str, Any]) -> StealthDecision:
        """
        Make stealth trailing decision for position
        
        This is the core logic that implements the stealth trailing system
        with breakeven protection at +0.5% as requested.
        """
        try:
            current_price = position.current_price
            entry_price = position.entry_price
            pnl_pct = position.unrealized_pnl_pct
            holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
            
            # Rev 00154: Log decision flow start for debugging
            log.info(f"🔄 STEALTH DECISION: {position.symbol} | P&L: {pnl_pct:.4f} ({pnl_pct*100:.2f}%) | Held: {holding_minutes:.1f}min | Breakeven: {position.breakeven_achieved} | Trailing: {position.trailing_activated}")
            
            # 1. Check for immediate exit conditions
            exit_check = self._check_exit_conditions(position, market_data)
            if exit_check:
                log.info(f"🚪 EXIT TRIGGERED: {position.symbol} - {exit_check.reasoning}")
                return exit_check
            
            # 2. Check for partial profit ladder (scale-outs) - Chat recommendation
            scale_out_check = await self._check_scale_out_ladder(position, market_data)
            if scale_out_check:
                return scale_out_check
            
            # 3. Check for volume-based protection (selling volume surges)
            volume_protection = self._apply_volume_protection(position, market_data)
            if volume_protection:
                return volume_protection
            
            # 4. Check for breakeven protection activation (uses breakeven_threshold_pct from config) - Rev 00152: Fixed to use config value
            # Rev 00194: CRITICAL FIX - Breakeven should NOT activate when trailing is already active
            # Trailing stops have priority - they allow positions to develop and capture profits
            # Breakeven should only activate to SAVE gains when trailing is NOT active
            # Rev 00119: Prevent breakeven from activating too early (first 3.5 minutes)
            # Rev 00154: Added comprehensive INFO-level logging for activation checks
            holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
            min_breakeven_activation_minutes = getattr(self.config, "min_breakeven_activation_minutes", 6.4)  # Rev 00196: Optimized from 3.5 to 6.4 minutes
            
            # Rev 00194: DO NOT activate breakeven if trailing is already active
            # Trailing stops should have priority - they allow positions to develop
            if position.trailing_activated:
                log.debug(f"⏸️ Breakeven check skipped for {position.symbol}: Trailing stop already active (trailing has priority)")
            elif not position.breakeven_achieved:
                log.info(f"🔍 Breakeven Check: {position.symbol} | P&L: {pnl_pct:.4f} ({pnl_pct*100:.2f}%) | Held: {holding_minutes:.1f}min | Threshold: {self.config.breakeven_threshold_pct:.4f} ({self.config.breakeven_threshold_pct*100:.2f}%) | Min Time: {min_breakeven_activation_minutes}min")
                
                # Rev 00215: CRITICAL FIX - Require sustained profit before activating breakeven
                # Prevents breakeven from activating on brief price spikes that immediately reverse
                if (pnl_pct >= self.config.breakeven_threshold_pct and
                    holding_minutes >= min_breakeven_activation_minutes):
                    # Check if profit has been sustained for minimum time (2 minutes)
                    if not hasattr(position, 'breakeven_sustained_start'):
                        position.breakeven_sustained_start = datetime.utcnow()
                        log.info(f"⏳ Breakeven threshold reached for {position.symbol}: Starting sustained profit timer (need 2 min)")
                    
                    sustained_minutes = (datetime.utcnow() - position.breakeven_sustained_start).total_seconds() / 60
                    min_sustained_minutes = getattr(self.config, "min_breakeven_sustained_minutes", 2.0)  # 2 minutes minimum
                    
                    if sustained_minutes >= min_sustained_minutes:
                        log.info(f"✅ Breakeven activation conditions MET for {position.symbol}: {pnl_pct:.2%} profit sustained for {sustained_minutes:.1f} min after {holding_minutes:.1f} min total")
                        return self._activate_breakeven_protection(position)
                    else:
                        log.info(f"⏸️ Breakeven deferred for {position.symbol}: Profit {pnl_pct:.2%} not sustained long enough ({sustained_minutes:.1f} min < {min_sustained_minutes} min)")
                elif (pnl_pct >= self.config.breakeven_threshold_pct and
                      holding_minutes < min_breakeven_activation_minutes):
                    log.info(f"⏸️ Breakeven protection deferred for {position.symbol}: {holding_minutes:.1f} min < {min_breakeven_activation_minutes} min (allow position to develop)")
                elif pnl_pct < self.config.breakeven_threshold_pct:
                    # Reset sustained timer if profit drops below threshold
                    if hasattr(position, 'breakeven_sustained_start'):
                        position.breakeven_sustained_start = None
                        log.debug(f"🔄 Breakeven sustained timer reset for {position.symbol}: Profit {pnl_pct:.2%} below threshold {self.config.breakeven_threshold_pct:.2%}")
                    log.info(f"⏸️ Breakeven protection deferred for {position.symbol}: {pnl_pct:.2%} < {self.config.breakeven_threshold_pct:.2%} (threshold not met)")
            
            # 5. Check for trailing stop activation
            # Rev 00144: CRITICAL FIX - Trailing should activate at min_profit_for_trailing_pct REGARDLESS of breakeven status
            # Breakeven requires breakeven_threshold_pct (configurable), trailing can activate at min_profit_for_trailing_pct (configurable)
            # Rev 00154: Added comprehensive INFO-level logging for activation checks
            if not position.trailing_activated:
                log.info(f"🔍 Trailing Check: {position.symbol} | P&L: {pnl_pct:.4f} ({pnl_pct*100:.2f}%) | Held: {holding_minutes:.1f}min")
                trailing_check = self._check_trailing_activation(position, market_data)
                if trailing_check:
                    log.info(f"✅ Trailing activation decision returned for {position.symbol}")
                    return trailing_check
                else:
                    log.info(f"⏸️ Trailing activation not triggered for {position.symbol} (conditions not met)")
            
            # 6. Update existing trailing stop
            if position.trailing_activated:
                return self._update_trailing_stop(position, market_data)
            
            # 7. Check for take profit updates
            take_profit_check = self._check_take_profit_update(position, market_data)
            if take_profit_check:
                return take_profit_check
            
            # 8. Default: Hold position
            return StealthDecision(
                action="HOLD",
                reasoning=f"Position holding: PnL={pnl_pct:.2%}, Mode={position.stealth_mode.value}"
            )
            
        except Exception as e:
            log.error(f"Error making stealth decision for {position.symbol}: {e}")
            return StealthDecision(
                action="HOLD",
                reasoning=f"Error in decision making: {str(e)}"
            )
    
    def _check_exit_conditions(self, position: PositionState, market_data: Dict[str, Any]) -> Optional[StealthDecision]:
        """Check for immediate exit conditions - Side-aware with gap-risk detection (Chat A+)"""
        current_price = position.current_price
        
        # NOTE: Circuit breaker (Rev 00046) was REMOVED after analysis showed:
        # - 6 out of 10 days recovered from drawdowns
        # - -5% threshold killed 2 winning days (Sept 29, Oct 6)
        # - 15-minute portfolio health check (Rev 00044) is more intelligent
        # - Health check considers win rate, momentum, peaks - not just P&L
        # Decision: Rely on 15-min health check instead of hard P&L cutoff
        
        # PRIORITY 0: RAPID EXIT FOR NO MOMENTUM (Rev 00044 - Loss Prevention)
        # Exit dead trades quickly in first 30 minutes to limit losses
        rapid_exit = self.check_rapid_exit_for_no_momentum(position)
        if rapid_exit:
            return rapid_exit
        
        # PRIORITY 1: GAP-RISK DETECTION (Chat recommendation)
        # Rev 00128: Make gap risk adaptive based on entry bar volatility to avoid closing profitable volatile trades
        # Gap risk should only trigger for truly significant gaps, not normal volatility swings
        holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
        min_gap_risk_activation_minutes = getattr(self.config, "min_gap_risk_activation_minutes", 10.0)  # 10 minutes minimum
        
        # Only check gap risk if position has been held for minimum time
        if holding_minutes >= min_gap_risk_activation_minutes:
            # Rev 00128: Calculate adaptive gap risk threshold based on entry bar volatility
            # Rev 00130: ADD profit-aware gap risk (increase threshold for profitable positions)
            # For volatile stocks, allow larger gaps before triggering exit
            # This prevents closing profitable trades due to normal volatility swings
            entry_vol = position.entry_bar_volatility if hasattr(position, 'entry_bar_volatility') else self.config.default_entry_bar_volatility
            pnl_pct = position.unrealized_pnl_pct
            
            # Rev 00131: INCREASED gap risk thresholds to avoid early exits on profitable trades
            # Rev 00156: All gap risk thresholds are now configurable
            # Widen thresholds to allow more room for normal pullbacks while still catching true gaps
            if entry_vol > self.config.vol_threshold_extreme:
                # Very volatile stocks (>6%): Use configurable gap threshold (default 6%)
                adaptive_gap_threshold = self.config.gap_risk_extreme_pct
                volatility_tier = "EXTREME"
            elif entry_vol > self.config.vol_threshold_high:
                # High volatility stocks (3-6%): Use configurable gap threshold (default 5%)
                adaptive_gap_threshold = self.config.gap_risk_high_pct
                volatility_tier = "HIGH"
            elif entry_vol > self.config.vol_threshold_moderate:
                # Moderate volatility stocks (2-3%): Use configurable gap threshold (default 4%)
                adaptive_gap_threshold = self.config.gap_risk_moderate_pct
                volatility_tier = "MODERATE"
            else:
                # Low volatility stocks (<2%): Use configurable gap threshold (default 3%)
                adaptive_gap_threshold = self.config.gap_risk_low_pct
                volatility_tier = "LOW"
            
            # Rev 00131: PROFIT-AWARE GAP RISK - INCREASED bonus for profitable positions
            # Rev 00170: All profit bonus values are now configurable (was hardcoded)
            # If position is profitable, add larger bonus to gap threshold to protect profits
            profit_bonus = 0.0
            if pnl_pct > self.config.profit_threshold_medium:  # >3% profit (configurable)
                profit_bonus = self.config.gap_risk_profit_bonus_high_pct  # Configurable high bonus
            elif pnl_pct > self.config.gap_risk_profit_bonus_threshold_pct:  # >1% profit (configurable)
                profit_bonus = self.config.gap_risk_profit_bonus_medium_pct  # Configurable medium bonus
            
            adaptive_gap_threshold += profit_bonus
            
            # Rev 00131: TIME-WEIGHTED PEAK - Extended to configurable minutes (default 45)
            # Rev 00170: Now configurable (was hardcoded 45 minutes)
            # This prevents exits based on old peaks and gives more room for profitable trades
            now = datetime.utcnow()
            recent_cutoff = now - timedelta(minutes=self.config.gap_risk_time_weighted_peak_minutes)
            
            # Get recent price history (last 30 minutes)
            recent_prices = []
            if hasattr(position, 'price_history') and position.price_history:
                for price_entry in position.price_history:
                    if isinstance(price_entry, dict) and 'timestamp' in price_entry:
                        if price_entry['timestamp'] >= recent_cutoff:
                            recent_prices.append(price_entry.get('price', 0))
            
            # Determine last peak: Use recent peak if available, otherwise use all-time peak
            if position.side == SignalSide.LONG:
                if recent_prices:
                    recent_peak = max(recent_prices)
                    all_time_peak = position.highest_price
                    last_peak = max(recent_peak, all_time_peak)  # Use higher of recent or all-time
                    peak_source = "recent" if recent_peak >= all_time_peak else "all-time"
                else:
                    last_peak = position.highest_price
                    peak_source = "all-time"
            else:  # SHORT
                if recent_prices:
                    recent_trough = min(recent_prices)
                    all_time_trough = position.lowest_price
                    last_peak = min(recent_trough, all_time_trough)  # Use lower of recent or all-time
                    peak_source = "recent" if recent_trough <= all_time_trough else "all-time"
                else:
                    last_peak = position.lowest_price
                    peak_source = "all-time"
            
            gap_pct = (position.current_price - last_peak) / max(abs(last_peak), 1e-9)
            
            # Only trigger if gap exceeds adaptive threshold (with profit bonus)
            if position.side == SignalSide.LONG and gap_pct < -adaptive_gap_threshold:
                log.warning(f"🚨 GAP-DOWN RISK ({volatility_tier}, P&L={pnl_pct:.2%}, profit_bonus={profit_bonus:.2%}): {position.symbol} gap={gap_pct:.1%} from {peak_source} peak ${last_peak:.2f} (threshold={adaptive_gap_threshold:.1%}, entry_vol={entry_vol:.1%}, after {holding_minutes:.1f} min)")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.GAP_RISK,
                    reasoning=f"Gap-down risk {gap_pct:.1%} exceeds {volatility_tier} volatility threshold {adaptive_gap_threshold:.1%} (profit-aware: +{profit_bonus:.1%} bonus for {pnl_pct:.1%} profit)"
                )
            elif position.side == SignalSide.SHORT and gap_pct > adaptive_gap_threshold:
                log.warning(f"🚨 GAP-UP RISK ({volatility_tier}, P&L={pnl_pct:.2%}, profit_bonus={profit_bonus:.2%}): {position.symbol} gap={gap_pct:.1%} from {peak_source} trough ${last_peak:.2f} (threshold={adaptive_gap_threshold:.1%}, entry_vol={entry_vol:.1%}, after {holding_minutes:.1f} min)")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.GAP_RISK,
                    reasoning=f"Gap-up risk {gap_pct:.1%} exceeds {volatility_tier} volatility threshold {adaptive_gap_threshold:.1%} (profit-aware: +{profit_bonus:.1%} bonus for {pnl_pct:.1%} profit)"
                )
            elif position.side == SignalSide.LONG and gap_pct < -self.config.gap_risk_threshold:
                # Log when gap risk would have triggered with old threshold but doesn't with adaptive threshold
                log.debug(f"⏸️ Gap risk check passed for {position.symbol}: gap={gap_pct:.1%} < old threshold {self.config.gap_risk_threshold:.1%} but < adaptive threshold {adaptive_gap_threshold:.1%} (entry_vol={entry_vol:.1%})")
        elif holding_minutes < min_gap_risk_activation_minutes:
            # Defer gap risk check until minimum holding time
            log.debug(f"⏸️ Gap risk check deferred for {position.symbol}: {holding_minutes:.1f} min < {min_gap_risk_activation_minutes} min (allow position to develop)")
        
        # PRIORITY 1: STEALTH STOP LOSS HIT - Side-aware (Chat recommendation)
        # Rev 00213: CRITICAL FIX - Add minimum holding time for profitable positions to prevent premature exits
        # Rev 00214: CRITICAL FIX - Add minimum profit threshold before allowing stop loss exit on profitable positions
        holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
        
        # Rev 00213: If position is profitable, require minimum holding time before allowing stop loss exit
        # This prevents positions from exiting too early when they're profitable but haven't had time to develop
        if position.unrealized_pnl_pct > 0:  # Position is profitable
            min_hold_minutes_profitable = getattr(self.config, "min_hold_minutes_profitable", 15.0)  # Minimum 15 minutes for profitable positions
            if holding_minutes < min_hold_minutes_profitable:
                log.info(f"⏸️ DEFERRING STOP LOSS EXIT: {position.symbol} is profitable (+{position.unrealized_pnl_pct:.2%}) but only held {holding_minutes:.1f} min (need {min_hold_minutes_profitable} min minimum)")
                # Don't exit yet - let position develop
                # But still check if stop is hit (for logging/debugging)
                if self._hit_stop(position):
                    log.warning(f"⚠️ Stop would be hit but deferring exit: {position.symbol} @ ${current_price:.2f} <= ${position.current_stop_loss:.2f} (profitable position, holding time too short)")
                return None  # Continue holding
            
            # Rev 00214: Require minimum profit (0.3%) before allowing stop loss exit on profitable positions
            # This prevents breakeven stop from triggering exit on positions with very small profits
            min_profit_for_stop_exit = getattr(self.config, "min_profit_for_stop_exit", 0.003)  # 0.3% minimum
            if position.unrealized_pnl_pct < min_profit_for_stop_exit:
                log.info(f"⏸️ DEFERRING STOP LOSS EXIT: {position.symbol} has only {position.unrealized_pnl_pct:.2%} profit (need {min_profit_for_stop_exit:.2%} minimum)")
                # Don't exit yet - let position develop more profit
                if self._hit_stop(position):
                    log.warning(f"⚠️ Stop would be hit but deferring exit: {position.symbol} @ ${current_price:.2f} <= ${position.current_stop_loss:.2f} (profit too small: {position.unrealized_pnl_pct:.2%})")
                return None  # Continue holding
        
        if self._hit_stop(position):
            # Rev 00199: Enhanced logging - log which stop triggered exit with all stop values
            # Rev 00213: Enhanced logging with entry bar volatility and holding time
            stop_type = "TRAILING_STOP" if position.trailing_activated else ("BREAKEVEN_STOP" if position.breakeven_achieved else "STOP_LOSS")
            log.warning(f"🚨 STEALTH STOP TRIGGERED: {position.symbol} @ ${current_price:.2f}")
            log.warning(f"   Entry: ${position.entry_price:.2f} | Current: ${current_price:.2f} | Stop: ${position.current_stop_loss:.2f}")
            log.warning(f"   Initial Stop: ${position.initial_stop_loss:.2f} | Stop Type: {stop_type}")
            log.warning(f"   P&L: {position.unrealized_pnl_pct:.2%} | Holding Time: {holding_minutes:.1f} min")
            log.warning(f"   Entry Bar Volatility: {position.entry_bar_volatility:.2f}% | Breakeven: {position.breakeven_achieved} | Trailing: {position.trailing_activated}")
            log.warning(f"   Peak: ${position.highest_price:.2f} | Lowest: ${position.lowest_price:.2f}")
            log.warning(f"🚨 TRIGGERING AUTOMATIC POSITION CLOSURE")
            return StealthDecision(
                action="EXIT",
                exit_reason=ExitReason.STOP_LOSS,
                reasoning=f"STEALTH STOP HIT - Side={position.side.value} - AUTOMATIC CLOSURE"
            )
        
        # PRIORITY 2: TAKE PROFIT HIT - ACTIVATE TRAILING INSTEAD OF EXITING (Rev 00168)
        # CRITICAL: When 3% TP is hit, lock in breakeven_offset_pct profit and activate TIGHTER trailing!
        if self._hit_tp(position):
            # Check if trailing is already activated
            if not position.trailing_activated:
                log.info(f"🎯 TAKE PROFIT REACHED: {position.symbol} @ ${current_price:.2f} - ACTIVATING TRAILING (not exiting!)")
                
                # Lock in minimum profit using breakeven offset (Rev 00168, Rev 00152: Use config value)
                breakeven_stop = position.entry_price * (1 + self.config.breakeven_offset_pct)
                
                # Activate ADAPTIVE trailing stop - Rev 00156: Use calculated trailing distance
                trailing_pct = self._calculate_trailing_distance(position, market_data)
                trailing_from_high = position.highest_price * (1 - trailing_pct)
                
                # Use the higher of breakeven or trailing
                new_stop_loss = max(breakeven_stop, trailing_from_high)
                
                position.trailing_activated = True
                position.stealth_mode = StealthMode.TRAILING
                self.stealth_metrics.trailing_activated += 1
                self.daily_stats['trailing_activations'] += 1
                
                log.info(f"🔒 BREAKEVEN LOCKED: ${breakeven_stop:.2f} (+{self.config.breakeven_offset_pct:.1%} profit guaranteed)")
                log.info(f"✅ TRAILING ACTIVATED: Stop=${new_stop_loss:.2f} (1.5% trail - TIGHTER!)")
                log.info(f"🚀 Will capture profits on pullbacks, let winners run on strength!")
                
                return StealthDecision(
                    action="TRAIL",
                    new_stop_loss=new_stop_loss,
                    stealth_mode=StealthMode.TRAILING,
                    reasoning=f"TP hit at 3% - Breakeven locked at +{self.config.breakeven_offset_pct:.1%}, trailing at ${new_stop_loss:.2f}"
                )
            else:
                # Trailing already active, just hold and let it trail
                return StealthDecision(
                    action="HOLD",
                    reasoning=f"Above 3% TP with trailing active - letting winner run"
                )
        
        # PRIORITY 3: RSI-based exit for losing positions (Chat: require N consecutive ticks)
        current_rsi = getattr(position, 'current_rsi', market_data.get('rsi', 50.0))
        
        # Rev 00201: Use configurable RSI threshold
        rsi_exit_threshold = getattr(self.config, "rsi_exit_threshold", 45.0)
        rsi_exit_consecutive_ticks = getattr(self.config, "rsi_exit_consecutive_ticks", 3)
        
        if current_rsi < rsi_exit_threshold:
            position.consecutive_low_rsi_ticks += 1
        else:
            position.consecutive_low_rsi_ticks = 0  # Reset if RSI recovers
        
        # Require N consecutive low RSI ticks AND losing position AND below -0.25× base trailing
        min_loss_for_rsi_exit = -0.25 * self.config.base_trailing_pct
        if (position.consecutive_low_rsi_ticks >= rsi_exit_consecutive_ticks and 
            position.unrealized_pnl_pct < min_loss_for_rsi_exit):
            log.warning(f"📉 RSI EXIT: {position.symbol} RSI={current_rsi:.1f} for 3 ticks with loss {position.unrealized_pnl_pct:.2%}")
            return StealthDecision(
                action="EXIT",
                exit_reason=ExitReason.MOMENTUM_EXIT,
                reasoning=f"RSI below 45 for 3 consecutive ticks ({current_rsi:.1f}) with loss {position.unrealized_pnl_pct:.2%}"
            )
        
        # PRIORITY 4: Profit timeout (Rev 00169 - close unprotected profitable positions)
        profit_timeout_check = self._check_profit_timeout(position)
        if profit_timeout_check:
            return profit_timeout_check
        
        # PRIORITY 5: Time-based exit (maximum holding period)
        # Rev 00149: CRITICAL FIX - Defer maximum holding time if breakeven or trailing is active
        # Positions with protection should be allowed to run longer to maximize profit capture
        holding_seconds = (datetime.utcnow() - position.entry_time).total_seconds()
        holding_hours = holding_seconds / 3600
        
        # Rev 00072: Debug logging for time-based exit (helps diagnose timezone issues)
        # Rev 00150: Enhanced logging for activation criteria check
        # Rev 00154: Changed to INFO level for visibility
        if holding_hours >= (self.config.max_holding_hours - 0.1):  # Log when close to threshold
            log.info(f"⏰ MAX HOLD TIME CHECK: {position.symbol} - Entry: {position.entry_time}, Now: {datetime.utcnow()}, Held: {holding_hours:.2f}h / {self.config.max_holding_hours:.2f}h")
            log.info(f"   Breakeven achieved: {position.breakeven_achieved}")
            log.info(f"   Trailing activated: {position.trailing_activated}")
        
        # Rev 00149: Check if position has protection (breakeven or trailing activated)
        # Rev 00150: CRITICAL FIX - Also check if protection SHOULD be active (based on criteria)
        # This prevents premature exits when flags aren't set yet but criteria are met
        # If protection is active, defer maximum holding time to allow positions to run longer
        holding_minutes = holding_hours * 60
        min_breakeven_activation_minutes = getattr(self.config, "min_breakeven_activation_minutes", 6.4)  # Rev 00196: Optimized from 3.5 to 6.4 minutes (median activation time)
        min_trailing_activation_minutes = getattr(self.config, "min_trailing_activation_minutes", 6.4)  # Rev 00196: Optimized from 3.5 to 6.4 minutes (median activation time)
        min_profit_for_trailing_pct = getattr(self.config, "min_profit_for_trailing_pct", 0.007)  # Rev 00196: Optimized from 0.5% to 0.7% (91.1% profit capture vs 75.4% at 0.5%)
        pnl_pct = position.unrealized_pnl_pct
        
        # Check if flags are set OR if criteria are met (should be active)
        breakeven_should_be_active = (
            not position.breakeven_achieved and
            pnl_pct >= self.config.breakeven_threshold_pct and
            holding_minutes >= min_breakeven_activation_minutes
        )
        trailing_should_be_active = (
            not position.trailing_activated and
            pnl_pct >= min_profit_for_trailing_pct and
            holding_minutes >= min_trailing_activation_minutes
        )
        
        has_protection = (
            position.breakeven_achieved or 
            position.trailing_activated or
            breakeven_should_be_active or
            trailing_should_be_active
        )
        
        # Rev 00150: Enhanced logging for activation criteria
        # Rev 00154: Changed to INFO level for visibility
        if holding_hours >= (self.config.max_holding_hours - 0.1):  # Log when close to threshold
            log.info(f"🔍 Max Hold Time Activation Criteria Check:")
            log.info(f"     - Breakeven threshold: {self.config.breakeven_threshold_pct:.4f} ({self.config.breakeven_threshold_pct*100:.2f}%)")
            log.info(f"     - Trailing threshold: {min_profit_for_trailing_pct:.4f} ({min_profit_for_trailing_pct*100:.2f}%)")
            log.info(f"     - Holding minutes: {holding_minutes:.1f} (breakeven min: {min_breakeven_activation_minutes}, trailing min: {min_trailing_activation_minutes})")
            log.info(f"     - P&L: {pnl_pct:.4f} ({pnl_pct*100:.2f}%)")
            log.info(f"     - Breakeven should be active: {breakeven_should_be_active}")
            log.info(f"     - Trailing should be active: {trailing_should_be_active}")
            log.info(f"     - Has protection: {has_protection}")
        
        if holding_hours >= self.config.max_holding_hours:
            if has_protection:
                # Position has protection - defer maximum holding time
                if position.trailing_activated:
                    protection_type = "trailing stop"
                elif position.breakeven_achieved:
                    protection_type = "breakeven"
                elif trailing_should_be_active:
                    protection_type = "trailing stop (should be active)"
                elif breakeven_should_be_active:
                    protection_type = "breakeven (should be active)"
                else:
                    protection_type = "protection"
                log.info(f"⏸️ MAX HOLD TIME DEFERRED: {position.symbol} has {protection_type} active - allowing position to run longer (held: {holding_hours:.1f}h)")
                return None  # Continue holding - protection is active
            else:
                # No protection - enforce maximum holding time
                log.info(f"⏰ TIME EXIT: {position.symbol} maximum holding time reached ({holding_hours:.1f} hours) - no protection active")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.TIME_EXIT,
                    reasoning=f"Maximum holding time reached: {holding_hours:.1f} hours (no breakeven or trailing protection)"
                )
        
        # PRIORITY 5: Volume-based exit (low volume indicates lack of interest)
        if position.volume_ratio < self.config.low_liquidity_exit_threshold:
            log.info(f"📊 VOLUME EXIT: {position.symbol} volume too low ({position.volume_ratio:.2f}x average)")
            return StealthDecision(
                action="EXIT",
                exit_reason=ExitReason.VOLUME_EXIT,
                reasoning=f"Volume too low: {position.volume_ratio:.2f}x average"
            )
        
        return None
    
    def check_portfolio_health_for_emergency_exit(self) -> Dict[str, Any]:
        """
        Check overall portfolio health for emergency exit (Rev 00044 - Loss Prevention)
        
        Called 15 minutes after SO batch execution (8:00 AM PT) to detect bad days.
        If 3+ red flags detected, triggers emergency exit of all positions.
        
        Returns:
            dict: {
                'status': 'OK' | 'WARNING' | 'EMERGENCY',
                'red_flags': list of red flag descriptions,
                'action': 'CONTINUE' | 'CLOSE_WEAK' | 'CLOSE_ALL',
                'positions_to_close': list of position symbols
            }
        """
        try:
            if not self.active_positions:
                return {'status': 'OK', 'red_flags': [], 'action': 'CONTINUE', 'positions_to_close': []}
            
            positions = list(self.active_positions.values())
            total_positions = len(positions)

            # Require a reasonable sample size or runtime before declaring a bad day
            earliest_entry = min(p.entry_time for p in positions)
            runtime_minutes = (datetime.utcnow() - earliest_entry).total_seconds() / 60
            min_positions = getattr(self.config, "bad_day_min_positions", 3)
            min_runtime = getattr(self.config, "bad_day_min_runtime_minutes", 20.0)

            if total_positions < min_positions or runtime_minutes < min_runtime:
                log.info(
                    "⏸️ Skipping portfolio health check: %d positions, %.1f minutes runtime "
                    "(need ≥%d positions and ≥%.0f minutes)",
                    total_positions,
                    runtime_minutes,
                    min_positions,
                    min_runtime,
                )
                # Ensure rapid exits stay disabled until a real health check runs
                self._portfolio_health_determined = False
                self._rapid_exits_enabled = False
                return {
                    'status': 'INSUFFICIENT',
                    'red_flags': [],
                    'action': 'CONTINUE',
                    'positions_to_close': []
                }
            
            # Calculate portfolio metrics
            profitable_positions = len([p for p in positions if p.unrealized_pnl_pct > 0])
            losing_positions = len([p for p in positions if p.unrealized_pnl_pct < 0])
            
            avg_pnl_pct = sum([p.unrealized_pnl_pct for p in positions]) / total_positions
            avg_peak_pct = sum([(p.highest_price - p.entry_price) / p.entry_price * 100 for p in positions]) / total_positions
            
            # Count positions showing momentum (peak > +0.5%)
            momentum_positions = len([p for p in positions if ((p.highest_price - p.entry_price) / p.entry_price * 100) > 0.5])
            momentum_rate = (momentum_positions / total_positions) * 100
            
            # Calculate win rate
            win_rate = (profitable_positions / total_positions) * 100
            
            log.info(f"🛡️ 15-MIN PORTFOLIO HEALTH CHECK (Rev 00044):")
            log.info(f"   Positions: {total_positions} open")
            log.info(f"   Win Rate: {win_rate:.0f}% ({profitable_positions}W / {losing_positions}L)")
            log.info(f"   Avg P&L: {avg_pnl_pct:+.2f}%")
            log.info(f"   Avg Peak: {avg_peak_pct:+.2f}%")
            log.info(f"   Momentum Rate: {momentum_rate:.0f}% (peaked > +0.5%)")
            
            # DETECTION CRITERIA
            # Rev 00168: Enhanced red flag detection for better capital protection
            red_flags = []
            
            # Rev 00201: Use configurable health check thresholds
            win_rate_threshold = getattr(self.config, "health_check_win_rate_threshold", 35.0)
            avg_pnl_threshold = getattr(self.config, "health_check_avg_pnl_threshold", -0.005)
            momentum_threshold = getattr(self.config, "health_check_momentum_threshold", 40.0)
            peak_threshold = getattr(self.config, "health_check_peak_threshold", 0.008)
            
            # Red Flag 1: Low win rate (<threshold%)
            if win_rate < win_rate_threshold:
                red_flags.append(f"Low win rate ({win_rate:.0f}%)")
            
            # Red Flag 2: Average P&L deeply negative (<threshold%)
            # Rev 00168: Keep at -0.5% to avoid premature exits on recoverable days
            if avg_pnl_pct < avg_pnl_threshold:
                red_flags.append(f"Avg P&L negative ({avg_pnl_pct:+.2f}%)")
            
            # Red Flag 3: Low momentum (<threshold% showing movement)
            if momentum_rate < momentum_threshold:
                red_flags.append(f"Low momentum ({momentum_rate:.0f}% peaked)")
            
            # Red Flag 4: Average peak very low (<threshold%)
            if avg_peak_pct < peak_threshold:
                red_flags.append(f"Weak peaks ({avg_peak_pct:+.2f}% avg)")
            
            # Red Flag 5: ALL POSITIONS LOSING (Rev 00168 - CRITICAL)
            # If 100% of positions are losing, this is a clear red day signal
            if losing_positions == total_positions and total_positions >= 3:
                red_flags.append(f"All positions losing (100% losers - {total_positions} positions)")
                log.error(f"🚨 CRITICAL: ALL {total_positions} POSITIONS ARE LOSING - RED DAY CONFIRMED")
            
            # Rev 00045: SET RAPID EXIT FLAG based on portfolio health
            # This determines whether we continue using aggressive rapid exits
            self._portfolio_health_determined = True
            
            # EMERGENCY ACTION
            if len(red_flags) >= 3:
                # 3+ RED FLAGS = BAD DAY DETECTED
                log.error(f"🚨 BAD DAY DETECTED - {len(red_flags)} red flags:")
                for flag in red_flags:
                    log.error(f"   ❌ {flag}")
                
                log.error(f"🚨 EMERGENCY EXIT: Closing all positions immediately")
                
                # Rev 00045: ENABLE aggressive rapid exits for remaining/future trades
                self._rapid_exits_enabled = True
                log.error(f"🚨 RAPID EXITS: ENABLED for all remaining trades (portfolio sick)")
                
                return {
                    'status': 'EMERGENCY',
                    'red_flags': red_flags,
                    'action': 'CLOSE_ALL',
                    'positions_to_close': [p.symbol for p in positions]
                }
            
            elif len(red_flags) >= 2:
                # 2 RED FLAGS = WARNING (close weak positions only)
                log.warning(f"⚠️ WEAK DAY DETECTED - {len(red_flags)} red flags:")
                for flag in red_flags:
                    log.warning(f"   ⚠️ {flag}")
                
                log.warning(f"⚠️ CLOSING WEAK POSITIONS - Reducing risk")
                
                # Rev 00168: Keep threshold at -0.5% to avoid premature exits on recoverable days
                # Close positions already losing >0.5% (reverted from -0.3% - too strict, prevents recovery)
                weak_positions = [p.symbol for p in positions if p.unrealized_pnl_pct < -0.5]
                
                # Rev 00045: ENABLE aggressive rapid exits for remaining trades
                self._rapid_exits_enabled = True
                log.warning(f"⚠️ RAPID EXITS: ENABLED for remaining trades (portfolio weak)")
                
                return {
                    'status': 'WARNING',
                    'red_flags': red_flags,
                    'action': 'CLOSE_WEAK',
                    'positions_to_close': weak_positions
                }
            
            else:
                # 0-1 RED FLAGS = NORMAL
                log.info(f"✅ 15-MIN CHECK: Portfolio healthy ({len(red_flags)} red flags)")
                
                # Rev 00045: DISABLE rapid exits - let winners run!
                self._rapid_exits_enabled = False
                log.info(f"✅ RAPID EXITS: DISABLED (portfolio healthy - letting winners run)")
                
                return {
                    'status': 'OK',
                    'red_flags': red_flags,
                    'action': 'CONTINUE',
                    'positions_to_close': []
                }
            
        except Exception as e:
            log.error(f"Error in portfolio health check: {e}")
            return {'status': 'ERROR', 'red_flags': [], 'action': 'CONTINUE', 'positions_to_close': []}
    
    # Circuit breaker method removed (Rev 00046 analysis)
    # Analysis showed 6/10 days recovered from drawdowns
    # -5% threshold killed 2 winning days (Sept 29, Oct 6)
    # Decision: Rely on 15-min portfolio health check (Rev 00044) instead
    
    def check_rapid_exit_for_no_momentum(self, position: PositionState) -> Optional[StealthDecision]:
        """
        CONDITIONAL rapid exit system for trades showing no momentum (Rev 00045 - Smart Loss Prevention)
        
        CRITICAL IMPROVEMENT: Only applies aggressive rapid exits on BAD DAYS.
        On good days, lets winners run to avoid cutting them short.
        
        Checks portfolio health at 15 minutes:
        - If portfolio is HEALTHY (35%+ win rate, avg > -0.2%), DISABLE rapid exits
        - If portfolio is SICK (<35% win rate, avg < -0.5%), ENABLE aggressive rapid exits
        
        This gives us best of both worlds:
        - Good days: Keep all winners → baseline performance
        - Bad days: Exit losers early → improved loss prevention
        
        Checks if trade should be exited early in first 30 minutes:
        - No momentum after 15 minutes (peak < +0.3%)
        - Immediate reversal after 5 minutes (down -0.5%)
        - Can't recover after 20 minutes (still negative)
        
        Returns:
            StealthDecision to exit, or None to continue
        """
        holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
        
        # Rev 00201: Use configurable rapid exit time limit
        rapid_exit_time_limit_minutes = getattr(self.config, "rapid_exit_time_limit_minutes", 30.0)
        
        # Only apply rapid exit rules for first N minutes
        if holding_minutes > rapid_exit_time_limit_minutes:
            return None
        
        # Rev 00045: CHECK PORTFOLIO HEALTH to determine if we should use rapid exits
        # This prevents cutting winners short on good days!
        if hasattr(self, '_portfolio_health_determined'):
            # Health check already performed at 15 minutes
            if hasattr(self, '_rapid_exits_enabled'):
                if not self._rapid_exits_enabled:
                    # Portfolio is healthy - let trades develop naturally
                    # Track this position for aggregated "letting winners run" alert
                    if not hasattr(self, '_letting_winners_run'):
                        self._letting_winners_run = []
                    
                    # Add this position to the list (will be sent in aggregated alert)
                    if position.symbol not in [p['symbol'] for p in self._letting_winners_run]:
                        self._letting_winners_run.append({
                            'symbol': position.symbol,
                            'shares': position.quantity,
                            'entry_price': position.entry_price,
                            'peak_pct': ((position.highest_price - position.entry_price) / position.entry_price) * 100,
                            'current_pnl': position.unrealized_pnl_pct * 100,
                            'holding_minutes': holding_minutes,
                            'trade_id': getattr(position, 'trade_id', f"MOCK_{position.symbol}")
                        })
                    
                    return None  # Continue holding
                # else: Portfolio is sick - proceed with aggressive rapid exits below
        else:
            # Health check not yet performed (we're < 15 min into trading)
            # Apply CONSERVATIVE rapid exits only (protect against extreme cases)
            pass
        
        # Rev 00070: Calculate both as PERCENTAGE for consistency
        peak_pct = (position.highest_price - position.entry_price) / position.entry_price * 100
        current_pnl_pct = position.unrealized_pnl_pct * 100  # Convert decimal to percentage
        
        # Rev 00201: Use configurable rapid exit thresholds
        no_momentum_minutes = getattr(self.config, "rapid_exit_no_momentum_minutes", 15.0)
        no_momentum_peak_threshold = getattr(self.config, "rapid_exit_no_momentum_peak_threshold", 0.003)
        immediate_reversal_start = getattr(self.config, "rapid_exit_immediate_reversal_min_start", 5.0)
        immediate_reversal_end = getattr(self.config, "rapid_exit_immediate_reversal_min_end", 10.0)
        immediate_reversal_pnl = getattr(self.config, "rapid_exit_immediate_reversal_pnl_threshold", -0.005)
        weak_position_minutes = getattr(self.config, "rapid_exit_weak_position_minutes", 20.0)
        weak_position_pnl = getattr(self.config, "rapid_exit_weak_position_pnl_threshold", -0.003)
        weak_position_peak = getattr(self.config, "rapid_exit_weak_position_peak_threshold", 0.002)
        
        # Rule 1: No momentum after N minutes
        # ONLY applies if portfolio health is poor OR health not yet determined
        if holding_minutes >= no_momentum_minutes:
            # Check if we should apply this rule
            apply_rule = True
            if hasattr(self, '_rapid_exits_enabled') and not self._rapid_exits_enabled:
                apply_rule = False  # Portfolio healthy - skip
            
            if apply_rule and peak_pct < no_momentum_peak_threshold:
                log.warning(f"🚨 RAPID EXIT: {position.symbol} - No momentum after {no_momentum_minutes:.0f} min (peak: {peak_pct:+.2f}%)")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.STOP_LOSS,
                    reasoning=f"No momentum after {no_momentum_minutes:.0f} min (peak < {no_momentum_peak_threshold:.1%})"
                )
        
        # Rule 2: Immediate reversal (within N minutes)
        # Rev 00213: CRITICAL FIX - Only apply if position is actually losing (prevent premature exits on profitable positions)
        # Always apply this rule - it's a safety net for extreme reversals
        # Rev 00070: Fixed threshold from -0.5 (50%) to -0.5% (correct value)
        if holding_minutes >= immediate_reversal_start and holding_minutes < immediate_reversal_end:
            # Rev 00213: Only exit if position is actually losing (not profitable)
            if current_pnl_pct < immediate_reversal_pnl and current_pnl_pct < 0:
                log.warning(f"🚨 RAPID EXIT: {position.symbol} - Immediate reversal ({current_pnl_pct:+.2f}% in {immediate_reversal_start:.0f} min)")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.STOP_LOSS,
                    reasoning=f"Immediate reversal (down {current_pnl_pct:.2f}% in {immediate_reversal_start:.0f} min)"
                )
            elif current_pnl_pct >= 0:
                # Position is profitable - don't exit on immediate reversal rule
                log.debug(f"⏸️ Skipping immediate reversal exit for {position.symbol}: Position is profitable ({current_pnl_pct:+.2f}%)")
        
        # Rule 3: Can't break even after N minutes
        # ONLY applies if portfolio health is poor
        # Rev 00070: Fixed threshold from -0.3 (30%) to -0.3% (correct value)
        if holding_minutes >= weak_position_minutes:
            # Check if we should apply this rule
            apply_rule = True
            if hasattr(self, '_rapid_exits_enabled') and not self._rapid_exits_enabled:
                apply_rule = False  # Portfolio healthy - skip
            
            if apply_rule and current_pnl_pct < weak_position_pnl and peak_pct < weak_position_peak:
                log.warning(f"🚨 RAPID EXIT: {position.symbol} - Weak after {weak_position_minutes:.0f} min (P&L: {current_pnl_pct:+.2f}%, peak: {peak_pct:+.2f}%)")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.STOP_LOSS,
                    reasoning=f"Weak position after {weak_position_minutes:.0f} min (no recovery)"
                )
        
        return None  # Continue holding
    
    def _check_profit_timeout(self, position: PositionState) -> Optional[StealthDecision]:
        """
        Check for profit timeout - close unprotected profitable positions after 2.5 hours (Rev 00179)
        
        Rev 00179 Update: Timeout window stays open after 2.5 hours. Position closes as soon as
        it hits +0.2% profit, even if that's at 3 hours, 4 hours, or later. Timer based on
        position entry time, not when it first became profitable.
        
        Rev 00069: Enhanced logging to diagnose timeout failures
        """
        current_time = datetime.utcnow()
        pnl_pct = position.unrealized_pnl_pct
        
        # Calculate time since ENTRY (not since first profitable)
        time_since_entry = (current_time - position.entry_time).total_seconds() / 3600
        
        # Rev 00069: Log timeout check details for debugging
        # Rev 00150: Enhanced logging for activation criteria check
        # Rev 00154: Changed to INFO level for visibility
        log.info(f"🔍 PROFIT TIMEOUT CHECK: {position.symbol}")
        log.info(f"   Time held: {time_since_entry:.2f}h (threshold: {self.config.profit_timeout_hours}h)")
        log.info(f"   P&L: {pnl_pct:.4f} decimal ({pnl_pct*100:.2f}%) (threshold: {self.config.profit_timeout_min_pct:.4f})")
        log.info(f"   Breakeven achieved: {position.breakeven_achieved}")
        log.info(f"   Trailing activated: {position.trailing_activated}")
        log.info(f"   Stealth mode: {position.stealth_mode.value}")
        
        # Check if position has protection (breakeven or trailing activated)
        # Rev 00135: Defer timeout if EITHER breakeven OR trailing is active
        # Rev 00150: CRITICAL FIX - Also check if protection SHOULD be active (based on criteria)
        # This prevents premature exits when flags aren't set yet but criteria are met
        holding_minutes = (current_time - position.entry_time).total_seconds() / 60
        min_breakeven_activation_minutes = getattr(self.config, "min_breakeven_activation_minutes", 6.4)  # Rev 00196: Optimized from 3.5 to 6.4 minutes (median activation time)
        min_trailing_activation_minutes = getattr(self.config, "min_trailing_activation_minutes", 6.4)  # Rev 00196: Optimized from 3.5 to 6.4 minutes (median activation time)
        min_profit_for_trailing_pct = getattr(self.config, "min_profit_for_trailing_pct", 0.007)  # Rev 00196: Optimized from 0.5% to 0.7% (91.1% profit capture vs 75.4% at 0.5%)
        
        # Check if flags are set OR if criteria are met (should be active)
        breakeven_should_be_active = (
            not position.breakeven_achieved and
            pnl_pct >= self.config.breakeven_threshold_pct and
            holding_minutes >= min_breakeven_activation_minutes
        )
        trailing_should_be_active = (
            not position.trailing_activated and
            pnl_pct >= min_profit_for_trailing_pct and
            holding_minutes >= min_trailing_activation_minutes
        )
        
        has_protection = (
            position.breakeven_achieved or 
            position.trailing_activated or
            breakeven_should_be_active or
            trailing_should_be_active
        )
        
        # Rev 00150: Enhanced logging for activation criteria
        # Rev 00154: Changed to INFO level for visibility
        log.info(f"   Activation Criteria Check:")
        log.info(f"     - Breakeven threshold: {self.config.breakeven_threshold_pct:.4f} ({self.config.breakeven_threshold_pct*100:.2f}%)")
        log.info(f"     - Trailing threshold: {min_profit_for_trailing_pct:.4f} ({min_profit_for_trailing_pct*100:.2f}%)")
        log.info(f"     - Holding minutes: {holding_minutes:.1f} (breakeven min: {min_breakeven_activation_minutes}, trailing min: {min_trailing_activation_minutes})")
        log.info(f"     - Breakeven should be active: {breakeven_should_be_active}")
        log.info(f"     - Trailing should be active: {trailing_should_be_active}")
        log.info(f"     - Has protection: {has_protection}")
        
        if has_protection:
            # Position has protection (breakeven or trailing), no timeout needed
            if position.trailing_activated:
                protection_type = "trailing stop"
            elif position.breakeven_achieved:
                protection_type = "breakeven"
            elif trailing_should_be_active:
                protection_type = "trailing stop (should be active)"
            elif breakeven_should_be_active:
                protection_type = "breakeven (should be active)"
            else:
                protection_type = "protection"
            log.info(f"   ⏸️ Skipping timeout ({protection_type} active)")
            return None
        
        log.info(f"   ✅ No trailing protection - checking timeout window")
        
        # Check if timeout window has opened (2.5 hours since entry)
        if time_since_entry >= self.config.profit_timeout_hours:
            log.info(f"⏰ {position.symbol}: Timeout window OPEN ({time_since_entry:.2f}h >= {self.config.profit_timeout_hours}h)")
            
            # Timeout window is OPEN - close if we hit +0.1% profit (Rev 00179)
            if pnl_pct >= self.config.profit_timeout_min_pct:  # +0.1% minimum (Rev 00179)
                log.warning(f"⏰ PROFIT TIMEOUT: {position.symbol} reached +{pnl_pct:.4f} ({pnl_pct*100:.2f}%) after {time_since_entry:.1f} hours")
                log.warning(f"🚨 CLOSING POSITION (timeout window open ≥2.5h, profit ≥{self.config.profit_timeout_min_pct:.4f} threshold met)")
                
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.TIME_EXIT,
                    reasoning=f"Profit timeout: Position {time_since_entry:.1f}h old with +{pnl_pct:.2%} profit (≥+0.1% threshold)"
                )
            else:
                # Timeout window open but waiting for +0.1% profit
                log.info(f"⏳ {position.symbol}: Timeout window open ({time_since_entry:.1f}h), waiting for +{self.config.profit_timeout_min_pct:.4f} profit (current: {pnl_pct:.4f})")
                return None
        else:
            # Timeout window not open yet - still within 2.5 hours
            log.debug(f"   ⏸️ Timeout window not open yet ({time_since_entry:.2f}h < {self.config.profit_timeout_hours}h)")
            return None
    
    async def _check_scale_out_ladder(self, position: PositionState, market_data: Dict[str, Any]) -> Optional[StealthDecision]:
        """Check for partial profit ladder scale-outs (Chat recommendation)"""
        pnl_pct = position.unrealized_pnl_pct
        t1, t2 = self._scale_targets(position)
        
        # First scale-out at +3%
        if not position.scaled1 and pnl_pct >= t1 and position.orig_qty > 0:
            qty_to_scale = max(1, int(position.orig_qty * self.config.scale_out_t1_qty_pct))
            
            # Don't scale out more than current quantity
            if qty_to_scale >= position.quantity:
                return None
            
            # Execute scale-out
            if self.exec:
                await self.exec.scale_out(position, qty_to_scale, "scale_out_t1")
            
            # Update position
            position.quantity -= qty_to_scale
            position.scaled1 = True
            
            # Tighten stop to +0.3% above entry
            tightened_stop = position.entry_price * (1 + self.config.scale_out_stop_tighten_t1)
            position.current_stop_loss = max(position.current_stop_loss, tightened_stop)
            
            self.daily_stats['scale_outs_triggered'] += 1
            
            log.info(f"💰 SCALE-OUT T1: {position.symbol} sold {qty_to_scale} shares at {pnl_pct:.1%} profit")
            log.info(f"   Remaining: {position.quantity} shares, Stop tightened to ${tightened_stop:.2f}")
            
            return StealthDecision(
                action="TRAIL",
                new_stop_loss=tightened_stop,
                reasoning=f"Scale-out T1: Sold {qty_to_scale} shares at +{pnl_pct:.1%}"
            )
        
        # Second scale-out at +7%
        elif not position.scaled2 and pnl_pct >= t2 and position.orig_qty > 0:
            qty_to_scale = max(1, int(position.orig_qty * self.config.scale_out_t2_qty_pct))
            
            # Don't scale out more than current quantity
            if qty_to_scale >= position.quantity:
                return None
            
            # Execute scale-out
            if self.exec:
                await self.exec.scale_out(position, qty_to_scale, "scale_out_t2")
            
            # Update position
            position.quantity -= qty_to_scale
            position.scaled2 = True
            
            # Halve trailing distance for tighter control on remaining position
            current_trailing = self._calculate_trailing_distance(position, market_data)
            tightened_trailing = current_trailing * self.config.scale_out_stop_tighten_t2
            new_stop = position.current_price - (position.current_price * tightened_trailing)
            position.current_stop_loss = max(position.current_stop_loss, new_stop)
            
            self.daily_stats['scale_outs_triggered'] += 1
            
            log.info(f"💰 SCALE-OUT T2: {position.symbol} sold {qty_to_scale} shares at {pnl_pct:.1%} profit")
            log.info(f"   Remaining: {position.quantity} shares, Trailing tightened {tightened_trailing:.2%}")
            
            return StealthDecision(
                action="TRAIL",
                new_stop_loss=new_stop,
                reasoning=f"Scale-out T2: Sold {qty_to_scale} shares at +{pnl_pct:.1%}"
            )
        
        return None
    
    def _check_volume_surge(self, position: PositionState, market_data: Dict[str, Any]) -> bool:
        """Check for volume surge and determine if it's buying or selling pressure (ENHANCED SENSITIVITY)"""
        volume_ratio = position.volume_ratio
        
        log.debug(f"Volume surge check for {position.symbol}: volume_ratio={volume_ratio:.2f}, threshold={self.config.selling_volume_surge_threshold}")
        
        # Enhanced sensitivity: Check for selling volume surge with lower threshold
        if volume_ratio >= self.config.selling_volume_surge_threshold:
            # Check if price is declining or if volume is extremely high (potential selling pressure)
            price_change = (position.current_price - position.highest_price) / max(position.highest_price, 1e-9)
            log.debug(f"Volume surge check for {position.symbol}: volume_ratio={volume_ratio:.2f}, price_change={price_change:.4f}")
            
            # More sensitive detection: any pullback from high OR extreme volume OR moderate volume with decline
            # Rev 00170: Volume/price thresholds now configurable (was hardcoded 1.6 and -0.01)
            if (price_change < 0.0 or  # Any pullback from the high
                volume_ratio >= self.config.extreme_selling_volume_threshold or  # Extreme volume
                (volume_ratio >= self.config.volume_surge_moderate_threshold and 
                 price_change < self.config.price_decline_moderate_threshold)):  # Configurable moderate thresholds
                log.info(f"Selling volume surge detected for {position.symbol}: volume={volume_ratio:.2f}x, price_change={price_change:.2%}")
                return True
            else:
                log.debug(f"Volume surge but conditions not met: volume={volume_ratio:.2f}x, price_change={price_change:.2%}")
        
        # Additional check for immediate exit on extreme selling volume
        if volume_ratio >= self.config.extreme_selling_volume_threshold:
            log.info(f"Extreme selling volume detected for {position.symbol}: volume={volume_ratio:.2f}x (immediate exit threshold)")
            return True
        
        return False
    
    def _check_volume_exit(self, position: PositionState, market_data: Dict[str, Any]) -> Optional[StealthDecision]:
        """Check for volume-based exit conditions"""
        volume_ratio = position.volume_ratio
        
        # Low liquidity exit
        if volume_ratio < self.config.low_liquidity_exit_threshold:
            return StealthDecision(
                action="EXIT",
                exit_reason=ExitReason.VOLUME_EXIT,
                reasoning=f"Volume too low: {volume_ratio:.2f}x average"
            )
        
        return None
    
    def _apply_volume_protection(self, position: PositionState, market_data: Dict[str, Any]) -> Optional[StealthDecision]:
        """Apply volume-based protection with hysteresis & cooldown (Chat A+)"""
        now = datetime.utcnow()
        
        # Update peak volume ratio for hysteresis
        position.peak_volume_ratio = max(position.peak_volume_ratio, position.volume_ratio)
        
        # Check cooldown (Chat recommendation: prevent churn)
        cooldown_ok = (not position.last_tighten_ts) or \
                     ((now - position.last_tighten_ts).total_seconds() >= self.config.volume_tighten_cooldown_sec)
        
        # Check if volume surge exists AND we're near peak (hysteresis)
        near_peak = position.volume_ratio >= (position.peak_volume_ratio * self.config.volume_hysteresis_pct)
        
        log.debug(f"Volume protection for {position.symbol}: ratio={position.volume_ratio:.2f}, "
                 f"peak={position.peak_volume_ratio:.2f}, near_peak={near_peak}, cooldown_ok={cooldown_ok}")
        
        if not self._check_volume_surge(position, market_data):
            log.debug(f"No volume surge detected for {position.symbol}")
            return None
        
        if not cooldown_ok:
            log.debug(f"Volume tighten cooldown active for {position.symbol}")
            return None
        
        if not near_peak:
            log.debug(f"Volume not near peak for {position.symbol} ({position.volume_ratio:.2f} < {position.peak_volume_ratio * self.config.volume_hysteresis_pct:.2f})")
            return None
        
        # Calculate new stop with enhanced tightening (80% tightening for better protection)
        current_stop = position.current_stop_loss
        price_distance = position.current_price - current_stop
        tightened_distance = price_distance * self.config.volume_stop_tightening_pct
        new_stop = position.current_price - tightened_distance
        
        # Additional tightening for extreme volume surges
        if position.volume_ratio >= self.config.extreme_selling_volume_threshold:
            # Extra 20% tightening for extreme volume
            extra_tightening = tightened_distance * 0.2
            new_stop = position.current_price - (tightened_distance + extra_tightening)
            log.info(f"Extreme volume detected ({position.volume_ratio:.1f}x) - applying extra 20% tightening for {position.symbol}")
        
        # Ensure stop doesn't go below breakeven
        breakeven_stop = position.entry_price * (1 + self.config.breakeven_offset_pct)
        new_stop = max(new_stop, breakeven_stop)
        
        log.debug(f"Volume protection calculation for {position.symbol}: "
                 f"current_stop=${current_stop:.2f}, new_stop=${new_stop:.2f}, "
                 f"price_distance=${price_distance:.2f}, tightened_distance=${tightened_distance:.2f}")
        
        # Only move stop if it's tighter (higher for long positions)
        if new_stop > current_stop:
            # Update cooldown timestamp (Chat recommendation)
            position.last_tighten_ts = now
            
            tightening_pct = self.config.volume_stop_tightening_pct * 100
            log.info(f"Volume protection activated for {position.symbol}: "
                    f"Stop tightened from ${current_stop:.2f} to ${new_stop:.2f} "
                    f"({tightening_pct:.0f}% tightening during selling volume surge)")
            
            return StealthDecision(
                action="TRAIL",
                new_stop_loss=new_stop,
                stealth_mode=StealthMode.TRAILING,
                reasoning=f"Volume protection: Stop tightened to ${new_stop:.2f} ({tightening_pct:.0f}% tightening)"
            )
        else:
            log.debug(f"Volume protection not applied for {position.symbol}: new_stop (${new_stop:.2f}) not higher than current_stop (${current_stop:.2f})")
        
        return None
    
    def _activate_breakeven_protection(self, position: PositionState) -> StealthDecision:
        """Activate breakeven protection using breakeven_threshold_pct and breakeven_offset_pct from config"""
        entry_price = position.entry_price
        breakeven_stop = entry_price * (1 + self.config.breakeven_offset_pct)
        
        # Rev 00215: CRITICAL FIX - Ensure breakeven stop respects initial stop (floor stop)
        # Breakeven can move stop up but never below the opening bar protected stop
        opening_bar_protected_stop = position.initial_stop_loss
        
        if position.side == SignalSide.LONG:
            # For LONG: Use the higher stop (tighter = better profit protection)
            # But ensure it's not below the floor stop
            effective_breakeven_stop = max(breakeven_stop, opening_bar_protected_stop)
            
            if effective_breakeven_stop != breakeven_stop:
                log.warning(f"⚠️ Breakeven stop adjusted for {position.symbol}: ${breakeven_stop:.2f} → ${effective_breakeven_stop:.2f} (respecting floor stop ${opening_bar_protected_stop:.2f})")
                breakeven_stop = effective_breakeven_stop
        else:  # SHORT
            # For SHORT: Use the lower stop (tighter = better profit protection)
            effective_breakeven_stop = min(breakeven_stop, opening_bar_protected_stop)
            
            if effective_breakeven_stop != breakeven_stop:
                log.warning(f"⚠️ Breakeven stop adjusted for {position.symbol}: ${breakeven_stop:.2f} → ${effective_breakeven_stop:.2f} (respecting floor stop ${opening_bar_protected_stop:.2f})")
                breakeven_stop = effective_breakeven_stop
        
        self.stealth_metrics.breakeven_protected += 1
        self.daily_stats['breakeven_activations'] += 1
        
        log.info(f"🛡️ BREAKEVEN PROTECTION ACTIVATED for {position.symbol}: "
                f"Stop moved to ${breakeven_stop:.2f} (+{self.config.breakeven_offset_pct:.1%} profit locked, floor: ${opening_bar_protected_stop:.2f})")
        
        return StealthDecision(
            action="BREAKEVEN",
            new_stop_loss=breakeven_stop,
            stealth_mode=StealthMode.BREAKEVEN,
            reasoning=f"Breakeven protection: Stop moved to ${breakeven_stop:.2f} (+{self.config.breakeven_offset_pct:.1%}, respects floor ${opening_bar_protected_stop:.2f})"
        )
    
    def _check_trailing_activation(self, position: PositionState, market_data: Dict[str, Any]) -> Optional[StealthDecision]:
        """Check if trailing stop should be activated (Rev 00129 - OPTIMIZED FOR PROFITABLE TRADES)"""
        pnl_pct = position.unrealized_pnl_pct
        
        # Rev 00131: Trailing activation (OPTIMIZED FOR PROFIT CAPTURE)
        # Lowered threshold to 0.5% and time to 4 minutes to capture profits earlier
        holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
        min_trailing_activation_minutes = getattr(self.config, "min_trailing_activation_minutes", 6.4)  # Rev 00196: Optimized from 3.5 to 6.4 minutes (median activation time)
        
        # Rev 00154: Enhanced logging - all messages at INFO level for visibility
        min_profit_for_trailing_pct = getattr(self.config, "min_profit_for_trailing_pct", 0.007)  # Rev 00196: Optimized from 0.5% to 0.7% (91.1% profit capture vs 75.4% at 0.5%)
        
        log.info(f"🔍 Trailing Activation Evaluation: {position.symbol}")
        log.info(f"   - P&L: {pnl_pct:.4f} ({pnl_pct*100:.2f}%)")
        log.info(f"   - Holding Minutes: {holding_minutes:.1f} / {min_trailing_activation_minutes}")
        log.info(f"   - Min Profit Required: {min_profit_for_trailing_pct:.4f} ({min_profit_for_trailing_pct*100:.2f}%)")
        
        # Rev 00196: Don't activate trailing until 6.4 minutes to allow positions to develop (optimized from 3.5 min)
        if holding_minutes < min_trailing_activation_minutes:
            log.info(f"⏸️ Trailing activation deferred for {position.symbol}: {holding_minutes:.1f} min < {min_trailing_activation_minutes} min (allow position to develop)")
            return None
        
        # Rev 00196: Require minimum +0.7% profit before trailing activates (optimized from 0.5% - 91.1% profit capture vs 75.4% at 0.5%)
        # This allows trailing to activate at optimal profit level to maximize profit capture
        if pnl_pct < min_profit_for_trailing_pct:
            log.info(f"⏸️ Trailing activation deferred for {position.symbol}: {pnl_pct:.2%} < {min_profit_for_trailing_pct:.1%} (require minimum profit)")
            return None
        
        # Rev 00196: Activate trailing when profit exceeds +0.7% after 6.4 minutes (optimized settings)
        # This ensures trailing activates at optimal time to maximize profit capture
        log.info(f"✅ Trailing activation conditions MET for {position.symbol}: {pnl_pct:.2%} profit after {holding_minutes:.1f} min - ACTIVATING")
        return self._activate_trailing_stop(position, market_data)
    
    def _activate_trailing_stop(self, position: PositionState, market_data: Dict[str, Any]) -> StealthDecision:
        """Activate stealth trailing stop (Rev 00043 - Tiered Entry Bar Protection)"""
        
        # ========== TIERED ENTRY BAR PROTECTION (Rev 00043) ==========
        # Rev 00156: All entry bar protection values are now configurable
        # CRITICAL: Use wider stops for first N minutes, scaled to entry bar volatility
        holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
        
        if holding_minutes < self.config.entry_bar_protection_minutes:
            # Rev 00131: TIERED Entry Bar Protection (OPTIMIZED - WIDENED for volatile stocks)
            # Rev 00156: All thresholds and percentages are configurable
            # Widen stops for volatile stocks to prevent premature exits
            if position.entry_bar_volatility > self.config.vol_threshold_extreme:
                trailing_pct = self.config.entry_bar_protection_extreme_pct  # Configurable (default 9%)
                protection_level = "EXTREME"
            elif position.entry_bar_volatility > self.config.vol_threshold_high:
                trailing_pct = self.config.entry_bar_protection_high_pct  # Configurable (default 6%)
                protection_level = "HIGH"
            elif position.entry_bar_volatility > self.config.vol_threshold_moderate:
                trailing_pct = self.config.entry_bar_protection_moderate_pct  # Configurable (default 3.5%)
                protection_level = "MODERATE"
            else:
                trailing_pct = self.config.entry_bar_protection_low_pct  # Configurable (default 2.5%)
                protection_level = "LOW"
            
            log.info(f"🛡️ Entry Bar Protection ({protection_level}): {position.symbol} "
                    f"({holding_minutes:.1f} min, entry vol {position.entry_bar_volatility:.2f}%) - Using {trailing_pct*100:.1f}% stop")
        else:
            # Rev 00129: Calculate adaptive trailing distance based on entry bar volatility AND profit
            # Rev 00144: Profit-based tightening is now built into _calculate_trailing_distance
            trailing_pct = self._calculate_trailing_distance(position, market_data)
        
        # Calculate new stop loss
        new_stop_loss = position.highest_price * (1 - trailing_pct)
        
        # Apply stealth offset (make stop less obvious) - Rev 00156: Configurable
        stealth_offset = position.highest_price * (trailing_pct * self.config.stealth_offset_multiplier)
        new_stop_loss -= stealth_offset
        
        # Rev 00183: CRITICAL FIX - Respect opening bar protected stop (floor stop)
        # The opening bar protected stop is stored in initial_stop_loss and must NEVER be violated
        # This prevents stops from being set too tight relative to entry bar volatility
        opening_bar_protected_stop = position.initial_stop_loss
        
        # Rev 00194: CRITICAL FIX - Trailing stops should NEVER use breakeven as floor
        # Breakeven is a separate protection mechanism that should only activate to SAVE gains
        # When trailing activates, it should work independently and allow positions to develop
        # Opening bar protection provides the initial floor, trailing provides dynamic protection
        # Breakeven should NOT interfere with trailing stops - it should only activate separately
        
        # First, ensure stop respects opening bar protected stop (always)
        if position.side == SignalSide.LONG:
            new_stop_loss = max(new_stop_loss, opening_bar_protected_stop)
        else:  # SHORT
            new_stop_loss = min(new_stop_loss, opening_bar_protected_stop)
        
        # Rev 00194: DO NOT use breakeven as floor for trailing stops
        # Trailing stops should work independently based on entry bar protection percentages
        # Breakeven is a separate mechanism that activates when position has meaningful profit (>0.3%)
        # When trailing activates, let it work without breakeven interference
        log.info(f"🚀 Trailing stop calculated for {position.symbol}: ${new_stop_loss:.2f} (NO breakeven floor - allowing position to develop)")
        
        self.stealth_metrics.trailing_activated += 1
        self.daily_stats['trailing_activations'] += 1
        
        log.info(f"🚀 TRAILING STOP ACTIVATED for {position.symbol}: "
                f"Stop=${new_stop_loss:.2f} (trailing {trailing_pct:.1%}, opening bar floor=${opening_bar_protected_stop:.2f})")
        
        return StealthDecision(
            action="TRAIL",
            new_stop_loss=new_stop_loss,
            stealth_mode=StealthMode.TRAILING,
            reasoning=f"Stealth trailing activated: Stop=${new_stop_loss:.2f} (trailing {trailing_pct:.1%})"
        )
    
    def _update_trailing_stop(self, position: PositionState, market_data: Dict[str, Any]) -> StealthDecision:
        """Update existing trailing stop with side-aware math and floor guards (Rev 00043 - Entry Bar Protection)"""
        # Rev 00182: CRITICAL FIX - Check if price has fallen below trailing stop BEFORE updating
        # This ensures trailing stop exits trigger correctly when price drops below the stop
        current_price = position.current_price
        current_stop_loss = position.current_stop_loss
        
        # Rev 00199: Enhanced logging - log all stop values at start of update check
        log.info(f"🔄 TRAILING STOP UPDATE CHECK: {position.symbol} | Price: ${current_price:.2f} | Peak: ${position.highest_price:.2f} | Current Stop: ${current_stop_loss:.2f} | Breakeven: {position.breakeven_achieved} | Trailing: {position.trailing_activated}")
        
        # Check if trailing stop has been hit (side-aware)
        if position.side == SignalSide.LONG:
            if current_price <= current_stop_loss:
                # Rev 00199: Enhanced logging - log which stop triggered exit
                stop_type = "TRAILING_STOP" if position.trailing_activated else ("BREAKEVEN_STOP" if position.breakeven_achieved else "STOP_LOSS")
                log.warning(f"🚨 TRAILING STOP HIT: {position.symbol} @ ${current_price:.2f} <= ${current_stop_loss:.2f} | Stop Type: {stop_type} | Breakeven: {position.breakeven_achieved} | Trailing: {position.trailing_activated}")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.TRAILING_STOP,
                    reasoning=f"Trailing stop hit: ${current_price:.2f} <= ${current_stop_loss:.2f} (Stop Type: {stop_type})"
                )
        else:  # SHORT
            if current_price >= current_stop_loss:
                # Rev 00199: Enhanced logging - log which stop triggered exit
                stop_type = "TRAILING_STOP" if position.trailing_activated else ("BREAKEVEN_STOP" if position.breakeven_achieved else "STOP_LOSS")
                log.warning(f"🚨 TRAILING STOP HIT: {position.symbol} @ ${current_price:.2f} >= ${current_stop_loss:.2f} | Stop Type: {stop_type} | Breakeven: {position.breakeven_achieved} | Trailing: {position.trailing_activated}")
                return StealthDecision(
                    action="EXIT",
                    exit_reason=ExitReason.TRAILING_STOP,
                    reasoning=f"Trailing stop hit: ${current_price:.2f} >= ${current_stop_loss:.2f} (Stop Type: {stop_type})"
                )
        
        # Ensure fresh peak (Chat fix: update highest_price before computing)
        position.highest_price = max(position.highest_price, position.current_price)
        position.lowest_price = min(position.lowest_price, position.current_price)
        
        # Side-aware peak selection
        peak = position.highest_price if position.side == SignalSide.LONG else position.lowest_price
        
        # Rev 00182: CRITICAL FIX - Check if price has fallen below trailing stop even when not at new high
        # This ensures trailing stop exits trigger correctly when price drops below the stop
        # Only update if at new favorable price
        at_new_extreme = (position.side == SignalSide.LONG and position.current_price >= peak) or \
                        (position.side == SignalSide.SHORT and position.current_price <= peak)
        
        if not at_new_extreme:
            # Rev 00182: Even when not at new high, check if price has fallen below trailing stop
            # This is critical for triggering exits when price drops below the stop
            if position.side == SignalSide.LONG:
                if current_price <= current_stop_loss:
                    # Rev 00199: Enhanced logging - log which stop triggered exit
                    stop_type = "TRAILING_STOP" if position.trailing_activated else ("BREAKEVEN_STOP" if position.breakeven_achieved else "STOP_LOSS")
                    log.warning(f"🚨 TRAILING STOP HIT (price not at new high): {position.symbol} @ ${current_price:.2f} <= ${current_stop_loss:.2f} | Stop Type: {stop_type} | Peak: ${peak:.2f}")
                    return StealthDecision(
                        action="EXIT",
                        exit_reason=ExitReason.TRAILING_STOP,
                        reasoning=f"Trailing stop hit: ${current_price:.2f} <= ${current_stop_loss:.2f} (Stop Type: {stop_type})"
                    )
            else:  # SHORT
                if current_price >= current_stop_loss:
                    # Rev 00199: Enhanced logging - log which stop triggered exit
                    stop_type = "TRAILING_STOP" if position.trailing_activated else ("BREAKEVEN_STOP" if position.breakeven_achieved else "STOP_LOSS")
                    log.warning(f"🚨 TRAILING STOP HIT (price not at new low): {position.symbol} @ ${current_price:.2f} >= ${current_stop_loss:.2f} | Stop Type: {stop_type} | Peak: ${peak:.2f}")
                    return StealthDecision(
                        action="EXIT",
                        exit_reason=ExitReason.TRAILING_STOP,
                        reasoning=f"Trailing stop hit: ${current_price:.2f} >= ${current_stop_loss:.2f} (Stop Type: {stop_type})"
                    )
            
            # Rev 00199: Enhanced logging - log when stop update is skipped
            log.info(f"⏸️ TRAILING STOP UPDATE SKIPPED: {position.symbol} | Price: ${current_price:.2f} | Peak: ${peak:.2f} | Current Stop: ${current_stop_loss:.2f} | Reason: Price not at new {'high' if position.side == SignalSide.LONG else 'low'}, stop not hit")
            return StealthDecision(
                action="HOLD",
                reasoning=f"Price not at new {'high' if position.side == SignalSide.LONG else 'low'}, stop not hit"
            )
        
        # ========== TIERED ENTRY BAR PROTECTION (Rev 00043) ==========
        # Rev 00156: All entry bar protection values are now configurable
        # CRITICAL: Use wider stops for first N minutes, scaled to entry bar volatility
        # Entry bars with high volatility need wider protection
        # Entry bars with low volatility only need minimal protection
        # This prevents entry bar noise from killing trades while minimizing downside
        
        holding_minutes = (datetime.utcnow() - position.entry_time).total_seconds() / 60
        
        if holding_minutes < self.config.entry_bar_protection_minutes:
            # TIERED Entry Bar Protection based on entry bar volatility - Rev 00156: Configurable
            if position.entry_bar_volatility > self.config.vol_threshold_extreme:
                trailing_pct = self.config.entry_bar_protection_extreme_pct  # Configurable (default 8%)
                protection_level = "EXTREME"
            elif position.entry_bar_volatility > self.config.vol_threshold_high:
                trailing_pct = self.config.entry_bar_protection_high_pct  # Configurable (default 5%)
                protection_level = "HIGH"
            elif position.entry_bar_volatility > self.config.vol_threshold_moderate:
                trailing_pct = self.config.entry_bar_protection_moderate_pct  # Configurable (default 3%)
                protection_level = "MODERATE"
            else:
                trailing_pct = self.config.entry_bar_protection_low_pct  # Configurable (default 2%)
                protection_level = "LOW"
            
            log.info(f"🛡️ Entry Bar Protection ({protection_level}): {position.symbol} "
                    f"({holding_minutes:.1f} min, entry vol {position.entry_bar_volatility:.2f}%) - Using {trailing_pct*100:.1f}% wide stop")
        else:
            # Rev 00147: Use _calculate_trailing_distance() for adaptive trailing (same as activation)
            # This ensures consistent trailing logic with volatility-based and profit-based adjustments
            trailing_pct = self._calculate_trailing_distance(position, market_data)
        
        # Apply mode-specific trailing profile (Chat recommendation)
        trailing_pct = self._apply_trailing_profile(position.stealth_mode, trailing_pct)
        
        # Side-aware trailing calculation
        if position.side == SignalSide.LONG:
            new_stop_loss = peak * (1 - trailing_pct)
            # Apply stealth offset (smaller for tighter trailing) - Rev 00156: Configurable
            stealth_offset = peak * (trailing_pct * self.config.stealth_offset_multiplier_active)
            new_stop_loss -= stealth_offset
            # Rev 00194: CRITICAL FIX - Trailing stops should NEVER use breakeven as floor
            # Breakeven is a separate protection mechanism that should only activate to SAVE gains
            # When trailing updates, it should work independently and allow positions to develop
            # Opening bar protection provides the initial floor, trailing provides dynamic protection
            # Breakeven should NOT interfere with trailing stops - it should only activate separately
            
            # Ensure stop only moves up
            if new_stop_loss <= position.current_stop_loss:
                # Rev 00199: Enhanced logging - log when stop update is skipped because new stop not higher
                log.info(f"⏸️ TRAILING STOP UPDATE SKIPPED: {position.symbol} | Current Stop: ${position.current_stop_loss:.2f} | New Stop: ${new_stop_loss:.2f} | Peak: ${peak:.2f} | Reason: New stop not higher than current")
                return StealthDecision(action="HOLD", reasoning="Stop not higher")
        else:  # SHORT
            new_stop_loss = peak * (1 + trailing_pct)
            # Apply stealth offset - Rev 00156: Configurable
            stealth_offset = peak * (trailing_pct * self.config.stealth_offset_multiplier_active)
            new_stop_loss += stealth_offset
            # Apply floor guards
            min_dist = self._min_stop_distance(position)
            breakeven_stop = position.entry_price * (1 - self.config.breakeven_offset_pct)
            new_stop_loss = min(new_stop_loss, position.current_price + min_dist, breakeven_stop)
            # Ensure stop only moves down
            if new_stop_loss >= position.current_stop_loss:
                return StealthDecision(action="HOLD", reasoning="Stop not lower")
        
        # Check for explosive/moon mode with confidence-based thresholds
        pnl_pct = position.unrealized_pnl_pct
        confidence = position.confidence
        
        # Get confidence-adjusted thresholds
        moon_threshold = self._get_confidence_adjusted_threshold(
            self.config.moon_take_profit_pct, 
            confidence, 
            "moon"
        )
        explosive_threshold = self._get_confidence_adjusted_threshold(
            self.config.explosive_take_profit_pct, 
            confidence, 
            "explosive"
        )
        
        if pnl_pct >= moon_threshold:
            position.stealth_mode = StealthMode.MOON
            self.stealth_metrics.moon_captured += 1
            log.info(f"Moon mode activated for {position.symbol} (confidence {confidence:.1%}): {pnl_pct:.1%} >= {moon_threshold:.1%}")
        elif pnl_pct >= explosive_threshold:
            position.stealth_mode = StealthMode.EXPLOSIVE
            self.stealth_metrics.explosive_captured += 1
            log.info(f"Explosive mode activated for {position.symbol} (confidence {confidence:.1%}): {pnl_pct:.1%} >= {explosive_threshold:.1%}")
        
        # Apply mode-specific TP multiplier (Chat recommendation)
        tp_mult = self._get_tp_multiplier_for_mode(position.stealth_mode)
        if tp_mult > 1.0:
            enhanced_tp = position.take_profit * tp_mult
            log.info(f"Mode {position.stealth_mode.value} enhances TP: ${position.take_profit:.2f} → ${enhanced_tp:.2f}")
        
        # Rev 00199: Enhanced logging - log detailed stop update information
        log.info(f"🔄 TRAILING STOP CALCULATED: {position.symbol} | Price: ${current_price:.2f} | Peak: ${peak:.2f} | Current Stop: ${current_stop_loss:.2f} | New Stop: ${new_stop_loss:.2f} | Trailing: {trailing_pct:.1%} | Mode: {position.stealth_mode.value}")
        log.info(f"Stealth trailing updated for {position.symbol}: "
                f"Stop=${new_stop_loss:.2f} (trailing {trailing_pct:.1%}, mode={position.stealth_mode.value})")
        
        return StealthDecision(
            action="TRAIL",
            new_stop_loss=new_stop_loss,
            stealth_mode=position.stealth_mode,
            reasoning=f"Stealth trailing updated: Stop=${new_stop_loss:.2f} (trailing {trailing_pct:.1%})"
        )
    
    def _calculate_trailing_distance(self, position: PositionState, market_data: Dict[str, Any]) -> float:
        """Calculate adaptive trailing distance combining volatility-based and profit-based adaptive trailing (Rev 00130)"""
        # Rev 00129: Adaptive trailing based on entry_bar_volatility
        # Rev 00130: ADD profit-based adaptive trailing and use the WIDER of the two (more protection)
        entry_vol = position.entry_bar_volatility if hasattr(position, 'entry_bar_volatility') else self.config.default_entry_bar_volatility
        pnl_pct = position.unrealized_pnl_pct
        
        # Rev 00131: OPTIMIZED TRAILING DISTANCE using ATR and dynamic volatility
        # Rev 00156: All volatility thresholds and trailing percentages are now configurable
        # 1. VOLATILITY-BASED ADAPTIVE TRAILING (WIDENED for better protection)
        if entry_vol > self.config.vol_threshold_extreme:
            # Very volatile stocks (>6%): Use configurable trailing (default 2.5%)
            volatility_trailing_pct = self.config.trailing_vol_extreme_pct
            volatility_tier = "EXTREME"
        elif entry_vol > self.config.vol_threshold_high:
            # High volatility stocks (3-6%): Use configurable trailing (default 2.0%)
            volatility_trailing_pct = self.config.trailing_vol_high_pct
            volatility_tier = "HIGH"
        elif entry_vol > self.config.vol_threshold_moderate:
            # Moderate volatility stocks (2-3%): Use configurable trailing (default 1.75%)
            volatility_trailing_pct = self.config.trailing_vol_moderate_pct
            volatility_tier = "MODERATE"
        else:
            # Low volatility stocks (<2%): Use configurable trailing (default 1.5%)
            volatility_trailing_pct = self.config.trailing_vol_low_pct
            volatility_tier = "LOW"
        
        # 2. PROFIT-BASED ADAPTIVE TRAILING (Rev 00131 - OPTIMIZED FOR MAXIMUM PROFIT CAPTURE)
        # Rev 00156: All profit thresholds and trailing percentages are now configurable
        # WIDER trailing for bigger profits to let winners run (Strategy.md line 551-555)
        # This matches the backtested configuration that achieved +73.69% weekly return
        if pnl_pct >= self.config.profit_threshold_max:
            # 12%+ profit: Use configurable trailing (default 1.5% - maximize profit capture)
            profit_trailing_pct = self.config.trailing_profit_max_pct
            profit_tier = "MAX_PROFIT"
        elif pnl_pct >= self.config.profit_threshold_high:
            # 7-12% profit: Use configurable trailing (default 2.0% - protect gains)
            profit_trailing_pct = self.config.trailing_profit_high_pct
            profit_tier = "PROTECT_GAINS"
        elif pnl_pct >= self.config.profit_threshold_medium:
            # 3-7% profit: Use configurable trailing (default 2.5% - let move develop)
            profit_trailing_pct = self.config.trailing_profit_medium_pct
            profit_tier = "LET_DEVELOP"
        else:
            # <3% profit: Use volatility-based trailing (not enough profit yet)
            profit_trailing_pct = volatility_trailing_pct
            profit_tier = "VOLATILITY_BASED"
        
        # 3. USE THE WIDER OF THE TWO (MORE PROTECTION - Strategy.md line 556)
        # This allows winners to run while protecting against reversals
        # Matches backtested configuration: "Uses the WIDER of the two (more protection)"
        trailing_pct = max(volatility_trailing_pct, profit_trailing_pct)
        
        # Rev 00214: WIDEN trailing distance for small profits (<1%) to prevent premature exits
        # Small profits need more room to develop before being stopped out
        if pnl_pct < 0.01:  # Less than 1% profit
            min_trailing_for_small_profit = 0.025  # Minimum 2.5% trailing for small profits
            if trailing_pct < min_trailing_for_small_profit:
                log.info(f"🔒 Widened trailing for {position.symbol}: {trailing_pct:.1%} → {min_trailing_for_small_profit:.1%} (small profit {pnl_pct:.2%})")
                trailing_pct = min_trailing_for_small_profit
        
        # 4. ATR-BASED FLOOR GUARD (Rev 00131 - INCREASED to 1.0× ATR)
        # Ensure trailing distance is at least 1.0× ATR to avoid stops that are too tight
        if position.atr > 0:
            atr_floor_pct = (self.config.atr_stop_k * position.atr) / max(position.current_price, 1e-9)
            trailing_pct = max(trailing_pct, atr_floor_pct)
            log.debug(f"📊 ATR floor guard for {position.symbol}: {atr_floor_pct:.2%} (ATR={position.atr:.2f}, price=${position.current_price:.2f}, 1.0× ATR)")
        
        log.debug(f"📊 Adaptive trailing for {position.symbol}: Vol={volatility_trailing_pct:.2%} ({volatility_tier}), "
                 f"Profit={profit_trailing_pct:.2%} ({profit_tier}), Final={trailing_pct:.2%} (P&L={pnl_pct:.2%}, EntryVol={entry_vol:.1%})")
        
        # Apply floor and ceiling guards
        trailing_pct = max(self.config.min_trailing_pct, min(trailing_pct, self.config.max_trailing_pct))
        
        return trailing_pct
    
    def _check_take_profit_update(self, position: PositionState, market_data: Dict[str, Any]) -> Optional[StealthDecision]:
        """Check if take profit should be updated with confidence-based and profit-based adjustments (Rev 00130)"""
        pnl_pct = position.unrealized_pnl_pct
        current_take_profit = position.take_profit
        confidence = position.confidence
        
        # Rev 00130: PROFIT-BASED TAKE PROFIT ADJUSTMENTS
        # Adjust TP based on current profit to capture more on big moves
        profit_based_tp_pct = None
        # Rev 00156: Use configurable profit thresholds for take profit adjustments
        if pnl_pct >= self.config.profit_threshold_max:
            # 12%+ profit: Increase TP (configurable - default 10%)
            # Rev 00170: Now configurable (was hardcoded 0.10)
            profit_based_tp_pct = self.config.profit_based_tp_moon_pct
            profit_tier = "MOON"
        elif pnl_pct >= self.config.profit_threshold_high:
            # 7-12% profit: Increase TP (configurable - default 5%)
            # Rev 00170: Now configurable (was hardcoded 0.05)
            profit_based_tp_pct = self.config.profit_based_tp_strong_pct
            profit_tier = "STRONG"
        elif pnl_pct >= self.config.profit_threshold_medium:
            # 3-7% profit: Keep TP (configurable - default 3%)
            # Rev 00170: Now configurable (was hardcoded 0.03)
            profit_based_tp_pct = self.config.profit_based_tp_standard_pct
            profit_tier = "STANDARD"
        else:
            # <3% profit: Use base TP (not enough profit yet)
            profit_based_tp_pct = self.config.base_take_profit_pct
            profit_tier = "BASE"
        
        # Calculate confidence-based thresholds
        explosive_threshold = self._get_confidence_adjusted_threshold(
            self.config.explosive_take_profit_pct, 
            confidence, 
            "explosive"
        )
        moon_threshold = self._get_confidence_adjusted_threshold(
            self.config.moon_take_profit_pct, 
            confidence, 
            "moon"
        )
        
        # Use the HIGHER of profit-based or confidence-based TP
        # This ensures we capture maximum profit on big moves
        base_tp_pct = max(profit_based_tp_pct, self.config.base_take_profit_pct)
        
        # Update take profit for explosive moves (confidence-adjusted)
        if pnl_pct >= explosive_threshold:
            # Calculate confidence-based take profit multiplier
            multiplier = self._get_confidence_take_profit_multiplier(confidence)
            confidence_tp_pct = explosive_threshold * multiplier
            # Use the higher of profit-based or confidence-based
            new_take_profit_pct = max(base_tp_pct, confidence_tp_pct)
            new_take_profit = position.entry_price * (1 + new_take_profit_pct)
            
            if new_take_profit > current_take_profit:
                return StealthDecision(
                    action="TRAIL",
                    new_take_profit=new_take_profit,
                    reasoning=f"Take profit updated for explosive move (profit-based: {profit_tier} {profit_based_tp_pct:.1%}, confidence {confidence:.1%}): ${new_take_profit:.2f} ({new_take_profit_pct:.1%})"
                )
        
        # Update take profit for moon moves (confidence-adjusted)
        if pnl_pct >= moon_threshold:
            # Calculate confidence-based take profit multiplier
            multiplier = self._get_confidence_take_profit_multiplier(confidence)
            confidence_tp_pct = moon_threshold * multiplier
            # Use the higher of profit-based or confidence-based
            new_take_profit_pct = max(base_tp_pct, confidence_tp_pct)
            new_take_profit = position.entry_price * (1 + new_take_profit_pct)
            
            if new_take_profit > current_take_profit:
                return StealthDecision(
                    action="TRAIL",
                    new_take_profit=new_take_profit,
                    reasoning=f"Take profit updated for moon move (profit-based: {profit_tier} {profit_based_tp_pct:.1%}, confidence {confidence:.1%}): ${new_take_profit:.2f} ({new_take_profit_pct:.1%})"
                )
        
        # Rev 00130: Update TP based on profit tier even if not explosive/moon
        if profit_based_tp_pct > self.config.base_take_profit_pct:
            new_take_profit = position.entry_price * (1 + profit_based_tp_pct)
            if new_take_profit > current_take_profit:
                return StealthDecision(
                    action="TRAIL",
                    new_take_profit=new_take_profit,
                    reasoning=f"Take profit updated based on profit tier ({profit_tier}): ${new_take_profit:.2f} ({profit_based_tp_pct:.1%})"
                )
        
        return None
    
    def _get_confidence_adjusted_threshold(self, base_threshold: float, confidence: float, move_type: str) -> float:
        """Get confidence-adjusted threshold for explosive/moon moves"""
        if confidence >= self.config.ultra_confidence_threshold:
            if move_type == "moon":
                return self.config.ultra_confidence_moon_threshold
            else:
                return base_threshold * 0.8  # Lower threshold for ultra confidence
        elif confidence >= self.config.high_confidence_threshold:
            if move_type == "moon":
                return self.config.high_confidence_moon_threshold
            else:
                return base_threshold * 0.9  # Slightly lower threshold for high confidence
        else:
            return base_threshold
    
    def _get_confidence_take_profit_multiplier(self, confidence: float) -> float:
        """Get confidence-based take profit multiplier"""
        if confidence >= self.config.ultra_confidence_threshold:
            return self.config.ultra_confidence_take_profit_multiplier
        elif confidence >= self.config.high_confidence_threshold:
            return self.config.high_confidence_take_profit_multiplier
        else:
            return 1.0
    
    async def _remove_position(self, symbol: str, exit_reason: ExitReason, send_alert: bool = True):
        """Remove position from stealth management
        
        Args:
            symbol: Symbol to remove
            exit_reason: Reason for exit
            send_alert: Whether to send individual exit alert (False for batch operations)
        """
        if symbol in self.active_positions:
            position = self.active_positions[symbol]
            
            # Rev 00117: Send exit alert for both Demo and Live modes
            # Rev 00126: Enhanced error handling and logging for exit alerts
            # Rev 00136: Add send_alert parameter to prevent duplicate alerts during batch operations
            if self.alert_manager and send_alert:
                try:
                    # Calculate holding time
                    holding_time_minutes = 0
                    if hasattr(position, 'entry_time') and position.entry_time:
                        time_diff = datetime.utcnow() - position.entry_time
                        holding_time_minutes = int(time_diff.total_seconds() / 60)
                    
                    # Calculate P&L
                    pnl_dollars = position.unrealized_pnl
                    pnl_percent = position.unrealized_pnl_pct * 100  # Convert to percentage
                    
                    # Get trade_id if available
                    trade_id = getattr(position, 'trade_id', getattr(position, 'position_id', f"{self.mode}_{symbol}"))
                    
                    # Send exit alert
                    alert_result = await self.alert_manager.send_trade_exit_alert(
                        symbol=symbol,
                        side="SELL",  # Closing position
                        quantity=position.quantity,
                        entry_price=position.entry_price,
                        exit_price=position.current_price,
                        pnl_dollars=pnl_dollars,
                        pnl_percent=pnl_percent,
                        exit_reason=exit_reason.value,
                        holding_time_minutes=holding_time_minutes,
                        mode=self.mode,
                        trade_id=trade_id
                    )
                    if alert_result:
                        log.info(f"📱 Exit alert sent for {symbol} ({self.mode} mode) - {exit_reason.value}")
                    else:
                        log.warning(f"⚠️ Exit alert returned False for {symbol} - alert may not have been sent")
                except Exception as e:
                    log.error(f"❌ Failed to send exit alert for {symbol}: {e}", exc_info=True)
                    log.error(f"   Alert manager: {self.alert_manager}, Mode: {self.mode}, Exit reason: {exit_reason.value}")
            else:
                log.error(f"❌ Cannot send exit alert for {symbol}: alert_manager is None!")
                log.error(f"   This should not happen - alert_manager should be set during initialization")
            
            # Update metrics
            self.stealth_metrics.total_pnl += position.unrealized_pnl
            self.daily_stats['exits_triggered'] += 1
            self.daily_stats['total_pnl'] += position.unrealized_pnl
            
            # Update exit reason metrics
            if exit_reason == ExitReason.STOP_LOSS:
                self.stealth_metrics.stop_loss_exits += 1
            elif exit_reason == ExitReason.TAKE_PROFIT:
                self.stealth_metrics.take_profit_exits += 1
            elif exit_reason == ExitReason.TRAILING_STOP:
                self.stealth_metrics.trailing_exits += 1
            elif exit_reason == ExitReason.BREAKEVEN_PROTECTION:
                self.stealth_metrics.breakeven_exits += 1
            
            # Rev 00133: Record exit in monitoring collector (TEMPORARY - for exit optimization)
            if self.exit_monitor:
                try:
                    self.exit_monitor.record_exit(
                        symbol=symbol,
                        exit_price=position.current_price,
                        exit_reason=exit_reason.value,
                        final_pnl=position.unrealized_pnl,
                        final_pnl_pct=position.unrealized_pnl_pct
                    )
                except Exception as e:
                    log.debug(f"Exit monitoring record skipped for {symbol}: {e}")
            
            # Add to history
            self.position_history.append(position)
            
            # Remove from active positions
            del self.active_positions[symbol]
            
            log.info(f"Removed position {symbol} from stealth management: "
                    f"Exit reason={exit_reason.value}, PnL=${position.unrealized_pnl:.2f}")
    
    def get_active_positions(self) -> Dict[str, PositionState]:
        """
        Get all active positions (Rev 00180d - CRITICAL FIX)
        
        Returns:
            Dictionary of symbol -> PositionState for all active positions
        """
        return self.active_positions
    
    def get_position_state(self, symbol: str) -> Optional[PositionState]:
        """
        Get current state of a position (DEPRECATED - use view() instead)
        
        DEPRECATED: Use view() for read-only access.
        """
        return self.active_positions.get(symbol)
    
    def view(self, symbol: str) -> Optional[PositionState]:
        """
        READ-ONLY access to position state.
        
        For managers and other modules to VIEW current stops/TP without modifying.
        
        ⚠️ WARNING: DO NOT write to the returned object!
        ⚠️ This is READ-ONLY access for monitoring purposes only.
        ⚠️ Only Prime Stealth Trailing System may write to stops/TP.
        
        Args:
            symbol: Symbol to view
        
        Returns:
            PositionState if found, None otherwise
        """
        return self.active_positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, PositionState]:
        """Get all active positions"""
        return self.active_positions.copy()
    
    # ========================================================================
    # POSITION REBALANCING (Rev 00176)
    # ========================================================================
    
    def evaluate_worst_position_for_orr(
        self,
        orr_signal: Dict[str, Any],
        available_capital: float,
        required_capital: float
    ) -> Optional[Union[Tuple[str, str], List[Tuple[str, str]]]]:
        """
        Evaluate if we should close worst position(s) to free capital for ORR trade
        
        Supports multi-position rebalancing for small accounts where individual
        positions are smaller than ORR requirement.
        
        Args:
            orr_signal: New ORR signal data
            available_capital: Current available cash
            required_capital: Capital needed for ORR trade
            
        Returns:
            Single tuple (symbol, reason) for 1-position rebalancing OR
            List of tuples [(symbol, reason), ...] for multi-position rebalancing OR
            None if no rebalancing needed
        """
        try:
            orr_symbol = orr_signal.get('symbol', 'UNKNOWN')
            
            # Check if we have enough capital
            if available_capital >= required_capital:
                log.debug(f"✅ Sufficient capital for {orr_symbol}: ${available_capital:.2f} >= ${required_capital:.2f}")
                return None
            
            capital_needed = required_capital - available_capital
            log.info(f"🔄 Evaluating rebalance for {orr_symbol}: need ${capital_needed:.2f} more")
            
            # Check if we have any positions
            if not self.active_positions:
                log.warning("⚠️ No positions available to close for rebalancing")
                return None
            
            # Try to find multiple worst positions (for small accounts)
            worst_positions = self.find_worst_bootable_positions(capital_needed, max_positions=3)
            
            if not worst_positions:
                log.warning("⚠️ No bootable positions found (all profitable or too young)")
                return None
            
            # If only 1 position needed, return single tuple
            if len(worst_positions) == 1:
                symbol, score, reason = worst_positions[0]
                log.info(f"✅ Rebalance approved: Close {symbol} (score {score:.3f}) for {orr_symbol}")
                log.info(f"   Reason: {reason}")
                return (symbol, f"Rebalance for ORR {orr_symbol}: {reason}")
            else:
                # Multiple positions needed
                symbols_str = ", ".join([w[0] for w in worst_positions])
                log.info(f"✅ Multi-position rebalance approved: Close {symbols_str} for {orr_symbol}")
                for symbol, score, reason in worst_positions:
                    log.info(f"   - {symbol}: Score {score:.3f}, {reason}")
                
                return [(symbol, f"Rebalance for ORR {orr_symbol}: {reason}") 
                       for symbol, score, reason in worst_positions]
            
        except Exception as e:
            log.error(f"Error evaluating rebalance: {e}")
            return None
    
    def _find_worst_bootable_position(self, capital_needed: float) -> Optional[Tuple[str, float, str]]:
        """
        Find worst bootable position(s) - supports multi-position rebalancing
        
        Returns: (symbol, score, reason) or None
        
        NOTE: For small accounts, may need to close 2-3 positions to free enough capital
        Use find_worst_bootable_positions() for multi-position rebalancing
        """
        scored_positions = []
        
        for symbol, pos in self.active_positions.items():
            score, is_bootable, reason = self._score_position_for_rebalance(pos)
            
            if is_bootable:
                # Estimate capital that would be freed
                position_value = pos.quantity * pos.entry_price
                unrealized_pnl = pos.quantity * (pos.current_price - pos.entry_price)
                freed_capital = position_value + unrealized_pnl
                
                scored_positions.append((symbol, score, reason, freed_capital))
        
        if not scored_positions:
            return None
        
        # Sort by score (highest = worst)
        scored_positions.sort(key=lambda x: x[1], reverse=True)
        
        # Find first position that frees enough capital
        for symbol, score, reason, freed_capital in scored_positions:
            if freed_capital >= capital_needed:
                return (symbol, score, reason)
        
        # If none free enough, return worst one anyway
        symbol, score, reason, _ = scored_positions[0]
        return (symbol, score, reason)
    
    def find_worst_bootable_positions(
        self,
        capital_needed: float,
        max_positions: int = 3
    ) -> List[Tuple[str, float, str]]:
        """
        Find multiple worst bootable positions that together free enough capital
        
        Args:
            capital_needed: Total capital needed
            max_positions: Maximum positions to close (default 3)
            
        Returns:
            List of (symbol, score, reason) tuples
        """
        scored_positions = []
        
        for symbol, pos in self.active_positions.items():
            score, is_bootable, reason = self._score_position_for_rebalance(pos)
            
            if is_bootable:
                # Estimate capital that would be freed
                position_value = pos.quantity * pos.entry_price
                unrealized_pnl = pos.quantity * (pos.current_price - pos.entry_price)
                freed_capital = position_value + unrealized_pnl
                
                scored_positions.append({
                    'symbol': symbol,
                    'score': score,
                    'reason': reason,
                    'freed_capital': freed_capital
                })
        
        if not scored_positions:
            return []
        
        # Sort by score (highest = worst)
        scored_positions.sort(key=lambda x: x['score'], reverse=True)
        
        # Find combination of worst positions that frees enough capital
        selected = []
        total_freed = 0.0
        
        for sp in scored_positions[:max_positions]:
            selected.append((sp['symbol'], sp['score'], sp['reason']))
            total_freed += sp['freed_capital']
            
            if total_freed >= capital_needed:
                log.info(f"✅ Found {len(selected)} positions to close for ${total_freed:.2f} capital")
                break
        
        if total_freed < capital_needed:
            log.warning(f"⚠️ Even closing {len(selected)} positions only frees ${total_freed:.2f} < ${capital_needed:.2f}")
        
        return selected
    
    def _calculate_adaptive_rebalance_threshold(self) -> float:
        """
        Calculate adaptive rebalancing threshold based on time and SO performance (Rev 00179)
        
        Lower threshold = more aggressive rebalancing
        
        Returns:
            Minimum score required to boot a position (0.1-0.5)
        """
        try:
            current_time = datetime.utcnow()
            
            # Estimate market open time (7:15 AM PT = 14:15 UTC / 10:15 AM ET)
            # For simplicity, use first SO position entry time if available
            if self.active_positions:
                first_entry = min(pos.entry_time for pos in self.active_positions.values())
                minutes_since_open = (current_time - first_entry).total_seconds() / 60.0
            else:
                minutes_since_open = 0
            
            # Time-based adjustment (more aggressive as day progresses)
            # Rev 00201: Use configurable time-weighted peak thresholds
            first_hour_minutes = getattr(self.config, "time_weighted_peak_first_hour_minutes", 60.0)
            second_hour_minutes = getattr(self.config, "time_weighted_peak_second_hour_minutes", 120.0)
            
            if minutes_since_open < first_hour_minutes:  # First hour (7:15-8:15 AM PT)
                time_factor = 0.5  # Very conservative - give SO trades time
            elif minutes_since_open < second_hour_minutes:  # Second hour (8:15-9:15 AM PT)
                time_factor = 0.3  # Moderate - start considering rebalancing
            else:  # After 9:15 AM PT
                time_factor = 0.2  # Aggressive - maximize ORR opportunities
            
            # SO performance adjustment
            if self.active_positions:
                so_positions = [p for p in self.active_positions.values() 
                              if hasattr(p, 'signal_type') and p.signal_type == 'SO']
                
                if so_positions:
                    avg_pnl = sum(p.unrealized_pnl_pct for p in so_positions) / len(so_positions)
                    
                    # Rev 00156: All P&L thresholds are now configurable
                    if avg_pnl < self.config.avg_pnl_threshold_aggressive:  # SO trades losing badly (<-0.5%)
                        perf_factor = 0.1  # Very aggressive - boot losers quickly
                    elif avg_pnl < 0:  # SO trades slightly negative
                        perf_factor = 0.2  # Aggressive
                    elif avg_pnl < self.config.profit_protection_threshold:  # SO trades flat/marginal (<+0.5%)
                        perf_factor = 0.25  # Moderate - on flat days, boot mediocre positions
                    else:  # SO trades profitable (≥+0.5%)
                        perf_factor = 0.4  # Conservative - keep winners
                else:
                    perf_factor = 0.3  # Default
            else:
                perf_factor = 0.3  # Default
            
            # Return lower of the two (more aggressive)
            threshold = min(time_factor, perf_factor)
            
            log.debug(f"📊 Adaptive Rebalance Threshold: {threshold:.2f} (time: {time_factor:.2f}, perf: {perf_factor:.2f}, minutes: {minutes_since_open:.0f})")
            
            return threshold
            
        except Exception as e:
            log.error(f"Error calculating adaptive threshold: {e}")
            return 0.3  # Default fallback
    
    def _score_position_for_rebalance(self, pos: PositionState) -> Tuple[float, bool, str]:
        """
        Score position for rebalancing (higher = worse = more likely to boot)
        
        Returns: (score, is_bootable, reason)
        """
        current_time = datetime.utcnow()
        age_minutes = (current_time - pos.entry_time).total_seconds() / 60.0
        
        # Calculate P&L percentage
        pnl_pct = pos.unrealized_pnl_pct if hasattr(pos, 'unrealized_pnl_pct') else 0.0
        
        # Scoring components (0-1, higher = worse)
        age_score = min(age_minutes / 180.0, 1.0)  # 3 hours = 1.0
        
        # P&L score: positions near 0% are worst - Rev 00156: All thresholds configurable
        if pnl_pct >= self.config.profit_protection_threshold:  # 0.5%+ profit (configurable)
            pnl_score = 0.0  # Best - protect profitable positions
        elif pnl_pct < self.config.loss_threshold:  # -0.2% or worse (configurable)
            pnl_score = 0.3  # Medium - let stop loss handle
        else:  # -0.2% to +0.5% (near breakeven)
            # Rev 00170: PnL score calculation now uses configurable values (was hardcoded)
            pnl_score = (self.config.booting_pnl_score_base + 
                        (1.0 - abs(pnl_pct) / self.config.booting_pnl_score_divisor) * 
                        self.config.booting_pnl_score_range)  # Configurable base + range
        
        # Stagnation score: check if position has moved
        # Rev 00170: Stagnation thresholds now configurable (was hardcoded)
        if pos.highest_price > 0 and pos.entry_price > 0:
            max_excursion_pct = abs(pos.highest_price - pos.entry_price) / pos.entry_price
            if max_excursion_pct < self.config.booting_stagnation_min_pct:  # Configurable minimum movement
                stagnation_score = 1.0  # Worst - completely stagnant
            elif max_excursion_pct > self.config.booting_stagnation_good_pct:  # Configurable good movement
                stagnation_score = 0.2  # Good - active position
            else:
                stagnation_score = 0.5  # Medium
        else:
            stagnation_score = 0.5
        
        # Composite score
        total_score = (
            age_score * 0.30 +
            pnl_score * 0.50 +
            stagnation_score * 0.20
        )
        
        # Get adaptive threshold (Rev 00179)
        min_score_threshold = self._calculate_adaptive_rebalance_threshold()
        
        # Determine if bootable
        is_bootable = False
        reason = ""
        
        # Protect profitable positions - Rev 00156: Threshold configurable
        if pnl_pct >= self.config.profit_protection_threshold:
            reason = f"Profitable ({pnl_pct:.2%}) - protected"
        # Require minimum age
        elif age_minutes < 30:
            reason = f"Too young ({age_minutes:.0f} min) - protected"
        # Protect positions in significant loss (let stop loss handle)
        # Rev 00170: Loss threshold now configurable (was hardcoded -0.01)
        elif pnl_pct < self.config.booting_loss_threshold_pct:
            reason = f"In loss ({pnl_pct:.2%}) - let stop loss handle"
        # Boot positions above adaptive threshold (Rev 00179)
        elif total_score >= min_score_threshold:
            is_bootable = True
            reason = f"Bootable (score {total_score:.2f} ≥ threshold {min_score_threshold:.2f}, {age_minutes:.0f} min, {pnl_pct:.2%} P&L)"
        else:
            reason = f"Score {total_score:.2f} < threshold {min_score_threshold:.2f} - not bootable"
        
        return (total_score, is_bootable, reason)
    
    def find_worst_position_for_rebalance(self) -> Optional[Dict[str, Any]]:
        """
        Find the worst bootable position for adaptive rebalancing (Rev 00180)
        
        Returns:
            Dict with symbol, score, value, reason if bootable position found, None otherwise
        """
        try:
            if not self.active_positions:
                return None
            
            worst_bootable = None
            worst_score = -1.0
            
            for symbol, pos in self.active_positions.items():
                score, is_bootable, reason = self._score_position_for_rebalance(pos)
                
                if is_bootable and score > worst_score:
                    worst_score = score
                    worst_bootable = {
                        'symbol': symbol,
                        'score': score,
                        'value': pos.entry_price * pos.quantity,
                        'reason': reason,
                        'age_minutes': (datetime.utcnow() - pos.entry_time).total_seconds() / 60.0,
                        'pnl_pct': pos.unrealized_pnl_pct
                    }
            
            if worst_bootable:
                log.info(f"🎯 Worst bootable position: {worst_bootable['symbol']} (score {worst_bootable['score']:.2f})")
            else:
                log.debug("No bootable positions found for rebalancing")
            
            return worst_bootable
            
        except Exception as e:
            log.error(f"Error finding worst position: {e}")
            return None
    
    async def close_position_for_rebalance(
        self,
        symbol: str,
        reason: str
    ) -> bool:
        """
        Close single position for rebalancing
        
        Args:
            symbol: Symbol to close
            reason: Reason for closing
            
        Returns:
            True if successfully closed
        """
        try:
            if symbol not in self.active_positions:
                log.error(f"❌ Cannot close {symbol} for rebalance: position not found")
                return False
            
            pos = self.active_positions[symbol]
            
            log.info(f"🔄 Closing {symbol} for rebalance: {reason}")
            log.info(f"   Age: {(datetime.utcnow() - pos.entry_time).total_seconds() / 60:.0f} min, "
                    f"P&L: {pos.unrealized_pnl_pct:.2%}")
            
            # Close via execution adapter
            if self.exec:
                await self.exec.close_position(pos, f"REBALANCE: {reason}")
            else:
                log.error(f"❌ No execution adapter available for rebalancing")
            
            # Remove from tracking
            await self._remove_position(symbol, ExitReason.VOLUME_EXIT, send_alert=False)  # Use VOLUME_EXIT as proxy
            
            log.info(f"✅ Position {symbol} closed for rebalancing")
            return True
            
        except Exception as e:
            log.error(f"❌ Error closing position {symbol} for rebalance: {e}")
            return False
    
    async def close_positions_for_rebalance(
        self,
        positions_to_close: List[Tuple[str, str]]
    ) -> Dict[str, bool]:
        """
        Close multiple positions for rebalancing (small account support)
        
        Args:
            positions_to_close: List of (symbol, reason) tuples
            
        Returns:
            Dict of {symbol: success} results
        """
        results = {}
        total_freed = 0.0
        
        log.info(f"🔄 Multi-position rebalance: Closing {len(positions_to_close)} positions")
        
        for symbol, reason in positions_to_close:
            try:
                if symbol not in self.active_positions:
                    log.error(f"❌ Cannot close {symbol}: position not found")
                    results[symbol] = False
                    continue
                
                pos = self.active_positions[symbol]
                
                # Calculate freed capital
                position_value = pos.quantity * pos.entry_price
                unrealized_pnl = pos.quantity * (pos.current_price - pos.entry_price)
                freed = position_value + unrealized_pnl
                
                log.info(f"   Closing {symbol}: {pos.quantity} shares @ ${pos.current_price:.2f}, "
                        f"P&L {pos.unrealized_pnl_pct:.2%}, Frees ${freed:.2f}")
                
                # Close via execution adapter
                await self.execution_adapter.close_position(pos, f"REBALANCE: {reason}")
                
                # Remove from tracking
                await self._remove_position(symbol, ExitReason.VOLUME_EXIT, send_alert=False)
                
                total_freed += freed
                results[symbol] = True
                
            except Exception as e:
                log.error(f"❌ Error closing {symbol} for rebalance: {e}")
                results[symbol] = False
        
        successful = sum(1 for v in results.values() if v)
        log.info(f"✅ Multi-position rebalance complete: {successful}/{len(positions_to_close)} closed, ${total_freed:.2f} freed")
        
        return results
    
    # ========================================================================
    
    def get_stealth_metrics(self) -> StealthMetrics:
        """Get stealth system performance metrics"""
        # Calculate additional metrics
        if self.stealth_metrics.total_positions > 0:
            self.stealth_metrics.avg_pnl_per_trade = self.stealth_metrics.total_pnl / self.stealth_metrics.total_positions
            
            total_exits = (self.stealth_metrics.stop_loss_exits + 
                          self.stealth_metrics.take_profit_exits + 
                          self.stealth_metrics.trailing_exits + 
                          self.stealth_metrics.breakeven_exits)
            
            if total_exits > 0:
                winning_exits = (self.stealth_metrics.take_profit_exits + 
                               self.stealth_metrics.trailing_exits + 
                               self.stealth_metrics.breakeven_exits)
                self.stealth_metrics.win_rate = winning_exits / total_exits
        
        return self.stealth_metrics
    
    def get_daily_stats(self) -> Dict[str, Any]:
        """Get daily statistics"""
        return self.daily_stats.copy()
    
    def reset_daily_stats(self):
        """Reset daily statistics (call at start of new trading day)"""
        self.daily_stats = {
            'positions_managed': 0,
            'breakeven_activations': 0,
            'trailing_activations': 0,
            'exits_triggered': 0,
            'total_pnl': 0.0
        }
        log.info("Daily stealth statistics reset")
    
    async def emergency_clear_all_positions(self, reason: str = "Emergency Exit"):
        """Clear all positions from stealth tracking during emergency exits (prevents duplicate alerts)
        
        Rev 00146: Added lock to prevent race conditions with position monitoring loop
        """
        async with self._emergency_lock:
            if not self.active_positions:
                log.info(f"🛡️ Emergency clear: No active positions to clear from stealth tracking")
                return
            
            cleared_symbols = list(self.active_positions.keys())
            log.warning(f"🚨 Emergency clear: Removing {len(cleared_symbols)} positions from stealth tracking - {reason}")
            
            # Clear all positions without sending individual alerts (batch alert already sent)
            for symbol in cleared_symbols:
                await self._remove_position(symbol, ExitReason.RAPID_EXIT, send_alert=False)
            
            log.info(f"✅ Emergency clear complete: {len(cleared_symbols)} positions removed from stealth tracking")

    async def shutdown(self):
        """Shutdown stealth system"""
        # Close all remaining positions
        for symbol in list(self.active_positions.keys()):
            await self._remove_position(symbol, ExitReason.TIME_EXIT, send_alert=False)
        
        log.info("PrimeStealthTrailingTP shutdown complete")

# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

def get_prime_stealth_trailing(strategy_mode: StrategyMode = StrategyMode.STANDARD, 
                                alert_manager: Optional[Any] = None) -> PrimeStealthTrailingTP:
    """Get Prime Stealth Trailing instance"""
    # Rev 00126: Pass alert_manager correctly (execution_adapter=None, mode="DEMO" default)
    return PrimeStealthTrailingTP(
        strategy_mode=strategy_mode,
        execution_adapter=None,  # Will be set later
        mode="DEMO",  # Default, will be set later
        alert_manager=alert_manager
    )

def create_stealth_trailing(strategy_mode: StrategyMode = StrategyMode.STANDARD) -> PrimeStealthTrailingTP:
    """Create new Prime Stealth Trailing instance"""
    return PrimeStealthTrailingTP(strategy_mode)

# ============================================================================
# INTEGRATION HELPERS
# ============================================================================

async def integrate_with_trading_manager(trading_manager, stealth_system: PrimeStealthTrailingTP):
    """
    Integrate stealth system with Prime Trading Manager
    
    This function shows how to integrate the stealth system with the existing
    trading manager for seamless position management.
    """
    try:
        # Get all active positions from trading manager
        positions = trading_manager.get_positions()
        
        # Add each position to stealth management
        for symbol, position in positions.items():
            # Get current market data (this would come from your data manager)
            market_data = {
                'price': position.current_price,
                'atr': getattr(position, 'atr', 0.0),
                'volume_ratio': getattr(position, 'volume_ratio', 1.0),
                'momentum': getattr(position, 'momentum', 0.0)
            }
            
            # Add to stealth system
            await stealth_system.add_position(position, market_data)
        
        log.info(f"Integrated {len(positions)} positions with stealth system")
        
    except Exception as e:
        log.error(f"Failed to integrate with trading manager: {e}")

# ============================================================================
# TESTING
# ============================================================================

async def test_stealth_system():
    """Test the stealth trailing system"""
    try:
        print("🧪 Testing Prime Stealth Trailing System...")
        
        # Create stealth system
        stealth = PrimeStealthTrailingTP(StrategyMode.STANDARD)
        
        # Create mock position
        from .prime_models import PrimePosition
        position = PrimePosition(
            position_id="TEST_001",
            symbol="AAPL",
            side=SignalSide.LONG,  # Use LONG for buy-only system
            quantity=100,
            entry_price=150.0,
            current_price=150.0,
            confidence=0.95,
            quality_score=0.95,
            strategy_mode=StrategyMode.STANDARD,
            reason="Test position"
        )
        
        # Add position
        market_data = {
            'price': 150.0,
            'atr': 2.0,
            'volume_ratio': 1.5,
            'momentum': 0.1
        }
        
        success = await stealth.add_position(position, market_data)
        print(f"✅ Position added: {success}")
        
        # Simulate price movement to trigger breakeven
        market_data['price'] = 150.75  # +0.5%
        decision = await stealth.update_position("AAPL", market_data)
        print(f"✅ Breakeven decision: {decision.action} - {decision.reasoning}")
        
        # Simulate further price movement to trigger trailing
        market_data['price'] = 152.0  # +1.33%
        decision = await stealth.update_position("AAPL", market_data)
        print(f"✅ Trailing decision: {decision.action} - {decision.reasoning}")
        
        # Get metrics
        metrics = stealth.get_stealth_metrics()
        print(f"✅ Metrics: {metrics.breakeven_protected} breakeven, {metrics.trailing_activated} trailing")
        
        print("🎯 Stealth system test completed successfully!")
        
    except Exception as e:
        print(f"❌ Stealth system test failed: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(test_stealth_system())
