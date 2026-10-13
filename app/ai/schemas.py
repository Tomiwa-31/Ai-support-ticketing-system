"""The only shape the model may return. Anything else is rejected, so a hostile or confused model output can't
introduce new categories, priorities or actions."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CATEGORIES = ("billing", "technical_issue", "account_access", "feature_request", "complaint", "general_inquiry", "other")
PRIORITIES = ("low", "medium", "high", "urgent")
# Slice 1 only displays the recommendation; later slices map these onto existing trigger actions.
ACTIONS = ("reply_only", "request_more_info", "escalate")


class Triage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    priority: Literal[PRIORITIES]  # type: ignore[valid-type]
    summary: str = Field(min_length=1, max_length=1000)
    draft_reply: str = Field(min_length=1, max_length=6000)
    recommended_action: Literal[ACTIONS]  # type: ignore[valid-type]
    # Ids of the knowledge articles the reply relies on. The worker keeps only ids it actually retrieved.
    cited_article_ids: list[int] = Field(max_length=20)


# JSON schema handed to the API's structured-output feature (keep in step with Triage).
TRIAGE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "priority": {"type": "string", "enum": list(PRIORITIES)},
        "summary": {"type": "string"},
        "draft_reply": {"type": "string"},
        "recommended_action": {"type": "string", "enum": list(ACTIONS)},
        "cited_article_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["category", "priority", "summary", "draft_reply", "recommended_action", "cited_article_ids"],
    "additionalProperties": False,
}
