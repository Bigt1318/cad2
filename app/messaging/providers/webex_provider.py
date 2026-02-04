# ============================================================================
# FORD-CAD Messaging — WebEx Provider
# ============================================================================

from .base import BaseProvider, ProviderResult, ProviderStatus, MessagePayload
from typing import Dict, List, Optional
import logging
import json

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None

logger = logging.getLogger(__name__)


class WebExProvider(BaseProvider):
    """
    Provider for Cisco WebEx messaging.

    Environment Variables:
    - WEBEX_ACCESS_TOKEN: WebEx Bot or Integration access token
    - WEBEX_ROOM_ID: Default room ID for messages (optional)
    - WEBEX_WEBHOOK_SECRET: Secret for validating webhooks (optional)
    """

    channel = "webex"
    display_name = "Cisco WebEx"

    API_BASE = "https://webexapis.com/v1"

    def _load_config(self):
        """Load WebEx configuration."""
        self.access_token = self._get_env("WEBEX_ACCESS_TOKEN")
        self.default_room_id = self._get_env("WEBEX_ROOM_ID")
        self.webhook_secret = self._get_env("WEBEX_WEBHOOK_SECRET")

    def is_configured(self) -> bool:
        """Check if WebEx credentials are configured."""
        return bool(self.access_token)

    def _headers(self) -> Dict:
        """Get API headers."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def get_status(self) -> ProviderStatus:
        """Check WebEx API availability."""
        if not self.is_configured():
            return ProviderStatus.NOT_CONFIGURED

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.API_BASE}/people/me",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return ProviderStatus.READY
                    elif response.status == 401:
                        logger.warning("WebEx token invalid or expired")
                        return ProviderStatus.NOT_CONFIGURED
                    else:
                        return ProviderStatus.DEGRADED

        except aiohttp.ClientError as e:
            logger.error(f"WebEx status check failed: {e}")
            return ProviderStatus.UNAVAILABLE
        except Exception as e:
            logger.error(f"WebEx status check error: {e}")
            return ProviderStatus.UNAVAILABLE

    def validate_address(self, address: str) -> bool:
        """
        Validate WebEx address.
        Can be: room ID, person ID, or email.
        """
        if not address:
            return False

        # Room IDs start with Y2lzY29 (base64 encoded)
        if address.startswith("Y2lzY29"):
            return True

        # Email format
        if "@" in address:
            return True

        # Person ID format (also base64)
        if len(address) > 20:
            return True

        return False

    async def send(self, payload: MessagePayload) -> ProviderResult:
        """Send message via WebEx."""
        if not HAS_AIOHTTP:
            return ProviderResult.fail("aiohttp not installed - WebEx provider unavailable")

        if not self.is_configured():
            return ProviderResult.fail("WebEx not configured")

        try:
            # Determine destination type
            to = payload.to or self.default_room_id

            if not to:
                return ProviderResult.fail("No recipient specified and no default room configured")

            msg_data = {}

            # Determine if sending to room, person, or email
            if to.startswith("Y2lzY29"):
                # Could be room or person ID
                if "ROOM" in to.upper() or payload.metadata.get("is_room"):
                    msg_data["roomId"] = to
                else:
                    msg_data["toPersonId"] = to
            elif "@" in to:
                msg_data["toPersonEmail"] = to
            else:
                msg_data["roomId"] = to

            # Add message content
            if payload.body_html:
                msg_data["html"] = payload.body_html
            else:
                msg_data["text"] = payload.body

            # WebEx also supports markdown
            if payload.metadata.get("markdown"):
                msg_data["markdown"] = payload.metadata["markdown"]

            # Handle attachments (WebEx uses file URLs or upload)
            if payload.attachments:
                files = []
                for att in payload.attachments:
                    if att.get("url"):
                        files.append(att["url"])
                if files:
                    msg_data["files"] = files

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.API_BASE}/messages",
                    headers=self._headers(),
                    json=msg_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response_data = await response.json()

                    if response.status in (200, 201):
                        return ProviderResult.ok(
                            message_id=response_data.get("id"),
                            external_status="sent",
                            raw_response=response_data
                        )
                    else:
                        error_msg = response_data.get("message", f"HTTP {response.status}")
                        return ProviderResult.fail(
                            error_msg,
                            raw_response=response_data
                        )

        except aiohttp.ClientError as e:
            logger.error(f"WebEx send failed: {e}")
            return ProviderResult.fail(f"Network error: {e}")
        except Exception as e:
            logger.error(f"WebEx send error: {e}")
            return ProviderResult.fail(str(e))

    async def create_room(self, title: str) -> Optional[str]:
        """Create a new WebEx room/space."""
        if not self.is_configured():
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.API_BASE}/rooms",
                    headers=self._headers(),
                    json={"title": title},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status in (200, 201):
                        data = await response.json()
                        return data.get("id")
                    return None

        except Exception as e:
            logger.error(f"WebEx create room failed: {e}")
            return None

    async def add_person_to_room(
        self,
        room_id: str,
        person_email: str = None,
        person_id: str = None
    ) -> bool:
        """Add a person to a WebEx room."""
        if not self.is_configured():
            return False

        try:
            data = {"roomId": room_id}
            if person_email:
                data["personEmail"] = person_email
            elif person_id:
                data["personId"] = person_id
            else:
                return False

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.API_BASE}/memberships",
                    headers=self._headers(),
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    return response.status in (200, 201)

        except Exception as e:
            logger.error(f"WebEx add person failed: {e}")
            return False

    async def handle_webhook(self, payload: Dict) -> Dict:
        """
        Process WebEx webhook for inbound messages.

        WebEx sends:
        - resource: "messages", "memberships", etc.
        - event: "created", "updated", etc.
        - data: message/membership data
        """
        try:
            resource = payload.get("resource")
            event = payload.get("event")
            data = payload.get("data", {})

            if resource == "messages" and event == "created":
                # Need to fetch full message content (WebEx doesn't include it in webhook)
                message_id = data.get("id")
                if message_id and self.is_configured():
                    full_message = await self._get_message(message_id)
                    if full_message:
                        return {
                            "type": "inbound",
                            "external_id": message_id,
                            "from_address": full_message.get("personEmail"),
                            "from_id": full_message.get("personId"),
                            "room_id": full_message.get("roomId"),
                            "body": full_message.get("text"),
                            "body_html": full_message.get("html"),
                            "files": full_message.get("files", []),
                            "raw": full_message,
                        }

                return {
                    "type": "inbound_partial",
                    "external_id": message_id,
                    "room_id": data.get("roomId"),
                    "raw": payload,
                }

            return {"type": "other", "resource": resource, "event": event, "raw": payload}

        except Exception as e:
            logger.error(f"WebEx webhook parse error: {e}")
            return {"type": "error", "error": str(e), "raw": payload}

    async def _get_message(self, message_id: str) -> Optional[Dict]:
        """Fetch full message content by ID."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.API_BASE}/messages/{message_id}",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            logger.error(f"WebEx get message failed: {e}")
            return None

    def get_config_schema(self) -> List[Dict]:
        """Configuration schema for WebEx."""
        return [
            {
                "key": "WEBEX_ACCESS_TOKEN",
                "label": "Access Token",
                "type": "password",
                "required": True,
                "description": "WebEx Bot or Integration access token"
            },
            {
                "key": "WEBEX_ROOM_ID",
                "label": "Default Room ID",
                "type": "text",
                "required": False,
                "description": "Default room/space ID for messages"
            },
            {
                "key": "WEBEX_WEBHOOK_SECRET",
                "label": "Webhook Secret",
                "type": "password",
                "required": False,
                "description": "Secret for validating inbound webhooks"
            },
        ]
