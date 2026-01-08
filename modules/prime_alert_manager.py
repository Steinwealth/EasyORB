#!/usr/bin/env python3
"""
Prime Alert Manager
==================

Comprehensive alert management system for the Easy ORB Strategy.
Handles all Telegram notifications for trade signals, performance updates,
and end-of-day summaries.

Key Features:
- Trade signal alerts (entry/exit notifications)
- Performance monitoring alerts
- End-of-day trade summaries
- System status notifications
- Error and warning alerts
- Configurable alert levels and throttling
- HTML formatting with auto-fallback to plain text
- Aggregated batch exit alerts (Rev 00078)
- Enhanced formatting with bold key metrics (Rev 00231)

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import asyncio
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import requests
import aiohttp
from collections import defaultdict, deque
import threading

try:
    from .config_loader import get_config_value
except ImportError:
    # Fallback for direct imports
    def get_config_value(key, default=''):
        import os
        return os.getenv(key, default)

log = logging.getLogger(__name__)

class AlertLevel(Enum):
    """Alert level enumeration"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    SUCCESS = "success"

class AlertType(Enum):
    """Alert type enumeration"""
    TRADE_SIGNAL = "trade_signal"
    TRADE_ENTRY = "trade_entry"
    TRADE_EXIT = "trade_exit"
    PERFORMANCE_UPDATE = "performance_update"
    END_OF_DAY_SUMMARY = "end_of_day_summary"
    SYSTEM_STATUS = "system_status"
    ERROR = "error"
    WARNING = "warning"
    MARKET_ALERT = "market_alert"
    # OAuth Token Management Alerts
    OAUTH_RENEWAL = "oauth_renewal"
    OAUTH_SUCCESS = "oauth_success"
    OAUTH_EXPIRED = "oauth_expired"
    OAUTH_ERROR = "oauth_error"
    OAUTH_WARNING = "oauth_warning"
    OAUTH_TOKEN_RENEWED_CONFIRMATION = "oauth_token_renewed_confirmation"
    
    # Trading Pipeline Alerts (Rev 00173)
    # ORB Strategy Alerts (ACTIVE)
    ORB_CAPTURE_COMPLETE = "orb_capture_complete"
    SO_EXECUTION_AGGREGATED = "so_execution_aggregated"
    ORR_EXECUTION_INDIVIDUAL = "orr_execution_individual"
    ORB_NO_SIGNALS = "orb_no_signals"
    
    # 0DTE Strategy Alerts (Rev 00206)
    ODTE_ORB_CAPTURE = "0dte_orb_capture"
    OPTIONS_SIGNAL_COLLECTION = "options_signal_collection"
    OPTIONS_EXECUTION = "options_execution"
    OPTIONS_POSITION_EXIT = "options_position_exit"
    OPTIONS_AGGREGATED_EXIT = "options_aggregated_exit"
    OPTIONS_PARTIAL_PROFIT = "options_partial_profit"
    OPTIONS_RUNNER_EXIT = "options_runner_exit"
    OPTIONS_HEALTH_CHECK = "options_health_check"
    
    # ARCHIVED ALERTS (Rev 00173) - Methods kept for backward compatibility but not called
    WATCHLIST_CREATED = "watchlist_created"  # ❌ ARCHIVED - Static list used
    SYMBOL_SELECTION_COMPLETE = "symbol_selection_complete"  # ❌ ARCHIVED - All symbols used
    MULTI_STRATEGY_ANALYSIS = "multi_strategy_analysis"  # ❌ ARCHIVED - ORB only
    SIGNAL_GENERATOR_PROCESSING = "signal_generator_processing"  # ❌ ARCHIVED - ORB direct
    MOCK_EXECUTOR_PROCESSING = "mock_executor_processing"

@dataclass
class Alert:
    """Alert data structure"""
    alert_id: str
    alert_type: AlertType
    level: AlertLevel
    title: str
    message: str
    symbol: Optional[str] = None
    strategy: Optional[str] = None
    confidence: Optional[float] = None
    expected_return: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TradeAlert:
    """Trade-specific alert data structure"""
    symbol: str
    strategy: str
    action: str  # "BUY" or "SELL"
    price: float
    quantity: int
    confidence: float
    expected_return: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class PerformanceSummary:
    """End-of-day performance summary"""
    date: datetime
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    daily_return: float
    active_positions: int
    signals_generated: int
    signals_accepted: int
    acceptance_rate: float
    top_performers: List[Dict[str, Any]] = field(default_factory=list)
    worst_performers: List[Dict[str, Any]] = field(default_factory=list)
    
    # Additional metrics for enhanced reporting
    max_drawdown: float = 0.0
    capital_used_pct: float = 0.0
    consecutive_wins: int = 0
    avg_risk_per_trade: float = 4.2
    total_pnl_dollars: float = 0.0

@dataclass
class OAuthAlert:
    """OAuth-specific alert data structure"""
    environment: str  # "prod" or "sandbox"
    alert_type: str  # "renewal", "success", "error", "warning"
    message: str
    oauth_url: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

class PrimeAlertManager:
    """Prime Alert Manager for comprehensive notification system"""
    
    def __init__(self):
        self.name = "Prime Alert Manager"
        self.version = "1.0"
        # UNIQUE DEPLOYMENT IDENTIFIER - REVISION 00077 DEBUG
        self.deployment_id = "REV_00077_DEBUG_2025_10_07"
        
        # Load configuration first
        self._load_configuration()
        
        # Telegram configuration
        self.telegram_bot_token = get_config_value('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = get_config_value('TELEGRAM_CHAT_ID', '')
        telegram_config = get_config_value('TELEGRAM_ALERTS_ENABLED', 'true')
        self.telegram_enabled = str(telegram_config).lower() == 'true' if isinstance(telegram_config, (str, bool)) else True
        
        # Alert configuration
        def safe_bool_config(key: str, default: str = 'true') -> bool:
            config_val = get_config_value(key, default)
            return str(config_val).lower() == 'true' if isinstance(config_val, (str, bool)) else True
        
        self.alert_levels_enabled = {
            AlertLevel.INFO: safe_bool_config('ALERT_LEVEL_INFO', 'true'),
            AlertLevel.WARNING: safe_bool_config('ALERT_LEVEL_WARNING', 'true'),
            AlertLevel.ERROR: safe_bool_config('ALERT_LEVEL_ERROR', 'true'),
            AlertLevel.CRITICAL: safe_bool_config('ALERT_LEVEL_CRITICAL', 'true'),
            AlertLevel.SUCCESS: safe_bool_config('ALERT_LEVEL_SUCCESS', 'true')
        }
        
        # Throttling configuration
        self.max_alerts_per_minute = int(get_config_value('TELEGRAM_MAX_MESSAGES_PER_MINUTE', '20'))
        self.alert_cooldown_seconds = int(get_config_value('ALERT_COOLDOWN_SECONDS', '30'))
        
        # Alert tracking
        self.alert_history = deque(maxlen=1000)
        self.alert_counts = defaultdict(int)
        self.last_alert_time = defaultdict(float)
        
        # Performance tracking
        self.daily_performance = {}
        self.trade_history = []

        # Pipeline alert behavior toggles (Rev 00173)
        # ARCHIVED: Multi-strategy alerts no longer used - ORB strategy only
        per_symbol_cfg = get_config_value('MULTI_STRATEGY_PER_SYMBOL_ALERTS', 'false')
        self.multi_strategy_per_symbol_enabled = str(per_symbol_cfg).lower() == 'true'
        log.info(f"🔧 ORB Strategy Active (Rev 00173) - Legacy multi-strategy alerts: {'ENABLED' if self.multi_strategy_per_symbol_enabled else 'DISABLED (archived)'}")
        log.info(f"🚀 DEPLOYMENT ID: {self.deployment_id}")
        
        # End of day scheduling
        self.scheduler_thread = None
        self.scheduler_running = False
        
        # OAuth configuration
        oauth_config = get_config_value('OAUTH_ALERTS_ENABLED', 'true')
        self.oauth_enabled = str(oauth_config).lower() == 'true' if isinstance(oauth_config, (str, bool)) else True
        self.oauth_renewal_url = get_config_value('OAUTH_RENEWAL_URL', 'https://easy-trading-oauth-v2.web.app')
        self.oauth_morning_hour = int(get_config_value('OAUTH_MORNING_HOUR', '21'))
        self.oauth_morning_minute = int(get_config_value('OAUTH_MORNING_MINUTE', '0'))
        self.oauth_market_open_hour = int(get_config_value('OAUTH_MARKET_OPEN_HOUR', '5'))
        self.oauth_market_open_minute = int(get_config_value('OAUTH_MARKET_OPEN_MINUTE', '30'))
        self.oauth_timezone = get_config_value('OAUTH_TIMEZONE', 'America/New_York')
        
        # OAuth tracking
        self.oauth_status = {
            'prod': {'last_renewed': None, 'is_valid': False, 'expires_at': None},
            'sandbox': {'last_renewed': None, 'is_valid': False, 'expires_at': None}
        }
        
        # System status
        self.is_initialized = False
        
        log.info(f"Prime Alert Manager v{self.version} initialized")
    
    def _load_configuration(self):
        """Load configuration from .env files"""
        try:
            from .config_loader import load_configuration
            load_configuration('standard', 'demo', 'development')
            log.info("✅ Configuration loaded successfully")
        except Exception as e:
            log.warning(f"⚠️ Could not load configuration: {e}")
            # Continue without configuration loading
    
    async def initialize(self) -> bool:
        """Initialize the alert manager"""
        try:
            if self.telegram_enabled:
                # Test Telegram connection
                if await self._test_telegram_connection():
                    log.info("✅ Telegram connection successful")
                else:
                    log.warning("⚠️ Telegram connection failed")
                    self.telegram_enabled = False
            
            self.is_initialized = True
            log.info("Prime Alert Manager initialized successfully")
            return True
            
        except Exception as e:
            log.error(f"Failed to initialize alert manager: {e}")
            return False
    
    async def _test_telegram_connection(self) -> bool:
        """Test Telegram bot connection"""
        try:
            if not self.telegram_bot_token or not self.telegram_chat_id:
                return False
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get('ok'):
                    log.info(f"Telegram bot connected: @{bot_info['result']['username']}")
                    return True
            
            return False
            
        except Exception as e:
            log.error(f"Telegram connection test failed: {e}")
            return False
    
    # ============================================================================================================================================
    # TRADE ALERTS
    # ============================================================================================================================================
    
    async def send_trade_signal_alert(self, signal_data: Dict[str, Any]) -> bool:
        """Send trade signal alert"""
        try:
            alert = Alert(
                alert_id=f"signal_{signal_data.get('symbol', 'unknown')}_{int(time.time())}",
                alert_type=AlertType.TRADE_SIGNAL,
                level=AlertLevel.INFO,
                title="🎯 New Trade Signal",
                message=self._format_trade_signal_message(signal_data),
                symbol=signal_data.get('symbol'),
                strategy=signal_data.get('strategy'),
                confidence=signal_data.get('confidence'),
                expected_return=signal_data.get('expected_return'),
                metadata=signal_data
            )
            
            return await self._send_alert(alert)
            
        except Exception as e:
            log.error(f"Failed to send trade signal alert: {e}")
            return False
    
    async def send_trade_entry_alert(self, trade_data: TradeAlert) -> bool:
        """Send trade entry alert"""
        try:
            alert = Alert(
                alert_id=f"entry_{trade_data.symbol}_{int(time.time())}",
                alert_type=AlertType.TRADE_ENTRY,
                level=AlertLevel.SUCCESS,
                title="✅ Trade Executed",
                message=self._format_trade_entry_message(trade_data),
                symbol=trade_data.symbol,
                strategy=trade_data.strategy,
                confidence=trade_data.confidence,
                expected_return=trade_data.expected_return,
                metadata={
                    'action': trade_data.action,
                    'price': trade_data.price,
                    'quantity': trade_data.quantity,
                    'stop_loss': trade_data.stop_loss,
                    'take_profit': trade_data.take_profit
                }
            )
            
            return await self._send_alert(alert)
            
        except Exception as e:
            log.error(f"Failed to send trade entry alert: {e}")
            return False
    
    async def send_trade_exit_alert(self, symbol: str, side: str, quantity: int, 
                                    entry_price: float, exit_price: float, 
                                    pnl_dollars: float, pnl_percent: float,
                                    exit_reason: str, holding_time_minutes: int = 0,
                                    mode: str = "DEMO", trade_id: str = "") -> bool:
        """
        Send trade exit alert for position closure
        
        Args:
            symbol: Symbol that was traded
            side: "SELL" (closing position)
            quantity: Number of shares
            entry_price: Original entry price
            exit_price: Exit/sale price
            pnl_dollars: Profit/loss in dollars
            pnl_percent: Profit/loss percentage
            exit_reason: Reason for exit (TAKE_PROFIT, STEALTH_STOP, BREAKEVEN, etc.)
            holding_time_minutes: How long position was held
            mode: DEMO or LIVE
            trade_id: Original trade ID
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode-specific elements
            if mode == "DEMO":
                mode_emoji = "🎮"
                mode_title = "🎮 Demo Trade Closed"
                mode_text = "DEMO Mode"
            else:
                mode_emoji = "💰"
                mode_title = "💰 Live Trade Closed"
                mode_text = "LIVE Mode"
            
            # Exit reason emoji and description (Rev 00180 - Complete mapping)
            exit_reasons = {
                # Stealth Trailing Exit Reasons
                'STOP_LOSS': ('🚨', 'Stop Loss Hit'),
                'stop_loss': ('🚨', 'Stop Loss Hit'),
                'TAKE_PROFIT': ('🎯', 'Take Profit Target Reached'),
                'take_profit': ('🎯', 'Take Profit Target Reached'),
                'TRAILING_STOP': ('🛡️', 'Trailing Stop Hit'),
                'trailing_stop': ('🛡️', 'Trailing Stop Hit'),
                'STEALTH_STOP': ('🛡️', 'Stealth Trailing Stop Hit'),
                'BREAKEVEN_PROTECTION': ('⚖️', 'Breakeven Protection Triggered'),
                'breakeven_protection': ('⚖️', 'Breakeven Protection Triggered'),
                'BREAKEVEN': ('⚖️', 'Breakeven Protection Triggered'),
                'TIME_EXIT': ('⏰', 'Profit Timeout or Max Holding Time'),  # Will be overridden below if TIME_EXIT
                'time_exit': ('⏰', 'Profit Timeout or Max Holding Time'),  # Will be overridden below if time_exit
                'TIME_LIMIT': ('⏰', 'Maximum Holding Time Reached'),
                'VOLUME_EXIT': ('📊', 'Low Volume Exit'),
                'volume_exit': ('📊', 'Low Volume Exit'),
                'VOLUME_DECLINE': ('📊', 'Volume Decline Exit'),
                'MOMENTUM_EXIT': ('📉', 'RSI Momentum Loss'),
                'momentum_exit': ('📉', 'RSI Momentum Loss'),
                'RSI_MOMENTUM': ('📉', 'RSI Momentum Loss'),
                'GAP_RISK': ('⚠️', 'Gap Risk Detected'),
                'gap_risk': ('⚠️', 'Gap Risk Detected'),
                'SCALE_OUT_T1': ('💰', 'Partial Profit T1 (+3%)'),
                'scale_out_t1': ('💰', 'Partial Profit T1 (+3%)'),
                'SCALE_OUT_T2': ('💰', 'Partial Profit T2 (+7%)'),
                'scale_out_t2': ('💰', 'Partial Profit T2 (+7%)'),
                'REBALANCE': ('🔄', 'Adaptive Rebalancing'),
                'rebalance': ('🔄', 'Adaptive Rebalancing')
            }
            
            reason_emoji, reason_desc = exit_reasons.get(exit_reason, ('🔚', exit_reason))
            
            # Rev 00171: Distinguish between Profit Timeout and Max Holding Time for TIME_EXIT
            # Profit Timeout: >= 2.5 hours (150 min) AND >= +0.1% profit
            # Max Holding Time: >= 4.0 hours (240 min) with no protection
            if exit_reason in ('TIME_EXIT', 'time_exit'):
                if holding_time_minutes >= 240:  # 4.0 hours - Max Holding Time
                    reason_emoji = '⏰'
                    reason_desc = 'Max Holding Time Reached'
                elif holding_time_minutes >= 150 and pnl_percent >= 0.001:  # 2.5 hours AND +0.1% profit - Profit Timeout
                    reason_emoji = '⏰'
                    reason_desc = 'Profit Timeout'
                else:
                    # Fallback: Default to Max Holding Time (shouldn't happen, but safety)
                    reason_emoji = '⏰'
                    reason_desc = 'Max Holding Time Reached'
            
            # P&L emoji and color
            if pnl_percent > 0:
                pnl_emoji = "💰"
                pnl_sign = "+"
            else:
                pnl_emoji = "📉"
                pnl_sign = ""
            
            # Calculate holding time display
            if holding_time_minutes > 60:
                hours = holding_time_minutes // 60
                minutes = holding_time_minutes % 60
                holding_display = f"{hours}h {minutes}m"
            else:
                holding_display = f"{holding_time_minutes}m"
            
            # Calculate trade value
            exit_value = quantity * exit_price
            
            # Rev 00180AE: Build message in updated format with bold
            message = f"""====================================================================

📉 <b>POSITION CLOSED</b> | {mode} Mode

1) 🔰 <b>{pnl_sign}{pnl_percent:.2f}%</b> {pnl_sign}${abs(pnl_dollars):.2f}
          {quantity} {symbol} @ ${entry_price:.2f} • ${entry_price * quantity:.2f}
          <b>Entry:</b> ${entry_price:.2f} • <b>Exit:</b> ${exit_price:.2f}
          <b>Reason:</b> {reason_desc}
          
          <b>Holding Time:</b> {holding_display}
          <b>Trade ID:</b>
          {trade_id}

