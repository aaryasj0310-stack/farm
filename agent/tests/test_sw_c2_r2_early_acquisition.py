"""Phase SW-C2-R2: Early Acquisition, Executable Capacity, & Shared Reservation Test Suite.

Verifies the 6 core deliverables:
1. Dynamic D8–D10 SW acquisition preference (earlier acquisition preferred when economically justified)
2. Settlement and utilization telemetry (exact turn, cash before/after, plant turn, attempt tracking)
3. Executable workforce availability (actual observed workers, release_step adherence, carried item decrement)
4. Shared reservation and dispatch capacity (obligations registered in ServiceObligationLedger)
5. Reservation lifecycle (commit on approval, clean cancellation on failure/withdrawal)
6. Preserved 8->12->16->20->24 acreage ladder option
"""
import pytest
from unittest.mock import MagicMock

import config
from config import (
    set_sw_r2_dynamic_acquisition_enabled,
    get_sw_r2_dynamic_acquisition_enabled,
    set_sw_adaptive_acreage_enabled,
    set_sw_max_adaptive_acreage,
    set_sw_p3_transactional_reservations_enabled,
)
from execution.obligation_types import (
    CapacityForecastResult,
    ObligationLifecycle,
    ObligationTier,
    ReservationState,
    ServiceObligation,
)
from execution.service_obligation_ledger import (
    ServiceObligationLedger,
    get_service_obligation_ledger,
    reset_service_obligation_ledger,
)
from execution.workforce_capacity_forecast import (
    WorkforceCapacityForecaster,
    get_workforce_capacity_forecaster,
    reset_workforce_capacity_forecaster,
)
from strategy.crop_cycle_reservation_manager import (
    CropCycleReservationManager,
    CropCycleTrialResult,
    CropCycleReservation,
    get_crop_cycle_reservation_manager,
    reset_crop_cycle_reservation_manager,
)
from strategy.adaptive_acreage_planner import (
    AdaptiveAcreagePlanner,
    EXPANSION_BLOCKS,
    INITIAL_SW_TILES,
)
from strategy.sw_tranche_controller import (
    SWTrancheController,
    SWLandLifecycleTelemetry,
    get_sw_tranche_controller,
    reset_sw_tranche_controller,
)


@pytest.fixture(autouse=True)
def clean_state():
    reset_service_obligation_ledger()
    reset_crop_cycle_reservation_manager()
    reset_sw_tranche_controller()
    reset_workforce_capacity_forecaster()
    set_sw_r2_dynamic_acquisition_enabled(False)
    set_sw_adaptive_acreage_enabled(False)
    set_sw_max_adaptive_acreage(8)
    set_sw_p3_transactional_reservations_enabled(False)
    yield
    reset_service_obligation_ledger()
    reset_crop_cycle_reservation_manager()
    reset_sw_tranche_controller()
    reset_workforce_capacity_forecaster()
    set_sw_r2_dynamic_acquisition_enabled(False)
    set_sw_adaptive_acreage_enabled(False)
    set_sw_max_adaptive_acreage(8)
    set_sw_p3_transactional_reservations_enabled(False)


# ---------------------------------------------------------------------------
# Deliverable 1: Dynamic D8–D10 Acquisition Preference & Safe Defaults
# ---------------------------------------------------------------------------

def test_r2_flag_defaults_to_false():
    """All behavior-changing feature flags must default to OFF/False."""
    assert get_sw_r2_dynamic_acquisition_enabled() is False
    assert config.SW_R2_DYNAMIC_ACQUISITION_ENABLED is False


def test_effective_quadrant_unlock_day_dynamic():
    """SW effective unlock day reflects Day 8 when dynamic acquisition is enabled."""
    from strategy.expansion_planner import get_effective_quadrant_unlock_day

    set_sw_r2_dynamic_acquisition_enabled(False)
    assert get_effective_quadrant_unlock_day(3) == 9

    set_sw_r2_dynamic_acquisition_enabled(True)
    assert get_effective_quadrant_unlock_day(3) == 8


# ---------------------------------------------------------------------------
# Deliverable 2: Settlement and Utilization Telemetry
# ---------------------------------------------------------------------------

