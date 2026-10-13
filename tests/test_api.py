import asyncio

import httpx
import pytest_asyncio

from app.core import event_bus
from app.database import AsyncSessionLocal
from app.main import app
from tests.helpers import stop_tasks


@pytest_asyncio.fixture
async def client():
    # ASGITransport does not run the lifespan, so start the event-bus worker by hand.
    worker = asyncio.create_task(event_bus.run_worker(AsyncSessionLocal))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await stop_tasks(worker)


async def test_health(client):
    r = await client.get("/")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_create_issue_add_message_and_read_back(client):
    r = await client.post(
        "/issues", json={"org_id": 1, "title": "API issue", "account_id": 1, "contact_id": 1, "channel": "manual"}
    )
    assert r.status_code == 201
    issue_id = r.json()["id"]
    assert r.json()["status"] == "New"

    r = await client.post(
        f"/issues/{issue_id}/messages", json={"author_type": "contact", "author_id": 1, "body_html": "hi"}
    )
    assert r.status_code == 201

    body = (await client.get(f"/issues/{issue_id}")).json()
    assert body["status"] == "On You"
    assert [m["body_html"] for m in body["messages"]] == ["hi"]
    assert len((await client.get("/issues", params={"org_id": 1})).json()) == 1


async def test_unknown_issue_is_404(client):
    assert (await client.get("/issues/999")).status_code == 404
    r = await client.post("/issues/999/messages", json={"author_type": "contact", "author_id": 1, "body_html": "x"})
    assert r.status_code == 404


async def test_simulate_message_opens_issue_then_threads(client):
    payload = {"org_id": 1, "account_id": 1, "author_id": 1, "body": "urgent: down", "title": "urgent: down"}
    r = await client.post("/simulate/message", json=payload)
    assert r.status_code == 201
    issue_id = r.json()["issue_id"]

    r = await client.post("/simulate/message", json={**payload, "body": "more", "issue_id": issue_id})
    assert r.json()["issue_id"] == issue_id
    assert len((await client.get(f"/issues/{issue_id}")).json()["messages"]) == 2


async def test_simulate_unknown_issue_is_400(client):
    r = await client.post(
        "/simulate/message", json={"org_id": 1, "account_id": 1, "author_id": 1, "body": "x", "issue_id": 999}
    )
    assert r.status_code == 400


async def test_slack_webhook_is_inert_without_secret(client):
    assert (await client.post("/webhooks/slack", json={})).status_code == 503
