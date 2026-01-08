#!/usr/bin/env python3
"""
OAuth Keep-Alive System for The Easy ORB Strategy
==================================================

Consolidated OAuth token keep-alive system that maintains E*TRADE tokens active
throughout the trading day by making lightweight API calls every 90 minutes.
This ensures tokens stay alive for their full 24-hour lifecycle by preventing
the 2-hour idle timeout from E*TRADE.

This module consolidates functionality from:
- ETradeOAuth/modules/automated_keepalive.py
- ETradeOAuth/modules/oauth_keepalive.py
- ETradeOAuth/modules/strategy_keepalive_integration.py

Key Features:
- 90-minute keep-alive interval (safety margin before 2-hour idle timeout)
- Prevents E*TRADE token idle timeout to maintain 24-hour token lifecycle
- Integration with ETradeOAuth system and Google Secret Manager
- Background task management with graceful shutdown
- Comprehensive error handling and recovery
- Real-time status monitoring
- Alert system integration

Usage:
    # Programmatic usage
    from keepalive_oauth import start_oauth_keepalive, stop_oauth_keepalive
    await start_oauth_keepalive()  # Start background keep-alive
    await stop_oauth_keepalive()   # Stop background keep-alive
    
    # CLI usage
    python3 keepalive_oauth.py status    # View status
    python3 keepalive_oauth.py prod      # Keep production alive
    python3 keepalive_oauth.py sandbox   # Keep sandbox alive
    python3 keepalive_oauth.py both      # Keep both alive
"""

import asyncio
import logging
import json
import subprocess
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Setup logging
log = logging.getLogger(__name__)

# Alert manager disabled for now due to configuration issues
ALERT_MANAGER_AVAILABLE = False

@dataclass
class KeepAliveStatus:
    """Keep-alive status tracking"""
    environment: str
    last_call: Optional[datetime] = None
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    is_running: bool = False
    next_call: Optional[datetime] = None
    total_calls: int = 0
    successful_calls: int = 0

