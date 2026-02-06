# ============================================================================
# FORD CAD - Reporting API Routes (v3)
# ============================================================================
# Complete FastAPI routes for the reporting system.
#
# Three routers:
#   - router:        /api/reporting/*      (new v3 endpoints)
#   - legacy_router: /api/v2/reports/*     (backward-compatible v2 endpoints)
#   - modal_router:  /modals/reporting     (modal HTML)
#
# Registration via register_reporting_routes(app).
# ============================================================================

import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from .models import (
    TemplateRepository, RunRepository, DeliveryRepository,
    NewScheduleRepository, AuditRepository, ReportRun,
    ReportDelivery, ReportScheduleNew, ReportTemplate,
    make_download_token, verify_download_token, ensure_artifact_dir,
    # Legacy imports
    ScheduleRepository, RecipientRepository, HistoryRepository,
    DeliveryLogRepository, Schedule, Recipient, ReportHistoryEntry,
    get_db,
)
from .config import (
    get_config, set_config, get_all_config, get_local_now,
    format_time_for_display, get_timezone, BC_DEFAULTS,
)
from .scheduler import get_scheduler, init_scheduler
from .engine import get_engine
from .delivery import EmailDelivery

logger = logging.getLogger("reporting.routes")

# ---------------------------------------------------------------------------
# Built-in template definitions (returned alongside DB templates)
# ---------------------------------------------------------------------------
BUILTIN_TEMPLATES = [
    {
        "template_key": "blotter",
        "name": "Blotter / Daily Log",
        "description": "Chronological list of events (daily logs + related remarks). "
                       "Filters by date range, shift, event type, unit, calltaker, status.",
        "builtin": True,
    },
    {
        "template_key": "incident_summary",
        "name": "Incident Summary",
        "description": "One or many incidents with full details: type, location, "
                       "timestamps, dispositions, narrative, units, timeline.",
        "builtin": True,
    },
    {
        "template_key": "unit_response_stats",
        "name": "Unit Response Stats",
        "description": "Response time metrics per unit: time-to-dispatch, enroute, "
                       "arrive, on-scene, utilization, counts.",
        "builtin": True,
    },
    {
        "template_key": "calltaker_stats",
        "name": "Calltaker Stats",
        "description": "Call counts, time to dispatch, dispositions, remarks per calltaker.",
        "builtin": True,
    },
    {
        "template_key": "shift_workload",
        "name": "Shift Workload Summary",
        "description": "Workload distribution across shifts: incident counts, "
                       "daily log activity, resource usage.",
        "builtin": True,
    },
    {
        "template_key": "response_compliance",
        "name": "Response-Time Compliance",
        "description": "Pass/fail analysis against response time thresholds per incident type.",
        "builtin": True,
    },
]


# ============================================================================
# Router definitions
# ============================================================================

router = APIRouter(prefix="/api/reporting", tags=["reporting"])
legacy_router = APIRouter(prefix="/api/v2/reports", tags=["reports-legacy"])
modal_router = APIRouter(tags=["reporting-modals"])


# ============================================================================
# Helper utilities
# ============================================================================

def _get_user(request: Request) -> str:
    """Extract the acting user from the request (header or session)."""
    return request.headers.get("X-User", "admin")


def _json_loads_safe(raw: str, fallback: Any = None) -> Any:
    """Safely parse a JSON string, returning *fallback* on failure."""
    try:
        return json.loads(raw)
    except Exception:
        return fallback if fallback is not None else {}


# ============================================================================
# Modal HTML endpoint
# ============================================================================

@modal_router.get("/modals/reporting", response_class=HTMLResponse)
async def reporting_modal(request: Request):
    """Return the 4-tab reporting modal HTML.

    Attempts to load the template from the templates directory via Jinja2.
    If Jinja2Templates is available on the app, uses it; otherwise reads
    the file directly and returns an HTMLResponse.
    """
    # Try Jinja2 template rendering first (if the app has templates attached)
    try:
        templates_engine = request.app.state.templates  # type: ignore[attr-defined]
        return templates_engine.TemplateResponse(
            "modals/reporting_modal.html",
            {"request": request},
        )
    except Exception:
        pass

    # Fallback: read the template file directly
    template_path = Path(__file__).resolve().parent.parent.parent / "templates" / "modals" / "reporting_modal.html"
    if template_path.exists():
        html = template_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html)

    # Last resort: minimal inline HTML
    return HTMLResponse(content=_inline_reporting_modal_html())


