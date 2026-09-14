"""Unit tests for guarded livestock valuation (L0 vs L2a/L2b/L2c).

Tests:
1. derive_opponent_committed_livestock_stress_capacity produces 100% deterministic physical capacity.
2. Guard blocking when baseline gap is wider than guard_threshold.
3. Guard switching when baseline gap is within guard_threshold.
4. Stress evaluation equality with zero opponent animals.
5. Integration with generate_dynamic_herd_plan and decision record logging.
6. Mode configuration verification (L0, L1, L2, L2A, L2B, L2C).
"""

import pytest
from unittest.mock import MagicMock
from strategy.marginal_livestock_valuator import (
    derive_opponent_committed_livestock_stress_capacity,
    select_guarded_livestock_candidate,
    estimate_realized_marginal_animal_value,
)
from strategy.herd_planner import generate_dynamic_herd_plan
from config import (
    set_livestock_valuation_mode,
    get_livestock_valuation_mode,
    get_livestock_guard_threshold,
)


class MockTile:
    def __init__(self, pos, is_animal=False, animal=None, is_structure=False, kind=None, yield_units=0, placed_day=None):
        self.pos = pos
        self.is_animal = is_animal
        self.animal = animal
        self.is_structure = is_structure
        self.kind = kind or ("EMPTY" if not is_animal else animal)
        self.yield_units = yield_units
        self.placed_day = placed_day
        self.is_plant = False


class MockFarmView:
    def __init__(self, tiles=None):
        self._tiles = tiles or []

    def iter_tiles(self):
        return iter(self._tiles)


def test_stress_capacity_derivation():
    """Verify that visible opponent animals yield 100% deterministic physical capacity."""
    tiles = [
        MockTile((0, 0), is_animal=True, animal="COW", yield_units=2, placed_day=0),
        MockTile((0, 1), is_animal=True, animal="SHEEP", yield_units=0, placed_day=0),
        MockTile((1, 0), is_animal=True, animal="GOOSE", yield_units=1, placed_day=0),
    ]
    opp_farm = MockFarmView(tiles)
    stress_cap = derive_opponent_committed_livestock_stress_capacity(opp_farm, current_day=10)

    assert "MILK" in stress_cap
    assert "WOOL" in stress_cap
    assert "EGG" in stress_cap

    # Day 10 on-tile uncollected units: Cow has 2 held, Goose has 1 held
    assert stress_cap["MILK"].get(10, 0) == 2.0
    assert stress_cap["EGG"].get(10, 0) == 1.0

    # Cow placed on Day 0, first_yield_day=8, interval=2 -> Days 8, 10, 12, 14, 16, etc.
    assert stress_cap["MILK"].get(12, 0) == 3.0
    assert stress_cap["MILK"].get(14, 0) == 3.0

    # Sheep placed on Day 0, first_yield_day=6, interval=3 -> Days 6, 9, 12, 15, 18, etc.
    assert stress_cap["WOOL"].get(12, 0) == 4.0
    assert stress_cap["WOOL"].get(15, 0) == 4.0

    # Goose placed on Day 0, first_yield_day=4, interval=1 -> Days 4, 5, ..., 11, 12, 13, etc.
    assert stress_cap["EGG"].get(11, 0) == 2.0
    assert stress_cap["EGG"].get(12, 0) == 2.0


def test_stress_capacity_empty_farm():
    """Verify that an empty opponent farm yields zero stress capacity."""
    opp_farm = MockFarmView([])
    stress_cap = derive_opponent_committed_livestock_stress_capacity(opp_farm, current_day=5)
    for prod in ("MILK", "WOOL", "EGG"):
        assert prod in stress_cap
        assert sum(stress_cap[prod].values()) == 0.0


def test_guard_blocks_when_baseline_gap_exceeds_threshold():
    """When baseline Cow is comfortably better (>15%), stress on Milk cannot flip choice to Sheep."""
    base_evals = {
        "COW": {"net_realized_value": 10000.0, "marginal_product_revenue": 12000.0},
        "SHEEP": {"net_realized_value": 8000.0, "marginal_product_revenue": 9500.0},  # 20% lower
    }
    # Stress heavily depresses Cow net realized value
    stress_evals = {
        "COW": {"net_realized_value": 6000.0, "marginal_product_revenue": 8000.0},
        "SHEEP": {"net_realized_value": 8000.0, "marginal_product_revenue": 9500.0},
    }

    # With guard threshold 0.15 (15%), gap is 2000 / 10000 = 20.0% > 15% -> BLOCKED
    best_sp, chosen_eval, diag = select_guarded_livestock_candidate(
        base_evals, stress_evals, guard_threshold=0.15
    )

    assert best_sp == "COW"
    assert chosen_eval == base_evals["COW"]
    assert diag["switched"] is False
    assert diag["baseline_best"] == "COW"
    assert diag["stress_best"] == "SHEEP"
    assert diag["blocked_by_guard"] is True
    assert pytest.approx(diag["relative_gap"], 0.01) == 0.20


