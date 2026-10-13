"""The tool gateway: allowlist, tenant mapping, placeholder substitution, masking of results, budget, timeouts."""
import threading
import time

import pytest
import uvicorn

from app.ai.masking import Masker
from app.mcp_gateway import registry
from app.mcp_gateway.gateway import ToolGateway, ToolsUnavailable, resolve_arguments
from app.mcp_gateway.registry import ServerConfig
from tests import stub_servers

STUB = ServerConfig(
    name="stub", product="stubproduct", transport="inprocess", target="tests.stub_servers:stub",
    allowed_tools=("echo", "slow", "boom", "big", "reveal"),  # refund_payment is NOT allowlisted
)


def gateway(**kw):
    return ToolGateway({"stubproduct": STUB}, {"acme": ("stubproduct",)}, **kw)


@pytest.fixture(autouse=True)
def _reset_executions():
    stub_servers.executions.clear()


# ---- the real registry ------------------------------------------------------------------------------------------

async def test_every_allowlisted_tool_exists_on_its_mock_server_and_nothing_else_is_exposed():
    gw = ToolGateway()
    for product, config in registry.SERVERS.items():
        async with gw.open("commsworth", product) as session:
            assert sorted(session.tools) == sorted(config.allowed_tools)
            assert session.missing == [] and session.blocked == []


async def test_mock_servers_have_no_write_tools():
    write_words = ("create", "update", "delete", "refund", "transfer", "send", "set_", "cancel", "approve", "write", "close")
    gw = ToolGateway()
    for product in registry.SERVERS:
        async with gw.open("commsworth", product) as session:
            offered = {t.name for t in (await session.client.list_tools()).tools}
            assert offered and not [n for n in offered if any(w in n for w in write_words)], offered
            assert all("read-only" in (t.description or "") for t in session.tools.values())


async def test_tool_definitions_have_the_shape_the_model_api_expects():
    async with ToolGateway().open("commsworth", "finsaas-lending") as session:
        for definition in session.definitions():
            assert set(definition) == {"name", "description", "input_schema"}
            assert definition["input_schema"]["type"] == "object" and definition["description"].startswith("MOCK")


# ---- tenant / product mapping -----------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tenant, product, reason",
    [
        (None, "credipay", "no tenant or product"),
        ("commsworth", None, "no tenant or product"),
        ("stranger", "credipay", "not mapped"),
        ("commsworth", "nonexistent", "not mapped"),
    ],
)
async def test_tenant_must_be_mapped_to_the_product(tenant, product, reason):
    with pytest.raises(ToolsUnavailable, match=reason):
        async with ToolGateway().open(tenant, product):
            pass


async def test_a_mapped_product_with_no_server_is_unavailable():
    gw = ToolGateway({}, {"acme": ("ghost",)})
    with pytest.raises(ToolsUnavailable, match="no tool server is registered"):
        async with gw.open("acme", "ghost"):
            pass


async def test_unreachable_server_is_unavailable_but_errors_in_the_body_are_not_swallowed():
    broken = ServerConfig("x", "p", "inprocess", "no_such_module:server", ("t",))
    with pytest.raises(ToolsUnavailable, match="unavailable"):
        async with ToolGateway({"p": broken}, {"acme": ("p",)}).open("acme", "p"):
            pass
    with pytest.raises(ValueError, match="mine"):
        async with gateway().open("acme", "stubproduct"):
            raise ValueError("mine")  # a bug in the caller must surface as itself


# ---- the allowlist ----------------------------------------------------------------------------------------------

async def test_a_tool_the_server_offers_but_the_allowlist_omits_is_invisible_and_uncallable():
    async with gateway().open("acme", "stubproduct") as session:
        assert "refund_payment" in session.blocked
        assert "refund_payment" not in {d["name"] for d in session.definitions()}
        outcome = await session.call("refund_payment", {"amount": 10}, Masker())
        assert outcome.denied and outcome.is_error and "not available" in outcome.text
    assert "refund_payment" not in stub_servers.executions  # it never reached the server


async def test_unknown_tool_names_are_denied():
    async with gateway().open("acme", "stubproduct") as session:
        assert (await session.call("drop_everything", {}, Masker())).denied


# ---- placeholders and masking -----------------------------------------------------------------------------------

def test_resolve_arguments_swaps_email_phone_and_account_but_never_cards():
    mapping = {"[ACCOUNT_1]": "0123456789", "[EMAIL_1]": "a@b.com", "[PHONE_1]": "+234 1", "[CARD_1]": "4111111111111111"}
    resolved, problem = resolve_arguments({"a": "[ACCOUNT_1]", "n": {"e": ["[EMAIL_1]", "x [PHONE_1] y"]}, "i": 3}, mapping)
    assert problem is None
    assert resolved == {"a": "0123456789", "n": {"e": ["a@b.com", "x +234 1 y"]}, "i": 3}
    _, problem = resolve_arguments({"c": "[CARD_1]"}, mapping)
    assert "card numbers are never sent to tools" in problem
    resolved, problem = resolve_arguments({"a": "[ACCOUNT_9]"}, mapping)  # unknown placeholder: left as written
    assert resolved == {"a": "[ACCOUNT_9]"} and problem is None


