# Security posture (POC scope)

## Human-in-the-loop by construction

- Wave execution is gated by a persisted `approvals` row. `execute_wave` refuses
  anything not in `APPROVED` state with HTTP 409; the state machine itself forbids
  `AWAITING_APPROVAL -> EXECUTING`.
- Rejecting returns the wave to `PLANNED` without touching any placement.
- HIGH-risk tools (`execute_wave`, `rollback_app`) refuse calls whose
  `ToolContext.approved` is False - agents cannot bypass the gate by construction.

## Allow-listed, audited tools

- Agents can only call tools registered in the registry (13). Unknown tool names are
  refused AND audited. No shell/subprocess tools exist anywhere in this repo.
- Every tool outcome is written to `tool_calls` with caller, risk level, duration,
  redacted arguments and a result summary.
- Arguments are validated against per-tool schemas before any handler runs;
  secret-looking keys (`secret`, `token`, `api_key`, `password`) are redacted to
  `***redacted***` before persistence.

## LLM containment

- The default provider is `MockLLM`: deterministic, facts-only narration.
- The optional `openai-compatible` mode sends only the fact block plus a task prompt,
  temperature 0. The system prompt forbids adding numbers/products/claims. The LLM
  NEVER chooses strategies, waves or approvals - every decision path is deterministic
  code, and decisions cite rule ids and evidence ids.
- API keys are read from env (`LLM_API_KEY`), never logged, never echoed in errors.

## Workflow integrity

- All transitions validated against an allow-list map (`workflow/engine.py`).
  Illegal jumps raise `WorkflowViolation` -> HTTP 409.
- Every decision carries provenance: `Evidence` rows for discovered dependencies,
  `DecisionRecord` rows for strategies, `Action`/`Outcome` rows for approvals and
  executions, `events` table for domain events.

## Web surface

- Pydantic v2 request validation on all POST bodies; query parameters bounded
  (`limit<=400`, enum-constrained `provider`/`format`); unknown sort keys -> 422.
- Exception handlers return safe messages; stack traces stay in logs, never in HTTP
  responses.
- CORS is an explicit env allow list (`CORS_ORIGINS`), no wildcard by default.
- Static SPA served from its own directory; no server-side templating of user input.

## Data

- SQLite file lives under `<project>/data/`; secrets never touch the database.
- `.gitignore` excludes `data/`, `.venv/`, caches.

## Honest limitations

This is a simulation POC: there is no real authentication on the API yet, no rate
limiting, no TLS termination (assume a reverse proxy), and audit rows live in the same
database rather than an append-only store. See LIMITATIONS.md.
