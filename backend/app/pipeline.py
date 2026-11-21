"""Full assessment pipeline orchestration: agents run in order over a persisted
investigation, wiping prior derived data first so reruns are idempotent."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.discovery import ApplicationDiscoveryAgent, DependencyMappingAgent
from app.agents.modernization import ModernizationAgent
from app.agents.planning import (
    MigrationStrategyAgent, RiskAgent, ValidationAgent, WavePlanningAgent,
)
from app.agents.readiness import CloudReadinessAgent, TechnicalDebtAgent
from app.llm.provider import get_llm_provider
from app.models import (
    AgenticReadinessItem, AppRuntimeDetails, Assessment, DecisionRecord,
    DomainEvent, Evidence, Investigation, MetricSnapshot,
    ModernizationOpportunity, Risk, StrategyRecommendation, TargetArchitecture,
)
from app.workflow.engine import start_investigation, transition


def _wipe_derived(session: Session) -> None:
    session.query(AgenticReadinessItem).delete()
    session.query(Assessment).delete()
    session.query(StrategyRecommendation).delete()
    session.query(ModernizationOpportunity).delete()
    session.query(TargetArchitecture).delete()
    session.query(Risk).delete()
    session.query(Evidence).delete()
    session.query(DecisionRecord).delete()
    session.flush()


def pct_off_eol_runtime_post_plan(session: Session) -> float:
    apps = session.query(AppRuntimeDetails).all()
    eol_ids = {r.application_id for r in apps if r.runtime_eol}
    if not eol_ids:
        return 100.0
    migrating = {
        s.application_id for s in session.query(StrategyRecommendation).all()
        if s.strategy in {"REHOST", "REPLATFORM", "REFACTOR", "REPURCHASE", "RELOCATE"}
    }
    off_eol = len(eol_ids & migrating)
    return round(100.0 * off_eol / len(eol_ids), 1)


def take_metric_snapshot(session: Session, kind: str = "assessment") -> dict:
    metrics = {
        "applications_assessed": session.query(Assessment).count(),
        "strategies_classified": session.query(StrategyRecommendation).count(),
        "modernization_opportunities": session.query(ModernizationOpportunity).count(),
        "risks_recorded": session.query(Risk).count(),
        "pct_apps_off_eol_runtime_post_plan": pct_off_eol_runtime_post_plan(session),
    }
    session.add(MetricSnapshot(snapshot_kind=kind, metrics=metrics))
    return metrics


def run_full_pipeline(session: Session, actor: str = "system") -> dict:
    from app.models import Application

    if session.query(Application).count() == 0:
        raise RuntimeError("estate is empty; seed it first (POST /api/v1/simulator/seed)")

    _wipe_derived(session)

    llm = get_llm_provider()
    inv = start_investigation(session, kind="assessment", subject="portfolio",
                              initial_state="DETECTED")
    transition(session, inv, "INVESTIGATING")

    discovery_out = ApplicationDiscoveryAgent(session, llm=llm).run(inv)
    mapping_out = DependencyMappingAgent(session, llm=llm).run(inv)
    debt_out = TechnicalDebtAgent(session, llm=llm).run(inv)
    readiness_out = CloudReadinessAgent(session, llm=llm).run(inv)
    transition(session, inv, "DIAGNOSED")

    opportunities = ModernizationAgent(session, llm=llm).run(inv)
    strategies = MigrationStrategyAgent(session, llm=llm).run(inv)
    transition(session, inv, "PLANNED")

    waves = WavePlanningAgent(session, llm=llm).run(inv)
    risks = RiskAgent(session, llm=llm).run(inv)
    validation = ValidationAgent(session, llm=llm).run(inv)

    metrics = take_metric_snapshot(session, kind="assessment")
    session.add(DomainEvent(event_type="assessment.completed", subject="portfolio",
                            payload={"investigation_id": inv.id}))

    return {
        "investigation_id": inv.id,
        "applications_assessed": readiness_out["applications_assessed"],
        "dependency_edges": mapping_out["total_edges"],
        "hidden_dependencies_found":
            discovery_out["undocumented_dependencies_found"],
        "modernization_opportunities": opportunities["opportunities_created"],
        "strategies_classified": strategies["classified"],
        "strategy_mix": strategies["by_strategy"],
        "waves_planned": len(waves["waves"]),
        "blocked_migrations": len(waves["blocked"]),
        "blocked_detail": waves["blocked"],
        "constraint_moves": waves["constraint_moves"],
        "risks_recorded": risks["risks_recorded"],
        "preflight": validation["per_wave"],
        "metrics_snapshot": metrics,
    }
