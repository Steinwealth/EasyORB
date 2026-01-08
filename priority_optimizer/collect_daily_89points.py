#!/usr/bin/env python3
"""
Daily 89-Point Data Collection Script
======================================

REST-based script to collect 89 comprehensive data points from E*TRADE
for all symbols in the trade list during each trading session.

**Collects data for BOTH strategies:**
- ORB Strategy symbols (from data/watchlist/standard_orders.csv)
- 0DTE Options Strategy symbols (from data/watchlist/0dte_list.csv)

This script should be run during trading hours (7:30 AM - 4:00 PM ET)
to collect all technical indicators before they become unavailable.

Similar to Historical Enhancer pattern:
- Collects data during trading session
- Stores in GCS for later retrieval
- Can be called anytime after collection

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

try:
    from modules.comprehensive_data_collector import ComprehensiveDataCollector
    from modules.config_loader import get_cloud_config
    from modules.prime_etrade_trading import PrimeETradeTrading
    from modules.prime_market_manager import get_prime_market_manager
except ImportError as e:
    log.error(f"Failed to import required modules: {e}")
    sys.exit(1)


class Daily89PointCollector:
    """Collect 89 data points for all symbols during trading session"""
    
    def __init__(self):
        """Initialize collector"""
        self.comprehensive_collector = ComprehensiveDataCollector(
            base_dir="priority_optimizer/comprehensive_data",
            gcs_bucket="easy-etrade-strategy-data",
            gcs_prefix="priority_optimizer/comprehensive_data"
        )
        
        # Initialize E*TRADE trading (for market data)
        try:
            self.etrade_trading = PrimeETradeTrading()
            log.info("✅ E*TRADE trading initialized")
        except Exception as e:
            log.error(f"Failed to initialize E*TRADE trading: {e}")
            self.etrade_trading = None
        
        self.market_manager = get_prime_market_manager()
        self.today_date = datetime.now().strftime('%Y-%m-%d')
        
    def get_trade_list_symbols(self) -> List[str]:
        """Get list of symbols from trade list/watchlist (ORB + 0DTE)"""
        symbols = []
        
        try:
            # Load ORB Strategy symbols
            watchlist_path = Path("data/watchlist/standard_orders.csv")
            if watchlist_path.exists():
                import csv
                with open(watchlist_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        symbol = row.get('Symbol', '').strip()
                        if symbol:
                            symbols.append(symbol)
                log.info(f"📋 Loaded {len(symbols)} ORB Strategy symbols from watchlist")
            else:
                log.warning("ORB Strategy watchlist not found: data/watchlist/standard_orders.csv")
            
            # Load 0DTE Strategy symbols
            dte_list_path = Path("data/watchlist/0dte_list.csv")
            if dte_list_path.exists():
                import csv
                dte_symbols = []
                with open(dte_list_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Handle different column names
                        symbol = row.get('symbol', row.get('Symbol', '')).strip()
                        if symbol and not symbol.startswith('#'):  # Skip comments
                            if symbol not in symbols:  # Avoid duplicates
                                dte_symbols.append(symbol)
                                symbols.append(symbol)
                log.info(f"📋 Loaded {len(dte_symbols)} 0DTE Strategy symbols from watchlist")
            else:
                log.warning("0DTE Strategy watchlist not found: data/watchlist/0dte_list.csv")
            
            if symbols:
                log.info(f"✅ Total symbols to collect: {len(symbols)} (ORB + 0DTE)")
                return symbols
            
            # Fallback: Get from active trades or recent signals
            log.warning("Watchlists not found, using fallback method")
            return []
            
        except Exception as e:
            log.error(f"Failed to get trade list: {e}")
            return []
    
    def get_symbols_from_signals(self) -> List[str]:
        """Get symbols from today's signal collection"""
        try:
            # Check for today's signal file
            signal_file = Path(f"priority_optimizer/recovered_data/daily_signals/{self.today_date}_signals.json")
            if not signal_file.exists():
                # Try GCS
                from modules.gcs_persistence import get_gcs_persistence
                gcs = get_gcs_persistence()
                gcs_path = f"priority_optimizer/daily_signals/{self.today_date}_signals.json"
                if gcs.file_exists(gcs_path):
                    content = gcs.read_string(gcs_path)
                    if content:
                        signal_data = json.loads(content)
                        symbols = [s.get('symbol') for s in signal_data.get('signals', [])]
                        log.info(f"📋 Loaded {len(symbols)} symbols from GCS signals")
                        return symbols
            
            if signal_file.exists():
                with open(signal_file, 'r') as f:
                    signal_data = json.load(f)
                    symbols = [s.get('symbol') for s in signal_data.get('signals', [])]
                    log.info(f"📋 Loaded {len(symbols)} symbols from signal file")
                    return symbols
            
            return []
            
        except Exception as e:
            log.error(f"Failed to get symbols from signals: {e}")
            return []
    
    async def collect_symbol_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Collect 89 data points for a single symbol
        
        Returns comprehensive data record or None if failed
        """
        try:
            if not self.etrade_trading:
                log.warning(f"E*TRADE trading not available for {symbol}")
                return None
            
            # Get comprehensive market data from E*TRADE
            market_data = self.etrade_trading.get_market_data_for_strategy(symbol)
            if not market_data:
                log.warning(f"No market data available for {symbol}")
                return None
            
            # Build comprehensive record structure
            # Note: This is for signal collection, not trade execution
            # So we don't have trade_data, ranking_data, etc.
            # We'll collect what we can from market data
            
            comprehensive_record = {
                'timestamp': datetime.utcnow().isoformat(),
                'date': self.today_date,
                'symbol': symbol,
                'trade_id': f"COLLECTION_{self.today_date}_{symbol}",
                'collection_type': 'daily_signal_collection',
                
                # Price Data (5)
                'open': market_data.get('open', 0.0),
                'high': market_data.get('high', 0.0),
                'low': market_data.get('low', 0.0),
                'close': market_data.get('close', 0.0),
                'volume': market_data.get('volume', 0),
                
                # Moving Averages (5)
                'sma_20': market_data.get('sma_20', 0.0),
                'sma_50': market_data.get('sma_50', 0.0),
                'sma_200': market_data.get('sma_200', 0.0),
                'ema_12': market_data.get('ema_12', 0.0),
                'ema_26': market_data.get('ema_26', 0.0),
                
                # Momentum Indicators (7)
                'rsi': market_data.get('rsi', 0.0),
                'rsi_14': market_data.get('rsi_14', market_data.get('rsi', 0.0)),
                'rsi_21': market_data.get('rsi_21', 0.0),
                'macd': market_data.get('macd', 0.0),
                'macd_signal': market_data.get('macd_signal', 0.0),
                'macd_histogram': market_data.get('macd_histogram', 0.0),
                'momentum_10': market_data.get('momentum_10', market_data.get('momentum', 0.0)),
                
                # Volatility Indicators (7)
                'atr': market_data.get('atr', 0.0),
                'bollinger_upper': market_data.get('bollinger_upper', 0.0),
                'bollinger_middle': market_data.get('bollinger_middle', 0.0),
                'bollinger_lower': market_data.get('bollinger_lower', 0.0),
                'bollinger_width': market_data.get('bollinger_width', 0.0),
                'bollinger_position': market_data.get('bollinger_position', 0.0),
                'volatility': market_data.get('volatility', 0.0),
                
                # Volume Indicators (4)
                'volume_ratio': market_data.get('volume_ratio', 0.0),
                'volume_sma': market_data.get('volume_sma', 0.0),
                'obv': market_data.get('obv', 0.0),
                'ad_line': market_data.get('ad_line', 0.0),
                
                # Pattern Recognition (4)
                'doji': market_data.get('doji', False),
                'hammer': market_data.get('hammer', False),
                'engulfing': market_data.get('engulfing', False),
                'morning_star': market_data.get('morning_star', False),
                
                # VWAP Indicators (2)
                'vwap': market_data.get('vwap', 0.0),
                'vwap_distance_pct': market_data.get('vwap_distance_pct', 0.0),
                
                # Relative Strength (1)
                'rs_vs_spy': market_data.get('rs_vs_spy', 0.0),
                
                # ORB Data (6) - May not be available for all symbols
                'orb_high': market_data.get('orb_high', 0.0),
                'orb_low': market_data.get('orb_low', 0.0),
                'orb_open': market_data.get('orb_open', 0.0),
                'orb_close': market_data.get('orb_close', 0.0),
                'orb_volume': market_data.get('orb_volume', 0),
                'orb_range_pct': market_data.get('orb_range_pct', 0.0),
                
                # Market Context (2)
                'spy_price': market_data.get('spy_price', 0.0),
                'spy_change_pct': market_data.get('spy_change_pct', 0.0),
                
                # Trade Data (15) - Not available for signal collection
                'entry_price': 0.0,
                'exit_price': 0.0,
                'entry_time': '',
                'exit_time': '',
                'shares': 0,
                'position_value': 0.0,
                'peak_price': 0.0,
                'peak_pct': 0.0,
                'pnl_dollars': 0.0,
                'pnl_pct': 0.0,
                'exit_reason': '',
                'win': False,
                'holding_minutes': 0.0,
                'entry_bar_volatility': 0.0,
                'time_weighted_peak': 0.0,
                
                # Ranking Data (6) - May be available from signals
                'rank': 0,
                'priority_score': market_data.get('confidence', 0.0),
                'confidence': market_data.get('confidence', 0.0),
                'orb_volume_ratio': market_data.get('orb_volume_ratio', 0.0),
                'exec_volume_ratio': 0.0,
                'category': '',
                
                # Risk Management (8) - Not available for signal collection
                'current_stop_loss': 0.0,
                'stop_loss_distance_pct': 0.0,
                'opening_bar_protection_active': False,
                'trailing_activated': False,
                'trailing_distance_pct': 0.0,
                'breakeven_activated': False,
                'gap_risk_pct': 0.0,
                'max_adverse_excursion': 0.0,
                
                # Market Conditions (5)
                'market_regime': market_data.get('market_regime', ''),
                'volatility_regime': market_data.get('volatility_regime', ''),
                'trend_direction': market_data.get('trend_direction', ''),
                'volume_regime': market_data.get('volume_regime', ''),
                'momentum_regime': market_data.get('momentum_regime', ''),
                
                # Additional Indicators (16)
                'stoch_k': market_data.get('stoch_k', 0.0),
                'stoch_d': market_data.get('stoch_d', 0.0),
                'williams_r': market_data.get('williams_r', 0.0),
                'cci': market_data.get('cci', 0.0),
                'adx': market_data.get('adx', 0.0),
                'plus_di': market_data.get('plus_di', 0.0),
                'minus_di': market_data.get('minus_di', 0.0),
                'aroon_up': market_data.get('aroon_up', 0.0),
                'aroon_down': market_data.get('aroon_down', 0.0),
                'mfi': market_data.get('mfi', 0.0),
                'cmf': market_data.get('cmf', 0.0),
                'roc': market_data.get('roc', 0.0),
                'ppo': market_data.get('ppo', 0.0),
                'tsi': market_data.get('tsi', 0.0),
                'ult_osc': market_data.get('ult_osc', 0.0),
                'ichimoku_base': market_data.get('ichimoku_base', 0.0),
            }
            
            return comprehensive_record
            
        except Exception as e:
            log.error(f"Failed to collect data for {symbol}: {e}", exc_info=True)
            return None
    
    async def collect_all_symbols(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Collect data for all symbols"""
        log.info(f"📊 Starting collection for {len(symbols)} symbols...")
        
        collected = []
        failed = []
        
        for i, symbol in enumerate(symbols, 1):
            log.info(f"[{i}/{len(symbols)}] Collecting {symbol}...")
            
            # Check market hours
            if not self.market_manager.is_market_open():
                log.warning(f"Market is closed - some data may be unavailable for {symbol}")
            
            record = await self.collect_symbol_data(symbol)
            if record:
                collected.append(record)
                self.comprehensive_collector.comprehensive_data.append(record)
                log.info(f"✅ Collected {symbol}")
            else:
                failed.append(symbol)
                log.warning(f"❌ Failed to collect {symbol}")
            
            # Rate limiting - small delay between requests
            await asyncio.sleep(0.5)
        
        log.info(f"\n📊 Collection Summary:")
        log.info(f"   ✅ Collected: {len(collected)} symbols")
        log.info(f"   ❌ Failed: {len(failed)} symbols")
        if failed:
            log.info(f"   Failed symbols: {', '.join(failed)}")
        
        return collected
    
    async def save_collected_data(self):
        """Save collected data to local and GCS"""
        log.info("💾 Saving collected data...")
        
        try:
            saved_files = await self.comprehensive_collector.save_daily_data(format='both')
            
            if saved_files:
                log.info(f"✅ Data saved:")
                for file_type, file_path in saved_files.items():
                    log.info(f"   {file_type}: {file_path}")
            else:
                log.warning("⚠️ No files saved")
                
        except Exception as e:
            log.error(f"Failed to save data: {e}", exc_info=True)


