#!/usr/bin/env python3
"""
E*TRADE OAuth Manager for Main Trading Strategy
Integrates OAuth tokens with the main trading system
"""

import json
import os
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

# Setup logging
log = logging.getLogger(__name__)

class ETradeOAuthManager:
    """Manages E*TRADE OAuth tokens for the trading strategy"""
    
    def __init__(self, project_id: str = "odin-187104", secret_name: str = "EtradeStrategy"):
        self.project_id = project_id
        self.secret_name = secret_name
        self.tokens_cache = {}
        self.last_refresh = None
        
    def get_tokens(self, environment: str = "prod") -> Optional[Dict[str, Any]]:
        """
        Get OAuth tokens for specified environment
        
        Args:
            environment: 'prod' or 'sandbox'
            
        Returns:
            Dict with oauth_token and oauth_token_secret, or None if not available
        """
        try:
            # Load from Secret Manager
            tokens_data = self._load_from_secret_manager()
            
            if not tokens_data:
                log.error(f"No tokens found in Secret Manager for {environment}")
                return None
            
            env_tokens = tokens_data.get(environment)
            if not env_tokens:
                log.error(f"No {environment} tokens found")
                return None
            
            # Check if tokens are expired
            if self._are_tokens_expired(env_tokens):
                log.warning(f"{environment} tokens are expired")
                return None
            
            # Cache tokens
            self.tokens_cache[environment] = env_tokens
            self.last_refresh = datetime.now()
            
            log.info(f"Successfully loaded {environment} tokens")
            return {
                'oauth_token': env_tokens.get('oauth_token'),
                'oauth_token_secret': env_tokens.get('oauth_token_secret'),
                'environment': environment,
                'expires_at': env_tokens.get('expires_at')
            }
            
        except Exception as e:
            log.error(f"Error getting {environment} tokens: {e}")
            return None
    
    def get_production_tokens(self) -> Optional[Dict[str, Any]]:
        """Get production OAuth tokens"""
        return self.get_tokens("prod")
    
    def get_sandbox_tokens(self) -> Optional[Dict[str, Any]]:
        """Get sandbox OAuth tokens"""
        return self.get_tokens("sandbox")
    
    def are_tokens_valid(self, environment: str = "prod") -> bool:
        """
        Check if tokens are valid for trading
        
        Args:
            environment: 'prod' or 'sandbox'
            
        Returns:
            True if tokens are valid and not expired
        """
        tokens = self.get_tokens(environment)
        return tokens is not None
    
    def get_trading_credentials(self, environment: str = "prod") -> Optional[Tuple[str, str]]:
        """
        Get credentials for E*TRADE API calls
        
        Args:
            environment: 'prod' or 'sandbox'
            
        Returns:
            Tuple of (consumer_key, consumer_secret, oauth_token, oauth_token_secret)
        """
        try:
            # Get OAuth tokens
            tokens = self.get_tokens(environment)
            if not tokens:
                return None
            
            # Load consumer credentials from .env
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent.parent / '.env')
            
            if environment == "sandbox":
                consumer_key = os.getenv('ETRADE_SANDBOX_KEY') or os.getenv('ETRADE_CONSUMER_KEY')
                consumer_secret = os.getenv('ETRADE_SANDBOX_SECRET') or os.getenv('ETRADE_CONSUMER_SECRET')
            else:
                consumer_key = os.getenv('ETRADE_CONSUMER_KEY')
                consumer_secret = os.getenv('ETRADE_CONSUMER_SECRET')
            
            if not consumer_key or not consumer_secret:
                log.error(f"No consumer credentials found for {environment}")
                return None
            
            return (consumer_key, consumer_secret, tokens['oauth_token'], tokens['oauth_token_secret'])
            
        except Exception as e:
            log.error(f"Error getting trading credentials: {e}")
            return None
    
    def _load_from_secret_manager(self) -> Optional[Dict[str, Any]]:
        """Load tokens from Google Secret Manager"""
        try:
            result = subprocess.run([
                'gcloud', 'secrets', 'versions', 'access', 'latest',
                '--secret', self.secret_name,
                '--project', self.project_id
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                
                # Handle old format (single token object)
                if 'oauth_token' in data and 'oauth_token_secret' in data:
                    # Convert old format to new format
                    log.info("Converting old token format to new format")
                    return {
                        'prod': data,
                        'metadata': {
                            'stored_at': data.get('created_at', datetime.now(timezone.utc).isoformat()),
                            'project_id': self.project_id,
                            'secret_name': self.secret_name
                        }
                    }
                
                # Handle new format (with prod/sandbox keys)
                return data
            else:
                log.error(f"Failed to load from Secret Manager: {result.stderr}")
                return None
                
        except Exception as e:
            log.error(f"Error loading from Secret Manager: {e}")
            return None
    
    def _are_tokens_expired(self, tokens: Dict[str, Any]) -> bool:
        """Check if tokens are expired"""
        try:
            expires_at_str = tokens.get('expires_at')
            if not expires_at_str:
                return True
            
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            
            return now >= expires_at
            
        except Exception as e:
            log.error(f"Error checking token expiry: {e}")
            return True
    
    def get_token_status(self) -> Dict[str, Any]:
        """Get status of all tokens"""
        status = {
            'prod': {'valid': False, 'expires_at': None, 'message': 'Not loaded'},
            'sandbox': {'valid': False, 'expires_at': None, 'message': 'Not loaded'},
            'last_refresh': self.last_refresh.isoformat() if self.last_refresh else None
        }
        
        for env in ['prod', 'sandbox']:
            tokens = self.get_tokens(env)
            if tokens:
                status[env] = {
                    'valid': True,
                    'expires_at': tokens.get('expires_at'),
                    'message': 'Valid and ready for trading'
                }
            else:
                status[env] = {
                    'valid': False,
                    'expires_at': None,
                    'message': 'Invalid or expired'
                }
        
        return status

# Global instance for easy import
oauth_manager = ETradeOAuthManager()

def get_etrade_credentials(environment: str = "prod") -> Optional[Tuple[str, str, str, str]]:
    """
    Convenience function to get E*TRADE credentials
    
    Args:
        environment: 'prod' or 'sandbox'
        
    Returns:
        Tuple of (consumer_key, consumer_secret, oauth_token, oauth_token_secret)
    """
    return oauth_manager.get_trading_credentials(environment)

def is_etrade_ready(environment: str = "prod") -> bool:
    """
    Check if E*TRADE is ready for trading
    
    Args:
        environment: 'prod' or 'sandbox'
        
    Returns:
        True if ready for trading
    """
    return oauth_manager.are_tokens_valid(environment)

if __name__ == "__main__":
    # Test the OAuth manager
    print("🧪 Testing E*TRADE OAuth Manager")
    print("=" * 40)
    
    manager = ETradeOAuthManager()
    
    # Test production tokens
    print("\n📋 Production Tokens:")
    prod_tokens = manager.get_production_tokens()
    if prod_tokens:
        print(f"✅ Valid: {prod_tokens['oauth_token'][:20]}...")
        print(f"⏰ Expires: {prod_tokens['expires_at']}")
    else:
        print("❌ Invalid or expired")
    
    # Test sandbox tokens
    print("\n📋 Sandbox Tokens:")
    sandbox_tokens = manager.get_sandbox_tokens()
    if sandbox_tokens:
        print(f"✅ Valid: {sandbox_tokens['oauth_token'][:20]}...")
        print(f"⏰ Expires: {sandbox_tokens['expires_at']}")
    else:
        print("❌ Invalid or expired")
    
    # Test trading credentials
    print("\n🔑 Trading Credentials:")
    prod_creds = manager.get_trading_credentials("prod")
    if prod_creds:
        print(f"✅ Production: {prod_creds[0][:8]}...")
    else:
        print("❌ Production: Not available")
    
    sandbox_creds = manager.get_trading_credentials("sandbox")
    if sandbox_creds:
        print(f"✅ Sandbox: {sandbox_creds[0][:8]}...")
    else:
        print("❌ Sandbox: Not available")
    
    # Overall status
    print("\n📊 Overall Status:")
    status = manager.get_token_status()
    for env, info in status.items():
        if env != 'last_refresh':
            print(f"{env.upper()}: {'✅' if info['valid'] else '❌'} {info['message']}")

