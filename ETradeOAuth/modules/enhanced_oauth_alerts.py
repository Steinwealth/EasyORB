#!/usr/bin/env python3
"""
Enhanced OAuth Alert System
Handles token expiry alerts and fallback alerts with smart logic
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional
import subprocess
import json

# Setup logging
log = logging.getLogger(__name__)

class EnhancedOAuthAlerts:
    """Enhanced OAuth alert system with smart fallback logic"""
    
    def __init__(self, project_id: str = "odin-187104", secret_name: str = "EtradeStrategy"):
        self.project_id = project_id
        self.secret_name = secret_name
        self.et_timezone = ZoneInfo('America/New_York')
        self.pt_timezone = ZoneInfo('America/Los_Angeles')
        self.last_token_check = None
        self.tokens_renewed_after_expiry = False
        
    async def check_and_send_expiry_alert(self) -> bool:
        """
        Check if it's 12:01am ET (token expiry time) and send alert
        
        Returns:
            True if alert sent or not needed
        """
        try:
            # Get current time in ET
            now_et = datetime.now(self.et_timezone)
            
            # Check if it's 12:01am ET (one minute after tokens expire)
            if now_et.hour == 0 and now_et.minute == 1:
                log.info("🕐 Token expiry time detected (12:01am ET) - checking token status")
                
                # Check if tokens are already renewed
                token_status = await self._get_token_status()
                
                if token_status['prod']['valid']:
                    log.info("✅ Production tokens are already valid - no alert needed")
                    self.tokens_renewed_after_expiry = True
                    return True
                else:
                    log.info("⚠️ Production tokens expired - sending renewal alert")
                    return await self._send_token_expiry_alert()
            else:
                log.debug(f"Not token expiry time: {now_et.strftime('%H:%M ET')}")
                return True
                
        except Exception as e:
            log.error(f"Error checking token expiry: {e}")
            return False
    
    async def check_and_send_fallback_alert(self) -> bool:
        """
        Check if it's 1 hour before market open and send fallback alert if needed
        
        Returns:
            True if alert sent or not needed
        """
        try:
            # Get current time in ET
            now_et = datetime.now(self.et_timezone)
            
            # Check if it's 1 hour before market open (8:30am ET - 1 hour = 7:30am ET)
            if now_et.hour == 7 and now_et.minute == 30:
                log.info("🕐 Pre-market time detected (7:30am ET) - checking if fallback alert needed")
                
                # Check if tokens are valid
                token_status = await self._get_token_status()
                
                if token_status['prod']['valid']:
                    log.info("✅ Production tokens are valid - no fallback alert needed")
                    return True
                else:
                    log.warning("⚠️ Production tokens still invalid - sending fallback alert")
                    return await self._send_fallback_alert()
            else:
                log.debug(f"Not pre-market time: {now_et.strftime('%H:%M ET')}")
                return True
                
        except Exception as e:
            log.error(f"Error checking fallback alert: {e}")
            return False
    
    async def _get_token_status(self) -> Dict[str, Any]:
        """Get current token status from Secret Manager"""
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
                    return {
                        'prod': self._check_token_validity(data),
                        'sandbox': {'valid': False, 'message': 'No sandbox tokens'}
                    }
                
                # Handle new format (with prod/sandbox keys)
                return {
                    'prod': self._check_token_validity(data.get('prod', {})),
                    'sandbox': self._check_token_validity(data.get('sandbox', {}))
                }
            else:
                log.error(f"Failed to get token status: {result.stderr}")
                return {
                    'prod': {'valid': False, 'message': 'Failed to load tokens'},
                    'sandbox': {'valid': False, 'message': 'Failed to load tokens'}
                }
                
        except Exception as e:
            log.error(f"Error getting token status: {e}")
            return {
                'prod': {'valid': False, 'message': f'Error: {e}'},
                'sandbox': {'valid': False, 'message': f'Error: {e}'}
            }
    
    def _check_token_validity(self, tokens: Dict[str, Any]) -> Dict[str, Any]:
        """Check if tokens are valid and not expired"""
        try:
            if not tokens or 'oauth_token' not in tokens:
                return {'valid': False, 'message': 'No tokens found'}
            
            expires_at_str = tokens.get('expires_at')
            if not expires_at_str:
                return {'valid': False, 'message': 'No expiry time set'}
            
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            
            if now >= expires_at:
                return {'valid': False, 'message': 'Tokens expired'}
            
            return {'valid': True, 'message': 'Tokens valid'}
            
        except Exception as e:
            return {'valid': False, 'message': f'Error checking validity: {e}'}
    
    async def _send_token_expiry_alert(self) -> bool:
        """Send token expiry alert"""
        try:
            now_pt = datetime.now(self.pt_timezone)
            
            message = f"""===========================================================

