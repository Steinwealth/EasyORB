# 89 Data Points Analysis & Sufficiency Assessment

**Last Updated**: January 6, 2026  
**Version**: Rev 00231

## Overview

This document provides a complete breakdown of the 89 data points being collected and assesses whether they are sufficient for:
1. **Early Red Day Detection** (preventing losses and losing trade entries)
2. **Trade Exit Optimization** (maximized profit capture)
3. **Priority Ranking Formula** (ensuring top-ranked trades get most capital and are usually biggest winners)

---

## Complete List of 89 Data Points

### 1. Price Data (5 points)
- `open` - Opening price
- `high` - High price
- `low` - Low price
- `close` - Closing/current price
- `volume` - Trading volume

### 2. Moving Averages (5 points)
- `sma_20` - Simple Moving Average (20 period)
- `sma_50` - Simple Moving Average (50 period)
- `sma_200` - Simple Moving Average (200 period)
- `ema_12` - Exponential Moving Average (12 period)
- `ema_26` - Exponential Moving Average (26 period)

### 3. Momentum Indicators (7 points)
- `rsi` - Relative Strength Index (14 period)
- `rsi_14` - RSI (14 period, explicit)
- `rsi_21` - RSI (21 period)
- `macd` - MACD Line
- `macd_signal` - MACD Signal Line
- `macd_histogram` - MACD Histogram
- `momentum_10` - Momentum (10 period)

### 4. Volatility Indicators (7 points)
- `atr` - Average True Range
- `bollinger_upper` - Bollinger Band Upper
- `bollinger_middle` - Bollinger Band Middle
- `bollinger_lower` - Bollinger Band Lower
- `bollinger_width` - Bollinger Band Width
- `bollinger_position` - Position within Bollinger Bands
- `volatility` - Current volatility measure

### 5. Volume Indicators (4 points)
- `volume_ratio` - Volume vs Average Volume
- `volume_sma` - Volume Simple Moving Average
- `obv` - On-Balance Volume
- `ad_line` - Accumulation/Distribution Line

### 6. Pattern Recognition (4 points)
- `doji` - Doji candlestick pattern
- `hammer` - Hammer candlestick pattern
- `engulfing` - Engulfing candlestick pattern
- `morning_star` - Morning star candlestick pattern

### 7. VWAP Indicators (2 points)
- `vwap` - Volume Weighted Average Price
- `vwap_distance_pct` - Distance from VWAP (%)

### 8. Relative Strength (1 point)
- `rs_vs_spy` - Relative Strength vs SPY (%)

### 9. ORB Data (6 points)
- `orb_high` - Opening Range Breakout High
- `orb_low` - Opening Range Breakout Low
- `orb_open` - Opening Range Open Price
- `orb_close` - Opening Range Close Price
- `orb_volume` - Opening Range Volume
- `orb_range_pct` - Opening Range Size (%)

### 10. Market Context (2 points)
- `spy_price` - SPY current price
- `spy_change_pct` - SPY change percentage

### 11. Trade Data (15 points)
- `symbol` - Stock symbol
- `trade_id` - Unique trade identifier
- `entry_price` - Trade entry price
- `exit_price` - Trade exit price
- `entry_time` - Entry timestamp
- `exit_time` - Exit timestamp
- `shares` - Number of shares
- `position_value` - Position value at entry
- `peak_price` - Peak price reached during trade
- `peak_pct` - Peak profit percentage
- `pnl_dollars` - Profit/Loss in dollars
- `pnl_pct` - Profit/Loss percentage
- `exit_reason` - Reason for exit
- `win` - Win/Loss boolean
- `holding_minutes` - Time held in minutes
- `entry_bar_volatility` - Volatility at entry bar
- `time_weighted_peak` - Time-weighted peak profit

**Note**: Trade data includes 17 fields, but only 15 are counted in the 89 total (symbol and trade_id are identification, not data points)

