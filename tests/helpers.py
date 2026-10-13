import asyncio
import contextlib
from datetime import datetime, timezone

from sqlalchemy import select

from app.channels.base import InboundEvent
from app.models import AuditLog
from tests.conftest import ACCOUNT_ID, CONTACT_ID, ORG_ID, USER_ID


def make_event(
    body="hello",
    *,
    author_type="contact",
    issue_id=None,
    title=None,
    thread_id=None,
    channel="manual",
    is_internal_note=False,
    context=None,
) -> InboundEvent:
    return InboundEvent(
        channel=channel,
        external_thread_id=thread_id or "",
        external_message_id="m-" + body[:8],
        author={"type": author_type, "id": CONTACT_ID if author_type == "contact" else USER_ID},
        body=body,
        occurred_at=datetime.now(timezone.utc),
        org_id=ORG_ID,
        account_id=ACCOUNT_ID,
        issue_id=issue_id,
        title=title,
        is_internal_note=is_internal_note,
        context=context,
    )


async def audit_actions(session, *, target_type=None, target_id=None) -> list[str]:
    query = select(AuditLog.action).order_by(AuditLog.id)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if target_id is not None:
        query = query.where(AuditLog.target_id == target_id)
    return list((await session.scalars(query)).all())


CONVERSIO_CONTEXT = {"tenant_id": "commsworth", "product": "credipay", "customer_ref": "u-1", "correlation_id": "corr-123"}


def conversio_event(body="hello", *, thread_id="conv-1", author_type="contact", issue_id=None, **kwargs):
    return make_event(
        body, channel="conversio", thread_id=thread_id, author_type=author_type, issue_id=issue_id,
        context=CONVERSIO_CONTEXT if author_type == "contact" else None, **kwargs,
    )


async def stop_tasks(*tasks: "asyncio.Task") -> None:
    """Cancel background workers and wait until they have really finished, so the event loop can close cleanly."""
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
