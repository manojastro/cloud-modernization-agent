"""Pydantic v2 API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ------------------------------------------------------- core fact records ----


class Evidence(BaseModel):
    """A sourced, timestamped fact an agent decision rests on."""

    source: str = Field(description="Where the fact came from, e.g. cmdb-sim, transfer-log-correlation")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    fact: str
    reliability: Literal["high", "medium", "low"] = "high"
    raw_reference: str = ""


class Decision(BaseModel):
    """An auditable agent decision with evidence ids and alternatives."""

    decision: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[int] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "medium"
    requires_approval: bool = False
    rationale: str = ""


# ------------------------------------------------------------------- meta ----


class MetaResponse(BaseModel):
    name: str
    version: str
    llm_mode: str
    mock_mode: bool
    badge: str | None = None
    estate_seeded: bool
    application_count: int
    default_provider_profile: str


class HealthResponse(BaseModel):
    status: str = "ok"
    database: str = "ok"


class ReadinessResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]


class SeedRequest(BaseModel):
    size: int | None = Field(default=None, ge=12, le=400)
    reset: bool = True


class SeedResponse(BaseModel):
    seeded: bool
    applications: int
    shared_services: int
    network_flows: int
    file_transfers: int
    batch_jobs: int
    cmdb_records: int
    servers: int
    truth_edges_written: int


# ------------------------------------------------------------- portfolio ----


class ApplicationSummary(BaseModel):
    id: str
    name: str
    domain: str
    business_owner: str
    language: str
    runtime_id: str
    os_id: str
    criticality: int
    api_surface: str
    auth_method: str
    statefulness: str
    compliance_scope: str
    usage_per_day: int
    monthly_usage_trend_pct: float
    annual_infra_cost_usd: float
    placement: str
    strategy: Optional[str] = None
    strategy_confidence: Optional[float] = None
    readiness_band: Optional[str] = None
    agentic_score: Optional[int] = None
    complexity_label: Optional[str] = None
    debt_index: Optional[float] = None


class ApplicationDetail(ApplicationSummary):
    description: str = ""
    dimensions: dict[str, float] = Field(default_factory=dict)
    indicators: list[str] = Field(default_factory=list)
    agentic_items: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    rule_trace: list[dict[str, Any]] = Field(default_factory=list)
    opportunities: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioResponse(BaseModel):
    total: int
    items: list[ApplicationSummary]


class GraphEdgeOut(BaseModel):
    src: str
    dst: str
    relation: str
    discovered_by: str
    confidence: float = 0.9
    note: str = ""


class GraphNodeOut(BaseModel):
    id: str
    kind: str
    label: str
    domain: str | None = None
    wave: Optional[int] = None


class GraphResponse(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


# ------------------------------------------------------------ assessment ----


class AssessmentOut(BaseModel):
    application_id: str
    dimensions: dict[str, float]
    debt_index: float
    complexity_score: float
    complexity_label: str
    agentic_score: int
    agentic_band: str
    indicators: list[str]
    summary_text: str
    created_at: datetime


class AgenticItemOut(BaseModel):
    item_key: str
    label: str
    passed: bool
    note: str


class AssessmentRunRequest(BaseModel):
    actor: str = "api-operator"


class AssessmentRunResponse(BaseModel):
    investigation_id: int
    applications_assessed: int
    strategies_classified: int
    waves_planned: int
    blocked_migrations: int
    preflight_applications: int
    modernization_opportunities: int
    risks_recorded: int


# -------------------------------------------------------------- strategy ----


class StrategyOut(BaseModel):
    application_id: str
    strategy: str
    confidence: float
    matched_rule_id: str
    reasons: list[str]
    alternatives: list[str]
    rule_trace: list[dict[str, Any]]
    risk_level: str
    requires_approval: bool


class StrategyRuleOut(BaseModel):
    id: str
    name: str
    description: str
    strategy: str
    order: int


# ----------------------------------------------------------------- waves ----


class WaveMembershipOut(BaseModel):
    member_id: str
    member_kind: str
    strategy: Optional[str] = None
    execution_status: str
    order_index: int


class BlockedMigrationOut(BaseModel):
    id: int
    application_id: str
    reason_code: str
    reason_detail: str
    suggested_resolution: str
    dep_id: Optional[str] = None


class PreflightCheckOut(BaseModel):
    application_id: str
    check_name: str
    status: str
    detail: dict[str, Any]


class ApprovalOut(BaseModel):
    id: int
    subject_type: str
    subject_id: str
    requested_by: str
    requested_at: datetime
    status: str
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    comment: Optional[str] = None


class WaveOut(BaseModel):
    wave_number: int
    name: str
    status: str
    max_concurrent: int
    description: str
    approval_id: Optional[int] = None
    memberships: list[WaveMembershipOut] = Field(default_factory=list)
    blocked_count: int = 0
    preflight_summary: dict[str, int] = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    decided_by: str = "operator"
    comment: str = ""


class ExecuteWaveRequest(BaseModel):
    actor: str = "operator"


class ExecutionOut(BaseModel):
    id: int
    wave_number: int
    application_id: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    detail: dict[str, Any]


class ValidationResultOut(BaseModel):
    execution_id: int
    application_id: str
    check_name: str
    sequence_no: int
    status: str
    metric_value: Optional[float] = None
    tolerance: Optional[float] = None
    detail: dict[str, Any]


class ExecuteWaveResponse(BaseModel):
    wave_number: int
    wave_status: str
    executions: list[ExecutionOut]
    rolled_back: list[str]
    completed: list[str]


# ----------------------------------------------------------- target arch ----


class TargetArchitectureOut(BaseModel):
    application_id: str
    provider_profile: str
    spec: dict[str, Any]
    cost_delta_monthly: float
    yaml: str | None = None


# ----------------------------------------------------- ops / eval / audit ----


class OpportunityOut(BaseModel):
    id: int
    application_id: str
    title: str
    category: str
    impact: str
    effort: str
    description: str


class RiskOut(BaseModel):
    id: int
    application_id: Optional[str] = None
    wave_number: Optional[int] = None
    category: str
    description: str
    likelihood: str
    impact: str
    severity_score: float
    mitigation: str


class MetricsSummaryResponse(BaseModel):
    applications_assessed: int
    discovery_recall: Optional[float] = None
    discovery_precision: Optional[float] = None
    hidden_dependency_found: Optional[bool] = None
    strategy_accuracy: Optional[float] = None
    blocked_migrations_identified: int
    wave_conflicts_prevented: int
    modernization_opportunities: int
    pct_apps_off_eol_runtime_post_plan: Optional[float] = None
    migration_success_rate: Optional[float] = None
    rollback_count: int
    evaluation_passed: Optional[bool] = None
    last_evaluation_at: Optional[datetime] = None


class AuditActionOut(BaseModel):
    id: int
    ts: datetime
    actor: str
    action_type: str
    target: str
    high_risk: bool
    status: str


class ToolCallOut(BaseModel):
    id: int
    ts: datetime
    tool_name: str
    caller: str
    risk_level: str
    allowed: bool
    duration_ms: int
    result_summary: str
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
