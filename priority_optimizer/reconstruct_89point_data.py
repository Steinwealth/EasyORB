#!/usr/bin/env python3
"""
89-Point Data Reconstruction Script
====================================

Reconstructs 89-point comprehensive data from recovered trade history and signals.
This attempts to fill in missing technical indicators where possible.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from modules.comprehensive_data_collector import ComprehensiveDataCollector
except ImportError:
    print("⚠️ Cannot import ComprehensiveDataCollector")
    ComprehensiveDataCollector = None


class DataReconstructor:
    """Reconstruct 89-point data from available sources"""
    
    def __init__(self, recovered_data_dir: Path):
        self.recovered_data_dir = recovered_data_dir
        self.comprehensive_collector = None
        
        if ComprehensiveDataCollector:
            self.comprehensive_collector = ComprehensiveDataCollector(
                base_dir=str(recovered_data_dir / "comprehensive_data_reconstructed")
            )
    
    def load_trade_history(self) -> Optional[Dict]:
        """Load trade history from recovered data"""
        trade_history_dir = self.recovered_data_dir / "trade_history"
        if not trade_history_dir.exists():
            return None
        
        # Find trade history file
        for file_path in trade_history_dir.glob("*.json"):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    if 'closed_trades' in data:
                        return data
            except Exception as e:
                print(f"⚠️ Error loading {file_path}: {e}")
        
        return None
    
    def load_signals_for_date(self, date: str) -> Optional[Dict]:
        """Load signals for a specific date"""
        signals_dir = self.recovered_data_dir / "daily_signals"
        signal_file = signals_dir / f"{date}_signals.json"
        
        if signal_file.exists():
            try:
                with open(signal_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Error loading signals for {date}: {e}")
        
        return None
    
    def reconstruct_trade_data(
        self,
        trade: Dict[str, Any],
        signal_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Reconstruct 89-point data from trade and signal data
        
        Note: This is a partial reconstruction. Full 89 points require
        real-time market data collection during trade execution.
        """
        symbol = trade.get('symbol', '')
        trade_id = trade.get('trade_id', '')
        
        # Find matching signal if available
        signal = None
        if signal_data and 'signals' in signal_data:
            for s in signal_data['signals']:
                if s.get('symbol') == symbol:
                    signal = s
                    break
        
        # Build market data (partial - missing real-time indicators)
        market_data = {
            'open': trade.get('entry_price', 0.0),
            'high': trade.get('max_favorable', trade.get('entry_price', 0.0)),
            'low': trade.get('entry_price', 0.0),  # Simplified
            'close': trade.get('exit_price', trade.get('entry_price', 0.0)),
            'volume': 0,  # Not available in trade history
            'current_price': trade.get('exit_price', trade.get('entry_price', 0.0)),
        }
        
        # Add signal data if available
        if signal:
            market_data.update({
                'confidence': signal.get('confidence', 0.0),
                'price': signal.get('price', trade.get('entry_price', 0.0)),
            })
        
        # Build trade data
        trade_data = {
            'entry_price': trade.get('entry_price', 0.0),
            'exit_price': trade.get('exit_price', 0.0),
            'entry_time': trade.get('timestamp', ''),
            'exit_time': trade.get('exit_timestamp', ''),
            'shares': trade.get('quantity', 0),
            'position_value': trade.get('position_value', 0.0),
            'peak_price': trade.get('max_favorable', trade.get('entry_price', 0.0)),
            'peak_pct': ((trade.get('max_favorable', trade.get('entry_price', 0.0)) - trade.get('entry_price', 0.0)) / trade.get('entry_price', 1.0)) * 100 if trade.get('entry_price', 0) > 0 else 0.0,
            'pnl_dollars': trade.get('pnl', 0.0),
            'pnl_pct': (trade.get('pnl', 0.0) / trade.get('position_value', 1.0)) * 100 if trade.get('position_value', 0) > 0 else 0.0,
            'exit_reason': trade.get('exit_reason', ''),
            'win': trade.get('pnl', 0.0) > 0,
            'holding_minutes': 0.0,  # Calculate if timestamps available
            'entry_bar_volatility': 0.0,  # Not available
        }
        
        # Calculate holding time if timestamps available
        if trade.get('timestamp') and trade.get('exit_timestamp'):
            try:
                entry_time = datetime.fromisoformat(trade['timestamp'].replace('Z', '+00:00'))
                exit_time = datetime.fromisoformat(trade['exit_timestamp'].replace('Z', '+00:00'))
                delta = exit_time - entry_time
                trade_data['holding_minutes'] = delta.total_seconds() / 60.0
            except:
                pass
        
        # Build ranking data
        ranking_data = {
            'rank': 0,  # Not available in trade history
            'priority_score': signal.get('confidence', 0.0) if signal else 0.0,
            'confidence': signal.get('confidence', 0.0) if signal else 0.0,
            'orb_volume_ratio': 0.0,  # Not available
            'exec_volume_ratio': 0.0,  # Not available
            'category': signal.get('signal_type', '') if signal else '',
        }
        
        # Build risk data
        risk_data = {
            'current_stop_loss': trade.get('stop_loss', 0.0),
            'stop_loss_distance_pct': 0.0,  # Calculate if possible
            'opening_bar_protection_active': False,  # Not available
            'trailing_activated': bool(trade.get('trailing_stop')),
            'trailing_distance_pct': 0.0,  # Not available
            'breakeven_activated': False,  # Not available
            'gap_risk_pct': 0.0,  # Not available
            'max_adverse_excursion': 0.0,  # Not available
        }
        
        # Build market conditions (minimal - not available in history)
        market_conditions = {
            'market_regime': '',
            'volatility_regime': '',
            'trend_direction': '',
            'volume_regime': '',
            'momentum_regime': '',
        }
        
        # Use comprehensive collector if available
        if self.comprehensive_collector:
            try:
                comprehensive_record = self.comprehensive_collector.collect_trade_data(
                    symbol=symbol,
                    trade_id=trade_id,
                    market_data=market_data,
                    trade_data=trade_data,
                    ranking_data=ranking_data,
                    risk_data=risk_data,
                    market_conditions=market_conditions
                )
                return comprehensive_record
            except Exception as e:
                print(f"⚠️ Error collecting comprehensive data for {symbol}: {e}")
        
        # Fallback: return partial data
        return {
            'symbol': symbol,
            'trade_id': trade_id,
            'date': trade.get('timestamp', '').split('T')[0] if trade.get('timestamp') else '',
            'reconstructed': True,
            'partial_data': True,
            'market_data': market_data,
            'trade_data': trade_data,
            'ranking_data': ranking_data,
            'risk_data': risk_data,
            'market_conditions': market_conditions,
        }
    
    def reconstruct_all_trades(self) -> List[Dict[str, Any]]:
        """Reconstruct data for all recovered trades"""
        print("\n🔧 Reconstructing 89-point data...")
        
        trade_history = self.load_trade_history()
        if not trade_history:
            print("❌ No trade history found")
            return []
        
        closed_trades = trade_history.get('closed_trades', [])
        print(f"📊 Found {len(closed_trades)} trades to reconstruct")
        
        reconstructed = []
        for i, trade in enumerate(closed_trades, 1):
            symbol = trade.get('symbol', '')
            trade_id = trade.get('trade_id', '')
            
            # Get date from timestamp
            date = ''
            if trade.get('timestamp'):
                try:
                    date = trade['timestamp'].split('T')[0]
                except:
                    pass
            
            # Load signals for this date
            signal_data = None
            if date:
                signal_data = self.load_signals_for_date(date)
            
            print(f"  [{i}/{len(closed_trades)}] Reconstructing {symbol} ({trade_id})...")
            
            reconstructed_record = self.reconstruct_trade_data(trade, signal_data)
            reconstructed.append(reconstructed_record)
        
        print(f"\n✅ Reconstructed {len(reconstructed)} trade records")
        return reconstructed
    
    def save_reconstructed_data(self, reconstructed: List[Dict[str, Any]]):
        """Save reconstructed data"""
        output_dir = self.recovered_data_dir / "comprehensive_data_reconstructed"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Group by date
        by_date = {}
        for record in reconstructed:
            date = record.get('date', 'unknown')
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(record)
        
        # Save each date
        for date, records in by_date.items():
            output_file = output_dir / f"{date}_reconstructed.json"
            data = {
                'date': date,
                'reconstructed': True,
                'total_records': len(records),
                'data_points_per_record': 89,
                'records': records
            }
            
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            
            print(f"✅ Saved {len(records)} records for {date} to {output_file}")
        
        # Also save to comprehensive collector if available
        if self.comprehensive_collector:
            self.comprehensive_collector.comprehensive_data = reconstructed
            try:
                import asyncio
                asyncio.run(self.comprehensive_collector.save_daily_data(format='both'))
                print("✅ Saved to comprehensive collector format")
            except Exception as e:
                print(f"⚠️ Error saving to comprehensive collector: {e}")


def main():
    """Main reconstruction function"""
    print("=" * 70)
    print("89-Point Data Reconstruction Script")
    print("=" * 70)
    
    recovered_data_dir = Path(__file__).parent / "recovered_data"
    
    if not recovered_data_dir.exists():
        print(f"\n❌ Recovered data directory not found: {recovered_data_dir}")
        print("   Please run recover_gcs_data.py first")
        return
    
    reconstructor = DataReconstructor(recovered_data_dir)
    reconstructed = reconstructor.reconstruct_all_trades()
    
    if reconstructed:
        reconstructor.save_reconstructed_data(reconstructed)
        print(f"\n✅ Reconstruction complete!")
        print(f"   Records: {len(reconstructed)}")
        print(f"   Output: {recovered_data_dir / 'comprehensive_data_reconstructed'}")
    else:
        print("\n⚠️ No data reconstructed")


if __name__ == "__main__":
    main()

