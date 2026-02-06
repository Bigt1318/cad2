# ============================================================================
# FORD-CAD Messaging — Twilio SMS/MMS Provider
# ============================================================================

from .base import BaseProvider, ProviderResult, ProviderStatus, MessagePayload
from typing import Dict, List, Optional
import re
import logging

logger = logging.getLogger(__name__)


class TwilioProvider(BaseProvider):
    """
    Provider for SMS/MMS via Twilio.

    Environment Variables:
    - TWILIO_ACCOUNT_SID: Twilio account SID
    - TWILIO_AUTH_TOKEN: Twilio auth token
    - TWILIO_PHONE_NUMBER: Twilio phone number to send from
    """

    channel = "sms"
    display_name = "Twilio SMS"

    def _load_config(self):
        """Load Twilio configuration."""
        self.account_sid = self._get_env("TWILIO_ACCOUNT_SID")
        self.auth_token = self._get_env("TWILIO_AUTH_TOKEN")
        self.phone_number = self._get_env("TWILIO_PHONE_NUMBER")
        self._client = None

    def _get_client(self):
        """Lazy-load Twilio client."""
        if self._client is None and self.is_configured():
            try:
                from twilio.rest import Client
                self._client = Client(self.account_sid, self.auth_token)
            except ImportError:
                logger.warning("Twilio library not installed. Run: pip install twilio")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
        return self._client

    def is_configured(self) -> bool:
        """Check if Twilio credentials are configured."""
        return bool(
            self.account_sid and
            self.auth_token and
            self.phone_number
        )

    async def get_status(self) -> ProviderStatus:
        """Check Twilio API availability."""
        if not self.is_configured():
            return ProviderStatus.NOT_CONFIGURED

        client = self._get_client()
        if not client:
            return ProviderStatus.UNAVAILABLE

        try:
            # Quick API check - fetch account info
            account = client.api.accounts(self.account_sid).fetch()
            if account.status == "active":
                return ProviderStatus.READY
            else:
                return ProviderStatus.DEGRADED
        except Exception as e:
            logger.error(f"Twilio status check failed: {e}")
            return ProviderStatus.UNAVAILABLE

    def validate_address(self, address: str) -> bool:
        """Validate phone number format."""
        if not address:
            return False

        # Strip to digits only
        digits = re.sub(r'\D', '', address)

        # US numbers: 10 digits (or 11 with country code 1)
        if len(digits) == 10:
            return True
        if len(digits) == 11 and digits[0] == '1':
            return True
        # International: 7-15 digits
        if 7 <= len(digits) <= 15:
            return True

        return False

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to E.164 format."""
        digits = re.sub(r'\D', '', phone)

        # Assume US if 10 digits
        if len(digits) == 10:
            return f"+1{digits}"

        # Already has country code
        if len(digits) == 11 and digits[0] == '1':
            return f"+{digits}"

        # International - assume has country code
        if not digits.startswith('+'):
            return f"+{digits}"

        return digits

    async def send(self, payload: MessagePayload) -> ProviderResult:
        """Send SMS via Twilio."""
        if not self.is_configured():
            return ProviderResult.fail("Twilio not configured")

        if not self.validate_address(payload.to):
            return ProviderResult.fail(f"Invalid phone number: {payload.to}")

        client = self._get_client()
        if not client:
            return ProviderResult.fail("Twilio client not available")

        try:
            to_number = self._normalize_phone(payload.to)
            from_number = payload.from_address or self.phone_number

            # Build message params
            msg_params = {
                "to": to_number,
                "from_": from_number,
                "body": payload.body,
            }

            # Handle MMS attachments
            if payload.attachments:
                media_urls = []
                for att in payload.attachments:
                    if att.get("url"):
                        media_urls.append(att["url"])
                if media_urls:
                    msg_params["media_url"] = media_urls

            # Send message
            message = client.messages.create(**msg_params)

            return ProviderResult.ok(
                message_id=message.sid,
                external_status=message.status,
                raw_response={
                    "sid": message.sid,
                    "status": message.status,
                    "to": message.to,
                    "from": message.from_,
                    "date_created": str(message.date_created),
                }
            )

        except Exception as e:
            logger.error(f"Twilio send failed: {e}")
            return ProviderResult.fail(str(e))

    async def handle_webhook(self, payload: Dict) -> Dict:
        """
        Process Twilio webhook for inbound SMS or status updates.

        Twilio sends:
        - MessageSid, From, To, Body for inbound
        - MessageStatus for delivery updates
        """
        try:
            # Inbound message
            if payload.get("Body"):
                return {
                    "type": "inbound",
                    "external_id": payload.get("MessageSid"),
                    "from_address": payload.get("From"),
                    "to_address": payload.get("To"),
                    "body": payload.get("Body"),
                    "media_urls": [
                        payload.get(f"MediaUrl{i}")
                        for i in range(int(payload.get("NumMedia", 0)))
                    ],
                    "raw": payload,
                }

            # Status callback
            if payload.get("MessageStatus"):
                return {
                    "type": "status_update",
                    "external_id": payload.get("MessageSid"),
                    "status": payload.get("MessageStatus"),
                    "error_code": payload.get("ErrorCode"),
                    "error_message": payload.get("ErrorMessage"),
                    "raw": payload,
                }

            return {"type": "unknown", "raw": payload}

        except Exception as e:
            logger.error(f"Twilio webhook parse error: {e}")
            return {"type": "error", "error": str(e), "raw": payload}

    def get_config_schema(self) -> List[Dict]:
        """Configuration schema for Twilio."""
        return [
            {
                "key": "TWILIO_ACCOUNT_SID",
                "label": "Account SID",
                "type": "text",
                "required": True,
                "description": "Twilio Account SID from console.twilio.com"
            },
            {
                "key": "TWILIO_AUTH_TOKEN",
                "label": "Auth Token",
                "type": "password",
                "required": True,
                "description": "Twilio Auth Token"
            },
            {
                "key": "TWILIO_PHONE_NUMBER",
                "label": "Phone Number",
                "type": "phone",
                "required": True,
                "description": "Twilio phone number in E.164 format (+1xxxxxxxxxx)"
            },
        ]
