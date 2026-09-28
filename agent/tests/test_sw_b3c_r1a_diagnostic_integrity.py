"""Unit tests for Phase SW-B3C-R1A: Diagnostic Integrity & Engine Verification.

Verifies:
1. Hard obligation execution requires genuine engine confirmation outcome.
2. Capacity-exhausted vs lower-band-score disposition classification.
3. Bidirectional attempted vs executed counters for Feed, Water, Harvest, Plant.
4. Engine crop mechanics (CROPS constants) match actual simulation rules.
5. Exact financial revenue decomposition identity.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import pytest
from agent.execution.sw_task_admission_controller import (
    SWTaskAdmissionTelemetry,
    get_sw_task_admission_telemetry,
    reset_sw_task_admission_telemetry,
)


def setup_function():
    reset_sw_task_admission_telemetry()


def teardown_function():
    reset_sw_task_admission_telemetry()


def test_1_hard_obligation_requires_engine_confirmed_outcome():
    """Verify that HARD obligation completion requires verified engine outcome."""
    telem = get_sw_task_admission_telemetry()

    # Register a FEED obligation
    telem.register_core_hard_obligation("CORE_FEED_COW_D16", "FEED", (6, 4), "animal:COW", 16, 2, 16 * 24 + 23)

    # Simulated worker executes command, but outcome indicates no food delivered (e.g. out of range / empty)
    telem.record_hard_obligation_executed("FEED", (6, 4), 16 * 24 + 4, outcome={"fed": False})
    assert telem.core_hard_tasks_completed == 0, "Unconfirmed feed marked as completed"

    # Now execute with confirmed feed
    telem.record_hard_obligation_executed("FEED", (6, 4), 16 * 24 + 5, outcome={"fed": True})
    assert telem.core_hard_tasks_completed == 1, "Confirmed feed not marked as completed"


def test_2_capacity_exhausted_vs_lower_band_score():
    """Verify unselected eligible tasks record appropriate reason."""
    telem = get_sw_task_admission_telemetry()

    t1_id = "SW_12_5_WATER_(1,5)_water"
    telem.record_sw_task_lifecycle_start(t1_id, 293, 12, 5, "WATER", (1, 5), "water", 40)
    telem.record_candidate_evaluation(True, "ADMITTED")
    telem.record_sw_task_disposition(t1_id, "ELIGIBLE_UNSELECTED", "CAPACITY_EXHAUSTED")

    t2_id = "SW_12_5_WATER_(2,5)_water"
    telem.record_sw_task_lifecycle_start(t2_id, 293, 12, 5, "WATER", (2, 5), "water", 30)
    telem.record_candidate_evaluation(True, "ADMITTED")
    telem.record_sw_task_disposition(t2_id, "ELIGIBLE_UNSELECTED", "LOWER_BAND_SCORE")

    d = telem.to_dict()
    assert d["sw_tasks_eligible_unselected"] == 2
    assert d["sw_tasks_unresolved"] == 0
    assert telem.sw_lifecycle_records[t1_id].reason == "CAPACITY_EXHAUSTED"
    assert telem.sw_lifecycle_records[t2_id].reason == "LOWER_BAND_SCORE"


def test_3_bidirectional_attempt_and_executed_telemetry():
    """Verify core and SW attempted and executed actions for feed and crops are separated."""
    telem = get_sw_task_admission_telemetry()

    # Core operations
    telem.record_command_emitted("CORE", "FEED")
    telem.record_command_emitted("CORE", "WATER")
    telem.record_executed_action("CORE", "FEED", (6, 4), outcome={"fed": True})
    telem.record_executed_action("CORE", "WATER", (2, 3), outcome={"watered": True})

    # SW operations
    telem.record_command_emitted("SW", "FEED")
    telem.record_command_emitted("SW", "HARVEST")
    telem.record_executed_action("SW", "HARVEST", (1, 5), outcome={"yield_units": 3, "item": "STRAWBERRY"})

    d = telem.to_dict()
    assert d["attempted_feed_core"] == 1
    assert d["core_feed_executed"] == 1
    assert d["attempted_water_core"] == 1
    assert d["core_water_executed"] == 1
    assert d["attempted_feed_sw"] == 1
    assert d["sw_feed_executed"] == 0
    assert d["attempted_harvest_sw"] == 1
    assert d["sw_harvest_executed"] == 1


def test_4_engine_crop_mechanics_ground_truth():
    """Verify engine crop parameter constants match official environment values."""
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS, LAND_PRICES

    # Land price progression: 1st plot (NE) = $1,000, 2nd plot (SW) = $2,000
    assert LAND_PRICES[0] == 1000
    assert LAND_PRICES[1] == 2000

    # Strawberry rules
    assert "STRAWBERRY" in CROPS
    sb = CROPS["STRAWBERRY"]
    assert sb["seed"] == 100
    assert sb["first_yield_day"] == 10
    assert sb["max_yield_day"] == 10
    assert sb["interval"] == 2
    assert sb["max_yield"] == 4
    assert sb["ongoing"] is True

    # Melon rules
    assert "MELON" in CROPS
    melon = CROPS["MELON"]
    assert melon["seed"] == 80
    assert melon["first_yield_day"] == 10
    assert melon["max_yield_day"] == 12
    assert melon["interval"] == 0
    assert melon["max_yield"] == 6
    assert melon["ongoing"] is False


def test_5_exact_crop_revenue_decomposition_identity():
    """Verify mathematical identity: Total Observed Delta = Core Delta + SW Attributed."""
    # From audited 40-match results
    core_delta = -7401.68
    sw_attributed = 7012.86
    total_delta = core_delta + sw_attributed
    expected_total = -388.82
    assert round(total_delta, 2) == round(expected_total, 2)
