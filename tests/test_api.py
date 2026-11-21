"""HTTP API contract: meta, seed, portfolio, strategies, waves, approvals, evaluation."""
import pytest


@pytest.fixture()
def loaded_client(client):
    """Seeded estate + full pipeline, driven through the public API."""
    resp = client.post("/api/v1/simulator/seed", json={"size": 40})
    assert resp.status_code == 200, resp.text
    resp = client.post("/api/v1/pipeline/run")
    assert resp.status_code == 200, resp.text
    return client


# ------------------------------------------------------------------ meta/ops

def test_meta_declares_mock_mode(client):
    data = client.get("/api/v1/meta").json()
    assert data["badge"] == "MOCK MODE"
    assert data["mock_mode"] is True and data["llm_mode"] == "mock"
    assert data["estate_seeded"] is False and data["application_count"] == 0


def test_health_readiness_metrics(client):
    assert client.get("/health").json()["status"] == "ok"
    body = client.get("/readiness").json()
    assert body["ready"] is False  # empty estate: database ok, nothing seeded yet
    assert body["checks"]["database"] is True
    text = client.get("/metrics").text
    assert "# HELP" in text and "# TYPE" in text


def test_meta_after_seed(seeded_client):
    data = seeded_client.get("/api/v1/meta").json()
    assert data["estate_seeded"] is True and data["application_count"] >= 12


# ------------------------------------------------------------------ seed/portfolio

def test_seed_rejects_out_of_range_size(client):
    assert client.post("/api/v1/simulator/seed", json={"size": 5}).status_code == 422
    assert client.post("/api/v1/simulator/seed", json={"size": 100_000}).status_code == 422


def test_portfolio_filters_and_sorting(loaded_client):
    c = loaded_client
    all_apps = c.get("/api/v1/applications?limit=400").json()
    assert all_apps["total"] >= 40 and len(all_apps["items"]) == all_apps["total"]

    filtered = c.get("/api/v1/applications",
                     params={"q": "payments"}).json()
    assert 0 < filtered["total"] < all_apps["total"]
    assert all("payment" in i["id"] or "payment" in i["name"].lower()
               or "payment" in i["domain"].lower()
               for i in filtered["items"])

    by_crit = c.get("/api/v1/applications",
                    params={"sort": "criticality", "limit": 10}).json()
    crits = [i["criticality"] for i in by_crit["items"]]
    assert crits == sorted(crits, reverse=True)

    # unknown sort key -> 422 (explicit validation, not a silent fallback)
    assert c.get("/api/v1/applications",
                 params={"sort": "nonsense"}).status_code == 422

    detail = c.get("/api/v1/applications/payments-api-gateway")
    assert detail.status_code == 200
    assert detail.json()["id"] == "payments-api-gateway"
    assert c.get("/api/v1/applications/does-not-exist").status_code == 404


def test_graph_endpoint_lists_hidden_dependency(loaded_client):
    data = loaded_client.get("/api/v1/graph").json()
    edges = data["edges"]
    hidden = [e for e in edges
              if e["discovered_by"] == "transfer-log-correlation"
              and e["relation"] == "APP_SENDS_FILE_TO"]
    assert any(e["src"] == "warehouse-inventory-sync"
               and e["dst"] == "partner-portal" for e in hidden)


# ------------------------------------------------------- assessments/strategies

def test_assessment_endpoints(loaded_client):
    rows = loaded_client.get("/api/v1/assessments").json()
    assert len(rows) >= 40
    one = loaded_client.get("/api/v1/assessments/payments-api-gateway").json()
    assert one["application_id"] == "payments-api-gateway"
    assert 0 <= one["agentic_score"] <= 9
    assert one["agentic_band"] in ("low", "medium", "high")
    assert set(one["dimensions"]) >= {"technical_debt_index", "security_posture"}
    assert loaded_client.get("/api/v1/assessments/nope").status_code == 404


def test_strategy_rules_visible_and_classifications(loaded_client):
    rules = loaded_client.get("/api/v1/strategy-rules").json()
    ids = [r["id"] for r in rules]
    assert len(rules) == 9 and ids[0].startswith("R01") and ids[-1].startswith("R09")

    strategies = {s["application_id"]: s for s in
                  loaded_client.get("/api/v1/strategies").json()}
    assert strategies["legacy-report-archive"]["strategy"] == "RETIRE"
    assert strategies["sftp-drop-hub"]["strategy"] == "REPURCHASE"
    assert strategies["core-ledger-batch"]["strategy"] == "RETAIN"
    # the LLM never decides: every classification cites its rule id
    assert all(s["matched_rule_id"].startswith(("R0", "R1"))
               for s in strategies.values())


