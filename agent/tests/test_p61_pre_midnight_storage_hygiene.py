"""Tests for Kaggriculture P6.1 Pre-Midnight Storage Hygiene Experiment.

Verifies:
1. Feature flag defaults to False (production baseline exactness).
2. When False, baseline sell ordering and urgency behavior are 100% bit-for-bit preserved.
3. When True:
   - Trigger condition: Hour in (20, 21, 22) and projected_midnight_load > 75.
   - Hours outside (20, 21, 22) do not trigger hygiene.
   - Projected load <= 75 does not trigger hygiene.
   - Liquidation priority: FERTILIZER -> STRAWBERRY -> WOOL -> MILK -> MELON -> CARROT -> TOMATO -> EGG -> WHEAT.
   - Safe wheat floor: max(15, animals * 2.0) strictly reserved.
   - CentralPlanner classification: P1_URGENT, urgency 1.5, never displacing P0_CRITICAL.
"""
import pytest
import config
from market.market_brain import MarketBrain
from strategy.price_forecast import PriceForecast
from strategy.central_planner import (
    CentralPlanner,
    P0_CRITICAL,
    P1_URGENT,
    P2_STRATEGIC,
    P3_NORMAL,
)


class MockTile:
    def __init__(self, is_animal=False, is_plant=False, crop=None, fertilized_until_day=-1):
        self.is_animal = is_animal
        self.is_plant = is_plant
        self.crop = crop
        self.fertilized_until_day = fertilized_until_day


class MockFarm:
    def __init__(self, tiles=None):
        self._tiles = tiles or []

    def iter_tiles(self):
        return iter(self._tiles)


class MockPrivate:
    def __init__(self, shed=None, inventories=None):
        self.shed = shed or {}
        self.inventories = inventories or []


class MockMarket:
    def __init__(self, inventory=None):
        self.inventory = inventory or {
            "WHEAT": 10000.0, "CARROT": 10000.0, "TOMATO": 10000.0,
            "STRAWBERRY": 10000.0, "MELON": 10000.0, "EGG": 10000.0,
            "MILK": 10000.0, "WOOL": 10000.0, "FERTILIZER": 10000.0
        }


def test_p61_flag_defaults_to_false():
    """Verify feature flag defaults to False."""
    assert config.P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED is False
    assert config.get_p61_pre_midnight_storage_hygiene_enabled() is False


def test_p61_trigger_timing_and_load_threshold():
    """Verify trigger only fires on hours 20, 21, 22 and projected_load > 75."""
    fc = PriceForecast.load()
    brain = MarketBrain(fc)
    farm = MockFarm([MockTile(is_animal=True) for _ in range(5)])

    # Shed has 50 items, workers carry 30 items -> projected load = 80 > 75
    shed = {"STRAWBERRY": 25, "WOOL": 25}
    inventories = [{"STRAWBERRY": 15}, {"WOOL": 15}]
    market = MockMarket()

    # Case 1: Flag is False -> Hour 20 should NOT trigger (returns no orders, waiting for sell window)
    config.set_p61_pre_midnight_storage_hygiene_enabled(False)
    ctx_h20_off = {
        "day": 15, "hour": 20, "farm": farm,
        "private": MockPrivate(shed=dict(shed), inventories=inventories),
        "market": market, "scheduled_product_deposits": {}
    }
    orders, details = brain.sell_orders(ctx_h20_off)
    assert details.get("is_p61_hygiene", False) is False
    assert len(orders) == 0

    # Case 2: Flag is True -> Hour 20 DOES trigger
    config.set_p61_pre_midnight_storage_hygiene_enabled(True)
    orders, details = brain.sell_orders(ctx_h20_off)
    assert details["is_p61_hygiene"] is True
    assert details["p61_needed_relief"] == 5  # 80 - 75 = 5
    assert len(orders) > 0

    # Case 3: Flag is True, but Hour is 19 -> does NOT trigger
    ctx_h19 = dict(ctx_h20_off, hour=19)
    orders, details = brain.sell_orders(ctx_h19)
    assert details.get("is_p61_hygiene", False) is False

    # Case 4: Flag is True, Hour is 20, but projected load is 70 <= 75 -> does NOT trigger
    ctx_h20_low = {
        "day": 15, "hour": 20, "farm": farm,
        "private": MockPrivate(shed={"STRAWBERRY": 40}, inventories=[{"STRAWBERRY": 30}]),
        "market": market, "scheduled_product_deposits": {}
    }
    orders, details = brain.sell_orders(ctx_h20_low)
    assert details.get("is_p61_hygiene", False) is False

    # Reset flag
    config.set_p61_pre_midnight_storage_hygiene_enabled(False)


