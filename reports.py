# ============================================================================
# FORD CAD — Daily Reporting & Messaging System
# ============================================================================
# Features:
#   - Daily shift reports (every 30 min during shift, until end of shift)
#   - Email (SMTP via Gmail)
#   - Signal messaging (via signal-cli)
#   - SMS via carrier email-to-SMS gateways
#   - Battalion Chief distribution list
# ============================================================================

import sqlite3
import datetime
import smtplib
import subprocess
import os
import json
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional, List, Dict, Any

# ---------------------------------------------------------------------------
# Configuration (override via environment or config file)
# ---------------------------------------------------------------------------
CONFIG = {
    # SMTP Settings - Gmail
    "smtp_host": os.getenv("CAD_SMTP_HOST", "smtp.gmail.com"),
    "smtp_port": int(os.getenv("CAD_SMTP_PORT", "587")),
    "smtp_user": os.getenv("CAD_SMTP_USER", "bosksert@gmail.com"),
    "smtp_pass": os.getenv("CAD_SMTP_PASS", ""),  # Set via env or load from config
    "smtp_from": os.getenv("CAD_SMTP_FROM", "FORD CAD System <bosksert@gmail.com>"),
    "smtp_use_tls": os.getenv("CAD_SMTP_TLS", "true").lower() == "true",

    # Signal CLI path (install signal-cli separately)
    "signal_cli_path": os.getenv("CAD_SIGNAL_CLI", "signal-cli"),
    "signal_sender": os.getenv("CAD_SIGNAL_SENDER", ""),

    # Database
    "db_path": os.getenv("CAD_DB_PATH", "cad.db"),

    # Shift Configuration - 4-shift rotation (A, B, C, D)
    # Day shifts: A and C (0600-1800, report at 1730)
    # Night shifts: B and D (1800-0600, report at 0530)
    "day_shift_start": 6,    # 0600
    "day_shift_end": 18,     # 1800
    "day_report_time": (17, 30),   # 1730
    "night_report_time": (5, 30),  # 0530

    # Shift rotation - 4 shifts cycle: A, B, C, D
    # Reference date when A shift started a day shift
    # Rotation: A(day)->B(night)->C(day)->D(night)->A(day)...
    # Feb 2, 2026 is A shift (day)
    "shift_reference_date": "2026-02-02",
    "shift_rotation": ["A", "B", "C", "D"],  # Order of rotation

    # Report interval (minutes) - for interim reports during shift
    "report_interval_minutes": 30,

    # Enable automatic reporting
    "auto_report_enabled": os.getenv("CAD_AUTO_REPORTS", "true").lower() == "true",
}

# Battalion Chief Distribution List
BATTALION_CHIEFS = {
    "Battalion 1": {
        "name": "Bill Mullins",
        "email": "bill.mullins@blueovalsk.com",
    },
    "Battalion 2": {
        "name": "Daniel Highbaugh",
        "email": "daniel.highbaugh@blueovalsky.com",
    },
    "Battalion 3": {
        "name": "Kevin Jevning",
        "email": "kevin.jevning@blueovalsk.com",
    },
    "Battalion 4": {
        "name": "Shane Carpenter",
        "email": "shane.carpenter@blueovalsky.com",
    },
}

# SMS Carrier Gateways (email-to-SMS)
SMS_GATEWAYS = {
    "att": "@txt.att.net",
    "verizon": "@vtext.com",
    "tmobile": "@tmomail.net",
    "sprint": "@messaging.sprintpcs.com",
    "uscellular": "@email.uscc.net",
    "virgin": "@vmobl.com",
    "boost": "@sms.myboostmobile.com",
    "cricket": "@sms.cricketwireless.net",
    "metro": "@mymetropcs.com",
    "google_fi": "@msg.fi.google.com",
}

# Track sent reports to avoid duplicates
_sent_reports = set()
_scheduler_running = False
_scheduler_thread = None

# Pending report confirmation state
_pending_report = None  # Dict with report details when awaiting confirmation
_pending_report_lock = threading.Lock()
CONFIRMATION_TIMEOUT_SECONDS = 30


def load_email_config():
    """Load email configuration from config file if exists."""
    config_path = Path("email_config.json")
    if config_path.exists():
        try:
            with open(config_path) as f:
                cfg = json.load(f)
                if cfg.get("smtp_pass"):
                    CONFIG["smtp_pass"] = cfg["smtp_pass"]
                if cfg.get("smtp_user"):
                    CONFIG["smtp_user"] = cfg["smtp_user"]
                if cfg.get("sendgrid_api_key"):
                    CONFIG["sendgrid_api_key"] = cfg["sendgrid_api_key"]
                if cfg.get("from_email"):
                    CONFIG["smtp_from"] = cfg["from_email"]
                if "auto_report_enabled" in cfg:
                    CONFIG["auto_report_enabled"] = cfg["auto_report_enabled"]
                print("[REPORTS] Email config loaded from email_config.json")
        except Exception as e:
            print(f"[REPORTS] Failed to load email config: {e}")


def save_email_config(smtp_user: str, smtp_pass: str):
    """Save email configuration to file."""
    config_path = Path("email_config.json")
    try:
        with open(config_path, "w") as f:
            json.dump({
                "smtp_user": smtp_user,
                "smtp_pass": smtp_pass,
            }, f, indent=2)
        print("[REPORTS] Email config saved")
        return True
    except Exception as e:
        print(f"[REPORTS] Failed to save email config: {e}")
        return False


# Load config on module import
load_email_config()


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(CONFIG["db_path"])
    conn.row_factory = sqlite3.Row
    return conn


def get_current_shift(dt: datetime.datetime = None) -> str:
    """
    Determine current shift letter using 4-shift rotation (A, B, C, D).

    Rotation pattern:
    - A and C are day shifts (0600-1800)
    - B and D are night shifts (1800-0600)
    - Cycle: A(day) -> B(night) -> C(day) -> D(night) -> repeat

    Reference: Feb 2, 2026 day shift = A shift
    """
    if dt is None:
        dt = datetime.datetime.now()

    # Reference date when A shift started (day shift)
    ref_date_str = CONFIG.get("shift_reference_date", "2026-02-02")
    ref_date = datetime.datetime.strptime(ref_date_str, "%Y-%m-%d").date()

    # Calculate the current date and whether we're in day or night
    current_date = dt.date()
    hour = dt.hour

    # Night shift spans two calendar days (1800-0600)
    # If it's between 0000-0600, we're still on the previous day's night shift
    if hour < 6:
        current_date = current_date - datetime.timedelta(days=1)
        is_night = True
    elif hour >= 18:
        is_night = True
    else:
        is_night = False

    # Calculate days since reference date
    days_diff = (current_date - ref_date).days

    # Each calendar day has 2 shifts (day and night)
    # shift_index cycles 0, 1, 2, 3 (A, B, C, D)
    # Day 0: A(day=0), B(night=1)
    # Day 1: C(day=2), D(night=3)
    # Day 2: A(day=0), B(night=1) ... repeats every 2 days
    day_in_cycle = days_diff % 2
    shift_index = (day_in_cycle * 2) + (1 if is_night else 0)

    rotation = CONFIG.get("shift_rotation", ["A", "B", "C", "D"])
    return rotation[shift_index]


