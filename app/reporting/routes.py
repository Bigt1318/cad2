# ============================================================================
# FORD CAD - Reporting API Routes (v2)
# ============================================================================
# FastAPI routes for the reporting system.
# ============================================================================

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse

from .config import (
    get_config, set_config, get_all_config,
    get_local_now, format_time_for_display, get_timezone,
    BC_DEFAULTS,
)
from .models import (
    ScheduleRepository, RecipientRepository, HistoryRepository,
    DeliveryLogRepository, AuditRepository,
    Schedule, Recipient,
    init_database,
)
from .scheduler import get_scheduler, init_scheduler
from .engine import get_engine
from .delivery import EmailDelivery

logger = logging.getLogger("reporting.routes")

# Create router
router = APIRouter(prefix="/api/v2/reports", tags=["reports"])


# ============================================================================
# Configuration Endpoints
# ============================================================================

@router.get("/config")
async def get_report_config():
    """Get all report configuration."""
    config = get_all_config()

    # Add computed values
    scheduler = get_scheduler()
    status = scheduler.get_status()

    config["scheduler_status"] = status
    config["current_time"] = format_time_for_display()
    config["timezone_display"] = str(get_timezone())

    # Mask sensitive values
    if config.get("sendgrid_api_key"):
        config["sendgrid_api_key"] = "***configured***"
    if config.get("smtp_pass"):
        config["smtp_pass"] = "***configured***"

    return config


@router.patch("/config")
async def update_report_config(request: Request):
    """Update report configuration."""
    data = await request.json()
    user = request.headers.get("X-User", "admin")

    updated = []
    for key, value in data.items():
        if key in ("sendgrid_api_key", "smtp_pass") and value == "***configured***":
            continue  # Skip if masked value sent back
        set_config(key, value, user=user)
        updated.append(key)

    return {"ok": True, "updated": updated}


@router.get("/config/email")
async def get_email_config():
    """Get email configuration."""
    return {
        "provider": get_config("email_provider", "sendgrid"),
        "sendgrid_configured": bool(get_config("sendgrid_api_key")),
        "smtp_configured": bool(get_config("smtp_user") and get_config("smtp_pass")),
        "from_email": get_config("from_email"),
        "from_name": get_config("from_name"),
    }


@router.put("/config/email")
async def update_email_config(request: Request):
    """Update email configuration."""
    data = await request.json()
    user = request.headers.get("X-User", "admin")

    if "provider" in data:
        set_config("email_provider", data["provider"], user=user)
    if "sendgrid_api_key" in data and data["sendgrid_api_key"]:
        set_config("sendgrid_api_key", data["sendgrid_api_key"], user=user)
    if "from_email" in data:
        set_config("from_email", data["from_email"], user=user)
    if "from_name" in data:
        set_config("from_name", data["from_name"], user=user)
    if "smtp_host" in data:
        set_config("smtp_host", data["smtp_host"], user=user)
    if "smtp_port" in data:
        set_config("smtp_port", int(data["smtp_port"]), user=user)
    if "smtp_user" in data:
        set_config("smtp_user", data["smtp_user"], user=user)
    if "smtp_pass" in data and data["smtp_pass"]:
        set_config("smtp_pass", data["smtp_pass"], user=user)

    return {"ok": True, "message": "Email configuration updated"}


