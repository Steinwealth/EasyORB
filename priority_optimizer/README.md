# Priority Optimizer

**Last Updated**: January 7, 2026  
**Version**: Rev 00232 (Comprehensive Data Collection & Red Day Detection Analysis)  
**Status**: ✅ Production Active

## Overview

The Priority Optimizer collects comprehensive signal and trade data from daily trading operations to enable analysis and optimization of the ranking formula, position sizing, and exit strategies.

**Supports both strategies:**
- ✅ **ORB Strategy** (Standard Orders)
- ✅ **0DTE Options Strategy**

## Purpose

This folder contains all data collected from signal collection each day, including:
- **Complete signal lists** (all signals generated before filtering)
- **Execution results** (executed vs filtered signals)
- **Trade performance** (entry, peak, exit, P&L data)
- **Technical indicators** (RSI, ORB Volume, VWAP, RS vs SPY, etc.)
- **Ranking data** (priority scores, ranks, filtering reasons)
- **89 Comprehensive Data Points** (for deep analysis)

## 🚀 Quick Start - Daily Data Collection

### ⭐ **START HERE**: Simple One-Command Collection

**Collect 89-point data for any trading day:**

```bash
cd priority_optimizer
python3 collect_89points_fast.py --date YYYY-MM-DD
```

**Example** (collect today's data):
```bash
python3 collect_89points_fast.py --date 2026-01-07
```

**Default**: If no date provided, collects for today.

**What it does**:
- ✅ Retrieves signals from GCS/daily markers
- ✅ Collects technical indicators (RSI, MACD, VWAP, etc.) at signal collection time
- ✅ Merges ORB data and execution data
- ✅ Saves to local JSON/CSV + GCS automatically
- ✅ Takes ~10-30 seconds for 16 signals

**Output**:
- Local: `comprehensive_data/YYYY-MM-DD_comprehensive_data.json` (49 KB)
- GCS: `gs://easy-etrade-strategy-data/priority_optimizer/comprehensive_data/YYYY-MM-DD_comprehensive_data.json`

**Quick Reference**: See **[`HOW_TO_USE.md`](HOW_TO_USE.md)** ⭐ **SIMPLE GUIDE**  
**Detailed Guide**: See **[`QUICK_COLLECTION_GUIDE.md`](QUICK_COLLECTION_GUIDE.md)**

## Folder Structure

```
priority_optimizer/
├── daily_data/          # ORB Strategy daily data files (local)
│   ├── YYYY-MM-DD_DATA.json    # Complete signal data (JSON)
│   ├── YYYY-MM-DD_DATA.csv     # Priority Optimizer format (CSV)
│   └── YYYY-MM-DD_DATA.txt     # Human-readable summary
├── daily_signals/       # ORB Strategy signals (GCS storage)
│   └── YYYY-MM-DD_signals.json # Daily signal collection (GCS)
├── 0dte_data/           # 0DTE Strategy daily data files (local)
│   └── YYYY-MM-DD_0DTE.json    # 0DTE trade data
├── 0dte_signals/        # 0DTE Strategy signals (GCS storage)
│   └── YYYY-MM-DD_0dte_signals.json  # 0DTE signal collection (GCS)
├── comprehensive_data/  # 89-point comprehensive data (ORB + 0DTE)
│   ├── YYYY-MM-DD_comprehensive_data.json  # Complete 89-point data
│   └── YYYY-MM-DD_comprehensive_data.csv   # CSV format
└── retrieved_data/      # Retrieved data from GCS (for analysis)
    └── YYYY-MM-DD_retrieved.json
```

## Data Collection

### ORB Strategy (Standard Orders)

**Collection Points:**
1. **Signal Collection** (7:15-7:30 AM PT): All signals generated during SO scanning
2. **Execution Results** (7:30 AM PT): Which signals were executed vs filtered
3. **Trade Performance** (EOD): Entry, peak, exit, P&L for executed trades
4. **Comprehensive Data** (7:30 AM PT): 89 data points per trade (REST-based collection)

**Data Captured:**
- Symbol, rank, priority score
- Technical indicators (confidence, ORB range %, ORB volume ratio, RSI)
- Price data (current price, ORB high/low)
- Execution status (executed/filtered, filter reason)
- Performance metrics (entry, peak, exit, P&L)
- **89 Comprehensive Data Points** (see Comprehensive Data Collection below)

### 0DTE Strategy (Options)

**Collection Points:**
1. **Signal Collection**: All 0DTE signals generated
2. **Entry Execution**: Strike selection, delta, spread type, entry price
3. **Exit Execution**: Exit reason, exit price, holding time
4. **Trade Performance**: Entry, peak, exit, P&L, max profit/loss
5. **Comprehensive Data** (7:30 AM PT): 89 data points per underlying symbol (REST-based collection)

**Data Captured:**
- Signal eligibility and spread type selection
- Entry execution data (strikes, delta, spread width)
- Exit execution data (exit reason, exit price, holding time)
- Trade performance (P&L, max profit, max loss)
- Market conditions (volatility, VWAP, ORB data)
- **89 Comprehensive Data Points** (underlying symbol technical indicators)

## Data Formats

### JSON Format
Complete data with all fields, including raw signal data for detailed analysis.

### CSV Format
Priority Optimizer format with standardized columns for analysis tools.

### Summary Format
Human-readable text summary with executed and filtered signal lists.

## GCS Storage

**Cloud Storage:**
- Daily signals automatically synced to GCS: `priority_optimizer/daily_signals/`
- 0DTE signals synced to GCS: `priority_optimizer/0dte_signals/`
- Comprehensive 89-point data: `priority_optimizer/comprehensive_data/`
- **Retention**: Last 50 days (rolling window)

**Benefits:**
- Data persists across deployments
- Enables historical analysis
- Supports formula optimization

## Usage

### 🚀 Quick Start

**See**: `QUICK_START.md` for a simple 3-step guide to daily data collection.

### Automatic Collection

Data is automatically collected by:
- **`modules/priority_data_collector.py`**: ORB Strategy data collection
- **`modules/options_priority_data_collector.py`**: 0DTE Strategy data collection
- **`modules/daily_run_tracker.py`**: GCS signal persistence

### Manual Collection (89-Point Data) ⭐ **RECOMMENDED METHOD**

**Fast REST-Based Collection Script** (works anytime, no E*TRADE initialization needed):
```bash
cd priority_optimizer
python3 collect_89points_fast.py --date YYYY-MM-DD
```

**What it collects**:
- ✅ **89 data points** for all signals from the trading day
- ✅ **Technical indicators** at signal collection time (7:30 AM PT)
- ✅ **ORB data** (high/low/volume/range)
- ✅ **Execution data** (entry prices, exit reasons, P&L if available)
- ✅ **Ranking data** (priority scores, confidence, ranks)

**When to run**:
- ✅ **Anytime** (no trading hours restriction)
- ✅ **After signal collection** (7:30 AM PT) for same-day analysis
- ✅ **Next day** for historical analysis
- ✅ **Multiple days** for pattern analysis

**Collection Time**: ~10-30 seconds for 16 signals

**Output Locations**:
- **Local**: `comprehensive_data/YYYY-MM-DD_comprehensive_data.json` + `.csv`
- **GCS**: `gs://easy-etrade-strategy-data/priority_optimizer/comprehensive_data/YYYY-MM-DD_comprehensive_data.json`

**Alternative Scripts** (if needed):
- `collect_89points_complete.py` - Complete collection with E*TRADE fallback (slower)
- `collect_89points_rest.py` - REST-based alternative (similar to fast)

**See**: `QUICK_COLLECTION_GUIDE.md` for detailed usage guide

### Manual Access

Data files are saved automatically at end-of-day. Files are organized by date:
- **Local**: `priority_optimizer/daily_data/YYYY-MM-DD_DATA.*`
- **GCS**: `priority_optimizer/daily_signals/YYYY-MM-DD_signals.json`
- **Comprehensive Data**: `priority_optimizer/comprehensive_data/YYYY-MM-DD_comprehensive_data.json`

## Comprehensive Data Collection (89 Data Points)

### Overview

The comprehensive data collector uses REST API calls to collect **89 data points** from trade collection each trading session. This enables deep analysis of trade performance, ranking formula effectiveness, and strategy optimization.

**Collects for both strategies:**
- **ORB Strategy**: All symbols in standard_orders.csv watchlist
- **0DTE Strategy**: All symbols in 0dte_list.csv watchlist

### Data Points Breakdown

1. **Price Data** (5): open, high, low, close, volume
2. **Moving Averages** (5): sma_20, sma_50, sma_200, ema_12, ema_26
3. **Momentum Indicators** (7): rsi, rsi_14, rsi_21, macd, macd_signal, macd_histogram, momentum_10
4. **Volatility Indicators** (7): atr, bollinger_upper, bollinger_middle, bollinger_lower, bollinger_width, bollinger_position, volatility
5. **Volume Indicators** (4): volume_ratio, volume_sma, obv, ad_line
6. **Pattern Recognition** (4): doji, hammer, engulfing, morning_star
7. **VWAP Indicators** (2): vwap, vwap_distance_pct
8. **Relative Strength** (1): rs_vs_spy
9. **ORB Data** (6): orb_high, orb_low, orb_open, orb_close, orb_volume, orb_range_pct
10. **Market Context** (2): spy_price, spy_change_pct
11. **Trade Data** (15): symbol, trade_id, entry_price, exit_price, entry_time, exit_time, shares, position_value, peak_price, peak_pct, pnl_dollars, pnl_pct, exit_reason, win, holding_minutes
12. **Ranking Data** (6): rank, priority_score, confidence, orb_volume_ratio, exec_volume_ratio, category
13. **Risk Management** (8): current_stop_loss, stop_loss_distance_pct, opening_bar_protection_active, trailing_activated, trailing_distance_pct, breakeven_activated, gap_risk_pct, max_adverse_excursion
14. **Market Conditions** (5): market_regime, volatility_regime, trend_direction, volume_regime, momentum_regime
15. **Additional Indicators** (16): stoch_k, stoch_d, williams_r, cci, adx, plus_di, minus_di, aroon_up, aroon_down, mfi, cmf, roc, ppo, tsi, ult_osc, ichimoku_base

**Total**: 89 data points per trade/symbol

### Collection Method

- **REST API**: Uses E*TRADE REST API for data collection
- **Batch Processing**: Efficient batch requests (25 symbols per call)
- **Timing**: Collected during trading hours (7:30 AM - 4:00 PM ET)
- **Storage**: Local JSON/CSV + GCS persistence

### Usage

```python
from modules.comprehensive_data_collector import get_comprehensive_data_collector

collector = get_comprehensive_data_collector()

# Collect 89 data points for a trade
comprehensive_record = collector.collect_trade_data(
    symbol="QQQ",
    trade_id="DEMO_QQQ_260106_485_488_c_704400",
    market_data=market_data_dict,
    trade_data=trade_data_dict,
    ranking_data=ranking_data_dict,
    risk_data=risk_data_dict,
    market_conditions=market_conditions_dict
)

# Save at end of day
await collector.save_daily_data(format='both')
```

## Analysis Use Cases

### ORB Strategy Optimization

1. **Priority Ranking Formula**: Analyze which signals performed best
   - Validate VWAP, RS vs SPY, ORB Volume weights
   - Optimize confidence thresholds
   - Improve signal filtering

2. **Red Day Detection**: Identify patterns in losing trades
   - Analyze market conditions before red days
   - Improve red day detection accuracy
   - Reduce false positives

3. **Exit Strategy**: Optimize exit triggers based on peak capture
   - Analyze peak capture rates
   - Optimize trailing stop distances
   - Improve breakeven activation timing

4. **Position Sizing**: Analyze optimal position sizes based on rank
   - Validate batch position sizing algorithm
   - Optimize capital allocation

### 0DTE Options Strategy Optimization

1. **Entry Signals**: Analyze which underlying symbols performed best
   - Optimize Convex Eligibility Filter
   - Improve spread type selection (debit/credit/lotto)
   - Refine signal filtering

2. **Exit Strategy**: Optimize options exit triggers
   - Analyze profit capture rates
   - Optimize hard stops and time stops
   - Improve profit target levels

3. **Position Sizing**: Analyze optimal capital allocation
   - Optimize max positions
   - Improve risk management
   - Balance debit spreads vs lotto trades

## Key Features

- ✅ **Complete Signal Capture**: All signals (executed + filtered)
- ✅ **Performance Tracking**: Entry, peak, exit, P&L for all trades
- ✅ **GCS Persistence**: Automatic cloud storage with retention
- ✅ **Multi-Format Export**: JSON, CSV, and summary formats
- ✅ **Historical Analysis**: 50-day rolling window for optimization
- ✅ **89-Point Data Collection**: Comprehensive technical indicators (REST script + trade execution integration)
- ✅ **GCS Retrieval**: Retrieve stored data anytime (similar to Historical Enhancer)
- ✅ **Dual Strategy Support**: Collects data for both ORB and 0DTE strategies

## Version Information

- **Current Version**: 2.31.0
- **Last Updated**: January 6, 2026
- **Rev**: 00231 (Trade ID Shortening & Alert Formatting Improvements)

---

## 📚 Documentation

### Quick Start Guides
- **`QUICK_COLLECTION_GUIDE.md`**: ⭐ **START HERE!** Simple guide to daily data collection with `collect_89points_fast.py`
- **`QUICK_START.md`**: Alternative quick start guide (uses different script)

### Analysis & Insights
- **`89_DATAPOINTS_ANALYSIS.md`**: Complete analysis - What are the 89 points? Will they suffice?
- **`DATAPOINTS_SUMMARY.md`**: Quick reference summary of 89 data points
- **`DATA_COLLECTION_INDEX.md`**: Central index for all data collection documentation

### Integration Guides
- **`INTEGRATION_GUIDE.md`**: Trade execution integration guide (automatic collection)
- **`INTEGRATION_AUTOMATIC_COLLECTION.md`**: Automatic collection integration guide

### Recovery & Utilities
- **`README_RECOVERY.md`**: Data recovery guide (recover historical data)
- **`recover_gcs_data.py`**: Recover historical data from GCS
- **`reconstruct_89point_data.py`**: Reconstruct 89-point data from trade history
- **`retrieve_gcs_89points.py`**: Retrieve stored data from GCS

### Session Documentation
- **Session folders**: `docs/doc_elements/Sessions/2026/Jan7 Session/` - Today's analysis and findings

## 🔗 Related Modules

*For module implementation, see [modules/priority_data_collector.py](../modules/priority_data_collector.py)*  
*For comprehensive 89-point collection, see [modules/comprehensive_data_collector.py](../modules/comprehensive_data_collector.py)*  
*For data history management, see [modules/data_history_manager.py](../modules/data_history_manager.py)*  
*For 0DTE collection, see [easy0DTE/modules/options_priority_data_collector.py](../easy0DTE/modules/options_priority_data_collector.py)*  
*For E*TRADE API improvements, see [docs/EtradeImprovementGuide.md](../docs/EtradeImprovementGuide.md)*
