# 89-Point Data Collection Integration Guide

**Last Updated**: January 6, 2026  
**Version**: Rev 00231

## Overview

This guide explains how to integrate 89-point comprehensive data collection into the Easy ORB Strategy trading system. The system supports two collection methods:

1. **Daily REST Script**: Collects data during trading hours for **both ORB and 0DTE** symbols
2. **Trade Execution Integration**: Collects data automatically on trade entry/exit (like Historical Enhancer)

**Supports both strategies:**
- ✅ **ORB Strategy** (Standard Orders)
- ✅ **0DTE Options Strategy**

---

## Method 1: Daily REST Script Collection

### Purpose
Collect 89 data points for all symbols in the trade list during trading hours (7:30 AM - 4:00 PM ET), since some data becomes unavailable after market close.

### Usage

```bash
cd priority_optimizer
python3 collect_daily_89points.py
```

### When to Run
- **During trading hours** (7:30 AM - 4:00 PM ET)
- **After signal collection** (7:15-7:30 AM PT) to collect data for all signals
- **Can be scheduled** via Cloud Scheduler or cron

### What It Does
1. Loads **ORB Strategy symbols** from `data/watchlist/standard_orders.csv`
2. Loads **0DTE Strategy symbols** from `data/watchlist/0dte_list.csv`
3. Calls E*TRADE API for each symbol to get comprehensive market data
4. Collects all 89 technical indicators for each symbol
5. Saves to local JSON/CSV files
6. Uploads to GCS: `priority_optimizer/comprehensive_data/YYYY-MM-DD_comprehensive_data.json`

**Note**: Collects data for **both ORB and 0DTE** strategies in a single run.

### Data Collected

**For ORB Strategy symbols:**
- All 89 technical indicators (RSI, MACD, Bollinger Bands, etc.)
- Price data (open, high, low, close, volume)
- Market context (SPY data, RS vs SPY)
- ORB data (ORB high/low, ORB volume, ORB range %)

**For 0DTE Strategy symbols:**
- All 89 technical indicators for underlying symbols
- Price data for underlying symbols
- Market context (SPY data, RS vs SPY)
- Options-specific data (if available from signals)

**Note**: Trade execution data (entry/exit, P&L) is NOT collected by this script. Use trade execution integration for that.

---

## Method 2: Trade Execution Integration (Recommended)

### Purpose
Automatically collect 89 data points when trades are executed (entry) and closed (exit), similar to Historical Enhancer pattern. Data is stored in GCS immediately.

### Integration Points

#### 1. Trade Entry (Execute Trade)

**File**: `modules/mock_trading_executor.py`  
**Function**: `execute_mock_trade()` (around line 626)

**Add after trade execution** (after line 626, before return):

```python
# Collect comprehensive 89 data points for Priority Optimizer
try:
    from modules.comprehensive_data_collector import get_comprehensive_data_collector
    from modules.prime_etrade_trading import PrimeETradeTrading
    
    comprehensive_collector = get_comprehensive_data_collector(
        gcs_bucket="easy-etrade-strategy-data",
        gcs_prefix="priority_optimizer/comprehensive_data"
    )
    
    # Get comprehensive market data from E*TRADE
    etrade_trading = PrimeETradeTrading()
    market_data_dict = etrade_trading.get_market_data_for_strategy(signal.symbol)
    
    if market_data_dict:
        # Build trade data
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
            'entry_bar_volatility': 0.0,
        }
        
        # Build ranking data
        ranking_data_dict = {
            'rank': signal.get('rank', 0) if hasattr(signal, 'rank') else 0,
            'priority_score': signal.confidence,
            'confidence': signal.confidence,
            'orb_volume_ratio': market_data_dict.get('orb_volume_ratio', 0.0),
            'exec_volume_ratio': 0.0,
            'category': signal.signal_type if hasattr(signal, 'signal_type') else '',
        }
        
        # Build risk data
        risk_data_dict = {
            'current_stop_loss': stop_loss,
            'stop_loss_distance_pct': ((entry_price - stop_loss) / entry_price) * 100 if entry_price > 0 else 0.0,
            'opening_bar_protection_active': False,
            'trailing_activated': False,
            'trailing_distance_pct': 0.0,
            'breakeven_activated': False,
            'gap_risk_pct': 0.0,
            'max_adverse_excursion': 0.0,
        }
        
        # Build market conditions
        market_conditions_dict = {
            'market_regime': market_data_dict.get('market_regime', ''),
            'volatility_regime': market_data_dict.get('volatility_regime', ''),
            'trend_direction': market_data_dict.get('trend_direction', ''),
            'volume_regime': market_data_dict.get('volume_regime', ''),
            'momentum_regime': market_data_dict.get('momentum_regime', ''),
        }
        
        # Collect comprehensive data
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
    else:
        log.warning(f"⚠️ No market data available for {signal.symbol} - comprehensive data not collected")
        
except Exception as e:
    log.warning(f"⚠️ Failed to collect comprehensive data for {signal.symbol}: {e}")
```