### 12. Ranking Data (6 points)
- `rank` - Trade rank (1 = highest priority)
- `priority_score` - Calculated priority score (0-1)
- `confidence` - Signal confidence (0-1)
- `orb_volume_ratio` - ORB volume ratio
- `exec_volume_ratio` - Execution volume ratio
- `category` - Signal category/type

### 13. Risk Management (8 points)
- `current_stop_loss` - Current stop loss price
- `stop_loss_distance_pct` - Stop loss distance (%)
- `opening_bar_protection_active` - Opening bar protection status
- `trailing_activated` - Trailing stop activated
- `trailing_distance_pct` - Trailing stop distance (%)
- `breakeven_activated` - Breakeven stop activated
- `gap_risk_pct` - Gap risk percentage
- `max_adverse_excursion` - Maximum adverse excursion

### 14. Market Conditions (5 points)
- `market_regime` - Market regime (bull/bear/sideways)
- `volatility_regime` - Volatility regime (low/medium/high)
- `trend_direction` - Trend direction (up/down/sideways)
- `volume_regime` - Volume regime (low/medium/high)
- `momentum_regime` - Momentum regime (low/medium/high)

### 15. Additional Indicators (16 points)
- `stoch_k` - Stochastic %K
- `stoch_d` - Stochastic %D
- `williams_r` - Williams %R
- `cci` - Commodity Channel Index
- `adx` - Average Directional Index
- `plus_di` - Plus Directional Indicator
- `minus_di` - Minus Directional Indicator
- `aroon_up` - Aroon Up
- `aroon_down` - Aroon Down
- `mfi` - Money Flow Index
- `cmf` - Chaikin Money Flow
- `roc` - Rate of Change
- `ppo` - Percentage Price Oscillator
- `tsi` - True Strength Index
- `ult_osc` - Ultimate Oscillator
- `ichimoku_base` - Ichimoku Base Line

**Total: 89 Data Points**

---

## Sufficiency Assessment

### ✅ 1. Early Red Day Detection

**Current Red Day Detection Uses:**
- RSI levels (<40 for oversold, >70 for overbought)
- Volume analysis (weak volume <1.0x)
- MACD histogram (momentum)
- Technical weakness patterns
- Market context (SPY momentum, VIX)

**89 Data Points Coverage:**

✅ **EXCELLENT COVERAGE** - All critical indicators present:

**Primary Indicators (Currently Used):**
- ✅ `rsi`, `rsi_14`, `rsi_21` - Multiple RSI periods for confirmation
- ✅ `macd`, `macd_signal`, `macd_histogram` - Momentum analysis
- ✅ `volume_ratio`, `volume_sma` - Volume weakness detection
- ✅ `spy_price`, `spy_change_pct` - Market context
- ✅ `market_regime`, `volatility_regime` - Regime analysis

**Additional Indicators Available (Enhancement Potential):**
- ✅ `stoch_k`, `stoch_d` - Stochastic confirmation of oversold/overbought
- ✅ `williams_r` - Additional momentum confirmation
- ✅ `adx`, `plus_di`, `minus_di` - Trend strength indicators
- ✅ `mfi`, `cmf` - Money flow analysis (volume + price)
- ✅ `bollinger_position` - Price position relative to volatility bands
- ✅ `atr` - Volatility expansion/contraction
- ✅ Pattern recognition (`doji`, `hammer`, `engulfing`) - Reversal signals

**Assessment**: ✅ **SUFFICIENT** - The 89 data points provide comprehensive coverage for red day detection. Current system uses RSI + Volume, but additional indicators (Stochastic, ADX, Money Flow) can enhance accuracy.

**Recommendations**:
- Use `stoch_k`/`stoch_d` to confirm RSI oversold conditions
- Use `mfi`/`cmf` to detect money flow weakness (more reliable than volume alone)
- Use `adx` to measure trend strength (weak trends = higher red day risk)
- Use `bollinger_position` to detect price compression (often precedes red days)

---

### ✅ 2. Trade Exit Optimization (Maximized Profit Capture)

