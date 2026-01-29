# ============================================================================
# FORD CAD — Daily Reporting & Messaging System
# ============================================================================
# Features:
#   - Daily shift reports (30 min before shift change)
#   - Email (SMTP, not Outlook)
#   - Signal messaging (via signal-cli)
#   - SMS via carrier email-to-SMS gateways
# ============================================================================

import sqlite3
import datetime
import smtplib
import subprocess
import os
import json
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
    # SMTP Settings
    "smtp_host": os.getenv("CAD_SMTP_HOST", "smtp.gmail.com"),
    "smtp_port": int(os.getenv("CAD_SMTP_PORT", "587")),
    "smtp_user": os.getenv("CAD_SMTP_USER", ""),
    "smtp_pass": os.getenv("CAD_SMTP_PASS", ""),
    "smtp_from": os.getenv("CAD_SMTP_FROM", ""),
    "smtp_use_tls": os.getenv("CAD_SMTP_TLS", "true").lower() == "true",

    # Signal CLI path (install signal-cli separately)
    "signal_cli_path": os.getenv("CAD_SIGNAL_CLI", "signal-cli"),
    "signal_sender": os.getenv("CAD_SIGNAL_SENDER", ""),  # Your registered Signal number

    # Database
    "db_path": os.getenv("CAD_DB_PATH", "cad.db"),

    # Report recipients
    "battalion_chief_email": os.getenv("CAD_BC_EMAIL", ""),
    "battalion_chief_phone": os.getenv("CAD_BC_PHONE", ""),  # For Signal/SMS
    "battalion_chief_signal": os.getenv("CAD_BC_SIGNAL", ""),  # Signal number

    # Shift times
    "shift_a_start": 6,   # 0600
    "shift_a_end": 18,    # 1800
    "shift_b_start": 18,  # 1800
    "shift_b_end": 6,     # 0600
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


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(CONFIG["db_path"])
    conn.row_factory = sqlite3.Row
    return conn


def get_current_shift() -> str:
    """Determine current shift letter."""
    hour = datetime.datetime.now().hour
    return "A" if 6 <= hour < 18 else "B"


