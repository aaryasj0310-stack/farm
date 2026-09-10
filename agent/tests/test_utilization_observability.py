"""Unit tests for separated utilization metrics, blocked diagnostics, and travel-aware capacity."""
import pytest
from execution.task_scheduler import (
    assign_tasks,
    get_daily_log,
    reset_daily_log,
    estimate_daily_load,
    get_sw_tile_breakdown,
    get_sw_season_summary,
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
        self.fed_today = False
        self.fertilizer_available = False
        self.cared_today = False
        self.placed_day = 0
        self.consecutive_unwatered = 0
        self.consecutive_unfed = 0
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
    def __init__(self, inventories=None, shed=None, seeds=None):
        self.seeds = seeds or {}
        self.shed = shed or {}
        self.inventories = inventories or [{} for _ in range(15)]


def setup_function():
    reset_daily_log()


def test_separated_utilization_metrics():
    """Verify distinct action_utilization, completion_rate, travel_share in _daily_log."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[(0, 1)], farmer=(0, 0))
    # Plant at (0, 0) (standing on target -> operation executed)
    farm.set_tile((0, 0), MockTile(0, 0, kind="PLANT", is_plant=True))
    # Plant at (0, 5) (not standing on target -> movement executed)
    farm.set_tile((0, 5), MockTile(0, 5, kind="PLANT", is_plant=True))
    
    ctx = {"farm": farm, "private": MockPrivate(), "day": 2, "hour": 23, "step": 23}
    tasks = [
        {"priority": 90, "op": "WATER", "target": (0, 0), "kind": "water", "args": []},
        {"priority": 80, "op": "WATER", "target": (0, 5), "kind": "water", "args": []},
    ]
    assign_tasks(tasks, ctx)

    log = get_daily_log()
    assert 2 in log
    entry = log[2]
    assert "action_utilization" in entry
    assert "completion_rate" in entry
    assert "travel_share" in entry
    assert "urgent_completion_rate" in entry
    assert "quadrant_completion_rates" in entry

    # 2 units available, both took actions -> utilization is 100%
    assert entry["action_utilization"] == 1.0
    # 1 movement action (travel_share = 0.5) and 1 non-movement completion (completion_rate = 0.5)
    assert entry["travel_share"] == 0.5
    assert entry["completion_rate"] == 0.5
    assert entry["quadrant_completion_rates"]["NW"] > 0


def test_blocked_task_diagnostics_inventory_and_carrier():
    """Verify tasks blocked by inventory or carrier are recorded without being hidden by fallback."""
    farm = MockFarm(unlocked=("NW",), hands=[], farmer=(0, 0))
    # Add a weed tile so fallback DIG would execute
    farm.set_tile((0, 1), MockTile(0, 1, kind="WEED"))
    
    # Private with empty inventory (no wheat, no animals)
    private = MockPrivate(inventories=[{}])
    ctx = {"farm": farm, "private": private, "day": 4, "hour": 5}

    # Tasks that cannot be executed due to inventory / carrier
    tasks = [
        {"priority": 85, "op": "FEED", "target": (2, 2), "kind": "feed_prod", "args": []},
        {"priority": 85, "op": "PLACE", "target": (3, 3), "kind": "place_animal", "args": ["COW"]},
    ]
    res = assign_tasks(tasks, ctx)
    diag = res["blocked_diagnostics"]
    
    assert diag["blocked_due_inventory"] >= 1  # FEED blocked due to no wheat
    assert diag["blocked_due_no_carrier"] >= 1  # PLACE COW blocked due to no COW carrier
    assert diag["blocked_task_turns"] >= 2
    assert diag["max_blocked_duration"] >= 1
    assert diag["urgent_blocked_turns"] >= 1
    # Fallback DIG was still executed for the idle unit
    assert any(t.get("op") == "DIG" for t in res["assignment"].values())

    # Turn 2: Same blocked tasks persist -> duration increments
    ctx["hour"] = 6
    ctx["step"] = 6
    res2 = assign_tasks(tasks, ctx)
    diag2 = res2["blocked_diagnostics"]
    assert diag2["max_blocked_duration"] == 2
    assert diag2["blocked_task_turns"] >= 4

    # Turn 3: Task completes/disappears -> auto-cleared from tracker
    ctx["hour"] = 7
    ctx["step"] = 7
    res3 = assign_tasks([], ctx)
    diag3 = res3["blocked_diagnostics"]
    assert diag3["blocked_task_turns"] == 0
    assert diag3["max_blocked_duration"] == 0


def test_travel_aware_estimate_daily_load():
    """Verify spatial dispersion and SW distance penalties increase load for multi-quadrant farm."""
    # 1. Single quadrant farm (NW only)
    farm_nw = MockFarm(unlocked=("NW",), farmer=(4, 4))
    for i in range(5):
        farm_nw.set_tile((i, i), MockTile(i, i, kind="PLANT", is_plant=True))
    ctx_nw = {"farm": farm_nw, "private": MockPrivate(), "day": 12}
    load_nw = estimate_daily_load(ctx_nw)

    # 2. Multi-quadrant farm with SW tiles
    farm_sw = MockFarm(unlocked=("NW", "NE", "SW"), farmer=(4, 4))
    for i in range(5):
        farm_sw.set_tile((i, i), MockTile(i, i, kind="PLANT", is_plant=True))
    # Add 5 tiles in SW
    for i in range(5):
        farm_sw.set_tile((8 + i, i), MockTile(8 + i, i, kind="PLANT", is_plant=True))
    ctx_sw = {"farm": farm_sw, "private": MockPrivate(), "day": 12}
    load_sw = estimate_daily_load(ctx_sw)

    # SW farm must have substantially higher estimated load due to SW transit + cross-quadrant dispersion
    assert load_sw > load_nw * 2


def test_sw_cluster_load_lower_than_scattered_cross_quadrant():
    """Verify clustered 20-tile SW farm has lower estimated travel burden than 20 scattered cross-quadrant tasks."""
    # 20 clustered SW tiles
    farm_sw20 = MockFarm(unlocked=("NW", "SW"), farmer=(4, 4))
    for r in range(8, 13):
        for c in range(4):
            farm_sw20.set_tile((r, c), MockTile(r, c, kind="PLANT", is_plant=True))
    ctx_sw20 = {"farm": farm_sw20, "private": MockPrivate(), "day": 15}
    load_sw20 = estimate_daily_load(ctx_sw20)

    # 20 scattered tiles across all 4 quadrants (NW, NE, SW, SE)
    farm_scattered = MockFarm(unlocked=("NW", "NE", "SW", "SE"), farmer=(4, 4))
    # 5 in NW, 5 in NE, 5 in SW, 5 in SE
    for i in range(5):
        farm_scattered.set_tile((i, i), MockTile(i, i, kind="PLANT", is_plant=True))
        farm_scattered.set_tile((i, 8 + i), MockTile(i, 8 + i, kind="PLANT", is_plant=True))
        farm_scattered.set_tile((8 + i, i), MockTile(8 + i, i, kind="PLANT", is_plant=True))
        farm_scattered.set_tile((8 + i, 8 + i), MockTile(8 + i, 8 + i, kind="PLANT", is_plant=True))
    ctx_scattered = {"farm": farm_scattered, "private": MockPrivate(), "day": 15}
    load_scattered = estimate_daily_load(ctx_scattered)

    # Clustered SW farm travel overhead should be lower than scattered 4-quadrant farm
    assert load_sw20 < load_scattered


def test_zero_sw_tasks_completion_rate_is_none():
    """Verify that 0 attempted SW tasks yields None completion rate (never vacuous 1.0 or 100%)."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[(0, 1)], farmer=(0, 0))
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 23, "step": 23}
    # Only NW tasks
    tasks = [
        {"priority": 80, "op": "WATER", "target": (0, 0), "kind": "water", "args": []},
    ]
    assign_tasks(tasks, ctx)

    log = get_daily_log()
    assert 5 in log
    entry = log[5]
    # Denominator is 0 for SW -> must be None, NOT 1.0!
    assert entry["quadrant_completion_rates"]["SW"] is None
    assert entry["sw_telemetry"]["sw_completion_rate"] is None
    assert entry["sw_telemetry"]["sw_tasks_assigned"] == 0

    season = get_sw_season_summary()
    assert season["sw_completion_rate"] is None
    assert season["sw_tasks_assigned"] == 0


