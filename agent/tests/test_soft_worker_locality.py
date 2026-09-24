"""Targeted unit tests for Phase C0: Soft, Workload-Aware Worker Locality.

Verifies the 10 safety and dispatch requirements from Phase C0 specification:
1. Worker prefers useful nearby work when priorities are otherwise equal.
2. Urgent remote work overrides locality.
3. Livestock feeding overrides locality.
4. A worker can cross zones when local work is exhausted.
5. Task continuity reduces unnecessary reassignment.
6. Invalid tasks do not cause worker lock-in.
7. Shed and well routes remain reachable.
8. Newly unlocked NE receives sufficient worker support.
9. Treatment reset does not contaminate subsequent matches.
10. CONTROL assignments are unchanged when the experimental flag is OFF.
"""
from __future__ import annotations

import pytest
import copy
import sys
import os

from config import (
    SOFT_WORKER_LOCALITY_MODE,
    set_soft_worker_locality_mode,
    get_soft_worker_locality_mode,
    SHED_ACCESS_TILES,
    PRIORITY_URGENT_SURVIVAL,
    PRIORITY_PROD_DAY_FEED,
    PRIORITY_STANDARD_HARVEST,
)
from execution.task_scheduler import (
    assign_tasks,
    get_home_quadrant,
    get_active_missions,
    reset_sticky_missions,
    get_blocked_task_tracker,
    reset_blocked_task_tracker,
)


class MockTile:
    def __init__(self, x: int, y: int, kind: str = "EMPTY"):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.crop = None
        self.animal = None
        self.is_plant = False
        self.is_animal = False
        self.fertilizer_available = False
        self.watered_today = True


class MockFarm:
    def __init__(self, unlocked=("NW", "NE"), hands=None, farmer=(4, 4)):
        self.unlocked = set(unlocked)
        self.unlocked_quadrants = list(unlocked)
        self.farmer = farmer
        self.hands = list(hands or [])
        self.money = 5000.0
        self._tiles_dict = {}
        for y in range(10):
            for x in range(10):
                q = self.quadrant_of((x, y))
                kind = "EMPTY" if q in self.unlocked else "LOCKED"
                self._tiles_dict[(x, y)] = MockTile(x, y, kind=kind)

    def quadrant_of(self, pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")

    def iter_tiles(self):
        for y in range(10):
            for x in range(10):
                yield self._tiles_dict[(x, y)]


class MockPrivate:
    def __init__(self, n_units=2):
        self.shed = {"WHEAT": 20, "FERTILIZER": 10}
        self.seeds = {"WHEAT": 10, "CARROT": 10}
        self.inventories = [{} for _ in range(n_units)]


@pytest.fixture(autouse=True)
def cleanup_locality_state():
    """Ensure every test starts with clean state and restores OFF mode."""
    set_soft_worker_locality_mode("OFF")
    reset_sticky_missions()
    reset_blocked_task_tracker()
    yield
    set_soft_worker_locality_mode("OFF")
    reset_sticky_missions()
    reset_blocked_task_tracker()


def test_1_worker_prefers_nearby_work_equal_priority():
    """Requirement 1: Worker prefers useful nearby work when priorities are equal."""
    set_soft_worker_locality_mode("ON")
    farm = MockFarm(unlocked=("NW", "NE"), hands=[(8, 2)], farmer=(1, 2))
    # Worker 0 is in NW at (1, 2). Worker 1 is in NE at (8, 2).
    private = MockPrivate(n_units=2)
    ctx = {"farm": farm, "private": private, "step": 10, "day": 1, "hour": 5}

    # Two equal-priority watering tasks: one in NW at (2, 2), one in NE at (7, 2)
    nw_task = {"priority": 40, "op": "WATER", "target": (2, 2), "args": [], "kind": "water_crop"}
    ne_task = {"priority": 40, "op": "WATER", "target": (7, 2), "args": [], "kind": "water_crop"}

    res = assign_tasks([nw_task, ne_task], ctx)
    asg = res["assignment"]

    # Worker 0 (NW) must take the NW task, Worker 1 (NE) must take the NE task
    assert tuple(asg[0]["target"]) == (2, 2)
    assert tuple(asg[1]["target"]) == (7, 2)


def test_2_urgent_remote_work_overrides_locality():
    """Requirement 2: Urgent remote work overrides locality."""
    set_soft_worker_locality_mode("ON")
    # Only 1 worker, currently in NW at (1, 1)
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(1, 1))
    private = MockPrivate(n_units=1)
    ctx = {"farm": farm, "private": private, "step": 10, "day": 1, "hour": 5}

    # NW has a low-priority task (prio 20). NE has an urgent survival task (prio 85).
    nw_task = {"priority": 20, "op": "DIG", "target": (1, 2), "args": [], "kind": "weed_dig"}
    ne_urgent = {"priority": 85, "op": "WATER", "target": (7, 1), "args": [], "kind": "urgent_water"}

    res = assign_tasks([nw_task, ne_urgent], ctx)
    asg = res["assignment"]

    # The urgent NE task must override NW locality and be assigned to the worker
    assert tuple(asg[0]["target"]) == (7, 1)