#### 2. Trade Exit (Close Position)

**File**: `modules/mock_trading_executor.py`  
**Function**: `close_position_with_data()` (around line 730)

**Add before closing trade** (before line 800, where trade is moved to closed_trades):

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
                record['peak_pct'] = ((trade.max_favorable - trade.entry_price) / trade.entry_price) * 100 if trade.entry_price > 0 else 0.0
            
            # Update risk data
            record['trailing_activated'] = bool(trade.trailing_stop)
            
            log.info(f"📊 Updated comprehensive data for {trade.symbol} ({trade.trade_id})")
            break
    else:
        log.warning(f"⚠️ Comprehensive data record not found for {trade.trade_id}")
        
except Exception as e:
    log.warning(f"⚠️ Failed to update comprehensive data: {e}")
```

#### 3. End of Day (Save Data)

**File**: `modules/prime_trading_system.py` or `main.py`  
**Location**: End of day report function

**Add at end of day** (after EOD report is sent):

```python
# Save comprehensive data to GCS
try:
    from modules.comprehensive_data_collector import get_comprehensive_data_collector
    
    comprehensive_collector = get_comprehensive_data_collector()
    
    if comprehensive_collector.comprehensive_data:
        await comprehensive_collector.save_daily_data(format='both')
        log.info(f"✅ Saved comprehensive data: {len(comprehensive_collector.comprehensive_data)} records")
    else:
        log.info("ℹ️ No comprehensive data to save")
        
except Exception as e:
    log.warning(f"⚠️ Failed to save comprehensive data: {e}")
```

---

## Retrieving Data from GCS

### Script: `retrieve_gcs_89points.py`

Similar to Historical Enhancer's `collect_trade_data.py`, this script retrieves stored data from GCS:

```bash
cd priority_optimizer
python3 retrieve_gcs_89points.py
```

**Options**:
1. Retrieve specific date
2. Retrieve date range
3. Retrieve all available dates

**Output**: Saves to `priority_optimizer/retrieved_data/YYYY-MM-DD_retrieved.json`

---

## Data Storage

### GCS Location
```
gs://easy-etrade-strategy-data/priority_optimizer/comprehensive_data/
├── YYYY-MM-DD_comprehensive_data.json  # Daily comprehensive data
└── YYYY-MM-DD_comprehensive_data.csv   # CSV format (if saved)
```

### Local Storage
```
priority_optimizer/comprehensive_data/
├── YYYY-MM-DD_comprehensive_data.json
└── YYYY-MM-DD_comprehensive_data.csv
```

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

## Comparison: Daily Script vs Trade Execution Integration

| Feature | Daily Script | Trade Execution Integration |
|---------|-------------|----------------------------|
| **When** | During trading hours | On trade entry/exit |
| **What** | All symbols (ORB + 0DTE) | Only executed trades |
| **Trade Data** | ❌ Not available | ✅ Entry/exit/P&L included |
| **Completeness** | Signal collection data | Full trade lifecycle |
| **Use Case** | Signal analysis | Trade performance analysis |
| **Storage** | GCS + Local | GCS + Local |
| **Strategies** | ✅ ORB + 0DTE | ✅ ORB + 0DTE (if integrated) |

**Recommendation**: Use **both methods**:
- **Daily Script**: For signal collection analysis (all symbols, both strategies)
- **Trade Execution Integration**: For trade performance analysis (executed trades only, both strategies)

---

## Next Steps

1. ✅ **Daily Script**: Created (`collect_daily_89points.py`)
2. ✅ **Retrieval Script**: Created (`retrieve_gcs_89points.py`)
3. ⚠️ **Integration**: Add comprehensive data collection to trade execution (see above)
4. ⚠️ **Test**: Verify data collection on next trading session
5. ⚠️ **Analysis**: Use collected data for optimization

---

*For comprehensive data collector implementation, see [modules/comprehensive_data_collector.py](../modules/comprehensive_data_collector.py)*

