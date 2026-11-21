# Demo script (5 minutes)

## 0. Setup

```powershell
cd "D:\ai apps dump\claude code project\enterprise-agentic-ai-portfolio-batch-3\15-cloud-modernization-agent"
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8015
```

Open http://127.0.0.1:8015/ - the cockpit loads with the amber MOCK MODE badge.

## 1. The estate and the hidden dependency

- Click **Seed estate** then **Run pipeline** (or run the two scripts in README).
- Portfolio panel: ~120 applications with strategy chips, readiness bands, debt.
- Dependency map panel: switch "hidden deps only" on. Exactly one dashed amber edge:
  `warehouse-inventory-sync -> partner-portal`, relation APP_SENDS_FILE_TO,
  discovered_by `transfer-log-correlation`. It is in NO CMDB record and no flow log -
  it only exists as a nightly SFTP drop landing inside partner-portal's registered
  mount.

Talking point: multi-source correlation finds what documentation misses; each
discovery becomes an Evidence row with provenance.

## 2. Deterministic decisions

- Mix donut: all seven 7R strategies appear; every classification cites its rule id.
- Blocked panel shows exactly two apps with reason codes and suggested resolutions:
  - commission-settlement-engine / DEPENDENCY_IN_LATER_WAVE (pinned wave 1 but
    anchored to shared Oracle which migrates in wave 2);
  - card-dispute-tracker / SECURITY_ZONE_NOT_READY (PCI override before zones exist).
- Tech debt board + agentic heatmap: click any cell to inspect its checklist.

## 3. Human-gated execution with automatic rollback

Wave cards show persisted workflow states. Walk wave 1:

1. Preflight already ran in the pipeline -> status AWAITING_APPROVAL.
2. Press **Approve** (persisted approval row; audited).
3. Press **Execute**. Watch: most members turn COMPLETED, but
   `receivables-matching-service` FAILS the database_connectivity validation
   (planted Oracle-only AQ feature) and turns ROLLED_BACK. Wave ends FAILED while its
   peers stay migrated. Migration progress shows the rolled-back callout.

Talking point: the failure is by design - a pre-existing incompatibility that only a
validation gate can catch. Rollback restores on-prem placement automatically; nothing
else in the wave is disturbed.

## 4. Provider-neutral target architecture

Target arch panel: pick `policy-administration-monolith`, flip provider aws ->
azure -> gcp and toggle YAML. Same structured intent, different provider naming. No
cloud calls anywhere.

## 5. Proof

```powershell
.venv\Scripts\python.exe scripts\run_wave0_wave1_demo.py   # rollback forensics
curl http://127.0.0.1:8015/metrics | findstr cma_          # Prometheus metrics
.venv\Scripts\python.exe -m pytest tests -q                # 70 passed
```

`GET /api/v1/evaluation/latest` shows the last labelled run: recall 1.0, precision
1.0, strategy accuracy 1.0, blocked exact match, rollback pass.

## CLI alternatives

- `scripts/generate_migration_assessment.py` - full ASCII assessment report.
- `scripts/run_wave0_wave1_demo.py` - waves 0+1 incl. rollback forensics.
