#!/usr/bin/env python
"""Execute waves 0 and 1 through the human approval gate, including the planted
wave-1 failure: 'receivables-matching-service' carries an Oracle-only feature,
fails the database_connectivity validation and is ROLLED BACK automatically
while the rest of wave 1 completes.

Deterministic; ASCII output only.

Usage:
    .venv\\Scripts\\python.exe scripts\\run_wave0_wave1_demo.py
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

from app.models import Application, MigrationExecution, ValidationResult, Wave  # noqa: E402
from app.models import WaveMembership  # noqa: E402
from simulator.generate_estate import WAVE1_INCOMPATIBLE_APP  # noqa: E402

WIDTH = 74


def rule(title: str = "", char: str = "=") -> None:
    if title:
        pad = max(2, (WIDTH - len(title) - 2) // 2)
        print(f"{char * pad} {title} {char * (WIDTH - len(title) - 2 - pad)}")
    else:
        print(char * WIDTH)


def run_wave(session, simulator, number: int) -> dict:
    rule(f"WAVE {number} EXECUTION (human approval gate)", "-")
    pre = simulator.preflight_wave(session, number)
    print(f"  preflight: {pre['PASS']} PASS / {pre['BLOCKED']} BLOCKED "
          f"across {pre['applications']} applications")

    wave = session.query(Wave).filter_by(wave_number=number).first()
    blocked_members = [
        m.member_id for m in session.query(WaveMembership)
        .filter(WaveMembership.wave_id == wave.id,
                WaveMembership.execution_status == "BLOCKED").all()
    ]
    if blocked_members:
        print(f"  blocked members (skipped this wave): {', '.join(blocked_members)}")

    print(f"  workflow state: {wave.status} -> awaiting human decision")

    decision = simulator.decide_approval(session, wave.approval_id,
                                         approve=True, decided_by="demo-operator")
    print(f"  approval #{decision.id}: {decision.status} by demo-operator")

    out = simulator.execute_wave(session, number, actor="demo-operator")
    print(f"  execution: wave -> {out['wave_status']}")
    print(f"    migrated ({len(out['completed'])}): "
          f"{', '.join(out['completed']) or '-'}")
    if out["rolled_back"]:
        print(f"    ROLLED BACK ({len(out['rolled_back'])}): "
              f"{', '.join(out['rolled_back'])}")
    return out


def main() -> int:
    from app.db import init_db, session_scope

    init_db()

    from simulator.loader import seed_estate

    with session_scope() as session:
        counts = seed_estate(session)
    print(f"estate seeded deterministically: {counts['applications']} applications")

    from app.pipeline import run_full_pipeline

    with session_scope() as session:
        summary = run_full_pipeline(session)
    print(f"pipeline: assessed {summary['applications_assessed']} apps, "
          f"{summary['dependency_edges']} edges, hidden deps found: "
          f"{summary['hidden_dependencies_found']}")

    from app.migration import simulator

    with session_scope() as session:
        out0 = run_wave(session, simulator, 0)
        out1 = run_wave(session, simulator, 1)

        rule("ROLLBACK FORENSICS", "-")
        app = session.get(Application, WAVE1_INCOMPATIBLE_APP)
        print(f"  application : {WAVE1_INCOMPATIBLE_APP} ({app.name})")
        exec_row = (session.query(MigrationExecution)
                    .filter_by(application_id=WAVE1_INCOMPATIBLE_APP)
                    .order_by(MigrationExecution.id.desc()).first())
        print(f"  execution   : status={exec_row.status}")
        validations = (session.query(ValidationResult)
                       .filter_by(execution_id=exec_row.id)
                       .order_by(ValidationResult.id).all())
        for v in validations:
            marker = "PASS" if v.status == "PASS" else "FAIL"
            print(f"    [{marker}] {v.check_name}")
            if v.status != "PASS":
                detail = str(v.detail)[:80] if v.detail else ""
                print(f"           -> {detail}")
        print(f"  placement restored to on-prem: {app.placement == 'on-prem'}")
        others_ok = len(out1["completed"])
        print(f"  wave continued despite failure: {others_ok} other members completed")

        from app.evaluation import evaluate_rollback
        import json

        truth = json.loads((ROOT / "evaluation" / "ground_truth.json").read_text("utf-8"))
        ev = evaluate_rollback(session, truth)

        rule("LABELLED EVALUATION (rollback axis)", "-")
        print(f"  pass={ev['pass']} failed_checks={ev['failed_checks']} "
              f"placement_restored={ev['placement_restored_on_prem']} "
              f"others_completed={ev['other_members_completed_count']}")

    rule("DEMO COMPLETE", "=")
    print("Wave 0: pilots migrated. Wave 1: one Oracle-coupled app failed its")
    print("database_connectivity validation and rolled back cleanly; the wave")
    print("continued. Every state change above is persisted and audited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
