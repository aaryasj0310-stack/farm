"""
Phase SW-C2: P3 Transactional Acreage and Complete Crop-Cycle Reservations Unit Tests.
Validates side-effect-free evaluation, full lifecycle obligation generation,
atomic multi-resource commit, binding rejections, and SWTrancheController integration.
"""

import pytest

from agent.config import (
    get_sw_p3_transactional_reservations_enabled,
    set_sw_p3_transactional_reservations_enabled,
    set_sw_adaptive_acreage_enabled,
    set_sw_max_adaptive_acreage,
    SHED_CAPACITY,
)
from agent.execution.obligation_types import (
    ReservationState,
    ObligationLifecycle,
    ObligationTier,
)
from agent.strategy.crop_cycle_reservation_manager import (
    CropCycleReservationManager,
    get_crop_cycle_reservation_manager,
    reset_crop_cycle_reservation_manager,
    get_crop_cycle_schedule,
    SHED_ACCESS_PORT,
    SW_RESERVATION_SAFETY_MARGIN,
)
from agent.strategy.sw_tranche_controller import (
    SWTrancheController,
    reset_sw_tranche_controller,
)


@pytest.fixture(autouse=True)
def cleanup_p3():
    set_sw_p3_transactional_reservations_enabled(False)
    reset_crop_cycle_reservation_manager()
    reset_sw_tranche_controller()
    yield
    set_sw_p3_transactional_reservations_enabled(False)
    reset_crop_cycle_reservation_manager()
    reset_sw_tranche_controller()


def test_default_flag_is_off():
    """Invariant: SW_P3_TRANSACTIONAL_RESERVATIONS_ENABLED must default to False."""
    assert get_sw_p3_transactional_reservations_enabled() is False


def test_crop_cycle_schedule_derivation():
    """Validates complete dated watering and harvest derivation for crops."""
    # Melon planted on Day 8: yields at Day 8 + 12 = Day 20
    yield_units, water_days, harvest_days = get_crop_cycle_schedule("MELON", 8)
    assert yield_units == 6
    assert harvest_days == [20]
    assert 8 in water_days

    # Strawberry planted on Day 8: first yield at Day 8 + 10 = Day 18, interval 2
    sb_yield, sb_water, sb_harvest = get_crop_cycle_schedule("STRAWBERRY", 8)
    assert sb_harvest == [18, 20, 22, 24]
    assert len(sb_harvest) == 4


def test_side_effect_free_trial_evaluation():
    """Trial evaluation must leave manager state and active reservations untouched."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(4, 6), (0, 7), (1, 7), (2, 7)]

    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=2000.0,
        active_workers=8,
        num_animals=2,
        wheat_inventory=20,
        current_shed_occupancy=10,
        core_planted_tiles=12,
    )

    assert trial.feasible is True
    assert trial.expected_whole_farm_delta > SW_RESERVATION_SAFETY_MARGIN
    # Manager state must NOT have committed reservations yet
    assert len(mgr.active_reservations) == 0
    assert mgr.get_telemetry()["reservations_committed"] == 0
    assert mgr.get_telemetry()["trials_evaluated"] == 1
    assert mgr.get_telemetry()["trials_approved"] == 1


def test_complete_lifecycle_obligations_generation():
    """Feasible trial must generate complete PLANT, WATER, and HARVEST obligations."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(4, 6), (0, 7), (1, 7), (2, 7)]

    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=2500.0,
        active_workers=8,
        num_animals=2,
        wheat_inventory=25,
        current_shed_occupancy=15,
        core_planted_tiles=10,
    )

    res = trial.reservation
    assert res is not None
    assert res.total_expected_yield == 24  # 4 tiles * 6 yield

    # Must contain PLANT, WATER, and HARVEST obligations
    ops = {obl.op for obl in res.obligations}
    assert "PLANT" in ops
    assert "WATER" in ops
    assert "HARVEST" in ops

    # 4 PLANT obligations on plant_day
    plant_obls = [o for o in res.obligations if o.op == "PLANT"]
    assert len(plant_obls) == 4
    for o in plant_obls:
        assert o.release_step == 8 * 24

    # 4 HARVEST obligations on Day 20
    harvest_obls = [o for o in res.obligations if o.op == "HARVEST"]
    assert len(harvest_obls) == 4
    for o in harvest_obls:
        assert o.release_step == 20 * 24


