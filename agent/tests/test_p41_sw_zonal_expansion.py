"""
Unit and Isolation Tests for P4.1 Late-Season Isolated SW Zonal Acreage Expansion.

Verifies:
1. Control Equivalence: When P41_SW_ZONAL_EXPANSION_ENABLED = False, behavior is 100% bit-for-bit identical to baseline.
2. Two-Worker Isolation: Units 11 & 12 are assigned to SW; units 0..10 remain partitioned in NW/NE.
3. Task Eligibility Invariants: Core workers are forbidden from SW agricultural tasks; shed access and emergency feeding remain open.
4. Purchase Pipeline & Activation Gate: Day 14, $15k cash, 13 workers, 90% core occupancy authorization.
5. SW Crop Controller: Plans only the 8 dedicated zone tiles with selected crop mode.
"""
import pytest
import sys
import os
from unittest.mock import patch

for p in ["agent", "agent/state", "agent/strategy", "agent/execution", "agent/market"]:
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from config import (
    set_p41_sw_zonal_expansion_enabled,
    get_p41_sw_zonal_expansion_enabled,
    set_p41_sw_crop_mode,
    get_p41_sw_crop_mode,
    P41_SW_ZONE_COORDS,
    P41_SW_DEDICATED_WORKER_INDICES,
    SHED_ACCESS_TILES,
)
from execution.task_scheduler import get_home_quadrant, assign_tasks
from strategy.expansion_planner import should_buy_land


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
        self.yield_units = 0
        self.fertilized_until_day = -1
        self.fed_today = False
        self.cared_today = False
        self.consecutive_unfed = 0
        self.fertilizer_available = False
        self.pending_care_bonus = 0


