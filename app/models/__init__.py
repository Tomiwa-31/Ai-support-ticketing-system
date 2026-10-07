from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.issue import Issue, IssueStatus
from app.models.message import Message
from app.models.organization import Organization
from app.models.sla import SLA, SLAInstance
from app.models.tag import Tag, issue_tags
from app.models.team import Team
from app.models.trigger import Trigger, TriggerAction, TriggerCondition
from app.models.user import User


#imports all the model files so they can all run and register all of them to the base metadata. which start off empty
#Then create_all() sees the full register of 15 tables.
__all__ = [
    "Account",
    "AuditLog",
    "Contact",
    "Issue",
    "IssueStatus",
    "Message",
    "Organization",
    "SLA",
    "SLAInstance",
    "Tag",
    "issue_tags",
    "Team",
    "Trigger",
    "TriggerAction",
    "TriggerCondition",
    "User",
]
