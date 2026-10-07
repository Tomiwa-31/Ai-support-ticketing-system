import uuid
from datetime import datetime, timezone

from app.channels.base import ChannelAdapter, InboundEvent
from app.schemas.simulate import SimulateMessageRequest


class ManualAdapter(ChannelAdapter):
    channel = "manual"

    def to_event(self, payload: SimulateMessageRequest) -> InboundEvent:
        if payload.external_thread_id:
            thread_id = payload.external_thread_id
        elif payload.issue_id is not None:
            thread_id = f"manual-issue-{payload.issue_id}"
        else:
            thread_id = f"manual-new-{uuid.uuid4()}"

        return InboundEvent(
            channel=self.channel,
            external_thread_id=thread_id,
            external_message_id=payload.external_message_id or str(uuid.uuid4()),
            author={"type": payload.author_type, "id": payload.author_id},
            body=payload.body,
            occurred_at=payload.occurred_at or datetime.now(timezone.utc),
            org_id=payload.org_id,
            account_id=payload.account_id,
            issue_id=payload.issue_id,
            title=payload.title,
            is_internal_note=payload.is_internal_note,
        )
