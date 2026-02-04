# ============================================================================
# FORD-CAD Unified Messaging Module
# ============================================================================
# Provides internal and external messaging capabilities including:
# - Internal CAD user messaging (WebSocket/SSE)
# - SMS via Twilio
# - Email via SendGrid
# - Signal (experimental)
# - WebEx integration
# ============================================================================

from .models import init_messaging_schema
from .routes import register_messaging_routes
from .websocket import MessageBroadcaster

__all__ = [
    "init_messaging_schema",
    "register_messaging_routes",
    "MessageBroadcaster",
]
