"""The approval gate: nothing AI-generated reaches the customer without a real agent's approval."""
import pytest
from sqlalchemy import select

from app.ai import llm as ai_llm
from app.ai import service, worker
from app.core import event_bus
from app.core.issue_service import ValidationError
from app.models import AIRun, AISuggestion, Issue, Message, Organization, User
from tests.fakes import FakeLLM
from tests.helpers import audit_actions, conversio_event

AGENT_ID = 1  # seeded "Dana Support"


async def _pending(session):
    message = await event_bus._handle_event(session, conversio_event("I was charged twice"))
    ai_llm.set_client(FakeLLM())
    suggestion = await worker.process_issue(session, message.issue_id)
    return suggestion


async def _agent_messages(session, issue_id):
    rows = await session.scalars(select(Message).where(Message.issue_id == issue_id, Message.author_type == "user"))
    return list(rows.all())


async def test_a_suggestion_alone_sends_nothing_to_the_customer(session):
    suggestion = await _pending(session)
    assert suggestion.status == "pending"
    assert await _agent_messages(session, suggestion.issue_id) == []
    assert (await session.get(Issue, suggestion.issue_id)).status == "On You"


async def test_approve_sends_the_draft_as_a_validated_human_write(session):
    suggestion = await _pending(session)
    approved = await service.approve(session, suggestion.id, AGENT_ID)

    assert approved.status == "approved" and approved.decided_by_user_id == AGENT_ID and approved.decided_at
    assert approved.final_reply == suggestion.draft_reply
    (reply,) = await _agent_messages(session, suggestion.issue_id)
    assert reply.body_html == suggestion.draft_reply and reply.author_id == AGENT_ID
    assert (await session.get(Issue, suggestion.issue_id)).status == "On Customer"  # normal status machine
    assert (await session.get(AIRun, suggestion.ai_run_id)).status == "approved"
    actions = await audit_actions(session)
    assert "ai.suggestion_approved" in actions and "ai.suggestion_edited" not in actions


async def test_approve_with_edit_sends_the_edited_text_and_records_the_edit(session):
    suggestion = await _pending(session)
    await service.approve(session, suggestion.id, AGENT_ID, reply_text="Hello! I have refunded the duplicate charge.")
    (reply,) = await _agent_messages(session, suggestion.issue_id)
    assert reply.body_html == "Hello! I have refunded the duplicate charge."
    await session.refresh(suggestion)
    assert suggestion.final_reply == reply.body_html and suggestion.draft_reply != reply.body_html
    assert "ai.suggestion_edited" in await audit_actions(session)


async def test_cannot_approve_twice(session):
    suggestion = await _pending(session)
    await service.approve(session, suggestion.id, AGENT_ID)
    with pytest.raises(service.SuggestionConflict):
        await service.approve(session, suggestion.id, AGENT_ID)
    assert len(await _agent_messages(session, suggestion.issue_id)) == 1


async def test_reject_sends_nothing_and_leaves_the_ticket_alone(session):
    suggestion = await _pending(session)
    rejected = await service.reject(session, suggestion.id, AGENT_ID, reason="wrong product")
    assert rejected.status == "rejected" and rejected.reject_reason == "wrong product"
    assert await _agent_messages(session, suggestion.issue_id) == []
    assert (await session.get(Issue, suggestion.issue_id)).status == "On You"
    assert (await session.get(AIRun, suggestion.ai_run_id)).status == "rejected"
    assert "ai.suggestion_rejected" in await audit_actions(session)


async def test_rejected_suggestion_cannot_be_approved_later(session):
    suggestion = await _pending(session)
    await service.reject(session, suggestion.id, AGENT_ID)
    with pytest.raises(service.SuggestionConflict):
        await service.approve(session, suggestion.id, AGENT_ID)
    assert await _agent_messages(session, suggestion.issue_id) == []


async def test_superseded_suggestion_cannot_be_approved(session):
    first = await _pending(session)
    await event_bus._handle_event(session, conversio_event("Any update?", issue_id=first.issue_id))
    await worker.process_issue(session, first.issue_id)
    with pytest.raises(service.SuggestionConflict):
        await service.approve(session, first.id, AGENT_ID)


async def test_approver_must_be_a_real_user_in_the_same_org(session):
    suggestion = await _pending(session)
    with pytest.raises(service.InvalidApprover):
        await service.approve(session, suggestion.id, 999)

    other_org = Organization(name="Other Co")
    session.add(other_org)
    await session.flush()
    outsider = User(org_id=other_org.id, name="Eve", email="eve@other.co", role="agent")
    session.add(outsider)
    await session.commit()
    with pytest.raises(service.InvalidApprover):
        await service.approve(session, suggestion.id, outsider.id)
    with pytest.raises(service.InvalidApprover):
        await service.reject(session, suggestion.id, outsider.id)

    await session.refresh(suggestion)
    assert suggestion.status == "pending" and await _agent_messages(session, suggestion.issue_id) == []


async def test_empty_reply_is_refused_by_validation_and_the_suggestion_stays_pending(session):
    suggestion = await _pending(session)
    suggestion_id, issue_id = suggestion.id, suggestion.issue_id  # a rollback expires loaded objects
    with pytest.raises(ValidationError):
        await service.approve(session, suggestion_id, AGENT_ID, reply_text="   ")
    fresh = (await session.scalars(select(AISuggestion).where(AISuggestion.id == suggestion_id))).one()
    assert fresh.status == "pending" and fresh.decided_by_user_id is None
    assert await _agent_messages(session, issue_id) == []
    assert "ai.suggestion_approved" not in await audit_actions(session)


async def test_a_reply_with_masked_placeholders_cannot_be_sent(session):
    suggestion = await _pending(session)
    suggestion_id, issue_id = suggestion.id, suggestion.issue_id
    with pytest.raises(ValidationError, match=r"\[CARD_1\]"):
        await service.approve(session, suggestion_id, AGENT_ID, reply_text="We saw the charge on [CARD_1].")
    assert await _agent_messages(session, issue_id) == []
    await service.approve(session, suggestion_id, AGENT_ID, reply_text="We saw the duplicate charge.")  # fixed by the agent
    assert len(await _agent_messages(session, issue_id)) == 1


async def test_unknown_suggestion(session):
    with pytest.raises(service.SuggestionNotFound):
        await service.approve(session, 999, AGENT_ID)
