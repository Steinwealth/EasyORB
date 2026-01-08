#!/usr/bin/env python3
"""
ETrade Options API Integration
===============================

ETrade API integration for options trading:
- Options chain fetching
- Options order placement (debit spreads, single-leg)
- Options position tracking

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
import os
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

# Import ETrade trading module from ORB Strategy
# Note: When integrated with ORB Strategy, this will use the shared PrimeETradeTrading instance
try:
    # Try relative import first (when modules are in same project)
    import sys
    import os
    orb_strategy_path = os.path.join(os.path.dirname(__file__), '../../1. The Easy ORB Strategy')
    if os.path.exists(orb_strategy_path):
        sys.path.insert(0, orb_strategy_path)
        from modules.prime_etrade_trading import PrimeETradeTrading
        ETRADE_AVAILABLE = True
    else:
        # Try direct import (when integrated)
        from modules.prime_etrade_trading import PrimeETradeTrading
        ETRADE_AVAILABLE = True
except ImportError:
    # Define a dummy class for type hints when ETrade is not available
    class PrimeETradeTrading:
        pass
    ETRADE_AVAILABLE = False
    logging.warning("ETrade trading module not available - will use mock/demo mode")

log = logging.getLogger(__name__)


@dataclass
class ETradeOptionContract:
    """ETrade Option Contract data"""
    symbol: str
    strike: float
    expiry: str
    option_type: str  # 'CALL' or 'PUT'
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    implied_volatility: Optional[float] = None
    
    @property
    def mid_price(self) -> float:
        """Calculate mid price"""
        return (self.bid + self.ask) / 2.0 if self.bid > 0 and self.ask > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'strike': self.strike,
            'expiry': self.expiry,
            'option_type': self.option_type.lower(),
            'bid': self.bid,
            'ask': self.ask,
            'last': self.last,
            'volume': self.volume,
            'open_interest': self.open_interest,
            'delta': self.delta,
            'gamma': self.gamma,
            'theta': self.theta,
            'vega': self.vega,
            'implied_volatility': self.implied_volatility,
            'mid_price': self.mid_price
        }


class ETradeOptionsAPI:
    """
    ETrade Options API Integration
    
    Handles options chain fetching and options order placement via ETrade API.
    """
    
    def __init__(
        self, 
        etrade_trading: Optional[PrimeETradeTrading] = None, 
        environment: str = 'prod',
        account_id: Optional[str] = None,
        secret_name: Optional[str] = None
    ):
        """
        Initialize ETrade Options API
        
        Args:
            etrade_trading: PrimeETradeTrading instance (optional, will create if None)
            environment: 'prod' or 'sandbox'
            account_id: Specific account ID to use (optional, for separate 0DTE account)
            secret_name: Secret Manager name for OAuth tokens (optional, for separate account)
                         Default: 'etrade-oauth-prod' or 'etrade-oauth-sandbox'
                         For separate 0DTE account: 'etrade-oauth-0dte-prod' or 'etrade-oauth-0dte-sandbox'
        """
        self.environment = environment
        self.account_id = account_id  # Rev 00218: Support separate account selection
        
        if etrade_trading:
            self.etrade = etrade_trading
            # Rev 00218: Select specific account if provided
            if account_id and hasattr(self.etrade, 'select_account'):
                if self.etrade.select_account(account_id):
                    log.info(f"✅ Selected 0DTE Strategy account: {account_id}")
                else:
                    log.warning(f"⚠️ Failed to select account {account_id}, using default account")
        elif ETRADE_AVAILABLE:
            try:
                # Rev 00218: Support separate OAuth tokens for 0DTE Strategy
                # If secret_name is provided, we need to create a custom PrimeETradeTrading instance
                # For now, create standard instance - account selection happens after initialization
                self.etrade = PrimeETradeTrading(environment=environment)
                if not self.etrade.initialize():
                    log.error("Failed to initialize ETrade trading system")
                    self.etrade = None
                else:
                    # Rev 00218: Select specific account if provided
                    if account_id and hasattr(self.etrade, 'select_account'):
                        if self.etrade.select_account(account_id):
                            log.info(f"✅ Selected 0DTE Strategy account: {account_id}")
                        else:
                            log.warning(f"⚠️ Account {account_id} not found, using default account")
                            log.info(f"   Available accounts: {[acc.account_id for acc in self.etrade.accounts]}")
            except Exception as e:
                log.error(f"Failed to create ETrade trading instance: {e}")
                self.etrade = None
        else:
            self.etrade = None
            log.warning("ETrade Options API not available - ETrade module not found")
    
    def is_available(self) -> bool:
        """Check if ETrade API is available"""
        return self.etrade is not None and self.etrade.is_authenticated()
    
    async def fetch_options_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None,
        strike_count: int = 20,
        include_greeks: bool = True
    ) -> Dict[str, List[ETradeOptionContract]]:
        """
        Fetch options chain from ETrade API
        
        Args:
            symbol: Underlying symbol (QQQ or SPY)
            expiry: Expiry date (YYYYMMDD format, None = 0DTE)
            strike_count: Number of strikes above/below ATM
            include_greeks: Include Greeks in response
            
        Returns:
            Dictionary with 'calls' and 'puts' lists
        """
        if not self.is_available():
            log.error("ETrade API not available for options chain fetch")
            return {'calls': [], 'puts': []}
        
        try:
            # Use today's date for 0DTE if expiry not specified
            if expiry is None:
                expiry = datetime.now().strftime('%Y%m%d')
            
            log.info(f"📊 Fetching options chain for {symbol} expiry {expiry}")
            
            # ETrade API endpoint: /v1/market/optionchains
            # Uses same OAuth authentication as ETF endpoints via _make_etrade_api_call()
            
            # Option 1: Use PrimeETradeTrading's built-in method (if available)
            if hasattr(self.etrade, 'get_option_chains'):
                # Convert expiry format: YYYYMMDD -> YYYY-MM-DD
                expiry_formatted = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:8]}"
                response = self.etrade.get_option_chains(
                    symbol=symbol,
                    expiry_date=expiry_formatted,
                    option_type='CALL'  # Will fetch both calls and puts
                )
            else:
                # Option 2: Direct API call (fallback)
                url = f"{self.etrade.config['base_url']}/v1/market/optionchains"
                params = {
                    'symbol': symbol,
                    'expiryDate': expiry,
                    'strikeCount': strike_count,
                    'includeGreeks': 'true' if include_greeks else 'false'
                }
                
                # Make API call (uses same OAuth authentication)
                response = self.etrade._make_etrade_api_call(
                    method='GET',
                    url=url,
                    params=params
                )
            
            # Parse response
            if 'OptionChainResponse' in response:
                chain_data = response['OptionChainResponse']
                option_pairs = chain_data.get('OptionPair', [])
                
                calls = []
                puts = []
                
                for pair in option_pairs:
                    call_data = pair.get('Call', {})
                    put_data = pair.get('Put', {})
                    
                    strike = float(pair.get('strikePrice', 0))
                    
                    # Parse call option
                    if call_data:
                        call = ETradeOptionContract(
                            symbol=symbol,
                            strike=strike,
                            expiry=expiry,
                            option_type='CALL',
                            bid=float(call_data.get('bid', 0)),
                            ask=float(call_data.get('ask', 0)),
                            last=float(call_data.get('lastPrice', 0)),
                            volume=int(call_data.get('volume', 0)),
                            open_interest=int(call_data.get('openInterest', 0)),
                            delta=float(call_data.get('OptionGreeks', {}).get('delta', 0)) if call_data.get('OptionGreeks') else None,
                            gamma=float(call_data.get('OptionGreeks', {}).get('gamma', 0)) if call_data.get('OptionGreeks') else None,
                            theta=float(call_data.get('OptionGreeks', {}).get('theta', 0)) if call_data.get('OptionGreeks') else None,
                            vega=float(call_data.get('OptionGreeks', {}).get('vega', 0)) if call_data.get('OptionGreeks') else None,
                            implied_volatility=float(call_data.get('OptionGreeks', {}).get('iv', 0)) if call_data.get('OptionGreeks') else None
                        )
                        calls.append(call)
                    
                    # Parse put option
                    if put_data:
                        put = ETradeOptionContract(
                            symbol=symbol,
                            strike=strike,
                            expiry=expiry,
                            option_type='PUT',
                            bid=float(put_data.get('bid', 0)),
                            ask=float(put_data.get('ask', 0)),
                            last=float(put_data.get('lastPrice', 0)),
                            volume=int(put_data.get('volume', 0)),
                            open_interest=int(put_data.get('openInterest', 0)),
                            delta=float(put_data.get('OptionGreeks', {}).get('delta', 0)) if put_data.get('OptionGreeks') else None,
                            gamma=float(put_data.get('OptionGreeks', {}).get('gamma', 0)) if put_data.get('OptionGreeks') else None,
                            theta=float(put_data.get('OptionGreeks', {}).get('theta', 0)) if put_data.get('OptionGreeks') else None,
                            vega=float(put_data.get('OptionGreeks', {}).get('vega', 0)) if put_data.get('OptionGreeks') else None,
                            implied_volatility=float(put_data.get('OptionGreeks', {}).get('iv', 0)) if put_data.get('OptionGreeks') else None
                        )
                        puts.append(put)
                
                log.info(f"✅ Fetched options chain: {len(calls)} calls, {len(puts)} puts")
                return {'calls': calls, 'puts': puts}
            else:
                log.warning(f"Unexpected response format: {response}")
                return {'calls': [], 'puts': []}
                
        except Exception as e:
            log.error(f"Failed to fetch options chain: {e}")
            return {'calls': [], 'puts': []}
    
    async def place_debit_spread_order(
        self,
        symbol: str,
        expiry: str,
        option_type: str,
        long_strike: float,
        short_strike: float,
        quantity: int = 1
    ) -> Optional[Dict[str, Any]]:
        """
        Place debit spread order via ETrade API
        
        Args:
            symbol: Underlying symbol
            expiry: Expiry date (YYYYMMDD)
            option_type: 'call' or 'put'
            long_strike: Long leg strike
            short_strike: Short leg strike
            quantity: Number of spreads
            
        Returns:
            Order response or None if failed
        """
        if not self.is_available():
            log.error("ETrade API not available for order placement")
            return None
        
        try:
            log.info(f"📝 Placing debit spread order: {symbol} {option_type.upper()} {long_strike}/{short_strike}")
            
            # Build option symbol strings
            # Format: SYMBOL YYMMDD C/P STRIKE
            # Example: QQQ 251219C400 (QQQ Dec 19 2025 Call $400)
            expiry_short = expiry[2:]  # YYMMDD
            option_type_code = 'C' if option_type.lower() == 'call' else 'P'
            
            long_option_symbol = f"{symbol} {expiry_short}{option_type_code}{int(long_strike * 1000):08d}"
            short_option_symbol = f"{symbol} {expiry_short}{option_type_code}{int(short_strike * 1000):08d}"
            
            # Build order data for ETrade API
            # ETrade uses a complex order structure for spreads
            order_data = {
                'orderType': 'NET_DEBIT',
                'clientOrderId': f"0DTE_{int(time.time())}",
                'orderTerm': 'GOOD_FOR_DAY',
                'priceType': 'NET_DEBIT',
                'Order': [{
                    'Instrument': [
                        {
                            'Product': {
                                'securityType': 'OPTION',
                                'symbol': long_option_symbol
                            },
                            'orderAction': 'BUY_OPEN',
                            'quantity': quantity
                        },
                        {
                            'Product': {
                                'securityType': 'OPTION',
                                'symbol': short_option_symbol
                            },
                            'orderAction': 'SELL_OPEN',
                            'quantity': quantity
                        }
                    ]
                }]
            }
            
            # Preview order first
            preview_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/preview"
            preview_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=preview_url,
                params=order_data
            )
            
            if 'PreviewOrderResponse' not in preview_response:
                log.error(f"Preview failed: {preview_response}")
                return None
            
            preview_id = preview_response['PreviewOrderResponse'].get('previewId')
            if not preview_id:
                log.error("No preview ID returned")
                return None
            
            # Place order
            order_data['previewId'] = preview_id
            place_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/place"
            
            place_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=place_url,
                params=order_data
            )
            
            log.info(f"✅ Debit spread order placed: {place_response}")
            return place_response
            
        except Exception as e:
            log.error(f"Failed to place debit spread order: {e}")
            return None
    
    async def place_single_option_order(
        self,
        symbol: str,
        expiry: str,
        option_type: str,
        strike: float,
        side: str,
        quantity: int = 1
    ) -> Optional[Dict[str, Any]]:
        """
        Place single-leg option order (lotto sleeve) via ETrade API
        
        Args:
            symbol: Underlying symbol
            expiry: Expiry date (YYYYMMDD)
            option_type: 'call' or 'put'
            strike: Strike price
            side: 'BUY' or 'SELL'
            quantity: Number of contracts
            
        Returns:
            Order response or None if failed
        """
        if not self.is_available():
            log.error("ETrade API not available for order placement")
            return None
        
        try:
            log.info(f"📝 Placing single option order: {symbol} {option_type.upper()} {strike} {side}")
            
            # Build option symbol string
            expiry_short = expiry[2:]  # YYMMDD
            option_type_code = 'C' if option_type.lower() == 'call' else 'P'
            option_symbol = f"{symbol} {expiry_short}{option_type_code}{int(strike * 1000):08d}"
            
            # Build order data
            order_action = 'BUY_OPEN' if side == 'BUY' else 'SELL_OPEN'
            
            order_data = {
                'orderType': 'MARKET',
                'clientOrderId': f"0DTE_LOTTO_{int(time.time())}",
                'orderTerm': 'GOOD_FOR_DAY',
                'priceType': 'MARKET',
                'Order': [{
                    'Instrument': [{
                        'Product': {
                            'securityType': 'OPTION',
                            'symbol': option_symbol
                        },
                        'orderAction': order_action,
                        'quantity': quantity
                    }]
                }]
            }
            
            # Preview order first
            preview_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/preview"
            preview_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=preview_url,
                params=order_data
            )
            
            if 'PreviewOrderResponse' not in preview_response:
                log.error(f"Preview failed: {preview_response}")
                return None
            
            preview_id = preview_response['PreviewOrderResponse'].get('previewId')
            if not preview_id:
                log.error("No preview ID returned")
                return None
            
            # Place order
            order_data['previewId'] = preview_id
            place_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/place"
            
            place_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=place_url,
                params=order_data
            )
            
            log.info(f"✅ Single option order placed: {place_response}")
            return place_response
            
        except Exception as e:
            log.error(f"Failed to place single option order: {e}")
            return None
    
    async def place_credit_spread_order(
        self,
        symbol: str,
        expiry: str,
        option_type: str,
        short_strike: float,
        long_strike: float,
        quantity: int = 1
    ) -> Optional[Dict[str, Any]]:
        """
        Place credit spread order via ETrade API
        
        For credit spreads:
        - CALL credit spread: Sell call at lower strike, buy call at higher strike (bearish)
        - PUT credit spread: Sell put at higher strike, buy put at lower strike (bullish)
        
        Args:
            symbol: Underlying symbol
            expiry: Expiry date (YYYYMMDD)
            option_type: 'call' or 'put'
            short_strike: Short leg strike (sell this)
            long_strike: Long leg strike (buy this for protection)
            quantity: Number of spreads
            
        Returns:
            Order response or None if failed
        """
        if not self.is_available():
            log.error("ETrade API not available for order placement")
            return None
        
        try:
            log.info(f"📝 Placing credit spread order: {symbol} {option_type.upper()} {short_strike}/{long_strike}")
            
            # Build option symbol strings
            # Format: SYMBOL YYMMDD C/P STRIKE
            expiry_short = expiry[2:]  # YYMMDD
            option_type_code = 'C' if option_type.lower() == 'call' else 'P'
            
            short_option_symbol = f"{symbol} {expiry_short}{option_type_code}{int(short_strike * 1000):08d}"
            long_option_symbol = f"{symbol} {expiry_short}{option_type_code}{int(long_strike * 1000):08d}"
            
            # Build order data for ETrade API
            # Credit spread: NET_CREDIT (receive premium)
            # Order: Sell short leg, buy long leg
            order_data = {
                'orderType': 'NET_CREDIT',
                'clientOrderId': f"0DTE_CREDIT_{int(time.time())}",
                'orderTerm': 'GOOD_FOR_DAY',
                'priceType': 'NET_CREDIT',
                'Order': [{
                    'Instrument': [
                        {
                            'Product': {
                                'securityType': 'OPTION',
                                'symbol': short_option_symbol
                            },
                            'orderAction': 'SELL_OPEN',  # Sell short leg (receive premium)
                            'quantity': quantity
                        },
                        {
                            'Product': {
                                'securityType': 'OPTION',
                                'symbol': long_option_symbol
                            },
                            'orderAction': 'BUY_OPEN',  # Buy long leg (protection)
                            'quantity': quantity
                        }
                    ]
                }]
            }
            
            # Preview order first
            preview_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/preview"
            preview_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=preview_url,
                params=order_data
            )
            
            if 'PreviewOrderResponse' not in preview_response:
                log.error(f"Preview failed: {preview_response}")
                return None
            
            preview_id = preview_response['PreviewOrderResponse'].get('previewId')
            if not preview_id:
                log.error("No preview ID returned")
                return None
            
            # Place order
            order_data['previewId'] = preview_id
            place_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/place"
            
            place_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=place_url,
                params=order_data
            )
            
            log.info(f"✅ Credit spread order placed: {place_response}")
            return place_response
            
        except Exception as e:
            log.error(f"Failed to place credit spread order: {e}")
            return None
    
    async def close_position(
        self,
        position: 'OptionsPosition',
        exit_price: Optional[float] = None,
        order_type: str = 'MARKET'
    ) -> Optional[Dict[str, Any]]:
        """
        Close options position via ETrade API
        
        Args:
            position: OptionsPosition object to close
            exit_price: Exit price (for LIMIT orders, None = use MARKET)
            order_type: 'MARKET' or 'LIMIT'
            
        Returns:
            Order response or None if failed
        """
        if not self.is_available():
            log.error("ETrade API not available for position close")
            return None
        
        try:
            log.info(f"📝 Closing options position: {position.position_id}")
            log.info(f"   Symbol: {position.symbol}, Type: {position.position_type}")
            log.info(f"   Quantity: {position.quantity}, Exit Price: ${exit_price or 'MARKET'}")
            
            # Determine order structure based on position type
            if position.position_type == 'debit_spread':
                # Close debit spread: Buy back short leg, sell long leg
                spread = position.debit_spread
                expiry_short = spread.expiry.replace('-', '')[2:]  # YYMMDD
                option_type_code = 'C' if spread.option_type.lower() == 'call' else 'P'
                
                long_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.long_strike * 1000):08d}"
                short_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.short_strike * 1000):08d}"
                
                # Close spread: Buy back short leg (close short), sell long leg (close long)
                order_data = {
                    'orderType': 'NET_CREDIT' if exit_price else 'MARKET',
                    'clientOrderId': f"0DTE_CLOSE_{int(time.time())}",
                    'orderTerm': 'GOOD_FOR_DAY',
                    'priceType': 'NET_CREDIT' if exit_price else 'MARKET',
                    'Order': [{
                        'Instrument': [
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': short_option_symbol
                                },
                                'orderAction': 'BUY_CLOSE',  # Buy back short leg
                                'quantity': position.quantity
                            },
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': long_option_symbol
                                },
                                'orderAction': 'SELL_CLOSE',  # Sell long leg
                                'quantity': position.quantity
                            }
                        ]
                    }]
                }
                
                if exit_price and order_type == 'LIMIT':
                    order_data['Order'][0]['limitPrice'] = exit_price
                    
            elif position.position_type == 'credit_spread':
                # Close credit spread: Buy back short leg, sell long leg
                spread = position.credit_spread
                expiry_short = spread.expiry.replace('-', '')[2:]  # YYMMDD
                option_type_code = 'C' if spread.option_type.lower() == 'call' else 'P'
                
                short_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.short_strike * 1000):08d}"
                long_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.long_strike * 1000):08d}"
                
                # Close spread: Buy back short leg (close short), sell long leg (close long)
                order_data = {
                    'orderType': 'NET_DEBIT' if exit_price else 'MARKET',
                    'clientOrderId': f"0DTE_CLOSE_{int(time.time())}",
                    'orderTerm': 'GOOD_FOR_DAY',
                    'priceType': 'NET_DEBIT' if exit_price else 'MARKET',
                    'Order': [{
                        'Instrument': [
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': short_option_symbol
                                },
                                'orderAction': 'BUY_CLOSE',  # Buy back short leg
                                'quantity': position.quantity
                            },
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': long_option_symbol
                                },
                                'orderAction': 'SELL_CLOSE',  # Sell long leg
                                'quantity': position.quantity
                            }
                        ]
                    }]
                }
                
                if exit_price and order_type == 'LIMIT':
                    order_data['Order'][0]['limitPrice'] = exit_price
                    
            elif position.position_type == 'lotto':
                # Close single-leg option: Sell the contract
                contract = position.lotto_contract
                expiry_short = contract.expiry.replace('-', '')[2:]  # YYMMDD
                option_type_code = 'C' if contract.option_type.lower() == 'call' else 'P'
                option_symbol = f"{contract.symbol} {expiry_short}{option_type_code}{int(contract.strike * 1000):08d}"
                
                order_data = {
                    'orderType': order_type,
                    'clientOrderId': f"0DTE_CLOSE_{int(time.time())}",
                    'orderTerm': 'GOOD_FOR_DAY',
                    'priceType': order_type,
                    'Order': [{
                        'Instrument': [{
                            'Product': {
                                'securityType': 'OPTION',
                                'symbol': option_symbol
                            },
                            'orderAction': 'SELL_CLOSE',  # Close long position
                            'quantity': position.quantity
                        }]
                    }]
                }
                
                if exit_price and order_type == 'LIMIT':
                    order_data['Order'][0]['limitPrice'] = exit_price
            else:
                log.error(f"Unknown position type: {position.position_type}")
                return None
            
            # Preview order first
            preview_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/preview"
            preview_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=preview_url,
                params=order_data
            )
            
            if 'PreviewOrderResponse' not in preview_response:
                log.error(f"Preview failed: {preview_response}")
                return None
            
            preview_id = preview_response['PreviewOrderResponse'].get('previewId')
            if not preview_id:
                log.error("No preview ID returned")
                return None
            
            # Place order
            order_data['previewId'] = preview_id
            place_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/place"
            
            place_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=place_url,
                params=order_data
            )
            
            log.info(f"✅ Options position closed: {place_response}")
            return place_response
            
        except Exception as e:
            log.error(f"Failed to close options position: {e}")
            return None
    
    async def partial_close_position(
        self,
        position: 'OptionsPosition',
        partial_quantity: int,
        exit_price: Optional[float] = None,
        order_type: str = 'MARKET'
    ) -> Optional[Dict[str, Any]]:
        """
        Partially close options position via ETrade API
        
        Args:
            position: OptionsPosition object to partially close
            partial_quantity: Number of contracts/spreads to close (must be < position.quantity)
            exit_price: Exit price (for LIMIT orders, None = use MARKET)
            order_type: 'MARKET' or 'LIMIT'
            
        Returns:
            Order response or None if failed
        """
        if not self.is_available():
            log.error("ETrade API not available for partial position close")
            return None
        
        if partial_quantity >= position.quantity:
            log.error(f"Partial quantity {partial_quantity} must be less than position quantity {position.quantity}")
            return None
        
        try:
            log.info(f"📝 Partially closing options position: {position.position_id}")
            log.info(f"   Symbol: {position.symbol}, Type: {position.position_type}")
            log.info(f"   Closing: {partial_quantity}/{position.quantity} contracts, Exit Price: ${exit_price or 'MARKET'}")
            
            # Determine order structure based on position type
            if position.position_type == 'debit_spread':
                # Partially close debit spread: Buy back short leg, sell long leg (partial quantity)
                spread = position.debit_spread
                expiry_short = spread.expiry.replace('-', '')[2:]  # YYMMDD
                option_type_code = 'C' if spread.option_type.lower() == 'call' else 'P'
                
                long_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.long_strike * 1000):08d}"
                short_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.short_strike * 1000):08d}"
                
                # Partially close spread: Buy back short leg (close short), sell long leg (close long)
                order_data = {
                    'orderType': 'NET_CREDIT' if exit_price else 'MARKET',
                    'clientOrderId': f"0DTE_PARTIAL_{int(time.time())}",
                    'orderTerm': 'GOOD_FOR_DAY',
                    'priceType': 'NET_CREDIT' if exit_price else 'MARKET',
                    'Order': [{
                        'Instrument': [
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': short_option_symbol
                                },
                                'orderAction': 'BUY_CLOSE',  # Buy back short leg
                                'quantity': partial_quantity
                            },
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': long_option_symbol
                                },
                                'orderAction': 'SELL_CLOSE',  # Sell long leg
                                'quantity': partial_quantity
                            }
                        ]
                    }]
                }
                
                if exit_price and order_type == 'LIMIT':
                    order_data['Order'][0]['limitPrice'] = exit_price
                    
            elif position.position_type == 'credit_spread':
                # Partially close credit spread: Buy back short leg, sell long leg (partial quantity)
                spread = position.credit_spread
                expiry_short = spread.expiry.replace('-', '')[2:]  # YYMMDD
                option_type_code = 'C' if spread.option_type.lower() == 'call' else 'P'
                
                short_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.short_strike * 1000):08d}"
                long_option_symbol = f"{spread.symbol} {expiry_short}{option_type_code}{int(spread.long_strike * 1000):08d}"
                
                # Partially close spread: Buy back short leg (close short), sell long leg (close long)
                order_data = {
                    'orderType': 'NET_DEBIT' if exit_price else 'MARKET',
                    'clientOrderId': f"0DTE_PARTIAL_{int(time.time())}",
                    'orderTerm': 'GOOD_FOR_DAY',
                    'priceType': 'NET_DEBIT' if exit_price else 'MARKET',
                    'Order': [{
                        'Instrument': [
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': short_option_symbol
                                },
                                'orderAction': 'BUY_CLOSE',  # Buy back short leg
                                'quantity': partial_quantity
                            },
                            {
                                'Product': {
                                    'securityType': 'OPTION',
                                    'symbol': long_option_symbol
                                },
                                'orderAction': 'SELL_CLOSE',  # Sell long leg
                                'quantity': partial_quantity
                            }
                        ]
                    }]
                }
                
                if exit_price and order_type == 'LIMIT':
                    order_data['Order'][0]['limitPrice'] = exit_price
                    
            elif position.position_type == 'lotto':
                # Partially close single-leg option: Sell partial quantity
                contract = position.lotto_contract
                expiry_short = contract.expiry.replace('-', '')[2:]  # YYMMDD
                option_type_code = 'C' if contract.option_type.lower() == 'call' else 'P'
                option_symbol = f"{contract.symbol} {expiry_short}{option_type_code}{int(contract.strike * 1000):08d}"
                
                order_data = {
                    'orderType': order_type,
                    'clientOrderId': f"0DTE_PARTIAL_{int(time.time())}",
                    'orderTerm': 'GOOD_FOR_DAY',
                    'priceType': order_type,
                    'Order': [{
                        'Instrument': [{
                            'Product': {
                                'securityType': 'OPTION',
                                'symbol': option_symbol
                            },
                            'orderAction': 'SELL_CLOSE',  # Close long position (partial)
                            'quantity': partial_quantity
                        }]
                    }]
                }
                
                if exit_price and order_type == 'LIMIT':
                    order_data['Order'][0]['limitPrice'] = exit_price
            else:
                log.error(f"Unknown position type: {position.position_type}")
                return None
            
            # Preview order first
            preview_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/preview"
            preview_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=preview_url,
                params=order_data
            )
            
            if 'PreviewOrderResponse' not in preview_response:
                log.error(f"Preview failed: {preview_response}")
                return None
            
            preview_id = preview_response['PreviewOrderResponse'].get('previewId')
            if not preview_id:
                log.error("No preview ID returned")
                return None
            
            # Place order
            order_data['previewId'] = preview_id
            place_url = f"{self.etrade.config['base_url']}/v1/accounts/{self.etrade.selected_account.account_id_key}/orders/place"
            
            place_response = self.etrade._make_etrade_api_call(
                method='POST',
                url=place_url,
                params=order_data
            )
            
            log.info(f"✅ Options position partially closed: {partial_quantity} contracts")
            log.info(f"   Remaining: {position.quantity - partial_quantity} contracts")
            return place_response
            
        except Exception as e:
            log.error(f"Failed to partially close options position: {e}")
            return None

