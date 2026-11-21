"""Structured target-architecture generation.

Produces a provider-neutral spec (compute/database/secrets/observability chain, sizing,
network notes, identity mapping, cost delta) per migrated application, then renders it
through an aws/azure/gcp profile that only renames resources. Local templates only:
nothing is provisioned anywhere.
"""
from __future__ import annotations

from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.migration.simulator import capacity_estimate
from app.models import (
    AppRuntimeDetails, Application, DatabaseRegistry, StrategyRecommendation,
    TargetArchitecture,
)
from app.targetarch.providers.aws_profile import PROFILE as AWS_PROFILE
from app.targetarch.providers.azure_profile import PROFILE as AZURE_PROFILE
from app.targetarch.providers.gcp_profile import PROFILE as GCP_PROFILE

PROFILES = {"aws": AWS_PROFILE, "azure": AZURE_PROFILE, "gcp": GCP_PROFILE}


def _db_target(db_meta: DatabaseRegistry | None, profile: dict) -> tuple[str, str]:
    """(generic slot, provider-named resource)"""
    engine = db_meta.engine if db_meta else "flat-files"
    if engine in ("postgres-13",):
        return "postgres", profile["database"]["postgres"]
    if engine == "mysql-5.7":
        return "mysql", profile["database"]["mysql"]
    if engine.startswith("sqlserver"):
        return "sqlserver", profile["database"]["sqlserver"]
    if engine.startswith("oracle"):
        return "oracle_bridge", profile["database"]["oracle_bridge"]
    return "object_storage", profile["database"]["object_storage"]


def _identity_mapping(app: Application, profile: dict) -> list[dict]:
    if app.auth_method == "sso":
        return [{"from": "on-prem SSO provider (SAML/OIDC)",
                 "to": profile["identity"]["sso"], "note": "repoint relying-party trust"}]
    if app.auth_method == "ldap":
        return [{"from": "corporate LDAP binds",
                 "to": profile["identity"]["ldap"], "note": "LDAPS endpoint swap"}]
    if app.auth_method == "local-db":
        return [{"from": "app-local user table",
                 "to": profile["secrets"] + " + managed identity",
                 "note": "migrate credentials out of the database"}]
    if app.auth_method == "basic":
        return [{"from": "HTTP basic credentials",
                 "to": profile["identity"]["sso"] + " (federate)",
                 "note": "basic auth is a finding; federate during replatform"}]
    return [{"from": "no authentication", "to": "front-door policy + rate limits",
             "note": "unauthenticated surface; keep behind WAF"}]


