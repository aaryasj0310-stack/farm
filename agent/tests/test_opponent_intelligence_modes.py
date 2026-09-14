"""Unit tests for Opponent Intelligence experiment modes (O0, O1, O1_SHADOW, O1R)."""

import pytest
import config
from main import _build_opp_advice, set_opponent_intelligence_mode, get_opponent_intelligence_mode
from strategy.opponent_advisor import OpponentAdvice
from observation_parser import FarmView


def _mock_farm_with_crops():
    grid = [[None for _ in range(10)] for _ in range(10)]
    grid[0][0] = {
        "kind": "PLANT", "x": 0, "y": 0, "crop": "MELON", "planted_day": 0,
        "yield_units": 0, "watered_today": True, "consecutive_unwatered": 0,
        "fertilized_until_day": -1, "animal": None, "fed_today": False,
        "cared_today": False, "consecutive_unfed": 0, "fertilizer_available": False,
        "pending_care_bonus": 0, "placed_day": None,
    }
    raw = {
        "money": 1000,
        "tiles": grid,
        "farmer": (4, 4),
        "hands": [],
        "unlocked_quadrants": ["NW"],
        "hires_today": 0,
    }
    return FarmView(raw)


def test_opponent_intelligence_mode_setter():
    config.set_opponent_intelligence_mode("O0")
    assert config.get_opponent_intelligence_mode() == "O0"
    assert config.SHADOW_OPPONENT_FORECAST_ENABLED is False

    config.set_opponent_intelligence_mode("O1")
    assert config.get_opponent_intelligence_mode() == "O1"
    assert config.SHADOW_OPPONENT_FORECAST_ENABLED is False

    config.set_opponent_intelligence_mode("O1_SHADOW")
    assert config.get_opponent_intelligence_mode() == "O1_SHADOW"
    assert config.SHADOW_OPPONENT_FORECAST_ENABLED is True

    config.set_opponent_intelligence_mode("O1R")
    assert config.get_opponent_intelligence_mode() == "O1R"

    with pytest.raises(ValueError):
        config.set_opponent_intelligence_mode("INVALID_MODE")

    # Reset to O1 baseline
    config.set_opponent_intelligence_mode("O1")


def test_o0_returns_empty_advice():
    opp_farm = _mock_farm_with_crops()
    ctx = {
        "day": 5, "hour": 2, "step": 122,
        "opponent_farm": opp_farm,
        "farm": opp_farm,
        "private": {"shed": {"MELON": 10}},
        "town": {"unlocked_shops": []},
        "market": {"inventory": {"MELON": 10000}},
    }
    mem = {}

    # Under O0: advice must be completely empty
    config.set_opponent_intelligence_mode("O0")
    advice = _build_opp_advice(ctx, mem)
    assert isinstance(advice, OpponentAdvice)
    assert advice.supply_adjustment == {}
    assert advice.preempt_sell == []
    assert advice.delay_sell == []
    assert advice.counter_pick == []
    assert advice.opp_shed_pressure == 0.0

    # Under O1: advice has supply adjustment populated for Melon
    config.set_opponent_intelligence_mode("O1")
    advice_o1 = _build_opp_advice(ctx, mem)
    assert "MELON" in advice_o1.supply_adjustment
    assert advice_o1.supply_adjustment["MELON"] > 0

    # Under O0_SHADOW: advice must be completely empty, shadow forecaster updated
    config.set_opponent_intelligence_mode("O0_SHADOW")
    assert config.SHADOW_OPPONENT_FORECAST_ENABLED is True
    advice_shadow = _build_opp_advice(ctx, mem)
    assert isinstance(advice_shadow, OpponentAdvice)
    assert advice_shadow.supply_adjustment == {}
    assert advice_shadow.preempt_sell == []
    assert advice_shadow.delay_sell == []
    assert advice_shadow.counter_pick == []
    assert advice_shadow.opp_shed_pressure == 0.0

    # Reset to O0
    config.set_opponent_intelligence_mode("O0")


def test_ablation_modes_isolation():
    opp_farm = _mock_farm_with_crops()
    ctx = {
        "day": 5, "hour": 2, "step": 122,
        "opponent_farm": opp_farm,
        "farm": opp_farm,
        "private": {"shed": {"MELON": 10}},
        "town": {"unlocked_shops": [{"shop": "MELON_BAR", "product": "MELON", "demand_bonus": 0.5}]},
        "market": {"inventory": {"MELON": 10000}},
    }
    mem = {
        "opp_sales_history": [(120, "MELON", 50.0)],
        "opp_sales_step": {"MELON": 50.0},
    }

    # A0: completely empty
    config.set_opponent_intelligence_mode("A0")
    adv_a0 = _build_opp_advice(ctx, mem)
    assert adv_a0.supply_adjustment == {}
    assert adv_a0.preempt_sell == []
    assert adv_a0.delay_sell == []

    # A1: commitments only (counter-pick)
    config.set_opponent_intelligence_mode("A1")
    adv_a1 = _build_opp_advice(ctx, mem)
    assert adv_a1.supply_adjustment == {}
    assert adv_a1.delay_sell == []
    assert adv_a1.preempt_sell == []

    # A2: recent sales delay only
    config.set_opponent_intelligence_mode("A2")
    adv_a2 = _build_opp_advice(ctx, mem)
    assert adv_a2.supply_adjustment == {}
    assert adv_a2.counter_pick == []
    assert adv_a2.opp_shed_pressure == 0.0

    # A3: production forecast only
    config.set_opponent_intelligence_mode("A3")
    adv_a3 = _build_opp_advice(ctx, mem)
    assert "MELON" in adv_a3.supply_adjustment
    assert adv_a3.delay_sell == []
    assert adv_a3.counter_pick == []

    # A4: high-confidence bounds only
    config.set_opponent_intelligence_mode("A4")
    adv_a4 = _build_opp_advice(ctx, mem)
    assert adv_a4.supply_adjustment == {}
    assert adv_a4.delay_sell == []
    assert adv_a4.counter_pick == []

    # Reset to O1 baseline
    config.set_opponent_intelligence_mode("O1")

