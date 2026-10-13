"""DEMO knowledge articles. Everything below is invented for the demo (timelines, hours, limits): it is not real
Credipay / FinSaaS / FinSaaS Lending policy. Replace it with approved documentation before any real use.
Products use the same ids as the Conversio chat dropdown; "all" applies to every product."""

SOURCE = "demo-sample"

SAMPLES: list[dict[str, str]] = [
    {
        "product": "credipay",
        "title": "Duplicate or double charges",
        "body": (
            "If a customer was charged twice for the same payment, the second charge is normally an authorisation "
            "hold that is released automatically. Held amounts return to the customer's account within 3 to 5 "
            "working days, depending on the customer's bank.\n\n"
            "Ask the customer for the transaction reference and the date of the payment. Never ask for a full card "
            "number, PIN or one-time code. If the duplicate has not been released after 5 working days, escalate to "
            "the payments team with the transaction reference so a manual reversal can be raised."
        ),
    },
    {
        "product": "credipay",
        "title": "Transfer failed but the account was debited",
        "body": (
            "When a transfer fails after the customer's account has been debited, the amount is reversed "
            "automatically, usually within 24 hours and at most within 3 working days.\n\n"
            "Tell the customer to wait for the automatic reversal first. If it has not arrived after 3 working days, "
            "collect the transaction reference, the amount, the date and the receiving bank, and escalate to the "
            "payments team."
        ),
    },
    {
        "product": "credipay",
        "title": "Resetting a password or unlocking an account",
        "body": (
            "Customers can reset their password from the sign-in page with the Forgot password link. A reset link "
            "is emailed to the address on the account and expires after 30 minutes.\n\n"
            "After 5 failed sign-in attempts the account is locked for 30 minutes and unlocks by itself. Support "
            "can never see or set a customer's password, and must never ask for it or for a one-time code."
        ),
    },
    {
        "product": "finsaas",
        "title": "Exporting invoices and statements",
        "body": (
            "Invoices and statements can be exported as CSV or PDF from the Billing page: choose a date range, pick "
            "the format and select Export.\n\n"
            "Exports covering more than 10,000 rows are prepared in the background and emailed to the account "
            "owner as a download link that stays valid for 24 hours. If an export is missing after an hour, ask the "
            "customer to check the spam folder and then escalate."
        ),
    },
    {
        "product": "finsaas",
        "title": "Webhook deliveries failing",
        "body": (
            "A webhook delivery counts as failed unless the customer's endpoint answers with a 2xx status within "
            "10 seconds. Failed deliveries are retried up to 6 times over 24 hours, with growing delays.\n\n"
            "Ask the customer to confirm the endpoint URL is public and uses HTTPS, that it returns 2xx quickly, and "
            "that it verifies the signature header with the current signing secret. The delivery log on the "
            "Developers page shows the status code and response time of each attempt."
        ),
    },
    {
        "product": "finsaas",
        "title": "Adding or removing team members",
        "body": (
            "Account owners and admins can invite team members from Settings, Team. Invitations expire after 7 "
            "days. Roles are Owner, Admin and Member; only Owners can change billing details or remove an Admin.\n\n"
            "Removing a member revokes their access immediately. Support can only change team members after the "
            "account owner confirms the request from the email address on the account."
        ),
    },
    {
        "product": "finsaas-lending",
        "title": "Loan disbursement delays",
        "body": (
            "Approved loans are normally disbursed within 1 business day. Requests approved after 4pm, or on a "
            "weekend or public holiday, are disbursed on the next business day.\n\n"
            "A disbursement can also be held while the borrower's bank details are verified. If a borrower reports "
            "that money has not arrived, confirm the approval date and the account the loan was sent to. If more "
            "than 2 business days have passed since approval, escalate to the lending operations team with the loan "
            "reference."
        ),
    },
    {
        "product": "finsaas-lending",
        "title": "Changing a repayment date or schedule",
        "body": (
            "A borrower can ask to move a repayment date at least 5 days before it falls due. The request is "
            "reviewed by the lending team and the borrower is told the outcome by email.\n\n"
            "A date change can add a rescheduling fee, so support should not promise one. Collect the loan "
            "reference, the instalment concerned and the preferred new date, then pass the request to the lending "
            "team."
        ),
    },
    {
        "product": "finsaas-lending",
        "title": "Early repayment and settlement figures",
        "body": (
            "Borrowers can repay a loan early. A settlement figure shows the outstanding principal and any accrued "
            "interest up to the settlement date and is valid for 3 days.\n\n"
            "Support can request a settlement figure for a verified borrower through the lending team. Do not quote "
            "a figure from memory: it changes daily."
        ),
    },
    {
        "product": "all",
        "title": "Support hours and when to escalate",
        "body": (
            "Support is available on weekdays from 8am to 6pm. Issues outside those hours are answered the next "
            "working day.\n\n"
            "Escalate immediately, whatever the time, when a customer reports unauthorised transactions, a possible "
            "account takeover or the loss of funds. Never ask a customer for a full card number, PIN, password or "
            "one-time code."
        ),
    },
]
