# modules/prime_models.py

"""
Unified Data Models for Easy ORB Strategy
Consolidates all data structures from across the strategy system
Eliminates redundancy and provides single source of truth

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0

Timestamp Convention:
    All datetime objects are stored as NAIVE UTC timestamps (no timezone info).
    Use datetime.utcnow() for creation, and assume all timestamps are UTC.
    This ensures consistency across logging, serialization, and API calls.
"""

from __future__ import annotations
import os
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Literal

log = logging.getLogger("unified_models")

# ============================================================================
# UTILITY HELPERS
# ============================================================================

def _clamp(value: Optional[float], lo: float, hi: float) -> Optional[float]:
    """Clamp a value to a range, preserving None"""
    return None if value is None else max(lo, min(hi, value))

def _require_non_negative(value: Optional[float], name: str) -> None:
    """Require a value to be non-negative, raising ValueError if not"""
    if value is not None and value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")

def _parse_timestamp(val: Any) -> datetime:
    """Parse timestamp from various formats (datetime, ISO string, etc.)"""
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            # Handle ISO format with Z timezone
            return datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.utcnow()

def _enum_to_value(obj: Any) -> Any:
    """
    Recursively convert enums to their values for safe serialization.
    
    Useful for asdict() serialization when dataclasses contain enum fields.
    Handles nested dicts and lists.
    
    Note: For more comprehensive serialization (enums + datetimes), use _serialize().
    """
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _enum_to_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_enum_to_value(v) for v in obj]
    return obj

def _serialize(obj: Any) -> Any:
    """
    Comprehensive serialization for logging/JSON: handles dataclasses, enums, datetimes, nested structures.
    
    Converts:
        - datetime → ISO format with 'Z' suffix (UTC)
        - Enum → value
        - dataclass → dict (recursively serialized)
        - dict/list → recursively serialized
    
    Returns:
        Plain Python types suitable for JSON/logging
    """
    from dataclasses import is_dataclass
    
    if isinstance(obj, datetime):
        return obj.isoformat() + "Z"
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    return obj

def ind(snapshot: 'MarketSnapshot', name: str, default: Any = 0.0) -> Any:
    """
    Convenience function to safely extract indicator from MarketSnapshot.
    
    Args:
        snapshot: MarketSnapshot instance
        name: Indicator field name
        default: Default value if not found
    
    Returns:
        Indicator value or default
    
    Example:
        rsi = ind(snapshot, 'rsi', 50.0)
    """
    return get_indicator_safely(snapshot.indicators, name, default)

def validate_stops(entry: float, stop: Optional[float], tp: Optional[float], side: 'SignalSide') -> bool:
    """
    Validate stop loss and take profit levels are logically correct.
    
    Args:
        entry: Entry price
        stop: Stop loss price (optional)
        tp: Take profit price (optional)
        side: Position side
    
    Returns:
        True if stops are valid or missing, False if clearly invalid
    
    Logic:
        - LONG/BUY: stop < entry < take_profit
        - SHORT/SELL: take_profit < entry < stop
    """
    if stop is None or tp is None:
        return True  # Missing stops are allowed
    
    if side in (SignalSide.LONG, SignalSide.BUY):
        return stop < entry < tp
    return tp < entry < stop

# ============================================================================
# ENUMS
# ============================================================================

class SystemMode(Enum):
    """System operation modes"""
    FULL_TRADING = "full_trading"
    SIGNAL_ONLY = "signal_only"
    ANALYSIS_ONLY = "analysis_only"
    BACKTEST = "backtest"
    PAPER_TRADING = "paper_trading"

class StrategyMode(Enum):
    """Strategy mode enumeration"""
    STANDARD = "standard"
    ADVANCED = "advanced"
    QUANTUM = "quantum"

class SignalType(Enum):
    """Signal type enumeration"""
    ENTRY = "entry"
    EXIT = "exit"

class SignalSide(Enum):
    """Signal side enumeration"""
    LONG = "long"
    SHORT = "short"
    BUY = "buy"      # Backward compatibility
    SELL = "sell"    # Backward compatibility

class TradeStatus(Enum):
    """Trade status enumeration"""
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    PENDING = "pending"

class StopType(Enum):
    """Stop type enumeration"""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    BREAK_EVEN = "break_even"
    VOLUME_STOP = "volume_stop"
    TIME_STOP = "time_stop"