@router.post("/config/email/test")
async def test_email_config(request: Request):
    """Test email configuration by sending a test email."""
    data = await request.json()
    email = data.get("email")

    if not email:
        raise HTTPException(status_code=400, detail="Email address required")

    delivery = EmailDelivery()

    if not delivery.is_configured():
        return {"ok": False, "error": "Email not configured"}

    # Test connection first
    if not delivery.test_connection():
        return {"ok": False, "error": "Failed to connect to email provider"}

    # Send test email
    result = delivery.send(
        recipient=email,
        subject="[FORD CAD] Test Email - Configuration Verified",
        body_text=f"This is a test email from FORD CAD.\n\nConfiguration:\n- Timezone: {get_config('timezone')}\n- Current Time: {format_time_for_display()}\n\nIf you received this, email is configured correctly!",
        body_html=f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #1e40af;">FORD CAD - Test Email</h2>
            <p>This is a test email. If you received this, email is configured correctly!</p>
            <ul>
                <li><strong>Timezone:</strong> {get_config('timezone')}</li>
                <li><strong>Current Time:</strong> {format_time_for_display()}</li>
            </ul>
        </div>
        """,
    )

    if result.success:
        return {"ok": True, "message": f"Test email sent to {email}"}
    else:
        return {"ok": False, "error": result.error}


# ============================================================================
# Schedule Endpoints
# ============================================================================

@router.get("/schedules")
async def list_schedules():
    """List all report schedules."""
    schedules = ScheduleRepository.get_all()
    return {"schedules": [s.to_dict() for s in schedules]}


@router.post("/schedules")
async def create_schedule(request: Request):
    """Create a new report schedule."""
    data = await request.json()
    user = request.headers.get("X-User", "admin")

    schedule = Schedule(
        name=data.get("name", "New Schedule"),
        description=data.get("description", ""),
        report_type=data.get("report_type", "shift_end"),
        schedule_type=data.get("schedule_type", "shift_based"),
        cron_expression=data.get("cron_expression"),
        day_time=data.get("day_time", "17:30"),
        night_time=data.get("night_time", "05:30"),
        timezone=data.get("timezone", "America/New_York"),
        enabled=data.get("enabled", False),
    )

    schedule_id = ScheduleRepository.create(schedule)

    AuditRepository.log(
        action="schedule_created",
        category="schedules",
        user_name=user,
        new_value=str(schedule_id),
        details=f"Created schedule: {schedule.name}",
    )

    # Refresh scheduler
    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True, "id": schedule_id}


@router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: int):
    """Get a specific schedule."""
    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule.to_dict()


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, request: Request):
    """Update a schedule."""
    data = await request.json()
    user = request.headers.get("X-User", "admin")

    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Update fields
    if "name" in data:
        schedule.name = data["name"]
    if "description" in data:
        schedule.description = data["description"]
    if "report_type" in data:
        schedule.report_type = data["report_type"]
    if "schedule_type" in data:
        schedule.schedule_type = data["schedule_type"]
    if "cron_expression" in data:
        schedule.cron_expression = data["cron_expression"]
    if "day_time" in data:
        schedule.day_time = data["day_time"]
    if "night_time" in data:
        schedule.night_time = data["night_time"]
    if "timezone" in data:
        schedule.timezone = data["timezone"]
    if "enabled" in data:
        schedule.enabled = data["enabled"]

    ScheduleRepository.update(schedule)

    AuditRepository.log(
        action="schedule_updated",
        category="schedules",
        user_name=user,
        details=f"Updated schedule {schedule_id}: {schedule.name}",
    )

    # Refresh scheduler
    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request):
    """Delete a schedule."""
    user = request.headers.get("X-User", "admin")

    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    ScheduleRepository.delete(schedule_id)

    AuditRepository.log(
        action="schedule_deleted",
        category="schedules",
        user_name=user,
        details=f"Deleted schedule {schedule_id}: {schedule.name}",
    )

    # Refresh scheduler
    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True}


@router.post("/schedules/{schedule_id}/enable")
async def enable_schedule(schedule_id: int, request: Request):
    """Enable a schedule."""
    user = request.headers.get("X-User", "admin")
    ScheduleRepository.set_enabled(schedule_id, True)

    AuditRepository.log(
        action="schedule_enabled",
        category="schedules",
        user_name=user,
        details=f"Enabled schedule {schedule_id}",
    )

    # Refresh scheduler
    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True, "enabled": True}


@router.post("/schedules/{schedule_id}/disable")
async def disable_schedule(schedule_id: int, request: Request):
    """Disable a schedule."""
    user = request.headers.get("X-User", "admin")
    ScheduleRepository.set_enabled(schedule_id, False)

    AuditRepository.log(
        action="schedule_disabled",
        category="schedules",
        user_name=user,
        details=f"Disabled schedule {schedule_id}",
    )

    # Refresh scheduler
    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True, "enabled": False}


@router.post("/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: int, request: Request, background_tasks: BackgroundTasks):
    """Manually run a schedule (test)."""
    user = request.headers.get("X-User", "admin")

    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Run in background
    engine = get_engine()
    background_tasks.add_task(
        engine.send_report,
        schedule_id=schedule_id,
        triggered_by="manual",
        triggered_by_user=user,
    )

    return {"ok": True, "message": "Report generation started"}


# ============================================================================
# Recipient Endpoints
# ============================================================================

@router.get("/recipients")
async def list_recipients(schedule_id: Optional[int] = None):
    """List all recipients."""
    recipients = RecipientRepository.get_all(schedule_id)
    return {"recipients": [r.to_dict() for r in recipients]}


@router.post("/recipients")
async def create_recipient(request: Request):
    """Create a new recipient."""
    data = await request.json()
    user = request.headers.get("X-User", "admin")

    recipient = Recipient(
        schedule_id=data.get("schedule_id"),
        recipient_type=data.get("recipient_type", "email"),
        destination=data.get("destination", ""),
        name=data.get("name", ""),
        role=data.get("role", "custom"),
        shift=data.get("shift"),
        enabled=data.get("enabled", True),
    )

    recipient_id = RecipientRepository.create(recipient)

    AuditRepository.log(
        action="recipient_added",
        category="recipients",
        user_name=user,
        new_value=recipient.destination,
        details=f"Added recipient: {recipient.name or recipient.destination}",
    )

    return {"ok": True, "id": recipient_id}


@router.put("/recipients/{recipient_id}")
async def update_recipient(recipient_id: int, request: Request):
    """Update a recipient."""
    data = await request.json()
    user = request.headers.get("X-User", "admin")

    recipient = RecipientRepository.get_by_id(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    old_value = recipient.destination

    # Update fields
    if "destination" in data:
        recipient.destination = data["destination"]
    if "name" in data:
        recipient.name = data["name"]
    if "recipient_type" in data:
        recipient.recipient_type = data["recipient_type"]
    if "role" in data:
        recipient.role = data["role"]
    if "shift" in data:
        recipient.shift = data["shift"]
    if "enabled" in data:
        recipient.enabled = data["enabled"]

    RecipientRepository.update(recipient)

    AuditRepository.log(
        action="recipient_updated",
        category="recipients",
        user_name=user,
        old_value=old_value,
        new_value=recipient.destination,
        details=f"Updated recipient {recipient_id}",
    )

    return {"ok": True}


@router.delete("/recipients/{recipient_id}")
async def delete_recipient(recipient_id: int, request: Request):
    """Delete a recipient."""
    user = request.headers.get("X-User", "admin")

    recipient = RecipientRepository.get_by_id(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    RecipientRepository.delete(recipient_id)

    AuditRepository.log(
        action="recipient_deleted",
        category="recipients",
        user_name=user,
        old_value=recipient.destination,
        details=f"Deleted recipient: {recipient.name or recipient.destination}",
    )

    return {"ok": True}


@router.post("/recipients/{recipient_id}/test")
async def test_recipient(recipient_id: int, request: Request):
    """Send test to a specific recipient."""
    recipient = RecipientRepository.get_by_id(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    delivery = EmailDelivery()
    result = delivery.send(
        recipient=recipient.destination,
        subject="[FORD CAD] Test Email",
        body_text="This is a test email from FORD CAD.",
        body_html="<p>This is a test email from <strong>FORD CAD</strong>.</p>",
    )

    if result.success:
        return {"ok": True, "message": f"Test sent to {recipient.destination}"}
    else:
        return {"ok": False, "error": result.error}


@router.get("/recipients/battalion")
async def get_battalion_chiefs():
    """Get battalion chief list by shift."""
    bcs = RecipientRepository.get_battalion_chiefs()

    # Fill in defaults for missing shifts
    result = {}
    for shift in ["A", "B", "C", "D"]:
        if shift in bcs:
            result[shift] = bcs[shift].to_dict()
        else:
            result[shift] = {
                "shift": shift,
                "name": BC_DEFAULTS.get(shift, {}).get("name", f"BC {shift}"),
                "email": "",
                "configured": False,
            }

    return {"battalion_chiefs": result}


@router.put("/recipients/battalion/{shift}")
async def update_battalion_chief(shift: str, request: Request):
    """Update battalion chief contact for a shift."""
    shift = shift.upper()
    if shift not in ["A", "B", "C", "D"]:
        raise HTTPException(status_code=400, detail="Invalid shift")

    data = await request.json()
    user = request.headers.get("X-User", "admin")

    email = data.get("email", "")
    name = data.get("name", BC_DEFAULTS.get(shift, {}).get("name", f"BC {shift}"))

    RecipientRepository.upsert_battalion_chief(shift, email, name)

    AuditRepository.log(
        action="battalion_chief_updated",
        category="recipients",
        user_name=user,
        new_value=email,
        details=f"Updated BC for shift {shift}: {name}",
    )

    return {"ok": True, "shift": shift, "name": name, "email": email}


# ============================================================================
# Report Generation Endpoints
# ============================================================================

@router.get("/preview", response_class=HTMLResponse)
async def preview_report(shift: Optional[str] = None):
    """Preview current report as HTML."""
    engine = get_engine()
    report = engine.generate_report(report_type="shift_end", shift=shift)
    html = engine.format_report_html(report)
    return HTMLResponse(content=html)


@router.get("/preview/pdf")
async def preview_report_pdf(shift: Optional[str] = None):
    """Preview report as PDF."""
    # PDF generation would require WeasyPrint or similar
    return {"ok": False, "error": "PDF export not yet implemented"}


@router.post("/send")
async def send_report_now(request: Request, background_tasks: BackgroundTasks):
    """Send report immediately."""
    data = await request.json()
    user = request.headers.get("X-User", "admin")
    shift = data.get("shift")

    engine = get_engine()

    # Run in background
    background_tasks.add_task(
        engine.send_report,
        shift=shift,
        triggered_by="manual",
        triggered_by_user=user,
    )

    AuditRepository.log(
        action="report_manual_send",
        category="reports",
        user_name=user,
        details=f"Manual report send initiated for shift {shift or 'current'}",
    )

    return {"ok": True, "message": "Report generation started"}


# ============================================================================
# History Endpoints
# ============================================================================

@router.get("/history")
async def get_report_history(limit: int = 50):
    """Get report history."""
    history = HistoryRepository.get_recent(limit)
    return {"history": [h.to_dict() for h in history]}


@router.get("/history/{history_id}")
async def get_history_detail(history_id: int):
    """Get detailed history for a specific report."""
    entry = HistoryRepository.get_by_id(history_id)
    if not entry:
        raise HTTPException(status_code=404, detail="History entry not found")

    delivery_logs = DeliveryLogRepository.get_for_history(history_id)

    return {
        "history": entry.to_dict(),
        "delivery_logs": delivery_logs,
    }


# ============================================================================
# Scheduler Control Endpoints
# ============================================================================

@router.get("/scheduler/status")
async def get_scheduler_status():
    """Get comprehensive scheduler status."""
    scheduler = get_scheduler()
    return scheduler.get_status()


@router.post("/scheduler/start")
async def start_scheduler(request: Request):
    """Start the scheduler."""
    user = request.headers.get("X-User", "admin")

    # Enable scheduler first
    set_config("scheduler_enabled", True, user=user)

    scheduler = get_scheduler()
    success = scheduler.start(user=user)

    if success:
        return {"ok": True, "message": "Scheduler started", "status": scheduler.get_status()}
    else:
        return {"ok": False, "error": "Failed to start scheduler"}


@router.post("/scheduler/stop")
async def stop_scheduler(request: Request):
    """Stop the scheduler."""
    user = request.headers.get("X-User", "admin")

    scheduler = get_scheduler()
    success = scheduler.stop(user=user)

    if success:
        return {"ok": True, "message": "Scheduler stopped", "status": scheduler.get_status()}
    else:
        return {"ok": False, "error": "Failed to stop scheduler"}


@router.post("/scheduler/restart")
async def restart_scheduler(request: Request):
    """Restart the scheduler."""
    user = request.headers.get("X-User", "admin")

    scheduler = get_scheduler()
    success = scheduler.restart(user=user)

    if success:
        return {"ok": True, "message": "Scheduler restarted", "status": scheduler.get_status()}
    else:
        return {"ok": False, "error": "Failed to restart scheduler"}


@router.post("/scheduler/enable")
async def enable_scheduler(request: Request):
    """Enable automatic reporting."""
    user = request.headers.get("X-User", "admin")

    set_config("scheduler_enabled", True, user=user)

    scheduler = get_scheduler()
    if not scheduler.is_running():
        scheduler.start(user=user)

    AuditRepository.log(
        action="scheduler_enabled",
        category="scheduler",
        user_name=user,
    )

    return {"ok": True, "enabled": True, "status": scheduler.get_status()}


@router.post("/scheduler/disable")
async def disable_scheduler(request: Request):
    """Disable automatic reporting."""
    user = request.headers.get("X-User", "admin")

    set_config("scheduler_enabled", False, user=user)

    scheduler = get_scheduler()
    if scheduler.is_running():
        scheduler.stop(user=user)

    AuditRepository.log(
        action="scheduler_disabled",
        category="scheduler",
        user_name=user,
    )

    return {"ok": True, "enabled": False, "status": scheduler.get_status()}


# ============================================================================
# Audit Log Endpoints
# ============================================================================

@router.get("/audit")
async def get_audit_log(limit: int = 100, category: Optional[str] = None):
    """Get audit log entries."""
    entries = AuditRepository.get_recent(limit, category)
    return {"entries": entries}


# ============================================================================
# Registration Function
# ============================================================================

def register_reporting_routes(app):
    """Register all reporting routes with the FastAPI app."""
    # Initialize database
    init_database()

    # Include router
    app.include_router(router)

    # Initialize scheduler
    init_scheduler()

    # Set up report callback
    scheduler = get_scheduler()
    engine = get_engine()
    scheduler.set_report_callback(engine.send_report)

    logger.info("Reporting module routes registered")
