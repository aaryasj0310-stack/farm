"""
Phase SW-C2: P1 Mission Ownership & Executable Resource Chains Unit Tests
Tests stable obligation indexing, anti-duplicate pursuit, explicit preemption,
cross-worker transfers, feeding chain isolation, and core fallback protection.
"""

import pytest
from config import (
    set_sw_p1_mission_ownership_enabled,
    get_sw_p1_mission_ownership_enabled,
    PRIORITY_URGENT_SURVIVAL,
)
from execution.mission_ownership_tracker import (
    get_mission_ownership_tracker,
    reset_mission_ownership_tracker,
    compute_task_obligation_id,
    MissionStatus,
)
from execution.task_scheduler import (
    assign_tasks,
    build_tasks,
    reset_sticky_missions,
    reset_daily_log,
)


class MockTile:
    def __init__(self, x, y, kind="EMPTY", is_plant=False, is_animal=False, crop=None, animal=None):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_plant = is_plant
        self.is_animal = is_animal
        self.crop = crop
        self.animal = animal
        self.watered_today = False
        self.consecutive_unwatered = 0
        self.fed_today = False
        self.consecutive_unfed = 0
        self.yield_units = 0
        self.fertilized_until_day = -1
        self.fertilizer_available = False
        self.cared_today = False


class MockFarm:
    def __init__(self, unlocked=("NW", "NE", "SW"), hands=(), farmer=(0, 0)):
        self.unlocked = set(unlocked)
        self.farmer = farmer
        self.hands = list(hands)
        self.money = 5000.0
        self._tiles = {}
        for r in range(16):
            for c in range(16):
                q = self.quadrant_of((r, c))
                kind = "EMPTY" if q in self.unlocked else "LOCKED"
                self._tiles[(r, c)] = MockTile(r, c, kind=kind)

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
    def __init__(self, n_units=15):
        self.seeds = {}
        self.shed = {}
        self.inventories = [{} for _ in range(n_units)]


@pytest.fixture(autouse=True)
def setup_teardown():
    set_sw_p1_mission_ownership_enabled(True)
    reset_sticky_missions()
    reset_mission_ownership_tracker()
    reset_daily_log()
    yield
    set_sw_p1_mission_ownership_enabled(False)
    reset_sticky_missions()
    reset_mission_ownership_tracker()
    reset_daily_log()


def test_p1_stable_obligation_identity_across_ops_and_days():
    """Verify tasks at the same coordinate with different ops or days produce distinct stable IDs."""
    id_harvest_d0 = compute_task_obligation_id(day=0, op="HARVEST", target=(2, 2), kind="harvest")
    id_water_d0 = compute_task_obligation_id(day=0, op="WATER", target=(2, 2), kind="water")
    id_water_d1 = compute_task_obligation_id(day=1, op="WATER", target=(2, 2), kind="water")

    assert id_harvest_d0 != id_water_d0, "Different ops at same tile must have distinct IDs"
    assert id_water_d0 != id_water_d1, "Same op at same tile on different days must have distinct IDs"
    assert "D0" in id_harvest_d0
    assert "D1" in id_water_d1
    assert "HARVEST" in id_harvest_d0
    assert "WATER" in id_water_d0


