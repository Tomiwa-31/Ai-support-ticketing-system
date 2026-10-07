from datetime import datetime

from pydantic import BaseModel


class SimulateMessageRequest(BaseModel):
    org_id: int
    account_id: int
    author_type: str = "contact"  # "contact" (customer) or "user" (teammate)
    author_id: int
    body: str
    issue_id: int | None = None  # attach to an existing issue; omit to open a new one
    title: str | None = None  # used only when opening a new issue
    is_internal_note: bool = False
    external_thread_id: str | None = None
    external_message_id: str | None = None
    occurred_at: datetime | None = None
