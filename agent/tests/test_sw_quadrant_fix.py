"r""Unit tests for SW Quadrant Fix."""
import pytest
from config import (
    PORT_SW,
    SW_PASTURE_TILES,
    SW_SOIL_TILES,
    SW_ESCROW_AMOUNT,
    get_sw_seed_targets,
)
from strategy.macro_planner import sw_plant_decision, MacroPlanner, _crop_allowed_today
from strategy.expansion_planner import should_buy_land, expansion_seed_targets
from execution.task_scheduler import assign_tasks

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

# 1-------- Layout ---------
def test_sw_layout_invariants():
    assert len(SW_SOIL_TILES) == 15
    assert len(SW_PASTURE_TILES) == 9
    assert PORT_SW == (4, 5)
    sw_all = SW_SOIL_TILES | SW_PASTURE_TILES | {PORT_SW}
    assert len(sw_all) == 25
    assert PORT_SW not in SW_PASTURE_TILES
    assert PORT_SW not in SW_SOIL_TILES
    assert len(SW_PASTURE_TILES & SW_SOIL_TILES) == 0

# 2-------- Escrow & Gate ---------
def test_escrow_gate():
    farm = MockFarm(["NW", "NE"])
    targets = expansion_seed_targets(3, day=9)
    assert targets == {"WHEAT": 15}
    seed_cost = sum(10 * n for n in targets.values())
    assert seed_cost == SW_ESCROW_AMOUNT
    buy, reason, _ = should_buy_land(3, 9, 2100, farm, hire_cost=54, reserve=0, roi=1.0, ow_factor=1.0)
    assert buy is False
    buy, reason, _ = should_buy_land(3, 9, 2250, farm, hire_cost=54, reserve=0, roi=1.0, ow_factor=1.0)
    assert buy is True
    buy, reason, _ = should_buy_land(3, 14, 10000, farm, hire_cost=54, roi=2.0, ow_factor=1.0)
    assert buy is False
    assert "sw_window_closed_after_day_13" in reason

# 3-------- Planting Decision ---------
def test_sw_plant_decision_logic():
    dec = sw_plant_decision(day=9, free_tiles=15, wheat_stock=10, herd_size=6)
    assert dec == {"WHEAT": 15, "CARROT": 0}

    dec = sw_plant_decision(day=25, free_tiles=15, wheat_stock=60, herd_size=9)
    assert dec == {"WHEAT": 0, "CARROT": 15}

    dec = sw_plant_decision(day=25, free_tiles=15, wheat_stock=35, herd_size=9)
    assert dec == {"WHEAT": 2, "CARROT": 13}

    assert sw_plant_decision(26, 15, 0, 9) == {"WHEAT": 0, "CARROT": 15}
    assert sw_plant_decision(27, 15, 0, 9) == {"WHEAT": 0, "CARROT": 15}
    assert sw_plant_decision(28, 15, 0, 9) == {"WHEAT": 0, "CARROT": 0}

    assert _crop_allowed_today("CARROT", 25) is True
    assert _crop_allowed_today("CARROT", 26) is True
    assert _crop_allowed_today("CARROT", 27) is True
    assert _crop_allowed_today("CARROT", 28) is False
    assert _crop_allowed_today("WHEAT", 26) is False
    assert _crop_allowed_today("STRAWBERRY", 26) is False

# 4-------- SW Squad Partitioning ---------
def test_sw_squad_routing():
    hands = [(4, 4), (4, 4), (4, 4), (4, 4), (4, 5), (4, 5), (4, 5), (4, 5)]
    farm = MockFarm(["NW", "NE", "SW"], hands=hands, farmer=(4, 4))
    private = MockPrivate()
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 0}

    tasks = [{"priority": 80, "op": "HARVEST", "target": (2, 7), "kind": "harvest", "args": []}]
    res = assign_tasks(tasks, ctx)
    assignment = res["assignment"]
    assigned_unit = [u for u, t in assignment.items() if t.get("target") == (2, 7)][0]
    assert assigned_unit in (5, 6, 7, 8)

    pickup_tasks = [{"priority": 70, "op": "PICKUP", "target": (4, 4), "kind": "pickup_wheat", "args": ["WHEAT", 5]}]
    res2 = assign_tasks(pickup_tasks, ctx)
    for u, t in res2["assignment"].items():
        if u in (5, 6, 7, 8) and t["op"] == "PICKUP":
            assert t["target"] == PORT_SW

    farm_idle = MockFarm(["NW", "NE", "SW"], hands=[(4, 4), (4, 4), (4, 4), (4, 4), (1, 9), (1, 9), (1, 9), (1, 9)], farmer=(4, 4))
    ctx_idle = {"farm": farm_idle, "private": private, "day": 10, "hour": 0}
    res3_idle = assign_tasks([], ctx_idle)
    for u in (5, 6, 7, 8):
        assert u in res3_idle["assignment"]
        assert res3_idle["assignment"][u]["kind"] == "sw_anchor"
        assert res3_idle["assignment"][u]["target"] == PORT_SW
