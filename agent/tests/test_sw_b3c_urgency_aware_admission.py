"""Unit and Regression Test Suite for Phase SW-B3C: Urgency-Aware SW Task Admission.

Verifies the 10 core requirements:
1. Core HARD task preempts SW work.
2. A routine unassigned core task does not automatically block SW admission.
3. A worker already in SW can complete an admitted productive task when core HARD obligations remain covered.
4. SW watering is allowed before a crop-survival deadline.
5. Mature SW crops can be harvested before decay.
6. Repeated routine core tasks cannot permanently starve all SW work.
7. Admitted SW missions retain continuity unless a legitimate higher-priority obligation arises.
8. No unauthorized SW tile is used.
9. No animal feeding emergency is displaced.
10. Disabling the new flag reproduces frozen Gate 2 scheduling (OFF parity).
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
    evaluate_active_sw_mission_continuation,
    get_sw_task_admission_telemetry,
    reset_sw_task_admission_telemetry,
    is_sw_agricultural_task,
    is_core_task,
    is_core_hard_task,
    REASON_UNAUTHORIZED_SW_TILE,
    REASON_UNASSIGNED_CORE_HARD_TASK,
    REASON_UNASSIGNED_CORE_STANDARD_TASK,
    REASON_CORE_WORKER_DEFICIT,
    REASON_NEAR_TERM_CORE_CAPACITY_DEFICIT,
    REASON_LATE_DAY_TRANSIT_OVERHEAD,
    REASON_INSUFFICIENT_HORIZON_FOR_COMMITMENT,
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
        self._tile_dict = {}

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

    def tile(self, pos):
        return self._tile_dict.get(tuple(pos))

    def add_tile(self, tile):
        self.tiles_list.append(tile)
        self._tile_dict[tuple(tile.pos)] = tile


def setup_function():
    config.set_sw_core_first_task_admission_enabled(False)
    config.set_sw_urgency_aware_admission_enabled(True)
    reset_sw_tranche_controller()
    reset_sw_task_admission_telemetry()


def teardown_function():
    config.set_sw_core_first_task_admission_enabled(False)
    config.set_sw_urgency_aware_admission_enabled(False)
    reset_sw_tranche_controller()
    reset_sw_task_admission_telemetry()


def test_1_core_hard_task_preempts_sw_work():
    """1. Core HARD task preempts SW work when Core workers are insufficient."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 12, "hour": 10}

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6), (1, 5), (1, 6)}

    sw_task = {"op": "WATER", "target": (0, 5), "priority": 75}
    # Unassigned Tier 0 HARD task in Core: urgent survival water (prio 100)
    all_tasks = [
        {"op": "WATER", "target": (2, 2), "priority": 100, "kind": "emergency_water"},
        sw_task,
    ]

    # Worker 0 in Core (2, 2)
    # free units: only worker 0 is available (free_core_workers = 0 for remaining)
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(2, 2),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[],
        all_tasks=all_tasks,
    )
    assert admit is False
    assert reason == REASON_UNASSIGNED_CORE_HARD_TASK


def test_2_routine_core_task_does_not_block_sw():
    """2. A routine unassigned core task does NOT automatically block SW admission."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 12, "hour": 8}

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6), (1, 5), (1, 6)}

    sw_task = {"op": "WATER", "target": (0, 5), "priority": 75}
    # Routine standard core tasks (e.g. routine carrot watering, prio 65)
    all_tasks = [
        {"op": "WATER", "target": (2, 2), "priority": 65, "kind": "routine_water"},
        {"op": "WATER", "target": (2, 3), "priority": 65, "kind": "routine_water"},
        sw_task,
    ]

    # Plenty of remaining hours (hour 8 -> 16 hours left), 3 workers in Core
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(3, 4),  # close to SW border
        task=sw_task,
        current_assignments={},
        remaining_free_units=[1, 2, 3],
        all_tasks=all_tasks,
    )
    assert admit is True
    assert reason == REASON_ADMITTED


def test_3_worker_in_sw_can_complete_admitted_task():
    """3. Worker already in SW can complete admitted productive task when core HARD covered."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 12, "hour": 11}

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6), (1, 5), (1, 6)}

    sw_task = {"op": "HARVEST", "target": (0, 6), "priority": 75}
    all_tasks = [sw_task]

    # Worker 3 is already at (0, 5) in SW
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=3,
        worker_pos=(0, 5),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[0, 1, 2],
        all_tasks=all_tasks,
    )
    assert admit is True
    assert reason == REASON_ADMITTED


def test_4_sw_watering_allowed_before_deadline():
    """4. SW watering is allowed before a crop-survival deadline."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 15, "hour": 10}

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6), (1, 5), (1, 6)}

    # SW strawberry tile needs water
    sw_water_task = {"op": "WATER", "target": (1, 5), "priority": 75}

    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=1,
        worker_pos=(2, 4),
        task=sw_water_task,
        current_assignments={},
        remaining_free_units=[0, 2, 3],
        all_tasks=[sw_water_task],
    )
    assert admit is True
    assert reason == REASON_ADMITTED


def test_5_mature_sw_crop_harvested_before_decay():
    """5. Mature SW crops can be harvested before decay."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 18, "hour": 9}

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6), (1, 5), (1, 6)}

    sw_harvest_task = {"op": "HARVEST", "target": (0, 5), "priority": 85, "kind": "sw_harvest"}

    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=2,
        worker_pos=(1, 5),
        task=sw_harvest_task,
        current_assignments={},
        remaining_free_units=[0, 1, 3],
        all_tasks=[sw_harvest_task],
    )
    assert admit is True
    assert reason == REASON_ADMITTED


