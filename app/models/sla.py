from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SLA(Base):
    __tablename__ = "slas"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    counts_business_hours_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    org: Mapped["Organization"] = relationship(back_populates="slas")
    instances: Mapped[list["SLAInstance"]] = relationship(back_populates="sla")


class SLAInstance(Base):
    __tablename__ = "sla_instances"  ##is the running timer on one issue

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id"), nullable=False)
    sla_id: Mapped[int] = mapped_column(ForeignKey("slas.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breached_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    issue: Mapped["Issue"] = relationship(back_populates="sla_instances")
    sla: Mapped["SLA"] = relationship(back_populates="instances")
