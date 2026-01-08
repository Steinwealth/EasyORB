#!/usr/bin/env python3
"""
Central ETrade OAuth Manager
===========================

Central token manager that owns all OAuth operations for the ETrade Strategy.
Provides start(), renew_if_needed(), sign_request(), and status() APIs.

Features:
- Per-environment token management (sandbox/prod)
- Daily re-auth after midnight ET
- Idle auto-renew (same ET day)
- Secure token storage with encryption
- Operational guardrails and observability
- Time & signing hygiene
- Per-user scope management
"""

import os
import sys
import json
import time
import logging
import hashlib
import hmac
import base64
import urllib.parse
import urllib.request
import secrets
import webbrowser
import threading
from typing import Dict, Optional, Tuple, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
import requests
from pathlib import Path
from cryptography.fernet import Fernet
import psutil

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('etrade_oauth.log')
    ]
)
log = logging.getLogger(__name__)

class Environment(Enum):
    """ETrade environment enumeration"""
    SANDBOX = "sandbox"
    PRODUCTION = "prod"

class TokenStatus(Enum):
    """Token status enumeration"""
    ACTIVE = "active"
    IDLE = "idle"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    ERROR = "error"

@dataclass
class TokenInfo:
    """Token information container"""
    oauth_token: str
    oauth_token_secret: str
    created_at: datetime
    last_used: datetime
    last_renewed: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    issued_et_date: Optional[str] = None  # ET date when token was issued
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'oauth_token': self.oauth_token,
            'oauth_token_secret': self.oauth_token_secret,
            'created_at': self.created_at.isoformat(),
            'last_used': self.last_used.isoformat(),
            'last_renewed': self.last_renewed.isoformat() if self.last_renewed else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'issued_et_date': self.issued_et_date
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TokenInfo':
        """Create from dictionary"""
        return cls(
            oauth_token=data['oauth_token'],
            oauth_token_secret=data['oauth_token_secret'],
            created_at=datetime.fromisoformat(data['created_at']),
            last_used=datetime.fromisoformat(data['last_used']),
            last_renewed=datetime.fromisoformat(data['last_renewed']) if data.get('last_renewed') else None,
            expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
            issued_et_date=data.get('issued_et_date')
        )

@dataclass
class OperationalMetrics:
    """Operational metrics for monitoring"""
    renew_attempts: int = 0
    renew_failures: int = 0
    consecutive_failures: int = 0
    last_401_count: int = 0
    last_successful_call: Optional[datetime] = None
    next_midnight_et: Optional[datetime] = None
    last_midnight_re_auth: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'renew_attempts': self.renew_attempts,
            'renew_failures': self.renew_failures,
            'consecutive_failures': self.consecutive_failures,
            'last_401_count': self.last_401_count,
            'last_successful_call': self.last_successful_call.isoformat() if self.last_successful_call else None,
            'next_midnight_et': self.next_midnight_et.isoformat() if self.next_midnight_et else None,
            'last_midnight_re_auth': self.last_midnight_re_auth.isoformat() if self.last_midnight_re_auth else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'OperationalMetrics':
        """Create from dictionary"""
        return cls(
            renew_attempts=data.get('renew_attempts', 0),
            renew_failures=data.get('renew_failures', 0),
            consecutive_failures=data.get('consecutive_failures', 0),
            last_401_count=data.get('last_401_count', 0),
            last_successful_call=datetime.fromisoformat(data['last_successful_call']) if data.get('last_successful_call') else None,
            next_midnight_et=datetime.fromisoformat(data['next_midnight_et']) if data.get('next_midnight_et') else None,
            last_midnight_re_auth=datetime.fromisoformat(data['last_midnight_re_auth']) if data.get('last_midnight_re_auth') else None
        )

