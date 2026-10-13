# AI Support Ticketing System

A B2B support platform (a simplified Pylon clone) with an advisory AI layer on top. Messages arrive from the
**Conversio chat**, Slack, Gmail, or a manual "simulate" endpoint; they become issues with message threads, run
through a trigger engine, are timed by an SLA engine, and show up live on a dashboard. For Conversio chats, Claude
reads the conversation (with sensitive values masked), searches an approved knowledge base, can look up account data
through read-only tools, and drafts a reply. **A support agent must approve it before the customer sees anything.**

Stack: FastAPI (async) · SQLite via SQLAlchemy (`aiosqlite`), or Postgres with pgvector · in-process `asyncio.Queue`
event bus · WebSocket dashboard (plain HTML files) · `asyncio` background tasks · Claude (Anthropic API) · Voyage AI
embeddings · MCP (Model Context Protocol) for tools. No Celery, Redis, or build step.

Where to read more: [ARCHITECTURE.md](ARCHITECTURE.md) (how it works, plus a file map of the tool/MCP/playbook
pieces), [docs/v2-spec.md](docs/v2-spec.md) (the v2 spec and demo script), [PROGRESS.md](PROGRESS.md) (what was built and
verified, and the known limits).

## Run it

```
python -m venv venv                  # first time only
venv\Scripts\activate
pip install -r requirements.txt      # first time only
python seed.py                       # tables + demo org/team/user/account/contact, an SLA, and two triggers
uvicorn app.main:app --reload
```

- API root: http://127.0.0.1:8000/ (returns `{"status": "ok"}`), interactive docs at `/docs`
- Dashboard (agent view): http://127.0.0.1:8000/dashboard
- Conversio chat (customer view): http://127.0.0.1:8000/conversio
- Database: `pylon_dummy.db` in the folder you run uvicorn from. `seed.py` is safe to re-run, and you must run it
  once after upgrading an older database (it adds the AI trigger; the new tables are created at startup).

