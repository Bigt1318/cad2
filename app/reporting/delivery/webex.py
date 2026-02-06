# ============================================================================
# FORD CAD - Webex Webhook Delivery Channel
# ============================================================================
# Delivers report notifications via a Cisco Webex incoming webhook.
#
# Configuration:
#   WEBEX_WEBHOOK_URL - The incoming webhook URL for a Webex space
#
# The webhook expects a POST with JSON body:
#   {"text": "<body_text>"}
#
# Optionally supports markdown:
#   {"markdown": "<markdown_body>"}
#
# Set via the ReportingConfig table or set_config():
#   set_config("webex_webhook_url", "https://webexapis.com/v1/webhooks/incoming/...")
# ============================================================================

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

from .base import DeliveryChannel, DeliveryResult
from ..config import get_config

logger = logging.getLogger("reporting.delivery.webex")


class WebexDelivery(DeliveryChannel):
    """Cisco Webex incoming webhook delivery channel.

    This channel posts report content to a Webex space via an incoming
    webhook URL. Webex incoming webhooks accept JSON with either a
    ``text`` field (plain text) or a ``markdown`` field (Markdown formatted).

    Configuration keys (in ReportingConfig):
        webex_webhook_url - The full incoming webhook URL for the target space
    """

    channel_name = "webex"

    def is_configured(self) -> bool:
        """Check if Webex delivery is configured.

        Returns True if the webhook URL is set and non-empty.
        """
        url = get_config("webex_webhook_url", "")
        return bool(url and url.strip())

    def test_connection(self) -> bool:
        """Test Webex webhook connectivity.

        Incoming webhooks are fire-and-forget by nature, so a true
        connectivity test would post a message. Instead, we verify
        that the URL is configured and the endpoint responds to a
        lightweight probe.
        """
        if not self.is_configured():
            logger.warning("Webex webhook URL not configured")
            return False

        webhook_url = get_config("webex_webhook_url", "").strip()

        try:
            # Send a minimal probe; Webex incoming webhooks require POST,
            # so a HEAD/GET will likely return 405 (which proves it is up).
            req = urllib.request.Request(
                webhook_url,
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.getcode() < 500
        except urllib.error.HTTPError as e:
            # 405 Method Not Allowed means the webhook endpoint is alive
            if e.code in (405, 400):
                return True
            logger.warning("Webex webhook test returned HTTP %d", e.code)
            return False
        except Exception as e:
            logger.error("Webex webhook test failed: %s", e)
            return False

    def send(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        **kwargs,
    ) -> DeliveryResult:
        """Send a message to a Webex space via incoming webhook.

        Args:
            recipient: Ignored for Webex webhooks (the space is determined
                       by the webhook URL). Kept for interface compatibility.
            subject:   Subject line (prepended to message body).
            body_text: Plain text body of the message.
            body_html: If provided, used to generate a markdown-formatted
                       message. Falls back to plain text.
            **kwargs:  Additional keyword arguments (ignored).

        Returns:
            DeliveryResult indicating success or failure.
        """
        webhook_url = get_config("webex_webhook_url", "").strip()

        if not webhook_url:
            logger.error("Webex webhook URL not configured")
            return DeliveryResult(
                success=False,
                recipient=recipient or "(webex-space)",
                channel=self.channel_name,
                error="Webex webhook URL not configured. "
                      "Set 'webex_webhook_url' in reporting config.",
            )

        # Build the message with a subject header
        if subject:
            full_text = f"**{subject}**\n\n{body_text}"
            markdown_body = f"**{subject}**\n\n{body_text}"
        else:
            full_text = body_text
            markdown_body = body_text

        # Construct the JSON payload.
        # Webex incoming webhooks accept {"text": "..."} and/or {"markdown": "..."}.
        # We send both for maximum compatibility.
        payload = {
            "text": full_text,
            "markdown": markdown_body,
        }

        display_recipient = recipient if recipient else "(webex-space)"

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
                    message_id = resp_data.get("id") or resp_data.get("messageId")
                    if message_id is not None:
                        message_id = str(message_id)
                except (json.JSONDecodeError, AttributeError):
                    pass

                logger.info(
                    "Webex message posted via webhook (HTTP %d)",
                    status,
                )
                return DeliveryResult(
                    success=True,
                    recipient=display_recipient,
                    channel=self.channel_name,
                    message_id=message_id,
                )
            else:
                error_msg = f"Webex webhook returned HTTP {status}"
                logger.warning("%s: %s", error_msg, response_body[:200])
                return DeliveryResult(
                    success=False,
                    recipient=display_recipient,
                    channel=self.channel_name,
                    error=error_msg,
                )

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            error_msg = f"Webex webhook error (HTTP {e.code}): {error_body}"
            logger.error("Webex delivery failed: %s", error_msg)
            return DeliveryResult(
                success=False,
                recipient=display_recipient,
                channel=self.channel_name,
                error=error_msg,
            )

        except urllib.error.URLError as e:
            error_msg = f"Webex webhook connection error: {e.reason}"
            logger.error("Webex delivery failed: %s", error_msg)
            return DeliveryResult(
                success=False,
                recipient=display_recipient,
                channel=self.channel_name,
                error=error_msg,
            )

        except Exception as e:
            error_msg = f"Webex delivery unexpected error: {e}"
            logger.error("Webex delivery failed: %s", error_msg, exc_info=True)
            return DeliveryResult(
                success=False,
                recipient=display_recipient,
                channel=self.channel_name,
                error=str(e),
            )
