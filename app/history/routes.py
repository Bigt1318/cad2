# ============================================================================
# FORD CAD — Call History Routes
# ============================================================================
# HTML + JSON APIs for the Call History Viewer.
# ============================================================================

import json
import logging
import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .queries import (
    create_saved_view,
    delete_saved_view,
    fetch_incident_detail,
    fetch_unified_events,
    get_distinct_values,
    get_saved_views,
    log_delivery,
    log_export,
)
from .export import render_incident_html, render_incident_report

logger = logging.getLogger("history.routes")

# Routers
api_router = APIRouter(prefix="/api/history", tags=["history-api"])
modal_router = APIRouter(tags=["history-modals"])


def _get_user(request: Request) -> str:
    return request.headers.get("X-User", "admin")


# ============================================================================
# HTML Routes
# ============================================================================

@modal_router.get("/modals/history", response_class=HTMLResponse)
async def history_modal(request: Request):
    """Return the full Call History Viewer modal HTML."""
    try:
        templates_engine = request.app.state.templates
        is_admin = bool(request.session.get("is_admin") or False)
        return templates_engine.TemplateResponse(
            "modals/history_modal.html",
            {"request": request, "is_admin": is_admin},
        )
    except Exception:
        logger.error("Failed to render history modal:\n%s", traceback.format_exc())
        return HTMLResponse(
            "<div style='padding:40px;color:#c0392b;'>Error loading history viewer.</div>",
            status_code=500,
        )


