"""Tests for v5.10 expansion planner logic.

Covers:
  - Static crop deadlines (strawberry Day 13, melon Day 17)
  - Land urgency computation
  - Treasury-safe purchase gate
  - Seed pre-purchase from surplus only
  - Expansion crop priorities
"""
import sys
import os
import pytest

# Bootstrap paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategy"))

from strategy.expansion_planner import (
    days_to_crop_deadline,
    compute_land_urgency,
    should_buy_land,
    compute_pre_buy_seeds,
    expansion_crop_priorities,
    expansion_seed_targets,
)
from config import (
    STRAWBERRY_PLANT_DEADLINE,
    MELON_PLANT_DEADLINE,
    CROPS,
    QUADRANT_UNLOCK_DAYS,
    QUADRANT_HARD_BLOCK,
)


# ---------------------------------------------------------------------------
# Mock farm for unit tests
# ---------------------------------------------------------------------------
class MockFarm:
    """Minimal farm mock for expansion planner tests."""
    def __init__(self, unlocked=None):
        self.unlocked = unlocked or ["NW"]
        self._tiles = []

    def iter_tiles(self):
        return iter(self._tiles)


# ---------------------------------------------------------------------------
# Deadline tests
# ---------------------------------------------------------------------------
class TestCropDeadlines:
    def test_strawberry_deadline_is_13(self):
        assert STRAWBERRY_PLANT_DEADLINE == 13

    def test_melon_deadline_is_17(self):
        assert MELON_PLANT_DEADLINE == 17

    def test_strawberry_days_to_deadline_day0(self):
        assert days_to_crop_deadline("STRAWBERRY", 0) == 13

    def test_strawberry_days_to_deadline_day10(self):
        assert days_to_crop_deadline("STRAWBERRY", 10) == 3

    def test_strawberry_days_to_deadline_day13(self):
        assert days_to_crop_deadline("STRAWBERRY", 13) == 0

    def test_strawberry_days_to_deadline_day14(self):
        assert days_to_crop_deadline("STRAWBERRY", 14) == -1

    def test_melon_days_to_deadline_day0(self):
        assert days_to_crop_deadline("MELON", 0) == 17

    def test_melon_days_to_deadline_day17(self):
        assert days_to_crop_deadline("MELON", 17) == 0

    def test_wheat_deadline(self):
        # Wheat: one-time, max_yield_day=4
        # last_harvest = 4, deadline = 29-1-4 = 24
        # days_to_deadline at day 0 = 24 - 0 = 24
        dt = days_to_crop_deadline("WHEAT", 0)
        assert dt >= 24  # at least 24 days to wheat deadline

    def test_carrot_deadline(self):
        # Carrot: one-time, max_yield_day=3
        # last_harvest = 3, deadline = 29-1-3 = 25
        # days_to_deadline at day 0 = 25 - 0 = 25
        dt = days_to_crop_deadline("CARROT", 0)
        assert dt >= 25  # at least 25 days to carrot deadline