class CentralOAuthManager:
    """
    Central ETrade OAuth Manager
    
    Owns all OAuth operations for the ETrade Strategy.
    Provides centralized token management with operational guardrails.
    """
    
    def __init__(self, oauth_dir: str = None):
        """
        Initialize central OAuth manager
        
        Args:
            oauth_dir: Directory for token storage (default: current directory)
        """
        self.oauth_dir = oauth_dir or os.path.dirname(__file__)
        self.encryption_key = self._get_or_create_encryption_key()
        
        # Environment configurations
        self.environments = {
            Environment.SANDBOX: {
                'base_url': 'https://apisb.etrade.com',
                'key_var': 'ETRADE_SANDBOX_KEY',
                'secret_var': 'ETRADE_SANDBOX_SECRET',
                'token_file': os.path.join(self.oauth_dir, 'tokens_sandbox.json'),
                'metrics_file': os.path.join(self.oauth_dir, 'metrics_sandbox.json')
            },
            Environment.PRODUCTION: {
                'base_url': 'https://api.etrade.com',
                'key_var': 'ETRADE_PROD_KEY',
                'secret_var': 'ETRADE_PROD_SECRET',
                'token_file': os.path.join(self.oauth_dir, 'tokens_prod.json'),
                'metrics_file': os.path.join(self.oauth_dir, 'metrics_prod.json')
            }
        }
        
        self.authorize_url = 'https://us.etrade.com/e/t/etws/authorize'
        self._lock = threading.Lock()  # Thread safety
        
        log.info("Central OAuth Manager initialized")
    
    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create encryption key for secure token storage"""
        key_file = os.path.join(self.oauth_dir, '.oauth_key')
        
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            os.chmod(key_file, 0o600)  # Secure permissions
            return key
    
    def _encrypt_token_data(self, data: str) -> str:
        """Encrypt token data"""
        f = Fernet(self.encryption_key)
        return f.encrypt(data.encode()).decode()
    
    def _decrypt_token_data(self, encrypted_data: str) -> str:
        """Decrypt token data"""
        f = Fernet(self.encryption_key)
        return f.decrypt(encrypted_data.encode()).decode()
    
    def _get_current_et_date(self) -> str:
        """Get current ET date string"""
        # Simplified ET timezone handling
        # In production, use proper timezone libraries
        now = datetime.now()
        return now.strftime('%Y-%m-%d')
    
    def _is_midnight_et_passed(self, token_info: TokenInfo) -> bool:
        """Check if midnight ET has passed since token creation"""
        if not token_info.issued_et_date:
            return True
        
        current_et_date = self._get_current_et_date()
        return token_info.issued_et_date != current_et_date
    
    def _needs_renewal(self, token_info: TokenInfo) -> bool:
        """Check if tokens need renewal (idle for 2+ hours)"""
        if not token_info.last_renewed:
            token_info.last_renewed = token_info.created_at
        
        idle_time = datetime.now() - token_info.last_renewed
        return idle_time > timedelta(hours=2)
    
    def _generate_nonce(self) -> str:
        """Generate OAuth nonce"""
        return secrets.token_urlsafe(32)
    
    def _generate_timestamp(self) -> str:
        """Generate OAuth timestamp"""
        return str(int(time.time()))
    
    def _generate_signature(self, method: str, url: str, params: Dict[str, str], 
                           consumer_secret: str, token_secret: str = "") -> str:
        """Generate OAuth 1.0a HMAC-SHA1 signature"""
        # Create parameter string
        param_string = "&".join([f"{k}={urllib.parse.quote(str(v), safe='')}" 
                                for k, v in sorted(params.items())])
        
        # Create signature base string
        base_string = f"{method.upper()}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_string, safe='')}"
        
        # Create signing key
        signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
        
        # Generate HMAC-SHA1 signature
        signature = hmac.new(
            signing_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha1
        ).digest()
        
        return base64.b64encode(signature).decode('utf-8')
    
    def _make_oauth_request(self, method: str, url: str, params: Dict[str, str], 
                           consumer_key: str, consumer_secret: str,
                           oauth_token: Optional[str] = None, 
                           oauth_token_secret: str = "") -> Dict:
        """Make OAuth-signed HTTP request with exponential backoff"""
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                # OAuth parameters
                oauth_params = {
                    'oauth_consumer_key': consumer_key,
                    'oauth_nonce': self._generate_nonce(),
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp': self._generate_timestamp(),
                    'oauth_version': '1.0'
                }
                
                # Add token if available
                if oauth_token:
                    oauth_params['oauth_token'] = oauth_token
                
                # Merge parameters
                all_params = {**oauth_params, **params}
                
                # Generate signature
                signature = self._generate_signature(method, url, all_params, consumer_secret, oauth_token_secret)
                all_params['oauth_signature'] = signature
                
                # Create Authorization header
                auth_header = "OAuth " + ", ".join([f'{k}="{urllib.parse.quote(str(v), safe="")}"' 
                                                  for k, v in all_params.items() if k.startswith('oauth_')])
                
                # Make request
                req = urllib.request.Request(url, headers={'Authorization': auth_header})
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    if response.headers.get_content_type() == 'application/json':
                        return json.loads(response.read().decode('utf-8'))
                    else:
                        # Parse form-encoded response
                        response_text = response.read().decode('utf-8')
                        return dict(urllib.parse.parse_qsl(response_text))
                        
            except urllib.error.HTTPError as e:
                error_response = e.read().decode('utf-8')
                
                if e.code == 401:
                    # Check for specific OAuth problems
                    if 'token_revoked' in error_response or 'token_inactive' in error_response:
                        raise ValueError(f"Token inactive/revoked: {error_response}")
                    elif 'token_expired' in error_response:
                        raise ValueError(f"Token expired: {error_response}")
                
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    log.warning(f"HTTP Error {e.code}, retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    log.error(f"HTTP Error {e.code}: {error_response}")
                    raise
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    log.warning(f"Request failed, retrying in {delay}s: {e}")
                    time.sleep(delay)
                    continue
                else:
                    log.error(f"Request failed: {e}")
                    raise
    
    def _save_tokens(self, env: Environment, token_info: TokenInfo) -> None:
        """Save tokens with encryption"""
        with self._lock:
            config = self.environments[env]
            token_file = config['token_file']
            
            # Encrypt sensitive data
            encrypted_data = {
                'oauth_token': self._encrypt_token_data(token_info.oauth_token),
                'oauth_token_secret': self._encrypt_token_data(token_info.oauth_token_secret),
                'created_at': token_info.created_at.isoformat(),
                'last_used': token_info.last_used.isoformat(),
                'last_renewed': token_info.last_renewed.isoformat() if token_info.last_renewed else None,
                'expires_at': token_info.expires_at.isoformat() if token_info.expires_at else None,
                'issued_et_date': token_info.issued_et_date
            }
            
            with open(token_file, 'w') as f:
                json.dump(encrypted_data, f, indent=2)
            
            log.info(f"Tokens saved to {token_file}")
    
    def _load_tokens(self, env: Environment) -> Optional[TokenInfo]:
        """Load tokens with decryption"""
        config = self.environments[env]
        token_file = config['token_file']
        
        if not os.path.exists(token_file):
            return None
        
        try:
            with open(token_file, 'r') as f:
                encrypted_data = json.load(f)
            
            # Decrypt sensitive data
            token_info = TokenInfo(
                oauth_token=self._decrypt_token_data(encrypted_data['oauth_token']),
                oauth_token_secret=self._decrypt_token_data(encrypted_data['oauth_token_secret']),
                created_at=datetime.fromisoformat(encrypted_data['created_at']),
                last_used=datetime.fromisoformat(encrypted_data['last_used']),
                last_renewed=datetime.fromisoformat(encrypted_data['last_renewed']) if encrypted_data.get('last_renewed') else None,
                expires_at=datetime.fromisoformat(encrypted_data['expires_at']) if encrypted_data.get('expires_at') else None,
                issued_et_date=encrypted_data.get('issued_et_date')
            )
            
            return token_info
            
        except Exception as e:
            log.error(f"Failed to load tokens from {token_file}: {e}")
            return None
    
    def _save_metrics(self, env: Environment, metrics: OperationalMetrics) -> None:
        """Save operational metrics"""
        config = self.environments[env]
        metrics_file = config['metrics_file']
        
        with open(metrics_file, 'w') as f:
            json.dump(metrics.to_dict(), f, indent=2)
    
    def _load_metrics(self, env: Environment) -> OperationalMetrics:
        """Load operational metrics"""
        config = self.environments[env]
        metrics_file = config['metrics_file']
        
        if os.path.exists(metrics_file):
            try:
                with open(metrics_file, 'r') as f:
                    data = json.load(f)
                return OperationalMetrics.from_dict(data)
            except Exception as e:
                log.error(f"Failed to load metrics from {metrics_file}: {e}")
        
        return OperationalMetrics()
    
    def start(self, env: Environment) -> bool:
        """
        Start full 3-legged OAuth flow
        
        Args:
            env: Environment (sandbox or production)
            
        Returns:
            True if successful
        """
        log.info(f"Starting OAuth flow for {env.value} environment")
        
        try:
            # Load credentials from environment
            config = self.environments[env]
            consumer_key = os.getenv(config['key_var'])
            consumer_secret = os.getenv(config['secret_var'])
            
            if not consumer_key or not consumer_secret:
                raise ValueError(f"Missing credentials. Set {config['key_var']} and {config['secret_var']} environment variables")
            
            base_url = config['base_url']
            
            # Step 1: Get request token
            log.info("Step 1: Getting request token...")
            request_url = f"{base_url}/oauth/request_token"
            params = {'oauth_callback': 'oob'}
            
            response = self._make_oauth_request('GET', request_url, params, 
                                             consumer_key, consumer_secret)
            
            if 'oauth_token' not in response:
                raise ValueError(f"Invalid request token response: {response}")
            
            request_token = response['oauth_token']
            request_token_secret = response['oauth_token_secret']
            
            log.info("✅ Request token obtained successfully")
            
            # Step 2: Get authorization URL
            log.info("Step 2: Getting authorization URL...")
            auth_url = f"{self.authorize_url}?key={consumer_key}&token={request_token}"
            
            log.info(f"Opening authorization URL in browser...")
            log.info(f"Authorization URL: {auth_url}")
            
            # Open browser
            webbrowser.open(auth_url)
            
            # Get verification code from user
            print("\n" + "="*60)
            print("🔐 ETrade Authorization Required")
            print("="*60)
            print(f"1. A browser window should have opened to: {auth_url}")
            print("2. Log in to your ETrade account")
            print("3. Authorize the application")
            print("4. Copy the verification code (PIN) from the page")
            print("5. Paste it below")
            print("="*60)
            
            oauth_verifier = input("Enter verification code (PIN): ").strip()
            
            if not oauth_verifier:
                raise ValueError("No verification code provided")
            
            # Step 3: Exchange for access token
            log.info("Step 3: Exchanging for access token...")
            access_url = f"{base_url}/oauth/access_token"
            params = {'oauth_verifier': oauth_verifier}
            
            response = self._make_oauth_request('GET', access_url, params,
                                             consumer_key, consumer_secret,
                                             request_token, request_token_secret)
            
            if 'oauth_token' not in response:
                raise ValueError(f"Invalid access token response: {response}")
            
            # Create token info
            now = datetime.now()
            current_et_date = self._get_current_et_date()
            midnight_et = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            
            token_info = TokenInfo(
                oauth_token=response['oauth_token'],
                oauth_token_secret=response['oauth_token_secret'],
                created_at=now,
                last_used=now,
                expires_at=midnight_et,
                issued_et_date=current_et_date
            )
            
            # Save tokens
            self._save_tokens(env, token_info)
            
            # Update metrics
            metrics = self._load_metrics(env)
            metrics.last_midnight_re_auth = now
            metrics.next_midnight_et = midnight_et
            metrics.last_successful_call = now
            metrics.consecutive_failures = 0  # Reset on successful auth
            self._save_metrics(env, metrics)
            
            log.info("✅ OAuth flow completed successfully!")
            log.info(f"Tokens expire at: {midnight_et}")
            
            return True
            
        except Exception as e:
            log.error(f"OAuth flow failed: {e}")
            
            # Update metrics
            metrics = self._load_metrics(env)
            metrics.consecutive_failures += 1
            self._save_metrics(env, metrics)
            
            return False
    
    def renew_if_needed(self, env: Environment) -> bool:
        """
        Renew tokens if needed (idle for 2+ hours, same ET day)
        
        Args:
            env: Environment
            
        Returns:
            True if renewal successful or not needed
        """
        with self._lock:
            log.info(f"Checking if renewal needed for {env.value} environment")
            
            token_info = self._load_tokens(env)
            if not token_info:
                log.error("No tokens found. Run 'start' command first.")
                return False
            
            # Check if midnight ET has passed
            if self._is_midnight_et_passed(token_info):
                log.error("Tokens expired at midnight ET. Run 'start' command to re-authenticate.")
                return False
            
            # Check if renewal is needed
            if not self._needs_renewal(token_info):
                log.info("Tokens are still active, no renewal needed")
                return True
            
            log.info("Tokens are idle, attempting renewal...")
            
            try:
                config = self.environments[env]
                consumer_key = os.getenv(config['key_var'])
                consumer_secret = os.getenv(config['secret_var'])
                base_url = config['base_url']
                
                renew_url = f"{base_url}/oauth/renew_access_token"
                
                response = self._make_oauth_request('GET', renew_url, {},
                                                 consumer_key, consumer_secret,
                                                 token_info.oauth_token, token_info.oauth_token_secret)
                
                # Update token info
                token_info.last_renewed = datetime.now()
                token_info.last_used = datetime.now()
                self._save_tokens(env, token_info)
                
                # Update metrics
                metrics = self._load_metrics(env)
                metrics.renew_attempts += 1
                metrics.last_successful_call = datetime.now()
                metrics.consecutive_failures = 0
                self._save_metrics(env, metrics)
                
                log.info("✅ Tokens renewed successfully")
                return True
                
            except Exception as e:
                log.error(f"Token renewal failed: {e}")
                
                # Update metrics
                metrics = self._load_metrics(env)
                metrics.renew_attempts += 1
                metrics.renew_failures += 1
                metrics.consecutive_failures += 1
                self._save_metrics(env, metrics)
                
                return False
    
    def sign_request(self, env: Environment, method: str, url: str, params: Dict[str, str] = None) -> Dict[str, str]:
        """
        Sign a request with OAuth tokens
        
        Args:
            env: Environment
            method: HTTP method
            url: Request URL
            params: Request parameters
            
        Returns:
            Dictionary with Authorization header and other headers
        """
        if params is None:
            params = {}
        
        # Load tokens
        token_info = self._load_tokens(env)
        if not token_info:
            raise ValueError("No tokens found. Run 'start' command first.")
        
        # Check if midnight ET has passed
        if self._is_midnight_et_passed(token_info):
            raise ValueError("Tokens expired at midnight ET. Run 'start' command to re-authenticate.")
        
        # Check if renewal is needed
        if self._needs_renewal(token_info):
            log.info("Tokens are idle, attempting renewal...")
            if not self.renew_if_needed(env):
                raise ValueError("Failed to renew idle tokens")
            # Reload tokens after renewal
            token_info = self._load_tokens(env)
        
        # Load credentials
        config = self.environments[env]
        consumer_key = os.getenv(config['key_var'])
        consumer_secret = os.getenv(config['secret_var'])
        
        # OAuth parameters
        oauth_params = {
            'oauth_consumer_key': consumer_key,
            'oauth_nonce': self._generate_nonce(),
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': self._generate_timestamp(),
            'oauth_version': '1.0',
            'oauth_token': token_info.oauth_token
        }
        
        # Merge parameters
        all_params = {**oauth_params, **params}
        
        # Generate signature
        signature = self._generate_signature(method, url, all_params, consumer_secret, token_info.oauth_token_secret)
        all_params['oauth_signature'] = signature
        
        # Create Authorization header
        auth_header = "OAuth " + ", ".join([f'{k}="{urllib.parse.quote(str(v), safe="")}"' 
                                          for k, v in all_params.items() if k.startswith('oauth_')])
        
        # Update last used time
        token_info.last_used = datetime.now()
        self._save_tokens(env, token_info)
        
        # Update metrics
        metrics = self._load_metrics(env)
        metrics.last_successful_call = datetime.now()
        metrics.consecutive_failures = 0
        self._save_metrics(env, metrics)
        
        return {'Authorization': auth_header}
    
    def status(self, env: Environment) -> Dict[str, Any]:
        """
        Get comprehensive token status
        
        Args:
            env: Environment
            
        Returns:
            Dictionary with token status information
        """
        token_info = self._load_tokens(env)
        metrics = self._load_metrics(env)
        
        if not token_info:
            return {
                'environment': env.value,
                'status': TokenStatus.NOT_FOUND.value,
                'message': 'No tokens found. Run start() to authenticate.'
            }
        
        # Determine status
        if self._is_midnight_et_passed(token_info):
            status = TokenStatus.EXPIRED.value
            message = 'Tokens expired at midnight ET. Run start() to re-authenticate.'
        elif self._needs_renewal(token_info):
            status = TokenStatus.IDLE.value
            message = 'Tokens are idle (2+ hours). Will auto-renew on next request.'
        else:
            status = TokenStatus.ACTIVE.value
            message = 'Tokens are active and ready for use.'
        
        return {
            'environment': env.value,
            'status': status,
            'message': message,
            'created_at': token_info.created_at.isoformat(),
            'last_used': token_info.last_used.isoformat(),
            'last_renewed': token_info.last_renewed.isoformat() if token_info.last_renewed else None,
            'expires_at': token_info.expires_at.isoformat() if token_info.expires_at else None,
            'issued_et_date': token_info.issued_et_date,
            'metrics': {
                'renew_attempts': metrics.renew_attempts,
                'renew_failures': metrics.renew_failures,
                'consecutive_failures': metrics.consecutive_failures,
                'last_successful_call': metrics.last_successful_call.isoformat() if metrics.last_successful_call else None,
                'next_midnight_et': metrics.next_midnight_et.isoformat() if metrics.next_midnight_et else None
            }
        }
    
    def make_api_call(self, env: Environment, endpoint: str, method: str = 'GET', params: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Make authenticated API call with automatic token management
        
        Args:
            env: Environment
            endpoint: API endpoint (without base URL)
            method: HTTP method
            params: Request parameters
            
        Returns:
            API response data
        """
        config = self.environments[env]
        base_url = config['base_url']
        url = f"{base_url}{endpoint}"
        
        try:
            # Sign the request
            headers = self.sign_request(env, method, url, params)
            
            # Make the request
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=30)
            else:
                response = requests.post(url, headers=headers, json=params, timeout=30)
            
            response.raise_for_status()
            
            # Update metrics
            metrics = self._load_metrics(env)
            metrics.last_successful_call = datetime.now()
            metrics.consecutive_failures = 0
            self._save_metrics(env, metrics)
            
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                error_text = e.response.text
                if 'token_revoked' in error_text or 'token_inactive' in error_text:
                    log.warning("Token inactive, attempting renewal...")
                    if self.renew_if_needed(env):
                        # Retry the original call once
                        headers = self.sign_request(env, method, url, params)
                        if method.upper() == 'GET':
                            response = requests.get(url, headers=headers, params=params, timeout=30)
                        else:
                            response = requests.post(url, headers=headers, json=params, timeout=30)
                        response.raise_for_status()
                        return response.json()
            
            # Update metrics
            metrics = self._load_metrics(env)
            metrics.last_401_count += 1
            self._save_metrics(env, metrics)
            
            raise
        except Exception as e:
            log.error(f"API call failed: {e}")
            raise

