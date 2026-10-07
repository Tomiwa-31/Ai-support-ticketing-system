import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.channels import slack_adapter
from app.database import AsyncSessionLocal

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/slack")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    if not slack_adapter.is_configured():
        raise HTTPException(status_code=503, detail="slack adapter is not configured")

    body = await request.body()
    if not slack_adapter.verify_signature(
        body,
        request.headers.get("X-Slack-Request-Timestamp"),
        request.headers.get("X-Slack-Signature"),
    ):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    # Slack redelivers when we're slow to ack; the first delivery is already being handled.
    if payload.get("type") == "event_callback" and not request.headers.get("X-Slack-Retry-Num"):
        background_tasks.add_task(slack_adapter.handle_event, AsyncSessionLocal, payload.get("event") or {})

    return {"ok": True}
