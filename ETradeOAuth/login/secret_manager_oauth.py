#!/usr/bin/env python3
"""
Secret Manager OAuth Integration
===============================

Google Secret Manager integration for E*TRADE OAuth tokens.
Provides secure storage and retrieval of OAuth credentials.

This module handles OAuth token storage in Google Secret Manager,
providing a secure alternative to local file storage.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path

try:
    from google.cloud import secretmanager
    SECRET_MANAGER_AVAILABLE = True
except ImportError:
    SECRET_MANAGER_AVAILABLE = False
    logging.warning("Google Secret Manager not available. Install with: pip install google-cloud-secret-manager")

log = logging.getLogger(__name__)

class SecretManagerOAuth:
    """Google Secret Manager OAuth integration"""
    
    def __init__(self, project_id: str = "easy-etrade-strategy"):
        self.project_id = project_id
        self.client = None
        
        if SECRET_MANAGER_AVAILABLE:
            try:
                self.client = secretmanager.SecretManagerServiceClient()
                log.info(f"Secret Manager client initialized for project: {project_id}")
            except Exception as e:
                log.error(f"Failed to initialize Secret Manager client: {e}")
                self.client = None
        else:
            log.warning("Secret Manager not available")
    
    def _get_secret_name(self, environment: str) -> str:
        """Get secret name for environment"""
        return f"etrade-oauth-{environment}"
    
    def _get_secret_path(self, environment: str) -> str:
        """Get full secret path"""
        secret_name = self._get_secret_name(environment)
        return f"projects/{self.project_id}/secrets/{secret_name}"
    
    def create_secret(self, environment: str) -> bool:
        """
        Create a new secret for OAuth tokens
        
        Args:
            environment: Environment (sandbox/prod)
            
        Returns:
            True if created successfully
        """
        try:
            if not self.client:
                log.error("Secret Manager client not available")
                return False
            
            secret_name = self._get_secret_name(environment)
            parent = f"projects/{self.project_id}"
            
            # Check if secret already exists
            try:
                secret_path = self._get_secret_path(environment)
                self.client.get_secret(request={"name": secret_path})
                log.info(f"Secret {secret_name} already exists")
                return True
            except Exception:
                # Secret doesn't exist, create it
                pass
            
            # Create the secret
            secret = {
                "replication": {
                    "automatic": {}
                }
            }
            
            parent = f"projects/{self.project_id}"
            secret_id = secret_name
            
            response = self.client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": secret,
                }
            )
            
            log.info(f"Created secret: {response.name}")
            return True
            
        except Exception as e:
            log.error(f"Failed to create secret: {e}")
            return False
    
    def store_tokens(self, environment: str, tokens: Dict[str, Any]) -> bool:
        """
        Store OAuth tokens in Secret Manager
        
        Args:
            environment: Environment (sandbox/prod)
            tokens: OAuth tokens dictionary
            
        Returns:
            True if stored successfully
        """
        try:
            if not self.client:
                log.error("Secret Manager client not available")
                return False
            
            # Ensure secret exists
            if not self.create_secret(environment):
                return False
            
            # Add metadata
            tokens["stored_at"] = datetime.now(timezone.utc).isoformat()
            tokens["environment"] = environment
            tokens["project_id"] = self.project_id
            
            # Convert to JSON
            payload = json.dumps(tokens).encode("UTF-8")
            
            # Add secret version
            parent = self._get_secret_path(environment)
            
            response = self.client.add_secret_version(
                request={
                    "parent": parent,
                    "payload": {"data": payload}
                }
            )
            
            log.info(f"Stored OAuth tokens for {environment}: {response.name}")
            return True
            
        except Exception as e:
            log.error(f"Failed to store tokens: {e}")
            return False
    
    def load_tokens(self, environment: str) -> Optional[Dict[str, Any]]:
        """
        Load OAuth tokens from Secret Manager
        
        Args:
            environment: Environment (sandbox/prod)
            
        Returns:
            Tokens dictionary or None if not found
        """
        try:
            if not self.client:
                log.error("Secret Manager client not available")
                return None
            
            # Get the latest version
            name = f"{self._get_secret_path(environment)}/versions/latest"
            
            response = self.client.access_secret_version(request={"name": name})
            
            # Decode the payload
            payload = response.payload.data.decode("UTF-8")
            tokens = json.loads(payload)
            
            log.info(f"Loaded OAuth tokens for {environment}")
            return tokens
            
        except Exception as e:
            log.error(f"Failed to load tokens: {e}")
            return None
    
    def is_token_valid(self, environment: str) -> bool:
        """
        Check if OAuth tokens are valid
        
        Args:
            environment: Environment (sandbox/prod)
            
        Returns:
            True if tokens are valid
        """
        try:
            tokens = self.load_tokens(environment)
            if not tokens:
                return False
            
            # Check if tokens have expires_at field
            if 'expires_at' in tokens:
                expires_at = datetime.fromisoformat(tokens['expires_at'])
                return datetime.now(timezone.utc) < expires_at
            
            # Check if tokens were created today (ET)
            stored_at = tokens.get('stored_at')
            if not stored_at:
                return False
            
            # Parse storage time
            stored_dt = datetime.fromisoformat(stored_at)
            
            # Check if stored today in ET
            now_et = datetime.now(timezone.utc).astimezone()
            stored_et = stored_dt.astimezone()
            
            # If stored on a different day, tokens are expired
            return stored_et.date() == now_et.date()
            
        except Exception as e:
            log.error(f"Error checking token validity: {e}")
            return False
    
    def get_token_info(self, environment: str) -> Dict[str, Any]:
        """
        Get token information
        
        Args:
            environment: Environment (sandbox/prod)
            
        Returns:
            Token information dictionary
        """
        try:
            tokens = self.load_tokens(environment)
            if not tokens:
                return {
                    "valid": False,
                    "environment": environment,
                    "message": "No tokens found in Secret Manager"
                }
            
            is_valid = self.is_token_valid(environment)
            
            return {
                "valid": is_valid,
                "environment": environment,
                "stored_at": tokens.get("stored_at", "Unknown"),
                "expires_at": tokens.get("expires_at", "Unknown"),
                "project_id": tokens.get("project_id", "Unknown"),
                "message": "Tokens are valid" if is_valid else "Tokens are expired"
            }
            
        except Exception as e:
            log.error(f"Error getting token info: {e}")
            return {
                "valid": False,
                "environment": environment,
                "message": f"Error: {e}"
            }
    
    def delete_tokens(self, environment: str) -> bool:
        """
        Delete OAuth tokens from Secret Manager
        
        Args:
            environment: Environment (sandbox/prod)
            
        Returns:
            True if deleted successfully
        """
        try:
            if not self.client:
                log.error("Secret Manager client not available")
                return False
            
            secret_path = self._get_secret_path(environment)
            
            # Delete the secret
            self.client.delete_secret(request={"name": secret_path})
            
            log.info(f"Deleted OAuth tokens for {environment}")
            return True
            
        except Exception as e:
            log.error(f"Failed to delete tokens: {e}")
            return False
    
    def list_secrets(self) -> list:
        """
        List available OAuth secrets
        
        Returns:
            List of secret names
        """
        try:
            if not self.client:
                log.error("Secret Manager client not available")
                return []
            
            parent = f"projects/{self.project_id}"
            secrets = []
            
            for secret in self.client.list_secrets(request={"parent": parent}):
                secret_name = secret.name.split("/")[-1]
                if secret_name.startswith("etrade-oauth-"):
                    environment = secret_name.replace("etrade-oauth-", "")
                    secrets.append(environment)
            
            return secrets
            
        except Exception as e:
            log.error(f"Error listing secrets: {e}")
            return []

# Global instance
_secret_manager_oauth = None

def get_secret_manager_oauth(project_id: str = "easy-etrade-strategy") -> SecretManagerOAuth:
    """Get the Secret Manager OAuth instance"""
    global _secret_manager_oauth
    if _secret_manager_oauth is None or _secret_manager_oauth.project_id != project_id:
        _secret_manager_oauth = SecretManagerOAuth(project_id)
    return _secret_manager_oauth

if __name__ == "__main__":
    # Test the Secret Manager OAuth integration
    print("Testing Secret Manager OAuth Integration...")
    
    manager = get_secret_manager_oauth()
    
    if not SECRET_MANAGER_AVAILABLE:
        print("❌ Secret Manager not available. Install with: pip install google-cloud-secret-manager")
        exit(1)
    
    if not manager.client:
        print("❌ Secret Manager client not available")
        exit(1)
    
    # Test storing tokens
    test_tokens = {
        "access_token": "test_access_token",
        "access_token_secret": "test_secret",
        "expires_at": (datetime.now(timezone.utc).replace(hour=23, minute=59, second=59)).isoformat()
    }
    
    print("Creating secret...")
    success = manager.create_secret("sandbox")
    print(f"Create secret: {'✅' if success else '❌'}")
    
    print("Storing tokens...")
    success = manager.store_tokens("sandbox", test_tokens)
    print(f"Store tokens: {'✅' if success else '❌'}")
    
    print("Loading tokens...")
    tokens = manager.load_tokens("sandbox")
    print(f"Load tokens: {'✅' if tokens else '❌'}")
    
    print("Checking validity...")
    is_valid = manager.is_token_valid("sandbox")
    print(f"Token validity: {'✅' if is_valid else '❌'}")
    
    print("Getting token info...")
    info = manager.get_token_info("sandbox")
    print(f"Token info: {info}")
    
    print("Listing secrets...")
    secrets = manager.list_secrets()
    print(f"Available secrets: {secrets}")
    
    print("✅ Secret Manager OAuth integration test completed!")

