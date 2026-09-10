"""Unit tests for sticky multi-turn task ownership in task_scheduler."""
import pytest
from execution.task_scheduler import (
    assign_tasks,
    get_active_missions,
    reset_sticky_missions,
    reset_daily_log,
    PRIORITY_URGENT_SURVIVAL,
)


class MockTile:
    def __init__(self, x, y, kind="PLANT", is_plant=True, is_animal=False, crop="WHEAT", watered_today=False):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_plant = is_plant
        self.is_animal = is_animal
        self.crop = crop
        self.watered_today = watered_today
        self.consecutive_unwatered = 0
        self.fed_today = False
        self.yield_units = 0
        self.fertilized_until_day = -1


class MockFarm:
    def __init__(self, unlocked=("NW", "NE"), hands=(), farmer=(0, 0)):
        self.unlocked = set(unlocked)
        self.farmer = farmer
        self.hands = list(hands)
        self.money = 5000.0
        self._tiles = {}
        for r in range(16):
            for c in range(16):
                q = self.quadrant_of((r, c))
                kind = "EMPTY" if q in self.unlocked else "LOCKED"
                self._tiles[(r, c)] = MockTile(r, c, kind=kind, is_plant=False)

    def set_tile(self, pos, tile):
        self._tiles[pos] = tile

    def tile_at(self, pos):
        return self._tiles.get(pos)

    def quadrant_of(self, pos):
        r, c = pos
        if r < 8 and c < 8:
            return "NW"
        elif r < 8 and c >= 8:
            return "NE"
        elif r >= 8 and c < 8:
            return "SW"
        return "SE"

    def iter_tiles(self):
        return list(self._tiles.values())


class MockPrivate:
    def __init__(self):
        self.seeds = {}
        self.shed = {}
        self.inventories = [{} for _ in range(15)]


def setup_function():
    reset_sticky_missions()
    reset_daily_log()


def test_sticky_mission_retains_worker_on_route():
    """Worker moving toward distant target keeps mission on next turn despite closer lower-priority task."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(0, 0))
    # Target plant at (0, 6) needing water
    plant_tile = MockTile(0, 6, kind="PLANT", is_plant=True, watered_today=False)
    farm.set_tile((0, 6), plant_tile)
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 1}

    # Turn 1: Farmer at (0, 0) assigned to WATER (0, 6)
    tasks_turn1 = [
        {"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []},
    ]
    res1 = assign_tasks(tasks_turn1, ctx)
    assert res1["assignment"][0]["target"] == (0, 6)
    missions = get_active_missions()
    assert 0 in missions
    assert missions[0]["target"] == (0, 6)

    # Turn 2: Farmer moved to (0, 1). A new weed task appears at (0, 2) (closer!).
    farm.farmer = (0, 1)
    weed_tile = MockTile(0, 2, kind="WEED", is_plant=False)
    farm.set_tile((0, 2), weed_tile)
    tasks_turn2 = [
        {"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []},
        {"priority": 25, "op": "DIG", "target": (0, 2), "kind": "dig", "args": []},
    ]
    res2 = assign_tasks(tasks_turn2, ctx)
    # Sticky mission must protect worker from diversion to (0, 2)
    assert res2["assignment"][0]["target"] == (0, 6)
    assert res2["assignment"][0]["op"] == "WATER"


def test_urgent_task_preempts_active_mission():
    """Emergency survival task preempts a worker currently on an active mission."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(0, 2))
    plant_tile = MockTile(0, 6, kind="PLANT", is_plant=True, watered_today=False)
    farm.set_tile((0, 6), plant_tile)
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 2}

    # Setup active mission to (0, 6)
    tasks_turn1 = [
        {"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []},
    ]
    assign_tasks(tasks_turn1, ctx)
    assert 0 in get_active_missions()

    # Turn 2: Emergency rescue task arrives
    urgent_task = {
        "priority": PRIORITY_URGENT_SURVIVAL + 10,
        "op": "WATER",
        "target": (0, 0),
        "kind": "water_emergency",
        "args": [],
    }
    res2 = assign_tasks([urgent_task, tasks_turn1[0]], ctx)
    # Worker 0 should be preempted by the emergency task
    assert res2["assignment"][0]["target"] == (0, 0)
    assert 0 not in get_active_missions()


def test_mission_released_when_target_completed():
    """When target tile is completed, mission is released."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(0, 5))
    plant_tile = MockTile(0, 6, kind="PLANT", is_plant=True, watered_today=False)
    farm.set_tile((0, 6), plant_tile)
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 3}

    assign_tasks([{"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []}], ctx)
    assert 0 in get_active_missions()

    # Now plant tile is watered, so build_tasks does not generate water task for (0, 6)
    plant_tile.watered_today = True
    assign_tasks([], ctx)
    # Mission released because task is no longer in tasks
    assert 0 not in get_active_missions()


def test_mission_staleness_no_progress_timeout():
    """Mission without progress for 4 consecutive turns is timed out and released."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(0, 0))
    plant_tile = MockTile(0, 7, kind="PLANT", is_plant=True, watered_today=False)
    farm.set_tile((0, 7), plant_tile)
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 0}

    task = [{"priority": 70, "op": "WATER", "target": (0, 7), "kind": "water", "args": []}]
    assign_tasks(task, ctx)
    assert 0 in get_active_missions()

    # Simulate 5 steps with farmer stationary (no progress toward (0, 7))
    for _ in range(5):
        assign_tasks(task, ctx)

    # After >= 4 steps of no progress, mission is released and re-dispatched cleanly
    missions = get_active_missions()
    assert missions[0]["consecutive_no_progress"] < 4


def test_sticky_mission_progress_does_not_timeout_on_long_journey():
    """Worker walking >10 steps while making continuous progress is NOT dropped."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"), hands=[], farmer=(0, 0))
    plant_tile = MockTile(12, 0, kind="PLANT", is_plant=True, watered_today=False)
    farm.set_tile((12, 0), plant_tile)
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 0}

    task = [{"priority": 70, "op": "WATER", "target": (12, 0), "kind": "water", "args": []}]
    assign_tasks(task, ctx)
    assert 0 in get_active_missions()

    # Move farmer 1 step closer each turn for 11 turns: (1, 0) -> (11, 0)
    for step in range(1, 12):
        farm.farmer = (step, 0)
        assign_tasks(task, ctx)
        missions = get_active_missions()
        assert 0 in missions
        assert missions[0]["steps_active"] == step
        assert missions[0]["consecutive_no_progress"] == 0


def test_livestock_delivery_remains_sticky_until_placed():
    """Animal delivery remains sticky until placed on empty tile."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"), hands=[], farmer=(0, 0))
    empty_target = MockTile(10, 0, kind="EMPTY", is_plant=False, is_animal=False)
    farm.set_tile((10, 0), empty_target)
    priv = MockPrivate()
    priv.inventories = [{"COW": 1}]
    ctx = {"farm": farm, "private": priv, "day": 8, "hour": 0}

    place_task = [{"priority": 85, "op": "PLACE", "target": (10, 0), "kind": "place_animal", "args": ["COW"]}]
    assign_tasks(place_task, ctx)
    assert 0 in get_active_missions()

    # Even if tasks list does not re-include the place_task (e.g. planner omission), worker holding COW keeps mission
    farm.farmer = (1, 0)
    assign_tasks([], ctx)
    missions = get_active_missions()
    assert 0 in missions
    assert missions[0]["op"] == "PLACE"
    assert missions[0]["target"] == (10, 0)
