#holds the 4 things a trigger can do
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.issue_service import write_audit_log
from app.models import Issue, Tag, Trigger, TriggerAction
from app.models.tag import issue_tags
from app.sla import sla_engine


async def _set_status(session: AsyncSession, issue: Issue, trigger: Trigger, params: dict[str, Any]) -> None:
    new_status = params["status"]
    old_status = issue.status
    if new_status == old_status:
        return
    issue.status = new_status
    await sla_engine.on_status_change(session, issue, old_status, new_status)#from a Non counting to a counting one(SO PAUSE ENDED)
    await write_audit_log(
        session,
        org_id=issue.org_id,
        actor_type="trigger",  #who took the action
        actor_id=trigger.id,
        action=f"issue.status_changed:{old_status}->{new_status}",
        target_type="issue",
        target_id=issue.id,
    )
#actor_type="trigger". That's how the audit log shows the trigger did it, not a human.

async def _assign_team(session: AsyncSession, issue: Issue, trigger: Trigger, params: dict[str, Any]) -> None:
    team_id = params["team_id"]
    issue.team_id = team_id
    await write_audit_log(
        session,
        org_id=issue.org_id,
        actor_type="trigger",
        actor_id=trigger.id,
        action=f"issue.team_assigned:{team_id}",
        target_type="issue",
        target_id=issue.id,
    )


async def _add_tag(session: AsyncSession, issue: Issue, trigger: Trigger, params: dict[str, Any]) -> None:
    tag_name = params["tag_name"]
    tag = await session.scalar(select(Tag).where(Tag.org_id == issue.org_id, Tag.name == tag_name))
    if tag is None:
        tag = Tag(org_id=issue.org_id, name=tag_name)
        session.add(tag)
        await session.flush()
        await write_audit_log(
            session,
            org_id=issue.org_id,
            actor_type="trigger",
            actor_id=trigger.id,
            action="tag.created",
            target_type="tag",
            target_id=tag.id,
        )

    # Work against the association table directly, not the issue.tags relationship,
    # so we never trigger an async lazy-load on an issue fetched without it eager-loaded.
    already_tagged = await session.scalar(
        select(issue_tags.c.tag_id).where(issue_tags.c.issue_id == issue.id, issue_tags.c.tag_id == tag.id)
    )
    if already_tagged is None:
        await session.execute(issue_tags.insert().values(issue_id=issue.id, tag_id=tag.id))

    await write_audit_log(
        session,
        org_id=issue.org_id,
        actor_type="trigger",
        actor_id=trigger.id,
        action=f"issue.tag_added:{tag_name}",
        target_type="issue",
        target_id=issue.id,
    )


async def _send_webhook(session: AsyncSession, issue: Issue, trigger: Trigger, params: dict[str, Any]) -> None:
    """Stub for v1 — no real HTTP call, just record that it would have fired."""
    url = params.get("url", "")
    await write_audit_log(
        session,
        org_id=issue.org_id,
        actor_type="trigger",
        actor_id=trigger.id,
        action=f"webhook.sent:{url}",
        target_type="issue",
        target_id=issue.id,
    )


_HANDLERS = {
    "set_status": _set_status,
    "assign_team": _assign_team,
    "add_tag": _add_tag,
    "send_webhook": _send_webhook,
}


async def execute(session: AsyncSession, issue: Issue, trigger: Trigger, action: TriggerAction) -> None:
    handler = _HANDLERS.get(action.action_type)
    if handler is None:
        raise ValueError(f"unknown trigger action_type: {action.action_type}")
    params = json.loads(action.params) if action.params else {}
    await handler(session, issue, trigger, params)