def is_day_shift(shift: str) -> bool:
    """Check if shift letter is a day shift (A or C)."""
    return shift in ("A", "C")


def is_night_shift(shift: str) -> bool:
    """Check if shift letter is a night shift (B or D)."""
    return shift in ("B", "D")


def get_shift_date_range(shift: str, date: datetime.date = None) -> tuple:
    """Get start and end datetime for a shift on given date."""
    if date is None:
        date = datetime.date.today()

    # A and C are day shifts (0600-1800)
    # B and D are night shifts (1800-0600)
    if is_day_shift(shift):
        start = datetime.datetime.combine(date, datetime.time(6, 0, 0))
        end = datetime.datetime.combine(date, datetime.time(18, 0, 0))
    else:  # Night shifts (B or D)
        start = datetime.datetime.combine(date, datetime.time(18, 0, 0))
        end = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(6, 0, 0))

    return start, end


def is_during_shift() -> bool:
    """
    Check if we're currently during an active reporting period.

    Reports are sent every 30 min during shift:
    - Day shifts (A/C): 0600-1730 (last report at 17:30)
    - Night shifts (B/D): 1800-0530 (last report at 05:30)
    """
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute

    # Day shift hours: 0600-1730 (reports until 17:30)
    if 6 <= hour < 17:
        return True
    if hour == 17 and minute <= 30:
        return True

    # Night shift hours: 1800-0530 (reports until 05:30)
    if 18 <= hour <= 23:
        return True
    if 0 <= hour < 5:
        return True
    if hour == 5 and minute <= 30:
        return True

    return False


def get_shift_info() -> dict:
    """
    Get comprehensive shift information for display.

    Returns:
        dict with shift letter, type (day/night), times, etc.
    """
    now = datetime.datetime.now()
    shift = get_current_shift(now)

    if is_day_shift(shift):
        shift_type = "Day"
        start_time = "0600"
        end_time = "1800"
        report_time = "1730"
    else:
        shift_type = "Night"
        start_time = "1800"
        end_time = "0600"
        report_time = "0530"

    return {
        "shift": shift,
        "shift_type": shift_type,
        "start_time": start_time,
        "end_time": end_time,
        "report_time": report_time,
        "current_time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "is_during_shift": is_during_shift(),
    }


def get_all_bc_emails() -> str:
    """Get comma-separated list of all battalion chief emails."""
    return ",".join([bc["email"] for bc in BATTALION_CHIEFS.values()])


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_daily_report(shift: str = None, date: datetime.date = None) -> Dict[str, Any]:
    """
    Generate daily shift report data.

    Returns dict with:
        - shift: A or B
        - date: date string
        - incidents: list of incidents with full timeline
        - daily_log: list of daily log entries
        - issues_found: list of entries with issues
        - stats: summary statistics
    """
    if shift is None:
        shift = get_current_shift()
    if date is None:
        date = datetime.date.today()

    start_dt, end_dt = get_shift_date_range(shift, date)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()

    # Get incidents for this shift with more detail
    incidents = conn.execute("""
        SELECT
            i.incident_id,
            i.incident_number,
            i.type,
            i.location,
            i.caller_name,
            i.narrative,
            i.status,
            i.priority,
            i.final_disposition,
            i.issue_found,
            i.created,
            i.updated,
            i.closed_at
        FROM Incidents i
        WHERE i.created >= ? AND i.created < ?
        ORDER BY i.created ASC
    """, (start_str, end_str)).fetchall()

    # Get unit assignments for each incident (for response times)
    incident_ids = [row["incident_id"] for row in incidents]
    unit_assignments = {}
    if incident_ids:
        placeholders = ",".join("?" * len(incident_ids))
        assignments = conn.execute(f"""
            SELECT
                ua.incident_id,
                ua.unit_id,
                ua.commanding_unit,
                ua.dispatched,
                ua.enroute,
                ua.arrived,
                ua.transporting,
                ua.at_medical,
                ua.cleared,
                ua.disposition
            FROM UnitAssignments ua
            WHERE ua.incident_id IN ({placeholders})
            ORDER BY ua.dispatched ASC
        """, incident_ids).fetchall()

        for ua in assignments:
            inc_id = ua["incident_id"]
            if inc_id not in unit_assignments:
                unit_assignments[inc_id] = []
            unit_assignments[inc_id].append(dict(ua))

    # Get narrative entries for each incident
    narratives = {}
    if incident_ids:
        placeholders = ",".join("?" * len(incident_ids))
        narr_rows = conn.execute(f"""
            SELECT incident_id, user, timestamp, text
            FROM Narrative
            WHERE incident_id IN ({placeholders})
            ORDER BY timestamp ASC
        """, incident_ids).fetchall()

        for n in narr_rows:
            inc_id = n["incident_id"]
            if inc_id not in narratives:
                narratives[inc_id] = []
            narratives[inc_id].append(dict(n))

    # Get daily log entries for this shift
    daily_log = conn.execute("""
        SELECT
            d.id,
            d.event_type as category,
            d.unit_id,
            d.details,
            d.issue_found,
            d.incident_id,
            d.timestamp,
            d.user as created_by
        FROM DailyLog d
        WHERE d.timestamp >= ? AND d.timestamp < ?
        ORDER BY d.timestamp ASC
    """, (start_str, end_str)).fetchall()

    # Get units that worked this shift (from assignments)
    units_on_shift = []
    if incident_ids:
        placeholders = ",".join("?" * len(incident_ids))
        units_on_shift = conn.execute(f"""
            SELECT DISTINCT ua.unit_id, u.name, u.unit_type
            FROM UnitAssignments ua
            LEFT JOIN Units u ON u.unit_id = ua.unit_id
            WHERE ua.incident_id IN ({placeholders})
        """, incident_ids).fetchall()

    # Get MasterLog entries for comprehensive activity
    master_log = conn.execute("""
        SELECT
            timestamp,
            user,
            action,
            incident_id,
            unit_id,
            details
        FROM MasterLog
        WHERE timestamp >= ? AND timestamp < ?
        ORDER BY timestamp ASC
    """, (start_str, end_str)).fetchall()

    conn.close()

    # Process data
    incidents_list = []
    for row in incidents:
        inc = dict(row)
        inc["units"] = unit_assignments.get(inc["incident_id"], [])
        inc["remarks"] = narratives.get(inc["incident_id"], [])
        incidents_list.append(inc)

    daily_log_list = [dict(row) for row in daily_log]
    units_list = [dict(row) for row in units_on_shift]
    master_log_list = [dict(row) for row in master_log]

    # Find issues
    issues_found = []
    for inc in incidents_list:
        if inc.get("issue_found") == 1:
            issues_found.append({
                "type": "INCIDENT",
                "id": inc["incident_id"],
                "number": inc.get("incident_number"),
                "description": f"{inc.get('type', '')} at {inc.get('location', '')}",
                "timestamp": inc.get("created")
            })

    for log in daily_log_list:
        if log.get("issue_found") == 1:
            issues_found.append({
                "type": "DAILY_LOG",
                "id": log["id"],
                "category": log.get("category"),
                "description": log.get("details", "")[:100],
                "unit": log.get("unit_id"),
                "timestamp": log.get("timestamp")
            })

    # Calculate stats
    stats = {
        "total_incidents": len(incidents_list),
        "open_incidents": len([i for i in incidents_list if i.get("status") not in ("CLOSED", "CANCELLED")]),
        "closed_incidents": len([i for i in incidents_list if i.get("status") == "CLOSED"]),
        "daily_log_entries": len(daily_log_list),
        "issues_found": len(issues_found),
        "units_active": len(units_list),
        "total_activity_log": len(master_log_list),
        "incidents_by_type": {},
        "daily_log_by_category": {},
    }

    for inc in incidents_list:
        t = inc.get("type", "UNKNOWN")
        stats["incidents_by_type"][t] = stats["incidents_by_type"].get(t, 0) + 1

    for log in daily_log_list:
        c = log.get("category", "UNKNOWN")
        stats["daily_log_by_category"][c] = stats["daily_log_by_category"].get(c, 0) + 1

    return {
        "shift": shift,
        "date": date.isoformat(),
        "start_time": start_dt.strftime("%H:%M"),
        "end_time": end_dt.strftime("%H:%M"),
        "incidents": incidents_list,
        "daily_log": daily_log_list,
        "master_log": master_log_list,
        "issues_found": issues_found,
        "units": units_list,
        "stats": stats,
        "generated_at": datetime.datetime.now().isoformat(),
        "report_type": "final",  # Always end-of-shift report
    }


