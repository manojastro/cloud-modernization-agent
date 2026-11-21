"""Labeled evaluation suite.

Compares system behaviour against the authored/machine-generated ground truth in
evaluation/ground_truth.json:

(a) dependency-discovery recall/precision vs the full true edge set;
(b) 7R strategy accuracy over hand-labeled applications;
(c) expected blocked-migration set must match exactly;
(d) the planted wave-1 incompatible app must FAIL + ROLL_BACK (never silently succeed).

The world is deterministic, so honest thresholds are 100% on every axis.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.graph.dependency_graph import REL_TRUTH
from app.models import (
    Application, BlockedMigration, DomainEvent, EvaluationRun, GraphEdge,
    MigrationExecution, StrategyRecommendation, ValidationResult, Wave,
    WaveMembership,
)

# <root>/evaluation/ground_truth.json  (this file is <root>/backend/app/evaluation.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH_PATH = PROJECT_ROOT / "evaluation" / "ground_truth.json"


def _load_truth() -> dict:
    return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


def evaluate_discovery(session: Session, truth: dict) -> dict:
    rows = session.query(GraphEdge).filter(GraphEdge.relation.in_(REL_TRUTH)).all()
    discovered = {(r.src, r.dst, r.relation) for r in rows}
    truth_set = {tuple(e) for e in truth["true_edges"]}
    overlap = truth_set & discovered
    recall = len(overlap) / len(truth_set) if truth_set else 0.0
    precision = len(overlap) / len(discovered) if discovered else 0.0
    hd = truth["hidden_dependency"]
    hidden_found = (hd["source_app"], hd["target_app"], hd["relation"]) in discovered
    missing = sorted(truth_set - discovered)[:25]
    unexpected = sorted(discovered - truth_set)[:25]
    return {
        "truth_edges": len(truth_set),
        "discovered_edges": len(discovered),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "hidden_dependency_found": hidden_found,
        "missing_examples": [list(e) for e in missing],
        "unexpected_examples": [list(e) for e in unexpected],
    }


def evaluate_strategies(session: Session, truth: dict) -> dict:
    recs = {r.application_id: r.strategy for r in
            session.query(StrategyRecommendation).all()}
    correct = 0
    total = 0
    mismatches = []
    for label in truth["strategy_labels"]:
        total += 1
        actual = recs.get(label["application"])
        if actual == label["expected"]:
            correct += 1
        else:
            mismatches.append({"application": label["application"],
                               "expected": label["expected"], "actual": actual})
    accuracy = correct / total if total else 0.0
    return {"accuracy": round(accuracy, 4), "correct": correct,
            "total": total, "mismatches": mismatches}


def evaluate_blocked(session: Session, truth: dict) -> dict:
    actual = sorted({b.application_id for b in session.query(BlockedMigration).all()})
    expected = sorted(set(truth["expected_blocked_migrations"]))
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    return {
        "expected": expected, "actual": actual,
        "missing": missing, "unexpected": unexpected,
        "match": not missing and not unexpected,
    }


def ensure_wave_executed(session: Session, wave_number: int, actor: str) -> None:
    """Approve + execute a wave if it has not run yet (evaluation auto-operator)."""
    from app.migration import simulator
    from app.workflow.engine import WorkflowViolation

    wave = session.query(Wave).filter(Wave.wave_number == wave_number).first()
    if wave is None:
        raise RuntimeError(f"wave {wave_number} not found")
    if wave.status in ("COMPLETED", "FAILED"):
        return
    try:
        simulator.preflight_wave(session, wave_number)
    except WorkflowViolation:
        pass  # already validated/approved earlier in this flow
    approval_id = wave.approval_id
    if wave.status != "APPROVED":
        if not approval_id:
            raise RuntimeError(f"wave {wave_number}: no approval request present")
        simulator.decide_approval(session, approval_id, approve=True,
                                  decided_by="evaluation-auto-operator",
                                  comment="automated evaluation operator (simulated)")
    simulator.execute_wave(session, wave_number, actor=actor)


def evaluate_rollback(session: Session, truth: dict) -> dict:
    app_id = truth["wave1_incompatible_app"]
    execs = (session.query(MigrationExecution)
             .filter(MigrationExecution.application_id == app_id).all())
    if not execs:
        return {"pass": False, "detail": f"no migration executions for {app_id}; "
                                         "wave 1 has not been executed"}
    latest = max(execs, key=lambda e: e.id)
    validations = (session.query(ValidationResult)
                   .filter(ValidationResult.execution_id == latest.id)
                   .order_by(ValidationResult.sequence_no).all())
    failed_checks = [v.check_name for v in validations if v.status == "FAIL"]

    app = session.get(Application, app_id)
    wave = session.query(Wave).filter(Wave.wave_number == 1).first()

    others_completed: list[str] = []
    others_rolled_back: list[str] = []
    if wave is not None:
        for membership in (session.query(WaveMembership)
                           .filter(WaveMembership.wave_id == wave.id,
                                   WaveMembership.member_kind == "application").all()):
            if membership.member_id == app_id:
                continue
            execution = (session.query(MigrationExecution)
                         .filter(MigrationExecution.application_id == membership.member_id)
                         .order_by(MigrationExecution.id.desc()).first())
            if execution is None:
                continue
            if execution.status == "COMPLETED":
                others_completed.append(membership.member_id)
            elif execution.status == "ROLLED_BACK":
                others_rolled_back.append(membership.member_id)

    ok = bool(
        latest.status == "ROLLED_BACK"
        and failed_checks
        and app is not None and app.placement == "on-prem"
        and len(others_completed) > 0
        and not others_rolled_back
    )
    return {
        "pass": ok,
        "application": app_id,
        "execution_status": latest.status,
        "failed_checks": failed_checks,
        "placement_restored_on_prem": bool(app and app.placement == "on-prem"),
        "wave_status": wave.status if wave else None,
        "other_members_completed_count": len(others_completed),
        "other_members_rolled_back": others_rolled_back,
    }


def run_evaluation(session: Session, actor: str = "evaluation") -> dict:
    truth = _load_truth()

    discovery = evaluate_discovery(session, truth)
    strategy = evaluate_strategies(session, truth)
    blocked = evaluate_blocked(session, truth)

    passed = bool(
        discovery["recall"] >= 1.0
        and discovery["precision"] >= 1.0
        and discovery["hidden_dependency_found"]
        and strategy["accuracy"] >= 1.0
        and blocked["match"]
    )
    rollback_block: dict | None = None
    if passed:
        # only run migrations once discovery/classification/planning are proven exact
        ensure_wave_executed(session, 0, actor=actor)
        ensure_wave_executed(session, 1, actor=actor)
        rollback_block = evaluate_rollback(session, truth)
        passed = bool(rollback_block.get("pass"))

    results = {
        "discovery": discovery,
        "strategy": strategy,
        "blocked": blocked,
        "rollback": rollback_block or {
            "pass": False, "detail": "skipped: upstream checks failed"},
        "thresholds": {
            "discovery_recall_min": 1.0, "discovery_precision_min": 1.0,
            "strategy_accuracy_min": 1.0, "blocked_set": "exact-match",
            "wave1_incompatible_app": "must fail validation and roll back",
        },
    }
    run = EvaluationRun(passed=bool(passed), results=results)
    session.add(run)
    session.flush()
    session.add(DomainEvent(event_type="evaluation.run", subject=f"run-{run.id}",
                            payload={"passed": bool(passed)}))
    return {"run_id": run.id, "passed": bool(passed), "results": results}
