import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.ai import events as ai_events
from app.models import SLA, AIRun, AISuggestion, AuditLog, Contact, Issue, Message, SLAInstance, Tag, User
from app.models.tag import issue_tags
from app.sla import sla_engine

AUDIT_LOG_LIMIT = 100
BROADCAST_DEBOUNCE_SECONDS = 0.15


def _iso(value: datetime | None) -> str | None:
    # Everything is stored as naive UTC, so mark it as such for the browser.
    return value.isoformat() + "Z" if value else None


async def build_snapshot(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    async with session_factory() as session:
        issues = (await session.scalars(select(Issue).order_by(Issue.id.desc()))).all()
        contact_names = {c.id: c.name for c in (await session.scalars(select(Contact))).all()}
        user_names = {u.id: u.name for u in (await session.scalars(select(User))).all()}

        tags_by_issue: dict[int, list[str]] = {}
        tag_rows = await session.execute(
            select(issue_tags.c.issue_id, Tag.name).join(Tag, Tag.id == issue_tags.c.tag_id)
        )
        for issue_id, tag_name in tag_rows.all():
            tags_by_issue.setdefault(issue_id, []).append(tag_name)

        messages_by_issue: dict[int, list[dict[str, Any]]] = {}
        for message in (await session.scalars(select(Message).order_by(Message.id))).all():
            names = contact_names if message.author_type == "contact" else user_names
            messages_by_issue.setdefault(message.issue_id, []).append(
                {
                    "id": message.id,
                    "author_type": message.author_type,
                    "author_name": names.get(message.author_id, f"{message.author_type} {message.author_id}"),
                    "body": message.body_html,
                    "is_internal_note": message.is_internal_note,
                    "created_at": _iso(message.created_at),
                }
            )

        issues_by_id = {issue.id: issue for issue in issues}
        sla_by_issue: dict[int, dict[str, Any]] = {}
        sla_rows = await session.execute(
            select(SLAInstance, SLA).join(SLA, SLA.id == SLAInstance.sla_id).order_by(SLAInstance.id)
        )
        now = sla_engine.utcnow()
        for instance, sla in sla_rows.all():
            issue = issues_by_id[instance.issue_id]
            sla_by_issue[instance.issue_id] = {
                "name": sla.name,
                "target_minutes": sla.target_minutes,
                "elapsed_seconds": await sla_engine.elapsed_seconds(session, instance, issue, now),
                "running": instance.breached_at is None and sla_engine.is_counting(issue.status),
                "breached_at": _iso(instance.breached_at),
            }

        # Latest AI run and suggestion per issue (ids ascend, so the last one written wins).
        latest_run: dict[int, AIRun] = {r.issue_id: r for r in (await session.scalars(select(AIRun).order_by(AIRun.id))).all()}
        latest_suggestion: dict[int, AISuggestion] = {
            s.issue_id: s for s in (await session.scalars(select(AISuggestion).order_by(AISuggestion.id))).all()
        }
        sources_by_run = await ai_events.knowledge_sources(session, [r.id for r in latest_run.values()])
        tools_by_run = await ai_events.tool_activity(session, [r.id for r in latest_run.values()])
        ai_by_issue: dict[int, dict[str, Any]] = {}
        for issue_id, run in latest_run.items():
            suggestion = latest_suggestion.get(issue_id)
            ai_by_issue[issue_id] = {
                "run_id": run.id,
                "run_status": run.status,
                "run_error": run.error,
                "sources": sources_by_run.get(run.id, []),
                "tools": tools_by_run.get(run.id, []),
                "suggestion": None
                if suggestion is None
                else {
                    "id": suggestion.id,
                    "status": suggestion.status,
                    "category": suggestion.category,
                    "priority": suggestion.priority,
                    "summary": suggestion.summary,
                    "draft_reply": suggestion.draft_reply,
                    "recommended_action": suggestion.recommended_action,
                    "final_reply": suggestion.final_reply,
                },
            }

        audit_logs = (
            await session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(AUDIT_LOG_LIMIT))
        ).all()

        return {
            "type": "snapshot",
            "issues": [
                {
                    "id": issue.id,
                    "title": issue.title,
                    "status": issue.status,
                    "channel": issue.channel,
                    "contact_name": contact_names.get(issue.contact_id, f"contact {issue.contact_id}"),
                    "team_id": issue.team_id,
                    "created_at": _iso(issue.created_at),
                    "updated_at": _iso(issue.updated_at),
                    "tags": sorted(tags_by_issue.get(issue.id, [])),
                    "sla": sla_by_issue.get(issue.id),
                    "messages": messages_by_issue.get(issue.id, []),
                    "ai": ai_by_issue.get(issue.id),
                }
                for issue in issues
            ],
            "audit_logs": [
                {
                    "id": log.id,
                    "actor_type": log.actor_type,
                    "actor_id": log.actor_id,
                    "action": log.action,
                    "target_type": log.target_type,
                    "target_id": log.target_id,
                    "happened_at": _iso(log.happened_at),
                }
                for log in audit_logs
            ],
        }


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._broadcast_scheduled = False
        self._tasks: set[asyncio.Task] = set()

    def init(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        assert self._session_factory is not None
        await websocket.send_json(await build_snapshot(self._session_factory))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    def notify_changed(self) -> None:
        """Called after any DB commit. Coalesces bursts of commits into one snapshot broadcast."""
        if not self._connections or self._session_factory is None or self._broadcast_scheduled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._broadcast_scheduled = True
        task = loop.create_task(self._broadcast())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _broadcast(self) -> None:
        await asyncio.sleep(BROADCAST_DEBOUNCE_SECONDS)
        self._broadcast_scheduled = False
        if not self._connections:
            return
        assert self._session_factory is not None
        snapshot = await build_snapshot(self._session_factory)
        for websocket in list(self._connections):
            try:
                await websocket.send_json(snapshot)
            except Exception:  # noqa: BLE001 -- a dead socket shouldn't block the others
                self._connections.discard(websocket)


manager = ConnectionManager()


@event.listens_for(Session, "after_commit")
def _on_commit(_session: Session) -> None:
    manager.notify_changed()


router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
