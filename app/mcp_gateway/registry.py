"""The tool registry: WHICH MCP servers exist, which tools of each the model may use, and which tenant may use which
product. This file is configuration. Swapping a mock for the real server is an edit here (transport "http" + its URL).

Rules the gateway enforces from this file:
- only tools in `allowed_tools` are ever offered to the model or callable, even if the server offers more;
- write tools are simply not listed: they are never registered, so the model can neither see nor call them;
- a tenant may only reach the products listed for it in TENANT_PRODUCTS.
"""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ServerConfig:
    name: str
    product: str  # same ids as the Conversio chat dropdown / IssueContext.product
    transport: Literal["inprocess", "http"]
    target: str  # inprocess: "module:attribute" of a FastMCP object; http: the streamable-HTTP endpoint URL
    allowed_tools: tuple[str, ...]  # the allowlist: read-only tools only
    auth_env: str | None = None  # http: name of the environment variable holding a bearer token (never the token itself)
    # The playbook: an operator-written procedure for this product, added to the prompt whenever this product's
    # tools are offered. It states the ORDER to use the tools in. It is guidance the model follows very reliably, not
    # a hard guarantee: a step that must never be skipped has to be enforced in code instead.
    playbook: str = ""


CREDIPAY_PLAYBOOK = """\
1. If the customer gives a transaction reference (like TX-1234), call lookup_transaction first.
2. If they give an account number but no reference, call list_recent_transactions to find the transaction.
3. For sign-in or locked-account problems, call get_account_status before suggesting anything.
4. If the customer gives neither a reference nor an account number, do not call a tool: ask for the transaction reference.
5. Use only what the tool result shows. If a payment is a hold or a reversal is pending, say so and give the timeline from the
   knowledge articles. If the transaction cannot be found, say so and ask for the reference; never guess.
"""

FINSAAS_PLAYBOOK = """\
1. For invoice questions, call get_invoice_status with the invoice id (like INV-1234).
2. For webhook problems, call get_webhook_deliveries with the endpoint id (like ep-12) and read the status codes before replying.
3. For questions about who is on the account or what roles they have, call list_team_members with the account id.
4. If the identifier the tool needs is missing, do not call a tool: ask the customer for it.
5. Use only what the tool result shows; never guess.
"""

FINSAAS_LENDING_PLAYBOOK = """\
1. If the customer gives a bank account number and no loan reference, call find_loans_by_account first to get their loan reference(s).
2. For each relevant loan reference (given by the customer or found in step 1), call get_disbursement_status.
3. For questions about instalments or due dates, call get_repayment_schedule instead.
4. If a loan is approved but not yet disbursed and the approval date is more than 2 business days before today's date (shown in
   the ticket; count Monday to Friday), recommend escalate. Within 2 business days, explain the normal timeline from the knowledge
   articles and recommend reply_only or request_more_info.
5. If the customer gives neither an account number nor a loan reference, do not call a tool: ask for the loan reference or account number.
6. Use only what the tool results show. Refer to the destination account by its last four digits.
"""

SERVERS: dict[str, ServerConfig] = {
    "credipay": ServerConfig(
        name="credipay", product="credipay", transport="inprocess", target="app.mcp_servers.credipay:server",
        allowed_tools=("lookup_transaction", "list_recent_transactions", "get_account_status"),
        playbook=CREDIPAY_PLAYBOOK,
    ),
    "finsaas": ServerConfig(
        name="finsaas", product="finsaas", transport="inprocess", target="app.mcp_servers.finsaas:server",
        allowed_tools=("get_invoice_status", "get_webhook_deliveries", "list_team_members"),
        playbook=FINSAAS_PLAYBOOK,
    ),
    "finsaas-lending": ServerConfig(
        name="finsaas-lending", product="finsaas-lending", transport="inprocess",
        target="app.mcp_servers.finsaas_lending:server",
        allowed_tools=("find_loans_by_account", "get_disbursement_status", "get_repayment_schedule"),
        playbook=FINSAAS_LENDING_PLAYBOOK,
    ),
}

# Which products each tenant may use. v1 is single-tenant, so the demo tenant gets all three.
TENANT_PRODUCTS: dict[str, tuple[str, ...]] = {
    "commsworth": ("credipay", "finsaas", "finsaas-lending"),
}
