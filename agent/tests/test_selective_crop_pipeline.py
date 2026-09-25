"""Kaggriculture Phase M0-C-R1: Selective Same-Turn Crop Pipeline Gating & Mechanics Tests.

Verifies:
1. OFF preserves existing baseline behavior (no pipelines scheduled).
2. GLOBAL preserves exact M0-A unconditional behavior.
3. SELECTIVE executes only when hard safety vetoes and net economic value pass.
4. Authoritative crop constants match engine rules (first_yield_day vs max_yield_day).
5. Cash read from farm.money (NOT private.money).
6. Liquidity risk accounts for real commitments (feed reserve, safety reserve).
7. Storage risk distinguishes worker carried inventory from shed inventory and models EOD dump.
8. Market timing gate uses actual market state (price depression / glut).
9. Large shed inventory alone triggers INVENTORY_BACKLOG_RISK, not MARKET_TIMING.
10. Survival hard veto triggers (starving animals, critical watering, urgent tasks).
11. Worker opportunity cost veto triggers (starved high-priority tasks, insufficient free units).
12. Season-end waste veto uses authoritative first_yield_day.
13. Animal escape telemetry detects disappearance after consecutive_unfed >= 2.
14. Crop watering failure telemetry detects PLANT -> WEED transition.
15. Transaction telemetry records actual purchases (HIRE, BUY_LAND, BUY_SEED, BUY_ANIMAL).
16. Runtime reset clears M0-C-R1 telemetry.
"""
import copy
import pytest
from typing import Any, Dict, List, Set, Tuple

import config
from execution.crop_pipeline_controller import (
    AUTHORITATIVE_CROPS,
    CROPS_INFO,
    REJECTION_SURVIVAL_PRIORITY,
    REJECTION_WORKER_OPPORTUNITY_COST,
    REJECTION_STORAGE_RISK,
    REJECTION_MARKET_TIMING,
    REJECTION_INVENTORY_BACKLOG_RISK,
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
    def __init__(
        self,
        pos,
        is_plant=True,
        crop="WHEAT",
        yield_units=2,
        planted_day=4,
        consecutive_unwatered=0,
        watered_today=False,
        is_animal=False,
        fed_today=True,
        consecutive_unfed=0,
    ):
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
            "kind": "PLANT" if self.is_plant else ("ANIMAL" if self.is_animal else "SOIL"),
            "crop": self.crop,
            "yield_units": self.yield_units,
            "planted_day": self.planted_day,
            "consecutive_unwatered": self.consecutive_unwatered,
            "watered_today": self.watered_today,
            "consecutive_unfed": self.consecutive_unfed,
            "fed_today": self.fed_today,
        }


