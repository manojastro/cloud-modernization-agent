"""Technical Debt Agent + Cloud Readiness Agent (incl. agentic readiness)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.assessment.engine import compute_debt_index, db_meta_for
from app.models import Application


class TechnicalDebtAgent(BaseAgent):
    name = "technical-debt-agent"

    def run(self, investigation) -> dict:
        def work():
            scored = []
            for app in self.session.query(Application).all():
                debt, indicators = compute_debt_index(
                    app, app.runtime_details, db_meta_for(self.session, app))
                scored.append({"application_id": app.id, "name": app.name,
                               "debt_index": round(debt, 1),
                               "indicators": indicators})
            scored.sort(key=lambda s: -s["debt_index"])
            top = scored[:10]
            eol_runtime_count = sum(
                1 for s in scored if "eol_runtime" in s["indicators"])

            self.add_evidence(
                source="runtime-analysis",
                fact=f"{eol_runtime_count} applications run on EOL runtimes; "
                     f"top debtor is {top[0]['name']} "
                     f"(index {top[0]['debt_index']})" if top else "no apps",
                raw_reference="app_runtime_details",
                investigation_id=investigation.id,
            )
            input_summary = {"applications": len(scored)}
            output_summary = {"applications_scored": len(scored),
                              "top_offenders": top,
                              "eol_runtime_apps": eol_runtime_count}
            facts = [
                {"label": "applications_scored", "value": len(scored)},
                {"label": "apps_on_eol_runtimes", "value": eol_runtime_count},
                {"label": "top_offender", "value": f"{top[0]['name']} ({top[0]['debt_index']})"},
            ]
            prompt = "Summarize the technical-debt landscape of the estate."
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "debt-analysis", work)


class CloudReadinessAgent(BaseAgent):
    name = "cloud-readiness-agent"

    def run(self, investigation) -> dict:
        def work():
            result = self.use("assess_application")
            bands: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
            for row in result["results"]:
                bands[row["agentic_band"]] = bands.get(row["agentic_band"], 0) + 1

            input_summary = {"mode": "full-portfolio"}
            output_summary = {
                "applications_assessed": result["assessed"],
                "agentic_readiness_bands": bands,
            }
            facts = [
                {"label": "applications_assessed", "value": result["assessed"]},
                {"label": "agentic_readiness_high", "value": bands["high"]},
                {"label": "agentic_readiness_medium", "value": bands["medium"]},
                {"label": "agentic_readiness_low", "value": bands["low"]},
            ]
            prompt = ("Summarize cloud readiness and agentic readiness distribution; "
                      "do not invent numbers.")
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "cloud-readiness-assessment", work)