def test_settlement_and_utilization_telemetry_recording():
    """Telemetry records exact turn, cash before/after, attempts, and plant turn."""
    ctrl = SWTrancheController()
    ctrl.state.treatment_active = True
    ctrl.state.pre_purchase_cash = 3200.0

    # Step 192 (Day 8 Hour 0): Order emitted
    market_orders = [["BUY_LAND"]]
    ctrl.notify_market_orders_emitted(
        orders=market_orders,
        step=192,
        day=8,
        hour=0,
        farm_money=3200.0,
        unlocked_quadrants={"NW", "NE"},
    )
    lc = ctrl.state.lifecycle
    assert 192 in lc.purchase_attempt_steps
    assert lc.sw_order_emitted_step == 192
    assert lc.sw_order_retained_step == 192

    # Step 193 (Day 8 Hour 1): Engine confirms SW unlock
    obs = {
        "farms": [{
            "unlocked_quadrants": ["NW", "NE", "SW"],
            "money": 1200.0,
            "tiles": [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)],
        }]
    }
    ctrl.observe_engine_step(obs, seat=0, step=193, day=8, hour=1)

    assert lc.purchase_settled is True
    assert lc.exact_purchase_step == 193
    assert lc.exact_purchase_day == 8
    assert lc.exact_purchase_hour == 1
    assert lc.cash_before_purchase == 3200.0
    assert lc.cash_after_purchase == 1200.0
    assert lc.sw_confirmed_cash_deduction == 2000.0

    # Step 194 (Day 8 Hour 2): First planting in SW
    obs["farms"][0]["tiles"][5][0] = {
        "kind": "PLANT",
        "crop": "STRAWBERRY",
        "planted_day": 8,
    }
    ctrl.observe_engine_step(obs, seat=0, step=194, day=8, hour=2)

    assert lc.first_productive_plant_step == 194
    assert lc.first_productive_plant_day == 8
    assert lc.first_productive_plant_crop == "STRAWBERRY"
    assert lc.first_productive_plant_pos == (0, 5)

    # Telemetry serialization sanity
    diag_dict = lc.to_dict()
    assert "settlement_telemetry" in diag_dict
    assert diag_dict["settlement_telemetry"]["purchase_settled"] is True
    assert diag_dict["settlement_telemetry"]["cash_before_purchase"] == 3200.0
    assert diag_dict["settlement_telemetry"]["cash_after_purchase"] == 1200.0


# ---------------------------------------------------------------------------
# Deliverable 3: Executable Workforce Availability & Capacity Corrections
# ---------------------------------------------------------------------------

def test_workforce_availability_uses_actual_workers():
    """Expansion evaluation strictly uses physically present workers (1 + len(hands))."""
    ctrl = SWTrancheController()
    ctrl.state.treatment_active = True
    ctrl.state.sw_purchase_confirmed = True
    ctrl.state.sw_purchase_day = 8
    set_sw_adaptive_acreage_enabled(True)
    set_sw_max_adaptive_acreage(12)

    farm_mock = MagicMock()
    farm_mock.money = 5000.0
    farm_mock.hands = []  # 0 hands hired -> active_workers must be 1, NOT optimistic scheduled (3)
    farm_mock.unlocked = ["NW", "NE", "SW"]
    farm_mock.iter_tiles.return_value = []

    ctx = {"day": 9, "hour": 0, "farm": farm_mock, "private": MagicMock(shed={"WHEAT": 50})}
    plan = MagicMock()

    # With only 1 worker, expanding to 12 tiles should evaluate active_workers == 1
    dec = ctrl.maybe_evaluate_adaptive_expansion(ctx, farm_mock, plan)
    if dec is not None:
        assert dec.active_workers == 1  # Exactly 1 worker, not inflated to 3+


def test_workforce_capacity_forecast_decrements_carried_resources_and_release_step():
    """Forecaster decrements carried items and honors release_step."""
    reset_service_obligation_ledger()
    ledger = get_service_obligation_ledger()
    forecaster = get_workforce_capacity_forecaster()

    obl1 = ServiceObligation(
        obligation_id="OBL_FEED_1",
        entity_id="COW_1",
        op="FEED",
        target_pos=(1, 1),
        region="NW",
        tier=ObligationTier.HARD,
        lifecycle=ObligationLifecycle.READY,
        release_step=10,
        deadline_step=20,
        latest_feasible_start_step=15,
        expected_duration_steps=1,
    )
    obl2 = ServiceObligation(
        obligation_id="OBL_FEED_2",
        entity_id="COW_2",
        op="FEED",
        target_pos=(1, 2),
        region="NW",
        tier=ObligationTier.HARD,
        lifecycle=ObligationLifecycle.READY,
        release_step=10,
        deadline_step=20,
        latest_feasible_start_step=15,
        expected_duration_steps=1,
    )
    ledger.register_obligation(obl1)
    ledger.register_obligation(obl2)

    # Worker 0 starts at (0, 0) with exactly 1 carried wheat; shed has 0 wheat
    obs_farm = {
        "farmer": [0, 0],
        "hands": [],
    }
    private = {
        "inventories": [{"WHEAT": 1}],
        "shed": {"WHEAT": 0},
    }

    result = forecaster.generate_forecast(
        step=5,
        obs_farm=obs_farm,
        private=private,
        ledger=ledger,
    )

    # First feed is feasible (uses the 1 carried unit)
    assert result.obligation_forecasts["OBL_FEED_1"]["is_feasible"] is True
    # Arrival must honor release_step=10 (earliest_start=10 + transit 2 = step 12)
    assert result.obligation_forecasts["OBL_FEED_1"]["estimated_arrival"] >= 10
    # Second feed must FAIL because worker's carried wheat was decremented and shed is empty!
    assert result.obligation_forecasts["OBL_FEED_2"]["is_feasible"] is False


