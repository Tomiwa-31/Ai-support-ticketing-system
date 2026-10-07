from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import issue_service
from app.database import get_db
from app.schemas.issue import IssueCreate, IssueRead, IssueWithMessages
from app.schemas.message import MessageCreate, MessageRead

router = APIRouter(prefix="/issues", tags=["issues"])


@router.post("", response_model=IssueRead, status_code=201)
async def create_issue(payload: IssueCreate, db: AsyncSession = Depends(get_db)):
    issue = await issue_service.create_issue(
        db,
        org_id=payload.org_id,
        title=payload.title,
        account_id=payload.account_id,
        contact_id=payload.contact_id,
        channel=payload.channel,
        assignee_id=payload.assignee_id,
        team_id=payload.team_id,
        is_ticket=payload.is_ticket,
    )
    return issue


@router.get("", response_model=list[IssueRead])
async def list_issues(org_id: int, db: AsyncSession = Depends(get_db)):# lists all the issues for a given org_id(organization).
    return await issue_service.list_issues(db, org_id)


@router.get("/{issue_id}", response_model=IssueWithMessages)
async def get_issue(issue_id: int, db: AsyncSession = Depends(get_db)):
    issue = await issue_service.get_issue(db, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue not found")
    messages = await issue_service.list_messages(db, issue_id)
    return IssueWithMessages(**IssueRead.model_validate(issue).model_dump(), messages=messages)#combines result of both function get issue and lsit message


@router.post("/{issue_id}/messages", response_model=MessageRead, status_code=201)
async def add_message(issue_id: int, payload: MessageCreate, db: AsyncSession = Depends(get_db)):
    message = await issue_service.add_message(
        db,
        issue_id=issue_id,
        author_type=payload.author_type,
        author_id=payload.author_id,
        body_html=payload.body_html,
        is_internal_note=payload.is_internal_note,
    )
    if message is None:
        raise HTTPException(status_code=404, detail="issue not found")
    return message


@router.get("/{issue_id}/messages", response_model=list[MessageRead])
async def list_messages(issue_id: int, db: AsyncSession = Depends(get_db)):
    issue = await issue_service.get_issue(db, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue not found")
    return await issue_service.list_messages(db, issue_id)
