# Interview guide - Project 15

## 60-second pitch

"Enterprises never have an accurate map of their own estate, and migration waves fail
on exactly the things nobody documented. I built a working agentic platform that
discovers the estate by correlating four independent sources, assesses every app -
including how ready its interface is for AI agents to operate - classifies it into a
7R strategy through a visible rules table, plans constraint-aware waves with a human
approval gate, executes them against a simulated target with validation gates and
automatic rollback, and evaluates itself against ground truth written at seed time.
It scores 100% on all labelled axes and 70 tests pass. The LLM narrates; it never
decides."

## Questions you should expect (and honest answers)

**Why does the LLM not pick strategies?**
Determinism and auditability. Every strategy cites a rule id from an ordered table;
confidence is computed from matched signals; alternatives are recorded. The LLM only
narrates decided facts. This is also what makes the labelled evaluation meaningful.

**How is the hidden dependency found?**
A nightly file transfer's remote path lands inside another application's registered
drop-dir mount. Neither CMDB nor flow logs show it. `correlate_transfer_logs` matches
transfer paths against CMDB share mounts (owner != sender) and emits an
APP_SENDS_FILE_TO edge with discovered_by=transfer-log-correlation plus an Evidence row.

**How do constraints work in wave planning?**
Preliminary assignment from complexity/criticality/compliance/pilot eligibility, then
a fixed-point pass: regulated zones not before wave 2, crit-5 capped to wave 3, hard
topological relations must point same-or-earlier, RETAINed deps count as bridgeable
(-1), concurrency caps per wave. Operator overrides are honored but validated -
violations become BlockedMigration records with suggested resolutions instead of
silent moves.

**What happens when a migration fails mid-wave?**
Fail-fast validation sequence per app; failure triggers automatic rollback restoring
the on-prem placement while remaining members continue. The wave ends FAILED if
anything rolled back. The planted case: an Oracle-only AQ callback package that no
managed database can satisfy - caught at database_connectivity validation in wave 1.

**Where does this touch real clouds?**
Nowhere - deliberately. Provider profiles are naming templates for aws/azure/gcp over
a structured spec. The point of the POC is the agentic control plane, not cloud APIs.

**What would productionizing require?**
Alembic migrations, real auth on the API, append-only audit store, streaming progress
(SSE/WebSocket), fuzzy matching for noisy discovery, resource leveling beyond static
wave caps, real preflight probes against target environments.

## Numbers to quote

- 120-app deterministic estate, 4 sources correlated, 1168 graph edges, 9 relation types
- 427 truth edges incl. 1 hidden dependency; recall/precision both 1.0
- 12 hand-labelled strategies, accuracy 1.0; exact blocked-set match
- Waves 0-3 with ~129 constraint adjustments; exactly 2 blocked apps
- Wave 1: 6 completed + 1 forced rollback; placement restored automatically
- 70 tests passing; Prometheus metrics on /metrics

## Demo flow

See DEMO.md - the cockpit walkthrough hits discovery, determinism, human gate,
rollback, provider templates, and metrics in about five minutes.
