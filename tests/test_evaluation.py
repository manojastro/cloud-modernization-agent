"""Labeled evaluation: the deterministic world must score 100% on every axis."""
import json
from pathlib import Path

from simulator.generate_estate import WAVE1_INCOMPATIBLE_APP
from app.evaluation import (
    ensure_wave_executed,
    evaluate_blocked,
    evaluate_discovery,
    evaluate_rollback,
    evaluate_strategies,
    run_evaluation,
)
from app.pipeline import run_full_pipeline

ROOT = Path(__file__).resolve().parents[1]


def _truth():
    return json.loads((ROOT / "evaluation" / "ground_truth.json").read_text("utf-8"))


def test_discovery_recall_precision_are_perfect(planned):
    session, _ = planned
    d = evaluate_discovery(session, _truth())
    assert d["recall"] == 1.0, d["missing_examples"][:5]
    assert d["precision"] == 1.0, d["unexpected_examples"][:5]
    assert d["hidden_dependency_found"] is True


def test_strategy_accuracy_is_perfect(planned):
    session, _ = planned
    s = evaluate_strategies(session, _truth())
    assert s["total"] >= 10, "at least 10 hand-labeled applications required"
    assert s["accuracy"] == 1.0, s["mismatches"]


def test_blocked_set_matches_exactly(planned):
    session, _ = planned
    b = evaluate_blocked(session, _truth())
    assert b["match"] is True, {"expected": b["expected"], "actual": b["actual"]}
    assert set(b["actual"]) == {"commission-settlement-engine", "card-dispute-tracker"}


def test_wave1_incompatible_app_is_forced_to_roll_back(planned):
    session, _ = planned
    truth = _truth()
    assert truth["wave1_incompatible_app"] == WAVE1_INCOMPATIBLE_APP

    ensure_wave_executed(session, 1, actor="evaluation")
    session.commit()
    r = evaluate_rollback(session, truth)
    assert r["pass"] is True, r
    assert r["application"] == WAVE1_INCOMPATIBLE_APP
    assert r["execution_status"] == "ROLLED_BACK"
    assert "database_connectivity" in r["failed_checks"]
    assert r["placement_restored_on_prem"] is True
    assert r["other_members_completed_count"] > 0
    assert r["other_members_rolled_back"] == []


def test_full_evaluation_passes(planned):
    session, _ = planned
    result = run_evaluation(session, actor="evaluation")
    session.commit()
    assert result["passed"] is True, json.dumps(result["results"], default=str)[:2000]
    assert result["results"]["discovery"]["recall"] == 1.0
    assert result["results"]["strategy"]["accuracy"] == 1.0
    assert result["results"]["blocked"]["match"] is True
    assert result["results"]["rollback"]["pass"] is True


def test_run_is_persisted(planned):
    session, _summary = planned
    run_evaluation(session, actor="evaluation")
    session.commit()

    from app.models import EvaluationRun

    rows = session.query(EvaluationRun).all()
    assert rows and rows[-1].passed is True
