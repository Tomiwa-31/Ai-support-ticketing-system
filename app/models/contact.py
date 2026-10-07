#Defines the contacts table: individual people at your customer companies (Chidi at Dangote).

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)

    org: Mapped["Organization"] = relationship(back_populates="contacts")
    account: Mapped["Account"] = relationship(back_populates="contacts")
    issues: Mapped[list["Issue"]] = relationship(back_populates="contact")
