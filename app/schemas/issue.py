from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.message import MessageRead


class IssueCreate(BaseModel):
    org_id: int
    title: str
    account_id: int
    contact_id: int
    channel: str = "manual"
    assignee_id: int | None = None
    team_id: int | None = None
    is_ticket: bool = True


class IssueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    title: str
    status: str
    account_id: int
    contact_id: int
    assignee_id: int | None
    team_id: int | None
    channel: str
    is_ticket: bool
    created_at: datetime
    resolved_at: datetime | None
    updated_at: datetime


class IssueWithMessages(IssueRead):
    messages: list[MessageRead] = []
