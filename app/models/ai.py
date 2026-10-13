from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.database import Base

# AIRun.status lifecycle: running -> awaiting_approval -> approved | rejected | superseded; or running -> failed.
# AISuggestion.status: pending -> approved | rejected | superseded.


class IssueContext(Base):
    """Channel-supplied context an issue was opened with (tenant, product, customer ref, correlation id).

    The v1 schema is frozen, so this lives in its own table. Generic on purpose: any adapter may supply it.
    """

    __tablename__ = "issue_contexts"

    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    product: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)


class MessageContext(Base):
    """The same channel context, recorded for EVERY message that carries it (tenant, product, customer ref, correlation
    id). The AI worker answers the latest customer message with that message's own context, so a customer who switches
    product mid-conversation is handled correctly and each tool call is audited under the right correlation id."""

    __tablename__ = "message_contexts"

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    product: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)


class AIRun(Base):
    """One model call and everything needed to audit it. Prompt is stored MASKED, never raw."""

    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    model: Mapped[str] = mapped_column(String, nullable=False)
    masked_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AISuggestion(Base):
    """What the model proposed. Advisory only: nothing reaches the customer until a human approves it."""

    __tablename__ = "ai_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), nullable=False)
    ai_run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    category: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    draft_reply: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(String, nullable=False)
    final_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AIRunEvent(Base):
    """Append-only step log for one AI run (retrieval, citations; tool calls arrive in Slice 3). `detail` is JSON."""

    __tablename__ = "ai_run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
