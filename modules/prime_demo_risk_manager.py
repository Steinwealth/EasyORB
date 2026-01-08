#!/usr/bin/env python3
"""
Prime Demo Risk Manager
======================

Demo Mode Risk Manager providing identical risk management functionality
to the Prime Risk Manager but using simulated account data instead of
real E*TRADE API calls.

Key Features:
- Simulated account balance and cash management
- Identical position sizing logic to Live Mode
- Risk parameter validation and enforcement
- Mock account metrics and performance tracking
- Safe Mode activation for Demo Mode
- Position limits and portfolio risk management
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

from .prime_models import (
    StrategyMode, SignalType, SignalSide, TradeStatus, StopType, TrailingMode,
    MarketRegime, SignalQuality, ConfidenceTier, PrimeSignal, PrimePosition,
    PrimeTrade, get_strategy_config
)
from .config_loader import get_config_value
from .prime_compound_engine import get_prime_compound_engine
from .adv_data_manager import get_adv_manager

log = logging.getLogger("prime_demo_risk_manager")

# ============================================================================
# ENUMS (Reused from Prime Risk Manager)
# ============================================================================

class RiskLevel(Enum):
    """Risk level enumeration"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"

class PositionSizingMethod(Enum):
    """Position sizing method enumeration"""
    FIXED_PERCENTAGE = "fixed_percentage"
    VOLATILITY_BASED = "volatility_based"
    CONFIDENCE_BASED = "confidence_based"
    KELLY_CRITERION = "kelly_criterion"

class SafeModeReason(Enum):
    """Safe mode activation reasons"""
    DRAWDOWN_EXCEEDED = "drawdown_exceeded"
    DAILY_LOSS_EXCEEDED = "daily_loss_exceeded"
    POSITION_LIMIT_EXCEEDED = "position_limit_exceeded"
    SYSTEM_ERROR = "system_error"
    MANUAL_OVERRIDE = "manual_override"

# ============================================================================
# DATA STRUCTURES (Reused from Prime Risk Manager)
# ============================================================================

@dataclass
class RiskParameters:
    """Dynamic risk parameters - identical to Live Mode"""
    # Core risk limits
    max_risk_per_trade_pct: float = 10.0
    cash_reserve_pct: float = 20.0
    trading_cash_pct: float = 80.0
    max_drawdown_pct: float = 10.0
    max_daily_loss_pct: float = 5.0
    
    # Position limits
    max_concurrent_positions: int = 20
    max_positions_per_strategy: int = 5
    max_daily_trades: int = 200
    
    # Confidence thresholds
    ultra_high_confidence_threshold: float = 0.995
    high_confidence_threshold: float = 0.95
    medium_confidence_threshold: float = 0.90
    
    # Confidence multipliers
    ultra_high_confidence_multiplier: float = 1.5
    high_confidence_multiplier: float = 1.2
    medium_confidence_multiplier: float = 1.0
    
    # Position sizing
    min_position_value: float = 50.0
    base_position_size_pct: float = 10.0
    max_position_size_pct: float = 35.0
    
    # Transaction costs
    transaction_cost_pct: float = 0.5
    
    # Stop management
    stop_loss_atr_multiplier: float = 1.5
    take_profit_atr_multiplier: float = 2.0

@dataclass
class AccountMetrics:
    """Account metrics for risk assessment - identical to Live Mode"""
    available_cash: float
    total_account_value: float
    cash_reserve: float
    trading_cash: float
    margin_available: Optional[float] = None
    buying_power: Optional[float] = None
    current_drawdown_pct: float = 0.0
    daily_pnl_pct: float = 0.0
    total_open_positions: int = 0
    strategy_positions: int = 0
    manual_positions: int = 0
    prime_system_position_value: float = 0.0  # Value of positions opened by Prime system only

@dataclass
class PositionRisk:
    """Position risk assessment - IDENTICAL to Live Mode"""
    symbol: str
    quantity: int
    entry_price: float
    position_value: float
    risk_amount: float
    risk_percentage: float
    confidence: float
    confidence_multiplier: float
    atr: float
    stop_loss_price: float
    take_profit_price: float
    transaction_cost: float
    net_position_value: float
    risk_reward_ratio: float

@dataclass
class RiskDecision:
    """Risk decision result - IDENTICAL to Live Mode"""
    approved: bool
    reason: str
    risk_level: RiskLevel
    position_size: Optional[PositionRisk] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    safe_mode_triggered: bool = False
    safe_mode_reason: Optional[SafeModeReason] = None
    warnings: Optional[List[str]] = None
    recommendations: Optional[List[str]] = None

# ============================================================================
# PRIME DEMO RISK MANAGER
# ============================================================================

