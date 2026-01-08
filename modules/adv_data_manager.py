#!/usr/bin/env python3
"""
ADV Data Manager - Slip Guard Component
========================================

Manages Average Daily Volume (ADV) data for all trading symbols to enable
position size capping based on liquidity. Part of the Slip Guard system that
prevents market impact and slippage as account sizes grow.

Key Features:
- Daily ADV data refresh (6:00 AM PT)
- 90-day rolling average calculation
- Simple in-memory caching
- Fallback to cached data if refresh fails
- Integration with risk managers for position capping

Author: Easy Trading Software Team
Date: October 17, 2025
Revision: 00046 - Slip Guard Initial Implementation
"""

import yfinance as yf
from datetime import datetime, timedelta
import logging
import os
import json
from typing import Dict, Optional, List
from pathlib import Path

log = logging.getLogger("adv_data_manager")

class ADVDataManager:
    """
    Simple ADV data manager for Slip Guard position capping.
    
    Fetches and caches Average Daily Volume data for all trading symbols.
    Used by risk managers to cap position sizes at 1% of ADV to prevent
    slippage and market impact.
    """
    
    def __init__(self):
        self.adv_cache: Dict[str, float] = {}  # symbol -> adv_dollars
        self.last_refresh: Optional[datetime] = None
        
        # Configuration
        self.enabled = os.getenv('SLIP_GUARD_ENABLED', 'true').lower() == 'true'
        self.adv_limit_pct = float(os.getenv('SLIP_GUARD_ADV_PCT', '1.0')) / 100.0  # Default 1.0%
        self.lookback_days = int(os.getenv('SLIP_GUARD_LOOKBACK_DAYS', '90'))
        
        # Cache file for persistence (optional)
        self.cache_file = Path('data/adv_cache.json')
        
        if self.enabled:
            log.info(f"✅ ADV Data Manager initialized")
            log.info(f"   Slip Guard Enabled: {self.enabled}")
            log.info(f"   ADV Limit: {self.adv_limit_pct * 100}% of ADV")
            log.info(f"   Lookback Days: {self.lookback_days}")
            
            # Try to load cached data
            self._load_cache_from_file()
        else:
            log.info("⚪ Slip Guard DISABLED - ADV data manager inactive")
    
    def get_adv(self, symbol: str) -> float:
        """
        Get ADV in dollars for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            ADV in dollars, or 0 if not found/disabled
        """
        if not self.enabled:
            return 0.0
        
        return self.adv_cache.get(symbol, 0.0)
    
    def get_adv_limit(self, symbol: str, mode: str = "aggressive") -> float:
        """
        Get position size limit based on ADV.
        
        Args:
            symbol: Trading symbol
            mode: "conservative" (0.5% ADV) or "aggressive" (1.0% ADV)
            
        Returns:
            Max position size in dollars
        """
        if not self.enabled:
            return float('inf')  # No limit if disabled
        
        adv = self.get_adv(symbol)
        if adv == 0:
            return float('inf')  # No limit if no ADV data
        
        # Conservative = 0.5% ADV, Aggressive = 1.0% ADV
        limit_pct = 0.005 if mode == "conservative" else self.adv_limit_pct
        
        return adv * limit_pct
    
    def refresh_adv_data(self, symbols: List[str]) -> Dict[str, float]:
        """
        Fetch ADV data for all symbols (call daily at 6:00 AM PT).
        
        Uses yfinance to fetch historical data and calculate 90-day
        rolling average of volume × price.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict of symbol -> adv_dollars
        """
        if not self.enabled:
            log.info("Slip Guard disabled - skipping ADV refresh")
            return {}
        
        log.info(f"🔄 Refreshing ADV data for {len(symbols)} symbols...")
        log.info(f"   Lookback period: {self.lookback_days} days")
        
        success_count = 0
        failed_symbols = []
        
        for symbol in symbols:
            try:
                # Fetch historical data
                ticker = yf.Ticker(symbol)
                end_date = datetime.now()
                start_date = end_date - timedelta(days=self.lookback_days + 30)  # Extra buffer
                
                hist = ticker.history(start=start_date, end=end_date)
                
                if hist.empty or len(hist) < 30:
                    log.warning(f"  {symbol}: Insufficient data (only {len(hist)} days)")
                    failed_symbols.append(symbol)
                    continue
                
                # Calculate ADV (90-day rolling average)
                recent_hist = hist.tail(self.lookback_days)
                avg_volume = recent_hist['Volume'].mean()
                current_price = hist['Close'].iloc[-1]
                adv_dollars = avg_volume * current_price
                
                # Store in cache
                self.adv_cache[symbol] = float(adv_dollars)
                success_count += 1
                
                log.debug(f"  {symbol}: ADV ${adv_dollars:,.0f} (${current_price:.2f}/share, {int(avg_volume):,} shares/day)")
                
            except Exception as e:
                log.error(f"  {symbol}: Failed to fetch ADV - {e}")
                failed_symbols.append(symbol)
        
        self.last_refresh = datetime.now()
        
        log.info(f"✅ ADV refresh complete: {success_count}/{len(symbols)} symbols")
        if failed_symbols:
            log.warning(f"   Failed symbols ({len(failed_symbols)}): {', '.join(failed_symbols[:10])}")
        
        # Save to cache file
        self._save_cache_to_file()
        
        return self.adv_cache
    
    def is_data_stale(self, max_age_hours: int = 24) -> bool:
        """
        Check if ADV data is stale (too old).
        
        Args:
            max_age_hours: Maximum age in hours before considered stale
            
        Returns:
            True if stale or no refresh yet
        """
        if not self.last_refresh:
            return True
        
        age = (datetime.now() - self.last_refresh).total_seconds() / 3600
        return age > max_age_hours
    
    def get_stats(self) -> Dict[str, any]:
        """Get ADV manager statistics"""
        return {
            'enabled': self.enabled,
            'symbols_loaded': len(self.adv_cache),
            'last_refresh': self.last_refresh.isoformat() if self.last_refresh else None,
            'data_age_hours': (datetime.now() - self.last_refresh).total_seconds() / 3600 if self.last_refresh else None,
            'is_stale': self.is_data_stale(),
            'adv_limit_pct': self.adv_limit_pct * 100
        }
    
    def _save_cache_to_file(self):
        """Save ADV cache to file for persistence"""
        try:
            cache_data = {
                'adv_data': self.adv_cache,
                'last_refresh': self.last_refresh.isoformat() if self.last_refresh else None,
                'lookback_days': self.lookback_days
            }
            
            # Ensure data directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            log.debug(f"💾 ADV cache saved to {self.cache_file}")
            
        except Exception as e:
            log.error(f"Failed to save ADV cache: {e}")
    
    def _load_cache_from_file(self):
        """Load ADV cache from file (fallback on startup)"""
        try:
            if not self.cache_file.exists():
                log.debug("No ADV cache file found")
                return
            
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)
            
            self.adv_cache = cache_data.get('adv_data', {})
            
            refresh_str = cache_data.get('last_refresh')
            if refresh_str:
                self.last_refresh = datetime.fromisoformat(refresh_str)
            
            age_hours = (datetime.now() - self.last_refresh).total_seconds() / 3600 if self.last_refresh else None
            
            log.info(f"📂 Loaded cached ADV data: {len(self.adv_cache)} symbols")
            if age_hours:
                log.info(f"   Cache age: {age_hours:.1f} hours")
                if age_hours > 48:
                    log.warning(f"   ⚠️ Cache is stale (>{age_hours:.0f} hours old) - refresh recommended")
            
        except Exception as e:
            log.warning(f"Failed to load ADV cache: {e}")

# ============================================================================
# GLOBAL SINGLETON
# ============================================================================

_adv_manager_instance: Optional[ADVDataManager] = None

def get_adv_manager() -> ADVDataManager:
    """
    Get or create global ADV manager instance.
    
    Returns:
        ADVDataManager singleton instance
    """
    global _adv_manager_instance
    
    if _adv_manager_instance is None:
        _adv_manager_instance = ADVDataManager()
    
    return _adv_manager_instance

