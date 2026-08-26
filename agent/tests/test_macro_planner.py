"""W2 tests: MacroPlanner decisions under controlled forecast/state."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from observation_parser import parse_observation
from config import CROPS
from strategy.macro_planner import MacroPlanner, _crop_allowed_today


def make_forecast(prices_by_product):
    """Constant-per-product fake forecast satisfying the MacroPlanner API."""
    class FakeFC:
        def __init__(self, prices):
            self.prices = prices

        def expected_price(self, product, day):
            return self.prices.get(product, 25.0)

    return FakeFC(prices_by_product)


def make_ctx(day=5, money=3000.0, hands=(), shed=None, seeds=None,
             animals=(), structures=(), unlocked=("NW",)):
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
    ctx = parse_observation(obs)
    assert ctx is not None
    return ctx


BASE_PRICES = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
               "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200}


def test_midgame_plan_queues_crops_and_seed_buys():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=3000)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.plant_queue, "empty tiles should be queued for planting"
    for pos, crop in plan.plant_queue:
        assert _crop_allowed_today(crop, 5)
    cost = sum(CROPS[c]["seed"] * n for c, n in plan.intents["buy_seed"].items())
    assert cost <= 3000 - 300   # seed buys within bank minus reserve
    # 25 NW tiles minus 3 reserved for animal structures = 22 queued actions,
    # which fit inside a lone farmer's 24 turns -> no hires required.
    assert len(plan.plant_queue) == 22
    assert plan.intents["hire"] == 0
    assert plan.water_budget_exceeded is False


def test_endgame_shuts_everything_down():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=29, money=99999)
    plan = MacroPlanner(fc).build(ctx)
    assert plan.phase == "endgame"
    assert plan.watering_enabled is False
    assert plan.feeding_enabled is False
    assert plan.plant_queue == []
    assert plan.intents == {}


def test_melon_cutoff_respected():
    fc = make_forecast(BASE_PRICES)
    # day 18: fert-melon cutoff is day 17 -> no melons allowed
    ctx = make_ctx(day=18, money=5000)
    plan = MacroPlanner(fc).build(ctx)
    assert all(crop != "MELON" for _, crop in plan.plant_queue)


def test_high_price_pivot_to_carrot():
    boosted = dict(BASE_PRICES, CARROT=400.0)
    base_fc = make_forecast(BASE_PRICES)
    carrot_fc = make_forecast(boosted)
    seeds = {"CARROT": 25}          # pre-owned so cash never blocks comparison
    plan_base = MacroPlanner(base_fc).build(make_ctx(day=20, money=5000, seeds=seeds))
    plan_carrot = MacroPlanner(carrot_fc).build(make_ctx(day=20, money=5000, seeds=seeds))
    n_base = sum(1 for _, c in plan_base.plant_queue if c == "CARROT")
    n_boost = sum(1 for _, c in plan_carrot.plant_queue if c == "CARROT")
    assert n_boost > n_base


def test_cash_starved_limits_buys():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=5, money=150)     # below reserve: nothing affordable
    plan = MacroPlanner(fc).build(ctx)
    cost = sum(CROPS[c]["seed"] * n for c, n in plan.intents["buy_seed"].items())
    assert cost <= max(0, 150 - 300) or cost == 0


def test_animal_expansion_intents_and_feed():
    goose_tile = (2, 2)
    animals = [(goose_tile[0], goose_tile[1],
                {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                 "yield_units": 1, "fed_today": True, "cared_today": False,
                 "consecutive_unfed": 0, "fertilizer_available": False,
                 "pending_care_bonus": 0})]
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=8, money=20000, animals=animals, shed={"WHEAT": 0})
    plan = MacroPlanner(fc).build(ctx)
    assert plan.intents["buy_animal"].get("GOOSE", 0) >= 1
    assert plan.build_op in ("BUILD_COOP", "BUILD_PASTURE")
    # feed buffer for existing animals triggers wheat purchase
    assert plan.intents["buy_wheat"] >= 2


def test_deterministic_output():
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=6, money=2500)
    p1 = MacroPlanner(fc).build(ctx)
    p2 = MacroPlanner(fc).build(ctx)
    assert p1.plant_queue == p2.plant_queue
    assert p1.intents == p2.intents
