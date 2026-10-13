"""Append-only step log for an AI run (ai_run_events): retrieval, citations, and later tool calls."""
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIRunEvent, KnowledgeArticle


async def log_event(session: AsyncSession, run_id: int, event_type: str, detail: dict[str, Any]) -> None:
    session.add(AIRunEvent(ai_run_id=run_id, event_type=event_type, detail=json.dumps(detail)))
    await session.flush()


async def list_events(session: AsyncSession, run_id: int) -> list[AIRunEvent]:
    rows = await session.scalars(select(AIRunEvent).where(AIRunEvent.ai_run_id == run_id).order_by(AIRunEvent.id))
    return list(rows.all())


async def knowledge_sources(session: AsyncSession, run_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """For each run: the articles retrieved for it, with whether the model cited them. Used by the dashboard."""
    if not run_ids:
        return {}
    rows = await session.scalars(
        select(AIRunEvent).where(AIRunEvent.ai_run_id.in_(run_ids), AIRunEvent.event_type.in_(["retrieval", "citations"])).order_by(AIRunEvent.id)
    )
    retrieved: dict[int, dict[int, float]] = {}
    cited: dict[int, set[int]] = {}
    for event in rows.all():
        detail = json.loads(event.detail)
        if event.event_type == "retrieval":
            best: dict[int, float] = {}
            for hit in detail.get("hits", []):
                best[hit["article_id"]] = max(best.get(hit["article_id"], -1.0), hit["score"])
            retrieved[event.ai_run_id] = best
        else:
            cited[event.ai_run_id] = set(detail.get("cited", []))

    article_ids = {a for best in retrieved.values() for a in best}
    titles = {}
    if article_ids:
        titles = {
            a.id: a.title
            for a in (await session.scalars(select(KnowledgeArticle).where(KnowledgeArticle.id.in_(article_ids)))).all()
        }
    return {
        run_id: [
            {"article_id": a, "title": titles.get(a, f"article {a}"), "score": round(score, 3), "cited": a in cited.get(run_id, set())}
            for a, score in sorted(best.items(), key=lambda kv: -kv[1])
        ]
        for run_id, best in retrieved.items()
    }


async def tool_activity(session: AsyncSession, run_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """For each run: the tool calls the gateway made or refused, in order. Used by the dashboard."""
    if not run_ids:
        return {}
    rows = await session.scalars(
        select(AIRunEvent)
        .where(AIRunEvent.ai_run_id.in_(run_ids), AIRunEvent.event_type.in_(["tool_call", "tool_denied"]))
        .order_by(AIRunEvent.id)
    )
    activity: dict[int, list[dict[str, Any]]] = {}
    for event in rows.all():
        detail = json.loads(event.detail)
        status = "denied" if event.event_type == "tool_denied" else ("error" if detail.get("is_error") else "ok")
        activity.setdefault(event.ai_run_id, []).append({"tool": detail.get("tool"), "status": status})
    return activity
