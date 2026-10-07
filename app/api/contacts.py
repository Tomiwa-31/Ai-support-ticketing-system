from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.issue_service import write_audit_log
from app.database import get_db
from app.models import Contact
from app.schemas.contact import ContactCreate, ContactRead

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.post("", response_model=ContactRead, status_code=201)
async def create_contact(payload: ContactCreate, db: AsyncSession = Depends(get_db)):
    contact = Contact(
        org_id=payload.org_id,
        account_id=payload.account_id,
        name=payload.name,
        email=payload.email,
    )
    db.add(contact)
    await db.flush()

    await write_audit_log(
        db,
        org_id=payload.org_id,
        actor_type="api",
        actor_id=None,
        action="contact.created",
        target_type="contact",
        target_id=contact.id,
    )

    await db.commit()
    await db.refresh(contact)
    return contact


@router.get("", response_model=list[ContactRead])
async def list_contacts(org_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Contact).where(Contact.org_id == org_id))
    return list(result.all())


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(contact_id: int, db: AsyncSession = Depends(get_db)):
    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")
    return contact
