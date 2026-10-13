from datetime import timedelta

from sqlalchemy import select, update

from app.core import event_bus, issue_service
from app.core.clock import utcnow
from app.models import AuditLog, Issue, SLAInstance
from app.sla import sla_engine
from tests.helpers import audit_actions, make_event


async def _open_issue(session, *, started_minutes_ago):
    message = await event_bus._handle_event(session, make_event("help"))
    issue = await session.get(Issue, message.issue_id)
    instance = await session.scalar(select(SLAInstance).where(SLAInstance.issue_id == issue.id))
    instance.started_at = utcnow() - timedelta(minutes=started_minutes_ago)
    await session.commit()
    return issue, instance


async def _move(session, issue, to_status, *, minutes_ago):
    """Change status with the matching audit row, stamped in the past (the pause start is read from audit_logs)."""
    old = issue.status
    issue.status = to_status
    action = f"issue.status_changed:{old}->{to_status}"
    await issue_service.write_audit_log(
        session, org_id=1, actor_type="api", actor_id=None, action=action, target_type="issue", target_id=issue.id
    )
    await session.commit()
    await session.execute(
        update(AuditLog)
        .where(AuditLog.action == action, AuditLog.target_id == issue.id)
        .values(happened_at=utcnow() - timedelta(minutes=minutes_ago))
    )
    await session.commit()


def _approx(seconds, minutes):
    return abs(seconds - minutes * 60) <= 5


def test_counting_statuses():
    assert all(sla_engine.is_counting(s) for s in ("New", "On You", "On Customer"))
    assert not any(sla_engine.is_counting(s) for s in ("On Hold", "Closed"))


async def test_elapsed_counts_wall_time_while_counting(session):
    issue, instance = await _open_issue(session, started_minutes_ago=100)
    assert _approx(await sla_engine.elapsed_seconds(session, instance, issue), 100)


async def test_open_pause_is_excluded(session):
    issue, instance = await _open_issue(session, started_minutes_ago=100)
    await _move(session, issue, "On Hold", minutes_ago=60)
    assert _approx(await sla_engine.elapsed_seconds(session, instance, issue), 40)


async def test_resume_folds_pause_into_paused_seconds(session):
    issue, instance = await _open_issue(session, started_minutes_ago=100)
    await _move(session, issue, "On Hold", minutes_ago=60)
    issue.status = "On You"
    await sla_engine.on_status_change(session, issue, "On Hold", "On You")
    await session.commit()
    await session.refresh(instance)
    assert _approx(instance.paused_seconds, 60)
    assert any(a.startswith("sla.resumed:paused_") for a in await audit_actions(session))
    assert _approx(await sla_engine.elapsed_seconds(session, instance, issue), 40)


async def test_on_hold_to_closed_is_one_pause(session):
    issue, instance = await _open_issue(session, started_minutes_ago=100)
    await _move(session, issue, "On Hold", minutes_ago=60)
    await _move(session, issue, "Closed", minutes_ago=10)
    assert _approx(await sla_engine.elapsed_seconds(session, instance, issue), 40)


async def test_no_breach_under_target_then_single_breach_over_it(session):
    issue, instance = await _open_issue(session, started_minutes_ago=40)
    assert await sla_engine.check_breaches(session) == []

    instance.started_at = utcnow() - timedelta(minutes=600)  # seeded target is 480
    await session.commit()
    assert await sla_engine.check_breaches(session) == [instance.id]
    assert await sla_engine.check_breaches(session) == []  # not re-fired
    actions = await audit_actions(session, target_type="issue", target_id=issue.id)
    assert actions.count("sla.breached:Resolution Time") == 1


async def test_paused_time_does_not_count_toward_breach(session):
    issue, instance = await _open_issue(session, started_minutes_ago=600)
    await _move(session, issue, "On Hold", minutes_ago=300)  # 300 of 600 min paused -> 300 counting < 480
    assert await sla_engine.check_breaches(session) == []
