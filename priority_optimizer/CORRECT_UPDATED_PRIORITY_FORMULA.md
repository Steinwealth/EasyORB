# Correct Updated Priority Rank Formula for ORB Strategy

**Date**: December 23, 2025  
**Status**: ✅ **COMPLETE FORMULA DOCUMENTATION**  
**Current Version**: v2.1 (Rev 00106, Nov 6, 2025) - **ACTUALLY IMPLEMENTED**  
**Updated Version**: v2.2 (Proposed) - **READY FOR IMPLEMENTATION**

---

## 📋 **Executive Summary**

The **current production formula is v2.1** (Rev 00106, Nov 6, 2025), which does **NOT** include ORB Volatility Scoring. The **updated formula v2.2** was documented but **never actually implemented**. This document provides the **complete updated formula v2.2** with ORB Volatility Scoring, ready for implementation.

---

## ✅ **Current Formula (v2.1) - ACTUALLY IMPLEMENTED**

**Location**: `modules/prime_trading_system.py` (lines 4472-4637)  
**Revision**: Rev 00106 (Nov 6, 2025)  
**Status**: ✅ **CURRENTLY IN PRODUCTION**

### **Formula v2.1**:
```
Priority Score = 
  VWAP Distance (27%) +
  RS vs SPY (25%) +
  ORB Volume (22%) +
  Confidence (13%) +
  RSI (10%) +
  ORB Range (3%)  ← Raw percentage, NOT ORB Volatility Scoring
```

### **Weights Breakdown**:
- **VWAP Distance**: 27% (correlation +0.772) ⭐⭐⭐ STRONGEST PREDICTOR
- **RS vs SPY**: 25% (correlation +0.609) ⭐⭐⭐ 2ND STRONGEST
- **ORB Volume**: 22% (correlation +0.342) ✅ MODERATE
- **Confidence**: 13% (correlation +0.333) ⚠️ WEAK
- **RSI**: 10% (correlation -0.096) ⚠️ CONTEXT-DEPENDENT
- **ORB Range**: 3% (raw percentage) ⚠️ MINIMAL CONTRIBUTION

### **Issue**:
❌ **ORB Volatility Scoring is NOT included**  
- Uses `orb_range_score` (raw ORB Range %) instead
- Raw percentage: `(orb_high - orb_low) / orb_low`
- This is **NOT** the same as ORB Volatility Scoring

---

## 🎯 **Updated Formula (v2.2) - RECOMMENDED**

**Status**: ⚠️ **PROPOSED - NOT YET IMPLEMENTED**  
**Revision**: Rev 00232 (Pending Implementation)  
**Date**: January 6, 2026

### **Formula v2.2** (Option 1 - Recommended):
```
Priority Score = 
  VWAP Distance (27%) +
  RS vs SPY (25%) +
  ORB Volume (22%) +
  Confidence (13%) +
  RSI (10%) +
  ORB Volatility Scoring (3%)  ← NEW: Percentile-based, replaces ORB Range %
```

### **Weights Breakdown**:
- **VWAP Distance**: 27% (no change)
- **RS vs SPY**: 25% (no change)
- **ORB Volume**: 22% (no change)
- **Confidence**: 13% (no change)
- **RSI**: 10% (no change)
- **ORB Volatility Scoring**: 3% (NEW - replaces ORB Range %)

### **Key Changes from v2.1 → v2.2**:
- ✅ **Replaced** ORB Range % (raw %) with ORB Volatility Scoring (percentile-based)
- ✅ **Maintains** same total weight (100%)
- ✅ **Uses** `entry_bar_volatility` with percentile ranking across all signals
- ✅ **Consistent** with 0DTE Strategy approach (40% weight in Convex Eligibility Filter)

---

## 📊 **ORB Volatility Scoring - Complete Implementation**

### **What is ORB Volatility Scoring?**

ORB Volatility Scoring is a **normalized percentile-based ranking** (0.0-1.0) that compares volatility across all signals. It's different from raw ORB Range % because:

1. **Percentile-Based**: Ranks signals relative to each other (top 20% = highest score)
2. **Normalized**: Converts raw volatility to 0.0-1.0 scale
3. **Relative Ranking**: Top performers get maximum score, not absolute thresholds

