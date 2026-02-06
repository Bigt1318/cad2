# ============================================================================
# FORD CAD - SMS Delivery Channel
# ============================================================================
# Supports Twilio SMS delivery.
# ============================================================================

import json
import logging
import base64
import urllib.request
import urllib.error
from typing import Optional

from .base import DeliveryChannel, DeliveryResult
from ..config import get_config

logger = logging.getLogger("reporting.delivery.sms")


class SMSDelivery(DeliveryChannel):
    """SMS delivery using Twilio."""

    channel_name = "sms"

    def is_configured(self) -> bool:
        """Check if SMS is configured."""
        return bool(
            get_config("twilio_account_sid")
            and get_config("twilio_auth_token")
            and get_config("twilio_from_number")
        )

    def test_connection(self) -> bool:
        """Test Twilio configuration."""
        if not self.is_configured():
            return False

        account_sid = get_config("twilio_account_sid")
        auth_token = get_config("twilio_auth_token")

        try:
            auth = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
            req = urllib.request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
                headers={"Authorization": f"Basic {auth}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.getcode() == 200
        except Exception as e:
            logger.error(f"Twilio test failed: {e}")
            return False

    def send(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        **kwargs,
    ) -> DeliveryResult:
        """Send SMS via Twilio."""
        account_sid = get_config("twilio_account_sid")
        auth_token = get_config("twilio_auth_token")
        from_number = get_config("twilio_from_number")

        if not all([account_sid, auth_token, from_number]):
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="sms",
                error="Twilio not configured",
            )

        # Format phone number
        phone = "".join(c for c in recipient if c.isdigit())
        if not phone.startswith("1") and len(phone) == 10:
            phone = "1" + phone
        phone = "+" + phone

        # Truncate message to 160 chars
        message = body_text[:160] if len(body_text) > 160 else body_text

        try:
            auth = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
            data = urllib.parse.urlencode({
                "From": from_number,
                "To": phone,
                "Body": message,
            }).encode()

            req = urllib.request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                data=data,
                headers={"Authorization": f"Basic {auth}"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                response_data = json.loads(resp.read().decode())
                message_id = response_data.get("sid", "")

            logger.info(f"SMS sent via Twilio to {phone}")
            return DeliveryResult(
                success=True,
                recipient=recipient,
                channel="sms",
                message_id=message_id,
            )

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            logger.error(f"Twilio error for {recipient}: {error_body}")
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="sms",
                error=f"Twilio error: {error_body}",
            )
        except Exception as e:
            logger.error(f"SMS send failed for {recipient}: {e}")
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="sms",
                error=str(e),
            )
