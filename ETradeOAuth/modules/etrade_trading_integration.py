#!/usr/bin/env python3
"""
E*TRADE Trading Integration with OAuth
Integrates OAuth tokens with the main trading system
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from requests_oauthlib import OAuth1Session

from .etrade_oauth_manager import oauth_manager, get_etrade_credentials, is_etrade_ready

# Setup logging
log = logging.getLogger(__name__)

class ETradeTradingIntegration:
    """E*TRADE Trading Integration with OAuth tokens"""
    
    def __init__(self, environment: str = "prod"):
        self.environment = environment
        self.base_url = "https://api.etrade.com"
        self.oauth_session = None
        self.last_credentials = None
        
    def initialize(self) -> bool:
        """
        Initialize E*TRADE trading session with OAuth tokens
        
        Returns:
            True if successfully initialized
        """
        try:
            # Check if E*TRADE is ready
            if not is_etrade_ready(self.environment):
                log.error(f"E*TRADE {self.environment} is not ready - tokens invalid or expired")
                return False
            
            # Get credentials
            credentials = get_etrade_credentials(self.environment)
            if not credentials:
                log.error(f"Failed to get {self.environment} credentials")
                return False
            
            consumer_key, consumer_secret, oauth_token, oauth_token_secret = credentials
            
            # Create OAuth session
            self.oauth_session = OAuth1Session(
                consumer_key,
                client_secret=consumer_secret,
                resource_owner_key=oauth_token,
                resource_owner_secret=oauth_token_secret
            )
            
            self.last_credentials = credentials
            log.info(f"E*TRADE {self.environment} session initialized successfully")
            return True
            
        except Exception as e:
            log.error(f"Failed to initialize E*TRADE {self.environment} session: {e}")
            return False
    
    def get_account_summary(self) -> Optional[Dict[str, Any]]:
        """
        Get account summary with OAuth tokens
        
        Returns:
            Account summary data or None if failed
        """
        if not self._ensure_session():
            return None
        
        try:
            url = f"{self.base_url}/v1/accounts/list"
            response = self.oauth_session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                log.info("Successfully retrieved account summary")
                return data
            else:
                log.error(f"Failed to get account summary: {response.status_code}")
                return None
                
        except Exception as e:
            log.error(f"Error getting account summary: {e}")
            return None
    
    def get_quotes(self, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """
        Get real-time quotes for symbols
        
        Args:
            symbols: List of symbols to get quotes for
            
        Returns:
            Quotes data or None if failed
        """
        if not self._ensure_session():
            return None
        
        try:
            # E*TRADE supports up to 10 symbols per request
            if len(symbols) > 10:
                symbols = symbols[:10]
            
            symbols_str = ",".join(symbols)
            url = f"{self.base_url}/v1/market/quote/{symbols_str}"
            response = self.oauth_session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                log.info(f"Successfully retrieved quotes for {len(symbols)} symbols")
                return data
            else:
                log.error(f"Failed to get quotes: {response.status_code}")
                return None
                
        except Exception as e:
            log.error(f"Error getting quotes: {e}")
            return None
    
    def get_positions(self) -> Optional[Dict[str, Any]]:
        """
        Get current positions
        
        Returns:
            Positions data or None if failed
        """
        if not self._ensure_session():
            return None
        
        try:
            # First get account list
            accounts_response = self.oauth_session.get(f"{self.base_url}/v1/accounts/list")
            if accounts_response.status_code != 200:
                log.error("Failed to get account list")
                return None
            
            accounts_data = accounts_response.json()
            accounts = accounts_data.get('AccountListResponse', {}).get('Accounts', {}).get('Account', [])
            
            if not accounts:
                log.warning("No accounts found")
                return None
            
            # Get positions for first account
            account_id = accounts[0]['accountIdKey']
            url = f"{self.base_url}/v1/accounts/{account_id}/portfolio"
            response = self.oauth_session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                log.info("Successfully retrieved positions")
                return data
            else:
                log.error(f"Failed to get positions: {response.status_code}")
                return None
                
        except Exception as e:
            log.error(f"Error getting positions: {e}")
            return None
    
    def place_order(self, order_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Place an order
        
        Args:
            order_data: Order details
            
        Returns:
            Order response or None if failed
        """
        if not self._ensure_session():
            return None
        
        try:
            # Get account ID
            accounts_response = self.oauth_session.get(f"{self.base_url}/v1/accounts/list")
            if accounts_response.status_code != 200:
                log.error("Failed to get account list for order")
                return None
            
            accounts_data = accounts_response.json()
            accounts = accounts_data.get('AccountListResponse', {}).get('Accounts', {}).get('Account', [])
            
            if not accounts:
                log.error("No accounts found for order")
                return None
            
            account_id = accounts[0]['accountIdKey']
            
            # Place order
            url = f"{self.base_url}/v1/accounts/{account_id}/orders/place"
            response = self.oauth_session.post(url, json=order_data)
            
            if response.status_code == 200:
                data = response.json()
                log.info("Order placed successfully")
                return data
            else:
                log.error(f"Failed to place order: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            log.error(f"Error placing order: {e}")
            return None
    
    def _ensure_session(self) -> bool:
        """
        Ensure OAuth session is valid and refresh if needed
        
        Returns:
            True if session is valid
        """
        try:
            # Check if session exists
            if not self.oauth_session:
                log.info("No OAuth session, initializing...")
                return self.initialize()
            
            # Check if credentials have changed
            current_credentials = get_etrade_credentials(self.environment)
            if current_credentials != self.last_credentials:
                log.info("Credentials changed, reinitializing session...")
                return self.initialize()
            
            # Test session with a simple API call
            try:
                test_url = f"{self.base_url}/v1/accounts/list"
                response = self.oauth_session.get(test_url)
                
                if response.status_code == 401:
                    log.warning("OAuth session expired, reinitializing...")
                    return self.initialize()
                elif response.status_code == 200:
                    return True
                else:
                    log.warning(f"Unexpected response code: {response.status_code}")
                    return self.initialize()
                    
            except Exception as e:
                log.warning(f"Session test failed: {e}, reinitializing...")
                return self.initialize()
                
        except Exception as e:
            log.error(f"Error ensuring session: {e}")
            return False
    
    def get_trading_status(self) -> Dict[str, Any]:
        """
        Get current trading status
        
        Returns:
            Status information
        """
        status = {
            'environment': self.environment,
            'session_initialized': self.oauth_session is not None,
            'etrade_ready': is_etrade_ready(self.environment),
            'last_check': datetime.now(timezone.utc).isoformat()
        }
        
        if self.oauth_session:
            # Test session
            try:
                test_url = f"{self.base_url}/v1/accounts/list"
                response = self.oauth_session.get(test_url)
                status['api_accessible'] = response.status_code == 200
                status['last_api_response'] = response.status_code
            except Exception as e:
                status['api_accessible'] = False
                status['api_error'] = str(e)
        
        return status

# Global instances for easy import
prod_trading = ETradeTradingIntegration("prod")
sandbox_trading = ETradeTradingIntegration("sandbox")

def get_production_trading() -> ETradeTradingIntegration:
    """Get production trading instance"""
    return prod_trading

def get_sandbox_trading() -> ETradeTradingIntegration:
    """Get sandbox trading instance"""
    return sandbox_trading

if __name__ == "__main__":
    # Test the trading integration
    print("🧪 Testing E*TRADE Trading Integration")
    print("=" * 50)
    
    # Test production
    print("\n📋 Production Trading:")
    prod = get_production_trading()
    if prod.initialize():
        print("✅ Production trading initialized")
        
        # Test account summary
        account = prod.get_account_summary()
        if account:
            print("✅ Account summary retrieved")
        else:
            print("❌ Failed to get account summary")
        
        # Test quotes
        quotes = prod.get_quotes(['AAPL', 'MSFT'])
        if quotes:
            print("✅ Quotes retrieved")
        else:
            print("❌ Failed to get quotes")
    else:
        print("❌ Production trading initialization failed")
    
    # Test sandbox
    print("\n📋 Sandbox Trading:")
    sandbox = get_sandbox_trading()
    if sandbox.initialize():
        print("✅ Sandbox trading initialized")
    else:
        print("❌ Sandbox trading initialization failed")
    
    # Overall status
    print("\n📊 Overall Status:")
    print(f"Production: {'✅' if is_etrade_ready('prod') else '❌'}")
    print(f"Sandbox: {'✅' if is_etrade_ready('sandbox') else '❌'}")

