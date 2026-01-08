#!/usr/bin/env python3
"""
Prime ORB Strategy Manager - COMPLETE & STANDALONE
==================================================

Single comprehensive module for ORB (Opening Range Breakout) Strategy.
Replaces multi-strategy manager with simpler, more predictable trading.

This manager handles the COMPLETE ORB trading workflow:
1. Opening Range Detection (6:30-6:45 AM PT / 9:30-9:45 AM ET)
2. Standard Order (SO) Signals (7:15 AM PT / 10:15 AM ET)
3. Opening Range Reversal (ORR) Signals (7:15 AM-12:15 PM PT / 10:15 AM-3:15 PM ET)
4. Inverse ETF Selection for bearish signals
5. Volume Color Validation (green/red candle confirmation)
6. Daily Trade Limits (1 SO + 1 ORR per symbol)

Entry Rules:
============

Opening Range: 6:30-6:45 AM PT (9:30-9:45 AM ET)
  - First 15-minute candle of market open
  - ORB High: High of opening candle
  - ORB Low: Low of opening candle

Standard Order (SO) - 7:15 AM PT (10:15 AM ET):
  Bullish SO:
    - Current price +0.2% above ORB high
    - Previous 15m candle (7:00-7:15 AM PT) closed above ORB high
    - Previous 15m candle closed above its open (green volume)
  
  Inverse SO:
    - Current price -0.2% below ORB low
    - Previous 15m candle (7:00-7:15 AM PT) closed below ORB low
    - Previous 15m candle closed below its open (red volume)

Opening Range Reversal (ORR) - 7:15 AM-12:15 PM PT (10:15 AM-3:15 PM ET):
  Bullish ORR (ONLY VALID ORR SIGNAL):
    - Price was previously below ORB low in the day
    - Price breaks above ORB high for the FIRST TIME in the day
    - V-shaped reversal pattern
    - ALWAYS generates LONG positions
    - NO SHORT positions or bearish signals

Target Gains: 3% average move (1%-10% range)
Hard Cutoff: No new SO after 7:30 AM PT, No new ORR after 12:15 PM PT

Author: Easy Trading Software Team
Date: October 11, 2025
Revision: 00151
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import pytz
import json
import os

log = logging.getLogger(__name__)

# Import SignalSide from prime_models
try:
    from .prime_models import SignalSide
except ImportError:
    class SignalSide(Enum):
        LONG = "LONG"
        SHORT = "SHORT"

log = logging.getLogger("prime_orb_strategy_manager")

# Timezone constants
ET_TZ = pytz.timezone('America/New_York')
PT_TZ = pytz.timezone('America/Los_Angeles')

# ============================================================================
# ENUMS & DATA STRUCTURES
# ============================================================================

class SignalType(Enum):
    """ORB Signal Types"""
    STANDARD_ORDER = "SO"
    OPENING_RANGE_REVERSAL = "ORR"

@dataclass
class ORBData:
    """Opening Range Breakout data"""
    symbol: str
    orb_high: float
    orb_low: float
    orb_open: float
    orb_close: float
    orb_volume: float
    orb_range: float
    orb_is_green: bool
    capture_time: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'orb_high': self.orb_high,
            'orb_low': self.orb_low,
            'orb_open': self.orb_open,
            'orb_close': self.orb_close,
            'orb_volume': self.orb_volume,
            'orb_range': self.orb_range,
            'orb_is_green': self.orb_is_green,
            'capture_time': self.capture_time.isoformat() if self.capture_time else None
        }

@dataclass
class ORRReversalState:
    """Track ORR reversal state for a symbol"""
    symbol: str
    was_above_orb_high: bool = False
    was_below_orb_low: bool = False
    first_above_timestamp: Optional[datetime] = None
    first_below_timestamp: Optional[datetime] = None
    bullish_orr_triggered: bool = False
    inverse_orr_triggered: bool = False

@dataclass
class PostORBValidation:
    """Track post-ORB validation to disable trading if major move already occurred"""
    symbol: str
    trading_disabled: bool = False
    validation_time: Optional[datetime] = None
    validation_reason: Optional[str] = None
    post_orb_high: Optional[float] = None
    post_orb_low: Optional[float] = None
    orb_high_breached: bool = False
    orb_low_breached: bool = False

@dataclass
class ORBStrategyResult:
    """Result from ORB strategy analysis"""
    symbol: str
    should_trade: bool
    signal_type: Optional[SignalType]
    side: SignalSide
    confidence: float
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size_pct: float
    reasoning: str
    inverse_symbol: Optional[str] = None
    orb_data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

# ============================================================================
# DAILY TRADE COUNTER
# ============================================================================

class DailyTradeCounter:
    """Track daily trade executions for SO/ORR limits"""
    
    def __init__(self):
        self.so_trades = set()  # Symbols traded with SO today
        self.orr_trades = set()  # Symbols traded with ORR today
        self.current_date = datetime.now().date()
        log.info("Daily Trade Counter initialized")
    
    def has_traded_so_today(self, symbol: str) -> bool:
        """Check if symbol has SO trade today"""
        self._check_new_day()
        return symbol in self.so_trades
    
    def has_traded_orr_today(self, symbol: str) -> bool:
        """Check if symbol has ORR trade today"""
        self._check_new_day()
        return symbol in self.orr_trades
    
    def record_trade(self, symbol: str, signal_type: SignalType, **kwargs):
        """Record a trade execution"""
        self._check_new_day()
        
        if signal_type == SignalType.STANDARD_ORDER:
            self.so_trades.add(symbol)
            log.info(f"📝 Recorded SO trade for {symbol}")
        elif signal_type == SignalType.OPENING_RANGE_REVERSAL:
            self.orr_trades.add(symbol)
            log.info(f"📝 Recorded ORR trade for {symbol}")
    
    def _check_new_day(self):
        """Reset counters if new day"""
        today = datetime.now().date()
        if today != self.current_date:
            self.reset_daily()
            self.current_date = today
    
    def reset_daily(self):
        """Reset daily counters"""
        self.so_trades.clear()
        self.orr_trades.clear()
        log.info("🔄 Daily trade counters reset")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status"""
        return {
            'date': self.current_date.isoformat(),
            'so_trades': len(self.so_trades),
            'orr_trades': len(self.orr_trades),
            'total_trades': len(self.so_trades) + len(self.orr_trades)
        }