# ---------------------------------------------------------------------------
# Land urgency tests
# ---------------------------------------------------------------------------
class TestLandUrgency:
    def test_no_schedule_returns_zero(self):
        farm = MockFarm(["NW", "NE", "SW"])
        urgency, reason, info = compute_land_urgency(4, 10, 5000, farm)
        assert urgency == 0.0
        assert "no_unlock_schedule" in reason

    def test_before_unlock_day(self):
        farm = MockFarm(["NW", "NE"])
        urgency, reason, info = compute_land_urgency(3, 5, 5000, farm)
        assert urgency == 0.1
        assert "before_unlock_day" in reason

    def test_critical_near_deadline(self):
        farm = MockFarm(["NW", "NE"])
        urgency, reason, info = compute_land_urgency(3, 11, 5000, farm)
        assert urgency == 1.0
        assert "critical" in reason

    def test_high_urgency(self):
        farm = MockFarm(["NW", "NE"])
        urgency, reason, info = compute_land_urgency(3, 9, 5000, farm)
        assert urgency == 0.8
        assert "high_urgency" in reason

    def test_treasury_ready(self):
        farm = MockFarm(["NW", "NE"])
        # Day 9 is unlock day, days_to_deadline = 13-9 = 4 → high_urgency
        # Day 9 with days_left=4 still triggers high_urgency, not treasury_ready
        # treasury_ready fires when days_to_deadline > 4 AND money >= requirement
        # That's only possible for NE (Q2, deadline=17, unlock=6)
        urgency, reason, info = compute_land_urgency(2, 6, 10000, farm)
        assert urgency == 0.6
        assert "treasury_ready" in reason

    def test_sw_high_urgency_on_unlock_day(self):
        farm = MockFarm(["NW", "NE"])
        # SW unlock day 9: days_to_deadline = 13-9 = 4 → high_urgency
        urgency, reason, info = compute_land_urgency(3, 9, 10000, farm)
        assert urgency == 0.8
        assert "high_urgency" in reason

    def test_after_deadline(self):
        farm = MockFarm(["NW", "NE"])
        urgency, reason, info = compute_land_urgency(3, 15, 5000, farm)
        assert urgency == 0.0
        assert "deadline_passed" in reason

    def test_info_contains_deadline(self):
        farm = MockFarm(["NW", "NE"])
        _, _, info = compute_land_urgency(3, 8, 5000, farm)
        assert "deadline" in info
        assert info["deadline"] == STRAWBERRY_PLANT_DEADLINE


# ---------------------------------------------------------------------------
# Purchase gate tests (non-negotiable treasury safety)
# ---------------------------------------------------------------------------
class TestShouldBuyLand:
    def test_before_unlock_day(self):
        farm = MockFarm(["NW", "NE"])
        buy, reason, info = should_buy_land(3, 5, 5000, farm,
                                            hire_cost=54, feed_cost=200)
        assert buy is False
        assert "before_day" in reason

    def test_hard_blocked(self):
        farm = MockFarm(["NW", "NE", "SW"])
        buy, reason, info = should_buy_land(4, 10, 5000, farm)
        assert buy is False
        # Q4 is not in UNLOCK_DAYS, so returns "no_schedule" before "hard_blocked"
        assert reason in ("hard_blocked", "no_schedule")

    def test_sufficient_treasury(self):
        farm = MockFarm(["NW", "NE"])
        # SW costs $2000 + seeds (~$1200) + hire + feed + reserve
        buy, reason, info = should_buy_land(3, 9, 8000, farm,
                                            hire_cost=143, feed_cost=500,
                                            roi=2.0, ow_factor=1.0)
        assert buy is True
        assert "treasury_sufficient" in reason

    def test_insufficient_treasury(self):
        farm = MockFarm(["NW", "NE"])
        # Only $2500 — not enough for land + seeds + commitments
        buy, reason, info = should_buy_land(3, 9, 2500, farm,
                                            hire_cost=143, feed_cost=500,
                                            roi=2.0, ow_factor=1.0)
        assert buy is False
        assert "short" in reason

    def test_adjusted_roi_zero_blocks_purchase(self):
        """adjusted_roi <= 0 → DO NOT BUY."""
        farm = MockFarm(["NW", "NE"])
        buy, reason, info = should_buy_land(3, 9, 8000, farm,
                                            hire_cost=143, feed_cost=500,
                                            roi=0.0, ow_factor=1.0)
        assert buy is False
        assert "non_positive" in reason

    def test_adjusted_roi_negative_blocks_purchase(self):
        """Negative adjusted_roi → DO NOT BUY."""
        farm = MockFarm(["NW", "NE"])
        buy, reason, info = should_buy_land(3, 9, 8000, farm,
                                            hire_cost=143, feed_cost=500,
                                            roi=1.0, ow_factor=-0.5)
        assert buy is False
        assert "non_positive" in reason

    def test_no_schedule(self):
        farm = MockFarm(["NW", "NE", "SW"])
        buy, reason, info = should_buy_land(4, 10, 5000, farm)
        assert buy is False


