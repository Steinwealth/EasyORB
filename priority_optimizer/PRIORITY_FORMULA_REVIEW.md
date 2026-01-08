# Priority Rank Formula Review

**Date**: January 6, 2026  
**Status**: ⚠️ **REVIEW REQUIRED**

---

## Current Status

### Current Formula (v2.1) - Rev 00106 (Nov 6, 2025)

**Location**: `modules/prime_trading_system.py` (lines 4472-4637)

**Current Formula**:
```
Priority Score = 
  VWAP Distance (27%) +
  RS vs SPY (25%) +
  ORB Volume (22%) +
  Confidence (13%) +
  RSI (10%) +
  ORB Range (3%)
```

**Issue**: ❌ **ORB Volatility Scoring is NOT included**

The current formula uses:
- `orb_range_score` (3% weight) - Based on raw ORB Range %: `(orb_high - orb_low) / orb_low`
- This is NOT the same as ORB Volatility scoring

---

## What is ORB Volatility Scoring?

Based on the 0DTE Strategy implementation (`easy0DTE/modules/convex_eligibility_filter.py`), ORB Volatility Scoring should be:

1. **Normalized Score**: A percentile-based ranking (0.0-1.0)
2. **Relative Ranking**: Compares volatility across all signals (top 20% = highest score)
3. **Fallback**: Uses `orb_volume_ratio` if `orb_volatility_score` not available

**Current Usage**:
- ✅ Used in 0DTE Strategy's Convex Eligibility Filter (40% weight)
- ❌ NOT used in ORB Strategy Priority Ranking Formula

---

## Proposed Updated Formula

### Option 1: Replace ORB Range with ORB Volatility Scoring

**Updated Formula v2.2**:
```
Priority Score = 
  VWAP Distance (27%) +
  RS vs SPY (25%) +
  ORB Volume (22%) +
  Confidence (13%) +
  RSI (10%) +
  ORB Volatility Scoring (3%)  ← REPLACE ORB Range
```

**ORB Volatility Scoring Calculation**:
```python
# Calculate ORB Volatility Score (normalized percentile-based)
# Similar to 0DTE Convex Eligibility Filter approach

# Step 1: Calculate raw volatility score for each signal
# Use entry_bar_volatility if available, otherwise use orb_range_pct
entry_bar_volatility = signal.get('entry_bar_volatility', 0.0)
if entry_bar_volatility == 0.0:
    # Fallback to ORB Range %
    orb_high = signal.get('orb_high', 0)
    orb_low = signal.get('orb_low', 0)
    if orb_low > 0:
        entry_bar_volatility = ((orb_high - orb_low) / orb_low) * 100
    else:
        entry_bar_volatility = 0.01

# Step 2: Normalize across all signals (percentile-based)
# Higher volatility = higher score (for better trade opportunities)
if all_signals:
    volatility_scores = []
    for s in all_signals:
        vol = s.get('entry_bar_volatility', 0.0)
        if vol == 0.0:
            orb_h = s.get('orb_high', 0)
            orb_l = s.get('orb_low', 0)
            if orb_l > 0:
                vol = ((orb_h - orb_l) / orb_l) * 100
            else:
                vol = 0.01
        volatility_scores.append(vol)
    
    if volatility_scores:
        # Score based on percentile ranking
        # Top 20% = 1.0, Top 40% = 0.85, Top 60% = 0.70, etc.
        percentile_80 = np.percentile(volatility_scores, 80)
        percentile_60 = np.percentile(volatility_scores, 60)
        percentile_40 = np.percentile(volatility_scores, 40)
        percentile_20 = np.percentile(volatility_scores, 20)
        
        if entry_bar_volatility >= percentile_80:
            orb_volatility_score = 1.0      # Top 20%
        elif entry_bar_volatility >= percentile_60:
            orb_volatility_score = 0.85    # Top 40%
        elif entry_bar_volatility >= percentile_40:
            orb_volatility_score = 0.70    # Top 60%
        elif entry_bar_volatility >= percentile_20:
            orb_volatility_score = 0.50    # Top 80%
        else:
            orb_volatility_score = 0.30    # Bottom 20%
else:
    # Fallback: use raw score normalized to 0-1.0
    # Normalize assuming 5%+ volatility = 1.0
    orb_volatility_score = min(entry_bar_volatility / 5.0, 1.0)
```

### Option 2: Increase ORB Volatility Weight (More Aggressive)

**Updated Formula v2.2**:
```
Priority Score = 
  VWAP Distance (27%) +
  RS vs SPY (25%) +
  ORB Volume (20%) +      ← Reduced from 22%
  ORB Volatility Scoring (5%) +  ← NEW, increased weight
  Confidence (13%) +
  RSI (10%)
```

**Rationale**: ORB Volatility is a strong predictor of trade opportunity quality. Higher volatility = more potential profit.

---

## Implementation Notes

### Data Availability

**Available in 89 Data Points**:
- ✅ `entry_bar_volatility` - Volatility at entry bar (calculated from ORB high/low)
- ✅ `orb_range_pct` - ORB Range % (fallback)
- ✅ `orb_high`, `orb_low` - Raw ORB data (for calculation)

**Calculation Method**:
```python
# Entry bar volatility calculation (from prime_stealth_trailing_tp.py)
entry_bar_volatility = ((entry_bar_high - entry_bar_low) / max(entry_bar_low, 1e-9)) * 100
```

### Integration Points

1. **Signal Collection**: Calculate `orb_volatility_score` during signal enrichment
2. **Priority Ranking**: Use `orb_volatility_score` in `calculate_so_priority_score()`
3. **Data Collection**: Store `orb_volatility_score` in comprehensive data collection

---

## Comparison: Current vs Proposed

| Factor | Current (v2.1) | Proposed (v2.2) |
|--------|---------------|-----------------|
| VWAP Distance | 27% | 27% |
| RS vs SPY | 25% | 25% |
| ORB Volume | 22% | 22% (or 20%) |
| Confidence | 13% | 13% |
| RSI | 10% | 10% |
| ORB Range % | 3% (raw %) | ❌ REMOVED |
| **ORB Volatility Scoring** | ❌ **NOT INCLUDED** | ✅ **3-5% (normalized)** |

---

## Next Steps

1. ⚠️ **Review**: Confirm ORB Volatility scoring approach
2. ⚠️ **Implement**: Add ORB Volatility scoring calculation
3. ⚠️ **Test**: Validate with historical data
4. ⚠️ **Deploy**: Update priority ranking formula

---

## References

- **Current Formula**: `modules/prime_trading_system.py:4472-4637`
- **0DTE Volatility Scoring**: `easy0DTE/modules/convex_eligibility_filter.py:125-149`
- **Entry Bar Volatility**: `modules/prime_stealth_trailing_tp.py:883`
- **89 Data Points**: `priority_optimizer/89_DATAPOINTS_ANALYSIS.md`

---

**Status**: ⚠️ **AWAITING CONFIRMATION** - Need to confirm:
1. Should ORB Volatility replace ORB Range % (3%) or be added separately?
2. What weight should ORB Volatility scoring have?
3. Should it use percentile-based ranking (like 0DTE) or raw normalized score?

