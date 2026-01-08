# modules/__init__.py
"""
Easy ORB Strategy Modules Package
Provides all core modules for the Easy ORB Strategy trading system
Last Updated: January 6, 2026 (Rev 00231)
"""

# Core modules that actually exist
from .config_loader import ConfigLoader, load_configuration, get_config_value

# Prime system modules
from .prime_data_manager import get_prime_data_manager, PrimeDataManager
from .prime_market_manager import get_prime_market_manager, PrimeMarketManager
from .prime_news_manager import get_prime_news_manager, PrimeNewsManager
from .prime_unified_trade_manager import get_prime_unified_trade_manager, PrimeUnifiedTradeManager
from .prime_models import (
    PrimeSignal, PrimePosition, PrimeTrade, PrimeStopOrder,
    StrategyMode, SignalQuality, SignalType, SignalSide, TradeStatus,
    StopType, TrailingMode, MarketRegime, ConfidenceTier
)

# ORB Strategy Manager - PRIMARY STRATEGY (Rev 00151)
from .prime_orb_strategy_manager import (
    get_prime_orb_strategy_manager,
    PrimeORBStrategyManager,
    SignalType as ORBSignalType,
    ORBData,
    ORBStrategyResult
)

# ARCHIVED (Not currently used, kept for reference):
# - prime_multi_strategy_manager.py
# - production_signal_generator.py

# OAuth keep-alive system handled by Cloud Scheduler (see ETradeOAuth/login/keepalive_oauth.py)

# Note: Live trading integration consolidated into prime_trading_manager

__all__ = [
    # Configuration
    'ConfigLoader', 'load_configuration', 'get_config_value',
    
    # Prime system modules
    'get_prime_data_manager', 'PrimeDataManager',
    'get_prime_market_manager', 'PrimeMarketManager',
    'get_prime_news_manager', 'PrimeNewsManager',
    'get_prime_unified_trade_manager', 'PrimeUnifiedTradeManager',
    
    # Prime models
    'PrimeSignal', 'PrimePosition', 'PrimeTrade', 'PrimeStopOrder',
    'StrategyMode', 'SignalQuality', 'SignalType', 'SignalSide', 'TradeStatus',
    'StopType', 'TrailingMode', 'MarketRegime', 'ConfidenceTier',
    
    # ORB Strategy Manager - PRIMARY STRATEGY
    'get_prime_orb_strategy_manager', 'PrimeORBStrategyManager',
    'ORBSignalType', 'ORBData', 'ORBStrategyResult',
]

# Version information
__version__ = "2.31.0"
__author__ = "Easy ORB Strategy Development Team"
__description__ = "Easy ORB Strategy Trading System Modules"
__last_updated__ = "2026-01-06"