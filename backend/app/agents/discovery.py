"""Application Discovery Agent + Dependency Mapping Agent.

Discovery correlates four simulated sources (CMDB, network flow logs, batch scheduler
extract, file-transfer logs) and builds the dependency graph. The hidden undocumented
dependency (nightly FTP into another app's drop-dir) is only discoverable here, by
correlating transfer-log remote paths with CMDB drop-dir mounts.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.models import GraphEdge


class ApplicationDiscoveryAgent(BaseAgent):
    name = "application-discovery-agent"

    def run(self, investigation) -> dict:
        def work():
            cmdb = self.use("query_cmdb")
            flows = self.use("query_network_flows")
            jobs = self.use("query_batch_jobs")
            transfers = self.use("query_transfer_logs")
            graph_result = self.use("build_dependency_graph")

            hidden = graph_result["undocumented_file_dependencies"]
            for edge in hidden:
                self.add_evidence(
                    source="transfer-log-correlation",
                    fact=(f"Undocumented dependency: {edge['src']} sends nightly files "
                          f"to {edge['dst']} ({edge['note']})"),
                    reliability="medium", raw_reference="file_transfers correlation",
                    investigation_id=investigation.id,
                )

            input_summary = {
                "sources": ["cmdb", "network_flows", "batch_jobs", "transfer_logs"],
                "cmdb_records": cmdb["count"],
                "flows": flows["count"],
                "batch_jobs": jobs["count"],
                "transfers": transfers["count"],
            }
            output_summary = {
                "edges_persisted": graph_result["edges_persisted"],
                "by_relation": graph_result["by_relation"],
                "correlation_stats": graph_result["correlation_stats"],
                "undocumented_dependencies_found": len(hidden),
                "hidden": [
                    {"src": e["src"], "dst": e["dst"], "relation": e["relation"]}
                    for e in hidden
                ],
            }
            facts = [
                {"label": "cmdb_records_considered", "value": cmdb["count"]},
                {"label": "network_flow_rows", "value": flows["count"]},
                {"label": "batch_job_rows", "value": jobs["count"]},
                {"label": "transfer_log_rows", "value": transfers["count"]},
                {"label": "dependency_edges_derived", "value": graph_result["edges_persisted"]},
                {"label": "undocumented_file_dependencies",
                 "value": "; ".join(f"{e['src']}->{e['dst']}" for e in hidden) or "none"},
            ]
            prompt = ("Summarize the discovery outcome: how many edges were derived from "
                      "each source and which undocumented dependencies were found.")
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "discovery-correlation", work)


class DependencyMappingAgent(BaseAgent):
    name = "dependency-mapping-agent"

    def run(self, investigation) -> dict:
        def work():
            edges = self.session.query(GraphEdge).all()
            by_relation: dict[str, int] = {}
            by_source: dict[str, int] = {}
            for e in edges:
                by_relation[e.relation] = by_relation.get(e.relation, 0) + 1
                by_source[e.discovered_by] = by_source.get(e.discovered_by, 0) + 1

            self.add_evidence(
                source="graph-build",
                fact=f"Persisted dependency graph holds {len(edges)} edges across "
                     f"{len(by_relation)} relations.",
                raw_reference="graph_edges",
                investigation_id=investigation.id,
            )
            input_summary = {"graph_tables": ["graph_edges"]}
            output_summary = {"total_edges": len(edges),
                              "by_relation": by_relation, "by_discovered_by": by_source}
            facts = [
                {"label": "total_edges", "value": len(edges)},
                {"label": "relations", "value": ", ".join(sorted(by_relation))},
                {"label": "discovery_sources", "value": ", ".join(sorted(by_source))},
            ]
            prompt = "Describe the shape of the persisted dependency graph."
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "graph-mapping", work)
