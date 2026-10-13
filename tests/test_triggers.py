import json

from sqlalchemy import select

from app.core import event_bus
from app.models import Issue, Tag, Trigger, TriggerAction, TriggerCondition
from app.models.tag import issue_tags
from tests.helpers import audit_actions, make_event


async def _tags_for(session, issue_id):
    rows = await session.execute(
        select(Tag.name).join(issue_tags, issue_tags.c.tag_id == Tag.id).where(issue_tags.c.issue_id == issue_id)
    )
    return [r[0] for r in rows.all()]


async def _add_trigger(session, *, name, position, kickoff, conds, acts):
    trigger = Trigger(org_id=1, name=name, kickoff_event=kickoff, position=position, is_enabled=True)
    session.add(trigger)
    await session.flush()
    for field, op, value in conds:
        session.add(TriggerCondition(trigger_id=trigger.id, field=field, operator=op, value=value))
    for i, (action_type, params) in enumerate(acts, start=1):
        session.add(
            TriggerAction(trigger_id=trigger.id, action_type=action_type, params=json.dumps(params), position=i)
        )
    await session.commit()
    return trigger


async def test_seeded_trigger_fires_on_urgent_title(session):
    message = await event_bus._handle_event(session, make_event("down", title="urgent: prod down"))
    assert await _tags_for(session, message.issue_id) == ["urgent"]
    actions = await audit_actions(session)
    assert "trigger.evaluated:fired" in actions
    assert "tag.created" in actions
    assert "issue.tag_added:urgent" in actions


async def test_seeded_trigger_does_not_fire_otherwise(session):
    message = await event_bus._handle_event(session, make_event("pw", title="Password reset question"))
    assert await _tags_for(session, message.issue_id) == []
    actions = await audit_actions(session)
    assert "trigger.evaluated:not_fired" in actions
    assert "tag.created" not in actions


async def test_tag_created_once_but_added_per_issue(session):
    await event_bus._handle_event(session, make_event("a", title="urgent one"))
    await event_bus._handle_event(session, make_event("b", title="urgent two"))
    actions = await audit_actions(session)
    assert actions.count("tag.created") == 1
    assert actions.count("issue.tag_added:urgent") == 2


async def test_triggers_run_in_position_order_in_a_single_pass(session):
    # B (position 20) sets On Hold. A (position 10) would match On Hold, but it already ran
    # earlier in the pass, so it must NOT be re-evaluated after B changes state.
    await _add_trigger(
        session, name="A", position=10, kickoff="message.created",
        conds=[("issue.status", "equals", "On Hold")], acts=[("add_tag", {"tag_name": "was-on-hold"})],
    )
    await _add_trigger(
        session, name="B", position=20, kickoff="message.created",
        conds=[], acts=[("set_status", {"status": "On Hold"})],
    )
    message = await event_bus._handle_event(session, make_event("hello", title="plain"))
    issue = await session.get(Issue, message.issue_id)
    await session.refresh(issue)
    assert issue.status == "On Hold"
    assert await _tags_for(session, issue.id) == []


async def test_assign_team_and_webhook_stub(session):
    await _add_trigger(
        session, name="route", position=1, kickoff="issue.created", conds=[],
        acts=[("assign_team", {"team_id": 1}), ("send_webhook", {"url": "https://example.test/hook"})],
    )
    message = await event_bus._handle_event(session, make_event("hello"))
    issue = await session.get(Issue, message.issue_id)
    await session.refresh(issue)
    assert issue.team_id == 1
    actions = await audit_actions(session)
    assert "issue.team_assigned:1" in actions
    assert "webhook.sent:https://example.test/hook" in actions


async def test_disabled_trigger_is_skipped(session):
    seeded = await session.scalar(select(Trigger).where(Trigger.name == "Tag urgent issues"))
    seeded.is_enabled = False
    await session.commit()
    await event_bus._handle_event(session, make_event("x", title="urgent"))
    assert await audit_actions(session, target_type="trigger", target_id=seeded.id) == []
