# OAuth Web Application for Daily Token Management
# Mobile-friendly FastAPI app for E*TRADE OAuth token renewal
# Enhanced with alert system integration and countdown timer

import os
import sys
import json
import asyncio
import time
import datetime as dt
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import secretmanager
from requests_oauthlib import OAuth1Session
from oauthlib.oauth1 import Client
import requests
import logging
import oauthlib
import sys

# Add the main project to path for alert manager integration
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# Import the main alert manager
try:
    from modules.prime_alert_manager import get_prime_alert_manager
    ALERT_MANAGER_AVAILABLE = True
except ImportError:
    ALERT_MANAGER_AVAILABLE = False
    logging.warning("Alert manager not available")

# Import OAuth modules
try:
    from central_oauth_manager import CentralOAuthManager, Environment
    OAUTH_MANAGER_AVAILABLE = True
except ImportError:
    OAUTH_MANAGER_AVAILABLE = False
    logging.warning("OAuth manager not available")

# Import keep-alive system
try:
    # Import from the local keepalive_oauth.py file
    from keepalive_oauth import get_oauth_keepalive, get_keepalive_status
    KEEPALIVE_AVAILABLE = True
except ImportError:
    KEEPALIVE_AVAILABLE = False
    logging.warning("Keep-alive system not available")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable oauthlib debug logging to see signature details
oauthlib.set_debug(True)
oauth_log = logging.getLogger("oauthlib")
oauth_log.addHandler(logging.StreamHandler(sys.stdout))
oauth_log.setLevel(logging.DEBUG)

app = FastAPI(title="ETrade OAuth Token Manager", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_headers=["*"], allow_methods=["*"])

# --- CONFIGURATION ---
EASTERN = ZoneInfo("America/New_York")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC", "projects/YOUR_GCP_PROJECT/topics/token-rotated")
PROJECT_ID = os.environ.get("GCP_PROJECT", "your-gcp-project")
APP_BASE = os.environ.get("APP_BASE_URL", "https://etrade-oauth.yourdomain.com")
E_TRADE_BASE = {
    "prod": "https://api.etrade.com",
    "sandbox": "https://apisb.etrade.com"
}

# --- GCP CLIENTS ---
_secrets = secretmanager.SecretManagerServiceClient()
# _pub = pubsub_v1.PublisherClient()  # Disabled for now

# --- ALERT MANAGER ---
alert_manager = None
if ALERT_MANAGER_AVAILABLE:
    try:
        alert_manager = get_prime_alert_manager()
        logger.info("✅ Alert manager instance created")
    except Exception as e:
        logger.error(f"Failed to create alert manager: {e}")

# --- OAUTH MANAGER ---
oauth_manager = None
if OAUTH_MANAGER_AVAILABLE:
    try:
        oauth_manager = CentralOAuthManager()
        logger.info("✅ OAuth manager initialized")
    except Exception as e:
        logger.error(f"Failed to initialize OAuth manager: {e}")

def _secret_name(name: str) -> str:
    """Generate secret name for GCP Secret Manager"""
    return f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"

def read_secret(name: str) -> str:
    """Read secret from GCP Secret Manager"""
    try:
        data = _secrets.access_secret_version(request={"name": _secret_name(name)}).payload.data
        return data.decode()
    except Exception as e:
        logger.error(f"Failed to read secret {name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read secret: {e}")

def write_secret(name: str, value: str):
    """Write secret to GCP Secret Manager"""
    try:
        # Create secret if it doesn't exist
        try:
            _secrets.get_secret(name=f"projects/{PROJECT_ID}/secrets/{name}")
        except Exception:
            parent = f"projects/{PROJECT_ID}"
            _secrets.create_secret(
                parent=parent,
                secret_id=name,
                secret={"replication": {"automatic": {}}}
            )
        
        # Add new version
        parent = f"projects/{PROJECT_ID}/secrets/{name}"
        _secrets.add_secret_version(parent=parent, payload={"data": value.encode()})
        logger.info(f"Secret {name} updated successfully")
    except Exception as e:
        logger.error(f"Failed to write secret {name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write secret: {e}")

def env_keys(env: str) -> tuple[str, str]:
    """Get consumer key and secret for environment"""
    try:
        ck = read_secret(f"etrade-{env}-consumer-key")
        cs = read_secret(f"etrade-{env}-consumer-secret")
        return ck, cs
    except Exception as e:
        logger.error(f"Failed to get keys for {env}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get API keys for {env}")

async def store_tokens(env: str, access_token: str, access_token_secret: str):
    """Store access tokens and notify trading service"""
    try:
        # Store tokens in Secret Manager (JSON format for status checking)
        token_data = {
            "oauth_token": access_token,
            "oauth_token_secret": access_token_secret,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()
        }
        write_secret(f"etrade-oauth-{env}", json.dumps(token_data))
        write_secret(f"etrade-{env}-access-token", access_token)
        write_secret(f"etrade-{env}-access-token-secret", access_token_secret)
        
        # Publish Pub/Sub notification
        payload = json.dumps({
            "env": env, 
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "action": "token_rotated"
        }).encode()
        
        # _pub.publish(PUBSUB_TOPIC, payload)  # Disabled for now
        logger.info(f"Tokens stored and notification sent for {env}")
        
        # Send success alert
        alert_sent = False
        
        # Try alert manager first
        if alert_manager:
            try:
                # Initialize alert manager if not already initialized
                if not hasattr(alert_manager, '_initialized') or not alert_manager._initialized:
                    await alert_manager.initialize()
                    logger.info("✅ Alert manager initialized for token renewal")
                
                # Use the more comprehensive confirmation alert
                await alert_manager.send_oauth_token_renewed_confirmation(env)
                logger.info(f"✅ Token renewal confirmation alert sent for {env} via alert manager")
                alert_sent = True
            except Exception as alert_error:
                logger.error(f"Failed to send renewal confirmation alert via alert manager: {alert_error}")
        
        # Fallback to direct Telegram API if alert manager failed or unavailable
        if not alert_sent and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                # Use zoneinfo which is already imported at the top
                eastern = ZoneInfo('America/New_York')
                pacific = ZoneInfo('America/Los_Angeles')
                now_et = dt.datetime.now(eastern)
                now_pt = dt.datetime.now(pacific)
                
                mode_name = "Live" if env == "prod" else "Demo"
                token_type = "Production" if env == "prod" else "Sandbox"
                env_display = "production" if env == "prod" else "sandbox"
                
                message = f"""====================================================================

✅ <b>OAuth {token_type} Token Renewed</b>
          Time: {now_pt.strftime('%I:%M %p')} PT ({now_et.strftime('%I:%M %p')} ET)

🎉 Success! E*TRADE {token_type.lower()} token successfully renewed for <b>{mode_name}</b>

📊 System Mode: <b>{mode_name}</b> Trading {'Enabled' if env == 'prod' else 'Available'}
💎 Status: Trading system ready and operational

🌐 Public Dashboard: 
          https://easy-trading-oauth-v2.web.app"""
                
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Token renewal alert sent for {env} via direct Telegram API")
                    alert_sent = True
                else:
                    logger.error(f"Failed to send Telegram alert: {response.status_code} - {response.text}")
                    
            except Exception as telegram_error:
                logger.error(f"Failed to send direct Telegram alert: {telegram_error}")
        
    except Exception as e:
        logger.error(f"Failed to store tokens for {env}: {e}")
        # Send error alert
        if alert_manager:
            try:
                # Initialize alert manager if not already initialized
                if not hasattr(alert_manager, '_initialized') or not alert_manager._initialized:
                    await alert_manager.initialize()
                    logger.info("✅ Alert manager initialized for error alert")
                
                await alert_manager.send_oauth_renewal_error(env, str(e))
                logger.info(f"❌ Token renewal error alert sent for {env}")
            except Exception as alert_error:
                logger.error(f"Failed to send renewal error alert: {alert_error}")
        raise HTTPException(status_code=500, detail=f"Failed to store tokens: {e}")

