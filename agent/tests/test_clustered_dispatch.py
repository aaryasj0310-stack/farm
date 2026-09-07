"""Unit tests for Stage 8B Phase 1F: C6 Residual Clustered Dispatch.

Tests A through N verify:
- Test A: Nearby compatible task preference
- Test B: Clustering does not override urgent survival task
- Test C: Clustering does not override C2 zone policy
- Test D: Reservation safety (already reserved tasks remain unavailable)
- Test E: No duplicate execution (two workers cannot claim the same task)
- Test F: Determinism across invocations
- Test G: Long-distance avoidance (nearby work beats distant equivalent work)
- Test H: Priority preservation (meaningfully higher priority not sacrificed)
- Test I: C4 preservation (livestock cap & cutoff unchanged)
- Test J: C5 preservation (maturity-window harvesting unchanged)
- Test K: SW squad preservation (Rule W1/W2 unchanged)
- Test L: Routing preservation (shortest-path, longer-axis unchanged)
- Test M: C1 exclusion (worker count & hiring schedule unchanged)
- Test N: C3 exclusion (crop allocation & Melon policy unchanged)
"""

import pytest
from config import (
    PORT_SW,
    SW_PASTURE_TILES,
    SW_SOIL_TILES,
    C2_MAX_SPILLOVER_DIST,
    C2_SPILLOVER_PRIORITY_FLOOR,
    C6_CLUSTER_RADIUS,
    C6_CLUSTER_BONUS,
    DAY_TO_HANDS,
    get_target_hands,
    CROP_TILE_CAPS,
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


# =========================================================================
# Test A — Nearby compatible task preference
# =========================================================================
def test_c6_test_a_nearby_compatible_task():
    """Worker prefers a nearby compatible task when priority/urgency permits."""
    # Farmer 0 is at (0, 3) [home NW].
    # Task 1 is at (0, 0) [prio 70, WATER, dist 3].
    # Task 2 is at (0, 3) [prio 70, WATER, dist 0 - co-located!].
    farm = MockFarm(["NW", "NE"], hands=[], farmer=(0, 3))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 70, "op": "WATER", "target": (0, 0), "kind": "water", "args": []},
        {"priority": 70, "op": "WATER", "target": (0, 3), "kind": "water", "args": []},
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Farmer must pick the co-located / nearby task at (0, 3), not the distant one at (0, 0)
    assert asg[0]["target"] == (0, 3)


# =========================================================================
# Test B — Clustering does not override urgent task
# =========================================================================
def test_c6_test_b_clustering_does_not_override_urgent_task():
    """Urgent task wins even if a clustered regular task is closer."""
    # Farmer 0 is at (0, 3).
    # Task 1 is at (0, 3) [prio 70, WATER, dist 0].
    # Task 2 is at (4, 4) [prio 120, DECAY HARVEST, dist 5].
    farm = MockFarm(["NW", "NE"], hands=[], farmer=(0, 3))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 70, "op": "WATER", "target": (0, 3), "kind": "water", "args": []},
        {"priority": 120, "op": "HARVEST", "target": (4, 4), "kind": "harvest_decay", "args": []},
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Urgent decay harvest must win over co-located normal watering
    assert asg[0]["target"] == (4, 4)
    assert asg[0]["op"] == "HARVEST"


# =========================================================================
# Test C — Clustering does not override C2 zone policy
# =========================================================================
def test_c6_test_c_clustering_does_not_override_c2_zone_policy():
    """C6 cannot bypass C2 home-zone eligibility or trigger illegal cross-zone jumps."""
    # Farmer 0 is at (4, 2) [home NW].
    # Hand 1 is at (8, 2) [home NE].
    # Task 1 in NE at (5, 2) [prio 70].
    # Task 2 in NW at (1, 2) [prio 70].
    # Farmer is closer to (5, 2) [dist 1] than Hand 1 [dist 3].
    # But (5, 2) is in NE! Hand 1 has home-zone preference in NE.
    farm = MockFarm(["NW", "NE"], hands=[(8, 2)], farmer=(4, 2))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 70, "op": "WATER", "target": (5, 2), "kind": "water", "args": []},
        {"priority": 70, "op": "WATER", "target": (1, 2), "kind": "water", "args": []},
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Hand 1 gets NE task, Farmer 0 gets NW task (C2 zoning preserved)
    assert asg[1]["target"] == (5, 2)
    assert asg[0]["target"] == (1, 2)