def format_report_text(report: Dict[str, Any]) -> str:
    """Format report as plain text."""
    lines = []
    lines.append("=" * 70)
    lines.append("FORD FIRE DEPARTMENT - DAILY ACTIVITY REPORT")
    lines.append("=" * 70)
    lines.append(f"Shift: {report['shift']} | Date: {report['date']}")
    lines.append(f"Period: {report['start_time']} - {report['end_time']}")
    report_type = "INTERIM REPORT" if report.get("report_type") == "interim" else "END OF SHIFT REPORT"
    lines.append(f"Type: {report_type}")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    # Summary stats
    stats = report["stats"]
    lines.append("-" * 50)
    lines.append("SUMMARY")
    lines.append("-" * 50)
    lines.append(f"Total Incidents:    {stats['total_incidents']}")
    lines.append(f"  - Open:           {stats['open_incidents']}")
    lines.append(f"  - Closed:         {stats['closed_incidents']}")
    lines.append(f"Daily Log Entries:  {stats['daily_log_entries']}")
    lines.append(f"Issues Flagged:     {stats['issues_found']}")
    lines.append(f"Units Active:       {stats['units_active']}")
    lines.append("")

    # Incidents by type
    if stats["incidents_by_type"]:
        lines.append("Incidents by Type:")
        for t, count in sorted(stats["incidents_by_type"].items(), key=lambda x: (x[0] is None, x[0] or "")):
            lines.append(f"  {t or 'Unknown'}: {count}")
        lines.append("")

    # Issues Found (highlighted)
    if report["issues_found"]:
        lines.append("-" * 50)
        lines.append("*** ISSUES FLAGGED FOR REVIEW ***")
        lines.append("-" * 50)
        for issue in report["issues_found"]:
            lines.append(f"  [{issue['type']}] {issue.get('number') or issue.get('category', 'N/A')}")
            lines.append(f"    {issue['description']}")
            if issue.get("unit"):
                lines.append(f"    Unit: {issue['unit']}")
            lines.append(f"    Time: {issue['timestamp']}")
            lines.append("")

    # Incidents with full timeline
    lines.append("-" * 50)
    lines.append("INCIDENT DETAIL")
    lines.append("-" * 50)
    if report["incidents"]:
        for inc in report["incidents"]:
            issue_flag = " *** ISSUE ***" if inc.get("issue_found") == 1 else ""
            lines.append(f"\n  INCIDENT #{inc.get('incident_number', inc['incident_id'])}{issue_flag}")
            lines.append(f"  {'-' * 40}")
            lines.append(f"    Type:      {inc.get('type', 'N/A')}")
            lines.append(f"    Location:  {inc.get('location', 'N/A')}")
            lines.append(f"    Status:    {inc.get('status', 'N/A')}")
            if inc.get("final_disposition") or inc.get("disposition"):
                lines.append(f"    Dispo:     {inc.get('final_disposition') or inc.get('disposition')}")
            lines.append(f"    Created:   {inc.get('created', 'N/A')}")
            if inc.get("closed_at"):
                lines.append(f"    Closed:    {inc.get('closed_at')}")

            # Unit assignments with times
            if inc.get("units"):
                lines.append("")
                lines.append("    UNITS ASSIGNED:")
                for ua in inc["units"]:
                    cmd_flag = " (CMD)" if ua.get("commanding_unit") == 1 else ""
                    lines.append(f"      {ua['unit_id']}{cmd_flag}")
                    if ua.get("dispatched"):
                        lines.append(f"        Dispatched:   {ua['dispatched']}")
                    if ua.get("enroute"):
                        lines.append(f"        Enroute:      {ua['enroute']}")
                    if ua.get("arrived"):
                        lines.append(f"        Arrived:      {ua['arrived']}")
                    if ua.get("transporting"):
                        lines.append(f"        Transporting: {ua['transporting']}")
                    if ua.get("at_medical"):
                        lines.append(f"        At Medical:   {ua['at_medical']}")
                    if ua.get("cleared"):
                        lines.append(f"        Cleared:      {ua['cleared']}")
                    if ua.get("disposition"):
                        lines.append(f"        Disposition:  {ua['disposition']}")

            # Remarks/Narrative
            if inc.get("remarks"):
                lines.append("")
                lines.append("    REMARKS:")
                for r in inc["remarks"]:
                    lines.append(f"      [{r.get('timestamp', '')}] {r.get('user', '')}: {r.get('text', '')}")

            lines.append("")
    else:
        lines.append("  No incidents during this shift.")
        lines.append("")

    # Daily Log
    lines.append("-" * 50)
    lines.append("DAILY LOG ENTRIES")
    lines.append("-" * 50)
    if report["daily_log"]:
        for log in report["daily_log"]:
            issue_flag = " *** ISSUE ***" if log.get("issue_found") == 1 else ""
            lines.append(f"  [{log.get('timestamp', '')}] {log.get('category', 'ENTRY')}{issue_flag}")
            lines.append(f"    Unit: {log.get('unit_id', 'N/A')}")
            lines.append(f"    {log.get('details', '')}")
            lines.append("")
    else:
        lines.append("  No daily log entries during this shift.")
        lines.append("")

    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)
    lines.append("")
    lines.append("This report was automatically generated by FORD CAD System.")
    lines.append("For questions, contact the dispatch supervisor.")

    return "\n".join(lines)


