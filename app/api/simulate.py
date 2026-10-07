from fastapi import APIRouter, HTTPException

from app.channels.manual_adapter import ManualAdapter
from app.core import event_bus
from app.schemas.message import MessageRead
from app.schemas.simulate import SimulateMessageRequest

router = APIRouter(prefix="/simulate", tags=["simulate"])

_adapter = ManualAdapter()


@router.post("/message", response_model=MessageRead, status_code=201)
async def simulate_message(payload: SimulateMessageRequest):
    event = _adapter.to_event(payload)
    try:
        message = await event_bus.publish_and_wait(event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return message


#venv\Scripts\activate
#uvicorn app.main:app --reload
#ngrok http 8000