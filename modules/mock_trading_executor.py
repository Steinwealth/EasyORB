"""
Mock Trading Executor for Demo Mode
===================================

Handles mock trade execution, P&L tracking, and performance simulation
for the Easy ORB Strategy Demo Mode.

Features:
- Mock trade execution with realistic P&L tracking
- GCS persistence for trade history (survives Cloud Run redeployments)
- Daily and weekly statistics tracking
- Compound engine integration for capital growth
- Batch position closing with aggregated alerts

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json
import os
from dataclasses import dataclass, asdict

from .prime_models import SignalQuality, SignalSide, TradeStatus
from .prime_alert_manager import PrimeAlertManager
from .prime_compound_engine import PrimeCompoundEngine

log = logging.getLogger(__name__)

@dataclass
class MockTrade:
    """Mock trade data structure"""
    trade_id: str
    symbol: str
    side: SignalSide
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    signal_quality: SignalQuality
    confidence: float
    timestamp: datetime
    status: TradeStatus = TradeStatus.OPEN
    current_price: float = 0.0
    pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trailing_stop: float = 0.0
    max_favorable: float = 0.0
    exit_price: float = 0.0
    exit_timestamp: Optional[datetime] = None
    exit_reason: str = ""
    position_value: float = 0.0  # FIX: Added for stealth trailing integration (Oct 24, 2025)

@dataclass
class MockPosition:
    """Mock position data structure"""
    symbol: str
    quantity: float
    average_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    stop_loss: float
    take_profit: float
    trailing_stop: float
    max_favorable: float

class MockTradingExecutor:
    """
    Mock trading executor for Demo Mode
    Simulates trade execution, P&L tracking, and stealth trailing stops
    """
    
    def __init__(self, alert_manager: Optional[PrimeAlertManager] = None, compound_engine: Optional[PrimeCompoundEngine] = None):
        self.alert_manager = alert_manager
        self.compound_engine = compound_engine  # Rev 00179: Compound engine for capital tracking
        self.active_trades: Dict[str, MockTrade] = {}
        self.closed_trades: List[MockTrade] = []
        self.positions: Dict[str, MockPosition] = {}
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.mock_data_file = "data/mock_trading_history.json"
        
        # Demo account balance (starts at $1,000, grows with profits)
        self.account_balance = 1000.0
        # Rev 00153: Track starting balance separately for accurate % calculations
        self.starting_balance = 1000.0
        
        # Daily stats tracking (like Live Mode) - tracks only TODAY's performance
        self.daily_stats = {
            'positions_opened': 0,
            'positions_closed': 0,
            'total_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
            'best_trade': 0.0,
            'worst_trade': 0.0
        }
        self.current_trading_date = datetime.utcnow().date()  # Rev 00074: UTC consistency
        
        # Weekly stats tracking (Monday-Friday) - resets on Monday
        self.weekly_stats = {
            'positions_opened': 0,
            'positions_closed': 0,
            'total_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
            'best_trade': 0.0,
            'worst_trade': 0.0,
            'week_start_date': self._get_week_start_date()
        }
        self._check_and_reset_weekly_stats()
        
        # Load existing mock trading data
        self._load_mock_data()
        
    def _load_mock_data(self):
        """Load existing mock trading data from GCS (primary) or local file (fallback)"""
        data = None
        loaded_from = None
        
        # Rev 00177: Try GCS first (persists across Cloud Run redeployments)
        try:
            from .gcs_persistence import get_gcs_persistence
            gcs = get_gcs_persistence()
            gcs_path = "demo_account/mock_trading_history.json"
            
            # Try to read from GCS directly
            if gcs.enabled:
                json_content = gcs.read_string(gcs_path)
                if json_content:
                    data = json.loads(json_content)
                    loaded_from = "GCS"
                    log.info(f"✅ Loaded mock trading data from GCS: {gcs_path}")
        except Exception as gcs_error:
            log.debug(f"GCS load failed (will try local): {gcs_error}")
        
        # Fallback to local file if GCS not available or failed
        if data is None:
            try:
                if os.path.exists(self.mock_data_file):
                    with open(self.mock_data_file, 'r') as f:
                        data = json.load(f)
                    loaded_from = "local file"
                    log.info(f"✅ Loaded mock trading data from local file: {self.mock_data_file}")
            except Exception as local_error:
                log.debug(f"Local file load failed: {local_error}")
        
        # Process loaded data
        if data:
            try:
                self.total_pnl = data.get('total_pnl', 0.0)
                self.total_trades = data.get('total_trades', 0)
                self.winning_trades = data.get('winning_trades', 0)
                self.losing_trades = data.get('losing_trades', 0)
                
                # Rev 00153: Load account balance and starting balance (persist across deployments)
                if 'account_balance' in data:
                    self.account_balance = data.get('account_balance', 1000.0)
                if 'starting_balance' in data:
                    self.starting_balance = data.get('starting_balance', 1000.0)
                
                # Rev 00177: Load weekly_stats if persisted
                if 'weekly_stats' in data:
                    saved_week_start = data['weekly_stats'].get('week_start_date')
                    if saved_week_start:
                        # Convert string to datetime if needed
                        if isinstance(saved_week_start, str):
                            saved_week_start = datetime.fromisoformat(saved_week_start)
                        current_week_start = self._get_week_start_date()
                        # Only use saved weekly_stats if same week
                        if saved_week_start.date() == current_week_start.date():
                            self.weekly_stats = data['weekly_stats']
                            # Ensure week_start_date is datetime object
                            if isinstance(self.weekly_stats['week_start_date'], str):
                                self.weekly_stats['week_start_date'] = datetime.fromisoformat(self.weekly_stats['week_start_date'])
                            log.info(f"✅ Loaded weekly_stats from {loaded_from} (week: {saved_week_start.date()})")
                
                # Load closed trades
                # Rev 00216: Use trade_id to prevent duplicates when loading
                loaded_trade_ids = set()
                for trade_data in data.get('closed_trades', []):
                    trade_id = trade_data.get('trade_id', '')
                    # Skip if we already loaded this trade (prevent duplicates)
                    if trade_id and trade_id in loaded_trade_ids:
                        log.debug(f"Skipping duplicate trade: {trade_id}")
                        continue
                    
                    try:
                        trade = MockTrade(**trade_data)
                        trade.timestamp = datetime.fromisoformat(trade_data['timestamp'])
                        if trade_data.get('exit_timestamp'):
                            trade.exit_timestamp = datetime.fromisoformat(trade_data['exit_timestamp'])
                        self.closed_trades.append(trade)
                        if trade_id:
                            loaded_trade_ids.add(trade_id)
                    except Exception as load_error:
                        log.warning(f"⚠️ Could not load trade {trade_id}: {load_error}")
                    
                log.info(f"✅ Loaded mock trading data from {loaded_from}: {self.total_trades} trades, {len(self.closed_trades)} closed trades, P&L: ${self.total_pnl:.2f}, Balance: ${self.account_balance:.2f}")
                
                # Rev 00185: Validate that total_trades matches closed_trades count
                if self.total_trades != len(self.closed_trades):
                    log.warning(f"⚠️ DISCREPANCY: total_trades ({self.total_trades}) != closed_trades count ({len(self.closed_trades)})")
                    log.warning(f"   Updating total_trades to match closed_trades count to ensure accuracy")
                    self.total_trades = len(self.closed_trades)
                    # Recalculate winning/losing trades from closed_trades
                    self.winning_trades = sum(1 for t in self.closed_trades if t.pnl > 0)
                    self.losing_trades = sum(1 for t in self.closed_trades if t.pnl <= 0)
                    log.info(f"✅ Corrected: total_trades={self.total_trades}, winning={self.winning_trades}, losing={self.losing_trades}")
                
                # If loaded from GCS, also save to local for faster future loads
                if loaded_from == "GCS":
                    try:
                        os.makedirs(os.path.dirname(self.mock_data_file), exist_ok=True)
                        # Save the loaded data to local file for faster future loads
                        with open(self.mock_data_file, 'w') as f:
                            json.dump(data, f, indent=2)
                        log.debug(f"✅ Synced GCS data to local file for faster future loads")
                    except Exception as sync_error:
                        log.debug(f"Could not sync GCS data to local: {sync_error}")
                
            except json.JSONDecodeError as e:
                log.warning(f"Invalid JSON in mock trading data ({loaded_from}): {e}")
                # Reset to empty state
                self._reset_to_defaults()
            except Exception as e:
                log.warning(f"Failed to process mock trading data from {loaded_from}: {e}")
                # Reset to empty state
                self._reset_to_defaults()
        else:
            log.info(f"📭 No existing mock trading data found (GCS or local) - starting fresh")
            self._reset_to_defaults()
    
    def _reset_to_defaults(self):
        """Reset to default empty state"""
        self.total_trades = 0
        self.total_pnl = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        self.closed_trades = []
        self.account_balance = 1000.0
        self.starting_balance = 1000.0
        # Rev 00177: Initialize weekly_stats if not loaded
        if not hasattr(self, 'weekly_stats') or not self.weekly_stats:
            self.weekly_stats = {
                'positions_opened': 0,
                'positions_closed': 0,
                'total_pnl': 0.0,
                'winning_trades': 0,
                'losing_trades': 0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'week_start_date': self._get_week_start_date()
            }
            
    def _save_mock_data(self):
        """Save mock trading data to GCS (primary) and local file (backup)"""
        try:
            # Rev 00185: SAFEGUARD - Before saving, check if GCS has more trades than we have in memory
            # This prevents data loss if closed_trades was accidentally cleared or if we're missing historical data
            gcs_trade_count = 0
            gcs_closed_trades = []
            try:
                from .gcs_persistence import get_gcs_persistence
                gcs = get_gcs_persistence()
                gcs_path = "demo_account/mock_trading_history.json"
                
                if gcs.enabled and gcs.file_exists(gcs_path):
                    json_content = gcs.read_string(gcs_path)
                    if json_content:
                        gcs_data = json.loads(json_content)
                        gcs_closed_trades = gcs_data.get('closed_trades', [])
                        gcs_trade_count = len(gcs_closed_trades)
                        log.info(f"📊 GCS has {gcs_trade_count} historical trades, memory has {len(self.closed_trades)} trades")
            except Exception as gcs_check_error:
                log.debug(f"Could not check GCS before save (non-critical): {gcs_check_error}")
            
            # Rev 00216: ALWAYS merge GCS trades with memory trades (both directions)
            # This ensures we NEVER lose historical data, even if one source is reset
            # Previous logic only merged if GCS had MORE trades, which could lose data if GCS was reset
            all_closed_trades = list(self.closed_trades)  # Start with current trades
            existing_trade_ids = {trade.trade_id for trade in self.closed_trades}
            
            # Always merge GCS trades (if any exist) to prevent data loss
            if gcs_closed_trades:
                trades_recovered = 0
                for trade_data in gcs_closed_trades:
                    trade_id = trade_data.get('trade_id', '')
                    if trade_id and trade_id not in existing_trade_ids:
                        try:
                            trade = MockTrade(**trade_data)
                            trade.timestamp = datetime.fromisoformat(trade_data['timestamp'])
                            if trade_data.get('exit_timestamp'):
                                trade.exit_timestamp = datetime.fromisoformat(trade_data['exit_timestamp'])
                            all_closed_trades.append(trade)
                            existing_trade_ids.add(trade_id)
                            trades_recovered += 1
                            log.info(f"✅ Recovered historical trade: {trade.symbol} ({trade_id})")
                        except Exception as merge_error:
                            log.warning(f"⚠️ Could not merge trade {trade_id}: {merge_error}")
                
                if trades_recovered > 0:
                    # Update self.closed_trades with merged list
                    original_count = len(self.closed_trades)
                    self.closed_trades = all_closed_trades
                    log.info(f"✅ Merged trades: Now have {len(self.closed_trades)} total trades (was {original_count}, recovered {trades_recovered} from GCS)")
                    
                    # Rev 00185: Recalculate stats from merged closed_trades to ensure accuracy
                    self.total_trades = len(self.closed_trades)
                    self.total_pnl = sum(t.pnl for t in self.closed_trades)
                    self.winning_trades = sum(1 for t in self.closed_trades if t.pnl > 0)
                    self.losing_trades = sum(1 for t in self.closed_trades if t.pnl <= 0)
                    log.info(f"✅ Recalculated stats from merged trades: total_trades={self.total_trades}, total_pnl=${self.total_pnl:.2f}, wins={self.winning_trades}, losses={self.losing_trades}")
                elif gcs_trade_count > len(self.closed_trades):
                    # GCS has more trades but we couldn't merge them (likely duplicate IDs or format issue)
                    log.warning(f"⚠️ GCS has {gcs_trade_count} trades but memory has {len(self.closed_trades)} - could not merge (check trade IDs)")
            
            # Rev 00216: CRITICAL SAFEGUARD - Never save if we would lose historical trades
            # If GCS had trades and we're about to save fewer, that's a data loss risk
            if gcs_trade_count > 0 and len(self.closed_trades) < gcs_trade_count:
                log.error(f"🚨 CRITICAL: About to save {len(self.closed_trades)} trades, but GCS had {gcs_trade_count} trades - DATA LOSS RISK!")
                log.error(f"   This should never happen - merging should have recovered all GCS trades")
                log.error(f"   Attempting to recover all GCS trades before save...")
                
                # Force merge all GCS trades (even if IDs match, in case of format issues)
                for trade_data in gcs_closed_trades:
                    trade_id = trade_data.get('trade_id', '')
                    # Check if we already have this trade by comparing key fields
                    already_exists = False
                    for existing_trade in self.closed_trades:
                        if (existing_trade.trade_id == trade_id or
                            (existing_trade.symbol == trade_data.get('symbol') and
                             abs(existing_trade.pnl - trade_data.get('pnl', 0)) < 0.01 and
                             existing_trade.timestamp.isoformat()[:10] == trade_data.get('timestamp', '')[:10])):
                            already_exists = True
                            break
                    
                    if not already_exists:
                        try:
                            trade = MockTrade(**trade_data)
                            trade.timestamp = datetime.fromisoformat(trade_data['timestamp'])
                            if trade_data.get('exit_timestamp'):
                                trade.exit_timestamp = datetime.fromisoformat(trade_data['exit_timestamp'])
                            self.closed_trades.append(trade)
                            log.info(f"✅ Force-recovered trade: {trade.symbol} ({trade_id})")
                        except Exception as merge_error:
                            log.warning(f"⚠️ Could not force-merge trade {trade_id}: {merge_error}")
                
                # Recalculate after force merge
                self.total_trades = len(self.closed_trades)
                self.total_pnl = sum(t.pnl for t in self.closed_trades)
                self.winning_trades = sum(1 for t in self.closed_trades if t.pnl > 0)
                self.losing_trades = sum(1 for t in self.closed_trades if t.pnl <= 0)
                log.info(f"✅ After force-merge: {len(self.closed_trades)} trades, P&L=${self.total_pnl:.2f}")
            
            # Rev 00185: Ensure stats match closed_trades count (safety check)
            if self.total_trades != len(self.closed_trades):
                log.warning(f"⚠️ Stats mismatch before save: total_trades ({self.total_trades}) != closed_trades count ({len(self.closed_trades)})")
                log.warning(f"   Recalculating stats from closed_trades to ensure accuracy")
                self.total_trades = len(self.closed_trades)
                self.total_pnl = sum(t.pnl for t in self.closed_trades)
                self.winning_trades = sum(1 for t in self.closed_trades if t.pnl > 0)
                self.losing_trades = sum(1 for t in self.closed_trades if t.pnl <= 0)
                log.info(f"✅ Corrected stats: total_trades={self.total_trades}, total_pnl=${self.total_pnl:.2f}")
            
            # Prepare data structure
            data = {
                'total_pnl': self.total_pnl,
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'account_balance': self.account_balance,  # Rev 00153: Persist account balance
                'starting_balance': getattr(self, 'starting_balance', 1000.0),  # Rev 00153: Persist starting balance
                'weekly_stats': self.weekly_stats.copy(),  # Rev 00177: Persist weekly_stats
                'closed_trades': []
            }
            
            # Convert week_start_date to ISO string for JSON serialization
            if 'week_start_date' in data['weekly_stats'] and isinstance(data['weekly_stats']['week_start_date'], datetime):
                data['weekly_stats']['week_start_date'] = data['weekly_stats']['week_start_date'].isoformat()
            
            # Save closed trades (now includes all historical trades)
            for trade in self.closed_trades:
                trade_dict = asdict(trade)
                # Convert enums to strings for JSON serialization
                if 'side' in trade_dict and hasattr(trade_dict['side'], 'value'):
                    trade_dict['side'] = trade_dict['side'].value
                if 'signal_quality' in trade_dict and hasattr(trade_dict['signal_quality'], 'value'):
                    trade_dict['signal_quality'] = trade_dict['signal_quality'].value
                if 'status' in trade_dict and hasattr(trade_dict['status'], 'value'):
                    trade_dict['status'] = trade_dict['status'].value
                trade_dict['timestamp'] = trade.timestamp.isoformat()
                if trade.exit_timestamp:
                    trade_dict['exit_timestamp'] = trade.exit_timestamp.isoformat()
                data['closed_trades'].append(trade_dict)
            
            log.info(f"💾 Saving {len(data['closed_trades'])} total trades to GCS (ensures persistence across deployments)")
            
            # Save to local file first (for backup)
            try:
                os.makedirs(os.path.dirname(self.mock_data_file), exist_ok=True)
                with open(self.mock_data_file, 'w') as f:
                    json.dump(data, f, indent=2)
                log.debug(f"✅ Saved mock trading data to local file: {self.mock_data_file}")
            except Exception as local_error:
                log.warning(f"⚠️ Failed to save to local file: {local_error}")
            
            # Rev 00177: Save to GCS (primary persistence for Cloud Run)
            try:
                from .gcs_persistence import get_gcs_persistence
                gcs = get_gcs_persistence()
                gcs_path = "demo_account/mock_trading_history.json"
                
                if gcs.enabled:
                    # Upload JSON string directly to GCS
                    json_content = json.dumps(data, indent=2)
                    if gcs.upload_string(gcs_path, json_content):
                        log.info(f"✅ Saved mock trading data to GCS: {gcs_path} ({len(data['closed_trades'])} trades, ${data['total_pnl']:.2f} P&L, persists across redeployments)")
                    else:
                        log.warning(f"⚠️ Failed to upload to GCS (will retry on next save)")
                else:
                    log.debug(f"GCS persistence disabled - only saved locally")
            except Exception as gcs_error:
                log.warning(f"⚠️ Failed to save to GCS: {gcs_error} (local file saved as backup)")
                
        except Exception as e:
            log.error(f"❌ Failed to save mock trading data: {e}")
    
    def _get_week_start_date(self) -> datetime:
        """Get the Monday of the current week"""
        today = datetime.now().date()
        # Monday = 0, Sunday = 6
        days_since_monday = today.weekday()
        monday = today - timedelta(days=days_since_monday)
        return datetime.combine(monday, datetime.min.time())
    
    def _check_and_reset_weekly_stats(self):
        """Check if we're in a new week and reset weekly stats if needed"""
        current_week_start = self._get_week_start_date()
        
        # If we're in a new week, reset weekly stats
        if self.weekly_stats['week_start_date'] < current_week_start:
            log.info(f"🔄 New week detected - Resetting weekly stats")
            log.info(f"   Previous week: {self.weekly_stats['week_start_date'].strftime('%Y-%m-%d')}")
            log.info(f"   Current week: {current_week_start.strftime('%Y-%m-%d')}")
            
            self.weekly_stats = {
                'positions_opened': 0,
                'positions_closed': 0,
                'total_pnl': 0.0,
                'winning_trades': 0,
                'losing_trades': 0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'week_start_date': current_week_start
            }
            log.info("✅ Weekly statistics reset for new week (Monday)")
    
    def reset_daily_stats(self):
        """Reset daily statistics (like Live Mode) - called at start of new trading day or after EOD report"""
        self.daily_stats = {
            'positions_opened': 0,
            'positions_closed': 0,
            'total_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
            'best_trade': 0.0,
            'worst_trade': 0.0
        }
        self.current_trading_date = datetime.utcnow().date()  # Rev 00074: UTC consistency
        
        # Check if we need to reset weekly stats (new week)
        self._check_and_reset_weekly_stats()
        
        log.info("🔄 Demo Mode: Daily statistics reset for new trading day")
    
    async def execute_mock_trade(self, signal, market_data: List[Dict]) -> Optional[MockTrade]:
        """
        Execute a mock trade based on signal
        """
        try:
            # CRITICAL: Check market hours before executing mock trades
            from .prime_market_manager import get_prime_market_manager
            market_manager = get_prime_market_manager()
            if not market_manager.is_market_open():
                log.warning(f"🚫 Mock Trading: Market is closed, rejecting mock trade for {signal.symbol}")
                return None
            
            # Generate mock trade ID (Rev 00232: Shortened format for alerts - symbol_date_microseconds)
            now = datetime.now()
            # Format: MOCK_SYMBOL_YYMMDD_microseconds (e.g., MOCK_AVGU_260107_546)
            date_str = now.strftime('%y%m%d')  # 2-digit year
            microseconds_short = now.microsecond % 1000  # Last 3 digits for uniqueness
            trade_id = f"MOCK_{signal.symbol}_{date_str}_{microseconds_short:03d}"
            
            # Calculate position size using Demo Risk Manager (if available)
            quantity = 100  # Default fallback
            
            # Try to get position size from Demo Risk Manager
            try:
                from .prime_demo_risk_manager import get_prime_demo_risk_manager
                demo_risk_manager = get_prime_demo_risk_manager()
                
                # Rev 00180V: Use market_data if it's a dict (has the critical fields!)
                # Otherwise create basic market data
                if isinstance(market_data, dict):
                    # Use the passed market_data (has num_concurrent_positions, so_capital_allocation, etc.)
                    market_data_dict = market_data
                    log.debug(f"  Using passed market_data: concurrent={market_data.get('num_concurrent_positions')}, SO capital=${market_data.get('so_capital_allocation', 0):.2f}")
                else:
                    # Fallback: Create basic market data
                    market_data_dict = {
                        'price': signal.price,
                        'atr': signal.price * 0.02,  # Default 2% ATR
                        'volume_ratio': 1.0,
                        'momentum': 0.0,
                        'volatility': 0.01
                    }
                    log.debug(f"  Using basic market_data (fallback)")
                
                # Assess risk and get position size
                # DIAGNOSTIC (Rev 00180): Enhanced logging for trade rejection debugging
                log.info(f"🔍 Assessing risk for {signal.symbol} @ ${signal.price:.2f}...")
                risk_decision = await demo_risk_manager.assess_risk(signal, market_data_dict)
                
                log.info(f"🔍 Risk Decision: approved={risk_decision.approved}, reason={risk_decision.reason}")
                
                if risk_decision.approved and risk_decision.position_size:
                    # Extract quantity from PositionRisk object
                    quantity = risk_decision.position_size.quantity
                    log.info(f"✅ Demo Risk Manager: Position size {quantity} shares approved (value: ${risk_decision.position_size.net_position_value:.2f})")
                else:
                    log.warning(f"❌ Demo Risk Manager: Position REJECTED - Reason: {risk_decision.reason}")
                    log.warning(f"   Signal: {signal.symbol} @ ${signal.price:.2f}, Confidence: {signal.confidence:.2%}")
                    return None
                    
            except Exception as e:
                log.warning(f"Demo Risk Manager not available, using fallback position sizing: {e}")
                
                # Fallback to quality-based sizing
                quality_multiplier = {
                    SignalQuality.ULTRA_HIGH: 1.5,
                    SignalQuality.VERY_HIGH: 1.3,
                    SignalQuality.HIGH: 1.1,
                    SignalQuality.MEDIUM: 1.0,
                    SignalQuality.LOW: 0.8
                }
                
                quantity = 100 * quality_multiplier.get(signal.quality, 1.0)
            
            # Calculate stop loss and take profit based on signal price
            entry_price = signal.price
            stop_loss = entry_price * 0.95  # 5% stop loss
            take_profit = entry_price * 1.15  # 15% take profit
            
            # Create mock trade
            position_value = quantity * entry_price  # Calculate position value
            mock_trade = MockTrade(
                trade_id=trade_id,
                symbol=signal.symbol,
                side=signal.side,
                entry_price=entry_price,
                quantity=quantity,
                stop_loss=stop_loss,
                take_profit=take_profit,
                signal_quality=signal.quality,
                confidence=signal.confidence,
                timestamp=datetime.now(),
                current_price=entry_price,
                trailing_stop=stop_loss,
                max_favorable=entry_price,
                position_value=position_value  # FIX: Set position value for stealth trailing (Oct 24, 2025)
            )
            
            # Add to active trades
            self.active_trades[trade_id] = mock_trade
            
            # Update daily stats (like Live Mode)
            self.daily_stats['positions_opened'] += 1
            
            # Notify Demo Risk Manager of new position for tracking
            try:
                from .prime_demo_risk_manager import get_prime_demo_risk_manager
                demo_risk_manager = get_prime_demo_risk_manager()
                demo_risk_manager.update_mock_position(
                    signal.symbol,
                    {
                        'symbol': signal.symbol,
                        'quantity': quantity,
                        'entry_price': entry_price,
                        'value': quantity * entry_price,
                        'source': 'strategy'
                    }
                )
                log.info(f"🎮 Demo Risk Manager notified of new position: {signal.symbol}")
            except Exception as e:
                log.warning(f"Could not notify Demo Risk Manager: {e}")
            
            # Update position
            await self._update_position(mock_trade)
            
            # Notify compound engine (Rev 00179) - Track deployed capital
            if self.compound_engine:
                position_value = quantity * entry_price
                signal_type = "SO" if hasattr(signal, 'signal_type') and signal.signal_type == "SO" else "ORR"
                self.compound_engine.on_position_opened(signal.symbol, position_value, signal_type)
                log.info(f"♻️ Compound Engine: Tracked {signal.symbol} open (${position_value:.2f}, {signal_type})")
            
            # Rev 00046: CRITICAL - SO trades use BATCH alert at 7:30 AM PT
            # Rev 00056: Individual alerts are DEPRECATED for SO trades
            # Only ORR trades (currently disabled) would use individual alerts
            is_so_trade = market_data.get('is_so_trade', False) if isinstance(market_data, dict) else False
            
            if is_so_trade:
                # SO trade - NO individual alert, only batch alert at 7:30 AM PT
                log.info(f"📦 SO trade {signal.symbol} - individual alert skipped (batch alert at 7:30 AM PT)")
            elif self.alert_manager:
                # ORR trade (currently disabled) - would send individual alert
                log.info(f"📱 ORR trade {signal.symbol} - individual alert (ORR currently disabled)")
                # Note: Individual alert code removed - ORR is disabled
            
            log.info(f"Mock trade executed: {signal.symbol} {signal.side.value} at ${entry_price}")
            
            return mock_trade
            
        except Exception as e:
            log.error(f"Failed to execute mock trade: {e}")
            return None
    
    async def update_mock_trades(self, market_prices: Dict[str, float]):
        """
        Update all active mock trades with current market prices
        """
        try:
            trades_to_close = []
            
            for trade_id, trade in self.active_trades.items():
                if trade.symbol in market_prices:
                    trade.current_price = market_prices[trade.symbol]
                    
                    # Calculate unrealized P&L
                    if trade.side == SignalSide.BUY:
                        trade.unrealized_pnl = (trade.current_price - trade.entry_price) * trade.quantity
                    else:
                        trade.unrealized_pnl = (trade.entry_price - trade.current_price) * trade.quantity
                    
                    # Update trailing stop (stealth trailing)
                    await self._update_trailing_stop(trade)
                    
                    # Check exit conditions
                    exit_reason = await self._check_exit_conditions(trade)
                    if exit_reason:
                        trades_to_close.append((trade_id, exit_reason))
            
            # Close trades that hit exit conditions
            for trade_id, exit_reason in trades_to_close:
                await self._close_mock_trade(trade_id, exit_reason)
                
        except Exception as e:
            log.error(f"Failed to update mock trades: {e}")
    
    async def _update_trailing_stop(self, trade: MockTrade):
        """
        Update trailing stop using stealth trailing logic
        """
        try:
            if trade.side == SignalSide.BUY:
                # For long positions
                if trade.current_price > trade.max_favorable:
                    trade.max_favorable = trade.current_price
                    
                    # Stealth trailing: move stop loss closer as price moves favorably
                    favorable_move = trade.max_favorable - trade.entry_price
                    trailing_distance = trade.entry_price * 0.02  # 2% trailing distance
                    
                    if favorable_move > trailing_distance:
                        new_trailing_stop = trade.max_favorable - trailing_distance
                        if new_trailing_stop > trade.trailing_stop:
                            trade.trailing_stop = new_trailing_stop
                            log.info(f"Updated trailing stop for {trade.symbol}: ${trade.trailing_stop:.2f}")
            else:
                # For short positions
                if trade.current_price < trade.max_favorable:
                    trade.max_favorable = trade.current_price
                    
                    favorable_move = trade.entry_price - trade.max_favorable
                    trailing_distance = trade.entry_price * 0.02
                    
                    if favorable_move > trailing_distance:
                        new_trailing_stop = trade.max_favorable + trailing_distance
                        if new_trailing_stop < trade.trailing_stop:
                            trade.trailing_stop = new_trailing_stop
                            log.info(f"Updated trailing stop for {trade.symbol}: ${trade.trailing_stop:.2f}")
                            
        except Exception as e:
            log.error(f"Failed to update trailing stop: {e}")
    
    async def _check_exit_conditions(self, trade: MockTrade) -> Optional[str]:
        """
        Check if trade should be closed based on exit conditions
        """
        try:
            if trade.side == SignalSide.BUY:
                # Check stop loss
                if trade.current_price <= trade.trailing_stop:
                    return "Stop Loss Hit"
                
                # Check take profit
                if trade.current_price >= trade.take_profit:
                    return "Take Profit Hit"
            else:
                # Check stop loss
                if trade.current_price >= trade.trailing_stop:
                    return "Stop Loss Hit"
                
                # Check take profit
                if trade.current_price <= trade.take_profit:
                    return "Take Profit Hit"
            
            return None
            
        except Exception as e:
            log.error(f"Failed to check exit conditions: {e}")
            return None
    
    async def close_position_with_data(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        pnl: float
    ):
        """
        Close a position with provided exit data from Stealth Trailing (Rev 00076)
        
        This is the CORRECT method that receives accurate exit price and P&L
        from the stealth trailing system which updates prices every 30 seconds.
        
        Args:
            symbol: Symbol to close
            exit_price: Actual exit price from stealth trailing
            exit_reason: Reason for closure
            pnl: Calculated P&L from stealth trailing
        """
        try:
            # Find trade_id for this symbol
            trade_id = None
            for tid, trade in self.active_trades.items():
                if trade.symbol == symbol:
                    trade_id = tid
                    break
            
            if trade_id:
                trade = self.active_trades[trade_id]
                trade.status = TradeStatus.CLOSED
                trade.exit_price = exit_price  # ✅ Rev 00076: Use provided exit price!
                trade.exit_timestamp = datetime.utcnow()
                trade.exit_reason = exit_reason
                trade.pnl = pnl  # ✅ Rev 00076: Use provided P&L!
                
                # Update cumulative statistics
                self.total_trades += 1
                self.total_pnl += pnl
                
                # Update Demo account balance
                if self.compound_engine:
                    self.account_balance = self.compound_engine.state.total_account
                    log.info(f"💰 Demo Balance (compounded): ${self.account_balance:,.2f} (P&L: ${pnl:+.2f})")
                else:
                    self.account_balance += pnl
                    log.info(f"💰 Demo Balance: ${self.account_balance:,.2f} (P&L: ${pnl:+.2f})")
                
                if pnl > 0:
                    self.winning_trades += 1
                else:
                    self.losing_trades += 1
                
                # Rev 00153: Update daily stats BEFORE moving to closed_trades (critical order)
                self.daily_stats['positions_closed'] += 1
                self.daily_stats['total_pnl'] += pnl
                
                if pnl > 0:
                    self.daily_stats['winning_trades'] += 1
                    if pnl > self.daily_stats['best_trade']:
                        self.daily_stats['best_trade'] = pnl
                else:
                    self.daily_stats['losing_trades'] += 1
                    if pnl < self.daily_stats['worst_trade']:
                        self.daily_stats['worst_trade'] = pnl
                
                # Update weekly stats
                self.weekly_stats['positions_closed'] += 1
                self.weekly_stats['total_pnl'] += pnl
                
                if pnl > 0:
                    self.weekly_stats['winning_trades'] += 1
                    if pnl > self.weekly_stats['best_trade']:
                        self.weekly_stats['best_trade'] = pnl
                else:
                    self.weekly_stats['losing_trades'] += 1
                    if pnl < self.weekly_stats['worst_trade']:
                        self.weekly_stats['worst_trade'] = pnl
                
                # Rev 00203: Move to closed trades BEFORE saving to ensure trade is persisted
                # This ensures the trade is included in closed_trades when we save to GCS
                self.closed_trades.append(trade)
                del self.active_trades[trade_id]
                
                # Rev 00153: Save stats after update to persist immediately (includes closed_trades)
                self._save_mock_data()
                
                log.info(f"✅ Position closed: {symbol} @ ${exit_price:.2f} | P&L: ${pnl:+.2f} ({(pnl/(trade.quantity*trade.entry_price))*100:+.2f}%) | {exit_reason}")
                log.debug(f"📊 Daily stats after close: {self.daily_stats['positions_closed']} closed, ${self.daily_stats['total_pnl']:.2f} P&L")
            else:
                # Rev 00181: Trade not found - this can happen if position exists in stealth trailing but not in active_trades
                # This is OK - just log and return (position will be removed from stealth trailing by caller)
                log.warning(f"⚠️ Cannot close {symbol}: Trade not found in active trades (position may have been closed already or orphaned)")
                # Return True to indicate we handled it (even though we didn't close anything)
                # This prevents exceptions from propagating and causing infinite loops
                return True
                
        except Exception as e:
            log.error(f"❌ Error closing position for {symbol}: {e}", exc_info=True)
            # Rev 00153: Even on error, try to ensure trade is tracked if it was already added to closed_trades
            # This prevents loss of trade data even if stats update fails
            # Rev 00181: Return True to prevent exception from causing infinite loops
            return True
    
    async def close_position(self, symbol: str, exit_reason: str):
        """
        DEPRECATED: Old close method (has $0 P&L bug)
        
        Kept for backward compatibility, but should not be used.
        Use close_position_with_data() instead.
        
        Args:
            symbol: Symbol to close
            exit_reason: Reason for closure
        """
        try:
            # Find trade_id for this symbol
            trade_id = None
            for tid, trade in self.active_trades.items():
                if trade.symbol == symbol:
                    trade_id = tid
                    break
            
            if trade_id:
                await self._close_mock_trade(trade_id, exit_reason)
                log.warning(f"⚠️ OLD METHOD USED: {symbol} - {exit_reason} (P&L will be $0.00!)")
            else:
                log.warning(f"⚠️ Cannot close {symbol}: Trade not found in active trades")
                
        except Exception as e:
            log.error(f"Error closing position for {symbol}: {e}")
    
    async def close_positions_batch(
        self,
        positions: List,  # List of PositionState from stealth trailing
        exit_reason: str
    ) -> bool:
        """
        Close multiple positions at once and send ONE aggregated alert (Rev 00076)
        
        Used for: EOD close, emergency exits, weak day exits
        
        Args:
            positions: List of PositionState objects from stealth trailing
            exit_reason: Common exit reason for all positions
        
        Returns:
            True if all positions closed successfully
        """
        try:
            closed_data = []
            
            # Close each position (no individual alerts)
            for position in positions:
                # Find trade_id
                trade_id = None
                for tid, trade in self.active_trades.items():
                    if trade.symbol == position.symbol:
                        trade_id = tid
                        break
                
                if not trade_id:
                    # Rev 00181: Trade not found - log and track for removal from stealth trailing
                    log.warning(f"⚠️ Cannot close {position.symbol}: Trade not found in active_trades (position may have been closed already or orphaned)")
                    # Track that we tried to close this position (even though trade wasn't found)
                    # This ensures the position can still be removed from stealth trailing
                    closed_data.append({
                        'symbol': position.symbol,
                        'quantity': position.quantity,
                        'entry_price': position.entry_price,
                        'exit_price': position.current_price,
                        'pnl': position.unrealized_pnl,
                        'pnl_percent': position.unrealized_pnl_pct * 100,
                        'exit_reason': exit_reason,
                        'holding_minutes': 0,
                        'trade_not_found': True  # Flag to indicate trade wasn't in active_trades
                    })
                    continue
                
                trade = self.active_trades[trade_id]
                
                # Close trade with accurate data from stealth trailing
                trade.status = TradeStatus.CLOSED
                trade.exit_price = position.current_price  # From stealth trailing
                trade.exit_timestamp = datetime.utcnow()
                trade.exit_reason = exit_reason
                trade.pnl = position.unrealized_pnl  # From stealth trailing
                
                # Update cumulative statistics
                self.total_trades += 1
                self.total_pnl += trade.pnl
                
                # Update account balance
                if self.compound_engine:
                    self.account_balance = self.compound_engine.state.total_account
                else:
                    self.account_balance += trade.pnl
                
                if trade.pnl > 0:
                    self.winning_trades += 1
                else:
                    self.losing_trades += 1
                
                # Update daily stats
                self.daily_stats['positions_closed'] += 1
                self.daily_stats['total_pnl'] += trade.pnl
                
                if trade.pnl > 0:
                    self.daily_stats['winning_trades'] += 1
                    if trade.pnl > self.daily_stats['best_trade']:
                        self.daily_stats['best_trade'] = trade.pnl
                else:
                    self.daily_stats['losing_trades'] += 1
                    if trade.pnl < self.daily_stats['worst_trade']:
                        self.daily_stats['worst_trade'] = trade.pnl
                
                # Update weekly stats
                self._check_and_reset_weekly_stats()
                self.weekly_stats['positions_closed'] += 1
                self.weekly_stats['total_pnl'] += trade.pnl
                
                if trade.pnl > 0:
                    self.weekly_stats['winning_trades'] += 1
                    if trade.pnl > self.weekly_stats['best_trade']:
                        self.weekly_stats['best_trade'] = trade.pnl
                else:
                    self.weekly_stats['losing_trades'] += 1
                    if trade.pnl < self.weekly_stats['worst_trade']:
                        self.weekly_stats['worst_trade'] = trade.pnl
                
                # Calculate holding time
                holding_time_minutes = 0
                if trade.timestamp and trade.exit_timestamp:
                    time_diff = trade.exit_timestamp - trade.timestamp
                    holding_time_minutes = int(time_diff.total_seconds() / 60)
                
                # Calculate P&L percent
                pnl_percent = ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100
                
                # Collect data for aggregated alert
                closed_data.append({
                    'symbol': trade.symbol,
                    'quantity': trade.quantity,
                    'entry_price': trade.entry_price,
                    'exit_price': trade.exit_price,
                    'pnl': trade.pnl,
                    'pnl_pct': pnl_percent,
                    'holding_time': holding_time_minutes,
                    'trade_id': trade_id
                })
                
                # Move to closed trades
                self.closed_trades.append(trade)
                del self.active_trades[trade_id]
                
                log.info(f"✅ Position closed (batch): {trade.symbol} @ ${trade.exit_price:.2f} | P&L: ${trade.pnl:+.2f}")
            
            # Send ONE aggregated alert for all positions
            if self.alert_manager and closed_data:
                await self.alert_manager.send_aggregated_exit_alert(
                    closed_positions=closed_data,
                    exit_reason=exit_reason,
                    mode="DEMO"
                )
                log.info(f"📱 Aggregated exit alert sent for {len(closed_data)} positions")
            
            # Save data
            self._save_mock_data()
            
            log.info(f"✅ Batch close complete: {len(closed_data)} positions closed - {exit_reason}")
            return True
            
        except Exception as e:
            log.error(f"Error in batch close: {e}")
            return False
    
    async def _close_mock_trade(self, trade_id: str, exit_reason: str):
        """
        Close a mock trade by trade_id (internal method)
        """
        try:
            if trade_id not in self.active_trades:
                return
            
            trade = self.active_trades[trade_id]
            trade.status = TradeStatus.CLOSED
            trade.exit_price = trade.current_price
            trade.exit_timestamp = datetime.utcnow()  # Rev 00074: UTC consistency
            trade.exit_reason = exit_reason
            trade.pnl = trade.unrealized_pnl
            
            # Update cumulative statistics
            self.total_trades += 1
            self.total_pnl += trade.pnl
            
            # Update Demo account balance (grows with profits, shrinks with losses)
            # 🔧 CRITICAL FIX (Rev 00180AE): Sync with compound engine's compounded total
            if self.compound_engine:
                # Use compound engine's total_account (includes all P&L compounding)
                self.account_balance = self.compound_engine.state.total_account
                log.info(f"💰 Demo Balance (compounded): ${self.account_balance:,.2f} (P&L: ${trade.pnl:+.2f})")
            else:
                # Fallback: manual P&L tracking
                self.account_balance += trade.pnl
                log.info(f"💰 Demo Balance: ${self.account_balance:,.2f} (P&L: ${trade.pnl:+.2f})")
            
            if trade.pnl > 0:
                self.winning_trades += 1
            else:
                self.losing_trades += 1
            
            # Update daily stats (like Live Mode)
            self.daily_stats['positions_closed'] += 1
            self.daily_stats['total_pnl'] += trade.pnl
            
            if trade.pnl > 0:
                self.daily_stats['winning_trades'] += 1
                if trade.pnl > self.daily_stats['best_trade']:
                    self.daily_stats['best_trade'] = trade.pnl
            else:
                self.daily_stats['losing_trades'] += 1
                if trade.pnl < self.daily_stats['worst_trade']:
                    self.daily_stats['worst_trade'] = trade.pnl
            
            # Update weekly stats (Monday-Friday)
            self._check_and_reset_weekly_stats()  # Reset if new week
            self.weekly_stats['positions_closed'] += 1
            self.weekly_stats['total_pnl'] += trade.pnl
            
            if trade.pnl > 0:
                self.weekly_stats['winning_trades'] += 1
                if trade.pnl > self.weekly_stats['best_trade']:
                    self.weekly_stats['best_trade'] = trade.pnl
            else:
                self.weekly_stats['losing_trades'] += 1
                if trade.pnl < self.weekly_stats['worst_trade']:
                    self.weekly_stats['worst_trade'] = trade.pnl
            
            # DIAGNOSTIC (Rev 00180): Log daily & weekly stats update
            log.info(f"📊 Daily Stats: Closed={self.daily_stats['positions_closed']}, P&L=${self.daily_stats['total_pnl']:.2f}, W/L={self.daily_stats['winning_trades']}/{self.daily_stats['losing_trades']}")
            log.info(f"📊 Weekly Stats: Closed={self.weekly_stats['positions_closed']}, P&L=${self.weekly_stats['total_pnl']:.2f}, W/L={self.weekly_stats['winning_trades']}/{self.weekly_stats['losing_trades']}")
            
            # Move to closed trades
            self.closed_trades.append(trade)
            del self.active_trades[trade_id]
            
            # Notify Demo Risk Manager of trade closure for account growth
            try:
                from .prime_demo_risk_manager import get_prime_demo_risk_manager
                demo_risk_manager = get_prime_demo_risk_manager()
                demo_risk_manager.process_trade_close(trade.symbol, trade.exit_price, trade.quantity, trade.pnl)
                log.info(f"🎮 Demo Risk Manager notified of trade closure: {trade.symbol} - P&L: ${trade.pnl:.2f}")
            except Exception as e:
                log.warning(f"Could not notify Demo Risk Manager: {e}")
            
            # Notify compound engine (Rev 00179) - Compound freed capital
            if self.compound_engine:
                position_value = trade.quantity * trade.entry_price
                signal_type = "SO" if hasattr(trade, 'signal_type') and trade.signal_type == "SO" else "ORR"
                freed = self.compound_engine.on_position_closed(
                    symbol=trade.symbol,
                    position_value=position_value,
                    signal_type=signal_type,
                    exit_reason=exit_reason,
                    pnl=trade.pnl
                )
                log.info(f"♻️ Compound Engine: Compounded {trade.symbol} close (${freed:.2f} freed, {exit_reason})")
                
                # Log updated capital availability
                available_orr = self.compound_engine.get_available_for_orr()
                log.info(f"💰 Available for ORR after close: ${available_orr:.2f}")
            
            # Update position
            await self._update_position(trade, closed=True)
            
            # Send exit alert
            if self.alert_manager:
                try:
                    # Calculate holding time
                    holding_time_minutes = 0
                    if trade.timestamp and trade.exit_timestamp:
                        time_diff = trade.exit_timestamp - trade.timestamp
                        holding_time_minutes = int(time_diff.total_seconds() / 60)
                    
                    # Calculate P&L
                    pnl_dollars = trade.pnl
                    pnl_percent = ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100
                    
                    # Send exit alert with new signature
                    await self.alert_manager.send_trade_exit_alert(
                        symbol=trade.symbol,
                        side="SELL",
                        quantity=trade.quantity,
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        pnl_dollars=pnl_dollars,
                        pnl_percent=pnl_percent,
                        exit_reason=exit_reason,
                        holding_time_minutes=holding_time_minutes,
                        mode="DEMO",
                        trade_id=trade_id
                    )
                    log.info(f"📱 Demo exit alert sent for {trade.symbol}")
                except Exception as e:
                    log.warning(f"Failed to send trade exit alert: {e}")
            
            # Save data
            self._save_mock_data()
            
            log.info(f"Mock trade closed: {trade.symbol} {trade.side.value} - P&L: ${trade.pnl:.2f} ({exit_reason})")
            
            return trade
            
        except Exception as e:
            log.error(f"Failed to close mock trade: {e}")
            return None
    
    async def _update_position(self, trade: MockTrade, closed: bool = False):
        """
        Update position based on trade
        """
        try:
            symbol = trade.symbol
            
            if closed:
                # Remove from positions if quantity becomes zero
                if symbol in self.positions:
                    position = self.positions[symbol]
                    if position.quantity == trade.quantity:
                        del self.positions[symbol]
                    else:
                        position.quantity -= trade.quantity
                        position.realized_pnl += trade.pnl
            else:
                # Add to positions
                if symbol not in self.positions:
                    self.positions[symbol] = MockPosition(
                        symbol=symbol,
                        quantity=0.0,
                        average_price=0.0,
                        current_price=trade.current_price,
                        unrealized_pnl=0.0,
                        realized_pnl=0.0,
                        stop_loss=trade.stop_loss,
                        take_profit=trade.take_profit,
                        trailing_stop=trade.trailing_stop,
                        max_favorable=trade.max_favorable
                    )
                
                position = self.positions[symbol]
                total_value = (position.quantity * position.average_price) + (trade.quantity * trade.entry_price)
                position.quantity += trade.quantity
                position.average_price = total_value / position.quantity
                position.current_price = trade.current_price
                position.unrealized_pnl += trade.unrealized_pnl
                
        except Exception as e:
            log.error(f"Failed to update position: {e}")
    
    async def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive performance summary
        """
        try:
            total_trades = len(self.closed_trades)
            win_rate = (self.winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            # Calculate additional metrics
            total_return = self.total_pnl / 10000 if self.total_pnl > 0 else 0  # Assuming $10k starting capital
            
            avg_win = 0
            avg_loss = 0
            
            if self.winning_trades > 0:
                wins = [t.pnl for t in self.closed_trades if t.pnl > 0]
                avg_win = sum(wins) / len(wins) if wins else 0
            
            if self.losing_trades > 0:
                losses = [t.pnl for t in self.closed_trades if t.pnl < 0]
                avg_loss = sum(losses) / len(losses) if losses else 0
            
            profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
            
            return {
                'total_trades': total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'win_rate': win_rate,
                'total_pnl': self.total_pnl,
                'total_return': total_return,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
                'active_positions': len(self.active_trades),
                'active_trades': len(self.positions)
            }
            
        except Exception as e:
            log.error(f"Failed to get performance summary: {e}")
            return {}
    
    def get_active_positions(self) -> Dict[str, Any]:
        """
        Get active mock positions for Demo Mode
        """
        try:
            active_positions = {}
            for trade_id, trade in self.active_trades.items():
                if trade.status == TradeStatus.OPEN:
                    active_positions[trade_id] = {
                        'symbol': trade.symbol,
                        'side': trade.side,
                        'quantity': trade.quantity,
                        'entry_price': trade.entry_price,
                        'current_price': trade.current_price,
                        'unrealized_pnl': trade.unrealized_pnl,
                        'status': trade.status,
                        'entry_time': trade.timestamp
                    }
            return active_positions
        except Exception as e:
            log.error(f"Failed to get active positions: {e}")
            return {}
    
    # NOTE (Rev 00180AE): generate_end_of_day_report() REMOVED
    # EOD reports now generated in prime_alert_manager.send_end_of_day_report()
    # This unified function handles both Demo and Live modes