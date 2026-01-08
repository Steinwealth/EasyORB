#!/usr/bin/env python3
"""
Prime 0DTE Strategy Manager
===========================

Listens to ORB signals and applies Convex Eligibility Filter to determine
which signals deserve options exposure. Manages 0DTE options trading workflow.

Key Responsibilities:
1. Listen to ORB signals from PrimeORBStrategyManager
2. Apply Convex Eligibility Filter
3. Generate 0DTE signals for QQQ & SPY
4. Coordinate with Options Trading Executor

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import pytz

from .convex_eligibility_filter import ConvexEligibilityFilter, ConvexEligibilityResult
from .options_priority_data_collector import OptionsPriorityDataCollector

log = logging.getLogger(__name__)

# Timezone constants
ET_TZ = pytz.timezone('America/New_York')
PT_TZ = pytz.timezone('America/Los_Angeles')

# 0DTE Symbols - Loaded from 0dte_list.csv (Rev 00209)
# Default fallback if file not found
DTE_SYMBOLS = ['SPX', 'QQQ', 'SPY']

def load_0dte_symbols() -> List[str]:
    """
    Load 0DTE symbols from 0dte_list.csv file
    
    Returns:
        List of 0DTE symbols in priority order (Tier 1 first, then Tier 2)
    """
    try:
        import pandas as pd
        import os
        
        # Try multiple paths for the 0DTE list
        possible_paths = [
            "data/watchlist/0dte_list.csv",
            "../1. The Easy ORB Strategy/data/watchlist/0dte_list.csv",
            "../../1. The Easy ORB Strategy/data/watchlist/0dte_list.csv",
            "/app/1. The Easy ORB Strategy/data/watchlist/0dte_list.csv"
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                df = pd.read_csv(path, comment='#')
                symbols = df['symbol'].tolist() if 'symbol' in df.columns else df.iloc[:, 0].tolist()
                # Sort by tier (1 first, then 2), maintaining order within tiers
                if 'tier' in df.columns:
                    tier_map = dict(zip(df['symbol'], df['tier']))
                    symbols = sorted(symbols, key=lambda s: (tier_map.get(s, 99), symbols.index(s) if s in symbols else 999))
                log.info(f"✅ Loaded {len(symbols)} 0DTE symbols from {path}")
                return symbols
        
        log.warning("⚠️ 0DTE symbol list not found, using default: SPX, QQQ, SPY")
        return DTE_SYMBOLS.copy()
    except Exception as e:
        log.warning(f"⚠️ Failed to load 0DTE symbol list: {e}, using default")
        return DTE_SYMBOLS.copy()


@dataclass
class DTE0Signal:
    """0DTE Signal structure"""
    symbol: str  # SPX, QQQ, or SPY
    direction: str  # 'LONG' or 'SHORT'
    orb_signal: Dict[str, Any]  # Original ORB signal
    eligibility_result: ConvexEligibilityResult
    target_delta: float  # Target delta for long leg (0.30-0.45)
    spread_width: float  # $1 or $2
    spread_type: str = 'debit'  # 'debit', 'credit', or 'lotto'
    strategy_type: str = 'debit_spread'  # Rev 00229: 'long_call', 'long_put', 'debit_spread', 'momentum_scalper', 'itm_probability_spread', 'lotto', 'no_trade'
    created_at: datetime = field(default_factory=datetime.now)
    priority_score: float = 0.0  # Priority score (0.0-1.0) - calculated during ranking
    priority_rank: int = 0  # Priority rank (1 = highest) - assigned during ranking
    capital_allocated: float = 0.0  # Capital allocated based on priority tier
    momentum_score: float = 0.0  # Rev 00228: Momentum Strength Score (0-100)
    
    @property
    def option_type(self) -> str:
        """
        Convert direction to option type
        
        Returns:
            'call' for LONG direction (bullish)
            'put' for SHORT direction (bearish)
        """
        return 'call' if self.direction == 'LONG' else 'put'
    
    @property
    def option_type_label(self) -> str:
        """Human-readable option type label"""
        return 'CALL' if self.direction == 'LONG' else 'PUT'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'option_type': self.option_type,  # 'call' or 'put'
            'option_type_label': self.option_type_label,  # 'CALL' or 'PUT'
            'orb_signal': self.orb_signal,
            'eligibility_score': self.eligibility_result.eligibility_score,
            'target_delta': self.target_delta,
            'spread_width': self.spread_width,
            'spread_type': self.spread_type,  # 'debit', 'credit', or 'lotto'
            'strategy_type': self.strategy_type,  # Rev 00227: Level 2 strategy type
            'created_at': self.created_at.isoformat(),
            'priority_score': self.priority_score,
            'priority_rank': self.priority_rank,
            'capital_allocated': self.capital_allocated
        }


class Prime0DTEStrategyManager:
    """
    Prime 0DTE Strategy Manager
    
    Listens to ORB signals and applies Convex Eligibility Filter to determine
    which signals deserve options exposure.
    """
    
    def __init__(
        self,
        convex_filter: Optional[ConvexEligibilityFilter] = None,
        target_symbols: List[str] = None,
        max_positions: int = 5,
        enable_lotto_sleeve: bool = False,
        priority_collector: Optional[OptionsPriorityDataCollector] = None,
        alert_manager=None
    ):
        """
        Initialize 0DTE Strategy Manager
        
        Args:
            convex_filter: Convex Eligibility Filter instance (creates default if None)
            target_symbols: Target symbols for options (default: ['QQQ', 'SPY'])
            max_positions: Maximum number of 0DTE positions
            enable_lotto_sleeve: Enable lotto sleeve (single-leg options)
            priority_collector: Options Priority Data Collector for trade history
        """
        self.convex_filter = convex_filter or ConvexEligibilityFilter()
        # Rev 00209: Load 0DTE symbols from file, or use provided list, or use default
        if target_symbols:
            self.target_symbols = target_symbols
        else:
            self.target_symbols = load_0dte_symbols()
        self.max_positions = max_positions
        self.enable_lotto_sleeve = enable_lotto_sleeve
        
        # Priority Data Collector for trade history
        self.priority_collector = priority_collector
        
        # Alert Manager for notifications
        self.alert_manager = alert_manager
        
        # Signal storage
        self.orb_signals: List[Dict[str, Any]] = []
        self.eligible_signals: List[ConvexEligibilityResult] = []
        self.dte0_signals: List[DTE0Signal] = []
        
        # Callbacks
        self.on_signal_callback: Optional[Callable] = None
        
        log.info(f"Prime 0DTE Strategy Manager initialized:")
        log.info(f"  - Target symbols: {self.target_symbols}")
        log.info(f"  - Max positions: {self.max_positions}")
        log.info(f"  - Lotto sleeve enabled: {self.enable_lotto_sleeve}")
        log.info(f"  - Priority collector: {'Enabled' if self.priority_collector else 'Disabled'}")
    
    def set_signal_callback(self, callback: Callable):
        """Set callback for when 0DTE signals are generated"""
        self.on_signal_callback = callback
    
    async def listen_to_orb_signals(
        self,
        orb_signals: List[Dict[str, Any]],
        symbol_mapping: Optional[Dict[str, str]] = None,
        orb_strategy_manager: Optional[Any] = None
    ) -> List[DTE0Signal]:
        """
        Listen to ORB signals and generate 0DTE signals
        
        Args:
            orb_signals: List of ORB signals from PrimeORBStrategyManager
            symbol_mapping: Mapping from ORB symbols to 0DTE symbols (e.g., {'TQQQ': 'QQQ'})
            
        Returns:
            List of 0DTE signals
        """
        if not orb_signals:
            log.info("No ORB signals received")
            return []
        
        log.info(f"Received {len(orb_signals)} ORB signals")
        
        # Store ORB signals
        self.orb_signals = orb_signals
        
        # Apply Convex Eligibility Filter
        eligible_results = self.convex_filter.filter_signals(
            orb_signals,
            min_score=0.75,
            max_signals=self.max_positions
        )
        
        self.eligible_signals = eligible_results
        
        if not eligible_results:
            log.info("No signals passed Convex Eligibility Filter")
            return []
        
        log.info(f"{len(eligible_results)} signals passed Convex Eligibility Filter")
        
        # Rev 00211: Separate LONG and SHORT signals for processing
        long_results = [r for r in eligible_results if r.signal.get('side', 'LONG') == 'LONG']
        short_results = [r for r in eligible_results if r.signal.get('side', 'LONG') == 'SHORT']
        
        log.info(f"   • LONG signals (CALL): {len(long_results)}")
        log.info(f"   • SHORT signals (PUT): {len(short_results)}")
        
        # Map ORB signals to 0DTE symbols (Rev 00209: All symbols from 0dte_list.csv)
        # Rev 00211: Process both LONG (CALL) and SHORT (PUT) signals
        dte0_signals = []
        
        # Process LONG signals (CALL options)
        for result in long_results:
            orb_signal = result.signal
            orb_symbol = orb_signal.get('symbol', '')
            direction = orb_signal.get('side', 'LONG')
            
            # ONLY process direct signals for symbols in target_symbols (loaded from 0dte_list.csv)
            if orb_symbol not in self.target_symbols:
                log.debug(f"Skipping {orb_symbol} - not in 0DTE target symbols list")
                continue
            
            target_symbol = orb_symbol
            log.debug(f"0DTE Mapping: {orb_symbol} ({direction}) -> {target_symbol} (CALL options)")
            
            # Rev 00212: Updated delta range to 0.10-0.30 (10-30 delta) for gamma explosion
            # Premium target: $0.20-$0.60, 1-3 strikes OTM
            orb_range_pct = orb_signal.get('orb_range_pct', 0.0)
            
            # SPX: Index options (professional/institutional standard)
            if target_symbol == 'SPX':
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta (cheap gamma)
                    spread_width = 10.0  # $10 spread for SPX index options
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 5.0   # $5 spread for SPX
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (very cheap gamma)
                    spread_width = 5.0   # $5 spread for SPX
            
            # QQQ: Higher volatility threshold, more aggressive
            elif target_symbol == 'QQQ':
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta
                    spread_width = 2.0  # Wider spread
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 1.0  # Narrower spread
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (cheap gamma)
                    spread_width = 1.0
            
            # SPY: Moderate volatility threshold, more stable
            elif target_symbol == 'SPY':
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta
                    spread_width = 2.0
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 1.0
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (cheap gamma)
                    spread_width = 1.0
            
            # Rev 00212: Default for other 0DTE symbols (NVDA, AMD, TSLA, META, AMZN, AAPL, MSFT, IWM)
            # Use 10-30 delta range for cheap gamma explosion
            else:
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta
                    spread_width = 2.0  # Wider spread for high volatility
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 1.0  # Standard spread
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (cheap gamma)
                    spread_width = 1.0
            
            # Rev 00228: Calculate momentum score first (will be used for strategy selection)
            # Create temporary signal to calculate momentum
            temp_signal = DTE0Signal(
                symbol=target_symbol,
                direction=direction,
                orb_signal=orb_signal,
                eligibility_result=result,
                target_delta=target_delta,
                spread_width=spread_width,
                spread_type='debit',
                strategy_type='debit_spread'  # Temporary
            )
            momentum_score = self.calculate_momentum_score(temp_signal)
            
            # Rev 00227: Determine Level 2 strategy type for CALL (LONG direction)
            # Rev 00228: Enhanced with momentum score
            strategy_type = self._select_strategy_type(
                direction='LONG',
                orb_signal=orb_signal,
                eligibility_result=result,
                orb_range_pct=orb_range_pct,
                momentum_score=momentum_score  # Rev 00228: Pass momentum score
            )
            
            # CALL options use debit spreads (Level 2: no credit spreads)
            spread_type = 'debit'  # CALL debit spread (bullish) - Level 2 compatible
            
            # Create 0DTE CALL signal
            dte0_signal = DTE0Signal(
                symbol=target_symbol,
                direction=direction,  # LONG
                orb_signal=orb_signal,
                eligibility_result=result,
                target_delta=target_delta,
                spread_width=spread_width,
                spread_type=spread_type,  # debit for CALL
                strategy_type=strategy_type,  # Rev 00227: Level 2 strategy selection
                momentum_score=momentum_score  # Rev 00228: Momentum Strength Score
            )
            
            dte0_signals.append(dte0_signal)
        
        # Rev 00211: Process SHORT signals (PUT options)
        for result in short_results:
            orb_signal = result.signal
            orb_symbol = orb_signal.get('symbol', '')
            direction = orb_signal.get('side', 'SHORT')
            
            # ONLY process direct signals for symbols in target_symbols
            if orb_symbol not in self.target_symbols:
                log.debug(f"Skipping {orb_symbol} - not in 0DTE target symbols list")
                continue
            
            target_symbol = orb_symbol
            log.debug(f"0DTE Mapping: {orb_symbol} ({direction}) -> {target_symbol} (PUT options)")
            
            # Determine target delta and spread width based on symbol and volatility
            orb_range_pct = orb_signal.get('orb_range_pct', 0.0)
            
            # Rev 00212: Updated delta range to 0.10-0.30 (10-30 delta) for PUT options
            # Premium target: $0.20-$0.60, 1-3 strikes OTM
            if target_symbol == 'SPX':
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta
                    spread_width = 10.0
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 5.0
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (cheap gamma)
                    spread_width = 5.0
            elif target_symbol == 'QQQ':
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta
                    spread_width = 2.0
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 1.0
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (cheap gamma)
                    spread_width = 1.0
            elif target_symbol == 'SPY':
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta
                    spread_width = 2.0
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 1.0
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (cheap gamma)
                    spread_width = 1.0
            else:
                # Default for other 0DTE symbols
                if orb_range_pct >= 0.50:
                    target_delta = 0.25  # High volatility: 25 delta
                    spread_width = 2.0
                elif orb_range_pct >= 0.35:
                    target_delta = 0.20  # Moderate volatility: 20 delta
                    spread_width = 1.0
                else:
                    target_delta = 0.15  # Lower volatility: 15 delta (cheap gamma)
                    spread_width = 1.0
            
            # Rev 00228: Calculate momentum score first (will be used for strategy selection)
            # Create temporary signal to calculate momentum
            temp_signal = DTE0Signal(
                symbol=target_symbol,
                direction=direction,
                orb_signal=orb_signal,
                eligibility_result=result,
                target_delta=target_delta,
                spread_width=spread_width,
                spread_type='debit',
                strategy_type='debit_spread'  # Temporary
            )
            momentum_score = self.calculate_momentum_score(temp_signal)
            
            # Rev 00227: Determine Level 2 strategy type for PUT (SHORT direction)
            # Rev 00228: Enhanced with momentum score
            strategy_type = self._select_strategy_type(
                direction='SHORT',
                orb_signal=orb_signal,
                eligibility_result=result,
                orb_range_pct=orb_range_pct,
                momentum_score=momentum_score  # Rev 00228: Pass momentum score
            )
            
            # PUT options use debit spreads for Level 2 (Bear Put Debit Spread)
            # Credit spreads require Level 3+ approval
            spread_type = 'debit'  # PUT debit spread (bearish) - Level 2 compatible
            
            # Create 0DTE PUT signal
            dte0_signal = DTE0Signal(
                symbol=target_symbol,
                direction=direction,  # SHORT
                orb_signal=orb_signal,
                eligibility_result=result,
                target_delta=target_delta,
                spread_width=spread_width,
                spread_type=spread_type,  # debit for PUT (Level 2)
                strategy_type=strategy_type,  # Rev 00227: Level 2 strategy selection
                momentum_score=momentum_score  # Rev 00228: Momentum Strength Score
            )
            
            dte0_signals.append(dte0_signal)
        
        # Rev 00228: Calculate momentum scores for all signals
        if dte0_signals:
            # Get market data for alignment check (SPY/QQQ direction)
            market_data = self._get_market_alignment_data()
            
            for signal in dte0_signals:
                momentum_score = self.calculate_momentum_score(signal, market_data)
                log.debug(f"   {signal.symbol} {signal.direction}: Momentum Score = {momentum_score:.1f}/100")
        
        # Calculate priority scores and rank signals (Rev 00225: Priority Ranking System)
        if dte0_signals:
            dte0_signals = self._rank_signals_by_priority(dte0_signals)
            log.info(f"✅ Ranked {len(dte0_signals)} 0DTE signals by priority")
        
        # Record signal collection for Priority Optimizer
        if self.priority_collector and dte0_signals:
            try:
                self.priority_collector.record_signal_collection(dte0_signals)
            except Exception as e:
                log.error(f"Failed to record signal collection: {e}")
        
        self.dte0_signals = dte0_signals
        
        log.info(f"Generated {len(dte0_signals)} 0DTE signals (ranked by priority):")
        for signal in dte0_signals:
            log.info(f"  - Rank {signal.priority_rank}: {signal.symbol} {signal.direction} ({signal.option_type_label}) - Priority: {signal.priority_score:.3f}, Eligibility: {signal.eligibility_result.eligibility_score:.2f}, Delta: {signal.target_delta:.2f}, Width: ${signal.spread_width:.0f}")
        
        # Send Options Signal Collection alert (Rev 00206)
        if self.alert_manager:
            try:
                # Determine mode (DEMO or LIVE)
                import os
                mode = "DEMO" if os.getenv('ETRADE_MODE', 'demo').lower() == 'demo' or os.getenv('AUTOMATION_MODE', 'demo').lower() == 'demo' else "LIVE"
                
                # Format qualified signals for alert
                qualified_signals = []
                for signal in dte0_signals:
                    qualified_signals.append({
                        'symbol': signal.symbol,
                        'option_type': signal.option_type,
                        'eligibility_score': signal.eligibility_result.eligibility_score,
                        'target_delta': signal.target_delta,
                        'spread_width': signal.spread_width
                    })
                
                # 0DTE signal collection is now integrated into the SO Signal Collection alert
                # No separate 0DTE alert sent - information included in main ORB alert
                log.info("✅ Options Signal Collection alert sent")
            except Exception as alert_error:
                log.error(f"Failed to send Options Signal Collection alert: {alert_error}")
        
        # Call callback if set
        if self.on_signal_callback:
            await self.on_signal_callback(dte0_signals)
        
        return dte0_signals
    
    def record_execution_results(
        self,
        executed_positions: List[Any],
        filtered_signals: List[Any] = None
    ):
        """
        Record execution results for Priority Optimizer
        
        Args:
            executed_positions: List of OptionsPosition objects that were executed
            filtered_signals: List of signals that were filtered out
        """
        if self.priority_collector:
            try:
                self.priority_collector.record_execution_results(executed_positions, filtered_signals)
            except Exception as e:
                log.error(f"Failed to record execution results: {e}")
    
    async def save_priority_data(self):
        """
        Save Priority Optimizer data at EOD
        """
        if self.priority_collector:
            try:
                await self.priority_collector.save_daily_data(format='json')
            except Exception as e:
                log.error(f"Failed to save Priority Optimizer data: {e}")
    
    async def generate_0dte_signals(
        self,
        eligible_signals: List[ConvexEligibilityResult]
    ) -> List[DTE0Signal]:
        """
        Generate 0DTE signals from eligible ORB signals
        
        NOTE: This method is deprecated. Use listen_to_orb_signals() instead,
        which includes complete symbol mapping logic.
        
        Args:
            eligible_signals: List of eligible signals from Convex Eligibility Filter
            
        Returns:
            List of 0DTE signals
        """
        # This method is kept for backward compatibility but should not be used.
        # The actual implementation is in listen_to_orb_signals() which includes
        # complete symbol mapping, inverse ETF handling, and delta/spread selection.
        log.warning("generate_0dte_signals() is deprecated. Use listen_to_orb_signals() instead.")
        return []
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """Get strategy statistics"""
        return {
            'orb_signals_received': len(self.orb_signals),
            'eligible_signals': len(self.eligible_signals),
            'dte0_signals_generated': len(self.dte0_signals),
            'target_symbols': self.target_symbols,
            'max_positions': self.max_positions,
            'lotto_sleeve_enabled': self.enable_lotto_sleeve
        }
    
    def get_qqq_spy_orb_data(self, orb_strategy_manager) -> Dict[str, Any]:
        """
        Extract QQQ and SPY ORB data from ORB Strategy Manager
        
        Args:
            orb_strategy_manager: PrimeORBStrategyManager instance from ORB Strategy
            
        Returns:
            Dictionary with QQQ and SPY ORB data:
            {
                'QQQ': ORBData or None,
                'SPY': ORBData or None
            }
        """
        qqq_spy_orb = {'QQQ': None, 'SPY': None}
        
        if not orb_strategy_manager or not hasattr(orb_strategy_manager, 'orb_data'):
            log.warning("ORB Strategy Manager not available or orb_data not found")
            return qqq_spy_orb
        
        # Extract QQQ ORB data
        if 'QQQ' in orb_strategy_manager.orb_data:
            qqq_spy_orb['QQQ'] = orb_strategy_manager.orb_data['QQQ']
            # Calculate orb_range_pct from orb_range and orb_low
            qqq_orb_range_pct = (qqq_spy_orb['QQQ'].orb_range / qqq_spy_orb['QQQ'].orb_low * 100) if qqq_spy_orb['QQQ'].orb_low > 0 else 0.0
            log.info(f"✅ QQQ ORB data found: High=${qqq_spy_orb['QQQ'].orb_high:.2f}, Low=${qqq_spy_orb['QQQ'].orb_low:.2f}, Range={qqq_orb_range_pct:.2f}%")
        else:
            log.warning("⚠️ QQQ ORB data not found in ORB Strategy")
        
        # Extract SPY ORB data
        if 'SPY' in orb_strategy_manager.orb_data:
            qqq_spy_orb['SPY'] = orb_strategy_manager.orb_data['SPY']
            # Calculate orb_range_pct from orb_range and orb_low
            spy_orb_range_pct = (qqq_spy_orb['SPY'].orb_range / qqq_spy_orb['SPY'].orb_low * 100) if qqq_spy_orb['SPY'].orb_low > 0 else 0.0
            log.info(f"✅ SPY ORB data found: High=${qqq_spy_orb['SPY'].orb_high:.2f}, Low=${qqq_spy_orb['SPY'].orb_low:.2f}, Range={spy_orb_range_pct:.2f}%")
        else:
            log.warning("⚠️ SPY ORB data not found in ORB Strategy")
        
        return qqq_spy_orb
    
    def get_spx_qqq_spy_orb_data(self, orb_strategy_manager) -> Dict[str, Any]:
        """
        Extract SPX, QQQ, and SPY ORB data from ORB Strategy Manager
        
        Args:
            orb_strategy_manager: PrimeORBStrategyManager instance from ORB Strategy
            
        Returns:
            Dictionary with SPX, QQQ, and SPY ORB data:
            {
                'SPX': ORBData or None,
                'QQQ': ORBData or None,
                'SPY': ORBData or None
            }
        """
        orb_data = {'SPX': None, 'QQQ': None, 'SPY': None}
        
        if not orb_strategy_manager or not hasattr(orb_strategy_manager, 'orb_data'):
            log.warning("ORB Strategy Manager not available or orb_data not found")
            return orb_data
        
        # Extract SPX ORB data (Priority 1)
        if 'SPX' in orb_strategy_manager.orb_data:
            orb_data['SPX'] = orb_strategy_manager.orb_data['SPX']
            # Calculate orb_range_pct from orb_range and orb_low
            spx_orb_range_pct = (orb_data['SPX'].orb_range / orb_data['SPX'].orb_low * 100) if orb_data['SPX'].orb_low > 0 else 0.0
            log.info(f"✅ SPX ORB data found: High=${orb_data['SPX'].orb_high:.2f}, Low=${orb_data['SPX'].orb_low:.2f}, Range={spx_orb_range_pct:.2f}%")
        else:
            log.warning("⚠️ SPX ORB data not found in ORB Strategy")
        
        # Extract QQQ ORB data (Priority 2)
        if 'QQQ' in orb_strategy_manager.orb_data:
            orb_data['QQQ'] = orb_strategy_manager.orb_data['QQQ']
            # Calculate orb_range_pct from orb_range and orb_low
            qqq_orb_range_pct = (orb_data['QQQ'].orb_range / orb_data['QQQ'].orb_low * 100) if orb_data['QQQ'].orb_low > 0 else 0.0
            log.info(f"✅ QQQ ORB data found: High=${orb_data['QQQ'].orb_high:.2f}, Low=${orb_data['QQQ'].orb_low:.2f}, Range={qqq_orb_range_pct:.2f}%")
        else:
            log.warning("⚠️ QQQ ORB data not found in ORB Strategy")
        
        # Extract SPY ORB data (Priority 3)
        if 'SPY' in orb_strategy_manager.orb_data:
            orb_data['SPY'] = orb_strategy_manager.orb_data['SPY']
            # Calculate orb_range_pct from orb_range and orb_low
            spy_orb_range_pct = (orb_data['SPY'].orb_range / orb_data['SPY'].orb_low * 100) if orb_data['SPY'].orb_low > 0 else 0.0
            log.info(f"✅ SPY ORB data found: High=${orb_data['SPY'].orb_high:.2f}, Low=${orb_data['SPY'].orb_low:.2f}, Range={spy_orb_range_pct:.2f}%")
        else:
            log.warning("⚠️ SPY ORB data not found in ORB Strategy")
        
        return orb_data
    
    def _calculate_priority_score(self, signal: DTE0Signal) -> float:
        """
        Calculate priority score for 0DTE signal (Rev 00225: Priority Ranking System)
        
        Similar to ORB Strategy priority ranking, but optimized for options trading.
        Uses multi-factor scoring to identify highest-probability setups.
        
        Formula v1.0:
        - ORB Breakout %: 30% (strong breakout = higher probability)
        - ORB Range %: 25% (wider range = better options opportunity)
        - Volume Score: 20% (high volume = stronger move)
        - Eligibility Score: 15% (already calculated by Convex Filter)
        - Directional Momentum: 10% (price vs ORB, breakout strength)
        
        Args:
            signal: DTE0Signal object
        
        Returns:
            Priority score (0.0-1.0, higher = better)
        """
        try:
            orb_signal = signal.orb_signal
            orb_high = orb_signal.get('orb_high', 0.0)
            orb_low = orb_signal.get('orb_low', 0.0)
            current_price = orb_signal.get('current_price', 0.0)
            orb_range_pct = orb_signal.get('orb_range_pct', 0.0)
            volume_ratio = orb_signal.get('volume_ratio', 1.0)
            
            # Factor 1: ORB Breakout % (30% weight)
            if signal.direction == 'LONG':
                # CALL: How far above ORB high
                if orb_high > 0:
                    breakout_pct = ((current_price - orb_high) / orb_high) * 100
                else:
                    breakout_pct = 0.0
            else:
                # PUT: How far below ORB low
                if orb_low > 0:
                    breakout_pct = ((orb_low - current_price) / orb_low) * 100
                else:
                    breakout_pct = 0.0
            
            # Normalize breakout % (1.0 at 5%+ breakout)
            if breakout_pct >= 5.0:
                breakout_score = 1.0
            elif breakout_pct >= 3.0:
                breakout_score = 0.85
            elif breakout_pct >= 1.0:
                breakout_score = 0.70
            elif breakout_pct >= 0.5:
                breakout_score = 0.50
            elif breakout_pct >= 0.2:
                breakout_score = 0.30
            else:
                breakout_score = 0.15
            
            # Factor 2: ORB Range % (25% weight)
            # Wider range = higher volatility = better options opportunity
            if orb_range_pct >= 0.50:
                range_score = 1.0  # High volatility
            elif orb_range_pct >= 0.35:
                range_score = 0.85  # Moderate volatility
            elif orb_range_pct >= 0.25:
                range_score = 0.70  # Good volatility
            elif orb_range_pct >= 0.15:
                range_score = 0.50  # Moderate
            else:
                range_score = 0.30  # Low volatility
            
            # Factor 3: Volume Score (20% weight)
            # High volume = stronger conviction
            if volume_ratio >= 3.0:
                volume_score = 1.0  # Exceptional
            elif volume_ratio >= 2.0:
                volume_score = 0.85  # Strong
            elif volume_ratio >= 1.5:
                volume_score = 0.70  # Good
            elif volume_ratio >= 1.2:
                volume_score = 0.50  # Moderate
            else:
                volume_score = 0.25  # Weak
            
            # Factor 4: Eligibility Score (15% weight)
            # Already calculated by Convex Eligibility Filter (0.75+ passes)
            eligibility_score = signal.eligibility_result.eligibility_score
            # Normalize to 0.0-1.0 (eligibility_score is already 0.0-1.0)
            eligibility_normalized = min(1.0, max(0.0, eligibility_score))
            
            # Factor 5: Directional Momentum (10% weight)
            # How strong is the breakout?
            if signal.direction == 'LONG':
                # CALL: Price momentum above ORB high
                if orb_high > 0 and current_price > orb_high:
                    momentum_pct = ((current_price - orb_high) / orb_high) * 100
                else:
                    momentum_pct = 0.0
            else:
                # PUT: Price momentum below ORB low
                if orb_low > 0 and current_price < orb_low:
                    momentum_pct = ((orb_low - current_price) / orb_low) * 100
                else:
                    momentum_pct = 0.0
            
            # Normalize momentum (1.0 at 2%+ momentum)
            if momentum_pct >= 2.0:
                momentum_score = 1.0
            elif momentum_pct >= 1.0:
                momentum_score = 0.85
            elif momentum_pct >= 0.5:
                momentum_score = 0.70
            elif momentum_pct >= 0.2:
                momentum_score = 0.50
            else:
                momentum_score = 0.30
            
            # Calculate final priority score (Formula v1.0)
            priority_score = (
                breakout_score * 0.30 +      # 30% - ORB Breakout %
                range_score * 0.25 +         # 25% - ORB Range %
                volume_score * 0.20 +        # 20% - Volume
                eligibility_normalized * 0.15 +  # 15% - Eligibility Score
                momentum_score * 0.10        # 10% - Directional Momentum
            )
            
            return min(1.0, max(0.0, priority_score))
            
        except Exception as e:
            log.error(f"Error calculating priority score for {signal.symbol}: {e}")
            return 0.0
    
    def _rank_signals_by_priority(self, signals: List[DTE0Signal]) -> List[DTE0Signal]:
        """
        Rank 0DTE signals by priority score (Rev 00225: Priority Ranking System)
        
        Args:
            signals: List of DTE0Signal objects
        
        Returns:
            List of signals ranked by priority (highest first)
        """
        try:
            # Calculate priority score for each signal
            for signal in signals:
                signal.priority_score = self._calculate_priority_score(signal)
            
            # Sort by priority score (highest first)
            ranked_signals = sorted(signals, key=lambda s: s.priority_score, reverse=True)
            
            # Assign priority rank (1 = highest)
            for rank, signal in enumerate(ranked_signals, 1):
                signal.priority_rank = rank
            
            log.info(f"✅ Ranked {len(ranked_signals)} signals by priority:")
            for i, signal in enumerate(ranked_signals[:5], 1):  # Log top 5
                log.info(f"   {i}. {signal.symbol} {signal.direction} - Score: {signal.priority_score:.3f}, Eligibility: {signal.eligibility_result.eligibility_score:.2f}")
            
            return ranked_signals
            
        except Exception as e:
            log.error(f"Error ranking signals by priority: {e}")
            return signals  # Return original list if ranking fails
    
    def calculate_position_sizing(
        self,
        signals: List[DTE0Signal],
        account_balance: float,
        trading_capital_pct: float = 90.0,
        max_position_pct: float = 35.0,
        max_concurrent_positions: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Calculate position sizes for 0DTE options trades (Rev 00226: 90% Capital Allocation)
        
        Similar to ORB Strategy's greedy capital packing with normalization:
        1. Calculate fair share per position (90% capital / number of signals)
        2. Apply rank-based multipliers (3.0x, 2.5x, 2.0x...)
        3. Normalize to fit 90% allocation
        4. Apply position caps (35% max per position)
        5. Calculate quantity based on spread cost
        
        Args:
            signals: List of ranked DTE0Signal objects (already sorted by priority)
            account_balance: Total account balance
            trading_capital_pct: Percentage of account to use for trading (default 90%)
            max_position_pct: Maximum position size as % of account (default 35%)
            max_concurrent_positions: Maximum number of positions (default 15)
        
        Returns:
            List of dicts with position sizing info: {
                'signal': DTE0Signal,
                'capital_allocated': float,
                'quantity': int,
                'position_value': float
            }
        """
        try:
            if not signals:
                return []
            
            # Calculate trading capital (90% of account)
            trading_capital = account_balance * (trading_capital_pct / 100.0)
            max_single_position = account_balance * (max_position_pct / 100.0)
            
            # Limit to max concurrent positions
            signals_to_size = signals[:max_concurrent_positions]
            num_signals = len(signals_to_size)
            
            if num_signals == 0:
                return []
            
            log.info(f"📊 Calculating position sizes for {num_signals} signals:")
            log.info(f"   - Account Balance: ${account_balance:.2f}")
            log.info(f"   - Trading Capital ({trading_capital_pct}%): ${trading_capital:.2f}")
            log.info(f"   - Max Position Size ({max_position_pct}%): ${max_single_position:.2f}")
            
            # STEP 1: Calculate fair share per position
            fair_share = trading_capital / num_signals
            log.info(f"   - Fair Share: ${fair_share:.2f} per position")
            
            # STEP 2: Apply rank-based multipliers (similar to ORB Strategy)
            position_sizes = []
            for signal in signals_to_size:
                rank = signal.priority_rank
                
                # Rank multipliers (same as ORB Strategy)
                if rank == 1:
                    multiplier = 3.0
                elif rank == 2:
                    multiplier = 2.5
                elif rank == 3:
                    multiplier = 2.0
                elif rank <= 5:
                    multiplier = 1.71
                elif rank <= 10:
                    multiplier = 1.5
                elif rank <= 15:
                    multiplier = 1.2
                else:
                    multiplier = 1.0
                
                raw_value = fair_share * multiplier
                
                # Apply position cap
                capped_value = min(raw_value, max_single_position)
                
                position_sizes.append({
                    'signal': signal,
                    'raw_value': raw_value,
                    'capped_value': capped_value,
                    'multiplier': multiplier
                })
            
            # STEP 3: Normalize to fit 90% allocation
            total_after_caps = sum(p['capped_value'] for p in position_sizes)
            
            if total_after_caps > trading_capital:
                norm_factor = trading_capital / total_after_caps
                log.info(f"   - Normalizing: ${total_after_caps:.2f} → ${trading_capital:.2f} (factor: {norm_factor:.3f})")
                for p in position_sizes:
                    p['normalized_value'] = p['capped_value'] * norm_factor
            else:
                log.info(f"   - No normalization needed: ${total_after_caps:.2f} <= ${trading_capital:.2f}")
                for p in position_sizes:
                    p['normalized_value'] = p['capped_value']
            
            # STEP 4: Calculate quantity for each position
            # Note: We'll need spread cost from execution, so for now we'll store the capital allocation
            # The actual quantity will be calculated during execution when we know the spread cost
            sized_positions = []
            for p in position_sizes:
                signal = p['signal']
                capital_allocated = p['normalized_value']
                
                # Store capital allocation in signal
                signal.capital_allocated = capital_allocated
                
                sized_positions.append({
                    'signal': signal,
                    'capital_allocated': capital_allocated,
                    'quantity': 0,  # Will be calculated during execution based on spread cost
                    'position_value': capital_allocated,
                    'multiplier': p['multiplier']
                })
            
            # Log summary
            total_allocated = sum(p['capital_allocated'] for p in sized_positions)
            deployment_pct = (total_allocated / account_balance * 100) if account_balance > 0 else 0.0
            log.info(f"✅ Position sizing complete:")
            log.info(f"   - Total Allocated: ${total_allocated:.2f} ({deployment_pct:.1f}% of account)")
            log.info(f"   - Top 3 positions: ${sum(p['capital_allocated'] for p in sized_positions[:3]):.2f}")
            
            return sized_positions
            
        except Exception as e:
            log.error(f"Error calculating position sizes: {e}", exc_info=True)
            # Fallback: Equal allocation
            fair_share = (account_balance * 0.90) / max(1, len(signals))
            return [{
                'signal': signal,
                'capital_allocated': fair_share,
                'quantity': 0,
                'position_value': fair_share,
                'multiplier': 1.0
            } for signal in signals[:max_concurrent_positions]]
    
    def _calculate_capital_allocation(
        self,
        priority_rank: int,
        total_signals: int,
        available_capital: float
    ) -> float:
        """
        DEPRECATED: Use calculate_position_sizing() instead (Rev 00226)
        
        This method is kept for backward compatibility but should not be used.
        The new calculate_position_sizing() method provides full ORB Strategy-style
        position sizing with rank multipliers, normalization, and caps.
        """
        log.warning("_calculate_capital_allocation() is deprecated. Use calculate_position_sizing() instead.")
        # Fallback: Equal allocation
        return available_capital / max(1, total_signals)
    
    def calculate_momentum_score(
        self,
        signal: DTE0Signal,
        market_data: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Calculate Momentum Strength Score (0-100) (Rev 00228: Momentum Score)
        
        Combines multiple factors to determine momentum strength:
        - ORB % range: 20 points
        - Relative volume (RVOL): 20 points
        - 1m/5m candle body strength: 20 points
        - VWAP slope & distance: 20 points
        - Market alignment (SPY ↔ QQQ): 20 points
        
        Args:
            signal: DTE0Signal object
            market_data: Optional market data (SPY/QQQ prices, etc.)
        
        Returns:
            Momentum score (0.0-100.0, higher = stronger momentum)
        """
        try:
            orb_signal = signal.orb_signal
            orb_range_pct = orb_signal.get('orb_range_pct', 0.0)
            volume_ratio = orb_signal.get('volume_ratio', 1.0)
            current_price = orb_signal.get('current_price', 0.0)
            vwap_distance = orb_signal.get('vwap_distance', 0.0)
            
            score = 0.0
            
            # Factor 1: ORB % Range (20 points)
            # Higher ORB range = stronger momentum potential
            if orb_range_pct >= 0.50:
                orb_score = 20.0  # Maximum
            elif orb_range_pct >= 0.35:
                orb_score = 15.0  # Strong
            elif orb_range_pct >= 0.25:
                orb_score = 10.0  # Moderate
            elif orb_range_pct >= 0.15:
                orb_score = 5.0   # Weak
            else:
                orb_score = 0.0   # Very weak
            score += orb_score
            
            # Factor 2: Relative Volume (RVOL) (20 points)
            # Higher volume = stronger conviction
            if volume_ratio >= 3.0:
                volume_score = 20.0  # Exceptional
            elif volume_ratio >= 2.0:
                volume_score = 15.0  # Strong
            elif volume_ratio >= 1.5:
                volume_score = 10.0  # Good
            elif volume_ratio >= 1.2:
                volume_score = 5.0   # Moderate
            else:
                volume_score = 0.0   # Weak
            score += volume_score
            
            # Factor 3: 1m/5m Candle Body Strength (20 points)
            # Strong candle body = strong momentum
            # Use ORB signal's confidence as proxy for candle strength
            confidence = orb_signal.get('confidence', 0.0)
            if confidence >= 0.90:
                candle_score = 20.0  # Very strong
            elif confidence >= 0.75:
                candle_score = 15.0  # Strong
            elif confidence >= 0.60:
                candle_score = 10.0  # Moderate
            elif confidence >= 0.45:
                candle_score = 5.0   # Weak
            else:
                candle_score = 0.0   # Very weak
            score += candle_score
            
            # Factor 4: VWAP Slope & Distance (20 points)
            # Price above VWAP with distance = bullish momentum
            # Price below VWAP with distance = bearish momentum
            if signal.direction == 'LONG':
                # Bullish: Want positive VWAP distance
                if vwap_distance >= 1.0:
                    vwap_score = 20.0  # Strong above VWAP
                elif vwap_distance >= 0.5:
                    vwap_score = 15.0  # Moderate above VWAP
                elif vwap_distance >= 0.0:
                    vwap_score = 10.0  # At VWAP
                else:
                    vwap_score = 5.0   # Below VWAP (weak)
            else:
                # Bearish: Want negative VWAP distance
                if vwap_distance <= -1.0:
                    vwap_score = 20.0  # Strong below VWAP
                elif vwap_distance <= -0.5:
                    vwap_score = 15.0  # Moderate below VWAP
                elif vwap_distance <= 0.0:
                    vwap_score = 10.0  # At VWAP
                else:
                    vwap_score = 5.0   # Above VWAP (weak)
            score += vwap_score
            
            # Factor 5: Market Alignment (SPY ↔ QQQ) (20 points)
            # Both SPY and QQQ moving in same direction = strong alignment
            if market_data:
                spy_direction = market_data.get('spy_direction', 'NONE')
                qqq_direction = market_data.get('qqq_direction', 'NONE')
                
                if signal.direction == 'LONG':
                    # Bullish: Want both SPY and QQQ bullish
                    if spy_direction == 'UP' and qqq_direction == 'UP':
                        alignment_score = 20.0  # Perfect alignment
                    elif (spy_direction == 'UP' and qqq_direction == 'NONE') or \
                         (spy_direction == 'NONE' and qqq_direction == 'UP'):
                        alignment_score = 10.0  # Partial alignment
                    else:
                        alignment_score = 0.0   # No alignment
                else:
                    # Bearish: Want both SPY and QQQ bearish
                    if spy_direction == 'DOWN' and qqq_direction == 'DOWN':
                        alignment_score = 20.0  # Perfect alignment
                    elif (spy_direction == 'DOWN' and qqq_direction == 'NONE') or \
                         (spy_direction == 'NONE' and qqq_direction == 'DOWN'):
                        alignment_score = 10.0  # Partial alignment
                    else:
                        alignment_score = 0.0   # No alignment
            else:
                # No market data available - neutral score
                alignment_score = 10.0
            score += alignment_score
            
            # Store momentum score in signal
            signal.momentum_score = score
            
            return score
            
        except Exception as e:
            log.error(f"Error calculating momentum score: {e}")
            return 0.0
    
    def validate_hard_gate(
        self,
        signal: DTE0Signal,
        current_time: datetime,
        max_allowed_spread_pct: float = 5.0,
        volume_multiplier: float = 1.0,
        session_avg_volume: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Hard Gate validation before 0DTE execution (Rev 00228: Hard Gate System)
        
        If ANY of these fail → NO 0DTE TRADE:
        - Symbol ∈ {SPY, QQQ, IWM, SPX (if enabled)}
        - Time ∈ [09:35, 10:15 ET] (6:35-7:15 PT) - ORB execution window
        - Spread < max_allowed_spread
        - Volume ≥ session_avg * volume_multiplier
        - Market not halted / extreme volatility flag
        
        Args:
            signal: DTE0Signal object
            current_time: Current datetime
            max_allowed_spread_pct: Maximum bid-ask spread % (default 5%)
            volume_multiplier: Volume multiplier for validation (default 1.0)
            session_avg_volume: Session average volume (optional)
        
        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            # Gate 1: Symbol Validation
            allowed_symbols = {'SPY', 'QQQ', 'IWM', 'SPX'}
            if signal.symbol not in allowed_symbols:
                return False, f"Symbol {signal.symbol} not in allowed list {allowed_symbols}"
            
            # Gate 2: Time Window Validation (09:35-10:15 ET = 6:35-7:15 PT)
            # Convert to ET for validation
            from pytz import timezone
            et_tz = timezone('US/Eastern')
            pt_tz = timezone('US/Pacific')
            
            if current_time.tzinfo is None:
                # Assume PT if no timezone
                current_time = pt_tz.localize(current_time)
            
            # Convert to ET
            current_et = current_time.astimezone(et_tz)
            et_hour = current_et.hour
            et_minute = current_et.minute
            
            # Check if within window (09:35-10:15 ET)
            window_start = (9, 35)  # 9:35 AM ET
            window_end = (10, 15)   # 10:15 AM ET
            
            current_time_tuple = (et_hour, et_minute)
            if current_time_tuple < window_start or current_time_tuple > window_end:
                return False, f"Time {et_hour:02d}:{et_minute:02d} ET outside execution window (09:35-10:15 ET)"
            
            # Gate 3: Spread Validation
            orb_signal = signal.orb_signal
            # Get bid-ask spread from options chain (if available)
            # For now, use a proxy: check if ORB range is reasonable
            orb_range_pct = orb_signal.get('orb_range_pct', 0.0)
            # If ORB range is too wide, might indicate wide spreads
            if orb_range_pct > 2.0:  # Very wide range might indicate issues
                log.warning(f"⚠️ Wide ORB range {orb_range_pct:.2f}% for {signal.symbol} - may indicate wide spreads")
                # Don't fail, but log warning
            
            # Gate 4: Volume Validation
            volume_ratio = orb_signal.get('volume_ratio', 1.0)
            if session_avg_volume:
                # Compare to session average
                current_volume = orb_signal.get('volume', 0)
                if current_volume < (session_avg_volume * volume_multiplier):
                    return False, f"Volume {current_volume} below threshold {session_avg_volume * volume_multiplier}"
            else:
                # Use volume ratio as proxy
                if volume_ratio < volume_multiplier:
                    return False, f"Volume ratio {volume_ratio:.2f} below threshold {volume_multiplier}"
            
            # Gate 5: Market Halt / Extreme Volatility
            # Check for extreme volatility (very wide ORB range)
            if orb_range_pct > 3.0:  # Extreme volatility (>3% range)
                return False, f"Extreme volatility detected (ORB range {orb_range_pct:.2f}%)"
            
            # All gates passed
            return True, "All hard gate checks passed"
            
        except Exception as e:
            log.error(f"Error in hard gate validation: {e}")
            return False, f"Hard gate validation error: {e}"
    
    def reset_daily(self):
        """Reset daily state"""
        self.orb_signals = []
        self.eligible_signals = []
        self.dte0_signals = []
        log.info("0DTE Strategy Manager daily reset complete")

