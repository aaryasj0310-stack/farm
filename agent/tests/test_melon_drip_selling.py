"""Comprehensive tests for MELON sell-side price protection.

Covers Tests A through H:
- Test A: High-price MELON drip selling bounded by marginal price keep fraction
- Test B: Fixed batch target overridden when larger than marginal safe quantity
- Test C: Floor price ($1) MELON held in normal & shed-pressure mode
- Test D: Price recovery after $1 floor hold unfreezes sales
- Test E: Same-turn multi-slice inventory tracking and turn budget enforcement
- Test F: MELON_SEASON_SALE_CAP strictly enforced against cumulative sales
- Test G: Endgame liquidation overrides floor hold on Days 28-29
- Test H: Non-MELON products (WHEAT, CARROT, TOMATO, STRAWBERRY) retain normal behavior
- Diagnostics: Verification of all 8 exposed melon telemetry fields
"""
import copy
import pytest

from config import (
    DRIP_PRICE_KEEP_FRAC,
    MELON_SEASON_SALE_CAP,
    FEED_WHEAT_BUFFER_DAYS,
)
from market.market_brain import MarketBrain
from market.price_math import (
    drip_batch_size,
    inventory_for_price_at_least,
    market_price,
)
from observation_parser import parse_observation
from state.state_tracker import _STATE, get_our_units_sold, record_our_sale, reset_memory


class FakeFC:
    def __init__(self, prices=None, drift=1.0):
        self.prices = prices or {}
        self.drift = drift

    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        base_prices = {
            "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
            "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
        }
        return self.prices.get(product, base_prices.get(product, 50))


def _make_ctx(day=10, hour=1, shed=None, inv=None, animals=0, plants=()):
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


