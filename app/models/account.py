#Defines the accounts table: your customer companies
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)  
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    primary_domain: Mapped[str] = mapped_column(String, nullable=False)#company's email domain, like acme.com.

    org: Mapped["Organization"] = relationship(back_populates="accounts")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="account")#all the people who belong to this company. Pairs with contact.account, powered by an account_id foreign key on the contacts table
    issues: Mapped[list["Issue"]] = relationship(back_populates="account")

#An organization has many accounts, an account has many contacts, and contacts create issues.