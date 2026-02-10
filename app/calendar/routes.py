"""Google Calendar API routes for Ford CAD."""

import datetime
import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .models import ensure_calendar_schema
from .google_auth import get_auth_url, handle_callback, get_google_service, save_credentials_to_db
from .sync import sync_from_google, push_to_google, delete_from_google

log = logging.getLogger("ford-cad.calendar")

router = APIRouter()


def _get_conn():
    import sqlite3
    from pathlib import Path
    db = Path(__file__).resolve().parent.parent.parent / "cad.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/api/calendar/auth")
async def calendar_auth(request: Request):
    """Initiate Google OAuth2 flow."""
    base_url = str(request.base_url).rstrip("/")
    url = get_auth_url(base_url)
    if not url:
        return JSONResponse({"error": "Google OAuth not configured. Place client_secret.json in app/calendar/"}, status_code=400)
    return JSONResponse({"auth_url": url})


@router.get("/api/calendar/callback")
async def calendar_callback(request: Request, code: str = ""):
    """OAuth2 callback — exchange code for tokens."""
    if not code:
        return HTMLResponse("<h3>Authorization failed — no code received</h3>", status_code=400)

    base_url = str(request.base_url).rstrip("/")
    result = handle_callback(code, base_url)
    if not result:
        return HTMLResponse("<h3>Authorization failed</h3>", status_code=400)

    conn = _get_conn()
    try:
        ensure_calendar_schema(conn)
        save_credentials_to_db(
            conn,
            result["email"],
            result["access_token"],
            result["refresh_token"],
            result["expiry"],
        )
    finally:
        conn.close()

    return HTMLResponse("""
        <html><body>
        <h3>Google Calendar connected successfully!</h3>
        <p>You can close this window and return to Ford CAD.</p>
        <script>window.opener && window.opener.postMessage('calendar-auth-ok','*'); setTimeout(()=>window.close(),2000);</script>
        </body></html>
    """)


@router.get("/api/calendar/status")
async def calendar_status():
    """Check Google Calendar auth and sync status."""
    conn = _get_conn()
    try:
        ensure_calendar_schema(conn)
        from .google_auth import get_credentials_from_db
        creds = get_credentials_from_db(conn)
        connected = bool(creds and creds.get("refresh_token"))
        last_event = None
        event_count = 0
        if connected:
            try:
                row = conn.execute("SELECT COUNT(*) as cnt FROM CalendarEvents").fetchone()
                event_count = row["cnt"] if row else 0
                last = conn.execute("SELECT updated FROM CalendarEvents ORDER BY updated DESC LIMIT 1").fetchone()
                last_event = last["updated"] if last else None
            except Exception:
                pass
        return JSONResponse({
            "connected": connected,
            "email": creds.get("email", "") if creds else "",
            "event_count": event_count,
            "last_sync": last_event,
        })
    finally:
        conn.close()


@router.get("/api/calendar/events")
async def calendar_events(month: int = 0, year: int = 0):
    """Get calendar events for a given month."""
    now = datetime.date.today()
    y = year or now.year
    m = month or now.month

    conn = _get_conn()
    try:
        ensure_calendar_schema(conn)
        time_min = f"{y}-{m:02d}-01"
        if m == 12:
            time_max = f"{y + 1}-01-01"
        else:
            time_max = f"{y}-{m + 1:02d}-01"

        rows = conn.execute("""
            SELECT id, google_event_id, summary, description, start_time, end_time,
                   all_day, location, source, sync_status, created, updated
            FROM CalendarEvents
            WHERE start_time >= ? AND start_time < ?
            ORDER BY start_time
        """, (time_min, time_max)).fetchall()

        events = [dict(r) for r in rows]
        return JSONResponse({"events": events, "month": m, "year": y})
    finally:
        conn.close()


