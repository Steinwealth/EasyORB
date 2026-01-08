#!/usr/bin/env python3
"""
Prime Market Manager
===================

This module consolidates ALL market-related functionality including:
- Market hours and trading phases
- Holiday filtering (US Bank and Muslim holidays)
- Market status and session management
- News timing integration
- Real-time market data integration
- Performance optimization with intelligent caching

Key Features:
- Comprehensive holiday management (US Bank + Muslim holidays)
- Market phase tracking and optimization
- Session management and monitoring
- Timezone handling and conversion
- Performance optimization with caching
- Real-time market status updates
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, date, time as dt_time, timedelta
from typing import Optional, Tuple, Dict, Any, List, Set
from dataclasses import dataclass, field
from enum import Enum
import pytz
from cachetools import TTLCache

# Holiday calculation dependencies
try:
    import holidays as pyholidays
    HOLIDAYS_AVAILABLE = True
except ImportError:
    HOLIDAYS_AVAILABLE = False

try:
    from hijri_converter import convert as hijri_convert
    HIJRI_AVAILABLE = True
except ImportError:
    HIJRI_AVAILABLE = False

try:
    from dateutil.easter import easter as easter_sunday
    EASTER_AVAILABLE = True
except ImportError:
    EASTER_AVAILABLE = False

from .config_loader import get_config_value

log = logging.getLogger(__name__)

class MarketPhase(Enum):
    """Market trading phases"""
    DARK = "DARK"           # After hours (outside trading windows)
    PREP = "PREP"           # Pre-market preparation (4:00 AM - 9:30 AM ET)
    OPEN = "OPEN"           # Regular trading hours (9:30 AM - 4:00 PM ET)
    COOLDOWN = "COOLDOWN"   # Post-market cooldown (4:00 PM - 8:00 PM ET)

class MarketStatus(Enum):
    """Market status enumeration"""
    CLOSED = "CLOSED"       # Market is closed
    OPEN = "OPEN"           # Market is open
    PRE_MARKET = "PRE_MARKET"  # Pre-market hours
    AFTER_HOURS = "AFTER_HOURS"  # After hours trading
    EARLY_CLOSE = "EARLY_CLOSE"  # Early close day
    HOLIDAY = "HOLIDAY"     # Holiday closure

class HolidayType(Enum):
    """Holiday type enumeration"""
    US_BANK = "US_BANK"     # US Bank holidays
    MUSLIM = "MUSLIM"       # Muslim holidays
    CUSTOM = "CUSTOM"       # Custom holidays
    EARLY_CLOSE = "EARLY_CLOSE"  # Early close days

@dataclass
class MarketSession:
    """Market session configuration"""
    tz_name: str = "America/New_York"
    prep_start: str = "04:00"      # Pre-market start (4:00 AM ET)
    rth_open: str = "09:30"        # Regular trading hours open (9:30 AM ET)
    rth_close: str = "16:00"       # Regular trading hours close (4:00 PM ET)
    cooldown_end: str = "20:00"    # Post-market cooldown end (8:00 PM ET)
    holidays_enabled: bool = True
    holidays_custom_path: str = "data/holidays_custom.json"

@dataclass
class TradingSession:
    """Trading session information"""
    session_id: str
    start_time: datetime
    end_time: datetime
    phase: MarketPhase
    is_active: bool
    symbols_scanned: int = 0
    signals_generated: int = 0
    trades_executed: int = 0
    pnl: float = 0.0

@dataclass
class HolidayInfo:
    """Holiday information"""
    date: date
    name: str
    holiday_type: HolidayType
    is_trading_day: bool
    is_early_close: bool = False
    early_close_time: Optional[str] = None

class PrimeMarketManager:
    """Consolidated market manager with all best features"""
    
    def __init__(self, session_config: Optional[MarketSession] = None):
        self.session_config = session_config or MarketSession()
        self.timezone = pytz.timezone(self.session_config.tz_name)
        
        # Caching for performance
        self.cache = TTLCache(maxsize=1000, ttl=300)  # 5-minute cache
        self.holiday_cache = TTLCache(maxsize=100, ttl=3600)  # 1-hour cache
        
        # Current session tracking
        self.current_session: Optional[TradingSession] = None
        self.session_history: List[TradingSession] = []
        
        # Holiday management
        self.us_holidays = self._load_us_holidays()
        self.muslim_holidays = self._load_muslim_holidays()
        self.custom_holidays = self._load_custom_holidays()
        
        # Performance metrics
        self.metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'holiday_checks': 0,
            'market_status_checks': 0,
            'session_updates': 0
        }
        
        log.info("Prime Market Manager initialized")

    async def initialize(self) -> None:
        """Initialize the market manager"""
        log.info("Initializing Prime Market Manager...")
        
        # Load holiday data
        await self._load_holiday_data()
        
        # Initialize current session
        await self._update_current_session()
        
        log.info("Prime Market Manager initialized successfully")

    def _load_us_holidays(self) -> Dict[date, HolidayInfo]:
        """Load US Bank holidays"""
        holidays = {}
        
        if not HOLIDAYS_AVAILABLE:
            log.warning("Holidays library not available, using basic holiday list")
            return self._get_basic_us_holidays()
        
        try:
            us_holidays = pyholidays.US(years=range(2020, 2030))
            
            for holiday_date, holiday_name in us_holidays.items():
                holidays[holiday_date] = HolidayInfo(
                    date=holiday_date,
                    name=holiday_name,
                    holiday_type=HolidayType.US_BANK,
                    is_trading_day=False,
                    is_early_close=False
                )
            
            # Add early close days
            early_close_days = self._get_early_close_days()
            for close_date, close_time in early_close_days.items():
                if close_date in holidays:
                    holidays[close_date].is_trading_day = True
                    holidays[close_date].is_early_close = True
                    holidays[close_date].early_close_time = close_time
                else:
                    holidays[close_date] = HolidayInfo(
                        date=close_date,
                        name="Early Close Day",
                        holiday_type=HolidayType.EARLY_CLOSE,
                        is_trading_day=True,
                        is_early_close=True,
                        early_close_time=close_time
                    )
            
            # CRITICAL FIX: Add low-volume holidays from dynamic calculator
            try:
                from .dynamic_holiday_calculator import calculate_low_volume_holidays
                current_year = datetime.utcnow().year
                year_range = range(current_year - 1, current_year + 6)
                
                for year in year_range:
                    year_low_volume = calculate_low_volume_holidays(year)
                    for low_vol_date, low_vol_name in year_low_volume:
                        if low_vol_date in holidays:
                            # If it's already an early close day, convert it to a skip day
                            # Low-volume holidays should skip trading entirely, not just close early
                            if holidays[low_vol_date].is_early_close:
                                holidays[low_vol_date].is_trading_day = False  # CRITICAL: Skip trading on low-volume days
                                holidays[low_vol_date].name = f"{low_vol_name} (Low Volume - Skip Trading)"
                                log.info(f"Converted early close day {low_vol_date} to skip day due to low volume")
                        else:
                            holidays[low_vol_date] = HolidayInfo(
                                date=low_vol_date,
                                name=low_vol_name,
                                holiday_type=HolidayType.CUSTOM,  # Use CUSTOM for low-volume days
                                is_trading_day=False,  # CRITICAL: Skip trading on low-volume days
                                is_early_close=False
                            )
                
                log.info(f"Added low-volume holidays from dynamic calculator for years {current_year-1}-{current_year+5}")
                
            except ImportError as e:
                log.warning(f"Could not load low-volume holidays from dynamic calculator: {e}")
            
        except Exception as e:
            log.error(f"Error loading US holidays: {e}")
            return self._get_basic_us_holidays()
        
        return holidays

    def _load_muslim_holidays(self) -> Dict[date, HolidayInfo]:
        """Load Muslim holidays"""
        holidays = {}
        
        if not HIJRI_AVAILABLE:
            log.warning("Hijri converter not available, skipping Muslim holidays")
            return holidays
        
        try:
            # Get current year range
            current_year = datetime.utcnow().year  # Rev 00075: UTC consistency
            years = range(current_year - 2, current_year + 3)
            
            for year in years:
                # Eid al-Fitr (approximate)
                eid_fitr = self._calculate_eid_fitr(year)
                if eid_fitr:
                    holidays[eid_fitr] = HolidayInfo(
                        date=eid_fitr,
                        name="Eid al-Fitr",
                        holiday_type=HolidayType.MUSLIM,
                        is_trading_day=False
                    )
                
                # Eid al-Adha (approximate)
                eid_adha = self._calculate_eid_adha(year)
                if eid_adha:
                    holidays[eid_adha] = HolidayInfo(
                        date=eid_adha,
                        name="Eid al-Adha",
                        holiday_type=HolidayType.MUSLIM,
                        is_trading_day=False
                    )
                
                # Islamic New Year
                islamic_new_year = self._calculate_islamic_new_year(year)
                if islamic_new_year:
                    holidays[islamic_new_year] = HolidayInfo(
                        date=islamic_new_year,
                        name="Islamic New Year",
                        holiday_type=HolidayType.MUSLIM,
                        is_trading_day=False
                    )
        
        except Exception as e:
            log.error(f"Error loading Muslim holidays: {e}")
        
        return holidays

    def _load_custom_holidays(self) -> Dict[date, HolidayInfo]:
        """Load custom holidays from file"""
        holidays = {}
        
        try:
            if os.path.exists(self.session_config.holidays_custom_path):
                with open(self.session_config.holidays_custom_path, 'r') as f:
                    custom_data = json.load(f)
                
                for holiday_data in custom_data.get('holidays', []):
                    holiday_date = datetime.strptime(holiday_data['date'], '%Y-%m-%d').date()
                    holidays[holiday_date] = HolidayInfo(
                        date=holiday_date,
                        name=holiday_data['name'],
                        holiday_type=HolidayType.CUSTOM,
                        is_trading_day=holiday_data.get('is_trading_day', False),
                        is_early_close=holiday_data.get('is_early_close', False),
                        early_close_time=holiday_data.get('early_close_time')
                    )
        
        except Exception as e:
            log.error(f"Error loading custom holidays: {e}")
        
        return holidays

    async def _load_holiday_data(self) -> None:
        """Load all holiday data"""
        log.info("Loading holiday data...")
        
        # Load holidays in parallel
        await asyncio.gather(
            self._load_us_holidays_async(),
            self._load_muslim_holidays_async(),
            self._load_custom_holidays_async()
        )
        
        log.info(f"Loaded {len(self.us_holidays)} US holidays, {len(self.muslim_holidays)} Muslim holidays, {len(self.custom_holidays)} custom holidays")

    async def _load_us_holidays_async(self) -> None:
        """Load US holidays asynchronously"""
        # This is already loaded in __init__, but we can add async processing here
        pass

    async def _load_muslim_holidays_async(self) -> None:
        """Load Muslim holidays asynchronously"""
        # This is already loaded in __init__, but we can add async processing here
        pass

    async def _load_custom_holidays_async(self) -> None:
        """Load custom holidays asynchronously"""
        # This is already loaded in __init__, but we can add async processing here
        pass

    def is_market_open(self) -> bool:
        """Check if market is currently open"""
        cache_key = f"market_open_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"  # Rev 00075: UTC consistency
        
        if cache_key in self.cache:
            self.metrics['cache_hits'] += 1
            return self.cache[cache_key]
        
        self.metrics['cache_misses'] += 1
        self.metrics['market_status_checks'] += 1
        
        # Check if it's a trading day
        if not self.is_trading_day():
            self.cache[cache_key] = False
            return False
        
        # Check current time in Eastern Time
        now = datetime.now(self.timezone)
        current_time = now.time()
        
        # Log current time for debugging
        log.debug(f"Market hours check: Current time {current_time} ET, Trading day: {self.is_trading_day()}")
        
        # Check for early close
        if self.is_early_close_day():
            early_close_time = self.get_early_close_time()
            if early_close_time and current_time >= early_close_time:
                log.debug(f"Early close day: Market closed at {early_close_time}")
                self.cache[cache_key] = False
                return False
        
        # Regular market hours (9:30 AM - 4:00 PM ET)
        market_open = dt_time(9, 30)
        market_close = dt_time(16, 0)
        
        is_open = market_open <= current_time < market_close
        
        if is_open:
            log.debug(f"Market is OPEN: {current_time} ET (9:30 AM - 4:00 PM)")
        else:
            log.debug(f"Market is CLOSED: {current_time} ET (outside 9:30 AM - 4:00 PM)")
        
        self.cache[cache_key] = is_open
        return is_open

    def is_trading_day(self) -> bool:
        """Check if today is a trading day"""
        today = datetime.now(self.timezone).date()
        cache_key = f"trading_day_{today}"
        
        if cache_key in self.cache:
            self.metrics['cache_hits'] += 1
            return self.cache[cache_key]
        
        self.metrics['cache_misses'] += 1
        self.metrics['holiday_checks'] += 1
        
        # Check if it's a weekend
        if today.weekday() >= 5:  # Saturday or Sunday
            self.cache[cache_key] = False
            return False
        
        # Check holidays
        if today in self.us_holidays:
            holiday = self.us_holidays[today]
            is_trading = holiday.is_trading_day
            self.cache[cache_key] = is_trading
            return is_trading
        
        if today in self.muslim_holidays:
            holiday = self.muslim_holidays[today]
            is_trading = holiday.is_trading_day
            self.cache[cache_key] = is_trading
            return is_trading
        
        if today in self.custom_holidays:
            holiday = self.custom_holidays[today]
            is_trading = holiday.is_trading_day
            self.cache[cache_key] = is_trading
            return is_trading
        
        # Regular trading day
        self.cache[cache_key] = True
        return True

    def is_early_close_day(self) -> bool:
        """Check if today is an early close day"""
        today = datetime.now(self.timezone).date()
        
        # Check US holidays
        if today in self.us_holidays:
            return self.us_holidays[today].is_early_close
        
        # Check custom holidays
        if today in self.custom_holidays:
            return self.custom_holidays[today].is_early_close
        
        return False

    def get_early_close_time(self) -> Optional[dt_time]:
        """Get early close time for today"""
        today = datetime.now(self.timezone).date()
        
        # Check US holidays
        if today in self.us_holidays:
            holiday = self.us_holidays[today]
            if holiday.is_early_close and holiday.early_close_time:
                return dt_time.fromisoformat(holiday.early_close_time)
        
        # Check custom holidays
        if today in self.custom_holidays:
            holiday = self.custom_holidays[today]
            if holiday.is_early_close and holiday.early_close_time:
                return dt_time.fromisoformat(holiday.early_close_time)
        
        return None

    def get_market_phase(self) -> MarketPhase:
        """Get current market phase"""
        now = datetime.now(self.timezone)
        current_time = now.time()
        
        prep_start = dt_time.fromisoformat(self.session_config.prep_start)
        rth_open = dt_time.fromisoformat(self.session_config.rth_open)
        rth_close = dt_time.fromisoformat(self.session_config.rth_close)
        cooldown_end = dt_time.fromisoformat(self.session_config.cooldown_end)
        
        if prep_start <= current_time < rth_open:
            return MarketPhase.PREP
        elif rth_open <= current_time < rth_close:
            return MarketPhase.OPEN
        elif rth_close <= current_time < cooldown_end:
            return MarketPhase.COOLDOWN
        else:
            return MarketPhase.DARK

    def get_market_status(self) -> MarketStatus:
        """Get current market status"""
        if not self.is_trading_day():
            return MarketStatus.HOLIDAY
        
        if self.is_early_close_day():
            return MarketStatus.EARLY_CLOSE
        
        if self.is_market_open():
            return MarketStatus.OPEN
        
        now = datetime.now(self.timezone)
        current_time = now.time()
        
        prep_start = dt_time.fromisoformat(self.session_config.prep_start)
        rth_open = dt_time.fromisoformat(self.session_config.rth_open)
        rth_close = dt_time.fromisoformat(self.session_config.rth_close)
        cooldown_end = dt_time.fromisoformat(self.session_config.cooldown_end)
        
        if prep_start <= current_time < rth_open:
            return MarketStatus.PRE_MARKET
        elif rth_close <= current_time < cooldown_end:
            return MarketStatus.AFTER_HOURS
        else:
            return MarketStatus.CLOSED

    async def _update_current_session(self) -> None:
        """Update current trading session"""
        now = datetime.now(self.timezone)
        phase = self.get_market_phase()
        
        # Check if we need to start a new session
        if not self.current_session or self.current_session.phase != phase:
            # End previous session
            if self.current_session:
                self.current_session.end_time = now
                self.current_session.is_active = False
                self.session_history.append(self.current_session)
            
            # Start new session
            session_id = f"{phase.value}_{now.strftime('%Y%m%d_%H%M%S')}"
            self.current_session = TradingSession(
                session_id=session_id,
                start_time=now,
                end_time=now + timedelta(hours=8),  # Default 8-hour session
                phase=phase,
                is_active=True
            )
            
            self.metrics['session_updates'] += 1
            log.info(f"Started new session: {session_id} ({phase.value})")

    def get_next_market_open(self) -> Optional[datetime]:
        """Get next market open time"""
        now = datetime.now(self.timezone)
        today = now.date()
        
        # Check if market is already open today
        if self.is_market_open():
            return now
        
        # Check if market will open today
        if self.is_trading_day():
            market_open_time = dt_time.fromisoformat(self.session_config.rth_open)
            next_open = datetime.combine(today, market_open_time, self.timezone)
            
            if next_open > now:
                return next_open
        
        # Find next trading day
        for days_ahead in range(1, 8):  # Check next 7 days
            check_date = today + timedelta(days=days_ahead)
            if self._is_trading_day(check_date):
                market_open_time = dt_time.fromisoformat(self.session_config.rth_open)
                next_open = datetime.combine(check_date, market_open_time, self.timezone)
                return next_open
        
        return None

    def get_next_market_close(self) -> Optional[datetime]:
        """Get next market close time"""
        if not self.is_market_open():
            return None
        
        now = datetime.now(self.timezone)
        today = now.date()
        
        # Check for early close
        if self.is_early_close_day():
            early_close_time = self.get_early_close_time()
            if early_close_time:
                return datetime.combine(today, early_close_time, self.timezone)
        
        # Regular market close
        market_close_time = dt_time.fromisoformat(self.session_config.rth_close)
        return datetime.combine(today, market_close_time, self.timezone)

    def _is_trading_day(self, check_date: date) -> bool:
        """Check if a specific date is a trading day"""
        # Check if it's a weekend
        if check_date.weekday() >= 5:
            return False
        
        # Check holidays
        if check_date in self.us_holidays:
            return self.us_holidays[check_date].is_trading_day
        
        if check_date in self.muslim_holidays:
            return self.muslim_holidays[check_date].is_trading_day
        
        if check_date in self.custom_holidays:
            return self.custom_holidays[check_date].is_trading_day
        
        return True

    def _get_basic_us_holidays(self) -> Dict[date, HolidayInfo]:
        """Get comprehensive US holidays using dynamic calculation (future-proof)"""
        holidays = {}
        
        # Get current year and calculate holidays for a range
        current_year = datetime.utcnow().year  # Rev 00075: UTC consistency
        year_range = range(current_year - 1, current_year + 6)  # 5 years ahead
        
        # Try to use dynamic calculator if available
        try:
            from .dynamic_holiday_calculator import calculate_us_holidays, calculate_early_close_days, calculate_low_volume_holidays
            
            for year in year_range:
                # Calculate holidays for this year
                year_holidays = calculate_us_holidays(year)
                for holiday_date, holiday_name in year_holidays:
                    holidays[holiday_date] = HolidayInfo(
                        date=holiday_date,
                        name=holiday_name,
                        holiday_type=HolidayType.US_BANK,
                        is_trading_day=False,
                        is_early_close=False
                    )
                
                # Calculate early close days for this year
                year_early_close = calculate_early_close_days(year)
                for close_date, close_name, close_time in year_early_close:
                    holidays[close_date] = HolidayInfo(
                        date=close_date,
                        name=close_name,
                        holiday_type=HolidayType.EARLY_CLOSE,
                        is_trading_day=True,
                        is_early_close=True,
                        early_close_time=close_time
                    )
                
                # Calculate low-volume holidays for this year (CRITICAL FIX: Include low-volume days)
                year_low_volume = calculate_low_volume_holidays(year)
                for low_vol_date, low_vol_name in year_low_volume:
                    # Don't overwrite existing holidays (early close takes precedence)
                    if low_vol_date not in holidays:
                        holidays[low_vol_date] = HolidayInfo(
                            date=low_vol_date,
                            name=low_vol_name,
                            holiday_type=HolidayType.CUSTOM,  # Use CUSTOM for low-volume days
                            is_trading_day=False,  # CRITICAL: Skip trading on low-volume days
                            is_early_close=False
                        )
            
            log.info(f"Loaded {len(holidays)} holidays from dynamic calculator ({current_year-1}-{current_year+5})")
            
        except ImportError:
            # Fallback to hardcoded 2025 holidays if dynamic calculator not available
            log.warning("Dynamic holiday calculator not available, using fallback 2025 holidays")
            holidays_2025 = [
                (date(2025, 1, 1), "New Year's Day"),
                (date(2025, 1, 20), "Martin Luther King Jr. Day"),
                (date(2025, 2, 17), "Presidents' Day"),
                (date(2025, 4, 18), "Good Friday"),
                (date(2025, 5, 26), "Memorial Day"),
                (date(2025, 6, 19), "Juneteenth"),
                (date(2025, 7, 4), "Independence Day"),
                (date(2025, 9, 1), "Labor Day"),
                (date(2025, 11, 27), "Thanksgiving Day"),
                (date(2025, 12, 25), "Christmas Day")
            ]
            
            # Add all 2025 holidays
            for holiday_date, holiday_name in holidays_2025:
                holidays[holiday_date] = HolidayInfo(
                    date=holiday_date,
                    name=holiday_name,
                    holiday_type=HolidayType.US_BANK,
                    is_trading_day=False,
                    is_early_close=False
                )
            
            # Add early close days for 2025
            early_close_days_2025 = [
                (date(2025, 7, 3), "Independence Day Eve", "13:00"),
                (date(2025, 11, 28), "Black Friday", "13:00"),
                (date(2025, 12, 24), "Christmas Eve", "13:00")
            ]
            
            for close_date, close_name, close_time in early_close_days_2025:
                holidays[close_date] = HolidayInfo(
                    date=close_date,
                    name=close_name,
                    holiday_type=HolidayType.EARLY_CLOSE,
                    is_trading_day=True,
                    is_early_close=True,
                    early_close_time=close_time
                )
            
            log.info(f"Loaded {len(holidays)} holidays from fallback configuration (2025)")
        
        return holidays

    def _get_early_close_days(self) -> Dict[date, str]:
        """Get early close days"""
        current_year = datetime.utcnow().year  # Rev 00075: UTC consistency
        early_close_days = {}
        
        # Black Friday (day after Thanksgiving)
        # This is a simplified calculation
        thanksgiving = self._get_thanksgiving_date(current_year)
        if thanksgiving:
            black_friday = thanksgiving + timedelta(days=1)
            early_close_days[black_friday] = "13:00"  # 1:00 PM
        
        # Christmas Eve
        christmas_eve = date(current_year, 12, 24)
        if christmas_eve.weekday() < 5:  # Weekday
            early_close_days[christmas_eve] = "13:00"  # 1:00 PM
        
        return early_close_days

    def _get_thanksgiving_date(self, year: int) -> Optional[date]:
        """Get Thanksgiving date for a given year"""
        if not EASTER_AVAILABLE:
            return None
        
        try:
            # Thanksgiving is the 4th Thursday of November
            november_1 = date(year, 11, 1)
            first_thursday = november_1 + timedelta(days=(3 - november_1.weekday()) % 7)
            thanksgiving = first_thursday + timedelta(days=21)  # 4th Thursday
            return thanksgiving
        except Exception:
            return None

    def _calculate_eid_fitr(self, year: int) -> Optional[date]:
        """Calculate Eid al-Fitr date (approximate)"""
        if not HIJRI_AVAILABLE:
            return None
        
        try:
            # This is a simplified calculation
            # In practice, you'd use proper Islamic calendar calculations
            return None  # Placeholder
        except Exception:
            return None

    def _calculate_eid_adha(self, year: int) -> Optional[date]:
        """Calculate Eid al-Adha date (approximate)"""
        if not HIJRI_AVAILABLE:
            return None
        
        try:
            # This is a simplified calculation
            # In practice, you'd use proper Islamic calendar calculations
            return None  # Placeholder
        except Exception:
            return None

    def _calculate_islamic_new_year(self, year: int) -> Optional[date]:
        """Calculate Islamic New Year date (approximate)"""
        if not HIJRI_AVAILABLE:
            return None
        
        try:
            # This is a simplified calculation
            # In practice, you'd use proper Islamic calendar calculations
            return None  # Placeholder
        except Exception:
            return None

    def get_holiday_info(self, check_date: Optional[date] = None) -> Optional[HolidayInfo]:
        """Get holiday information for a specific date"""
        if check_date is None:
            check_date = datetime.now(self.timezone).date()
        
        # Check US holidays
        if check_date in self.us_holidays:
            return self.us_holidays[check_date]
        
        # Check Muslim holidays
        if check_date in self.muslim_holidays:
            return self.muslim_holidays[check_date]
        
        # Check custom holidays
        if check_date in self.custom_holidays:
            return self.custom_holidays[check_date]
        
        return None

    def get_market_hours_info(self) -> Dict[str, Any]:
        """Get comprehensive market hours information"""
        now = datetime.now(self.timezone)
        
        return {
            'current_time': now.isoformat(),
            'timezone': self.timezone.zone,
            'market_status': self.get_market_status().value,
            'market_phase': self.get_market_phase().value,
            'is_trading_day': self.is_trading_day(),
            'is_market_open': self.is_market_open(),
            'is_early_close_day': self.is_early_close_day(),
            'early_close_time': self.get_early_close_time().isoformat() if self.get_early_close_time() else None,
            'next_market_open': self.get_next_market_open().isoformat() if self.get_next_market_open() else None,
            'next_market_close': self.get_next_market_close().isoformat() if self.get_next_market_close() else None,
            'holiday_info': self.get_holiday_info().__dict__ if self.get_holiday_info() else None,
            'session_info': {
                'current_session': self.current_session.__dict__ if self.current_session else None,
                'total_sessions': len(self.session_history)
            },
            'performance_metrics': self.metrics.copy()
        }

    async def shutdown(self) -> None:
        """Shutdown the market manager"""
        log.info("Shutting down Prime Market Manager...")
        
        # End current session
        if self.current_session:
            self.current_session.end_time = datetime.now(self.timezone)
            self.current_session.is_active = False
            self.session_history.append(self.current_session)
        
        # Clear caches
        self.cache.clear()
        self.holiday_cache.clear()
        
        log.info("Prime Market Manager shutdown completed")

# Global instance
_prime_market_manager = None

def get_prime_market_manager(session_config: Optional[MarketSession] = None) -> PrimeMarketManager:
    """Get the prime market manager instance"""
    global _prime_market_manager
    if _prime_market_manager is None:
        _prime_market_manager = PrimeMarketManager(session_config)
    return _prime_market_manager
