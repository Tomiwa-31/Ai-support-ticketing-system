"""MOCK FinSaaS MCP server. Fake data, read-only. See app/mcp_servers/__init__.py."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("finsaas (MOCK)")

INVOICES = {
    "INV-2001": {"invoice_id": "INV-2001", "status": "paid", "amount": 120000.0, "currency": "NGN", "issued_on": "2026-09-30", "paid_on": "2026-10-02", "billing_contact": "billing@northwind.example"},
    "INV-2002": {"invoice_id": "INV-2002", "status": "overdue", "amount": 120000.0, "currency": "NGN", "issued_on": "2026-10-01", "due_on": "2026-10-08", "billing_contact": "billing@northwind.example"},
}
WEBHOOKS = {
    "ep-77": [
        {"delivery": "d-3", "status_code": 500, "response_ms": 840, "at": "2026-10-12T09:15:00Z"},
        {"delivery": "d-2", "status_code": 500, "response_ms": 910, "at": "2026-10-12T08:15:00Z"},
        {"delivery": "d-1", "status_code": 200, "response_ms": 120, "at": "2026-10-11T22:00:00Z"},
    ]
}
TEAMS = {
    "acct-9": [
        {"name": "Ada Okafor", "email": "ada.okafor@example.com", "role": "Owner"},
        {"name": "Tunde Bello", "email": "tunde.bello@example.com", "role": "Member"},
    ]
}


@server.tool()
def get_invoice_status(invoice_id: str) -> dict:
    """MOCK. Status of one invoice by its id, e.g. INV-2001 (read-only)."""
    invoice = INVOICES.get(invoice_id.strip().upper())
    if invoice is None:
        raise ValueError(f"invoice {invoice_id!r} was not found")
    return invoice


@server.tool()
def get_webhook_deliveries(endpoint_id: str, limit: int = 5) -> dict:
    """MOCK. Recent webhook delivery attempts for an endpoint id, newest first (read-only)."""
    rows = WEBHOOKS.get(endpoint_id.strip())
    if rows is None:
        raise ValueError(f"endpoint {endpoint_id!r} was not found")
    return {"endpoint_id": endpoint_id.strip(), "deliveries": rows[: max(1, min(limit, 10))]}


@server.tool()
def list_team_members(account_id: str) -> dict:
    """MOCK. The team members and roles on a FinSaaS account id (read-only)."""
    members = TEAMS.get(account_id.strip())
    if members is None:
        raise ValueError(f"account {account_id!r} was not found")
    return {"account_id": account_id.strip(), "members": members}
