"""Shared fixtures. Every test runs against a throwaway SQLite file, never pylon_dummy.db or a real .env DB."""
import asyncio
import os
import tempfile
from pathlib import Path

# Must be set before `app` is imported: settings and the engine are built at import time.
_TMP_DIR = tempfile.mkdtemp(prefix="pylon_tests_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMP_DIR, 'test.db').as_posix()}"
os.environ["SLACK_SIGNING_SECRET"] = ""
os.environ["SLACK_BOT_TOKEN"] = ""
os.environ["GMAIL_ADDRESS"] = ""
os.environ["GMAIL_APP_PASSWORD"] = ""
# Tests must never reach the real API, even if .env holds a key (environment variables override .env).
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["VOYAGE_API_KEY"] = ""

import pytest_asyncio  # noqa: E402

import seed as seed_module  # noqa: E402
from app import models  # noqa: E402,F401
from app.ai import llm as ai_llm  # noqa: E402
from app.ai import queue as ai_queue  # noqa: E402
from app.core import event_bus  # noqa: E402
from app.knowledge import embeddings as kb_embeddings  # noqa: E402
from app.database import AsyncSessionLocal, Base, engine  # noqa: E402

# Ids created by seed.py on a fresh DB.
ORG_ID = 1
ACCOUNT_ID = 1
CONTACT_ID = 1
USER_ID = 1


_schema_ready = False


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    """Every test starts from freshly seeded tables. The schema is created once per run (DDL is slow on Windows);
    between tests the rows are cleared, which also restarts the id counters at 1 as the tests expect. The event bus
    and AI queues get queues bound to this test's event loop."""
    global _schema_ready
    async with engine.begin() as conn:
        if not _schema_ready:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            _schema_ready = True
        else:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())
    await seed_module.seed()
    event_bus._queue = asyncio.Queue()
    ai_queue.reset()
    ai_llm.set_client(None)
    kb_embeddings.set_embedder(None)
    yield
    ai_llm.set_client(None)
    kb_embeddings.set_embedder(None)
    await engine.dispose()


@pytest_asyncio.fixture
async def session():
    async with AsyncSessionLocal() as s:
        yield s
