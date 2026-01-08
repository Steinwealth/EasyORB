#!/usr/bin/env python3
"""
REST-Based 89-Point Data Collection Script
==========================================

Collects comprehensive 89 data points from GCS and daily markers WITHOUT requiring
E*TRADE initialization. This is a pure REST-based collector that retrieves data
from already-stored sources.

**Data Sources:**
1. Signal Collection Data: GCS `priority_optimizer/daily_signals/YYYY-MM-DD_signals.json`
2. Daily Markers: GCS `daily_markers/YYYY-MM-DD.json` (contains full signal data with technical indicators)
3. Trade Execution Data: From daily markers `signals.executed_signals` and `signals.rejected_signals`
4. Exit Monitoring Data: From trade manager/position tracking (if available)

**Collection Phases:**
- Signal Collection (7:15-7:30 AM PT): All signals with technical indicators
- Entry Execution (7:30 AM PT): Executed trades with entry data
- Exit Monitoring (throughout day): Exit data, peak capture, P&L

Author: Easy ORB Strategy Development Team
Last Updated: January 7, 2026
Version: 3.0.0 (REST-based)
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
    from modules.gcs_persistence import get_gcs_persistence
    from modules.comprehensive_data_collector import ComprehensiveDataCollector
except ImportError as e:
    log.error(f"Failed to import required modules: {e}")
    sys.exit(1)


class REST89PointCollector:
    """REST-based collector for 89 data points from GCS/daily markers"""
    
    def __init__(self, date: Optional[str] = None):
        """
        Initialize REST-based collector
        
        Args:
            date: Date to collect (YYYY-MM-DD format). Default: today
        """
        self.gcs = get_gcs_persistence()
        self.date = date or datetime.now().strftime('%Y-%m-%d')
        
        # Initialize comprehensive data collector
        # Use absolute path to avoid nested directories
        base_path = Path(__file__).parent / "comprehensive_data"
        self.comprehensive_collector = ComprehensiveDataCollector(
            base_dir=str(base_path),
            gcs_bucket="easy-etrade-strategy-data",
            gcs_prefix="priority_optimizer/comprehensive_data"
        )
        
        log.info(f"✅ REST-based 89-Point Collector initialized for {self.date}")
    
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
        """Retrieve full daily marker from GCS (contains complete signal data)"""
        try:
            marker_path = f"daily_markers/{self.date}.json"
            
            if not self.gcs.enabled:
                log.warning("GCS not enabled, checking local file...")
                local_file = Path(f"/tmp/easy_etrade_markers/{self.date}.json")
                if local_file.exists():
                    with open(local_file, 'r') as f:
                        return json.load(f)
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
    
    def build_89point_record(
        self,
        signal: Dict[str, Any],
        market_data: Optional[Dict[str, Any]] = None,
        trade_data: Optional[Dict[str, Any]] = None,
        ranking_data: Optional[Dict[str, Any]] = None,
        risk_data: Optional[Dict[str, Any]] = None,
        market_conditions: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build comprehensive 89-point record from available data
        
        Args:
            signal: Signal data from collection
            market_data: Market data with technical indicators (from daily marker or signal)
            trade_data: Trade execution data (entry, exit, P&L)
            ranking_data: Ranking and priority data
            risk_data: Risk management data
            market_conditions: Market regime and conditions
        """
        # Extract market data from signal if not provided
        if not market_data:
            market_data = signal.get('raw_signal', signal)
        
        # Extract ranking data from signal
        if not ranking_data:
            ranking_data = {
                'rank': signal.get('rank', 0),
                'priority_score': signal.get('priority_score', 0.0),
                'confidence': signal.get('confidence', 0.0),
                'orb_volume_ratio': signal.get('orb_volume_ratio', 0.0),
                'exec_volume_ratio': signal.get('exec_volume_ratio', 0.0),
                'category': signal.get('category', '')
            }
        
        # Extract trade data from signal
        if not trade_data:
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
        
        # Default risk data
        if not risk_data:
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
        
        # Default market conditions
        if not market_conditions:
            market_conditions = {
                'market_regime': market_data.get('market_regime', ''),
                'volatility_regime': market_data.get('volatility_regime', ''),
                'trend_direction': market_data.get('trend_direction', ''),
                'volume_regime': market_data.get('volume_regime', ''),
                'momentum_regime': market_data.get('momentum_regime', '')
            }
        
        # Build comprehensive record using ComprehensiveDataCollector format
        comprehensive_record = {
            # Timestamp
            'timestamp': signal.get('collection_time', datetime.now(datetime.timezone.utc).isoformat()),
            'date': self.date,
            
            # Trade identification
            'symbol': signal.get('symbol', ''),
            'trade_id': f"{self.date}_{signal.get('symbol', 'UNKNOWN')}_{signal.get('rank', 0)}",
            
            # 1. Price Data (5)
            'open': market_data.get('open', market_data.get('open_price', 0.0)),
            'high': market_data.get('high', market_data.get('high_today', 0.0)),
            'low': market_data.get('low', market_data.get('low_today', 0.0)),
            'close': market_data.get('close', market_data.get('current_price', signal.get('price', 0.0))),
            'volume': market_data.get('volume', market_data.get('volume_today', 0)),
            
            # 2. Moving Averages (5)
            'sma_20': market_data.get('sma_20', 0.0),
            'sma_50': market_data.get('sma_50', 0.0),
            'sma_200': market_data.get('sma_200', 0.0),
            'ema_12': market_data.get('ema_12', 0.0),
            'ema_26': market_data.get('ema_26', 0.0),
            
            # 3. Momentum Indicators (7)
            'rsi': market_data.get('rsi', signal.get('rsi', 0.0)),
            'rsi_14': market_data.get('rsi_14', market_data.get('rsi', signal.get('rsi', 0.0))),
            'rsi_21': market_data.get('rsi_21', 0.0),
            'macd': market_data.get('macd', 0.0),
            'macd_signal': market_data.get('macd_signal', 0.0),
            'macd_histogram': market_data.get('macd_histogram', 0.0),
            'momentum_10': market_data.get('momentum_10', market_data.get('momentum', 0.0)),
            
            # 4. Volatility Indicators (7)
            'atr': market_data.get('atr', 0.0),
            'bollinger_upper': market_data.get('bollinger_upper', 0.0),
            'bollinger_middle': market_data.get('bollinger_middle', 0.0),
            'bollinger_lower': market_data.get('bollinger_lower', 0.0),
            'bollinger_width': market_data.get('bollinger_width', 0.0),
            'bollinger_position': market_data.get('bollinger_position', 0.0),
            'volatility': market_data.get('volatility', market_data.get('current_volatility', 0.0)),
            
            # 5. Volume Indicators (4)
            'volume_ratio': market_data.get('volume_ratio', signal.get('volume_ratio', 0.0)),
            'volume_sma': market_data.get('volume_sma', 0.0),
            'obv': market_data.get('obv', 0.0),
            'ad_line': market_data.get('ad_line', 0.0),
            
            # 6. Pattern Recognition (4)
            'doji': market_data.get('doji', False),
            'hammer': market_data.get('hammer', False),
            'engulfing': market_data.get('engulfing', False),
            'morning_star': market_data.get('morning_star', False),
            
            # 7. VWAP Indicators (2)
            'vwap': market_data.get('vwap', 0.0),
            'vwap_distance_pct': market_data.get('vwap_distance_pct', 0.0),
            
            # 8. Relative Strength (1)
            'rs_vs_spy': market_data.get('rs_vs_spy', 0.0),
            
            # 9. ORB Data (6)
            'orb_high': market_data.get('orb_high', signal.get('orb_high', 0.0)),
            'orb_low': market_data.get('orb_low', signal.get('orb_low', 0.0)),
            'orb_open': market_data.get('orb_open', 0.0),
            'orb_close': market_data.get('orb_close', 0.0),
            'orb_volume': market_data.get('orb_volume', 0),
            'orb_range_pct': market_data.get('orb_range_pct', signal.get('orb_range_pct', 0.0)),
            
            # 10. Market Context (2)
            'spy_price': market_data.get('spy_price', 0.0),
            'spy_change_pct': market_data.get('spy_change_pct', 0.0),
            
            # 11. Trade Data (15)
            'entry_price': trade_data.get('entry_price', 0.0),
            'exit_price': trade_data.get('exit_price', 0.0),
            'entry_time': trade_data.get('entry_time', ''),
            'exit_time': trade_data.get('exit_time', ''),
            'shares': trade_data.get('shares', 0),
            'position_value': trade_data.get('position_value', 0.0),
            'peak_price': trade_data.get('peak_price', 0.0),
            'peak_pct': trade_data.get('peak_pct', 0.0),
            'pnl_dollars': trade_data.get('pnl_dollars', 0.0),
            'pnl_pct': trade_data.get('pnl_pct', 0.0),
            'exit_reason': trade_data.get('exit_reason', ''),
            'win': trade_data.get('win', False),
            'holding_minutes': trade_data.get('holding_minutes', 0.0),
            'entry_bar_volatility': trade_data.get('entry_bar_volatility', 0.0),
            'time_weighted_peak': trade_data.get('time_weighted_peak', 0.0),
            
            # 12. Ranking Data (6)
            'rank': ranking_data.get('rank', 0),
            'priority_score': ranking_data.get('priority_score', 0.0),
            'confidence': ranking_data.get('confidence', 0.0),
            'orb_volume_ratio': ranking_data.get('orb_volume_ratio', 0.0),
            'exec_volume_ratio': ranking_data.get('exec_volume_ratio', 0.0),
            'category': ranking_data.get('category', ''),
            
            # 13. Risk Management (8)
            'current_stop_loss': risk_data.get('current_stop_loss', 0.0),
            'stop_loss_distance_pct': risk_data.get('stop_loss_distance_pct', 0.0),
            'opening_bar_protection_active': risk_data.get('opening_bar_protection_active', False),
            'trailing_activated': risk_data.get('trailing_activated', False),
            'trailing_distance_pct': risk_data.get('trailing_distance_pct', 0.0),
            'breakeven_activated': risk_data.get('breakeven_activated', False),
            'gap_risk_pct': risk_data.get('gap_risk_pct', 0.0),
            'max_adverse_excursion': risk_data.get('max_adverse_excursion', 0.0),
            
            # 14. Market Conditions (5)
            'market_regime': market_conditions.get('market_regime', ''),
            'volatility_regime': market_conditions.get('volatility_regime', ''),
            'trend_direction': market_conditions.get('trend_direction', ''),
            'volume_regime': market_conditions.get('volume_regime', ''),
            'momentum_regime': market_conditions.get('momentum_regime', ''),
            
            # 15. Additional Indicators (16)
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
    
    async def collect_all_data(self) -> List[Dict[str, Any]]:
        """Collect all 89-point data from available sources"""
        log.info(f"📊 Collecting 89-point data for {self.date}...")
        
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
        
        # Retrieve daily marker for additional data
        marker = self.retrieve_daily_marker()
        executed_signals = []
        rejected_signals = []
        
        if marker and marker.get('signals'):
            signals_entry = marker['signals']
            executed_signals = signals_entry.get('executed_signals', [])
            rejected_signals = signals_entry.get('rejected_signals', [])
            log.info(f"   Found {len(executed_signals)} executed, {len(rejected_signals)} rejected")
        
        # Build comprehensive records
        comprehensive_records = []
        
        for signal in signals:
            try:
                # Check if this signal was executed or rejected
                symbol = signal.get('symbol', '')
                executed_sig = next((s for s in executed_signals if s.get('symbol') == symbol), None)
                rejected_sig = next((s for s in rejected_signals if s.get('symbol') == symbol), None)
                
                # Merge execution/rejection data if available
                if executed_sig:
                    signal.update(executed_sig)
                    signal['executed'] = True
                elif rejected_sig:
                    signal.update(rejected_sig)
                    signal['executed'] = False
                    signal['filtered'] = True
                
                # Build 89-point record
                record = self.build_89point_record(signal)
                comprehensive_records.append(record)
                
            except Exception as e:
                log.error(f"Failed to process signal {signal.get('symbol', 'UNKNOWN')}: {e}", exc_info=True)
        
        log.info(f"✅ Built {len(comprehensive_records)} comprehensive records")
        return comprehensive_records
    
    async def save_collected_data(self, records: List[Dict[str, Any]]):
        """Save collected data using ComprehensiveDataCollector"""
        if not records:
            log.warning("No records to save")
            return
        
        # Add records to comprehensive collector
        self.comprehensive_collector.comprehensive_data = records
        
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
    
    parser = argparse.ArgumentParser(description='Collect 89-point data from GCS/daily markers')
    parser.add_argument('--date', type=str, help='Date to collect (YYYY-MM-DD). Default: today')
    args = parser.parse_args()
    
    print("=" * 70)
    print("REST-Based 89-Point Data Collection Script")
    print("=" * 70)
    print(f"Date: {args.date or datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    collector = REST89PointCollector(date=args.date)
    
    # Collect all data
    records = await collector.collect_all_data()
    
    if records:
        # Save data
        await collector.save_collected_data(records)
        
        print(f"\n✅ Collection complete!")
        print(f"   Records collected: {len(records)}")
        print(f"   Data saved to: priority_optimizer/comprehensive_data/")
        print(f"   GCS location: priority_optimizer/comprehensive_data/{collector.date}_comprehensive_data.json")
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

