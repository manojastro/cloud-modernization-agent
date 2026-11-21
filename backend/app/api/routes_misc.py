"""Opportunities, risks, audit trail, metrics summary and evaluation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.evaluation import (
    evaluate_blocked, evaluate_discovery, evaluate_strategies, run_evaluation,
)
from app.models import (
    Action, Assessment, BlockedMigration, DomainEvent, EvaluationRun,
    ModernizationOpportunity, Risk, ToolCall,
)
from app.pipeline import pct_off_eol_runtime_post_plan
from app.schemas import MetricsSummaryResponse, OpportunityOut, RiskOut

router = APIRouter(prefix="/api/v1", tags=["ops"])


@router.post("/pipeline/run")
def run_pipeline_endpoint(actor: str = Query(default="operator"),
                          db: Session = Depends(get_db)) -> dict:
    """Run the full agentic pipeline: discover, assess, classify, plan, validate.

    Requires a seeded estate (POST /api/v1/simulator/seed first).
    """
    from app.models import Application
    from app.pipeline import run_full_pipeline

    if db.query(Application).count() == 0:
        raise HTTPException(status_code=409, detail="estate is empty; seed first")
    try:
        return run_full_pipeline(db)
    except Exception as exc:  # noqa: BLE001 - surfaced as a safe 500
        raise HTTPException(status_code=500, detail=f"pipeline failed: {exc}")


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(impact: str | None = None,
                       limit: int = Query(default=200, ge=1, le=1000),
                       db: Session = Depends(get_db)) -> list[OpportunityOut]:
    q = db.query(ModernizationOpportunity)
    if impact:
        q = q.filter(ModernizationOpportunity.impact == impact)
    rows = q.limit(limit).all()
    return [OpportunityOut(id=o.id, application_id=o.application_id, title=o.title,
                           category=o.category, impact=o.impact, effort=o.effort,
                           description=o.description) for o in rows]


@router.get("/risks", response_model=list[RiskOut])
def list_risks(db: Session = Depends(get_db),
               wave_number: int | None = None) -> list[RiskOut]:
    q = db.query(Risk).order_by(Risk.severity_score.desc())
    if wave_number is not None:
        q = q.filter(Risk.wave_number == wave_number)
    return [RiskOut(id=r.id, application_id=r.application_id,
                    wave_number=r.wave_number, category=r.category,
                    description=r.description, likelihood=r.likelihood,
                    impact=r.impact, severity_score=r.severity_score,
                    mitigation=r.mitigation) for r in q.all()]


@router.get("/audit/actions")
def audit_actions(limit: int = Query(default=100, ge=1, le=500),
                  db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Action).order_by(Action.id.desc()).limit(limit).all()
    return [{"id": a.id, "ts": a.ts, "actor": a.actor,
             "action_type": a.action_type, "target": a.target,
             "high_risk": a.high_risk, "status": a.status} for a in rows]


@router.get("/audit/tool-calls")
def audit_tool_calls(limit: int = Query(default=100, ge=1, le=500),
                     db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ToolCall).order_by(ToolCall.id.desc()).limit(limit).all()
    return [{"id": t.id, "ts": t.ts, "tool_name": t.tool_name, "caller": t.caller,
             "risk_level": t.risk_level, "allowed": t.allowed,
             "duration_ms": t.duration_ms, "result_summary": t.result_summary[:200],
             "error": t.error} for t in rows]


@router.get("/audit/events")
def audit_events(limit: int = Query(default=100, ge=1, le=500),
                 db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(DomainEvent).order_by(DomainEvent.id.desc()).limit(limit).all()
    return [{"id": e.id, "ts": e.ts, "event_type": e.event_type,
             "subject": e.subject, "payload": e.payload} for e in rows]


def _safe_discovery_metrics(db: Session) -> tuple[float | None, float | None, bool | None]:
    try:
        d = evaluate_discovery(db, _truth())
        return d["recall"], d["precision"], d["hidden_dependency_found"]
    except Exception:  # noqa: BLE001 - ground truth may not exist yet
        return None, None, None


def _truth() -> dict:
    from app.evaluation import _load_truth

    return _load_truth()


@router.get("/metrics-summary", response_model=MetricsSummaryResponse)
def metrics_summary(db: Session = Depends(get_db)) -> MetricsSummaryResponse:
    recall, precision, hidden_found = _safe_discovery_metrics(db)

    strategy_accuracy = None
    try:
        strategy_accuracy = evaluate_strategies(db, _truth())["accuracy"]
    except Exception:  # noqa: BLE001
        pass

    from sqlalchemy import func

    from app.models import MigrationExecution

    status_counts = dict(
        db.query(MigrationExecution.status, func.count(MigrationExecution.id))
        .group_by(MigrationExecution.status).all()
    )
    completed = status_counts.get("COMPLETED", 0)
    rolled_back = status_counts.get("ROLLED_BACK", 0)
    total_finished = completed + rolled_back
    success_rate = round(completed / total_finished, 4) if total_finished else None

    last_eval = (db.query(EvaluationRun).order_by(EvaluationRun.id.desc()).first())

    blocked_count = db.query(BlockedMigration).count()
    return MetricsSummaryResponse(
        applications_assessed=db.query(Assessment).count(),
        discovery_recall=recall,
        discovery_precision=precision,
        hidden_dependency_found=hidden_found,
        strategy_accuracy=strategy_accuracy,
        blocked_migrations_identified=blocked_count,
        wave_conflicts_prevented=blocked_count,
        modernization_opportunities=db.query(ModernizationOpportunity).count(),
        pct_apps_off_eol_runtime_post_plan=pct_off_eol_runtime_post_plan(db),
        migration_success_rate=success_rate,
        rollback_count=rolled_back,
        evaluation_passed=last_eval.passed if last_eval else None,
        last_evaluation_at=last_eval.ts if last_eval else None,
    )


@router.post("/evaluation/run")
def evaluation_run(db: Session = Depends(get_db)) -> dict:
    if db.query(Assessment).count() == 0:
        raise HTTPException(status_code=409,
                            detail="portfolio not assessed yet; run POST "
                                   "/api/v1/assessment/run first")
    try:
        return run_evaluation(db, actor="api-evaluation")
    except Exception as exc:  # noqa: BLE001 - surfaced as safe error
        raise HTTPException(status_code=500,
                            detail=f"evaluation failed: {type(exc).__name__}")


@router.get("/evaluation/latest")
def evaluation_latest(db: Session = Depends(get_db)) -> dict:
    row = db.query(EvaluationRun).order_by(EvaluationRun.id.desc()).first()
    if row is None:
        raise HTTPException(status_code=404, detail="no evaluation runs yet")
    return {"run_id": row.id, "ts": row.ts, "passed": row.passed,
            "results": row.results}