class OAuthKeepAlive:
    """
    OAuth Keep-Alive System
    
    Maintains E*TRADE OAuth tokens active by making lightweight API calls
    every 90 minutes to prevent idle timeout (2 hours). This ensures tokens
    stay alive for their full 24-hour lifecycle without requiring renewal.
    """
    
    def __init__(self, project_id: str = "easy-etrade-strategy", secret_name: str = "etrade-oauth"):
        self.project_id = project_id
        self.secret_name = secret_name
        self.keepalive_interval = 90 * 60  # 90 minutes in seconds (safety margin before 2-hour idle timeout)
        self.environments = ['prod', 'sandbox']
        self.status: Dict[str, KeepAliveStatus] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.running = False
        
        # Initialize status for each environment
        for env in self.environments:
            self.status[env] = KeepAliveStatus(environment=env)
        
        # Initialize alert manager
        self.alert_manager = None
        if ALERT_MANAGER_AVAILABLE:
            try:
                # Set required environment variables for alert manager
                os.environ.setdefault('TELEGRAM_ALERTS_ENABLED', 'false')
                os.environ.setdefault('ALERT_LEVEL_INFO', 'true')
                os.environ.setdefault('ALERT_LEVEL_WARNING', 'true')
                os.environ.setdefault('ALERT_LEVEL_ERROR', 'true')
                os.environ.setdefault('ALERT_LEVEL_CRITICAL', 'true')
                os.environ.setdefault('ALERT_LEVEL_SUCCESS', 'true')
                os.environ.setdefault('TELEGRAM_MAX_MESSAGES_PER_MINUTE', '20')
                os.environ.setdefault('ALERT_COOLDOWN_SECONDS', '30')
                
                self.alert_manager = get_prime_alert_manager()
                log.info("✅ Alert manager initialized for keep-alive")
            except Exception as e:
                log.error(f"Failed to initialize alert manager: {e}")
                self.alert_manager = None
    
    async def start_keepalive(self) -> bool:
        """
        Start keep-alive system for all environments
        
        Returns:
            True if started successfully
        """
        try:
            self.running = True
            log.info("🔄 Starting OAuth keep-alive system (every 90 minutes - safety margin before 2-hour idle timeout)...")
            
            # Check if any tokens are available before starting
            available_envs = []
            for env in self.environments:
                tokens = await self._get_current_tokens(env)
                if tokens and not self._are_tokens_expired(tokens):
                    available_envs.append(env)
                    log.info(f"✅ Valid tokens found for {env} - keep-alive will run")
                else:
                    log.warning(f"⚠️ No valid tokens for {env} - keep-alive will skip until tokens are renewed")
            
            if not available_envs:
                log.warning("⚠️ No valid tokens available - keep-alive system will wait for tokens to be renewed via frontend")
            
            # Start keep-alive tasks for each environment
            for env in self.environments:
                task = asyncio.create_task(self._keepalive_loop(env))
                self.tasks[env] = task
                self.status[env].is_running = True
                self.status[env].next_call = datetime.now(timezone.utc) + timedelta(seconds=self.keepalive_interval)
                
                if env in available_envs:
                    log.info(f"✅ Keep-alive started for {env} environment")
                else:
                    log.info(f"⏸️ Keep-alive started for {env} environment (waiting for valid tokens)")
            
            # Send startup alert
            if self.alert_manager:
                await self.alert_manager.send_oauth_warning(
                    "system", 
                    f"OAuth keep-alive system started - {len(available_envs)} environments with valid tokens"
                )
            
            return True
            
        except Exception as e:
            log.error(f"Failed to start keep-alive system: {e}")
            return False
    
    async def stop_keepalive(self) -> bool:
        """
        Stop keep-alive system
        
        Returns:
            True if stopped successfully
        """
        try:
            self.running = False
            log.info("🛑 Stopping OAuth keep-alive system...")
            
            # Cancel all tasks
            for env, task in self.tasks.items():
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                
                self.status[env].is_running = False
                self.status[env].next_call = None
                
                log.info(f"✅ Keep-alive stopped for {env} environment")
            
            self.tasks.clear()
            
            # Send shutdown alert
            if self.alert_manager:
                await self.alert_manager.send_oauth_warning(
                    "system", 
                    "OAuth keep-alive system stopped"
                )
            
            return True
            
        except Exception as e:
            log.error(f"Failed to stop keep-alive system: {e}")
            return False
    
    async def _keepalive_loop(self, env: str):
        """Smart keep-alive loop for specific environment based on last_used timestamp"""
        log.info(f"🔄 Starting smart keep-alive loop for {env}")
        
        while self.running:
            try:
                # Get current tokens to check last_used timestamp
                tokens = await self._get_current_tokens(env)
                if not tokens:
                    log.warning(f"No tokens available for {env} - waiting 5 minutes before retry")
                    await asyncio.sleep(300)
                    continue
                
                # Check if tokens are expired
                if self._are_tokens_expired(tokens):
                    log.warning(f"Tokens are expired for {env} - waiting 5 minutes before retry")
                    await asyncio.sleep(300)
                    continue
                
                # Get last_used timestamp
                last_used_str = tokens.get('last_used')
                now = datetime.now(timezone.utc)
                
                if last_used_str:
                    try:
                        last_used = datetime.fromisoformat(last_used_str.replace('Z', '+00:00'))
                        time_since_last_call = (now - last_used).total_seconds()
                        
                        # Check if keepalive is needed (>80 minutes since last call)
                        if time_since_last_call > (80 * 60):  # 80 minutes
                            log.info(f"Keep-alive needed for {env} (last call {time_since_last_call/60:.1f} minutes ago)")
                            await self._make_keepalive_call(env)
                            # Schedule next check for 90 minutes from now
                            next_check = now + timedelta(seconds=self.keepalive_interval)
                        else:
                            # Schedule next check for 90 minutes from last_used timestamp
                            next_check = last_used + timedelta(seconds=self.keepalive_interval)
                            log.info(f"Next keep-alive check for {env} scheduled for {next_check.strftime('%H:%M:%S')} UTC")
                        
                        self.status[env].next_call = next_check
                        
                    except Exception as e:
                        log.error(f"Error parsing last_used timestamp for {env}: {e}")
                        # Default to 90 minutes from now
                        next_check = now + timedelta(seconds=self.keepalive_interval)
                        self.status[env].next_call = next_check
                else:
                    # No last_used timestamp - make keepalive call immediately
                    log.info(f"No last_used timestamp for {env} - making immediate keep-alive call")
                    await self._make_keepalive_call(env)
                    next_check = now + timedelta(seconds=self.keepalive_interval)
                    self.status[env].next_call = next_check
                
                # Calculate wait time until next check
                wait_time = (next_check - now).total_seconds()
                if wait_time > 0:
                    log.info(f"Waiting {wait_time/60:.1f} minutes until next keep-alive check for {env}")
                    await asyncio.sleep(wait_time)
                else:
                    # If we're already past the scheduled time, continue immediately
                    continue
                
            except asyncio.CancelledError:
                log.info(f"Keep-alive loop cancelled for {env}")
                break
            except Exception as e:
                log.error(f"Error in keep-alive loop for {env}: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retry
    
    async def _make_keepalive_call(self, env: str) -> bool:
        """
        Make lightweight API call to keep tokens alive
        
        Args:
            env: Environment ('prod' or 'sandbox')
            
        Returns:
            True if call successful
        """
        try:
            log.info(f"🔄 Making keep-alive call for {env}...")
            
            # Update call count
            self.status[env].total_calls += 1
            self.status[env].last_call = datetime.now(timezone.utc)
            
            # Get current tokens from Secret Manager
            tokens = await self._get_current_tokens(env)
            if not tokens:
                log.warning(f"No tokens available for {env} - skipping keep-alive (tokens need to be renewed via frontend)")
                return False
            
            # Check if tokens are expired
            if self._are_tokens_expired(tokens):
                log.warning(f"Tokens are expired for {env} - skipping keep-alive (tokens need to be renewed via frontend)")
                return False
            
            # Make a simple API call to keep tokens alive
            success = await self._make_etrade_api_call(env, tokens)
            
            if success:
                self.status[env].last_success = datetime.now(timezone.utc)
                self.status[env].consecutive_failures = 0
                self.status[env].successful_calls += 1
                
                log.info(f"✅ Keep-alive call successful for {env}")
                return True
            else:
                self.status[env].consecutive_failures += 1
                log.warning(f"⚠️ Keep-alive call failed for {env} (attempt {self.status[env].consecutive_failures})")
                
                # Send error alert if too many failures
                if self.status[env].consecutive_failures >= 3 and self.alert_manager:
                    await self.alert_manager.send_oauth_renewal_error(
                        env, 
                        f"Keep-alive failed {self.status[env].consecutive_failures} consecutive times"
                    )
                
                return False
                
        except Exception as e:
            log.error(f"Keep-alive call error for {env}: {e}")
            self.status[env].consecutive_failures += 1
            return False
    
    async def _get_current_tokens(self, env: str) -> Optional[Dict[str, Any]]:
        """Get current tokens from Secret Manager"""
        try:
            # Use environment-specific secret name
            secret_name = f"etrade-oauth-{env}"
            
            result = subprocess.run([
                'gcloud', 'secrets', 'versions', 'access', 'latest',
                '--secret', secret_name,
                '--project', self.project_id
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                
                # Return the token data directly (already in correct format)
                return data
            else:
                log.error(f"Failed to get tokens for {env}: {result.stderr}")
                return None
                
        except Exception as e:
            log.error(f"Error getting tokens for {env}: {e}")
            return None
    
    def _are_tokens_expired(self, tokens: Dict[str, Any]) -> bool:
        """Check if tokens are expired or missing"""
        try:
            # Check if tokens exist (same logic as get_token_status)
            oauth_token = tokens.get('oauth_token', '')
            oauth_token_secret = tokens.get('oauth_token_secret', '')
            
            if not oauth_token or not oauth_token_secret:
                return True  # Tokens are missing/invalid
            
            # For now, we consider tokens valid if they exist
            # In the future, we could add expiry checking based on last_used timestamp
            # or make actual API calls to validate them
            return False
            
        except Exception as e:
            log.error(f"Error checking token expiry: {e}")
            return True  # Default to expired on error
    
    async def _make_etrade_api_call(self, env: str, tokens: Dict[str, Any]) -> bool:
        """
        Make a simple E*TRADE API call to keep tokens alive
        
        Args:
            env: Environment ('prod' or 'sandbox')
            tokens: OAuth tokens
            
        Returns:
            True if API call successful
        """
        try:
            # Get consumer credentials from Secret Manager
            consumer_key_secret = f"etrade-{env}-consumer-key"
            consumer_secret_secret = f"etrade-{env}-consumer-secret"
            
            # Get consumer key
            result = subprocess.run([
                'gcloud', 'secrets', 'versions', 'access', 'latest',
                '--secret', consumer_key_secret,
                '--project', self.project_id
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                log.error(f"Failed to get consumer key for {env}: {result.stderr}")
                return False
            
            consumer_key = result.stdout.strip()
            
            # Get consumer secret
            result = subprocess.run([
                'gcloud', 'secrets', 'versions', 'access', 'latest',
                '--secret', consumer_secret_secret,
                '--project', self.project_id
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                log.error(f"Failed to get consumer secret for {env}: {result.stderr}")
                return False
            
            consumer_secret = result.stdout.strip()
            
            # Set base URL based on environment
            if env == 'prod':
                base_url = "https://api.etrade.com"
            else:  # sandbox
                base_url = "https://apisb.etrade.com"
            
            # Create OAuth session
            from requests_oauthlib import OAuth1Session
            oauth = OAuth1Session(
                consumer_key,
                client_secret=consumer_secret,
                resource_owner_key=tokens['oauth_token'],
                resource_owner_secret=tokens['oauth_token_secret']
            )
            
            # Make a simple API call (get account list)
            url = f"{base_url}/v1/accounts/list"
            response = oauth.get(url, timeout=30)
            
            if response.status_code == 200:
                log.debug(f"Keep-alive API call successful for {env}")
                
                # Update last used timestamp in Secret Manager
                await self._update_token_timestamp(env, tokens)
                
                return True
            else:
                log.warning(f"Keep-alive API call failed for {env}: {response.status_code}")
                return False
                
        except Exception as e:
            log.error(f"Error making keep-alive API call for {env}: {e}")
            return False
    
    async def _update_token_timestamp(self, env: str, tokens: Dict[str, Any]):
        """Update last_used timestamp in Secret Manager"""
        try:
            # Update timestamp
            tokens['last_used'] = datetime.now(timezone.utc).isoformat()
            
            # Use environment-specific secret name
            secret_name = f"etrade-oauth-{env}"
            
            # Save updated tokens back to Secret Manager
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(tokens, f, indent=2)
                temp_file = f.name
            
            subprocess.run([
                'gcloud', 'secrets', 'versions', 'add', secret_name,
                '--data-file', temp_file,
                '--project', self.project_id
            ], check=True)
            
            # Clean up temp file
            os.unlink(temp_file)
            
            log.debug(f"Updated last_used timestamp for {env}")
                
        except Exception as e:
            log.error(f"Error updating token timestamp for {env}: {e}")
    
    def get_status(self, env: str = None) -> Dict[str, Any]:
        """
        Get keep-alive status for environment or all environments
        
        Args:
            env: Environment ('prod' or 'sandbox') or None for all
            
        Returns:
            Status dictionary
        """
        if env:
            if env not in self.status:
                return {"error": "Environment not found"}
            
            status = self.status[env]
            now = datetime.now(timezone.utc)
            
            return {
                "environment": env,
                "is_running": status.is_running,
                "last_call": status.last_call.isoformat() if status.last_call else None,
                "last_success": status.last_success.isoformat() if status.last_success else None,
                "consecutive_failures": status.consecutive_failures,
                "next_call": status.next_call.isoformat() if status.next_call else None,
                "time_until_next": (status.next_call - now).total_seconds() if status.next_call else None,
                "total_calls": status.total_calls,
                "successful_calls": status.successful_calls,
                "success_rate": (status.successful_calls / status.total_calls * 100) if status.total_calls > 0 else 0,
                "status": "healthy" if status.consecutive_failures == 0 else "degraded" if status.consecutive_failures < 3 else "unhealthy"
            }
        else:
            return {
                env: self.get_status(env) 
                for env in self.environments
            }
    
    async def force_keepalive_call(self, env: str) -> bool:
        """
        Force an immediate keep-alive call
        
        Args:
            env: Environment ('prod' or 'sandbox')
            
        Returns:
            True if call successful
        """
        log.info(f"🔄 Forcing keep-alive call for {env}...")
        return await self._make_keepalive_call(env)
    
    def is_keepalive_needed(self, env: str) -> bool:
        """
        Check if keep-alive is needed based on last API call time
        
        Args:
            env: Environment ('prod' or 'sandbox')
            
        Returns:
            True if keep-alive is needed
        """
        try:
            # Get current tokens to check last_used timestamp
            tokens = asyncio.run(self._get_current_tokens(env))
            if not tokens:
                return False  # No tokens means no keep-alive needed (wait for renewal)
            
            last_used_str = tokens.get('last_used')
            if not last_used_str:
                return True  # No last_used means keep-alive needed
            
            last_used = datetime.fromisoformat(last_used_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            time_since_last_call = (now - last_used).total_seconds()
            
            # Keep-alive needed if more than 80 minutes since last call (10-minute safety margin)
            return time_since_last_call > (80 * 60)  # 80 minutes
            
        except Exception as e:
            log.error(f"Error checking if keep-alive needed for {env}: {e}")
            return False  # Default to not needing keep-alive on error
    
    async def check_and_update_tokens(self) -> Dict[str, bool]:
        """
        Check if tokens have been renewed and update keep-alive status
        
        Returns:
            Dictionary of environment -> has_valid_tokens
        """
        token_status = {}
        
        for env in self.environments:
            try:
                tokens = await self._get_current_tokens(env)
                has_valid_tokens = tokens and not self._are_tokens_expired(tokens)
                token_status[env] = has_valid_tokens
                
                if has_valid_tokens:
                    log.info(f"✅ Valid tokens available for {env}")
                else:
                    log.info(f"⚠️ No valid tokens for {env} - waiting for renewal via frontend")
                    
            except Exception as e:
                log.error(f"Error checking tokens for {env}: {e}")
                token_status[env] = False
        
        return token_status

# Global instance
_keepalive_instance: Optional[OAuthKeepAlive] = None

def get_oauth_keepalive() -> OAuthKeepAlive:
    """Get or create OAuth keep-alive instance"""
    global _keepalive_instance
    
    if _keepalive_instance is None:
        _keepalive_instance = OAuthKeepAlive()
    
    return _keepalive_instance

async def start_oauth_keepalive() -> bool:
    """Start OAuth keep-alive system"""
    keepalive = get_oauth_keepalive()
    return await keepalive.start_keepalive()

async def stop_oauth_keepalive() -> bool:
    """Stop OAuth keep-alive system"""
    keepalive = get_oauth_keepalive()
    return await keepalive.stop_keepalive()

def get_keepalive_status(env: str = None) -> Dict[str, Any]:
    """Get keep-alive status"""
    keepalive = get_oauth_keepalive()
    return keepalive.get_status(env)

async def force_keepalive_call(env: str) -> bool:
    """Force an immediate keep-alive call"""
    keepalive = get_oauth_keepalive()
    return await keepalive.force_keepalive_call(env)

def is_keepalive_needed(env: str) -> bool:
    """Check if keep-alive is needed for environment"""
    keepalive = get_oauth_keepalive()
    return keepalive.is_keepalive_needed(env)

async def check_and_update_tokens() -> Dict[str, bool]:
    """Check if tokens have been renewed and update keep-alive status"""
    keepalive = get_oauth_keepalive()
    return await keepalive.check_and_update_tokens()

# --- CLI INTERFACE ---
async def keep_alive_environment(env: str) -> bool:
    """Keep tokens alive for a specific environment (CLI)"""
    print(f"🔐 Keeping {env.upper()} tokens alive...")
    print("=" * 40)
    
    # Test force call
    success = await force_keepalive_call(env)
    
    if success:
        print(f"✅ {env.upper()} keep-alive successful")
        print(f"✅ {env.upper()} tokens will remain valid for 2+ hours")
    else:
        print(f"❌ {env.upper()} keep-alive failed")
        print(f"⚠️  {env.upper()} tokens may need renewal")
    
    return success

async def main():
    """Main CLI function"""
    if len(sys.argv) != 2:
        print("Usage: python3 keepalive_oauth.py {sandbox|prod|both|status}")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    print("🔐 ETrade OAuth Keep-Alive System")
    print("=" * 50)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if command == 'status':
        # Show status
        status = get_keepalive_status()
        print("📊 Keep-Alive Status:")
        for env, env_status in status.items():
            print(f"\n{env.upper()}:")
            print(f"  Running: {'✅' if env_status['is_running'] else '❌'}")
            print(f"  Last Call: {env_status['last_call'] or 'Never'}")
            print(f"  Last Success: {env_status['last_success'] or 'Never'}")
            print(f"  Consecutive Failures: {env_status['consecutive_failures']}")
            print(f"  Total Calls: {env_status['total_calls']}")
            print(f"  Success Rate: {env_status['success_rate']:.1f}%")
            print(f"  Status: {env_status['status']}")
    elif command == 'sandbox':
        success = await keep_alive_environment('sandbox')
        print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}")
    elif command == 'prod':
        success = await keep_alive_environment('prod')
        print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}")
    elif command == 'both':
        print("🔄 Keeping both environments alive...")
        print()
        sandbox_ok = await keep_alive_environment('sandbox')
        print()
        prod_ok = await keep_alive_environment('prod')
        
        print()
        print("📊 SUMMARY:")
        print("=" * 20)
        print(f"Sandbox: {'✅ Active' if sandbox_ok else '❌ Failed'}")
        print(f"Production: {'✅ Active' if prod_ok else '❌ Failed'}")
    else:
        print("❌ Invalid command. Use: sandbox, prod, both, or status")
        sys.exit(1)
    
    print()
    print("🎯 Keep-alive complete!")

if __name__ == "__main__":
    asyncio.run(main())

