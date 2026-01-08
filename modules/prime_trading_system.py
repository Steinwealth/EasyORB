# modules/prime_trading_system_optimized.py

"""
Optimized Prime Trading System for Easy ORB Strategy
High-performance trading system with parallel processing and async optimization
Performance improvements: 3x faster main loop, 4x concurrent operations

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

from __future__ import annotations
import asyncio
import logging
import os
import time
import threading
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from collections import deque
import queue
import weakref

from .prime_models import StrategyMode, SignalType, SignalSide, TradeStatus, StopType, TrailingMode
from .config_loader import get_config_value
from .mock_trading_executor import MockTradingExecutor
from .daily_run_tracker import get_daily_run_tracker

# ============================================================================
# TRADING CONFIGURATION
# ============================================================================

class SystemMode(Enum):
    """System operation modes"""
    DEMO_MODE = "demo_mode"      # Demo mode with mock execution
    LIVE_MODE = "live_mode"      # Live mode with real E*TRADE API

@dataclass
class TradingConfig:
    """Trading configuration for the system"""
    mode: SystemMode = SystemMode.DEMO_MODE
    strategy_mode: StrategyMode = StrategyMode.STANDARD
    enable_premarket_analysis: bool = True
    enable_confluence_trading: bool = True
    enable_multi_strategy: bool = True  # Load from environment
    enable_news_sentiment: bool = True
    enable_enhanced_signals: bool = True
    max_positions: int = 15  # Oct 27, 2025: Aligned with max_concurrent_trades (was 20)
    max_daily_trades: int = 200
    scan_frequency: int = 60  # 60 seconds
    position_refresh_frequency: int = 30  # 30 seconds - enhanced for maximum profit capture
    signal_generation_frequency: int = 120  # 2 minutes
    api_calls_per_hour_limit: int = 200
    position_update_interval: float = 1.0  # 1 second - for position updates
    
    # Capital Allocation (Rev 00102: Unified & Validated)
    # ⭐ SINGLE SOURCE OF TRUTH: Adjust capital allocation in configs/strategies.env
    # These defaults are overridden by environment variables
    so_capital_pct: float = 90.0        # Standard Order allocation (% of total account)
    cash_reserve_pct: float = 10.0      # Cash reserve (% of total account)
    orr_capital_pct: float = 0.0         # ORR allocation (DISABLED)
    max_position_pct: float = 35.0       # Max single position size (% of total account)
    expensive_threshold_pct: float = 110.0  # Filter symbols if share price > this % of fair share
    max_concurrent_trades: int = 15      # Maximum trades to execute simultaneously (Oct 27, 2025)
    
    def __post_init__(self):
        """Load configuration from environment after initialization"""
        from .config_loader import get_config_value
        import os
        
        # Rev 00102: Load Capital Allocation from Environment (SINGLE SOURCE OF TRUTH)
        # Priority: SO_CAPITAL_PCT > CASH_RESERVE_PCT > ORR_CAPITAL_PCT
        # Validation: SO + ORR + Reserve MUST = 100%
        self.so_capital_pct = float(get_config_value("SO_CAPITAL_PCT", 90.0))
        self.cash_reserve_pct = float(get_config_value("CASH_RESERVE_PCT", 10.0))
        self.orr_capital_pct = float(get_config_value("ORR_CAPITAL_PCT", 0.0))
        
        # CRITICAL VALIDATION: Ensure SO + ORR + Reserve = 100%
        total_allocation = self.so_capital_pct + self.orr_capital_pct + self.cash_reserve_pct
        if abs(total_allocation - 100.0) > 0.01:  # Allow 0.01% rounding error
            raise ValueError(
                f"❌ CAPITAL ALLOCATION ERROR: SO ({self.so_capital_pct}%) + "
                f"ORR ({self.orr_capital_pct}%) + Reserve ({self.cash_reserve_pct}%) "
                f"= {total_allocation}% (MUST = 100%!)"
            )
        
        log.info(f"✅ Capital Allocation Validated: SO {self.so_capital_pct}% + "
                 f"ORR {self.orr_capital_pct}% + Reserve {self.cash_reserve_pct}% = 100%")
        
        # Load multi-strategy configuration from environment
        multi_strategy_val = get_config_value("ENABLE_MULTI_STRATEGY", "true")
        if isinstance(multi_strategy_val, bool):
            self.enable_multi_strategy = multi_strategy_val
        else:
            self.enable_multi_strategy = str(multi_strategy_val).lower() == "true"
        
        # Load other configurations
        premarket_val = get_config_value("ENABLE_PREMARKET_ANALYSIS", "true")
        self.enable_premarket_analysis = premarket_val if isinstance(premarket_val, bool) else str(premarket_val).lower() == "true"
        
        confluence_val = get_config_value("ENABLE_CONFLUENCE_TRADING", "true")
        self.enable_confluence_trading = confluence_val if isinstance(confluence_val, bool) else str(confluence_val).lower() == "true"
        
        news_val = get_config_value("ENABLE_NEWS_SENTIMENT", "true")
        self.enable_news_sentiment = news_val if isinstance(news_val, bool) else str(news_val).lower() == "true"
        
        enhanced_val = get_config_value("ENABLE_ENHANCED_SIGNALS", "true")
        self.enable_enhanced_signals = enhanced_val if isinstance(enhanced_val, bool) else str(enhanced_val).lower() == "true"
        
        # Load system mode from environment
        trading_mode = get_config_value("TRADING_MODE", "DEMO_MODE")
        if isinstance(trading_mode, str):
            trading_mode = trading_mode.upper()
        else:
            trading_mode = str(trading_mode).upper()
            
        if trading_mode == "LIVE_MODE":
            self.mode = SystemMode.LIVE_MODE
        else:
            self.mode = SystemMode.DEMO_MODE
            
        # Load strategy mode from environment
        strategy_mode_val = get_config_value("STRATEGY_MODE", "standard")
        if isinstance(strategy_mode_val, str):
            strategy_mode_str = strategy_mode_val.lower()
        else:
            strategy_mode_str = str(strategy_mode_val).lower()
            
        if strategy_mode_str == "advanced":
            self.strategy_mode = StrategyMode.ADVANCED
        elif strategy_mode_str == "quantum":
            self.strategy_mode = StrategyMode.QUANTUM
        else:
            self.strategy_mode = StrategyMode.STANDARD

log = logging.getLogger("prime_trading_system_optimized")

# ============================================================================
# PERFORMANCE CONFIGURATION
# ============================================================================

@dataclass
class PerformanceConfig:
    """Performance configuration for optimized trading system"""
    # Parallel processing settings
    max_workers: int = get_config_value("MAX_WORKERS", 10)
    batch_size: int = get_config_value("BATCH_SIZE", 20)
    queue_size: int = get_config_value("QUEUE_SIZE", 1000)
    
    # Timing settings
    main_loop_interval: float = get_config_value("MAIN_LOOP_INTERVAL", 0.1)  # 100ms
    position_update_interval: float = get_config_value("POSITION_UPDATE_INTERVAL", 1.0)  # 1s
    signal_generation_interval: float = get_config_value("SIGNAL_GENERATION_INTERVAL", 5.0)  # 5s
    
    # Memory management
    max_memory_usage: float = get_config_value("MAX_MEMORY_USAGE", 0.8)  # 80%
    gc_interval: int = get_config_value("GC_INTERVAL", 100)  # Every 100 iterations
    
    # Performance monitoring
    enable_metrics: bool = get_config_value("ENABLE_METRICS", True)
    metrics_interval: int = get_config_value("METRICS_INTERVAL", 60)  # Every 60 seconds

# ============================================================================
# PARALLEL PROCESSING MANAGER
# ============================================================================

class ParallelProcessingManager:
    """Manages parallel processing for optimal performance"""
    
    def __init__(self, config: PerformanceConfig):
        self.config = config
        self.thread_pool = ThreadPoolExecutor(max_workers=config.max_workers)
        self.task_queue = asyncio.Queue(maxsize=config.queue_size)
        self.result_queue = asyncio.Queue(maxsize=config.queue_size)
        self.running_tasks = set()
        self._shutdown = False
        
        # Performance metrics
        self.metrics = {
            'tasks_completed': 0,
            'tasks_failed': 0,
            'avg_task_time': 0.0,
            'queue_size': 0,
            'active_workers': 0
        }
    
    async def submit_task(self, coro, *args, **kwargs):
        """Submit a task for parallel processing"""
        if self._shutdown:
            return None
        
        try:
            task = asyncio.create_task(coro(*args, **kwargs))
            self.running_tasks.add(task)
            task.add_done_callback(self.running_tasks.discard)
            return task
        except Exception as e:
            log.error(f"Error submitting task: {e}")
            return None
    
    async def submit_batch_tasks(self, tasks: List[Tuple[callable, tuple, dict]]) -> List[Any]:
        """Submit multiple tasks for parallel processing"""
        if self._shutdown:
            return []
        
        try:
            # Create tasks
            created_tasks = []
            for coro, args, kwargs in tasks:
                task = asyncio.create_task(coro(*args, **kwargs))
                self.running_tasks.add(task)
                task.add_done_callback(self.running_tasks.discard)
                created_tasks.append(task)
            
            # Wait for completion
            results = await asyncio.gather(*created_tasks, return_exceptions=True)
            
            # Update metrics
            self.metrics['tasks_completed'] += len([r for r in results if not isinstance(r, Exception)])
            self.metrics['tasks_failed'] += len([r for r in results if isinstance(r, Exception)])
            
            return results
            
        except Exception as e:
            log.error(f"Error submitting batch tasks: {e}")
            return []
    
    async def process_symbols_parallel(self, symbols: List[str], process_func, **kwargs) -> Dict[str, Any]:
        """Process multiple symbols in parallel"""
        if not symbols:
            return {}
        
        try:
            # Create tasks for each symbol
            tasks = [(process_func, (symbol,), kwargs) for symbol in symbols]
            
            # Process in batches
            results = {}
            for i in range(0, len(tasks), self.config.batch_size):
                batch = tasks[i:i + self.config.batch_size]
                batch_results = await self.submit_batch_tasks(batch)
                
                # Process results
                for j, result in enumerate(batch_results):
                    if not isinstance(result, Exception):
                        symbol = symbols[i + j]
                        results[symbol] = result
                    else:
                        log.error(f"Error processing symbol {symbols[i + j]}: {result}")
            
            return results
            
        except Exception as e:
            log.error(f"Error processing symbols in parallel: {e}")
            return {}
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        return {
            'tasks_completed': self.metrics['tasks_completed'],
            'tasks_failed': self.metrics['tasks_failed'],
            'avg_task_time': f"{self.metrics['avg_task_time']:.2f}ms",
            'queue_size': self.task_queue.qsize(),
            'active_workers': len(self.running_tasks),
            'success_rate': f"{(self.metrics['tasks_completed'] / max(self.metrics['tasks_completed'] + self.metrics['tasks_failed'], 1)) * 100:.2f}%"
        }
    
    async def shutdown(self):
        """Shutdown parallel processing manager"""
        self._shutdown = True
        
        # Cancel running tasks
        for task in self.running_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self.running_tasks:
            await asyncio.gather(*self.running_tasks, return_exceptions=True)
        
        # Shutdown thread pool
        self.thread_pool.shutdown(wait=True)
        log.info("✅ Parallel processing manager shutdown complete")

# ============================================================================
# MEMORY MANAGEMENT
# ============================================================================

class MemoryManager:
    """Manages memory usage and garbage collection"""
    
    def __init__(self, config: PerformanceConfig):
        self.config = config
        self.memory_threshold = config.max_memory_usage
        self.gc_counter = 0
        self.last_gc_time = time.time()
        
        # Memory tracking
        self.memory_usage = 0.0
        self.peak_memory = 0.0
        self.gc_count = 0
    
    def check_memory_usage(self) -> bool:
        """Check if memory usage exceeds threshold"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            self.memory_usage = memory_info.rss / (1024 * 1024 * 1024)  # GB
            
            if self.memory_usage > self.peak_memory:
                self.peak_memory = self.memory_usage
            
            return self.memory_usage > self.memory_threshold
            
        except ImportError:
            # psutil not available, skip memory checking
            return False
        except Exception as e:
            log.error(f"Error checking memory usage: {e}")
            return False
    
    def should_gc(self) -> bool:
        """Check if garbage collection should be performed"""
        self.gc_counter += 1
        return self.gc_counter >= self.config.gc_interval
    
    def perform_gc(self):
        """Perform garbage collection"""
        try:
            import gc
            gc.collect()
            self.gc_count += 1
            self.gc_counter = 0
            self.last_gc_time = time.time()
            log.debug(f"Garbage collection performed (count: {self.gc_count})")
        except Exception as e:
            log.error(f"Error performing garbage collection: {e}")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics"""
        return {
            'current_memory_gb': f"{self.memory_usage:.2f}",
            'peak_memory_gb': f"{self.peak_memory:.2f}",
            'gc_count': self.gc_count,
            'memory_threshold': f"{self.memory_threshold * 100:.1f}%"
        }

# ============================================================================
# OPTIMIZED TRADING SYSTEM
# ============================================================================

class PrimeTradingSystem:
    """High-performance Prime Trading System with parallel processing"""
    
    def __init__(self, config: TradingConfig = None):
        self.config = config or TradingConfig()
        self.parallel_manager = ParallelProcessingManager(PerformanceConfig())
        self.memory_manager = MemoryManager(PerformanceConfig())
        
        # System state
        self.running = False
        self.initialized = False
        self.last_update = time.time()
        # Ensure strategy_mode is properly set
        if hasattr(self.config, 'strategy_mode'):
            self.strategy_mode = self.config.strategy_mode
        else:
            self.strategy_mode = StrategyMode.STANDARD
        
        # Component references (will be set during initialization)
        self.data_manager = None
        self.market_manager = None  # ⭐ CRITICAL for timezone-aware market hours (Rev 00179)
        # ARCHIVED (Rev 00173): Legacy components no longer used
        # DELETED (Oct 20, 2025): signal_generator and symbol_selector removed - ORB handles both
        self.risk_manager = None
        self.trade_manager = None
        self.stealth_trailing = None
        self.alert_manager = None
        self.mock_executor = None
        
        # Alert deduplication
        self.last_symbol_selection_alert_time = 0
        self.last_signal_generated = {}  # Track last signal time per symbol
        
        # Performance tracking
        self.performance_metrics = {
            'main_loop_iterations': 0,
            'avg_loop_time': 0.0,
            'signals_generated': 0,
            'positions_updated': 0,
            'errors': 0,
            'start_time': None
        }
        
        # Daily markers / persistence
        self.daily_run_tracker = get_daily_run_tracker()
        self._daily_markers_applied = False
    
    async def initialize(self, components: Dict[str, Any]):
        """Initialize the optimized trading system with components"""
        try:
            # Initialize components if not provided
            if not components.get('data_manager'):
                from .prime_data_manager import get_prime_data_manager
                # CRITICAL: Pass ETrade OAuth for real-time data (Rev 00180AE)
                etrade_oauth = components.get('etrade_oauth', None)
                self.data_manager = await get_prime_data_manager(etrade_oauth)
            
            # DELETED (Oct 20, 2025): Production signal generator removed - ORB manager generates signals directly
            #     self.signal_generator = get_enhanced_production_signal_generator()
            
            # Initialize Market Manager (CRITICAL for timezone-aware market hours)
            if not components.get('market_manager'):
                from .prime_market_manager import get_prime_market_manager
                self.market_manager = get_prime_market_manager()
                log.info("🕐 Market Manager initialized (timezone-aware market hours)")
            
            # Initialize ORB Strategy Manager (PRIMARY & ONLY STRATEGY)
            # Multi-strategy manager kept in module but not used in production
            from .prime_orb_strategy_manager import get_prime_orb_strategy_manager
            self.orb_strategy_manager = get_prime_orb_strategy_manager(self.data_manager)
            from .config_loader import get_config_value
            so_cutoff_str = get_config_value('SO_CUTOFF_TIME', '07:30')
            
            log.info("🎯 ORB Strategy Manager initialized")
            log.info(f"   - ORB Window: 6:30-6:45 AM PT (9:30-9:45 AM ET)")
            log.info(f"   - SO Window: 7:15-{so_cutoff_str} AM PT - Continuous scanning, batch execution at {so_cutoff_str} AM")
            log.info(f"   - ORR Window: DISABLED (0% allocation)")
            log.info(f"   - Inverse ETFs: {len(self.orb_strategy_manager.inverse_mapping)}")
            log.info(f"   - Target Gain: 3% average (1-10% range)")
            
            # Initialize risk management based on mode
            if self.config.mode == SystemMode.DEMO_MODE:
                # Demo Mode: Use Demo Risk Manager
                if not components.get('risk_manager'):
                    from .prime_demo_risk_manager import get_prime_demo_risk_manager
                    self.risk_manager = get_prime_demo_risk_manager()
                    log.info("🎮 Demo Mode: Initialized Demo Risk Manager")
            else:
                # Live Mode: Use real Risk Manager with E*TRADE
                if not components.get('risk_manager'):
                    from .prime_risk_manager import get_prime_risk_manager
                    self.risk_manager = get_prime_risk_manager()
                    log.info("💰 Live Mode: Initialized Prime Risk Manager")
            
            # Initialize unified trade manager for BOTH modes
            if not components.get('trade_manager'):
                from .prime_unified_trade_manager import get_prime_unified_trade_manager
                self.trade_manager = get_prime_unified_trade_manager()
                mode_text = "Live" if self.config.mode == SystemMode.LIVE_MODE else "Demo"
                log.info(f"🎯 {mode_text} Mode: Initialized Unified Trade Manager")
            
            # Rev 00127: Initialize alert_manager BEFORE stealth_trailing so it can be passed correctly
            if not components.get('alert_manager'):
                from .prime_alert_manager import get_prime_alert_manager
                self.alert_manager = get_prime_alert_manager()
            
            # Initialize stealth trailing - MUST happen AFTER mock_executor AND alert_manager initialization
            # Will be re-initialized later with execution adapter
            if not components.get('stealth_trailing'):
                from .prime_stealth_trailing_tp import get_prime_stealth_trailing
                # Rev 00117: Pass alert_manager and mode for exit alerts
                # Rev 00127: alert_manager is now initialized before this point
                mode_str = "LIVE" if self.config.mode == SystemMode.LIVE_MODE else "DEMO"
                self.stealth_trailing = get_prime_stealth_trailing(alert_manager=self.alert_manager)
                self.stealth_trailing.mode = mode_str  # Set mode for alert display
                log.info(f"🛡️ Stealth Trailing System initialized ({mode_str} mode, execution adapter will be set later)")
            
            # ARCHIVED (Rev 00173): Symbol selector no longer used - ORB strategy uses static prioritized list
            # DELETED (Oct 20, 2025): Prime symbol selector removed - All symbols used in ORB strategy
            #     self.symbol_selector = PrimeSymbolSelector(self.data_manager)
            
            # Set component references (only if not already initialized)
            if not self.data_manager:
                self.data_manager = components.get('data_manager')
            if not self.market_manager:
                self.market_manager = components.get('market_manager')
            # DELETED (Oct 20, 2025): Signal generator removed - ORB manager handles all signals
            if not self.risk_manager:
                self.risk_manager = components.get('risk_manager')
            if not self.trade_manager:
                self.trade_manager = components.get('trade_manager')
            # Only set stealth_trailing from components if we don't already have one
            if not self.stealth_trailing:
                self.stealth_trailing = components.get('stealth_trailing')
            # Only set alert_manager from components if we don't already have one
            if not self.alert_manager:
                self.alert_manager = components.get('alert_manager')
            # ARCHIVED (Rev 00173): Symbol selector no longer used
            # self.symbol_selector = components.get('symbol_selector', self.symbol_selector)
            
            # Initialize mock trading executor for Demo Mode (after alert manager and risk manager)
            if not components.get('mock_executor') and self.alert_manager:
                # Rev 00107: Pass risk manager's compound engine to mock executor (single engine!)
                compound_engine_to_pass = None
                if hasattr(self, 'risk_manager') and hasattr(self.risk_manager, 'compound_engine'):
                    compound_engine_to_pass = self.risk_manager.compound_engine
                    log.info(f"✅ Passing compound engine from risk manager to mock executor (SINGLE ENGINE)")
                
                self.mock_executor = MockTradingExecutor(
                    alert_manager=self.alert_manager,
                    compound_engine=compound_engine_to_pass
                )
                log.info(f"✅ Mock Executor initialized (alert_manager: {self.alert_manager is not None}, compound_engine: {compound_engine_to_pass is not None})")
            elif components.get('mock_executor'):
                self.mock_executor = components.get('mock_executor')
                log.info(f"✅ Mock Executor received from components")
            
            # CRITICAL FIX (Rev 00180AE): Configure stealth trailing IMMEDIATELY after mock executor
            # This ensures exec adapter is available BEFORE any trading begins
            if hasattr(self, 'stealth_trailing') and self.stealth_trailing:
                if self.config.mode == SystemMode.DEMO_MODE and hasattr(self, 'mock_executor') and self.mock_executor:
                    # Demo Mode: Use MockExecutionAdapter
                    from .prime_stealth_trailing_tp import MockExecutionAdapter
                    self.stealth_trailing.exec = MockExecutionAdapter(self.mock_executor)
                    log.info("🛡️ Stealth Trailing configured with MockExecutionAdapter for Demo Mode")
                elif self.config.mode == SystemMode.LIVE_MODE and hasattr(self, 'trade_manager') and self.trade_manager:
                    # Live Mode: Use LiveETradeAdapter
                    from .prime_stealth_trailing_tp import LiveETradeAdapter
                    # Get ETrade client from trade manager
                    etrade_client = getattr(self.trade_manager, 'etrade_trading', None)
                    if etrade_client:
                        self.stealth_trailing.exec = LiveETradeAdapter(etrade_client)
                        log.info("🛡️ Stealth Trailing configured with LiveETradeAdapter for Live Mode")
                    else:
                        log.warning("⚠️ ETrade client not found in trade_manager - stealth trailing execution disabled")
            
            # Initialize market manager
            if not hasattr(self, 'market_manager') or not self.market_manager:
                from .prime_market_manager import get_prime_market_manager
                self.market_manager = get_prime_market_manager()
            
            # Rev 00046: Initialize ORR enabled flag based on capital allocation
            # This prevents ORR scanning when ORR is disabled (0% allocation)
            orr_reserve_pct = float(get_config_value('ORR_CAPITAL_PCT', 0))
            self._orr_enabled = (orr_reserve_pct > 0)
            orr_status = "ENABLED" if self._orr_enabled else "DISABLED"
            log.info(f"🎯 ORR Trading: {orr_status} (ORR_CAPITAL_PCT={orr_reserve_pct}%)")
            
            # Initialize alert manager and start EOD scheduler
            if self.alert_manager:
                await self.alert_manager.initialize()
                # Set mock executor reference for Demo Mode EOD reports
                if hasattr(self, 'mock_executor') and self.mock_executor:
                    self.alert_manager._mock_executor = self.mock_executor
                    log.info(f"✅ Alert Manager: Mock Executor reference set (instance: {id(self.mock_executor)})")
                # Rev 00180AE: Set unified trade manager reference for Live Mode EOD reports
                if hasattr(self, 'trade_manager') and self.trade_manager:
                    self.alert_manager._unified_trade_manager = self.trade_manager
                    log.info(f"✅ Alert Manager: Unified Trade Manager reference set for Live EOD")
                    log.info(f"   Instance ID: {id(self.trade_manager)}")
                
                # Rev 00047: DISABLE internal EOD scheduler - use Cloud Scheduler ONLY
                # This prevents 3 duplicate reports (internal scheduler + Cloud Scheduler + multiple instances)
                # Cloud Scheduler job "end-of-day-report" triggers /api/end-of-day-report at 4:05 PM ET
                # self.alert_manager.start_end_of_day_scheduler()  # DISABLED
                log.info("✅ EOD reporting configured - handled by Cloud Scheduler ONLY (internal scheduler disabled)")
            
            # Parallel processing is ready to use
            
            try:
                self._apply_daily_markers()
            except Exception as marker_error:
                log.warning(f"⚠️ Daily marker application failed: {marker_error}")
            
            self.initialized = True
            self.performance_metrics['start_time'] = time.time()
            log.info("✅ Optimized Prime Trading System initialized successfully (Rev 00173)")
            log.info(f"   Data Manager: {'✅' if self.data_manager else '❌'}")
            log.info(f"   ORB Strategy Manager: {'✅' if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager else '❌'} ⭐ PRIMARY")
            log.info(f"   Risk Manager: {'✅' if self.risk_manager else '❌'}")
            log.info(f"   Trade Manager: {'✅' if self.trade_manager else '❌'}")
            log.info(f"   Stealth Trailing: {'✅' if self.stealth_trailing else '❌'}")
            log.info(f"   Alert Manager: {'✅' if self.alert_manager else '❌'}")
            log.info(f"   Mock Executor: {'✅' if hasattr(self, 'mock_executor') and self.mock_executor else '❌'}")
            log.info(f"   ARCHIVED - Signal Generator: ❌ (ORB direct)")
            log.info(f"   ARCHIVED - Symbol Selector: ❌ (All symbols used)")
            
        except Exception as e:
            log.error(f"❌ Failed to initialize Optimized Prime Trading System: {e}")
            raise
    
    def _apply_daily_markers(self):
        """Load persisted daily markers to avoid duplicate ORB and SO tasks."""
        if getattr(self, "_daily_markers_applied", False):
            return
        
        try:
            state = self.daily_run_tracker.get_today_state() if hasattr(self, "daily_run_tracker") else {}
        except Exception as marker_error:
            log.warning(f"⚠️ Failed to load daily run markers: {marker_error}")
            self._daily_markers_applied = True
            return
        
        if not state:
            log.debug("🗒️ No daily run markers found for today (fresh session)")
            self._daily_markers_applied = True
            return
        
        utc_today = datetime.utcnow().date()
        
        # ------------------------------------------------------------------
        # ORB snapshot
        # ------------------------------------------------------------------
        orb_info = state.get("orb") or {}
        if orb_info.get("captured"):
            snapshot = orb_info.get("snapshot") or {}
            if snapshot and hasattr(self, "orb_strategy_manager") and self.orb_strategy_manager:
                try:
                    loaded = self.orb_strategy_manager.load_orb_snapshot(snapshot)
                    log.info(f"☁️ Loaded ORB snapshot from markers ({loaded} symbols)")
                except Exception as load_error:
                    log.warning(f"⚠️ Failed to apply ORB snapshot from markers: {load_error}")
            self._orb_captured_today = True
            # Rev 00198: Set alert flag when loading from markers to prevent duplicate alerts on restart
            # If ORB was already captured today (from markers), the alert was already sent
            # This prevents duplicate alerts when the application restarts after ORB capture
            self._orb_capture_alert_sent_today = True
            log.info(f"🔒 ORB capture alert already sent today (loaded from markers) - skipping duplicate")
            self._orb_backfill_attempted = True
            self._last_orb_date = utc_today
        
        # ------------------------------------------------------------------
        # SO signal markers
        # ------------------------------------------------------------------
        signals_info = state.get("signals") or {}
        if signals_info.get("collected"):
            # Rev 00123: DO NOT set _so_collection_alert_sent_today when loading from markers
            # The alert should only be sent when signal collection actually happens, not when loading persisted state
            # This flag is set at line 1672 when the alert is actually sent
            # self._so_collection_alert_sent_today = True  # REMOVED - prevents alert from being sent
            self._pending_so_signals = []
            collection_epoch = signals_info.get("collection_epoch")
            if collection_epoch:
                self._so_signals_ready_time = collection_epoch
        
        if signals_info.get("execution_completed"):
            executed_signals = signals_info.get("executed_signals") or []
            rejected_signals = signals_info.get("rejected_signals") or []
            
            self._pending_so_signals = []
            self._send_so_execution_alert = False
            # Rev 00123: DO NOT set _so_alert_sent_today when loading from markers
            # The alert should only be sent when execution actually happens, not when loading persisted state
            # This flag is set when the execution alert is actually sent (in _process_orb_signals)
            # self._so_alert_sent_today = True  # REMOVED - prevents alert from being sent
            # self._so_no_signals_alert_sent_today = True  # REMOVED - prevents alert from being sent
            execution_epoch = signals_info.get("execution_epoch")
            self._so_execution_time = execution_epoch if execution_epoch else time.time()
            
            executed_symbols = {s.get("symbol") for s in executed_signals if s.get("symbol")}
            original_symbols = {s.get("original_symbol") for s in executed_signals if s.get("original_symbol")}
            
            if executed_symbols:
                if not hasattr(self, "_so_executed_symbols_today"):
                    self._so_executed_symbols_today = set()
                self._so_executed_symbols_today.update(executed_symbols)
                
                if hasattr(self, "orb_strategy_manager") and getattr(self.orb_strategy_manager, "executed_symbols_today", None) is not None:
                    self.orb_strategy_manager.executed_symbols_today.update(executed_symbols)
                    self.orb_strategy_manager.executed_symbols_today.update(original_symbols)
            
            log.info(
                "☁️ SO markers applied (executed=%s, rejected=%s)",
                len(executed_signals),
                len(rejected_signals),
            )
        
        self._daily_markers_applied = True
    
    async def start(self):
        """Start the optimized trading system with watchlist building and continuous scanning"""
        if not self.initialized:
            raise RuntimeError("System not initialized")
        
        if self.running:
            log.warning("Trading system already running")
            return
        
        self.running = True
        log.info("🚀 Starting Optimized Prime Trading System...")
        
        try:
            # Initialize watchlist and symbol management
            await self._initialize_watchlist_system()
            
            # Start main trading loop with watchlist scanning
            await self._main_trading_loop()
        except Exception as e:
            log.error(f"Error in main trading loop: {e}")
            self.performance_metrics['errors'] += 1
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the trading system"""
        if not self.running:
            return
        
        self.running = False
        log.info("🛑 Stopping Optimized Prime Trading System...")
        
        try:
            # Stop EOD scheduler (Rev 00047 - No longer used)
            # if self.alert_manager:
            #     self.alert_manager.stop_end_of_day_scheduler()
            #     log.info("✅ EOD scheduler stopped")
            log.debug("EOD reporting via Cloud Scheduler - no internal scheduler to stop")
            
            # Close data manager connections
            if self.data_manager:
                await self.data_manager.close()
                log.info("✅ Data manager connections closed")
            
            # Shutdown parallel processing
            await self.parallel_manager.shutdown()
            
            # Final performance report
            self._log_performance_report()
            
            log.info("✅ Optimized Prime Trading System stopped successfully")
            
        except Exception as e:
            log.error(f"Error stopping trading system: {e}")
    
    async def shutdown(self):
        """Shutdown the trading system"""
        await self.stop()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system metrics"""
        return {
            'system_metrics': {
                'running': self.running,
                'initialized': self.initialized,
                'uptime_hours': (time.time() - self.performance_metrics['start_time']) / 3600 if self.performance_metrics['start_time'] else 0,
                'errors': self.performance_metrics['errors'],
                'main_loop_iterations': self.performance_metrics['main_loop_iterations'],
                'avg_loop_time': self.performance_metrics['avg_loop_time']
            },
            'trading_metrics': {
                'signals_generated': self.performance_metrics['signals_generated'],
                'positions_updated': self.performance_metrics['positions_updated'],
                'active_positions': len(self.active_positions) if hasattr(self, 'active_positions') else 0
            },
            'scanner_metrics': {
                'scans_completed': 0,  # Placeholder
                'symbols_processed': 0  # Placeholder
            },
            'current_phase': 'ACTIVE' if self.running else 'STOPPED',
            'running': self.running
        }
    
    async def _initialize_watchlist_system(self):
        """Initialize watchlist building and symbol management system"""
        try:
            log.info("📋 Initializing watchlist and symbol management system...")
            
            # Import watchlist building components
            from .prime_market_manager import get_prime_market_manager
            self.market_manager = get_prime_market_manager()
            
            # Rev 00180c: Use core_list.csv ONLY (no legacy lists)
            # Static list with 65 elite symbols, tier-ranked
            log.info("🚀 Rev 00180c: Using core_list.csv ONLY (no legacy lists)")
            log.info("📋 Loading core_list.csv (65 elite symbols, tier-ranked)...")
            await self._load_existing_watchlist()
            
            if not hasattr(self, 'symbol_list') or not self.symbol_list:
                log.warning("⚠️ No symbols loaded, using core_list.csv as fallback")
                await self._load_existing_watchlist()
            else:
                log.info(f"✅ Watchlist loaded with {len(self.symbol_list)} symbols")
            
            log.info("✅ Watchlist system initialized successfully")
            
        except Exception as e:
            log.error(f"❌ Failed to initialize watchlist system: {e}")
            raise
    
    async def _check_watchlist_freshness(self) -> bool:
        """
        Check if watchlist was built today
        Syncs from GCS first to get latest version across container restarts
        """
        try:
            import os
            from datetime import timezone
            # Rev 00125: datetime already imported at top of file - removed redundant local import
            
            watchlist_path = "data/watchlist/dynamic_watchlist.csv"
            
            # CRITICAL: Sync from GCS FIRST before checking freshness
            # This ensures we get the latest watchlist even after container restarts
            try:
                from .gcs_persistence import get_gcs_persistence
                gcs = get_gcs_persistence()
                
                # Check GCS file age first
                gcs_age_hours = gcs.get_file_age_hours("watchlist/dynamic_watchlist.csv")
                
                if gcs_age_hours is not None and gcs_age_hours < 24:
                    # Download fresh file from GCS
                    gcs_synced = gcs.download_file(
                        "watchlist/dynamic_watchlist.csv",
                        watchlist_path
                    )
                    if gcs_synced:
                        log.info(f"☁️ Synced watchlist from GCS ({gcs_age_hours:.1f}h old)")
                else:
                    log.debug(f"📭 No fresh watchlist in GCS (age: {gcs_age_hours}h)" if gcs_age_hours else "📭 No watchlist in GCS")
                    
            except Exception as gcs_error:
                log.warning(f"⚠️ GCS sync failed (non-critical): {gcs_error}")
            
            # Now check local file freshness
            if not os.path.exists(watchlist_path):
                log.warning("⚠️ Watchlist file doesn't exist - needs to be built")
                return False
            
            # Get file modification time
            mod_time = os.path.getmtime(watchlist_path)
            mod_datetime = datetime.fromtimestamp(mod_time, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            
            # Check if watchlist was modified today
            if mod_datetime.date() == now.date():
                log.info(f"✅ Watchlist is fresh (built today at {mod_datetime.strftime('%H:%M:%S')} UTC)")
                return True
            else:
                log.warning(f"⚠️ Watchlist is stale (last built {mod_datetime.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
                return False
                
        except Exception as e:
            log.error(f"Error checking watchlist freshness: {e}")
            return False
    
    async def _check_and_build_watchlist(self):
        """Check if watchlist needs to be built and rebuild if stale or missing"""
        try:
            # Use the new ensure_fresh_watchlist method
            await self.ensure_fresh_watchlist()
                
        except Exception as e:
            log.error(f"Error checking watchlist build time: {e}")
    
    async def _build_dynamic_watchlist(self):
        """
        ARCHIVED (Rev 00173): Build the dynamic watchlist for trading
        
        This method is NO LONGER CALLED in production. The ORB strategy uses
        a static prioritized_core_list.csv loaded at startup.
        
        Preserved for historical reference only.
        """
        try:
            log.info("📊 Building dynamic watchlist...")
            
            # Import and run watchlist builder
            import subprocess
            import os
            
            # Run the watchlist builder script
            watchlist_script = "build_dynamic_watchlist.py"
            if os.path.exists(watchlist_script):
                result = subprocess.run(
                    ["python3", watchlist_script], 
                    capture_output=True, 
                    text=True, 
                    timeout=300
                )
                
                if result.returncode == 0:
                    log.info("✅ Dynamic watchlist built successfully")
                    log.info(f"Output: {result.stdout}")
                    
                    # Send watchlist created alert
                    if self.alert_manager:
                        try:
                            # Count symbols in the built watchlist
                            watchlist_path = "data/watchlist/dynamic_watchlist.csv"
                            if os.path.exists(watchlist_path):
                                import pandas as pd
                                df = pd.read_csv(watchlist_path, comment='#')  # Rev 00180Q: Skip comment lines
                                symbol_count = len(df)
                                
                                await self.alert_manager.send_watchlist_created_alert(
                                    symbol_count=symbol_count,
                                    watchlist_type="daily"
                                )
                                log.info("📱 Watchlist created alert sent")
                        except Exception as alert_error:
                            log.error(f"Failed to send watchlist created alert: {alert_error}")
                else:
                    log.error(f"❌ Watchlist build failed: {result.stderr}")
            else:
                log.warning(f"⚠️ Watchlist script {watchlist_script} not found")
                
        except Exception as e:
            log.error(f"Error building dynamic watchlist: {e}")
    
    async def force_watchlist_rebuild(self):
        """
        Force rebuild the watchlist immediately, regardless of freshness
        
        Returns:
            bool: True if watchlist was built successfully
        """
        try:
            log.info("🔄 Force rebuilding watchlist...")
            await self._build_dynamic_watchlist()
            
            # Reload the watchlist after building (no alert, already sent in build)
            await self._load_existing_watchlist(send_alert=False)
            
            log.info("✅ Watchlist force rebuild completed")
            return True
            
        except Exception as e:
            log.error(f"Error force rebuilding watchlist: {e}")
            return False
    
    async def ensure_fresh_watchlist(self):
        """
        Ensure we have a fresh watchlist for today, building if necessary
        
        Returns:
            bool: True if watchlist is fresh or was built successfully
        """
        try:
            # Check if watchlist is fresh
            is_fresh = await self._check_watchlist_freshness()
            
            if is_fresh:
                log.info("✅ Watchlist is already fresh for today")
                return True
            
            # Watchlist is stale or missing - rebuild it
            log.warning("⚠️ Watchlist is stale or missing - rebuilding now...")
            await self._build_dynamic_watchlist()
            
            # Reload the watchlist after building (no alert, already sent in build)
            await self._load_existing_watchlist(send_alert=False)
            
            log.info("✅ Fresh watchlist ensured")
            return True
            
        except Exception as e:
            log.error(f"Error ensuring fresh watchlist: {e}")
            return False
    
    async def _load_existing_watchlist(self, send_alert: bool = True):
        """
        Load existing watchlist and use symbol selector to choose best symbols
        Syncs from GCS first to get latest version across container restarts
        
        Args:
            send_alert: Whether to send watchlist fetched alert (default: True)
        """
        try:
            import pandas as pd
            import os
            
            # ARCHIVED (Rev 00173): GCS sync for dynamic watchlist no longer used
            # ORB strategy uses static core_list.csv (no GCS sync needed)
            # try:
            #     from .gcs_persistence import get_gcs_persistence
            #     gcs = get_gcs_persistence()
            #     gcs_synced = gcs.sync_from_gcs(
            #         "watchlist/dynamic_watchlist.csv",
            #         "data/watchlist/dynamic_watchlist.csv",
            #         max_age_hours=24
            #     )
            #     if gcs_synced:
            #         log.info("☁️ Synced fresh watchlist from GCS")
            # except Exception as gcs_error:
            #     log.warning(f"⚠️ GCS sync failed (non-critical): {gcs_error}")
            
            log.debug("📋 Using static core_list.csv (no GCS sync needed)")
            
            # Rev 00180c: Use core_list.csv ONLY (no fallbacks)
            watchlist_files = [
                "data/watchlist/core_list.csv",              # ⭐ ONLY: 65 elite symbols with tier rankings - Rev 00180c
            ]
            
            daily_watchlist = []
            for file_path in watchlist_files:
                if os.path.exists(file_path):
                    # Rev 00180j: Skip comment lines starting with '#'
                    df = pd.read_csv(file_path, comment='#')
                    daily_watchlist = df['symbol'].tolist() if 'symbol' in df.columns else df.iloc[:, 0].tolist()
                    log.info(f"✅ Loaded {len(daily_watchlist)} symbols from: {file_path}")
                    
                    # ARCHIVED (Rev 00173): Watchlist fetched alert no longer sent
                    # ORB strategy uses static core_list.csv (no alert needed)
                    # if send_alert and self.alert_manager:
                    #     await self.alert_manager.send_watchlist_fetched_alert(
                    #         symbol_count=len(daily_watchlist),
                    #         watchlist_type="daily"
                    #     )
                    
                    log.debug("📋 ORB Strategy: Symbol list loaded (no alert sent)")
                    break
            
            if not daily_watchlist:
                # Fallback to default symbol list
                daily_watchlist = ["TQQQ", "SQQQ", "UPRO", "SPXU", "SPXL", "SPXS", "QQQ", "SPY", "AAPL", "TSLA"]
                log.warning(f"⚠️ Using fallback symbol list: {daily_watchlist}")
            
            # Use Prime Symbol Selector to intelligently select best symbols from daily watchlist
            # ONLY run during market hours to avoid after-hours alerts on container restarts
            # OPTIMIZATION: Skip deep analysis during initialization to avoid Yahoo rate limits
            is_market_open = await self._is_market_open()
            
            # Check if we have existing selected symbols from previous run
            import os
            from datetime import time as dt_time
            # Rev 00125: datetime already imported at top of file - removed redundant local import
            existing_selection_file = "data/watchlist/selected_symbols.csv"
            has_existing_selection = os.path.exists(existing_selection_file)
            
            # CRITICAL FIX: Skip deep symbol selection during initialization to avoid Yahoo rate limits
            # Deep symbol selection will run in the hourly update loop (not during startup)
            # This prevents 5-minute timeout and container restarts
            # Just use top 50 from watchlist during init
            
            # Rev 00173: SIMPLIFIED - Use ALL symbols from core_list.csv directly
            # No symbol selection needed - already pre-validated, prioritized, and proven profitable
            # This eliminates 2 minutes of startup time and 4 API calls
            
            self.symbol_list = daily_watchlist  # Use all symbols (84 from core_list.csv)
            log.info(f"✅ Using ALL {len(self.symbol_list)} symbols from Core List (tier-ranked)")
            log.info(f"   Pre-filtered with volatility, ATR, volume, and performance metrics")
            log.info(f"   Symbol List: {', '.join(self.symbol_list[:10])}{'...' if len(self.symbol_list) > 10 else ''}")
            
            # ARCHIVED (Rev 00173): Symbol selection alert no longer sent
            # ORB strategy uses all symbols from core_list.csv (no selection needed)
            # if self.alert_manager and is_market_open:
            #     await self.alert_manager.send_symbol_selection_alert(
            #         selected_symbols=self.symbol_list,
            #         total_analyzed=len(daily_watchlist)
            #     )
            
            log.debug("📋 ORB Strategy: All symbols ready for ORB capture (no selection alert)")
            
        except Exception as e:
            log.error(f"Error loading watchlist: {e}")
            # Fallback to default symbols
            self.symbol_list = ["TQQQ", "SQQQ", "UPRO", "SPXU", "SPXL", "SPXS", "QQQ", "SPY", "AAPL", "TSLA"]
    
    async def _update_symbol_selector(self):
        """
        ARCHIVED (Rev 00173): Update symbol selector with fresh analysis (ONCE DAILY)
        
        This method is NO LONGER CALLED in production. The ORB strategy uses
        all 84 symbols from prioritized_core_list.csv with no selection needed.
        
        Preserved for historical reference only.
        
        HISTORICAL NOTE (Oct 11, 2025):
        - Was called ONCE per day at 8:35 AM ET (after watchlist build)
        - Uses LIVE E*TRADE batch quotes (streaming: 4 batches of 25 symbols)
        - Identifies top 100 symbols trending UP for positive daily gains
        """
        try:
            # ARCHIVED (Rev 00173): Symbol selector no longer used
            log.debug("⏸️ Symbol selector update skipped (ORB strategy uses static core_list.csv)")
            return
            
            # if not self.symbol_selector:
            #     log.warning("⚠️ Symbol selector not available for update")
            #     return
            
            # Load fresh daily watchlist
            import pandas as pd
            import os
            
            daily_watchlist = []
            watchlist_files = [
                "data/watchlist/core_list.csv",           # ⭐ ONLY: 65 elite symbols (Rev 00180c)
            ]
            
            for file_path in watchlist_files:
                if os.path.exists(file_path):
                    df = pd.read_csv(file_path, comment='#')  # Rev 00180Q: Skip comment lines
                    daily_watchlist = df['symbol'].tolist() if 'symbol' in df.columns else df.iloc[:, 0].tolist()
                    log.info(f"🔄 Loaded {len(daily_watchlist)} symbols from daily watchlist for symbol selection")
                    break
            
            if not daily_watchlist:
                log.warning("⚠️ No daily watchlist available for symbol selection")
                return
            
            # ARCHIVED (Rev 00173): Symbol selector no longer used
            # self.symbol_selector.core_symbols = daily_watchlist
            # selection_result = await self.symbol_selector.select_with_live_etrade_data(...)
            
            log.debug(f"⏸️ Symbol selector update skipped (ORB uses all symbols from core_list.csv)")
            
            # ARCHIVED (Rev 00173): All symbol selection logic commented out
            # selection_result = None
            # 
            # import asyncio
            # try:
            #     selection_result = await asyncio.wait_for(
            #         self.symbol_selector.select_with_live_etrade_data(daily_watchlist, self.strategy_mode),
            #         timeout=180.0
            #     )
            # except asyncio.TimeoutError:
            #     log.warning(f"⏱️ Symbol selection timed out after 180 seconds")
            #     selection_result = None
            # except Exception as e:
            #     log.error(f"Error during daily symbol selection: {e}")
            #     selection_result = None
            # 
            # if selection_result and selection_result.selected_symbols:
            #     old_symbol_count = len(self.symbol_list) if hasattr(self, 'symbol_list') else 0
            #     self.symbol_list = [score.symbol for score in selection_result.selected_symbols]
            #     log.info(f"🔄 Symbol selector updated: {old_symbol_count} → {len(self.symbol_list)} symbols")
            #     await self.alert_manager.send_symbol_selection_alert(...)
            # else:
            #     log.warning("⚠️ Symbol selector update failed, keeping existing symbol list")
                
        except Exception as e:
            log.error(f"Error updating symbol selector: {e}")
    
    async def _refresh_adv_data_if_needed(self):
        """
        Refresh ADV data daily for Slip Guard (Rev 00046).
        
        Called once per day when date changes (before ORB capture).
        Fetches 90-day average volume for all symbols to enable
        position size capping at 1% ADV.
        """
        try:
            from .adv_data_manager import get_adv_manager
            
            adv_manager = get_adv_manager()
            
            # Check if Slip Guard is enabled
            if not adv_manager.enabled:
                log.debug("Slip Guard disabled - skipping ADV refresh")
                return
            
            # Check if data is fresh (<24 hours)
            if not adv_manager.is_data_stale(max_age_hours=24):
                age_hours = (datetime.utcnow() - adv_manager.last_refresh).total_seconds() / 3600 if adv_manager.last_refresh else 0  # Rev 00073: UTC consistency
                log.debug(f"ADV data is fresh ({age_hours:.1f}h old) - skipping refresh")
                return
            
            log.info("🛡️ SLIP GUARD: Refreshing ADV data for all symbols...")
            
            # Get symbols from symbol list
            symbols = self.symbol_list if hasattr(self, 'symbol_list') and self.symbol_list else []
            
            if not symbols:
                # Fallback: Load from core_list.csv
                import pandas as pd
                try:
                    df = pd.read_csv('data/watchlist/core_list.csv')
                    symbols = df['symbol'].tolist()
                    log.info(f"   Loaded {len(symbols)} symbols from core_list.csv")
                except Exception as e:
                    log.error(f"Failed to load symbols from core_list.csv: {e}")
                    return
            
            # Refresh ADV data (run in executor to avoid blocking event loop)
            await asyncio.get_event_loop().run_in_executor(
                None,
                adv_manager.refresh_adv_data,
                symbols
            )
            
            stats = adv_manager.get_stats()
            log.info(f"✅ SLIP GUARD: ADV refresh complete")
            log.info(f"   Symbols loaded: {stats['symbols_loaded']}")
            log.info(f"   ADV limit: {stats['adv_limit_pct']}% of ADV")
            
            if stats['data_age_hours']:
                log.info(f"   Data age: {stats['data_age_hours']:.1f} hours")
            
        except Exception as e:
            log.error(f"Error refreshing ADV data: {e}")
            log.warning("⚠️ Slip Guard will use cached ADV data (if available)")
    
    async def _main_trading_loop(self):
        """Enhanced main trading loop with watchlist scanning and Buy signal detection"""
        log.info("🔄 Starting enhanced main trading loop with watchlist scanning...")
        
        # Initialize symbol list for scanning
        if not hasattr(self, 'symbol_list'):
            await self._load_existing_watchlist()
        
        log.info(f"⭐ ORB STRATEGY ACTIVE (Rev 00173) ⭐")
        from .config_loader import get_config_value
        so_entry_str = get_config_value('SO_ENTRY_TIME', '07:15')
        so_cutoff_str = get_config_value('SO_CUTOFF_TIME', '07:30')
        window_minutes = (int(so_cutoff_str.split(':')[0]) * 60 + int(so_cutoff_str.split(':')[1])) - (int(so_entry_str.split(':')[0]) * 60 + int(so_entry_str.split(':')[1]))
        
        log.info(f"📋 Symbol List: {len(self.symbol_list)} symbols from core_list.csv")
        log.info(f"🎯 ORB Capture: 6:30-6:45 AM PT (9:30-9:45 AM ET)")
        log.info(f"🪽 SO Window: {so_entry_str}-{so_cutoff_str} AM PT ({window_minutes}-min collection, execute at {so_cutoff_str} AM)")
        log.info(f"🪽 ORR Window: DISABLED (0% allocation)")
        log.info(f"👁️ Position Monitoring: Every 30 seconds")
        log.info(f"📈 Symbols: {', '.join(self.symbol_list[:10])}{'...' if len(self.symbol_list) > 10 else ''}")
        log.info(f"❌ ARCHIVED: Dynamic watchlist, symbol selector, multi-strategy, signal generator")
        
        # ========== IMMEDIATE ORB BACKFILL ON STARTUP (Rev 00181) ==========
        # If system starts after ORB window (6:45 AM PT) and ORB data is missing, capture immediately
        # This ensures ORB capture happens even if system starts late (e.g., after Good Morning alert)
        if (hasattr(self, 'orb_strategy_manager') and 
            self.orb_strategy_manager and
            not hasattr(self, '_orb_captured_today')):
            self._orb_captured_today = False
        
        if (hasattr(self, 'orb_strategy_manager') and 
            self.orb_strategy_manager and
            not self._orb_captured_today):
            
            current_pt_time = self.orb_strategy_manager._get_current_time_pt()
            from datetime import time as dt_time
            orb_end_time = dt_time(6, 45, 0)
            
            # Check if we're past ORB window and have no ORB data
            if current_pt_time > orb_end_time:
                orb_count = len(self.orb_strategy_manager.orb_data) if hasattr(self.orb_strategy_manager, 'orb_data') else 0
                
                if orb_count == 0:
                    log.warning(f"⚠️ System started after ORB window (current: {current_pt_time.strftime('%H:%M:%S')} PT, ORB window ended: 06:45:00 PT)")
                    log.warning(f"⚠️ ORB data missing - IMMEDIATELY BACKFILLING from today's market data...")
                    await self._capture_orb_for_all_symbols()
                    self._orb_captured_today = True
                    log.info(f"✅ IMMEDIATE ORB BACKFILL COMPLETE: {len(self.orb_strategy_manager.orb_data)} symbols captured from today's OHLC")
                else:
                    log.info(f"✅ ORB data already exists ({orb_count} symbols) - no backfill needed")
                    self._orb_captured_today = True
        
        # Track last scan times for different intervals
        last_watchlist_scan_time = 0
        last_position_monitor_time = 0
        watchlist_scan_interval = 120  # 2 minutes = 120 seconds (NEW signal scanning)
        position_monitor_interval = 30  # 30 seconds (OPEN position monitoring - E*TRADE batch efficiency)
        # REMOVED: symbol_selector_interval - Now runs ONCE daily after watchlist build (not hourly)
        
        while self.running:
            loop_start = time.time()
            
            try:
                # ========== CLOSE ALL POSITIONS (12:55 PM PT / 3:55 PM ET) ==========
                # Rev 20251020: Close all open positions 5 minutes before market close
                if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager and self.stealth_trailing:
                    current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                    from datetime import time as dt_time
                    
                    # Check if it's 12:55 PM PT (5 min before market close at 1:00 PM PT / 4:00 PM ET)
                    eod_close_start = dt_time(12, 55, 0)  # 12:55 PM PT
                    eod_close_end = dt_time(12, 56, 0)  # 1-minute window
                    
                    if eod_close_start <= current_pt_time < eod_close_end:
                        if not hasattr(self, '_eod_positions_closed_today'):
                            self._eod_positions_closed_today = False
                        
                        if not self._eod_positions_closed_today:
                            log.info(f"🏁 END OF DAY CLOSE (12:55 PM PT) - Closing all open positions")
                            
                            # Get all active positions from stealth trailing
                            active_positions = list(self.stealth_trailing.active_positions.keys())
                            
                            # Rev 00121: Also check orphaned positions tracker
                            if hasattr(self, '_orphaned_positions_to_monitor'):
                                for symbol in self._orphaned_positions_to_monitor.keys():
                                    if symbol not in active_positions:
                                        active_positions.append(symbol)
                                        log.info(f"   📋 Found orphaned position in tracker: {symbol}")
                            
                            # CRITICAL FIX (Oct 24, 2025): Also check mock_executor for Demo Mode
                            # Some positions may be in mock_executor but not in stealth trailing (if they failed to add)
                            if self.config.mode == SystemMode.DEMO_MODE and self.mock_executor:
                                mock_positions = list(self.mock_executor.active_trades.keys())
                                # Add any mock positions that aren't already in stealth trailing
                                for symbol in mock_positions:
                                    if symbol not in active_positions:
                                        trade_id = symbol  # The key is the trade_id
                                        mock_trade = self.mock_executor.active_trades.get(trade_id)
                                        if mock_trade and hasattr(mock_trade, 'symbol'):
                                            if mock_trade.symbol not in active_positions:
                                                active_positions.append(mock_trade.symbol)
                                                log.info(f"   📋 Found orphaned Demo position: {mock_trade.symbol} (in mock_executor but not stealth)")
                            
                            if active_positions:
                                log.info(f"📊 Closing {len(active_positions)} open positions before market close")
                                
                                # Rev 00076: Use batch close for aggregated alert
                                if self.config.mode == SystemMode.DEMO_MODE and self.mock_executor:
                                    # Get all position states from stealth trailing
                                    positions_to_close = []
                                    orphaned_to_close = []
                                    for symbol in active_positions:
                                        position = self.stealth_trailing.active_positions.get(symbol)
                                        if position:
                                            positions_to_close.append(position)
                                        elif hasattr(self, '_orphaned_positions_to_monitor') and symbol in self._orphaned_positions_to_monitor:
                                            # Track orphaned positions for separate closing
                                            orphaned_to_close.append(symbol)
                                    
                                    # Close all positions in batch (sends ONE aggregated alert)
                                    if positions_to_close:
                                        await self.mock_executor.close_positions_batch(
                                            positions=positions_to_close,
                                            exit_reason="End of Day Close"
                                        )
                                        
                                        # Clear all positions from stealth trailing (prevents duplicate alerts)
                                        await self.stealth_trailing.emergency_clear_all_positions("End of Day Close")
                                        
                                        log.info(f"✅ Batch closed {len(positions_to_close)} positions at EOD")
                                    
                                    # Rev 00121: Close orphaned positions
                                    if orphaned_to_close:
                                        for symbol in orphaned_to_close:
                                            orphan_data = self._orphaned_positions_to_monitor.get(symbol)
                                            if orphan_data:
                                                trade = orphan_data['trade']
                                                exit_price = trade.current_price
                                                pnl = (exit_price - trade.entry_price) * trade.quantity
                                                await self.mock_executor.close_position_with_data(
                                                    symbol=symbol,
                                                    exit_price=exit_price,
                                                    exit_reason="End of Day Close",
                                                    pnl=pnl
                                                )
                                                log.info(f"✅ Closed orphaned position {symbol} at EOD")
                                                # Remove from orphaned tracker
                                                self._orphaned_positions_to_monitor.pop(symbol, None)
                                        
                                        log.info(f"✅ Closed {len(orphaned_to_close)} orphaned positions at EOD")
                                else:
                                    # Live Mode or fallback: close individually
                                    for symbol in active_positions:
                                        try:
                                            position = self.stealth_trailing.active_positions.get(symbol)
                                            if position:
                                                # Close via execution adapter
                                                if hasattr(self.stealth_trailing, 'exec') and self.stealth_trailing.exec:
                                                    await self.stealth_trailing.exec.close_position(position, "End of Day Close")
                                                    log.info(f"   ✅ Closed {symbol} (End of Day Close)")
                                                
                                                # Remove from active positions
                                                from .prime_stealth_trailing_tp import ExitReason
                                                await self.stealth_trailing._remove_position(symbol, ExitReason.END_OF_DAY_CLOSE, send_alert=False)
                                        except Exception as close_error:
                                            log.error(f"Failed to close {symbol} at EOD: {close_error}")
                                
                                # Rev 00170: Flush exit monitoring data after EOD close
                                if hasattr(self, 'stealth_trailing') and self.stealth_trailing and hasattr(self.stealth_trailing, 'exit_monitor') and self.stealth_trailing.exit_monitor:
                                    try:
                                        self.stealth_trailing.exit_monitor.flush_all()
                                        log.info("✅ Exit monitoring data flushed after EOD close")
                                    except Exception as flush_error:
                                        log.warning(f"⚠️ Failed to flush exit monitoring data after EOD close: {flush_error}")
                                
                                self._eod_positions_closed_today = True
                                log.info(f"✅ All positions closed at EOD (12:55 PM PT)")
                            else:
                                log.info(f"ℹ️ No open positions to close at EOD")
                                # Rev 00170: Still flush exit monitoring data even if no positions to close
                                if hasattr(self, 'stealth_trailing') and self.stealth_trailing and hasattr(self.stealth_trailing, 'exit_monitor') and self.stealth_trailing.exit_monitor:
                                    try:
                                        self.stealth_trailing.exit_monitor.flush_all()
                                        log.info("✅ Exit monitoring data flushed at EOD (no positions to close)")
                                    except Exception as flush_error:
                                        log.warning(f"⚠️ Failed to flush exit monitoring data at EOD: {flush_error}")
                                self._eod_positions_closed_today = True
                            
                            # Rev 00206: Close all 0DTE options positions at EOD (12:55 PM PT)
                            if hasattr(self, 'dte0_manager') and self.dte0_manager:
                                if hasattr(self.dte0_manager, 'options_executor') and self.dte0_manager.options_executor:
                                    try:
                                        options_executor = self.dte0_manager.options_executor
                                        open_options_positions = options_executor.get_open_positions()
                                        
                                        if open_options_positions:
                                            log.info(f"🏁 END OF DAY CLOSE (12:55 PM PT) - Closing {len(open_options_positions)} open 0DTE options positions")
                                            closed_positions = await options_executor.close_all_positions(reason="EOD_CLOSE")
                                            if closed_positions:
                                                log.info(f"✅ Closed {len(closed_positions)} 0DTE options positions at EOD")
                                            else:
                                                log.warning(f"⚠️ Failed to close some 0DTE options positions at EOD")
                                        else:
                                            log.info(f"ℹ️ No open 0DTE options positions to close at EOD")
                                    except Exception as options_eod_error:
                                        log.error(f"❌ Error closing 0DTE options positions at EOD: {options_eod_error}", exc_info=True)
                
                # ========== END OF DAY REPORT (1:00 PM PT / 4:00 PM ET) ==========
                # Rev 20251020: Send at market close (AFTER positions closed, BEFORE loop exits)
                # Rev 00092 (Nov 1, 2025): CRITICAL FIX - Only send on trading days (Mon-Fri market open)
                if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager and self.alert_manager:
                    current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                    from datetime import time as dt_time
                    
                    # Check if it's 1:00 PM PT (market close at 4:00 PM ET)
                    eod_time_start = dt_time(13, 0, 0)  # 1:00 PM PT
                    eod_time_end = dt_time(13, 1, 0)  # 1-minute window
                    
                    # current_pt_time is already a time object from _get_current_time_pt()
                    if eod_time_start <= current_pt_time < eod_time_end:
                        if not hasattr(self, '_eod_report_sent_today'):
                            self._eod_report_sent_today = False
                        
                        if not self._eod_report_sent_today:
                            # Rev 00092: CRITICAL - Check if it's a trading day BEFORE sending EOD report
                            # EOD reports should only send Mon-Fri when market is actually open
                            from datetime import date
                            today = date.today()
                            
                            # Check if weekend
                            is_weekend = today.weekday() >= 5  # Saturday=5, Sunday=6
                            
                            # Check if holiday
                            from .dynamic_holiday_calculator import should_skip_trading
                            should_skip, skip_reason, holiday_name = should_skip_trading(today)
                            
                            if is_weekend:
                                log.info(f"📅 Weekend ({today.strftime('%A')}) - Skipping EOD report")
                            elif should_skip:
                                log.info(f"📅 Holiday ({holiday_name}) - Skipping EOD report")
                            else:
                                # Normal trading day - send EOD report
                                log.info(f"📊 END OF DAY REPORT TIME (1:00 PM PT / 4:00 PM ET) - Sending EOD summary")
                                
                                # Rev 00133: Flush exit monitoring data before EOD report (TEMPORARY - for exit optimization)
                                if hasattr(self, 'stealth_trailing') and self.stealth_trailing and hasattr(self.stealth_trailing, 'exit_monitor') and self.stealth_trailing.exit_monitor:
                                    try:
                                        self.stealth_trailing.exit_monitor.flush_all()
                                        log.info("✅ Exit monitoring data flushed to GCS")
                                    except Exception as flush_error:
                                        log.warning(f"⚠️ Failed to flush exit monitoring data: {flush_error}")
                                
                                # Send Demo Mode EOD report
                                if self.config.mode == SystemMode.DEMO_MODE and hasattr(self, 'mock_executor') and self.mock_executor:
                                    try:
                                        await self.alert_manager._send_demo_eod_summary()
                                        self._eod_report_sent_today = True
                                        log.info(f"✅ Demo Mode EOD report sent")
                                    except Exception as eod_error:
                                        log.error(f"Failed to send Demo EOD report: {eod_error}")
                                
                                # Send Live Mode EOD report
                                elif self.config.mode == SystemMode.LIVE_MODE and hasattr(self, 'trade_manager') and self.trade_manager:
                                    try:
                                        await self.alert_manager._send_live_eod_summary()
                                        self._eod_report_sent_today = True
                                        log.info(f"✅ Live Mode EOD report sent")
                                    except Exception as eod_error:
                                        log.error(f"Failed to send Live EOD report: {eod_error}")
                                
                                # Send 0DTE Options EOD report (Rev 00206)
                                if hasattr(self, 'dte0_manager') and self.dte0_manager:
                                    if hasattr(self.dte0_manager, 'options_executor') and self.dte0_manager.options_executor:
                                        try:
                                            options_executor = self.dte0_manager.options_executor
                                            
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
                                            await self.alert_manager.send_options_end_of_day_report(
                                                daily_stats=daily_stats,
                                                weekly_stats=weekly_stats,
                                                all_time_stats=all_time_stats,
                                                account_balance=account_balance,
                                                starting_balance=starting_balance,
                                                mode=mode
                                            )
                                            log.info(f"✅ Options EOD report sent ({mode} Mode)")
                                        except Exception as options_eod_error:
                                            log.error(f"Failed to send Options EOD report: {options_eod_error}", exc_info=True)
                
                # ========== GOOD MORNING ALERT (5:30 AM PT / 8:30 AM ET) ==========
                # Rev 20251020: Internal scheduler for Good Morning alert (replaces Cloud Scheduler dependency)
                # CRITICAL FIX (Rev 20251020-2): Moved BEFORE market check so it sends when market closed
                if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager and self.alert_manager:
                    current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                    from datetime import time as dt_time
                    
                    # Check if it's 5:30 AM PT (1 hour before market open)
                    morning_alert_time = dt_time(5, 30, 0)
                    morning_alert_end = dt_time(5, 31, 0)  # 1-minute window
                    
                    # current_pt_time is already a time object from _get_current_time_pt()
                    if morning_alert_time <= current_pt_time < morning_alert_end:
                        if not hasattr(self, '_morning_alert_sent_today'):
                            self._morning_alert_sent_today = False
                        
                        # Rev 00066: Good Morning alert now sent ONLY by Cloud Scheduler (oauth-market-open-alert job)
                        # Removed duplicate from trading loop to prevent double alerts
                        # Rev 00087: Check for holidays FIRST, send holiday alert instead if needed
                        if not self._morning_alert_sent_today:
                            # Normal trading day - Cloud Scheduler handles morning alert
                            log.info(f"🌅 Good Morning alert time (5:30 AM PT) - Handled by Cloud Scheduler")
                            self._morning_alert_sent_today = True
                
                # Rev 00087: Check for holidays at the start of each loop iteration
                # This ensures we skip trading on both bank holidays AND low-volume holidays
                # Rev 00139: FIX - Added proper daily reset by tracking the date
                from datetime import date
                today = date.today()
                
                if not hasattr(self, '_holiday_checked_date'):
                    self._holiday_checked_date = None
                    self._holiday_skip_today = False
                
                # Reset holiday check if it's a new day (critical fix for multi-day container uptime)
                if self._holiday_checked_date != today:
                    log.info(f"📅 New trading day detected: {today} (previous: {self._holiday_checked_date})")
                    self._holiday_checked_date = None  # Force re-check
                    self._holiday_skip_today = False
                
                # Check once per day
                if self._holiday_checked_date != today:
                    from .dynamic_holiday_calculator import should_skip_trading
                    
                    should_skip, skip_reason, holiday_name = should_skip_trading(today)
                    
                    if should_skip:
                        log.info(f"🎃 Holiday detected: {holiday_name} ({skip_reason}) - Trading disabled for today")
                        self._holiday_skip_today = True
                    else:
                        log.info(f"✅ Normal trading day: {today} - Trading enabled")
                        self._holiday_skip_today = False
                    
                    self._holiday_checked_date = today
                
                # Skip trading if today is a holiday
                if self._holiday_skip_today:
                    log.debug("🎃 Trading disabled today (holiday)")
                    await asyncio.sleep(60)  # Check every minute on holidays
                    continue
                
                # Check if market is open for trading
                if not await self._is_market_open():
                    # Market is closed - only run minimal monitoring
                    log.debug("🚫 Market is closed - running minimal monitoring only")
                    await asyncio.sleep(60)  # Check every minute when market is closed
                    continue
                
                # Check memory usage
                if self.memory_manager.check_memory_usage():
                    log.warning("High memory usage detected, performing garbage collection")
                    self.memory_manager.perform_gc()
                
                # Perform garbage collection if needed
                if self.memory_manager.should_gc():
                    self.memory_manager.perform_gc()
                
                current_time = time.time()
                
                # REMOVED: Hourly symbol selector update (Oct 11, 2025 optimization)
                # Symbol selection now runs ONCE daily at 8:35 AM ET after watchlist build
                # This eliminates 6 unnecessary hourly updates and improves data quality with live E*TRADE data
                
                # REMOVED (Rev 20251020-2): Good Morning Alert moved BEFORE market check (line 1148)
                # This ensures alert sends at 5:30 AM PT even when market is closed
                
                # ========== ORB CAPTURE TASK (6:30-6:45 AM PT / 9:30-9:45 AM ET) ==========
                # Reset ORB capture flag daily
                if not hasattr(self, '_orb_captured_today'):
                    self._orb_captured_today = False
                
                # Initialize _last_orb_date if not set
                if not hasattr(self, '_last_orb_date'):
                    self._last_orb_date = datetime.utcnow().date()  # Rev 00073: UTC consistency
                
                current_date = datetime.utcnow().date()  # Rev 00073: UTC consistency
                if self._last_orb_date != current_date:
                    self._orb_captured_today = False
                    self._orb_capture_alert_sent_today = False  # Rev 00181: Reset ORB capture alert flag daily
                    self._morning_alert_sent_today = False  # Rev 20251020: Reset morning alert flag
                    self._so_collection_alert_sent_today = False  # Rev 00048: Reset SO collection alert flag
                    self._so_alert_sent_today = False  # Rev 00181: Reset SO execution alert flag daily
                    self._so_no_signals_alert_sent_today = False  # Rev 00198: Reset SO no signals alert flag daily
                    self._red_day_filter_blocked = False  # Reset Red Day Filter blocked flag
                    self._eod_positions_closed_today = False  # Rev 20251020: Reset EOD position close flag
                    self._eod_report_sent_today = False  # Rev 20251020: Reset EOD report flag
                    self._zero_signals_alert_sent_today = False  # Rev 00198: Reset zero signals alert flag daily
                    self._prev_candle_prefetched_today = False  # Rev 20251023: Reset prefetch flag for SO window
                    self._holiday_checked_date = None  # Rev 00139: Reset holiday check for new day
                    self._holiday_skip_today = False  # Rev 00139: Reset holiday skip flag
                    self._last_orb_date = current_date
                    log.info(f"🔄 Daily reset complete for {current_date} - all flags cleared")
                    
                    # 🛡️ SLIP GUARD: Daily ADV refresh (Rev 00046)
                    # Refresh ADV data at 6:00 AM PT (before ORB capture at 6:30 AM)
                    await self._refresh_adv_data_if_needed()
                    
                    if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                        self.orb_strategy_manager.reset_daily()
                        log.info("🔄 ORB Strategy Manager reset for new trading day")
                    log.debug("🔄 Daily flags reset: ORB capture + SO collection alert")
                
                # Capture ORB during opening window (6:30-6:45 AM PT)
                # ENHANCED DIAGNOSTIC (Rev 00173): Added detailed logging for ORB capture troubleshooting
                if (hasattr(self, 'orb_strategy_manager') and 
                    self.orb_strategy_manager and
                    not self._orb_captured_today):
                    
                    current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                    orb_start = self.orb_strategy_manager.orb_window_start
                    orb_end = self.orb_strategy_manager.orb_window_end
                    
                    # ENHANCED DIAGNOSTIC: Log every minute during pre-market with full details
                    if current_pt_time.hour == 6 and current_pt_time.minute % 1 == 0:
                        log.info(f"⏰ ORB DIAGNOSTIC CHECK:")
                        log.info(f"   Current PT Time: {current_pt_time.strftime('%H:%M:%S')}")
                        log.info(f"   ORB Window: {orb_start} - {orb_end}")
                        log.info(f"   Past ORB End: {current_pt_time >= orb_end}")
                        log.info(f"   Already Captured: {self._orb_captured_today}")
                        log.info(f"   Symbol List: {len(self.symbol_list) if hasattr(self, 'symbol_list') else 0} symbols")
                        log.info(f"   Data Manager: {self.data_manager is not None}")
                        log.info(f"   Alert Manager: {self.alert_manager is not None}")
                    
                    # Rev 00180Q: Capture at END of ORB window (6:45 AM PT) for COMPLETE 15-min range
                    # This ensures we get the FULL first 15-minute high/low, not partial data
                    # Rev 00198: Additional check for existing ORB data to prevent duplicate captures on restart
                    orb_data_exists = (hasattr(self.orb_strategy_manager, 'orb_data') and 
                                     self.orb_strategy_manager.orb_data and 
                                     len(self.orb_strategy_manager.orb_data) > 0)
                    
                    if current_pt_time >= orb_end and not self._orb_captured_today and not orb_data_exists:
                        log.info(f"🎯 ⭐⭐⭐ ORB WINDOW CLOSED - CAPTURING COMPLETE RANGE ⭐⭐⭐")
                        log.info(f"   Time: {current_pt_time.strftime('%H:%M:%S')} PT (ORB window: {orb_start}-{orb_end})")
                        log.info(f"   Symbols to capture: {len(self.symbol_list)}")
                        log.info(f"   Calling _capture_orb_for_all_symbols()...")
                        await self._capture_orb_for_all_symbols()
                        self._orb_captured_today = True
                        log.info(f"✅ ORB CAPTURE COMPLETE: {len(self.orb_strategy_manager.orb_data)} symbols captured")
                        log.info(f"   Flag set: _orb_captured_today = True")
                        log.info(f"   ORB data now contains COMPLETE first 15-minute high/low for all symbols")
                    elif current_pt_time >= orb_end and (self._orb_captured_today or orb_data_exists):
                        log.info(f"🔒 ORB already captured today - skipping duplicate capture")
                        log.info(f"   _orb_captured_today: {self._orb_captured_today}")
                        log.info(f"   ORB data exists: {orb_data_exists} ({len(self.orb_strategy_manager.orb_data) if orb_data_exists else 0} symbols)")
                        if not self._orb_captured_today and orb_data_exists:
                            # If ORB data exists but flag wasn't set, set it now
                            self._orb_captured_today = True
                            log.info(f"   ✅ Flag set: _orb_captured_today = True (ORB data already exists)")
                
                # ========== PREVIOUS CANDLE PRE-FETCH (7:15:00 AM PT) ==========
                # Pre-fetch 7:00-7:15 AM PT candle data RIGHT at 7:15 AM for instant SO decisions
                # This ensures we have prev_candle_close and prev_candle_open ready immediately
                if not hasattr(self, '_prev_candle_prefetched_today'):
                    self._prev_candle_prefetched_today = False
                
                if (hasattr(self, 'orb_strategy_manager') and 
                    self.orb_strategy_manager and
                    not self._prev_candle_prefetched_today):
                    
                    current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                    from datetime import time as dt_time
                    
                    # Check if exactly at 7:15:00 AM PT (SO window opens)
                    # Rev 20251023: Expanded to entire SO window to handle late starts
                    # Rev 00053 (Oct 27, 2025): Read from config for optimization testing
                    from .config_loader import get_config_value
                    so_entry_str = get_config_value('SO_ENTRY_TIME', '07:15')
                    so_cutoff_str = get_config_value('SO_CUTOFF_TIME', '07:30')  # Optimized to 15-min window
                    
                    so_entry_hour, so_entry_min = map(int, so_entry_str.split(':'))
                    so_cutoff_hour, so_cutoff_min = map(int, so_cutoff_str.split(':'))
                    
                    so_entry_time = dt_time(so_entry_hour, so_entry_min, 0)
                    so_cutoff_time = dt_time(so_cutoff_hour, so_cutoff_min, 0)
                    
                    if so_entry_time <= current_pt_time <= so_cutoff_time:
                        log.info("⚡ SO WINDOW OPENED: Pre-fetching 7:00-7:15 AM PT candle data for all 100 symbols...")
                        await self._prefetch_previous_candle_data()
                        self._prev_candle_prefetched_today = True
                        log.info(f"✅ Previous candle data ready - SO validation can now execute instantly!")
                
                # ========== AUTO ORB BACKFILL (Rev 00180L) ==========
                # If ORB data is missing (system started mid-day), auto-capture using today's market data
                if not hasattr(self, '_orb_backfill_attempted'):
                    self._orb_backfill_attempted = False
                
                if (hasattr(self, 'orb_strategy_manager') and 
                    self.orb_strategy_manager and
                    not self._orb_backfill_attempted and
                    not self._orb_captured_today):
                    
                    # Check if we're past ORB window and have no ORB data
                    current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                    from datetime import time as dt_time
                    orb_end_time = dt_time(6, 45, 0)
                    
                    if current_pt_time > orb_end_time:
                        orb_count = len(self.orb_strategy_manager.orb_data) if hasattr(self.orb_strategy_manager, 'orb_data') else 0
                        
                        if orb_count == 0:
                            log.warning(f"⚠️ ORB data missing (system started mid-day) - AUTO-BACKFILLING from today's market data...")
                            await self._capture_orb_for_all_symbols()
                            self._orb_backfill_attempted = True
                            self._orb_captured_today = True
                            log.info(f"✅ AUTO ORB BACKFILL: {len(self.orb_strategy_manager.orb_data)} symbols captured from today's OHLC")
                        else:
                            log.info(f"✅ ORB data already exists ({orb_count} symbols) - skipping backfill")
                            self._orb_backfill_attempted = True
                
                # ========== ORB SIGNAL SCANNING (Time-Windowed - Rev 00180f) ==========
                # SO: Scan during 15-min window (7:15-7:30 AM PT) but execute each symbol ONCE
                # ORR: Continuous scanning 7:30 AM - 12:15 PM PT every 30 seconds
                if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                    within_so = self.orb_strategy_manager._is_within_so_window()
                    within_orr = self.orb_strategy_manager._is_within_orr_window()
                    
                    # Rev 00180f: Track executed SO symbols to prevent duplicates
                    if not hasattr(self, '_so_executed_symbols_today'):
                        self._so_executed_symbols_today = set()
                    
                    # Rev 00180Q: Validate ORB data exists before allowing SO/ORR trades
                    orb_data_count = len(self.orb_strategy_manager.orb_data) if hasattr(self.orb_strategy_manager, 'orb_data') else 0
                    
                    if orb_data_count == 0 and (within_so or within_orr):
                        log.warning(f"⚠️ No ORB data available - cannot generate SO/ORR signals")
                        log.warning(f"   ORB data required for SO/ORR validation - skipping scan")
                        # Skip scanning if no ORB data
                        within_so = False
                        within_orr = False
                    
                    # Rev 20251023: CONTINUOUS SCANNING with improved ranking
                    # Rev 00056: Scan every 30 seconds from 7:15-7:30 AM to capture best entry prices (15-min window)
                    # Improved ranking (leverage + category bonuses) ensures high-vol symbols (IONZ, RGTZ) rank #1-2
                    
                    # Determine if we should scan
                    should_scan_so = within_so  # Scan throughout entire SO window
                    
                    # Rev 00180AE: Skip ORR scanning when ORR is disabled (0% allocation)
                    orr_enabled = hasattr(self, '_orr_enabled') and self._orr_enabled
                    should_scan_orr = within_orr and not within_so and orr_enabled  # ORR only after SO window closes AND if enabled
                    
                    if should_scan_so or should_scan_orr:
                        # Rev 20251023: Continuous scanning for SO (better entry prices)
                        # Rev 00056: SO: Every 30 seconds 7:15-7:30 AM PT (15-min window, captures best entries)
                        # ORR: Every 30 seconds from 8:15 AM - 12:15 PM PT
                        scan_interval = 30  # Both scan every 30 seconds
                        
                        if current_time - last_watchlist_scan_time >= scan_interval:
                            window_type = "SO" if should_scan_so else "ORR"
                            log.info(f"🎯 {window_type} Window: Scanning {len(self.symbol_list)} symbols for ORB signals...")
                            
                            # Scan for ORB signals (SO or ORR) using ORB Strategy Manager
                            scan_result = await self._scan_orb_batch_signals()
                            
                            # Rev 20251023: No longer mark SO as complete - continuous scanning until 7:30 AM
                            # Rev 00056: This captures symbols that break above threshold at different times in 15-min window
                            if should_scan_so:
                                log.debug(f"✅ SO scan iteration complete - continuing to collect signals until 7:30 AM PT")
                            
                            if scan_result and scan_result.get('count', 0) > 0:
                                log.info(f"✅ {window_type} Scan: Found {scan_result['count']} signals")
                            else:
                                log.debug(f"📊 {window_type} Scan: No signals found")
                            
                            last_watchlist_scan_time = current_time
                    else:
                        # Outside ORB windows - position monitoring only (log every 5 min)
                        if current_time - last_watchlist_scan_time >= 300:
                            log.debug(f"⏸️ Outside ORB windows - position monitoring only (Next: SO 7:15 AM PT, ORR 8:15 AM-12:15 PM PT)")
                            last_watchlist_scan_time = current_time
                else:
                    # Fallback: ORB manager not initialized (shouldn't happen)
                    log.error("❌ ORB Strategy Manager not initialized!")
                
                # ========== SO BATCH EXECUTION (7:30 AM PT) ==========
                # Rev 00056: Execute pending SO signals at 7:30 AM PT (15-min collection window)
                # Rev 20251021: Send alert even for 0 signals case
                # Rev 00053 (Oct 27, 2025): Dynamic execution time based on SO_CUTOFF_TIME
                if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                    current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                    from datetime import time as dt_time
                    from .config_loader import get_config_value
                    
                    # Get SO cutoff time from config (execution happens at cutoff)
                    so_cutoff_str = get_config_value('SO_CUTOFF_TIME', '07:30')  # Default 7:30 AM PT
                    so_cutoff_hour, so_cutoff_min = map(int, so_cutoff_str.split(':'))
                    
                    # Check if it's execution time (at SO cutoff)
                    so_execution_start = dt_time(so_cutoff_hour, so_cutoff_min, 0)
                    so_execution_end = dt_time(so_cutoff_hour, so_cutoff_min + 1, 0)  # 1-minute window
                    
                    if so_execution_start <= current_pt_time < so_execution_end:
                        # Rev 20251021: Get pending signals (or empty list if none collected)
                        pending_signals = getattr(self, '_pending_so_signals', [])
                        log.info(f"🚀 SO BATCH EXECUTION TIME ({so_cutoff_str} AM PT) - {len(pending_signals)} signals collected")
                        
                        # Rev 00048: Send SO Signal Collection alert FIRST (before execution)
                        # Rev 20251021: ALWAYS send this alert (even for 0 signals case)
                        # Rev 00187: Fix condition to check flag value, not just existence
                        if self.alert_manager and not getattr(self, '_so_collection_alert_sent_today', False):
                            try:
                                from .config_loader import get_config_value
                                etrade_mode = get_config_value('ETRADE_MODE', 'sandbox')
                                mode_display = "LIVE" if etrade_mode == "prod" else "DEMO"
                                
                                # Get 0DTE ORB data and PROCESS SIGNALS for inclusion in alert (if available)
                                spx_data = None
                                qqq_data = None
                                spy_data = None
                                dte0_signals_qualified = None
                                dte0_signals_list = None

                                if hasattr(self, 'dte0_manager') and self.dte0_manager:
                                    log.info(f"✅ dte0_manager is available for 0DTE signal processing")
                                else:
                                    log.warning(f"⚠️ dte0_manager NOT available - 0DTE signals will show as 0")
                                    log.warning(f"   hasattr(self, 'dte0_manager'): {hasattr(self, 'dte0_manager')}")
                                    if hasattr(self, 'dte0_manager'):
                                        log.warning(f"   self.dte0_manager value: {self.dte0_manager}")

                                if hasattr(self, 'dte0_manager') and self.dte0_manager:
                                    try:
                                        # Get ORB data for display
                                        spx_qqq_spy_orb = self.dte0_manager.get_spx_qqq_spy_orb_data(self.orb_strategy_manager)
                                        
                                        # Try to get current prices for context
                                        current_prices = {}
                                        if hasattr(self, 'trade_manager') and self.trade_manager and hasattr(self.trade_manager, 'etrade_trading'):
                                            try:
                                                quotes = self.trade_manager.etrade_trading.get_quotes(['SPX', 'QQQ', 'SPY'])
                                                for quote in quotes:
                                                    symbol = getattr(quote, 'symbol', None) or getattr(quote, 'Symbol', None)
                                                    if symbol:
                                                        current_prices[symbol] = getattr(quote, 'last_price', None) or getattr(quote, 'LastPrice', None) or getattr(quote, 'last', None)
                                            except Exception as price_error:
                                                log.debug(f"Could not get current prices for Signal Collection alert: {price_error}")
                                        
                                        if spx_qqq_spy_orb['SPX']:
                                            orb = spx_qqq_spy_orb['SPX']
                                            current_price = current_prices.get('SPX', None)
                                            # Calculate orb_range_pct from orb_range and orb_low
                                            spx_orb_range_pct = (orb.orb_range / orb.orb_low * 100) if orb.orb_low > 0 else 0.0
                                            spx_data = {
                                                'orb_high': orb.orb_high,
                                                'orb_low': orb.orb_low,
                                                'orb_range_pct': spx_orb_range_pct,
                                                'current_price': current_price,
                                                'orb_open': orb.orb_open
                                            }
                                        if spx_qqq_spy_orb['QQQ']:
                                            orb = spx_qqq_spy_orb['QQQ']
                                            current_price = current_prices.get('QQQ', None)
                                            # Calculate orb_range_pct from orb_range and orb_low
                                            qqq_orb_range_pct = (orb.orb_range / orb.orb_low * 100) if orb.orb_low > 0 else 0.0
                                            qqq_data = {
                                                'orb_high': orb.orb_high,
                                                'orb_low': orb.orb_low,
                                                'orb_range_pct': qqq_orb_range_pct,
                                                'current_price': current_price,
                                                'orb_open': orb.orb_open
                                            }
                                        if spx_qqq_spy_orb['SPY']:
                                            orb = spx_qqq_spy_orb['SPY']
                                            current_price = current_prices.get('SPY', None)
                                            # Calculate orb_range_pct from orb_range and orb_low
                                            spy_orb_range_pct = (orb.orb_range / orb.orb_low * 100) if orb.orb_low > 0 else 0.0
                                            spy_data = {
                                                'orb_high': orb.orb_high,
                                                'orb_low': orb.orb_low,
                                                'orb_range_pct': spy_orb_range_pct,
                                                'current_price': current_price,
                                                'orb_open': orb.orb_open
                                            }

                                                        # CRITICAL: Process 0DTE signals NOW (before SO alert) so final approved trades are known
                                        log.info(f"🎯 Processing 0DTE signals for {len(pending_signals)} ORB signals BEFORE SO alert...")
                                        log.info(f"   dte0_manager available: {self.dte0_manager is not None}")
                                        log.info(f"   dte0_manager type: {type(self.dte0_manager).__name__ if self.dte0_manager else 'None'}")
                                        dte0_signals = await self.dte0_manager.listen_to_orb_signals(
                                            pending_signals,
                                            orb_strategy_manager=self.orb_strategy_manager
                                        )
                                        log.info(f"   listen_to_orb_signals returned: {len(dte0_signals) if dte0_signals else 0} signals (type: {type(dte0_signals).__name__})")

                                        if dte0_signals:
                                            log.info(f"✅ 0DTE Strategy qualified {len(dte0_signals)} options signals for execution")
                                            for signal in dte0_signals:
                                                log.info(f"   - {signal.symbol} {signal.option_type_label}: Score {signal.eligibility_result.eligibility_score:.2f}, Delta {signal.target_delta:.2f}, Width ${signal.spread_width:.0f}")
                                            dte0_signals_qualified = len(dte0_signals)
                                            dte0_signals_list = []
                                            
                                            # Rev 00229: Pre-validate Hard Gate for alert display
                                            # Use module-level datetime import (line 17)
                                            current_time = datetime.now()
                                            hard_gated_symbols = []
                                            
                                            for signal in dte0_signals:
                                                # Pre-validate Hard Gate to show status in alert
                                                is_valid, reason = self.dte0_manager.validate_hard_gate(
                                                    signal=signal,
                                                    current_time=current_time,
                                                    max_allowed_spread_pct=5.0,
                                                    volume_multiplier=1.0
                                                )
                                                
                                                if not is_valid:
                                                    hard_gated_symbols.append({
                                                        'symbol': signal.symbol,
                                                        'reason': reason
                                                    })
                                                
                                                dte0_signals_list.append({
                                                    'symbol': signal.symbol,
                                                    'direction': signal.direction,  # Rev 00220: Add direction (LONG/SHORT)
                                                    'option_type': signal.option_type,
                                                    'option_type_label': signal.option_type_label,  # Rev 00220: Add option type label
                                                    'eligibility_score': signal.eligibility_result.eligibility_score,
                                                    'target_delta': signal.target_delta,
                                                    'spread_width': signal.spread_width,
                                                    'spread_type': getattr(signal, 'spread_type', 'debit'),
                                                    'momentum_score': getattr(signal, 'momentum_score', 0.0),  # Rev 00229: Add momentum score
                                                    'strategy_type': getattr(signal, 'strategy_type', 'debit_spread'),  # Rev 00229: Add strategy type
                                                    'hard_gate_passed': is_valid,  # Rev 00229: Add Hard Gate status
                                                    'hard_gate_reason': reason if not is_valid else None  # Rev 00229: Add Hard Gate reason
                                                })
                                            # Store for execution later
                                            self._pending_dte0_signals = dte0_signals
                                        else:
                                            log.info("ℹ️ 0DTE Strategy: No signals qualified for options trading")
                                            dte0_signals_qualified = 0
                                            dte0_signals_list = []
                                            self._pending_dte0_signals = []

                                    except Exception as e:
                                        import traceback
                                        error_trace = traceback.format_exc()
                                        log.error(f"❌ ERROR: Could not process 0DTE signals for SO alert: {e}")
                                        log.error(f"   Error details: {error_trace}")
                                        log.error(f"   ORB signals count: {len(pending_signals) if pending_signals else 0}")
                                        log.error(f"   dte0_manager available: {hasattr(self, 'dte0_manager') and self.dte0_manager is not None}")
                                        dte0_signals_qualified = 0
                                        dte0_signals_list = []
                                        self._pending_dte0_signals = []

                                # Rev 00221: Load 0DTE symbol list for alert display
                                dte_symbols_for_alert = []
                                try:
                                    import pandas as pd
                                    import os
                                    dte_list_path = "data/watchlist/0dte_list.csv"
                                    if os.path.exists(dte_list_path):
                                        df = pd.read_csv(dte_list_path, comment='#')
                                        dte_symbols_for_alert = df['symbol'].tolist() if 'symbol' in df.columns else df.iloc[:, 0].tolist()
                                except Exception as e:
                                    log.warning(f"Could not load 0DTE symbol list for alert: {e}")
                                
                                # Rev 00229: Extract Hard Gated symbols for alert
                                hard_gated_symbols = []
                                if dte0_signals_list:
                                    for signal in dte0_signals_list:
                                        if not signal.get('hard_gate_passed', True):
                                            hard_gated_symbols.append({
                                                'symbol': signal.get('symbol', 'UNKNOWN'),
                                                'reason': signal.get('hard_gate_reason', 'Hard Gate failed')
                                            })
                                
                                await self.alert_manager.send_so_signal_collection(
                                    so_signals=pending_signals,  # Can be empty list
                                    total_scanned=len(self.symbol_list) if hasattr(self, 'symbol_list') else 103,
                                    mode=mode_display,
                                    spx_orb_data=spx_data,
                                    qqq_orb_data=qqq_data,
                                    spy_orb_data=spy_data,
                                    dte0_signals_qualified=dte0_signals_qualified,
                                    dte0_signals_list=dte0_signals_list,
                                    dte_symbols_list=dte_symbols_for_alert,  # Rev 00221: Pass complete 0DTE symbol list
                                    hard_gated_symbols=hard_gated_symbols  # Rev 00229: Pass Hard Gated symbols
                                )
                                self._so_collection_alert_sent_today = True
                                log.info(f"📱 SO Signal Collection alert sent: {len(pending_signals)} signals collected from entire window")
                            except Exception as alert_error:
                                log.error(f"Failed to send SO signal collection alert: {alert_error}")
                            
                            if hasattr(self, 'daily_run_tracker') and self.daily_run_tracker:
                                try:
                                    metadata = {
                                        "window": "SO",
                                        "service": os.getenv("K_SERVICE"),
                                        "revision": os.getenv("K_REVISION"),
                                    }
                                    self.daily_run_tracker.record_signal_collection(
                                        signals=pending_signals,
                                        total_scanned=len(self.symbol_list) if hasattr(self, 'symbol_list') else 0,
                                        mode=mode_display,
                                        metadata=metadata,
                                    )
                                except Exception as tracker_error:
                                    log.warning(f"⚠️ Failed to persist signal collection marker: {tracker_error}")
                        
                        # Only execute if there are signals
                        # Rev 00094 (Nov 3, 2025): CRITICAL FIX - Check correct executor for Demo vs Live mode
                        # Bug: Was checking self.trade_manager (Live mode only), but Demo mode uses self.mock_executor
                        # This prevented ALL trade execution in Demo mode despite signals being collected
                        executor = self.mock_executor if self.config.mode == SystemMode.DEMO_MODE else self.trade_manager
                        mode_name = "DEMO" if self.config.mode == SystemMode.DEMO_MODE else "LIVE"
                        
                        if pending_signals and executor:
                            # Set flag to enable SO execution alert (sent by _process_orb_signals)
                            self._send_so_execution_alert = True
                            log.info(f"🚀 Now executing {len(pending_signals)} SO signals ({mode_name} MODE)...")
                            await self._process_orb_signals(pending_signals)
                            log.info(f"✅ SO batch execution complete at 7:30 AM PT ({mode_name} MODE)")
                            
                            # Mark execution time for 15-min health check
                            self._so_execution_time = time.time()
                        elif not pending_signals:
                            log.info(f"ℹ️ No SO signals to execute (0 signals collected)")
                            if hasattr(self, 'daily_run_tracker') and self.daily_run_tracker:
                                try:
                                    metadata = {
                                        "window": "SO",
                                        "service": os.getenv("K_SERVICE"),
                                        "revision": os.getenv("K_REVISION"),
                                        "note": "No signals collected",
                                    }
                                    self.daily_run_tracker.record_signal_execution(
                                        executed_signals=[],
                                        rejected_signals=[],
                                        mode=mode_display,
                                        metadata=metadata,
                                    )
                                except Exception as tracker_error:
                                    log.warning(f"⚠️ Failed to persist zero-signal execution marker: {tracker_error}")
                        else:
                            log.error(f"❌ Executor not available for SO batch execution ({mode_name} MODE)!")
                            log.error(f"   Config mode: {self.config.mode}")
                            log.error(f"   Mock executor: {self.mock_executor is not None}")
                            log.error(f"   Trade manager: {self.trade_manager is not None}")
                        
                        # Clear pending signals
                        if hasattr(self, '_pending_so_signals'):
                            self._pending_so_signals = []
                        
                        # ========== 0DTE OPTIONS EXECUTION (After ORB Execution) ==========
                        # Execute 0DTE options trades if signals were qualified and Red Day was not detected
                        if hasattr(self, 'dte0_manager') and self.dte0_manager:
                            try:
                                # Check if Red Day filter blocked execution
                                red_day_blocked = getattr(self, '_red_day_filter_blocked', False)
                                
                                if red_day_blocked:
                                    log.warning("🚨 RED DAY DETECTED - 0DTE Options Execution SKIPPED")
                                    log.warning("   ⚠️ Red Day filter blocking options trading to preserve capital")
                                    # Clear pending 0DTE signals if Red Day detected
                                    if hasattr(self, '_pending_dte0_signals'):
                                        self._pending_dte0_signals = []
                                else:
                                    # Check for pending 0DTE signals (processed before SO alert)
                                    if hasattr(self, '_pending_dte0_signals') and self._pending_dte0_signals:
                                        dte0_signals = self._pending_dte0_signals
                                        log.info(f"🎯 Executing {len(dte0_signals)} 0DTE options signals after ORB execution...")
                                        
                                        # Verify Options Chain Manager and Executor are available
                                        if hasattr(self.dte0_manager, 'options_chain_manager') and hasattr(self.dte0_manager, 'options_executor'):
                                            if self.dte0_manager.options_chain_manager and self.dte0_manager.options_executor:
                                                await self._execute_0dte_options_trades(dte0_signals)
                                                log.info(f"✅ 0DTE options execution complete")
                                            else:
                                                log.warning("⚠️ 0DTE Options Chain Manager or Executor not initialized - skipping execution")
                                        else:
                                            log.warning("⚠️ 0DTE Options Chain Manager or Executor not available - skipping execution")
                                        
                                        # Clear pending 0DTE signals after execution
                                        self._pending_dte0_signals = []
                                    else:
                                        log.info("ℹ️ No pending 0DTE signals to execute")
                            except Exception as e:
                                log.error(f"❌ Error executing 0DTE options trades: {e}", exc_info=True)
                                # Clear pending signals on error to prevent retry
                                if hasattr(self, '_pending_dte0_signals'):
                                    self._pending_dte0_signals = []
                
                # NOTE: EOD report moved BEFORE market hours check (lines 1067-1103) to ensure it runs at 1:05 PM
                
                # ========== 15-MINUTE PORTFOLIO HEALTH CHECK (8:00 AM PT) ==========
                # Rev 00044: Detect bad days 15 minutes after SO execution
                # ========== CONTINUOUS PORTFOLIO HEALTH CHECK (Rev 00067 - EVERY 15 MINUTES) ==========
                # Check portfolio health EVERY 15 minutes throughout trading day
                # Emergency exit if portfolio shows 3+ red flags
                if (hasattr(self, '_so_execution_time') and 
                    hasattr(self, 'stealth_trailing') and self.stealth_trailing and
                    hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager):
                    
                    # Initialize last health check time if not exists
                    if not hasattr(self, '_last_health_check_time'):
                        self._last_health_check_time = 0
                    
                    # Run health check EVERY 15 MINUTES (900 seconds)
                    health_check_interval = 900  # 15 minutes in seconds
                    
                    if current_time - self._last_health_check_time >= health_check_interval:
                        # Only run during market hours (7:30 AM - 12:55 PM PT)
                        current_pt_time = self.orb_strategy_manager._get_current_time_pt()
                        market_hours_start = dt_time(7, 30, 0)
                        market_hours_end = dt_time(12, 55, 0)
                        
                        if market_hours_start <= current_pt_time < market_hours_end:
                            log.info(f"🛡️ PORTFOLIO HEALTH CHECK (Every 15 min - {current_pt_time.strftime('%I:%M %p')} PT)")
                            
                            # Update last check time
                            self._last_health_check_time = current_time
                            
                            # Check portfolio health
                            health_result = self.stealth_trailing.check_portfolio_health_for_emergency_exit()
                            
                            if health_result['action'] == 'CLOSE_ALL':
                                # EMERGENCY: Close all positions
                                log.error(f"🚨 EMERGENCY EXIT TRIGGERED:")
                                for flag in health_result['red_flags']:
                                    log.error(f"   ❌ {flag}")
                                
                                # Rev 00076: Use batch close for aggregated alert
                                if self.config.mode == SystemMode.DEMO_MODE and self.mock_executor:
                                    # Get all position states from stealth trailing
                                    positions_to_close = []
                                    for symbol in health_result['positions_to_close']:
                                        position = self.stealth_trailing.active_positions.get(symbol)
                                        if position:
                                            positions_to_close.append(position)
                                    
                                    # Close all positions in batch (sends ONE aggregated alert)
                                    if positions_to_close:
                                        await self.mock_executor.close_positions_batch(
                                            positions=positions_to_close,
                                            exit_reason="Emergency Bad Day Detected"
                                        )
                                        
                                        # Clear all positions from stealth trailing (prevents duplicate alerts)
                                        await self.stealth_trailing.emergency_clear_all_positions("Emergency Bad Day Detected")
                                        
                                        log.error(f"🚨 Batch closed {len(positions_to_close)} positions (emergency)")
                                elif self.config.mode == SystemMode.LIVE_MODE and self.trade_manager:
                                    # Live Mode: close individually (Live mode alert system handles this)
                                    for symbol in health_result['positions_to_close']:
                                        try:
                                            await self.trade_manager.close_position(symbol, "EMERGENCY_BAD_DAY_DETECTED")
                                            log.error(f"   🚨 Closed {symbol} (emergency)")
                                        except Exception as e:
                                            log.error(f"Failed to emergency close {symbol}: {e}")
                                    
                                    # Clear all positions from stealth trailing (prevents duplicate alerts)
                                    await self.stealth_trailing.emergency_clear_all_positions("Emergency Bad Day Detected")
                                
                                # Send emergency alert
                                if self.alert_manager:
                                    try:
                                        from modules.prime_alert_manager import AlertLevel
                                        await self.alert_manager.send_telegram_alert(
                                            f"🚨 <b>BAD DAY DETECTED - EMERGENCY EXIT</b>\n\n"
                                            f"📊 <b>Red Flags:</b>\n" +
                                            '\n'.join([f"  ❌ {flag}" for flag in health_result['red_flags']]) +
                                            f"\n\n🛡️ <b>Action:</b> Closed {len(health_result['positions_to_close'])} positions\n"
                                            f"💰 Exited early to preserve capital\n\n"
                                            f"<i>Emergency system preventing larger losses</i>",
                                            AlertLevel.ERROR
                                        )
                                    except Exception as e:
                                        log.error(f"Failed to send emergency alert: {e}")
                            
                            elif health_result['action'] == 'CLOSE_WEAK':
                                # WARNING: Close weak positions only
                                log.warning(f"⚠️ WEAK DAY DETECTED:")
                                for flag in health_result['red_flags']:
                                    log.warning(f"   ⚠️ {flag}")
                                
                                # Rev 00078: Use batch close for aggregated alert
                                if self.config.mode == SystemMode.DEMO_MODE and self.mock_executor:
                                    # Get all weak position states from stealth trailing
                                    positions_to_close = []
                                    for symbol in health_result['positions_to_close']:
                                        position = self.stealth_trailing.active_positions.get(symbol)
                                        if position:
                                            positions_to_close.append(position)
                                    
                                    # Close all weak positions in batch (sends ONE aggregated alert)
                                    if positions_to_close:
                                        await self.mock_executor.close_positions_batch(
                                            positions=positions_to_close,
                                            exit_reason="Weak Day Early Exit"
                                        )
                                        
                                        # Clear all positions from stealth trailing (prevents duplicate alerts)
                                        await self.stealth_trailing.emergency_clear_all_positions("Weak Day Early Exit")
                                        
                                        log.warning(f"⚠️ Batch closed {len(positions_to_close)} weak positions")
                                elif self.config.mode == SystemMode.LIVE_MODE and self.trade_manager:
                                    # Live Mode: close individually (Live mode alert system handles this)
                                    for symbol in health_result['positions_to_close']:
                                        try:
                                            await self.trade_manager.close_position(symbol, "WEAK_DAY_EARLY_EXIT")
                                            log.warning(f"   ⚠️ Closed {symbol} (weak)")
                                        except Exception as e:
                                            log.error(f"Failed to close weak position {symbol}: {e}")
                                    
                                    # Clear all positions from stealth trailing (prevents duplicate alerts)
                                    await self.stealth_trailing.emergency_clear_all_positions("Weak Day Early Exit")
                                
                                # Send warning alert
                                if self.alert_manager:
                                    try:
                                        remaining = len(self.stealth_trailing.active_positions) - len(health_result['positions_to_close'])
                                        from modules.prime_alert_manager import AlertLevel
                                        await self.alert_manager.send_telegram_alert(
                                            f"⚠️ <b>WEAK DAY DETECTED</b>\n\n"
                                            f"📊 <b>Warnings:</b>\n" +
                                            '\n'.join([f"  ⚠️ {flag}" for flag in health_result['red_flags']]) +
                                            f"\n\n🛡️ <b>Action:</b> Closed {len(health_result['positions_to_close'])} weak positions\n"
                                            f"📊 <b>Remaining:</b> {remaining} positions monitored closely\n\n"
                                            f"<i>Trading cautiously due to weak conditions</i>",
                                            AlertLevel.WARNING
                                        )
                                    except Exception as e:
                                        log.error(f"Failed to send weak day alert: {e}")
                            
                            else:
                                # OK: Portfolio healthy
                                log.info(f"✅ HEALTH CHECK PASSED: Portfolio healthy (continues every 15 min)")
                
                # Check if 30 seconds have passed - monitor OPEN positions
                if current_time - last_position_monitor_time >= position_monitor_interval:
                    # Monitor 0DTE Options Positions (if enabled)
                    if hasattr(self, 'dte0_manager') and self.dte0_manager:
                        if hasattr(self.dte0_manager, 'options_executor') and self.dte0_manager.options_executor:
                            try:
                                # Get market data provider function
                                async def get_market_data(symbol: str) -> Dict[str, Any]:
                                    """Get market data for options position monitoring"""
                                    try:
                                        quote = await self.data_manager.get_quote(symbol)
                                        current_price = quote.get('last', quote.get('price', 0.0))
                                        
                                        # Get VWAP if available
                                        vwap = None
                                        if hasattr(self.data_manager, 'get_vwap'):
                                            try:
                                                vwap = await self.data_manager.get_vwap(symbol)
                                            except Exception:
                                                pass  # VWAP not available, continue without it
                                        
                                        # Calculate momentum from price change (simplified)
                                        # For better accuracy, would need historical prices
                                        prev_price = quote.get('previous_close', current_price)
                                        momentum = ((current_price - prev_price) / prev_price) if prev_price > 0 else 0.0
                                        
                                        # Get current options value
                                        # Note: For accurate options pricing, would need to fetch from options chain manager
                                        # For demo mode, using underlying price as proxy is acceptable
                                        # For live mode, should fetch actual options bid/ask from options chain
                                        current_value = current_price  # Underlying price proxy for demo mode
                                        
                                        # Estimate bid/ask spread (typical for liquid options: 0.5-2%)
                                        bid_ask_spread_pct = 0.01  # 1% default for liquid options
                                        
                                        return {
                                            'current_price': current_price,
                                            'current_value': current_value,  # Underlying price (demo mode proxy)
                                            'vwap': vwap,
                                            'bid_ask_spread_pct': bid_ask_spread_pct,
                                            'momentum': momentum  # Calculated from price change
                                        }
                                    except Exception as e:
                                        log.warning(f"Error getting market data for {symbol}: {e}")
                                        return {
                                            'current_price': 0.0,
                                            'current_value': 0.0,
                                            'vwap': None,
                                            'bid_ask_spread_pct': 0.0,
                                            'momentum': 0.0
                                        }
                                
                                # Get ORB data provider function
                                async def get_orb_data(symbol: str):
                                    """Get ORB data for options position monitoring"""
                                    try:
                                        if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                                            if symbol in self.orb_strategy_manager.orb_data:
                                                return self.orb_strategy_manager.orb_data[symbol]
                                    except Exception as e:
                                        log.warning(f"Error getting ORB data for {symbol}: {e}")
                                    return None
                                
                                # Monitor options positions
                                exit_signals = await self.dte0_manager.options_executor.monitor_positions(
                                    market_data_provider=get_market_data,
                                    orb_data_provider=get_orb_data
                                )
                                
                                # Execute exits for positions with exit signals
                                for exit_signal in exit_signals:
                                    log.warning(f"🚨 EXIT SIGNAL: {exit_signal.reason.value} for position {exit_signal.position_id}")
                                    log.warning(f"   P&L: {exit_signal.pnl_pct*100:.1f}% (${exit_signal.pnl_dollar:.2f})")
                                    
                                    # Execute exit
                                    closed_position = await self.dte0_manager.options_executor.execute_exit(exit_signal)
                                    
                                    if closed_position:
                                        log.info(f"✅ Options position {exit_signal.position_id} closed: {exit_signal.reason.value}")
                                        # Note: Exit alert is sent from options_executor.execute_exit() method
                                
                            except Exception as e:
                                log.error(f"❌ Error monitoring 0DTE options positions: {e}", exc_info=True)
                    
                    # BOTH Demo and Live use Stealth Trailing System (SINGLE SOURCE OF TRUTH)
                    if hasattr(self, 'stealth_trailing') and self.stealth_trailing:
                        # Get positions from stealth trailing (primary source of truth for BOTH modes)
                        stealth_positions = self.stealth_trailing.get_active_positions()
                        
                        # Rev 00122: CRITICAL FIX - Check for orphaned positions in BOTH Demo and Live modes
                        # Demo Mode: Check mock_executor for positions not in stealth trailing
                        # Live Mode: Sync from E*TRADE API to catch positions not in stealth trailing
                        
                        # Initialize orphaned positions tracker if not exists (persists across loop iterations)
                        if not hasattr(self, '_orphaned_positions_to_monitor'):
                            self._orphaned_positions_to_monitor = {}
                        
                        orphaned_symbols = []
                        orphaned_positions_to_monitor = self._orphaned_positions_to_monitor
                        
                        # Rev 00122: Live Mode - Sync positions from E*TRADE API
                        if self.config.mode == SystemMode.LIVE_MODE and self.trade_manager:
                            try:
                                # Get positions from E*TRADE API
                                if hasattr(self.trade_manager, 'etrade_trading') and self.trade_manager.etrade_trading:
                                    # Rev 00124: asyncio already imported at top of file - removed redundant local import
                                    portfolio = await asyncio.to_thread(self.trade_manager.etrade_trading.get_portfolio)
                                    
                                    if portfolio:
                                        for etrade_pos in portfolio:
                                            symbol = etrade_pos.symbol
                                            # Check if position is orphaned (in E*TRADE but not in stealth trailing)
                                            if symbol not in stealth_positions and etrade_pos.quantity > 0:
                                                orphaned_symbols.append(symbol)
                                                log.warning(f"⚠️ Found orphaned Live position: {symbol} (in E*TRADE portfolio but not stealth trailing)")
                                                
                                                # Try to add to stealth trailing
                                                try:
                                                    from .prime_models import PrimePosition, SignalSide
                                                    # Rev 00125: datetime already imported at top of file - removed redundant local import
                                                    
                                                    # Get current market data
                                                    if self.data_manager:
                                                        quote = await self.data_manager.get_batch_quotes([symbol])
                                                        if symbol in quote:
                                                            current_price = quote[symbol].get('last', quote[symbol].get('price', etrade_pos.last_price))
                                                            
                                                            # Create PrimePosition from E*TRADE position
                                                            position = PrimePosition(
                                                                position_id=f"ETRADE_{symbol}_{int(datetime.utcnow().timestamp())}",
                                                                symbol=symbol,
                                                                side=SignalSide.LONG,  # E*TRADE positions are typically long
                                                                quantity=etrade_pos.quantity,
                                                                entry_price=etrade_pos.average_price or current_price,
                                                                current_price=current_price,
                                                                entry_time=datetime.utcnow(),  # Use current time as fallback
                                                                stop_loss=None,  # Will be calculated by stealth trailing
                                                                take_profit=None  # Will be calculated by stealth trailing
                                                            )
                                                            
                                                            market_data = {
                                                                'price': current_price,
                                                                'atr': current_price * 0.02,
                                                                'volume_ratio': 1.0,
                                                                'entry_bar_high': current_price * 1.02,
                                                                'entry_bar_low': current_price * 0.98
                                                            }
                                                            
                                                            # Try to add to stealth trailing
                                                            added = await self.stealth_trailing.add_position(position, market_data)
                                                            if added:
                                                                log.info(f"✅ Successfully synced orphaned Live position {symbol} from E*TRADE API to stealth trailing")
                                                                # Refresh stealth_positions
                                                                stealth_positions = self.stealth_trailing.get_active_positions()
                                                            else:
                                                                log.warning(f"⚠️ Failed to sync orphaned Live position {symbol} - will monitor via E*TRADE API")
                                                                # Store for separate monitoring
                                                                orphaned_positions_to_monitor[symbol] = {
                                                                    'etrade_position': etrade_pos,
                                                                    'market_data': market_data
                                                                }
                                                        else:
                                                            log.warning(f"⚠️ No market data for orphaned Live position {symbol}")
                                                            orphaned_positions_to_monitor[symbol] = {
                                                                'etrade_position': etrade_pos,
                                                                'market_data': {'price': etrade_pos.last_price, 'atr': 0.0, 'volume_ratio': 1.0}
                                                            }
                                                except Exception as e:
                                                    log.error(f"❌ Error syncing orphaned Live position {symbol}: {e}")
                                                    # Store for separate monitoring even if sync fails
                                                    orphaned_positions_to_monitor[symbol] = {
                                                        'etrade_position': etrade_pos,
                                                        'market_data': {'price': etrade_pos.last_price, 'atr': 0.0, 'volume_ratio': 1.0}
                                                    }
                            except Exception as e:
                                log.error(f"❌ Error syncing Live positions from E*TRADE API: {e}")
                        
                        # Rev 00121: Demo Mode - Check mock_executor for orphaned positions
                        if self.config.mode == SystemMode.DEMO_MODE and self.mock_executor:
                            for trade_id, trade in self.mock_executor.active_trades.items():
                                if trade.status == TradeStatus.OPEN:
                                    symbol = trade.symbol
                                    # Check if position is orphaned (in mock_executor but not stealth trailing)
                                    if symbol not in stealth_positions:
                                        orphaned_symbols.append(symbol)
                                        log.warning(f"⚠️ Found orphaned Demo position: {symbol} (in mock_executor but not stealth trailing)")
                                        # Try to re-add to stealth trailing
                                        try:
                                            from .prime_models import PrimePosition
                                            position = PrimePosition(
                                                position_id=trade_id,
                                                symbol=symbol,
                                                side=trade.side,
                                                quantity=trade.quantity,
                                                entry_price=trade.entry_price,
                                                current_price=trade.current_price,
                                                entry_time=trade.timestamp,
                                                stop_loss=trade.stop_loss,
                                                take_profit=trade.take_profit
                                            )
                                            # Get market data for the symbol
                                            if self.data_manager:
                                                quote = await self.data_manager.get_batch_quotes([symbol])
                                                if symbol in quote:
                                                    market_data = {
                                                        'price': quote[symbol].get('last', quote[symbol].get('price', trade.current_price)),
                                                        'atr': quote[symbol].get('price', trade.current_price) * 0.02,
                                                        'volume_ratio': 1.0
                                                    }
                                                    # Try to re-add to stealth trailing
                                                    added = await self.stealth_trailing.add_position(position, market_data)
                                                    if added:
                                                        log.info(f"✅ Successfully re-added orphaned position {symbol} to stealth trailing")
                                                        # Refresh stealth_positions
                                                        stealth_positions = self.stealth_trailing.get_active_positions()
                                                        # Remove from orphaned list since it's now in stealth
                                                        orphaned_positions_to_monitor.pop(symbol, None)
                                                    else:
                                                        log.warning(f"⚠️ Failed to re-add orphaned position {symbol} to stealth trailing - will monitor via mock_executor")
                                                        # Store for separate monitoring
                                                        orphaned_positions_to_monitor[symbol] = {
                                                            'trade': trade,
                                                            'market_data': market_data
                                                        }
                                                else:
                                                    log.warning(f"⚠️ No market data for orphaned position {symbol} - will monitor via mock_executor")
                                                    orphaned_positions_to_monitor[symbol] = {
                                                        'trade': trade,
                                                        'market_data': {'price': trade.current_price, 'atr': 0.0, 'volume_ratio': 1.0}
                                                    }
                                        except Exception as e:
                                            log.error(f"❌ Error re-adding orphaned position {symbol}: {e}")
                                            # Store for separate monitoring even if re-add fails
                                            orphaned_positions_to_monitor[symbol] = {
                                                'trade': trade,
                                                'market_data': {'price': trade.current_price, 'atr': 0.0, 'volume_ratio': 1.0}
                                            }
                            
                            if orphaned_symbols:
                                mode_text = "Demo" if self.config.mode == SystemMode.DEMO_MODE else "Live"
                                log.warning(f"⚠️ Position Monitor: Found {len(orphaned_symbols)} orphaned {mode_text} positions: {orphaned_symbols}")
                                log.warning(f"⚠️ These positions will be monitored separately and closed at EOD if still open")
                        
                        # Rev 00121: DIAGNOSTIC - Log position count for troubleshooting (includes orphaned)
                        total_positions = len(stealth_positions) + len(orphaned_positions_to_monitor)
                        log.info(f"👁️ Position Monitor: Found {total_positions} active positions ({len(stealth_positions)} in stealth, {len(orphaned_positions_to_monitor)} orphaned)")
                        if stealth_positions:
                            log.info(f"   Stealth Symbols: {list(stealth_positions.keys())}")
                        if orphaned_positions_to_monitor:
                            log.info(f"   Orphaned Symbols: {list(orphaned_positions_to_monitor.keys())}")
                        if not stealth_positions and not orphaned_positions_to_monitor:
                            log.debug(f"   No active positions to monitor")
                        
                        if stealth_positions or orphaned_positions_to_monitor:
                            mode_text = "LIVE" if self.config.mode == SystemMode.LIVE_MODE else "DEMO"
                            total_positions = len(stealth_positions) + len(orphaned_positions_to_monitor)
                            log.debug(f"👁️ {mode_text} Mode: Monitoring {total_positions} positions ({len(stealth_positions)} in stealth, {len(orphaned_positions_to_monitor)} orphaned) - 30-sec interval")
                            
                            # CRITICAL FIX (Rev 00180): Update stealth trailing positions with current prices!
                            try:
                                # Get all symbols to monitor (stealth + orphaned)
                                all_symbols = list(stealth_positions.keys()) + list(orphaned_positions_to_monitor.keys())
                                
                                if all_symbols and self.data_manager:
                                    # Batch fetch current prices and market data
                                    batch_quotes = await self.data_manager.get_batch_quotes(all_symbols)
                                    
                                    if batch_quotes:
                                        # Update each position in stealth trailing
                                        for symbol in list(stealth_positions.keys()):
                                            if symbol in batch_quotes:
                                                quote = batch_quotes[symbol]
                                                current_price = quote.get('last', quote.get('price', 0.0))
                                                
                                                # Rev 00135: Enhanced market_data with comprehensive technical indicators for Exit Monitoring Collector
                                                # Try to get comprehensive technical indicators from data_manager or calculate basic ones
                                                market_data = {
                                                    'price': current_price,
                                                    'open': quote.get('open', current_price),
                                                    'high': quote.get('high', current_price),
                                                    'low': quote.get('low', current_price),
                                                    'volume': quote.get('volume', 0),
                                                    'volume_today': quote.get('volume', 0),
                                                    'open_price': quote.get('open', current_price),
                                                    'high_today': quote.get('high', current_price),
                                                    'low_today': quote.get('low', current_price),
                                                }
                                                
                                                # Rev 00141: Try to get comprehensive technical indicators if available
                                                try:
                                                    if hasattr(self, 'trade_manager') and self.trade_manager and hasattr(self.trade_manager, 'etrade_trading') and self.trade_manager.etrade_trading:
                                                        # Use E*TRADE trading system's comprehensive market data
                                                        comprehensive_data = self.trade_manager.etrade_trading.get_market_data_for_strategy(symbol)
                                                        if comprehensive_data and comprehensive_data.get('data_quality', 0) > 0:
                                                            # Extract technical indicators (only use if data quality is good)
                                                            market_data.update({
                                                                'rsi': comprehensive_data.get('rsi'),
                                                                'rsi_14': comprehensive_data.get('rsi_14', comprehensive_data.get('rsi')),
                                                                'macd': comprehensive_data.get('macd'),
                                                                'macd_signal': comprehensive_data.get('macd_signal'),
                                                                'macd_histogram': comprehensive_data.get('macd_histogram'),
                                                                'sma_20': comprehensive_data.get('sma_20'),
                                                                'sma_50': comprehensive_data.get('sma_50'),
                                                                'ema_12': comprehensive_data.get('ema_12'),
                                                                'ema_26': comprehensive_data.get('ema_26'),
                                                                'atr': comprehensive_data.get('atr'),
                                                                'bollinger_upper': comprehensive_data.get('bollinger_upper'),
                                                                'bollinger_middle': comprehensive_data.get('bollinger_middle'),
                                                                'bollinger_lower': comprehensive_data.get('bollinger_lower'),
                                                                'bollinger_width': comprehensive_data.get('bollinger_width'),
                                                                'bollinger_position': comprehensive_data.get('bollinger_position'),
                                                                'volatility': comprehensive_data.get('volatility'),
                                                                'volume_ratio': comprehensive_data.get('volume_ratio'),
                                                                'vwap': comprehensive_data.get('vwap'),
                                                                'vwap_distance_pct': comprehensive_data.get('vwap_distance_pct'),
                                                                'rs_vs_spy': comprehensive_data.get('rs_vs_spy'),
                                                                'spy_price': comprehensive_data.get('spy_price'),
                                                                'spy_change_pct': comprehensive_data.get('spy_change_pct'),
                                                                'momentum_10': comprehensive_data.get('momentum'),
                                                                'momentum': comprehensive_data.get('momentum')
                                                            })
                                                            log.debug(f"✅ Fetched comprehensive technicals for {symbol} (quality: {comprehensive_data.get('data_quality', 0)})")
                                                        else:
                                                            log.debug(f"⚠️ Comprehensive data for {symbol} has low quality or missing, using fallbacks")
                                                except Exception as tech_error:
                                                    log.debug(f"⚠️ Could not fetch comprehensive technicals for {symbol}: {tech_error}, using defaults")
                                                
                                                # Fallback to basic indicators if comprehensive data not available
                                                if 'rsi' not in market_data or market_data.get('rsi') is None:
                                                    market_data.update({
                                                        'rsi': 50.0,  # Default neutral RSI
                                                        'rsi_14': 50.0,
                                                        'atr': current_price * 0.02,  # Estimate 2% ATR
                                                        'volume_ratio': 1.0,
                                                        'momentum': 0.0,
                                                        'momentum_10': 0.0,
                                                        'volatility': 0.02
                                                    })
                                                
                                                # Rev 00146: Validate market data before position update
                                                if not market_data or 'price' not in market_data or market_data.get('price', 0) <= 0:
                                                    log.warning(f"⚠️ Invalid market data for {symbol}, skipping update (data: {market_data})")
                                                    continue
                                                
                                                # Update stealth trailing (will check ALL exit conditions)
                                                # Rev 00143: Enhanced error handling to prevent monitoring failures
                                                try:
                                                    await self.stealth_trailing.update_position(symbol, market_data)
                                                except Exception as update_error:
                                                    log.error(f"❌ Error updating position {symbol} in stealth trailing: {update_error}", exc_info=True)
                                                    # Continue monitoring other positions even if one fails
                                        
                                        # Rev 00122: Monitor orphaned positions separately (check exit conditions manually)
                                        # Handle both Demo (MockTrade) and Live (ETradePosition) orphaned positions
                                        for symbol, orphan_data in list(orphaned_positions_to_monitor.items()):
                                            if symbol in batch_quotes:
                                                quote = batch_quotes[symbol]
                                                current_price = quote.get('last', quote.get('price', 0.0))
                                                
                                                # Rev 00122: Handle Demo Mode orphaned positions
                                                if 'trade' in orphan_data:
                                                    trade = orphan_data['trade']
                                                    current_price = quote.get('last', quote.get('price', trade.current_price))
                                                    
                                                    # Update trade's current price
                                                    trade.current_price = current_price
                                                    
                                                    # Check exit conditions manually (stop loss, take profit, etc.)
                                                    # Check stop loss
                                                    if trade.stop_loss and current_price <= trade.stop_loss:
                                                        log.warning(f"🚨 Orphaned Demo position {symbol} hit stop loss: ${current_price:.2f} <= ${trade.stop_loss:.2f}")
                                                        # Close via mock executor
                                                        exit_price = current_price
                                                        pnl = (exit_price - trade.entry_price) * trade.quantity
                                                        await self.mock_executor.close_position_with_data(
                                                            symbol=symbol,
                                                            exit_price=exit_price,
                                                            exit_reason="stop_loss",
                                                            pnl=pnl
                                                        )
                                                        log.info(f"✅ Closed orphaned Demo position {symbol} via stop loss")
                                                        # Remove from orphaned list
                                                        orphaned_positions_to_monitor.pop(symbol, None)
                                                    
                                                    # Check take profit
                                                    elif trade.take_profit and current_price >= trade.take_profit:
                                                        log.info(f"🎯 Orphaned Demo position {symbol} hit take profit: ${current_price:.2f} >= ${trade.take_profit:.2f}")
                                                        # Close via mock executor
                                                        exit_price = current_price
                                                        pnl = (exit_price - trade.entry_price) * trade.quantity
                                                        await self.mock_executor.close_position_with_data(
                                                            symbol=symbol,
                                                            exit_price=exit_price,
                                                            exit_reason="take_profit",
                                                            pnl=pnl
                                                        )
                                                        log.info(f"✅ Closed orphaned Demo position {symbol} via take profit")
                                                        # Remove from orphaned list
                                                        orphaned_positions_to_monitor.pop(symbol, None)
                                                
                                                # Rev 00122: Handle Live Mode orphaned positions (monitor via E*TRADE API)
                                                elif 'etrade_position' in orphan_data:
                                                    etrade_pos = orphan_data['etrade_position']
                                                    # Update E*TRADE position price (if supported)
                                                    if hasattr(etrade_pos, 'last_price'):
                                                        etrade_pos.last_price = current_price
                                                    
                                                    # For Live mode, we rely on stealth trailing to handle exits
                                                    # But we can log the position status
                                                    log.debug(f"📊 Monitoring orphaned Live position {symbol} via E*TRADE API: "
                                                             f"Qty={etrade_pos.quantity}, Price=${current_price:.2f}")
                                                    
                                                    # Note: Live mode orphaned positions are monitored by stealth trailing
                                                    # once they're successfully synced. If sync fails, they remain in
                                                    # orphaned tracker and will be closed at EOD.
                                        
                                        log.debug(f"✅ Updated {len(stealth_positions)} stealth positions + {len(orphaned_positions_to_monitor)} orphaned positions ({mode_text} Mode)")
                                    else:
                                        log.warning(f"⚠️ No market quotes available for stealth updates")
                                else:
                                    log.warning(f"⚠️ No symbols or data_manager not available")
                            except Exception as e:
                                log.error(f"❌ Error updating stealth trailing: {e}")
                    else:
                        # Fallback: Stealth trailing not available (shouldn't happen after initialization)
                        log.error(f"❌ Stealth Trailing System not available for position monitoring!")
                    last_position_monitor_time = current_time
                
                # Update performance metrics
                self._update_performance_metrics(loop_start)
                
                # Calculate adaptive sleep interval based on market conditions
                sleep_interval = self._calculate_adaptive_sleep_interval()
                await asyncio.sleep(sleep_interval)
                
            except Exception as e:
                log.error(f"Error in main trading loop: {e}")
                self.performance_metrics['errors'] += 1
                await asyncio.sleep(1.0)  # Wait before retrying
    
    async def _run_enhanced_parallel_tasks(self):
        """Run enhanced parallel tasks with watchlist scanning and Buy signal detection"""
        try:
            # Create enhanced parallel tasks
            tasks = []
            
            # DEBUG: Check what components are available
            log.info(f"🔍 DEBUG - Component availability check (Rev 00173):")
            log.info(f"   - symbol_list: {hasattr(self, 'symbol_list')} (count: {len(self.symbol_list) if hasattr(self, 'symbol_list') else 0})")
            log.info(f"   - orb_strategy_manager: {self.orb_strategy_manager is not None if hasattr(self, 'orb_strategy_manager') else False} ⭐ PRIMARY")
            log.info(f"   - trade_manager: {self.trade_manager is not None if hasattr(self, 'trade_manager') else False}")
            log.info(f"   - ARCHIVED signal_generator: ❌ (ORB direct)")
            log.info(f"   - ARCHIVED symbol_selector: ❌ (All symbols used)")
            log.info(f"   - risk_manager: {self.risk_manager is not None if hasattr(self, 'risk_manager') else False}")
            
            # Watchlist scanning task (continuous scanning for Buy signals)
            if hasattr(self, 'symbol_list') and self.symbol_list:
                tasks.append(('scan_watchlist', self._scan_watchlist_for_signals, (), {}))
                log.info(f"✅ Added scan_watchlist task")
            else:
                log.warning(f"⚠️ No symbol_list available, skipping scan_watchlist task")
            
            # ARCHIVED (Rev 00173): Signal generation task no longer used
            # ORB strategy manager generates and validates signals directly
            log.debug("⏸️ Signal generation task skipped (ORB validates directly)")
            
            # Position update task
            if self.trade_manager and time.time() - self.last_update > self.config.position_update_interval:
                tasks.append(('update_positions', self._update_positions_task, (), {}))
            
            # Risk assessment task
            if self.risk_manager:
                tasks.append(('assess_risk', self._assess_risk_task, (), {}))
            
            # Stealth trailing task
            if self.stealth_trailing:
                tasks.append(('update_stealth', self._update_stealth_task, (), {}))
            
            # Execute tasks in parallel
            if tasks:
                task_names = [task[0] for task in tasks]
                task_coros = [task[1] for task in tasks]
                task_args = [task[2] for task in tasks]
                task_kwargs = [task[3] for task in tasks]
                
                # Create task tuples for parallel processing
                parallel_tasks = [(coro, args, kwargs) for coro, args, kwargs in zip(task_coros, task_args, task_kwargs)]
                
                # Execute in parallel
                results = await self.parallel_manager.submit_batch_tasks(parallel_tasks)
                
                # Process results
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        log.error(f"Error in {task_names[i]}: {result}")
                    else:
                        log.debug(f"Completed {task_names[i]} successfully")
                
                self.last_update = time.time()
                
        except Exception as e:
            log.error(f"Error running enhanced parallel tasks: {e}")
    
    async def _run_parallel_tasks(self):
        """Run parallel tasks for optimal performance"""
        try:
            # Create parallel tasks
            tasks = []
            
            # ARCHIVED (Rev 00173): Signal generation task no longer used
            # if self.signal_generator and time.time() - self.last_update > self.config.signal_generation_frequency:
            #     tasks.append(('generate_signals', self._generate_signals_task, (), {}))
            
            # Position update task
            if self.trade_manager and time.time() - self.last_update > self.config.position_update_interval:
                tasks.append(('update_positions', self._update_positions_task, (), {}))
            
            # Risk assessment task
            if self.risk_manager:
                tasks.append(('assess_risk', self._assess_risk_task, (), {}))
            
            # Stealth trailing task
            if self.stealth_trailing:
                tasks.append(('update_stealth', self._update_stealth_task, (), {}))
            
            # Execute tasks in parallel
            if tasks:
                task_names = [task[0] for task in tasks]
                task_coros = [task[1] for task in tasks]
                task_args = [task[2] for task in tasks]
                task_kwargs = [task[3] for task in tasks]
                
                # Create task tuples for parallel processing
                parallel_tasks = [(coro, args, kwargs) for coro, args, kwargs in zip(task_coros, task_args, task_kwargs)]
                
                # Execute in parallel
                results = await self.parallel_manager.submit_batch_tasks(parallel_tasks)
                
                # Process results
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        log.error(f"Error in {task_names[i]}: {result}")
                    else:
                        log.debug(f"Completed {task_names[i]} successfully")
                
                self.last_update = time.time()
                
        except Exception as e:
            log.error(f"Error running parallel tasks: {e}")
    
    async def _is_market_open(self) -> bool:
        """Check if market is currently open for trading"""
        try:
            if hasattr(self, 'market_manager') and self.market_manager:
                return self.market_manager.is_market_open()
            else:
                # Fallback: timezone-aware time check (9:30 AM - 4:00 PM ET, exclusive of close)
                # Rev 00055: CRITICAL FIX - Use ET timezone, not local time
                # Rev 00125: datetime already imported at top of file - removed redundant local import
                from zoneinfo import ZoneInfo
                
                et_tz = ZoneInfo('America/New_York')
                now_et = datetime.now(et_tz)
                
                # Market hours: 9:30 AM - 4:00 PM ET
                market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
                market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
                
                is_open = market_open <= now_et < market_close
                
                if not is_open:
                    log.debug(f"Market check: {now_et.strftime('%I:%M %p ET')} - Market {'OPEN' if is_open else 'CLOSED'}")
                
                return is_open
        except Exception as e:
            log.error(f"Error checking market status: {e}")
            return False
    
    async def _prefetch_previous_candle_data(self):
        """
        Pre-fetch 7:00-7:15 AM PT candle data for instant SO decisions
        
        Called AT 7:15:00 AM PT when SO window opens to ensure:
        - prev_candle_close is ready
        - prev_candle_open is ready
        - Volume color can be calculated instantly
        
        This eliminates API call delays during SO validation (2-5 second fetch)
        """
        try:
            symbols = self.symbol_list[:100]
            
            log.info(f"📊 Pre-fetching 7:00-7:15 AM PT candle for {len(symbols)} symbols...")
            start_time = time.time()
            
            # BATCH fetch intraday 15m bars (includes 7:00-7:15 AM bar)
            batch_intraday = await self.data_manager.get_batch_intraday_data(
                symbols,
                interval="15m",
                bars=5  # Get last 5 bars to ensure we have 7:00-7:15 AM
            )
            
            if not batch_intraday:
                log.error("❌ Pre-fetch failed")
                return
            
            # Store for instant SO access
            self._prefetched_intraday = batch_intraday
            
            # Calculate volume colors for all symbols (instant)
            volume_colors = {}
            for symbol, bars in batch_intraday.items():
                if bars and len(bars) > 0:
                    # Get the 7:00-7:15 AM bar (most recent)
                    prev_candle = bars[-1]
                    prev_open = prev_candle.get('open', 0)
                    prev_close = prev_candle.get('close', 0)
                    
                    if prev_close > prev_open:
                        volume_colors[symbol] = "GREEN"
                    elif prev_close < prev_open:
                        volume_colors[symbol] = "RED"
                    else:
                        volume_colors[symbol] = "NEUTRAL"
            
            self._prefetched_volume_colors = volume_colors
            
            elapsed = time.time() - start_time
            log.info(f"✅ Pre-fetch complete: {len(batch_intraday)} bars + {len(volume_colors)} volume colors in {elapsed:.1f}s")
            log.info(f"   GREEN: {sum(1 for c in volume_colors.values() if c == 'GREEN')}, RED: {sum(1 for c in volume_colors.values() if c == 'RED')}")
            
        except Exception as e:
            log.error(f"Error pre-fetching SO data: {e}")
    
    async def _capture_orb_for_all_symbols(self):
        """
        Capture ORB for all symbols - BATCH OPTIMIZED (Rev 00151)
        Rev 00060: Captures ALL symbols dynamically from core_list.csv (currently 121)
        Rev 00209: Also captures 0DTE Strategy symbols from 0dte_list.csv
        
        SPEED: 2-5 seconds for any reasonable count (100x faster than individual calls)
        Completes well before 6:45 AM PT ORB window closes
        
        This runs ONCE per day at market open (6:30 AM PT) to establish
        the opening range for all selected symbols.
        """
        try:
            if not hasattr(self, 'symbol_list') or not self.symbol_list:
                log.warning("⚠️ No symbols available for ORB capture")
                return
            
            # Rev 00057: Capture ALL symbols (not just first 100)
            symbols = self.symbol_list.copy()  # Capture all ORB Strategy symbols
            
            # Rev 00209: Load and add 0DTE Strategy symbols
            dte_symbols = []
            try:
                import pandas as pd
                import os
                dte_list_path = "data/watchlist/0dte_list.csv"
                if os.path.exists(dte_list_path):
                    df = pd.read_csv(dte_list_path, comment='#')
                    dte_symbols = df['symbol'].tolist() if 'symbol' in df.columns else df.iloc[:, 0].tolist()
                    # Add 0DTE symbols that aren't already in the ORB list
                    for dte_symbol in dte_symbols:
                        if dte_symbol not in symbols:
                            symbols.append(dte_symbol)
                    log.info(f"📊 Added {len(dte_symbols)} 0DTE Strategy symbols to ORB capture")
                else:
                    log.warning(f"⚠️ 0DTE symbol list not found: {dte_list_path}")
            except Exception as e:
                log.warning(f"⚠️ Failed to load 0DTE symbol list: {e}")
            
            log.info(f"📊 BATCH capturing ORB for {len(symbols)} symbols ({len(self.symbol_list)} ORB + {len(dte_symbols)} 0DTE)...")
            start_time = time.time()
            
            # BATCH fetch intraday data for ALL symbols using ETrade quotes (Rev 00036)
            # CRITICAL FIX: Use bars=1 to trigger ETrade quotes path (line 1140 in data_manager)
            # ETrade quotes contain TODAY's OHLC which IS the opening range!
            # bars > 1 triggers yfinance fallback which has NaN errors for 26 symbols
            batch_intraday = await self.data_manager.get_batch_intraday_data(
                symbols,
                interval="15m",
                bars=1  # FIXED: Use bars=1 to get ETrade quotes (100% reliable)
            )
            
            if not batch_intraday:
                log.error("❌ Batch intraday fetch failed")
                return
            
            captured_count = 0
            dte_captured_count = 0  # Rev 00210: Track 0DTE symbols separately
            failed_symbols = []  # Rev 00188: Track symbols that failed to capture
            missing_data_symbols = []  # Rev 00188: Track symbols with no data from ETrade
            
            # Rev 00188: Identify symbols that didn't get data from ETrade
            symbols_with_data = set(batch_intraday.keys())
            symbols_requested = set(symbols)
            missing_data_symbols = list(symbols_requested - symbols_with_data)
            if missing_data_symbols:
                log.warning(f"⚠️ {len(missing_data_symbols)} symbols did not receive data from ETrade: {', '.join(sorted(missing_data_symbols))}")
            
            # Process each symbol's data (NO API CALLS - instant processing)
            for symbol, intraday_data in batch_intraday.items():
                try:
                    orb_result = self.orb_strategy_manager._capture_opening_range(symbol, intraday_data)
                    if orb_result:
                        captured_count += 1
                        # Track 0DTE symbols separately
                        if symbol in dte_symbols:
                            dte_captured_count += 1
                    else:
                        # Rev 00188: Track symbols that failed to capture (no ORB data found)
                        failed_symbols.append(symbol)
                        log.debug(f"⚠️ No ORB data found for {symbol} (no candle in ORB window)")
                except Exception as e:
                    failed_symbols.append(symbol)
                    log.error(f"Error capturing ORB for {symbol}: {e}")
            
            elapsed = time.time() - start_time
            
            # Rev 00188: Log detailed capture results
            total_missing = len(missing_data_symbols) + len(failed_symbols)
            if total_missing > 0:
                log.warning(f"⚠️ ORB CAPTURE INCOMPLETE: {captured_count}/{len(symbols)} symbols captured ({total_missing} missing)")
                if missing_data_symbols:
                    log.warning(f"   ❌ Missing data from ETrade ({len(missing_data_symbols)}): {', '.join(sorted(missing_data_symbols))}")
                if failed_symbols:
                    log.warning(f"   ❌ Failed to capture ORB ({len(failed_symbols)}): {', '.join(sorted(failed_symbols))}")
            else:
                log.info(f"✅ ORB CAPTURE COMPLETE: {captured_count}/{len(symbols)} symbols ({captured_count - dte_captured_count} ORB + {dte_captured_count} 0DTE) in {elapsed:.1f}s")
            
            # Extract SPX/QQQ/SPY ORB data for 0DTE Strategy (if enabled)
            if hasattr(self, 'dte0_manager') and self.dte0_manager:
                try:
                    spx_qqq_spy_orb = self.dte0_manager.get_spx_qqq_spy_orb_data(self.orb_strategy_manager)
                    if spx_qqq_spy_orb['SPX'] or spx_qqq_spy_orb['QQQ'] or spx_qqq_spy_orb['SPY']:
                        log.info(f"✅ 0DTE Strategy: SPX/QQQ/SPY ORB data extracted")
                        if spx_qqq_spy_orb['SPX']:
                            # Calculate orb_range_pct from orb_range and orb_low
                            spx_orb_range_pct = (spx_qqq_spy_orb['SPX'].orb_range / spx_qqq_spy_orb['SPX'].orb_low * 100) if spx_qqq_spy_orb['SPX'].orb_low > 0 else 0.0
                            log.info(f"   SPX: High=${spx_qqq_spy_orb['SPX'].orb_high:.2f}, Low=${spx_qqq_spy_orb['SPX'].orb_low:.2f}, Range={spx_orb_range_pct:.2f}% (Priority 1)")
                        if spx_qqq_spy_orb['QQQ']:
                            # Calculate orb_range_pct from orb_range and orb_low
                            qqq_orb_range_pct = (spx_qqq_spy_orb['QQQ'].orb_range / spx_qqq_spy_orb['QQQ'].orb_low * 100) if spx_qqq_spy_orb['QQQ'].orb_low > 0 else 0.0
                            log.info(f"   QQQ: High=${spx_qqq_spy_orb['QQQ'].orb_high:.2f}, Low=${spx_qqq_spy_orb['QQQ'].orb_low:.2f}, Range={qqq_orb_range_pct:.2f}% (Priority 2)")
                        if spx_qqq_spy_orb['SPY']:
                            # Calculate orb_range_pct from orb_range and orb_low
                            spy_orb_range_pct = (spx_qqq_spy_orb['SPY'].orb_range / spx_qqq_spy_orb['SPY'].orb_low * 100) if spx_qqq_spy_orb['SPY'].orb_low > 0 else 0.0
                            log.info(f"   SPY: High=${spx_qqq_spy_orb['SPY'].orb_high:.2f}, Low=${spx_qqq_spy_orb['SPY'].orb_low:.2f}, Range={spy_orb_range_pct:.2f}% (Priority 3)")
                        
                    else:
                        log.warning("⚠️  0DTE Strategy: SPX/QQQ/SPY ORB data not found")
                except Exception as e:
                    log.error(f"❌ Error extracting SPX/QQQ/SPY ORB data for 0DTE Strategy: {e}", exc_info=True)
            
            # Show top 5 ORB ranges for verification
            if captured_count > 0:
                orb_samples = list(self.orb_strategy_manager.orb_data.items())[:5]
                log.info(f"📊 Sample ORB Ranges:")
                for symbol, orb_data in orb_samples:
                    log.info(f"   {symbol}: H=${orb_data.orb_high:.2f}, L=${orb_data.orb_low:.2f}, Range=${orb_data.orb_range:.2f}")
            
            # Persist ORB snapshot for deduplication across instances
            if hasattr(self, 'daily_run_tracker') and self.daily_run_tracker:
                try:
                    orb_snapshot = {
                        sym: data.to_dict() if hasattr(data, "to_dict") else data
                        for sym, data in self.orb_strategy_manager.orb_data.items()
                    }
                    from .config_loader import get_config_value
                    etrade_mode = get_config_value('ETRADE_MODE', 'sandbox')
                    metadata = {
                        "mode": "LIVE" if etrade_mode == "prod" else "DEMO",
                        "capture_seconds": elapsed,
                        "service": os.getenv("K_SERVICE"),
                        "revision": os.getenv("K_REVISION"),
                    }
                    self.daily_run_tracker.record_orb_capture(
                        orb_snapshot=orb_snapshot,
                        captured_count=captured_count,
                        total_symbols=len(symbols),
                        metadata=metadata,
                    )
                except Exception as tracker_error:
                    log.warning(f"⚠️ Failed to persist ORB daily marker: {tracker_error}")
            
            # Send ORB Capture alert (Rev 00180AE: Send appropriate alert based on capture success)
            if self.alert_manager:
                try:
                    # Determine mode
                    from .config_loader import get_config_value
                    etrade_mode = get_config_value('ETRADE_MODE', 'sandbox')
                    mode = "LIVE" if etrade_mode == "prod" else "DEMO"
                    
                    # Rev 00046: Add deduplication flag to prevent duplicate alerts across Cloud Run instances
                    if not hasattr(self, '_orb_capture_alert_sent_today'):
                        self._orb_capture_alert_sent_today = False
                    
                    if not self._orb_capture_alert_sent_today:
                        if captured_count > 0:
                            # Success: Send ORB Capture Complete alert
                            filtered_count = len([s for s in self.orb_strategy_manager.post_orb_validation.values() 
                                                if not s.is_valid])
                            
                            # Get 0DTE data for inclusion in alert (Rev 00209: All 0DTE symbols)
                            spx_data = None
                            qqq_data = None
                            spy_data = None
                            dte_orb_data = {}  # Dictionary of all 0DTE symbols with ORB data

                            # Load 0DTE symbol list to get tier information
                            dte_symbols_list = []
                            dte_tier_map = {}
                            try:
                                import pandas as pd
                                import os
                                dte_list_path = "data/watchlist/0dte_list.csv"
                                if os.path.exists(dte_list_path):
                                    df = pd.read_csv(dte_list_path, comment='#')
                                    dte_symbols_list = df['symbol'].tolist() if 'symbol' in df.columns else df.iloc[:, 0].tolist()
                                    if 'tier' in df.columns:
                                        dte_tier_map = dict(zip(df['symbol'], df['tier']))
                                    log.debug(f"Loaded {len(dte_symbols_list)} 0DTE symbols for alert")
                            except Exception as e:
                                log.warning(f"Could not load 0DTE symbol list: {e}")

                            # Get ORB data for all 0DTE symbols from ORB Strategy Manager
                            if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                                try:
                                    # Try to get current prices for context
                                    current_prices = {}
                                    if hasattr(self, 'trade_manager') and self.trade_manager and hasattr(self.trade_manager, 'etrade_trading'):
                                        try:
                                            # Get quotes for all 0DTE symbols
                                            quotes = self.trade_manager.etrade_trading.get_quotes(dte_symbols_list if dte_symbols_list else ['SPX', 'QQQ', 'SPY'])
                                            for quote in quotes:
                                                symbol = getattr(quote, 'symbol', None) or getattr(quote, 'Symbol', None)
                                                if symbol:
                                                    current_prices[symbol] = getattr(quote, 'last_price', None) or getattr(quote, 'LastPrice', None) or getattr(quote, 'last', None)
                                        except Exception as price_error:
                                            log.debug(f"Could not get current prices for 0DTE alert: {price_error}")
                                    
                                    # Extract ORB data for all 0DTE symbols
                                    for symbol in dte_symbols_list if dte_symbols_list else ['SPX', 'QQQ', 'SPY']:
                                        if symbol in self.orb_strategy_manager.orb_data:
                                            orb = self.orb_strategy_manager.orb_data[symbol]
                                            current_price = current_prices.get(symbol, None)
                                            
                                            # Calculate orb_range_pct from orb_range and orb_low
                                            orb_range_pct = (orb.orb_range / orb.orb_low * 100) if orb.orb_low > 0 else 0.0
                                            orb_data_dict = {
                                                'orb_high': orb.orb_high,
                                                'orb_low': orb.orb_low,
                                                'orb_range_pct': orb_range_pct,
                                                'current_price': current_price,
                                                'orb_open': orb.orb_open,
                                                'tier': dte_tier_map.get(symbol, None)
                                            }
                                            
                                            # Keep separate variables for SPX, QQQ, SPY for backward compatibility
                                            if symbol == 'SPX':
                                                spx_data = orb_data_dict
                                            elif symbol == 'QQQ':
                                                qqq_data = orb_data_dict
                                            elif symbol == 'SPY':
                                                spy_data = orb_data_dict
                                            
                                            # Add to dte_orb_data dictionary
                                            dte_orb_data[symbol] = orb_data_dict
                                    
                                    log.debug(f"Collected ORB data for {len(dte_orb_data)} 0DTE symbols")
                                except Exception as e:
                                    log.warning(f"Could not get 0DTE ORB data for alert: {e}")

                            # Calculate ORB Strategy count (total - 0DTE)
                            orb_strategy_count = captured_count - dte_captured_count
                            
                            await self.alert_manager.send_orb_capture_complete_alert(
                                symbols_captured=captured_count,
                                orb_strategy_count=orb_strategy_count,  # Rev 00210: Separate ORB Strategy count
                                dte_strategy_count=dte_captured_count,  # Rev 00210: Separate 0DTE Strategy count
                                capture_time_seconds=elapsed,
                                filtered_count=filtered_count,
                                mode=mode,
                                spx_orb_data=spx_data,
                                qqq_orb_data=qqq_data,
                                spy_orb_data=spy_data,
                                dte_orb_data=dte_orb_data
                            )
                            log.info(f"📱 ORB capture complete alert sent ({captured_count} symbols)")
                            self._orb_capture_alert_sent_today = True
                        else:
                            # Failure: Send No ORBs Captured alert
                            await self.alert_manager.send_orb_capture_failed_alert(
                                total_symbols=len(symbols),
                                capture_time_seconds=elapsed,
                                mode=mode
                            )
                            log.warning(f"📱 ORB capture FAILED alert sent (0 symbols captured)")
                            self._orb_capture_alert_sent_today = True
                    else:
                        log.info(f"🔒 ORB capture alert already sent today - skipping duplicate")
                except Exception as alert_error:
                    log.error(f"Failed to send ORB capture alert: {alert_error}")
            
        except Exception as e:
            log.error(f"Error in batch ORB capture: {e}")
    
    async def _scan_watchlist_for_signals(self) -> Dict[str, Any]:
        """
        Scan watchlist for ORB trading opportunities (SO/ORR signals)
        
        Scans 100 symbols in batches of 25 for efficiency
        """
        try:
            if not hasattr(self, 'symbol_list') or not self.symbol_list:
                return {'signals': [], 'count': 0}
            
            # Use ORB Strategy Manager (ONLY strategy)
            if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                return await self._scan_orb_batch_signals()
            else:
                log.error("⚠️ ORB Strategy Manager not available")
                return {'signals': [], 'count': 0}
                
        except Exception as e:
            log.error(f"Error scanning watchlist for signals: {e}")
            return {'signals': [], 'count': 0}
    
    async def _scan_orb_batch_signals(self) -> Dict[str, Any]:
        """
        Scan 100 symbols for ORB signals (SO/ORR) - OPTIMIZED for instant decisions
        
        SO Window (7:15 AM PT):
        - Uses PRE-FETCHED 7:00-7:15 AM candle data (instant)
        - Volume colors already calculated (instant)
        - Only fetches current prices (2-3 seconds)
        - Total: <5 seconds for 100 symbols ⚡
        
        ORR Window (7:15-9:15 AM PT):
        - Fetches current prices (2-3 seconds)
        - Tracks price movements vs ORB high/low
        - Detects first-time reversals
        - Total: <5 seconds per scan ⚡
        """
        try:
            if not self.data_manager or not hasattr(self, 'symbol_list'):
                return {'signals': [], 'count': 0}
            
            # Check if within trading windows
            within_so = self.orb_strategy_manager._is_within_so_window()
            within_orr = self.orb_strategy_manager._is_within_orr_window()
            
            # Rev 00046: Check if ORR is enabled (0% capital = disabled)
            orr_enabled = hasattr(self, '_orr_enabled') and self._orr_enabled
            if not orr_enabled:
                within_orr = False  # Force ORR to False if disabled
                log.debug("⏸️ ORR scanning disabled (0% capital allocation)")
            
            if not within_so and not within_orr:
                log.debug("⏸️ Outside ORB trading windows")
                return {'signals': [], 'count': 0}
            
            # Rev 00211: Load 0DTE symbols for independent monitoring
            dte_symbols = []
            try:
                import pandas as pd
                import os
                dte_list_path = "data/watchlist/0dte_list.csv"
                if os.path.exists(dte_list_path):
                    df = pd.read_csv(dte_list_path, comment='#')
                    dte_symbols = df['symbol'].tolist() if 'symbol' in df.columns else df.iloc[:, 0].tolist()
                    log.debug(f"Loaded {len(dte_symbols)} 0DTE symbols for independent monitoring")
            except Exception as e:
                log.warning(f"Could not load 0DTE symbol list: {e}")
            
            # Combine ORB symbols with 0DTE symbols (avoid duplicates)
            symbols_to_scan = self.symbol_list[:100]
            all_dte_symbols = [s for s in dte_symbols if s not in symbols_to_scan]
            symbols_to_scan = symbols_to_scan + all_dte_symbols  # Add 0DTE symbols not in ORB list
            
            all_signals = []
            dte_signals = []  # Separate list for 0DTE signals (CALL and PUT)
            
            window_type = "SO" if within_so else "ORR"
            log.info(f"🎯 {window_type} Scan: {len(symbols_to_scan)} symbols")
            
            # Rev 00176: Market Quality Gate removed - Red Day Detection Filter provides this functionality
            # Red Day Detection runs after signal collection and is more sophisticated and accurate
            
            # Use pre-fetched data for SO window (instant), fetch fresh for ORR
            if within_so and hasattr(self, '_prefetched_intraday'):
                log.info(f"⚡ Using PRE-FETCHED 7:00-7:15 AM candle data (instant SO decisions)")
                batch_intraday = self._prefetched_intraday
                volume_colors = self._prefetched_volume_colors
            else:
                log.info(f"📊 Fetching fresh intraday data for ORR tracking...")
                batch_intraday = await self.data_manager.get_batch_intraday_data(
                    symbols_to_scan,
                    interval="15m",
                    bars=5
                )
                volume_colors = {}
                # Calculate volume colors on-the-fly for ORR
                for symbol, bars in batch_intraday.items():
                    if bars and len(bars) > 0:
                        prev_candle = bars[-1]
                        prev_open = prev_candle.get('open', 0)
                        prev_close = prev_candle.get('close', 0)
                        volume_colors[symbol] = "GREEN" if prev_close > prev_open else ("RED" if prev_close < prev_open else "NEUTRAL")
            
            # Get current prices (always fetch fresh)
            log.info(f"📊 Fetching current prices (4 batches of 25)...")
            batch_quotes = await self.data_manager.get_batch_quotes(symbols_to_scan)
            
            if not batch_quotes:
                log.warning(f"⚠️ No quotes available")
                return {'signals': [], 'count': 0}
            
            # Process all symbols (ORB + 0DTE) - Rev 00211: Monitor 0DTE symbols independently
            for symbol in symbols_to_scan:
                try:
                    if symbol not in batch_quotes:
                        continue
                    
                    quote = batch_quotes[symbol]
                    intraday_bars = batch_intraday.get(symbol, [])
                    
                    # Build market data with pre-fetched/fresh info
                    market_data = {
                        'symbol': symbol,
                        'current_price': quote.get('last', 0.0),
                        'open_price': quote.get('open', 0.0),
                        'high_price': quote.get('high', 0.0),
                        'low_price': quote.get('low', 0.0),
                        'volume': quote.get('volume', 0),
                        'intraday_data': intraday_bars,  # Pass bars for prev candle validation
                        'volume_color': volume_colors.get(symbol, 'NEUTRAL'),  # Pre-calculated
                        'timestamp': datetime.utcnow()  # Rev 00073: UTC consistency
                    }
                    
                    # Check if this is a 0DTE symbol
                    is_dte_symbol = symbol in dte_symbols
                    
                    # Analyze with ORB Strategy Manager (INSTANT)
                    orb_result = await self.orb_strategy_manager.analyze_symbol(symbol, market_data)
                    
                    # Rev 00211: For 0DTE symbols, also analyze bearish signals (for PUT options)
                    bearish_result = None
                    if is_dte_symbol and within_so:
                        bearish_result = await self.orb_strategy_manager.analyze_bearish_symbol(symbol, market_data)
                    
                    # Process bullish signal (for both ORB and 0DTE)
                    if orb_result.should_trade:
                        signal_type = orb_result.signal_type.value if orb_result.signal_type else "UNKNOWN"
                        log.info(f"✅ {signal_type}: {orb_result.symbol} @ ${orb_result.entry_price:.2f} ({orb_result.confidence:.1%})")
                        
                        # Rev 00181: Calculate RS vs SPY early if possible (for Red Day Filter) - Enhanced with fallback
                        rs_vs_spy = 0.0
                        spy_price = None
                        spy_change_pct = 0.0
                        try:
                            if hasattr(self, 'trade_manager') and self.trade_manager and hasattr(self.trade_manager, 'etrade_trading'):
                                spy_quotes = self.trade_manager.etrade_trading.get_quotes(['SPY'])
                                if spy_quotes and len(spy_quotes) > 0:
                                    spy_quote = spy_quotes[0]
                                    spy_change_pct = getattr(spy_quote, 'change_pct', None)
                                    if spy_change_pct is None:
                                        spy_change_pct = 0.0
                                    spy_price = spy_quote.last_price
                                    
                                    # Get symbol change % from quote (quote is a dict from batch_quotes)
                                    symbol_change_pct = quote.get('change_pct', 0.0) if isinstance(quote, dict) else 0.0
                                    
                                    # Rev 00181: Enhanced fallback - use open vs previous close if change_pct is 0.0
                                    if symbol_change_pct == 0.0 and isinstance(quote, dict):
                                        # Try to calculate from open price if available
                                        symbol_open = quote.get('open', None)
                                        symbol_price = quote.get('last_price', quote.get('price', None))
                                        if symbol_open and symbol_price:
                                            # Use market data manager to get historical data for fallback
                                            try:
                                                if hasattr(self, 'data_manager') and self.data_manager:
                                                    # Get historical data for the symbol
                                                    hist_data = await self.data_manager.get_historical_data(orb_result.symbol, days=2)
                                                    if hist_data and len(hist_data) >= 2:
                                                        prev_close = hist_data[-2].get('close', None) if isinstance(hist_data[-2], dict) else (getattr(hist_data[-2], 'close', None) if hasattr(hist_data[-2], 'close') else None)
                                                        if prev_close and prev_close > 0:
                                                            # Use open price for more accurate intraday calculation
                                                            symbol_change_pct = ((symbol_open - prev_close) / prev_close) * 100
                                                            log.debug(f"📊 Calculated symbol change % from open vs prev close for {orb_result.symbol}: {symbol_change_pct:.2f}%")
                                            except Exception as hist_error:
                                                log.debug(f"⚠️ Could not calculate symbol change % from historical data for {orb_result.symbol}: {hist_error}")
                                    
                                    # Rev 00181: Enhanced SPY fallback
                                    if spy_change_pct == 0.0:
                                        try:
                                            import yfinance as yf
                                            spy_ticker = yf.Ticker("SPY")
                                            spy_hist = spy_ticker.history(period="2d", interval="1d")
                                            if not spy_hist.empty and len(spy_hist) >= 2:
                                                spy_prev_close = spy_hist['Close'].iloc[-2]
                                                spy_base_price = spy_quote.open if spy_quote.open > 0 else spy_quote.last_price
                                                if spy_prev_close > 0 and spy_base_price:
                                                    spy_change_pct = ((spy_base_price - spy_prev_close) / spy_prev_close) * 100
                                                    log.debug(f"📊 Calculated SPY change % from open vs prev close: {spy_change_pct:.2f}%")
                                        except Exception as spy_hist_error:
                                            log.debug(f"⚠️ Could not calculate SPY change % from historical data: {spy_hist_error}")
                                    
                                    # Calculate RS vs SPY
                                    rs_vs_spy = symbol_change_pct - spy_change_pct
                                    log.debug(f"✅ Calculated RS vs SPY for {orb_result.symbol}: {rs_vs_spy:.2f}% (symbol: {symbol_change_pct:.2f}%, SPY: {spy_change_pct:.2f}%)")
                        except Exception as rs_error:
                            log.debug(f"⚠️ Could not calculate RS vs SPY for {orb_result.symbol} during signal creation: {rs_error}")
                        
                        # Add RS vs SPY to metadata for early access
                        signal_metadata = orb_result.metadata.copy() if orb_result.metadata else {}
                        signal_metadata['rs_vs_spy'] = rs_vs_spy
                        signal_metadata['spy_price'] = spy_price
                        signal_metadata['spy_change_pct'] = spy_change_pct
                        
                        signal_dict = {
                            'symbol': orb_result.symbol,  # May be inverse ETF
                            'original_symbol': symbol,
                            'signal_type': signal_type,
                            'side': orb_result.side.value,
                            'price': orb_result.entry_price,
                            'stop_loss': orb_result.stop_loss,
                            'take_profit': orb_result.take_profit,
                            'confidence': orb_result.confidence,
                            'position_size_pct': orb_result.position_size_pct,
                            'reasoning': orb_result.reasoning,
                            'inverse_symbol': orb_result.inverse_symbol,
                            'orb_data': orb_result.orb_data,
                            'metadata': signal_metadata,
                            'rs_vs_spy': rs_vs_spy  # Rev 00174: Add directly to signal for Red Day Filter
                        }
                        
                        # Rev 00211: For 0DTE symbols, add to dte_signals list (will be processed separately)
                        if is_dte_symbol:
                            dte_signals.append(signal_dict)
                        else:
                            all_signals.append(signal_dict)
                    
                    # Rev 00211: Process bearish signal for 0DTE symbols (PUT options)
                    if is_dte_symbol and bearish_result and bearish_result.should_trade:
                        signal_type = bearish_result.signal_type.value if bearish_result.signal_type else "UNKNOWN"
                        log.info(f"✅ {signal_type} BEARISH: {bearish_result.symbol} @ ${bearish_result.entry_price:.2f} ({bearish_result.confidence:.1%}) - PUT signal")
                        
                        # Calculate RS vs SPY for bearish signal (same logic)
                        rs_vs_spy = 0.0
                        spy_price = None
                        spy_change_pct = 0.0
                        try:
                            if hasattr(self, 'trade_manager') and self.trade_manager and hasattr(self.trade_manager, 'etrade_trading'):
                                spy_quotes = self.trade_manager.etrade_trading.get_quotes(['SPY'])
                                if spy_quotes and len(spy_quotes) > 0:
                                    spy_quote = spy_quotes[0]
                                    spy_change_pct = getattr(spy_quote, 'change_pct', None) or 0.0
                                    spy_price = spy_quote.last_price
                                    symbol_change_pct = quote.get('change_pct', 0.0) if isinstance(quote, dict) else 0.0
                                    rs_vs_spy = symbol_change_pct - spy_change_pct
                        except Exception as rs_error:
                            log.debug(f"⚠️ Could not calculate RS vs SPY for bearish {symbol}: {rs_error}")
                        
                        signal_metadata = bearish_result.metadata.copy() if bearish_result.metadata else {}
                        signal_metadata['rs_vs_spy'] = rs_vs_spy
                        signal_metadata['spy_price'] = spy_price
                        signal_metadata['spy_change_pct'] = spy_change_pct
                        
                        # Add bearish signal to dte_signals (for PUT options)
                        dte_signals.append({
                            'symbol': bearish_result.symbol,
                            'original_symbol': symbol,
                            'signal_type': signal_type,
                            'side': bearish_result.side.value,  # SHORT
                            'price': bearish_result.entry_price,
                            'stop_loss': bearish_result.stop_loss,
                            'take_profit': bearish_result.take_profit,
                            'confidence': bearish_result.confidence,
                            'position_size_pct': bearish_result.position_size_pct,
                            'reasoning': bearish_result.reasoning,
                            'inverse_symbol': None,  # No inverse for bearish
                            'orb_data': bearish_result.orb_data,
                            'metadata': signal_metadata,
                            'rs_vs_spy': rs_vs_spy
                        })
                        
                except Exception as e:
                    log.error(f"Error analyzing {symbol}: {e}")
                    continue
            
            log.info(f"✅ {window_type} Scan Complete: {len(all_signals)} ORB signals, {len(dte_signals)} 0DTE signals from {len(symbols_to_scan)} symbols")
            
            # Rev 00048: SO Signal Collection alert sent at 7:30 AM (not during scanning)
            # Rev 00056: This alert is now sent BEFORE execution in the batch execution trigger
            # Shows final count of ALL collected signals from entire 7:15-7:30 AM window (15 minutes)
            
            # Clear pre-fetched data after SO window to free memory
            if within_so and hasattr(self, '_prefetched_intraday'):
                delattr(self, '_prefetched_intraday')
                delattr(self, '_prefetched_volume_colors')
                log.debug("🧹 Cleared pre-fetched data after SO scan")
            
            # Process signals through trading system
            # Rev 00180AE: SO signals are STORED at 7:15 AM, EXECUTED at 7:30 AM (batch execution)
            # ORR signals are processed immediately (individual execution)
            if within_so and all_signals:
                # SO WINDOW: Store signals for batch execution at 7:30 AM PT
                log.info(f"📦 SO Window: Storing {len(all_signals)} signals for batch execution at 7:30 AM PT...")
                self._pending_so_signals = all_signals
                self._so_signals_ready_time = time.time()
                log.info(f"✅ SO signals stored - batch execution scheduled for 7:30 AM PT")
                
                # Rev 00055: Log timing summary for collection window analysis
                # Rev 00064: Removed redundant datetime import (already imported at top)
                from zoneinfo import ZoneInfo
                pt_tz = ZoneInfo('America/Los_Angeles')
                now_pt = datetime.now(pt_tz)
                collection_time = now_pt.strftime('%H:%M:%S')
                log.info(f"📊 Signal Collection Summary at {collection_time} PT:")
                log.info(f"   • Total Signals: {len(all_signals)}")
                log.info(f"   • Collection Window: 7:15-7:30 AM PT (15 minutes)")
                log.info(f"   • Execution Time: 7:30 AM PT")
                log.info(f"   • Symbols: {[s.get('symbol') for s in all_signals]}")
            elif within_orr and all_signals and self.trade_manager:
                # ORR WINDOW: Execute immediately (individual execution)
                log.info(f"🚀 ORR Window: Processing {len(all_signals)} ORR signals immediately...")
                await self._process_orb_signals(all_signals)
            elif all_signals and not self.trade_manager:
                log.error(f"❌ CRITICAL: {len(all_signals)} signals found but trade_manager NOT AVAILABLE!")
                log.error(f"   Signals will NOT be executed - trade_manager is required")
                log.error(f"   This is a configuration error that needs immediate attention")
            else:
                log.info(f"📊 No {window_type} signals to process (scan complete)")
            
            # Rev 00211: Send 0DTE signals to 0DTE Strategy (if enabled)
            # Process both CALL (LONG) and PUT (SHORT) signals from dte_signals
            if hasattr(self, 'dte0_manager') and self.dte0_manager and (all_signals or dte_signals):
                try:
                    # CRITICAL: Check Red Day filter before 0DTE execution (Rev 00206)
                    # Check if flag is already set (from previous check) OR perform quick inline check
                    red_day_blocked = getattr(self, '_red_day_filter_blocked', False)
                    
                    # Rev 00211: Combine ORB and 0DTE signals for Red Day check
                    combined_signals_for_red_day = all_signals + dte_signals
                    
                    # If flag not set yet, perform quick Red Day check on current signals
                    if not red_day_blocked and combined_signals_for_red_day:
                        # Quick Red Day check using same logic as _process_orb_signals()
                        # This ensures 0DTE respects Red Day filter even if ORB execution hasn't run yet
                        num_signals = len(combined_signals_for_red_day)
                        signals_with_low_rsi = sum(1 for sig in combined_signals_for_red_day if sig.get('rsi', 55) < 40)
                        signals_with_high_rsi = sum(1 for sig in combined_signals_for_red_day if sig.get('rsi', 55) > 80)
                        signals_with_weak_volume = sum(1 for sig in combined_signals_for_red_day if sig.get('volume_ratio', 1.0) < 1.0)
                        
                        pct_low_rsi = (signals_with_low_rsi / num_signals * 100) if num_signals > 0 else 0
                        pct_high_rsi = (signals_with_high_rsi / num_signals * 100) if num_signals > 0 else 0
                        pct_weak_volume = (signals_with_weak_volume / num_signals * 100) if num_signals > 0 else 0
                        
                        # Red Day thresholds (same as _process_orb_signals)
                        RED_DAY_RSI_LOW_THRESHOLD = 70.0
                        RED_DAY_RSI_HIGH_THRESHOLD = 80.0
                        RED_DAY_VOLUME_THRESHOLD = 80.0
                        
                        # Check patterns
                        pattern1_oversold = (pct_low_rsi >= RED_DAY_RSI_LOW_THRESHOLD and pct_weak_volume >= RED_DAY_VOLUME_THRESHOLD)
                        pattern2_overbought = (pct_high_rsi >= RED_DAY_RSI_HIGH_THRESHOLD and pct_weak_volume >= RED_DAY_VOLUME_THRESHOLD)
                        pattern3_weak_volume_only = (pct_weak_volume >= RED_DAY_VOLUME_THRESHOLD)

                        # Check for momentum override (simplified - would need enriched signals for full check)
                        avg_macd_histogram = sum(sig.get('macd_histogram', 0) for sig in combined_signals_for_red_day) / num_signals if num_signals > 0 else 0
                        avg_rs_vs_spy = sum(sig.get('rs_vs_spy', 0) for sig in combined_signals_for_red_day) / num_signals if num_signals > 0 else 0
                        avg_vwap_distance = sum(sig.get('vwap_distance_pct', 0) for sig in combined_signals_for_red_day) / num_signals if num_signals > 0 else 0
                        avg_rsi = sum(sig.get('rsi', 55) for sig in combined_signals_for_red_day) / num_signals if num_signals > 0 else 55
                        avg_volume = sum(sig.get('volume_ratio', 1.0) for sig in combined_signals_for_red_day) / num_signals if num_signals > 0 else 1.0

                        # Rev 00205: Apply Pattern 1 momentum overrides (inline version)
                        if pattern1_oversold:
                            extreme_oversold_with_momentum = (avg_rsi < 10 and avg_macd_histogram > 0)
                            strong_bullish_momentum = (avg_macd_histogram > 0.5)
                            market_bottoming_signals = (avg_rsi > 20 and avg_volume > 0.2)

                            if extreme_oversold_with_momentum or strong_bullish_momentum or market_bottoming_signals:
                                pattern1_oversold = False  # Override: allow trading
                        
                        MIN_MACD_HISTOGRAM = 0.0
                        MIN_RS_VS_SPY = 2.0
                        MIN_VWAP_DISTANCE = 1.0
                        
                        # Apply momentum override to patterns
                        if pattern2_overbought:
                            if (avg_macd_histogram > MIN_MACD_HISTOGRAM and avg_rs_vs_spy > MIN_RS_VS_SPY) or \
                               (avg_vwap_distance > MIN_VWAP_DISTANCE and avg_macd_histogram > MIN_MACD_HISTOGRAM):
                                pattern2_overbought = False
                        
                        if pattern3_weak_volume_only:
                            if (avg_macd_histogram > MIN_MACD_HISTOGRAM and avg_rs_vs_spy > MIN_RS_VS_SPY) or \
                               (avg_vwap_distance > MIN_VWAP_DISTANCE and avg_macd_histogram > MIN_MACD_HISTOGRAM):
                                pattern3_weak_volume_only = False
                        
                        is_red_day = pattern1_oversold or pattern2_overbought or pattern3_weak_volume_only
                        
                        if is_red_day:
                            red_day_blocked = True
                            self._red_day_filter_blocked = True  # Set flag for future checks
                            log.warning("🚨 RED DAY DETECTED (Inline Check) - 0DTE Options Execution SKIPPED")
                            log.warning(f"   ⚠️ Pattern detected: {pct_low_rsi:.0f}% oversold, {pct_high_rsi:.0f}% overbought, {pct_weak_volume:.0f}% weak volume")
                            log.warning("   📊 Red Day filter blocking options trading to preserve capital")
                    
                    if red_day_blocked:
                        log.warning("🚨 RED DAY DETECTED - 0DTE Options Execution SKIPPED")
                        log.warning("   ⚠️ Red Day filter blocking options trading to preserve capital")
                        log.warning("   📊 ORB signals received but options execution skipped")
                        # Don't send signals to 0DTE Strategy if Red Day detected
                        return {'signals': all_signals, 'count': len(all_signals)}
                    
                    # Rev 00211: Process 0DTE signals (both CALL and PUT from dte_signals)
                    # dte_signals contains both LONG (CALL) and SHORT (PUT) signals for 0DTE symbols
                    if dte_signals:
                        log.info(f"🔮 Processing {len(dte_signals)} 0DTE signals ({sum(1 for s in dte_signals if s.get('side') == 'LONG')} CALL, {sum(1 for s in dte_signals if s.get('side') == 'SHORT')} PUT)...")
                        
                        # Check if 0DTE signals were already processed before SO alert
                        if hasattr(self, '_pending_dte0_signals') and self._pending_dte0_signals is not None:
                            # Use pre-processed signals from SO alert timing
                            dte0_signals = self._pending_dte0_signals
                            log.info(f"✅ Using pre-processed 0DTE signals: {len(dte0_signals)} qualified")
                        else:
                            # Process 0DTE signals now (both CALL and PUT)
                            log.info(f"🔮 Processing {len(dte_signals)} 0DTE signals (CALL and PUT)...")
                            dte0_signals = await self.dte0_manager.listen_to_orb_signals(
                                dte_signals,  # Rev 00211: Pass dte_signals (includes both LONG and SHORT)
                                orb_strategy_manager=self.orb_strategy_manager
                            )
                    else:
                        log.info("ℹ️  No 0DTE signals to process")
                        dte0_signals = []
                    
                    if dte0_signals:
                        log.info(f"✅ 0DTE Strategy generated {len(dte0_signals)} options signals:")
                        for signal in dte0_signals:
                            log.info(f"   - {signal.symbol} {signal.option_type_label}: Score {signal.eligibility_result.eligibility_score:.2f}, Delta {signal.target_delta:.2f}, Width ${signal.spread_width:.0f}")
                        
                        # Execute options trades (if Options Chain Manager and Executor are available)
                        if hasattr(self.dte0_manager, 'options_chain_manager') and hasattr(self.dte0_manager, 'options_executor'):
                            if self.dte0_manager.options_chain_manager and self.dte0_manager.options_executor:
                                await self._execute_0dte_options_trades(dte0_signals)
                            else:
                                log.warning("⚠️ 0DTE Options Chain Manager or Executor not initialized - skipping execution")
                        else:
                            log.warning("⚠️ 0DTE Options Chain Manager or Executor not available - skipping execution")
                    else:
                        log.info("ℹ️  0DTE Strategy: No eligible signals for options trading")
                except Exception as e:
                    log.error(f"❌ Error sending signals to 0DTE Strategy: {e}", exc_info=True)

            # Clean up stored 0DTE signals after execution
            if hasattr(self, '_pending_dte0_signals'):
                self._pending_dte0_signals = None

            return {'signals': all_signals, 'count': len(all_signals)}
            
        except Exception as e:
            log.error(f"Error in ORB batch scanning: {e}")
            return {'signals': [], 'count': 0}
    
    async def _execute_0dte_options_trades(self, dte0_signals) -> None:
        """
        Execute 0DTE options trades from generated signals
        
        Args:
            dte0_signals: List of DTE0Signal objects from Prime0DTEStrategyManager
        """
        if not dte0_signals:
            return
        
        log.info(f"🎯 Executing {len(dte0_signals)} 0DTE options trades (in priority order)...")
        
        dte0_manager = self.dte0_manager
        options_chain_manager = dte0_manager.options_chain_manager
        options_executor = dte0_manager.options_executor
        
        if not options_chain_manager or not options_executor:
            log.error("❌ Options Chain Manager or Executor not available")
            return
        
        # Rev 00225: Signals are already ranked by priority (highest first)
        # Log priority ranking for verification
        if dte0_signals:
            log.info(f"📊 Priority Ranking (Top 5):")
            for i, signal in enumerate(dte0_signals[:5], 1):
                log.info(f"   {i}. {signal.symbol} {signal.direction} - Priority: {signal.priority_score:.3f} (Rank: {signal.priority_rank})")
        
        # Rev 00226: Calculate position sizes using 90% capital allocation (similar to ORB Strategy)
        # Rev 00231: Use config values to match ORB Strategy risk parameters
        import os
        account_balance = 5000.0  # Default $5,000 Demo account
        if options_executor.demo_mode and options_executor.mock_executor:
            account_balance = options_executor.mock_executor.account_balance
        else:
            # Live mode - would need to get from live account
            account_balance = 5000.0
        
        # Get max positions from config (default 15 to match ORB Strategy)
        max_concurrent_positions = int(os.getenv('0DTE_MAX_POSITIONS', '15'))
        
        # Calculate position sizes for all signals (90% capital allocation, rank-based multipliers)
        sized_positions = dte0_manager.calculate_position_sizing(
            signals=dte0_signals,
            account_balance=account_balance,
            trading_capital_pct=90.0,  # 90% capital allocation (same as ORB Strategy)
            max_position_pct=35.0,     # 35% max position size (same as ORB Strategy)
            max_concurrent_positions=max_concurrent_positions  # Max positions from config (default 15)
        )
        
        # Create a mapping of signal to position sizing info
        signal_sizing_map = {p['signal'].symbol: p for p in sized_positions}
        
        executed_count = 0
        failed_count = 0
        executed_positions = []  # Collect executed positions for alert
        total_capital_deployed = 0.0
        hard_gated_symbols = []  # Rev 00230: Collect Hard Gated symbols for execution alert
        
        # Rev 00228: Get current time for hard gate validation
        # Use module-level datetime import (line 17)
        current_time = datetime.now()
        
        for sized_pos in sized_positions:
            signal = sized_pos['signal']
            capital_allocated = sized_pos['capital_allocated']
            try:
                symbol = signal.symbol
                option_type = signal.option_type  # 'call' or 'put'
                target_delta = signal.target_delta
                spread_width = signal.spread_width
                
                momentum_score = getattr(signal, 'momentum_score', 0.0)
                strategy_type = getattr(signal, 'strategy_type', 'debit_spread')
                
                log.info(f"📊 Processing {symbol} {signal.option_type_label} signal (Rank {signal.priority_rank}):")
                log.info(f"   - Priority Score: {signal.priority_score:.3f}")
                log.info(f"   - Momentum Score: {momentum_score:.1f}/100")  # Rev 00228
                log.info(f"   - Strategy Type: {strategy_type}")  # Rev 00229
                log.info(f"   - Target delta: {target_delta:.2f}")
                log.info(f"   - Spread width: ${spread_width:.0f}")
                log.info(f"   - Eligibility score: {signal.eligibility_result.eligibility_score:.2f}")
                log.info(f"   - Capital Allocated: ${capital_allocated:.2f} ({capital_allocated/account_balance*100:.1f}% of account)")
                
                # Rev 00229: Preflight Checks (Execution Guardrails)
                # Direction confirmation
                if signal.direction not in ['LONG', 'SHORT']:
                    log.warning(f"🚨 PREFLIGHT FAILED: Invalid direction '{signal.direction}'")
                    failed_count += 1
                    continue
                
                # Rev 00228: Hard Gate Validation - If ANY fail → NO TRADE
                is_valid, reason = dte0_manager.validate_hard_gate(
                    signal=signal,
                    current_time=current_time,
                    max_allowed_spread_pct=5.0,  # 5% max spread
                    volume_multiplier=1.0  # Volume must be >= 1.0x average
                )
                
                if not is_valid:
                    log.warning(f"🚨 HARD GATE FAILED for {symbol}: {reason}")
                    log.warning(f"   ⚠️ Skipping execution - capital preserved")
                    # Rev 00230: Collect Hard Gated symbols for execution alert
                    hard_gated_symbols.append({
                        'symbol': symbol,
                        'reason': reason
                    })
                    failed_count += 1
                    continue
                
                log.info(f"   ✅ Hard Gate: PASSED")
                
                # Rev 00229: Check for NO TRADE strategy
                if strategy_type == 'no_trade':
                    log.warning(f"🚫 NO TRADE: Momentum {momentum_score:.1f} < 45 or chop detected")
                    failed_count += 1
                    continue
                
                # Fetch options chain
                log.info(f"📡 Fetching options chain for {symbol}...")
                chain = await options_chain_manager.fetch_options_chain(symbol, expiry=None)
                
                if not chain or not chain.get(option_type + 's'):
                    log.warning(f"⚠️ No {option_type} contracts found for {symbol}")
                    failed_count += 1
                    continue
                
                # Get current price from ORB signal
                current_price = signal.orb_signal.get('current_price', 0.0)
                if current_price <= 0:
                    log.warning(f"⚠️ Invalid current price for {symbol}: {current_price}")
                    failed_count += 1
                    continue
                
                # Rev 00227: Get strategy type from signal (Level 2 Options Strategies)
                strategy_type = getattr(signal, 'strategy_type', 'debit_spread')  # Default to debit spread
                spread_type = getattr(signal, 'spread_type', 'debit')  # Default to debit
                direction = getattr(signal, 'direction', 'LONG')
                
                log.info(f"📊 Strategy: {strategy_type} | Spread type: {spread_type} ({'CALL' if direction == 'LONG' else 'PUT'} options)")
                
                position = None
                
                # Rev 00229: Execute based on enhanced strategy selection
                # CASE E — NO TRADE
                if strategy_type == 'no_trade':
                    log.warning(f"🚫 NO TRADE: Momentum score {getattr(signal, 'momentum_score', 0.0):.1f} < 45 or chop detected")
                    failed_count += 1
                    continue
                
                # CASE D — LOTTO MODE (RARE, OPTIONAL)
                # momentum_score ≥ 90, trend_day_confirmed
                if strategy_type == 'lotto':
                    log.info(f"🎰 LOTTO MODE: Selecting OTM {signal.option_type_label} option (momentum ≥90)...")
                    # Use lower delta for lotto (0.10-0.15 for maximum leverage)
                    lotto_option = options_chain_manager.select_lotto_strike(
                        chain=chain,
                        option_type=option_type,
                        current_price=current_price,
                        target_delta=0.15  # Lower delta for lotto (cheap premium)
                    )
                    
                    if lotto_option:
                        log.info(f"✅ Selected Lotto {signal.option_type_label} option:")
                        log.info(f"   - Strike: ${lotto_option.strike:.2f} @ ${lotto_option.mid_price:.2f}")
                        log.info(f"   - Delta: {lotto_option.delta:.2f}, Premium: ${lotto_option.mid_price:.2f}")
                        
                        # Rev 00229: Lotto sizing: 0.25-0.5x normal risk (smaller position)
                        lotto_capital = capital_allocated * 0.35  # 35% of allocated capital (0.35x normal)
                        option_cost = lotto_option.mid_price * 100
                        if option_cost > 0:
                            quantity = int(lotto_capital / option_cost)
                            quantity = max(1, quantity)
                        else:
                            quantity = 1
                        
                        log.info(f"   - Quantity: {quantity} options (${lotto_capital:.2f} allocated, 0.35x normal risk)")
                        log.info(f"🚀 Executing Lotto {signal.option_type_label} order...")
                        position = await options_executor.execute_lotto_sleeve(lotto_option, quantity=quantity)
                
                # CASE A — LONG OPTION (Momentum Expansion)
                # momentum_score ≥ 80, volatility_expanding
                elif strategy_type == 'long_call' or strategy_type == 'long_put':
                    log.info(f"🚀 LONG OPTION: Selecting ATM/ITM {signal.option_type_label} option (momentum ≥80)...")
                    # Buy ATM or 1-strike ITM for maximum convexity
                    single_option = options_chain_manager.select_lotto_strike(
                        chain=chain,
                        option_type=option_type,
                        current_price=current_price,
                        target_delta=0.40  # ATM or slightly ITM (delta 0.40)
                    )
                    
                    if single_option:
                        log.info(f"✅ Selected {signal.option_type_label} option:")
                        log.info(f"   - Strike: ${single_option.strike:.2f} @ ${single_option.mid_price:.2f}")
                        log.info(f"   - Delta: {single_option.delta:.2f}, Gamma: {single_option.gamma:.4f}")
                        log.info(f"   - Premium: ${single_option.mid_price:.2f}")
                        
                        # Rev 00229: Long option sizing: 0.25-0.5x normal risk (smaller position)
                        long_capital = capital_allocated * 0.40  # 40% of allocated capital (0.4x normal)
                        option_cost = single_option.mid_price * 100
                        if option_cost > 0:
                            quantity = int(long_capital / option_cost)
                            quantity = max(1, quantity)
                        else:
                            quantity = 1
                        
                        log.info(f"   - Quantity: {quantity} options (${long_capital:.2f} allocated, 0.4x normal risk)")
                        log.info(f"🚀 Executing {signal.option_type_label} order...")
                        position = await options_executor.execute_lotto_sleeve(single_option, quantity=quantity)
                
                elif strategy_type == 'momentum_scalper':
                    # Strategy 2: ATM Debit Spread "Momentum Scalper"
                    log.info(f"🎯 Selecting ATM Momentum Scalper debit spread...")
                    debit_spread = options_chain_manager.select_atm_momentum_scalper(
                        chain=chain,
                        option_type=option_type,
                        current_price=current_price,
                        strikes_otm=1  # 1-2 strikes OTM for quick payoff
                    )
                    
                    if debit_spread:
                        log.info(f"✅ Selected ATM Momentum Scalper:")
                        log.info(f"   - Long strike: ${debit_spread.long_strike:.2f} (delta: {debit_spread.long_contract.delta:.2f})")
                        log.info(f"   - Short strike: ${debit_spread.short_strike:.2f} (delta: {debit_spread.short_contract.delta:.2f})")
                        log.info(f"   - Debit cost: ${debit_spread.debit_cost:.2f}")
                        log.info(f"   - Max profit: ${debit_spread.max_profit:.2f}")
                        
                        # Rev 00226: Calculate quantity based on allocated capital
                        spread_cost = debit_spread.debit_cost * 100
                        if spread_cost > 0:
                            quantity = int(capital_allocated / spread_cost)
                            quantity = max(1, quantity)
                        else:
                            quantity = 1
                        
                        log.info(f"   - Quantity: {quantity} spreads (${capital_allocated:.2f} allocated / ${spread_cost:.2f} per spread)")
                        
                        # Execute debit spread
                        log.info(f"🚀 Executing ATM Momentum Scalper order...")
                        position = await options_executor.execute_debit_spread(debit_spread, quantity=quantity)
                
                # CASE C — ITM PROBABILITY SPREAD (Easy Mode)
                # momentum_score ∈ [45, 55], structure clean
                elif strategy_type == 'itm_probability_spread':
                    log.info(f"📊 ITM PROBABILITY SPREAD: Selecting deeper ITM spread (momentum 45-55)...")
                    debit_spread = options_chain_manager.select_itm_probability_spread(
                        chain=chain,
                        option_type=option_type,
                        current_price=current_price,
                        target_delta=0.65  # Deeper ITM (0.60-0.70 delta)
                    )
                    
                    if debit_spread:
                        log.info(f"✅ Selected ITM Probability Spread:")
                        log.info(f"   - Long strike: ${debit_spread.long_strike:.2f} (delta: {debit_spread.long_contract.delta:.2f}, ITM)")
                        log.info(f"   - Short strike: ${debit_spread.short_strike:.2f} (delta: {debit_spread.short_contract.delta:.2f})")
                        log.info(f"   - Debit cost: ${debit_spread.debit_cost:.2f}")
                        log.info(f"   - Max profit: ${debit_spread.max_profit:.2f}")
                        log.info(f"   - Higher probability, lower breakeven")
                        
                        # Rev 00226: Calculate quantity based on allocated capital
                        spread_cost = debit_spread.debit_cost * 100
                        if spread_cost > 0:
                            quantity = int(capital_allocated / spread_cost)
                            quantity = max(1, quantity)
                        else:
                            quantity = 1
                        
                        log.info(f"   - Quantity: {quantity} spreads (${capital_allocated:.2f} allocated / ${spread_cost:.2f} per spread)")
                        log.info(f"🚀 Executing ITM Probability Spread order...")
                        position = await options_executor.execute_debit_spread(debit_spread, quantity=quantity)
                
                # CASE B — DEBIT SPREAD (Default / Core Trade) ⭐ MOST COMMON
                # momentum_score ∈ [55, 80] OR default
                elif strategy_type == 'debit_spread' or spread_type == 'debit':
                    # Strategy 3: Debit Spread (Default - Bull Call or Bear Put)
                    if direction == 'LONG':
                        log.info(f"🎯 Selecting Bull Call Debit Spread...")
                    else:
                        log.info(f"🎯 Selecting Bear Put Debit Spread...")
                    # CALL options: Debit spread (buy call spread)
                    log.info(f"🎯 Selecting CALL debit spread strikes...")
                    debit_spread = options_chain_manager.select_debit_spread_strikes(
                        chain=chain,
                        option_type=option_type,
                        target_delta=target_delta,
                        spread_width=spread_width,
                        current_price=current_price
                    )
                    
                    if debit_spread:
                        log.info(f"✅ Selected debit spread:")
                        log.info(f"   - Long strike: ${debit_spread.long_strike:.2f} (delta: {debit_spread.long_contract.delta:.2f})")
                        log.info(f"   - Short strike: ${debit_spread.short_strike:.2f} (delta: {debit_spread.short_contract.delta:.2f})")
                        log.info(f"   - Debit cost: ${debit_spread.debit_cost:.2f}")
                        log.info(f"   - Max profit: ${debit_spread.max_profit:.2f}")
                        log.info(f"   - Max loss: ${debit_spread.max_loss:.2f}")
                        
                        # Rev 00226: Calculate quantity based on allocated capital
                        spread_cost = debit_spread.debit_cost * 100  # Cost per spread (multiply by 100 for options)
                        if spread_cost > 0:
                            quantity = int(capital_allocated / spread_cost)
                            quantity = max(1, quantity)  # Minimum 1 spread
                        else:
                            quantity = 1
                        
                        log.info(f"   - Quantity: {quantity} spreads (${capital_allocated:.2f} allocated / ${spread_cost:.2f} per spread)")
                        
                        # Execute debit spread
                        log.info(f"🚀 Executing debit spread order...")
                        position = await options_executor.execute_debit_spread(debit_spread, quantity=quantity)
                
                elif spread_type == 'credit':
                    # PUT options: Credit spread (sell put spread)
                    log.info(f"🎯 Selecting PUT credit spread strikes...")
                    credit_spread = options_chain_manager.select_credit_spread_strikes(
                        chain=chain,
                        option_type=option_type,
                        target_delta=target_delta,
                        spread_width=spread_width,
                        current_price=current_price
                    )
                    
                    if credit_spread:
                        log.info(f"✅ Selected credit spread:")
                        log.info(f"   - Short strike: ${credit_spread.short_strike:.2f} (delta: {credit_spread.short_contract.delta:.2f})")
                        log.info(f"   - Long strike: ${credit_spread.long_strike:.2f} (delta: {credit_spread.long_contract.delta:.2f})")
                        log.info(f"   - Credit received: ${credit_spread.credit_received:.2f}")
                        log.info(f"   - Max profit: ${credit_spread.max_profit:.2f}")
                        log.info(f"   - Max loss: ${credit_spread.max_loss:.2f}")
                        
                        # Rev 00226: Calculate quantity based on allocated capital
                        # For credit spreads, we need margin (max loss), not credit received
                        spread_margin = credit_spread.max_loss * 100  # Margin required per spread
                        if spread_margin > 0:
                            quantity = int(capital_allocated / spread_margin)
                            quantity = max(1, quantity)  # Minimum 1 spread
                        else:
                            quantity = 1
                        
                        log.info(f"   - Quantity: {quantity} spreads (${capital_allocated:.2f} allocated / ${spread_margin:.2f} margin per spread)")
                        
                        # Execute PUT credit spread
                        log.info(f"🚀 Executing PUT credit spread order...")
                        position = await options_executor.execute_credit_spread(credit_spread, quantity=quantity)
                else:
                    log.warning(f"⚠️ Unknown spread type: {spread_type} for {symbol} {signal.option_type_label}")
                    failed_count += 1
                    continue
                
                if not position:
                    log.warning(f"⚠️ Failed to execute {symbol} {signal.option_type_label} {spread_type} spread")
                    failed_count += 1
                    continue
                
                if position:
                    executed_count += 1
                    executed_positions.append(position)  # Add to list for alert
                    
                    # Calculate actual capital deployed
                    if position.position_type == 'debit_spread':
                        actual_cost = position.entry_price * position.quantity * 100
                    elif position.position_type == 'credit_spread':
                        # For credit spreads, use margin (max loss) as capital requirement
                        if position.credit_spread:
                            actual_cost = position.credit_spread.max_loss * position.quantity * 100
                        else:
                            actual_cost = position.entry_price * position.quantity * 100
                    else:
                        actual_cost = position.entry_price * position.quantity * 100
                    
                    total_capital_deployed += actual_cost
                    
                    log.info(f"✅ Options trade executed successfully:")
                    log.info(f"   - Position ID: {position.position_id}")
                    log.info(f"   - Entry price: ${position.entry_price:.2f}")
                    log.info(f"   - Quantity: {position.quantity}")
                    log.info(f"   - Capital Deployed: ${actual_cost:.2f}")
                    log.info(f"   - Status: {position.status}")
                else:
                    failed_count += 1
                    log.warning(f"⚠️ Failed to execute options trade for {symbol}")
                    
            except Exception as e:
                failed_count += 1
                log.error(f"❌ Error executing options trade for {signal.symbol}: {e}", exc_info=True)
        
        log.info(f"📊 0DTE Options Execution Summary:")
        log.info(f"   - Total signals: {len(dte0_signals)}")
        log.info(f"   - Executed: {executed_count}")
        log.info(f"   - Failed: {failed_count}")
        
        # Send 0DTE Strategy Options Execution Alert (Rev 00222: Separate from ORB alerts)
        # Send alert even if no trades executed (user needs to know status)
        if self.alert_manager:
            try:
                # Rev 00226: total_capital_deployed already calculated during execution
                # Account balance already retrieved above
                
                # Determine mode
                mode = "DEMO" if options_executor.demo_mode else "LIVE"
                
                # Convert positions to dict format for alert
                # Rev 00225: Add priority ranking data from signals to positions
                executed_positions_dict = []
                for pos in executed_positions:
                    pos_dict = pos.to_dict()
                    
                    # Find matching signal to get priority data
                    matching_signal = None
                    for signal in dte0_signals:
                        if signal.symbol == pos.symbol:
                            matching_signal = signal
                            break
                    
                    # Add priority ranking data if signal found (Rev 00230: Enhanced with momentum and strategy)
                    if matching_signal:
                        pos_dict['priority_rank'] = matching_signal.priority_rank
                        pos_dict['priority_score'] = matching_signal.priority_score
                        pos_dict['capital_allocated'] = matching_signal.capital_allocated
                        # Get confidence from ORB signal
                        orb_signal = matching_signal.orb_signal
                        pos_dict['confidence'] = orb_signal.get('confidence', 0.0)
                        # Rev 00230: Add momentum score and strategy type for execution alert
                        pos_dict['momentum_score'] = getattr(matching_signal, 'momentum_score', 0.0)
                        pos_dict['strategy_type'] = getattr(matching_signal, 'strategy_type', 'debit_spread')
                        pos_dict['direction'] = matching_signal.direction
                        pos_dict['hard_gate_passed'] = True  # If we got here, Hard Gate passed
                    
                    # Add account balance for capital % calculation
                    pos_dict['account_balance'] = account_balance
                    
                    executed_positions_dict.append(pos_dict)
                
                # Collect rejected signals (if available)
                rejected_signals = []
                # Note: Rejected signals would need to be tracked during execution
                # For now, we'll pass empty list - can be enhanced later
                
                # Rev 00230: Get 0DTE summary counts
                dte_symbols_count = len(self.dte0_manager.target_symbols) if self.dte0_manager else None
                dte_options_found = len(dte0_signals) if dte0_signals else None
                
                # Send alert (Rev 00230: Enhanced with Hard Gated symbols and summary counts)
                await self.alert_manager.send_options_execution_alert(
                    executed_positions=executed_positions_dict,
                    total_capital_deployed=total_capital_deployed,
                    account_balance=account_balance,
                    mode=mode,
                    rejected_signals=rejected_signals,  # Can be enhanced to track rejections
                    failed_count=failed_count,
                    hard_gated_symbols=hard_gated_symbols,  # Rev 00230: Pass Hard Gated symbols
                    dte_symbols_count=dte_symbols_count,  # Rev 00230: Pass 0DTE Symbols count
                    dte_options_found=dte_options_found  # Rev 00230: Pass 0DTE Options Found count
                )
                if executed_count > 0:
                    log.info(f"✅ 0DTE Strategy Options Execution alert sent - {executed_count} trades executed")
                else:
                    log.warning(f"⚠️ 0DTE Strategy Options Execution alert sent - 0 trades executed, {failed_count} failed")
            except Exception as e:
                log.error(f"Failed to send 0DTE options execution alert: {e}", exc_info=True)
    
    def _get_symbol_priorities(self) -> Dict[str, float]:
        """Get symbol priority scores for batch selection"""
        # Default priority scores (can be enhanced with sentiment, volume, etc.)
        priority_scores = {}
        
        # High priority for 3x leverage ETFs
        high_priority_3x = ["TQQQ", "SQQQ", "UPRO", "SPXU", "SPXL", "SPXS", "SOXL", "SOXS", "TECL", "TECS"]
        for symbol in high_priority_3x:
            priority_scores[symbol] = 1.0
        
        # Medium priority for 2x leverage ETFs
        medium_priority_2x = ["QQQ", "SPY", "IWM", "DIA", "ERX", "ERY", "TSLL", "TSLS", "NVDL", "NVDD"]
        for symbol in medium_priority_2x:
            priority_scores[symbol] = 0.7
        
        # Lower priority for individual stocks
        individual_stocks = ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "NFLX"]
        for symbol in individual_stocks:
            priority_scores[symbol] = 0.5
        
        return priority_scores
    
    def _calculate_adaptive_sleep_interval(self) -> float:
        """Calculate adaptive sleep interval based on market conditions and API limits"""
        try:
            # Base interval from config
            base_interval = getattr(self.config, 'main_loop_interval', 30.0)
            
            # Check API usage and adjust accordingly
            if hasattr(self, 'data_manager') and self.data_manager:
                api_summary = self.data_manager.get_api_usage_summary()
                
                # If approaching hourly limits, slow down
                usage_percentage = api_summary.get('hourly_usage', {}).get('usage_percentage', 0)
                if usage_percentage > 80:  # 80% of hourly limit
                    log.warning(f"⚠️ High API usage: {usage_percentage:.1f}%, slowing down")
                    return base_interval * 2  # Double the interval
                elif usage_percentage > 60:  # 60% of hourly limit
                    return base_interval * 1.5  # 1.5x the interval
            
            # Market volatility-based adjustment (if available)
            # This could be enhanced with real market volatility data
            market_volatility = 0.02  # Default 2% volatility
            
            if market_volatility > 0.03:  # High volatility
                return base_interval * 0.5  # Faster scanning
            elif market_volatility > 0.01:  # Medium volatility
                return base_interval  # Normal scanning
            else:  # Low volatility
                return base_interval * 1.5  # Slower scanning
            
        except Exception as e:
            log.error(f"Error calculating adaptive sleep interval: {e}")
            return 30.0  # Default fallback
    
    async def _batch_execute_live_signals(self, signals_to_execute: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Batch execute Live signals via E*TRADE (Rev 00180T - Simplified)
        
        Uses prime_etrade_trading.execute_batch_orders() for efficient batch execution
        
        Args:
            signals_to_execute: List of validated signal dictionaries with quantity
        
        Returns:
            Dict with executed and rejected signals
        """
        try:
            # Get E*TRADE trading instance
            etrade_trading = self.trade_manager.etrade_trading if self.trade_manager and hasattr(self.trade_manager, 'etrade_trading') else None
            
            if not etrade_trading:
                log.error("❌ E*TRADE trading not available for Live execution")
                return {'executed': [], 'rejected': signals_to_execute}
            
            # Execute batch via E*TRADE (uses built-in batch execution)
            log.info(f"🚀 Executing {len(signals_to_execute)} Live orders via E*TRADE batch...")
            
            batch_result = await asyncio.to_thread(
                etrade_trading.execute_batch_orders,
                signals_to_execute,
                max_concurrent=3
            )
            
            # Process results
            executed = []
            rejected = []
            
            for exec_order in batch_result.get('executed_orders', []):
                # Find matching signal
                matching_signal = next((s for s in signals_to_execute if s['symbol'] == exec_order['symbol']), None)
                if matching_signal:
                    executed.append(matching_signal)
                    
                    # Add to stealth trailing for exit management
                    if hasattr(self, 'stealth_trailing') and self.stealth_trailing:
                        try:
                            from .prime_models import PrimePosition, SignalSide
                            
                            stealth_position = PrimePosition(
                                position_id=exec_order.get('trade_id', f"POS_{exec_order['symbol']}"),
                                symbol=exec_order['symbol'],
                                side=SignalSide.LONG,
                                quantity=exec_order['quantity'],
                                entry_price=matching_signal['price'],
                                current_price=matching_signal['price'],
                                position_value=exec_order['quantity'] * matching_signal['price'],  # Oct 27, 2025: CRITICAL FIX
                                stop_loss=matching_signal.get('stop_loss'),
                                take_profit=matching_signal.get('take_profit'),
                                confidence=matching_signal.get('confidence', 0.85),
                                entry_time=datetime.utcnow()  # Rev 00072: Use UTC for consistent timezone handling
                            )
                            
                            # Rev 00080: Include ORB data for entry bar protection
                            orb_data = self.orb_manager.orb_data.get(exec_order['symbol'])
                            market_data = {
                                'price': matching_signal['price'],
                                'atr': matching_signal['price'] * 0.02,
                                'volume_ratio': 1.0,
                                'momentum': 0.0,
                                'volatility': 0.02,
                                'entry_bar_high': orb_data.orb_high if orb_data else matching_signal['price'] * 1.02,
                                'entry_bar_low': orb_data.orb_low if orb_data else matching_signal['price'] * 0.98
                            }
                            
                            await self.stealth_trailing.add_position(stealth_position, market_data)
                            log.info(f"   📊 Tracked in stealth trailing: {exec_order['symbol']}")
                        except Exception as e:
                            log.error(f"Failed to add Live position to stealth trailing: {e}")
            
            for failed_order in batch_result.get('failed_orders', []):
                matching_signal = next((s for s in signals_to_execute if s['symbol'] == failed_order['order']['symbol']), None)
                if matching_signal:
                    rejected.append(matching_signal)
            
            log.info(f"✅ Live batch execution: {batch_result['success_count']}/{len(signals_to_execute)} orders executed")
            
            return {
                'executed': executed,
                'rejected': rejected,
                'batch_result': batch_result
            }
            
        except Exception as e:
            log.error(f"Batch execution failed: {e}", exc_info=True)
            return {'executed': [], 'rejected': signals_to_execute}
    
    async def _process_orb_signals(self, orb_signals: List[Dict[str, Any]]):
        """
        Process ORB signals through the trading system (Demo or Live Mode)
        
        ORB signals include:
        - SO (Standard Order) at 7:15 AM PT
        - ORR (Opening Range Reversal) 7:15-9:15 AM PT
        - Inverse ETF support for bearish signals
        
        Sends aggregated SO alerts and individual ORR alerts.
        """
        try:
            if not self.trade_manager:
                log.error("Trade manager not available")
                return
            
            # Determine trading mode
            trading_mode = self._get_trading_mode()
            mode_display = "DEMO" if trading_mode == "DEMO_MODE" else "LIVE"
            
            log.info(f"🎯 Processing {len(orb_signals)} ORB signals in {trading_mode} mode...")
            
            # Separate SO and ORR signals for different alert handling
            so_signals = [s for s in orb_signals if s.get('signal_type') == 'SO']
            orr_signals = [s for s in orb_signals if s.get('signal_type') == 'ORR']
            
            # DIAGNOSTIC (Rev 00180): Enhanced logging for signal generation debugging
            log.info(f"📊 Signal breakdown BEFORE filtering: {len(so_signals)} SO, {len(orr_signals)} ORR from {len(orb_signals)} total")
            if so_signals:
                log.info(f"✅ SO Signals found: {[s.get('symbol') for s in so_signals]}")
            else:
                log.warning(f"⚠️ NO SO signals generated from ORB scan - checking why...")
            
            # Determine account value and capital allocation BEFORE processing signals
            # This ensures orr_reserve is defined even if so_signals is empty
            account_value = 1000.0  # Default fallback
            try:
                if trading_mode == "DEMO_MODE" and hasattr(self, 'mock_executor') and self.mock_executor:
                    # Get Demo account balance
                    if hasattr(self.mock_executor, 'account_balance'):
                        # 🔧 CRITICAL FIX (Rev 00107 - Nov 6, 2025): Demo Mode ALWAYS resets to $1,000 daily
                        # ROOT CAUSE: Cloud Run instances can persist across days
                        # Without reset: account_balance can be depleted to $0 from previous day's losses
                        # Demo mode is for testing - should start fresh each trading day
                        
                        current_balance = self.mock_executor.account_balance
                        
                        # Rev 00135: Use actual account balance (no more resets)
                        # Account balance persists between days via GCS storage
                        if current_balance is None:
                            log.warning(f"⚠️ Demo Mode: account_balance is None, using default $1,000")
                            self.mock_executor.account_balance = 1000.0
                            account_value = 1000.0
                        else:
                            # Use actual balance (tracks multi-day profits/losses)
                            account_value = current_balance
                            log.info(f"✅ Demo Mode: Account balance ${account_value:,.2f} (persistent balance)")
                elif trading_mode == "LIVE_MODE" and self.trade_manager:
                    # Get Live account balance from E*TRADE
                    try:
                        if hasattr(self.trade_manager, 'etrade_trading') and self.trade_manager.etrade_trading:
                            account_summary = self.trade_manager.etrade_trading.get_account_summary()
                            if account_summary and 'balance' in account_summary:
                                balance = account_summary['balance']
                                # Use cash available for investment
                                if 'cash_available_for_investment' in balance:
                                    account_value = float(balance['cash_available_for_investment'])
                                    log.info(f"💰 Live Mode: Account balance ${account_value:,.0f} from E*TRADE")
                                elif 'cash_buying_power' in balance:
                                    account_value = float(balance['cash_buying_power'])
                                    log.info(f"💰 Live Mode: Using buying power ${account_value:,.0f} from E*TRADE")
                                else:
                                    log.warning("⚠️ Live Mode: Could not find cash balance in account summary, using default")
                            else:
                                log.warning("⚠️ Live Mode: Could not get account summary, using default")
                    except Exception as e:
                        log.warning(f"⚠️ Live Mode: Error getting E*TRADE balance: {e}, using default")
            except Exception as e:
                log.warning(f"⚠️ Error determining account value: {e}, using default ${account_value:,.0f}")
                account_value = 1000.0
            
            # Capital allocation (Rev 00046: Define BEFORE signal processing)
            # Oct 24, 2025: Use unified config (adjustable in one place)
            so_capital = account_value * (self.config.so_capital_pct / 100.0)
            orr_reserve = account_value * (self.config.orr_capital_pct / 100.0)
            cash_reserve = account_value * (self.config.cash_reserve_pct / 100.0)
            
            # Set ORR enabled flag
            self._orr_enabled = (orr_reserve > 0)
            
            log.info(f"📊 Capital Allocation: SO ${so_capital:,.0f} ({self.config.so_capital_pct:.0f}%), "
                    f"ORR {'ENABLED' if self._orr_enabled else 'DISABLED'} ({self.config.orr_capital_pct:.0f}%), "
                    f"Cash Reserve ${cash_reserve:,.0f} ({self.config.cash_reserve_pct:.0f}%)")
            
            # CRITICAL FIX (Rev 00163): Limit SO trades based on account size
            # ENHANCED (Rev 00170): Multi-factor ranking with volatility and volume
            if so_signals:
                # Rev 00141: Enrich signals with technical data from orb_data and metadata
                async def enrich_signal_with_technical_data(signal):
                    """Extract technical indicators from orb_data, metadata, and data_manager"""
                    symbol = signal.get('symbol', '')
                    
                    # Extract from orb_data
                    orb_data = signal.get('orb_data', {})
                    if orb_data:
                        signal['orb_high'] = orb_data.get('high', orb_data.get('orb_high', signal.get('orb_high', 0)))
                        signal['orb_low'] = orb_data.get('low', orb_data.get('orb_low', signal.get('orb_low', 0)))
                        if signal['orb_low'] > 0:
                            signal['orb_range_pct'] = ((signal['orb_high'] - signal['orb_low']) / signal['orb_low']) * 100
                        else:
                            signal['orb_range_pct'] = 0
                        # Extract ORB volume if available
                        signal['orb_volume_ratio'] = orb_data.get('volume_ratio', signal.get('orb_volume_ratio', 0))
                    
                    # Extract from metadata
                    metadata = signal.get('metadata', {})
                    if metadata:
                        signal['rsi'] = metadata.get('rsi', signal.get('rsi', 0))
                        signal['volume_ratio'] = metadata.get('volume_ratio', signal.get('volume_ratio', signal.get('orb_volume_ratio', 0)))
                        signal['orb_volume_ratio'] = metadata.get('orb_volume_ratio', signal.get('orb_volume_ratio', signal.get('volume_ratio', 0)))
                        signal['exec_volume_ratio'] = metadata.get('exec_volume_ratio', signal.get('exec_volume_ratio', 0))
                        signal['vwap_distance_pct'] = metadata.get('vwap_distance_pct', signal.get('vwap_distance_pct', 0))
                        signal['rs_vs_spy'] = metadata.get('rs_vs_spy', signal.get('rs_vs_spy', 0))
                        signal['leverage'] = metadata.get('leverage', signal.get('leverage', ''))
                        signal['category'] = metadata.get('category', signal.get('category', ''))
                    
                    # Rev 00148: Get comprehensive technical indicators from E*TRADE for Priority Optimizer
                    # CRITICAL FIX: Improved error handling and ensure all indicators are collected
                    if hasattr(self, 'trade_manager') and self.trade_manager and hasattr(self.trade_manager, 'etrade_trading') and self.trade_manager.etrade_trading:
                        try:
                            # Get comprehensive market data with technical indicators (on-demand from yfinance)
                            comprehensive_data = self.trade_manager.etrade_trading.get_market_data_for_strategy(symbol)
                            if comprehensive_data:
                                # Extract technical indicators for Priority Optimizer (all 18 indicators)
                                indicators_collected = 0
                                indicators_missing = []
                                
                                # Rev 00208: FIX - Use proper None check instead of 'or' operator
                                # The 'or' operator treats 0.0 as falsy, causing valid 0.0 values to be replaced with defaults
                                # Use 'is not None' check to preserve valid 0.0 values while handling None correctly
                                
                                # Momentum Indicators
                                rsi_val = comprehensive_data.get('rsi')
                                signal['rsi'] = rsi_val if rsi_val is not None else signal.get('rsi', 0)
                                if rsi_val is not None: indicators_collected += 1
                                else: indicators_missing.append('rsi')
                                
                                rsi_14_val = comprehensive_data.get('rsi_14')
                                signal['rsi_14'] = rsi_14_val if rsi_14_val is not None else signal.get('rsi_14', signal.get('rsi', 0))
                                if rsi_14_val is not None: indicators_collected += 1
                                else: indicators_missing.append('rsi_14')
                                
                                macd_val = comprehensive_data.get('macd')
                                signal['macd'] = macd_val if macd_val is not None else signal.get('macd', 0)
                                if macd_val is not None: indicators_collected += 1
                                else: indicators_missing.append('macd')
                                
                                macd_signal_val = comprehensive_data.get('macd_signal')
                                signal['macd_signal'] = macd_signal_val if macd_signal_val is not None else signal.get('macd_signal', 0)
                                if macd_signal_val is not None: indicators_collected += 1
                                else: indicators_missing.append('macd_signal')
                                
                                macd_hist_val = comprehensive_data.get('macd_histogram')
                                signal['macd_histogram'] = macd_hist_val if macd_hist_val is not None else signal.get('macd_histogram', 0)
                                if macd_hist_val is not None: indicators_collected += 1
                                else: indicators_missing.append('macd_histogram')
                                
                                # Trend Indicators
                                sma_20_val = comprehensive_data.get('sma_20')
                                signal['sma_20'] = sma_20_val if sma_20_val is not None else signal.get('sma_20', 0)
                                if sma_20_val is not None: indicators_collected += 1
                                else: indicators_missing.append('sma_20')
                                
                                sma_50_val = comprehensive_data.get('sma_50')
                                signal['sma_50'] = sma_50_val if sma_50_val is not None else signal.get('sma_50', 0)
                                if sma_50_val is not None: indicators_collected += 1
                                else: indicators_missing.append('sma_50')
                                
                                ema_12_val = comprehensive_data.get('ema_12')
                                signal['ema_12'] = ema_12_val if ema_12_val is not None else signal.get('ema_12', 0)
                                if ema_12_val is not None: indicators_collected += 1
                                else: indicators_missing.append('ema_12')
                                
                                ema_26_val = comprehensive_data.get('ema_26')
                                signal['ema_26'] = ema_26_val if ema_26_val is not None else signal.get('ema_26', 0)
                                if ema_26_val is not None: indicators_collected += 1
                                else: indicators_missing.append('ema_26')
                                
                                # Volatility Indicators
                                atr_val = comprehensive_data.get('atr')
                                signal['atr'] = atr_val if atr_val is not None else signal.get('atr', 0)
                                if atr_val is not None: indicators_collected += 1
                                else: indicators_missing.append('atr')
                                
                                bb_upper_val = comprehensive_data.get('bollinger_upper')
                                signal['bollinger_upper'] = bb_upper_val if bb_upper_val is not None else signal.get('bollinger_upper', 0)
                                if bb_upper_val is not None: indicators_collected += 1
                                else: indicators_missing.append('bollinger_upper')
                                
                                bb_middle_val = comprehensive_data.get('bollinger_middle')
                                signal['bollinger_middle'] = bb_middle_val if bb_middle_val is not None else signal.get('bollinger_middle', 0)
                                if bb_middle_val is not None: indicators_collected += 1
                                else: indicators_missing.append('bollinger_middle')
                                
                                bb_lower_val = comprehensive_data.get('bollinger_lower')
                                signal['bollinger_lower'] = bb_lower_val if bb_lower_val is not None else signal.get('bollinger_lower', 0)
                                if bb_lower_val is not None: indicators_collected += 1
                                else: indicators_missing.append('bollinger_lower')
                                
                                bb_width_val = comprehensive_data.get('bollinger_width')
                                signal['bollinger_width'] = bb_width_val if bb_width_val is not None else signal.get('bollinger_width', 0)
                                if bb_width_val is not None: indicators_collected += 1
                                else: indicators_missing.append('bollinger_width')
                                
                                # Volume Indicators
                                volume_ratio_val = comprehensive_data.get('volume_ratio')
                                signal['volume_ratio'] = volume_ratio_val if volume_ratio_val is not None else signal.get('volume_ratio', signal.get('orb_volume_ratio', 0))
                                if volume_ratio_val is not None: indicators_collected += 1
                                else: indicators_missing.append('volume_ratio')
                                
                                # VWAP and Relative Strength (may need to be calculated)
                                signal['vwap'] = comprehensive_data.get('vwap') or signal.get('vwap', 0)
                                if comprehensive_data.get('vwap'): indicators_collected += 1
                                else: indicators_missing.append('vwap')
                                
                                # VWAP distance and RS vs SPY should already be in signal from metadata
                                signal['vwap_distance_pct'] = signal.get('vwap_distance_pct', 0)  # From metadata
                                signal['rs_vs_spy'] = signal.get('rs_vs_spy', 0)  # From metadata
                                
                                # Volatility (ATR-based or price-based)
                                signal['volatility'] = comprehensive_data.get('volatility') or signal.get('volatility', 0)
                                if comprehensive_data.get('volatility'): indicators_collected += 1
                                else: indicators_missing.append('volatility')
                                
                                if indicators_collected >= 15:
                                    log.info(f"✅ Enriched {symbol} with {indicators_collected}/18 technical indicators for Priority Optimizer")
                                elif indicators_collected >= 10:
                                    log.warning(f"⚠️ Partially enriched {symbol} with {indicators_collected}/18 indicators (missing: {', '.join(indicators_missing[:5])})")
                                else:
                                    log.warning(f"⚠️ Limited enrichment for {symbol}: only {indicators_collected}/18 indicators collected (missing: {', '.join(indicators_missing[:8])})")
                            else:
                                log.warning(f"⚠️ No comprehensive data returned for {symbol} - Priority Optimizer data incomplete")
                                log.warning(f"   • get_market_data_for_strategy() returned None or empty - check ETrade API connectivity")
                                # Rev 00233: FIX - Use neutral fallback values instead of 0 to prevent data quality issues
                                # Use RSI=50 (neutral) and Volume=1.0 (normal) instead of 0 to prevent Red Day Filter fail-safe mode
                                try:
                                    fallback_data = self.trade_manager.etrade_trading._get_fallback_market_data(symbol)
                                    if fallback_data:
                                        signal['rsi'] = fallback_data.get('rsi', 50.0)  # Use fallback RSI=50.0 instead of 0
                                        signal['volume_ratio'] = fallback_data.get('volume_ratio', 1.0)  # Use fallback Volume=1.0 instead of 0
                                        signal['macd_histogram'] = fallback_data.get('macd_histogram', 0.0)
                                        log.info(f"   ✅ Applied fallback data for {symbol}: RSI={fallback_data.get('rsi')}, Volume={fallback_data.get('volume_ratio')}")
                                    else:
                                        # Rev 00233: Use neutral defaults instead of 0 to prevent data quality issues
                                        signal['rsi'] = signal.get('rsi', 50.0) if signal.get('rsi', 0) > 0 else 50.0
                                        signal['volume_ratio'] = signal.get('volume_ratio', 1.0) if signal.get('volume_ratio', 0) > 0 else 1.0
                                        log.warning(f"   ⚠️ Using neutral defaults for {symbol}: RSI=50.0 (neutral), Volume=1.0x (normal)")
                                        log.warning(f"   • This prevents Red Day Filter from entering fail-safe mode due to invalid data")
                                except Exception as fallback_error:
                                    log.debug(f"   ⚠️ Could not apply fallback data for {symbol}: {fallback_error}")
                                    # Rev 00233: Use neutral defaults as last resort
                                    signal['rsi'] = signal.get('rsi', 50.0) if signal.get('rsi', 0) > 0 else 50.0
                                    signal['volume_ratio'] = signal.get('volume_ratio', 1.0) if signal.get('volume_ratio', 0) > 0 else 1.0
                                    log.warning(f"   ⚠️ Applied neutral defaults for {symbol}: RSI=50.0, Volume=1.0x")
                        except Exception as e:
                            log.error(f"❌ Failed to fetch comprehensive technical data for {symbol}: {e}", exc_info=True)
                            log.warning(f"⚠️ Priority Optimizer data will be incomplete for {symbol}")
                            log.warning(f"   • Data enrichment failure may cause Red Day Filter to use invalid data (RSI=0, Volume=0)")
                            log.warning(f"   • Red Day Filter will enter fail-safe mode if all signals have invalid data")
                    
                    return signal
                
                # Enrich all signals with technical data before ranking
                enriched_signals = []
                for sig in so_signals:
                    enriched = await enrich_signal_with_technical_data(sig.copy())
                    enriched_signals.append(enriched)
                so_signals = enriched_signals
                
                # Enhanced ranking function with volatility and volume filters
                def calculate_so_priority_score(signal):
                    """
                    Calculate multi-factor priority score for SO signals
                    
                    Rev 00106: Formula v2.1 - DATA-DRIVEN REFINEMENT (Nov 6, 2025)
                    Based on comprehensive correlation analysis (Nov 6):
                    
                    CORRELATION EVIDENCE (Nov 6 - 15 signals):
                    - VWAP Distance: +0.772 correlation ⭐⭐⭐ STRONGEST PREDICTOR!
                    - RS vs SPY: +0.609 correlation ⭐⭐⭐ 2ND STRONGEST!
                    - ORB Volume: +0.342 correlation ✅ MODERATE
                    - Confidence: +0.333 correlation ⚠️ WEAK (inconsistent)
                    - RSI: -0.096 correlation ⚠️ NEGATIVE (context-dependent)
                    
                    TOP PERFORMER VALIDATION (Nov 6):
                    - TSDD (+3.24% P&L): Had HIGHEST VWAP Distance (+3.35%) ✅
                    - TSDD: Strong RS vs SPY (+8.16%) ✅
                    - AMDD (95% conf): Only +1.03% P&L (#14/15) - confidence not predictive!
                    
                    Formula v2.1 Weights (Conservative +2% Adjustments):
                    - VWAP Distance: 27% (↑ +2% - exceptional +0.772 correlation) ⭐
                    - RS vs SPY: 25% (same - strong +0.609 correlation) ⭐
                    - ORB Volume: 22% (↑ +2% - moderate +0.342 correlation)
                    - Confidence: 13% (↓ -2% - weak +0.333 correlation)
                    - RSI: 10% (same - context-aware for bull/bear markets)
                    - ORB Range: 3% (↓ -2% - minimal contribution)
                    
                    Changes from v2.0 → v2.1:
                    - More weight to proven predictors (VWAP, Volume)
                    - Less weight to weak predictors (Confidence, ORB Range)
                    - Evidence-based, conservative adjustments
                    
                    Expected: +10-15% better capital allocation vs v2.0
                    """
                    symbol = signal.get('symbol', '')
                    
                    # Factor 1: RS vs SPY (25%) - Rev 00104: NEW ⭐⭐⭐
                    # Top performers on Nov 5: +27-28% vs SPY (market leaders)
                    rs_vs_spy = signal.get('rs_vs_spy', 0)
                    
                    if rs_vs_spy >= 20.0:
                        rs_score = 1.0           # Massive outperformance (>+20%)
                    elif rs_vs_spy >= 10.0:
                        rs_score = 0.85          # Strong outperformance (+10-20%)
                    elif rs_vs_spy >= 5.0:
                        rs_score = 0.70          # Good outperformance (+5-10%)
                    elif rs_vs_spy >= 0.0:
                        rs_score = 0.50          # Inline with market (0-5%)
                    elif rs_vs_spy >= -10.0:
                        rs_score = 0.35          # Slight underperformance (0 to -10%)
                    else:
                        rs_score = 0.20          # Underperforming (<-10%)
                    
                    # Factor 2: VWAP Distance (25%) - Rev 00104: NEW ⭐⭐⭐
                    # Top performers on Nov 5: +18-20% above VWAP (institutional support)
                    vwap_distance = signal.get('vwap_distance_pct', 0)
                    
                    if vwap_distance >= 15.0:
                        vwap_score = 1.0         # Far above VWAP (>+15%)
                    elif vwap_distance >= 10.0:
                        vwap_score = 0.90        # Well above VWAP (+10-15%)
                    elif vwap_distance >= 5.0:
                        vwap_score = 0.75        # Above VWAP (+5-10%)
                    elif vwap_distance >= 0.0:
                        vwap_score = 0.60        # At/slightly above VWAP (0-5%)
                    elif vwap_distance >= -3.0:
                        vwap_score = 0.40        # Slightly below VWAP (0 to -3%)
                    else:
                        vwap_score = 0.20        # Below VWAP (<-3%)
                    
                    # Factor 3: ORB Volume Ratio (20%) - Rev 00104: Reduced from 40%
                    # Still important but less than VWAP/RS discoveries
                    orb_volume_ratio = signal.get('volume_ratio', 1.0)
                    
                    if orb_volume_ratio >= 3.0:
                        orb_vol_score = 1.0      # Exceptional
                    elif orb_volume_ratio >= 2.0:
                        orb_vol_score = 0.85     # Strong
                    elif orb_volume_ratio >= 1.5:
                        orb_vol_score = 0.70     # Good
                    elif orb_volume_ratio >= 1.2:
                        orb_vol_score = 0.50     # Moderate
                    else:
                        orb_vol_score = 0.25     # Weak
                    
                    # Factor 4: Confidence (15%) - Rev 00104: RE-ADDED ⭐⭐
                    # Nov 5 discovery: 95% confidence = top 2 performers
                    # Was removed (Rev 00091) due to -0.298 correlation on holiday days
                    # Re-added based on positive correlation on normal trading days
                    confidence = signal.get('confidence', 0.5)
                    
                    # Scale 0.5-1.0 → 0-1.0
                    if confidence >= 0.5:
                        conf_score = (confidence - 0.5) / 0.5
                        conf_score = min(1.0, conf_score)
                    else:
                        conf_score = 0.0
                    
                    # Factor 5: RSI Context-Aware (10%) - Rev 00104: REVISED ⭐⭐
                    # Nov 5 discovery: High RSI (70-75) = top performers in BULL markets
                    # Nov 1 data: High RSI (>65) = losers in weak markets
                    # Solution: Context-aware scoring based on market regime
                    rsi = signal.get('rsi', 55.0)
                    market_regime = signal.get('market_regime', 'MIXED')  # Will be added to signals
                    
                    if market_regime == 'BULL':
                        # Bull market: High RSI = momentum (not overbought)
                        if 65 <= rsi <= 75:
                            rsi_score = 0.85     # Strong momentum ⭐ REVISED
                        elif 55 <= rsi < 65:
                            rsi_score = 1.0      # Sweet spot
                        elif 50 <= rsi < 55:
                            rsi_score = 0.90     # Good
                        elif 45 <= rsi < 50:
                            rsi_score = 0.75     # Acceptable
                        elif rsi > 75:
                            rsi_score = 0.60     # Getting too high even for bull
                        else:  # rsi < 45
                            rsi_score = 0.40     # Weak even in bull market
                    else:
                        # Non-bull market: High RSI = overbought (penalty)
                        if 50 <= rsi <= 60:
                            rsi_score = 1.0      # Sweet spot
                        elif 45 <= rsi < 50:
                            rsi_score = 0.85     # Good
                        elif 60 < rsi <= 65:
                            rsi_score = 0.70     # Getting high
                        elif rsi > 65:
                            rsi_score = 0.30     # PENALTY (overbought)
                        elif 40 <= rsi < 45:
                            rsi_score = 0.75     # Acceptable
                        else:  # rsi < 40
                            rsi_score = 0.60     # Weak
                    
                    # Factor 6: ORB Range % - Volatility (5%) - Rev 00104: Reduced from 30%
                    # Less predictive than VWAP/RS discoveries
                    orb_high = signal.get('orb_high', 0)
                    orb_low = signal.get('orb_low', 0)
                    if orb_low > 0:
                        orb_range_pct = (orb_high - orb_low) / orb_low
                    else:
                        orb_range_pct = 0.01
                    orb_range_score = min(orb_range_pct / 0.05, 1.0)  # 1.0 at 5%+
                    
                    # Rev 00106: Formula v2.1 - DATA-DRIVEN REFINEMENT (Nov 6, 2025)
                    # Conservative +2% adjustments based on correlation analysis
                    # Evidence: VWAP +0.772, RS +0.609, Volume +0.342, Confidence +0.333
                    priority_score = (
                        vwap_score * 0.27 +           # 27% - VWAP Distance ⭐ (↑ +2%, correlation +0.772)
                        rs_score * 0.25 +             # 25% - RS vs SPY ⭐ (same, correlation +0.609)
                        orb_vol_score * 0.22 +        # 22% - ORB volume (↑ +2%, correlation +0.342)
                        conf_score * 0.13 +           # 13% - Confidence (↓ -2%, correlation +0.333 weak)
                        rsi_score * 0.10 +            # 10% - RSI (same, context-aware)
                        orb_range_score * 0.03        # 3% - ORB range (↓ -2%, minimal contribution)
                    )
                    
                    # Rev 00141: Store calculated values in signal for data collection
                    signal['priority_score'] = priority_score
                    signal['rs_vs_spy'] = rs_vs_spy
                    signal['vwap_distance_pct'] = vwap_distance
                    signal['volume_ratio'] = orb_volume_ratio
                    signal['orb_volume_ratio'] = orb_volume_ratio
                    signal['rsi'] = rsi
                    signal['orb_range_pct'] = orb_range_pct
                    
                    return priority_score
                
                # Rank by multi-factor score (highest first)
                so_signals_ranked = sorted(so_signals, 
                                          key=calculate_so_priority_score, 
                                          reverse=True)
                
                # Rev 00141: Add priority_score to each signal after ranking
                for sig in so_signals_ranked:
                    sig['priority_score'] = calculate_so_priority_score(sig)
                
                # Rev 00180f: Filter out already-executed SO symbols (prevents duplicates)
                if not hasattr(self, '_so_executed_symbols_today'):
                    self._so_executed_symbols_today = set()
                
                original_count = len(so_signals_ranked)
                so_signals_ranked = [s for s in so_signals_ranked if s.get('symbol') not in self._so_executed_symbols_today]
                
                if original_count > len(so_signals_ranked):
                    filtered_count = original_count - len(so_signals_ranked)
                    log.info(f"🔒 Filtered {filtered_count} already-executed SO symbols: {[s.get('symbol') for s in so_signals if s.get('symbol') in self._so_executed_symbols_today]}")
                
                # If all signals already executed, skip processing
                if not so_signals_ranked:
                    log.info("✅ All SO signals already executed today - skipping")
                    return
                
                # Log top 3 for verification
                if len(so_signals_ranked) >= 3:
                    log.info(f"🎯 Top 3 SO Signals by Multi-Factor Score (Rev 00104: VWAP + RS vs SPY + Confidence):")
                    for i, sig in enumerate(so_signals_ranked[:3], 1):
                        score = calculate_so_priority_score(sig)
                        orb_range = ((sig.get('orb_high', 0) - sig.get('orb_low', 0)) / sig.get('orb_low', 1)) * 100
                        log.info(f"   {i}. {sig.get('symbol', 'N/A')}: Score {score:.3f} "
                                f"(Conf {sig.get('confidence', 0):.2f}, RSI {sig.get('rsi', 55):.1f}, "
                                f"VWAP {sig.get('vwap_distance_pct', 0):+.1f}%, RS vs SPY {sig.get('rs_vs_spy', 0):+.1f}%)")
                
                # ========================================================================
                # REV 00104: RED DAY FILTER (Factor 1 - Capital Preservation)
                # REV 00180: FIXED - Pattern 3 independent override + real-time data verification
                # ========================================================================
                # Detects bad market conditions and skips execution to preserve capital
                # Based on 89-field data collection (Nov 4-5, 2025)
                # 
                # Rev 00180 Fixes:
                # 1. Pattern 3 now has independent override logic (not dependent on Pattern 2)
                # 2. Added data source verification logging to ensure real-time data is used
                # 3. Enhanced logging for Pattern 3 override conditions
                # 
                # Pattern discovered:
                # - Nov 4 (RED DAY): 80% RSI <40 + 90% weak volume → ALL lost (-0.98% avg)
                # - Nov 5 (GREEN): 14% RSI <40 + 86% weak volume → 86% winning (+1.36% avg)
                # 
                # Red Day Rule: IF >70% signals RSI <40 AND >80% signals volume <1.0x → SKIP
                # Expected savings: $11-27 per red day = $400-1,600/year
                
                log.info(f"")
                log.info(f"=" * 80)
                log.info(f"🚨 ENHANCED RED DAY FILTER CHECK (Rev 00136 - Multi-Factor)")
                log.info(f"=" * 80)
                
                # Calculate aggregate metrics for red day detection
                # Rev 00169: Enhanced to detect both OVERSOLD and OVERBOUGHT patterns
                # Rev 00180: FIXED - Use enriched signals (real-time data) not stale signal creation data
                # CRITICAL: so_signals_ranked should already be enriched with real-time data from enrich_signal_with_technical_data()
                num_signals = len(so_signals_ranked)
                
                # Rev 00180: Log data source verification
                if num_signals > 0:
                    sample_sig = so_signals_ranked[0]
                    log.info(f"   📊 Data Source Verification (Rev 00180):")
                    log.info(f"      • Sample signal: {sample_sig.get('symbol', 'N/A')}")
                    log.info(f"      • RSI: {sample_sig.get('rsi', 'N/A')} (from enriched data)")
                    log.info(f"      • MACD Histogram: {sample_sig.get('macd_histogram', 'N/A')} (from enriched data)")
                    log.info(f"      • RS vs SPY: {sample_sig.get('rs_vs_spy', 'N/A')} (from enriched data)")
                    log.info(f"      • VWAP Distance: {sample_sig.get('vwap_distance_pct', 'N/A')}% (from enriched data)")
                    log.info(f"      • Volume Ratio: {sample_sig.get('volume_ratio', 'N/A')} (from enriched data)")
                
                # Rev 00233: Improved data validation - filter out invalid values (0.0, None) before calculations
                # Use neutral defaults (RSI=50, Volume=1.0) for missing data to prevent false Red Day detection
                def get_valid_rsi(sig):
                    rsi = sig.get('rsi', 50)
                    # Return neutral RSI=50 if value is invalid (None, 0.0, or negative)
                    if rsi is None or rsi <= 0:
                        return 50.0
                    return float(rsi)
                
                def get_valid_volume(sig):
                    vol = sig.get('volume_ratio', sig.get('orb_volume_ratio', 1.0))
                    # Return neutral Volume=1.0 if value is invalid (None, 0.0, or negative)
                    if vol is None or vol <= 0:
                        return 1.0
                    return float(vol)
                
                signals_with_low_rsi = sum(1 for sig in so_signals_ranked if get_valid_rsi(sig) < 40)
                signals_with_high_rsi = sum(1 for sig in so_signals_ranked if get_valid_rsi(sig) > 80)
                signals_with_weak_volume = sum(1 for sig in so_signals_ranked if get_valid_volume(sig) < 1.0)
                
                pct_low_rsi = (signals_with_low_rsi / num_signals * 100) if num_signals > 0 else 0
                pct_high_rsi = (signals_with_high_rsi / num_signals * 100) if num_signals > 0 else 0
                pct_weak_volume = (signals_with_weak_volume / num_signals * 100) if num_signals > 0 else 0
                
                # Calculate averages with improved data validation (Rev 00233)
                rsi_values = [get_valid_rsi(sig) for sig in so_signals_ranked]
                volume_values = [get_valid_volume(sig) for sig in so_signals_ranked]

                avg_rsi = sum(rsi_values) / len(rsi_values) if rsi_values else 0.0
                avg_volume = sum(volume_values) / len(volume_values) if volume_values else 0.0

                # Flag data quality issues
                rsi_data_missing = len(rsi_values) < num_signals
                volume_data_missing = len(volume_values) < num_signals
                
                # Rev 00171: Calculate momentum and relative strength metrics for override checks
                # Rev 00180: Using enriched real-time data (not stale signal creation data)
                avg_macd_histogram = sum(sig.get('macd_histogram', 0) for sig in so_signals_ranked) / num_signals if num_signals > 0 else 0
                avg_rs_vs_spy = sum(sig.get('rs_vs_spy', 0) for sig in so_signals_ranked) / num_signals if num_signals > 0 else 0
                # Rev 00173: Calculate VWAP distance for additional override check
                avg_vwap_distance = sum(sig.get('vwap_distance_pct', 0) for sig in so_signals_ranked) / num_signals if num_signals > 0 else 0
                
                log.info(f"   Signals Analyzed: {num_signals}")
                log.info(f"   Avg RSI: {avg_rsi:.1f} {'⚠️ INVALID DATA' if avg_rsi == 0.0 else ''}")
                log.info(f"   Signals RSI <40 (oversold): {signals_with_low_rsi}/{num_signals} ({pct_low_rsi:.0f}%)")
                log.info(f"   Signals RSI >80 (overbought): {signals_with_high_rsi}/{num_signals} ({pct_high_rsi:.0f}%)")
                log.info(f"   Avg Volume: {avg_volume:.2f}x {'⚠️ NO VOLUME DATA' if avg_volume == 0.0 else ''}")
                log.info(f"   Signals Volume <1.0x: {signals_with_weak_volume}/{num_signals} ({pct_weak_volume:.0f}%)")
                log.info(f"   Avg MACD Histogram: {avg_macd_histogram:.3f} (momentum)")
                log.info(f"   Avg RS vs SPY: {avg_rs_vs_spy:.2f} (relative strength)")
                log.info(f"   Avg VWAP Distance: {avg_vwap_distance:.2f}% (institutional support)")

                # Log data quality warnings
                if rsi_data_missing:
                    log.warning(f"   ⚠️ RSI DATA QUALITY: {len(rsi_values)}/{num_signals} signals have valid RSI data")
                if volume_data_missing:
                    log.warning(f"   ⚠️ VOLUME DATA QUALITY: {len(volume_values)}/{num_signals} signals have valid volume data")
                log.info(f"")
                
                # RED DAY THRESHOLDS (Rev 00169: Enhanced for both patterns)
                # Pattern 1: OVERSOLD + WEAK VOLUME (original - Nov 4 pattern)
                # Pattern 2: OVERBOUGHT + WEAK VOLUME (new - Dec 5 pattern)
                RED_DAY_RSI_LOW_THRESHOLD = 70.0        # >70% signals oversold (RSI <40)
                RED_DAY_RSI_HIGH_THRESHOLD = 80.0       # >80% signals overbought (RSI >80) - Rev 00169
                RED_DAY_VOLUME_THRESHOLD = 80.0         # >80% signals weak volume
                
                # Rev 00171: MOMENTUM & RELATIVE STRENGTH OVERRIDE (initialize before pattern checks)
                # If Pattern 2 is detected but momentum/RS is strong, allow trading
                # This prevents blocking profitable days like Dec 8 while still blocking Dec 5
                momentum_override = False
                MIN_MACD_HISTOGRAM = 0.0  # Positive momentum required
                MIN_RS_VS_SPY = 2.0       # Strong relative strength required
                MIN_MACD_FOR_SOLO_OVERRIDE = 10.0  # Rev 00172: Very strong MACD can override alone if RS vs SPY missing/0
                MIN_VWAP_DISTANCE = 1.0   # Rev 00173: Strong institutional support (VWAP distance > 1.0%)
                
                # Rev 00206: DATA QUALITY VALIDATION - Fail-safe mode when data is invalid
                # Rev 00233: FIX - Clear is_red_day flag on signals when fail-safe mode activates
                # If critical data (RSI, Volume) is invalid (0.0), skip Red Day Filter to prevent false negatives
                # This ensures profitable trades aren't blocked due to data collection failures
                if avg_rsi == 0.0 or avg_volume == 0.0:
                    log.warning(f"")
                    log.warning(f"⚠️" * 40)
                    log.warning(f"⚠️ DATA QUALITY ISSUE: Cannot evaluate Red Day Filter")
                    log.warning(f"⚠️" * 40)
                    log.warning(f"   • Avg RSI: {avg_rsi:.1f} {'⚠️ INVALID' if avg_rsi == 0.0 else ''}")
                    log.warning(f"   • Avg Volume: {avg_volume:.2f}x {'⚠️ NO DATA' if avg_volume == 0.0 else ''}")
                    log.warning(f"   • Avg MACD Histogram: {avg_macd_histogram:.3f}")
                    log.warning(f"   • Signals with valid RSI: {len(rsi_values)}/{num_signals}")
                    log.warning(f"   • Signals with valid Volume: {len(volume_values)}/{num_signals}")
                    log.warning(f"")
                    log.warning(f"   🔧 FAIL-SAFE MODE: Skipping Red Day Filter - allowing trading")
                    log.warning(f"   📊 Reason: Invalid data prevents accurate pattern detection")
                    log.warning(f"   ✅ Trading will proceed (better than blocking profitable trades with invalid data)")
                    log.warning(f"")
                    # Rev 00206 FIX: Set all patterns to False and skip ALL pattern evaluation
                    # Rev 00233: CRITICAL FIX - Clear is_red_day flag on all signals when fail-safe mode activates
                    # This ensures 0DTE filter doesn't reject signals based on invalid Red Day detection
                    pattern1_oversold = False
                    pattern2_overbought = False
                    pattern3_weak_volume_only = False
                    momentum_override = False  # Not needed in fail-safe mode
                    # Clear is_red_day flag on all signals to prevent 0DTE filter rejection
                    for sig in so_signals_ranked:
                        sig['is_red_day'] = False
                    log.info(f"✅ FAIL-SAFE MODE: Red Day Filter bypassed - trading will proceed")
                    log.info(f"   🔧 Cleared is_red_day flag on all {len(so_signals_ranked)} signals (fail-safe mode)")
                    log.info(f"")
                else:
                    # Data is valid - proceed with normal Red Day Filter evaluation
                    # Rev 00205: Enhanced Pattern 1 with momentum-based overrides
                    # Pattern 1: Oversold RSI + Weak Volume with momentum overrides
                    pattern1_oversold = (pct_low_rsi >= RED_DAY_RSI_LOW_THRESHOLD and
                                        pct_weak_volume >= RED_DAY_VOLUME_THRESHOLD)

                    # Rev 00205: Apply Pattern 1 momentum overrides BEFORE final decision
                    if pattern1_oversold:
                        # Check for extreme oversold + positive momentum override
                        # Condition 1: RSI < 10 AND MACD > 0 (extreme oversold with momentum)
                        extreme_oversold_with_momentum = (avg_rsi < 10 and avg_macd_histogram > 0)
                        # Condition 2: MACD > 0.5 (strong bullish momentum)
                        strong_bullish_momentum = (avg_macd_histogram > 0.5)
                        # Condition 3: RSI > 20 AND Volume > 0.2 (market bottoming signals)
                        market_bottoming_signals = (avg_rsi > 20 and avg_volume > 0.2)

                        if extreme_oversold_with_momentum or strong_bullish_momentum or market_bottoming_signals:
                            pattern1_oversold = False  # Override: allow trading
                            log.info(f"   ✅ PATTERN 1 OVERRIDE (Rev 00205): Extreme oversold conditions with momentum allow trading")
                            if extreme_oversold_with_momentum:
                                log.info(f"      • Condition 1: RSI {avg_rsi:.1f} < 10 AND MACD {avg_macd_histogram:.3f} > 0 (extreme oversold + momentum)")
                            if strong_bullish_momentum:
                                log.info(f"      • Condition 2: MACD {avg_macd_histogram:.3f} > 0.5 (strong bullish momentum)")
                            if market_bottoming_signals:
                                log.info(f"      • Condition 3: RSI {avg_rsi:.1f} > 20 AND Volume {avg_volume:.2f} > 0.2 (market bottoming)")
                            log.info(f"      • Trading allowed despite oversold + weak volume pattern (momentum override)")
                    else:
                        log.warning(f"   ⚠️ PATTERN 1 DETECTED: {pct_low_rsi:.0f}% oversold + {pct_weak_volume:.0f}% weak volume - NO OVERRIDE CONDITIONS MET")
                        log.warning(f"      • RSI: {avg_rsi:.1f} (need <10 for condition 1, or >20 for condition 3)")
                        log.warning(f"      • MACD Histogram: {avg_macd_histogram:.3f} (need >0 for condition 1, or >0.5 for condition 2)")
                        log.warning(f"      • Volume: {avg_volume:.2f} (need >0.2 for condition 3)")
                        log.warning(f"      • Pattern 1 will BLOCK trading (no momentum override applied)")

                    # Pattern 2: Overbought RSI + Weak Volume (new - Dec 5 discovery)
                    pattern2_overbought = (pct_high_rsi >= RED_DAY_RSI_HIGH_THRESHOLD and
                                          pct_weak_volume >= RED_DAY_VOLUME_THRESHOLD)

                    # Pattern 3: Weak volume alone (very strong signal - Rev 00168)
                    pattern3_weak_volume_only = (pct_weak_volume >= RED_DAY_VOLUME_THRESHOLD)
                
                # Rev 00171/00172: Check momentum override for Pattern 2
                if pattern2_overbought:
                    # Check if momentum and relative strength are strong enough to override
                    # Dec 8: MACD +0.038, RS +2.97 → Allow
                    # Dec 5: MACD -0.01, RS +1.23 → Block
                    # Dec 9: MACD +33.546, RS 0.00 → Allow (Rev 00172: Very strong MACD overrides missing RS)
                    
                    # Primary override: Both MACD and RS vs SPY strong
                    if avg_macd_histogram > MIN_MACD_HISTOGRAM and avg_rs_vs_spy > MIN_RS_VS_SPY:
                        momentum_override = True
                        log.info(f"   ✅ MOMENTUM OVERRIDE: Pattern 2 detected but strong momentum/RS allows trading")
                        log.info(f"      • MACD Histogram: {avg_macd_histogram:.3f} > {MIN_MACD_HISTOGRAM} (positive momentum)")
                        log.info(f"      • RS vs SPY: {avg_rs_vs_spy:.2f} > {MIN_RS_VS_SPY} (strong relative strength)")
                        log.info(f"      • Trading allowed despite overbought + weak volume pattern")
                        pattern2_overbought = False  # Override: don't treat as red day
                    # Rev 00172: Secondary override: Very strong MACD alone (if RS vs SPY missing/0)
                    elif avg_macd_histogram > MIN_MACD_FOR_SOLO_OVERRIDE and (avg_rs_vs_spy == 0 or avg_rs_vs_spy is None):
                        momentum_override = True
                        log.info(f"   ✅ MOMENTUM OVERRIDE (SOLO): Pattern 2 detected but very strong MACD allows trading")
                        log.info(f"      • MACD Histogram: {avg_macd_histogram:.3f} > {MIN_MACD_FOR_SOLO_OVERRIDE} (very strong momentum)")
                        log.info(f"      • RS vs SPY: {avg_rs_vs_spy:.2f} (missing/0 - using MACD solo override)")
                        log.info(f"      • Trading allowed despite overbought + weak volume pattern (strong momentum)")
                        pattern2_overbought = False  # Override: don't treat as red day
                    # Rev 00173: Tertiary override: Strong VWAP distance + positive MACD (institutional support)
                    elif avg_vwap_distance > MIN_VWAP_DISTANCE and avg_macd_histogram > MIN_MACD_HISTOGRAM:
                        momentum_override = True
                        log.info(f"   ✅ MOMENTUM OVERRIDE (VWAP): Pattern 2 detected but strong institutional support allows trading")
                        log.info(f"      • VWAP Distance: {avg_vwap_distance:.2f}% > {MIN_VWAP_DISTANCE}% (strong institutional support)")
                        log.info(f"      • MACD Histogram: {avg_macd_histogram:.3f} > {MIN_MACD_HISTOGRAM} (positive momentum)")
                        log.info(f"      • Trading allowed despite overbought + weak volume pattern (strong institutional support)")
                        pattern2_overbought = False  # Override: don't treat as red day
                
                # Rev 00178: Apply override logic to Pattern 3 as well
                # Rev 00180: FIXED - Pattern 3 now has independent override logic (not dependent on Pattern 2)
                # If momentum override is active (from Pattern 2), also override Pattern 3
                # OR if Pattern 3 is detected independently, check override conditions
                if pattern3_weak_volume_only:
                    # Check if Pattern 2 override is already active
                    if momentum_override:
                        log.info(f"   ✅ MOMENTUM OVERRIDE APPLIED TO PATTERN 3: Strong momentum/institutional support overrides weak volume")
                        log.info(f"      • Pattern 3 (weak volume) detected but override conditions met from Pattern 2")
                        log.info(f"      • Trading allowed despite weak volume (strong momentum/institutional support)")
                        pattern3_weak_volume_only = False  # Override: don't treat as red day
                    # Rev 00180: Independent Pattern 3 override check (when Pattern 2 not detected or override not active)
                    else:
                        # Check if Pattern 3 override conditions are met independently
                        # Primary override: Both MACD and RS vs SPY strong
                        if avg_macd_histogram > MIN_MACD_HISTOGRAM and avg_rs_vs_spy > MIN_RS_VS_SPY:
                            momentum_override = True
                            log.info(f"   ✅ PATTERN 3 OVERRIDE (PRIMARY): Weak volume detected but strong momentum/RS allows trading")
                            log.info(f"      • MACD Histogram: {avg_macd_histogram:.3f} > {MIN_MACD_HISTOGRAM} (positive momentum)")
                            log.info(f"      • RS vs SPY: {avg_rs_vs_spy:.2f} > {MIN_RS_VS_SPY} (strong relative strength)")
                            log.info(f"      • Trading allowed despite weak volume pattern")
                            pattern3_weak_volume_only = False  # Override: don't treat as red day
                        # Secondary override: Very strong MACD alone (if RS vs SPY missing/0)
                        elif avg_macd_histogram > MIN_MACD_FOR_SOLO_OVERRIDE and (avg_rs_vs_spy == 0 or avg_rs_vs_spy is None):
                            momentum_override = True
                            log.info(f"   ✅ PATTERN 3 OVERRIDE (SECONDARY): Weak volume detected but very strong MACD allows trading")
                            log.info(f"      • MACD Histogram: {avg_macd_histogram:.3f} > {MIN_MACD_FOR_SOLO_OVERRIDE} (very strong momentum)")
                            log.info(f"      • RS vs SPY: {avg_rs_vs_spy:.2f} (missing/0 - using MACD solo override)")
                            log.info(f"      • Trading allowed despite weak volume pattern (strong momentum)")
                            pattern3_weak_volume_only = False  # Override: don't treat as red day
                        # Tertiary override: Strong VWAP distance + positive MACD (institutional support)
                        elif avg_vwap_distance > MIN_VWAP_DISTANCE and avg_macd_histogram > MIN_MACD_HISTOGRAM:
                            momentum_override = True
                            log.info(f"   ✅ PATTERN 3 OVERRIDE (TERTIARY): Weak volume detected but strong institutional support allows trading")
                            log.info(f"      • VWAP Distance: {avg_vwap_distance:.2f}% > {MIN_VWAP_DISTANCE}% (strong institutional support)")
                            log.info(f"      • MACD Histogram: {avg_macd_histogram:.3f} > {MIN_MACD_HISTOGRAM} (positive momentum)")
                            log.info(f"      • Trading allowed despite weak volume pattern (strong institutional support)")
                            pattern3_weak_volume_only = False  # Override: don't treat as red day
                        else:
                            # No override conditions met - Pattern 3 should block trading
                            log.warning(f"   ⚠️ PATTERN 3 DETECTED: {pct_weak_volume:.0f}% weak volume - NO OVERRIDE CONDITIONS MET")
                            log.warning(f"      • MACD Histogram: {avg_macd_histogram:.3f} (need >{MIN_MACD_HISTOGRAM} for primary, >{MIN_MACD_FOR_SOLO_OVERRIDE} for secondary)")
                            log.warning(f"      • RS vs SPY: {avg_rs_vs_spy:.2f} (need >{MIN_RS_VS_SPY} for primary)")
                            log.warning(f"      • VWAP Distance: {avg_vwap_distance:.2f}% (need >{MIN_VWAP_DISTANCE}% for tertiary)")
                            log.warning(f"      • Pattern 3 will BLOCK trading (no override applied)")
                
                # Rev 00169: Any pattern indicates red day (after momentum override check)
                # Rev 00206: In fail-safe mode, all patterns are False, so is_red_day will be False
                # Rev 00233: Validate data quality before setting Red Day flag
                is_red_day = pattern1_oversold or pattern2_overbought or pattern3_weak_volume_only
                
                # Rev 00233: Only set is_red_day flag if data quality is valid
                # Don't mark signals as Red Day if data is invalid (prevents false positives)
                if is_red_day and (avg_rsi == 0.0 or avg_volume == 0.0):
                    log.warning(f"   ⚠️ Red Day pattern detected but data quality invalid - NOT setting is_red_day flag")
                    log.warning(f"   • This prevents false Red Day detection due to data collection failures")
                    is_red_day = False  # Don't mark as Red Day if data is invalid
                
                # Rev 00233: Set is_red_day flag on all signals for 0DTE filter
                # This allows 0DTE Convex filter to correctly reject signals on Red Days
                if is_red_day:
                    for sig in so_signals_ranked:
                        sig['is_red_day'] = True
                    log.info(f"   ✅ Set is_red_day=True on all {len(so_signals_ranked)} signals (for 0DTE filter)")
                else:
                    # Ensure is_red_day is False when not a Red Day
                    for sig in so_signals_ranked:
                        sig['is_red_day'] = False
                
                if is_red_day:
                    # RED DAY DETECTED - Skip execution to preserve capital
                    log.warning(f"")
                    log.warning(f"🚨" * 40)
                    log.warning(f"🚨 RED DAY DETECTED - EXECUTION SKIPPED")
                    log.warning(f"🚨" * 40)
                    log.warning(f"")
                    log.warning(f"   ⚠️ Market Conditions:")
                    # Rev 00169: Show which pattern triggered
                    if pattern1_oversold:
                        log.warning(f"      • Pattern 1: {pct_low_rsi:.0f}% oversold (RSI <40) + {pct_weak_volume:.0f}% weak volume ✅ TRIGGERED")
                    elif pattern2_overbought:
                        log.warning(f"      • Pattern 2: {pct_high_rsi:.0f}% overbought (RSI >80) + {pct_weak_volume:.0f}% weak volume ✅ TRIGGERED")
                    elif pattern3_weak_volume_only:
                        log.warning(f"      • Pattern 3: {pct_weak_volume:.0f}% weak volume alone (≥{RED_DAY_VOLUME_THRESHOLD:.0f}%) ✅ TRIGGERED")
                    
                    log.warning(f"      • Oversold (RSI <40): {pct_low_rsi:.0f}%")
                    log.warning(f"      • Overbought (RSI >80): {pct_high_rsi:.0f}%")
                    log.warning(f"      • Weak Volume (<1.0x): {pct_weak_volume:.0f}%")
                    log.warning(f"      • Avg RSI: {avg_rsi:.1f}")
                    log.warning(f"      • Avg Volume: {avg_volume:.2f}x (weak)")
                    log.warning(f"      • Avg MACD Histogram: {avg_macd_histogram:.3f}")
                    log.warning(f"      • Avg RS vs SPY: {avg_rs_vs_spy:.2f}")
                    if momentum_override:
                        log.warning(f"      ⚠️ Momentum override was considered but not applied (pattern still triggered)")
                    log.warning(f"")
                    log.warning(f"   📊 Historical Pattern:")
                    if pattern1_oversold:
                        log.warning(f"      • Nov 4 (RED DAY): 80% RSI <40 + 90% weak vol → ALL signals lost")
                        log.warning(f"      • Avg loss: -0.98%, Entry bar stops: -$11.16")
                    elif pattern2_overbought:
                        log.warning(f"      • Dec 5 (RED DAY): 100% RSI >80 + 100% weak vol → ALL signals lost")
                        log.warning(f"      • Pattern: OVERBOUGHT + WEAK VOLUME = RED DAY")
                    elif pattern3_weak_volume_only:
                        log.warning(f"      • Weak volume alone ({pct_weak_volume:.0f}%) is strong red day signal")
                        log.warning(f"      • Pattern: 100% weak volume = RED DAY (regardless of RSI)")
                    log.warning(f"")
                    log.warning(f"   💰 Action: SKIP EXECUTION (Preserve Capital)")
                    log.warning(f"      • No trades executed today")
                    log.warning(f"      • Capital preserved: $1,000 (100%)")
                    log.warning(f"      • Expected savings: $11-27")
                    log.warning(f"")
                    log.warning(f"🚨" * 40)
                    
                    # Send alert about red day filter (Rev 00179: Fixed HTML formatting and error handling)
                    if self.alert_manager:
                        try:
                            # Build detailed alert message with pattern information
                            pattern_desc = []
                            if pattern1_oversold:
                                pattern_desc.append(f"Pattern 1: {pct_low_rsi:.0f}% oversold (RSI <40) + {pct_weak_volume:.0f}% weak volume")
                            if pattern2_overbought:
                                pattern_desc.append(f"Pattern 2: {pct_high_rsi:.0f}% overbought (RSI >80) + {pct_weak_volume:.0f}% weak volume")
                            if pattern3_weak_volume_only:
                                pattern_desc.append(f"Pattern 3: {pct_weak_volume:.0f}% weak volume alone")
                            
                            # Rev 00179: Simplified HTML formatting to avoid HTTP 400 errors
                            # Use plain text with minimal HTML tags, escape special characters
                            # NOTE: Avoid '<' and '>' characters because Telegram HTML parse_mode
                            # will return HTTP 400 on unescaped comparison operators.
                            alert_message = (
                                f"====================================================================\n"
                                f"🚨 RED DAY FILTER TRIGGERED\n"
                                f"====================================================================\n\n"
                                f"📊 Market Conditions:\n"
                                f"   • {pct_low_rsi:.0f}% signals oversold (RSI under 40)\n"
                                f"   • {pct_high_rsi:.0f}% signals overbought (RSI above 80)\n"
                                f"   • {pct_weak_volume:.0f}% signals weak volume (below 1.0x)\n"
                                f"   • Avg RSI: {avg_rsi:.1f} (valid range: 0-100){' ⚠️ INVALID' if avg_rsi == 0.0 else ''}\n"
                                f"   • Avg Volume: {avg_volume:.2f}x (1.0x = normal){' ⚠️ NO DATA' if avg_volume == 0.0 else ''}\n"
                                f"   • Avg MACD Histogram: {avg_macd_histogram:.3f} (momentum)\n"
                                f"   • Avg RS vs SPY: {avg_rs_vs_spy:.2f} (relative strength)\n"
                                f"   • Avg VWAP Distance: {avg_vwap_distance:.2f}% (institutional support)\n\n"
                                f"🔍 Pattern Detected:\n"
                            )
                            for pattern in pattern_desc:
                                alert_message += f"   • {pattern} TRIGGERED\n"

                            # Add data quality warnings
                            if rsi_data_missing or volume_data_missing or avg_rsi == 0.0 or avg_volume == 0.0:
                                alert_message += f"\n⚠️ Data Quality Issues:\n"
                                if avg_rsi == 0.0:
                                    alert_message += f"   • RSI = 0.0: Invalid data (RSI cannot be exactly 0.0)\n"
                                if avg_volume == 0.0:
                                    alert_message += f"   • Volume = 0.00x: No volume data collected\n"
                                if rsi_data_missing:
                                    alert_message += f"   • RSI Data: {len(rsi_values)}/{num_signals} signals have valid RSI\n"
                                if volume_data_missing:
                                    alert_message += f"   • Volume Data: {len(volume_values)}/{num_signals} signals have valid volume\n"

                            # Add override analysis
                            # Rev 00206: Replace < and > with text to avoid Telegram HTML parse errors
                            alert_message += f"\n⚡ Override Analysis:\n"
                            if pattern1_oversold:
                                alert_message += f"   • Pattern 1 Overrides:\n"
                                alert_message += f"     - Extreme Oversold: RSI {avg_rsi:.1f} under 10 & MACD above 0? {'YES' if avg_rsi < 10 and avg_macd_histogram > 0 else 'NO'}\n"
                                alert_message += f"     - Strong Momentum: MACD {avg_macd_histogram:.3f} above 0.5? {'YES' if avg_macd_histogram > 0.5 else 'NO'}\n"
                                alert_message += f"     - Market Bottoming: RSI {avg_rsi:.1f} above 20 & Vol {avg_volume:.2f} above 0.2? {'YES' if avg_rsi > 20 and avg_volume > 0.2 else 'NO'}\n"
                            if pattern2_overbought or pattern3_weak_volume_only:
                                alert_message += f"   • Pattern 2/3 Overrides:\n"
                                alert_message += f"     - Momentum Override: MACD {avg_macd_histogram:.3f} above 5.0? {'YES' if avg_macd_histogram > 5.0 else 'NO'}\n"
                                alert_message += f"     - Strong Momentum: MACD above 0 & RS {avg_rs_vs_spy:.2f} above 2.0? {'YES' if avg_macd_histogram > 0 and avg_rs_vs_spy > 2.0 else 'NO'}\n"

                            alert_message += (
                                f"\n💰 Action Taken:\n"
                                f"   • Execution SKIPPED\n"
                                f"   • Capital preserved: $1,000 (100%)\n"
                                f"   • Expected savings: $11-27\n\n"
                                f"📊 Signals:\n"
                                f"   • Collected: {num_signals}\n"
                                f"   • Executed: 0\n\n"
                                f"✅ Red Day Filter protecting capital!\n"
                                f"===================================================================="
                            )
                            
                            from modules.prime_alert_manager import AlertLevel
                            success = await self.alert_manager.send_telegram_alert(alert_message, AlertLevel.WARNING)
                            if success:
                                log.info("✅ Red Day Filter alert sent successfully")
                            else:
                                log.error("❌ Red Day Filter alert failed to send - check Telegram credentials and formatting")
                                # Try sending a simplified fallback message (Rev 00184: Plain text, no HTML)
                                try:
                                    # Rev 00184: Use plain text pattern description without HTML characters
                                    pattern_text = "Red day detected"
                                    if pattern1_oversold:
                                        pattern_text = f"{pct_low_rsi:.0f}% oversold (RSI under 40) + {pct_weak_volume:.0f}% weak volume"
                                    elif pattern2_overbought:
                                        pattern_text = f"{pct_high_rsi:.0f}% overbought (RSI above 80) + {pct_weak_volume:.0f}% weak volume"
                                    elif pattern3_weak_volume_only:
                                        pattern_text = f"{pct_weak_volume:.0f}% weak volume alone"
                                    
                                    fallback_message = (
                                        f"🚨 RED DAY FILTER TRIGGERED\n\n"
                                        f"Execution SKIPPED - Capital preserved\n"
                                        f"Signals: {num_signals} collected, 0 executed\n"
                                        f"Pattern: {pattern_text}\n"
                                        f"Expected savings: $11-27"
                                    )
                                    # Rev 00184: Try sending without HTML parse_mode first
                                    success_fallback = await self.alert_manager.send_telegram_alert(fallback_message, AlertLevel.WARNING)
                                    if success_fallback:
                                        log.info("✅ Red Day Filter fallback alert sent")
                                    else:
                                        # Last resort: Very simple message with no special characters
                                        simple_message = f"🚨 RED DAY FILTER: Execution skipped today. {num_signals} signals collected, 0 executed. Capital preserved."
                                        await self.alert_manager.send_telegram_alert(simple_message, AlertLevel.WARNING)
                                        log.info("✅ Red Day Filter simple alert sent as last resort")
                                except Exception as e2:
                                    log.error(f"❌ Red Day Filter fallback alert also failed: {e2}")
                                    # Last resort: Very simple message
                                    try:
                                        simple_message = f"🚨 RED DAY FILTER: Execution skipped today. {num_signals} signals collected, 0 executed. Capital preserved."
                                        await self.alert_manager.send_telegram_alert(simple_message, AlertLevel.WARNING)
                                        log.info("✅ Red Day Filter simple alert sent as last resort")
                                    except Exception as e3:
                                        log.error(f"❌ All Red Day Filter alert attempts failed: {e3}")
                        except Exception as e:
                            log.error(f"❌ Failed to send red day filter alert: {e}", exc_info=True)
                            # Last resort: try sending a very simple message (Rev 00184: Plain text only)
                            try:
                                simple_message = f"🚨 RED DAY FILTER: Execution skipped today. {num_signals} signals collected, 0 executed. Capital preserved."
                                await self.alert_manager.send_telegram_alert(simple_message, AlertLevel.WARNING)
                                log.info("✅ Red Day Filter simple alert sent as fallback")
                            except Exception as e3:
                                log.error(f"❌ All Red Day Filter alert attempts failed: {e3}")
                    
                    # Skip execution - but continue to execution alert logic (Rev 00181: Don't return early)
                    log.info(f"✅ Red Day Filter: Execution skipped, capital preserved")
                    # Mark that execution was attempted (even though skipped) so execution alert can be sent
                    self._send_so_execution_alert = True
                    # Mark that Red Day Filter blocked execution (so execution alert knows why)
                    self._red_day_filter_blocked = True
                    # Store empty execution results for alert
                    if not hasattr(self, 'executed_so_signals'):
                        self.executed_so_signals = []
                    if not hasattr(self, 'rejected_so_signals'):
                        self.rejected_so_signals = []
                    # Rev 00181: Continue to execution alert logic instead of returning early
                    # This ensures the execution alert is sent even when red day filter blocks execution
                    # Skip execution by clearing signals, but continue to alert code
                    so_signals_ranked = []  # Clear signals to skip execution
                    # Continue to execution alert code below - execution will skip because signals are empty
                
                else:
                    # NOT a red day by traditional metrics - run enhanced detection
                    log.info(f"✅ RED DAY FILTER: PASS")
                    log.info(f"   • Oversold (RSI <40): {pct_low_rsi:.0f}% (threshold: ≥{RED_DAY_RSI_LOW_THRESHOLD:.0f}%)")
                    log.info(f"   • Overbought (RSI >80): {pct_high_rsi:.0f}% (threshold: ≥{RED_DAY_RSI_HIGH_THRESHOLD:.0f}%)")
                    log.info(f"   • Weak Volume: {pct_weak_volume:.0f}% (threshold: ≥{RED_DAY_VOLUME_THRESHOLD:.0f}%)")
                    if momentum_override:
                        log.info(f"   • ✅ Momentum Override: Strong momentum/RS allows trading despite Pattern 2")
                        log.info(f"      • MACD Histogram: {avg_macd_histogram:.3f} (positive momentum)")
                        log.info(f"      • RS vs SPY: {avg_rs_vs_spy:.2f} (strong relative strength)")
                    log.info(f"   • Rev 00171: Detects oversold, overbought, weak volume + momentum/RS override")
                    log.info(f"")
                
                # ========================================================================
                # REV 00136: ENHANCED MULTI-FACTOR RED DAY DETECTION
                # ========================================================================
                log.info(f"🔍 ENHANCED RED DAY DETECTION (Multi-Factor Analysis)")
                
                try:
                    # Import and run enhanced detector
                    from .prime_enhanced_red_day_detector import PrimeEnhancedRedDayDetector
                    enhanced_detector = PrimeEnhancedRedDayDetector()
                    
                    # Run enhanced analysis (with fallback market data)
                    risk_assessment = await enhanced_detector.analyze_red_day_risk(
                        signals=so_signals_ranked,
                        spy_momentum=0.0,  # TODO: Get real SPY momentum
                        vix_level=15.0     # TODO: Get real VIX level
                    )
                    
                    log.info(f"   • Risk Score: {risk_assessment.composite_risk_score:.3f}")
                    log.info(f"   • Risk Level: {risk_assessment.risk_level}")
                    log.info(f"   • Recommendation: {risk_assessment.recommendation}")
                    log.info(f"   • Technical Weakness: {risk_assessment.technical_weakness.combined_weakness_score:.1f}%")
                    
                    # Check for high risk patterns
                    if risk_assessment.recommendation == "SKIP_EXECUTION":
                        log.warning(f"")
                        log.warning(f"🚨 ENHANCED RED DAY DETECTED - EXECUTION SKIPPED")
                        log.warning(f"   • Risk Score: {risk_assessment.composite_risk_score:.3f} (HIGH)")
                        log.warning(f"   • Primary Risk: {risk_assessment.primary_risk_reason}")
                        log.warning(f"   • Prevention Estimate: ${risk_assessment.prevention_amount_estimate:.2f}")
                        log.warning(f"")
                        
                        # Send alert and skip execution
                        if self.alert_manager:
                            try:
                                from modules.prime_alert_manager import AlertLevel
                                await self.alert_manager.send_telegram_alert(
                                    f"🚨 ENHANCED RED DAY DETECTED\n\n"
                                    f"Risk Score: {risk_assessment.composite_risk_score:.3f}\n"
                                    f"Technical Weakness: {risk_assessment.technical_weakness.combined_weakness_score:.1f}%\n"
                                    f"Primary Risk: {risk_assessment.primary_risk_reason}\n\n"
                                    f"💰 Execution SKIPPED - Capital preserved\n"
                                    f"Prevention estimate: ${risk_assessment.prevention_amount_estimate:.2f}",
                                    AlertLevel.WARNING
                                )
                            except Exception as e:
                                log.error(f"Failed to send enhanced red day alert: {e}")
                        
                        return  # Skip execution
                    
                    elif risk_assessment.recommendation.startswith("REDUCE_POSITION_SIZE"):
                        log.warning(f"⚠️ MEDIUM RISK - Reducing position sizes by {(1-risk_assessment.position_size_multiplier)*100:.0f}%")
                        # Apply position size reduction
                        for signal in so_signals_ranked:
                            original_size = signal.get('position_size_pct', 0)
                            signal['position_size_pct'] = original_size * risk_assessment.position_size_multiplier
                            signal['risk_reduction_applied'] = True
                    
                    else:
                        log.info(f"✅ Enhanced analysis: Normal execution approved")
                
                except Exception as e:
                    log.error(f"Enhanced red day detection failed: {e}")
                    log.info(f"⚠️ Continuing with traditional detection results")
                
                log.info(f"")
                
                # Rev 00046: Account value and capital allocation already calculated above
                # Oct 24, 2025: CLEAN EXECUTION FLOW
                # 1. Signals are already ranked by priority score
                # 2. Filter expensive symbols FIRST (before selecting top 15)
                # 3. Select best 15 from affordable signals
                # 4. Apply multipliers and normalize ALL to fit in SO capital allocation
                
                log.info(f"🎯 Capital Allocation: ${so_capital:,.0f} ({self.config.so_capital_pct:.0f}% of ${account_value:,.0f})")
                log.info(f"   Total signals available: {len(so_signals_ranked)}")
                
                # Rev 00233: SIGNAL-LEVEL RED DAY FILTERING (Individual Trade Filtering)
                # Filter out individual signals that show Red Day characteristics even if portfolio-level passed
                # This prevents losing trades while allowing winning trades
                if not is_red_day and len(so_signals_ranked) > 0:
                    log.info(f"")
                    log.info(f"🔍 SIGNAL-LEVEL RED DAY FILTERING (Rev 00233)")
                    log.info(f"=" * 80)
                    filtered_signals = []
                    rejected_signals = []
                    
                    for sig in so_signals_ranked:
                        symbol = sig.get('symbol', 'UNKNOWN')
                        sig_rsi = get_valid_rsi(sig)
                        sig_volume = get_valid_volume(sig)
                        sig_macd = sig.get('macd_histogram', 0)
                        sig_rs_vs_spy = sig.get('rs_vs_spy', 0)
                        sig_vwap_dist = sig.get('vwap_distance_pct', 0)
                        
                        # Signal-level Red Day criteria (stricter than portfolio-level)
                        # Reject signal if: Weak volume AND (Low RSI OR Zero MACD OR Negative VWAP)
                        is_signal_red_day = False
                        rejection_reason = None
                        
                        if sig_volume < 1.0:  # Weak volume
                            if sig_rsi < 40:  # Oversold
                                is_signal_red_day = True
                                rejection_reason = f"Weak volume ({sig_volume:.2f}x) + Oversold RSI ({sig_rsi:.1f})"
                            elif sig_macd <= 0 and sig_rs_vs_spy <= 0:  # No momentum
                                is_signal_red_day = True
                                rejection_reason = f"Weak volume ({sig_volume:.2f}x) + No momentum (MACD={sig_macd:.3f}, RS={sig_rs_vs_spy:.2f})"
                            elif sig_vwap_dist < -0.5:  # Negative VWAP distance
                                is_signal_red_day = True
                                rejection_reason = f"Weak volume ({sig_volume:.2f}x) + Negative VWAP distance ({sig_vwap_dist:.2f}%)"
                        
                        if is_signal_red_day:
                            rejected_signals.append({'symbol': symbol, 'reason': rejection_reason})
                            sig['is_red_day'] = True  # Mark for 0DTE filter
                            log.debug(f"   ❌ Rejected {symbol}: {rejection_reason}")
                        else:
                            filtered_signals.append(sig)
                            sig['is_red_day'] = False  # Ensure flag is clear
                    
                    if rejected_signals:
                        log.info(f"   📊 Signal-Level Filter Results:")
                        log.info(f"      • Total signals: {len(so_signals_ranked)}")
                        log.info(f"      • Filtered (kept): {len(filtered_signals)}")
                        log.info(f"      • Rejected (Red Day): {len(rejected_signals)}")
                        log.info(f"   🚨 Rejected Signals (Signal-Level Red Day):")
                        for rejected in rejected_signals[:5]:  # Show top 5
                            log.info(f"      • {rejected['symbol']}: {rejected['reason']}")
                        if len(rejected_signals) > 5:
                            log.info(f"      ... and {len(rejected_signals) - 5} more")
                        so_signals_ranked = filtered_signals
                        log.info(f"   ✅ Continuing with {len(so_signals_ranked)} filtered signals")
                    else:
                        log.info(f"   ✅ All signals passed signal-level Red Day filter")
                    log.info(f"=" * 80)
                    log.info(f"")
                
                # STEP 1: ADAPTIVE SIGNAL FILTERING (Rev 00095 - Nov 3, 2025)
                # Progressive reduction: 15 → 12 → 10 → 8 based on expense ratios
                # Ensures top-priority signals are prioritized even with expensive stocks
                #
                # Key improvements from Oct 27 system:
                # 1. Progressive reduction (not binary halving: 15→7→3)
                # 2. 3x fair share threshold (not 1.1x - too strict)
                # 3. Top 3 protection (always attempt best signals if ≤60% account)
                # 4. 30% expense ratio (allows 2-3 premium stocks, not 60% rejection)
                #
                # Based on comprehensive simulations and historical validation
                
                skipped_expensive = []
                num_signals_total = len(so_signals_ranked)
                
                log.info(f"")
                log.info(f"=" * 80)
                log.info(f"🎯 ADAPTIVE SIGNAL FILTERING (Rev 00095)")
                log.info(f"=" * 80)
                log.info(f"   Account: ${account_value:,.0f}")
                log.info(f"   SO Capital: ${so_capital:,.0f} ({self.config.so_capital_pct:.0f}%)")
                log.info(f"   Signals Collected: {num_signals_total}")
                log.info(f"")
                
                # PHASE 1: Top 3 Protection
                # Always protect top 3 signals if remotely affordable (≤60% account)
                max_single_position = account_value * 0.60  # $600 for $1K account
                protected_top_3 = []
                
                log.info(f"PHASE 1: Top 3 Protection (≤60% account = ${max_single_position:.0f})")
                for sig in so_signals_ranked[:3]:
                    symbol = sig.get('symbol')
                    price = sig.get('price', 0)
                    rank = len(protected_top_3) + 1
                    
                    if price <= max_single_position:
                        protected_top_3.append(sig)
                        log.info(f"   🛡️ PROTECTED: #{rank} {symbol} @ ${price:.2f} (top 3)")
                    else:
                        log.warning(f"   ⚠️ TOO EXPENSIVE: #{rank} {symbol} @ ${price:.2f} (>${max_single_position:.0f})")
                
                log.info(f"   Protected Count: {len(protected_top_3)}")
                log.info(f"")
                
                # PHASE 2: Progressive Reduction
                # Try targets: 15 → 12 → 10 → 8, checking expense ratio at each level
                EXPENSE_THRESHOLD_MULTIPLIER = 3.0  # Price > 3x fair share = expensive
                EXPENSE_RATIO_LIMIT = 0.30  # 30% expensive allowed (2-3 out of 10)
                PROGRESSIVE_TARGETS = [15, 12, 10, 8]  # Try each in sequence
                
                selected_signals = []
                final_target = 0
                selection_reason = ""
                final_fair_share = 0
                final_expense_ratio = 0
                
                log.info(f"PHASE 2: Progressive Target Selection")
                
                for target_count in PROGRESSIVE_TARGETS:
                    # Don't try targets larger than signals we have
                    if target_count > num_signals_total:
                        continue
                    
                    # Calculate fair share and expense threshold for this target
                    fair_share = so_capital / target_count
                    expensive_threshold = fair_share * EXPENSE_THRESHOLD_MULTIPLIER
                    
                    # Get top N signals
                    candidate_signals = so_signals_ranked[:target_count]
                    
                    # Separate affordable vs expensive (exclude protected from expense ratio calc)
                    affordable_in_target = []
                    expensive_in_target = []
                    
                    for sig in candidate_signals:
                        price = sig.get('price', 0)
                        
                        # Protected signals always count as "affordable" for ratio purposes
                        if sig in protected_top_3:
                            affordable_in_target.append(sig)
                        elif price <= expensive_threshold:
                            affordable_in_target.append(sig)
                        else:
                            expensive_in_target.append(sig)
                    
                    # Calculate expense ratio (excluding protected top 3)
                    non_protected_count = target_count - len(protected_top_3)
                    expense_ratio = len(expensive_in_target) / non_protected_count if non_protected_count > 0 else 0.0
                    
                    log.info(f"")
                    log.info(f"Testing {target_count} signals:")
                    log.info(f"   Fair Share: ${fair_share:.2f}")
                    log.info(f"   Expensive Threshold: ${expensive_threshold:.2f} (3x fair share)")
                    log.info(f"   Affordable: {len(affordable_in_target)} | Expensive: {len(expensive_in_target)}")
                    log.info(f"   Expense Ratio: {expense_ratio*100:.1f}% (of {non_protected_count} non-protected)")
                    
                    # Check if this target is acceptable
                    if expense_ratio <= EXPENSE_RATIO_LIMIT:
                        # ACCEPT this target count
                        selected_signals = candidate_signals
                        final_target = target_count
                        final_fair_share = fair_share
                        final_expense_ratio = expense_ratio
                        selection_reason = f"{target_count}_signals_{expense_ratio*100:.0f}pct_expensive"
                        log.info(f"   ✅ ACCEPT: {expense_ratio*100:.1f}% ≤ {EXPENSE_RATIO_LIMIT*100:.0f}% threshold")
                        break
                    else:
                        # REJECT - too many expensive, try next lower target
                        log.info(f"   ❌ REJECT: {expense_ratio*100:.1f}% > {EXPENSE_RATIO_LIMIT*100:.0f}% threshold")
                
                # FALLBACK: If even top 8 has >30% expensive, use top 8 AFFORDABLE from full list
                if not selected_signals or (final_target == 8 and final_expense_ratio > EXPENSE_RATIO_LIMIT):
                    log.warning(f"")
                    log.warning(f"⚠️ FALLBACK TRIGGERED: Even top 8 has >{EXPENSE_RATIO_LIMIT*100:.0f}% expensive")
                    log.warning(f"   Solution: Selecting top 8 AFFORDABLE signals from full list")
                    
                    # Recalculate threshold for 8 signals
                    fair_share_8 = so_capital / 8
                    threshold_8 = fair_share_8 * EXPENSE_THRESHOLD_MULTIPLIER
                    
                    # Always include protected top 3
                    selected_signals = protected_top_3.copy()
                    log.warning(f"   Starting with {len(protected_top_3)} protected signals")
                    
                    # Add best affordable from ranks 4+ (or from rank 1+ if top 3 not all protected)
                    start_rank = 3 if len(protected_top_3) == 3 else 0
                    for sig in so_signals_ranked[start_rank:]:
                        if len(selected_signals) >= 8:
                            break
                        if sig.get('price', 0) <= threshold_8 and sig not in selected_signals:
                            selected_signals.append(sig)
                    
                    final_target = len(selected_signals)
                    final_fair_share = so_capital / max(1, final_target)
                    selection_reason = f"top_{len(protected_top_3)}_protected_plus_{len(selected_signals)-len(protected_top_3)}_affordable"
                    log.warning(f"   Final: {len(protected_top_3)} protected + {len(selected_signals)-len(protected_top_3)} affordable = {final_target} total")
                    log.info(f"")
                
                # Log final selection summary
                log.info(f"")
                log.info(f"=" * 80)
                log.info(f"📊 FILTERING COMPLETE")
                log.info(f"=" * 80)
                log.info(f"   Input Signals: {num_signals_total}")
                log.info(f"   Final Target: {final_target}")
                log.info(f"   Selected: {len(selected_signals)}")
                log.info(f"   Filtered: {num_signals_total - len(selected_signals)}")
                log.info(f"   Selection Reason: {selection_reason}")
                log.info(f"   Final Fair Share: ${final_fair_share:.2f}")
                log.info(f"")
                
                # Show selected signals
                log.info(f"SELECTED SIGNALS FOR EXECUTION:")
                for i, sig in enumerate(selected_signals, 1):
                    symbol = sig.get('symbol')
                    price = sig.get('price', 0)
                    score = calculate_so_priority_score(sig)
                    protected = " 🛡️ PROTECTED" if sig in protected_top_3 else ""
                    log.info(f"   {i}. {symbol} @ ${price:.2f} (Score: {score:.3f}){protected}")
                log.info(f"")
                
                # Show filtered signals (if any)
                filtered_count = num_signals_total - len(selected_signals)
                if filtered_count > 0:
                    log.info(f"FILTERED SIGNALS ({filtered_count}):")
                    filtered_symbols = [s for s in so_signals_ranked if s not in selected_signals]
                    for sig in filtered_symbols[:5]:  # Show first 5
                        symbol = sig.get('symbol')
                        price = sig.get('price', 0)
                        rank_in_original = so_signals_ranked.index(sig) + 1
                        log.info(f"   • #{rank_in_original} {symbol} @ ${price:.2f}")
                        skipped_expensive.append((symbol, price, sig.get('confidence', 0), 
                                                 f'Filtered by adaptive algorithm'))
                    
                    if filtered_count > 5:
                        log.info(f"   • ... and {filtered_count - 5} more")
                log.info(f"")
            
            # PRIORITY OPTIMIZER: Save complete signal list + Auto-cleanup (Rev 00096)
            # Minimal integration for after-EOD data collection with 50-day retention
            try:
                from .gcs_persistence import get_gcs_persistence
                from datetime import timedelta
                import json
                
                gcs = get_gcs_persistence()
                
                if gcs and gcs.enabled:
                    # Prepare signal list data
                    # Rev 00147: Include ALL technical indicators collected during signal enrichment
                    signal_list_data = {
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'total_signals': len(so_signals_ranked),
                        'executed_count': len(selected_signals),
                        'filtered_count': len(so_signals_ranked) - len(selected_signals),
                        'signals': [
                            {
                                'symbol': sig.get('symbol'),
                                'rank': i + 1,
                                'priority_score': sig.get('priority_score', 0),
                                'confidence': sig.get('confidence', 0),
                                'orb_range_pct': sig.get('orb_range_pct', 0),
                                'orb_volume_ratio': sig.get('orb_volume_ratio', 0),
                                'exec_volume_ratio': sig.get('exec_volume_ratio', 0),
                                'price': sig.get('price', sig.get('current_price', 0)),
                                'orb_high': sig.get('orb_high', 0),
                                'orb_low': sig.get('orb_low', 0),
                                'leverage': sig.get('leverage', ''),
                                'category': sig.get('category', ''),
                                'executed': sig in selected_signals,
                                # Rev 00135: Basic technical indicators
                                'vwap_distance_pct': sig.get('vwap_distance_pct', 0),
                                'rs_vs_spy': sig.get('rs_vs_spy', 0),
                                'rsi': sig.get('rsi', 0),
                                # Rev 00147: Comprehensive technical indicators (collected during enrichment)
                                'rsi_14': sig.get('rsi_14', sig.get('rsi', 0)),
                                'macd': sig.get('macd', 0),
                                'macd_signal': sig.get('macd_signal', 0),
                                'macd_histogram': sig.get('macd_histogram', 0),
                                'sma_20': sig.get('sma_20', 0),
                                'sma_50': sig.get('sma_50', 0),
                                'ema_12': sig.get('ema_12', 0),
                                'ema_26': sig.get('ema_26', 0),
                                'atr': sig.get('atr', 0),
                                'bollinger_upper': sig.get('bollinger_upper', 0),
                                'bollinger_middle': sig.get('bollinger_middle', 0),
                                'bollinger_lower': sig.get('bollinger_lower', 0),
                                'bollinger_width': sig.get('bollinger_width', 0),
                                'volume_ratio': sig.get('volume_ratio', sig.get('orb_volume_ratio', 0)),
                                'vwap': sig.get('vwap', 0),
                                'volatility': sig.get('volatility', 0)
                            }
                            for i, sig in enumerate(so_signals_ranked)
                        ]
                    }
                    
                    # Save to GCS
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    gcs_path = f"priority_optimizer/daily_signals/{today_str}_signals.json"
                    gcs.upload_string(gcs_path, json.dumps(signal_list_data, indent=2, default=str))
                    
                    log.info(f"📊 Priority Optimizer: Saved {len(so_signals_ranked)} signals to GCS")
                    log.info(f"   • Path: {gcs_path}")
                    log.info(f"   • Executed: {len(selected_signals)} | Filtered: {len(so_signals_ranked) - len(selected_signals)}")
                    
                    # AUTO-CLEANUP: Delete files older than 50 days (keeps last 50 only)
                    try:
                        cutoff_date = datetime.now() - timedelta(days=50)
                        prefix = "priority_optimizer/daily_signals/"
                        
                        blobs = list(gcs.client.list_blobs(gcs.bucket, prefix=prefix))
                        deleted_count = 0
                        
                        for blob in blobs:
                            # Extract date from filename (YYYY-MM-DD_signals.json)
                            try:
                                filename = blob.name.split('/')[-1]
                                file_date_str = filename.split('_')[0]  # Get YYYY-MM-DD
                                file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                                
                                if file_date < cutoff_date:
                                    blob.delete()
                                    deleted_count += 1
                                    log.debug(f"   🗑️ Deleted old signal file: {blob.name} (from {file_date_str})")
                            
                            except Exception as parse_error:
                                # Skip files that don't match expected format
                                log.debug(f"   ⚠️ Skipped file (unexpected format): {blob.name}")
                        
                        if deleted_count > 0:
                            log.info(f"   🗑️ Cleaned up {deleted_count} signal files older than 50 days")
                        else:
                            log.debug(f"   ✅ No old signal files to clean (all within 50 days)")
                    
                    except Exception as cleanup_error:
                        log.warning(f"   ⚠️ Signal file cleanup failed (non-critical): {cleanup_error}")
            
            except Exception as e:
                log.warning(f"⚠️ Signal list preservation failed (non-critical): {e}")
            # END PRIORITY OPTIMIZER
            
            # STEP 2: Prepare signals for Risk Manager
            signals_to_execute = selected_signals
            
            # Rev 00099 (Nov 4, 2025): CRITICAL - Add priority_rank BEFORE batch sizing
            # Batch sizing needs priority_rank to apply correct multipliers (3.0x, 2.5x, 2.0x, etc.)
            # Bug: priority_rank was being added AFTER batch sizing (line 3401), so all signals got 1.0x multiplier!
            for rank, sig in enumerate(signals_to_execute, 1):
                sig['priority_rank'] = rank  # ✅ Add rank BEFORE batch sizing
                sig['priority_score'] = calculate_so_priority_score(sig)  # For reference
            
            log.info(f"✅ Added priority ranks 1-{len(signals_to_execute)} to signals before batch sizing")
            
            # ========== Rev 00084: USE BATCH POSITION SIZING (CLEAN FLOW) ==========
            # Instead of complex greedy packing here, delegate to Risk Manager for batch sizing
            # Risk Manager will handle: multipliers, caps, ADV, normalization, whole-share conversion
            
            log.info(f"")
            log.info(f"📊 Delegating position sizing to Risk Manager (Rev 00084 Clean Flow)")
            
            # Rev 00105 (Nov 6, 2025): CRITICAL DIAGNOSTIC LOGGING
            # Log inputs to batch sizing to diagnose why all signals get quantity=0
            log.info(f"")
            log.info(f"💰 BATCH SIZING INPUTS:")
            log.info(f"   • Account Value: ${account_value:,.2f}")
            log.info(f"   • SO Capital ({self.config.so_capital_pct:.0f}%): ${so_capital:,.2f}")
            log.info(f"   • Signals to Size: {len(signals_to_execute)}")
            log.info(f"   • Max Position: {self.config.max_position_pct:.0f}% (${account_value * (self.config.max_position_pct / 100.0):,.2f})")
            log.info(f"")
            
            # Call batch sizing method
            # Rev 00094 (Nov 3, 2025): CRITICAL FIX #2 - Use self.risk_manager, not self.demo_risk_manager
            # Bug: Was checking self.demo_risk_manager which doesn't exist (it's stored as self.risk_manager)
            # This prevented position sizing from working in both Demo and Live modes
            if self.risk_manager:
                sized_signals = await self.risk_manager.calculate_batch_position_sizes(
                    signals=signals_to_execute,
                    so_capital=so_capital,
                    account_value=account_value,
                    max_position_pct=self.config.max_position_pct
                )
                
                # Replace signals_to_execute with sized signals
                signals_to_execute = sized_signals
                
                # Rev 00105 (Nov 6, 2025): CRITICAL - Filter out 0-quantity signals before execution
                # Bug: Batch sizing was returning signals with quantity=0 (insufficient capital)
                # These were being passed to execution and rejected, causing "all trades rejected" alert
                # Fix: Only keep signals with quantity > 0 (executable signals)
                executable_signals = [s for s in sized_signals if s.get('quantity', 0) > 0]
                rejected_count = len(sized_signals) - len(executable_signals)
                
                if rejected_count > 0:
                    log.warning(f"⚠️ {rejected_count} signals rejected after batch sizing (quantity=0 - insufficient capital)")
                    rejected_symbols = [s['symbol'] for s in sized_signals if s.get('quantity', 0) == 0]
                    log.warning(f"   Rejected: {', '.join(rejected_symbols)}")
                
                # Calculate actual deployed capital (only from executable signals)
                deployed_capital = sum(s.get('position_value', 0) for s in executable_signals)
                capital_efficiency = (deployed_capital / so_capital) * 100.0 if so_capital > 0 else 0.0
                
                log.info(f"")
                log.info(f"✅ Batch Sizing Complete:")
                log.info(f"   • Signals Sized: {len(sized_signals)}")
                log.info(f"   • Executable: {len(executable_signals)} (quantity > 0)")
                log.info(f"   • Rejected: {rejected_count} (quantity = 0)")
                log.info(f"   • Total Deployed: ${deployed_capital:,.2f}")
                log.info(f"   • Capital Efficiency: {capital_efficiency:.1f}%")
                log.info(f"")
                
                # Set SO signals to ONLY executable signals
                so_signals = executable_signals
            else:
                log.error(f"❌ Risk Manager not available for batch sizing!")
                log.error(f"   self.risk_manager: {self.risk_manager is not None}")
                so_signals = []
                
                # Skip old greedy packing logic (Rev 00084: Replaced with batch sizing)
                # The following ~260 lines are DEPRECATED - Batch sizing handles it all
                
                """
                # ========== DEPRECATED (Rev 00084) - OLD GREEDY PACKING LOGIC ==========
                # This section is replaced by batch sizing in Risk Manager
                # Kept commented for reference only
                
                # STEP 3: APPLY MULTIPLIERS AND NORMALIZE TO FIT IN SO CAPITAL ALLOCATION
                # Fair share already calculated in STEP 1 (based on selected trades count)
                
                log.info(f"")
                log.info(f"📊 Position Sizing:")
                log.info(f"   • Fair Share: ${fair_share:.2f} (${so_capital:.0f} / {min(num_affordable, target_trades)} selected trades)")
                log.info(f"   • Max Position: ${account_value * (self.config.max_position_pct / 100.0):.2f} ({self.config.max_position_pct:.0f}% cap)")
                
                # Calculate total with rank multipliers
                # Oct 24, 2025: Deploy exactly to SO capital allocation (not 105% buffer)
                capital_limit = so_capital * 1.00  # Deploy 100% of SO allocation (from config)
                total_raw = 0
                
                for rank, sig in enumerate(signals_to_execute, 1):
                    # GRADUATED RANK MULTIPLIERS (original proven system)
                    if rank == 1:
                        boost = 3.0  # Rank #1: Maximum (best signal)
                    elif rank == 2:
                        boost = 2.5  # Rank #2: Very strong
                    elif rank == 3:
                        boost = 2.0  # Rank #3: Strong
                    elif rank <= 5:
                        boost = 1.71  # Rank 4-5: Good
                    elif rank <= 10:
                        boost = 1.5  # Rank 6-10: Above average
                    elif rank <= 15:
                        boost = 1.2  # Rank 11-15: Moderate
                    else:
                        boost = 1.0  # Rank 16+: Base
                    
                    # Store boost on signal for Slip Guard reallocation (Rev 00037)
                    sig['rank_boost'] = boost
                    
                    # Calculate position value with multiplier (Oct 27, 2025: DON'T cap yet!)
                    # Cap should be applied AFTER normalization to preserve rank distribution
                    pos_raw = fair_share * boost
                    total_raw += pos_raw  # Use RAW value (not capped) for normalization
                
                # STEP 4: NORMALIZE IF EXCEEDS LIMIT
                if total_raw > capital_limit:
                    # Scale down ALL positions proportionally to fit
                    scale_factor = capital_limit / total_raw
                    deployed_capital = capital_limit
                    
                    log.info(f"")
                    log.info(f"📏 NORMALIZATION: Scaling positions to fit in {self.config.so_capital_pct:.0f}% allocation")
                    log.info(f"   • Raw Total: ${total_raw:.2f} (exceeds limit)")
                    log.info(f"   • Capital Limit: ${capital_limit:.2f} ({self.config.so_capital_pct:.0f}% of account)")
                    log.info(f"   • Scale Factor: {scale_factor:.3f} ({scale_factor*100:.1f}%)")
                    log.info(f"   • Normalized Total: ${deployed_capital:.2f}")
                    
                    # Pass scale_factor to risk manager
                    for signal in signals_to_execute:
                        signal['normalization_factor'] = scale_factor
                else:
                    # Total fits within limit - no scaling needed
                    deployed_capital = total_raw
                    scale_factor = 1.0
                    
                    log.info(f"")
                    log.info(f"✅ No normalization needed - positions fit within {self.config.so_capital_pct:.0f}% allocation")
                    log.info(f"   • Total: ${total_raw:.2f} / ${capital_limit:.2f}")
                
                # ========== STEP 4: SLIP GUARD WITH CAPITAL REALLOCATION (Rev 00037) ==========
                # Check ADV limits AFTER normalization and reallocate freed capital to top signals
                from .adv_data_manager import get_adv_manager
                adv_manager = get_adv_manager()
                
                if adv_manager.enabled:
                    log.info(f"")
                    log.info(f"🛡️ SLIP GUARD: Checking ADV limits for {len(signals_to_execute)} positions...")
                    
                    # Calculate final positions after normalization
                    final_positions = {}
                    for rank, sig in enumerate(signals_to_execute, 1):
                        pos_raw = fair_share * sig.get('rank_boost', 1.0)
                        pos_capped_35 = min(pos_raw, account_value * (self.config.max_position_pct / 100.0))
                        pos_normalized = pos_capped_35 * scale_factor
                        final_positions[sig.get('symbol')] = {
                            'signal': sig,
                            'rank': rank,
                            'boost': sig.get('rank_boost', 1.0),
                            'position': pos_normalized,
                            'capped_by_adv': False,
                            'freed': 0
                        }
                    
                    # First pass: Check ADV limits and cap positions
                    total_freed = 0
                    capped_count = 0
                    uncapped_symbols = []
                    
                    for symbol, info in final_positions.items():
                        position = info['position']
                        
                        # Get ADV limit
                        adv_dollars = adv_manager.get_adv(symbol)
                        if adv_dollars > 0:
                            adv_limit = adv_manager.get_adv_limit(symbol, mode="aggressive")
                            
                            if position > adv_limit:
                                # Cap this position
                                freed = position - adv_limit
                                total_freed += freed
                                info['position'] = adv_limit
                                info['capped_by_adv'] = True
                                info['freed'] = freed
                                capped_count += 1
                                
                                pct_of_adv = (position / adv_dollars) * 100
                                log.warning(f"   🛡️ {symbol} (Rank {info['rank']}): "
                                           f"${position:,.0f} → ${adv_limit:,.0f} "
                                           f"({pct_of_adv:.1f}% → 1.0% ADV, freed ${freed:,.0f})")
                            else:
                                uncapped_symbols.append(symbol)
                        else:
                            # No ADV data - treat as uncapped
                            uncapped_symbols.append(symbol)
                    
                    # Second pass: Reallocate freed capital to uncapped signals (proportional to rank boost)
                    if total_freed > 0 and uncapped_symbols:
                        log.info(f"")
                        log.info(f"💰 REALLOCATION: Distributing ${total_freed:,.0f} freed capital to {len(uncapped_symbols)} uncapped signals...")
                        
                        # Calculate total rank weight of uncapped signals
                        total_boost = sum(final_positions[sym]['boost'] for sym in uncapped_symbols)
                        
                        reallocation_applied = 0
                        for symbol in uncapped_symbols:
                            info = final_positions[symbol]
                            
                            # Proportional allocation based on rank boost (top signals get more)
                            allocation_share = (info['boost'] / total_boost) * total_freed
                            original_position = info['position']
                            info['position'] += allocation_share
                            reallocation_applied += allocation_share
                            
                            log.info(f"   💰 {symbol} (Rank {info['rank']}, {info['boost']:.2f}x): "
                                    f"${original_position:,.0f} + ${allocation_share:,.0f} = ${info['position']:,.0f}")
                        
                        log.info(f"   ✅ ${reallocation_applied:,.0f} freed capital reallocated")
                        
                        # Update deployed_capital to include reallocated amount
                        deployed_capital = sum(info['position'] for info in final_positions.values())
                        
                        log.info(f"")
                        log.info(f"🛡️ Slip Guard Summary:")
                        log.info(f"   • Capped: {capped_count} signals")
                        log.info(f"   • Freed: ${total_freed:,.0f}")
                        log.info(f"   • Reallocated: ${reallocation_applied:,.0f}")
                        log.info(f"   • Final Deployment: ${deployed_capital:,.0f} ({(deployed_capital/account_value)*100:.1f}% of account)")
                    elif total_freed > 0:
                        log.warning(f"⚠️ ${total_freed:,.0f} freed but no uncapped signals to reallocate to")
                        deployed_capital = sum(info['position'] for info in final_positions.values())
                    
                    # Update signals with final positions (after ADV caps + reallocation)
                    for symbol, info in final_positions.items():
                        sig = info['signal']
                        sig['position_after_adv'] = info['position']
                        sig['adv_capped'] = info['capped_by_adv']
                        if info['capped_by_adv']:
                            sig['adv_freed'] = info['freed']
                else:
                    log.info(f"")
                    log.info(f"⚪ Slip Guard DISABLED - ADV limits not applied")
                
                # ========== STEP 5: POST-ROUNDING RE-NORMALIZATION (Rev 00067, Fixed Rev 00083) ==========
                # After all sizing, normalization, ADV caps, and reallocation,
                # check if significant capital is unused due to whole-share rounding losses.
                # If so, iteratively add 1 share to top-ranked signals to maximize deployment.
                # 
                # CRITICAL FIX (Rev 00083): Enforce capital_limit cap during redistribution
                # Previously: Could add shares beyond SO capital limit
                # Now: Stops adding shares when total would exceed capital_limit
                
                # Calculate current deployment after all processing
                total_deployed_after_rounding = sum(info['position'] for info in final_positions.values())
                unused_capital = capital_limit - total_deployed_after_rounding
                unused_pct = (unused_capital / capital_limit) * 100.0 if capital_limit > 0 else 0.0
                
                # If >10% capital unused, redistribute to top signals (WITH CAPITAL LIMIT ENFORCEMENT)
                if unused_pct > 10.0 and len(final_positions) > 0:
                    log.warning(f"")
                    log.warning(f"⚠️ POST-ROUNDING GAP DETECTED:")
                    log.warning(f"   • Deployed: ${total_deployed_after_rounding:,.2f} ({100.0 - unused_pct:.1f}%)")
                    log.warning(f"   • Unused: ${unused_capital:,.2f} ({unused_pct:.1f}%)")
                    log.warning(f"   • Redistributing to top-ranked signals...")
                    
                    # Sort by rank (top signals first for priority)
                    sorted_by_rank = sorted(final_positions.items(), key=lambda x: x[1]['rank'])
                    
                    redistribution_count = 0
                    redistribution_amount = 0.0
                    
                    # Iteratively add 1 share to top signals until SO capital deployed or caps hit
                    # Rev 00083: ENFORCE capital_limit cap to prevent over-deployment
                    for symbol, info in sorted_by_rank:
                        # Stop if <$50 unused (not worth another share)
                        if unused_capital < 50:
                            break
                        
                        # Get signal price
                        sig = info['signal']
                        price = sig.get('price', sig.get('current_price', 0))
                        
                        if price <= 0:
                            continue
                        
                        # Calculate new position value if we add 1 share
                        new_position_value = info['position'] + price
                        
                        # Rev 00083: Calculate what total deployment would be with this addition
                        current_total = sum(i['position'] for i in final_positions.values())
                        new_total = current_total + price
                        
                        # Check constraints:
                        # 1. Can we afford it?
                        # 2. Does it stay under 35% position cap?
                        # 3. Rev 00083: Does total stay under capital_limit (SO capital from config)?
                        max_position_cap = account_value * (self.config.max_position_pct / 100.0)
                        
                        if (price <= unused_capital and 
                            new_position_value <= max_position_cap and
                            new_total <= capital_limit):  # Rev 00083: CRITICAL SAFETY CHECK
                            # Add 1 share to this position
                            info['position'] = new_position_value
                            unused_capital -= price
                            redistribution_count += 1
                            redistribution_amount += price
                            
                            log.info(f"   ✅ {symbol} (Rank #{info['rank']}): +1 share (+${price:.2f}) = ${new_position_value:.2f}")
                        elif new_total > capital_limit:
                            # Rev 00083: Stop if we'd exceed capital limit
                            log.info(f"   ⛔ {symbol}: Skipped (would exceed SO capital limit: ${new_total:.2f} > ${capital_limit:.2f})")
                            break  # Don't try remaining signals either
                    
                    # Recalculate total deployment after redistribution
                    deployed_capital = sum(info['position'] for info in final_positions.values())
                    final_efficiency = (deployed_capital / capital_limit) * 100.0 if capital_limit > 0 else 0.0
                    
                    log.info(f"")
                    log.info(f"✅ POST-ROUNDING REDISTRIBUTION COMPLETE:")
                    log.info(f"   • Shares Added: {redistribution_count}")
                    log.info(f"   • Capital Redeployed: ${redistribution_amount:.2f}")
                    log.info(f"   • Final Deployment: ${deployed_capital:,.2f} ({final_efficiency:.1f}%)")
                    log.info(f"   • Remaining Unused: ${unused_capital:.2f}")
                    log.info(f"")
                    
                    # Update signals with final redistributed positions
                    # Rev 00083: Now SAFE to set because redistribution enforces capital_limit
                    for symbol, info in final_positions.items():
                        sig = info['signal']
                        sig['position_after_redistribution'] = info['position']
                else:
                    # Calculate final deployment (no redistribution needed)
                    deployed_capital = sum(info['position'] for info in final_positions.values())
                
                # Log final deployment status (Rev 00083)
                log.info(f"")
                log.info(f"✅ Final Capital Deployment (Post-Rounding Disabled - Rev 00083):")
                log.info(f"   • Deployed: ${deployed_capital:.2f}")
                log.info(f"   • Target: ${so_capital:.2f}")
                log.info(f"   • Efficiency: {deployment_pct:.1f}%")
                log.info(f"   • Note: Post-rounding disabled to ensure normalization (capital safety)")
                log.info(f"")
                
                # RESULTS
                so_signals = signals_to_execute
                """
                # ========== END DEPRECATED SECTION ==========
                
                # Capital efficiency already calculated in batch sizing above
                
                log.info(f"")
                log.info(f"📊 Execution Summary:")
                log.info(f"   • Total Signals Found: {len(so_signals_ranked)}")
                log.info(f"   • Trades Executing: {len(so_signals)} ✅")
                log.info(f"   • Filtered Out: {len(skipped_expensive)}")
                log.info(f"   • Capital Deployed: ${deployed_capital:,.2f} / ${so_capital:,.2f} ({capital_efficiency:.1f}%)")
                log.info(f"")
                
                if skipped_expensive:
                    log.info(f"⚠️ Filtered {len(skipped_expensive)} signals:")
                    for sym, px, conf, reason in skipped_expensive[:5]:  # Show first 5
                        log.info(f"   • {sym} @ ${px:.2f} ({conf:.0%} conf) - {reason}")
                    if len(skipped_expensive) > 5:
                        log.info(f"   ... and {len(skipped_expensive) - 5} more")
                
                # Add concurrent count, SO capital allocation to each SO signal
                # Rev 00099: priority_rank now added BEFORE batch sizing (line 3060)
                # FIX (Oct 24, 2025): Pass total_signals so risk manager uses correct fair share divisor
                for signal_data in so_signals:
                    signal_data['num_concurrent_positions'] = len(so_signals)  # How many we're executing
                    signal_data['total_signals'] = len(so_signals_ranked)  # ⭐ CRITICAL: Total signals found (for fair share)
                    signal_data['so_capital_allocation'] = so_capital  # 90% of account for SO trades
                    signal_data['is_so_trade'] = True  # Mark as SO trade
                    # Note: priority_rank and priority_score already set before batch sizing (Rev 00099)
            
            # Add ORR reserve allocation to each ORR signal for risk manager
            if orr_signals:
                for signal_data in orr_signals:
                    signal_data['orr_reserve_allocation'] = orr_reserve  # 20% of account for ORR trades
                    signal_data['is_so_trade'] = False  # Mark as ORR trade
                    signal_data['num_concurrent_positions'] = 1  # ORR trades come one at a time
            
            # Combine SO and ORR signals for processing
            orb_signals = so_signals + orr_signals
            total_so_positions = len(so_signals)
            
            # Rev 00180T: Batch execution for Live mode, individual for Demo
            executed_so_signals = []
            rejected_so_signals = []
            
            # Rev 00180T: BATCH EXECUTION FOR LIVE MODE
            if trading_mode != "DEMO_MODE" and len(orb_signals) > 1:
                # LIVE MODE with multiple signals - BATCH EXECUTE
                log.info(f"🚀 Live Mode: Batch executing {len(orb_signals)} signals...")
                
                # Rev 00084: Use batch sizing for Live mode (same as Demo)
                from .prime_risk_manager import get_prime_risk_manager
                live_rm = get_prime_risk_manager()
                
                # Filter to SO signals only (ORR handled separately)
                so_signals_for_batch = [s for s in orb_signals if s.get('signal_type') == 'SO']
                so_signals_sized = []
                
                if so_signals_for_batch:
                    log.info(f"📊 Live Mode: Using batch position sizing (Rev 00084 Clean Flow)")
                    
                    # Get SO signals and calculate their capital
                    so_signals_only = [s for s in so_signals_for_batch]
                    so_capital_for_batch = sum(s.get('so_capital_allocation', 0) for s in so_signals_only)
                    
                    # Call batch sizing
                    so_signals_sized = await live_rm.calculate_batch_position_sizes(
                        signals=so_signals_only,
                        so_capital=so_capital_for_batch,
                        account_value=account_value,
                        max_position_pct=self.config.max_position_pct
                    )
                    
                    # Rev 00105 (Nov 6, 2025): CRITICAL - Filter out 0-quantity signals before execution
                    # Same fix as Demo mode - only keep executable signals
                    executable_signals_live = [s for s in so_signals_sized if s.get('quantity', 0) > 0]
                    rejected_count_live = len(so_signals_sized) - len(executable_signals_live)
                    
                    if rejected_count_live > 0:
                        log.warning(f"⚠️ Live Mode: {rejected_count_live} signals rejected after batch sizing (quantity=0)")
                        rejected_symbols_live = [s['symbol'] for s in so_signals_sized if s.get('quantity', 0) == 0]
                        log.warning(f"   Rejected: {', '.join(rejected_symbols_live)}")
                    
                    # Add action to executable signals only
                    for s in executable_signals_live:
                        s['action'] = 'BUY'
                    
                    so_signals_sized = executable_signals_live
                
                # Combine sized SO signals with ORR signals (if any)
                signals_with_quantity = so_signals_sized
                
                # Handle ORR signals individually (don't batch)
                # NOTE: ORR logic unchanged
                
                # Batch execute all approved signals
                if signals_with_quantity:
                    batch_result = await self._batch_execute_live_signals(signals_with_quantity)
                    executed_so_signals = batch_result.get('executed', [])
                    rejected_so_signals.extend(batch_result.get('rejected', []))
                    
                    # Record executed trades with ORB manager
                    for signal_data in executed_so_signals:
                        if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                            from .prime_orb_strategy_manager import SignalType as ORBSignalType
                            orb_signal_type = ORBSignalType.STANDARD_ORDER if signal_data.get('signal_type') == 'SO' else ORBSignalType.OPENING_RANGE_REVERSAL
                            
                            self.orb_strategy_manager.record_trade(
                                symbol=signal_data.get('original_symbol', signal_data['symbol']),
                                signal_type=orb_signal_type,
                                entry_price=signal_data['price'],
                                stop_loss=signal_data.get('stop_loss', 0.0),
                                take_profit=signal_data.get('take_profit', 0.0),
                                position_size=signal_data['position_size_pct']
                            )
            
            else:
                # DEMO MODE or single signal - Process individually
                for signal_data in orb_signals:
                    try:
                        # Create PrimeSignal from ORB result
                        from .prime_models import PrimeSignal, SignalSide, SignalType
                        
                        # Determine signal side (LONG for both bullish and inverse ETFs)
                        signal_side = SignalSide.LONG  # Always LONG (inverse ETFs are LONG positions)
                        
                        # Determine quality from confidence
                        from .prime_models import determine_signal_quality
                        signal_quality = determine_signal_quality(signal_data['confidence'])
                        
                        signal = PrimeSignal(
                            symbol=signal_data['symbol'],  # May be inverse ETF
                            side=signal_side,
                            price=signal_data['price'],
                            confidence=signal_data['confidence'],
                            quality=signal_quality,
                            quality_score=signal_data['confidence'],  # Use confidence as quality score
                            stop_loss=signal_data.get('stop_loss'),
                            take_profit=signal_data.get('take_profit'),
                            expected_return=0.03,  # 3% target for ORB trades
                            signal_type=SignalType.ENTRY,
                            reason=f"ORB {signal_data['signal_type']}: {signal_data['reasoning']}",
                            strategy_mode=self.strategy_mode,
                            metadata={
                                'orb_signal_type': signal_data['signal_type'],
                                'original_symbol': signal_data.get('original_symbol'),
                                'inverse_symbol': signal_data.get('inverse_symbol'),
                                'orb_data': signal_data.get('orb_data'),
                                'position_size_pct': signal_data['position_size_pct']
                            }
                        )
                        
                        # Get market data for the symbol
                        # Rev 00180AE: CRITICAL - Pass priority_rank and priority_score for rank-based sizing
                        
                        is_so_trade = signal_data.get('is_so_trade')
                        if is_so_trade is None:
                            is_so_trade = (signal_data.get('signal_type') == 'SO')

                        # Ensure per-signal capital metadata is always populated for Demo risk manager
                        so_capital_allocation = signal_data.get('so_capital_allocation')
                        if not so_capital_allocation and is_so_trade:
                            so_capital_allocation = so_capital

                        orr_reserve_allocation = signal_data.get('orr_reserve_allocation')
                        if orr_reserve_allocation is None:
                            orr_reserve_allocation = orr_reserve if not is_so_trade else 0

                        num_concurrent_positions = signal_data.get('num_concurrent_positions')
                        if not num_concurrent_positions and is_so_trade:
                            num_concurrent_positions = total_so_positions or 1
                        elif not num_concurrent_positions:
                            num_concurrent_positions = 1

                        # Persist the normalized flags back onto the signal for downstream consumers
                        signal_data['is_so_trade'] = is_so_trade
                        if so_capital_allocation is not None:
                            signal_data['so_capital_allocation'] = so_capital_allocation
                        signal_data['num_concurrent_positions'] = num_concurrent_positions
                        signal_data['orr_reserve_allocation'] = orr_reserve_allocation

                        market_data = {
                            'price': signal_data['price'],
                            'stop_loss': signal_data.get('stop_loss'),
                            'take_profit': signal_data.get('take_profit'),
                            'confidence': signal_data['confidence'],
                            'orb_data': signal_data.get('orb_data'),
                            'num_concurrent_positions': num_concurrent_positions,
                            'is_so_trade': is_so_trade,
                            'so_capital_allocation': so_capital_allocation or 0,
                            'orr_reserve_allocation': orr_reserve_allocation or 0,
                            'priority_rank': signal_data.get('priority_rank', 999),  # ⭐ CRITICAL for rank-based sizing
                            'priority_score': signal_data.get('priority_score', 0.0),  # ⭐ CRITICAL for rank-based sizing
                            # Rev 00176: Market Quality Gate removed - Red Day Detection Filter provides this functionality
                            'normalization_factor': signal_data.get('normalization_factor', 1.0),  # ⭐ Rev 00083: CRITICAL - Pass normalization to Risk Manager
                            'position_value_override': signal_data.get('position_value'),  # 🎯 Rev 00089: CRITICAL - Use batch-sized position value
                            'quantity_override': signal_data.get('quantity')  # 🎯 Rev 00089: CRITICAL - Use batch-sized quantity (whole shares)
                        }
                        
                        # Process signal (Demo mode)
                        execution_result = await self._process_demo_orb_signal(signal, market_data)
                        
                        # Track SO execution success/failure
                        is_so = signal_data.get('signal_type') == 'SO'
                        if is_so:
                            if execution_result:  # Successfully executed
                                # Rev 00079: Update signal_data with ACTUAL executed quantity from mock_trade
                                # Rev 00082: Also update position_value for correct alert display
                                if hasattr(execution_result, 'quantity'):
                                    signal_data['quantity'] = execution_result.quantity
                                    # Recalculate position value with actual executed quantity and price
                                    signal_data['position_value'] = execution_result.quantity * signal_data['price']
                                    log.debug(f"✅ Updated {signal.symbol} for alert: {execution_result.quantity} shares, ${signal_data['position_value']:.2f} value")
                                
                                # Add trade_id to signal_data for execution alert
                                if hasattr(execution_result, 'trade_id'):
                                    signal_data['trade_id'] = execution_result.trade_id
                                    log.debug(f"✅ Added trade_id to {signal.symbol}: {execution_result.trade_id}")
                                executed_so_signals.append(signal_data)
                            else:  # Rejected (insufficient capital or other reason)
                                rejected_so_signals.append(signal_data)
                        
                        # Record trade with ORB manager (only if executed)
                        if execution_result and hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                            from .prime_orb_strategy_manager import SignalType as ORBSignalType
                            orb_signal_type = ORBSignalType.STANDARD_ORDER if signal_data['signal_type'] == 'SO' else ORBSignalType.OPENING_RANGE_REVERSAL
                            
                            self.orb_strategy_manager.record_trade(
                                symbol=signal_data.get('original_symbol', signal_data['symbol']),
                                signal_type=orb_signal_type,
                                entry_price=signal_data['price'],
                                stop_loss=signal_data.get('stop_loss', 0.0),
                                take_profit=signal_data.get('take_profit', 0.0),
                                position_size=signal_data['position_size_pct']
                            )
                            
                    except Exception as e:
                        log.error(f"Error processing ORB signal for {signal_data['symbol']}: {e}")
            
            # Rev 00046: Mark SUCCESSFULLY EXECUTED SO symbols (prevents duplicates in future scans)
            # CRITICAL: Mark in BOTH tracking systems!
            # 1. prime_trading_system._so_executed_symbols_today (filtering)
            # 2. orb_strategy_manager.executed_symbols_today (ORB validation)
            if executed_so_signals:
                for signal_data in executed_so_signals:
                    symbol = signal_data.get('symbol')
                    original_symbol = signal_data.get('original_symbol', symbol)
                    
                    if symbol:
                        # Mark in trading system (for filtering)
                        self._so_executed_symbols_today.add(symbol)
                        
                        # Mark in ORB strategy manager (for generation-time checks)
                        if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                            self.orb_strategy_manager.executed_symbols_today.add(symbol)
                            self.orb_strategy_manager.executed_symbols_today.add(original_symbol)
                            
                            # Also mark inverse pair to prevent conflicts
                            inverse_symbol = self.orb_strategy_manager.inverse_mapping.get(original_symbol)
                            if inverse_symbol:
                                self.orb_strategy_manager.executed_symbols_today.add(inverse_symbol)
                
                log.info(f"🔒 Marked {len(executed_so_signals)} SO symbols as executed in BOTH tracking systems: {[s.get('symbol') for s in executed_so_signals]}")
            
            # Rev 00180g: Log rejected signals
            if rejected_so_signals:
                log.warning(f"⚠️ {len(rejected_so_signals)} SO signals rejected (insufficient capital): {[s.get('symbol') for s in rejected_so_signals]}")
            
            # Send aggregated SO alert (if any SO signals were processed)
            # Rev 00180g: Send alert with ACTUAL executions + rejections (not all signals)
            # Only send if we have NEW signals that weren't already alerted
            if not hasattr(self, '_so_alert_sent_today'):
                self._so_alert_sent_today = False
            
            log.info(f"🔍 SO Alert Check: executed={len(executed_so_signals)}, rejected={len(rejected_so_signals)}, alert_sent={self._so_alert_sent_today}")
            
            # Rev 00180AE: Send SO Execution alert ONLY at 7:30 AM PT (batch execution time)
            # Rev 00056: This ensures alert is sent at correct time, not during 7:15-7:30 AM scanning
            # Rev 00172: Send alert even if Red Day Filter blocked execution (0 executed, 0 rejected)
            has_so_activity = (len(executed_so_signals) > 0 or len(rejected_so_signals) > 0)
            send_alert_now = hasattr(self, '_send_so_execution_alert') and self._send_so_execution_alert
            # Check if Red Day Filter blocked execution
            red_day_blocked = getattr(self, '_red_day_filter_blocked', False)
            
            if (has_so_activity or red_day_blocked) and self.alert_manager and not self._so_alert_sent_today and send_alert_now:
                try:
                    # Rev 00180AE: Send alert even if all trades rejected (user needs to know!)
                    # Rev 00172: Send alert even if Red Day Filter blocked execution
                    if red_day_blocked:
                        log.warning(f"⚠️ Sending SO execution alert: 0 executed, 0 rejected (RED DAY FILTER BLOCKED EXECUTION)")
                    elif len(executed_so_signals) > 0:
                        log.info(f"📱 Sending SO execution alert: {len(executed_so_signals)} executed, {len(rejected_so_signals)} rejected")
                    else:
                        log.warning(f"⚠️ Sending SO execution alert: 0 executed, {len(rejected_so_signals)} rejected (ALL TRADES REJECTED!)")
                    
                    # Rev 00180e: Use actual symbol count, not hardcoded 100
                    total_scanned = len(self.symbol_list) if hasattr(self, 'symbol_list') else 65
                    
                    await self.alert_manager.send_orb_so_execution_aggregated(
                        so_signals=executed_so_signals,  # Executed signals (may be empty)
                        total_scanned=total_scanned,
                        mode=mode_display,
                        rejected_signals=rejected_so_signals,  # Rejected signals
                        account_value=account_value,  # Rev 00180AE: Pass actual account balance for accurate capital deployment
                        so_capital_pct=self.config.so_capital_pct,
                        filtered_expensive=len(skipped_expensive)  # Oct 27, 2025: Show filtered count  # Oct 24, 2025: Pass from unified config
                    )
                    log.info(f"✅ SO execution alert sent: {len(executed_so_signals)} executed, {len(rejected_so_signals)} rejected")
                    # Rev 00180g: Mark SO alert as sent (prevents duplicate alerts)
                    self._so_alert_sent_today = True
                    self._so_no_signals_alert_sent_today = True
                except Exception as alert_error:
                    log.error(f"❌ Failed to send SO execution alert: {alert_error}", exc_info=True)
            elif has_so_activity and self._so_alert_sent_today:
                log.info(f"🔒 SO execution alert already sent today - skipping duplicate")
            elif has_so_activity and not send_alert_now:
                log.info(f"⏰ SO execution alert deferred to 7:30 AM PT (batch execution time)")
            elif not has_so_activity:
                log.info(f"ℹ️ No SO activity to report (no executed or rejected trades)")
            elif not self.alert_manager:
                log.error(f"❌ Alert manager not initialized - cannot send SO alert!")
            
            # DISABLED (Rev 20251020-3): ORR alerts removed - ORR trades disabled (0% allocation)
            # Send individual ORR alerts (as they occur)
            if orr_signals and self.alert_manager:
                # ORR is disabled (0% capital allocation) - no alerts should be sent
                log.info(f"⏸️ ORR signals generated but ORR is DISABLED - skipping {len(orr_signals)} ORR alerts")
                # REMOVED: ORR alert sending (ORR trades disabled)
                # for orr_signal in orr_signals:
                #     await self.alert_manager.send_orb_orr_execution_alert(orr_signal, mode_display)
            
            if has_so_activity and send_alert_now and hasattr(self, 'daily_run_tracker') and self.daily_run_tracker:
                try:
                    metadata = {
                        "service": os.getenv("K_SERVICE"),
                        "revision": os.getenv("K_REVISION"),
                        "total_scanned": total_scanned,
                        "account_value": account_value,
                    }
                    self.daily_run_tracker.record_signal_execution(
                        executed_signals=executed_so_signals,
                        rejected_signals=rejected_so_signals,
                        mode=mode_display,
                        metadata=metadata,
                    )
                except Exception as tracker_error:
                    log.warning(f"⚠️ Failed to persist SO execution marker: {tracker_error}")
            
        except Exception as e:
            log.error(f"Error processing ORB signals: {e}")
    
    async def _process_demo_orb_signal(self, signal: PrimeSignal, market_data: Dict[str, Any]):
        """Process ORB signal in Demo Mode - Returns mock_trade if successful, None if rejected"""
        try:
            # DIAGNOSTIC (Rev 00180): Enhanced logging for Demo execution debugging
            log.info(f"🎮 Processing Demo ORB signal: {signal.symbol} @ ${signal.price:.2f}")
            
            # CRITICAL: Check market hours
            if not await self._is_market_open():
                log.warning(f"🚫 Demo Mode: Market is closed, skipping {signal.symbol}")
                return None
            
            if not self.mock_executor:
                log.error("❌ Mock trading executor not initialized")
                return None
            
            log.info(f"✅ Mock executor ready, passing market data...")
            
            # Rev 00180V: Pass market_data directly (has num_concurrent_positions, so_capital, etc.)
            # Don't create a list - pass the dict directly!
            log.info(f"📊 Executing mock trade for {signal.symbol}...")
            log.info(f"   Market Data: concurrent={market_data.get('num_concurrent_positions')}, SO capital=${market_data.get('so_capital_allocation', 0):.2f}")
            
            # Execute mock trade with full market_data
            mock_trade = await self.mock_executor.execute_mock_trade(signal, market_data)
            
            if mock_trade:
                log.info(f"✅ Mock trade executed: {mock_trade.symbol} - {mock_trade.quantity} shares @ ${mock_trade.entry_price:.2f}")
            else:
                log.warning(f"⚠️ Mock trade returned None for {signal.symbol} - likely rejected by Demo Risk Manager")
            
            # Add to stealth trailing system for monitoring
            if mock_trade and self.stealth_trailing:
                try:
                    from .prime_models import PrimePosition
                    
                    quality_attr = getattr(signal, 'quality', None)
                    if hasattr(quality_attr, 'value'):
                        quality_score = quality_attr.value
                    else:
                        mock_quality = getattr(mock_trade, 'signal_quality', None)
                        quality_score = mock_quality.value if hasattr(mock_quality, 'value') else float(getattr(signal, 'confidence', getattr(mock_trade, 'confidence', 0.0)))
                    
                    confidence = float(getattr(signal, 'confidence', getattr(mock_trade, 'confidence', 0.0)))
                    
                    position = PrimePosition(
                        position_id=mock_trade.trade_id,
                        symbol=mock_trade.symbol,
                        side=mock_trade.side,
                        quantity=mock_trade.quantity,
                        entry_price=mock_trade.entry_price,
                        current_price=mock_trade.entry_price,
                        stop_loss=mock_trade.stop_loss,
                        take_profit=mock_trade.take_profit,
                        position_value=mock_trade.position_value,
                        confidence=confidence,
                        quality_score=quality_score,
                        strategy_mode=getattr(signal, 'strategy_mode', StrategyMode.STANDARD),
                        reason=getattr(signal, 'reason', 'Demo ORB trade'),
                        entry_time=mock_trade.timestamp
                    )
                    
                    # Rev 00080: Include ORB data for entry bar protection
                    orb_data = None
                    if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                        orb_data = self.orb_strategy_manager.orb_data.get(signal.symbol)
                    market_data = {
                        'price': mock_trade.entry_price,
                        'rsi': 50.0,
                        'atr': mock_trade.entry_price * 0.02,
                        'volume_ratio': 1.0,
                        'momentum': 0.0,
                        'volatility': 0.02,
                        'entry_bar_high': orb_data.orb_high if orb_data else mock_trade.entry_price * 1.02,
                        'entry_bar_low': orb_data.orb_low if orb_data else mock_trade.entry_price * 0.98
                    }
                    
                    # CRITICAL FIX (Rev 00116): Check return value and log result
                    added = await self.stealth_trailing.add_position(position, market_data)
                    if added:
                        log.info(f"✅ Demo: Successfully added {signal.symbol} to stealth trailing (ORB) - Trade ID: {mock_trade.trade_id}")
                    else:
                        log.error(f"❌ Demo: Failed to add {signal.symbol} to stealth trailing - add_position returned False (position may already exist)")
                    
                except Exception as e:
                    log.error(f"❌ Error adding demo ORB position {signal.symbol} to stealth trailing: {e}", exc_info=True)
            elif mock_trade and not self.stealth_trailing:
                log.error(f"❌ Demo: Cannot add {signal.symbol} to stealth trailing - stealth_trailing is None!")
            elif not mock_trade:
                log.warning(f"⚠️ Demo: No mock_trade returned for {signal.symbol} - cannot add to stealth trailing")
            
            # Rev 00180g: Return mock_trade for execution tracking
            return mock_trade
            
        except Exception as e:
            log.error(f"Error processing demo ORB signal: {e}")
            return None
    
    async def _process_live_orb_signal(self, signal: PrimeSignal, market_data: Dict[str, Any]):
        """Process ORB signal in Live Mode - Returns trade_result if successful, None if rejected"""
        try:
            # CRITICAL: Check market hours
            if not await self._is_market_open():
                log.warning(f"🚫 Live Mode: Market is closed, skipping {signal.symbol}")
                return None
            
            # Validate signal through risk manager
            if not self.risk_manager:
                log.error("Risk manager not available")
                return None
            
            risk_assessment = await self.risk_manager.assess_signal_risk(signal)
            
            if not risk_assessment or not risk_assessment.get('approved', False):
                log.warning(f"⚠️ Live Mode: Risk manager rejected {signal.symbol}")
                return None
            
            # Execute trade through trade manager
            if not self.trade_manager:
                log.error("Trade manager not available")
                return None
            
            # Use position size from ORB signal
            position_size_pct = signal.metadata.get('position_size_pct', 25.0)
            
            trade_result = await self.trade_manager.execute_trade(
                signal=signal,
                position_size_pct=position_size_pct,
                risk_assessment=risk_assessment
            )
            
            if trade_result and trade_result.get('success'):
                log.info(f"✅ Live: Executed ORB trade for {signal.symbol} @ ${signal.price:.2f}")
                
                # Add to stealth trailing system for monitoring
                if self.stealth_trailing and trade_result.get('position'):
                    # Rev 00080: Include ORB data for entry bar protection
                    orb_data = None
                    if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                        orb_data = self.orb_strategy_manager.orb_data.get(signal.symbol)
                    market_data = {
                        'price': signal.price,
                        'rsi': 50.0,
                        'atr': signal.price * 0.02,
                        'volume_ratio': 1.0,
                        'momentum': 0.0,
                        'volatility': 0.02,
                        'entry_bar_high': orb_data.orb_high if orb_data else signal.price * 1.02,
                        'entry_bar_low': orb_data.orb_low if orb_data else signal.price * 0.98
                    }
                    
                    # Rev 00122: CRITICAL FIX - Check return value and handle failures
                    added = await self.stealth_trailing.add_position(trade_result['position'], market_data)
                    if added:
                        log.info(f"✅ Live: Successfully added {signal.symbol} to stealth trailing (ORB) - Trade ID: {trade_result.get('order_id', 'N/A')}")
                    else:
                        log.error(f"❌ Live: Failed to add {signal.symbol} to stealth trailing - add_position returned False (position may already exist or error occurred)")
                        # Store for orphaned position tracking (Live mode)
                        if not hasattr(self, '_orphaned_live_positions'):
                            self._orphaned_live_positions = []
                        self._orphaned_live_positions.append({
                            'symbol': signal.symbol,
                            'position': trade_result['position'],
                            'market_data': market_data,
                            'timestamp': datetime.utcnow()
                        })
                        log.warning(f"⚠️ Live: Position {signal.symbol} stored for orphaned tracking - will attempt to sync from E*TRADE API")
                
                # Rev 00180g: Return trade_result for execution tracking
                return trade_result
            else:
                log.warning(f"⚠️ Live: Trade execution failed for {signal.symbol}")
                return None
            
        except Exception as e:
            log.error(f"Error processing live ORB signal: {e}")
            return None
    
    def _get_trading_mode(self) -> str:
        """Determine current trading mode"""
        try:
            # Check configuration for trading mode
            trading_mode = get_config_value('TRADING_MODE', 'demo')
            
            # Handle both string and boolean values
            if isinstance(trading_mode, bool):
                return "DEMO_MODE" if not trading_mode else "LIVE_MODE"
            else:
                mode = str(trading_mode).lower()
                if mode in ['demo', 'demo_mode', 'mock', 'simulation']:
                    return "DEMO_MODE"
                elif mode in ['live', 'live_mode', 'production', 'real']:
                    return "LIVE_MODE"
                else:
                    # Default to demo mode for safety
                    return "DEMO_MODE"
                
        except Exception as e:
            log.error(f"Error determining trading mode: {e}")
            return "DEMO_MODE"  # Default to demo mode for safety
    
    async def _process_demo_signal(self, signal: PrimeSignal, market_data: Dict[str, Any]):
        """Process signal in Demo Mode using mock trading executor"""
        try:
            # CRITICAL: Check market hours before executing any trades
            if not await self._is_market_open():
                log.warning(f"🚫 Demo Mode: Market is closed, skipping trade execution for {signal.symbol}")
                return
            
            if not self.mock_executor:
                log.error("Mock trading executor not initialized")
                return
            
            # Rev 00180V: Pass market_data directly (no list creation needed)
            # market_data already has all critical fields from ORB signal processing
            
            # Execute mock trade with full market_data
            mock_trade = await self.mock_executor.execute_mock_trade(signal, market_data)
            
            # Add to stealth trailing system for position monitoring
            if mock_trade and self.stealth_trailing:
                try:
                    # Convert MockTrade to PrimePosition for stealth trailing
                    from .prime_models import PrimePosition
                    
                    prime_position = PrimePosition(
                        position_id=mock_trade.trade_id,
                        symbol=mock_trade.symbol,
                        side=mock_trade.side,
                        quantity=mock_trade.quantity,
                        entry_price=mock_trade.entry_price,
                        current_price=mock_trade.entry_price,
                        stop_loss=mock_trade.stop_loss,
                        take_profit=mock_trade.take_profit,
                        position_value=mock_trade.position_value,  # Oct 27, 2025: CRITICAL FIX (same bug as Oct 24!)
                        confidence=getattr(signal, 'confidence', 0.85),
                        quality_score=getattr(signal, 'quality', 0.85).value if hasattr(signal, 'quality') else 0.85,
                        strategy_mode=getattr(signal, 'strategy_mode', StrategyMode.STANDARD),
                        reason=getattr(signal, 'reason', 'Demo Mode trade'),
                        entry_time=mock_trade.timestamp
                    )
                    
                    # Create market data for stealth trailing
                    # Rev 00080: Include ORB data for entry bar protection
                    orb_data = None
                    if hasattr(self, 'orb_strategy_manager') and self.orb_strategy_manager:
                        orb_data = self.orb_strategy_manager.orb_data.get(signal.symbol)
                    market_data_dict = {
                        'price': mock_trade.entry_price,
                        'rsi': 50.0,  # Default RSI
                        'atr': 2.0,   # Default ATR
                        'volume_ratio': 1.0,
                        'momentum': 0.0,
                        'volatility': 0.01,
                        'volume': 1000000,  # Default volume
                        'high': mock_trade.entry_price * 1.02,
                        'low': mock_trade.entry_price * 0.98,
                        'open': mock_trade.entry_price,
                        'close': mock_trade.entry_price,
                        'entry_bar_high': orb_data.orb_high if orb_data else mock_trade.entry_price * 1.02,
                        'entry_bar_low': orb_data.orb_low if orb_data else mock_trade.entry_price * 0.98
                    }
                    
                    # Add position to stealth trailing system
                    await self.stealth_trailing.add_position(prime_position, market_data_dict)
                    log.info(f"🎮 Demo Mode: Added {signal.symbol} to stealth trailing system")
                    
                except Exception as stealth_error:
                    log.error(f"Failed to add mock trade to stealth trailing: {stealth_error}")
            
            if mock_trade:
                log.info(f"🎮 DEMO BUY SIGNAL EXECUTED: {signal.symbol} @ ${signal.price:.2f} "
                        f"(Confidence: {signal.confidence:.1%}) - Trade ID: {mock_trade.trade_id}")
                
                # Note: Trade execution alert is sent by mock_trading_executor.py
                # No need to send duplicate alert here
            else:
                log.warning(f"Demo mock trade failed for {signal.symbol}")
                
        except Exception as e:
            log.error(f"Error processing demo mock signal for {signal.symbol}: {e}")
    
    async def _process_live_signal(self, signal: PrimeSignal, market_data: Dict[str, Any]):
        """Process signal in Live Mode using real E*TRADE trading"""
        try:
            # CRITICAL: Check market hours before executing any trades
            if not await self._is_market_open():
                log.warning(f"🚫 Live Mode: Market is closed, skipping trade execution for {signal.symbol}")
                return
            
            if not self.trade_manager:
                log.error("Trade manager not initialized for live trading")
                return
            
            # Process signal through real trading system
            trade_result = await self.trade_manager.process_signal(signal, market_data)
            
            if trade_result.action.value == "open":
                log.info(f"💰 LIVE BUY SIGNAL EXECUTED: {signal.symbol} @ ${signal.price:.2f} "
                        f"(Confidence: {signal.confidence:.1%})")
                
                # DEPRECATED (Rev 20251020-3): Individual SO alerts removed
                # Rev 00056: SO trades use BATCH aggregated alert (send_orb_so_execution_aggregated) at 7:30 AM PT
                # This old method sends incorrect individual alerts - DISABLED
                # if self.alert_manager:
                #     await self.alert_manager.send_trade_execution_alert(...)
                log.debug(f"✅ Live trade executed: {signal.symbol} (batch alert will be sent at 7:30 AM PT)")
            else:
                log.debug(f"Live signal not executed for {signal.symbol}: {trade_result.reasoning}")
                
        except Exception as e:
            log.error(f"Error processing live real signal for {signal.symbol}: {e}")
    
    def _create_mock_market_data_list(self, symbol: str, market_data: Dict[str, Any]) -> List[Dict]:
        """Create mock market data list for signal generation"""
        try:
            # Create realistic historical data for the symbol
            base_price = market_data.get('price', 100.0)
            volume_ratio = market_data.get('volume_ratio', 1.0)
            
            mock_data = []
            current_price = base_price
            
            for i in range(100):  # 100 data points
                # Simulate price movement
                price_change = np.random.normal(0.001, 0.02)
                current_price *= (1 + price_change)
                
                # Create OHLC data
                open_price = current_price * np.random.uniform(0.998, 1.002)
                close_price = current_price
                high_price = max(open_price, close_price) * np.random.uniform(1.001, 1.015)
                low_price = min(open_price, close_price) * np.random.uniform(0.985, 0.999)
                
                mock_data.append({
                    'timestamp': datetime.utcnow() - timedelta(hours=100-i),  # Rev 00073: UTC consistency
                    'open': round(open_price, 2),
                    'high': round(high_price, 2),
                    'low': round(low_price, 2),
                    'close': round(close_price, 2),
                    'volume': int(1000000 * volume_ratio * np.random.uniform(0.8, 1.2))
                })
            
            return mock_data
            
        except Exception as e:
            log.error(f"Error creating mock market data for {symbol}: {e}")
            return []
    
    async def _generate_signals_task(self) -> Dict[str, Any]:
        """
        Generate trading signals task
        
        Note: Primary signal generation now happens in _scan_watchlist_for_signals via ORB Manager.
        This task validates signals through production signal generator for additional quality checks.
        """
        try:
            # CRITICAL: Check market hours FIRST - no signal generation after market close
            is_market_open = await self._is_market_open()
            if not is_market_open:
                log.info(f"⏸️ Market closed - skipping signal generation")
                return {}
            
            # ARCHIVED (Rev 00173): Signal validation task no longer used
            log.debug(f"⏸️ Signal validation task skipped (ORB validates directly)")
            return {}
            
            # if not self.signal_generator:
            #     log.warning(f"⚠️ Signal generator not available in _generate_signals_task")
            #     return {}
            
            # Get market data for signal generation
            symbols = await self._get_active_symbols()
            log.info(f"📊 Got {len(symbols) if symbols else 0} active symbols for signal generation")
            if not symbols:
                log.warning(f"⚠️ No active symbols for signal generation - returning early")
                return {}
            
            # OPTIMIZATION 1: BATCH fetch historical data (SINGLE yfinance API call for ALL symbols)
            log.info(f"📊 Fetching historical data for {len(symbols)} symbols (SINGLE batch call)...")
            batch_historical_data = {}
            
            try:
                # CRITICAL: Use data_manager.get_batch_historical_data() for SINGLE API call
                # Rev 00125: datetime and timedelta already imported at top of file - removed redundant local import
                end_date = datetime.utcnow()  # Rev 00073: UTC consistency
                start_date = end_date - timedelta(days=100)
                
                # SINGLE BATCH CALL for all 100 symbols (99% API reduction)
                batch_historical_data = await self.data_manager.get_batch_historical_data(
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    interval="1d"
                )
                
                log.info(f"✅ BATCH fetch complete: {len(batch_historical_data)}/{len(symbols)} symbols (SINGLE API call)")
            except Exception as hist_error:
                log.warning(f"⚠️ Error fetching batch historical data: {hist_error}")
                batch_historical_data = {}
            
            # Store batch historical data for use in _generate_signal_for_symbol
            self._batch_historical_data = batch_historical_data
            
            # OPTIMIZATION 2: STREAMING batch processing (process each batch as it completes)
            # Instead of waiting for all 4 batches, process symbols from each batch immediately
            log.info(f"📡 Starting STREAMING batch processing for {len(symbols)} symbols (25 per batch)...")
            
            # Check if E*TRADE is available
            has_etrade = self.trade_manager and hasattr(self.trade_manager, 'etrade_trading') and self.trade_manager.etrade_trading
            log.info(f"📊 E*TRADE availability: {has_etrade}")
            
            # Initialize storage
            self._batch_quotes = {}
            all_signals = {}
            symbols_with_recommendations = []
            
            if has_etrade:
                try:
                    # Rev 00124: asyncio already imported at top of file - removed redundant local import
                    # Process each batch of 25 symbols immediately (don't wait for all batches)
                    num_batches = (len(symbols) - 1) // 25 + 1
                    
                    for i in range(0, len(symbols), 25):
                        batch_symbols = symbols[i:i+25]
                        batch_num = i//25 + 1
                        
                        log.info(f"📦 BATCH {batch_num}/{num_batches}: Fetching {len(batch_symbols)} symbols...")
                        
                        # Fetch quotes for this batch with timeout
                        try:
                            quotes = await asyncio.wait_for(
                                asyncio.to_thread(self.trade_manager.etrade_trading.get_quotes, batch_symbols),
                                timeout=30.0  # 30 second timeout per batch
                            )
                            log.info(f"✅ BATCH {batch_num}: Got {len(quotes) if quotes else 0} quotes")
                            
                            # Store quotes
                            if quotes:
                                for quote in quotes:
                                    if hasattr(quote, 'symbol'):
                                        self._batch_quotes[quote.symbol] = {
                                            'bid': quote.bid if hasattr(quote, 'bid') else 0.0,
                                            'ask': quote.ask if hasattr(quote, 'ask') else 0.0,
                                            'last': quote.last_price if hasattr(quote, 'last_price') else 0.0,
                                            'volume': quote.volume if hasattr(quote, 'volume') else 0
                                        }
                            
                            # IMMEDIATE PROCESSING: Generate signals for this batch right away
                            log.info(f"🚀 BATCH {batch_num}: Processing {len(batch_symbols)} symbols immediately...")
                            batch_signals = await self.parallel_manager.process_symbols_parallel(
                                batch_symbols,
                                self._generate_signal_for_symbol
                            )
                            
                            # Merge batch signals into all_signals
                            all_signals.update(batch_signals)
                            log.info(f"✅ BATCH {batch_num}: Processed {len(batch_signals)} symbols (total: {len(all_signals)})")
                            
                        except asyncio.TimeoutError:
                            log.warning(f"⏰ BATCH {batch_num}: Timeout after 30s - skipping this batch")
                        except Exception as batch_error:
                            log.error(f"❌ BATCH {batch_num}: Error - {batch_error}")
                    
                    log.info(f"✅ STREAMING processing complete: {len(all_signals)}/{len(symbols)} symbols processed")
                    
                except Exception as quote_error:
                    log.error(f"❌ Failed in streaming batch processing: {quote_error}", exc_info=True)
            else:
                log.warning(f"⚠️ E*TRADE not available - trade_manager: {self.trade_manager is not None}")
                # Fallback: process all symbols without quotes
                all_signals = await self.parallel_manager.process_symbols_parallel(
                    symbols,
                    self._generate_signal_for_symbol
                )
            
            # Use all_signals instead of signals
            signals = all_signals
            
            # Process generated signals and collect multi-strategy recommendations
            processed_signals = []
            print(f"🔥🔥🔥 CRITICAL DEBUG: Processing {len(signals)} signal results from parallel generation...")
            log.warning(f"🔥🔥🔥 CRITICAL DEBUG: Processing {len(signals)} signal results from parallel generation...")
            log.info(f"📊 Processing {len(signals)} signal results from parallel generation...")
            for symbol, signal in signals.items():
                print(f"🔥 CRITICAL DEBUG: Signal for {symbol}: type={type(signal)}")
                log.warning(f"🔥 CRITICAL DEBUG: Signal for {symbol}: type={type(signal)}")
                log.info(f"🔍 Signal for {symbol}: type={type(signal)}, is_exception={isinstance(signal, Exception)}, is_none={signal is None}")
                if signal and not isinstance(signal, Exception):
                    processed_signals.append(signal)
                    log.info(f"✅ Added {symbol} to processed_signals (total: {len(processed_signals)})")
                    
                    # Collect multi-strategy recommendation data for aggregated alert
                    if isinstance(signal, dict) and 'multi_strategy_agreement' in signal:
                        symbols_with_recommendations.append({
                            'symbol': symbol,
                            'confidence': signal.get('confidence', 0),
                            'agreement': signal.get('multi_strategy_agreement', 'UNKNOWN'),
                            'agreement_count': f"{len(signal.get('multi_strategy_agreements', []))}/8"
                        })
                        log.info(f"✅ Added {symbol} to recommendations list")
            
            log.info(f"📊 Final processed_signals count: {len(processed_signals)}")
            
            # Track previous recommendations to detect NEW ones
            if not hasattr(self, '_last_recommendations'):
                self._last_recommendations = set()
            
            current_recommendations = set(rec['symbol'] for rec in symbols_with_recommendations)
            
            # Check if there are NEW recommendations (symbols not in previous list)
            new_recommendations = current_recommendations - self._last_recommendations
            has_new_recommendations = len(new_recommendations) > 0
            
            # DEBUG: Log recommendation tracking
            log.info(f"📊 Recommendation tracking: {len(symbols_with_recommendations)} current, {len(self._last_recommendations)} previous, {len(new_recommendations)} NEW")
            if new_recommendations:
                log.info(f"🆕 NEW recommendations: {list(new_recommendations)[:10]}")
            
            # Send aggregated multi-strategy analysis alert ONLY if we have NEW recommendations
            if has_new_recommendations and symbols_with_recommendations and hasattr(self, 'alert_manager') and self.alert_manager:
                try:
                    await self.alert_manager.send_multi_strategy_analysis_aggregated(
                        symbols_with_recommendations=symbols_with_recommendations,
                        total_analyzed=len(symbols)
                    )
                    log.info(f"📱 Aggregated multi-strategy alert sent - {len(new_recommendations)} NEW recommendations (Full list: {len(symbols_with_recommendations)} total from {len(symbols)} analyzed)")
                    
                    # Update the last recommendations list
                    self._last_recommendations = current_recommendations
                except Exception as alert_error:
                    log.warning(f"Failed to send aggregated multi-strategy alert: {alert_error}")
            elif not has_new_recommendations and symbols_with_recommendations:
                log.debug(f"No NEW recommendations found - skipping aggregated alert (current: {len(symbols_with_recommendations)}, same as previous)")
            
            # Send a status alert on FIRST cycle if 0 signals found (so user knows system is working)
            # Rev 00198: Renamed flag to follow _*_sent_today convention
            if not hasattr(self, '_zero_signals_alert_sent_today'):
                self._zero_signals_alert_sent_today = False
            
            if len(symbols_with_recommendations) == 0 and not self._zero_signals_alert_sent_today and hasattr(self, 'alert_manager') and self.alert_manager:
                try:
                    await self.alert_manager.send_multi_strategy_status_alert(
                        symbols_analyzed=len(symbols),
                        signals_found=0,
                        market_condition="Waiting for qualified setups"
                    )
                    self._zero_signals_alert_sent_today = True
                    log.info(f"📱 Multi-strategy status alert sent - 0 signals found (system operational)")
                except Exception as alert_error:
                    log.warning(f"Failed to send multi-strategy status alert: {alert_error}")
            
            self.performance_metrics['signals_generated'] += len(processed_signals)
            
            # CRITICAL FIX: Execute the generated signals!
            if processed_signals:
                log.info(f"🚀 Executing {len(processed_signals)} generated signals...")
                log.info(f"📊 Processed signals type: {type(processed_signals)}, count: {len(processed_signals)}")
                
                for i, signal_dict in enumerate(processed_signals):
                    try:
                        log.info(f"🔍 Processing signal {i+1}/{len(processed_signals)}: type={type(signal_dict)}")
                        
                        # Extract signal object from dict
                        signal_obj = signal_dict.get('signal') if isinstance(signal_dict, dict) else signal_dict
                        
                        if not signal_obj:
                            log.warning(f"❌ No signal object found in signal_dict: {list(signal_dict.keys()) if isinstance(signal_dict, dict) else type(signal_dict)}")
                            continue
                        
                        # Get symbol for logging
                        symbol = signal_obj.symbol if hasattr(signal_obj, 'symbol') else signal_dict.get('symbol', 'UNKNOWN')
                        log.info(f"📊 Extracted symbol: {symbol}, signal_obj type: {type(signal_obj)}")
                        
                        # Check if position already exists for this symbol
                        has_open_position = False
                        try:
                            current_positions = await self._get_current_positions()
                            if current_positions and symbol in current_positions:
                                has_open_position = True
                                log.info(f"⏭️ Skipping {symbol} - Position already open (no duplicate positions)")
                                continue
                        except Exception as pos_check_error:
                            log.warning(f"⚠️ Failed to check existing positions for {symbol}: {pos_check_error}")
                            # Continue with execution if position check fails (fail-open)
                        
                        # Execute based on mode
                        if self.config.mode == SystemMode.DEMO_MODE:
                            log.info(f"🎮 Executing DEMO trade for {symbol} (mode: {self.config.mode})...")
                            # Get market data for execution (use empty dict as fallback)
                            market_data = {}
                            await self._process_demo_mock_signal(signal_obj, market_data)
                            log.info(f"✅ DEMO trade execution completed for {symbol}")
                        else:
                            log.info(f"💰 Executing LIVE trade for {symbol} (mode: {self.config.mode})...")
                            # Get market data for execution
                            market_data = {}
                            await self._process_live_real_signal(signal_obj, market_data)
                            log.info(f"✅ LIVE trade execution completed for {symbol}")
                            
                    except Exception as e:
                        log.error(f"❌ Failed to execute signal {i+1}: {e}", exc_info=True)
                
                log.info(f"✅ Signal execution complete - {len(processed_signals)} signals processed")
            else:
                log.info(f"ℹ️  No signals to execute (processed_signals is empty or None)")
            
            # Cleanup: Clear batch data to free memory
            if hasattr(self, '_batch_quotes'):
                del self._batch_quotes
            if hasattr(self, '_batch_historical_data'):
                del self._batch_historical_data
            
            log.debug(f"🧹 Cleared batch data cache to free memory")
            
            return {'signals': processed_signals, 'count': len(processed_signals)}
            
        except Exception as e:
            log.error(f"Error generating signals: {e}")
            # Cleanup on error too
            if hasattr(self, '_batch_quotes'):
                del self._batch_quotes
            if hasattr(self, '_batch_historical_data'):
                del self._batch_historical_data
            return {}
    
    async def _update_positions_task(self) -> Dict[str, Any]:
        """Update positions task"""
        try:
            if not self.trade_manager:
                return {}
            
            # Get current positions
            positions = await self._get_current_positions()
            if not positions:
                return {}
            
            # Update positions in parallel
            updates = await self.parallel_manager.process_symbols_parallel(
                list(positions.keys()),
                self._update_position_for_symbol
            )
            
            # Process updates
            updated_count = len([u for u in updates.values() if u and not isinstance(u, Exception)])
            self.performance_metrics['positions_updated'] += updated_count
            
            return {'updates': updates, 'count': updated_count}
            
        except Exception as e:
            log.error(f"Error updating positions: {e}")
            return {}
    
    async def _assess_risk_task(self) -> Dict[str, Any]:
        """Assess risk task"""
        try:
            if not self.risk_manager:
                return {}
            
            # Get risk assessment
            risk_summary = self.risk_manager.get_risk_summary()
            return {'risk_summary': risk_summary}
            
        except Exception as e:
            log.error(f"Error assessing risk: {e}")
            return {}
    
    async def _update_stealth_task(self) -> Dict[str, Any]:
        """Update stealth trailing task"""
        try:
            if not self.stealth_trailing:
                return {}
            
            # Update stealth trailing for all positions
            positions = await self._get_current_positions()
            if not positions:
                return {}
            
            # Update stealth trailing in parallel
            updates = await self.parallel_manager.process_symbols_parallel(
                list(positions.keys()),
                self._update_stealth_for_symbol
            )
            
            return {'updates': updates, 'count': len(updates)}
            
        except Exception as e:
            log.error(f"Error updating stealth trailing: {e}")
            return {}
    
    async def _generate_signal_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        ARCHIVED (Rev 00173): Generate signal for a specific symbol
        
        ❌ NO LONGER CALLED - ORB strategy generates signals directly
        Method kept for backward compatibility only.
        """
        try:
            # ARCHIVED (Rev 00173): Signal generator no longer used
            log.debug(f"⏸️ Signal generation skipped for {symbol} (ORB validates directly)")
            return None
            
            # if not self.signal_generator:
            #     return None
            
            # NEW (Oct 11, 2025): Get market data from DAILY CACHE
            # Historical data cached once daily at 8:35 AM - FAST access!
            market_data = None
            
            # Get cached historical data from today's cache key
            cache_key = f"daily_historical_{datetime.utcnow().strftime('%Y-%m-%d')}"  # Rev 00073: UTC consistency
            
            try:
                if self.data_manager and hasattr(self.data_manager, 'cache_manager'):
                    cached_daily_data = await self.data_manager.cache_manager.get(cache_key)
                    if cached_daily_data and symbol in cached_daily_data:
                        # Use cached historical data (instant!)
                        market_data = cached_daily_data[symbol].copy()  # Deep copy to avoid mutating cache
                        log.debug(f"📊 Using CACHED historical data for {symbol} ({len(market_data)} days)")
                    else:
                        log.debug(f"⚠️ No cached data for {symbol}, falling back to individual fetch")
            except Exception as cache_error:
                log.debug(f"Cache retrieval error for {symbol}: {cache_error}")
            
            # Fallback to individual fetch if cache miss
            if not market_data:
                market_data = await self.data_manager.get_historical_data(symbol, datetime.utcnow() - timedelta(days=100), datetime.utcnow(), "1d")  # Rev 00073: UTC consistency
                log.debug(f"📊 Individual fetch for {symbol}: {len(market_data) if market_data else 0} days")
            
            if not market_data:
                log.warning(f"⚠️ No market data available for {symbol}")
                return None
            
            # Get real-time quote for current bid/ask (needed for liquidity gates)
            # Use pre-fetched batch quotes (from _generate_signals_task) to save API calls
            quote_bid = 0.0
            quote_ask = 0.0
            
            if hasattr(self, '_batch_quotes') and symbol in self._batch_quotes:
                # Use pre-fetched batch quote (efficient!)
                batch_quote = self._batch_quotes[symbol]
                quote_bid = batch_quote.get('bid', 0.0)
                quote_ask = batch_quote.get('ask', 0.0)
                log.debug(f"📈 Using batch quote for {symbol}: bid=${quote_bid:.2f}, ask=${quote_ask:.2f}")
            else:
                # Fallback: Individual quote if batch not available
                try:
                    import asyncio
                    if self.trade_manager and hasattr(self.trade_manager, 'etrade_trading') and self.trade_manager.etrade_trading:
                        # CRITICAL FIX: Use asyncio.to_thread() for synchronous E*TRADE call
                        quotes = await asyncio.to_thread(self.trade_manager.etrade_trading.get_quotes, [symbol])
                        if quotes and len(quotes) > 0:
                            quote = quotes[0]
                            quote_bid = quote.bid if hasattr(quote, 'bid') else 0.0
                            quote_ask = quote.ask if hasattr(quote, 'ask') else 0.0
                            log.debug(f"📈 Individual quote for {symbol}: bid=${quote_bid:.2f}, ask=${quote_ask:.2f}")
                except Exception as quote_error:
                    log.debug(f"Could not get individual quote for {symbol}: {quote_error}")
            
            # Two-step signal generation process
            
            # ARCHIVED (Rev 00173): Multi-Strategy Manager and Signal Generator no longer used
            # ORB Strategy Manager generates and validates signals directly
            # 
            # Step 1: Multi-Strategy Manager (Screening) - ARCHIVED
            # Step 2: Production Signal Generator (Final Confirmation) - ARCHIVED
            # 
            # if hasattr(self, 'multi_strategy_manager') and self.multi_strategy_manager:
            #     multi_result = await self.multi_strategy_manager.analyze_symbol(symbol, strategy_market_data)
            #     if not multi_result.should_trade:
            #         return None
            # 
            # if hasattr(self, 'signal_generator') and self.signal_generator:
            #     signal = await self.signal_generator.generate_profitable_signal(symbol, signal_market_data, self.strategy_mode)
            
            log.debug(f"⏸️ Multi-strategy and signal generator skipped for {symbol} (ORB validates directly)")
            signal = None  # No signal from legacy system
            
            # ARCHIVED (Rev 00173): Signal generator alerts and multi-strategy metadata no longer used
            # ORB Strategy Manager handles all signal generation and validation directly
            # 
            # if self.alert_manager and signal:
            #     await self.alert_manager.send_signal_generator_alert(...)
            # 
            # if hasattr(self, 'multi_strategy_manager') and self.multi_strategy_manager and multi_result:
            #     signal['multi_strategy_agreement'] = multi_result.agreement_level.value
            
            log.debug(f"⏸️ Legacy signal processing skipped for {symbol} (ORB only)")
            return None  # No signal from legacy system
            
        except Exception as e:
            log.error(f"Error generating signal for {symbol}: {e}")
            return None
    
    async def _update_position_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Update position for a specific symbol"""
        try:
            if not self.trade_manager:
                return None
            
            # Get market data
            market_data = await self.data_manager.get_market_data(symbol)
            if not market_data:
                return None
            
            # Update position
            update = await self.trade_manager.update_position(symbol, market_data)
            return update
            
        except Exception as e:
            log.error(f"Error updating position for {symbol}: {e}")
            return None
    
    async def _process_demo_mock_signal(self, signal, market_data: Dict[str, Any]) -> bool:
        """⚡ LIGHTNING-FAST Demo trade execution using unified trade manager"""
        try:
            if not self.trade_manager:
                log.error("❌ Trade manager not available")
                return False
            
            # SPEED OPTIMIZATION: Single call to trade_manager.process_signal()
            # This handles: market hours check, position sizing, mock execution, alerts
            log.info(f"⚡ DEMO execution starting for {signal.symbol}...")
            
            result = await self.trade_manager.process_signal(signal, market_data)
            
            if result and result.action == TradeAction.OPEN:
                log.info(f"✅ DEMO trade executed: {signal.symbol}")
                return True
            else:
                log.warning(f"⚠️ DEMO trade rejected: {signal.symbol} - {result.reasoning if result else 'Unknown'}")
                return False
                
        except Exception as e:
            log.error(f"❌ Demo execution error for {signal.symbol}: {e}", exc_info=True)
            return False
    
    async def _process_live_real_signal(self, signal, market_data: Dict[str, Any]) -> bool:
        """⚡ LIGHTNING-FAST Live trade execution using unified trade manager"""
        try:
            if not self.trade_manager:
                log.error("❌ Trade manager not available")
                return False
            
            # SPEED OPTIMIZATION: Single call to trade_manager.process_signal()
            # This handles: market hours check, risk validation, position sizing, E*TRADE order, alerts
            log.info(f"⚡ LIVE execution starting for {signal.symbol}...")
            
            result = await self.trade_manager.process_signal(signal, market_data)
            
            if result and result.action == TradeAction.OPEN:
                log.info(f"✅ LIVE trade executed: {signal.symbol}")
                return True
            else:
                log.warning(f"⚠️ LIVE trade rejected: {signal.symbol} - {result.reasoning if result else 'Unknown'}")
                return False
                
        except Exception as e:
            log.error(f"❌ Live execution error for {signal.symbol}: {e}", exc_info=True)
            return False
    
    async def _update_stealth_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Update stealth trailing for a specific symbol with comprehensive market data"""
        try:
            if not self.stealth_trailing:
                return None
            
            # Get comprehensive market data with all required features
            end_date = datetime.utcnow()  # Rev 00073: UTC consistency
            start_date = end_date - timedelta(days=30)
            
            # Get historical data for technical analysis
            historical_data = await self.data_manager.get_historical_data(symbol, start_date, end_date, "1d")
            if not historical_data or len(historical_data) < 20:
                log.warning(f"Insufficient historical data for stealth analysis of {symbol}")
                return None
            
            # Extract current price and calculate technical indicators
            current_price = historical_data[-1]['close']
            prices = [d['close'] for d in historical_data[-20:]]
            volumes = [d['volume'] for d in historical_data[-20:]]
            
            # Calculate technical indicators
            rsi = self._calculate_rsi(prices)
            atr = self._calculate_atr(historical_data[-14:])
            volume_ratio = volumes[-1] / np.mean(volumes[:-1]) if len(volumes) > 1 else 1.0
            momentum = (prices[-1] - prices[-5]) / prices[-5] if len(prices) >= 5 else 0.0
            volatility = np.std(prices) / np.mean(prices) if prices else 0.0
            
            # Create comprehensive market data for stealth system
            market_data = {
                'price': current_price,
                'rsi': rsi,
                'atr': atr,
                'volume_ratio': volume_ratio,
                'momentum': momentum,
                'volatility': volatility,
                'volume': volumes[-1],
                'high': historical_data[-1]['high'],
                'low': historical_data[-1]['low'],
                'open': historical_data[-1]['open'],
                'close': current_price
            }
            
            # Update stealth trailing with comprehensive data
            update = await self.stealth_trailing.update_position(symbol, market_data)
            return update
            
        except Exception as e:
            log.error(f"Error updating stealth for {symbol}: {e}")
            return None
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [delta if delta > 0 else 0 for delta in deltas]
        losses = [-delta if delta < 0 else 0 for delta in deltas]
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_atr(self, historical_data: List[Dict], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(historical_data) < 2:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(historical_data)):
            high = historical_data[i]['high']
            low = historical_data[i]['low']
            prev_close = historical_data[i-1]['close']
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            
            true_range = max(tr1, tr2, tr3)
            true_ranges.append(true_range)
        
        if not true_ranges:
            return 0.0
        
        return np.mean(true_ranges[-period:]) if len(true_ranges) >= period else np.mean(true_ranges)
    
    async def _get_active_symbols(self) -> List[str]:
        """Get list of active symbols for processing - uses symbol_list from Symbol Selector"""
        try:
            # Return the symbol list from Symbol Selector (100 selected symbols)
            if hasattr(self, 'symbol_list') and self.symbol_list:
                log.info(f"📊 Returning {len(self.symbol_list)} active symbols from symbol_list")
                return self.symbol_list
            else:
                # Fallback to default list if symbol_list not available
                log.warning("⚠️ symbol_list not available, using fallback 10 symbols")
                return ["SPY", "QQQ", "TQQQ", "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META"]
        except Exception as e:
            log.error(f"Error getting active symbols: {e}")
            return []
    
    async def _get_current_positions(self) -> Dict[str, Any]:
        """Get current positions from appropriate source (Demo or Live Mode)"""
        try:
            # Check if we're in Demo Mode
            if self.config.mode == SystemMode.DEMO_MODE and hasattr(self, 'mock_executor') and self.mock_executor:
                # Get mock positions from Demo Mode
                mock_positions = self.mock_executor.get_active_positions()
                if mock_positions:
                    # Convert mock positions to format expected by stealth trailing
                    positions = {}
                    for trade_id, trade in mock_positions.items():
                        positions[trade.symbol] = {
                            'symbol': trade.symbol,
                            'entry_price': trade.entry_price,
                            'current_price': trade.current_price,
                            'quantity': trade.quantity,
                            'side': trade.side.value if hasattr(trade.side, 'value') else str(trade.side),
                            'status': trade.status,
                            'entry_time': trade.timestamp,
                            'confidence': getattr(trade, 'confidence', 0.85),
                            'stop_loss': getattr(trade, 'stop_loss', trade.entry_price * 0.95),
                            'take_profit': getattr(trade, 'take_profit', trade.entry_price * 1.15),
                            'trade_id': trade_id,
                            'source': 'demo'
                        }
                    log.debug(f"Demo Mode: Retrieved {len(positions)} mock positions for stealth trailing")
                    return positions
                log.debug("Demo Mode: No mock positions found")
                return {}
            
            # Live Mode: Get positions from trade manager
            elif self.trade_manager and hasattr(self.trade_manager, 'active_positions'):
                # Get live positions from unified trade manager
                live_positions = {}
                for symbol, position in self.trade_manager.active_positions.items():
                    live_positions[symbol] = {
                        'symbol': position.symbol,
                        'entry_price': position.entry_price,
                        'current_price': position.current_price,
                        'quantity': position.quantity,
                        'side': position.side.value if hasattr(position.side, 'value') else str(position.side),
                        'status': position.status.value if hasattr(position.status, 'value') else str(position.status),
                        'entry_time': position.entry_time,
                        'confidence': position.confidence,
                        'stop_loss': position.stop_loss,
                        'take_profit': position.take_profit,
                        'position_id': position.position_id,
                        'source': 'live'
                    }
                log.debug(f"Live Mode: Retrieved {len(live_positions)} live positions for stealth trailing")
                return live_positions
            
            log.debug("No positions found for stealth trailing")
            return {}
        except Exception as e:
            log.error(f"Error getting current positions: {e}")
            return {}
    
    def _update_performance_metrics(self, loop_start: float):
        """Update performance metrics"""
        loop_time = (time.time() - loop_start) * 1000  # Convert to milliseconds
        
        self.performance_metrics['main_loop_iterations'] += 1
        
        # Update average loop time
        iterations = self.performance_metrics['main_loop_iterations']
        current_avg = self.performance_metrics['avg_loop_time']
        self.performance_metrics['avg_loop_time'] = ((current_avg * (iterations - 1)) + loop_time) / iterations
    
    def _log_performance_report(self):
        """Log performance report"""
        if not self.performance_metrics['start_time']:
            return
        
        runtime = time.time() - self.performance_metrics['start_time']
        
        log.info("📊 Performance Report:")
        log.info(f"  Runtime: {runtime:.2f}s")
        log.info(f"  Main loop iterations: {self.performance_metrics['main_loop_iterations']}")
        log.info(f"  Average loop time: {self.performance_metrics['avg_loop_time']:.2f}ms")
        log.info(f"  Signals generated: {self.performance_metrics['signals_generated']}")
        log.info(f"  Positions updated: {self.performance_metrics['positions_updated']}")
        log.info(f"  Errors: {self.performance_metrics['errors']}")
        
        # Parallel processing metrics
        parallel_metrics = self.parallel_manager.get_metrics()
        log.info(f"  Parallel processing:")
        for key, value in parallel_metrics.items():
            log.info(f"    {key}: {value}")
        
        # Memory metrics
        memory_stats = self.memory_manager.get_memory_stats()
        log.info(f"  Memory usage:")
        for key, value in memory_stats.items():
            log.info(f"    {key}: {value}")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get comprehensive performance metrics"""
        return {
            'trading_system': self.performance_metrics,
            'parallel_processing': self.parallel_manager.get_metrics(),
            'memory': self.memory_manager.get_memory_stats(),
            'config': {
                'max_workers': self.config.max_workers,
                'batch_size': self.config.batch_size,
                'main_loop_interval': self.config.main_loop_interval
            }
        }

# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def get_prime_trading_system(config: TradingConfig = None) -> PrimeTradingSystem:
    """Get optimized Prime Trading System instance"""
    return PrimeTradingSystem(config)

# ============================================================================
# PERFORMANCE TESTING
# ============================================================================

async def test_performance():
    """Test performance improvements"""
    print("🚀 Testing Optimized Prime Trading System Performance...")
    
    # Create performance config
    config = PerformanceConfig(
        max_workers=5,
        batch_size=10,
        main_loop_interval=0.1
    )
    
    # Initialize system
    system = get_prime_trading_system(config)
    
    # Mock components
    components = {
        'data_manager': None,
        'signal_generator': None,
        'risk_manager': None,
        'trade_manager': None,
        'stealth_trailing': None,
        'alert_manager': None
    }
    
    # Initialize system
    await system.initialize(components)
    
    # Test parallel processing
    print("\n📊 Testing parallel processing...")
    start_time = time.time()
    
    # Simulate parallel tasks
    symbols = ["SPY", "QQQ", "TQQQ", "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META"]
    
    # Test parallel symbol processing
    results = await system.parallel_manager.process_symbols_parallel(
        symbols,
        lambda symbol: {"symbol": symbol, "processed": True}
    )
    
    parallel_time = (time.time() - start_time) * 1000
    print(f"Parallel processing time: {parallel_time:.2f}ms ({len(results)} symbols)")
    print(f"Average per symbol: {parallel_time/len(symbols):.2f}ms")
    
    # Get performance metrics
    metrics = system.get_performance_metrics()
    print(f"\n📈 Performance Metrics:")
    for category, data in metrics.items():
        print(f"  {category}:")
        for key, value in data.items():
            print(f"    {key}: {value}")
    
    # Shutdown system
    await system.stop()
    
    print("\n✅ Performance test completed!")

if __name__ == "__main__":
    asyncio.run(test_performance())