def get_shift_date_range(shift: str, date: datetime.date = None) -> tuple:
    """Get start and end datetime for a shift on given date."""
    if date is None:
        date = datetime.date.today()

    if shift == "A":
        start = datetime.datetime.combine(date, datetime.time(6, 0, 0))
        end = datetime.datetime.combine(date, datetime.time(18, 0, 0))
    else:  # B shift
        start = datetime.datetime.combine(date, datetime.time(18, 0, 0))
        end = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(6, 0, 0))

    return start, end


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_daily_report(shift: str = None, date: datetime.date = None) -> Dict[str, Any]:
    """
    Generate daily shift report data.

    Returns dict with:
        - shift: A or B
        - date: date string
        - incidents: list of incidents
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

    # Get incidents for this shift
    incidents = conn.execute("""
        SELECT
            i.incident_id,
            i.incident_number,
            i.type,
            i.subtype,
            i.location,
            i.caller_name,
            i.narrative,
            i.status,
            i.priority,
            i.disposition,
            i.issue_found,
            i.created,
            i.updated
        FROM Incidents i
        WHERE i.created >= ? AND i.created < ?
        ORDER BY i.created ASC
    """, (start_str, end_str)).fetchall()

    # Get daily log entries for this shift
    daily_log = conn.execute("""
        SELECT
            d.id,
            d.category,
            d.unit_id,
            d.details,
            d.issue_found,
            d.incident_id,
            d.timestamp,
            d.created_by
        FROM DailyLog d
        WHERE d.timestamp >= ? AND d.timestamp < ?
        ORDER BY d.timestamp ASC
    """, (start_str, end_str)).fetchall()

    # Get units that worked this shift
    units_on_shift = conn.execute("""
        SELECT DISTINCT u.unit_id, u.name, u.unit_type
        FROM UnitStatus us
        JOIN Units u ON u.unit_id = us.unit_id
        WHERE us.timestamp >= ? AND us.timestamp < ?
    """, (start_str, end_str)).fetchall()

    conn.close()

    # Process data
    incidents_list = [dict(row) for row in incidents]
    daily_log_list = [dict(row) for row in daily_log]
    units_list = [dict(row) for row in units_on_shift]

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
        "daily_log_entries": len(daily_log_list),
        "issues_found": len(issues_found),
        "units_active": len(units_list),
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
        "issues_found": issues_found,
        "units": units_list,
        "stats": stats,
        "generated_at": datetime.datetime.now().isoformat(),
    }


def format_report_text(report: Dict[str, Any]) -> str:
    """Format report as plain text."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"FORD FIRE DEPARTMENT - DAILY SHIFT REPORT")
    lines.append("=" * 60)
    lines.append(f"Shift: {report['shift']} | Date: {report['date']}")
    lines.append(f"Period: {report['start_time']} - {report['end_time']}")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    # Summary stats
    stats = report["stats"]
    lines.append("-" * 40)
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"Total Incidents: {stats['total_incidents']}")
    lines.append(f"Daily Log Entries: {stats['daily_log_entries']}")
    lines.append(f"Issues Found: {stats['issues_found']}")
    lines.append(f"Units Active: {stats['units_active']}")
    lines.append("")

    # Issues Found (highlighted)
    if report["issues_found"]:
        lines.append("-" * 40)
        lines.append("*** ISSUES FOUND ***")
        lines.append("-" * 40)
        for issue in report["issues_found"]:
            lines.append(f"  [{issue['type']}] {issue.get('number') or issue.get('category', 'N/A')}")
            lines.append(f"    {issue['description']}")
            if issue.get("unit"):
                lines.append(f"    Unit: {issue['unit']}")
            lines.append(f"    Time: {issue['timestamp']}")
            lines.append("")

    # Incidents
    lines.append("-" * 40)
    lines.append("INCIDENTS")
    lines.append("-" * 40)
    if report["incidents"]:
        for inc in report["incidents"]:
            issue_flag = " [ISSUE]" if inc.get("issue_found") == 1 else ""
            lines.append(f"  #{inc.get('incident_number', inc['incident_id'])}{issue_flag}")
            lines.append(f"    Type: {inc.get('type', 'N/A')}")
            lines.append(f"    Location: {inc.get('location', 'N/A')}")
            lines.append(f"    Status: {inc.get('status', 'N/A')}")
            lines.append(f"    Time: {inc.get('created', 'N/A')}")
            lines.append("")
    else:
        lines.append("  No incidents during this shift.")
        lines.append("")

    # Daily Log
    lines.append("-" * 40)
    lines.append("DAILY LOG")
    lines.append("-" * 40)
    if report["daily_log"]:
        for log in report["daily_log"]:
            issue_flag = " [ISSUE]" if log.get("issue_found") == 1 else ""
            lines.append(f"  {log.get('category', 'ENTRY')}{issue_flag}")
            lines.append(f"    Unit: {log.get('unit_id', 'N/A')}")
            lines.append(f"    Details: {log.get('details', '')[:80]}")
            lines.append(f"    Time: {log.get('timestamp', 'N/A')}")
            lines.append("")
    else:
        lines.append("  No daily log entries during this shift.")
        lines.append("")

    lines.append("=" * 60)
    lines.append("END OF REPORT")
    lines.append("=" * 60)

    return "\n".join(lines)


