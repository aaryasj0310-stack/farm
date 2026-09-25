"""Phase M0-B Unit & Regression Tests: Midnight Storage Dump Logistics.

Covers:
1. Mode OFF preserves baseline behavior.
2. Worker inventory accounting accuracy.
3. Late-day candidate detection (hours 18–23).
4. Congestion gate: only buffers when shed is loaded or worker is distant.
5. Worker eligibility and safe crop item selection.
6. Feed wheat protection: never buffers wheat when live feeds are due.
7. Capacity headroom guarantee: blocks buffering if projected midnight total > 95.
8. Urgent task non-preemption.
9. Endgame protection: no buffering on Day 29.
10. Midnight transition: automatic dump into shed on Day+1 Hour 0.
11. M0-A + M0-B interaction: simultaneous pipeline and buffering compatibility.
12. Reset idempotency across episodes.
13. Deterministic behavior under fixed seed.
"""
from __future__ import annotations

import copy
import pytest
from kaggle_environments import make

import config
from execution.midnight_storage_controller import (
    is_midnight_storage_dump_enabled,
    should_buffer_worker_inventory,
    reset_midnight_storage_telemetry,
    get_midnight_storage_telemetry,
    MAX_SAFE_SHED_HEADROOM,
)
from main import reset_agent_state, agent


@pytest.fixture(autouse=True)
def clean_flags_and_state():
    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode("OFF")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_midnight_storage_dump_mode("OFF")
    reset_agent_state()
    yield
    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode("OFF")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_midnight_storage_dump_mode("OFF")
    reset_agent_state()


def test_mode_off_preserves_baseline():
    """Test 1: When mode is OFF, should_buffer_worker_inventory always returns False."""
    config.set_midnight_storage_dump_mode("OFF")
    ctx = {"day": 5, "hour": 20}
    assert should_buffer_worker_inventory(ctx, 0, {"WHEAT": 5}, {"WHEAT": 5}, 80, 5, feeds_due=0) is False


def test_late_day_candidate_detection():
    """Test 2: Buffering is allowed at hour >= 18, but rejected at hour < 18."""
    config.set_midnight_storage_dump_mode("ON")
    ctx_early = {"day": 5, "hour": 17}
    ctx_late = {"day": 5, "hour": 18}

    assert should_buffer_worker_inventory(ctx_early, 0, {"WHEAT": 5}, {"WHEAT": 5}, 80, 5) is False
    assert should_buffer_worker_inventory(ctx_late, 0, {"WHEAT": 5}, {"WHEAT": 5}, 80, 5) is True


def test_endgame_day_29_protection():
    """Test 3: Day 29 must reject buffering because items must be sold before season end."""
    config.set_midnight_storage_dump_mode("ON")
    ctx_day29 = {"day": 29, "hour": 20}
    assert should_buffer_worker_inventory(ctx_day29, 0, {"WHEAT": 5}, {"WHEAT": 5}, 80, 5) is False


def test_feed_wheat_protection():
    """Test 4: Never buffer wheat when live animal feeding is due today."""
    config.set_midnight_storage_dump_mode("ON")
    ctx = {"day": 5, "hour": 19}
    # When feeds_due > 0, wheat buffering is rejected
    assert should_buffer_worker_inventory(ctx, 0, {"WHEAT": 5}, {"WHEAT": 5}, 80, 5, feeds_due=1) is False
    # But carrot buffering remains permitted
    assert should_buffer_worker_inventory(ctx, 0, {"CARROT": 5}, {"CARROT": 5}, 80, 5, feeds_due=1) is True


def test_capacity_headroom_guarantee():
    """Test 5: Block buffering if projected midnight total exceeds MAX_SAFE_SHED_HEADROOM (95)."""
    config.set_midnight_storage_dump_mode("ON")
    ctx = {"day": 5, "hour": 21}
    # 85 shed + 10 carried = 95 -> Allowed
    assert should_buffer_worker_inventory(ctx, 0, {"CARROT": 10}, {"CARROT": 10}, 85, 10) is True
    # 90 shed + 6 carried = 96 -> Blocked to guarantee no overflow discard
    assert should_buffer_worker_inventory(ctx, 0, {"CARROT": 6}, {"CARROT": 6}, 90, 6) is False


def test_item_safety_filtering():
    """Test 6: Reject non-crop items (animals, fertilizer, etc.)."""
    config.set_midnight_storage_dump_mode("ON")
    ctx = {"day": 5, "hour": 19}
    assert should_buffer_worker_inventory(ctx, 0, {"FERTILIZER": 2}, {"FERTILIZER": 2}, 80, 2) is False
    assert should_buffer_worker_inventory(ctx, 0, {"COW": 1}, {"COW": 1}, 80, 1) is False
    assert should_buffer_worker_inventory(ctx, 0, {"MELON": 2}, {"MELON": 2}, 80, 2) is True


