from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.issue_service import write_audit_log
from app.models import Issue, Message, Trigger
from app.triggers import actions, conditions


async def evaluate(
    session: AsyncSession,
    *,
    org_id: int,
    kickoff_event: str,
    issue: Issue,
    message: Message | None = None,
) -> None:
    """Evaluate every enabled trigger for this kickoff_event, in a single pass top to
    bottom ordered by position. No re-evaluation loop: a trigger's actions never cause
    earlier (already-evaluated) triggers in this pass to be checked again.
    """
    result = await session.scalars(
        select(Trigger)
        .where(
            Trigger.org_id == org_id,
            Trigger.kickoff_event == kickoff_event,
            Trigger.is_enabled.is_(True),
        )
        .order_by(Trigger.position)
        .options(selectinload(Trigger.conditions), selectinload(Trigger.actions))
    )
    triggers = result.all()

    context = {"issue": issue, "message": message}

    for trigger in triggers:
        matched = conditions.evaluate(trigger.conditions, context)
        await write_audit_log(
            session,
            org_id=org_id,
            actor_type="trigger",
            actor_id=trigger.id,
            action=f"trigger.evaluated:{'fired' if matched else 'not_fired'}",
            target_type="trigger",
            target_id=trigger.id,
        )
        if not matched:
            continue

        for action in sorted(trigger.actions, key=lambda a: a.position):
            await actions.execute(session, issue, trigger, action)

    await session.commit()

#The worker creates the issue, then the engine checks each trigger's conditions, and if they match, runs the actions from trigger_actions using the tools in actions.py."
