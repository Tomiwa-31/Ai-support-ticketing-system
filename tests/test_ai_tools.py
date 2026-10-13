"""Tools inside the AI worker: per-message context, product scoping, audited tool calls, masking, graceful failure,
and the model client's tool loop (against a mocked SDK)."""
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai import llm as ai_llm
from app.ai import worker
from app.ai.llm import AnthropicLLM
from app.core import event_bus
from app.database import AsyncSessionLocal
from app.mcp_gateway.gateway import ToolGateway
from app.mcp_gateway.registry import ServerConfig
from app.models import AIRun, AIRunEvent, IssueContext, MessageContext
from app.realtime import ws_manager
from tests.fakes import FakeLLM
from tests.helpers import audit_actions, conversio_event

ACCOUNT = "0123456789"  # LN-1001's destination account in the mock lending server
LENDING_TOOLS = {"find_loans_by_account", "get_disbursement_status", "get_repayment_schedule"}


async def _open(session, text, *, product="finsaas-lending", tenant="commsworth", thread="t-1", issue_id=None, corr="corr-1"):
    event = conversio_event(text, thread_id=thread, issue_id=issue_id)
    event.context = {"tenant_id": tenant, "product": product, "customer_ref": "u-1", "correlation_id": corr}
    return await event_bus._handle_event(session, event)


async def _events(session, run_id):
    rows = await session.scalars(select(AIRunEvent).where(AIRunEvent.ai_run_id == run_id).order_by(AIRunEvent.id))
    return [(e.event_type, json.loads(e.detail)) for e in rows.all()]


def _last4_from_tools(results):
    """What a model would do: read the account's last four digits out of the (masked) tool result."""
    for _, _, text, _ in results:
        match = re.search(r'"destination_account_last4": "(\d{4})"', text)
        if match:
            return {"draft_reply": f"Your loan is queued for bank verification; funds go to the account ending {match.group(1)}."}
    return {}


LENDING_SCRIPT = [
    ("find_loans_by_account", {"account_number": "[ACCOUNT_1]"}),
    ("get_disbursement_status", {"loan_reference": "LN-1001"}),
]


# ---- per-message context ----------------------------------------------------------------------------------------

async def test_every_message_keeps_its_own_context_not_just_the_first(session):
    first = await _open(session, "My loan has not arrived", product="credipay", corr="corr-A")
    second = await _open(session, "Actually it is about my lending product", product="finsaas-lending", corr="corr-B",
                         thread="t-1", issue_id=first.issue_id)
    rows = (await session.scalars(select(MessageContext).order_by(MessageContext.message_id))).all()
    assert [(r.message_id, r.product, r.correlation_id) for r in rows] == [
        (first.id, "credipay", "corr-A"), (second.id, "finsaas-lending", "corr-B"),
    ]
    issue_ctx = await session.get(IssueContext, first.issue_id)
    assert issue_ctx.product == "credipay"  # the issue-level record is unchanged: it is where the issue started
    assert (await audit_actions(session)).count("message.context_recorded") == 2


async def test_the_answer_uses_the_context_of_the_message_being_answered(session):
    first = await _open(session, "Question about payments", product="credipay", corr="corr-A")
    second = await _open(session, "Now a lending question", product="finsaas-lending", corr="corr-B",
                         thread="t-1", issue_id=first.issue_id)
    fake = FakeLLM()
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, second.issue_id)

    assert {t["name"] for t in fake.calls[0]["tools"]} == LENDING_TOOLS  # the lending tools, not credipay's
    assert "Product: finsaas-lending" in fake.calls[0]["user"]
    run = await session.get(AIRun, suggestion.ai_run_id)
    assert run.correlation_id == "corr-B"


async def test_a_message_without_context_falls_back_to_the_issue_context(session):
    first = await _open(session, "Loan question", corr="corr-A")
    plain = conversio_event("Any news?", thread_id="t-1", issue_id=first.issue_id)  # no context on this one
    plain.context = None
    await event_bus._handle_event(session, plain)
    fake = FakeLLM()
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, first.issue_id)
    assert {t["name"] for t in fake.calls[0]["tools"]} == LENDING_TOOLS
    assert (await session.get(AIRun, suggestion.ai_run_id)).correlation_id == "corr-A"


