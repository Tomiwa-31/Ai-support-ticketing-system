import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.tag import issue_tags


class IssueStatus(str, enum.Enum):
    NEW = "New"
    ON_YOU = "On You"
    ON_CUSTOMER = "On Customer"
    ON_HOLD = "On Hold"
    CLOSED = "Closed"


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=IssueStatus.NEW.value)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)#can be empty a new new issue starts unassigned
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    is_ticket: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    org: Mapped["Organization"] = relationship(back_populates="issues")
    account: Mapped["Account"] = relationship(back_populates="issues")
    contact: Mapped["Contact"] = relationship(back_populates="issues")
    assignee: Mapped["User | None"] = relationship(back_populates="assigned_issues")
    team: Mapped["Team | None"] = relationship(back_populates="issues")
    messages: Mapped[list["Message"]] = relationship(back_populates="issue")
    tags: Mapped[list["Tag"]] = relationship(secondary=issue_tags, back_populates="issues")
    sla_instances: Mapped[list["SLAInstance"]] = relationship(back_populates="issue")