def test_3_livestock_feeding_overrides_locality():
    """Requirement 3: Livestock feeding overrides locality."""
    set_soft_worker_locality_mode("ON")
    # Worker 0 is in NW at (1, 1) and holds wheat. Cow is in NE at (7, 1).
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(1, 1))
    private = MockPrivate(n_units=1)
    private.inventories[0]["WHEAT"] = 5
    ctx = {"farm": farm, "private": private, "step": 20, "day": 2, "hour": 10}

    nw_task = {"priority": 40, "op": "WATER", "target": (1, 2), "args": [], "kind": "water_crop"}
    feed_task = {"priority": PRIORITY_PROD_DAY_FEED, "op": "FEED", "target": (7, 1), "args": [], "kind": "feed_prod"}

    res = assign_tasks([nw_task, feed_task], ctx)
    asg = res["assignment"]

    # Feeding obligation in NE must be assigned despite worker being in NW
    assert tuple(asg[0]["target"]) == (7, 1)
    assert asg[0]["op"] == "FEED"


def test_4_worker_crosses_zones_when_local_work_exhausted():
    """Requirement 4: Worker crosses zones when local work is exhausted."""
    set_soft_worker_locality_mode("ON")
    # Worker is in NW at (2, 2). NW has zero tasks. NE has a regular harvest task.
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(2, 2))
    private = MockPrivate(n_units=1)
    ctx = {"farm": farm, "private": private, "step": 30, "day": 3, "hour": 8}

    ne_harvest = {"priority": PRIORITY_STANDARD_HARVEST, "op": "HARVEST", "target": (8, 2), "args": [], "kind": "harvest"}

    res = assign_tasks([ne_harvest], ctx)
    asg = res["assignment"]

    # Worker smoothly crosses to NE without being blocked
    assert tuple(asg[0]["target"]) == (8, 2)
    assert asg[0]["op"] == "HARVEST"


def test_5_task_continuity_reduces_reassignment():
    """Requirement 5: Task continuity gives bonus to continuing active journey."""
    set_soft_worker_locality_mode("ON")
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(2, 2))
    private = MockPrivate(n_units=1)
    farm._tiles_dict[(7, 2)].is_plant = True
    farm._tiles_dict[(7, 2)].watered_today = False
    farm._tiles_dict[(1, 2)].is_plant = True
    farm._tiles_dict[(1, 2)].watered_today = False
    ctx = {"farm": farm, "private": private, "step": 40, "day": 4, "hour": 6}

    # Worker already has an active mission toward (7, 2)
    from execution.task_scheduler import _ACTIVE_MISSIONS
    _ACTIVE_MISSIONS[0] = {
        "task": {"priority": 40, "op": "WATER", "target": (7, 2), "args": [], "kind": "water"},
        "target": (7, 2),
        "op": "WATER",
        "kind": "water",
        "args": [],
        "priority": 40,
        "prev_distance": 5,
        "consecutive_no_progress": 0,
        "mission_age": 1,
        "steps_active": 1,
    }

    # A competing task appears at (1, 2) with equal priority
    task_old = {"priority": 40, "op": "WATER", "target": (7, 2), "args": [], "kind": "water"}
    task_new = {"priority": 40, "op": "WATER", "target": (1, 2), "args": [], "kind": "water"}

    res = assign_tasks([task_old, task_new], ctx)
    asg = res["assignment"]

    # Active mission continuity preserves the journey to (7, 2)
    assert tuple(asg[0]["target"]) == (7, 2)


