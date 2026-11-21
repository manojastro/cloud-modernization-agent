"""Human-gated migration execution: approval gate, reject path, rollback story."""
import pytest

from simulator.generate_estate import WAVE1_INCOMPATIBLE_APP
from app.migration import simulator
from app.models import (
    Approval,
    Application,
    MigrationExecution,
    ValidationResult,
    Wave,
    WaveMembership,
)
from app.workflow.engine import (
    ALLOWED_TRANSITIONS,
    WorkflowViolation,
    start_investigation,
    transition,
)


def _wave(session, n):
    return session.query(Wave).filter_by(wave_number=n).first()


def test_state_machine_rejects_skipping_the_approval_gate(session):
    inv = start_investigation(session, kind="migration", subject="t")
    with pytest.raises(WorkflowViolation):
        transition(session, inv, "APPROVED")
    transition(session, inv, "INVESTIGATING")
    assert inv.state == "INVESTIGATING"


def test_allowed_transitions_shape():
    # AWAITING_APPROVAL can be approved or sent back to PLANNED (reject) - nothing else
    assert ALLOWED_TRANSITIONS["AWAITING_APPROVAL"] == {"APPROVED", "PLANNED"}
    assert "ROLLED_BACK" in ALLOWED_TRANSITIONS["VERIFYING"]


def test_execute_requires_approval(planned):
    session, _ = planned
    simulator.preflight_wave(session, 0)
    session.commit()
    with pytest.raises(WorkflowViolation):
        simulator.execute_wave(session, 0, actor="tester")


def test_approve_then_execute_wave_0(planned):
    session, _ = planned
    simulator.preflight_wave(session, 0)
    session.commit()

    wave = _wave(session, 0)
    assert wave.status == "AWAITING_APPROVAL" and wave.approval_id is not None

    result = simulator.decide_approval(
        session, wave.approval_id, approve=True, decided_by="tester")
    session.commit()
    assert result.status == "APPROVED"

    out = simulator.execute_wave(session, 0, actor="tester")
    session.commit()
    assert out["wave_status"] == "COMPLETED"
    assert len(out["completed"]) >= 1
    assert out["rolled_back"] == []

    for member in out["completed"]:
        app = session.get(Application, member)
        assert app.placement == "cloud-managed"
    assert _wave(session, 0).status == "COMPLETED"


def test_reject_returns_wave_to_planned_and_touches_nothing(planned):
    session, summary = planned
    before = {a.id: a.placement for a in session.query(Application).all()}

    simulator.preflight_wave(session, 1)
    session.commit()
    wave = _wave(session, 1)
    approval_id = wave.approval_id

    decision = simulator.decide_approval(
        session, approval_id, approve=False, decided_by="tester")
    session.commit()
    assert decision.status == "REJECTED"

    wave = _wave(session, 1)
    assert wave.status == "PLANNED"
    assert wave.approval_id is None

    after = {a.id: a.placement for a in session.query(Application).all()}
    assert after == before, "a rejected wave must not mutate any placement"

    with pytest.raises(WorkflowViolation):
        simulator.execute_wave(session, 1, actor="tester")


def test_wave1_incompatible_app_fails_and_rolls_back_while_wave_continues(planned):
    session, _ = planned

    memberships = (session.query(WaveMembership, Wave)
                   .filter(WaveMembership.wave_id == Wave.id).all())
    target = [m for m, w in memberships
              if m.member_id == WAVE1_INCOMPATIBLE_APP and w.wave_number == 1]
    assert target, "planted incompatible app must be planned into wave 1"

    simulator.preflight_wave(session, 1)
    session.commit()
    wave = _wave(session, 1)
    simulator.decide_approval(session, wave.approval_id, approve=True,
                              decided_by="tester")
    out = simulator.execute_wave(session, 1, actor="tester")
    session.commit()

    assert out["rolled_back"] == [WAVE1_INCOMPATIBLE_APP]
    assert out["wave_status"] == "FAILED"
    assert len(out["completed"]) > 0, "other members must complete despite the failure"

    app = session.get(Application, WAVE1_INCOMPATIBLE_APP)
    assert app.placement == "on-prem", "rollback must restore the on-prem placement"

    failed_rows = (session.query(ValidationResult)
                   .filter_by(application_id=WAVE1_INCOMPATIBLE_APP,
                              status="FAIL").all())
    checks_failed = {r.check_name for r in failed_rows}
    assert "database_connectivity" in checks_failed

    exec_row = (session.query(MigrationExecution)
                .filter_by(application_id=WAVE1_INCOMPATIBLE_APP)
                .order_by(MigrationExecution.id.desc()).first())
    assert exec_row.status == "ROLLED_BACK"

    completed_members = [
        m.member_id for m, w in
        (session.query(WaveMembership, Wave)
         .filter(WaveMembership.wave_id == Wave.id).all())
        if w.wave_number == 1 and m.execution_status == "COMPLETED"
    ]
    assert completed_members


def test_preflight_is_idempotent_and_persists_checks(planned):
    session, _ = planned
    first = simulator.preflight_wave(session, 2)
    second = simulator.preflight_wave(session, 2)
    session.commit()
    rows = (session.query(simulator.PreflightCheck)
            .filter_by(wave_number=2).all())
    names = {r.check_name for r in rows}
    assert names == set(simulator.PREFLIGHT_CHECKS)
    # no duplicate rows from the second run
    per_app_check = {}
    for r in rows:
        key = (r.application_id, r.check_name)
        per_app_check[key] = per_app_check.get(key, 0) + 1
        assert per_app_check[key] <= 1
    assert first["applications"] == second["applications"]