async def test_the_tool_receives_the_real_value_but_the_model_only_ever_sees_the_placeholder():
    masker = Masker()
    masker.mask("my account is 0123456789")  # -> [ACCOUNT_1]
    async with gateway().open("acme", "stubproduct") as session:
        outcome = await session.call("echo", {"text": "[ACCOUNT_1]"}, masker)
    assert not outcome.denied and not outcome.is_error
    assert "0123456789" not in outcome.text and "[ACCOUNT_1]" in outcome.text  # the result is masked on the way back
    assert outcome.detail["arguments"] == {"text": "[ACCOUNT_1]"}
    assert "0123456789" not in str(outcome.detail)


async def test_the_tool_really_got_the_resolved_value():
    masker = Masker()
    masker.mask("acct 0123456789")
    async with ToolGateway().open("commsworth", "finsaas-lending") as session:
        outcome = await session.call("find_loans_by_account", {"account_number": "[ACCOUNT_1]"}, masker)
    assert "LN-1001" in outcome.text  # only possible if the real number was substituted before the call


async def test_a_card_placeholder_is_refused_and_the_tool_is_not_called():
    masker = Masker()
    masker.mask("card 4111 1111 1111 1111")  # -> [CARD_1]
    async with gateway().open("acme", "stubproduct") as session:
        outcome = await session.call("echo", {"text": "[CARD_1]"}, masker)
    assert outcome.denied and "card numbers are never sent to tools" in outcome.text
    assert stub_servers.executions == []


async def test_results_are_masked_before_the_model_sees_them():
    masker = Masker()
    async with gateway().open("acme", "stubproduct") as session:
        outcome = await session.call("reveal", {}, masker)
    for raw in ("jamie@acme.com", "234 802", "0123456789"):
        assert raw not in outcome.text and raw not in str(outcome.detail)
    assert "[EMAIL_1]" in outcome.text and "[PHONE_1]" in outcome.text and "[ACCOUNT_1]" in outcome.text
    assert "last4 6789" in outcome.text  # four digits are not sensitive and stay readable


async def test_the_same_value_gets_the_same_placeholder_across_calls():
    masker = Masker()
    masker.mask("my account is 0123456789")
    async with ToolGateway().open("commsworth", "finsaas-lending") as session:
        out = await session.call("get_disbursement_status", {"loan_reference": "LN-1001"}, masker)
    assert '"destination_account_number": "[ACCOUNT_1]"' in out.text  # same token the customer's message got


async def test_arguments_are_masked_in_the_log_even_if_the_model_typed_a_raw_value():
    masker = Masker()
    async with gateway().open("acme", "stubproduct") as session:
        outcome = await session.call("echo", {"text": "jamie@acme.com"}, masker)
    assert "jamie@acme.com" not in str(outcome.detail["arguments"])


# ---- limits and failures ----------------------------------------------------------------------------------------

async def test_call_budget_is_enforced():
    async with gateway(max_calls=2).open("acme", "stubproduct") as session:
        results = [await session.call("echo", {"text": str(i)}, Masker()) for i in range(3)]
    assert [r.denied for r in results] == [False, False, True]
    assert "limit (2)" in results[2].text and stub_servers.executions.count("echo") == 2


async def test_a_slow_tool_times_out_without_breaking_anything():
    async with gateway(timeout_seconds=0.1).open("acme", "stubproduct") as session:
        outcome = await session.call("slow", {}, Masker())
    assert outcome.is_error and not outcome.denied and "did not answer" in outcome.text


async def test_a_failing_tool_comes_back_as_an_error_result():
    async with gateway().open("acme", "stubproduct") as session:
        outcome = await session.call("boom", {}, Masker())
    assert outcome.is_error and outcome.text.startswith("Error:") and "kaboom" in outcome.text


async def test_missing_required_arguments_are_an_error_result_not_a_crash():
    async with gateway().open("acme", "stubproduct") as session:
        outcome = await session.call("echo", {}, Masker())
    assert outcome.is_error and "Error:" in outcome.text


async def test_very_long_results_are_truncated():
    async with gateway().open("acme", "stubproduct") as session:
        outcome = await session.call("big", {}, Masker())
    assert len(outcome.text) < 4100 and outcome.text.endswith("[truncated]")


# ---- the real-server path: streamable HTTP ----------------------------------------------------------------------

async def test_the_http_transport_works_against_a_real_server_over_the_network():
    """Swapping a mock for a real server is a registry change. Prove the http path with a real MCP server on a port."""
    from app.mcp_servers import finsaas

    finsaas.server.settings.port = 0
    app = finsaas.server.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started and server.servers and server.servers[0].sockets:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        remote = ServerConfig(
            "remote-finsaas", "finsaas", "http", f"http://127.0.0.1:{port}/mcp", ("get_invoice_status", "list_team_members")
        )
        async with ToolGateway({"finsaas": remote}, {"acme": ("finsaas",)}).open("acme", "finsaas") as session:
            assert sorted(session.tools) == ["get_invoice_status", "list_team_members"]
            assert session.blocked == ["get_webhook_deliveries"]  # offered by the server, not allowlisted
            outcome = await session.call("get_invoice_status", {"invoice_id": "INV-2002"}, Masker())
            assert not outcome.is_error and "overdue" in outcome.text
            assert "billing@northwind.example" not in outcome.text  # masked on the way back, over HTTP too
            assert (await session.call("get_webhook_deliveries", {"endpoint_id": "ep-77"}, Masker())).denied
    finally:
        server.should_exit = True
        thread.join(timeout=5)
