# Data Recovery and Collection Guide

**Last Updated**: January 6, 2026  
**Version**: Rev 00231

## Overview

This guide explains how to recover historical trading data from Google Cloud Storage and set up collection of the 89 comprehensive data points for future analysis.

## Recovery Process

### Step 1: Recover Data from GCS

Run the recovery script to download all available data from Google Cloud Storage:

```bash
cd priority_optimizer
python3 recover_gcs_data.py
```

This will:
- Download all signal files from `priority_optimizer/daily_signals/`
- Download trade history from `demo_account/mock_trading_history.json`
- Download any existing comprehensive data files
- Save everything to `priority_optimizer/recovered_data/`

### Step 2: Reconstruct 89-Point Data

Reconstruct comprehensive 89-point data from recovered trade history:

```bash
python3 reconstruct_89point_data.py
```

This will:
- Load recovered trade history and signals
- Attempt to reconstruct 89-point data records
- Save reconstructed data to `priority_optimizer/recovered_data/comprehensive_data_reconstructed/`

**Note**: Reconstructed data will be **partial** because:
- Real-time technical indicators (RSI, MACD, Bollinger Bands, etc.) require market data collection during trade execution
- Historical market data is not stored in trade history
- Some indicators require intraday price/volume data

### Step 3: Verify Integration

Check if comprehensive data collection is integrated into trade execution:

```bash
grep -r "comprehensive_data_collector\|collect_trade_data" ../modules/prime_trading_system.py
```

If not found, the comprehensive data collector needs to be integrated into the trade execution flow.

## Future Data Collection

### Integration Points

The comprehensive data collector should be called at these points:

1. **Trade Execution** (7:30 AM PT):
   - After trade is executed
   - Collect all 89 data points from current market data
   - Store immediately

2. **Trade Exit**:
   - When position is closed
   - Update comprehensive record with exit data
   - Finalize record

3. **End of Day**:
   - Save all collected data to GCS
   - Generate summary reports

### Required Integration

Add to `modules/prime_trading_system.py` or `modules/mock_trading_executor.py`:

```python
from modules.comprehensive_data_collector import get_comprehensive_data_collector

# After trade execution
comprehensive_collector = get_comprehensive_data_collector(
    gcs_bucket="easy-etrade-strategy-data",
    gcs_prefix="priority_optimizer/comprehensive_data"
)

# Collect 89 data points
comprehensive_record = comprehensive_collector.collect_trade_data(
    symbol=symbol,
    trade_id=trade_id,
    market_data=market_data_dict,  # From E*TRADE API
    trade_data=trade_data_dict,     # Entry, exit, P&L
    ranking_data=ranking_data_dict, # Priority score, rank
    risk_data=risk_data_dict,        # Stop loss, trailing stops
    market_conditions=market_conditions_dict  # Market regime
)

# At end of day
await comprehensive_collector.save_daily_data(format='both')
```

## Data Structure

### 89 Data Points Breakdown

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

## Analysis Use Cases

Once data is collected, use it for:

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

4. **Position Sizing**
   - Analyze optimal position sizes by rank
   - Validate batch position sizing algorithm
   - Optimize capital allocation

## Files

- `recover_gcs_data.py`: Downloads data from GCS
- `reconstruct_89point_data.py`: Reconstructs comprehensive data from recovered trades
- `README_RECOVERY.md`: This guide

## Next Steps

1. ✅ Run recovery scripts to get existing data
2. ⚠️ Verify comprehensive data collector integration
3. ⚠️ Add integration if missing
4. ✅ Test data collection on next trading session
5. ✅ Analyze collected data for optimization

---

*For comprehensive data collector implementation, see [modules/comprehensive_data_collector.py](../modules/comprehensive_data_collector.py)*

