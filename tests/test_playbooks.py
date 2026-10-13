"""Per-product playbooks: operator-written procedures added to the prompt when (and only when) that product's tools
are offered."""
import re
from datetime import date

from sqlalchemy import select

from app.ai import llm as ai_llm
from app.ai import worker
from app.ai.schemas import ACTIONS
from app.core import event_bus
from app.mcp_gateway import registry
from app.models import AIRun, AIRunEvent
from tests.fakes import FakeLLM
from tests.helpers import conversio_event


async def _message(session, text, product="finsaas-lending", tenant="commsworth", thread="pb-1"):
    event = conversio_event(text, thread_id=thread)
    event.context = {"tenant_id": tenant, "product": product, "customer_ref": "u", "correlation_id": "c-1"}
    return await event_bus._handle_event(session, event)


def test_every_product_has_a_playbook_that_only_names_its_own_allowlisted_tools():
    for product, config in registry.SERVERS.items():
        assert config.playbook.strip(), f"{product} has no playbook"
        named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", config.playbook))
        unknown = named - set(config.allowed_tools) - set(ACTIONS)
        assert not unknown, f"{product} playbook names tools it cannot use: {unknown}"
        assert named & set(config.allowed_tools), f"{product} playbook never mentions a tool"


def test_the_lending_playbook_states_the_order_the_user_asked_for():
    steps = registry.SERVERS["finsaas-lending"].playbook
    assert steps.index("find_loans_by_account") < steps.index("get_disbursement_status")
    assert "2 business days" in steps and "do not call a tool" in steps


def test_compose_system_prompt_only_adds_a_playbook_when_there_is_one():
    assert worker.compose_system_prompt("", "x") == worker.SYSTEM_PROMPT
    assert worker.compose_system_prompt(None, "x") == worker.SYSTEM_PROMPT
    composed = worker.compose_system_prompt("1. do a thing", "credipay")
    assert composed.startswith(worker.SYSTEM_PROMPT) and "Procedure for credipay" in composed and "1. do a thing" in composed


async def test_the_product_playbook_reaches_the_model_and_the_stored_prompt(session):
    message = await _message(session, "Where is my loan money?")
    fake = FakeLLM()
    ai_llm.set_client(fake)
    suggestion = await worker.process_issue(session, message.issue_id)

    system = fake.calls[0]["system"]
    assert "Procedure for finsaas-lending" in system and "call find_loans_by_account first" in system
    assert "lookup_transaction" not in system  # another product's playbook is not mixed in
    run = await session.get(AIRun, suggestion.ai_run_id)
    assert "Procedure for finsaas-lending" in run.masked_prompt  # what is stored is exactly what was sent
    offered = await session.scalar(
        select(AIRunEvent.detail).where(AIRunEvent.ai_run_id == run.id, AIRunEvent.event_type == "tools_offered")
    )
    assert '"playbook": true' in offered


async def test_each_product_gets_its_own_playbook(session):
    message = await _message(session, "A payment problem", product="credipay")
    fake = FakeLLM()
    ai_llm.set_client(fake)
    await worker.process_issue(session, message.issue_id)
    system = fake.calls[0]["system"]
    assert "Procedure for credipay" in system and "call lookup_transaction first" in system
    assert "find_loans_by_account" not in system


async def test_no_tools_means_no_playbook(session):
    # A tenant that is not mapped to the product gets no tools, so a procedure about tools would only confuse the model.
    message = await _message(session, "Where is my loan money?", tenant="stranger")
    fake = FakeLLM()
    ai_llm.set_client(fake)
    await worker.process_issue(session, message.issue_id)
    assert "Procedure for" not in fake.calls[0]["system"] and fake.calls[0]["system"] == worker.SYSTEM_PROMPT


async def test_todays_date_is_in_the_ticket_so_a_business_day_rule_can_be_applied(session):
    message = await _message(session, "Where is my loan money?")
    fake = FakeLLM()
    ai_llm.set_client(fake)
    await worker.process_issue(session, message.issue_id)
    assert f"Today (UTC): {date.today().isoformat()}" in fake.calls[0]["user"]
