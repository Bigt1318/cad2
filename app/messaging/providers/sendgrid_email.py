# ============================================================================
# FORD-CAD Messaging — SendGrid Email Provider
# ============================================================================

from .base import BaseProvider, ProviderResult, ProviderStatus, MessagePayload
from typing import Dict, List
import re
import logging
import base64
import os

logger = logging.getLogger(__name__)


class SendGridProvider(BaseProvider):
    """
    Provider for email via SendGrid.

    Environment Variables:
    - SENDGRID_API_KEY: SendGrid API key
    - SENDGRID_FROM_EMAIL: Default sender email
    - SENDGRID_FROM_NAME: Default sender name (optional)
    """

    channel = "email"
    display_name = "SendGrid Email"

    def _load_config(self):
        """Load SendGrid configuration."""
        self.api_key = self._get_env("SENDGRID_API_KEY")
        self.from_email = self._get_env("SENDGRID_FROM_EMAIL")
        self.from_name = self._get_env("SENDGRID_FROM_NAME", "FORD CAD")
        self._client = None

    def _get_client(self):
        """Lazy-load SendGrid client."""
        if self._client is None and self.is_configured():
            try:
                from sendgrid import SendGridAPIClient
                self._client = SendGridAPIClient(self.api_key)
            except ImportError:
                logger.warning("SendGrid library not installed. Run: pip install sendgrid")
            except Exception as e:
                logger.error(f"Failed to initialize SendGrid client: {e}")
        return self._client

    def is_configured(self) -> bool:
        """Check if SendGrid credentials are configured."""
        return bool(self.api_key and self.from_email)

    async def get_status(self) -> ProviderStatus:
        """Check SendGrid API availability."""
        if not self.is_configured():
            return ProviderStatus.NOT_CONFIGURED

        client = self._get_client()
        if not client:
            return ProviderStatus.UNAVAILABLE

        try:
            # Quick API check - get user profile
            response = client.client.user.profile.get()
            if response.status_code == 200:
                return ProviderStatus.READY
            else:
                return ProviderStatus.DEGRADED
        except Exception as e:
            logger.error(f"SendGrid status check failed: {e}")
            return ProviderStatus.UNAVAILABLE

    def validate_address(self, address: str) -> bool:
        """Validate email address format."""
        if not address:
            return False

        # Basic email regex
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, address.strip()))

    async def send(self, payload: MessagePayload) -> ProviderResult:
        """Send email via SendGrid."""
        if not self.is_configured():
            return ProviderResult.fail("SendGrid not configured")

        if not self.validate_address(payload.to):
            return ProviderResult.fail(f"Invalid email address: {payload.to}")

        client = self._get_client()
        if not client:
            return ProviderResult.fail("SendGrid client not available")

        try:
            from sendgrid.helpers.mail import (
                Mail, Email, To, Content, Attachment,
                FileContent, FileName, FileType, Disposition
            )

            # Build email
            from_email = Email(
                payload.from_address or self.from_email,
                self.from_name
            )
            to_email = To(payload.to)
            subject = payload.subject or "Message from FORD CAD"

            # Content
            if payload.body_html:
                content = Content("text/html", payload.body_html)
            else:
                content = Content("text/plain", payload.body)

            mail = Mail(from_email, to_email, subject, content)

            # Add plain text version if we have HTML
            if payload.body_html and payload.body:
                mail.add_content(Content("text/plain", payload.body))

            # Handle attachments
            for att in payload.attachments:
                if att.get("path") and os.path.exists(att["path"]):
                    with open(att["path"], "rb") as f:
                        file_data = base64.b64encode(f.read()).decode()

                    attachment = Attachment()
                    attachment.file_content = FileContent(file_data)
                    attachment.file_name = FileName(att.get("name", os.path.basename(att["path"])))
                    attachment.file_type = FileType(att.get("type", "application/octet-stream"))
                    attachment.disposition = Disposition("attachment")
                    mail.add_attachment(attachment)

                elif att.get("content"):
                    # Base64 content provided directly
                    attachment = Attachment()
                    attachment.file_content = FileContent(att["content"])
                    attachment.file_name = FileName(att.get("name", "attachment"))
                    attachment.file_type = FileType(att.get("type", "application/octet-stream"))
                    attachment.disposition = Disposition("attachment")
                    mail.add_attachment(attachment)

            # Send
            response = client.send(mail)

            # Extract message ID from headers
            message_id = None
            if hasattr(response, 'headers') and 'X-Message-Id' in response.headers:
                message_id = response.headers['X-Message-Id']

            if response.status_code in (200, 201, 202):
                return ProviderResult.ok(
                    message_id=message_id,
                    external_status="sent",
                    raw_response={
                        "status_code": response.status_code,
                        "message_id": message_id,
                    }
                )
            else:
                return ProviderResult.fail(
                    f"SendGrid returned status {response.status_code}",
                    raw_response={"status_code": response.status_code}
                )

        except Exception as e:
            logger.error(f"SendGrid send failed: {e}")
            return ProviderResult.fail(str(e))

    async def handle_webhook(self, payload: Dict) -> Dict:
        """
        Process SendGrid webhook for inbound email or events.

        SendGrid Inbound Parse sends multipart form data with:
        - from, to, subject, text, html, attachments
        """
        try:
            # Inbound email (from Inbound Parse)
            if payload.get("from") and payload.get("text"):
                # Parse from address
                from_addr = payload.get("from", "")
                # Format: "Name <email@domain.com>" or just "email@domain.com"
                email_match = re.search(r'<(.+?)>|^([^\s<]+@[^\s>]+)$', from_addr)
                email = email_match.group(1) or email_match.group(2) if email_match else from_addr

                return {
                    "type": "inbound",
                    "from_address": email,
                    "from_name": from_addr.split('<')[0].strip().strip('"') if '<' in from_addr else None,
                    "to_address": payload.get("to"),
                    "subject": payload.get("subject"),
                    "body": payload.get("text"),
                    "body_html": payload.get("html"),
                    "attachments": payload.get("attachments", []),
                    "raw": payload,
                }

            # Event webhook (delivery status)
            if isinstance(payload, list):
                events = []
                for event in payload:
                    events.append({
                        "type": "status_update",
                        "external_id": event.get("sg_message_id"),
                        "status": event.get("event"),
                        "email": event.get("email"),
                        "timestamp": event.get("timestamp"),
                        "raw": event,
                    })
                return {"type": "batch_status", "events": events}

            return {"type": "unknown", "raw": payload}

        except Exception as e:
            logger.error(f"SendGrid webhook parse error: {e}")
            return {"type": "error", "error": str(e), "raw": payload}

    def get_config_schema(self) -> List[Dict]:
        """Configuration schema for SendGrid."""
        return [
            {
                "key": "SENDGRID_API_KEY",
                "label": "API Key",
                "type": "password",
                "required": True,
                "description": "SendGrid API key"
            },
            {
                "key": "SENDGRID_FROM_EMAIL",
                "label": "From Email",
                "type": "email",
                "required": True,
                "description": "Verified sender email address"
            },
            {
                "key": "SENDGRID_FROM_NAME",
                "label": "From Name",
                "type": "text",
                "required": False,
                "description": "Sender display name (default: FORD CAD)"
            },
        ]
