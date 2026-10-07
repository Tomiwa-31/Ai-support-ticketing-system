from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Trigger(Base):
    __tablename__ = "triggers"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kickoff_event: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    org: Mapped["Organization"] = relationship(back_populates="triggers")
    conditions: Mapped[list["TriggerCondition"]] = relationship(back_populates="trigger")
    actions: Mapped[list["TriggerAction"]] = relationship(back_populates="trigger")


class TriggerCondition(Base):
    __tablename__ = "trigger_conditions"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_id: Mapped[int] = mapped_column(ForeignKey("triggers.id"), nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    operator: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)

    trigger: Mapped["Trigger"] = relationship(back_populates="conditions")


class TriggerAction(Base):
    __tablename__ = "trigger_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_id: Mapped[int] = mapped_column(ForeignKey("triggers.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    trigger: Mapped["Trigger"] = relationship(back_populates="actions")
