from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.issue_service import write_audit_log
from app.database import get_db
from app.models import Account
from app.schemas.account import AccountCreate, AccountRead

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountRead, status_code=201)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db)):
    account = Account(org_id=payload.org_id, name=payload.name, primary_domain=payload.primary_domain)
    db.add(account)
    await db.flush()

    await write_audit_log(
        db,
        org_id=payload.org_id,
        actor_type="api",
        actor_id=None,
        action="account.created",
        target_type="account",
        target_id=account.id,
    )

    await db.commit()
    await db.refresh(account)
    return account


@router.get("", response_model=list[AccountRead])
async def list_accounts(org_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Account).where(Account.org_id == org_id))
    return list(result.all())


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return account