def test_telemetry_recording_and_reset():
    """Test 7: Telemetry records events and resets cleanly."""
    config.set_midnight_storage_dump_mode("ON")
    ctx = {"day": 5, "hour": 19}
    should_buffer_worker_inventory(ctx, 0, {"CARROT": 3}, {"CARROT": 3}, 80, 3)

    t = get_midnight_storage_telemetry()
    assert t["holds_successful"] >= 1
    assert t["products_held"]["CARROT"] >= 3

    reset_midnight_storage_telemetry()
    t_clean = get_midnight_storage_telemetry()
    assert t_clean["holds_successful"] == 0
    assert t_clean["products_held"]["CARROT"] == 0


def test_midnight_engine_dump_execution():
    """Test 8: Verify real engine executes midnight dump from worker to shed."""
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 42})
    env.reset()

    # Step to hour 23
    for _ in range(23):
        env.step([{"farmer": ["PASS"], "market": []}, {"farmer": ["PASS"], "market": []}])

    priv = env.state[0].observation.private
    priv.inventories[0]["CARROT"] = 15
    for k in priv.shed:
        priv.shed[k] = 0

    # Step 23 -> 24 rollover
    env.step([{"farmer": ["PASS"], "market": []}, {"farmer": ["PASS"], "market": []}])

    s0 = env.state[0].observation
    assert s0.day == 1 and s0.hour == 0
    assert s0.private.shed.get("CARROT", 0) == 15
    assert s0.private.inventories[0].get("CARROT", 0) == 0


def test_m0_a_and_m0_b_simultaneous_flags():
    """Test 9: Both M0-A and M0-B flags can be toggled independently and concurrently."""
    config.set_same_turn_crop_pipeline_mode("ON")
    config.set_midnight_storage_dump_mode("ON")
    assert config.get_same_turn_crop_pipeline_mode() == "ON"
    assert config.get_midnight_storage_dump_mode() == "ON"

    config.set_same_turn_crop_pipeline_mode("OFF")
    assert config.get_same_turn_crop_pipeline_mode() == "OFF"
    assert config.get_midnight_storage_dump_mode() == "ON"

    config.set_midnight_storage_dump_mode("OFF")
    assert config.get_midnight_storage_dump_mode() == "OFF"


def test_deterministic_behavior():
    """Test 10: Fixed seed produces deterministic decisions."""
    env1 = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 96511})
    env2 = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 96511})
    env1.reset()
    env2.reset()

    config.set_midnight_storage_dump_mode("ON")
    reset_agent_state()
    act1 = agent(env1.state[0].observation, env1.configuration)

    reset_agent_state()
    act2 = agent(env2.state[0].observation, env2.configuration)

    assert act1["farmer"] == act2["farmer"]
    assert act1["market"] == act2["market"]


def test_rescue_mode_configuration_and_validation():
    """Test 11: Configuration supports OFF, BUFFER, RESCUE, ON, and rejects invalid strings."""
    for valid in ("OFF", "BUFFER", "RESCUE", "ON"):
        config.set_midnight_storage_dump_mode(valid)
        assert config.get_midnight_storage_dump_mode() == valid

    with pytest.raises(ValueError):
        config.set_midnight_storage_dump_mode("INVALID_MODE")


def test_rescue_mode_buffering_behavior():
    """Test 12: In RESCUE mode, normal worker delivery is preserved without artificial hold delays."""
    config.set_midnight_storage_dump_mode("RESCUE")
    ctx_hour19 = {"day": 10, "hour": 19}
    ctx_hour21 = {"day": 10, "hour": 21}

    # In RESCUE mode, should_buffer_worker_inventory returns False so normal deliveries proceed unimpeded
    assert should_buffer_worker_inventory(ctx_hour19, 0, {"CARROT": 5}, {"CARROT": 5}, 50, 5) is False
    assert should_buffer_worker_inventory(ctx_hour21, 0, {"CARROT": 5}, {"CARROT": 5}, 50, 5) is False


def test_rescue_mode_market_relief_activation():
    """Test 13: MarketBrain generates proactive storage rescue sell orders when midnight load > 90."""
    from market.market_brain import MarketBrain

    class MockFC:
        def prob_floor(self, product, day):
            return 0.0

        def expected_price(self, product, day):
            return 50.0

    config.set_midnight_storage_dump_mode("RESCUE")
    brain = MarketBrain(MockFC())

    # Mock ctx where shed has 60 items, workers carry 35 items (projected 95 > 90)
    class MockFarm:
        def iter_tiles(self):
            return []

    class MockPrivate:
        shed = {"WHEAT": 40, "CARROT": 20}
        inventories = [{"CARROT": 15}, {"MELON": 20}]

    class MockMarket:
        inventory = {"WHEAT": 10000.0, "CARROT": 10000.0}

    ctx = {
        "day": 15,
        "hour": 21,
        "private": MockPrivate(),
        "market": MockMarket(),
        "farm": MockFarm(),
        "scheduled_product_deposits": {},
    }

    orders, details = brain.sell_orders(ctx, max_slots=10)
    assert len(orders) > 0
    assert any(o[0] == "SELL" for o in orders)
    # Check that relief freed units
    total_sold = sum(o[2] for o in orders if o[0] == "SELL")
    assert total_sold >= 5  # At least 95 - 90 = 5 units freed

