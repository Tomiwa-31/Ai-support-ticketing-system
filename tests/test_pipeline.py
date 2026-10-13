"""Canonical event -> issue/message pipeline, status machine wiring and audit logging."""
import asyncio

import pytest
from sqlalchemy import select

from app.core import event_bus, issue_service
from app.database import AsyncSessionLocal
from app.models import AuditLog, Issue, Message, SLAInstance
from tests.helpers import audit_actions, make_event, stop_tasks


async def test_new_contact_message_opens_issue_at_on_you(session):
    message = await event_bus._handle_event(session, make_event("Cannot log in", title="Login broken", thread_id="t1"))

    issue = await session.get(Issue, message.issue_id)
    assert issue.title == "Login broken"
    assert issue.status == "On You"
    assert issue.channel == "manual"

    actions = await audit_actions(session)
    assert "issue.created" in actions
    assert "message.created" in actions
    assert "issue.status_changed:New->On You" in actions
    assert "thread.linked:manual:t1" in actions


async def test_title_defaults_to_start_of_body(session):
    message = await event_bus._handle_event(session, make_event("x" * 200))
    issue = await session.get(Issue, message.issue_id)
    assert issue.title == "x" * 80


async def test_sla_instance_created_with_issue(session):
    message = await event_bus._handle_event(session, make_event("hi"))
    instances = (await session.scalars(select(SLAInstance).where(SLAInstance.issue_id == message.issue_id))).all()
    assert len(instances) == 1
    assert "sla.started" in await audit_actions(session)


async def test_same_thread_id_appends_to_same_issue(session):
    first = await event_bus._handle_event(session, make_event("first", thread_id="t9"))
    second = await event_bus._handle_event(session, make_event("second", thread_id="t9"))
    assert first.issue_id == second.issue_id
    assert len((await session.scalars(select(Issue))).all()) == 1


async def test_team_reply_flips_to_on_customer_and_customer_flips_back(session):
    first = await event_bus._handle_event(session, make_event("help"))
    await event_bus._handle_event(session, make_event("on it", author_type="user", issue_id=first.issue_id))
    assert (await session.get(Issue, first.issue_id)).status == "On Customer"
    await event_bus._handle_event(session, make_event("thanks", issue_id=first.issue_id))
    assert (await session.get(Issue, first.issue_id)).status == "On You"


async def test_closed_issue_reopens_on_customer_message(session):
    first = await event_bus._handle_event(session, make_event("help"))
    issue = await session.get(Issue, first.issue_id)
    issue.status = "Closed"
    await session.commit()
    await event_bus._handle_event(session, make_event("still broken", issue_id=issue.id))
    await session.refresh(issue)
    assert issue.status == "On You"


async def test_on_hold_is_not_auto_changed_and_logs_no_status_row(session):
    first = await event_bus._handle_event(session, make_event("help"))
    issue = await session.get(Issue, first.issue_id)
    issue.status = "On Hold"
    await session.commit()
    before = await audit_actions(session, target_type="issue", target_id=issue.id)
    await event_bus._handle_event(session, make_event("any update?", issue_id=issue.id))
    await session.refresh(issue)
    assert issue.status == "On Hold"
    assert await audit_actions(session, target_type="issue", target_id=issue.id) == before


async def test_internal_note_does_not_change_status(session):
    first = await event_bus._handle_event(session, make_event("help"))
    await event_bus._handle_event(
        session, make_event("note", author_type="user", issue_id=first.issue_id, is_internal_note=True)
    )
    assert (await session.get(Issue, first.issue_id)).status == "On You"


async def test_unknown_issue_id_raises_and_writes_no_audit_row(session):
    with pytest.raises(ValueError):
        await event_bus._handle_event(session, make_event("hi", issue_id=999))
    assert await audit_actions(session) == []


async def test_team_member_cannot_open_a_new_issue(session):
    with pytest.raises(ValueError):
        await event_bus._handle_event(session, make_event("hi", author_type="user"))


async def test_validation_only_applies_when_not_bypassed(session):
    with pytest.raises(issue_service.ValidationError):
        await issue_service.create_issue(
            session, org_id=1, title="  ", account_id=1, contact_id=1, channel="manual", bypass_validation=False
        )
    issue = await issue_service.create_issue(
        session, org_id=1, title="  ", account_id=1, contact_id=1, channel="manual", bypass_validation=True
    )
    assert issue.id is not None


async def test_issue_and_message_creates_write_audit_rows_as_channel(session):
    await event_bus._handle_event(session, make_event("a"))
    rows = (
        await session.scalars(select(AuditLog).where(AuditLog.action.in_(["issue.created", "message.created"])))
    ).all()
    assert {r.action for r in rows} == {"issue.created", "message.created"}
    assert all(r.actor_type == "channel" for r in rows)
    assert len((await session.scalars(select(Message))).all()) == 1


async def test_worker_processes_published_events_and_survives_failures(session):
    worker = asyncio.create_task(event_bus.run_worker(AsyncSessionLocal))
    try:
        message = await asyncio.wait_for(event_bus.publish_and_wait(make_event("via worker")), timeout=10)
        assert message.id is not None
        with pytest.raises(ValueError):
            await asyncio.wait_for(event_bus.publish_and_wait(make_event("x", issue_id=999)), timeout=10)
        again = await asyncio.wait_for(event_bus.publish_and_wait(make_event("still alive")), timeout=10)
        assert again.id is not None
    finally:
        await stop_tasks(worker)
