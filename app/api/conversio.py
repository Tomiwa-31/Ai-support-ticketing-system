from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.contact_resolver import resolve_contact
from app.channels.conversio_adapter import ConversioAdapter
from app.core import event_bus, issue_service
from app.database import get_db
from app.schemas.conversio import ConversioChatMessage, ConversioConversation, ConversioMessage, ConversioPosted

router = APIRouter(prefix="/conversio", tags=["conversio"])

_adapter = ConversioAdapter()
PAGE_FILE = Path(__file__).resolve().parent.parent.parent / "dashboard" / "conversio.html"


@router.get("", include_in_schema=False)
async def chat_page():
    return FileResponse(PAGE_FILE)


@router.post("/messages", response_model=ConversioPosted, status_code=201)
async def post_message(payload: ConversioMessage, db: AsyncSession = Depends(get_db)):
    """A customer message from the Conversio chat. v1 is single-tenant, so the tenant id is recorded as context only."""
    resolved = await resolve_contact(db, email=payload.user.email, name=payload.user.name)
    event = _adapter.to_event(
        {
            "message": payload,
            "org_id": resolved.org_id,
            "account_id": resolved.account_id,
            "contact_id": resolved.contact_id,
        }
    )
    try:
        message = await event_bus.publish_and_wait(event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConversioPosted(
        conversation_id=payload.conversation_id,
        issue_id=message.issue_id,
        message_id=message.id,
        correlation_id=event.context["correlation_id"],  # type: ignore[index]
    )


@router.get("/conversations/{conversation_id}", response_model=ConversioConversation)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """What the customer's chat shows: customer messages and agent replies. Internal notes are never included, and
    an AI suggestion is never here until an agent has approved it (it only becomes a message on approval)."""
    issue_id = await event_bus.find_linked_issue_id(db, _adapter.channel, conversation_id)
    if issue_id is None:
        return ConversioConversation(conversation_id=conversation_id, issue_id=None, messages=[])
    messages = await issue_service.list_messages(db, issue_id)
    return ConversioConversation(
        conversation_id=conversation_id,
        issue_id=issue_id,
        messages=[
            ConversioChatMessage(
                id=m.id,
                sender="customer" if m.author_type == "contact" else "agent",
                text=m.body_html,
                created_at=m.created_at.isoformat() + "Z" if m.created_at else None,
            )
            for m in messages
            if not m.is_internal_note
        ],
    )