# ---- using tools ------------------------------------------------------------------------------------------------

async def test_tools_are_offered_for_the_product_only_and_the_guidance_is_in_the_prompt(session):
    message = await _open(session, "Where is my loan money?")
    fake = FakeLLM()
    ai_llm.set_client(fake)
    await worker.process_issue(session, message.issue_id)
    names = {t["name"] for t in fake.calls[0]["tools"]}
    assert names == LENDING_TOOLS and not names & {"lookup_transaction", "get_invoice_status"}
    assert "read-only lookups" in fake.calls[0]["system"] and "never guess an identifier" in fake.calls[0]["system"]


async def test_the_whole_story_account_number_to_tool_results_to_an_informed_draft(session):
    message = await _open(session, f"My loan was approved but the money is missing. My account number is {ACCOUNT}.")
    fake = FakeLLM(_last4_from_tools, tool_script=LENDING_SCRIPT)
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, message.issue_id)

    # The model asked, the gateway answered with real (mock) data, and the draft uses it.
    assert [name for name, *_ in fake.tool_results] == ["find_loans_by_account", "get_disbursement_status"]
    assert not any(is_error for *_, is_error in fake.tool_results)
    assert "ending 6789" in suggestion.draft_reply and suggestion.status == "pending"

    # What the model saw never contained the real values.
    seen = fake.calls[0]["user"] + " ".join(text for _, _, text, _ in fake.tool_results)
    for raw in (ACCOUNT, "ada.okafor@example.com", "802 555 0147"):
        assert raw not in seen
    assert "[ACCOUNT_1]" in seen and "[EMAIL_" in seen and "[PHONE_" in seen

    # Every call is on the run's audit record, masked, and summarised in audit_logs.
    run = await session.get(AIRun, suggestion.ai_run_id)
    kinds = [k for k, _ in await _events(session, run.id)]
    assert kinds == ["retrieval_failed", "tools_offered", "tool_call", "tool_call", "citations"]
    calls = [d for k, d in await _events(session, run.id) if k == "tool_call"]
    assert [c["tool"] for c in calls] == ["find_loans_by_account", "get_disbursement_status"]
    assert calls[0]["arguments"] == {"account_number": "[ACCOUNT_1]"} and calls[0]["is_error"] is False
    assert all(c["latency_ms"] >= 0 and c["server"] == "finsaas-lending" for c in calls)
    stored = json.dumps(await _events(session, run.id)) + run.masked_prompt
    for raw in (ACCOUNT, "ada.okafor@example.com", "802 555 0147"):
        assert raw not in stored
    actions = await audit_actions(session)
    assert "ai.tool_call:find_loans_by_account" in actions and "ai.tool_call:get_disbursement_status" in actions


async def test_nothing_reaches_the_customer_and_the_ticket_is_untouched_by_tool_use(session):
    from app.models import Issue, Message

    message = await _open(session, "Where is my money?")
    issue = await session.get(Issue, message.issue_id)
    before = (issue.status, issue.assignee_id, issue.team_id)
    ai_llm.set_client(FakeLLM(tool_script=LENDING_SCRIPT[1:]))
    await worker.process_issue(session, message.issue_id)
    await session.refresh(issue)
    assert (issue.status, issue.assignee_id, issue.team_id) == before
    authors = (await session.scalars(select(Message.author_type).where(Message.issue_id == issue.id))).all()
    assert list(authors) == ["contact"]


async def test_a_write_tool_the_model_asks_for_is_denied_and_the_run_still_completes(session):
    message = await _open(session, "Please refund me")
    fake = FakeLLM(tool_script=[("refund_payment", {"amount": 100})])
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, message.issue_id)
    assert suggestion is not None and fake.tool_results[0][3] is True and "not available" in fake.tool_results[0][2]
    run = await session.get(AIRun, suggestion.ai_run_id)
    denied = [d for k, d in await _events(session, run.id) if k == "tool_denied"]
    assert denied and denied[0]["tool"] == "refund_payment" and "not available" in denied[0]["denied"]
    assert "ai.tool_denied:refund_payment" in await audit_actions(session)


