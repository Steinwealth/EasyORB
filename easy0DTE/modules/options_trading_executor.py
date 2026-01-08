#!/usr/bin/env python3
"""
Options Trading Executor
========================

Executes options trades (debit spreads and lotto sleeve) for 0DTE Strategy.
Handles order execution, position management, and profit-taking.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field

from .options_chain_manager import DebitSpread, CreditSpread, OptionContract
from .options_exit_manager import OptionsExitManager, ExitReason, ExitSignal
from .options_types import OptionsPosition

# Import ETrade Options API
try:
    from .etrade_options_api import ETradeOptionsAPI
    ETRADE_OPTIONS_AVAILABLE = True
except ImportError:
    ETRADE_OPTIONS_AVAILABLE = False
    logging.warning("ETrade Options API not available")

log = logging.getLogger(__name__)


class OptionsTradingExecutor:
    """
    Options Trading Executor for 0DTE Strategy
    
    Handles:
    - Debit spread execution (Demo/Live)
    - Credit spread execution (Demo/Live)
    - Lotto sleeve execution (Demo/Live)
    - Position management
    - Auto-partial profits
    - Systematic runners
    
    Supports both Demo Mode (mock execution) and Live Mode (broker API).
    """
    
    def __init__(
        self,
        auto_partial_enabled: bool = True,
        partial_profit_pct: float = 0.50,  # Legacy: Take 50% profit at target
        runner_profit_pct: float = 2.0,  # Legacy: Let 50% run to 2x
        max_position_cost: float = 999999.0,  # Disabled - using only percentage-based limit (35%)
        max_position_size_pct: float = 0.35,  # Max position size as % of account equity (35% - matches ORB Strategy)
        demo_mode: Optional[bool] = None,  # None = auto-detect from env, True/False = explicit
        mock_executor=None,  # Mock executor for Demo mode
        alert_manager=None,  # Alert manager for notifications
        priority_collector=None  # Priority Data Collector for trade history
    ):
        """
        Initialize Options Trading Executor
        
        Args:
            auto_partial_enabled: Enable auto-partial profits
            partial_profit_pct: Percentage to take profit at (e.g., 0.50 = 50%)
            runner_profit_pct: Profit percentage for runners (e.g., 2.0 = 2x)
            max_position_cost: Maximum cost per position
        """
        self.auto_partial_enabled = auto_partial_enabled
        self.partial_profit_pct = partial_profit_pct  # Legacy, kept for compatibility
        self.runner_profit_pct = runner_profit_pct  # Legacy, kept for compatibility
        self.max_position_cost = max_position_cost
        self.max_position_size_pct = max_position_size_pct  # 35% max of account equity (matches ORB Strategy)
        
        # Detect mode from environment if not explicitly set
        if demo_mode is None:
            demo_mode = (
                os.getenv('ETRADE_MODE', 'demo').lower() == 'demo' or
                os.getenv('DEPLOYMENT_MODE', 'demo').lower() == 'demo' or
                os.getenv('DEMO_MODE_ENABLED', 'true').lower() == 'true'
            )
        
        self.demo_mode = demo_mode
        self.mock_executor = mock_executor
        self.alert_manager = alert_manager
        self.priority_collector = priority_collector  # Priority Data Collector
        
        # ETrade Options API for Live Mode
        self.etrade_options_api = None
        if not demo_mode and ETRADE_OPTIONS_AVAILABLE:
            try:
                environment = os.getenv('ETRADE_ENVIRONMENT', 'prod')
                self.etrade_options_api = ETradeOptionsAPI(environment=environment)
                if not self.etrade_options_api.is_available():
                    log.warning("ETrade Options API not available - Live mode disabled")
                    self.etrade_options_api = None
            except Exception as e:
                log.warning(f"Failed to initialize ETrade Options API: {e}")
                self.etrade_options_api = None
        
        # Position tracking
        self.positions: Dict[str, OptionsPosition] = {}
        
        # Initialize Exit Manager with automated exit targets
        self.exit_manager = OptionsExitManager(
            debit_spread_hard_stop_pct=float(os.getenv('0DTE_DEBIT_HARD_STOP_PCT', '-0.45')),
            debit_spread_time_stop_minutes=int(os.getenv('0DTE_DEBIT_TIME_STOP_MINUTES', '25')),
            debit_spread_fail_safe_pct=float(os.getenv('0DTE_DEBIT_FAIL_SAFE_PCT', '-0.60')),
            lotto_hard_stop_pct=float(os.getenv('0DTE_LOTTO_HARD_STOP_PCT', '-0.55')),
            lotto_time_stop_minutes=int(os.getenv('0DTE_LOTTO_TIME_STOP_MINUTES', '12')),
            lotto_fail_safe_pct=float(os.getenv('0DTE_LOTTO_FAIL_SAFE_PCT', '-0.60')),
            first_profit_target_pct=float(os.getenv('0DTE_FIRST_PROFIT_TARGET_PCT', '0.60')),  # +60%
            first_profit_sell_pct=float(os.getenv('0DTE_FIRST_PROFIT_SELL_PCT', '0.50')),  # Sell 50%
            second_profit_target_pct=float(os.getenv('0DTE_SECOND_PROFIT_TARGET_PCT', '1.20')),  # +120%
            second_profit_sell_pct=float(os.getenv('0DTE_SECOND_PROFIT_SELL_PCT', '0.25')),  # Sell 25%
            partial_profit_pct=partial_profit_pct,  # Legacy
            runner_profit_pct=runner_profit_pct  # Legacy
        )
        
        mode_label = "🎮 DEMO MODE" if demo_mode else "💰 LIVE MODE"
        log.info(f"Options Trading Executor initialized ({mode_label}):")
        log.info(f"  - Auto-partial enabled: {auto_partial_enabled}")
        log.info(f"  - First profit target: +{self.exit_manager.first_profit_target_pct*100:.0f}% → sell {self.exit_manager.first_profit_sell_pct*100:.0f}%")
        log.info(f"  - Second profit target: +{self.exit_manager.second_profit_target_pct*100:.0f}% → sell {self.exit_manager.second_profit_sell_pct*100:.0f}%")
        log.info(f"  - Max position cost: ${max_position_cost:.2f}")
        log.info(f"  - Max position size: {max_position_size_pct*100:.0f}% of account equity")
        log.info(f"  - Exit Manager: ✅ Initialized with optimized exit framework")
        if not demo_mode:
            log.info(f"  - ETrade API available: {self.etrade_options_api is not None}")
    
    async def execute_debit_spread(
        self,
        spread: DebitSpread,
        quantity: int = 1
    ) -> Optional[OptionsPosition]:
        """
        Execute debit spread order (Demo or Live)
        
        Args:
            spread: DebitSpread object
            quantity: Number of spreads
            
        Returns:
            OptionsPosition or None if execution failed
        """
        # Validate position cost
        total_cost = spread.debit_cost * quantity * 100  # Options are per 100 shares
        
        # Check max position size as % of account equity (35% max - matches ORB Strategy)
        # Note: max_position_cost check disabled - using only percentage-based limit
        if self.mock_executor:
            account_balance = self.mock_executor.account_balance
            max_allowed = account_balance * self.max_position_size_pct
            if total_cost > max_allowed:
                log.warning(f"Position cost ${total_cost:.2f} exceeds {self.max_position_size_pct*100:.0f}% of account equity (${max_allowed:.2f})")
                return None
        
        # Demo Mode: Use mock executor
        if self.demo_mode and self.mock_executor:
            return await self.mock_executor.execute_debit_spread(spread, quantity)
        
        # Live Mode: Use ETrade API
        if not self.demo_mode and self.etrade_options_api:
            # Check max position size as % of account equity (33% max) for Live Mode
            try:
                # Get account balance from ETrade API
                if hasattr(self.etrade_options_api, 'etrade') and self.etrade_options_api.etrade:
                    account_balance_obj = self.etrade_options_api.etrade.get_account_balance()
                    if account_balance_obj:
                        # Use cash available for investment or account value
                        account_balance = (
                            account_balance_obj.cash_available_for_investment or
                            account_balance_obj.account_value or
                            0.0
                        )
                        
                        if account_balance > 0:
                            max_allowed = account_balance * self.max_position_size_pct
                            if total_cost > max_allowed:
                                log.warning(f"Position cost ${total_cost:.2f} exceeds {self.max_position_size_pct*100:.0f}% of account equity (${max_allowed:.2f} of ${account_balance:.2f})")
                                return None
                            log.debug(f"✅ Live Mode: Position cost ${total_cost:.2f} within {self.max_position_size_pct*100:.0f}% limit (${max_allowed:.2f} of ${account_balance:.2f})")
                        else:
                            log.warning(f"⚠️ Live Mode: Could not determine account balance, skipping 33% check")
            except Exception as e:
                log.warning(f"⚠️ Live Mode: Error checking account balance for 33% limit: {e}")
                # Continue execution but log warning
            
            try:
                # Convert expiry format: YYYY-MM-DD -> YYYYMMDD
                expiry_etrade = spread.expiry.replace('-', '')
                
                # Place order via ETrade API
                order_response = await self.etrade_options_api.place_debit_spread_order(
                    symbol=spread.symbol,
                    expiry=expiry_etrade,
                    option_type=spread.option_type,
                    long_strike=spread.long_strike,
                    short_strike=spread.short_strike,
                    quantity=quantity
                )
                
                if order_response:
                    # Create position from order response (shortened ID format)
                    timestamp = int(datetime.now().timestamp())
                    expiry_short = spread.expiry.replace('-', '')[-6:] if spread.expiry else datetime.now().strftime('%y%m%d')
                    position_id = f"LIVE_{spread.symbol}_{expiry_short}_{int(spread.long_strike)}_{int(spread.short_strike)}_{spread.option_type[0]}_{str(timestamp)[-6:]}"
                    
                    position = OptionsPosition(
                        position_id=position_id,
                        symbol=spread.symbol,
                        position_type='debit_spread',
                        debit_spread=spread,
                        entry_price=spread.debit_cost,
                        quantity=quantity,
                        current_value=spread.debit_cost,
                        unrealized_pnl=0.0
                    )
                    
                    self.positions[position_id] = position
                    
                    log.info(f"✅ Live debit spread executed: Position ID {position_id}")
                    return position
                else:
                    log.error("Failed to place debit spread order via ETrade API")
                    return None
                    
            except Exception as e:
                log.error(f"Error placing debit spread order via ETrade API: {e}")
                return None
        
        # Fallback: Log warning
        log.warning(f"💰 LIVE: ETrade Options API not available")
        log.info(f"Would execute debit spread: {spread.symbol} {spread.option_type} {spread.long_strike}/{spread.short_strike}")
        log.info(f"  Quantity: {quantity}, Debit: ${spread.debit_cost:.2f}, Total Cost: ${total_cost:.2f}")
        
        # Create position (Rev 00232: Shortened format for alerts - symbol_date_strikes_type_microseconds)
        now = datetime.now()
        expiry_short = spread.expiry.replace('-', '')[-6:] if spread.expiry else now.strftime('%y%m%d')
        microseconds_short = now.microsecond % 1000  # Last 3 digits for uniqueness
        # Format: LIVE_SYMBOL_YYMMDD_LONG_SHORT_TYPE_microseconds (e.g., LIVE_SPY_260107_585_590_c_546)
        position_id = f"LIVE_{spread.symbol}_{expiry_short}_{int(spread.long_strike)}_{int(spread.short_strike)}_{spread.option_type[0]}_{microseconds_short:03d}"
        
        position = OptionsPosition(
            position_id=position_id,
            symbol=spread.symbol,
            position_type='debit_spread',
            debit_spread=spread,
            entry_price=spread.debit_cost,
            quantity=quantity,
            current_value=spread.debit_cost,
            unrealized_pnl=0.0
        )
        
        self.positions[position_id] = position
        
        log.info(f"Debit spread executed: Position ID {position_id}")
        
        return position
    
    async def execute_lotto_sleeve(
        self,
        contract: OptionContract,
        quantity: int = 1
    ) -> Optional[OptionsPosition]:
        """
        Execute lotto sleeve (single-leg option) (Demo or Live)
        
        Args:
            contract: OptionContract object
            quantity: Number of contracts
            
        Returns:
            OptionsPosition or None if execution failed
        """
        # Calculate position cost for percentage check
        total_cost = contract.mid_price * quantity * 100  # Options are per 100 shares
        
        # Check max position size as % of account equity (35% max - matches ORB Strategy)
        # Note: max_position_cost check disabled - using only percentage-based limit
        
        # Demo Mode: Use mock executor
        if self.demo_mode and self.mock_executor:
            return await self.mock_executor.execute_lotto_sleeve(contract, quantity)
        
        # Live Mode: Use ETrade API
        if not self.demo_mode and self.etrade_options_api:
            # Check max position size as % of account equity (33% max) for Live Mode
            try:
                # Get account balance from ETrade API
                if hasattr(self.etrade_options_api, 'etrade') and self.etrade_options_api.etrade:
                    account_balance_obj = self.etrade_options_api.etrade.get_account_balance()
                    if account_balance_obj:
                        # Use cash available for investment or account value
                        account_balance = (
                            account_balance_obj.cash_available_for_investment or
                            account_balance_obj.account_value or
                            0.0
                        )
                        
                        if account_balance > 0:
                            max_allowed = account_balance * self.max_position_size_pct
                            if total_cost > max_allowed:
                                log.warning(f"Position cost ${total_cost:.2f} exceeds {self.max_position_size_pct*100:.0f}% of account equity (${max_allowed:.2f} of ${account_balance:.2f})")
                                return None
                            log.debug(f"✅ Live Mode: Position cost ${total_cost:.2f} within {self.max_position_size_pct*100:.0f}% limit (${max_allowed:.2f} of ${account_balance:.2f})")
                        else:
                            log.warning(f"⚠️ Live Mode: Could not determine account balance, skipping 33% check")
            except Exception as e:
                log.warning(f"⚠️ Live Mode: Error checking account balance for 33% limit: {e}")
                # Continue execution but log warning
            
            try:
                # Convert expiry format: YYYY-MM-DD -> YYYYMMDD
                expiry_etrade = contract.expiry.replace('-', '')
                
                # Place order via ETrade API
                order_response = await self.etrade_options_api.place_single_option_order(
                    symbol=contract.symbol,
                    expiry=expiry_etrade,
                    option_type=contract.option_type,
                    strike=contract.strike,
                    side='BUY',  # Lotto sleeve is always buying
                    quantity=quantity
                )
                
                if order_response:
                    # Create position from order response
                    # Create position (shortened ID format)
                    timestamp = int(datetime.now().timestamp())
                    expiry_short = contract.expiry.replace('-', '')[-6:] if contract.expiry else datetime.now().strftime('%y%m%d')
                    position_id = f"LIVE_{contract.symbol}_{expiry_short}_{int(contract.strike)}_{contract.option_type[0]}_{str(timestamp)[-6:]}"
                    
                    position = OptionsPosition(
                        position_id=position_id,
                        symbol=contract.symbol,
                        position_type='lotto',
                        lotto_contract=contract,
                        entry_price=contract.mid_price,
                        quantity=quantity,
                        current_value=contract.mid_price,
                        unrealized_pnl=0.0
                    )
                    
                    self.positions[position_id] = position
                    
                    log.info(f"✅ Live lotto sleeve executed: Position ID {position_id}")
                    return position
                else:
                    log.error("Failed to place lotto sleeve order via ETrade API")
                    return None
                    
            except Exception as e:
                log.error(f"Error placing lotto sleeve order via ETrade API: {e}")
                return None
        
        # Fallback: Log warning
        log.warning(f"💰 LIVE: ETrade Options API not available")
        log.info(f"Would execute lotto sleeve: {contract.symbol} {contract.option_type} {contract.strike}")
        log.info(f"  Quantity: {quantity}, Cost: ${contract.mid_price:.2f}, Total Cost: ${total_cost:.2f}")
        
        # Create position
        # Create position (shortened ID format)
        timestamp = int(datetime.now().timestamp())
        expiry_short = contract.expiry.replace('-', '')[-6:] if contract.expiry else datetime.now().strftime('%y%m%d')
        position_id = f"LIVE_{contract.symbol}_{expiry_short}_{int(contract.strike)}_{contract.option_type[0]}_{str(timestamp)[-6:]}"
        
        position = OptionsPosition(
            position_id=position_id,
            symbol=contract.symbol,
            position_type='lotto',
            lotto_contract=contract,
            entry_price=contract.mid_price,
            quantity=quantity,
            current_value=contract.mid_price,
            unrealized_pnl=0.0
        )
        
        self.positions[position_id] = position
        
        log.info(f"Lotto sleeve executed: Position ID {position_id}")
        
        return position
    
    async def execute_credit_spread(
        self,
        spread: CreditSpread,
        quantity: int = 1
    ) -> Optional[OptionsPosition]:
        """
        Execute credit spread order (Demo or Live)
        
        Args:
            spread: CreditSpread object
            quantity: Number of spreads
            
        Returns:
            OptionsPosition or None if execution failed
        """
        # Validate position cost (for credit spreads, we receive credit, so check margin requirement)
        # Margin requirement = max_loss (spread_width - credit_received) * quantity * 100
        margin_requirement = spread.max_loss * quantity * 100  # Options are per 100 shares
        
        # Check max position size as % of account equity (35% max - matches ORB Strategy)
        # Note: max_position_cost check disabled - using only percentage-based limit
        if self.mock_executor:
            account_balance = self.mock_executor.account_balance
            max_allowed = account_balance * self.max_position_size_pct
            if margin_requirement > max_allowed:
                log.warning(f"Margin requirement ${margin_requirement:.2f} exceeds {self.max_position_size_pct*100:.0f}% of account equity (${max_allowed:.2f})")
                return None
        
        # Demo Mode: Use mock executor
        if self.demo_mode and self.mock_executor:
            return await self.mock_executor.execute_credit_spread(spread, quantity)
        
        # Live Mode: Use ETrade API
        if not self.demo_mode and self.etrade_options_api:
            # Check max position size as % of account equity (33% max) for Live Mode
            try:
                # Get account balance from ETrade API
                if hasattr(self.etrade_options_api, 'etrade') and self.etrade_options_api.etrade:
                    account_balance_obj = self.etrade_options_api.etrade.get_account_balance()
                    if account_balance_obj:
                        # Use cash available for investment or account value
                        account_balance = (
                            account_balance_obj.cash_available_for_investment or
                            account_balance_obj.account_value or
                            0.0
                        )
                        
                        if account_balance > 0:
                            max_allowed = account_balance * self.max_position_size_pct
                            if margin_requirement > max_allowed:
                                log.warning(f"Margin requirement ${margin_requirement:.2f} exceeds {self.max_position_size_pct*100:.0f}% of account equity (${max_allowed:.2f} of ${account_balance:.2f})")
                                return None
                            log.debug(f"✅ Live Mode: Margin requirement ${margin_requirement:.2f} within {self.max_position_size_pct*100:.0f}% limit (${max_allowed:.2f} of ${account_balance:.2f})")
                        else:
                            log.warning(f"⚠️ Live Mode: Could not determine account balance, skipping 33% check")
            except Exception as e:
                log.warning(f"⚠️ Live Mode: Error checking account balance for 33% limit: {e}")
                # Continue execution but log warning
            
            try:
                # Convert expiry format: YYYY-MM-DD -> YYYYMMDD
                expiry_etrade = spread.expiry.replace('-', '')
                
                # Place order via ETrade API
                order_response = await self.etrade_options_api.place_credit_spread_order(
                    symbol=spread.symbol,
                    expiry=expiry_etrade,
                    option_type=spread.option_type,
                    short_strike=spread.short_strike,
                    long_strike=spread.long_strike,
                    quantity=quantity
                )
                
                if order_response:
                    # Create position from order response (shortened ID format)
                    timestamp = int(datetime.now().timestamp())
                    expiry_short = spread.expiry.replace('-', '')[-6:] if spread.expiry else datetime.now().strftime('%y%m%d')
                    position_id = f"LIVE_{spread.symbol}_{expiry_short}_{int(spread.short_strike)}_{int(spread.long_strike)}_{spread.option_type[0]}_{str(timestamp)[-6:]}"
                    
                    position = OptionsPosition(
                        position_id=position_id,
                        symbol=spread.symbol,
                        position_type='credit_spread',
                        credit_spread=spread,
                        entry_price=spread.credit_received,  # Entry price = credit received
                        quantity=quantity,
                        current_value=spread.credit_received,
                        unrealized_pnl=0.0
                    )
                    
                    self.positions[position_id] = position
                    
                    log.info(f"✅ Live credit spread executed: Position ID {position_id}")
                    return position
                else:
                    log.error("Failed to place credit spread order via ETrade API")
                    return None
                    
            except Exception as e:
                log.error(f"Error placing credit spread order via ETrade API: {e}")
                return None
        
        # Fallback: Log warning
        log.warning(f"💰 LIVE: ETrade Options API not available")
        log.info(f"Would execute credit spread: {spread.symbol} {spread.option_type} {spread.short_strike}/{spread.long_strike}")
        log.info(f"  Quantity: {quantity}, Credit: ${spread.credit_received:.2f}, Margin: ${margin_requirement:.2f}")
        
        # Create position (shortened ID format)
        timestamp = int(datetime.now().timestamp())
        expiry_short = spread.expiry.replace('-', '')[-6:] if spread.expiry else datetime.now().strftime('%y%m%d')
        position_id = f"LIVE_{spread.symbol}_{expiry_short}_{int(spread.short_strike)}_{int(spread.long_strike)}_{spread.option_type[0]}_{str(timestamp)[-6:]}"
        
        position = OptionsPosition(
            position_id=position_id,
            symbol=spread.symbol,
            position_type='credit_spread',
            credit_spread=spread,
            entry_price=spread.credit_received,  # Entry price = credit received
            quantity=quantity,
            current_value=spread.credit_received,
            unrealized_pnl=0.0
        )
        
        self.positions[position_id] = position
        
        log.info(f"Credit spread executed: Position ID {position_id}")
        
        return position
    
    async def update_position_value(
        self,
        position_id: str,
        current_value: float
    ) -> Optional[OptionsPosition]:
        """
        Update position current value and P&L
        
        Args:
            position_id: Position ID
            current_value: Current position value
            
        Returns:
            Updated OptionsPosition or None if not found
        """
        if position_id not in self.positions:
            log.warning(f"Position {position_id} not found")
            return None
        
        position = self.positions[position_id]
        position.current_value = current_value
        
        # Calculate unrealized P&L
        if position.position_type == 'debit_spread':
            # For debit spread: profit = (current_value - entry_price) * quantity * 100
            position.unrealized_pnl = (current_value - position.entry_price) * position.quantity * 100
        elif position.position_type == 'credit_spread':
            # For credit spread: profit = (entry_price - current_value) * quantity * 100
            # Entry price = credit received, current_value = current cost to close
            # Profit when current_value decreases (spread expires worthless or decreases)
            position.unrealized_pnl = (position.entry_price - current_value) * position.quantity * 100
        else:  # lotto
            # For lotto: profit = (current_value - entry_price) * quantity * 100
            position.unrealized_pnl = (current_value - position.entry_price) * position.quantity * 100
        
        return position
    
    async def auto_partial_profit(
        self,
        position_id: str,
        target_name: str = 'first_target_60pct'
    ) -> Optional[Dict[str, Any]]:
        """
        Auto-partial profit: Automated exit strategy
        
        Automated Exit Strategy:
        - +60% → sell 50% (first target)
        - +120% → sell 25% (second target)
        - Runner trails until VWAP/ORB reclaim or time cutoff
        
        Args:
            position_id: Position ID
            target_name: Target name ('first_target_60pct' or 'second_target_120pct')
            
        Returns:
            Dictionary with partial execution details or None
        """
        if not self.auto_partial_enabled:
            return None
        
        if position_id not in self.positions:
            return None
        
        position = self.positions[position_id]
        
        # Determine sell percentage based on target
        if target_name == 'first_target_60pct':
            sell_pct = self.exit_manager.first_profit_sell_pct  # 50%
            target_pct = self.exit_manager.first_profit_target_pct  # +60%
        elif target_name == 'second_target_120pct':
            sell_pct = self.exit_manager.second_profit_sell_pct  # 25%
            target_pct = self.exit_manager.second_profit_target_pct  # +120%
        else:
            # Legacy fallback
            sell_pct = self.partial_profit_pct
            target_pct = 0.50
        
        # Check if profit target reached
        entry_price = position.entry_price
        current_value = position.current_value
        
        # Calculate P&L based on position type
        if position.position_type == 'credit_spread':
            # For credit spreads: profit = (entry_price - current_value) / entry_price
            # Entry price = credit received, current_value = cost to close
            # Profit when current_value decreases (spread expires worthless)
            pnl_pct = (entry_price - current_value) / entry_price if entry_price > 0 else 0.0
        else:
            # For debit spreads and lottos: profit = (current_value - entry_price) / entry_price
            pnl_pct = (current_value - entry_price) / entry_price if entry_price > 0 else 0.0
        
        if pnl_pct < target_pct:
            return None  # Profit target not reached
        
        # Calculate partial quantity
        partial_quantity = int(position.quantity * sell_pct)
        
        # Validate partial quantity
        if partial_quantity <= 0:
            log.warning(f"⚠️ Partial quantity calculation resulted in 0 or negative: {partial_quantity} (quantity: {position.quantity}, sell_pct: {sell_pct})")
            return None
        
        # Ensure we don't try to close more than available
        if partial_quantity >= position.quantity:
            log.warning(f"⚠️ Partial quantity ({partial_quantity}) >= position quantity ({position.quantity}), adjusting to close all")
            partial_quantity = position.quantity
        
        # Calculate profit for partial close
        current_profit = position.unrealized_pnl
        partial_profit = current_profit * sell_pct
        
        log.info(f"💰 AUTOMATED EXIT: Position {position_id}")
        log.info(f"   Target: {target_name} (+{target_pct*100:.0f}%)")
        log.info(f"   Selling: {partial_quantity}/{position.quantity} contracts ({sell_pct*100:.0f}%)")
        log.info(f"   Profit: ${partial_profit:.2f} (${current_profit:.2f} total)")
        
        # Demo Mode: Update position directly
        if self.demo_mode and self.mock_executor:
            # Demo mode: Just update position tracking
            position.quantity -= partial_quantity
            position.realized_pnl += partial_profit
            position.status = 'partial'
            log.info(f"🎮 DEMO: Partial close executed (simulated)")
        
        # Live Mode: Execute partial close via ETrade API
        elif not self.demo_mode and self.etrade_options_api:
            try:
                # Execute partial close via ETrade API
                close_response = await self.etrade_options_api.partial_close_position(
                    position=position,
                    partial_quantity=partial_quantity,
                    exit_price=current_value,  # Use current value as exit price
                    order_type='MARKET'  # Use MARKET for immediate execution
                )
                
                if close_response:
                    # Update position after successful partial close
                    position.quantity -= partial_quantity
                    position.realized_pnl += partial_profit
                    position.status = 'partial'
                    log.info(f"✅ LIVE: Partial close executed via ETrade API")
                    log.info(f"   Closed: {partial_quantity} contracts, Remaining: {position.quantity}")
                else:
                    log.error(f"❌ LIVE: Failed to execute partial close via ETrade API")
                    # Don't update position if API call failed
                    return None
                    
            except Exception as e:
                log.error(f"❌ LIVE: Error executing partial close via ETrade API: {e}", exc_info=True)
                # Don't update position if API call failed
                return None
        
        # Fallback: Update position tracking (for cases where API is not available)
        else:
            position.quantity -= partial_quantity
            position.realized_pnl += partial_profit
            position.status = 'partial'
            log.warning(f"⚠️ Partial close executed (fallback mode - no broker API call)")
        
        partial_result = {
            'position_id': position_id,
            'target_name': target_name,
            'target_pct': target_pct,
            'partial_quantity': partial_quantity,
            'remaining_quantity': position.quantity,
            'realized_pnl': position.realized_pnl,
            'partial_profit': partial_profit,
            'status': position.status
        }
        
        # Send Partial Profit alert (Rev 00206)
        if self.alert_manager:
            try:
                position_dict = position.to_dict()
                import os
                mode = "DEMO" if self.demo_mode else "LIVE"
                await self.alert_manager.send_options_partial_profit_alert(
                    position=position_dict,
                    partial_details=partial_result,
                    mode=mode
                )
                log.info(f"✅ Partial Profit alert sent for position {position_id}")
            except Exception as alert_error:
                log.error(f"Failed to send Partial Profit alert: {alert_error}")
        
        return partial_result
    
    def get_open_positions(self) -> List[OptionsPosition]:
        """Get all open positions"""
        return [p for p in self.positions.values() if p.status == 'open' or p.status == 'partial']
    
    def get_position(self, position_id: str) -> Optional[OptionsPosition]:
        """Get position by ID"""
        return self.positions.get(position_id)
    
    async def monitor_positions(
        self,
        market_data_provider: Optional[Any] = None,
        orb_data_provider: Optional[Any] = None
    ) -> List[ExitSignal]:
        """
        Monitor all open positions and check exit conditions
        
        Args:
            market_data_provider: Function/provider to get current market data
            orb_data_provider: Function/provider to get ORB data
            
        Returns:
            List of ExitSignal objects for positions that should be closed
        """
        exit_signals = []
        open_positions = self.get_open_positions()
        
        if not open_positions:
            return exit_signals
        
        log.debug(f"Monitoring {len(open_positions)} open positions for exit conditions...")
        
        for position in open_positions:
            try:
                # Get current market data
                if market_data_provider:
                    market_data = await market_data_provider(position.symbol)
                else:
                    # Fallback: Use position current_value
                    market_data = {
                        'current_price': position.current_value,
                        'current_value': position.current_value,
                        'vwap': None,
                        'bid_ask_spread_pct': 0.0,
                        'momentum': 0.0
                    }
                
                # Get ORB data
                orb_data = None
                if orb_data_provider:
                    orb_data = await orb_data_provider(position.symbol)
                
                # Check profit targets first (automated exits: +60% sell 50%, +120% sell 25%)
                profit_target_result = self.exit_manager.check_profit_targets(position, position.current_value)
                if profit_target_result:
                    exit_reason, target_details = profit_target_result
                    target_name = target_details.get('target_name', 'unknown')
                    
                    # Execute automated partial profit
                    partial_result = await self.auto_partial_profit(position.position_id, target_name)
                    if partial_result:
                        log.info(f"✅ AUTOMATED EXIT EXECUTED: Position {position.position_id}")
                        log.info(f"   Target: {target_name} (+{target_details['target_pct']*100:.0f}%)")
                        log.info(f"   Sold: {partial_result['partial_quantity']} contracts ({partial_result.get('partial_profit', 0):.2f} profit)")
                        # Don't add to exit_signals - this is a partial exit, not full close
                        continue
                
                # Evaluate other exit conditions (hard stops, invalidation, time stops, fail-safe, runner exits)
                exit_signal = self.exit_manager.evaluate_exit(
                    position=position,
                    current_value=position.current_value,
                    market_data=market_data,
                    orb_data=orb_data
                )
                
                if exit_signal:
                    exit_signals.append(exit_signal)
                    log.info(f"✅ Exit signal generated for position {position.position_id}: {exit_signal.reason.value}")
                    
                    # Record trade performance for Priority Optimizer
                    if self.priority_collector:
                        try:
                            # Calculate peak values (use current value as peak if higher)
                            peak_value = max(position.current_value, position.entry_price)
                            if position.position_type == 'credit_spread':
                                peak_pnl_pct = (position.entry_price - peak_value) / position.entry_price if position.entry_price > 0 else 0.0
                            else:
                                peak_pnl_pct = (peak_value - position.entry_price) / position.entry_price if position.entry_price > 0 else 0.0
                            
                            self.priority_collector.record_trade_performance(
                                position=position,
                                exit_signal=exit_signal,
                                peak_value=peak_value,
                                peak_pnl_pct=peak_pnl_pct
                            )
                        except Exception as e:
                            log.error(f"Failed to record trade performance: {e}")
                    
            except Exception as e:
                log.error(f"Error monitoring position {position.position_id}: {e}", exc_info=True)
        
        return exit_signals
    
    async def execute_exit(
        self,
        exit_signal: ExitSignal,
        exit_reason_override: Optional[str] = None
    ) -> Optional[OptionsPosition]:
        """
        Execute exit for a position based on exit signal
        
        Args:
            exit_signal: ExitSignal object
            exit_reason_override: Override exit reason string
            
        Returns:
            Closed OptionsPosition or None if execution failed
        """
        position_id = exit_signal.position_id
        
        if position_id not in self.positions:
            log.warning(f"Position {position_id} not found for exit")
            return None
        
        position = self.positions[position_id]
        
        # Close position
        if self.demo_mode and self.mock_executor:
            # Demo Mode: Use mock executor
            closed_position = await self.mock_executor.close_position(
                position_id=position_id,
                exit_price=exit_signal.exit_price,
                reason=exit_reason_override or exit_signal.reason.value
            )
            
            if closed_position:
                # Remove from positions dict
                if position_id in self.positions:
                    del self.positions[position_id]
                
                log.info(f"✅ Position {position_id} closed via exit signal: {exit_signal.reason.value}")
                log.info(f"   P&L: {exit_signal.pnl_pct*100:.1f}% (${exit_signal.pnl_dollar:.2f})")
                
                # Send Position Exit alert (Rev 00206)
                if self.alert_manager:
                    try:
                        # Calculate holding time
                        holding_time_minutes = int((exit_signal.exit_time - position.entry_time).total_seconds() / 60)
                        
                        position_dict = position.to_dict()
                        import os
                        mode = "DEMO" if self.demo_mode else "LIVE"
                        
                        # Check if this is a runner exit
                        if exit_signal.reason.value == 'runner_target':
                            await self.alert_manager.send_options_runner_exit_alert(
                                position=position_dict,
                                exit_signal=exit_signal.to_dict() if hasattr(exit_signal, 'to_dict') else {
                                    'exit_price': exit_signal.exit_price,
                                    'pnl_pct': exit_signal.pnl_pct,
                                    'pnl_dollar': exit_signal.pnl_dollar,
                                    'details': exit_signal.details
                                },
                                mode=mode
                            )
                        else:
                            await self.alert_manager.send_options_position_exit_alert(
                                position=position_dict,
                                exit_price=exit_signal.exit_price,
                                exit_reason=exit_reason_override or exit_signal.reason.value,
                                holding_time_minutes=holding_time_minutes,
                                mode=mode
                            )
                        log.info(f"✅ Options Position Exit alert sent for {position_id}")
                    except Exception as alert_error:
                        log.error(f"Failed to send Options Position Exit alert: {alert_error}")
                
                return position
        
        elif not self.demo_mode and self.etrade_options_api:
            # Live Mode: Use ETrade API
            try:
                log.info(f"💰 LIVE: Closing position {position_id} via ETrade API")
                log.info(f"   Exit reason: {exit_signal.reason.value}")
                log.info(f"   Exit price: ${exit_signal.exit_price:.2f}")
                
                # Close position via ETrade API
                close_response = await self.etrade_options_api.close_position(
                    position=position,
                    exit_price=exit_signal.exit_price,
                    order_type='MARKET'  # Use MARKET for immediate execution
                )
                
                if close_response:
                    # Update position status
                    position.status = 'closed'
                    position.realized_pnl = exit_signal.pnl_dollar
                    position.unrealized_pnl = 0.0
                    
                    # Remove from positions dict
                    if position_id in self.positions:
                        del self.positions[position_id]
                    
                    log.info(f"✅ Live position {position_id} closed via ETrade API")
                    log.info(f"   P&L: {exit_signal.pnl_pct*100:.1f}% (${exit_signal.pnl_dollar:.2f})")
                    
                    # Send Position Exit alert (Rev 00206)
                    if self.alert_manager:
                        try:
                            # Calculate holding time
                            holding_time_minutes = int((exit_signal.exit_time - position.entry_time).total_seconds() / 60)
                            
                            position_dict = position.to_dict()
                            mode = "LIVE"
                            
                            # Check if this is a runner exit
                            if exit_signal.reason.value == 'runner_target':
                                await self.alert_manager.send_options_runner_exit_alert(
                                    position=position_dict,
                                    exit_signal=exit_signal.to_dict() if hasattr(exit_signal, 'to_dict') else {
                                        'exit_price': exit_signal.exit_price,
                                        'pnl_pct': exit_signal.pnl_pct,
                                        'pnl_dollar': exit_signal.pnl_dollar,
                                        'details': exit_signal.details
                                    },
                                    mode=mode
                                )
                            else:
                                await self.alert_manager.send_options_position_exit_alert(
                                    position=position_dict,
                                    exit_price=exit_signal.exit_price,
                                    exit_reason=exit_reason_override or exit_signal.reason.value,
                                    holding_time_minutes=holding_time_minutes,
                                    mode=mode
                                )
                            log.info(f"✅ Options Position Exit alert sent for {position_id}")
                        except Exception as alert_error:
                            log.error(f"Failed to send Options Position Exit alert: {alert_error}")
                    
                    return position
                else:
                    log.error(f"Failed to close position {position_id} via ETrade API")
                    return None
                
            except Exception as e:
                log.error(f"Error closing position via ETrade API: {e}", exc_info=True)
                return None
        
        # Fallback: Update position status
        position.status = 'closed'
        position.realized_pnl = exit_signal.pnl_dollar
        position.unrealized_pnl = 0.0
        
        log.info(f"Position {position_id} marked as closed: {exit_signal.reason.value}")
        
        return position
    
    async def close_all_positions(self, reason: str = "EOD_CLOSE") -> List[OptionsPosition]:
        """
        Close all open options positions (typically at EOD)
        
        Args:
            reason: Reason for closing all positions (e.g., "EOD_CLOSE")
            
        Returns:
            List of closed OptionsPosition objects
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            log.info("No open options positions to close")
            return []
        
        log.info(f"Closing {len(open_positions)} open options positions: {reason}")
        closed_positions = []
        
        for position in open_positions:
            try:
                # Get current value for exit price
                current_value = position.current_value if hasattr(position, 'current_value') else position.entry_price
                
                # Create exit signal
                from .options_exit_manager import ExitSignal, ExitReason
                # Use module-level datetime import (line 17)
                
                exit_reason_enum = ExitReason.EOD_CLOSE if reason == "EOD_CLOSE" else ExitReason.HEALTH_EMERGENCY
                
                # Calculate P&L based on position type
                if position.position_type == 'credit_spread':
                    # For credit spreads: profit = (entry_price - current_value) / entry_price
                    # Entry price = credit received, current_value = cost to close
                    pnl_pct = (position.entry_price - current_value) / position.entry_price if position.entry_price > 0 else 0.0
                    pnl_dollar = (position.entry_price - current_value) * position.quantity * 100
                else:
                    # For debit spreads and lottos: profit = (current_value - entry_price) / entry_price
                    pnl_pct = (current_value - position.entry_price) / position.entry_price if position.entry_price > 0 else 0.0
                    pnl_dollar = (current_value - position.entry_price) * position.quantity * 100
                
                exit_signal = ExitSignal(
                    position_id=position.position_id,
                    reason=exit_reason_enum,
                    exit_price=current_value,
                    exit_time=datetime.now(),
                    pnl_pct=pnl_pct,
                    pnl_dollar=pnl_dollar,
                    details={'reason': reason}
                )
                
                # Execute exit
                closed_position = await self.execute_exit(exit_signal, exit_reason_override=reason)
                if closed_position:
                    closed_positions.append(closed_position)
                    
            except Exception as e:
                log.error(f"Error closing position {position.position_id}: {e}", exc_info=True)
        
        log.info(f"✅ Closed {len(closed_positions)}/{len(open_positions)} options positions")
        
        # Send aggregated exit alert if positions were closed
        if closed_positions and self.alert_manager:
            try:
                mode = "DEMO" if self.demo_mode else "LIVE"
                closed_positions_dict = [p.to_dict() for p in closed_positions]
                await self.alert_manager.send_options_aggregated_exit_alert(
                    closed_positions=closed_positions_dict,
                    exit_reason=reason,
                    mode=mode
                )
                log.info(f"✅ Options aggregated exit alert sent for {len(closed_positions)} positions")
            except Exception as e:
                log.error(f"Failed to send options aggregated exit alert: {e}")
        
        return closed_positions
    
    def reset_daily(self):
        """Reset daily state"""
        self.positions = {}
        log.info("Options Trading Executor daily reset complete")

