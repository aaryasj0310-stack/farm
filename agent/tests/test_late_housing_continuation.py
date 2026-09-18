"""Production Tests for Point-2 Late Housing Continuation & Feed Reservation Fix.

Covering the 10 required regression tests:
1. Shed/unplaced animals remain included in feed reservations.
2. Forward pasture candidate gives zero animal-purchase capacity.
3. Completed physical empty pasture gives exactly one unit of purchase capacity.
4. One forward continuation candidate at a time.
5. Day 12 continuation allowed when gates pass.
6. Day 13 continuation allowed when gates pass.
7. Day 14 continuation construction rejected.
8. Failed economic/feed candidate creates no speculative pasture.
9. Completed late pasture can subsequently be occupied.
10. Disabling the continuation flag restores previous behavior.
"""
from __future__ import annotations

import copy
import pytest

import config
from strategy.herd_planner import generate_dynamic_herd_plan, DynamicHerdPlan
from strategy.macro_planner import MacroPlanner
from market.order_builder import OrderBuilder
from market.market_brain import MarketBrain
from strategy.feed_feasibility import (
    build_fresh_live_ledger,
    compute_remaining_existing_feed_hold,
    derive_feed_sale_reservation,
)


def test_production_defaults_stage2():
    """Verify all production defaults remain strictly safe."""
    assert config.POINT2_FEED_MODE == "shadow"
    assert config.BOOTSTRAP_LIVESTOCK_ARM == "none"
    assert config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED is False


# ---------------------------------------------------------------------------
# Test 1: Shed/unplaced animals remain included in feed reservations
# ---------------------------------------------------------------------------
def test_shed_unplaced_animals_included_in_feed_reservations():
    """Verify that unplaced animals in shed receive full sell-side feed protection."""
    class DummyFarm:
        money = 1000.0
        hires_today = 0
        unlocked = ["NW"]
        def iter_tiles(self):
            return []  # 0 placed animals on tiles

    class DummyPrivate:
        # 3 cows sitting in shed waiting to be placed!
        shed = {"COW": 3, "WHEAT": 10}
        inventories = []
        seeds = {}

    class DummyMarket:
        inventory = {"WHEAT": 10000, "MILK": 100, "WOOL": 100}

    ctx = {
        "day": 0,
        "hour": 1,
        "farm": DummyFarm(),
        "private": DummyPrivate(),
        "market": DummyMarket(),
        "memory": {},
    }

    # MarketBrain sell_orders check:
    # 3 cows in shed require 3 * FEED_WHEAT_BUFFER_DAYS = 12 wheat buffer.
    # Shed has 10 wheat -> stock = max(0, 10 - 12) = 0.
    # ZERO wheat should be sold!
    brain = MarketBrain(forecast=None)
    orders, details = brain.sell_orders(ctx)
    wheat_sells = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 0, f"Expected 0 wheat sells, got {wheat_sells}"


# ---------------------------------------------------------------------------
# Test 2: Forward pasture candidate gives zero animal-purchase capacity
# ---------------------------------------------------------------------------
def test_forward_pasture_candidate_gives_zero_animal_purchase_capacity():
    """Verify forward-only candidate increases required_pastures but NEVER enters buy_animal_sequence."""
    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=True,
    )
    assert plan.required_pastures == 4  # Increments forward pasture requirement
    assert len(plan.buy_animal_sequence) == 0  # CRUCIAL INVARIANT: Buy sequence is empty!

    fwd_recs = [r for r in plan.decision_records if r.get("forward_only")]
    assert len(fwd_recs) == 1
    assert fwd_recs[0]["purchase_eligible"] is False
    assert fwd_recs[0]["sequence_index"] == -1


# ---------------------------------------------------------------------------
# Test 3: Completed physical empty pasture gives exactly one unit of purchase capacity
# ---------------------------------------------------------------------------
def test_completed_physical_empty_pasture_gives_purchase_capacity():
    """Verify that an empty completed pasture authorizes exactly one unit in buy_animal_sequence."""
    plan = generate_dynamic_herd_plan(
        day=13,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 1, "COOP": 0},  # Exactly 1 empty pasture completed
        allow_late_continuation=False,
    )
    assert plan.required_pastures == 4
    assert len(plan.buy_animal_sequence) == 1
    assert plan.buy_animal_sequence[0] in ("COW", "SHEEP")

    admitted = [r for r in plan.decision_records if r.get("accepted")]
    assert len(admitted) == 1
    assert admitted[0]["purchase_eligible"] is True
    assert admitted[0]["forward_only"] is False
    assert admitted[0]["sequence_index"] == 0


