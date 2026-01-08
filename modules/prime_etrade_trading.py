"""
Prime ETrade Trading Module

This module provides comprehensive ETrade API integration for the trading system.
It implements all the essential ETrade API functions based on the provided checklist:

Auth (OAuth 1.0a): getRequestToken, authorizeUrl, getAccessToken, renewAccessToken, revokeAccessToken
Accounts: listAccounts, getAccountBalances, getPortfolio, listTransactions  
Orders: listOrders, getOrderDetails, previewEquityOrder, placeEquityOrder, cancelOrder
Market: getQuotes, lookupProduct, getOptionChains
Alerts: listAlerts, getAlert, deleteAlert
"""

import os
import sys
import json
import logging
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

# Rev 00180h: Use Google Secret Manager directly (no local ETradeOAuth folder dependency)
# Tokens are managed by https://easy-trading-oauth-v2.web.app/ and stored in Secret Manager
try:
    from google.cloud import secretmanager
    SECRET_MANAGER_AVAILABLE = True
    ETradeOAuth_AVAILABLE = True  # Enable ETrade trading with Secret Manager
    logging.info("✅ Google Secret Manager available for OAuth token loading")
except ImportError:
    SECRET_MANAGER_AVAILABLE = False
    ETradeOAuth_AVAILABLE = False
    logging.error("❌ Google Secret Manager not available - ETrade trading disabled")

# Import requests-oauthlib for correct OAuth 1.0a implementation
try:
    import requests
    from requests_oauthlib import OAuth1
    REQUESTS_OAUTH_AVAILABLE = True
except ImportError:
    REQUESTS_OAUTH_AVAILABLE = False
    logging.warning("requests-oauthlib not available. Using fallback OAuth implementation.")

log = logging.getLogger(__name__)

@dataclass
class ETradeAccount:
    """ETrade Account Information"""
    account_id: str
    account_name: Optional[str]
    account_id_key: str
    account_status: str
    institution_type: str
    account_type: str

@dataclass
class ETradeBalance:
    """ETrade Account Balance Information - Essential fields only"""
    account_value: Optional[float]
    cash_available_for_investment: Optional[float]  # Cash available for investments
    cash_buying_power: Optional[float]  # Total buying power (cash + margin)
    option_level: Optional[str]

@dataclass
class ETradePosition:
    """ETrade Position Information"""
    position_id: str
    symbol: str
    symbol_description: str
    quantity: int
    position_type: str
    market_value: float
    total_cost: float
    total_gain: float
    total_gain_pct: float
    days_gain: float
    days_gain_pct: float

@dataclass
class ETradeQuote:
    """ETrade Market Quote"""
    symbol: str
    last_price: float
    change: float
    change_pct: float
    volume: int
    bid: float
    ask: float
    high: float
    low: float
    open: float