**Current Exit System Uses:**
- Peak price tracking
- Trailing stops
- Breakeven activation
- Time-based exits
- Exit reasons

**89 Data Points Coverage:**

✅ **EXCELLENT COVERAGE** - All critical exit indicators present:

**Primary Exit Indicators:**
- ✅ `peak_price`, `peak_pct` - Peak profit tracking
- ✅ `time_weighted_peak` - Time-adjusted peak (prevents early exits)
- ✅ `trailing_activated`, `trailing_distance_pct` - Trailing stop data
- ✅ `breakeven_activated` - Breakeven stop data
- ✅ `holding_minutes` - Time-based exit analysis
- ✅ `exit_reason` - Exit trigger analysis
- ✅ `max_adverse_excursion` - Drawdown analysis

**Technical Exit Signals Available:**
- ✅ `rsi` - Overbought conditions (RSI >70 = potential exit)
- ✅ `macd_histogram` - Momentum reversal (negative histogram = exit signal)
- ✅ `bollinger_position` - Upper band touch (potential exit)
- ✅ `stoch_k`, `stoch_d` - Stochastic overbought (>80 = exit signal)
- ✅ `williams_r` - Williams %R overbought (<-20 = exit signal)
- ✅ `volume_ratio` - Volume exhaustion (declining volume = exit signal)
- ✅ `mfi`, `cmf` - Money flow reversal (negative flow = exit signal)
- ✅ Pattern recognition - Reversal patterns (doji, engulfing = exit signals)

**Assessment**: ✅ **SUFFICIENT** - The 89 data points provide comprehensive exit signal analysis. Current system tracks peak profit, but technical indicators can optimize exit timing.

**Recommendations**:
- **Peak Capture Analysis**: Use `peak_pct` vs `pnl_pct` to measure exit efficiency
- **Momentum Exhaustion**: Exit when `rsi` >70 AND `macd_histogram` turns negative
- **Volume Exhaustion**: Exit when `volume_ratio` <0.8 AND price near peak
- **Multi-Signal Confirmation**: Exit when 3+ indicators show reversal (RSI + Stochastic + Money Flow)
- **Time-Weighted Peak**: Use `time_weighted_peak` to prevent premature exits on quick spikes

---

### ⚠️ 3. Priority Ranking Formula Optimization

**Current Priority Ranking Formula (ORB Strategy):**
```
Priority Score = 
  VWAP Distance (27%) +
  RS vs SPY (25%) +
  ORB Volume (22%) +
  Confidence (13%) +
  RSI (10%) +
  ORB Range (3%)
```

**89 Data Points Coverage:**

✅ **GOOD COVERAGE** - All current formula components present:

**Current Formula Components:**
- ✅ `vwap_distance_pct` - VWAP Distance (27% weight)
- ✅ `rs_vs_spy` - RS vs SPY (25% weight)
- ✅ `orb_volume_ratio` - ORB Volume (22% weight)
- ✅ `confidence` - Confidence (13% weight)
- ✅ `rsi` - RSI (10% weight)
- ✅ `orb_range_pct` - ORB Range (3% weight)

**Additional Indicators Available (Enhancement Potential):**
- ✅ `macd_histogram` - Momentum strength (not currently used)
- ✅ `volume_ratio` - General volume strength (not currently used)
- ✅ `bollinger_position` - Price position within volatility bands
- ✅ `atr` - Volatility measure (higher ATR = more potential)
- ✅ `stoch_k`, `stoch_d` - Momentum confirmation
- ✅ `adx` - Trend strength (stronger trends = better trades)
- ✅ `mfi`, `cmf` - Money flow (institutional buying)
- ✅ `sma_20`, `sma_50`, `sma_200` - Trend alignment
- ✅ `ema_12`, `ema_26` - Short-term momentum

**Assessment**: ⚠️ **MOSTLY SUFFICIENT** - Current formula uses 6 factors, but 89 data points provide many additional factors that could improve ranking accuracy.

