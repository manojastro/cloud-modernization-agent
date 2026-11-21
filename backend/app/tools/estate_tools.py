"""The estate tool belt: every capability an agent has, as audited registry tools.
No shell, no subprocess, no network: all handlers query the simulated estate."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.assessment.engine import assess_application
from app.graph import dependency_graph
from app.migration import simulator
from app.models import (
    AppRuntimeDetails, Application, Assessment, BatchJob, CMDBRecord,
    DatabaseRegistry, FileTransfer, MigrationExecution, NetworkFlow,
    StrategyRecommendation, ValidationResult, Wave,
)
from app.strategy.rules_7r import build_context, classify
from app.tools.base import ToolContext, ToolError, ToolRegistry, ToolRefused, ToolSpec
from app.waves.planner import plan_waves


def _app_or_404(session: Session, app_id: str) -> Application:
    app = session.get(Application, app_id)
    if app is None:
        raise LookupError(f"application '{app_id}' not found")
    return app


# ------------------------------------------------------------------ handlers

def _query_cmdb(args: dict, ctx: ToolContext) -> dict:
    q = ctx.session.query(CMDBRecord)
    if args.get("application_id"):
        q = q.filter(CMDBRecord.application_id == args["application_id"])
    if args.get("field"):
        q = q.filter(CMDBRecord.field == args["field"])
    rows = q.limit(2000).all()
    return {
        "count": len(rows),
        "records": [
            {"application_id": r.application_id, "service_id": r.service_id,
             "field": r.field, "value": r.value, "source_system": r.source_system}
            for r in rows
        ],
    }


def _query_network_flows(args: dict, ctx: ToolContext) -> dict:
    q = ctx.session.query(NetworkFlow)
    if args.get("src"):
        q = q.filter(NetworkFlow.src_app_id == args["src"])
    if args.get("dst"):
        q = q.filter(NetworkFlow.dst_node_id == args["dst"])
    rows = q.all()
    return {
        "count": len(rows),
        "flows": [
            {"src": f.src_app_id, "dst": f.dst_node_id, "dst_kind": f.dst_kind,
             "port": f.port, "protocol": f.protocol, "connections_daily": f.connections_daily}
            for f in rows
        ],
    }


def _query_batch_jobs(args: dict, ctx: ToolContext) -> dict:
    q = ctx.session.query(BatchJob)
    if args.get("application_id"):
        q = q.filter(BatchJob.application_id == args["application_id"])
    rows = q.all()
    return {
        "count": len(rows),
        "jobs": [
            {"application_id": j.application_id, "job_name": j.job_name,
             "schedule": j.schedule, "window_start": j.window_start,
             "duration_minutes": j.duration_minutes,
             "change_frequency": j.change_frequency,
             "last_change_months_ago": j.last_change_months_ago}
            for j in rows
        ],
    }


def _query_transfer_logs(args: dict, ctx: ToolContext) -> dict:
    q = ctx.session.query(FileTransfer)
    if args.get("src"):
        q = q.filter(FileTransfer.source_app_id == args["src"])
    rows = q.all()
    return {
        "count": len(rows),
        "transfers": [
            {"id": t.id, "source_app_id": t.source_app_id, "direction": t.direction,
             "remote_system": t.remote_system, "remote_path": t.remote_path,
             "frequency": t.frequency, "file_pattern": t.file_pattern,
             "avg_mb": t.avg_mb, "hour_of_day": t.hour_of_day}
            for t in rows
        ],
    }


def _build_dependency_graph(args: dict, ctx: ToolContext) -> dict:
    edges, stats = dependency_graph.discover_all(ctx.session)
    persisted = dependency_graph.persist_edges(ctx.session, edges)
    by_relation: dict[str, int] = {}
    for e in edges:
        by_relation[e["relation"]] = by_relation.get(e["relation"], 0) + 1
    hidden = [e for e in edges if e["discovered_by"] == "transfer-log-correlation"
              and e["relation"] == "APP_SENDS_FILE_TO"]
    return {
        "edges_persisted": persisted,
        "by_relation": by_relation,
        "correlation_stats": stats,
        "undocumented_file_dependencies": hidden,
    }


def _assess_application(args: dict, ctx: ToolContext) -> dict:
    session = ctx.session
    if args.get("application_id"):
        apps = [_app_or_404(session, args["application_id"])]
    else:
        apps = session.query(Application).order_by(Application.id).all()
    assessed = []
    for app in apps:
        a = assess_application(session, app)
        assessed.append({
            "application_id": app.id, "debt_index": a.debt_index,
            "complexity": a.complexity_label,
            "agentic_score": a.agentic_score, "agentic_band": a.agentic_band,
        })
    return {"assessed": len(assessed), "results": assessed[:500]}


def _classify_strategy(args: dict, ctx: ToolContext) -> dict:
    session = ctx.session
    if args.get("application_id"):
        apps = [_app_or_404(session, args["application_id"])]
    else:
        apps = session.query(Application).order_by(Application.id).all()
    out = []
    for app in apps:
        details = app.runtime_details
        db_meta = session.get(DatabaseRegistry, app.database_id) if app.database_id else None
        assessment = (session.query(Assessment)
                      .filter(Assessment.application_id == app.id)
                      .order_by(Assessment.id.desc()).first())
        fact_ctx = build_context(app, details, db_meta)
        fact_ctx["debt_index"] = assessment.debt_index if assessment else 0.0
        result = classify(fact_ctx)
        existing = (session.query(StrategyRecommendation)
                    .filter(StrategyRecommendation.application_id == app.id).first())
        if existing is None:
            existing = StrategyRecommendation(application_id=app.id)
            session.add(existing)
        existing.strategy = result.strategy
        existing.confidence = result.confidence
        existing.matched_rule_id = result.matched_rule_id
        existing.reasons = result.reasons
        existing.alternatives = result.alternatives
        existing.rule_trace = result.rule_trace
        existing.risk_level = result.risk_level
        existing.requires_approval = result.requires_approval
        out.append({"application_id": app.id, "strategy": result.strategy,
                    "confidence": result.confidence,
                    "matched_rule_id": result.matched_rule_id})
    return {"classified": len(out), "results": out}


def _plan_waves(args: dict, ctx: ToolContext) -> dict:
    result = plan_waves(ctx.session)
    return {
        "waves": result.waves,
        "memberships": len(result.memberships),
        "blocked": [
            {k: v for k, v in b.items() if k != "resolved"} for b in result.blocked
        ],
        "constraint_moves": result.constraint_moves,
    }


def _preflight(args: dict, ctx: ToolContext) -> dict:
    try:
        return simulator.preflight_wave(ctx.session, int(args["wave_number"]))
    except LookupError as exc:
        raise ToolError(str(exc)) from exc


def _execute_wave(args: dict, ctx: ToolContext) -> dict:
    wave_number = int(args["wave_number"])
    wave = ctx.session.query(Wave).filter(Wave.wave_number == wave_number).first()
    if wave is None:
        raise ToolError(f"wave {wave_number} not found")
    if wave.status != "APPROVED":
        raise ToolRefused(
            f"wave {wave_number} is '{wave.status}'; execute_wave requires APPROVED "
            "(human approval gate)")
    return simulator.execute_wave(ctx.session, wave_number, actor=ctx.actor)


def _validate_migration(args: dict, ctx: ToolContext) -> dict:
    q = ctx.session.query(ValidationResult)
    execs: list[MigrationExecution] = []
    if args.get("execution_id"):
        q = q.filter(ValidationResult.execution_id == args["execution_id"])
        execs = (ctx.session.query(MigrationExecution)
                 .filter(MigrationExecution.id == args["execution_id"]).all())
    elif args.get("wave_number"):
        n = int(args["wave_number"])
        execs = (ctx.session.query(MigrationExecution)
                 .filter(MigrationExecution.wave_number == n).all())
        q = q.filter(ValidationResult.execution_id.in_(
            [e.id for e in execs] or [-1]))
    else:
        raise ToolRefused("provide execution_id or wave_number")
    rows = q.order_by(ValidationResult.execution_id,
                      ValidationResult.sequence_no).all()
    return {
        "validations": [
            {"execution_id": r.execution_id, "application_id": r.application_id,
             "check_name": r.check_name, "sequence_no": r.sequence_no,
             "status": r.status, "metric_value": r.metric_value,
             "tolerance": r.tolerance, "detail": r.detail}
            for r in rows
        ],
        "executions": [
            {"id": e.id, "wave_number": e.wave_number, "application_id": e.application_id,
             "status": e.status}
            for e in execs
        ],
    }


def _rollback_app(args: dict, ctx: ToolContext) -> dict:
    session = ctx.session
    app_id = args["application_id"]
    allowed, why = simulator.can_rollback_app(session, app_id)
    if not allowed:
        raise ToolRefused(f"rollback refused for '{app_id}': {why}")
    latest = (session.query(MigrationExecution)
              .filter(MigrationExecution.application_id == app_id)
              .order_by(MigrationExecution.id.desc()).first())
    app = _app_or_404(session, app_id)
    simulator._rollback(session, latest, app,
                        args.get("reason", "operator-requested rollback"),
                        str(args.get("reason", "operator-requested rollback")))
    return {"rolled_back": app_id, "placement": app.placement}


def _generate_target_architecture(args: dict, ctx: ToolContext) -> dict:
    from app.targetarch.generator import generate_for_app

    provider = args.get("provider") or "aws"
    row = generate_for_app(ctx.session, args["application_id"], provider)
    return {
        "application_id": row.application_id, "provider_profile": row.provider_profile,
        "cost_delta_monthly": row.cost_delta_monthly, "spec": row.spec,
    }


# ------------------------------------------------------------------ registry

def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(ToolSpec(
        name="query_cmdb", purpose="Query CMDB-like inventory records for applications "
        "and platform services.",
        input_schema={"application_id": "string", "field": "string"},
        permission="estate:read", risk_level="LOW", timeout_seconds=15,
        handler=_query_cmdb))

    reg.register(ToolSpec(
        name="query_network_flows", purpose="Query observed network flow logs "
        "(who-calls-whom evidence).",
        input_schema={"src": "string", "dst": "string"},
        permission="estate:read", risk_level="LOW", timeout_seconds=15,
        handler=_query_network_flows))

    reg.register(ToolSpec(
        name="query_batch_jobs", purpose="Query the batch scheduler extract.",
        input_schema={"application_id": "string"},
        permission="estate:read", risk_level="LOW", timeout_seconds=15,
        handler=_query_batch_jobs))

    reg.register(ToolSpec(
        name="query_transfer_logs", purpose="Query file-transfer logs (SFTP hub traffic).",
        input_schema={"src": "string"},
        permission="estate:read", risk_level="LOW", timeout_seconds=15,
        handler=_query_transfer_logs))

    reg.register(ToolSpec(
        name="build_dependency_graph", purpose="Correlate CMDB + flows + transfer logs + "
        "scheduler extracts into the persisted dependency graph; surfaces undocumented "
        "file dependencies.",
        input_schema={},
        permission="graph:write", risk_level="MEDIUM", timeout_seconds=60,
        handler=_build_dependency_graph))

    reg.register(ToolSpec(
        name="assess_application", purpose="Run the deterministic assessment engine "
        "(dimension scores, debt index, agentic readiness) for one or all applications.",
        input_schema={"application_id": "string"},
        permission="assessment:write", risk_level="LOW", timeout_seconds=120,
        handler=_assess_application))

    reg.register(ToolSpec(
        name="classify_strategy", purpose="Classify one or all applications into the 7R "
        "strategy using the visible deterministic rules table.",
        input_schema={"application_id": "string"},
        permission="assessment:write", risk_level="LOW", timeout_seconds=60,
        handler=_classify_strategy))

    reg.register(ToolSpec(
        name="plan_waves", purpose="(Re)plan migration waves under constraints; produces "
        "memberships and BlockedMigration records.",
        input_schema={},
        permission="planning:write", risk_level="MEDIUM", timeout_seconds=60,
        handler=_plan_waves))

    reg.register(ToolSpec(
        name="simulate_migration_preflight", purpose="Run pre-flight checks for a wave "
        "(dependencies, zones, identity, DB plan, capacity, controls, rollback plan).",
        input_schema={"wave_number": "integer"}, required_args=["wave_number"],
        permission="migration:write", risk_level="MEDIUM", timeout_seconds=60,
        handler=_preflight))

    reg.register(ToolSpec(
        name="execute_wave", purpose="Execute an APPROVED wave: mutate placements, run "
        "validations, auto-roll back failures.",
        input_schema={"wave_number": "integer"}, required_args=["wave_number"],
        permission="migration:execute", risk_level="HIGH", timeout_seconds=300,
        handler=_execute_wave))

    reg.register(ToolSpec(
        name="validate_migration", purpose="Read post-migration validation results for an "
        "execution or whole wave.",
        input_schema={"execution_id": "integer", "wave_number": "integer"},
        permission="migration:read", risk_level="LOW", timeout_seconds=30,
        handler=_validate_migration))

    reg.register(ToolSpec(
        name="rollback_app", purpose="Roll back a failed/running migration to its on-prem "
        "placement. Gated: requires a failed or running execution.",
        input_schema={"application_id": "string", "reason": "string"},
        required_args=["application_id"],
        permission="migration:rollback", risk_level="HIGH", timeout_seconds=60,
        handler=_rollback_app))

    reg.register(ToolSpec(
        name="generate_target_architecture", purpose="Generate the structured target "
        "architecture spec for an application under a provider profile (aws|azure|gcp).",
        input_schema={"application_id": "string", "provider": "string"},
        required_args=["application_id"],
        permission="targetarch:write", risk_level="LOW", timeout_seconds=30,
        handler=_generate_target_architecture))

    return reg
