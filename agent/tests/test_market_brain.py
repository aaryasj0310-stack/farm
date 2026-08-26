"""W-market tests: MarketBrain sell decisions."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import MAX_MARKET_ORDERS
from market.market_brain import MarketBrain
from observation_parser import parse_observation


class FakeFC:
    """Constant forecast by default; per-product overrides possible."""

    def __init__(self, prices=None, drift=1.0):
        self.prices = prices or {}
        self.drift = drift              # E[P|future] = base * drift
        self.floors = {}                # product -> P(price==$1)

    def prob_floor(self, product, day):
        return self.floors.get(product, 0.0)

    def expected_price(self, product, day):
        return self.prices.get(product, 25.0) * self.drift if product == "WHEAT" \
            else self.prices.get(product, {product: None} and
                                 {"MELON": 250, "EGG": 50, "FERTILIZER": 100,
                                  "CARROT": 35, "TOMATO": 60,
                                  "STRAWBERRY": 120, "MILK": 160,
                                  "WOOL": 200}.get(product, 50)) * (
            1.0 if product != "WHEAT" else self.drift)


def make_ctx(day=10, hour=5, shed=None, inv=None, animals=0, plants=()):
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    inventory = inv or {p: 10000 for p in products}
    board = 10
    tiles = [[None] * board for _ in range(board)]
    for y in range(board):
        for x in range(board):
            if x >= 5 or y >= 5:
                tiles[y][x] = "LOCKED"
    for k in range(animals):
        tiles[0][k] = {"kind": "COOP", "animal": "GOOSE", "placed_day": 1,
                       "yield_units": 0, "fed_today": True,
                       "cared_today": False, "consecutive_unfed": 0,
                       "fertilizer_available": False,
                       "pending_care_bonus": 0}
    for (x, y, plant_dict) in plants:
        tiles[y][x] = plant_dict
    farm = {"money": 5000, "tiles": tiles, "farmer": [4, 4], "hands": [],
            "unlocked_quadrants": ["NW"], "hires_today": 0}
    obs = {"player": 0, "day": day, "hour": hour,
           "farms": [farm, farm],
           "market": {"inventory": inventory, "prices": {}},
           "town": {"unlocked_shops": []},
           "private": {"shed": dict(shed or {}), "seeds": {},
                       "inventories": [{}]}}
    return parse_observation(obs)


def test_non_window_hour_emits_nothing():
    brain = MarketBrain(FakeFC())
    ctx = make_ctx(hour=3, shed={"MELON": 30})
    orders, details = brain.sell_orders(ctx)
    assert orders == []
    assert details["reason"] == "not_a_sell_window"


def test_window_sells_respect_drip_budget_and_stock():
    brain = MarketBrain(FakeFC())
    ctx = make_ctx(day=10, hour=5, shed={"MELON": 50})
    orders, details = brain.sell_orders(ctx)
    melon = [c for c in details["candidates"] if c["product"] == "MELON"]
    assert melon and melon[0]["qty"] <= 50
    for o in orders:
        assert o[0] == "SELL" and 1 <= o[2] <= 50


def test_slots_cap_and_urgency_ranking():
    brain = MarketBrain(FakeFC())
    big_shed = {"WHEAT": 60, "MELON": 40, "EGG": 30, "WOOL": 20,
                "CARROT": 15, "TOMATO": 10, "STRAWBERRY": 8,
                "FERTILIZER": 5, "MILK": 4}
    ctx = make_ctx(day=10, hour=5, shed=big_shed)
    max_slots = int(MAX_MARKET_ORDERS * 0.6)     # 6 sells max
    orders, details = brain.sell_orders(ctx, max_slots=max_slots)
    assert len(orders) <= max_slots
    # ranked by shed share: the largest stock leads
    assert orders[0][1] == "WHEAT"


def test_wheat_reserve_protects_animal_feed():
    brain = MarketBrain(FakeFC())
    ctx = make_ctx(day=10, hour=5, shed={"WHEAT": 12}, animals=5)
    _, details = brain.sell_orders(ctx)
    wheat = [c for c in details["candidates"] if c["product"] == "WHEAT"]
    if wheat:
        assert wheat[0]["qty"] <= 12 - 5 * 2        # FEED_WHEAT_BUFFER_DAYS=2


def test_floor_hold_releases_near_endgame():
    brain = MarketBrain(FakeFC())
    deep_glut = {"MELON": 26000}
    held_ctx = make_ctx(day=10, hour=5, shed={"MELON": 40}, inv=deep_glut)
    orders_held, _ = brain.sell_orders(held_ctx)
    assert not any(o[1] == "MELON" for o in orders_held), \
        "floored premium must be held while season remains"

    dump_ctx = make_ctx(day=29, hour=1, shed={"MELON": 40}, inv=deep_glut)
    orders_dump, _ = brain.sell_orders(dump_ctx)
    melon_dump = [o for o in orders_dump if o[1] == "MELON"]
    assert melon_dump and melon_dump[0][2] == 40


def test_carry_hold_when_recovery_outweighs_sale():
    class RisingFC(FakeFC):
        def expected_price(self, product, day):
            # E[P] grows 10%/day -> strong carry signal for WHEAT
            return 25 * (1.10 ** max(0, day))

    brain = MarketBrain(RisingFC())
    ctx = make_ctx(day=10, hour=5, shed={"WHEAT": 30}, animals=0)
    orders, _ = brain.sell_orders(ctx)
    assert not any(o[1] == "WHEAT" for o in orders)


def test_compose_caps_and_priority():
    from market.market_brain import MarketBrain as B
    buys = [["HIRE"], ["BUY_SEED", "MELON", 6]]
    sells = [["SELL", "MELON", 7], ["SELL", "EGG", 3]]
    out = B.compose(buys, sells, cap=10)
    assert len(out) == 4 and out[0] == ["SELL", "MELON", 7]
    out = B.compose([["BUY_A", "X", 1]] * 9 + [["BUY_B", "X", 1]],
                    sells, cap=10, purchases_first=True)
    assert len(out) == 10 and all(o[0].startswith("BUY") for o in out)