class TrailingMode(Enum):
    """Trailing stop modes"""
    BREAK_EVEN = "break_even"
    ATR_TRAILING = "atr_trailing"
    PERCENTAGE_TRAILING = "percentage_trailing"
    MOMENTUM_TRAILING = "momentum_trailing"
    EXPLOSIVE_TRAILING = "explosive_trailing"
    MOON_TRAILING = "moon_trailing"
    VOLUME_TRAILING = "volume_trailing"

class MarketRegime(Enum):
    """Market regime enumeration"""
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    VOLATILE = "volatile"

class SignalQuality(Enum):
    """Signal quality enumeration"""
    ULTRA_HIGH = "ultra_high"     # 99%+ confidence
    VERY_HIGH = "very_high"       # 95-98% confidence
    HIGH = "high"                 # 90-94% confidence
    MEDIUM = "medium"             # 80-89% confidence
    LOW = "low"                   # 70-79% confidence

class ConfidenceTier(Enum):
    """Confidence tiers for position sizing"""
    ULTRA = "ultra"          # 99.5%+
    EXTREME = "extreme"      # 99.0-99.4%
    VERY_HIGH = "very_high"  # 97.5-98.9%
    HIGH = "high"           # 95.0-97.4%
    STANDARD = "standard"   # 90.0-94.9%

class AgreementLevel(Enum):
    """Strategy agreement level for multi-strategy analysis"""
    NONE = "none"        # 0 strategies agree
    LOW = "low"          # 1 strategy agrees
    MEDIUM = "medium"    # 2 strategies agree
    HIGH = "high"        # 3 strategies agree
    MAXIMUM = "maximum"  # 4+ strategies agree

# ============================================================================
# CORE DATA STRUCTURES
# ============================================================================

@dataclass(slots=True)
class TechnicalIndicators:
    """Comprehensive technical indicators"""
    # Price data
    open: float
    high: float
    low: float
    close: float
    volume: float  # Changed from int for consistency with MarketSnapshot.volumes
    
    # Moving averages
    sma_20: float = 0.0
    sma_50: float = 0.0
    sma_200: float = 0.0
    ema_12: float = 0.0
    ema_26: float = 0.0
    
    # Momentum
    rsi: float = 0.0
    rsi_14: float = 0.0
    rsi_21: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    stoch_k: float = 0.0
    stoch_d: float = 0.0
    
    # Volatility
    atr: float = 0.0
    bollinger_upper: float = 0.0
    bollinger_middle: float = 0.0
    bollinger_lower: float = 0.0
    bollinger_width: float = 0.0
    
    # Volume
    obv: float = 0.0
    ad_line: float = 0.0
    volume_sma: float = 0.0
    volume_ratio: float = 0.0
    
    # Patterns
    doji: bool = False
    hammer: bool = False
    engulfing: bool = False
    morning_star: bool = False