def test_6_repeated_routine_tasks_cannot_starve_sw():
    """6. Repeated routine core tasks cannot permanently starve all SW work."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 14, "hour": 7}

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6), (1, 5), (1, 6)}

    # Routine core tasks are constantly present
    core_routine = [{"op": "WATER", "target": (6, 2), "priority": 60} for _ in range(5)]
    sw_task = {"op": "WATER", "target": (0, 5), "priority": 75}

    all_tasks = core_routine + [sw_task]

    # In B3B strict mode, this would be rejected with REASON_UNASSIGNED_CORE_STANDARD_TASK
    # In B3C Urgency-Aware mode, with 4 workers and 17 hours remaining, SW is admitted!
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=1,
        worker_pos=(3, 4),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[0, 2, 3],
        all_tasks=all_tasks,
    )
    assert admit is True
    assert reason == REASON_ADMITTED


def test_7_admitted_sw_mission_retains_continuity():
    """7. Admitted SW missions retain continuity unless legitimate higher-priority obligation arises."""
    farm = DummyFarm()
    sw_tile = DummyTile(pos=(0, 5), is_plant=True, watered_today=False)
    farm.add_tile(sw_tile)

    ctx = {"farm": farm, "day": 12, "hour": 10}
    mission = {
        "op": "WATER",
        "target": (0, 5),
        "task": {"op": "WATER", "target": (0, 5), "priority": 75},
    }

    # Case A: Routine core task appears while worker is walking to SW
    routine_tasks = [{"op": "WATER", "target": (6, 2), "priority": 60}]
    admit_cont, reason_cont = evaluate_active_sw_mission_continuation(
        ctx=ctx,
        worker_idx=1,
        worker_pos=(2, 4),  # on the way
        mission=mission,
        current_assignments={},
        remaining_free_units=[0, 2, 3],
        all_tasks=routine_tasks,
    )
    # Continuity must be PRESERVED! (Solving Defect 2.D)
    assert admit_cont is True
    assert reason_cont == REASON_ADMITTED

    # Case B: Severe Tier 0 survival emergency arises and Core has no free workers
    emergency_tasks = [{"op": "FEED", "target": (2, 2), "priority": 100, "kind": "feed_rescue"}]
    admit_em, reason_em = evaluate_active_sw_mission_continuation(
        ctx=ctx,
        worker_idx=1,
        worker_pos=(2, 4),
        mission=mission,
        current_assignments={},
        remaining_free_units=[],  # NO free workers in Core!
        all_tasks=emergency_tasks,
    )
    # Emergency preemption must trigger!
    assert admit_em is False
    assert reason_em == REASON_UNASSIGNED_CORE_HARD_TASK


def test_8_no_unauthorized_sw_tile_used():
    """8. No unauthorized SW tile is used (tranche invariant preserved)."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 12, "hour": 9}

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    # Tranche authorized only for (0, 5) and (0, 6)
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6)}

    # Task on unauthorized SW tile (4, 9)
    unauth_task = {"op": "WATER", "target": (4, 9), "priority": 75}
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(4, 4),
        task=unauth_task,
        current_assignments={},
        remaining_free_units=[1, 2, 3],
        all_tasks=[unauth_task],
    )
    assert admit is False
    assert reason == REASON_UNAUTHORIZED_SW_TILE


def test_9_no_animal_feeding_emergency_displaced():
    """9. No animal feeding emergency is displaced (late hour animal care protected)."""
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 16, "hour": 19}  # Late day: hour 19

    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.admitted_sw_tiles = {(0, 5), (0, 6)}

    sw_task = {"op": "WATER", "target": (0, 5), "priority": 75}
    # Unfed animal at hour 19 in Core
    all_tasks = [
        {"op": "FEED", "target": (2, 2), "priority": 85},
        sw_task,
    ]

    # Only 1 free worker available in Core -> reserved for animal feed!
    admit, reason = evaluate_sw_task_admission(
        ctx=ctx,
        worker_idx=0,
        worker_pos=(2, 2),
        task=sw_task,
        current_assignments={},
        remaining_free_units=[],
        all_tasks=all_tasks,
    )
    assert admit is False
    assert reason == REASON_UNASSIGNED_CORE_HARD_TASK


def test_10_disabling_flag_reproduces_frozen_gate2():
    """10. Disabling the new flag reproduces frozen Gate 2 scheduling (admission bypassed)."""
    config.set_sw_urgency_aware_admission_enabled(False)
    config.set_sw_core_first_task_admission_enabled(False)
    assert config.get_sw_urgency_aware_admission_enabled() is False
    assert config.get_sw_core_first_task_admission_enabled() is False

    from agent.execution.task_scheduler import assign_tasks
    farm = DummyFarm()
    ctx = {"farm": farm, "day": 12, "hour": 12, "step": 300, "private": None}
    tasks = [
        {"priority": 70, "op": "WATER", "target": (0, 5), "kind": "water", "meta": {}, "args": []},
        {"priority": 70, "op": "WATER", "target": (2, 2), "kind": "water", "meta": {}, "args": []},
    ]

    reset_sw_task_admission_telemetry()
    asg = assign_tasks(tasks, ctx)
    assert asg is not None
    assert "assignment" in asg
    telem = get_sw_task_admission_telemetry()
    # When both admission flags are disabled, admission controller is completely bypassed
    assert telem.sw_tasks_deferred == 0
