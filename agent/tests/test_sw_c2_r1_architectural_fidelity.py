"""
Phase SW-C2-R1 Architectural Fidelity & Lifecycle Tests.

Validates:
1. Time-dependent worker availability queues & competing worker assignments.
2. Service-chain dependencies (shed pickup before feeding when worker has no inventory).
3. Candidate schedule evaluation via WorkforceCapacityForecaster.
4. Defensible incremental whole-farm delta deducting feed displacement costs.
5. Reservation lifecycle reconciliation: unharvested crops marked FAILED, not FULFILLED.
"""

import pytest

from agent.config import SHED_CAPACITY
from agent.execution.obligation_types import (
    ObligationLifecycle,
    ObligationTier,
    ReservationState,
    ServiceObligation,
)
from agent.execution.service_obligation_ledger import (
    ServiceObligationLedger,
    reset_service_obligation_ledger,
)
from agent.execution.workforce_capacity_forecast import (
    WorkforceCapacityForecaster,
    get_workforce_capacity_forecaster,
    reset_workforce_capacity_forecaster,
)
from agent.strategy.crop_cycle_reservation_manager import (
    CropCycleReservationManager,
    reset_crop_cycle_reservation_manager,
    SW_RESERVATION_SAFETY_MARGIN,
)


@pytest.fixture(autouse=True)
def cleanup():
    reset_service_obligation_ledger()
    reset_workforce_capacity_forecaster()
    reset_crop_cycle_reservation_manager()
    yield
    reset_service_obligation_ledger()
    reset_workforce_capacity_forecaster()
    reset_crop_cycle_reservation_manager()


def test_time_dependent_competing_worker_assignments():
    """Worker availability queues sequence obligations sequentially rather than simultaneously."""
    forecaster = WorkforceCapacityForecaster()
    ledger = ServiceObligationLedger()

    # 1 worker (farmer at 4,4)
    obs_farm = {"farmer": (4, 4), "hands": []}
    private = {"inventories": [{}], "shed": {}}

    # 2 watering obligations at distance 2 and distance 4
    obl1 = ServiceObligation(
        obligation_id="OBL_WATER_1",
        entity_id="TILE_1",
        op="WATER",
        target_pos=(4, 6),  # dist 2
        region="SW",
        tier=ObligationTier.HARD,
        lifecycle=ObligationLifecycle.READY,
        release_step=0,
        deadline_step=20,
    )
    obl2 = ServiceObligation(
        obligation_id="OBL_WATER_2",
        entity_id="TILE_2",
        op="WATER",
        target_pos=(4, 8),  # dist 2 from obl1
        region="SW",
        tier=ObligationTier.HARD,
        lifecycle=ObligationLifecycle.READY,
        release_step=0,
        deadline_step=20,
    )

    ledger.register_obligation(obl1)
    ledger.register_obligation(obl2)

    fc = forecaster.generate_forecast(step=0, obs_farm=obs_farm, private=private, ledger=ledger)
    assert fc.feasible_tier == "FEASIBLE"
    # Obl1: arrival at 0 + 2 = 2, completion at 3
    # Obl2: must start after obl1 finishes at step 3, arrival at 3 + 2 = 5, completion at 6
    o1_diag = fc.obligation_forecasts["OBL_WATER_1"]
    o2_diag = fc.obligation_forecasts["OBL_WATER_2"]
    assert o1_diag["estimated_arrival"] == 2
    assert o1_diag["projected_completion"] == 3
    assert o2_diag["estimated_arrival"] == 5
    assert o2_diag["projected_completion"] == 6


def test_service_chain_feed_prerequisite_shed_transit():
    """If worker does not carry wheat, forecaster models transit to shed before feeding."""
    forecaster = WorkforceCapacityForecaster()
    ledger = ServiceObligationLedger()

    # Farmer at (0, 0), Shed access at (4, 4), Animal at (0, 2)
    obs_farm = {"farmer": (0, 0), "hands": []}
    # Farmer has NO wheat, but shed has wheat
    private = {"inventories": [{}], "shed": {"WHEAT": 10}}

    obl = ServiceObligation(
        obligation_id="OBL_FEED_1",
        entity_id="COW_1",
        op="FEED",
        target_pos=(0, 2),
        region="NW",
        tier=ObligationTier.HARD,
        lifecycle=ObligationLifecycle.READY,
        release_step=0,
        deadline_step=30,
    )
    ledger.register_obligation(obl)

    fc = forecaster.generate_forecast(step=0, obs_farm=obs_farm, private=private, ledger=ledger)
    assert fc.feasible_tier == "FEASIBLE"
    o_diag = fc.obligation_forecasts["OBL_FEED_1"]
    # Direct transit would be dist((0,0), (0,2)) = 2
    # But because worker lacks wheat, transit must go via nearest shed (4,4):
    # dist((0,0), (4,4)) = 8 + 1 (pickup) + dist((4,4), (0,2)) = 6 => total transit = 15!
    assert o_diag["estimated_arrival"] == 15
    assert o_diag["projected_completion"] == 16


