"""W-market tests: EndgameLiquidator policy."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market.market_brain import MarketBrain
from strategy.endgame_liquidator import EndgameLiquidator

from tests.test_market_brain import FakeFC, make_ctx


def test_flat_prices_liquidate_everything_by_day28():
    liq = EndgameLiquidator(FakeFC())
    for prod in ("MELON", "WHEAT", "EGG"):
        assert liq.should_liquidate_now(prod, 28) is True


def test_rising_uplift_defers_but_floor_forces_dump():
    class Rising(FakeFC):
        def __init__(self, floors=None):
            super().__init__()
            self.floors = floors or {}

        def expected_price(self, product, day):
            base = {"MELON": 250}.get(product, 50)
            return base * (1.0 + 0.05 * day)      # strong uplift to d29

    liq = EndgameLiquidator(Rising())
    assert liq.should_liquidate_now("MELON", 26) is False   # waiting pays

    # same uplift, but 40% chance of being at the floor on day 29 -> dump
    liq_floor = EndgameLiquidator(Rising(floors={"MELON": 0.40}))
    assert liq_floor.should_liquidate_now("MELON", 26) is True


def test_plan_emits_round_robin_sells_under_cap():
    liq = EndgameLiquidator(FakeFC())
    shed = {"WHEAT": 30, "MELON": 20, "EGG": 10, "FERTILIZER": 5}
    ctx = make_ctx(day=28, hour=1, shed=shed)
    orders, details = liq.plan(ctx, max_slots=6)
    assert len(orders) <= 6
    sold = {o[1] for o in orders}
    assert "WHEAT" in sold and "MELON" in sold     # biggest stocks covered
    assert details["liquidated_products"]


def test_harvest_priorities_lists_yielding_tiles():
    liq = EndgameLiquidator(FakeFC())
    ripe = {"kind": "PLANT", "crop": "MELON", "planted_day": 0,
            "watered_today": True, "consecutive_unwatered": 0,
            "yield_units": 4, "fertilized_until_day": -1}
    ctx = make_ctx(day=28, hour=0, plants=[(2, 2, ripe)])
    prio = liq.harvest_priorities(ctx)
    assert any(p["pos"] == (2, 2) and p["crop"] == "MELON" and p["units"] == 4
               for p in prio)
