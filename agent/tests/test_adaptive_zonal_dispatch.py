"""Unit tests for Stage 8B Phase 1E: C2 Adaptive Zonal Dispatch.

Tests A through L verify:
- Test A: Home-zone preference
- Test B: Local saturation / spillover
- Test C: Poor distant opportunity rejection
- Test D: Urgent task override
- Test E: Reservation safety and mutual exclusion
- Test F: Determinism across invocations
- Test G: Worker population and hiring unchanged
- Test H: C4 livestock investment cap compatibility
- Test I: C5 maturity-window harvesting compatibility
- Test J: Routing preservation (shortest-path, longer-axis-first)
- Test K: SW squad utilization and Rule W1/W2 anchoring
- Test L: No global-nearest regression (prevents stealing other zone tasks)
"""

import pytest
from config import (
    PORT_SW,
    SW_PASTURE_TILES,
    SW_SOIL_TILES,
    C2_MAX_SPILLOVER_DIST,
    C2_SPILLOVER_PRIORITY_FLOOR,
    DAY_TO_HANDS,
    get_target_hands,
)
from execution.task_scheduler import assign_tasks, get_home_quadrant
from execution.pathfinding import bfs_first_step, path_length
from strategy.animal_planner import get_animal_targets
from strategy.macro_planner import _crop_allowed_today


class MockTile:
    def __init__(self, x, y, kind="EMPTY"):
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
    def __init__(self, unlocked, hands=None, farmer=(4, 4)):
        self.unlocked = set(unlocked)
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
        if x < 5 and y < 5:
            return "NW"
        elif x >= 5 and y < 5:
            return "NE"
        elif x < 5 and y >= 5:
            return "SW"
        return "SE"

    def iter_tiles(self):
        return list(self._tiles_dict.values())


class MockPrivate:
    def __init__(self, seeds=None):
        self.seeds = dict(seeds or {})
        self.shed = {}
        self.inventories = [{} for _ in range(15)]


def test_c2_test_a_home_zone_preference():
    """When useful local work exists, worker remains in its home zone."""
    farm = MockFarm(["NW", "NE"], hands=[(7, 2)], farmer=(2, 2))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 80, "op": "HARVEST", "target": (1, 1), "kind": "harvest", "args": []},
        {"priority": 80, "op": "HARVEST", "target": (8, 1), "kind": "harvest", "args": []},
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    assert asg[0]["target"] == (1, 1)
    assert asg[1]["target"] == (8, 1)


def test_c2_test_b_local_saturation_spillover():
    """When home zone has no tasks and nearby zone has tasks, controlled spillover occurs."""
    farm = MockFarm(["NW", "NE"], hands=[(6, 2)], farmer=(4, 2))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 80, "op": "HARVEST", "target": (6, 1), "kind": "harvest", "args": []},
        {"priority": 75, "op": "HARVEST", "target": (7, 2), "kind": "harvest", "args": []},
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    assert 0 in asg
    assert 1 in asg
    targets = {asg[0]["target"], asg[1]["target"]}
    assert targets == {(6, 1), (7, 2)}


def test_c2_test_c_poor_distant_opportunity():
    """A distant low-value task does not automatically trigger cross-zone movement."""
    farm = MockFarm(["NW", "NE"], hands=[], farmer=(0, 0))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": C2_SPILLOVER_PRIORITY_FLOOR - 5, "op": "DIG", "target": (9, 4), "kind": "dig", "args": []}
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Farmer should NOT be assigned this low-priority spillover task in main dispatch
    assert 0 not in asg or asg[0].get("kind") != "dig"


def test_c2_test_d_urgent_task_override():
    """Urgent work (priority >= 100) overrides normal zoning restrictions."""
    farm = MockFarm(["NW", "NE"], hands=[(9, 4)], farmer=(4, 2))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 120, "op": "HARVEST", "target": (5, 2), "kind": "decay_harvest", "args": []}
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    assert asg[0]["target"] == (5, 2)


def test_c2_test_e_reservation_safety():
    """A task cannot be assigned to multiple units."""
    farm = MockFarm(["NW", "NE"], hands=[(3, 3), (2, 2)], farmer=(1, 1))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 80, "op": "HARVEST", "target": (2, 1), "kind": "harvest", "args": []}
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    harvest_units = [u for u, t in asg.items() if t.get("target") == (2, 1)]
    assert len(harvest_units) == 1


