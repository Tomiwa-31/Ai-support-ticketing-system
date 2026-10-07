# CLAUDE.md

This file gives Claude Code context for working in this repo.

**Always check [PLAN.md](PLAN.md) and [PROGRESS.md](PROGRESS.md) before doing any work here.** PLAN.md is the full architecture spec (phases, schema, trigger/SLA rules, ground rules) — treat it as the source of truth and don't deviate from it or add scope beyond what a phase calls for. PROGRESS.md tracks which phase is currently done vs. next; update it whenever a phase is completed or its status changes.

## Tech stack
- Backend: FastAPI (async), Python
- DB: SQLite via SQLAlchemy (async, `aiosqlite` driver) — written so it's a one-line swap to Postgres later
- Real-time: FastAPI WebSocket broadcasting DB changes to a dashboard
- Event bus: in-process `asyncio.Queue` (channel adapters push canonical events, one worker consumes) — not Kafka/SQS
- Frontend: a single plain HTML/JS page (`dashboard/index.html`), no framework, no build step
- Background jobs: `asyncio` background tasks (Gmail IMAP polling, SLA breach checks) — no Celery/Redis
- Secrets: `.env` (see `.env.example`), loaded via `app/config.py` (pydantic-settings)

## Conventions
- Every channel adapter's only job is to convert its message into the canonical inbound event shape and push it onto the queue. Nothing downstream should know or care which channel a message came from — no channel-specific logic past the adapter layer.
- Manual/human writes go through validation; triggers, the API, and adapters bypass validation via a `bypass_validation` flag threaded through the write path.
- Every create/update should write to `audit_logs`.
- Build phase by phase per PLAN.md, and pause after each phase for confirmation before moving to the next. Don't skip ahead or add features beyond what a phase lists.

## Project layout
```
app/
  config.py       Settings (env vars)
  database.py     Async SQLAlchemy engine/session
  main.py         FastAPI app entrypoint
  models/         SQLAlchemy models (Phase 1+)
  schemas/        Pydantic schemas (Phase 2+)
  core/           Domain services: issues, status machine, event bus
  api/            REST routers
  channels/       Channel adapters (manual, Slack, Gmail)
  triggers/       Trigger engine
  sla/            SLA engine
  realtime/       WebSocket manager
dashboard/
  index.html      Plain HTML/JS dashboard (Phase 7+)
```

## Running it
```
venv\Scripts\activate
uvicorn app.main:app --reload
```