def build_spec(session: Session, app: Application, provider_key: str) -> dict[str, Any]:
    profile = PROFILES[provider_key]
    details: AppRuntimeDetails | None = app.runtime_details
    strategy_row = (session.query(StrategyRecommendation)
                    .filter(StrategyRecommendation.application_id == app.id).first())
    strategy = strategy_row.strategy if strategy_row else "REHOST"
    db_meta = session.get(DatabaseRegistry, app.database_id) if app.database_id else None
    capacity = capacity_estimate(app)
    current_monthly = round(app.annual_infra_cost_usd / 12, 2)

    if strategy == "RELOCATE":
        compute_target = profile["compute"]["vm"]
        runtime_chain = [
            {"slot": "os_image", "from": f"{details.os_family} VM image",
             "to": f"{profile['compute']['vm']} (lifted image)"},
            {"slot": "runtime", "from": details.runtime_version if details else app.framework,
             "to": "unchanged (licence/socket-coupled workload kept intact)"},
        ]
    elif strategy == "REPURCHASE":
        compute_target = profile["saas_file_hub"]
        runtime_chain = [
            {"slot": "capability", "from": f"homegrown {app.name}",
             "to": "SaaS-equivalent service"},
            {"slot": "integration_adapter", "from": "direct drop-dir consumers",
             "to": f"adapter on {profile['compute']['containers']}"},
            {"slot": "homegrown_system", "from": app.id, "to": "DECOMMISSION"},
        ]
    elif strategy == "REFACTOR":
        compute_target = profile["compute"]["containers"]
        runtime_chain = [
            {"slot": "phase_1_runtime", "from": app.framework,
             "to": f"containerized on {profile['compute']['containers']} (strangler facade)"},
            {"slot": "phase_2_modules", "from": f"{details.monolith_loc:,} LOC monolith"
             if details else "monolith",
             "to": "extract high-change modules; API-first seams"},
            {"slot": "database", "from": db_meta.engine if db_meta else "n/a",
             "to": _db_target(db_meta, profile)[1]},
        ]
    else:  # REHOST / REPLATFORM share the container chain
        compute_target = profile["compute"]["containers"]
        runtime_chain = [
            {"slot": "runtime", "from": f"{app.framework}",
             "to": f"container image on {compute_target}"
                   + (" (supported base image)" if strategy == "REPLATFORM" else "")},
            {"slot": "database", "from": db_meta.engine if db_meta else "n/a",
             "to": _db_target(db_meta, profile)[1]},
            {"slot": "secrets", "from": "config files / hardcoded values"
             if (details and details.hardcoded_secrets_found) else "config files",
             "to": profile["secrets"]},
            {"slot": "observability", "from": "legacy monitoring stack" if
             (details and not details.has_observability) else "existing agents",
             "to": profile["observability"]},
        ]

    db_slot, db_resource = _db_target(db_meta, profile)
    projected_monthly = capacity.est_monthly_cost_usd + round(
        (db_meta.eol and 350 or 120) if db_meta else 40, 2)

    spec: dict[str, Any] = {
        "simulated": True,
        "application": {"id": app.id, "name": app.name, "domain": app.domain,
                        "criticality": app.criticality},
        "strategy": strategy,
        "provider_profile": profile["provider"],
        "provider_display_name": profile["display_name"],
        "source": {
            "runtime": f"{app.framework} ({details.runtime_version})" if details else app.framework,
            "os": details.os_family if details else app.os_id,
            "database_engine": db_meta.engine if db_meta else "none",
            "servers": app.server_count,
        },
        "target": {
            "chain": runtime_chain,
            "resources": {
                "compute": compute_target,
                "artifact_registry": profile["compute"]["artifact_registry"],
                "database": db_resource,
                "secrets": profile["secrets"],
                "observability": profile["observability"],
                "messaging": profile["messaging"],
                "file_transfer": profile["file_transfer"] if app.statefulness != "batch-only" else None,
            },
            "sizing": {
                "vcpu_total": capacity.vcpu_total,
                "ram_gb_total": capacity.ram_gb_total,
                "replicas": capacity.container_replicas,
            },
            "network_notes": [
                f"place in {'regulated' if app.compliance_scope != 'none' else 'general'} zone "
                f"({profile['network']['vpc']} + private DNS {profile['network']['private_dns']})",
                f"WAF in front of any public surface ({profile['network']['waf']})",
            ],
            "identity_mapping": _identity_mapping(app, profile),
        },
        "cost_estimate": {
            "current_on_prem_monthly_usd": current_monthly,
            "projected_cloud_monthly_usd": round(projected_monthly, 2),
            "delta_monthly_usd": round(projected_monthly - current_monthly, 2),
        },
    }
    if strategy == "REPURCHASE":
        spec["target"]["resources"]["database"] = profile["database"]["object_storage"]
    return spec


def generate_for_app(session: Session, app_id: str, provider_key: str = "aws") -> TargetArchitecture:
    if provider_key not in PROFILES:
        raise ValueError(f"unknown provider profile '{provider_key}' (use aws|azure|gcp)")
    app = session.get(Application, app_id)
    if app is None:
        raise LookupError(f"application '{app_id}' not found")

    spec = build_spec(session, app, provider_key)
    row = (session.query(TargetArchitecture)
           .filter(TargetArchitecture.application_id == app_id,
                   TargetArchitecture.provider_profile == provider_key)
           .first())
    if row is None:
        row = TargetArchitecture(application_id=app_id, provider_profile=provider_key)
        session.add(row)
    row.spec = spec
    row.cost_delta_monthly = spec["cost_estimate"]["delta_monthly_usd"]
    return row


def render_yaml(spec: dict) -> str:
    return yaml.safe_dump(spec, sort_keys=False, default_flow_style=False)