### **Data Source**:
- **Primary**: `entry_bar_volatility` - Volatility at entry bar
  - Calculation: `((entry_bar_high - entry_bar_low) / max(entry_bar_low, 1e-9)) * 100`
- **Fallback**: `orb_range_pct` - ORB Range % if `entry_bar_volatility` not available
  - Calculation: `((orb_high - orb_low) / orb_low) * 100`

### **Complete Implementation Code**:

```python
import numpy as np
from typing import Dict, List, Any, Optional

def calculate_orb_volatility_score(
    signal: Dict[str, Any],
    all_signals: Optional[List[Dict[str, Any]]] = None
) -> float:
    """
    Calculate ORB Volatility Score (normalized percentile-based)
    
    Similar to 0DTE Convex Eligibility Filter approach (40% weight in 0DTE).
    
    Args:
        signal: Current signal dictionary
        all_signals: All signals for percentile calculation (required for percentile-based)
    
    Returns:
        ORB Volatility Score (0.0-1.0, higher = more volatile = better opportunity)
    """
    # Step 1: Get raw volatility value
    entry_bar_volatility = signal.get('entry_bar_volatility', 0.0)
    
    # Fallback to ORB Range % if entry_bar_volatility not available
    if entry_bar_volatility == 0.0:
        orb_high = signal.get('orb_high', 0)
        orb_low = signal.get('orb_low', 0)
        if orb_low > 0:
            entry_bar_volatility = ((orb_high - orb_low) / orb_low) * 100
        else:
            entry_bar_volatility = 0.01  # Minimum value
    
    # Step 2: Normalize across all signals (percentile-based)
    if all_signals and len(all_signals) > 1:
        # Collect volatility scores from all signals
        volatility_scores = []
        for s in all_signals:
            vol = s.get('entry_bar_volatility', 0.0)
            if vol == 0.0:
                # Fallback to ORB Range %
                orb_h = s.get('orb_high', 0)
                orb_l = s.get('orb_low', 0)
                if orb_l > 0:
                    vol = ((orb_h - orb_l) / orb_l) * 100
                else:
                    vol = 0.01
            volatility_scores.append(vol)
        
        if volatility_scores:
            # Calculate percentiles
            percentile_80 = np.percentile(volatility_scores, 80)
            percentile_60 = np.percentile(volatility_scores, 60)
            percentile_40 = np.percentile(volatility_scores, 40)
            percentile_20 = np.percentile(volatility_scores, 20)
            
            # Score based on percentile ranking
            # Higher volatility = higher score (better trade opportunity)
            if entry_bar_volatility >= percentile_80:
                orb_volatility_score = 1.0      # Top 20% - Maximum score
            elif entry_bar_volatility >= percentile_60:
                orb_volatility_score = 0.85    # Top 40%
            elif entry_bar_volatility >= percentile_40:
                orb_volatility_score = 0.70    # Top 60%
            elif entry_bar_volatility >= percentile_20:
                orb_volatility_score = 0.50    # Top 80%
            else:
                orb_volatility_score = 0.30    # Bottom 20% - Minimum score
            
            return orb_volatility_score
    
    # Fallback: Use raw score normalized to 0-1.0
    # Normalize assuming 5%+ volatility = 1.0
    orb_volatility_score = min(entry_bar_volatility / 5.0, 1.0)
    return orb_volatility_score
```

### **Percentile Scoring Breakdown**:
- **Top 20%** (≥ 80th percentile): Score = **1.0** (Maximum)
- **Top 40%** (≥ 60th percentile): Score = **0.85**
- **Top 60%** (≥ 40th percentile): Score = **0.70**
- **Top 80%** (≥ 20th percentile): Score = **0.50**
- **Bottom 20%** (< 20th percentile): Score = **0.30** (Minimum)

---

## 🔧 **Updated `calculate_so_priority_score()` Function**

### **Complete Implementation**:

