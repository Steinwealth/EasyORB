# Data Collection Recovery & Integration Guide

**Date**: January 6, 2026  
**Status**: Recovery Scripts Created, Integration Needed

---

## Summary

The Priority Optimizer is missing scripts to collect the 89 technical data points from each day's trade collection. Recovery scripts have been created to:
1. Download existing data from GCS
2. Reconstruct partial 89-point data from trade history
3. Set up future collection

**However**, the comprehensive data collector is **NOT integrated** into the trade execution flow, so future data collection will not happen automatically until integration is added.

---

## Available Data in GCS

### Signal Files
- **Location**: `gs://easy-etrade-strategy-data/priority_optimizer/daily_signals/`
- **Files Found**: 21 signal files (Nov 17, 2025 - Jan 5, 2026)
- **Content**: Basic signal data (symbol, confidence, price, signal_type)
- **Missing**: Technical indicators, comprehensive 89-point data

### Trade History
- **Location**: `gs://easy-etrade-strategy-data/demo_account/mock_trading_history.json`
- **Content**: Closed trades with basic fields (entry_price, exit_price, P&L, exit_reason)
- **Missing**: Technical indicators, ranking data, market conditions

### Comprehensive Data
- **Location**: `gs://easy-etrade-strategy-data/priority_optimizer/comprehensive_data/`
- **Status**: **EMPTY** - No comprehensive 89-point data files found

---

## Recovery Scripts Created

### 1. `priority_optimizer/recover_gcs_data.py`
Downloads all available data from GCS:
- Signal files
- Trade history
- Any existing comprehensive data

**Usage**:
```bash
cd priority_optimizer
python3 recover_gcs_data.py
```

### 2. `priority_optimizer/reconstruct_89point_data.py`
Reconstructs partial 89-point data from recovered trades:
- Attempts to fill in available fields
- **Limitation**: Cannot reconstruct real-time technical indicators (RSI, MACD, Bollinger Bands, etc.)

**Usage**:
```bash
python3 reconstruct_89point_data.py
```

---

## Integration Required

The comprehensive data collector exists (`modules/comprehensive_data_collector.py`) but is **NOT integrated** into trade execution. Integration points needed:

### 1. Trade Execution (Entry)
**File**: `modules/mock_trading_executor.py`  
**Function**: `execute_mock_trade()` (around line 626)

**Add after trade execution**:
```python
# Collect comprehensive 89 data points
try:
    from modules.comprehensive_data_collector import get_comprehensive_data_collector
    
    comprehensive_collector = get_comprehensive_data_collector(
        gcs_bucket="easy-etrade-strategy-data",
        gcs_prefix="priority_optimizer/comprehensive_data"
    )
    
    # Get market data with technical indicators
    # (This requires E*TRADE API call or market data from signal processing)
    market_data_dict = {
        # Price data
        'open': entry_price,
        'high': entry_price,  # Will be updated during trade
        'low': entry_price,
        'close': entry_price,
        'volume': 0,  # Get from market data
        
        # Technical indicators (from E*TRADE API or signal processing)
        'rsi': signal.get('rsi', 0.0) if hasattr(signal, 'rsi') else 0.0,
        'rsi_14': signal.get('rsi_14', 0.0) if hasattr(signal, 'rsi_14') else 0.0,
        'macd': 0.0,  # Get from market data
        'atr': market_data.get('atr', 0.0) if isinstance(market_data, dict) else 0.0,
        'vwap': signal.get('vwap', 0.0) if hasattr(signal, 'vwap') else 0.0,
        'rs_vs_spy': signal.get('rs_vs_spy', 0.0) if hasattr(signal, 'rs_vs_spy') else 0.0,
        # ... add all 89 fields
    }
    
    trade_data_dict = {
        'entry_price': entry_price,
        'exit_price': 0.0,  # Will be set on exit
        'entry_time': datetime.now().isoformat(),
        'exit_time': '',
        'shares': quantity,
        'position_value': position_value,
        'peak_price': entry_price,
        'peak_pct': 0.0,
        'pnl_dollars': 0.0,
        'pnl_pct': 0.0,
        'exit_reason': '',
        'win': False,
        'holding_minutes': 0.0,
    }
    
    ranking_data_dict = {
        'rank': signal.get('rank', 0) if hasattr(signal, 'rank') else 0,
        'priority_score': signal.confidence,
        'confidence': signal.confidence,
        'orb_volume_ratio': signal.get('orb_volume_ratio', 0.0) if hasattr(signal, 'orb_volume_ratio') else 0.0,
        'exec_volume_ratio': 0.0,
        'category': signal.signal_type if hasattr(signal, 'signal_type') else '',
    }
    
    risk_data_dict = {
        'current_stop_loss': stop_loss,
        'stop_loss_distance_pct': ((entry_price - stop_loss) / entry_price) * 100,
        'opening_bar_protection_active': False,
        'trailing_activated': False,
        'trailing_distance_pct': 0.0,
        'breakeven_activated': False,
        'gap_risk_pct': 0.0,
        'max_adverse_excursion': 0.0,
    }
    
    market_conditions_dict = {
        'market_regime': '',  # Get from market analysis
        'volatility_regime': '',
        'trend_direction': '',
        'volume_regime': '',
        'momentum_regime': '',
    }
    
    comprehensive_collector.collect_trade_data(
        symbol=signal.symbol,
        trade_id=trade_id,
        market_data=market_data_dict,
        trade_data=trade_data_dict,
        ranking_data=ranking_data_dict,
        risk_data=risk_data_dict,
        market_conditions=market_conditions_dict
    )
    
    log.info(f"📊 Collected 89 data points for {signal.symbol} ({trade_id})")
except Exception as e:
    log.warning(f"⚠️ Failed to collect comprehensive data: {e}")
```

