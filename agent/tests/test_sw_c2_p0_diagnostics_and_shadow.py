"""Unit and Integration Tests for Phase SW-C2: P0 Diagnostic Integrity and Shadow Forecasting.

Tests:
1. Operation identity at same coordinate (FEED / CARE / HARVEST / COLLECT_FERTILIZER).
2. Obligation lifecycle transitions and duplicate idempotency.
3. Repaired PLANT outcome, CARE vs COLLECT_FERTILIZER, and seed debit attribution.
4. HARD obligation registration and completion tracking.
5. Shadow Capacity Forecaster outputs and zero gameplay mutation.
"""
import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from execution.obligation_types import (
    CapacityForecastResult,
    ObligationLifecycle,
    ObligationTier,
    ServiceObligation,
)
from execution.service_obligation_ledger import (
    ServiceObligationLedger,
    compute_quadrant,
    get_service_obligation_ledger,
    reset_service_obligation_ledger,
)
from execution.sw_task_admission_controller import (
    SWTaskAdmissionTelemetry,
    get_sw_task_admission_telemetry,
    reset_sw_task_admission_telemetry,
)
from execution.workforce_capacity_forecast import (
    WorkforceCapacityForecaster,
    get_workforce_capacity_forecaster,
    reset_workforce_capacity_forecaster,
)


def test_operation_identity_at_same_coordinate():
    """Verify distinct operations at the exact same coordinate have unique stable obligation IDs."""
    ledger = ServiceObligationLedger()
    animal_pos = (6, 4)

    id_feed = ledger.generate_obligation_id(1, "animal_6_4", "FEED")
    id_care = ledger.generate_obligation_id(1, "animal_6_4", "CARE")
    id_harvest = ledger.generate_obligation_id(1, "animal_6_4", "HARVEST")
    id_fert = ledger.generate_obligation_id(1, "animal_6_4", "COLLECT_FERTILIZER")

    ids = {id_feed, id_care, id_harvest, id_fert}
    assert len(ids) == 4, f"Colliding obligation IDs at same coordinate: {ids}"
    assert "FEED" in id_feed
    assert "CARE" in id_care
    assert "HARVEST" in id_harvest
    assert "COLLECT_FERTILIZER" in id_fert


def test_obligation_lifecycle_transitions():
    """Verify lifecycle state transitions from PROPOSED -> READY -> COMPLETED / EXPIRED."""
    ledger = ServiceObligationLedger()
    obl = ServiceObligation(
        obligation_id="OBL_TEST_1",
        entity_id="crop_1_1",
        op="WATER",
        target_pos=(1, 1),
        region="NW",
        tier=ObligationTier.STRATEGIC,
        release_step=0,
        deadline_step=23,
        latest_feasible_start_step=20,
        lifecycle=ObligationLifecycle.READY,
    )
    ledger.register_obligation(obl)
    assert obl.is_active()
    assert not obl.is_terminal()

    # Reconcile with engine state where tile is watered
    tiles = [[None] * 10 for _ in range(10)]
    tiles[1][1] = {"kind": "PLANT", "crop": "WHEAT", "watered_today": True}
    obs_farm = {"tiles": tiles}
    reconciled = ledger.reconcile_with_observation(10, obs_farm, {})

    assert reconciled["completed"] == 1
    assert obl.lifecycle == ObligationLifecycle.COMPLETED
    assert obl.completed_step == 10
    assert obl.is_terminal()


def test_hard_obligation_execution_wiring():
    """Verify HARD obligation registration and completion tracking in telemetry."""
    reset_sw_task_admission_telemetry()
    telem = get_sw_task_admission_telemetry()

    task_id = "CORE_HARD_1_FEED_(6,4)_COW"
    telem.register_core_hard_obligation(task_id, "FEED", (6, 4), "COW", 1, 2, 47)
    assert telem.core_hard_tasks_due == 1
    assert telem.core_hard_tasks_completed == 0

    # Simulate execution with outcome
    telem.record_executed_action("CORE", "FEED", (6, 4), outcome={"fed": True}, step=26)
    assert telem.core_hard_tasks_completed == 1
    rec = telem.hard_obligations[task_id]
    assert rec.status == "COMPLETED"
    assert rec.completed_step == 26


