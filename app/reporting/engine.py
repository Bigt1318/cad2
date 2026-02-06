# ============================================================================
# FORD CAD - Report Generation Engine
# ============================================================================
# Generates various report types with data from the CAD database.
# ============================================================================

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import get_config, get_local_now, format_time_for_display, get_timezone
from .models import (
    ScheduleRepository,
    RecipientRepository,
    HistoryRepository,
    DeliveryLogRepository,
    ReportHistoryEntry,
    get_db,
)
from .delivery import EmailDelivery, SMSDelivery, WebhookDelivery, DeliveryResult

# Import shift logic
try:
    from shift_logic import get_current_shift, get_shift_for_date, BATTALION_CHIEFS
except ImportError:
    BATTALION_CHIEFS = {}
    def get_current_shift(dt=None):
        if dt is None:
            dt = datetime.now()
        hour = dt.hour
        return "A" if 6 <= hour < 18 else "B"
    def get_shift_for_date(date=None):
        return ("A", "B")

logger = logging.getLogger("reporting.engine")
EASTERN = ZoneInfo('America/New_York')
DB_PATH = Path("cad.db")


class ReportEngine:
    """
    Report generation and delivery engine.

    Supports multiple report types:
    - shift_end: End-of-shift summary
    - daily_summary: 24-hour summary
    - weekly: Weekly analytics
    - custom: Custom date range
    """

    def __init__(self):
        self.email_delivery = EmailDelivery()
        self.sms_delivery = SMSDelivery()
        self.webhook_delivery = WebhookDelivery()

    def generate_report(
        self,
        report_type: str = "shift_end",
        shift: str = None,
        date: datetime = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> Dict[str, Any]:
        """Generate a report based on type."""
        if report_type == "shift_end":
            return self._generate_shift_end_report(shift, date)
        elif report_type == "daily_summary":
            return self._generate_daily_summary(date)
        elif report_type == "weekly":
            return self._generate_weekly_report(end_date)
        elif report_type == "custom":
            return self._generate_custom_report(start_date, end_date)
        else:
            return self._generate_shift_end_report(shift, date)

    def _get_db_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_shift_date_range(self, shift: str, date: datetime = None) -> tuple:
        """Get start and end datetime for a shift."""
        if date is None:
            date = get_local_now()

        current_date = date.date() if hasattr(date, 'date') else date

        # Day shift: 06:00 - 18:00
        # Night shift: 18:00 - 06:00 next day
        if shift in ("A", "C"):
            # Day shift
            start = datetime.combine(current_date, datetime.strptime("06:00", "%H:%M").time())
            end = datetime.combine(current_date, datetime.strptime("18:00", "%H:%M").time())
        else:
            # Night shift
            hour = date.hour if hasattr(date, 'hour') else 12
            if hour < 6:
                # Early morning - shift started yesterday
                start = datetime.combine(current_date - timedelta(days=1), datetime.strptime("18:00", "%H:%M").time())
                end = datetime.combine(current_date, datetime.strptime("06:00", "%H:%M").time())
            else:
                # Evening - shift ends tomorrow morning
                start = datetime.combine(current_date, datetime.strptime("18:00", "%H:%M").time())
                end = datetime.combine(current_date + timedelta(days=1), datetime.strptime("06:00", "%H:%M").time())

        return start, end

    def _generate_shift_end_report(
        self,
        shift: str = None,
        date: datetime = None,
    ) -> Dict[str, Any]:
        """Generate shift end report."""
        if shift is None:
            shift = get_current_shift(get_local_now())
        if date is None:
            date = get_local_now()

        start_dt, end_dt = self._get_shift_date_range(shift, date)
        start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_db_connection()

        # Get incidents
        incidents = conn.execute("""
            SELECT
                incident_id, incident_number, type, location,
                caller_name, narrative, status, priority,
                final_disposition, issue_found, created, updated, closed_at
            FROM Incidents
            WHERE created >= ? AND created < ?
            ORDER BY created ASC
        """, (start_str, end_str)).fetchall()

        # Get unit assignments
        incident_ids = [row["incident_id"] for row in incidents]
        unit_assignments = {}

        if incident_ids:
            placeholders = ",".join("?" * len(incident_ids))
            assignments = conn.execute(f"""
                SELECT
                    incident_id, unit_id, commanding_unit,
                    dispatched, enroute, arrived, transporting,
                    at_medical, cleared, disposition
                FROM UnitAssignments
                WHERE incident_id IN ({placeholders})
                ORDER BY dispatched ASC
            """, incident_ids).fetchall()

            for ua in assignments:
                inc_id = ua["incident_id"]
                if inc_id not in unit_assignments:
                    unit_assignments[inc_id] = []
                unit_assignments[inc_id].append(dict(ua))

        # Get daily log
        daily_log = conn.execute("""
            SELECT
                id, event_type as category, unit_id, details,
                issue_found, incident_id, timestamp, user as created_by
            FROM DailyLog
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
        """, (start_str, end_str)).fetchall()

        conn.close()

        # Process incidents
        incidents_list = []
        issues_found = []

        for row in incidents:
            inc = dict(row)
            inc["units"] = unit_assignments.get(inc["incident_id"], [])
            incidents_list.append(inc)

            if inc.get("issue_found") == 1:
                issues_found.append({
                    "type": "INCIDENT",
                    "id": inc["incident_id"],
                    "number": inc.get("incident_number"),
                    "description": f"{inc.get('type', '')} at {inc.get('location', '')}",
                    "timestamp": inc.get("created"),
                })

        daily_log_list = [dict(row) for row in daily_log]

        for log in daily_log_list:
            if log.get("issue_found") == 1:
                issues_found.append({
                    "type": "DAILY_LOG",
                    "id": log["id"],
                    "category": log.get("category"),
                    "description": log.get("details", "")[:100],
                    "timestamp": log.get("timestamp"),
                })

        # Calculate stats
        stats = {
            "total_incidents": len(incidents_list),
            "open_incidents": len([i for i in incidents_list if i.get("status") not in ("CLOSED", "CANCELLED")]),
            "closed_incidents": len([i for i in incidents_list if i.get("status") == "CLOSED"]),
            "daily_log_entries": len(daily_log_list),
            "issues_found": len(issues_found),
            "incidents_by_type": {},
        }

        for inc in incidents_list:
            t = inc.get("type", "UNKNOWN")
            stats["incidents_by_type"][t] = stats["incidents_by_type"].get(t, 0) + 1

        # Get battalion chief info
        bc_info = BATTALION_CHIEFS.get(shift, {})

        return {
            "report_type": "shift_end",
            "shift": shift,
            "date": date.strftime("%Y-%m-%d"),
            "start_time": start_dt.strftime("%H:%M"),
            "end_time": end_dt.strftime("%H:%M"),
            "timezone": str(get_timezone()),
            "battalion_chief": bc_info.get("name", "Unknown"),
            "incidents": incidents_list,
            "daily_log": daily_log_list,
            "issues_found": issues_found,
            "stats": stats,
            "generated_at": format_time_for_display(),
        }

    def _generate_daily_summary(self, date: datetime = None) -> Dict[str, Any]:
        """Generate 24-hour summary report."""
        if date is None:
            date = get_local_now()

        start = date - timedelta(days=1)
        return self._generate_shift_end_report(shift="ALL", date=date)

    def _generate_weekly_report(self, end_date: datetime = None) -> Dict[str, Any]:
        """Generate weekly analytics report."""
        if end_date is None:
            end_date = get_local_now()

        start_date = end_date - timedelta(days=7)

        # This would include trend analysis, charts data, etc.
        return {
            "report_type": "weekly",
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "generated_at": format_time_for_display(),
        }

    def _generate_custom_report(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """Generate custom date range report."""
        return {
            "report_type": "custom",
            "start_date": start_date.strftime("%Y-%m-%d %H:%M"),
            "end_date": end_date.strftime("%Y-%m-%d %H:%M"),
            "generated_at": format_time_for_display(),
        }

    def format_report_html(self, report: Dict[str, Any]) -> str:
        """Format report as HTML email."""
        report_type = report.get("report_type", "shift_end")

        if report_type == "shift_end":
            return self._format_shift_end_html(report)
        else:
            return self._format_generic_html(report)

    def _format_shift_end_html(self, report: Dict[str, Any]) -> str:
        """Format shift end report as HTML."""
        stats = report.get("stats", {})
        issues = report.get("issues_found", [])

        # Build issues section
        issues_html = ""
        if issues:
            issues_rows = ""
            for issue in issues:
                issues_rows += f"""
                <tr style="background:#fff5f5;">
                    <td style="padding:8px;border:1px solid #e5e7eb;">{issue.get('timestamp', '-')}</td>
                    <td style="padding:8px;border:1px solid #e5e7eb;">{issue['type']}</td>
                    <td style="padding:8px;border:1px solid #e5e7eb;">{issue.get('number') or issue.get('id', '-')}</td>
                    <td style="padding:8px;border:1px solid #e5e7eb;">{issue['description']}</td>
                </tr>
                """
            issues_html = f"""
            <div style="background:#fef2f2;border:2px solid #dc2626;border-radius:8px;padding:15px;margin:20px 0;">
                <h2 style="color:#dc2626;margin-top:0;">Issues Flagged for Review ({len(issues)})</h2>
                <table style="width:100%;border-collapse:collapse;">
                    <tr style="background:#fecaca;">
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Time</th>
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Type</th>
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">ID</th>
                        <th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">Description</th>
                    </tr>
                    {issues_rows}
                </table>
            </div>
            """

        # Build incidents section
        incidents_html = ""
        for inc in report.get("incidents", []):
            has_issue = inc.get("issue_found") == 1
            bg = "background:#fff5f5;" if has_issue else ""
            issue_badge = '<span style="background:#dc2626;color:white;padding:2px 6px;border-radius:4px;font-size:11px;margin-left:8px;">ISSUE</span>' if has_issue else ""

            incidents_html += f"""
            <div style="border:1px solid #e5e7eb;border-radius:8px;padding:15px;margin-bottom:15px;{bg}">
                <div style="display:flex;justify-content:space-between;margin-bottom:10px;">
                    <h3 style="margin:0;color:#1e40af;">#{inc.get('incident_number', inc['incident_id'])} {issue_badge}</h3>
                    <span style="background:#e5e7eb;padding:4px 8px;border-radius:4px;font-size:12px;">{inc.get('status', 'N/A')}</span>
                </div>
                <table style="width:100%;font-size:13px;">
                    <tr><td style="width:100px;color:#6b7280;">Type:</td><td><strong>{inc.get('type', 'N/A')}</strong></td></tr>
                    <tr><td style="color:#6b7280;">Location:</td><td>{inc.get('location', 'N/A')}</td></tr>
                    <tr><td style="color:#6b7280;">Created:</td><td>{inc.get('created', 'N/A')}</td></tr>
                </table>
            </div>
            """

        if not report.get("incidents"):
            incidents_html = '<p style="text-align:center;color:#6b7280;padding:20px;">No incidents during this shift.</p>'

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Shift End Report - {report['shift']} Shift</title>
        </head>
        <body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;background:#f9fafb;">
            <div style="background:white;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);overflow:hidden;">
                <!-- Header -->
                <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);color:white;padding:25px;">
                    <h1 style="margin:0;font-size:24px;">Ford Fire Department</h1>
                    <p style="margin:5px 0 0;opacity:0.9;font-size:16px;">End of Shift Report</p>
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
                            <strong>BC:</strong> {report.get('battalion_chief', 'N/A')}
                        </div>
                    </div>

                    <!-- Stats boxes -->
                    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:25px;">
                        <div style="background:#eff6ff;border:1px solid #bfdbfe;padding:15px;border-radius:8px;text-align:center;">
                            <div style="font-size:28px;font-weight:bold;color:#1e40af;">{stats.get('total_incidents', 0)}</div>
                            <div style="font-size:12px;color:#6b7280;">Total Incidents</div>
                        </div>
                        <div style="background:#f0fdf4;border:1px solid #bbf7d0;padding:15px;border-radius:8px;text-align:center;">
                            <div style="font-size:28px;font-weight:bold;color:#16a34a;">{stats.get('closed_incidents', 0)}</div>
                            <div style="font-size:12px;color:#6b7280;">Closed</div>
                        </div>
                        <div style="background:#fefce8;border:1px solid #fef08a;padding:15px;border-radius:8px;text-align:center;">
                            <div style="font-size:28px;font-weight:bold;color:#ca8a04;">{stats.get('daily_log_entries', 0)}</div>
                            <div style="font-size:12px;color:#6b7280;">Daily Log</div>
                        </div>
                        <div style="background:{'#fef2f2' if stats.get('issues_found', 0) > 0 else '#f3f4f6'};border:1px solid {'#fecaca' if stats.get('issues_found', 0) > 0 else '#e5e7eb'};padding:15px;border-radius:8px;text-align:center;">
                            <div style="font-size:28px;font-weight:bold;color:{'#dc2626' if stats.get('issues_found', 0) > 0 else '#6b7280'};">{stats.get('issues_found', 0)}</div>
                            <div style="font-size:12px;color:#6b7280;">Issues</div>
                        </div>
                    </div>

                    {issues_html}

                    <!-- Incidents -->
                    <h2 style="color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:10px;margin-top:30px;">
                        Incidents ({len(report.get('incidents', []))})
                    </h2>
                    {incidents_html}

                    <!-- Footer -->
                    <div style="margin-top:30px;padding-top:20px;border-top:1px solid #e5e7eb;text-align:center;color:#6b7280;font-size:12px;">
                        <p>Generated: {report.get('generated_at', '')}</p>
                        <p>This report was automatically generated by FORD CAD System.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _format_generic_html(self, report: Dict[str, Any]) -> str:
        """Format generic report as HTML."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>Report</title></head>
        <body style="font-family:Arial,sans-serif;padding:20px;">
            <h1>FORD CAD Report</h1>
            <p>Report Type: {report.get('report_type', 'unknown')}</p>
            <p>Generated: {report.get('generated_at', '')}</p>
        </body>
        </html>
        """

    def format_report_text(self, report: Dict[str, Any]) -> str:
        """Format report as plain text."""
        lines = []
        lines.append("=" * 70)
        lines.append("FORD FIRE DEPARTMENT - SHIFT END REPORT")
        lines.append("=" * 70)
        lines.append(f"Shift: {report.get('shift')} | Date: {report.get('date')}")
        lines.append(f"Period: {report.get('start_time')} - {report.get('end_time')}")
        lines.append(f"Battalion Chief: {report.get('battalion_chief', 'N/A')}")
        lines.append(f"Generated: {report.get('generated_at', '')}")
        lines.append("")

        stats = report.get("stats", {})
        lines.append("-" * 50)
        lines.append("SUMMARY")
        lines.append("-" * 50)
        lines.append(f"Total Incidents:    {stats.get('total_incidents', 0)}")
        lines.append(f"  - Closed:         {stats.get('closed_incidents', 0)}")
        lines.append(f"Daily Log Entries:  {stats.get('daily_log_entries', 0)}")
        lines.append(f"Issues Flagged:     {stats.get('issues_found', 0)}")
        lines.append("")

        if report.get("issues_found"):
            lines.append("-" * 50)
            lines.append("*** ISSUES FLAGGED FOR REVIEW ***")
            lines.append("-" * 50)
            for issue in report["issues_found"]:
                lines.append(f"  [{issue['type']}] {issue.get('number') or issue.get('id', 'N/A')}")
                lines.append(f"    {issue['description']}")
                lines.append("")

        lines.append("=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)

        return "\n".join(lines)

    def send_report(
        self,
        schedule_id: int = None,
        shift: str = None,
        triggered_by: str = "manual",
        triggered_by_user: str = None,
    ) -> Dict[str, Any]:
        """Generate and send a report."""
        now = get_local_now()

        # Determine shift if not specified
        if shift is None:
            shift = get_current_shift(now)

        # Generate report
        report = self.generate_report(report_type="shift_end", shift=shift)

        # Format report
        html_report = self.format_report_html(report)
        text_report = self.format_report_text(report)

        # Get recipients
        recipients = RecipientRepository.get_by_shift(shift)

        # If no specific recipients, get all enabled
        if not recipients:
            recipients = RecipientRepository.get_all()
            recipients = [r for r in recipients if r.enabled]

        # Create history entry
        history_entry = ReportHistoryEntry(
            schedule_id=schedule_id,
            report_type="shift_end",
            shift=shift,
            status="sending",
            recipients_count=len(recipients),
            triggered_by=triggered_by,
            triggered_by_user=triggered_by_user,
        )
        history_id = HistoryRepository.create(history_entry)
        HistoryRepository.save_report_data(history_id, report)

        # Send to each recipient
        successful = 0
        failed = 0
        errors = []

        subject = f"[FORD CAD] Shift End Report - {shift} Shift - {report['date']}"

        for recipient in recipients:
            # Create delivery log entry
            log_id = DeliveryLogRepository.create(
                history_id=history_id,
                recipient=recipient.destination,
                name=recipient.name,
                channel=recipient.recipient_type,
            )

            # Send based on channel type
            if recipient.recipient_type == "email":
                result = self.email_delivery.send(
                    recipient=recipient.destination,
                    subject=subject,
                    body_text=text_report,
                    body_html=html_report,
                )
            elif recipient.recipient_type == "sms":
                result = self.sms_delivery.send(
                    recipient=recipient.destination,
                    subject=subject,
                    body_text=f"FORD CAD: {shift} Shift Report - {report['stats']['total_incidents']} incidents, {report['stats']['issues_found']} issues",
                )
            elif recipient.recipient_type == "webhook":
                result = self.webhook_delivery.send(
                    recipient=recipient.destination,
                    subject=subject,
                    body_text=text_report,
                )
            else:
                result = DeliveryResult(
                    success=False,
                    recipient=recipient.destination,
                    channel=recipient.recipient_type,
                    error=f"Unknown channel type: {recipient.recipient_type}",
                )

            # Update delivery log
            DeliveryLogRepository.update_status(
                log_id=log_id,
                status="sent" if result.success else "failed",
                error=result.error,
            )

            if result.success:
                successful += 1
            else:
                failed += 1
                errors.append(result.error)

        # Update history
        final_status = "sent" if failed == 0 else ("partial" if successful > 0 else "failed")
        HistoryRepository.update_status(
            history_id=history_id,
            status=final_status,
            successful=successful,
            failed=failed,
            error="; ".join(errors) if errors else None,
        )

        logger.info(
            f"Report sent: shift={shift}, recipients={len(recipients)}, "
            f"successful={successful}, failed={failed}"
        )

        return {
            "ok": successful > 0,
            "history_id": history_id,
            "shift": shift,
            "recipients": len(recipients),
            "successful": successful,
            "failed": failed,
            "errors": errors if errors else None,
        }


# Global engine instance
_engine: Optional[ReportEngine] = None


def get_engine() -> ReportEngine:
    """Get the global report engine instance."""
    global _engine
    if _engine is None:
        _engine = ReportEngine()
    return _engine