# ---------------------------------------------------------------------------
# Seed pre-purchase tests
# ---------------------------------------------------------------------------
class TestPreBuySeeds:
    def test_only_on_lead_day(self):
        """Pre-buy only happens on unlock_day - PRE_BUY_LEAD_DAYS."""
        farm = MockFarm(["NW", "NE"])
        # Day 8 is lead day for SW (unlock day 9)
        seeds = compute_pre_buy_seeds(3, 8, 5000)
        assert "STRAWBERRY" in seeds

    def test_not_on_wrong_day(self):
        seeds = compute_pre_buy_seeds(3, 7, 5000)
        assert seeds == {}

    def test_not_after_unlock(self):
        seeds = compute_pre_buy_seeds(3, 9, 5000)
        assert seeds == {}

    def test_funded_from_surplus(self):
        """Pre-buy should respect surplus budget."""
        seeds = compute_pre_buy_seeds(3, 8, 0)
        assert seeds == {}  # no surplus, no pre-buy

    def test_partial_funding(self):
        """With limited surplus, buy what we can."""
        seeds = compute_pre_buy_seeds(3, 8, 200)  # only $200 surplus
        # Strawberry seed costs $100, tomato $50
        assert seeds.get("STRAWBERRY", 0) + seeds.get("TOMATO", 0) > 0
        total_cost = sum(CROPS[c]["seed"] * n for c, n in seeds.items())
        assert total_cost <= 200

    def test_ne_pre_buy(self):
        """NE pre-buy should include carrot and tomato."""
        seeds = compute_pre_buy_seeds(2, 5, 5000)  # NE unlock day 6, lead day 5
        assert "CARROT" in seeds or "TOMATO" in seeds


# ---------------------------------------------------------------------------
# Expansion crop priority tests
# ---------------------------------------------------------------------------
class TestExpansionCropPriorities:
    def test_no_priority_after_deadline(self):
        farm = MockFarm(["NW", "NE"])
        priorities = expansion_crop_priorities(3, 15)
        assert priorities == {}

    def test_critical_priority_near_deadline(self):
        farm = MockFarm(["NW", "NE"])
        priorities = expansion_crop_priorities(3, 12)
        assert "STRAWBERRY" in priorities
        assert priorities["STRAWBERRY"] >= 50.0

    def test_moderate_priority_early(self):
        farm = MockFarm(["NW", "NE"])
        priorities = expansion_crop_priorities(3, 5)
        assert "STRAWBERRY" in priorities
        assert priorities["STRAWBERRY"] <= 20.0

    def test_sw_targets_strawberry(self):
        targets = expansion_seed_targets(3)
        assert "STRAWBERRY" in targets

    def test_ne_targets_carrot(self):
        targets = expansion_seed_targets(2)
        assert "CARROT" in targets

    def test_unknown_quadrant_empty(self):
        targets = expansion_seed_targets(5)
        assert targets == {}


# ---------------------------------------------------------------------------
# v5.11: Tests for dynamic ROI, opportunity window, dynamic caps/targets
# ---------------------------------------------------------------------------

class TestComputeLandROI:
    """Tests for compute_land_roi() — dynamic land valuation."""

    def test_zero_days_left_returns_zero(self):
        """No production time = no value from land."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        farm.unlocked = ["NW", "NE"]
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        roi, info = compute_land_roi(3, 29, 5000, farm, forecast)
        assert roi == 0.0
        assert info.get("reason") == "season_over"

    def test_before_unlock_day(self):
        """Can't buy land before unlock day."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW"])
        forecast = MagicMock()
        roi, info = compute_land_roi(3, 5, 5000, farm, forecast)
        assert roi == 0.0
        assert "before_unlock" in info.get("reason", "")

    def test_all_unlocked(self):
        """All quadrants already purchased."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE", "SW", "SE"])
        forecast = MagicMock()
        roi, info = compute_land_roi(3, 10, 5000, farm, forecast)
        assert roi == 0.0
        assert info.get("reason") == "all_unlocked"

    def test_no_eligible_crops(self):
        """All crop deadlines passed."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        # Day 26: all crops deadline passed (planting cuts off after Day 25)
        roi, info = compute_land_roi(3, 26, 5000, farm, forecast)
        assert roi < 0.0
        assert info["expected_profit"] < 0

    def test_positive_roi_with_early_day(self):
        """Early day (after unlock) = plenty of production time = positive ROI."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        # Day 9 is unlock day for SW
        roi, info = compute_land_roi(3, 9, 5000, farm, forecast)
        assert roi > 0.0
        assert "best_mix" in info

    def test_info_dict_contains_land_price_and_mix(self):
        """Info dict has all required fields."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        roi, info = compute_land_roi(3, 10, 5000, farm, forecast)
        assert "land_price" in info
        assert "best_mix" in info
        assert "expected_profit" in info
        assert "roi" in info


