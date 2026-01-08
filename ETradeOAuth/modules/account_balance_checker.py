#!/usr/bin/env python3
"""
ETrade Account Balance Checker

This module provides functionality to check account balances and cash available for trading
using the ETrade API. It handles both Sandbox and Production environments.

Based on ETrade API documentation:
- /v1/accounts/list - Get account list
- /v1/accounts/{accountId}/portfolio - Get portfolio summary
- /v1/accounts/{accountId}/balance - Get account balance details
"""

import os
import sys
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Add ETradeOAuth to path
etrade_oauth_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, etrade_oauth_path)

try:
    from simple_oauth_cli import load_config, load_tokens, make_oauth_request
    ETradeOAuth_AVAILABLE = True
except ImportError:
    logging.error("ETradeOAuth simple_oauth_cli not found. Please ensure ETradeOAuth folder is correctly set up.")
    ETradeOAuth_AVAILABLE = False
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

class ETradeAccountBalanceChecker:
    """ETrade Account Balance Checker"""
    
    def __init__(self, environment: str = 'prod'):
        self.environment = environment
        self.config = None
        self.tokens = None
        self.account_id = None
        self.account_id_key = None
        
        self._load_credentials()
        self._load_tokens()
        
    def _load_credentials(self):
        """Load ETrade credentials"""
        try:
            self.config = load_config(self.environment)
            if not self.config:
                raise Exception(f"Failed to load config for {self.environment}")
            log.info(f"✅ Loaded credentials for {self.environment}")
        except Exception as e:
            log.error(f"Failed to load credentials: {e}")
            raise
    
    def _load_tokens(self):
        """Load ETrade tokens"""
        try:
            self.tokens = load_tokens(self.environment)
            if not self.tokens:
                raise Exception(f"No tokens found for {self.environment}")
            log.info(f"✅ Loaded tokens for {self.environment}")
        except Exception as e:
            log.error(f"Failed to load tokens: {e}")
            raise
    
    def get_account_list(self) -> Dict[str, Any]:
        """Get list of accounts"""
        try:
            log.info("📋 Fetching account list...")
            response = make_oauth_request(
                method='GET',
                url=f"{self.config['base_url']}/v1/accounts/list",
                params={},
                consumer_key=self.config['consumer_key'],
                consumer_secret=self.config['consumer_secret'],
                oauth_token=self.tokens['oauth_token'],
                oauth_token_secret=self.tokens['oauth_token_secret']
            )
            
            # Parse XML response
            xml_key = '<?xml version'
            if xml_key in response:
                xml_data = response[xml_key]
                log.debug(f"XML Response: {xml_data[:200]}...")  # Log first 200 chars
                return self._parse_account_list_xml(xml_data)
            else:
                log.error(f"Unexpected response format. Keys: {list(response.keys())}")
                log.debug(f"Full response: {response}")
                return {}
                
        except Exception as e:
            log.error(f"Failed to get account list: {e}")
            return {}
    
    def _parse_account_list_xml(self, xml_data: str) -> Dict[str, Any]:
        """Parse account list XML response"""
        try:
            # Clean up the XML data - remove any wrapper or extra content
            xml_data = xml_data.strip()
            
            # The XML data from ETrade API response is missing the XML declaration
            # It starts with "1.0" encoding="UTF-8" standalone="yes"?>
            if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                # Add the missing XML declaration
                xml_data = '<?xml version=' + xml_data
            elif xml_data.startswith('<?xml version'):
                # Already has XML declaration
                pass
            else:
                # Add XML declaration if missing
                xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
            
            # Parse the XML
            root = ET.fromstring(xml_data)
            
            accounts = []
            for account in root.findall('.//Account'):
                account_data = {
                    'account_id': account.find('accountId').text if account.find('accountId') is not None else None,
                    'account_name': account.find('accountName').text if account.find('accountName') is not None else None,
                    'account_id_key': account.find('accountIdKey').text if account.find('accountIdKey') is not None else None,
                    'account_status': account.find('accountStatus').text if account.find('accountStatus') is not None else None,
                    'institution_type': account.find('institutionType').text if account.find('institutionType') is not None else None,
                    'account_type': account.find('accountType').text if account.find('accountType') is not None else None,
                }
                accounts.append(account_data)
            
            return {
                'accounts': accounts,
                'total_accounts': len(accounts),
                'active_accounts': len([a for a in accounts if a['account_status'] == 'ACTIVE'])
            }
            
        except Exception as e:
            log.error(f"Failed to parse account list XML: {e}")
            return {}
    
    def set_account(self, account_id: str, account_id_key: str = None):
        """Set the account to use for balance checking"""
        self.account_id = account_id
        self.account_id_key = account_id_key
        log.info(f"✅ Set account to: {account_id}")
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary for the selected account"""
        if not self.account_id:
            log.error("No account selected. Call set_account() first.")
            return {}
        
        try:
            log.info(f"📊 Fetching portfolio summary for account {self.account_id}...")
            
            # Try different portfolio endpoints - use accountIdKey for some endpoints
            endpoints = [
                f"/v1/accounts/{self.account_id_key}/portfolio" if self.account_id_key else f"/v1/accounts/{self.account_id}/portfolio",
                f"/v1/accounts/{self.account_id}/portfolio",
                f"/v1/accounts/{self.account_id_key}/portfolio/summary" if self.account_id_key else f"/v1/accounts/{self.account_id}/portfolio/summary",
                f"/v1/accounts/{self.account_id}/portfolio/summary",
                f"/v1/accounts/{self.account_id_key}/portfolio/positions" if self.account_id_key else f"/v1/accounts/{self.account_id}/portfolio/positions",
                f"/v1/accounts/{self.account_id}/portfolio/positions"
            ]
            
            for endpoint in endpoints:
                try:
                    response = make_oauth_request(
                        method='GET',
                        url=f"{self.config['base_url']}{endpoint}",
                        params={},
                        consumer_key=self.config['consumer_key'],
                        consumer_secret=self.config['consumer_secret'],
                        oauth_token=self.tokens['oauth_token'],
                        oauth_token_secret=self.tokens['oauth_token_secret']
                    )
                    
                    if response:
                        log.info(f"✅ Successfully got portfolio data from {endpoint}")
                        return self._parse_portfolio_response(response, endpoint)
                        
                except Exception as e:
                    log.warning(f"Failed to get portfolio from {endpoint}: {e}")
                    continue
            
            log.error("All portfolio endpoints failed")
            return {}
            
        except Exception as e:
            log.error(f"Failed to get portfolio summary: {e}")
            return {}
    
    def get_account_balance(self) -> Dict[str, Any]:
        """Get account balance for the selected account"""
        if not self.account_id:
            log.error("No account selected. Call set_account() first.")
            return {}
        
        try:
            log.info(f"💰 Fetching account balance for account {self.account_id}...")
            
            # Try the correct ETrade API endpoints for account balances
            # Based on ETrade API documentation: 
            # https://api.etrade.com/v1/accounts/{accountIdKey}/balance?instType=BROKERAGE&realTimeNAV=true
            endpoints = []
            
            if self.account_id_key:
                # Primary endpoint with parameters
                endpoints.append({
                    'url': f"/v1/accounts/{self.account_id_key}/balance",
                    'params': {'instType': 'BROKERAGE', 'realTimeNAV': 'true'}
                })
                # Secondary endpoint without parameters
                endpoints.append({
                    'url': f"/v1/accounts/{self.account_id_key}/balance",
                    'params': {}
                })
            
            # Fallback to accountId if no accountIdKey
            endpoints.append({
                'url': f"/v1/accounts/{self.account_id}/balance",
                'params': {}
            })
            
            for endpoint_info in endpoints:
                try:
                    response = make_oauth_request(
                        method='GET',
                        url=f"{self.config['base_url']}{endpoint_info['url']}",
                        params=endpoint_info['params'],
                        consumer_key=self.config['consumer_key'],
                        consumer_secret=self.config['consumer_secret'],
                        oauth_token=self.tokens['oauth_token'],
                        oauth_token_secret=self.tokens['oauth_token_secret']
                    )
                    
                    if response:
                        endpoint = endpoint_info['url']
                        log.info(f"✅ Successfully got balance data from {endpoint}")
                        return self._parse_balance_response(response, endpoint)
                        
                except Exception as e:
                    endpoint = endpoint_info['url']
                    log.warning(f"Failed to get balance from {endpoint}: {e}")
                    continue
            
            log.error("All balance endpoints failed")
            return {}
            
        except Exception as e:
            log.error(f"Failed to get account balance: {e}")
            return {}
    
    def _parse_portfolio_response(self, response: Dict, endpoint: str) -> Dict[str, Any]:
        """Parse portfolio response"""
        try:
            xml_key = '<?xml version'
            if xml_key in response:
                xml_data = response[xml_key]
                
                # Clean up the XML data - same issue as account list
                xml_data = xml_data.strip()
                
                # The XML data from ETrade API response is missing the XML declaration
                if xml_data.startswith('"1.0" encoding="UTF-8" standalone="yes"?>'):
                    # Add the missing XML declaration
                    xml_data = '<?xml version=' + xml_data
                elif xml_data.startswith('<?xml version'):
                    # Already has XML declaration
                    pass
                else:
                    # Add XML declaration if missing
                    xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
                
                root = ET.fromstring(xml_data)
                
                # Extract portfolio information
                portfolio_data = {
                    'endpoint': endpoint,
                    'total_value': None,
                    'cash_available': None,
                    'buying_power': None,
                    'positions': [],
                    'account_summary': {}
                }
                
                # Look for account summary information
                account_portfolio = root.find('.//AccountPortfolio')
                if account_portfolio is not None:
                    # Extract account-level information
                    for child in account_portfolio:
                        if child.tag not in ['Position', 'next', 'totalPages', 'nextPageNo']:
                            portfolio_data['account_summary'][child.tag] = child.text
                
                # Look for common balance fields in account summary
                for field in ['totalValue', 'totalAccountValue', 'netAccountValue', 'accountValue']:
                    if field in portfolio_data['account_summary']:
                        portfolio_data['total_value'] = portfolio_data['account_summary'][field]
                        break
                
                for field in ['cashAvailable', 'cashAvailableForTrading', 'availableCash', 'cashBalance']:
                    if field in portfolio_data['account_summary']:
                        portfolio_data['cash_available'] = portfolio_data['account_summary'][field]
                        break
                
                for field in ['buyingPower', 'buyingPowerAvailable', 'availableBuyingPower', 'dayTradingBuyingPower']:
                    if field in portfolio_data['account_summary']:
                        portfolio_data['buying_power'] = portfolio_data['account_summary'][field]
                        break
                
                # Extract positions if available
                positions = []
                for position in root.findall('.//Position'):
                    pos_data = {}
                    for child in position:
                        pos_data[child.tag] = child.text
                    positions.append(pos_data)
                
                portfolio_data['positions'] = positions
                portfolio_data['total_positions'] = len(positions)
                
                return portfolio_data
            
            return {'error': 'Unexpected response format', 'endpoint': endpoint}
            
        except Exception as e:
            log.error(f"Failed to parse portfolio response: {e}")
            return {'error': str(e), 'endpoint': endpoint}
    
    def _parse_balance_response(self, response: Dict, endpoint: str) -> Dict[str, Any]:
        """Parse balance response"""
        try:
            xml_key = '<?xml version'
            if xml_key in response:
                xml_data = response[xml_key]
                
                # Ensure XML has proper declaration
                if not xml_data.startswith('<?xml'):
                    xml_data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml_data
                
                root = ET.fromstring(xml_data)
                
                # Extract balance information
                balance_data = {
                    'endpoint': endpoint,
                    'account_value': None,
                    'cash_available': None,
                    'buying_power': None,
                    'margin_available': None,
                    'day_trading_buying_power': None,
                    'option_level': None,
                    'account_summary': {}
                }
                
                # Look for AccountBalanceResponse structure
                account_balance = root.find('.//AccountBalance')
                if account_balance is not None:
                    # Extract all balance fields
                    for child in account_balance:
                        balance_data['account_summary'][child.tag] = child.text
                
                # Look for common balance fields in account summary
                for field in ['accountValue', 'totalAccountValue', 'netAccountValue', 'accountBalance']:
                    if field in balance_data['account_summary']:
                        balance_data['account_value'] = balance_data['account_summary'][field]
                        break
                
                for field in ['cashAvailable', 'cashAvailableForTrading', 'availableCash', 'cashBalance', 'cash']:
                    if field in balance_data['account_summary']:
                        balance_data['cash_available'] = balance_data['account_summary'][field]
                        break
                
                for field in ['buyingPower', 'buyingPowerAvailable', 'availableBuyingPower', 'buyingPowerCash']:
                    if field in balance_data['account_summary']:
                        balance_data['buying_power'] = balance_data['account_summary'][field]
                        break
                
                for field in ['marginAvailable', 'availableMargin', 'marginBalance']:
                    if field in balance_data['account_summary']:
                        balance_data['margin_available'] = balance_data['account_summary'][field]
                        break
                
                for field in ['dayTradingBuyingPower', 'dayTradingAvailable', 'dayTradingBuyingPowerCash']:
                    if field in balance_data['account_summary']:
                        balance_data['day_trading_buying_power'] = balance_data['account_summary'][field]
                        break
                
                for field in ['optionLevel', 'optionBuyingPower', 'optionApprovalLevel']:
                    if field in balance_data['account_summary']:
                        balance_data['option_level'] = balance_data['account_summary'][field]
                        break
                
                return balance_data
            
            return {'error': 'Unexpected response format', 'endpoint': endpoint}
            
        except Exception as e:
            log.error(f"Failed to parse balance response: {e}")
            return {'error': str(e), 'endpoint': endpoint}
    
    def get_comprehensive_account_info(self) -> Dict[str, Any]:
        """Get comprehensive account information including balances and portfolio"""
        log.info("🔍 Getting comprehensive account information...")
        
        # Get account list first
        account_list = self.get_account_list()
        if not account_list or 'accounts' not in account_list:
            return {'error': 'Failed to get account list'}
        
        # Find active accounts
        active_accounts = [acc for acc in account_list['accounts'] if acc['account_status'] == 'ACTIVE']
        if not active_accounts:
            return {'error': 'No active accounts found'}
        
        results = {
            'account_list': account_list,
            'active_accounts': active_accounts,
            'account_details': {}
        }
        
        # Get details for each active account
        for account in active_accounts:
            account_id = account['account_id']
            account_id_key = account['account_id_key']
            
            log.info(f"📊 Getting details for account {account_id}...")
            
            # Set current account
            self.set_account(account_id, account_id_key)
            
            # Get portfolio and balance
            portfolio = self.get_portfolio_summary()
            balance = self.get_account_balance()
            
            results['account_details'][account_id] = {
                'account_info': account,
                'portfolio': portfolio,
                'balance': balance,
                'cash_available_for_trading': self._extract_cash_available(portfolio, balance)
            }
        
        return results
    
    def _extract_cash_available(self, portfolio: Dict, balance: Dict) -> Optional[str]:
        """Extract cash available for trading from portfolio or balance data"""
        # Try portfolio first
        if portfolio and 'cash_available' in portfolio and portfolio['cash_available']:
            return portfolio['cash_available']
        
        # Try balance
        if balance and 'cash_available' in balance and balance['cash_available']:
            return balance['cash_available']
        
        # Try buying power as fallback
        if portfolio and 'buying_power' in portfolio and portfolio['buying_power']:
            return portfolio['buying_power']
        
        if balance and 'buying_power' in balance and balance['buying_power']:
            return balance['buying_power']
        
        return None

def print_header(title: str):
    """Print formatted header"""
    print("\n" + "="*60)
    print(f"🔐 {title}")
    print("="*60)

def print_account_summary(account_info: Dict[str, Any]):
    """Print formatted account summary"""
    print(f"\n📊 ACCOUNT SUMMARY")
    print("-" * 40)
    
    if 'account_list' in account_info:
        account_list = account_info['account_list']
        print(f"Total Accounts: {account_list.get('total_accounts', 0)}")
        print(f"Active Accounts: {account_list.get('active_accounts', 0)}")
    
    if 'account_details' in account_info:
        for account_id, details in account_info['account_details'].items():
            account_info_data = details.get('account_info', {})
            cash_available = details.get('cash_available_for_trading', 'N/A')
            
            print(f"\n🏦 Account: {account_info_data.get('account_name', 'No Name')} ({account_id})")
            print(f"   Status: {account_info_data.get('account_status', 'Unknown')}")
            print(f"   Type: {account_info_data.get('account_type', 'Unknown')}")
            print(f"   Cash Available for Trading: ${cash_available}")
            
            # Show portfolio info if available
            portfolio = details.get('portfolio', {})
            if portfolio and 'total_value' in portfolio and portfolio['total_value']:
                print(f"   Total Portfolio Value: ${portfolio['total_value']}")
            
            # Show balance info if available
            balance = details.get('balance', {})
            if balance and 'account_value' in balance and balance['account_value']:
                print(f"   Account Value: ${balance['account_value']}")

def main():
    """Main function for testing"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ETrade Account Balance Checker')
    parser.add_argument('environment', choices=['sandbox', 'prod'], 
                       help='Environment to check (sandbox or prod)')
    parser.add_argument('--account-id', type=str, 
                       help='Specific account ID to check (optional)')
    args = parser.parse_args()
    
    print_header(f"ETrade Account Balance Checker - {args.environment.upper()}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        checker = ETradeAccountBalanceChecker(args.environment)
        
        if args.account_id:
            # Check specific account
            print(f"\n🎯 Checking specific account: {args.account_id}")
            checker.set_account(args.account_id)
            
            portfolio = checker.get_portfolio_summary()
            balance = checker.get_account_balance()
            
            print(f"\n📊 Portfolio Summary:")
            print(json.dumps(portfolio, indent=2))
            
            print(f"\n💰 Account Balance:")
            print(json.dumps(balance, indent=2))
            
        else:
            # Get comprehensive account info
            account_info = checker.get_comprehensive_account_info()
            print_account_summary(account_info)
            
            # Show raw data for debugging
            print(f"\n🔍 Raw Data:")
            print(json.dumps(account_info, indent=2))
        
        print(f"\n✅ Account balance check completed successfully!")
        
    except Exception as e:
        log.error(f"❌ Account balance check failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

