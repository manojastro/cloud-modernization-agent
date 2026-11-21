"""Modernization Agent: derives an opportunity catalog per application from the debt
indicators the assessment engine recorded (facts only, no invented opportunities)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.models import Assessment, ModernizationOpportunity

INDICATOR_OPPORTUNITIES = {
    "eol_runtime": ("Get off EOL runtime", "runtime-currency", "high", "medium",
                    "Runtime is end-of-life; move to a supported managed runtime image."),
    "eol_os": ("Upgrade OS baseline", "os-currency", "high", "medium",
               "Operating system is past end of support; rebuild on supported base image."),
    "no_api_layer": ("Expose an API facade", "api-enablement", "medium", "medium",
                     "No modern API surface; add a facade to unlock integration and automation."),
    "shared_database": ("Break shared-database ownership", "data-decoupling", "high", "high",
                        "Application shares a database with others; assign ownership and route "
                        "consumers through APIs before migration."),
    "hardcoded_secrets": ("Move secrets to central vault", "security-hygiene", "high", "low",
                          "Hardcoded credentials found; bind to the central secrets manager."),
    "manual_deployments": ("Automate deployment pipeline", "delivery-engineering", "medium", "low",
                           "Deployments are manual; add CI/CD before cutover to reduce risk."),
    "monolith_codebase": ("Strangler-fig decomposition", "architecture", "high", "high",
                          "Large monolith; carve high-change modules behind stable interfaces."),
    "large_codebase": ("Modularize hot spots", "architecture", "medium", "medium",
                       "Codebase above 100k LOC; isolate high-churn modules."),
    "no_observability": ("Instrument service", "operability", "medium", "low",
                         "No monitoring integration; add metrics/traces/logging."),
    "eol_database": ("Migrate off EOL database", "data-platform", "high", "high",
                     "Database engine is EOL; convert to a managed equivalent."),
}


class ModernizationAgent(BaseAgent):
    name = "modernization-agent"

    def run(self, investigation) -> dict:
        def work():
            created = 0
            per_app_counts: dict[str, int] = {}
            assessments = self.session.query(Assessment).all()
            for assessment in assessments:
                self.session.query(ModernizationOpportunity).filter_by(
                    application_id=assessment.application_id).delete()
                count = 0
                for indicator in assessment.indicators:
                    title, category, impact, effort, description = INDICATOR_OPPORTUNITIES[indicator]
                    self.session.add(ModernizationOpportunity(
                        application_id=assessment.application_id, title=title,
                        category=category, impact=impact, effort=effort,
                        description=description, source_facts=[indicator]))
                    count += 1
                created += count
                per_app_counts[assessment.application_id] = count

            top = sorted(per_app_counts.items(), key=lambda kv: -kv[1])[:3]
            input_summary = {"assessments": len(assessments)}
            output_summary = {"opportunities_created": created,
                              "most_opportunities": top}
            facts = [
                {"label": "applications_with_opportunities",
                 "value": sum(1 for c in per_app_counts.values() if c)},
                {"label": "total_opportunities", "value": created},
            ]
            prompt = "Summarize how many modernization opportunities were derived and where."
            return input_summary, output_summary, facts, prompt

        return self.stage(investigation, "modernization-catalog", work)
