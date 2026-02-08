"""
FORD-CAD Mobile — Extended Routes
Adds timeline, photo upload, messaging, and gallery to the mobile MDT.
"""
import os
import uuid
import datetime
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse

from .models import init_mobile_schema, save_photo, get_photos

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "uploads", "photos")


def register_mobile_routes(app: FastAPI):
    """Register extended mobile endpoints."""

    init_mobile_schema()
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    @app.get("/mobile/mdt/{unit_id}/timeline", response_class=HTMLResponse)
    async def mobile_timeline(unit_id: str, request: Request):
        """Event timeline for active incident on this unit's MDT."""
        incident_id = _get_active_incident(unit_id)
        events = []
        if incident_id:
            try:
                from app.eventstream.models import query_events
                events = query_events(limit=50, incident_id=incident_id)
            except Exception:
                pass

        return _render_mobile_timeline(unit_id, incident_id, events)

    @app.post("/mobile/mdt/{unit_id}/photo")
    async def mobile_upload_photo(
        unit_id: str,
        request: Request,
        file: UploadFile = File(...),
        caption: str = Form(""),
        incident_id: int = Form(0),
    ):
        """Upload a photo from mobile device."""
        if not incident_id:
            incident_id = _get_active_incident(unit_id)
        if not incident_id:
            return JSONResponse({"ok": False, "error": "No active incident"}, status_code=400)

        # Generate unique filename
        ext = os.path.splitext(file.filename or "photo.jpg")[1] or ".jpg"
        unique_name = f"{incident_id}_{unit_id}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = os.path.join(UPLOAD_DIR, unique_name)

        # Save file
        contents = await file.read()
        with open(filepath, "wb") as f:
            f.write(contents)

        # Save to DB
        photo_id = save_photo(
            incident_id=incident_id,
            filename=unique_name,
            filepath=f"/static/uploads/photos/{unique_name}",
            mime_type=file.content_type or "image/jpeg",
            file_size=len(contents),
            caption=caption,
            uploaded_by=unit_id,
        )

        # Emit to event stream
        try:
            from app.eventstream.emitter import emit_event
            emit_event("PHOTO_UPLOADED", incident_id=incident_id, unit_id=unit_id,
                       summary=f"Photo uploaded by {unit_id}" + (f": {caption}" if caption else ""))
        except Exception:
            pass

        return {"ok": True, "photo_id": photo_id, "filepath": f"/static/uploads/photos/{unique_name}"}

    @app.get("/mobile/mdt/{unit_id}/photos", response_class=HTMLResponse)
    async def mobile_photos(unit_id: str, request: Request):
        """Photo gallery for active incident."""
        incident_id = _get_active_incident(unit_id)
        photos = get_photos(incident_id) if incident_id else []
        return _render_mobile_photos(unit_id, incident_id, photos)

    @app.get("/mobile/mdt/{unit_id}/messages", response_class=HTMLResponse)
    async def mobile_messages(unit_id: str, request: Request):
        """Mobile chat interface for unit."""
        incident_id = _get_active_incident(unit_id)
        messages = []
        if incident_id:
            try:
                from app.messaging.chat_engine import get_chat_engine
                engine = get_chat_engine()
                # Try to get incident channel messages
                import sqlite3
                conn = sqlite3.connect("cad.db", timeout=30, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                rows = c.execute("""
                    SELECT * FROM chat_messages
                    WHERE channel_id IN (
                        SELECT id FROM chat_channels WHERE key LIKE ?
                    )
                    ORDER BY created_at DESC LIMIT 30
                """, (f"%{incident_id}%",)).fetchall()
                messages = [dict(r) for r in rows]
                conn.close()
            except Exception:
                pass

        return _render_mobile_messages(unit_id, incident_id, messages)

    @app.get("/api/mobile/photos/{incident_id}")
    async def api_mobile_photos(incident_id: int):
        """JSON photo list for an incident."""
        photos = get_photos(incident_id)
        return {"ok": True, "photos": photos}


def _get_active_incident(unit_id: str):
    """Get the active incident for a unit."""
    try:
        import sqlite3
        conn = sqlite3.connect("cad.db", timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        row = c.execute("""
            SELECT incident_id FROM UnitAssignments
            WHERE unit_id = ? AND cleared IS NULL
            ORDER BY dispatched DESC LIMIT 1
        """, (unit_id,)).fetchone()
        conn.close()
        return row["incident_id"] if row else None
    except Exception:
        return None


def _render_mobile_timeline(unit_id, incident_id, events) -> str:
    """Render mobile-optimized timeline."""
    severity_colors = {"info": "#4a5568", "warning": "#d69e2e", "alert": "#e53e3e", "critical": "#e53e3e"}

    rows = ""
    if not events:
        rows = '<div style="text-align:center;color:#64748b;padding:40px;">No events yet</div>'
    else:
        for ev in events:
            color = severity_colors.get(ev.get("severity", "info"), "#4a5568")
            ts = ev.get("timestamp", "")
            time_part = ts[11:19] if len(ts) >= 19 else ts
            rows += f"""<div style="padding:10px 16px;border-left:3px solid {color};margin-bottom:2px;background:rgba(255,255,255,0.03);">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                    <span style="font-size:13px;font-weight:600;color:#e2e8f0;">{ev.get('event_type','')}</span>
                    <span style="font-size:11px;color:#64748b;">{time_part}</span>
                </div>
                <div style="font-size:12px;color:#94a3b8;">{ev.get('summary','')}</div>
                <div style="font-size:11px;color:#64748b;margin-top:2px;">{ev.get('user','')}{(' | ' + str(ev.get('unit_id',''))) if ev.get('unit_id') else ''}</div>
            </div>"""

    return f"""<!DOCTYPE html><html><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
    <title>Timeline - {unit_id}</title>
    <style>body{{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;}}</style>
    </head><body>
    <div style="padding:12px 16px;background:#003478;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;">
        <div style="font-size:16px;font-weight:700;">Timeline</div>
        <div style="font-size:12px;color:#94a3b8;">Inc #{incident_id or 'N/A'}</div>
        <button onclick="history.back()" style="background:#1e3a5f;color:#fff;border:none;padding:6px 12px;border-radius:8px;font-size:12px;">Back</button>
    </div>
    <div id="timeline-events">{rows}</div>
    <script>setInterval(()=>location.reload(), 15000);</script>
    </body></html>"""


def _render_mobile_photos(unit_id, incident_id, photos) -> str:
    """Render mobile photo gallery with upload form."""
    gallery = ""
    if not photos:
        gallery = '<div style="text-align:center;color:#64748b;padding:40px;">No photos yet</div>'
    else:
        for p in photos:
            gallery += f"""<div style="margin-bottom:12px;background:#1e293b;border-radius:12px;overflow:hidden;">
                <img src="{p['filepath']}" style="width:100%;max-height:300px;object-fit:cover;">
                <div style="padding:8px 12px;">
                    <div style="font-size:12px;color:#94a3b8;">{p.get('caption','')}</div>
                    <div style="font-size:11px;color:#64748b;">{p.get('uploaded_by','')} - {p.get('uploaded_at','')}</div>
                </div>
            </div>"""

    return f"""<!DOCTYPE html><html><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
    <title>Photos - {unit_id}</title>
    <style>body{{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;}}</style>
    </head><body>
    <div style="padding:12px 16px;background:#003478;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;">
        <div style="font-size:16px;font-weight:700;">Photos</div>
        <button onclick="history.back()" style="background:#1e3a5f;color:#fff;border:none;padding:6px 12px;border-radius:8px;font-size:12px;">Back</button>
    </div>
    <div style="padding:16px;">
        <form id="upload-form" enctype="multipart/form-data" style="margin-bottom:16px;background:#1e293b;padding:16px;border-radius:12px;">
            <input type="file" id="photo-input" accept="image/*" capture="environment"
                   style="display:block;width:100%;margin-bottom:8px;color:#e2e8f0;font-size:14px;">
            <input type="text" id="photo-caption" placeholder="Caption (optional)"
                   style="width:100%;padding:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;border-radius:8px;margin-bottom:8px;font-size:14px;">
            <button type="button" onclick="uploadPhoto()"
                    style="width:100%;padding:12px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:600;">
                Upload Photo
            </button>
        </form>
        <div id="photo-gallery">{gallery}</div>
    </div>
    <script>
    async function uploadPhoto() {{
        const input = document.getElementById('photo-input');
        const caption = document.getElementById('photo-caption').value;
        if (!input.files.length) return alert('Select a photo');
        const form = new FormData();
        form.append('file', input.files[0]);
        form.append('caption', caption);
        form.append('incident_id', '{incident_id or 0}');
        try {{
            const res = await fetch('/mobile/mdt/{unit_id}/photo', {{method:'POST', body:form}});
            const data = await res.json();
            if (data.ok) location.reload();
            else alert(data.error || 'Upload failed');
        }} catch(e) {{ alert('Error: ' + e.message); }}
    }}
    </script>
    </body></html>"""


def _render_mobile_messages(unit_id, incident_id, messages) -> str:
    """Render mobile chat interface."""
    msg_html = ""
    if not messages:
        msg_html = '<div style="text-align:center;color:#64748b;padding:40px;">No messages yet</div>'
    else:
        for m in reversed(messages):
            is_self = (m.get("sender_id", "") or "").upper() == unit_id.upper()
            align = "flex-end" if is_self else "flex-start"
            bg = "#2563eb" if is_self else "#1e293b"
            msg_html += f"""<div style="display:flex;justify-content:{align};margin-bottom:8px;">
                <div style="max-width:80%;background:{bg};padding:10px 14px;border-radius:12px;">
                    <div style="font-size:11px;color:#94a3b8;margin-bottom:2px;">{m.get('sender_id','')}</div>
                    <div style="font-size:14px;color:#e2e8f0;">{m.get('body','') or m.get('content','')}</div>
                    <div style="font-size:10px;color:#64748b;text-align:right;margin-top:2px;">{m.get('created_at','')[-8:]}</div>
                </div>
            </div>"""

    return f"""<!DOCTYPE html><html><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
    <title>Chat - {unit_id}</title>
    <style>body{{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;display:flex;flex-direction:column;height:100vh;}}</style>
    </head><body>
    <div style="padding:12px 16px;background:#003478;display:flex;align-items:center;justify-content:space-between;">
        <div style="font-size:16px;font-weight:700;">Chat</div>
        <div style="font-size:12px;color:#94a3b8;">Inc #{incident_id or 'N/A'}</div>
        <button onclick="history.back()" style="background:#1e3a5f;color:#fff;border:none;padding:6px 12px;border-radius:8px;font-size:12px;">Back</button>
    </div>
    <div style="flex:1;overflow-y:auto;padding:16px;" id="msg-container">{msg_html}</div>
    <div style="padding:12px 16px;background:#1e293b;display:flex;gap:8px;">
        <input type="text" id="msg-input" placeholder="Type a message..."
               style="flex:1;padding:10px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;border-radius:8px;font-size:14px;">
        <button onclick="sendMsg()" style="background:#2563eb;color:#fff;border:none;padding:10px 16px;border-radius:8px;font-weight:600;">Send</button>
    </div>
    <script>
    async function sendMsg() {{
        const input = document.getElementById('msg-input');
        const text = input.value.trim();
        if (!text) return;
        try {{
            await fetch('/remark', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{incident_id: {incident_id or 0}, text: text, user: '{unit_id}'}})
            }});
            input.value = '';
            setTimeout(() => location.reload(), 500);
        }} catch(e) {{ alert('Error'); }}
    }}
    document.getElementById('msg-input').addEventListener('keydown', function(e) {{
        if (e.key === 'Enter') sendMsg();
    }});
    setInterval(() => location.reload(), 10000);
    </script>
    </body></html>"""