Copy `.env.example` to `.env` to configure anything below. Changes to `.env` need a uvicorn **restart**
(`--reload` doesn't watch it).

## Use the Conversio channel and the AI assistant

Conversio is the customer chat. This repo includes a simulator for it, so you can try the whole flow locally.
Without the keys below the tickets still work; the AI just records a failed run instead of drafting.

**1. Add keys to `.env`** (never commit this file; it is git-ignored):

| Variable | What for |
|---|---|
| `ANTHROPIC_API_KEY` | Claude. Required for drafts. |
| `ANTHROPIC_WORKSPACE_ID` | Only if your key is not scoped to one workspace (the API then asks for it). |
| `VOYAGE_API_KEY` | Embeddings for the knowledge base. Without it, drafts are made with no articles and the run log says why. |
| `AI_MODEL` | Optional. Defaults to `claude-haiku-5-5`; set a larger model for production. |
| `EMBEDDING_MODEL`, `KB_TOP_K`, `KB_MIN_SCORE` | Optional. Defaults `voyage-4`, 4 articles, minimum similarity 0.3. |
| `AI_MAX_TOOL_CALLS`, `AI_TOOL_TIMEOUT_SECONDS`, `AI_MAX_OUTPUT_TOKENS` | Optional. Defaults 4, 15, 8000. |

A Voyage account without a payment method is limited to 3 requests a minute; the loader below waits and retries, and a
ticket that hits the limit simply gets a draft without articles.

**2. Load the demo knowledge articles** (10 invented articles for Credipay, FinSaaS and FinSaaS Lending; needs
`VOYAGE_API_KEY` and a seeded database; safe to re-run):

```
python -m app.knowledge.load_samples
```

**3. Chat and review.** Open the chat at `/conversio` and the dashboard at `/dashboard` side by side.
Pick a product in the chat, type as the customer, and click **New conversation** to start a separate ticket.
A few seconds later the dashboard shows a **suggestion** on that issue: category, priority, summary, recommended
action, the knowledge articles and tools used, and an editable draft reply. The agent edits the draft and clicks
**Approve & send to customer** (the reply then appears in the chat and the issue moves to On Customer) or **Reject**
(nothing is sent). Approval is refused while the draft still contains a masked placeholder such as `[ACCOUNT_1]`.

**Two scenarios to try** (the product servers are mocks with fake data):

1. *Product FinSaaS Lending.* Send `My loan was approved on 6 October but the money has not reached my account.`
   The assistant should ask for a loan reference or account number and call no tool. Then send
   `The account number is 0123456789. Please check where my money is.` It looks up the loan by account, then its
   disbursement status (loan `LN-1001`, held for bank verification, account ending 6789) and recommends escalating.
2. *Product Credipay.* Send `I was charged twice for payment TX-5001. My card is 4111 1111 1111 1111.` It looks up the
   transaction (an authorisation hold, released in 3 to 5 working days) and cites the "Duplicate or double charges"
   article. The card number never reaches Claude or appears in the stored record.

Other mock data: lending account `0987654321` → loan `LN-1002` (disbursed); Credipay `TX-5002` (failed transfer,
reversal pending) and account `0987654321` (locked); FinSaaS invoice `INV-2002` (overdue), webhook endpoint `ep-77`
(failing) and account `acct-9`.

**To see exactly what happened in a run**, open `http://127.0.0.1:8000/ai/runs/<id>` (ids start at 1). It shows the
masked prompt Claude was sent, the model's JSON answer, tokens and latency, and the step log: knowledge retrieved,
tools offered, each tool call with its masked result, and citations.

You can also post as Conversio directly:

```
curl -X POST http://127.0.0.1:8000/conversio/messages -H "Content-Type: application/json" ^
  -d "{\"tenant_id\":\"commsworth\",\"user\":{\"id\":\"u1\",\"email\":\"jamie@acme.com\",\"name\":\"Jamie\"},\"product\":\"finsaas-lending\",\"conversation_id\":\"demo-1\",\"text\":\"Where is my loan money?\"}"
```

`product` is `credipay`, `finsaas` or `finsaas-lending`. The same `conversation_id` keeps joining the same issue.

## How the AI layer works

The ticketing engine stays the system of record and the only writer of tickets. The AI layer only writes
**suggestions**; a human approval goes through the normal validated message path.

```
Conversio message -> adapter -> event bus -> issue + message (status machine, triggers, SLA as usual)
   -> seeded trigger "request_ai_assist" -> separate AI queue -> AI worker:
        mask the conversation -> search approved knowledge (pgvector or SQLite) -> open the product's tools
        -> Claude drafts (JSON, validated) and may call read-only tools -> pending suggestion + audit record
   -> agent edits and approves -> reply is added as a normal message -> the chat shows it
```

- **Masking**: emails, phone numbers, card and account numbers become placeholders (`[EMAIL_1]`, `[CARD_1]`...) before
  anything goes to a model or an embedding service. The placeholder-to-value map never leaves the server. Real emails
  and phones are put back in the agent's draft; card and account numbers never are.
- **Approval gate**: the only path from a suggestion to a customer message. It needs a real support user, and the
  suggestion must still be pending.
- **Knowledge base (RAG)**: articles are chunked, masked, embedded with Voyage, and stored with the model name.
  Searches are always filtered by organisation and product, return only published articles, and ignore weak matches.
  The draft cites the articles it used; made-up citations are dropped.
- **Tools (MCP)**: `app/mcp_gateway/registry.py` lists, per product, which MCP server to use, an allowlist of
  read-only tools, which tenant may use which product, and a per-product **playbook** (the order to use the tools in).
  The gateway is the only way the AI reaches product systems: it offers only allowlisted tools, replaces masked
  placeholders in tool arguments with the real values on the server (never card numbers), masks results again, limits
  each run to 4 calls, and logs every call. The three product servers in `app/mcp_servers/` are **mocks**; pointing the
  registry at a real server is a configuration change.
- **Audit**: every step writes to `audit_logs` (`ai.requested`, `ai.run_started`, `ai.suggestion_created`,
  `ai.tool_call:<tool>`, `ai.suggestion_approved`, ...), and each model call has an `ai_runs` record with its step log.
- **If something is unavailable** (no key, an API error, no tools for that tenant), the run still completes without
  that part and logs why; it never blocks the ticket.

## Try it without Slack, Gmail or Conversio

With the server running, post a simulated customer message (this opens a new issue):

```
curl -X POST http://127.0.0.1:8000/simulate/message -H "Content-Type: application/json" ^
  -d "{\"org_id\":1,\"account_id\":1,\"author_type\":\"contact\",\"author_id\":1,\"body\":\"Checkout is down\",\"title\":\"urgent: checkout down\"}"
```

Reply as a teammate by repeating it with `"author_type":"user"` and `"issue_id": <id>`. With the dashboard open
you'll see the issue appear live, its status flip, the `urgent` tag added by the seeded trigger, the SLA
timer running, and every step in the audit log. The dashboard header also has a small form that does the same.
The AI only runs for Conversio chats (that is what the seeded rule says), not for simulated or Slack messages.

## How the ticketing engine works

Every channel adapter has one job: turn its message into the canonical event
`{channel, external_thread_id, external_message_id, author, body, occurred_at}` (plus optional tenant/product/
correlation context) and push it on the queue. One worker consumes the queue. Nothing downstream knows which channel
a message came from.

For each event the worker: finds or opens the issue, adds the message, applies the status machine, then runs
triggers (`issue.created` / `message.created`). The SLA engine and dashboard hook into the same writes.

- **Status machine** (fixed: New → On You → On Customer → On Hold / Closed). Two automatic transitions only: a
  customer message moves the issue to On You (reopening a Closed one); a team reply moves it to On Customer.
  On Hold is never auto-changed; internal notes never change status.
- **Triggers**: evaluated in a single pass, top to bottom by `position`, no re-evaluation. Conditions are
  AND'd (`issue.title`, `issue.channel`, `message.author_type`, ... with `equals`/`not_equals`/`contains`/
  `not_contains`). Actions: `set_status`, `assign_team`, `add_tag`, `send_webhook` (a no-op stub that only logs),
  `request_ai_assist` (queues the AI worker). Triggers, adapters and the API bypass validation
  (`bypass_validation`); only manual human writes are validated.
