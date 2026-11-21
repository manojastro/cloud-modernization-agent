"""Dependency discovery: multi-source edge extraction and the hidden FTP dependency."""
from simulator.generate_estate import HIDDEN_MOUNT, HIDDEN_SOURCE, HIDDEN_TARGET
from app.graph.dependency_graph import (
    build_graph,
    correlate_transfer_logs,
    discover_all,
    edges_from_cmdb,
    edges_from_flows,
    persist_edges,
)
from app.models import Application, GraphEdge


def test_correlation_finds_hidden_dependency(seeded):
    edges, stats = correlate_transfer_logs(seeded)
    hidden = [e for e in edges
              if e["src"] == HIDDEN_SOURCE and e["dst"] == HIDDEN_TARGET
              and e["relation"] == "APP_SENDS_FILE_TO"]
    assert len(hidden) == 1
    (edge,) = hidden
    assert edge["discovered_by"] == "transfer-log-correlation"
    assert HIDDEN_MOUNT in edge["note"]
    assert stats["correlated_drops"] >= 1
    assert stats["transfers_examined"] > 0


def test_cmdb_edges_cover_identity_and_database(seeded):
    edges = edges_from_cmdb(seeded)
    by_rel = {}
    for e in edges:
        by_rel.setdefault(e["relation"], set()).add((e["src"], e["dst"]))
    assert "APP_USES_IDENTITY" in by_rel and "APP_USES_DATABASE" in by_rel

    # every ldap/sso app gets an identity edge to a shared service
    for app in seeded.query(Application).all():
        if app.auth_method == "ldap":
            assert (app.id, "svc-corporate-ldap") in by_rel["APP_USES_IDENTITY"]
        elif app.auth_method == "sso":
            assert (app.id, "svc-sso-provider") in by_rel["APP_USES_IDENTITY"]

    # every app with a dedicated database row gets a database edge
    with_databases = {a.id for a in seeded.query(Application).all() if a.database_id}
    srcs = {s for s, _ in by_rel["APP_USES_DATABASE"]}
    assert with_databases <= srcs


def test_flow_edges_are_application_to_application_only(seeded):
    for e in edges_from_flows(seeded):
        assert e["relation"] == "APP_CALLS_APP"
        assert seeded.get(Application, e["dst"]) is not None


def test_discover_all_dedupes_and_persists(seeded):
    edges, stats = discover_all(seeded)
    triples = [(e["src"], e["dst"], e["relation"]) for e in edges]
    assert len(triples) == len(set(triples)), "duplicate edges must be removed"
    assert any(e["discovered_by"] == "transfer-log-correlation" for e in edges)

    written = persist_edges(seeded, edges)
    seeded.commit()
    assert written == seeded.query(GraphEdge).count()

    g = build_graph(seeded)
    assert g.number_of_nodes() > 0
    assert seeded.query(GraphEdge).count() > 0
    data = g[HIDDEN_SOURCE][HIDDEN_TARGET]
    assert data["relation"] == "APP_SENDS_FILE_TO"


def test_truth_file_matches_discovered_edges(planned):
    import json
    from pathlib import Path

    from app.graph.dependency_graph import REL_TRUTH

    session, summary = planned
    root = Path(__file__).resolve().parents[1]
    truth = json.loads((root / "evaluation" / "ground_truth.json").read_text("utf-8"))
    discovered = {
        (e.src, e.dst, e.relation)
        for e in session.query(GraphEdge).all()
        if e.relation in REL_TRUTH  # inventory relations are outside discovery truth
    }
    missing = [t for t in map(tuple, truth["true_edges"]) if t not in discovered]
    unexpected = list(discovered - set(map(tuple, truth["true_edges"])))
    assert not missing and not unexpected