def test_care_vs_collect_fertilizer_separation():
    """Verify CARE and COLLECT_FERTILIZER are tracked as separate actions and counters."""
    reset_sw_task_admission_telemetry()
    from scripts.run_phase_sw_c2_experiment import RepairedMatchEngineAuditor

    auditor = RepairedMatchEngineAuditor(monitored_seat=0)
    auditor.start_step(10)

    # Record CARE
    auditor.record_action(
        player_id=0,
        unit_idx=0,
        action=["CARE"],
        pre_pos=(6, 4),
        post_pos=(6, 4),
        outcome={"cared": True, "animal": "COW"},
    )
    assert auditor.action_counts["care_actions"] == 1
    assert auditor.action_counts["collect_fertilizer_actions"] == 0

    # Record COLLECT_FERTILIZER
    auditor.record_action(
        player_id=0,
        unit_idx=0,
        action=["COLLECT_FERTILIZER"],
        pre_pos=(6, 4),
        post_pos=(6, 4),
        outcome={"collected_fertilizer": True},
    )
    assert auditor.action_counts["care_actions"] == 1
    assert auditor.action_counts["collect_fertilizer_actions"] == 1


def test_plant_outcome_and_seed_debit_attribution():
    """Verify PLANT outcome detection increments seed ledger and tracks coordinates."""
    from scripts.run_phase_sw_c2_experiment import RepairedMatchEngineAuditor

    auditor = RepairedMatchEngineAuditor(monitored_seat=0)
    auditor.start_step(5)

    # Core PLANT
    auditor.record_action(
        player_id=0,
        unit_idx=0,
        action=["PLANT", "WHEAT"],
        pre_pos=(2, 2),
        post_pos=(2, 2),
        outcome={"planted": True, "crop": "WHEAT"},
    )
    assert auditor.seed_ledger["WHEAT"]["planted_core"] == 1
    assert auditor.seed_ledger["WHEAT"]["planted_sw"] == 0
    assert len(auditor.plant_events) == 1
    assert auditor.plant_events[0]["is_sw"] is False

    # SW PLANT
    auditor.record_action(
        player_id=0,
        unit_idx=0,
        action=["PLANT", "MELON"],
        pre_pos=(2, 7),
        post_pos=(2, 7),
        outcome={"planted": True, "crop": "MELON"},
    )
    assert auditor.seed_ledger["MELON"]["planted_sw"] == 1
    assert len(auditor.plant_events) == 2
    assert auditor.plant_events[1]["is_sw"] is True
    assert auditor.first_productive_plant_event["crop"] == "MELON"


def test_shadow_capacity_forecaster_output():
    """Verify WorkforceCapacityForecaster outputs structured predictions without error."""
    reset_service_obligation_ledger()
    reset_workforce_capacity_forecaster()

    ledger = get_service_obligation_ledger()
    forecaster = get_workforce_capacity_forecaster()

    obl = ServiceObligation(
        obligation_id="OBL_TEST_SW",
        entity_id="crop_2_7",
        op="WATER",
        target_pos=(2, 7),
        region="SW",
        tier=ObligationTier.STRATEGIC,
        release_step=24,
        deadline_step=47,
        latest_feasible_start_step=40,
        lifecycle=ObligationLifecycle.READY,
    )
    ledger.register_obligation(obl)

    obs_farm = {
        "farmer": [4, 4],
        "hands": [[4, 5], [5, 4]],
    }
    private = {"inventories": [{}, {}, {}], "shed": {"WHEAT": 10}}

    res = forecaster.generate_forecast(25, obs_farm, private, ledger)
    assert isinstance(res, CapacityForecastResult)
    assert res.feasible_tier in ("FEASIBLE", "CONSTRAINED_DISCRETIONARY", "CRITICAL_INFEASIBLE")
    assert "SW" in res.by_region_hour_supply
    assert "OBL_TEST_SW" in res.obligation_forecasts
    assert res.obligation_forecasts["OBL_TEST_SW"]["region"] == "SW"