class TestOpportunityWindowFactor:
    """Tests for opportunity_window_factor() — economic window viability."""

    def test_q3_before_deadline_full_value(self):
        """SW quadrant before strawberry deadline = 1.0."""
        from strategy.expansion_planner import opportunity_window_factor
        factor = opportunity_window_factor(3, 5)
        assert factor == 1.0

    def test_q3_at_day_12_full_value(self):
        """SW quadrant on Day 12 has full production window = 1.0 (no artificial cliff)."""
        from strategy.expansion_planner import opportunity_window_factor
        factor = opportunity_window_factor(3, 12)
        assert factor == 1.0

    def test_q2_before_day_25_full_value(self):
        """NE quadrant before Day 25 = 1.0."""
        from strategy.expansion_planner import opportunity_window_factor
        factor = opportunity_window_factor(2, 15)
        assert factor == 1.0

    def test_after_day_25_returns_zero(self):
        """After Day 25 planting cut-off = 0.0."""
        from strategy.expansion_planner import opportunity_window_factor
        assert opportunity_window_factor(3, 26) == 0.0
        assert opportunity_window_factor(2, 26) == 0.0


class TestEstimateCropRevenuePerTile:
    """Tests for _estimate_crop_revenue_per_tile() — per-tile net profit."""

    def test_one_time_crop_single_harvest(self):
        """Wheat: single harvest, fixed yield."""
        from strategy.expansion_planner import _estimate_crop_revenue_per_tile
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.return_value = 50
        revenue, units = _estimate_crop_revenue_per_tile("WHEAT", 20, 20, forecast)
        # Wheat at day 20 yields 6 units on day 24, day 25-29 yields another 6 units
        assert units >= 6
        assert revenue > 0

    def test_ongoing_crop_multiple_harvests(self):
        """Tomato: multiple harvests over season."""
        from strategy.expansion_planner import _estimate_crop_revenue_per_tile
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.return_value = 50
        revenue, units = _estimate_crop_revenue_per_tile("TOMATO", 0, 0, forecast)
        assert units >= 4  # tomato yields multiple harvests
        assert revenue > 0

    def test_uses_price_forecast_directly_without_arbitrary_discount(self):
        """Revenue calculation directly consumes PriceForecast without arbitrary discounts."""
        from strategy.expansion_planner import _estimate_crop_revenue_per_tile
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        # Wheat on day 25: 1 cycle (day 25-29), harvest day 29, yield 6. Price 100 -> gross 600, seed 10 -> net 590
        net, units = _estimate_crop_revenue_per_tile("WHEAT", 25, 25, forecast)
        assert units == 6
        assert net == (6 * 100 - 10)  # Gross 600 - Seed 10 = 590

    def test_zero_future_harvests(self):
        """No future harvests = zero revenue."""
        from strategy.expansion_planner import _estimate_crop_revenue_per_tile
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        # Plant wheat on day 29 — no harvest possible
        revenue, units = _estimate_crop_revenue_per_tile("WHEAT", 29, 29, forecast)
        assert revenue == 0.0
        assert units == 0


