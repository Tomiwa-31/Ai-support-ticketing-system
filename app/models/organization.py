from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="org")
    teams: Mapped[list["Team"]] = relationship(back_populates="org")
    accounts: Mapped[list["Account"]] = relationship(back_populates="org")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="org")
    issues: Mapped[list["Issue"]] = relationship(back_populates="org")
    tags: Mapped[list["Tag"]] = relationship(back_populates="org")
    triggers: Mapped[list["Trigger"]] = relationship(back_populates="org")
    slas: Mapped[list["SLA"]] = relationship(back_populates="org")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="org")


#That line sits inside the Organization class, so teams is an attribute of an organization object:
#org.teams   # all Team objects that belong to this org


#org.users -- this users all belong to this organization
#users.org -- this organinazitaion has this user
