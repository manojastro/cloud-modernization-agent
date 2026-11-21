"""Deterministic per-application assessment engine.

Produces dimension scores (0-100), a technical-debt index, a complexity estimate and
an agentic-readiness checklist for every application. No LLM involvement: the same
application always yields the same assessment.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.assessment.agentic_readiness import evaluate_agentic_readiness
from app.models import (
    AgenticReadinessItem, AppRuntimeDetails, Application, Assessment,
    CMDBRecord, DatabaseRegistry, NetworkFlow,
)

DIMENSIONS: list[str] = [
    "architecture_fit",
    "runtime_support_status",
    "os_support_status",
    "database_compatibility",
    "dependency_tangle",
    "api_readiness",
    "statefulness_score",
    "security_posture",
    "business_criticality",
    "technical_debt_index",  # higher = more debt (inverted vs other dimensions)
]

_API_READINESS = {
    "gRPC": 95, "REST-public": 90, "REST-internal": 75,
    "SOAP": 35, "none": 20, "batch-only": 25,
}

_AUTH_BASE = {"sso": 90, "ldap": 70, "local-db": 60, "basic": 30, "none": 10}


def db_meta_for(session: Session, app: Application) -> DatabaseRegistry | None:
    if not app.database_id:
        return None
    return session.get(DatabaseRegistry, app.database_id)


def point_to_point_count(session: Session, app_id: str) -> int:
    return (
        session.query(NetworkFlow)
        .filter(NetworkFlow.src_app_id == app_id, NetworkFlow.dst_kind == "application")
        .count()
    )


def compute_debt_index(app: Application, d: AppRuntimeDetails | None,
                       db_meta: DatabaseRegistry | None) -> tuple[float, list[str]]:
    indicators: list[str] = []
    score = 0.0

    def add(points: float, name: str) -> None:
        nonlocal score
        score += points
        indicators.append(name)

    if d is None:
        return 0.0, indicators
    if d.runtime_eol:
        add(20, "eol_runtime")
    if d.os_eol:
        add(15, "eol_os")
    if app.api_surface in ("none", "SOAP"):
        add(10, "no_api_layer")
    if d.shared_database or (db_meta is not None and db_meta.is_shared_service):
        add(15, "shared_database")
    if d.hardcoded_secrets_found:
        add(15, "hardcoded_secrets")
    if d.manual_deployments:
        add(10, "manual_deployments")
    if d.monolith_loc > 200_000:
        add(10, "monolith_codebase")
    elif d.monolith_loc > 100_000:
        add(5, "large_codebase")
    if not d.has_observability:
        add(10, "no_observability")
    if db_meta is not None and db_meta.eol:
        add(10, "eol_database")

    return min(score, 100.0), indicators


def assess_application(session: Session, app: Application) -> Assessment:
    d = app.runtime_details
    db_meta = db_meta_for(session, app)
    p2p = point_to_point_count(session, app.id)
    debt_index, indicators = compute_debt_index(app, d, db_meta)

    monolith_penalty = min(40, (d.monolith_loc / 25_000) if d else 0)
    architecture_fit = max(5, 100 - monolith_penalty - (15 if app.api_surface in ("none", "SOAP") else 0) - p2p * 4)

    runtime_score = 90
    if d and d.runtime_eol:
        runtime_score = 70 if app.runtime_id == "cobol-mainframe" else 25

    os_score = 90
    if d and d.os_eol:
        os_score = 70 if app.os_id == "zos-sim" else 25

    compat = (db_meta.compatibility if db_meta else "direct") or "direct"
    db_score = {"direct": 90, "conversion-required": 55, "upgrade-required": 70, "none": 25}.get(compat, 55)

    shared_db = 1 if (d and (d.shared_database or (db_meta and db_meta.is_shared_service))) else 0
    tangle = max(5, 100 - min(85, shared_db * 35 + p2p * 8))

    statefulness_score = {"stateless": 95, "sticky-sessions": 50, "session-replication": 30}.get(
        app.statefulness, 50)

    security = _AUTH_BASE.get(app.auth_method, 40)
    if d and d.hardcoded_secrets_found:
        security -= 25
    if app.compliance_scope != "none" and security < 60:
        security -= 10
    security = max(5, security)

    dimensions = {
        "architecture_fit": round(architecture_fit, 1),
        "runtime_support_status": runtime_score,
        "os_support_status": os_score,
        "database_compatibility": db_score,
        "dependency_tangle": round(tangle, 1),
        "api_readiness": _API_READINESS.get(app.api_surface, 40),
        "statefulness_score": statefulness_score,
        "security_posture": security,
        "business_criticality": app.criticality * 20,
        "technical_debt_index": round(debt_index, 1),
    }

    # ---- migration complexity estimate
    complexity = (
        (100 - statefulness_score) * 0.30
        + debt_index * 0.30
        + (100 - tangle) * 0.20
        + (100 - db_score) * 0.10
        + (15 if app.compliance_scope != "none" else 0)
        + (10 if app.criticality == 5 else 0)
    )
    if shared_db:
        complexity = max(complexity, 50.0)  # shared-database consumers are never 'low'
    complexity = round(min(complexity, 100.0), 1)
    label = "low" if complexity < 40 else ("medium" if complexity < 65 else "high")

    agentic = evaluate_agentic_readiness(app)

    summary_bits = [
        f"{app.name}: {app.framework} on {d.os_family if d else app.os_id}",
        f"criticality {app.criticality}/5",
        f"debt index {debt_index:.0f}/100",
        f"complexity {label}",
        f"agentic readiness {agentic.score}/9 ({agentic.band})",
    ]

    assessment = Assessment(
        application_id=app.id,
        dimensions=dimensions,
        debt_index=round(debt_index, 1),
        complexity_score=complexity,
        complexity_label=label,
        agentic_score=agentic.score,
        agentic_band=agentic.band,
        indicators=indicators,
        summary_text="; ".join(summary_bits),
    )
    session.add(assessment)

    session.query(AgenticReadinessItem).filter_by(application_id=app.id).delete()
    for item in agentic.items:
        session.add(AgenticReadinessItem(application_id=app.id, **item))

    return assessment


def cmdb_field(session: Session, app_id: str, field: str) -> str:
    row = (
        session.query(CMDBRecord)
        .filter(CMDBRecord.application_id == app_id, CMDBRecord.field == field)
        .first()
    )
    return row.value if row else ""
