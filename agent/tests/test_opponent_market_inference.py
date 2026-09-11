"""Unit tests for opponent market-activity inference.

Covers:
1. Normal opponent sale above $1 floor (inventory rises, correct sales inferred).
2. Our own sale (does not get attributed to opponent).
3. Our own WHEAT BUY_PRODUCT (inventory falls, not attributed to opponent).
4. Opponent WHEAT BUY_PRODUCT (inventory falls beyond town/our activity, inferred as buy, not sale).
5. $1 floor opponent sale (inventory unchanged, no sales fabricated, marked censored/low confidence).
6. Mixed turn (our sale + our buy + town consumption + opponent sale).
7. WHEAT/FERTILIZER buy ambiguity (confidence bounded/moderate).
8. High-confidence non-buyable crop / animal product inference.
"""

import pytest
from config import MARKET_I0, PRODUCTS
from market.price_math import market_price
from state.state_tracker import (
    _STATE,
    _update_drain_ledger,
    get_opp_market_inference,
    get_our_units_bought,
    get_our_units_sold,
    record_our_buy,
    record_our_sale,
    reset_memory,
)


class MockMarket:
    def __init__(self, inventory):
        self.inventory = dict(inventory)


def _make_ctx(inventory, step=1):
    return {
        "step": step,
        "day": step // 24,
        "hour": step % 24,
        "market": MockMarket(inventory),
    }


def _default_inventory(overrides=None):
    inv = {p: MARKET_I0 for p in PRODUCTS}
    if overrides:
        inv.update(overrides)
    return inv


