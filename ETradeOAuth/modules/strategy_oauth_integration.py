#!/usr/bin/env python3
"""
Main Strategy OAuth Integration
Integrates OAuth tokens with the main trading strategy
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from .etrade_oauth_manager import oauth_manager, is_etrade_ready
from .etrade_trading_integration import get_production_trading, get_sandbox_trading

# Setup logging
log = logging.getLogger(__name__)

class StrategyOAuthIntegration:
    """Main Strategy OAuth Integration"""
    
    def __init__(self):
        self.prod_trading = get_production_trading()
        self.sandbox_trading = get_sandbox_trading()
        self.current_environment = "prod"  # Default to production
        
    def initialize_trading(self, environment: str = "prod") -> bool:
        """
        Initialize trading for specified environment
        
        Args:
            environment: 'prod' or 'sandbox'
            
        Returns:
            True if successfully initialized
        """
        try:
            self.current_environment = environment
            
            if environment == "prod":
                success = self.prod_trading.initialize()
                if success:
                    log.info("Production trading initialized successfully")
                else:
                    log.error("Failed to initialize production trading")
                return success
            else:
                success = self.sandbox_trading.initialize()
                if success:
                    log.info("Sandbox trading initialized successfully")
                else:
                    log.error("Failed to initialize sandbox trading")
                return success
                
        except Exception as e:
            log.error(f"Error initializing {environment} trading: {e}")
            return False
    
    def get_market_data(self, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """
        Get market data for symbols using OAuth tokens
        
        Args:
            symbols: List of symbols to get data for
            
        Returns:
            Market data or None if failed
        """
        try:
            if self.current_environment == "prod":
                return self.prod_trading.get_quotes(symbols)
            else:
                return self.sandbox_trading.get_quotes(symbols)
                
        except Exception as e:
            log.error(f"Error getting market data: {e}")
            return None
    
    def get_account_balance(self) -> Optional[Dict[str, Any]]:
        """
        Get account balance using OAuth tokens
        
        Returns:
            Account balance data or None if failed
        """
        try:
            if self.current_environment == "prod":
                return self.prod_trading.get_account_summary()
            else:
                return self.sandbox_trading.get_account_summary()
                
        except Exception as e:
            log.error(f"Error getting account balance: {e}")
            return None
    
    def get_current_positions(self) -> Optional[Dict[str, Any]]:
        """
        Get current positions using OAuth tokens
        
        Returns:
            Positions data or None if failed
        """
        try:
            if self.current_environment == "prod":
                return self.prod_trading.get_positions()
            else:
                return self.sandbox_trading.get_positions()
                
        except Exception as e:
            log.error(f"Error getting positions: {e}")
            return None
    
    def execute_trade(self, order_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Execute a trade using OAuth tokens
        
        Args:
            order_data: Order details
            
        Returns:
            Trade execution result or None if failed
        """
        try:
            if self.current_environment == "prod":
                return self.prod_trading.place_order(order_data)
            else:
                return self.sandbox_trading.place_order(order_data)
                
        except Exception as e:
            log.error(f"Error executing trade: {e}")
            return None
    
    def check_trading_readiness(self) -> Dict[str, Any]:
        """
        Check if trading is ready with OAuth tokens
        
        Returns:
            Trading readiness status
        """
        status = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'environment': self.current_environment,
            'oauth_ready': False,
            'trading_ready': False,
            'details': {}
        }
        
        try:
            # Check OAuth status
            oauth_status = oauth_manager.get_token_status()
            status['oauth_ready'] = oauth_status[self.current_environment]['valid']
            status['details']['oauth'] = oauth_status[self.current_environment]
            
            # Check trading status
            if self.current_environment == "prod":
                trading_status = self.prod_trading.get_trading_status()
            else:
                trading_status = self.sandbox_trading.get_trading_status()
            
            status['trading_ready'] = trading_status.get('api_accessible', False)
            status['details']['trading'] = trading_status
            
            # Overall readiness
            status['ready'] = status['oauth_ready'] and status['trading_ready']
            
        except Exception as e:
            log.error(f"Error checking trading readiness: {e}")
            status['error'] = str(e)
        
        return status
    
    def get_available_cash(self) -> Optional[float]:
        """
        Get available cash for trading
        
        Returns:
            Available cash amount or None if failed
        """
        try:
            account_data = self.get_account_balance()
            if not account_data:
                return None
            
            # Extract cash information
            accounts = account_data.get('AccountListResponse', {}).get('Accounts', {}).get('Account', [])
            if not accounts:
                return None
            
            account = accounts[0]
            balance = account.get('RealAccount', {}).get('accountBalance', {})
            
            # Get cash available for investment
            cash_available = balance.get('cashAvailableForInvestment', 0.0)
            return float(cash_available)
            
        except Exception as e:
            log.error(f"Error getting available cash: {e}")
            return None
    
    def get_buying_power(self) -> Optional[float]:
        """
        Get total buying power (cash + margin)
        
        Returns:
            Buying power amount or None if failed
        """
        try:
            account_data = self.get_account_balance()
            if not account_data:
                return None
            
            # Extract buying power information
            accounts = account_data.get('AccountListResponse', {}).get('Accounts', {}).get('Account', [])
            if not accounts:
                return None
            
            account = accounts[0]
            balance = account.get('RealAccount', {}).get('accountBalance', {})
            
            # Get total buying power
            buying_power = balance.get('cashBuyingPower', 0.0)
            return float(buying_power)
            
        except Exception as e:
            log.error(f"Error getting buying power: {e}")
            return None

# Global instance for easy import
strategy_oauth = StrategyOAuthIntegration()

def initialize_trading_strategy(environment: str = "prod") -> bool:
    """
    Initialize the trading strategy with OAuth tokens
    
    Args:
        environment: 'prod' or 'sandbox'
        
    Returns:
        True if successfully initialized
    """
    return strategy_oauth.initialize_trading(environment)

def get_strategy_oauth() -> StrategyOAuthIntegration:
    """Get the strategy OAuth integration instance"""
    return strategy_oauth

if __name__ == "__main__":
    # Test the strategy OAuth integration
    print("🧪 Testing Strategy OAuth Integration")
    print("=" * 50)
    
    # Test initialization
    print("\n📋 Initializing Trading Strategy:")
    if initialize_trading_strategy("prod"):
        print("✅ Production trading strategy initialized")
    else:
        print("❌ Failed to initialize production trading strategy")
    
    # Test readiness
    print("\n📊 Trading Readiness:")
    readiness = strategy_oauth.check_trading_readiness()
    print(f"OAuth Ready: {'✅' if readiness['oauth_ready'] else '❌'}")
    print(f"Trading Ready: {'✅' if readiness['trading_ready'] else '❌'}")
    print(f"Overall Ready: {'✅' if readiness.get('ready', False) else '❌'}")
    
    # Test account data
    print("\n💰 Account Data:")
    cash = strategy_oauth.get_available_cash()
    if cash is not None:
        print(f"Available Cash: ${cash:,.2f}")
    else:
        print("❌ Failed to get available cash")
    
    buying_power = strategy_oauth.get_buying_power()
    if buying_power is not None:
        print(f"Buying Power: ${buying_power:,.2f}")
    else:
        print("❌ Failed to get buying power")
    
    # Test market data
    print("\n📈 Market Data:")
    quotes = strategy_oauth.get_market_data(['AAPL', 'MSFT'])
    if quotes:
        print("✅ Market data retrieved successfully")
    else:
        print("❌ Failed to get market data")

