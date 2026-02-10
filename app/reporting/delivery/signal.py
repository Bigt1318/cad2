# ============================================================================
# FORD CAD - Signal Webhook Delivery Channel
# ============================================================================
# Delivers report notifications via a Signal webhook endpoint.
#
# Configuration:
#   SIGNAL_WEBHOOK_URL  - The URL of the Signal webhook relay service
#   SIGNAL_NUMBER       - Default recipient phone number (optional)
#
# The webhook expects a POST with JSON body:
#   {"message": "<body_text>", "number": "<recipient>"}
#
# Set these via the ReportingConfig table or set_config():
#   set_config("signal_webhook_url", "https://signal-relay.example.com/send")
# ============================================================================

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

from .base import DeliveryChannel, DeliveryResult
from ..config import get_config

logger = logging.getLogger("reporting.delivery.signal")


class SignalDelivery(DeliveryChannel):
    """Signal messaging delivery via a webhook relay.

    This channel sends report content to a Signal webhook service that
    forwards the message to the specified phone number. The webhook
    is typically a self-hosted signal-cli REST API or similar relay.

    Configuration keys (in ReportingConfig):
        signal_webhook_url  - Base URL of the Signal webhook relay
        signal_number       - Default Signal recipient number (E.164 format)
    """

    channel_name = "signal"

    def is_configured(self) -> bool:
        """Check if Signal delivery is configured.

        Returns True if the webhook URL is set.
        """
        url = get_config("signal_webhook_url", "")
        return bool(url and url.strip())

    def test_connection(self) -> bool:
        """Test Signal webhook connectivity.

        Performs a lightweight check against the configured webhook URL.
        Since most Signal relays do not expose a health endpoint, this
        simply verifies that the URL is configured and reachable.
        """
        if not self.is_configured():
            logger.warning("Signal webhook URL not configured")
            return False

        webhook_url = get_config("signal_webhook_url", "").strip()

        try:
            # Attempt a HEAD request to verify the endpoint is reachable.
            # Fall back gracefully if the relay does not support HEAD.
            req = urllib.request.Request(
                webhook_url,
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.getcode() < 500
        except urllib.error.HTTPError as e:
            # A 405 (Method Not Allowed) still means the server is up
            if e.code in (405, 400):
                return True
            logger.warning("Signal webhook test returned HTTP %d", e.code)
            return False
        except Exception as e:
            logger.error("Signal webhook test failed: %s", e)
            return False

    def send(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        **kwargs,
    ) -> DeliveryResult:
        """Send a message via Signal webhook.

        Args:
            recipient: The phone number to send to (E.164 format, e.g. +15551234567).
                       If empty, the default ``signal_number`` config is used.
            subject:   Subject line (prepended to message body).
            body_text: Plain text body of the message.
            body_html: Ignored for Signal (plain text only).
            **kwargs:  Additional keyword arguments (ignored).

        Returns:
            DeliveryResult indicating success or failure.
        """
        webhook_url = get_config("signal_webhook_url", "").strip()

        if not webhook_url:
            logger.info(
                "Signal disabled — would send to=%s subject=%r body_len=%d",
                recipient, subject, len(body_text),
            )
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel=self.channel_name,
                error="Signal webhook URL not configured — delivery skipped (logged)",
            )

        # Resolve recipient: use provided number, fall back to config default
        target_number = recipient.strip() if recipient else ""
        if not target_number:
            target_number = get_config("signal_number", "").strip()

        if not target_number:
            logger.error("No Signal recipient number provided or configured")
            return DeliveryResult(
                success=False,
                recipient=recipient or "(none)",
                channel=self.channel_name,
                error="No recipient number provided. Supply a phone number "
                      "or set 'signal_number' in reporting config.",
            )

        # Build message: prepend subject as a bold-style header
        if subject:
            message = f"*{subject}*\n\n{body_text}"
        else:
            message = body_text

        # Construct the JSON payload
        payload = {
            "message": message,
            "number": target_number,
        }

        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.getcode()
                response_body = resp.read().decode("utf-8", errors="replace")

            if status in (200, 201, 202, 204):
                # Try to extract a message ID from the response
                message_id = None
                try:
                    resp_data = json.loads(response_body)
                    message_id = resp_data.get("id") or resp_data.get("timestamp")
                    if message_id is not None:
                        message_id = str(message_id)
                except (json.JSONDecodeError, AttributeError):
                    pass

                logger.info(
                    "Signal message sent to %s via webhook (HTTP %d)",
                    target_number, status,
                )
                return DeliveryResult(
                    success=True,
                    recipient=target_number,
                    channel=self.channel_name,
                    message_id=message_id,
                )
            else:
                error_msg = f"Signal webhook returned HTTP {status}"
                logger.warning("%s: %s", error_msg, response_body[:200])
                return DeliveryResult(
                    success=False,
                    recipient=target_number,
                    channel=self.channel_name,
                    error=error_msg,
                )

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            error_msg = f"Signal webhook error (HTTP {e.code}): {error_body}"
            logger.error("Signal delivery failed for %s: %s", target_number, error_msg)
            return DeliveryResult(
                success=False,
                recipient=target_number,
                channel=self.channel_name,
                error=error_msg,
            )

        except urllib.error.URLError as e:
            error_msg = f"Signal webhook connection error: {e.reason}"
            logger.error("Signal delivery failed for %s: %s", target_number, error_msg)
            return DeliveryResult(
                success=False,
                recipient=target_number,
                channel=self.channel_name,
                error=error_msg,
            )

        except Exception as e:
            error_msg = f"Signal delivery unexpected error: {e}"
            logger.error("Signal delivery failed for %s: %s", target_number, error_msg, exc_info=True)
            return DeliveryResult(
                success=False,
                recipient=target_number,
                channel=self.channel_name,
                error=str(e),
            )