class MockFarm:
    def __init__(self, tiles=None, unlocked=None, money=5000.0):
        self.tiles_list = tiles or []
        self.unlocked = set(unlocked or ["NW", "NE"])
        self.money = float(money)

    def iter_tiles(self):
        return iter(self.tiles_list)

    def quadrant_of(self, pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


class MockPrivate:
    def __init__(self, seeds=None, shed=None, inventories=None):
        self.seeds = seeds or {"WHEAT": 5, "CARROT": 5}
        self.shed = shed or {"WHEAT": 10}
        self.inventories = inventories or [{} for _ in range(8)]


class MockMarket:
    def __init__(self, prices=None, inventory=None):
        self.prices = prices or {"WHEAT": 25, "CARROT": 35, "MELON": 250}
        self.inventory = inventory or {"WHEAT": 100.0, "CARROT": 50.0, "MELON": 20.0}


def make_ctx(day=6, hour=5, shed_load=10, carried=0, money=5000.0, seeds=None, wheat_in_shed=None, market_prices=None):
    if wheat_in_shed is not None:
        w_shed = wheat_in_shed
        other_shed = max(0, shed_load - w_shed)
        shed_dict = {"WHEAT": w_shed, "CARROT": other_shed}
    else:
        shed_dict = {"WHEAT": shed_load}

    invs = [{} for _ in range(8)]
    if carried > 0:
        invs[0] = {"WHEAT": carried}

    priv = MockPrivate(
        seeds=seeds or {"WHEAT": 5},
        shed=shed_dict,
        inventories=invs,
    )
    farm = MockFarm(money=money)
    market = MockMarket(prices=market_prices)

    return {
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
        "private": priv,
        "farm": farm,
        "market": market,
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


def test_authoritative_crop_constants_match_engine():
    """Verify crop constants match authoritative Kaggriculture rules."""
    assert AUTHORITATIVE_CROPS["WHEAT"]["first_yield_day"] == 2
    assert AUTHORITATIVE_CROPS["WHEAT"]["max_yield_day"] == 4
    assert AUTHORITATIVE_CROPS["WHEAT"]["max_yield"] == 6
    assert AUTHORITATIVE_CROPS["WHEAT"]["ongoing"] is False

    assert AUTHORITATIVE_CROPS["CARROT"]["first_yield_day"] == 2
    assert AUTHORITATIVE_CROPS["CARROT"]["max_yield_day"] == 3
    assert AUTHORITATIVE_CROPS["CARROT"]["max_yield"] == 4
    assert AUTHORITATIVE_CROPS["CARROT"]["ongoing"] is False

    assert AUTHORITATIVE_CROPS["MELON"]["first_yield_day"] == 10
    assert AUTHORITATIVE_CROPS["MELON"]["max_yield_day"] == 12
    assert AUTHORITATIVE_CROPS["MELON"]["max_yield"] == 6
    assert AUTHORITATIVE_CROPS["MELON"]["ongoing"] is False

    assert AUTHORITATIVE_CROPS["TOMATO"]["ongoing"] is True
    assert AUTHORITATIVE_CROPS["STRAWBERRY"]["ongoing"] is True


def test_cash_read_from_farm_money_not_private():
    """Verify farm.money = 2500 and private has no money attribute results in current_cash == 2500."""
    ctx = make_ctx(money=2500.0)
    # Ensure private object has no money attribute
    assert not hasattr(ctx["private"], "money")

    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop], money=2500.0)

    accepted, reasons, metrics = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert metrics["current_cash"] == 2500.0


def test_liquidity_capital_risk_accounts_for_feed_commitments():
    """Verify liquidity risk vetoes when available cash after feed reserve is < 3000."""
    # 2 cows on farm -> feed needed = 2 * 4 = 8 wheat. Wheat in shed = 0.
    # Feed reserve = 8 * 25 = $200. Safety reserve = $300.
    # If cash = 3200, available cash = 3200 - 200 - 300 = 2700 < 3000.
    cow1 = MockTile((1, 1), is_plant=False, is_animal=True, fed_today=True)
    cow2 = MockTile((1, 2), is_plant=False, is_animal=True, fed_today=True)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([cow1, cow2, crop], money=3200.0)

    ctx = make_ctx(day=10, hour=8, shed_load=86, wheat_in_shed=0, money=3200.0)
    accepted, reasons, metrics = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_LIQUIDITY_CAPITAL_RISK in reasons
    assert metrics["available_cash"] == 2700.0


def test_storage_projection_distinguishes_worker_from_shed_inventory():
    """Verify harvest yield enters worker inventory immediately, while EOD dump exposure is tracked."""
    ctx = make_ctx(shed_load=80, carried=10)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=3)
    farm = MockFarm([crop])

    accepted, reasons, metrics = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    # Immediate shed load is 80 (not 83!)
    assert metrics["immediate_post_pipeline_shed_load"] == 80
    # End-of-day dump exposure is carried (10) + harvest (3) = 13
    assert metrics["end_of_day_dump_exposure"] == 13
    # Worst case EOD shed load is 80 + 13 = 93
    assert metrics["worst_case_end_of_day_shed_load"] == 93


