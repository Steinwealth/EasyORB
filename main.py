#!/usr/bin/env python3
"""
Improved Main Entry Point
High-performance entry point using the integrated trading system
Consolidates all functionality and eliminates redundancy
"""

from __future__ import annotations
import os
import sys
import logging
import argparse
import asyncio
import signal
from typing import Optional
from datetime import datetime

# --- Prime System Imports ---
from modules.prime_trading_system import (
    get_prime_trading_system, PrimeTradingSystem, TradingConfig, SystemMode
)
from modules.prime_market_manager import (
    get_prime_market_manager, PrimeMarketManager, MarketSession
)
# ARCHIVED (Rev 00173): Production signal generator no longer used - ORB manager generates signals directly
# DELETED (Oct 20, 2025): Removed production_signal_generator import - ORB strategy handles signals directly
from modules.etrade_oauth_integration import get_etrade_oauth_integration
from modules.prime_etrade_trading import PrimeETradeTrading
from modules.prime_models import StrategyMode
from modules.config_loader import load_configuration, get_config_value
from modules.prime_alert_manager import AlertLevel

# OAuth keep-alive handled by Cloud Scheduler (no local keep-alive needed)

# --- Google Cloud specific imports ---
try:
    from google.cloud import logging as gcp_logging
    GCP_LOGGING_AVAILABLE = True
except ImportError:
    GCP_LOGGING_AVAILABLE = False

# --- Load configuration based on command line args or environment ---
def load_app_config():
    parser = argparse.ArgumentParser(description='ETrade Strategy Trading Bot - Improved')
    parser.add_argument('--strategy-mode', default=os.getenv('STRATEGY_MODE', 'standard'),
                       choices=['standard', 'advanced', 'quantum'],
                       help='Trading strategy mode')
    parser.add_argument('--system-mode', default=os.getenv('SYSTEM_MODE', 'full_trading'),
                       choices=['signal_only', 'scanner_only', 'full_trading', 'alert_only'],
                       help='System operation mode')
    parser.add_argument('--environment', default=os.getenv('ENVIRONMENT', 'development'),
                       choices=['development', 'production', 'sandbox'],
                       help='Deployment environment')
    parser.add_argument('--etrade-mode', default=os.getenv('ETRADE_MODE', 'demo'),
                       choices=['demo', 'live'],
                       help='ETrade trading mode (demo or live)')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', 8080)),
                       help='Port for HTTP server (cloud mode)')
    parser.add_argument('--host', default=os.getenv('HOST', '0.0.0.0'),
                       help='Host for HTTP server (cloud mode)')
    parser.add_argument('--cloud-mode', action='store_true',
                       help='Enable cloud deployment mode with HTTP server')
    parser.add_argument('--enable-premarket', action='store_true',
                       help='Enable pre-market news analysis')
    parser.add_argument('--enable-confluence', action='store_true',
                       help='Enable confluence trading system')
    parser.add_argument('--enable-multi-strategy', action='store_true',
                       help='Enable multi-strategy engine')
    parser.add_argument('--enable-news-sentiment', action='store_true',
                       help='Enable news sentiment analysis')
    parser.add_argument('--enable-enhanced-signals', action='store_true',
                       help='Enable enhanced signal generation')
    parser.add_argument('--enable-production-signals', action='store_true',
                       help='Enable Production Signal Generator (THE ONE AND ONLY)')
    parser.add_argument('--enable-signal-optimization', action='store_true',
                       help='Enable signal optimization and quality monitoring')
    parser.add_argument('--log-level', default=os.getenv('LOG_LEVEL', 'INFO'),
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='Set logging level')
    parser.add_argument('--max-positions', type=int, default=int(os.getenv('MAX_POSITIONS', '10')),
                       help='Maximum number of positions')
    parser.add_argument('--scan-frequency', type=int, default=int(os.getenv('SCAN_FREQUENCY', '30')),
                       help='Scan frequency in seconds')
    
    args = parser.parse_args()
    
    # Load unified configuration
    automation_mode = 'live' if args.etrade_mode == 'live' else 'demo'
    config = load_configuration(args.strategy_mode, automation_mode, args.environment)
    
    # Set environment variables for backward compatibility
    for key, value in config.items():
        os.environ[key] = str(value)
    
    return config, args

# --- Initialize configuration ---
try:
    CONFIG, ARGS = load_app_config()
except Exception as e:
    print(f"Failed to load configuration: {e}")
    sys.exit(1)

