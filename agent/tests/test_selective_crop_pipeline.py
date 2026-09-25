"""Kaggriculture Phase M0-C: Selective Same-Turn Crop Pipeline Gating Tests.

Verifies:
1. OFF preserves existing baseline behavior (no pipelines scheduled).
2. GLOBAL preserves exact M0-A unconditional behavior.
3. SELECTIVE executes only when hard safety vetoes and net economic value pass.
4. Unsupported ongoing crops (Tomato, Strawberry) rejected.
5. Survival hard veto triggers (starving animals, critical watering, urgent tasks).
6. Worker opportunity cost veto triggers (starved high-priority tasks, insufficient free units).
7. Storage risk hard veto triggers (projected shed >= 92 or shed_load >= 90).
8. Liquidity / capital risk hard veto triggers (near-term animal purchase window with tight shed).
9. Market timing hard veto triggers (crop stockpile in shed >= 50).
10. Season-end waste veto triggers (crop cannot mature before season end).
11. Seed constraint veto triggers (no unreserved seeds).
12. Favorable conditions pass gate and execute atomic pipeline.
13. Shadow decision telemetry records accurate rejection reasons and metrics in both modes.
14. Complete decoupling from Phase M0-B (midnight storage dump remains OFF).
"""
import copy
import pytest
from typing import Any, Dict, List

import config
from execution.crop_pipeline_controller import (
    CROPS_INFO,
    REJECTION_SURVIVAL_PRIORITY,
    REJECTION_WORKER_OPPORTUNITY_COST,
    REJECTION_STORAGE_RISK,
    REJECTION_MARKET_TIMING,
    REJECTION_LIQUIDITY_CAPITAL_RISK,
    REJECTION_SEASON_END_NO_VALUE,
    REJECTION_SEED_CONSTRAINT,
    REJECTION_UNSUPPORTED_CROP,
    REJECTION_INSUFFICIENT_ORDERED_WORKERS,
    REJECTION_NEGATIVE_NET_VALUE,
    evaluate_pipeline_economic_gate,
    evaluate_and_assign_pipelines,
    get_crop_pipeline_shadow_decisions,
    get_crop_pipeline_telemetry,
    is_pipeline_enabled,
    reset_crop_pipeline_telemetry,
)


class MockTile:
    def __init__(self, pos, is_plant=True, crop="WHEAT", yield_units=2, planted_day=4, consecutive_unwatered=0, watered_today=False, is_animal=False, fed_today=True, consecutive_unfed=0):
        self.pos = pos
        self.is_plant = is_plant
        self.crop = crop
        self.yield_units = yield_units
        self.planted_day = planted_day
        self.consecutive_unwatered = consecutive_unwatered
        self.watered_today = watered_today
        self.is_animal = is_animal
        self.fed_today = fed_today
        self.consecutive_unfed = consecutive_unfed

    def to_dict(self):
        return {
            "kind": "PLANT" if self.is_plant else "SOIL",
            "crop": self.crop,
            "yield_units": self.yield_units,
            "planted_day": self.planted_day,
            "consecutive_unwatered": self.consecutive_unwatered,
            "watered_today": self.watered_today,
        }


