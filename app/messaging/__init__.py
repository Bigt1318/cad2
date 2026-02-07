# ============================================================================
# FORD-CAD Unified Messaging Module
# ============================================================================
# Provides internal and external messaging capabilities including:
# - Channel-based real-time chat (DM, incident, shift, ops, broadcast)
# - Presence tracking, structured cards, reactions, ACK-required
# - SMS via Twilio
# - Email via SendGrid
# - Signal (experimental)
# - WebEx integration
# ============================================================================

from .models import init_messaging_schema, init_chat_schema
from .routes import register_messaging_routes
from .websocket import MessageBroadcaster
from .chat_engine import ChatEngine, get_chat_engine

__all__ = [
    "init_messaging_schema",
    "init_chat_schema",
    "register_messaging_routes",
    "MessageBroadcaster",
    "ChatEngine",
    "get_chat_engine",
]