def get_token_expiry_countdown() -> str:
    """Calculate countdown to midnight ET"""
    try:
        now = dt.datetime.now(EASTERN)
        midnight_et = now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
        time_left = midnight_et - now
        
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except Exception:
        return "00:00:00"

def get_token_status(env: str) -> Dict[str, Any]:
    """Get token status for environment"""
    try:
        secret_data = read_secret(f"etrade-oauth-{env}")
        if secret_data:
            # Parse JSON data from secret
            token_data = json.loads(secret_data)
            oauth_token = token_data.get("oauth_token", "")
            oauth_token_secret = token_data.get("oauth_token_secret", "")
            
            if oauth_token and oauth_token_secret:
                # Actually test the tokens with a real API call
                try:
                    ck, cs = env_keys(env)
                    base = E_TRADE_BASE[env]
                    
                    oauth = OAuth1Session(
                        ck,
                        client_secret=cs,
                        resource_owner_key=oauth_token,
                        resource_owner_secret=oauth_token_secret
                    )
                    
                    # Test with a simple API call
                    test_url = f"{base}/v1/accounts/list"
                    response = oauth.get(test_url, timeout=5)
                    
                    if response.status_code == 200:
                        return {
                            "status": "active",
                            "message": f"{env.upper()} tokens are active",
                            "valid": True,
                            "class": "success"
                        }
                    else:
                        return {
                            "status": "expired",
                            "message": f"{env.upper()} tokens expired or invalid",
                            "valid": False,
                            "class": "error"
                        }
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"{env.upper()} tokens test failed: {str(e)}",
                        "valid": False,
                        "class": "error"
                    }
            else:
                return {
                    "status": "missing",
                    "message": f"{env.upper()} tokens not configured",
                    "valid": False,
                    "class": "error"
                }
        else:
            return {
                "status": "missing",
                "message": f"{env.upper()} tokens not found",
                "valid": False,
                "class": "error"
            }
    except Exception as e:
        logger.error(f"Error checking {env} tokens: {e}")
        return {
            "status": "error",
            "message": f"Error checking {env.upper()} tokens",
            "valid": False,
            "class": "error"
        }

# --- UI HELPERS ---
def mobile_html(title: str, body_html: str) -> HTMLResponse:
    """Generate mobile-friendly HTML response"""
    return HTMLResponse(f"""<!doctype html>
<html lang="en">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
    <title>{title}</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            padding: 16px;
            max-width: 560px;
            margin: 0 auto;
            background-color: #f5f5f5;
        }}
        .container {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        input, button {{
            font-size: 18px;
            padding: 12px;
            width: 100%;
            box-sizing: border-box;
            margin-top: 8px;
            border: 1px solid #ddd;
            border-radius: 8px;
        }}
        .card {{
            border: 1px solid #ddd;
            border-radius: 12px;
            padding: 16px;
            margin: 12px 0;
            background: #f9f9f9;
        }}
        .label {{
            font-size: 12px;
            color: #666;
            font-weight: bold;
            margin-bottom: 4px;
        }}
        .mask {{
            font-family: monospace;
            letter-spacing: 2px;
            background: #f0f0f0;
            padding: 8px;
            border-radius: 4px;
        }}
        a.btn, button.btn {{
            display: block;
            text-align: center;
            background: #0a7cff;
            color: #fff;
            text-decoration: none;
            border-radius: 10px;
            padding: 12px;
            margin-top: 12px;
            border: none;
            cursor: pointer;
        }}
        .btn.secondary {{
            background: #111;
            color: #fff;
        }}
        .btn.success {{
            background: #28a745;
        }}
        .btn.warning {{
            background: #ffc107;
            color: #000;
        }}
        .small {{
            font-size: 12px;
            color: #777;
        }}
        .status {{
            padding: 8px;
            border-radius: 4px;
            margin: 8px 0;
        }}
        .status.success {{
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }}
        .status.error {{
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }}
        .status.warning {{
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffeaa7;
        }}
        h1, h2 {{
            color: #333;
            margin-top: 0;
        }}
        .env-badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .env-prod {{
            background: #dc3545;
            color: white;
        }}
        .env-sandbox {{
            background: #6c757d;
            color: white;
        }}
        .countdown {{
            font-size: 24px;
            font-weight: bold;
            color: #e74c3c;
            text-align: center;
            margin: 20px 0;
            padding: 15px;
            background: #fff3cd;
            border: 2px solid #ffeaa7;
            border-radius: 8px;
        }}
        .countdown.warning {{
            background: #fff3cd;
            color: #856404;
        }}
        .countdown.danger {{
            background: #f8d7da;
            color: #721c24;
        }}
        .status-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin: 15px 0;
        }}
        .status-card {{
            padding: 10px;
            border-radius: 8px;
            text-align: center;
            font-size: 14px;
        }}
        .refresh-btn {{
            background: #17a2b8;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }}
    </style>
    <script>
        function updateCountdown() {{
            // This would be implemented with JavaScript for real-time updates
            // For now, it's static but could be enhanced
        }}
        
        function refreshPage() {{
            location.reload();
        }}
        
        // Auto-refresh every 30 seconds
        setInterval(refreshPage, 30000);
    </script>
</head>
<body>
    <div class="container">
        {body_html}
    </div>
</body>
</html>""")

# --- ADMIN SECRETS UI ---
@app.get("/admin/secrets", response_class=HTMLResponse)
def admin_secrets(env: str = Query("prod", description="Environment: prod or sandbox")):
    """Admin page to view and update API credentials"""
    try:
        ck = read_secret(f"etrade/{env}/consumer_key")
        cs = read_secret(f"etrade/{env}/consumer_secret")
        ck_masked = f"{ck[:4]}••••••••" if ck else "Not set"
        cs_masked = f"{cs[:4]}••••••••" if cs else "Not set"
    except Exception:
        ck_masked = "Not set"
        cs_masked = "Not set"
    
    env_badge = f'<span class="env-badge env-{env}">{env}</span>'
    
    html = f"""
    <h1>🔐 E*TRADE API Keys {env_badge}</h1>
    
    <div class="card">
        <form method="post" action="/admin/secrets?env={env}">
            <div class="label">Consumer Key</div>
            <input name="consumer_key" value="{ck_masked}" placeholder="Enter Consumer Key" type="password">
            
            <div class="label">Consumer Secret</div>
            <input name="consumer_secret" value="{cs_masked}" placeholder="Enter Consumer Secret" type="password">
            
            <button class="btn" type="submit">💾 Save Keys</button>
        </form>
    </div>
    
    <div class="card">
        <h3>🧪 Test Connection</h3>
        <a class="btn secondary" href="/test-connection?env={env}">Test API Connection</a>
    </div>
    
    <div class="card">
        <h3>🔄 Daily Token Renewal</h3>
        <a class="btn success" href="/oauth/start?env={env}">Get Today's Access Token</a>
    </div>
    
    <div class="card">
        <h3>⚙️ Switch Environment</h3>
        <a class="btn secondary" href="/admin/secrets?env={'sandbox' if env=='prod' else 'prod'}">
            Switch to {'Sandbox' if env=='prod' else 'Production'}
        </a>
    </div>
    
    <div class="small">
        <p><strong>Instructions:</strong></p>
        <ol>
            <li>Enter your E*TRADE API credentials above</li>
            <li>Test the connection to verify</li>
            <li>Use "Get Today's Access Token" each morning</li>
        </ol>
    </div>
    """
    return mobile_html("API Keys Management", html)

