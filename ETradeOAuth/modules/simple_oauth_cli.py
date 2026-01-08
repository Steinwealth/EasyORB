#!/usr/bin/env python3
"""
Simple OAuth CLI - No External Dependencies
==========================================

Simple CLI for OAuth operations using only standard library.
Perfect for systems with restricted package installation.

Usage:
    python simple_oauth_cli.py start sandbox        # After 12:00 AM ET
    python simple_oauth_cli.py start prod           # After 12:00 AM ET (when ready)
    python simple_oauth_cli.py test sandbox         # Before market open
    python simple_oauth_cli.py status               # Show status
"""

import sys
import os
import argparse
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
from datetime import datetime
from typing import Dict, Optional

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

def print_header(title: str):
    """Print formatted header"""
    print("\n" + "="*60)
    print(f"🔐 {title}")
    print("="*60)

def print_result(success: bool, message: str):
    """Print formatted result"""
    status = "✅ SUCCESS" if success else "❌ FAILED"
    print(f"{status}: {message}")

def load_config(env: str) -> Dict[str, str]:
    """Load configuration from environment variables"""
    if env.lower() == 'sandbox':
        return {
            'consumer_key': os.getenv('ETRADE_SANDBOX_KEY'),
            'consumer_secret': os.getenv('ETRADE_SANDBOX_SECRET'),
            'base_url': 'https://apisb.etrade.com',
            'token_file': 'tokens_sandbox.json'
        }
    else:
        return {
            'consumer_key': os.getenv('ETRADE_PROD_KEY'),
            'consumer_secret': os.getenv('ETRADE_PROD_SECRET'),
            'base_url': 'https://api.etrade.com',
            'token_file': 'tokens_prod.json'
        }

def generate_nonce() -> str:
    """Generate OAuth nonce"""
    return secrets.token_urlsafe(32)

def generate_timestamp() -> str:
    """Generate OAuth timestamp"""
    return str(int(time.time()))