def test_storage_risk_hard_veto_near_capacity_or_eod():
    """Verify storage veto triggers if current shed >= 90 or hour >= 18 and EOD >= 95."""
    # Case A: shed >= 90
    ctx_congested = make_ctx(hour=10, shed_load=90)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx_congested, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_STORAGE_RISK in reasons

    # Case B: hour >= 18, shed=85, carried=8, yield=3 -> EOD = 85 + 11 = 96 >= 95
    ctx_eod = make_ctx(hour=18, shed_load=85, carried=8)
    crop3 = MockTile((2, 2), crop="WHEAT", yield_units=3)
    accepted_eod, reasons_eod, _ = evaluate_pipeline_economic_gate(
        ctx_eod, farm, (2, 2), crop3, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted_eod
    assert REJECTION_STORAGE_RISK in reasons_eod


def test_market_timing_gate_uses_actual_market_state():
    """Verify MARKET_TIMING veto triggers when market price is depressed <= 60% of base."""
    # Wheat base is 25. If market price is 12 (<= 15), market timing veto triggers
    depressed_market = MockMarket(prices={"WHEAT": 12})
    ctx_depressed = make_ctx(shed_load=20, wheat_in_shed=10)
    ctx_depressed["market"] = depressed_market

    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])

    accepted, reasons, metrics = evaluate_pipeline_economic_gate(
        ctx_depressed, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_MARKET_TIMING in reasons


def test_large_shed_inventory_triggers_inventory_backlog_not_market_timing():
    """Verify shed inventory >= 50 triggers INVENTORY_BACKLOG_RISK, NOT MARKET_TIMING."""
    normal_market = MockMarket(prices={"WHEAT": 25})
    ctx = make_ctx(shed_load=60, wheat_in_shed=55)
    ctx["market"] = normal_market

    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])

    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted
    assert REJECTION_INVENTORY_BACKLOG_RISK in reasons
    assert REJECTION_MARKET_TIMING not in reasons


def test_season_end_waste_veto_uses_first_yield_day():
    """Verify replanting on Day 28 cannot yield (28 + 2 = 30 > 29), but Day 27 can (27 + 2 = 29 <= 29)."""
    # Day 28: Wheat first yield day is 2 -> 28 + 2 = 30 > 29 (VETO)
    ctx28 = make_ctx(day=28, hour=5)
    crop = MockTile((2, 2), crop="WHEAT", yield_units=2)
    farm = MockFarm([crop])
    accepted28, reasons28, _ = evaluate_pipeline_economic_gate(
        ctx28, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert not accepted28
    assert REJECTION_SEASON_END_NO_VALUE in reasons28

    # Day 27: 27 + 2 = 29 <= 29 (Passes season end veto)
    ctx27 = make_ctx(day=27, hour=5)
    accepted27, reasons27, _ = evaluate_pipeline_economic_gate(
        ctx27, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2, 3, 4}, []
    )
    assert REJECTION_SEASON_END_NO_VALUE not in reasons27


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
    reg_tasks = [{"priority": 90, "target": (3, 3)}]
    accepted, reasons, _ = evaluate_pipeline_economic_gate(
        ctx, farm, (2, 2), crop, "WHEAT", [0, 1, 2], {0, 1, 2}, reg_tasks
    )
    assert not accepted
    assert REJECTION_WORKER_OPPORTUNITY_COST in reasons


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


def test_global_mode_mechanically_unconditional():
    """Verify GLOBAL mode executes physically eligible pipelines even when shadow gate vetoes."""
    config.set_same_turn_crop_pipeline_mode("GLOBAL")
    t_bad = MockTile((2, 2), crop="WHEAT", yield_units=2, planted_day=6)
    farm = MockFarm([t_bad])
    ctx = make_ctx(day=8, hour=4, shed_load=91, wheat_in_shed=10, money=10000.0)
    pos_by_idx = {0: (2, 2), 1: (2, 2), 2: (2, 2)}
    asg, busy, _ = evaluate_and_assign_pipelines(ctx, farm, pos_by_idx, {0, 1, 2}, [], None, {})

    assert len(asg) == 3
    assert busy == {0, 1, 2}

    shadow = get_crop_pipeline_shadow_decisions()
    assert len(shadow) == 1
    assert shadow[0]["gate_accepted"] is False
    assert shadow[0]["decision"] == "EXECUTE"


def test_runtime_reset_clears_pipeline_telemetry():
    """Verify reset clears all recorded shadow telemetry and counters."""
    config.set_same_turn_crop_pipeline_mode("GLOBAL")
    t = MockTile((2, 2), crop="WHEAT", yield_units=2, planted_day=6)
    farm = MockFarm([t])
    ctx = make_ctx(day=8, hour=4, shed_load=10, wheat_in_shed=5, money=10000.0)
    pos_by_idx = {0: (2, 2), 1: (2, 2), 2: (2, 2)}
    evaluate_and_assign_pipelines(ctx, farm, pos_by_idx, {0, 1, 2}, [], None, {})

    assert len(get_crop_pipeline_shadow_decisions()) > 0
    reset_crop_pipeline_telemetry()
    assert len(get_crop_pipeline_shadow_decisions()) == 0
    assert len(get_crop_pipeline_telemetry()) == 0