def test_sw_tile_breakdown_unlocked_invariant():
    """Verify that when SW is unlocked: active + weeds + empty == 25 and no double-counting."""
    raw_tiles = [[{"kind": "LOCKED"} for _ in range(10)] for _ in range(10)]
    # In SW (rows 5-9, cols 0-4): populate a mix
    # 5 crops, 3 animals, 2 empty pastures, 4 weeds, 11 empty ground => 25 total
    crops_added = 0
    animals_added = 0
    pastures_added = 0
    weeds_added = 0
    empty_added = 0

    for r in range(5, 10):
        for c in range(0, 5):
            idx = (r - 5) * 5 + c
            if idx < 5:
                raw_tiles[r][c] = {"kind": "PLANT", "crop": "STRAWBERRY" if idx < 2 else "WHEAT"}
                crops_added += 1
            elif idx < 8:
                raw_tiles[r][c] = {"kind": "ANIMAL", "animal": "COW"}
                animals_added += 1
            elif idx < 10:
                raw_tiles[r][c] = {"kind": "PASTURE"}
                pastures_added += 1
            elif idx < 14:
                raw_tiles[r][c] = {"kind": "WEED"}
                weeds_added += 1
            else:
                raw_tiles[r][c] = {"kind": "EMPTY"}
                empty_added += 1

    farm_dict = {
        "unlocked_quadrants": ["NW", "NE", "SW"],
        "tiles": raw_tiles,
    }

    breakdown = get_sw_tile_breakdown(farm_dict)
    assert breakdown["sw_owned"] is True
    assert breakdown["crops"] == 5
    assert breakdown["crops_strawberry"] == 2
    assert breakdown["crops_other"] == 3
    assert breakdown["animals"] == 3
    assert breakdown["structures"] == 2
    assert breakdown["weeds"] == 4
    assert breakdown["empty"] == 11

    # Invariant: active = crops + animals + structures (no double counting)
    assert breakdown["active"] == 5 + 3 + 2 == 10
    # Invariant: active + weeds + empty == 25
    assert breakdown["active"] + breakdown["weeds"] + breakdown["empty"] == 25
    assert breakdown["utilization"] == round(10 / 25.0, 4)