- **SLA**: one type, Resolution Time (seeded at 480 min). A running/paused timer that only counts in New /
  On You / On Customer. A background task checks every 30 s; a breach writes `sla.breached` to the audit log and
  shows as a red banner/badge on the dashboard. `counts_business_hours_only` is stored but not enforced (24/7).
- **Audit log**: every create/update writes to `audit_logs` (issues, messages, status changes, contacts/accounts,
  tags, trigger evaluations and actions, SLA start/resume/breach, AI steps). The seed script's bootstrap rows are the
  only exception.
- **Thread linking**: the schema has no external-thread column, so when an event opens a new issue the bus records
  `thread.linked:<channel>:<external_thread_id>` in `audit_logs`; later events on that thread join the issue. A new
  issue is opened only when a message has no matching thread.
- **Message context**: tenant, product, customer reference and correlation id are saved for every message that
  carries them (`message_contexts`), and for the issue's first message (`issue_contexts`).

## Plug in real Slack

Slack only needs the **signing secret** to turn on; the bot token is optional (without it, senders appear as
`<user id>@slack.invalid` instead of their real email/name).

1. https://api.slack.com/apps → **Create New App** → From scratch.
2. **Basic Information** → copy **Signing Secret** → `SLACK_SIGNING_SECRET` in `.env`.
3. **OAuth & Permissions** → Bot Token Scopes: `channels:history`, `users:read`, `users:read.email`
   (add `groups:history` / `im:history` / `mpim:history` for private channels / DMs). **Install to Workspace**, copy
   the `xoxb-...` **Bot User OAuth Token** → `SLACK_BOT_TOKEN`.
4. Expose your server publicly (for local dev: `ngrok http 8000`) and restart uvicorn.
5. **Socket Mode must be OFF** (Settings → Socket Mode). With it on, Slack stops sending HTTP events.
6. **Event Subscriptions** → enable → Request URL `https://<your-host>/webhooks/slack` (must show Verified) →
   Subscribe to bot events: `message.channels` (plus `message.groups` / `message.im` / `message.mpim` as needed)
   → Save. Reinstall the app if Slack asks.
7. Create a public channel, `/invite @YourApp`, and post. Replies in a Slack thread join the same issue.

Requests are verified with Slack's signing scheme (5-minute replay window). With `SLACK_SIGNING_SECRET` blank,
`/webhooks/slack` returns 503 and nothing runs. Bot posts, edits and retries are ignored. Replying *to* Slack from
the platform is out of scope.

## Plug in real Gmail