@dataclass(slots=True)
class MarketSnapshot:
    """
    Unified market data snapshot for strategy analysis.
    
    Provides a standardized interface for market data across all strategies,
    data managers, and analysis components. Ensures all components speak
    the same language when consuming market data.
    
    Sentiment Fields:
        - news_sentiment: Raw sentiment polarity in range -1.0 to +1.0
        - news_sentiment_score: Confidence/strength of sentiment in range 0.0 to 1.0
        - news_count: Number of news items analyzed
    
    ETF Alignment Fields:
        - etf_type: 'bull' (e.g., SOXL/TQQQ), 'bear' (SOXS/SQQQ), or None
        - pair_bias: 'aligned' if sentiment matches exposure, else 'misaligned'
        - underlying_asset: The underlying asset/sector (e.g., 'semiconductors')
        - counterpart_etf: The paired ETF ticker (bull's bear or vice versa)
    """
    symbol: str
    timestamp: datetime
    
    # Price data (OHLCV)
    prices: List[float] = field(default_factory=list)
    volumes: List[float] = field(default_factory=list)
    open_prices: Optional[List[float]] = None
    high_prices: Optional[List[float]] = None
    low_prices: Optional[List[float]] = None
    
    # Current values
    current_price: float = 0.0
    current_volume: float = 0.0
    
    # Spread data (for spread caps)
    # Note: spread_pct auto-computed in __post_init__ if not provided
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    
    # Volume analysis (for volume surge strategies)
    # volume_ratio: current volume vs 20-day average (e.g., 1.5 = 50% above avg)
    # volume_surge: real-time surge multiplier (e.g., 1.8 = 1.8x baseline)
    volume_ratio: Optional[float] = None
    volume_surge: Optional[float] = None
    avg_volume: Optional[float] = None
    
    # ORB (Opening Range Breakout) data
    orb_score: Optional[float] = None
    orb_high: Optional[float] = None
    orb_low: Optional[float] = None
    orb_range: Optional[float] = None
    
    # News sentiment (for sentiment strategies)
    news_sentiment: Optional[float] = None  # Raw polarity: -1.0 to +1.0
    news_sentiment_score: Optional[float] = None  # Confidence: 0.0 to 1.0
    news_count: Optional[int] = None
    
    # Bull/Bear ETF alignment
    etf_type: Optional[str] = None  # 'bull' (SOXL/TQQQ), 'bear' (SOXS/SQQQ), or None
    underlying_asset: Optional[str] = None
    pair_bias: Optional[str] = None  # 'aligned' if sentiment matches exposure, else 'misaligned'
    counterpart_etf: Optional[str] = None
    
    # Technical indicators (optional, can be computed on-demand)
    indicators: Optional[TechnicalIndicators] = None
    
    # Market metadata
    market_phase: Optional[str] = None
    market_regime: Optional[MarketRegime] = None
    
    # Data quality
    data_points: int = 0
    data_quality_score: float = 1.0
    
    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Auto-compute derived fields and validate inputs after initialization"""
        # Default current_price from bid/ask if not provided
        if not self.current_price and self.bid is not None and self.ask is not None:
            self.current_price = (self.bid + self.ask) / 2.0
        
        # Validate non-negative values (catch bad feeds early)
        _require_non_negative(self.current_price, "current_price")
        _require_non_negative(self.current_volume, "current_volume")
        
        # Auto-compute spread_pct if not provided
        if self.spread_pct is None:
            if self.spread is not None and self.current_price:
                self.spread_pct = self.spread / max(self.current_price, 1e-9)
            elif self.bid is not None and self.ask is not None and self.current_price:
                self.spread = self.ask - self.bid
                self.spread_pct = self.spread / max(self.current_price, 1e-9)
        
        # Clamp sentiment values to valid ranges (guard against bad feeds)
        self.news_sentiment = _clamp(self.news_sentiment, -1.0, 1.0)
        self.news_sentiment_score = _clamp(self.news_sentiment_score, 0.0, 1.0)
        
        # Clamp volume ratios to non-negative (defuse bad feeds)
        self.volume_ratio = None if self.volume_ratio is None else max(0.0, self.volume_ratio)
        self.volume_surge = None if self.volume_surge is None else max(0.0, self.volume_surge)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for backward compatibility"""
        # Serialize indicators safely (convert dataclass to dict for JSON compatibility)
        indicators_data = None
        if self.indicators is not None:
            indicators_data = asdict(self.indicators) if isinstance(self.indicators, TechnicalIndicators) else self.indicators
        
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'prices': self.prices,
            'volumes': self.volumes,
            'open': self.open_prices,
            'high': self.high_prices,
            'low': self.low_prices,
            'current_price': self.current_price,
            'current_volume': self.current_volume,
            # Spread data
            'bid': self.bid,
            'ask': self.ask,
            'spread': self.spread,
            'spread_pct': self.spread_pct,
            # Volume analysis
            'volume_ratio': self.volume_ratio,
            'volume_surge': self.volume_surge,
            'avg_volume': self.avg_volume,
            # ORB data
            'orb_score': self.orb_score,
            'orb_high': self.orb_high,
            'orb_low': self.orb_low,
            'orb_range': self.orb_range,
            # News sentiment
            'news_sentiment': self.news_sentiment,
            'news_sentiment_score': self.news_sentiment_score,
            'news_count': self.news_count,
            # ETF alignment
            'etf_type': self.etf_type,
            'underlying_asset': self.underlying_asset,
            'pair_bias': self.pair_bias,
            'counterpart_etf': self.counterpart_etf,
            # Technical indicators (serialized safely for JSON/loggers)
            'indicators': indicators_data,
            # Market metadata
            'market_phase': self.market_phase,
            'market_regime': _enum_to_value(self.market_regime),
            # Data quality
            'data_points': self.data_points,
            'data_quality_score': self.data_quality_score,
            # Additional context
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketSnapshot':
        """
        Create MarketSnapshot from dictionary (backward compatibility).
        
        Note: Incoming timestamp strings (e.g., ISO format) are parsed and
        normalized to naive UTC datetime objects for consistency.
        """
        # Handle market_regime conversion from string
        market_regime = data.get('market_regime')
        if isinstance(market_regime, str):
            try:
                market_regime = MarketRegime(market_regime)
            except ValueError:
                market_regime = None
        
        return cls(
            symbol=data.get('symbol', ''),
            timestamp=_parse_timestamp(data.get('timestamp')),
            prices=data.get('prices', []),
            volumes=data.get('volumes', []),
            open_prices=data.get('open'),
            high_prices=data.get('high'),
            low_prices=data.get('low'),
            current_price=data.get('current_price', data.get('prices', [0])[-1] if data.get('prices') else 0.0),
            current_volume=data.get('current_volume', data.get('volumes', [0])[-1] if data.get('volumes') else 0.0),
            # Spread data
            bid=data.get('bid'),
            ask=data.get('ask'),
            spread=data.get('spread'),
            spread_pct=data.get('spread_pct'),
            # Volume analysis
            volume_ratio=data.get('volume_ratio'),
            volume_surge=data.get('volume_surge'),
            avg_volume=data.get('avg_volume'),
            # ORB data
            orb_score=data.get('orb_score'),
            orb_high=data.get('orb_high'),
            orb_low=data.get('orb_low'),
            orb_range=data.get('orb_range'),
            # News sentiment
            news_sentiment=data.get('news_sentiment'),
            news_sentiment_score=data.get('news_sentiment_score'),
            news_count=data.get('news_count'),
            # ETF alignment
            etf_type=data.get('etf_type'),
            underlying_asset=data.get('underlying_asset'),
            pair_bias=data.get('pair_bias'),
            counterpart_etf=data.get('counterpart_etf'),
            # Technical indicators
            indicators=data.get('indicators'),
            # Market metadata
            market_phase=data.get('market_phase'),
            market_regime=market_regime,
            # Data quality
            data_points=data.get('data_points', len(data.get('prices', []))),
            data_quality_score=data.get('data_quality_score', 1.0),
            # Additional context
            metadata=data.get('metadata', {})
        )

