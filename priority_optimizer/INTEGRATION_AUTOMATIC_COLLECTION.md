# Automatic 89-Point Data Collection Integration Guide

## Overview

This guide explains how to integrate automatic 89-point data collection into the ORB Strategy trading system so data is collected automatically at each phase:
1. **Signal Collection** (7:15-7:30 AM PT)
2. **Entry Execution** (7:30 AM PT)
3. **Exit Monitoring** (Throughout day)

## Integration Points

### 1. Signal Collection Phase

**Location**: `modules/prime_trading_system.py` ~line 1992

**Current Code**:
```python
self.daily_run_tracker.record_signal_collection(
    signals=all_signals,
    total_scanned=total_scanned,
    mode=self.mode,
    metadata=metadata
)
```

**Enhanced Code**:
```python
# Record signal collection (existing)
self.daily_run_tracker.record_signal_collection(
    signals=all_signals,
    total_scanned=total_scanned,
    mode=self.mode,
    metadata=metadata
)

# Collect 89-point data for Priority Optimizer
from modules.comprehensive_data_collector import get_comprehensive_data_collector
comprehensive_collector = get_comprehensive_data_collector()

for sig in all_signals:
    # Get full market data with technical indicators (BEFORE sanitization)
    market_data = self.trade_manager.etrade_trading.get_market_data_for_strategy(sig['symbol'])
    
    if market_data:
        comprehensive_collector.collect_trade_data(
            symbol=sig['symbol'],
            trade_id=f"{self.daily_run_tracker._date_key()}_{sig['symbol']}_{sig.get('rank', 0)}",
            market_data=market_data,  # Full technical indicators
            trade_data={},  # Empty at collection time
            ranking_data={
                'rank': sig.get('rank', 0),
                'priority_score': sig.get('priority_score', 0.0),
                'confidence': sig.get('confidence', 0.0),
                'orb_volume_ratio': sig.get('orb_volume_ratio', 0.0),
                'exec_volume_ratio': sig.get('exec_volume_ratio', 0.0),
                'category': sig.get('category', '')
            },
            risk_data={},  # Empty at collection time
            market_conditions={
                'market_regime': market_data.get('market_regime', ''),
                'volatility_regime': market_data.get('volatility_regime', ''),
                'trend_direction': market_data.get('trend_direction', ''),
                'volume_regime': market_data.get('volume_regime', ''),
                'momentum_regime': market_data.get('momentum_regime', '')
            }
        )
```

### 2. Entry Execution Phase

**Location**: `modules/prime_trading_system.py` ~line 2027

**Current Code**:
```python
self.daily_run_tracker.record_signal_execution(
    executed_signals=executed_signals,
    rejected_signals=rejected_signals,
    mode=self.mode,
    metadata=execution_metadata
)
```

**Enhanced Code**:
```python
# Record signal execution (existing)
self.daily_run_tracker.record_signal_execution(
    executed_signals=executed_signals,
    rejected_signals=rejected_signals,
    mode=self.mode,
    metadata=execution_metadata
)

# Update comprehensive records with entry data
from modules.comprehensive_data_collector import get_comprehensive_data_collector
comprehensive_collector = get_comprehensive_data_collector()

for sig in executed_signals:
    symbol = sig['symbol']
    # Find existing record and update with entry data
    for record in comprehensive_collector.comprehensive_data:
        if record['symbol'] == symbol and record['date'] == self.daily_run_tracker._date_key():
            record['entry_price'] = sig.get('price', sig.get('current_price', 0.0))
            record['entry_time'] = datetime.now().isoformat()
            record['shares'] = sig.get('quantity', 0)
            record['position_value'] = sig.get('position_value', 0.0)
            record['entry_bar_volatility'] = sig.get('entry_bar_volatility', 0.0)
            break
```

### 3. Exit Monitoring Phase

**Location**: `modules/prime_trading_system.py` ~line 6175 (or wherever trades are closed)

**Current Code**:
```python
# Trade exit logic
exit_price = ...
exit_reason = ...
pnl_dollars = ...
pnl_pct = ...
```

