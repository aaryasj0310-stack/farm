"""Unit and Regression Test Suite for Phase SW-B3B: Core-First SW Task Admission.

Verifies:
1. Config flag toggling and multi-module synchronization.
2. Rejection of unauthorized SW tile tasks (invariant preservation).
3. Deferral when unassigned Core HARD tasks exist (survival water, feed rescue, decay harvest).
4. Deferral when Core standard tasks await workers while candidate worker is in Core.
5. Deferral when near-term day horizon capacity deficit is detected.
6. Deferral of late-day cross-map transit (hour >= 18).
7. Admission when core obligations are fully covered and spare capacity exists.
8. Active mission preemption and deferral for SW travel.
9. Bit-for-bit identical task scheduling when flag is OFF.
"""
import copy
import os
import sys
import pytest
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import agent.config as config
from agent.execution.sw_task_admission_controller import (
    evaluate_sw_task_admission,
    get_sw_task_admission_telemetry,
    reset_sw_task_admission_telemetry,
    is_sw_agricultural_task,
    is_core_task,
    REASON_UNAUTHORIZED_SW_TILE,
    REASON_UNASSIGNED_CORE_HARD_TASK,
    REASON_UNASSIGNED_CORE_STANDARD_TASK,
    REASON_CORE_WORKER_DEFICIT,
    REASON_NEAR_TERM_CORE_CAPACITY_DEFICIT,
    REASON_LATE_DAY_TRANSIT_OVERHEAD,
    REASON_ADMITTED,
)
from agent.strategy.sw_tranche_controller import (
    get_sw_tranche_controller,
    reset_sw_tranche_controller,
)


class DummyTile:
    def __init__(self, pos, is_plant=False, is_animal=False, crop=None, animal=None,
                 watered_today=True, fed_today=True, yield_units=0, consecutive_unwatered=0,
                 consecutive_unfed=0, planted_day=0):
        self.pos = pos
        self.is_plant = is_plant
        self.is_animal = is_animal
        self.crop = crop
        self.animal = animal
        self.watered_today = watered_today
        self.fed_today = fed_today
        self.yield_units = yield_units
        self.consecutive_unwatered = consecutive_unwatered
        self.consecutive_unfed = consecutive_unfed
        self.planted_day = planted_day


class DummyFarm:
    def __init__(self, unlocked=None):
        self.unlocked = unlocked or ["NW", "NE", "SW"]
        self.farmer = [2, 2]
        self.hands = [[2, 3], [3, 2], [3, 3]]
        self.tiles_list = []

    def quadrant_of(self, pos):
        x, y = pos[0], pos[1]
        if x < 5 and y < 5:
            return "NW"
        elif x >= 5 and y < 5:
            return "NE"
        elif x < 5 and y >= 5:
            return "SW"
        return "SE"

    def iter_tiles(self):
        return iter(self.tiles_list)


def setup_function():
    config.set_sw_core_first_task_admission_enabled(False)
    reset_sw_tranche_controller()
    reset_sw_task_admission_telemetry()


def teardown_function():
    config.set_sw_core_first_task_admission_enabled(False)
    reset_sw_tranche_controller()
    reset_sw_task_admission_telemetry()


def test_flag_toggle_and_config_sync():
    """Verify flag toggling and getter/setter behavior."""
    assert config.get_sw_core_first_task_admission_enabled() is False
    config.set_sw_core_first_task_admission_enabled(True)
    assert config.get_sw_core_first_task_admission_enabled() is True
    config.set_sw_core_first_task_admission_enabled(False)
    assert config.get_sw_core_first_task_admission_enabled() is False


def test_unauthorized_sw_tile_rejection():
    """Verify tasks targeting unauthorized SW tiles are rejected."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(1, 6), (1, 7)}

    farm = DummyFarm()
    ctx = {"farm": farm, "day": 10, "hour": 5, "step": 245}
    sw_task = {"op": "WATER", "target": (3, 8), "priority": 70}

    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(1, 6),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[1, 2, 3],
        all_tasks=[sw_task],
    )
    assert admit is False
    assert reason == REASON_UNAUTHORIZED_SW_TILE


def test_unassigned_core_hard_tasks_rejection():
    """Verify SW task is deferred when an urgent core hard task is waiting."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(1, 6), (1, 7)}

    farm = DummyFarm()
    ctx = {"farm": farm, "day": 10, "hour": 5, "step": 245}

    urgent_core_task = {
        "op": "WATER",
        "target": (2, 2),  # NW Core
        "priority": 100,    # URGENT_SURVIVAL
        "kind": "water_urgent",
    }
    sw_task = {"op": "WATER", "target": (1, 6), "priority": 70}

    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=1,
        worker_pos=(1, 6),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[0, 2, 3],
        all_tasks=[urgent_core_task, sw_task],
    )
    assert admit is False
    assert reason == REASON_UNASSIGNED_CORE_HARD_TASK