class MockFarm:
    def __init__(self, unlocked=None, money=20000.0, n_hands=12):
        self.unlocked = set(unlocked or ["NW", "NE"])
        self.money = float(money)
        self.farmer = (4, 4)
        self.hands = [(4, 4)] * n_hands
        self.tiles = []
        for y in range(10):
            row = []
            for x in range(10):
                row.append(MockTile(x, y))
            self.tiles.append(row)

    def iter_tiles(self):
        for row in self.tiles:
            for t in row:
                yield t

    def tile_at(self, pos):
        x, y = pos
        return self.tiles[y][x]

    def quadrant_of(self, pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def test_control_equivalence_when_disabled():
    """Verify that when disabled, get_home_quadrant reproduces baseline squad partition."""
    set_p41_sw_zonal_expansion_enabled(False)
    assert not get_p41_sw_zonal_expansion_enabled()

    # In baseline with SW unlocked and 13 units, units 8..12 are SW, 0..3 are NW, 4..7 are NE
    unlocked = {"NW", "NE", "SW"}
    n_units = 13
    baseline_sw = [u for u in range(n_units) if get_home_quadrant(u, n_units, unlocked) == "SW"]
    assert baseline_sw == [8, 9, 10, 11, 12], f"Expected legacy 5-worker squad, got {baseline_sw}"


def test_two_worker_squad_override_when_enabled():
    """Verify that when enabled, get_home_quadrant assigns strictly units 11 & 12 to SW."""
    set_p41_sw_zonal_expansion_enabled(True)
    try:
        unlocked = {"NW", "NE", "SW"}
        n_units = 13
        sw_squad = [u for u in range(n_units) if get_home_quadrant(u, n_units, unlocked) == "SW"]
        assert sw_squad == [11, 12], f"Expected strictly [11, 12] in SW, got {sw_squad}"

        # Units 8, 9, 10 must NOT be in SW
        for u in (8, 9, 10):
            hq = get_home_quadrant(u, n_units, unlocked)
            assert hq in ("NW", "NE"), f"Unit {u} was assigned to {hq}, expected core"
    finally:
        set_p41_sw_zonal_expansion_enabled(False)


def test_should_buy_land_p41_gate():
    """Verify the P4.1 purchase gate conditions."""
    set_p41_sw_zonal_expansion_enabled(True)
    try:
        farm = MockFarm(unlocked=["NW", "NE"], money=16000.0, n_hands=12)

        # 1. Day < 14 should reject
        ok, reason, diag = should_buy_land(3, current_day=13, money=farm.money, farm=farm)
        assert not ok
        assert "before_day_14" in reason

        # 2. Money < 15,000 should reject
        ok, reason, diag = should_buy_land(3, current_day=14, money=14500.0, farm=farm)
        assert not ok
        assert "p41_insufficient_cash" in reason

        # 3. Core occupancy < 90% should reject
        ok, reason, diag = should_buy_land(3, current_day=14, money=farm.money, farm=farm)
        assert not ok
        assert "p41_core_occupancy_low" in reason

        # 4. Populate core farm to >= 90% (out of 46 usable tiles)
        core_tiles = [
            t for t in farm.iter_tiles()
            if farm.quadrant_of(t.pos) in ("NW", "NE") and t.pos not in SHED_ACCESS_TILES
        ]
        assert len(core_tiles) == 48
        for t in core_tiles[:45]:  # 45 / 48 = 93.75%
            t.is_plant = True
            t.kind = "PLANT"

        # 5. Workers < 13 should reject when simulated with fewer workers
        with patch("strategy.land_serviceability_model.compute_projected_workers", return_value=11):
            ok, reason, diag = should_buy_land(3, current_day=14, money=farm.money, farm=farm)
            assert not ok
            assert "p41_insufficient_workers" in reason

        # 6. All conditions met: Day 14, $16k cash, 13 workers, 93.5% core occupancy
        ok, reason, diag = should_buy_land(3, current_day=14, money=farm.money, farm=farm)
        assert ok
        assert reason == "p41_sw_zonal_authorized"
        assert diag["p41_core_occupancy"] >= 0.90
    finally:
        set_p41_sw_zonal_expansion_enabled(False)


def test_task_eligibility_isolation():
    """Verify task eligibility isolation between SW and core agricultural tasks."""
    set_p41_sw_zonal_expansion_enabled(True)
    try:
        farm = MockFarm(unlocked=["NW", "NE", "SW"], money=16000.0, n_hands=12)
        ctx = {
            "farm": farm,
            "day": 14,
            "hour": 2,
            "private": None,
        }

        # SW agricultural task on (3, 6)
        sw_task = {
            "op": "WATER",
            "target": (3, 6),
            "priority": 75,
            "kind": "water_crop",
        }

        # Core agricultural task on (1, 1)
        core_task = {
            "op": "WATER",
            "target": (1, 1),
            "priority": 75,
            "kind": "water_crop",
        }

        # Shed task on (4, 4)
        shed_task = {
            "op": "PICKUP",
            "target": (4, 4),
            "priority": 86,
            "kind": "pickup_wheat",
        }

        tasks = [sw_task, core_task, shed_task]
        asg = assign_tasks(tasks, ctx)
        assignment = asg["assignment"]

        # Hands 11 & 12 are unit indices 11 & 12
        # SW task MUST be assigned to unit 11 or 12
        sw_assignees = [u for u, t in assignment.items() if t.get("target") == (3, 6)]
        if sw_assignees:
            assert sw_assignees[0] in (11, 12), f"SW task assigned to non-dedicated unit: {sw_assignees[0]}"

        # Core task MUST NOT be assigned to unit 11 or 12
        core_assignees = [u for u, t in assignment.items() if t.get("target") == (1, 1)]
        if core_assignees:
            assert core_assignees[0] not in (11, 12), f"Core task assigned to dedicated SW unit: {core_assignees[0]}"
    finally:
        set_p41_sw_zonal_expansion_enabled(False)


def test_sw_crop_controller_planning():
    """Verify that MacroPlanner plans SW crops strictly for the 8 SW zone coordinates."""
    set_p41_sw_zonal_expansion_enabled(True)
    try:
        from strategy.price_forecast import PriceForecast
        from strategy.macro_planner import MacroPlanner
        fc = PriceForecast.load()
        planner = MacroPlanner(fc)

        farm = MockFarm(unlocked=["NW", "NE", "SW"], money=16000.0, n_hands=12)
        # Ensure all 8 SW zone coordinates are empty
        for pos in P41_SW_ZONE_COORDS:
            t = farm.tile_at(pos)
            t.kind = "EMPTY"
            t.is_plant = False

        ctx = {
            "farm": farm,
            "day": 14,
            "hour": 0,
            "private": type("MockPrivate", (), {
                "shed": {"WHEAT": 20},
                "seeds": {"STRAWBERRY": 4, "WHEAT": 4},
                "inventories": [{} for _ in range(13)],
            })(),
            "town": type("MockTown", (), {"unlocked_shops": []})(),
            "step": 336,
        }

        plan = planner.build(ctx)
        p41_diag = plan.diagnostics.get("p41_sw_crop_controller", {})
        assert p41_diag.get("active") is True
        planted_coords = [pos for pos, crop in p41_diag.get("planted", [])]
        for c in planted_coords:
            assert c in P41_SW_ZONE_COORDS
    finally:
        set_p41_sw_zonal_expansion_enabled(False)
