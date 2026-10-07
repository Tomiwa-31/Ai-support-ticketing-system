import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import InboundEvent
from app.core import issue_service
from app.models import AuditLog, Message
from app.triggers import engine as trigger_engine

logger = logging.getLogger(__name__)

_queue: "asyncio.Queue[tuple[InboundEvent, asyncio.Future | None]]" = asyncio.Queue()


async def publish(event: InboundEvent) -> None:
    """Fire-and-forget publish, for adapters that don't need the result (e.g. Slack, Gmail)."""
    await _queue.put((event, None))


async def publish_and_wait(event: InboundEvent) -> Message:
    """Publish and wait for the worker to process it, returning the created message."""
    future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
    await _queue.put((event, future))
    return await future


def _thread_link_action(channel: str, external_thread_id: str) -> str:
    return f"thread.linked:{channel}:{external_thread_id}"


async def _find_linked_issue_id(session: AsyncSession, channel: str, external_thread_id: str) -> int | None:
    """The schema has no external-thread column, so thread->issue links live in audit_logs."""
    return await session.scalar(
        select(AuditLog.target_id)
        .where(
            AuditLog.target_type == "issue",
            AuditLog.action == _thread_link_action(channel, external_thread_id),
        )
        .limit(1)
    )


async def _handle_event(session: AsyncSession, event: InboundEvent) -> Message:
    author_type = event.author["type"]
    author_id = event.author["id"]

    issue_id = event.issue_id
    if issue_id is None and event.external_thread_id:
        issue_id = await _find_linked_issue_id(session, event.channel, event.external_thread_id)

    if issue_id is not None:
        issue = await issue_service.get_issue(session, issue_id)
        if issue is None:
            raise ValueError(f"issue {issue_id} not found")
    else:
        if author_type != "contact":
            raise ValueError("a new issue can only be opened by a contact message")
        issue = await issue_service.create_issue(
            session,
            org_id=event.org_id,
            title=event.title or event.body[:80],
            account_id=event.account_id,
            contact_id=author_id,
            channel=event.channel,
            actor_type="channel",
            actor_id=None,
            bypass_validation=True,
        )
        if event.external_thread_id:
            await issue_service.write_audit_log(
                session,
                org_id=event.org_id,
                actor_type="channel",
                actor_id=None,
                action=_thread_link_action(event.channel, event.external_thread_id),
                target_type="issue",
                target_id=issue.id,
            )
            await session.commit()
        await trigger_engine.evaluate(session, org_id=event.org_id, kickoff_event="issue.created", issue=issue)

    message = await issue_service.add_message(
        session,
        issue_id=issue.id,
        author_type=author_type,
        author_id=author_id,
        body_html=event.body,
        is_internal_note=event.is_internal_note,
        actor_type="channel",
        actor_id=None,
        bypass_validation=True,
    )
    assert message is not None
    await trigger_engine.evaluate(
        session, org_id=event.org_id, kickoff_event="message.created", issue=issue, message=message
    )
    return message


async def run_worker(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """The single event-bus worker: consumes canonical events, one at a time, forever."""
    while True:
        event, future = await _queue.get()
        try:
            async with session_factory() as session:
                message = await _handle_event(session, event)
            if future is not None and not future.done():
                future.set_result(message)
        except Exception as exc:  # noqa: BLE001 -- surface the failure to the waiting caller; keep the worker alive
            if future is not None and not future.done():
                future.set_exception(exc)
            else:
                logger.exception("failed to process %s event %s", event.channel, event.external_message_id)
        finally:
            _queue.task_done()
