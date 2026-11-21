"""Constraint-aware wave planner.

Heuristics assign a preliminary wave per app (complexity/criticality/compliance driven);
a constraint-solver pass then enforces:

* topological order: hard dependencies must be available in the SAME OR EARLIER wave;
* regulated-zone readiness (PCI/PII zones provisioned from wave 2);
* criticality cap (criticality-5 apps not before wave 3 without explicit exception);
* per-wave concurrency caps (overflow spills to the next wave).

Operator overrides (app.requested_wave_override) are honoured but VALIDATED: an override
that violates a structural constraint produces a BlockedMigration record rather than a
silent reschedule. Non-overridden scheduling conflicts are auto-deferred (recorded as
constraint moves) because pure timing can be fixed by scheduling alone.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    Application, Assessment, BlockedMigration, CMDBRecord, DatabaseRegistry,
    DomainEvent, GraphEdge, SharedService, StrategyRecommendation, Wave,
    WaveMembership,
)

MAX_CONCURRENT = {0: 8, 1: 26, 2: 30, 3: 999}
REGULATED_ZONE_READY_FROM = 2
CRITICALITY_CAP_WAVE = 3
WAVE_NAMES = {
    0: "Wave 0 - Low-risk pilot",
    1: "Wave 1 - Stateless internal",
    2: "Wave 2 - Medium complexity",
    3: "Wave 3 - Business critical",
}

MIGRATING_STRATEGIES = {"REHOST", "REPLATFORM", "REFACTOR", "REPURCHASE", "RELOCATE"}


def _pilot_eligible(session: Session, app: Application, assessment: Assessment,
                    db_meta: DatabaseRegistry | None, has_calls: bool, has_events: bool) -> bool:
    return bool(
        app.requested_wave_override is None
        and assessment.complexity_label == "low"
        and app.criticality <= 2
        and app.server_count <= 3
        and app.statefulness == "stateless"
        and app.compliance_scope == "none"
        and app.api_surface in ("none", "REST-internal", "REST-public")
        and not has_events
        and not has_calls
        and db_meta is not None and db_meta.compatibility == "direct"
        and app.auth_method in ("none", "basic", "local-db")
    )


def _preliminary_wave(session: Session, app: Application, assessment: Assessment,
                      db_meta: DatabaseRegistry | None, has_calls: bool,
                      has_events: bool) -> int:
    if app.requested_wave_override is not None:
        return app.requested_wave_override
    if _pilot_eligible(session, app, assessment, db_meta, has_calls, has_events):
        return 0
    if assessment.complexity_label == "high" or app.criticality == 5:
        return 3
    if app.compliance_scope != "none":
        return max(2, 2)
    if assessment.complexity_label == "medium":
        return 2
    return 1


def _hard_dependency_edges(session: Session, app_id: str) -> list[GraphEdge]:
    rows = (session.query(GraphEdge)
            .filter(GraphEdge.src == app_id,
                    GraphEdge.relation.in_({"APP_CALLS_APP", "APP_USES_IDENTITY",
                                            "APP_USES_DATABASE"}))
            .all())
    out = []
    for e in rows:
        if e.relation == "APP_USES_DATABASE":
            db = session.get(DatabaseRegistry, e.dst)
            if db is None or not db.is_shared_service:
                continue  # dedicated databases migrate with the app
        out.append(e)
    return out


class PlannerResult:
    def __init__(self) -> None:
        self.waves: list[int] = []
        self.memberships: list[tuple[int, str, str]] = []  # (wave, member, kind)
        self.blocked: list[dict] = []
        self.constraint_moves: list[dict] = []


def plan_waves(session: Session) -> PlannerResult:
    result = PlannerResult()

    apps = {a.id: a for a in session.query(Application).all()}
    assessments = {a.application_id: a for a in session.query(Assessment).all()}
    strategies = {s.application_id: s for s in session.query(StrategyRecommendation).all()}
    services = {s.id: s for s in session.query(SharedService).all()}

    # ---- events / outgoing calls facts (cheap once)
    event_app_ids = {
        r.application_id for r in
        session.query(CMDBRecord).filter(
            CMDBRecord.field.in_(("publishes_topic", "consumes_topic"))).all()
    }
    call_src_ids = {
        r[0] for r in session.query(GraphEdge.src)
        .filter(GraphEdge.relation == "APP_CALLS_APP").all()
    }

    # ---- preliminary assignment
    assignment: dict[str, int] = {}
    pilots: list[str] = []
    for app_id, app in sorted(apps.items()):
        strategy = strategies.get(app_id)
        if not strategy or strategy.strategy not in MIGRATING_STRATEGIES:
            continue  # RETAIN / RETIRE / missing stay off the migration train
        assessment = assessments.get(app_id)
        if assessment is None:
            continue
        db_meta = session.get(DatabaseRegistry, app.database_id) if app.database_id else None
        wave = _preliminary_wave(
            session, app, assessment, db_meta,
            has_calls=app_id in call_src_ids,
            has_events=app_id in event_app_ids,
        )
        assignment[app_id] = wave
        if wave == 0 and app.requested_wave_override is None:
            pilots.append(app_id)

    # ---- wave 0 capacity: cheapest pilots first
    if len(pilots) > MAX_CONCURRENT[0]:
        pilots.sort(key=lambda aid: (apps[aid].annual_infra_cost_usd, aid))
        for aid in pilots[MAX_CONCURRENT[0]:]:
            assignment[aid] = 1

    blocked_ids: set[str] = set()
    blocks: list[dict] = []

    def add_block(app_id: str, code: str, detail: str, suggestion: str,
                  dep_id: str | None) -> None:
        blocks.append({
            "application_id": app_id, "reason_code": code, "reason_detail": detail,
            "suggested_resolution": suggestion, "dep_id": dep_id,
        })
        blocked_ids.add(app_id)
        assignment.pop(app_id, None)

    def resolve_dep_wave(dst: str, current: dict[str, int]) -> int | None:
        if dst in blocked_ids:
            return None
        if dst in services:
            return services[dst].wave_assignment
        if dst in current:
            return current[dst]
        strategy = strategies.get(dst)
        if strategy and strategy.strategy == "RETAIN":
            return -1  # stays on-prem permanently: bridgeable
        return None  # excluded (RETIRE) or unknown

    for _iteration in range(25):
        changed = False

        # criticality cap
        for app_id in sorted(list(assignment.keys())):
            if apps[app_id].criticality == 5 and assignment[app_id] < CRITICALITY_CAP_WAVE:
                assignment[app_id] = CRITICALITY_CAP_WAVE
                changed = True

        # regulated zone readiness
        for app_id in sorted(list(assignment.keys())):
            app = apps[app_id]
            if app.compliance_scope != "none" and assignment[app_id] < REGULATED_ZONE_READY_FROM:
                if app.requested_wave_override is not None:
                    add_block(
                        app_id, "SECURITY_ZONE_NOT_READY",
                        f"{app.compliance_scope}-scoped workload pinned to wave "
                        f"{assignment[app_id]} by operator override, but regulated network "
                        f"zones are provisioned from wave {REGULATED_ZONE_READY_FROM}.",
                        f"Remove the override and schedule in wave >="
                        f"{REGULATED_ZONE_READY_FROM}, or provision the "
                        f"{app.compliance_scope} zone earlier.",
                        None,
                    )
                else:
                    result.constraint_moves.append({
                        "application_id": app_id, "from": assignment[app_id],
                        "to": REGULATED_ZONE_READY_FROM,
                        "reason": "regulated zone readiness",
                    })
                    assignment[app_id] = REGULATED_ZONE_READY_FROM
                changed = True

        # topological hard dependencies
        for app_id in sorted(list(assignment.keys())):
            wave = assignment[app_id]
            for edge in _hard_dependency_edges(session, app_id):
                dep_wave = resolve_dep_wave(edge.dst, assignment)
                if dep_wave == -1:
                    continue  # retained on-prem: connectivity bridge planned instead
                if dep_wave is None:
                    # dependency unavailable (blocked/excluded): defer this app last
                    if assignment[app_id] != 3:
                        result.constraint_moves.append({
                            "application_id": app_id, "from": assignment[app_id], "to": 3,
                            "reason": f"dependency '{edge.dst}' not yet schedulable",
                        })
                        assignment[app_id] = 3
                        changed = True
                    continue
                if dep_wave > wave:
                    if apps[app_id].requested_wave_override is not None:
                        svc_note = "shared platform service" if edge.dst in services else "dependency"
                        add_block(
                            app_id, "DEPENDENCY_IN_LATER_WAVE",
                            f"Operator override pins this app to wave {wave}, but "
                            f"{svc_note} '{edge.dst}' migrates in wave {dep_wave} "
                            f"(edge: {edge.relation}).",
                            f"Move '{edge.dst}' to wave <= {wave}, or drop the override and "
                            f"schedule this app in wave >= {dep_wave}.",
                            edge.dst,
                        )
                    else:
                        result.constraint_moves.append({
                            "application_id": app_id, "from": wave, "to": dep_wave,
                            "reason": f"dependency '{edge.dst}' is in wave {dep_wave}",
                        })
                        assignment[app_id] = dep_wave
                        changed = True
                    break

        # capacity spills (never out of wave 3). Operator-overridden apps are exempt:
        # overrides are still VALIDATED against hard constraints above (regulated zones,
        # topological dependencies), but a soft concurrency heuristic must not silently
        # displace explicitly pinned workloads.
        for w in (0, 1, 2):
            members = sorted(
                aid for aid, aw in assignment.items()
                if aw == w and apps[aid].requested_wave_override is None
            )
            cap = MAX_CONCURRENT[w]
            if len(members) > cap:
                members.sort(key=lambda aid: (-apps[aid].criticality,
                                              -apps[aid].annual_infra_cost_usd, aid))
                for aid in members[cap:]:
                    assignment[aid] = w + 1
                    result.constraint_moves.append({
                        "application_id": aid, "from": w, "to": w + 1,
                        "reason": f"wave {w} concurrency cap ({cap}) exceeded",
                    })
                    changed = True

        if not changed:
            break

    # ---- persist waves + memberships
    from app.models import Approval

    session.query(WaveMembership).delete()
    session.query(Wave).delete()
    session.query(BlockedMigration).delete()
    session.query(Approval).filter(
        Approval.subject_type == "wave",
        Approval.status == "PENDING").update({"status": "SUPERSEDED"})
    session.flush()

    wave_rows: dict[int, Wave] = {}
    for w in (0, 1, 2, 3):
        row = Wave(
            wave_number=w, name=WAVE_NAMES[w], status="PLANNED",
            max_concurrent=MAX_CONCURRENT[w],
            description={
                0: "Lowest-risk pilot workloads prove the landing zone.",
                1: "Stateless internal applications with direct managed-database paths.",
                2: "Medium-complexity replatforms plus shared platform services.",
                3: "Business-critical systems, refactors and regulated cores.",
            }[w],
        )
        session.add(row)
        wave_rows[w] = row
    session.flush()

    for svc_id, svc in sorted(services.items()):
        if svc.wave_assignment is not None:
            session.add(WaveMembership(wave_id=wave_rows[svc.wave_assignment].id,
                                       member_id=svc_id,
                                       member_kind="service", strategy="REPLATFORM",
                                       execution_status="PENDING",
                                       order_index=svc.wave_assignment))
            result.memberships.append((svc.wave_assignment, svc_id, "service"))

    for w in (0, 1, 2, 3):
        members = sorted(aid for aid, aw in assignment.items() if aw == w)
        for idx, aid in enumerate(members):
            session.add(WaveMembership(
                wave_id=wave_rows[w].id, member_id=aid, member_kind="application",
                strategy=strategies[aid].strategy, execution_status="PENDING",
                order_index=idx,
            ))
            result.memberships.append((w, aid, "application"))

    for b in blocks:
        session.add(BlockedMigration(**b))
    result.blocked = blocks
    result.waves = [0, 1, 2, 3]

    session.add(DomainEvent(
        event_type="waves.planned", subject="migration-plan",
        payload={"members": len(result.memberships), "blocked": len(blocks),
                 "constraint_moves": result.constraint_moves[:25]},
    ))
    return result
