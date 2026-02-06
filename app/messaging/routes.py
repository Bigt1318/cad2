# ============================================================================
# FORD-CAD Messaging — API Routes
# ============================================================================

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from typing import Optional, List, Dict, Any
import json
import logging

from .models import (
    init_messaging_schema,
    MessageChannel, MessageStatus, MessageDirection,
    create_contact, get_contact, find_contact_by_address,
    create_conversation, get_conversation, find_or_create_direct_conversation,
    create_message, update_message_status, get_message,
    get_conversation_messages, get_user_conversations,
    mark_messages_read, get_unread_count, log_webhook,
)
from .providers import (
    InternalProvider, TwilioProvider, SendGridProvider,
    SignalProvider, WebExProvider, ProviderResult, MessagePayload
)
from .websocket import get_broadcaster, get_sse_manager, sse_event_generator

logger = logging.getLogger(__name__)

# Provider registry
PROVIDERS = {
    "internal": InternalProvider,
    "sms": TwilioProvider,
    "email": SendGridProvider,
    "signal": SignalProvider,
    "webex": WebExProvider,
}


def get_provider(channel: str):
    """Get provider instance for a channel."""
    provider_class = PROVIDERS.get(channel)
    if not provider_class:
        return None
    return provider_class()


def register_messaging_routes(app, templates, get_conn):
    """
    Register all messaging routes with the FastAPI app.

    Args:
        app: FastAPI application
        templates: Jinja2 templates
        get_conn: Function to get database connection
    """

    router = APIRouter(prefix="/api/messaging", tags=["messaging"])

    # Initialize schema on startup
    @app.on_event("startup")
    async def init_messaging():
        conn = get_conn()
        init_messaging_schema(conn)
        conn.close()
        logger.info("[Messaging] Schema initialized")

    # =========================================================================
    # UNIFIED SEND API
    # =========================================================================

    @router.post("/send")
    async def send_message(request: Request):
        """
        Unified message send endpoint.

        Body:
        {
            "to": "contact_id or address (phone/email/user_id)",
            "channel": "sms|email|signal|webex|internal" (optional - auto-detect),
            "message": "text content",
            "subject": "email subject" (optional),
            "attachments": [] (optional),
            "conversation_id": int (optional - for replies)
        }
        """
        user = request.session.get("user", "System")
        user_id = request.session.get("unit_id", user)

        try:
            data = await request.json()
        except:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        to = data.get("to")
        channel = data.get("channel")
        message = data.get("message", "").strip()
        subject = data.get("subject")
        attachments = data.get("attachments", [])
        conversation_id = data.get("conversation_id")

        if not to:
            raise HTTPException(status_code=400, detail="Recipient required")
        if not message:
            raise HTTPException(status_code=400, detail="Message required")

        conn = get_conn()

        try:
            # Resolve recipient
            recipient_type = "unknown"
            recipient_id = None
            recipient_name = None
            recipient_address = to

            # Check if "to" is a contact ID
            if str(to).isdigit():
                contact = get_contact(conn, int(to))
                if contact:
                    recipient_type = "contact"
                    recipient_id = str(contact["contact_id"])
                    recipient_name = contact["name"]
                    # Use preferred channel address
                    if not channel:
                        channel = contact.get("preferred_channel", "sms")
                    if channel == "sms":
                        recipient_address = contact.get("phone")
                    elif channel == "email":
                        recipient_address = contact.get("email")
                    elif channel == "signal":
                        recipient_address = contact.get("signal_number")
                    elif channel == "webex":
                        recipient_address = contact.get("webex_person_id")

            # Check if it's an internal user (for internal messaging)
            elif channel == "internal" or (not channel and not "@" in to and not to.replace("-","").replace("+","").isdigit()):
                channel = "internal"
                recipient_type = "user"
                recipient_id = to
                recipient_address = to

            # Auto-detect channel from address format
            if not channel:
                if "@" in to:
                    channel = "email"
                elif to.replace("-","").replace("+","").replace("(","").replace(")","").replace(" ","").isdigit():
                    channel = "sms"
                else:
                    channel = "internal"

            # Get or create conversation
            if not conversation_id:
                # For direct messages, find or create conversation
                sender_participant = {"type": "user", "id": user_id, "name": user}
                recipient_participant = {
                    "type": recipient_type,
                    "id": recipient_id or to,
                    "name": recipient_name or to
                }
                conversation_id = find_or_create_direct_conversation(
                    conn, sender_participant, recipient_participant
                )

            # Create message record
            message_id = create_message(
                conn,
                direction=MessageDirection.OUTBOUND,
                channel=channel,
                sender_type="user",
                sender_id=user_id,
                sender_name=user,
                recipient_type=recipient_type,
                recipient_id=recipient_id,
                recipient_name=recipient_name,
                recipient_address=recipient_address,
                conversation_id=conversation_id,
                subject=subject,
                body=message,
                attachments=attachments,
                status=MessageStatus.PENDING
            )

            # Get provider and send
            provider = get_provider(channel)
            if not provider:
                update_message_status(conn, message_id, MessageStatus.FAILED, error_message=f"Unknown channel: {channel}")
                raise HTTPException(status_code=400, detail=f"Unknown channel: {channel}")

            if not provider.is_configured():
                update_message_status(conn, message_id, MessageStatus.FAILED, error_message=f"{channel} provider not configured")
                raise HTTPException(status_code=503, detail=f"{channel} provider not configured")

            # Build payload
            payload = MessagePayload(
                to=recipient_address,
                body=message,
                subject=subject,
                attachments=attachments,
                metadata={
                    "sender_id": user_id,
                    "sender_name": user,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                }
            )

            # Send
            result = await provider.send(payload)

            # Update message status
            if result.success:
                update_message_status(
                    conn, message_id,
                    MessageStatus.SENT,
                    external_id=result.message_id,
                    external_status=result.external_status,
                    provider_response=result.raw_response
                )

                # Notify via WebSocket for internal messages
                if channel == "internal":
                    broadcaster = get_broadcaster()
                    await broadcaster.send_to_user(
                        recipient_address,
                        "new_message",
                        {
                            "message_id": message_id,
                            "conversation_id": conversation_id,
                            "from_id": user_id,
                            "from_name": user,
                            "body": message,
                            "channel": channel,
                        }
                    )

                return {
                    "ok": True,
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "external_id": result.message_id,
                    "status": MessageStatus.SENT,
                }
            else:
                update_message_status(
                    conn, message_id,
                    MessageStatus.FAILED,
                    error_message=result.error,
                    provider_response=result.raw_response
                )
                return {
                    "ok": False,
                    "message_id": message_id,
                    "error": result.error,
                }

        finally:
            conn.close()

    # =========================================================================
    # CONVERSATIONS
    # =========================================================================

    @router.get("/conversations")
    async def list_conversations(request: Request):
        """Get user's conversations."""
        user_id = request.session.get("unit_id") or request.session.get("user", "unknown")

        conn = get_conn()
        try:
            conversations = get_user_conversations(conn, user_id)
            return {"ok": True, "conversations": conversations}
        finally:
            conn.close()

    @router.get("/conversations/{conversation_id}")
    async def get_conversation_detail(request: Request, conversation_id: int):
        """Get conversation details and messages."""
        user_id = request.session.get("unit_id") or request.session.get("user", "unknown")

        conn = get_conn()
        try:
            conversation = get_conversation(conn, conversation_id)
            if not conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")

            messages = get_conversation_messages(conn, conversation_id)

            # Mark as read
            mark_messages_read(conn, user_id, conversation_id=conversation_id)

            return {
                "ok": True,
                "conversation": conversation,
                "messages": messages,
            }
        finally:
            conn.close()

    @router.get("/conversations/{conversation_id}/messages")
    async def get_messages(
        request: Request,
        conversation_id: int,
        limit: int = Query(50, le=100),
        before_id: Optional[int] = None
    ):
        """Get messages for a conversation with pagination."""
        conn = get_conn()
        try:
            messages = get_conversation_messages(conn, conversation_id, limit, before_id)
            return {"ok": True, "messages": messages}
        finally:
            conn.close()

    @router.post("/conversations/{conversation_id}/read")
    async def mark_conversation_read(request: Request, conversation_id: int):
        """Mark all messages in conversation as read."""
        user_id = request.session.get("unit_id") or request.session.get("user", "unknown")

        conn = get_conn()
        try:
            mark_messages_read(conn, user_id, conversation_id=conversation_id)
            return {"ok": True}
        finally:
            conn.close()

    # =========================================================================
    # CONTACTS
    # =========================================================================

    @router.get("/contacts")
    async def list_contacts(request: Request, search: str = None):
        """List messaging contacts."""
        conn = get_conn()
        try:
            c = conn.cursor()

            if search:
                search_term = f"%{search}%"
                rows = c.execute("""
                    SELECT * FROM MessagingContacts
                    WHERE is_active = 1 AND (
                        name LIKE ? OR phone LIKE ? OR email LIKE ? OR organization LIKE ?
                    )
                    ORDER BY name
                    LIMIT 100
                """, (search_term, search_term, search_term, search_term)).fetchall()
            else:
                rows = c.execute("""
                    SELECT * FROM MessagingContacts
                    WHERE is_active = 1
                    ORDER BY name
                    LIMIT 100
                """).fetchall()

            contacts = [dict(r) for r in rows]
            return {"ok": True, "contacts": contacts}
        finally:
            conn.close()

    @router.post("/contacts")
    async def create_contact_endpoint(request: Request):
        """Create a new contact."""
        try:
            data = await request.json()
        except:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        name = data.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Name required")

        conn = get_conn()
        try:
            contact_id = create_contact(
                conn,
                name=name,
                phone=data.get("phone"),
                email=data.get("email"),
                signal_number=data.get("signal_number"),
                webex_person_id=data.get("webex_person_id"),
                preferred_channel=data.get("preferred_channel", "sms"),
                organization=data.get("organization"),
                notes=data.get("notes"),
                tags=data.get("tags", [])
            )
            return {"ok": True, "contact_id": contact_id}
        finally:
            conn.close()

    @router.get("/contacts/{contact_id}")
    async def get_contact_detail(contact_id: int):
        """Get contact details."""
        conn = get_conn()
        try:
            contact = get_contact(conn, contact_id)
            if not contact:
                raise HTTPException(status_code=404, detail="Contact not found")
            return {"ok": True, "contact": contact}
        finally:
            conn.close()

    # =========================================================================
    # UNREAD COUNT
    # =========================================================================

    @router.get("/unread")
    async def get_unread(request: Request):
        """Get unread message count for current user."""
        user_id = request.session.get("unit_id") or request.session.get("user", "unknown")

        conn = get_conn()
        try:
            count = get_unread_count(conn, user_id)
            return {"ok": True, "unread_count": count}
        finally:
            conn.close()

    # =========================================================================
    # PROVIDER STATUS
    # =========================================================================

    @router.get("/providers")
    async def get_providers():
        """Get status of all messaging providers."""
        statuses = {}
        for channel, provider_class in PROVIDERS.items():
            provider = provider_class()
            statuses[channel] = {
                "name": provider.display_name,
                "configured": provider.is_configured(),
                "status": (await provider.get_status()).value,
                "config_schema": provider.get_config_schema(),
            }
        return {"ok": True, "providers": statuses}

    # =========================================================================
    # WEBHOOKS
    # =========================================================================

    @router.post("/webhooks/twilio")
    async def twilio_webhook(request: Request):
        """Handle Twilio inbound SMS and status callbacks."""
        conn = get_conn()
        try:
            # Parse form data (Twilio sends form-encoded)
            form = await request.form()
            payload = dict(form)

            # Log webhook
            log_webhook(conn, "twilio", json.dumps(payload), payload.get("MessageStatus") or "inbound")

            # Process with provider
            provider = TwilioProvider()
            result = await provider.handle_webhook(payload)

            if result.get("type") == "inbound":
                # Create inbound message
                # Try to find existing contact
                contact = find_contact_by_address(conn, result["from_address"], "sms")

                sender_id = str(contact["contact_id"]) if contact else None
                sender_name = contact["name"] if contact else result["from_address"]

                # Find or create conversation
                # For inbound, we need to figure out the recipient (our CAD)
                # This is simplified - in production you might route to specific users
                message_id = create_message(
                    conn,
                    direction=MessageDirection.INBOUND,
                    channel="sms",
                    sender_type="contact" if contact else "external",
                    sender_id=sender_id,
                    sender_name=sender_name,
                    sender_address=result["from_address"],
                    recipient_address=result.get("to_address"),
                    body=result["body"],
                    attachments=[{"url": u} for u in result.get("media_urls", [])],
                    status=MessageStatus.DELIVERED,
                    metadata={"twilio_sid": result.get("external_id")}
                )

                # Broadcast to connected users
                broadcaster = get_broadcaster()
                await broadcaster.broadcast(
                    "inbound_message",
                    {
                        "message_id": message_id,
                        "channel": "sms",
                        "from_address": result["from_address"],
                        "from_name": sender_name,
                        "body": result["body"],
                    }
                )

            elif result.get("type") == "status_update":
                # Update existing message status
                external_id = result.get("external_id")
                if external_id:
                    c = conn.cursor()
                    msg = c.execute(
                        "SELECT message_id FROM Messages WHERE external_id = ?",
                        (external_id,)
                    ).fetchone()
                    if msg:
                        status_map = {
                            "delivered": MessageStatus.DELIVERED,
                            "read": MessageStatus.READ,
                            "failed": MessageStatus.FAILED,
                            "undelivered": MessageStatus.FAILED,
                        }
                        new_status = status_map.get(result["status"], MessageStatus.SENT)
                        update_message_status(
                            conn, msg["message_id"], new_status,
                            external_status=result["status"],
                            error_message=result.get("error_message")
                        )

            # Twilio expects empty 200 response
            return ""

        finally:
            conn.close()

    @router.post("/webhooks/sendgrid")
    async def sendgrid_webhook(request: Request):
        """Handle SendGrid inbound email and events."""
        conn = get_conn()
        try:
            content_type = request.headers.get("content-type", "")

            if "multipart/form-data" in content_type:
                # Inbound Parse (email)
                form = await request.form()
                payload = dict(form)
            else:
                # Event webhook
                payload = await request.json()

            log_webhook(conn, "sendgrid", json.dumps(payload) if isinstance(payload, dict) else str(payload))

            provider = SendGridProvider()
            result = await provider.handle_webhook(payload)

            if result.get("type") == "inbound":
                contact = find_contact_by_address(conn, result["from_address"], "email")

                message_id = create_message(
                    conn,
                    direction=MessageDirection.INBOUND,
                    channel="email",
                    sender_type="contact" if contact else "external",
                    sender_id=str(contact["contact_id"]) if contact else None,
                    sender_name=result.get("from_name") or result["from_address"],
                    sender_address=result["from_address"],
                    recipient_address=result.get("to_address"),
                    subject=result.get("subject"),
                    body=result.get("body"),
                    body_html=result.get("body_html"),
                    status=MessageStatus.DELIVERED,
                )

                broadcaster = get_broadcaster()
                await broadcaster.broadcast(
                    "inbound_message",
                    {
                        "message_id": message_id,
                        "channel": "email",
                        "from_address": result["from_address"],
                        "subject": result.get("subject"),
                    }
                )

            return {"ok": True}

        finally:
            conn.close()

    @router.post("/webhooks/webex")
    async def webex_webhook(request: Request):
        """Handle WebEx webhooks."""
        conn = get_conn()
        try:
            payload = await request.json()
            log_webhook(conn, "webex", json.dumps(payload), payload.get("event"))

            provider = WebExProvider()
            result = await provider.handle_webhook(payload)

            if result.get("type") == "inbound":
                message_id = create_message(
                    conn,
                    direction=MessageDirection.INBOUND,
                    channel="webex",
                    sender_type="external",
                    sender_address=result.get("from_address"),
                    body=result.get("body"),
                    body_html=result.get("body_html"),
                    status=MessageStatus.DELIVERED,
                    metadata={
                        "webex_message_id": result.get("external_id"),
                        "room_id": result.get("room_id"),
                    }
                )

                broadcaster = get_broadcaster()
                await broadcaster.broadcast(
                    "inbound_message",
                    {
                        "message_id": message_id,
                        "channel": "webex",
                        "from_address": result.get("from_address"),
                        "body": result.get("body"),
                    }
                )

            return {"ok": True}

        finally:
            conn.close()

    # =========================================================================
    # WEBSOCKET
    # =========================================================================

    @app.websocket("/ws/messaging")
    async def messaging_websocket(websocket: WebSocket):
        """WebSocket endpoint for real-time messaging."""
        # Get user from query params or session
        user_id = websocket.query_params.get("user_id")

        if not user_id:
            await websocket.close(code=4001)
            return

        broadcaster = get_broadcaster()
        await broadcaster.connect(websocket, user_id)

        try:
            while True:
                # Receive and handle client messages
                data = await websocket.receive_json()

                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                elif data.get("type") == "typing":
                    # Broadcast typing indicator
                    conversation_id = data.get("conversation_id")
                    if conversation_id:
                        # Get other participants
                        conn = get_conn()
                        try:
                            conv = get_conversation(conn, conversation_id)
                            if conv:
                                for p in conv["participants"]:
                                    if p["id"] != user_id:
                                        await broadcaster.send_to_user(
                                            p["id"],
                                            "typing",
                                            {
                                                "conversation_id": conversation_id,
                                                "user_id": user_id,
                                            }
                                        )
                        finally:
                            conn.close()

                elif data.get("type") == "read":
                    # Mark messages as read
                    conversation_id = data.get("conversation_id")
                    if conversation_id:
                        conn = get_conn()
                        try:
                            mark_messages_read(conn, user_id, conversation_id=conversation_id)
                        finally:
                            conn.close()

        except WebSocketDisconnect:
            pass
        finally:
            await broadcaster.disconnect(websocket)

    # =========================================================================
    # SSE FALLBACK
    # =========================================================================

    @router.get("/events")
    async def sse_endpoint(request: Request):
        """Server-Sent Events endpoint for clients without WebSocket support."""
        user_id = request.session.get("unit_id") or request.session.get("user")
        if not user_id:
            raise HTTPException(status_code=401, detail="Not authenticated")

        return StreamingResponse(
            sse_event_generator(user_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )

    # =========================================================================
    # HTML FRAGMENTS (HTMX)
    # =========================================================================

    @router.get("/panel", response_class=HTMLResponse)
    async def messaging_panel(request: Request):
        """Render messaging panel for dispatch UI."""
        user_id = request.session.get("unit_id") or request.session.get("user", "unknown")

        conn = get_conn()
        try:
            conversations = get_user_conversations(conn, user_id)
            unread = get_unread_count(conn, user_id)

            return templates.TemplateResponse(
                "messaging/panel.html",
                {
                    "request": request,
                    "conversations": conversations,
                    "unread_count": unread,
                    "user_id": user_id,
                }
            )
        finally:
            conn.close()

    @router.get("/conversation/{conversation_id}/fragment", response_class=HTMLResponse)
    async def conversation_fragment(request: Request, conversation_id: int):
        """Render conversation thread fragment."""
        user_id = request.session.get("unit_id") or request.session.get("user", "unknown")

        conn = get_conn()
        try:
            conversation = get_conversation(conn, conversation_id)
            messages = get_conversation_messages(conn, conversation_id)
            mark_messages_read(conn, user_id, conversation_id=conversation_id)

            return templates.TemplateResponse(
                "messaging/conversation.html",
                {
                    "request": request,
                    "conversation": conversation,
                    "messages": messages,
                    "user_id": user_id,
                }
            )
        finally:
            conn.close()

    @router.get("/compose", response_class=HTMLResponse)
    async def compose_modal(request: Request, to: str = None, channel: str = None):
        """Render compose message modal."""
        conn = get_conn()
        try:
            # Get provider statuses
            provider_status = {}
            for ch, provider_class in PROVIDERS.items():
                p = provider_class()
                provider_status[ch] = p.is_configured()

            # Pre-fill recipient if provided
            recipient = None
            if to and to.isdigit():
                recipient = get_contact(conn, int(to))

            return templates.TemplateResponse(
                "messaging/compose.html",
                {
                    "request": request,
                    "recipient": recipient,
                    "to": to,
                    "channel": channel,
                    "providers": provider_status,
                }
            )
        finally:
            conn.close()

    # Register router with app
    app.include_router(router)

    logger.info("[Messaging] Routes registered")
