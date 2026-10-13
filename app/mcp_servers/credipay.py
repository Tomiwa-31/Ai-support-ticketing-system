"""MOCK Credipay MCP server. Fake data, read-only. See app/mcp_servers/__init__.py."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("credipay (MOCK)")

TRANSACTIONS = {
    "TX-5001": {
        "reference": "TX-5001",
        "type": "card_payment",
        "amount": 15000.0,
        "currency": "NGN",
        "status": "authorisation_hold",
        "created_on": "2026-10-08",
        "note": "A second authorisation hold for the same payment; it is released automatically within 3 to 5 working days.",
        "account_number": "0123456789",
        "customer_email": "ada.okafor@example.com",
    },
    "TX-5002": {
        "reference": "TX-5002",
        "type": "transfer",
        "amount": 40000.0,
        "currency": "NGN",
        "status": "failed_reversal_pending",
        "created_on": "2026-10-09",
        "note": "Transfer failed after the account was debited; the automatic reversal is queued.",
        "account_number": "0123456789",
        "customer_email": "ada.okafor@example.com",
    },
    "TX-5003": {
        "reference": "TX-5003",
        "type": "transfer",
        "amount": 5000.0,
        "currency": "NGN",
        "status": "completed",
        "created_on": "2026-10-05",
        "note": "Completed.",
        "account_number": "0987654321",
        "customer_email": "tunde.bello@example.com",
    },
}
ACCOUNTS = {
    "0123456789": {"account_last4": "6789", "status": "active", "holder_email": "ada.okafor@example.com", "holder_phone": "+234 802 555 0147"},
    "0987654321": {
        "account_last4": "4321", "status": "locked", "locked_until": "2026-10-10T18:00:00Z", "failed_sign_ins": 5,
        "holder_email": "tunde.bello@example.com", "holder_phone": "+234 803 555 0192",
    },
}


@server.tool()
def lookup_transaction(reference: str) -> dict:
    """MOCK. Look up one transaction by its reference, e.g. TX-5001 (read-only)."""
    tx = TRANSACTIONS.get(reference.strip().upper())
    if tx is None:
        raise ValueError(f"transaction {reference!r} was not found")
    return tx


@server.tool()
def list_recent_transactions(account_number: str, limit: int = 5) -> dict:
    """MOCK. The most recent transactions on an account number, newest first (read-only)."""
    rows = [t for t in TRANSACTIONS.values() if t["account_number"] == account_number.strip()]
    rows.sort(key=lambda t: t["created_on"], reverse=True)
    return {"account_last4": account_number.strip()[-4:], "transactions": rows[: max(1, min(limit, 10))]}


@server.tool()
def get_account_status(account_number: str) -> dict:
    """MOCK. Status of a Credipay account by account number: active or locked (read-only)."""
    account = ACCOUNTS.get(account_number.strip())
    if account is None:
        raise ValueError("account was not found")
    return account