**Enhanced Code**:
```python
# Trade exit logic (existing)
exit_price = ...
exit_reason = ...
pnl_dollars = ...
pnl_pct = ...
peak_price = ...  # From position tracking

# Update comprehensive records with exit data
from modules.comprehensive_data_collector import get_comprehensive_data_collector
comprehensive_collector = get_comprehensive_data_collector()

for record in comprehensive_collector.comprehensive_data:
    if record['symbol'] == symbol and record['date'] == self.daily_run_tracker._date_key():
        record['exit_price'] = exit_price
        record['exit_time'] = datetime.now().isoformat()
        record['exit_reason'] = exit_reason
        record['peak_price'] = peak_price
        record['peak_pct'] = ((peak_price - record['entry_price']) / record['entry_price']) * 100 if record['entry_price'] > 0 else 0.0
        record['pnl_dollars'] = pnl_dollars
        record['pnl_pct'] = pnl_pct
        record['win'] = pnl_dollars > 0
        
        # Calculate holding minutes
        if record['entry_time']:
            entry_dt = datetime.fromisoformat(record['entry_time'])
            exit_dt = datetime.fromisoformat(record['exit_time'])
            record['holding_minutes'] = (exit_dt - entry_dt).total_seconds() / 60.0
        
        break
```

### 4. End-of-Day Save

**Location**: `modules/prime_trading_system.py` (end of trading day, ~4:00 PM PT)

**Add Code**:
```python
# Save comprehensive data at end of day
from modules.comprehensive_data_collector import get_comprehensive_data_collector
comprehensive_collector = get_comprehensive_data_collector()

if comprehensive_collector.comprehensive_data:
    await comprehensive_collector.save_daily_data(format='both')
    log.info(f"✅ Saved {len(comprehensive_collector.comprehensive_data)} comprehensive records for Priority Optimizer")
```

## Helper Method: Update Comprehensive Record

Add this helper method to `comprehensive_data_collector.py`:

```python
def update_trade_entry(self, symbol: str, entry_price: float, entry_time: str, 
                      shares: int, position_value: float, entry_bar_volatility: float = 0.0):
    """Update comprehensive record with entry data"""
    for record in self.comprehensive_data:
        if record['symbol'] == symbol and record['date'] == self.today_date:
            record['entry_price'] = entry_price
            record['entry_time'] = entry_time
            record['shares'] = shares
            record['position_value'] = position_value
            record['entry_bar_volatility'] = entry_bar_volatility
            return True
    return False

def update_trade_exit(self, symbol: str, exit_price: float, exit_time: str,
                     exit_reason: str, peak_price: float, pnl_dollars: float,
                     pnl_pct: float, max_adverse_excursion: float = 0.0):
    """Update comprehensive record with exit data"""
    for record in self.comprehensive_data:
        if record['symbol'] == symbol and record['date'] == self.today_date:
            record['exit_price'] = exit_price
            record['exit_time'] = exit_time
            record['exit_reason'] = exit_reason
            record['peak_price'] = peak_price
            record['peak_pct'] = ((peak_price - record['entry_price']) / record['entry_price']) * 100 if record['entry_price'] > 0 else 0.0
            record['pnl_dollars'] = pnl_dollars
            record['pnl_pct'] = pnl_pct
            record['win'] = pnl_dollars > 0
            record['max_adverse_excursion'] = max_adverse_excursion
            
            # Calculate holding minutes
            if record['entry_time']:
                from datetime import datetime
                entry_dt = datetime.fromisoformat(record['entry_time'])
                exit_dt = datetime.fromisoformat(exit_time)
                record['holding_minutes'] = (exit_dt - entry_dt).total_seconds() / 60.0
            
            return True
    return False
```

## Testing

1. **Test Signal Collection**: Run signal collection and verify records are created
2. **Test Entry Execution**: Execute trades and verify entry data is updated
3. **Test Exit Monitoring**: Close trades and verify exit data is updated
4. **Test End-of-Day Save**: Verify data is saved to GCS and local storage

## Notes

- The comprehensive collector uses a singleton pattern, so it persists across the trading session
- Data is saved automatically at end of day, but can also be saved manually
- The REST-based collector (`collect_89points_rest.py`) can be used to retrieve and reconstruct data from GCS if needed