async def test_a_card_number_placeholder_is_never_passed_to_a_tool(session):
    message = await _open(session, "My card 4111 1111 1111 1111 was charged twice", product="credipay")
    fake = FakeLLM(tool_script=[("lookup_transaction", {"reference": "[CARD_1]"})])
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, message.issue_id)
    assert "card numbers are never sent to tools" in fake.tool_results[0][2]
    run = await session.get(AIRun, suggestion.ai_run_id)
    assert any(k == "tool_denied" for k, _ in await _events(session, run.id))


async def test_a_tool_that_errors_is_reported_to_the_model_and_logged_without_failing_the_run(session):
    message = await _open(session, "Where is loan LN-9999?")
    fake = FakeLLM(tool_script=[("get_disbursement_status", {"loan_reference": "LN-9999"})])
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, message.issue_id)
    assert suggestion is not None and fake.tool_results[0][3] is True and "not found" in fake.tool_results[0][2]
    run = await session.get(AIRun, suggestion.ai_run_id)
    call = next(d for k, d in await _events(session, run.id) if k == "tool_call")
    assert call["is_error"] is True


async def test_the_per_run_call_budget_is_enforced(session):
    worker.set_gateway(ToolGateway(max_calls=1))
    try:
        message = await _open(session, "Where is my money?")
        fake = FakeLLM(tool_script=[("get_repayment_schedule", {"loan_reference": "LN-1001"})] * 3)
        ai_llm.set_client(fake)
        suggestion = await worker.process_issue(session, message.issue_id)
    finally:
        worker.set_gateway(None)
    run = await session.get(AIRun, suggestion.ai_run_id)
    kinds = [k for k, _ in await _events(session, run.id)]
    assert kinds.count("tool_call") == 1 and kinds.count("tool_denied") == 2


# ---- tools unavailable: the run degrades, it does not fail ------------------------------------------------------

@pytest.mark.parametrize(
    "tenant, product, reason",
    [("someone-else", "credipay", "not mapped"), ("commsworth", "unknown-product", "not mapped")],
)
async def test_unmapped_tenant_or_product_gets_no_tools(session, tenant, product, reason):
    message = await _open(session, "Help please", tenant=tenant, product=product)
    fake = FakeLLM(tool_script=[("lookup_transaction", {"reference": "TX-5001"})])
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, message.issue_id)
    assert suggestion is not None and fake.calls[0]["tools"] is None and fake.tool_results == []
    run = await session.get(AIRun, suggestion.ai_run_id)
    event = next(d for k, d in await _events(session, run.id) if k == "tools_unavailable")
    assert reason in event["reason"]


async def test_a_message_with_no_tenant_or_product_gets_no_tools(session):
    event = conversio_event("Plain message", thread_id="plain")
    event.context = None
    message = await event_bus._handle_event(session, event)
    ai_llm.set_client(FakeLLM())
    suggestion = await worker.process_issue(session, message.issue_id)
    run = await session.get(AIRun, suggestion.ai_run_id)
    assert any(k == "tools_unavailable" for k, _ in await _events(session, run.id))


async def test_a_broken_tool_server_degrades_to_no_tools(session):
    broken = ServerConfig("x", "finsaas-lending", "inprocess", "no_such_module:server", ("t",))
    worker.set_gateway(ToolGateway({"finsaas-lending": broken}, {"commsworth": ("finsaas-lending",)}))
    try:
        message = await _open(session, "Where is my money?")
        fake = FakeLLM()
        ai_llm.set_client(fake)
        suggestion = await worker.process_issue(session, message.issue_id)
    finally:
        worker.set_gateway(None)
    assert suggestion is not None and fake.calls[0]["tools"] is None
    run = await session.get(AIRun, suggestion.ai_run_id)
    assert any(k == "tools_unavailable" and "unavailable" in d["reason"] for k, d in await _events(session, run.id))


# ---- the dashboard sees it ---------------------------------------------------------------------------------------

async def test_dashboard_snapshot_lists_the_tools_used(session):
    message = await _open(session, "Where is my money?")
    ai_llm.set_client(FakeLLM(tool_script=[LENDING_SCRIPT[1], ("refund_payment", {"amount": 1})]))
    await worker.process_issue(session, message.issue_id)
    snapshot = await ws_manager.build_snapshot(AsyncSessionLocal)
    tools = next(i for i in snapshot["issues"] if i["id"] == message.issue_id)["ai"]["tools"]
    assert tools == [{"tool": "get_disbursement_status", "status": "ok"}, {"tool": "refund_payment", "status": "denied"}]


