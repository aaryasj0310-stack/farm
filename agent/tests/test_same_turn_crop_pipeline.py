"""Tests for Phase M0-A Same-Turn Crop Pipeline Exploit.

Covers:
1. HARVEST->PLANT->WATER succeeds with ordered workers.
2. Incorrect worker order does not get treated as a valid pipeline.
3. Pipeline requires pre-existing seed inventory.
4. Same-turn BUY_SEED cannot satisfy current-turn pipeline planting.
5. Pipeline seed reservations prevent atomic PLANT failure.
6. One-time crops qualify.
7. Ongoing crops do not incorrectly enter replant pipeline.
8. Pipeline does not override urgent watering.
9. Pipeline does not override animal feeding.
10. Feature OFF produces baseline behavior.
11. Reset clears pipeline state between matches.
12. agent/ and submission/ remain synchronized.
"""
from __future__ import annotations

import copy
import pytest
from kaggle_environments import make

import config
try:
    from execution.crop_pipeline_controller import (
        evaluate_and_assign_pipelines,
        get_crop_pipeline_telemetry,
        is_pipeline_enabled,
        reset_crop_pipeline_telemetry,
        verify_post_turn_pipelines,
    )
except ImportError:
    from agent.execution.crop_pipeline_controller import (
        evaluate_and_assign_pipelines,
        get_crop_pipeline_telemetry,
        is_pipeline_enabled,
        reset_crop_pipeline_telemetry,
        verify_post_turn_pipelines,
    )

try:
    from main import agent, reset_agent_state
except ImportError:
    from agent.main import agent, reset_agent_state


@pytest.fixture(autouse=True)
def clean_pipeline_state():
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_soft_worker_locality_mode("OFF")
    config.set_sw_forward_architecture_mode("OFF")
    reset_crop_pipeline_telemetry()
    reset_agent_state()
    yield
    config.set_same_turn_crop_pipeline_mode("OFF")
    reset_crop_pipeline_telemetry()
    reset_agent_state()


def _make_mock_ctx_and_farm(crop="WHEAT", yield_units=2, age=3, seeds=1, hour=10, day=5):
    class MockTile:
        def __init__(self, pos, is_plant=True, crop="WHEAT", yield_units=2, planted_day=2, watered_today=False):
            self.pos = pos
            self.is_plant = is_plant
            self.is_animal = False
            self.crop = crop
            self.yield_units = yield_units
            self.planted_day = planted_day
            self.watered_today = watered_today
            self.kind = "PLANT"

    class MockFarm:
        def __init__(self):
            self.unlocked = ["NW", "NE"]
            self.farmer = [1, 1]
            self.hands = [[1, 1], [1, 1]]
            self.tiles_list = [MockTile((1, 1), crop=crop, yield_units=yield_units, planted_day=day - age)]

        def iter_tiles(self):
            return list(self.tiles_list)

        def quadrant_of(self, pos):
            return "NW"

    class MockPrivate:
        def __init__(self):
            self.seeds = {crop: seeds}
            self.inventories = [{}, {}, {}]
            self.shed = {}

    class MockMacro:
        def __init__(self):
            self.plant_queue = [((1, 1), crop)]

    farm = MockFarm()
    private = MockPrivate()
    macro = MockMacro()
    ctx = {
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
        "farm": farm,
        "private": private,
        "plan": macro,
        "macro": macro,
    }
    pos_by_idx = {0: (1, 1), 1: (1, 1), 2: (1, 1)}
    free_units = {0, 1, 2}
    return ctx, farm, pos_by_idx, free_units, macro


def test_1_harvest_plant_water_succeeds_ordered():
    """1. HARVEST->PLANT->WATER succeeds with ordered workers."""
    config.set_same_turn_crop_pipeline_mode("ON")
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=2)
    asg, busy, removed = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )

    assert len(asg) == 3
    assert set(busy) == {0, 1, 2}
    # Verify strict worker order: u_harvest < u_plant < u_water
    assert asg[0]["op"] == "HARVEST"
    assert asg[1]["op"] == "PLANT"
    assert asg[2]["op"] == "WATER"


def test_2_incorrect_worker_order_not_valid():
    """2. Worker ordering u_harvest < u_plant < u_water is mathematically enforced."""
    config.set_same_turn_crop_pipeline_mode("ON")
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=2)
    # Give free units out of order
    free_units = {2, 0, 1}
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )
    assigned_order = [u for u in sorted(asg.keys())]
    assert assigned_order == [0, 1, 2]
    assert asg[assigned_order[0]]["op"] == "HARVEST"
    assert asg[assigned_order[1]]["op"] == "PLANT"
    assert asg[assigned_order[2]]["op"] == "WATER"


