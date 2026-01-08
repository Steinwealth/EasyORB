#!/usr/bin/env python3
"""
Correct OAuth Balance Checker for ETrade API
===========================================

This script implements the correct OAuth 1.0a signature with HMAC-SHA1
and uses the required query parameters to get accurate account balance
and available cash from ETrade API.

Key fixes:
1. Correct OAuth 1.0a HMAC-SHA1 signature
2. Use production host (api.etrade.com) not sandbox
3. Use accountIdKey (not accountId)
4. Add required query params: instType=BROKERAGE&realTimeNAV=true
5. Proper Authorization header with OAuth params
"""

import os
import requests
import json
from requests_oauthlib import OAuth1
from datetime import datetime
import xml.etree.ElementTree as ET

def xml_to_dict(element):
    """Convert XML element to dictionary"""
    result = {}
    
    # Add attributes
    if element.attrib:
        result.update(element.attrib)
    
    # Add text content if no children
    if not element:
        if element.text and element.text.strip():
            return element.text.strip()
        return element.attrib if element.attrib else None
    
    # Process children
    children = {}
    for child in element:
        child_data = xml_to_dict(child)
        if child.tag in children:
            if not isinstance(children[child.tag], list):
                children[child.tag] = [children[child.tag]]
            children[child.tag].append(child_data)
        else:
            children[child.tag] = child_data
    
    result.update(children)
    return result

