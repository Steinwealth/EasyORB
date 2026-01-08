#!/usr/bin/env python3
"""
Market Regime Detector
=====================

Detects bull vs bear market conditions and adjusts symbol weighting.

This module analyzes SPY (S&P 500) to determine the current market regime
and provides weighting adjustments for bull vs bear ETFs.

Author: Easy Trading Software Team
Date: October 12, 2025
Revision: 00163
"""

import logging
from typing import Dict, Any
from datetime import datetime, timedelta
import yfinance as yf

log = logging.getLogger("market_regime_detector")

class MarketRegimeDetector:
    """Detects market regime (bull/bear) and adjusts trading strategy"""
    
    def __init__(self):
        self.current_regime = "NEUTRAL"  # BULL, BEAR, NEUTRAL
        self.spy_price = None
        self.spy_ma20 = None
        self.spy_ma50 = None
        self.regime_strength = 0.0  # -1.0 (strong bear) to +1.0 (strong bull)
        self.last_update = None
        
        # Bear ETF symbols (these benefit in down markets)
        self.bear_etf_symbols = {
            # Index 3x Bear
            'SRTY', 'TZA', 'SQQQ', 'SPXS', 'SPXU', 'SDOW',
            # Index 2x Bear
            'TWM', 'QID', 'SDS', 'DXD',
            # Sector 3x Bear
            'TECS', 'FAZ', 'LABD', 'FNGD', 'WEBS', 'DRIP',
            # Stock 2x Bear
            'MUD', 'METD', 'TSLS', 'NVDD', 'ETHD', 'BITX', 'SBIT',
            'PLTD', 'DUST', 'PALD', 'AMDD', 'MSFD'
        }
        
        log.info("🌍 Market Regime Detector initialized")
    
    def detect_regime(self) -> str:
        """
        Detect market regime using SPY analysis
        
        Uses multiple indicators:
        - 20-day MA: Short-term trend
        - 50-day MA: Medium-term trend
        - Price momentum
        
        Returns: "BULL", "BEAR", or "NEUTRAL"
        """
        try:
            # Fetch SPY data
            spy = yf.Ticker("SPY")
            hist = spy.history(period="3mo", interval="1d")
            
            if hist.empty or len(hist) < 50:
                log.warning("⚠️ Insufficient SPY data for regime detection")
                return "NEUTRAL"
            
            # Get current price
            self.spy_price = hist['Close'].iloc[-1]
            
            # Calculate moving averages
            self.spy_ma20 = hist['Close'].tail(20).mean()
            self.spy_ma50 = hist['Close'].tail(50).mean()
            
            # Calculate regime strength
            # Factor 1: Price vs MA20 (40% weight)
            ma20_diff = (self.spy_price - self.spy_ma20) / self.spy_ma20
            ma20_score = max(-1.0, min(1.0, ma20_diff * 50))  # Normalize to -1 to 1
            
            # Factor 2: Price vs MA50 (30% weight)
            ma50_diff = (self.spy_price - self.spy_ma50) / self.spy_ma50
            ma50_score = max(-1.0, min(1.0, ma50_diff * 50))
            
            # Factor 3: MA20 vs MA50 (30% weight)
            ma_cross = (self.spy_ma20 - self.spy_ma50) / self.spy_ma50
            ma_cross_score = max(-1.0, min(1.0, ma_cross * 50))
            
            # Composite regime strength
            self.regime_strength = (
                ma20_score * 0.40 +
                ma50_score * 0.30 +
                ma_cross_score * 0.30
            )
            
            # Determine regime
            if self.regime_strength > 0.15:  # Strong bullish
                self.current_regime = "BULL"
            elif self.regime_strength < -0.15:  # Strong bearish
                self.current_regime = "BEAR"
            else:
                self.current_regime = "NEUTRAL"
            
            self.last_update = datetime.now()
            
            log.info(f"📊 Market Regime: {self.current_regime}")
            log.info(f"   SPY: ${self.spy_price:.2f}")
            log.info(f"   MA20: ${self.spy_ma20:.2f} ({ma20_diff:+.2%})")
            log.info(f"   MA50: ${self.spy_ma50:.2f} ({ma50_diff:+.2%})")
            log.info(f"   Regime Strength: {self.regime_strength:+.2f}")
            
            return self.current_regime
            
        except Exception as e:
            log.error(f"Error detecting market regime: {e}")
            return "NEUTRAL"
    
    def is_bear_etf(self, symbol: str) -> bool:
        """Check if symbol is a bear/inverse ETF"""
        return symbol in self.bear_etf_symbols
    
    def get_symbol_weight(self, symbol: str) -> float:
        """
        Get weight multiplier for a symbol based on market regime
        
        Args:
            symbol: Symbol to weight
            
        Returns:
            Weight multiplier (0.3 to 1.7)
            - Bull market: Bull ETFs get 1.5x, Bear ETFs get 0.5x
            - Bear market: Bear ETFs get 1.5x, Bull ETFs get 0.5x
            - Neutral: All ETFs get 1.0x
        """
        is_bear = self.is_bear_etf(symbol)
        
        if self.current_regime == "BULL":
            # Favor bull ETFs, reduce bear ETFs
            if is_bear:
                return 0.5  # Reduce bear ETF allocation
            else:
                return 1.5  # Increase bull ETF allocation
        
        elif self.current_regime == "BEAR":
            # Favor bear ETFs, reduce bull ETFs
            if is_bear:
                return 1.5  # Increase bear ETF allocation
            else:
                return 0.5  # Reduce bull ETF allocation
        
        else:
            # Neutral - equal weight
            return 1.0
    
    def get_position_size_multiplier(self, symbol: str) -> float:
        """
        Get position size multiplier based on regime and symbol type
        
        This adjusts position sizes to allocate more capital to
        symbols that align with the current market regime.
        
        Returns:
            Multiplier (0.7 to 1.3)
        """
        is_bear = self.is_bear_etf(symbol)
        
        # Use regime strength for fine-tuned adjustment
        if is_bear:
            # Bear ETFs: Benefit from negative regime strength
            multiplier = 1.0 - (self.regime_strength * 0.3)
        else:
            # Bull ETFs: Benefit from positive regime strength
            multiplier = 1.0 + (self.regime_strength * 0.3)
        
        # Clamp to reasonable range
        return max(0.7, min(1.3, multiplier))
    
    def should_filter_symbol(self, symbol: str) -> bool:
        """
        Determine if a symbol should be filtered out based on regime
        
        In strong bull/bear markets, we may want to completely skip
        counter-trend symbols to focus capital on aligned opportunities.
        
        Returns:
            True if symbol should be skipped
        """
        # Only filter in STRONG regimes (not neutral)
        if abs(self.regime_strength) < 0.30:
            return False  # Don't filter in weak/neutral regimes
        
        is_bear = self.is_bear_etf(symbol)
        
        # Filter out counter-trend symbols in strong regimes
        if self.regime_strength > 0.30 and is_bear:
            # Strong bull market, skip bear ETFs
            log.debug(f"⏭️  Filtering {symbol} (bear ETF in strong bull market)")
            return True
        
        if self.regime_strength < -0.30 and not is_bear:
            # Strong bear market, skip bull ETFs
            log.debug(f"⏭️  Filtering {symbol} (bull ETF in strong bear market)")
            return True
        
        return False
    
    def get_regime_summary(self) -> Dict[str, Any]:
        """Get current regime summary"""
        return {
            'regime': self.current_regime,
            'strength': self.regime_strength,
            'spy_price': self.spy_price,
            'spy_ma20': self.spy_ma20,
            'spy_ma50': self.spy_ma50,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'bear_etf_count': len(self.bear_etf_symbols)
        }

# Factory function
def get_market_regime_detector() -> MarketRegimeDetector:
    """Get Market Regime Detector instance"""
    return MarketRegimeDetector()

