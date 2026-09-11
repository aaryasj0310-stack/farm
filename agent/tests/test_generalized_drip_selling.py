"""Comprehensive tests for Generalized Price-Protected Drip Selling.

Demonstrates that large inventories of MELON, WOOL, MILK, or STRAWBERRY cannot
be dumped in a quantity that violates their configured marginal-price floor
during normal selling, while preserving floor-hold, emergency relief, and endgame behavior.
"""
import pytest

from config import (
    DRIP_PRICE_KEEP_FRAC,
    HOLD_AT_FLOOR_PRODUCTS,
    MELON_SEASON_SALE_CAP,
)
from market.market_brain import MarketBrain, DRIP_PROTECTED_PRODUCTS
from market.price_math import (
    market_price,
    safe_drip_budget,
    inventory_at_price,
)
from observation_parser import parse_observation
from state.state_tracker import reset_memory


@pytest.fixture(autouse=True)
def clean_memory():
    reset_memory()
    yield
    reset_memory()


class FakeFC:
    def __init__(self, prices=None):
        self.prices = prices or {}

    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        base_prices = {
            "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
            "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
        }
        return self.prices.get(product, base_prices.get(product, 50))


def _make_ctx(day=10, hour=1, shed=None, inv=None):
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    inventory = {p: 10000 for p in products}
    if inv:
        inventory.update(inv)

    board = 10
    tiles = [[None] * board for _ in range(board)]
    for y in range(board):
        for x in range(board):
            if x >= 5 or y >= 5:
                tiles[y][x] = "LOCKED"

    farm = {"money": 5000, "tiles": tiles, "farmer": [4, 4], "hands": [],
            "unlocked": ["NW"]}
    private = {"shed": shed or {}, "inventories": [{}], "seeds": {}}
    market = {"inventory": inventory}
    town = {"shops": {}}
    obs = {"day": day, "hour": hour, "farms": [farm, farm], "private": private,
           "market": market, "town": town, "step": day * 24 + hour}
    return parse_observation(obs)


@pytest.mark.parametrize("prod", ["MELON", "WOOL", "MILK", "STRAWBERRY"])
def test_large_inventory_cannot_breach_marginal_price_floor(prod):
    """A large inventory (50 units) of a protected product cannot be dumped in normal
    selling in a quantity that violates its configured keep-fraction marginal price.
    """
    reset_memory()
    brain = MarketBrain(FakeFC())
    # Start at base market inventory (10,000)
    ctx = _make_ctx(day=10, hour=1, shed={prod: 50}, inv={prod: 10000})

    orders, _ = brain.sell_orders(ctx)
    prod_orders = [o for o in orders if o[0] == "SELL" and o[1] == prod]

    assert len(prod_orders) >= 1, f"Expected sell orders for {prod}"
    total_qty = sum(o[2] for o in prod_orders)

    keep_frac = DRIP_PRICE_KEEP_FRAC[prod]
    spot_init = market_price(prod, 10000)
    min_marginal_price = max(2, int(spot_init * keep_frac))

    # Marginal price of the last unit sold must remain >= min_marginal_price
    marginal_quote = market_price(prod, 10000 + total_qty)
    assert marginal_quote >= min_marginal_price, (
        f"{prod}: sold {total_qty} units, marginal quote dropped to {marginal_quote} "
        f"which is below floor {min_marginal_price} (spot={spot_init}, keep_frac={keep_frac})"
    )

    # And selling 1 more unit beyond total_qty should either hit the batch target
    # or drop the quote below min_marginal_price
    safe_budget = safe_drip_budget(prod, 10000, keep_frac, spot_init)
    assert total_qty <= safe_budget


@pytest.mark.parametrize("prod", ["MELON", "WOOL", "MILK", "STRAWBERRY"])
def test_fragile_goods_held_at_one_dollar_floor_in_normal_mode(prod):
    """When market spot is at the $1 floor, normal mode holds the good and emits 0 sell orders."""
    reset_memory()
    brain = MarketBrain(FakeFC())
    # Heavy glut inventory where price is floored at $1
    glut_inv = {prod: 15000}
    ctx = _make_ctx(day=10, hour=1, shed={prod: 20}, inv=glut_inv)

    assert market_price(prod, 15000) == 1

    orders, _ = brain.sell_orders(ctx)
    prod_orders = [o for o in orders if o[0] == "SELL" and o[1] == prod]

    assert len(prod_orders) == 0, f"Expected {prod} to be held at $1 floor, but got {prod_orders}"


@pytest.mark.parametrize("prod", ["MELON", "WOOL", "MILK", "STRAWBERRY"])
def test_endgame_liquidation_overrides_drip_protection_and_floor(prod):
    """On Day 28 (endgame liquidation), price protection and floor holds are lifted."""
    reset_memory()
    brain = MarketBrain(FakeFC())
    # Even at $1 floor and huge stock, endgame dumps up to slice capacity (20)
    glut_inv = {prod: 15000}
    ctx = _make_ctx(day=28, hour=1, shed={prod: 30}, inv=glut_inv)

    orders, details = brain.sell_orders(ctx)
    prod_orders = [o for o in orders if o[0] == "SELL" and o[1] == prod]

    assert len(prod_orders) >= 1
    # Endgame slice size is 20
    assert prod_orders[0][2] == 20
    assert details["endgame"] is True


def test_emergency_relief_respects_drip_sizing_for_fragile_goods():
    """In emergency shed relief (shed >= 65), multi-slice selling updates live inventory
    and never sells past the safe marginal price limit.
    """
    reset_memory()
    brain = MarketBrain(FakeFC())
    # Overfill shed with 70 WOOL to trigger emergency relief
    ctx = _make_ctx(day=10, hour=2, shed={"WOOL": 70}, inv={"WOOL": 10000})

    orders, details = brain.sell_orders(ctx)
    wool_orders = [o for o in orders if o[0] == "SELL" and o[1] == "WOOL"]

    assert len(wool_orders) >= 1
    total_wool_sold = sum(o[2] for o in wool_orders)

    keep_frac = DRIP_PRICE_KEEP_FRAC["WOOL"]
    spot_init = market_price("WOOL", 10000)
    min_marginal_price = max(2, int(spot_init * keep_frac))

    marginal_quote = market_price("WOOL", 10000 + total_wool_sold)
    assert marginal_quote >= min_marginal_price, (
        f"Emergency relief sold {total_wool_sold} WOOL, but marginal price dropped to {marginal_quote} < {min_marginal_price}"
    )


def test_melon_seasonal_cap_preserved():
    """Melon seasonal cap (150) continues to be respected even when safe drip budget is large."""
    reset_memory()
    from state.state_tracker import record_our_sale
    # Record 145 melons already sold
    record_our_sale("MELON", 145)

    brain = MarketBrain(FakeFC())
    ctx = _make_ctx(day=10, hour=1, shed={"MELON": 20}, inv={"MELON": 10000})

    orders, details = brain.sell_orders(ctx)
    melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

    assert len(melon_orders) == 1
    # Only 5 melons can be sold before hitting the 150 seasonal cap
    assert melon_orders[0][2] <= 5
