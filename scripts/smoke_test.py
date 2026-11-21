"""Smoke test: bootstrap paths, import everything, seed, run pipeline (throwaway)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'cloud_modernization.db'}")

from app.db import init_db, session_scope  # noqa: E402


def main() -> int:
    init_db()
    from simulator.loader import seed_estate

    with session_scope() as session:
        counts = seed_estate(session)
        print("seed:", {k: counts[k] for k in ("applications", "network_flows", "file_transfers")})

        from app.pipeline import run_full_pipeline

        summary = run_full_pipeline(session)
        print("pipeline keys:", sorted(summary.keys()))
        print("apps assessed:", summary["applications_assessed"])
        print("edges:", summary["dependency_edges"])
        print("hidden found:", summary["hidden_dependencies_found"])
        print("strategy mix:", summary["strategy_mix"])
        print("blocked:", [b["application_id"] for b in summary["blocked_detail"]])
        print("constraint moves:", summary["constraint_moves"])

        from app.evaluation import evaluate_discovery

        truth = __import__("json").loads(
            (ROOT / "evaluation" / "ground_truth.json").read_text(encoding="utf-8"))
        d = evaluate_discovery(session, truth)
        print("discovery recall/precision:", d["recall"], d["precision"],
              "hidden:", d["hidden_dependency_found"])
        if d["missing_examples"]:
            print("missing examples:", d["missing_examples"][:10])
        if d["unexpected_examples"]:
            print("unexpected examples:", d["unexpected_examples"][:10])

        s = __import__("app.evaluation", fromlist=["evaluate_strategies"]).evaluate_strategies(
            session, truth)
        print("strategy accuracy:", s["accuracy"], s.get("mismatches"))

        b = __import__("app.evaluation", fromlist=["evaluate_blocked"]).evaluate_blocked(
            session, truth)
        print("blocked match:", b["match"], b["actual"])

        # execute wave 0 + 1 with auto-approval to prove rollback story
        from app.migration import simulator

        w1 = __import__("app.models", fromlist=["Wave"]).Wave
        wave0 = session.query(w1).filter_by(wave_number=0).first()
        simulator.preflight_wave(session, 0)
        simulator.decide_approval(session, wave0.approval_id, approve=True,
                                  decided_by="smoke")
        r0 = simulator.execute_wave(session, 0, actor="smoke")
        print("wave0:", r0["wave_status"], "completed:", len(r0["completed"]),
              "rolled_back:", r0["rolled_back"])

        wave1 = session.query(w1).filter_by(wave_number=1).first()
        if wave1.status == "PLANNED":
            simulator.preflight_wave(session, 1)
        wave1 = session.query(w1).filter_by(wave_number=1).first()
        if wave1.status != "APPROVED":
            simulator.decide_approval(session, wave1.approval_id, approve=True,
                                      decided_by="smoke")
        r1 = simulator.execute_wave(session, 1, actor="smoke")
        print("wave1:", r1["wave_status"], "completed:", len(r1["completed"]),
              "rolled_back:", r1["rolled_back"])

        ev = __import__("app.evaluation", fromlist=["evaluate_rollback"]).evaluate_rollback(
            session, truth)
        print("rollback eval pass:", ev["pass"], ev.get("failed_checks"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
