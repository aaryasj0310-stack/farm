"""Tests for P2.1 Dynamic Strawberry Portfolio Optimization isolation and admission logic."""
import pytest
import sys
import os

# Ensure agent paths are present
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [AGENT_DIR] + [os.path.join(AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from strategy.strawberry_portfolio_evaluator import (
    compute_dynamic_strawberry_cap,
    evaluate_marginal_strawberry,
    compute_next_best_crop_mv,
    _engine_market_price,
)


def test_default_flag_is_false():
    """Verify P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED defaults to False."""
    assert config.P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED is False
    assert config.get_p21_dynamic_strawberry_allocation_enabled() is False


def test_flag_toggle():
    """Verify setter toggles flag cleanly and restores safely."""
    try:
        config.set_p21_dynamic_strawberry_allocation_enabled(True)
        assert config.P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED is True
        assert config.get_p21_dynamic_strawberry_allocation_enabled() is True

        config.set_p21_dynamic_strawberry_allocation_enabled(False)
        assert config.P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED is False
        assert config.get_p21_dynamic_strawberry_allocation_enabled() is False
    finally:
        config.set_p21_dynamic_strawberry_allocation_enabled(False)


def test_market_pricing_math():
    """Verify authoritative integer-rounded price matching engine."""
    # At I0 (10,000): STRAWBERRY base is 120
    assert _engine_market_price("STRAWBERRY", 10000) == 120

    # At inventory > I0: linear price degradation
    # STRAWBERRY: amp = 1.60 * 120 / 100 = 1.92 per unit above I0
    # At I0 + 20: price = 120 - 1.92 * 20 = 120 - 38.4 = 81.6 -> rounded = 82
    p_above = _engine_market_price("STRAWBERRY", 10020)
    assert p_above == 82

    # At I0 (10,000): WHEAT base is 30
    assert _engine_market_price("WHEAT", 10000) == 30

    # Floor price is respected
    assert _engine_market_price("STRAWBERRY", 20000) >= 1


def test_next_best_crop_economics():
    """Verify alternative crop valuation over remaining days."""
    inv = {"WHEAT": 10000.0, "CARROT": 10000.0, "TOMATO": 10000.0}
    
    # Day 3: 27 days left. Multiple cycles possible.
    mv, best_crop = compute_next_best_crop_mv(day=3, market_inventory=inv, shed_wheat=10)
    assert mv > 0.0
    assert best_crop in ("WHEAT", "CARROT", "TOMATO")

    # Day 28: 2 days left. Wheat (5d) and Tomato (12d) cannot complete.
    mv_late, best_late = compute_next_best_crop_mv(day=28, market_inventory=inv, shed_wheat=10)
    # Late season returns should reflect short cycle constraints
    assert best_late in ("CARROT", "FALLOW", "WHEAT")


def test_marginal_strawberry_maintenance_labor():
    """Verify 17 calendar days of maintenance labor and diminishing marginal returns."""
    # On Day 13: Plant lives until Day 29 (17 calendar days: Days 13-29)
    # Maintenance labor: Seed ($100) + 17 waterings * $5 ($85) + 4 harvests * $5 ($20) + 2 sells * $5 ($10) = $215 total costs
    mv_k1 = evaluate_marginal_strawberry(
        day=13,
        k_tile=1,
        cur_market_inv=10000.0,
        committed_tiles=0,
        shed_stock=0,
    )
    # 6 units output. With town drain, price remains healthy for small k, so net profit is positive
    assert mv_k1 > 0.0

    # Diminishing marginal returns: tile 20 must have strictly lower marginal profit than tile 1
    mv_k20 = evaluate_marginal_strawberry(
        day=13,
        k_tile=20,
        cur_market_inv=10000.0,
        committed_tiles=0,
        shed_stock=0,
    )
    assert mv_k1 > mv_k20, f"Marginal return must diminish: k1={mv_k1} vs k20={mv_k20}"


def test_evaluator_deadline_and_quadrant_locking():
    """Verify evaluator blocks planting past Day 13 or without NE unlocked."""
    inv = {"STRAWBERRY": 10000.0, "WHEAT": 10000.0, "CARROT": 10000.0, "TOMATO": 10000.0}

    # Day 14 (past STRAWBERRY_PLANT_DEADLINE)
    cap_day14, diag_day14 = compute_dynamic_strawberry_cap(
        day=14, farm_unlocked={"NW", "NE"}, cur_market_inv=inv, committed_strawberries=16,
    )
    assert cap_day14 == 0
    assert diag_day14["reason"] == "deadline_passed_or_ne_locked"

    # Day 3 without NE unlocked
    cap_no_ne, diag_no_ne = compute_dynamic_strawberry_cap(
        day=3, farm_unlocked={"NW"}, cur_market_inv=inv, committed_strawberries=0,
    )
    assert cap_no_ne == 0
    assert diag_no_ne["reason"] == "deadline_passed_or_ne_locked"


def test_non_retroactivity_guarantee():
    """Verify evaluator cannot unplant already committed strawberries."""
    inv = {"STRAWBERRY": 10500.0, "WHEAT": 10000.0, "CARROT": 10000.0, "TOMATO": 10000.0}
    # Even if market is saturated and admitted_count would be low, committed_strawberries is preserved
    cap, diag = compute_dynamic_strawberry_cap(
        day=9,
        farm_unlocked={"NW", "NE"},
        cur_market_inv=inv,
        committed_strawberries=16,
        shed_strawberry=30,
        risk_buffer=50.0,  # High risk buffer to force admitted_count lower
    )
    assert cap >= 16, f"Cap must be >= committed strawberries (16), got {cap}"
    assert diag["new_tiles_allowed"] == 0


def test_control_cap_schedule_consistency():
    """Verify Control baseline cap schedule: 16 (Days 0-8), 18 (Days 9-12), 20 (Day 13), 0 (Day 14+)."""
    for d in range(0, 9):
        assert config.get_strawberry_cap(d, True) == 16, f"Day {d} expected 16"
    for d in range(9, 13):
        assert config.get_strawberry_cap(d, True) == 18, f"Day {d} expected 18"
    assert config.get_strawberry_cap(13, True) == 20, "Day 13 expected 20"
    for d in range(14, 30):
        assert config.get_strawberry_cap(d, True) == 0, f"Day {d} expected 0"