# Global instance
_central_oauth_manager = None

def get_central_oauth_manager() -> CentralOAuthManager:
    """Get the central OAuth manager instance"""
    global _central_oauth_manager
    if _central_oauth_manager is None:
        _central_oauth_manager = CentralOAuthManager()
    return _central_oauth_manager

# Convenience functions for easy integration
def start_auth(env: str) -> bool:
    """Start authentication (convenience function)"""
    environment = Environment.SANDBOX if env.lower() == 'sandbox' else Environment.PRODUCTION
    return get_central_oauth_manager().start(environment)

def renew_if_needed(env: str) -> bool:
    """Renew tokens if needed (convenience function)"""
    environment = Environment.SANDBOX if env.lower() == 'sandbox' else Environment.PRODUCTION
    return get_central_oauth_manager().renew_if_needed(environment)

def sign_request(env: str, method: str, url: str, params: Dict[str, str] = None) -> Dict[str, str]:
    """Sign request (convenience function)"""
    environment = Environment.SANDBOX if env.lower() == 'sandbox' else Environment.PRODUCTION
    return get_central_oauth_manager().sign_request(environment, method, url, params)

def get_status(env: str) -> Dict[str, Any]:
    """Get status (convenience function)"""
    environment = Environment.SANDBOX if env.lower() == 'sandbox' else Environment.PRODUCTION
    return get_central_oauth_manager().status(environment)

def make_api_call(env: str, endpoint: str, method: str = 'GET', params: Dict[str, str] = None) -> Dict[str, Any]:
    """Make API call (convenience function)"""
    environment = Environment.SANDBOX if env.lower() == 'sandbox' else Environment.PRODUCTION
    return get_central_oauth_manager().make_api_call(environment, endpoint, method, params)

