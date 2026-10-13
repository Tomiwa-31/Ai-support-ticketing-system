# V2 context: AI layer demo (handoff from the v1 session)

Status: **Slices 0 and 1 done. Slices 0-3 done. Next: Slice 4 (duplicates, category/priority, escalation, dashboard metrics).** See [v2-spec.md](v2-spec.md) for the demo script and Out-of-scope list.

## What v2 is
A **demo** of how an AI layer (Claude + RAG + MCP) interfaces with the ticketing engine built in v1. It is not the production system. Spend effort on the *seams* (adapter contract, tool registry, approval API, audit schema), which should match what production will use. Model quality and UI polish come second.

The product it demonstrates is "Delivery 1: Conversio-powered unified AI support platform":
- Authenticated support requests that keep tenant, user, product and correlation context.
- Structured ticket lifecycle: category, priority, owner, status, timestamps, SLA indicator, escalation history.
- Claude classifies, summarises, detects likely duplicates, retrieves approved knowledge, drafts a reply or next action.
- Deterministic rules for access, product mapping, state transitions, SLA, escalation, required fields, permitted actions.
- Conversational requests routed to governed Credipay, FinSaaS and FinSaaS Lending interfaces. All product write actions disabled.
- A support agent must approve customer-facing responses and action recommendations (90-day pilot).
- Mask sensitive data before model use. Audit model, prompt, knowledge source, tool call, result, approval, outcome.
- Dashboard: volumes, categories, ageing, escalation, AI usage, workflow success, latency, cost, outcome.
- Knowledge base updated from confirmed resolutions and product docs under review control.

## Architecture decision: AI as an advisory sidecar
The v1 ticketing engine stays the system of record and the only writer of tickets. The AI layer reads tickets and writes only **suggestions**; a human approves; approval goes through existing services. (Same spirit as the channel rule: AI proposes, deterministic code decides.)

```
Slack / Gmail / Conversio adapter -> event bus -> issue + message saved
      -> status machine, triggers, SLA                         (unchanged)
            | trigger action "request_ai_assist" (a rule decides when AI runs)
            v
    AI queue + AI worker (separate from the main worker)
    mask sensitive data -> retrieve knowledge (RAG) -> read-only tools (MCP)
            -> Claude -> validate structured output
            v
    ai_suggestions (pending) + AI audit record
            v
    Agent approves / edits / rejects -> existing add_message / actions
```

