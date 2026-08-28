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


def test_hour0_emits_nothing_except_purchases():
    brain = MarketBrain(FakeFC())
    ctx = make_ctx(hour=0, shed={"MELON": 30})
    orders, details = brain.sell_orders(ctx)
    assert orders == []
    assert details["reason"] == "hour0_purchases"


def test_batch_sells_respect_phase_batch_targets():
    brain = MarketBrain(FakeFC())
    # Phase 1 (day 3): batch target 15
    ctx_p1 = make_ctx(day=3, hour=1, shed={"MELON": 50})
    orders_p1, _ = brain.sell_orders(ctx_p1)
    assert orders_p1[0][2] == 15

    # Phase 3 (day 15): batch target 4
    ctx_p3 = make_ctx(day=15, hour=1, shed={"MELON": 50})
    orders_p3, _ = brain.sell_orders(ctx_p3)
    assert orders_p3[0][2] == 4


def test_compose_caps_and_priority():
    from market.market_brain import MarketBrain as B
    buys = [["HIRE"], ["BUY_SEED", "MELON", 6]]
    sells = [["SELL", "MELON", 7], ["SELL", "EGG", 3]]
    out = B.compose(buys, sells, cap=10)
    assert len(out) == 4 and out[0] == ["SELL", "MELON", 7]
    out = B.compose([["BUY_A", "X", 1]] * 9 + [["BUY_B", "X", 1]],
                    sells, cap=10, purchases_first=True)
    assert len(out) == 10 and all(o[0].startswith("BUY") for o in out)


def test_endgame_overrides_delay_sell():
    """Day 29 liquidates everything despite delay_sell flag."""
    from strategy.opponent_advisor import OpponentAdvice
    brain = MarketBrain(FakeFC())
    delay_advice = OpponentAdvice(delay_sell=["MELON"])

    # Day 10: delay_sell holds MELON
    ctx_mid = make_ctx(day=10, hour=1, shed={"MELON": 30})
    orders_mid, _ = brain.sell_orders(ctx_mid, opp_advice=delay_advice)
    assert not any(o[1] == "MELON" for o in orders_mid), \
        "delay_sell should hold MELON on day 10"

    # Day 29: delay_sell is overridden — MELON must be sold
    ctx_end = make_ctx(day=29, hour=1, shed={"MELON": 30})
    orders_end, _ = brain.sell_orders(ctx_end, opp_advice=delay_advice)
    assert any(o[1] == "MELON" for o in orders_end), \
        "day 29 must liquidate despite delay_sell"