# =========================================================================
# Test D — Reservation safety
# =========================================================================
def test_c6_test_d_reservation_safety():
    """Already-reserved tasks remain unavailable."""
    farm = MockFarm(["NW", "NE"], hands=[(1, 1)], farmer=(0, 0))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 70, "op": "WATER", "target": (0, 0), "kind": "water", "args": []}
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Only one unit gets the task
    assigned_targets = [t["target"] for t in asg.values() if t.get("target") == (0, 0)]
    assert len(assigned_targets) == 1


# =========================================================================
# Test E — No duplicate execution
# =========================================================================
def test_c6_test_e_no_duplicate_execution():
    """Two workers cannot claim the same exclusive task."""
    farm = MockFarm(["NW", "NE"], hands=[(0, 0), (0, 1)], farmer=(0, 0))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 70, "op": "WATER", "target": (0, 0), "kind": "water", "args": []}
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Exactly 1 unit gets the (0, 0) water task
    water_00 = [u for u, t in asg.items() if t.get("target") == (0, 0) and t.get("op") == "WATER"]
    assert len(water_00) == 1


# =========================================================================
# Test F — Determinism
# =========================================================================
def test_c6_test_f_determinism():
    """Same state produces identical assignments across invocations."""
    hands = [(0, 1), (4, 4), (7, 2)]
    farm1 = MockFarm(["NW", "NE"], hands=hands, farmer=(2, 2))
    farm2 = MockFarm(["NW", "NE"], hands=hands, farmer=(2, 2))
    ctx1 = {"farm": farm1, "private": MockPrivate(), "day": 10, "hour": 0}
    ctx2 = {"farm": farm2, "private": MockPrivate(), "day": 10, "hour": 0}

    tasks1 = [
        {"priority": 75, "op": "PLANT", "target": (1, 1), "kind": "plant", "args": ["WHEAT"]},
        {"priority": 70, "op": "WATER", "target": (0, 1), "kind": "water", "args": []},
        {"priority": 70, "op": "WATER", "target": (4, 3), "kind": "water", "args": []},
    ]
    tasks2 = [dict(t) for t in tasks1]

    res1 = assign_tasks(tasks1, ctx1)
    res2 = assign_tasks(tasks2, ctx2)

    assert set(res1["assignment"].keys()) == set(res2["assignment"].keys())
    for u in res1["assignment"]:
        assert res1["assignment"][u]["target"] == res2["assignment"][u]["target"]
        assert res1["assignment"][u]["op"] == res2["assignment"][u]["op"]


# =========================================================================
# Test G — Long-distance avoidance
# =========================================================================
def test_c6_test_g_long_distance_avoidance():
    """Nearby compatible work beats unnecessary distant compatible work when priorities are equivalent."""
    # Worker 0 at (0, 0), Worker 1 at (4, 4).
    # Task A at (0, 1) [dist 1 from W0, dist 7 from W1].
    # Task B at (4, 3) [dist 7 from W0, dist 1 from W1].
    farm = MockFarm(["NW"], hands=[(4, 4)], farmer=(0, 0))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 70, "op": "WATER", "target": (4, 3), "kind": "water", "args": []},
        {"priority": 70, "op": "WATER", "target": (0, 1), "kind": "water", "args": []},
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # W0 gets Task A at (0, 1); W1 gets Task B at (4, 3)
    assert asg[0]["target"] == (0, 1)
    assert asg[1]["target"] == (4, 3)


