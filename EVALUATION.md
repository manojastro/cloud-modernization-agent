# Evaluation

All numbers below are measured on this machine (Python 3.11, Windows, estate size
120) with the deterministic simulator. Reproduce with:

```powershell
.venv\Scripts\python.exe scripts\run_wave0_wave1_demo.py   # prints the rollback axis
.venv\Scripts\python.exe -m pytest tests/test_evaluation.py -q
```

or via the API: `POST /api/v1/evaluation/run`.

## Ground truth as code

`evaluation/ground_truth.json` is written at seed time by the simulator itself:

- `true_edges`: every real relation in the generated world (427 edges at size 120),
  including the hidden `warehouse-inventory-sync -> partner-portal` file dependency;
- `strategy_labels`: 12 hand-labeled applications spanning all seven strategies;
- `expected_blocked_migrations`: exactly `commission-settlement-engine`
  (dependency in later wave) and `card-dispute-tracker` (security zone not ready);
- `wave1_incompatible_app`: `receivables-matching-service`.

Because the world is deterministic, thresholds are honest: **100% required** on every
axis. A failure means the logic is broken - never a loosened threshold.

## Measured results (estate size 120)

| Axis | Threshold | Measured |
|---|---|---|
| Discovery recall vs true edges | = 1.0 | **1.0** (0 missing of 427) |
| Discovery precision | = 1.0 | **1.0** (0 unexpected of 1168 persisted edges; inventory relations excluded from truth scope by design) |
| Hidden FTP dependency found | True | **True** (`discovered_by=transfer-log-correlation`) |
| Strategy accuracy vs 12 labels | = 1.0 | **1.0**, 0 mismatches |
| Blocked set exact match | exact | **True**: {commission-settlement-engine: DEPENDENCY_IN_LATER_WAVE, card-dispute-tracker: SECURITY_ZONE_NOT_READY} |
| Wave-1 incompatible app forced rollback | pass | **pass=True**: execution ROLLED_BACK, failed check `database_connectivity`, placement restored to on-prem, 6 wave peers completed, no peer rolled back |
| Overall evaluation run | passed | **passed=True** |

## Pipeline facts (same run)

- 120 applications assessed; 1168 graph edges persisted across 9 relation types.
- Strategy mix: REHOST 45, REPLATFORM 63, REFACTOR 4, REPURCHASE 2, RELOCATE 3,
  RETAIN 2, RETIRE 1 (all seven reachable).
- Constraint passes: ~129 plan adjustments (topological deferrals dominate), 2 blocks.
- Wave composition after planning: w0 = 3 apps + identity/monitoring services,
  w1 = 12 apps + ESB (+ pinned receivables app), w2 = 17 apps + SFTP hub/shared
  Oracle, w3 = 83 apps.
- Execution through the demo script: wave 0 COMPLETED (2 migrated; 1 member blocked
  at preflight for hardcoded secrets); wave 1 FAILED overall with exactly one
  automatic rollback and 6 members COMPLETED.

## What the tests lock down (70 tests)

- every one of the 9 rules reachable / first-match semantics / confidence bounds /
  approval flags;
- debt index indicator math; agentic checklist scoring bands incl. boundaries;
- capacity estimator math; latency tolerance boundary (1.25x);
- hidden-dependency correlation; CMDB/flow edge extraction; dedupe/persistence;
- blocked reason codes; pinned override placement; pilots in wave 0; service waves;
  RETAIN off the train; capacity cap respected for non-overridden apps;
- tool allow-list, HIGH-risk refusal without approval, argument validation,
  secret redaction in audit rows;
- MockLLM determinism and facts-only narration; discovery agent evidence trail;
- state machine gate enforcement; reject-touches-nothing; execute-requires-approval;
  planted rollback story end to end; preflight idempotency;
- HTTP contract: meta badge, seed bounds, portfolio filters/sorts/422s, graph hidden
  edge, assessments, visible rules table, full approval->execute lifecycle over HTTP,
  target architecture for all three providers, evaluation endpoint gating;
- labelled evaluation axes all green.

## Known non-goals

The evaluator measures this closed world only; it is not a claim about production
migration outcomes. See LIMITATIONS.md.
