#!/usr/bin/env python3
"""
Comprehensive Data Collector - 89 Data Points Collection
=========================================================

REST-based data collection system that collects 89 comprehensive data points
from trade collection each trading session for Priority Optimizer analysis.

Collects:
- 89 technical indicators (price, momentum, trend, volatility, volume, patterns)
- Multi-factor ranking data (VWAP, RS vs SPY, ORB Volume, Confidence, RSI, ORB Range)
- Trade execution data (entry, exit, P&L)
- Market context data (SPY, market conditions)

This enables comprehensive analysis of:
- Ranking formula effectiveness (Rev 00108: Multi-Factor Ranking v2.1)
- Trade performance optimization
- Signal filtering effectiveness
- Exit strategy optimization

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import logging
import json
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import asyncio

# Try to import GCS storage (optional)
try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    logging.warning("Google Cloud Storage not available - will use local storage")

log = logging.getLogger(__name__)


class ComprehensiveDataCollector:
    """
    Collects 89 comprehensive data points from trade collection each trading session
    
    Data Points Collected:
    1. Price Data (5): open, high, low, close, volume
    2. Moving Averages (5): sma_20, sma_50, sma_200, ema_12, ema_26
    3. Momentum Indicators (7): rsi, rsi_14, rsi_21, macd, macd_signal, macd_histogram, momentum_10
    4. Volatility Indicators (7): atr, bollinger_upper, bollinger_middle, bollinger_lower, bollinger_width, bollinger_position, volatility
    5. Volume Indicators (4): volume_ratio, volume_sma, obv, ad_line
    6. Pattern Recognition (4): doji, hammer, engulfing, morning_star
    7. VWAP Indicators (2): vwap, vwap_distance_pct
    8. Relative Strength (1): rs_vs_spy
    9. ORB Data (6): orb_high, orb_low, orb_open, orb_close, orb_volume, orb_range_pct
    10. Market Context (2): spy_price, spy_change_pct
    11. Trade Data (15): symbol, trade_id, entry_price, exit_price, entry_time, exit_time, shares, position_value, peak_price, peak_pct, pnl_dollars, pnl_pct, exit_reason, win, holding_minutes
    12. Ranking Data (6): rank, priority_score, confidence, orb_volume_ratio, exec_volume_ratio, category
    13. Risk Management (8): current_stop_loss, stop_loss_distance_pct, opening_bar_protection_active, trailing_activated, trailing_distance_pct, breakeven_activated, gap_risk_pct, entry_bar_volatility
    14. Market Conditions (5): market_regime, volatility_regime, trend_direction, volume_regime, momentum_regime
    15. Additional Indicators (16): stoch_k, stoch_d, williams_r, cci, adx, plus_di, minus_di, aroon_up, aroon_down, mfi, cmf, roc, ppo, tsi, ult_osc, ichimoku_base
    
    Total: 89 data points
    """
    
    def __init__(
        self,
        base_dir: str = "priority_optimizer/comprehensive_data",
        gcs_bucket: Optional[str] = None,
        gcs_prefix: str = "priority_optimizer/comprehensive_data"
    ):
        """
        Initialize Comprehensive Data Collector
        
        Args:
            base_dir: Local directory for data storage
            gcs_bucket: GCS bucket name (optional, for cloud storage)
            gcs_prefix: GCS prefix path for data files
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        self.gcs_bucket_name = gcs_bucket
        self.gcs_prefix = gcs_prefix
        self.gcs_client = None
        
        if GCS_AVAILABLE and gcs_bucket:
            try:
                self.gcs_client = storage.Client()
                self.gcs_bucket = self.gcs_client.bucket(gcs_bucket)
                log.info(f"✅ GCS storage enabled: {gcs_bucket}/{gcs_prefix}")
            except Exception as e:
                log.warning(f"Failed to initialize GCS client: {e}")
                self.gcs_bucket = None
        
        # Storage for today's comprehensive data
        self.comprehensive_data: List[Dict[str, Any]] = []
        self.today_date = datetime.now().strftime('%Y-%m-%d')
        
        log.info(f"✅ Comprehensive Data Collector initialized (89 data points, data dir: {self.base_dir})")
    
    def collect_trade_data(
        self,
        symbol: str,
        trade_id: str,
        market_data: Dict[str, Any],
        trade_data: Dict[str, Any],
        ranking_data: Dict[str, Any],
        risk_data: Dict[str, Any],
        market_conditions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Collect comprehensive 89 data points for a trade
        
        Args:
            symbol: Stock symbol
            trade_id: Unique trade identifier
            market_data: Market data with technical indicators
            trade_data: Trade execution data (entry, exit, P&L)
            ranking_data: Ranking and priority data
            risk_data: Risk management data
            market_conditions: Market regime and conditions
        
        Returns:
            Dictionary with all 89 data points
        """
        try:
            # Build comprehensive data record
            comprehensive_record = {
                # Timestamp
                'timestamp': datetime.utcnow().isoformat(),
                'date': self.today_date,
                
                # Trade identification
                'symbol': symbol,
                'trade_id': trade_id,
                
                # 1. Price Data (5)
                'open': market_data.get('open') or market_data.get('open_price', 0.0),
                'high': market_data.get('high') or market_data.get('high_today', 0.0),
                'low': market_data.get('low') or market_data.get('low_today', 0.0),
                'close': market_data.get('close') or market_data.get('current_price', 0.0),
                'volume': market_data.get('volume') or market_data.get('volume_today', 0),
                
                # 2. Moving Averages (5)
                'sma_20': market_data.get('sma_20', 0.0),
                'sma_50': market_data.get('sma_50', 0.0),
                'sma_200': market_data.get('sma_200', 0.0),
                'ema_12': market_data.get('ema_12', 0.0),
                'ema_26': market_data.get('ema_26', 0.0),
                
                # 3. Momentum Indicators (7)
                'rsi': market_data.get('rsi') or market_data.get('rsi_14', 0.0),
                'rsi_14': market_data.get('rsi_14') or market_data.get('rsi', 0.0),
                'rsi_21': market_data.get('rsi_21', 0.0),
                'macd': market_data.get('macd', 0.0),
                'macd_signal': market_data.get('macd_signal', 0.0),
                'macd_histogram': market_data.get('macd_histogram', 0.0),
                'momentum_10': market_data.get('momentum_10') or market_data.get('momentum', 0.0),
                
                # 4. Volatility Indicators (7)
                'atr': market_data.get('atr', 0.0),
                'bollinger_upper': market_data.get('bollinger_upper', 0.0),
                'bollinger_middle': market_data.get('bollinger_middle', 0.0),
                'bollinger_lower': market_data.get('bollinger_lower', 0.0),
                'bollinger_width': market_data.get('bollinger_width', 0.0),
                'bollinger_position': market_data.get('bollinger_position', 0.0),
                'volatility': market_data.get('volatility') or market_data.get('current_volatility', 0.0),
                
                # 5. Volume Indicators (4)
                'volume_ratio': market_data.get('volume_ratio', 0.0),
                'volume_sma': market_data.get('volume_sma', 0.0),
                'obv': market_data.get('obv', 0.0),
                'ad_line': market_data.get('ad_line', 0.0),
                
                # 6. Pattern Recognition (4)
                'doji': market_data.get('doji', False),
                'hammer': market_data.get('hammer', False),
                'engulfing': market_data.get('engulfing', False),
                'morning_star': market_data.get('morning_star', False),
                
                # 7. VWAP Indicators (2)
                'vwap': market_data.get('vwap', 0.0),
                'vwap_distance_pct': market_data.get('vwap_distance_pct', 0.0),
                
                # 8. Relative Strength (1)
                'rs_vs_spy': market_data.get('rs_vs_spy', 0.0),
                
                # 9. ORB Data (6)
                'orb_high': market_data.get('orb_high', 0.0),
                'orb_low': market_data.get('orb_low', 0.0),
                'orb_open': market_data.get('orb_open', 0.0),
                'orb_close': market_data.get('orb_close', 0.0),
                'orb_volume': market_data.get('orb_volume', 0),
                'orb_range_pct': market_data.get('orb_range_pct', 0.0),
                
                # 10. Market Context (2)
                'spy_price': market_data.get('spy_price', 0.0),
                'spy_change_pct': market_data.get('spy_change_pct', 0.0),
                
                # 11. Trade Data (15)
                'entry_price': trade_data.get('entry_price', 0.0),
                'exit_price': trade_data.get('exit_price', 0.0),
                'entry_time': trade_data.get('entry_time', ''),
                'exit_time': trade_data.get('exit_time', ''),
                'shares': trade_data.get('shares', 0),
                'position_value': trade_data.get('position_value', 0.0),
                'peak_price': trade_data.get('peak_price', 0.0),
                'peak_pct': trade_data.get('peak_pct', 0.0),
                'pnl_dollars': trade_data.get('pnl_dollars', 0.0),
                'pnl_pct': trade_data.get('pnl_pct', 0.0),
                'exit_reason': trade_data.get('exit_reason', ''),
                'win': trade_data.get('win', False),
                'holding_minutes': trade_data.get('holding_minutes', 0.0),
                'entry_bar_volatility': trade_data.get('entry_bar_volatility', 0.0),
                'time_weighted_peak': trade_data.get('time_weighted_peak', 0.0),
                
                # 12. Ranking Data (6)
                'rank': ranking_data.get('rank', 0),
                'priority_score': ranking_data.get('priority_score', 0.0),
                'confidence': ranking_data.get('confidence', 0.0),
                'orb_volume_ratio': ranking_data.get('orb_volume_ratio', 0.0),
                'exec_volume_ratio': ranking_data.get('exec_volume_ratio', 0.0),
                'category': ranking_data.get('category', ''),
                
                # 13. Risk Management (8)
                'current_stop_loss': risk_data.get('current_stop_loss', 0.0),
                'stop_loss_distance_pct': risk_data.get('stop_loss_distance_pct', 0.0),
                'opening_bar_protection_active': risk_data.get('opening_bar_protection_active', False),
                'trailing_activated': risk_data.get('trailing_activated', False),
                'trailing_distance_pct': risk_data.get('trailing_distance_pct', 0.0),
                'breakeven_activated': risk_data.get('breakeven_activated', False),
                'gap_risk_pct': risk_data.get('gap_risk_pct', 0.0),
                'max_adverse_excursion': risk_data.get('max_adverse_excursion', 0.0),
                
                # 14. Market Conditions (5)
                'market_regime': market_conditions.get('market_regime', ''),
                'volatility_regime': market_conditions.get('volatility_regime', ''),
                'trend_direction': market_conditions.get('trend_direction', ''),
                'volume_regime': market_conditions.get('volume_regime', ''),
                'momentum_regime': market_conditions.get('momentum_regime', ''),
                
                # 15. Additional Indicators (16) - Extended technical indicators
                'stoch_k': market_data.get('stoch_k', 0.0),
                'stoch_d': market_data.get('stoch_d', 0.0),
                'williams_r': market_data.get('williams_r', 0.0),
                'cci': market_data.get('cci', 0.0),
                'adx': market_data.get('adx', 0.0),
                'plus_di': market_data.get('plus_di', 0.0),
                'minus_di': market_data.get('minus_di', 0.0),
                'aroon_up': market_data.get('aroon_up', 0.0),
                'aroon_down': market_data.get('aroon_down', 0.0),
                'mfi': market_data.get('mfi', 0.0),
                'cmf': market_data.get('cmf', 0.0),
                'roc': market_data.get('roc', 0.0),
                'ppo': market_data.get('ppo', 0.0),
                'tsi': market_data.get('tsi', 0.0),
                'ult_osc': market_data.get('ult_osc', 0.0),
                'ichimoku_base': market_data.get('ichimoku_base', 0.0),
            }
            
            # Add to collection
            self.comprehensive_data.append(comprehensive_record)
            
            log.debug(f"📊 Collected 89 data points for {symbol} ({trade_id})")
            
            return comprehensive_record
            
        except Exception as e:
            log.error(f"Failed to collect comprehensive data for {symbol}: {e}", exc_info=True)
            return {}
    
    async def save_daily_data(self, format: str = 'both'):
        """
        Save all collected comprehensive data to file(s)
        
        Args:
            format: 'json', 'csv', or 'both' (default)
        """
        try:
            if not self.comprehensive_data:
                log.warning("No comprehensive data to save")
                return None
            
            # Create filename
            filename_base = self.base_dir / f"{self.today_date}_comprehensive_data"
            
            saved_files = {}
            
            # Save JSON (complete data with all 89 fields)
            if format in ['json', 'both']:
                json_file = filename_base.with_suffix('.json')
                
                data = {
                    'date': self.today_date,
                    'total_records': len(self.comprehensive_data),
                    'data_points_per_record': 89,
                    'records': self.comprehensive_data
                }
                
                with open(json_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                
                saved_files['json_file'] = str(json_file)
                log.info(f"✅ Saved JSON data: {json_file} ({len(self.comprehensive_data)} records)")
                
                # Upload to GCS if available
                if self.gcs_bucket:
                    try:
                        blob_path = f"{self.gcs_prefix}/{self.today_date}_comprehensive_data.json"
                        blob = self.gcs_bucket.blob(blob_path)
                        blob.upload_from_string(
                            json.dumps(data, indent=2, default=str),
                            content_type="application/json"
                        )
                        log.info(f"✅ Uploaded to GCS: {blob_path}")
                    except Exception as e:
                        log.warning(f"Failed to upload to GCS: {e}")
            
            # Save CSV (Priority Optimizer format)
            if format in ['csv', 'both']:
                csv_file = filename_base.with_suffix('.csv')
                
                # CSV Headers (all 89 fields)
                headers = [
                    'timestamp', 'date', 'symbol', 'trade_id',
                    # Price Data
                    'open', 'high', 'low', 'close', 'volume',
                    # Moving Averages
                    'sma_20', 'sma_50', 'sma_200', 'ema_12', 'ema_26',
                    # Momentum Indicators
                    'rsi', 'rsi_14', 'rsi_21', 'macd', 'macd_signal', 'macd_histogram', 'momentum_10',
                    # Volatility Indicators
                    'atr', 'bollinger_upper', 'bollinger_middle', 'bollinger_lower', 'bollinger_width', 'bollinger_position', 'volatility',
                    # Volume Indicators
                    'volume_ratio', 'volume_sma', 'obv', 'ad_line',
                    # Pattern Recognition
                    'doji', 'hammer', 'engulfing', 'morning_star',
                    # VWAP Indicators
                    'vwap', 'vwap_distance_pct',
                    # Relative Strength
                    'rs_vs_spy',
                    # ORB Data
                    'orb_high', 'orb_low', 'orb_open', 'orb_close', 'orb_volume', 'orb_range_pct',
                    # Market Context
                    'spy_price', 'spy_change_pct',
                    # Trade Data
                    'entry_price', 'exit_price', 'entry_time', 'exit_time', 'shares', 'position_value',
                    'peak_price', 'peak_pct', 'pnl_dollars', 'pnl_pct', 'exit_reason', 'win', 'holding_minutes',
                    'entry_bar_volatility', 'time_weighted_peak',
                    # Ranking Data
                    'rank', 'priority_score', 'confidence', 'orb_volume_ratio', 'exec_volume_ratio', 'category',
                    # Risk Management
                    'current_stop_loss', 'stop_loss_distance_pct', 'opening_bar_protection_active',
                    'trailing_activated', 'trailing_distance_pct', 'breakeven_activated', 'gap_risk_pct', 'max_adverse_excursion',
                    # Market Conditions
                    'market_regime', 'volatility_regime', 'trend_direction', 'volume_regime', 'momentum_regime',
                    # Additional Indicators
                    'stoch_k', 'stoch_d', 'williams_r', 'cci', 'adx', 'plus_di', 'minus_di',
                    'aroon_up', 'aroon_down', 'mfi', 'cmf', 'roc', 'ppo', 'tsi', 'ult_osc', 'ichimoku_base'
                ]
                
                with open(csv_file, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
                    writer.writeheader()
                    
                    for record in self.comprehensive_data:
                        writer.writerow(record)
                
                saved_files['csv_file'] = str(csv_file)
                log.info(f"✅ Saved CSV data: {csv_file} ({len(self.comprehensive_data)} records, 89 fields)")
            
            return saved_files
            
        except Exception as e:
            log.error(f"Failed to save comprehensive data: {e}", exc_info=True)
            return None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of collected data"""
        return {
            'date': self.today_date,
            'total_records': len(self.comprehensive_data),
            'data_points_per_record': 89,
            'symbols': list(set(r['symbol'] for r in self.comprehensive_data)),
            'total_trades': len(self.comprehensive_data)
        }
    
    def reset_daily_data(self):
        """Reset for new trading day"""
        self.comprehensive_data = []
        self.today_date = datetime.now().strftime('%Y-%m-%d')
        log.info("🔄 Comprehensive Data Collector reset for new day")


# Singleton instance
_comprehensive_data_collector = None

def get_comprehensive_data_collector(
    base_dir: str = "priority_optimizer/comprehensive_data",
    gcs_bucket: Optional[str] = None,
    gcs_prefix: str = "priority_optimizer/comprehensive_data"
) -> ComprehensiveDataCollector:
    """Get or create Comprehensive Data Collector singleton"""
    global _comprehensive_data_collector
    if _comprehensive_data_collector is None:
        _comprehensive_data_collector = ComprehensiveDataCollector(
            base_dir=base_dir,
            gcs_bucket=gcs_bucket,
            gcs_prefix=gcs_prefix
        )
    return _comprehensive_data_collector

