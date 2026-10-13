import uuid
from datetime import datetime, timezone
from typing import Any

from app.channels.base import ChannelAdapter, InboundEvent
from app.schemas.conversio import ConversioMessage


class ConversioAdapter(ChannelAdapter):
    """Conversio chat -> canonical event. The only Conversio-specific code; it carries tenant, user, product and
    correlation id as generic context so nothing downstream needs to know the channel."""

    channel = "conversio"

    def to_event(self, payload: dict[str, Any]) -> InboundEvent:
        """payload: {"message": ConversioMessage, "org_id", "account_id", "contact_id"}."""
        message: ConversioMessage = payload["message"]
        correlation_id = message.correlation_id or str(uuid.uuid4())
        return InboundEvent(
            channel=self.channel,
            external_thread_id=message.conversation_id,
            external_message_id=message.message_id or str(uuid.uuid4()),
            author={"type": "contact", "id": payload["contact_id"]},
            body=message.text,
            occurred_at=datetime.now(timezone.utc),
            org_id=payload["org_id"],
            account_id=payload["account_id"],
            title=message.text.strip().splitlines()[0][:80] if message.text.strip() else None,
            context={
                "tenant_id": message.tenant_id,
                "product": message.product,
                "customer_ref": message.user.id,
                "correlation_id": correlation_id,
            },
        )
