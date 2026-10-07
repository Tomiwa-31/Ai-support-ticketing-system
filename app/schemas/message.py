from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageCreate(BaseModel):
    author_type: str
    author_id: int
    body_html: str
    is_internal_note: bool = False


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_id: int
    author_type: str
    author_id: int
    body_html: str
    is_internal_note: bool
    created_at: datetime