class TestMelonDripSelling:
    def setup_method(self):
        reset_memory(_STATE)

    # ------------------------------------------------------------------
    # Test A — High-price MELON
    # ------------------------------------------------------------------
    def test_a_high_price_melon_sells_marginal_safe_slice(self):
        """Given sufficient MELON inventory and a healthy market price, agent sells a positive safe slice."""
        brain = MarketBrain(FakeFC())
        ctx = _make_ctx(day=10, hour=1, shed={"MELON": 40}, inv={"MELON": 10000})

        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

        assert len(melon_orders) == 1
        qty = melon_orders[0][2]
        assert qty > 0

        # Verify marginal price rule: the last unit sold must quote >= 0.90 * spot
        spot = market_price("MELON", 10000)
        marginal_quote = market_price("MELON", 10000 + qty - 1)
        keep_frac = DRIP_PRICE_KEEP_FRAC["MELON"]
        assert marginal_quote >= int(spot * keep_frac)
        assert details["melon_sell_quantity"] == qty
        assert details["melon_hold_reason"] is None

    # ------------------------------------------------------------------
    # Test B — Fixed batch is too large
    # ------------------------------------------------------------------
    def test_b_fixed_batch_overridden_when_exceeding_drip_budget(self):
        """When batch_target > safe_quantity, emitted quantity <= safe_quantity, NOT the old fixed batch."""
        brain = MarketBrain(FakeFC())
        # On Day 3, normal batch_target is 15
        # Set market inventory to 10100 where spot = 150, threshold = 135, safe budget = 7
        ctx = _make_ctx(day=3, hour=1, shed={"MELON": 50}, inv={"MELON": 10100})

        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

        assert len(melon_orders) == 1
        qty = melon_orders[0][2]

        safe_budget, _ = drip_batch_size("MELON", 10100, DRIP_PRICE_KEEP_FRAC["MELON"])
        assert safe_budget == 7
        assert qty <= safe_budget
        assert qty < 15  # The old fixed batch of 15 is NOT used
        assert qty == 7

    # ------------------------------------------------------------------
    # Test C — MELON at $1
    # ------------------------------------------------------------------
    def test_c_floor_price_melon_is_held_in_normal_mode(self):
        """When MELON spot = $1 in normal mode without emergency, no MELON sell order is emitted."""
        brain = MarketBrain(FakeFC())
        # Market inventory at 10250 puts MELON at $1 floor
        ctx = _make_ctx(day=10, hour=1, shed={"MELON": 40}, inv={"MELON": 10250})

        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

        assert len(melon_orders) == 0
        assert details["melon_sell_quantity"] == 0
        assert details["melon_spot"] == 1
        assert details["melon_safe_quantity"] == 0
        assert details["melon_hold_reason"] == "floor_price_hold"

    def test_c_floor_price_melon_is_held_under_shed_soft_cap_pressure(self):
        """Under normal shed soft-cap pressure (urgency 1), $1 MELON is still held; other goods relieve shed."""
        brain = MarketBrain(FakeFC())
        # shed_total = 70 >= SHED_SOFT_CAP (65) triggers urgency 1
        shed = {"MELON": 40, "WHEAT": 30}
        ctx = _make_ctx(day=10, hour=2, shed=shed, inv={"MELON": 10250, "WHEAT": 10000})

        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]
        wheat_orders = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]

        # MELON at floor is protected
        assert len(melon_orders) == 0
        assert details["melon_hold_reason"] == "floor_price_hold"
        # Wheat is sold to relieve shed pressure
        assert len(wheat_orders) > 0

    # ------------------------------------------------------------------
    # Test D — Price recovery
    # ------------------------------------------------------------------
    def test_d_price_recovery_unfreezes_melon_sales(self):
        """MELON at $1 is held; when town drains market inventory, MELON becomes sellable again."""
        brain = MarketBrain(FakeFC())

        # Step 1: At $1 floor, held
        ctx_floor = _make_ctx(day=10, hour=1, shed={"MELON": 30}, inv={"MELON": 10300})
        orders_floor, details_floor = brain.sell_orders(ctx_floor)
        assert len([o for o in orders_floor if o[1] == "MELON"]) == 0
        assert details_floor["melon_hold_reason"] == "floor_price_hold"

        # Step 2: Town drain recovers inventory back to 10050 (spot = 225)
        ctx_recovered = _make_ctx(day=10, hour=5, shed={"MELON": 30}, inv={"MELON": 10050})
        orders_rec, details_rec = brain.sell_orders(ctx_recovered)
        melon_orders_rec = [o for o in orders_rec if o[1] == "MELON"]

        assert len(melon_orders_rec) == 1
        assert melon_orders_rec[0][2] > 0
        assert details_rec["melon_hold_reason"] is None

    # ------------------------------------------------------------------
    # Test E — Same-turn slices
    # ------------------------------------------------------------------
    def test_e_same_turn_multi_slice_enforces_turn_marginal_budget(self):
        """In emergency relief mode, multiple slices of MELON must respect start-of-turn marginal budget."""
        brain = MarketBrain(FakeFC())
        # Trigger urgency 1 with large MELON shed
        # inv=10100: spot=150, 90% threshold=135, turn safe budget=7
        ctx = _make_ctx(day=10, hour=2, shed={"MELON": 75}, inv={"MELON": 10100})

        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

        total_melon_sold = sum(o[2] for o in melon_orders)
        safe_budget, _ = drip_batch_size("MELON", 10100, 0.90)

        assert total_melon_sold <= safe_budget
        assert total_melon_sold == 7
        # Verify the final marginal quote of the last melon sold is >= 135
        final_marginal = market_price("MELON", 10100 + total_melon_sold - 1)
        assert final_marginal >= 135

    # ------------------------------------------------------------------
    # Test F — Season cap
    # ------------------------------------------------------------------
    def test_f_season_cap_strictly_enforced(self):
        """When MELON_SEASON_SALE_CAP - our_units_sold < safe_qty, sell at most the remaining cap."""
        brain = MarketBrain(FakeFC())
        # Record 148 prior melon sales (cap is 150, so 2 remain)
        record_our_sale("MELON", 148)
        assert get_our_units_sold("MELON") == 148

        ctx = _make_ctx(day=15, hour=1, shed={"MELON": 30}, inv={"MELON": 10000})
        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

        assert len(melon_orders) == 1
        qty = melon_orders[0][2]
        assert qty <= 2
        assert details["melon_sale_cap_remaining"] == 2

        # Record the remaining 2 sales to reach exactly the season cap
        record_our_sale("MELON", qty)
        assert get_our_units_sold("MELON") >= 150

        # Now zero melons can be sold
        ctx2 = _make_ctx(day=15, hour=5, shed={"MELON": 30}, inv={"MELON": 10000})
        orders2, details2 = brain.sell_orders(ctx2)
        melon_orders2 = [o for o in orders2 if o[0] == "SELL" and o[1] == "MELON"]

        assert len(melon_orders2) == 0
        assert details2["melon_hold_reason"] == "season_cap_reached"
        assert details2["melon_sale_cap_remaining"] == 0

    # ------------------------------------------------------------------
    # Test G — Endgame
    # ------------------------------------------------------------------
    def test_g_endgame_liquidation_overrides_floor_hold(self):
        """On Day 29, endgame liquidation sells MELON even if at $1 floor."""
        brain = MarketBrain(FakeFC())
        # Day 29 endgame, MELON at $1
        ctx = _make_ctx(day=29, hour=1, shed={"MELON": 35}, inv={"MELON": 10300})

        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

        assert len(melon_orders) == 1
        assert melon_orders[0][2] == 20  # Endgame slice cap of 20
        assert details["endgame"] is True

    def test_g_midnight_hard_guard_overrides_floor_hold(self):
        """Hour 22 with shed_total > 88 (urgency 2) liquidates MELON to prevent overflow."""
        brain = MarketBrain(FakeFC())
        ctx = _make_ctx(day=15, hour=22, shed={"MELON": 90}, inv={"MELON": 10300})

        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]

        assert len(melon_orders) == 1
        assert melon_orders[0][2] == 20
        assert details["urgency"] == 2

    # ------------------------------------------------------------------
    # Test H — Non-MELON regression
    # ------------------------------------------------------------------
    def test_h_wheat_reserve_and_normal_crops_unaffected(self):
        """Wheat feed reserve and normal crops (CARROT, TOMATO, STRAWBERRY) retain existing behavior."""
        brain = MarketBrain(FakeFC())
        # 2 animals => reserved_wheat = 2 * 4 = 8
        shed = {"WHEAT": 20, "CARROT": 10, "TOMATO": 10, "STRAWBERRY": 10}
        ctx = _make_ctx(day=10, hour=1, shed=shed, animals=2)

        orders, _ = brain.sell_orders(ctx)
        by_prod = {o[1]: o[2] for o in orders if o[0] == "SELL"}

        # Available wheat was 20 - 8 = 12. Batch target is 4.
        assert by_prod.get("WHEAT") == 4
        assert by_prod.get("CARROT") == 4
        assert by_prod.get("TOMATO") == 4
        assert by_prod.get("STRAWBERRY") == 4

    # ------------------------------------------------------------------
    # Diagnostics Verification
    # ------------------------------------------------------------------
    def test_diagnostics_structure_and_completeness(self):
        """Details dictionary exposes all required diagnostic fields."""
        brain = MarketBrain(FakeFC())
        ctx = _make_ctx(day=10, hour=1, shed={"MELON": 25}, inv={"MELON": 10000})

        _, details = brain.sell_orders(ctx)

        expected_keys = [
            "melon_spot",
            "melon_market_inventory",
            "melon_shed_inventory",
            "melon_safe_quantity",
            "melon_sell_quantity",
            "melon_units_sold_this_season",
            "melon_sale_cap_remaining",
            "melon_hold_reason",
        ]
        for k in expected_keys:
            assert k in details, f"Missing top-level key {k}"
            assert k in details["melon_diagnostics"], f"Missing nested key {k}"

        assert details["melon_spot"] == 250
        assert details["melon_market_inventory"] == 10000.0
        assert details["melon_shed_inventory"] == 25
        assert details["melon_safe_quantity"] > 0
        assert details["melon_sell_quantity"] > 0
        assert details["melon_units_sold_this_season"] == 0
        assert details["melon_sale_cap_remaining"] == 150
        assert details["melon_hold_reason"] is None