📊 Position closed by Stealth Trailing System
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"Trade exit alert sent for {symbol} - {reason_desc} - P&L: {pnl_sign}{pnl_percent:.2f}%")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending trade exit alert: {e}")
            return False
    
    async def send_aggregated_exit_alert(self, closed_positions: List[Dict[str, Any]], 
                                        exit_reason: str, mode: str = "DEMO") -> bool:
        """
        Send aggregated alert for multiple position closes (Rev 00076)
        
        Used for: EOD close, emergency exits, weak day exits
        
        Args:
            closed_positions: List of dicts with position data
            exit_reason: Common exit reason
            mode: DEMO or LIVE
        
        Returns:
            True if alert sent successfully
        """
        try:
            if not closed_positions:
                return False
            
            # Build message header
            message = f"""====================================================================

📉 <b>POSITIONS CLOSED</b> | {mode} Mode

"""
            
            # Add each position
            for i, pos in enumerate(closed_positions, 1):
                pnl_pct = pos['pnl_pct']
                pnl_dollars = pos['pnl']
                
                # P&L emoji and sign
                if pnl_pct > 0:
                    pnl_emoji = "💰"
                    pnl_sign = "+"
                else:
                    pnl_emoji = "📉"
                    pnl_sign = "-"
                
                # Calculate holding time display
                holding_minutes = pos.get('holding_time', 0)
                if holding_minutes > 60:
                    hours = holding_minutes // 60
                    minutes = holding_minutes % 60
                    holding_display = f"{hours}h {minutes}m"
                else:
                    holding_display = f"{holding_minutes}m"
                
                # Rev 00184: Format P&L with correct signs (include + for positive values)
                # Format percentage: show + for positive, - for negative
                if pnl_pct >= 0:
                    pnl_pct_str = f"+{pnl_pct:.2f}%"
                else:
                    pnl_pct_str = f"{pnl_pct:.2f}%"
                
                # Format dollars: show + for positive, - for negative
                if pnl_dollars >= 0:
                    pnl_dollars_str = f"+${pnl_dollars:.2f}"
                else:
                    pnl_dollars_str = f"-${abs(pnl_dollars):.2f}"
                
                message += f"""{i}) {pnl_emoji} <b>{pnl_pct_str}</b> {pnl_dollars_str}
          {pos['quantity']} {pos['symbol']} @ ${pos['entry_price']:.2f} • ${pos['quantity'] * pos['entry_price']:.2f}
          <b>Entry:</b> ${pos['entry_price']:.2f} • <b>Exit:</b> ${pos['exit_price']:.2f}
          <b>Reason:</b> {exit_reason}
          
          <b>Holding Time:</b> {holding_display}
          <b>Trade ID:</b>
          {pos.get('trade_id', 'N/A')}

"""
            
            message += f"📊 Positions closed by Stealth Trailing System"
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"Aggregated exit alert sent for {len(closed_positions)} positions - {exit_reason}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending aggregated exit alert: {e}")
            return False
    
    async def send_end_of_day_report(self, daily_stats: Dict[str, Any], weekly_stats: Dict[str, Any], 
                                    active_positions: int = 0, mode: str = "DEMO", 
                                    account_balance: float = 0.0, starting_balance: float = 1000.0,
                                    all_time_stats: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send unified End of Day report for both Demo and Live modes
        
        Args:
            daily_stats: Today's trading statistics
            weekly_stats: This week's trading statistics  
            active_positions: Number of currently open positions
            mode: "DEMO" or "LIVE"
            account_balance: Current account balance (for % calculation)
            starting_balance: Starting balance for % calculation
        """
        try:
            # Calculate stats
            daily_closed = daily_stats.get('positions_closed', 0)
            daily_wins = daily_stats.get('winning_trades', 0)
            daily_losses = daily_stats.get('losing_trades', 0)
            daily_pnl = daily_stats.get('total_pnl', 0.0)
            daily_best = daily_stats.get('best_trade', 0.0)
            daily_worst = daily_stats.get('worst_trade', 0.0)
            
            weekly_closed = weekly_stats.get('positions_closed', 0)
            weekly_wins = weekly_stats.get('winning_trades', 0)
            weekly_losses = weekly_stats.get('losing_trades', 0)
            weekly_pnl = weekly_stats.get('total_pnl', 0.0)
            
            # Calculate rates
            daily_win_rate = (daily_wins / daily_closed * 100) if daily_closed > 0 else 0.0
            weekly_win_rate = (weekly_wins / weekly_closed * 100) if weekly_closed > 0 else 0.0
            
            # Calculate P&L percentages
            daily_pnl_pct = (daily_pnl / starting_balance * 100) if starting_balance > 0 else 0.0
            weekly_pnl_pct = (weekly_pnl / starting_balance * 100) if starting_balance > 0 else 0.0
            
            # Format P&L
            daily_pnl_sign = "+" if daily_pnl >= 0 else ""
            weekly_pnl_sign = "+" if weekly_pnl >= 0 else ""
            
            # Rev 00135: Calculate profit factors from actual trade data (passed in stats)
            # Profit factor = sum of all wins / sum of all losses (absolute values)
            
            # Daily profit factor: Use actual wins/losses sums if available
            daily_total_wins = daily_stats.get('total_wins_sum', None)
            daily_total_losses = daily_stats.get('total_losses_sum', None)
            
            # If not provided, calculate from stats (fallback)
            if daily_total_wins is None or daily_total_losses is None:
                if daily_wins > 0 and daily_losses > 0:
                    # Estimate from average win/loss
                    avg_win = (daily_pnl / daily_wins) if daily_wins > 0 else 0.0
                    avg_loss = abs(daily_stats.get('worst_trade', 0.0)) if daily_losses > 0 and daily_stats.get('worst_trade', 0.0) < 0 else 0.0
                    if avg_loss == 0.0 and daily_losses > 0:
                        estimated_wins_sum = avg_win * daily_wins
                        avg_loss = abs((daily_pnl - estimated_wins_sum) / daily_losses) if daily_losses > 0 else 0.0
                    daily_total_wins = avg_win * daily_wins if daily_wins > 0 else 0.0
                    daily_total_losses = avg_loss * daily_losses if daily_losses > 0 else 0.0
                elif daily_wins > 0:
                    daily_total_wins = daily_pnl
                    daily_total_losses = 0.0
                elif daily_losses > 0:
                    daily_total_wins = 0.0
                    daily_total_losses = abs(daily_pnl)
                else:
                    daily_total_wins = 0.0
                    daily_total_losses = 0.0
            
            profit_factor = (daily_total_wins / daily_total_losses) if daily_total_losses > 0 else (daily_total_wins if daily_total_wins > 0 else (float('inf') if daily_total_wins > 0 and daily_total_losses == 0 else 0.0))
            
            # Weekly profit factor: Use actual wins/losses sums if available
            weekly_total_wins = weekly_stats.get('total_wins_sum', None)
            weekly_total_losses = weekly_stats.get('total_losses_sum', None)
            
            # If not provided, calculate from stats (fallback)
            if weekly_total_wins is None or weekly_total_losses is None:
                if weekly_wins > 0 and weekly_losses > 0:
                    weekly_avg_win = (weekly_pnl / weekly_wins) if weekly_wins > 0 else 0.0
                    estimated_wins_sum = weekly_avg_win * weekly_wins
                    weekly_avg_loss = abs((weekly_pnl - estimated_wins_sum) / weekly_losses) if weekly_losses > 0 else 0.0
                    weekly_total_wins = weekly_avg_win * weekly_wins
                    weekly_total_losses = weekly_avg_loss * weekly_losses
                elif weekly_wins > 0:
                    weekly_total_wins = weekly_pnl
                    weekly_total_losses = 0.0
                elif weekly_losses > 0:
                    weekly_total_wins = 0.0
                    weekly_total_losses = abs(weekly_pnl)
                else:
                    weekly_total_wins = 0.0
                    weekly_total_losses = 0.0
            
            weekly_profit_factor = (weekly_total_wins / weekly_total_losses) if weekly_total_losses > 0 else (weekly_total_wins if weekly_total_wins > 0 else (float('inf') if weekly_total_wins > 0 and weekly_total_losses == 0 else 0.0))
            
            # All-time stats (Rev 00135)
            all_time_total_trades = 0
            all_time_wins = 0
            all_time_losses = 0
            all_time_pnl = 0.0
            all_time_profit_factor = 0.0
            all_time_pnl_pct = 0.0
            
            if all_time_stats:
                all_time_total_trades = all_time_stats.get('total_trades', 0)
                all_time_wins = all_time_stats.get('winning_trades', 0)
                all_time_losses = all_time_stats.get('losing_trades', 0)
                all_time_pnl = all_time_stats.get('total_pnl', 0.0)
                
                # Rev 00135: Calculate all-time profit factor from actual trade data
                if all_time_total_trades > 0:
                    # Use actual wins/losses sums if available (more accurate)
                    all_time_wins_sum = all_time_stats.get('total_wins_sum', 0.0)
                    all_time_losses_sum = all_time_stats.get('total_losses_sum', 0.0)
                    
                    if all_time_wins_sum > 0 and all_time_losses_sum > 0:
                        # Have both wins and losses - use actual sums
                        all_time_profit_factor = all_time_wins_sum / all_time_losses_sum
                    elif all_time_wins_sum > 0 and all_time_losses_sum == 0:
                        # All wins - infinite profit factor
                        all_time_profit_factor = float('inf')
                    elif all_time_wins_sum == 0 and all_time_losses_sum > 0:
                        # All losses
                        all_time_profit_factor = 0.0
                    else:
                        # Fallback to estimation method
                        if all_time_wins > 0 and all_time_losses > 0:
                            all_time_avg_win = (all_time_pnl / all_time_wins) if all_time_wins > 0 else 0.0
                            estimated_wins_sum = all_time_avg_win * all_time_wins
                            all_time_avg_loss = abs((all_time_pnl - estimated_wins_sum) / all_time_losses) if all_time_losses > 0 else 0.0
                            all_time_total_wins_sum = all_time_avg_win * all_time_wins
                            all_time_total_losses_sum = all_time_avg_loss * all_time_losses
                            all_time_profit_factor = (all_time_total_wins_sum / all_time_total_losses_sum) if all_time_total_losses_sum > 0 else 0.0
                        elif all_time_wins > 0:
                            all_time_profit_factor = float('inf')
                        else:
                            all_time_profit_factor = 0.0
                
                # Calculate all-time P&L percentage
                all_time_pnl_pct = (all_time_pnl / starting_balance * 100) if starting_balance > 0 else 0.0
            
            all_time_win_rate = (all_time_wins / all_time_total_trades * 100) if all_time_total_trades > 0 else 0.0
            all_time_pnl_sign = "+" if all_time_pnl >= 0 else ""
            
            # Rev 00183: Calculate worst trade sign for formatting
            daily_worst_sign = "-" if daily_worst < 0 else "+"
            
            # Rev 00183: Calculate actual account balance (starting + total P&L)
            actual_account_balance = starting_balance + all_time_pnl
            
            # Get current date
            report_date = datetime.utcnow().strftime('%Y-%m-%d')  # Rev 00075: UTC consistency
            
            # Rev 00135: Calculate averages for display
            # Rev 00183: Fix average calculations - use actual wins/losses sums
            avg_win = (daily_total_wins / daily_wins) if daily_wins > 0 else 0.0
            avg_loss = -(daily_total_losses / daily_losses) if daily_losses > 0 else 0.0  # Rev 00183: Negative for losses
            
            # Format profit factors (handle infinity)
            daily_pf_str = f"{profit_factor:.2f}" if profit_factor != float('inf') else "∞"
            weekly_pf_str = f"{weekly_profit_factor:.2f}" if weekly_profit_factor != float('inf') else "∞"
            all_time_pf_str = f"{all_time_profit_factor:.2f}" if all_time_profit_factor != float('inf') else "∞"
            
            # Build message (Rev 00135: Updated format with All Time stats)
            message = f"""====================================================================

🛃 <b>END-OF-DAY REPORT</b> | {mode} Mode

📈 <b>P&L (TODAY):</b>
          <b>{daily_pnl_sign}{daily_pnl_pct:.2f}%</b> {daily_pnl_sign}${daily_pnl:.2f}
          Win Rate: {daily_win_rate:.1f}% • Total Trades: {daily_closed}
          Wins: {daily_wins} • Losses: {daily_losses}
          Profit Factor: {daily_pf_str}
          Average Win: ${avg_win:.2f}
          Average Loss: ${avg_loss:.2f}
          Best Trade: {daily_pnl_sign}${daily_best:.2f}
          Worst Trade: {daily_worst_sign}${abs(daily_worst):.2f}

🎖️ <b>P&L (WEEK M-F):</b>
          <b>{weekly_pnl_sign}{weekly_pnl_pct:.2f}%</b> {weekly_pnl_sign}${weekly_pnl:.2f}
          Win Rate: {weekly_win_rate:.1f}% • Total Trades: {weekly_closed}
          Profit Factor: {weekly_pf_str}

💎 <b>Account Balances (All Time):</b>
          <b>{all_time_pnl_sign}{all_time_pnl_pct:.2f}%</b> {all_time_pnl_sign}${all_time_pnl:.2f}
          <b>${actual_account_balance:,.2f}</b>
          Win Rate: {all_time_win_rate:.1f}% • Total Trades: {all_time_total_trades}
          Profit Factor: {all_time_pf_str}
          Wins: {all_time_wins} • Losses: {all_time_losses}

📅 Report Date: {report_date}
"""
            
            # Send via Telegram
            success = await self._send_telegram_message(message, AlertLevel.INFO)
            
            if success:
                log.info(f"{mode} Mode EOD Report sent - Daily: {daily_pnl_sign}${daily_pnl:.2f} ({daily_pnl_sign}{daily_pnl_pct:.2f}%), Weekly: {weekly_pnl_sign}${weekly_pnl:.2f} ({weekly_pnl_sign}{weekly_pnl_pct:.2f}%)")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending EOD report: {e}")
            return False
    
    # ============================================================================================================================================
    # PERFORMANCE ALERTS
    # ============================================================================================================================================
    
    async def send_performance_alert(self, performance_data: Dict[str, Any]) -> bool:
        """Send performance update alert"""
        try:
            alert = Alert(
                alert_id=f"performance_{int(time.time())}",
                alert_type=AlertType.PERFORMANCE_UPDATE,
                level=AlertLevel.INFO,
                title="📊 Performance Update",
                message=self._format_performance_message(performance_data),
                metadata=performance_data
            )
            
            return await self._send_alert(alert)
            
        except Exception as e:
            log.error(f"Failed to send performance alert: {e}")
            return False
    
    # ARCHIVED (Rev 00047): Old EOD summary method replaced by unified send_end_of_day_report()
    # This method used old format (📊) without weekly stats
    # New unified method (line 454) uses 🛃 and includes weekly performance
    # async def send_end_of_day_summary(self, summary: PerformanceSummary) -> bool:
    #     """ARCHIVED: Old end-of-day summary (replaced by unified report)"""
    #     pass
    
    # ============================================================================================================================================
    # SYSTEM ALERTS
    # ============================================================================================================================================
    
    async def send_system_alert(self, title: str, message: str, level: AlertLevel = AlertLevel.INFO) -> bool:
        """Send system alert"""
        try:
            alert = Alert(
                alert_id=f"system_{int(time.time())}",
                alert_type=AlertType.SYSTEM_STATUS,
                level=level,
                title=title,
                message=message,
                metadata={'timestamp': datetime.now().isoformat()}
            )
            
            return await self._send_alert(alert)
            
        except Exception as e:
            log.error(f"Failed to send system alert: {e}")
            return False
    
    async def send_error_alert(self, error_message: str, error_type: str = "General Error") -> bool:
        """Send error alert"""
        try:
            alert = Alert(
                alert_id=f"error_{int(time.time())}",
                alert_type=AlertType.ERROR,
                level=AlertLevel.ERROR,
                title="🚨 System Error",
                message=f"**{error_type}**\n\n{error_message}",
                metadata={'error_type': error_type, 'timestamp': datetime.now().isoformat()}
            )
            
            return await self._send_alert(alert)
            
        except Exception as e:
            log.error(f"Failed to send error alert: {e}")
            return False
    
    async def send_warning_alert(self, warning_message: str, warning_type: str = "General Warning") -> bool:
        """Send warning alert"""
        try:
            alert = Alert(
                alert_id=f"warning_{int(time.time())}",
                alert_type=AlertType.WARNING,
                level=AlertLevel.WARNING,
                title="⚠️ System Warning",
                message=f"**{warning_type}**\n\n{warning_message}",
                metadata={'warning_type': warning_type, 'timestamp': datetime.now().isoformat()}
            )
            
            return await self._send_alert(alert)
            
        except Exception as e:
            log.error(f"Failed to send warning alert: {e}")
            return False
    
    # ============================================================================================================================================
    # CORE ALERT SENDING
    # ============================================================================================================================================
    
    async def _send_alert(self, alert: Alert) -> bool:
        """Send alert via configured channels"""
        try:
            # Check if alert level is enabled
            if not self.alert_levels_enabled.get(alert.level, False):
                return False
            
            # Check throttling
            if not self._check_alert_throttling(alert):
                return False
            
            # Send via Telegram if enabled
            if self.telegram_enabled:
                success = await self._send_telegram_alert(alert)
                if success:
                    self._track_alert(alert)
                    return True
            
            # Log alert if no other channels available
            log.info(f"Alert: {alert.title} - {alert.message}")
            self._track_alert(alert)
            return True
            
        except Exception as e:
            log.error(f"Failed to send alert: {e}")
            return False
    
    async def _send_telegram_alert(self, alert: Alert) -> bool:
        """Send alert via Telegram"""
        try:
            if not self.telegram_bot_token or not self.telegram_chat_id:
                return False
            
            # Format message
            message = self._format_telegram_message(alert)
            
            # Send to Telegram
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    log.debug(f"Telegram alert sent: {alert.alert_id}")
                    return True
                else:
                    log.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
            else:
                log.error(f"Telegram HTTP error: {response.status_code}")
            
            return False
            
        except Exception as e:
            log.error(f"Failed to send Telegram alert: {e}")
            return False
    
    async def _send_telegram_message(self, message: str, level: AlertLevel = AlertLevel.INFO) -> bool:
        """Send raw message via Telegram (Rev 00184: Auto-fallback to plain text on HTML errors)"""
        try:
            # CRITICAL DEBUG: Log every telegram message attempt
            log.info(f"🔍🔍🔍 _send_telegram_message CALLED - Message preview: {message[:100]}...")
            
            if not self.telegram_bot_token or not self.telegram_chat_id:
                log.info("🔍🔍🔍 No Telegram credentials, returning False")
                return False
            
            # Send to Telegram
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            
            # Rev 00184: Try HTML first, then fallback to plain text if HTML fails
            data = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    log.debug(f"Telegram message sent successfully")
                    return True
                else:
                    error_desc = result.get('description', 'Unknown error')
                    log.error(f"Telegram API error: {error_desc}")
                    
                    # Rev 00184: If HTML parse error, retry with plain text
                    if 'parse' in error_desc.lower() or 'html' in error_desc.lower() or response.status_code == 400:
                        log.warning(f"⚠️ HTML parse error detected, retrying with plain text mode")
                        data_plain = {
                            'chat_id': self.telegram_chat_id,
                            'text': message,
                            'disable_web_page_preview': True
                            # No parse_mode = plain text
                        }
                        response_plain = requests.post(url, json=data_plain, timeout=10)
                        if response_plain.status_code == 200:
                            result_plain = response_plain.json()
                            if result_plain.get('ok'):
                                log.info("✅ Telegram message sent successfully (plain text fallback)")
                                return True
                            else:
                                log.error(f"Telegram API error (plain text): {result_plain.get('description', 'Unknown error')}")
                        else:
                            log.error(f"Telegram HTTP error (plain text): {response_plain.status_code}")
            else:
                log.error(f"Telegram HTTP error: {response.status_code}")
                # Rev 00184: Try plain text on HTTP errors too
                if response.status_code == 400:
                    log.warning(f"⚠️ HTTP 400 error, retrying with plain text mode")
                    data_plain = {
                        'chat_id': self.telegram_chat_id,
                        'text': message,
                        'disable_web_page_preview': True
                    }
                    response_plain = requests.post(url, json=data_plain, timeout=10)
                    if response_plain.status_code == 200:
                        result_plain = response_plain.json()
                        if result_plain.get('ok'):
                            log.info("✅ Telegram message sent successfully (plain text fallback)")
                            return True
            
            return False
            
        except Exception as e:
            log.error(f"Failed to send Telegram message: {e}")
            return False
    
    # ============================================================================================================================================
    # MESSAGE FORMATTING
    # ============================================================================================================================================
    
    def _format_telegram_message(self, alert: Alert) -> str:
        """Format alert for Telegram"""
        emoji_map = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "🚨",
            AlertLevel.CRITICAL: "🔥",
            AlertLevel.SUCCESS: "✅"
        }
        
        emoji = emoji_map.get(alert.level, "📢")
        timestamp = alert.timestamp.strftime("%H:%M:%S")
        
        message = f"{emoji} **{alert.title}**\n"
        message += f"🕐 {timestamp}\n\n"
        
        if alert.symbol:
            message += f"📈 **Symbol:** {alert.symbol}\n"
        
        if alert.strategy:
            message += f"🎯 **Strategy:** {alert.strategy}\n"
        
        if alert.confidence:
            message += f"🎲 **Confidence:** {alert.confidence:.1%}\n"
        
        if alert.expected_return:
            message += f"💰 **Expected Return:** {alert.expected_return:.2%}\n"
        
        message += f"\n{alert.message}"
        
        return message
    
    def _format_trade_signal_message(self, signal_data: Dict[str, Any]) -> str:
        """Format trade signal message"""
        symbol = signal_data.get('symbol', 'Unknown')
        strategy = signal_data.get('strategy', 'Unknown')
        confidence = signal_data.get('confidence', 0)
        expected_return = signal_data.get('expected_return', 0)
        entry_price = signal_data.get('entry_price', 0)
        
        message = f"**{symbol}** - {strategy} Strategy\n"
        message += f"🎯 **Entry Price:** ${entry_price:.2f}\n"
        message += f"🎲 **Confidence:** {confidence:.1%}\n"
        message += f"💰 **Expected Return:** {expected_return:.2%}\n"
        
        if signal_data.get('stop_loss'):
            message += f"🛑 **Stop Loss:** ${signal_data['stop_loss']:.2f}\n"
        
        if signal_data.get('take_profit'):
            message += f"🎯 **Take Profit:** ${signal_data['take_profit']:.2f}\n"
        
        return message
    
    def _format_trade_entry_message(self, trade_data: TradeAlert) -> str:
        """Format trade entry message"""
        message = f"**{trade_data.symbol}** - {trade_data.strategy}\n"
        message += f"✅ **{trade_data.action}** {trade_data.quantity} shares @ ${trade_data.price:.2f}\n"
        message += f"🎲 **Confidence:** {trade_data.confidence:.1%}\n"
        message += f"💰 **Expected Return:** {trade_data.expected_return:.2%}\n"
        
        if trade_data.stop_loss:
            message += f"🛑 **Stop Loss:** ${trade_data.stop_loss:.2f}\n"
        
        if trade_data.take_profit:
            message += f"🎯 **Take Profit:** ${trade_data.take_profit:.2f}\n"
        
        if trade_data.reason:
            message += f"📝 **Reason:** {trade_data.reason}\n"
        
        return message
    
    def _format_trade_exit_message(self, trade_data: TradeAlert, pnl_pct: float) -> str:
        """Format trade exit message"""
        pnl_emoji = "💰" if pnl_pct > 0 else "📉"
        
        message = f"**{trade_data.symbol}** - {trade_data.strategy}\n"
        message += f"🔚 **{trade_data.action}** {trade_data.quantity} shares @ ${trade_data.price:.2f}\n"
        message += f"{pnl_emoji} **P&L:** {pnl_pct:+.2f}%\n"
        
        if trade_data.reason:
            message += f"📝 **Reason:** {trade_data.reason}\n"
        
        return message
    
    def _format_performance_message(self, performance_data: Dict[str, Any]) -> str:
        """Format performance update message"""
        message = f"📊 **Performance Update**\n\n"
        
        if 'win_rate' in performance_data:
            message += f"🎯 **Win Rate:** {performance_data['win_rate']:.1%}\n"
        
        if 'total_pnl' in performance_data:
            message += f"💰 **Total P&L:** {performance_data['total_pnl']:.2%}\n"
        
        if 'active_positions' in performance_data:
            message += f"📈 **Active Positions:** {performance_data['active_positions']}\n"
        
        if 'daily_return' in performance_data:
            message += f"📅 **Daily Return:** {performance_data['daily_return']:.2%}\n"
        
        return message
    
    # ARCHIVED (Rev 00047): Old formatting method for archived send_end_of_day_summary()
    def _format_end_of_day_message(self, summary: PerformanceSummary) -> str:
        """ARCHIVED: Format end-of-day summary message (replaced by unified report format)"""
        # Determine performance emojis and status
        pnl_emoji = "✅" if summary.total_pnl > 0 else "📉"
        return_emoji = "📈" if summary.daily_return > 0 else "📉"
        
        # Calculate additional metrics
        avg_gain_per_trade = summary.total_pnl / summary.total_trades if summary.total_trades > 0 else 0
        max_drawdown = getattr(summary, 'max_drawdown', 0.0)
        capital_used_pct = getattr(summary, 'capital_used_pct', 0.0)
        consecutive_wins = getattr(summary, 'consecutive_wins', 0)
        
        # Calculate total P&L in dollars (approximate)
        total_pnl_dollars = getattr(summary, 'total_pnl_dollars', summary.total_pnl * 1000)  # Rough estimate
        
        message = f"⚖️ End of Day Trade Report\n"
        message += f"💹🛅 • Date: {summary.date.strftime('%Y-%m-%d')}\n\n"
        
        message += f"{pnl_emoji} {summary.total_pnl:+.2f}% ${total_pnl_dollars:+,.2f}\n"
        message += f"📈 • Total Trades: {summary.total_trades}\n"
        message += f"      • Win Rate: {summary.win_rate:.1%}\n"
        message += f"      • Max Drawdown: {max_drawdown:+.1f}%\n\n"
        
        # Highlights section
        message += f"⚡ Highlights\n"
        if consecutive_wins >= 3:
            message += f"🔰 Win streak: {consecutive_wins} consecutive wins\n"
        if summary.top_performers:
            best_trade = summary.top_performers[0]
            best_symbol = best_trade.get('symbol', 'N/A')
            best_return = best_trade.get('return', 0)
            message += f"👑 Biggest gain: {best_return:+.1f}% on {best_symbol}\n"
        message += "\n"
        
        # Risk metrics
        message += f"🛡 Risk Metrics\n"
        message += f"      • Capital Used: {capital_used_pct:.0f}%\n"
        message += f"      • Avg Gain per Trade: {avg_gain_per_trade:+.1f}%\n"
        message += f"      • Avg Risk per Trade: {getattr(summary, 'avg_risk_per_trade', 4.2):.1f}%\n\n"
        
        # Best and worst trades with detailed breakdown
        if summary.top_performers:
            best_trade = summary.top_performers[0]
            message += f"📈 Best Trade\n"
            message += f"👑 {best_trade.get('symbol', 'N/A')} ({best_trade.get('side', 'LONG')}) — "
            message += f"{best_trade.get('return', 0):+.1f}% ${best_trade.get('pnl_dollars', 0):+.2f} • "
            message += f"Duration: {best_trade.get('duration', 'N/A')}\n"
            message += f"      • Entry: {best_trade.get('entry_price', 'N/A')} @ {best_trade.get('entry_time', 'N/A')}\n"
            message += f"      • Exit: {best_trade.get('exit_price', 'N/A')} @ {best_trade.get('exit_time', 'N/A')}\n"
            message += f"      • Entry Reason: {best_trade.get('entry_reason', 'N/A')}\n"
            message += f"      • Exit Reason: {best_trade.get('exit_reason', 'N/A')}\n\n"
        
        if summary.worst_performers:
            worst_trade = summary.worst_performers[0]
            message += f"💢 Worst Trade\n"
            message += f"📛 {worst_trade.get('symbol', 'N/A')} ({worst_trade.get('side', 'SHORT')}) — "
            message += f"{worst_trade.get('return', 0):+.1f}% ${worst_trade.get('pnl_dollars', 0):+.2f} • "
            message += f"Duration: {worst_trade.get('duration', 'N/A')}\n"
            message += f"      • Entry: {worst_trade.get('entry_price', 'N/A')} @ {worst_trade.get('entry_time', 'N/A')}\n"
            message += f"      • Exit: {worst_trade.get('exit_price', 'N/A')} @ {worst_trade.get('exit_time', 'N/A')}\n"
            message += f"      • Entry Reason: {worst_trade.get('entry_reason', 'N/A')}\n"
            message += f"      • Exit Reason: {worst_trade.get('exit_reason', 'N/A')}\n\n"
        
        # Summary
        message += f"✨ Summary\n"
        if summary.win_rate >= 0.8:
            message += f"📈 Strong execution with disciplined risk. "
        elif summary.win_rate >= 0.6:
            message += f"📊 Solid performance with room for optimization. "
        else:
            message += f"⚠️ Challenging session - reviewing strategy. "
        
        if summary.total_pnl > 2.0:
            message += f"Momentum signals lined up with sentiment confluence."
        elif summary.total_pnl > 0:
            message += f"Positive day with controlled risk management."
        else:
            message += f"Risk management prevented larger losses."
        
        return message
    
    # ============================================================================================================================================
    # END OF DAY SCHEDULING
    # ============================================================================================================================================
    
    def start_end_of_day_scheduler(self):
        """Start the end-of-day summary scheduler"""
        if self.scheduler_running:
            log.warning("End-of-day scheduler is already running")
            return
        
        self.scheduler_running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        log.info("End-of-day scheduler started - will send summary at 4:05 PM ET (5 min after market close)")
    
    def stop_end_of_day_scheduler(self):
        """Stop the end-of-day summary scheduler"""
        self.scheduler_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        log.info("End-of-day scheduler stopped")
    
    def _run_scheduler(self):
        """Run the scheduler in a background thread"""
        while self.scheduler_running:
            # Get current time in Eastern Time (market timezone)
            from zoneinfo import ZoneInfo
            et_tz = ZoneInfo('America/New_York')
            current_time = datetime.now(et_tz)
            
            # Check if it's EOD report time (4:05 PM ET - 5 min buffer after market close)
            # Rev 00180AE: Delayed from 4:00 PM to ensure all closing trades are processed
            if current_time.hour == 16 and current_time.minute == 5:
                # CRITICAL: Only send EOD on trading days (not weekends/holidays)
                today = current_time.date()
                
                # Check if it's a trading day
                if today.weekday() >= 5:  # Saturday=5, Sunday=6
                    log.info(f"📅 Weekend detected - skipping EOD report")
                    time.sleep(60)
                    continue
                
                # Check if we haven't sent today's summary yet
                last_summary_date = getattr(self, '_last_summary_date', None)
                
                if last_summary_date != today:
                    self._send_scheduled_end_of_day_summary()
                    self._last_summary_date = today
            
            time.sleep(60)  # Check every minute
    
    def _send_scheduled_end_of_day_summary(self):
        """Send the scheduled end-of-day summary"""
        try:
            log.info("Generating scheduled end-of-day summary")
            
            # Check if we're in Demo Mode
            demo_mode = get_config_value('TRADING_MODE', 'demo').lower() in ['demo', 'demo_mode']
            
            if demo_mode and hasattr(self, '_mock_executor') and self._mock_executor:
                # Generate Demo Mode EOD report
                asyncio.run(self._send_demo_eod_summary())
            elif hasattr(self, '_unified_trade_manager') and self._unified_trade_manager:
                # Generate Live Mode EOD report (Rev 00180AE)
                asyncio.run(self._send_live_eod_summary())
            else:
                # ARCHIVED (Rev 00047): Fallback EOD removed
                # Internal scheduler is now disabled - Cloud Scheduler handles all EOD reports
                log.warning("⚠️ Internal EOD scheduler triggered but is DISABLED - Cloud Scheduler handles EOD")
                log.warning("   If you see this, the internal scheduler was not properly stopped")
            
            log.info("Scheduled end-of-day processing complete (internal scheduler disabled)")
            
        except Exception as e:
            log.error(f"Failed to send scheduled end-of-day summary: {e}")
    
    async def _send_demo_eod_summary(self):
        """Send Demo Mode end-of-day summary (with GCS-based deduplication - Rev 00180AD)"""
        try:
            # Rev 00047: Enhanced validation and logging
            if not hasattr(self, '_mock_executor'):
                log.error("❌ CRITICAL: _mock_executor attribute not set on alert_manager!")
                log.error("   This means trading_system did not set the reference during initialization")
                return
            
            if not self._mock_executor:
                log.error("❌ CRITICAL: _mock_executor is None!")
                log.error("   Mock executor was set but is null - check trading_system initialization")
                return
            
            log.info(f"✅ Mock executor available for EOD (instance: {id(self._mock_executor)})")
            
            # DEDUPLICATION: Check if EOD report already sent today (Rev 00180AD - GCS-based)
            # This prevents duplicate reports across Cloud Run instances
            # Rev 00047: Date-based marker (internal scheduler disabled, so no blocking)
            # Ensures only ONE EOD report per day, even if Cloud Scheduler retries
            today = datetime.utcnow().strftime('%Y-%m-%d')  # Rev 00075: UTC consistency
            eod_sent_key = f"eod_sent_{today}_unified"  # One per day
            
            # Try GCS-based deduplication first (works across all instances)
            try:
                from .gcs_persistence import get_gcs_persistence
                gcs = get_gcs_persistence()
                
                # Check if marker file exists in GCS (one per day)
                gcs_marker_path = f"eod_markers/{eod_sent_key}.txt"
                
                # Try to download marker (if exists, report already sent today)
                if gcs.file_exists(gcs_marker_path):
                    log.info(f"✅ EOD report already sent today ({today}) - only ONE report per day, skipping duplicate")
                    return
                
                # Upload marker file to GCS (atomic operation prevents race conditions)
                marker_content = datetime.now().isoformat()
                gcs.upload_string(gcs_marker_path, marker_content)
                log.info(f"📝 Created GCS EOD marker for {today}")
                
            except Exception as gcs_error:
                log.warning(f"GCS deduplication failed (non-critical): {gcs_error}")
                # Fall back to class-level cache (works within same instance)
                if not hasattr(self.__class__, '_eod_sent_cache'):
                    self.__class__._eod_sent_cache = {}
                
                if eod_sent_key in self.__class__._eod_sent_cache:
                    log.info(f"EOD report already sent today ({today}) - skipping duplicate (class cache)")
                    return
                
                # Mark as sent in class cache
                self.__class__._eod_sent_cache[eod_sent_key] = datetime.utcnow()  # Rev 00075: UTC consistency
            
            # Rev 00180AE: Use unified EOD report function (centralized in alert_manager)
            # DIAGNOSTIC (Rev 00180AE): Check mock executor state before reading stats
            log.info(f"📊 EOD DIAGNOSTIC: Mock executor instance: {id(self._mock_executor)}")
            log.info(f"📊 EOD DIAGNOSTIC: Active trades: {len(self._mock_executor.active_trades)}")
            log.info(f"📊 EOD DIAGNOSTIC: Closed trades: {len(self._mock_executor.closed_trades)}")
            log.info(f"📊 EOD DIAGNOSTIC: Daily stats raw: {self._mock_executor.daily_stats}")
            log.info(f"📊 EOD DIAGNOSTIC: Weekly stats raw: {self._mock_executor.weekly_stats}")
            log.info(f"📊 EOD DIAGNOSTIC: Account balance: ${self._mock_executor.account_balance:,.2f}")
            
            # Rev 00153: Validate stats consistency before reading (early detection)
            today = datetime.utcnow().date()
            today_trades_count = sum(1 for trade in self._mock_executor.closed_trades 
                                    if trade.exit_timestamp and trade.exit_timestamp.date() == today)
            stats_count = self._mock_executor.daily_stats.get('positions_closed', 0)
            if today_trades_count > 0 and stats_count != today_trades_count:
                log.warning(f"⚠️ EOD VALIDATION: Discrepancy detected before report - stats: {stats_count}, actual: {today_trades_count}")
                log.warning(f"   Will be fixed in recovery logic below")
            
            # Rev 00135: Calculate profit factors from actual trade data
            today = datetime.utcnow().date()
            current_week_start = datetime.utcnow().date()
            days_since_monday = current_week_start.weekday()
            monday = current_week_start - timedelta(days=days_since_monday)
            
            # Calculate daily profit factor from today's trades
            daily_total_wins = 0.0
            daily_total_losses = 0.0
            for trade in self._mock_executor.closed_trades:
                if trade.exit_timestamp and trade.exit_timestamp.date() == today:
                    if trade.pnl > 0:
                        daily_total_wins += trade.pnl
                    else:
                        daily_total_losses += abs(trade.pnl)
            
            # Calculate weekly profit factor from this week's trades
            weekly_total_wins = 0.0
            weekly_total_losses = 0.0
            weekly_trades = []  # Rev 00223: Collect all weekly trades for accurate calculation
            for trade in self._mock_executor.closed_trades:
                if trade.exit_timestamp and trade.exit_timestamp.date() >= monday:
                    weekly_trades.append(trade)
                    if trade.pnl > 0:
                        weekly_total_wins += trade.pnl
                    else:
                        weekly_total_losses += abs(trade.pnl)
            
            # Get stats from mock executor
            daily_stats = {
                'positions_closed': self._mock_executor.daily_stats['positions_closed'],
                'winning_trades': self._mock_executor.daily_stats['winning_trades'],
                'losing_trades': self._mock_executor.daily_stats['losing_trades'],
                'total_pnl': self._mock_executor.daily_stats['total_pnl'],
                'best_trade': self._mock_executor.daily_stats['best_trade'],
                'worst_trade': self._mock_executor.daily_stats['worst_trade'],
                'best_symbol': 'N/A',  # TODO: Track symbols
                'worst_symbol': 'N/A',
                'total_wins_sum': daily_total_wins,  # Rev 00135: For accurate profit factor
                'total_losses_sum': daily_total_losses  # Rev 00135: For accurate profit factor
            }
            
            # Rev 00223: Calculate weekly stats from closed_trades (source of truth) instead of weekly_stats
            # This ensures weekly stats include ALL trades from the week, even after deployments
            weekly_total_pnl = sum(t.pnl for t in weekly_trades)
            weekly_winning_trades = sum(1 for t in weekly_trades if t.pnl > 0)
            weekly_losing_trades = sum(1 for t in weekly_trades if t.pnl <= 0)
            weekly_best_trade = max((t.pnl for t in weekly_trades), default=0.0)
            weekly_worst_trade = min((t.pnl for t in weekly_trades), default=0.0)
            
            # Get weekly stats from closed_trades (Rev 00223: Calculate from source of truth)
            weekly_stats = {
                'positions_closed': len(weekly_trades),  # Rev 00223: Count from closed_trades
                'winning_trades': weekly_winning_trades,  # Rev 00223: Calculated from closed_trades
                'losing_trades': weekly_losing_trades,  # Rev 00223: Calculated from closed_trades
                'total_pnl': weekly_total_pnl,  # Rev 00223: Calculated from closed_trades
                'total_wins_sum': weekly_total_wins,  # Rev 00135: For accurate profit factor
                'total_losses_sum': weekly_total_losses  # Rev 00135: For accurate profit factor
            }
            
            # Rev 00223: Log if discrepancy found between executor weekly_stats and calculated
            if (self._mock_executor.weekly_stats.get('positions_closed', 0) != len(weekly_trades) or
                abs(self._mock_executor.weekly_stats.get('total_pnl', 0.0) - weekly_total_pnl) > 0.01):
                log.warning(f"⚠️ EOD WEEKLY STATS DISCREPANCY: Executor weekly_stats (trades={self._mock_executor.weekly_stats.get('positions_closed', 0)}, P&L=${self._mock_executor.weekly_stats.get('total_pnl', 0.0):.2f}) != closed_trades (count={len(weekly_trades)}, P&L=${weekly_total_pnl:.2f})")
                log.warning(f"   Using closed_trades as source of truth for weekly stats (ensures persistence)")
            
            # DIAGNOSTIC (Rev 00180AE): Validate stats before sending
            total_trades_today = daily_stats.get('positions_closed', 0)
            total_trades_week = weekly_stats.get('positions_closed', 0)
            
            # Rev 00132: RECOVERY - If daily_stats is empty (e.g., after deployment), recover from closed_trades
            # Rev 00153: Also fix discrepancies when stats count doesn't match closed_trades count
            today = datetime.utcnow().date()
            today_trades = []
            for trade in self._mock_executor.closed_trades:
                # Check if trade was closed today
                if trade.exit_timestamp:
                    exit_date = trade.exit_timestamp.date()
                    if exit_date == today:
                        today_trades.append(trade)
                # Also check entry date if no exit timestamp (shouldn't happen, but safety check)
                elif trade.timestamp.date() == today:
                    today_trades.append(trade)
            
            actual_trades_count = len(today_trades)
            
            # Check for discrepancy or empty stats
            if (total_trades_today == 0 and actual_trades_count > 0) or (actual_trades_count > 0 and total_trades_today != actual_trades_count):
                if total_trades_today == 0:
                    log.warning(f"⚠️ EOD Report: daily_stats is empty but {actual_trades_count} closed trades found!")
                    log.warning(f"   Recovering daily stats from closed_trades (likely deployment wiped in-memory stats)")
                else:
                    log.warning(f"⚠️ EOD Report DISCREPANCY: daily_stats shows {total_trades_today} trades, but {actual_trades_count} trades closed today!")
                    log.warning(f"   Recovering daily stats from closed_trades to fix discrepancy (Rev 00153)")
                
                if today_trades:
                    log.info(f"✅ Recovered {len(today_trades)} trades from today in closed_trades")
                    
                    # Recalculate daily stats from recovered trades
                    recovered_pnl = sum(t.pnl for t in today_trades)
                    recovered_wins = sum(1 for t in today_trades if t.pnl > 0)
                    recovered_losses = sum(1 for t in today_trades if t.pnl <= 0)
                    recovered_best = max((t.pnl for t in today_trades), default=0.0)
                    recovered_worst = min((t.pnl for t in today_trades), default=0.0)
                    
                    # Update daily_stats with recovered data
                    daily_stats = {
                        'positions_closed': len(today_trades),
                        'winning_trades': recovered_wins,
                        'losing_trades': recovered_losses,
                        'total_pnl': recovered_pnl,
                        'best_trade': recovered_best,
                        'worst_trade': recovered_worst,
                        'best_symbol': 'N/A',  # TODO: Track symbols
                        'worst_symbol': 'N/A'
                    }
                    
                    log.info(f"✅ Recovered daily stats: {len(today_trades)} trades, ${recovered_pnl:.2f} P&L, {recovered_wins}W/{recovered_losses}L (was {total_trades_today} trades, ${daily_stats.get('total_pnl', 0.0):.2f} P&L)")
                    total_trades_today = len(today_trades)
                    
                    # Rev 00153: Also update mock_executor's daily_stats to prevent future discrepancies
                    self._mock_executor.daily_stats['positions_closed'] = len(today_trades)
                    self._mock_executor.daily_stats['total_pnl'] = recovered_pnl
                    self._mock_executor.daily_stats['winning_trades'] = recovered_wins
                    self._mock_executor.daily_stats['losing_trades'] = recovered_losses
                    self._mock_executor.daily_stats['best_trade'] = recovered_best
                    self._mock_executor.daily_stats['worst_trade'] = recovered_worst
                    log.info(f"✅ Updated mock_executor.daily_stats to match recovered data")
            
            if total_trades_today == 0 and total_trades_week == 0:
                log.warning(f"⚠️ EOD Report: No trades recorded today or this week!")
                log.warning(f"   This may indicate a stats tracking issue or all positions still open")
            
            active_positions = len(self._mock_executor.active_trades)
            account_balance = self._mock_executor.account_balance
            # Rev 00135: Use persisted starting balance for accurate % calculations
            starting_balance = getattr(self._mock_executor, 'starting_balance', 1000.0)
            
            # Rev 00135: Get all-time stats from mock executor
            # Rev 00185: Calculate ALL stats from closed_trades to ensure accuracy and persistence
            # This ensures all-time stats include ALL historical trades, even after deployments
            all_time_total_wins_sum = 0.0
            all_time_total_losses_sum = 0.0
            all_time_total_pnl = 0.0
            all_time_winning_trades = 0
            all_time_losing_trades = 0
            
            for trade in self._mock_executor.closed_trades:
                all_time_total_pnl += trade.pnl
                if trade.pnl > 0:
                    all_time_total_wins_sum += trade.pnl
                    all_time_winning_trades += 1
                else:
                    all_time_total_losses_sum += abs(trade.pnl)
                    all_time_losing_trades += 1
            
            # Rev 00185: Use calculated values from closed_trades (source of truth)
            # This ensures all-time stats are always accurate and include all historical trades
            all_time_stats = {
                'total_trades': len(self._mock_executor.closed_trades),  # Count from closed_trades
                'winning_trades': all_time_winning_trades,  # Calculated from closed_trades
                'losing_trades': all_time_losing_trades,  # Calculated from closed_trades
                'total_pnl': all_time_total_pnl,  # Calculated from closed_trades
                'total_wins_sum': all_time_total_wins_sum,  # For accurate profit factor
                'total_losses_sum': all_time_total_losses_sum  # For accurate profit factor
            }
            
            # Rev 00185: Validate consistency and log if discrepancy found
            if (self._mock_executor.total_trades != len(self._mock_executor.closed_trades) or
                abs(self._mock_executor.total_pnl - all_time_total_pnl) > 0.01):
                log.warning(f"⚠️ EOD STATS DISCREPANCY: Executor stats (trades={self._mock_executor.total_trades}, P&L=${self._mock_executor.total_pnl:.2f}) != closed_trades (count={len(self._mock_executor.closed_trades)}, P&L=${all_time_total_pnl:.2f})")
                log.warning(f"   Using closed_trades as source of truth for all-time stats (ensures persistence)")
            
            # Send unified EOD report (🛃 format with weekly stats and all-time stats)
            log.info(f"📤 Sending unified 🛃 EOD report...")
            success = await self.send_end_of_day_report(
                daily_stats=daily_stats,
                weekly_stats=weekly_stats,
                active_positions=active_positions,
                mode="DEMO",
                account_balance=account_balance,
                starting_balance=starting_balance,
                all_time_stats=all_time_stats
            )
            
            if not success:
                log.error(f"❌ Failed to send unified 🛃 EOD report - send_end_of_day_report returned False")
                # Don't return - still reset stats and mark as sent
            else:
                log.info(f"✅ Unified 🛃 EOD report sent successfully!")
            
            # Rev 00135: Save account balance and weekly stats before resetting daily stats
            # Rev 00185: Save ALL trade history to GCS to ensure persistence across deployments
            # NOTE: Account balance and weekly stats are NOT reset - they persist across days
            # NOTE: closed_trades are NEVER cleared - they accumulate all historical trades
            self._mock_executor._save_mock_data()
            log.info(f"💰 Saved account balance: ${self._mock_executor.account_balance:,.2f} (will persist for tomorrow)")
            log.info(f"📊 Saved {len(self._mock_executor.closed_trades)} total trades to GCS (all historical trades preserved)")
            
            # Reset daily stats after sending report (mock executor handles this internally)
            self._mock_executor.reset_daily_stats()
            
            log.info(f"✅ Demo Mode EOD summary complete ({today}) - UNIFIED 🛃 FORMAT")
            
        except Exception as e:
            log.error(f"Failed to send Demo Mode EOD summary: {e}")
    
    async def _send_live_eod_summary(self):
        """Send Live Mode end-of-day summary (with GCS-based deduplication - Rev 00180AE)"""
        try:
            if not hasattr(self, '_unified_trade_manager') or not self._unified_trade_manager:
                log.warning("No unified trade manager available for Live EOD summary")
                return
            
            # DEDUPLICATION: Check if EOD report already sent today (Rev 00180AE - GCS-based)
            # Rev 00047: Date-based marker (internal scheduler disabled, so no blocking)
            # Ensures only ONE EOD report per day, even if Cloud Scheduler retries
            today = datetime.utcnow().strftime('%Y-%m-%d')  # Rev 00075: UTC consistency
            eod_sent_key = f"eod_sent_{today}_LIVE_unified"  # One per day
            
            # Try GCS-based deduplication first (works across all instances)
            try:
                from .gcs_persistence import get_gcs_persistence
                gcs = get_gcs_persistence()
                
                # Check if marker file exists in GCS (one per day)
                gcs_marker_path = f"eod_markers/{eod_sent_key}.txt"
                
                # Try to download marker (if exists, report already sent today)
                if gcs.file_exists(gcs_marker_path):
                    log.info(f"✅ Live EOD report already sent today ({today}) - only ONE report per day, skipping duplicate")
                    return
                
                # Upload marker file to GCS (atomic operation prevents race conditions)
                marker_content = datetime.utcnow().isoformat()  # Rev 00075: UTC consistency
                gcs.upload_string(gcs_marker_path, marker_content)
                log.info(f"📝 Created GCS EOD marker for {today} LIVE")
                
            except Exception as gcs_error:
                log.warning(f"GCS deduplication failed (non-critical): {gcs_error}")
                # Fall back to class-level cache (works within same instance)
                if not hasattr(self.__class__, '_eod_sent_cache_live'):
                    self.__class__._eod_sent_cache_live = {}
                
                if eod_sent_key in self.__class__._eod_sent_cache_live:
                    log.info(f"Live EOD report already sent today ({today}) - skipping duplicate (class cache)")
                    return
                
                # Mark as sent in class cache
                self.__class__._eod_sent_cache_live[eod_sent_key] = datetime.utcnow()  # Rev 00075: UTC consistency
            
            # Rev 00180AE: Use unified EOD report function (centralized in alert_manager)
            # DIAGNOSTIC (Rev 00180AE): Check unified trade manager state before reading stats
            log.info(f"📊 LIVE EOD DIAGNOSTIC: Unified TM instance: {id(self._unified_trade_manager)}")
            log.info(f"📊 LIVE EOD DIAGNOSTIC: Active positions: {len(self._unified_trade_manager.active_positions)}")
            log.info(f"📊 LIVE EOD DIAGNOSTIC: Daily stats raw: {self._unified_trade_manager.daily_stats}")
            log.info(f"📊 LIVE EOD DIAGNOSTIC: Weekly stats raw: {self._unified_trade_manager.weekly_stats}")
            
            # Rev 00135: Calculate profit factors from actual trade data (like Demo mode)
            today = datetime.utcnow().date()
            current_week_start = datetime.utcnow().date()
            days_since_monday = current_week_start.weekday()
            monday = current_week_start - timedelta(days=days_since_monday)
            
            # Calculate daily profit factor from today's trades
            daily_total_wins = 0.0
            daily_total_losses = 0.0
            if hasattr(self._unified_trade_manager, 'trade_history') and self._unified_trade_manager.trade_history:
                for trade in self._unified_trade_manager.trade_history:
                    if hasattr(trade, 'exit_time') and trade.exit_time and trade.exit_time.date() == today:
                        pnl = getattr(trade, 'pnl', getattr(trade, 'pnl_dollars', 0.0))
                        if pnl > 0:
                            daily_total_wins += pnl
                        else:
                            daily_total_losses += abs(pnl)
                    elif isinstance(trade, dict):
                        exit_time = trade.get('exit_time')
                        if exit_time:
                            if isinstance(exit_time, datetime):
                                exit_date = exit_time.date()
                            else:
                                exit_date = exit_time
                            if exit_date == today:
                                pnl = trade.get('pnl', trade.get('pnl_dollars', 0.0))
                                if pnl > 0:
                                    daily_total_wins += pnl
                                else:
                                    daily_total_losses += abs(pnl)
            
            # Calculate weekly profit factor from this week's trades
            weekly_total_wins = 0.0
            weekly_total_losses = 0.0
            weekly_trades = []  # Rev 00224: Collect all weekly trades for accurate calculation
            if hasattr(self._unified_trade_manager, 'trade_history') and self._unified_trade_manager.trade_history:
                for trade in self._unified_trade_manager.trade_history:
                    exit_date = None
                    if hasattr(trade, 'exit_time') and trade.exit_time:
                        exit_date = trade.exit_time.date() if isinstance(trade.exit_time, datetime) else trade.exit_time
                    elif isinstance(trade, dict):
                        exit_time = trade.get('exit_time')
                        if exit_time:
                            exit_date = exit_time.date() if isinstance(exit_time, datetime) else exit_time
                    
                    if exit_date and exit_date >= monday:
                        weekly_trades.append(trade)
                        pnl = getattr(trade, 'pnl', getattr(trade, 'pnl_dollars', 0.0)) if hasattr(trade, 'pnl') or hasattr(trade, 'pnl_dollars') else (trade.get('pnl', trade.get('pnl_dollars', 0.0)) if isinstance(trade, dict) else 0.0)
                        if pnl > 0:
                            weekly_total_wins += pnl
                        else:
                            weekly_total_losses += abs(pnl)
            
            # Get stats from unified trade manager
            daily_stats = {
                'positions_closed': self._unified_trade_manager.daily_stats['positions_closed'],
                'winning_trades': self._unified_trade_manager.daily_stats['winning_trades'],
                'losing_trades': self._unified_trade_manager.daily_stats['losing_trades'],
                'total_pnl': self._unified_trade_manager.daily_stats['total_pnl'],
                'best_trade': self._unified_trade_manager.daily_stats.get('best_trade', 0.0),
                'worst_trade': self._unified_trade_manager.daily_stats.get('worst_trade', 0.0),
                'best_symbol': 'N/A',  # TODO: Track symbols
                'worst_symbol': 'N/A',
                'total_wins_sum': daily_total_wins,  # Rev 00135: For accurate profit factor
                'total_losses_sum': daily_total_losses  # Rev 00135: For accurate profit factor
            }
            
            # DIAGNOSTIC (Rev 00180AE): Validate stats before sending
            total_trades_today = daily_stats.get('positions_closed', 0)
            if total_trades_today == 0:
                log.warning(f"⚠️ Live EOD Report: No trades recorded today!")
                log.warning(f"   This may indicate a stats tracking issue or all positions still open")
            
            # Rev 00224: Calculate weekly stats from trade_history (source of truth) instead of weekly_stats
            # This ensures weekly stats include ALL trades from the week, even after deployments
            weekly_total_pnl = 0.0
            weekly_winning_trades = 0
            weekly_losing_trades = 0
            for trade in weekly_trades:
                pnl = getattr(trade, 'pnl', getattr(trade, 'pnl_dollars', 0.0)) if hasattr(trade, 'pnl') or hasattr(trade, 'pnl_dollars') else (trade.get('pnl', trade.get('pnl_dollars', 0.0)) if isinstance(trade, dict) else 0.0)
                weekly_total_pnl += pnl
                if pnl > 0:
                    weekly_winning_trades += 1
                else:
                    weekly_losing_trades += 1
            
            weekly_stats = {
                'positions_closed': len(weekly_trades),  # Rev 00224: Count from trade_history
                'winning_trades': weekly_winning_trades,  # Rev 00224: Calculated from trade_history
                'losing_trades': weekly_losing_trades,  # Rev 00224: Calculated from trade_history
                'total_pnl': weekly_total_pnl,  # Rev 00224: Calculated from trade_history
                'total_wins_sum': weekly_total_wins,  # Rev 00135: For accurate profit factor
                'total_losses_sum': weekly_total_losses  # Rev 00135: For accurate profit factor
            }
            
            # Rev 00224: Log if discrepancy found between executor weekly_stats and calculated
            if (self._unified_trade_manager.weekly_stats.get('positions_closed', 0) != len(weekly_trades) or
                abs(self._unified_trade_manager.weekly_stats.get('total_pnl', 0.0) - weekly_total_pnl) > 0.01):
                log.warning(f"⚠️ LIVE EOD WEEKLY STATS DISCREPANCY: Executor weekly_stats (trades={self._unified_trade_manager.weekly_stats.get('positions_closed', 0)}, P&L=${self._unified_trade_manager.weekly_stats.get('total_pnl', 0.0):.2f}) != trade_history (count={len(weekly_trades)}, P&L=${weekly_total_pnl:.2f})")
                log.warning(f"   Using trade_history as source of truth for weekly stats (ensures persistence)")
            
            active_positions = len(self._unified_trade_manager.active_positions)
            
            # Get account balance from unified trade manager (via compound engine or E*TRADE)
            account_balance = 10000.0  # Default fallback
            starting_balance = 10000.0  # Default fallback
            
            try:
                # Rev 00108: Live mode uses E*TRADE directly - no compound engine
                # Get account balance from E*TRADE API
                if hasattr(self._unified_trade_manager, 'etrade_trading') and self._unified_trade_manager.etrade_trading:
                    account_summary = self._unified_trade_manager.etrade_trading.get_account_summary()
                    if 'error' not in account_summary:
                        account_balance = account_summary['balance'].get('account_value', 10000.0)
                        starting_balance = getattr(self._unified_trade_manager, 'starting_balance', account_balance)
                        log.debug(f"📊 Live EOD: Account ${account_balance:,.2f} from E*TRADE (real-time)")
            except Exception as balance_error:
                log.warning(f"⚠️ Could not get Live account balance: {balance_error}, using fallback")
            
            # Rev 00135: Get all-time stats from unified_metrics
            all_time_total_wins_sum = 0.0
            all_time_total_losses_sum = 0.0
            if hasattr(self._unified_trade_manager, 'trade_history') and self._unified_trade_manager.trade_history:
                for trade in self._unified_trade_manager.trade_history:
                    pnl = getattr(trade, 'pnl', getattr(trade, 'pnl_dollars', 0.0)) if hasattr(trade, 'pnl') or hasattr(trade, 'pnl_dollars') else (trade.get('pnl', trade.get('pnl_dollars', 0.0)) if isinstance(trade, dict) else 0.0)
                    if pnl > 0:
                        all_time_total_wins_sum += pnl
                    else:
                        all_time_total_losses_sum += abs(pnl)
            
            all_time_stats = {
                'total_trades': self._unified_trade_manager.unified_metrics.get('total_trades', 0),
                'winning_trades': self._unified_trade_manager.unified_metrics.get('winning_trades', 0),
                'losing_trades': self._unified_trade_manager.unified_metrics.get('losing_trades', 0),
                'total_pnl': self._unified_trade_manager.unified_metrics.get('total_pnl', 0.0),
                'total_wins_sum': all_time_total_wins_sum,  # Rev 00135: For accurate profit factor
                'total_losses_sum': all_time_total_losses_sum  # Rev 00135: For accurate profit factor
            }
            
            # Send unified EOD report (🛃 format with weekly stats and all-time stats)
            log.info(f"📤 Sending unified 🛃 EOD report (LIVE)...")
            success = await self.send_end_of_day_report(
                daily_stats=daily_stats,
                weekly_stats=weekly_stats,
                active_positions=active_positions,
                mode="LIVE",
                account_balance=account_balance,
                starting_balance=starting_balance,
                all_time_stats=all_time_stats  # Rev 00135: Add all-time stats
            )
            
            if not success:
                log.error(f"❌ Failed to send unified 🛃 EOD report (LIVE) - send_end_of_day_report returned False")
            else:
                log.info(f"✅ Unified 🛃 EOD report (LIVE) sent successfully!")
            
            log.info(f"✅ Live Mode EOD summary complete ({today}) - UNIFIED 🛃 FORMAT")
            
        except Exception as e:
            log.error(f"Failed to send Live Mode EOD summary: {e}")
    
    def _create_daily_performance_summary(self) -> PerformanceSummary:
        """Create a performance summary from today's trades"""
        today = datetime.utcnow().date()  # Rev 00075: UTC consistency
        
        # Check if we're in Demo Mode and get mock trades
        demo_mode = get_config_value('TRADING_MODE', 'demo').lower() in ['demo', 'demo_mode']
        mock_trades = []
        
        if demo_mode:
            # Get mock trades from the trading system if available
            try:
                from .prime_trading_system import PrimeTradingSystem
                # This is a bit of a hack - we need a better way to access mock executor
                # For now, we'll check if there are any mock trades in the system
                pass
            except:
                pass
        
        # Filter trades from today (both real and mock)
        today_trades = [trade for trade in self.trade_history 
                       if trade.get('date', datetime.utcnow()).date() == today]  # Rev 00075: UTC consistency
        
        # Add mock trades if in Demo Mode
        if demo_mode and hasattr(self, '_mock_executor') and self._mock_executor:
            mock_closed_trades = getattr(self._mock_executor, 'closed_trades', [])
            for mock_trade in mock_closed_trades:
                if hasattr(mock_trade, 'timestamp') and mock_trade.timestamp.date() == today:
                    today_trades.append({
                        'date': mock_trade.timestamp,
                        'symbol': mock_trade.symbol,
                        'side': mock_trade.side.value,
                        'entry_price': mock_trade.entry_price,
                        'exit_price': mock_trade.exit_price,
                        'quantity': mock_trade.quantity,
                        'pnl': mock_trade.pnl,
                        'exit_reason': mock_trade.exit_reason,
                        'is_mock': True
                    })
        
        if not today_trades:
            # Return empty summary if no trades today
            return PerformanceSummary(
                date=datetime.now(),
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                daily_return=0.0,
                active_positions=0,
                signals_generated=0,
                signals_accepted=0,
                acceptance_rate=0.0,
                total_pnl_dollars=0.0
            )
        
        # Calculate metrics
        total_trades = len(today_trades)
        winning_trades = len([t for t in today_trades if t.get('pnl', 0) > 0])
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        total_pnl = sum(t.get('pnl', 0) for t in today_trades)
        total_pnl_dollars = sum(t.get('pnl_dollars', 0) for t in today_trades)
        
        # Get top and worst performers
        sorted_trades = sorted(today_trades, key=lambda x: x.get('pnl', 0), reverse=True)
        top_performers = sorted_trades[:3] if sorted_trades else []
        worst_performers = sorted_trades[-2:] if len(sorted_trades) >= 2 else []
        
        # Calculate consecutive wins
        consecutive_wins = 0
        for trade in reversed(sorted_trades):
            if trade.get('pnl', 0) > 0:
                consecutive_wins += 1
            else:
                break
        
        return PerformanceSummary(
            date=datetime.now(),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            daily_return=total_pnl,  # Same as total_pnl for daily
            active_positions=len([t for t in today_trades if t.get('status') == 'open']),
            signals_generated=len(self.alert_history),  # Approximate
            signals_accepted=total_trades,
            acceptance_rate=total_trades / len(self.alert_history) if self.alert_history else 0.0,
            max_drawdown=self._calculate_max_drawdown(today_trades),
            capital_used_pct=self._calculate_capital_used_pct(),
            consecutive_wins=consecutive_wins,
            avg_risk_per_trade=4.2,  # Default value
            total_pnl_dollars=total_pnl_dollars,
            top_performers=top_performers,
            worst_performers=worst_performers
        )
    
    def _calculate_max_drawdown(self, trades: List[Dict]) -> float:
        """Calculate maximum drawdown from trades"""
        if not trades:
            return 0.0
        
        peak = 0.0
        max_dd = 0.0
        running_pnl = 0.0
        
        for trade in trades:
            running_pnl += trade.get('pnl', 0)
            if running_pnl > peak:
                peak = running_pnl
            dd = peak - running_pnl
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
    
    def _calculate_capital_used_pct(self) -> float:
        """Calculate percentage of capital used"""
        # This would need to be calculated based on account balance and position sizes
        # For now, return a default value
        return 82.0
    
    def add_trade_to_history(self, trade_data: Dict[str, Any]):
        """Add a trade to the daily history for end-of-day summary"""
        trade_data['date'] = datetime.now()
        self.trade_history.append(trade_data)
        
        # Keep only last 30 days of trades
        cutoff_date = datetime.now() - timedelta(days=30)
        self.trade_history = [t for t in self.trade_history 
                            if t.get('date', datetime.now()) > cutoff_date]
    
    # ============================================================================================================================================
    # UTILITY METHODS
    # ============================================================================================================================================
    
    def _check_alert_throttling(self, alert: Alert) -> bool:
        """Check if alert should be throttled"""
        current_time = time.time()
        alert_key = f"{alert.alert_type.value}_{alert.level.value}"
        
        # Check cooldown
        if current_time - self.last_alert_time.get(alert_key, 0) < self.alert_cooldown_seconds:
            return False
        
        # Check rate limiting
        minute_key = f"{alert_key}_{current_time // 60}"
        if self.alert_counts[minute_key] >= self.max_alerts_per_minute:
            return False
        
        self.last_alert_time[alert_key] = current_time
        self.alert_counts[minute_key] += 1
        
        return True
    
    def _track_alert(self, alert: Alert):
        """Track alert for analytics"""
        self.alert_history.append(alert)
    
    def get_alert_statistics(self) -> Dict[str, Any]:
        """Get alert statistics"""
        if not self.alert_history:
            return {}
        
        stats = {
            'total_alerts': len(self.alert_history),
            'alerts_by_type': defaultdict(int),
            'alerts_by_level': defaultdict(int),
            'recent_alerts': []
        }
        
        for alert in self.alert_history:
            stats['alerts_by_type'][alert.alert_type.value] += 1
            stats['alerts_by_level'][alert.level.value] += 1
        
        # Get recent alerts (last 10)
        stats['recent_alerts'] = [
            {
                'type': alert.alert_type.value,
                'level': alert.level.value,
                'title': alert.title,
                'timestamp': alert.timestamp.isoformat()
            }
            for alert in list(self.alert_history)[-10:]
        ]
        
        return stats
    
    # ================================================================================================================================================
    # OAUTH ALERT METHODS
    # ================================================================================================================================================
    
    
    async def send_oauth_renewal_success(self, environment: str, token_valid: bool = True) -> bool:
        """
        Send OAuth token renewal success notification
        
        Args:
            environment: Environment (prod or sandbox)
            token_valid: Whether token has been confirmed valid (default: True)
            
        Returns:
            True if alert sent successfully
            
        Note:
            Only sends success alert if token_valid is True.
            If token_valid is False, this method returns False without sending.
        """
        try:
            # Only send success alert if token is confirmed valid
            if not token_valid:
                log.warning(f"Token renewal completed but token is INVALID for {environment} - skipping success alert")
                return False
            
            # Get current time in Pacific Time and Eastern Time
            from zoneinfo import ZoneInfo
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            # Format times properly
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Determine system mode based on environment
            if environment.lower() == 'prod':
                system_mode = "Live Trading Enabled"
                env_label = "Production"
                mode_label = "Live"
            else:
                system_mode = "Demo Trading Available"
                env_label = "Sandbox"
                mode_label = "Demo"
            
            message = f"""====================================================================

✅ OAuth {env_label} Token Renewed
          Time: {pt_time} ({et_time})

🎉 Success! E*TRADE {environment.lower()} token successfully renewed for {mode_label}

📊 System Mode: {system_mode}
💎 Status: Trading system ready and operational

🌐 Public Dashboard: 
          https://easy-trading-oauth-v2.web.app"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                # Update OAuth status
                self.oauth_status[environment]['last_renewed'] = datetime.now()
                self.oauth_status[environment]['is_valid'] = True
                log.info(f"OAuth renewal success alert sent for {environment}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending OAuth renewal success alert: {e}")
            return False
    
    async def send_oauth_renewal_error(self, environment: str, error_message: str) -> bool:
        """Send OAuth token renewal error notification"""
        try:
            message = f"""❌ OAuth Token Renewal Failed

🔐 Environment: {environment.upper()}
⏰ Time: {datetime.now().strftime('%I:%M %p ET')}
🚨 Error: {error_message}

🔧 Please check the OAuth web app and try again
🔗 URL: {self.oauth_renewal_url}/oauth/start?env={environment}"""
            
            success = await self._send_telegram_message(message, AlertLevel.ERROR)
            
            if success:
                # Update OAuth status
                self.oauth_status[environment]['is_valid'] = False
                log.info(f"OAuth renewal error alert sent for {environment}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending OAuth renewal error alert: {e}")
            return False
    
    def update_oauth_status(self, environment: str, is_valid: bool, last_renewed: datetime = None):
        """Update OAuth token status"""
        try:
            self.oauth_status[environment]['is_valid'] = is_valid
            if last_renewed:
                self.oauth_status[environment]['last_renewed'] = last_renewed
            else:
                self.oauth_status[environment]['last_renewed'] = datetime.now()
            
            log.info(f"OAuth status updated for {environment}: valid={is_valid}")
            
        except Exception as e:
            log.error(f"Error updating OAuth status: {e}")
    
    def get_oauth_status(self, environment: str) -> Dict[str, Any]:
        """Get current OAuth status for environment"""
        return self.oauth_status.get(environment, {
            'last_renewed': None,
            'is_valid': False,
            'expires_at': None
        })
    
    async def schedule_oauth_morning_alert(self) -> bool:
        """Schedule OAuth morning alert (called by Cloud Scheduler)"""
        try:
            if not self.oauth_enabled:
                log.info("OAuth alerts disabled, skipping morning alert scheduling")
                return False
            
            # This method is called by Cloud Scheduler at 8:30 AM ET
            success = await self.send_oauth_morning_alert()
            
            if success:
                log.info("OAuth morning alert scheduled and sent")
            else:
                log.error("Failed to send scheduled OAuth morning alert")
            
            return success
            
        except Exception as e:
            log.error(f"Error in scheduled OAuth morning alert: {e}")
            return False
    
    async def shutdown(self):
        """Shutdown the alert manager"""
        log.info("Prime Alert Manager shutting down...")
        
        # Send shutdown notification
        await self.send_system_alert(
            "🔌 System Shutdown",
            "Easy ORB Strategy system is shutting down gracefully.",
            AlertLevel.INFO
        )
    
    async def send_oauth_alert(self, title: str, message: str, level: AlertLevel = AlertLevel.INFO) -> bool:
        """
        Send OAuth-related alert
        
        Args:
            title: Alert title
            message: Alert message
            level: Alert level
            
        Returns:
            True if alert sent successfully
        """
        try:
            # Format OAuth alert
            formatted_message = f"🔐 **OAuth Alert**\n\n**{title}**\n\n{message}"
            
            # Send alert
            success = await self._send_telegram_message(formatted_message, level)
            
            if success:
                log.info(f"OAuth alert sent: {title}")
            else:
                log.warning(f"Failed to send OAuth alert: {title}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending OAuth alert: {e}")
            return False
    
    async def send_oauth_morning_alert(self) -> bool:
        """
        Send Good Morning alert 1 hour before market open (8:30 AM ET / 5:30 AM PT)
        Shows token status and system readiness
        
        OCT 25, 2025: Now checks for holidays and sends holiday alert instead of morning alert
        
        Returns:
            True if alert sent successfully
        """
        try:
            # Get current time in both timezones
            from zoneinfo import ZoneInfo
            et_tz = ZoneInfo('America/New_York')
            pt_tz = ZoneInfo('America/Los_Angeles')
            now_et = datetime.now(et_tz)
            now_pt = datetime.now(pt_tz)
            
            # Get day name
            day_name = now_et.strftime('%A, %B %d, %Y')
            today = now_et.date()
            
            # OCT 25, 2025: Check if today is a holiday BEFORE checking tokens
            day_of_week = today.weekday()  # 0=Monday, 6=Sunday
            
            # Skip weekends (already handled by Cloud Scheduler schedule)
            if day_of_week >= 5:
                log.info("Weekend - skipping morning alert")
                return True
            
            # Rev 00087: Check for ALL holidays (bank + low-volume) using unified checker
            try:
                from .dynamic_holiday_calculator import should_skip_trading
                
                should_skip, skip_reason, holiday_name = should_skip_trading(today)
                
                if should_skip:
                    # Send holiday alert instead of morning alert
                    log.info(f"🎃 Holiday detected: {holiday_name} ({skip_reason}) - sending holiday alert")
                    return await self.send_holiday_alert(holiday_name, skip_reason)
            except Exception as e:
                log.warning(f"Could not check holiday status: {e}")
            
            # Check token status from Secret Manager
            # Rev 00097 (Nov 4, 2025): Check BOTH prod AND sandbox tokens with expiration
            from google.cloud import secretmanager
            import json
            import os
            from datetime import timezone, timedelta
            from zoneinfo import ZoneInfo
            from datetime import datetime as dt_cls
            
            client = secretmanager.SecretManagerServiceClient()
            et_tz = ZoneInfo('America/New_York')
            now_et = dt_cls.now(et_tz)
            
            # Calculate last midnight ET (tokens before this are expired)
            last_midnight_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
            
            log.info(f"🔍 Checking BOTH Production and Sandbox tokens...")
            log.info(f"📅 Current time: {now_et.strftime('%I:%M %p ET on %B %d, %Y')}")
            log.info(f"⏰ Last midnight ET: {last_midnight_et.strftime('%I:%M %p ET on %B %d, %Y')}")
            
            # Check BOTH Production and Sandbox tokens
            def check_token_expiration(env: str) -> tuple[bool, str]:
                """
                Check if token is valid (not expired)
                Returns: (is_valid, status_message)
                """
                try:
                    # Rev 00190: Use centralized cloud config instead of hardcoded project_id
                    from .config_loader import get_cloud_config
                    cloud_config = get_cloud_config()
                    project_id = cloud_config["project_id"]
                    
                    oauth_secret_name = f"projects/{project_id}/secrets/etrade-oauth-{env}/versions/latest"
                    response = client.access_secret_version(request={"name": oauth_secret_name})
                    token_json = response.payload.data.decode('UTF-8')
                    token_data = json.loads(token_json)
                    
                    # Get token timestamp
                    timestamp_str = token_data.get('timestamp', '')
                    oauth_token = token_data.get('oauth_token', '')
                    oauth_secret = token_data.get('oauth_token_secret', '')
                    
                    # Check if tokens exist
                    if not oauth_token or len(oauth_token) < 10:
                        return False, "Token missing"
                    if not oauth_secret or len(oauth_secret) < 10:
                        return False, "Secret missing"
                    
                    # Check expiration
                    if timestamp_str:
                        token_time = dt_cls.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        token_time_et = token_time.astimezone(et_tz)
                        
                        # Token is valid if created AFTER last midnight ET
                        if token_time_et >= last_midnight_et:
                            time_str = token_time_et.strftime('%I:%M %p ET')
                            log.info(f"✅ {env.upper()} token VALID (renewed {time_str}, after midnight)")
                            return True, f"Valid (renewed {time_str})"
                        else:
                            time_str = token_time_et.strftime('%I:%M %p ET')
                            log.warning(f"❌ {env.upper()} token EXPIRED (renewed {time_str}, before midnight)")
                            return False, f"Expired (renewed {time_str})"
                    else:
                        log.warning(f"❌ {env.upper()} token has no timestamp")
                        return False, "No timestamp"
                        
                except Exception as e:
                    log.error(f"❌ Error checking {env} token: {e}")
                    return False, f"Error: {str(e)[:30]}"
            
            # Check Production token
            prod_valid, prod_status = check_token_expiration('prod')
            
            # Check Sandbox token
            sandbox_valid, sandbox_status = check_token_expiration('sandbox')
            
            # System is ready ONLY if BOTH tokens are valid
            tokens_valid = prod_valid and sandbox_valid
            
            log.info(f"📊 Final Token Status: Production={prod_valid}, Sandbox={sandbox_valid}, System Ready={tokens_valid}")
            
            if tokens_valid:
                # BOTH TOKENS VALID - Send Good Morning alert
                message = f"""====================================================================

🌅 <b>Good Morning!</b> ☁️☁️🌤️☁️☁️☁️🕊️☁️
          {day_name}

⏰ Market opens in 1 hour (9:30 AM ET)

🔐 Token Status:
    ✅ Production Token: Valid
    ✅ Sandbox Token: Valid

💎 Status:
          Trading system ready and operational

📊 Trading Schedule:
    <b>ORB Capture:</b>
          6:30-6:45 AM PT (9:30-9:45 AM ET)
    <b>SO Window:</b>
          7:15-7:30 AM PT (10:15-10:30 AM ET)
    <b>SO Execution:</b>
          7:30 AM PT (10:30 AM ET)

🌐 Public Dashboard: 
          https://easy-trading-oauth-v2.web.app

✅ Ready to trade!"""
                
                alert_level = AlertLevel.INFO
                log.info("Sending Good Morning alert - BOTH tokens VALID")
            
            elif not prod_valid and sandbox_valid:
                # PRODUCTION INVALID, SANDBOX VALID - Only Demo mode ready
                message = f"""====================================================================

🌅 <b>Good Morning!</b> ☁️☁️🌧️☁️☁️🌧️🌧️☁️
          {day_name}

⏰ Market opens in 1 hour (9:30 AM ET)

🔐 Token Status:
    ❌ Production Token: INVALID
    ✅ Sandbox Token: Valid

💎 Status:
          Only DEMO mode trading is ready and operational

📊 Trading Schedule:
    <b>ORB Capture:</b>
          6:30-6:45 AM PT (9:30-9:45 AM ET)
    <b>SO Window:</b>
          7:15-7:30 AM PT (10:15-10:30 AM ET)
    <b>SO Execution:</b>
          7:30 AM PT (10:30 AM ET)

🌐 Public Dashboard: 
          https://easy-trading-oauth-v2.web.app

⚠️ Renew Production token for LIVE mode trading"""
                
                alert_level = AlertLevel.WARNING
                log.warning("Sending Good Morning alert - Production INVALID, Sandbox valid (DEMO mode only)")
            
            elif prod_valid and not sandbox_valid:
                # PRODUCTION VALID, SANDBOX INVALID - Only Live mode ready
                message = f"""====================================================================

🌅 <b>Good Morning!</b> ☁️☁️🌧️☁️☁️🌧️🌧️☁️
          {day_name}

⏰ Market opens in 1 hour (9:30 AM ET)

🔐 Token Status:
    ✅ Production Token: Valid
    ❌ Sandbox Token: INVALID

💎 Status:
          LIVE mode trading is ready and operational

📊 Trading Schedule:
    <b>ORB Capture:</b>
          6:30-6:45 AM PT (9:30-9:45 AM ET)
    <b>SO Window:</b>
          7:15-7:30 AM PT (10:15-10:30 AM ET)
    <b>SO Execution:</b>
          7:30 AM PT (10:30 AM ET)

🌐 Public Dashboard: 
          https://easy-trading-oauth-v2.web.app

⚠️ Renew Sandbox token for DEMO mode trading"""
                
                alert_level = AlertLevel.WARNING
                log.warning("Sending Good Morning alert - Production valid, Sandbox INVALID (LIVE mode only)")
            
            else:
                # BOTH TOKENS INVALID - Critical alert
                message = f"""====================================================================

🌅 <b>Good Morning!</b> ☁️🌧️⛈️🌧️⛈️🌧️☁️🌧️
          {day_name}

⏰ Market opens in 1 hour (9:30 AM ET)

⚠️ TOKEN ALERT - 😱
🔴 ETRADE tokens are INVALID!

❌ Action required: Renew tokens NOW

📊 Trading Schedule:
    <b>ORB Capture:</b> 
          6:30-6:45 AM PT (9:30-9:45 AM ET)
    <b>SO Window:</b>
          7:15-7:30 AM PT (10:15-10:30 AM ET)
    <b>SO Execution:</b>
          7:30 AM PT (10:30 AM ET)

🌐 Public Dashboard:
          https://easy-trading-oauth-v2.web.app

⚠️ Please renew tokens before market open!"""
                
                alert_level = AlertLevel.CRITICAL
                log.error("Sending Good Morning alert - BOTH tokens INVALID (NO TRADING POSSIBLE)")
            
            success = await self._send_telegram_message(message, alert_level)
            
            if success:
                log.info(f"Good Morning alert sent successfully (tokens {'valid' if tokens_valid else 'INVALID'})")
            else:
                log.warning("Failed to send Good Morning alert")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Good Morning alert: {e}")
            return False
    
    async def send_oauth_token_renewed_confirmation(self, environment: str) -> bool:
        """
        Send OAuth token renewal confirmation alert when tokens are successfully renewed
        
        Args:
            environment: Environment (sandbox/prod)
            
        Returns:
            True if alert sent successfully
        """
        try:
            # Get current time in Pacific Time and Eastern Time
            from zoneinfo import ZoneInfo
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            # Format times properly
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Determine environment labels
            if environment.lower() == 'prod':
                env_label = "Production"
                system_mode = "Live Trading Enabled"
            else:
                env_label = "Sandbox"
                system_mode = "Demo Trading Available"
            
            # Determine environment-specific details
            if environment.lower() == 'prod':
                token_type = "production token successfully renewed for Live"
            else:
                token_type = "sandbox token successfully renewed for Demo"
            
            message = f"""====================================================================

✅ OAuth {env_label} Token Renewed
          Time: {pt_time} ({et_time})

🎉 Success! E*TRADE {token_type}

📊 System Mode: {system_mode}
💎 Status: Trading system ready and operational

🌐 Public Dashboard: 
          https://easy-trading-oauth-v2.web.app"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"OAuth {environment} token renewal confirmation sent")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending OAuth token renewal confirmation: {e}")
            return False

    async def send_oauth_success(self, environment: str, message: str) -> bool:
        """
        Send OAuth success alert
        
        Args:
            environment: Environment (sandbox/prod)
            message: Success message
            
        Returns:
            True if alert sent successfully
        """
        try:
            # Format success message
            formatted_message = f"""✅ **OAuth Success** - {environment.upper()}

{message}

**Environment**: {environment}
**Time**: {datetime.now().strftime('%I:%M %p ET')}
**Status**: Active and ready for trading"""

            success = await self._send_telegram_message(formatted_message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"OAuth success alert sent for {environment}")
            else:
                log.warning(f"Failed to send OAuth success alert for {environment}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending OAuth success alert: {e}")
            return False
    
    async def send_buy_signal_alert(self, symbol: str, company_name: str, shares: int,
                                   entry_price: float, total_value: float, confidence: float,
                                   expected_return: float, quality_score: float,
                                   strategies_agreeing: str, stop_loss: float,
                                   take_profit: float, note: str = "") -> bool:
        """Send buy signal alert with comprehensive details"""
        try:
            # Determine confidence emoji
            if confidence >= 0.98:
                emoji = "🔰🔰🔰"
            elif confidence >= 0.85:
                emoji = "🔰🔰"
            elif confidence >= 0.70:
                emoji = "🔰"
            elif confidence >= 0.60:
                emoji = "📟"
            else:
                emoji = "🟡"
            
            message = f"""📈 <b>BUY SIGNAL - {symbol}</b> {emoji}

📊 <b>BUY</b> - {shares} shares - {company_name}
• Entry: ${entry_price:.2f}
• Total Value: ${total_value:.2f}

💼 <b>POSITION DETAILS:</b>
Symbol: {symbol}
Confidence: {confidence:.0%}
Expected Return: {expected_return:.1%}
Quality Score: {quality_score:.0%}

📊 <b>RISK MANAGEMENT:</b>
Stop Loss: ${stop_loss:.2f} ({((stop_loss - entry_price) / entry_price * 100):.1f}%)
Take Profit: ${take_profit:.2f} ({((take_profit - entry_price) / entry_price * 100):.1f}%)

⏰ <b>Entry Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
            
            if note:
                message += f"\n\n{note}"
            
            return await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
        except Exception as e:
            log.error(f"Failed to send buy signal alert: {e}")
            return False
    
    async def send_sell_signal_alert(self, symbol: str, company_name: str, shares: int,
                                     entry_price: float, exit_price: float, total_pnl: float,
                                     pnl_pct: float, duration_minutes: float, exit_reason: str,
                                     note: str = "") -> bool:
        """Send sell signal alert with P&L details"""
        try:
            pnl_emoji = "💰" if total_pnl > 0 else "📉"
            
            message = f"""📉 <b>SELL SIGNAL - {symbol}</b>

📊 <b>SELL</b> - {shares} shares - {company_name}
• Exit: ${exit_price:.2f}

💼 <b>POSITION CLOSED:</b>
Entry: ${entry_price:.2f}
Exit: ${exit_price:.2f}
P&L: {pnl_emoji} ${total_pnl:+.2f} ({pnl_pct:+.2f}%)
Duration: {duration_minutes:.0f} minutes

🎯 <b>EXIT REASON:</b>
{exit_reason}

⏰ <b>Exit Time:</b> {datetime.utcnow().strftime('%H:%M:%S')} UTC"""
            
            if note:
                message += f"\n\n{note}"
            
            return await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
        except Exception as e:
            log.error(f"Failed to send sell signal alert: {e}")
            return False
    
    async def send_telegram_alert(self, message: str, level: AlertLevel = AlertLevel.INFO) -> bool:
        """Public method to send raw Telegram message"""
        return await self._send_telegram_message(message, level)
    
    async def send_oauth_market_open_alert(self) -> bool:
        """
        Send OAuth market open alert at 5:30 AM PT (8:30 AM ET) - 1 hour before market open
        Only sends if tokens are actually invalid at that time
        
        Returns:
            True if alert sent successfully
        """
        try:
            if not self.oauth_enabled:
                log.info("OAuth alerts disabled, skipping market open alert")
                return False
            
            # Get current time in Pacific Time and Eastern Time
            from zoneinfo import ZoneInfo
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            # Format times properly
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Check if it's 5:30 AM PT (8:30 AM ET) - 1 hour before market open
            if now_pt.hour == 5 and now_pt.minute == 30:
                log.info("Checking token status before market open")
            else:
                log.info(f"Market open alert time check: {pt_time} (waiting for 5:30 AM PT)")
                return False
            
            # Check token status via Secret Manager directly
            # Since we're in Demo Mode, we only need sandbox tokens to be valid
            prod_valid = False
            sandbox_valid = False
            
            try:
                # Import Secret Manager OAuth integration
                from modules.etrade_oauth_integration import get_etrade_oauth_integration
                
                # Check sandbox token (required for Demo Mode)
                sandbox_oauth = get_etrade_oauth_integration('sandbox')
                if sandbox_oauth and sandbox_oauth.is_authenticated():
                    sandbox_valid = True
                    log.info("Sandbox tokens are valid - Demo Mode can proceed")
                else:
                    log.info("Sandbox tokens are invalid - Demo Mode cannot proceed")
                
                # Check production token (optional for Demo Mode)
                prod_oauth = get_etrade_oauth_integration('prod')
                if prod_oauth and prod_oauth.is_authenticated():
                    prod_valid = True
                    log.info("Production tokens are valid - Live Mode available")
                else:
                    log.info("Production tokens are invalid - Live Mode not available")
                
                # For Demo Mode, we only need sandbox tokens
                if sandbox_valid:
                    log.info("Demo Mode can proceed with sandbox tokens - skipping market open alert")
                    return False
                else:
                    log.info("Demo Mode cannot proceed - sandbox tokens invalid")
                    
            except Exception as oauth_error:
                log.error(f"Failed to check token status via OAuth integration: {oauth_error}")
                # If we can't check status, err on the side of caution and send alert
                log.info("Unable to verify token status - sending market open alert as precaution")
            
            # Only reach here if production tokens are invalid or we can't verify status
            if sandbox_valid:
                # Sandbox is valid - system will run in demo mode
                message = f"""====================================================================

🌅 <b>OAuth Market Open Alert —</b> {now_pt.strftime('%I:%M %p PT')}

📝 <b>REMINDER:</b> Market opens in <b>1 hour</b> - OAuth Sandbox token is INVALID

🌐 <b>Public Dashboard:</b> 
          https://easy-trading-oauth-v2.web.app

⚠️ <b>Status:</b> Pre-Market Check → Production Token INVALID
🛡️ <b>Status:</b> Demo Token VALID
🛠 <b>Trading Mode:</b> Demo Sandbox (Testing Mode)

📝 <b>Reminder:</b> Market opens in <b>1 hour</b>
📈 <b>Market Opens:</b> 9:30 AM ET (6:30 AM PT)
🕒 <b>Current Time:</b> {now_pt.strftime('%I:%M %p PT')} (8:30 AM ET)

✅ <b>System Status:</b> Trading system active in Sandbox
🔎 <b>Scanning & Signals:</b> Running (sandbox token valid)
📊 <b>Data & Analysis:</b> Fully functional"""
            else:
                # Neither token is valid - system cannot function
                message = f"""====================================================================

🌅 OAuth Market Open Alert — {pt_time} ({et_time})

🚨 URGENT: Market opens in 1 hour - OAuth Production token is INVALID

🌐 Public Dashboard: 
          https://easy-trading-oauth-v2.web.app

🚫 Trading System: Cannot start until tokens are valid

🚨 System Status: Trading system BLOCKED
❌ All Operations: Suspended (no valid tokens)
⚠️ Risk Level: HIGH - No trading capability"""

            success = await self._send_telegram_message(message, AlertLevel.ERROR)
            
            if success:
                log.info("OAuth market open alert sent successfully")
            else:
                log.warning("Failed to send OAuth market open alert")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending OAuth market open alert: {e}")
            return False
    
    # ================================================================================================================================================
    # TRADING PIPELINE ALERT METHODS
    # ================================================================================================================================================
    
    # Rev 00046: DEPRECATED - Old individual SO execution alert removed
    # Use send_orb_so_execution_aggregated() for SO batch alerts (7:30 AM PT)
    # This method is kept ONLY for ORR individual trades (if ORR ever re-enabled)
    async def send_trade_execution_alert(self, symbol: str, side: str, price: float, 
                                        quantity: int, trade_id: str, mode: str = "LIVE") -> bool:
        """
        DEPRECATED for SO trades - use send_orb_so_execution_aggregated() instead
        
        Only used for ORR individual trade alerts (ORR currently disabled)
        """
        log.warning(f"⚠️ send_trade_execution_alert called for {symbol} - THIS SHOULD NOT HAPPEN FOR SO TRADES!")
        log.warning(f"⚠️ SO trades should use send_orb_so_execution_aggregated() for batch alerts")
        return False
    
    # ================================================================================================================================================
    # ORB STRATEGY ALERT METHODS (Rev 00152)
    # ================================================================================================================================================
    
    async def send_so_signal_collection(self, so_signals: List[Dict[str, Any]],
                                        total_scanned: int, mode: str = "DEMO",
                                        spx_orb_data: Optional[Dict[str, Any]] = None,
                                        qqq_orb_data: Optional[Dict[str, Any]] = None,
                                        spy_orb_data: Optional[Dict[str, Any]] = None,
                                        dte0_signals_qualified: Optional[int] = None,
                                        dte0_signals_list: Optional[List[Dict[str, Any]]] = None,
                                        dte_symbols_list: Optional[List[str]] = None,
                                        hard_gated_symbols: Optional[List[Dict[str, Any]]] = None) -> bool:  # Rev 00229: Add Hard Gated symbols
        """
        Send SO Signal Collection alert after scan completes (Rev 00180AE)
        
        Shows actual scan results - handles both signals found and no signals cases.
        Replaces the old separate "No Signals" alert.
        
        Args:
            so_signals: List of SO signals collected (may be empty)
            total_scanned: Total symbols scanned
            mode: Trading mode (DEMO/LIVE)
        """
        try:
            # Rev 00065: Removed redundant datetime import (already imported at top)
            from zoneinfo import ZoneInfo
            
            # Get current time in both timezones
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p')
            et_time = now_et.strftime('%I:%M %p')
            
            signal_count = len(so_signals)
            
            # Extract ORB symbol list from signals (abbreviated list for confirmation)
            orb_symbol_list = []
            if signal_count > 0:
                for signal in so_signals:
                    symbol = signal.get('symbol') or signal.get('original_symbol')
                    if symbol:
                        orb_symbol_list.append(symbol)
                orb_symbols_text = ", ".join(orb_symbol_list)
            else:
                orb_symbols_text = ""

            # Extract 0DTE symbol list from approved signals (abbreviated list for confirmation)
            # Rev 00230: Keep abbreviated - detailed info goes to execution alert
            dte_symbol_list = []
            if dte0_signals_list:
                for signal in dte0_signals_list:
                    symbol = signal.get('symbol', '')
                    if symbol and symbol not in dte_symbol_list:
                        dte_symbol_list.append(symbol)
                
                dte_symbols_text = ", ".join(dte_symbol_list)
            else:
                dte_symbols_text = ""
            
            # Rev 00230: Hard Gated info moved to execution alert (removed from signal collection)

            # Build message based on whether signals were found
            if signal_count > 0 or (dte0_signals_qualified is not None and dte0_signals_qualified > 0):
                # Signals found - show collection complete status
                status_line = "Signal collection finished, ranking for quality…"
                
                # Build ORB section
                orb_section = ""
                if orb_symbols_text:
                    orb_section = f"""
📑 <b>Standard Orders Ready:</b>
{orb_symbols_text}"""
                
                # Build 0DTE section (Rev 00230: Keep abbreviated - details in execution alert)
                dte_section = ""
                if dte_symbols_text:
                    dte_section = f"""

🔮 <b>0DTE Options Ready:</b>
{dte_symbols_text}"""
                
                next_section = f"""

📡 <b>Signal Window:</b>
          7:15-7:30 AM PT (10:15-10:30 AM ET)
🚀 <b>Next:</b> ORB & Options Execution
          7:30 AM PT (10:30 AM ET)"""
            else:
                # No signals - show status
                status_line = "💢 <b>No Signals</b>"
                orb_section = ""
                dte_section = ""
                next_section = f"""

💡 <b>Status:</b>
          No qualified setups detected
📊 <b>Next:</b> Position monitoring
          (Throughout trading day)"""
            
            # Build 0DTE count display
            dte_count_display = ""
            if dte0_signals_qualified is not None:
                dte_count_display = f"          • <b>0DTE Options Signals:</b> {dte0_signals_qualified}\n"
            
            message = f"""====================================================================

🪽 <b>Trade Signal Collection</b> | {mode} Mode
          Time: {pt_time} PT ({et_time} ET)

{status_line}

📊 <b>Results:</b>
          • <b>Symbols Scanned:</b> {total_scanned}
          • <b>ORB Signals Generated:</b> {signal_count}
{dte_count_display}{orb_section}{dte_section}
{next_section}
"""

            success = await self._send_telegram_message(message, AlertLevel.INFO)
            
            if success:
                dte_count = dte0_signals_qualified if dte0_signals_qualified is not None else 0
                log.info(f"✅ SO Signal Collection alert sent: {signal_count} ORB + {dte_count} 0DTE signals from {total_scanned} symbols")
            
            return success
            
        except Exception as e:
            log.error(f"Failed to send SO signal collection alert: {e}")
            return False

    async def send_orb_so_execution_aggregated(self, so_signals: List[Dict[str, Any]], 
                                               total_scanned: int, mode: str = "DEMO",
                                               rejected_signals: List[Dict[str, Any]] = None,
                                               account_value: float = 1000.0,
                                               so_capital_pct: float = 90.0,
                                               filtered_expensive: int = 0) -> bool:
        """
        Send AGGREGATED Standard Order (SO) execution alert at 7:15 AM PT
        
        Shows all SO trades executed in ONE consolidated alert for clarity.
        Rev 00180g: Now includes rejected signals (insufficient capital)
        Oct 24, 2025: Added so_capital_pct parameter for unified configuration
        
        Args:
            so_signals: List of EXECUTED SO signals with trade details
            total_scanned: Total number of symbols scanned
            mode: Trading mode (DEMO or LIVE)
            rejected_signals: List of signals rejected due to insufficient capital
            account_value: Total account value
            so_capital_pct: SO capital allocation percentage (default 90.0)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            mode_text = f"{mode} Mode"
            
            # Count signals
            so_count = len(so_signals)
            bullish_count = sum(1 for s in so_signals if s.get('side') == 'LONG' or 'inverse' not in s.get('reasoning', '').lower())
            inverse_count = so_count - bullish_count
            
            # Rev 00180AE: SORT signals by priority score (DESCENDING - highest first)
            # This ensures alert shows trades in execution order
            so_signals_sorted = sorted(
                so_signals, 
                key=lambda s: s.get('priority_score', s.get('confidence', 0)), 
                reverse=True  # Highest priority first
            )
            
            # Build trade list (NOW IN PRIORITY ORDER)
            trade_lines = []
            total_value = 0.0
            
            for i, signal in enumerate(so_signals_sorted, 1):
                symbol = signal.get('symbol', 'UNKNOWN')
                price = signal.get('price', 0.0)
                confidence = signal.get('confidence', 0.0)
                priority_score = signal.get('priority_score', confidence)  # Rev 00180AE: Get priority score
                priority_rank = signal.get('priority_rank', i)  # Rev 00180AE: Get rank
                is_inverse = signal.get('inverse_symbol') is not None
                original_symbol = signal.get('original_symbol', symbol)
                
                # Rev 00180V: Get actual quantity from signal if available (from execution)
                # Rev 00082: Use position_value from signal if available (already calculated post-execution)
                # account_value is now passed as parameter (actual Demo account balance)
                quantity = signal.get('quantity', 0)  # Get actual executed quantity if available
                trade_value = signal.get('position_value', 0.0)  # Rev 00082: Use pre-calculated value
                
                if quantity == 0 or trade_value == 0.0:
                    # Fallback: Estimate quantity (SO capital / num trades)
                    # Oct 24, 2025: Use parameter from unified config
                    so_capital = account_value * (so_capital_pct / 100.0)
                    num_trades = len(so_signals)
                    per_trade_value = so_capital / max(1, num_trades)
                    quantity = int(per_trade_value / price) if price > 0 else 0
                    trade_value = quantity * price
                
                total_value += trade_value
                
                # Rev 00180V: Calculate ACTUAL portfolio percentage (not ORB's raw %)
                actual_position_pct = (trade_value / account_value) * 100.0
                
                # Use actual trade ID from executed signal (if available)
                trade_id = signal.get('trade_id')
                if not trade_id:
                    # Fallback: Generate trade ID (Rev 00232: Shortened format for alerts - symbol_date_microseconds)
                    now = datetime.now()
                    date_str = now.strftime('%y%m%d')  # 2-digit year
                    microseconds_short = now.microsecond % 1000  # Last 3 digits for uniqueness
                    trade_prefix = "MOCK" if mode == "DEMO" else "LIVE"
                    trade_id = f"{trade_prefix}_{symbol}_{date_str}_{microseconds_short:03d}"
                
                # Format with inverse notation if applicable
                if is_inverse:
                    inverse_line = f"\n          🔄 <b>Inverse Trade:</b> {original_symbol} → {symbol}"
                else:
                    inverse_line = ""
                
                # Rev 00231: Enhanced format with bold formatting for key metrics
                # Bold: Rank, Priority Score, Confidence (per documentation)
                confidence_pct = int(confidence * 100)
                trade_lines.append(
                    f"{i}) 🟢 <b>BUY {quantity}</b> • <b>{symbol} @ ${price:.2f}</b> • <b>${trade_value:.2f}</b>\n"
                    f"          <b>Rank #{priority_rank}</b> • Priority Score <b>{priority_score:.3f}</b>\n"
                    f"          <b>{confidence_pct}%</b> Confidence • {actual_position_pct:.1f}% Of Account{inverse_line}\n"
                    f"          Trade ID:\n"
                    f"          {trade_id}"
                )
            
            trades_text = "\n\n".join(trade_lines)
            
            # Rev 00180g: Build rejected signals section
            rejected_text = ""
            if rejected_signals and len(rejected_signals) > 0:
                rejected_lines = []
                for signal in rejected_signals:
                    symbol = signal.get('symbol', 'UNKNOWN')
                    price = signal.get('price', 0.0)
                    confidence = signal.get('confidence', 0.0)
                    rejected_lines.append(f"  • {symbol} @ ${price:.2f} ({confidence:.0%} confidence)")
                
                rejected_text = f"\n\n⚠️ <b>Rejected (Insufficient Capital):</b>\n" + "\n".join(rejected_lines)
            
            # Mode-specific title
            if mode == "DEMO":
                mode_title = "🎮 Demo Trade Executed"
            else:
                mode_title = "💰 Live Trade Executed"
            
            # FIX (Oct 24, 2025): Show deployment as % of TOTAL ACCOUNT
            # User requested: "$900 / $1,000 (90%)" not "$811 / $900 (81%)"
            # Display should show total account value (100%) and what % is deployed
            # Oct 24, 2025: Use parameter from unified config (no longer hardcoded)
            so_capital_total = account_value * (so_capital_pct / 100.0)  # Max deployable
            deployment_pct_of_account = (total_value / account_value) * 100.0 if account_value > 0 else 0.0
            
            # Rev 00180AE: Handle case where ALL trades were rejected (0 executed)
            if so_count > 0:
                # Some trades executed
                # FIX (Oct 24, 2025): Show denominator as total account (not SO allocation)
                execution_section = f"""💼 <b>Trades Executed:</b>

{trades_text}

💰 <b>Capital Deployment:</b>
          • <b>Deployed:</b> ${total_value:.2f} / ${account_value:.0f} ({deployment_pct_of_account:.1f}%)

🛡️ <b>Monitoring:</b> All positions tracked by Stealth Trailing System (1.5% trailing)"""
            else:
                # NO trades executed - ALL rejected
                total_rejected = len(rejected_signals) if rejected_signals else 0
                execution_section = f"""⚠️ <b>NO TRADES EXECUTED</b>

All {total_rejected} signals were REJECTED due to insufficient capital.

💡 <b>Action Required:</b>
• Increase account balance for more trading capacity
• Review position sizing strategy
• Check risk management settings{rejected_text}

📊 <b>System Status:</b> Ready for next trading opportunity"""
            
            # Build message (Rev 00180AE: Updated format with batch execution note)
            message = f"""====================================================================

🪽 <b>Standard Order Execution</b> | {mode} Mode
          Time: {pt_time} ({et_time})

📟 <b>Scan Results (7:15 AM PT):</b>
          • <b>Symbols Scanned:</b> {total_scanned}
          • <b>SO Signals Found:</b> {so_count + len(rejected_signals or []) + filtered_expensive}
          • <b>Filtered (Expensive):</b> {filtered_expensive}

{execution_section}

"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"SO execution aggregated alert sent - {so_count} trades from {total_scanned} symbols")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending SO execution aggregated alert: {e}")
            return False
    
    async def send_orb_orr_execution_alert(self, orr_signal: Dict[str, Any], 
                                          mode: str = "DEMO") -> bool:
        """
        Send individual Opening Range Reversal (ORR) execution alert
        
        Sent immediately when ORR reversal is detected and traded.
        
        Args:
            orr_signal: ORR signal with trade details
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            mode_text = f"{mode} Mode"
            
            # Extract signal data
            symbol = orr_signal.get('symbol', 'UNKNOWN')
            original_symbol = orr_signal.get('original_symbol', symbol)
            price = orr_signal.get('price', 0.0)
            confidence = orr_signal.get('confidence', 0.0)
            # Rev 00180V: Don't use ORB's raw position_size_pct
            # position_size = orr_signal.get('position_size_pct', 25.0)  # OLD
            stop_loss = orr_signal.get('stop_loss', 0.0)
            take_profit = orr_signal.get('take_profit', 0.0)
            reasoning = orr_signal.get('reasoning', '')
            is_inverse = orr_signal.get('inverse_symbol') is not None
            
            # Rev 00180V: Get actual quantity from signal (from execution)
            # Or estimate from ORR capital
            account_value = 1000.0  # Demo Mode virtual capital
            quantity = orr_signal.get('quantity', 0)
            
            if quantity == 0:
                # Fallback: Estimate from ORR reserve (20% of account)
                orr_capital = account_value * 0.20
                quantity = int(orr_capital / price) if price > 0 else 0
            
            trade_value = quantity * price
            # Rev 00180V: Calculate ACTUAL portfolio percentage
            actual_position_pct = (trade_value / account_value) * 100.0
            
            # Get ORB data
            orb_data = orr_signal.get('orb_data', {})
            orb_high = orb_data.get('orb_high', 0.0)
            orb_low = orb_data.get('orb_low', 0.0)
            orb_range = orb_data.get('orb_range', 0.0)
            
            # Determine reversal type and description
            if is_inverse:
                reversal_desc = f"Price reversed from above ORB high to below ORB low"
                inverse_line = f"\n          🔄 <b>Inverse Trade:</b> {original_symbol} → {symbol}"
            else:
                reversal_desc = f"Price reversed from below ORB low to above ORB high"
                inverse_line = ""
            
            # Mode-specific title
            if mode == "DEMO":
                mode_title = "🎮 Demo Trade Executed"
            else:
                mode_title = "💰 Live Trade Executed"
            
            # Generate trade ID
            timestamp = now_pt.strftime('%Y%m%d_%H%M%S')
            trade_prefix = "MOCK" if mode == "DEMO" else "LIVE"
            trade_id = f"{trade_prefix}_{timestamp}_{original_symbol}"
            
            # Build message (Rev 00180V: Use actual_position_pct)
            message = f"""====================================================================

🪽 <b>Opening Range Reversal Execution</b>
{mode_title}
⏰ <b>Execution Time:</b> {pt_time} ({et_time})

📉 <b>Opening Range Reversal Detected!</b>

   🟢 • <b>BUY {quantity} • {symbol} @ ${price:.2f} • ${trade_value:,.2f}</b>
          {confidence:.0%} Confidence • {actual_position_pct:.0f}% Of Portfolio{inverse_line}
          <b>Trade ID:</b> {trade_id}

   📈 <b>ORB Reference:</b>
   • Opening Range High: ${orb_high:.2f}
   • Opening Range Low: ${orb_low:.2f}
   • ORB Range: ${orb_range:.2f}

   🎯 <b>Reversal:</b>
   {reversal_desc}

   🛡️ <b>Risk Management:</b>
   • Stop Loss: ${stop_loss:.2f} ({((stop_loss - price) / price * 100):.1f}%)
   • Take Profit: ${take_profit:.2f} ({((take_profit - price) / price * 100):.1f}%)

{mode_emoji} <b>Mode:</b> {mode_text} - Position monitored by stealth trailing
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                signal_desc = "Inverse ORR" if is_inverse else "Bullish ORR"
                log.info(f"ORR execution alert sent for {symbol} - {signal_desc}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending ORR execution alert: {e}")
            return False
    
    async def send_orb_no_signals_alert(self, signal_type: str, total_scanned: int, 
                                       filtered_count: int = 0, mode: str = "DEMO") -> bool:
        """
        DEPRECATED (Rev 00180AE): Use send_so_signal_collection() instead
        
        This function is no longer called. The SO Signal Collection alert now handles
        both cases (signals found and no signals found).
        
        Send alert when ORB scan completes with NO signals
        
        Confirms system is working but no trade opportunities detected.
        
        Args:
            signal_type: "SO" or "ORR"
            total_scanned: Number of symbols scanned
            filtered_count: Number filtered by post-ORB validation
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Signal type specific text (Rev 00055: Updated SO next step to 7:30 AM PT)
            if signal_type == "SO":
                scan_desc = "Standard Order scan completed"
                next_step = "Signal execution at 7:30 AM PT (10:30 AM ET)"
            else:  # ORR
                scan_desc = "Opening Range Reversal scan completed"
                next_step = "Continuing ORR monitoring (next scan in 5 minutes)"
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            
            # Filtered info
            filtered_text = f"\n⛔ <b>Filtered (Sideways):</b> {filtered_count}" if filtered_count > 0 else ""
            
            message = f"""====================================================================

⏸️ <b>{signal_type} Scan Complete - No Signals</b>
⏰ <b>Scan Time:</b> {pt_time} ({et_time})

✅ {scan_desc}

📊 <b>Results:</b>
• Symbols Scanned: {total_scanned}
• Signals Generated: 0{filtered_text}

💡 <b>Status:</b> No qualified setups detected
🔍 <b>Next:</b> {next_step}

{mode_emoji} <b>Mode:</b> {mode} - System operational, waiting for qualified signals
"""
            
            success = await self._send_telegram_message(message, AlertLevel.INFO)
            
            if success:
                log.info(f"{signal_type} no signals alert sent - {total_scanned} scanned, 0 signals")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending ORB no signals alert: {e}")
            return False
    
    async def send_orb_capture_failed_alert(self, total_symbols: int,
                                            capture_time_seconds: float,
                                            mode: str = "DEMO") -> bool:
        """
        Send alert when ORB capture FAILS (0 symbols captured) - Rev 00180AE
        
        This indicates a critical issue with data fetching (ETrade/yfinance both failed).
        
        Args:
            total_symbols: Total number of symbols attempted
            capture_time_seconds: Time spent attempting capture
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            
            # Build failure alert message
            message = f"""====================================================================

🔴 <b>ORB CAPTURE FAILED</b>
⏰ Time: {pt_time} ({et_time})

❌ <b>Status: NO opening ranges captured!</b>

📊 <b>Capture Attempt:</b>
          • <b>Symbols Attempted:</b> {total_symbols}
          • <b>Symbols Captured:</b> 0
          • <b>Success Rate:</b> 0%
          • <b>Duration:</b> {capture_time_seconds:.1f} seconds

⚠️ <b>Issue:</b> Both ETrade and yfinance data sources failed

🔧 <b>Next Steps:</b>
          1. Check ETrade OAuth tokens
          2. Verify network connectivity
          3. Monitor for auto-retry

⚛️ <b>ORB Window:</b> 
          6:30-6:45 AM PT (9:30-9:45 AM ET)

🚨 Trading will be PAUSED until ORB data is available"""
            
            success = await self._send_telegram_message(message, AlertLevel.ERROR)
            
            if success:
                log.warning(f"ORB capture FAILED alert sent - 0/{total_symbols} symbols")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending ORB capture failed alert: {e}")
            return False
    
    async def send_orb_capture_complete_alert(self, symbols_captured: int,
                                              capture_time_seconds: float,
                                              filtered_count: int = 0,
                                              mode: str = "DEMO",
                                              spx_orb_data: Optional[Dict[str, Any]] = None,
                                              qqq_orb_data: Optional[Dict[str, Any]] = None,
                                              spy_orb_data: Optional[Dict[str, Any]] = None,
                                              dte_orb_data: Optional[Dict[str, Dict[str, Any]]] = None,
                                              orb_strategy_count: Optional[int] = None,  # Rev 00210: ORB Strategy symbol count
                                              dte_strategy_count: Optional[int] = None) -> bool:  # Rev 00210: 0DTE Strategy symbol count
        """
        Send alert when ORB capture completes for all symbols (Rev 00163)
        
        Confirms opening range has been captured and system is ready for SO/ORR signals.
        
        Args:
            symbols_captured: Number of symbols with ORB captured
            capture_time_seconds: Time taken to capture all ORBs
            filtered_count: Number filtered by post-ORB validation (sideways markets)
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            
            # Calculate active symbols (captured - filtered)
            active_symbols = symbols_captured - filtered_count
            
            # Rev 00210: Calculate separate counts for ORB Strategy and 0DTE Strategy
            orb_strategy_captured = orb_strategy_count if orb_strategy_count is not None else symbols_captured
            dte_strategy_captured = dte_strategy_count if dte_strategy_count is not None else 0
            orb_strategy_active = orb_strategy_captured - filtered_count  # Filtered count applies to ORB Strategy
            dte_strategy_active = dte_strategy_captured  # 0DTE symbols not filtered by post-ORB validation
            
            # Build message based on whether ORBs were captured (Rev 00180AE)
            if symbols_captured > 0:
                # ORBs captured successfully
                status_line = "✅ Status: All opening ranges captured successfully!"
                filtered_section = f"\n          • ⛔ <b>Filtered (Sideways):</b> {filtered_count}" if filtered_count > 0 else ""
            else:
                # No ORBs captured (error condition)
                status_line = "💢 No ORBs Captured"
                filtered_section = ""
            
            # Build 0DTE section if data provided (Rev 00209: Enhanced with all 0DTE symbols)
            # Rev 00186: Remove 0DTE data from ORB Capture alert - it should only be in 0DTE-specific alerts
            # Rev 00186: Remove 0DTE data from ORB Capture alert - it should only be in 0DTE-specific alerts
            dte_section = ""
            # Disabled - 0DTE data should not be in ORB Capture alert
            has_dte_data = False
            
            if False:  # Rev 00186: Disabled - 0DTE data removed from ORB Capture alert
                dte_section = "\n🔮 <b>0DTE Strategy ORB Data:</b>\n"
                
                def format_0dte_symbol(symbol_name, orb_data, priority_num=None):
                    """Format 0DTE symbol data with volatility context"""
                    range_pct = orb_data.get('orb_range_pct', 0.0)
                    current_price = orb_data.get('current_price', None)
                    orb_high = orb_data.get('orb_high', 0.0)
                    orb_low = orb_data.get('orb_low', 0.0)
                    orb_open = orb_data.get('orb_open', None)
                    tier = orb_data.get('tier', None)
                    
                    # Tier label
                    tier_label = ""
                    if tier == 1:
                        tier_label = " [Tier 1]"
                    elif tier == 2:
                        tier_label = " [Tier 2]"
                    
                    # Volatility assessment
                    if range_pct >= 0.50:
                        volatility_label = "🔥 HIGH"
                    elif range_pct >= 0.35:
                        volatility_label = "⚡ MODERATE"
                    else:
                        volatility_label = "📊 LOW"
                    
                    # Current price context
                    price_context = ""
                    if current_price and orb_open:
                        price_vs_open = ((current_price - orb_open) / orb_open) * 100 if orb_open > 0 else 0
                        if price_vs_open > 0.1:
                            price_context = f" • Price: ${current_price:.2f} (+{price_vs_open:.2f}%)"
                        elif price_vs_open < -0.1:
                            price_context = f" • Price: ${current_price:.2f} ({price_vs_open:.2f}%)"
                        else:
                            price_context = f" • Price: ${current_price:.2f}"
                    elif current_price:
                        price_context = f" • Price: ${current_price:.2f}"
                    
                    # Position vs ORB range
                    range_position = ""
                    if current_price and orb_high > 0 and orb_low > 0:
                        if current_price > orb_high:
                            range_position = " • Above ORB High 🟢"
                        elif current_price < orb_low:
                            range_position = " • Below ORB Low 🔴"
                        else:
                            range_position = " • Within ORB Range ⚪"
                    
                    prefix = f"{priority_num}) " if priority_num else ""
                    return f"          {prefix}<b>{symbol_name}</b>{tier_label} • Range: {range_pct:.2f}% ({volatility_label}){price_context}{range_position}\n          H=${orb_high:.2f} | L=${orb_low:.2f}\n"
                
                # Priority order: SPX (Tier 1), QQQ (Tier 1), SPY (Tier 1), then others
                priority_order = ['SPX', 'QQQ', 'SPY']
                priority_num = 1
                
                # Add Tier 1 symbols first (SPX, QQQ, SPY)
                if spx_orb_data:
                    dte_section += format_0dte_symbol("SPX", spx_orb_data, str(priority_num))
                    priority_num += 1
                if qqq_orb_data:
                    dte_section += format_0dte_symbol("QQQ", qqq_orb_data, str(priority_num))
                    priority_num += 1
                if spy_orb_data:
                    dte_section += format_0dte_symbol("SPY", spy_orb_data, str(priority_num))
                    priority_num += 1
                
                # Add other 0DTE symbols from dte_orb_data (if provided)
                if dte_orb_data:
                    # Sort by tier (1 first, then 2), then alphabetically
                    sorted_symbols = sorted(
                        dte_orb_data.items(),
                        key=lambda x: (x[1].get('tier', 99), x[0])
                    )
                    
                    for symbol, orb_data_dict in sorted_symbols:
                        # Skip if already added above
                        if symbol in ['SPX', 'QQQ', 'SPY']:
                            continue
                        dte_section += format_0dte_symbol(symbol, orb_data_dict, str(priority_num))
                        priority_num += 1
                
                dte_section += "\n⚡ <b>Next:</b> 0DTE Signal Processing\n          7:15-7:30 AM PT (10:15-10:30 AM ET)"

            # Rev 00210: Build separate sections for ORB Strategy and 0DTE Strategy
            orb_section = f"""📊 <b>Opening Range Capture:</b>
          • <b>Symbols Captured:</b> {orb_strategy_captured}
          • <b>Active Symbols:</b> {orb_strategy_active}{filtered_section}
          • <b>Capture Duration:</b> {capture_time_seconds:.1f} seconds"""
            
            dte_capture_section = ""
            if dte_strategy_captured > 0:
                dte_capture_section = f"""
🔮 <b>0DTE ORB Capture:</b>
          • <b>Symbols Captured:</b> {dte_strategy_captured}
          • <b>Active Symbols:</b> {dte_strategy_active}
          • <b>Capture Duration:</b> {capture_time_seconds:.1f} seconds"""
            
            # Build message
            message = f"""====================================================================

✅ <b>ORB Capture Complete</b>
          Time: {pt_time} ({et_time})

{status_line}

{orb_section}
{dte_capture_section}

⚛️ <b>ORB Window:</b>
          6:30-6:45 AM PT (9:30-9:45 AM ET)
🎯 <b>Next:</b> SO & 0DTE Signal Collection
          7:15-7:30 AM PT (10:15-10:30 AM ET){dte_section}
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"ORB capture complete alert sent - {symbols_captured} symbols, {active_symbols} active")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending ORB capture complete alert: {e}")
            return False
    
    async def send_rapid_exit_alert(self, symbol: str, exit_reason: str,
                                    shares: int, entry_price: float, current_price: float,
                                    peak_price: float, current_pnl_pct: float,
                                    holding_minutes: int, trade_id: str = None,
                                    mode: str = "DEMO") -> bool:
        """
        Send individual rapid exit alert (Rev 00045)
        
        Sent when a position is rapid exited due to:
        - No momentum after 15 minutes
        - Immediate reversal after 5-10 minutes
        
        Args:
            symbol: Symbol being exited
            exit_reason: "NO_MOMENTUM" or "IMMEDIATE_REVERSAL"
            shares: Number of shares
            entry_price: Entry price
            current_price: Current price
            peak_price: Peak price reached
            current_pnl_pct: Current P&L percentage
            holding_minutes: Minutes held
            trade_id: Trade ID
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            
            # Calculate metrics
            position_value = shares * entry_price
            pnl_dollars = shares * (current_price - entry_price)
            peak_pct = ((peak_price - entry_price) / entry_price) * 100
            
            # Format holding time
            hours = int(holding_minutes // 60)
            mins = int(holding_minutes % 60)
            if hours > 0:
                time_str = f"{hours}h {mins}m"
            else:
                time_str = f"{mins} minutes"
            
            # Reason text
            if "NO_MOMENTUM" in exit_reason:
                reason_text = (
                    f"🚨 <b>Exit Reason:</b>\n"
                    f"  Peak movement &lt;+0.3% after 15 minutes\n"
                    f"  Trade shows no momentum - exiting to limit loss"
                )
            else:  # IMMEDIATE_REVERSAL
                reason_text = (
                    f"🚨 <b>Exit Reason:</b>\n"
                    f"  Down {current_pnl_pct:+.2f}% within {holding_minutes} minutes\n"
                    f"  Immediate reversal detected"
                )
            
            # Build message - Rev 00045: Compact format
            message = f"""====================================================================

🚨 <b>RAPID EXIT - {exit_reason.replace('_', ' ').title()}</b>

⏰ <b>Time Held:</b> {time_str}

📉 <b>{shares} {symbol} @ ${entry_price:.2f}</b> • <b>${position_value:.2f}</b>
  • <b>Current P&amp;L:</b> {current_pnl_pct:+.2f}% (${pnl_dollars:+.2f})
  • <b>Peak:</b> ${peak_price:.2f} ({peak_pct:+.2f}%)
  • Trade ID:
  • {trade_id if trade_id else f"MOCK_{symbol}"}

{reason_text}

💡 <b>Action:</b> Position closed at {current_pnl_pct:+.2f}%
   Early exit to prevent further loss"""
            
            # Send alert
            await self._send_telegram_message(message)
            
            log.info(f"✅ Sent rapid exit alert for {symbol} ({exit_reason})")
            return True
            
        except Exception as e:
            log.error(f"Error sending rapid exit alert: {e}")
            return False
    
    async def send_letting_winners_run_aggregated(self, positions_held: list, 
                                                  portfolio_health: dict,
                                                  mode: str = "DEMO") -> bool:
        """
        Send aggregated alert for positions being held despite meeting rapid exit criteria (Rev 00045)
        
        This alert is sent when portfolio is HEALTHY and rapid exits are DISABLED,
        showing which positions would have been rapid exited but are being held instead.
        
        Args:
            positions_held: List of dicts with position info (symbol, shares, entry_price, peak_pct, current_pnl, holding_minutes)
            portfolio_health: Dict with win_rate, avg_pnl
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            
            # Build position list
            position_lines = []
            for i, pos in enumerate(positions_held, 1):
                symbol = pos['symbol']
                shares = pos['shares']
                entry_price = pos['entry_price']
                position_value = shares * entry_price
                trade_id = pos.get('trade_id', f"MOCK_{symbol}")
                
                position_lines.append(
                    f"{i}) 🟢 • <b>BUY {shares}</b> • <b>{symbol} @ ${entry_price:.2f}</b> • <b>${position_value:.2f}</b>\n"
                    f"          Trade ID: \n"
                    f"          {trade_id}"
                )
            
            positions_text = '\n\n'.join(position_lines)
            
            # Get average holding time
            avg_holding = sum([p.get('holding_minutes', 18) for p in positions_held]) / len(positions_held) if positions_held else 18
            
            # Build message
            message = f"""====================================================================

ℹ️ <b>Trade Monitoring - Letting Winners Run</b>
{mode_emoji} Mode: {mode}

⏰ <b>Time Held:</b> ~{int(avg_holding)} minutes (average)

ℹ️ <b>Rapid Exit Criteria Met:</b>
  Peak &lt;+0.3% after 15 minutes
  Normally would trigger rapid exit...

✅ <b>BUT - Portfolio Health: HEALTHY</b>
  • Win rate: {portfolio_health.get('win_rate', 52):.0f}%
  • Avg P&amp;L: {portfolio_health.get('avg_pnl', 0.3):+.1f}%
  • Rapid exits: DISABLED

💼 <b>Positions Held:</b> {len(positions_held)}

{positions_text}

💡 <b>Action:</b> Holding positions
   Letting trades develop (good day strategy)
   Will use normal 1.5% trailing stop"""
            
            # Send alert
            await self._send_telegram_message(message)
            
            log.info(f"✅ Sent aggregated 'Letting Winners Run' alert for {len(positions_held)} positions")
            return True
            
        except Exception as e:
            log.error(f"Error sending letting winners run alert: {e}")
            return False
    
    async def send_holiday_alert(self, holiday_name: str, skip_reason: str) -> bool:
        """
        Send alert on holidays (Rev 00087)
        
        Handles both MARKET_CLOSED (bank holidays) and LOW_VOLUME (non-bank holidays).
        Sent at 5:30 AM PT instead of Good Morning alert.
        
        Args:
            holiday_name: Name of the holiday (e.g., "Halloween", "Christmas Day")
            skip_reason: "MARKET_CLOSED" or "LOW_VOLUME"
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            day_name = now_et.strftime('%A, %B %d, %Y')
            
            # Determine emoji and message based on reason
            if skip_reason == "MARKET_CLOSED":
                # Bank holiday - market is closed
                emoji = "🏖️"
                reason_msg = "U.S. stock market is closed today. Trading disabled to preserve capital quality."
            else:
                # Low-volume holiday - market is open but we skip trading
                emoji = "🎃"
                reason_msg = "Market is open, but volume is typically low on this holiday. Trading disabled to preserve capital quality."
            
            # Build message (user's exact format)
            message = f"""====================================================================

{emoji} <b>Holiday! - {holiday_name}</b>
          {day_name}

🎭 <b>No Trading Today!</b> ☁️🏖️🏝️⛱️🌤️☁️☁️

🚫 <b>Status:</b>
          Trading DISABLED today.

💡 <b>Why:</b>
          {reason_msg}

✅ <b>System Status:</b> 
          Normal

🔍 <b>Next Trading:</b> 
          System will resume at next normal trading day

🌐 <b>Dashboard:</b> 
          https://easy-trading-oauth-v2.web.app

"""
            
            success = await self._send_telegram_message(message, AlertLevel.INFO)
            
            if success:
                log.info(f"Holiday alert sent - {holiday_name} ({skip_reason})")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending holiday alert: {e}")
            return False
    
    # NOTE (Rev 00180AE): Old send_end_of_day_report() removed - duplicate of line 454
    # The unified version at line 454 has account_balance parameter and updated formatting
    
    # ============================================================================================================================================
    # 0DTE STRATEGY ALERTS (Rev 00206)
    # ============================================================================================================================================
    
    async def send_0dte_orb_capture_alert(self, spx_orb_data: Optional[Dict[str, Any]] = None,
                                           qqq_orb_data: Optional[Dict[str, Any]] = None, 
                                           spy_orb_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        [DEPRECATED - Rev 00209] 
        This alert is no longer used. 0DTE ORB data is now included in the unified 
        send_orb_capture_complete_alert() which shows both ORB Strategy and 0DTE Strategy data.
        
        Kept for backward compatibility with test files.
        
        Args:
            spx_orb_data: SPX ORB data (high, low, range_pct, volatility_score) - Priority 1
            qqq_orb_data: QQQ ORB data (high, low, range_pct, volatility_score) - Priority 2
            spy_orb_data: SPY ORB data (high, low, range_pct, volatility_score) - Priority 3
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Format SPX data (Priority 1)
            spx_high = spx_orb_data.get('orb_high', 0.0) if spx_orb_data else 0.0
            spx_low = spx_orb_data.get('orb_low', 0.0) if spx_orb_data else 0.0
            spx_range_pct = spx_orb_data.get('orb_range_pct', 0.0) if spx_orb_data else 0.0
            spx_volatility = spx_orb_data.get('orb_volatility_score', 0.0) if spx_orb_data else 0.0
            
            # Format QQQ data (Priority 2)
            qqq_high = qqq_orb_data.get('orb_high', 0.0) if qqq_orb_data else 0.0
            qqq_low = qqq_orb_data.get('orb_low', 0.0) if qqq_orb_data else 0.0
            qqq_range_pct = qqq_orb_data.get('orb_range_pct', 0.0) if qqq_orb_data else 0.0
            qqq_volatility = qqq_orb_data.get('orb_volatility_score', 0.0) if qqq_orb_data else 0.0
            
            # Format SPY data (Priority 3)
            spy_high = spy_orb_data.get('orb_high', 0.0) if spy_orb_data else 0.0
            spy_low = spy_orb_data.get('orb_low', 0.0) if spy_orb_data else 0.0
            spy_range_pct = spy_orb_data.get('orb_range_pct', 0.0) if spy_orb_data else 0.0
            spy_volatility = spy_orb_data.get('orb_volatility_score', 0.0) if spy_orb_data else 0.0
            
            # Build opening ranges section (Priority order: SPX → QQQ → SPY)
            ranges_text = ""
            if spx_range_pct > 0:
                ranges_text += f"          <b>• SPX:</b> High ${spx_high:.2f}, Low ${spx_low:.2f}, Range {spx_range_pct:.2f}% (Priority 1)\n"
            if qqq_range_pct > 0:
                ranges_text += f"          <b>• QQQ:</b> High ${qqq_high:.2f}, Low ${qqq_low:.2f}, Range {qqq_range_pct:.2f}% (Priority 2)\n"
            if spy_range_pct > 0:
                ranges_text += f"          <b>• SPY:</b> High ${spy_high:.2f}, Low ${spy_low:.2f}, Range {spy_range_pct:.2f}% (Priority 3)\n"
            
            if not ranges_text:
                ranges_text = "          <i>No ORB data available</i>\n"
            
            message = f"""====================================================================

🔮 💠 <b>0DTE ORB Capture Complete</b>
          Time: {pt_time} ({et_time})

🚦 <b>Opening Ranges Captured:</b>
{ranges_text}
🔍 <b>Next:</b> Options Signal Collection
          7:15-7:30 AM PT (10:15-10:30 AM ET)
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"0DTE ORB Capture alert sent - SPX Range: {spx_range_pct:.2f}%, QQQ Range: {qqq_range_pct:.2f}%, SPY Range: {spy_range_pct:.2f}%")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending 0DTE ORB Capture alert: {e}")
            return False
    
    async def send_options_signal_collection_alert(self, orb_signals_received: int,
                                                   options_signals_qualified: int,
                                                   qualified_signals: List[Dict[str, Any]],
                                                   mode: str = "DEMO",
                                                   spx_orb_data: Optional[Dict[str, Any]] = None,
                                                   qqq_orb_data: Optional[Dict[str, Any]] = None,
                                                   spy_orb_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        [DEPRECATED - Rev 00220] 
        This alert is no longer used. 0DTE signals are now included in the unified 
        send_so_signal_collection() which shows both ORB Strategy and 0DTE Strategy signals.
        
        Kept for backward compatibility with test files.
        
        Args:
            orb_signals_received: Number of ORB signals received
            options_signals_qualified: Number of options signals that passed Convex Eligibility Filter
            qualified_signals: List of qualified DTE0Signal objects with details
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            
            # Build qualified signals list
            signals_text = ""
            if qualified_signals:
                for i, signal in enumerate(qualified_signals, 1):
                    symbol = signal.get('symbol', 'UNKNOWN')
                    option_type = signal.get('option_type', 'CALL')
                    option_type_label = 'CALL' if option_type == 'call' else 'PUT'
                    direction_emoji = "🟢" if option_type == 'call' else "🔴"
                    eligibility_score = signal.get('eligibility_score', 0.0)
                    target_delta = signal.get('target_delta', 0.0)
                    spread_width = signal.get('spread_width', 0.0)
                    
                    signals_text += f"{i}) {direction_emoji} <b>{symbol} {option_type_label}</b>\n"
                    # Add blank line between signals, but only one blank line before "Next:" for last signal
                    if i < len(qualified_signals):
                        signals_text += f"          Score: <b>{eligibility_score:.2f}</b> • Delta: <b>{target_delta:.2f}</b> • Width: <b>${spread_width:.0f}</b>\n\n"
                    else:
                        signals_text += f"          Score: <b>{eligibility_score:.2f}</b> • Delta: <b>{target_delta:.2f}</b> • Width: <b>${spread_width:.0f}</b>\n"
            else:
                signals_text = "          <i>No signals qualified</i>\n"
            
            # Build ORB ranges section if data provided
            orb_section = ""
            if spx_orb_data or qqq_orb_data or spy_orb_data:
                orb_section = "\n🎯 <b>Opening Ranges Captured:</b>\n"
                if spx_orb_data:
                    orb_section += f"          • <b>SPX:</b> H=${spx_orb_data['orb_high']:.2f}, L=${spx_orb_data['orb_low']:.2f}, Range={spx_orb_data['orb_range_pct']:.2f}% (Priority 1)\n"
                if qqq_orb_data:
                    orb_section += f"          • <b>QQQ:</b> H=${qqq_orb_data['orb_high']:.2f}, L=${qqq_orb_data['orb_low']:.2f}, Range={qqq_orb_data['orb_range_pct']:.2f}% (Priority 2)\n"
                if spy_orb_data:
                    orb_section += f"          • <b>SPY:</b> H=${spy_orb_data['orb_high']:.2f}, L=${spy_orb_data['orb_low']:.2f}, Range={spy_orb_data['orb_range_pct']:.2f}% (Priority 3)\n"
                orb_section += "\n"

            message = f"""====================================================================

🔮 💠 <b>0DTE Signal Collection</b> | {mode} Mode
          Time: {pt_time} ({et_time}){orb_section}
📊 <b>Results:</b>
          <b>• ORB Signals Received:</b> {orb_signals_received}
          <b>• Convex Eligibility Filter Applied</b>
          <b>• Options Signals Qualified:</b> {options_signals_qualified}

✅ <b>Qualified Signals:</b>
{signals_text}
🔍 <b>Next:</b> Red Day Filter Check
          7:30 AM PT (10:30 AM ET)
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"Options Signal Collection alert sent - {options_signals_qualified} qualified from {orb_signals_received} ORB signals")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options Signal Collection alert: {e}")
            return False
    
    async def send_options_execution_alert(self, executed_positions: List[Dict[str, Any]],
                                          total_capital_deployed: float,
                                          account_balance: float = 1000.0,
                                          mode: str = "DEMO",
                                          rejected_signals: Optional[List[Dict[str, Any]]] = None,
                                          failed_count: int = 0,
                                          hard_gated_symbols: Optional[List[Dict[str, Any]]] = None,
                                          dte_symbols_count: Optional[int] = None,  # Rev 00230: 0DTE Symbols count
                                          dte_options_found: Optional[int] = None) -> bool:  # Rev 00230: 0DTE Options Found count
        """
        Send 0DTE Options Execution alert (Rev 00230: Enhanced with momentum and strategy details)
        
        Shows complete execution details including:
        - Momentum scores for each trade
        - Strategy types (Long Call/Put, Debit Spread, ITM Prob, Lotto, etc.)
        - Priority ranking
        - Hard Gate status (all executed trades passed)
        
        Args:
            executed_positions: List of executed OptionsPosition objects with trade details
            total_capital_deployed: Total capital deployed in options trades
            account_balance: Current account balance
            mode: Trading mode (DEMO or LIVE)
            rejected_signals: Optional list of rejected signals (insufficient capital, etc.)
            failed_count: Number of trades that failed to execute
            hard_gated_symbols: Optional list of Hard Gated symbols
            dte_symbols_count: Optional count of 0DTE symbols monitored
            dte_options_found: Optional count of 0DTE options found
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Strategy type labels for display (Rev 00230)
            strategy_labels = {
                'long_call': 'Long Call',
                'long_put': 'Long Put',
                'debit_spread': 'Debit Spread',
                'itm_probability_spread': 'ITM Prob',
                'lotto': 'Lotto',
                'no_trade': 'NO TRADE',
                'momentum_scalper': 'Scalper'
            }
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Mode emoji
            mode_emoji = "🎮" if mode == "DEMO" else "💰"
            
            # Build trade list
            trade_lines = []
            for i, position in enumerate(executed_positions, 1):
                symbol = position.get('symbol', 'UNKNOWN')
                position_type = position.get('position_type', 'debit_spread')
                debit_spread = position.get('debit_spread')
                credit_spread = position.get('credit_spread')
                lotto_contract = position.get('lotto_contract')
                entry_price = position.get('entry_price', 0.0)
                quantity = position.get('quantity', 1)
                position_id = position.get('position_id', 'N/A')
                
                # Get priority ranking data (Rev 00225: Priority Ranking System)
                priority_rank = position.get('priority_rank', 0)
                priority_score = position.get('priority_score', 0.0)
                capital_allocated = position.get('capital_allocated', 0.0)
                account_balance = position.get('account_balance', 5000.0)
                capital_pct = (capital_allocated / account_balance * 100) if account_balance > 0 else 0.0
                
                # Get confidence from signal if available
                confidence = position.get('confidence', 0.0)
                confidence_pct = int(confidence * 100) if confidence > 0 else 0
                
                if position_type == 'debit_spread' and debit_spread:
                    option_type = debit_spread.get('option_type', 'call')
                    option_type_label = 'CALL' if option_type == 'call' else 'PUT'
                    direction_emoji = "🟢" if option_type == 'call' else "🔴"
                    long_strike = debit_spread.get('long_strike', 0.0)
                    short_strike = debit_spread.get('short_strike', 0.0)
                    debit_cost = debit_spread.get('debit_cost', 0.0)
                    max_profit = debit_spread.get('max_profit', 0.0)
                    
                    # Get contract prices and delta from contract dictionaries
                    long_contract = debit_spread.get('long_contract', {})
                    short_contract = debit_spread.get('short_contract', {})
                    long_price = long_contract.get('mid_price', 0.0) if isinstance(long_contract, dict) else 0.0
                    short_price = short_contract.get('mid_price', 0.0) if isinstance(short_contract, dict) else 0.0
                    long_delta = long_contract.get('delta', 0.0) if isinstance(long_contract, dict) else 0.0
                    
                    # Format expiry date (YYYY-MM-DD -> MMDDYY or TODAY)
                    expiry = debit_spread.get('expiry', '')
                    if expiry:
                        expiry_formatted = expiry.replace('-', '')[-6:] if len(expiry.replace('-', '')) >= 6 else 'TODAY'
                    else:
                        expiry_formatted = 'TODAY'
                    
                    # Rev 00230: Get momentum score and strategy type from position
                    momentum_score = position.get('momentum_score', 0.0)
                    strategy_type = position.get('strategy_type', 'debit_spread')
                    strategy_label = strategy_labels.get(strategy_type, strategy_type) if 'strategy_labels' in locals() else strategy_type
                    
                    # Build priority ranking line (Rev 00225)
                    priority_line = ""
                    if priority_rank > 0:
                        priority_line = f"          <b>Rank #{priority_rank}</b> • Priority Score <b>{priority_score:.3f}</b>\n"
                    
                    # Build confidence and momentum line (unified format)
                    confidence_momentum_line = ""
                    if confidence_pct > 0 or momentum_score > 0:
                        parts = []
                        if confidence_pct > 0:
                            parts.append(f"<b>{confidence_pct}%</b> Confidence")
                        if momentum_score > 0:
                            parts.append(f"<b>{momentum_score:.0f}/100</b> Momentum")
                        confidence_momentum_line = " • ".join(parts) + "\n"
                    
                    trade_lines.append(
                        f"{i}) {direction_emoji} <b>{quantity}</b> • <b>{symbol} {option_type_label} Debit Spread</b>\n"
                        f"{priority_line}"
                        f"          {confidence_momentum_line}"
                        f"          <b>{long_delta:.2f}</b> Delta\n"
                        f"          Long: {symbol} {expiry_formatted}{option_type[0].upper()}{long_strike:.0f} @ ${long_price:.2f}\n"
                        f"          Short: {symbol} {expiry_formatted}{option_type[0].upper()}{short_strike:.0f} @ ${short_price:.2f}\n"
                        f"          Net Debit: <b>${debit_cost:.2f}</b> • Max Profit: <b>${max_profit:.2f}</b>\n"
                        f"          {capital_pct:.1f}% Of Account\n"
                        f"          Trade ID: {position_id}"
                    )
                elif position_type == 'credit_spread' and credit_spread:
                    option_type = credit_spread.get('option_type', 'put')
                    option_type_label = 'PUT' if option_type == 'put' else 'CALL'
                    direction_emoji = "🔴" if option_type == 'put' else "🟢"
                    short_strike = credit_spread.get('short_strike', 0.0)
                    long_strike = credit_spread.get('long_strike', 0.0)
                    credit_received = credit_spread.get('credit_received', 0.0)
                    max_profit = credit_spread.get('max_profit', 0.0)
                    
                    # Get contract prices and delta from contract dictionaries
                    short_contract = credit_spread.get('short_contract', {})
                    long_contract = credit_spread.get('long_contract', {})
                    short_price = short_contract.get('mid_price', 0.0) if isinstance(short_contract, dict) else 0.0
                    long_price = long_contract.get('mid_price', 0.0) if isinstance(long_contract, dict) else 0.0
                    short_delta = short_contract.get('delta', 0.0) if isinstance(short_contract, dict) else 0.0
                    
                    # Format expiry date
                    expiry = credit_spread.get('expiry', '')
                    if expiry:
                        expiry_formatted = expiry.replace('-', '')[-6:] if len(expiry.replace('-', '')) >= 6 else 'TODAY'
                    else:
                        expiry_formatted = 'TODAY'
                    
                    # Rev 00230: Get momentum score and strategy type from position
                    momentum_score = position.get('momentum_score', 0.0)
                    strategy_type = position.get('strategy_type', 'debit_spread')
                    
                    # Format strategy type for display
                    strategy_labels = {
                        'long_call': 'Long Call',
                        'long_put': 'Long Put',
                        'debit_spread': 'Debit Spread',
                        'itm_probability_spread': 'ITM Prob',
                        'lotto': 'Lotto',
                        'no_trade': 'NO TRADE',
                        'momentum_scalper': 'Scalper'
                    }
                    strategy_label = strategy_labels.get(strategy_type, strategy_type)
                    
                    # Build priority ranking line (Rev 00225)
                    priority_line = ""
                    if priority_rank > 0:
                        priority_line = f"          <b>Rank #{priority_rank}</b> • Priority Score <b>{priority_score:.3f}</b>\n"
                    
                    # Build confidence and momentum line (unified format)
                    confidence_momentum_line = ""
                    if confidence_pct > 0 or momentum_score > 0:
                        parts = []
                        if confidence_pct > 0:
                            parts.append(f"<b>{confidence_pct}%</b> Confidence")
                        if momentum_score > 0:
                            parts.append(f"<b>{momentum_score:.0f}/100</b> Momentum")
                        confidence_momentum_line = " • ".join(parts) + "\n"
                    
                    trade_lines.append(
                        f"{i}) {direction_emoji} <b>{quantity}</b> • <b>{symbol} {option_type_label} Credit Spread</b>\n"
                        f"{priority_line}"
                        f"          {confidence_momentum_line}"
                        f"          <b>{short_delta:.2f}</b> Delta\n"
                        f"          Short: {symbol} {expiry_formatted}{option_type[0].upper()}{short_strike:.0f} @ ${short_price:.2f}\n"
                        f"          Long: {symbol} {expiry_formatted}{option_type[0].upper()}{long_strike:.0f} @ ${long_price:.2f}\n"
                        f"          Net Credit: <b>${credit_received:.2f}</b> • Max Profit: <b>${max_profit:.2f}</b>\n"
                        f"          {capital_pct:.1f}% Of Account\n"
                        f"          Trade ID: {position_id}"
                    )
                elif position_type == 'lotto' and lotto_contract:
                    option_type = lotto_contract.get('option_type', 'call')
                    option_type_label = 'CALL' if option_type == 'call' else 'PUT'
                    direction_emoji = "🟢" if option_type == 'call' else "🔴"
                    strike = lotto_contract.get('strike', 0.0)
                    premium = lotto_contract.get('premium', 0.0)
                    target_delta = lotto_contract.get('delta', 0.0)
                    
                    expiry = lotto_contract.get('expiry', '')
                    expiry_formatted = expiry.replace('-', '')[-6:] if expiry else 'TODAY'
                    
                    # Rev 00230: Get priority ranking data (unified format)
                    priority_rank = position.get('priority_rank', 0)
                    priority_score = position.get('priority_score', 0.0)
                    confidence = position.get('confidence', 0.0)
                    confidence_pct = int(confidence * 100) if confidence > 0 else 0
                    momentum_score = position.get('momentum_score', 0.0)
                    
                    # Build priority ranking line (unified format)
                    priority_line = ""
                    if priority_rank > 0:
                        priority_line = f"          <b>Rank #{priority_rank}</b> • Priority Score <b>{priority_score:.3f}</b>\n"
                    
                    # Build confidence and momentum line (unified format)
                    confidence_momentum_line = ""
                    if confidence_pct > 0 or momentum_score > 0:
                        parts = []
                        if confidence_pct > 0:
                            parts.append(f"<b>{confidence_pct}%</b> Confidence")
                        if momentum_score > 0:
                            parts.append(f"<b>{momentum_score:.0f}/100</b> Momentum")
                        confidence_momentum_line = " • ".join(parts) + "\n"
                    
                    trade_lines.append(
                        f"{i}) {direction_emoji} <b>{quantity}</b> • <b>{symbol} {option_type_label} Lotto</b>\n"
                        f"{priority_line}"
                        f"          {confidence_momentum_line}"
                        f"          <b>{target_delta:.2f}</b> Delta\n"
                        f"          Strike: {symbol} {expiry_formatted}{option_type[0].upper()}{strike:.0f} @ ${premium:.2f}\n"
                        f"          Premium: <b>${premium:.2f}</b>\n"
                        f"          Trade ID: {position_id}"
                    )
            
            trades_text = "\n\n".join(trade_lines) if trade_lines else "          <i>No trades executed</i>\n"
            
            # Calculate deployment percentage
            deployment_pct = (total_capital_deployed / account_balance * 100) if account_balance > 0 else 0.0
            
            # Rev 00230: Build 0DTE Summary section at the top (with Rejected, Failed, Hard Gated)
            filtered_count = len(rejected_signals) if rejected_signals else 0
            
            # Calculate average momentum score
            momentum_scores = [p.get('momentum_score', 0.0) for p in executed_positions if p.get('momentum_score', 0.0) > 0]
            avg_momentum = sum(momentum_scores) / len(momentum_scores) if momentum_scores else 0.0
            
            # Count strategy types
            strategy_counts = {}
            for p in executed_positions:
                st = p.get('strategy_type', 'debit_spread')
                strategy_counts[st] = strategy_counts.get(st, 0) + 1
            
            strategy_summary = ""
            if strategy_counts:
                strategy_summary = ", ".join([f"{v}x {strategy_labels.get(k, k)}" for k, v in strategy_counts.items()])
            
            # Build summary section
            dte_symbols_display = dte_symbols_count if dte_symbols_count is not None else 38  # Default if not provided
            dte_options_found_display = dte_options_found if dte_options_found is not None else len(executed_positions) + filtered_count  # Default if not provided
            
            summary_section = f"""🎙️ <b>0DTE Summary (7:15 AM PT):</b>
          • <b>0DTE Symbols:</b> {dte_symbols_display}
          • <b>0DTE Options Found:</b> {dte_options_found_display}
          • <b>Filtered (Expensive):</b> {filtered_count}
          • <b>Failed Executions:</b> {failed_count}"""
            
            if avg_momentum > 0:
                summary_section += f"\n          • <b>Avg Momentum:</b> {avg_momentum:.0f}/100"
            
            # Build execution section
            if len(executed_positions) > 0:
                execution_section = f"""💼 <b>0DTE Options Executed:</b> {len(executed_positions)}

{trades_text}

💰 <b>Capital Deployment:</b>
          • <b>Deployed:</b> ${total_capital_deployed:.2f} / ${account_balance:.2f} ({deployment_pct:.1f}%)

🛡️ <b>Monitoring:</b> All positions tracked (every 30 seconds)"""
            else:
                # No trades executed
                total_rejected = len(rejected_signals) if rejected_signals else 0
                execution_section = f"""⚠️ <b>NO 0DTE OPTIONS TRADES EXECUTED</b>

All {total_rejected} signals were REJECTED or FAILED.

💡 <b>Possible Reasons:</b>
• Insufficient capital
• Options chain unavailable
• Strike selection failed
• Red Day filter blocked execution

📊 <b>System Status:</b> Ready for next trading opportunity"""
            
            message = f"""====================================================================

🔮 <b>0DTE Options Execution</b> | {mode} Mode
          Time: {pt_time} ({et_time})

{summary_section}

{execution_section}
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                if len(executed_positions) > 0:
                    log.info(f"0DTE Strategy Options Execution alert sent - {len(executed_positions)} trades, ${total_capital_deployed:.2f} deployed")
                else:
                    log.warning(f"0DTE Strategy Options Execution alert sent - 0 trades executed")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options Execution alert: {e}")
            return False
    
    async def send_options_position_exit_alert(self, position: Dict[str, Any],
                                              exit_price: float,
                                              exit_reason: str,
                                              holding_time_minutes: int = 0,
                                              mode: str = "DEMO") -> bool:
        """
        Send individual Options Position Exit alert
        
        Args:
            position: OptionsPosition dict with position details
            exit_price: Exit price
            exit_reason: Exit reason (hard_stop, invalidation_stop, time_stop, profit_target, runner_target, eod_close)
            holding_time_minutes: How long position was held
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            symbol = position.get('symbol', 'UNKNOWN')
            entry_price = position.get('entry_price', 0.0)
            quantity = position.get('quantity', 1)
            position_id = position.get('position_id', 'N/A')
            position_type = position.get('position_type', 'debit_spread')
            realized_pnl = position.get('realized_pnl', 0.0)
            
            # Calculate P&L
            pnl_dollars = realized_pnl
            pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            
            # Exit reason emoji and description
            exit_reasons = {
                'hard_stop': ('🛑', 'Hard Stop'),
                'invalidation_stop': ('📉', 'Invalidation Stop'),
                'time_stop': ('⏰', 'Time Stop'),
                'fail_safe': ('🚨', 'Fail-Safe Exit'),
                'profit_target': ('💰', 'Profit Target Hit'),
                'runner_target': ('🚀', 'Runner Target Hit'),
                'eod_close': ('📉', 'End of Day Close'),
                'health_emergency': ('🚨', 'Health Emergency Exit')
            }
            
            reason_emoji, reason_desc = exit_reasons.get(exit_reason.lower(), ('🔚', exit_reason))
            
            # P&L emoji and sign
            if pnl_pct > 0:
                pnl_emoji = "💰"
                pnl_sign = "+"
            else:
                pnl_emoji = "📉"
                pnl_sign = ""
            
            # Calculate holding time display
            if holding_time_minutes > 60:
                hours = holding_time_minutes // 60
                minutes = holding_time_minutes % 60
                holding_display = f"{hours}h {minutes}m"
            else:
                holding_display = f"{holding_time_minutes}m"
            
            # Format position type
            position_type_label = "Debit Spread" if position_type == 'debit_spread' else "Lotto"
            debit_spread = position.get('debit_spread')
            if debit_spread:
                option_type = debit_spread.get('option_type', 'call')
                option_type_label = 'CALL' if option_type == 'call' else 'PUT'
                position_type_label = f"{symbol} {option_type_label} Debit Spread"
            
            message = f"""====================================================================

🔮 💠 <b>OPTION CLOSED</b> | {mode} Mode
          Time: {pt_time} ({et_time})

1) {pnl_emoji} <b>{pnl_sign}{pnl_pct:.2f}% {pnl_sign}${abs(pnl_dollars):.2f}</b>
          {position_type_label}
          <b>Entry:</b> ${entry_price:.2f} • <b>Exit:</b> ${exit_price:.2f}
          <b>Reason:</b> {reason_desc}
          
          <b>Holding Time:</b> {holding_display}
          <b>Trade ID:</b>
          {position_id}

📊 Position closed by Options Exit Manager
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"Options Position Exit alert sent for {symbol} - {reason_desc} - P&L: {pnl_sign}{pnl_pct:.2f}%")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options Position Exit alert: {e}")
            return False
    
    async def send_options_aggregated_exit_alert(self, closed_positions: List[Dict[str, Any]],
                                                exit_reason: str,
                                                mode: str = "DEMO") -> bool:
        """
        Send aggregated Options Exit alert for multiple position closes
        
        Used for: EOD close, emergency exits, batch exits
        
        Args:
            closed_positions: List of closed OptionsPosition dicts
            exit_reason: Common exit reason
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            if not closed_positions:
                return False
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Exit reason emoji
            exit_reasons = {
                'eod_close': '📉',
                'health_emergency': '🚨',
                'fail_safe': '🚨'
            }
            reason_emoji = exit_reasons.get(exit_reason.lower(), '📉')
            
            # Calculate total P&L first
            total_pnl = 0.0
            for pos in closed_positions:
                realized_pnl = pos.get('realized_pnl', 0.0)
                total_pnl += realized_pnl
            
            # Format total P&L
            if total_pnl >= 0:
                total_pnl_str = f"+${total_pnl:.2f}"
            else:
                total_pnl_str = f"-${abs(total_pnl):.2f}"
            
            # Build message header
            message = f"""====================================================================

