import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import issue_service
from app.core.clock import utcnow
from app.models import SLA, AuditLog, Issue, IssueStatus, SLAInstance

# Timer only accrues in these statuses; On Hold / Closed pause it.
COUNTING_STATUSES = {
    IssueStatus.NEW.value,
    IssueStatus.ON_YOU.value,
    IssueStatus.ON_CUSTOMER.value,
}

CHECK_INTERVAL_SECONDS = 30


def is_counting(status: str) -> bool:
    return status in COUNTING_STATUSES


#time used = (now − started_at) − paused_seconds.
async def _pause_started_at(session: AsyncSession, issue_id: int) -> datetime | None:
    """When the issue's current run of non-counting statuses began.

    The schema has no paused_at column, so derive it from audit_logs: the most recent
    transition from a counting status into a non-counting one (On Hold -> Closed is
    still the same pause, so it is skipped).
    """
    rows = await session.execute(
        select(AuditLog.action, AuditLog.happened_at)
        .where(
            AuditLog.target_type == "issue",
            AuditLog.target_id == issue_id,
            AuditLog.action.like("issue.status_changed:%"),
        )
        .order_by(AuditLog.id.desc())
    )
    for action, happened_at in rows.all():
        old_status, _, new_status = action.split(":", 1)[1].partition("->")
        if is_counting(old_status) and not is_counting(new_status):
            return happened_at
    return None


async def _instances_for_issue(session: AsyncSession, issue_id: int) -> list[SLAInstance]:
    result = await session.scalars(select(SLAInstance).where(SLAInstance.issue_id == issue_id))
    return list(result.all())


async def start_for_issue(session: AsyncSession, issue: Issue) -> None:
    """Start a Resolution Time timer for each SLA defined for the issue's org."""
    slas = await session.scalars(select(SLA).where(SLA.org_id == issue.org_id))
    for sla in slas.all():
        instance = SLAInstance(issue_id=issue.id, sla_id=sla.id, started_at=utcnow())
        session.add(instance)
        await session.flush()
        await issue_service.write_audit_log(
            session,
            org_id=issue.org_id,
            actor_type="sla",
            actor_id=sla.id,
            action="sla.started",
            target_type="sla_instance",
            target_id=instance.id,
        )


async def on_status_change(session: AsyncSession, issue: Issue, old_status: str, new_status: str) -> None:
    """Close out a pause when the issue goes from a non-counting status back to a counting one.

    The open pause itself is never stored; it's derived at read time by `elapsed_seconds`.
    """
    if is_counting(old_status) or not is_counting(new_status):
        return
    pause_started = await _pause_started_at(session, issue.id)
    if pause_started is None:
        return
    paused = max(0, int((utcnow() - pause_started).total_seconds()))
    for instance in await _instances_for_issue(session, issue.id):
        instance.paused_seconds += paused
        await issue_service.write_audit_log(
            session,
            org_id=issue.org_id,
            actor_type="sla",
            actor_id=instance.sla_id,
            action=f"sla.resumed:paused_{paused}s",
            target_type="sla_instance",
            target_id=instance.id,
        )


async def elapsed_seconds(session: AsyncSession, instance: SLAInstance, issue: Issue, now: datetime | None = None) -> int:
    """Counting time so far: wall time since start, minus closed pauses, minus any open pause."""
    now = now or utcnow()
    total = (now - instance.started_at).total_seconds() - instance.paused_seconds
    if not is_counting(issue.status):
        pause_started = await _pause_started_at(session, issue.id)
        if pause_started is not None:
            total -= (now - pause_started).total_seconds()
    return max(0, int(total))


async def check_breaches(session: AsyncSession) -> list[int]:
    """Mark every unbreached instance whose counting time has hit its target. Returns breached instance ids."""
    rows = await session.execute(
        select(SLAInstance, SLA, Issue)
        .join(SLA, SLA.id == SLAInstance.sla_id)
        .join(Issue, Issue.id == SLAInstance.issue_id)
        .where(SLAInstance.breached_at.is_(None))
    )
    now = utcnow()
    breached: list[int] = []
    for instance, sla, issue in rows.all():
        if await elapsed_seconds(session, instance, issue, now) < sla.target_minutes * 60:
            continue
        instance.breached_at = now
        await issue_service.write_audit_log(
            session,
            org_id=issue.org_id,
            actor_type="sla",
            actor_id=sla.id,
            action=f"sla.breached:{sla.name}",
            target_type="issue",
            target_id=issue.id,
        )
        breached.append(instance.id)

    if breached:
        await session.commit()
    return breached


async def run_breach_checker(
    session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = CHECK_INTERVAL_SECONDS
) -> None:
    """Background task: periodically check for SLA breaches, forever."""
    while True:
        try:
            async with session_factory() as session:
                await check_breaches(session)
        except Exception as exc:  # noqa: BLE001 -- keep the loop alive on a bad tick
            print(f"[sla] breach check failed: {exc!r}")
        await asyncio.sleep(interval_seconds)
#flags timers that exceed the target