def load_environment():
    """Load environment variables from etrade-oauth.env"""
    env_file = os.path.join(os.path.dirname(__file__), '..', 'configs', 'etrade-oauth.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print("✅ Environment variables loaded from etrade-oauth.env")
    else:
        print("❌ etrade-oauth.env file not found")

def load_oauth_tokens():
    """Load OAuth tokens from tokens_prod.json"""
    token_file = os.path.join(os.path.dirname(__file__), 'tokens_prod.json')
    if os.path.exists(token_file):
        with open(token_file, 'r') as f:
            tokens = json.load(f)
        print("✅ OAuth tokens loaded")
        return tokens
    else:
        print("❌ OAuth tokens file not found")
        return None

def get_correct_balance_and_cash():
    """Get correct account balance and available cash using proper OAuth 1.0a"""
    print("=" * 80)
    print("CORRECT OAUTH 1.0A BALANCE CHECKER")
    print("=" * 80)
    
    try:
        # Load credentials and tokens
        CONSUMER_KEY = os.environ.get("ETRADE_PROD_KEY")
        CONSUMER_SECRET = os.environ.get("ETRADE_PROD_SECRET")
        
        if not CONSUMER_KEY or not CONSUMER_SECRET:
            print("❌ Missing consumer key/secret in environment")
            return
        
        tokens = load_oauth_tokens()
        if not tokens:
            return
        
        ACCESS_TOKEN = tokens.get("oauth_token")
        ACCESS_TOKEN_SECRET = tokens.get("oauth_token_secret")
        
        if not ACCESS_TOKEN or not ACCESS_TOKEN_SECRET:
            print("❌ Missing access token/secret")
            return
        
        print(f"✅ Using Consumer Key: {CONSUMER_KEY[:20]}...")
        print(f"✅ Using Access Token: {ACCESS_TOKEN[:20]}...")
        
        # Use PRODUCTION host (not sandbox)
        API_BASE = "https://api.etrade.com"  # PRODUCTION
        
        # Set up OAuth 1.0a with HMAC-SHA1
        oauth = OAuth1(
            client_key=CONSUMER_KEY,
            client_secret=CONSUMER_SECRET,
            resource_owner_key=ACCESS_TOKEN,
            resource_owner_secret=ACCESS_TOKEN_SECRET,
            signature_method="HMAC-SHA1",
            signature_type="AUTH_HEADER",  # OAuth params in Authorization header
        )
        
        print(f"✅ OAuth 1.0a configured with HMAC-SHA1")
        print(f"✅ Using PRODUCTION API: {API_BASE}")
        
        # 1) Get the accountIdKey from accounts list
        print("\n📋 STEP 1: Getting accounts list...")
        
        resp = requests.get(f"{API_BASE}/v1/accounts/list", auth=oauth)
        print(f"   Status Code: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"   ❌ Error: {resp.text}")
            return
        
        # Parse response (ETrade returns XML by default)
        if resp.headers.get("Content-Type", "").startswith("application/json"):
            acct_list = resp.json()
        else:
            # Parse XML manually
            root = ET.fromstring(resp.text)
            acct_list = xml_to_dict(root)
        
        print("   ✅ Accounts list retrieved")
        
        # Debug: Print the structure
        print(f"   Raw response structure: {json.dumps(acct_list, indent=2)}")
        
        # Extract accountIdKey for Steinwealth account
        accounts = acct_list["Accounts"]["Account"]
        if isinstance(accounts, list):
            # Find Steinwealth account (775690861)
            target_account = None
            for acct in accounts:
                if acct.get("accountId") == "775690861":
                    target_account = acct
                    break
            if not target_account:
                print("   ❌ Steinwealth account not found")
                return
            acct = target_account
        else:
            acct = accounts
        
        account_id_key = acct["accountIdKey"]
        account_name = acct.get("accountName", "Unknown")
        
        print(f"   ✅ Found account: {account_name}")
        print(f"   ✅ Account ID Key: {account_id_key}")
        
        # 2) Get account balance with required query parameters
        print(f"\n💰 STEP 2: Getting account balance...")
        
        # Required query parameters for balance endpoint
        params = {
            "instType": "BROKERAGE",
            "realTimeNAV": "true"
        }
        
        # Request JSON response
        headers = {"Accept": "application/json"}
        
        print(f"   Using params: {params}")
        
        bal_resp = requests.get(
            f"{API_BASE}/v1/accounts/{account_id_key}/balance",
            params=params,
            headers=headers,
            auth=oauth,
        )
        
        print(f"   Status Code: {bal_resp.status_code}")
        
        if bal_resp.status_code != 200:
            print(f"   ❌ Error: {bal_resp.text}")
            return
        
        # Parse balance response
        if bal_resp.headers.get("Content-Type", "").startswith("application/json"):
            balance = bal_resp.json()
        else:
            # Parse XML manually
            root = ET.fromstring(bal_resp.text)
            balance = xml_to_dict(root)
        
        print("   ✅ Balance data retrieved")
        
        # Extract balance information
        balance_response = balance.get("BalanceResponse", {})
        computed = balance_response.get("Computed", {}) or balance_response.get("ComputedBalance", {})
        
        if not computed:
            print("   ❌ No computed balance data found")
            print(f"   Raw response: {json.dumps(balance, indent=2)}")
            return
        
        # Extract key balance fields
        account_value = float(computed.get("totalAccountValue", 0))
        cash_available = float(computed.get("cashAvailableForInvestment", 0))
        cash_buying_power = float(computed.get("cashBuyingPower", 0))
        margin_buying_power = float(computed.get("marginBuyingPower", 0))
        settled_cash = float(computed.get("settledCashForInvestment", 0))
        funds_withheld = float(computed.get("fundsWithheldFromPurchasePower", 0))
        
        # Display results
        print(f"\n🎯 CORRECT ACCOUNT BALANCE AND CASH:")
        print(f"   Account: {account_name} ({account_id_key})")
        print(f"   Total Account Value: ${account_value:,.2f}")
        print(f"   Cash Available for Investment: ${cash_available:,.2f}")
        print(f"   Cash Buying Power: ${cash_buying_power:,.2f}")
        print(f"   Margin Buying Power: ${margin_buying_power:,.2f}")
        print(f"   Settled Cash for Investment: ${settled_cash:,.2f}")
        print(f"   Funds Withheld from Purchase Power: ${funds_withheld:,.2f}")
        
        # Calculate Easy ETrade Strategy cash management
        print(f"\n🎯 EASY ETRADE STRATEGY CASH MANAGEMENT:")
        
        # Use cashAvailableForInvestment as the primary available cash
        available_cash = cash_available
        cash_reserve_pct = 20.0
        trading_cash_pct = 80.0
        
        cash_reserve = available_cash * (cash_reserve_pct / 100.0)
        trading_cash = available_cash * (trading_cash_pct / 100.0)
        
        print(f"   Available Cash: ${available_cash:,.2f}")
        print(f"   Cash Reserve (20%): ${cash_reserve:,.2f}")
        print(f"   Trading Cash (80%): ${trading_cash:,.2f}")
        
        # Position sizing
        max_position_size_pct = 20.0
        max_position_value = trading_cash * (max_position_size_pct / 100.0)
        max_positions = 5
        positions_possible = int(trading_cash / max_position_value) if max_position_value > 0 else 0
        positions_possible = min(positions_possible, max_positions)
        
        print(f"\n📊 POSITION SIZING:")
        print(f"   Max Position Size: ${max_position_value:,.2f} ({max_position_size_pct}% of trading cash)")
        print(f"   Positions Possible: {positions_possible}/{max_positions}")
        print(f"   Total Position Value: ${positions_possible * max_position_value:,.2f}")
        
        # Trading feasibility
        print(f"\n⚠️  TRADING FEASIBILITY:")
        if available_cash >= 1000:
            print(f"   ✅ ADEQUATE: Available cash (${available_cash:,.2f}) allows proper trading")
        elif available_cash >= 500:
            print(f"   ⚠️  MODERATE: Available cash (${available_cash:,.2f}) allows limited trading")
        elif available_cash >= 100:
            print(f"   ⚠️  LIMITED: Available cash (${available_cash:,.2f}) allows only small positions")
        else:
            print(f"   ❌ CRITICAL: Available cash (${available_cash:,.2f}) is too low for meaningful trading")
        
        # Summary
        print(f"\n📋 SUMMARY:")
        print(f"   ✅ OAuth 1.0a HMAC-SHA1 signature working")
        print(f"   ✅ Production API endpoint working")
        print(f"   ✅ Required query parameters included")
        print(f"   ✅ Real account balance retrieved")
        print(f"   ✅ Available cash: ${available_cash:,.2f}")
        print(f"   ✅ Trading cash: ${trading_cash:,.2f}")
        print(f"   ✅ Position size: ${max_position_value:,.2f}")
        
        return {
            "account_value": account_value,
            "cash_available": cash_available,
            "cash_buying_power": cash_buying_power,
            "margin_buying_power": margin_buying_power,
            "trading_cash": trading_cash,
            "max_position_value": max_position_value
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    load_environment()
    result = get_correct_balance_and_cash()
    
    if result:
        print(f"\n🎉 SUCCESS: Correct balance and cash retrieved!")
    else:
        print(f"\n❌ FAILED: Could not retrieve balance and cash")