@dataclass(slots=True)
class PrimeSignal:
    """Unified signal data structure"""
    symbol: str
    signal_type: SignalType
    side: SignalSide
    confidence: float
    quality: SignalQuality
    price: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Technical data
    indicators: Optional[TechnicalIndicators] = None
    orb_score: float = 0.0
    volume_analysis: Optional[Dict[str, Any]] = None
    
    # Risk management (Rev 00173 - ORB Strategy)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    expected_return: float = 0.0
    quality_score: float = 0.0
    
    # Strategy data
    strategy_mode: StrategyMode = StrategyMode.STANDARD
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_confidence(cls, *, symbol: str, signal_type: SignalType, side: SignalSide,
                        confidence: float, price: float, **kwargs) -> 'PrimeSignal':
        """
        Convenience constructor that auto-maps confidence to quality.
        
        Prevents callers from forgetting to set quality based on confidence.
        
        Args:
            symbol: Trading symbol
            signal_type: Type of signal (ENTRY/EXIT)
            side: Signal side (LONG/SHORT/BUY/SELL)
            confidence: Confidence level (0.0-1.0)
            price: Signal price
            **kwargs: Additional fields (indicators, orb_score, etc.)
        
        Returns:
            PrimeSignal with quality automatically determined from confidence
        """
        return cls(
            symbol=symbol,
            signal_type=signal_type,
            side=side,
            confidence=confidence,
            quality=determine_signal_quality(confidence),
            price=price,
            **kwargs
        )

