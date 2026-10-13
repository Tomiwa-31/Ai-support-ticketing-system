"""The approval gate. This is the ONLY code path that turns an AI suggestion into a customer-visible message,
and it requires a real support user. The reply goes through issue_service.add_message as a validated human write."""
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import masking
from app.core import issue_service
from app.core.clock import utcnow
from app.core.issue_service import ValidationError
from app.models import AIRun, AISuggestion, User


class SuggestionNotFound(Exception):
    pass


class SuggestionConflict(Exception):
    """The suggestion is no longer pending (already approved, rejected or superseded)."""


class InvalidApprover(ValueError):
    pass


async def _load_pending(session: AsyncSession, suggestion_id: int, user_id: int) -> AISuggestion:
    suggestion = await session.get(AISuggestion, suggestion_id)
    if suggestion is None:
        raise SuggestionNotFound(f"suggestion {suggestion_id} not found")
    user = await session.get(User, user_id)
    if user is None or user.org_id != suggestion.org_id:
        raise InvalidApprover(f"user {user_id} is not a member of this organization")
    if suggestion.status != "pending":
        raise SuggestionConflict(f"suggestion {suggestion_id} is already {suggestion.status}")
    return suggestion


async def _claim(session: AsyncSession, suggestion: AISuggestion, *, new_status: str, user_id: int, **fields) -> None:
    """Atomically move pending -> new_status so two concurrent decisions can't both win."""
    result = await session.execute(
        update(AISuggestion)
        .where(AISuggestion.id == suggestion.id, AISuggestion.status == "pending")
        .values(status=new_status, decided_by_user_id=user_id, decided_at=utcnow(), **fields)
    )
    if result.rowcount == 0:
        raise SuggestionConflict(f"suggestion {suggestion.id} is no longer pending")
    await session.execute(update(AIRun).where(AIRun.id == suggestion.ai_run_id).values(status=new_status))


async def approve(session: AsyncSession, suggestion_id: int, user_id: int, reply_text: str | None = None) -> AISuggestion:
    suggestion = await _load_pending(session, suggestion_id, user_id)
    final_reply = suggestion.draft_reply if reply_text is None else reply_text
    leftover = masking.find_tokens(final_reply)
    if leftover:
        # A placeholder like [CARD_1] must never reach the customer: the agent has to replace or remove it first.
        raise ValidationError(f"the reply still contains masked placeholders {sorted(set(leftover))}; edit them out")
    edited = final_reply != suggestion.draft_reply
    try:
        await _claim(session, suggestion, new_status="approved", user_id=user_id, final_reply=final_reply)
        await issue_service.write_audit_log(
            session, org_id=suggestion.org_id, actor_type="user", actor_id=user_id,
            action="ai.suggestion_approved", target_type="ai_suggestion", target_id=suggestion.id,
        )
        if edited:
            await issue_service.write_audit_log(
                session, org_id=suggestion.org_id, actor_type="user", actor_id=user_id,
                action="ai.suggestion_edited", target_type="ai_suggestion", target_id=suggestion.id,
            )
        # Validated human write (bypass_validation=False): an empty reply raises ValidationError. add_message commits
        # the approval, the audit rows and the message together, so a failure leaves the suggestion pending.
        await issue_service.add_message(
            session,
            issue_id=suggestion.issue_id,
            author_type="user",
            author_id=user_id,
            body_html=final_reply,
            actor_type="user",
            actor_id=user_id,
            bypass_validation=False,
        )
    except Exception:
        await session.rollback()
        raise
    await session.refresh(suggestion)
    return suggestion


async def reject(session: AsyncSession, suggestion_id: int, user_id: int, reason: str | None = None) -> AISuggestion:
    suggestion = await _load_pending(session, suggestion_id, user_id)
    try:
        await _claim(session, suggestion, new_status="rejected", user_id=user_id, reject_reason=reason)
        await issue_service.write_audit_log(
            session, org_id=suggestion.org_id, actor_type="user", actor_id=user_id,
            action="ai.suggestion_rejected", target_type="ai_suggestion", target_id=suggestion.id,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(suggestion)
    return suggestion
