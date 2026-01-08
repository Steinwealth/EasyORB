# System Architecture
## Easy ORB Strategy - Complete Architecture Documentation

**Last Updated**: January 7, 2026  
**Version**: Rev 00233 (Performance Improvements & Data Quality Fixes)  
**Purpose**: Comprehensive documentation of the Easy ORB Strategy system architecture, module organization, data flows, and component interactions.

**System**: Easy ORB Strategy (ORB ETF + 0DTE Options Trading)  
**Status**: ✅ Production Ready - Deployed on Google Cloud Run  
**Architecture**: Cloud-native, serverless, scale-to-zero design

---

## 📋 **Table of Contents**

1. [System Overview](#system-overview)
2. [Core Architecture](#core-architecture)
3. [Module Organization](#module-organization)
4. [Data Flow](#data-flow)
5. [Component Interactions](#component-interactions)
6. [Deployment Architecture](#deployment-architecture)
7. [Integration Points](#integration-points)
8. [Configuration System](#configuration-system)
9. [Data Persistence](#data-persistence)
10. [Security Architecture](#security-architecture)

---

## 🎯 **System Overview**

The Easy ORB Strategy is a fully automated trading system implementing Opening Range Breakout (ORB) strategy for ETF trading and Zero Days To Expiration (0DTE) options trading. The system operates 24/7 on Google Cloud Platform with intelligent scaling, comprehensive risk management, and real-time position monitoring.

### **Key Characteristics**

- **Strategy**: ORB (Opening Range Breakout) for ETFs + 0DTE Options
- **Execution Modes**: Demo (simulated) and Live (E*TRADE API)
- **Deployment**: Google Cloud Run (serverless, scale-to-zero)
- **Data Sources**: E*TRADE API (primary), yfinance (fallback)
- **Alerting**: Telegram notifications (24/7)
- **Persistence**: Google Cloud Storage (GCS)
- **Configuration**: Unified configuration system (65+ settings)

### **Trading Flow**

```
Pre-Market → ORB Capture → Signal Collection → Execution → Monitoring → Exit → EOD Report
```

---

## 🏗️ **Core Architecture**

### **High-Level Architecture**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Easy ORB Strategy System                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Prime Trading System (Orchestrator)             │  │
│  │  - Coordinates all components                           │  │
│  │  - Manages trading lifecycle                           │  │
│  │  - Handles system state                                │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           │                                      │
│        ┌──────────────────┼──────────────────┐                  │
│        │                  │                  │                  │
│  ┌─────▼─────┐    ┌───────▼──────┐   ┌──────▼──────┐          │
│  │   Data    │    │   Strategy   │   │   Risk     │          │
│  │  Manager  │    │   Manager    │   │  Manager   │          │
│  └───────────┘    └──────────────┘   └─────────────┘          │
│        │                  │                  │                  │
│        └──────────────────┼──────────────────┘                  │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Execution Layer                             │  │
│  │  - Mock Executor (Demo)                                  │  │
│  │  - E*TRADE Executor (Live)                              │  │
│  │  - 0DTE Options Executor                                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Position Monitoring Layer                      │  │
│  │  - Stealth Trailing (Exit Management)                  │  │
│  │  - Health Monitor (Portfolio Health)                    │  │
│  │  - Exit Monitoring (Data Collection)                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           │                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Alert & Persistence Layer                   │  │
│  │  - Alert Manager (Telegram)                              │  │
│  │  - Daily Run Tracker (GCS)                               │  │
│  │  - GCS Persistence (Trade History)                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### **Component Hierarchy**

```
main.py (Entry Point)
  └── Prime Trading System
       ├── Prime Data Manager (Market Data)
       ├── Prime Market Manager (Market Hours)
       ├── Prime ORB Strategy Manager (Signal Generation)
       ├── Prime Risk Manager (Position Sizing)
       ├── Prime Unified Trade Manager (Trade Coordination)
       ├── Mock Trading Executor (Demo Mode)
       ├── Prime ETrade Trading (Live Mode)
       ├── Prime Stealth Trailing (Exit Management)
       ├── Prime Health Monitor (Portfolio Health)
       ├── Prime Alert Manager (Notifications)
       ├── Daily Run Tracker (Persistence)
       └── 0DTE Strategy Manager (Options Trading)
```

---

## 📦 **Module Organization**

### **Core Modules** (`modules/`)

#### **1. System Core**

**`prime_trading_system.py`** ⭐ **ORCHESTRATOR**
- **Purpose**: Main trading system orchestrator
- **Responsibilities**:
  - Coordinates all components
  - Manages trading lifecycle
  - Handles system state
  - Parallel processing management
  - Memory management
- **Key Classes**: `PrimeTradingSystem`, `ParallelProcessingManager`, `MemoryManager`

**`prime_models.py`** ⭐ **DATA STRUCTURES**
- **Purpose**: Unified data models for all components
- **Key Models**:
  - `PrimeSignal`: Trading signals
  - `PrimePosition`: Open positions
  - `PrimeTrade`: Completed trades
  - `PrimeStopOrder`: Stop loss orders
  - Enums: `StrategyMode`, `SignalType`, `TradeStatus`, `StopType`
- **Usage**: Used throughout system for type safety and consistency

**`config_loader.py`** ⭐ **CONFIGURATION**
- **Purpose**: Unified configuration system
- **Features**:
  - Loads from `configs/` directory
  - Environment variable support
  - 65+ configurable settings
  - Single source of truth
- **Key Classes**: `ConfigLoader`

#### **2. Data Management**

**`prime_data_manager.py`** ⭐ **DATA FETCHING**
- **Purpose**: Market data retrieval and caching
- **Features**:
  - E*TRADE API integration (primary)
  - yfinance fallback
  - Batch quote processing (25 symbols/call)
  - Multi-tier caching (L1: memory, L2: file, L3: GCS)
  - Circuit breaker protection
- **Key Methods**: `get_batch_quotes()`, `get_technical_indicators()`

**`prime_market_manager.py`** ⭐ **MARKET HOURS**
- **Purpose**: Market hours and timezone management
- **Features**:
  - Timezone-aware market hours (PT/ET)
  - Holiday detection
  - Market session tracking
  - Pre-market/post-market detection
- **Key Classes**: `PrimeMarketManager`, `MarketSession`

**`daily_run_tracker.py`** ⭐ **PERSISTENCE**
- **Purpose**: Daily run tracking and signal persistence
- **Features**:
  - Signal sanitization before GCS save
  - Daily marker generation
  - GCS persistence
  - 50-day cleanup
- **Key Methods**: `save_signals()`, `get_daily_marker()`

#### **3. Strategy Management**

**`prime_orb_strategy_manager.py`** ⭐ **ORB STRATEGY**
- **Purpose**: Opening Range Breakout signal generation
- **Features**:
  - ORB capture (6:30-6:45 AM PT)
  - SO signal generation (7:15-7:30 AM PT)
  - Signal validation (3 strict rules)
  - Multi-factor ranking (VWAP 27%, RS vs SPY 25%, ORB Vol 22%)
  - Red Day detection (portfolio-level)
  - Signal-level filtering (Rev 00233)
- **Key Classes**: `PrimeORBStrategyManager`, `ORBData`
- **Key Methods**: `capture_orb_data()`, `generate_so_signals()`

**`easy0DTE/modules/dte0_manager.py`** ⭐ **0DTE STRATEGY**
- **Purpose**: Zero Days To Expiration options trading
- **Features**:
  - ORB capture for options symbols
  - Convex eligibility filtering
  - Options signal generation
  - Debit spreads, lotto sleeves, credit spreads
- **Integration**: Receives ORB signals, filters via Convex Eligibility Filter

**`easy0DTE/modules/convex_eligibility_filter.py`** ⭐ **OPTIONS FILTER**
- **Purpose**: Filters ORB signals for 0DTE options eligibility
- **Features**:
  - Volatility assessment
  - ORB range analysis
  - Red Day detection (uses `is_red_day` flag)
  - Momentum evaluation
  - Market regime detection
- **Key Classes**: `ConvexEligibilityFilter`, `EligibilityResult`
- **Enhanced Logging**: Rev 00233 - Detailed rejection reasons

#### **4. Risk Management**

**`prime_risk_manager.py`** ⭐ **POSITION SIZING**
- **Purpose**: Position sizing and capital allocation
- **Features**:
  - Rank-based multipliers (3.0x, 2.5x, 2.0x...)
  - Greedy capital packing
  - Adaptive fair share
  - Slip Guard (ADV-based capping)
  - Post-rounding redistribution
  - 6-step batch sizing flow
- **Key Classes**: `PrimeRiskManager`
- **Key Methods**: `calculate_batch_position_sizes()`

**`prime_enhanced_red_day_detector.py`** ⭐ **RED DAY DETECTION**
- **Purpose**: Pre-execution loss prevention
- **Features**:
  - Portfolio-level detection (3 patterns)
  - Signal-level detection (Rev 00233)
  - 3-Tier Override System
  - Data quality validation (Rev 00233)
  - Fail-safe mode consistency (Rev 00233)
- **Patterns**:
  1. Oversold + Weak Volume
  2. Overbought + Weak Volume
  3. Weak Volume Alone
- **Key Classes**: `PrimeEnhancedRedDayDetector`

**`prime_stealth_trailing_tp.py`** ⭐ **EXIT MANAGEMENT**
- **Purpose**: Position monitoring and exit triggers
- **Features**:
  - 14 exit triggers
  - Breakeven stops (0.75% @ 6.4 min)
  - Trailing stops (0.7% @ 6.4 min, 1.5-2.5% distance)
  - Permanent floor stops (entry bar protection)
  - 30-second monitoring frequency
- **Key Classes**: `PrimeStealthTrailingTP`
- **Key Methods**: `update_positions()`, `check_exit_triggers()`

**`prime_health_monitor.py`** ⭐ **PORTFOLIO HEALTH**
- **Purpose**: Portfolio-level health monitoring
- **Features**:
  - 15-minute health checks
  - Emergency exit detection (3+ red flags)
  - Weak day detection (2 red flags)
  - Red flag tracking (win rate, P&L, momentum, peaks)
- **Key Classes**: `PrimeHealthMonitor`

#### **5. Execution**

**`mock_trading_executor.py`** ⭐ **DEMO MODE**
- **Purpose**: Simulated trade execution
- **Features**:
  - Mock position creation
  - P&L tracking
  - Account balance management
  - GCS persistence
  - Shortened Trade IDs (Rev 00232)
- **Key Classes**: `MockTradingExecutor`
- **Key Methods**: `execute_trade()`, `close_position()`

**`prime_etrade_trading.py`** ⭐ **LIVE MODE**
- **Purpose**: Live E*TRADE API execution
- **Features**:
  - Real order placement
  - Order status tracking
  - Position management
  - Account balance retrieval
- **Key Classes**: `PrimeETradeTrading`
- **Integration**: Uses `etrade_oauth_integration.py` for authentication

**`easy0DTE/modules/mock_options_executor.py`** ⭐ **DEMO OPTIONS**
- **Purpose**: Simulated options execution
- **Features**:
  - Debit spreads
  - Lotto sleeves
  - Credit spreads
  - Shortened Position IDs (Rev 00232)
- **Key Classes**: `MockOptionsExecutor`

**`easy0DTE/modules/options_trading_executor.py`** ⭐ **LIVE OPTIONS**
- **Purpose**: Live options execution via E*TRADE API
- **Features**:
  - Real options order placement
  - Position management
  - Shortened Position IDs (Rev 00232)

#### **6. Alerting & Monitoring**

**`prime_alert_manager.py`** ⭐ **NOTIFICATIONS**
- **Purpose**: Telegram alert system
- **Features**:
  - All trading alerts
  - Enhanced formatting (Rev 00231 - bold key metrics)
  - Alert deduplication
  - Error handling
  - 24/7 operation
- **Key Classes**: `PrimeAlertManager`
- **Alert Types**: Morning, ORB Capture, Signal Collection, Execution, Exits, EOD Report

**`prime_exit_monitoring_collector.py`** ⭐ **DATA COLLECTION**
- **Purpose**: Exit monitoring data collection
- **Features**:
  - 89-point data collection
  - Technical indicators
  - Trade execution data
  - Performance metrics
- **Integration**: Used by Priority Optimizer

#### **7. OAuth Integration**

**`etrade_oauth_integration.py`** ⭐ **AUTHENTICATION**
- **Purpose**: E*TRADE OAuth token management
- **Features**:
  - Token retrieval from Secret Manager
  - Token validity checking
  - Request signing (OAuth 1.0a)
- **Integration**: Used by `prime_etrade_trading.py`

**`ETradeOAuth/`** ⭐ **OAUTH WEB APP**
- **Purpose**: OAuth token renewal web interface
- **Components**:
  - Frontend: Firebase Hosting (`login/public/`)
  - Backend: Cloud Run (`login/oauth_backend.py`)
  - Keepalive: Cloud Scheduler jobs
- **URL**: https://easy-trading-oauth-v2.web.app

#### **8. Supporting Modules**

**`gcs_persistence.py`** ⭐ **STORAGE**
- **Purpose**: Google Cloud Storage integration
- **Features**:
  - Trade history persistence
  - Account balance persistence
  - Signal storage
  - State management

**`prime_unified_trade_manager.py`** ⭐ **TRADE COORDINATION**
- **Purpose**: Unified trade management
- **Features**:
  - Trade lifecycle management
  - Position tracking
  - Trade coordination between strategies

**`prime_symbol_score.py`** ⭐ **SCORING**
- **Purpose**: Symbol performance scoring
- **Features**:
  - Performance tracking
  - Score calculation
  - Historical analysis

**`dynamic_holiday_calculator.py`** ⭐ **HOLIDAYS**
- **Purpose**: Market holiday detection
- **Features**:
  - 19 high-risk days per year
  - Bank holidays
  - Low-volume holidays
- **Integration**: Used by `prime_market_manager.py`

---

## 🔄 **Data Flow**

### **Complete Trading Flow**

```
1. System Startup
   ├── Load Configuration (config_loader.py)
   ├── Initialize Components (prime_trading_system.py)
   └── Load Symbol List (core_list.csv)

2. Pre-Market (5:00-6:30 AM PT)
   ├── OAuth Token Check (etrade_oauth_integration.py)
   ├── Holiday Check (dynamic_holiday_calculator.py)
   └── Morning Alert (prime_alert_manager.py)

3. ORB Capture (6:30-6:45 AM PT)
   ├── Fetch Opening Range (prime_data_manager.py)
   ├── Store ORB Data (prime_orb_strategy_manager.py)
   └── ORB Capture Alert (prime_alert_manager.py)

4. Signal Collection (7:15-7:30 AM PT)
   ├── Prefetch Candle Data (prime_data_manager.py)
   ├── Scan Symbols (prime_orb_strategy_manager.py)
   ├── Validate Signals (3 strict rules)
   ├── Red Day Detection (prime_enhanced_red_day_detector.py)
   │   ├── Portfolio-Level Check
   │   └── Signal-Level Filter (Rev 00233)
   ├── Multi-Factor Ranking (VWAP 27%, RS vs SPY 25%, ORB Vol 22%)
   └── Signal Collection Alert (prime_alert_manager.py)

5. Execution (7:30 AM PT)
   ├── Position Sizing (prime_risk_manager.py)
   │   ├── Rank Multipliers
   │   ├── ADV Capping (Slip Guard)
   │   ├── Normalization
   │   └── Redistribution
   ├── Execute Trades
   │   ├── ORB: Mock Executor (demo) / E*TRADE (live)
   │   └── 0DTE: Mock Options Executor (demo) / Options Executor (live)
   └── Execution Alert (prime_alert_manager.py)

6. Position Monitoring (7:30 AM - 12:55 PM PT)
   ├── Update Positions (every 30 seconds)
   │   ├── Price Updates (prime_data_manager.py)
   │   ├── Exit Checks (prime_stealth_trailing_tp.py)
   │   └── Stop Updates (breakeven, trailing, floor stops)
   ├── Health Checks (every 15 minutes)
   │   └── Portfolio Health (prime_health_monitor.py)
   └── Exit Alerts (prime_alert_manager.py)

7. End of Day (12:55 PM PT)
   ├── Close All Positions
   ├── EOD Close Alert (prime_alert_manager.py)
   ├── Save Trade History (gcs_persistence.py)
   └── EOD Report (prime_alert_manager.py)
```

### **Data Flow Diagram**

```
Symbol List (core_list.csv)
    ↓
Prime Data Manager (Fetch Market Data)
    ↓
Prime ORB Strategy Manager (Generate Signals)
    ↓
Prime Enhanced Red Day Detector (Filter Red Days)
    ↓
Prime Risk Manager (Calculate Position Sizes)
    ↓
Execution Layer (Mock/E*TRADE)
    ↓
Prime Stealth Trailing (Monitor & Exit)
    ↓
Prime Alert Manager (Send Notifications)
    ↓
GCS Persistence (Save Trade History)
```

---

## 🔗 **Component Interactions**

### **Key Interactions**

#### **1. Signal Generation Flow**

```
Prime ORB Strategy Manager
    ├── Uses: Prime Data Manager (market data)
    ├── Uses: Prime Market Manager (market hours)
    ├── Generates: PrimeSignal objects
    └── Sends to: Prime Trading System
```

#### **2. Risk Management Flow**

```
Prime Risk Manager
    ├── Receives: PrimeSignal objects (from ORB Manager)
    ├── Uses: ADV Data Manager (for Slip Guard)
    ├── Calculates: Position sizes
    └── Returns: Sized signals to Prime Trading System
```

#### **3. Execution Flow**

```
Prime Trading System
    ├── Receives: Sized signals (from Risk Manager)
    ├── Routes to: Mock Executor (demo) or E*TRADE Executor (live)
    ├── Creates: PrimePosition objects
    └── Sends to: Prime Stealth Trailing (monitoring)
```

#### **4. Monitoring Flow**

```
Prime Stealth Trailing
    ├── Receives: PrimePosition objects
    ├── Uses: Prime Data Manager (price updates)
    ├── Checks: Exit triggers (14 triggers)
    ├── Updates: Stop losses (breakeven, trailing, floor)
    └── Sends: Exit signals to Prime Alert Manager
```

#### **5. 0DTE Integration Flow**

```
ORB Signals (from Prime ORB Strategy Manager)
    ↓
Convex Eligibility Filter
    ├── Checks: Volatility, ORB range, Red Day flag
    ├── Evaluates: Momentum, market regime
    └── Filters: Eligible signals
    ↓
0DTE Manager (dte0_manager.py)
    ├── Generates: Options signals
    └── Routes to: Mock Options Executor / Options Executor
```

---

## ☁️ **Deployment Architecture**

### **Cloud Architecture**

```
┌─────────────────────────────────────────────────────────────┐
│                    Google Cloud Platform                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Cloud Run (Trading Service)                 │  │
│  │  Service: easy-etrade-strategy                      │  │
│  │  Revision: easy-etrade-strategy-00200-nqd            │  │
│  │  Resources: 2 vCPU, 2Gi Memory                      │  │
│  │  Scaling: Scale-to-zero (cost optimized)             │  │
│  │                                                       │  │
│  │  Components:                                          │  │
│  │  ├── Prime Trading System                            │  │
│  │  ├── Prime ORB Strategy Manager                      │  │
│  │  ├── 0DTE Strategy Manager                           │  │
│  │  ├── Mock Trading Executor                           │  │
│  │  └── All Core Modules                                │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Cloud Run (OAuth Service)                    │  │
│  │  Service: easy-etrade-strategy-oauth                 │  │
│  │  Resources: 1 vCPU, 512Mi Memory                     │  │
│  │  Scaling: Scale-to-zero                              │  │
│  │                                                       │  │
│  │  Components:                                          │  │
│  │  ├── OAuth Backend (FastAPI)                         │  │
│  │  ├── Token Keepalive                                 │  │
│  │  └── Token Refresh                                   │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Firebase Hosting (Frontend)                 │  │
│  │  URL: https://easy-trading-oauth-v2.web.app          │  │
│  │                                                       │  │
│  │  Components:                                          │  │
│  │  ├── Public Dashboard (index.html)                  │  │
│  │  └── Management Portal (manage.html)                 │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Cloud Storage (GCS)                          │  │
│  │                                                       │  │
│  │  Buckets:                                            │  │
│  │  ├── easy-etrade-strategy-trades/                    │  │
│  │  │   └── Trade history                               │  │
│  │  ├── easy-etrade-strategy-state/                     │  │
│  │  │   └── System state                                │  │
│  │  └── easy-etrade-strategy-logs/                      │  │
│  │      └── Performance logs                            │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Secret Manager                               │  │
│  │                                                       │  │
│  │  Secrets:                                            │  │
│  │  ├── ETRADE API Keys                                 │  │
│  │  ├── OAuth Tokens                                    │  │
│  │  └── Telegram Credentials                            │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │         Cloud Scheduler                               │  │
│  │                                                       │  │
│  │  Jobs:                                                │  │
│  │  ├── Trading Hours Keep-Alive (every 3-5 min)        │  │
│  │  ├── OAuth Keepalive (hourly)                        │  │
│  │  └── EOD Reports (daily 4:00 PM ET)                  │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### **Deployment Details**

- **Platform**: Google Cloud Run (serverless containers)
- **Scaling**: Scale-to-zero (cost optimized)
- **Cold Start**: ~10-30 seconds (when Cloud Scheduler wakes system)
- **Cost**: ~$17.75-22.25/month (86-88% cost reduction)
- **Region**: us-central1
- **Project**: easy-etrade-strategy (ID: 223967598315)

---

## 🔌 **Integration Points**

### **External Integrations**

#### **1. E*TRADE API**
- **Purpose**: Market data and trade execution
- **Integration**: `prime_data_manager.py`, `prime_etrade_trading.py`
- **Authentication**: OAuth 1.0a via `etrade_oauth_integration.py`
- **Rate Limiting**: 100ms between calls, batch processing (25 symbols/call)

#### **2. yfinance (Fallback)**
- **Purpose**: Backup data source when E*TRADE unavailable
- **Integration**: `prime_data_manager.py`
- **Usage**: Automatic fallback, no API key required

#### **3. Telegram API**
- **Purpose**: Alert notifications
- **Integration**: `prime_alert_manager.py`
- **Features**: 24/7 operation, enhanced formatting (Rev 00231)

#### **4. Google Cloud Services**
- **Cloud Storage**: Trade history persistence (`gcs_persistence.py`)
- **Secret Manager**: Credential storage (`etrade_oauth_integration.py`)
- **Cloud Logging**: Application logs (native GCP logging)
- **Cloud Scheduler**: Keep-alive jobs and EOD reports

---

## ⚙️ **Configuration System**

### **Unified Configuration** (Rev 00201)

**Location**: `configs/` directory

**Key Configuration Files**:
- `strategies.env`: Capital allocation (90% SO / 10% Reserve)
- `position-sizing.env`: Position sizing rules
- `risk-management.env`: Exit settings (65+ configurable settings)
- `deployment.env`: Strategy enablement (ORB/0DTE)

**Configuration Loader**: `config_loader.py`
- Loads from `configs/` directory
- Environment variable support
- Single source of truth
- No hardcoded values

**Key Settings**:
- `SO_CAPITAL_PCT`: 90.0 (Standard Order allocation)
- `CASH_RESERVE_PCT`: 10.0 (Cash reserve)
- `MAX_POSITION_SIZE_PCT`: 35.0 (Maximum single position)
- `MAX_CONCURRENT_POSITIONS`: 15 (Maximum simultaneous trades)
- `ENABLE_0DTE_STRATEGY`: true/false (0DTE options enablement)

---

## 💾 **Data Persistence**

### **GCS Persistence** (Rev 00203)

**Trade History**:
- **Location**: `gs://easy-etrade-strategy-trades/`
- **Format**: JSON files (one per day)
- **Persistence**: Immediate on trade close
- **Retention**: 50-day cleanup

**Account Balance**:
- **Location**: `gs://easy-etrade-strategy-state/`
- **Format**: JSON state file
- **Persistence**: After each trade close
- **Retry Logic**: Prevents balance reset on transient failures

**Signals**:
- **Location**: `gs://easy-etrade-strategy-state/signals/`
- **Format**: Sanitized JSON (technical indicators preserved)
- **Persistence**: After signal collection
- **Retention**: 50-day cleanup

**Daily Markers**:
- **Location**: `gs://easy-etrade-strategy-state/markers/`
- **Format**: JSON daily marker
- **Purpose**: Execution data tracking
- **Usage**: Used by Priority Optimizer for data collection

---

## 🔒 **Security Architecture**

### **Authentication & Authorization**

**E*TRADE OAuth**:
- **Protocol**: OAuth 1.0a
- **Storage**: Google Secret Manager
- **Renewal**: Daily via web app (https://easy-trading-oauth-v2.web.app)
- **Keepalive**: Cloud Scheduler jobs (hourly)

**Secret Management**:
- **Storage**: Google Secret Manager
- **Encryption**: At rest (automatic)
- **Access**: Service account with minimal permissions
- **Secrets**: E*TRADE API keys, OAuth tokens, Telegram credentials

### **Network Security**

**Cloud Run Services**:
- **Access**: Public (required for Cloud Scheduler)
- **Protection**: HTTPS only
- **Authentication**: Optional (currently unauthenticated for keep-alive)

**OAuth Web App**:
- **Public Dashboard**: No authentication (information only)
- **Management Portal**: Password-protected (access code: easy2025)
- **Anti-Phishing**: Two-tier architecture (public/private separation)

---

## 📊 **Performance Characteristics**

### **System Performance**

**Data Processing**:
- **ORB Capture**: 2-5 seconds for 145 symbols
- **Signal Scanning**: 1-2 seconds per scan
- **Signal Ranking**: <100ms for 6-15 signals
- **Batch Execution**: 2-3 seconds for up to 15 trades

**Memory Usage**:
- **Baseline**: 400-600MB
- **Peak (during trading)**: 800MB-1.2GB
- **After hours**: 300-500MB

**API Usage**:
- **Daily E*TRADE Calls**: ~1,236 calls/day
- **Batch Size**: 25 symbols per call
- **Rate Limiting**: 100ms between calls

### **Cost Optimization**

**Monthly Costs**: ~$17.75-22.25/month
- **Cloud Run (Trading)**: $11-15/month
- **Cloud Run (OAuth)**: $2-5/month
- **Cloud Storage**: $0.50-1.50/month
- **Cloud Scheduler**: $0.10-0.25/month
- **Secret Manager**: $0.06-0.10/month
- **Cloud Logging**: $1-2/month
- **Firebase Hosting**: $0 (free tier)

**Cost Reduction**: 86-88% (from ~$155/month)

---

## 🎯 **Key Design Principles**

1. **Modularity**: Each component has a single, well-defined responsibility
2. **Scalability**: Dynamic symbol list, no hardcoded limits
3. **Reliability**: Multi-provider fallback, circuit breaker protection
4. **Cost Efficiency**: Scale-to-zero deployment, optimized resource usage
5. **Maintainability**: Unified configuration, comprehensive logging
6. **Type Safety**: Unified data models (`PrimeSignal`, `PrimePosition`, `PrimeTrade`)
7. **Testability**: Clear separation of concerns, mock executors for testing

---

## 📚 **Related Documentation**

- **[README.md](../README.md)**: System overview and features
- **[docs/ProcessFlow.md](ProcessFlow.md)**: End-to-end process flow
- **[docs/Strategy.md](Strategy.md)**: ORB strategy details
- **[docs/Risk.md](Risk.md)**: Risk management and position sizing
- **[docs/Cloud.md](Cloud.md)**: Cloud deployment guide
- **[docs/Data.md](Data.md)**: Data management system
- **[docs/Settings.md](Settings.md)**: Configuration reference

---

*Last Updated: January 7, 2026*  
*Version: Rev 00233 (Performance Improvements & Data Quality Fixes)*  
*Status: ✅ Production Ready*  
*Maintainer: Easy ORB Strategy Development Team*

