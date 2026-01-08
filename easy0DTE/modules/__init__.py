"""
Easy 0DTE Strategy Modules
==========================

Modules for the Easy 0DTE Strategy - Integrated with Easy ORB Strategy.

Provides 0DTE options trading capabilities that work in conjunction with
the ORB Strategy signals for enhanced trading opportunities.

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

from .convex_eligibility_filter import ConvexEligibilityFilter, ConvexEligibilityResult
from .prime_0dte_strategy_manager import Prime0DTEStrategyManager, DTE0Signal
from .options_chain_manager import OptionsChainManager, OptionContract, DebitSpread
from .options_trading_executor import OptionsTradingExecutor
from .options_types import OptionsPosition
from .options_exit_manager import OptionsExitManager, ExitReason, ExitSignal
from .mock_options_executor import MockOptionsExecutor, MockOptionsPosition

# ETrade Options API (optional, only available when integrated)
try:
    from .etrade_options_api import ETradeOptionsAPI, ETradeOptionContract
    __all__ = [
        'ConvexEligibilityFilter',
        'ConvexEligibilityResult',
        'Prime0DTEStrategyManager',
        'DTE0Signal',
        'OptionsChainManager',
        'OptionContract',
        'DebitSpread',
        'OptionsTradingExecutor',
        'OptionsPosition',
        'MockOptionsExecutor',
        'MockOptionsPosition',
        'ETradeOptionsAPI',
        'ETradeOptionContract'
    ]
except ImportError:
    __all__ = [
        'ConvexEligibilityFilter',
        'ConvexEligibilityResult',
        'Prime0DTEStrategyManager',
        'DTE0Signal',
        'OptionsChainManager',
        'OptionContract',
        'DebitSpread',
        'OptionsTradingExecutor',
        'OptionsPosition',
        'MockOptionsExecutor',
        'MockOptionsPosition'
    ]