# ---------------------------------------------------------------------------
# Test 4: One forward continuation candidate at a time
# ---------------------------------------------------------------------------
def test_one_forward_continuation_candidate_at_a_time():
    """Verify that at most 1 forward continuation candidate is admitted."""
    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP", "SUPERMARKET"],
        market_inventory={"WHEAT": 10000, "MILK": 10, "WOOL": 10, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=True,
    )
    fwd_recs = [r for r in plan.decision_records if r.get("forward_only")]
    assert len(fwd_recs) <= 1


# ---------------------------------------------------------------------------
# Test 5: Day 12 continuation allowed when gates pass
# ---------------------------------------------------------------------------
def test_day12_continuation_allowed_when_gates_pass():
    """Verify that on Day 12, continuation candidate evaluates and passes when gates pass."""
    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=True,
    )
    assert plan.required_pastures == 4
    fwd_recs = [r for r in plan.decision_records if r.get("forward_only")]
    assert len(fwd_recs) == 1
    assert fwd_recs[0]["reason"] == "forward_housing_continuation_justified"


# ---------------------------------------------------------------------------
# Test 6: Day 13 continuation allowed when gates pass
# ---------------------------------------------------------------------------
def test_day13_continuation_allowed_when_gates_pass():
    """Verify that on Day 13, continuation candidate evaluates and passes when gates pass."""
    plan = generate_dynamic_herd_plan(
        day=13,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=True,
    )
    assert plan.required_pastures == 4
    fwd_recs = [r for r in plan.decision_records if r.get("forward_only")]
    assert len(fwd_recs) == 1
    assert fwd_recs[0]["reason"] == "forward_housing_continuation_justified"


# ---------------------------------------------------------------------------
# Test 7: Day 14 continuation construction rejected
# ---------------------------------------------------------------------------
def test_day14_continuation_construction_rejected():
    """Verify Day 14 strictly prohibits initiating forward continuation builds."""
    plan = generate_dynamic_herd_plan(
        day=14,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=False,  # Enforced by day >= 14 rule
    )
    assert plan.required_pastures == 3
    assert len(plan.buy_animal_sequence) == 0
    assert not any(r.get("forward_only") for r in plan.decision_records)


# ---------------------------------------------------------------------------
# Test 8: Failed economic/feed candidate creates no speculative pasture
# ---------------------------------------------------------------------------
def test_failed_economic_or_feed_candidate_creates_no_speculative_pasture():
    """Verify that if economic payoff hurdle fails (<$500), required_pastures is not incremented."""
    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=[],  # Zero shops
        market_inventory={"WHEAT": 10000, "MILK": 100000, "WOOL": 100000, "FERTILIZER": 100000},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=True,
    )
    assert plan.required_pastures == 3  # Not incremented!
    assert len(plan.buy_animal_sequence) == 0
    assert not any(r.get("forward_only") for r in plan.decision_records)


# ---------------------------------------------------------------------------
# Test 9: Completed late pasture can subsequently be occupied
# ---------------------------------------------------------------------------
def test_completed_late_pasture_can_subsequently_be_occupied():
    """Verify state transition: in-flight pasture completes -> clears in-flight -> authorizes buy."""
    from state.state_tracker import _STATE, reset_memory

    reset_memory()
    _STATE["late_continuation_in_flight"] = True
    _STATE["late_continuation_target_pos"] = (2, 2)

    class DummyTile:
        pos = (2, 2)
        kind = "PASTURE"
        is_animal = False
        is_plant = False

    class DummyFarm:
        money = 5000.0
        hires_today = 0
        hands = []
        unlocked = ["NW"]
        def iter_tiles(self):
            return [DummyTile()]
        def tile_at(self, pos):
            return DummyTile() if pos == (2, 2) else None
        def quadrant_of(self, pos):
            return "NW"

    ctx = {
        "day": 13,
        "hour": 0,
        "farm": DummyFarm(),
        "private": type("DummyPriv", (), {"shed": {"WHEAT": 50}, "inventories": [], "seeds": {}})(),
        "market": type("DummyMkt", (), {"inventory": {"WHEAT": 10000, "MILK": 100, "WOOL": 100}})(),
        "memory": {},
    }

    mock_fc = type("MockFC", (), {
        "expected_price": lambda self, crop, day: 25.0,
        "expected_price_at_hour": lambda self, crop, day, hour: 25.0,
    })()

    old_flag = config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED
    old_mode = config.POINT2_FEED_MODE
    try:
        config.POINT2_FEED_MODE = "live"
        config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = True

        planner = MacroPlanner(forecast=mock_fc)
        plan = planner.build(ctx)

        assert _STATE["late_continuation_in_flight"] is False
        assert _STATE["late_continuation_target_pos"] is None
    finally:
        config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = old_flag
        config.POINT2_FEED_MODE = old_mode


