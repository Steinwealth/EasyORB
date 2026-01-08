# How to Use - Priority Optimizer Data Collection

**Last Updated**: January 7, 2026  
**Status**: ✅ Working and Tested

---

## 🚀 One Command to Collect Data

```bash
cd priority_optimizer
python3 collect_89points_fast.py --date YYYY-MM-DD
```

**Example** (collect today's data):
```bash
python3 collect_89points_fast.py --date 2026-01-07
```

**Default**: If no date provided, collects for today.

---

## ✅ What You Get

- **89 data points** per signal (technical indicators, ORB data, ranking data)
- **16 signals** collected (for Jan 7, 2026)
- **Files saved**:
  - Local: `comprehensive_data/YYYY-MM-DD_comprehensive_data.json` (49 KB)
  - Local: `comprehensive_data/YYYY-MM-DD_comprehensive_data.csv` (16 KB)
  - GCS: `gs://easy-etrade-strategy-data/priority_optimizer/comprehensive_data/YYYY-MM-DD_comprehensive_data.json`

---

## ⏱️ How Long Does It Take?

- **Collection Time**: ~10-30 seconds for 16 signals
- **No E*TRADE initialization** needed
- **Works anytime** (no trading hours restriction)

---

## 📊 What Data is Collected?

### Technical Indicators
- RSI, MACD, Bollinger Bands, ATR
- Moving Averages (SMA 20/50/200, EMA 12/26)
- Volume indicators (volume ratio, OBV)
- VWAP and VWAP distance %
- RS vs SPY

### ORB Data
- ORB high/low/open/close
- ORB volume
- ORB range %

### Trade Data
- Entry prices
- Exit reasons
- Priority scores
- Confidence levels

**Total**: 89 data points per signal

---

## 🎯 Common Use Cases

### Daily Collection
```bash
# Collect today's data
python3 collect_89points_fast.py

# Or specify date
python3 collect_89points_fast.py --date 2026-01-07
```

### Red Day Analysis
```bash
# Collect data for a red day (emergency exit day)
python3 collect_89points_fast.py --date 2026-01-07

# Analyze patterns (see session docs)
```

### Multiple Days
```bash
# Collect data for multiple days
for date in 2026-01-07 2026-01-08 2026-01-09; do
    python3 collect_89points_fast.py --date $date
done
```

---

## ✅ Verify Collection

After running, verify the data:

```bash
# Check file exists
ls -lh comprehensive_data/YYYY-MM-DD_comprehensive_data.json

# Quick check
python3 -c "
import json
with open('comprehensive_data/YYYY-MM-DD_comprehensive_data.json') as f:
    data = json.load(f)
print(f'Records: {len(data.get(\"records\", []))}')
print(f'Data points: {data.get(\"data_points_per_record\", 0)}')
"
```

---

## 📚 More Information

- **Quick Guide**: `QUICK_COLLECTION_GUIDE.md` - Detailed usage guide
- **Complete Docs**: `README.md` - Full documentation
- **Session Analysis**: `docs/doc_elements/Sessions/2026/Jan7 Session/` - Today's findings

---

## 🔧 Troubleshooting

### Script not found
- **Check**: You're in the `priority_optimizer/` directory
- **Check**: File exists: `ls -la collect_89points_fast.py`

### No data collected
- **Check**: Date format is correct (YYYY-MM-DD)
- **Check**: Signals exist in GCS for that date
- **Check**: GCS is accessible

### Collection takes too long
- **Normal**: ~10-30 seconds for 16 signals
- **If slower**: Check internet connection
- **If fails**: Check yfinance is installed (`pip install yfinance`)

---

**Ready?** Run `python3 collect_89points_fast.py --date YYYY-MM-DD` now!