def test_guard_permits_switch_when_baseline_gap_within_threshold():
    """When baseline Cow and Sheep are close (<5%), opponent Cow stress safely breaks the tie."""
    base_evals = {
        "COW": {"net_realized_value": 10000.0, "marginal_product_revenue": 12000.0},
        "SHEEP": {"net_realized_value": 9800.0, "marginal_product_revenue": 11800.0},  # 2% lower
    }
    # Stress depresses Cow net realized value
    stress_evals = {
        "COW": {"net_realized_value": 7500.0, "marginal_product_revenue": 9500.0},
        "SHEEP": {"net_realized_value": 9800.0, "marginal_product_revenue": 11800.0},
    }

    # With guard threshold 0.05 (5%), gap is 200 / 10000 = 2.0% <= 5% -> PERMITTED SWITCH
    best_sp, chosen_eval, diag = select_guarded_livestock_candidate(
        base_evals, stress_evals, guard_threshold=0.05
    )

    assert best_sp == "SHEEP"
    assert chosen_eval == stress_evals["SHEEP"]
    assert diag["switched"] is True
    assert diag["baseline_best"] == "COW"
    assert diag["stress_best"] == "SHEEP"
    assert diag["blocked_by_guard"] is False
    assert pytest.approx(diag["relative_gap"], 0.01) == 0.02


def test_guard_agreement_no_switch():
    """When baseline and stress agree, no switch is triggered."""
    base_evals = {
        "COW": {"net_realized_value": 10000.0},
        "SHEEP": {"net_realized_value": 8000.0},
    }
    stress_evals = {
        "COW": {"net_realized_value": 9000.0},
        "SHEEP": {"net_realized_value": 8000.0},
    }
    best_sp, chosen_eval, diag = select_guarded_livestock_candidate(
        base_evals, stress_evals, guard_threshold=0.15
    )
    assert best_sp == "COW"
    assert diag["switched"] is False
    assert diag["blocked_by_guard"] is False


def test_config_mode_switching():
    """Verify that config correctly sets L0, L1, L2, L2A, L2B, L2C and respective thresholds."""
    set_livestock_valuation_mode("L0")
    assert get_livestock_valuation_mode() == "L0"

    set_livestock_valuation_mode("L1")
    assert get_livestock_valuation_mode() == "L1"

    set_livestock_valuation_mode("L2A")
    assert get_livestock_valuation_mode() == "L2A"
    assert get_livestock_guard_threshold() == 0.05

    set_livestock_valuation_mode("L2B")
    assert get_livestock_valuation_mode() == "L2B"
    assert get_livestock_guard_threshold() == 0.15

    set_livestock_valuation_mode("L2C")
    assert get_livestock_valuation_mode() == "L2C"
    assert get_livestock_guard_threshold() == 0.30

    # Reset to L0 baseline
    set_livestock_valuation_mode("L0")
    assert get_livestock_valuation_mode() == "L0"


def test_herd_planner_integration_with_guard():
    """Verify that herd planner records guard decisions in decision_records."""
    current_herd = {"COW": 1, "SHEEP": 0, "GOOSE": 0}
    market_inv = {"MILK": 10.0, "WOOL": 10.0, "WHEAT": 50.0, "FERTILIZER": 10.0}

    # High stress on Milk
    opp_stress = {
        "MILK": {d: 15.0 for d in range(4, 29, 2)},
        "WOOL": {},
        "EGG": {},
    }

    # Run with tight guard (5%)
    plan_l2a = generate_dynamic_herd_plan(
        day=4,
        hour=0,
        current_herd=current_herd,
        market_inventory=market_inv,
        max_sustainable=6,
        opponent_stress_supplies=opp_stress,
        guard_threshold=0.05,
    )

    assert hasattr(plan_l2a, "decision_records")
    assert len(plan_l2a.decision_records) > 0
    # Every decision record must have guard fields
    for rec in plan_l2a.decision_records:
        assert "species" in rec
        assert "accepted" in rec
        if rec.get("accepted"):
            gdiag = rec.get("guarded_diag", {})
            assert "baseline_best" in gdiag
            assert "switched" in gdiag
            assert "guard_threshold" in gdiag
            assert gdiag["guard_threshold"] == 0.05
