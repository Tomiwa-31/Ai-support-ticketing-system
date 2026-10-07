from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

#support agents/team members who work on issues. Each user belongs to one organization.

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)

    org: Mapped["Organization"] = relationship(back_populates="users")

    #"User has an attribute called assigned_issues, holding a list of Issue objects."
    #back_populates is the handshake that says "these two attributes are the same relationship seen from opposite ends."
    assigned_issues: Mapped[list["Issue"]] = relationship(back_populates="assignee")
