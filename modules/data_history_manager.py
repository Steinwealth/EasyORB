#!/usr/bin/env python3
"""
Data History Manager
====================

Manages historical data storage and retrieval for comprehensive analysis.
Stores all trade data, signal data, and comprehensive 89-point data collections
in Google Cloud Storage with efficient querying and retrieval capabilities.

Features:
- GCS persistence for all historical data
- Efficient data retrieval by date range, symbol, or trade ID
- Data compression and optimization
- Rolling retention policies
- Query interface for analysis

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
import json
import gzip
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

# Try to import GCS storage
try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    logging.warning("Google Cloud Storage not available - will use local storage")

log = logging.getLogger(__name__)


class DataHistoryManager:
    """
    Manages historical data storage and retrieval
    """
    
    def __init__(
        self,
        gcs_bucket: str = "easy-etrade-strategy-data",
        local_base_dir: str = "data/history"
    ):
        """
        Initialize Data History Manager
        
        Args:
            gcs_bucket: GCS bucket name for cloud storage
            local_base_dir: Local directory for data storage (fallback)
        """
        self.gcs_bucket_name = gcs_bucket
        self.local_base_dir = Path(local_base_dir)
        self.local_base_dir.mkdir(parents=True, exist_ok=True)
        
        self.storage_client = None
        self.gcs_bucket = None
        
        if GCS_AVAILABLE:
            try:
                self.storage_client = storage.Client()
                self.gcs_bucket = self.storage_client.bucket(gcs_bucket)
                log.info(f"✅ Data History Manager initialized (GCS: {gcs_bucket})")
            except Exception as e:
                log.warning(f"⚠️ Data History Manager initialized (Local only - GCS error: {e})")
        else:
            log.info("ℹ️ Data History Manager initialized (Local storage only)")
    
    def save_trade_history(
        self,
        date: str,
        trade_data: Dict[str, Any],
        data_type: str = "trades"
    ) -> bool:
        """
        Save trade history data
        
        Args:
            date: Date string (YYYY-MM-DD)
            trade_data: Trade data dictionary
            data_type: Type of data ('trades', 'signals', 'comprehensive')
        
        Returns:
            True if saved successfully
        """
        try:
            # Prepare data
            data = {
                'date': date,
                'timestamp': datetime.utcnow().isoformat(),
                'data_type': data_type,
                'data': trade_data
            }
            
            # Save to GCS
            if self.gcs_bucket:
                blob_path = f"history/{data_type}/{date}_{data_type}.json.gz"
                blob = self.gcs_bucket.blob(blob_path)
                
                # Compress and upload
                json_str = json.dumps(data, default=str)
                compressed = gzip.compress(json_str.encode('utf-8'))
                blob.upload_from_string(compressed, content_type="application/gzip")
                
                log.debug(f"✅ Saved {data_type} history to GCS: {blob_path}")
            
            # Also save locally
            local_file = self.local_base_dir / data_type / f"{date}_{data_type}.json"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(local_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            
            return True
            
        except Exception as e:
            log.error(f"Failed to save trade history: {e}", exc_info=True)
            return False
    
    def load_trade_history(
        self,
        date: str,
        data_type: str = "trades"
    ) -> Optional[Dict[str, Any]]:
        """
        Load trade history data for a specific date
        
        Args:
            date: Date string (YYYY-MM-DD)
            data_type: Type of data ('trades', 'signals', 'comprehensive')
        
        Returns:
            Trade data dictionary or None if not found
        """
        try:
            # Try GCS first
            if self.gcs_bucket:
                blob_path = f"history/{data_type}/{date}_{data_type}.json.gz"
                blob = self.gcs_bucket.blob(blob_path)
                
                if blob.exists():
                    compressed = blob.download_as_bytes()
                    json_str = gzip.decompress(compressed).decode('utf-8')
                    data = json.loads(json_str)
                    log.debug(f"✅ Loaded {data_type} history from GCS: {blob_path}")
                    return data.get('data')
            
            # Fallback to local
            local_file = self.local_base_dir / data_type / f"{date}_{data_type}.json"
            if local_file.exists():
                with open(local_file, 'r') as f:
                    data = json.load(f)
                log.debug(f"✅ Loaded {data_type} history from local: {local_file}")
                return data.get('data')
            
            return None
            
        except Exception as e:
            log.error(f"Failed to load trade history: {e}", exc_info=True)
            return None
    
    def query_trade_history(
        self,
        start_date: str,
        end_date: str,
        symbol: Optional[str] = None,
        data_type: str = "trades"
    ) -> List[Dict[str, Any]]:
        """
        Query trade history for a date range
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            symbol: Optional symbol filter
            data_type: Type of data ('trades', 'signals', 'comprehensive')
        
        Returns:
            List of trade data dictionaries
        """
        try:
            results = []
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            
            current = start
            while current <= end:
                date_str = current.strftime('%Y-%m-%d')
                data = self.load_trade_history(date_str, data_type)
                
                if data:
                    if symbol:
                        # Filter by symbol if provided
                        if isinstance(data, list):
                            filtered = [d for d in data if d.get('symbol') == symbol]
                            results.extend(filtered)
                        elif isinstance(data, dict) and data.get('symbol') == symbol:
                            results.append(data)
                    else:
                        # Include all data
                        if isinstance(data, list):
                            results.extend(data)
                        else:
                            results.append(data)
                
                current += timedelta(days=1)
            
            log.info(f"✅ Queried {data_type} history: {len(results)} records from {start_date} to {end_date}")
            return results
            
        except Exception as e:
            log.error(f"Failed to query trade history: {e}", exc_info=True)
            return []
    
    def get_data_summary(
        self,
        start_date: str,
        end_date: str
    ) -> Dict[str, Any]:
        """
        Get summary statistics for a date range
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            Summary statistics dictionary
        """
        try:
            trades = self.query_trade_history(start_date, end_date, data_type="trades")
            signals = self.query_trade_history(start_date, end_date, data_type="signals")
            comprehensive = self.query_trade_history(start_date, end_date, data_type="comprehensive")
            
            summary = {
                'date_range': {
                    'start': start_date,
                    'end': end_date
                },
                'trades': {
                    'total': len(trades),
                    'winners': len([t for t in trades if t.get('win', False)]),
                    'losers': len([t for t in trades if not t.get('win', False)]),
                    'total_pnl': sum(t.get('pnl_dollars', 0) for t in trades),
                    'avg_pnl': sum(t.get('pnl_dollars', 0) for t in trades) / len(trades) if trades else 0
                },
                'signals': {
                    'total': len(signals),
                    'executed': len([s for s in signals if s.get('executed', False)]),
                    'filtered': len([s for s in signals if s.get('filtered', False)])
                },
                'comprehensive': {
                    'total': len(comprehensive),
                    'data_points_per_record': 89
                }
            }
            
            return summary
            
        except Exception as e:
            log.error(f"Failed to get data summary: {e}", exc_info=True)
            return {}


# Singleton instance
_data_history_manager = None

def get_data_history_manager(
    gcs_bucket: str = "easy-etrade-strategy-data",
    local_base_dir: str = "data/history"
) -> DataHistoryManager:
    """Get or create Data History Manager singleton"""
    global _data_history_manager
    if _data_history_manager is None:
        _data_history_manager = DataHistoryManager(
            gcs_bucket=gcs_bucket,
            local_base_dir=local_base_dir
        )
    return _data_history_manager

