import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app import models  # noqa: F401 -- registers models on Base.metadata
from app.ai import worker as ai_worker
from app.api import accounts, ai, contacts, conversio, issues, knowledge, simulate, webhooks
from app.channels import gmail_adapter
from app.core import event_bus
from app.database import AsyncSessionLocal, Base, engine
from app.knowledge import db as knowledge_db
from app.realtime import ws_manager
from app.sla import sla_engine

DASHBOARD_FILE = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await knowledge_db.before_create(conn)
        await conn.run_sync(Base.metadata.create_all)
        await knowledge_db.after_create(conn)
    ws_manager.manager.init(AsyncSessionLocal)
    background_tasks = [
        asyncio.create_task(event_bus.run_worker(AsyncSessionLocal)),
        asyncio.create_task(sla_engine.run_breach_checker(AsyncSessionLocal)),
        asyncio.create_task(gmail_adapter.run_poller(AsyncSessionLocal)),
        asyncio.create_task(ai_worker.run_worker(AsyncSessionLocal)),
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
app.include_router(conversio.router)
app.include_router(ai.router)
app.include_router(knowledge.router)
app.include_router(ws_manager.router)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(DASHBOARD_FILE)

#uvicorn app.main:app --reload