def format_report_html(report: Dict[str, Any]) -> str:
    """Format report as HTML email."""
    report_type = "Interim Report" if report.get("report_type") == "interim" else "End of Shift Report"

    # Build issues section
    issues_html = ""
    if report["issues_found"]:
        issues_rows = ""
        for issue in report["issues_found"]:
            issues_rows += f"""
            <tr style="background:#fff5f5;">
                <td style="padding:8px;border:1px solid #e5e7eb;">{issue['type']}</td>
                <td style="padding:8px;border:1px solid #e5e7eb;">{issue.get('number') or issue.get('category', 'N/A')}</td>
                <td style="padding:8px;border:1px solid #e5e7eb;">{issue['description']}</td>
                <td style="padding:8px;border:1px solid #e5e7eb;">{issue.get('unit', '-')}</td>
                <td style="padding:8px;border:1px solid #e5e7eb;">{issue['timestamp']}</td>
            </tr>
            """
        issues_html = f"""
        <div style="background:#fef2f2;border:2px solid #dc2626;border-radius:8px;padding:15px;margin:20px 0;">
            <h2 style="color:#dc2626;margin-top:0;">Issues Flagged for Review ({len(report['issues_found'])})</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr style="background:#fecaca;">
                    <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Type</th>
                    <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">ID</th>
                    <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Description</th>
                    <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Unit</th>
                    <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Time</th>
                </tr>
                {issues_rows}
            </table>
        </div>
        """

    # Build incidents section
    incidents_html = ""
    for inc in report["incidents"]:
        bg = "background:#fff5f5;" if inc.get("issue_found") == 1 else ""
        issue_badge = '<span style="background:#dc2626;color:white;padding:2px 6px;border-radius:4px;font-size:11px;margin-left:8px;">ISSUE</span>' if inc.get("issue_found") == 1 else ""

        # Unit assignments
        units_html = ""
        if inc.get("units"):
            units_rows = ""
            for ua in inc["units"]:
                cmd_flag = '<span style="background:#1e40af;color:white;padding:1px 4px;border-radius:3px;font-size:10px;">CMD</span> ' if ua.get("commanding_unit") == 1 else ""
                units_rows += f"""
                <tr>
                    <td style="padding:4px 8px;border:1px solid #e5e7eb;">{cmd_flag}{ua['unit_id']}</td>
                    <td style="padding:4px 8px;border:1px solid #e5e7eb;">{ua.get('dispatched', '-')}</td>
                    <td style="padding:4px 8px;border:1px solid #e5e7eb;">{ua.get('enroute', '-')}</td>
                    <td style="padding:4px 8px;border:1px solid #e5e7eb;">{ua.get('arrived', '-')}</td>
                    <td style="padding:4px 8px;border:1px solid #e5e7eb;">{ua.get('cleared', '-')}</td>
                    <td style="padding:4px 8px;border:1px solid #e5e7eb;">{ua.get('disposition', '-')}</td>
                </tr>
                """
            units_html = f"""
            <table style="width:100%;border-collapse:collapse;margin-top:10px;font-size:12px;">
                <tr style="background:#f3f4f6;">
                    <th style="padding:4px 8px;border:1px solid #e5e7eb;text-align:left;">Unit</th>
                    <th style="padding:4px 8px;border:1px solid #e5e7eb;text-align:left;">Dispatched</th>
                    <th style="padding:4px 8px;border:1px solid #e5e7eb;text-align:left;">Enroute</th>
                    <th style="padding:4px 8px;border:1px solid #e5e7eb;text-align:left;">Arrived</th>
                    <th style="padding:4px 8px;border:1px solid #e5e7eb;text-align:left;">Cleared</th>
                    <th style="padding:4px 8px;border:1px solid #e5e7eb;text-align:left;">Dispo</th>
                </tr>
                {units_rows}
            </table>
            """

        # Remarks
        remarks_html = ""
        if inc.get("remarks"):
            remarks_items = ""
            for r in inc["remarks"]:
                remarks_items += f'<div style="margin:4px 0;padding:4px 8px;background:#f9fafb;border-radius:4px;font-size:12px;"><strong>{r.get("user", "")}</strong> ({r.get("timestamp", "")}): {r.get("text", "")}</div>'
            remarks_html = f'<div style="margin-top:10px;"><strong>Remarks:</strong>{remarks_items}</div>'

        incidents_html += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:15px;margin-bottom:15px;{bg}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <h3 style="margin:0;color:#1e40af;">#{inc.get('incident_number', inc['incident_id'])}{issue_badge}</h3>
                <span style="background:#e5e7eb;padding:4px 8px;border-radius:4px;font-size:12px;">{inc.get('status', 'N/A')}</span>
            </div>
            <table style="width:100%;font-size:13px;">
                <tr><td style="width:100px;color:#6b7280;">Type:</td><td><strong>{inc.get('type', 'N/A')}</strong></td></tr>
                <tr><td style="color:#6b7280;">Location:</td><td>{inc.get('location', 'N/A')}</td></tr>
                <tr><td style="color:#6b7280;">Created:</td><td>{inc.get('created', 'N/A')}</td></tr>
                {'<tr><td style="color:#6b7280;">Closed:</td><td>' + inc.get('closed_at', '') + '</td></tr>' if inc.get('closed_at') else ''}
                {'<tr><td style="color:#6b7280;">Disposition:</td><td>' + (inc.get('final_disposition') or inc.get('disposition', '')) + '</td></tr>' if inc.get('final_disposition') or inc.get('disposition') else ''}
            </table>
            {units_html}
            {remarks_html}
        </div>
        """

    if not report["incidents"]:
        incidents_html = '<p style="text-align:center;color:#6b7280;padding:20px;">No incidents during this shift.</p>'

    # Daily log section
    daily_log_html = ""
    if report["daily_log"]:
        for log in report["daily_log"]:
            bg = "background:#fff5f5;" if log.get("issue_found") == 1 else ""
            issue_badge = '<span style="background:#dc2626;color:white;padding:1px 4px;border-radius:3px;font-size:10px;margin-left:5px;">ISSUE</span>' if log.get("issue_found") == 1 else ""
            daily_log_html += f"""
            <tr style="{bg}">
                <td style="padding:8px;border:1px solid #e5e7eb;">{log.get('timestamp', '')}</td>
                <td style="padding:8px;border:1px solid #e5e7eb;">{log.get('category', 'ENTRY')}{issue_badge}</td>
                <td style="padding:8px;border:1px solid #e5e7eb;">{log.get('unit_id', '-')}</td>
                <td style="padding:8px;border:1px solid #e5e7eb;">{log.get('details', '')}</td>
            </tr>
            """
    else:
        daily_log_html = '<tr><td colspan="4" style="padding:20px;text-align:center;color:#6b7280;">No daily log entries during this shift.</td></tr>'

    stats = report["stats"]

    # Build type breakdown
    type_breakdown = ""
    for t, count in sorted(stats.get("incidents_by_type", {}).items(), key=lambda x: (x[0] is None, x[0] or "")):
        type_breakdown += f'<span style="background:#e5e7eb;padding:2px 8px;border-radius:4px;margin-right:5px;font-size:12px;">{t or "Unknown"}: {count}</span>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily Activity Report - {report['shift']} Shift - {report['date']}</title>
    </head>
    <body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;background:#f9fafb;">
        <div style="background:white;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);overflow:hidden;">
            <!-- Header -->
            <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;padding:25px;">
                <h1 style="margin:0;font-size:24px;">Ford Fire Department</h1>
                <p style="margin:5px 0 0;opacity:0.9;font-size:16px;">Daily Activity Report - {report_type}</p>
            </div>

            <div style="padding:25px;">
                <!-- Meta info -->
                <div style="display:flex;gap:20px;margin-bottom:20px;flex-wrap:wrap;">
                    <div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;">
                        <strong>Shift:</strong> {report['shift']}
                    </div>
                    <div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;">
                        <strong>Date:</strong> {report['date']}
                    </div>
                    <div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;">
                        <strong>Period:</strong> {report['start_time']} - {report['end_time']}
                    </div>
                    <div style="background:#f3f4f6;padding:10px 15px;border-radius:6px;">
                        <strong>Generated:</strong> {report['generated_at'][:19]}
                    </div>
                </div>

                <!-- Stats boxes -->
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:25px;">
                    <div style="background:#eff6ff;border:1px solid #bfdbfe;padding:15px;border-radius:8px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:#1e40af;">{stats['total_incidents']}</div>
                        <div style="font-size:12px;color:#6b7280;">Total Incidents</div>
                    </div>
                    <div style="background:#f0fdf4;border:1px solid #bbf7d0;padding:15px;border-radius:8px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:#16a34a;">{stats['closed_incidents']}</div>
                        <div style="font-size:12px;color:#6b7280;">Closed</div>
                    </div>
                    <div style="background:#fefce8;border:1px solid #fef08a;padding:15px;border-radius:8px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:#ca8a04;">{stats['daily_log_entries']}</div>
                        <div style="font-size:12px;color:#6b7280;">Daily Log</div>
                    </div>
                    <div style="background:{'#fef2f2' if stats['issues_found'] > 0 else '#f3f4f6'};border:1px solid {'#fecaca' if stats['issues_found'] > 0 else '#e5e7eb'};padding:15px;border-radius:8px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:{'#dc2626' if stats['issues_found'] > 0 else '#6b7280'};">{stats['issues_found']}</div>
                        <div style="font-size:12px;color:#6b7280;">Issues</div>
                    </div>
                </div>

                <!-- Type breakdown -->
                {f'<div style="margin-bottom:20px;"><strong>By Type:</strong> {type_breakdown}</div>' if type_breakdown else ''}

                {issues_html}

                <!-- Incidents -->
                <h2 style="color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:10px;margin-top:30px;">
                    Incidents ({len(report['incidents'])})
                </h2>
                {incidents_html}

                <!-- Daily Log -->
                <h2 style="color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:10px;margin-top:30px;">
                    Daily Log ({len(report['daily_log'])})
                </h2>
                <table style="width:100%;border-collapse:collapse;">
                    <tr style="background:#f3f4f6;">
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Time</th>
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Category</th>
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Unit</th>
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Details</th>
                    </tr>
                    {daily_log_html}
                </table>

                <!-- Footer -->
                <div style="margin-top:30px;padding-top:20px;border-top:1px solid #e5e7eb;text-align:center;color:#6b7280;font-size:12px;">
                    <p>This report was automatically generated by FORD CAD System.</p>
                    <p>Distributed to: Battalion Chiefs 1-4</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return html


# ---------------------------------------------------------------------------
# Email Sending
# ---------------------------------------------------------------------------

def send_email_sendgrid(
    to: str,
    subject: str,
    body_text: str,
    body_html: str = None,
) -> bool:
    """
    Send email via SendGrid Web API.
    """
    import urllib.request
    import urllib.error

    api_key = CONFIG.get("sendgrid_api_key", "")
    if not api_key:
        print("[REPORTS] SendGrid API key not configured")
        return False

    from_email = CONFIG.get("smtp_from", "noreply@fordcad.local")
    # Extract just the email address if it's in "Name <email>" format
    if "<" in from_email:
        from_email = from_email.split("<")[1].replace(">", "").strip()

    # Parse recipients
    recipients = [r.strip() for r in to.split(",") if r.strip()]

    # Build personalizations
    personalizations = [{
        "to": [{"email": r} for r in recipients]
    }]

    # Build content
    content = [{"type": "text/plain", "value": body_text}]
    if body_html:
        content.append({"type": "text/html", "value": body_html})

    payload = {
        "personalizations": personalizations,
        "from": {"email": from_email},
        "subject": subject,
        "content": content
    }

    try:
        print(f"[REPORTS] SendGrid: Sending to {recipients}")
        print(f"[REPORTS] SendGrid: From {from_email}")
        print(f"[REPORTS] SendGrid: API key starts with {api_key[:20]}...")

        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            print(f"[REPORTS] SendGrid response: {status}")

        print(f"[REPORTS] Email sent via SendGrid to {len(recipients)} recipient(s)")
        return True

    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"[REPORTS] SendGrid HTTP error {e.code}: {error_body}")
        return False
    except Exception as e:
        print(f"[REPORTS] SendGrid exception: {type(e).__name__}: {e}")
        return False


def send_email_smtp(
    to: str,
    subject: str,
    body_text: str,
    body_html: str = None,
    attachments: List[tuple] = None
) -> bool:
    """
    Send email via SMTP.
    """
    if not CONFIG["smtp_user"] or not CONFIG["smtp_pass"]:
        print("[REPORTS] SMTP not configured")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = CONFIG["smtp_from"] or CONFIG["smtp_user"]
        msg["To"] = to

        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        if attachments:
            for filename, content in attachments:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={filename}")
                msg.attach(part)

        recipients = [r.strip() for r in to.split(",") if r.strip()]

        if CONFIG["smtp_use_tls"]:
            server = smtplib.SMTP(CONFIG["smtp_host"], CONFIG["smtp_port"])
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(CONFIG["smtp_host"], CONFIG["smtp_port"])

        server.login(CONFIG["smtp_user"], CONFIG["smtp_pass"])
        server.sendmail(msg["From"], recipients, msg.as_string())
        server.quit()

        print(f"[REPORTS] Email sent via SMTP to {len(recipients)} recipient(s)")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print(f"[REPORTS] SMTP auth failed: {e}")
        return False
    except Exception as e:
        print(f"[REPORTS] SMTP failed: {e}")
        return False


def send_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str = None,
    attachments: List[tuple] = None
) -> bool:
    """
    Send email - uses SendGrid if configured, otherwise SMTP.
    """
    # Prefer SendGrid if API key is set
    if CONFIG.get("sendgrid_api_key"):
        return send_email_sendgrid(to, subject, body_text, body_html)

    # Fall back to SMTP
    return send_email_smtp(to, subject, body_text, body_html, attachments)


# ---------------------------------------------------------------------------
# SMS via Carrier Gateways
# ---------------------------------------------------------------------------

def send_sms(phone: str, carrier: str, message: str) -> bool:
    """Send SMS via carrier email-to-SMS gateway."""
    phone = "".join(c for c in phone if c.isdigit())

    if carrier not in SMS_GATEWAYS:
        print(f"[REPORTS] Unknown carrier: {carrier}. Available: {list(SMS_GATEWAYS.keys())}")
        return False

    gateway_email = f"{phone}{SMS_GATEWAYS[carrier]}"

    if len(message) > 160:
        message = message[:157] + "..."

    return send_email(
        to=gateway_email,
        subject="",
        body_text=message
    )


# ---------------------------------------------------------------------------
# Signal Messaging
# ---------------------------------------------------------------------------

def send_signal(recipient: str, message: str) -> bool:
    """Send Signal message using signal-cli."""
    if not CONFIG["signal_sender"]:
        print("[REPORTS] Signal sender not configured. Set CAD_SIGNAL_SENDER.")
        return False

    try:
        cmd = [
            CONFIG["signal_cli_path"],
            "-u", CONFIG["signal_sender"],
            "send",
            "-m", message,
            recipient
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            print(f"[REPORTS] Signal message sent to {recipient}")
            return True
        else:
            print(f"[REPORTS] Signal failed: {result.stderr}")
            return False

    except FileNotFoundError:
        print(f"[REPORTS] signal-cli not found at {CONFIG['signal_cli_path']}")
        return False
    except subprocess.TimeoutExpired:
        print("[REPORTS] Signal command timed out")
        return False
    except Exception as e:
        print(f"[REPORTS] Signal failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Report Sending
# ---------------------------------------------------------------------------

def send_daily_report_to_battalion_chiefs(
    shift: str = None,
    date: datetime.date = None
) -> Dict[str, Any]:
    """
    Generate and send daily shift report to all battalion chiefs.

    Returns:
        Dict with send results
    """
    # Generate report
    report = generate_daily_report(shift, date)
    text_report = format_report_text(report)
    html_report = format_report_html(report)

    # Get all BC emails
    all_emails = get_all_bc_emails()

    report_type = "Interim" if report.get("report_type") == "interim" else "End of Shift"
    subject = f"[FORD CAD] {report_type} Report - {report['shift']} Shift - {report['date']} {datetime.datetime.now().strftime('%H:%M')}"

    result = {
        "success": False,
        "recipients": all_emails,
        "report_type": report_type,
        "shift": report["shift"],
        "date": report["date"],
        "stats": report["stats"],
        "error": None,
    }

    # Send email
    try:
        success = send_email(
            to=all_emails,
            subject=subject,
            body_text=text_report,
            body_html=html_report
        )
        result["success"] = success
        if not success:
            result["error"] = "Email send returned False"
    except Exception as e:
        result["error"] = str(e)
        print(f"[REPORTS] Failed to send report: {e}")

    return result


def send_daily_report(
    shift: str = None,
    date: datetime.date = None,
    email: str = None,
    signal_number: str = None,
    sms_phone: str = None,
    sms_carrier: str = None
) -> Dict[str, bool]:
    """
    Generate and send daily shift report (legacy function for API compatibility).
    """
    report = generate_daily_report(shift, date)
    text_report = format_report_text(report)
    html_report = format_report_html(report)

    results = {
        "email": False,
        "signal": False,
        "sms": False,
    }

    # Send email
    email_to = email or get_all_bc_emails()
    if email_to:
        report_type = "Interim" if report.get("report_type") == "interim" else "End of Shift"
        subject = f"[FORD CAD] {report_type} Report - {report['shift']} Shift - {report['date']}"
        results["email"] = send_email(
            to=email_to,
            subject=subject,
            body_text=text_report,
            body_html=html_report
        )

    # Send Signal
    if signal_number:
        summary = f"FORD CAD Daily Report - {report['shift']} Shift\n"
        summary += f"Date: {report['date']}\n"
        summary += f"Incidents: {report['stats']['total_incidents']}\n"
        summary += f"Issues: {report['stats']['issues_found']}\n"
        if report["issues_found"]:
            summary += "\nISSUES FOUND - Check email for details."
        results["signal"] = send_signal(signal_number, summary)

    # Send SMS
    if sms_phone and sms_carrier:
        summary = f"CAD Report {report['shift']}: {report['stats']['total_incidents']} inc, {report['stats']['issues_found']} issues"
        results["sms"] = send_sms(sms_phone, sms_carrier, summary)

    return results


# ---------------------------------------------------------------------------
# Automatic Report Scheduler
# ---------------------------------------------------------------------------

def get_next_report_time() -> Optional[datetime.datetime]:
    """Get the next scheduled report time based on current time."""
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute

    # Determine which shift we're in
    if 6 <= hour < 18:
        # A shift: reports every 30 min from 0600-1730
        shift_end_hour = 17
        shift_end_minute = 30
    else:
        # B shift: reports every 30 min from 1800-0530
        if hour >= 18:
            # Evening portion
            shift_end_hour = 5
            shift_end_minute = 30
        else:
            # Morning portion (0-6)
            shift_end_hour = 5
            shift_end_minute = 30

    # Calculate next 30-minute mark
    if minute < 30:
        next_minute = 30
        next_hour = hour
    else:
        next_minute = 0
        next_hour = (hour + 1) % 24

    next_time = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)

    # Check if we've passed end of shift
    current_shift = get_current_shift()
    if current_shift == "A":
        end_time = now.replace(hour=17, minute=30, second=0, microsecond=0)
        if now > end_time:
            return None  # Past end of A shift
    else:
        # B shift - ends at 05:30 next day
        if 18 <= hour <= 23:
            end_time = (now + datetime.timedelta(days=1)).replace(hour=5, minute=30, second=0, microsecond=0)
        else:
            end_time = now.replace(hour=5, minute=30, second=0, microsecond=0)
        if now > end_time and hour < 18:
            return None  # Past end of B shift

    return next_time


def should_send_report_now() -> bool:
    """
    Check if it's time to send the end-of-shift report.

    Only ONE report per shift:
    - Day shifts (A/C): 1730 (30 min before end at 1800)
    - Night shifts (B/D): 0530 (30 min before end at 0600)
    """
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute

    # Day shift report time: 17:30
    if hour == 17 and minute == 30:
        return True

    # Night shift report time: 05:30
    if hour == 5 and minute == 30:
        return True

    return False


# ---------------------------------------------------------------------------
# Pending Report Confirmation System
# ---------------------------------------------------------------------------

def create_pending_report(shift: str = None) -> dict:
    """
    Create a pending report that awaits confirmation before sending.
    Returns the pending report info.
    """
    global _pending_report

    if shift is None:
        shift = get_current_shift()

    report = generate_daily_report(shift)
    now = datetime.datetime.now()

    with _pending_report_lock:
        _pending_report = {
            "id": f"{now.strftime('%Y%m%d%H%M%S')}",
            "created_at": now.isoformat(),
            "expires_at": (now + datetime.timedelta(seconds=CONFIRMATION_TIMEOUT_SECONDS)).isoformat(),
            "shift": shift,
            "report_type": report.get("report_type", "interim"),
            "stats": report["stats"],
            "recipients": get_all_bc_emails(),
            "status": "pending",  # pending, confirmed, cancelled, expired, sent
        }
        print(f"[REPORTS] Pending report created - awaiting confirmation ({CONFIRMATION_TIMEOUT_SECONDS}s timeout)")
        return _pending_report.copy()


def get_pending_report() -> Optional[dict]:
    """Get the current pending report if any."""
    global _pending_report

    with _pending_report_lock:
        if _pending_report is None:
            return None

        # Check if expired
        expires_at = datetime.datetime.fromisoformat(_pending_report["expires_at"])
        now = datetime.datetime.now()

        if now > expires_at and _pending_report["status"] == "pending":
            _pending_report["status"] = "expired"

        # Calculate remaining time
        remaining = max(0, (expires_at - now).total_seconds())
        result = _pending_report.copy()
        result["remaining_seconds"] = int(remaining)

        return result


def confirm_pending_report() -> dict:
    """Confirm and send the pending report."""
    global _pending_report

    with _pending_report_lock:
        if _pending_report is None:
            return {"ok": False, "error": "No pending report"}

        if _pending_report["status"] != "pending" and _pending_report["status"] != "expired":
            return {"ok": False, "error": f"Report already {_pending_report['status']}"}

        shift = _pending_report["shift"]
        _pending_report["status"] = "sending"

    # Send the report (outside the lock)
    print(f"[REPORTS] Report confirmed - sending to battalion chiefs...")
    result = send_daily_report_to_battalion_chiefs(shift=shift)

    with _pending_report_lock:
        if result["success"]:
            _pending_report["status"] = "sent"
            _pending_report["sent_at"] = datetime.datetime.now().isoformat()
            print(f"[REPORTS] Report sent successfully")
        else:
            _pending_report["status"] = "failed"
            _pending_report["error"] = result.get("error", "Unknown error")
            print(f"[REPORTS] Report send failed: {result.get('error')}")

        return {"ok": result["success"], "result": _pending_report.copy()}


def cancel_pending_report() -> dict:
    """Cancel the pending report."""
    global _pending_report

    with _pending_report_lock:
        if _pending_report is None:
            return {"ok": False, "error": "No pending report"}

        if _pending_report["status"] != "pending":
            return {"ok": False, "error": f"Report already {_pending_report['status']}"}

        _pending_report["status"] = "cancelled"
        _pending_report["cancelled_at"] = datetime.datetime.now().isoformat()
        print(f"[REPORTS] Pending report cancelled by user")

        return {"ok": True, "message": "Report cancelled"}


def clear_pending_report():
    """Clear the pending report state."""
    global _pending_report
    with _pending_report_lock:
        _pending_report = None


def process_expired_report():
    """Check if pending report has expired and auto-send if so."""
    global _pending_report

    with _pending_report_lock:
        if _pending_report is None:
            return

        if _pending_report["status"] != "pending":
            return

        expires_at = datetime.datetime.fromisoformat(_pending_report["expires_at"])
        now = datetime.datetime.now()

        if now <= expires_at:
            return  # Not expired yet

        # Expired - auto-send
        shift = _pending_report["shift"]
        _pending_report["status"] = "auto-sending"
        print(f"[REPORTS] Confirmation timeout - auto-sending report...")

    # Send outside lock
    result = send_daily_report_to_battalion_chiefs(shift=shift)

    with _pending_report_lock:
        if _pending_report and _pending_report["status"] == "auto-sending":
            if result["success"]:
                _pending_report["status"] = "sent"
                _pending_report["sent_at"] = datetime.datetime.now().isoformat()
                _pending_report["auto_sent"] = True
                print(f"[REPORTS] Report auto-sent successfully (timeout)")
            else:
                _pending_report["status"] = "failed"
                _pending_report["error"] = result.get("error", "Unknown error")


def run_scheduler():
    """
    Run report scheduler in a loop.
    Creates pending reports every 30 minutes during shift hours.
    Reports require confirmation (or auto-send after 30 second timeout).
    """
    global _scheduler_running, _pending_report
    _scheduler_running = True

    print("[REPORTS] Scheduler started - end-of-shift reports only")
    print("[REPORTS] Day shifts (A/C): 1730 | Night shifts (B/D): 0530")
    print(f"[REPORTS] Battalion Chiefs: {', '.join(BATTALION_CHIEFS.keys())}")
    print(f"[REPORTS] Confirmation timeout: {CONFIRMATION_TIMEOUT_SECONDS} seconds")

    last_pending_key = None

    while _scheduler_running:
        try:
            now = datetime.datetime.now()
            current_key = f"{now.date()}_{now.hour}_{now.minute // 30}"

            # Check for expired pending reports and auto-send
            process_expired_report()

            # Check if we need to create a new pending report
            if should_send_report_now() and current_key != last_pending_key:
                # Check if there's already a pending report
                pending = get_pending_report()
                if pending and pending["status"] == "pending":
                    # Still waiting for confirmation on previous report
                    pass
                elif pending and pending["status"] in ("sent", "cancelled", "failed"):
                    # Previous report handled, clear it and create new
                    clear_pending_report()
                    shift = get_current_shift()
                    print(f"[REPORTS] Creating pending {shift} shift report at {now.strftime('%H:%M')}...")
                    create_pending_report(shift)
                    last_pending_key = current_key
                else:
                    # No pending report, create one
                    shift = get_current_shift()
                    print(f"[REPORTS] Creating pending {shift} shift report at {now.strftime('%H:%M')}...")
                    create_pending_report(shift)
                    last_pending_key = current_key

            time.sleep(5)  # Check every 5 seconds for faster confirmation response

        except Exception as e:
            print(f"[REPORTS] Scheduler error: {e}")
            time.sleep(10)


def start_scheduler():
    """Start the report scheduler in a background thread."""
    global _scheduler_thread, _scheduler_running

    if _scheduler_thread and _scheduler_thread.is_alive():
        print("[REPORTS] Scheduler already running")
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    _scheduler_thread.start()
    print("[REPORTS] Scheduler thread started")


def stop_scheduler():
    """Stop the report scheduler."""
    global _scheduler_running
    _scheduler_running = False
    print("[REPORTS] Scheduler stopped")


# ---------------------------------------------------------------------------
# API Endpoints (to be registered in main.py)
# ---------------------------------------------------------------------------

def register_report_routes(app):
    """Register report routes with FastAPI app."""
    from fastapi import BackgroundTasks, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    @app.get("/api/reports/daily")
    async def api_get_daily_report(shift: str = None):
        """Get daily report data as JSON."""
        report = generate_daily_report(shift)
        return JSONResponse(content=report)

    @app.get("/api/reports/daily/html")
    async def api_get_daily_report_html(shift: str = None):
        """Get daily report as HTML."""
        report = generate_daily_report(shift)
        html = format_report_html(report)
        return HTMLResponse(content=html)

    @app.get("/api/reports/daily/text")
    async def api_get_daily_report_text(shift: str = None):
        """Get daily report as plain text."""
        report = generate_daily_report(shift)
        text = format_report_text(report)
        return HTMLResponse(content=f"<pre>{text}</pre>")

    @app.post("/api/reports/send")
    async def api_send_report(
        background_tasks: BackgroundTasks,
        shift: str = None,
        email: str = None,
    ):
        """Send daily report via email to all battalion chiefs."""
        background_tasks.add_task(
            send_daily_report_to_battalion_chiefs,
            shift=shift,
        )
        return {"ok": True, "message": "Report send initiated", "recipients": get_all_bc_emails()}

    @app.post("/api/reports/send/test")
    async def api_send_test_report(email: str):
        """Send test report to a single email address."""
        report = generate_daily_report()
        text_report = format_report_text(report)
        html_report = format_report_html(report)

        success = send_email(
            to=email,
            subject=f"[TEST] FORD CAD Daily Report - {report['shift']} Shift",
            body_text=text_report,
            body_html=html_report
        )
        return {"ok": success, "email": email}

    @app.post("/api/reports/config/email")
    async def api_configure_email(request: Request):
        """Configure email settings."""
        data = await request.json()
        smtp_user = data.get("smtp_user", "").strip()
        smtp_pass = data.get("smtp_pass", "").strip()

        if smtp_user:
            CONFIG["smtp_user"] = smtp_user
        if smtp_pass:
            CONFIG["smtp_pass"] = smtp_pass

        # Save to config file
        save_email_config(CONFIG["smtp_user"], CONFIG["smtp_pass"])

        return {"ok": True, "message": "Email config updated"}

    @app.get("/api/reports/config")
    async def api_get_report_config():
        """Get current report configuration."""
        return {
            "smtp_configured": bool(CONFIG["smtp_user"] and CONFIG["smtp_pass"]),
            "smtp_user": CONFIG["smtp_user"],
            "smtp_from": CONFIG["smtp_from"],
            "battalion_chiefs": BATTALION_CHIEFS,
            "auto_report_enabled": CONFIG["auto_report_enabled"],
            "report_interval_minutes": CONFIG["report_interval_minutes"],
            "scheduler_running": _scheduler_running,
        }

    @app.get("/api/shift")
    async def api_get_current_shift():
        """Get current shift information for display."""
        return get_shift_info()

    # -----------------------------------------------------------------------
    # Pending Report Confirmation Endpoints
    # -----------------------------------------------------------------------

    @app.get("/api/reports/pending")
    async def api_get_pending_report():
        """
        Get pending report status.
        Poll this endpoint to check for reports awaiting confirmation.
        """
        pending = get_pending_report()
        if pending:
            return {"ok": True, "pending": True, "report": pending}
        return {"ok": True, "pending": False, "report": None}

    @app.post("/api/reports/pending/confirm")
    async def api_confirm_pending_report():
        """Confirm and send the pending report."""
        result = confirm_pending_report()
        return result

    @app.post("/api/reports/pending/cancel")
    async def api_cancel_pending_report():
        """Cancel the pending report (skip this scheduled send)."""
        result = cancel_pending_report()
        return result

    @app.post("/api/reports/pending/clear")
    async def api_clear_pending_report():
        """Clear the pending report state."""
        clear_pending_report()
        return {"ok": True, "message": "Pending report cleared"}

    @app.post("/api/reports/pending/create")
    async def api_create_pending_report():
        """Manually create a pending report (triggers confirmation modal)."""
        # Check if there's already a pending report
        existing = get_pending_report()
        if existing and existing["status"] == "pending":
            return {"ok": False, "error": "A report is already pending confirmation"}

        # Clear any old completed/cancelled reports
        clear_pending_report()

        # Create new pending report
        shift = get_current_shift()
        report = create_pending_report(shift)
        return {"ok": True, "message": "Report created - awaiting confirmation", "report": report}

    @app.get("/api/reports/battalion_chiefs")
    async def api_get_battalion_chiefs():
        """Get battalion chief list."""
        return {"battalion_chiefs": BATTALION_CHIEFS}

    @app.post("/api/reports/scheduler/start")
    async def api_start_scheduler():
        """Start the automatic report scheduler."""
        start_scheduler()
        return {"ok": True, "message": "Scheduler started"}

    @app.post("/api/reports/scheduler/stop")
    async def api_stop_scheduler():
        """Stop the automatic report scheduler."""
        stop_scheduler()
        return {"ok": True, "message": "Scheduler stopped"}

    @app.post("/api/message/email")
    async def api_send_email(request: Request):
        """Send email."""
        data = await request.json()
        to = data.get("to", "")
        subject = data.get("subject", "")
        body = data.get("body", "")
        success = send_email(to, subject, body)
        return {"ok": success}

    @app.post("/api/message/signal")
    async def api_send_signal(request: Request):
        """Send Signal message."""
        data = await request.json()
        to = data.get("to", "")
        message = data.get("message", "")
        success = send_signal(to, message)
        return {"ok": success}

    @app.post("/api/message/sms")
    async def api_send_sms(request: Request):
        """Send SMS via carrier gateway."""
        data = await request.json()
        phone = data.get("phone", "")
        carrier = data.get("carrier", "")
        message = data.get("message", "")
        success = send_sms(phone, carrier, message)
        return {"ok": success}

    @app.get("/api/message/carriers")
    async def api_get_carriers():
        """Get available SMS carrier gateways."""
        return {"carriers": list(SMS_GATEWAYS.keys())}


# ---------------------------------------------------------------------------
# Auto-start scheduler if enabled
# ---------------------------------------------------------------------------

def init_reports():
    """Initialize reports module - call from main.py startup."""
    load_email_config()
    # Auto-scheduler disabled - use manual "Send Report" button or REPORT command
    # To enable: set auto_report_enabled to true in config or call start_scheduler()
    if CONFIG.get("auto_report_enabled") and CONFIG.get("auto_report_enabled") != "false":
        start_scheduler()
    else:
        print("[REPORTS] Auto-scheduler disabled - use manual Send Report")


if __name__ == "__main__":
    # Test report generation
    print("Generating test report...")
    report = generate_daily_report()
    print(format_report_text(report))