```python
def calculate_so_priority_score(signal, all_signals=None):
    """
    Calculate multi-factor priority score for SO signals
    
    Rev 00232: Formula v2.2 - ORB Volatility Scoring Added (Jan 6, 2026)
    
    Formula v2.2 Weights:
    - VWAP Distance: 27% (↑ +2%, correlation +0.772) ⭐
    - RS vs SPY: 25% (same, correlation +0.609) ⭐
    - ORB Volume: 22% (↑ +2%, correlation +0.342)
    - Confidence: 13% (↓ -2%, correlation +0.333 weak)
    - RSI: 10% (same, context-aware)
    - ORB Volatility Scoring: 3% (NEW - replaces ORB Range %)
    
    Changes from v2.1 → v2.2:
    - Replaced ORB Range % (raw %) with ORB Volatility Scoring (percentile-based)
    - ORB Volatility uses normalized percentile ranking (like 0DTE Strategy)
    - Better predictor of trade opportunity quality
    """
    symbol = signal.get('symbol', '')
    
    # Factor 1: RS vs SPY (25%)
    rs_vs_spy = signal.get('rs_vs_spy', 0)
    if rs_vs_spy >= 20.0:
        rs_score = 1.0
    elif rs_vs_spy >= 10.0:
        rs_score = 0.85
    elif rs_vs_spy >= 5.0:
        rs_score = 0.70
    elif rs_vs_spy >= 0.0:
        rs_score = 0.50
    elif rs_vs_spy >= -10.0:
        rs_score = 0.35
    else:
        rs_score = 0.20
    
    # Factor 2: VWAP Distance (27%)
    vwap_distance = signal.get('vwap_distance_pct', 0)
    if vwap_distance >= 15.0:
        vwap_score = 1.0
    elif vwap_distance >= 10.0:
        vwap_score = 0.90
    elif vwap_distance >= 5.0:
        vwap_score = 0.75
    elif vwap_distance >= 0.0:
        vwap_score = 0.60
    elif vwap_distance >= -3.0:
        vwap_score = 0.40
    else:
        vwap_score = 0.20
    
    # Factor 3: ORB Volume Ratio (22%)
    orb_volume_ratio = signal.get('volume_ratio', 1.0)
    if orb_volume_ratio >= 3.0:
        orb_vol_score = 1.0
    elif orb_volume_ratio >= 2.0:
        orb_vol_score = 0.85
    elif orb_volume_ratio >= 1.5:
        orb_vol_score = 0.70
    elif orb_volume_ratio >= 1.2:
        orb_vol_score = 0.50
    else:
        orb_vol_score = 0.25
    
    # Factor 4: Confidence (13%)
    confidence = signal.get('confidence', 0.5)
    if confidence >= 0.5:
        conf_score = (confidence - 0.5) / 0.5
        conf_score = min(1.0, conf_score)
    else:
        conf_score = 0.0
    
    # Factor 5: RSI Context-Aware (10%)
    rsi = signal.get('rsi', 55.0)
    market_regime = signal.get('market_regime', 'MIXED')
    
    if market_regime == 'BULL':
        if 65 <= rsi <= 75:
            rsi_score = 0.85
        elif 55 <= rsi < 65:
            rsi_score = 1.0
        elif 50 <= rsi < 55:
            rsi_score = 0.90
        elif 45 <= rsi < 50:
            rsi_score = 0.75
        elif rsi > 75:
            rsi_score = 0.60
        else:
            rsi_score = 0.40
    else:
        if 50 <= rsi <= 60:
            rsi_score = 1.0
        elif 45 <= rsi < 50:
            rsi_score = 0.85
        elif 60 < rsi <= 65:
            rsi_score = 0.70
        elif rsi > 65:
            rsi_score = 0.30
        elif 40 <= rsi < 45:
            rsi_score = 0.75
        else:
            rsi_score = 0.60
    
    # Factor 6: ORB Volatility Scoring (3%) - NEW in v2.2
    orb_volatility_score = calculate_orb_volatility_score(signal, all_signals)
    
    # Rev 00232: Formula v2.2 - ORB Volatility Scoring Added
    priority_score = (
        vwap_score * 0.27 +                    # 27% - VWAP Distance ⭐
        rs_score * 0.25 +                      # 25% - RS vs SPY ⭐
        orb_vol_score * 0.22 +                 # 22% - ORB volume
        conf_score * 0.13 +                    # 13% - Confidence
        rsi_score * 0.10 +                     # 10% - RSI
        orb_volatility_score * 0.03           # 3% - ORB Volatility Scoring (NEW)
    )
    
    # Store calculated values in signal for data collection
    signal['priority_score'] = priority_score
    signal['rs_vs_spy'] = rs_vs_spy
    signal['vwap_distance_pct'] = vwap_distance
    signal['volume_ratio'] = orb_volume_ratio
    signal['orb_volume_ratio'] = orb_volume_ratio
    signal['rsi'] = rsi
    signal['orb_volatility_score'] = orb_volatility_score  # NEW in v2.2
    
    return priority_score
```