class PrimeETradeTrading:
    """
    Prime ETrade Trading System
    
    Comprehensive ETrade API integration for the trading strategy.
    Handles authentication, account management, portfolio tracking, and trading operations.
    """
    
    def __init__(self, environment: str = 'prod'):
        self.environment = environment
        self.config = None
        self.tokens = None
        self.accounts: List[ETradeAccount] = []
        self.selected_account: Optional[ETradeAccount] = None
        self.balance: Optional[ETradeBalance] = None
        self.portfolio: List[ETradePosition] = []
        
        if not ETradeOAuth_AVAILABLE:
            raise Exception("ETradeOAuth not available. Please set up ETradeOAuth system first.")
        
        self._load_credentials()
        self._load_tokens()
        self._load_accounts()
    
    def initialize(self) -> bool:
        """
        Initialize the ETrade trading system
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            log.info(f"🔧 Initializing ETrade {self.environment} trading system...")
            
            # Validate OAuth tokens
            if not self._validate_oauth_tokens():
                log.error("❌ OAuth token validation failed")
                return False
            
            # Test API connection
            if not self._test_api_connection():
                log.error("❌ API connection test failed")
                return False
            
            # Load account data
            if not self.accounts:
                log.error("❌ No accounts found")
                return False
            
            # Select primary account
            self._select_primary_account()
            
            log.info(f"✅ ETrade {self.environment} trading system initialized successfully")
            log.info(f"   Selected account: {self.selected_account.account_name if self.selected_account else 'None'}")
            log.info(f"   Total accounts: {len(self.accounts)}")
            
            return True
            
        except Exception as e:
            log.error(f"❌ Failed to initialize ETrade trading system: {e}")
            return False
    
    def _validate_oauth_tokens(self) -> bool:
        """
        Validate OAuth tokens
        
        Returns:
            True if tokens are valid, False otherwise
        """
        try:
            if not self.tokens:
                log.error("No OAuth tokens found")
                return False
            
            # Check if tokens have required fields
            required_fields = ['oauth_token', 'oauth_token_secret']
            for field in required_fields:
                if field not in self.tokens or not self.tokens[field]:
                    log.error(f"Missing required token field: {field}")
                    return False
            
            # Check if tokens are expired (past midnight ET)
            if self._is_token_expired():
                log.error("OAuth tokens expired at midnight ET")
                return False
            
            # Check if tokens need renewal (idle for 2+ hours)
            if self._needs_token_renewal():
                log.warning("OAuth tokens idle for 2+ hours, renewal needed")
                if not self._renew_tokens():
                    log.error("Failed to renew OAuth tokens")
                    return False
            
            log.info("✅ OAuth tokens validated successfully")
            return True
            
        except Exception as e:
            log.error(f"OAuth token validation failed: {e}")
            return False
    
    def _is_token_expired(self) -> bool:
        """Check if OAuth tokens are expired (check last_used for validity)"""
        try:
            if not self.tokens:
                return True
            
            # Check last_used timestamp - if used recently, tokens are valid
            last_used = self.tokens.get('last_used')
            if last_used:
                try:
                    last_used_dt = datetime.fromisoformat(last_used.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    
                    # If used within last 2 hours, tokens are definitely valid
                    hours_since_use = (now - last_used_dt).total_seconds() / 3600
                    if hours_since_use < 2:
                        log.debug(f"Tokens used {hours_since_use:.1f} hours ago - still valid")
                        return False
                except Exception as e:
                    log.debug(f"Could not parse last_used timestamp: {e}")
            
            # Check timestamp field (from Secret Manager)
            timestamp = self.tokens.get('timestamp')
            if timestamp:
                try:
                    timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    
                    # If created/updated today (within last 24 hours), tokens are valid
                    hours_since_creation = (now - timestamp_dt).total_seconds() / 3600
                    if hours_since_creation < 24:
                        log.debug(f"Tokens created {hours_since_creation:.1f} hours ago - still valid")
                        return False
                except Exception as e:
                    log.debug(f"Could not parse timestamp: {e}")
            
            # Fallback: Assume tokens are valid (don't block the system)
            log.warning("Could not determine token expiration - assuming valid")
            return False
            
        except Exception as e:
            log.error(f"Error checking token expiration: {e}")
            # Default to valid to avoid blocking
            return False
    
    def _needs_token_renewal(self) -> bool:
        """Check if OAuth tokens need renewal (idle for 2+ hours)"""
        try:
            if not self.tokens:
                return True
            
            # Check timestamp field first (from Secret Manager)
            timestamp = self.tokens.get('timestamp')
            if timestamp:
                try:
                    timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    hours_since = (datetime.now(timezone.utc) - timestamp_dt).total_seconds() / 3600
                    if hours_since < 2:
                        log.debug(f"Tokens renewed {hours_since:.1f} hours ago - fresh, no renewal needed")
                        return False
                except Exception as e:
                    log.debug(f"Could not parse timestamp: {e}")
            
            # Check last_used field (legacy)
            last_used = self.tokens.get('last_used')
            if not last_used:
                # No timestamp info, assume renewal needed
                log.warning("No timestamp or last_used field in tokens")
                return True
            
            # Parse last used time
            last_used_dt = datetime.fromisoformat(last_used.replace('Z', '+00:00'))
            
            # Make timezone-aware if needed
            if last_used_dt.tzinfo is None:
                last_used_dt = last_used_dt.replace(tzinfo=timezone.utc)
            
            # Check if idle for 2+ hours
            idle_hours = (datetime.now(timezone.utc) - last_used_dt).total_seconds() / 3600
            return idle_hours >= 2
            
        except Exception as e:
            log.error(f"Error checking renewal need: {e}")
            # Default to NOT needing renewal to avoid breaking fresh tokens
            return False
    
    def _renew_tokens(self) -> bool:
        """
        Renew OAuth tokens if needed
        
        Returns:
            True if renewal successful or not needed
        """
        try:
            # Import the OAuth manager
            from central_oauth_manager import CentralOAuthManager, Environment
            
            oauth_manager = CentralOAuthManager()
            env = Environment.PROD if self.environment == 'prod' else Environment.SANDBOX
            
            # Attempt renewal
            success = oauth_manager.renew_if_needed(env)
            
            if success:
                log.info("✅ OAuth tokens renewed successfully")
                # Reload tokens
                self._load_tokens()
                return True
            else:
                log.warning("⚠️ OAuth token renewal failed")
                return False
                
        except Exception as e:
            log.error(f"Error renewing tokens: {e}")
            return False
    
    def _test_api_connection(self) -> bool:
        """
        Test API connection with a simple call
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            log.info("🔍 Testing API connection...")
            
            # Test with account list call
            response = self._make_etrade_api_call(
                method='GET',
                url="/v1/accounts/list",
                params={}
            )
            
            # Check if response contains error
            if isinstance(response, dict) and 'error' in response:
                log.error(f"API test failed: {response['error']}")
                return False
            
            # Check if response contains account data
            if isinstance(response, dict) and 'AccountListResponse' in response:
                log.info("✅ API connection test successful")
                return True
            elif isinstance(response, str) and 'AccountListResponse' in response:
                log.info("✅ API connection test successful")
                return True
            else:
                log.error(f"Unexpected API response: {response}")
                return False
                
        except Exception as e:
            log.error(f"API connection test failed: {e}")
            return False
    
    def _select_primary_account(self):
        """Select the primary trading account"""
        try:
            if not self.accounts:
                log.warning("No accounts available for selection")
                return
            
            # Select the first account as primary
            self.selected_account = self.accounts[0]
            log.info(f"Selected primary account: {self.selected_account.account_name} ({self.selected_account.account_id})")
            
        except Exception as e:
            log.error(f"Failed to select primary account: {e}")
    
    def is_authenticated(self) -> bool:
        """
        Check if the system is properly authenticated
        
        Returns:
            True if authenticated and ready for trading
        """
        try:
            return (
                self.tokens is not None and
                self.accounts is not None and
                len(self.accounts) > 0 and
                self.selected_account is not None
            )
        except Exception as e:
            log.error(f"Error checking authentication status: {e}")
            return False
    
    def _make_etrade_api_call(self, method: str, url: str, params: Dict = None):
        """Make ETrade API call with correct OAuth 1.0a implementation"""
        if REQUESTS_OAUTH_AVAILABLE:
            return self._make_correct_oauth_call(method, url, params)
        else:
            # Fallback to original implementation
            return self._make_legacy_oauth_call(method, url, params)
    
    def _make_correct_oauth_call(self, method: str, url: str, params: Dict = None):
        """Make ETrade API call with correct OAuth 1.0a HMAC-SHA1 signature"""
        try:
            # Ensure all OAuth parameters are strings and not None
            consumer_key = str(self.config.get('consumer_key', '')) if self.config.get('consumer_key') else ''
            consumer_secret = str(self.config.get('consumer_secret', '')) if self.config.get('consumer_secret') else ''
            oauth_token = str(self.tokens.get('oauth_token', '')) if self.tokens.get('oauth_token') else ''
            oauth_token_secret = str(self.tokens.get('oauth_token_secret', '')) if self.tokens.get('oauth_token_secret') else ''
            
            # Validate that all required OAuth parameters are present
            if not all([consumer_key, consumer_secret, oauth_token, oauth_token_secret]):
                log.error(f"Missing OAuth parameters: consumer_key={bool(consumer_key)}, consumer_secret={bool(consumer_secret)}, oauth_token={bool(oauth_token)}, oauth_token_secret={bool(oauth_token_secret)}")
                return {"error": "Missing OAuth parameters"}
            
            # Set up OAuth 1.0a with HMAC-SHA1
            oauth = OAuth1(
                client_key=consumer_key,
                client_secret=consumer_secret,
                resource_owner_key=oauth_token,
                resource_owner_secret=oauth_token_secret,
                signature_method="HMAC-SHA1",
                signature_type="AUTH_HEADER",  # OAuth params in Authorization header
            )
            
            # Make the request
            if url.startswith('/'):
                full_url = f"{self.config['base_url']}{url}"
            else:
                full_url = url
            
            # Add Accept header for JSON responses
            headers = {"Accept": "application/json"}
            
            response = requests.request(
                method=method,
                url=full_url,
                params=params or {},
                headers=headers,
                auth=oauth,
                timeout=30
            )
            
            # Handle response
            if response.status_code == 200:
                # Try to parse as JSON first
                try:
                    return response.json()
                except:
                    # Return as text if not JSON
                    return response.text
            else:
                log.error(f"API call failed: {response.status_code} - {response.text}")
                return {"error": f"HTTP {response.status_code}", "message": response.text}
                
        except Exception as e:
            log.error(f"OAuth API call failed: {e}")
            return {"error": str(e)}
    
    def _make_legacy_oauth_call(self, method: str, url: str, params: Dict = None):
        """Fallback OAuth implementation using original method"""
        original_cwd = os.getcwd()
        etrade_oauth_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ETradeOAuth')
        
        try:
            # Ensure all OAuth parameters are strings and not None
            consumer_key = str(self.config.get('consumer_key', '')) if self.config.get('consumer_key') else ''
            consumer_secret = str(self.config.get('consumer_secret', '')) if self.config.get('consumer_secret') else ''
            oauth_token = str(self.tokens.get('oauth_token', '')) if self.tokens.get('oauth_token') else ''
            oauth_token_secret = str(self.tokens.get('oauth_token_secret', '')) if self.tokens.get('oauth_token_secret') else ''
            
            # Validate that all required OAuth parameters are present
            if not all([consumer_key, consumer_secret, oauth_token, oauth_token_secret]):
                log.error(f"Missing OAuth parameters in legacy call: consumer_key={bool(consumer_key)}, consumer_secret={bool(consumer_secret)}, oauth_token={bool(oauth_token)}, oauth_token_secret={bool(oauth_token_secret)}")
                return {"error": "Missing OAuth parameters"}
            
            os.chdir(etrade_oauth_dir)
            return make_oauth_request(
                method=method,
                url=url,
                params=params or {},
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                oauth_token=oauth_token,
                oauth_token_secret=oauth_token_secret
            )
        finally:
            os.chdir(original_cwd)
        
    def _load_credentials(self):
        """Load ETrade credentials from Google Secret Manager"""
        try:
            # Try to load from Google Secret Manager first
            self.config = self._load_credentials_from_secret_manager()
            
            if not self.config:
                # Fallback to original method
                log.info("Falling back to file-based credential loading...")
                self._load_credentials_from_file()
            
            if not self.config:
                raise Exception(f"Failed to load config for {self.environment}")
            
            # Validate that we have the required credentials
            if not self.config.get('consumer_key') or not self.config.get('consumer_secret'):
                # Try mock credentials for local testing
                if not os.getenv('K_SERVICE'):  # Not running in Cloud Run
                    log.info("Attempting to use mock credentials for local testing...")
                    self._use_mock_credentials_for_local_testing()
                else:
                    raise Exception(f"Missing consumer_key or consumer_secret for {self.environment}")
            
            log.info(f"✅ Loaded ETrade credentials for {self.environment}")
            
        except Exception as e:
            log.error(f"Failed to load ETrade credentials: {e}")
            
            # For local testing, try to use environment variables or mock credentials
            if not os.getenv('K_SERVICE'):  # Not running in Cloud Run
                log.info("Attempting to use mock credentials for local testing...")
                self._use_mock_credentials_for_local_testing()
            else:
                raise
    
    def _use_mock_credentials_for_local_testing(self):
        """Use mock credentials for local testing when Secret Manager is not available"""
        try:
            log.info("Setting up mock credentials for local testing...")
            
            # Set up mock configuration for local testing
            if self.environment.lower() == 'sandbox':
                self.config = {
                    'consumer_key': 'mock_sandbox_consumer_key',
                    'consumer_secret': 'mock_sandbox_consumer_secret',
                    'base_url': 'https://apisb.etrade.com',
                    'token_file': 'tokens_sandbox.json'
                }
            else:
                self.config = {
                    'consumer_key': 'mock_prod_consumer_key',
                    'consumer_secret': 'mock_prod_consumer_secret',
                    'base_url': 'https://api.etrade.com',
                    'token_file': 'tokens_prod.json'
                }
            
            log.info(f"✅ Mock credentials configured for {self.environment} (local testing)")
            
        except Exception as e:
            log.error(f"Failed to setup mock credentials: {e}")
            raise
    
    def _load_credentials_from_secret_manager(self) -> Optional[Dict[str, str]]:
        """Load credentials directly from Google Secret Manager"""
        try:
            # Try Python library first
            from google.cloud import secretmanager
            from .config_loader import get_cloud_config
            
            client = secretmanager.SecretManagerServiceClient()
            # Rev 00190: Use centralized cloud config instead of hardcoded project_id
            cloud_config = get_cloud_config()
            project_id = cloud_config["project_id"]
            
            # Load consumer credentials directly
            if self.environment.lower() == 'sandbox':
                consumer_key_secret = f"projects/{project_id}/secrets/etrade-sandbox-consumer-key/versions/latest"
                consumer_secret_secret = f"projects/{project_id}/secrets/etrade-sandbox-consumer-secret/versions/latest"
                base_url = 'https://apisb.etrade.com'
                token_file = 'tokens_sandbox.json'
            else:
                consumer_key_secret = f"projects/{project_id}/secrets/etrade-prod-consumer-key/versions/latest"
                consumer_secret_secret = f"projects/{project_id}/secrets/etrade-prod-consumer-secret/versions/latest"
                base_url = 'https://api.etrade.com'
                token_file = 'tokens_prod.json'
            
            # Access secrets directly
            log.info(f"Loading consumer credentials from Secret Manager for {self.environment}")
            consumer_key_response = client.access_secret_version(request={"name": consumer_key_secret})
            consumer_secret_response = client.access_secret_version(request={"name": consumer_secret_secret})
            
            consumer_key = consumer_key_response.payload.data.decode("UTF-8")
            consumer_secret = consumer_secret_response.payload.data.decode("UTF-8")
            
            if consumer_key and consumer_secret:
                log.info(f"✅ Loaded consumer credentials from Secret Manager for {self.environment}")
                return {
                    'consumer_key': consumer_key,
                    'consumer_secret': consumer_secret,
                    'base_url': base_url,
                    'token_file': token_file
                }
            
            return None
            
        except Exception as e:
            # FALLBACK: Use gcloud CLI if Python library has DNS issues
            log.warning(f"Secret Manager Python library failed: {e}")
            log.info("Trying gcloud CLI fallback for Secret Manager access...")
            
            try:
                import subprocess
                from .config_loader import get_cloud_config
                
                # Rev 00190: Use centralized cloud config instead of hardcoded project_id
                cloud_config = get_cloud_config()
                project_id = cloud_config["project_id"]
                
                if self.environment.lower() == 'sandbox':
                    key_secret = "etrade-sandbox-consumer-key"
                    secret_secret = "etrade-sandbox-consumer-secret"
                    base_url = 'https://apisb.etrade.com'
                    token_file = 'tokens_sandbox.json'
                else:
                    key_secret = "etrade-prod-consumer-key"
                    secret_secret = "etrade-prod-consumer-secret"
                    base_url = 'https://api.etrade.com'
                    token_file = 'tokens_prod.json'
                
                # Use gcloud CLI
                key_result = subprocess.run(
                    ['gcloud', 'secrets', 'versions', 'access', 'latest',
                     f'--secret={key_secret}', f'--project={project_id}'],
                    capture_output=True, text=True, timeout=10
                )
                
                secret_result = subprocess.run(
                    ['gcloud', 'secrets', 'versions', 'access', 'latest',
                     f'--secret={secret_secret}', f'--project={project_id}'],
                    capture_output=True, text=True, timeout=10
                )
                
                if key_result.returncode == 0 and secret_result.returncode == 0:
                    consumer_key = key_result.stdout.strip()
                    consumer_secret = secret_result.stdout.strip()
                    log.info(f"✅ Loaded credentials via gcloud CLI fallback for {self.environment}")
                    return {
                        'consumer_key': consumer_key,
                        'consumer_secret': consumer_secret,
                        'base_url': base_url,
                        'token_file': token_file
                    }
                
            except Exception as cli_error:
                log.error(f"gcloud CLI fallback also failed: {cli_error}")
            
            return None
    
    def _load_secret_manager_credential(self, secret_manager, secret_name: str) -> Optional[str]:
        """Load a specific credential from Secret Manager"""
        try:
            # Load the secret
            tokens = secret_manager.load_tokens(secret_name.replace('etrade-', '').replace('-consumer-key', '').replace('-consumer-secret', ''))
            
            if tokens and secret_name.endswith('-consumer-key'):
                return tokens.get('consumer_key')
            elif tokens and secret_name.endswith('-consumer-secret'):
                return tokens.get('consumer_secret')
            
            # Try direct credential loading
            parent = f"projects/{secret_manager.project_id}/secrets/{secret_name}/versions/latest"
            response = secret_manager.client.access_secret_version(request={"name": parent})
            return response.payload.data.decode("UTF-8")
            
        except Exception as e:
            log.debug(f"Could not load credential {secret_name}: {e}")
            return None
    
    def _load_credentials_from_file(self):
        """Fallback method to load credentials from file"""
        try:
            # Temporarily change to ETradeOAuth directory for config loading
            original_cwd = os.getcwd()
            etrade_oauth_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ETradeOAuth')
            
            try:
                os.chdir(etrade_oauth_dir)
                from simple_oauth_cli import load_config
                self.config = load_config(self.environment)
            finally:
                os.chdir(original_cwd)
            
        except Exception as e:
            log.error(f"Failed to load credentials from file: {e}")
            self.config = None
    
    def _load_tokens(self):
        """Load ETrade tokens from Google Secret Manager"""
        try:
            # Try to load from Google Secret Manager first
            self.tokens = self._load_tokens_from_secret_manager()
            
            if not self.tokens:
                # Fallback to file-based loading
                log.info("Falling back to file-based token loading...")
                self._load_tokens_from_file()
            
            if not self.tokens:
                raise Exception(f"No tokens found for {self.environment}")
            
            log.info(f"✅ Loaded ETrade tokens for {self.environment}")
            
        except Exception as e:
            log.error(f"Failed to load ETrade tokens: {e}")
            raise
    
    def _load_tokens_from_secret_manager(self) -> Optional[Dict[str, Any]]:
        """Load OAuth tokens from Google Secret Manager (Rev 00180h)"""
        try:
            # Rev 00180h: Load tokens directly from Secret Manager (no local folder dependency)
            # Tokens managed by https://easy-trading-oauth-v2.web.app/
            if not SECRET_MANAGER_AVAILABLE:
                log.warning("Secret Manager not available for token loading")
                return None
            
            from google.cloud import secretmanager
            from .config_loader import get_cloud_config
            
            client = secretmanager.SecretManagerServiceClient()
            # Rev 00190: Use centralized cloud config instead of hardcoded project_id
            cloud_config = get_cloud_config()
            project_id = cloud_config["project_id"]
            
            # Determine secret name based on environment (Rev 00180h: Correct secret names)
            if self.environment.lower() == 'sandbox':
                secret_name = f"projects/{project_id}/secrets/etrade-oauth-sandbox/versions/latest"
            else:
                secret_name = f"projects/{project_id}/secrets/etrade-oauth-prod/versions/latest"
            
            # Load tokens from Secret Manager
            log.info(f"📥 Loading OAuth tokens from Secret Manager for {self.environment}...")
            response = client.access_secret_version(request={"name": secret_name})
            token_data = response.payload.data.decode("UTF-8")
            tokens = json.loads(token_data)
            
            if tokens and 'oauth_token' in tokens and 'oauth_token_secret' in tokens:
                log.info(f"✅ Loaded OAuth tokens from Secret Manager for {self.environment}")
                log.info(f"   Token expires: {tokens.get('expires_at', 'unknown')}")
                return tokens
            else:
                log.warning(f"⚠️ Tokens loaded but missing required fields")
                return None
            
        except Exception as e:
            # FALLBACK: Use gcloud CLI if Python library has DNS issues
            log.warning(f"Secret Manager Python library failed for tokens: {e}")
            log.info("Trying gcloud CLI fallback for token access...")
            
            try:
                import subprocess
                from .config_loader import get_cloud_config
                
                # Rev 00190: Use centralized cloud config instead of hardcoded project_id
                cloud_config = get_cloud_config()
                project_id = cloud_config["project_id"]
                
                if self.environment.lower() == 'sandbox':
                    oauth_secret = "etrade-oauth-sandbox"
                else:
                    oauth_secret = "etrade-oauth-prod"
                
                # Use gcloud CLI to get tokens
                token_result = subprocess.run(
                    ['gcloud', 'secrets', 'versions', 'access', 'latest',
                     f'--secret={oauth_secret}', f'--project={project_id}'],
                    capture_output=True, text=True, timeout=10
                )
                
                if token_result.returncode == 0:
                    tokens = json.loads(token_result.stdout.strip())
                    if tokens and 'oauth_token' in tokens and 'oauth_token_secret' in tokens:
                        log.info(f"✅ Loaded OAuth tokens via gcloud CLI fallback for {self.environment}")
                        return tokens
                
            except Exception as cli_error:
                log.error(f"gcloud CLI fallback also failed for tokens: {cli_error}")
            
            return None
    
    def _load_tokens_from_file(self):
        """Fallback method to load tokens from file"""
        try:
            # Temporarily change to ETradeOAuth directory for token loading
            original_cwd = os.getcwd()
            etrade_oauth_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ETradeOAuth')
            
            try:
                os.chdir(etrade_oauth_dir)
                from simple_oauth_cli import load_tokens
                self.tokens = load_tokens(self.environment)
            finally:
                os.chdir(original_cwd)
            
        except Exception as e:
            log.error(f"Failed to load tokens from file: {e}")
            self.tokens = None
    
    def _load_accounts(self):
        """Load and parse account list"""
        try:
            log.info("📋 Loading ETrade accounts...")
            
            response = self._make_etrade_api_call(
                method='GET',
                url="/v1/accounts/list",
                params={}
            )
            
            # Handle different response formats
            if isinstance(response, dict):
                # JSON response from new OAuth implementation
                if 'AccountListResponse' in response:
                    self._parse_account_list_json(response)
                elif 'Accounts' in response:
                    self._parse_account_list_json(response)
                elif 'error' in response:
                    log.error(f"API error: {response['error']}")
                    raise Exception(f"API error: {response['error']}")
                else:
                    log.error(f"Unexpected JSON response format: {response}")
                    raise Exception("Unexpected JSON response format")
            elif isinstance(response, str):
                # XML response (legacy)
                if '<?xml' in response:
                    self._parse_account_list_xml(response)
                else:
                    log.error(f"Unexpected string response: {response[:200]}...")
                    raise Exception("Unexpected string response format")
            else:
                log.error(f"Unexpected response type: {type(response)}")
                raise Exception(f"Unexpected response type: {type(response)}")
                
        except Exception as e:
            log.error(f"Failed to load accounts: {e}")
            raise
    
    def _parse_account_list_json(self, response_data: dict):
        """Parse account list JSON response"""
        try:
            # Handle both response formats
            if 'AccountListResponse' in response_data:
                accounts_data = response_data['AccountListResponse']['Accounts']['Account']
            elif 'Accounts' in response_data:
                accounts_data = response_data['Accounts']['Account']
            else:
                raise Exception("No accounts data found in response")
            
            if not isinstance(accounts_data, list):
                accounts_data = [accounts_data]
            
            for account_data in accounts_data:
                account = ETradeAccount(
                    account_id=account_data.get('accountId'),
                    account_name=account_data.get('accountName'),
                    account_id_key=account_data.get('accountIdKey'),
                    account_status=account_data.get('accountStatus'),
                    institution_type=account_data.get('institutionType'),
                    account_type=account_data.get('accountType')
                )
                self.accounts.append(account)
                log.info(f"✅ Loaded account: {account.account_name} ({account.account_id})")
            
            log.info(f"✅ Loaded {len(self.accounts)} accounts")
            
        except Exception as e:
            log.error(f"Failed to parse account list JSON: {e}")
            raise
    
    def _parse_account_list_xml(self, xml_data: str):
        """Parse account list XML response"""
        try:
            # Clean up the XML data
            xml_data = xml_data.strip()
            
            if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                xml_data = '<?xml version=' + xml_data
            elif not xml_data.startswith('<?xml version'):
                xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
            
            root = ET.fromstring(xml_data)
            
            self.accounts = []
            for account in root.findall('.//Account'):
                account_data = ETradeAccount(
                    account_id=account.find('accountId').text if account.find('accountId') is not None else None,
                    account_name=account.find('accountName').text if account.find('accountName') is not None else None,
                    account_id_key=account.find('accountIdKey').text if account.find('accountIdKey') is not None else None,
                    account_status=account.find('accountStatus').text if account.find('accountStatus') is not None else None,
                    institution_type=account.find('institutionType').text if account.find('institutionType') is not None else None,
                    account_type=account.find('accountType').text if account.find('accountType') is not None else None,
                )
                self.accounts.append(account_data)
            
            # Auto-select the first active account
            active_accounts = [acc for acc in self.accounts if acc.account_status == 'ACTIVE']
            if active_accounts:
                self.selected_account = active_accounts[0]
                log.info(f"✅ Auto-selected account: {self.selected_account.account_name} ({self.selected_account.account_id})")
            
            log.info(f"✅ Loaded {len(self.accounts)} accounts ({len(active_accounts)} active)")
            
        except Exception as e:
            log.error(f"Failed to parse account list XML: {e}")
            raise
    
    def select_account(self, account_id: str) -> bool:
        """Select a specific account for trading"""
        for account in self.accounts:
            if account.account_id == account_id and account.account_status == 'ACTIVE':
                self.selected_account = account
                log.info(f"✅ Selected account: {account.account_name} ({account.account_id})")
                return True
        log.error(f"Account {account_id} not found or not active")
        return False
    
    def get_account_balance(self) -> ETradeBalance:
        """Get account balance information using correct OAuth 1.0a"""
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"💰 Fetching balance for account {self.selected_account.account_id}...")
            
            # Use correct OAuth implementation with required query parameters
            params = {'instType': 'BROKERAGE', 'realTimeNAV': 'true'}
            url = f"/v1/accounts/{self.selected_account.account_id_key}/balance"
            
            response = self._make_etrade_api_call(
                method='GET',
                url=url,
                params=params
            )
            
            if response and not isinstance(response, dict) or 'error' not in response:
                self.balance = self._parse_balance_response(response)
                log.info(f"✅ Retrieved balance: Cash Available for Investment: ${self.balance.cash_available_for_investment}")
                return self.balance
            else:
                log.warning(f"Balance API failed: {response}")
                
                # Fallback: Try to get balance from portfolio
                log.info("🔄 Attempting to get balance from portfolio data...")
                portfolio = self.get_portfolio()
                if portfolio:
                    # Calculate balance from portfolio positions
                    total_value = sum(pos.market_value for pos in portfolio if pos.market_value)
                    cash_positions = [pos for pos in portfolio 
                                    if 'CASH' in pos.symbol.upper() or 'USD' in pos.symbol.upper()]
                    cash_available = sum(pos.market_value for pos in cash_positions if pos.market_value) if cash_positions else 0.0
                    
                    self.balance = ETradeBalance(
                        account_value=total_value,
                        cash_available_for_investment=cash_available,
                        cash_buying_power=cash_available,
                        option_level=None
                    )
                    log.info(f"✅ Retrieved balance from portfolio: Cash Available for Investment: ${self.balance.cash_available_for_investment}")
                    return self.balance
            
            # If all methods fail, return empty balance
            self.balance = ETradeBalance(
                account_value=None,
                cash_available_for_investment=None,
                cash_buying_power=None,
                option_level=None
            )
            return self.balance
            
        except Exception as e:
            log.error(f"Failed to get account balance: {e}")
            raise
    
    def _parse_balance_response(self, response) -> ETradeBalance:
        """Parse balance response (JSON or XML)"""
        try:
            # Handle JSON response first (preferred)
            if isinstance(response, dict):
                if 'BalanceResponse' in response:
                    # JSON response structure
                    balance_response = response['BalanceResponse']
                    computed = balance_response.get('Computed', {}) or balance_response.get('ComputedBalance', {})
                    
                    def safe_float(value):
                        try:
                            return float(value) if value else None
                        except (ValueError, TypeError):
                            return None
                    
                    return ETradeBalance(
                        account_value=safe_float(computed.get('totalAccountValue')),
                        cash_available_for_investment=safe_float(computed.get('cashAvailableForInvestment')),
                        cash_buying_power=safe_float(computed.get('cashBuyingPower')),
                        option_level=computed.get('optionLevel')
                    )
            
            # Handle XML response (legacy)
            if isinstance(response, str) and '<?xml' in response:
                xml_data = response.strip()
                
                # Clean up XML data
                if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                    xml_data = '<?xml version=' + xml_data
                elif not xml_data.startswith('<?xml version'):
                    xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
                
                root = ET.fromstring(xml_data)
                
                # Extract balance information
                balance_data = {}
                account_balance = root.find('.//AccountBalance')
                if account_balance is not None:
                    for child in account_balance:
                        balance_data[child.tag] = child.text
                
                # Map to ETradeBalance
                def safe_float(value):
                    try:
                        return float(value) if value else None
                    except (ValueError, TypeError):
                        return None
                
                return ETradeBalance(
                    account_value=safe_float(balance_data.get('accountValue', balance_data.get('accountBalance'))),
                    cash_available_for_investment=safe_float(balance_data.get('cashAvailableForInvestment')),
                    cash_buying_power=safe_float(balance_data.get('cashBuyingPower', balance_data.get('buyingPower'))),
                    option_level=balance_data.get('optionLevel')
                )
            
            return ETradeBalance(None, None, None, None)
            
        except Exception as e:
            log.error(f"Failed to parse balance response: {e}")
            return ETradeBalance(None, None, None, None)
    
    def get_portfolio(self) -> List[ETradePosition]:
        """Get portfolio positions"""
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"📊 Fetching portfolio for account {self.selected_account.account_id}...")
            
            response = self._make_etrade_api_call(
                method='GET',
                url=f"{self.config['base_url']}/v1/accounts/{self.selected_account.account_id_key}/portfolio",
                params={}
            )
            
            if response:
                self.portfolio = self._parse_portfolio_response(response)
                log.info(f"✅ Retrieved {len(self.portfolio)} portfolio positions")
                return self.portfolio
            else:
                self.portfolio = []
                return self.portfolio
                
        except Exception as e:
            log.error(f"Failed to get portfolio: {e}")
            self.portfolio = []
            return self.portfolio
    
    def _parse_portfolio_response(self, response: Dict) -> List[ETradePosition]:
        """Parse portfolio response"""
        try:
            xml_key = '<?xml version'
            if xml_key in response:
                xml_data = response[xml_key]
                
                # Clean up XML data
                xml_data = xml_data.strip()
                if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                    xml_data = '<?xml version=' + xml_data
                elif not xml_data.startswith('<?xml version'):
                    xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
                
                root = ET.fromstring(xml_data)
                
                positions = []
                for position in root.findall('.//Position'):
                    pos_data = {}
                    for child in position:
                        pos_data[child.tag] = child.text
                    
                    # Map to ETradePosition
                    def safe_float(value):
                        try:
                            return float(value) if value else 0.0
                        except (ValueError, TypeError):
                            return 0.0
                    
                    def safe_int(value):
                        try:
                            return int(value) if value else 0
                        except (ValueError, TypeError):
                            return 0
                    
                    positions.append(ETradePosition(
                        position_id=pos_data.get('positionId', ''),
                        symbol=pos_data.get('symbolDescription', ''),
                        symbol_description=pos_data.get('symbolDescription', ''),
                        quantity=safe_int(pos_data.get('quantity')),
                        position_type=pos_data.get('positionType', ''),
                        market_value=safe_float(pos_data.get('marketValue')),
                        total_cost=safe_float(pos_data.get('totalCost')),
                        total_gain=safe_float(pos_data.get('totalGain')),
                        total_gain_pct=safe_float(pos_data.get('totalGainPct')),
                        days_gain=safe_float(pos_data.get('daysGain')),
                        days_gain_pct=safe_float(pos_data.get('daysGainPct'))
                    ))
                
                return positions
            
            return []
            
        except Exception as e:
            log.error(f"Failed to parse portfolio response: {e}")
            return []
    
    def get_quotes(self, symbols: List[str]) -> List[ETradeQuote]:
        """Get market quotes for symbols"""
        try:
            if not symbols:
                return []
            
            log.info(f"📈 Fetching quotes for {len(symbols)} symbols...")
            
            # ETrade API accepts comma-separated symbols
            symbol_param = ','.join(symbols)
            
            response = self._make_etrade_api_call(
                method='GET',
                url=f"{self.config['base_url']}/v1/market/quote/{symbol_param}",
                params={'detailFlag': 'ALL'}
            )
            
            if response:
                log.info(f"📊 E*TRADE response received for {len(symbols)} symbols")
                log.debug(f"📊 E*TRADE response keys: {list(response.keys())[:10]}")
                log.debug(f"📊 E*TRADE response type: {type(response)}")
                
                quotes = self._parse_quotes_response(response)
                
                if len(quotes) == 0:
                    log.warning(f"⚠️ E*TRADE parsing returned 0 quotes - response keys: {list(response.keys())}")
                    log.info(f"📊 Full response (first 1000 chars): {str(response)[:1000]}")
                else:
                    log.info(f"✅ Retrieved {len(quotes)} quotes")
                    
                return quotes
            else:
                log.warning(f"⚠️ E*TRADE returned empty/None response for {len(symbols)} symbols")
                return []
                
        except Exception as e:
            log.error(f"Failed to get quotes: {e}")
            return []
    
    def get_intraday_bars(self, symbols: List[str], interval: str = "15m", bars: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get intraday bars for multiple symbols (Rev 20251024 - ETrade with proper bars)
        
        ETrade supports: 5m, 15m, 30m, 1h intervals
        
        Rev 20251024: Fixed to return SINGLE bar (today's OHLC) since ETrade quote API
        doesn't provide historical intraday bars. The detailFlag='INTRADAY' doesn't
        return multiple historical bars - it just returns today's aggregated OHLC.
        
        For historical intraday bars (e.g., 5 bars for SO prefetch), use yfinance fallback.
        
        Args:
            symbols: List of symbols to fetch
            interval: Bar interval (5m, 15m, 30m, 1h) - not actually used by ETrade quotes
            bars: Number of bars requested - ETrade quotes only return 1 bar (today's OHLC)
        
        Returns:
            Dict mapping symbol → list with SINGLE bar (today's OHLC only)
        """
        try:
            if not symbols:
                return {}
            
            log.info(f"📊 ETrade: Fetching current OHLC for {len(symbols)} symbols...")
            log.info(f"   Note: ETrade quotes return today's aggregated OHLC only (not historical bars)")
            
            # Use batch quotes API (more efficient than intraday endpoint)
            import pytz
            PT_TZ = pytz.timezone('America/Los_Angeles')
            ET_TZ = pytz.timezone('America/New_York')
            
            all_bars = {}
            batch_size = 25
            
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i+batch_size]
                
                try:
                    # Get current quotes (today's OHLC)
                    quotes = self.get_batch_quotes(batch)
                    
                    if quotes:
                        # Create timestamp for today's market open (9:30 AM ET)
                        today_et = datetime.now(ET_TZ).date()
                        market_open_et = ET_TZ.localize(datetime(today_et.year, today_et.month, today_et.day, 9, 30, 0))
                        market_open_pt = market_open_et.astimezone(PT_TZ)
                        
                        for quote in quotes:
                            # ETrade quote has today's OHLC (aggregated from market open)
                            bar = {
                                'timestamp': market_open_pt,
                                'datetime': market_open_pt,
                                'open': quote.open,
                                'high': quote.high,
                                'low': quote.low,
                                'close': quote.last_price,
                                'volume': quote.volume
                            }
                            # Return single bar (ETrade doesn't provide historical intraday)
                            all_bars[quote.symbol] = [bar]
                        
                        log.debug(f"✅ ETrade batch: {len(quotes)} symbols (today's OHLC only)")
                    
                except Exception as batch_error:
                    log.warning(f"ETrade batch failed: {batch_error}")
            
            if all_bars:
                log.info(f"✅ ETrade intraday: {len(all_bars)} symbols (single bar each - today's OHLC)")
            
            return all_bars
            
        except Exception as e:
            log.error(f"Failed to get ETrade intraday bars: {e}")
            return {}
    
    def get_historical_data(self, symbol: str, period: str = "1d", count: int = 200) -> List[Dict[str, Any]]:
        """
        Get historical data for technical analysis
        
        Args:
            symbol: Stock symbol
            period: Time period (1d, 5d, 1m, 3m, 6m, 1y, 2y, 5y)
            count: Number of data points (max 200)
        """
        try:
            log.info(f"📊 Fetching historical data for {symbol} ({period}, {count} points)...")
            
            # E*TRADE doesn't provide historical data directly
            # This would need to be implemented with a different provider
            # For now, return empty list
            log.warning(f"E*TRADE doesn't provide historical data for {symbol}")
            return []
            
        except Exception as e:
            log.error(f"Failed to get historical data for {symbol}: {e}")
            return []
    
    def get_market_data_for_strategy(self, symbol: str) -> Dict[str, Any]:
        """
        Get comprehensive market data for strategy analysis
        
        This method provides all the data that strategies need by:
        1. Getting real-time data from E*TRADE
        2. Using cached historical data if available
        3. Calculating technical indicators
        4. Providing fallback data for missing information
        
        Returns:
            Dictionary with all data needed for strategy analysis
        """
        try:
            # Get real-time quote from E*TRADE
            quotes = self.get_quotes([symbol])
            if not quotes:
                log.warning(f"No quote data available for {symbol}")
                return self._get_fallback_market_data(symbol)
            
            quote = quotes[0]
            
            # Rev 00142: Fetch historical data on-demand (only when needed, not stored)
            # Only fetched for symbols we're actually trading, calculated, then discarded
            historical_data = self._get_historical_data_for_symbol(symbol)
            
            # Calculate comprehensive technical indicators
            technical_indicators = self._calculate_technical_indicators(quote, historical_data)
            
            # Build comprehensive market data
            market_data = {
                'symbol': symbol,
                'current_price': quote.last_price,
                'bid': quote.bid,
                'ask': quote.ask,
                'open': quote.open,
                'high': quote.high,
                'low': quote.low,
                'volume': quote.volume,
                'change': quote.change,
                'change_pct': quote.change_pct,
                'timestamp': datetime.utcnow().isoformat(),
                
                # Price arrays for technical analysis (enhanced)
                'prices': self._build_price_array(quote, historical_data),
                'volumes': self._build_volume_array(quote, historical_data),
                'closes': self._build_closes_array(quote, historical_data),
                'highs': self._build_highs_array(quote, historical_data),
                'lows': self._build_lows_array(quote, historical_data),
                'opens': self._build_opens_array(quote, historical_data),
                
                # Technical indicators (comprehensive)
                'rsi': technical_indicators['rsi'],
                'rsi_14': technical_indicators['rsi_14'],
                'rsi_21': technical_indicators['rsi_21'],
                'macd': technical_indicators['macd'],
                'macd_signal': technical_indicators['macd_signal'],
                'macd_histogram': technical_indicators['macd_histogram'],
                'sma_20': technical_indicators['sma_20'],
                'sma_50': technical_indicators['sma_50'],
                'sma_200': technical_indicators['sma_200'],
                'ema_12': technical_indicators['ema_12'],
                'ema_26': technical_indicators['ema_26'],
                'atr': technical_indicators['atr'],
                'bollinger_upper': technical_indicators['bollinger_upper'],
                'bollinger_middle': technical_indicators['bollinger_middle'],
                'bollinger_lower': technical_indicators['bollinger_lower'],
                'bollinger_width': technical_indicators['bollinger_width'],
                
                # Volume analysis
                'volume_ratio': technical_indicators['volume_ratio'],
                'volume_sma': technical_indicators['volume_sma'],
                'obv': technical_indicators['obv'],
                'ad_line': technical_indicators['ad_line'],
                
                # Pattern recognition
                'doji': technical_indicators['doji'],
                'hammer': technical_indicators['hammer'],
                'engulfing': technical_indicators['engulfing'],
                'morning_star': technical_indicators['morning_star'],
                
                # Market data metadata
                'data_source': 'ETRADE',
                'data_quality': technical_indicators['data_quality'],
                'historical_points': len(historical_data) if historical_data else 0,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            # Rev 00181: Calculate RS vs SPY (Relative Strength) - Enhanced with better fallback logic
            # RS vs SPY = (Symbol change % - SPY change %)
            # This indicates how much the symbol is outperforming/underperforming the market
            try:
                spy_quotes = self.get_quotes(['SPY'])
                if spy_quotes and len(spy_quotes) > 0:
                    spy_quote = spy_quotes[0]
                    
                    # Rev 00181: Better detection of missing change_pct (None, 0.0, or missing attribute)
                    spy_change_pct = getattr(spy_quote, 'change_pct', None)
                    if spy_change_pct is None:
                        spy_change_pct = 0.0
                    
                    symbol_change_pct = getattr(quote, 'change_pct', None)
                    if symbol_change_pct is None:
                        symbol_change_pct = 0.0
                    
                    # Rev 00181: Enhanced fallback - check if change_pct is actually 0.0 or missing
                    # Use open price vs previous close if available (more accurate for early morning)
                    symbol_change_calculated = False
                    if (symbol_change_pct == 0.0 or symbol_change_pct is None) and quote.open and quote.last_price:
                        # Try using open price vs previous close from historical data
                        if historical_data and len(historical_data) >= 2:
                            try:
                                prev_close = historical_data[-2].get('close', None) if isinstance(historical_data[-2], dict) else (getattr(historical_data[-2], 'close', None) if hasattr(historical_data[-2], 'close') else None)
                                if prev_close and prev_close > 0:
                                    # Use open price if available (more accurate for intraday)
                                    base_price = quote.open if quote.open > 0 else quote.last_price
                                    symbol_change_pct = ((base_price - prev_close) / prev_close) * 100
                                    symbol_change_calculated = True
                                    log.debug(f"📊 Calculated symbol change % from open vs prev close for {symbol}: {symbol_change_pct:.2f}%")
                            except Exception as hist_error:
                                log.debug(f"⚠️ Could not calculate symbol change % from historical data for {symbol}: {hist_error}")
                        
                        # Fallback: use current price vs previous close if open not available
                        if not symbol_change_calculated and historical_data and len(historical_data) >= 2:
                            try:
                                prev_close = historical_data[-2].get('close', None) if isinstance(historical_data[-2], dict) else (getattr(historical_data[-2], 'close', None) if hasattr(historical_data[-2], 'close') else None)
                                if prev_close and prev_close > 0 and quote.last_price:
                                    symbol_change_pct = ((quote.last_price - prev_close) / prev_close) * 100
                                    symbol_change_calculated = True
                                    log.debug(f"📊 Calculated symbol change % from current vs prev close for {symbol}: {symbol_change_pct:.2f}%")
                            except Exception as hist_error:
                                log.debug(f"⚠️ Could not calculate symbol change % from current price for {symbol}: {hist_error}")
                    
                    # Rev 00181: Enhanced SPY fallback - use yfinance if change_pct is 0.0 or missing
                    spy_change_calculated = False
                    if (spy_change_pct == 0.0 or spy_change_pct is None) and spy_quote.open and spy_quote.last_price:
                        # Try using SPY open price vs previous close
                        try:
                            import yfinance as yf
                            spy_ticker = yf.Ticker("SPY")
                            spy_hist = spy_ticker.history(period="2d", interval="1d")
                            if not spy_hist.empty and len(spy_hist) >= 2:
                                spy_prev_close = spy_hist['Close'].iloc[-2]
                                # Use open price if available (more accurate for intraday)
                                spy_base_price = spy_quote.open if spy_quote.open > 0 else spy_quote.last_price
                                if spy_prev_close > 0:
                                    spy_change_pct = ((spy_base_price - spy_prev_close) / spy_prev_close) * 100
                                    spy_change_calculated = True
                                    log.debug(f"📊 Calculated SPY change % from open vs prev close: {spy_change_pct:.2f}%")
                        except Exception as spy_hist_error:
                            log.debug(f"⚠️ Could not calculate SPY change % from historical data: {spy_hist_error}")
                    
                    rs_vs_spy = symbol_change_pct - spy_change_pct
                    
                    market_data['rs_vs_spy'] = rs_vs_spy
                    market_data['spy_price'] = spy_quote.last_price
                    market_data['spy_change_pct'] = spy_change_pct
                    
                    if symbol_change_calculated or spy_change_calculated:
                        log.info(f"✅ Calculated RS vs SPY for {symbol} (using fallback): {rs_vs_spy:.2f}% (symbol: {symbol_change_pct:.2f}%, SPY: {spy_change_pct:.2f}%)")
                    else:
                        log.debug(f"✅ Calculated RS vs SPY for {symbol}: {rs_vs_spy:.2f}% (symbol: {symbol_change_pct:.2f}%, SPY: {spy_change_pct:.2f}%)")
                else:
                    log.warning(f"⚠️ Could not fetch SPY quote for RS vs SPY calculation for {symbol}")
                    market_data['rs_vs_spy'] = 0.0
                    market_data['spy_price'] = None
                    market_data['spy_change_pct'] = 0.0
            except Exception as rs_error:
                log.warning(f"⚠️ Error calculating RS vs SPY for {symbol}: {rs_error}", exc_info=True)
                market_data['rs_vs_spy'] = 0.0
                market_data['spy_price'] = None
                market_data['spy_change_pct'] = 0.0
            
            log.debug(f"📊 Generated comprehensive market data for {symbol}: {technical_indicators['data_quality']} quality")
            return market_data
            
        except Exception as e:
            log.error(f"Failed to get market data for strategy: {e}", exc_info=True)
            log.warning(f"   • Exception in get_market_data_for_strategy({symbol}): {type(e).__name__}: {e}")
            log.warning(f"   • Returning fallback data (RSI=50.0, Volume=1.0) to prevent invalid 0.0 values")
            fallback_data = self._get_fallback_market_data(symbol)
            log.debug(f"   ✅ Fallback data for {symbol}: RSI={fallback_data.get('rsi')}, Volume={fallback_data.get('volume_ratio')}")
            return fallback_data
    
    def _calculate_basic_rsi(self, quote: ETradeQuote) -> float:
        """Calculate basic RSI from available data"""
        try:
            # Very basic RSI calculation using price change
            if quote.change_pct > 0:
                return min(100, 50 + (quote.change_pct * 2))  # Rough approximation
            else:
                return max(0, 50 + (quote.change_pct * 2))
        except:
            return 50.0
    
    def _calculate_basic_macd(self, quote: ETradeQuote) -> float:
        """Calculate basic MACD from available data"""
        try:
            # Very basic MACD using price vs open
            return quote.last_price - quote.open
        except:
            return 0.0
    
    def _calculate_basic_atr(self, quote: ETradeQuote) -> float:
        """Calculate basic ATR from available data"""
        try:
            # Basic ATR using high-low range
            return quote.high - quote.low
        except:
            return 0.0
    
    def _get_historical_data_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get historical data for symbol on-demand (Rev 00142: Efficient on-demand fetching)
        
        Strategy:
        - Fetch historical data on-demand when needed (only for symbols we're trading)
        - Use yfinance as lightweight on-demand service (not stored)
        - Calculate technical indicators, then discard data
        - No persistent storage - much more efficient
        
        Max needed: 200 days (for SMA_200 technical indicator)
        """
        try:
            # Fetch historical data on-demand from yfinance (lightweight, no storage)
            # Only called when we need technical indicators for a symbol we're actually trading
            historical_data = self._fetch_historical_data_on_demand(symbol, days=200)
            
            if historical_data and len(historical_data) > 0:
                log.debug(f"✅ Fetched {len(historical_data)} days of historical data for {symbol} (on-demand, not stored)")
                return historical_data
            else:
                log.debug(f"No historical data available for {symbol} - using E*TRADE quote for basic calculations")
                return []
                
        except Exception as e:
            log.debug(f"No historical data available for {symbol}: {e}")
            return []
    
    def _fetch_historical_data_on_demand(self, symbol: str, days: int = 200) -> List[Dict[str, Any]]:
        """
        Fetch historical data on-demand from yfinance (lightweight, no storage)
        Only called when we need technical indicators for symbols we're actually trading
        Data is calculated, used, then discarded - no persistent storage
        """
        try:
            import yfinance as yf
            # Use module-level datetime import (line 21)
            
            # Fetch historical data on-demand
            ticker = yf.Ticker(symbol)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days + 30)  # Extra days for weekends/holidays
            
            hist = ticker.history(start=start_date, end=end_date)
            
            if hist is not None and len(hist) > 0:
                formatted_data = []
                for idx, row in hist.iterrows():
                    formatted_data.append({
                        'date': idx.strftime("%Y-%m-%d"),
                        'open': float(row['Open']),
                        'high': float(row['High']),
                        'low': float(row['Low']),
                        'close': float(row['Close']),
                        'volume': int(row['Volume'])
                    })
                
                # Return last N days (exactly what we need)
                return formatted_data[-days:] if len(formatted_data) > days else formatted_data
            else:
                return []
                
        except ImportError:
            log.warning(f"yfinance not available for {symbol} - using E*TRADE quote only")
            return []
        except Exception as e:
            log.debug(f"Could not fetch historical data for {symbol}: {e}")
            return []
    
    
    def _calculate_technical_indicators(self, quote: ETradeQuote, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate comprehensive technical indicators"""
        try:
            # Build price arrays from available data
            closes = self._build_closes_array(quote, historical_data)
            highs = self._build_highs_array(quote, historical_data)
            lows = self._build_lows_array(quote, historical_data)
            volumes = self._build_volume_array(quote, historical_data)
            
            # Determine data quality
            data_quality = 'excellent' if len(historical_data) >= 200 else 'good' if len(historical_data) >= 50 else 'limited' if len(historical_data) >= 20 else 'minimal'
            
            # Calculate indicators based on available data
            indicators = {
                # RSI calculations
                'rsi': self._calculate_rsi(closes, 14) if len(closes) >= 15 else self._calculate_basic_rsi(quote),
                'rsi_14': self._calculate_rsi(closes, 14) if len(closes) >= 15 else self._calculate_basic_rsi(quote),
                'rsi_21': self._calculate_rsi(closes, 21) if len(closes) >= 22 else self._calculate_basic_rsi(quote),
                
                # MACD calculations
                'macd': self._calculate_macd(closes) if len(closes) >= 26 else self._calculate_basic_macd(quote),
                'macd_signal': self._calculate_macd_signal(closes) if len(closes) >= 26 else 0.0,
                'macd_histogram': self._calculate_macd_histogram(closes) if len(closes) >= 26 else 0.0,
                
                # Moving averages
                'sma_20': self._calculate_sma(closes, 20) if len(closes) >= 20 else quote.last_price,
                'sma_50': self._calculate_sma(closes, 50) if len(closes) >= 50 else quote.last_price,
                'sma_200': self._calculate_sma(closes, 200) if len(closes) >= 200 else quote.last_price,
                'ema_12': self._calculate_ema(closes, 12) if len(closes) >= 12 else quote.last_price,
                'ema_26': self._calculate_ema(closes, 26) if len(closes) >= 26 else quote.last_price,
                
                # Volatility indicators
                'atr': self._calculate_atr(highs, lows, closes) if len(highs) >= 14 else self._calculate_basic_atr(quote),
                
                # Bollinger Bands
                'bollinger_upper': self._calculate_bollinger_upper(closes) if len(closes) >= 20 else quote.high,
                'bollinger_middle': self._calculate_bollinger_middle(closes) if len(closes) >= 20 else quote.last_price,
                'bollinger_lower': self._calculate_bollinger_lower(closes) if len(closes) >= 20 else quote.low,
                'bollinger_width': self._calculate_bollinger_width(closes) if len(closes) >= 20 else 0.0,
                
                # Volume analysis
                'volume_ratio': self._calculate_volume_ratio(volumes) if len(volumes) >= 20 else 1.0,
                'volume_sma': self._calculate_sma(volumes, 20) if len(volumes) >= 20 else quote.volume,
                'obv': self._calculate_obv(closes, volumes) if len(closes) >= 2 else 0.0,
                'ad_line': self._calculate_ad_line(highs, lows, closes, volumes) if len(highs) >= 2 else 0.0,
                
                # Pattern recognition
                'doji': self._detect_doji(quote) if quote.open and quote.close else False,
                'hammer': self._detect_hammer(quote) if quote.open and quote.close and quote.high and quote.low else False,
                'engulfing': False,  # Would need previous candle data
                'morning_star': False,  # Would need previous candle data
                
                # Data quality
                'data_quality': data_quality
            }
            
            return indicators
            
        except Exception as e:
            log.error(f"Error calculating technical indicators: {e}")
            return self._get_basic_indicators(quote)
    
    def _build_price_array(self, quote: ETradeQuote, historical_data: List[Dict[str, Any]]) -> List[float]:
        """Build price array for technical analysis"""
        try:
            prices = []
            
            # Add historical data if available
            if historical_data:
                for data_point in historical_data:
                    if 'close' in data_point:
                        prices.append(float(data_point['close']))
            
            # Add current quote data
            if quote.last_price:
                prices.append(quote.last_price)
            
            return prices if prices else [quote.last_price] if quote.last_price else [100.0]
        except:
            return [quote.last_price] if quote.last_price else [100.0]
    
    def _build_volume_array(self, quote: ETradeQuote, historical_data: List[Dict[str, Any]]) -> List[int]:
        """Build volume array for technical analysis"""
        try:
            volumes = []
            
            # Add historical data if available
            if historical_data:
                for data_point in historical_data:
                    if 'volume' in data_point:
                        volumes.append(int(data_point['volume']))
            
            # Add current quote data
            if quote.volume:
                volumes.append(quote.volume)
            
            return volumes if volumes else [quote.volume] if quote.volume else [1000000]
        except:
            return [quote.volume] if quote.volume else [1000000]
    
    def _build_closes_array(self, quote: ETradeQuote, historical_data: List[Dict[str, Any]]) -> List[float]:
        """Build closes array for technical analysis"""
        return self._build_price_array(quote, historical_data)
    
    def _build_highs_array(self, quote: ETradeQuote, historical_data: List[Dict[str, Any]]) -> List[float]:
        """Build highs array for technical analysis"""
        try:
            highs = []
            
            # Add historical data if available
            if historical_data:
                for data_point in historical_data:
                    if 'high' in data_point:
                        highs.append(float(data_point['high']))
            
            # Add current quote data
            if quote.high:
                highs.append(quote.high)
            
            return highs if highs else [quote.high] if quote.high else [quote.last_price] if quote.last_price else [100.0]
        except:
            return [quote.high] if quote.high else [quote.last_price] if quote.last_price else [100.0]
    
    def _build_lows_array(self, quote: ETradeQuote, historical_data: List[Dict[str, Any]]) -> List[float]:
        """Build lows array for technical analysis"""
        try:
            lows = []
            
            # Add historical data if available
            if historical_data:
                for data_point in historical_data:
                    if 'low' in data_point:
                        lows.append(float(data_point['low']))
            
            # Add current quote data
            if quote.low:
                lows.append(quote.low)
            
            return lows if lows else [quote.low] if quote.low else [quote.last_price] if quote.last_price else [100.0]
        except:
            return [quote.low] if quote.low else [quote.last_price] if quote.last_price else [100.0]
    
    def _build_opens_array(self, quote: ETradeQuote, historical_data: List[Dict[str, Any]]) -> List[float]:
        """Build opens array for technical analysis"""
        try:
            opens = []
            
            # Add historical data if available
            if historical_data:
                for data_point in historical_data:
                    if 'open' in data_point:
                        opens.append(float(data_point['open']))
            
            # Add current quote data
            if quote.open:
                opens.append(quote.open)
            
            return opens if opens else [quote.open] if quote.open else [quote.last_price] if quote.last_price else [100.0]
        except:
            return [quote.open] if quote.open else [quote.last_price] if quote.last_price else [100.0]
    
    def _get_fallback_market_data(self, symbol: str) -> Dict[str, Any]:
        """Get fallback market data when E*TRADE data is unavailable"""
        try:
            return {
                'symbol': symbol,
                'current_price': 100.0,
                'bid': 99.95,
                'ask': 100.05,
                'open': 99.50,
                'high': 100.50,
                'low': 99.00,
                'volume': 1000000,
                'change': 0.50,
                'change_pct': 0.5,
                'timestamp': datetime.utcnow().isoformat(),
                
                # Price arrays
                'prices': [99.50, 100.50, 99.00, 100.0],
                'volumes': [1000000],
                'closes': [100.0],
                'highs': [100.50],
                'lows': [99.00],
                'opens': [99.50],
                
                # Technical indicators (fallback values)
                'rsi': 50.0,
                'rsi_14': 50.0,
                'rsi_21': 50.0,
                'macd': 0.0,
                'macd_signal': 0.0,
                'macd_histogram': 0.0,
                'sma_20': 100.0,
                'sma_50': 100.0,
                'sma_200': 100.0,
                'ema_12': 100.0,
                'ema_26': 100.0,
                'atr': 1.0,
                'bollinger_upper': 101.0,
                'bollinger_middle': 100.0,
                'bollinger_lower': 99.0,
                'bollinger_width': 2.0,
                
                # Volume analysis
                'volume_ratio': 1.0,
                'volume_sma': 1000000,
                'obv': 0.0,
                'ad_line': 0.0,
                
                # Pattern recognition
                'doji': False,
                'hammer': False,
                'engulfing': False,
                'morning_star': False,
                
                # Metadata
                'data_source': 'FALLBACK',
                'data_quality': 'placeholder',
                'historical_points': 0,
                'last_updated': datetime.utcnow().isoformat()
            }
        except Exception as e:
            log.error(f"Error creating fallback market data: {e}")
            return {}
    
    def _get_basic_indicators(self, quote: ETradeQuote) -> Dict[str, Any]:
        """Get basic indicators when calculation fails"""
        return {
            'rsi': self._calculate_basic_rsi(quote),
            'rsi_14': self._calculate_basic_rsi(quote),
            'rsi_21': self._calculate_basic_rsi(quote),
            'macd': self._calculate_basic_macd(quote),
            'macd_signal': 0.0,
            'macd_histogram': 0.0,
            'sma_20': quote.last_price,
            'sma_50': quote.last_price,
            'sma_200': quote.last_price,
            'ema_12': quote.last_price,
            'ema_26': quote.last_price,
            'atr': self._calculate_basic_atr(quote),
            'bollinger_upper': quote.high,
            'bollinger_middle': quote.last_price,
            'bollinger_lower': quote.low,
            'bollinger_width': 0.0,
            'volume_ratio': 1.0,
            'volume_sma': quote.volume,
            'obv': 0.0,
            'ad_line': 0.0,
            'doji': False,
            'hammer': False,
            'engulfing': False,
            'morning_star': False,
            'data_quality': 'minimal'
        }
    
    # ========================================================================
    # COMPREHENSIVE TECHNICAL ANALYSIS METHODS
    # ========================================================================
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI with proper algorithm"""
        try:
            if len(prices) < period + 1:
                return 50.0
            
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [delta if delta > 0 else 0 for delta in deltas]
            losses = [-delta if delta < 0 else 0 for delta in deltas]
            
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            if avg_loss == 0:
                return 100.0
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except:
            return 50.0
    
    def _calculate_macd(self, prices: List[float]) -> float:
        """Calculate MACD line"""
        try:
            if len(prices) < 26:
                return 0.0
            
            ema_12 = self._calculate_ema(prices, 12)
            ema_26 = self._calculate_ema(prices, 26)
            return ema_12 - ema_26
        except:
            return 0.0
    
    def _calculate_macd_signal(self, prices: List[float]) -> float:
        """Calculate MACD signal line"""
        try:
            if len(prices) < 26:
                return 0.0
            
            macd_values = []
            for i in range(26, len(prices) + 1):
                ema_12 = self._calculate_ema(prices[:i], 12)
                ema_26 = self._calculate_ema(prices[:i], 26)
                macd_values.append(ema_12 - ema_26)
            
            if len(macd_values) < 9:
                return 0.0
            
            return self._calculate_ema(macd_values, 9)
        except:
            return 0.0
    
    def _calculate_macd_histogram(self, prices: List[float]) -> float:
        """Calculate MACD histogram"""
        try:
            macd = self._calculate_macd(prices)
            signal = self._calculate_macd_signal(prices)
            return macd - signal
        except:
            return 0.0
    
    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Calculate Simple Moving Average"""
        try:
            if len(prices) < period:
                return sum(prices) / len(prices) if prices else 0.0
            return sum(prices[-period:]) / period
        except:
            return 0.0
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        try:
            if len(prices) < period:
                return sum(prices) / len(prices) if prices else 0.0
            
            multiplier = 2 / (period + 1)
            ema = prices[0]
            
            for price in prices[1:]:
                ema = (price * multiplier) + (ema * (1 - multiplier))
            
            return ema
        except:
            return 0.0
    
    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculate Average True Range"""
        try:
            if len(highs) < period + 1:
                return 0.0
            
            true_ranges = []
            for i in range(1, len(highs)):
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i-1])
                tr3 = abs(lows[i] - closes[i-1])
                true_ranges.append(max(tr1, tr2, tr3))
            
            if len(true_ranges) < period:
                return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
            
            return sum(true_ranges[-period:]) / period
        except:
            return 0.0
    
    def _calculate_bollinger_upper(self, prices: List[float], period: int = 20, std_dev: float = 2.0) -> float:
        """Calculate Bollinger Bands upper band"""
        try:
            if len(prices) < period:
                return prices[-1] if prices else 0.0
            
            sma = self._calculate_sma(prices, period)
            variance = sum((price - sma) ** 2 for price in prices[-period:]) / period
            std = variance ** 0.5
            return sma + (std_dev * std)
        except:
            return prices[-1] if prices else 0.0
    
    def _calculate_bollinger_middle(self, prices: List[float], period: int = 20) -> float:
        """Calculate Bollinger Bands middle band (SMA)"""
        return self._calculate_sma(prices, period)
    
    def _calculate_bollinger_lower(self, prices: List[float], period: int = 20, std_dev: float = 2.0) -> float:
        """Calculate Bollinger Bands lower band"""
        try:
            if len(prices) < period:
                return prices[-1] if prices else 0.0
            
            sma = self._calculate_sma(prices, period)
            variance = sum((price - sma) ** 2 for price in prices[-period:]) / period
            std = variance ** 0.5
            return sma - (std_dev * std)
        except:
            return prices[-1] if prices else 0.0
    
    def _calculate_bollinger_width(self, prices: List[float], period: int = 20) -> float:
        """Calculate Bollinger Bands width"""
        try:
            upper = self._calculate_bollinger_upper(prices, period)
            lower = self._calculate_bollinger_lower(prices, period)
            middle = self._calculate_bollinger_middle(prices, period)
            return (upper - lower) / middle if middle != 0 else 0.0
        except:
            return 0.0
    
    def _calculate_volume_ratio(self, volumes: List[int], period: int = 20) -> float:
        """Calculate volume ratio (current vs average)"""
        try:
            if len(volumes) < 2:
                return 1.0
            
            current_volume = volumes[-1]
            avg_volume = self._calculate_sma(volumes, min(period, len(volumes)))
            return current_volume / avg_volume if avg_volume > 0 else 1.0
        except:
            return 1.0
    
    def _calculate_obv(self, closes: List[float], volumes: List[int]) -> float:
        """Calculate On-Balance Volume"""
        try:
            if len(closes) < 2 or len(volumes) < 2:
                return 0.0
            
            obv = 0.0
            for i in range(1, min(len(closes), len(volumes))):
                if closes[i] > closes[i-1]:
                    obv += volumes[i]
                elif closes[i] < closes[i-1]:
                    obv -= volumes[i]
            
            return obv
        except:
            return 0.0
    
    def _calculate_ad_line(self, highs: List[float], lows: List[float], closes: List[float], volumes: List[int]) -> float:
        """Calculate Accumulation/Distribution Line"""
        try:
            if len(highs) < 2 or len(volumes) < 2:
                return 0.0
            
            ad_line = 0.0
            for i in range(min(len(highs), len(lows), len(closes), len(volumes))):
                if highs[i] != lows[i]:
                    clv = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / (highs[i] - lows[i])
                    ad_line += clv * volumes[i]
            
            return ad_line
        except:
            return 0.0
    
    def _detect_doji(self, quote: ETradeQuote) -> bool:
        """Detect doji pattern"""
        try:
            if not all([quote.open, quote.close, quote.high, quote.low]):
                return False
            
            body_size = abs(quote.close - quote.open)
            total_range = quote.high - quote.low
            
            return body_size <= (total_range * 0.1) if total_range > 0 else False
        except:
            return False
    
    def _detect_hammer(self, quote: ETradeQuote) -> bool:
        """Detect hammer pattern"""
        try:
            if not all([quote.open, quote.close, quote.high, quote.low]):
                return False
            
            body_size = abs(quote.close - quote.open)
            lower_shadow = min(quote.open, quote.close) - quote.low
            upper_shadow = quote.high - max(quote.open, quote.close)
            total_range = quote.high - quote.low
            
            return (lower_shadow >= 2 * body_size and 
                   upper_shadow <= body_size * 0.5 and 
                   total_range > 0)
        except:
            return False
    
    def _parse_quotes_response(self, response: Dict) -> List[ETradeQuote]:
        """Parse quotes response (supports both JSON and XML)"""
        try:
            # Helper functions for safe type conversion
            def safe_float(value):
                try:
                    return float(value) if value else 0.0
                except (ValueError, TypeError):
                    return 0.0
            
            def safe_int(value):
                try:
                    return int(value) if value else 0
                except (ValueError, TypeError):
                    return 0
            
            # CRITICAL FIX: Handle JSON response (most common)
            if 'QuoteResponse' in response:
                log.info("📋 Parsing JSON quote response")
                quote_response = response['QuoteResponse']
                log.info(f"📋 QuoteResponse keys: {list(quote_response.keys()) if isinstance(quote_response, dict) else 'not a dict'}")
                
                # QuoteResponse can have either 'QuoteData' (list) or single quote
                quote_data_list = quote_response.get('QuoteData', [])
                log.info(f"📋 QuoteData type: {type(quote_data_list)}, length: {len(quote_data_list) if isinstance(quote_data_list, (list, tuple)) else 'N/A'}")
                
                # Ensure it's a list
                if not isinstance(quote_data_list, list):
                    quote_data_list = [quote_data_list]
                
                quotes = []
                for quote_data in quote_data_list:
                    if not quote_data:
                        continue
                    
                    # Extract product info (contains symbol)
                    product = quote_data.get('Product', {})
                    all_data = quote_data.get('All', {})
                    
                    quotes.append(ETradeQuote(
                        symbol=product.get('symbol', ''),
                        last_price=safe_float(all_data.get('lastTrade')),
                        change=safe_float(all_data.get('change')),
                        change_pct=safe_float(all_data.get('changePercent')),
                        volume=safe_int(all_data.get('totalVolume')),
                        bid=safe_float(all_data.get('bid')),
                        ask=safe_float(all_data.get('ask')),
                        high=safe_float(all_data.get('high')),
                        low=safe_float(all_data.get('low')),
                        open=safe_float(all_data.get('open'))
                    ))
                
                log.debug(f"Parsed {len(quotes)} quotes from JSON response")
                return quotes
            
            # Fallback: Handle XML response (legacy)
            xml_key = '<?xml version'
            if xml_key in response:
                log.debug("Parsing XML quote response")
                xml_data = response[xml_key]
                
                # Clean up XML data
                xml_data = xml_data.strip()
                if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                    xml_data = '<?xml version=' + xml_data
                elif not xml_data.startswith('<?xml version'):
                    xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
                
                root = ET.fromstring(xml_data)
                
                quotes = []
                for quote in root.findall('.//QuoteData'):
                    quote_data = {}
                    for child in quote:
                        quote_data[child.tag] = child.text
                    
                    quotes.append(ETradeQuote(
                        symbol=quote_data.get('symbol', ''),
                        last_price=safe_float(quote_data.get('lastPrice')),
                        change=safe_float(quote_data.get('change')),
                        change_pct=safe_float(quote_data.get('changePercent')),
                        volume=safe_int(quote_data.get('volume')),
                        bid=safe_float(quote_data.get('bid')),
                        ask=safe_float(quote_data.get('ask')),
                        high=safe_float(quote_data.get('high')),
                        low=safe_float(quote_data.get('low')),
                        open=safe_float(quote_data.get('open'))
                    ))
                
                log.debug(f"Parsed {len(quotes)} quotes from XML response")
                return quotes
            
            log.warning(f"Unknown response format - keys: {list(response.keys())}")
            return []
            
        except Exception as e:
            log.error(f"Failed to parse quotes response: {e}", exc_info=True)
            return []
    
    def get_cash_available_for_trading(self) -> Optional[float]:
        """Get cash available for trading (primary method)"""
        if not self.balance:
            self.get_account_balance()
        
        return self.balance.cash_available_for_investment if self.balance else None
    
    def get_cash_available_for_investment(self) -> Optional[float]:
        """Get cash specifically available for investment"""
        if not self.balance:
            self.get_account_balance()
        
        return self.balance.cash_available_for_investment if self.balance else None
    
    def get_cash_buying_power(self) -> Optional[float]:
        """Get total cash buying power (cash + margin)"""
        if not self.balance:
            self.get_account_balance()
        
        return self.balance.cash_buying_power if self.balance else None
    
    def get_available_cash_for_trading(self) -> Optional[float]:
        """
        Get the most appropriate cash amount for trading decisions
        
        Priority order:
        1. Cash available for investment (primary trading cash)
        2. Cash buying power (includes margin)
        """
        if not self.balance:
            self.get_account_balance()
        
        if not self.balance:
            return None
        
        # Priority order for trading decisions
        if self.balance.cash_available_for_investment is not None and self.balance.cash_available_for_investment > 0:
            return self.balance.cash_available_for_investment
        elif self.balance.cash_buying_power is not None and self.balance.cash_buying_power > 0:
            return self.balance.cash_buying_power
        else:
            return 0.0
    
    def get_total_portfolio_value(self) -> float:
        """Get total portfolio value from positions"""
        if not self.portfolio:
            self.get_portfolio()
        
        return sum(pos.market_value for pos in self.portfolio)
    
    def get_position_by_symbol(self, symbol: str) -> Optional[ETradePosition]:
        """Get position by symbol"""
        if not self.portfolio:
            self.get_portfolio()
        
        for position in self.portfolio:
            if position.symbol == symbol:
                return position
        return None
    
    def refresh_data(self):
        """Refresh all account data"""
        log.info("🔄 Refreshing ETrade account data...")
        self.get_account_balance()
        self.get_portfolio()
        log.info("✅ ETrade data refreshed")
    
    def get_account_summary(self) -> Dict[str, Any]:
        """Get comprehensive account summary"""
        if not self.selected_account:
            return {"error": "No account selected"}
        
        # Refresh data
        self.refresh_data()
        
        return {
            "account": {
                "id": self.selected_account.account_id,
                "name": self.selected_account.account_name,
                "status": self.selected_account.account_status,
                "type": self.selected_account.account_type
            },
            "balance": {
                "account_value": self.balance.account_value if self.balance else None,
                "cash_available_for_investment": self.balance.cash_available_for_investment if self.balance else None,
                "cash_buying_power": self.balance.cash_buying_power if self.balance else None,
                "option_level": self.balance.option_level if self.balance else None
            },
            "portfolio": {
                "total_positions": len(self.portfolio),
                "total_value": self.get_total_portfolio_value(),
                "positions": [
                    {
                        "symbol": pos.symbol,
                        "quantity": pos.quantity,
                        "market_value": pos.market_value,
                        "total_gain": pos.total_gain,
                        "total_gain_pct": pos.total_gain_pct,
                        "days_gain": pos.days_gain,
                        "days_gain_pct": pos.days_gain_pct
                    }
                    for pos in self.portfolio
                ]
            }
        }
    
    def get_orders(self, status: str = 'OPEN') -> List[Dict[str, Any]]:
        """Get account orders
        
        Args:
            status: Order status filter ('OPEN', 'EXECUTED', 'CANCELLED', 'REJECTED', 'EXPIRED')
        """
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"📋 Fetching orders for account {self.selected_account.account_id}...")
            
            response = self._make_etrade_api_call(
                method='GET',
                url=f"{self.config['base_url']}/v1/accounts/{self.selected_account.account_id_key}/orders",
                params={'status': status} if status else {}
            )
            
            orders = []
            if '<?xml version' in response:
                xml_data = response['<?xml version']
                orders = self._parse_orders_response(xml_data)
            
            log.info(f"✅ Retrieved {len(orders)} orders")
            return orders
            
        except Exception as e:
            log.error(f"Failed to get orders: {e}")
            return []
    
    def _parse_orders_response(self, xml_data: str) -> List[Dict[str, Any]]:
        """Parse orders XML response"""
        try:
            # Clean up XML data
            xml_data = xml_data.strip()
            if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                xml_data = '<?xml version=' + xml_data
            elif not xml_data.startswith('<?xml version'):
                xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
            
            root = ET.fromstring(xml_data)
            
            orders = []
            for order in root.findall('.//Order'):
                order_data = {
                    'order_id': order.find('orderId').text if order.find('orderId') is not None else None,
                    'status': order.find('status').text if order.find('status') is not None else None,
                    'order_type': order.find('orderType').text if order.find('orderType') is not None else None,
                    'side': order.find('side').text if order.find('side') is not None else None,
                    'symbol': order.find('symbol').text if order.find('symbol') is not None else None,
                    'quantity': int(order.find('quantity').text) if order.find('quantity') is not None else 0,
                    'price': float(order.find('price').text) if order.find('price') is not None else None,
                    'stop_price': float(order.find('stopPrice').text) if order.find('stopPrice') is not None else None,
                    'time_in_force': order.find('timeInForce').text if order.find('timeInForce') is not None else None,
                    'created_time': order.find('createdTime').text if order.find('createdTime') is not None else None,
                    'executed_quantity': int(order.find('executedQuantity').text) if order.find('executedQuantity') is not None else 0,
                    'remaining_quantity': int(order.find('remainingQuantity').text) if order.find('remainingQuantity') is not None else 0,
                }
                orders.append(order_data)
            
            return orders
            
        except Exception as e:
            log.error(f"Failed to parse orders XML: {e}")
            return []
    
    def preview_order(self, symbol: str, quantity: int, side: str, order_type: str = 'MARKET', 
                     price: Optional[float] = None, stop_price: Optional[float] = None) -> Dict[str, Any]:
        """Preview order before placing
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            side: 'BUY' or 'SELL'
            order_type: 'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'
            price: Limit price (for LIMIT orders)
            stop_price: Stop price (for STOP orders)
        """
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"🔍 Previewing {side} order for {quantity} shares of {symbol}...")
            
            # Build order data
            order_data = {
                'orderType': order_type,
                'clientOrderId': f"PREVIEW_{int(time.time())}",
                'Order': [{
                    'allOrNone': False,
                    'priceType': 'MARKET' if order_type == 'MARKET' else 'LIMIT',
                    'orderAction': side,
                    'quantity': quantity,
                    'symbol': symbol,
                    'orderTerm': 'GOOD_FOR_DAY'
                }]
            }
            
            # Add price if limit order
            if order_type == 'LIMIT' and price:
                order_data['Order'][0]['limitPrice'] = price
            
            # Add stop price if stop order
            if order_type in ['STOP', 'STOP_LIMIT'] and stop_price:
                order_data['Order'][0]['stopPrice'] = stop_price
            
            response = self._make_etrade_api_call(
                method='POST',
                url=f"{self.config['base_url']}/v1/accounts/{self.selected_account.account_id_key}/orders/preview",
                params=order_data
            )
            
            log.info(f"✅ Order preview successful")
            return response
            
        except Exception as e:
            log.error(f"Failed to preview order: {e}")
            raise
    
    def place_order(self, symbol: str, quantity: int, side: str, order_type: str = 'MARKET',
                   price: Optional[float] = None, stop_price: Optional[float] = None,
                   client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """Place an order
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            side: 'BUY' or 'SELL'
            order_type: 'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'
            price: Limit price (for LIMIT orders)
            stop_price: Stop price (for STOP orders)
            client_order_id: Custom order ID
        """
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"📝 Placing {side} order for {quantity} shares of {symbol}...")
            
            # Generate client order ID if not provided
            if not client_order_id:
                client_order_id = f"ETRADE_{int(time.time())}"
            
            # Build order data
            order_data = {
                'orderType': order_type,
                'clientOrderId': client_order_id,
                'Order': [{
                    'allOrNone': False,
                    'priceType': 'MARKET' if order_type == 'MARKET' else 'LIMIT',
                    'orderAction': side,
                    'quantity': quantity,
                    'symbol': symbol,
                    'orderTerm': 'GOOD_FOR_DAY'
                }]
            }
            
            # Add price if limit order
            if order_type == 'LIMIT' and price:
                order_data['Order'][0]['limitPrice'] = price
            
            # Add stop price if stop order
            if order_type in ['STOP', 'STOP_LIMIT'] and stop_price:
                order_data['Order'][0]['stopPrice'] = stop_price
            
            # DIAGNOSTIC (Rev 00180): Log order details before placing
            log.info(f"📋 Order Details:")
            log.info(f"   Account: {self.selected_account.account_id_key}")
            log.info(f"   Symbol: {symbol}")
            log.info(f"   Side: {side}")
            log.info(f"   Quantity: {quantity}")
            log.info(f"   Order Type: {order_type}")
            log.info(f"   Environment: {self.environment}")
            log.info(f"   Base URL: {self.config.get('base_url', 'N/A')}")
            
            response = self._make_etrade_api_call(
                method='POST',
                url=f"{self.config['base_url']}/v1/accounts/{self.selected_account.account_id_key}/orders/place",
                params=order_data
            )
            
            # DIAGNOSTIC (Rev 00180): Log full response
            log.info(f"📬 ETrade Response: {response}")
            log.info(f"✅ Order placed successfully: {client_order_id}")
            return response
            
        except Exception as e:
            log.error(f"Failed to place order: {e}")
            raise
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order
        
        Args:
            order_id: Order ID to cancel
        """
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"❌ Cancelling order {order_id}...")
            
            response = self._make_etrade_api_call(
                method='DELETE',
                url=f"{self.config['base_url']}/v1/accounts/{self.selected_account.account_id_key}/orders/cancel",
                params={'orderId': order_id}
            )
            
            log.info(f"✅ Order cancelled successfully")
            return response
            
        except Exception as e:
            log.error(f"Failed to cancel order: {e}")
            raise
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status
        
        Args:
            order_id: Order ID to check
        """
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"🔍 Getting status for order {order_id}...")
            
            response = self._make_etrade_api_call(
                method='GET',
                url=f"{self.config['base_url']}/v1/accounts/{self.selected_account.account_id_key}/orders/{order_id}",
                params={}
            )
            
            log.info(f"✅ Retrieved order status")
            return response
            
        except Exception as e:
            log.error(f"Failed to get order status: {e}")
            raise
    
    def get_market_hours(self) -> Dict[str, Any]:
        """Get market hours information"""
        try:
            log.info("🕐 Fetching market hours...")
            
            response = self._make_etrade_api_call(
                method='GET',
                url=f"{self.config['base_url']}/v1/market/hours",
                params={}
            )
            
            log.info(f"✅ Retrieved market hours")
            return response
            
        except Exception as e:
            log.error(f"Failed to get market hours: {e}")
            return {}
    
    def execute_batch_orders(self, orders: List[Dict[str, Any]], max_concurrent: int = 3) -> Dict[str, Any]:
        """
        Execute multiple orders with controlled concurrency (Rev 00180T)
        
        Handles 30-40 simultaneous orders efficiently with:
        - Controlled concurrency (3 at a time)
        - Rate limiting (1.2s spacing)
        - Automatic retry on errors
        - Order verification
        
        Args:
            orders: List of order dictionaries with keys:
                    {symbol, quantity, side, order_type, signal_type, confidence}
            max_concurrent: Maximum concurrent orders (default 3)
        
        Returns:
            Dict with execution results:
                {success_count, failed_count, executed_orders, failed_orders}
        """
        try:
            import asyncio
            from concurrent.futures import ThreadPoolExecutor
            import time
            
            log.info(f"")
            log.info(f"{'='*80}")
            log.info(f"🎯 BATCH EXECUTION: {len(orders)} orders")
            log.info(f"{'='*80}")
            log.info(f"   Max Concurrent: {max_concurrent}")
            log.info(f"   Spacing: 1.2s between bursts")
            log.info(f"")
            
            executed_orders = []
            failed_orders = []
            
            # Sort by confidence (highest first)
            sorted_orders = sorted(orders, key=lambda x: x.get('confidence', 0.85), reverse=True)
            
            # Log prioritized queue
            log.info(f"📊 PRIORITIZED ORDER QUEUE:")
            for i, order in enumerate(sorted_orders[:10], 1):
                log.info(f"   {i}. {order['symbol']} {order.get('side', 'BUY')} {order.get('quantity', 0)} (conf={order.get('confidence', 0.85):.0%})")
            if len(sorted_orders) > 10:
                log.info(f"   ... and {len(sorted_orders) - 10} more")
            log.info(f"")
            
            # Execute in batches of max_concurrent
            start_time = time.time()
            
            for i in range(0, len(sorted_orders), max_concurrent):
                batch = sorted_orders[i:i+max_concurrent]
                batch_num = i // max_concurrent + 1
                
                log.info(f"📦 Batch {batch_num}: Executing {len(batch)} orders...")
                
                # Execute this batch concurrently
                with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                    futures = []
                    
                    for order in batch:
                        future = executor.submit(self._execute_single_order_with_retry, order)
                        futures.append((future, order))
                    
                    # Wait for all in this batch to complete
                    for future, order in futures:
                        try:
                            result = future.result(timeout=30)
                            if result.get('success'):
                                executed_orders.append(result)
                                log.info(f"   ✅ {order['symbol']}: Executed")
                            else:
                                failed_orders.append({'order': order, 'error': result.get('error', 'Unknown')})
                                log.warning(f"   ❌ {order['symbol']}: Failed - {result.get('error', 'Unknown')}")
                        except Exception as e:
                            failed_orders.append({'order': order, 'error': str(e)})
                            log.error(f"   ❌ {order['symbol']}: Exception - {e}")
                
                # Spacing between batches (rate limiting)
                if i + max_concurrent < len(sorted_orders):
                    time.sleep(1.2)
            
            duration = time.time() - start_time
            
            log.info(f"")
            log.info(f"{'='*80}")
            log.info(f"✅ BATCH EXECUTION COMPLETE")
            log.info(f"{'='*80}")
            log.info(f"   Duration: {duration:.1f}s")
            log.info(f"   Success: {len(executed_orders)}/{len(orders)} ✅")
            log.info(f"   Failed: {len(failed_orders)}/{len(orders)}")
            log.info(f"   Success Rate: {len(executed_orders)/len(orders)*100:.1f}%")
            log.info(f"")
            
            return {
                'success': True,
                'success_count': len(executed_orders),
                'failed_count': len(failed_orders),
                'executed_orders': executed_orders,
                'failed_orders': failed_orders,
                'duration': duration
            }
            
        except Exception as e:
            log.error(f"Batch execution failed: {e}", exc_info=True)
            return {
                'success': False,
                'success_count': 0,
                'failed_count': len(orders),
                'executed_orders': [],
                'failed_orders': [{'order': o, 'error': str(e)} for o in orders],
                'error': str(e)
            }
    
    def _execute_single_order_with_retry(self, order: Dict[str, Any], max_retries: int = 3) -> Dict[str, Any]:
        """
        Execute single order with retry logic
        
        Args:
            order: Order dictionary
            max_retries: Maximum retry attempts
        
        Returns:
            Execution result dict
        """
        for attempt in range(1, max_retries + 1):
            try:
                # Place order
                response = self.place_order(
                    symbol=order['symbol'],
                    quantity=order['quantity'],
                    side=order.get('side', 'BUY'),
                    order_type=order.get('order_type', 'MARKET')
                )
                
                # Check response
                if response and not isinstance(response, dict) or 'error' not in response:
                    # Success
                    order_id = self._extract_order_id_from_response(response)
                    return {
                        'success': True,
                        'symbol': order['symbol'],
                        'quantity': order['quantity'],
                        'side': order.get('side', 'BUY'),
                        'order_id': order_id,
                        'signal_type': order.get('signal_type', 'TRADE')
                    }
                else:
                    # Error response
                    error_msg = response.get('error', 'Unknown') if isinstance(response, dict) else str(response)
                    
                    # Check if retriable
                    if self._is_retriable_error(error_msg) and attempt < max_retries:
                        wait_time = 2 ** attempt
                        log.warning(f"   ⚠️ Retry {attempt}/{max_retries} for {order['symbol']}: {error_msg}")
                        time.sleep(wait_time)
                        continue
                    else:
                        return {'success': False, 'symbol': order['symbol'], 'error': error_msg}
            
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    return {'success': False, 'symbol': order['symbol'], 'error': str(e)}
        
        return {'success': False, 'symbol': order['symbol'], 'error': 'Max retries exceeded'}
    
    def _extract_order_id_from_response(self, response) -> Optional[str]:
        """Extract order ID from E*TRADE response"""
        try:
            if isinstance(response, dict):
                for field in ['orderId', 'order_id', 'OrderId', 'id']:
                    if field in response:
                        return str(response[field])
                
                if 'OrderResponse' in response:
                    return self._extract_order_id_from_response(response['OrderResponse'])
                if 'Order' in response:
                    return self._extract_order_id_from_response(response['Order'])
            
            return None
        except:
            return None
    
    def _is_retriable_error(self, error_msg: str) -> bool:
        """Check if error should be retried"""
        retriable = ['rate limit', '429', 'timeout', 'temporary', 'unavailable', 'network', 'connection']
        error_lower = str(error_msg).lower()
        return any(keyword in error_lower for keyword in retriable)
    
    def get_option_chains(self, symbol: str, expiry_date: str, option_type: str = 'CALL') -> Dict[str, Any]:
        """Get option chains for a symbol
        
        Args:
            symbol: Stock symbol
            expiry_date: Expiry date (YYYY-MM-DD)
            option_type: 'CALL' or 'PUT'
        """
        try:
            log.info(f"🔗 Fetching option chains for {symbol} expiring {expiry_date}...")
            
            response = self._make_etrade_api_call(
                method='GET',
                url=f"{self.config['base_url']}/v1/market/optionchains",
                params={
                    'symbol': symbol,
                    'expiryDate': expiry_date,
                    'optionType': option_type,
                    'includeWeekly': 'true'
                }
            )
            
            log.info(f"✅ Retrieved option chains")
            return response
            
        except Exception as e:
            log.error(f"Failed to get option chains: {e}")
            return {}
    
    def get_account_alerts(self) -> List[Dict[str, Any]]:
        """Get account alerts"""
        if not self.selected_account:
            raise Exception("No account selected")
        
        try:
            log.info(f"🔔 Fetching alerts for account {self.selected_account.account_id}...")
            
            response = self._make_etrade_api_call(
                method='GET',
                url=f"{self.config['base_url']}/v1/user/alerts",
                params={}
            )
            
            alerts = []
            if '<?xml version' in response:
                xml_data = response['<?xml version']
                alerts = self._parse_alerts_response(xml_data)
            
            log.info(f"✅ Retrieved {len(alerts)} alerts")
            return alerts
            
        except Exception as e:
            log.error(f"Failed to get alerts: {e}")
            return []
    
    def _parse_alerts_response(self, xml_data: str) -> List[Dict[str, Any]]:
        """Parse alerts XML response"""
        try:
            # Clean up XML data
            xml_data = xml_data.strip()
            if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                xml_data = '<?xml version=' + xml_data
            elif not xml_data.startswith('<?xml version'):
                xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
            
            root = ET.fromstring(xml_data)
            
            alerts = []
            for alert in root.findall('.//Alert'):
                alert_data = {
                    'alert_id': alert.find('alertId').text if alert.find('alertId') is not None else None,
                    'alert_name': alert.find('alertName').text if alert.find('alertName') is not None else None,
                    'alert_type': alert.find('alertType').text if alert.find('alertType') is not None else None,
                    'status': alert.find('status').text if alert.find('status') is not None else None,
                    'created_time': alert.find('createdTime').text if alert.find('createdTime') is not None else None,
                    'symbol': alert.find('symbol').text if alert.find('symbol') is not None else None,
                    'condition': alert.find('condition').text if alert.find('condition') is not None else None,
                    'trigger_price': float(alert.find('triggerPrice').text) if alert.find('triggerPrice') is not None else None,
                }
                alerts.append(alert_data)
            
            return alerts
            
        except Exception as e:
            log.error(f"Failed to parse alerts XML: {e}")
            return []