@dataclass(slots=True)
class PrimePosition:
    """Unified position data structure"""
    # Core position data
    position_id: str
    symbol: str
    side: SignalSide
    quantity: int
    entry_price: float
    current_price: float
    entry_time: datetime = field(default_factory=datetime.utcnow)
    status: TradeStatus = TradeStatus.OPEN
    
    # PnL data
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    pnl_pct: float = 0.0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    position_value: float = 0.0  # Oct 27, 2025: CRITICAL for stealth trailing integration
    
    # Risk management
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    stop_type: StopType = StopType.STOP_LOSS
    trailing_mode: TrailingMode = TrailingMode.BREAK_EVEN
    atr_multiplier: float = 1.8
    
    # Signal data
    confidence: float = 0.0
    quality_score: float = 0.0
    strategy_mode: StrategyMode = StrategyMode.STANDARD
    signal_reason: str = ""
    reason: str = ""  # Backward compatibility alias for signal_reason
    
    # Performance tracking
    holding_period: float = 0.0
    risk_taken: float = 0.0
    reward_achieved: float = 0.0
    risk_reward_ratio: float = 0.0
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate position invariants"""
        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if self.entry_price <= 0:
            raise ValueError(f"entry_price must be > 0, got {self.entry_price}")
    
    def mark(self, price: float) -> None:
        """
        Mark position to current price and update PnL.
        
        Keeps position updates consistent and reduces duplicate logic.
        
        Args:
            price: Current market price
        """
        self.current_price = price
        self.pnl_pct = calculate_pnl_percentage(self.entry_price, price, self.side)
        
        if self.side in (SignalSide.LONG, SignalSide.BUY):
            self.unrealized_pnl = (price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.quantity
    
    def to_plain_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict for JSON/logging (enums → values, datetimes → ISO)"""
        return _serialize(self)

@dataclass(slots=True)
class PrimeTrade:
    """Unified trade execution record"""
    trade_id: str
    position_id: str
    symbol: str
    side: Literal["BUY", "SELL"]  # Safer than str - only valid order actions
    quantity: int
    price: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Execution details
    commission: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    order_id: str = ""
    client_order_id: str = ""
    execution_venue: str = "ETRADE"
    
    # Strategy data
    strategy_mode: StrategyMode = StrategyMode.STANDARD
    confidence: float = 0.0
    quality_score: float = 0.0
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate trade invariants"""
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {self.side}. Must be 'BUY' or 'SELL'.")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if self.price <= 0:
            raise ValueError(f"price must be > 0, got {self.price}")
        # Validate non-negative money fields
        for name, value in {
            "commission": self.commission,
            "fees": self.fees,
            "slippage": self.slippage
        }.items():
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")
    
    def to_plain_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict for JSON/logging (enums → values, datetimes → ISO)"""
        return _serialize(self)