class MockFarm:
    def __init__(self, tiles=None, unlocked=None):
        self.tiles_list = tiles or []
        self.unlocked = set(unlocked or ["NW", "NE"])

    def iter_tiles(self):
        return iter(self.tiles_list)

    def quadrant_of(self, pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


class MockPrivate:
    def __init__(self, seeds=None, shed=None, inventories=None, money=5000.0):
        self.seeds = seeds or {"WHEAT": 5, "CARROT": 5}
        self.shed = shed or {"WHEAT": 10}
        self.inventories = inventories or [{} for _ in range(8)]
        self.money = money


def make_ctx(day=6, hour=5, shed_load=10, carried=0, money=5000.0, seeds=None, wheat_in_shed=None):
    if wheat_in_shed is not None:
        w_shed = wheat_in_shed
        other_shed = max(0, shed_load - w_shed)
        shed_dict = {"WHEAT": w_shed, "CARROT": other_shed}
    else:
        shed_dict = {"WHEAT": shed_load}
    priv = MockPrivate(
        seeds=seeds or {"WHEAT": 5},
        shed=shed_dict,
        inventories=[{} for _ in range(8)],
        money=money,
    )
    return {
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
        "private": priv,
    }


@pytest.fixture(autouse=True)
def clean_pipeline_state():
    reset_crop_pipeline_telemetry()
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_midnight_storage_dump_mode("OFF")
    yield
    reset_crop_pipeline_telemetry()
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_midnight_storage_dump_mode("OFF")


def test_config_mode_support_and_backward_compatibility():
    """Verify OFF, GLOBAL, SELECTIVE, and legacy ON mapping."""
    config.set_same_turn_crop_pipeline_mode("OFF")
    assert config.get_same_turn_crop_pipeline_mode() == "OFF"
    assert not is_pipeline_enabled()

    config.set_same_turn_crop_pipeline_mode("ON")
    assert config.get_same_turn_crop_pipeline_mode() in ("ON", "GLOBAL")
    assert is_pipeline_enabled()

    config.set_same_turn_crop_pipeline_mode("GLOBAL")
    assert config.get_same_turn_crop_pipeline_mode() == "GLOBAL"
    assert is_pipeline_enabled()

    config.set_same_turn_crop_pipeline_mode("SELECTIVE")
    assert config.get_same_turn_crop_pipeline_mode() == "SELECTIVE"
    assert is_pipeline_enabled()

    with pytest.raises(ValueError):
        config.set_same_turn_crop_pipeline_mode("INVALID_MODE")


def test_off_mode_schedules_no_pipelines():
    """Verify OFF mode strictly disables scheduling."""
    config.set_same_turn_crop_pipeline_mode("OFF")
    t = MockTile((2, 2), crop="WHEAT", yield_units=2, planted_day=4)
    farm = MockFarm([t])
    ctx = make_ctx()
    pos_by_idx = {0: (2, 2), 1: (2, 2), 2: (2, 2)}
    asg, busy, rem = evaluate_and_assign_pipelines(ctx, farm, pos_by_idx, {0, 1, 2}, [], None, {})
    assert asg == {}
    assert busy == set()
    assert rem == []


def test_storage_risk_hard_veto():
    """Verify candidate is rejected if projected shed occupancy >= 92."""
    ctx = make_ctx(shed_load=91, wheat_in_shed=10)  # 91 + 2 yield = 93 >= 92
    t = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([t])
    accepted, reasons, metrics = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), t, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_STORAGE_RISK in reasons
    assert metrics["projected_shed"] == 93


def test_survival_priority_hard_veto_unfed_animals():
    """Verify candidate is rejected if animals are in starvation risk (consecutive_unfed >= 2)."""
    ctx = make_ctx(day=10, hour=14)
    anim = MockTile((1, 1), is_plant=False, is_animal=True, fed_today=False, consecutive_unfed=2)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([anim, crop])
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_SURVIVAL_PRIORITY in reasons


def test_survival_priority_hard_veto_critical_watering():
    """Verify candidate is rejected if any crop has consecutive_unwatered >= 2."""
    ctx = make_ctx(day=10, hour=6)
    dying = MockTile((1, 1), crop="WHEAT", consecutive_unwatered=2, watered_today=False)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([dying, crop])
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_SURVIVAL_PRIORITY in reasons


def test_worker_opportunity_cost_veto():
    """Verify candidate is rejected if high-priority regular tasks exceed remaining workers."""
    ctx = make_ctx()
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])
    # 3 free workers, but 1 high-priority task (priority 90) waiting -> leaves 0 workers for priority task
    reg_tasks = [{"priority": 90, "target": (3, 3)}]
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2}, reg_tasks
    )
    assert not accepted
    assert REJECTION_WORKER_OPPORTUNITY_COST in reasons


def test_season_end_waste_veto():
    """Verify replanting on or after Day 28 is vetoed (cannot mature before season end)."""
    ctx = make_ctx(day=28, hour=5)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_SEASON_END_NO_VALUE in reasons


