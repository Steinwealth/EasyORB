"""
Google Cloud Storage Persistence Module
========================================

Handles persistent storage of watchlists and other data files in GCS
to survive Cloud Run container restarts.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import os
import logging
from typing import Optional, List
from datetime import datetime

log = logging.getLogger(__name__)

# GCS Configuration (Rev 00190: Use config loader for centralized cloud config)
def _get_gcs_bucket_name() -> str:
    """Get GCS bucket name from config (Rev 00190)"""
    try:
        from .config_loader import get_cloud_config
        cloud_config = get_cloud_config()
        return cloud_config.get("bucket_name", "easy-etrade-strategy-data")
    except Exception:
        # Fallback to environment variable or default
        return os.getenv("GCS_BUCKET_NAME", "easy-etrade-strategy-data")

GCS_BUCKET_NAME = _get_gcs_bucket_name()
GCS_ENABLED = os.getenv("GCS_PERSISTENCE_ENABLED", "true").lower() == "true"

class GCSPersistence:
    """Handle persistent storage in Google Cloud Storage"""
    
    def __init__(self):
        self.bucket = None
        self.client = None
        self.enabled = GCS_ENABLED
        
        if self.enabled:
            try:
                from google.cloud import storage
                self.client = storage.Client()
                self.bucket = self.client.bucket(GCS_BUCKET_NAME)
                log.info(f"✅ GCS persistence initialized (bucket: {GCS_BUCKET_NAME})")
            except Exception as e:
                log.warning(f"⚠️ GCS persistence disabled: {e}")
                self.enabled = False
    
    def upload_file(self, local_path: str, gcs_path: str) -> bool:
        """
        Upload a file to GCS
        
        Args:
            local_path: Local file path
            gcs_path: GCS path (without gs://bucket/)
            
        Returns:
            True if successful
        """
        if not self.enabled:
            return False
        
        try:
            if not os.path.exists(local_path):
                log.warning(f"⚠️ Local file not found: {local_path}")
                return False
            
            blob = self.bucket.blob(gcs_path)
            blob.upload_from_filename(local_path)
            log.info(f"☁️ Uploaded to GCS: {gcs_path}")
            return True
            
        except Exception as e:
            log.error(f"❌ Failed to upload {local_path} to GCS: {e}")
            return False
    
    def download_file(self, gcs_path: str, local_path: str) -> bool:
        """
        Download a file from GCS
        
        Args:
            gcs_path: GCS path (without gs://bucket/)
            local_path: Local file path to save to
            
        Returns:
            True if successful
        """
        if not self.enabled:
            return False
        
        try:
            blob = self.bucket.blob(gcs_path)
            
            if not blob.exists():
                log.debug(f"📭 GCS file not found: {gcs_path}")
                return False
            
            # Create directory if needed
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            blob.download_to_filename(local_path)
            log.info(f"☁️ Downloaded from GCS: {gcs_path}")
            return True
            
        except Exception as e:
            log.error(f"❌ Failed to download {gcs_path} from GCS: {e}")
            return False
    
    def file_exists(self, gcs_path: str) -> bool:
        """Check if a file exists in GCS"""
        if not self.enabled:
            return False
        
        try:
            blob = self.bucket.blob(gcs_path)
            return blob.exists()
        except Exception as e:
            log.error(f"Error checking GCS file existence: {e}")
            return False
    
    def upload_string(self, gcs_path: str, content: str) -> bool:
        """
        Upload string content directly to GCS (Rev 00047)
        
        Args:
            gcs_path: GCS path (without gs://bucket/)
            content: String content to upload
            
        Returns:
            True if successful
        """
        if not self.enabled:
            return False
        
        try:
            blob = self.bucket.blob(gcs_path)
            blob.upload_from_string(content)
            log.debug(f"☁️ Uploaded string to GCS: {gcs_path}")
            return True
        except Exception as e:
            log.error(f"❌ Failed to upload string to GCS {gcs_path}: {e}")
            return False
    
    def read_string(self, gcs_path: str) -> Optional[str]:
        """
        Read string content from GCS.
        
        Args:
            gcs_path: GCS path (without gs://bucket/)
        
        Returns:
            The file contents as a string, or None if unavailable.
        """
        if not self.enabled:
            return None
        
        try:
            blob = self.bucket.blob(gcs_path)
            if not blob.exists():
                log.debug(f"📭 GCS file not found: {gcs_path}")
                return None
            content = blob.download_as_text()
            log.debug(f"☁️ Read string from GCS: {gcs_path}")
            return content
        except Exception as e:
            log.error(f"❌ Failed to read string from GCS {gcs_path}: {e}")
            return None

    def list_files(self, prefix: str) -> List[str]:
        """
        List file paths in GCS under a given prefix.
        
        Args:
            prefix: GCS prefix (e.g. "priority_optimizer/daily_signals/")
        
        Returns:
            List of GCS object names (paths without bucket).
        """
        if not self.enabled:
            return []
        
        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            paths = [b.name for b in blobs]
            log.debug(f"☁️ Listed {len(paths)} objects under prefix: {prefix}")
            return paths
        except Exception as e:
            log.error(f"❌ Failed to list files under prefix {prefix}: {e}")
            return []

    def delete_file(self, gcs_path: str) -> bool:
        """
        Delete a file from GCS.
        
        Args:
            gcs_path: GCS path (without gs://bucket/)
        
        Returns:
            True if the file was deleted (or did not exist).
        """
        if not self.enabled:
            return False
        
        try:
            blob = self.bucket.blob(gcs_path)
            if not blob.exists():
                log.debug(f"📭 GCS file not found for delete (already gone): {gcs_path}")
                return True
            blob.delete()
            log.info(f"🗑️ Deleted GCS object: {gcs_path}")
            return True
        except Exception as e:
            log.error(f"❌ Failed to delete GCS object {gcs_path}: {e}")
            return False
    
    def get_file_age_hours(self, gcs_path: str) -> Optional[float]:
        """Get the age of a file in GCS in hours"""
        if not self.enabled:
            return None
        
        try:
            blob = self.bucket.blob(gcs_path)
            if not blob.exists():
                return None
            
            blob.reload()  # Refresh metadata
            updated = blob.updated
            
            if updated:
                age = (datetime.now(updated.tzinfo) - updated).total_seconds() / 3600
                return age
            
            return None
            
        except Exception as e:
            log.error(f"Error getting GCS file age: {e}")
            return None
    
    def sync_to_gcs(self, local_path: str, gcs_path: str) -> bool:
        """
        Sync a local file to GCS (upload after save)
        
        Args:
            local_path: Local file path
            gcs_path: GCS path
            
        Returns:
            True if successful
        """
        return self.upload_file(local_path, gcs_path)
    
    def sync_from_gcs(self, gcs_path: str, local_path: str, max_age_hours: float = 24) -> bool:
        """
        Sync from GCS to local (download if fresh)
        
        Args:
            gcs_path: GCS path
            local_path: Local file path
            max_age_hours: Maximum age in hours (default 24)
            
        Returns:
            True if file was downloaded and is fresh
        """
        if not self.enabled:
            return False
        
        try:
            age = self.get_file_age_hours(gcs_path)
            
            if age is None:
                log.debug(f"📭 No GCS file found: {gcs_path}")
                return False
            
            if age > max_age_hours:
                log.info(f"⏰ GCS file too old ({age:.1f}h): {gcs_path}")
                return False
            
            # Download fresh file
            success = self.download_file(gcs_path, local_path)
            
            if success:
                log.info(f"✅ Synced fresh file from GCS ({age:.1f}h old): {gcs_path}")
            
            return success
            
        except Exception as e:
            log.error(f"Error syncing from GCS: {e}")
            return False


# Singleton instance
_gcs_persistence = None

def get_gcs_persistence() -> GCSPersistence:
    """Get singleton GCS persistence instance"""
    global _gcs_persistence
    if _gcs_persistence is None:
        _gcs_persistence = GCSPersistence()
    return _gcs_persistence