🔮 💠 <b>OPTIONS CLOSED</b> | {mode} Mode
          Time: {pt_time} ({et_time})

💰 <b>Total P&L:</b> {total_pnl_str}

"""
            
            # Add each position
            for i, pos in enumerate(closed_positions, 1):
                symbol = pos.get('symbol', 'UNKNOWN')
                entry_price = pos.get('entry_price', 0.0)
                exit_price = pos.get('current_value', entry_price)  # Use current_value as exit price
                quantity = pos.get('quantity', 1)
                position_id = pos.get('position_id', 'N/A')
                position_type = pos.get('position_type', 'debit_spread')
                realized_pnl = pos.get('realized_pnl', 0.0)
                
                # Calculate P&L
                pnl_dollars = realized_pnl
                pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
                total_pnl += pnl_dollars
                
                # P&L emoji and sign
                if pnl_pct > 0:
                    pnl_emoji = "💰"
                    pnl_sign = "+"
                else:
                    pnl_emoji = "📉"
                    pnl_sign = ""
                
                # Calculate holding time
                entry_time = pos.get('entry_time')
                if entry_time:
                    if isinstance(entry_time, str):
                        from dateutil.parser import parse
                        entry_time = parse(entry_time)
                    holding_minutes = int((now_pt.replace(tzinfo=None) - entry_time.replace(tzinfo=None)).total_seconds() / 60)
                else:
                    holding_minutes = 0
                
                if holding_minutes > 60:
                    hours = holding_minutes // 60
                    minutes = holding_minutes % 60
                    holding_display = f"{hours}h {minutes}m"
                else:
                    holding_display = f"{holding_minutes}m"
                
                # Format position type
                position_type_label = "Debit Spread" if position_type == 'debit_spread' else "Lotto"
                debit_spread = pos.get('debit_spread')
                if debit_spread:
                    option_type = debit_spread.get('option_type', 'call')
                    option_type_label = 'CALL' if option_type == 'call' else 'PUT'
                    position_type_label = f"{symbol} {option_type_label} Debit Spread"
                
                # Format P&L
                if pnl_pct >= 0:
                    pnl_pct_str = f"+{pnl_pct:.2f}%"
                else:
                    pnl_pct_str = f"{pnl_pct:.2f}%"
                
                if pnl_dollars >= 0:
                    pnl_dollars_str = f"+${pnl_dollars:.2f}"
                else:
                    pnl_dollars_str = f"-${abs(pnl_dollars):.2f}"
                
                message += f"""{i}) {pnl_emoji} <b>{pnl_pct_str}</b> {pnl_dollars_str}
          {position_type_label}
          <b>Entry:</b> ${entry_price:.2f} • <b>Exit:</b> ${exit_price:.2f}
          <b>Reason:</b> {exit_reason}
          
          <b>Holding Time:</b> {holding_display}
          <b>Trade ID:</b>
          {position_id}

