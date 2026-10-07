# Pylon Dummy

A v1 demo of a B2B support platform (a simplified Pylon clone). Messages arrive from Slack, Gmail, or a
manual "simulate" endpoint; they become issues with message threads, run through a trigger engine, are
timed by an SLA engine, and show up live on a dashboard.

Stack: FastAPI (async) · SQLite via SQLAlchemy (`aiosqlite`) · in-process `asyncio.Queue` event bus ·
WebSocket dashboard (one plain HTML file) · `asyncio` background tasks. No Celery, Redis, or build step.

## Run it

```
python -m venv venv                  # first time only
venv\Scripts\activate
pip install -r requirements.txt      # first time only
python seed.py                       # creates tables + demo org/team/user/account/contact, an SLA, one trigger
uvicorn app.main:app --reload
```

- API root: http://127.0.0.1:8000/ (returns `{"status": "ok"}`), interactive docs at `/docs`
- Dashboard: http://127.0.0.1:8000/dashboard
- Database: `pylon_dummy.db` in the folder you run uvicorn from. `seed.py` is safe to re-run.

Copy `.env.example` to `.env` to configure anything below. Changes to `.env` need a uvicorn **restart**
(`--reload` doesn't watch it).

## Try it without Slack or Gmail

With the server running, post a simulated customer message (this opens a new issue):

```
curl -X POST http://127.0.0.1:8000/simulate/message -H "Content-Type: application/json" ^
  -d "{\"org_id\":1,\"account_id\":1,\"author_type\":\"contact\",\"author_id\":1,\"body\":\"Checkout is down\",\"title\":\"urgent: checkout down\"}"
```

Reply as a teammate by repeating it with `"author_type":"user"` and `"issue_id": <id>`. With the dashboard open
you'll see the issue appear live, its status flip, the `urgent` tag added by the seeded trigger, the SLA
timer running, and every step in the audit log. The dashboard header also has a small form that does the same.

## How it works

Every channel adapter has one job: turn its message into the canonical event
`{channel, external_thread_id, external_message_id, author, body, occurred_at}` and push it on the queue.
One worker consumes the queue. Nothing downstream knows which channel a message came from.

For each event the worker: finds or opens the issue, adds the message, applies the status machine, then runs
triggers (`issue.created` / `message.created`). The SLA engine and dashboard hook into the same writes.

- **Status machine** (fixed: New → On You → On Customer → On Hold / Closed). Two automatic transitions only: a
  customer message moves the issue to On You (reopening a Closed one); a team reply moves it to On Customer.
  On Hold is never auto-changed; internal notes never change status.
- **Triggers**: evaluated in a single pass, top to bottom by `position`, no re-evaluation. Conditions are
  AND'd (`issue.title`, `message.body_html`, ... with `equals`/`not_equals`/`contains`/`not_contains`). Actions:
  `set_status`, `assign_team`, `add_tag`, `send_webhook` (a no-op stub that only logs). Triggers, adapters and the
  API bypass validation (`bypass_validation`); only manual human writes are validated.
- **SLA**: one type, Resolution Time (seeded at 480 min). A running/paused timer that only counts in New /
  On You / On Customer. A background task checks every 30 s; a breach writes `sla.breached` to the audit log and
  shows as a red banner/badge on the dashboard. `counts_business_hours_only` is stored but not enforced (24/7).
- **Audit log**: every create/update writes to `audit_logs` (issues, messages, status changes, contacts/accounts,
  tags, trigger evaluations and actions, SLA start/resume/breach). The seed script's bootstrap rows are the only
  exception.
- **Thread linking**: the schema has no external-thread column, so when an event opens a new issue the bus records
  `thread.linked:<channel>:<external_thread_id>` in `audit_logs`; later events on that thread join the issue.

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
the platform is out of scope for v1.

## Plug in real Gmail

1. Use a dedicated mailbox: the poller reads **unread** mail and marks handled messages as read.
2. Turn on 2-Step Verification, make sure IMAP is enabled, and create an **app password**
   (https://myaccount.google.com/apppasswords). Some Workspace accounts block app passwords.
3. In `.env`: `GMAIL_ADDRESS=you@gmail.com` and `GMAIL_APP_PASSWORD=<16 chars>` (spaces are fine), then restart.

Every 60 s it fetches unread INBOX mail over IMAP and pushes each message onto the bus. Replies (via
`In-Reply-To`/`References`) join the original issue; mail from your own address is ignored. If either value is
blank, the poller exits immediately (idle). Outbound email is out of scope for v1.

## Hosting it (Render + Neon)

The app is one long-running process (in-memory queue, background tasks, WebSockets), so it needs a normal
web-service host, not a serverless one. Render's free disk is wiped on every restart, so use hosted Postgres
instead of the SQLite file.

1. **Neon** (neon.tech): create a project, open **Connect**, turn **Connection pooling off**, and copy the
   `postgresql://…` string. Paste it as-is: `app/database.py` converts it for asyncpg (`sslmode` → `ssl`, drops
   `channel_binding`).
2. Push the repo to GitHub (`.env` and `*.db` are git-ignored).
3. **Render**: New → Blueprint → pick the repo. `render.yaml` sets the build/start commands (the start command
   runs the idempotent `seed.py` first, so the tables and demo data are created on first boot). Fill in
   `DATABASE_URL` (and `SLACK_SIGNING_SECRET` / `SLACK_BOT_TOKEN` if using Slack); add `GMAIL_ADDRESS` /
   `GMAIL_APP_PASSWORD` as extra env vars if using Gmail.
4. Point Slack's Event Subscriptions Request URL at `https://<service>.onrender.com/webhooks/slack`.

Free Render services sleep after ~15 minutes idle (first request takes 30–60 s, and the SLA checker and Gmail
poller pause while asleep), so open `/dashboard` a few minutes before presenting. There is no authentication:
anyone with the URL can use the dashboard and `/simulate/message`.

## Contacts and accounts

Both live adapters match the sender's email to an existing contact. Unknown senders get an account (by email
domain) and a contact created automatically in the first organization — v1 is single-tenant.

## Project layout

```
app/
  config.py  database.py  main.py
  models/      SQLAlchemy models (the 15 v1 tables)
  schemas/     Pydantic schemas
  core/        issue_service, status_machine, event_bus
  api/         issues, accounts, contacts, simulate, webhooks
  channels/    base (canonical event), manual / slack / gmail adapters, contact_resolver
  triggers/    engine, conditions, actions
  sla/         sla_engine (+ breach checker)
  realtime/    ws_manager (WebSocket broadcasting)
dashboard/index.html
seed.py
```

## Out of scope for v1

Knowledge base, AI agents, third-party ticket sync, outbound Slack/email replies, business-hours SLAs,
a REST API for managing triggers/SLAs (they're seeded), authentication.
