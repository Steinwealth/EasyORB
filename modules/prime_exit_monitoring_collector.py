"""
Prime Exit Monitoring Data Collector (TEMPORARY)

Purpose: Collect essential trade monitoring data for exit optimization
Duration: Temporary - will be removed after exit settings are optimized
Data Collected: Only data needed for exit triggers (price, RSI, volume, ATR, etc.)
NOT: All 89 technical indicators (only collected on entry via Priority Enhancer)

Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from google.cloud import storage

log = logging.getLogger(__name__)

# TEMPORARY FEATURE FLAG - Set to False to disable data collection
EXIT_MONITORING_ENABLED = os.getenv("EXIT_MONITORING_ENABLED", "true").lower() == "true"

@dataclass
class ExitMonitoringData:
    """Exit monitoring data - 35 technical indicators collected every 30 seconds for exit optimization"""
    # Timestamp
    timestamp: str
    
    # Trade identification
    symbol: str
    trade_id: str
    
    # Price data (essential for all exits)
    current_price: float
    entry_price: float
    peak_price: float
    lowest_price: float
    
    # P&L data (essential for profit capture analysis)
    unrealized_pnl: float
    unrealized_pnl_pct: float
    peak_pnl: float
    peak_pnl_pct: float
    profit_capture_pct: float  # current_pnl / peak_pnl
    
    # Time data (essential for time-based exits)
    entry_time: str
    holding_minutes: float
    
    # Stop loss data (essential for stop loss exits)
    current_stop_loss: float
    stop_loss_distance_pct: float
    opening_bar_protection_active: bool
    
    # Trailing stop data (essential for trailing exits)
    trailing_activated: bool
    trailing_distance_pct: float
    breakeven_activated: bool
    
    # Gap risk data (essential for gap risk exits)
    gap_risk_pct: float
    entry_bar_volatility: float
    time_weighted_peak: float
    
    # Technical indicators (35 fields for exit optimization)
    # Momentum Indicators
    rsi: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    momentum_10: Optional[float] = None
    
    # Trend Indicators
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    
    # Volatility Indicators
    atr: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_middle: Optional[float] = None
    bollinger_lower: Optional[float] = None
    bollinger_width: Optional[float] = None
    bollinger_position: Optional[float] = None
    volatility: Optional[float] = None  # Current volatility (matches comprehensive_data.json)
    
    # Volume Indicators
    volume: Optional[int] = None
    volume_ratio: Optional[float] = None
    volume_today: Optional[int] = None
    
    # VWAP Indicators
    vwap: Optional[float] = None
    vwap_distance_pct: Optional[float] = None
    
    # Relative Strength
    rs_vs_spy: Optional[float] = None
    
    # Market Context
    spy_price: Optional[float] = None
    spy_change_pct: Optional[float] = None
    
    # Price Data
    open_price: Optional[float] = None
    high_today: Optional[float] = None
    low_today: Optional[float] = None
    
    # Exit decision factors (what would trigger exits?)
    would_exit_gap_risk: bool = False
    would_exit_trailing: bool = False
    would_exit_stop_loss: bool = False
    would_exit_rsi: bool = False
    would_exit_volume: bool = False
    would_exit_timeout: bool = False
    
    # Exit reason (if position closed)
    exit_reason: Optional[str] = None
    exit_price: Optional[float] = None


class PrimeExitMonitoringCollector:
    """
    Exit monitoring data collector (TEMPORARY)
    
    Collects 35 technical indicators on every 30-second monitoring call for exit optimization:
    - Price movements and P&L tracking
    - Exit decision factors
    - 35 technical indicators (RSI, MACD, Moving Averages, Bollinger, VWAP, Volume, etc.)
    
    Note:
    - 89 technical indicators are collected at trade execution (7:30 AM) for Priority Ranking
    - 35 technical indicators are collected on each monitoring call for exit optimization
    - This allows daily review of exit settings to optimize profit capture
    """
    
    def __init__(self, gcs_bucket: str = "easy-etrade-strategy-data"):
        self.enabled = EXIT_MONITORING_ENABLED
        self.gcs_bucket = gcs_bucket
        self.storage_client = None
        
        # In-memory buffer (flushed to GCS periodically)
        self.monitoring_buffer: Dict[str, List[ExitMonitoringData]] = {}
        
        # Rev 00170: Track last flush time for periodic flushing
        self.last_periodic_flush: Optional[datetime] = None
        self.periodic_flush_interval_minutes = 5  # Flush every 5 minutes
        
        # Rev 00170: Track last collection time for health monitoring
        self.last_collection_time: Optional[datetime] = None
        
        if self.enabled:
            try:
                self.storage_client = storage.Client()
                log.info("✅ Exit Monitoring Collector initialized (ENABLED)")
            except Exception as e:
                log.warning(f"⚠️ Exit Monitoring Collector initialized (DISABLED - GCS error: {e})")
                self.enabled = False
        else:
            log.info("ℹ️ Exit Monitoring Collector initialized (DISABLED via env var)")
    
    def collect_monitoring_data(
        self,
        symbol: str,
        trade_id: str,
        position_state: Any,  # PositionState from stealth trailing
        market_data: Dict[str, Any],
        exit_decision_factors: Optional[Dict[str, Any]] = None
    ) -> Optional[ExitMonitoringData]:
        """
        Collect essential monitoring data for exit optimization
        
        Args:
            symbol: Stock symbol
            trade_id: Unique trade identifier
            position_state: PositionState from stealth trailing system
            market_data: Current market data for the symbol
            exit_decision_factors: Optional dict with exit decision analysis
        
        Returns:
            ExitMonitoringData if collection successful, None otherwise
        """
        if not self.enabled:
            return None
        
        try:
            # Calculate essential metrics
            current_price = position_state.current_price
            entry_price = position_state.entry_price
            peak_price = position_state.highest_price
            lowest_price = position_state.lowest_price
            
            # P&L calculations
            unrealized_pnl = position_state.unrealized_pnl
            unrealized_pnl_pct = position_state.unrealized_pnl_pct
            peak_pnl = position_state.max_favorable
            peak_pnl_pct = (peak_price - entry_price) / entry_price if entry_price > 0 else 0.0
            profit_capture_pct = (unrealized_pnl / peak_pnl) if peak_pnl > 0 else 0.0
            
            # Time calculations
            holding_minutes = (datetime.utcnow() - position_state.entry_time).total_seconds() / 60
            
            # Stop loss data
            current_stop_loss = position_state.current_stop_loss
            stop_loss_distance_pct = abs((current_price - current_stop_loss) / current_price) if current_price > 0 else 0.0
            opening_bar_protection_active = holding_minutes < 30
            
            # Trailing data
            trailing_activated = position_state.trailing_activated
            trailing_distance_pct = abs((peak_price - current_stop_loss) / peak_price) if peak_price > 0 and trailing_activated else 0.0
            breakeven_activated = position_state.breakeven_achieved
            
            # Gap risk data
            gap_risk_pct = (current_price - peak_price) / peak_price if peak_price > 0 else 0.0
            entry_bar_volatility = getattr(position_state, 'entry_bar_volatility', 0.0)
            
            # Time-weighted peak (last 45 minutes)
            time_weighted_peak = peak_price
            if hasattr(position_state, 'price_history') and position_state.price_history:
                now = datetime.utcnow()
                recent_cutoff = now - timedelta(minutes=45)
                recent_prices = [
                    entry.get('price', 0) for entry in position_state.price_history
                    if isinstance(entry, dict) and entry.get('timestamp', now) >= recent_cutoff
                ]
                if recent_prices:
                    time_weighted_peak = max(recent_prices)
            
            # Technical indicators (35 fields for exit optimization)
            # Momentum Indicators
            rsi = market_data.get('rsi') or market_data.get('rsi_14')
            rsi_14 = market_data.get('rsi_14') or market_data.get('rsi')
            macd = market_data.get('macd')
            macd_signal = market_data.get('macd_signal')
            macd_histogram = market_data.get('macd_histogram')
            momentum_10 = market_data.get('momentum_10') or market_data.get('momentum')
            
            # Trend Indicators
            sma_20 = market_data.get('sma_20')
            sma_50 = market_data.get('sma_50')
            ema_12 = market_data.get('ema_12')
            ema_26 = market_data.get('ema_26')
            
            # Volatility Indicators
            atr = market_data.get('atr') or getattr(position_state, 'atr', None)
            bollinger_upper = market_data.get('bollinger_upper')
            bollinger_middle = market_data.get('bollinger_middle')
            bollinger_lower = market_data.get('bollinger_lower')
            bollinger_width = market_data.get('bollinger_width')
            bollinger_position = market_data.get('bollinger_position')
            volatility = market_data.get('volatility') or market_data.get('current_volatility')
            
            # Volume Indicators
            volume = market_data.get('volume')
            volume_ratio = market_data.get('volume_ratio')
            volume_today = market_data.get('volume_today')
            
            # VWAP Indicators
            vwap = market_data.get('vwap')
            vwap_distance_pct = market_data.get('vwap_distance_pct')
            
            # Relative Strength
            rs_vs_spy = market_data.get('rs_vs_spy')
            
            # Market Context
            spy_price = market_data.get('spy_price')
            spy_change_pct = market_data.get('spy_change_pct')
            
            # Price Data
            open_price = market_data.get('open') or market_data.get('open_price')
            high_today = market_data.get('high') or market_data.get('high_today')
            low_today = market_data.get('low') or market_data.get('low_today')
            
            # Exit decision factors (from exit condition checks)
            exit_factors = exit_decision_factors or {}
            would_exit_gap_risk = exit_factors.get('would_exit_gap_risk', False)
            would_exit_trailing = exit_factors.get('would_exit_trailing', False)
            would_exit_stop_loss = exit_factors.get('would_exit_stop_loss', False)
            would_exit_rsi = exit_factors.get('would_exit_rsi', False)
            would_exit_volume = exit_factors.get('would_exit_volume', False)
            would_exit_timeout = exit_factors.get('would_exit_timeout', False)
            
            # Create monitoring data record
            monitoring_data = ExitMonitoringData(
                timestamp=datetime.utcnow().isoformat(),
                symbol=symbol,
                trade_id=trade_id,
                current_price=current_price,
                entry_price=entry_price,
                peak_price=peak_price,
                lowest_price=lowest_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                peak_pnl=peak_pnl,
                peak_pnl_pct=peak_pnl_pct,
                profit_capture_pct=profit_capture_pct,
                entry_time=position_state.entry_time.isoformat(),
                holding_minutes=holding_minutes,
                current_stop_loss=current_stop_loss,
                stop_loss_distance_pct=stop_loss_distance_pct,
                opening_bar_protection_active=opening_bar_protection_active,
                trailing_activated=trailing_activated,
                trailing_distance_pct=trailing_distance_pct,
                breakeven_activated=breakeven_activated,
                gap_risk_pct=gap_risk_pct,
                entry_bar_volatility=entry_bar_volatility,
                time_weighted_peak=time_weighted_peak,
                # Technical indicators (35 fields)
                rsi=rsi,
                rsi_14=rsi_14,
                macd=macd,
                macd_signal=macd_signal,
                macd_histogram=macd_histogram,
                momentum_10=momentum_10,
                sma_20=sma_20,
                sma_50=sma_50,
                ema_12=ema_12,
                ema_26=ema_26,
                atr=atr,
                bollinger_upper=bollinger_upper,
                bollinger_middle=bollinger_middle,
                bollinger_lower=bollinger_lower,
                bollinger_width=bollinger_width,
                bollinger_position=bollinger_position,
                volatility=volatility,
                volume=volume,
                volume_ratio=volume_ratio,
                volume_today=volume_today,
                vwap=vwap,
                vwap_distance_pct=vwap_distance_pct,
                rs_vs_spy=rs_vs_spy,
                spy_price=spy_price,
                spy_change_pct=spy_change_pct,
                open_price=open_price,
                high_today=high_today,
                low_today=low_today,
                would_exit_gap_risk=would_exit_gap_risk,
                would_exit_trailing=would_exit_trailing,
                would_exit_stop_loss=would_exit_stop_loss,
                would_exit_rsi=would_exit_rsi,
                would_exit_volume=would_exit_volume,
                would_exit_timeout=would_exit_timeout
            )
            
            # Add to buffer
            if symbol not in self.monitoring_buffer:
                self.monitoring_buffer[symbol] = []
            self.monitoring_buffer[symbol].append(monitoring_data)
            
            # Rev 00170: Update last collection time for health monitoring
            self.last_collection_time = datetime.utcnow()
            
            # Rev 00148: Flush buffer more frequently for better data freshness
            # Flush every 5 records (instead of 10) to ensure more up-to-date data
            # Also flush if breakeven or trailing was just activated (critical state change)
            should_flush = False
            if len(self.monitoring_buffer[symbol]) >= 5:
                should_flush = True
            elif breakeven_activated and not any(r.breakeven_activated for r in self.monitoring_buffer[symbol][:-1]):
                # Breakeven just activated - flush immediately to capture state change
                should_flush = True
                log.debug(f"📊 Flushing Exit Monitoring data for {symbol} - breakeven just activated")
            elif trailing_activated and not any(r.trailing_activated for r in self.monitoring_buffer[symbol][:-1]):
                # Trailing just activated - flush immediately to capture state change
                should_flush = True
                log.debug(f"📊 Flushing Exit Monitoring data for {symbol} - trailing just activated")
            
            if should_flush:
                self._flush_symbol_data(symbol)
            
            # Rev 00170: Periodic flush check (every 5 minutes)
            self._check_periodic_flush()
            
            return monitoring_data
            
        except Exception as e:
            log.error(f"❌ Error collecting monitoring data for {symbol}: {e}")
            return None
    
    def record_exit(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        final_pnl: float,
        final_pnl_pct: float
    ) -> None:
        """Record exit data for the final monitoring record"""
        if not self.enabled:
            return
        
        try:
            if symbol in self.monitoring_buffer and self.monitoring_buffer[symbol]:
                # Update the last record with exit data
                last_record = self.monitoring_buffer[symbol][-1]
                last_record.exit_reason = exit_reason
                last_record.exit_price = exit_price
                # Note: P&L is already in the record, but we can add final confirmation
                
                # Rev 00170: Flush immediately on exit (even if buffer < 5 records)
                log.info(f"📊 Flushing exit monitoring data for {symbol} on position close")
                self._flush_symbol_data(symbol)
            else:
                # Rev 00170: If no buffer data, create a final record
                log.warning(f"⚠️ No monitoring buffer data for {symbol} at exit - creating final record")
                # Create a minimal exit record
                final_record = ExitMonitoringData(
                    timestamp=datetime.utcnow().isoformat(),
                    symbol=symbol,
                    trade_id=f"{symbol}_{datetime.utcnow().strftime('%Y%m%d')}",
                    current_price=exit_price,
                    entry_price=0.0,  # Unknown if not in buffer
                    peak_price=exit_price,
                    lowest_price=exit_price,
                    unrealized_pnl=final_pnl,
                    unrealized_pnl_pct=final_pnl_pct,
                    peak_pnl=final_pnl,
                    peak_pnl_pct=final_pnl_pct,
                    profit_capture_pct=1.0,
                    entry_time=datetime.utcnow().isoformat(),
                    holding_minutes=0.0,
                    current_stop_loss=exit_price,
                    stop_loss_distance_pct=0.0,
                    opening_bar_protection_active=False,
                    trailing_activated=False,
                    trailing_distance_pct=0.0,
                    breakeven_activated=False,
                    gap_risk_pct=0.0,
                    entry_bar_volatility=0.0,
                    time_weighted_peak=exit_price,
                    exit_reason=exit_reason,
                    exit_price=exit_price
                )
                if symbol not in self.monitoring_buffer:
                    self.monitoring_buffer[symbol] = []
                self.monitoring_buffer[symbol].append(final_record)
                self._flush_symbol_data(symbol)
                
        except Exception as e:
            log.error(f"❌ Error recording exit for {symbol}: {e}", exc_info=True)
    
    def _flush_symbol_data(self, symbol: str) -> None:
        """Flush monitoring data for a symbol to GCS"""
        if not self.enabled or not self.storage_client or symbol not in self.monitoring_buffer:
            return
        
        try:
            today = datetime.utcnow().date()
            date_str = today.isoformat()
            
            # Get data to flush
            data_to_flush = self.monitoring_buffer[symbol].copy()
            self.monitoring_buffer[symbol] = []  # Clear buffer
            
            if not data_to_flush:
                return
            
            # Convert to JSON
            json_data = [asdict(record) for record in data_to_flush]
            
            # Upload to GCS
            bucket = self.storage_client.bucket(self.gcs_bucket)
            blob_path = f"exit_monitoring/{date_str}/{symbol}_monitoring.json"
            blob = bucket.blob(blob_path)
            
            # Append to existing data if file exists
            existing_data = []
            if blob.exists():
                try:
                    existing_content = blob.download_as_text()
                    existing_data = json.loads(existing_content)
                except:
                    existing_data = []
            
            # Combine and upload
            combined_data = existing_data + json_data
            blob.upload_from_string(
                json.dumps(combined_data, indent=2),
                content_type="application/json"
            )
            
            log.debug(f"📊 Flushed {len(data_to_flush)} monitoring records for {symbol} to GCS")
            
        except Exception as e:
            log.error(f"❌ Error flushing monitoring data for {symbol}: {e}", exc_info=True)
            # Re-add to buffer on error
            if symbol not in self.monitoring_buffer:
                self.monitoring_buffer[symbol] = []
            self.monitoring_buffer[symbol].extend(data_to_flush)
            
            # Rev 00170: Alert if GCS errors persist (buffer growing)
            buffer_size = len(self.monitoring_buffer[symbol])
            if buffer_size > 50:  # Alert if buffer exceeds 50 records
                log.warning(f"⚠️ Exit monitoring buffer for {symbol} is large ({buffer_size} records) - GCS upload may be failing")
    
    def _check_periodic_flush(self) -> None:
        """Rev 00170: Check if periodic flush is needed (every 5 minutes)"""
        if not self.enabled:
            return
        
        now = datetime.utcnow()
        
        # Check if periodic flush is needed
        if self.last_periodic_flush is None:
            self.last_periodic_flush = now
            return
        
        time_since_last_flush = (now - self.last_periodic_flush).total_seconds() / 60
        
        if time_since_last_flush >= self.periodic_flush_interval_minutes:
            log.info(f"📊 Periodic flush triggered ({time_since_last_flush:.1f} min since last flush)")
            self._flush_all_symbols()
            self.last_periodic_flush = now
    
    def _flush_all_symbols(self) -> None:
        """Rev 00170: Flush all symbols in buffer (internal method)"""
        if not self.enabled:
            return
        
        symbols_to_flush = list(self.monitoring_buffer.keys())
        if not symbols_to_flush:
            return
        
        flushed_count = 0
        for symbol in symbols_to_flush:
            if self.monitoring_buffer[symbol]:  # Only flush if buffer has data
                self._flush_symbol_data(symbol)
                flushed_count += 1
        
        if flushed_count > 0:
            log.info(f"📊 Periodic flush: Flushed {flushed_count} symbols to GCS")
    
    def flush_all(self) -> None:
        """Flush all buffered data to GCS (call at EOD)"""
        if not self.enabled:
            return
        
        log.info("📊 EOD flush: Flushing all exit monitoring data to GCS")
        self._flush_all_symbols()
        self.last_periodic_flush = datetime.utcnow()
        log.info("✅ Flushed all exit monitoring data to GCS")
    
    def get_health_status(self) -> Dict[str, Any]:
        """Rev 00170: Get health status of exit monitoring collector"""
        now = datetime.utcnow()
        
        status = {
            'enabled': self.enabled,
            'buffer_size': sum(len(records) for records in self.monitoring_buffer.values()),
            'symbols_tracked': len(self.monitoring_buffer),
            'last_collection_time': self.last_collection_time.isoformat() if self.last_collection_time else None,
            'last_periodic_flush': self.last_periodic_flush.isoformat() if self.last_periodic_flush else None,
        }
        
        # Check if collection is stale (no data for 10 minutes)
        if self.last_collection_time:
            minutes_since_collection = (now - self.last_collection_time).total_seconds() / 60
            status['minutes_since_last_collection'] = minutes_since_collection
            status['is_stale'] = minutes_since_collection > 10
        else:
            status['minutes_since_last_collection'] = None
            status['is_stale'] = True
        
        return status


def get_exit_monitoring_collector() -> PrimeExitMonitoringCollector:
    """Factory function to get exit monitoring collector instance"""
    return PrimeExitMonitoringCollector()

