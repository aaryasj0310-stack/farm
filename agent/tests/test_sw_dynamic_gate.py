"""Regression tests for Dynamic Economic Gate on SW Land Purchases.

Verifies the 5 required test cases:
1. Day 12, profitable SW -> BUY.
2. Day 14, still clearly profitable and affordable -> BUY.
3. Day 14, negative/insufficient payback -> WAIT.
4. Late season where no realistic payback remains -> WAIT.
5. High ROI but insufficient treasury -> WAIT.
"""
import pytest

from strategy.expansion_planner import (
    should_buy_land,
    opportunity_window_factor,
    expansion_seed_targets,
)


class MockTile:
    def __init__(self, is_plant=False, is_animal=False):
        self.is_plant = is_plant
        self.is_animal = is_animal


class MockFarm:
    def __init__(self, unlocked, hands=None, active_tiles_count=5):
        self.unlocked = list(unlocked)
        self.hands = hands if hands is not None else [(0, 1), (0, 2)]
        self.seeds = {}
        self._tiles = [MockTile(is_plant=True) for _ in range(active_tiles_count)]

    def iter_tiles(self):
        return iter(self._tiles)


def test_day_12_profitable_sw_buys():
    """Case 1: Day 12, profitable SW and sufficient treasury -> BUY."""
    farm = MockFarm(["NW", "NE"], hands=[(0, 1), (0, 2)])
    # Land price is 2000, seed cost is ~150, reserve 300, mandatory ~200 -> total ~2650
    # Money = 5000 is plenty. ROI = 0.50 (marginal gain ~ 3000 > 2000 + 150)
    buy, reason, diag = should_buy_land(
        next_quadrant=3,
        current_day=12,
        money=5000.0,
        farm=farm,
        hire_cost=100.0,
        feed_cost=100.0,
        reserve=300.0,
        roi=0.50,
        ow_factor=1.0,
    )
    assert buy is True, f"Expected Day 12 to buy SW, got {reason}"
    assert reason == "treasury_sufficient_roi_positive"
    assert diag["payback_surplus"] > 0


def test_day_14_profitable_and_affordable_sw_buys():
    """Case 2: Day 14, still clearly profitable and affordable -> BUY.
    This was previously rejected by the hard Day-13 cutoff.
    """
    farm = MockFarm(["NW", "NE"], hands=[(0, 1), (0, 2), (0, 3)])
    buy, reason, diag = should_buy_land(
        next_quadrant=3,
        current_day=14,
        money=6000.0,
        farm=farm,
        hire_cost=150.0,
        feed_cost=100.0,
        reserve=300.0,
        roi=0.60,
        ow_factor=1.0,
    )
    assert buy is True, f"Expected Day 14 with ROI=0.60 to buy SW, got {reason}"
    assert reason == "treasury_sufficient_roi_positive"
    assert diag["payback_surplus"] > 0


def test_day_14_negative_or_insufficient_payback_waits():
    """Case 3: Day 14, negative/insufficient payback -> WAIT."""
    farm = MockFarm(["NW", "NE"], hands=[(0, 1), (0, 2)])
    # ROI = -0.20 -> marginal revenue gain = 1600 < land price 2000
    buy, reason, diag = should_buy_land(
        next_quadrant=3,
        current_day=14,
        money=6000.0,
        farm=farm,
        hire_cost=150.0,
        feed_cost=100.0,
        reserve=300.0,
        roi=-0.20,
        ow_factor=1.0,
    )
    assert buy is False, "Expected negative ROI to reject purchase"
    assert "non_positive" in reason or "insufficient_payback" in reason


def test_late_season_no_realistic_payback_waits():
    """Case 4: Late season where no realistic payback remains -> WAIT."""
    farm = MockFarm(["NW", "NE"], hands=[(0, 1), (0, 2)])
    # Day 26 or 27: opportunity window factor closes (0.0) because crops cannot mature
    ow_factor = opportunity_window_factor(3, 27)
    assert ow_factor == 0.0

    buy, reason, diag = should_buy_land(
        next_quadrant=3,
        current_day=27,
        money=10000.0,
        farm=farm,
        hire_cost=0.0,
        feed_cost=0.0,
        reserve=300.0,
        roi=1.0,
        ow_factor=ow_factor,
    )
    assert buy is False, "Expected late season (Day 27) to reject purchase"
    assert "non_positive" in reason


def test_high_roi_insufficient_treasury_waits():
    """Case 5: High ROI but insufficient treasury -> WAIT."""
    farm = MockFarm(["NW", "NE"], hands=[(0, 1), (0, 2)])
    # ROI = 2.0 (tremendous expected profit), but money is only $1,200 (less than $2,000 land alone)
    buy, reason, diag = should_buy_land(
        next_quadrant=3,
        current_day=12,
        money=1200.0,
        farm=farm,
        hire_cost=100.0,
        feed_cost=100.0,
        reserve=300.0,
        roi=2.0,
        ow_factor=1.0,
    )
    assert buy is False, "Expected treasury shortfall to block purchase despite high ROI"
    assert "short_" in reason
    assert diag["shortfall"] > 0
