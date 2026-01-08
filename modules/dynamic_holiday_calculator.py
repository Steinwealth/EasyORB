#!/usr/bin/env python3
"""
Dynamic Holiday Calculator
=========================

Future-proof US market holiday calculator that works without external libraries.
Calculates holidays for any year using mathematical algorithms.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

def calculate_easter(year: int) -> date:
    """Calculate Easter Sunday for a given year using the Anonymous Gregorian algorithm"""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = (h + l - 7 * m + 114) // 31
    p = (h + l - 7 * m + 114) % 31
    return date(year, n, p + 1)

def get_nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Get the nth occurrence of a weekday in a given month"""
    # weekday: 0=Monday, 1=Tuesday, ..., 6=Sunday
    first_day = date(year, month, 1)
    days_ahead = weekday - first_day.weekday()
    if days_ahead < 0:
        days_ahead += 7
    first_weekday = first_day + timedelta(days=days_ahead)
    return first_weekday + timedelta(weeks=n-1)

def calculate_us_holidays(year: int) -> List[Tuple[date, str]]:
    """Calculate all US market holidays for a given year"""
    holidays = []
    
    # Fixed holidays
    holidays.extend([
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 7, 4), "Independence Day"),
        (date(year, 12, 25), "Christmas Day"),
    ])
    
    # Variable holidays
    # Martin Luther King Jr. Day - 3rd Monday of January
    mlk_day = get_nth_weekday_of_month(year, 1, 0, 3)  # 0 = Monday
    holidays.append((mlk_day, "Martin Luther King Jr. Day"))
    
    # Presidents' Day - 3rd Monday of February
    presidents_day = get_nth_weekday_of_month(year, 2, 0, 3)  # 0 = Monday
    holidays.append((presidents_day, "Presidents' Day"))
    
    # Good Friday - Friday before Easter Sunday
    easter = calculate_easter(year)
    good_friday = easter - timedelta(days=2)
    holidays.append((good_friday, "Good Friday"))
    
    # Memorial Day - Last Monday of May
    # Find the last day of May, then work backwards to the last Monday
    last_day_of_may = date(year, 6, 1) - timedelta(days=1)
    days_back = last_day_of_may.weekday()  # 0=Monday, 6=Sunday
    memorial_day = last_day_of_may - timedelta(days=days_back)
    holidays.append((memorial_day, "Memorial Day"))
    
    # Juneteenth - June 19th (fixed since 2021)
    holidays.append((date(year, 6, 19), "Juneteenth"))
    
    # Labor Day - 1st Monday of September
    labor_day = get_nth_weekday_of_month(year, 9, 0, 1)  # 0 = Monday
    holidays.append((labor_day, "Labor Day"))
    
    # Thanksgiving Day - 4th Thursday of November
    thanksgiving = get_nth_weekday_of_month(year, 11, 3, 4)  # 3 = Thursday
    holidays.append((thanksgiving, "Thanksgiving Day"))
    
    return sorted(holidays)

def calculate_low_volume_holidays(year: int) -> List[Tuple[date, str]]:
    """
    Calculate non-bank holidays with typically low trading volume (Rev 00087)
    
    These are days when markets are OPEN but volume/momentum is typically low.
    Strategy should skip trading on these days to avoid low-quality setups.
    """
    low_volume_days = []
    
    # Halloween - October 31st (if it's a weekday)
    halloween = date(year, 10, 31)
    if halloween.weekday() < 5:  # Monday-Friday
        low_volume_days.append((halloween, "Halloween"))
    
    # Indigenous Peoples' / Columbus Day - second Monday in October
    columbus_day = get_nth_weekday_of_month(year, 10, 0, 2)  # 0 = Monday, 2nd occurrence
    low_volume_days.append((columbus_day, "Indigenous Peoples' Day / Columbus Day"))
    
    # Veterans Day - November 11 (market open but historically low volume)
    veterans_day = date(year, 11, 11)
    if veterans_day.weekday() < 5:
        low_volume_days.append((veterans_day, "Veterans Day"))
    
    # Day before Thanksgiving (markets often close early or have low volume)
    thanksgiving = get_nth_weekday_of_month(year, 11, 3, 4)  # 4th Thursday
    day_before_thanksgiving = thanksgiving - timedelta(days=1)
    if day_before_thanksgiving.weekday() < 5:  # Should be Wednesday
        low_volume_days.append((day_before_thanksgiving, "Day Before Thanksgiving"))
    
    # Black Friday - Day after Thanksgiving (often early close)
    black_friday = thanksgiving + timedelta(days=1)
    if black_friday.weekday() < 5:  # Should be Friday
        low_volume_days.append((black_friday, "Black Friday"))
    
    # Christmas Eve - December 24th (if it's a weekday)
    christmas_eve = date(year, 12, 24)
    if christmas_eve.weekday() < 5:  # Monday-Friday
        low_volume_days.append((christmas_eve, "Christmas Eve"))
    
    # New Year's Eve - December 31st (if it's a weekday)
    nye = date(year, 12, 31)
    if nye.weekday() < 5:  # Monday-Friday
        low_volume_days.append((nye, "New Year's Eve"))
    
    # Day after Christmas (if Dec 26 is a weekday and Dec 25 was a weekday)
    christmas = date(year, 12, 25)
    day_after_christmas = date(year, 12, 26)
    if christmas.weekday() < 5 and day_after_christmas.weekday() < 5:
        low_volume_days.append((day_after_christmas, "Day After Christmas"))
    
    # Day after New Year's (if Jan 2 is a weekday and Jan 1 was a weekday)
    new_years = date(year, 1, 1)
    day_after_ny = date(year, 1, 2)
    if new_years.weekday() < 5 and day_after_ny.weekday() < 5:
        low_volume_days.append((day_after_ny, "Day After New Year's"))
    
    return sorted(low_volume_days)

