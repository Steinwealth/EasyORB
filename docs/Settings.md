# Settings / Configuration

**Last Updated**: January 7, 2026  
**Version**: Rev 00233

## Where configuration lives

- **Primary**: `configs/` (env-style files)
- **Runtime overrides**: environment variables (Cloud Run / shell)
- **Local Development Secrets**: `secretsprivate/` (gitignored) - See Secrets Management section below
- **Production Secrets**: Google Secret Manager (Cloud Run deployments)

## Common toggles

### **Trading Mode**
- **Demo vs Live**
  - `ETRADE_MODE=demo|live` (in `configs/deployment.env`)
  - `DEPLOYMENT_MODE=demo|live` (in `configs/deployment.env`)

### **Strategy Enablement**
- **Enable ORB Strategy**
  - `ENABLE_ORB_STRATEGY=true|false` (in `configs/deployment.env`)
  - Default: `true` (always enabled)
- **Enable 0DTE Strategy**
  - `ENABLE_0DTE_STRATEGY=true|false` (in `configs/deployment.env`)
  - Default: `true` (enabled by default)
  - When enabled, 0DTE Strategy listens to ORB signals and generates options trades

## Watchlists

- **ORB core list**: `data/watchlist/core_list.csv`
  - Currently 145 symbols (fully dynamic)
  - Used for ETF ORB trades
  - Add/remove symbols without code changes
- **0DTE list**: `data/watchlist/0dte_list.csv`
  - Target symbols for 0DTE options trades
  - Default: SPX, QQQ, SPY
  - Configurable via `0DTE_TARGET_SYMBOLS` in `easy0DTE/configs/0dte.env`

## Configuration Files

### **Deployment Configuration** (`configs/deployment.env`)
- `ENABLE_ORB_STRATEGY=true` - Enable ORB Strategy (ETF trades)
- `ENABLE_0DTE_STRATEGY=true` - Enable 0DTE Strategy (options trades)
- `ETRADE_MODE=demo|live` - Trading mode
- `DEPLOYMENT_MODE=demo|live` - Deployment mode

### **ORB Strategy Configuration** (`configs/strategies.env`)
- `SO_CAPITAL_PCT=90.0` - Standard Order capital allocation (90%)
- `ORR_CAPITAL_PCT=0.0` - Opening Range Reversal allocation (disabled)
- `CASH_RESERVE_PCT=10.0` - Cash reserve (auto-calculated)

### **0DTE Strategy Configuration** (`easy0DTE/configs/0dte.env`)
- `ENABLE_0DTE_STRATEGY=true` - Enable 0DTE Strategy
- `0DTE_TARGET_SYMBOLS=SPX,QQQ,SPY` - Target symbols for options
- `0DTE_MAX_POSITIONS=5` - Maximum 0DTE positions
- `0DTE_CONVEX_MIN_SCORE=0.75` - Minimum eligibility score
- `0DTE_DEBIT_SPREAD_TARGET_DELTA_MIN=0.30` - Debit spread delta range
- `0DTE_DEBIT_SPREAD_TARGET_DELTA_MAX=0.45`
- See `easy0DTE/configs/0dte.env` for complete configuration

### **Risk / Sizing** (`configs/risk-management.env`, `configs/position-sizing.env`)

See the env files in `configs/` for:
- Capital allocation (ORB Strategy)
- Max positions (ORB: 15, 0DTE: 5)
- Exit thresholds (breakeven, trailing stops)
- Filters and guardrails (red day filter, holiday filter)
- Position sizing rules (rank multipliers, ADV limits)

## Secrets Management (Rev 00233) 🔒

### **Overview**
The Easy ORB Strategy uses a **two-tier secrets management system**:
- **Production/Deployment**: Google Secret Manager (GCP)
- **Local Development**: `secretsprivate/` folder (gitignored)

**All sensitive credentials are stored securely and never committed to Git.**

### **Local Development Setup**
1. **Create secrets files**:
   ```bash
   cp secretsprivate/etrade.env.template secretsprivate/etrade.env
   cp secretsprivate/telegram.env.template secretsprivate/telegram.env
   ```

2. **Fill in credentials**:
   - Edit `secretsprivate/etrade.env` with your E*TRADE keys/secrets
   - Edit `secretsprivate/telegram.env` with your Telegram bot token/chat ID

3. **Automatic loading**: `modules/config_loader.py` automatically loads from `secretsprivate/` when `ENVIRONMENT=development`

### **Production Deployment**
- **Location**: Google Secret Manager
- **Access**: Via service account with Secret Manager permissions
- **Secret Names**:
  - `etrade/sandbox/consumer_key`, `etrade/sandbox/consumer_secret`
  - `etrade/prod/consumer_key`, `etrade/prod/consumer_secret`
  - `telegram/bot_token`, `telegram/chat_id`
  - `EtradeStrategy` (combined OAuth tokens)
- **Automatic loading**: `modules/config_loader.py` automatically loads from Secret Manager when `ENVIRONMENT=production`

### **Configuration Files**
- **No hardcoded secrets**: All sensitive credentials removed from `configs/*.env` files (Rev 00233)
- **Templates**: Template files (`.env.template`) are safe to commit
- **Gitignored**: `secretsprivate/` folder and actual `.env` files with secrets are gitignored

### **Security Best Practices**
- ✅ Store production secrets in Google Secret Manager
- ✅ Use `secretsprivate/` for local development only
- ✅ Keep template files (`.template`) in Git
- ✅ Never commit `secretsprivate/` folder to Git
- ✅ Never hardcode secrets in config files

## Priority Rank Formula (v2.1 - Rev 00106/00108)

**Current Production Formula** (Deployed Nov 6, 2025):
- VWAP Distance: **27%** (strongest predictor - +0.772 correlation)
- RS vs SPY: **25%** (2nd strongest - +0.609 correlation)
- ORB Volume: **22%** (moderate - +0.342 correlation)
- Confidence: **13%** (weak - +0.333 correlation)
- RSI: **10%** (context-aware)
- ORB Range: **3%** (minimal contribution)

**Location**: `modules/prime_trading_system.py` (lines 4619-4626)

## 0DTE Strategy Integration

**How It Works**:
1. 0DTE Strategy listens to ORB signal generation
2. Filters ORB signals using Convex Eligibility Filter
3. Generates options strategies (debit spreads, credit spreads, lottos)
4. Executes options trades via E*TRADE Options API
5. Manages options exits independently

**Configuration**:
- Enabled via `ENABLE_0DTE_STRATEGY=true` in `configs/deployment.env`
- Target symbols: SPX, QQQ, SPY (configurable in `easy0DTE/configs/0dte.env`)
- Strategy types: Debit spreads, credit spreads, lottos

**Code Location**:
- `easy0DTE/modules/prime_0dte_strategy_manager.py` - Main 0DTE manager
- `easy0DTE/modules/convex_eligibility_filter.py` - Eligibility filter
- `easy0DTE/configs/0dte.env` - 0DTE configuration


