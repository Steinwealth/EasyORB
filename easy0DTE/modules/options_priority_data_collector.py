#!/usr/bin/env python3
"""
Options Priority Optimizer Data Collector
==========================================

Automatically collects and saves ALL options trade data (executed + filtered)
for Priority Optimizer analysis and strategy optimization.

Captures:
- Complete signal list (all signals generated)
- Entry execution data (strikes, delta, spread width, entry price)
- Exit execution data (exit reason, exit price, holding time)
- Trade performance (entry, peak, exit, P&L, max profit, max loss)
- Market conditions (volatility, VWAP, ORB data)
- Position type (debit spread, credit spread, lotto)
- Exit triggers (hard stop, time stop, profit target, etc.)

This enables tracking trade results and optimizing:
- Entry signals (eligibility filter, spread type selection)
- Exit signals (hard stops, time stops, profit targets)
- Position sizing and risk management
- Strategy parameters for maximum profitable trades

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import asyncio

# Try to import GCS storage (optional)
try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    logging.warning("Google Cloud Storage not available - will use local storage")

log = logging.getLogger(__name__)


class OptionsPriorityDataCollector:
    """
    Collects comprehensive options trade data for Priority Optimizer analysis
    """
    
    def __init__(
        self,
        base_dir: str = "priority_optimizer/0dte_data",
        gcs_bucket: Optional[str] = None,
        gcs_prefix: str = "priority_optimizer/0dte_signals"
    ):
        """
        Initialize Options Priority Data Collector
        
        Args:
            base_dir: Local directory for data storage
            gcs_bucket: GCS bucket name (optional, for cloud storage)
            gcs_prefix: GCS prefix path for data files
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        self.gcs_bucket_name = gcs_bucket
        self.gcs_prefix = gcs_prefix
        self.gcs_client = None
        
        if GCS_AVAILABLE and gcs_bucket:
            try:
                self.gcs_client = storage.Client()
                self.gcs_bucket = self.gcs_client.bucket(gcs_bucket)
                log.info(f"✅ GCS storage enabled: {gcs_bucket}/{gcs_prefix}")
            except Exception as e:
                log.warning(f"Failed to initialize GCS client: {e}")
                self.gcs_bucket = None
        
        # Storage for today's signals and trades
        self.all_signals_collected = []  # All signals from collection phase
        self.executed_trades = []  # Trades that were executed
        self.filtered_signals = []  # Signals that were filtered out
        self.trade_tracking = {}  # Track performance for each trade
        
        self.today_date = datetime.now().strftime('%Y-%m-%d')
        
        log.info(f"✅ Options Priority Data Collector initialized (data dir: {self.base_dir})")
    
    def record_signal_collection(
        self,
        signals: List[Dict[str, Any]],
        collection_time: Optional[str] = None
    ):
        """
        Record ALL signals collected during signal generation phase
        
        Args:
            signals: Complete list of DTE0Signal objects (before filtering)
            collection_time: Time of collection (default: now)
        """
        try:
            if not collection_time:
                collection_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            log.info(f"📊 Recording {len(signals)} options signals collected at {collection_time}")
            
            # Store all signals
            for signal in signals:
                # Extract signal data
                if hasattr(signal, 'to_dict'):
                    signal_dict = signal.to_dict()
                elif isinstance(signal, dict):
                    signal_dict = signal
                else:
                    signal_dict = {
                        'symbol': getattr(signal, 'symbol', 'UNKNOWN'),
                        'direction': getattr(signal, 'direction', 'UNKNOWN'),
                        'spread_type': getattr(signal, 'spread_type', 'auto'),
                        'target_delta': getattr(signal, 'target_delta', 0.0),
                        'spread_width': getattr(signal, 'spread_width', 0.0),
                    }
                
                symbol = signal_dict.get('symbol', 'UNKNOWN')
                eligibility_result = signal_dict.get('eligibility_result', {})
                orb_signal = signal_dict.get('orb_signal', {})
                
                signal_data = {
                    # Basic identification
                    'date': self.today_date,
                    'collection_time': collection_time,
                    'symbol': symbol,
                    'direction': signal_dict.get('direction', 'UNKNOWN'),
                    'spread_type': signal_dict.get('spread_type', 'auto'),
                    
                    # Eligibility filter data
                    'eligibility_score': eligibility_result.get('score', 0.0) if isinstance(eligibility_result, dict) else getattr(eligibility_result, 'score', 0.0),
                    'eligibility_passed': eligibility_result.get('passed', False) if isinstance(eligibility_result, dict) else getattr(eligibility_result, 'passed', False),
                    'volatility_score': eligibility_result.get('volatility_score', 0.0) if isinstance(eligibility_result, dict) else getattr(eligibility_result, 'volatility_score', 0.0),
                    'orb_range_pct': eligibility_result.get('orb_range_pct', 0.0) if isinstance(eligibility_result, dict) else getattr(eligibility_result, 'orb_range_pct', 0.0),
                    'momentum_confirmed': eligibility_result.get('momentum_confirmed', False) if isinstance(eligibility_result, dict) else getattr(eligibility_result, 'momentum_confirmed', False),
                    'trend_day_confirmed': eligibility_result.get('trend_day_confirmed', False) if isinstance(eligibility_result, dict) else getattr(eligibility_result, 'trend_day_confirmed', False),
                    
                    # ORB signal data
                    'orb_high': orb_signal.get('orb_high', 0.0),
                    'orb_low': orb_signal.get('orb_low', 0.0),
                    'orb_range': orb_signal.get('orb_range', 0.0),
                    'orb_breakout_price': orb_signal.get('breakout_price', 0.0),
                    'orb_breakout_time': orb_signal.get('breakout_time', ''),
                    
                    # Options parameters
                    'target_delta': signal_dict.get('target_delta', 0.0),
                    'spread_width': signal_dict.get('spread_width', 0.0),
                    
                    # Priority ranking data (Rev 00225: Priority Ranking System)
                    'priority_score': signal_dict.get('priority_score', 0.0),
                    'priority_rank': signal_dict.get('priority_rank', 0),
                    'capital_allocated': signal_dict.get('capital_allocated', 0.0),
                    
                    # Priority factor values (for analysis)
                    'orb_breakout_pct': orb_breakout_pct,
                    'volume_ratio': orb_signal.get('volume_ratio', 1.0),
                    'directional_momentum': directional_momentum,
                    
                    # Execution status (will be updated later)
                    'executed': False,
                    'filtered': False,
                    'filter_reason': '',
                    
                    # Entry execution data (will be filled in when executed)
                    'entry_time': '',
                    'entry_price': 0.0,
                    'position_type': '',  # 'debit_spread', 'credit_spread', or 'lotto'
                    'long_strike': 0.0,
                    'short_strike': 0.0,
                    'strike_selected': '',
                    'delta_selected': 0.0,
                    'spread_width_actual': 0.0,
                    'quantity': 0,
                    'max_profit': 0.0,
                    'max_loss': 0.0,
                    'break_even': 0.0,
                    
                    # Exit execution data (will be filled in when closed)
                    'exit_time': '',
                    'exit_price': 0.0,
                    'exit_reason': '',
                    'holding_time_minutes': 0,
                    'peak_value': 0.0,
                    'peak_pnl_pct': 0.0,
                    'realized_pnl': 0.0,
                    'realized_pnl_pct': 0.0,
                    'unrealized_pnl': 0.0,
                    'win': False,
                    
                    # Market conditions at entry
                    'entry_underlying_price': 0.0,
                    'entry_vwap': 0.0,
                    'entry_volatility': 0.0,
                    'entry_iv': 0.0,
                    
                    # Market conditions at exit
                    'exit_underlying_price': 0.0,
                    'exit_vwap': 0.0,
                    
                    # Complete signal data for reference
                    'raw_signal': signal_dict
                }
                
                self.all_signals_collected.append(signal_data)
                self.trade_tracking[symbol] = signal_data
            
            log.info(f"✅ Recorded {len(self.all_signals_collected)} options signals for Priority Optimizer")
            
        except Exception as e:
            log.error(f"Failed to record signal collection: {e}", exc_info=True)
    
    def record_execution_results(
        self,
        executed_positions: List[Any],
        filtered_signals: List[Any] = None
    ):
        """
        Record which signals were executed vs filtered
        
        Args:
            executed_positions: List of OptionsPosition objects that were executed
            filtered_signals: List of signals that were filtered out (optional)
        """
        try:
            log.info(f"📊 Recording execution results: {len(executed_positions)} executed, {len(filtered_signals or [])} filtered")
            
            # Mark executed trades
            for position in executed_positions:
                symbol = position.symbol
                
                # Get position details
                if position.debit_spread:
                    spread = position.debit_spread
                    position_type = 'debit_spread'
                    long_strike = spread.long_strike
                    short_strike = spread.short_strike
                    max_profit = spread.max_profit
                    max_loss = spread.max_loss
                    break_even = spread.break_even
                    delta_selected = getattr(spread.long_contract, 'delta', 0.0)
                    spread_width_actual = abs(long_strike - short_strike)
                elif position.credit_spread:
                    spread = position.credit_spread
                    position_type = 'credit_spread'
                    long_strike = spread.long_strike
                    short_strike = spread.short_strike
                    max_profit = spread.max_profit
                    max_loss = spread.max_loss
                    break_even = spread.break_even
                    delta_selected = getattr(spread.short_contract, 'delta', 0.0)
                    spread_width_actual = abs(short_strike - long_strike)
                else:  # lotto
                    contract = position.lotto_contract
                    position_type = 'lotto'
                    long_strike = contract.strike
                    short_strike = 0.0
                    max_profit = 0.0  # Unlimited for lottos
                    max_loss = position.entry_price
                    break_even = contract.strike
                    delta_selected = getattr(contract, 'delta', 0.0)
                    spread_width_actual = 0.0
                
                if symbol in self.trade_tracking:
                    trade = self.trade_tracking[symbol]
                    trade['executed'] = True
                    trade['entry_time'] = position.entry_time.isoformat() if hasattr(position.entry_time, 'isoformat') else str(position.entry_time)
                    trade['entry_price'] = position.entry_price
                    trade['position_type'] = position_type
                    trade['long_strike'] = long_strike
                    trade['short_strike'] = short_strike
                    trade['strike_selected'] = f"{short_strike}/{long_strike}" if short_strike > 0 else f"{long_strike}"
                    trade['delta_selected'] = delta_selected
                    trade['spread_width_actual'] = spread_width_actual
                    trade['quantity'] = position.quantity
                    trade['max_profit'] = max_profit
                    trade['max_loss'] = max_loss
                    trade['break_even'] = break_even
                    
                    # Update capital allocated if available from position or calculate from entry
                    if hasattr(position, 'capital_allocated'):
                        trade['capital_allocated'] = position.capital_allocated
                    elif 'capital_allocated' not in trade or trade.get('capital_allocated', 0.0) == 0.0:
                        # Calculate from entry price if not set
                        trade['capital_allocated'] = position.entry_price * position.quantity * 100
                    
                    self.executed_trades.append(trade)
                    
                    log.debug(f"  ✅ {symbol}: Executed {position_type} - Entry: ${position.entry_price:.2f}")
            
            # Mark filtered signals
            if filtered_signals:
                for signal in filtered_signals:
                    symbol = getattr(signal, 'symbol', signal.get('symbol', 'UNKNOWN')) if not isinstance(signal, dict) else signal.get('symbol', 'UNKNOWN')
                    reason = getattr(signal, 'filter_reason', 'Filtered by eligibility filter') if not isinstance(signal, dict) else signal.get('filter_reason', 'Filtered by eligibility filter')
                    
                    if symbol in self.trade_tracking:
                        trade = self.trade_tracking[symbol]
                        trade['filtered'] = True
                        trade['filter_reason'] = reason
                        
                        self.filtered_signals.append(trade)
                        
                        log.debug(f"  ⚠️ {symbol}: Filtered - {reason}")
            
            log.info(f"✅ Execution results recorded - {len(self.executed_trades)} executed, {len(self.filtered_signals)} filtered")
            
        except Exception as e:
            log.error(f"Failed to record execution results: {e}", exc_info=True)
    
    def record_trade_performance(
        self,
        position: Any,
        exit_signal: Optional[Any] = None,
        peak_value: float = 0.0,
        peak_pnl_pct: float = 0.0
    ):
        """
        Record trade performance data for executed positions
        
        Args:
            position: OptionsPosition object
            exit_signal: ExitSignal object (if position was closed)
            peak_value: Highest value reached during trade
            peak_pnl_pct: Highest P&L percentage reached
        """
        try:
            symbol = position.symbol
            
            if symbol not in self.trade_tracking:
                # Create new trade entry if not found
                log.warning(f"Trade {symbol} not found in tracking - creating new entry")
                self.trade_tracking[symbol] = {
                    'date': self.today_date,
                    'symbol': symbol,
                    'executed': True,
                    'entry_time': position.entry_time.isoformat() if hasattr(position.entry_time, 'isoformat') else str(position.entry_time),
                    'entry_price': position.entry_price,
                    'position_type': position.position_type,
                }
            
            trade = self.trade_tracking[symbol]
            
            # Update performance data
            trade['peak_value'] = max(trade.get('peak_value', 0.0), peak_value, position.current_value)
            trade['peak_pnl_pct'] = max(trade.get('peak_pnl_pct', 0.0), peak_pnl_pct)
            trade['realized_pnl'] = position.realized_pnl
            trade['unrealized_pnl'] = position.unrealized_pnl
            
            # Calculate realized P&L percentage
            if position.entry_price > 0:
                if position.position_type == 'credit_spread':
                    # For credit spreads: profit = (entry_price - exit_price) / entry_price
                    trade['realized_pnl_pct'] = (position.realized_pnl / (position.entry_price * position.quantity * 100)) * 100 if position.quantity > 0 else 0.0
                else:
                    # For debit spreads and lottos: profit = (exit_price - entry_price) / entry_price
                    trade['realized_pnl_pct'] = (position.realized_pnl / (position.entry_price * position.quantity * 100)) * 100 if position.quantity > 0 else 0.0
            
            # Update exit data if position was closed
            if exit_signal:
                trade['exit_time'] = exit_signal.exit_time.isoformat() if hasattr(exit_signal.exit_time, 'isoformat') else str(exit_signal.exit_time)
                trade['exit_price'] = exit_signal.exit_price
                trade['exit_reason'] = exit_signal.reason.value if hasattr(exit_signal.reason, 'value') else str(exit_signal.reason)
                
                # Calculate holding time
                entry_time = datetime.fromisoformat(trade['entry_time']) if isinstance(trade['entry_time'], str) else trade['entry_time']
                exit_time = exit_signal.exit_time
                holding_time = exit_time - entry_time
                trade['holding_time_minutes'] = int(holding_time.total_seconds() / 60)
                
                trade['win'] = exit_signal.pnl_dollar > 0 if hasattr(exit_signal, 'pnl_dollar') else trade['realized_pnl'] > 0
            
            log.debug(f"  📊 {symbol}: P&L {trade.get('realized_pnl_pct', 0.0):+.2f}% - {trade.get('exit_reason', 'Open')}")
        
        except Exception as e:
            log.error(f"Failed to record performance for {symbol}: {e}", exc_info=True)
    
    async def save_daily_data(self, format: str = 'json'):
        """
        Save all collected data for today
        
        Args:
            format: Output format ('json', 'csv', or 'both')
        """
        try:
            filename_base = f"{self.today_date}_0dte_signals"
            
            # Prepare data
            data = {
                'date': self.today_date,
                'collection_time': datetime.now().isoformat(),
                'signals_collected': len(self.all_signals_collected),
                'trades_executed': len(self.executed_trades),
                'signals_filtered': len(self.filtered_signals),
                'all_signals': self.all_signals_collected,
                'executed_trades': self.executed_trades,
                'filtered_signals': self.filtered_signals
            }
            
            # Save JSON
            if format in ['json', 'both']:
                json_file = self.base_dir / f"{filename_base}.json"
                with open(json_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                log.info(f"✅ Saved daily data to {json_file}")
                
                # Upload to GCS if available
                if self.gcs_bucket:
                    try:
                        blob_name = f"{self.gcs_prefix}/daily_signals/{filename_base}.json"
                        blob = self.gcs_bucket.blob(blob_name)
                        blob.upload_from_filename(str(json_file))
                        log.info(f"✅ Uploaded to GCS: {blob_name}")
                    except Exception as e:
                        log.warning(f"Failed to upload to GCS: {e}")
            
            # Save CSV export
            if format in ['csv', 'both']:
                csv_file = self.base_dir / f"{filename_base}.csv"
                try:
                    import csv
                    
                    # Write CSV with all trade data
                    with open(csv_file, 'w', newline='') as f:
                        writer = csv.writer(f)
                        
                        # Write header row
                        header = [
                            'Date', 'Symbol', 'Direction', 'Position Type', 'Spread Type',
                            'Priority Rank', 'Priority Score', 'Capital Allocated',
                            'Entry Time', 'Entry Price', 'Quantity',
                            'Long Strike', 'Short Strike', 'Target Delta', 'Spread Width',
                            'Exit Time', 'Exit Price', 'Exit Reason', 'Holding Time (min)',
                            'Realized P&L ($)', 'Realized P&L (%)', 'Peak P&L (%)',
                            'Eligibility Score', 'Volatility Score', 'ORB Range (%)',
                            'ORB Breakout %', 'Volume Ratio', 'Directional Momentum',
                            'Win', 'Status'
                        ]
                        writer.writerow(header)
                        
                        # Write executed trades
                        for trade in self.executed_trades:
                            row = [
                                trade.get('date', self.today_date),
                                trade.get('symbol', ''),
                                trade.get('direction', ''),
                                trade.get('position_type', ''),
                                trade.get('spread_type', ''),
                                trade.get('priority_rank', 0),
                                trade.get('priority_score', 0.0),
                                trade.get('capital_allocated', 0.0),
                                trade.get('entry_time', ''),
                                trade.get('entry_price', 0.0),
                                trade.get('quantity', 0),
                                trade.get('long_strike', ''),
                                trade.get('short_strike', ''),
                                trade.get('target_delta', 0.0),
                                trade.get('spread_width', 0.0),
                                trade.get('exit_time', ''),
                                trade.get('exit_price', ''),
                                trade.get('exit_reason', ''),
                                trade.get('holding_time_minutes', ''),
                                trade.get('realized_pnl', 0.0),
                                trade.get('realized_pnl_pct', 0.0),
                                trade.get('peak_pnl_pct', 0.0),
                                trade.get('eligibility_score', 0.0),
                                trade.get('volatility_score', 0.0),
                                trade.get('orb_range_pct', 0.0),
                                trade.get('orb_breakout_pct', 0.0),
                                trade.get('volume_ratio', 1.0),
                                trade.get('directional_momentum', 0.0),
                                trade.get('win', False),
                                trade.get('status', 'closed')
                            ]
                            writer.writerow(row)
                        
                        # Write filtered signals (signals that didn't execute)
                        for signal in self.filtered_signals:
                            row = [
                                signal.get('date', self.today_date),
                                signal.get('symbol', ''),
                                signal.get('direction', ''),
                                '',  # Position Type (N/A for filtered)
                                signal.get('spread_type', ''),
                                '',  # Entry Time (N/A)
                                '',  # Entry Price (N/A)
                                '',  # Quantity (N/A)
                                '',  # Long Strike (N/A)
                                '',  # Short Strike (N/A)
                                signal.get('target_delta', 0.0),
                                signal.get('spread_width', 0.0),
                                '',  # Exit Time (N/A)
                                '',  # Exit Price (N/A)
                                signal.get('filter_reason', 'FILTERED'),
                                '',  # Holding Time (N/A)
                                '',  # Realized P&L (N/A)
                                '',  # Realized P&L % (N/A)
                                '',  # Peak P&L % (N/A)
                                signal.get('eligibility_score', 0.0),
                                signal.get('volatility_score', 0.0),
                                signal.get('orb_range_pct', 0.0),
                                '',  # Win (N/A)
                                'filtered'
                            ]
                            writer.writerow(row)
                    
                    log.info(f"✅ Saved CSV data to {csv_file} ({len(self.executed_trades)} trades, {len(self.filtered_signals)} filtered)")
                    
                    # Upload to GCS if available
                    if self.gcs_bucket:
                        try:
                            blob_name = f"{self.gcs_prefix}/daily_signals/{filename_base}.csv"
                            blob = self.gcs_bucket.blob(blob_name)
                            blob.upload_from_filename(str(csv_file))
                            log.info(f"✅ Uploaded CSV to GCS: {blob_name}")
                        except Exception as e:
                            log.warning(f"Failed to upload CSV to GCS: {e}")
                            
                except ImportError:
                    log.warning("CSV module not available - CSV export skipped")
                except Exception as e:
                    log.error(f"Failed to save CSV data: {e}", exc_info=True)
            
            return data
        
        except Exception as e:
            log.error(f"Failed to save daily data: {e}", exc_info=True)
            return None
    
    def get_trade_history(self) -> Dict[str, Any]:
        """
        Get complete trade history for analysis
        
        Returns:
            Dictionary with all trade data
        """
        return {
            'date': self.today_date,
            'signals_collected': len(self.all_signals_collected),
            'trades_executed': len(self.executed_trades),
            'signals_filtered': len(self.filtered_signals),
            'all_signals': self.all_signals_collected,
            'executed_trades': self.executed_trades,
            'filtered_signals': self.filtered_signals,
            'trade_tracking': self.trade_tracking
        }