def calculate_early_close_days(year: int) -> List[Tuple[date, str, str]]:
    """Calculate early close days for a given year"""
    early_close_days = []
    
    # Independence Day Eve - July 3rd (if July 4th is not a weekend)
    july_4th = date(year, 7, 4)
    if july_4th.weekday() == 0:  # Monday
        # If July 4th is Monday, July 3rd (Sunday) is early close
        early_close_days.append((date(year, 7, 3), "Independence Day Eve", "13:00"))
    elif july_4th.weekday() in [1, 2, 3, 4]:  # Tuesday through Friday
        # If July 4th is a weekday, July 3rd is early close
        early_close_days.append((date(year, 7, 3), "Independence Day Eve", "13:00"))
    
    # Black Friday - Day after Thanksgiving
    thanksgiving = get_nth_weekday_of_month(year, 11, 3, 4)  # 4th Thursday
    black_friday = thanksgiving + timedelta(days=1)
    early_close_days.append((black_friday, "Black Friday", "13:00"))
    
    # Christmas Eve - December 24th (if December 25th is not a weekend)
    christmas = date(year, 12, 25)
    if christmas.weekday() == 0:  # Monday
        # If Christmas is Monday, December 24th (Sunday) is early close
        early_close_days.append((date(year, 12, 24), "Christmas Eve", "13:00"))
    elif christmas.weekday() in [1, 2, 3, 4]:  # Tuesday through Friday
        # If Christmas is a weekday, December 24th is early close
        early_close_days.append((date(year, 12, 24), "Christmas Eve", "13:00"))
    
    return sorted(early_close_days)

def get_holidays_for_year(year: int) -> Dict:
    """Get all holidays and early close days for a specific year (Rev 00087)"""
    holidays = calculate_us_holidays(year)
    early_close = calculate_early_close_days(year)
    low_volume = calculate_low_volume_holidays(year)
    
    return {
        "year": year,
        "holidays": [(d.strftime("%Y-%m-%d"), name) for d, name in holidays],
        "early_close_days": [(d.strftime("%Y-%m-%d"), name, time) for d, name, time in early_close],
        "low_volume_holidays": [(d.strftime("%Y-%m-%d"), name) for d, name in low_volume],
        "total_holidays": len(holidays),
        "total_early_close_days": len(early_close),
        "total_low_volume_holidays": len(low_volume)
    }

def is_low_volume_holiday(check_date: date = None) -> Tuple[bool, str]:
    """
    Check if a given date is a low-volume holiday (Rev 00087)
    
    Args:
        check_date: Date to check (default: today)
        
    Returns:
        Tuple of (is_holiday, holiday_name)
    """
    if check_date is None:
        check_date = date.today()
    
    year = check_date.year
    low_volume_days = calculate_low_volume_holidays(year)
    
    for holiday_date, name in low_volume_days:
        if holiday_date == check_date:
            return (True, name)
    
    return (False, "")

def should_skip_trading(check_date: date = None) -> Tuple[bool, str, str]:
    """
    Determine if trading should be skipped on a given date (Rev 00087)
    
    Checks both bank holidays (market closed) AND low-volume holidays (market open, low momentum).
    
    Args:
        check_date: Date to check (default: today)
        
    Returns:
        Tuple of (should_skip, reason, holiday_name)
        reason: "MARKET_CLOSED" or "LOW_VOLUME" or ""
    """
    if check_date is None:
        check_date = date.today()
    
    year = check_date.year
    
    # Check bank holidays (market closed)
    bank_holidays = calculate_us_holidays(year)
    for holiday_date, name in bank_holidays:
        if holiday_date == check_date:
            return (True, "MARKET_CLOSED", name)
    
    # Check low-volume holidays (market open, skip trading)
    low_volume_days = calculate_low_volume_holidays(year)
    for holiday_date, name in low_volume_days:
        if holiday_date == check_date:
            return (True, "LOW_VOLUME", name)
    
    return (False, "", "")

if __name__ == "__main__":
    # Test the calculator
    current_year = datetime.now().year
    print(f"Testing holiday calculator for {current_year}...")
    
    result = get_holidays_for_year(current_year)
    print(f"\nBank Holidays (Market Closed) for {current_year}:")
    for date_str, name in result["holidays"]:
        print(f"  {date_str}: {name}")
    
    print(f"\nLow-Volume Holidays (Skip Trading) for {current_year}:")
    for date_str, name in result["low_volume_holidays"]:
        print(f"  {date_str}: {name}")
    
    print(f"\nEarly Close Days for {current_year}:")
    for date_str, name, time in result["early_close_days"]:
        print(f"  {date_str}: {name} ({time})")
    
    print(f"\nSummary:")
    print(f"  Bank Holidays: {result['total_holidays']}")
    print(f"  Low-Volume Holidays: {result['total_low_volume_holidays']}")
    print(f"  Early Close Days: {result['total_early_close_days']}")
    print(f"  Total Days to Skip: {result['total_holidays'] + result['total_low_volume_holidays']}")
    
    # Test today
    print(f"\nToday's Check ({date.today()}):")
    should_skip, reason, holiday_name = should_skip_trading()
    if should_skip:
        print(f"  ⛔ SKIP TRADING: {holiday_name} ({reason})")
    else:
        print(f"  ✅ NORMAL TRADING DAY")