🌙 OAuth Token Renewal Alert — {now_pt.strftime('%I:%M %p PT')} ({now_pt.astimezone(self.et_timezone).strftime('%I:%M %p ET')})

⚠️ E*TRADE tokens just expired at midnight ET (just now)

🌐 Public Dashboard: https://easy-trading-oauth-v2.web.app

🪙 Renewal required ♻️"""
            
            # Send via Telegram (you'll need to implement this)
            success = await self._send_telegram_message(message)
            
            if success:
                log.info("✅ Token expiry alert sent successfully")
            else:
                log.error("❌ Failed to send token expiry alert")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending token expiry alert: {e}")
            return False
    
    async def _send_fallback_alert(self) -> bool:
        """Send fallback alert 1 hour before market open"""
        try:
            now_et = datetime.now(self.et_timezone)
            
            message = f"""🚨 **URGENT: OAuth Token Renewal Required** - {now_et.strftime('%H:%M ET')}

⚠️ **CRITICAL**: E*TRADE tokens still expired - market opens in 1 hour!

**IMMEDIATE ACTION REQUIRED:**
1. Visit the OAuth web app NOW
2. Click "Renew Production Tokens"
3. Complete the authorization flow
4. Tokens must be renewed before market open

**Web App**: [OAuth Manager](https://etrade-strategy.web.app)

**Status**: CRITICAL - Tokens expired since midnight
**Market Opens**: 9:30am ET (in 1 hour)
**Trading**: Will be disabled until tokens are renewed

**This is your final warning before trading is disabled!**"""
            
            # Send via Telegram (you'll need to implement this)
            success = await self._send_telegram_message(message)
            
            if success:
                log.info("✅ Fallback alert sent successfully")
            else:
                log.error("❌ Failed to send fallback alert")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending fallback alert: {e}")
            return False
    
    async def _send_telegram_message(self, message: str) -> bool:
        """Send message via Telegram (placeholder - implement with your bot)"""
        try:
            # This is a placeholder - implement with your actual Telegram bot
            log.info(f"📱 Telegram message would be sent: {message[:100]}...")
            
            # For now, just log the message
            print(f"\n📱 TELEGRAM ALERT:\n{message}\n")
            
            return True
            
        except Exception as e:
            log.error(f"Error sending Telegram message: {e}")
            return False
    
    async def run_alert_checks(self) -> Dict[str, Any]:
        """Run all alert checks and return status"""
        try:
            results = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'expiry_alert_sent': False,
                'fallback_alert_sent': False,
                'tokens_valid': False,
                'errors': []
            }
            
            # Check expiry alert
            try:
                expiry_result = await self.check_and_send_expiry_alert()
                results['expiry_alert_sent'] = expiry_result
            except Exception as e:
                results['errors'].append(f"Expiry alert error: {e}")
            
            # Check fallback alert
            try:
                fallback_result = await self.check_and_send_fallback_alert()
                results['fallback_alert_sent'] = fallback_result
            except Exception as e:
                results['errors'].append(f"Fallback alert error: {e}")
            
            # Check token status
            try:
                token_status = await self._get_token_status()
                results['tokens_valid'] = token_status['prod']['valid']
            except Exception as e:
                results['errors'].append(f"Token status error: {e}")
            
            return results
            
        except Exception as e:
            log.error(f"Error running alert checks: {e}")
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }

# Global instance
enhanced_alerts = EnhancedOAuthAlerts()

async def run_oauth_alert_checks() -> Dict[str, Any]:
    """Run OAuth alert checks"""
    return await enhanced_alerts.run_alert_checks()

if __name__ == "__main__":
    # Test the enhanced alert system
    print("🧪 Testing Enhanced OAuth Alert System")
    print("=" * 50)
    
    async def test_alerts():
        # Test alert checks
        results = await run_oauth_alert_checks()
        print(f"Results: {results}")
        
        # Test individual checks
        print("\n📋 Testing individual checks...")
        
        # Test expiry check
        expiry_result = await enhanced_alerts.check_and_send_expiry_alert()
        print(f"Expiry alert check: {'✅' if expiry_result else '❌'}")
        
        # Test fallback check
        fallback_result = await enhanced_alerts.check_and_send_fallback_alert()
        print(f"Fallback alert check: {'✅' if fallback_result else '❌'}")
    
    asyncio.run(test_alerts())

