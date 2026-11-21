"""Migration simulator: pre-flight checks, human approval gate, wave execution with
placement mutation, post-migration validation, and automatic rollback on failure.

Everything is deterministic. One planted incompatibility exists: the receivables
matching service hardcodes an Oracle-only feature (Oracle AQ callbacks) that static
assessment does not flag but runtime validation catches -- it fails database
connectivity in wave 1 and rolls back cleanly while the wave continues.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    Action, Approval, Application, DatabaseRegistry, DomainEvent,
    MigrationExecution, Outcome, PreflightCheck, SharedService, StrategyRecommendation,
    ValidationResult, Wave, WaveMembership,
)
from app.workflow.engine import WorkflowViolation, record_stage, transition

PERFORMANCE_TOLERANCE = 1.25
BASE_LATENCY_MS = {"springboot-17": 42, "go": 38, "python-flask": 55, "node14-express": 60,
                   "java8-weblogic": 120, "dotnet48-iis": 110, "php-legacy": 130,
                   "cobol-mainframe": 240}
VCPU_PER_SERVER = 4
RAM_GB_PER_SERVER = 16
CLOUD_COST_FACTOR = 0.82  # simulated infra savings vs on-prem run-rate
REGULATED_ZONE_READY_FROM_WAVE = 2


class PreflightBlocked(RuntimeError):
    pass


# ------------------------------------------------------------- cost / perf model

@dataclass
class CapacityEstimate:
    vcpu_total: int
    ram_gb_total: int
    container_replicas: int
    est_monthly_cost_usd: float


def capacity_estimate(app: Application) -> CapacityEstimate:
    vcpu = max(1, app.server_count * VCPU_PER_SERVER)
    ram = app.server_count * RAM_GB_PER_SERVER
    replicas = min(max(2, vcpu // 2), 24)
    monthly = round(app.annual_infra_cost_usd / 12 * CLOUD_COST_FACTOR, 2)
    return CapacityEstimate(vcpu_total=vcpu, ram_gb_total=ram,
                            container_replicas=replicas, est_monthly_cost_usd=monthly)


def baseline_latency_ms(app: Application) -> float:
    return float(BASE_LATENCY_MS.get(app.runtime_id, 90))


def projected_latency_ms(app: Application) -> float:
    """Deterministic post-migration latency estimate (hash-seeded per app)."""
    digest = int(hashlib.sha256(app.id.encode()).hexdigest()[:8], 16)
    jitter = (digest % 100) / 100.0  # 0..1
    complexity_drag = 1.0 + 0.10 * (app.criticality / 5)
    return round(baseline_latency_ms(app) * (0.92 + 0.18 * jitter) * complexity_drag, 1)


def within_tolerance(baseline: float, actual: float,
                     tolerance: float = PERFORMANCE_TOLERANCE) -> bool:
    return actual <= baseline * tolerance


# ------------------------------------------------------------------- preflight

PREFLIGHT_CHECKS = [
    "dependency_availability",
    "network_security_zone",
    "identity_requirement",
    "database_connectivity_plan",
    "capacity_estimate",
    "security_controls_present",
    "rollback_plan_defined",
]


def preflight_wave(session: Session, wave_number: int) -> dict:
    wave = session.query(Wave).filter(Wave.wave_number == wave_number).first()
    if wave is None:
        raise LookupError(f"wave {wave_number} not found")
    if wave.status not in ("PLANNED", "AWAITING_APPROVAL"):
        raise WorkflowViolation(
            f"wave {wave_number} is '{wave.status}'; preflight needs PLANNED")

    # flush pending rows first: with autoflush=False a bulk delete would otherwise
    # miss un-flushed check rows from an earlier preflight in this same session.
    session.flush()
    session.query(PreflightCheck).filter(PreflightCheck.wave_number == wave_number).delete()

    from app.models import GraphEdge
    summary = {"PASS": 0, "BLOCKED": 0, "applications": 0}
    blocked_apps: set[str] = set()

    memberships = (session.query(WaveMembership)
                   .filter(WaveMembership.wave_id == wave.id,
                           WaveMembership.member_kind == "application")
                   .order_by(WaveMembership.order_index).all())
    service_waves = {s.id: s.wave_assignment for s in session.query(SharedService).all()}
    app_waves = {
        m.member_id: w.wave_number
        for m, w in session.query(WaveMembership, Wave)
        .filter(WaveMembership.wave_id == Wave.id).all()
    }

    for membership in memberships:
        app = session.get(Application, membership.member_id)
        if app is None:
            continue
        summary["applications"] += 1
        details = app.runtime_details
        db_meta = session.get(DatabaseRegistry, app.database_id) if app.database_id else None
        capacity = capacity_estimate(app)

        results: dict[str, tuple[str, dict]] = {}

        # 1 dependency availability within/before this wave
        deps = (session.query(GraphEdge)
                .filter(GraphEdge.src == app.id,
                        GraphEdge.relation.in_({"APP_CALLS_APP", "APP_USES_IDENTITY"})).all())
        problems = []
        dep_detail = []
        for edge in deps:
            dw = None
            if edge.dst in service_waves:
                dw = service_waves[edge.dst]
            elif edge.dst in app_waves:
                dw = app_waves[edge.dst]
            ok = dw is None or dw <= wave_number or dw == -1
            dep_detail.append({"dep": edge.dst, "relation": edge.relation,
                               "available_from_wave": dw, "ok": ok})
            if not ok:
                problems.append(edge.dst)
        results["dependency_availability"] = (
            "PASS" if not problems else "BLOCKED",
            {"dependencies": dep_detail, "problems": problems},
        )

        # 2 network / security zone readiness
        zone_ready_from = REGULATED_ZONE_READY_FROM_WAVE
        zone_required = "pci" if "PCI" in app.compliance_scope else (
            "pii" if app.compliance_scope != "none" else "general")
        needed = 0 if zone_required == "general" else zone_ready_from
        results["network_security_zone"] = (
            "PASS" if wave_number >= needed else "BLOCKED",
            {"zone": zone_required, "ready_from_wave": needed},
        )

        # 3 identity reachability (sso/ldap migrated wave 0; bridge assumed later)
        id_dep = "svc-sso-provider" if app.auth_method == "sso" else (
            "svc-corporate-ldap" if app.auth_method == "ldap" else None)
        results["identity_requirement"] = (
            "PASS",
            {"identity_service": id_dep or "app-local",
             "note": "identity services migrate in wave 0; bridge available"},
        )

        # 4 database connectivity plan
        compat = db_meta.compatibility if db_meta else "direct"
        managed = db_meta.managed_equivalent if db_meta else "managed-postgres"
        plan_ok = compat in ("direct", "conversion-required", "upgrade-required")
        results["database_connectivity_plan"] = (
            "PASS" if plan_ok else "BLOCKED",
            {"source_engine": db_meta.engine if db_meta else "none",
             "compatibility": compat, "target": managed,
             "driver_note": "psycopg/ODBC managed endpoint" },
        )

        # 5 capacity
        cap_dict = asdict(capacity)
        cap_ok = capacity.vcpu_total <= 512 and capacity.ram_gb_total <= 4096
        results["capacity_estimate"] = ("PASS" if cap_ok else "BLOCKED", cap_dict)

        # 6 security controls
        controls = ["central-secrets-manager", "tls-mesh", "image-scanning"]
        if app.compliance_scope != "none":
            controls += [f"{app.compliance_scope.lower()}-zone-controls", "audit-log-stream"]
        missing = []
        if details and details.hardcoded_secrets_found:
            missing.append("hardcoded secrets must move to central secrets manager before cutover")
        results["security_controls_present"] = (
            "PASS" if not missing else "BLOCKED",
            {"controls": controls, "missing": missing},
        )

        # 7 rollback plan
        results["rollback_plan_defined"] = (
            "PASS",
            {"strategy": "on-prem footprint retained until validation completes",
             "snapshot": f"pre-wave-{wave_number}-baseline"},
        )

        for check_name in PREFLIGHT_CHECKS:
            status, detail = results[check_name]
            session.add(PreflightCheck(wave_number=wave_number,
                                       application_id=app.id,
                                       check_name=check_name, status=status,
                                       detail=detail))
            summary[status] = summary.get(status, 0) + 1
            if status == "BLOCKED":
                blocked_apps.add(app.id)

    for membership in memberships:
        if membership.member_id in blocked_apps:
            membership.execution_status = "BLOCKED"

    inv = _inv_for_wave(session, wave)
    if wave.status == "PLANNED":
        transition(session, inv, "VALIDATING")
        wave.status = "VALIDATING"
    _ensure_approval(session, wave)
    session.add(DomainEvent(event_type="preflight.completed", subject=f"wave-{wave_number}",
                            payload=dict(summary)))
    return summary


def _inv_for_wave(session: Session, wave: Wave):
    from app.models import Investigation
    from app.workflow.engine import start_investigation

    inv = (session.query(Investigation)
           .filter(Investigation.kind == "wave_migration",
                   Investigation.subject == f"wave-{wave.wave_number}")
           .first())
    if inv is None:
        inv = start_investigation(session, "wave_migration",
                                  f"wave-{wave.wave_number}", initial_state="PLANNED")
    return inv


def _ensure_approval(session: Session, wave: Wave) -> Approval:
    if wave.approval_id:
        approval = session.get(Approval, wave.approval_id)
        if approval and approval.status == "PENDING":
            return approval
    approval = Approval(subject_type="wave", subject_id=f"wave-{wave.wave_number}",
                        requested_by="migration-agent")
    session.add(approval)
    session.flush()
    wave.approval_id = approval.id
    transition(session, _inv_for_wave(session, wave), "AWAITING_APPROVAL")
    wave.status = "AWAITING_APPROVAL"
    return approval


def decide_approval(session: Session, approval_id: int, approve: bool,
                    decided_by: str = "operator", comment: str = "") -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise LookupError(f"approval {approval_id} not found")
    if approval.status != "PENDING":
        raise WorkflowViolation(f"approval {approval_id} already {approval.status}")

    approval.status = "APPROVED" if approve else "REJECTED"
    approval.decided_by = decided_by
    approval.decided_at = datetime.utcnow()
    approval.comment = comment

    if approval.subject_type == "wave":
        wave_number = int(str(approval.subject_id).split("-")[1])
        wave = session.query(Wave).filter(Wave.wave_number == wave_number).one()
        inv = _inv_for_wave(session, wave)
        if approve:
            transition(session, inv, "APPROVED")
            wave.status = "APPROVED"
        else:
            transition(session, inv, "PLANNED")
            wave.status = "PLANNED"
            wave.approval_id = None

    action = Action(actor=decided_by, action_type="approve" if approve else "reject",
                    target=approval.subject_id,
                    params={"comment": comment[:200]}, high_risk=True)
    session.add(action)
    session.flush()
    session.add(Outcome(action_id=action.id,
                        outcome_type="approval_decision",
                        success=True, metrics={"approved": approve}))
    session.add(DomainEvent(
        event_type=f"wave.{'approved' if approve else 'rejected'}",
        subject=approval.subject_id, payload={"decided_by": decided_by}))
    return approval


# -------------------------------------------------------------------- execute

VALIDATION_SEQUENCE = [
    "app_starts",
    "api_smoke_test",
    "database_connectivity",
    "dependency_connectivity",
    "business_transaction_replay",
    "security_policy_applied",
    "performance_baseline",
]


def execute_wave(session: Session, wave_number: int, actor: str = "operator") -> dict:
    started = time.perf_counter()
    wave = session.query(Wave).filter(Wave.wave_number == wave_number).first()
    if wave is None:
        raise LookupError(f"wave {wave_number} not found")
    if wave.status != "APPROVED":
        raise WorkflowViolation(
            f"wave {wave_number} cannot execute: status '{wave.status}' "
            "(requires human APPROVAL first)")

    inv = _inv_for_wave(session, wave)
    transition(session, inv, "EXECUTING")
    wave.status = "EXECUTING"
    wave.started_at = datetime.utcnow()

    action = Action(actor=actor, action_type="execute_wave", target=f"wave-{wave_number}",
                    params={}, high_risk=True)
    session.add(action)
    session.flush()

    completed: list[str] = []
    rolled_back: list[str] = []

    from app.metrics import count_migration

    memberships = (session.query(WaveMembership)
                   .filter(WaveMembership.wave_id == wave.id)
                   .order_by(WaveMembership.order_index, WaveMembership.id).all())
    for membership in memberships:
        if membership.member_kind == "service":
            membership.execution_status = "COMPLETED"
            continue
        if membership.execution_status in ("BLOCKED", "COMPLETED", "ROLLED_BACK"):
            continue
        app = session.get(Application, membership.member_id)
        execution = MigrationExecution(wave_number=wave_number, application_id=app.id,
                                       status="RUNNING")
        session.add(execution)
        session.flush()

        # provisional placement mutation (the "move")
        app.placement = "cloud-managed"

        failed = _validate_app(session, execution, app, wave_number)
        if failed:
            _rollback(session, execution, app, failed["check"], failed["detail"])
            rolled_back.append(app.id)
            count_migration(wave_number, "rolled_back")
        else:
            execution.status = "COMPLETED"
            execution.finished_at = datetime.utcnow()
            execution.detail = {"latency_ms": projected_latency_ms(app),
                                "cost_model": asdict(capacity_estimate(app))}
            membership.execution_status = "COMPLETED"
            completed.append(app.id)
            count_migration(wave_number, "completed")

    transition(session, inv, "VERIFYING")
    final = "FAILED" if rolled_back else "COMPLETED"
    transition(session, inv, final)
    wave.status = final
    wave.completed_at = datetime.utcnow()
    wave.result_json = {
        "completed": completed, "rolled_back": rolled_back,
        "duration_s": round(time.perf_counter() - started, 3),
    }

    session.add(Outcome(action_id=action.id, outcome_type="wave_execution",
                        success=not rolled_back,
                        metrics={"completed": len(completed),
                                 "rolled_back": len(rolled_back)}))
    session.add(DomainEvent(event_type="wave.executed", subject=f"wave-{wave_number}",
                            payload={"completed": completed, "rolled_back": rolled_back}))
    return {"wave_number": wave_number, "wave_status": final,
            "completed": completed, "rolled_back": rolled_back}


def _validate_app(session: Session, execution: MigrationExecution, app: Application,
                  wave_number: int) -> dict | None:
    """Run the validation sequence; returns failure dict or None."""
    details = app.runtime_details

    def record(check: str, seq: int, status: str, metric_value: float | None = None,
               tolerance: float | None = None, detail: dict | None = None) -> None:
        session.add(ValidationResult(
            execution_id=execution.id, application_id=app.id, check_name=check,
            sequence_no=seq, status=status, metric_value=metric_value,
            tolerance=tolerance, detail=detail or {}))

    # 1 app starts
    record("app_starts", 1, "PASS", detail={"health": "simulated liveness probe ok"})
    # 2 API smoke test
    if app.api_surface in ("REST-internal", "REST-public", "gRPC", "SOAP"):
        record("api_smoke_test", 2, "PASS", detail={"probe": "/health + one GET route"})
    else:
        record("api_smoke_test", 2, "SKIPPED", detail={"reason": f"api_surface={app.api_surface}"})
    # 3 database connectivity
    if details and details.oracle_only_feature:
        fail = {"check": "database_connectivity",
                "detail": "runtime error: PL/SQL AQ callback package has no equivalent on "
                          "the managed SQL endpoint; hardcoded Oracle-only feature"}
        record("database_connectivity", 3, "FAIL",
               detail={"error": fail["detail"]})
        return fail
    db_meta = session.get(DatabaseRegistry, app.database_id) if app.database_id else None
    record("database_connectivity", 3, "PASS",
           detail={"endpoint": db_meta.managed_equivalent if db_meta else "object-storage",
                   "driver": "managed"})
    # 4 dependency connectivity
    from app.models import GraphEdge

    dep_edges = (session.query(GraphEdge)
                 .filter(GraphEdge.src == app.id,
                         GraphEdge.relation.in_({"APP_CALLS_APP", "APP_USES_IDENTITY"})).all())
    record("dependency_connectivity", 4, "PASS",
           detail={"checked": [e.dst for e in dep_edges],
                   "note": "retained on-prem dependencies reached via connectivity bridge"})
    # 5 business transaction replay (critical apps only)
    if app.criticality >= 4:
        record("business_transaction_replay", 5, "PASS",
               detail={"canned_transaction": f"txn-{app.id}-01", "result": "reconciled"})
    else:
        record("business_transaction_replay", 5, "SKIPPED",
               detail={"reason": f"criticality {app.criticality} < 4"})
    # 6 security policy applied
    record("security_policy_applied", 6, "PASS",
           detail={"secrets": "bound to central secrets manager",
                   "network_policy": "zone default-deny applied"})
    # 7 performance baseline within tolerance
    base = baseline_latency_ms(app)
    actual = projected_latency_ms(app)
    ok = within_tolerance(base, actual)
    record("performance_baseline", 7, "PASS" if ok else "FAIL",
           metric_value=actual, tolerance=PERFORMANCE_TOLERANCE,
           detail={"baseline_ms": base})
    if not ok:
        return {"check": "performance_baseline",
                "detail": f"{actual}ms exceeds {base}ms x{PERFORMANCE_TOLERANCE}"}
    return None


def _rollback(session: Session, execution: MigrationExecution, app: Application,
              failed_check: str, detail: str) -> None:
    """Automatic rollback: restore placement, mark execution ROLLED_BACK."""
    app.placement = "on-prem"
    execution.status = "ROLLED_BACK"
    execution.finished_at = __import__("datetime").datetime.utcnow()
    execution.detail = {"failed_check": failed_check, "reason": detail,
                        "restored_placement": "on-prem"}

    membership = (session.query(WaveMembership)
                  .filter(WaveMembership.member_id == app.id).first())
    if membership:
        membership.execution_status = "ROLLED_BACK"

    action = Action(actor="migration-agent", action_type="rollback_app",
                    target=app.id, high_risk=True,
                    params={"wave": execution.wave_number, "reason": detail[:200]})
    session.add(action)
    session.flush()
    session.add(Outcome(action_id=action.id, outcome_type="rollback",
                        success=True, metrics={"failed_check": failed_check}))
    session.add(DomainEvent(event_type="app.rolled_back", subject=app.id,
                            payload={"wave": execution.wave_number,
                                     "failed_check": failed_check}))


def can_rollback_app(session: Session, app_id: str) -> tuple[bool, str]:
    """Gate for the high-risk rollback tool: only during/after a real failed migration."""
    execs = (session.query(MigrationExecution)
             .filter(MigrationExecution.application_id == app_id)
             .order_by(MigrationExecution.id.desc()).all())
    if not execs:
        return False, "no migration execution exists for this app"
    latest = execs[0]
    if latest.status in ("FAILED", "RUNNING"):
        return True, f"execution #{latest.id} is '{latest.status}'"
    if latest.status == "ROLLED_BACK":
        return False, "already rolled back"
    return False, f"execution #{latest.id} is '{latest.status}'; rollback requires a failure or an approved change request"
