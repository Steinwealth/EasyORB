#!/usr/bin/env python3
"""
Priority Optimizer Data Collector
==================================

Automatically collects and saves ALL signal data (executed + filtered)
for Priority Optimizer analysis.

Captures:
- Complete signal list (all signals generated)
- Technical indicators (RSI, ORB Volume, volatility, VWAP, RS vs SPY, etc.)
- Execution results (executed vs filtered)
- Trade performance (entry, peak, exit, P&L)
- Ranking data (rank, score, filtering reason)

This enables tracking hypothetical results for filtered signals
and comprehensive analysis of ranking formula effectiveness.

Multi-Factor Ranking Data (Rev 00108):
- VWAP Distance (27% weight)
- RS vs SPY (25% weight)
- ORB Volume (22% weight)
- Confidence (13% weight)
- RSI (10% weight)
- ORB Range (3% weight)

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
import json
import csv
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import asyncio

log = logging.getLogger(__name__)

class PriorityDataCollector:
    """
    Collects comprehensive signal data for Priority Optimizer analysis
    """
    
    def __init__(self, base_dir: str = "priority_optimizer/daily_data"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Storage for today's signals
        self.all_signals_collected = []  # All signals from collection phase
        self.executed_signals = []  # Signals that were executed
        self.filtered_signals = []  # Signals that were filtered out
        self.signal_tracking = {}  # Track performance for each signal
        
        self.today_date = datetime.now().strftime('%Y-%m-%d')
        
        log.info(f"✅ Priority Data Collector initialized (data dir: {self.base_dir})")
    
    def record_signal_collection(self, signals: List[Dict[str, Any]], 
                                 collection_time: Optional[str] = None):
        """
        Record ALL signals collected during signal generation phase
        
        Args:
            signals: Complete list of signals generated (before filtering)
            collection_time: Time of collection (default: now)
        """
        try:
            if not collection_time:
                collection_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            log.info(f"📊 Recording {len(signals)} signals collected at {collection_time}")
            
            # Store all signals
            for sig in signals:
                signal_data = {
                    # Basic identification
                    'date': self.today_date,
                    'collection_time': collection_time,
                    'symbol': sig.get('symbol'),
                    
                    # Ranking data
                    'rank': sig.get('rank', 0),
                    'priority_score': sig.get('priority_score', 0),
                    
                    # Technical indicators
                    'confidence': sig.get('confidence', 0),
                    'orb_range_pct': sig.get('orb_range_pct', 0),
                    'orb_volume_ratio': sig.get('orb_volume_ratio', 0),
                    'exec_volume_ratio': sig.get('exec_volume_ratio', 0),
                    'rsi': sig.get('rsi', 0),
                    'leverage': sig.get('leverage', ''),
                    'category': sig.get('category', ''),
                    
                    # Price data
                    'price': sig.get('price', sig.get('current_price', 0)),
                    'orb_high': sig.get('orb_high', 0),
                    'orb_low': sig.get('orb_low', 0),
                    
                    # Execution status (will be updated later)
                    'executed': False,
                    'filtered': False,
                    'filter_reason': '',
                    
                    # Performance data (will be filled in after EOD)
                    'entry_price': 0,
                    'shares': 0,
                    'position_value': 0,
                    'peak_price': 0,
                    'peak_pct': 0,
                    'exit_price': 0,
                    'pnl_dollars': 0,
                    'pnl_pct': 0,
                    'exit_reason': '',
                    'win': False,
                    
                    # Complete signal data for reference
                    'raw_signal': sig
                }
                
                self.all_signals_collected.append(signal_data)
                self.signal_tracking[sig.get('symbol')] = signal_data
            
            log.info(f"✅ Recorded {len(self.all_signals_collected)} signals for Priority Optimizer")
            
        except Exception as e:
            log.error(f"Failed to record signal collection: {e}", exc_info=True)
    
    def record_execution_results(self, executed: List[Dict[str, Any]], 
                                filtered: List[Dict[str, Any]]):
        """
        Record which signals were executed vs filtered
        
        Args:
            executed: List of signals that were executed
            filtered: List of signals that were filtered out
        """
        try:
            log.info(f"📊 Recording execution results: {len(executed)} executed, {len(filtered)} filtered")
            
            # Mark executed signals
            for sig in executed:
                symbol = sig.get('symbol')
                if symbol in self.signal_tracking:
                    self.signal_tracking[symbol]['executed'] = True
                    self.signal_tracking[symbol]['entry_price'] = sig.get('price', sig.get('current_price', 0))
                    self.signal_tracking[symbol]['shares'] = sig.get('quantity', 0)
                    self.signal_tracking[symbol]['position_value'] = sig.get('position_value', 0)
                    
                    self.executed_signals.append(self.signal_tracking[symbol])
                    
                    log.debug(f"  ✅ {symbol}: Executed with {sig.get('quantity', 0)} shares")
            
            # Mark filtered signals
            for sig in filtered:
                symbol = sig.get('symbol')
                reason = sig.get('filter_reason', 'Filtered by adaptive algorithm')
                
                if symbol in self.signal_tracking:
                    self.signal_tracking[symbol]['filtered'] = True
                    self.signal_tracking[symbol]['filter_reason'] = reason
                    
                    self.filtered_signals.append(self.signal_tracking[symbol])
                    
                    log.debug(f"  ⚠️ {symbol}: Filtered - {reason}")
            
            log.info(f"✅ Execution results recorded - {len(self.executed_signals)} executed, {len(self.filtered_signals)} filtered")
            
        except Exception as e:
            log.error(f"Failed to record execution results: {e}", exc_info=True)
    
    def record_trade_performance(self, symbol: str, peak_price: float = 0, 
                                exit_price: float = 0, pnl_dollars: float = 0, 
                                pnl_pct: float = 0, exit_reason: str = '', 
                                exit_time: Optional[str] = None):
        """
        Record trade performance data for executed signals
        
        Args:
            symbol: Symbol ticker
            peak_price: Highest price reached
            exit_price: Exit price
            pnl_dollars: P&L in dollars
            pnl_pct: P&L in percentage
            exit_reason: Reason for exit
            exit_time: Time of exit
        """
        try:
            if symbol in self.signal_tracking:
                sig = self.signal_tracking[symbol]
                
                # Update performance data
                sig['peak_price'] = peak_price
                sig['peak_pct'] = pnl_pct if peak_price == 0 else ((peak_price - sig['entry_price']) / sig['entry_price']) * 100
                sig['exit_price'] = exit_price
                sig['pnl_dollars'] = pnl_dollars
                sig['pnl_pct'] = pnl_pct
                sig['exit_reason'] = exit_reason
                sig['exit_time'] = exit_time or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                sig['win'] = pnl_dollars > 0
                
                log.debug(f"  📊 {symbol}: P&L {pnl_pct:+.2f}% - {exit_reason}")
        
        except Exception as e:
            log.error(f"Failed to record performance for {symbol}: {e}", exc_info=True)
    
    async def save_daily_data(self, format: str = 'both'):
        """
        Save all collected data to file(s)
        
        Args:
            format: 'json', 'csv', or 'both' (default)
        """
        try:
            # Create filename (YYYY-MM-DD format)
            filename_base = self.base_dir / f"{self.today_date}_DATA"
            
            # Save JSON (complete data with all fields)
            if format in ['json', 'both']:
                json_file = filename_base.with_suffix('.json')
                
                data = {
                    'date': self.today_date,
                    'total_signals': len(self.all_signals_collected),
                    'executed_count': len(self.executed_signals),
                    'filtered_count': len(self.filtered_signals),
                    'all_signals': self.all_signals_collected,
                    'executed_signals': self.executed_signals,
                    'filtered_signals': self.filtered_signals
                }
                
                with open(json_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                
                log.info(f"✅ Saved JSON data: {json_file}")
            
            # Save CSV (Priority Optimizer format)
            if format in ['csv', 'both']:
                csv_file = filename_base.with_suffix('.csv')
                
                # CSV Headers (all signals, executed and filtered)
                headers = [
                    'Date', 'Symbol', 'Rank', 'Priority_Score', 'Executed', 'Filtered', 'Filter_Reason',
                    'Confidence', 'ORB_Range_Pct', 'ORB_Volume_Ratio', 'Exec_Volume_Ratio',
                    'RSI', 'Leverage', 'Category',
                    'Price', 'ORB_High', 'ORB_Low',
                    'Entry_Price', 'Shares', 'Position_Value',
                    'Peak_Price', 'Peak_Pct', 'Exit_Price', 'PnL_Dollars', 'PnL_Pct',
                    'Exit_Reason', 'Exit_Time', 'Win'
                ]
                
                with open(csv_file, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
                    writer.writeheader()
                    
                    # Write all signals (both executed and filtered)
                    for sig in sorted(self.all_signals_collected, key=lambda x: x.get('rank', 999)):
                        # Prepare row data
                        row = {
                            'Date': sig.get('date'),
                            'Symbol': sig.get('symbol'),
                            'Rank': sig.get('rank'),
                            'Priority_Score': f"{sig.get('priority_score', 0):.4f}",
                            'Executed': 'YES' if sig.get('executed') else 'NO',
                            'Filtered': 'YES' if sig.get('filtered') else 'NO',
                            'Filter_Reason': sig.get('filter_reason', ''),
                            'Confidence': f"{sig.get('confidence', 0):.4f}",
                            'ORB_Range_Pct': f"{sig.get('orb_range_pct', 0):.4f}",
                            'ORB_Volume_Ratio': f"{sig.get('orb_volume_ratio', 0):.4f}",
                            'Exec_Volume_Ratio': f"{sig.get('exec_volume_ratio', 0):.4f}",
                            'RSI': f"{sig.get('rsi', 0):.2f}",
                            'Leverage': sig.get('leverage', ''),
                            'Category': sig.get('category', ''),
                            'Price': f"{sig.get('price', 0):.2f}",
                            'ORB_High': f"{sig.get('orb_high', 0):.2f}",
                            'ORB_Low': f"{sig.get('orb_low', 0):.2f}",
                            'Entry_Price': f"{sig.get('entry_price', 0):.2f}",
                            'Shares': sig.get('shares', 0),
                            'Position_Value': f"{sig.get('position_value', 0):.2f}",
                            'Peak_Price': f"{sig.get('peak_price', 0):.2f}",
                            'Peak_Pct': f"{sig.get('peak_pct', 0):.2f}",
                            'Exit_Price': f"{sig.get('exit_price', 0):.2f}",
                            'PnL_Dollars': f"{sig.get('pnl_dollars', 0):.2f}",
                            'PnL_Pct': f"{sig.get('pnl_pct', 0):.2f}",
                            'Exit_Reason': sig.get('exit_reason', ''),
                            'Exit_Time': sig.get('exit_time', ''),
                            'Win': 'TRUE' if sig.get('win') else 'FALSE'
                        }
                        
                        writer.writerow(row)
                
                log.info(f"✅ Saved CSV data: {csv_file}")
                log.info(f"   • Total signals: {len(self.all_signals_collected)}")
                log.info(f"   • Executed: {len(self.executed_signals)}")
                log.info(f"   • Filtered: {len(self.filtered_signals)}")
            
            # Save summary
            summary_file = filename_base.with_suffix('.txt')
            with open(summary_file, 'w') as f:
                f.write(f"Priority Optimizer Data Summary\n")
                f.write(f"=" * 80 + "\n\n")
                f.write(f"Date: {self.today_date}\n")
                f.write(f"Total Signals Collected: {len(self.all_signals_collected)}\n")
                f.write(f"Signals Executed: {len(self.executed_signals)}\n")
                f.write(f"Signals Filtered: {len(self.filtered_signals)}\n\n")
                
                f.write(f"Executed Signals:\n")
                for sig in sorted(self.executed_signals, key=lambda x: x.get('rank', 999)):
                    f.write(f"  #{sig.get('rank')}: {sig.get('symbol')} @ ${sig.get('entry_price', 0):.2f} "
                           f"(Score: {sig.get('priority_score', 0):.3f}, ORB Vol: {sig.get('orb_volume_ratio', 0):.2f}x)\n")
                
                f.write(f"\nFiltered Signals:\n")
                for sig in sorted(self.filtered_signals, key=lambda x: x.get('rank', 999)):
                    f.write(f"  #{sig.get('rank')}: {sig.get('symbol')} @ ${sig.get('price', 0):.2f} "
                           f"(Score: {sig.get('priority_score', 0):.3f}) - {sig.get('filter_reason')}\n")
            
            log.info(f"✅ Saved summary: {summary_file}")
            
            return {
                'json_file': str(json_file) if format in ['json', 'both'] else None,
                'csv_file': str(csv_file) if format in ['csv', 'both'] else None,
                'summary_file': str(summary_file),
                'signals_saved': len(self.all_signals_collected)
            }
            
        except Exception as e:
            log.error(f"Failed to save daily data: {e}", exc_info=True)
            return None
    
    def get_signal_summary(self) -> Dict[str, Any]:
        """Get summary of collected data"""
        return {
            'total_signals': len(self.all_signals_collected),
            'executed': len(self.executed_signals),
            'filtered': len(self.filtered_signals),
            'executed_symbols': [s['symbol'] for s in self.executed_signals],
            'filtered_symbols': [s['symbol'] for s in self.filtered_signals]
        }
    
    def reset_daily_data(self):
        """Reset for new trading day"""
        self.all_signals_collected = []
        self.executed_signals = []
        self.filtered_signals = []
        self.signal_tracking = {}
        self.today_date = datetime.now().strftime('%Y-%m-%d')
        log.info("🔄 Priority Data Collector reset for new day")


# Singleton instance
_priority_data_collector = None

def get_priority_data_collector(base_dir: str = "priority_optimizer/daily_data") -> PriorityDataCollector:
    """Get or create Priority Data Collector singleton"""
    global _priority_data_collector
    if _priority_data_collector is None:
        _priority_data_collector = PriorityDataCollector(base_dir)
    return _priority_data_collector

