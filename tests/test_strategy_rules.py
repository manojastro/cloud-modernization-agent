"""Unit tests for the deterministic 7R rules table (the LLM never classifies)."""
from app.strategy.rules_7r import (
    RULES_TABLE,
    RULES_TABLE_VISIBLE,
    STRATEGIES,
    classify,
)


def ctx(**over):
    base = {
        "application_id": "t", "usage_per_day": 5_000, "criticality": 3,
        "monthly_usage_trend_pct": 0.0, "commodity_capability": False,
        "runtime_id": "python-flask", "os_id": "ubuntu-22",
        "change_frequency": "monthly", "last_change_months_ago": 3,
        "monolith_loc": 40_000, "debt_index": 20.0,
        "specialized_os_deps": False, "hypervisor_hosted": False,
        "runtime_eol": False, "os_eol": False, "db_compatibility": "direct",
        "managed_db_path": True, "statefulness": "stateless",
        "compliance_scope": "none",
    }
    base.update(over)
    return base


def test_all_seven_strategies_reachable():
    cases = {
        "RETIRE": ctx(usage_per_day=4, criticality=1, monthly_usage_trend_pct=-85),
        "REPURCHASE": ctx(commodity_capability=True),
        "RETAIN": ctx(runtime_id="cobol-mainframe", change_frequency="rare"),
        "REFACTOR": ctx(monolith_loc=850_000, debt_index=72.0, criticality=5),
        "RELOCATE": ctx(specialized_os_deps=True, hypervisor_hosted=True),
        "REPLATFORM": ctx(runtime_eol=True),
        "REHOST": ctx(),  # R07: healthy runtime, stateless, low debt
    }
    seen = {}
    for expected, c in cases.items():
        result = classify(c)
        assert result.strategy == expected, (
            expected, result.strategy, result.matched_rule_id)
        seen[expected] = result.matched_rule_id
    assert set(seen) == set(STRATEGIES)


def test_first_match_wins_and_alternatives_recorded():
    # An EOL runtime would also satisfy R08, but commodity REPURCHASE sits earlier.
    result = classify(ctx(commodity_capability=True, runtime_eol=True))
    assert result.strategy == "REPURCHASE"
    assert result.matched_rule_id == "R02-repurchase-commodity"
    assert "REPLATFORM" in result.alternatives


def test_r09_catch_all():
    # stateful + moderate debt defeats R07; nothing earlier matches -> default rehost
    result = classify(ctx(statefulness="session-replication", debt_index=55.0))
    assert result.strategy == "REHOST"
    assert result.matched_rule_id == "R09-default-rehost"


def test_confidence_bounds():
    for c in (ctx(), ctx(runtime_eol=True), ctx(commodity_capability=True)):
        result = classify(c)
        assert 0.5 <= result.confidence <= 0.97


def test_approval_flags_and_risk_levels():
    r01 = classify(ctx(usage_per_day=4, criticality=1, monthly_usage_trend_pct=-85))
    assert r01.requires_approval is True  # RETIRE is a business decision
    assert r01.risk_level == "medium"

    r04 = classify(ctx(monolith_loc=850_000, debt_index=72.0, criticality=5))
    assert r04.requires_approval is True
    assert r04.risk_level == "high"

    r07 = classify(ctx())
    assert r07.requires_approval is False
    assert r07.risk_level == "low"


def test_trace_is_complete_and_ordered():
    result = classify(ctx())
    assert len(result.rule_trace) == len(RULES_TABLE)
    assert [t["order"] for t in result.rule_trace] == list(range(1, len(RULES_TABLE) + 1))
    matched = [t for t in result.rule_trace if t["matched"]]
    assert matched and matched[0]["rule_id"] == result.matched_rule_id


def test_visible_table_covers_every_strategy():
    strategies_in_table = {r.strategy for r in RULES_TABLE}
    assert strategies_in_table == set(STRATEGIES)
    assert len(RULES_TABLE_VISIBLE) == len(RULES_TABLE)
    assert all(set(v) == {"id", "name", "description", "strategy"}
               for v in RULES_TABLE_VISIBLE)