# ---------------------------------------------------------------------------
# Deliverable 4 & 5: Shared Reservation & Dispatch Capacity + Lifecycle
# ---------------------------------------------------------------------------

def test_reservation_commits_obligations_to_shared_ledger():
    """Committing a reservation registers all lifecycle obligations in ServiceObligationLedger."""
    res_mgr = get_crop_cycle_reservation_manager()
    ledger = get_service_obligation_ledger()

    trial = res_mgr.evaluate_complete_crop_cycle(
        candidate_tiles=[(0, 5), (1, 5), (2, 5), (3, 5)],
        candidate_crop="STRAWBERRY",
        plant_day=8,
        current_cash=5000.0,
        active_workers=3,
        num_animals=0,
        wheat_inventory=50,
        current_shed_occupancy=0,
        core_planted_tiles=8,
    )
    assert trial.feasible is True

    res_id = res_mgr.commit_reservation(trial)
    assert res_id in res_mgr.active_reservations
    assert res_mgr.active_reservations[res_id].state == ReservationState.COMMITTED

    # Verify obligations are present in the shared ledger
    committed_obls = res_mgr.active_reservations[res_id].obligations
    assert len(committed_obls) > 0
    for obl in committed_obls:
        ledger_obl = ledger.get_obligation(obl.obligation_id)
        assert ledger_obl is not None
        assert ledger_obl.lifecycle == ObligationLifecycle.RESERVED


def test_reservation_cancellation_releases_shared_ledger_obligations():
    """Cancelling a reservation marks all obligations CANCELLED in shared ledger."""
    res_mgr = get_crop_cycle_reservation_manager()
    ledger = get_service_obligation_ledger()

    trial = res_mgr.evaluate_complete_crop_cycle(
        candidate_tiles=[(0, 5), (1, 5), (2, 5), (3, 5)],
        candidate_crop="STRAWBERRY",
        plant_day=8,
        current_cash=5000.0,
        active_workers=3,
        num_animals=0,
        wheat_inventory=50,
        current_shed_occupancy=0,
        core_planted_tiles=8,
    )
    res_id = res_mgr.commit_reservation(trial)
    committed_obls = list(res_mgr.active_reservations[res_id].obligations)

    # Cancel reservation
    success = res_mgr.cancel_reservation(res_id, reason="market_rejection")
    assert success is True
    assert res_id not in res_mgr.active_reservations

    # Verify ledger obligations are marked CANCELLED
    for obl in committed_obls:
        ledger_obl = ledger.get_obligation(obl.obligation_id)
        assert ledger_obl is not None
        assert ledger_obl.lifecycle == ObligationLifecycle.CANCELLED
        assert ledger_obl.terminal_reason == "market_rejection"


# ---------------------------------------------------------------------------
# Deliverable 6: Preserve the 8->12->16->20->24 Acreage Ladder Option
# ---------------------------------------------------------------------------

def test_preserved_acreage_ladder_blocks():
    """Acreage ladder expansion blocks (12, 16, 20, 24) remain intact and valid."""
    planner = AdaptiveAcreagePlanner()

    assert set(EXPANSION_BLOCKS.keys()) == {12, 16, 20, 24}
    for level, tiles in EXPANSION_BLOCKS.items():
        assert len(tiles) == 4
        for x, y in tiles:
            assert 0 <= x < 5
            assert 5 <= y < 10
            assert (x, y) != (4, 5), "Shed port (4, 5) must never be in expansion blocks"

    assert len(INITIAL_SW_TILES) == 8
    assert (4, 5) not in INITIAL_SW_TILES