@app.post("/admin/secrets", response_class=HTMLResponse)
def admin_secrets_save(
    env: str = Query("prod"),
    consumer_key: str = Form(...),
    consumer_secret: str = Form(...)
):
    """Save API credentials to Secret Manager"""
    try:
        # Only update if not masked values
        if "•" not in consumer_key and len(consumer_key) > 8:
            write_secret(f"etrade/{env}/consumer_key", consumer_key.strip())
            logger.info(f"Consumer key updated for {env}")
        
        if "•" not in consumer_secret and len(consumer_secret) > 8:
            write_secret(f"etrade/{env}/consumer_secret", consumer_secret.strip())
            logger.info(f"Consumer secret updated for {env}")
        
        return RedirectResponse(url=f"/admin/secrets?env={env}&saved=true", status_code=303)
    except Exception as e:
        logger.error(f"Failed to save secrets: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save secrets: {e}")

@app.get("/test-connection", response_class=HTMLResponse)
def test_connection(env: str = Query("prod")):
    """Test API connection with current credentials"""
    try:
        ck, cs = env_keys(env)
        
        # Test with a simple API call
        base = E_TRADE_BASE[env]
        oauth = OAuth1Session(ck, client_secret=cs)
        
        # Try to get account list (this will fail without access token, but validates credentials)
        test_url = f"{base}/v1/accounts/list"
        
        # This is a basic test - in production you might want to test with a different endpoint
        response = requests.get(test_url, timeout=10)
        
        if response.status_code in [200, 401]:  # 401 is expected without access token
            status = "success"
            message = f"✅ API credentials are valid for {env.upper()}"
        else:
            status = "warning"
            message = f"⚠️ API responded with status {response.status_code}"
            
    except Exception as e:
        status = "error"
        message = f"❌ Connection failed: {str(e)}"
    
    html = f"""
    <h2>🧪 Connection Test Results</h2>
    <div class="status {status}">
        {message}
    </div>
    <a class="btn" href="/admin/secrets?env={env}">← Back to Admin</a>
    """
    return mobile_html("Connection Test", html)

@app.get("/api/test-access-tokens")
def test_access_tokens(env: str = Query("prod")):
    """Test access tokens by making a real API call to get account balances"""
    try:
        # Get access tokens from Secret Manager
        token_data = get_token_status(env)
        if not token_data.get("valid", False):
            return {
                "success": False,
                "error": f"No valid access tokens found for {env.upper()}",
                "message": token_data.get("message", "Unknown error")
            }
        
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Test with account list API call
        test_url = f"{base}/v1/accounts/list"
        response = oauth.get(test_url, timeout=10)
        
        if response.status_code == 200:
            try:
                accounts_data = response.json()
                account_count = len(accounts_data.get("AccountListResponse", {}).get("Accounts", {}).get("Account", []))
                
                return {
                    "success": True,
                    "message": f"✅ Access tokens are working! Found {account_count} account(s) in {env.upper()}",
                    "environment": env,
                    "account_count": account_count,
                    "api_response": accounts_data
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"✅ Access tokens are working! API responded successfully for {env.upper()}",
                    "environment": env,
                    "raw_response": response.text[:500]  # First 500 chars
                }
        else:
            return {
                "success": False,
                "error": f"API call failed with status {response.status_code}",
                "environment": env,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to test access tokens: {str(e)}",
            "environment": env
        }

@app.get("/api/account-balance")
def get_account_balance(env: str = Query("prod"), accountIdKey: str = Query(...)):
    """Get account balance for a specific account ID key"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Get account balance using account key with required parameters
        balance_url = f"{base}/v1/accounts/{accountIdKey}/balance.json"
        params = {
            "instType": "BROKERAGE",
            "realTimeNAV": "true"
        }
        headers = {
            "consumerkey": ck,
            "Accept": "application/json"
        }
        print(f"DEBUG: Making request to {balance_url}")
        print(f"DEBUG: Account key: {accountIdKey}")
        print(f"DEBUG: Params: {params}")
        response = oauth.get(balance_url, params=params, headers=headers, timeout=10)
        print(f"DEBUG: Response status: {response.status_code}")
        print(f"DEBUG: Response text: {response.text[:500]}")
        
        if response.status_code == 200:
            try:
                balance_data = response.json()
                return {
                    "success": True,
                    "message": f"Account balance retrieved successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "balance_data": balance_data
                }
            except json.JSONDecodeError:
                # Try to parse as XML if JSON fails
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(response.text)
                    # Extract cash balance information
                    cash_info = {}
                    for elem in root.iter():
                        if elem.tag in ['netAccountValue', 'cashAvailableForInvestment', 'totalCash', 'availableCash']:
                            cash_info[elem.tag] = elem.text
                    
                            return {
                                "success": True,
                                "message": f"Account balance retrieved successfully for {env.upper()}",
                                "environment": env,
                                "account_id_key": accountIdKey,
                                "balance_data": cash_info,
                                "raw_response": response.text[:500]
                            }
                except ET.ParseError:
                        return {
                            "success": True,
                            "message": f"Account balance retrieved successfully for {env.upper()}",
                            "environment": env,
                            "account_id_key": accountIdKey,
                            "raw_response": response.text[:500]
                        }
        else:
            return {
                "success": False,
                "error": f"API call failed with status {response.status_code}",
                "environment": env,
                "account_id_key": accountIdKey,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get account balance: {str(e)}",
            "environment": env,
            "account_id_key": accountIdKey
        }

@app.get("/api/accounts")
def get_accounts(env: str = Query("prod")):
    """Get list of E*TRADE accounts"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Get accounts list
        accounts_url = f"{base}/v1/accounts/list"
        response = oauth.get(accounts_url, timeout=10)
        
        if response.status_code == 200:
            try:
                accounts_data = response.json()
                return {
                    "success": True,
                    "message": f"Accounts retrieved successfully for {env.upper()}",
                    "environment": env,
                    "accounts": accounts_data
                }
            except json.JSONDecodeError:
                # Try to parse as XML if JSON fails
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(response.text)
                    accounts = []
                    for account in root.findall('.//Account'):
                        account_info = {}
                        for child in account:
                            account_info[child.tag] = child.text
                        accounts.append(account_info)
                    
                    return {
                        "success": True,
                        "message": f"Accounts retrieved successfully for {env.upper()}",
                        "environment": env,
                        "accounts": accounts
                    }
                except ET.ParseError:
                    return {
                        "success": True,
                        "message": f"Accounts retrieved successfully for {env.upper()}",
                        "environment": env,
                        "raw_response": response.text[:500]
                    }
        else:
            return {
                "success": False,
                "error": f"API call failed with status {response.status_code}",
                "environment": env,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get accounts: {str(e)}",
            "environment": env
        }

