"""Tests for P2.2-A Day 28 Feed/Liquidation Harmonization isolation and logic."""
import pytest
import sys
import os

# Ensure agent paths are present
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [AGENT_DIR] + [os.path.join(AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from main import reconcile_day28_wheat_market_orders
from market.market_brain import MarketBrain


class FakeFC:
    def __init__(self):
        self.prices = {}

    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        return {"WHEAT": 25.0, "CARROT": 35.0, "TOMATO": 60.0, "MELON": 250.0, "STRAWBERRY": 120.0, "MILK": 160.0, "WOOL": 200.0, "EGG": 50.0, "FEATHER": 70.0, "FERTILIZER": 100.0}.get(product, 25.0)


class MockTile:
    def __init__(self, pos, is_animal=False, fed_today=False, animal="COW"):
        self.pos = pos
        self.is_animal = is_animal
        self.fed_today = fed_today
        self.animal = animal
        self.kind = animal if is_animal else "EMPTY"
        self.yield_units = 0
        self.cared_today = False
        self.consecutive_unfed = 0
        self.fertilized_until_day = -1
        self.is_plant = False


class MockFarm:
    def __init__(self, tiles=None, unlocked=None):
        self._tiles = tiles or []
        self.unlocked = unlocked or {"NW", "NE"}
        self.money = 5000.0
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
    def __init__(self, shed_wheat=0, worker_wheat=0):
        self.shed = {"WHEAT": shed_wheat}
        self.inventories = [{"WHEAT": worker_wheat}] if worker_wheat > 0 else [{}]


class MockMarket:
    def __init__(self):
        self.inventory = {p: 10000.0 for p in ("WHEAT", "CARROT", "TOMATO", "MELON", "STRAWBERRY", "MILK", "WOOL", "EGG", "FEATHER", "FERTILIZER")}


def test_default_flag_is_false():
    """Verify P22A_DAY28_FEED_HARMONIZATION_ENABLED defaults to False."""
    assert config.P22A_DAY28_FEED_HARMONIZATION_ENABLED is False
    assert config.get_p22a_day28_feed_harmonization_enabled() is False


def test_flag_toggle_and_sync():
    """Verify setter toggles flag cleanly and synchronizes with imported modules."""
    try:
        config.set_p22a_day28_feed_harmonization_enabled(True)
        assert config.P22A_DAY28_FEED_HARMONIZATION_ENABLED is True
        assert config.get_p22a_day28_feed_harmonization_enabled() is True

        config.set_p22a_day28_feed_harmonization_enabled(False)
        assert config.P22A_DAY28_FEED_HARMONIZATION_ENABLED is False
        assert config.get_p22a_day28_feed_harmonization_enabled() is False
    finally:
        config.set_p22a_day28_feed_harmonization_enabled(False)


def test_market_brain_day28_state_a_insufficient_wheat():
    """State A: Day 28, some animals unfed, accessible wheat < requirement.

    MarketBrain must protect all accessible wheat from sale (reserved_wheat >= shed_wheat).
    """
    try:
        config.set_p22a_day28_feed_harmonization_enabled(True)

        fc = FakeFC()
        brain = MarketBrain(fc)

        tiles = [MockTile((i, 0), is_animal=True, fed_today=False) for i in range(10)]
        farm = MockFarm(tiles=tiles)
        private = MockPrivate(shed_wheat=4, worker_wheat=2)  # 6 accessible < 10 needed
        market = MockMarket()

        ctx = {
            "day": 28,
            "hour": 12,
            "farm": farm,
            "private": private,
            "market": market,
        }

        orders, details = brain.sell_orders(ctx)
        wheat_sells = [o for o in orders if o[1] == "WHEAT"]
        # Must not sell any wheat because shed_wheat (4) <= reserved_wheat (10 - 2 = 8)
        assert len(wheat_sells) == 0
    finally:
        config.set_p22a_day28_feed_harmonization_enabled(False)


def test_market_brain_day28_state_b_sufficient_wheat_surplus_sold():
    """State B: Day 28, some animals unfed, sufficient accessible wheat exists.

    MarketBrain must protect only remaining requirement (10 - 2 = 8) and permit selling surplus (20 - 8 = 12).
    """
    try:
        config.set_p22a_day28_feed_harmonization_enabled(True)

        fc = FakeFC()
        brain = MarketBrain(fc)

        tiles = [MockTile((i, 0), is_animal=True, fed_today=False) for i in range(10)]
        farm = MockFarm(tiles=tiles)
        private = MockPrivate(shed_wheat=20, worker_wheat=2)  # 20 in shed, 2 in worker; need 10 - 2 = 8 from shed
        market = MockMarket()

        ctx = {
            "day": 28,
            "hour": 12,
            "farm": farm,
            "private": private,
            "market": market,
        }

        orders, details = brain.sell_orders(ctx)
        wheat_sells = [o for o in orders if o[1] == "WHEAT"]
        assert len(wheat_sells) > 0
        total_wheat_sold = sum(o[2] for o in wheat_sells)
        # Sellable stock was 20 - 8 = 12. Total sold must not exceed 12.
        assert total_wheat_sold <= 12
    finally:
        config.set_p22a_day28_feed_harmonization_enabled(False)


def test_market_brain_day28_state_c_all_fed_complete_liquidation():
    """State C: Day 28, all animals already fed today.

    MarketBrain must set reserved_wheat = 0, permitting 100% of shed wheat to be sold.
    """
    try:
        config.set_p22a_day28_feed_harmonization_enabled(True)

        fc = FakeFC()
        brain = MarketBrain(fc)

        tiles = [MockTile((i, 0), is_animal=True, fed_today=True) for i in range(10)]
        farm = MockFarm(tiles=tiles)
        private = MockPrivate(shed_wheat=25, worker_wheat=0)
        market = MockMarket()

        ctx = {
            "day": 28,
            "hour": 16,
            "farm": farm,
            "private": private,
            "market": market,
        }

        orders, details = brain.sell_orders(ctx)
        wheat_sells = [o for o in orders if o[1] == "WHEAT"]
        assert len(wheat_sells) > 0
        total_wheat_sold = sum(o[2] for o in wheat_sells)
        assert total_wheat_sold > 0
        # No artificial buffer: all 25 units are available for sale
        assert total_wheat_sold <= 25
    finally:
        config.set_p22a_day28_feed_harmonization_enabled(False)


def test_day29_full_liquidation_no_feeding():
    """Day 29: No feeding requirement, full liquidation mode."""
    try:
        config.set_p22a_day28_feed_harmonization_enabled(True)

        fc = FakeFC()
        brain = MarketBrain(fc)

        tiles = [MockTile((i, 0), is_animal=True, fed_today=False) for i in range(10)]
        farm = MockFarm(tiles=tiles)
        private = MockPrivate(shed_wheat=30, worker_wheat=0)
        market = MockMarket()

        ctx = {
            "day": 29,
            "hour": 0,
            "farm": farm,
            "private": private,
            "market": market,
        }

        orders, details = brain.sell_orders(ctx)
        wheat_sells = [o for o in orders if o[1] == "WHEAT"]
        assert len(wheat_sells) > 0
    finally:
        config.set_p22a_day28_feed_harmonization_enabled(False)


def test_control_invariance_when_flag_false():
    """When P22A is False, Day 28 behavior exactly matches legacy control (reserved_wheat = 0)."""
    assert config.get_p22a_day28_feed_harmonization_enabled() is False

    fc = FakeFC()
    brain = MarketBrain(fc)

    tiles = [MockTile((i, 0), is_animal=True, fed_today=False) for i in range(10)]
    farm = MockFarm(tiles=tiles)
    private = MockPrivate(shed_wheat=10, worker_wheat=0)
    market = MockMarket()

    ctx = {
        "day": 28,
        "hour": 0,
        "farm": farm,
        "private": private,
        "market": market,
    }

    # In control, endgame=True so reserved_wheat=0, meaning shed wheat (10) is sellable immediately
    orders, details = brain.sell_orders(ctx)
    wheat_sells = [o for o in orders if o[1] == "WHEAT"]
    assert len(wheat_sells) > 0


def test_reconcile_day28_order_netting_wash_trade_elimination():
    """Order reconciliation eliminates simultaneous buy and sell wash trades on Day 28."""
    # Scenario: 10 unfed animals, 2 worker wheat, 4 shed wheat -> need 8 from shed, deficit = 4
    tiles = [MockTile((i, 0), is_animal=True, fed_today=False) for i in range(10)]
    farm = MockFarm(tiles=tiles)
    private = MockPrivate(shed_wheat=4, worker_wheat=2)

    ctx = {
        "day": 28,
        "hour": 0,
        "farm": farm,
        "private": private,
    }

    # If both buy 10 and sell 4 are proposed (a classic wash trade)
    market_orders = [
        ["BUY_PRODUCT", "WHEAT", 10],
        ["SELL", "WHEAT", 4],
        ["SELL", "CARROT", 8],
    ]

    reconciled = reconcile_day28_wheat_market_orders(market_orders, ctx)
    wheat_buys = [o for o in reconciled if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"]
    wheat_sells = [o for o in reconciled if o[0] == "SELL" and o[1] == "WHEAT"]

    # Sell must be eliminated, buy must be net and bounded by actual deficit (4)
    assert len(wheat_sells) == 0
    assert len(wheat_buys) == 1
    assert wheat_buys[0][2] == 4  # Net: 10 - 4 = 6, clamped to actual deficit 4

    # Non-wheat orders must be preserved
    carrot_sells = [o for o in reconciled if o[0] == "SELL" and o[1] == "CARROT"]
    assert len(carrot_sells) == 1
    assert carrot_sells[0][2] == 8


def test_reconcile_day28_no_encroachment_on_unfed_animals():
    """Order reconciliation never executes SELL WHEAT if quantity encroaches on remaining unfed."""
    # 10 unfed animals, 0 worker wheat, 15 shed wheat -> needed = 10, safe sellable = 5
    tiles = [MockTile((i, 0), is_animal=True, fed_today=False) for i in range(10)]
    farm = MockFarm(tiles=tiles)
    private = MockPrivate(shed_wheat=15, worker_wheat=0)

    ctx = {
        "day": 28,
        "hour": 5,
        "farm": farm,
        "private": private,
    }

    market_orders = [
        ["SELL", "WHEAT", 12],
    ]

    reconciled = reconcile_day28_wheat_market_orders(market_orders, ctx)
    wheat_sells = [o for o in reconciled if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 1
    # Clamped to safe sellable (5)
    assert wheat_sells[0][2] == 5
