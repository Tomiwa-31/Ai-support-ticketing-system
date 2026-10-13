# Architecture

How the system works today (v1, as built and tested), and where the v2 AI layer attaches. v1 is the
system of record; v2 is an advisory sidecar. Decisions and slice plan for v2 live in
[docs/v2-context.md](docs/v2-context.md); the acceptance test is in [docs/v2-spec.md](docs/v2-spec.md).

## v1 message flow

```
Slack webhook ─┐
Gmail IMAP poll ┼─> channel adapter ─> InboundEvent ─> asyncio.Queue ─> single worker (event_bus._handle_event)
/simulate/message ┘   (only job: convert)                                       │
                                                                               v
        find issue (event.issue_id, else thread link in audit_logs) ── none ──> create_issue (contact authors only)
                                                                               │      └─ audit thread.linked:<channel>:<thread>
                                                                               │      └─ triggers: kickoff "issue.created"
                                                                               v
                                                      add_message ─> status_machine.next_status ─> SLA on_status_change
                                                                               │
                                                                               v
                                                      triggers: kickoff "message.created"  ─> actions (set_status, assign_team, add_tag, send_webhook stub)

Every DB commit ─> SQLAlchemy after_commit ─> ws_manager (debounced 150 ms) ─> full snapshot to every /ws client (dashboard)
Background tasks (lifespan): event-bus worker · SLA breach checker (30 s) · Gmail poller (60 s, idle without credentials)
```

## Modules

| Path | Responsibility |
|---|---|
| `app/channels/` | Adapters. `base.InboundEvent` is the canonical shape. `manual`, `slack` (HMAC-verified webhook), `gmail` (IMAP poller), shared `contact_resolver`. Nothing downstream knows the channel. |
| `app/core/event_bus.py` | Queue + one worker. `publish` (fire and forget) / `publish_and_wait` (API callers). Thread->issue routing. |
| `app/core/issue_service.py` | The only writer of issues and messages. `create_issue`, `add_message`, `write_audit_log`. `bypass_validation` flag (default True; human writes pass False). |
| `app/core/status_machine.py` | Pure function `next_status`. Two automatic transitions only; On Hold is never auto-changed; internal notes never transition. |
| `app/triggers/` | `engine` (single pass by `position`, no re-evaluation), `conditions` (AND of equals / not_equals / contains / not_contains on dotted field paths), `actions`. |
| `app/sla/sla_engine.py` | Running/paused timer. Counts in New / On You / On Customer. Open pause start is derived from `audit_logs`. |
| `app/realtime/ws_manager.py` | `/ws` snapshot broadcaster. `dashboard/index.html` is the whole UI. |
| `app/database.py` | Async engine. `DATABASE_URL` picks SQLite (local) or Postgres (Neon); provider URLs are converted for asyncpg. |

## Invariants (do not break; tests cover them)
1. Adapters only convert to `InboundEvent` and publish. No channel-specific logic past the adapter.
2. Human writes are validated; triggers, API and adapters bypass via `bypass_validation`.
3. Every create/update writes an `audit_logs` row.
4. Triggers: one pass, ordered by `position`, never re-evaluated.
5. SLA elapsed = now - started_at - paused_seconds - open pause. All timestamps come from `app/core/clock.utcnow()` (app clock), never the DB clock.
6. Thread links live in `audit_logs` as `thread.linked:<channel>:<thread id>` (schema has no thread column).

## Known gaps v2 must fill
No authentication · single-tenant (everything lands in the first org) · no category, priority or escalation history ·
no outbound replies to Slack/Gmail · no payload column on `audit_logs` · Gmail adapter only tested with a fake IMAP server.

## v2 AI layer: Slice 1 (built) and what is still planned
Built in Slice 1:
- **Trigger action `request_ai_assist`** (seeded rule: Conversio customer messages): a rule decides when AI runs; `app/ai/queue.py` is a separate queue from the event bus, consumed by `app/ai/worker.py`.
- **Worker**: masks the conversation (`masking.py`) -> Claude via the `LLMClient` seam (`llm.py`, structured JSON) -> strict validation (`schemas.py`) -> a PENDING `ai_suggestions` row. It never writes messages, status, SLA or assignee.
- **Approval gate** (`service.py`, `/ai/suggestions/{id}/approve|reject`): the only path to a customer message; a validated human write through `issue_service.add_message`.
- **Audit**: `ai_runs` (masked prompt, raw model JSON, model, tokens, latency, correlation id, outcome) plus summary rows in `audit_logs` (`ai.requested`, `ai.run_started`, `ai.suggestion_created`, `ai.suggestion_approved|rejected|edited`, `ai.run_failed`). `ai_run_events` arrives with tool calls in Slice 3.
- **Conversio simulator**: `conversio_adapter.py` + `/conversio` chat page. Tenant, product, user and correlation id ride on `InboundEvent.context` and are stored in `issue_contexts`; approved replies show up in the chat (it polls `GET /conversio/conversations/{id}`).

```
Conversio chat -> /conversio/messages -> adapter -> event bus -> issue + message (v1 pipeline)
   -> trigger "request_ai_assist" -> AI queue -> AI worker -> ai_suggestions (pending) + ai_runs
   -> dashboard shows it -> agent edits + approves -> issue_service.add_message -> chat shows the reply
```

