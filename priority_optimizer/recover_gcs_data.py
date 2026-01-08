#!/usr/bin/env python3
"""
GCS Data Recovery Script
=========================

Recovers historical trading data from Google Cloud Storage and reconstructs
89-point comprehensive data where possible.

This script:
1. Downloads all signal files from GCS
2. Downloads trade history from GCS
3. Attempts to reconstruct 89-point data from available information
4. Saves recovered data to local priority_optimizer folders

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import os
import sys
import json
import gzip
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    print("⚠️ Google Cloud Storage not available. Install: pip install google-cloud-storage")

try:
    from modules.config_loader import get_cloud_config
    cloud_config = get_cloud_config()
    GCS_BUCKET_NAME = cloud_config.get("bucket_name", "easy-etrade-strategy-data")
except Exception:
    GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "easy-etrade-strategy-data")


class GCSDataRecovery:
    """Recover data from Google Cloud Storage"""
    
    def __init__(self, bucket_name: str = GCS_BUCKET_NAME):
        self.bucket_name = bucket_name
        self.client = None
        self.bucket = None
        
        if GCS_AVAILABLE:
            try:
                self.client = storage.Client()
                self.bucket = self.client.bucket(bucket_name)
                print(f"✅ Connected to GCS bucket: {bucket_name}")
            except Exception as e:
                print(f"❌ Failed to connect to GCS: {e}")
                self.bucket = None
        else:
            print("❌ GCS not available")
    
    def list_files(self, prefix: str) -> List[str]:
        """List all files with given prefix"""
        if not self.bucket:
            return []
        
        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            return [blob.name for blob in blobs]
        except Exception as e:
            print(f"❌ Error listing files: {e}")
            return []
    
    def download_file(self, gcs_path: str, local_path: Path) -> bool:
        """Download file from GCS"""
        if not self.bucket:
            return False
        
        try:
            blob = self.bucket.blob(gcs_path)
            if not blob.exists():
                return False
            
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle gzipped files
            if gcs_path.endswith('.gz'):
                compressed = blob.download_as_bytes()
                content = gzip.decompress(compressed).decode('utf-8')
                with open(local_path, 'w') as f:
                    f.write(content)
            else:
                blob.download_to_filename(str(local_path))
            
            print(f"✅ Downloaded: {gcs_path} -> {local_path}")
            return True
        except Exception as e:
            print(f"❌ Error downloading {gcs_path}: {e}")
            return False
    
    def download_signals(self, output_dir: Path) -> List[str]:
        """Download all signal files"""
        print("\n📥 Downloading signal files...")
        signal_files = self.list_files("priority_optimizer/daily_signals/")
        
        downloaded = []
        for gcs_path in signal_files:
            if gcs_path.endswith('.json'):
                filename = Path(gcs_path).name
                local_path = output_dir / "daily_signals" / filename
                if self.download_file(gcs_path, local_path):
                    downloaded.append(str(local_path))
        
        print(f"✅ Downloaded {len(downloaded)} signal files")
        return downloaded
    
    def download_trade_history(self, output_dir: Path) -> Optional[Dict]:
        """Download trade history"""
        print("\n📥 Downloading trade history...")
        
        # Try multiple possible locations
        trade_paths = [
            "demo_account/mock_trading_history.json",
            "demo-mode/mock_trading_data.json",
            "history/trades/"
        ]
        
        for gcs_path in trade_paths:
            if gcs_path.endswith('/'):
                # List all files in directory
                files = self.list_files(gcs_path)
                if files:
                    print(f"📁 Found {len(files)} trade history files in {gcs_path}")
                    for file_path in files:
                        filename = Path(file_path).name
                        local_path = output_dir / "trade_history" / filename
                        self.download_file(file_path, local_path)
            else:
                # Single file
                filename = Path(gcs_path).name
                local_path = output_dir / "trade_history" / filename
                if self.download_file(gcs_path, local_path):
                    try:
                        with open(local_path, 'r') as f:
                            return json.load(f)
                    except Exception as e:
                        print(f"⚠️ Error reading trade history: {e}")
        
        return None
    
    def download_comprehensive_data(self, output_dir: Path) -> List[str]:
        """Download comprehensive data files if they exist"""
        print("\n📥 Downloading comprehensive data files...")
        comp_files = self.list_files("priority_optimizer/comprehensive_data/")
        
        downloaded = []
        for gcs_path in comp_files:
            if gcs_path.endswith('.json'):
                filename = Path(gcs_path).name
                local_path = output_dir / "comprehensive_data" / filename
                if self.download_file(gcs_path, local_path):
                    downloaded.append(str(local_path))
        
        if downloaded:
            print(f"✅ Downloaded {len(downloaded)} comprehensive data files")
        else:
            print("ℹ️ No comprehensive data files found in GCS")
        
        return downloaded
    
    def get_data_summary(self) -> Dict[str, Any]:
        """Get summary of available data"""
        print("\n📊 Analyzing GCS data...")
        
        summary = {
            'signals': len(self.list_files("priority_optimizer/daily_signals/")),
            'comprehensive': len(self.list_files("priority_optimizer/comprehensive_data/")),
            'trade_history': [],
            'date_range': {'start': None, 'end': None}
        }
        
        # Get date range from signal files
        signal_files = self.list_files("priority_optimizer/daily_signals/")
        dates = []
        for file_path in signal_files:
            if file_path.endswith('.json'):
                try:
                    date_str = Path(file_path).stem.split('_')[0]
                    dates.append(date_str)
                except:
                    pass
        
        if dates:
            dates.sort()
            summary['date_range']['start'] = dates[0]
            summary['date_range']['end'] = dates[-1]
        
        return summary


def main():
    """Main recovery function"""
    print("=" * 70)
    print("GCS Data Recovery Script")
    print("=" * 70)
    
    # Setup output directory
    output_dir = Path(__file__).parent / "recovered_data"
    output_dir.mkdir(exist_ok=True)
    
    # Initialize recovery
    recovery = GCSDataRecovery()
    
    if not recovery.bucket:
        print("\n❌ Cannot proceed without GCS access")
        return
    
    # Get summary
    summary = recovery.get_data_summary()
    print(f"\n📊 Data Summary:")
    print(f"   Signals: {summary['signals']} files")
    print(f"   Comprehensive Data: {summary['comprehensive']} files")
    if summary['date_range']['start']:
        print(f"   Date Range: {summary['date_range']['start']} to {summary['date_range']['end']}")
    
    # Download signals
    signal_files = recovery.download_signals(output_dir)
    
    # Download trade history
    trade_history = recovery.download_trade_history(output_dir)
    if trade_history:
        print(f"✅ Trade history: {len(trade_history.get('closed_trades', []))} trades")
    
    # Download comprehensive data
    comp_files = recovery.download_comprehensive_data(output_dir)
    
    # Create summary report
    report = {
        'recovery_date': datetime.now().isoformat(),
        'summary': summary,
        'downloaded': {
            'signals': len(signal_files),
            'comprehensive': len(comp_files),
            'trade_history': trade_history is not None
        },
        'output_directory': str(output_dir)
    }
    
    report_path = output_dir / "recovery_report.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n✅ Recovery complete!")
    print(f"   Output directory: {output_dir}")
    print(f"   Report: {report_path}")
    print(f"\n📝 Next steps:")
    print(f"   1. Review recovered data in: {output_dir}")
    print(f"   2. Run reconstruct_89point_data.py to build comprehensive records")
    print(f"   3. Run collect_future_data.py to set up future collection")


if __name__ == "__main__":
    main()

