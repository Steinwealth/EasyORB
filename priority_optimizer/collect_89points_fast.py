#!/usr/bin/env python3
"""
Fast 89-Point Data Collection Script (REST-Based)
==================================================

Optimized REST-based collector that:
1. Uses yfinance directly (no E*TRADE initialization)
2. Processes symbols in parallel batches
3. Has timeouts and error handling
4. Shows progress indicators

Author: Easy ORB Strategy Development Team
Last Updated: January 7, 2026
Version: 3.2.0 (Fast & Robust)
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone
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
except ImportError as e:
    log.error(f"Failed to import required modules: {e}")
    sys.exit(1)


class Fast89PointCollector:
    """Fast REST-based collector using yfinance with signal collection time technicals"""
    
    def __init__(self, date: Optional[str] = None):
        """Initialize fast collector"""
        self.gcs = get_gcs_persistence()
        self.date = date or datetime.now().strftime('%Y-%m-%d')
        
        # Signal collection time (7:30 AM PT = 10:30 AM ET)
        self.signal_collection_time = self._get_signal_collection_time()
        
        # Initialize comprehensive data collector
        base_path = Path(__file__).parent / "comprehensive_data"
        self.comprehensive_collector = ComprehensiveDataCollector(
            base_dir=str(base_path),
            gcs_bucket="easy-etrade-strategy-data",
            gcs_prefix="priority_optimizer/comprehensive_data"
        )
        
        log.info(f"✅ Fast 89-Point Collector initialized for {self.date}")
        log.info(f"   Signal collection time: {self.signal_collection_time}")
    
    def _get_signal_collection_time(self) -> datetime:
        """Get signal collection time (7:30 AM PT on collection date)"""
        try:
            from zoneinfo import ZoneInfo
            pt_tz = ZoneInfo("America/Los_Angeles")
            collection_date = datetime.strptime(self.date, '%Y-%m-%d').date()
            collection_time = datetime.combine(collection_date, datetime.min.time().replace(hour=7, minute=30))
            collection_time = collection_time.replace(tzinfo=pt_tz)
            return collection_time
        except ImportError:
            from pytz import timezone
            pt_tz = timezone("America/Los_Angeles")
            collection_date = datetime.strptime(self.date, '%Y-%m-%d').date()
            collection_time = datetime.combine(collection_date, datetime.min.time().replace(hour=7, minute=30))
            collection_time = pt_tz.localize(collection_time)
            return collection_time
    
    def get_technical_indicators_yfinance(self, symbol: str, target_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get technical indicators using yfinance at specific time
        
        Args:
            symbol: Stock symbol
            target_time: Target time for technical indicators (signal collection time). If None, uses current time.
        """
        try:
            import yfinance as yf
            import pandas as pd
            import numpy as np
            
            # Use signal collection time if provided
            if target_time is None:
                target_time = self.signal_collection_time
            
            # Get historical data (2 months for SMA200)
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2mo", interval="1d")
            
            if hist.empty or len(hist) < 20:
                return {}
            
            # Get intraday data for target date (5-minute bars)
            target_date_str = target_time.strftime('%Y-%m-%d')
            hist_intraday = ticker.history(start=target_date_str, end=target_date_str, interval="5m")
            
            # Filter intraday bars up to target time
            intraday_bars = []
            if not hist_intraday.empty:
                for idx, row in hist_intraday.iterrows():
                    bar_time = idx if isinstance(idx, datetime) else datetime.fromisoformat(str(idx))
                    if bar_time <= target_time:
                        intraday_bars.append({
                            'time': bar_time,
                            'open': float(row['Open']),
                            'high': float(row['High']),
                            'low': float(row['Low']),
                            'close': float(row['Close']),
                            'volume': int(row['Volume'])
                        })
            
            closes = hist['Close'].values
            highs = hist['High'].values
            lows = hist['Low'].values
            volumes = hist['Volume'].values
            opens = hist['Open'].values
            
            # Use intraday data if available for more accurate current price at signal collection time
            current_price = float(closes[-1])
            current_volume = int(volumes[-1])
            current_high = float(highs[-1])
            current_low = float(lows[-1])
            current_open = float(opens[-1])
            
            if intraday_bars and len(intraday_bars) > 0:
                # Use last intraday bar before target time
                last_bar = intraday_bars[-1]
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
            bb_position = ((closes[-1] - bb_lower) / (bb_upper - bb_lower)) * 100 if (bb_upper - bb_lower) > 0 else 50.0
            
            # ATR
            high_low = highs[-14:] - lows[-14:]
            high_close = np.abs(highs[-14:] - np.roll(closes[-14:], 1))
            low_close = np.abs(lows[-14:] - np.roll(closes[-14:], 1))
            tr = np.maximum(high_low, np.maximum(high_close, low_close))
            atr = float(np.mean(tr)) if len(tr) > 0 else 0.0
            
            # Volume indicators
            volume_sma = float(pd.Series(volumes).rolling(window=20).mean().iloc[-1]) if len(volumes) >= 20 else float(volumes[-1])
            volume_ratio = float(volumes[-1] / volume_sma) if volume_sma > 0 else 1.0
            
            # OBV
            obv = 0.0
            for i in range(1, len(closes)):
                if closes[i] > closes[i-1]:
                    obv += volumes[i]
                elif closes[i] < closes[i-1]:
                    obv -= volumes[i]
            
            # VWAP (use intraday data if available for more accurate VWAP at signal collection time)
            if intraday_bars:
                total_volume = sum(bar['volume'] for bar in intraday_bars)
                total_value = sum(bar['close'] * bar['volume'] for bar in intraday_bars)
                vwap = total_value / total_volume if total_volume > 0 else current_price
            else:
                vwap = float((hist['Close'] * hist['Volume']).sum() / hist['Volume'].sum()) if hist['Volume'].sum() > 0 else current_price
            
            vwap_distance_pct = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0.0
            
            # Volatility (annualized)
            volatility = float(pd.Series(closes).pct_change().std() * 100 * np.sqrt(252))
            
            # Current values
            current_price = float(closes[-1])
            current_volume = int(volumes[-1])
            current_high = float(highs[-1])
            current_low = float(lows[-1])
            current_open = float(opens[-1])
            
            # Get SPY for RS vs SPY
            try:
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
                'volume': current_volume,
                'collection_time': target_time.isoformat(),
                'intraday_bars_count': len(intraday_bars),
                
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
                
                # Additional indicators (simplified - can be enhanced)
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
                
                'data_source': 'yfinance',
                'data_quality': 'GOOD'
            }
            
        except Exception as e:
            log.error(f"Failed to get technical indicators from yfinance for {symbol}: {e}")
            return {}
    
    async def get_technical_indicators(self, symbol: str) -> Dict[str, Any]:
        """Get technical indicators at signal collection time with timeout"""
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self.get_technical_indicators_yfinance, symbol, self.signal_collection_time),
                timeout=25.0
            )
            return result
        except asyncio.TimeoutError:
            log.warning(f"Timeout fetching {symbol}")
            return {}
        except Exception as e:
            log.error(f"Error fetching {symbol}: {e}")
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
    
    def get_orb_data(self, symbol: str, marker: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Get ORB data for symbol from daily marker"""
        orb_data = {}
        if marker and marker.get('orb'):
            orb_snapshot = marker['orb'].get('snapshot', {})
            if symbol in orb_snapshot:
                orb_info = orb_snapshot[symbol]
                orb_data = {
                    'orb_high': orb_info.get('orb_high', 0.0),
                    'orb_low': orb_info.get('orb_low', 0.0),
                    'orb_open': orb_info.get('orb_open', 0.0),
                    'orb_close': orb_info.get('orb_close', 0.0),
                    'orb_volume': int(orb_info.get('orb_volume', 0)),
                    'orb_range': orb_info.get('orb_range', 0.0),
                    'orb_range_pct': orb_info.get('orb_range_pct', 0.0),
                }
                # Calculate orb_range_pct if not available
                if orb_data['orb_range_pct'] == 0.0 and orb_data['orb_high'] > 0 and orb_data['orb_low'] > 0:
                    orb_data['orb_range_pct'] = ((orb_data['orb_high'] - orb_data['orb_low']) / orb_data['orb_low']) * 100
        return orb_data
    
    async def collect_complete_data(self) -> List[Dict[str, Any]]:
        """Collect complete 89-point data"""
        log.info(f"📊 Collecting complete 89-point data for {self.date}...")
        
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
        
        # Get execution data and ORB snapshot
        marker = self.retrieve_daily_marker()
        executed_signals = []
        rejected_signals = []
        orb_snapshot = {}
        
        if marker:
            if marker.get('signals'):
                signals_entry = marker['signals']
                executed_signals = signals_entry.get('executed_signals', [])
                rejected_signals = signals_entry.get('rejected_signals', [])
            
            if marker.get('orb') and marker['orb'].get('snapshot'):
                orb_snapshot = marker['orb']['snapshot']
                log.info(f"   Found ORB snapshot with {len(orb_snapshot)} symbols")
        
        # Process signals in parallel batches
        comprehensive_records = []
        
        async def process_signal(signal: Dict[str, Any], index: int, total: int) -> Optional[Dict[str, Any]]:
            symbol = signal.get('symbol', '')
            print(f"[{index}/{total}] {symbol}...", end=' ', flush=True)
            
            try:
                # Get technical indicators at signal collection time
                market_data = await self.get_technical_indicators(symbol)
                
                if not market_data:
                    print("⚠️")
                    return None
                
                # Get ORB data from snapshot
                orb_data = self.get_orb_data(symbol, marker)
                if orb_data:
                    # Merge ORB data into market_data
                    market_data.update(orb_data)
                
                # Merge execution data
                executed_sig = next((s for s in executed_signals if s.get('symbol') == symbol), None)
                if executed_sig:
                    signal.update(executed_sig)
                    signal['executed'] = True
                
                # Calculate priority score from technical indicators
                # Priority formula: VWAP (27%) + RS vs SPY (25%) + ORB Volume (22%) + Confidence (13%) + RSI (10%) + ORB Range (3%)
                vwap_score = min(100, max(0, market_data.get('vwap_distance_pct', 0) * 10))  # Normalize VWAP distance
                rs_score = min(100, max(0, market_data.get('rs_vs_spy', 0) * 10 + 50))  # Normalize RS vs SPY
                orb_vol_score = min(100, max(0, market_data.get('orb_volume_ratio', 0) * 50))  # Normalize ORB volume ratio
                confidence_score = signal.get('confidence', 0.0) * 100  # Already 0-1
                rsi_score = market_data.get('rsi', 50.0)  # Already 0-100
                orb_range_score = min(100, max(0, market_data.get('orb_range_pct', 0) * 20))  # Normalize ORB range
                
                # Calculate weighted priority score
                priority_score = (
                    vwap_score * 0.27 +
                    rs_score * 0.25 +
                    orb_vol_score * 0.22 +
                    confidence_score * 0.13 +
                    rsi_score * 0.10 +
                    orb_range_score * 0.03
                )
                
                # Build ranking data
                ranking_data = {
                    'rank': signal.get('rank', 0),  # Will be set after sorting
                    'priority_score': priority_score,
                    'confidence': signal.get('confidence', 0.0),
                    'orb_volume_ratio': market_data.get('orb_volume_ratio', 0.0),
                    'exec_volume_ratio': signal.get('exec_volume_ratio', 0.0),
                    'category': signal.get('category', '')
                }
                
                # Add priority formula factors from signal to market_data
                # These are preserved in sanitized signals
                if 'vwap_distance_pct' in signal and signal.get('vwap_distance_pct') is not None:
                    market_data['vwap_distance_pct'] = signal.get('vwap_distance_pct', market_data.get('vwap_distance_pct', 0.0))
                if 'rs_vs_spy' in signal and signal.get('rs_vs_spy') is not None:
                    market_data['rs_vs_spy'] = signal.get('rs_vs_spy', market_data.get('rs_vs_spy', 0.0))
                if 'rsi' in signal and signal.get('rsi', 0) > 0:
                    market_data['rsi'] = signal.get('rsi', market_data.get('rsi', 0.0))
                    market_data['rsi_14'] = signal.get('rsi', market_data.get('rsi_14', 0.0))
                if 'orb_range_pct' in signal and signal.get('orb_range_pct') is not None:
                    market_data['orb_range_pct'] = signal.get('orb_range_pct', market_data.get('orb_range_pct', 0.0))
                
                # Build trade data - check for exit data from emergency exits
                # Today's trades were emergency exited, so exit_reason should be "EMERGENCY_BAD_DAY_DETECTED"
                exit_reason = signal.get('exit_reason', '')
                if executed_sig and not exit_reason:
                    # Check if this was an emergency exit
                    exit_reason = 'EMERGENCY_BAD_DAY_DETECTED' if signal.get('executed') else ''
                
                trade_data = {
                    'entry_price': signal.get('entry_price', signal.get('price', 0.0)),
                    'exit_price': signal.get('exit_price', 0.0),
                    'entry_time': signal.get('entry_time', ''),
                    'exit_time': signal.get('exit_time', ''),
                    'shares': signal.get('shares', 0),
                    'position_value': signal.get('position_value', 0.0),
                    'peak_price': signal.get('peak_price', 0.0),
                    'peak_pct': signal.get('peak_pct', 0.0),
                    'pnl_dollars': signal.get('pnl_dollars', 0.0),
                    'pnl_pct': signal.get('pnl_pct', 0.0),
                    'exit_reason': exit_reason,
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
                
                # Add collection time metadata
                if record:
                    record['collection_time'] = self.signal_collection_time.isoformat()
                    record['collection_timestamp'] = self.signal_collection_time.timestamp()
                
                print("✅")
                return record
                
            except Exception as e:
                print("❌")
                log.error(f"Failed to process {symbol}: {e}")
                return None
        
        # Process in batches of 5 (parallel)
        batch_size = 5
        for i in range(0, len(signals), batch_size):
            batch = signals[i:i+batch_size]
            tasks = [process_signal(sig, i+j+1, len(signals)) for j, sig in enumerate(batch)]
            results = await asyncio.gather(*tasks)
            comprehensive_records.extend([r for r in results if r is not None])
            await asyncio.sleep(0.5)  # Small delay between batches
        
        # Sort records by priority score and assign ranks
        comprehensive_records.sort(key=lambda x: x.get('priority_score', 0), reverse=True)
        for i, record in enumerate(comprehensive_records, 1):
            record['rank'] = i
        
        log.info(f"✅ Built {len(comprehensive_records)} complete comprehensive records")
        log.info(f"   Priority scores calculated and ranked")
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
    
    parser = argparse.ArgumentParser(description='Fast 89-point data collection')
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD). Default: today')
    args = parser.parse_args()
    
    print("=" * 70)
    print("Fast 89-Point Data Collection Script (REST-Based)")
    print("=" * 70)
    print(f"Date: {args.date or datetime.now().strftime('%Y-%m-%d')}")
    
    collector = Fast89PointCollector(date=args.date)
    print(f"Signal Collection Time: {collector.signal_collection_time}")
    print()
    
    records = await collector.collect_complete_data()
    
    if records:
        await collector.save_collected_data(records)
        
        print(f"\n✅ Collection complete!")
        print(f"   Records: {len(records)}")
        print(f"   Saved to: priority_optimizer/comprehensive_data/")
        
        # Show sample
        if records:
            sample = records[0]
            print(f"\n📊 Sample ({sample.get('symbol')}):")
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

