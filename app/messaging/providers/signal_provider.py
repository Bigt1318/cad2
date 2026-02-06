# ============================================================================
# FORD-CAD Messaging — Signal Provider (Experimental)
# ============================================================================
# Uses signal-cli for Signal messaging
# https://github.com/AsamK/signal-cli
# ============================================================================

from .base import BaseProvider, ProviderResult, ProviderStatus, MessagePayload
from typing import Dict, List, Optional
import subprocess
import json
import re
import logging
import asyncio
import os

logger = logging.getLogger(__name__)


class SignalProvider(BaseProvider):
    """
    Provider for Signal messaging via signal-cli.

    EXPERIMENTAL: Requires signal-cli to be installed and configured.

    Environment Variables:
    - SIGNAL_CLI_PATH: Path to signal-cli executable (default: signal-cli)
    - SIGNAL_PHONE_NUMBER: Registered Signal phone number
    - SIGNAL_CONFIG_PATH: signal-cli config directory (optional)
    """

    channel = "signal"
    display_name = "Signal (Experimental)"

    def _load_config(self):
        """Load Signal configuration."""
        self.cli_path = self._get_env("SIGNAL_CLI_PATH", "signal-cli")
        self.phone_number = self._get_env("SIGNAL_PHONE_NUMBER")
        self.config_path = self._get_env("SIGNAL_CONFIG_PATH")

    def is_configured(self) -> bool:
        """Check if Signal is configured."""
        if not self.phone_number:
            return False

        # Check if signal-cli is available
        try:
            result = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def get_status(self) -> ProviderStatus:
        """Check Signal availability."""
        if not self.phone_number:
            return ProviderStatus.NOT_CONFIGURED

        try:
            # Check if signal-cli is available and registered
            cmd = [self.cli_path, "-u", self.phone_number, "listAccounts"]
            if self.config_path:
                cmd.extend(["--config", self.config_path])

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                result.communicate(),
                timeout=10
            )

            if result.returncode == 0:
                return ProviderStatus.READY
            else:
                logger.warning(f"Signal status check failed: {stderr.decode()}")
                return ProviderStatus.DEGRADED

        except FileNotFoundError:
            logger.warning("signal-cli not found")
            return ProviderStatus.NOT_CONFIGURED
        except asyncio.TimeoutError:
            logger.warning("Signal status check timed out")
            return ProviderStatus.UNAVAILABLE
        except Exception as e:
            logger.error(f"Signal status check error: {e}")
            return ProviderStatus.UNAVAILABLE

    def validate_address(self, address: str) -> bool:
        """Validate Signal phone number."""
        if not address:
            return False

        # Strip to digits and +
        cleaned = re.sub(r'[^\d+]', '', address)

        # Must start with + for international format
        if not cleaned.startswith('+'):
            cleaned = '+1' + re.sub(r'\D', '', address)  # Assume US

        # Basic length check (E.164 format: 7-15 digits + country code)
        digits = re.sub(r'\D', '', cleaned)
        return 7 <= len(digits) <= 15

    def _normalize_phone(self, phone: str) -> str:
        """Normalize to E.164 format."""
        cleaned = re.sub(r'[^\d+]', '', phone)
        if not cleaned.startswith('+'):
            digits = re.sub(r'\D', '', phone)
            if len(digits) == 10:  # US number
                return f"+1{digits}"
            return f"+{digits}"
        return cleaned

    async def send(self, payload: MessagePayload) -> ProviderResult:
        """Send message via Signal."""
        if not self.is_configured():
            return ProviderResult.fail("Signal not configured")

        if not self.validate_address(payload.to):
            return ProviderResult.fail(f"Invalid phone number: {payload.to}")

        try:
            to_number = self._normalize_phone(payload.to)

            # Build signal-cli command
            cmd = [
                self.cli_path,
                "-u", self.phone_number,
                "send",
                "-m", payload.body,
                to_number
            ]

            if self.config_path:
                cmd.insert(1, "--config")
                cmd.insert(2, self.config_path)

            # Add attachments
            for att in payload.attachments:
                if att.get("path") and os.path.exists(att["path"]):
                    cmd.extend(["-a", att["path"]])

            # Run signal-cli
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                result.communicate(),
                timeout=30
            )

            if result.returncode == 0:
                # Parse timestamp from output if available
                output = stdout.decode()
                timestamp_match = re.search(r'timestamp:\s*(\d+)', output)
                message_id = timestamp_match.group(1) if timestamp_match else None

                return ProviderResult.ok(
                    message_id=message_id,
                    external_status="sent",
                    raw_response={"stdout": output, "stderr": stderr.decode()}
                )
            else:
                error_msg = stderr.decode() or stdout.decode()
                return ProviderResult.fail(
                    f"signal-cli error: {error_msg}",
                    raw_response={"stdout": stdout.decode(), "stderr": error_msg}
                )

        except asyncio.TimeoutError:
            return ProviderResult.fail("Signal send timed out")
        except Exception as e:
            logger.error(f"Signal send failed: {e}")
            return ProviderResult.fail(str(e))

    async def receive_messages(self) -> List[Dict]:
        """
        Poll for new messages.
        Call this periodically to check for inbound messages.
        """
        if not self.is_configured():
            return []

        try:
            cmd = [
                self.cli_path,
                "-u", self.phone_number,
                "receive",
                "--json"
            ]

            if self.config_path:
                cmd.insert(1, "--config")
                cmd.insert(2, self.config_path)

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                result.communicate(),
                timeout=30
            )

            if result.returncode == 0:
                messages = []
                for line in stdout.decode().strip().split('\n'):
                    if line:
                        try:
                            msg = json.loads(line)
                            if msg.get("envelope", {}).get("dataMessage"):
                                data = msg["envelope"]["dataMessage"]
                                messages.append({
                                    "type": "inbound",
                                    "from_address": msg["envelope"].get("source"),
                                    "timestamp": data.get("timestamp"),
                                    "body": data.get("message"),
                                    "attachments": data.get("attachments", []),
                                    "raw": msg,
                                })
                        except json.JSONDecodeError:
                            continue
                return messages
            return []

        except Exception as e:
            logger.error(f"Signal receive failed: {e}")
            return []

    async def handle_webhook(self, payload: Dict) -> Dict:
        """
        Signal doesn't use webhooks directly.
        Use receive_messages() instead for polling.
        """
        return {"error": "Signal uses polling, not webhooks. Use receive_messages() instead."}

    def get_config_schema(self) -> List[Dict]:
        """Configuration schema for Signal."""
        return [
            {
                "key": "SIGNAL_CLI_PATH",
                "label": "signal-cli Path",
                "type": "text",
                "required": False,
                "description": "Path to signal-cli executable (default: signal-cli)"
            },
            {
                "key": "SIGNAL_PHONE_NUMBER",
                "label": "Phone Number",
                "type": "phone",
                "required": True,
                "description": "Registered Signal phone number in E.164 format"
            },
            {
                "key": "SIGNAL_CONFIG_PATH",
                "label": "Config Path",
                "type": "text",
                "required": False,
                "description": "signal-cli config directory (optional)"
            },
        ]
