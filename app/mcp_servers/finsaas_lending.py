"""MOCK FinSaaS Lending MCP server. Fake data, read-only. See app/mcp_servers/__init__.py."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("finsaas-lending (MOCK)")

# Fake loans. Results deliberately include full account numbers, emails and phones, so the gateway's masking of tool
# RESULTS is exercised: the model must only ever see placeholders for those.
LOANS = {
    "LN-1001": {
        "loan_reference": "LN-1001",
        "status": "queued_for_bank_verification",
        "approved_on": "2026-10-06",
        "amount": 250000.0,
        "currency": "NGN",
        "destination_bank": "Northwind Bank",
        "destination_account_number": "0123456789",
        "destination_account_last4": "6789",
        "expected_by": "2026-10-12",
        "note": "Disbursement is held until the destination account name is verified with the bank.",
        "borrower_name": "Ada Okafor",
        "borrower_email": "ada.okafor@example.com",
        "borrower_phone": "+234 802 555 0147",
    },
    "LN-1002": {
        "loan_reference": "LN-1002",
        "status": "disbursed",
        "approved_on": "2026-09-01",
        "disbursed_on": "2026-09-02",
        "amount": 100000.0,
        "currency": "NGN",
        "destination_bank": "Harbour Bank",
        "destination_account_number": "0987654321",
        "destination_account_last4": "4321",
        "note": "Funds were credited on the disbursement date.",
        "borrower_name": "Tunde Bello",
        "borrower_email": "tunde.bello@example.com",
        "borrower_phone": "+234 803 555 0192",
    },
}
BY_ACCOUNT = {"0123456789": ["LN-1001"], "0987654321": ["LN-1002"]}
SCHEDULES = {
    "LN-1001": [{"instalment": 1, "due": "2026-11-06", "amount": 22000.0}, {"instalment": 2, "due": "2026-12-06", "amount": 22000.0}],
    "LN-1002": [{"instalment": 1, "due": "2026-10-02", "amount": 9500.0, "status": "paid"}, {"instalment": 2, "due": "2026-11-02", "amount": 9500.0}],
}


def _loan(loan_reference: str) -> dict:
    loan = LOANS.get(loan_reference.strip().upper())
    if loan is None:
        raise ValueError(f"loan {loan_reference!r} was not found")
    return loan


@server.tool()
def find_loans_by_account(account_number: str) -> dict:
    """MOCK. List the loans whose destination account is this bank account number (read-only)."""
    refs = BY_ACCOUNT.get(account_number.strip(), [])
    return {
        "account_last4": account_number.strip()[-4:],
        "loans": [{"loan_reference": r, "status": LOANS[r]["status"], "approved_on": LOANS[r]["approved_on"]} for r in refs],
    }


@server.tool()
def get_disbursement_status(loan_reference: str) -> dict:
    """MOCK. Disbursement status of one loan by its loan reference, e.g. LN-1001 (read-only)."""
    return _loan(loan_reference)


@server.tool()
def get_repayment_schedule(loan_reference: str) -> dict:
    """MOCK. Repayment schedule of one loan by its loan reference (read-only)."""
    _loan(loan_reference)
    return {"loan_reference": loan_reference.strip().upper(), "instalments": SCHEDULES[loan_reference.strip().upper()]}
