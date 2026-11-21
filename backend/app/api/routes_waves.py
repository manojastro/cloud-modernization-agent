"""Wave planning, preflight, blocked migrations, approvals-gated execution, validations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.migration import simulator
from app.models import (
    BlockedMigration, MigrationExecution, PreflightCheck, Wave, WaveMembership,
)
from app.schemas import (
    ApprovalDecisionRequest, ApprovalOut, BlockedMigrationOut, ExecutionOut,
    ExecuteWaveRequest, ExecuteWaveResponse, PreflightCheckOut, ValidationResultOut,
    WaveMembershipOut, WaveOut,
)
from app.workflow.engine import WorkflowViolation as WFViolation

router = APIRouter(prefix="/api/v1", tags=["waves"])


def _wave_or_404(db: Session, wave_number: int) -> Wave:
    wave = db.query(Wave).filter(Wave.wave_number == wave_number).first()
    if wave is None:
        raise HTTPException(status_code=404, detail=f"wave {wave_number} not found")
    return wave


@router.get("/waves", response_model=list[WaveOut])
def list_waves(db: Session = Depends(get_db)) -> list[WaveOut]:
    waves = db.query(Wave).order_by(Wave.wave_number).all()
    return [_to_wave_out(w) for w in waves]


@router.get("/waves/{wave_number}", response_model=WaveOut)
def get_wave(wave_number: int, db: Session = Depends(get_db)) -> WaveOut:
    return _to_wave_out(_wave_or_404(db, wave_number))


def _to_wave_out(w: Wave) -> WaveOut:
    memberships = (w.memberships and sorted(
        w.memberships, key=lambda m: m.order_index)) or []
    return WaveOut(
        wave_number=w.wave_number, name=w.name, status=w.status,
        max_concurrent=w.max_concurrent, description=w.description,
        approval_id=w.approval_id,
        memberships=[
            WaveMembershipOut(member_id=m.member_id, member_kind=m.member_kind,
                              strategy=m.strategy,
                              execution_status=m.execution_status,
                              order_index=m.order_index)
            for m in memberships
        ],
        blocked_count=0,
        preflight_summary={},
    )


@router.post("/waves/plan")
def plan_waves_endpoint(db: Session = Depends(get_db)) -> dict:
    from app.waves.planner import plan_waves

    result = plan_waves(db)
    return {
        "waves": result.waves,
        "memberships": len(result.memberships),
        "blocked": result.blocked,
        "constraint_moves": result.constraint_moves,
    }


@router.get("/waves/{wave_number}/preflight", response_model=list[PreflightCheckOut])
def wave_preflight(wave_number: int, db: Session = Depends(get_db)):
    _wave_or_404(db, wave_number)
    rows = (db.query(PreflightCheck)
            .filter(PreflightCheck.wave_number == wave_number)
            .order_by(PreflightCheck.application_id, PreflightCheck.check_name).all())
    if not rows:
        raise HTTPException(status_code=404, detail="no preflight results; run "
                                                    "POST /api/v1/waves/{n}/preflight first")
    return [PreflightCheckOut(application_id=r.application_id, check_name=r.check_name,
                              status=r.status, detail=r.detail or {}) for r in rows]


@router.post("/waves/{wave_number}/preflight", response_model=dict)
def run_wave_preflight(wave_number: int, db: Session = Depends(get_db)) -> dict:
    try:
        return simulator.preflight_wave(db, wave_number)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (WFViolation, WorkflowViolation) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/blocked", response_model=list[BlockedMigrationOut])
def list_blocked(db: Session = Depends(get_db)) -> list[BlockedMigrationOut]:
    rows = db.query(BlockedMigration).order_by(BlockedMigration.id).all()
    return [
        BlockedMigrationOut(id=b.id, application_id=b.application_id,
                            reason_code=b.reason_code,
                            reason_detail=b.reason_detail,
                            suggested_resolution=b.suggested_resolution,
                            dep_id=b.dep_id)
        for b in rows
    ]


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(db: Session = Depends(get_db)) -> list[ApprovalOut]:
    from app.models import Approval

    rows = (db.query(Approval).order_by(Approval.id.desc()).limit(100).all())
    return [ApprovalOut(**{c.name: getattr(r, c.name)
                           for c in Approval.__table__.columns}) for r in rows]


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalOut)
def approve(approval_id: int, payload: ApprovalDecisionRequest | None = None,
            db: Session = Depends(get_db)) -> ApprovalOut:
    payload = payload or ApprovalDecisionRequest()
    try:
        a = simulator.decide_approval(db, approval_id, approve=True,
                                      decided_by=payload.decided_by,
                                      comment=payload.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WFViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return ApprovalOut(
        id=a.id, subject_type=a.subject_type, subject_id=a.subject_id,
        requested_by=a.requested_by, requested_at=a.requested_at,
        status=a.status, decided_by=a.decided_by, decided_at=a.decided_at,
        comment=a.comment)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalOut)
def reject(approval_id: int, payload: ApprovalDecisionRequest | None = None,
           db: Session = Depends(get_db)) -> ApprovalOut:
    payload = payload or ApprovalDecisionRequest()
    try:
        a = simulator.decide_approval(db, approval_id, approve=False,
                                      decided_by=payload.decided_by,
                                      comment=payload.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WFViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return ApprovalOut(
        id=a.id, subject_type=a.subject_type, subject_id=a.subject_id,
        requested_by=a.requested_by, requested_at=a.requested_at,
        status=a.status, decided_by=a.decided_by, decided_at=a.decided_at,
        comment=a.comment)


@router.post("/waves/{wave_number}/execute", response_model=ExecuteWaveResponse)
def execute_wave(wave_number: int, payload: ExecuteWaveRequest | None = None,
                 db: Session = Depends(get_db)) -> ExecuteWaveResponse:
    payload = payload or ExecuteWaveRequest()
    try:
        result = simulator.execute_wave(db, wave_number, actor=payload.actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except WFViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    execs = (db.query(MigrationExecution)
             .filter(MigrationExecution.wave_number == wave_number)
             .order_by(MigrationExecution.id.desc()).limit(200).all())
    latest_by_app: dict[str, ExecutionOut] = {}
    for e in execs:
        if e.application_id not in latest_by_app:
            latest_by_app[e.application_id] = ExecutionOut(
                id=e.id, wave_number=e.wave_number, application_id=e.application_id,
                status=e.status, started_at=e.started_at,
                finished_at=e.finished_at, detail=e.detail or {})
    return ExecuteWaveResponse(
        wave_number=result["wave_number"], wave_status=result["wave_status"],
        executions=list(latest_by_app.values()),
        rolled_back=result["rolled_back"], completed=result["completed"])


@router.get("/executions", response_model=list[ExecutionOut])
def list_executions(wave_number: int | None = Query(default=None),
                    limit: int = Query(default=200, ge=1, le=500),
                    db: Session = Depends(get_db)) -> list[ExecutionOut]:
    q = db.query(MigrationExecution)
    if wave_number is not None:
        q = q.filter(MigrationExecution.wave_number == wave_number)
    rows = q.order_by(MigrationExecution.id.desc()).limit(limit).all()
    return [ExecutionOut(id=e.id, wave_number=e.wave_number,
                         application_id=e.application_id, status=e.status,
                         started_at=e.started_at, finished_at=e.finished_at,
                         detail=e.detail or {}) for e in rows]


@router.get("/validations", response_model=list[ValidationResultOut])
def list_validations(execution_id: int | None = None,
                     wave_number: int | None = None,
                     db: Session = Depends(get_db)) -> list[ValidationResultOut]:
    from app.models import ValidationResult

    q = db.query(ValidationResult)
    if execution_id is not None:
        q = q.filter(ValidationResult.execution_id == execution_id)
    elif wave_number is not None:
        exec_ids = [e.id for e in db.query(MigrationExecution.id)
                    .filter(MigrationExecution.wave_number == wave_number).all()]
        q = q.filter(ValidationResult.execution_id.in_(exec_ids or [-1]))
    else:
        raise HTTPException(status_code=422,
                            detail="provide execution_id or wave_number")
    rows = q.order_by(ValidationResult.execution_id,
                      ValidationResult.sequence_no).all()
    return [
        ValidationResultOut(execution_id=v.execution_id,
                            application_id=v.application_id,
                            check_name=v.check_name, sequence_no=v.sequence_no,
                            status=v.status, metric_value=v.metric_value,
                            tolerance=v.tolerance, detail=v.detail or {})
        for v in rows
    ]