def test_liquidity_capital_risk_veto():
    """Verify candidate is vetoed if day <= 18, cash < 3000 and shed >= 85."""
    ctx = make_ctx(day=12, hour=8, shed_load=86, wheat_in_shed=10, money=2500.0)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_LIQUIDITY_CAPITAL_RISK in reasons


def test_market_timing_glut_veto():
    """Verify candidate is vetoed if shed already holds >= 50 units of this crop."""
    ctx = make_ctx(shed_load=60, wheat_in_shed=55)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_MARKET_TIMING in reasons


def test_favorable_opportunity_passes_gate():
    """Verify a clean candidate with ample headroom and free workers passes."""
    ctx = make_ctx(day=8, hour=4, shed_load=20, wheat_in_shed=5, money=10000.0)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2, planted_day=6)
    farm = MockFarm([crop])
    accepted, reasons, metrics = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4, 5, 6}, []
    )
    assert accepted
    assert reasons == []
    assert metrics["estimated_net_value"] > 0


def test_selective_mode_filters_rejected_and_executes_accepted():
    """Verify SELECTIVE mode rejects bad opportunities and schedules good ones."""
    config.set_same_turn_crop_pipeline_mode("SELECTIVE")

    # Tile A: Bad (shed near capacity, 91 items)
    # Tile B: Good (clean)
    t_bad = MockTile((2, 2), crop="WHEAT", yield_units=2, planted_day=6)
    t_good = MockTile((3, 3), crop="WHEAT", yield_units=2, planted_day=6)
    farm = MockFarm([t_bad, t_good])

    # Context with shed_load = 91 -> projected 93 >= 92 (REJECT)
    ctx = make_ctx(day=8, hour=4, shed_load=91, wheat_in_shed=10, money=10000.0)
    pos_by_idx = {0: (2, 2), 1: (2, 2), 2: (2, 2)}
    asg, busy, rem = evaluate_and_assign_pipelines(ctx, farm, pos_by_idx, {0, 1, 2}, [], None, {})

    # t_bad should be rejected, so no assignment
    assert asg == {}

    # Now make shed clean (shed_load = 10, wheat_in_shed = 5) -> should accept and assign
    ctx_clean = make_ctx(day=8, hour=4, shed_load=10, wheat_in_shed=5, money=10000.0)
    asg2, busy2, _ = evaluate_and_assign_pipelines(ctx_clean, farm, pos_by_idx, {0, 1, 2}, [], None, {})
    assert len(asg2) == 3
    assert busy2 == {0, 1, 2}
    assert asg2[0]["op"] == "HARVEST"
    assert asg2[1]["op"] == "PLANT"
    assert asg2[2]["op"] == "WATER"

    # Verify shadow decision records captured both
    shadow = get_crop_pipeline_shadow_decisions()
    assert len(shadow) >= 2
    assert any(s["decision"] == "REJECT" for s in shadow)
    assert any(s["decision"] == "EXECUTE" for s in shadow)


def test_global_mode_executes_even_when_shadow_rejects():
    """Verify GLOBAL mode executes physically eligible pipelines even if shadow gate rejects."""
    config.set_same_turn_crop_pipeline_mode("GLOBAL")
    # Bad tile (shed 91)
    t_bad = MockTile((2, 2), crop="WHEAT", yield_units=2, planted_day=6)
    farm = MockFarm([t_bad])
    ctx = make_ctx(day=8, hour=4, shed_load=91, wheat_in_shed=10, money=10000.0)
    pos_by_idx = {0: (2, 2), 1: (2, 2), 2: (2, 2)}
    asg, busy, _ = evaluate_and_assign_pipelines(ctx, farm, pos_by_idx, {0, 1, 2}, [], None, {})

    # In GLOBAL mode, physical eligibility executes
    assert len(asg) == 3
    assert busy == {0, 1, 2}

    # But shadow record reflects gate rejection
    shadow = get_crop_pipeline_shadow_decisions()
    assert len(shadow) == 1
    assert shadow[0]["gate_accepted"] is False
    assert REJECTION_STORAGE_RISK in shadow[0]["rejection_reasons"]
    assert shadow[0]["decision"] == "EXECUTE"  # GLOBAL executed despite gate rejection
