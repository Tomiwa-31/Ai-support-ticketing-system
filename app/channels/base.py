from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class InboundEvent:
    """Canonical shape every channel adapter must produce (PLAN.md)."""

    channel: str
    external_thread_id: str
    external_message_id: str
    author: dict[str, Any]  # {"type": "contact" | "user", "id": int}
    body: str
    occurred_at: datetime
    org_id: int
    account_id: int
    issue_id: int | None = None
    title: str | None = None
    is_internal_note: bool = False


class ChannelAdapter(ABC):
    channel: str

    @abstractmethod
    def to_event(self, payload: Any) -> InboundEvent:
        """Convert a channel-specific payload into a canonical InboundEvent."""