**Key Gap**: **Trade Performance Correlation** - The 89 points include trade execution data (`pnl_dollars`, `pnl_pct`, `win`), which is CRITICAL for validating that top-ranked trades actually perform best.

**Recommendations**:

1. **Validate Current Formula**:
   - Analyze correlation between `priority_score` and `pnl_dollars`/`pnl_pct`
   - Ensure top-ranked trades (`rank` 1-5) have highest average P&L
   - If correlation is weak, adjust weights

2. **Add Missing Factors**:
   - **MACD Histogram** (momentum strength) - Currently not used, but strong predictor
   - **ADX** (trend strength) - Strong trends = better trades
   - **Money Flow** (`mfi`, `cmf`) - Institutional buying = better trades
   - **Trend Alignment** (`sma_20` > `sma_50` > `sma_200`) - Aligned trends = better trades

3. **Optimize Weights**:
   - Use historical data to find optimal weights
   - Test different combinations of factors
   - Ensure top 20% of ranked trades capture 80%+ of profits

4. **Capital Allocation Validation**:
   - Verify that trades with highest `priority_score` get most capital
   - Analyze if `position_value` correlates with `priority_score`
   - Ensure top-ranked trades are usually biggest winners

---

## Data Gaps & Recommendations

### Current Gaps

1. **VIX Data** ❌
   - Red day detection uses VIX, but not in 89-point collection
   - **Recommendation**: Add `vix_level` to market context

2. **Time-of-Day Data** ⚠️
   - Entry/exit times are captured, but not time-of-day patterns
   - **Recommendation**: Add `entry_hour`, `exit_hour` for time-based analysis

3. **Pre-Market Data** ❌
   - Pre-market activity can predict red days
   - **Recommendation**: Add `premarket_change_pct`, `premarket_volume`

4. **Sector/Industry Data** ❌
   - Sector rotation affects trade performance
   - **Recommendation**: Add `sector`, `industry` for sector analysis

5. **Options Data (for 0DTE)** ⚠️
   - 0DTE strategy needs options-specific data
   - **Recommendation**: Add `options_iv`, `options_delta`, `options_theta`, `options_vega`

### Enhancement Opportunities

1. **Derived Metrics**:
   - Calculate `rsi_divergence` (price vs RSI)
   - Calculate `volume_price_trend` (OBV slope)
   - Calculate `trend_strength` (ADX + DI+/-)

2. **Multi-Timeframe Analysis**:
   - Add 5-minute, 15-minute, 1-hour indicators
   - Compare short-term vs long-term trends

3. **Market Breadth**:
   - Add `advancing_issues`, `declining_issues`
   - Add `new_highs`, `new_lows`

---

## Conclusion

### Overall Assessment: ✅ **SUFFICIENT** with Enhancements Recommended

**Red Day Detection**: ✅ **EXCELLENT** - All critical indicators present, additional indicators can enhance accuracy

**Exit Optimization**: ✅ **EXCELLENT** - Comprehensive exit signal coverage, technical indicators can optimize timing

**Priority Ranking**: ⚠️ **GOOD** - Current formula components present, but trade performance correlation analysis is critical for validation

### Critical Success Factors

1. **Data Quality**: Ensure all 89 points are collected accurately during trading hours
2. **Historical Analysis**: Collect data over many trading sessions (50+ days) for statistical significance
3. **Correlation Analysis**: Validate that top-ranked trades actually perform best
4. **Continuous Optimization**: Regularly review and adjust formulas based on new data

### Next Steps

1. ✅ **Collect Data**: Run `collect_daily_89points.py` daily during trading hours
2. ⚠️ **Analyze Correlations**: After 20+ trading sessions, analyze correlations
3. ⚠️ **Validate Formulas**: Ensure top-ranked trades are biggest winners
4. ⚠️ **Optimize Weights**: Adjust priority ranking formula weights based on data
5. ⚠️ **Enhance Detection**: Add VIX and pre-market data for red day detection

---

**The 89 data points provide a solid foundation for all three optimization goals. With proper analysis and validation, they should be sufficient to significantly improve strategy performance.**

