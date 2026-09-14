"""Unit tests for Persistent Worker Home Zones with Hysteresis.

Tests cover:
1. Exact experiment-arm matching (ArmA, ArmB, ArmB-P, ArmC, ArmD) in set_sw_experiment_arm().
2. Intra-day SW capacity preservation during task lulls when SW has active crops.
3. Intra-day worker home role stability (workers retain home across turns).
4. Temporary cross-zone spillover executes without modifying worker persistent home.
5. Tier 1 emergency survival dispatch bypasses home assignment without rewriting persistent home.
6. Diagonal NE <-> SW home reassignments are strictly blocked.
7. Episode reset via reset_daily_log() clears locality state.
8. Feature flag isolation: baseline behavior is preserved when PERSISTENT_WORKER_LOCALITY_ENABLED is False.
"""
import pytest
from unittest.mock import MagicMock
import config
from config import (
    set_sw_experiment_arm,
    get_sw_experiment_settings,
    set_persistent_worker_locality,
    set_dynamic_zonal_allocation,
    PERSISTENT_WORKER_LOCALITY_ENABLED,
    PORT_SW,
    PRIORITY_URGENT_SURVIVAL,
)
from execution.task_scheduler import (
    compute_workload_aware_home_quadrants,
    assign_tasks,
    get_worker_home_state,
    get_zone_home_capacity,
    get_locality_telemetry,
    reset_worker_locality,
    reset_daily_log,
)


class MockTile:
    def __init__(self, x, y, kind="EMPTY", is_plant=False, is_animal=False, crop=None):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_plant = is_plant
        self.is_animal = is_animal
        self.crop = crop
        self.watered_today = False
        self.consecutive_unwatered = 0
        self.fed_today = False
        self.yield_units = 0


class MockFarm:
    def __init__(self, unlocked=("NW", "NE", "SW"), hands=(), farmer=(4, 4)):
        self.unlocked = set(unlocked)
        self.farmer = farmer
        self.hands = list(hands)
        self.money = 5000.0
        self._tiles = {}
        for r in range(10):
            for c in range(10):
                q = self.quadrant_of((r, c))
                kind = "EMPTY" if q in self.unlocked else "LOCKED"
                self._tiles[(r, c)] = MockTile(r, c, kind=kind)

    def set_tile(self, pos, tile):
        self._tiles[pos] = tile

    def tile_at(self, pos):
        return self._tiles.get(pos)

    def quadrant_of(self, pos):
        r, c = pos
        if r < 5 and c < 5:
            return "NW"
        elif r < 5 and c >= 5:
            return "NE"
        elif r >= 5 and c < 5:
            return "SW"
        return "SE"

    def iter_tiles(self):
        return list(self._tiles.values())


class MockPrivate:
    def __init__(self):
        self.seeds = {}
        self.shed = {}
        self.inventories = [{} for _ in range(15)]


@pytest.fixture(autouse=True)
def cleanup():
    reset_daily_log()
    reset_worker_locality()
    config.set_sw_experiment_arm("ArmA")
    config.set_quadrant_hard_block({4})
    yield
    reset_daily_log()
    reset_worker_locality()
    config.set_sw_experiment_arm("ArmA")
    config.set_quadrant_hard_block({4})


def test_exact_arm_matching():
    """Verify exact normalized equality in set_sw_experiment_arm()."""
    set_sw_experiment_arm("ArmB-P")
    settings_bp = get_sw_experiment_settings()
    assert settings_bp["persistent_worker_locality"] is True
    assert settings_bp["strategic_sw_ownership"] is True
    assert settings_bp["activation_mode"] == "discrete"

    set_sw_experiment_arm("ArmB")
    settings_b = get_sw_experiment_settings()
    assert settings_b["persistent_worker_locality"] is False
    assert settings_b["strategic_sw_ownership"] is True
    assert settings_b["activation_mode"] == "discrete"

    set_sw_experiment_arm("ArmA")
    settings_a = get_sw_experiment_settings()
    assert settings_a["persistent_worker_locality"] is False
    assert settings_a["strategic_sw_ownership"] is False

    set_sw_experiment_arm("ArmC")
    settings_c = get_sw_experiment_settings()
    assert settings_c["persistent_worker_locality"] is False
    assert settings_c["activation_mode"] == "progressive"