# ------------------------------------------------------------- waves lifecycle

def test_full_wave_lifecycle_over_http(loaded_client):
    c = loaded_client

    waves = c.get("/api/v1/waves").json()
    assert [w["wave_number"] for w in waves] == [0, 1, 2, 3]
    # the pipeline preflights every wave; nothing is APPROVED/EXECUTED yet
    assert all(w["status"] in ("PLANNED", "AWAITING_APPROVAL") for w in waves)

    blocked = {b["application_id"]: b["reason_code"]
               for b in c.get("/api/v1/blocked").json()}
    assert blocked == {"commission-settlement-engine": "DEPENDENCY_IN_LATER_WAVE",
                       "card-dispute-tracker": "SECURITY_ZONE_NOT_READY"}

    # preflight wave 0 -> AWAITING_APPROVAL; execute before approval -> 409
    checks = c.post("/api/v1/waves/0/preflight").json()
    assert checks["applications"] >= 1
    assert c.post("/api/v1/waves/0/execute").status_code == 409

    approvals = c.get("/api/v1/approvals").json()
    pending = [a for a in approvals if a["status"] == "PENDING"
               and a["subject_id"] == "wave-0"]
    assert pending, "preflight must raise a human approval request"

    approved = c.post(f"/api/v1/approvals/{pending[0]['id']}/approve",
                      json={"decided_by": "http-tester", "comment": "go"}).json()
    assert approved["status"] == "APPROVED"

    out = c.post("/api/v1/waves/0/execute", json={"actor": "http-tester"}).json()
    assert out["wave_status"] == "COMPLETED"

    execs = c.get("/api/v1/executions?wave_number=0").json()
    assert execs and all(e["wave_number"] == 0 for e in execs)
    vals = c.get("/api/v1/validations",
                 params={"wave_number": 0}).json()
    assert vals, "executed apps must have validation rows"


def test_approve_requires_pending_approval(loaded_client):
    c = loaded_client
    missing = c.post("/api/v1/approvals/999999/approve", json={})
    assert missing.status_code == 404


def test_validation_endpoint_requires_filter(seeded_client):
    resp = seeded_client.get("/api/v1/validations")
    assert resp.status_code == 422


# ------------------------------------------------------------ target architecture

def test_target_architecture_providers(loaded_client):
    c = loaded_client
    seen = set()
    for provider in ("aws", "azure", "gcp"):
        resp = c.get("/api/v1/target-architecture/payments-api-gateway",
                     params={"provider": provider})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["provider_profile"] == provider
        assert isinstance(data["spec"], dict) and data["spec"]
        seen.add(data["provider_profile"])
    assert seen == {"aws", "azure", "gcp"}

    yaml_resp = c.get("/api/v1/target-architecture/payments-api-gateway",
                      params={"format": "yaml"})
    assert "aws:" in yaml_resp.json()["yaml"] or ":" in yaml_resp.json()["yaml"]

    bad = c.get("/api/v1/target-architecture/payments-api-gateway",
                params={"provider": "alibaba"})
    assert bad.status_code == 422
    assert c.get("/api/v1/target-architecture/nope-app").status_code == 404


# ------------------------------------------------------------------ misc/eval

def test_opportunities_risks_audit_metrics_summary(loaded_client):
    c = loaded_client
    opps = c.get("/api/v1/opportunities").json()
    assert opps and {"title", "impact", "effort"} <= set(opps[0])
    risks = c.get("/api/v1/risks").json()
    scores = [r["severity_score"] for r in risks]
    assert scores == sorted(scores, reverse=True)
    events = c.get("/api/v1/audit/events?limit=50").json()
    assert any(e["event_type"] == "waves.planned" for e in events)
    summary = c.get("/api/v1/metrics-summary").json()
    assert summary["applications_assessed"] >= 40
    assert summary["blocked_migrations_identified"] == 2


def test_evaluation_endpoint_gates_on_unseeded_estate(client):
    assert client.post("/api/v1/evaluation/run").status_code == 409