@router.post("/api/calendar/events")
async def create_event(request: Request):
    """Create a new calendar event, optionally syncing to Google."""
    body = await request.json()
    summary = body.get("summary", "").strip()
    if not summary:
        return JSONResponse({"error": "Summary is required"}, status_code=400)

    description = body.get("description", "")
    start_time = body.get("start_time", "")
    end_time = body.get("end_time", "")
    all_day = 1 if body.get("all_day") else 0
    location = body.get("location", "")

    if not start_time:
        return JSONResponse({"error": "Start time is required"}, status_code=400)
    if not end_time:
        end_time = start_time

    ts = datetime.datetime.now().isoformat()
    conn = _get_conn()
    try:
        ensure_calendar_schema(conn)
        c = conn.execute("""
            INSERT INTO CalendarEvents
            (summary, description, start_time, end_time, all_day, location, source, sync_status, created, updated)
            VALUES (?, ?, ?, ?, ?, ?, 'local', 'pending', ?, ?)
        """, (summary, description, start_time, end_time, all_day, location, ts, ts))
        event_id = c.lastrowid
        conn.commit()

        # Try to push to Google if connected
        google_result = None
        try:
            service = get_google_service(conn)
            if service:
                google_result = push_to_google(conn, service, event_id)
        except Exception as e:
            log.warning(f"Google push failed for new event: {e}")

        return JSONResponse({"ok": True, "id": event_id, "google": google_result})
    finally:
        conn.close()


@router.put("/api/calendar/events/{event_id}")
async def update_event(event_id: int, request: Request):
    """Update an existing calendar event."""
    body = await request.json()
    conn = _get_conn()
    try:
        ensure_calendar_schema(conn)
        row = conn.execute("SELECT * FROM CalendarEvents WHERE id=?", (event_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Event not found"}, status_code=404)

        ev = dict(row)
        summary = body.get("summary", ev["summary"])
        description = body.get("description", ev["description"])
        start_time = body.get("start_time", ev["start_time"])
        end_time = body.get("end_time", ev["end_time"])
        all_day = 1 if body.get("all_day", ev["all_day"]) else 0
        location = body.get("location", ev["location"])
        ts = datetime.datetime.now().isoformat()

        conn.execute("""
            UPDATE CalendarEvents
            SET summary=?, description=?, start_time=?, end_time=?, all_day=?, location=?, updated=?, sync_status='pending'
            WHERE id=?
        """, (summary, description, start_time, end_time, all_day, location, ts, event_id))
        conn.commit()

        # Sync to Google
        try:
            service = get_google_service(conn)
            if service:
                push_to_google(conn, service, event_id)
        except Exception as e:
            log.warning(f"Google push failed for event update: {e}")

        return JSONResponse({"ok": True})
    finally:
        conn.close()


@router.delete("/api/calendar/events/{event_id}")
async def delete_event(event_id: int):
    """Delete a calendar event (and from Google if synced)."""
    conn = _get_conn()
    try:
        ensure_calendar_schema(conn)
        row = conn.execute("SELECT * FROM CalendarEvents WHERE id=?", (event_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Event not found"}, status_code=404)

        # Delete from Google first
        try:
            service = get_google_service(conn)
            if service:
                delete_from_google(conn, service, event_id)
        except Exception as e:
            log.warning(f"Google delete failed: {e}")

        conn.execute("DELETE FROM CalendarEvents WHERE id=?", (event_id,))
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()


@router.post("/api/calendar/sync")
async def force_sync():
    """Force a sync from Google Calendar."""
    conn = _get_conn()
    try:
        ensure_calendar_schema(conn)
        service = get_google_service(conn)
        if not service:
            return JSONResponse({"error": "Google Calendar not connected"}, status_code=400)
        result = sync_from_google(conn, service)
        return JSONResponse(result)
    finally:
        conn.close()


def register_calendar_routes(app_instance):
    """Register calendar routes with the FastAPI app."""
    app_instance.include_router(router)