class TestOpponentMarketInference:
    def setup_method(self):
        reset_memory(_STATE)

    def test_1_normal_opponent_sale_above_floor(self):
        """Opponent sells 5 MELON above floor -> detected with high confidence."""
        base_inv = _default_inventory()
        _STATE["prev_inventory"] = dict(base_inv)

        # Opponent sells 5 MELON, inventory increases by 5
        new_inv = dict(base_inv)
        new_inv["MELON"] += 5

        ctx = _make_ctx(new_inv, step=2)  # step=2 has no shop/daily drain
        _update_drain_ledger(ctx, _STATE)

        inf = get_opp_market_inference("MELON")
        assert inf["opponent_visible_sales_estimate"] == 5.0
        assert inf["opponent_sales_lower_bound"] == 5.0
        assert inf["opponent_sales_upper_bound"] == 5.0
        assert inf["confidence"] == "high"
        assert inf["censored"] is False
        assert _STATE["opp_sales_inferred"]["MELON"] == 5.0
        assert _STATE["opp_sales_step"]["MELON"] == 5.0

    def test_2_our_own_sale_not_attributed_to_opponent(self):
        """Our own sale of 10 MELON must not be attributed to opponent."""
        base_inv = _default_inventory()
        _STATE["prev_inventory"] = dict(base_inv)

        # We sell 10 MELON
        record_our_sale("MELON", 10)
        assert get_our_units_sold("MELON") == 10

        # Market inventory increases by 10
        new_inv = dict(base_inv)
        new_inv["MELON"] += 10

        ctx = _make_ctx(new_inv, step=2)
        _update_drain_ledger(ctx, _STATE)

        inf = get_opp_market_inference("MELON")
        assert inf["opponent_visible_sales_estimate"] == 0.0
        assert inf["opponent_sales_lower_bound"] == 0.0
        assert inf["confidence"] == "high"
        assert _STATE["opp_sales_inferred"].get("MELON", 0.0) == 0.0
        assert _STATE["opp_sales_step"].get("MELON", 0.0) == 0.0
        # Step-level sales should be cleared after ledger update
        assert _STATE["our_units_sold_last_step"] == {}

    def test_3_our_own_wheat_buy_not_attributed_to_opponent(self):
        """Our own BUY_PRODUCT for WHEAT must not be attributed to opponent."""
        base_inv = _default_inventory()
        _STATE["prev_inventory"] = dict(base_inv)

        # We buy 15 WHEAT
        record_our_buy("WHEAT", 15)
        assert get_our_units_bought("WHEAT") == 15

        # Market inventory decreases by 15
        new_inv = dict(base_inv)
        new_inv["WHEAT"] -= 15

        ctx = _make_ctx(new_inv, step=2)
        _update_drain_ledger(ctx, _STATE)

        inf = get_opp_market_inference("WHEAT")
        assert inf["opponent_buy_estimate"] == 0.0
        assert inf["opponent_visible_sales_estimate"] == 0.0
        assert _STATE["opp_sales_inferred"].get("WHEAT", 0.0) == 0.0
        # Step-level buys should be cleared after ledger update
        assert _STATE["our_units_bought_last_step"] == {}

    def test_4_opponent_wheat_buy_inferred_as_buy_not_negative_sales(self):
        """Opponent BUY_PRODUCT drops inventory -> inferred as buy, not negative sales."""
        base_inv = _default_inventory()
        _STATE["prev_inventory"] = dict(base_inv)

        # Opponent buys 8 WHEAT
        new_inv = dict(base_inv)
        new_inv["WHEAT"] -= 8

        ctx = _make_ctx(new_inv, step=2)
        _update_drain_ledger(ctx, _STATE)

        inf = get_opp_market_inference("WHEAT")
        assert inf["opponent_buy_estimate"] == 8.0
        assert inf["opponent_visible_sales_estimate"] == 0.0
        assert inf["opponent_sales_lower_bound"] == 0.0
        assert inf["censored"] is False
        # Cumulative sales must NOT become negative or decrement
        assert _STATE["opp_sales_inferred"].get("WHEAT", 0.0) == 0.0
        assert _STATE["opp_sales_step"].get("WHEAT", 0.0) == 0.0

    def test_5_floor_price_sale_censored_and_not_claimed_zero(self):
        """At $1 price floor, sales do not increment inventory -> censored, low confidence."""
        # Find inventory where MELON price reaches floor 1
        floor_inv = MARKET_I0
        while market_price("MELON", floor_inv) > 1:
            floor_inv += 500

        base_inv = _default_inventory({"MELON": floor_inv})
        assert market_price("MELON", base_inv["MELON"]) == 1

        _STATE["prev_inventory"] = dict(base_inv)

        # Opponent sold 20 MELON at floor. Under engine rules, inventory is unchanged.
        new_inv = dict(base_inv)  # delta = 0

        ctx = _make_ctx(new_inv, step=2)
        _update_drain_ledger(ctx, _STATE)

        inf = get_opp_market_inference("MELON")
        assert inf["censored"] is True
        assert inf["confidence"] == "low"
        assert inf["opponent_sales_upper_bound"] is None
        # Does not fabricate fake sales, nor claims high confidence 0 sales
        assert _STATE["opp_sales_inferred"].get("MELON", 0.0) == 0.0

    def test_6_mixed_turn_accounting(self):
        """Mixed turn: our sale + our buy + town consumption + opponent sale."""
        base_inv = _default_inventory()
        _STATE["prev_inventory"] = dict(base_inv)
        _STATE["known_shops"] = ["BAKERY"]  # consumes 1 WHEAT, 1 EGG at prev_step % 4 == 0

        # Step 5: prev_step is 4 (4 % 4 == 0 -> Bakery consumes 1 WHEAT)
        # Our actions at step 4:
        record_our_sale("MELON", 5)
        record_our_buy("WHEAT", 10)

        # Opponent actions:
        # Opponent sells 3 MELON and 7 WHEAT
        # Net deltas:
        # MELON: +5 (ours) + 3 (opp) = +8
        # WHEAT: -1 (bakery) - 10 (our buy) + 7 (opp sale) = -4
        new_inv = dict(base_inv)
        new_inv["MELON"] += 8
        new_inv["WHEAT"] -= 4

        ctx = _make_ctx(new_inv, step=5)
        _update_drain_ledger(ctx, _STATE)

        melon_inf = get_opp_market_inference("MELON")
        assert melon_inf["opponent_visible_sales_estimate"] == 3.0
        assert melon_inf["confidence"] == "high"
        assert _STATE["opp_sales_inferred"]["MELON"] == 3.0

        wheat_inf = get_opp_market_inference("WHEAT")
        assert wheat_inf["opponent_visible_sales_estimate"] == 7.0
        assert wheat_inf["opponent_sales_lower_bound"] == 7.0
        assert _STATE["opp_sales_inferred"]["WHEAT"] == 7.0

    def test_7_wheat_fertilizer_buy_ambiguity(self):
        """Buyable products (WHEAT/FERTILIZER) have bounded confidence due to simultaneous buy/sell possibility."""
        base_inv = _default_inventory()
        _STATE["prev_inventory"] = dict(base_inv)

        # WHEAT drops by 6 without our participation or town drain
        new_inv = dict(base_inv)
        new_inv["WHEAT"] -= 6

        ctx = _make_ctx(new_inv, step=2)
        _update_drain_ledger(ctx, _STATE)

        wheat_inf = get_opp_market_inference("WHEAT")
        assert wheat_inf["opponent_buy_estimate"] == 6.0
        assert wheat_inf["confidence"] == "medium"
        assert wheat_inf["opponent_sales_lower_bound"] == 0.0
        assert wheat_inf["opponent_sales_upper_bound"] is None

        # Contrast with CARROT (non-buyable):
        # A drop on CARROT cannot be a buy; it's an unexplained drain anomaly
        new_inv2 = dict(base_inv)
        new_inv2["CARROT"] -= 6
        reset_memory(_STATE)
        _STATE["prev_inventory"] = dict(base_inv)

        _update_drain_ledger(_make_ctx(new_inv2, step=2), _STATE)
        carrot_inf = get_opp_market_inference("CARROT")
        assert carrot_inf["opponent_buy_estimate"] == 0.0
        assert carrot_inf["confidence"] == "low"  # anomalous negative residual

    def test_8_high_confidence_non_buyable_inference(self):
        """Non-buyable products yield high-confidence observations when above floor."""
        base_inv = _default_inventory()
        _STATE["prev_inventory"] = dict(base_inv)

        non_buyables = ["CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL"]
        new_inv = dict(base_inv)
        for i, prod in enumerate(non_buyables, 1):
            new_inv[prod] += i  # Opponent sold i units

        ctx = _make_ctx(new_inv, step=2)
        _update_drain_ledger(ctx, _STATE)

        for i, prod in enumerate(non_buyables, 1):
            inf = get_opp_market_inference(prod)
            assert inf["opponent_visible_sales_estimate"] == float(i)
            assert inf["opponent_sales_lower_bound"] == float(i)
            assert inf["opponent_sales_upper_bound"] == float(i)
            assert inf["confidence"] == "high"
            assert inf["censored"] is False
            assert _STATE["opp_sales_inferred"][prod] == float(i)
