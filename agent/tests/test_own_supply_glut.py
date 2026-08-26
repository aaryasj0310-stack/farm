"""Tests for P1: own-supply glut in macro_planner._crop_score.

Proves that:
  - increasing own production lowers effective price
  - melon is no longer incorrectly ranked highly under town-only forecast
  - wheat's log curve absorbs glut better than melon's sq curve
  - planner allocation changes when own-supply is considered
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _sub in ("state", "strategy", "execution", "market"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), _sub))

from strategy.macro_planner import (
    MacroPlanner,
    _crop_score,
    _cum_town_drain,
    _cum_own_production,
)
from market.price_math import market_price, MARKET_I0
from config import CROPS


# ---------------------------------------------------------------------------
# Fake forecast: constant price per product (sufficient for own-supply tests)
# ---------------------------------------------------------------------------

def make_forecast(prices_by_product):
    class FakeFC:
        def __init__(self, prices):
            self.prices = prices
        def expected_price(self, product, day):
            return self.prices.get(product, 25.0)
    return FakeFC(prices_by_product)


BASE_PRICES = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60,
               "STRAWBERRY": 120, "MELON": 250,
               "EGG": 50, "MILK": 160, "WOOL": 200}


# ---------------------------------------------------------------------------
# Helper: build a test context with configurable wheat tiles
# ---------------------------------------------------------------------------

def make_ctx(day=5, money=3000.0, hands=(), shed=None, seeds=None,
             animals=(), structures=(), unlocked=("NW",), wheat_tiles=0):
    from observation_parser import parse_observation
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
        "money": money, "tiles": tiles, "farmer": [4, 4],
        "hands": [[4, 4]] * len(hands),
        "unlocked_quadrants": list(unlocked), "hires_today": 0,
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
    ctx = parse_observation(obs)
    assert ctx is not None
    return ctx


# ---------------------------------------------------------------------------
# 1. Monotonic penalty: more own production → lower score
# ---------------------------------------------------------------------------

def test_own_supply_penalizes_melon_monotonically():
    """Melon score must decrease as own_tiles increases."""
    fc = make_forecast(BASE_PRICES)
    scores = []
    for tiles in (0, 5, 10, 25):
        s, _ = _crop_score("MELON", 5, fc, {}, own_tiles=tiles)
        scores.append(s)
    # strictly decreasing
    for i in range(1, len(scores)):
        assert scores[i] < scores[i - 1], \
            f"melon score did not decrease: {scores}"


def test_own_supply_penalizes_strawberry_monotonically():
    """Strawberry score must decrease as own_tiles increases.

    Note: strawberry is ongoing (interval=2) with low cycle_yield, so
    it hits the $1 floor quickly. The key test is 0→5 tiles causes a drop.
    """
    fc = make_forecast(BASE_PRICES)
    s0, _ = _crop_score("STRAWBERRY", 5, fc, {}, own_tiles=0)
    s5, _ = _crop_score("STRAWBERRY", 5, fc, {}, own_tiles=5)
    s25, _ = _crop_score("STRAWBERRY", 5, fc, {}, own_tiles=25)
    assert s5 < s0, f"strawberry not penalized at 5 tiles: {s5} vs {s0}"
    assert s25 <= s5, f"strawberry score increased at 25 tiles: {s25} vs {s5}"


def test_own_supply_penalizes_wheat_gently():
    """Wheat's log curve absorbs glut better than melon's sq curve."""
    fc = make_forecast(BASE_PRICES)
    s0_m, _ = _crop_score("MELON", 5, fc, {}, own_tiles=0)
    s25_m, _ = _crop_score("MELON", 5, fc, {}, own_tiles=25)
    s0_w, _ = _crop_score("WHEAT", 5, fc, {}, own_tiles=0)
    s25_w, _ = _crop_score("WHEAT", 5, fc, {}, own_tiles=25)
    melon_drop = s0_m - s25_m
    wheat_drop = s0_w - s25_w
    # melon penalized at least 10x harder than wheat
    assert melon_drop > wheat_drop * 10, \
        f"melon drop {melon_drop:.1f} should be >> wheat drop {wheat_drop:.1f}"


# ---------------------------------------------------------------------------
# 2. Effective price at harvest drops with own production
# ---------------------------------------------------------------------------

def test_eff_price_drops_with_own_production():
    """market_price(I0 + own) < market_price(I0) for glut-side products."""
    fc = make_forecast(BASE_PRICES)
    for crop in ("MELON", "STRAWBERRY", "TOMATO"):
        _, d0 = _crop_score(crop, 5, fc, {}, own_tiles=0)
        _, d25 = _crop_score(crop, 5, fc, {}, own_tiles=25)
        for h in d0.get("eff_prices", {}):
            if h in d25["eff_prices"]:
                assert d25["eff_prices"][h] < d0["eff_prices"][h], \
                    f"{crop} day {h}: eff_price did not drop"


def test_eff_price_zero_tiles_equals_forecast():
    """With own_tiles=0, eff_price matches town-only forecast."""
    fc = make_forecast(BASE_PRICES)
    for crop in ("WHEAT", "CARROT", "MELON"):
        _, d = _crop_score(crop, 5, fc, {}, own_tiles=0)
        for h, eff_p in d.get("eff_prices", {}).items():
            town_p = fc.expected_price(crop, h)
            assert abs(eff_p - town_p) < 1.0, \
                f"{crop} day {h}: eff={eff_p} != town={town_p}"


# ---------------------------------------------------------------------------
# 3. Melon no longer ranked highest under constant base prices
# ---------------------------------------------------------------------------

def test_melon_not_ranked_first_with_own_tiles():
    """Under constant base prices with 25 tiles, melon must NOT be #1."""
    fc = make_forecast(BASE_PRICES)
    scores = {}
    for crop in CROPS:
        if crop == "FERTILIZER":
            continue
        s, _ = _crop_score(crop, 5, fc, {}, own_tiles=25)
        scores[crop] = s
    ranked = sorted(scores, key=scores.get, reverse=True)
    assert ranked[0] != "MELON", \
        f"melon still ranked #1 with own_tiles=25: {ranked}"