def test_intraday_sw_capacity_preservation():
    """When SW has active planted crops, SW capacity does not collapse to 0 on taskless hours."""
    set_sw_experiment_arm("ArmB-P")
    farm = MockFarm(unlocked=["NW", "NE", "SW"])
    for r in range(5, 10):
        farm.set_tile((r, 2), MockTile(r, 2, kind="PLANT", is_plant=True, crop="STRAWBERRY"))

    n_units = 10
    pos_by_idx = {i: (4, 4) if i < 8 else (7, 2) for i in range(n_units)}

    tasks_turn0 = [
        {"op": "WATER", "target": (2, 2), "priority": 75} for _ in range(24)
    ] + [
        {"op": "WATER", "target": (2, 7), "priority": 75} for _ in range(24)
    ] + [
        {"op": "WATER", "target": (7, 2), "priority": 75} for _ in range(12)
    ]

    ctx_h0 = {"farm": farm, "day": 5, "hour": 0, "step": 120}
    home_h0 = compute_workload_aware_home_quadrants(tasks_turn0, farm, n_units, pos_by_idx, ctx=ctx_h0)
    sw_count_h0 = sum(1 for q in home_h0.values() if q == "SW")
    assert sw_count_h0 >= 1, f"Expected at least 1 SW worker at hour 0, got {sw_count_h0}"

    zone_cap_h0 = get_zone_home_capacity()
    assert zone_cap_h0.get("SW", 0) >= 1

    tasks_turn1 = [
        {"op": "DIG", "target": (2, 2), "priority": 40} for _ in range(10)
    ]
    ctx_h3 = {"farm": farm, "day": 5, "hour": 3, "step": 123}
    home_h3 = compute_workload_aware_home_quadrants(tasks_turn1, farm, n_units, pos_by_idx, ctx=ctx_h3)
    sw_count_h3 = sum(1 for q in home_h3.values() if q == "SW")

    assert sw_count_h3 >= 1, f"Expected SW capacity to be preserved across task lull, but got {sw_count_h3}"


def test_baseline_collapses_without_persistent_locality():
    """In Arm B (without persistent locality), 0 tasks in SW causes SW capacity to immediately collapse to 0."""
    set_sw_experiment_arm("ArmB")
    farm = MockFarm(unlocked=["NW", "NE", "SW"])
    for r in range(5, 10):
        farm.set_tile((r, 2), MockTile(r, 2, kind="PLANT", is_plant=True, crop="STRAWBERRY"))

    n_units = 10
    pos_by_idx = {i: (4, 4) for i in range(n_units)}
    tasks = [{"op": "DIG", "target": (2, 2), "priority": 40} for _ in range(10)]
    ctx = {"farm": farm, "day": 5, "hour": 3, "step": 123}

    home_quads = compute_workload_aware_home_quadrants(tasks, farm, n_units, pos_by_idx, ctx=ctx)
    sw_count = sum(1 for q in home_quads.values() if q == "SW")
    assert sw_count == 0, f"Expected baseline Arm B to collapse SW to 0 when SW has 0 tasks, got {sw_count}"


