from pydantic import BaseModel, Field


class ConversioUser(BaseModel):
    id: str = Field(min_length=1)
    email: str = Field(min_length=3)
    name: str = ""


class ConversioMessage(BaseModel):
    """What the (simulated) Conversio chat sends: tenant, user, product and correlation context travel with every message."""

    tenant_id: str = Field(min_length=1)
    user: ConversioUser
    product: str | None = None
    conversation_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    message_id: str | None = None
    correlation_id: str | None = None


class ConversioPosted(BaseModel):
    conversation_id: str
    issue_id: int
    message_id: int
    correlation_id: str


class ConversioChatMessage(BaseModel):
    id: int
    sender: str  # "customer" | "agent"
    text: str
    created_at: str | None


class ConversioConversation(BaseModel):
    conversation_id: str
    issue_id: int | None
    messages: list[ConversioChatMessage]
