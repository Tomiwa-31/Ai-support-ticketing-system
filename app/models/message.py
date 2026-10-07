from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), nullable=False)
    author_type: Mapped[str] = mapped_column(String, nullable=False)
    author_id: Mapped[int] = mapped_column(nullable=False)
    body_html: Mapped[str] = mapped_column(String, nullable=False)
    is_internal_note: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    issue: Mapped["Issue"] = relationship(back_populates="messages")


#author_type = "user", author_id = the support person, 
