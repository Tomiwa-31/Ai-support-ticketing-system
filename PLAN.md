# Pylon Dummy — v1 Demo Plan

A v1 demo of a B2B support platform (a simplified Pylon clone) in Python/FastAPI with SQLite.
Built incrementally, phase by phase, confirming each phase works before moving to the next.

## Stack
- Backend: FastAPI (async)
- DB: SQLite via SQLAlchemy (so it's a one-line swap to Postgres later)
- Real-time: FastAPI WebSocket, broadcasting DB changes to a dashboard
- Event bus: simulate with an in-process asyncio.Queue (channel adapters push events, one worker consumes them) — not Kafka/SQS, keep it simple
- Frontend: a single plain HTML/JS page (dashboard/index.html), no framework, no build step
- Background jobs (Gmail IMAP polling, SLA breach checks): asyncio background tasks, no Celery/Redis

## Core concept
Messages come in from multiple channels (Slack, Gmail, and a manual/simulate endpoint for testing). Every channel adapter's only job is to convert its message into one canonical shape and push it onto the queue. Nothing downstream should ever know or care which channel a message came from — this is the most important architectural rule, don't let channel-specific logic leak past the adapter layer.

## Canonical inbound event shape
```
{ channel, external_thread_id, external_message_id, author (contact_ref | bot_ref), body, occurred_at }
```

## Database schema (v1 only — do not add anything beyond this list)
```
organizations(id, name, created_at)
users(id, org_id, name, email, role)
teams(id, org_id, name)
accounts(id, org_id, name, primary_domain)
contacts(id, org_id, account_id, name, email)
issues(id, org_id, title, status, account_id, contact_id, assignee_id, team_id, channel, is_ticket, created_at, resolved_at, updated_at)
messages(id, issue_id, author_type, author_id, body_html, is_internal_note, created_at)
tags(id, org_id, name)
issue_tags(issue_id, tag_id)
triggers(id, org_id, name, kickoff_event, position, is_enabled)
trigger_conditions(id, trigger_id, field, operator, value)
trigger_actions(id, trigger_id, action_type, params, position)
slas(id, org_id, name, target_minutes, counts_business_hours_only)
sla_instances(id, issue_id, sla_id, started_at, paused_seconds, breached_at)
audit_logs(id, org_id, actor_type, actor_id, action, target_type, target_id, happened_at)
```

## Status state machine (fixed 5 statuses)
```
New -> On You -> On Customer -> On Hold / Closed
```
Two automatic transitions only:
1. A Closed issue reopens (status -> On You) when a new customer message arrives.
2. Status flips to "On You" when the customer replies last, and "On Customer" when the team replies last.

## Trigger engine rules (important — copy exactly, don't "improve")
- Triggers are evaluated in a single pass, top to bottom, ordered by `position`. No re-evaluation loop, no re-checking earlier triggers after a later one changes state.
- Required-field/validation rules apply ONLY to manual human-initiated writes. Triggers, the API, and adapters bypass validation entirely (implement as a bypass_validation flag threaded through the write path).
- Log every trigger evaluation and action taken to audit_logs.

## SLA rules
- Model as a running/paused timer, not created_at + target_minutes.
- Only accrues while the issue is in a "counting" status (not On Hold / Closed).
- One SLA type for v1: Resolution Time. Breach = write to audit_logs + a note visible on the dashboard (no real Slack alert needed yet).

## File structure — build in this order, phase by phase, and pause after each phase for confirmation before continuing:

**Phase 0: Scaffolding** — requirements.txt, app/config.py, app/database.py, app/main.py. Goal: `uvicorn app.main:app` runs and returns `{"status": "ok"}`.

**Phase 1: Schema & seed** — all files under app/models/, plus seed.py that creates one demo org/team/user/account/contact. Goal: open the SQLite file and see the tables and seed rows.

**Phase 2: Core domain + REST API** — app/core/issue_service.py, app/schemas/*, app/api/issues.py, app/api/accounts.py, app/api/contacts.py. Goal: POST /issues and POST /issues/{id}/messages via curl and see rows appear.

**Phase 3: Manual channel adapter + event bus** — app/channels/base.py, app/channels/manual_adapter.py, app/core/event_bus.py, plus a POST /simulate/message endpoint. Goal: a simulated message flows through the full canonical pipeline into issues/messages tables.

**Phase 4: Status state machine** — app/core/status_machine.py. Goal: verify the two automatic transitions using the simulate endpoint.

**Phase 5: Trigger engine** — app/triggers/engine.py, conditions.py, actions.py (support at minimum: set_status, assign_team, add_tag, send_webhook as a no-op stub for now). Seed one example trigger and prove it fires correctly and logs to audit_logs.

**Phase 6: SLA engine** — app/sla/sla_engine.py, plus a background task that checks for breaches periodically.

**Phase 7: Real-time dashboard** — app/realtime/ws_manager.py, dashboard/index.html. Goal: opening the dashboard in a browser and firing a simulated message updates the UI live with no refresh — show the issue list, its message thread, and a running trigger/audit log.

**Phase 8: Slack live adapter** — app/channels/slack_adapter.py, app/api/webhooks.py (including the URL verification challenge echo). Should work with real Slack Events API credentials from .env, and stay inert if the env vars are blank.

**Phase 9: Gmail live adapter** — app/channels/gmail_adapter.py using IMAP polling. Should work once GMAIL_APP_PASSWORD is set in .env, and stay inert/idle if blank.

**Phase 10: Polish** — make sure every create/update writes to audit_logs, and write a README.md explaining how to run it and how to plug in real Slack/Gmail credentials later.

## Ground rules
- After each phase, tell the user exactly what to run/test to verify it before moving on.
- Don't add features beyond what's listed for each phase (no knowledge base, no AI agents, no third-party ticket sync — those are explicitly out of scope for this build).
- Use .env for all secrets (SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, GMAIL_ADDRESS, GMAIL_APP_PASSWORD), with a .env.example checked in instead.
