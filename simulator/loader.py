"""Persist the generated estate into the application database."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    AppRuntimeDetails, Application, BatchJob, CMDBRecord, DatabaseRegistry,
    DomainEvent, FileTransfer, Integration, NetworkFlow, Server, SharedService,
)
from app.db import reset_db
from simulator.generate_estate import (
    OS_TABLE, RUNTIME_PROFILES, SHARED_SERVICES, EstateData,
    generate_estate, write_ground_truth,
)


def _persist(estate: EstateData, session: Session) -> dict:
    for db_row in estate.databases:
        session.add(DatabaseRegistry(**db_row))

    for svc in SHARED_SERVICES:
        session.add(SharedService(
            id=svc["id"], display_name=svc["display_name"], kind=svc["kind"],
            description=svc["description"], wave_assignment=svc["wave_assignment"],
            replacement_note=svc["replacement_note"],
        ))
    session.flush()  # parents first: bare FK columns get no automatic insert ordering

    for spec in estate.applications:
        profile = RUNTIME_PROFILES[spec.runtime_id]
        os_meta = OS_TABLE[spec.os_id]
        session.add(Application(
            id=spec.id, name=spec.name, domain=spec.domain,
            business_owner=spec.business_owner, language=spec.language,
            framework=profile["framework"], runtime_id=spec.runtime_id,
            os_id=spec.os_id, database_id=spec.database_row_id,
            server_count=spec.server_count, api_surface=spec.api_surface,
            auth_method=spec.auth_method, statefulness=spec.statefulness,
            compliance_scope=spec.compliance_scope, usage_per_day=spec.usage_per_day,
            monthly_usage_trend_pct=spec.monthly_usage_trend_pct,
            annual_infra_cost_usd=spec.annual_infra_cost_usd,
            criticality=spec.criticality,
            commodity_capability=spec.commodity_capability,
            specialized_os_deps=spec.specialized_os_deps,
            hypervisor_hosted=spec.hypervisor_hosted,
            requested_wave_override=spec.requested_wave_override,
            lifecycle=spec.lifecycle, placement="on-prem",
            description=spec.description,
        ))
        session.add(AppRuntimeDetails(
            application_id=spec.id,
            runtime_family=profile["language"], runtime_version=profile["version"],
            runtime_eol=profile["eol"], os_family=f"{os_meta['family']} {os_meta['version']}",
            os_eol=os_meta["eol"], deployment_type=profile["deployment"],
            monolith_loc=spec.monolith_loc, manual_deployments=spec.manual_deployments,
            has_observability=spec.has_observability,
            hardcoded_secrets_found=spec.hardcoded_secrets_found,
            oracle_only_feature=spec.oracle_only_feature,
            shared_database=spec.shared_database,
            change_frequency=spec.change_frequency,
            last_change_months_ago=spec.last_change_months_ago,
        ))
    session.flush()  # applications before their dependent inventory rows

    for row in estate.servers:
        session.add(Server(**row))
    for row in estate.network_flows:
        session.add(NetworkFlow(**row))
    for row in estate.batch_jobs:
        session.add(BatchJob(**row))
    for row in estate.file_transfers:
        session.add(FileTransfer(**row))
    for row in estate.cmdb_records:
        session.add(CMDBRecord(**row))
    for row in estate.integrations:
        session.add(Integration(**row))

    session.add(DomainEvent(event_type="estate.seeded", subject="estate",
                            payload={"applications": len(estate.applications)}))
    session.flush()

    truth_edges = write_ground_truth(estate)

    return {
        "seeded": True,
        "applications": len(estate.applications),
        "shared_services": len(SHARED_SERVICES),
        "network_flows": len(estate.network_flows),
        "file_transfers": len(estate.file_transfers),
        "batch_jobs": len(estate.batch_jobs),
        "cmdb_records": len(estate.cmdb_records),
        "servers": len(estate.servers),
        "truth_edges_written": truth_edges,
    }


def seed_estate(session: Session, size: int | None = None, reset: bool = True) -> dict:
    from app.config import get_settings

    size = size or get_settings().estate_size
    if reset:
        reset_db()
    estate = generate_estate(size=size)
    return _persist(estate, session)