Built in Slice 2 (RAG):
- `app/knowledge/`: articles are chunked, **masked**, embedded (Voyage `voyage-4` behind the `Embedder` seam) and stored in `knowledge_chunks` with the embedding model name. On Postgres the column is a real pgvector `vector(1024)` ranked in SQL with `<=>`; on SQLite vectors are JSON text ranked in Python (same filters, so local dev and tests behave the same).
- Every search is filtered by organisation and product (plus articles marked `all`), returns **published** articles only and compares only vectors from the same embedding model.
- The AI worker retrieves for the customer's latest (masked) messages, adds a `<knowledge>` block to the prompt, and the model cites article ids; only ids actually retrieved are kept. Steps are logged in `ai_run_events` (`retrieval`, `retrieval_failed`, `citations`). A retrieval failure degrades to a draft without articles, never to a failed run.

```
customer message -> (masked) query embedding -> knowledge_chunks (org + product + published) -> top 4
   -> <knowledge> block in the prompt -> model drafts + cites ids -> ai_run_events + suggestion
```

Built in Slice 3 (MCP tool gateway):
- `app/mcp_servers/`: MOCK Credipay / FinSaaS / FinSaaS Lending MCP servers (fake data, read-only tools only). `app/mcp_gateway/registry.py` is the configuration: one server per product, the tool **allowlist**, and the tenant -> products map. Swapping a mock for the real server is a registry edit.
- `app/mcp_gateway/gateway.py`: the only way the AI layer reaches product systems. One MCP session per AI run; only allowlisted tools are offered or callable; a per-run call budget; masked placeholders in arguments are replaced with the real values **server-side** (never card numbers); results are masked again before the model sees them; everything is logged on the run.
- Each message carries its own context (`message_contexts`), so the worker picks the product (knowledge + tools) and correlation id of the message it answers.

```
message (tenant, product) -> AI worker -> gateway.open(tenant, product) -> offered tools = allowlist ∩ server
   model asks for a tool -> gateway: allowlist + budget -> [ACCOUNT_1] -> real value -> MCP server -> result -> masked -> model
   every step -> ai_run_events (tools_offered / tool_call / tool_denied) + audit_logs
```

Still planned: duplicate detection, category/priority-driven escalation and the metrics dashboard (Slice 4); the knowledge loop (Slice 5).

## Where the tool / MCP / playbook pieces live (a map for learning the code)

Read in this order. Line numbers drift, so search the file for the names given.

| Step | What happens | File and name to look for |
|---|---|---|
| 1 | The chat sends tenant, product and correlation id with every message | `app/schemas/conversio.py` (`ConversioMessage`), `app/channels/conversio_adapter.py` (`to_event`, the `context` dict) |
| 2 | Each message's context is saved | `app/core/event_bus.py` (`MessageContext`), model in `app/models/ai.py` |
| 3 | A trigger asks for AI help | `app/triggers/actions.py` (`_request_ai_assist`), queue in `app/ai/queue.py` |
| 4 | The AI worker picks up the job, reads the answered message's context, then **searches knowledge first** | `app/ai/worker.py` (`process_issue`, `_retrieve`), `app/knowledge/store.py` (`search`) |
| 5 | The worker opens the product's tools | `app/ai/worker.py` (`_open_tools`) calling `app/mcp_gateway/gateway.py` (`ToolGateway.open`) |
| 6 | The gateway checks the tenant, connects to the MCP server, offers only allowlisted tools | `gateway.py` (`open`, `_connect`), config in `app/mcp_gateway/registry.py` (`SERVERS`, `TENANT_PRODUCTS`, `allowed_tools`) |
| 7 | The product playbook is added to the system prompt, only if tools were offered | `registry.py` (`*_PLAYBOOK`, the `playbook` field), `worker.py` (`compose_system_prompt`, `PLAYBOOK_INTRO`) |
| 8 | The tool guidance Claude reads (when to call, no guessing, placeholders) | `worker.py` (`SYSTEM_PROMPT`, the paragraph starting "If tools are provided") |
| 9 | One request goes to Claude with the ticket, articles, tool definitions and playbook; Claude decides the tool order step by step | `app/ai/llm.py` (`AnthropicLLM.complete`, the loop on `stop_reason == "tool_use"`) |
| 10 | For each tool call: allowlist, call budget, masked placeholder swapped for the real value, call with timeout, result masked again | `gateway.py` (`ToolSession.call`, `resolve_arguments`) |
| 11 | Every step is logged on the run | `app/ai/events.py`, `worker.py` (`execute_tool`: `tool_call` / `tool_denied` events plus `ai.tool_*` audit rows) |
| 12 | The mock product servers (fake data, read-only tools) | `app/mcp_servers/credipay.py`, `finsaas.py`, `finsaas_lending.py` |
| 13 | The dashboard shows tools used | `app/realtime/ws_manager.py` (`tools`), `dashboard/index.html` (`renderAI`) |

Tool descriptions and input schemas are not written by hand: the MCP library builds them from each mock server function's name, docstring and type hints, and `gateway.py` (`ToolSession.definitions`) passes them to Claude. The final answer's JSON schema is a separate thing: `app/ai/schemas.py`.

Why the playbook is guidance and not a guarantee, and the other two ways to control tool order, are in the presentation document linked from PROGRESS.md.

## Tests
`pip install -r requirements-dev.txt`, then `pytest`. Each test runs against a fresh temp SQLite DB (see `tests/conftest.py`);
nothing touches `pylon_dummy.db` or a real `.env` database. Covers the status machine, trigger conditions/engine, SLA
timer and breaches, the event-bus pipeline with audit rows, and the REST/simulate/webhook endpoints.
