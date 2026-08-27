"""Unit tests for opponent_advisor.py (Phase 5 — Tactical Advisor).

Covers:
  - OpponentAdvice dataclass defaults and to_dict
  - Supply adjustment: opp production projected into future supply
  - Pre-emptive sell: high opp sell probability + our stock -> flag
  - Delay sell: depressed price + recent opp dump -> hold
  - Counter-pick: shop demand with zero opp commitment -> monopoly
  - Clean defaults for empty/unavailable opponent state
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT = os.path.dirname(_HERE)
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "state"))
sys.path.insert(0, os.path.join(_AGENT, "strategy"))
sys.path.insert(0, os.path.join(_AGENT, "execution"))
sys.path.insert(0, os.path.join(_AGENT, "market"))

from opponent_advisor import (
    OpponentAdvice,
    build_opponent_advice,
    _compute_supply_adjustment,
    _compute_preempt_sell,
    _compute_delay_sell,
    _compute_counter_pick,
    SUPPLY_PROJECTION_DAYS,
    SUPPLY_ADJUSTMENT_WEIGHT,
    PREEMPT_SELL_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_ctx(day=5, hour=1, our_shed=None, market_inv=None):
    """Build a minimal ctx dict for the advisor."""
    return {
        "day": day,
        "hour": hour,
        "private": {"shed": our_shed or {}},
        "market": {"inventory": market_inv or {}},
        "farm": None,  # not used directly by advisor
    }


def _mk_opp_state(estimated_shed=None, sell_probs=None, opp_sales_inferred=None,
                   shed_pressure=0.0, forecast=None, commitments=None,
                   animal_counts=None):
    """Build a minimal opp_state dict for the advisor."""
    return {
        "estimated_shed": estimated_shed or {},
        "sell_probs": sell_probs or {},
        "opp_sales_inferred": opp_sales_inferred or {},
        "shed_pressure": shed_pressure,
        "forecast": forecast or {},
        "commitments": commitments or {},
        "animal_counts": animal_counts or {},
    }


# ===== OpponentAdvice DATACLASS TESTS =====

class TestOpponentAdviceDataclass:
    def test_default_fields(self):
        advice = OpponentAdvice()
        assert advice.supply_adjustment == {}
        assert advice.preempt_sell == []
        assert advice.delay_sell == []
        assert advice.counter_pick == []
        assert advice.opp_shed_pressure == 0.0

    def test_to_dict_roundtrip(self):
        advice = OpponentAdvice(
            supply_adjustment={"MELON": 3.0},
            preempt_sell=["EGG"],
            delay_sell=["WHEAT"],
            counter_pick=["CARROT"],
            opp_shed_pressure=0.75,
        )
        d = advice.to_dict()
        assert d["supply_adjustment"]["MELON"] == 3.0
        assert d["preempt_sell"] == ["EGG"]
        assert d["delay_sell"] == ["WHEAT"]
        assert d["counter_pick"] == ["CARROT"]
        assert d["opp_shed_pressure"] == 0.75

    def test_to_dict_empty(self):
        advice = OpponentAdvice()
        d = advice.to_dict()
        assert d["supply_adjustment"] == {}
        assert d["preempt_sell"] == []
        assert d["delay_sell"] == []
        assert d["counter_pick"] == []
        assert d["opp_shed_pressure"] == 0.0

    def test_to_dict_clamps_pressure(self):
        advice = OpponentAdvice(opp_shed_pressure=1.5)
        d = advice.to_dict()
        assert d["opp_shed_pressure"] == 1.0


# ===== SUPPLY ADJUSTMENT TESTS =====

class TestSupplyAdjustment:
    def test_opponent_melon_production_adds_to_adj(self):
        """Opponent has 10 melon tiles -> expected future melon volume."""
        forecast = {"MELON": {17: 60.0}}  # e.g. 10 tiles x 6 units
        adj = _compute_supply_adjustment(forecast, current_day=5)
        expected = 60.0 * SUPPLY_ADJUSTMENT_WEIGHT
        assert adj["MELON"] == pytest.approx(expected, abs=0.01)

    def test_projection_within_horizon(self):
        """Only production within SUPPLY_PROJECTION_DAYS is included."""
        forecast = {
            "WHEAT": {8: 12.0, 12: 12.0},  # both within horizon of day 5
        }
        adj = _compute_supply_adjustment(forecast, current_day=5)
        expected = (12.0 + 12.0) * SUPPLY_ADJUSTMENT_WEIGHT
        assert adj["WHEAT"] == pytest.approx(expected, abs=0.01)

    def test_beyond_horizon_excluded(self):
        """Production beyond horizon is excluded."""
        forecast = {
            "WHEAT": {8: 12.0, 20: 12.0},  # day 20 > day 5 + 12 = 17
        }
        adj = _compute_supply_adjustment(forecast, current_day=5)
        # Only day 8 is within horizon
        expected = 12.0 * SUPPLY_ADJUSTMENT_WEIGHT
        assert adj["WHEAT"] == pytest.approx(expected, abs=0.01)

    def test_multiple_products(self):
        """Multiple products are adjusted independently."""
        forecast = {
            "MELON": {17: 60.0},
            "WHEAT": {8: 24.0},
            "EGG": {6: 10.0, 7: 10.0},
        }
        adj = _compute_supply_adjustment(forecast, current_day=5)
        assert "MELON" in adj
        assert "WHEAT" in adj
        assert "EGG" in adj
        assert adj["EGG"] == pytest.approx(
            (10.0 + 10.0) * SUPPLY_ADJUSTMENT_WEIGHT, abs=0.01,
        )

    def test_empty_forecast_returns_empty(self):
        assert _compute_supply_adjustment({}, 5) == {}

    def test_none_forecast_returns_empty(self):
        assert _compute_supply_adjustment(None, 5) == {}

    def test_past_harvest_excluded(self):
        """Harvests before current_day are excluded."""
        forecast = {"WHEAT": {3: 12.0, 8: 12.0}}
        adj = _compute_supply_adjustment(forecast, current_day=5)
        # day 3 < current_day 5 -> excluded; day 8 -> included
        expected = 12.0 * SUPPLY_ADJUSTMENT_WEIGHT
        assert adj["WHEAT"] == pytest.approx(expected, abs=0.01)

    def test_zero_production_not_included(self):
        forecast = {"MELON": {10: 0.0}}
        adj = _compute_supply_adjustment(forecast, current_day=5)
        assert "MELON" not in adj


# ===== PREEMPT SELL TESTS =====

class TestPreemptSell:
    def test_high_prob_and_stock_triggers_flag(self):
        """Opp sell prob >= 0.65 + our melon stock -> preempt flag."""
        sell_probs = {"MELON": 0.80, "WHEAT": 0.30}
        our_shed = {"MELON": 5, "WHEAT": 10}
        result = _compute_preempt_sell(sell_probs, our_shed)
        assert "MELON" in result
        assert "WHEAT" not in result

    def test_high_prob_no_stock_not_flagged(self):
        """Opp sell prob high but our stock is 0 -> not flagged."""
        sell_probs = {"MELON": 0.80}
        our_shed = {"MELON": 0}
        result = _compute_preempt_sell(sell_probs, our_shed)
        assert "MELON" not in result

    def test_low_prob_not_flagged(self):
        """Opp sell prob < 0.65 -> not flagged even with stock."""
        sell_probs = {"MELON": 0.50}
        our_shed = {"MELON": 5}
        result = _compute_preempt_sell(sell_probs, our_shed)
        assert "MELON" not in result

    def test_threshold_boundary(self):
        """Exactly at threshold -> included."""
        sell_probs = {"MELON": PREEMPT_SELL_THRESHOLD}
        our_shed = {"MELON": 3}
        result = _compute_preempt_sell(sell_probs, our_shed)
        assert "MELON" in result

    def test_sorted_by_probability(self):
        """Results sorted by descending sell probability."""
        sell_probs = {"EGG": 0.90, "MELON": 0.75, "WOOL": 0.66}
        our_shed = {"EGG": 2, "MELON": 3, "WOOL": 4}
        result = _compute_preempt_sell(sell_probs, our_shed)
        assert result == ["EGG", "MELON", "WOOL"]

    def test_empty_sell_probs(self):
        assert _compute_preempt_sell({}, {"MELON": 5}) == []

    def test_empty_shed(self):
        sell_probs = {"MELON": 0.80}
        assert _compute_preempt_sell(sell_probs, {}) == []

    def test_multiple_high_prob_products(self):
        """Multiple products with high prob and stock."""
        sell_probs = {"MELON": 0.80, "EGG": 0.70, "STRAWBERRY": 0.90}
        our_shed = {"MELON": 3, "EGG": 5, "STRAWBERRY": 2}
        result = _compute_preempt_sell(sell_probs, our_shed)
        assert "STRAWBERRY" in result
        assert "MELON" in result
        assert "EGG" in result


# ===== DELAY SELL TESTS =====

class TestDelaySell:
    def test_recent_dump_and_depressed_price_triggers_hold(self):
        """Opponent dumped tomatoes recently, price is depressed -> hold."""
        opp_sales = {"TOMATO": 8.0}
        our_shed = {"TOMATO": 4}
        forecast = {"TOMATO": {5: 20.0}}  # expected price ~20
        # High inventory -> price floor ($1) -> depressed below 80% of 20
        ctx = _mk_ctx(day=5, our_shed=our_shed,
                      market_inv={"TOMATO": 50000})
        result = _compute_delay_sell(opp_sales, our_shed, forecast, 5, ctx)
        assert "TOMATO" in result

    def test_no_dump_no_hold(self):
        """No opponent sales -> no delay flag."""
        opp_sales = {}
        our_shed = {"TOMATO": 4}
        forecast = {"TOMATO": {5: 20.0}}
        ctx = _mk_ctx(day=5, our_shed=our_shed,
                      market_inv={"TOMATO": 10000})
        result = _compute_delay_sell(opp_sales, our_shed, forecast, 5, ctx)
        assert "TOMATO" not in result

    def test_dump_but_no_stock_no_hold(self):
        """Opponent dumped but we have no stock -> not flagged."""
        opp_sales = {"TOMATO": 8.0}
        our_shed = {}
        forecast = {"TOMATO": {5: 20.0}}
        ctx = _mk_ctx(day=5, our_shed=our_shed,
                      market_inv={"TOMATO": 10000})
        result = _compute_delay_sell(opp_sales, our_shed, forecast, 5, ctx)
        assert "TOMATO" not in result

    def test_dump_but_price_healthy_no_hold(self):
        """Opponent dumped but price is still healthy -> not delayed."""
        opp_sales = {"TOMATO": 2.0}
        our_shed = {"TOMATO": 4}
        forecast = {"TOMATO": {5: 20.0}}
        # Low inventory = high price ($452k+) -> price NOT depressed
        ctx = _mk_ctx(day=5, our_shed=our_shed,
                      market_inv={"TOMATO": 100})
        result = _compute_delay_sell(opp_sales, our_shed, forecast, 5, ctx)
        assert "TOMATO" not in result

    def test_zero_opponent_units_ignored(self):
        opp_sales = {"TOMATO": 0.0}
        our_shed = {"TOMATO": 4}
        forecast = {"TOMATO": {5: 20.0}}
        ctx = _mk_ctx(day=5, our_shed=our_shed,
                      market_inv={"TOMATO": 50000})
        result = _compute_delay_sell(opp_sales, our_shed, forecast, 5, ctx)
        assert "TOMATO" not in result


# ===== COUNTER-PICK TESTS =====

class TestCounterPick:
    def test_pet_cafe_carrot_demand_opp_no_carrots(self):
        """PET_CAFE demands carrot, opponent has 0 carrots -> counter-pick."""
        boosts = {"CARROT": 1.0}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {"WHEAT": 10, "MELON": 5}},
        )
        result = _compute_counter_pick(boosts, opp_state)
        assert "CARROT" in result

    def test_opp_has_carrots_not_counter_picked(self):
        """Opponent has carrots -> not a counter-pick opportunity."""
        boosts = {"CARROT": 1.0}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {"CARROT": 5, "WHEAT": 10}},
        )
        result = _compute_counter_pick(boosts, opp_state)
        assert "CARROT" not in result

    def test_zero_demand_not_counter_picked(self):
        """Zero demand -> not a counter-pick."""
        boosts = {"CARROT": 0.0}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {}},
        )
        result = _compute_counter_pick(boosts, opp_state)
        assert "CARROT" not in result

    def test_multiple_demands_opp_ignores(self):
        """Multiple demanded products opponent ignores."""
        boosts = {"CARROT": 0.5, "STRAWBERRY": 0.3}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {"WHEAT": 10}},
        )
        result = _compute_counter_pick(boosts, opp_state)
        assert "CARROT" in result
        assert "STRAWBERRY" in result

    def test_animal_product_counter_pick(self):
        """Opponent has no geese -> EGG is counter-pick if demanded."""
        boosts = {"EGG": 0.5}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {"WHEAT": 5}},
            animal_counts={},
        )
        result = _compute_counter_pick(boosts, opp_state)
        assert "EGG" in result

    def test_animal_product_opp_has_geese_not_counter_picked(self):
        """Opponent has geese -> EGG not a counter-pick."""
        boosts = {"EGG": 0.5}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {}},
            animal_counts={"GOOSE": 3},
        )
        result = _compute_counter_pick(boosts, opp_state)
        assert "EGG" not in result

    def test_empty_boosts(self):
        assert _compute_counter_pick({}, _mk_opp_state()) == []

    def test_sorted_output(self):
        """Results are sorted alphabetically."""
        boosts = {"STRAWBERRY": 0.5, "CARROT": 0.3, "EGG": 0.4}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {}},
            animal_counts={},
        )
        result = _compute_counter_pick(boosts, opp_state)
        assert result == ["CARROT", "EGG", "STRAWBERRY"]


# ===== FULL build_opponent_advice INTEGRATION TESTS =====

class TestBuildOpponentAdvice:
    def test_empty_opp_state_clean_defaults(self):
        """Empty opponent state returns safe defaults."""
        advice = build_opponent_advice(
            _mk_opp_state(), _mk_ctx(), {},
        )
        assert advice.supply_adjustment == {}
        assert advice.preempt_sell == []
        assert advice.delay_sell == []
        assert advice.counter_pick == []
        assert advice.opp_shed_pressure == 0.0

    def test_none_ctx_clean_defaults(self):
        advice = build_opponent_advice(_mk_opp_state(), None, {})
        assert advice.supply_adjustment == {}
        assert advice.opp_shed_pressure == 0.0

    def test_supply_adjustment_populated(self):
        forecast = {"MELON": {17: 60.0}}
        advice = build_opponent_advice(
            _mk_opp_state(forecast=forecast),
            _mk_ctx(day=5),
            forecast,
        )
        expected = 60.0 * SUPPLY_ADJUSTMENT_WEIGHT
        assert advice.supply_adjustment["MELON"] == pytest.approx(
            expected, abs=0.01,
        )

    def test_preempt_sell_populated(self):
        sell_probs = {"MELON": 0.80}
        our_shed = {"MELON": 5}
        advice = build_opponent_advice(
            _mk_opp_state(sell_probs=sell_probs),
            _mk_ctx(our_shed=our_shed),
            {},
        )
        assert "MELON" in advice.preempt_sell

    def test_counter_pick_populated(self):
        boosts = {"CARROT": 1.0}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {"WHEAT": 10}},
        )
        advice = build_opponent_advice(opp_state, _mk_ctx(), {}, boosts=boosts)
        assert "CARROT" in advice.counter_pick

    def test_shed_pressure_passthrough(self):
        advice = build_opponent_advice(
            _mk_opp_state(shed_pressure=0.85),
            _mk_ctx(),
            {},
        )
        assert advice.opp_shed_pressure == 0.85

    def test_shed_pressure_clamped_above_one(self):
        advice = build_opponent_advice(
            _mk_opp_state(shed_pressure=1.5),
            _mk_ctx(),
            {},
        )
        assert advice.opp_shed_pressure == 1.0

    def test_shed_pressure_clamped_below_zero(self):
        advice = build_opponent_advice(
            _mk_opp_state(shed_pressure=-0.5),
            _mk_ctx(),
            {},
        )
        assert advice.opp_shed_pressure == 0.0

    def test_to_dict_returns_structured_output(self):
        advice = build_opponent_advice(
            _mk_opp_state(
                shed_pressure=0.70,
                forecast={"MELON": {17: 60.0}},
            ),
            _mk_ctx(day=5, our_shed={"MELON": 3}),
            {"MELON": {17: 60.0}},
        )
        d = advice.to_dict()
        assert "supply_adjustment" in d
        assert "preempt_sell" in d
        assert "delay_sell" in d
        assert "counter_pick" in d
        assert "opp_shed_pressure" in d
        assert isinstance(d["preempt_sell"], list)
        assert isinstance(d["supply_adjustment"], dict)

    def test_full_scenario_opponent_melon_glut(self):
        """Opponent heavily in melons, we hold melons -> preempt."""
        forecast = {"MELON": {17: 60.0}}
        sell_probs = {"MELON": 0.85}
        our_shed = {"MELON": 8, "WHEAT": 10}
        advice = build_opponent_advice(
            _mk_opp_state(
                estimated_shed={"MELON": 20},
                sell_probs=sell_probs,
                shed_pressure=0.70,
                forecast=forecast,
            ),
            _mk_ctx(day=10, our_shed=our_shed),
            forecast,
        )
        # Supply adjustment penalises MELON
        assert advice.supply_adjustment.get("MELON", 0) > 0
        # Preempt sell flags MELON
        assert "MELON" in advice.preempt_sell
        # WHEAT not flagged (opp prob low)
        assert "WHEAT" not in advice.preempt_sell
        # Shed pressure passed through
        assert advice.opp_shed_pressure == 0.70

    def test_full_scenario_counter_pick_opportunity(self):
        """Town demands CARROT, opponent has none -> counter-pick."""
        boosts = {"CARROT": 0.8, "STRAWBERRY": 0.5}
        opp_state = _mk_opp_state(
            commitments={"crop_tiles": {"WHEAT": 10, "MELON": 8}},
            animal_counts={"GOOSE": 3},
        )
        advice = build_opponent_advice(
            opp_state, _mk_ctx(), {}, boosts=boosts,
        )
        assert "CARROT" in advice.counter_pick
        assert "STRAWBERRY" in advice.counter_pick
        # EGG not counter-picked (opponent has geese)
        assert "EGG" not in advice.counter_pick


# ===== CROP SCORE DEPRESSION UNDER OPPONENT GLUT =====

class TestCropScoreDepressesUnderOpponentGlut:
    """Verify _crop_score penalises crops where opponent is flooding supply."""

    def _make_forecast(self, prices=None):
        prices = prices or {"WHEAT": 25, "MELON": 250, "CARROT": 35}
        class FakeFC:
            def __init__(self, p):
                self.p = p
            def expected_price(self, product, day):
                return self.p.get(product, 25.0)
        return FakeFC(prices)

    def test_opponent_melon_glut_depresses_score(self):
        from strategy.macro_planner import _crop_score
        fc = self._make_forecast()
        no_opp, _ = _crop_score("MELON", 5, fc, {}, own_tiles=0)
        advice = OpponentAdvice(supply_adjustment={"MELON": 30.0})
        with_opp, _ = _crop_score("MELON", 5, fc, {}, own_tiles=0,
                                   opp_advice=advice)
        assert with_opp < no_opp, \
            f"melon score not depressed: {with_opp} vs {no_opp}"

    def test_no_opponent_supply_same_score(self):
        from strategy.macro_planner import _crop_score
        fc = self._make_forecast()
        no_opp, _ = _crop_score("WHEAT", 5, fc, {}, own_tiles=0)
        empty_advice = OpponentAdvice()
        with_empty, _ = _crop_score("WHEAT", 5, fc, {}, own_tiles=0,
                                     opp_advice=empty_advice)
        assert with_empty == pytest.approx(no_opp, abs=0.01)

    def test_unaffected_crop_unchanged(self):
        from strategy.macro_planner import _crop_score
        fc = self._make_forecast()
        advice = OpponentAdvice(supply_adjustment={"MELON": 50.0})
        s_no_opp, _ = _crop_score("WHEAT", 5, fc, {}, own_tiles=0)
        s_with_opp, _ = _crop_score("WHEAT", 5, fc, {}, own_tiles=0,
                                     opp_advice=advice)
        assert s_with_opp == pytest.approx(s_no_opp, abs=0.01)

    def test_larger_glut_depresses_more(self):
        from strategy.macro_planner import _crop_score
        fc = self._make_forecast()
        advice_small = OpponentAdvice(supply_adjustment={"MELON": 10.0})
        advice_large = OpponentAdvice(supply_adjustment={"MELON": 40.0})
        s_small, _ = _crop_score("MELON", 5, fc, {}, own_tiles=0,
                                  opp_advice=advice_small)
        s_large, _ = _crop_score("MELON", 5, fc, {}, own_tiles=0,
                                  opp_advice=advice_large)
        assert s_large < s_small, \
            f"larger glut did not depress more: {s_large} vs {s_small}"
