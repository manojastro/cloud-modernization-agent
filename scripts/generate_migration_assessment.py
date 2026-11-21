#!/usr/bin/env python
"""Generate a full migration assessment report for the simulated estate.

Runs: seed -> agent pipeline (discover, assess, classify, plan, validate)
and prints a deterministic ASCII report to stdout.

Usage:
    .venv\\Scripts\\python.exe scripts\\generate_migration_assessment.py [size]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'cloud_modernization.db').as_posix()}")
os.environ.setdefault("LLM_MODE", "mock")

WIDTH = 74


def rule(title: str = "", char: str = "=") -> None:
    if title:
        pad = max(2, (WIDTH - len(title) - 2) // 2)
        print(f"{char * pad} {title} {char * (WIDTH - len(title) - 2 - pad)}")
    else:
        print(char * WIDTH)


def main() -> int:
    size = int(sys.argv[1]) if len(sys.argv) > 1 else None

    from app.config import get_settings
    from app.db import init_db, session_scope

    init_db()
    settings = get_settings()

    from simulator.loader import seed_estate

    with session_scope() as session:
        counts = seed_estate(session, size=size)

    rule("AUTONOMOUS CLOUD MIGRATION - ESTATE ASSESSMENT REPORT", "=")
    print(f"mode          : {'MOCK (deterministic simulation)' if settings.is_mock else 'live-llm'}")
    print(f"llm provider  : {settings.llm_mode}")
    print(f"estate size   : {counts['applications']} applications")
    print(f"inventory     : {counts['network_flows']} flows, "
          f"{counts['file_transfers']} transfers, {counts['batch_jobs']} batch jobs,")
    print(f"                {counts['cmdb_records']} CMDB records, {counts['servers']} servers")
    print(f"truth edges   : {counts['truth_edges_written']} (evaluation ground truth)")

    from app.pipeline import run_full_pipeline

    with session_scope() as session:
        summary = run_full_pipeline(session)

        rule("AGENT PIPELINE RUN", "-")
        print(f"investigation : #{summary['investigation_id']}")
        print(f"apps assessed : {summary['applications_assessed']}")
        print(f"graph edges   : {summary['dependency_edges']} correlated from all sources")
        print(f"hidden deps   : {summary['hidden_dependencies_found']} found via "
              f"transfer-log correlation")

        mix = summary["strategy_mix"]
        rule("7R STRATEGY MIX (rules table decided every one)", "-")
        for strat in ("REHOST", "REPLATFORM", "REFACTOR", "REPURCHASE",
                      "RELOCATE", "RETAIN", "RETIRE"):
            bar = "#" * min(mix.get(strat, 0), 60)
            print(f"  {strat:<11} {mix.get(strat, 0):>4}  {bar}")

        from app.models import BlockedMigration

        blocked = session.query(BlockedMigration).all()
        rule("BLOCKED MIGRATIONS (constraint solver output)", "-")
        if not blocked:
            print("  none")
        for b in blocked:
            print(f"  [{b.application_id}] {b.reason_code}")
            print(f"      detail     : {b.reason_detail[:86]}")
            print(f"      resolution : {b.suggested_resolution[:86]}")

        from app.models import Wave, WaveMembership

        waves = session.query(Wave).order_by(Wave.wave_number).all()
        rule("WAVE PLAN (constraints: topology, zones, criticality, capacity)", "-")
        for w in waves:
            members = (session.query(WaveMembership)
                       .filter(WaveMembership.wave_id == w.id,
                               WaveMembership.member_kind == "application").count())
            services = (session.query(WaveMembership)
                        .filter(WaveMembership.wave_id == w.id,
                                WaveMembership.member_kind == "service").all())
            svc_ids = ", ".join(s.member_id for s in services) or "-"
            print(f"  Wave {w.wave_number} | cap {w.max_concurrent:>3} | apps {members:>3} "
                  f"| status {w.status}")
            print(f"          services in wave: {svc_ids}")

        moves = summary["constraint_moves"]
        rule(f"CONSTRAINT PASSES ({moves} plan adjustments)", "-")
        from app.models import DomainEvent

        event = (session.query(DomainEvent)
                 .filter(DomainEvent.event_type == "waves.planned")
                 .order_by(DomainEvent.id.desc()).first())
        if event and isinstance(event.payload, dict):
            for m in event.payload.get("constraint_moves", [])[:12]:
                print(f"  {m['application_id'][:38]:<38} "
                      f"wave {m['from']} -> {m['to']}: {m['reason'][:30]}")
        else:
            print("  (detail not retained)")

        from app.models import ModernizationOpportunity, Risk

        opps = (session.query(ModernizationOpportunity)
                .order_by(ModernizationOpportunity.impact.desc()).limit(8).all())
        rule("TOP MODERNIZATION OPPORTUNITIES", "-")
        for o in opps:
            print(f"  [{o.impact.upper():<6}] {o.title[:60]}")
            print(f"           {o.application_id}: {o.description[:64]}")

        risks = (session.query(Risk)
                 .order_by(Risk.severity_score.desc()).limit(8).all())
        rule("TOP RISKS", "-")
        for r in risks:
            wave_no = f"w{r.wave_number}" if r.wave_number is not None else "--"
            print(f"  sev {r.severity_score:>2} [{wave_no}] "
                  f"{r.category:<12} {(r.application_id or 'portfolio')[:34]}")
            print(f"           mitigation: {r.mitigation[:66]}")

    rule()
    print("Assessment complete. Next: scripts/run_wave0_wave1_demo.py executes the")
    print("first two waves through the human approval gate (including a rollback).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