def generate_signature(method: str, url: str, params: Dict[str, str], 
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

def make_oauth_request(method: str, url: str, params: Dict[str, str], 
                      consumer_key: str, consumer_secret: str,
                      oauth_token: Optional[str] = None, 
                      oauth_token_secret: str = "") -> Dict:
    """Make OAuth-signed HTTP request"""
    
    # OAuth parameters
    oauth_params = {
        'oauth_consumer_key': consumer_key,
        'oauth_nonce': generate_nonce(),
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': generate_timestamp(),
        'oauth_version': '1.0'
    }
    
    # Add token if available
    if oauth_token:
        oauth_params['oauth_token'] = oauth_token
    
    # Merge parameters
    all_params = {**oauth_params, **params}
    
    # Generate signature
    signature = generate_signature(method, url, all_params, consumer_secret, oauth_token_secret)
    all_params['oauth_signature'] = signature
    
    # Create Authorization header
    auth_header = "OAuth " + ", ".join([f'{k}="{urllib.parse.quote(str(v), safe="")}"' 
                                      for k, v in all_params.items() if k.startswith('oauth_')])
    
    # Make request
    req = urllib.request.Request(url, headers={'Authorization': auth_header})
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.headers.get_content_type() == 'application/json':
                return json.loads(response.read().decode('utf-8'))
            else:
                # Parse form-encoded response
                response_text = response.read().decode('utf-8')
                return dict(urllib.parse.parse_qsl(response_text))
    except urllib.error.HTTPError as e:
        error_response = e.read().decode('utf-8')
        log.error(f"HTTP Error {e.code}: {error_response}")
        raise
    except Exception as e:
        log.error(f"Request failed: {e}")
        raise

def save_tokens(env: str, oauth_token: str, oauth_token_secret: str) -> None:
    """Save tokens to file"""
    config = load_config(env)
    token_file = config['token_file']
    
    token_data = {
        'oauth_token': oauth_token,
        'oauth_token_secret': oauth_token_secret,
        'created_at': datetime.now().isoformat(),
        'last_used': datetime.now().isoformat()
    }
    
    with open(token_file, 'w') as f:
        json.dump(token_data, f, indent=2)
    
    log.info(f"Tokens saved to {token_file}")

def load_tokens(env: str) -> Optional[Dict]:
    """Load tokens from file"""
    config = load_config(env)
    token_file = config['token_file']
    
    if not os.path.exists(token_file):
        return None
    
    try:
        with open(token_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to load tokens from {token_file}: {e}")
        return None

def start_auth(env: str) -> bool:
    """
    Start authentication (run after 12:00 AM ET)
    
    Args:
        env: Environment ('sandbox' or 'prod')
        
    Returns:
        True if successful
    """
    print_header(f"START AUTHENTICATION - {env.upper()}")
    
    config = load_config(env)
    
    if not config['consumer_key'] or not config['consumer_secret']:
        print_result(False, f"Missing credentials for {env}")
        print(f"   Set {env.upper()}_KEY and {env.upper()}_SECRET environment variables")
        return False
    
    print(f"🔄 Starting 3-legged OAuth flow for {env}...")
    print("   This will open a browser for authorization.")
    
    try:
        base_url = config['base_url']
        
        # Step 1: Get request token
        log.info("Step 1: Getting request token...")
        request_url = f"{base_url}/oauth/request_token"
        params = {'oauth_callback': 'oob'}
        
        response = make_oauth_request('GET', request_url, params, 
                                   config['consumer_key'], config['consumer_secret'])
        
        if 'oauth_token' not in response:
            raise ValueError(f"Invalid request token response: {response}")
        
        request_token = response['oauth_token']
        request_token_secret = response['oauth_token_secret']
        
        log.info("✅ Request token obtained successfully")
        
        # Step 2: Get authorization URL
        log.info("Step 2: Getting authorization URL...")
        auth_url = f"https://us.etrade.com/e/t/etws/authorize?key={config['consumer_key']}&token={request_token}"
        
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
        
        response = make_oauth_request('GET', access_url, params,
                                   config['consumer_key'], config['consumer_secret'],
                                   request_token, request_token_secret)
        
        if 'oauth_token' not in response:
            raise ValueError(f"Invalid access token response: {response}")
        
        # Save tokens
        save_tokens(env, response['oauth_token'], response['oauth_token_secret'])
        
        print_result(True, f"{env.title()} authentication completed successfully")
        print(f"   Tokens are valid until next midnight ET")
        return True
        
    except Exception as e:
        print_result(False, f"{env.title()} authentication error: {e}")
        return False

def test_connection(env: str) -> bool:
    """
    Test API connection (run before market open)
    
    Args:
        env: Environment ('sandbox' or 'prod')
        
    Returns:
        True if successful
    """
    print_header(f"HEALTH CHECK - {env.upper()}")
    
    config = load_config(env)
    
    if not config['consumer_key'] or not config['consumer_secret']:
        print_result(False, f"Missing credentials for {env}")
        return False
    
    # Load tokens
    tokens = load_tokens(env)
    if not tokens:
        print_result(False, f"No tokens found for {env}. Run start command first.")
        return False
    
    print(f"🔍 Testing {env} API connection...")
    
    try:
        base_url = config['base_url']
        test_url = f"{base_url}/v1/accounts/list"
        
        response = make_oauth_request('GET', test_url, {},
                                   config['consumer_key'], config['consumer_secret'],
                                   tokens['oauth_token'], tokens['oauth_token_secret'])
        
        # Parse response
        accounts = response.get('AccountListResponse', {}).get('Accounts', {}).get('Account', [])
        print(f"   📊 Found {len(accounts)} account(s)")
        
        for i, account in enumerate(accounts):
            account_id = account.get('accountId', 'N/A')
            account_type = account.get('accountType', 'N/A')
            print(f"      Account {i+1}: {account_id} ({account_type})")
        
        # Update last used time
        tokens['last_used'] = datetime.now().isoformat()
        save_tokens(env, tokens['oauth_token'], tokens['oauth_token_secret'])
        
        print_result(True, f"{env.title()} health check passed - ready for trading")
        return True
        
    except Exception as e:
        print_result(False, f"{env.title()} health check failed: {e}")
        return False

def status_report() -> None:
    """Show comprehensive status report"""
    print_header("STATUS REPORT")
    
    current_time = datetime.now()
    print(f"⏰ Current Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Sandbox status
    print("\n📱 SANDBOX STATUS:")
    print("-" * 30)
    config = load_config('sandbox')
    if config['consumer_key']:
        tokens = load_tokens('sandbox')
        if tokens:
            print(f"Status: ✅ TOKENS FOUND")
            print(f"Created: {tokens['created_at']}")
            print(f"Last Used: {tokens['last_used']}")
        else:
            print(f"Status: ❌ NO TOKENS")
            print("Run: python simple_oauth_cli.py start sandbox")
    else:
        print("❌ Not configured (ETRADE_SANDBOX_KEY not set)")
    
    # Production status
    print("\n🏭 PRODUCTION STATUS:")
    print("-" * 30)
    config = load_config('prod')
    if config['consumer_key']:
        tokens = load_tokens('prod')
        if tokens:
            print(f"Status: ✅ TOKENS FOUND")
            print(f"Created: {tokens['created_at']}")
            print(f"Last Used: {tokens['last_used']}")
        else:
            print(f"Status: ❌ NO TOKENS")
            print("Run: python simple_oauth_cli.py start prod")
    else:
        print("❌ Not configured (ETRADE_PROD_KEY not set)")

def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description='Simple OAuth CLI - No External Dependencies',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Daily Cadence Examples:

  After 12:00 AM ET (≈ 9:00 PM PT):
    python simple_oauth_cli.py start sandbox        # Mint fresh sandbox tokens
    python simple_oauth_cli.py start prod           # Mint fresh production tokens (when ready)

  Before market open:
    python simple_oauth_cli.py test sandbox         # Health check sandbox
    python simple_oauth_cli.py test prod            # Health check production

  Status and monitoring:
    python simple_oauth_cli.py status               # Show comprehensive status report
        """
    )
    
    parser.add_argument('command', choices=['start', 'test', 'status'],
                       help='Command to execute')
    parser.add_argument('env', nargs='?', choices=['sandbox', 'prod'],
                       help='Environment (required for start and test commands)')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.command in ['start', 'test'] and not args.env:
        parser.error(f"Environment required for '{args.command}' command")
    
    try:
        if args.command == 'start':
            success = start_auth(args.env)
            return 0 if success else 1
            
        elif args.command == 'test':
            success = test_connection(args.env)
            return 0 if success else 1
            
        elif args.command == 'status':
            status_report()
            return 0
            
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        return 0
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())