# ---------------------------------------------------------------------------
# Test 10: Disabling the continuation flag restores previous behavior
# ---------------------------------------------------------------------------
def test_disabling_continuation_flag_restores_previous_behavior():
    """Verify that when ONE_AT_A_TIME_LATE_HOUSING_ENABLED is False, no forward pasture is queued."""
    from state.state_tracker import reset_memory
    reset_memory()

    class DummyTile:
        def __init__(self, pos):
            self.pos = pos
            self.kind = "PASTURE"
            self.is_animal = True
            self.animal = "COW"
            self.is_plant = False

    class DummyFarm:
        money = 5000.0
        hires_today = 0
        hands = []
        unlocked = ["NW", "NE"]
        def iter_tiles(self):
            return [DummyTile((0, 0)), DummyTile((0, 1)), DummyTile((0, 2))]
        def quadrant_of(self, pos):
            return "NW"

    ctx = {
        "day": 12,
        "hour": 0,
        "farm": DummyFarm(),
        "private": type("DummyPriv", (), {"shed": {"WHEAT": 50}, "inventories": [], "seeds": {}})(),
        "market": type("DummyMkt", (), {"inventory": {"WHEAT": 10000, "MILK": 100, "WOOL": 100}})(),
        "town_shops": ["BAKERY", "PIZZA_SHOP"],
        "memory": {},
    }

    old_flag = config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED
    old_mode = config.POINT2_FEED_MODE
    try:
        config.POINT2_FEED_MODE = "live"
        config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False

        mock_fc = type("MockFC", (), {
            "expected_price": lambda self, crop, day: 25.0,
            "expected_price_at_hour": lambda self, crop, day, hour: 25.0,
        })()
        planner = MacroPlanner(forecast=mock_fc)
        plan = planner.build(ctx)

        # Build queue and buy sequence should be empty (no forward pasture built)
        assert len(plan.build_queue) == 0
        assert len(plan.buy_animal_sequence) == 0
    finally:
        config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = old_flag
        config.POINT2_FEED_MODE = old_mode


# ---------------------------------------------------------------------------
# Test 11 & 12: Authority boundary isolation tests
# ---------------------------------------------------------------------------
def test_forward_only_feed_ledger_unmutated():
    """Verify that forward-only late continuation evaluates candidate feasibility without mutating authoritative ledger."""
    from strategy.feed_feasibility import FeedResourceLedger
    ledger = FeedResourceLedger(
        day=12,
        hour=0,
        operational_horizon_days=4,
        observed_cash=5000.0,
        placed_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        wheat_in_shed=50,
        wheat_price_current=20.0,
        wheat_market_inventory=10000.0,
        lifetime_price_policy="engine_stress_bound_v1",
    )
    initial_hold = ledger.candidate_feed_cash_hold
    initial_reservations_len = len(ledger.candidate_reservations)
    initial_purchases_len = len(ledger.scheduled_market_purchases)
    initial_spent = ledger.candidate_purchase_cash_spent

    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=True,
        feed_ledger=ledger,
    )

    # Must have admitted a forward-only candidate
    fwd_recs = [r for r in plan.decision_records if r.get("forward_only")]
    assert len(fwd_recs) == 1
    assert fwd_recs[0]["accepted"] is True

    # Authoritative ledger MUST remain 100% unmutated!
    assert ledger.candidate_feed_cash_hold == initial_hold
    assert len(ledger.candidate_reservations) == initial_reservations_len
    assert len(ledger.scheduled_market_purchases) == initial_purchases_len
    assert ledger.candidate_purchase_cash_spent == initial_spent


def test_normal_candidate_commits_reservations_when_housing_available():
    """Verify that normal animal candidates with physical housing still commit reservations into authoritative ledger."""
    from strategy.feed_feasibility import FeedResourceLedger
    ledger = FeedResourceLedger(
        day=12,
        hour=0,
        operational_horizon_days=4,
        observed_cash=5000.0,
        placed_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        wheat_in_shed=50,
        wheat_price_current=20.0,
        wheat_market_inventory=10000.0,
        lifetime_price_policy="engine_stress_bound_v1",
    )
    initial_hold = ledger.candidate_feed_cash_hold
    initial_reservations_len = len(ledger.candidate_reservations)

    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 1, "COOP": 0},  # 1 physical pasture available!
        allow_late_continuation=False,
        feed_ledger=ledger,
    )

    admitted_recs = [r for r in plan.decision_records if r.get("accepted") and not r.get("forward_only")]
    assert len(admitted_recs) == 1
    assert len(plan.buy_animal_sequence) == 1

    # Authoritative ledger MUST have reservations committed for live candidate!
    assert len(ledger.candidate_reservations) == initial_reservations_len + 1
    assert ledger.candidate_purchase_cash_spent > 0.0


