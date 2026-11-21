"""Dependency graph: derive edges from CMDB records, network flow logs, batch scheduler
extracts and file-transfer logs; correlate them; persist to graph_edges; expose a NetworkX
graph and an API-friendly node/edge export.

The hidden undocumented dependency surfaces ONLY here: a nightly file transfer whose
remote path lands inside another application's registered drop-dir mount.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import networkx as nx

from app.models import (
    Application, BatchJob, CMDBRecord, DatabaseRegistry, FileTransfer, GraphEdge,
    NetworkFlow, SharedService,
)

REL_TRUTH = {
    "APP_CALLS_APP", "APP_USES_DATABASE", "APP_USES_IDENTITY", "APP_USES_FILE_SHARE",
    "APP_SENDS_FILE_TO", "APP_PUBLISHES_EVENT", "APP_CONSUMES_EVENT",
}

# Relations whose dependency must be available in the SAME OR EARLIER wave (hard).
HARD_TOPO_RELATIONS = {"APP_CALLS_APP", "APP_USES_IDENTITY"}


def edges_from_cmdb(session: Session) -> list[dict]:
    edges: list[dict] = []
    apps = session.query(Application).all()
    for app in apps:
        if app.database_id:
            shared_note = ""
            db = session.get(DatabaseRegistry, app.database_id)
            if db is not None and db.is_shared_service:
                shared_note = "shared platform database"
            edges.append({
                "src": app.id, "dst": app.database_id, "relation": "APP_USES_DATABASE",
                "discovered_by": "cmdb", "confidence": 0.95, "note": shared_note,
            })
        if app.auth_method == "ldap":
            edges.append({"src": app.id, "dst": "svc-corporate-ldap",
                          "relation": "APP_USES_IDENTITY", "discovered_by": "cmdb",
                          "confidence": 0.95, "note": f"auth={app.auth_method}"})
        elif app.auth_method == "sso":
            edges.append({"src": app.id, "dst": "svc-sso-provider",
                          "relation": "APP_USES_IDENTITY", "discovered_by": "cmdb",
                          "confidence": 0.95, "note": f"auth={app.auth_method}"})
    # file shares registered in CMDB
    share_rows = (session.query(CMDBRecord)
                  .filter(CMDBRecord.field == "file_share").all())
    for row in share_rows:
        share_name = row.value.split(":", 1)[0]
        edges.append({"src": row.application_id, "dst": f"fs:{share_name}",
                      "relation": "APP_USES_FILE_SHARE", "discovered_by": "cmdb",
                      "confidence": 0.9, "note": row.value})
    # event publish/consume facts
    for field_name, rel in (("publishes_topic", "APP_PUBLISHES_EVENT"),
                            ("consumes_topic", "APP_CONSUMES_EVENT")):
        rows = session.query(CMDBRecord).filter(CMDBRecord.field == field_name).all()
        for row in rows:
            edges.append({"src": row.application_id, "dst": f"topic:{row.value}",
                          "relation": rel, "discovered_by": "cmdb",
                          "confidence": 0.9, "note": ""})
    return edges


def edges_from_flows(session: Session) -> list[dict]:
    edges: list[dict] = []
    flows = session.query(NetworkFlow).all()
    for flow in flows:
        if flow.dst_kind != "application":
            continue  # service traffic is covered by identity/db/share relations
        edges.append({
            "src": flow.src_app_id, "dst": flow.dst_node_id,
            "relation": "APP_CALLS_APP", "discovered_by": "flow-logs",
            "confidence": 0.85,
            "note": f"{flow.connections_daily} conn/day over {flow.protocol}/{flow.port}",
        })
    return edges


def correlate_transfer_logs(session: Session) -> tuple[list[dict], dict]:
    """Correlate file-transfer log paths with CMDB-registered drop-dir mounts.

    Returns (edges, correlation_stats).
    """
    mounts: dict[str, tuple[str, str]] = {}  # mount path -> (owner_app_id, share_name)
    share_rows = (session.query(CMDBRecord)
                  .filter(CMDBRecord.field == "file_share").all())
    for row in share_rows:
        try:
            _name, mount = row.value.split(":", 1)
        except ValueError:
            continue
        mounts[mount.rstrip("/")] = (row.application_id, row.value.split(":", 1)[0])

    transfers = session.query(FileTransfer).all()
    edges: list[dict] = []
    stats = {"transfers_examined": len(transfers), "hub_transfers": 0, "correlated_drops": 0}

    for tr in transfers:
        if tr.remote_system == "sftp-hub":
            stats["hub_transfers"] += 1
            edges.append({
                "src": tr.source_app_id, "dst": "svc-sftp-hub",
                "relation": "APP_USES_FILE_SHARE", "discovered_by": "transfer-log-correlation",
                "confidence": 0.8, "note": f"nightly hub usage ({tr.frequency})",
            })
        normalized = tr.remote_path.replace("*", "").rstrip("/")
        for mount, (owner_app, share_value) in mounts.items():
            if owner_app == tr.source_app_id:
                continue
            if normalized.startswith(mount):
                stats["correlated_drops"] += 1
                edges.append({
                    "src": tr.source_app_id, "dst": owner_app,
                    "relation": "APP_SENDS_FILE_TO", "discovered_by": "transfer-log-correlation",
                    "confidence": 0.75,
                    "note": f"transfer path '{tr.remote_path}' lands inside drop-dir "
                            f"'{mount}' owned by {owner_app} ({tr.frequency}, {tr.avg_mb} MB)",
                })
                break
    return edges, stats


def batch_job_edges(session: Session) -> list[dict]:
    """Batch scheduler extract -> APP_RUNS_BATCH_JOB edges (inventory, not discovery truth)."""
    edges: list[dict] = []
    for job in session.query(BatchJob).all():
        edges.append({
            "src": job.application_id, "dst": f"batch:{job.job_name}",
            "relation": "APP_RUNS_BATCH_JOB", "discovered_by": "scheduler-extract",
            "confidence": 0.95, "note": job.schedule,
        })
    return edges


def library_edges(session: Session) -> list[dict]:
    edges: list[dict] = []
    rows = session.query(CMDBRecord).filter(CMDBRecord.field == "libraries").all()
    for row in rows:
        libs = [lib for lib in (row.value or "").split(",") if lib]
        for lib in libs:
            edges.append({
                "src": row.application_id, "dst": f"library:{lib}",
                "relation": "APP_DEPENDS_ON_LIBRARY", "discovered_by": "cmdb",
                "confidence": 0.85, "note": "",
            })
    return edges


def server_edges(session: Session) -> list[dict]:
    from app.models import Server

    return [
        {"src": s.application_id, "dst": f"server:{s.hostname}",
         "relation": "APP_REQUIRES_SERVER", "discovered_by": "cmdb",
         "confidence": 0.99, "note": ""}
        for s in session.query(Server).all()
    ]


def discover_all(session: Session) -> tuple[list[dict], dict]:
    """Run every discovery source; returns deduplicated edges + correlation stats."""
    edges: list[dict] = []
    edges.extend(edges_from_cmdb(session))
    edges.extend(edges_from_flows(session))
    correlated, stats = correlate_transfer_logs(session)
    edges.extend(correlated)
    edges.extend(batch_job_edges(session))
    edges.extend(library_edges(session))
    edges.extend(server_edges(session))

    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for e in edges:
        key = (e["src"], e["dst"], e["relation"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    unique.sort(key=lambda e: (e["relation"], e["src"], e["dst"]))
    return unique, stats


def persist_edges(session: Session, edges: list[dict]) -> int:
    session.query(GraphEdge).delete()
    session.flush()
    for e in edges:
        session.add(GraphEdge(**e))
    session.flush()  # sessions run with autoflush=False
    return len(edges)


def build_graph(session: Session) -> nx.DiGraph:
    g = nx.DiGraph()
    for app in session.query(Application).all():
        g.add_node(app.id, kind="application", label=app.name, domain=app.domain)
    for svc in session.query(SharedService).all():
        g.add_node(svc.id, kind="service", label=svc.display_name)
    for db in session.query(DatabaseRegistry).all():
        g.add_node(db.id, kind="database", label=db.display_name)
    for edge in session.query(GraphEdge).all():
        if edge.relation in ("APP_RUNS_BATCH_JOB", "APP_DEPENDS_ON_LIBRARY", "APP_REQUIRES_SERVER"):
            kind = edge.dst.split(":", 1)[0]
            g.add_node(edge.dst, kind=kind, label=edge.dst)
        if edge.src not in g:
            g.add_node(edge.src, kind="application", label=edge.src)
        if edge.dst not in g:
            g.add_node(edge.dst, kind="node", label=edge.dst)
        g.add_edge(edge.src, edge.dst, relation=edge.relation,
                   discovered_by=edge.discovered_by, confidence=edge.confidence)
    return g


def export_nodes_edges(session: Session) -> tuple[list[dict], list[dict]]:
    nodes: dict[str, dict] = {}
    for app in session.query(Application).all():
        nodes[app.id] = {"id": app.id, "kind": "application", "label": app.name,
                         "domain": app.domain}
    for svc in session.query(SharedService).all():
        nodes[svc.id] = {"id": svc.id, "kind": "service", "label": svc.display_name}
    for db in session.query(DatabaseRegistry).all():
        nodes[db.id] = {"id": db.id, "kind": "database", "label": db.display_name}
    edges_out: list[dict] = []
    for edge in session.query(GraphEdge).all():
        if edge.dst not in nodes:
            kind = edge.dst.split(":", 1)[0]
            nodes[edge.dst] = {"id": edge.dst, "kind": kind, "label": edge.dst}
        edges_out.append({
            "src": edge.src, "dst": edge.dst, "relation": edge.relation,
            "discovered_by": edge.discovered_by, "confidence": edge.confidence,
            "note": edge.note,
        })
    return list(nodes.values()), edges_out
