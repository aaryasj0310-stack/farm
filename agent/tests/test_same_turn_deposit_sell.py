"""Unit tests for Phase M0-E: Same-Turn Deposit-to-Market Exploit.

Tests:
1. DROP then SELL same turn works in actual engine.
2. PLACE-to-shed then SELL same turn works.
3. Predicted deposit equals actual deposit.
4. Deposit prediction respects shed capacity.
5. Multiple worker execution order modeled correctly.
6. Multiple product deposits modeled correctly.
7. Invalid DROP does not become sellable.
8. Mandatory feed wheat remains reserved.
9. Same-turn sell does not exceed effective inventory.
10. Shared 10-order cap respected.
11. Existing sell policy still decides whether product should sell.
12. $1 floor strategy unchanged.
13. OFF mode reproduces baseline.
14. SHADOW emits no changed actions.
15. LIVE uses predicted deposit only after worker actions are finalized.
16. Reset clears prediction state.
17. agent/ and submission/ remain synchronized.
"""

from __future__ import annotations

import copy
import filecmp
import os
from types import SimpleNamespace
import pytest

import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kengine

from config import (
    SAME_TURN_DEPOSIT_SELL_MODE,
    get_same_turn_deposit_sell_mode,
    set_same_turn_deposit_sell_mode,
)
from execution.same_turn_deposit_controller import (
    predict_same_turn_deposits,
    reset_same_turn_deposit_telemetry,
    get_same_turn_deposit_telemetry,
    is_shed_adjacent,
)
from market.market_brain import MarketBrain


class FakeFC:
    def expected_price(self, prod, day):
        return 120.0

    def prob_floor(self, prod, day):
        return 0.0


def make_test_ctx(day=10, hour=1, shed=None, inventories=None, farmer=(4, 4), hands=(), money=5000):
    shed_dict = copy.deepcopy(shed) if shed is not None else {}
    invs = copy.deepcopy(inventories) if inventories is not None else [{}]

    class MockTile:
        def __init__(self, x, y):
            self.x = x
            self.y = y
            self.is_plant = False
            self.is_animal = False
            self.crop = None
            self.yield_units = 0

    grid = [[MockTile(x, y) for x in range(10)] for y in range(10)]

    farm = SimpleNamespace(
        farmer=list(farmer),
        hands=[list(h) for h in hands],
        money=money,
        hires_today=0,
        unlocked={"NW"},
        iter_tiles=lambda: [t for row in grid for t in row],
        quadrant_of=lambda pos: ("N" if pos[1] < 5 else "S") + ("W" if pos[0] < 5 else "E"),
    )

    private = SimpleNamespace(
        shed=shed_dict,
        inventories=invs,
        seeds={},
    )

    market = SimpleNamespace(
        inventory={p: 10000.0 for p in [
            "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
            "EGG", "MILK", "WOOL", "FERTILIZER"
        ]},
        params=None,
    )

    ctx = {
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farm": farm,
        "private": private,
        "market": market,
        "scheduled_product_deposits": {},
    }
    return ctx


# 1. DROP then SELL same turn works in actual engine
def test_1_drop_then_sell_same_turn_engine():
    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": 96501})
    env.reset()
    s0 = env.state[0].observation
    s0.farms[0]["farmer"] = [4, 4]
    s0.private["inventories"] = [{"STRAWBERRY": 10}]
    s0.private["shed"] = {}

    action = {
        "farmer": ["DROP"],
        "hands": [],
        "market": [["SELL", "STRAWBERRY", 10]],
    }
    env.step([action, {}])

    post_s0 = env.state[0].observation
    assert post_s0.private["inventories"][0].get("STRAWBERRY", 0) == 0
    assert post_s0.private["shed"].get("STRAWBERRY", 0) == 0
    assert post_s0.farms[0]["money"] > 3000


# 2. PLACE-to-shed then SELL same turn works
def test_2_place_to_shed_then_sell_same_turn_engine():
    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": 96501})
    env.reset()
    s0 = env.state[0].observation
    s0.farms[0]["farmer"] = [4, 4]
    s0.private["inventories"] = [{"STRAWBERRY": 10}]
    s0.private["shed"] = {}

    action = {
        "farmer": ["PLACE", "STRAWBERRY", 10],
        "hands": [],
        "market": [["SELL", "STRAWBERRY", 10]],
    }
    env.step([action, {}])

    post_s0 = env.state[0].observation
    assert post_s0.private["inventories"][0].get("STRAWBERRY", 0) == 0
    assert post_s0.private["shed"].get("STRAWBERRY", 0) == 0
    assert post_s0.farms[0]["money"] > 3000


# 3. Predicted deposit equals actual deposit
def test_3_predicted_deposit_equals_actual_deposit():
    ctx = make_test_ctx(day=10, hour=1, shed={}, inventories=[{"CARROT": 5}], farmer=(4, 4))
    asg = {"actions": {0: ["DROP"]}}
    pred = predict_same_turn_deposits(ctx, asg)
    assert pred == {"CARROT": 5}


