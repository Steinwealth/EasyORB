#!/usr/bin/env python3
"""
Prime Risk Manager
=================

Comprehensive risk management system implementing the 10 core principles
for the Easy ORB Strategy. This module handles all risk management
decisions for opening new positions.

Last Updated: January 6, 2026 (Rev 00231)
"""

Key Features:
- Multi-layer risk framework with 10 core principles
- Dynamic position sizing with confidence-based scaling
- Trade ownership isolation (only manages Easy ORB Strategy positions)
- Capital allocation with 80/20 rule and dynamic scaling
- Drawdown protection with Safe Mode activation
- News sentiment integration for trade filtering
- Auto-close engine with multiple exit triggers
- End-of-day reporting and P&L tracking
- Capital compounding with risk-weighted allocation
- Re-entry logic with confidence gating
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
# Compound engine removed from Live mode (Rev 00108) - E*TRADE provides all data
from .adv_data_manager import get_adv_manager

log = logging.getLogger("prime_risk_manager")

# ============================================================================
# ENUMS
# ============================================================================

class RiskLevel(Enum):
    """Risk level enumeration"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"

class PositionSizingMethod(Enum):
    """Position sizing method enumeration"""
    FIXED = "fixed"
    PERCENTAGE = "percentage"
    ATR_BASED = "atr_based"
    KELLY = "kelly"
    CONFIDENCE_BASED = "confidence_based"
    DYNAMIC = "dynamic"

class TradeOwnership(Enum):
    """Trade ownership enumeration"""
    EASY_ETRADE_STRATEGY = "EES"
    MANUAL = "MANUAL"
    OTHER_SYSTEM = "OTHER"
    UNKNOWN = "UNKNOWN"

class SafeModeReason(Enum):
    """Safe mode activation reasons"""
    DRAWDOWN_EXCEEDED = "drawdown_exceeded"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MARGIN_CALL = "margin_call"
    SYSTEM_ERROR = "system_error"
    MANUAL_OVERRIDE = "manual_override"

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class RiskParameters:
    """Dynamic risk parameters"""
    # Core risk limits
    max_risk_per_trade_pct: float = 10.0
    cash_reserve_pct: float = 20.0
    trading_cash_pct: float = 80.0
    max_drawdown_pct: float = 10.0
    max_daily_loss_pct: float = 5.0
    
    # Position limits
    max_concurrent_positions: int = 20  # Max open positions at once
    max_positions_per_strategy: int = 5  # Max positions per strategy
    max_daily_trades: int = 200  # Daily trade limit (can close and reopen)
    
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
    base_position_size_pct: float = 10.0  # 10% base position size
    max_position_size_pct: float = 35.0   # 35% max position size (after boosting)
    
    # Transaction costs
    transaction_cost_pct: float = 0.5
    
    # Stop management
    stop_loss_atr_multiplier: float = 1.5
    take_profit_atr_multiplier: float = 2.0

@dataclass
class AccountMetrics:
    """Account metrics for risk assessment"""
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
    """Position risk assessment"""
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
    position_ownership: TradeOwnership = TradeOwnership.EASY_ETRADE_STRATEGY

@dataclass
class RiskDecision:
    """Risk management decision"""
    approved: bool
    reason: str
    risk_level: RiskLevel
    position_size: Optional[PositionRisk] = None
    safe_mode_triggered: bool = False
    safe_mode_reason: Optional[SafeModeReason] = None
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

@dataclass
class MarketConditions:
    """Market conditions for risk adjustment"""
    volatility: float = 0.0
    trend_strength: float = 0.0
    volume_ratio: float = 0.0
    market_regime: MarketRegime = MarketRegime.SIDEWAYS
    vix_level: float = 0.0
    sector_rotation: Dict[str, float] = field(default_factory=dict)

# ============================================================================
# PRIME RISK MANAGER
# ============================================================================

class PrimeRiskManager:
    """
    Prime Risk Manager implementing comprehensive risk management
    for the Easy ORB Strategy with 10 core principles.
    """
    
    def __init__(self, strategy_mode: StrategyMode = StrategyMode.STANDARD):
        self.strategy_mode = strategy_mode
        self.config = get_strategy_config(strategy_mode)
        self.risk_params = self._load_risk_parameters()
        
        # E*TRADE integration for real account data
        self.etrade_trading = None
        self._initialize_etrade_trading()
        
        # Rev 00108: Compound engine REMOVED from Live mode
        # E*TRADE provides all account data directly - no local tracking needed
        
        # Slip Guard ADV Manager (Rev 00046)
        self.adv_manager = get_adv_manager()
        
        # Risk tracking
        self.current_positions: Dict[str, UnifiedPosition] = {}
        self.strategy_positions: Dict[str, UnifiedPosition] = {}
        self.manual_positions: Dict[str, UnifiedPosition] = {}
        self.position_history: deque = deque(maxlen=1000)
        
        # Performance tracking
        self.daily_pnl: float = 0.0
        self.total_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.consecutive_wins: int = 0
        self.win_streak_multiplier: float = 1.0
        
        # Safe mode
        self.safe_mode_active: bool = False
        self.safe_mode_reason: Optional[SafeModeReason] = None
        self.safe_mode_activated_at: Optional[datetime] = None
        
        # Account metrics
        self.account_metrics: Optional[AccountMetrics] = None
        
        # Market conditions
        self.market_conditions: Optional[MarketConditions] = None
        
        log.info(f"PrimeRiskManager initialized for {strategy_mode.value} strategy")
    
    def _initialize_etrade_trading(self):
        """Initialize E*TRADE trading integration for real account data"""
        try:
            from .prime_etrade_trading import PrimeETradeTrading
            
            # Determine environment based on configuration
            etrade_mode = get_config_value('ETRADE_MODE', 'sandbox')
            
            # Initialize E*TRADE trading with environment
            self.etrade_trading = PrimeETradeTrading(environment=etrade_mode)
            
            # Initialize the trading system
            if self.etrade_trading.initialize():
                log.info("✅ Risk Manager E*TRADE integration successful")
                
                # Get account summary for verification
                account_summary = self.etrade_trading.get_account_summary()
                if 'error' not in account_summary:
                    log.info(f"✅ Risk Manager connected to E*TRADE account: {account_summary['account']['name']}")
                    log.info(f"   Cash available for investment: ${account_summary['balance']['cash_available_for_investment']}")
                    log.info(f"   Cash buying power: ${account_summary['balance']['cash_buying_power']}")
                else:
                    log.warning(f"⚠️ Risk Manager E*TRADE account issue: {account_summary['error']}")
            else:
                log.error("❌ Risk Manager E*TRADE integration failed")
                self.etrade_trading = None
                
        except Exception as e:
            log.error(f"❌ Risk Manager E*TRADE integration error: {e}")
            self.etrade_trading = None
    
    def _load_risk_parameters(self) -> RiskParameters:
        """Load risk parameters from configuration"""
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
    
    async def assess_position_risk(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> RiskDecision:
        """
        Comprehensive risk assessment for opening a new position.
        Implements all 10 core risk management principles.
        """
        try:
            log.info(f"Assessing risk for {signal.symbol} position")
            
            # 1. Check Safe Mode status
            if self.safe_mode_active:
                return RiskDecision(
                    approved=False,
                    reason=f"Safe mode active: {self.safe_mode_reason.value if self.safe_mode_reason else 'unknown'}",
                    risk_level=RiskLevel.HIGH,
                    safe_mode_triggered=True,
                    safe_mode_reason=self.safe_mode_reason
                )
            
            # 2. Load current account metrics
            await self._update_account_metrics()
            if not self.account_metrics:
                return RiskDecision(
                    approved=False,
                    reason="Unable to load account metrics",
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
                await self._activate_safe_mode(SafeModeReason.DAILY_LOSS_LIMIT)
                return RiskDecision(
                    approved=False,
                    reason=daily_loss_check["reason"],
                    risk_level=RiskLevel.HIGH,
                    safe_mode_triggered=True,
                    safe_mode_reason=SafeModeReason.DAILY_LOSS_LIMIT
                )
            
            # 5. Check position limits (Principle 7)
            position_limit_check = self._check_position_limits()
            if not position_limit_check["approved"]:
                return RiskDecision(
                    approved=False,
                    reason=position_limit_check["reason"],
                    risk_level=RiskLevel.MEDIUM
                )
            
            # 6. Check news sentiment filtering (Principle 5)
            sentiment_check = self._check_news_sentiment(signal, market_data)
            if not sentiment_check["approved"]:
                return RiskDecision(
                    approved=False,
                    reason=sentiment_check["reason"],
                    risk_level=RiskLevel.MEDIUM
                )
            
            # 7. Calculate dynamic position sizing (Principle 4)
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
            
            # 10. Create approved risk decision
            return RiskDecision(
                approved=True,
                reason="Position approved after comprehensive risk assessment",
                risk_level=final_risk_assessment["risk_level"],
                position_size=position_sizing["position_risk"],
                warnings=final_risk_assessment["warnings"],
                recommendations=final_risk_assessment["recommendations"]
            )
            
        except Exception as e:
            log.error(f"Risk assessment failed for {signal.symbol}: {e}")
            return RiskDecision(
                approved=False,
                reason=f"Risk assessment error: {str(e)}",
                risk_level=RiskLevel.HIGH
            )
    
    async def _update_account_metrics(self):
        """Update account metrics from REAL E*TRADE API"""
        try:
            if not self.etrade_trading:
                log.error("E*TRADE trading not available for account metrics")
                return
            
            # Get REAL account balance from E*TRADE
            import asyncio
            balance = await asyncio.to_thread(self.etrade_trading.get_account_balance)
            if not balance:
                log.error("Failed to get account balance from E*TRADE")
                return
            
            # Get current positions from E*TRADE
            portfolio = await asyncio.to_thread(self.etrade_trading.get_portfolio)
            
            # Calculate REAL metrics from E*TRADE data
            available_cash = balance.cash_available_for_investment or 0.0
            total_value = balance.account_value or available_cash
            # Rev 00101: Use unified config (adjustable in ONE place)
            cash_reserve = total_value * (self.config.cash_reserve_pct / 100.0)
            trading_cash = total_value * ((100.0 - self.config.cash_reserve_pct) / 100.0)
            
            # CRITICAL: Calculate Prime System position value (only positions opened by THIS system)
            # Filter positions by checking if they're in our strategy_positions tracking dict
            prime_positions = [p for p in portfolio if p.symbol in self.strategy_positions]
            prime_system_position_value = sum(p.market_value for p in prime_positions)
            
            # Count strategy positions vs manual positions
            strategy_positions_count = len(prime_positions)
            manual_positions_count = len(portfolio) - strategy_positions_count
            
            # Calculate drawdown from peak capital
            current_drawdown_pct = 0.0
            if hasattr(self, 'peak_capital') and self.peak_capital > 0:
                current_drawdown_pct = max(0.0, (self.peak_capital - total_value) / self.peak_capital)
            
            self.account_metrics = AccountMetrics(
                available_cash=available_cash,
                total_account_value=total_value,
                cash_reserve=cash_reserve,
                trading_cash=trading_cash,
                margin_available=balance.cash_buying_power,
                buying_power=balance.cash_buying_power,
                current_drawdown_pct=current_drawdown_pct,
                daily_pnl_pct=self.daily_pnl / total_value if total_value > 0 else 0.0,
                total_open_positions=len(portfolio),
                strategy_positions=strategy_positions_count,
                manual_positions=manual_positions_count,
                prime_system_position_value=prime_system_position_value  # CRITICAL: Only Prime system positions
            )
            
            log.info(f"✅ REAL account metrics updated from E*TRADE: ${available_cash:.2f} available cash, ${total_value:.2f} total value")
            log.info(f"📊 Position breakdown: {strategy_positions_count} Prime positions (${prime_system_position_value:.2f}), {manual_positions_count} manual/other positions (IGNORED)")
            
            # Rev 00108: Compound engine REMOVED from Live mode
            # E*TRADE provides all account data directly - no local tracking needed
            # Available capital comes from E*TRADE's cash_available_for_investment
            
        except Exception as e:
            log.error(f"Failed to update account metrics from E*TRADE: {e}")
    
    def _check_drawdown_protection(self) -> Dict[str, Any]:
        """Check drawdown protection (Principle 7)"""
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
        """Check daily loss limits"""
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
        """Check position limits (Principle 7)"""
        if not self.account_metrics:
            return {"approved": False, "reason": "No account metrics available"}
        
        current_positions = self.account_metrics.strategy_positions
        max_positions = self.risk_params.max_concurrent_positions
        
        if current_positions >= max_positions:
            return {
                "approved": False,
                "reason": f"Position limit reached: {current_positions}/{max_positions}"
            }
        
        # Check portfolio risk limits
        max_portfolio_risk_pct = get_config_value("MAX_PORTFOLIO_RISK_PCT", 80.0)
        total_account_value = self.account_metrics.total_account_value
        trading_cash = self.account_metrics.trading_cash
        
        # Calculate current portfolio risk percentage
        current_portfolio_risk_pct = (trading_cash / total_account_value) * 100.0
        
        if current_portfolio_risk_pct >= max_portfolio_risk_pct:
            return {
                "approved": False,
                "reason": f"Portfolio risk limit reached: {current_portfolio_risk_pct:.1f}% >= {max_portfolio_risk_pct}%"
            }
        
        return {"approved": True}
    
    def _check_news_sentiment(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Check news sentiment filtering (Principle 5)"""
        try:
            # Get news sentiment from market data
            news_sentiment = market_data.get("news_sentiment", {})
            sentiment_score = news_sentiment.get("sentiment_score", 0.0)
            sentiment_direction = news_sentiment.get("direction", "neutral")
            
            # Check for divergent sentiment
            if signal.side == SignalSide.BUY and sentiment_direction == "negative":
                return {
                    "approved": False,
                    "reason": f"Negative news sentiment ({sentiment_score:.2f}) conflicts with buy signal"
                }
            elif signal.side == SignalSide.SELL and sentiment_direction == "positive":
                return {
                    "approved": False,
                    "reason": f"Positive news sentiment ({sentiment_score:.2f}) conflicts with sell signal"
                }
            
            return {"approved": True}
            
        except Exception as e:
            log.warning(f"News sentiment check failed: {e}")
            return {"approved": True}  # Allow trade if sentiment check fails
    
    async def _calculate_position_sizing(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate position sizing with boosting factors and 80/20 rule
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
            
            if current_price <= 0:
                return {"approved": False, "reason": "Invalid current price"}
            
            # Rev 00108: Live mode uses E*TRADE directly - no compound engine needed
            # E*TRADE provides exact cash_available_for_investment (already includes freed capital)
            # This is always accurate and current - no local tracking needed
            available_capital = self.account_metrics.available_cash
            log.debug(f"  E*TRADE: ${available_capital:.2f} cash available for investment (real-time)")
            
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
            # If prime_trading_system calculated a final position value after redistribution,
            # use that instead of recalculating (ensures capital efficiency)
            position_value_override = market_data.get('position_value_override')
            if position_value_override is not None and position_value_override > 0:
                original_position_value = position_value
                position_value = position_value_override
                log.info(f"🎯 POST-ROUNDING OVERRIDE: ${original_position_value:.2f} → ${position_value:.2f} (redistributed capital)")
            
            # 7.5 RANK-BASED POSITION SIZING (Rev 00180AE - Gradual Scaling by Rank)
            # Uses priority score ranking (confidence already weighted at 40%)
            # Rank #1 gets maximum boost (3.0x), gradually decreasing by rank
            
            priority_rank = market_data.get('priority_rank', 999)
            priority_score = market_data.get('priority_score', 0.0)
            
            if priority_rank == 1:
                # RANK #1: Maximum allocation (best signal)
                boost = 3.0
                log.info(f"🚀 RANK #1 MAXIMUM {signal.symbol}: 3.0x (Priority: {priority_score:.3f})")
            elif priority_rank == 2:
                # RANK #2: Very high allocation
                boost = 2.5
                log.info(f"🌟 RANK #2 VERY HIGH {signal.symbol}: 2.5x (Priority: {priority_score:.3f})")
            elif priority_rank == 3:
                # RANK #3: High allocation
                boost = 2.0
                log.info(f"⭐ RANK #3 HIGH {signal.symbol}: 2.0x (Priority: {priority_score:.3f})")
            elif priority_rank <= 5:
                # RANK 4-5: Above average
                boost = 1.71
                log.info(f"🔥 RANK #{priority_rank} ABOVE AVG {signal.symbol}: 1.71x (Priority: {priority_score:.3f})")
            elif priority_rank <= 10:
                # RANK 6-10: Moderate boost
                boost = 1.5
                log.info(f"📈 RANK #{priority_rank} MODERATE {signal.symbol}: 1.5x (Priority: {priority_score:.3f})")
            elif priority_rank <= 15:
                # RANK 11-15: Small boost
                boost = 1.2
                log.info(f"📊 RANK #{priority_rank} SMALL {signal.symbol}: 1.2x (Priority: {priority_score:.3f})")
            elif priority_rank <= 20:
                # RANK 16-20: Base allocation
                boost = 1.0
                log.info(f"✅ RANK #{priority_rank} BASE {signal.symbol}: 1.0x (Priority: {priority_score:.3f})")
            else:
                # RANK 21+: Reduced (should be filtered out by trading system)
                boost = 0.8
                log.debug(f"⚪ RANK #{priority_rank} {signal.symbol}: 0.8x (low priority)")
            
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
            
            # 8. Apply maximum position size limit (35% of total account value)
            # FIX (Oct 24, 2025): Cap at 35% (not 70%) to match Demo mode and user requirements
            try:
                # Rev 00180Z: Fix variable name error (was: prime_system_portfolio_value)
                total_portfolio_value = available_capital + self.account_metrics.prime_system_position_value
                
                # Handle string values with comments
                max_position_size_str = str(self.risk_params.max_position_size_pct).split('#')[0].strip()
                max_position_size_pct = float(max_position_size_str)
                
                # FIX (Oct 24, 2025): Cap at 35% (not 70%)
                max_position_size_pct = min(max_position_size_pct, 35.0)
                
                max_position_value = total_portfolio_value * (max_position_size_pct / 100.0)
                position_value = min(position_value, max_position_value)
            except (TypeError, ValueError) as e:
                log.error(f"Error in max position size calculation: {e}, value: {self.risk_params.max_position_size_pct}")
                # FIX (Oct 24, 2025): Use 35% default (not 70%)
                total_portfolio_value = available_capital + self.account_metrics.prime_system_position_value
                max_position_value = total_portfolio_value * 0.35
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
            # If not enough cash, reduce position size to available cash or reject
            if position_value > available_capital:
                if available_capital < 50.0:  # Minimum $50 position
                    log.warning(f"Insufficient cash for position: ${position_value:.2f} > ${available_capital:.2f}")
                    return PositionRisk(
                        position_value=0.0,
                        quantity=0.0,
                        risk_percentage=0.0,
                        confidence_multiplier=confidence_multiplier,
                        agreement_bonus=agreement_bonus,
                        risk_level=RiskLevel.HIGH,
                        reasoning="Insufficient available cash for position"
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
            
            # Create position risk object
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
            log.info(f"💰 Position sizing calculated for {signal.symbol} ({trade_type_str}): "
                    f"${position_value:.2f} value ({risk_percentage:.1f}% of portfolio), {quantity} shares, "
                    f"Available Cash: ${available_capital:.2f}, Base Position: ${base_position_value:.2f}, "
                    f"Concurrent: {num_concurrent_positions}, Conf Mult: {confidence_multiplier:.2f}x")
            
            return {
                "approved": True,
                "position_risk": position_risk
            }
            
        except Exception as e:
            log.error(f"Position sizing calculation failed: {e}")
            return {"approved": False, "reason": f"Position sizing error: {str(e)}"}
    
    def _get_confidence_multiplier(self, confidence: float) -> float:
        """Get confidence multiplier for position sizing (Principle 6) - IDENTICAL to Demo Mode"""
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
        """Get profit-based scaling multiplier for position sizing (NEW FEATURE)"""
        if not self.account_metrics:
            return 1.0
        
        # Calculate profit percentage from initial capital
        # Assuming initial capital was $10,000 (can be made configurable)
        initial_capital = 10000.0
        current_value = self.account_metrics.total_account_value
        profit_pct = (current_value - initial_capital) / initial_capital
        
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
            scaling_multiplier = 1.0  # No scaling for small profits or losses
        
        log.debug(f"Profit scaling multiplier: {profit_pct:.1%} profit -> {scaling_multiplier:.2f}x scaling")
        return scaling_multiplier
    
    def _get_strategy_agreement_bonus(self, signal: PrimeSignal, market_data: Dict[str, Any]) -> float:
        """Get strategy agreement bonus for position sizing"""
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
        """Get win streak multiplier for position sizing"""
        # This would track consecutive wins and apply multiplier
        # For now, return 1.0 as placeholder
        return self.win_streak_multiplier
    
    
    def _final_risk_assessment(self, position_risk: PositionRisk) -> Dict[str, Any]:
        """Final risk assessment and warnings"""
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
        if position_risk.confidence < 0.90:
            warnings.append(f"Low confidence level: {position_risk.confidence:.3f}")
            recommendations.append("Consider waiting for higher confidence signals")
        
        # Check risk-reward ratio
        if position_risk.risk_reward_ratio < 1.5:
            warnings.append(f"Low risk-reward ratio: {position_risk.risk_reward_ratio:.2f}")
            recommendations.append("Consider adjusting stop loss or take profit levels")
        
        # Check position size
        if position_risk.net_position_value < 100.0:
            warnings.append(f"Small position size: ${position_risk.net_position_value:.2f}")
            recommendations.append("Position may not be profitable after transaction costs")
        
        return {
            "risk_level": risk_level,
            "warnings": warnings,
            "recommendations": recommendations
        }
    
    async def _activate_safe_mode(self, reason: SafeModeReason):
        """Activate safe mode (Principle 7)"""
        self.safe_mode_active = True
        self.safe_mode_reason = reason
        self.safe_mode_activated_at = datetime.utcnow()
        
        log.warning(f"Safe mode activated: {reason.value}")
        
        # Send alert about safe mode activation
        await self._send_safe_mode_alert(reason)
    
    async def _deactivate_safe_mode(self):
        """Deactivate safe mode when conditions improve"""
        if self.safe_mode_active:
            self.safe_mode_active = False
            self.safe_mode_reason = None
            self.safe_mode_activated_at = None
            
            log.info("Safe mode deactivated")
            
            # Send alert about safe mode deactivation
            await self._send_safe_mode_alert(None, deactivated=True)
    
    async def _send_safe_mode_alert(self, reason: Optional[SafeModeReason], deactivated: bool = False):
        """Send safe mode alert via Telegram"""
        try:
            from .prime_alert_manager import get_prime_alert_manager
            
            alert_manager = get_prime_alert_manager()
            
            if deactivated:
                message = "🟢 **Safe Mode Deactivated**\n\nTrading has resumed normal operations."
                urgency = "INFO"
            else:
                message = f"🔴 **Safe Mode Activated**\n\nReason: {reason.value if reason else 'Unknown'}\n\nTrading has been suspended for risk management."
                urgency = "HIGH"
            
            await alert_manager.send_alert("SAFE_MODE", message, urgency)
            
        except Exception as e:
            log.error(f"Failed to send safe mode alert: {e}")
    
    def get_risk_summary(self) -> Dict[str, Any]:
        """Get comprehensive risk summary"""
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
                "win_streak_multiplier": self.win_streak_multiplier
            },
            "positions": {
                "total": len(self.current_positions),
                "strategy": len(self.strategy_positions),
                "manual": len(self.manual_positions)
            }
        }
    
    async def calculate_batch_position_sizes(self, signals: List[Dict[str, Any]], 
                                            so_capital: float, account_value: float,
                                            max_position_pct: float = 35.0) -> List[Dict[str, Any]]:
        """
        Calculate position sizes for a batch of signals (Rev 00084)
        
        Same logic as Demo Risk Manager for consistency.
        See prime_demo_risk_manager.py for detailed documentation.
        """
        try:
            from .adv_data_manager import get_adv_manager
            
            so_capital_pct = (so_capital / account_value) * 100.0 if account_value > 0 else 90.0
            
            log.info(f"")
            log.info(f"=" * 80)
            log.info(f"📊 LIVE BATCH POSITION SIZING (Rev 00084 Clean Flow)")
            log.info(f"=" * 80)
            log.info(f"   Account: ${account_value:,.0f}")
            log.info(f"   SO Capital ({so_capital_pct:.0f}%): ${so_capital:,.0f}")
            log.info(f"   Signals: {len(signals)}")
            log.info(f"")
            
            # Calculate fair share and position cap
            fair_share = so_capital / max(1, len(signals))
            max_position_cap = account_value * (max_position_pct / 100.0)
            
            # STEP 1: Apply rank multipliers
            positions = []
            total_raw = 0
            
            for sig in signals:
                rank = sig.get('priority_rank', 999)
                
                # Get multiplier (same as Demo)
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
            
            log.info(f"   Total Raw: ${total_raw:,.2f}")
            
            # STEP 2: Apply max position cap
            total_after_cap = 0
            for pos in positions:
                if pos['raw_value'] > max_position_cap:
                    pos['value_after_cap'] = max_position_cap
                    pos['capped'] = True
                else:
                    pos['value_after_cap'] = pos['raw_value']
                    pos['capped'] = False
                total_after_cap += pos['value_after_cap']
            
            # STEP 3: Apply ADV limits
            adv_manager = get_adv_manager()
            total_after_adv = 0
            
            if adv_manager and adv_manager.enabled:
                for pos in positions:
                    adv_limit = adv_manager.get_adv_limit(pos['symbol'], mode="aggressive")
                    
                    if adv_limit > 0 and pos['value_after_cap'] > adv_limit:
                        pos['value_after_adv'] = adv_limit
                        pos['adv_capped'] = True
                    else:
                        pos['value_after_adv'] = pos['value_after_cap']
                        pos['adv_capped'] = False
                    
                    total_after_adv += pos['value_after_adv']
            else:
                for pos in positions:
                    pos['value_after_adv'] = pos['value_after_cap']
                    pos['adv_capped'] = False
                total_after_adv = total_after_cap
            
            # STEP 4: Normalize (cap at 1.0, never scale up)
            norm_factor = min(1.0, so_capital / total_after_adv) if total_after_adv > 0 else 1.0
            
            for pos in positions:
                pos['normalized_value'] = pos['value_after_adv'] * norm_factor
            
            log.info(f"   Normalization Factor: {norm_factor:.4f}")
            
            # STEP 5: Constrained sequential rounding
            running_total = 0.0
            final_positions = []
            sorted_positions = sorted(positions, key=lambda p: p['rank'])
            
            for pos in sorted_positions:
                target = pos['normalized_value']
                price = pos['price']
                
                raw_shares = target / price if price > 0 else 0
                shares_down = int(raw_shares)
                shares_up = shares_down + 1
                
                cost_down = shares_down * price
                cost_up = shares_up * price
                remaining = so_capital - running_total
                
                # Try rounding UP
                if cost_up <= remaining and cost_up <= target * 1.10:
                    shares, cost = shares_up, cost_up
                elif cost_down <= remaining:
                    shares, cost = shares_down, cost_down
                else:
                    shares = int(remaining / price) if price > 0 else 0
                    cost = shares * price
                
                if shares == 0 and price <= remaining:
                    shares, cost = 1, price
                
                running_total += cost
                
                final_positions.append({
                    'symbol': pos['symbol'],
                    'rank': pos['rank'],
                    'shares': shares,
                    'price': price,
                    'actual_cost': cost
                })
            
            log.info(f"   Final Total: ${running_total:,.2f} ({(running_total/account_value)*100:.1f}%)")
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
            
            # Update signals
            result_signals = []
            for pos in final_positions:
                sig = next((s for s in signals if s['symbol'] == pos['symbol']), None)
                if sig:
                    sig['quantity'] = pos['shares']
                    sig['position_value'] = pos['actual_cost']
                    result_signals.append(sig)
            
            return result_signals
            
        except Exception as e:
            log.error(f"Error in Live batch position sizing: {e}")
            return signals

# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def get_prime_risk_manager(strategy_mode: StrategyMode = StrategyMode.STANDARD) -> PrimeRiskManager:
    """Get Prime Risk Manager instance"""
    return PrimeRiskManager(strategy_mode)
