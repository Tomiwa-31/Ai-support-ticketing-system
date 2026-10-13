"""Conversio chat simulator: adapter contract and the whole Slice 1 story over HTTP with a fake model."""
import asyncio

import httpx
import pytest_asyncio

from app.ai import llm as ai_llm
from app.ai import queue as ai_queue
from app.ai import worker as ai_worker
from app.channels.conversio_adapter import ConversioAdapter
from app.core import event_bus
from app.database import AsyncSessionLocal
from app.main import app
from app.schemas.conversio import ConversioMessage
from tests.fakes import FakeLLM
from tests.helpers import stop_tasks

RAW_CARD = "4111 1111 1111 1111"


def payload(text="I was charged twice", **overrides):
    body = {
        "tenant_id": "commsworth",
        "user": {"id": "u-1", "email": "jamie@acme.com", "name": "Jamie Customer"},
        "product": "credipay",
        "conversation_id": "conv-1",
        "correlation_id": "corr-abc",
        "text": text,
    }
    body.update(overrides)
    return body


@pytest_asyncio.fixture
async def client():
    ai_llm.set_client(FakeLLM())
    tasks = [
        asyncio.create_task(event_bus.run_worker(AsyncSessionLocal)),
        asyncio.create_task(ai_worker.run_worker(AsyncSessionLocal)),
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    # Let in-flight work finish first: cancelling a worker mid-commit would leave the SQLite file locked.
    await asyncio.wait_for(event_bus._queue.join(), timeout=15)
    await asyncio.wait_for(ai_queue._queue.join(), timeout=15)
    await stop_tasks(*tasks)


async def wait_for_suggestion(client, status="pending", timeout=15):
    for _ in range(int(timeout * 20)):
        found = (await client.get("/ai/suggestions", params={"status": status})).json()
        if found:
            return found[0]
        await asyncio.sleep(0.05)
    raise AssertionError(f"no {status} suggestion appeared")


def test_adapter_produces_the_canonical_event_with_context():
    adapter = ConversioAdapter()
    event = adapter.to_event(
        {"message": ConversioMessage(**payload()), "org_id": 1, "account_id": 1, "contact_id": 7}
    )
    assert event.channel == "conversio" and event.external_thread_id == "conv-1"
    assert event.author == {"type": "contact", "id": 7} and event.body == "I was charged twice"
    assert event.context == {
        "tenant_id": "commsworth", "product": "credipay", "customer_ref": "u-1", "correlation_id": "corr-abc",
    }


def test_adapter_generates_a_correlation_id_when_none_is_supplied():
    event = ConversioAdapter().to_event(
        {"message": ConversioMessage(**payload(correlation_id=None)), "org_id": 1, "account_id": 1, "contact_id": 1}
    )
    assert event.context["correlation_id"]


async def test_full_story_chat_to_masked_ai_draft_to_agent_approval_to_customer_reply(client):
    sent = await client.post("/conversio/messages", json=payload(f"I was charged twice, card {RAW_CARD}"))
    assert sent.status_code == 201
    issue_id = sent.json()["issue_id"]
    assert sent.json()["correlation_id"] == "corr-abc"

    # The AI runs on its own queue and produces a PENDING suggestion.
    suggestion = await wait_for_suggestion(client)
    assert suggestion["issue_id"] == issue_id

    # Audit record for the run: masked prompt only, tokens and latency present, linked by correlation id.
    run = (await client.get(f"/ai/runs/{suggestion['ai_run_id']}")).json()
    assert RAW_CARD not in run["masked_prompt"] and "[CARD_1]" in run["masked_prompt"]
    assert run["correlation_id"] == "corr-abc" and run["input_tokens"] == 120 and run["latency_ms"] is not None

    # The customer's chat shows only their own message: the draft has not been sent.
    chat = (await client.get("/conversio/conversations/conv-1")).json()
    assert [m["sender"] for m in chat["messages"]] == ["customer"]

    # The agent edits and approves; the reply reaches the chat and the ticket moves to On Customer.
    approved = await client.post(
        f"/ai/suggestions/{suggestion['id']}/approve", json={"user_id": 1, "reply_text": "Refund is on its way."}
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    chat = (await client.get("/conversio/conversations/conv-1")).json()
    assert [(m["sender"], m["text"]) for m in chat["messages"]][1:] == [("agent", "Refund is on its way.")]
    assert (await client.get(f"/issues/{issue_id}")).json()["status"] == "On Customer"


async def test_rejected_suggestion_never_reaches_the_chat(client):
    await client.post("/conversio/messages", json=payload())
    suggestion = await wait_for_suggestion(client)
    rejected = await client.post(f"/ai/suggestions/{suggestion['id']}/reject", json={"user_id": 1, "reason": "no"})
    assert rejected.json()["status"] == "rejected"
    chat = (await client.get("/conversio/conversations/conv-1")).json()
    assert [m["sender"] for m in chat["messages"]] == ["customer"]


async def test_second_message_joins_the_same_issue(client):
    first = (await client.post("/conversio/messages", json=payload())).json()
    second = (await client.post("/conversio/messages", json=payload("Any update?"))).json()
    assert first["issue_id"] == second["issue_id"]
    assert len((await client.get("/conversio/conversations/conv-1")).json()["messages"]) == 2


async def test_internal_notes_are_hidden_from_the_chat(client):
    issue_id = (await client.post("/conversio/messages", json=payload())).json()["issue_id"]
    await client.post(
        f"/issues/{issue_id}/messages",
        json={"author_type": "user", "author_id": 1, "body_html": "INTERNAL: VIP", "is_internal_note": True},
    )
    texts = [m["text"] for m in (await client.get("/conversio/conversations/conv-1")).json()["messages"]]
    assert texts == ["I was charged twice"]


async def test_unknown_conversation_is_an_empty_chat(client):
    chat = (await client.get("/conversio/conversations/nope")).json()
    assert chat == {"conversation_id": "nope", "issue_id": None, "messages": []}


async def test_empty_message_is_rejected(client):
    assert (await client.post("/conversio/messages", json=payload(""))).status_code == 422


async def test_approval_endpoint_errors(client):
    body = {"user_id": 1}
    assert (await client.post("/ai/suggestions/999/approve", json=body)).status_code == 404
    await client.post("/conversio/messages", json=payload())
    suggestion = await wait_for_suggestion(client)
    path = f"/ai/suggestions/{suggestion['id']}/approve"
    assert (await client.post(path, json={"user_id": 999})).status_code == 400
    assert (await client.post(path, json={"user_id": 1, "reply_text": "  "})).status_code == 400
    assert (await client.post(path, json=body)).status_code == 200
    assert (await client.post(path, json=body)).status_code == 409


async def test_pages_are_served(client):
    assert "Conversio" in (await client.get("/conversio")).text
    assert (await client.get("/dashboard")).status_code == 200