"""
            
            message += f"📊 Positions closed by Options Exit Manager"
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"Options Aggregated Exit alert sent for {len(closed_positions)} positions - {exit_reason}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options Aggregated Exit alert: {e}")
            return False
    
    async def send_options_partial_profit_alert(self, position: Dict[str, Any],
                                               partial_details: Dict[str, Any],
                                               mode: str = "DEMO") -> bool:
        """
        Send Options Partial Profit alert when automated exit triggers (+60% sell 50%, +120% sell 25%)
        
        Args:
            position: OptionsPosition dict
            partial_details: Partial profit details (target_name, target_pct, partial_quantity, partial_profit)
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            symbol = position.get('symbol', 'UNKNOWN')
            position_id = position.get('position_id', 'N/A')
            target_name = partial_details.get('target_name', 'unknown')
            target_pct = partial_details.get('target_pct', 0.0)
            partial_quantity = partial_details.get('partial_quantity', 0)
            remaining_quantity = partial_details.get('remaining_quantity', 0)
            partial_profit = partial_details.get('partial_profit', 0.0)
            
            # Format target name and header
            if target_name == 'first_target_60pct':
                target_label = "First Target (+60%)"
                action_label = "Sold 50%"
                header_text = "FIRST TARGET EXIT"
            elif target_name == 'second_target_120pct':
                target_label = "Second Target (+120%)"
                action_label = "Sold 25%"
                header_text = "SECOND TARGET EXIT"
            else:
                target_label = f"Target (+{target_pct*100:.0f}%)"
                action_label = "Partial Profit"
                header_text = "TARGET EXIT"
            
            message = f"""====================================================================

🔮 💠 <b>{header_text}</b> | {mode} Mode
          Time: {pt_time} ({et_time})

1) 💰 <b>{target_label}</b>
          {symbol} Options Position
          • <b>{action_label}:</b> {partial_quantity} contracts
          • <b>Remaining:</b> {remaining_quantity} contracts (runner)
          • <b>Profit Locked:</b> +${partial_profit:.2f}
          
          <b>Trade ID:</b>
          {position_id}

📊 Automated exit system profit capture
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"Options Partial Profit alert sent for {symbol} - {target_label} - Profit: ${partial_profit:.2f}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options Partial Profit alert: {e}")
            return False
    
    async def send_options_runner_exit_alert(self, position: Dict[str, Any],
                                            exit_signal: Dict[str, Any],
                                            mode: str = "DEMO") -> bool:
        """
        Send Options Runner Exit alert when runner exits (VWAP/ORB reclaim or time cutoff)
        
        Args:
            position: OptionsPosition dict
            exit_signal: ExitSignal dict with exit details
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            symbol = position.get('symbol', 'UNKNOWN')
            position_id = position.get('position_id', 'N/A')
            exit_price = exit_signal.get('exit_price', 0.0)
            pnl_pct = exit_signal.get('pnl_pct', 0.0)
            pnl_dollars = exit_signal.get('pnl_dollar', 0.0)
            exit_reasons = exit_signal.get('details', {}).get('exit_reasons', [])
            
            # HTML escape exit reasons to prevent parsing errors (e.g., < characters)
            import html
            
            # Format exit reason (take first reason or default)
            if exit_reasons:
                # Remove "Runner exit: " prefix if present, then escape HTML
                first_reason = str(exit_reasons[0])
                if first_reason.startswith("Runner exit: "):
                    first_reason = first_reason.replace("Runner exit: ", "")
                reason_text = html.escape(first_reason)
            else:
                reason_text = "Runner exit triggered"
            
            # P&L emoji and sign
            if pnl_pct > 0:
                pnl_emoji = "💰"
                pnl_sign = "+"
            else:
                pnl_emoji = "📉"
                pnl_sign = ""
            
            message = f"""====================================================================

🔮 💠 <b>RUNNER EXIT</b> | {mode} Mode
          Time: {pt_time} ({et_time})

1) {pnl_emoji} <b>{pnl_sign}{pnl_pct*100:.2f}%</b> {pnl_sign}${abs(pnl_dollars):.2f}
          {symbol} Options Runner
          <b>Exit Price:</b> ${exit_price:.2f}
          <b>Reason:</b> {reason_text}
          
          <b>Trade ID:</b>
          {position_id}

📊 Automated exit system profit capture
"""
            
            success = await self._send_telegram_message(message, AlertLevel.SUCCESS)
            
            if success:
                log.info(f"Options Runner Exit alert sent for {symbol} - P&L: {pnl_sign}{pnl_pct:.2f}%")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options Runner Exit alert: {e}")
            return False
    
    async def send_options_health_check_alert(self, health_status: str,
                                             red_flags: List[str],
                                             positions_closed: int = 0,
                                             mode: str = "DEMO") -> bool:
        """
        Send Options Portfolio Health Check alert
        
        Args:
            health_status: Health status (EMERGENCY, WARNING, OK)
            red_flags: List of red flag descriptions
            positions_closed: Number of positions closed due to health check
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Status emoji
            status_emojis = {
                'EMERGENCY': '🚨',
                'WARNING': '⚠️',
                'OK': '✅'
            }
            status_emoji = status_emojis.get(health_status, '🛡️')
            
            # Build red flags list
            flags_text = ""
            if red_flags:
                for flag in red_flags:
                    flags_text += f"   ❌ {flag}\n"
            else:
                flags_text = "   ✅ No red flags detected\n"
            
            # Action text
            if health_status == 'EMERGENCY':
                action_text = f"🛡️ <b>Action:</b> Closed {positions_closed} options positions\n💰 Exited early to preserve capital"
            elif health_status == 'WARNING':
                action_text = f"🛡️ <b>Action:</b> Closed {positions_closed} weak positions\n💰 Preserving capital while keeping strong positions"
            else:
                action_text = "✅ <b>Action:</b> Continue trading\n📊 Normal operations"
            
            message = f"""====================================================================

