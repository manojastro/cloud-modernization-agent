# Architecture

## System shape

```
                 +----------------------------------------------------------+
                 |                       frontend/ SPA                       |
                 |  static cockpit (vanilla ES modules, no CDN, dark theme)  |
                 +----------------------------|-----------------------------+
                                              | fetch /api/v1/*
                 +----------------------------v-----------------------------+
                 |                     FastAPI application                   |
                 |  routes_* -> schemas (Pydantic v2) -> services -> ORM     |
                 |  workflow state machine gates every mutating transition   |
                 +---|------------------|------------------|----------------+
                     |                  |                  |
        +------------v-----+   +--------v--------+  +------v-----------+
        | agents/          |   | tools/ registry |  | migration/       |
        | discovery, debt, |-->| 13 audited tools|->| preflight,       |
        | readiness, strat,|   | risk-gated      |  | approval gate,   |
        | planning, waves  |   | (HIGH needs OK) |  | execution+rollback|
        +-------|---------+    +-----------------+  +------------------+
                |
        +-------v----------------------+     +---------------------------+
        | graph/ dependency_graph.py   |     | llm/ provider             |
        | CMDB x flows x transfers x   |     | MockLLM (default) or any  |
        | scheduler -> NetworkX DiGraph|     | OpenAI-compatible endpoint|
        +------------------------------+     +---------------------------+

        simulator/generate_estate.py  --seed-->  SQLite (SQLAlchemy 2, 35 tables)
        evaluation/ground_truth.json  <--written at seed time
```

## The agentic pipeline (`app/pipeline.py`)

`POST /api/v1/pipeline/run` walks one persisted `Investigation` through the server
enforced state machine:

```
DETECTED -> INVESTIGATING -> DIAGNOSED -> PLANNED
```

Stages (each persisted as a `StageRun`, each narrated by the LLM layer):

1. `ApplicationDiscoveryAgent` - queries the four inventory sources via tools and
   builds the dependency graph; undocumented dependencies become `Evidence` rows.
2. `DependencyMappingAgent` - persists/refreshes `graph_edges`, exposes stats.
3. `TechnicalDebtAgent` - portfolio-wide debt index computation.
4. `CloudReadinessAgent` - per-app assessment incl. the 9-point agentic checklist
   (`AgenticReadinessItem` rows).
5. `ModernizationAgent` - indicator-driven `ModernizationOpportunity` rows.
6. `MigrationStrategyAgent` - classifies every app through the rules table tool and
   writes a `DecisionRecord` (decision, confidence, evidence ids, alternatives,
   risk level, requires_approval).
7. `WavePlanningAgent` - constraint solver producing Waves 0-3, memberships,
   `BlockedMigration` rows and a `Risk` register.
8. `ValidationAgent` - runs preflight for every wave so the UI shows readiness.

The LLM is invoked ONLY to narrate: it receives a fact list (digest-hashed) and must
restate facts. With `LLM_MODE=mock` narration is deterministic.

## Deterministic world (`simulator/`)

`generate_estate(size=120)` uses `random.Random(20260815)`. Planted showcase apps
carry stable ids and exact attribute sets:

| App | Story |
|---|---|
| `payments-api-gateway` | healthy REHOST label |
| `customer-onboarding-orchestrator` | EOL runtime REPLATFORM |
| `policy-administration-monolith` | 850k LOC, crit 5, PCI+PII -> REFACTOR, wave 3 cap |
| `legacy-report-archive` | usage 4/day, trend -85% -> RETIRE (approval required) |
| `sftp-drop-hub`, `marketing-content-cms` | commodity capability -> REPURCHASE |
| `core-ledger-batch` + 6 consumers | RETAIN mainframe; retained deps are bridgeable |
| `treasury-risk-analytics` | specialized OS deps + hypervisor -> RELOCATE |
| `warehouse-inventory-sync` -> `partner-portal` | THE hidden dependency: nightly transfer lands in partner-portal's registered drop-dir mount; discoverable only by correlating transfer logs with CMDB file shares |
| `commission-settlement-engine` | override wave 1 but anchored to shared Oracle (wave 2) -> BLOCKED `DEPENDENCY_IN_LATER_WAVE` |
| `card-dispute-tracker` | PCI app overridden into wave 1 -> BLOCKED `SECURITY_ZONE_NOT_READY` |
| `receivables-matching-service` | pinned wave 1; Oracle-only AQ feature fails validation -> ROLLED_BACK |
| `expense-capture-tool`, `feedback-survey-collector` | wave-0 pilots |

