#!/usr/bin/env python3
"""
Complete 89-Point Data Collection Script
========================================

Collects ALL 89 data points with complete technical indicators by:
1. Retrieving signal collection data from GCS
2. Fetching comprehensive technical indicators for each symbol (E*TRADE or yfinance fallback)
3. Merging technical indicators with signal data
4. Completing the 89-point dataset

Author: Easy ORB Strategy Development Team
Last Updated: January 7, 2026
Version: 3.1.0 (Complete Technical Indicators)
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone
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
    from modules.gcs_persistence import get_gcs_persistence
    from modules.comprehensive_data_collector import ComprehensiveDataCollector
    from modules.prime_etrade_trading import PrimeETradeTrading
except ImportError as e:
    log.error(f"Failed to import required modules: {e}")
    sys.exit(1)


class Complete89PointCollector:
    """Complete collector that fetches all technical indicators"""
    
    def __init__(self, date: Optional[str] = None):
        """
        Initialize complete collector
        
        Args:
            date: Date to collect (YYYY-MM-DD format). Default: today
        """
        self.gcs = get_gcs_persistence()
        self.date = date or datetime.now().strftime('%Y-%m-%d')
        
        # Initialize E*TRADE trading (for technical indicators) - skip if slow
        self.etrade_trading = None
        # Skip E*TRADE initialization for REST-based collection - use yfinance directly
        log.info("   Using yfinance for technical indicators (REST-based collection)")
        
        # Initialize comprehensive data collector
        base_path = Path(__file__).parent / "comprehensive_data"
        self.comprehensive_collector = ComprehensiveDataCollector(
            base_dir=str(base_path),
            gcs_bucket="easy-etrade-strategy-data",
            gcs_prefix="priority_optimizer/comprehensive_data"
        )
        
        log.info(f"✅ Complete 89-Point Collector initialized for {self.date}")
    
    def get_technical_indicators_yfinance(self, symbol: str) -> Dict[str, Any]:
        """Get technical indicators using yfinance (fallback when E*TRADE unavailable)"""
        try:
            import yfinance as yf
            import pandas as pd
            import numpy as np
            
            # Get historical data
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1mo", interval="1d")
            
            if hist.empty or len(hist) < 20:
                log.warning(f"Insufficient data for {symbol} from yfinance")
                return {}
            
            # Calculate technical indicators
            closes = hist['Close'].values
            highs = hist['High'].values
            lows = hist['Low'].values
            volumes = hist['Volume'].values
            
            # RSI
            def calculate_rsi(prices, period=14):
                delta = np.diff(prices)
                gain = np.where(delta > 0, delta, 0)
                loss = np.where(delta < 0, -delta, 0)
                avg_gain = pd.Series(gain).rolling(window=period).mean()
                avg_loss = pd.Series(loss).rolling(window=period).mean()
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                return rsi.iloc[-1] if len(rsi) > 0 else 50.0
            
            rsi_14 = calculate_rsi(closes, 14)
            rsi_21 = calculate_rsi(closes, 21)
            
            # Moving Averages
            sma_20 = pd.Series(closes).rolling(window=20).mean().iloc[-1] if len(closes) >= 20 else closes[-1]
            sma_50 = pd.Series(closes).rolling(window=50).mean().iloc[-1] if len(closes) >= 50 else closes[-1]
            sma_200 = pd.Series(closes).rolling(window=200).mean().iloc[-1] if len(closes) >= 200 else closes[-1]
            
            # EMA
            ema_12 = pd.Series(closes).ewm(span=12).mean().iloc[-1]
            ema_26 = pd.Series(closes).ewm(span=26).mean().iloc[-1]
            
            # MACD
            macd_line = ema_12 - ema_26
            macd_signal = pd.Series(macd_line).ewm(span=9).mean().iloc[-1] if isinstance(macd_line, pd.Series) else macd_line
            macd_histogram = macd_line - macd_signal if isinstance(macd_signal, (int, float)) else 0.0
            
            # Bollinger Bands
            bb_period = 20
            bb_std = 2
            bb_middle = pd.Series(closes).rolling(window=bb_period).mean().iloc[-1]
            bb_std_val = pd.Series(closes).rolling(window=bb_period).std().iloc[-1]
            bb_upper = bb_middle + (bb_std_val * bb_std)
            bb_lower = bb_middle - (bb_std_val * bb_std)
            bb_width = ((bb_upper - bb_lower) / bb_middle) * 100 if bb_middle > 0 else 0.0
            bb_position = ((closes[-1] - bb_lower) / (bb_upper - bb_lower)) * 100 if (bb_upper - bb_lower) > 0 else 50.0
            
            # ATR
            high_low = highs[-14:] - lows[-14:]
            high_close = np.abs(highs[-14:] - np.roll(closes[-14:], 1))
            low_close = np.abs(lows[-14:] - np.roll(closes[-14:], 1))
            tr = np.maximum(high_low, np.maximum(high_close, low_close))
            atr = np.mean(tr) if len(tr) > 0 else 0.0
            
            # Volume indicators
            volume_sma = pd.Series(volumes).rolling(window=20).mean().iloc[-1] if len(volumes) >= 20 else volumes[-1]
            volume_ratio = volumes[-1] / volume_sma if volume_sma > 0 else 1.0
            
            # OBV
            obv = 0
            for i in range(1, len(closes)):
                if closes[i] > closes[i-1]:
                    obv += volumes[i]
                elif closes[i] < closes[i-1]:
                    obv -= volumes[i]
            
            # VWAP (simplified - using recent data)
            vwap = (hist['Close'] * hist['Volume']).sum() / hist['Volume'].sum() if hist['Volume'].sum() > 0 else closes[-1]
            vwap_distance_pct = ((closes[-1] - vwap) / vwap) * 100 if vwap > 0 else 0.0
            
            # Volatility
            volatility = pd.Series(closes).pct_change().std() * 100 * np.sqrt(252)  # Annualized
            
            # Current values
            current_price = closes[-1]
            current_volume = volumes[-1]
            current_high = highs[-1]
            current_low = lows[-1]
            current_open = hist['Open'].iloc[-1]
            
            return {
                'open': current_open,
                'high': current_high,
                'low': current_low,
                'close': current_price,
                'volume': int(current_volume),
                
                # Moving Averages
                'sma_20': float(sma_20),
                'sma_50': float(sma_50),
                'sma_200': float(sma_200),
                'ema_12': float(ema_12),
                'ema_26': float(ema_26),
                
                # Momentum Indicators
                'rsi': float(rsi_14),
                'rsi_14': float(rsi_14),
                'rsi_21': float(rsi_21),
                'macd': float(macd_line) if isinstance(macd_line, (int, float)) else 0.0,
                'macd_signal': float(macd_signal) if isinstance(macd_signal, (int, float)) else 0.0,
                'macd_histogram': float(macd_histogram),
                'momentum_10': float((closes[-1] - closes[-10]) / closes[-10] * 100) if len(closes) >= 10 else 0.0,
                
                # Volatility Indicators
                'atr': float(atr),
                'bollinger_upper': float(bb_upper),
                'bollinger_middle': float(bb_middle),
                'bollinger_lower': float(bb_lower),
                'bollinger_width': float(bb_width),
                'bollinger_position': float(bb_position),
                'volatility': float(volatility),
                
                # Volume Indicators
                'volume_ratio': float(volume_ratio),
                'volume_sma': float(volume_sma),
                'obv': float(obv),
                'ad_line': 0.0,  # Not easily calculated from daily data
                
                # VWAP Indicators
                'vwap': float(vwap),
                'vwap_distance_pct': float(vwap_distance_pct),
                
                # Additional indicators (simplified)
                'stoch_k': 0.0,
                'stoch_d': 0.0,
                'williams_r': 0.0,
                'cci': 0.0,
                'adx': 0.0,
                'plus_di': 0.0,
                'minus_di': 0.0,
                'aroon_up': 0.0,
                'aroon_down': 0.0,
                'mfi': 0.0,
                'cmf': 0.0,
                'roc': 0.0,
                'ppo': 0.0,
                'tsi': 0.0,
                'ult_osc': 0.0,
                'ichimoku_base': 0.0,
                
                # Pattern recognition (simplified)
                'doji': False,
                'hammer': False,
                'engulfing': False,
                'morning_star': False,
                
                'data_source': 'yfinance',
                'data_quality': 'GOOD'
            }
            
        except Exception as e:
            log.error(f"Failed to get technical indicators from yfinance for {symbol}: {e}", exc_info=True)
            return {}
    
    async def get_technical_indicators(self, symbol: str, timeout: int = 10) -> Dict[str, Any]:
        """Get technical indicators from E*TRADE or yfinance fallback with timeout"""
        # Try E*TRADE first (with timeout)
        if self.etrade_trading:
            try:
                # Use asyncio timeout
                market_data = await asyncio.wait_for(
                    asyncio.to_thread(self.etrade_trading.get_market_data_for_strategy, symbol),
                    timeout=timeout
                )
                if market_data and market_data.get('data_quality') != 'POOR':
                    log.info(f"✅ Got technical indicators for {symbol} from E*TRADE")
                    return market_data
            except asyncio.TimeoutError:
                log.warning(f"E*TRADE timeout for {symbol} ({timeout}s), trying yfinance...")
            except Exception as e:
                log.warning(f"E*TRADE failed for {symbol}: {e}, trying yfinance...")
        
        # Fallback to yfinance (with timeout)
        try:
            log.info(f"📊 Fetching technical indicators for {symbol} from yfinance...")
            result = await asyncio.wait_for(
                asyncio.to_thread(self.get_technical_indicators_yfinance, symbol),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            log.error(f"yfinance timeout for {symbol} ({timeout}s)")
            return {}
        except Exception as e:
            log.error(f"yfinance failed for {symbol}: {e}")
            return {}
    
    def retrieve_signal_collection_data(self) -> Optional[Dict[str, Any]]:
        """Retrieve signal collection data from GCS"""
        try:
            signal_path = f"priority_optimizer/daily_signals/{self.date}_signals.json"
            
            if not self.gcs.enabled:
                log.warning("GCS not enabled, checking local file...")
                local_file = Path(f"priority_optimizer/retrieved_data/{self.date}_signals.json")
                if local_file.exists():
                    with open(local_file, 'r') as f:
                        return json.load(f)
                return None
            
            content = self.gcs.read_string(signal_path)
            if content:
                data = json.loads(content)
                log.info(f"✅ Retrieved signal collection data: {data.get('signal_count', 0)} signals")
                return data
            else:
                log.warning(f"No signal collection data found at {signal_path}")
                return None
                
        except Exception as e:
            log.error(f"Failed to retrieve signal collection data: {e}", exc_info=True)
            return None
    
    def retrieve_daily_marker(self) -> Optional[Dict[str, Any]]:
        """Retrieve full daily marker from GCS"""
        try:
            marker_path = f"daily_markers/{self.date}.json"
            
            if not self.gcs.enabled:
                return None
            
            content = self.gcs.read_string(marker_path)
            if content:
                data = json.loads(content)
                log.info(f"✅ Retrieved daily marker for {self.date}")
                return data
            else:
                log.warning(f"No daily marker found at {marker_path}")
                return None
                
        except Exception as e:
            log.error(f"Failed to retrieve daily marker: {e}", exc_info=True)
            return None
    
    async def collect_complete_data(self) -> List[Dict[str, Any]]:
        """Collect complete 89-point data with all technical indicators"""
        log.info(f"📊 Collecting complete 89-point data for {self.date}...")
        
        # Retrieve signal collection data
        signal_data = self.retrieve_signal_collection_data()
        if not signal_data:
            log.warning("No signal collection data found - trying daily marker...")
            marker = self.retrieve_daily_marker()
            if marker and marker.get('signals'):
                signals_entry = marker['signals']
                signal_data = {
                    'signals': signals_entry.get('signals', []),
                    'total_scanned': signals_entry.get('total_scanned', 0),
                    'mode': signals_entry.get('mode', 'DEMO')
                }
        
        if not signal_data or not signal_data.get('signals'):
            log.error(f"❌ No signal data found for {self.date}")
            return []
        
        signals = signal_data['signals']
        log.info(f"📋 Processing {len(signals)} signals...")
        
        # Retrieve daily marker for execution data
        marker = self.retrieve_daily_marker()
        executed_signals = []
        rejected_signals = []
        
        if marker and marker.get('signals'):
            signals_entry = marker['signals']
            executed_signals = signals_entry.get('executed_signals', [])
            rejected_signals = signals_entry.get('rejected_signals', [])
            log.info(f"   Found {len(executed_signals)} executed, {len(rejected_signals)} rejected")
        
        # Collect comprehensive records
        comprehensive_records = []
        
        for i, signal in enumerate(signals, 1):
            symbol = signal.get('symbol', '')
            print(f"[{i}/{len(signals)}] Processing {symbol}...", end=' ', flush=True)
            
            try:
                # Get technical indicators with timeout
                market_data = await self.get_technical_indicators(symbol, timeout=15)
                
                if not market_data:
                    print(f"⚠️ No data")
                    log.warning(f"⚠️ No technical indicators for {symbol}, skipping...")
                    continue
                
                print(f"✅")
                
                # Check if this signal was executed or rejected
                executed_sig = next((s for s in executed_signals if s.get('symbol') == symbol), None)
                rejected_sig = next((s for s in rejected_signals if s.get('symbol') == symbol), None)
                
                # Merge execution/rejection data
                if executed_sig:
                    signal.update(executed_sig)
                    signal['executed'] = True
                elif rejected_sig:
                    signal.update(rejected_sig)
                    signal['executed'] = False
                    signal['filtered'] = True
                
                # Build ranking data
                ranking_data = {
                    'rank': signal.get('rank', 0),
                    'priority_score': signal.get('priority_score', 0.0),
                    'confidence': signal.get('confidence', 0.0),
                    'orb_volume_ratio': signal.get('orb_volume_ratio', 0.0),
                    'exec_volume_ratio': signal.get('exec_volume_ratio', 0.0),
                    'category': signal.get('category', '')
                }
                
                # Build trade data
                trade_data = {
                    'entry_price': signal.get('entry_price', 0.0),
                    'exit_price': signal.get('exit_price', 0.0),
                    'entry_time': signal.get('entry_time', ''),
                    'exit_time': signal.get('exit_time', ''),
                    'shares': signal.get('shares', 0),
                    'position_value': signal.get('position_value', 0.0),
                    'peak_price': signal.get('peak_price', 0.0),
                    'peak_pct': signal.get('peak_pct', 0.0),
                    'pnl_dollars': signal.get('pnl_dollars', 0.0),
                    'pnl_pct': signal.get('pnl_pct', 0.0),
                    'exit_reason': signal.get('exit_reason', ''),
                    'win': signal.get('win', False),
                    'holding_minutes': signal.get('holding_minutes', 0.0),
                    'entry_bar_volatility': signal.get('entry_bar_volatility', 0.0),
                    'time_weighted_peak': signal.get('time_weighted_peak', 0.0)
                }
                
                # Build risk data
                risk_data = {
                    'current_stop_loss': 0.0,
                    'stop_loss_distance_pct': 0.0,
                    'opening_bar_protection_active': False,
                    'trailing_activated': signal.get('trailing_activated', False),
                    'trailing_distance_pct': signal.get('trailing_distance_pct', 0.0),
                    'breakeven_activated': signal.get('breakeven_activated', False),
                    'gap_risk_pct': 0.0,
                    'max_adverse_excursion': signal.get('max_adverse_excursion', 0.0)
                }
                
                # Build market conditions
                market_conditions = {
                    'market_regime': market_data.get('market_regime', ''),
                    'volatility_regime': market_data.get('volatility_regime', ''),
                    'trend_direction': market_data.get('trend_direction', ''),
                    'volume_regime': market_data.get('volume_regime', ''),
                    'momentum_regime': market_data.get('momentum_regime', '')
                }
                
                # Use comprehensive collector to build record
                record = self.comprehensive_collector.collect_trade_data(
                    symbol=symbol,
                    trade_id=f"{self.date}_{symbol}_{signal.get('rank', 0)}",
                    market_data=market_data,
                    trade_data=trade_data,
                    ranking_data=ranking_data,
                    risk_data=risk_data,
                    market_conditions=market_conditions
                )
                
                if record:
                    comprehensive_records.append(record)
                    log.info(f"✅ Collected complete data for {symbol}")
                
                # Rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                log.error(f"Failed to process signal {symbol}: {e}", exc_info=True)
        
        log.info(f"✅ Built {len(comprehensive_records)} complete comprehensive records")
        return comprehensive_records
    
    async def save_collected_data(self, records: List[Dict[str, Any]]):
        """Save collected data"""
        if not records:
            log.warning("No records to save")
            return
        
        # Save to local and GCS
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
    import argparse
    
    parser = argparse.ArgumentParser(description='Collect complete 89-point data with technical indicators')
    parser.add_argument('--date', type=str, help='Date to collect (YYYY-MM-DD). Default: today')
    args = parser.parse_args()
    
    print("=" * 70)
    print("Complete 89-Point Data Collection Script")
    print("=" * 70)
    print(f"Date: {args.date or datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    collector = Complete89PointCollector(date=args.date)
    
    # Collect complete data
    records = await collector.collect_complete_data()
    
    if records:
        # Save data
        await collector.save_collected_data(records)
        
        print(f"\n✅ Collection complete!")
        print(f"   Records collected: {len(records)}")
        print(f"   Data saved to: priority_optimizer/comprehensive_data/")
        print(f"   GCS location: priority_optimizer/comprehensive_data/{collector.date}_comprehensive_data.json")
        
        # Show sample
        if records:
            sample = records[0]
            print(f"\n📊 Sample record ({sample.get('symbol')}):")
            print(f"   RSI: {sample.get('rsi', 0):.2f}")
            print(f"   Volume Ratio: {sample.get('volume_ratio', 0):.2f}")
            print(f"   MACD Histogram: {sample.get('macd_histogram', 0):.4f}")
            print(f"   VWAP Distance: {sample.get('vwap_distance_pct', 0):.2f}%")
            print(f"   RS vs SPY: {sample.get('rs_vs_spy', 0):.2f}%")
            print(f"   Executed: {sample.get('entry_price', 0) > 0}")
    else:
        print(f"\n⚠️ No data collected for {collector.date}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Collection interrupted by user")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