Key choices:
1. Separate AI queue and worker (model calls take seconds; must not block the main worker or Slack's 3 s ack).
2. Claude returns structured JSON only (category, priority, summary, duplicate candidates, draft, recommended action), validated against fixed lists. Recommended actions map to existing trigger actions. The model can never change status, SLA or assignee itself.
3. RAG in Postgres with pgvector (Neon supports it). Every search filters by org and product. Articles go draft -> in_review -> published; confirmed resolutions only create *drafts*.
4. MCP as a tool gateway: allowlisted, read-only tools. Write tools are not registered at all. Conversio enters as another channel adapter.
5. Mask sensitive values before the model (rule-based, tokens map kept server-side). Treat customer text and tool results as untrusted (prompt injection).
6. `audit_logs` has no payload column, so add `ai_runs` + `ai_run_events` (model, masked prompt, knowledge sources, tool calls, result, approval, outcome, tokens, latency, cost) linked by correlation ID, plus short summary rows in `audit_logs`.

## Decisions made with the user
- **The three products expose governed interfaces through MCP.** The user has no access to those endpoints or to Conversio's API yet.
- Therefore: **mock MCP servers** (Credipay, FinSaaS, FinSaaS Lending; read-only, fake data) in one clearly labelled folder, behind a **tool registry** (server, allowed tools, tenant-to-product mapping). The gateway discovers tools via MCP `list_tools` and exposes only allowlisted ones. Swapping mock for real = configuration change. Mock tool names are guesses; confirm when real access exists.
- **Demo channel: a Conversio simulator** (customer chat page + `conversio_adapter` carrying tenant, user, product, correlation ID, with approved replies delivered back to the chat). Slack stays as a second channel.
- **Embeddings: Voyage AI** (Claude has no embedding model). Confirm current model names and pricing. Keep behind an interface and store model name with each vector. Fallback if compliance forbids third parties: self-hosted bge/e5. Mask before embedding.

## Build approach (from `C:\Users\DELL\Downloads\claude-code-prompt.md`, not in the repo)
Agreed with most of it: smallest spec with an Out-of-scope list, thin vertical slices (not layers), time-box per slice, small commits, self-verifying tests, end-of-phase "keep me knowledgeable" routine, extra care on security (masking, approval gate, tool gateway). Adaptations:
1. Pre-approve the new dependencies v2 needs (Anthropic SDK, MCP SDK, pgvector support, embedding client).
2. **Merge** those rules into `CLAUDE.md`; do not replace it. Keep v1 invariants (below). `PLAN.md` is the frozen v1 record.
3. The v2 spec's acceptance test is the **demo script**.
4. Add Corrections-log entries: never put real credentials in `.env.example` or notes; check `git diff --staged` for secrets before committing; never overwrite a file with an old copy.
Use "explain it back / predict before running" only for the risky parts (masking, approval gate, tool gateway).

## Slices
| Slice | Demonstrates |
|---|---|
| 0 | Housekeeping: committed `tests/`, `ARCHITECTURE.md`, merged `CLAUDE.md`, one-page v2 spec with Out-of-scope list |
| 1 | Whole story, thin: Conversio chat -> masking -> Claude classify/summarise/draft -> agent approval -> reply to the customer, minimal audit record |
| 2 | RAG: knowledge articles in pgvector, citations, knowledge source logged |
| 3 | MCP gateway + mock Credipay tool, then the other two mocks, every tool call audited |
| 4 | Duplicate detection, category/priority, escalation, dashboard metrics (latency, cost) |
| 5 | Knowledge loop: confirmed resolution -> draft article -> review -> publish |

## What the v1 codebase gives v2 (and what it lacks)
Invariants to preserve:
- Every channel adapter only converts its message to the canonical `InboundEvent` and publishes it; nothing downstream knows the channel.
- Manual/human writes are validated; triggers, API and adapters bypass via `bypass_validation`. Human-approved AI actions count as manual writes (validated).
- Every create/update writes to `audit_logs`.
- Triggers run in a single pass ordered by `position`; SLA timer counts only in New / On You / On Customer; seeded Resolution Time SLA = 480 min (value lives in the `slas` table).
- Thread-to-issue links are stored as `thread.linked:<channel>:<thread id>` rows in `audit_logs`.

Gaps v2 must fill: no authentication; single-tenant; no category, priority or escalation history; v1 schema was frozen, so v2 adds tables/columns; no outbound replies to Slack/Gmail; the Gmail adapter was only tested with a fake IMAP server.

Environment: SQLite locally, Postgres (Neon) when hosted on Render, chosen by `DATABASE_URL` (`app/database.py` converts provider URLs for asyncpg). pgvector needs Postgres, so develop AI features against a Neon branch. Real secrets live only in the git-ignored `.env` / `neon_test.env`. The v1 verification scripts were scratch files and were not kept, so Slice 0 must create real tests. Repo: GitHub `Tomiwa-31/Support-System-V1`, branch `main`; a local branch `backup-before-cleanup` still contains old secrets and should be deleted, never pushed.

## Still needed from the user
Anthropic API key and Voyage key (for `.env`), a Neon branch with the pgvector extension enabled, and the presentation date (to size the slices).

## Known follow-ups (decided, not yet built)
- **Per-message context: DONE in Slice 3** (`message_contexts`; the worker answers a message with its own context).
- **External business id on accounts.** `accounts` has no column for Conversio's business id; today the account is inferred from the email domain. Add the column once the real post-login payload (business id/name, user, product) is known.
- **Product mapping: DONE in Slice 3** (registry: tenant -> products, product -> tool server + allowlist).
- **Agent note field (remind the user after all slices are done).** A separate `agent_note` on AI suggestions for guidance taken from knowledge articles (e.g. "escalate if more than 2 business days have passed"), kept out of the summary. Needs a new column on `ai_suggestions`, so also a small "add missing column" startup step because `create_all` never alters existing tables. Deferred by the user on 2026-10-09; for now the summary prompt only allows what the customer reported or asked.
- **Tool authorisation per customer (important before production).** The gateway checks tenant -> product and the tool allowlist, but not that the account/loan/transaction a tool is asked about belongs to the customer who is writing. Anyone who can type an account number could ask the AI about someone else's loan. In production: pass the authenticated customer identity to the tool server (MCP request metadata / auth) and have the product system enforce ownership; the gateway should refuse calls it cannot attribute to an authenticated customer. Not built in the demo.
- **Tool names/arguments are guesses** (mock servers). Confirm against the real Credipay / FinSaaS / FinSaaS Lending interfaces; then point the registry at them.
- **Per-run tool turns cost latency and tokens** (live test: ~10-18 s, ~9K input tokens with two tool calls). Options later: cache the system prompt, lower tool-round limit, stream, or run tools in parallel.