def test_temporary_spillover_preserves_persistent_home():
    """A worker assigned to SW who takes a discretionary NW task keeps SW as its persistent home."""
    set_sw_experiment_arm("ArmB-P")
    farm = MockFarm(unlocked=["NW", "NE", "SW"], hands=[(7, 2)], farmer=(4, 4))
    farm.set_tile((7, 2), MockTile(7, 2, kind="PLANT", is_plant=True, crop="STRAWBERRY"))
    private = MockPrivate()

    ctx = {"farm": farm, "private": private, "day": 5, "hour": 2, "step": 122}

    tasks_h0 = [
        {"op": "WATER", "target": (2, 2), "priority": 75},
        {"op": "WATER", "target": (7, 2), "priority": 75},
    ]
    res_h0 = assign_tasks(tasks_h0, ctx)
    worker_state = get_worker_home_state()
    assert worker_state.get(1) == "SW", f"Unit 1 should have persistent home SW, got {worker_state.get(1)}"

    tasks_h2 = [
        {"op": "DIG", "target": (4, 4), "priority": 30},
    ]
    res_h2 = assign_tasks(tasks_h2, ctx)

    worker_state_after = get_worker_home_state()
    assert worker_state_after.get(1) == "SW", "Temporary spillover must NOT modify persistent home quadrant!"


def test_tier1_emergency_bypasses_and_preserves_home():
    """Tier 1 emergency survival dispatch executes globally without altering persistent home."""
    set_sw_experiment_arm("ArmB-P")
    farm = MockFarm(unlocked=["NW", "NE", "SW"], hands=[(7, 2)], farmer=(4, 4))
    farm.set_tile((7, 2), MockTile(7, 2, kind="PLANT", is_plant=True, crop="STRAWBERRY"))
    private = MockPrivate()

    ctx = {"farm": farm, "private": private, "day": 5, "hour": 0, "step": 120}

    assign_tasks([{"op": "WATER", "target": (7, 2), "priority": 75}], ctx)
    assert get_worker_home_state().get(1) == "SW"

    emergency_task = {
        "priority": PRIORITY_URGENT_SURVIVAL,
        "op": "WATER",
        "target": (1, 1),
        "kind": "water_survival",
    }
    farm.hands = [(1, 2)]
    res_emerg = assign_tasks([emergency_task], ctx)

    assert res_emerg["assignment"][1]["op"] == "WATER"
    assert res_emerg["assignment"][1]["target"] == (1, 1)

    assert get_worker_home_state().get(1) == "SW"


def test_diagonal_sw_ne_switches_blocked():
    """Direct diagonal assignment (SW <-> NE) has 1000 penalty and is prohibited."""
    set_sw_experiment_arm("ArmB-P")
    farm = MockFarm(unlocked=["NW", "NE", "SW"])
    n_units = 4
    pos_by_idx = {
        0: (4, 4),
        1: (4, 4),
        2: (7, 2),
        3: (2, 7),
    }
    tasks = [
        {"op": "WATER", "target": (2, 2), "priority": 75},
        {"op": "WATER", "target": (2, 7), "priority": 75},
        {"op": "WATER", "target": (7, 2), "priority": 75},
    ]
    ctx = {"farm": farm, "day": 10, "hour": 0, "step": 240}
    home_quads = compute_workload_aware_home_quadrants(tasks, farm, n_units, pos_by_idx, ctx=ctx)

    assert home_quads[2] != "NE", "SW unit 2 should never be assigned to NE diagonally"
    assert home_quads[3] != "SW", "NE unit 3 should never be assigned to SW diagonally"


def test_episode_reset_cleans_locality_state():
    """reset_daily_log() resets all locality state and metrics for episode isolation."""
    set_sw_experiment_arm("ArmB-P")
    farm = MockFarm(unlocked=["NW", "NE", "SW"])
    ctx = {"farm": farm, "day": 5, "hour": 0, "step": 120}
    compute_workload_aware_home_quadrants(
        [{"op": "WATER", "target": (7, 2), "priority": 75}], farm, 2, {0: (4, 4), 1: (7, 2)}, ctx=ctx
    )
    assert len(get_worker_home_state()) > 0

    reset_daily_log()

    assert get_worker_home_state() == {}
    assert get_zone_home_capacity() == {"NW": 1, "NE": 0, "SW": 0}
    telem = get_locality_telemetry()
    assert telem["daily_log"] == {}
    assert telem["raw_records"] == []
