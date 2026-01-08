# Complete Trading Session Workflow - ORB Strategy & 0DTE Strategy

**Last Updated**: January 7, 2026  
**Version**: Rev 00231

---

## 📋 **Table of Contents**

1. [E*TRADE Token Management](#etrade-token-management)
2. [ORB Strategy Trading Session Steps](#orb-strategy-trading-session-steps)
3. [0DTE Strategy Trading Session Steps](#0dte-strategy-trading-session-steps)
4. [End of Day (EOD) Process](#end-of-day-eod-process)
5. [Complete Alert List](#complete-alert-list)

---

## 🔐 **E*TRADE Token Management**

### **Token Expiration & Renewal Workflow**

#### **Step 1: Token Validation Check**
- **When**: System initialization, before trading operations
- **Action**: `ETradeOAuthIntegration.validate_and_renew()`
- **Checks**:
  - Token authentication status
  - Token expiration status
  - Last used timestamp

#### **Step 2: Token Renewal (if needed)**
- **When**: Tokens expire or need renewal
- **Action**: `ETradeOAuthIntegration.renew_tokens()`
- **Process**:
  1. Request new access token from E*TRADE
  2. Update token storage
  3. Update last used timestamp

#### **Step 3: Alert - OAuth Token Renewal Success**
- **Alert Method**: `send_oauth_renewal_success()`
- **When**: Tokens successfully renewed
- **Content**: 
  - Environment (prod/sandbox)
  - Token status (Active and ready)
  - Renewal confirmation

#### **Step 4: Alert - OAuth Token Renewal Error**
- **Alert Method**: `send_oauth_renewal_error()`
- **When**: Token renewal fails
- **Content**:
  - Environment
  - Error message
  - Manual intervention required

#### **Step 5: Alert - OAuth Warning**
- **Alert Method**: `send_oauth_warning()`
- **When**: OAuth not authenticated
- **Content**: Manual intervention required message

---

## 🎯 **ORB Strategy Trading Session Steps**

### **Phase 0: Pre-Market Preparation (5:30 AM PT / 8:30 AM ET)**

#### **Step 1: Good Morning Alert**
- **Time**: 5:30 AM PT (1 hour before market open)
- **Trigger**: Cloud Scheduler (`oauth-market-open-alert` job)
- **Alert Method**: `send_oauth_market_open_alert()`
- **Content**:
  - System status
  - OAuth token status
  - Market open countdown
  - Trading day confirmation

#### **Step 2: Holiday Check**
- **Time**: 5:30 AM PT (checked daily)
- **Action**: `dynamic_holiday_calculator.should_skip_trading()`
- **Checks**:
  - Weekend detection
  - Bank holidays
  - Low-volume holidays
- **Alert**: `send_holiday_alert()` (if holiday detected)
- **Result**: Trading disabled if holiday detected

#### **Step 3: Daily Reset**
- **Time**: Midnight UTC (new trading day detected)
- **Actions**:
  - Reset all daily flags
  - Clear executed symbols list
  - Reset ORB capture flag
  - Reset SO collection alert flag
  - Reset SO execution alert flag
  - Reset EOD report flag
  - Reset holiday check flag

#### **Step 4: ADV Data Refresh**
- **Time**: 6:00 AM PT (before ORB capture)
- **Action**: `_refresh_adv_data_if_needed()`
- **Purpose**: Refresh Average Daily Volume data for Slip Guard

---

### **Phase 1: ORB Capture (6:30-6:45 AM PT / 9:30-9:45 AM ET)**

#### **Step 1: ORB Window Opens**
- **Time**: 6:30 AM PT (9:30 AM ET)
- **Window**: First 15 minutes of market open
- **Purpose**: Capture opening range (high/low) for all symbols

#### **Step 2: ORB Capture Execution**
- **Time**: 6:45 AM PT (9:45 AM ET) - **AT END OF WINDOW**
- **Action**: `_capture_orb_for_all_symbols()`
- **Process**:
  1. Batch fetch intraday data for all symbols (E*TRADE batch quotes)
  2. Extract ORB high/low from first 15-minute candle
  3. Store ORB data for entire trading day
  4. Process 147 symbols from `core_list.csv`
  5. Fallback: yfinance if E*TRADE unavailable
- **Duration**: 2-5 seconds for all symbols
- **Flag**: `_orb_captured_today = True`

#### **Step 3: 0DTE ORB Data Extraction**
- **Time**: Immediately after ORB capture
- **Action**: `dte0_manager.get_spx_qqq_spy_orb_data()`
- **Purpose**: Extract SPX, QQQ, SPY ORB data for 0DTE Strategy
- **Data Extracted**:
  - SPX ORB (Priority 1)
  - QQQ ORB (Priority 2)
  - SPY ORB (Priority 3)

#### **Step 4: Alert - ORB Capture Complete**
- **Alert Method**: `send_orb_capture_complete_alert()`
- **When**: ORB capture successful
- **Content**:
  - Symbols captured count
  - Capture time (seconds)
  - Sample ORB ranges (top 5)
  - 0DTE ORB data (SPX/QQQ/SPY)
  - ORB Strategy symbol count
  - 0DTE Strategy symbol count
- **Flag**: `_orb_capture_alert_sent_today = True`

#### **Step 5: Alert - ORB Capture Failed**
- **Alert Method**: `send_orb_capture_failed_alert()`
- **When**: ORB capture fails or no data found
- **Content**:
  - Total symbols attempted
  - Failure reason
  - Retry information

---

### **Phase 2: Standard Order (SO) Signal Collection (7:15-7:30 AM PT / 10:15-10:30 AM ET)**

#### **Step 1: Previous Candle Pre-Fetch**
- **Time**: 7:15:00 AM PT (SO window opens)
- **Action**: `_prefetch_previous_candle_data()`
- **Purpose**: Pre-fetch 7:00-7:15 AM PT candle data for instant SO validation
- **Data Collected**:
  - Previous candle close
  - Previous candle open
  - Volume color (green/red)
- **Flag**: `_prev_candle_prefetched_today = True`

#### **Step 2: SO Signal Scanning**
- **Time**: 7:15-7:30 AM PT (15-minute collection window)
- **Frequency**: Every 30 seconds
- **Action**: `_scan_orb_batch_signals()`
- **Process**:
  1. Scan all symbols in `core_list.csv` (147 symbols)
  2. Validate SO rules for each symbol:
     - **Bullish SO**: Price +0.2% above ORB high, previous candle closed above ORB high, green volume
     - **Inverse SO**: Price -0.2% below ORB low, previous candle closed below ORB low, red volume
  3. Calculate priority scores (Formula v2.1)
  4. Rank signals by priority score
  5. Store top signals for batch execution
- **Storage**: Signals stored in `_pending_so_signals` list

#### **Step 3: Red Day Filter Evaluation**
- **Time**: 7:30 AM PT (before SO execution)
- **Action**: `PrimeEnhancedRedDayDetector.evaluate_red_day_risk()`
- **Checks**:
  - Pattern 1: Oversold RSI (<40) + Weak Volume (<1.0x)
  - Pattern 2: Overbought RSI (>80) + Weak Volume (<1.0x) with momentum overrides
  - Pattern 3: Weak Volume Alone (≥80%)
  - Momentum Override: MACD > 0.0 AND RS vs SPY > 2.0
- **Result**: 
  - If Red Day detected: Trading blocked, alert sent
  - If not Red Day: Trading proceeds
- **Alert**: `send_telegram_alert()` (if Red Day detected)

#### **Step 4: 0DTE Signal Processing (Before SO Alert)**
- **Time**: 7:30 AM PT (before SO execution alert)
- **Action**: `dte0_manager.listen_to_orb_signals()`
- **Process**:
  1. Receive ORB signals from SO collection
  2. Apply Convex Eligibility Filter
  3. Generate 0DTE signals for SPX/QQQ/SPY
  4. Calculate priority scores
  5. Rank by priority
  6. Pre-validate Hard Gate (for alert display)
- **Output**: Qualified 0DTE signals stored in `_pending_dte0_signals`

#### **Step 5: Alert - SO Signal Collection**
- **Alert Method**: `send_so_signal_collection()`
- **When**: 7:30 AM PT (at SO cutoff time)
- **Content**:
  - Total signals collected (can be 0)
  - Total symbols scanned
  - Mode (DEMO/LIVE)
  - Signal details (symbol, rank, priority score, confidence, VWAP distance, RS vs SPY, ORB volume, RSI)
  - 0DTE Strategy section:
    - SPX/QQQ/SPY ORB data
    - Qualified 0DTE signals count
    - 0DTE signals list (with Hard Gate status)
    - Hard Gated symbols (if any)
  - 0DTE symbol list from `0dte_list.csv`
- **Flag**: `_so_collection_alert_sent_today = True`

#### **Step 6: Alert - No SO Signals**
- **Alert Method**: `send_orb_no_signals_alert()`
- **When**: 0 signals found during SO collection
- **Content**:
  - Signal type (SO)
  - Total scanned
  - Filtered count
  - System operational confirmation

#### **Step 7: Signal Persistence**
- **Time**: Immediately after signal collection
- **Action**: `daily_run_tracker.record_signal_collection()`
- **Storage**: GCS `priority_optimizer/daily_signals/YYYY-MM-DD_signals.json`
- **Data Saved**:
  - All signals (with priority ranking data)
  - Collection timestamp
  - Total scanned
  - Mode

---

### **Phase 3: SO Batch Execution (7:30 AM PT / 10:30 AM ET)**

#### **Step 1: SO Execution Time Check**
- **Time**: 7:30 AM PT (exactly at SO cutoff)
- **Action**: Check if `current_pt_time == so_cutoff_time`
- **Trigger**: Batch execution of stored SO signals

#### **Step 2: Red Day Filter Final Check**
- **Time**: 7:30 AM PT (before execution)
- **Action**: Final Red Day evaluation
- **Result**: Block execution if Red Day detected

#### **Step 3: Position Sizing Calculation**
- **Action**: `risk_manager.calculate_position_sizes()`
- **Process**:
  1. Rank-based multipliers (Rank 1 = 3.0x, Rank 2 = 2.5x, etc.)
  2. Capital allocation (default 90% deployment)
  3. Whole share normalization
  4. ADV caps (Slip Guard)
  5. Position size caps (35% max per position)

#### **Step 4: Batch Trade Execution**
- **Action**: `_process_orb_signals()` → `trade_manager.process_signal()`
- **Process**:
  1. Execute up to 15 best trades simultaneously
  2. DEMO Mode: Mock execution
  3. LIVE Mode: E*TRADE order placement with OAuth
  4. Track executed symbols (prevent duplicates)
- **Flag**: `_so_executed_symbols_today` updated

#### **Step 5: Alert - SO Execution Aggregated**
- **Alert Method**: `send_orb_so_execution_aggregated()`
- **When**: After batch execution completes
- **Content**:
  - Executed signals count
  - Executed signals list (symbol, rank, side, shares, price, position value, priority score)
  - Rejected signals count (if any)
  - Rejected signals list (with filter reasons)
  - Capital deployed
  - Capital efficiency
- **Flag**: `_so_alert_sent_today = True`

#### **Step 6: Execution Persistence**
- **Action**: `daily_run_tracker.record_signal_execution()`
- **Storage**: GCS daily markers
- **Data Saved**:
  - Executed signals
  - Rejected signals
  - Execution timestamp

---

### **Phase 4: Opening Range Reversal (ORR) Signals (8:15 AM-12:15 PM PT / 11:15 AM-3:15 PM ET)**

#### **Step 1: ORR Window Opens**
- **Time**: 8:15 AM PT (11:15 AM ET)
- **Window**: 8:15 AM - 12:15 PM PT (4-hour window)
- **Purpose**: Capture V-shaped reversal patterns

#### **Step 2: ORR Signal Scanning**
- **Frequency**: Every 30 seconds
- **Action**: `_scan_orb_batch_signals()`
- **Process**:
  1. Scan for ORR patterns:
     - Price was previously below ORB low
     - Price breaks above ORB high for FIRST TIME
     - V-shaped reversal pattern
  2. Generate ORR signals (LONG only, no SHORT)
  3. Execute immediately (individual execution)

#### **Step 3: Individual ORR Execution**
- **Action**: `_process_orb_signals()` → Individual execution
- **Process**:
  1. Execute ORR signal immediately (not batched)
  2. Position sizing (same as SO)
  3. Track executed symbols

#### **Step 4: Alert - ORR Execution Individual**
- **Alert Method**: `send_orb_orr_execution_alert()`
- **When**: Each ORR signal executed
- **Content**:
  - Symbol
  - Side (LONG)
  - Entry price
  - Shares
  - Position value
  - Reasoning (ORR pattern)

---

### **Phase 5: Position Monitoring (Throughout Trading Day)**

#### **Step 1: Continuous Position Monitoring**
- **Frequency**: Every 30 seconds
- **Action**: `stealth_trailing.update_positions()`
- **Process**:
  1. Check each position's P&L
  2. Update trailing stops
  3. Check breakeven activation
  4. Monitor exit triggers (14 automatic triggers)

#### **Step 2: Breakeven Protection**
- **Activation**: +0.75% profit after 6.4 minutes
- **Action**: Lock +0.2% profit
- **Optimized**: Rev 00196 (from 2.0% and 3.5 min)

#### **Step 3: Trailing Stop**
- **Activation**: +0.7% profit after 6.4 minutes
- **Distance**: Dynamic 1.5-2.5% (based on volatility and profit tiers)
- **Method**: Uses WIDER of volatility/profit-based for maximum protection
- **Optimized**: Rev 00196 (91.1% profit capture vs 75.4% at 0.5%)

#### **Step 4: Portfolio Health Check**
- **Frequency**: Every 15 minutes (8:00 AM - 12:45 PM PT)
- **Action**: `stealth_trailing.check_portfolio_health_for_emergency_exit()`
- **Red Flags**:
  - Win rate <35%
  - Avg P&L <-0.5%
  - Low momentum <40%
  - Weak peaks <0.8%
  - All positions losing (100% losers)
- **Actions**:
  - **EMERGENCY (3+ flags)**: Close ALL positions, send emergency alert
  - **WARNING (2 flags)**: Close weak positions, send warning alert
  - **OK (0-1 flags)**: Continue normal trading

#### **Step 5: Individual Position Exits**
- **Alert Method**: `send_trade_exit_alert()` (individual exits)
- **When**: Each position exits
- **Content**:
  - Symbol
  - Side
  - Exit price
  - P&L ($ and %)
  - Exit reason
  - Holding time

#### **Step 6: Aggregated Exit Alerts**
- **Alert Method**: `send_aggregated_exit_alert()`
- **When**: Batch exits (EOD, emergency, weak day)
- **Content**:
  - Multiple positions closed
  - Total P&L
  - Exit reason (EOD/EMERGENCY/WEAK_DAY)

#### **Step 7: Rapid Exit Alert**
- **Alert Method**: `send_rapid_exit_alert()`
- **When**: Position exits within 2 minutes
- **Content**: Rapid exit notification with P&L

#### **Step 8: Letting Winners Run Alert**
- **Alert Method**: `send_letting_winners_run_aggregated()`
- **When**: Positions held past normal exit time
- **Content**: Positions still open with current P&L

---

### **Phase 6: End of Day Position Close (12:55 PM PT / 3:55 PM ET)**

#### **Step 1: EOD Position Close**
- **Time**: 12:55 PM PT (3:55 PM ET) - 5 minutes before market close
- **Action**: `stealth_trailing.close_all_positions(ExitReason.END_OF_DAY_CLOSE)`
- **Process**:
  1. Close all open positions
  2. Batch close (sends ONE aggregated alert)
  3. Record exit reason: END_OF_DAY_CLOSE

#### **Step 2: Alert - Aggregated EOD Exit**
- **Alert Method**: `send_aggregated_exit_alert()`
- **When**: All positions closed at EOD
- **Content**:
  - All positions closed
  - Total P&L
  - Exit reason: END_OF_DAY_CLOSE
- **Flag**: `_eod_positions_closed_today = True`

---

## 🎯 **0DTE Strategy Trading Session Steps**

### **Phase 1: 0DTE Signal Collection (7:30 AM PT / 10:30 AM ET)**

#### **Step 1: Listen to ORB Signals**
- **Time**: 7:30 AM PT (after SO signal collection)
- **Action**: `dte0_manager.listen_to_orb_signals()`
- **Input**: ORB signals from SO collection
- **Process**:
  1. Filter for 0DTE target symbols (SPX, QQQ, SPY from `0dte_list.csv`)
  2. Map leveraged ETFs to underlying (e.g., TQQQ → QQQ)

#### **Step 2: Convex Eligibility Filter**
- **Action**: `ConvexEligibilityFilter.filter_signals()`
- **Criteria** (All Must Pass):
  1. **ORB Volatility Score** ≥ Top 80th percentile (40% weight)
  2. **ORB Range** ≥ 0.25% of symbol price OR 5-min ATR ≥ threshold
  3. **NOT Red Day** (trading disabled if Red Day)
  4. **ORB Break**: Long requires price > ORB High, Short requires price < ORB Low
  5. **Volume** > ORB volume average
  6. **VWAP Condition**: Long requires Price ≥ VWAP, Short requires Price ≤ VWAP
  7. **Early momentum** confirmation
  8. **Market regime** = impulse/trend (NOT rotation)
- **Eligibility Score**: 0.0-1.0 (normalized)
- **Minimum Score**: 0.75 (75%) to qualify

#### **Step 3: 0DTE Signal Generation**
- **Action**: Generate `DTE0Signal` objects
- **Process**:
  1. Determine direction (LONG → CALL, SHORT → PUT)
  2. Calculate target delta (0.30-0.45 for long leg)
  3. Determine spread width ($1 or $2)
  4. Determine spread type (debit/credit/lotto)
  5. Calculate priority score
  6. Assign priority rank

#### **Step 4: Hard Gate Validation**
- **Action**: `dte0_manager.validate_hard_gate()`
- **Checks**:
  - Max spread % (5% max)
  - Volume multiplier (≥1.0x average)
  - Time-based gates
  - Market conditions
- **Result**: Pass/Fail with reason

#### **Step 5: Alert - Options Signal Collection**
- **Alert Method**: `send_options_signal_collection_alert()`
- **When**: After 0DTE signal processing
- **Content**:
  - ORB signals received count
  - Qualified 0DTE signals count
  - 0DTE signals list (symbol, direction, option type, eligibility score, delta, spread width, Hard Gate status)
  - Hard Gated symbols (if any)

---

### **Phase 2: 0DTE Options Execution (7:30 AM PT / 10:30 AM ET)**

#### **Step 1: Priority Ranking**
- **Action**: `dte0_manager._rank_signals_by_priority()`
- **Process**:
  1. Calculate priority score for each signal
  2. Sort by priority (highest first)
  3. Assign priority rank (1 = highest)

#### **Step 2: Position Sizing**
- **Action**: `dte0_manager.calculate_position_sizing()`
- **Process**:
  1. Rank-based capital allocation
  2. Max positions (default: 5)
  3. Max position cost (default: $500)
  4. Capital deployment (default: 90%)

#### **Step 3: Preflight Checks**
- **Action**: Validate signal before execution
- **Checks**:
  - Direction valid (LONG/SHORT)
  - Hard Gate passed
  - Max positions not exceeded
  - Capital available

#### **Step 4: Options Trade Execution**
- **Action**: `dte0_manager._execute_0dte_options_trades()`
- **Process**:
  1. Select strikes based on target delta
  2. Determine spread type (debit/credit/lotto)
  3. Calculate position cost
  4. Execute options order
  5. DEMO Mode: Mock execution
  6. LIVE Mode: E*TRADE options order (if integrated)

#### **Step 5: Alert - Options Execution**
- **Alert Method**: `send_options_execution_alert()`
- **When**: After options execution
- **Content**:
  - Executed positions count
  - Executed positions list (symbol, direction, option type, strikes, delta, spread width, cost, priority rank, Hard Gate status)
  - Rejected signals count
  - Rejected signals list (with reasons)
  - Hard Gated symbols summary
  - Capital deployed

---

### **Phase 3: 0DTE Position Monitoring (Throughout Day)**

#### **Step 1: Options Position Monitoring**
- **Frequency**: Every 30 seconds
- **Action**: `options_executor.update_positions()`
- **Process**:
  1. Check position P&L
  2. Monitor profit targets
  3. Check hard stops
  4. Check time stops
  5. Monitor partial profit exits

#### **Step 2: Partial Profit Alert**
- **Alert Method**: `send_options_partial_profit_alert()`
- **When**: Partial profit taken (50% of max profit)
- **Content**: Partial profit notification

#### **Step 3: Runner Exit Alert**
- **Alert Method**: `send_options_runner_exit_alert()`
- **When**: Runner leg closed (keeping long leg)
- **Content**: Runner exit notification

#### **Step 4: Options Position Exit**
- **Alert Method**: `send_options_position_exit_alert()`
- **When**: Individual options position exits
- **Content**:
  - Symbol
  - Option type
  - Exit price
  - P&L
  - Exit reason
  - Holding time

#### **Step 5: Options Aggregated Exit**
- **Alert Method**: `send_options_aggregated_exit_alert()`
- **When**: Batch options exits
- **Content**: Multiple positions closed

#### **Step 6: Options Health Check**
- **Alert Method**: `send_options_health_check_alert()`
- **When**: Options position health check
- **Content**: Health status and recommendations

---

## 📊 **End of Day (EOD) Process**

### **Phase 1: EOD Position Close (12:55 PM PT / 3:55 PM ET)**

#### **Step 1: Close All Positions**
- **Time**: 12:55 PM PT (5 minutes before market close)
- **Action**: Close all ORB Strategy positions
- **Alert**: Aggregated exit alert sent

#### **Step 2: Close All Options Positions**
- **Time**: 12:55 PM PT
- **Action**: Close all 0DTE Strategy positions
- **Alert**: Options aggregated exit alert sent

---

### **Phase 2: EOD Report Generation (1:00 PM PT / 4:00 PM ET)**

#### **Step 1: EOD Report Trigger**
- **Time**: 1:00 PM PT (4:00 PM ET) - Market close
- **Trigger**: Cloud Scheduler (`/eod/trigger` endpoint) OR internal scheduler
- **Checks**:
  - Weekend check (skip if Saturday/Sunday)
  - Holiday check (skip if holiday)

#### **Step 2: Exit Monitoring Data Flush**
- **Action**: `exit_monitor.flush_all()`
- **Purpose**: Save exit monitoring data to GCS for analysis

#### **Step 3: Demo Mode EOD Report**
- **Alert Method**: `_send_demo_eod_summary()`
- **When**: DEMO Mode active
- **Content**:
  - Daily P&L ($ and %)
  - Total trades
  - Win rate
  - Winning trades count
  - Losing trades count
  - Best trade
  - Worst trade
  - Active positions (if any)
  - Capital deployed
  - Daily return %

#### **Step 4: Live Mode EOD Report**
- **Alert Method**: `_send_live_eod_summary()`
- **When**: LIVE Mode active
- **Content**:
  - Daily P&L ($ and %)
  - Total trades
  - Win rate
  - Account balance
  - Daily return %
  - GCS-based deduplication (one report per day)

#### **Step 5: Options EOD Report**
- **Alert Method**: `send_options_end_of_day_report()`
- **When**: 0DTE Strategy active
- **Content**:
  - Daily stats (positions closed, wins, losses, P&L)
  - Weekly stats
  - All-time stats (if available)
  - Account balance
  - Starting balance
  - Mode (DEMO/LIVE)
- **Flag**: `_eod_report_sent_today = True`

---

## 📱 **Complete Alert List**

### **OAuth & Token Management Alerts**

1. **`send_oauth_market_open_alert()`**
   - **When**: 5:30 AM PT (Good Morning)
   - **Content**: System status, OAuth status, market countdown

2. **`send_oauth_renewal_success()`**
   - **When**: OAuth tokens successfully renewed
   - **Content**: Renewal confirmation, environment, status

3. **`send_oauth_renewal_error()`**
   - **When**: OAuth token renewal fails
   - **Content**: Error message, environment, manual intervention required

4. **`send_oauth_warning()`**
   - **When**: OAuth not authenticated
   - **Content**: Warning message, manual intervention required

5. **`send_oauth_token_renewed_confirmation()`**
   - **When**: Token renewal webhook received
   - **Content**: Confirmation message

---

### **ORB Strategy Alerts**

6. **`send_orb_capture_complete_alert()`**
   - **When**: ORB capture successful (6:45 AM PT)
   - **Content**: Symbols captured, capture time, sample ranges, 0DTE ORB data

7. **`send_orb_capture_failed_alert()`**
   - **When**: ORB capture fails
   - **Content**: Failure reason, retry information

8. **`send_so_signal_collection()`**
   - **When**: SO signal collection complete (7:30 AM PT)
   - **Content**: Signals collected, ranking, 0DTE signals, Hard Gate status

9. **`send_orb_no_signals_alert()`**
   - **When**: 0 signals found during collection
   - **Content**: Total scanned, filtered count, system operational

10. **`send_orb_so_execution_aggregated()`**
    - **When**: SO batch execution complete (7:30 AM PT)
    - **Content**: Executed signals, rejected signals, capital deployed

11. **`send_orb_orr_execution_alert()`**
    - **When**: Individual ORR signal executed
    - **Content**: Symbol, entry, position details, reasoning

12. **`send_trade_exit_alert()`**
    - **When**: Individual position exits
    - **Content**: Symbol, exit price, P&L, exit reason, holding time

13. **`send_aggregated_exit_alert()`**
    - **When**: Batch exits (EOD, emergency, weak day)
    - **Content**: Multiple positions, total P&L, exit reason

14. **`send_rapid_exit_alert()`**
    - **When**: Position exits within 2 minutes
    - **Content**: Rapid exit notification

15. **`send_letting_winners_run_aggregated()`**
    - **When**: Positions held past normal exit
    - **Content**: Open positions with current P&L

---

### **0DTE Strategy Alerts**

16. **`send_0dte_orb_capture_alert()`**
    - **When**: 0DTE ORB data extracted (6:45 AM PT)
    - **Content**: SPX/QQQ/SPY ORB data

17. **`send_options_signal_collection_alert()`**
    - **When**: 0DTE signals processed (7:30 AM PT)
    - **Content**: Qualified signals, eligibility scores, Hard Gate status

18. **`send_options_execution_alert()`**
    - **When**: Options trades executed (7:30 AM PT)
    - **Content**: Executed positions, rejected signals, Hard Gated symbols

19. **`send_options_position_exit_alert()`**
    - **When**: Individual options position exits
    - **Content**: Symbol, option type, exit price, P&L, exit reason

20. **`send_options_aggregated_exit_alert()`**
    - **When**: Batch options exits
    - **Content**: Multiple positions closed

21. **`send_options_partial_profit_alert()`**
    - **When**: Partial profit taken (50% of max)
    - **Content**: Partial profit notification

22. **`send_options_runner_exit_alert()`**
    - **When**: Runner leg closed
    - **Content**: Runner exit notification

23. **`send_options_health_check_alert()`**
    - **When**: Options health check
    - **Content**: Health status, recommendations

---

### **End of Day Alerts**

24. **`_send_demo_eod_summary()`**
    - **When**: EOD report (1:00 PM PT) - DEMO Mode
    - **Content**: Daily performance, trades, P&L, win rate

25. **`_send_live_eod_summary()`**
    - **When**: EOD report (1:00 PM PT) - LIVE Mode
    - **Content**: Daily performance, account balance, trades, P&L

26. **`send_options_end_of_day_report()`**
    - **When**: EOD report (1:00 PM PT) - 0DTE Strategy
    - **Content**: Daily/weekly/all-time stats, account balance

---

### **System & Error Alerts**

27. **`send_holiday_alert()`**
    - **When**: Holiday detected
    - **Content**: Holiday name, skip reason, trading disabled

28. **`send_telegram_alert()`**
    - **When**: General system alerts (Red Day, emergency, warnings)
    - **Content**: Custom message, alert level

29. **`send_error_alert()`**
    - **When**: System errors occur
    - **Content**: Error message, error type

30. **`send_warning_alert()`**
    - **When**: System warnings occur
    - **Content**: Warning message, warning type

---

## 📅 **Complete Daily Timeline**

| Time (PT) | Time (ET) | Phase | Action | Alert |
|-----------|-----------|-------|--------|-------|
| 5:30 AM | 8:30 AM | Pre-Market | Good Morning Alert | `send_oauth_market_open_alert()` |
| 6:00 AM | 9:00 AM | Pre-Market | ADV Data Refresh | None |
| 6:30 AM | 9:30 AM | ORB Capture | ORB Window Opens | None |
| 6:45 AM | 9:45 AM | ORB Capture | ORB Capture Complete | `send_orb_capture_complete_alert()` |
| 7:15 AM | 10:15 AM | SO Collection | SO Window Opens, Pre-fetch Candle | None |
| 7:15-7:30 AM | 10:15-10:30 AM | SO Collection | Continuous Signal Scanning (every 30s) | None |
| 7:30 AM | 10:30 AM | SO Collection | Signal Collection Alert | `send_so_signal_collection()` |
| 7:30 AM | 10:30 AM | SO Execution | Batch Execution | `send_orb_so_execution_aggregated()` |
| 7:30 AM | 10:30 AM | 0DTE Collection | 0DTE Signal Processing | `send_options_signal_collection_alert()` |
| 7:30 AM | 10:30 AM | 0DTE Execution | Options Execution | `send_options_execution_alert()` |
| 8:00 AM-12:45 PM | 11:00 AM-3:45 PM | Monitoring | Portfolio Health Check (every 15 min) | Emergency/Warning alerts if needed |
| 8:15 AM-12:15 PM | 11:15 AM-3:15 PM | ORR Collection | ORR Signal Scanning (every 30s) | `send_orb_orr_execution_alert()` (per signal) |
| Throughout Day | Throughout Day | Monitoring | Position Monitoring (every 30s) | `send_trade_exit_alert()` (per exit) |
| 12:55 PM | 3:55 PM | EOD Close | Close All Positions | `send_aggregated_exit_alert()` |
| 1:00 PM | 4:00 PM | EOD Report | EOD Report Generation | `_send_demo_eod_summary()` / `_send_live_eod_summary()` / `send_options_end_of_day_report()` |

---

## 🔄 **Data Collection Points**

### **Priority Optimizer Data Collection**

1. **Signal Collection** (7:30 AM PT)
   - **Storage**: `priority_optimizer/daily_signals/YYYY-MM-DD_signals.json`
   - **Data**: All signals with priority ranking data

2. **Comprehensive 89-Point Data** (7:30 AM-4:00 PM ET)
   - **Script**: `collect_daily_89points.py`
   - **Storage**: `priority_optimizer/comprehensive_data/YYYY-MM-DD_comprehensive_data.json`
   - **Data**: 89 data points per symbol (including priority score, formula factors)

3. **Trade Execution Data** (Throughout day)
   - **Storage**: GCS trade history
   - **Data**: Entry, exit, P&L, performance metrics

---

## 📝 **Notes**

- **All times in Pacific Time (PT)** unless otherwise specified
- **ET = Eastern Time**
- **UTC times** used for GCS storage and markers
- **Alerts sent via Telegram** (configured in `configs/base.env`)
- **Priority Ranking Formula v2.1** (Rev 00106, Nov 6, 2025) currently deployed
- **Red Day Filter** can block trading if patterns detected
- **Portfolio Health Check** runs every 15 minutes during trading hours
- **EOD reports** sent only on trading days (Mon-Fri, non-holidays)

---

**Last Updated**: January 7, 2026  
**Version**: Rev 00231