# ============================================================================
# PRIME ORB STRATEGY MANAGER - COMPLETE IMPLEMENTATION
# ============================================================================

class PrimeORBStrategyManager:
    """
    Prime ORB Strategy Manager - COMPLETE & STANDALONE
    
    Single comprehensive manager for ORB trading with SO/ORR signals,
    inverse ETF selection, daily trade limits, and complete integration.
    """
    
    def __init__(self, data_manager=None):
        """Initialize Prime ORB Strategy Manager"""
        self.data_manager = data_manager
        
        # Core data structures
        self.orb_data = {}  # {symbol: ORBData}
        self.reversal_states = {}  # {symbol: ORRReversalState}
        self.post_orb_validation = {}  # {symbol: PostORBValidation}
        
        # Daily trade counter
        self.trade_counter = DailyTradeCounter()
        
        # Duplicate signal prevention (Rev 00163)
        # Rev 00046: FORCE clear on initialization to prevent stale data from persisting across container restarts
        self.executed_symbols_today: set = set()  # Track executed trading symbols
        log.info("🔄 Initialized: executed_symbols_today = {} (empty - ready for today's trading)")
        
        # Load inverse ETF mappings
        self.inverse_mapping = self._load_inverse_mapping()
        
        # Trading windows (Pacific Time)
        # Rev 00056: Updated to 15-minute SO window
        self.orb_window_start = time(6, 30)  # 6:30 AM PT (9:30 AM ET)
        self.orb_window_end = time(6, 45)    # 6:45 AM PT (9:45 AM ET)
        self.so_entry_time = time(7, 15)     # 7:15 AM PT (10:15 AM ET)
        self.so_cutoff_time = time(7, 30)    # 7:30 AM PT (10:30 AM ET) - 15-minute collection window
        self.so_execution_time = time(7, 30) # 7:30 AM PT (10:30 AM ET) - Batch execution time
        self.orr_start_time = time(8, 15)    # 8:15 AM PT (11:15 AM ET) - Rev 00180Z: Delayed 1 hour from SO
        self.orr_cutoff_time = time(12, 15)  # 12:15 PM PT (3:15 PM ET) - Captures 100% of ORR opportunities
        
        # Strategy parameters
        self.target_gain_pct = 3.0
        self.so_bullish_threshold = 0.001  # +0.1% (Reduced from 0.2% - Rev 00153)
        self.so_inverse_threshold = 0.001  # -0.1% (Reduced from 0.2% - Rev 00153)
        
        # Position sizing
        self.default_position_size = 25.0
        self.max_position_size = 35.0
        
        log.info("🚀 Prime ORB Strategy Manager initialized")
        log.info(f"   - ORB Window: {self.orb_window_start}-{self.orb_window_end} PT")
        log.info(f"   - SO Window: {self.so_entry_time}-{self.so_cutoff_time} PT")
        log.info(f"   - ORR Window: {self.orr_start_time}-{self.orr_cutoff_time} PT")
        log.info(f"   - Target Gain: {self.target_gain_pct}%")
        log.info(f"   - Inverse ETFs: {len(self.inverse_mapping)}")
    
    def _load_inverse_mapping(self) -> Dict[str, str]:
        """Load inverse ETF mappings"""
        try:
            mapping_file = "data/watchlist/orb_inverse_mapping.json"
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r') as f:
                    data = json.load(f)
                    
                    # Extract inverse mappings from nested structure
                    inverse_mappings = {}
                    orb_strategy = data.get('orb_strategy_mapping', {})
                    
                    # Process 3x leverage pairs
                    for category, pairs in orb_strategy.get('3x_leverage_pairs', {}).items():
                        for symbol, info in pairs.items():
                            if 'bear_etf' in info:
                                inverse_mappings[symbol] = info['bear_etf']
                    
                    # Process 2x leverage pairs
                    for category, pairs in orb_strategy.get('2x_leverage_pairs', {}).items():
                        for symbol, info in pairs.items():
                            if 'bear_etf' in info:
                                inverse_mappings[symbol] = info['bear_etf']
                    
                    log.info(f"✅ Loaded {len(inverse_mappings)} inverse ETF mappings")
                    return inverse_mappings
            else:
                log.warning(f"⚠️ Inverse mapping file not found: {mapping_file}")
                return {}
        except Exception as e:
            log.error(f"❌ Error loading inverse ETF mappings: {e}")
            return {}
    
    # ========================================================================
    # TIME WINDOW MANAGEMENT
    # ========================================================================
    
    def _get_current_time_pt(self) -> time:
        """Get current time in Pacific Time"""
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_pt = now_utc.astimezone(PT_TZ)
        return now_pt.time()
    
    def _is_within_so_window(self) -> bool:
        """Check if current time is within SO collection window (7:15-7:30 AM PT, 15-minute window)"""
        current_time = self._get_current_time_pt()
        return current_time >= self.so_entry_time and current_time < self.so_cutoff_time
    
    def _is_within_orr_window(self) -> bool:
        """Check if current time is within ORR entry window"""
        current_time = self._get_current_time_pt()
        return current_time >= self.orr_start_time and current_time < self.orr_cutoff_time
    
    # ========================================================================
    # ORB DATA CAPTURE & ANALYSIS
    # ========================================================================
    
    def _capture_opening_range(self, symbol: str, intraday_data: List[Dict[str, Any]]) -> Optional[ORBData]:
        """Capture ORB high/low from 6:30-6:45 AM PT candle and track range violations during capture"""
        try:
            if not intraday_data:
                return None
            
            orb_high = None
            orb_low = None
            orb_open = None
            orb_close = None
            orb_volume = None
            
            # Track if price violated the ORB range during the capture window
            was_above_orb_high = False
            was_below_orb_low = False
            
            # First pass: Find the opening range candle (6:30-6:45 AM PT)
            for bar in intraday_data:
                timestamp = bar.get('timestamp', bar.get('datetime'))
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                
                pt_time = timestamp.astimezone(PT_TZ)
                bar_time = pt_time.time()
                
                # Check if this is the opening range candle
                if self.orb_window_start <= bar_time <= self.orb_window_end:
                    orb_high = float(bar['high'])
                    orb_low = float(bar['low'])
                    orb_open = float(bar['open'])
                    orb_close = float(bar['close'])
                    orb_volume = float(bar['volume'])
                    break
            
            if orb_high is None:
                return None
            
            # Second pass: Check all bars in the ORB window for range violations
            for bar in intraday_data:
                timestamp = bar.get('timestamp', bar.get('datetime'))
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                
                pt_time = timestamp.astimezone(PT_TZ)
                bar_time = pt_time.time()
                
                # Check all bars within the ORB window (6:30-6:45 AM PT)
                if self.orb_window_start <= bar_time <= self.orb_window_end:
                    bar_high = float(bar['high'])
                    bar_low = float(bar['low'])
                    
                    # Track if price ever went above ORB high during capture
                    if bar_high > orb_high:
                        was_above_orb_high = True
                        log.debug(f"🔍 {symbol} went ABOVE ORB high during capture: ${bar_high:.2f} > ${orb_high:.2f}")
                    
                    # Track if price ever went below ORB low during capture
                    if bar_low < orb_low:
                        was_below_orb_low = True
                        log.debug(f"🔍 {symbol} went BELOW ORB low during capture: ${bar_low:.2f} < ${orb_low:.2f}")
            
            orb_range = orb_high - orb_low
            orb_is_green = orb_close > orb_open
            
            orb_data = ORBData(
                symbol=symbol,
                orb_high=orb_high,
                orb_low=orb_low,
                orb_open=orb_open,
                orb_close=orb_close,
                orb_volume=orb_volume,
                orb_range=orb_range,
                orb_is_green=orb_is_green,
                capture_time=datetime.now(PT_TZ)
            )
            
            # Initialize ORR reversal state with capture window violations
            self.reversal_states[symbol] = ORRReversalState(
                symbol=symbol,
                was_above_orb_high=was_above_orb_high,
                was_below_orb_low=was_below_orb_low,
                bullish_orr_triggered=False,
                inverse_orr_triggered=False
            )
            
            self.orb_data[symbol] = orb_data
            
            violation_info = ""
            if was_above_orb_high and was_below_orb_low:
                violation_info = " (violated BOTH high and low during capture)"
            elif was_above_orb_high:
                violation_info = " (went above high during capture)"
            elif was_below_orb_low:
                violation_info = " (went below low during capture)"
            
            log.info(f"✅ ORB captured for {symbol}: H=${orb_high:.2f}, L=${orb_low:.2f}, Range=${orb_range:.2f}{violation_info}")
            return orb_data
            
        except Exception as e:
            log.error(f"Error capturing ORB for {symbol}: {e}")
            return None
    
    def _get_volume_color(self, symbol: str, intraday_data: List[Dict[str, Any]]) -> str:
        """Get volume color from 7:00-7:15 AM PT candle"""
        try:
            prev_candle_start = time(7, 0)
            prev_candle_end = time(7, 15)
            
            for bar in intraday_data:
                timestamp = bar.get('timestamp', bar.get('datetime'))
                
                # Handle different timestamp formats
                if isinstance(timestamp, str):
                    try:
                        # Try ISO format first
                        if 'T' in timestamp:
                            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        else:
                            # Try other formats
                            timestamp = datetime.fromisoformat(timestamp)
                    except:
                        # If parsing fails, use current time as fallback
                        timestamp = datetime.now(PT_TZ)
                elif isinstance(timestamp, datetime):
                    # Already a datetime object
                    pass
                else:
                    # Unknown format, use current time
                    timestamp = datetime.now(PT_TZ)
                
                # Ensure timezone awareness
                if timestamp.tzinfo is None:
                    timestamp = PT_TZ.localize(timestamp)
                
                pt_time = timestamp.astimezone(PT_TZ)
                bar_time = pt_time.time()
                
                if prev_candle_start <= bar_time <= prev_candle_end:
                    candle_open = float(bar['open'])
                    candle_close = float(bar['close'])
                    
                    if candle_close > candle_open:
                        return "GREEN"
                    elif candle_close < candle_open:
                        return "RED"
                    else:
                        return "NEUTRAL"
            
            return "NEUTRAL"
            
        except Exception as e:
            log.error(f"Error getting volume color for {symbol}: {e}")
            return "NEUTRAL"
    
    def _check_prev_candle_vs_orb(self, symbol: str, intraday_data: List[Dict[str, Any]], orb_level: float, above: bool) -> bool:
        """Check if previous 7:00-7:15 AM PT candle closed above/below ORB level"""
        try:
            prev_candle_start = time(7, 0)
            prev_candle_end = time(7, 15)
            
            for bar in intraday_data:
                timestamp = bar.get('timestamp', bar.get('datetime'))
                
                # Handle different timestamp formats
                if isinstance(timestamp, str):
                    try:
                        # Try ISO format first
                        if 'T' in timestamp:
                            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        else:
                            # Try other formats
                            timestamp = datetime.fromisoformat(timestamp)
                    except:
                        # If parsing fails, use current time as fallback
                        timestamp = datetime.now(PT_TZ)
                elif isinstance(timestamp, datetime):
                    # Already a datetime object
                    pass
                else:
                    # Unknown format, use current time
                    timestamp = datetime.now(PT_TZ)
                
                # Ensure timezone awareness
                if timestamp.tzinfo is None:
                    timestamp = PT_TZ.localize(timestamp)
                
                pt_time = timestamp.astimezone(PT_TZ)
                bar_time = pt_time.time()
                
                if prev_candle_start <= bar_time <= prev_candle_end:
                    candle_close = float(bar['close'])
                    if above:
                        return candle_close > orb_level
                    else:
                        return candle_close < orb_level
            
            return False
            
        except Exception as e:
            log.error(f"Error checking previous candle for {symbol}: {e}")
            return False
    
    def _validate_post_orb_candle(self, symbol: str, intraday_data: List[Dict[str, Any]]) -> bool:
        """
        Validate post-ORB candle (6:45-7:00 AM PT) to detect sideways/choppy markets.
        
        DISABLES TRADING if the 6:45-7:00 AM candle engulfs BOTH the high AND low 
        of the opening range (6:30-6:45 AM PT). This indicates a sideways market 
        with no clear directional bias.
        
        Returns:
            True if symbol is safe to trade (normal market)
            False if trading should be disabled (choppy market)
        """
        try:
            if symbol not in self.orb_data:
                return True  # No ORB data yet, allow trading
            
            # Check if already validated
            if symbol in self.post_orb_validation:
                validation = self.post_orb_validation[symbol]
                if validation.trading_disabled:
                    log.debug(f"⛔ {symbol} already disabled: {validation.validation_reason}")
                return not validation.trading_disabled
            
            orb = self.orb_data[symbol]
            post_orb_start = time(6, 45)
            post_orb_end = time(7, 0)
            
            # Find the 6:45-7:00 AM PT candle
            for bar in intraday_data:
                timestamp = bar.get('timestamp', bar.get('datetime'))
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                
                pt_time = timestamp.astimezone(PT_TZ)
                bar_time = pt_time.time()
                
                # Check if this is the post-ORB candle (6:45-7:00 AM PT)
                if post_orb_start <= bar_time <= post_orb_end:
                    post_orb_high = float(bar['high'])
                    post_orb_low = float(bar['low'])
                    
                    # Check if post-ORB candle breached BOTH ORB high and low
                    breached_high = post_orb_high > orb.orb_high
                    breached_low = post_orb_low < orb.orb_low
                    
                    validation = PostORBValidation(
                        symbol=symbol,
                        validation_time=datetime.now(PT_TZ),
                        post_orb_high=post_orb_high,
                        post_orb_low=post_orb_low,
                        orb_high_breached=breached_high,
                        orb_low_breached=breached_low
                    )
                    
                    # DISABLE trading if BOTH high and low breached (sideways/choppy)
                    if breached_high and breached_low:
                        validation.trading_disabled = True
                        validation.validation_reason = (
                            f"Post-ORB candle (6:45-7:00 AM) engulfed entire ORB range "
                            f"(H:{post_orb_high:.2f} > {orb.orb_high:.2f}, "
                            f"L:{post_orb_low:.2f} < {orb.orb_low:.2f}) - Sideways market detected"
                        )
                        log.warning(f"⛔ {symbol}: Trading DISABLED - {validation.validation_reason}")
                    else:
                        validation.trading_disabled = False
                        validation.validation_reason = (
                            f"Post-ORB candle normal "
                            f"(High breached: {breached_high}, Low breached: {breached_low})"
                        )
                        log.info(f"✅ {symbol}: Trading ENABLED - {validation.validation_reason}")
                    
                    self.post_orb_validation[symbol] = validation
                    return not validation.trading_disabled
            
            # If no post-ORB candle found yet, allow trading (will check later)
            return True
            
        except Exception as e:
            log.error(f"Error validating post-ORB for {symbol}: {e}")
            return True  # Default to allowing trading on error
    
    # ========================================================================
    # SIGNAL GENERATION
    # ========================================================================
    
    def _evaluate_so_signal(self, symbol: str, current_price: float, intraday_data: List[Dict[str, Any]]) -> Optional[ORBStrategyResult]:
        """Evaluate Standard Order signal at 7:15 AM PT"""
        try:
            if symbol not in self.orb_data:
                return None
            
            orb = self.orb_data[symbol]
            volume_color = self._get_volume_color(symbol, intraday_data)
            
            # Bullish SO
            # Rev 20251022: Add zero check to prevent division by zero
            if orb.orb_high == 0:
                log.warning(f"⚠️ {symbol}: ORB high is zero, skipping SO evaluation")
                return None
            
            distance_from_high = (current_price - orb.orb_high) / orb.orb_high
            
            # DEBUG: Log validation checks for first few symbols
            if distance_from_high >= self.so_bullish_threshold:
                log.info(f"🔍 {symbol}: Price above ORB high (+{distance_from_high:.2%}), Volume: {volume_color}")
                prev_candle_ok = self._check_prev_candle_vs_orb(symbol, intraday_data, orb.orb_high, above=True)
                log.info(f"   Previous candle check: {'✅ PASS' if prev_candle_ok else '❌ FAIL'}")
                
                if volume_color == "GREEN" and prev_candle_ok:
                    log.info(f"✅ {symbol}: ALL VALIDATION PASSED - Creating signal!")
                    return self._create_signal(
                        symbol=symbol,
                        signal_type=SignalType.STANDARD_ORDER,
                        side=SignalSide.LONG,
                        current_price=current_price,
                        stop_loss=orb.orb_low,
                        take_profit=current_price * 1.03,
                        confidence=min(0.95, 0.7 + abs(distance_from_high) * 10),
                        reasoning=f"Bullish SO: Price {distance_from_high:.2%} above ORB high with GREEN volume",
                        orb_data=orb
                    )
                else:
                    log.info(f"   ❌ REJECTED: Volume={volume_color} (need GREEN), Prev candle={'✅' if prev_candle_ok else '❌'}")
            
            # CRITICAL RULE: NO LONG POSITIONS if price is below ORB high
            # Only allow LONG positions when price > ORB high (momentum signals)
            if current_price < orb.orb_high:
                # Price below ORB high - NO LONG positions allowed (fundamental rule)
                log.debug(f"⏭️ {symbol}: Price ${current_price:.2f} below ORB high ${orb.orb_high:.2f} - no long positions allowed")
                return None
            
            return None
            
        except Exception as e:
            log.error(f"Error evaluating SO for {symbol}: {e}")
            return None
    
    def _evaluate_bearish_so_signal(self, symbol: str, current_price: float, intraday_data: List[Dict[str, Any]]) -> Optional[ORBStrategyResult]:
        """
        Evaluate Bearish SO signal (for 0DTE PUT options) - Rev 00211
        
        Uses same validation rules as Inverse SO but generates SHORT signals directly
        for 0DTE Strategy PUT options.
        
        Validation Rules (All 3 Required):
        1. Current price ≤ ORB Low × 0.999 (-0.1% buffer)
        2. Previous close < ORB Low (7:00-7:15 AM candle closed below ORB low)
        3. Red candle (7:00-7:15 AM candle close < open = selling pressure)
        """
        try:
            if symbol not in self.orb_data:
                return None
            
            orb = self.orb_data[symbol]
            volume_color = self._get_volume_color(symbol, intraday_data)
            
            # Bearish SO validation
            if orb.orb_low == 0:
                log.warning(f"⚠️ {symbol}: ORB low is zero, skipping bearish SO evaluation")
                return None
            
            distance_from_low = (current_price - orb.orb_low) / orb.orb_low
            
            # DEBUG: Log validation checks
            if distance_from_low <= -self.so_inverse_threshold:
                log.info(f"🔍 {symbol}: Price below ORB low ({distance_from_low:.2%}), Volume: {volume_color}")
                prev_candle_ok = self._check_prev_candle_vs_orb(symbol, intraday_data, orb.orb_low, above=False)
                log.info(f"   Previous candle check: {'✅ PASS' if prev_candle_ok else '❌ FAIL'}")
                
                if volume_color == "RED" and prev_candle_ok:
                    log.info(f"✅ {symbol}: ALL BEARISH VALIDATION PASSED - Creating SHORT signal!")
                    return self._create_signal(
                        symbol=symbol,
                        signal_type=SignalType.STANDARD_ORDER,
                        side=SignalSide.SHORT,  # SHORT for PUT options
                        current_price=current_price,
                        stop_loss=orb.orb_high,
                        take_profit=current_price * 0.97,  # 3% target down
                        confidence=min(0.95, 0.7 + abs(distance_from_low) * 10),
                        reasoning=f"Bearish SO: Price {distance_from_low:.2%} below ORB low with RED volume",
                        orb_data=orb
                    )
                else:
                    log.info(f"   ❌ REJECTED: Volume={volume_color} (need RED), Prev candle={'✅' if prev_candle_ok else '❌'}")
            
            # CRITICAL RULE: NO SHORT POSITIONS if price is above ORB low
            # Only allow SHORT positions when price < ORB low (momentum signals)
            if current_price > orb.orb_low:
                log.debug(f"⏭️ {symbol}: Price ${current_price:.2f} above ORB low ${orb.orb_low:.2f} - no short positions allowed")
                return None
            
            return None
            
        except Exception as e:
            log.error(f"Error evaluating bearish SO for {symbol}: {e}")
            return None
    
    def _evaluate_orr_signal(self, symbol: str, current_price: float, intraday_data: List[Dict[str, Any]]) -> Optional[ORBStrategyResult]:
        """Evaluate Opening Range Reversal signal - triggers on CROSSING events only"""
        try:
            if symbol not in self.orb_data:
                return None
            
            orb = self.orb_data[symbol]
            
            # Initialize reversal state
            if symbol not in self.reversal_states:
                self.reversal_states[symbol] = ORRReversalState(symbol=symbol)
            
            state = self.reversal_states[symbol]
            
            # CRITICAL RULE (Rev 00180): Check price position FIRST - MUST be above ORB high to proceed
            # NO positions allowed if price is below ORB high (fundamental rule)
            if current_price <= orb.orb_high:
                # Price at or below ORB high - NO LONG positions allowed
                # Still track if we go below ORB low for future ORR detection
                if current_price < orb.orb_low and not state.was_below_orb_low:
                    state.was_below_orb_low = True
                    state.first_below_timestamp = datetime.now(PT_TZ)
                    log.debug(f"📉 {symbol}: Price ${current_price:.2f} below ORB low ${orb.orb_low:.2f} (tracking for future ORR)")
                return None  # Exit early - no signals below/at ORB high
            
            # At this point: current_price > orb.orb_high (confirmed above ORB high)
            
            # STEP 1: Track if price was previously BELOW ORB low (required for V-shaped reversal)
            # This tracking happens continuously, but we already know price is currently ABOVE ORB high
            # So this checks historical state only
            if not state.was_below_orb_low:
                # Price is above ORB high but was never below ORB low - no V-shape possible
                log.debug(f"⏭️ {symbol}: Price ${current_price:.2f} above ORB high but never went below ORB low - no V-shaped reversal")
                return None
            
            # STEP 2: Bullish ORR - Detect FIRST TIME crossing above ORB high (after V-shape confirmed)
            if not state.was_above_orb_high:
                # Price just crossed above ORB high for the FIRST TIME
                state.was_above_orb_high = True
                state.first_above_timestamp = datetime.now(PT_TZ)
                
                # Trigger Bullish ORR (V-shaped reversal confirmed)
                if not state.bullish_orr_triggered:
                    state.bullish_orr_triggered = True
                    log.info(f"🔔 Bullish ORR triggered for {symbol}: Price ${current_price:.2f} crossed above ORB high ${orb.orb_high:.2f} after being below ORB low ${orb.orb_low:.2f}")
                    return self._create_signal(
                        symbol=symbol,
                        signal_type=SignalType.OPENING_RANGE_REVERSAL,
                        side=SignalSide.LONG,
                        current_price=current_price,
                        stop_loss=orb.orb_low,
                        take_profit=current_price * 1.03,
                        confidence=0.85,
                        reasoning=f"Bullish ORR: V-shaped reversal from below ORB low ${orb.orb_low:.2f} to above ORB high ${orb.orb_high:.2f}",
                        orb_data=orb
                    )
            else:
                # Already triggered ORR for this symbol today
                log.debug(f"⏭️ {symbol}: Bullish ORR already triggered today")
                return None
            
            return None
            
        except Exception as e:
            log.error(f"Error evaluating ORR for {symbol}: {e}")
            return None
    
    def _create_signal(self, symbol: str, signal_type: SignalType, side: SignalSide,
                      current_price: float, stop_loss: float, take_profit: float,
                      confidence: float, reasoning: str, orb_data: ORBData,
                      inverse_symbol: Optional[str] = None) -> ORBStrategyResult:
        """Create ORB strategy result"""
        
        # Calculate position size
        if confidence >= 0.8:
            position_size = 32.0
        elif confidence >= 0.6:
            position_size = 27.0
        else:
            position_size = 22.0
        
        # SO bonus
        if signal_type == SignalType.STANDARD_ORDER:
            position_size += 3.0
        
        position_size = min(self.max_position_size, position_size)
        
        # Trading symbol (original or inverse)
        trading_symbol = inverse_symbol if inverse_symbol else symbol
        
        return ORBStrategyResult(
            symbol=trading_symbol,
            should_trade=True,
            signal_type=signal_type,
            side=side,  # Use the correct side passed in (LONG for inverse ETFs)
            confidence=confidence,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_size,
            reasoning=reasoning,
            inverse_symbol=inverse_symbol,
            orb_data=orb_data.to_dict() if orb_data else None,
            metadata={
                'original_symbol': symbol,
                'is_inverse': inverse_symbol is not None,
                'signal_type_name': signal_type.value,
                'original_side': side.value  # Keep track of original side for debugging
            }
        )
    
    # ========================================================================
    # MAIN ANALYSIS METHOD
    # ========================================================================
    
    async def analyze_symbol(self, symbol: str, market_data: Dict[str, Any]) -> ORBStrategyResult:
        """
        Analyze a symbol using ORB Primary Strategy
        
        Args:
            symbol: Symbol to analyze
            market_data: Market data including current price and intraday data
        
        Returns:
            ORBStrategyResult with trading recommendation
        """
        try:
            # CRITICAL: Check for inverse pair conflicts BEFORE analysis
            # This prevents both GUSH and DRIP from generating signals on the same day
            potential_trading_symbol = self.inverse_mapping.get(symbol, symbol)
            
            # Check if either the symbol or its inverse pair has already generated a signal today
            inverse_symbol = self.inverse_mapping.get(symbol)
            if inverse_symbol and inverse_symbol in self.executed_symbols_today:
                log.info(f"⏭️  {symbol}: Inverse pair {inverse_symbol} already executed today, preventing conflict")
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.LONG,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning=f"Inverse pair {inverse_symbol} already executed today - preventing conflict"
                )
            
            # Also check if the symbol itself has already been executed
            if symbol in self.executed_symbols_today:
                log.info(f"⏭️  {symbol}: Already executed today, skipping duplicate")
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.LONG,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning=f"{symbol} already executed today"
                )
            
            # Check time windows
            within_so = self._is_within_so_window()
            within_orr = self._is_within_orr_window()
            
            if not within_so and not within_orr:
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.LONG,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning=f"Outside trading windows (Current: {self._get_current_time_pt()})"
                )
            
            # Get intraday data
            intraday_data = market_data.get('intraday_data', [])
            if not intraday_data:
                # Create minimal bar from quote
                intraday_data = [{
                    'timestamp': datetime.now(),
                    'open': market_data.get('open_price', market_data.get('current_price', 0.0)),
                    'high': market_data.get('high_price', market_data.get('current_price', 0.0)),
                    'low': market_data.get('low_price', market_data.get('current_price', 0.0)),
                    'close': market_data.get('current_price', 0.0),
                    'volume': market_data.get('volume', 0)
                }]
            
            # Capture ORB if not already done
            if symbol not in self.orb_data:
                self._capture_opening_range(symbol, intraday_data)
            
            if symbol not in self.orb_data:
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.LONG,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning="No ORB data available (outside 6:30-6:45 AM PT window)"
                )
            
            # CRITICAL: Validate post-ORB candle (6:45-7:00 AM PT)
            # Disables trading if 6:45-7:00 candle engulfed BOTH ORB high AND low
            # This filters out sideways/choppy markets (~1% of symbols)
            if not self._validate_post_orb_candle(symbol, intraday_data):
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.LONG,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning=f"Trading disabled: Post-ORB candle engulfed entire range (sideways market)"
                )
            
            current_price = market_data.get('current_price', 0.0)
            
            # Try SO signal (within SO window)
            if within_so:
                result = self._evaluate_so_signal(symbol, current_price, intraday_data)
                if result and result.should_trade:
                    # Rev 00046: CRITICAL FIX - DO NOT mark SO signals as executed during generation!
                    # SO signals are collected at 7:15-7:30 AM but executed at 7:30 AM (batch)
                    # Marking them as "executed" during generation prevents all signals!
                    # 
                    # The executed_symbols_today check is moved to _process_orb_signals (after execution)
                    # This allows signals to be GENERATED during 7:15-7:30 AM and EXECUTED at 7:30 AM
                    
                    # Rev 00163: Check if trading_symbol already executed today (prevent duplicates)
                    # ONLY check, don't mark yet - marking happens AFTER execution at 7:30 AM
                    trading_symbol = result.symbol  # Could be inverse
                    if trading_symbol in self.executed_symbols_today:
                        log.info(f"⏭️  {symbol} → {trading_symbol} SO: Already executed today, skipping duplicate")
                        result.should_trade = False
                        result.reasoning = f"{trading_symbol} SO already executed today"
                        return result
                    
                    # Check daily limit
                    if not self.trade_counter.has_traded_so_today(symbol):
                        # Rev 00046: REMOVED premature marking - now happens after execution in prime_trading_system.py
                        # Symbols are marked as executed in prime_trading_system._process_orb_signals()
                        # AFTER actual execution at 7:30 AM (not during generation at 7:15-7:30 AM)
                        
                        # Rev 00055: Log signal timing for collection window analysis
                        # Rev 00064: Removed redundant datetime import (already imported at top line 54)
                        from zoneinfo import ZoneInfo
                        pt_tz = ZoneInfo('America/Los_Angeles')
                        now_pt = datetime.now(pt_tz)
                        signal_time = now_pt.strftime('%H:%M:%S')
                        log.info(f"✅ {trading_symbol} SO: Signal generated at {signal_time} PT, will be executed at 7:30 AM PT")
                        
                        return result
                    else:
                        result.should_trade = False
                        result.reasoning = f"Already traded SO for {symbol} today"
                        return result
            
            # Try ORR signal (within ORR window)
            if within_orr:
                result = self._evaluate_orr_signal(symbol, current_price, intraday_data)
                if result and result.should_trade:
                    # Rev 00163: Check if trading_symbol already executed today (prevent duplicates)
                    trading_symbol = result.symbol  # Could be inverse symbol
                    if trading_symbol in self.executed_symbols_today:
                        log.info(f"⏭️  {symbol} → {trading_symbol} ORR: Already executed today, skipping duplicate")
                        result.should_trade = False
                        result.reasoning = f"{trading_symbol} ORR already executed today"
                        return result
                    
                    # Check daily limit on TRADING SYMBOL (not original symbol)
                    # This prevents both SPYU Inverse ORR → SPXS and SPXS ORR → SPXS on same day
                    if not self.trade_counter.has_traded_orr_today(trading_symbol):
                        # Rev 00046: REMOVED premature marking for ORR (same bug as SO)
                        # Marking happens AFTER actual execution in prime_trading_system._process_orb_signals()
                        # self.executed_symbols_today.add(trading_symbol)  # ❌ REMOVED
                        # self.executed_symbols_today.add(symbol)  # ❌ REMOVED
                        # inverse_symbol = self.inverse_mapping.get(symbol)
                        # if inverse_symbol:
                        #     self.executed_symbols_today.add(inverse_symbol)  # ❌ REMOVED
                        log.info(f"✅ {trading_symbol} ORR: Signal generated, will be executed immediately")
                        return result
                    else:
                        result.should_trade = False
                        result.reasoning = f"Already traded ORR on {trading_symbol} today (via {symbol})"
                        return result
            
            # No signal
            return ORBStrategyResult(
                symbol=symbol,
                should_trade=False,
                signal_type=None,
                side=SignalSide.LONG,
                confidence=0.0,
                entry_price=current_price,
                stop_loss=None,
                take_profit=None,
                position_size_pct=0.0,
                reasoning="No ORB signal (rules not met)"
            )
            
        except Exception as e:
            log.error(f"Error analyzing {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return ORBStrategyResult(
                symbol=symbol,
                should_trade=False,
                signal_type=None,
                side=SignalSide.LONG,
                confidence=0.0,
                entry_price=market_data.get('current_price', 0.0),
                stop_loss=None,
                take_profit=None,
                position_size_pct=0.0,
                reasoning=f"Error: {str(e)}"
            )
    
    async def analyze_bearish_symbol(self, symbol: str, market_data: Dict[str, Any]) -> ORBStrategyResult:
        """
        Analyze symbol for bearish SO signal (for 0DTE PUT options) - Rev 00211
        
        Same validation flow as analyze_symbol but evaluates bearish signals.
        Used by 0DTE Strategy to generate PUT option signals.
        
        Validation Rules (All 3 Required):
        1. Current price ≤ ORB Low × 0.999 (-0.1% buffer)
        2. Previous close < ORB Low (7:00-7:15 AM candle closed below ORB low)
        3. Red candle (7:00-7:15 AM candle close < open = selling pressure)
        """
        try:
            # Check if symbol has ORB data
            if symbol not in self.orb_data:
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.SHORT,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning="No ORB data available"
                )
            
            # Check time windows (only SO window for bearish signals)
            within_so = self._is_within_so_window()
            
            if not within_so:
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.SHORT,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning=f"Outside SO window (Current: {self._get_current_time_pt()})"
                )
            
            # Get intraday data
            intraday_data = market_data.get('intraday_data', [])
            if not intraday_data:
                # Create minimal bar from quote
                intraday_data = [{
                    'timestamp': datetime.now(),
                    'open': market_data.get('open_price', market_data.get('current_price', 0.0)),
                    'high': market_data.get('high_price', market_data.get('current_price', 0.0)),
                    'low': market_data.get('low_price', market_data.get('current_price', 0.0)),
                    'close': market_data.get('current_price', 0.0),
                    'volume': market_data.get('volume', 0)
                }]
            
            # Validate post-ORB candle (same as bullish)
            if not self._validate_post_orb_candle(symbol, intraday_data):
                return ORBStrategyResult(
                    symbol=symbol,
                    should_trade=False,
                    signal_type=None,
                    side=SignalSide.SHORT,
                    confidence=0.0,
                    entry_price=market_data.get('current_price', 0.0),
                    stop_loss=None,
                    take_profit=None,
                    position_size_pct=0.0,
                    reasoning=f"Trading disabled: Post-ORB candle engulfed entire range (sideways market)"
                )
            
            current_price = market_data.get('current_price', 0.0)
            
            # Try bearish SO signal (within SO window)
            if within_so:
                result = self._evaluate_bearish_so_signal(symbol, current_price, intraday_data)
                if result and result.should_trade:
                    # Check if already executed today
                    if symbol in self.executed_symbols_today:
                        result.should_trade = False
                        result.reasoning = f"Already traded bearish SO for {symbol} today"
                        return result
                    
                    log.info(f"✅ {symbol} Bearish SO: Signal generated for PUT options")
                    return result
            
            return ORBStrategyResult(
                symbol=symbol,
                should_trade=False,
                signal_type=None,
                side=SignalSide.SHORT,
                confidence=0.0,
                entry_price=current_price,
                stop_loss=None,
                take_profit=None,
                position_size_pct=0.0,
                reasoning="No valid bearish SO signal"
            )
            
        except Exception as e:
            log.error(f"Error analyzing bearish {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return ORBStrategyResult(
                symbol=symbol,
                should_trade=False,
                signal_type=None,
                side=SignalSide.SHORT,
                confidence=0.0,
                entry_price=market_data.get('current_price', 0.0),
                stop_loss=None,
                take_profit=None,
                position_size_pct=0.0,
                reasoning=f"Error: {str(e)}"
            )
    
    # ========================================================================
    # INVERSE PAIR CONFLICT RESOLUTION (Rev 00167)
    # ========================================================================
    
    def resolve_inverse_pair_conflict(self, symbol1: str, signal1: ORBStrategyResult, 
                                    symbol2: str, signal2: ORBStrategyResult) -> ORBStrategyResult:
        """
        Resolve conflicts between inverse pairs by choosing the stronger signal
        
        Criteria:
        1. Higher confidence score
        2. Larger distance from ORB level
        3. Better volume confirmation
        4. Prefer direct signals over inverse signals (momentum vs reversal)
        
        Returns:
            ORBStrategyResult for the stronger signal, with conflict resolution note
        """
        try:
            # Calculate quality scores for both signals
            score1 = self.calculate_signal_quality_score(signal1)
            score2 = self.calculate_signal_quality_score(signal2)
            
            # Choose the higher scoring signal
            if score1 > score2:
                stronger_signal = signal1
                weaker_symbol = symbol2
                stronger_symbol = symbol1
                stronger_score = score1
                weaker_score = score2
            else:
                stronger_signal = signal2
                weaker_symbol = symbol1
                stronger_symbol = symbol2
                stronger_score = score2
                weaker_score = score1
            
            # Add conflict resolution note to reasoning
            stronger_signal.reasoning += f" [CONFLICT RESOLVED: {stronger_symbol} (score: {stronger_score:.2f}) vs {weaker_symbol} (score: {weaker_score:.2f})]"
            
            log.info(f"🔀 Inverse pair conflict resolved: {stronger_symbol} (score: {stronger_score:.2f}) chosen over {weaker_symbol} (score: {weaker_score:.2f})")
            
            return stronger_signal
            
        except Exception as e:
            log.error(f"Error resolving inverse pair conflict between {symbol1} and {symbol2}: {e}")
            # Default to first signal if error
            return signal1
    
    # ========================================================================
    # SIGNAL RANKING (Rev 00163)
    # ========================================================================
    
    def calculate_signal_quality_score(self, signal: ORBStrategyResult) -> float:
        """
        Calculate quality score for signal ranking
        
        Score = confidence × orb_range_pct × price_strength
        
        Higher scores = better signals = larger positions
        """
        try:
            # Get ORB data
            orb = self.orb_data.get(signal.symbol)
            if not orb:
                return 0.0
            
            # Factor 1: Confidence (0.85-0.99)
            confidence_score = signal.confidence
            
            # Factor 2: ORB Range Size (larger range = more opportunity)
            orb_range_pct = orb.orb_range / orb.orb_low if orb.orb_low > 0 else 0
            range_score = min(2.0, orb_range_pct * 100)  # Normalize to 0-2
            
            # Factor 3: Price Strength (how far from ORB)
            if signal.signal_type == SignalType.STANDARD_ORDER:
                if signal.entry_price > orb.orb_high:
                    distance_pct = (signal.entry_price - orb.orb_high) / orb.orb_high
                elif signal.entry_price < orb.orb_low:
                    distance_pct = (orb.orb_low - signal.entry_price) / orb.orb_low
                else:
                    distance_pct = 0
                
                price_strength = min(2.0, distance_pct * 100)  # Normalize to 0-2
            else:
                price_strength = 1.0  # ORR signals get default
            
            # Calculate composite score
            quality_score = confidence_score * range_score * price_strength
            
            return quality_score
            
        except Exception as e:
            log.error(f"Error calculating quality score for {signal.symbol}: {e}")
            return 0.0
    
    # ========================================================================
    # TRADE MANAGEMENT
    # ========================================================================
    
    def record_trade(self, symbol: str, signal_type: SignalType, **kwargs):
        """Record a trade execution (use trading_symbol if provided for inverse trades)"""
        # Use trading_symbol if provided (for inverse trades), otherwise use original symbol
        trading_symbol = kwargs.get('trading_symbol', symbol)
        self.trade_counter.record_trade(trading_symbol, signal_type, **kwargs)
    
    def reset_daily(self):
        """Reset for new trading day"""
        self.trade_counter.reset_daily()
        self.orb_data.clear()
        self.reversal_states.clear()
        self.post_orb_validation.clear()
        self.executed_symbols_today.clear()  # Rev 00163: Reset executed symbols
        log.info("🔄 Prime ORB Strategy Manager reset for new trading day")
        log.info("🔄 Executed symbols tracking reset")

    def load_orb_snapshot(self, snapshot: Dict[str, Dict[str, Any]]) -> int:
        """Load ORB data from a persisted snapshot dictionary."""
        if not snapshot:
            return 0
        
        loaded = 0
        self.orb_data.clear()
        self.reversal_states.clear()
        
        for symbol, data in snapshot.items():
            try:
                capture_time_str = data.get("capture_time")
                capture_dt: Optional[datetime] = None
                if capture_time_str:
                    try:
                        capture_dt = datetime.fromisoformat(capture_time_str.replace("Z", "+00:00"))
                    except ValueError:
                        capture_dt = datetime.now(PT_TZ)
                orb_data = ORBData(
                    symbol=symbol,
                    orb_high=float(data.get("orb_high", 0.0)),
                    orb_low=float(data.get("orb_low", 0.0)),
                    orb_open=float(data.get("orb_open", 0.0)),
                    orb_close=float(data.get("orb_close", 0.0)),
                    orb_volume=float(data.get("orb_volume", 0.0)),
                    orb_range=float(data.get("orb_range", 0.0)),
                    orb_is_green=bool(data.get("orb_is_green", False)),
                    capture_time=capture_dt or datetime.now(PT_TZ),
                )
                self.orb_data[symbol] = orb_data
                self.reversal_states[symbol] = ORRReversalState(symbol=symbol)
                loaded += 1
            except Exception as load_error:
                log.warning(f"⚠️ Failed to load ORB snapshot for {symbol}: {load_error}")
        
        if loaded:
            log.info(f"☁️ ORB snapshot applied ({loaded} symbols)")
        else:
            log.warning("⚠️ ORB snapshot applied but contained no valid symbols")
        return loaded
    
    def get_strategy_status(self) -> Dict[str, Any]:
        """Get current strategy status"""
        # Count disabled symbols
        disabled_count = sum(1 for v in self.post_orb_validation.values() if v.trading_disabled)
        enabled_count = len(self.post_orb_validation) - disabled_count
        
        return {
            'manager': 'Prime ORB Strategy Manager',
            'within_so_window': self._is_within_so_window(),
            'within_orr_window': self._is_within_orr_window(),
            'current_time_pt': str(self._get_current_time_pt()),
            'trade_counter': self.trade_counter.get_status(),
            'inverse_etfs_loaded': len(self.inverse_mapping),
            'target_gain_pct': self.target_gain_pct,
            'orb_data_captured': len(self.orb_data),
            'reversal_states_tracked': len(self.reversal_states),
            'post_orb_validation': {
                'total_validated': len(self.post_orb_validation),
                'enabled_for_trading': enabled_count,
                'disabled_sideways': disabled_count
            }
        }

# Factory function
# SINGLETON INSTANCE - FIX for ORB data persistence (Rev 20251020)
_prime_orb_strategy_manager_singleton = None

def get_prime_orb_strategy_manager(data_manager=None) -> PrimeORBStrategyManager:
    """
    Get Prime ORB Strategy Manager instance (SINGLETON)
    
    CRITICAL FIX (Oct 20, 2025): Changed to singleton pattern to ensure
    ORB data persists between capture (6:45 AM) and SO scanning (7:15+ AM).
    
    Previous bug: Created new instance each time, so ORB data captured at
    6:45 AM was not accessible during SO scanning.
    """
    global _prime_orb_strategy_manager_singleton
    
    if _prime_orb_strategy_manager_singleton is None:
        _prime_orb_strategy_manager_singleton = PrimeORBStrategyManager(data_manager=data_manager)
        log.info("🔧 Created SINGLETON Prime ORB Strategy Manager instance")
    else:
        # Update data manager if provided (but keep same instance)
        if data_manager is not None:
            _prime_orb_strategy_manager_singleton.data_manager = data_manager
    
    return _prime_orb_strategy_manager_singleton
