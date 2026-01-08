# Quick Collection Guide - 89-Point Data Collection

**Last Updated**: January 7, 2026  
**Status**: ✅ Working and Tested

## 🚀 Quick Start - One Command

To collect complete 89-point data for any trading day:

```bash
cd priority_optimizer
python3 collect_89points_fast.py --date YYYY-MM-DD
```

**Example** (collect today's data):
```bash
python3 collect_89points_fast.py --date 2026-01-07
```

**Default**: If no date is provided, collects for today.

**Collection Time**: ~10-30 seconds for 16 signals

**Requirements**: 
- ✅ No E*TRADE initialization needed
- ✅ Uses yfinance (REST-based, no API keys)
- ✅ Works anytime (no trading hours restriction)
- ✅ Retrieves data from GCS/daily markers

## 📊 What Gets Collected

1. **Technical Indicators** (89 data points):
   - RSI, MACD, Bollinger Bands, ATR
   - Moving Averages (SMA, EMA)
   - Volume indicators
   - VWAP and VWAP distance
   - RS vs SPY
   - And more...

2. **Signal Data**:
   - Entry prices
   - Exit reasons
   - Priority scores
   - Confidence levels

3. **ORB Data**:
   - ORB high/low/open/close
   - ORB volume
   - ORB range %

## 💾 Where Data is Stored

### Local Storage
```
priority_optimizer/comprehensive_data/
├── YYYY-MM-DD_comprehensive_data.json
└── YYYY-MM-DD_comprehensive_data.csv
```

### GCS Storage
```
gs://easy-etrade-strategy-data/priority_optimizer/comprehensive_data/
└── YYYY-MM-DD_comprehensive_data.json
```

## ✅ Verification

After collection, verify data:

```bash
python3 -c "
import json
with open('comprehensive_data/YYYY-MM-DD_comprehensive_data.json') as f:
    data = json.load(f)
records = data.get('records', [])
print(f'Records: {len(records)}')
print(f'Sample keys: {len(records[0].keys()) if records else 0}')
"
```

## 🎯 Use Cases

### Red Day Detection
Collect data for days when trades were emergency exited to analyze patterns:
```bash
python3 collect_89points_fast.py --date 2026-01-07
```

### Regular Collection
Collect data for any trading day to build historical dataset:
```bash
python3 collect_89points_fast.py --date 2026-01-08
```

### Multiple Days
Collect data for multiple days (run separately):
```bash
for date in 2026-01-07 2026-01-08 2026-01-09; do
    python3 collect_89points_fast.py --date $date
done
```

## 📋 Collection Scripts Available

1. **`collect_89points_fast.py`** ⭐ **RECOMMENDED & TESTED**
   - ✅ Fast REST-based collection (~10-30 seconds)
   - ✅ No E*TRADE initialization required
   - ✅ Uses yfinance for technical indicators (no API keys)
   - ✅ Parallel processing (batches of 5)
   - ✅ Works anytime (no trading hours restriction)
   - ✅ Retrieves signals from GCS/daily markers
   - ✅ Merges ORB data and execution data
   - ✅ Saves to local JSON/CSV + GCS automatically
   - **Status**: ✅ Working (tested Jan 7, 2026)

2. **`collect_89points_complete.py`**
   - Complete collection with E*TRADE fallback
   - More comprehensive but slower
   - Requires E*TRADE initialization

3. **`collect_89points_rest.py`**
   - REST-based alternative
   - Similar to fast collector

## 🔍 Data Analysis

### Check Exit Reasons
```python
import json
with open('comprehensive_data/YYYY-MM-DD_comprehensive_data.json') as f:
    data = json.load(f)
records = data.get('records', [])
exit_reasons = [r.get('exit_reason', 'N/A') for r in records]
print(set(exit_reasons))
```

### Check Technical Indicators
```python
import json
with open('comprehensive_data/YYYY-MM-DD_comprehensive_data.json') as f:
    data = json.load(f)
records = data.get('records', [])
sample = records[0]
print(f"RSI: {sample.get('rsi', 0)}")
print(f"Volume Ratio: {sample.get('volume_ratio', 0)}")
print(f"VWAP Distance: {sample.get('vwap_distance_pct', 0)}%")
```

## ⚠️ Important Notes

- **Exit Prices/P&L**: May be 0.0 if not in sanitized signals (not critical for red day detection)
- **Technical Indicators**: Collected at signal collection time (7:30 AM PT)
- **Data Source**: Uses yfinance (REST-based, no API keys required)
- **Collection Time**: ~10-30 seconds for 16 signals
- **Works Anytime**: No trading hours restriction (uses historical data from GCS)
- **Signal Source**: Retrieves from `priority_optimizer/daily_signals/` or `daily_markers/` in GCS

## ✅ Verification

After collection, verify the data was collected successfully:

```bash
# Check file exists and has data
ls -lh comprehensive_data/YYYY-MM-DD_comprehensive_data.json

# Quick verification
python3 -c "
import json
with open('comprehensive_data/YYYY-MM-DD_comprehensive_data.json') as f:
    data = json.load(f)
records = data.get('records', [])
print(f'✅ Records: {len(records)}')
print(f'✅ Data points per record: {data.get(\"data_points_per_record\", 0)}')
if records:
    sample = records[0]
    print(f'✅ Sample symbol: {sample.get(\"symbol\", \"N/A\")}')
    print(f'✅ Sample RSI: {sample.get(\"rsi\", 0):.2f}')
"
```

## 🚀 Future: Automatic Collection

For automatic collection during trading sessions, see:
- `INTEGRATION_AUTOMATIC_COLLECTION.md` - Integration guide
- `INTEGRATION_GUIDE.md` - Complete integration documentation

---

## 📚 Related Documentation

- **`README.md`**: Complete Priority Optimizer documentation
- **`QUICK_START.md`**: Alternative quick start guide
- **`INTEGRATION_GUIDE.md`**: Trade execution integration (automatic collection)
- **`DATA_COLLECTION_INDEX.md`**: Central index for all documentation
- **Session Analysis**: `docs/doc_elements/Sessions/2026/Jan7 Session/` - Today's findings

## 🎯 Use Case Examples

### Daily Collection Workflow
```bash
# Morning: After signal collection (7:30 AM PT)
python3 collect_89points_fast.py --date 2026-01-07

# Verify collection
ls -lh comprehensive_data/2026-01-07_comprehensive_data.json

# Next day: Collect previous day's data
python3 collect_89points_fast.py --date 2026-01-08
```

### Pattern Analysis (Multiple Days)
```bash
# Collect data for multiple days
for date in 2026-01-07 2026-01-08 2026-01-09; do
    echo "Collecting $date..."
    python3 collect_89points_fast.py --date $date
done
```

### Red Day Analysis
```bash
# Collect data for a red day (emergency exit day)
python3 collect_89points_fast.py --date 2026-01-07

# Analyze patterns (see RED_DAY_ANALYSIS_JAN7.md)
```

---

**Last Updated**: January 7, 2026  
**Status**: ✅ Working and Documented

