"""W-market tests: order_builder intent -> engine-format orders."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import MAX_MARKET_ORDERS
from market.order_builder import OrderBuilder, hire_total_cost, land_price_for
from observation_parser import parse_observation


def make_ctx(money=3000.0, unlocked=("NW",), shed=None, structures=()):
    board = 10
    tiles = [[None] * board for _ in range(board)]
    half = 5
    quads = {("N", "W"): "NW", ("N", "E"): "NE",
             ("S", "W"): "SW", ("S", "E"): "SE"}
    for y in range(board):
        for x in range(board):
            q = quads[("N" if y < half else "S", "W" if x < half else "E")]
            if q not in unlocked:
                tiles[y][x] = "LOCKED"
    for (x, y, obj) in list(structures):
        tiles[y][x] = obj
    farm = {"money": money, "tiles": tiles, "farmer": [4, 4], "hands": [],
            "unlocked_quadrants": list(unlocked), "hires_today": 0}
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    inv = {p: 10000 for p in products}
    obs = {"player": 0, "day": 5, "hour": 0,
           "farms": [farm, farm],
           "market": {"inventory": inv, "prices": {}},
           "town": {"unlocked_shops": []},
           "private": {"shed": dict(shed or {}), "seeds": {},
                       "inventories": [{}]}}
    return parse_observation(obs)


INTENTS_FULL = {
    "hire": 3,
    "buy_land": True,
    "buy_seed": {"MELON": 15, "CARROT": 10},
    "buy_animal": {"GOOSE": 1},
    "buy_wheat": 20,
}


def test_hire_cost_mirror():
    assert hire_total_cost(0) == 0
    assert hire_total_cost(1) == 1
    assert land_price_for(1) == 1000 and land_price_for(2) == 2000
    assert land_price_for(3) is None


def test_full_intents_shape_and_budget():
    structures = [(0, 0, {"kind": "COOP"})]
    ctx = make_ctx(money=3600, structures=structures)              # budget 3300 after reserve
    orders, ledger = OrderBuilder().build(ctx, INTENTS_FULL)
    assert len(orders) <= MAX_MARKET_ORDERS
    # hires expanded to one entry each
    assert sum(1 for o in orders if o[0] == "HIRE") == 3
    # seeds aggregated into one order per crop
    melon = [o for o in orders if o[0] == "BUY_SEED" and o[1] == "MELON"]
    assert len(melon) == 1 and melon[0][2] == 15
    # wheat buffered estimate kept within budget tier
    wheat = [o for o in orders if o[0] == "BUY_PRODUCT"]
    assert len(wheat) == 1 and wheat[0][2] == 20
    # animals clamped by shed room (shed empty -> 1 goose fits)
    goose = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert goose and goose[0][2] == 1
    # exact tier stack: 4 (hires) + 350 + 1200 (seeds) + 560 (buffered wheat,
    # ceil(25*1.1)=28/unit x20) + 300 (goose) + 1000 (land) = 3264 <= 3300
    assert ["BUY_LAND"] in [list(o) for o in orders]
    assert ledger["spent_estimate"] == pytest.approx(3264)
    assert ledger["spent_estimate"] <= ledger["budget"] + 1e-6


def test_land_fits_when_budget_allows():
    ctx = make_ctx(money=3800)              # budget 3500 >= 3264 needed
    orders, ledger = OrderBuilder().build(ctx, INTENTS_FULL)
    assert ["BUY_LAND"] in [list(o) for o in orders]
    assert ledger["spent_estimate"] <= ledger["budget"] + 1e-6


def test_budget_trim_prioritizes_land_and_clamps_counts():
    ctx = make_ctx(money=1500)              # budget 1200
    orders, ledger = OrderBuilder().build(ctx, INTENTS_FULL)
    kinds = [o[0] for o in orders]
    assert kinds.count("HIRE") == 3
    assert any(o[0] == "BUY_LAND" for o in orders), \
        "land is high priority when budget allows"


def test_seed_quantity_clamped_to_affordability():
    ctx = make_ctx(money=500)               # budget 200 -> 10 melon seeds max
    orders, ledger = OrderBuilder().build(ctx, INTENTS_FULL)
    melon = [o for o in orders if o[:2] == ["BUY_SEED", "MELON"]]
    if melon:
        assert melon[0][2] <= 10
        trims = [d for d in ledger["dropped"] if d.get("kind") == "seed"
                 and d.get("crop") == "MELON"]
        assert trims, "expected a trim record"


def test_order_cap_enforced_with_huge_intents():
    ctx = make_ctx(money=100000)
    intents = {
        "hire": 7,
        "buy_land": True,
        "buy_seed": {"MELON": 40, "CARROT": 30, "TOMATO": 20},
        "buy_animal": {"GOOSE": 5, "COW": 3, "SHEEP": 2},
        "buy_wheat": 90,
    }
    orders, _ = OrderBuilder().build(ctx, intents)
    assert len(orders) <= MAX_MARKET_ORDERS


def test_reserve_protects_minimum_cash():
    ctx = make_ctx(money=304)               # budget 4 with default reserve 300
    orders, ledger = OrderBuilder().build(ctx, INTENTS_FULL)
    assert ledger["budget"] == pytest.approx(4)
    # three hires cost fib(0)+fib(1)+fib(2) = 4 coins -> they DO fit $4;
    # everything else must be dropped by the budget gate.
    hires = [o for o in orders if o[0] == "HIRE"]
    assert len(hires) == 3
    assert ledger["spent_estimate"] <= 4 + 1e-6
    assert not any(o[0].startswith("BUY") for o in orders)


def test_shed_room_limits_animal_buys():
    structures = [(x, y, {"kind": "COOP"}) for x in range(3) for y in range(3)]
    ctx = make_ctx(money=30000, shed={"WHEAT": 95}, structures=structures)   # room = 5
    intents = {"hire": 0, "buy_land": False, "buy_seed": {},
               "buy_animal": {"GOOSE": 8}, "buy_wheat": 0}
    orders, ledger = OrderBuilder().build(ctx, intents)
    goose = [o for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "GOOSE"]
    assert goose[0][2] <= 5
