# ============================================================================
# FORD-CAD Messaging — Internal Provider
# ============================================================================
# Handles internal CAD user-to-user messaging via WebSocket/SSE
# ============================================================================

from .base import BaseProvider, ProviderResult, ProviderStatus, MessagePayload
from typing import Dict, List
import uuid


class InternalProvider(BaseProvider):
    """
    Provider for internal CAD user messaging.
    Messages are delivered via WebSocket to connected clients.
    """

    channel = "internal"
    display_name = "Internal Messaging"

    # Reference to the WebSocket broadcaster (set externally)
    broadcaster = None

    def _load_config(self):
        """No external config needed for internal messaging."""
        pass

    def is_configured(self) -> bool:
        """Internal messaging is always available."""
        return True

    async def get_status(self) -> ProviderStatus:
        """Internal messaging is always ready."""
        return ProviderStatus.READY

    def validate_address(self, address: str) -> bool:
        """
        For internal messaging, address is a user_id.
        Basic validation - non-empty string.
        """
        return bool(address and address.strip())

    async def send(self, payload: MessagePayload) -> ProviderResult:
        """
        Send internal message.
        The actual delivery happens via WebSocket in the routes layer.
        This just validates and returns success.
        """
        if not payload.to:
            return ProviderResult.fail("Recipient user ID required")

        if not payload.body:
            return ProviderResult.fail("Message body required")

        # Generate internal message ID
        message_id = f"int_{uuid.uuid4().hex[:12]}"

        # If broadcaster is available, send immediately
        if self.broadcaster:
            try:
                await self.broadcaster.send_to_user(
                    user_id=payload.to,
                    event_type="new_message",
                    data={
                        "message_id": message_id,
                        "body": payload.body,
                        "from": payload.metadata.get("sender_id"),
                        "from_name": payload.metadata.get("sender_name"),
                    }
                )
            except Exception as e:
                # WebSocket delivery is best-effort
                # Message is still stored in DB for later retrieval
                pass

        return ProviderResult.ok(
            message_id=message_id,
            external_status="delivered",
            metadata={"delivery_method": "websocket" if self.broadcaster else "stored"}
        )

    def get_config_schema(self) -> List[Dict]:
        """No configuration needed."""
        return []