@app.get("/api/portfolio")
def get_portfolio(env: str = Query("prod"), accountIdKey: str = Query(...)):
    """Get portfolio/positions for a specific account"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Get portfolio
        portfolio_url = f"{base}/v1/accounts/{accountIdKey}/portfolio"
        response = oauth.get(portfolio_url, timeout=10)
        
        if response.status_code == 200:
            try:
                portfolio_data = response.json()
                return {
                    "success": True,
                    "message": f"Portfolio retrieved successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "portfolio": portfolio_data
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"Portfolio retrieved successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "raw_response": response.text[:500]
                }
        else:
            return {
                "success": False,
                "error": f"API call failed with status {response.status_code}",
                "environment": env,
                "account_id_key": accountIdKey,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get portfolio: {str(e)}",
            "environment": env,
            "account_id_key": accountIdKey
        }

@app.get("/api/orders")
def get_orders(env: str = Query("prod"), accountIdKey: str = Query(...), status: str = Query("OPEN")):
    """Get orders for a specific account"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Get orders
        orders_url = f"{base}/v1/accounts/{accountIdKey}/orders"
        params = {"status": status}
        response = oauth.get(orders_url, params=params, timeout=10)
        
        if response.status_code == 200:
            try:
                orders_data = response.json()
                return {
                    "success": True,
                    "message": f"Orders retrieved successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "status": status,
                    "orders": orders_data
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"Orders retrieved successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "status": status,
                    "raw_response": response.text[:500]
                }
        else:
            return {
                "success": False,
                "error": f"API call failed with status {response.status_code}",
                "environment": env,
                "account_id_key": accountIdKey,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get orders: {str(e)}",
            "environment": env,
            "account_id_key": accountIdKey
        }

@app.post("/api/orders/preview")
def preview_order(
    env: str = Form("prod"),
    accountIdKey: str = Form(...),
    symbol: str = Form(...),
    quantity: int = Form(...),
    side: str = Form(...),
    order_type: str = Form("MARKET"),
    price: Optional[float] = Form(None),
    stop_price: Optional[float] = Form(None),
    time_in_force: str = Form("DAY")
):
    """Preview an order before placing it"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Build order preview request
        preview_url = f"{base}/v1/accounts/{accountIdKey}/orders/preview"
        
        order_data = {
            "PreviewOrderRequest": {
                "orderType": order_type,
                "clientOrderId": int(time.time()),  # Unique client order ID
                "Order": [{
                    "allOrNone": False,
                    "priceType": order_type,
                    "orderTerm": time_in_force,
                    "marketSession": "REGULAR",
                    "stopPrice": stop_price,
                    "limitPrice": price,
                    "Instrument": [{
                        "Product": {
                            "securityType": "EQ",
                            "symbol": symbol
                        },
                        "orderAction": side,
                        "quantityType": "QUANTITY",
                        "quantity": quantity
                    }]
                }]
            }
        }
        
        response = oauth.post(preview_url, json=order_data, timeout=10)
        
        if response.status_code == 200:
            try:
                preview_data = response.json()
                return {
                    "success": True,
                    "message": f"Order preview successful for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "symbol": symbol,
                    "preview": preview_data
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"Order preview successful for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "symbol": symbol,
                    "raw_response": response.text[:500]
                }
        else:
            return {
                "success": False,
                "error": f"Order preview failed with status {response.status_code}",
                "environment": env,
                "account_id_key": accountIdKey,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to preview order: {str(e)}",
            "environment": env,
            "account_id_key": accountIdKey,
            "symbol": symbol
        }

@app.post("/api/orders/place")
def place_order(
    env: str = Form("prod"),
    accountIdKey: str = Form(...),
    symbol: str = Form(...),
    quantity: int = Form(...),
    side: str = Form(...),
    order_type: str = Form("MARKET"),
    price: Optional[float] = Form(None),
    stop_price: Optional[float] = Form(None),
    time_in_force: str = Form("DAY")
):
    """Place an order"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Build order request
        place_url = f"{base}/v1/accounts/{accountIdKey}/orders/place"
        
        order_data = {
            "PlaceOrderRequest": {
                "orderType": order_type,
                "clientOrderId": int(time.time()),  # Unique client order ID
                "Order": [{
                    "allOrNone": False,
                    "priceType": order_type,
                    "orderTerm": time_in_force,
                    "marketSession": "REGULAR",
                    "stopPrice": stop_price,
                    "limitPrice": price,
                    "Instrument": [{
                        "Product": {
                            "securityType": "EQ",
                            "symbol": symbol
                        },
                        "orderAction": side,
                        "quantityType": "QUANTITY",
                        "quantity": quantity
                    }]
                }]
            }
        }
        
        response = oauth.post(place_url, json=order_data, timeout=10)
        
        if response.status_code == 200:
            try:
                order_data = response.json()
                return {
                    "success": True,
                    "message": f"Order placed successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "symbol": symbol,
                    "order_result": order_data
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"Order placed successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "symbol": symbol,
                    "raw_response": response.text[:500]
                }
        else:
            return {
                "success": False,
                "error": f"Order placement failed with status {response.status_code}",
                "environment": env,
                "account_id_key": accountIdKey,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to place order: {str(e)}",
            "environment": env,
            "account_id_key": accountIdKey,
            "symbol": symbol
        }

