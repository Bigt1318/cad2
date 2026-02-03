# ============================================================================
# FORD CAD — Smart Shift Logic (2-2-3-2-2-3 Rotation)
# ============================================================================
# 
# The 2-2-3-2-2-3 schedule (Panama/Pitman schedule) is a 14-day cycle:
#
# Pattern for day shifts: A A C C C A A | C C A A A C C
# Pattern for night shifts: B B D D D B B | D D B B B D D
#
# Each crew works:
#   - 2 days on, 2 days off
#   - 3 days on, 2 days off
#   - 2 days on, 3 days off
#   Then repeat
#
# Reference: Feb 2-3, 2026 = Day 0-1 of cycle (A-day, B-night)
# ============================================================================

import datetime
from typing import Dict, Tuple, Optional

# 14-day cycle pattern
# Index 0-13 represents each day in the cycle
# Each entry is (day_shift, night_shift)
SHIFT_CYCLE = [
    # Week 1
    ("A", "B"),  # Day 0 (Mon) - 2-day block starts
    ("A", "B"),  # Day 1 (Tue)
    ("C", "D"),  # Day 2 (Wed) - 3-day block starts
    ("C", "D"),  # Day 3 (Thu)
    ("C", "D"),  # Day 4 (Fri)
    ("A", "B"),  # Day 5 (Sat) - 2-day block starts
    ("A", "B"),  # Day 6 (Sun)
    # Week 2
    ("C", "D"),  # Day 7 (Mon) - 2-day block starts
    ("C", "D"),  # Day 8 (Tue)
    ("A", "B"),  # Day 9 (Wed) - 3-day block starts
    ("A", "B"),  # Day 10 (Thu)
    ("A", "B"),  # Day 11 (Fri)
    ("C", "D"),  # Day 12 (Sat) - 2-day block starts
    ("C", "D"),  # Day 13 (Sun)
]

# Battalion Chiefs by shift
BATTALION_CHIEFS = {
    "A": {
        "unit_id": "Batt1",
        "name": "Bill Mullins",
        "email": "",  # To be configured
        "phone": "",  # To be configured
    },
    "B": {
        "unit_id": "Batt2", 
        "name": "Daniel Highbaugh",
        "email": "",
        "phone": "",
    },
    "C": {
        "unit_id": "Batt3",
        "name": "Kevin Jevning",
        "email": "",
        "phone": "",
    },
    "D": {
        "unit_id": "Batt4",
        "name": "Shane Carpenter",
        "email": "",
        "phone": "",
    },
}

# Reference date: Feb 2, 2026 is Day 0 of the cycle (A-day, B-night)
REFERENCE_DATE = datetime.date(2026, 2, 2)


def get_cycle_day(date: datetime.date = None) -> int:
    """
    Get the day index (0-13) in the 14-day cycle for a given date.
    
    Args:
        date: The date to check. Defaults to today.
        
    Returns:
        int: Day index 0-13 in the cycle
    """
    if date is None:
        date = datetime.date.today()
    
    days_since_ref = (date - REFERENCE_DATE).days
    return days_since_ref % 14


def get_shift_for_date(date: datetime.date = None) -> Tuple[str, str]:
    """
    Get the day and night shift letters for a given date.
    
    Args:
        date: The date to check. Defaults to today.
        
    Returns:
        tuple: (day_shift, night_shift) e.g., ("A", "B")
    """
    cycle_day = get_cycle_day(date)
    return SHIFT_CYCLE[cycle_day]


def get_current_shift(dt: datetime.datetime = None) -> str:
    """
    Determine the current active shift letter based on date and time.
    
    Day shift: 0600-1800
    Night shift: 1800-0600
    
    Args:
        dt: DateTime to check. Defaults to now.
        
    Returns:
        str: Shift letter (A, B, C, or D)
    """
    if dt is None:
        dt = datetime.datetime.now()
    
    hour = dt.hour
    current_date = dt.date()
    
    # Night shift spans two calendar days (1800-0600)
    # If it's between 0000-0600, we're on the previous day's night shift
    if hour < 6:
        # Use previous day's night shift
        prev_date = current_date - datetime.timedelta(days=1)
        day_shift, night_shift = get_shift_for_date(prev_date)
        return night_shift
    elif hour >= 18:
        # Current day's night shift
        day_shift, night_shift = get_shift_for_date(current_date)
        return night_shift
    else:
        # Day shift (0600-1800)
        day_shift, night_shift = get_shift_for_date(current_date)
        return day_shift


def get_current_battalion_chief(dt: datetime.datetime = None) -> Dict:
    """
    Get the battalion chief info for the current shift.
    
    Args:
        dt: DateTime to check. Defaults to now.
        
    Returns:
        dict: Battalion chief info including name, email, etc.
    """
    shift = get_current_shift(dt)
    return BATTALION_CHIEFS.get(shift, {})


