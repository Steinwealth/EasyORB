#!/usr/bin/env python3
"""
Store existing OAuth tokens in the ORB Strategy Secret Manager secret
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from google.cloud import secretmanager
    SECRET_MANAGER_AVAILABLE = True
except ImportError:
    print("❌ Google Cloud Secret Manager library not available")
    print("Run: pip install google-cloud-secret-manager")
    sys.exit(1)

def store_tokens_in_etradestrategy_secret():
    """Store existing OAuth tokens in the ORB Strategy secret (EtradeStrategy secret name)"""
    
    # Get project ID
    project_id = "odin-187104"  # Your current project
    secret_id = "EtradeStrategy"  # Your secret name
    print(f"🔧 Using project: {project_id}")
    print(f"🔧 Using secret: {secret_id}")
    
    # Initialize Secret Manager client
    try:
        client = secretmanager.SecretManagerServiceClient()
        print("✅ Secret Manager client initialized")
    except Exception as e:
        print(f"❌ Failed to initialize Secret Manager client: {e}")
        return False
    
    # Path to existing token files
    etrade_oauth_dir = Path(__file__).parent.parent
    sandbox_token_file = etrade_oauth_dir / "tokens_sandbox.json"
    prod_token_file = etrade_oauth_dir / "tokens_prod.json"
    
    # Prepare combined tokens data
    tokens_data = {
        "sandbox": None,
        "prod": None,
        "metadata": {
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "secret_name": secret_id
        }
    }
    
    # Load sandbox tokens
    if sandbox_token_file.exists():
        print("\n📦 Loading sandbox tokens...")
        try:
            with open(sandbox_token_file, 'r') as f:
                sandbox_tokens = json.load(f)
            
            # Add metadata to sandbox tokens
            sandbox_tokens['stored_at'] = datetime.now(timezone.utc).isoformat()
            # Set expiry to midnight ET (tokens expire daily)
            now_et = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-5)))
            midnight_et = now_et.replace(hour=23, minute=59, second=59, microsecond=999999)
            sandbox_tokens['expires_at'] = midnight_et.astimezone(timezone.utc).isoformat()
            sandbox_tokens['environment'] = 'sandbox'
            
            tokens_data['sandbox'] = sandbox_tokens
            print(f"✅ Loaded sandbox tokens")
            
        except Exception as e:
            print(f"❌ Failed to load sandbox tokens: {e}")
            return False
    else:
        print("⚠️ Sandbox token file not found")
    
    # Load production tokens
    if prod_token_file.exists():
        print("\n📦 Loading production tokens...")
        try:
            with open(prod_token_file, 'r') as f:
                prod_tokens = json.load(f)
            
            # Add metadata to production tokens
            prod_tokens['stored_at'] = datetime.now(timezone.utc).isoformat()
            # Set expiry to midnight ET (tokens expire daily)
            now_et = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-5)))
            midnight_et = now_et.replace(hour=23, minute=59, second=59, microsecond=999999)
            prod_tokens['expires_at'] = midnight_et.astimezone(timezone.utc).isoformat()
            prod_tokens['environment'] = 'prod'
            
            tokens_data['prod'] = prod_tokens
            print(f"✅ Loaded production tokens")
            
        except Exception as e:
            print(f"❌ Failed to load production tokens: {e}")
            return False
    else:
        print("⚠️ Production token file not found")
    
    # Store combined tokens in Secret Manager
    print(f"\n📦 Storing tokens in Secret Manager...")
    try:
        secret_name = f"projects/{project_id}/secrets/{secret_id}"
        
        # Add secret version
        payload = json.dumps(tokens_data, indent=2).encode('UTF-8')
        client.add_secret_version(
            request={"parent": secret_name, "payload": {"data": payload}}
        )
        print(f"✅ Stored tokens in Secret Manager secret: {secret_id}")
        
    except Exception as e:
        print(f"❌ Failed to store tokens in Secret Manager: {e}")
        return False
    
    # Verify tokens were stored
    print("\n🔍 Verifying stored tokens...")
    try:
        response = client.access_secret_version(
            request={"name": f"{secret_name}/versions/latest"}
        )
        stored_data = json.loads(response.payload.data.decode('UTF-8'))
        
        print(f"✅ Successfully verified tokens in Secret Manager")
        print(f"   - Secret: {stored_data['metadata']['secret_name']}")
        print(f"   - Stored at: {stored_data['metadata']['stored_at']}")
        
        if stored_data['sandbox']:
            print(f"   - Sandbox tokens: ✅ Available")
            print(f"     - Expires: {stored_data['sandbox']['expires_at']}")
        else:
            print(f"   - Sandbox tokens: ❌ Not available")
            
        if stored_data['prod']:
            print(f"   - Production tokens: ✅ Available")
            print(f"     - Expires: {stored_data['prod']['expires_at']}")
        else:
            print(f"   - Production tokens: ❌ Not available")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to verify stored tokens: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Storing OAuth tokens in ORB Strategy Secret Manager")
    print("=" * 60)
    
    success = store_tokens_in_etradestrategy_secret()
    
    if success:
        print("\n✅ SUCCESS! OAuth tokens stored in ORB Strategy secret (EtradeStrategy)")
        print("🌐 Your web app can now access tokens from Secret Manager")
        print("🔗 Web app: https://easy-trading-oauth-v2.web.app")
        print("\n📋 Next steps:")
        print("   1. Update web app to use ORB Strategy secret (EtradeStrategy)")
        print("   2. Test token retrieval from web app")
        print("   3. Verify countdown timer shows correct expiry")
    else:
        print("\n❌ FAILED! Could not store tokens in Secret Manager")
        sys.exit(1)

