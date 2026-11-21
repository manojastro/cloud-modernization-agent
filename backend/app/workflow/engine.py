"""Persisted workflow state machine for investigations.

Two linear chains are enforced server-side:

assessment:    DETECTED -> INVESTIGATING -> DIAGNOSED -> PLANNED
wave migration: PLANNED -> VALIDATING -> AWAITING_APPROVAL -> APPROVED -> EXECUTING
                -> VERIFYING -> COMPLETED | FAILED | ROLLED_BACK

Every transition is validated and persisted, so the API cannot skip e.g. the approval
gate. LangGraph note: this machine maps 1:1 onto a LangGraph StateGraph whose nodes are
the agents and whose edges carry these states; we keep a plain persisted machine so the
audit trail does not depend on a graph-runtime dependency.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Investigation, StageRun

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DETECTED": {"INVESTIGATING"},
    "INVESTIGATING": {"DIAGNOSED"},
    "DIAGNOSED": {"PLANNED"},
    "PLANNED": {"VALIDATING"},
    "VALIDATING": {"AWAITING_APPROVAL"},
    "AWAITING_APPROVAL": {"APPROVED", "PLANNED"},  # reject returns to PLANNED
    "APPROVED": {"EXECUTING"},
    "EXECUTING": {"VERIFYING"},
    "VERIFYING": {"COMPLETED", "FAILED", "ROLLED_BACK"},
}

TERMINAL_STATES = {"PLANNED", "COMPLETED", "FAILED", "ROLLED_BACK"}


class WorkflowViolation(RuntimeError):
    """Raised on illegal workflow transitions or missing gates."""


def start_investigation(session: Session, kind: str, subject: str,
                        initial_state: str = "DETECTED") -> Investigation:
    inv = Investigation(kind=kind, subject=subject, state=initial_state,
                        current_stage="")
    session.add(inv)
    session.flush()
    return inv


def transition(session: Session, inv: Investigation, new_state: str) -> Investigation:
    allowed = ALLOWED_TRANSITIONS.get(inv.state, set())
    if new_state not in allowed:
        raise WorkflowViolation(
            f"illegal transition {inv.state} -> {new_state} for investigation "
            f"#{inv.id} ({inv.kind}/{inv.subject})"
        )
    inv.state = new_state
    inv.updated_at = datetime.utcnow()
    if new_state in TERMINAL_STATES:
        inv.finished_at = datetime.utcnow()
    session.flush()
    return inv


def record_stage(session: Session, inv: Investigation, agent: str, stage: str,
                 input_summary: dict, output_summary: dict, duration_ms: int,
                 order_index: int | None = None, status: str = "ok") -> StageRun:
    if order_index is None:
        last = (
            session.query(StageRun)
            .filter(StageRun.investigation_id == inv.id)
            .order_by(StageRun.order_index.desc())
            .first()
        )
        order_index = (last.order_index + 1) if last else 0
    run = StageRun(
        investigation_id=inv.id, agent=agent, stage=stage, status=status,
        order_index=order_index, input_summary=input_summary,
        output_summary=output_summary, started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(), duration_ms=duration_ms,
    )
    session.add(run)
    inv.current_stage = stage
    return run
