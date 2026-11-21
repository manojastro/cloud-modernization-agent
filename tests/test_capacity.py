"""Cost/perf model: capacity estimator and post-migration latency tolerance."""
from app.migration.simulator import (
    CLOUD_COST_FACTOR,
    PERFORMANCE_TOLERANCE,
    RAM_GB_PER_SERVER,
    VCPU_PER_SERVER,
    baseline_latency_ms,
    capacity_estimate,
    projected_latency_ms,
    within_tolerance,
)
from app.models import Application


def make_app(runtime_id="go", servers=2, criticality=3, cost=24_000.0):
    return Application(
        id=f"{runtime_id}-{servers}-{criticality}", name="X", domain="d",
        business_owner="o", language="Go", framework="net/http",
        runtime_id=runtime_id, os_id="ubuntu-22", database_id=None,
        server_count=servers, api_surface="REST-internal", auth_method="sso",
        statefulness="stateless", compliance_scope="none", usage_per_day=1_000,
        monthly_usage_trend_pct=0.0, annual_infra_cost_usd=cost,
        criticality=criticality,
    )


def test_capacity_math():
    app = make_app(servers=4, cost=48_000.0)
    cap = capacity_estimate(app)
    assert cap.vcpu_total == 4 * VCPU_PER_SERVER
    assert cap.ram_gb_total == 4 * RAM_GB_PER_SERVER
    assert cap.container_replicas == min(max(2, cap.vcpu_total // 2), 24)
    expected_monthly = round(48_000.0 / 12 * CLOUD_COST_FACTOR, 2)
    assert abs(cap.est_monthly_cost_usd - expected_monthly) < 0.01


def test_replica_bounds():
    assert capacity_estimate(make_app(servers=1)).container_replicas >= 2
    big = capacity_estimate(make_app(servers=60))
    assert big.container_replicas <= 24


def test_projected_latency_stays_within_tolerance_for_every_criticality():
    for crit in range(1, 6):
        app = make_app(criticality=crit)
        base = baseline_latency_ms(app)
        proj = projected_latency_ms(app)
        assert within_tolerance(base, proj), (crit, base, proj)
        assert base * PERFORMANCE_TOLERANCE >= proj


def test_within_tolerance_boundary():
    assert within_tolerance(100.0, 125.0)          # exactly at tolerance passes
    assert not within_tolerance(100.0, 125.1)      # anything above fails
    assert within_tolerance(100.0, 80.0)           # faster is fine