def get_shift_info(dt: datetime.datetime = None) -> Dict:
    """
    Get comprehensive shift information for a given datetime.
    
    Args:
        dt: DateTime to check. Defaults to now.
        
    Returns:
        dict: Complete shift information
    """
    if dt is None:
        dt = datetime.datetime.now()
    
    shift = get_current_shift(dt)
    bc = get_current_battalion_chief(dt)
    hour = dt.hour
    
    # Determine if day or night shift
    if 6 <= hour < 18:
        shift_type = "Day"
        start_time = "0600"
        end_time = "1800"
        report_time = "1730"
    else:
        shift_type = "Night"
        start_time = "1800"
        end_time = "0600"
        report_time = "0530"
    
    # Get the full day's shifts
    day_shift, night_shift = get_shift_for_date(dt.date())
    
    return {
        "shift": shift,
        "shift_type": shift_type,
        "start_time": start_time,
        "end_time": end_time,
        "report_time": report_time,
        "battalion_chief": bc.get("name", "Unknown"),
        "battalion_unit": bc.get("unit_id", ""),
        "bc_email": bc.get("email", ""),
        "bc_phone": bc.get("phone", ""),
        "day_shift": day_shift,
        "night_shift": night_shift,
        "current_time": dt.strftime("%H:%M"),
        "date": dt.strftime("%Y-%m-%d"),
        "cycle_day": get_cycle_day(dt.date()),
    }


def is_report_time(dt: datetime.datetime = None) -> bool:
    """
    Check if it's time to send the end-of-shift report.
    
    Day shift report: 1730 (17:30)
    Night shift report: 0530 (05:30)
    
    Args:
        dt: DateTime to check. Defaults to now.
        
    Returns:
        bool: True if within report window (±5 minutes of report time)
    """
    if dt is None:
        dt = datetime.datetime.now()
    
    hour = dt.hour
    minute = dt.minute
    
    # Day shift report time: 17:25-17:35
    if hour == 17 and 25 <= minute <= 35:
        return True
    
    # Night shift report time: 05:25-05:35
    if hour == 5 and 25 <= minute <= 35:
        return True
    
    return False


def get_shift_schedule(start_date: datetime.date = None, days: int = 14) -> list:
    """
    Generate a schedule showing shifts for a range of dates.
    
    Args:
        start_date: First date to show. Defaults to today.
        days: Number of days to show. Defaults to 14 (full cycle).
        
    Returns:
        list: List of dicts with date, day_shift, night_shift
    """
    if start_date is None:
        start_date = datetime.date.today()
    
    schedule = []
    for i in range(days):
        date = start_date + datetime.timedelta(days=i)
        day_shift, night_shift = get_shift_for_date(date)
        
        day_bc = BATTALION_CHIEFS.get(day_shift, {})
        night_bc = BATTALION_CHIEFS.get(night_shift, {})
        
        schedule.append({
            "date": date.strftime("%Y-%m-%d"),
            "day_of_week": date.strftime("%A"),
            "day_shift": day_shift,
            "day_bc": day_bc.get("name", ""),
            "night_shift": night_shift,
            "night_bc": night_bc.get("name", ""),
            "cycle_day": get_cycle_day(date),
        })
    
    return schedule


def update_battalion_chief_contact(shift: str, email: str = None, phone: str = None) -> bool:
    """
    Update contact info for a battalion chief.
    
    Args:
        shift: Shift letter (A, B, C, or D)
        email: Email address
        phone: Phone number
        
    Returns:
        bool: True if updated successfully
    """
    if shift not in BATTALION_CHIEFS:
        return False
    
    if email is not None:
        BATTALION_CHIEFS[shift]["email"] = email
    if phone is not None:
        BATTALION_CHIEFS[shift]["phone"] = phone
    
    return True


# ---------------------------------------------------------------------------
# Testing / Verification
# ---------------------------------------------------------------------------

def verify_schedule():
    """Print the next 14 days to verify the schedule is correct."""
    print("=" * 70)
    print("FORD CAD - 2-2-3-2-2-3 Shift Schedule Verification")
    print("=" * 70)
    print()
    
    schedule = get_shift_schedule(days=14)
    
    print(f"{'Date':<12} {'Day':<10} {'Day Shift':<12} {'Night Shift':<12} {'Cycle'}")
    print("-" * 70)
    
    for day in schedule:
        print(f"{day['date']:<12} {day['day_of_week']:<10} "
              f"{day['day_shift']} ({day['day_bc'][:10]:<10}) "
              f"{day['night_shift']} ({day['night_bc'][:10]:<10}) "
              f"Day {day['cycle_day']}")
    
    print()
    print("Current shift info:")
    info = get_shift_info()
    for k, v in info.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    verify_schedule()