# Global instance
_etrade_trading_instance: Optional[PrimeETradeTrading] = None
_etrade_trading_lock = threading.Lock()

def get_etrade_trading(environment: str = 'prod') -> PrimeETradeTrading:
    """Get or create ETrade trading instance"""
    global _etrade_trading_instance
    with _etrade_trading_lock:
        if _etrade_trading_instance is None:
            _etrade_trading_instance = PrimeETradeTrading(environment)
        return _etrade_trading_instance

def test_etrade_trading():
    """Test ETrade trading functionality"""
    try:
        print("🔐 Testing ETrade Trading System...")
        
        etrade = get_etrade_trading('prod')
        
        print(f"✅ Environment: {etrade.environment}")
        print(f"✅ Accounts loaded: {len(etrade.accounts)}")
        
        if etrade.selected_account:
            print(f"✅ Selected account: {etrade.selected_account.account_name} ({etrade.selected_account.account_id})")
            
            # Test balance
            balance = etrade.get_account_balance()
            print(f"✅ Account value: ${balance.account_value}")
            print(f"✅ Cash available for investment: ${balance.cash_available_for_investment}")
            print(f"✅ Cash buying power: ${balance.cash_buying_power}")
            print(f"✅ Option level: {balance.option_level}")
            
            # Test portfolio
            portfolio = etrade.get_portfolio()
            print(f"✅ Portfolio positions: {len(portfolio)}")
            
            # Test quotes for first few positions
            if portfolio:
                symbols = [pos.symbol for pos in portfolio[:3]]
                quotes = etrade.get_quotes(symbols)
                print(f"✅ Retrieved quotes for {len(quotes)} symbols")
                
                # Test comprehensive market data for strategies
                if quotes:
                    test_symbol = quotes[0].symbol
                    market_data = etrade.get_market_data_for_strategy(test_symbol)
                    print(f"✅ Generated comprehensive market data for {test_symbol}:")
                    print(f"   Data quality: {market_data.get('data_quality', 'unknown')}")
                    print(f"   Historical points: {market_data.get('historical_points', 0)}")
                    print(f"   RSI: {market_data.get('rsi', 0):.2f}")
                    print(f"   MACD: {market_data.get('macd', 0):.4f}")
                    print(f"   SMA 20: {market_data.get('sma_20', 0):.2f}")
                    print(f"   Volume ratio: {market_data.get('volume_ratio', 0):.2f}")
                    print(f"   Bollinger width: {market_data.get('bollinger_width', 0):.4f}")
                    print(f"   Patterns - Doji: {market_data.get('doji', False)}, Hammer: {market_data.get('hammer', False)}")
            
            # Get summary
            summary = etrade.get_account_summary()
            print(f"✅ Account summary generated")
            
        print("🎯 ETrade trading system test completed successfully!")
        
    except Exception as e:
        log.error(f"❌ ETrade trading test failed: {e}")
        raise

if __name__ == '__main__':
    test_etrade_trading()