# 4. Deposit prediction respects shed capacity
def test_4_deposit_prediction_respects_shed_capacity():
    ctx = make_test_ctx(day=10, hour=1, shed={"WHEAT": 96}, inventories=[{"CARROT": 10}], farmer=(4, 4))
    asg = {"actions": {0: ["DROP"]}}
    pred = predict_same_turn_deposits(ctx, asg)
    assert pred == {"CARROT": 4}  # only 4 fit in shed


# 5. Multiple worker execution order modeled correctly
def test_5_multiple_worker_order_modeled_correctly():
    # Shed at 95. Room = 5.
    # Worker 0 carries 4 CARROT.
    # Worker 1 carries 4 MELON.
    # Worker 0 takes 4, room becomes 1.
    # Worker 1 takes min(4, 1) = 1.
    ctx = make_test_ctx(
        day=10, hour=1,
        shed={"WHEAT": 95},
        inventories=[{"CARROT": 4}, {"MELON": 4}],
        farmer=(4, 4),
        hands=[(5, 4)],
    )
    asg = {"actions": {0: ["DROP"], 1: ["DROP"]}}
    pred = predict_same_turn_deposits(ctx, asg)
    assert pred == {"CARROT": 4, "MELON": 1}


# 6. Multiple product deposits modeled correctly
def test_6_multiple_product_deposits():
    ctx = make_test_ctx(
        day=10, hour=1,
        shed={},
        inventories=[{"CARROT": 3, "TOMATO": 4}],
        farmer=(4, 4),
    )
    asg = {"actions": {0: ["DROP"]}}
    pred = predict_same_turn_deposits(ctx, asg)
    assert pred == {"CARROT": 3, "TOMATO": 4}


# 7. Invalid DROP does not become sellable
def test_7_invalid_drop_does_not_become_sellable():
    # Worker is at (0, 0), not shed adjacent!
    ctx = make_test_ctx(
        day=10, hour=1,
        shed={},
        inventories=[{"CARROT": 10}],
        farmer=(0, 0),
    )
    asg = {"actions": {0: ["DROP"]}}
    pred = predict_same_turn_deposits(ctx, asg)
    assert pred == {}


# 8. Mandatory feed wheat remains reserved
def test_8_mandatory_feed_wheat_remains_reserved():
    # 2 animals on farm -> requires 2 * 3 = 6 wheat buffer
    ctx = make_test_ctx(day=10, hour=1, shed={"WHEAT": 10}, inventories=[{"WHEAT": 5}], farmer=(4, 4))
    # mock 2 animals on farm
    for i, t in enumerate(list(ctx["farm"].iter_tiles())[:2]):
        t.is_animal = True

    set_same_turn_deposit_sell_mode("LIVE")
    try:
        ctx["scheduled_product_deposits"] = {"WHEAT": 5}
        brain = MarketBrain(FakeFC())
        orders, details = brain.sell_orders(ctx)
        # Total physical wheat = 10 + 5 = 15. Reserved = 6. Sellable = 9.
        wheat_sold = sum(o[2] for o in orders if o[0] == "SELL" and o[1] == "WHEAT")
        assert wheat_sold <= 9
    finally:
        set_same_turn_deposit_sell_mode("OFF")


# 9. Same-turn sell does not exceed effective inventory
def test_9_same_turn_sell_does_not_exceed_effective_inventory():
    ctx = make_test_ctx(day=10, hour=1, shed={}, inventories=[{"STRAWBERRY": 4}], farmer=(4, 4))
    set_same_turn_deposit_sell_mode("LIVE")
    try:
        ctx["scheduled_product_deposits"] = {"STRAWBERRY": 4}
        brain = MarketBrain(FakeFC())
        orders, details = brain.sell_orders(ctx)
        straw_sold = sum(o[2] for o in orders if o[0] == "SELL" and o[1] == "STRAWBERRY")
        assert straw_sold <= 4
    finally:
        set_same_turn_deposit_sell_mode("OFF")


# 10. Shared 10-order cap respected
def test_10_shared_10_order_cap_respected():
    ctx = make_test_ctx(day=10, hour=1, shed={"CARROT": 10}, inventories=[{"TOMATO": 10}], farmer=(4, 4))
    set_same_turn_deposit_sell_mode("LIVE")
    try:
        ctx["scheduled_product_deposits"] = {"TOMATO": 10}
        brain = MarketBrain(FakeFC())
        orders, details = brain.sell_orders(ctx, max_slots=10)
        assert len(orders) <= 10
    finally:
        set_same_turn_deposit_sell_mode("OFF")