def test_sw_task_counters_monotonicity():
    """Verify sw_tasks_completed <= sw_tasks_assigned <= sw_tasks_created."""
    farm = MockFarm(unlocked=("NW", "SW"), hands=[(8, 1)], farmer=(8, 0))
    ctx = {"farm": farm, "private": MockPrivate(), "day": 10, "hour": 23, "step": 23}

    # 3 created tasks in SW, 2 units available:
    # Farmer at (8,0) will execute op on (8,0)
    # Hand at (8,1) will move towards (8,4)
    # Task at (8,3) will remain unassigned
    tasks = [
        {"priority": 90, "op": "WATER", "target": (8, 0), "kind": "water", "args": []},
        {"priority": 85, "op": "WATER", "target": (8, 4), "kind": "water", "args": []},
        {"priority": 70, "op": "WATER", "target": (8, 3), "kind": "water", "args": []},
    ]
    for t in tasks:
        farm.set_tile(t["target"], MockTile(t["target"][0], t["target"][1], kind="PLANT", is_plant=True))

    assign_tasks(tasks, ctx)

    season = get_sw_season_summary()
    created = season["sw_tasks_created"]
    assigned = season["sw_tasks_assigned"]
    completed = season["sw_tasks_completed"]

    assert created == 3
    assert assigned == 2
    assert completed == 1
    assert completed <= assigned <= created
    assert season["sw_movement_actions"] == 1
    assert season["sw_operation_actions"] == 1
    assert season["sw_assignment_rate"] == round(2 / 3, 4)
    assert season["sw_completion_rate"] == round(1 / 2, 4)


def test_sw_locked_state_invariants():
    """Verify that when SW is locked, sw_owned is False, active=0, and utilization/empty are None."""
    farm = MockFarm(unlocked=("NW", "NE"), hands=[], farmer=(0, 0))
    breakdown = get_sw_tile_breakdown(farm)

    assert breakdown["sw_owned"] is False
    assert breakdown["active"] == 0
    assert breakdown["crops"] == 0
    assert breakdown["animals"] == 0
    assert breakdown["structures"] == 0
    assert breakdown["weeds"] == 0
    assert breakdown["empty"] is None
    assert breakdown["utilization"] is None


def test_sw_telemetry_resets_between_episodes():
    """Verify that calling reset_daily_log resets all daily logs and seasonal SW trackers."""
    farm = MockFarm(unlocked=("NW", "SW"), hands=[(8, 0)], farmer=(8, 0))
    farm.set_tile((8, 0), MockTile(8, 0, kind="PLANT", is_plant=True))
    ctx = {"farm": farm, "private": MockPrivate(), "day": 3, "hour": 23, "step": 23}
    tasks = [{"priority": 90, "op": "WATER", "target": (8, 0), "kind": "water", "args": []}]
    assign_tasks(tasks, ctx)

    assert len(get_daily_log()) > 0
    season_before = get_sw_season_summary()
    assert season_before["sw_tasks_assigned"] > 0

    # Reset
    reset_daily_log()

    assert len(get_daily_log()) == 0
    season_after = get_sw_season_summary()
    assert season_after["sw_owned"] is False
    assert season_after["first_sw_unlock_day"] is None
    assert season_after["first_sw_active_day"] is None
    assert season_after["sw_tasks_created"] == 0
    assert season_after["sw_tasks_assigned"] == 0
    assert season_after["sw_tasks_completed"] == 0
    assert season_after["sw_completion_rate"] is None