def _inline_reporting_modal_html() -> str:
    """Minimal inline reporting modal returned when no template file is found."""
    return """
    <div class="cad-modal-overlay" onclick="CAD_MODAL.close()"></div>
    <div class="cad-modal reports-modal" role="dialog" aria-modal="true" aria-label="Reports">
        <div class="cad-modal-header">
            <div class="cad-modal-title">Reports</div>
            <button class="cad-modal-close" onclick="CAD_MODAL.close()">&times;</button>
        </div>
        <div class="cad-modal-body">
            <div class="reports-container">
                <div class="report-tabs">
                    <button class="report-tab active" data-tab="run">Run Report</button>
                    <button class="report-tab" data-tab="templates">Templates</button>
                    <button class="report-tab" data-tab="schedules">Schedules</button>
                    <button class="report-tab" data-tab="history">History</button>
                </div>
                <div class="report-tab-content active" id="tab-run">
                    <p>Select a template and configure filters to generate a report.</p>
                    <div id="template-picker"></div>
                    <div id="report-filters"></div>
                    <div style="margin-top:12px;">
                        <button class="btn-primary" onclick="REPORTING.runReport()">Run Report</button>
                        <button class="btn-secondary" onclick="REPORTING.previewReport()">Preview</button>
                    </div>
                    <div id="report-result" style="margin-top:12px;display:none;"></div>
                </div>
                <div class="report-tab-content" id="tab-templates">
                    <div id="templates-list">Loading templates...</div>
                </div>
                <div class="report-tab-content" id="tab-schedules">
                    <div id="schedules-list">Loading schedules...</div>
                    <button class="btn-primary" onclick="REPORTING.createSchedule()" style="margin-top:12px;">
                        New Schedule
                    </button>
                </div>
                <div class="report-tab-content" id="tab-history">
                    <div id="history-list">Loading history...</div>
                </div>
            </div>
        </div>
        <div class="cad-modal-footer">
            <button class="btn-secondary" onclick="CAD_MODAL.close()">Close</button>
        </div>
    </div>
    <style>
    .reports-modal { min-width: 600px; max-width: 700px; }
    .reports-container { padding: 8px; }
    .report-tabs { display:flex; gap:4px; border-bottom:1px solid var(--border-default,#ccc); margin-bottom:12px; }
    .report-tab { padding:10px 16px; background:none; border:none; cursor:pointer; font-size:13px; font-weight:600; color:#6b7280; border-bottom:2px solid transparent; }
    .report-tab:hover { color:#2563eb; }
    .report-tab.active { color:#2563eb; border-bottom-color:#2563eb; }
    .report-tab-content { display:none; }
    .report-tab-content.active { display:block; }
    </style>
    <script>
    window.REPORTING = window.REPORTING || {};
    (function(){
        document.querySelectorAll('.report-tab').forEach(function(tab){
            tab.addEventListener('click',function(){
                document.querySelectorAll('.report-tab').forEach(function(t){t.classList.remove('active');});
                document.querySelectorAll('.report-tab-content').forEach(function(c){c.classList.remove('active');});
                tab.classList.add('active');
                var target = document.getElementById('tab-'+tab.dataset.tab);
                if(target) target.classList.add('active');
            });
        });
    })();
    </script>
    """


# ============================================================================
# Template endpoints  (/api/reporting/templates)
# ============================================================================

@router.get("/templates")
async def list_templates():
    """List all report templates (built-in + custom).

    Returns a combined list with built-in templates flagged as ``builtin: true``
    and custom user-created templates flagged as ``builtin: false``.
    """
    # Database templates (custom)
    db_templates = TemplateRepository.get_all()
    db_keys = {t.template_key for t in db_templates}

    results: List[Dict[str, Any]] = []

    # Add built-in templates first
    for bt in BUILTIN_TEMPLATES:
        entry = dict(bt)
        # If a DB template overrides the built-in, merge the DB version
        if bt["template_key"] in db_keys:
            db_t = next(t for t in db_templates if t.template_key == bt["template_key"])
            entry.update(db_t.to_dict())
            entry["builtin"] = True
        results.append(entry)

    # Add purely custom templates (not overriding any built-in)
    for t in db_templates:
        if t.template_key not in {bt["template_key"] for bt in BUILTIN_TEMPLATES}:
            d = t.to_dict()
            d["builtin"] = False
            results.append(d)

    return {"templates": results}


