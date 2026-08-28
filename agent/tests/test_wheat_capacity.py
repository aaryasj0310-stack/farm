"""Tests for wheat capacity projection and dynamic animal-cap controller.

Verifies that:
  - 24 animals require 24 wheat/day
  - the 2-day buffer (~48 wheat) is maintained
  - projected wheat shortage is detected before starvation
  - animal targets are correctly reduced or wheat purchases triggered
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CROPS, FEED_WHEAT_BUFFER_DAYS, TARGET_GEESE, TARGET_COWS, TARGET_SHEEP
from strategy.macro_planner import (
    MacroPlanner,
    project_wheat_harvests,
    compute_wheat_capacity,
    compute_sustainable_animals,
    detect_wheat_deficit,
)


# ── wheat harvest projection ─────────────────────────────────────────────

def test_wheat_harvest_day0():
    """Tile planted day 0: first_yield=2, max_yield=4, yields 6 units."""
    h = project_wheat_harvests(plant_day=0, current_day=0)
    assert h == 6  # 6 units × (1 + (4-2)) = 6


def test_wheat_harvest_day5():
    """Tile planted day 5: harvest window days 7-9, still gets 6 units."""
    h = project_wheat_harvests(plant_day=5, current_day=5)
    assert h == 6  # max_yield_day=4 → harvest by day 9 ≤ 29


def test_wheat_harvest_day26():
    """Tile planted day 26: max_yield_day=4 → harvest at day 30 > 29 → zero."""
    h = project_wheat_harvests(plant_day=26, current_day=26)
    assert h == 0  # can't harvest before season end


def test_wheat_harvest_day28():
    """Tile planted day 28: first harvest day 30 > 29 → zero."""
    h = project_wheat_harvests(plant_day=28, current_day=28)
    assert h == 0


def test_wheat_harvest_day27():
    """Tile planted day 27: max_yield_day=4 → harvest at day 31 > 29 → zero."""
    h = project_wheat_harvests(plant_day=27, current_day=27)
    assert h == 0  # can't harvest before season end


def test_wheat_capacity_scales_with_tiles():
    """Capacity = tiles × per-tile yield."""
    tiles = [0, 0, 5, 10]  # 4 tiles at different plant days
    cap = compute_wheat_capacity(tiles, current_day=0)
    assert cap == 6 + 6 + 6 + 6  # all 4 tiles produce 6 units


def test_wheat_capacity_empty():
    """No tiles → zero capacity."""
    assert compute_wheat_capacity([], current_day=0) == 0


# ── sustainable animal count ─────────────────────────────────────────────

def test_sustainable_24_animals():
    """24 animals × 30 days × 1 wheat = 720 wheat needed.

    With 20 wheat tiles planted day 0: 20 × 6 = 120 wheat capacity.
    120 // 30 = 4 sustainable animals (not 24).
    """
    cap = compute_wheat_capacity([0] * 20, current_day=0)  # 120
    sus = compute_sustainable_animals(cap, days_left=30)
    assert sus == 4  # 120 // 30 = 4


def test_sustainable_scales_with_capacity():
    """More wheat tiles → more sustainable animals."""
    cap60 = compute_wheat_capacity([0] * 10, current_day=0)  # 60
    cap120 = compute_wheat_capacity([0] * 20, current_day=0)  # 120
    assert compute_sustainable_animals(cap120, 30) > \
           compute_sustainable_animals(cap60, 30)


def test_sustainable_zero_capacity():
    """No wheat production → zero sustainable animals."""
    assert compute_sustainable_animals(0, days_left=30) == 0


def test_sustainable_zero_days():
    """Season over → zero."""
    assert compute_sustainable_animals(100, days_left=0) == 0


# ── deficit detection ────────────────────────────────────────────────────

def test_no_deficit_when_surplus():
    """Plenty of wheat → no deficit, no trigger."""
    deficit, trigger = detect_wheat_deficit(
        wheat_capacity=200, wheat_have=100, days_left=10,
        n_animals=5, buffer_days=2)
    # demand = 5×10 + 5×2 = 60; supply = 100+200=300 → surplus
    assert deficit == 0
    assert trigger is False


def test_deficit_detected():
    """Low wheat → deficit detected."""
    deficit, trigger = detect_wheat_deficit(
        wheat_capacity=0, wheat_have=5, days_left=20,
        n_animals=10, buffer_days=2)
    # demand = 10×20 + 10×2 = 220; supply = 5+0=5 → deficit 215
    assert deficit == 215
    assert trigger is True  # wheat_have(5) < 10×2=20


def test_trigger_only_when_buffer_low():
    """Deficit exists but buffer is full → no urgent trigger."""
    deficit, trigger = detect_wheat_deficit(
        wheat_capacity=0, wheat_have=50, days_left=10,
        n_animals=10, buffer_days=2)
    # demand = 10×10 + 10×2 = 120; supply = 50+0=50 → deficit 70
    assert deficit == 70
    assert trigger is False  # wheat_have(50) >= 10×2=20


# ── planner integration ─────────────────────────────────────────────────

def make_forecast(prices_by_product):
    class FakeFC:
        def __init__(self, prices):
            self.prices = prices
        def expected_price(self, product, day):
            return self.prices.get(product, 25.0)
    return FakeFC(prices_by_product)


def make_ctx(day=5, money=3000.0, hands=(), shed=None, seeds=None,
             animals=(), structures=(), unlocked=("NW",), wheat_tiles=0):
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    half = 5
    quads = {("N", "W"): "NW", ("N", "E"): "NE",
             ("S", "W"): "SW", ("S", "E"): "SE"}
    for y in range(board):
        for x in range(board):
            q = quads[("N" if y < half else "S", "W" if x < half else "E")]
            if q not in unlocked:
                tiles[y][x] = "LOCKED"
    for (x, y, obj) in list(animals) + list(structures):
        tiles[y][x] = obj
    # plant wheat tiles (engine uses kind="PLANT" with crop="WHEAT")
    wheat_placed = 0
    for y in range(board):
        for x in range(board):
            if wheat_placed >= wheat_tiles:
                break
            if tiles[y][x] is None:
                tiles[y][x] = {
                    "kind": "PLANT", "crop": "WHEAT",
                    "pos": (x, y), "x": x, "y": y,
                    "watered_today": False, "yield_units": 0,
                    "placed_day": day, "consecutive_unwatered": 0,
                }
                wheat_placed += 1
        if wheat_placed >= wheat_tiles:
            break
    farm = {
        "money": money,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4]] * len(hands),
        "unlocked_quadrants": list(unlocked),
        "hires_today": 0,
    }
    obs = {
        "player": 0, "day": day, "hour": 1,
        "farms": [farm, farm],
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
        "private": {"shed": dict(shed or {}),
                    "seeds": dict(seeds or {}),
                    "inventories": [{}]},
    }
    from observation_parser import parse_observation
    ctx = parse_observation(obs)
    assert ctx is not None
    return ctx


BASE_PRICES = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
               "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200}


def test_planner_caps_animals_without_wheat():
    """No wheat tiles → sustainable=0 → planner buys zero new animals."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=20000, wheat_tiles=0)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_animal"] == {}


