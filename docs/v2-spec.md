# v2 spec: AI layer demo (one page)

**Goal.** Demonstrate how Claude + RAG + MCP interface with the v1 ticketing engine, with production-shaped seams
(adapter contract, tool registry, approval API, audit schema). It is a demo, not the production system. Decisions:
[v2-context.md](v2-context.md). Design: [../ARCHITECTURE.md](../ARCHITECTURE.md).

## Acceptance test: the demo script
A customer opens the Conversio simulator chat and asks something that needs both knowledge and product data.

1. Customer message (containing a card number and email) arrives via the Conversio adapter with tenant, user, product and correlation id. An issue opens; status, SLA and triggers behave exactly as in v1.
2. A trigger fires `request_ai_assist`. The dashboard shows an AI run in progress.
3. The prompt sent to Claude contains masked tokens, not the card number or email (visible in the run's audit record).
4. Claude returns validated JSON: category, priority, summary, duplicate candidates, draft reply, recommended action, and cites the knowledge articles it used.
5. The draft calls a read-only mock Credipay tool; the tool call and result appear in the audit record. A write tool is not callable (not registered).
6. The agent sees the suggestion as **pending**. Nothing reached the customer. The agent edits and approves; the reply is added through `issue_service.add_message` as a human write and delivered back to the chat; status flips to On Customer.
7. A rejected suggestion leaves the thread and status untouched and is recorded as rejected.
8. The audit record for the run shows: model, masked prompt, knowledge sources, tool calls, result, approval, outcome, tokens, latency, cost; linked by correlation id.
9. The dashboard shows volumes, categories, ageing, escalations, AI usage, latency, cost and outcome.
10. A confirmed resolution produces a **draft** knowledge article, which becomes searchable only after review and publish.

Every step is repeatable by running the demo script and by automated tests where the step is deterministic (masking, tool allowlist, approval gate, validation, audit rows).

## In scope (by slice)
0 Housekeeping · 1 Conversio chat -> masking -> Claude -> approval -> reply + minimal audit · 2 RAG (pgvector, citations) ·
3 MCP gateway + three read-only mocks, every call audited · 4 duplicates, category/priority, escalation, dashboard metrics ·
5 knowledge loop (draft -> in_review -> published).

## Out of scope
- Real Credipay / FinSaaS / FinSaaS Lending endpoints and any product **write** action (write tools are not registered at all).
- The real Conversio API; the simulator stands in for it.
- Authentication, SSO, multi-tenant isolation beyond a tenant id carried on the event and used to filter retrieval and tools.
- Autonomous replies: every customer-facing message and action recommendation needs agent approval.
- The model changing status, SLA, assignee or any ticket field by itself.
- Outbound replies to Slack or Gmail; production hosting, scaling, queues beyond in-process `asyncio`.
- Fine-tuning, evals beyond the demo script, multilingual support, attachments, voice.
- Self-hosted embeddings (a fallback if compliance forbids a third party; keep behind an interface).
- Polished UI: functional pages only.

## Dependencies (pre-approved for v2)
Anthropic SDK, MCP Python SDK, pgvector support for SQLAlchemy/asyncpg, Voyage AI client, plus test tooling already added
(`pytest`, `pytest-asyncio`, `httpx`).

## Security rules (tested, not just documented)
- Mask sensitive values (card numbers, emails, phones, account numbers) before any model or embedding call; token map stays server-side.
- Customer text and tool results are untrusted input to the model (prompt injection): output is JSON validated against fixed lists, and recommended actions map to an allowlist.
- Tool gateway exposes only allowlisted read-only tools; the allowlist lives in config, not in model output.
- Approval gate has no bypass path: a suggestion cannot reach a customer without an agent approval row.
- No real credentials in `.env.example`, notes, tests or commits.

## Open inputs
Anthropic API key, Voyage key, Neon branch with pgvector enabled (SQLite cannot do vectors), presentation date.