@router.post("/templates")
async def create_template(request: Request):
    """Create a custom report template from the builder.

    Expects JSON body:
    ```json
    {
        "name": "My Custom Report",
        "template_key": "my_custom_report",
        "description": "...",
        "default_config": {}
    }
    ```
    """
    data = await request.json()
    user = _get_user(request)

    name = data.get("name", "").strip()
    template_key = data.get("template_key", "").strip()
    if not name or not template_key:
        raise HTTPException(status_code=400, detail="name and template_key are required")

    default_config = data.get("default_config", {})
    if isinstance(default_config, dict):
        default_config_json = json.dumps(default_config)
    else:
        default_config_json = str(default_config)

    template = ReportTemplate(
        name=name,
        template_key=template_key,
        description=data.get("description", ""),
        default_config_json=default_config_json,
    )

    template_id = TemplateRepository.upsert(template)

    AuditRepository.log(
        action="template_created",
        category="templates",
        user_name=user,
        new_value=template_key,
        details=f"Created/updated template: {name}",
    )

    logger.info("Template created/updated: %s (key=%s) by %s", name, template_key, user)
    return {"ok": True, "id": template_id, "template_key": template_key}


# ============================================================================
# Run report  (/api/reporting/run)
# ============================================================================

@router.post("/run")
async def run_report(request: Request, background_tasks: BackgroundTasks):
    """Run a report now.

    Expects JSON body:
    ```json
    {
        "template_key": "blotter",
        "title": "Optional title override",
        "filters": {"date_from": "...", "date_to": "...", "shift": "A", ...},
        "formats": ["html", "pdf"]
    }
    ```

    Returns ``{run_id, links, summary}`` immediately; generation may continue
    in the background for heavy reports.
    """
    data = await request.json()
    user = _get_user(request)

    template_key = data.get("template_key", "blotter")
    title = data.get("title", "")
    filters = data.get("filters", {})
    formats = data.get("formats", ["html"])

    # Validate template exists
    template = TemplateRepository.get_by_key(template_key)
    if not template:
        # Check built-in keys
        if template_key not in {bt["template_key"] for bt in BUILTIN_TEMPLATES}:
            raise HTTPException(status_code=404, detail=f"Unknown template_key: {template_key}")

    # Create report run record
    run = ReportRun(
        template_key=template_key,
        title=title or f"Report: {template_key}",
        filters_json=json.dumps(filters),
        format_json=json.dumps(formats),
        created_by=user,
        status="running",
    )
    run_id = RunRepository.create(run)

    # Generate the report synchronously for now (fast templates); heavy ones
    # could be moved to background_tasks if needed.
    try:
        engine = get_engine()
        shift = filters.get("shift")
        report_data = engine.generate_report(
            report_type=template_key if template_key in ("shift_end", "daily_summary", "weekly", "custom") else "shift_end",
            shift=shift,
        )

        # Save artifacts
        artifact_dir = ensure_artifact_dir(run_id)
        links: Dict[str, str] = {}

        if "html" in formats:
            html_content = engine.format_report_html(report_data)
            html_path = artifact_dir / "report.html"
            html_path.write_text(html_content, encoding="utf-8")
            token = make_download_token(run_id, "html")
            links["html"] = f"/api/reporting/download/{token}"

        if "text" in formats:
            text_content = engine.format_report_text(report_data)
            text_path = artifact_dir / "report.txt"
            text_path.write_text(text_content, encoding="utf-8")
            token = make_download_token(run_id, "text")
            links["text"] = f"/api/reporting/download/{token}"

        # Store summary
        summary = report_data.get("stats", {})
        summary_text = json.dumps(summary)
        RunRepository.save_summary(run_id, summary_text)

        # Store artifact paths
        artifact_paths = {fmt: str(artifact_dir / f"report.{fmt}") for fmt in formats}
        RunRepository.save_artifacts(run_id, artifact_paths)

        RunRepository.update_status(run_id, "completed")

        AuditRepository.log(
            action="report_run",
            category="reports",
            user_name=user,
            new_value=str(run_id),
            details=f"Ran report {template_key} (run_id={run_id})",
        )

        logger.info("Report run completed: run_id=%d, template=%s, user=%s", run_id, template_key, user)

        return {
            "ok": True,
            "run_id": run_id,
            "links": links,
            "summary": summary,
            "status": "completed",
        }

    except Exception as exc:
        error_msg = str(exc)
        RunRepository.update_status(run_id, "failed", error=error_msg)
        logger.error("Report run failed: run_id=%d, error=%s", run_id, error_msg, exc_info=True)
        return {
            "ok": False,
            "run_id": run_id,
            "error": error_msg,
            "status": "failed",
        }


# ============================================================================
# Preview  (/api/reporting/preview)
# ============================================================================

