"""Portfolio queries, application detail, and dependency-graph export."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.graph.dependency_graph import export_nodes_edges
from app.models import (
    AgenticReadinessItem, Application, Assessment, ModernizationOpportunity,
    StrategyRecommendation,
)
from app.schemas import (
    ApplicationDetail, ApplicationSummary, GraphEdgeOut, GraphNodeOut,
    GraphResponse, PortfolioResponse,
)

router = APIRouter(prefix="/api/v1", tags=["portfolio"])

_SORTERS = {
    "name": lambda a: a.name,
    "criticality": lambda a: -a.criticality,
    "cost": lambda a: -a.annual_infra_cost_usd,
    "debt": lambda a: -(a.debt_index if a.debt_index is not None else -1),
    "agentic": lambda a: -(a.agentic_score if a.agentic_score is not None else -1),
    "usage": lambda a: -a.usage_per_day,
}


def _summary(app: Application, strategy, assessment) -> ApplicationSummary:
    return ApplicationSummary(
        id=app.id, name=app.name, domain=app.domain,
        business_owner=app.business_owner, language=app.language,
        runtime_id=app.runtime_id, os_id=app.os_id, criticality=app.criticality,
        api_surface=app.api_surface, auth_method=app.auth_method,
        statefulness=app.statefulness, compliance_scope=app.compliance_scope,
        usage_per_day=app.usage_per_day,
        monthly_usage_trend_pct=app.monthly_usage_trend_pct,
        annual_infra_cost_usd=app.annual_infra_cost_usd, placement=app.placement,
        strategy=strategy.strategy if strategy else None,
        strategy_confidence=strategy.confidence if strategy else None,
        readiness_band=assessment.agentic_band if assessment else None,
        agentic_score=assessment.agentic_score if assessment else None,
        complexity_label=assessment.complexity_label if assessment else None,
        debt_index=assessment.debt_index if assessment else None,
    )


@router.get("/applications", response_model=PortfolioResponse)
def list_applications(
    q: str | None = Query(default=None, max_length=80),
    domain: str | None = None,
    runtime_id: str | None = None,
    strategy: str | None = None,
    readiness_band: str | None = None,
    criticality_min: int = Query(default=None, ge=1, le=5),
    criticality_max: int = Query(default=None, ge=1, le=5),
    sort: str = Query(default="name"),
    limit: int = Query(default=200, ge=1, le=400),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PortfolioResponse:
    strategies = {s.application_id: s for s in db.query(StrategyRecommendation).all()}
    assessments = {a.application_id: a for a in db.query(Assessment).all()}

    rows = []
    for app in db.query(Application).all():
        st = strategies.get(app.id)
        asmt = assessments.get(app.id)
        rows.append(_summary(app, st, asmt))

    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r.name.lower()
                or needle in r.domain.lower() or needle in r.id]
    if domain:
        rows = [r for r in rows if r.domain == domain]
    if runtime_id:
        rows = [r for r in rows if r.runtime_id == runtime_id]
    if strategy:
        rows = [r for r in rows if r.strategy == strategy]
    if readiness_band:
        rows = [r for r in rows if r.readiness_band == readiness_band]
    if criticality_min is not None:
        rows = [r for r in rows if r.criticality >= criticality_min]
    if criticality_max is not None:
        rows = [r for r in rows if r.criticality <= criticality_max]

    keyfn = _SORTERS.get(sort)
    if keyfn is None:
        raise HTTPException(status_code=422, detail=f"unsupported sort '{sort}'")
    rows.sort(key=keyfn)

    total = len(rows)
    page = rows[offset:offset + limit]
    return PortfolioResponse(total=total, items=page)


@router.get("/applications/{app_id}", response_model=ApplicationDetail)
def application_detail(app_id: str, db: Session = Depends(get_db)) -> ApplicationDetail:
    app = db.get(Application, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"application '{app_id}' not found")
    strategy = (db.query(StrategyRecommendation)
                .filter(StrategyRecommendation.application_id == app_id).first())
    assessment = (db.query(Assessment)
                  .filter(Assessment.application_id == app_id).first())
    items = (db.query(AgenticReadinessItem)
             .filter(AgenticReadinessItem.application_id == app_id).all())
    opportunities = (db.query(ModernizationOpportunity)
                     .filter(ModernizationOpportunity.application_id == app_id).all())

    base = _summary(app, strategy, assessment)
    return ApplicationDetail(
        **base.model_dump(),
        description=app.description or "",
        dimensions=(assessment.dimensions if assessment else {}) or {},
        indicators=(assessment.indicators if assessment else []) or [],
        agentic_items=[
            {"item_key": i.item_key, "label": i.label, "passed": i.passed, "note": i.note}
            for i in items
        ],
        reasons=list(strategy.reasons) if strategy else [],
        alternatives=list(strategy.alternatives) if strategy else [],
        rule_trace=list(strategy.rule_trace) if strategy else [],
        opportunities=[
            {"title": o.title, "category": o.category, "impact": o.impact,
             "effort": o.effort, "description": o.description}
            for o in opportunities
        ],
    )


@router.get("/graph", response_model=GraphResponse)
def graph(relation: str | None = Query(default=None), include_inventory: bool = False,
          db: Session = Depends(get_db)) -> GraphResponse:
    nodes_raw, edges_raw = export_nodes_edges(db)
    from app.models import WaveMembership, Wave

    wave_by_member: dict[str, int] = {}
    for m, w in (db.query(WaveMembership, Wave)
                 .filter(WaveMembership.wave_id == Wave.id).all()):
        wave_by_member[m.member_id] = w.wave_number

    keep_kinds = {"application", "service", "database"}
    nodes = []
    for n in nodes_raw:
        if not include_inventory and n["kind"] not in keep_kinds:
            continue
        n = dict(n)
        n["wave"] = wave_by_member.get(n["id"])
        nodes.append(n)
    node_ids = {n["id"] for n in nodes}
    edges = [
        GraphEdgeOut(**e) for e in edges_raw
        if e["src"] in node_ids and e["dst"] in node_ids
        and (relation is None or e["relation"] == relation)
    ]
    return GraphResponse(nodes=[GraphNodeOut(**n) for n in nodes], edges=edges)
