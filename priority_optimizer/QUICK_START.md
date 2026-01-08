# Quick Start Guide - Daily Data Collection

**Last Updated**: January 6, 2026  
**Version**: Rev 00231

## Overview

This guide shows you how to collect 89 comprehensive data points for **both ORB Strategy and 0DTE Options Strategy** each trading day. Use this data to find insights and improve strategy performance after many trading sessions.

---

## 🚀 Quick Start (3 Steps)

### Step 1: Run Daily Collection Script ⭐ **RECOMMENDED**

**When**: Anytime (no trading hours restriction), after signal collection (7:15-7:30 AM PT)

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
- ✅ Retrieves signals from GCS/daily markers for the specified date
- ✅ Collects 89 data points for **all signals** from that trading day
- ✅ Uses yfinance for technical indicators (no E*TRADE initialization needed)
- ✅ Merges ORB data and execution data
- ✅ Saves to local JSON/CSV + GCS automatically
- ✅ Takes ~10-30 seconds for 16 signals

**Output**:
- Local: `comprehensive_data/YYYY-MM-DD_comprehensive_data.json` (49 KB)
- Local: `comprehensive_data/YYYY-MM-DD_comprehensive_data.csv` (16 KB)
- GCS: `gs://easy-etrade-strategy-data/priority_optimizer/comprehensive_data/YYYY-MM-DD_comprehensive_data.json`

### Step 2: Retrieve Data for Analysis

**When**: Anytime after collection (can be days/weeks later)

```bash
python3 retrieve_gcs_89points.py
```

**Options**:
1. Retrieve specific date
2. Retrieve date range
3. Retrieve all available dates

**Output**: `priority_optimizer/retrieved_data/YYYY-MM-DD_retrieved.json`

### Step 3: Analyze Data

Use the collected data to:
- **Improve Priority Ranking Formula**: Analyze which signals performed best
- **Optimize Red Day Detection**: Identify patterns in losing trades
- **Enhance Exit Strategy**: Optimize trailing stops and profit capture
- **Refine 0DTE Strategy**: Analyze options trade performance

---

## 📊 What Data is Collected?

### ORB Strategy Data

**89 Comprehensive Data Points** including:
- Price data (open, high, low, close, volume)
- Technical indicators (RSI, MACD, Bollinger Bands, etc.)
- ORB data (ORB high/low, ORB volume, ORB range %)
- Ranking data (priority score, confidence, rank)
- Market context (SPY data, RS vs SPY)
- Trade execution data (if integrated)

**Symbols Collected**: All symbols from `data/watchlist/standard_orders.csv`

### 0DTE Options Strategy Data

**89 Comprehensive Data Points** including:
- Underlying symbol price data
- Technical indicators (RSI, MACD, volatility, etc.)
- Options-specific data (delta, spread type, strikes)
- Entry/exit execution data
- Trade performance (P&L, max profit/loss)
- Market conditions (volatility regime, trend direction)

**Symbols Collected**: All symbols from `data/watchlist/0dte_list.csv`

---

## 📅 Daily Workflow

### Morning (7:15-7:30 AM PT)
1. ✅ Signal collection runs automatically (ORB + 0DTE)
2. ✅ Signals saved to GCS automatically

### During Trading Hours or Anytime After
3. ✅ **Run collection script**: `python3 collect_89points_fast.py --date YYYY-MM-DD`
   - Collects 89 data points for all signals from that day
   - Can run anytime (no trading hours restriction)
   - Uses historical data from GCS/daily markers

### End of Day (4:00 PM ET)
4. ✅ Trade execution data saved automatically (if integrated)
5. ✅ Comprehensive data available in GCS

### Analysis (Anytime)
6. ✅ **Retrieve data**: `python3 retrieve_gcs_89points.py`
7. ✅ Analyze collected data for insights

---

## 🔍 Analysis Use Cases

### ORB Strategy Optimization

**Priority Ranking Formula**:
- Which signals performed best?
- Validate VWAP, RS vs SPY, ORB Volume weights
- Optimize confidence thresholds

**Red Day Detection**:
- Identify patterns before losing trades
- Improve red day detection accuracy
- Reduce false positives

**Exit Strategy**:
- Analyze peak capture rates
- Optimize trailing stop distances
- Improve breakeven activation timing

### 0DTE Options Strategy Optimization

**Entry Signals**:
- Which underlying symbols performed best?
- Optimize Convex Eligibility Filter
- Improve spread type selection

**Exit Strategy**:
- Analyze profit capture rates
- Optimize hard stops and time stops
- Improve profit target levels

**Position Sizing**:
- Analyze optimal capital allocation
- Optimize max positions
- Improve risk management

---

## 📁 Data Storage Locations

### Local Storage
```
priority_optimizer/
├── comprehensive_data/          # 89-point data (ORB + 0DTE)
│   └── YYYY-MM-DD_comprehensive_data.json
├── daily_data/                  # ORB Strategy daily data
│   └── YYYY-MM-DD_DATA.json
├── 0dte_data/                    # 0DTE Strategy daily data
│   └── YYYY-MM-DD_0DTE.json
└── retrieved_data/              # Retrieved from GCS
    └── YYYY-MM-DD_retrieved.json
```

### GCS Storage
```
gs://easy-etrade-strategy-data/priority_optimizer/
├── comprehensive_data/           # 89-point data (ORB + 0DTE)
│   └── YYYY-MM-DD_comprehensive_data.json
├── daily_signals/                # ORB Strategy signals
│   └── YYYY-MM-DD_signals.json
└── 0dte_signals/                 # 0DTE Strategy signals
    └── YYYY-MM-DD_0dte_signals.json
```

---

## ⚙️ Advanced: Trade Execution Integration

For automatic collection on trade entry/exit (like Historical Enhancer), see `INTEGRATION_GUIDE.md`.

This provides:
- ✅ Automatic collection on trade execution
- ✅ Trade execution data (entry/exit, P&L) included
- ✅ Real-time data capture

---

## 📚 Additional Resources

- **`README.md`**: Complete documentation
- **`INTEGRATION_GUIDE.md`**: Trade execution integration guide
- **`README_RECOVERY.md`**: Data recovery guide
- **`recover_gcs_data.py`**: Recover historical data from GCS

---

## ❓ Troubleshooting

### Script fails to find symbols
- **Check**: `data/watchlist/standard_orders.csv` exists (ORB Strategy)
- **Check**: `data/watchlist/0dte_list.csv` exists (0DTE Strategy)
- **Fallback**: Script will try to load from today's signal files

### No data collected
- **Check**: Market is open (7:30 AM - 4:00 PM ET)
- **Check**: E*TRADE API is accessible
- **Check**: OAuth tokens are valid

### GCS upload fails
- **Check**: GCS credentials are configured
- **Check**: Bucket `easy-etrade-strategy-data` exists
- **Note**: Data is still saved locally even if GCS upload fails

---

**Ready to collect data?** Run `python3 collect_89points_fast.py --date YYYY-MM-DD` anytime!

**For detailed guide**: See `QUICK_COLLECTION_GUIDE.md` ⭐