class TestMarginalLandROI:
    """Comprehensive tests for marginal profit land ROI calculation."""

    def test_marginal_profit_calculation(self):
        """Incremental profit = profit_with_land - profit_without_land."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        forecast = MagicMock()
        forecast.expected_price.return_value = 60
        roi, info = compute_land_roi(3, 9, 5000, farm, forecast)
        assert "profit_with_land" in info
        assert "profit_without_land" in info
        assert "marginal_revenue_gain" in info
        assert info["marginal_revenue_gain"] == info["profit_with_land"] - info["profit_without_land"]
        assert info["expected_profit"] == info["marginal_revenue_gain"] - info["land_price"]

    def test_seed_and_input_costs_deducted_accurately(self):
        """Seed and fertilizer costs are deducted per cycle."""
        from strategy.expansion_planner import _estimate_crop_revenue_per_tile
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        # Strawberry planted on day 10: 4 harvests (days 20, 22, 24, 26) x 2 units = 8 units.
        # Gross = 8 x 100 = 800. Seed = 100, Fert = 2 x 25 = 50. Net = 800 - 100 - 50 = 650
        net, units = _estimate_crop_revenue_per_tile("STRAWBERRY", 10, 10, forecast)
        assert units == 8
        assert net == (8 * 100 - 100 - 50)

    def test_crop_caps_strictly_enforced_in_allocations(self):
        """Tile caps are strictly respected in both with and without allocations."""
        from strategy.expansion_planner import _allocate_portfolio_profit
        from unittest.mock import MagicMock
        from config import CROP_TILE_CAPS
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        total_profit, mix = _allocate_portfolio_profit(75, 5, forecast, is_sw_available=True)
        for crop, count in mix.items():
            if crop == "STRAWBERRY":
                assert count <= 10  # day 5 cap
            else:
                assert count <= CROP_TILE_CAPS.get(crop, 99)

    def test_dynamic_strawberry_cap_day13_vs_day14(self):
        """Day 13 includes strawberry up to 18; Day 14 includes 0 strawberry."""
        from strategy.expansion_planner import _allocate_portfolio_profit
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.side_effect = lambda crop, day: 150 if crop == "STRAWBERRY" else (60 if crop == "TOMATO" else 25)
        # Day 13
        _, mix_d13 = _allocate_portfolio_profit(50, 13, forecast, is_sw_available=True)
        assert mix_d13.get("STRAWBERRY", 0) <= 20
        assert mix_d13.get("STRAWBERRY", 0) > 0

        # Day 14
        _, mix_d14 = _allocate_portfolio_profit(50, 14, forecast, is_sw_available=True)
        assert mix_d14.get("STRAWBERRY", 0) == 0

    def test_profitable_marginal_expansion_produces_positive_roi(self):
        """Genuinely profitable expansion produces positive ROI."""
        from strategy.expansion_planner import compute_land_roi
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        forecast = MagicMock()
        forecast.expected_price.return_value = 150  # High crop prices
        roi, info = compute_land_roi(3, 9, 5000, farm, forecast)
        assert roi > 0.0
        assert info["expected_profit"] > 0

    def test_unprofitable_marginal_expansion_is_rejected(self):
        """When incremental profit is negative or zero, expansion is rejected."""
        from strategy.expansion_planner import compute_land_roi, should_buy_land
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        forecast = MagicMock()
        forecast.expected_price.return_value = 1  # Rock bottom floor prices
        roi, info = compute_land_roi(3, 9, 5000, farm, forecast)
        assert roi < 0.0
        should_buy, reason, _ = should_buy_land(3, 9, 10000, farm, roi=roi, ow_factor=1.0)
        assert should_buy is False
        assert "non_positive" in reason


class TestCandidateCropMix:
    """Tests for _candidate_crop_mix_for_quadrant() — mix generation."""

    def test_empty_when_no_eligible_crops(self):
        """No eligible crops = empty list."""
        from strategy.expansion_planner import _candidate_crop_mix_for_quadrant
        from unittest.mock import MagicMock
        farm = MockFarm(["NW", "NE"])
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        # Day 26: most crops expired
        candidates = _candidate_crop_mix_for_quadrant(3, 26, forecast, 25, 0, 0)
        assert len(candidates) == 0

    def test_all_in_strategy_selected(self):
        """Candidate mix respects crop caps."""
        from strategy.expansion_planner import _candidate_crop_mix_for_quadrant
        from unittest.mock import MagicMock
        from config import CROP_TILE_CAPS
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        candidates = _candidate_crop_mix_for_quadrant(3, 5, forecast, 25, 0, 0)
        assert len(candidates) > 0
        first_mix = candidates[0][0]
        total_tiles = sum(first_mix.values())
        assert total_tiles > 0
        for crop, count in first_mix.items():
            assert count <= CROP_TILE_CAPS.get(crop, 99)

    def test_crop_cap_enforced_in_mix(self):
        """Mix respects CROP_TILE_CAPS."""
        from strategy.expansion_planner import _candidate_crop_mix_for_quadrant
        from unittest.mock import MagicMock
        from config import CROP_TILE_CAPS
        forecast = MagicMock()
        forecast.expected_price.return_value = 100
        candidates = _candidate_crop_mix_for_quadrant(3, 5, forecast, 25, 0, 0)
        for mix, _, _ in candidates:
            for crop, count in mix.items():
                assert count <= CROP_TILE_CAPS.get(crop, 99)

    def test_strawberry_heavy_for_q3(self):
        """Q3 generates strawberry-heavy variant."""
        from strategy.expansion_planner import _candidate_crop_mix_for_quadrant
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.side_effect = lambda crop, day: 150 if crop == "STRAWBERRY" else (60 if crop == "TOMATO" else 25)
        candidates = _candidate_crop_mix_for_quadrant(3, 10, forecast, 25, 0, 0)
        has_strawberry = any("STRAWBERRY" in mix for mix, _, _ in candidates)
        assert has_strawberry


class TestDynamicStrawberryCap:
    """Tests for get_strawberry_cap() — time-varying cap."""

    def test_early_day_cap_16(self):
        """Day 0-8: cap = 16."""
        from config import get_strawberry_cap
        assert get_strawberry_cap(0, True) == 16
        assert get_strawberry_cap(8, True) == 16

    def test_mid_day_cap_18(self):
        """Day 9-12: cap = 18."""
        from config import get_strawberry_cap
        assert get_strawberry_cap(9, True) == 18
        assert get_strawberry_cap(12, True) == 18

    def test_late_day_cap_20_only_day_13(self):
        """Day 13: cap = 20 (only Day 13)."""
        from config import get_strawberry_cap
        assert get_strawberry_cap(13, True) == 20

    def test_very_late_cap_0(self):
        """Day 14+: cap = 0 (deadline passed)."""
        from config import get_strawberry_cap
        assert get_strawberry_cap(14, True) == 0
        assert get_strawberry_cap(29, True) == 0

    def test_no_land_returns_0(self):
        """No land purchased = cap = 0."""
        from config import get_strawberry_cap
        assert get_strawberry_cap(5, False) == 0


class TestSwSeedTargets:
    """Tests for get_sw_seed_targets() — dynamic seed targets."""

    def test_early_day_full_mix(self):
        """Day 0-8: 8 strawberry + 4 tomato."""
        from config import get_sw_seed_targets
        targets = get_sw_seed_targets(5, 5000)
        assert targets == {"STRAWBERRY": 8, "TOMATO": 4}

    def test_mid_day_strawberry_heavy(self):
        """Day 9-12: 10 strawberry + 2 tomato."""
        from config import get_sw_seed_targets
        targets = get_sw_seed_targets(10, 5000)
        assert targets == {"STRAWBERRY": 10, "TOMATO": 2}

    def test_late_day_strawberry_only(self):
        """Day 13: 12 strawberry + 0 tomato."""
        from config import get_sw_seed_targets
        targets = get_sw_seed_targets(13, 5000)
        assert targets == {"STRAWBERRY": 12, "TOMATO": 0}

    def test_very_late_no_strawberry(self):
        """Day 14+: 0 strawberry + 6 tomato (no strawberry after deadline)."""
        from config import get_sw_seed_targets
        targets = get_sw_seed_targets(14, 5000)
        assert targets == {"STRAWBERRY": 0, "TOMATO": 6}

    def test_treasury_constraint(self):
        """Low treasury reduces targets proportionally."""
        from config import get_sw_seed_targets
        targets = get_sw_seed_targets(5, 1500)  # Only $1500 after land
        total_cost = targets.get("STRAWBERRY", 0) * 100 + targets.get("TOMATO", 0) * 50
        assert total_cost <= 1200  # 1500 - 300 reserve


class TestExpansionSeedTargetsDynamic:
    """Tests for expansion_seed_targets() with dynamic params."""

    def test_sw_with_dynamic_params(self):
        """SW quadrant with day/money uses dynamic targets."""
        from strategy.expansion_planner import expansion_seed_targets
        targets = expansion_seed_targets(3, day=5, money=5000)
        assert targets == {"STRAWBERRY": 8, "TOMATO": 4}

    def test_sw_without_dynamic_params(self):
        """SW quadrant without day/money uses static targets."""
        from strategy.expansion_planner import expansion_seed_targets
        from config import SW_SEED_TARGETS
        targets = expansion_seed_targets(3)
        assert targets == dict(SW_SEED_TARGETS)

    def test_ne_ignores_dynamic_params(self):
        """NE quadrant always uses static targets."""
        from strategy.expansion_planner import expansion_seed_targets
        from config import NE_SEED_TARGETS
        targets = expansion_seed_targets(2, day=5, money=5000)
        assert targets == dict(NE_SEED_TARGETS)


class TestEvaluateSWTiming:
    """Tests for evaluate_sw_timing() — Buy Today vs Wait 1 Day."""

    def test_sw_timing_day13_vs_day14_delay_penalty(self):
        """Day 13 vs Day 14 should show substantial delay penalty due to strawberry deadline."""
        from strategy.expansion_planner import evaluate_sw_timing
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.side_effect = lambda crop, day: 120 if crop == "STRAWBERRY" else (60 if crop == "TOMATO" else 25)

        today_val, wait_val, delay_val, details = evaluate_sw_timing(13, forecast, n_tiles=25)
        assert today_val > wait_val
        assert delay_val > 0
        assert details["strawberry_tiles_today"] > 0
        assert details["strawberry_tiles_tomorrow"] == 0

    def test_sw_timing_day8_positive_value(self):
        """Day 8 evaluation shows positive value for buying SW today."""
        from strategy.expansion_planner import evaluate_sw_timing
        from unittest.mock import MagicMock
        forecast = MagicMock()
        forecast.expected_price.side_effect = lambda crop, day: 120 if crop == "STRAWBERRY" else (60 if crop == "TOMATO" else 25)

        today_val, wait_val, delay_val, details = evaluate_sw_timing(8, forecast, n_tiles=25)
        assert today_val > 0
        assert "buy_today_value" in details
        assert "wait_1_day_value" in details
        assert "delay_value" in details


class TestSWDiagnostics:
    """Tests for SW decision diagnostics dictionary in MacroPlanner."""

    def test_sw_decision_diagnostics_structure(self):
        """Ensure all required SW diagnostic fields are present."""
        from strategy.macro_planner import MacroPlanner
        from strategy.price_forecast import PriceForecast
        from unittest.mock import MagicMock

        fc = MagicMock(spec=PriceForecast)
        fc.expected_price.return_value = 30.0

        from test_macro_planner import make_ctx
        ctx = make_ctx(day=10, money=5000.0, unlocked=("NW", "NE", "SW"))

        planner = MacroPlanner(fc)
        plan = planner.build(ctx)

        assert "sw_decision" in plan.diagnostics
        diag = plan.diagnostics["sw_decision"]

        required_keys = [
            "day", "money", "SW buy/wait", "ROI", "buy_today_value",
            "wait_1_day_value", "delay_value", "SW utilization",
            "SW empty tiles", "SW empty tile-days", "projected utilization",
            "strawberry tiles", "other crop tiles", "reason"
        ]
        for k in required_keys:
            assert k in diag, f"Missing key '{k}' in sw_decision diagnostics"
