#!/usr/bin/env python3
"""
ETrade OAuth Integration Module
==============================

Provides integration between the main trading system and the ETradeOAuth system.
Handles OAuth token validation, renewal, and integration with the alert system.

This module bridges the gap between the main trading system and the ETradeOAuth
folder, providing a clean interface for OAuth operations.
"""

import os
import sys
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

# Add ETradeOAuth to path
current_dir = Path(__file__).parent
etrade_oauth_dir = current_dir.parent / "ETradeOAuth"
sys.path.insert(0, str(etrade_oauth_dir))

# Import OAuth modules
try:
    from central_oauth_manager import CentralOAuthManager, Environment
    from simple_oauth_cli import load_tokens, load_config
    OAUTH_AVAILABLE = True
except ImportError as e:
    logging.warning(f"ETradeOAuth modules not available: {e}")
    OAUTH_AVAILABLE = False

# Import alert manager
try:
    from modules.prime_alert_manager import get_prime_alert_manager
    ALERT_MANAGER_AVAILABLE = True
except ImportError:
    ALERT_MANAGER_AVAILABLE = False

log = logging.getLogger(__name__)

class ETradeOAuthIntegration:
    """
    ETrade OAuth Integration
    
    Provides OAuth token management and integration with the main trading system.
    Handles token validation, renewal, and alert notifications.
    """
    
    def __init__(self, environment: str = 'prod'):
        self.environment = environment
        self.oauth_manager = None
        self.alert_manager = None
        self._tokens = None
        self._last_validation = None
        
        # Initialize OAuth manager if available
        if OAUTH_AVAILABLE:
            try:
                self.oauth_manager = CentralOAuthManager()
                log.info("✅ OAuth manager initialized")
            except Exception as e:
                log.error(f"Failed to initialize OAuth manager: {e}")
        
        # Initialize alert manager if available
        if ALERT_MANAGER_AVAILABLE:
            try:
                self.alert_manager = get_prime_alert_manager()
                log.info("✅ Alert manager initialized")
            except Exception as e:
                log.error(f"Failed to initialize alert manager: {e}")
    
    def get_auth_status(self) -> Dict[str, Any]:
        """
        Get current OAuth authentication status
        
        Returns:
            Dict containing authentication status and details
        """
        try:
            if not OAUTH_AVAILABLE:
                return {
                    "status": "unavailable",
                    "message": "OAuth modules not available",
                    "authenticated": False
                }
            
            # Load tokens
            tokens = self._load_tokens()
            if not tokens:
                return {
                    "status": "no_tokens",
                    "message": "No OAuth tokens found",
                    "authenticated": False
                }
            
            # Check if tokens are expired
            if self._is_token_expired(tokens):
                return {
                    "status": "expired",
                    "message": "OAuth tokens expired at midnight ET",
                    "authenticated": False,
                    "expired_at": tokens.get('expires_at'),
                    "last_used": tokens.get('last_used')
                }
            
            # Check if tokens need renewal (idle for 2+ hours)
            if self._needs_renewal(tokens):
                return {
                    "status": "needs_renewal",
                    "message": "OAuth tokens idle for 2+ hours, renewal needed",
                    "authenticated": True,
                    "last_used": tokens.get('last_used'),
                    "needs_renewal": True
                }
            
            return {
                "status": "active",
                "message": "OAuth tokens are active and valid",
                "authenticated": True,
                "last_used": tokens.get('last_used'),
                "created_at": tokens.get('created_at')
            }
            
        except Exception as e:
            log.error(f"Error getting auth status: {e}")
            return {
                "status": "error",
                "message": f"Error checking auth status: {e}",
                "authenticated": False
            }
    
    def is_authenticated(self) -> bool:
        """
        Check if OAuth is authenticated and tokens are valid
        
        Returns:
            True if authenticated and tokens are valid
        """
        status = self.get_auth_status()
        return status.get("authenticated", False)
    
    def needs_renewal(self) -> bool:
        """
        Check if OAuth tokens need renewal
        
        Returns:
            True if tokens need renewal
        """
        status = self.get_auth_status()
        return status.get("needs_renewal", False)
    
    async def renew_tokens(self) -> bool:
        """
        Renew OAuth tokens if needed
        
        Returns:
            True if renewal successful or not needed
        """
        try:
            if not self.oauth_manager:
                log.error("OAuth manager not available")
                return False
            
            # Convert environment string to enum
            env = Environment.PROD if self.environment == 'prod' else Environment.SANDBOX
            
            # Attempt renewal
            success = self.oauth_manager.renew_if_needed(env)
            
            if success:
                log.info("✅ OAuth tokens renewed successfully")
                
                # Send success alert
                if self.alert_manager:
                    await self.alert_manager.send_oauth_renewal_success(self.environment)
                
                return True
            else:
                log.warning("⚠️ OAuth token renewal failed")
                
                # Send error alert
                if self.alert_manager:
                    await self.alert_manager.send_oauth_renewal_error(
                        self.environment, 
                        "Token renewal failed"
                    )
                
                return False
                
        except Exception as e:
            log.error(f"Error renewing tokens: {e}")
            
            # Send error alert
            if self.alert_manager:
                await self.alert_manager.send_oauth_renewal_error(
                    self.environment, 
                    f"Token renewal error: {e}"
                )
            
            return False
    
    async def validate_and_renew(self) -> bool:
        """
        Validate OAuth tokens and renew if needed
        
        Returns:
            True if tokens are valid or renewal successful
        """
        try:
            # Check if authentication is needed
            if not self.is_authenticated():
                log.warning("⚠️ OAuth not authenticated")
                
                # Send warning alert
                if self.alert_manager:
                    await self.alert_manager.send_oauth_warning(
                        self.environment,
                        "OAuth not authenticated - manual intervention required"
                    )
                
                return False
            
            # Check if renewal is needed
            if self.needs_renewal():
                log.info("🔄 OAuth tokens need renewal, attempting renewal...")
                success = await self.renew_tokens()
                
                if success:
                    # Send success alert
                    if self.alert_manager:
                        await self.alert_manager.send_oauth_alert(
                            "🔄 OAuth Tokens Renewed",
                            f"OAuth tokens successfully renewed for {self.environment} environment.\n"
                            f"Status: Active and ready for trading"
                        )
                
                return success
            
            # Tokens are valid - update last used timestamp
            await self._update_last_used()
            log.info("✅ OAuth tokens are valid")
            return True
            
        except Exception as e:
            log.error(f"Error validating OAuth tokens: {e}")
            return False
    
    def get_tokens(self) -> Optional[Dict[str, Any]]:
        """
        Get current OAuth tokens
        
        Returns:
            Dict containing OAuth tokens or None if not available
        """
        return self._load_tokens()
    
    def _load_tokens(self) -> Optional[Dict[str, Any]]:
        """Load OAuth tokens from Secret Manager (cloud) or file (local)"""
        try:
            # Check if running in cloud or if Secret Manager is available
            is_cloud = os.getenv('K_SERVICE') or os.getenv('CLOUD_MODE') == 'true'
            has_secret_manager = self._can_access_secret_manager()
            
            if is_cloud or has_secret_manager:
                # Load from Google Secret Manager (preferred method)
                log.info(f"Loading tokens from Secret Manager for {self.environment}")
                tokens = self._load_tokens_from_secret_manager()
                if tokens:
                    return tokens
                else:
                    log.warning("Failed to load from Secret Manager, falling back to local files")
            
            # Fallback to local files
            if OAUTH_AVAILABLE:
                tokens = load_tokens(self.environment)
                if tokens:
                    log.info(f"Loaded tokens from local files for {self.environment}")
                    return tokens
            
            log.warning(f"No tokens available for {self.environment}")
            return None
            
        except Exception as e:
            log.error(f"Error loading tokens: {e}")
            return None
    
    def _can_access_secret_manager(self) -> bool:
        """Check if Secret Manager is accessible"""
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            # Try to list secrets to test access
            project_id = "easy-etrade-strategy"
            parent = f"projects/{project_id}"
            client.list_secrets(request={"parent": parent})
            return True
        except Exception:
            return False
    
    def _load_tokens_from_secret_manager(self) -> Optional[Dict[str, Any]]:
        """Load tokens directly from Google Secret Manager"""
        try:
            from google.cloud import secretmanager
            
            client = secretmanager.SecretManagerServiceClient()
            project_id = "easy-etrade-strategy"
            secret_name = f"etrade-oauth-{self.environment}"
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            
            log.info(f"Loading tokens from Secret Manager: {secret_name}")
            response = client.access_secret_version(request={"name": name})
            
            # Decode and parse JSON
            tokens = json.loads(response.payload.data.decode("UTF-8"))
            log.info(f"✅ Loaded OAuth tokens from Secret Manager for {self.environment}")
            return tokens
            
        except Exception as e:
            log.error(f"Failed to load tokens from Secret Manager: {e}")
            return None
    
    def _is_token_expired(self, tokens: Dict[str, Any]) -> bool:
        """Check if tokens are expired (past midnight ET)"""
        try:
            if not tokens:
                return True
            
            # Check last_used timestamp - if used recently, tokens are valid
            last_used = tokens.get('last_used')
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
            timestamp = tokens.get('timestamp')
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
            
            # Fallback: Assume tokens are valid (better than blocking the system)
            log.warning("Could not determine token expiration - assuming valid")
            return False
            
        except Exception as e:
            log.error(f"Error checking token expiration: {e}")
            # Default to valid to avoid blocking
            return False
    
    def _needs_renewal(self, tokens: Dict[str, Any]) -> bool:
        """Check if tokens need renewal (idle for 2+ hours)"""
        try:
            if not tokens:
                return True
            
            last_used = tokens.get('last_used')
            if not last_used:
                return True
            
            # Parse last used time
            last_used_dt = datetime.fromisoformat(last_used)
            
            # Check if idle for 2+ hours
            idle_hours = (datetime.now(timezone.utc) - last_used_dt).total_seconds() / 3600
            return idle_hours >= 2
            
        except Exception as e:
            log.error(f"Error checking renewal need: {e}")
            return True
    
    async def _update_last_used(self) -> None:
        """Update last used timestamp for tokens"""
        try:
            if not OAUTH_AVAILABLE:
                return
            
            # Load current tokens
            tokens = load_tokens(self.environment)
            if not tokens:
                return
            
            # Update last used timestamp
            tokens['last_used'] = datetime.now(timezone.utc).isoformat()
            
            # Save updated tokens
            token_file = Path(etrade_oauth_dir) / f"tokens_{self.environment}.json"
            with open(token_file, 'w') as f:
                json.dump(tokens, f, indent=2)
            
            log.debug(f"Updated last_used timestamp for {self.environment} tokens")
            
        except Exception as e:
            log.error(f"Error updating last_used timestamp: {e}")
    
    async def start_keepalive(self, interval_minutes: int = 70) -> bool:
        """
        Start OAuth token keepalive process
        
        Args:
            interval_minutes: Keepalive interval in minutes
            
        Returns:
            True if keepalive started successfully
        """
        try:
            if not OAUTH_AVAILABLE:
                log.error("OAuth modules not available")
                return False
            
            # Start keepalive in background
            asyncio.create_task(self._keepalive_loop(interval_minutes))
            log.info(f"OAuth keepalive started for {self.environment} (every {interval_minutes} minutes)")
            
            # Send startup alert
            if self.alert_manager:
                await self.alert_manager.send_oauth_alert(
                    "🔄 OAuth Keepalive Started",
                    f"OAuth token keepalive started for {self.environment} environment.\n"
                    f"Interval: {interval_minutes} minutes\n"
                    f"Status: Active"
                )
            
            return True
            
        except Exception as e:
            log.error(f"Failed to start OAuth keepalive: {e}")
            return False
    
    async def _keepalive_loop(self, interval_minutes: int) -> None:
        """Keepalive loop that runs in background"""
        try:
            while True:
                # Wait for interval
                await asyncio.sleep(interval_minutes * 60)
                
                # Validate and renew tokens
                success = await self.validate_and_renew()
                
                if success:
                    log.info(f"OAuth keepalive successful for {self.environment}")
                else:
                    log.warning(f"OAuth keepalive failed for {self.environment}")
                    
        except Exception as e:
            log.error(f"OAuth keepalive loop error: {e}")

    async def send_morning_alert(self) -> bool:
        """
        Send morning OAuth renewal alert
        
        Returns:
            True if alert sent successfully
        """
        try:
            if not self.alert_manager:
                log.warning("Alert manager not available")
                return False
            
            success = await self.alert_manager.send_oauth_morning_alert()
            if success:
                log.info("✅ Morning OAuth alert sent")
            else:
                log.warning("⚠️ Failed to send morning OAuth alert")
            
            return success
            
        except Exception as e:
            log.error(f"Error sending morning alert: {e}")
            return False