class PrimeDemoRiskManager:
    """
    Demo Mode Risk Manager providing identical functionality to Prime Risk Manager
    but using simulated account data instead of real E*TRADE API calls.
    """
    
    def __init__(self, strategy_mode: StrategyMode = StrategyMode.STANDARD):
        self.strategy_mode = strategy_mode
        self.config = get_strategy_config(strategy_mode)
        self.risk_params = self._load_risk_parameters()
        
        # Mock account data - Start with $1,000 for realistic Demo Mode
        self.mock_account_balance = 1000.0  # Starting with $1k for realistic growth
        self.mock_initial_balance = 1000.0  # Track initial balance
        self.mock_positions: Dict[str, Any] = {}
        
        # Prime Compound Engine (Rev 00179) - Tracks freed capital
        self.compound_engine = get_prime_compound_engine(self.mock_account_balance)
        
        # Slip Guard ADV Manager (Rev 00046)
        self.adv_manager = get_adv_manager()
        
        # Risk tracking
        self.current_positions: Dict[str, Any] = {}
        self.strategy_positions: Dict[str, Any] = {}
        self.manual_positions: Dict[str, Any] = {}
        self.position_history: deque = deque(maxlen=1000)
        
        # Performance tracking
        self.daily_pnl: float = 0.0
        self.total_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.consecutive_wins: int = 0
        self.win_streak_multiplier: float = 1.0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
        
        # Safe mode
        self.safe_mode_active: bool = False
        self.safe_mode_reason: Optional[SafeModeReason] = None
        self.safe_mode_activated_at: Optional[datetime] = None
        
        # Account metrics
        self.account_metrics: Optional[AccountMetrics] = None
        
        log.info(f"PrimeDemoRiskManager initialized for {strategy_mode.value} strategy")
        log.info(f"🎮 Demo Mode: Starting with ${self.mock_account_balance:,.2f} simulated balance")
        log.info(f"🎯 Demo Mode: Account will grow with profitable trades - starting small for realistic growth!")
    
    def _load_risk_parameters(self) -> RiskParameters:
        """Load risk parameters from configuration - identical to Live Mode"""
        # Rev 00101: UNIFIED - Load from StrategyConfig (adjustable in ONE place)
        return RiskParameters(
            max_risk_per_trade_pct=get_config_value("MAX_SINGLE_POSITION_RISK_PCT", 35.0),
            cash_reserve_pct=self.config.cash_reserve_pct,  # FROM CONFIG: 10.0
            trading_cash_pct=100.0 - self.config.cash_reserve_pct,  # FROM CONFIG: 90.0
            max_drawdown_pct=get_config_value("MAX_DRAWDOWN_PCT", 10.0),
            max_daily_loss_pct=get_config_value("MAX_DAILY_LOSS_PCT", 5.0),
            max_concurrent_positions=get_config_value("MAX_OPEN_POSITIONS", 20),
            max_positions_per_strategy=get_config_value("MAX_POSITIONS_PER_STRATEGY", 5),
            ultra_high_confidence_threshold=get_config_value("ULTRA_HIGH_CONFIDENCE_THRESHOLD", 0.95),
            high_confidence_threshold=get_config_value("HIGH_CONFIDENCE_THRESHOLD", 0.90),
            medium_confidence_threshold=get_config_value("MEDIUM_CONFIDENCE_THRESHOLD", 0.85),
            ultra_high_confidence_multiplier=get_config_value("ULTRA_HIGH_CONFIDENCE_MULTIPLIER", 2.5),
            high_confidence_multiplier=get_config_value("HIGH_CONFIDENCE_MULTIPLIER", 2.0),
            medium_confidence_multiplier=get_config_value("MEDIUM_CONFIDENCE_MULTIPLIER", 1.0),
            min_position_value=get_config_value("MIN_POSITION_VALUE", 50.0),
            base_position_size_pct=get_config_value("BASE_POSITION_SIZE_PCT", 10.0),
            max_position_size_pct=get_config_value("MAX_POSITION_SIZE_PCT", 35.0),
            transaction_cost_pct=get_config_value("TRANSACTION_COST_PCT", 0.5),
            stop_loss_atr_multiplier=get_config_value("STOP_LOSS_ATR_MULTIPLIER", 1.5),
            take_profit_atr_multiplier=get_config_value("TAKE_PROFIT_ATR_MULTIPLIER", 2.0)
        )
    
    async def assess_risk(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> RiskDecision:
        """
        Comprehensive risk assessment for opening a new position - IDENTICAL to Live Mode.
        Implements all 10 core risk management principles.
        """
        try:
            log.info(f"🎮 Assessing Demo risk for {signal.symbol} position")
            
            # 1. Check Safe Mode status
            if self.safe_mode_active:
                return RiskDecision(
                    approved=False,
                    reason=f"Safe mode active: {self.safe_mode_reason.value if self.safe_mode_reason else 'unknown'}",
                    risk_level=RiskLevel.HIGH,
                    safe_mode_triggered=True,
                    safe_mode_reason=self.safe_mode_reason
                )
            
            # 2. Load current mock account metrics
            await self._update_mock_account_metrics()
            if not self.account_metrics:
                return RiskDecision(
                    approved=False,
                    reason="Unable to load mock account metrics",
                    risk_level=RiskLevel.HIGH
                )
            
            # 3. Check drawdown protection (Principle 7)
            drawdown_check = self._check_drawdown_protection()
            if not drawdown_check["approved"]:
                await self._activate_safe_mode(SafeModeReason.DRAWDOWN_EXCEEDED)
                return RiskDecision(
                    approved=False,
                    reason=drawdown_check["reason"],
                    risk_level=RiskLevel.HIGH,
                    safe_mode_triggered=True,
                    safe_mode_reason=SafeModeReason.DRAWDOWN_EXCEEDED
                )
            
            # 4. Check daily loss limits
            daily_loss_check = self._check_daily_loss_limits()
            if not daily_loss_check["approved"]:
                await self._activate_safe_mode(SafeModeReason.DAILY_LOSS_EXCEEDED)
                return RiskDecision(
                    approved=False,
                    reason=daily_loss_check["reason"],
                    risk_level=RiskLevel.HIGH,
                    safe_mode_triggered=True,
                    safe_mode_reason=SafeModeReason.DAILY_LOSS_EXCEEDED
                )
            
            # 5. Check position limits (Principle 7)
            position_limit_check = self._check_position_limits()
            if not position_limit_check["approved"]:
                return RiskDecision(
                    approved=False,
                    reason=position_limit_check["reason"],
                    risk_level=RiskLevel.MEDIUM
                )
            
            # 6. Check news sentiment filtering (Principle 5) - Demo Mode placeholder
            sentiment_check = self._check_news_sentiment(signal, market_data)
            if not sentiment_check["approved"]:
                return RiskDecision(
                    approved=False,
                    reason=sentiment_check["reason"],
                    risk_level=RiskLevel.MEDIUM
                )
            
            # 7. Calculate dynamic position sizing (Principle 4) - IDENTICAL to Live Mode
            position_sizing = await self._calculate_position_sizing(signal, market_data)
            if not position_sizing["approved"]:
                return RiskDecision(
                    approved=False,
                    reason=position_sizing["reason"],
                    risk_level=RiskLevel.LOW
                )
            
            # 8. Check minimum position validation - PORTFOLIO-AWARE minimum
            # For concurrent positions, use a proportional minimum based on portfolio allocation
            if not self.account_metrics:
                return RiskDecision(
                    approved=False,
                    reason="No account metrics available for minimum position validation",
                    risk_level=RiskLevel.HIGH
                )
            
            available_capital = self.account_metrics.available_cash
            num_concurrent_positions = market_data.get("num_concurrent_positions", 1)
            portfolio_aware_minimum = (available_capital * 0.80) / max(1, num_concurrent_positions) * 0.05  # 5% of fair share
            effective_minimum = min(self.risk_params.min_position_value, portfolio_aware_minimum)
            
            if position_sizing["position_risk"].net_position_value < effective_minimum:
                return RiskDecision(
                    approved=False,
                    reason=f"Position size too small: ${position_sizing['position_risk'].net_position_value:.2f} < ${effective_minimum:.2f} (portfolio-aware minimum)",
                    risk_level=RiskLevel.LOW,
                    recommendations=["Wait for account growth", "Consider micro-position sizing", "Reduce concurrent positions"]
                )
            
            # 9. Final risk assessment
            final_risk_assessment = self._final_risk_assessment(position_sizing["position_risk"])
            
            # 10. Create approved risk decision - IDENTICAL to Live Mode
            return RiskDecision(
                approved=True,
                reason="Position approved after comprehensive risk assessment",
                risk_level=final_risk_assessment["risk_level"],
                position_size=position_sizing["position_risk"],
                warnings=final_risk_assessment["warnings"],
                recommendations=final_risk_assessment["recommendations"]
            )
            
        except Exception as e:
            log.error(f"🎮 Demo risk assessment failed for {signal.symbol}: {e}")
            return RiskDecision(
                approved=False,
                reason=f"Risk assessment error: {str(e)}",
                risk_level=RiskLevel.HIGH
            )
    
    async def _update_mock_account_metrics(self):
        """Update mock account metrics - simulates Live Mode account data"""
        try:
            # Calculate current account value including ONLY strategy positions
            strategy_positions = [pos for pos in self.mock_positions.values() if pos.get('source') == 'strategy']
            total_strategy_position_value = sum(pos.get('value', 0) for pos in strategy_positions)
            
            # Total account value = cash + strategy positions only (ignore manual/other positions)
            total_account_value = self.mock_account_balance + total_strategy_position_value
            
            # Calculate cash allocation - ONLY use available cash, not total account value
            # Rev 00101: Use unified config (adjustable in ONE place)
            cash_reserve = self.mock_account_balance * (self.config.cash_reserve_pct / 100.0)
            trading_cash = self.mock_account_balance * ((100.0 - self.config.cash_reserve_pct) / 100.0)
            
            # Calculate drawdown from peak (using strategy-only account value)
            current_drawdown_pct = 0.0
            if hasattr(self, 'peak_capital') and self.peak_capital > 0:
                current_drawdown_pct = max(0.0, (self.peak_capital - total_account_value) / self.peak_capital)
            
            # Update peak capital
            if not hasattr(self, 'peak_capital') or total_account_value > self.peak_capital:
                self.peak_capital = total_account_value
            
            # Rev 00180e: CRITICAL FIX - No margin for Demo Mode (cash account only)
            # Demo should match real trading limits - no 2x leverage
            self.account_metrics = AccountMetrics(
                available_cash=self.mock_account_balance,  # Only available cash
                total_account_value=total_account_value,   # Cash + strategy positions only
                cash_reserve=cash_reserve,
                trading_cash=trading_cash,
                margin_available=0.0,  # No margin for demo (cash account)
                buying_power=self.mock_account_balance,  # Only cash available (no leverage)
                current_drawdown_pct=current_drawdown_pct,
                daily_pnl_pct=self.daily_pnl / total_account_value if total_account_value > 0 else 0.0,
                total_open_positions=len(strategy_positions),  # Only strategy positions
                strategy_positions=len(strategy_positions),
                manual_positions=0  # Ignore manual positions
            )
            
            log.debug(f"🎮 Demo Account: ${self.mock_account_balance:,.2f} cash, ${total_account_value:,.2f} total (strategy only)")
            log.debug(f"🎮 Strategy Positions: {len(strategy_positions)} positions, ${total_strategy_position_value:,.2f} value")
            
        except Exception as e:
            log.error(f"Failed to update mock account metrics: {e}")
    
    async def _calculate_position_sizing(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate position sizing with boosting factors and 80/20 rule - IDENTICAL to Live Mode
        Implements position splitting from 80% trading capital with confidence-based scaling,
        profit-based scaling, strategy agreement bonuses, and win streak boosting
        """
        try:
            if not self.account_metrics:
                return {"approved": False, "reason": "No account metrics not available"}
            
            # Get market data
            current_price = market_data.get("price", 0.0)
            atr = market_data.get("atr", 0.0)
            volume = market_data.get("volume", 0)
            num_concurrent_positions = market_data.get("num_concurrent_positions", 1)
            is_so_trade = market_data.get("is_so_trade", False)
            so_capital_allocation = market_data.get("so_capital_allocation", 0)
            orr_reserve_allocation = market_data.get("orr_reserve_allocation", 0)

            # Ensure trading_cash is always defined (prevents UnboundLocalError when SO flag missing)
            if is_so_trade:
                if not so_capital_allocation or so_capital_allocation <= 0:
                    # Fallback to account metrics allocation when signal metadata is missing
                    so_capital_allocation = self.account_metrics.trading_cash
                    log.debug(
                        "  SO capital allocation missing in market data; using account trading cash ${:.2f}".format(
                            so_capital_allocation
                        )
                    )
                trading_cash = so_capital_allocation
            else:
                # ORR trades share the same trading cash pool in Demo mode
                trading_cash = self.account_metrics.trading_cash
            
            if current_price <= 0:
                return {"approved": False, "reason": "Invalid current price"}
            
            # CRITICAL (Rev 00179): Query Compound Engine for Available Capital
            # Compound engine tracks freed capital from closed positions
            # SO trades use base 70% allocation
            # ORR trades use base 25% + freed capital + unused SO (compounding!)
            if is_so_trade:
                available_capital = self.compound_engine.get_available_for_so()
            else:
                available_capital = self.compound_engine.get_available_for_orr()
            
            log.debug(f"  Compound Engine: ${available_capital:.2f} available for {'SO' if is_so_trade else 'ORR'}")
            
            log.debug(f"Position sizing calculation:")
            log.debug(f"  Available cash: ${available_capital:.2f}")
            log.debug(f"  Trade type: {'SO' if is_so_trade else 'ORR'}")
            log.debug(f"  Concurrent positions: {num_concurrent_positions}")
            
            # 1. Calculate base position value based on trade type (Rev 00165)
            try:
                if is_so_trade:
                    # SO TRADES: Use SO capital allocation from config (Rev 00085: Configurable)
                    # ORR DISABLED - All capital focused on SO profitability
                    # This happens at 10:45 AM with all SO signals known
                    trading_cash = so_capital_allocation  # From SO_CAPITAL_PCT config (default 90%)
                    
                    # CRITICAL FIX (Oct 27, 2025): Use selected trade count (configurable), NOT total signals
                    # Greedy packing divides by trades we'll execute (max_concurrent_trades), not total signals found
                    # This is clearer: "each of the N trades gets 1/Nth of capital as baseline"
                    # Risk manager must use SAME divisor to match greedy packing estimates
                    from .config_loader import get_config_value
                    max_concurrent_trades = int(get_config_value('MAX_CONCURRENT_TRADES', 15))
                    total_signals = market_data.get('total_signals', num_concurrent_positions)
                    selected_trades = min(total_signals, max_concurrent_trades)  # Configurable max
                    fair_share_per_position = trading_cash / max(1, selected_trades)
                    base_position_value = fair_share_per_position
                    log.debug(f"  SO Trade: ${trading_cash:.2f} / {selected_trades} selected trades (max {max_concurrent_trades}) = ${base_position_value:.2f}")
                else:
                    # ORR TRADES: Use available cash (includes closed position profits)
                    # Cap at total trading allocation to maintain cash reserve (Rev 00085: Configurable)
                    # As positions close, their capital becomes available for new ORR trades
                    total_trading_allocation_pct = (self.config.so_capital_pct + self.config.orr_capital_pct) / 100.0
                    max_deployment = (available_capital + self.account_metrics.prime_system_position_value) * total_trading_allocation_pct
                    currently_deployed = self.account_metrics.prime_system_position_value
                    remaining_capacity = max(0, max_deployment - currently_deployed)
                    
                    # Use available cash, but don't exceed remaining capacity
                    orr_allocation = min(available_capital, remaining_capacity)
                    
                    # CRITICAL (Rev 00177): For small accounts, limit ORR trades to SO trade size
                    # This enables 1-for-1 rebalancing (close 1 SO, open 1 ORR)
                    total_account = available_capital + self.account_metrics.prime_system_position_value
                    if total_account < 2500:
                        # Match ORR size to SO size for small accounts
                        # Rev 00107: Use config value (90%), not hardcoded 70%
                        so_capital_calc = total_account * (self.config.so_capital_pct / 100.0)
                        max_so_trades_calc = 7 if total_account < 2500 else 10
                        per_so_trade = so_capital_calc / max_so_trades_calc
                        orr_allocation = min(orr_allocation, per_so_trade)
                        log.debug(f"  Small Account: Limiting ORR to ${per_so_trade:.2f} (matches SO size)")
                    
                    # Also cap at max position % from config (single position limit)
                    # Rev 00107: Use config value, not hardcoded 35%
                    max_single_position = total_account * (self.config.max_position_pct / 100.0)
                    base_position_value = min(orr_allocation, max_single_position)
                    
                    log.debug(f"  ORR Trade: Available ${available_capital:.2f}, Capacity ${remaining_capacity:.2f}, Allocated ${base_position_value:.2f}")
                
            except (TypeError, ValueError) as e:
                log.error(f"Error in base position size calculation: {e}")
                # Fallback: Use available cash with 85% allocation
                base_position_value = available_capital * 0.85 / max(1, num_concurrent_positions)
            
            # 2. FOR SO TRADES: Use base_position_value directly (ORB already factored in confidence)
            # FOR ORR TRADES: Apply multipliers for dynamic sizing
            if is_so_trade:
                # SO TRADE: Use fair share directly (already calculated as SO capital / num trades)
                # ORB manager already applied position_size_pct (22-35%) based on confidence
                # This is the per-trade allocation - use it fully
                position_value = base_position_value
                confidence_multiplier = 1.0  # Already factored in by ORB manager
                agreement_bonus = 0.0  # No additional multipliers for SO
                log.debug(f"  SO Trade: Using direct allocation ${position_value:.2f}")
            else:
                # ORR TRADE: Apply confidence multipliers for dynamic sizing
                confidence_multiplier = self._get_confidence_multiplier(signal.confidence)
                agreement_bonus = self._get_strategy_agreement_bonus(signal, market_data)
                profit_scaling_multiplier = self._get_profit_scaling_multiplier()
                win_streak_multiplier = self._get_win_streak_multiplier()
                
                position_value = (
                    base_position_value * 
                    confidence_multiplier * 
                    (1 + agreement_bonus) * 
                    profit_scaling_multiplier * 
                    win_streak_multiplier
                )
                log.debug(f"  ORR Trade: Multiplied ${base_position_value:.2f} → ${position_value:.2f}")
            
            # Rev 00067: POST-ROUNDING REDISTRIBUTION OVERRIDE
            # Rev 00083: Now SAFE to use because post-rounding enforces capital_limit
            # If prime_trading_system calculated a final position value after redistribution,
            # use that instead of recalculating (ensures capital efficiency while staying under capital limits)
            position_value_override = market_data.get('position_value_override')
            if position_value_override is not None and position_value_override > 0:
                original_position_value = position_value
                position_value = position_value_override
                log.info(f"🎯 POST-ROUNDING OVERRIDE: ${original_position_value:.2f} → ${position_value:.2f} (Rev 00083: respects SO capital cap)")
            
            # 7.5 RANK-BASED POSITION SIZING (Rev 00180AE - ENABLED WITH GREEDY PACKING)
            # How it works:
            # 1. Greedy packing SELECTS which trades to execute (based on affordability)
            # 2. Rank boosts DETERMINE position size (fair_share × rank_multiplier)
            # 3. Greedy packing ensures total deployed <= 105% of SO capital
            
            priority_rank = market_data.get('priority_rank', 999)
            priority_score = market_data.get('priority_score', 0.0)
            
            if is_so_trade:
                # Rev 00180AE: Apply rank-based multipliers for SO trades
                # Oct 24, 2025: Original steep multipliers with MAX TRADES = 15
                # Greedy packing ensures we never exceed 15 trades
                # Fair share fix ensures correct position sizing
                
                # GRADUATED RANK MULTIPLIERS (original proven system)
                if priority_rank == 1:
                    boost = 3.0  # Rank #1: Maximum allocation (best signal)
                    log.info(f"🚀 RANK #1 {signal.symbol}: 3.0x boost (Priority: {priority_score:.3f})")
                elif priority_rank == 2:
                    boost = 2.5  # Rank #2: Very high allocation
                    log.info(f"🌟 RANK #2 {signal.symbol}: 2.5x boost (Priority: {priority_score:.3f})")
                elif priority_rank == 3:
                    boost = 2.0  # Rank #3: High allocation
                    log.info(f"⭐ RANK #3 {signal.symbol}: 2.0x boost (Priority: {priority_score:.3f})")
                elif priority_rank <= 5:
                    boost = 1.71  # Rank 4-5: Above average
                    log.info(f"🔥 RANK #{priority_rank} {signal.symbol}: 1.71x boost (Priority: {priority_score:.3f})")
                elif priority_rank <= 10:
                    boost = 1.5  # Rank 6-10: Moderate boost
                    log.info(f"📈 RANK #{priority_rank} {signal.symbol}: 1.5x boost (Priority: {priority_score:.3f})")
                elif priority_rank <= 15:
                    boost = 1.2  # Rank 11-15: Small boost
                    log.info(f"📊 RANK #{priority_rank} {signal.symbol}: 1.2x boost (Priority: {priority_score:.3f})")
                elif priority_rank <= 20:
                    boost = 1.0  # Rank 16-20: Base allocation
                    log.info(f"✅ RANK #{priority_rank} {signal.symbol}: 1.0x (base)")
                else:
                    boost = 0.8  # Rank 21+: Reduced
                    log.debug(f"⚪ RANK #{priority_rank} {signal.symbol}: 0.8x (reduced)")
            else:
                # For ORR trades, apply modest boosts (when ORR is enabled)
                if priority_rank <= 3:
                    boost = 1.5
                    log.info(f"🚀 RANK #{priority_rank} {signal.symbol}: 1.5x boost (Priority: {priority_score:.3f})")
                elif priority_rank <= 5:
                    boost = 1.3
                    log.info(f"🔥 RANK #{priority_rank} {signal.symbol}: 1.3x boost (Priority: {priority_score:.3f})")
                elif priority_rank <= 10:
                    boost = 1.2
                    log.info(f"📈 RANK #{priority_rank} {signal.symbol}: 1.2x boost (Priority: {priority_score:.3f})")
                else:
                    boost = 1.0
                    log.debug(f"✅ RANK #{priority_rank} {signal.symbol}: 1.0x (base)")
            
            position_value *= boost
            
            # 7.5.5 NORMALIZATION (Oct 24, 2025): Apply proportional scaling if greedy packing set it
            # This allows ALL signals ≤15 to execute by scaling proportionally
            normalization_factor = market_data.get('normalization_factor', 1.0)
            if normalization_factor < 1.0:
                original_value = position_value
                position_value *= normalization_factor
                log.info(f"📏 Normalized: ${original_value:.2f} → ${position_value:.2f} ({normalization_factor*100:.1f}% scale)")
            
            # 7.5.6 🛡️ SLIP GUARD - ADV-BASED POSITION CAPPING (Rev 00046, Enhanced Rev 00037)
            # Cap position at 1% of Average Daily Volume to prevent slippage
            # Rev 00037: Primary Slip Guard now in greedy packing with reallocation
            # This is a SAFETY CHECK in case greedy packing didn't apply it
            
            # Check if Slip Guard already applied in greedy packing (Rev 00037)
            position_after_adv = market_data.get('position_after_adv', 0)
            if position_after_adv > 0:
                # Slip Guard already applied with reallocation in greedy packing
                log.debug(f"   Slip Guard position from greedy packing: ${position_after_adv:,.0f}")
                position_value = position_after_adv  # Use the ADV-adjusted position
            else:
                # Fallback: Apply Slip Guard here (for non-SO trades or old code paths)
                adv_dollars = market_data.get('adv_dollars', 0)
                if not adv_dollars:
                    adv_dollars = self.adv_manager.get_adv(signal.symbol)
                
                if adv_dollars > 0:
                    adv_limit = self.adv_manager.get_adv_limit(signal.symbol, mode="aggressive")
                    
                    if position_value > adv_limit:
                        original_position = position_value
                        position_value = adv_limit
                        freed_capital = original_position - adv_limit
                        pct_of_adv = (original_position / adv_dollars) * 100
                        
                        log.warning(f"🛡️ SLIP GUARD (Safety): {signal.symbol} (Rank {priority_rank}) "
                                   f"${original_position:,.0f} → ${adv_limit:,.0f} "
                                   f"(ADV: ${adv_dollars:,.0f}, {pct_of_adv:.1f}% → 1.0%, freed ${freed_capital:,.0f})")
                        
                        # Mark for tracking
                        market_data['slip_guard_capped'] = True
                        market_data['slip_guard_freed'] = freed_capital
            
            # Rev 00176: Market Quality Gate removed - Red Day Detection Filter provides this functionality
            
            # 8. Apply maximum position size limit (Rev 00180AE - ALLOWS RANK BOOSTS)
            try:
                # Rev 00180Z: Fix variable name error (was: prime_system_portfolio_value)
                total_portfolio_value = available_capital + self.account_metrics.prime_system_position_value
                
                # Rev 00180AE: Max position size for rank-based sizing with greedy packing
                # FIX (Oct 24, 2025): Cap at 35% per position (not 45%)
                # With small account multipliers (1.5x max), this gives proper diversification
                # 7 trades × 1.5x boost → Need 35% cap (not 45%)
                # Rev 00107: Use config value, not hardcoded 35%
                if is_so_trade:
                    max_position_size_pct = self.config.max_position_pct  # From config
                else:
                    max_position_size_pct = 25.0  # ORR trades get smaller max (when enabled)
                
                max_position_value = total_portfolio_value * (max_position_size_pct / 100.0)
                position_value = min(position_value, max_position_value)
                log.debug(f"  Position capped at {max_position_size_pct}% of ${total_portfolio_value:.2f} = ${max_position_value:.2f}")
            except (TypeError, ValueError) as e:
                log.error(f"Error in max position size calculation: {e}")
                # Rev 00107: Use config value, not hardcoded 35%
                total_portfolio_value = available_capital + self.account_metrics.prime_system_position_value
                max_position_value = total_portfolio_value * (self.config.max_position_pct / 100.0 if is_so_trade else 0.25)
                position_value = min(position_value, max_position_value)
            
            # 9. PORTFOLIO-AWARE CONFIDENCE SCALING (SKIP FOR SO TRADES - Rev 00174)
            # For SO trades: ORB manager already calculated optimal allocation
            # For ORR trades: Apply portfolio-aware confidence scaling
            if not is_so_trade:
                # Calculate confidence weight (0.5 to 1.5 range based on confidence and agreement)
                confidence_weight = 0.5  # Base weight
                confidence_weight += (signal.confidence - 0.85) * 2.0  # Confidence contribution
                confidence_weight += agreement_bonus * 0.3  # Agreement contribution
                
                # Normalize weight to reasonable range (0.7 to 1.3)
                confidence_weight = max(0.7, min(1.3, confidence_weight))
                
                # Apply portfolio-aware scaling for ORR trades
                max_fair_share = trading_cash / max(1, num_concurrent_positions)
                confidence_scaled_allocation = max_fair_share * confidence_weight
                position_value = min(position_value, confidence_scaled_allocation)
                log.debug(f"  ORR: Portfolio-aware scaling applied (weight {confidence_weight:.2f}x)")
            else:
                log.debug(f"  SO: Using direct fair share allocation ${position_value:.2f} (no additional scaling)")
            
            # 10. CRITICAL: Check if we have enough available cash to open this position
            # Rev 00180: For ORR trades, trigger adaptive rebalancing if capital insufficient
            if position_value > available_capital:
                # Check if this is an ORR trade that could benefit from rebalancing
                is_orr_trade = market_data.get('is_orr_trade', False) or not market_data.get('is_so_trade', True)
                
                if is_orr_trade and available_capital < position_value:
                    # Try adaptive rebalancing to free capital (Rev 00180)
                    log.info(f"💰 ORR Trade: Need ${position_value:.2f}, Available ${available_capital:.2f} - checking rebalancing...")
                    
                    # Get stealth trailing system reference
                    try:
                        from .prime_stealth_trailing_tp import get_prime_stealth_trailing
                        stealth_trailing = get_prime_stealth_trailing()
                        
                        # Check if we can boot a position to free capital
                        worst_position = stealth_trailing.find_worst_position_for_rebalance()
                        
                        if worst_position:
                            # Boot worst position asynchronously
                            import asyncio
                            freed = asyncio.create_task(
                                stealth_trailing.close_position_for_rebalance(
                                    worst_position['symbol'],
                                    f"Adaptive rebalancing for {signal.symbol} ORR (score: {worst_position['score']:.2f})"
                                )
                            )
                            log.info(f"🔄 Adaptive Rebalancing: Booted {worst_position['symbol']} to free ${worst_position['value']:.2f} for ORR")
                            # Capital will be freed and available for next check
                        else:
                            log.info(f"⚠️ No positions can be booted for rebalancing (all protected)")
                    except Exception as e:
                        log.warning(f"Could not trigger rebalancing: {e}")
                
                # Standard handling for insufficient capital
                if available_capital < 50.0:  # Minimum $50 position
                    log.warning(f"Insufficient cash for position: ${position_value:.2f} > ${available_capital:.2f}")
                    return PositionRisk(
                        position_value=0.0,
                        quantity=0.0,
                        risk_percentage=0.0,
                        confidence_multiplier=confidence_multiplier,
                        agreement_bonus=agreement_bonus,
                        risk_level=RiskLevel.HIGH,
                        reasoning="Insufficient available cash for position (rebalancing attempted if ORR)"
                    )
                else:
                    # Reduce position size to available cash
                    position_value = available_capital
                    log.info(f"Reduced position size to available cash: ${position_value:.2f}")
            
            log.debug(f"Final position sizing:")
            log.debug(f"  Base position value: ${base_position_value:.2f}")
            log.debug(f"  Confidence multiplier: {confidence_multiplier:.2f}x")
            log.debug(f"  Agreement bonus: +{agreement_bonus:.0%}")
            log.debug(f"  Final position value: ${position_value:.2f}")
            
            # SPREAD PROTECTION (Rev 00175) - Inline validation
            # Get bid/ask from market data or estimate
            bid = market_data.get('bid', current_price * 0.999)  # Assume 0.1% spread if not provided
            ask = market_data.get('ask', current_price * 1.001)
            
            # Validate spread width (40 bps = 0.40% max for regular symbols)
            mid_price = (bid + ask) / 2.0
            spread_abs = ask - bid
            spread_bps = (spread_abs / mid_price) * 10000
            
            # Check spread limits by symbol type
            max_spread_bps = 40.0  # Default for regular symbols
            if signal.symbol in ['SPY', 'QQQ', 'IWM', 'SOXL', 'TQQQ', 'TNA', 'URTY', 'UWM']:  # ETFs
                max_spread_bps = 25.0  # Tighter for liquid ETFs
            
            if spread_bps > max_spread_bps:
                return {
                    "approved": False,
                    "reason": f"Spread too wide: {spread_bps:.1f}bps > {max_spread_bps:.1f}bps limit"
                }
            
            # Check slippage vs signal price (0.8% max)
            slippage_pct = abs(ask - current_price) / current_price * 100
            if slippage_pct > 0.8:
                return {
                    "approved": False,
                    "reason": f"Excessive slippage: {slippage_pct:.2f}% > 0.8% limit"
                }
            
            # Use ask price + 0.10% buffer for execution
            execution_price = ask * 1.001
            spread_cost = (execution_price - mid_price) * (position_value / execution_price)
            
            log.info(f"🛡️ Spread validated: {spread_bps:.1f}bps, slippage {slippage_pct:.2f}%, execution ${execution_price:.2f}")
            
            # Rev 00089: CRITICAL FIX - Check for batch-sized quantity override
            # If batch sizing already calculated whole shares, use that instead of recalculating
            quantity_override = market_data.get('quantity_override')
            
            if quantity_override is not None and quantity_override > 0:
                # Use batch-sized quantity (already optimized for whole shares and capital limit)
                quantity = int(quantity_override)
                log.info(f"🎯 Using batch-sized quantity: {quantity} shares (from batch sizing, no recalculation)")
            else:
                # Original flow: Calculate quantity using spread-protected execution price (Rev 00038: Smart Integer Rounding)
                # ETrade requires whole shares - optimize rounding to maximize capital utilization
                raw_quantity = position_value / execution_price
                
                # Smart rounding: Try rounding UP first to improve capital efficiency
                quantity_down = int(raw_quantity)
                quantity_up = quantity_down + 1 if raw_quantity > quantity_down else quantity_down
                
                # Calculate costs for both options
                cost_down = quantity_down * execution_price
                cost_up = quantity_up * execution_price
                
                # Determine safe rounding limits
                # Rev 00180Z: Fix variable name error (was: prime_system_portfolio_value)
                total_portfolio_value = available_capital + self.account_metrics.prime_system_position_value
                max_position_value = total_portfolio_value * (max_position_size_pct / 100.0)
                overage_tolerance = position_value * 1.05  # Allow 5% overage for better capital utilization
                
                # Decide: Round up if safe (improves capital efficiency)
                if (quantity_up > quantity_down and 
                    cost_up <= overage_tolerance and 
                    cost_up <= max_position_value and 
                    cost_up <= available_capital):
                    quantity = quantity_up
                    overage = cost_up - position_value
                    overage_pct = (overage / position_value) * 100 if position_value > 0 else 0
                    log.info(f"📈 Smart round UP: {raw_quantity:.3f} → {quantity} shares (${cost_up:.2f}, +${overage:.2f} or +{overage_pct:.1f}%)")
                else:
                    quantity = quantity_down
                    if quantity_down > 0:
                        underage = position_value - cost_down
                        log.debug(f"📉 Round DOWN: {raw_quantity:.3f} → {quantity} shares (${cost_down:.2f}, unused ${underage:.2f})")
                
                # CRITICAL FIX (Rev 00174): Ensure at least 1 share for affordable symbols
                if quantity < 1 and position_value >= execution_price:
                    # If we have enough $ for 1 share, buy 1 share
                    quantity = 1
                    log.info(f"🔧 Adjusted to minimum 1 share: ${position_value:.2f} allocation, ${current_price:.2f} price")
            
            if quantity < 1:
                return {"approved": False, "reason": f"Position size too small: ${position_value:.2f} < ${current_price:.2f} (need ${current_price:.2f} for 1 share)"}
            
            # Calculate transaction cost
            transaction_cost = position_value * (self.risk_params.transaction_cost_pct / 100.0)
            net_position_value = position_value - transaction_cost
            
            # Calculate risk metrics using total account value
            # Rev 00180Z: Fix variable name error (was: prime_system_portfolio_value)
            total_portfolio_value = available_capital + self.account_metrics.prime_system_position_value
            risk_amount = position_value
            risk_percentage = (risk_amount / total_portfolio_value) * 100.0
            
            # Calculate stop loss and take profit
            if atr > 0:
                stop_loss_price = current_price - (atr * self.risk_params.stop_loss_atr_multiplier)
                take_profit_price = current_price + (atr * self.risk_params.take_profit_atr_multiplier)
                risk_reward_ratio = (take_profit_price - current_price) / (current_price - stop_loss_price)
            else:
                stop_loss_price = current_price * 0.95  # 5% stop loss
                take_profit_price = current_price * 1.10  # 10% take profit
                risk_reward_ratio = 2.0
            
            # Create position risk object - IDENTICAL to Live Mode
            position_risk = PositionRisk(
                symbol=signal.symbol,
                quantity=quantity,
                entry_price=current_price,
                position_value=position_value,
                risk_amount=risk_amount,
                risk_percentage=risk_percentage,
                confidence=signal.confidence,
                confidence_multiplier=confidence_multiplier,
                atr=atr,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                transaction_cost=transaction_cost,
                net_position_value=net_position_value,
                risk_reward_ratio=risk_reward_ratio
            )
            
            trade_type_str = "SO" if is_so_trade else "ORR"
            log.info(f"🎮 Position sizing calculated for {signal.symbol} ({trade_type_str}): "
                    f"${position_value:.2f} value ({risk_percentage:.1f}% of portfolio), {quantity} shares, "
                    f"Available Cash: ${available_capital:.2f}, Base Position: ${base_position_value:.2f}, "
                    f"Concurrent: {num_concurrent_positions}, Conf Mult: {confidence_multiplier:.2f}x")
            
            return {
                "approved": True,
                "position_risk": position_risk
            }
            
        except Exception as e:
            log.error(f"🎮 Position sizing calculation error: {e}")
            return {"approved": False, "reason": f"Position sizing calculation error: {str(e)}"}
    
    def _get_confidence_multiplier(self, confidence: float) -> float:
        """Get confidence multiplier for position sizing (Principle 6) - IDENTICAL to Live Mode"""
        try:
            # Handle string values with comments
            ultra_high_threshold = float(str(self.risk_params.ultra_high_confidence_threshold).split('#')[0].strip())
            high_threshold = float(str(self.risk_params.high_confidence_threshold).split('#')[0].strip())
            medium_threshold = float(str(self.risk_params.medium_confidence_threshold).split('#')[0].strip())
            
            ultra_high_multiplier = float(str(self.risk_params.ultra_high_confidence_multiplier).split('#')[0].strip())
            high_multiplier = float(str(self.risk_params.high_confidence_multiplier).split('#')[0].strip())
            medium_multiplier = float(str(self.risk_params.medium_confidence_multiplier).split('#')[0].strip())
            
            if confidence >= ultra_high_threshold:
                return ultra_high_multiplier
            elif confidence >= high_threshold:
                return high_multiplier
            elif confidence >= medium_threshold:
                return medium_multiplier
            else:
                return 1.0
        except (TypeError, ValueError) as e:
            log.warning(f"Error in confidence calculation, using default: {e}")
            # Use default multipliers
            if confidence >= 0.95:
                return 1.5
            elif confidence >= 0.90:
                return 1.2
            elif confidence >= 0.85:
                return 1.0
            else:
                return 1.0
    
    def _get_profit_scaling_multiplier(self) -> float:
        """Get profit-based scaling multiplier for position sizing - IDENTICAL to Live Mode"""
        if not self.account_metrics:
            return 1.0
        
        # Calculate profit percentage from initial capital
        # Using mock initial balance for Demo Mode
        initial_capital = self.mock_initial_balance
        current_value = self.account_metrics.total_account_value
        profit_pct = (current_value - initial_capital) / initial_capital if initial_capital > 0 else 0
        
        # Scale position sizes based on profit growth
        if profit_pct >= 1.0:  # 100%+ profit
            scaling_multiplier = 2.0  # Double position sizes
        elif profit_pct >= 0.5:  # 50%+ profit
            scaling_multiplier = 1.5  # 1.5x position sizes
        elif profit_pct >= 0.25:  # 25%+ profit
            scaling_multiplier = 1.25  # 1.25x position sizes
        elif profit_pct >= 0.1:  # 10%+ profit
            scaling_multiplier = 1.1  # 1.1x position sizes
        else:
            scaling_multiplier = 1.0  # No scaling
        
        return scaling_multiplier
    
    def _get_strategy_agreement_bonus(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> float:
        """Get strategy agreement bonus for position sizing - IDENTICAL to Live Mode"""
        # Get strategy agreement level from market data
        agreement_level = market_data.get("strategy_agreement_level", "NONE")
        
        # Strategy Agreement Bonuses for Position Sizing
        agreement_bonuses = {
            'NONE': 0.0,      # 0 strategies agree
            'LOW': 0.0,       # 1 strategy agrees  
            'MEDIUM': 0.25,   # 2 strategies agree (+25%)
            'HIGH': 0.50,     # 3 strategies agree (+50%)
            'MAXIMUM': 1.00   # 4+ strategies agree (+100%)
        }
        
        return agreement_bonuses.get(agreement_level, 0.0)
    
    def _get_win_streak_multiplier(self) -> float:
        """Get win streak multiplier for position sizing - IDENTICAL to Live Mode"""
        # This tracks consecutive wins and applies multiplier
        return self.win_streak_multiplier
    
    def _check_news_sentiment(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check news sentiment filtering (Principle 5) - Demo Mode placeholder"""
        # For Demo Mode, we'll always approve (no real news sentiment available)
        # In Live Mode, this would check actual news sentiment data
        return {"approved": True, "reason": "News sentiment check passed (Demo Mode)"}
    
    def _final_risk_assessment(self, position_risk: PositionRisk) -> Dict[str, Any]:
        """Final risk assessment and warnings - IDENTICAL to Live Mode"""
        warnings = []
        recommendations = []
        risk_level = RiskLevel.LOW
        
        # Check risk percentage
        if position_risk.risk_percentage > 15.0:
            risk_level = RiskLevel.HIGH
            warnings.append(f"High risk percentage: {position_risk.risk_percentage:.2f}%")
        elif position_risk.risk_percentage > 10.0:
            risk_level = RiskLevel.MEDIUM
            warnings.append(f"Medium risk percentage: {position_risk.risk_percentage:.2f}%")
        
        # Check confidence level
        if position_risk.confidence < 0.80:
            warnings.append(f"Low confidence signal: {position_risk.confidence:.2f}")
            recommendations.append("Consider waiting for higher confidence signals")
        
        # Check risk/reward ratio
        if position_risk.risk_reward_ratio < 1.5:
            warnings.append(f"Poor risk/reward ratio: {position_risk.risk_reward_ratio:.2f}")
            recommendations.append("Consider adjusting stop loss or take profit levels")
        
        return {
            "risk_level": risk_level,
            "warnings": warnings,
            "recommendations": recommendations
        }
    
    def _check_drawdown_protection(self) -> Dict[str, Any]:
        """Check drawdown protection - identical to Live Mode"""
        if not self.account_metrics:
            return {"approved": False, "reason": "No account metrics available"}
        
        current_drawdown = self.account_metrics.current_drawdown_pct
        max_drawdown = self.risk_params.max_drawdown_pct
        
        if current_drawdown >= max_drawdown:
            return {
                "approved": False,
                "reason": f"Drawdown limit exceeded: {current_drawdown:.2f}% >= {max_drawdown}%"
            }
        
        return {"approved": True}
    
    def _check_daily_loss_limits(self) -> Dict[str, Any]:
        """Check daily loss limits - identical to Live Mode"""
        if not self.account_metrics:
            return {"approved": False, "reason": "No account metrics available"}
        
        daily_pnl = self.account_metrics.daily_pnl_pct
        max_daily_loss = self.risk_params.max_daily_loss_pct
        
        if daily_pnl <= -max_daily_loss:
            return {
                "approved": False,
                "reason": f"Daily loss limit exceeded: {daily_pnl:.2f}% <= -{max_daily_loss}%"
            }
        
        return {"approved": True}
    
    def _check_position_limits(self) -> Dict[str, Any]:
        """Check position limits - identical to Live Mode"""
        if not self.account_metrics:
            return {"approved": False, "reason": "No account metrics available"}
        
        current_positions = self.account_metrics.strategy_positions
        max_positions = self.risk_params.max_concurrent_positions
        
        if current_positions >= max_positions:
            return {
                "approved": False,
                "reason": f"Position limit reached: {current_positions}/{max_positions}"
            }
        
        return {"approved": True}
    
    async def _activate_safe_mode(self, reason: SafeModeReason):
        """Activate safe mode"""
        self.safe_mode_active = True
        self.safe_mode_reason = reason
        self.safe_mode_activated_at = datetime.now()
        log.warning(f"🚨 Demo Safe Mode activated: {reason.value}")
    
    async def deactivate_safe_mode(self):
        """Deactivate safe mode"""
        self.safe_mode_active = False
        self.safe_mode_reason = None
        self.safe_mode_activated_at = None
        log.info("✅ Demo Safe Mode deactivated")
    
    def update_mock_position(self, symbol: str, position_data: Dict[str, Any]):
        """Update mock position data"""
        self.mock_positions[symbol] = position_data
        log.debug(f"🎮 Updated mock position: {symbol}")
        
        # If this is a new strategy position, deduct cash
        if position_data.get('source') == 'strategy' and 'value' in position_data:
            position_value = position_data['value']
            if position_value > 0:
                self.mock_account_balance -= position_value
                log.debug(f"🎮 Deducted ${position_value:.2f} for new position: {symbol}")
                log.debug(f"🎮 New cash balance: ${self.mock_account_balance:.2f}")
    
    def remove_mock_position(self, symbol: str):
        """Remove mock position"""
        if symbol in self.mock_positions:
            del self.mock_positions[symbol]
            log.debug(f"🎮 Removed mock position: {symbol}")
    
    def process_trade_close(self, symbol: str, exit_price: float, quantity: float, pnl: float):
        """
        Process trade closing and update account balance
        
        Args:
            symbol: Symbol of the closed trade
            exit_price: Exit price of the trade
            quantity: Quantity of shares
            pnl: Profit or loss from the trade
        """
        try:
            if symbol in self.mock_positions:
                # Get position data before removing
                position_data = self.mock_positions[symbol]
                position_value = position_data.get('value', 0)
                
                # Remove position
                del self.mock_positions[symbol]
                
                # Add back the original position value + P&L
                self.mock_account_balance += position_value + pnl
                
                # Update performance tracking
                self.daily_pnl += pnl
                self.total_pnl += pnl
                
                if pnl > 0:
                    self.winning_trades += 1
                    self.consecutive_wins += 1
                    self.consecutive_losses = 0
                else:
                    self.losing_trades += 1
                    self.consecutive_losses += 1
                    self.consecutive_wins = 0
                
                # Update win streak multiplier
                if self.consecutive_wins >= 3:
                    self.win_streak_multiplier = min(2.0, 1.0 + (self.consecutive_wins * 0.1))
                else:
                    self.win_streak_multiplier = 1.0
                
                log.info(f"🎮 Demo Trade Closed: {symbol} - P&L: ${pnl:.2f} - New Balance: ${self.mock_account_balance:.2f}")
                
                # Check if account has grown significantly
                growth_pct = ((self.mock_account_balance - self.mock_initial_balance) / self.mock_initial_balance) * 100
                if growth_pct > 10:  # More than 10% growth
                    log.info(f"🚀 Demo Account Growth: {growth_pct:.1f}% from initial ${self.mock_initial_balance:.2f}")
                
                return True
            else:
                log.warning(f"Demo position {symbol} not found for closing")
                return False
                
        except Exception as e:
            log.error(f"Error processing demo trade close: {e}")
            return False
    
    def get_mock_account_summary(self) -> Dict[str, Any]:
        """Get mock account summary"""
        current_value = self.mock_account_balance + sum(pos.get('value', 0) for pos in self.mock_positions.values())
        growth_pct = ((current_value - self.mock_initial_balance) / self.mock_initial_balance) * 100 if self.mock_initial_balance > 0 else 0
        
        return {
            'mock_balance': self.mock_account_balance,
            'mock_positions': len(self.mock_positions),
            'mock_total_value': current_value,
            'mock_initial_balance': self.mock_initial_balance,
            'growth_percentage': growth_pct,
            'total_pnl': self.total_pnl,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': (self.winning_trades / (self.winning_trades + self.losing_trades)) * 100 if (self.winning_trades + self.losing_trades) > 0 else 0,
            'safe_mode_active': self.safe_mode_active,
            'safe_mode_reason': self.safe_mode_reason.value if self.safe_mode_reason else None
        }
    
    def get_risk_summary(self) -> Dict[str, Any]:
        """Get comprehensive risk summary - matches PrimeRiskManager interface"""
        return {
            "account_metrics": self.account_metrics.__dict__ if self.account_metrics else None,
            "safe_mode": {
                "active": self.safe_mode_active,
                "reason": self.safe_mode_reason.value if self.safe_mode_reason else None,
                "activated_at": self.safe_mode_activated_at.isoformat() if self.safe_mode_activated_at else None
            },
            "risk_parameters": self.risk_params.__dict__,
            "performance": {
                "daily_pnl": self.daily_pnl,
                "total_pnl": self.total_pnl,
                "consecutive_losses": self.consecutive_losses,
                "consecutive_wins": self.consecutive_wins,
                "win_streak_multiplier": self.win_streak_multiplier,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades
            },
            "positions": {
                "total": len(self.current_positions),
                "strategy": len(self.strategy_positions),
                "manual": len(self.manual_positions),
                "mock": len(self.mock_positions)
            },
            "demo_mode": True,
            "mock_balance": self.mock_account_balance,
            "initial_balance": self.mock_initial_balance
        }

# ============================================================================
# FACTORY FUNCTIONS
    async def calculate_batch_position_sizes(self, signals: List[Dict[str, Any]], 
                                            so_capital: float, account_value: float,
                                            max_position_pct: float = 35.0) -> List[Dict[str, Any]]:
        """
        Calculate position sizes for a batch of signals (Rev 00084)
        
        Implements clean flow:
        1. Apply rank multipliers
        2. Apply max position cap (configurable, default 35%)
        3. Apply ADV limits
        4. Normalize to fit SO capital (configurable via SO_CAPITAL_ALLOCATION_PCT)
        5. Convert to whole shares (constrained sequential)
        
        Args:
            signals: List of signal dicts with symbol, price, rank, etc.
            so_capital: Total SO capital allocation (e.g., $900 for $1K account @ 90%)
            account_value: Total account value
            max_position_pct: Maximum position size as % of account (default 35.0)
            
        Returns:
            List of signals with 'quantity' and 'position_value' set
        """
        try:
            from .adv_data_manager import get_adv_manager
            
            so_capital_pct = (so_capital / account_value) * 100.0 if account_value > 0 else 90.0
            
            log.info(f"")
            log.info(f"=" * 80)
            log.info(f"📊 BATCH POSITION SIZING (Rev 00084 Clean Flow)")
            log.info(f"=" * 80)
            log.info(f"   Account: ${account_value:,.0f}")
            log.info(f"   SO Capital ({so_capital_pct:.0f}%): ${so_capital:,.0f}")
            log.info(f"   Signals: {len(signals)}")
            log.info(f"")
            
            # Calculate fair share and position cap
            fair_share = so_capital / max(1, len(signals))
            max_position_cap = account_value * (max_position_pct / 100.0)
            
            log.info(f"   Fair Share: ${fair_share:,.2f}")
            log.info(f"   Max Position ({max_position_pct:.0f}% cap): ${max_position_cap:,.2f}")
            log.info(f"")
            
            # STEP 1: Apply rank multipliers
            log.info(f"STEP 1: Apply Rank Multipliers")
            positions = []
            total_raw = 0
            
            for sig in signals:
                rank = sig.get('priority_rank', 999)
                
                # Get multiplier
                if rank == 1:
                    mult = 3.0
                elif rank == 2:
                    mult = 2.5
                elif rank == 3:
                    mult = 2.0
                elif rank <= 5:
                    mult = 1.71
                elif rank <= 10:
                    mult = 1.5
                elif rank <= 15:
                    mult = 1.2
                else:
                    mult = 1.0
                
                raw_value = fair_share * mult
                total_raw += raw_value
                
                positions.append({
                    'signal': sig,
                    'rank': rank,
                    'symbol': sig['symbol'],
                    'price': sig['price'],
                    'raw_value': raw_value,
                    'multiplier': mult
                })
            
            log.info(f"   Total Raw (with multipliers): ${total_raw:,.2f}")
            log.info(f"")
            
            # STEP 2: Apply max position cap
            log.info(f"STEP 2: Apply {max_position_pct:.0f}% Position Cap")
            capped_count = 0
            total_after_cap = 0
            
            for pos in positions:
                if pos['raw_value'] > max_position_cap:
                    pos['value_after_cap'] = max_position_cap
                    pos['capped'] = True
                    capped_count += 1
                    log.info(f"   #{pos['rank']} {pos['symbol']}: ${pos['raw_value']:,.0f} → ${max_position_cap:,.0f} ({max_position_pct:.0f}% cap)")
                else:
                    pos['value_after_cap'] = pos['raw_value']
                    pos['capped'] = False
                
                total_after_cap += pos['value_after_cap']
            
            log.info(f"   Capped: {capped_count} positions")
            log.info(f"   Total After {max_position_pct:.0f}% Cap: ${total_after_cap:,.2f}")
            log.info(f"")
            
            # STEP 3: Apply ADV limits
            log.info(f"STEP 3: Apply ADV Limits")
            adv_manager = get_adv_manager()
            adv_capped_count = 0
            total_after_adv = 0
            
            if adv_manager and adv_manager.enabled:
                for pos in positions:
                    adv_limit = adv_manager.get_adv_limit(pos['symbol'], mode="aggressive")
                    
                    if adv_limit > 0 and pos['value_after_cap'] > adv_limit:
                        freed = pos['value_after_cap'] - adv_limit
                        pos['value_after_adv'] = adv_limit
                        pos['adv_capped'] = True
                        pos['adv_freed'] = freed
                        adv_capped_count += 1
                        
                        adv_dollars = adv_manager.get_adv(pos['symbol'])
                        pct_of_adv = (pos['value_after_cap'] / adv_dollars) * 100 if adv_dollars > 0 else 0
                        log.info(f"   #{pos['rank']} {pos['symbol']}: ${pos['value_after_cap']:,.0f} → ${adv_limit:,.0f} "
                                f"({pct_of_adv:.1f}% → 1.0% ADV)")
                    else:
                        pos['value_after_adv'] = pos['value_after_cap']
                        pos['adv_capped'] = False
                    
                    total_after_adv += pos['value_after_adv']
                
                log.info(f"   ADV Capped: {adv_capped_count} positions")
            else:
                # ADV disabled
                for pos in positions:
                    pos['value_after_adv'] = pos['value_after_cap']
                    pos['adv_capped'] = False
                total_after_adv = total_after_cap
                log.info(f"   ADV Guard: DISABLED")
            
            log.info(f"   Total After ADV: ${total_after_adv:,.2f}")
            log.info(f"")
            
            # STEP 4: Normalize to fit SO capital (FINAL step)
            log.info(f"STEP 4: Normalize to {so_capital_pct:.0f}% (FINAL STEP)")
            
            if total_after_adv > so_capital:
                norm_factor = so_capital / total_after_adv
                log.info(f"   Target: ${so_capital:,.0f}")
                log.info(f"   Current: ${total_after_adv:,.0f}")
                log.info(f"   Normalization Factor: {norm_factor:.4f} ({norm_factor*100:.1f}%)")
            else:
                # Don't scale up (cap at 1.0)
                norm_factor = 1.0
                log.info(f"   No normalization needed (total ${total_after_adv:,.0f} ≤ ${so_capital:,.0f})")
            
            # Apply normalization
            for pos in positions:
                pos['normalized_value'] = pos['value_after_adv'] * norm_factor
            
            log.info(f"")
            
            # STEP 5: Convert to whole shares (constrained sequential)
            log.info(f"STEP 5: Convert to Whole Shares (Constrained Sequential Rounding)")
            
            running_total = 0.0
            final_positions = []
            
            # Sort by rank (process top signals first)
            sorted_positions = sorted(positions, key=lambda p: p['rank'])
            
            for pos in sorted_positions:
                target = pos['normalized_value']
                price = pos['price']
                symbol = pos['symbol']
                rank = pos['rank']
                
                # Calculate shares
                raw_shares = target / price if price > 0 else 0
                shares_down = int(raw_shares)
                shares_up = shares_down + 1
                
                cost_down = shares_down * price
                cost_up = shares_up * price
                
                # Check what fits in remaining budget
                remaining = so_capital - running_total
                
                # Try rounding UP first (better efficiency)
                if cost_up <= remaining and cost_up <= target * 1.10:
                    # Round UP (within 10% overage and fits budget)
                    shares = shares_up
                    cost = cost_up
                elif cost_down <= remaining:
                    # Round DOWN (safe)
                    shares = shares_down
                    cost = cost_down
                else:
                    # Can't fit even rounded down (constrained by budget)
                    max_shares = int(remaining / price) if price > 0 else 0
                    shares = max_shares
                    cost = shares * price
                
                # Ensure at least 1 share if affordable
                if shares == 0 and price <= remaining and price <= target * 2:
                    shares = 1
                    cost = price
                
                # Update running total
                running_total += cost
                
                # Save final position
                final_positions.append({
                    'symbol': symbol,
                    'rank': rank,
                    'shares': shares,
                    'price': price,
                    'actual_cost': cost,
                    'target': target,
                    'adv_capped': pos.get('adv_capped', False),
                    'capped_35': pos.get('capped_35', False)
                })
                
                log.debug(f"   #{rank} {symbol}: {shares} shares × ${price:.2f} = ${cost:.2f} "
                         f"(target ${target:.2f}, running ${running_total:.2f})")
            
            log.info(f"   Final Total: ${running_total:,.2f} ({(running_total/account_value)*100:.1f}% of account)")
            log.info(f"   Target: ${so_capital:,.0f} ({so_capital_pct:.0f}%)")
            log.info(f"   Efficiency: {(running_total/so_capital)*100:.1f}% of target")
            log.info(f"")
            
            # STEP 6: POST-ROUNDING REDISTRIBUTION (Rev 00090)
            # If we have unused capital after whole-share rounding, try to add shares to top-ranked positions
            unused_capital = so_capital - running_total
            
            if unused_capital > 0:
                log.info(f"STEP 6: Post-Rounding Redistribution")
                log.info(f"   Unused Capital: ${unused_capital:,.2f}")
                log.info(f"   Attempting to redistribute to top-ranked positions...")
                log.info(f"")
                
                redistributed = 0.0
                
                # Sort positions by rank for top-down redistribution
                sorted_final = sorted(final_positions, key=lambda p: p['rank'])
                
                for pos in sorted_final:
                    if unused_capital <= 0:
                        break
                    
                    symbol = pos['symbol']
                    price = pos['price']
                    current_shares = pos['shares']
                    current_cost = pos['actual_cost']
                    
                    # Try adding 1 share at a time
                    additional_shares = 0
                    while unused_capital > 0:
                        # Cost of adding 1 more share
                        cost_of_one_more = price
                        
                        # Check if we can afford it
                        if cost_of_one_more <= unused_capital:
                            # Check max position cap from config
                            # Rev 00107: Use config value, not hardcoded 35%
                            new_total_cost = current_cost + (cost_of_one_more * (additional_shares + 1))
                            max_position_cap = account_value * (self.config.max_position_pct / 100.0)
                            
                            if new_total_cost <= max_position_cap:
                                # Can afford and within cap
                                additional_shares += 1
                                unused_capital -= cost_of_one_more
                                redistributed += cost_of_one_more
                            else:
                                # Would exceed 35% cap
                                break
                        else:
                            # Can't afford
                            break
                    
                    if additional_shares > 0:
                        # Update position
                        pos['shares'] += additional_shares
                        pos['actual_cost'] += (additional_shares * price)
                        running_total += (additional_shares * price)
                        
                        log.info(f"   #{pos['rank']} {symbol}: Added {additional_shares} share(s) → "
                                f"{pos['shares']} total (${pos['actual_cost']:,.2f})")
                
                log.info(f"")
                log.info(f"   Redistributed: ${redistributed:,.2f}")
                log.info(f"   Remaining Unused: ${unused_capital:,.2f}")
                log.info(f"   New Total: ${running_total:,.2f} ({(running_total/so_capital)*100:.1f}% of target)")
                log.info(f"")
            
            # Update signals with final quantities
            result_signals = []
            for pos in final_positions:
                # Find original signal
                sig = next((s for s in signals if s['symbol'] == pos['symbol']), None)
                if sig:
                    sig['quantity'] = pos['shares']
                    sig['position_value'] = pos['actual_cost']
                    sig['target_allocation'] = pos['target']
                    result_signals.append(sig)
            
            log.info(f"=" * 80)
            log.info(f"")
            
            return result_signals
            
        except Exception as e:
            log.error(f"Error in batch position sizing: {e}")
            import traceback
            traceback.print_exc()
            return signals

# ============================================================================

def get_prime_demo_risk_manager(strategy_mode: StrategyMode = StrategyMode.STANDARD) -> PrimeDemoRiskManager:
    """Get Prime Demo Risk Manager instance"""
    return PrimeDemoRiskManager(strategy_mode)

def create_demo_risk_manager(strategy_mode: StrategyMode = StrategyMode.STANDARD) -> PrimeDemoRiskManager:
    """Create new Prime Demo Risk Manager instance"""
    return PrimeDemoRiskManager(strategy_mode)
