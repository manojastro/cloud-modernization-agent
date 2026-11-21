"""Migration Strategy Agent, Wave Planning Agent, Risk Agent and Validation Agent."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.migration import simulator
from app.models import (
    Assessment, BlockedMigration, DecisionRecord, Risk, StrategyRecommendation,
)
from app.workflow.engine import WorkflowViolation

SEVERITY = {
    ("unlikely", "minor"): 1.0, ("unlikely", "moderate"): 2.0, ("unlikely", "major"): 3.0,
    ("possible", "minor"): 2.0, ("possible", "moderate"): 4.0, ("possible", "major"): 6.0,
    ("likely", "minor"): 3.0, ("likely", "moderate"): 6.0, ("likely", "major"): 9.0,
}


class MigrationStrategyAgent(BaseAgent):
    name = "migration-strategy-agent"

    def run(self, investigation) -> dict:
        def work():
            result = self.use("classify_strategy")
            by_strategy: dict[str, int] = {}
            for row in result["results"]:
                by_strategy[row["strategy"]] = by_strategy.get(row["strategy"], 0) + 1

            # persist one auditable decision per application
            recs = {r.application_id: r for r in
                    self.session.query(StrategyRecommendation).all()}
            for app_id in sorted(recs):
                rec = recs[app_id]
                self.session.add(DecisionRecord(
                    investigation_id=investigation.id, application_id=app_id,
                    decision_type="7r-strategy", decision=rec.strategy,
                    confidence=rec.confidence,
                    evidence_ids=[], alternatives=rec.alternatives,
                    risk_level=rec.risk_level, requires_approval=rec.requires_approval,
                    rationale=" | ".join(rec.reasons)[:900],
                ))

            input_summary = {"rule_table": "app.strategy.rules_7r.RULES_TABLE"}
            output_summary = {"classified": result["classified"],
                              "by_strategy": by_strategy}
            facts = [
                {"label": f"strategy_{name}", "value": count}
                for name, count in sorted(by_strategy.items())
            ]
            prompt = ("Report the 7R distribution across the portfolio; strategies were "
                      "chosen by the deterministic rules table, not by you.")
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "strategy-classification", work)


class WavePlanningAgent(BaseAgent):
    name = "wave-planning-agent"

    def run(self, investigation) -> dict:
        def work():
            result = self.use("plan_waves")
            blocked_ids = [b["application_id"] for b in result["blocked"]]
            if blocked_ids:
                self.add_evidence(
                    source="constraint-solver",
                    fact=f"Wave conflicts detected for: {', '.join(blocked_ids)}",
                    raw_reference="blocked_migrations",
                    investigation_id=investigation.id,
                )
            input_summary = {"constraints": ["topology", "criticality-cap",
                                             "regulated-zone-readiness", "concurrency-caps"]}
            output_summary = {
                "waves": result["waves"], "memberships": result["memberships"],
                "blocked": result["blocked"],
                "constraint_moves": len(result["constraint_moves"]),
            }
            facts = [
                {"label": "members_placed", "value": result["memberships"]},
                {"label": "blocked_migrations", "value": len(result["blocked"])},
                {"label": "auto_constraint_moves", "value": len(result["constraint_moves"])},
            ]
            prompt = "Summarize the wave plan and which applications were blocked and why."
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "wave-planning", work)


class RiskAgent(BaseAgent):
    name = "risk-agent"

    def run(self, investigation) -> dict:
        def work():
            created = 0
            blocks = self.session.query(BlockedMigration).all()
            for b in blocks:
                self._add(b.application_id, None, "schedule-conflict",
                          f"{b.reason_code}: {b.reason_detail}",
                          "possible", "major",
                          b.suggested_resolution)
                created += 1

            strategies = {s.application_id: s for s in
                          self.session.query(StrategyRecommendation).all()}
            refactors = [a for a, s in strategies.items() if s.strategy == "REFACTOR"]
            for app_id in refactors[:10]:
                self._add(app_id, 3, "refactor-scope",
                          "Refactor candidate migrates first as a strangler facade; module "
                          "extraction continues after cutover.",
                          "possible", "moderate",
                          "Timebox phase 2; keep facade stable during extraction.")
                created += 1

            retains = [a for a, s in strategies.items() if s.strategy == "RETAIN"]
            for app_id in retains:
                self._add(app_id, 2, "retained-dependency-bridge",
                          "Retained on-prem dependency requires a connectivity bridge for "
                          "cloud consumers during transition.",
                          "possible", "moderate",
                          "Provision bridge + private connectivity before dependent waves.")
                created += 1

            self._add(None, 0, "pilot-novelty", "Landing-zone and tooling are new in wave 0.",
                      "possible", "minor",
                      "Pilot apps are low criticality and stateless; rollback rehearsed.")
            created += 1
            self._add(None, 3, "business-criticality", "Wave 3 moves mission-critical systems.",
                      "unlikely", "major",
                      "Full rehearsal, transaction replay and staged approval gates.")
            created += 1

            input_summary = {"sources": ["blocked_migrations", "strategies"]}
            output_summary = {"risks_recorded": created}
            facts = [
                {"label": "blocked_schedule_risks", "value": len(blocks)},
                {"label": "total_risks", "value": created},
            ]
            prompt = "Summarize the top migration risks recorded."
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "risk-register", work)

    def _add(self, app_id, wave_number, category, description, likelihood, impact,
             mitigation) -> None:
        self.session.add(Risk(
            application_id=app_id, wave_number=wave_number, category=category,
            description=description, likelihood=likelihood, impact=impact,
            severity_score=SEVERITY[(likelihood, impact)], mitigation=mitigation))


class ValidationAgent(BaseAgent):
    name = "validation-agent"

    def run(self, investigation) -> dict:
        def work():
            summaries = {}
            for wave_number in (0, 1, 2, 3):
                try:
                    summaries[f"wave-{wave_number}"] = self.use(
                        "simulate_migration_preflight", {"wave_number": wave_number})
                except (WorkflowViolation, LookupError) as exc:
                    summaries[f"wave-{wave_number}"] = {"skipped": str(exc)[:200]}
                    continue

            total_blocked = sum(
                s.get("BLOCKED", 0) for s in summaries.values() if "BLOCKED" in s)
            input_summary = {"preflight_checks": simulator.PREFLIGHT_CHECKS}
            output_summary = {"per_wave": summaries,
                              "blocked_check_instances": total_blocked}
            facts = [
                {"label": "waves_preflighted",
                 "value": sum(1 for s in summaries.values() if "PASS" in s)},
                {"label": "blocked_check_instances", "value": total_blocked},
            ]
            prompt = ("Summarize pre-flight validation outcomes per wave; every check is "
                      "PASS or BLOCKED with a reason.")
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "premigration-validation", work)