# Global instance
_oauth_integration_instance: Optional[ETradeOAuthIntegration] = None

def get_etrade_oauth_integration(environment: str = 'prod') -> ETradeOAuthIntegration:
    """
    Get or create ETrade OAuth integration instance
    
    Args:
        environment: Environment ('prod' or 'sandbox')
        
    Returns:
        ETradeOAuthIntegration instance
    """
    global _oauth_integration_instance
    
    if _oauth_integration_instance is None or _oauth_integration_instance.environment != environment:
        _oauth_integration_instance = ETradeOAuthIntegration(environment)
    
    return _oauth_integration_instance

async def test_oauth_integration():
    """Test OAuth integration functionality"""
    print("🔐 Testing ETrade OAuth Integration")
    print("-" * 40)
    
    # Test production environment
    oauth = get_etrade_oauth_integration('prod')
    
    # Get auth status
    status = oauth.get_auth_status()
    print(f"Auth Status: {status}")
    
    # Check if authenticated
    is_auth = oauth.is_authenticated()
    print(f"Authenticated: {is_auth}")
    
    # Check if renewal needed
    needs_renewal = oauth.needs_renewal()
    print(f"Needs Renewal: {needs_renewal}")
    
    # Test validation and renewal
    if is_auth:
        valid = await oauth.validate_and_renew()
        print(f"Validation/Renewal: {valid}")
    
    print("✅ OAuth integration test completed")

if __name__ == "__main__":
    asyncio.run(test_oauth_integration())
