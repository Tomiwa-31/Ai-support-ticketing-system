from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import status_machine
from app.core.clock import utcnow
from app.models import Account, AuditLog, Contact, Issue, IssueStatus, Message
from app.sla import sla_engine


class ValidationError(ValueError):
    pass


async def _validate_issue_fields(session: AsyncSession, *, title: str, account_id: int, contact_id: int) -> None:
    if not title.strip():
        raise ValidationError("title is required")
    if await session.get(Account, account_id) is None:
        raise ValidationError(f"account {account_id} does not exist")
    contact = await session.get(Contact, contact_id)
    if contact is None:
        raise ValidationError(f"contact {contact_id} does not exist")
    if contact.account_id != account_id:
        raise ValidationError(f"contact {contact_id} does not belong to account {account_id}")


async def _validate_message_fields(body_html: str) -> None:
    if not body_html.strip():
        raise ValidationError("body_html is required")


async def write_audit_log(
    session: AsyncSession,
    *,
    org_id: int,
    actor_type: str,
    actor_id: int | None,
    action: str,
    target_type: str,
    target_id: int,
) -> None:
    session.add(
        AuditLog(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            happened_at=utcnow(),
        )
    )


async def create_issue(
    session: AsyncSession,
    *,
    org_id: int,
    title: str,
    account_id: int,
    contact_id: int,
    channel: str,
    assignee_id: int | None = None,
    team_id: int | None = None,
    is_ticket: bool = True,
    actor_type: str = "api",
    actor_id: int | None = None,
    bypass_validation: bool = True,
) -> Issue:
    if not bypass_validation:
        await _validate_issue_fields(session, title=title, account_id=account_id, contact_id=contact_id)

    issue = Issue(
        org_id=org_id,
        title=title,
        status=IssueStatus.NEW.value,
        account_id=account_id,
        contact_id=contact_id,
        assignee_id=assignee_id,
        team_id=team_id,
        channel=channel,
        is_ticket=is_ticket,
    )
    session.add(issue)
    await session.flush()

    await write_audit_log(
        session,
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="issue.created",
        target_type="issue",
        target_id=issue.id,
    )
    await sla_engine.start_for_issue(session, issue)

    await session.commit()
    await session.refresh(issue)
    return issue


async def add_message(
    session: AsyncSession,
    *,
    issue_id: int,
    author_type: str,
    author_id: int,
    body_html: str,
    is_internal_note: bool = False,
    actor_type: str = "api",
    actor_id: int | None = None,
    bypass_validation: bool = True,
) -> Message | None:
    issue = await session.get(Issue, issue_id)
    if issue is None:
        return None

    if not bypass_validation:
        await _validate_message_fields(body_html)

    message = Message(
        issue_id=issue_id,
        author_type=author_type,
        author_id=author_id,
        body_html=body_html,
        is_internal_note=is_internal_note,
    )
    session.add(message)
    await session.flush()

    await write_audit_log(
        session,
        org_id=issue.org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="message.created",
        target_type="message",
        target_id=message.id,
    )

    old_status = issue.status
    new_status = status_machine.next_status(
        old_status, author_type=author_type, is_internal_note=is_internal_note
    )
    if new_status != old_status:
        issue.status = new_status
        await sla_engine.on_status_change(session, issue, old_status, new_status)
        await write_audit_log(
            session,
            org_id=issue.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=f"issue.status_changed:{old_status}->{new_status}",
            target_type="issue",
            target_id=issue.id,
        )

    await session.commit()
    await session.refresh(message)
    return message


async def get_issue(session: AsyncSession, issue_id: int) -> Issue | None:
    return await session.get(Issue, issue_id)#always returnd id ,satus and title of the issue


async def list_issues(session: AsyncSession, org_id: int) -> list[Issue]:
    result = await session.scalars(select(Issue).where(Issue.org_id == org_id).order_by(Issue.created_at.desc()))
    return list(result.all())


async def list_messages(session: AsyncSession, issue_id: int) -> list[Message]:
    result = await session.scalars(
        select(Message).where(Message.issue_id == issue_id).order_by(Message.created_at.asc())
    )
    return list(result.all())
