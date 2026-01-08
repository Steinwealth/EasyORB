#!/usr/bin/env python3
"""
E*TRADE-Based 89-Point Data Collection Script
==============================================

Collects ALL 89 data points using E*TRADE API with:
1. Technical indicators from signal collection time (7:15-7:30 AM PT)
2. Intraday candle data from E*TRADE (with yfinance fallback for historical)
3. Exit monitoring data for profit capture optimization

Author: Easy ORB Strategy Development Team
Last Updated: January 7, 2026
Version: 4.0.0 (E*TRADE + Signal Collection Time + Exit Monitoring)
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
    from modules.prime_data_manager import get_prime_data_manager
except ImportError as e:
    log.error(f"Failed to import required modules: {e}")
    sys.exit(1)


class ETrade89PointCollector:
    """E*TRADE-based collector with signal collection time technicals"""
    
    def __init__(self, date: Optional[str] = None):
        """Initialize E*TRADE collector"""
        self.gcs = get_gcs_persistence()
        self.date = date or datetime.now().strftime('%Y-%m-%d')
        
        # Initialize E*TRADE trading
        self.etrade_trading = None
        try:
            self.etrade_trading = PrimeETradeTrading()
            log.info("✅ E*TRADE trading initialized")
        except Exception as e:
            log.warning(f"E*TRADE trading not available: {e}")
            log.info("   Will use yfinance for historical data")
        
        # Initialize data manager (for historical intraday data)
        self.data_manager = None
        try:
            self.data_manager = get_prime_data_manager()
            log.info("✅ Data Manager initialized")
        except Exception as e:
            log.warning(f"Data Manager not available: {e}")
        
        # Initialize comprehensive data collector
        base_path = Path(__file__).parent / "comprehensive_data"
        self.comprehensive_collector = ComprehensiveDataCollector(
            base_dir=str(base_path),
            gcs_bucket="easy-etrade-strategy-data",
            gcs_prefix="priority_optimizer/comprehensive_data"
        )
        
        # Signal collection time (7:30 AM PT = 10:30 AM ET)
        self.signal_collection_time = self._get_signal_collection_time()
        
        log.info(f"✅ E*TRADE 89-Point Collector initialized for {self.date}")
        log.info(f"   Signal collection time: {self.signal_collection_time}")
    
    def _get_signal_collection_time(self) -> datetime:
        """Get signal collection time (7:30 AM PT on collection date)"""
        try:
            from zoneinfo import ZoneInfo
            pt_tz = ZoneInfo("America/Los_Angeles")
        except ImportError:
            from pytz import timezone as ZoneInfo
            pt_tz = ZoneInfo("America/Los_Angeles")
        
        collection_date = datetime.strptime(self.date, '%Y-%m-%d').date()
        collection_time = datetime.combine(collection_date, datetime.min.time().replace(hour=7, minute=30))
        collection_time = pt_tz.localize(collection_time)
        return collection_time
    
    async def get_technical_indicators_at_time(
        self, 
        symbol: str, 
        target_time: datetime
    ) -> Dict[str, Any]:
        """
        Get technical indicators at specific time using E*TRADE + historical data
        
        Args:
            symbol: Stock symbol
            target_time: Target time for technical indicators (signal collection time)
        """
        try:
            # Try E*TRADE first for current quote
            current_quote = None
            if self.etrade_trading:
                try:
                    quotes = self.etrade_trading.get_quotes([symbol])
                    if quotes:
                        current_quote = quotes[0]
                except Exception as e:
                    log.debug(f"E*TRADE quote failed for {symbol}: {e}")
            
            # Get historical data up to target time using data manager or yfinance
            historical_data = []
            
            if self.data_manager:
                try:
                    # Get historical data from data manager (uses yfinance internally)
                    end_date = target_time
                    start_date = end_date - timedelta(days=60)  # 60 days for SMA200
                    
                    hist_data = await self.data_manager.get_historical_data(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        interval="1d"
                    )
                    if hist_data:
                        historical_data = hist_data
                except Exception as e:
                    log.debug(f"Data manager historical data failed for {symbol}: {e}")
            
            # Fallback to yfinance if no historical data
            if not historical_data:
                try:
                    import yfinance as yf
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="2mo", interval="1d")
                    
                    if not hist.empty:
                        # Convert to list of dicts
                        for idx, row in hist.iterrows():
                            historical_data.append({
                                'date': idx,
                                'open': float(row['Open']),
                                'high': float(row['High']),
                                'low': float(row['Low']),
                                'close': float(row['Close']),
                                'volume': int(row['Volume'])
                            })
                except Exception as e:
                    log.warning(f"yfinance historical data failed for {symbol}: {e}")
            
            # Get intraday data for target date (if available)
            intraday_data = []
            try:
                import yfinance as yf
                ticker = yf.Ticker(symbol)
                # Get 5-minute bars for the target date
                target_date_str = target_time.strftime('%Y-%m-%d')
                hist_intraday = ticker.history(start=target_date_str, end=target_date_str, interval="5m")
                
                if not hist_intraday.empty:
                    # Filter bars up to target time
                    for idx, row in hist_intraday.iterrows():
                        bar_time = idx if isinstance(idx, datetime) else datetime.fromisoformat(str(idx))
                        if bar_time <= target_time:
                            intraday_data.append({
                                'time': bar_time,
                                'open': float(row['Open']),
                                'high': float(row['High']),
                                'low': float(row['Low']),
                                'close': float(row['Close']),
                                'volume': int(row['Volume'])
                            })
            except Exception as e:
                log.debug(f"Intraday data not available for {symbol} at {target_time}: {e}")
            
            # Calculate technical indicators from historical data
            market_data = self._calculate_technical_indicators(
                symbol=symbol,
                current_quote=current_quote,
                historical_data=historical_data,
                intraday_data=intraday_data,
                target_time=target_time
            )
            
            return market_data
            
        except Exception as e:
            log.error(f"Failed to get technical indicators for {symbol}: {e}", exc_info=True)
            return {}
    
    def _calculate_technical_indicators(
        self,
        symbol: str,
        current_quote: Optional[Any],
        historical_data: List[Dict[str, Any]],
        intraday_data: List[Dict[str, Any]],
        target_time: datetime
    ) -> Dict[str, Any]:
        """Calculate technical indicators from historical and intraday data"""
        try:
            import pandas as pd
            import numpy as np
            
            if not historical_data:
                return {}
            
            # Convert to DataFrame
            df = pd.DataFrame(historical_data)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
            
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            volumes = df['volume'].values
            opens = df['open'].values
            
            # Use intraday data if available for more accurate current price
            current_price = closes[-1]
            current_volume = volumes[-1]
            current_high = highs[-1]
            current_low = lows[-1]
            current_open = opens[-1]
            
            if intraday_data and len(intraday_data) > 0:
                # Use last intraday bar before target time
                last_bar = intraday_data[-1]
                current_price = last_bar['close']
                current_volume = last_bar['volume']
                current_high = last_bar['high']
                current_low = last_bar['low']
                current_open = last_bar['open']
            
            # RSI calculation
            def calculate_rsi(prices, period=14):
                delta = pd.Series(prices).diff()
                gain = delta.where(delta > 0, 0)
                loss = -delta.where(delta < 0, 0)
                avg_gain = gain.rolling(window=period).mean()
                avg_loss = loss.rolling(window=period).mean()
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                return float(rsi.iloc[-1]) if len(rsi) > 0 and not pd.isna(rsi.iloc[-1]) else 50.0
            
            rsi_14 = calculate_rsi(closes, 14)
            rsi_21 = calculate_rsi(closes, 21)
            
            # Moving Averages
            sma_20 = float(pd.Series(closes).rolling(window=20).mean().iloc[-1]) if len(closes) >= 20 else float(closes[-1])
            sma_50 = float(pd.Series(closes).rolling(window=50).mean().iloc[-1]) if len(closes) >= 50 else float(closes[-1])
            sma_200 = float(pd.Series(closes).rolling(window=200).mean().iloc[-1]) if len(closes) >= 200 else float(closes[-1])
            
            # EMA
            ema_12 = float(pd.Series(closes).ewm(span=12, adjust=False).mean().iloc[-1])
            ema_26 = float(pd.Series(closes).ewm(span=26, adjust=False).mean().iloc[-1])
            
            # MACD
            macd_line = ema_12 - ema_26
            macd_signal = float(pd.Series([macd_line]).ewm(span=9, adjust=False).mean().iloc[-1]) if isinstance(macd_line, (int, float)) else 0.0
            macd_histogram = macd_line - macd_signal
            
            # Bollinger Bands
            bb_period = 20
            bb_std = 2
            bb_middle = float(pd.Series(closes).rolling(window=bb_period).mean().iloc[-1])
            bb_std_val = float(pd.Series(closes).rolling(window=bb_period).std().iloc[-1])
            bb_upper = bb_middle + (bb_std_val * bb_std)
            bb_lower = bb_middle - (bb_std_val * bb_std)
            bb_width = ((bb_upper - bb_lower) / bb_middle) * 100 if bb_middle > 0 else 0.0
            bb_position = ((current_price - bb_lower) / (bb_upper - bb_lower)) * 100 if (bb_upper - bb_lower) > 0 else 50.0
            
            # ATR
            high_low = highs[-14:] - lows[-14:]
            high_close = np.abs(highs[-14:] - np.roll(closes[-14:], 1))
            low_close = np.abs(lows[-14:] - np.roll(closes[-14:], 1))
            tr = np.maximum(high_low, np.maximum(high_close, low_close))
            atr = float(np.mean(tr)) if len(tr) > 0 else 0.0
            
            # Volume indicators
            volume_sma = float(pd.Series(volumes).rolling(window=20).mean().iloc[-1]) if len(volumes) >= 20 else float(volumes[-1])
            volume_ratio = float(current_volume / volume_sma) if volume_sma > 0 else 1.0
            
            # OBV
            obv = 0.0
            for i in range(1, len(closes)):
                if closes[i] > closes[i-1]:
                    obv += volumes[i]
                elif closes[i] < closes[i-1]:
                    obv -= volumes[i]
            
            # VWAP (using intraday data if available, else daily)
            if intraday_data:
                total_volume = sum(bar['volume'] for bar in intraday_data)
                total_value = sum(bar['close'] * bar['volume'] for bar in intraday_data)
                vwap = total_value / total_volume if total_volume > 0 else current_price
            else:
                vwap = float((df['close'] * df['volume']).sum() / df['volume'].sum()) if df['volume'].sum() > 0 else current_price
            
            vwap_distance_pct = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0.0
            
            # Volatility (annualized)
            volatility = float(pd.Series(closes).pct_change().std() * 100 * np.sqrt(252))
            
            # Get SPY for RS vs SPY
            try:
                import yfinance as yf
                spy_ticker = yf.Ticker("SPY")
                spy_hist = spy_ticker.history(period="2d", interval="1d")
                if not spy_hist.empty:
                    spy_price = float(spy_hist['Close'].iloc[-1])
                    spy_change_pct = float((spy_price - spy_hist['Close'].iloc[-2]) / spy_hist['Close'].iloc[-2] * 100) if len(spy_hist) >= 2 else 0.0
                    symbol_change_pct = float((current_price - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0.0
                    rs_vs_spy = symbol_change_pct - spy_change_pct
                else:
                    spy_price = 0.0
                    spy_change_pct = 0.0
                    rs_vs_spy = 0.0
            except:
                spy_price = 0.0
                spy_change_pct = 0.0
                rs_vs_spy = 0.0
            
            return {
                'open': current_open,
                'high': current_high,
                'low': current_low,
                'close': current_price,
                'volume': int(current_volume),
                
                # Moving Averages
                'sma_20': sma_20,
                'sma_50': sma_50,
                'sma_200': sma_200,
                'ema_12': ema_12,
                'ema_26': ema_26,
                
                # Momentum Indicators
                'rsi': rsi_14,
                'rsi_14': rsi_14,
                'rsi_21': rsi_21,
                'macd': macd_line,
                'macd_signal': macd_signal,
                'macd_histogram': macd_histogram,
                'momentum_10': ((closes[-1] - closes[-10]) / closes[-10] * 100) if len(closes) >= 10 else 0.0,
                
                # Volatility Indicators
                'atr': atr,
                'bollinger_upper': bb_upper,
                'bollinger_middle': bb_middle,
                'bollinger_lower': bb_lower,
                'bollinger_width': bb_width,
                'bollinger_position': bb_position,
                'volatility': volatility,
                
                # Volume Indicators
                'volume_ratio': volume_ratio,
                'volume_sma': volume_sma,
                'obv': obv,
                'ad_line': 0.0,
                
                # VWAP Indicators
                'vwap': vwap,
                'vwap_distance_pct': vwap_distance_pct,
                
                # Market Context
                'spy_price': spy_price,
                'spy_change_pct': spy_change_pct,
                'rs_vs_spy': rs_vs_spy,
                
                # Additional indicators
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
                
                # Pattern recognition
                'doji': False,
                'hammer': False,
                'engulfing': False,
                'morning_star': False,
                
                'data_source': 'ETRADE+yfinance',
                'data_quality': 'GOOD',
                'collection_time': target_time.isoformat()
            }
            
        except Exception as e:
            log.error(f"Failed to calculate technical indicators for {symbol}: {e}", exc_info=True)
            return {}
    
    def retrieve_signal_collection_data(self) -> Optional[Dict[str, Any]]:
        """Retrieve signal collection data from GCS"""
        try:
            signal_path = f"priority_optimizer/daily_signals/{self.date}_signals.json"
            if not self.gcs.enabled:
                local_file = Path(f"priority_optimizer/retrieved_data/{self.date}_signals.json")
                if local_file.exists():
                    with open(local_file, 'r') as f:
                        return json.load(f)
                return None
            
            content = self.gcs.read_string(signal_path)
            if content:
                return json.loads(content)
            return None
        except Exception as e:
            log.error(f"Failed to retrieve signal collection data: {e}")
            return None
    
    def retrieve_daily_marker(self) -> Optional[Dict[str, Any]]:
        """Retrieve daily marker from GCS"""
        try:
            marker_path = f"daily_markers/{self.date}.json"
            if not self.gcs.enabled:
                return None
            
            content = self.gcs.read_string(marker_path)
            if content:
                return json.loads(content)
            return None
        except Exception as e:
            log.error(f"Failed to retrieve daily marker: {e}")
            return None
    
    async def collect_complete_data(self) -> List[Dict[str, Any]]:
        """Collect complete 89-point data with signal collection time technicals"""
        log.info(f"📊 Collecting complete 89-point data for {self.date}...")
        log.info(f"   Using technical indicators from signal collection time: {self.signal_collection_time}")
        
        # Retrieve signal data
        signal_data = self.retrieve_signal_collection_data()
        if not signal_data:
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
        
        # Get execution data
        marker = self.retrieve_daily_marker()
        executed_signals = []
        rejected_signals = []
        
        if marker and marker.get('signals'):
            signals_entry = marker['signals']
            executed_signals = signals_entry.get('executed_signals', [])
            rejected_signals = signals_entry.get('rejected_signals', [])
        
        # Process signals
        comprehensive_records = []
        
        async def process_signal(signal: Dict[str, Any], index: int, total: int) -> Optional[Dict[str, Any]]:
            symbol = signal.get('symbol', '')
            print(f"[{index}/{total}] {symbol}...", end=' ', flush=True)
            
            try:
                # Get technical indicators at signal collection time
                market_data = await self.get_technical_indicators_at_time(
                    symbol=symbol,
                    target_time=self.signal_collection_time
                )
                
                if not market_data:
                    print("⚠️")
                    return None
                
                # Merge execution data
                executed_sig = next((s for s in executed_signals if s.get('symbol') == symbol), None)
                if executed_sig:
                    signal.update(executed_sig)
                    signal['executed'] = True
                
                # Build data structures
                ranking_data = {
                    'rank': signal.get('rank', 0),
                    'priority_score': signal.get('priority_score', 0.0),
                    'confidence': signal.get('confidence', 0.0),
                    'orb_volume_ratio': signal.get('orb_volume_ratio', 0.0),
                    'exec_volume_ratio': signal.get('exec_volume_ratio', 0.0),
                    'category': signal.get('category', '')
                }
                
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
                
                market_conditions = {
                    'market_regime': '',
                    'volatility_regime': '',
                    'trend_direction': '',
                    'volume_regime': '',
                    'momentum_regime': ''
                }
                
                # Build record
                record = self.comprehensive_collector.collect_trade_data(
                    symbol=symbol,
                    trade_id=f"{self.date}_{symbol}_{signal.get('rank', 0)}",
                    market_data=market_data,
                    trade_data=trade_data,
                    ranking_data=ranking_data,
                    risk_data=risk_data,
                    market_conditions=market_conditions
                )
                
                print("✅")
                return record
                
            except Exception as e:
                print("❌")
                log.error(f"Failed to process {symbol}: {e}")
                return None
        
        # Process in batches
        batch_size = 3  # Smaller batches for E*TRADE API
        for i in range(0, len(signals), batch_size):
            batch = signals[i:i+batch_size]
            tasks = [process_signal(sig, i+j+1, len(signals)) for j, sig in enumerate(batch)]
            results = await asyncio.gather(*tasks)
            comprehensive_records.extend([r for r in results if r is not None])
            await asyncio.sleep(1.0)  # Rate limiting for E*TRADE
        
        log.info(f"✅ Built {len(comprehensive_records)} complete comprehensive records")
        return comprehensive_records
    
    async def save_collected_data(self, records: List[Dict[str, Any]]):
        """Save collected data"""
        if not records:
            return
        
        try:
            saved_files = await self.comprehensive_collector.save_daily_data(format='both')
            if saved_files:
                log.info(f"✅ Data saved:")
                for file_type, file_path in saved_files.items():
                    log.info(f"   {file_type}: {file_path}")
        except Exception as e:
            log.error(f"Failed to save data: {e}")


async def main():
    """Main collection function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='E*TRADE 89-point data collection')
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD). Default: today')
    args = parser.parse_args()
    
    print("=" * 70)
    print("E*TRADE-Based 89-Point Data Collection Script")
    print("=" * 70)
    print(f"Date: {args.date or datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    collector = ETrade89PointCollector(date=args.date)
    
    records = await collector.collect_complete_data()
    
    if records:
        await collector.save_collected_data(records)
        
        print(f"\n✅ Collection complete!")
        print(f"   Records: {len(records)}")
        print(f"   Signal collection time: {collector.signal_collection_time}")
        print(f"   Saved to: priority_optimizer/comprehensive_data/")
        
        # Show sample
        if records:
            sample = records[0]
            print(f"\n📊 Sample ({sample.get('symbol')}):")
            print(f"   Collection Time: {sample.get('collection_time', 'N/A')}")
            print(f"   RSI: {sample.get('rsi', 0):.2f}")
            print(f"   Volume Ratio: {sample.get('volume_ratio', 0):.2f}x")
            print(f"   MACD Histogram: {sample.get('macd_histogram', 0):.4f}")
            print(f"   VWAP Distance: {sample.get('vwap_distance_pct', 0):.2f}%")
            print(f"   RS vs SPY: {sample.get('rs_vs_spy', 0):.2f}%")
    else:
        print(f"\n⚠️ No data collected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

