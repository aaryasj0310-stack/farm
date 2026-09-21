"""Tests for P2.3 Marginal Wheat Replanting / Crop Substitution isolation and logic."""
import pytest
import sys
import os

# Ensure agent paths are present
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [AGENT_DIR] + [os.path.join(AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from strategy.macro_planner import (
    MacroPlanner,
    project_wheat_harvests,
    compute_wheat_capacity,
    _crop_allowed_today,
    _crop_score,
)
from strategy.price_forecast import PriceForecast


class FakeFC:
    def __init__(self):
        self.prices = {}

    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        return {
            "WHEAT": 25.0, "CARROT": 35.0, "TOMATO": 60.0, "MELON": 250.0,
            "STRAWBERRY": 120.0, "MILK": 160.0, "WOOL": 200.0,
            "EGG": 50.0, "FEATHER": 70.0, "FERTILIZER": 100.0,
        }.get(product, 25.0)


class MockTile:
    def __init__(self, pos, crop=None, is_plant=False, is_animal=False, planted_day=None, animal="COW"):
        self.pos = pos
        self.crop = crop
        self.is_plant = is_plant
        self.is_animal = is_animal
        self.planted_day = planted_day
        self.animal = animal
        self.kind = "PLANT" if is_plant else (animal if is_animal else "EMPTY")
        self.yield_units = 0
        self.cared_today = False
        self.fed_today = False
        self.consecutive_unfed = 0
        self.fertilized_until_day = -1


class MockFarm:
    def __init__(self, tiles=None, unlocked=None, money=5000.0):
        self._tiles = tiles or []
        self.unlocked = unlocked or {"NW", "NE"}
        self.money = money
        self.hands = [0, 1, 2]

    def iter_tiles(self):
        return iter(self._tiles)

    def quadrant_of(self, pos):
        x, y = pos
        if x < 5 and y < 5:
            return "NW"
        elif x >= 5 and y < 5:
            return "NE"
        elif x < 5 and y >= 5:
            return "SW"
        return "SE"


class MockPrivate:
    def __init__(self, shed_wheat=0, seeds=None):
        self.shed = {"WHEAT": shed_wheat}
        self.seeds = seeds or {}
        self.inventories = []


def test_default_flag_is_true():
    """Verify P23_MARGINAL_WHEAT_ALLOCATION_ENABLED defaults to True in production."""
    assert config.P23_MARGINAL_WHEAT_ALLOCATION_ENABLED is True
    assert config.get_p23_marginal_wheat_allocation_enabled() is True


def test_flag_toggle_and_sync():
    """Verify setter toggles flag cleanly and restores safely."""
    try:
        config.set_p23_marginal_wheat_allocation_enabled(False)
        assert config.P23_MARGINAL_WHEAT_ALLOCATION_ENABLED is False
        assert config.get_p23_marginal_wheat_allocation_enabled() is False

        config.set_p23_marginal_wheat_allocation_enabled(True)
        assert config.P23_MARGINAL_WHEAT_ALLOCATION_ENABLED is True
        assert config.get_p23_marginal_wheat_allocation_enabled() is True
    finally:
        config.set_p23_marginal_wheat_allocation_enabled(True)


def test_terminal_deadline_blocks_wheat_on_days_26_plus():
    """Verify wheat planting is strictly blocked on Day 26+ when P2.3 is enabled."""
    try:
        config.set_p23_marginal_wheat_allocation_enabled(True)
        fc = FakeFC()
        planner = MacroPlanner(fc)

        # On Day 26, create empty tiles
        empty_tiles = [MockTile((x, y)) for x in range(3) for y in range(3)]
        animals = [MockTile((4, y), is_animal=True) for y in range(2)]
        farm = MockFarm(tiles=empty_tiles + animals, unlocked={"NW", "NE"})
        private = MockPrivate(shed_wheat=10)

        ctx = {"day": 26, "hour": 0, "farm": farm, "private": private}
        plan = planner.build(ctx)

        p23_diag = plan.diagnostics.get("p23_marginal_wheat", {})
        assert p23_diag.get("reason") == "terminal_deadline_past"
        assert p23_diag.get("wheat_to_plant") == 0
        # Dedicated block must not plant any wheat
        wheat_plantings = [crop for pos, crop in plan.plant_queue if crop == "WHEAT"]
        assert len(wheat_plantings) == 0
    finally:
        config.set_p23_marginal_wheat_allocation_enabled(True)


def test_normal_wheat_replanting_on_days_0_to_25():
    """Days 0-25 strictly preserve normal wheat replanting up to target."""
    try:
        config.set_p23_marginal_wheat_allocation_enabled(True)
        fc = FakeFC()
        planner = MacroPlanner(fc)

        # Day 12: empty tiles available, day <= 25 -> normal replanting
        empty_tiles = [MockTile((x, y)) for x in range(5) for y in range(3)]  # 15 empty tiles
        animals = [MockTile((x, 4), is_animal=True) for x in range(10)]
        farm = MockFarm(tiles=empty_tiles + animals, unlocked={"NW", "NE"})
        private = MockPrivate(shed_wheat=10)

        ctx = {"day": 12, "hour": 0, "farm": farm, "private": private}
        plan = planner.build(ctx)

        p23_diag = plan.diagnostics.get("p23_marginal_wheat", {})
        assert p23_diag.get("reason") == "normal_replant_maintained"
        assert p23_diag.get("wheat_to_plant") > 0
    finally:
        config.set_p23_marginal_wheat_allocation_enabled(True)


def test_p23_production_promoted_terminal_guard():
    """Verify production behavior transitions cleanly from Day 25 to Day 26."""
    try:
        config.set_p23_marginal_wheat_allocation_enabled(True)
        fc = FakeFC()
        planner = MacroPlanner(fc)

        empty_tiles = [MockTile((x, y)) for x in range(3) for y in range(3)]  # 9 empty tiles
        animals = [MockTile((x, 4), is_animal=True) for x in range(2)]
        farm = MockFarm(tiles=empty_tiles + animals, unlocked={"NW", "NE"})
        private = MockPrivate(shed_wheat=50)

        # Day 25: wheat allowed
        plan_25 = planner.build({"day": 25, "hour": 0, "farm": farm, "private": private})
        assert plan_25.diagnostics.get("p23_marginal_wheat", {}).get("reason") == "normal_replant_maintained"
        assert plan_25.diagnostics.get("p23_marginal_wheat", {}).get("wheat_to_plant") > 0

        # Day 26: wheat blocked
        plan_26 = planner.build({"day": 26, "hour": 0, "farm": farm, "private": private})
        assert plan_26.diagnostics.get("p23_marginal_wheat", {}).get("reason") == "terminal_deadline_past"
        assert plan_26.diagnostics.get("p23_marginal_wheat", {}).get("wheat_to_plant") == 0
    finally:
        config.set_p23_marginal_wheat_allocation_enabled(True)


def test_control_invariance_when_flag_false():
    """When P2.3 flag is False, continuous replanting behavior matches baseline exactly."""
    try:
        config.set_p23_marginal_wheat_allocation_enabled(False)
        assert config.get_p23_marginal_wheat_allocation_enabled() is False
        fc = FakeFC()
        planner = MacroPlanner(fc)

        # Even on Day 26 with 100 wheat in shed, baseline blindly targets 20 wheat tiles
        empty_tiles = [MockTile((x, y)) for x in range(5) for y in range(2)]  # 10 empty
        animals = [MockTile((x, 4), is_animal=True) for x in range(2)]
        farm = MockFarm(tiles=empty_tiles + animals, unlocked={"NW", "NE"})
        private = MockPrivate(shed_wheat=100)

        ctx = {"day": 26, "hour": 0, "farm": farm, "private": private}
        plan = planner.build(ctx)

        # In Control, p23_marginal_wheat diagnostic is NOT present
        assert "p23_marginal_wheat" not in plan.diagnostics
        # And baseline planted wheat in the dedicated replant loop
        wheat_plantings = [crop for pos, crop in plan.plant_queue if crop == "WHEAT"]
        assert len(wheat_plantings) > 0
    finally:
        config.set_p23_marginal_wheat_allocation_enabled(True)


def test_project_wheat_harvests_timing():
    """Future wheat only yields if harvest arrives before season cutoff."""
    # Planted day 20 -> harvest day 24 <= 28: yields 6
    assert project_wheat_harvests(20, 20, season_end=28) == 6
    # Planted day 25 -> harvest day 29 > 28: yields 0 for feed before Day 28
    assert project_wheat_harvests(25, 25, season_end=28) == 0
    # Planted day 26 -> harvest day 30 > 29: yields 0 for season
    assert project_wheat_harvests(26, 26, season_end=29) == 0