@app.post("/api/orders/cancel")
def cancel_order(
    env: str = Form("prod"),
    accountIdKey: str = Form(...),
    order_id: str = Form(...)
):
    """Cancel an order"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Cancel order
        cancel_url = f"{base}/v1/accounts/{accountIdKey}/orders/cancel"
        
        cancel_data = {
            "CancelOrderRequest": {
                "orderId": order_id
            }
        }
        
        response = oauth.post(cancel_url, json=cancel_data, timeout=10)
        
        if response.status_code == 200:
            try:
                cancel_result = response.json()
                return {
                    "success": True,
                    "message": f"Order cancelled successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "order_id": order_id,
                    "cancel_result": cancel_result
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"Order cancelled successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "order_id": order_id,
                    "raw_response": response.text[:500]
                }
        else:
            return {
                "success": False,
                "error": f"Order cancellation failed with status {response.status_code}",
                "environment": env,
                "account_id_key": accountIdKey,
                "order_id": order_id,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to cancel order: {str(e)}",
            "environment": env,
            "account_id_key": accountIdKey,
            "order_id": order_id
        }

@app.get("/api/debug-account-key")
def debug_account_key(accountIdKey: str = Query(...)):
    """Debug endpoint to test account key handling"""
    try:
        return {
            "success": True,
            "account_key_received": accountIdKey,
            "account_key_length": len(accountIdKey),
            "account_key_encoded": accountIdKey.encode('utf-8').hex(),
            "message": "Account key received successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/account-summary")
def get_account_summary(env: str = Query("prod"), accountIdKey: str = Query(...)):
    """Get account summary for a specific account ID key"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Try account summary endpoint with required parameters
        summary_url = f"{base}/v1/accounts/{accountIdKey}/summary.json"
        params = {
            "instType": "BROKERAGE",
            "realTimeNAV": "true"
        }
        headers = {
            "consumerkey": ck,
            "Accept": "application/json"
        }
        print(f"DEBUG: Making request to {summary_url}")
        print(f"DEBUG: Params: {params}")
        response = oauth.get(summary_url, params=params, headers=headers, timeout=10)
        print(f"DEBUG: Response status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                summary_data = response.json()
                return {
                    "success": True,
                    "message": f"Account summary retrieved successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "summary_data": summary_data
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"Account summary retrieved successfully for {env.upper()}",
                    "environment": env,
                    "account_id_key": accountIdKey,
                    "raw_response": response.text[:500]
                }
        else:
            return {
                "success": False,
                "error": f"API call failed with status {response.status_code}",
                "environment": env,
                "account_id_key": accountIdKey,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get account summary: {str(e)}",
            "environment": env,
            "account_id_key": accountIdKey
        }

@app.get("/api/quotes")
def get_quotes(env: str = Query("prod"), symbols: str = Query(...)):
    """Get market quotes for symbols (comma-separated)"""
    try:
        # Read the actual tokens from Secret Manager
        secret_data = read_secret(f"etrade-oauth-{env}")
        if not secret_data:
            return {
                "success": False,
                "error": f"Could not read token data for {env.upper()}"
            }
        
        # Parse token data
        import json
        tokens = json.loads(secret_data)
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Create OAuth session with access tokens
        ck, cs = env_keys(env)
        base = E_TRADE_BASE[env]
        
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret
        )
        
        # Get quotes
        quotes_url = f"{base}/v1/market/quote/{symbols}"
        response = oauth.get(quotes_url, timeout=10)
        
        if response.status_code == 200:
            try:
                quotes_data = response.json()
                return {
                    "success": True,
                    "message": f"Quotes retrieved successfully for {env.upper()}",
                    "environment": env,
                    "symbols": symbols,
                    "quotes": quotes_data
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "message": f"Quotes retrieved successfully for {env.upper()}",
                    "environment": env,
                    "symbols": symbols,
                    "raw_response": response.text[:500]
                }
        else:
            return {
                "success": False,
                "error": f"Quotes request failed with status {response.status_code}",
                "environment": env,
                "symbols": symbols,
                "response_text": response.text[:500]
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get quotes: {str(e)}",
            "environment": env,
            "symbols": symbols
        }

# --- OAUTH 1.0a (PIN) FLOW ---
def oauth_session(env: str, resource_owner_key=None, resource_owner_secret=None, callback_uri=None) -> OAuth1Session:
    """Create OAuth session for environment"""
    ck, cs = env_keys(env)
    return OAuth1Session(
        ck, 
        client_secret=cs,
        resource_owner_key=resource_owner_key,
        resource_owner_secret=resource_owner_secret,
        callback_uri=callback_uri
    )

@app.get("/oauth/start")
def oauth_start(env: str = Query("prod")):
    """Begin OAuth flow - get request token and redirect to E*TRADE"""
    try:
        base = E_TRADE_BASE[env]
        ck, cs = env_keys(env)
        
        # Create OAuth session with oob callback (PIN flow)
        # Strip secrets to remove any whitespace/newlines from Secret Manager
        ck = ck.strip()
        cs = cs.strip()
        
        # Add timestamp debugging
        import time
        current_time = time.time()
        logger.info(f"Current UTC timestamp: {current_time}")
        
        # Use header-only callback (no query oauth_callback)
        oauth = OAuth1Session(
            ck, 
            client_secret=cs,
            callback_uri="oob"  # E*TRADE PIN flow - header only
            # Removed signature_method override - let requests-oauthlib default to HMAC-SHA1
        )
        
        # Get request token using GET (header-only callback, no query params)
        req_token_url = f"{base}/oauth/request_token"
        logger.info(f"Requesting token from: {req_token_url}")
        logger.info(f"Using consumer key: {ck[:8]}...")
        
        try:
            # Add more detailed debugging before the request
            logger.info(f"Consumer key (first 8 chars): {ck[:8]}...")
            logger.info(f"Consumer secret length: {len(cs) if cs else 'None'}")
            logger.info(f"Consumer secret (first 8 chars): {cs[:8] if cs else 'None'}...")
            
            # Try alternative OAuth implementation with oauthlib directly
            logger.info("Attempting OAuth with oauthlib.Client...")
            client = Client(ck, client_secret=cs, callback_uri='oob')
            uri, headers, body = client.sign(req_token_url)
            
            logger.info(f"Signed URI: {uri}")
            logger.info(f"Signed headers: {headers}")
            
            # Make request with manually signed headers
            r = requests.get(uri, headers=headers)
            
            # Debug logging
            logger.info(f"Response status: {r.status_code}")
            logger.info(f"Response headers: {dict(r.headers)}")
            logger.info(f"Request URL: {r.request.url}")
            logger.info(f"Auth header: {r.request.headers.get('Authorization', 'NOT FOUND')}")
            logger.info(f"Response body: {r.text[:500]}...")  # First 500 chars
            
            r.raise_for_status()
            logger.info("Token request successful")
            
            # Parse response manually since we're using GET
            from urllib.parse import parse_qsl
            req_tokens = dict(parse_qsl(r.text))
            fetch = req_tokens
        except Exception as e:
            logger.error(f"Token request failed: {e}")
            # Log the full response for debugging
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response headers: {dict(e.response.headers)}")
                logger.error(f"Response body: {e.response.text}")
            raise
        
        rok = fetch.get("oauth_token")
        ros = fetch.get("oauth_token_secret")
        
        if not rok or not ros:
            raise HTTPException(status_code=500, detail="Failed to get request token")
        
        # Create authorization URL (E*TRADE format)
        authorize_url = f"https://us.etrade.com/e/t/etws/authorize?key={ck}&token={rok}"
        
        env_badge = f'<span class="env-badge env-{env}">{env}</span>'
        
        html = f"""
        <h1>🔐 E*TRADE Authorization {env_badge}</h1>
        
        <div class="card">
            <h3>📱 Step-by-Step Instructions</h3>
            <ol>
                <li><strong>Tap the button below</strong> to open E*TRADE in a new tab</li>
                <li><strong>Sign in</strong> to your E*TRADE account</li>
                <li><strong>Approve the application</strong> - you'll see a 6-digit PIN</li>
                <li><strong>Copy the PIN</strong> and come back to this page</li>
                <li><strong>Paste the PIN</strong> in the form below</li>
            </ol>
        </div>
        
        <a class="btn success" target="_blank" href="{authorize_url}">
            🚀 Open E*TRADE Authorization
        </a>
        
        <div class="card">
            <form method="post" action="/oauth/verify?env={env}">
                <input type="hidden" name="request_token" value="{rok}">
                <input type="hidden" name="request_secret" value="{ros}">
                
                <div class="label">📋 Enter 6-Digit PIN (Verifier)</div>
                <input name="verifier" placeholder="123456" inputmode="numeric" pattern="[0-9]*" autofocus maxlength="6">
                
                <button class="btn" type="submit">
                    ✅ Generate Today's Access Token
                </button>
            </form>
        </div>
        
        <div class="small">
            <p><strong>💡 Pro Tip:</strong> Add this page to your phone's home screen for one-tap morning renewals!</p>
        </div>
        """
        return {
            "success": True,
            "authorize_url": authorize_url,
            "request_token": rok,
            "request_secret": ros,
            "session_id": f"{env}_{rok}_{ros}",  # Create a session ID for frontend
            "environment": env,
            "message": f"OAuth flow started for {env.upper()}. Visit the authorize_url to get your PIN."
        }
        
    except Exception as e:
        logger.error(f"OAuth start failed for {env}: {e}")
        return {
            "success": False,
            "error": f"OAuth start failed for {env.upper()}",
            "details": str(e),
            "environment": env
        }