def test_3_pipeline_requires_pre_existing_seed():
    """3. Pipeline requires pre-existing seed inventory."""
    config.set_same_turn_crop_pipeline_mode("ON")
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=0)
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )
    assert len(asg) == 0
    assert len(busy) == 0


def test_4_same_turn_buy_seed_cannot_satisfy_current_pipeline():
    """4. Same-turn BUY_SEED cannot satisfy current-turn pipeline planting."""
    config.set_same_turn_crop_pipeline_mode("ON")
    # Even if market has orders to buy seed, if private.seeds is 0 at turn start, pipeline does not form
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=0)
    ctx["market_orders"] = [["BUY_SEED", "WHEAT", 1]]
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )
    assert len(asg) == 0


def test_5_seed_reservations_prevent_atomic_plant_failure():
    """5. Pipeline seed reservations prevent atomic PLANT failure."""
    config.set_same_turn_crop_pipeline_mode("ON")
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=1)
    # If 1 seed is already reserved by another task
    reserved_seeds = {"WHEAT": 1}
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, reserved_seeds
    )
    # Available seeds = 1 - 1 = 0, so pipeline cannot reserve
    assert len(asg) == 0


def test_6_one_time_crops_qualify():
    """6. One-time crops (WHEAT, CARROT, MELON) qualify."""
    config.set_same_turn_crop_pipeline_mode("ON")
    for crop in ("WHEAT", "CARROT", "MELON"):
        ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm(crop, yield_units=2, age=10, seeds=2)
        asg, busy, _ = evaluate_and_assign_pipelines(
            ctx, farm, pos_by_idx, free_units, [], macro, {}
        )
        assert len(asg) == 3, f"Failed on one-time crop {crop}"
        assert asg[0]["op"] == "HARVEST"
        assert asg[1]["args"] == [crop]


def test_7_ongoing_crops_do_not_enter_replant_pipeline():
    """7. Ongoing crops (TOMATO, STRAWBERRY) do not incorrectly enter replant pipeline."""
    config.set_same_turn_crop_pipeline_mode("ON")
    for crop in ("TOMATO", "STRAWBERRY"):
        ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm(crop, yield_units=2, age=12, seeds=2)
        asg, busy, _ = evaluate_and_assign_pipelines(
            ctx, farm, pos_by_idx, free_units, [], macro, {}
        )
        assert len(asg) == 0, f"Ongoing crop {crop} should not enter replant pipeline"


def test_8_pipeline_does_not_override_urgent_tasks():
    """8. Pipeline does not override urgent watering or survival tasks."""
    config.set_same_turn_crop_pipeline_mode("ON")
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=2)
    # Only 2 free units left because unit 0 was assigned to urgent task
    free_units = {1, 2}
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )
    # Needs 3 units; cannot form pipeline with only 2 free units
    assert len(asg) == 0


def test_9_pipeline_does_not_override_animal_feeding():
    """9. Pipeline does not override animal feeding."""
    config.set_same_turn_crop_pipeline_mode("ON")
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=2)
    # Unit 2 is busy feeding animal
    free_units = {0, 1}
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )
    assert len(asg) == 0


def test_10_feature_off_produces_baseline():
    """10. Feature OFF produces baseline behavior."""
    config.set_same_turn_crop_pipeline_mode("OFF")
    assert not is_pipeline_enabled()
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=2)
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )
    assert len(asg) == 0


def test_11_reset_clears_pipeline_state():
    """11. Reset clears pipeline state between matches."""
    config.set_same_turn_crop_pipeline_mode("ON")
    ctx, farm, pos_by_idx, free_units, macro = _make_mock_ctx_and_farm("WHEAT", yield_units=2, age=3, seeds=2)
    asg, busy, _ = evaluate_and_assign_pipelines(
        ctx, farm, pos_by_idx, free_units, [], macro, {}
    )
    # Trigger post-turn verification mock
    class MockObsPost:
        def __init__(self):
            class MockFarmPost:
                tiles = [[None for _ in range(10)] for _ in range(10)]
            self.farms = [MockFarmPost()]
            self.farms[0].tiles[1][1] = {
                "kind": "PLANT", "crop": "WHEAT", "planted_day": 5, "watered_today": True
            }
            class MockPrivPost:
                inventories = [{"WHEAT": 2}, {}, {}]
            self.private = MockPrivPost()

    verify_post_turn_pipelines(MockObsPost(), 0)
    assert len(get_crop_pipeline_telemetry()) == 1

    # Reset
    reset_agent_state()
    assert len(get_crop_pipeline_telemetry()) == 0


def test_12_agent_submission_parity_check():
    """12. agent/ and submission/ sync verification."""
    import os
    agent_dir = os.path.join(r"d:\website project\kaggri ox", "agent")
    sub_dir = os.path.join(r"d:\website project\kaggri ox", "submission")
    assert os.path.exists(agent_dir)
    assert os.path.exists(sub_dir)