### 2. Trade Exit (Update Record)
**File**: `modules/mock_trading_executor.py`  
**Function**: `close_position_with_data()` (around line 730)

**Add before closing trade**:
```python
# Update comprehensive data record with exit data
try:
    from modules.comprehensive_data_collector import get_comprehensive_data_collector
    
    comprehensive_collector = get_comprehensive_data_collector()
    
    # Find and update the record for this trade
    for record in comprehensive_collector.comprehensive_data:
        if record.get('trade_id') == trade.trade_id:
            record['exit_price'] = exit_price
            record['exit_time'] = datetime.now().isoformat()
            record['pnl_dollars'] = pnl
            record['pnl_pct'] = (pnl / trade.position_value) * 100 if trade.position_value > 0 else 0.0
            record['exit_reason'] = exit_reason
            record['win'] = pnl > 0
            record['holding_minutes'] = holding_minutes
            
            # Update peak data
            if trade.max_favorable:
                record['peak_price'] = trade.max_favorable
                record['peak_pct'] = ((trade.max_favorable - trade.entry_price) / trade.entry_price) * 100
            
            log.info(f"📊 Updated comprehensive data for {trade.symbol} ({trade.trade_id})")
            break
except Exception as e:
    log.warning(f"⚠️ Failed to update comprehensive data: {e}")
```

### 3. End of Day (Save Data)
**File**: `modules/prime_trading_system.py` or `main.py`  
**Location**: End of day report function

**Add at end of day**:
```python
# Save comprehensive data
try:
    from modules.comprehensive_data_collector import get_comprehensive_data_collector
    
    comprehensive_collector = get_comprehensive_data_collector()
    await comprehensive_collector.save_daily_data(format='both')
    
    log.info(f"✅ Saved comprehensive data: {len(comprehensive_collector.comprehensive_data)} records")
except Exception as e:
    log.warning(f"⚠️ Failed to save comprehensive data: {e}")
```

---

## Data Collection Requirements

### Market Data Source
To collect all 89 data points, need access to:
1. **E*TRADE REST API**: For real-time technical indicators
2. **Signal Processing**: Some indicators may be calculated during signal generation
3. **Market Data Service**: For SPY data, market conditions

### Technical Indicators Needed
- RSI (14, 21)
- MACD (signal, histogram)
- Bollinger Bands (upper, middle, lower, width, position)
- Moving Averages (SMA 20/50/200, EMA 12/26)
- Volume indicators (OBV, AD Line, volume ratio)
- Pattern recognition (doji, hammer, engulfing, morning star)
- Additional indicators (Stochastic, Williams %R, CCI, ADX, etc.)

---

## Next Steps

1. ✅ **Recovery Scripts**: Created and ready to use
2. ⚠️ **Run Recovery**: Execute `recover_gcs_data.py` to download existing data
3. ⚠️ **Reconstruct Data**: Execute `reconstruct_89point_data.py` for partial reconstruction
4. ⚠️ **Integration**: Add comprehensive data collection to trade execution flow
5. ⚠️ **Test**: Verify data collection on next trading session
6. ⚠️ **Analysis**: Use collected data for Priority Ranking optimization

---

## Files Created

- `priority_optimizer/recover_gcs_data.py`: GCS data recovery script
- `priority_optimizer/reconstruct_89point_data.py`: 89-point data reconstruction script
- `priority_optimizer/README_RECOVERY.md`: Recovery guide
- `docs/doc_elements/Sessions/2026/Jan6 Session/DATA_COLLECTION_RECOVERY.md`: This document

---

## Analysis Use Cases

Once data is collected, use for:

1. **Priority Ranking Formula Optimization**
   - Analyze which signals performed best
   - Validate VWAP, RS vs SPY, ORB Volume weights
   - Optimize confidence thresholds

2. **Red Day Detection**
   - Identify patterns in losing trades
   - Analyze market conditions before red days
   - Improve red day detection accuracy

3. **Exit Strategy Optimization**
   - Analyze peak capture rates
   - Optimize trailing stop distances
   - Improve breakeven activation timing

---

*For comprehensive data collector implementation, see [modules/comprehensive_data_collector.py](../../modules/comprehensive_data_collector.py)*