{status_emoji} <b>OPTIONS PORTFOLIO HEALTH</b> - {health_status} | {mode} Mode
          Time: {pt_time} ({et_time})

📊 <b>Red Flags:</b>
{flags_text}
{action_text}

🛡️ Health check system protecting capital
"""
            
            success = await self._send_telegram_message(message, AlertLevel.WARNING if health_status in ['EMERGENCY', 'WARNING'] else AlertLevel.INFO)
            
            if success:
                log.info(f"Options Health Check alert sent - Status: {health_status}, Flags: {len(red_flags)}")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options Health Check alert: {e}")
            return False
    
    async def send_options_end_of_day_report(self, daily_stats: Dict[str, Any],
                                            weekly_stats: Dict[str, Any],
                                            all_time_stats: Optional[Dict[str, Any]] = None,
                                            account_balance: float = 1000.0,
                                            starting_balance: float = 1000.0,
                                            mode: str = "DEMO") -> bool:
        """
        Send End-of-Day report for 0DTE Strategy options trading
        
        Args:
            daily_stats: Today's options trading statistics
            weekly_stats: This week's options trading statistics
            all_time_stats: All-time options trading statistics (optional)
            account_balance: Current account balance
            starting_balance: Starting balance for % calculation
            mode: Trading mode (DEMO or LIVE)
        
        Returns:
            True if alert sent successfully
        """
        try:
            from zoneinfo import ZoneInfo
            
            # Get current time
            pt_tz = ZoneInfo('America/Los_Angeles')
            et_tz = ZoneInfo('America/New_York')
            now_pt = datetime.now(pt_tz)
            now_et = datetime.now(et_tz)
            
            pt_time = now_pt.strftime('%I:%M %p PT')
            et_time = now_et.strftime('%I:%M %p ET')
            
            # Calculate stats
            daily_closed = daily_stats.get('positions_closed', 0)
            daily_wins = daily_stats.get('winning_trades', 0)
            daily_losses = daily_stats.get('losing_trades', 0)
            daily_pnl = daily_stats.get('total_pnl', 0.0)
            daily_best = daily_stats.get('best_trade', 0.0)
            daily_worst = daily_stats.get('worst_trade', 0.0)
            
            weekly_closed = weekly_stats.get('positions_closed', 0)
            weekly_wins = weekly_stats.get('winning_trades', 0)
            weekly_losses = weekly_stats.get('losing_trades', 0)
            weekly_pnl = weekly_stats.get('total_pnl', 0.0)
            
            # Calculate rates
            daily_win_rate = (daily_wins / daily_closed * 100) if daily_closed > 0 else 0.0
            weekly_win_rate = (weekly_wins / weekly_closed * 100) if weekly_closed > 0 else 0.0
            
            # Calculate P&L percentages
            daily_pnl_pct = (daily_pnl / starting_balance * 100) if starting_balance > 0 else 0.0
            weekly_pnl_pct = (weekly_pnl / starting_balance * 100) if starting_balance > 0 else 0.0
            
            # Format P&L
            daily_pnl_sign = "+" if daily_pnl >= 0 else ""
            weekly_pnl_sign = "+" if weekly_pnl >= 0 else ""
            
            # Calculate profit factors
            daily_total_wins = daily_stats.get('total_wins_sum', None)
            daily_total_losses = daily_stats.get('total_losses_sum', None)
            
            if daily_total_wins is None or daily_total_losses is None:
                if daily_wins > 0 and daily_losses > 0:
                    avg_win = (daily_pnl / daily_wins) if daily_wins > 0 else 0.0
                    estimated_wins_sum = avg_win * daily_wins
                    avg_loss = abs((daily_pnl - estimated_wins_sum) / daily_losses) if daily_losses > 0 else 0.0
                    daily_total_wins = avg_win * daily_wins
                    daily_total_losses = avg_loss * daily_losses
                elif daily_wins > 0:
                    daily_total_wins = daily_pnl
                    daily_total_losses = 0.0
                elif daily_losses > 0:
                    daily_total_wins = 0.0
                    daily_total_losses = abs(daily_pnl)
                else:
                    daily_total_wins = 0.0
                    daily_total_losses = 0.0
            
            daily_profit_factor = (daily_total_wins / daily_total_losses) if daily_total_losses > 0 else (daily_total_wins if daily_total_wins > 0 else (float('inf') if daily_total_wins > 0 and daily_total_losses == 0 else 0.0))
            
            weekly_total_wins = weekly_stats.get('total_wins_sum', None)
            weekly_total_losses = weekly_stats.get('total_losses_sum', None)
            
            if weekly_total_wins is None or weekly_total_losses is None:
                if weekly_wins > 0 and weekly_losses > 0:
                    weekly_avg_win = (weekly_pnl / weekly_wins) if weekly_wins > 0 else 0.0
                    estimated_wins_sum = weekly_avg_win * weekly_wins
                    weekly_avg_loss = abs((weekly_pnl - estimated_wins_sum) / weekly_losses) if weekly_losses > 0 else 0.0
                    weekly_total_wins = weekly_avg_win * weekly_wins
                    weekly_total_losses = weekly_avg_loss * weekly_losses
                elif weekly_wins > 0:
                    weekly_total_wins = weekly_pnl
                    weekly_total_losses = 0.0
                elif weekly_losses > 0:
                    weekly_total_wins = 0.0
                    weekly_total_losses = abs(weekly_pnl)
                else:
                    weekly_total_wins = 0.0
                    weekly_total_losses = 0.0
            
            weekly_profit_factor = (weekly_total_wins / weekly_total_losses) if weekly_total_losses > 0 else (weekly_total_wins if weekly_total_wins > 0 else (float('inf') if weekly_total_wins > 0 and weekly_total_losses == 0 else 0.0))
            
            # All-time stats
            all_time_total_trades = 0
            all_time_wins = 0
            all_time_losses = 0
            all_time_pnl = 0.0
            all_time_profit_factor = 0.0
            all_time_pnl_pct = 0.0
            
            if all_time_stats:
                all_time_total_trades = all_time_stats.get('total_trades', 0)
                all_time_wins = all_time_stats.get('winning_trades', 0)
                all_time_losses = all_time_stats.get('losing_trades', 0)
                all_time_pnl = all_time_stats.get('total_pnl', 0.0)
                
                all_time_wins_sum = all_time_stats.get('total_wins_sum', 0.0)
                all_time_losses_sum = all_time_stats.get('total_losses_sum', 0.0)
                
                if all_time_wins_sum > 0 and all_time_losses_sum > 0:
                    all_time_profit_factor = all_time_wins_sum / all_time_losses_sum
                elif all_time_wins_sum > 0 and all_time_losses_sum == 0:
                    all_time_profit_factor = float('inf')
                elif all_time_wins_sum == 0 and all_time_losses_sum > 0:
                    all_time_profit_factor = 0.0
                else:
                    if all_time_wins > 0 and all_time_losses > 0:
                        all_time_avg_win = (all_time_pnl / all_time_wins) if all_time_wins > 0 else 0.0
                        estimated_wins_sum = all_time_avg_win * all_time_wins
                        all_time_avg_loss = abs((all_time_pnl - estimated_wins_sum) / all_time_losses) if all_time_losses > 0 else 0.0
                        all_time_total_wins_sum = all_time_avg_win * all_time_wins
                        all_time_total_losses_sum = all_time_avg_loss * all_time_losses
                        all_time_profit_factor = (all_time_total_wins_sum / all_time_total_losses_sum) if all_time_total_losses_sum > 0 else 0.0
                    elif all_time_wins > 0:
                        all_time_profit_factor = float('inf')
                    else:
                        all_time_profit_factor = 0.0
                
                all_time_pnl_pct = (all_time_pnl / starting_balance * 100) if starting_balance > 0 else 0.0
            
            all_time_win_rate = (all_time_wins / all_time_total_trades * 100) if all_time_total_trades > 0 else 0.0
            all_time_pnl_sign = "+" if all_time_pnl >= 0 else ""
            
            # Calculate averages
            avg_win = (daily_total_wins / daily_wins) if daily_wins > 0 else 0.0
            avg_loss = -(daily_total_losses / daily_losses) if daily_losses > 0 else 0.0
            
            # Format profit factors
            daily_pf_str = f"{daily_profit_factor:.2f}" if daily_profit_factor != float('inf') else "∞"
            weekly_pf_str = f"{weekly_profit_factor:.2f}" if weekly_profit_factor != float('inf') else "∞"
            all_time_pf_str = f"{all_time_profit_factor:.2f}" if all_time_profit_factor != float('inf') else "∞"
            
            # Get current date
            report_date = datetime.utcnow().strftime('%Y-%m-%d')
            
            # Format worst trade sign
            daily_worst_sign = "-" if daily_worst < 0 else "+"
            
            # Mode emoji
            mode_emoji = "🎮 🍒" if mode == "DEMO" else "💰"
            
            # Build message
            message = f"""====================================================================