def test_evaluate_candidate_schedule_capacity_overload():
    """Candidate obligations exceeding daily workforce threshold are rejected."""
    forecaster = WorkforceCapacityForecaster()
    ledger = ServiceObligationLedger()

    # 1 worker -> daily supply = 24 hours. Max allowed at 85% = 20.4 hours.
    obs_farm = {"farmer": (4, 4), "hands": []}
    private = {"inventories": [{}], "shed": {}}

    # Create 20 candidate obligations on Day 10 (each 1h + 2h transit = 3h load each -> 60h demand!)
    candidate_obls = [
        ServiceObligation(
            obligation_id=f"OBL_TEST_{i}",
            entity_id=f"T_{i}",
            op="WATER",
            target_pos=(0, 6),
            region="SW",
            release_step=10 * 24,
            deadline_step=10 * 24 + 23,
            expected_duration_steps=1,
        )
        for i in range(20)
    ]

    feasible, reason, diag = forecaster.evaluate_candidate_schedule(
        candidate_obligations=candidate_obls,
        current_step=0,
        obs_farm=obs_farm,
        private=private,
        ledger=ledger,
        max_load_threshold=0.85,
    )
    assert feasible is False
    assert "Labor overload on Day 10" in reason
    assert diag["binding_day"] == 10


def test_defensible_whole_farm_delta_deducts_feed_displacement():
    """Whole-farm delta deducts feed displacement costs from gross margin."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(4, 6), (0, 7), (1, 7), (2, 7)]

    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=3000.0,
        active_workers=8,
        num_animals=2,
        wheat_inventory=25,
        current_shed_occupancy=10,
        core_planted_tiles=12,
        market_inventories={"WHEAT": 100, "MELON": 100},
    )

    assert trial.feasible is True
    res = trial.reservation
    assert res is not None
    # Verify feed displacement cost was calculated and deducted
    feed_disp = res.metadata.get("feed_displacement_cost", 0.0)
    assert feed_disp > 0.0
    # Expected net margin = gross - seed - feed_displacement
    expected_margin = res.expected_gross_revenue - res.seed_cost - feed_disp
    assert abs(res.expected_net_margin - expected_margin) < 1e-4


def test_lifecycle_reconciliation_unharvested_failure():
    """If tiles still have unharvested crop after last_harvest_day, reservation is FAILED, not FULFILLED."""
    mgr = CropCycleReservationManager()
    candidate_tiles = [(0, 7)]

    trial = mgr.evaluate_complete_crop_cycle(
        candidate_tiles=candidate_tiles,
        candidate_crop="MELON",
        plant_day=8,
        current_cash=3000.0,
        active_workers=8,
        num_animals=2,
        wheat_inventory=20,
        current_shed_occupancy=10,
        core_planted_tiles=10,
    )
    res_id = mgr.commit_reservation(trial)
    assert res_id in mgr.active_reservations

    # Simulation context on Day 21 (after Day 20 harvest): tile (0,7) still has mature crop!
    # Build 10x10 mock tiles
    tiles = [[{"crop": None, "stage": None} for _ in range(10)] for _ in range(10)]
    tiles[7][0] = {"crop": "MELON", "stage": "mature"}  # Crop was never harvested!

    mock_ctx = {
        "day": 21,
        "hour": 0,
        "step": 21 * 24,
        "farm": {"tiles": tiles},
    }

    mgr.reconcile_turn(mock_ctx)
    # Must NOT be marked fulfilled!
    assert mgr.get_telemetry()["reservations_fulfilled"] == 0
    assert mgr.get_telemetry()["reservations_failed"] == 1
    assert res_id not in mgr.active_reservations