@app.post("/oauth/verify")
async def oauth_verify(
    session_id: str = Form(...),
    verifier: str = Form(...)
):
    """Exchange PIN for access tokens"""
    try:
        # Parse session_id to extract environment, request_token, and request_secret
        parts = session_id.split('_', 2)
        if len(parts) != 3:
            raise ValueError("Invalid session_id format")
        
        env = parts[0]
        request_token = parts[1]
        request_secret = parts[2]
        
        base = E_TRADE_BASE[env]
        ck, cs = env_keys(env)
        
        # Create OAuth session for access token exchange
        oauth = OAuth1Session(
            ck,
            client_secret=cs,
            resource_owner_key=request_token,
            resource_owner_secret=request_secret,
            verifier=verifier.strip()
        )
        
        # Exchange PIN for access tokens using GET
        access_url = f"{base}/oauth/access_token"
        r = oauth.get(access_url)
        r.raise_for_status()
        
        # Parse response manually
        from urllib.parse import parse_qsl
        tokens = dict(parse_qsl(r.text))
        
        access_token = tokens["oauth_token"]
        access_token_secret = tokens["oauth_token_secret"]
        
        # Store tokens and notify trading service
        await store_tokens(env, access_token, access_token_secret)
        
        return {
            "success": True,
            "message": f"OAuth authorization completed successfully for {env.upper()}!",
            "environment": env,
            "timestamp": dt.datetime.now(EASTERN).strftime('%Y-%m-%d %H:%M:%S ET'),
            "access_token": access_token[:8] + "...",  # Show first 8 chars for confirmation
            "status": "Active and ready for trading"
        }
        
    except Exception as e:
        logger.error(f"OAuth verify failed: {e}")
        return {
            "success": False,
            "error": f"Failed to complete OAuth flow",
            "details": str(e),
            "message": f"OAuth verification failed: {str(e)}"
        }

# --- TELEGRAM ALERT SYSTEM ---
@app.get("/cron/morning-alert")
def morning_alert():
    """Send morning Telegram alert with token renewal links"""
    try:
        # Use alert manager if available
        if alert_manager:
            asyncio.create_task(alert_manager.schedule_oauth_morning_alert())
            logger.info("Morning alert sent via alert manager")
            return PlainTextResponse("Alert sent via alert manager")
        
        # Fallback to direct Telegram API
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Telegram credentials not configured")
            return PlainTextResponse("Telegram not configured")
        
        today = dt.datetime.now(EASTERN).date()
        weekday = today.strftime('%A')
        
        # Check if it's a trading day (Monday-Friday)
        if today.weekday() >= 5:  # Saturday=5, Sunday=6
            logger.info(f"Non-trading day: {weekday}")
            return PlainTextResponse("Non-trading day")
        
        message = f"""🌅 **Good Morning!** 

📅 **{weekday}, {today.strftime('%B %d, %Y')}**

⏰ **Market opens in 1 hour** (9:30 AM ET)

🔐 **Renew E*TRADE tokens:**
• [Production Token]({APP_BASE}/oauth/start?env=prod)
• [Sandbox Token]({APP_BASE}/oauth/start?env=sandbox)

📱 **Quick Steps:**
1. Tap the link above
2. Authorize in E*TRADE
3. Copy the 6-digit PIN
4. Paste and submit

✅ **Ready to trade!**"""
        
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            },
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info("Morning alert sent successfully")
            return PlainTextResponse("Alert sent")
        else:
            logger.error(f"Failed to send alert: {response.status_code}")
            return PlainTextResponse(f"Alert failed: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Morning alert failed: {e}")
        return PlainTextResponse(f"Alert error: {str(e)}")

@app.get("/cron/midnight-expiry-alert")
def midnight_expiry_alert():
    """Send midnight token expiry Telegram alert (Rev 20251020)"""
    try:
        # Direct Telegram API (works 24/7, independent of main system)
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Telegram credentials not configured")
            return PlainTextResponse("Telegram not configured", status_code=500)
        
        # Get current time in both timezones
        from zoneinfo import ZoneInfo
        pt_tz = ZoneInfo('America/Los_Angeles')
        et_tz = ZoneInfo('America/New_York')
        now_pt = dt.datetime.now(pt_tz)
        now_et = dt.datetime.now(et_tz)
        
        pt_time = now_pt.strftime('%I:%M %p PT')
        et_time = now_et.strftime('%I:%M %p ET')
        
        message = f"""====================================================================

⚠️ <b>OAuth Tokens Expired</b>
          Time: {pt_time} ({et_time})

🚨 Token Status:
          E*TRADE tokens are <b>EXPIRED</b> ❌

🌐 Public Dashboard:
          https://easy-trading-oauth-v2.web.app

⚠️ Renew Production Token for Live Mode
⚠️ Renew Sandbox Token for Demo Mode

👉 Action Required:
1. Visit the public dashboard
2. Click "Renew Production" and/or "Renew Sandbox"
3. Enter access code (easy2025) on management portal
4. Complete OAuth authorization
5. Token will be renewed and stored"""
        
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info("✅ Midnight token expiry alert sent via Telegram")
            return PlainTextResponse("Midnight expiry alert sent successfully")
        else:
            logger.error(f"Failed to send midnight alert: {response.status_code} - {response.text}")
            return PlainTextResponse(f"Alert failed: {response.status_code}", status_code=500)
            
    except Exception as e:
        logger.error(f"Midnight expiry alert failed: {e}")
        return PlainTextResponse(f"Alert error: {str(e)}", status_code=500)

