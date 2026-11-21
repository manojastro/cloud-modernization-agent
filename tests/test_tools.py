"""Tool registry: allow-list, risk gating, argument validation and audit trail."""
import pytest

from app.models import ToolCall
from app.tools.base import ToolContext, ToolRefused, get_registry


@pytest.fixture()
def registry():
    return get_registry()


def ctx(session, approved=False):
    return ToolContext(session=session, actor="tester", approved=approved)


def test_registry_has_expected_tools(registry):
    names = {s["name"] for s in registry.specs()}
    expected = {
        "query_cmdb", "query_network_flows", "query_batch_jobs", "query_transfer_logs",
        "build_dependency_graph", "assess_application", "classify_strategy",
        "plan_waves", "simulate_migration_preflight", "execute_wave",
        "validate_migration", "rollback_app", "generate_target_architecture",
    }
    assert expected <= names
    risks = {s["name"]: s["risk_level"] for s in registry.specs()}
    assert risks["execute_wave"] == "HIGH"
    assert risks["rollback_app"] == "HIGH"
    assert risks["query_cmdb"] == "LOW"


def test_unknown_tool_is_refused_and_audited(seeded, registry):
    session = seeded
    with pytest.raises(ToolRefused):
        registry.run("delete_everything", {}, ctx(session))
    session.flush()  # sessions run with autoflush=False
    row = (session.query(ToolCall).filter_by(tool_name="delete_everything")
           .order_by(ToolCall.id.desc()).first())
    assert row is not None and row.allowed is False
    assert "unknown tool" in row.error


def test_high_risk_tool_refused_without_approval(seeded, registry):
    session = seeded
    with pytest.raises(ToolRefused) as excinfo:
        registry.run("execute_wave", {"wave_number": 0}, ctx(session))
    assert "high-risk" in str(excinfo.value)
    session.flush()
    row = (session.query(ToolCall).filter_by(tool_name="execute_wave")
           .order_by(ToolCall.id.desc()).first())
    assert row.allowed is False and row.risk_level == "HIGH"


def test_missing_required_args_refused(seeded, registry):
    session = seeded
    # simulate_migration_preflight requires wave_number
    with pytest.raises(ToolRefused) as excinfo:
        registry.run("simulate_migration_preflight", {}, ctx(session))
    assert "missing required arguments" in str(excinfo.value)


def test_wrong_arg_type_refused(seeded, registry):
    session = seeded
    with pytest.raises(ToolRefused) as excinfo:
        registry.run("simulate_migration_preflight", {"wave_number": "zero"},
                     ctx(session))
    assert "must be integer" in str(excinfo.value)


def test_low_risk_tool_runs_and_audits_success(seeded, registry):
    session = seeded
    result = registry.run("query_transfer_logs", {"limit": 5}, ctx(session))
    assert result["count"] > 0  # the estate always contains transfer rows
    session.flush()
    row = (session.query(ToolCall).filter_by(tool_name="query_transfer_logs")
           .order_by(ToolCall.id.desc()).first())
    assert row.allowed is True and row.caller == "tester"
    assert row.duration_ms >= 0


def test_secret_looking_arguments_are_redacted_in_audit(seeded, registry):
    session = seeded
    registry.run("query_cmdb",
                 {"application_id": "payments-api-gateway", "api_key": "super-secret"},
                 ctx(session))
    session.flush()
    row = (session.query(ToolCall).filter_by(tool_name="query_cmdb")
           .order_by(ToolCall.id.desc()).first())
    import json

    args = json.loads(row.arguments) if isinstance(row.arguments, str) else row.arguments
    assert args["api_key"] == "***redacted***"
    assert args["application_id"] == "payments-api-gateway"


def test_handler_error_is_audited_and_wrapped(seeded, registry):
    from app.tools.base import ToolError

    session = seeded
    with pytest.raises((ToolRefused, ToolError)):
        registry.run("classify_strategy", {"application_id": "nope-not-here"},
                     ctx(session))
