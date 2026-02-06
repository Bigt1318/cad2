# ============================================================================
# FORD CAD — Smart Shift Logic (2-2-3-2-2-3 Rotation)
# ============================================================================
# 
# Corrected pattern based on actual BlueOval SK schedule:
# 
# A/B crews and C/D crews alternate:
#   - 2 days on, 2 days off, 3 days on, 2 days off, 2 days on, 3 days off
#
# Starting Feb 2, 2026 (Sunday) = A/B:
#   Feb 2-3 (Sun-Mon): A/B - 2 days
#   Feb 4-5 (Tue-Wed): C/D - 2 days
#   Feb 6-8 (Thu-Sat): A/B - 3 days
#   Feb 9-10 (Sun-Mon): C/D - 2 days
#   Feb 11-12 (Tue-Wed): A/B - 2 days
#   Feb 13-15 (Thu-Sat): C/D - 3 days
#   Then repeats...
#
# ============================================================================

import datetime
from typing import Dict, Tuple, Optional

# 14-day cycle pattern (corrected)
# Index 0-13 represents each day in the cycle
# Each entry is (day_shift, night_shift)
SHIFT_CYCLE = [
    # Week 1
    ("A", "B"),  # Day 0 (Sun) - 2-day block
    ("A", "B"),  # Day 1 (Mon)
    ("C", "D"),  # Day 2 (Tue) - 2-day block
    ("C", "D"),  # Day 3 (Wed)
    ("A", "B"),  # Day 4 (Thu) - 3-day block
    ("A", "B"),  # Day 5 (Fri)
    ("A", "B"),  # Day 6 (Sat)
    # Week 2
    ("C", "D"),  # Day 7 (Sun) - 2-day block
    ("C", "D"),  # Day 8 (Mon)
    ("A", "B"),  # Day 9 (Tue) - 2-day block
    ("A", "B"),  # Day 10 (Wed)
    ("C", "D"),  # Day 11 (Thu) - 3-day block
    ("C", "D"),  # Day 12 (Fri)
    ("C", "D"),  # Day 13 (Sat)
]

# Battalion Chiefs by shift
BATTALION_CHIEFS = {
    "A": {
        "unit_id": "Batt1",
        "name": "Bill Mullins",
        "email": "",
        "phone": "",
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
    """Get the day index (0-13) in the 14-day cycle for a given date."""
    if date is None:
        date = datetime.date.today()
    
    days_since_ref = (date - REFERENCE_DATE).days
    return days_since_ref % 14


def get_shift_for_date(date: datetime.date = None) -> Tuple[str, str]:
    """Get the day and night shift letters for a given date."""
    cycle_day = get_cycle_day(date)
    return SHIFT_CYCLE[cycle_day]


def get_current_shift(dt: datetime.datetime = None) -> str:
    """
    Determine the current active shift letter based on date and time.
    
    Day shift: 0600-1800
    Night shift: 1800-0600
    """
    if dt is None:
        dt = datetime.datetime.now()
    
    hour = dt.hour
    current_date = dt.date()
    
    # Night shift spans two calendar days (1800-0600)
    if hour < 6:
        prev_date = current_date - datetime.timedelta(days=1)
        day_shift, night_shift = get_shift_for_date(prev_date)
        return night_shift
    elif hour >= 18:
        day_shift, night_shift = get_shift_for_date(current_date)
        return night_shift
    else:
        day_shift, night_shift = get_shift_for_date(current_date)
        return day_shift


def get_current_battalion_chief(dt: datetime.datetime = None) -> Dict:
    """Get the battalion chief info for the current shift."""
    shift = get_current_shift(dt)
    return BATTALION_CHIEFS.get(shift, {})


def get_shift_info(dt: datetime.datetime = None) -> Dict:
    """Get comprehensive shift information for a given datetime."""
    if dt is None:
        dt = datetime.datetime.now()
    
    shift = get_current_shift(dt)
    bc = get_current_battalion_chief(dt)
    hour = dt.hour
    
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
    """Check if it's time to send the end-of-shift report."""
    if dt is None:
        dt = datetime.datetime.now()
    
    hour = dt.hour
    minute = dt.minute
    
    if hour == 17 and 25 <= minute <= 35:
        return True
    if hour == 5 and 25 <= minute <= 35:
        return True
    
    return False


def get_shift_schedule(start_date: datetime.date = None, days: int = 14) -> list:
    """Generate a schedule showing shifts for a range of dates."""
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
    """Update contact info for a battalion chief."""
    if shift not in BATTALION_CHIEFS:
        return False
    
    if email is not None:
        BATTALION_CHIEFS[shift]["email"] = email
    if phone is not None:
        BATTALION_CHIEFS[shift]["phone"] = phone
    
    return True


def verify_schedule():
    """Print the next 14 days to verify the schedule is correct."""
    print("=" * 70)
    print("FORD CAD - 2-2-3-2-2-3 Shift Schedule (CORRECTED)")
    print("=" * 70)
    print()
    
    schedule = get_shift_schedule(days=14)
    
    print(f"{'Date':<12} {'Day':<10} {'Day Shift':<20} {'Night Shift':<20}")
    print("-" * 70)
    
    for day in schedule:
        print(f"{day['date']:<12} {day['day_of_week']:<10} "
              f"{day['day_shift']} - {day['day_bc']:<16} "
              f"{day['night_shift']} - {day['night_bc']:<16}")


if __name__ == "__main__":
    verify_schedule()