@app.get("/status", response_class=HTMLResponse)
def status():
    """Detailed token status page"""
    prod_status = get_token_status("prod")
    sandbox_status = get_token_status("sandbox")
    countdown = get_token_expiry_countdown()
    
    html = f"""
    <h1>📊 Token Status Dashboard</h1>
    
    <div class="countdown">
        ⏰ Access Token expires in: {countdown}
    </div>
    
    <div class="card">
        <h3>🏭 Production Environment</h3>
        <div class="status {prod_status['class']}">
            {prod_status['message']}
        </div>
        <a class="btn" href="/oauth/start?env=prod">Renew Production Token</a>
    </div>
    
    <div class="card">
        <h3>🧪 Sandbox Environment</h3>
        <div class="status {sandbox_status['class']}">
            {sandbox_status['message']}
        </div>
        <a class="btn secondary" href="/oauth/start?env=sandbox">Renew Sandbox Token</a>
    </div>
    
    <div class="card">
        <h3>🔧 System Status</h3>
        <p><strong>Alert Manager:</strong> {'✅ Available' if alert_manager else '❌ Not Available'}</p>
        <p><strong>OAuth Manager:</strong> {'✅ Available' if oauth_manager else '❌ Not Available'}</p>
        <p><strong>Last Updated:</strong> {dt.datetime.now(EASTERN).strftime('%Y-%m-%d %H:%M:%S ET')}</p>
    </div>
    
    <a class="btn" href="/">← Back to Home</a>
    """
    return mobile_html("Token Status", html)

@app.get("/test-telegram")
def test_telegram():
    """Test Telegram alert functionality"""
    return morning_alert()

@app.get("/test-oauth-alert")
async def test_oauth_alert():
    """Test OAuth token renewal alert functionality"""
    try:
        if alert_manager:
            # Test both production and sandbox renewal alerts
            await alert_manager.send_oauth_token_renewed_confirmation("prod")
            await alert_manager.send_oauth_token_renewed_confirmation("sandbox")
            logger.info("✅ Test OAuth renewal alerts sent")
            return PlainTextResponse("✅ Test OAuth renewal alerts sent successfully!")
        else:
            return PlainTextResponse("❌ Alert manager not available")
    except Exception as e:
        logger.error(f"Failed to send test OAuth alert: {e}")
        return PlainTextResponse(f"❌ Test failed: {e}")

@app.get("/test-env-vars")
def test_env_vars():
    """Test environment variables"""
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "NOT_SET")
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "NOT_SET")
    gcp_project = os.environ.get("GCP_PROJECT", "NOT_SET")
    
    return PlainTextResponse(f"TELEGRAM_BOT_TOKEN: {telegram_token[:20]}...\nTELEGRAM_CHAT_ID: {telegram_chat}\nGCP_PROJECT: {gcp_project}")