def test_planner_allows_animals_with_wheat():
    """10 wheat tiles → sustainable ≈ 2 → planner allows some animal buys."""
    fc = make_forecast(BASE_PRICES)
    # 10 tiles × 6 units = 60 capacity; 60 // 30 = 2 sustainable
    ctx = make_ctx(day=5, money=20000, wheat_tiles=10)
    plan = MacroPlanner(fc).build(ctx)
    total_buys = sum(plan.intents["buy_animal"].values())
    assert total_buys <= 2  # capped by sustainable


def test_planner_triggers_wheat_purchase_on_deficit():
    """Animals exist but no wheat → trigger buys wheat to fill deficit."""
    animals = [(2, 2, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                        "yield_units": 1, "fed_today": True,
                        "cared_today": False, "consecutive_unfed": 0,
                        "fertilizer_available": False, "pending_care_bonus": 0})]
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=8, money=20000, animals=animals,
                   shed={"WHEAT": 0}, wheat_tiles=0)
    plan = MacroPlanner(fc).build(ctx)
    # 1 animal, 0 wheat capacity, 22 days left → deficit = 1×22+1×2=24
    assert plan.intents["buy_wheat"] >= 24


def test_planner_no_trigger_with_sufficient_wheat():
    """Wheat tiles produce enough → no deficit trigger, but buffer is maintained."""
    animals = [(2, 2, {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                        "yield_units": 1, "fed_today": True,
                        "cared_today": False, "consecutive_unfed": 0,
                        "fertilizer_available": False, "pending_care_bonus": 0})]
    fc = make_forecast(BASE_PRICES)
    # 20 wheat tiles × 6 = 120 capacity; 1 animal × 22 days = 22 demand → surplus
    # Need hands for labor gate: 5 hands + 1 farmer = 6 units × 12 = 72 capacity
    ctx = make_ctx(day=8, money=20000, animals=animals,
                   shed={"WHEAT": 0}, wheat_tiles=20, hands=[(3,3)] * 5)
    plan = MacroPlanner(fc).build(ctx)
    # deficit is zero (120 cap > 24 demand) → no deficit trigger
    # buffer maintenance for existing goose: 1 * 2 = 2
    assert plan.intents["buy_wheat"] >= 2
    # key assertion: NOT the full deficit (which would be 24)
    assert plan.intents["buy_wheat"] < 24


def test_sustainable_animals_24():
    """Verify the 24-animal target requires specific wheat capacity.

    24 animals × 30 days = 720 wheat needed.
    Each wheat tile produces 6 units.
    Need 720/6 = 120 wheat tiles → sustainable = 120×6//30 = 24.
    """
    cap = compute_wheat_capacity([0] * 120, current_day=0)  # 720
    sus = compute_sustainable_animals(cap, days_left=30)
    assert sus == 24  # exactly supports 24 animals


def test_sustainable_less_than_24():
    """With only 10 wheat tiles, sustainable is 2 (not 24)."""
    cap = compute_wheat_capacity([0] * 10, current_day=0)  # 60
    sus = compute_sustainable_animals(cap, days_left=30)
    assert sus == 2  # 60 // 30 = 2
    assert sus < TARGET_GEESE + TARGET_COWS + TARGET_SHEEP