@modal_router.get("/modals/history/incident/{incident_id}", response_class=HTMLResponse)
async def history_incident_report(request: Request, incident_id: int):
    """Return a printable HTML incident report."""
    incident = fetch_incident_detail(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    html = render_incident_html(incident)
    return HTMLResponse(html)


# ============================================================================
# JSON API — Event List (root of /api/history)
# ============================================================================

@api_router.get("")
async def api_history_list(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    mode: Optional[str] = Query(None),
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    shift: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    disposition: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    calltaker: Optional[str] = Query(None),
    has_narrative: Optional[bool] = Query(None),
    issue_found: Optional[bool] = Query(None),
):
    """Filtered, paginated event list (incidents + daily log)."""
    filters = {}
    if mode:
        filters["mode"] = mode
    if date_start:
        filters["date_start"] = date_start
    if date_end:
        filters["date_end"] = date_end
    if shift:
        filters["shift"] = shift
    if search:
        filters["search"] = search
    if event_type:
        filters["event_type"] = event_type
    if disposition:
        filters["disposition"] = disposition
    if unit_id:
        filters["unit_id"] = unit_id
    if calltaker:
        filters["calltaker"] = calltaker
    if has_narrative:
        filters["has_narrative"] = True
    if issue_found:
        filters["issue_found"] = True

    try:
        result = fetch_unified_events(filters=filters, page=page, per_page=per_page)
        return result
    except Exception as e:
        logger.error("api_history_list failed: %s\n%s", e, traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================================
# Static-path routes MUST be declared BEFORE /{incident_id} catch-all
# ============================================================================

@api_router.get("/filters")
async def api_history_filters():
    """Return distinct values for filter dropdowns."""
    return get_distinct_values()


@api_router.get("/saved-views")
async def api_saved_views_list():
    """List saved views."""
    views = get_saved_views()
    return {"views": views}


@api_router.post("/saved-views")
async def api_saved_views_create(request: Request):
    """Create a saved view."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = data.get("name", "").strip()
    filters = data.get("filters", {})
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    user = _get_user(request)
    view_id = create_saved_view(name, json.dumps(filters), user)
    return {"ok": True, "id": view_id}


@api_router.delete("/saved-views/{view_id}")
async def api_saved_views_delete(view_id: int):
    """Delete a saved view."""
    ok = delete_saved_view(view_id)
    if not ok:
        raise HTTPException(status_code=404, detail="View not found")
    return {"ok": True}


@api_router.post("/export")
async def api_history_export(request: Request):
    """Generate PDF/CSV/XLSX for an incident. Returns download URL."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    incident_id = data.get("incident_id")
    formats = data.get("formats", ["pdf"])

    if not incident_id:
        raise HTTPException(status_code=400, detail="incident_id is required")

    incident = fetch_incident_detail(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        artifact_paths = render_incident_report(incident, formats)
    except Exception as e:
        logger.error("Export failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    download_links = {}
    for fmt, path in artifact_paths.items():
        download_links[fmt] = f"/api/history/download/{incident_id}/{fmt}"
        log_export(incident_id, fmt, path)

    return {
        "ok": True,
        "incident_id": incident_id,
        "formats": list(artifact_paths.keys()),
        "download_links": download_links,
    }


@api_router.post("/send")
async def api_history_send(request: Request):
    """Send incident report via email/SMS/Signal/Webex/webhook."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    incident_id = data.get("incident_id")
    channel = data.get("channel", "").lower()
    destination = data.get("destination", "").strip()

    if not incident_id:
        raise HTTPException(status_code=400, detail="incident_id is required")
    if not channel:
        raise HTTPException(status_code=400, detail="channel is required")
    if not destination:
        raise HTTPException(status_code=400, detail="destination is required")

    incident = fetch_incident_detail(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Generate HTML for the report
    html_body = render_incident_html(incident)
    run_num = incident.get("incident_number") or incident.get("run_number") or incident_id
    subject = f"Incident Report #{run_num} — {incident.get('type', 'Unknown')}"
    summary = f"Incident #{run_num} | {incident.get('type','')} | {incident.get('location','')} | {incident.get('status','')}"

    # Generate PDF attachment if available
    pdf_path = None
    try:
        artifacts = render_incident_report(incident, ["pdf"])
        pdf_path = artifacts.get("pdf")
    except Exception:
        pass

    # Bridge to existing delivery channels
    result = None
    try:
        if channel == "email":
            from app.reporting.delivery import EmailDelivery
            delivery = EmailDelivery()
            result = delivery.send(
                recipient=destination,
                subject=subject,
                body_text=summary,
                body_html=html_body,
                attachments=[pdf_path] if pdf_path else [],
            )
        elif channel == "sms":
            from app.reporting.delivery import SMSDelivery
            delivery = SMSDelivery()
            result = delivery.send(
                recipient=destination,
                subject=subject,
                body_text=summary,
            )
        elif channel == "signal":
            from app.reporting.delivery import SignalDelivery
            delivery = SignalDelivery()
            result = delivery.send(
                recipient=destination,
                subject=subject,
                body_text=summary,
                attachments=[pdf_path] if pdf_path else [],
            )
        elif channel == "webex":
            from app.reporting.delivery import WebexDelivery
            delivery = WebexDelivery()
            result = delivery.send(
                recipient=destination,
                subject=subject,
                body_text=summary,
                body_html=html_body,
            )
        elif channel == "webhook":
            from app.reporting.delivery import WebhookDelivery
            delivery = WebhookDelivery()
            result = delivery.send(
                recipient=destination,
                subject=subject,
                body_text=summary,
                body_html=html_body,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported channel: {channel}")

    except ImportError as ie:
        logger.error("Delivery channel import failed: %s", ie)
        log_delivery(incident_id, channel, destination, "{}", "failed", error_text=str(ie))
        return JSONResponse({"ok": False, "error": f"Delivery channel not available: {ie}"}, status_code=500)
    except Exception as e:
        logger.error("Send failed: %s\n%s", e, traceback.format_exc())
        log_delivery(incident_id, channel, destination, "{}", "failed", error_text=str(e))
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # Log delivery
    status = "sent" if result and result.success else "failed"
    error = result.error if result and not result.success else None
    provider_id = result.message_id if result else None
    log_delivery(
        incident_id, channel, destination,
        json.dumps({"subject": subject}),
        status, provider_id, error,
    )

    return {
        "ok": result.success if result else False,
        "channel": channel,
        "destination": destination,
        "status": status,
        "message_id": provider_id,
        "error": error,
    }


@api_router.get("/download/{incident_id}/{fmt}")
async def api_history_download(incident_id: int, fmt: str):
    """Download an exported incident artifact."""
    artifact_dir = Path("artifacts/history") / str(incident_id)
    if not artifact_dir.exists():
        raise HTTPException(status_code=404, detail="No exports found for this incident")

    # Find most recent file of the requested format
    ext_map = {"pdf": ".pdf", "csv": ".csv", "xlsx": ".xlsx", "html": ".html"}
    ext = ext_map.get(fmt)
    if not ext:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    files = sorted(artifact_dir.glob(f"*{ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail=f"No {fmt} export found")

    media_types = {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
    }
    return FileResponse(
        str(files[0]),
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=files[0].name,
    )


# ============================================================================
# Catch-all: Incident Detail (MUST be last among GET routes)
# ============================================================================

@api_router.get("/{incident_id}")
async def api_history_detail(incident_id: int):
    """Full incident data (JSON)."""
    incident = fetch_incident_detail(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"ok": True, "incident": incident}


# ============================================================================
# Registration
# ============================================================================

def register_history_routes(app):
    """Register all history routers with the FastAPI application."""
    app.include_router(api_router)
    app.include_router(modal_router)
    logger.info("History module registered: /api/history, /modals/history")
