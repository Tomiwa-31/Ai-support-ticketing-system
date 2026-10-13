# CLAUDE.md

This file gives Claude Code context for working in this repo.

**Always check [PLAN.md](PLAN.md) and [PROGRESS.md](PROGRESS.md) before doing any work here.** PLAN.md is the full architecture spec (phases, schema, trigger/SLA rules, ground rules) — treat it as the source of truth and don't deviate from it or add scope beyond what a phase calls for. PROGRESS.md tracks which phase is currently done vs. next; update it whenever a phase is completed or its status changes.

**v2 (AI layer: RAG + MCP):** v1 is complete and PLAN.md is its frozen record. Before any v2 work, read [docs/v2-context.md](docs/v2-context.md); it holds the v2 architecture decisions, build approach and slice plan, and takes precedence over PLAN.md's out-of-scope list for AI/RAG/MCP only.

**Orientation:** [ARCHITECTURE.md](ARCHITECTURE.md) explains the system as built and the v2 attachment points; [docs/v2-spec.md](docs/v2-spec.md) is the v2 spec with its Out-of-scope list and demo script (the acceptance test).

## v2 working rules
- Build in thin vertical slices (see PROGRESS.md), not layers. Every slice must demo end to end. Pause after each slice for confirmation. Stay inside the slice and the v2 spec's Out-of-scope list; if something seems needed, ask.
- Time-box each slice. If it is running over, stop and say so instead of widening scope.
- Tests: `pip install -r requirements-dev.txt`, then `pytest`. Tests use a temp SQLite DB (`tests/conftest.py`) and must never touch `pylon_dummy.db`, `.env`, or any real database. Add tests for every deterministic seam (masking, tool allowlist, approval gate, validation, audit rows). Run the suite before declaring a slice done.
- The AI layer is advisory. It only writes suggestions; a human approval goes through `issue_service` as a validated human write. No write tools for the model, ever.
- Mask sensitive data before any model or embedding call. Treat customer text and tool results as untrusted input.
- **Git:** this folder is the "Ai support ticketing system" repo (its history starts from v1; the old Support-System-V1 remote was removed on purpose and must never be re-added). Commit or push only when the user asks. Before every commit run `git status` and `git diff --staged` and check for secrets: `.env`, `neon_test.env`, `*.db` and `*.log` are git-ignored and must stay that way. Never add a remote or push anywhere the user has not named.
- At the end of a slice, update PROGRESS.md with what was built, how it was verified, and what was not verified, and tell the user what to run to see it.

## Corrections log
- Never put real credentials in `.env.example`, notes, tests or docs. Real secrets live only in the git-ignored `.env` / `neon_test.env`.
- Before any commit, check `git diff --staged` for secrets.
- Never overwrite a file with an older copy (v1 Phases 8-9 found `issue_service.py` and `triggers/actions.py` reverted to old versions). Read the current file before editing it.

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