# ---- the model client's tool loop (SDK mocked: no network, no key) ----------------------------------------------

def _block(type_, **kw):
    return SimpleNamespace(type=type_, **kw)


def _response(stop_reason, content, input_tokens=100, output_tokens=10):
    return SimpleNamespace(
        stop_reason=stop_reason, content=content, model="claude-test",
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _ScriptedSDK:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(dict(kwargs, messages=[dict(m) for m in kwargs["messages"]]))
        return self.responses.pop(0)


def _llm(sdk):
    llm = AnthropicLLM("key", "claude-test", 1000)
    llm._client = sdk
    return llm


TOOLS = [{"name": "get_x", "description": "d", "input_schema": {"type": "object", "properties": {}}}]


async def test_the_tool_loop_runs_the_tool_returns_results_and_sums_tokens():
    thinking = _block("thinking", thinking="", signature="sig")
    sdk = _ScriptedSDK([
        _response("tool_use", [thinking, _block("tool_use", id="tu_1", name="get_x", input={"a": "[ACCOUNT_1]"})], 100, 10),
        _response("end_turn", [_block("text", text='{"ok": true}')], 150, 20),
    ])
    seen = []

    async def execute(name, arguments):
        seen.append((name, arguments))
        return "tool says hi", False

    result = await _llm(sdk).complete(system="s", user="u", schema={}, tools=TOOLS, execute_tool=execute)

    assert seen == [("get_x", {"a": "[ACCOUNT_1]"})]
    assert result.text == '{"ok": true}' and result.tool_rounds == 1
    assert (result.input_tokens, result.output_tokens) == (250, 30)
    first, second = sdk.requests
    assert first["tools"] == TOOLS and "tool_choice" not in first  # no forced tool use
    assistant, tool_turn = second["messages"][1], second["messages"][2]
    assert assistant["role"] == "assistant" and assistant["content"][0].type == "thinking"  # thinking blocks go back as received
    assert tool_turn == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "tool says hi", "is_error": False}],
    }


async def test_parallel_tool_calls_come_back_in_one_user_message():
    sdk = _ScriptedSDK([
        _response("tool_use", [
            _block("tool_use", id="a", name="get_x", input={}), _block("tool_use", id="b", name="get_x", input={"n": 2}),
        ]),
        _response("end_turn", [_block("text", text="{}")]),
    ])

    async def execute(name, arguments):
        return "r", name != "get_x"

    await _llm(sdk).complete(system="s", user="u", schema={}, tools=TOOLS, execute_tool=execute)
    results = sdk.requests[1]["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


async def test_without_tools_there_is_one_plain_request():
    sdk = _ScriptedSDK([_response("end_turn", [_block("text", text="{}")])])
    result = await _llm(sdk).complete(system="s", user="u", schema={})
    assert len(sdk.requests) == 1 and "tools" not in sdk.requests[0] and result.tool_rounds == 0


async def test_a_model_that_never_stops_asking_for_tools_is_cut_off():
    loop = [_response("tool_use", [_block("tool_use", id=f"t{i}", name="get_x", input={})]) for i in range(ai_llm.MAX_TOOL_ROUNDS)]
    sdk = _ScriptedSDK(loop + [_response("end_turn", [_block("text", text="{}")])])

    async def execute(name, arguments):
        return "r", False

    result = await _llm(sdk).complete(system="s", user="u", schema={}, tools=TOOLS, execute_tool=execute)
    assert result.tool_rounds == ai_llm.MAX_TOOL_ROUNDS
    assert sdk.requests[-1]["tool_choice"] == {"type": "none"}  # the last turn must answer, not call another tool
    assert all("tool_choice" not in r for r in sdk.requests[:-1])


async def test_refusals_and_truncation_still_raise():
    for stop, text in (("refusal", "declined"), ("max_tokens", "cut off")):
        sdk = _ScriptedSDK([_response(stop, [])])
        with pytest.raises(ai_llm.LLMError, match=text):
            await _llm(sdk).complete(system="s", user="u", schema={}, tools=TOOLS, execute_tool=lambda n, a: None)