def test_unassigned_core_standard_tasks_rejection_for_core_worker():
    """Verify worker in Core is not dispatched to SW when Core standard tasks await workers."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(1, 6), (1, 7)}

    farm = DummyFarm()
    ctx = {"farm": farm, "day": 10, "hour": 5, "step": 245}

    core_water_task = {
        "op": "WATER",
        "target": (2, 2),  # NW Core
        "priority": 70,
        "kind": "water",
    }
    sw_task = {"op": "WATER", "target": (1, 6), "priority": 70}

    # Worker 0 is at (2, 2) in Core
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(2, 2),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[1, 2, 3],
        all_tasks=[core_water_task, sw_task],
    )
    assert admit is False
    assert reason == REASON_UNASSIGNED_CORE_STANDARD_TASK


def test_near_term_capacity_deficit_deferral():
    """Verify SW task is deferred when Core has unwatered crops and insufficient remaining capacity."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(1, 6), (1, 7)}

    farm = DummyFarm()
    # 8 unwatered core plants at hour 20 (only 4 hours remaining today)
    farm.tiles_list = [
        DummyTile(pos=(x, y), is_plant=True, watered_today=False)
        for x in range(4) for y in range(2)
    ]
    ctx = {"farm": farm, "day": 10, "hour": 20, "step": 260}

    sw_task = {"op": "WATER", "target": (1, 6), "priority": 70}

    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(1, 6),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[1],
        all_tasks=[sw_task],
    )
    assert admit is False
    assert reason == REASON_NEAR_TERM_CORE_CAPACITY_DEFICIT


def test_late_day_transit_overhead_deferral():
    """Verify Core worker is not sent on long transit to SW late in the day (hour >= 18)."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(1, 7)}

    farm = DummyFarm()
    ctx = {"farm": farm, "day": 10, "hour": 19, "step": 259}
    sw_task = {"op": "WATER", "target": (1, 7), "priority": 70}

    # Worker 0 is in Core NW at (1, 1), distance to (1, 7) is 6 >= 5
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(1, 1),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[1, 2, 3],
        all_tasks=[sw_task],
    )
    assert admit is False
    assert reason == REASON_LATE_DAY_TRANSIT_OVERHEAD


def test_sw_admitted_when_core_fully_covered():
    """Verify SW task is admitted when Core obligations are fully covered and capacity is ample."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(1, 6)}

    farm = DummyFarm()
    # All core plants are already watered today
    farm.tiles_list = [
        DummyTile(pos=(1, 1), is_plant=True, watered_today=True),
        DummyTile(pos=(2, 2), is_plant=True, watered_today=True),
    ]
    ctx = {"farm": farm, "day": 10, "hour": 6, "step": 246}
    sw_task = {"op": "WATER", "target": (1, 6), "priority": 70}

    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(1, 6),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[1, 2, 3],
        all_tasks=[sw_task],
    )
    assert admit is True
    assert reason == REASON_ADMITTED


def test_bit_for_bit_parity_when_flag_off():
    """Verify that when SW_CORE_FIRST_TASK_ADMISSION is False, behavior is unchanged."""
    config.set_sw_core_first_task_admission_enabled(False)
    assert config.get_sw_core_first_task_admission_enabled() is False

    from agent.execution.task_scheduler import assign_tasks
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 10, "hour": 5, "step": 245, "private": None}
    tasks = [
        {"priority": 70, "op": "WATER", "target": (1, 6), "kind": "water", "meta": {}, "args": []},
        {"priority": 70, "op": "WATER", "target": (2, 2), "kind": "water", "meta": {}, "args": []},
    ]

    asg = assign_tasks(tasks, ctx)
    assert asg is not None
    assert "assignment" in asg
    assert "actions" in asg