# 11. Existing sell policy still decides whether product should sell
def test_11_existing_sell_policy_still_decides():
    # Hour 2 is NOT a sell window (SELL_WINDOWS are 1, 5, 9, 13, 17, 21), and no urgency
    ctx = make_test_ctx(day=10, hour=2, shed={"CARROT": 5}, inventories=[{"TOMATO": 5}], farmer=(4, 4))
    set_same_turn_deposit_sell_mode("LIVE")
    try:
        ctx["scheduled_product_deposits"] = {"TOMATO": 5}
        brain = MarketBrain(FakeFC())
        orders, details = brain.sell_orders(ctx)
        # Should be empty because hour 2 is off-window and shed is not overflowing
        assert orders == []
    finally:
        set_same_turn_deposit_sell_mode("OFF")


# 12. $1 floor strategy unchanged
def test_12_price_floor_hold_unchanged():
    ctx = make_test_ctx(day=10, hour=1, shed={}, inventories=[{"MELON": 10}], farmer=(4, 4))
    # Force MELON market inventory very high so spot price = $1
    ctx["market"].inventory["MELON"] = 50000.0
    set_same_turn_deposit_sell_mode("LIVE")
    try:
        ctx["scheduled_product_deposits"] = {"MELON": 10}
        brain = MarketBrain(FakeFC())
        orders, details = brain.sell_orders(ctx)
        melon_orders = [o for o in orders if o[0] == "SELL" and o[1] == "MELON"]
        assert melon_orders == []
    finally:
        set_same_turn_deposit_sell_mode("OFF")


# 13. OFF mode reproduces baseline
def test_13_off_mode_reproduces_baseline():
    ctx = make_test_ctx(day=10, hour=1, shed={"CARROT": 3}, inventories=[{"CARROT": 5}], farmer=(4, 4))
    ctx["scheduled_product_deposits"] = {"CARROT": 5}
    set_same_turn_deposit_sell_mode("OFF")
    brain = MarketBrain(FakeFC())
    orders, details = brain.sell_orders(ctx)
    carrot_sold = sum(o[2] for o in orders if o[0] == "SELL" and o[1] == "CARROT")
    assert carrot_sold <= 3  # uses only shed_pre (3)


# 14. SHADOW emits no changed actions
def test_14_shadow_mode_emits_no_changed_actions():
    ctx = make_test_ctx(day=10, hour=1, shed={"CARROT": 3}, inventories=[{"CARROT": 5}], farmer=(4, 4))
    ctx["scheduled_product_deposits"] = {"CARROT": 5}

    set_same_turn_deposit_sell_mode("OFF")
    brain = MarketBrain(FakeFC())
    orders_off, _ = brain.sell_orders(ctx)

    set_same_turn_deposit_sell_mode("SHADOW")
    orders_shadow, _ = brain.sell_orders(ctx)
    set_same_turn_deposit_sell_mode("OFF")

    assert orders_off == orders_shadow


# 15. LIVE uses predicted deposit only after worker actions are finalized
def test_15_live_uses_predicted_deposit_after_actions():
    ctx = make_test_ctx(day=10, hour=1, shed={}, inventories=[{"CARROT": 5}], farmer=(4, 4))
    asg = {"actions": {0: ["DROP"]}}
    predicted = predict_same_turn_deposits(ctx, asg)
    assert predicted == {"CARROT": 5}

    set_same_turn_deposit_sell_mode("LIVE")
    try:
        ctx["scheduled_product_deposits"] = predicted
        brain = MarketBrain(FakeFC())
        orders, details = brain.sell_orders(ctx)
        carrot_sold = sum(o[2] for o in orders if o[0] == "SELL" and o[1] == "CARROT")
        assert carrot_sold > 0
    finally:
        set_same_turn_deposit_sell_mode("OFF")


# 16. Reset clears prediction state
def test_16_reset_clears_prediction_state():
    reset_same_turn_deposit_telemetry()
    ctx = make_test_ctx(day=10, hour=1, shed={}, inventories=[{"CARROT": 5}], farmer=(4, 4))
    asg = {"actions": {0: ["DROP"]}}
    _ = predict_same_turn_deposits(ctx, asg)
    t1 = get_same_turn_deposit_telemetry()
    assert t1["opportunities_detected"] > 0

    reset_same_turn_deposit_telemetry()
    t2 = get_same_turn_deposit_telemetry()
    assert t2["opportunities_detected"] == 0
    assert t2["same_turn_sales_enabled"] == 0


# 17. agent/ and submission/ remain synchronized
def test_17_agent_and_submission_synchronized():
    repo_root = r"d:\website project\kaggri ox"
    pairs = [
        ("agent/config.py", "submission/config.py"),
        ("agent/main.py", "submission/main.py"),
        ("agent/market/market_brain.py", "submission/market/market_brain.py"),
        ("agent/execution/same_turn_deposit_controller.py", "submission/execution/same_turn_deposit_controller.py"),
    ]
    for p_agent, p_sub in pairs:
        path_a = os.path.join(repo_root, p_agent)
        path_b = os.path.join(repo_root, p_sub)
        assert os.path.exists(path_a), f"Missing {path_a}"
        assert os.path.exists(path_b), f"Missing {path_b}"
        assert filecmp.cmp(path_a, path_b, shallow=False), f"Mismatch between {path_a} and {path_b}"