Ground truth as code: `build_true_edges()` writes `evaluation/ground_truth.json`
(true edges incl. the hidden one), strategy labels (12 apps), expected blocked set,
and the wave-1 incompatible app id. Hand labels live in `simulator/generate_estate.py`
as constants; nothing in evaluation is eyeballed after the fact.

## Wave planner (`waves/planner.py`)

- Preliminary wave from complexity/criticality/compliance/pilot eligibility, honoring
  `requested_wave_override`.
- Fixed-point constraint pass (max 25 iterations):
  - criticality-5 capped to wave 3;
  - regulated zones ready from wave 2;
  - hard topological relations (`APP_CALLS_APP`, `APP_USES_IDENTITY`, shared DB)
    must point to same-or-earlier waves; RETAINed dependencies count as `-1`
    (bridgeable on-prem);
  - concurrency caps `{0: 8, 1: 26, 2: 30, 3: unlimited}`; cheapest-first spill.
  - Operator overrides are exempt from soft capacity spills but still validated:
    violating overrides become `BlockedMigration` rows (never silently moved).
- Shared services are waved explicitly: identity/monitoring wave 0, ESB wave 1,
  SFTP hub + shared Oracle wave 2.

## Migration simulation (`migration/simulator.py`)

Wave lifecycle (persisted on `Wave.status`, enforced server-side):

```
PLANNED -> VALIDATING -> AWAITING_APPROVAL -> APPROVED -> EXECUTING
        -> VERIFYING -> COMPLETED | FAILED
(reject returns to PLANNED)
```

- Preflight: 7 checks per app (dependency availability, security zone, identity,
  database connectivity plan, capacity, security controls, rollback plan).
  Failing checks mark memberships BLOCKED before anything executes.
- Approval: an `Approval` row (PENDING -> APPROVED/REJECTED) plus `Action`/`Outcome`
  audit rows. `execute_wave` refuses non-APPROVED waves (409).
- Execution: provisional placement mutation per member, then a fail-fast validation
  sequence (app starts, API smoke test, database connectivity, dependency
  connectivity, business transaction replay for criticality >= 4, security policy,
  performance baseline within 1.25x). Any FAIL triggers automatic rollback that
  restores `placement='on-prem'`; remaining members still complete; the wave ends
  FAILED if anything rolled back.

## Tools & safety (`tools/`)

13 registered tools with JSON-ish input schemas, permission strings, risk levels and
timeouts. Every call outcome - success, refusal, unknown tool, handler error - is
audited into `ToolCall` with duration and redacted arguments (secret/token/api_key/
password values become `***redacted***`). HIGH-risk tools (`execute_wave`,
`rollback_app`) refuse unless the caller carries an approved context.

## Target architecture (`targetarch/`)

Strategy-specific target chains rendered against provider profiles for aws/azure/gcp
(naming only; no cloud SDK calls). Output is a structured spec plus optional YAML,
upserted into `TargetArchitecture`.

## Data model

35 tables including `applications`, `app_runtime_details`, `databases`, `servers`,
`network_flows`, `batch_jobs`, `file_transfers`, `cmdb_records`, `integrations`,
`shared_services`, `graph_edges`, `assessments`, `agentic_readiness_items`,
`strategy_recommendations`, `waves`, `wave_memberships`, `blocked_migrations`,
`preflight_checks`, `migration_executions`, `validation_results`,
`target_architectures`, `modernization_opportunities`, `risks`, `events`,
`investigations`, `stage_runs`, `evidence`, `decisions`, `approvals`, `actions`,
`outcomes`, `metric_snapshots`, `evaluation_runs`, `tool_calls`.

SQLite default (WAL + foreign keys ON). Relative sqlite URLs are anchored to the
project root so the server can start from any cwd. PostgreSQL works unchanged via
`DATABASE_URL` (psycopg driver installed).

## Frontend

Static SPA served by FastAPI's StaticFiles at `/`. Vanilla ES module, zero CDN, dark
cockpit theme, amber MOCK MODE badge from `/api/v1/meta`. Panels: portfolio table with
filters, mix donut, dependency map SVG (hidden dep dashed amber), agentic heatmap,
debt board, readiness checklist viewer, wave cards with approve/reject/execute
buttons, blocked panel, progress bars with rolled-back callout, target architecture
viewer with provider switcher and YAML toggle, opportunities, risks, audit trail.