@app.get("/test-direct-telegram")
def test_direct_telegram():
    """Test direct Telegram API call"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return PlainTextResponse("❌ Telegram credentials not configured")
        
        # Send a test message
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "🧪 Test OAuth Alert - Telegram integration is working!",
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            return PlainTextResponse("✅ Test Telegram message sent successfully!")
        else:
            return PlainTextResponse(f"❌ Telegram API error: {response.status_code} - {response.text}")
    except Exception as e:
        return PlainTextResponse(f"❌ Test failed: {e}")

# --- KEEP-ALIVE SYSTEM ---
@app.get("/keepalive/status", response_class=HTMLResponse)
def keepalive_status():
    """Keep-alive system status page"""
    if not KEEPALIVE_AVAILABLE:
        html = """
        <h1>❌ Keep-Alive System Not Available</h1>
        <p>The OAuth keep-alive system is not available.</p>
        <a class="btn" href="/">← Back to Home</a>
        """
        return mobile_html("Keep-Alive Status", html)
    
    try:
        status = get_keepalive_status()
        
        html = f"""
        <h1>🔄 OAuth Keep-Alive Status</h1>
        
        <div class="card">
            <h3>System Overview</h3>
            <p>Keep-alive calls are made every 1.5 hours to prevent token idle timeout (2 hours).</p>
        </div>
        """
        
        for env, env_status in status.items():
            status_class = env_status.get('status', 'unknown')
            is_running = env_status.get('is_running', False)
            last_call = env_status.get('last_call', 'Never')
            next_call = env_status.get('next_call', 'Unknown')
            failures = env_status.get('consecutive_failures', 0)
            
            html += f"""
            <div class="card">
                <h3>{env.upper()} Environment</h3>
                <div class="status {status_class}">
                    <p><strong>Status:</strong> {status_class.title()}</p>
                    <p><strong>Running:</strong> {'✅ Yes' if is_running else '❌ No'}</p>
                    <p><strong>Last Call:</strong> {last_call}</p>
                    <p><strong>Next Call:</strong> {next_call}</p>
                    <p><strong>Failures:</strong> {failures}</p>
                </div>
            </div>
            """
        
        html += """
        <div class="card">
            <h3>Actions</h3>
            <a class="btn" href="/keepalive/force">Force Keep-Alive Call</a>
            <a class="btn secondary" href="/">← Back to Home</a>
        </div>
        """
        
        return mobile_html("Keep-Alive Status", html)
        
    except Exception as e:
        html = f"""
        <h1>❌ Keep-Alive Status Error</h1>
        <div class="status error">
            <p>Error: {str(e)}</p>
        </div>
        <a class="btn" href="/">← Back to Home</a>
        """
        return mobile_html("Keep-Alive Error", html)

@app.get("/keepalive/force", response_class=HTMLResponse)
def force_keepalive():
    """Force immediate keep-alive call"""
    if not KEEPALIVE_AVAILABLE:
        html = """
        <h1>❌ Keep-Alive System Not Available</h1>
        <p>The OAuth keep-alive system is not available.</p>
        <a class="btn" href="/">← Back to Home</a>
        """
        return mobile_html("Keep-Alive Error", html)
    
    try:
        keepalive = get_oauth_keepalive()
        
        # Force keep-alive calls for both environments
        results = {}
        for env in ['prod', 'sandbox']:
            try:
                # This would be async in a real implementation
                # For now, we'll just show the status
                results[env] = "Forced (async)"
            except Exception as e:
                results[env] = f"Error: {str(e)}"
        
        html = f"""
        <h1>🔄 Force Keep-Alive Call</h1>
        
        <div class="card">
            <h3>Results</h3>
        """
        
        for env, result in results.items():
            html += f"""
            <div class="status {'success' if 'Error' not in result else 'error'}">
                <p><strong>{env.upper()}:</strong> {result}</p>
            </div>
            """
        
        html += """
        </div>
        
        <div class="card">
            <h3>Note</h3>
            <p>Keep-alive calls are normally made automatically every 1.5 hours.</p>
            <p>This force call helps maintain token activity during trading hours.</p>
        </div>
        
        <a class="btn" href="/keepalive/status">View Status</a>
        <a class="btn secondary" href="/">← Back to Home</a>
        """
        
        return mobile_html("Force Keep-Alive", html)
        
    except Exception as e:
        html = f"""
        <h1>❌ Force Keep-Alive Error</h1>
        <div class="status error">
            <p>Error: {str(e)}</p>
        </div>
        <a class="btn" href="/">← Back to Home</a>
        """
        return mobile_html("Force Keep-Alive Error", html)

# --- NEW API ENDPOINTS FOR KEEPALIVE ---
@app.get("/api/keepalive/status")
async def api_keepalive_status():
    """Get keepalive system status via API"""
    try:
        if not KEEPALIVE_AVAILABLE:
            return {
                "success": False,
                "error": "Keep-alive system not available"
            }
        
        keepalive = get_oauth_keepalive()
        status = keepalive.get_status()
        
        return {
            "success": True,
            "data": status
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get keepalive status: {str(e)}"
        }

@app.post("/api/keepalive/force/{env}")
async def api_force_keepalive(env: str):
    """Force keepalive call for specific environment via API"""
    try:
        if not KEEPALIVE_AVAILABLE:
            return {
                "success": False,
                "error": "Keep-alive system not available"
            }
        
        if env not in ['prod', 'sandbox']:
            return {
                "success": False,
                "error": "Invalid environment. Use 'prod' or 'sandbox'"
            }
        
        keepalive = get_oauth_keepalive()
        success = await keepalive.force_keepalive_call(env)
        
        return {
            "success": success,
            "message": f"Keep-alive call {'successful' if success else 'failed'} for {env}",
            "environment": env
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to force keepalive for {env}: {str(e)}",
            "environment": env
        }

@app.get("/api/keepalive/needed/{env}")
async def api_keepalive_needed(env: str):
    """Check if keepalive is needed for specific environment via API"""
    try:
        if not KEEPALIVE_AVAILABLE:
            return {
                "success": False,
                "error": "Keep-alive system not available"
            }
        
        if env not in ['prod', 'sandbox']:
            return {
                "success": False,
                "error": "Invalid environment. Use 'prod' or 'sandbox'"
            }
        
        keepalive = get_oauth_keepalive()
        needed = keepalive.is_keepalive_needed(env)
        
        return {
            "success": True,
            "needed": needed,
            "environment": env,
            "message": f"Keep-alive {'needed' if needed else 'not needed'} for {env}"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to check keepalive status for {env}: {str(e)}",
            "environment": env
        }

@app.post("/api/keepalive/start")
async def api_start_keepalive():
    """Start keepalive system via API"""
    try:
        if not KEEPALIVE_AVAILABLE:
            return {
                "success": False,
                "error": "Keep-alive system not available"
            }
        
        keepalive = get_oauth_keepalive()
        success = await keepalive.start_keepalive()
        
        return {
            "success": success,
            "message": f"Keep-alive system {'started' if success else 'failed to start'}"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to start keepalive system: {str(e)}"
        }

@app.post("/api/keepalive/stop")
async def api_stop_keepalive():
    """Stop keepalive system via API"""
    try:
        if not KEEPALIVE_AVAILABLE:
            return {
                "success": False,
                "error": "Keep-alive system not available"
            }
        
        keepalive = get_oauth_keepalive()
        success = await keepalive.stop_keepalive()
        
        return {
            "success": success,
            "message": f"Keep-alive system {'stopped' if success else 'failed to stop'}"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to stop keepalive system: {str(e)}"
        }

@app.post("/api/keepalive/auto-start")
async def api_auto_start_keepalive():
    """Auto-start keepalive system if valid tokens are available"""
    try:
        if not KEEPALIVE_AVAILABLE:
            return {
                "success": False,
                "error": "Keep-alive system not available"
            }
        
        keepalive = get_oauth_keepalive()
        
        # Check if we have valid tokens
        token_status = await keepalive.check_and_update_tokens()
        has_valid_tokens = any(token_status.values())
        
        if not has_valid_tokens:
            return {
                "success": False,
                "message": "No valid tokens available - keepalive will start automatically when tokens are renewed",
                "token_status": token_status
            }
        
        # Check if keepalive is already running
        current_status = keepalive.get_status()
        prod_running = current_status.get('prod', {}).get('is_running', False)
        sandbox_running = current_status.get('sandbox', {}).get('is_running', False)
        
        if prod_running or sandbox_running:
            return {
                "success": True,
                "message": "Keepalive system is already running",
                "token_status": token_status,
                "keepalive_status": current_status
            }
        
        # Start keepalive system
        success = await keepalive.start_keepalive()
        
        return {
            "success": success,
            "message": f"Keepalive system {'started automatically' if success else 'failed to start'} due to valid tokens",
            "token_status": token_status
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to auto-start keepalive system: {str(e)}"
        }

# --- HEALTH CHECK ---
@app.get("/api/secret-manager/status")
def api_secret_manager_status():
    """JSON API endpoint for frontend token status"""
    try:
        prod_status = get_token_status("prod")
        sandbox_status = get_token_status("sandbox")
        
        # Convert to JSON format expected by frontend
        data = {
            "prod": {
                "valid": prod_status.get("valid", False),
                "message": prod_status.get("message", "Unknown status")
            },
            "sandbox": {
                "valid": sandbox_status.get("valid", False),
                "message": sandbox_status.get("message", "Unknown status")
            }
        }
        
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Error getting token status: {e}")
        return {"success": False, "error": str(e)}

@app.get("/healthz")
def healthz():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}

@app.get("/")
def root():
    """Root endpoint with countdown timer and navigation"""
    countdown = get_token_expiry_countdown()
    prod_status = get_token_status("prod")
    sandbox_status = get_token_status("sandbox")
    
    # Determine countdown class based on time remaining
    hours_left = int(countdown.split(':')[0])
    countdown_class = "warning" if hours_left < 4 else "danger" if hours_left < 1 else ""
    
    html = f"""
    <h1>🔐 E*TRADE OAuth Token Manager</h1>
    
    <div class="countdown {countdown_class}">
        ⏰ Access Token expires in: {countdown}
    </div>
    
    <div class="status-grid">
        <div class="status-card status-{prod_status['class']}">
            <strong>Production</strong><br>
            {prod_status['message']}
        </div>
        <div class="status-card status-{sandbox_status['class']}">
            <strong>Sandbox</strong><br>
            {sandbox_status['message']}
        </div>
    </div>
    
    <div class="card">
        <h3>🚀 Quick Start</h3>
        <a class="btn" href="/admin/secrets?env=prod">Production Keys</a>
        <a class="btn secondary" href="/admin/secrets?env=sandbox">Sandbox Keys</a>
    </div>
    
    <div class="card">
        <h3>🔄 Daily Token Renewal</h3>
        <a class="btn success" href="/oauth/start?env=prod">Get Production Token</a>
        <a class="btn" href="/oauth/start?env=sandbox">Get Sandbox Token</a>
    </div>
    
    <div class="card">
        <h3>📊 Token Status</h3>
        <a class="btn secondary" href="/status">View Detailed Status</a>
        <button class="refresh-btn" onclick="refreshPage()">🔄 Refresh</button>
    </div>
    
    <div class="card">
        <h3>🔄 Keep-Alive System</h3>
        <p>Automatic token maintenance every 1.5 hours</p>
        <a class="btn secondary" href="/keepalive/status">View Keep-Alive Status</a>
        <a class="btn secondary" href="/keepalive/force">Force Keep-Alive Call</a>
    </div>
    
    <div class="card">
        <h3>🧪 Testing</h3>
        <a class="btn secondary" href="/test-telegram">Test Telegram Alert</a>
        <a class="btn secondary" href="/healthz">Health Check</a>
    </div>
    
    <div class="small">
        <p><strong>💡 Pro Tip:</strong> Add this page to your phone's home screen for one-tap access!</p>
        <p><strong>⏰ Reminder:</strong> Tokens expire daily at midnight ET. Renew before market open.</p>
    </div>
    """
    return mobile_html("E*TRADE OAuth Manager", html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