def test_wheat_beats_melon_under_own_tiles():
    """Wheat must outrank melon when own production is considered."""
    fc = make_forecast(BASE_PRICES)
    s_w, _ = _crop_score("WHEAT", 5, fc, {}, own_tiles=25)
    s_m, _ = _crop_score("MELON", 5, fc, {}, own_tiles=25)
    assert s_w > s_m, f"wheat {s_w:.2f} should beat melon {s_m:.2f}"


# ---------------------------------------------------------------------------
# 4. Wheat feed offset reduces own production for wheat
# ---------------------------------------------------------------------------

def test_wheat_feed_offset_reduces_own_production():
    """Feeding animals subtracts from wheat's cumulative own production."""
    fc = make_forecast(BASE_PRICES)
    _, d_no_feed = _crop_score("WHEAT", 5, fc, {}, own_tiles=25,
                                feed_wheat_per_day=0)
    _, d_feed = _crop_score("WHEAT", 5, fc, {}, own_tiles=25,
                             feed_wheat_per_day=10)
    # with feed offset, cum_own is lower → eff_price is higher → score higher
    for h in d_no_feed.get("cum_own", {}):
        if h in d_feed["cum_own"]:
            assert d_feed["cum_own"][h] <= d_no_feed["cum_own"][h]


# ---------------------------------------------------------------------------
# 5. Planner integration: melon no longer dominates plant_queue
# ---------------------------------------------------------------------------

def test_planner_no_melon_dominance_with_own_tiles():
    """With 22 free tiles, planner should NOT plant all melons."""
    fc = make_forecast(BASE_PRICES)
    seeds = {"MELON": 30, "WHEAT": 30, "CARROT": 30, "TOMATO": 30,
             "STRAWBERRY": 30}
    ctx = make_ctx(day=5, money=99999, seeds=seeds)
    plan = MacroPlanner(fc).build(ctx)
    melon_count = sum(1 for _, c in plan.plant_queue if c == "MELON")
    total = len(plan.plant_queue)
    assert total > 0, "empty plant queue"
    # melon should be a small fraction, not dominant
    assert melon_count < total * 0.5, \
        f"melon dominates: {melon_count}/{total}"


def test_planner_deterministic_with_own_supply():
    """Own-supply scoring is deterministic."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=3000)
    p1 = MacroPlanner(fc).build(ctx)
    p2 = MacroPlanner(fc).build(ctx)
    assert p1.plant_queue == p2.plant_queue
    assert p1.intents == p2.intents
