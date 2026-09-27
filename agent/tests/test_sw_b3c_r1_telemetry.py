"""Unit and Telemetry Accounting Tests for Phase SW-B3C-R1.

Verifies:
1. Every proposed SW task receives an explicit terminal disposition (0 unassigned/orphaned tasks).
2. Core HARD obligations use stable identities with zero duplicate counts per entity/day.
3. Core HARD obligations strictly reconcile: due == completed + missed.
4. Separation of attempted commands, executed actions, and harvested product units.
5. Strict failure assertion if any proposed task lacks a valid recorded disposition.
"""
import copy
import os
import sys
import pytest
from typing import Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from agent.execution.sw_task_admission_controller import (
    SWTaskAdmissionTelemetry,
    get_sw_task_admission_telemetry,
    reset_sw_task_admission_telemetry,
    REASON_UNAUTHORIZED_SW_TILE,
    REASON_UNASSIGNED_CORE_HARD_TASK,
)


def setup_function():
    reset_sw_task_admission_telemetry()


def teardown_function():
    reset_sw_task_admission_telemetry()


def test_1_sw_task_lifecycle_all_proposals_have_explicit_disposition():
    """Verify that every proposed SW task receives an explicit recorded terminal disposition."""
    telem = get_sw_task_admission_telemetry()

    # Task 1: Proposed -> Gate Deferral
    t1_id = "SW_10_5_WATER_(1,5)_water"
    telem.record_sw_task_lifecycle_start(t1_id, 245, 10, 5, "WATER", (1, 5), "water", 50)
    telem.record_candidate_evaluation(False, REASON_UNASSIGNED_CORE_HARD_TASK)
    telem.record_sw_task_disposition(t1_id, "REJECTED_BY_GATE", REASON_UNASSIGNED_CORE_HARD_TASK)

    # Task 2: Proposed -> Admitted & Selected
    t2_id = "SW_10_5_HARVEST_(2,6)_harvest"
    telem.record_sw_task_lifecycle_start(t2_id, 245, 10, 5, "HARVEST", (2, 6), "harvest", 80)
    telem.record_candidate_evaluation(True, "ADMITTED")
    telem.record_sw_task_disposition(t2_id, "SELECTED_AND_ASSIGNED")

    # Task 3: Proposed -> Eligible but Unselected by Scheduler (lost to Task 2)
    t3_id = "SW_10_5_WATER_(3,6)_water"
    telem.record_sw_task_lifecycle_start(t3_id, 245, 10, 5, "WATER", (3, 6), "water", 40)
    telem.record_candidate_evaluation(True, "ADMITTED")
    telem.record_sw_task_disposition(t3_id, "ELIGIBLE_UNSELECTED", "LOWER_BAND_SCORE")

    d = telem.to_dict()
    assert d["sw_tasks_proposed"] == 3
    assert d["sw_tasks_admitted"] == 1
    assert d["sw_tasks_deferred"] == 1
    assert d["sw_tasks_eligible_unselected"] == 1
    assert d["sw_tasks_unresolved"] == 0, f"Unresolved proposals found: {d['sw_tasks_unresolved']}"


def test_2_accounting_fails_when_proposed_tasks_lack_disposition():
    """Verify accounting detects and fails if any proposed task lacks a recorded disposition."""
    telem = get_sw_task_admission_telemetry()

    # Proposed but abandoned without recording disposition (the B3C gap)
    t_orphaned = "SW_12_8_WATER_(0,5)_water"
    telem.record_sw_task_lifecycle_start(t_orphaned, 296, 12, 8, "WATER", (0, 5), "water", 45)
    telem.record_candidate_evaluation(True, "ADMITTED")
    # Not assigned and not recorded as unselected

    d = telem.to_dict()
    assert d["sw_tasks_proposed"] == 1
    assert d["sw_tasks_unresolved"] == 1

    # Strict accounting validation rule
    with pytest.raises(AssertionError, match="Unresolved task proposals detected"):
        if d["sw_tasks_unresolved"] > 0:
            raise AssertionError(f"Unresolved task proposals detected: {d['sw_tasks_unresolved']}")


def test_3_core_hard_obligations_no_duplicate_registrations():
    """Verify stable obligation IDs prevent duplicate counting of ongoing needs."""
    telem = get_sw_task_admission_telemetry()

    # Need persists from Hour 8 to Hour 10 on Day 14
    for hr in [8, 9, 10]:
        added = telem.register_core_hard_obligation(
            task_id="CORE_WATER_2_3_D14",
            op="WATER",
            pos=(2, 3),
            entity="crop:STRAWBERRY",
            day=14,
            hour=hr,
            deadline_step=14 * 24 + 23,
        )
        if hr == 8:
            assert added is True
        else:
            assert added is False

    d = telem.to_dict()
    assert d["core_hard_tasks_due"] == 1, "Duplicate observation inflated core_hard_tasks_due"
    assert d["hard_tasks_by_op"]["WATER"]["due"] == 1


def test_4_core_hard_obligations_reconcile_exactly():
    """Verify that all registered HARD obligations reconcile: due == completed + missed."""
    telem = get_sw_task_admission_telemetry()

    # Obligation 1: Water completed before deadline
    telem.register_core_hard_obligation("CORE_WATER_1_2_D15", "WATER", (1, 2), "crop:MELON", 15, 6, 15 * 24 + 23)
    telem.record_hard_obligation_assigned("CORE_WATER_1_2_D15", 1)
    telem.record_hard_obligation_emitted("CORE_WATER_1_2_D15")
    # Executed on hour 8 (step 368)
    telem.record_hard_obligation_executed("WATER", (1, 2), 15 * 24 + 8)

    # Obligation 2: Animal feed missed at deadline
    telem.register_core_hard_obligation("CORE_FEED_6_4_D15", "FEED", (6, 4), "animal:COW", 15, 18, 15 * 24 + 23)
    # Deadline passes at step 16*24 = 384
    telem.reconcile_hard_deadlines(16 * 24)

    d = telem.to_dict()
    assert d["core_hard_tasks_due"] == 2
    assert d["core_hard_tasks_completed"] == 1
    assert d["missed_core_deadlines"] == 1
    assert d["core_hard_tasks_due"] == d["core_hard_tasks_completed"] + d["missed_core_deadlines"]


def test_5_separate_attempted_executed_and_harvested_units():
    """Verify attempted actions, executed actions, and harvested yield units are strictly distinguished."""
    telem = get_sw_task_admission_telemetry()

    # Worker emits 3 HARVEST commands in SW
    for _ in range(3):
        telem.record_command_emitted("SW", "HARVEST")

    # Engine executes 1 HARVEST on a Melon plant yielding 4 units
    telem.record_executed_action("SW", "HARVEST", (1, 5), outcome={"yield_units": 4, "item": "MELON"})

    d = telem.to_dict()
    assert d["attempted_harvest_sw"] == 3
    assert d["executed_harvest_sw"] == 1
    assert d["harvested_crop_units_sw"]["MELON"] == 4
    # Ensure product units (4) are strictly separated from executed actions (1) and attempted commands (3)
    assert d["harvested_crop_units_sw"]["MELON"] != d["executed_harvest_sw"]
    assert d["executed_harvest_sw"] != d["attempted_harvest_sw"]
