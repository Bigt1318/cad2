# ============================================================================
# FORD CAD - Webhook Delivery Channel
# ============================================================================
# Supports Slack, Teams, and custom webhooks.
# ============================================================================

import json
import logging
import urllib.request
import urllib.error
from typing import Optional, Dict

from .base import DeliveryChannel, DeliveryResult
from ..config import get_config

logger = logging.getLogger("reporting.delivery.webhook")


class WebhookDelivery(DeliveryChannel):
    """Webhook delivery for Slack, Teams, etc."""

    channel_name = "webhook"

    def is_configured(self) -> bool:
        """Check if any webhook is configured."""
        return bool(
            get_config("slack_webhook_url")
            or get_config("teams_webhook_url")
        )

    def test_connection(self) -> bool:
        """Test webhook configuration."""
        # Webhooks are fire-and-forget, hard to test without sending
        return self.is_configured()

    def send(
        self,
        recipient: str,  # webhook URL
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        webhook_type: str = "slack",
        **kwargs,
    ) -> DeliveryResult:
        """Send to webhook."""
        if webhook_type == "slack":
            return self._send_slack(recipient, subject, body_text)
        elif webhook_type == "teams":
            return self._send_teams(recipient, subject, body_text)
        else:
            return self._send_generic(recipient, subject, body_text)

    def _send_slack(
        self,
        webhook_url: str,
        subject: str,
        body_text: str,
    ) -> DeliveryResult:
        """Send to Slack webhook."""
        payload = {
            "text": f"*{subject}*\n{body_text}",
            "mrkdwn": True,
        }

        return self._post_webhook(webhook_url, payload, "slack")

    def _send_teams(
        self,
        webhook_url: str,
        subject: str,
        body_text: str,
    ) -> DeliveryResult:
        """Send to Microsoft Teams webhook."""
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "1e40af",
            "summary": subject,
            "sections": [
                {
                    "activityTitle": subject,
                    "text": body_text,
                }
            ],
        }

        return self._post_webhook(webhook_url, payload, "teams")

    def _send_generic(
        self,
        webhook_url: str,
        subject: str,
        body_text: str,
    ) -> DeliveryResult:
        """Send to generic webhook."""
        payload = {
            "subject": subject,
            "body": body_text,
            "source": "FORD CAD",
        }

        return self._post_webhook(webhook_url, payload, "webhook")

    def _post_webhook(
        self,
        url: str,
        payload: Dict,
        channel_type: str,
    ) -> DeliveryResult:
        """Post to webhook URL."""
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.getcode()

            if status in (200, 201, 202, 204):
                logger.info(f"Webhook delivered to {channel_type}")
                return DeliveryResult(
                    success=True,
                    recipient=url[:50] + "...",
                    channel=channel_type,
                )
            else:
                return DeliveryResult(
                    success=False,
                    recipient=url[:50] + "...",
                    channel=channel_type,
                    error=f"Webhook returned status {status}",
                )

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            logger.error(f"Webhook error: {error_body}")
            return DeliveryResult(
                success=False,
                recipient=url[:50] + "...",
                channel=channel_type,
                error=f"Webhook error: {e.code}",
            )
        except Exception as e:
            logger.error(f"Webhook failed: {e}")
            return DeliveryResult(
                success=False,
                recipient=url[:50] + "...",
                channel=channel_type,
                error=str(e),
            )
