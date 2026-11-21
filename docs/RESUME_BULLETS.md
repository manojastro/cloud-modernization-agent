# Resume bullets (implemented work only, POC-labelled)

- Built a working agentic cloud-migration platform (FastAPI + SQLAlchemy 2 + NetworkX
  + vanilla-JS cockpit) that discovers a simulated 120-application enterprise estate
  from CMDB, network-flow, batch-scheduler and SFTP-transfer sources - including an
  undocumented dependency recoverable only through transfer-log/CMDB-mount correlation
  (discovery recall and precision 1.0 against machine-written ground truth).

  *POC; deterministic simulator, no real infrastructure touched.*

- Implemented a deterministic 7R migration-strategy engine as a visible ordered rules
  table (9 rules, all seven strategies reachable) with signal-based confidence,
  recorded alternatives and approval flags, plus a constraint-aware wave planner
  (topology, security zones, criticality, concurrency caps) that converts violating
  operator overrides into blocked-migration records with suggested resolutions.

  *POC; decisions validated against 12 hand-labelled applications at accuracy 1.0.*

- Delivered human-gated migration execution with persisted workflow states: 7-check
  preflight, server-enforced approval gate, fail-fast validation sequence with
  automatic rollback restoring on-prem placement while the wave continues, full
  action/outcome audit trail, allow-listed risk-gated tool registry with secret
  redaction, and Prometheus metrics.

  *POC; executed against simulated targets only.*

- Wrote a labelled evaluation harness run at seed time (ground truth as code):
  discovery recall/precision, strategy accuracy, exact blocked-set match and forced-
  rollback checks with strict 100% thresholds on the deterministic world; locked in
  by a 70-test pytest suite covering rules, planner, tools gating, workflow states,
  HTTP contract and evaluation axes.

  *POC; thresholds valid for the deterministic world, not production estates.*