# --- Logging Configuration ---
def setup_logging():
    """Setup optimized logging for all environments"""
    # Get log level from args or config
    log_level = ARGS.log_level.upper() if hasattr(ARGS, 'log_level') else get_config_value("SESSION_LOG_LEVEL", "INFO").upper()
    
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Create formatter
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ"
    )
    
    # Console handler (required for all environments)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)
    
    # Optional file handler for local development
    if ARGS.environment == 'development' and get_config_value("FILE_LOGGING", True):
        log_path = get_config_value("LOG_PATH", "logs/signals.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    
    return logger

# --- Google Cloud Logging Setup ---
def setup_cloud_logging():
    """Setup Google Cloud Logging if available"""
    if GCP_LOGGING_AVAILABLE and ARGS.environment == 'production':
        try:
            client = gcp_logging.Client()
            client.setup_logging()
            print("Google Cloud Logging initialized")
            return True
        except Exception as e:
            print(f"Failed to initialize GCP logging: {e}")
            return False
    return False

# --- Global System Instance ---
_system_instance = None

def _to_strategy_mode(mode_str: str) -> StrategyMode:
    """Safely convert string to StrategyMode enum with a sensible default."""
    mapping = {
        "standard": StrategyMode.STANDARD,
        "advanced": StrategyMode.ADVANCED,
        "quantum": StrategyMode.QUANTUM,
    }
    return mapping.get(str(mode_str).lower(), StrategyMode.STANDARD)

def get_integrated_system():
    """Get or create the integrated system instance"""
    global _system_instance
    if _system_instance is None:
        # Determine trading mode strictly from ETRADE_MODE to avoid enum mismatch
        resolved_mode = SystemMode.DEMO_MODE if ARGS.etrade_mode == 'demo' else SystemMode.LIVE_MODE

        # Create system configuration
        system_config = TradingConfig(
            mode=resolved_mode,
            strategy_mode=_to_strategy_mode(ARGS.strategy_mode),
            enable_premarket_analysis=ARGS.enable_premarket,
            enable_confluence_trading=ARGS.enable_confluence,
            enable_multi_strategy=ARGS.enable_multi_strategy,
            enable_news_sentiment=ARGS.enable_news_sentiment,
            enable_enhanced_signals=ARGS.enable_enhanced_signals,
            max_positions=ARGS.max_positions,
            scan_frequency=ARGS.scan_frequency
        )
        _system_instance = get_prime_trading_system(system_config)
    return _system_instance

# --- Health Check Endpoint ---
async def health_check():
    """Comprehensive health check endpoint using integrated system"""
    try:
        # Get integrated system instance
        system = get_integrated_system()
        
        # Get system metrics
        metrics = system.get_metrics()
        
        # Determine health status
        health_status = "healthy"
        if metrics["system_metrics"]["errors"] > 10:
            health_status = "degraded"
        if metrics["system_metrics"]["errors"] > 50:
            health_status = "unhealthy"
        
        # Check if deployment test file exists
        import os
        test_file_exists = os.path.exists("DEPLOYMENT_TEST_00078.txt")
        test_file_content = ""
        if test_file_exists:
            try:
                with open("DEPLOYMENT_TEST_00078.txt", "r") as f:
                    test_file_content = f.read().strip()
            except:
                test_file_content = "Error reading file"
        
        return {
            "status": health_status,
            "timestamp": datetime.utcnow().isoformat(),
            "environment": ARGS.environment,
            "strategy_mode": ARGS.strategy_mode,
            "system_mode": ARGS.system_mode,
            "uptime_hours": metrics["system_metrics"]["uptime_hours"],
            "current_phase": metrics["current_phase"],
            "running": metrics["running"],
            "system_metrics": metrics["system_metrics"],
            "trading_metrics": metrics["trading_metrics"],
            "scanner_metrics": metrics["scanner_metrics"],
            "deployment_test": {
                "file_exists": test_file_exists,
                "content": test_file_content
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# --- HTTP Server for Cloud Mode ---
async def check_and_build_stale_watchlist():
    """Deprecated: Dynamic watchlist build removed. Using static core_list.csv."""
    logger = logging.getLogger("improved_main")
    logger.info("🗒️ Watchlist builder disabled - using static core_list.csv")
    return

async def start_http_server():
    """Start HTTP server for cloud deployment"""
    try:
        try:
            from aiohttp import web
        except ImportError:
            logger = logging.getLogger("improved_main")
            logger.error("aiohttp not available. Install with: pip install aiohttp")
            return None
        
        async def handle_health(request):
            health_data = await health_check()
            status_code = 200 if health_data["status"] in ["healthy", "degraded"] else 503
            return web.json_response(health_data, status=status_code)
        
        async def handle_metrics(request):
            system = get_integrated_system()
            metrics = system.get_metrics()
            return web.json_response(metrics)
        
        async def handle_status(request):
            health_data = await health_check()
            return web.json_response(health_data)
        
        async def handle_control(request):
            """Control endpoint for system management"""
            data = await request.json()
            action = data.get('action')
            
            if action == 'shutdown':
                system = get_integrated_system()
                await system.shutdown()
                return web.json_response({"status": "shutdown_initiated"})
            elif action == 'restart':
                # Restart would be handled by the container orchestrator
                return web.json_response({"status": "restart_initiated"})
            else:
                return web.json_response({"error": "unknown_action"}, status=400)
        

        async def handle_build_watchlist(request):
            """Deprecated endpoint; static core_list.csv is used. Returns success no-op."""
            logger = logging.getLogger("improved_main")
            logger.info("📋 /api/build-watchlist called - dynamic builder disabled; using core_list.csv")
            return web.json_response({
                "status": "success",
                "message": "Dynamic watchlist disabled. Using static core_list.csv",
                "timestamp": datetime.utcnow().isoformat(),
                "force_rebuild": False,
                "symbol_count": None
            })
        
        async def handle_watchlist_status(request):
            """Return static watchlist status indicating core_list.csv usage."""
            logger = logging.getLogger("improved_main")
            file_path = "data/watchlist/core_list.csv"
            info = {
                "using_static_core_list": True,
                "file_exists": os.path.exists(file_path),
                "timestamp": datetime.utcnow().isoformat()
            }
            if info["file_exists"]:
                try:
                    mod_time = os.path.getmtime(file_path)
                    info["last_modified"] = datetime.fromtimestamp(mod_time).isoformat()
                    try:
                        import pandas as pd
                        df = pd.read_csv(file_path)
                        info["symbol_count"] = len(df)
                    except Exception:
                        info["symbol_count"] = None
                except Exception:
                    pass
            return web.json_response({"status": "success", "watchlist": info})
        
        async def handle_oauth_token_renewed(request):
            """Handle OAuth token renewal webhook"""
            try:
                logger = logging.getLogger("improved_main")
                data = await request.json()
                environment = data.get("environment", "prod")
                
                logger.info(f"🔄 Received OAuth token renewal webhook for {environment}")
                
                # Send OAuth token renewal confirmation alert
                system = get_integrated_system()
                if system.alert_manager:
                    success = await system.alert_manager.send_oauth_renewal_success(environment)
                    if success:
                        logger.info(f"✅ OAuth token renewal alert sent for {environment}")
                        return web.json_response({
                            "status": "success", 
                            "message": f"OAuth token renewal alert sent for {environment}"
                        })
                    else:
                        logger.error(f"❌ Failed to send OAuth token renewal alert for {environment}")
                        return web.json_response({
                            "status": "error", 
                            "message": f"Failed to send OAuth token renewal alert for {environment}"
                        }, status=500)
                else:
                    logger.error("❌ Alert manager not available")
                    return web.json_response({
                        "status": "error", 
                        "message": "Alert manager not available"
                    }, status=500)
                    
            except Exception as e:
                logger.error(f"❌ Error handling OAuth token renewal webhook: {e}")
                return web.json_response({
                    "status": "error", 
                    "message": f"Error handling OAuth token renewal webhook: {str(e)}"
                }, status=500)

        async def handle_oauth_test_alert(request):
            """Test OAuth alert functionality"""
            try:
                logger = logging.getLogger("improved_main")
                logger.info("🔄 Testing OAuth alert functionality")
                
                # Get the integrated trading system
                system = get_integrated_system()
                
                if system.alert_manager:
                    # Test both production and sandbox alerts
                    success_prod = await system.alert_manager.send_oauth_renewal_success("prod")
                    success_sandbox = await system.alert_manager.send_oauth_renewal_success("sandbox")
                    
                    if success_prod and success_sandbox:
                        logger.info("✅ OAuth test alerts sent successfully")
                        return web.json_response({
                            "status": "success", 
                            "message": "OAuth test alerts sent successfully"
                        })
                    else:
                        logger.error("❌ Some OAuth test alerts failed")
                        return web.json_response({
                            "status": "partial", 
                            "message": "Some OAuth test alerts failed"
                        })
                else:
                    logger.error("❌ Alert manager not available")
                    return web.json_response({
                        "status": "error", 
                        "message": "Alert manager not available"
                    }, status=500)
                    
            except Exception as e:
                logger.error(f"❌ Error testing OAuth alerts: {e}")
                return web.json_response({
                    "status": "error", 
                    "message": f"Error testing OAuth alerts: {str(e)}"
                }, status=500)
        
        async def handle_market_open_alert(request):
            """
            Market open alert endpoint (Cloud Scheduler at 8:30 AM ET / 5:30 AM PT)
            Sends Good Morning alert with token status 1 hour before market open
            
            RESTORED (Oct 24, 2025): Cloud Scheduler job IS calling this endpoint
            """
            try:
                logger = logging.getLogger("improved_main")
                logger.info("🌅 Market open alert triggered by Cloud Scheduler (8:30 AM ET)")
                
                # Get the system instance
                system = get_integrated_system()
                if not system or not system.alert_manager:
                    logger.warning("System or alert_manager not available for market open alert")
                    return web.json_response({
                        "status": "error",
                        "message": "System not available"
                    }, status=503)
                
                # Send Good Morning alert via alert manager
                success = await system.alert_manager.send_oauth_morning_alert()
                
                if success:
                    logger.info("✅ Good Morning alert sent successfully")
                    return web.json_response({
                        "status": "success",
                        "message": "Good Morning alert sent"
                    })
                else:
                    logger.warning("⚠️ Good Morning alert failed to send")
                    return web.json_response({
                        "status": "warning",
                        "message": "Alert send failed (non-critical)"
                    }, status=200)  # 200 to prevent Cloud Scheduler retries
                    
            except Exception as e:
                logger = logging.getLogger("improved_main")
                logger.error(f"❌ Error in market open alert endpoint: {e}")
                return web.json_response({
                    "status": "error",
                    "message": f"Market open alert error: {str(e)}"
                }, status=500)
        
        async def handle_end_of_day_report(request):
            """
            End of day report endpoint (Cloud Scheduler at 4:05 PM ET / 1:05 PM PT)
            Sends EOD summary with daily P&L and performance metrics
            
            RESTORED (Oct 24, 2025): Cloud Scheduler job IS calling this endpoint
            FIXED (Nov 2, 2025 - Rev 00093): Added weekday/holiday checking to prevent weekend alerts
            """
            try:
                logger = logging.getLogger("improved_main")
                logger.info("📊 End of day report triggered by Cloud Scheduler (4:05 PM ET)")
                
                # Rev 00093: Check if it's a trading day BEFORE sending EOD report
                from datetime import date
                from modules.prime_market_hours import should_skip_trading
                
                today = date.today()
                is_weekend = today.weekday() >= 5  # Saturday=5, Sunday=6
                should_skip, skip_reason, holiday_name = should_skip_trading(today)
                
                if is_weekend:
                    logger.info(f"📅 Weekend ({today.strftime('%A')}) - Skipping EOD report")
                    return web.json_response({
                        "status": "skipped",
                        "message": f"Weekend ({today.strftime('%A')}) - No EOD report sent"
                    })
                elif should_skip:
                    logger.info(f"📅 Holiday ({holiday_name}) - Skipping EOD report")
                    return web.json_response({
                        "status": "skipped",
                        "message": f"Holiday ({holiday_name}) - No EOD report sent"
                    })
                
                # Get the system instance
                system = get_integrated_system()
                if not system or not system.alert_manager:
                    logger.warning("System or alert_manager not available for EOD report")
                    return web.json_response({
                        "status": "error",
                        "message": "System not available"
                    }, status=503)
                
                # Send Demo Mode EOD summary
                logger.info("Sending Demo Mode EOD summary...")
                await system.alert_manager._send_demo_eod_summary()
                
                # Send Live Mode EOD summary (if unified trade manager exists)
                if hasattr(system, 'unified_trade_manager') and system.unified_trade_manager:
                    logger.info("Sending Live Mode EOD summary...")
                    await system.alert_manager._send_live_eod_summary(system.unified_trade_manager)
                
                # Send 0DTE Options EOD report (Rev 00206)
                if hasattr(system, 'dte0_manager') and system.dte0_manager:
                    if hasattr(system.dte0_manager, 'options_executor') and system.dte0_manager.options_executor:
                        try:
                            logger.info("Sending 0DTE Options EOD report...")
                            options_executor = system.dte0_manager.options_executor
                            
                            # Get stats from mock executor if in demo mode
                            if options_executor.demo_mode and options_executor.mock_executor:
                                daily_stats = options_executor.mock_executor.get_daily_stats()
                                weekly_stats = options_executor.mock_executor.get_weekly_stats()
                                all_time_stats = options_executor.mock_executor.get_all_time_stats()
                                account_balance = options_executor.mock_executor.account_balance
                                starting_balance = options_executor.mock_executor.starting_balance
                                mode = "DEMO"
                            else:
                                # Live mode - would need to get stats from live executor
                                daily_stats = {'positions_closed': 0, 'winning_trades': 0, 'losing_trades': 0, 'total_pnl': 0.0, 'best_trade': 0.0, 'worst_trade': 0.0, 'total_wins_sum': 0.0, 'total_losses_sum': 0.0}
                                weekly_stats = {'positions_closed': 0, 'winning_trades': 0, 'losing_trades': 0, 'total_pnl': 0.0, 'total_wins_sum': 0.0, 'total_losses_sum': 0.0}
                                all_time_stats = None
                                account_balance = 0.0
                                starting_balance = 0.0
                                mode = "LIVE"
                            
                            # Send Options EOD report
                            await system.alert_manager.send_options_end_of_day_report(
                                daily_stats=daily_stats,
                                weekly_stats=weekly_stats,
                                all_time_stats=all_time_stats,
                                account_balance=account_balance,
                                starting_balance=starting_balance,
                                mode=mode
                            )
                            logger.info(f"✅ Options EOD report sent ({mode} Mode)")
                        except Exception as options_eod_error:
                            logger.error(f"Failed to send Options EOD report: {options_eod_error}", exc_info=True)
                
                logger.info("✅ EOD reports sent successfully")
                return web.json_response({
                    "status": "success",
                    "message": "EOD reports sent"
                })
                    
            except Exception as e:
                logger = logging.getLogger("improved_main")
                logger.error(f"❌ Error in EOD report endpoint: {e}")
                return web.json_response({
                    "status": "error",
                    "message": f"EOD report error: {str(e)}"
                }, status=500)
        
        async def handle_cleanup_historical_data(request):
            """
            Historical data cleanup endpoint (Cloud Scheduler at 4:05 PM ET)
            
            UPDATED (Oct 11, 2025 - Rev 00151):
            - No historical data to clean up (ORB strategy uses intraday bars only)
            - Endpoint kept for backward compatibility with Cloud Scheduler
            - Returns success immediately (no-op)
            """
            try:
                logger = logging.getLogger("improved_main")
                logger.info("🗑️ Cleanup endpoint called (no-op for ORB strategy)")
                
                # ORB strategy doesn't use 100-day historical data
                # Only uses intraday 15-minute bars (fetched on-demand)
                # No cleanup needed - endpoint kept for Cloud Scheduler compatibility
                
                return web.json_response({
                    "status": "success",
                    "message": "No cleanup needed (ORB strategy uses intraday bars only)",
                    "removed_count": 0,
                    "timestamp": datetime.now().isoformat(),
                    "note": "Historical data caching removed in Rev 00151 - ORB strategy optimization"
                })
                    
            except Exception as e:
                logger = logging.getLogger("improved_main")
                logger.error(f"❌ Cleanup endpoint error: {e}")
                return web.json_response({
                    "status": "error",
                    "message": f"Cleanup endpoint error: {str(e)}"
                }, status=500)
        
        async def handle_pending_signals(request):
            """
            Pending signals endpoint (Oct 27, 2025)
            Shows accumulated SO signals during collection window (7:15-7:44 AM PT)
            Useful for real-time monitoring and window optimization
            """
            try:
                logger = logging.getLogger("improved_main")
                logger.info("📡 Pending signals request received")
                
                # Get the system instance
                system = get_integrated_system()
                if not system:
                    return web.json_response({
                        "status": "error",
                        "message": "System not initialized"
                    }, status=503)
                
                # Check if ORB strategy manager exists and has signals
                if not hasattr(system, 'orb_strategy_manager') or not system.orb_strategy_manager:
                    return web.json_response({
                        "status": "ok",
                        "message": "ORB strategy manager not available",
                        "pending_signals": [],
                        "count": 0
                    })
                
                # Get accumulated SO signals
                orb_manager = system.orb_strategy_manager
                accumulated_signals = []
                
                if hasattr(orb_manager, 'accumulated_so_signals'):
                    accumulated_signals = orb_manager.accumulated_so_signals or []
                
                # Format signal preview
                signal_preview = []
                for idx, sig in enumerate(accumulated_signals[:20], 1):  # Show top 20
                    signal_preview.append({
                        "rank": idx,
                        "symbol": sig.get('symbol', 'UNKNOWN'),
                        "price": round(sig.get('price', 0), 2),
                        "confidence": round(sig.get('confidence', 0), 3),
                        "priority_score": round(sig.get('priority_score', 0), 3),
                        "orb_range": round(sig.get('orb_range_pct', 0), 2),
                        "volume_ratio": round(sig.get('volume_ratio', 0), 2)
                    })
                
                return web.json_response({
                    "status": "ok",
                    "timestamp": datetime.now().isoformat(),
                    "collection_window": "7:15-7:44 AM PT (10:15-10:44 AM ET)",
                    "total_signals": len(accumulated_signals),
                    "signals_preview": signal_preview,
                    "max_trades": 15,
                    "will_execute": min(len(accumulated_signals), 15)
                })
                    
            except Exception as e:
                logger = logging.getLogger("improved_main")
                logger.error(f"❌ Error in pending signals endpoint: {e}")
                return web.json_response({
                    "status": "error",
                    "message": f"Pending signals error: {str(e)}"
                }, status=500)
        
        async def handle_market_holiday_check(request):
            """
            Market holiday check endpoint (Cloud Scheduler at 5:30 AM PT / 8:30 AM ET)
            Sends alert if today is a holiday - 1 hour before market would open
            Rev 00163
            """
            try:
                logger = logging.getLogger("improved_main")
                logger.info("🏖️ Market holiday check triggered by Cloud Scheduler")
                
                # Get the system instance
                system = get_integrated_system()
                
                if not system or not system.market_manager:
                    logger.error("❌ System or market manager not available")
                    return web.json_response({
                        "status": "error",
                        "message": "System not initialized"
                    }, status=500)
                
                # Check if today is a trading day
                # Use module-level datetime import (line 16)
                today = datetime.now().date()
                is_trading_day = system.market_manager.is_trading_day()
                
                if is_trading_day:
                    logger.info("✅ Today is a trading day - no holiday alert needed")
                    return web.json_response({
                        "status": "success",
                        "message": "Today is a trading day",
                        "is_holiday": False,
                        "timestamp": datetime.now().isoformat()
                    })
                
                # Today is NOT a trading day - check if it's a holiday (not just weekend)
                day_of_week = today.weekday()  # 0=Monday, 6=Sunday
                
                if day_of_week >= 5:  # Saturday or Sunday
                    logger.info("⏸️ Today is a weekend - no holiday alert needed")
                    return web.json_response({
                        "status": "success",
                        "message": "Today is a weekend",
                        "is_holiday": False,
                        "is_weekend": True,
                        "timestamp": datetime.now().isoformat()
                    })
                
                # It's a weekday but not a trading day = HOLIDAY
                # Rev 00087: Use unified holiday checker
                logger.info("🏖️ Today is a holiday - checking type")
                
                # Use unified holiday checker
                from modules.dynamic_holiday_calculator import should_skip_trading
                
                should_skip, skip_reason, holiday_name = should_skip_trading(today)
                
                if not should_skip:
                    # Shouldn't happen (market_manager said not trading day), but handle gracefully
                    holiday_name = "Market Holiday"
                    skip_reason = "MARKET_CLOSED"
                    logger.warning("Holiday detected by market_manager but not by holiday calculator")
                
                # Send holiday alert (unified method)
                # NOTE: This endpoint is called by Cloud Scheduler, but the morning alert (5:30 AM PT)
                # now also checks for holidays. This is a redundant check for backwards compatibility.
                if system.alert_manager:
                    success = await system.alert_manager.send_holiday_alert(
                        holiday_name=holiday_name,
                        skip_reason=skip_reason
                    )
                    
                    if success:
                        logger.info(f"✅ Market holiday alert sent - {holiday_name}")
                        return web.json_response({
                            "status": "success",
                            "message": f"Holiday alert sent - {holiday_name}",
                            "holiday_name": holiday_name,
                            "holiday_date": holiday_date,
                            "is_holiday": True,
                            "timestamp": datetime.now().isoformat()
                        })
                    else:
                        logger.error("❌ Failed to send holiday alert")
                        return web.json_response({
                            "status": "error",
                            "message": "Failed to send holiday alert"
                        }, status=500)
                else:
                    logger.error("❌ Alert manager not available")
                    return web.json_response({
                        "status": "error",
                        "message": "Alert manager not available"
                    }, status=500)
                
            except Exception as e:
                logger = logging.getLogger("improved_main")
                logger.error(f"Error in market holiday check: {e}")
                return web.json_response({
                    "status": "error",
                    "message": str(e)
                }, status=500)
        
        async def handle_manual_orb_capture(request):
            """Manually trigger ORB capture (Rev 00173 - for testing/recovery)"""
            try:
                logger = logging.getLogger("improved_main")
                logger.info("📊 Manual ORB capture triggered")
                
                # Get the integrated trading system
                system = get_integrated_system()
                
                if not system:
                    return web.json_response({
                        "status": "error",
                        "message": "Trading system not initialized"
                    }, status=500)
                
                # Check if ORB capture is available
                if not hasattr(system, '_capture_orb_for_all_symbols'):
                    return web.json_response({
                        "status": "error",
                        "message": "ORB capture method not available"
                    }, status=500)
                
                # Check if ORB strategy manager is initialized
                if not hasattr(system, 'orb_strategy_manager') or not system.orb_strategy_manager:
                    return web.json_response({
                        "status": "error",
                        "message": "ORB Strategy Manager not initialized"
                    }, status=500)
                
                # Trigger ORB capture
                logger.info(f"🎯 Manually capturing ORB for {len(system.symbol_list)} symbols...")
                await system._capture_orb_for_all_symbols()
                
                # Get capture results
                symbols_captured = len(system.orb_strategy_manager.orb_data)
                
                logger.info(f"✅ Manual ORB capture complete: {symbols_captured} symbols")
                
                return web.json_response({
                    "status": "success",
                    "message": f"ORB captured for {symbols_captured} symbols",
                    "symbols_captured": symbols_captured,
                    "symbol_list_size": len(system.symbol_list),
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                logger = logging.getLogger("improved_main")
                logger.error(f"Error in manual ORB capture: {e}")
                return web.json_response({
                    "status": "error",
                    "message": str(e)
                }, status=500)
        
        async def handle_positions(request):
            """
            Get current open positions with full details (Rev 00068)
            Returns position data from stealth trailing system (source of truth for monitoring)
            """
            try:
                logger = logging.getLogger("improved_main")
                logger.info("📊 /api/positions called")
                
                # Get the integrated trading system
                system = get_integrated_system()
                
                if not system:
                    return web.json_response({
                        "error": "Trading system not initialized",
                        "total_positions": 0,
                        "positions": []
                    }, status=500)
                
                # Check if stealth trailing is available (source of truth for position monitoring)
                if not hasattr(system, 'stealth_trailing') or not system.stealth_trailing:
                    return web.json_response({
                        "error": "Stealth trailing system not available",
                        "total_positions": 0,
                        "positions": []
                    })
                
                # Get positions from stealth trailing
                positions_data = []
                for symbol, pos_state in system.stealth_trailing.active_positions.items():
                    time_held_sec = (datetime.now() - pos_state.entry_time).total_seconds()
                    time_held_min = time_held_sec / 60.0
                    
                    # Rev 00071: Fix field names to match PositionState dataclass
                    position_value = pos_state.quantity * pos_state.entry_price
                    max_favorable_pct = (pos_state.max_favorable / pos_state.entry_price) * 100 if pos_state.entry_price > 0 else 0.0
                    
                    positions_data.append({
                        'symbol': symbol,
                        'entry_price': pos_state.entry_price,
                        'current_price': pos_state.current_price,
                        'quantity': pos_state.quantity,
                        'position_value': position_value,  # Rev 00071: Calculate (was accessing non-existent field)
                        'unrealized_pnl': pos_state.unrealized_pnl,  # Rev 00071: Fixed field name (was unrealized_pl)
                        'unrealized_pnl_pct': pos_state.unrealized_pnl_pct * 100,  # Rev 00071: Convert to percentage (was unrealized_pl_pct)
                        'current_stop': pos_state.current_stop_loss,
                        'take_profit': pos_state.take_profit,
                        'time_held_min': round(time_held_min, 1),
                        'max_favorable': pos_state.max_favorable,
                        'max_favorable_pct': max_favorable_pct,  # Rev 00071: Calculate (was accessing non-existent field)
                        'entry_bar_protection': False,  # Rev 00071: Placeholder (field doesn't exist in PositionState)
                        'breakeven_activated': pos_state.breakeven_achieved,  # Rev 00071: Fixed field name (was breakeven_activated)
                        'trailing_activated': pos_state.trailing_activated
                    })
                
                logger.info(f"✅ Returning {len(positions_data)} positions from stealth trailing")
                
                return web.json_response({
                    'total_positions': len(positions_data),
                    'positions': positions_data,
                    'timestamp': datetime.now().isoformat(),
                    'mode': system.config.mode.value if hasattr(system.config, 'mode') else 'unknown'
                })
                
            except Exception as e:
                logger = logging.getLogger("improved_main")
                logger.error(f"Error in /api/positions endpoint: {e}")
                return web.json_response({
                    'error': str(e),
                    'total_positions': 0,
                    'positions': []
                }, status=500)
        
        app = web.Application()
        app.router.add_get('/health', handle_health)
        app.router.add_get('/api/health', handle_health)  # Alias for Cloud Scheduler keep-alive
        app.router.add_get('/metrics', handle_metrics)
        app.router.add_get('/status', handle_status)
        app.router.add_post('/control', handle_control)
        app.router.add_post('/api/build-watchlist', handle_build_watchlist)  # Cloud Scheduler endpoint
        app.router.add_get('/api/watchlist-status', handle_watchlist_status)  # Watchlist status endpoint
        app.router.add_post('/api/cleanup-historical-data', handle_cleanup_historical_data)  # Historical data cleanup endpoint (4:05 PM ET)
        app.router.add_post('/api/oauth/token-renewed', handle_oauth_token_renewed)  # OAuth webhook endpoint
        app.router.add_get('/api/oauth/test-alert', handle_oauth_test_alert)  # OAuth test endpoint
        app.router.add_post('/api/end-of-day-report', handle_end_of_day_report)  # EOD report endpoint (4:05 PM ET) - RESTORED Oct 24
        app.router.add_post('/api/alerts/market-open', handle_market_open_alert)  # Good Morning alert (8:30 AM ET) - RESTORED Oct 24
        # NOTE: /api/alerts/midnight-token-expiry → OAuth backend handles midnight alert (separate service)
        app.router.add_get('/api/pending-signals', handle_pending_signals)  # Pending signals endpoint (Oct 27, 2025) - Real-time signal monitoring
        app.router.add_get('/api/positions', handle_positions)  # Position tracking endpoint (Rev 00068 - Oct 30, 2025) - Real-time position monitoring
        app.router.add_post('/api/alerts/market-holiday-check', handle_market_holiday_check)  # Market holiday check endpoint (5:30 AM PT)
        app.router.add_post('/api/manual-orb-capture', handle_manual_orb_capture)  # Manual ORB capture endpoint (Rev 00173)
        app.router.add_get('/', handle_health)  # Root endpoint
        
        # Start server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, ARGS.host, ARGS.port)
        await site.start()
        
        logger = logging.getLogger("improved_main")
        logger.info(f"HTTP server started on {ARGS.host}:{ARGS.port}")
        
        return runner
        
    except Exception as e:
        logger = logging.getLogger("improved_main")
        logger.error(f"Failed to start HTTP server: {e}")
        return None

# --- Graceful Shutdown ---
async def graceful_shutdown(http_runner=None, trading_task=None):
    """Graceful shutdown for all services"""
    logger = logging.getLogger("improved_main")
    logger.info("Initiating graceful shutdown...")
    
    try:
        # Cancel trading task if running
        if trading_task and not trading_task.done():
            logger.info("🛑 Stopping trading system...")
            trading_task.cancel()
            try:
                await trading_task
            except asyncio.CancelledError:
                logger.info("✅ Trading system stopped")
            except Exception as e:
                logger.error(f"❌ Error stopping trading system: {e}")
        
        # OAuth keep-alive handled by Cloud Scheduler (no shutdown needed)
        logger.info("ℹ️  OAuth keep-alive runs automatically via Cloud Scheduler")
        
        # Shutdown HTTP server
        if http_runner:
            await http_runner.cleanup()
        
        # Shutdown integrated system
        system = get_integrated_system()
        await system.shutdown()
        
        logger.info("Graceful shutdown completed")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

# --- Signal Handlers ---
# Global shutdown flag
shutdown_event = asyncio.Event()

def setup_signal_handlers(http_runner=None, trading_task=None):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        logger = logging.getLogger("improved_main")
        logger.info(f"Received signal {signum}, setting shutdown flag...")
        
        # Set the shutdown event to trigger graceful shutdown in the main loop
        shutdown_event.set()
    
    # Only setup signal handlers in the main thread
    try:
        import logging
        log = logging.getLogger("improved_main")
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        log.info("Signal handlers setup successfully")
    except ValueError as e:
        log.warning(f"Cannot setup signal handlers: {e} (not in main thread)")
        # In Cloud Run, signal handling is managed by the platform

# --- Main Function ---
async def main():
    """Main async function"""
    # Setup logging
    logger = setup_logging()
    
    # Setup Google Cloud logging if available
    setup_cloud_logging()
    
    # Detect cloud deployment
    is_cloud_deployment = (
        ARGS.cloud_mode or 
        os.getenv('K_SERVICE') or  # Cloud Run
        os.getenv('GAE_APPLICATION') or  # App Engine
        os.getenv('FUNCTION_NAME') or  # Cloud Functions
        os.getenv('CLOUD_RUN_JOB')  # Cloud Run Jobs
    )
    
    logger.info("🚀 Starting ETrade Strategy - Improved")
    
    # Log version to verify fresh code deployment
    try:
        with open("VERSION.txt", "r") as f:
            version = f.read().strip()
            logger.info(f"📦 CODE VERSION: {version}")
    except:
        logger.warning("⚠️ VERSION.txt not found - cache might be stale")
    
    logger.info(f"Strategy Mode: {ARGS.strategy_mode}")
    logger.info(f"System Mode: {ARGS.system_mode}")
    logger.info(f"Environment: {ARGS.environment}")
    logger.info(f"ETrade Mode: {ARGS.etrade_mode}")
    logger.info(f"Cloud Mode: {ARGS.cloud_mode}")
    logger.info(f"Cloud Deployment Detected: {is_cloud_deployment}")
    logger.info(f"Pre-market Analysis: {ARGS.enable_premarket}")
    logger.info(f"Confluence Trading: {ARGS.enable_confluence}")
    logger.info(f"Multi-Strategy: {ARGS.enable_multi_strategy}")
    logger.info(f"News Sentiment: {ARGS.enable_news_sentiment}")
    logger.info(f"Enhanced Signals: {ARGS.enable_enhanced_signals}")
    logger.info(f"Production Signals: {ARGS.enable_production_signals}")
    logger.info(f"Signal Optimization: {ARGS.enable_signal_optimization}")
    logger.info(f"OAuth Keep-Alive: Managed by Cloud Scheduler")
    
    # Initialize ETrade OAuth and Trader
    logger.info("Initializing ETrade integration...")
    try:
        # Map etrade_mode to correct environment for Secret Manager
        # 'demo' → 'sandbox', 'live' → 'prod'
        secret_manager_env = 'sandbox' if ARGS.etrade_mode == 'demo' else 'prod'
        logger.info(f"ETrade Mode: {ARGS.etrade_mode} → Secret Manager: {secret_manager_env}")
        
        etrade_oauth = get_etrade_oauth_integration(secret_manager_env)
        
        # Check OAuth status
        oauth_status = etrade_oauth.get_auth_status()
        logger.info(f"OAuth Status: {oauth_status}")
        
        if not etrade_oauth.is_authenticated():
            logger.warning("⚠️  OAuth not authenticated. Please setup tokens first.")
            logger.info(f"Run: cd modules && python3 keepalive_oauth.py {ARGS.etrade_mode}")
            if ARGS.etrade_mode == 'live' and not ARGS.cloud_mode:
                logger.warning("⚠️  Live trading requires proper OAuth setup")
                return
            # In cloud mode, continue to start HTTP server even without OAuth
            if ARGS.cloud_mode:
                logger.warning("☁️  Cloud mode: Starting HTTP server despite OAuth issue")
                logger.warning("   System will wait for OAuth tokens from Secret Manager")
        
        logger.info("✅ OAuth authentication ready")
        
        # Use mapped environment for ETrade trader
        etrade_trader = PrimeETradeTrading(environment=secret_manager_env)
        
        if etrade_trader.initialize():
            logger.info(f"✅ ETrade {ARGS.etrade_mode} trader initialized successfully")
        else:
            logger.error(f"❌ Failed to initialize ETrade {ARGS.etrade_mode} trader")
            if ARGS.etrade_mode == 'live':
                logger.warning("⚠️  Live trading requires proper OAuth setup")
                logger.info("Run: cd modules && python3 keepalive_oauth.py prod")
                return
        
        # OAuth keep-alive handled automatically by Cloud Scheduler
        # No local keep-alive needed - Cloud Scheduler hits backend every hour
        logger.info("ℹ️  OAuth keep-alive managed by Cloud Scheduler (hourly at :00 and :30)")
    except Exception as e:
        logger.error(f"ETrade initialization failed: {e}")
        if ARGS.etrade_mode == 'live' and not ARGS.cloud_mode:
            logger.warning("⚠️  Live trading requires proper OAuth setup")
            logger.info("Run: cd modules && python3 keepalive_oauth.py prod")
            return
        # In cloud mode, continue to start HTTP server even with OAuth errors
        if ARGS.cloud_mode:
            logger.warning("☁️  Cloud mode: Continuing despite ETrade initialization error")
            logger.warning("   HTTP server will start, system will retry OAuth later")
    
    http_runner = None
    # Ensure trading_task is defined for finally/shutdown even if init fails early
    trading_task = None
    
    try:
        # Determine trading mode strictly from ETRADE_MODE to avoid enum mismatches
        resolved_mode = SystemMode.DEMO_MODE if ARGS.etrade_mode == 'demo' else SystemMode.LIVE_MODE

        # Create system configuration
        system_config = TradingConfig(
            mode=resolved_mode,
            strategy_mode=_to_strategy_mode(ARGS.strategy_mode),
            enable_premarket_analysis=ARGS.enable_premarket,
            enable_confluence_trading=ARGS.enable_confluence,
            enable_multi_strategy=ARGS.enable_multi_strategy,
            enable_news_sentiment=ARGS.enable_news_sentiment,
            enable_enhanced_signals=ARGS.enable_enhanced_signals,
            max_positions=ARGS.max_positions,
            scan_frequency=ARGS.scan_frequency
        )
        
        # Rev 00063: Use get_integrated_system() to ensure single instance (fixes health endpoint)
        # This ensures the trading loop and health endpoint use the SAME system instance
        system = get_integrated_system()
        
        # Start HTTP server if in cloud mode
        if ARGS.cloud_mode:
            http_runner = await start_http_server()
        
        # trading_task already defined above for safe shutdown
        
        # Initialize integrated trading system (without UnifiedServicesManager)
        # Note: UnifiedServicesManager disabled to avoid duplicate alert systems
        logger.info("🔧 Initializing integrated trading system...")
        
        # Initialize system with minimal components (system will create its own)
        minimal_components = {
            'data_manager': None,  # System will initialize
            'etrade_oauth': etrade_oauth,  # CRITICAL: Pass ETrade OAuth for data manager (Rev 00180AE)
            # ARCHIVED (Rev 00173): Signal generator no longer used - ORB generates directly
            # 'signal_generator': None,
            'risk_manager': None,  # System will initialize
            'trade_manager': None,  # System will initialize
            'stealth_trailing': None,  # System will initialize
            'alert_manager': None  # System will initialize with proper config
        }
        
        try:
            await system.initialize(minimal_components)
            logger.info("✅ Trading system initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize trading system: {e}")
            raise
        
        # Initialize 0DTE Strategy (if enabled)
        dte0_manager = None
        ENABLE_0DTE_STRATEGY = os.getenv('ENABLE_0DTE_STRATEGY', 'false').lower() == 'true'

        # Debug logging for 0DTE strategy enablement
        logger.info(f"🔧 ENABLE_0DTE_STRATEGY environment variable: {os.getenv('ENABLE_0DTE_STRATEGY', 'NOT_SET')}")
        logger.info(f"🔧 ENABLE_0DTE_STRATEGY parsed value: {ENABLE_0DTE_STRATEGY}")

        if ENABLE_0DTE_STRATEGY:
            logger.info("🎯 Initializing 0DTE Strategy...")
            try:
                # Add 0DTE Strategy modules to Python path
                import sys
                # Try multiple path locations for 0DTE Strategy
                # 1. Same directory as main.py (./easy0DTE) - NEW STRUCTURE
                # 2. Absolute path in container (/app/easy0DTE)
                # 3. Legacy path for backwards compatibility (../1. The Easy 0DTE Strategy)
                dte_strategy_paths = [
                    os.path.join(os.path.dirname(__file__), 'easy0DTE'),
                    '/app/easy0DTE',
                    os.path.join(os.path.dirname(__file__), '../1. The Easy 0DTE Strategy')  # Legacy fallback
                ]
                dte_strategy_path = None
                for path in dte_strategy_paths:
                    if os.path.exists(path):
                        dte_strategy_path = path
                        break
                
                if dte_strategy_path and os.path.exists(dte_strategy_path):
                    # Add both the base path and modules path to sys.path
                    sys.path.insert(0, dte_strategy_path)
                    modules_path = os.path.join(dte_strategy_path, 'modules')
                    if os.path.exists(modules_path):
                        sys.path.insert(0, modules_path)
                    logger.info(f"✅ Added 0DTE Strategy path: {dte_strategy_path}")
                
                # Import 0DTE modules (try both import styles)
                try:
                    from modules.convex_eligibility_filter import ConvexEligibilityFilter
                    from modules.prime_0dte_strategy_manager import Prime0DTEStrategyManager
                    from modules.options_chain_manager import OptionsChainManager
                    from modules.options_trading_executor import OptionsTradingExecutor
                    from modules.mock_options_executor import MockOptionsExecutor
                except ImportError:
                    # Fallback: try direct import from easy0DTE.modules
                    from easy0DTE.modules.convex_eligibility_filter import ConvexEligibilityFilter
                    from easy0DTE.modules.prime_0dte_strategy_manager import Prime0DTEStrategyManager
                    from easy0DTE.modules.options_chain_manager import OptionsChainManager
                    from easy0DTE.modules.options_trading_executor import OptionsTradingExecutor
                    from easy0DTE.modules.mock_options_executor import MockOptionsExecutor
                
                # Determine Demo/Live mode for 0DTE (same as ORB Strategy)
                is_demo_mode = ARGS.etrade_mode == 'demo'
                
                # Initialize 0DTE components
                convex_filter = ConvexEligibilityFilter(
                    volatility_percentile_threshold=float(os.getenv('0DTE_CONVEX_VOLATILITY_PERCENTILE', '0.80')),
                    orb_range_min_pct=float(os.getenv('0DTE_CONVEX_ORB_RANGE_MIN', '0.35')),
                    momentum_confirmation_required=os.getenv('0DTE_CONVEX_MOMENTUM_REQUIRED', 'true').lower() == 'true',
                    trend_day_required=os.getenv('0DTE_CONVEX_TREND_DAY_REQUIRED', 'true').lower() == 'true'
                )
                
                # Initialize Options Chain Manager
                etrade_options_api = None
                if not is_demo_mode:
                    # Live Mode: Initialize ETrade Options API
                    try:
                        from modules.etrade_options_api import ETradeOptionsAPI
                        
                        # Rev 00218: Support separate ETrade account for 0DTE Strategy
                        # Check for separate account configuration
                        dte_account_id = os.getenv('0DTE_ETRADE_ACCOUNT_ID', None)
                        dte_secret_name = os.getenv('0DTE_ETRADE_SECRET_NAME', None)
                        
                        if dte_account_id:
                            # Use separate account for 0DTE Strategy
                            logger.info(f"🔗 Initializing 0DTE Strategy with separate ETrade account: {dte_account_id}")
                            
                            # Option 1: Use separate ETrade instance (if separate OAuth tokens)
                            if dte_secret_name:
                                # TODO: Support separate OAuth tokens via custom PrimeETradeTrading instance
                                # For now, use shared instance but select separate account
                                logger.info(f"   Using separate OAuth tokens from: {dte_secret_name}")
                                logger.warning("⚠️ Separate OAuth tokens not yet implemented - using shared tokens")
                            
                            # Initialize with account selection
                            etrade_options_api = ETradeOptionsAPI(
                                etrade_trading=etrade_trader,  # Can use shared instance or create separate
                                environment='prod' if ARGS.environment == 'production' else 'sandbox',
                                account_id=dte_account_id  # Select specific account
                            )
                            logger.info(f"✅ ETrade Options API initialized for Live Mode with account: {dte_account_id}")
                        else:
                            # Use shared ETrade instance (default behavior)
                            etrade_options_api = ETradeOptionsAPI(
                                etrade_trading=etrade_trader,
                                environment='prod' if ARGS.environment == 'production' else 'sandbox'
                            )
                            logger.info("✅ ETrade Options API initialized for Live Mode (shared account)")
                    except Exception as e:
                        logger.error(f"❌ Failed to initialize ETrade Options API: {e}")
                        logger.warning("⚠️ Falling back to Demo Mode for 0DTE Strategy")
                        is_demo_mode = True
                
                options_chain_manager = OptionsChainManager(
                    min_open_interest=int(os.getenv('0DTE_MIN_OPEN_INTEREST', '100')),
                    max_bid_ask_spread_pct=float(os.getenv('0DTE_MAX_BID_ASK_SPREAD_PCT', '5.0')),
                    min_volume=int(os.getenv('0DTE_MIN_VOLUME', '50')),
                    etrade_options_api=etrade_options_api,
                    use_live_api=not is_demo_mode
                )
                
                # Initialize Priority Data Collector (optional, for trade optimization)
                priority_collector = None
                if os.getenv('0DTE_PRIORITY_COLLECTOR_ENABLED', 'false').lower() == 'true':
                    try:
                        from modules.options_priority_data_collector import OptionsPriorityDataCollector
                        gcs_bucket = os.getenv('GCS_BUCKET_NAME', None)
                        priority_collector = OptionsPriorityDataCollector(
                            base_dir="priority_optimizer/0dte_data",
                            gcs_bucket=gcs_bucket,
                            gcs_prefix="priority_optimizer/0dte_signals"
                        )
                        logger.info("✅ Priority Data Collector initialized for 0DTE Strategy")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to initialize Priority Data Collector: {e}")
                
                # Initialize Mock Options Executor for Demo Mode
                mock_options_executor = None
                if is_demo_mode:
                    mock_options_executor = MockOptionsExecutor(alert_manager=system.alert_manager)
                    logger.info("✅ Mock Options Executor initialized for Demo Mode")
                    logger.info(f"   - Starting balance: ${mock_options_executor.starting_balance:.2f}")
                
                # Initialize Options Trading Executor
                # Rev 00231: Using only 35% max position size (matches ORB Strategy) - max_position_cost disabled
                options_executor = OptionsTradingExecutor(
                    auto_partial_enabled=os.getenv('0DTE_AUTO_PARTIAL_ENABLED', 'true').lower() == 'true',
                    partial_profit_pct=float(os.getenv('0DTE_PARTIAL_PROFIT_PCT', '0.50')),
                    runner_profit_pct=float(os.getenv('0DTE_RUNNER_PROFIT_PCT', '2.0')),
                    max_position_cost=999999.0,  # Disabled - using only 35% percentage-based limit
                    max_position_size_pct=0.35,  # 35% max position size (matches ORB Strategy)
                    demo_mode=is_demo_mode,
                    mock_executor=mock_options_executor,
                    alert_manager=system.alert_manager,
                    priority_collector=priority_collector
                )
                
                # Initialize 0DTE Strategy Manager
                # Priority Order: SPX (Priority 1) → QQQ (Priority 2) → SPY (Priority 3)
                dte0_manager = Prime0DTEStrategyManager(
                    convex_filter=convex_filter,
                    target_symbols=['SPX', 'QQQ', 'SPY'],  # SPX is Priority 1 per README
                    max_positions=int(os.getenv('0DTE_MAX_POSITIONS', '5')),
                    enable_lotto_sleeve=os.getenv('0DTE_LOTTO_SLEEVE_ENABLED', 'false').lower() == 'true',
                    priority_collector=priority_collector,
                    alert_manager=system.alert_manager
                )
                
                # Store references for options execution
                dte0_manager.options_chain_manager = options_chain_manager
                dte0_manager.options_executor = options_executor
                
                # Store reference in system for signal hooking
                system.dte0_manager = dte0_manager

                logger.info("✅ 0DTE Strategy initialized successfully")
                logger.info(f"   🔗 0DTE Manager assigned to system: {system.dte0_manager is not None}")
                logger.info(f"   - Mode: {'🎮 DEMO' if is_demo_mode else '💰 LIVE'}")
                logger.info(f"   - Target symbols: SPX (Priority 1), QQQ (Priority 2), SPY (Priority 3)")
                logger.info(f"   - Max positions: {dte0_manager.max_positions}")
                logger.info(f"   - Lotto sleeve: {'Enabled' if dte0_manager.enable_lotto_sleeve else 'Disabled'}")
                logger.info(f"   - Convex Filter: Volatility ≥{convex_filter.volatility_percentile_threshold*100:.0f}%, Range ≥{convex_filter.orb_range_min_pct:.2f}%")
            except ImportError as e:
                logger.error(f"❌ Failed to import 0DTE modules: {e}")
                logger.warning("⚠️ 0DTE Strategy disabled - continuing with ORB Strategy only")
                dte0_manager = None
            except Exception as e:
                logger.error(f"❌ Failed to initialize 0DTE Strategy: {e}")
                logger.warning("⚠️ 0DTE Strategy disabled - continuing with ORB Strategy only")
                dte0_manager = None
        else:
            logger.info("ℹ️  0DTE Strategy disabled (ENABLE_0DTE_STRATEGY=false)")
        
        # Dynamic watchlist build removed; static core_list.csv is used
        
        # Start trading system in background thread to avoid blocking HTTP server
        logger.info("🚀 Starting prime trading system with ORB strategy...")
        logger.info("📊 Using static core_list.csv (62 elite symbols, tier-ranked)")
        logger.info("🔍 ORB capture at 6:30 AM PT, SO batch at 7:45 AM PT")
        if dte0_manager:
            logger.info("🎯 0DTE Strategy enabled - will listen to ORB signals for QQQ/SPY options")
        
        # Start trading system in background task
        trading_task = asyncio.create_task(system.start())
        
        # Setup signal handlers with trading task
        setup_signal_handlers(http_runner, trading_task)
        
        logger.info("✅ Trading system started in background thread")
        
        # Keep main thread alive to handle HTTP requests
        if ARGS.cloud_mode:
            logger.info("🌐 HTTP server running, keeping main thread alive...")
            try:
                # Wait for shutdown signal instead of infinite loop
                await shutdown_event.wait()
                logger.info("Shutdown signal received, initiating graceful shutdown...")
            except KeyboardInterrupt:
                logger.info("Received KeyboardInterrupt, shutting down...")
        else:
            # In non-cloud mode, wait for trading task to complete
            await trading_task
        
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.exception(f"Fatal error in main: {e}")
        import sys  # Ensure sys is available in exception handler
        sys.exit(1)
    finally:
        # Only attempt graceful shutdown if HTTP runner was started
        if http_runner is not None:
            await graceful_shutdown(http_runner, trading_task)

# --- Entry Point ---
if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
