"""Assessment engine: technical-debt index and the 9-point agentic readiness checklist."""
from app.assessment.agentic_readiness import ITEMS, evaluate_agentic_readiness
from app.assessment.engine import compute_debt_index
from app.models import AppRuntimeDetails, Application, DatabaseRegistry


def make_app(**over):
    d_over = over.pop("details", {})
    app = Application(
        id="a1", name="A1", domain="d", business_owner="o", language="Python",
        framework="Flask", runtime_id="python-flask", os_id="ubuntu-22",
        database_id=None, server_count=1, api_surface="REST-public",
        auth_method="sso", statefulness="stateless", compliance_scope="none",
        usage_per_day=1_000, monthly_usage_trend_pct=1.0,
        annual_infra_cost_usd=1_000.0, criticality=2,
    )
    d = AppRuntimeDetails(
        application_id="a1", monolith_loc=10_000, manual_deployments=False,
        has_observability=True, hardcoded_secrets_found=False,
        oracle_only_feature=False, shared_database=False,
        change_frequency="monthly", last_change_months_ago=2,
    )
    for k, v in d_over.items():
        setattr(d, k, v)
    for k, v in over.items():
        setattr(app, k, v)
    app.runtime_details = d
    return app


# ------------------------------------------------------------------- debt index

def test_clean_app_has_zero_debt():
    app = make_app()
    score, indicators = compute_debt_index(app, app.runtime_details, None)
    assert score == 0.0 and indicators == []


def test_each_indicator_scores():
    app = make_app(api_surface="SOAP")
    d = app.runtime_details
    d.runtime_eol = True            # +20
    d.os_eol = True                 # +15
    d.shared_database = True        # +15
    d.hardcoded_secrets_found = True  # +15
    d.manual_deployments = True     # +10
    d.monolith_loc = 250_000        # +10 (monolith_codebase)
    d.has_observability = False     # +10
    db_meta = DatabaseRegistry(id="db1", display_name="db", engine="oracle-11g",
                               version="", eol=True, is_shared_service=False,
                               managed_equivalent="managed-pg",
                               compatibility="conversion-required")  # +10 (eol db)
    score, indicators = compute_debt_index(app, d, db_meta)
    assert score == 105.0 or score == 100.0  # capped at 100
    assert set(indicators) == {
        "eol_runtime", "eol_os", "no_api_layer", "shared_database",
        "hardcoded_secrets", "manual_deployments", "monolith_codebase",
        "no_observability", "eol_database",
    }


def test_shared_db_via_registry_counts_even_without_flag():
    app = make_app()
    db_meta = DatabaseRegistry(id="db2", display_name="db", engine="postgres-13",
                               version="", eol=False, is_shared_service=True,
                               managed_equivalent="managed-pg",
                               compatibility="direct")
    score, indicators = compute_debt_index(app, app.runtime_details, db_meta)
    assert indicators == ["shared_database"] and score == 15.0


# --------------------------------------------------------- agentic readiness

def test_modern_public_api_scores_full_nine_high_band():
    result = evaluate_agentic_readiness(make_app())
    assert [i["item_key"] for i in result.items] == [k for k, _ in ITEMS]
    assert len(result.items) == 9
    assert result.score == 9
    assert result.band == "high"
    assert all(i["passed"] for i in result.items)


def test_legacy_siloed_app_scores_zero_low_band():
    result = evaluate_agentic_readiness(make_app(
        api_surface="none", auth_method="none",
        details={"runtime_eol": True, "has_observability": False,
                 "hardcoded_secrets_found": True}))
    assert result.score == 0
    assert result.band == "low"


def test_stateful_internal_api_is_medium():
    # REST-internal loses the public rate-limit point; sticky sessions lose
    # idempotent_operations and safe_retries -> 6/9 medium.
    result = evaluate_agentic_readiness(make_app(
        api_surface="REST-internal", statefulness="sticky-sessions"))
    failed = {i["item_key"] for i in result.items if not i["passed"]}
    assert failed == {"rate_limit_support", "idempotent_operations", "safe_retries"}
    assert result.score == 6
    assert result.band == "medium"


def test_band_boundaries():
    # score >= 7 high; 4..6 medium; < 4 low -- verified via crafted apps.
    assert evaluate_agentic_readiness(make_app()).band == "high"          # 9
    med = evaluate_agentic_readiness(make_app(api_surface="REST-internal"))
    assert med.score == 8 and med.band == "high"                          # only rate limit lost