---

## 📊 **Comparison: v2.1 vs v2.2**

| Factor | v2.1 (Current) | v2.2 (Updated) | Change |
|--------|----------------|----------------|--------|
| **VWAP Distance** | 27% | 27% | No change |
| **RS vs SPY** | 25% | 25% | No change |
| **ORB Volume** | 22% | 22% | No change |
| **Confidence** | 13% | 13% | No change |
| **RSI** | 10% | 10% | No change |
| **ORB Range %** | 3% (raw %) | ❌ **REMOVED** | Replaced |
| **ORB Volatility Scoring** | ❌ **NOT INCLUDED** | ✅ **3% (percentile-based)** | **NEW** |

---

## 🎯 **Why ORB Volatility Scoring?**

### **Evidence from 0DTE Strategy**:
- **0DTE Usage**: ORB Volatility Scoring has **40% weight** in 0DTE Strategy's Convex Eligibility Filter
- **Proven Predictor**: Higher volatility = better trade opportunities
- **Percentile-Based**: Ranks signals relative to each other (more accurate than absolute thresholds)

### **Data Availability**:
- ✅ `entry_bar_volatility` is collected in 89 data points
- ✅ Calculated from ORB high/low: `((entry_bar_high - entry_bar_low) / max(entry_bar_low, 1e-9)) * 100`
- ✅ Fallback to `orb_range_pct` if `entry_bar_volatility` not available

---

## 📝 **Implementation Steps**

1. **Add `calculate_orb_volatility_score()` function** to `prime_trading_system.py`
2. **Update `calculate_so_priority_score()` function** to use ORB Volatility Scoring
3. **Pass `all_signals` parameter** to `calculate_so_priority_score()` for percentile calculation
4. **Store `orb_volatility_score`** in signal dictionary for data collection
5. **Test with historical data** to validate improvement
6. **Deploy as Rev 00232**

---

## 📚 **References**

- **Current Formula**: `modules/prime_trading_system.py:4472-4637`
- **0DTE Volatility Scoring**: `easy0DTE/modules/convex_eligibility_filter.py:125-149`
- **Entry Bar Volatility**: `modules/prime_stealth_trailing_tp.py:883`
- **89 Data Points**: `priority_optimizer/89_DATAPOINTS_ANALYSIS.md`
- **Formula Review**: `priority_optimizer/PRIORITY_FORMULA_REVIEW.md`
- **Status Clarification**: `priority_optimizer/FORMULA_STATUS_CLARIFICATION.md`

---

## ✅ **Summary**

### **Updated Formula v2.2**:
```
Priority Score = 
  VWAP Distance (27%) +
  RS vs SPY (25%) +
  ORB Volume (22%) +
  Confidence (13%) +
  RSI (10%) +
  ORB Volatility Scoring (3%)  ← NEW: Percentile-based, replaces ORB Range %
```

### **Key Changes**:
- ✅ Replaced ORB Range % (raw %) with ORB Volatility Scoring (percentile-based)
- ✅ Uses `entry_bar_volatility` with percentile ranking across all signals
- ✅ Consistent with 0DTE Strategy approach
- ✅ Better predictor of trade opportunity quality

### **Status**:
- **Current Production**: v2.1 (Rev 00106) - **ACTUALLY IMPLEMENTED**
- **Proposed Update**: v2.2 (Rev 00232) - **READY FOR IMPLEMENTATION**

---

**Last Updated**: December 23, 2025  
**Version**: v2.2 (Proposed)  
**Revision**: Rev 00232 (Pending Implementation)