def test_c2_test_f_determinism():
    """Identical state produces identical task assignments across invocations."""
    hands = [(7, 2), (1, 3), (8, 4)]
    farm1 = MockFarm(["NW", "NE"], hands=hands, farmer=(2, 2))
    farm2 = MockFarm(["NW", "NE"], hands=hands, farmer=(2, 2))
    ctx1 = {"farm": farm1, "private": MockPrivate(), "day": 10, "hour": 0}
    ctx2 = {"farm": farm2, "private": MockPrivate(), "day": 10, "hour": 0}

    tasks1 = [
        {"priority": 80, "op": "HARVEST", "target": (1, 1), "kind": "harvest", "args": []},
        {"priority": 80, "op": "HARVEST", "target": (8, 1), "kind": "harvest", "args": []},
        {"priority": 70, "op": "WATER", "target": (2, 3), "kind": "water", "args": []},
    ]
    tasks2 = [dict(t) for t in tasks1]

    res1 = assign_tasks(tasks1, ctx1)
    res2 = assign_tasks(tasks2, ctx2)

    assert set(res1["assignment"].keys()) == set(res2["assignment"].keys())
    for u in res1["assignment"]:
        assert res1["assignment"][u]["target"] == res2["assignment"][u]["target"]
        assert res1["assignment"][u]["op"] == res2["assignment"][u]["op"]


def test_c2_test_g_worker_population_unchanged():
    """C2 does NOT modify hiring schedule, wages, or worker population."""
    assert DAY_TO_HANDS == {0: 4, 6: 8, 9: 8, 10: 10, 11: 12, 30: 0}
    assert get_target_hands(0) == 4
    assert get_target_hands(5) == 4
    assert get_target_hands(6) == 8
    assert get_target_hands(9) == 8
    assert get_target_hands(10) == 10
    assert get_target_hands(15) == 12
    assert get_target_hands(29) == 12
    assert get_target_hands(30) == 0


def test_c2_test_h_c4_compatibility():
    """C2 does NOT alter C4 Late-Game Livestock Investment Cap."""
    res_10 = get_animal_targets(10, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=9)
    assert res_10['SHEEP'] > 0 or res_10['COW'] > 0

    res_12 = get_animal_targets(12, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=10)
    assert res_12['COW'] == 0
    assert res_12['SHEEP'] == 0


def test_c2_test_i_c5_compatibility():
    """C2 does NOT alter C5 maturity-window harvesting decisions."""
    assert _crop_allowed_today("CARROT", 25) is True
    assert _crop_allowed_today("CARROT", 27) is True
    assert _crop_allowed_today("CARROT", 28) is False
    assert _crop_allowed_today("WHEAT", 26) is False


def test_c2_test_j_routing_preservation():
    """C2 preserves shortest-path routing and path length calculation."""
    step = bfs_first_step((0, 0), (3, 5))
    assert step in ("SOUTH", "EAST")
    assert path_length((0, 0), (3, 5)) == 8


def test_c2_test_k_sw_utilization():
    """C2 preserves Rule W1 SW squad partitioning and Rule W2 PORT_SW anchoring."""
    # Place SW hands inside SW at (1, 9) so they need to anchor to PORT_SW (4, 5)
    hands = [(4, 4)] * 4 + [(1, 9)] * 4
    farm = MockFarm(["NW", "NE", "SW"], hands=hands, farmer=(4, 4))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    assert get_home_quadrant(0, 9, ["NW", "NE", "SW"]) == "NW"
    assert get_home_quadrant(1, 9, ["NW", "NE", "SW"]) == "NW"
    assert get_home_quadrant(2, 9, ["NW", "NE", "SW"]) == "NE"
    assert get_home_quadrant(3, 9, ["NW", "NE", "SW"]) == "NE"
    assert get_home_quadrant(4, 9, ["NW", "NE", "SW"]) == "NE"
    assert get_home_quadrant(5, 9, ["NW", "NE", "SW"]) == "SW"
    assert get_home_quadrant(6, 9, ["NW", "NE", "SW"]) == "SW"
    assert get_home_quadrant(7, 9, ["NW", "NE", "SW"]) == "SW"
    assert get_home_quadrant(8, 9, ["NW", "NE", "SW"]) == "SW"

    res_idle = assign_tasks([], ctx)
    for u in (5, 6, 7, 8):
        assert res_idle["assignment"][u]["kind"] == "sw_anchor"
        assert res_idle["assignment"][u]["target"] == PORT_SW


def test_c2_test_l_no_global_nearest_regression():
    """Workers do not steal other zones' tasks merely due to raw Manhattan proximity."""
    farm = MockFarm(["NW", "NE"], hands=[(8, 2)], farmer=(4, 2))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 80, "op": "HARVEST", "target": (5, 2), "kind": "harvest", "args": []}
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    assert 1 in asg
    assert asg[1]["target"] == (5, 2)
    assert 0 not in asg or asg[0].get("target") != (5, 2)