@router.get("/preview", response_class=HTMLResponse)
async def preview_report(
    template_key: str = Query("blotter", description="Template key"),
    shift: Optional[str] = Query(None, description="Shift filter (A/B/C/D)"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
):
    """Return preview HTML for the current filters/template.

    This generates the report in memory and returns the HTML directly
    without persisting a run record.
    """
    try:
        engine = get_engine()
        report_data = engine.generate_report(
            report_type="shift_end",
            shift=shift,
        )
        html = engine.format_report_html(report_data)
        return HTMLResponse(content=html)
    except Exception as exc:
        logger.error("Preview failed: %s", exc, exc_info=True)
        return HTMLResponse(
            content=f"<html><body><h2>Preview Error</h2><p>{exc}</p></body></html>",
            status_code=500,
        )


# ============================================================================
# Delivery  (/api/reporting/deliver)
# ============================================================================

@router.post("/deliver")
async def deliver_report(request: Request, background_tasks: BackgroundTasks):
    """Deliver an existing report run via specified channels.

    Expects JSON body:
    ```json
    {
        "report_run_id": 42,
        "channels": [
            {"channel": "email", "destination": "user@example.com"},
            {"channel": "webhook", "destination": "https://hooks.slack.com/..."}
        ]
    }
    ```
    """
    data = await request.json()
    user = _get_user(request)

    run_id = data.get("report_run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="report_run_id is required")

    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Report run {run_id} not found")

    channels = data.get("channels", [])
    if not channels:
        raise HTTPException(status_code=400, detail="At least one channel is required")

    results: List[Dict[str, Any]] = []

    for ch in channels:
        channel_name = ch.get("channel", "email")
        destination = ch.get("destination", "")

        # Create delivery record
        delivery = ReportDelivery(
            report_run_id=run_id,
            channel=channel_name,
            destination=destination,
            status="pending",
        )
        delivery_id = DeliveryRepository.create(delivery)

        # Attempt delivery
        try:
            if channel_name == "email":
                email_delivery = EmailDelivery()
                # Load the HTML artifact if available
                artifacts = _json_loads_safe(run.artifact_paths_json, {})
                html_path = artifacts.get("html", "")
                body_html = ""
                body_text = run.summary_text or "Report attached."
                if html_path:
                    try:
                        body_html = Path(html_path).read_text(encoding="utf-8")
                    except Exception:
                        pass

                result = email_delivery.send(
                    recipient=destination,
                    subject=f"[FORD CAD] Report #{run_id} - {run.title}",
                    body_text=body_text,
                    body_html=body_html or None,
                )

                if result.success:
                    DeliveryRepository.update_status(delivery_id, "sent", msg_id=result.message_id)
                    results.append({"delivery_id": delivery_id, "status": "sent", "channel": channel_name})
                else:
                    DeliveryRepository.update_status(delivery_id, "failed", error=result.error)
                    results.append({"delivery_id": delivery_id, "status": "failed", "error": result.error, "channel": channel_name})
            else:
                # For other channels, mark as unsupported for now
                DeliveryRepository.update_status(delivery_id, "failed", error=f"Channel '{channel_name}' not yet implemented for ad-hoc delivery")
                results.append({"delivery_id": delivery_id, "status": "failed", "error": f"Unsupported channel: {channel_name}", "channel": channel_name})

        except Exception as exc:
            DeliveryRepository.update_status(delivery_id, "failed", error=str(exc))
            results.append({"delivery_id": delivery_id, "status": "failed", "error": str(exc), "channel": channel_name})

    AuditRepository.log(
        action="report_delivered",
        category="delivery",
        user_name=user,
        details=f"Delivered run_id={run_id} to {len(channels)} channel(s)",
    )

    logger.info("Report delivery: run_id=%d, channels=%d, user=%s", run_id, len(channels), user)
    return {"ok": True, "run_id": run_id, "deliveries": results}


# ============================================================================
# History  (/api/reporting/history, /api/reporting/run/{id})
# ============================================================================

@router.get("/history")
async def report_history(
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    template_key: Optional[str] = Query(None, description="Filter by template"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """List report runs with optional filters."""
    runs = RunRepository.get_recent(limit=limit, template_key=template_key)

    # Apply status filter in-memory if provided
    if status:
        runs = [r for r in runs if r.status == status]

    return {
        "history": [r.to_dict() for r in runs],
        "count": len(runs),
    }


@router.get("/run/{run_id}")
async def get_run_detail(run_id: int):
    """Get details of a specific report run including delivery records."""
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Report run {run_id} not found")

    deliveries = DeliveryRepository.get_for_run(run_id)

    # Generate download links if artifacts exist
    links: Dict[str, str] = {}
    artifacts = _json_loads_safe(run.artifact_paths_json, {})
    for kind, path in artifacts.items():
        if Path(path).exists():
            token = make_download_token(run_id, kind)
            links[kind] = f"/api/reporting/download/{token}"

    return {
        "run": run.to_dict(),
        "deliveries": [d.to_dict() for d in deliveries],
        "download_links": links,
    }


# ============================================================================
# Schedule endpoints  (/api/reporting/schedules, /api/reporting/schedule)
# ============================================================================

@router.get("/schedules")
async def list_schedules():
    """List all report schedules (new-style)."""
    schedules = NewScheduleRepository.get_all()
    return {"schedules": [s.to_dict() for s in schedules]}


@router.post("/schedule")
async def create_schedule(request: Request):
    """Create a new report schedule.

    Expects JSON body:
    ```json
    {
        "name": "Daily Blotter",
        "template_key": "blotter",
        "filters": {},
        "formats": ["pdf", "html"],
        "delivery": [{"channel": "email", "destination": "admin@example.com"}],
        "rrule_or_cron": "0 17 * * *",
        "schedule_type": "cron",
        "enabled": false
    }
    ```
    """
    data = await request.json()
    user = _get_user(request)

    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    schedule = ReportScheduleNew(
        name=name,
        template_key=data.get("template_key", "blotter"),
        filters_json=json.dumps(data.get("filters", {})),
        formats_json=json.dumps(data.get("formats", ["pdf", "html"])),
        delivery_json=json.dumps(data.get("delivery", [])),
        rrule_or_cron=data.get("rrule_or_cron"),
        schedule_type=data.get("schedule_type", "cron"),
        enabled=bool(data.get("enabled", False)),
        created_by=user,
    )

    schedule_id = NewScheduleRepository.create(schedule)

    AuditRepository.log(
        action="schedule_created",
        category="schedules",
        user_name=user,
        new_value=str(schedule_id),
        details=f"Created schedule: {name}",
    )

    logger.info("Schedule created: id=%d, name=%s, user=%s", schedule_id, name, user)
    return {"ok": True, "id": schedule_id}


@router.post("/schedule/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int, request: Request):
    """Enable or disable a schedule.

    Expects JSON body: ``{"enabled": true}`` or ``{"enabled": false}``.
    If no body is provided, the schedule's enabled state is flipped.
    """
    user = _get_user(request)
    schedule = NewScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    try:
        data = await request.json()
        enabled = bool(data.get("enabled", not schedule.enabled))
    except Exception:
        # No body or invalid JSON -- just toggle
        enabled = not schedule.enabled

    NewScheduleRepository.toggle(schedule_id, enabled)

    AuditRepository.log(
        action="schedule_toggled",
        category="schedules",
        user_name=user,
        details=f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'}",
    )

    logger.info("Schedule %d toggled to %s by %s", schedule_id, enabled, user)
    return {"ok": True, "id": schedule_id, "enabled": enabled}


@router.post("/schedule/{schedule_id}/run_now")
async def run_schedule_now(schedule_id: int, request: Request, background_tasks: BackgroundTasks):
    """Manually trigger a scheduled report immediately."""
    user = _get_user(request)
    schedule = NewScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # Run in background
    engine = get_engine()
    background_tasks.add_task(
        engine.send_report,
        schedule_id=schedule_id,
        triggered_by="manual",
        triggered_by_user=user,
    )

    AuditRepository.log(
        action="schedule_manual_run",
        category="schedules",
        user_name=user,
        details=f"Manual run for schedule {schedule_id}: {schedule.name}",
    )

    logger.info("Manual trigger for schedule %d by %s", schedule_id, user)
    return {"ok": True, "message": f"Schedule '{schedule.name}' triggered", "schedule_id": schedule_id}


@router.delete("/schedule/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request):
    """Delete a report schedule."""
    user = _get_user(request)
    schedule = NewScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    NewScheduleRepository.delete(schedule_id)

    AuditRepository.log(
        action="schedule_deleted",
        category="schedules",
        user_name=user,
        details=f"Deleted schedule {schedule_id}: {schedule.name}",
    )

    logger.info("Schedule %d deleted by %s", schedule_id, user)
    return {"ok": True, "id": schedule_id}


# ============================================================================
# Secure download  (/api/reporting/download/{token})
# ============================================================================

@router.get("/download/{token}")
async def download_artifact(token: str):
    """Download a report artifact using a time-limited signed token.

    Tokens are generated by ``make_download_token`` and contain the run ID,
    artifact kind, expiry, and HMAC signature.
    """
    payload = verify_download_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail="Invalid or expired download token")

    run_id = payload["run_id"]
    kind = payload["kind"]

    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Report run not found")

    artifacts = _json_loads_safe(run.artifact_paths_json, {})
    file_path_str = artifacts.get(kind)
    if not file_path_str:
        raise HTTPException(status_code=404, detail=f"Artifact '{kind}' not found for run {run_id}")

    file_path = Path(file_path_str)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing from disk")

    # Determine media type
    media_types = {
        "html": "text/html",
        "pdf": "application/pdf",
        "csv": "text/csv",
        "text": "text/plain",
        "txt": "text/plain",
        "json": "application/json",
    }
    media_type = media_types.get(kind, "application/octet-stream")
    filename = f"report_{run_id}.{kind}"

    logger.info("Download: run_id=%d, kind=%s", run_id, kind)
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
    )


# ============================================================================
# Legacy v2 routes  (/api/v2/reports/*)
# ============================================================================
# These preserve backward compatibility with the existing v2 API surface.

@legacy_router.get("/config")
async def legacy_get_config():
    """Get all report configuration (legacy v2)."""
    config = get_all_config()

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


@legacy_router.patch("/config")
async def legacy_update_config(request: Request):
    """Update report configuration (legacy v2)."""
    data = await request.json()
    user = _get_user(request)

    updated = []
    for key, value in data.items():
        if key in ("sendgrid_api_key", "smtp_pass") and value == "***configured***":
            continue
        set_config(key, value, user=user)
        updated.append(key)

    return {"ok": True, "updated": updated}


@legacy_router.get("/config/email")
async def legacy_get_email_config():
    """Get email configuration (legacy v2)."""
    return {
        "provider": get_config("email_provider", "sendgrid"),
        "sendgrid_configured": bool(get_config("sendgrid_api_key")),
        "smtp_configured": bool(get_config("smtp_user") and get_config("smtp_pass")),
        "from_email": get_config("from_email"),
        "from_name": get_config("from_name"),
    }


@legacy_router.put("/config/email")
async def legacy_update_email_config(request: Request):
    """Update email configuration (legacy v2)."""
    data = await request.json()
    user = _get_user(request)

    email_fields = {
        "provider": "email_provider",
        "sendgrid_api_key": "sendgrid_api_key",
        "from_email": "from_email",
        "from_name": "from_name",
        "smtp_host": "smtp_host",
        "smtp_port": "smtp_port",
        "smtp_user": "smtp_user",
        "smtp_pass": "smtp_pass",
    }

    for field, config_key in email_fields.items():
        if field in data and data[field]:
            value = data[field]
            if field == "smtp_port":
                value = int(value)
            set_config(config_key, value, user=user)

    return {"ok": True, "message": "Email configuration updated"}


@legacy_router.post("/config/email/test")
async def legacy_test_email(request: Request):
    """Test email configuration by sending a test email (legacy v2)."""
    data = await request.json()
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email address required")

    delivery = EmailDelivery()
    if not delivery.is_configured():
        return {"ok": False, "error": "Email not configured"}

    if not delivery.test_connection():
        return {"ok": False, "error": "Failed to connect to email provider"}

    result = delivery.send(
        recipient=email,
        subject="[FORD CAD] Test Email - Configuration Verified",
        body_text=f"This is a test email from FORD CAD.\n\nTimezone: {get_config('timezone')}\nTime: {format_time_for_display()}\n\nEmail is configured correctly!",
        body_html=f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
            <h2 style="color:#1e40af;">FORD CAD - Test Email</h2>
            <p>If you received this, email is configured correctly!</p>
            <ul>
                <li><strong>Timezone:</strong> {get_config('timezone')}</li>
                <li><strong>Time:</strong> {format_time_for_display()}</li>
            </ul>
        </div>
        """,
    )

    if result.success:
        return {"ok": True, "message": f"Test email sent to {email}"}
    return {"ok": False, "error": result.error}


# --- Legacy schedule endpoints ---

@legacy_router.get("/schedules")
async def legacy_list_schedules():
    """List all report schedules (legacy v2)."""
    schedules = ScheduleRepository.get_all()
    return {"schedules": [s.to_dict() for s in schedules]}


@legacy_router.post("/schedules")
async def legacy_create_schedule(request: Request):
    """Create a new report schedule (legacy v2)."""
    data = await request.json()
    user = _get_user(request)

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
        details=f"Created legacy schedule: {schedule.name}",
    )

    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True, "id": schedule_id}


@legacy_router.get("/schedules/{schedule_id}")
async def legacy_get_schedule(schedule_id: int):
    """Get a specific schedule (legacy v2)."""
    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule.to_dict()


@legacy_router.put("/schedules/{schedule_id}")
async def legacy_update_schedule(schedule_id: int, request: Request):
    """Update a schedule (legacy v2)."""
    data = await request.json()
    user = _get_user(request)

    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    updatable_fields = [
        "name", "description", "report_type", "schedule_type",
        "cron_expression", "day_time", "night_time", "timezone", "enabled",
    ]
    for field in updatable_fields:
        if field in data:
            setattr(schedule, field, data[field])

    ScheduleRepository.update(schedule)

    AuditRepository.log(
        action="schedule_updated",
        category="schedules",
        user_name=user,
        details=f"Updated legacy schedule {schedule_id}: {schedule.name}",
    )

    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True}


@legacy_router.delete("/schedules/{schedule_id}")
async def legacy_delete_schedule(schedule_id: int, request: Request):
    """Delete a schedule (legacy v2)."""
    user = _get_user(request)

    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    ScheduleRepository.delete(schedule_id)

    AuditRepository.log(
        action="schedule_deleted",
        category="schedules",
        user_name=user,
        details=f"Deleted legacy schedule {schedule_id}: {schedule.name}",
    )

    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True}


@legacy_router.post("/schedules/{schedule_id}/enable")
async def legacy_enable_schedule(schedule_id: int, request: Request):
    """Enable a schedule (legacy v2)."""
    user = _get_user(request)
    ScheduleRepository.set_enabled(schedule_id, True)

    AuditRepository.log(
        action="schedule_enabled",
        category="schedules",
        user_name=user,
        details=f"Enabled legacy schedule {schedule_id}",
    )

    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True, "enabled": True}


@legacy_router.post("/schedules/{schedule_id}/disable")
async def legacy_disable_schedule(schedule_id: int, request: Request):
    """Disable a schedule (legacy v2)."""
    user = _get_user(request)
    ScheduleRepository.set_enabled(schedule_id, False)

    AuditRepository.log(
        action="schedule_disabled",
        category="schedules",
        user_name=user,
        details=f"Disabled legacy schedule {schedule_id}",
    )

    scheduler = get_scheduler()
    scheduler.refresh_schedules()

    return {"ok": True, "enabled": False}


@legacy_router.post("/schedules/{schedule_id}/run")
async def legacy_run_schedule(schedule_id: int, request: Request, background_tasks: BackgroundTasks):
    """Manually run a schedule (legacy v2)."""
    user = _get_user(request)

    schedule = ScheduleRepository.get_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    engine = get_engine()
    background_tasks.add_task(
        engine.send_report,
        schedule_id=schedule_id,
        triggered_by="manual",
        triggered_by_user=user,
    )

    return {"ok": True, "message": "Report generation started"}


# --- Legacy recipient endpoints ---

@legacy_router.get("/recipients")
async def legacy_list_recipients(schedule_id: Optional[int] = None):
    """List all recipients (legacy v2)."""
    recipients = RecipientRepository.get_all(schedule_id)
    return {"recipients": [r.to_dict() for r in recipients]}


@legacy_router.post("/recipients")
async def legacy_create_recipient(request: Request):
    """Create a new recipient (legacy v2)."""
    data = await request.json()
    user = _get_user(request)

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


@legacy_router.put("/recipients/{recipient_id}")
async def legacy_update_recipient(recipient_id: int, request: Request):
    """Update a recipient (legacy v2)."""
    data = await request.json()
    user = _get_user(request)

    recipient = RecipientRepository.get_by_id(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    old_value = recipient.destination
    updatable_fields = ["destination", "name", "recipient_type", "role", "shift", "enabled"]
    for field in updatable_fields:
        if field in data:
            setattr(recipient, field, data[field])

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


@legacy_router.delete("/recipients/{recipient_id}")
async def legacy_delete_recipient(recipient_id: int, request: Request):
    """Delete a recipient (legacy v2)."""
    user = _get_user(request)

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


@legacy_router.post("/recipients/{recipient_id}/test")
async def legacy_test_recipient(recipient_id: int):
    """Send test to a specific recipient (legacy v2)."""
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
    return {"ok": False, "error": result.error}


@legacy_router.get("/recipients/battalion")
async def legacy_get_battalion_chiefs():
    """Get battalion chief list by shift (legacy v2)."""
    bcs = RecipientRepository.get_battalion_chiefs()

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


@legacy_router.put("/recipients/battalion/{shift}")
async def legacy_update_battalion_chief(shift: str, request: Request):
    """Update battalion chief contact for a shift (legacy v2)."""
    shift = shift.upper()
    if shift not in ["A", "B", "C", "D"]:
        raise HTTPException(status_code=400, detail="Invalid shift")

    data = await request.json()
    user = _get_user(request)

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


# --- Legacy report generation endpoints ---

@legacy_router.get("/preview", response_class=HTMLResponse)
async def legacy_preview_report(shift: Optional[str] = None):
    """Preview current report as HTML (legacy v2)."""
    engine = get_engine()
    report = engine.generate_report(report_type="shift_end", shift=shift)
    html = engine.format_report_html(report)
    return HTMLResponse(content=html)


@legacy_router.get("/preview/pdf")
async def legacy_preview_pdf(shift: Optional[str] = None):
    """Preview report as PDF (legacy v2)."""
    return {"ok": False, "error": "PDF export not yet implemented"}


@legacy_router.post("/send")
async def legacy_send_report(request: Request, background_tasks: BackgroundTasks):
    """Send report immediately (legacy v2)."""
    data = await request.json()
    user = _get_user(request)
    shift = data.get("shift")

    engine = get_engine()
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


# --- Legacy history endpoints ---

@legacy_router.get("/history")
async def legacy_get_history(limit: int = 50):
    """Get report history (legacy v2)."""
    history = HistoryRepository.get_recent(limit)
    return {"history": [h.to_dict() for h in history]}


@legacy_router.get("/history/{history_id}")
async def legacy_get_history_detail(history_id: int):
    """Get detailed history for a specific report (legacy v2)."""
    entry = HistoryRepository.get_by_id(history_id)
    if not entry:
        raise HTTPException(status_code=404, detail="History entry not found")

    delivery_logs = DeliveryLogRepository.get_for_history(history_id)

    return {
        "history": entry.to_dict(),
        "delivery_logs": delivery_logs,
    }


# --- Legacy scheduler control endpoints ---

@legacy_router.get("/scheduler/status")
async def legacy_scheduler_status():
    """Get scheduler status (legacy v2)."""
    scheduler = get_scheduler()
    return scheduler.get_status()


@legacy_router.post("/scheduler/start")
async def legacy_scheduler_start(request: Request):
    """Start the scheduler (legacy v2)."""
    user = _get_user(request)
    set_config("scheduler_enabled", True, user=user)
    scheduler = get_scheduler()
    success = scheduler.start(user=user)
    if success:
        return {"ok": True, "message": "Scheduler started", "status": scheduler.get_status()}
    return {"ok": False, "error": "Failed to start scheduler"}


@legacy_router.post("/scheduler/stop")
async def legacy_scheduler_stop(request: Request):
    """Stop the scheduler (legacy v2)."""
    user = _get_user(request)
    scheduler = get_scheduler()
    success = scheduler.stop(user=user)
    if success:
        return {"ok": True, "message": "Scheduler stopped", "status": scheduler.get_status()}
    return {"ok": False, "error": "Failed to stop scheduler"}


@legacy_router.post("/scheduler/restart")
async def legacy_scheduler_restart(request: Request):
    """Restart the scheduler (legacy v2)."""
    user = _get_user(request)
    scheduler = get_scheduler()
    success = scheduler.restart(user=user)
    if success:
        return {"ok": True, "message": "Scheduler restarted", "status": scheduler.get_status()}
    return {"ok": False, "error": "Failed to restart scheduler"}


@legacy_router.post("/scheduler/enable")
async def legacy_scheduler_enable(request: Request):
    """Enable automatic reporting (legacy v2)."""
    user = _get_user(request)
    set_config("scheduler_enabled", True, user=user)
    scheduler = get_scheduler()
    if not scheduler.is_running():
        scheduler.start(user=user)
    AuditRepository.log(action="scheduler_enabled", category="scheduler", user_name=user)
    return {"ok": True, "enabled": True, "status": scheduler.get_status()}


@legacy_router.post("/scheduler/disable")
async def legacy_scheduler_disable(request: Request):
    """Disable automatic reporting (legacy v2)."""
    user = _get_user(request)
    set_config("scheduler_enabled", False, user=user)
    scheduler = get_scheduler()
    if scheduler.is_running():
        scheduler.stop(user=user)
    AuditRepository.log(action="scheduler_disabled", category="scheduler", user_name=user)
    return {"ok": True, "enabled": False, "status": scheduler.get_status()}


# --- Legacy audit log ---

@legacy_router.get("/audit")
async def legacy_get_audit_log(limit: int = 100, category: Optional[str] = None):
    """Get audit log entries (legacy v2)."""
    entries = AuditRepository.get_recent(limit, category)
    return {"entries": entries}


# ============================================================================
# Registration function
# ============================================================================

def register_reporting_routes(app):
    """Register all reporting routers with the FastAPI application.

    This function:
    1. Includes the new ``/api/reporting`` router
    2. Includes the legacy ``/api/v2/reports`` router for backward compatibility
    3. Includes the modal router for ``/modals/reporting``
    4. Initialises the database, scheduler, and report engine
    """
    from .models import init_database

    # Initialize database tables
    init_database()

    # Include all three routers
    app.include_router(router)
    app.include_router(legacy_router)
    app.include_router(modal_router)

    # Initialize scheduler
    init_scheduler()

    # Wire scheduler -> engine callback
    scheduler = get_scheduler()
    engine = get_engine()
    scheduler.set_report_callback(engine.send_report)

    logger.info(
        "Reporting module registered: /api/reporting (new), "
        "/api/v2/reports (legacy), /modals/reporting (modal)"
    )