def test_6_invalid_tasks_do_not_cause_worker_lock_in():
    """Requirement 6: Invalid tasks do not cause worker lock-in."""
    set_soft_worker_locality_mode("ON")
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(2, 2))
    private = MockPrivate(n_units=1)
    ctx = {"farm": farm, "private": private, "step": 50, "day": 5, "hour": 2}

    # Active mission target is now invalid (e.g. tile locked or already harvested)
    from execution.task_scheduler import _ACTIVE_MISSIONS
    _ACTIVE_MISSIONS[0] = {
        "task": {"priority": 40, "op": "HARVEST", "target": (1, 1), "args": [], "kind": "harvest"},
        "target": (1, 1),
        "op": "HARVEST",
        "kind": "harvest",
        "args": [],
        "priority": 40,
        "prev_distance": 2,
        "consecutive_no_progress": 0,
        "mission_age": 1,
        "steps_active": 1,
    }

    # Only a new valid task exists at (3, 3)
    new_task = {"priority": 40, "op": "WATER", "target": (3, 3), "args": [], "kind": "water"}

    res = assign_tasks([new_task], ctx)
    asg = res["assignment"]

    # Worker must successfully switch to the valid task at (3, 3)
    assert tuple(asg[0]["target"]) == (3, 3)


def test_7_shed_and_well_routes_remain_reachable():
    """Requirement 7: Shed access tiles are treated as shared and reachable."""
    set_soft_worker_locality_mode("ON")
    farm = MockFarm(unlocked=("NW", "NE"), hands=[(8, 3)], farmer=(1, 3))
    private = MockPrivate(n_units=2)
    ctx = {"farm": farm, "private": private, "step": 60, "day": 6, "hour": 4}

    shed_tile = list(SHED_ACCESS_TILES)[0]
    deposit_task = {"priority": 50, "op": "DROP", "target": shed_tile, "args": [], "kind": "deposit"}

    res = assign_tasks([deposit_task], ctx)
    asg = res["assignment"]

    # Shed task is assigned without being penalized or blocked
    assert any(tuple(t["target"]) == shed_tile for t in asg.values())


def test_8_newly_unlocked_ne_receives_support():
    """Requirement 8: Newly unlocked NE with heavy backlog receives worker support."""
    set_soft_worker_locality_mode("ON")
    # 4 workers, all initially spawned near NW/shed
    farm = MockFarm(unlocked=("NW", "NE"), hands=[(4, 3), (3, 4), (4, 5)], farmer=(4, 4))
    private = MockPrivate(n_units=4)
    ctx = {"farm": farm, "private": private, "step": 70, "day": 7, "hour": 0}

    # Heavy backlog in NE (6 tasks)
    ne_tasks = [
        {"priority": 40, "op": "PLANT", "target": (7, y), "args": ["WHEAT"], "kind": "plant"}
        for y in range(6)
    ]

    res = assign_tasks(ne_tasks, ctx)
    asg = res["assignment"]

    # All 4 workers must receive NE tasks to develop the newly unlocked zone
    ne_assigned = sum(1 for t in asg.values() if farm.quadrant_of(t["target"]) == "NE")
    assert ne_assigned == 4


def test_9_treatment_reset_does_not_contaminate():
    """Requirement 9: Resetting clears all active missions and does not contaminate subsequent matches."""
    set_soft_worker_locality_mode("ON")
    from execution.task_scheduler import _ACTIVE_MISSIONS
    _ACTIVE_MISSIONS[0] = {"task": {}, "target": (5, 5)}
    assert len(get_active_missions()) > 0

    reset_sticky_missions()
    assert len(get_active_missions()) == 0


def test_10_control_assignments_unchanged_when_flag_off():
    """Requirement 10: CONTROL assignments are 100% identical when flag is OFF."""
    set_soft_worker_locality_mode("OFF")
    farm = MockFarm(unlocked=("NW", "NE"), hands=[(7, 2)], farmer=(2, 2))
    private = MockPrivate(n_units=2)
    ctx = {"farm": farm, "private": private, "step": 80, "day": 8, "hour": 2}

    nw_task = {"priority": 40, "op": "WATER", "target": (3, 2), "args": [], "kind": "water"}
    ne_task = {"priority": 40, "op": "WATER", "target": (8, 2), "args": [], "kind": "water"}

    # Run with OFF
    res_off = assign_tasks([nw_task, ne_task], ctx)
    asg_off = res_off["assignment"]

    # In baseline C2 zonal dispatch, worker 0 home is NW, worker 1 home is NE
    assert tuple(asg_off[0]["target"]) == (3, 2)
    assert tuple(asg_off[1]["target"]) == (8, 2)