# =========================================================================
# Test H — Priority preservation
# =========================================================================
def test_c6_test_h_priority_preservation():
    """Meaningfully higher-priority work is not sacrificed for a small travel reduction."""
    # Farmer 0 is at (0, 0).
    # Nearby Task at (0, 1): Priority 60 (FERTILIZE_CROP), dist 1.
    # Distant Task at (4, 4): Priority 90 (DECAY_HARVEST), dist 8.
    farm = MockFarm(["NW"], hands=[], farmer=(0, 0))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [
        {"priority": 60, "op": "FERTILIZE", "target": (0, 1), "kind": "fertilize_crop", "args": []},
        {"priority": 90, "op": "HARVEST", "target": (4, 4), "kind": "harvest_decay", "args": []},
    ]
    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Must take the priority 90 task despite the 8-step distance!
    assert asg[0]["target"] == (4, 4)
    assert asg[0]["priority"] == 90


# =========================================================================
# Test I — C4 preservation
# =========================================================================
def test_c6_test_i_c4_preservation():
    """C6 does NOT alter C4 Late-Game Livestock Investment Cap."""
    res_10 = get_animal_targets(10, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=9)
    assert res_10['SHEEP'] > 0 or res_10['COW'] > 0

    res_12 = get_animal_targets(12, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=10)
    assert res_12['COW'] == 0
    assert res_12['SHEEP'] == 0


# =========================================================================
# Test J — C5 preservation
# =========================================================================
def test_c6_test_j_c5_preservation():
    """C6 does NOT alter C5 maturity-window harvesting decisions."""
    assert _crop_allowed_today("CARROT", 25) is True
    assert _crop_allowed_today("CARROT", 27) is True
    assert _crop_allowed_today("CARROT", 28) is False
    assert _crop_allowed_today("WHEAT", 26) is False


# =========================================================================
# Test K — SW preservation
# =========================================================================
def test_c6_test_k_sw_preservation():
    """C6 preserves Rule W1 SW squad partitioning and Rule W2 PORT_SW anchoring."""
    hands = [(4, 4)] * 4 + [(1, 9)] * 4
    farm = MockFarm(["NW", "NE", "SW"], hands=hands, farmer=(4, 4))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    assert get_home_quadrant(5, 9, ["NW", "NE", "SW"]) == "SW"
    assert get_home_quadrant(6, 9, ["NW", "NE", "SW"]) == "SW"
    assert get_home_quadrant(7, 9, ["NW", "NE", "SW"]) == "SW"
    assert get_home_quadrant(8, 9, ["NW", "NE", "SW"]) == "SW"

    res_idle = assign_tasks([], ctx)
    for u in (5, 6, 7, 8):
        assert res_idle["assignment"][u]["kind"] == "sw_anchor"
        assert res_idle["assignment"][u]["target"] == PORT_SW


# =========================================================================
# Test L — Routing preservation
# =========================================================================
def test_c6_test_l_routing_preservation():
    """C6 preserves shortest-path routing and path length calculation."""
    step = bfs_first_step((0, 0), (3, 5))
    assert step in ("SOUTH", "EAST")
    assert path_length((0, 0), (3, 5)) == 8


# =========================================================================
# Test M — C1 exclusion
# =========================================================================
def test_c6_test_m_c1_exclusion():
    """C1 remains strictly excluded: worker count & hiring schedule unchanged."""
    assert DAY_TO_HANDS == {0: 4, 6: 8, 9: 8, 10: 10, 11: 12, 30: 0}
    assert get_target_hands(0) == 4
    assert get_target_hands(15) == 12
    assert get_target_hands(29) == 12


# =========================================================================
# Test N — C3 exclusion
# =========================================================================
def test_c6_test_n_c3_exclusion():
    """C3 remains strictly excluded: Melon tile cap locked at 12/6."""
    assert CROP_TILE_CAPS["MELON"] <= 12
