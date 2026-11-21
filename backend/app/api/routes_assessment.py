"""Assessment queries and the full pipeline run endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Assessment
from app.pipeline import run_full_pipeline
from app.schemas import (
    AssessmentOut, AssessmentRunRequest, AssessmentRunResponse,
)

router = APIRouter(prefix="/api/v1", tags=["assessment"])


@router.get("/assessments", response_model=list[AssessmentOut])
def list_assessments(
    limit: int = Query(default=200, ge=1, le=400),
    db: Session = Depends(get_db),
) -> list[AssessmentOut]:
    rows = (db.query(Assessment)
            .order_by(Assessment.debt_index.desc())
            .limit(limit).all())
    return [
        AssessmentOut(
            application_id=a.application_id, dimensions=a.dimensions or {},
            debt_index=a.debt_index, complexity_score=a.complexity_score,
            complexity_label=a.complexity_label, agentic_score=a.agentic_score,
            agentic_band=a.agentic_band, indicators=a.indicators or [],
            summary_text=a.summary_text, created_at=a.created_at,
        )
        for a in rows
    ]


@router.get("/assessments/{app_id}", response_model=AssessmentOut)
def get_assessment(app_id: str, db: Session = Depends(get_db)) -> AssessmentOut:
    a = (db.query(Assessment)
         .filter(Assessment.application_id == app_id)
         .order_by(Assessment.id.desc()).first())
    if a is None:
        raise HTTPException(status_code=404, detail=f"no assessment for '{app_id}'")
    return AssessmentOut(
        application_id=a.application_id, dimensions=a.dimensions or {},
        debt_index=a.debt_index, complexity_score=a.complexity_score,
        complexity_label=a.complexity_label, agentic_score=a.agentic_score,
        agentic_band=a.agentic_band, indicators=a.indicators or [],
        summary_text=a.summary_text, created_at=a.created_at,
    )


@router.post("/assessment/run", response_model=AssessmentRunResponse)
def assessment_run(payload: AssessmentRunRequest | None = None,
                   db: Session = Depends(get_db)) -> AssessmentRunResponse:
    payload = payload or AssessmentRunRequest()
    try:
        summary = run_full_pipeline(db, actor=payload.actor)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    preflight_pass = sum(v.get("PASS", 0) for v in summary["preflight"].values()
                         if isinstance(v, dict))
    return AssessmentRunResponse(
        investigation_id=summary["investigation_id"],
        applications_assessed=summary["applications_assessed"],
        strategies_classified=summary["strategies_classified"],
        waves_planned=summary["waves_planned"],
        blocked_migrations=summary["blocked_migrations"],
        preflight_applications=preflight_pass,
        modernization_opportunities=summary["modernization_opportunities"],
        risks_recorded=summary["risks_recorded"],
    )