def test_p1_unique_ownership_and_anti_duplicate_pursuit():
    """Verify that when Worker 0 is traveling to an obligation, Worker 1 does not duplicate pursuit."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[(1, 0)], farmer=(0, 0))
    plant_tile = MockTile(0, 6, kind="PLANT", is_plant=True, crop="WHEAT")
    farm.set_tile((0, 6), plant_tile)
    ctx = {"farm": farm, "private": MockPrivate(), "day": 1, "hour": 2, "step": 26}

    # Two duplicate tasks targeting the same watering obligation at (0, 6)
    tasks = [
        {"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []},
        {"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []},
        {"priority": 20, "op": "DIG", "target": (1, 2), "kind": "dig", "args": []},
    ]

    res = assign_tasks(tasks, ctx)
    # Farmer (0) at (0,0) claims (0, 6)
    assert res["assignment"][0]["target"] == (0, 6)
    # Hand (1) must NOT be assigned to duplicate pursuit of (0, 6)
    assert res["assignment"][1]["target"] != (0, 6)

    tracker = get_mission_ownership_tracker()
    telemetry = tracker.get_telemetry()
    assert telemetry["duplicate_pursuits_blocked"] >= 1


def test_p1_explicit_preemption_and_wasted_travel_accounting():
    """Verify that when an urgent task preempts a worker en route, wasted travel is tracked."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(0, 0))
    plant_tile = MockTile(0, 6, kind="PLANT", is_plant=True, crop="WHEAT")
    farm.set_tile((0, 6), plant_tile)
    ctx = {"farm": farm, "private": MockPrivate(), "day": 2, "hour": 1, "step": 49}

    # Step 49: Farmer starts mission toward (0, 6)
    tasks1 = [{"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []}]
    assign_tasks(tasks1, ctx)

    tracker = get_mission_ownership_tracker()
    obl_id = compute_task_obligation_id(2, "WATER", (0, 6), "water", [])
    m = tracker.get_mission_for_obligation(obl_id)
    assert m is not None
    assert m.worker_idx == 0

    # Step 50: Farmer moved closer to (0, 1), spends 1 travel step
    farm.farmer = (0, 1)
    ctx["step"] = 50
    ctx["hour"] = 2
    tasks2 = [{"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []}]
    assign_tasks(tasks2, ctx)
    assert m.travel_steps_spent == 1

    # Step 51: An emergency urgent survival task suddenly appears at (0, 0)
    # Cow in danger of escaping!
    cow_tile = MockTile(0, 0, kind="ANIMAL", is_animal=True, animal="COW")
    cow_tile.consecutive_unfed = 1
    farm.set_tile((0, 0), cow_tile)
    private = MockPrivate()
    private.inventories[0]["WHEAT"] = 2  # Farmer has wheat to feed
    ctx["private"] = private
    ctx["step"] = 51
    ctx["hour"] = 3

    urgent_tasks = [
        {"priority": PRIORITY_URGENT_SURVIVAL + 5, "op": "FEED", "target": (0, 0), "kind": "feed_rescue", "args": []},
        {"priority": 70, "op": "WATER", "target": (0, 6), "kind": "water", "args": []},
    ]

    res3 = assign_tasks(urgent_tasks, ctx)
    # Farmer must be preempted to handle urgent feed at (0, 0)
    assert res3["assignment"][0]["op"] == "FEED"
    assert res3["assignment"][0]["target"] == (0, 0)

    # Verify tracker recorded preemption and wasted travel
    telemetry = tracker.get_telemetry()
    assert telemetry["missions_preempted"] >= 1
    assert telemetry["wasted_travel_steps"] >= 1
    assert "PREEMPTED_BY_URGENT_SURVIVAL" in telemetry["preemptions_by_reason"]


def test_p1_explicit_cross_worker_transfer():
    """Verify explicit transfer between workers records history and releases old worker."""
    tracker = get_mission_ownership_tracker()
    obl_id = "OBL_TEST_TRANSFER"
    task = {"op": "WATER", "target": (4, 4), "priority": 75}

    # Worker 0 claims
    m = tracker.claim_or_continue_mission(worker_idx=0, obligation_id=obl_id, task=task, worker_pos=(0, 0), step=10)
    assert tracker.get_mission_for_worker(0) == m
    assert m.worker_idx == 0

    # Worker 0 travels 2 steps
    m.travel_steps_spent = 2

    # Worker 1 takes over mission
    m_transferred = tracker.transfer_mission(
        obligation_id=obl_id,
        old_worker=0,
        new_worker=1,
        reason="REASSIGNED_TO_FASTER_WORKER",
        step=12,
    )

    assert m_transferred.worker_idx == 1
    assert tracker.get_mission_for_worker(0) is None
    assert tracker.get_mission_for_worker(1) == m_transferred
    assert len(m_transferred.transfer_history) == 1
    assert m_transferred.transfer_history[0]["old_worker"] == 0
    assert m_transferred.transfer_history[0]["new_worker"] == 1
    assert m_transferred.transfer_history[0]["travel_steps_spent_by_old"] == 2


def test_p1_feeding_chain_distant_wheat_isolation():
    """Verify distant worker-held wheat in SW does NOT suppress necessary shed pickup for NW animals."""
    from types import SimpleNamespace
    farm = MockFarm(unlocked=("NW", "NE", "SW"), hands=[(14, 2)], farmer=(0, 0))
    # Hungry cow in NW at (2, 2)
    cow_tile = MockTile(2, 2, kind="ANIMAL", is_animal=True, animal="COW")
    cow_tile.consecutive_unfed = 1
    farm.set_tile((2, 2), cow_tile)

    private = MockPrivate()
    # Hand 1 is way down in SW at (14, 2) with 3 wheat
    private.inventories[1]["WHEAT"] = 3
    # Shed has 5 wheat
    private.shed["WHEAT"] = 5
    # Farmer has 0 wheat
    private.inventories[0]["WHEAT"] = 0

    ctx = {"farm": farm, "private": private, "day": 3, "hour": 2, "step": 74}
    macro = SimpleNamespace(
        plant_queue=[],
        build_queue=[],
        build_op="BUILD_PASTURE",
        place_queue=[],
        feeding_enabled=True,
        watering_enabled=True,
    )

    # Under P1: distant hand 1's wheat in SW should NOT suppress pickup_wheat task at shed
    tasks = build_tasks(ctx, macro)
    pickup_tasks = [t for t in tasks if t.get("kind") == "pickup_wheat"]
    assert len(pickup_tasks) > 0, "Distant worker wheat in SW must not suppress needed shed wheat pickup"
    assert any(t.get("op") == "PICKUP" and "WHEAT" in t.get("args", []) for t in pickup_tasks)


def test_p1_fallback_core_protection():
    """Verify idle core workers in NW are not dispatched to SW for low-value fallback."""
    farm = MockFarm(unlocked=("NW", "NE", "SW"), hands=[], farmer=(0, 0))
    # Weed in SW at (12, 2)
    weed_sw = MockTile(12, 2, kind="WEED")
    farm.set_tile((12, 2), weed_sw)

    # Empty task list for turn
    ctx = {"farm": farm, "private": MockPrivate(), "day": 4, "hour": 8, "step": 104}

    # Core farmer is at (0, 0). Fallback should NOT send farmer down to (12, 2) in SW
    res = assign_tasks([], ctx)
    assert 0 not in res["assignment"] or res["assignment"][0].get("target") != (12, 2), (
        "Core farmer should not be dispatched to SW for fallback weed digging"
    )
    tracker = get_mission_ownership_tracker()
    assert tracker.get_telemetry()["fallback_discretionary_blocked"] >= 1


def test_p1_midnight_rollover_cleanup():
    """Verify that at midnight rollover, active missions are safely cleared with wasted travel logged."""
    tracker = get_mission_ownership_tracker()
    m = tracker.claim_or_continue_mission(
        worker_idx=1,
        obligation_id="OBL_D5_WATER_(10,10)",
        task={"op": "WATER", "target": (10, 10), "priority": 60},
        worker_pos=(8, 8),
        step=140,
    )
    m.travel_steps_spent = 3

    # Midnight rollover into Day 6
    tracker.handle_midnight_rollover(new_day=6)

    assert tracker.get_mission_for_worker(1) is None
    assert m.status == MissionStatus.INVALIDATED
    assert m.wasted_travel_steps == 3
    telemetry = tracker.get_telemetry()
    assert telemetry["wasted_travel_steps"] >= 3
    assert telemetry["active_missions_count"] == 0