@dataclass(slots=True)
class PrimeStopOrder:
    """Unified stop order data structure"""
    stop_id: str
    position_id: str
    symbol: str
    stop_type: StopType
    stop_price: float
    trigger_price: float
    created_time: datetime = field(default_factory=datetime.utcnow)
    
    # Trailing data
    trailing_mode: Optional[TrailingMode] = None
    trailing_distance: float = 0.0
    max_trailing_distance: float = 0.0
    
    # Status
    is_active: bool = True
    triggered_time: Optional[datetime] = None
    cancelled_time: Optional[datetime] = None
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate stop order invariants"""
        if self.stop_price <= 0:
            raise ValueError(f"stop_price must be > 0, got {self.stop_price}")
        if self.trigger_price <= 0:
            raise ValueError(f"trigger_price must be > 0, got {self.trigger_price}")

# ============================================================================
# PERFORMANCE METRICS
# ============================================================================

@dataclass(slots=True)
class UnifiedPerformanceMetrics:
    """Unified performance metrics"""
    # Trade statistics
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # Performance ratios
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    recovery_factor: float = 0.0
    
    # Risk metrics
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    max_drawdown_duration: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    
    # Return metrics
    total_return: float = 0.0
    annualized_return: float = 0.0
    volatility: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    
    # Trade analysis
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_holding_period: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    expectancy: float = 0.0
    kelly_percentage: float = 0.0
    
    # Strategy-specific metrics
    standard_trades: int = 0
    advanced_trades: int = 0
    quantum_trades: int = 0
    standard_win_rate: float = 0.0
    advanced_win_rate: float = 0.0
    quantum_win_rate: float = 0.0

@dataclass(slots=True)
class UnifiedStrategyConfig:
    """Unified strategy configuration"""
    # Strategy mode
    mode: StrategyMode
    target_weekly_return: float
    base_risk_per_trade: float
    max_risk_per_trade: float
    position_size_pct: float
    confidence_threshold: float
    
    # Risk management
    max_open_positions: int = 5
    reserve_cash_pct: float = 20.0
    stop_loss_atr_multiplier: float = 1.8
    take_profit_atr_multiplier: float = 3.0
    
    # Capital Allocation (Oct 24, 2025: Unified | Nov 1, 2025: Env configurable with validation)
    # Rev 00084: Read from configs/position-sizing.env
    # CRITICAL: SO + ORR must = TOTAL_CAPITAL_ALLOCATION_PCT
    # CRITICAL: TOTAL_CAPITAL_ALLOCATION_PCT + CASH_RESERVE_PCT must = 100%
    so_capital_pct: float = field(default_factory=lambda: float(os.getenv('SO_CAPITAL_PCT', '90.0')))
    orr_capital_pct: float = field(default_factory=lambda: float(os.getenv('ORR_CAPITAL_PCT', '0.0')))
    cash_reserve_pct: float = field(default_factory=lambda: float(os.getenv('CASH_RESERVE_PCT', '10.0')))
    max_position_pct: float = field(default_factory=lambda: float(os.getenv('MAX_POSITION_SIZE_PCT', '35.0')))
    expensive_threshold_pct: float = 110.0  # Filter symbols if share price > this % of fair share
    max_concurrent_trades: int = field(default_factory=lambda: int(os.getenv('MAX_CONCURRENT_POSITIONS', '15')))
    
    def __post_init__(self):
        """Validate capital allocation percentages"""
        total_allocation = self.so_capital_pct + self.orr_capital_pct
        total_account = total_allocation + self.cash_reserve_pct
        
        # Validate that allocations sum correctly
        if abs(total_account - 100.0) > 0.1:  # Allow 0.1% tolerance for float precision
            raise ValueError(
                f"Capital allocation error: SO ({self.so_capital_pct}%) + ORR ({self.orr_capital_pct}%) + "
                f"Reserve ({self.cash_reserve_pct}%) = {total_account}% (must equal 100%)"
            )
    
    # Signal requirements
    min_confirmations: int = 6
    min_quality_score: float = 60.0
    min_confidence_score: float = 0.9
    
    # Performance targets
    expected_daily_gain: float = 0.02
    expected_trade_gain_min: float = 0.005
    expected_trade_gain_max: float = 0.08
    expected_win_rate: float = 0.75

# ============================================================================
# STRATEGY CONFIGURATIONS
# ============================================================================

STRATEGY_CONFIGS = {
    StrategyMode.STANDARD: UnifiedStrategyConfig(
        mode=StrategyMode.STANDARD,
        target_weekly_return=0.12,  # 12% weekly
        base_risk_per_trade=0.02,   # 2% base risk
        max_risk_per_trade=0.05,    # 5% max risk
        position_size_pct=10.0,     # 10% position size
        confidence_threshold=0.90,  # 90% confidence
        min_confirmations=6,
        min_quality_score=60.0,
        expected_daily_gain=0.03,   # 3% daily
        expected_trade_gain_min=0.005,  # 0.5% min
        expected_trade_gain_max=0.08,   # 8% max
        expected_win_rate=0.75      # 75% win rate
    ),
    
    StrategyMode.ADVANCED: UnifiedStrategyConfig(
        mode=StrategyMode.ADVANCED,
        target_weekly_return=0.20,  # 20% weekly
        base_risk_per_trade=0.05,   # 5% base risk
        max_risk_per_trade=0.15,    # 15% max risk
        position_size_pct=20.0,     # 20% position size
        confidence_threshold=0.90,  # 90% confidence
        min_confirmations=8,
        min_quality_score=70.0,
        expected_daily_gain=0.04,   # 4% daily
        expected_trade_gain_min=0.01,   # 1% min
        expected_trade_gain_max=0.10,   # 10% max
        expected_win_rate=0.80      # 80% win rate
    ),
    
    StrategyMode.QUANTUM: UnifiedStrategyConfig(
        mode=StrategyMode.QUANTUM,
        target_weekly_return=0.35,  # 35% weekly
        base_risk_per_trade=0.10,   # 10% base risk
        max_risk_per_trade=0.25,    # 25% max risk
        position_size_pct=30.0,     # 30% position size
        confidence_threshold=0.95,  # 95% confidence
        min_confirmations=10,
        min_quality_score=80.0,
        expected_daily_gain=0.06,   # 6% daily
        expected_trade_gain_min=0.02,   # 2% min
        expected_trade_gain_max=0.15,   # 15% max
        expected_win_rate=0.85      # 85% win rate
    )
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_strategy_config(mode: StrategyMode) -> UnifiedStrategyConfig:
    """Get strategy configuration for given mode"""
    return STRATEGY_CONFIGS.get(mode, STRATEGY_CONFIGS[StrategyMode.STANDARD])

def create_position_id(symbol: str, timestamp: datetime = None) -> str:
    """Create unique position ID"""
    if timestamp is None:
        timestamp = datetime.utcnow()
    return f"{symbol}_{int(timestamp.timestamp())}"

def create_trade_id(symbol: str, side: str, timestamp: datetime = None) -> str:
    """Create unique trade ID"""
    if timestamp is None:
        timestamp = datetime.utcnow()
    return f"{symbol}_{side}_{int(timestamp.timestamp())}"

def create_stop_id(position_id: str, stop_type: StopType) -> str:
    """Create unique stop ID"""
    return f"{position_id}_{stop_type.value}_{int(time.time())}"

def calculate_pnl_percentage(entry_price: float, current_price: float, side: SignalSide) -> float:
    """
    Calculate PnL percentage with safe divide-by-zero handling.
    
    Args:
        entry_price: Entry price (must be > 0)
        current_price: Current price
        side: Position side (LONG/SHORT/BUY/SELL)
    
    Returns:
        PnL percentage, or 0.0 if entry_price is invalid
    
    Note:
        Explicitly checks for None, 0, and negative values to avoid edge cases.
    """
    if entry_price is None or entry_price <= 0:
        return 0.0
    
    if side in (SignalSide.LONG, SignalSide.BUY):
        return (current_price - entry_price) / entry_price
    else:
        return (entry_price - current_price) / entry_price

def calculate_risk_reward_ratio(entry_price: float, stop_loss: Optional[float], 
                               take_profit: Optional[float], side: SignalSide) -> float:
    """
    Calculate risk-reward ratio with safe None/zero handling.
    
    Args:
        entry_price: Entry price
        stop_loss: Stop loss price (optional)
        take_profit: Take profit price (optional)
        side: Position side (LONG/SHORT/BUY/SELL)
    
    Returns:
        Risk/reward ratio, or 0.0 if stops are missing or risk is invalid
    """
    if stop_loss is None or take_profit is None:
        return 0.0
    
    if side in (SignalSide.LONG, SignalSide.BUY):
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
    else:
        risk = stop_loss - entry_price
        reward = entry_price - take_profit
    
    return 0.0 if risk <= 0 else (reward / risk)

def determine_signal_quality(confidence: float) -> SignalQuality:
    """Determine signal quality based on confidence"""
    if confidence >= 0.99:
        return SignalQuality.ULTRA_HIGH
    elif confidence >= 0.95:
        return SignalQuality.VERY_HIGH
    elif confidence >= 0.90:
        return SignalQuality.HIGH
    elif confidence >= 0.80:
        return SignalQuality.MEDIUM
    else:
        return SignalQuality.LOW

def side_to_order_action(side: SignalSide) -> str:
    """
    Convert SignalSide enum to order action string for E*TRADE API.
    
    Handles both modern (LONG/SHORT) and legacy (BUY/SELL) enum values.
    Prevents accidental mixing of enum values by providing a single conversion point.
    
    Args:
        side: SignalSide enum value
    
    Returns:
        "BUY" or "SELL" string for E*TRADE API
    
    Raises:
        ValueError: If side is not a recognized SignalSide value
    
    Note:
        Use this at the E*TRADE boundary to convert SignalSide → API action string.
        Internally, prefer SignalSide.LONG/SHORT over BUY/SELL for clarity.
    """
    if side in (SignalSide.LONG, SignalSide.BUY):
        return "BUY"
    if side in (SignalSide.SHORT, SignalSide.SELL):
        return "SELL"
    raise ValueError(f"Unknown side: {side}")

def order_action_to_side(action: str) -> SignalSide:
    """
    Convert order action string to SignalSide enum (inverse of side_to_order_action).
    
    Useful for ingesting fills, webhooks, and API responses.
    
    Args:
        action: Order action string ("BUY" or "SELL", case-insensitive)
    
    Returns:
        SignalSide enum value (BUY or SELL)
    
    Raises:
        ValueError: If action is not "BUY" or "SELL"
    
    Example:
        side = order_action_to_side("BUY")  # Returns SignalSide.BUY
    """
    a = action.upper()
    if a == "BUY":
        return SignalSide.BUY
    if a == "SELL":
        return SignalSide.SELL
    raise ValueError(f"Unknown action: {action}")

def determine_confidence_tier(confidence: float) -> ConfidenceTier:
    """Determine confidence tier based on confidence"""
    if confidence >= 0.995:
        return ConfidenceTier.ULTRA
    elif confidence >= 0.99:
        return ConfidenceTier.EXTREME
    elif confidence >= 0.975:
        return ConfidenceTier.VERY_HIGH
    elif confidence >= 0.95:
        return ConfidenceTier.HIGH
    else:
        return ConfidenceTier.STANDARD

def agreement_count_to_level(agreement_count: int) -> AgreementLevel:
    """
    Convert agreement count to AgreementLevel enum.
    
    Args:
        agreement_count: Number of strategies that agree (0-8+)
    
    Returns:
        AgreementLevel enum value
    
    Mapping:
        - 0 → NONE
        - 1 → LOW
        - 2 → MEDIUM
        - 3 → HIGH
        - 4+ → MAXIMUM
    """
    if agreement_count == 0:
        return AgreementLevel.NONE
    elif agreement_count == 1:
        return AgreementLevel.LOW
    elif agreement_count == 2:
        return AgreementLevel.MEDIUM
    elif agreement_count == 3:
        return AgreementLevel.HIGH
    else:  # 4+
        return AgreementLevel.MAXIMUM

def agreement_level_to_mode(level: AgreementLevel) -> StrategyMode:
    """
    Convert AgreementLevel to StrategyMode for position sizing.
    
    Higher agreement levels use more aggressive strategy modes.
    More aggressive mapping: HIGH/MAXIMUM → QUANTUM for strong signals.
    
    Args:
        level: AgreementLevel enum value
    
    Returns:
        StrategyMode enum value
    
    Mapping:
        - MAXIMUM (4+) or HIGH (3) → QUANTUM (most aggressive)
        - MEDIUM (2) → ADVANCED (moderate)
        - LOW (1) or NONE (0) → STANDARD (conservative)
    """
    if level in (AgreementLevel.MAXIMUM, AgreementLevel.HIGH):
        return StrategyMode.QUANTUM  # 3+ strategies = quantum mode (aggressive)
    elif level == AgreementLevel.MEDIUM:
        return StrategyMode.ADVANCED  # 2 strategies = advanced mode
    else:
        return StrategyMode.STANDARD  # 0-1 strategies = standard mode

def get_indicator_safely(indicators: Optional[Union[TechnicalIndicators, Dict[str, Any]]], 
                        field: str, 
                        default: Any = 0.0) -> Any:
    """
    Safely extract indicator value from TechnicalIndicators dataclass or dict.
    
    Args:
        indicators: TechnicalIndicators dataclass or dict
        field: Field name to extract
        default: Default value if field not found
    
    Returns:
        Indicator value or default
    """
    if indicators is None:
        return default
    
    # If it's a dataclass, use getattr
    if isinstance(indicators, TechnicalIndicators):
        return getattr(indicators, field, default)
    
    # If it's a dict, use get
    if isinstance(indicators, dict):
        return indicators.get(field, default)
    
    return default

# ============================================================================
# MEMORY EFFICIENT VERSIONS
# ============================================================================

class MemoryEfficientPosition:
    """Memory-efficient position using __slots__"""
    __slots__ = [
        'position_id', 'symbol', 'side', 'quantity', 'entry_price', 'current_price',
        'entry_time', 'status', 'unrealized_pnl', 'realized_pnl', 'pnl_pct',
        'stop_loss', 'take_profit', 'confidence', 'quality_score', 'strategy_mode'
    ]
    

class MemoryEfficientSignal:
    """Memory-efficient signal using __slots__"""
    __slots__ = [
        'symbol', 'signal_type', 'side', 'confidence', 'quality', 'price', 'timestamp',
        'strategy_mode', 'reason'
    ]
    
    def __init__(self, symbol: str, signal_type: SignalType, side: SignalSide, 
                 confidence: float, price: float):
        self.symbol = symbol
        self.signal_type = signal_type
        self.side = side
        self.confidence = confidence
        self.quality = determine_signal_quality(confidence)
        self.price = price
        self.timestamp = datetime.utcnow()
        self.strategy_mode = StrategyMode.STANDARD
        self.reason = ""

log.info("Unified models loaded successfully")
