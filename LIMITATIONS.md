# Limitations (honest scope)

This is a portfolio-grade POC of an agentic migration platform. It is deliberately a
simulation; the following are real boundaries, not hidden gaps.

## Simulation vs reality

- The estate is synthetic (seeded RNG). Costs, latencies, server counts and the
  0.82 cloud-cost factor are illustrative models, not measured data.
- "Execution" mutates `applications.placement` and runs modeled validation checks.
  No real VMs, databases or network zones are touched. No cloud provider is called -
  aws/azure/gcp profiles are naming templates only.
- The hidden dependency is planted by construction to prove the correlation engine;
  real discovery would surface many more partial/ambiguous signals than this world
  contains.

## LLM layer

- Default is a deterministic mock narrator. The optional OpenAI-compatible mode
  narrates facts only and is not exercised by tests against a live model (no network
  in tests); prompt quality for real models is unvalidated.
- Narration is decorative by design: decisions come from deterministic code.

## Engineering trims (documented, deliberate)

- **create_all instead of Alembic**: schema changes drop/recreate in tests via
  reset_db(). Fine for a POC; production would need migrations.
- **SQLite default** with WAL; sessions use autoflush=False with explicit flush
  boundaries where bare FK insert ordering matters. PostgreSQL supported but only
  SQLite is exercised in CI/tests here.
- **Static vanilla SPA** rather than React/Vue: zero build tooling, zero CDN deps;
  tradeoff is hand-rolled rendering and no virtualization for very large tables.
- **Single-user demo API**: no authentication/authorization on HTTP endpoints yet,
  no rate limiting, no CSRF story; the approval gate is workflow-level, not a login
  system. Audit rows live in the same DB, not an append-only external store.
- Capacity model is linear (4 vCPU / 16 GB per server) with crude replica bounds;
  performance validation uses a deterministic jittered latency model within 1.25x
  tolerance - it can fail apps only via the planted database check in practice.
- Wave concurrency caps {8, 26, 30} are constants; no calendar/resource leveling.
- Evaluation thresholds are 100% because the world is deterministic and small;
  precision/recall on noisy real-world estates would need fuzzy matching and human
  review queues that are out of scope.
- `pytest` suite (~43 s) reseeds per test; no parallelization tuning.
- Docker image validated locally with compose; no registry push, no multi-arch build.

## Known cosmetic notes

- Preflight BLOCKED members remain listed in their wave (skipped at execution) so
  operators see why they were excluded; they do not silently disappear.
- Operator-overridden apps are exempt from soft capacity spills, so a wave can
  exceed its nominal cap when overrides pin extra work into it (hard constraints
  still block violations).
