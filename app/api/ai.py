import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import events as ai_events
from app.ai import service
from app.core.issue_service import ValidationError
from app.database import get_db
from app.models import AIRun, AISuggestion

router = APIRouter(prefix="/ai", tags=["ai"])


class SuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_id: int
    ai_run_id: int
    status: str
    category: str
    priority: str
    summary: str
    draft_reply: str
    recommended_action: str
    final_reply: str | None
    decided_by_user_id: int | None
    decided_at: datetime | None
    reject_reason: str | None
    created_at: datetime


class RunRead(BaseModel):
    """The audit record for one model call. The prompt shown here is the MASKED prompt that was actually sent."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_id: int
    correlation_id: str
    status: str
    model: str
    masked_prompt: str
    response_json: str | None
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    created_at: datetime
    finished_at: datetime | None


class RunEventRead(BaseModel):
    id: int
    event_type: str
    detail: dict
    created_at: datetime


class RunDetail(RunRead):
    """The run plus its step log (knowledge retrieval, citations; tool calls later)."""

    events: list[RunEventRead] = []


class ApproveRequest(BaseModel):
    user_id: int
    reply_text: str | None = None  # the agent's edited reply; omit to send the draft as written


class RejectRequest(BaseModel):
    user_id: int
    reason: str | None = None


@router.get("/suggestions", response_model=list[SuggestionRead])
async def list_suggestions(status: str | None = None, issue_id: int | None = None, db: AsyncSession = Depends(get_db)):
    query = select(AISuggestion).order_by(AISuggestion.id.desc())
    if status:
        query = query.where(AISuggestion.status == status)
    if issue_id is not None:
        query = query.where(AISuggestion.issue_id == issue_id)
    return list((await db.scalars(query)).all())


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    events = [
        RunEventRead(id=e.id, event_type=e.event_type, detail=json.loads(e.detail), created_at=e.created_at)
        for e in await ai_events.list_events(db, run_id)
    ]
    return RunDetail(**RunRead.model_validate(run).model_dump(), events=events)


@router.post("/suggestions/{suggestion_id}/approve", response_model=SuggestionRead)
async def approve(suggestion_id: int, payload: ApproveRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await service.approve(db, suggestion_id, payload.user_id, payload.reply_text)
    except service.SuggestionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.SuggestionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (service.InvalidApprover, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionRead)
async def reject(suggestion_id: int, payload: RejectRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await service.reject(db, suggestion_id, payload.user_id, payload.reason)
    except service.SuggestionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.SuggestionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.InvalidApprover as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