def format_report_html(report: Dict[str, Any]) -> str:
    """Format report as HTML."""
    issues_html = ""
    if report["issues_found"]:
        issues_rows = ""
        for issue in report["issues_found"]:
            issues_rows += f"""
            <tr style="background:#fff5f5;">
                <td>{issue['type']}</td>
                <td>{issue.get('number') or issue.get('category', 'N/A')}</td>
                <td>{issue['description']}</td>
                <td>{issue.get('unit', '-')}</td>
                <td>{issue['timestamp']}</td>
            </tr>
            """
        issues_html = f"""
        <h2 style="color:#dc2626;">Issues Found ({len(report['issues_found'])})</h2>
        <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
            <tr style="background:#fef2f2;"><th>Type</th><th>ID</th><th>Description</th><th>Unit</th><th>Time</th></tr>
            {issues_rows}
        </table>
        """

    incidents_rows = ""
    for inc in report["incidents"]:
        bg = "background:#fff5f5;" if inc.get("issue_found") == 1 else ""
        issue_badge = '<span style="color:#dc2626;font-weight:bold;">[ISSUE]</span>' if inc.get("issue_found") == 1 else ""
        incidents_rows += f"""
        <tr style="{bg}">
            <td>#{inc.get('incident_number', inc['incident_id'])} {issue_badge}</td>
            <td>{inc.get('type', 'N/A')}</td>
            <td>{inc.get('location', 'N/A')}</td>
            <td>{inc.get('status', 'N/A')}</td>
            <td>{inc.get('created', 'N/A')}</td>
        </tr>
        """

    daily_log_rows = ""
    for log in report["daily_log"]:
        bg = "background:#fff5f5;" if log.get("issue_found") == 1 else ""
        issue_badge = '<span style="color:#dc2626;font-weight:bold;">[ISSUE]</span>' if log.get("issue_found") == 1 else ""
        daily_log_rows += f"""
        <tr style="{bg}">
            <td>{log.get('category', 'ENTRY')} {issue_badge}</td>
            <td>{log.get('unit_id', 'N/A')}</td>
            <td>{log.get('details', '')[:100]}</td>
            <td>{log.get('timestamp', 'N/A')}</td>
        </tr>
        """

    stats = report["stats"]

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Daily Shift Report - {report['shift']} Shift - {report['date']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
            h1 {{ color: #1e40af; border-bottom: 2px solid #1e40af; padding-bottom: 10px; }}
            h2 {{ color: #374151; margin-top: 30px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }}
            th {{ background: #f3f4f6; font-weight: 600; }}
            .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
            .stat-box {{ background: #f3f4f6; padding: 15px; border-radius: 8px; text-align: center; }}
            .stat-value {{ font-size: 24px; font-weight: bold; color: #1e40af; }}
            .stat-label {{ font-size: 12px; color: #6b7280; margin-top: 5px; }}
            .issue-alert {{ background: #fef2f2; border: 1px solid #fecaca; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <h1>Ford Fire Department - Daily Shift Report</h1>
        <p><strong>Shift:</strong> {report['shift']} | <strong>Date:</strong> {report['date']} | <strong>Period:</strong> {report['start_time']} - {report['end_time']}</p>
        <p><em>Generated: {report['generated_at']}</em></p>

        <div class="stats">
            <div class="stat-box">
                <div class="stat-value">{stats['total_incidents']}</div>
                <div class="stat-label">Total Incidents</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{stats['daily_log_entries']}</div>
                <div class="stat-label">Daily Log Entries</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" style="color:#dc2626;">{stats['issues_found']}</div>
                <div class="stat-label">Issues Found</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{stats['units_active']}</div>
                <div class="stat-label">Units Active</div>
            </div>
        </div>

        {issues_html}

        <h2>Incidents ({len(report['incidents'])})</h2>
        <table>
            <tr><th>Incident #</th><th>Type</th><th>Location</th><th>Status</th><th>Time</th></tr>
            {incidents_rows if incidents_rows else '<tr><td colspan="5" style="text-align:center;opacity:0.5;">No incidents during this shift.</td></tr>'}
        </table>

        <h2>Daily Log ({len(report['daily_log'])})</h2>
        <table>
            <tr><th>Category</th><th>Unit</th><th>Details</th><th>Time</th></tr>
            {daily_log_rows if daily_log_rows else '<tr><td colspan="4" style="text-align:center;opacity:0.5;">No daily log entries during this shift.</td></tr>'}
        </table>

        <hr>
        <p style="text-align:center;opacity:0.5;">End of Report</p>
    </body>
    </html>
    """

    return html


# ---------------------------------------------------------------------------
# Email Sending
# ---------------------------------------------------------------------------

def send_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str = None,
    attachments: List[tuple] = None  # List of (filename, content_bytes)
) -> bool:
    """
    Send email via SMTP (not Outlook).

    Args:
        to: Recipient email address (or comma-separated list)
        subject: Email subject
        body_text: Plain text body
        body_html: Optional HTML body
        attachments: Optional list of (filename, bytes) tuples

    Returns:
        True if sent successfully
    """
    if not CONFIG["smtp_user"] or not CONFIG["smtp_pass"]:
        print("[REPORTS] SMTP not configured. Set CAD_SMTP_USER and CAD_SMTP_PASS.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = CONFIG["smtp_from"] or CONFIG["smtp_user"]
        msg["To"] = to

        # Add plain text
        msg.attach(MIMEText(body_text, "plain"))

        # Add HTML if provided
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        # Add attachments
        if attachments:
            for filename, content in attachments:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={filename}")
                msg.attach(part)

        # Connect and send
        if CONFIG["smtp_use_tls"]:
            server = smtplib.SMTP(CONFIG["smtp_host"], CONFIG["smtp_port"])
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(CONFIG["smtp_host"], CONFIG["smtp_port"])

        server.login(CONFIG["smtp_user"], CONFIG["smtp_pass"])
        server.sendmail(msg["From"], to.split(","), msg.as_string())
        server.quit()

        print(f"[REPORTS] Email sent to {to}")
        return True

    except Exception as e:
        print(f"[REPORTS] Email failed: {e}")
        return False


# ---------------------------------------------------------------------------
# SMS via Carrier Gateways
# ---------------------------------------------------------------------------

def send_sms(phone: str, carrier: str, message: str) -> bool:
    """
    Send SMS via carrier email-to-SMS gateway.

    Args:
        phone: 10-digit phone number (no dashes or spaces)
        carrier: Carrier key (att, verizon, tmobile, etc.)
        message: SMS message (keep under 160 chars for best results)

    Returns:
        True if sent successfully
    """
    phone = "".join(c for c in phone if c.isdigit())

    if carrier not in SMS_GATEWAYS:
        print(f"[REPORTS] Unknown carrier: {carrier}. Available: {list(SMS_GATEWAYS.keys())}")
        return False

    gateway_email = f"{phone}{SMS_GATEWAYS[carrier]}"

    # SMS should be short
    if len(message) > 160:
        message = message[:157] + "..."

    return send_email(
        to=gateway_email,
        subject="",  # SMS gateways ignore subject
        body_text=message
    )


# ---------------------------------------------------------------------------
# Signal Messaging
# ---------------------------------------------------------------------------

def send_signal(recipient: str, message: str) -> bool:
    """
    Send Signal message using signal-cli.

    Requires signal-cli to be installed and configured:
    https://github.com/AsamK/signal-cli

    Args:
        recipient: Phone number in international format (+1XXXXXXXXXX)
        message: Message to send

    Returns:
        True if sent successfully
    """
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
# Scheduled Report Sending
# ---------------------------------------------------------------------------

def send_daily_report(
    shift: str = None,
    date: datetime.date = None,
    email: str = None,
    signal_number: str = None,
    sms_phone: str = None,
    sms_carrier: str = None
) -> Dict[str, bool]:
    """
    Generate and send daily shift report.

    Args:
        shift: A or B (auto-detect if not specified)
        date: Date for report (today if not specified)
        email: Email recipient (uses config if not specified)
        signal_number: Signal recipient (uses config if not specified)
        sms_phone: SMS phone number
        sms_carrier: SMS carrier key

    Returns:
        Dict with send results for each channel
    """
    # Generate report
    report = generate_daily_report(shift, date)
    text_report = format_report_text(report)
    html_report = format_report_html(report)

    results = {
        "email": False,
        "signal": False,
        "sms": False,
    }

    # Send email
    email_to = email or CONFIG["battalion_chief_email"]
    if email_to:
        subject = f"Daily Shift Report - {report['shift']} Shift - {report['date']}"
        results["email"] = send_email(
            to=email_to,
            subject=subject,
            body_text=text_report,
            body_html=html_report
        )

    # Send Signal
    signal_to = signal_number or CONFIG["battalion_chief_signal"]
    if signal_to:
        # Signal message should be shorter
        summary = f"FORD CAD Daily Report - {report['shift']} Shift\n"
        summary += f"Date: {report['date']}\n"
        summary += f"Incidents: {report['stats']['total_incidents']}\n"
        summary += f"Daily Log: {report['stats']['daily_log_entries']}\n"
        summary += f"Issues: {report['stats']['issues_found']}\n"
        if report["issues_found"]:
            summary += "\nISSUES FOUND - Check email for details."

        results["signal"] = send_signal(signal_to, summary)

    # Send SMS
    phone = sms_phone or CONFIG["battalion_chief_phone"]
    if phone and sms_carrier:
        summary = f"CAD Report {report['shift']}: {report['stats']['total_incidents']} inc, {report['stats']['issues_found']} issues"
        results["sms"] = send_sms(phone, sms_carrier, summary)

    return results


def should_send_report_now() -> Optional[str]:
    """
    Check if it's time to send the shift report (30 min before shift change).

    Returns:
        Shift letter to report on, or None if not report time
    """
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute

    # A shift ends at 18:00, so send at 17:30
    if hour == 17 and 25 <= minute <= 35:
        return "A"

    # B shift ends at 06:00, so send at 05:30
    if hour == 5 and 25 <= minute <= 35:
        return "B"

    return None


# ---------------------------------------------------------------------------
# API Endpoints (to be registered in main.py)
# ---------------------------------------------------------------------------

def register_report_routes(app):
    """Register report routes with FastAPI app."""
    from fastapi import BackgroundTasks
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

    @app.post("/api/reports/send")
    async def api_send_report(
        background_tasks: BackgroundTasks,
        shift: str = None,
        email: str = None,
        signal: str = None,
        sms_phone: str = None,
        sms_carrier: str = None
    ):
        """Send daily report via configured channels."""
        background_tasks.add_task(
            send_daily_report,
            shift=shift,
            email=email,
            signal_number=signal,
            sms_phone=sms_phone,
            sms_carrier=sms_carrier
        )
        return {"ok": True, "message": "Report send initiated"}

    @app.post("/api/message/email")
    async def api_send_email(to: str, subject: str, body: str):
        """Send email."""
        success = send_email(to, subject, body)
        return {"ok": success}

    @app.post("/api/message/signal")
    async def api_send_signal(to: str, message: str):
        """Send Signal message."""
        success = send_signal(to, message)
        return {"ok": success}

    @app.post("/api/message/sms")
    async def api_send_sms(phone: str, carrier: str, message: str):
        """Send SMS via carrier gateway."""
        success = send_sms(phone, carrier, message)
        return {"ok": success}

    @app.get("/api/message/carriers")
    async def api_get_carriers():
        """Get available SMS carrier gateways."""
        return {"carriers": list(SMS_GATEWAYS.keys())}


# ---------------------------------------------------------------------------
# Scheduler (run as background thread or separate process)
# ---------------------------------------------------------------------------

def run_scheduler():
    """
    Run report scheduler in a loop.
    Check every minute if it's time to send a report.
    """
    import time

    print("[REPORTS] Scheduler started")
    last_sent = None

    while True:
        try:
            shift = should_send_report_now()

            if shift and shift != last_sent:
                print(f"[REPORTS] Sending {shift} shift report...")
                results = send_daily_report(shift=shift)
                print(f"[REPORTS] Send results: {results}")
                last_sent = shift
            elif not shift:
                last_sent = None

            time.sleep(60)  # Check every minute

        except Exception as e:
            print(f"[REPORTS] Scheduler error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    # Test report generation
    print("Generating test report...")
    report = generate_daily_report()
    print(format_report_text(report))
