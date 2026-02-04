# ============================================================================
# FORD-CAD Messaging — Base Provider Interface
# ============================================================================

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
import os


class ProviderStatus(str, Enum):
    """Provider health status."""
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


@dataclass
class ProviderResult:
    """Result from a provider operation."""
    success: bool
    message_id: Optional[str] = None  # Provider's message ID
    external_status: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[Dict] = None
    metadata: Dict = field(default_factory=dict)

    @classmethod
    def ok(cls, message_id: str = None, **kwargs):
        return cls(success=True, message_id=message_id, **kwargs)

    @classmethod
    def fail(cls, error: str, **kwargs):
        return cls(success=False, error=error, **kwargs)


@dataclass
class MessagePayload:
    """Standardized message payload for providers."""
    to: str  # Recipient address (phone, email, etc.)
    body: str
    subject: Optional[str] = None
    body_html: Optional[str] = None
    attachments: List[Dict] = field(default_factory=list)
    from_address: Optional[str] = None  # Override default sender
    metadata: Dict = field(default_factory=dict)


class BaseProvider(ABC):
    """
    Abstract base class for messaging providers.

    Each provider must implement:
    - channel: The channel identifier
    - send(): Send a message
    - get_status(): Check provider health
    - is_configured(): Check if provider has required config

    Optional:
    - validate_address(): Check if address is valid for this channel
    - handle_webhook(): Process inbound webhooks
    """

    channel: str = "base"
    display_name: str = "Base Provider"

    def __init__(self, config: Dict = None):
        """
        Initialize provider with optional config override.
        By default, reads from environment variables.
        """
        self.config = config or {}
        self._load_config()

    def _load_config(self):
        """Load configuration from environment. Override in subclasses."""
        pass

    def _get_env(self, key: str, default: str = None) -> Optional[str]:
        """Get environment variable or config value."""
        return self.config.get(key) or os.environ.get(key, default)

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if provider has all required configuration."""
        pass

    @abstractmethod
    async def send(self, payload: MessagePayload) -> ProviderResult:
        """
        Send a message through this provider.

        Args:
            payload: Standardized message payload

        Returns:
            ProviderResult with success/failure info
        """
        pass

    @abstractmethod
    async def get_status(self) -> ProviderStatus:
        """Check provider health/availability."""
        pass

    def validate_address(self, address: str) -> bool:
        """
        Validate that an address is valid for this channel.
        Override in subclasses with specific validation.
        """
        return bool(address and address.strip())

    async def handle_webhook(self, payload: Dict) -> Dict:
        """
        Process an inbound webhook from this provider.
        Override in subclasses that support inbound messaging.

        Returns:
            Dict with parsed message data
        """
        return {"error": "Webhooks not supported by this provider"}

    def get_config_schema(self) -> List[Dict]:
        """
        Return configuration schema for UI display.
        Override in subclasses.
        """
        return []

    def __repr__(self):
        configured = "configured" if self.is_configured() else "not configured"
        return f"<{self.__class__.__name__} ({self.channel}) [{configured}]>"