🏦 <b>END-OF-DAY OPTIONS</b> | {mode_emoji}
          Time: {pt_time} ({et_time})

📈 <b>P&L (TODAY):</b>
          <b>{daily_pnl_sign}{daily_pnl_pct:.2f}%</b> {daily_pnl_sign}${daily_pnl:.2f}
          Win Rate: {daily_win_rate:.1f}% • Total Trades: {daily_closed}
          Wins: {daily_wins} • Losses: {daily_losses}
          Profit Factor: {daily_pf_str}
          Average Win: ${avg_win:.2f}
          Average Loss: ${avg_loss:.2f}
          Best Trade: {daily_pnl_sign}${daily_best:.2f}
          Worst Trade: {daily_worst_sign}${abs(daily_worst):.2f}

🎖️ <b>P&L (WEEK M-F):</b>
          <b>{weekly_pnl_sign}{weekly_pnl_pct:.2f}%</b> {weekly_pnl_sign}${weekly_pnl:.2f}
          Win Rate: {weekly_win_rate:.1f}% • Total Trades: {weekly_closed}
          Profit Factor: {weekly_pf_str}

💎 <b>Account Balances (All Time):</b>
          <b>{all_time_pnl_sign}{all_time_pnl_pct:.2f}%</b> {all_time_pnl_sign}${all_time_pnl:.2f}
          <b>${account_balance:,.2f}</b>
          Win Rate: {all_time_win_rate:.1f}% • Total Trades: {all_time_total_trades}
          Profit Factor: {all_time_pf_str}
          Wins: {all_time_wins} • Losses: {all_time_losses}

📅 Report Date: {report_date}
"""
            
            # Send via Telegram
            success = await self._send_telegram_message(message, AlertLevel.INFO)
            
            if success:
                log.info(f"Options EOD Report sent ({mode} Mode) - Daily: {daily_pnl_sign}${daily_pnl:.2f} ({daily_pnl_sign}{daily_pnl_pct:.2f}%), Weekly: {weekly_pnl_sign}${weekly_pnl:.2f} ({weekly_pnl_sign}{weekly_pnl_pct:.2f}%)")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending Options EOD Report: {e}")
            return False

# Global instance
_prime_alert_manager = None

def get_prime_alert_manager() -> PrimeAlertManager:
    """Get the prime alert manager instance"""
    global _prime_alert_manager
    if _prime_alert_manager is None:
        _prime_alert_manager = PrimeAlertManager()
    return _prime_alert_manager

log.info("Prime Alert Manager loaded successfully")
