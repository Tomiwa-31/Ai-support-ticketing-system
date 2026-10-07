import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app import models  # noqa: F401 -- registers models on Base.metadata
from app.api import accounts, contacts, issues, simulate, webhooks
from app.channels import gmail_adapter
from app.core import event_bus
from app.database import AsyncSessionLocal, Base, engine
from app.realtime import ws_manager
from app.sla import sla_engine

DASHBOARD_FILE = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ws_manager.manager.init(AsyncSessionLocal)
    background_tasks = [
        asyncio.create_task(event_bus.run_worker(AsyncSessionLocal)),
        asyncio.create_task(sla_engine.run_breach_checker(AsyncSessionLocal)),
        asyncio.create_task(gmail_adapter.run_poller(AsyncSessionLocal)),
    ]
    yield
    for task in background_tasks:
        task.cancel()
    for task in background_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Pylon Dummy", lifespan=lifespan)

app.include_router(issues.router)
app.include_router(accounts.router)
app.include_router(contacts.router)
app.include_router(simulate.router)
app.include_router(webhooks.router)
app.include_router(ws_manager.router)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(DASHBOARD_FILE)

#uvicorn app.main:app --reload