async def main():
    """Main collection function"""
    print("=" * 70)
    print("Daily 89-Point Data Collection Script")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    collector = Daily89PointCollector()
    
    # Check market hours
    if not collector.market_manager.is_market_open():
        log.warning("⚠️ Market is closed - some data may be unavailable")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("Collection cancelled")
            return
    
    # Get symbols to collect
    print("\n📋 Getting symbol list...")
    symbols = collector.get_trade_list_symbols()
    
    if not symbols:
        # Fallback: Get from signals
        symbols = collector.get_symbols_from_signals()
    
    if not symbols:
        log.error("❌ No symbols found to collect")
        print("\nPlease ensure:")
        print("  1. Watchlist exists: data/watchlist/standard_orders.csv")
        print("  2. Or signal file exists for today")
        return
    
    print(f"📋 Found {len(symbols)} symbols to collect")
    print(f"   Symbols: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}")
    
    # Collect data
    collected = await collector.collect_all_symbols(symbols)
    
    if collected:
        # Save data
        await collector.save_collected_data()
        
        print(f"\n✅ Collection complete!")
        print(f"   Records collected: {len(collected)}")
        print(f"   Data saved to: priority_optimizer/comprehensive_data/")
        print(f"   GCS location: priority_optimizer/comprehensive_data/{collector.today_date}_comprehensive_data.json")
    else:
        print("\n⚠️ No data collected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Collection interrupted by user")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

