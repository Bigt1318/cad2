# ============================================================================
# FORD-CAD Chat API Routes — Channel-Based Messaging v2
# ============================================================================

import os
import uuid
import hashlib
import json
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, HTMLResponse

logger = logging.getLogger(__name__)

# Allowed upload extensions and max size
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx",
                      ".xls", ".xlsx", ".txt", ".csv", ".webm", ".ogg", ".mp3"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = os.path.join("static", "uploads", "chat")


def register_chat_routes(app: FastAPI, templates, get_conn):
    """Register all /api/chat/* routes."""

    from .chat_engine import get_chat_engine
    from .websocket import get_broadcaster

    def engine():
        return get_chat_engine()

    def _user(request: Request):
        """Extract current user from session. Prioritize dispatcher_unit for proper attribution."""
        uid = (
            request.session.get("dispatcher_unit")
            or request.session.get("unit_id")
            or request.session.get("unit")
            or request.session.get("user")
            or "DISPATCH"
        )
        return str(uid)

    def _is_dispatcher(request: Request):
        return request.session.get("is_admin") or _user(request) == "DISPATCH"

    # ================================================================
    # HTML FRAGMENT ENDPOINTS (for HTMX / drawer)
    # ================================================================

    @app.get("/modal/messaging", response_class=HTMLResponse)
    async def chat_drawer(request: Request):
        """Full messaging drawer HTML fragment."""
        user_id = _user(request)
        return templates.TemplateResponse("chat/drawer.html", {
            "request": request,
            "user_id": user_id,
            "is_dispatcher": _is_dispatcher(request),
        })

    @app.get("/api/chat/channel/{channel_id}/fragment", response_class=HTMLResponse)
    async def chat_thread_fragment(request: Request, channel_id: int):
        """Channel thread view fragment."""
        user_id = _user(request)
        eng = engine()
        channel = eng.get_channel(channel_id)
        if not channel:
            raise HTTPException(404, "Channel not found")
        messages = eng.get_messages(channel_id, limit=50)
        members = eng.get_members(channel_id)

        # Determine other party name for DMs
        other_name = None
        if channel["type"] == "dm":
            for m in members:
                if m["member_id"] != user_id:
                    other_name = m.get("display_name") or m["member_id"]
                    break

        broadcaster = get_broadcaster()
        presence = broadcaster.get_all_presence()

        return templates.TemplateResponse("chat/thread.html", {
            "request": request,
            "channel": channel,
            "messages": messages,
            "members": members,
            "user_id": user_id,
            "other_name": other_name,
            "presence": presence,
            "is_dispatcher": _is_dispatcher(request),
        })

    @app.get("/api/chat/search/fragment", response_class=HTMLResponse)
    async def chat_search_fragment(request: Request, q: str = ""):
        """Search results HTML fragment."""
        user_id = _user(request)
        results = engine().search(user_id, q, limit=30) if len(q) >= 2 else []
        return templates.TemplateResponse("chat/search_results.html", {
            "request": request,
            "results": results,
            "query": q,
            "user_id": user_id,
        })

    @app.get("/api/chat/group/create", response_class=HTMLResponse)
    async def chat_group_create_form(request: Request):
        """Create group/ops channel modal."""
        return templates.TemplateResponse("chat/group_create.html", {
            "request": request,
            "user_id": _user(request),
        })

    @app.get("/api/chat/channel/{channel_id}/info", response_class=HTMLResponse)
    async def chat_channel_info(request: Request, channel_id: int):
        """Channel info panel."""
        eng = engine()
        channel = eng.get_channel(channel_id)
        if not channel:
            raise HTTPException(404, "Channel not found")
        members = eng.get_members(channel_id)
        broadcaster = get_broadcaster()
        presence = broadcaster.get_all_presence()
        return templates.TemplateResponse("chat/channel_info.html", {
            "request": request,
            "channel": channel,
            "members": members,
            "presence": presence,
            "user_id": _user(request),
        })

    @app.get("/api/chat/broadcast/form", response_class=HTMLResponse)
    async def chat_broadcast_form(request: Request):
        """Broadcast compose form (dispatcher only)."""
        if not _is_dispatcher(request):
            raise HTTPException(403, "Dispatcher access required")
        # Get available units
        conn = get_conn()
        try:
            units = conn.execute("SELECT unit_id, unit_name, shift FROM Units WHERE status != 'OFF' ORDER BY unit_id").fetchall()
            units = [dict(u) for u in units]
        except Exception:
            units = []
        finally:
            conn.close()
        return templates.TemplateResponse("chat/broadcast.html", {
            "request": request,
            "user_id": _user(request),
            "units": units,
        })

    # ================================================================
    # JSON API ENDPOINTS
    # ================================================================

    @app.get("/api/chat/channels")
    async def list_channels(request: Request):
        """Get user's channels with unread counts."""
        user_id = _user(request)
        channels = engine().get_channels(user_id)
        broadcaster = get_broadcaster()
        presence = broadcaster.get_all_presence()
        return {"ok": True, "channels": channels, "presence": presence}

    @app.post("/api/chat/channels")
    async def create_channel(request: Request):
        """Create an ops/group channel."""
        data = await request.json()
        user_id = _user(request)
        title = data.get("title", "New Group")
        member_ids = data.get("members", [])

        eng = engine()
        channel = eng.create_ops_channel(title, user_id)
        # Add creator as admin
        eng.add_member(channel["id"], "unit", user_id, display_name=user_id, role="admin")
        # Add other members
        for mid in member_ids:
            eng.add_member(channel["id"], "unit", mid, display_name=mid)

        return {"ok": True, "channel": channel}

    @app.get("/api/chat/channel/{channel_id}/messages")
    async def get_messages(request: Request, channel_id: int, limit: int = 50, before: int = None):
        """Get paginated messages for a channel."""
        messages = engine().get_messages(channel_id, limit=limit, before_id=before)
        return {"ok": True, "messages": messages}

    @app.post("/api/chat/channel/{channel_id}/send")
    async def send_message(request: Request, channel_id: int):
        """Send a message to a channel."""
        data = await request.json()
        user_id = _user(request)
        body = data.get("body", "").strip()
        if not body:
            raise HTTPException(400, "Message body required")

        msg = engine().send_message(
            channel_id=channel_id,
            sender_type="unit",
            sender_id=user_id,
            body=body,
            sender_name=data.get("sender_name") or user_id,
            msg_type=data.get("msg_type", "text"),
            priority=data.get("priority", "normal"),
            reply_to_id=data.get("reply_to_id"),
            metadata=data.get("metadata"),
            require_ack=data.get("require_ack", False),
        )
        return {"ok": True, "message": msg}

    @app.put("/api/chat/messages/{message_id}")
    async def edit_message(request: Request, message_id: int):
        """Edit a message (sender only)."""
        data = await request.json()
        user_id = _user(request)
        new_body = data.get("body", "").strip()
        if not new_body:
            raise HTTPException(400, "Body required")

        msg = engine().edit_message(message_id, new_body, user_id)
        if not msg:
            raise HTTPException(403, "Cannot edit this message")
        return {"ok": True, "message": msg}

    @app.delete("/api/chat/messages/{message_id}")
    async def delete_message(request: Request, message_id: int):
        """Soft-delete a message (sender only)."""
        user_id = _user(request)
        ok = engine().delete_message(message_id, user_id)
        if not ok:
            raise HTTPException(403, "Cannot delete this message")
        return {"ok": True}

    @app.post("/api/chat/messages/{message_id}/receipt")
    async def post_receipt(request: Request, message_id: int):
        """Mark delivered/read/ack."""
        data = await request.json()
        user_id = _user(request)
        status = data.get("status")
        if status == "delivered":
            engine().mark_delivered(message_id, user_id)
        elif status == "read":
            engine().mark_read(message_id, user_id)
        elif status == "ack":
            engine().mark_ack(message_id, user_id)
        else:
            raise HTTPException(400, "Invalid status")
        return {"ok": True}

    @app.post("/api/chat/messages/{message_id}/react")
    async def add_reaction_route(request: Request, message_id: int):
        """Add a reaction."""
        data = await request.json()
        user_id = _user(request)
        reaction = data.get("reaction", "")
        if not reaction:
            raise HTTPException(400, "Reaction required")
        ok = engine().react(message_id, user_id, reaction)
        reactions = engine().get_reactions(message_id)
        return {"ok": ok, "reactions": reactions}

    @app.delete("/api/chat/messages/{message_id}/react/{reaction}")
    async def remove_reaction_route(request: Request, message_id: int, reaction: str):
        """Remove a reaction."""
        user_id = _user(request)
        ok = engine().unreact(message_id, user_id, reaction)
        reactions = engine().get_reactions(message_id)
        return {"ok": ok, "reactions": reactions}

    @app.post("/api/chat/upload")
    async def upload_file(request: Request, file: UploadFile = File(...)):
        """Upload a file attachment."""
        user_id = _user(request)

        # Validate extension
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"File type {ext} not allowed")

        # Read and validate size
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(400, "File exceeds 10MB limit")

        # Build path: static/uploads/chat/YYYY/MM/DD/{uuid}_{filename}
        now = datetime.now()
        date_path = os.path.join(UPLOAD_DIR, now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"))
        os.makedirs(date_path, exist_ok=True)

        safe_name = file.filename.replace(" ", "_").replace("..", "")
        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        full_path = os.path.join(date_path, unique_name)

        with open(full_path, "wb") as f:
            f.write(content)

        sha = hashlib.sha256(content).hexdigest()

        # Generate thumbnail for images
        thumb_path = None
        mime = file.content_type or ""
        if mime.startswith("image/"):
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(content))
                img.thumbnail((200, 200))
                thumb_name = f"thumb_{unique_name}"
                thumb_full = os.path.join(date_path, thumb_name)
                img.save(thumb_full)
                thumb_path = thumb_full.replace("\\", "/")
            except Exception:
                pass

        return {
            "ok": True,
            "attachment": {
                "filename": file.filename,
                "path": full_path.replace("\\", "/"),
                "mime": mime,
                "size": len(content),
                "sha256": sha,
                "thumbnail_path": thumb_path,
            }
        }

    @app.get("/api/chat/search")
    async def search_messages(request: Request, q: str = "", type: str = None,
                               sender: str = None, limit: int = 50):
        """Search messages across user's channels."""
        user_id = _user(request)
        if len(q) < 2:
            return {"ok": True, "results": []}
        results = engine().search(user_id, q, channel_type=type, sender_id=sender, limit=limit)
        return {"ok": True, "results": results}

    @app.post("/api/chat/broadcast")
    async def send_broadcast(request: Request):
        """Send broadcast to multiple units (dispatcher only)."""
        if not _is_dispatcher(request):
            raise HTTPException(403, "Dispatcher access required")
        data = await request.json()
        user_id = _user(request)
        targets = data.get("targets", [])
        body = data.get("body", "").strip()
        priority = data.get("priority", "normal")
        require_ack = data.get("require_ack", False)

        if not targets or not body:
            raise HTTPException(400, "Targets and body required")

        messages = engine().broadcast(
            targets=targets,
            body=body,
            sender_id=user_id,
            sender_name=data.get("sender_name") or user_id,
            priority=priority,
            require_ack=require_ack,
        )
        return {"ok": True, "count": len(messages)}

    @app.get("/api/chat/presence")
    async def get_presence(request: Request):
        """Get all presence data."""
        broadcaster = get_broadcaster()
        return {"ok": True, "presence": broadcaster.get_all_presence()}

    @app.post("/api/chat/presence")
    async def set_presence(request: Request):
        """Set own presence status."""
        data = await request.json()
        user_id = _user(request)
        status = data.get("status", "available")
        broadcaster = get_broadcaster()
        import asyncio
        await broadcaster.set_user_status(user_id, status)
        return {"ok": True, "status": status}

    @app.post("/api/chat/dm/{unit_id}")
    async def open_dm(request: Request, unit_id: str):
        """Open/create a DM with a unit."""
        user_id = _user(request)
        if user_id == unit_id:
            raise HTTPException(400, "Cannot DM yourself")
        channel = engine().get_or_create_dm(user_id, unit_id,
                                             name1=user_id, name2=unit_id)
        return {"ok": True, "channel": channel}

    @app.get("/api/chat/units/available")
    async def list_available_units(request: Request):
        """List units available for messaging."""
        conn = get_conn()
        try:
            rows = conn.execute("""
                SELECT unit_id, unit_name, status, shift
                FROM Units WHERE status != 'OFF'
                ORDER BY unit_id
            """).fetchall()
            units = [dict(r) for r in rows]
        except Exception:
            units = []
        finally:
            conn.close()
        return {"ok": True, "units": units}

    @app.post("/api/chat/channel/{channel_id}/read")
    async def mark_channel_read(request: Request, channel_id: int):
        """Mark all messages in channel as read."""
        user_id = _user(request)
        count = engine().mark_read_bulk(channel_id, user_id)
        return {"ok": True, "count": count}

    @app.post("/api/chat/channel/{channel_id}/members")
    async def add_member(request: Request, channel_id: int):
        """Add a member to a channel."""
        data = await request.json()
        member_id = data.get("member_id")
        if not member_id:
            raise HTTPException(400, "member_id required")
        member = engine().add_member(channel_id, "unit", member_id,
                                      display_name=data.get("display_name", member_id))
        return {"ok": True, "member": member}

    @app.delete("/api/chat/channel/{channel_id}/members/{member_id}")
    async def remove_member(request: Request, channel_id: int, member_id: str):
        """Remove a member from a channel."""
        ok = engine().remove_member(channel_id, "unit", member_id)
        return {"ok": ok}

    # ================================================================
    # PREFERENCES & SETTINGS
    # ================================================================

    @app.get("/api/chat/preferences")
    async def get_preferences(request: Request):
        """Load all user preferences from chat_preferences table."""
        user_id = _user(request)
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT channel_id, pref_key, pref_value FROM chat_preferences WHERE user_id = ?",
                (user_id,)
            ).fetchall()
            prefs = {}
            for r in rows:
                ch = r["channel_id"] or 0
                key = f"{ch}:{r['pref_key']}" if ch != 0 else r["pref_key"]
                prefs[key] = r["pref_value"]
            return {"ok": True, "preferences": prefs}
        except Exception as e:
            logger.warning(f"[CHAT] Failed to load preferences: {e}")
            return {"ok": True, "preferences": {}}
        finally:
            conn.close()

    @app.post("/api/chat/preferences")
    async def save_preferences(request: Request):
        """Batch upsert preferences."""
        user_id = _user(request)
        data = await request.json()
        prefs = data.get("preferences", {})
        conn = get_conn()
        try:
            for key, value in prefs.items():
                # Keys like "sound_enabled" are global (channel_id=0)
                # Keys like "5:muted" are per-channel
                if ":" in key and key.split(":")[0].isdigit():
                    parts = key.split(":", 1)
                    channel_id = int(parts[0])
                    pref_key = parts[1]
                else:
                    channel_id = 0
                    pref_key = key
                conn.execute(
                    """INSERT INTO chat_preferences (user_id, channel_id, pref_key, pref_value)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id, channel_id, pref_key) DO UPDATE SET pref_value = excluded.pref_value""",
                    (user_id, channel_id, pref_key, str(value))
                )
            conn.commit()
            return {"ok": True}
        except Exception as e:
            logger.error(f"[CHAT] Failed to save preferences: {e}")
            raise HTTPException(500, "Failed to save preferences")
        finally:
            conn.close()

    @app.delete("/api/chat/channel/{channel_id}/messages")
    async def clear_channel_messages(request: Request, channel_id: int):
        """Soft-delete all messages in a channel for this user."""
        user_id = _user(request)
        conn = get_conn()
        try:
            # Verify user is a member of the channel
            member = conn.execute(
                "SELECT 1 FROM chat_members WHERE channel_id = ? AND member_id = ?",
                (channel_id, user_id)
            ).fetchone()
            if not member:
                raise HTTPException(403, "Not a member of this channel")
            now = datetime.now().isoformat()
            result = conn.execute(
                "UPDATE chat_messages SET deleted_at = ? WHERE channel_id = ? AND deleted_at IS NULL",
                (now, channel_id)
            )
            conn.commit()
            count = result.rowcount
            return {"ok": True, "cleared": count}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[CHAT] Failed to clear channel messages: {e}")
            raise HTTPException(500, "Failed to clear messages")
        finally:
            conn.close()

    @app.get("/api/chat/settings/fragment", response_class=HTMLResponse)
    async def chat_settings_fragment(request: Request):
        """Settings panel HTML fragment."""
        return templates.TemplateResponse("chat/settings.html", {
            "request": request,
            "user_id": _user(request),
        })

    # ================================================================
    # CHANNEL ADMIN (archive, rename, set topic)
    # ================================================================

    @app.post("/api/chat/channel/{channel_id}/archive")
    async def archive_channel(request: Request, channel_id: int):
        """Archive a channel (admin/dispatcher only)."""
        if not _is_dispatcher(request):
            raise HTTPException(403, "Dispatcher access required")
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE chat_channels SET is_archived = 1, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), channel_id)
            )
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "channel_id": channel_id, "archived": True}

    @app.post("/api/chat/channel/{channel_id}/restore")
    async def restore_channel(request: Request, channel_id: int):
        """Restore an archived channel."""
        if not _is_dispatcher(request):
            raise HTTPException(403, "Dispatcher access required")
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE chat_channels SET is_archived = 0, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), channel_id)
            )
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "channel_id": channel_id, "archived": False}

    @app.put("/api/chat/channel/{channel_id}")
    async def update_channel(request: Request, channel_id: int):
        """Update channel title (admin/creator only)."""
        data = await request.json()
        title = data.get("title")
        conn = get_conn()
        try:
            if title:
                conn.execute(
                    "UPDATE chat_channels SET title = ?, updated_at = ? WHERE id = ?",
                    (title, datetime.now().isoformat(), channel_id)
                )
                conn.commit()
        finally:
            conn.close()
        return {"ok": True}

    # ================================================================
    # CHAT WEBSOCKET ENDPOINT
    # ================================================================

    from fastapi import WebSocket, WebSocketDisconnect
    from .websocket import get_broadcaster as _get_bc

    @app.websocket("/ws/chat")
    async def chat_websocket(websocket: WebSocket):
        """WebSocket endpoint for chat v2."""
        user_id = websocket.query_params.get("user_id", "UNKNOWN")
        broadcaster = _get_bc()
        await broadcaster.connect(websocket, user_id)

        # Persist presence
        try:
            engine().persist_presence("unit", user_id, "available")
        except Exception:
            pass

        try:
            while True:
                data = await websocket.receive_json()
                await broadcaster.handle_client_message(user_id, data)
        except WebSocketDisconnect:
            await broadcaster.disconnect(websocket)
            try:
                engine().persist_presence("unit", user_id, "offline")
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[WS/Chat] Error for {user_id}: {e}")
            await broadcaster.disconnect(websocket)

    logger.info("[CHAT] Chat v2 routes registered")