1. Use a dedicated mailbox: the poller reads **unread** mail and marks handled messages as read.
2. Turn on 2-Step Verification, make sure IMAP is enabled, and create an **app password**
   (https://myaccount.google.com/apppasswords). Some Workspace accounts block app passwords.
3. In `.env`: `GMAIL_ADDRESS=you@gmail.com` and `GMAIL_APP_PASSWORD=<16 chars>` (spaces are fine), then restart.

Every 60 s it fetches unread INBOX mail over IMAP and pushes each message onto the bus. Replies (via
`In-Reply-To`/`References`) join the original issue; mail from your own address is ignored. If either value is
blank, the poller exits immediately (idle). Outbound email is out of scope.

## Hosting it (Render + Neon)

The app is one long-running process (in-memory queues, background tasks, WebSockets), so it needs a normal
web-service host, not a serverless one. Render's free disk is wiped on every restart, so use hosted Postgres
instead of the SQLite file.

1. **Neon** (neon.tech): create a project, open **Connect**, turn **Connection pooling off**, and copy the
   `postgresql://…` string. Paste it as-is: `app/database.py` converts it for asyncpg (`sslmode` → `ssl`, drops
   `channel_binding`). On Postgres the knowledge base uses real **pgvector**: startup runs
   `CREATE EXTENSION IF NOT EXISTS vector` and creates an index, so the database role must be allowed to do that
   (Neon allows it for the project owner). Vectors are stored as `vector(1024)`.
2. Push the repo to GitHub (`.env` and `*.db` are git-ignored).
3. **Render**: New → Blueprint → pick the repo. `render.yaml` sets the build/start commands (the start command
   runs the idempotent `seed.py` first, so the tables and demo data are created on first boot). Fill in
   `DATABASE_URL` (and `SLACK_SIGNING_SECRET` / `SLACK_BOT_TOKEN` if using Slack); add `GMAIL_ADDRESS` /
   `GMAIL_APP_PASSWORD` as extra env vars if using Gmail, and `ANTHROPIC_API_KEY` (plus `ANTHROPIC_WORKSPACE_ID` if
   needed) and `VOYAGE_API_KEY` for the AI layer. `render.yaml` does not list the AI variables, so add them in the
   Render dashboard. Run `python -m app.knowledge.load_samples` once against that database (from your machine with
   `DATABASE_URL` pointing at it, or in a Render shell) to load the demo articles.
4. Point Slack's Event Subscriptions Request URL at `https://<service>.onrender.com/webhooks/slack`.

Free Render services sleep after ~15 minutes idle (first request takes 30–60 s, and the SLA checker and Gmail
poller pause while asleep), so open `/dashboard` a few minutes before presenting. There is **no authentication**:
anyone with the URL can use the dashboard, the chat, `/simulate/message` and the approval endpoints. Do not put real
customer data in a deployment like this.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

About a minute. Every test runs against a throwaway SQLite database, uses fake model and embedding clients, and never
reads your `.env` keys or touches `pylon_dummy.db`. It covers the status machine, triggers, SLA timers, the event
pipeline, masking, the approval gate, knowledge search, the tool gateway (including a real MCP server over HTTP) and
the AI worker end to end.

## Contacts and accounts

All channel adapters match the sender's email to an existing contact. Unknown senders get an account (by email
domain) and a contact created automatically in the first organization (single-tenant for now). The Conversio tenant id
is recorded as context only.

## Project layout

```
app/
  config.py  database.py  main.py
  models/        SQLAlchemy models (v1 tables + ai_runs, ai_run_events, ai_suggestions, issue/message contexts, knowledge)
  schemas/       Pydantic schemas
  core/          issue_service, status_machine, event_bus
  api/           issues, accounts, contacts, simulate, webhooks, conversio, ai (approval), knowledge
  channels/      base (canonical event), manual / slack / gmail / conversio adapters, contact_resolver
  triggers/      engine, conditions, actions
  sla/           sla_engine (+ breach checker)
  realtime/      ws_manager (WebSocket broadcasting)
  ai/            masking, llm (Claude + tool loop), worker, service (approval gate), schemas, events, queue
  knowledge/     embeddings (Voyage), chunking, store (search), vector column type, samples + loader
  mcp_gateway/   registry (servers, allowlists, tenant map, playbooks), gateway (the MCP client and its guards)
  mcp_servers/   MOCK Credipay / FinSaaS / FinSaaS Lending MCP servers (fake data, read-only)
dashboard/       index.html (agent dashboard), conversio.html (customer chat simulator)
docs/            v2 spec, context and decisions, v1 progress log
tests/
seed.py
```

## Out of scope (for now)

Real Credipay / FinSaaS / FinSaaS Lending endpoints and any product write action (the model has no write tools),
the real Conversio API (the simulator stands in), authentication and per-customer authorisation of tool calls,
autonomous replies (an agent always approves), outbound Slack/email replies, business-hours SLAs, third-party ticket
sync, a REST API for managing triggers/SLAs (they're seeded). Still to build: duplicate detection, escalation rules and
the metrics dashboard (Slice 4) and the knowledge review loop (Slice 5); see [PROGRESS.md](PROGRESS.md).
