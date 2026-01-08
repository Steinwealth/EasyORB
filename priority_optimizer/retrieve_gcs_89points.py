#!/usr/bin/env python3
"""
Retrieve 89-Point Data from GCS
================================

Retrieves comprehensive 89-point data from Google Cloud Storage,
similar to Historical Enhancer's collection pattern.

This script can be run anytime after data collection to retrieve
and analyze the stored data.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    log.warning("Google Cloud Storage not available")

try:
    from modules.config_loader import get_cloud_config
    cloud_config = get_cloud_config()
    GCS_BUCKET_NAME = cloud_config.get("bucket_name", "easy-etrade-strategy-data")
except Exception:
    GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "easy-etrade-strategy-data")


class GCS89PointRetriever:
    """Retrieve 89-point data from GCS"""
    
    def __init__(self, bucket_name: str = GCS_BUCKET_NAME):
        self.bucket_name = bucket_name
        self.client = None
        self.bucket = None
        
        if GCS_AVAILABLE:
            try:
                self.client = storage.Client()
                self.bucket = self.client.bucket(bucket_name)
                log.info(f"✅ Connected to GCS bucket: {bucket_name}")
            except Exception as e:
                log.error(f"Failed to connect to GCS: {e}")
                self.bucket = None
        else:
            log.error("GCS not available")
    
    def list_available_dates(self) -> List[str]:
        """List all available dates with comprehensive data"""
        if not self.bucket:
            return []
        
        try:
            prefix = "priority_optimizer/comprehensive_data/"
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            
            dates = []
            for blob in blobs:
                if blob.name.endswith('.json'):
                    # Extract date from filename: YYYY-MM-DD_comprehensive_data.json
                    filename = Path(blob.name).name
                    date_str = filename.split('_')[0]
                    if date_str not in dates:
                        dates.append(date_str)
            
            dates.sort()
            return dates
            
        except Exception as e:
            log.error(f"Failed to list dates: {e}")
            return []
    
    def retrieve_date_data(self, date: str) -> Optional[Dict[str, Any]]:
        """Retrieve comprehensive data for a specific date"""
        if not self.bucket:
            return None
        
        try:
            blob_path = f"priority_optimizer/comprehensive_data/{date}_comprehensive_data.json"
            blob = self.bucket.blob(blob_path)
            
            if not blob.exists():
                log.warning(f"No data found for {date}")
                return None
            
            content = blob.download_as_text()
            data = json.loads(content)
            
            log.info(f"✅ Retrieved data for {date}: {data.get('total_records', 0)} records")
            return data
            
        except Exception as e:
            log.error(f"Failed to retrieve data for {date}: {e}")
            return None
    
    def retrieve_date_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Retrieve data for a date range"""
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        all_data = []
        current = start
        
        while current <= end:
            date_str = current.strftime('%Y-%m-%d')
            data = self.retrieve_date_data(date_str)
            if data:
                all_data.append(data)
            current += timedelta(days=1)
        
        return all_data
    
    def save_to_local(self, data: Dict[str, Any], output_dir: Path):
        """Save retrieved data to local directory"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        date = data.get('date', 'unknown')
        output_file = output_dir / f"{date}_retrieved.json"
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        log.info(f"✅ Saved to {output_file}")
        return output_file


def main():
    """Main retrieval function"""
    print("=" * 70)
    print("Retrieve 89-Point Data from GCS")
    print("=" * 70)
    
    retriever = GCS89PointRetriever()
    
    if not retriever.bucket:
        print("\n❌ Cannot connect to GCS")
        return
    
    # List available dates
    print("\n📅 Available dates:")
    dates = retriever.list_available_dates()
    if dates:
        for date in dates:
            print(f"   {date}")
    else:
        print("   No data found")
        return
    
    # Get date range or specific date
    print("\nOptions:")
    print("  1. Retrieve specific date")
    print("  2. Retrieve date range")
    print("  3. Retrieve all available dates")
    
    choice = input("\nChoice (1-3): ").strip()
    
    output_dir = Path(__file__).parent / "retrieved_data"
    output_dir.mkdir(exist_ok=True)
    
    if choice == "1":
        date = input("Enter date (YYYY-MM-DD): ").strip()
        data = retriever.retrieve_date_data(date)
        if data:
            retriever.save_to_local(data, output_dir)
            print(f"\n✅ Retrieved {data.get('total_records', 0)} records for {date}")
    
    elif choice == "2":
        start_date = input("Start date (YYYY-MM-DD): ").strip()
        end_date = input("End date (YYYY-MM-DD): ").strip()
        all_data = retriever.retrieve_date_range(start_date, end_date)
        for data in all_data:
            retriever.save_to_local(data, output_dir)
        print(f"\n✅ Retrieved {len(all_data)} date(s)")
    
    elif choice == "3":
        for date in dates:
            data = retriever.retrieve_date_data(date)
            if data:
                retriever.save_to_local(data, output_dir)
        print(f"\n✅ Retrieved all {len(dates)} date(s)")
    
    print(f"\n📁 Data saved to: {output_dir}")


if __name__ == "__main__":
    main()

