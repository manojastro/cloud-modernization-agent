"""Constraint-aware wave planning: blocked migrations, pinned overrides, service waves."""
from simulator.generate_estate import (
    PILOT_APPS,
    WAVE1_INCOMPATIBLE_APP,
)
from app.models import BlockedMigration, SharedService, Wave, WaveMembership
from app.waves.planner import MAX_CONCURRENT


def _memberships(session):
    out = {}
    for m, w in (session.query(WaveMembership, Wave)
                 .filter(WaveMembership.wave_id == Wave.id).all()):
        if m.member_kind == "application":
            out[m.member_id] = w.wave_number
    return out


def test_expected_apps_are_blocked_with_reason_codes(planned):
    session, _ = planned
    blocked = {b.application_id: b.reason_code
               for b in session.query(BlockedMigration).all()}
    assert blocked.get("commission-settlement-engine") == "DEPENDENCY_IN_LATER_WAVE"
    assert blocked.get("card-dispute-tracker") == "SECURITY_ZONE_NOT_READY"
    # every block carries an actionable suggestion
    for b in session.query(BlockedMigration).all():
        assert b.suggested_resolution and b.reason_detail


def test_operator_override_pins_receivables_to_wave_1(planned):
    session, _ = planned
    waves = _memberships(session)
    assert waves.get(WAVE1_INCOMPATIBLE_APP) == 1


def test_pilots_land_in_wave_0(planned):
    session, _ = planned
    waves = _memberships(session)
    for pilot in PILOT_APPS:
        assert waves.get(pilot) == 0, pilot


def test_shared_services_are_waved_before_consumers(planned):
    session, _ = planned
    svc = {s.id: s.wave_assignment for s in session.query(SharedService).all()}
    assert svc["svc-corporate-ldap"] == 0
    assert svc["svc-sso-provider"] == 0
    assert svc["svc-esb-messaging"] == 1
    assert svc["svc-shared-oracle-11g"] == 2
    # services appear as memberships too
    svc_members = {m.member_id: w.wave_number
                   for m, w in session.query(WaveMembership, Wave)
                   .filter(WaveMembership.wave_id == Wave.id).all()
                   if m.member_kind == "service"}
    for sid, wave_no in svc.items():
        if wave_no <= 3:
            assert svc_members.get(sid) == wave_no, sid


def test_retained_apps_stay_off_the_migration_train(planned):
    from app.models import StrategyRecommendation

    session, _ = planned
    waves = _memberships(session)
    retained = [s.application_id for s in session.query(StrategyRecommendation).all()
                if s.strategy in ("RETAIN", "RETIRE")]
    assert retained, "estate must contain RETAIN/RETIRE apps for this assertion"
    for app_id in retained:
        assert app_id not in waves


def test_capacity_cap_respected_for_non_overridden_apps(planned):
    from app.models import Application

    session, _ = planned
    per_wave: dict[int, int] = {}
    for m, w in (session.query(WaveMembership, Wave)
                 .filter(WaveMembership.wave_id == Wave.id).all()):
        if m.member_kind != "application":
            continue
        app = session.get(Application, m.member_id)
        if app is not None and app.requested_wave_override is not None:
            continue  # overrides are exempt from soft capacity spills by design
        per_wave[w.wave_number] = per_wave.get(w.wave_number, 0) + 1
    for wave_no, count in per_wave.items():
        assert count <= MAX_CONCURRENT[wave_no], (wave_no, count)


def test_waves_are_zero_to_three(planned):
    session, _ = planned
    numbers = sorted(w.wave_number for w in session.query(Wave).all())
    assert numbers == [0, 1, 2, 3]
    for w in session.query(Wave).all():
        # pipeline preflights push waves to AWAITING_APPROVAL; nothing executes
        # until a persisted human approval exists.
        assert w.status in ("PLANNED", "AWAITING_APPROVAL")
        assert w.status != "APPROVED" or w.approval_id is not None
