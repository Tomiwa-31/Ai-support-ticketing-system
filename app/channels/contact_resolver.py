from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.issue_service import write_audit_log
from app.models import Account, Contact, Organization


@dataclass
class ResolvedContact:
    org_id: int
    account_id: int
    contact_id: int


async def resolve_contact(session: AsyncSession, *, email: str, name: str) -> ResolvedContact:
    """Find (or auto-create) the contact for an external sender, plus their account by email domain.

    v1 is single-tenant: everything lands in the first organization.
    """
    email = email.strip().lower()
    org_id = await session.scalar(select(Organization.id).order_by(Organization.id).limit(1))
    if org_id is None:
        raise RuntimeError("no organization exists; run seed.py first")

    contact = await session.scalar(
        select(Contact).where(Contact.org_id == org_id, func.lower(Contact.email) == email)
    )
    if contact is not None:
        return ResolvedContact(org_id=org_id, account_id=contact.account_id, contact_id=contact.id)

    domain = email.rpartition("@")[2]
    account = await session.scalar(
        select(Account).where(Account.org_id == org_id, func.lower(Account.primary_domain) == domain)
    )
    if account is None:
        account = Account(org_id=org_id, name=domain, primary_domain=domain)
        session.add(account)
        await session.flush()
        await write_audit_log(
            session, org_id=org_id, actor_type="channel", actor_id=None,
            action="account.created", target_type="account", target_id=account.id,
        )

    contact = Contact(org_id=org_id, account_id=account.id, name=name or email, email=email)
    session.add(contact)
    await session.flush()
    await write_audit_log(
        session, org_id=org_id, actor_type="channel", actor_id=None,
        action="contact.created", target_type="contact", target_id=contact.id,
    )
    await session.commit()
    return ResolvedContact(org_id=org_id, account_id=account.id, contact_id=contact.id)
