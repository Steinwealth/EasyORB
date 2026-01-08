# Modules Documentation

**Last Updated**: January 6, 2026  
**Version**: Rev 00231 (Trade ID Shortening & Alert Formatting Improvements)  
**Status**: ✅ Production Ready

## Overview

This directory contains documentation for the Easy ORB Strategy modules package. The modules provide all core functionality for the trading system, including data management, risk management, strategy execution, and position monitoring.

## Module Structure

### Core Modules

- **`config_loader.py`**: Unified configuration loader for Easy ORB Strategy
- **`prime_models.py`**: Data models and enums used throughout the system
- **`__init__.py`**: Package initialization and exports

### Prime System Modules

- **`prime_data_manager.py`**: High-performance data management with caching
- **`prime_market_manager.py`**: Market hours, holidays, and session management
- **`prime_news_manager.py`**: News sentiment analysis and integration
- **`prime_trading_system.py`**: Main trading system orchestrator
- **`prime_unified_trade_manager.py`**: Unified trade management interface

### Strategy Modules

- **`prime_orb_strategy_manager.py`**: ORB (Opening Range Breakout) strategy implementation
- **`prime_stealth_trailing_tp.py`**: Stealth trailing stop and take profit system
- **`prime_risk_manager.py`**: Comprehensive risk management system
- **`prime_demo_risk_manager.py`**: Demo mode risk management

### Trade Execution

- **`prime_etrade_trading.py`**: E*TRADE API integration for live trading
- **`mock_trading_executor.py`**: Mock trading executor for demo mode
- **`prime_unified_trade_manager.py`**: Unified trade management

### Alert & Monitoring

- **`prime_alert_manager.py`**: Telegram alert management system
- **`prime_health_monitor.py`**: System health monitoring
- **`prime_exit_monitoring_collector.py`**: Exit monitoring and data collection

### Data & Persistence

- **`gcs_persistence.py`**: Google Cloud Storage persistence layer
- **`adv_data_manager.py`**: Average Daily Volume (ADV) data management
- **`priority_data_collector.py`**: Priority data collection system

### Utilities

- **`dynamic_holiday_calculator.py`**: Dynamic holiday calculation
- **`inverse_etf_detector.py`**: Inverse ETF detection and mapping
- **`prime_sentiment_tracker.py`**: Sentiment tracking system
- **`prime_symbol_score.py`**: Symbol scoring system
- **`prime_trade_prioritizer.py`**: Trade prioritization logic
- **`prime_signal_analyzer.py`**: Signal analysis and validation
- **`prime_enhanced_red_day_detector.py`**: Enhanced red day detection
- **`market_regime_detector.py`**: Market regime detection
- **`daily_loss_analyzer.py`**: Daily loss analysis
- **`daily_run_tracker.py`**: Daily run tracking
- **`health_endpoints.py`**: Health check endpoints
- **`etrade_oauth_integration.py`**: E*TRADE OAuth integration
- **`symbol_score_integration.py`**: Symbol score integration
- **`prime_settings_configuration.py`**: Settings configuration management
- **`prime_compound_engine.py`**: Compound engine (archived)

## Key Features

### Unified Configuration (Rev 00201)
- **65+ configurable settings** via `configs/` files
- **No hardcoded values**
- **Single source of truth**

### Optimized Exit Settings (Rev 00196)
- **Breakeven**: 0.75% activation after 6.4 minutes
- **Trailing**: 0.7% activation after 6.4 minutes
- **Distance**: 1.5-2.5% based on volatility
- **Expected**: 85-90% profit capture

### Multi-Factor Ranking (Rev 00108)
- **VWAP Distance**: 27% (strongest predictor)
- **RS vs SPY**: 25% (2nd strongest)
- **ORB Volume**: 22% (moderate)
- **Data-driven**: Based on correlation analysis

### Entry Bar Protection (Rev 00135)
- **Permanent Floor Stops**: Based on ORB volatility
- **Tiered Stops**: 2-8% based on volatility
- **Prevents**: 64% of immediate stop-outs

## Documentation Files

- **`README.md`**: This file - module overview
- **`API.md`**: API reference documentation (if exists)
- **`ARCHITECTURE.md`**: Architecture documentation (if exists)

## Version Information

- **Current Version**: 2.31.0
- **Last Updated**: January 6, 2026
- **Rev**: 00231 (Trade ID Shortening & Alert Formatting Improvements)

---

*For complete strategy documentation, see [docs/](../docs/)*  
*For configuration details, see [configs/](../configs/)*

