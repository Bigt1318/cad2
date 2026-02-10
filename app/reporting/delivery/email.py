# ============================================================================
# FORD CAD - Email Delivery Channel
# ============================================================================
# Supports SendGrid (preferred) and SMTP fallback.
# ============================================================================

import json
import logging
import smtplib
import urllib.request
import urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List

from .base import DeliveryChannel, DeliveryResult
from ..config import get_config

logger = logging.getLogger("reporting.delivery.email")


class EmailDelivery(DeliveryChannel):
    """Email delivery using SendGrid or SMTP."""

    channel_name = "email"

    def is_configured(self) -> bool:
        """Check if email is configured."""
        provider = get_config("email_provider", "sendgrid")

        if provider == "sendgrid":
            return bool(get_config("sendgrid_api_key"))
        else:
            return bool(get_config("smtp_user") and get_config("smtp_pass"))

    def test_connection(self) -> bool:
        """Test email configuration."""
        provider = get_config("email_provider", "sendgrid")

        if provider == "sendgrid":
            return self._test_sendgrid()
        else:
            return self._test_smtp()

    def _test_sendgrid(self) -> bool:
        """Test SendGrid API connection."""
        api_key = get_config("sendgrid_api_key")
        if not api_key:
            return False

        try:
            req = urllib.request.Request(
                "https://api.sendgrid.com/v3/scopes",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.getcode() == 200
        except Exception as e:
            logger.error(f"SendGrid test failed: {e}")
            return False

    def _test_smtp(self) -> bool:
        """Test SMTP connection."""
        try:
            host = get_config("smtp_host", "smtp.gmail.com")
            port = get_config("smtp_port", 587)
            user = get_config("smtp_user")
            password = get_config("smtp_pass")

            server = smtplib.SMTP(host, port)
            server.starttls()
            server.login(user, password)
            server.quit()
            return True
        except Exception as e:
            logger.error(f"SMTP test failed: {e}")
            return False

    def send(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        **kwargs,
    ) -> DeliveryResult:
        """Send email."""
        provider = get_config("email_provider", "sendgrid")

        if provider == "sendgrid":
            return self._send_sendgrid(recipient, subject, body_text, body_html)
        else:
            return self._send_smtp(recipient, subject, body_text, body_html)

    def send_to_multiple(
        self,
        recipients: List[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> List[DeliveryResult]:
        """Send email to multiple recipients."""
        results = []
        for recipient in recipients:
            result = self.send(recipient, subject, body_text, body_html)
            results.append(result)
        return results

    def _send_sendgrid(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> DeliveryResult:
        """Send email via SendGrid."""
        api_key = get_config("sendgrid_api_key")
        from_email = get_config("from_email", "noreply@fordcad.local")
        from_name = get_config("from_name", "FORD CAD System")

        if not api_key:
            logger.info(
                "SendGrid disabled — would send email to=%s subject=%r body_len=%d",
                recipient, subject, len(body_text),
            )
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="email",
                error="SendGrid API key not configured — delivery skipped (logged)",
            )

        # Build content
        content = [{"type": "text/plain", "value": body_text}]
        if body_html:
            content.append({"type": "text/html", "value": body_html})

        payload = {
            "personalizations": [{"to": [{"email": recipient}]}],
            "from": {"email": from_email, "name": from_name},
            "subject": subject,
            "content": content,
        }

        try:
            req = urllib.request.Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.getcode()
                message_id = resp.headers.get("X-Message-Id", "")

            if status in (200, 201, 202):
                logger.info(f"Email sent via SendGrid to {recipient}")
                return DeliveryResult(
                    success=True,
                    recipient=recipient,
                    channel="email",
                    message_id=message_id,
                )
            else:
                return DeliveryResult(
                    success=False,
                    recipient=recipient,
                    channel="email",
                    error=f"SendGrid returned status {status}",
                )

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            logger.error(f"SendGrid error for {recipient}: {error_body}")
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="email",
                error=f"SendGrid error: {error_body}",
            )
        except Exception as e:
            logger.error(f"Email send failed for {recipient}: {e}")
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="email",
                error=str(e),
            )

    def _send_smtp(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> DeliveryResult:
        """Send email via SMTP."""
        host = get_config("smtp_host", "smtp.gmail.com")
        port = get_config("smtp_port", 587)
        user = get_config("smtp_user")
        password = get_config("smtp_pass")
        from_email = get_config("from_email") or user
        from_name = get_config("from_name", "FORD CAD System")

        if not user or not password:
            logger.info(
                "SMTP disabled — would send email to=%s subject=%r body_len=%d",
                recipient, subject, len(body_text),
            )
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="email",
                error="SMTP not configured — delivery skipped (logged)",
            )

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{from_name} <{from_email}>"
            msg["To"] = recipient

            msg.attach(MIMEText(body_text, "plain"))
            if body_html:
                msg.attach(MIMEText(body_html, "html"))

            server = smtplib.SMTP(host, port)
            server.starttls()
            server.login(user, password)
            server.sendmail(from_email, [recipient], msg.as_string())
            server.quit()

            logger.info(f"Email sent via SMTP to {recipient}")
            return DeliveryResult(
                success=True,
                recipient=recipient,
                channel="email",
            )

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP auth failed: {e}")
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="email",
                error=f"SMTP authentication failed",
            )
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return DeliveryResult(
                success=False,
                recipient=recipient,
                channel="email",
                error=str(e),
            )