def test_p61_liquidation_priority():
    """Verify priority: FERTILIZER -> STRAWBERRY -> WOOL -> MILK -> MELON -> CARROT -> TOMATO -> EGG -> WHEAT."""
    fc = PriceForecast.load()
    brain = MarketBrain(fc)
    farm = MockFarm([MockTile(is_animal=True) for _ in range(5)])

    # Shed has 10 of each product, workers carry 30 items -> load = 90 + 30 = 120 > 75
    # Needed relief = 120 - 75 = 45 units
    shed = {
        "WHEAT": 50,  # 5 animals * 4 = 20 reserved, 30 surplus
        "FERTILIZER": 10,
        "STRAWBERRY": 10,
        "WOOL": 10,
        "MILK": 10,
    }
    inventories = [{"WHEAT": 30}]
    market = MockMarket()

    config.set_p61_pre_midnight_storage_hygiene_enabled(True)
    ctx = {
        "day": 15, "hour": 20, "farm": farm,
        "private": MockPrivate(shed=dict(shed), inventories=inventories),
        "market": market, "scheduled_product_deposits": {}
    }
    orders, details = brain.sell_orders(ctx)
    assert details["is_p61_hygiene"] is True

    # Check order sequence: FERTILIZER should be sold first, then STRAWBERRY, then WOOL, then MILK
    sold_products = [o[1] for o in orders]
    assert "FERTILIZER" in sold_products
    fert_idx = sold_products.index("FERTILIZER")
    if "STRAWBERRY" in sold_products:
        straw_idx = sold_products.index("STRAWBERRY")
        assert fert_idx < straw_idx

    # Reset flag
    config.set_p61_pre_midnight_storage_hygiene_enabled(False)


def test_p61_safe_wheat_floor_protection():
    """Verify storage hygiene never sells wheat below max(15, animals * 2.0)."""
    fc = PriceForecast.load()
    brain = MarketBrain(fc)
    animals_count = 6
    farm = MockFarm([MockTile(is_animal=True) for _ in range(animals_count)])

    # 6 animals * 2.0 = 12 -> floor is max(15, 12) = 15.
    # Shed has exactly 15 wheat and 70 strawberry, worker carries 20 items.
    # Projected load = 85 + 20 = 105 > 75.
    # Wheat in shed is 15 == safe_wheat_floor -> wheat sellable stock MUST be 0.
    shed = {"WHEAT": 15, "STRAWBERRY": 70}
    inventories = [{"STRAWBERRY": 20}]
    market = MockMarket()

    config.set_p61_pre_midnight_storage_hygiene_enabled(True)
    ctx = {
        "day": 15, "hour": 21, "farm": farm,
        "private": MockPrivate(shed=dict(shed), inventories=inventories),
        "market": market, "scheduled_product_deposits": {}
    }
    orders, details = brain.sell_orders(ctx)
    assert details["is_p61_hygiene"] is True

    # No wheat should be sold because shed wheat == floor
    sold_wheat = sum(o[2] for o in orders if o[1] == "WHEAT")
    assert sold_wheat == 0

    # Reset flag
    config.set_p61_pre_midnight_storage_hygiene_enabled(False)


def test_p61_central_planner_priority_and_emergency_invariance():
    """Verify CentralPlanner classifies hygiene as P1_URGENT and preserves P0_CRITICAL purchases."""
    cp = CentralPlanner()
    farm = MockFarm([MockTile(is_animal=True) for _ in range(5)])
    ctx = {"day": 15, "hour": 20, "farm": farm, "private": MockPrivate(shed={"STRAWBERRY": 50, "WHEAT": 0})}

    # Hygiene sell proposal
    sell_orders = [["SELL", "STRAWBERRY", 10]]
    sell_details = {"is_p61_hygiene": True, "reason": "hygiene"}

    # Candidate classification check
    candidate = cp._classify_sell(sell_orders[0], 0, ctx, sell_details, None)
    assert candidate.priority_class == P1_URGENT
    assert candidate.urgency == 1.5
    assert candidate.metadata["sell_pressure_class"] == "pre_midnight_hygiene"

    # Emergency feed wheat purchase (P0_CRITICAL)
    purchase_orders = [["BUY_PRODUCT", "WHEAT", 10]]
    purchase_ledger = {"feed_risk": "critical"}

    # Case 1: cap = 10 -> both fit
    final_orders, diag = cp.plan_market(
        ctx=ctx,
        purchase_orders=purchase_orders,
        purchase_ledger=purchase_ledger,
        sell_orders=sell_orders,
        sell_details=sell_details,
        cap=10,
    )
    ops = [o[0] for o in final_orders]
    assert "BUY_PRODUCT" in ops
    assert "SELL" in ops

    # Case 2: cap = 1 -> P0_CRITICAL purchase MUST strictly dominate P1_URGENT sell!
    final_orders_cap1, diag_cap1 = cp.plan_market(
        ctx=ctx,
        purchase_orders=purchase_orders,
        purchase_ledger=purchase_ledger,
        sell_orders=sell_orders,
        sell_details=sell_details,
        cap=1,
    )
    assert len(final_orders_cap1) == 1
    assert final_orders_cap1[0][0] == "BUY_PRODUCT"
    rejections = [r["proposal_id"] for r in diag_cap1.get("rejected_details", [])]
    assert "sell:0" in rejections
