"""SQLAlchemy ORM models. All persistence for the estate, assessment pipeline, waves,
migrations, workflow, audit and evaluation lives here."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- estate ----

class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    business_owner: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(60), nullable=False)
    framework: Mapped[str] = mapped_column(String(120), nullable=False)
    runtime_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    os_id: Mapped[str] = mapped_column(String(40), nullable=False)
    database_id: Mapped[str | None] = mapped_column(ForeignKey("databases_registry.id"), nullable=True)

    server_count: Mapped[int] = mapped_column(Integer, default=1)
    api_surface: Mapped[str] = mapped_column(String(30), default="none")  # none|SOAP|REST-internal|REST-public|gRPC|batch-only
    auth_method: Mapped[str] = mapped_column(String(20), default="none")  # none|basic|ldap|local-db|sso
    statefulness: Mapped[str] = mapped_column(String(30), default="stateless")  # stateless|sticky-sessions|session-replication
    compliance_scope: Mapped[str] = mapped_column(String(40), default="none")  # none|PCI|PII|PCI+PII
    usage_per_day: Mapped[int] = mapped_column(Integer, default=1000)
    monthly_usage_trend_pct: Mapped[float] = mapped_column(Float, default=0.0)
    annual_infra_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    criticality: Mapped[int] = mapped_column(Integer, default=3)  # 1 lowest .. 5 mission critical

    commodity_capability: Mapped[bool] = mapped_column(Boolean, default=False)
    specialized_os_deps: Mapped[bool] = mapped_column(Boolean, default=False)
    hypervisor_hosted: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_wave_override: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lifecycle: Mapped[str] = mapped_column(String(20), default="active")  # active|retain-on-mainframe
    placement: Mapped[str] = mapped_column(String(40), default="on-prem")  # on-prem|cloud-managed
    description: Mapped[str] = mapped_column(Text, default="")

    database = relationship("DatabaseRegistry", lazy="joined")
    runtime_details: Mapped["AppRuntimeDetails | None"] = relationship(
        "AppRuntimeDetails", back_populates="application", uselist=False, lazy="joined"
    )


class AppRuntimeDetails(Base):
    __tablename__ = "app_runtime_details"

    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), primary_key=True)
    runtime_family: Mapped[str] = mapped_column(String(60))
    runtime_version: Mapped[str] = mapped_column(String(80))
    runtime_eol: Mapped[bool] = mapped_column(Boolean, default=False)
    os_family: Mapped[str] = mapped_column(String(60))
    os_eol: Mapped[bool] = mapped_column(Boolean, default=False)
    deployment_type: Mapped[str] = mapped_column(String(40))  # app-server|iis|vm|mainframe-batch|jar
    monolith_loc: Mapped[int] = mapped_column(Integer, default=0)
    manual_deployments: Mapped[bool] = mapped_column(Boolean, default=False)
    has_observability: Mapped[bool] = mapped_column(Boolean, default=False)
    hardcoded_secrets_found: Mapped[bool] = mapped_column(Boolean, default=False)
    oracle_only_feature: Mapped[bool] = mapped_column(Boolean, default=False)
    shared_database: Mapped[bool] = mapped_column(Boolean, default=False)
    change_frequency: Mapped[str] = mapped_column(String(20), default="monthly")  # rare|monthly|weekly|daily
    last_change_months_ago: Mapped[int] = mapped_column(Integer, default=6)

    application = relationship("Application", back_populates="runtime_details")


class DatabaseRegistry(Base):
    __tablename__ = "databases_registry"

    id: Mapped[str] = mapped_column(String(90), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(140))
    engine: Mapped[str] = mapped_column(String(50))  # oracle-11g|sqlserver-2014|mysql-5.7|postgres-13|db2|flat-files
    version: Mapped[str] = mapped_column(String(40), default="")
    eol: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shared_service: Mapped[bool] = mapped_column(Boolean, default=False)
    managed_equivalent: Mapped[str | None] = mapped_column(String(120), nullable=True)
    compatibility: Mapped[str] = mapped_column(String(30), default="direct")  # direct|conversion-required|none


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    hostname: Mapped[str] = mapped_column(String(120))
    cpu_cores: Mapped[int] = mapped_column(Integer, default=4)
    ram_gb: Mapped[int] = mapped_column(Integer, default=16)
    environment: Mapped[str] = mapped_column(String(20), default="prod")
    zone: Mapped[str] = mapped_column(String(40), default="general")


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(90), index=True)
    target_id: Mapped[str] = mapped_column(String(90), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # sync-api|event|file|database
    transport: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    job_name: Mapped[str] = mapped_column(String(140))
    schedule: Mapped[str] = mapped_column(String(60), default="daily")
    window_start: Mapped[str] = mapped_column(String(10), default="01:00")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=45)
    change_frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    last_change_months_ago: Mapped[int] = mapped_column(Integer, default=8)


class FileTransfer(Base):
    __tablename__ = "file_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_app_id: Mapped[str] = mapped_column(String(90), index=True)  # app that pushes the file (log identity)
    direction: Mapped[str] = mapped_column(String(10), default="send")
    remote_system: Mapped[str] = mapped_column(String(90), default="sftp-hub")
    remote_path: Mapped[str] = mapped_column(String(240), default="")
    frequency: Mapped[str] = mapped_column(String(30), default="nightly")
    file_pattern: Mapped[str] = mapped_column(String(120), default="")
    avg_mb: Mapped[float] = mapped_column(Float, default=12.0)
    hour_of_day: Mapped[int] = mapped_column(Integer, default=2)


class NetworkFlow(Base):
    __tablename__ = "network_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    src_app_id: Mapped[str] = mapped_column(String(90), index=True)
    dst_node_id: Mapped[str] = mapped_column(String(90), index=True)
    dst_kind: Mapped[str] = mapped_column(String(20), default="application")  # application|service
    port: Mapped[int] = mapped_column(Integer, default=443)
    protocol: Mapped[str] = mapped_column(String(20), default="https")
    connections_daily: Mapped[int] = mapped_column(Integer, default=5000)


class CMDBRecord(Base):
    __tablename__ = "cmdb_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str | None] = mapped_column(String(90), nullable=True, index=True)
    service_id: Mapped[str | None] = mapped_column(String(90), nullable=True)
    field: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(Text, default="")
    source_system: Mapped[str] = mapped_column(String(60), default="cmdb-sim")
    confidence: Mapped[float] = mapped_column(Float, default=0.9)


class SharedService(Base):
    __tablename__ = "shared_services"

    id: Mapped[str] = mapped_column(String(90), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(140))
    kind: Mapped[str] = mapped_column(String(40))  # identity|messaging|file-transfer|database|monitoring|sso
    description: Mapped[str] = mapped_column(Text, default="")
    wave_assignment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replacement_note: Mapped[str] = mapped_column(String(240), default="")


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    src: Mapped[str] = mapped_column(String(90), index=True)
    dst: Mapped[str] = mapped_column(String(90), index=True)
    relation: Mapped[str] = mapped_column(String(40))
    discovered_by: Mapped[str] = mapped_column(String(60), default="cmdb")
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    note: Mapped[str] = mapped_column(String(300), default="")


# ------------------------------------------------------------ assessment ----

class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    debt_index: Mapped[float] = mapped_column(Float, default=0.0)
    complexity_score: Mapped[float] = mapped_column(Float, default=0.0)
    complexity_label: Mapped[str] = mapped_column(String(20), default="low")
    agentic_score: Mapped[int] = mapped_column(Integer, default=0)
    agentic_band: Mapped[str] = mapped_column(String(20), default="low")
    indicators: Mapped[list] = mapped_column(JSON, default=list)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgenticReadinessItem(Base):
    __tablename__ = "agentic_readiness_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(140))
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(300), default="")


class StrategyRecommendation(Base):
    __tablename__ = "strategy_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    strategy: Mapped[str] = mapped_column(String(20))  # REHOST|REPLATFORM|REFACTOR|REPURCHASE|RETAIN|RETIRE|RELOCATE
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    matched_rule_id: Mapped[str] = mapped_column(String(40), default="")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    rule_trace: Mapped[list] = mapped_column(JSON, default=list)
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ------------------------------------------------------------------ waves ----

class Wave(Base):
    __tablename__ = "waves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wave_number: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="PLANNED")
    # PLANNED|VALIDATING|AWAITING_APPROVAL|APPROVED|EXECUTING|VERIFYING|COMPLETED|FAILED
    max_concurrent: Mapped[int] = mapped_column(Integer, default=24)
    description: Mapped[str] = mapped_column(Text, default="")
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    memberships: Mapped[list["WaveMembership"]] = relationship(back_populates="wave")


class WaveMembership(Base):
    __tablename__ = "wave_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wave_id: Mapped[int] = mapped_column(ForeignKey("waves.id"), index=True)
    member_id: Mapped[str] = mapped_column(String(90), index=True)
    member_kind: Mapped[str] = mapped_column(String(20), default="application")  # application|service
    strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    execution_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    wave = relationship("Wave", back_populates="memberships")


class BlockedMigration(Base):
    __tablename__ = "blocked_migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(String(90), index=True)
    reason_code: Mapped[str] = mapped_column(String(60))
    reason_detail: Mapped[str] = mapped_column(Text, default="")
    suggested_resolution: Mapped[str] = mapped_column(Text, default="")
    dep_id: Mapped[str | None] = mapped_column(String(90), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class PreflightCheck(Base):
    __tablename__ = "preflight_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wave_number: Mapped[int] = mapped_column(Integer, index=True)
    application_id: Mapped[str] = mapped_column(String(90), index=True)
    check_name: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10))  # PASS|BLOCKED
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class MigrationExecution(Base):
    __tablename__ = "migration_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wave_number: Mapped[int] = mapped_column(Integer, index=True)
    application_id: Mapped[str] = mapped_column(String(90), index=True)
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    # RUNNING|COMPLETED|FAILED|ROLLED_BACK
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("migration_executions.id"), index=True)
    application_id: Mapped[str] = mapped_column(String(90), index=True)
    check_name: Mapped[str] = mapped_column(String(60))
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12))  # PASS|FAIL|SKIPPED
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class TargetArchitecture(Base):
    __tablename__ = "target_architectures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(String(90), index=True)
    provider_profile: Mapped[str] = mapped_column(String(20), default="aws")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_delta_monthly: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ModernizationOpportunity(Base):
    __tablename__ = "modernization_opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(String(90), index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60))
    impact: Mapped[str] = mapped_column(String(20), default="medium")  # high|medium|low
    effort: Mapped[str] = mapped_column(String(20), default="medium")
    description: Mapped[str] = mapped_column(Text, default="")
    source_facts: Mapped[list] = mapped_column(JSON, default=list)


class Risk(Base):
    __tablename__ = "risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str | None] = mapped_column(String(90), nullable=True, index=True)
    wave_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    likelihood: Mapped[str] = mapped_column(String(20), default="possible")  # unlikely|possible|likely
    impact: Mapped[str] = mapped_column(String(20), default="moderate")  # minor|moderate|major
    severity_score: Mapped[float] = mapped_column(Float, default=0.0)
    mitigation: Mapped[str] = mapped_column(Text, default="")


class DomainEvent(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    subject: Mapped[str] = mapped_column(String(120), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------- workflow ----

class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(30))  # assessment|wave_migration
    subject: Mapped[str] = mapped_column(String(90))
    state: Mapped[str] = mapped_column(String(30), default="DETECTED")
    current_stage: Mapped[str] = mapped_column(String(60), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    stage_runs: Mapped[list["StageRun"]] = relationship(back_populates="investigation")


class StageRun(Base):
    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id"), index=True)
    stage: Mapped[str] = mapped_column(String(60))
    agent: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|error
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    input_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    investigation = relationship("Investigation", back_populates="stage_runs")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    application_id: Mapped[str | None] = mapped_column(String(90), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(80))
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    fact: Mapped[str] = mapped_column(Text)
    reliability: Mapped[str] = mapped_column(String(20), default="high")  # high|medium|low
    raw_reference: Mapped[str] = mapped_column(String(240), default="")


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    application_id: Mapped[str | None] = mapped_column(String(90), nullable=True, index=True)
    decision_type: Mapped[str] = mapped_column(String(60), default="strategy")
    decision: Mapped[str] = mapped_column(String(120))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(String(30), default="wave")
    subject_id: Mapped[str] = mapped_column(String(90), index=True)  # e.g. "wave-1"
    requested_by: Mapped[str] = mapped_column(String(80), default="migration-agent")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING|APPROVED|REJECTED
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    action_type: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120), default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    high_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="ok")


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id"), index=True)
    outcome_type: Mapped[str] = mapped_column(String(60))
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    snapshot_kind: Mapped[str] = mapped_column(String(40), default="assessment")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    results: Mapped[dict] = mapped_column(JSON, default=dict)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (UniqueConstraint("id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    tool_name: Mapped[str] = mapped_column(String(60), index=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    caller: Mapped[str] = mapped_column(String(80), default="system")
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