def test_atomic_commit_reservation():
    """Committing reservation transitions state to COMMITTED and logs active record."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(4, 6), (0, 7), (1, 7), (2, 7)]

    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=2000.0,
        active_workers=8,
        num_animals=2,
        wheat_inventory=20,
        current_shed_occupancy=10,
        core_planted_tiles=12,
    )

    res_id = mgr.commit_reservation(trial)
    assert res_id.startswith("RES_SW_C4_MELON_D8")
    assert len(mgr.active_reservations) == 1
    assert mgr.active_reservations[res_id].state == ReservationState.COMMITTED
    assert mgr.get_telemetry()["reservations_committed"] == 1


def test_binding_rejection_treasury_shortage():
    """Insufficient cash reserves triggers binding rejection with CASH binding resource."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(4, 6), (0, 7), (1, 7), (2, 7)]

    # Melon seed cost: 4 * 80 = $320 + $300 reserve = $620 required
    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=400.0,  # Insufficient!
        active_workers=8,
        num_animals=2,
        wheat_inventory=20,
        current_shed_occupancy=10,
        core_planted_tiles=12,
    )

    assert trial.feasible is False
    assert trial.binding_resource == "CASH"
    assert "Treasury shortage" in trial.rejection_reason
    assert len(mgr.active_reservations) == 0


def test_binding_rejection_feed_risk():
    """Insufficient wheat buffer for livestock triggers binding rejection."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(4, 6), (0, 7), (1, 7), (2, 7)]

    # 4 animals require 4 * 3 = 12 wheat buffer
    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=3000.0,
        active_workers=8,
        num_animals=4,
        wheat_inventory=5,  # Only 5 wheat! Risk!
        current_shed_occupancy=10,
        core_planted_tiles=12,
    )

    assert trial.feasible is False
    assert trial.binding_resource == "WHEAT_FEED"
    assert "Feed risk" in trial.rejection_reason


def test_binding_rejection_shed_port_violation():
    """Expansion block attempting to include reserved port (4, 5) is rejected."""
    mgr = CropCycleReservationManager()
    # (4, 5) is reserved shed port
    candidate_tiles = [(4, 5), (0, 7), (1, 7), (2, 7)]

    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=3000.0,
        active_workers=8,
        num_animals=2,
        wheat_inventory=20,
        current_shed_occupancy=10,
        core_planted_tiles=12,
    )

    assert trial.feasible is False
    assert trial.binding_resource == "GEOMETRY"
    assert "reserved shed-access port" in trial.rejection_reason


def test_binding_rejection_storage_congestion():
    """Shed congestion with high anticipated yield triggers storage rejection."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(4, 6), (0, 7), (1, 7), (2, 7)]

    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=3000.0,
        active_workers=8,
        num_animals=2,
        wheat_inventory=20,
        current_shed_occupancy=90,  # 90/100 full! Cannot take 24 melon yield!
        core_planted_tiles=12,
    )

    assert trial.feasible is False
    assert trial.binding_resource == "STORAGE_SLOT"
    assert "Storage congestion" in trial.rejection_reason


def test_sw_tranche_controller_p3_integration():
    """SWTrancheController with P3 enabled creates atomic reservation and records ID."""
    set_sw_p3_transactional_reservations_enabled(True)
    set_sw_adaptive_acreage_enabled(True)
    set_sw_max_adaptive_acreage(12)

    ctrl = SWTrancheController()
    ctrl.state.treatment_active = True
    ctrl.state.sw_purchase_confirmed = True
    ctrl.state.sw_purchase_day = 6  # purchased on Day 6
    # Seed with initial 8 tiles
    ctrl.state.admitted_sw_tiles = {
        (0, 5), (1, 5), (2, 5), (3, 5),
        (0, 6), (1, 6), (2, 6), (3, 6),
    }

    mock_farm = {
        "money": 4000.0,
        "hands": [1, 2, 3, 4, 5, 6, 7],
        "tiles": [],
    }

    mock_ctx = {
        "day": 8,
        "hour": 0,
        "farm": mock_farm,
        "private": {"shed": {"WHEAT": 25}, "inventories": []},
        "market": {"inventory": {}},
    }

    decision = ctrl.maybe_evaluate_adaptive_expansion(mock_ctx, mock_farm, None)
    assert decision is not None
    assert decision.approved is True
    assert len(ctrl.state.admitted_sw_tiles) == 12

    # Verify reservation ID is recorded in expansion history
    assert len(ctrl.state.adaptive_expansion_history) == 1
    event = ctrl.state.adaptive_expansion_history[0]
    assert "reservation_id" in event
    assert event["reservation_id"].startswith("RES_SW_C4")

    # Verify reservation manager has active reservation
    res_mgr = get_crop_cycle_reservation_manager()
    assert len(res_mgr.active_reservations) == 1
