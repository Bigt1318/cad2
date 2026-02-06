# ============================================================================
# FORD CAD - Base Delivery Channel
# ============================================================================

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class DeliveryResult:
    """Result of a delivery attempt."""
    success: bool
    recipient: str
    channel: str
    message_id: Optional[str] = None
    error: Optional[str] = None
    response_data: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "recipient": self.recipient,
            "channel": self.channel,
            "message_id": self.message_id,
            "error": self.error,
        }


class DeliveryChannel(ABC):
    """Abstract base class for delivery channels."""

    channel_name: str = "base"

    @abstractmethod
    def send(
        self,
        recipient: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        **kwargs,
    ) -> DeliveryResult:
        """Send a message through this channel."""
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if the channel is properly configured."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the channel is configured."""
        pass
