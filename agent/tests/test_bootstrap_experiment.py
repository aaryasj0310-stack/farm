"""Test Suite for Point-2 Early Livestock Bootstrap Experiment.

Verifies:
1. Target candidate sequences for all 5 arms (A, B, C, D, E).
2. Day-0 only restriction (no bootstrap on Day 1+).
3. Rejection of bootstrap candidates when cash is insufficient for purchase.
4. Correct 8-day horizon / candidate feed hold on Day 0 (4 operational + 4 financial).
5. Existing-herd continuity on Day 1 (no false remaining-season demand on bootstrap cohort).
6. Non-bootstrap animals under Point 2 still evaluate standard full-season horizon.
7. Production defaults remain POINT2_FEED_MODE = "shadow" and BOOTSTRAP_LIVESTOCK_ARM = "none".
8. Package isolation & zero syntax errors.
"""

import pytest
import config
from config import (
    POINT2_FEED_MODE,
    BOOTSTRAP_LIVESTOCK_ARM,
    BOOTSTRAP_SEQUENCES,
    get_bootstrap_target_sequence,
    FEED_OPERATIONAL_HORIZON_DAYS,
)
from strategy.feed_feasibility import (
    FeedResourceLedger,
    build_fresh_live_ledger,
    evaluate_existing_herd_feasibility,
    evaluate_incremental_candidate,
    commit_candidate_reservation,
)


def test_1_target_candidate_sequences():
    """Verify target sequences for all 5 experimental arms."""
    assert get_bootstrap_target_sequence("ArmA") == []
    assert get_bootstrap_target_sequence("ArmB") == ["COW", "COW"]
    assert get_bootstrap_target_sequence("ArmC") == ["COW", "COW", "SHEEP"]
    assert get_bootstrap_target_sequence("ArmD") == ["COW", "COW", "SHEEP", "SHEEP"]
    assert get_bootstrap_target_sequence("ArmE") == ["COW", "COW", "COW"]
    assert get_bootstrap_target_sequence("none") == []


def test_2_day0_only_restriction():
    """Verify bootstrap exception is restricted strictly to Day 0."""
    ledger_d0 = FeedResourceLedger(
        day=0, hour=0, operational_horizon_days=4, observed_cash=2000.0,
        wheat_in_shed=20,
    )
    res_d0 = evaluate_incremental_candidate(ledger_d0, "COW", purchase_cost=400.0, is_day0_bootstrap=True)
    assert res_d0.feasible is True
    assert res_d0.diagnostics.get("is_day0_bootstrap") is True
    assert res_d0.remaining_lifetime_feed_units == 4

    ledger_d1 = FeedResourceLedger(
        day=1, hour=0, operational_horizon_days=4, observed_cash=2000.0,
        wheat_in_shed=20,
    )
    res_d1 = evaluate_incremental_candidate(ledger_d1, "COW", purchase_cost=400.0, is_day0_bootstrap=True)
    assert res_d1.diagnostics.get("is_day0_bootstrap") is False
    assert res_d1.remaining_lifetime_feed_units == 24


def test_3_rejection_insufficient_cash():
    """Verify bootstrap candidate is rejected when treasury cannot afford purchase price."""
    ledger = FeedResourceLedger(
        day=0, hour=0, operational_horizon_days=4, observed_cash=300.0,
        wheat_in_shed=20,
    )
    res = evaluate_incremental_candidate(ledger, "COW", purchase_cost=400.0, is_day0_bootstrap=True)
    assert res.feasible is False
    assert res.blocking_reason == "insufficient_cash"


def test_4_correct_8day_horizon_on_day0():
    """Verify candidate feed hold on Day 0 covers 4 operational + 4 additional financial days."""
    ledger = FeedResourceLedger(
        day=0, hour=0, operational_horizon_days=4, observed_cash=2500.0,
        wheat_in_shed=20,
    )
    res = evaluate_incremental_candidate(ledger, "COW", purchase_cost=400.0, is_day0_bootstrap=True)
    assert res.feasible is True
    assert res.diagnostics.get("is_day0_bootstrap") is True
    assert res.near_term_feed_units == 3 # Days 1, 2, 3 (within 4-day horizon)
    assert res.remaining_lifetime_feed_units == 4 # 4 days beyond operational horizon


def test_5_existing_herd_continuity_day1():
    """Verify Day-1 ledger handles bootstrap cohort without demanding 24-day escrow upfront."""
    ledger = FeedResourceLedger(
        day=1, hour=0, operational_horizon_days=4, observed_cash=1000.0,
        wheat_in_shed=8,
        placed_herd={"COW": 2},
        bootstrap_cohort_liabilities=2,
    )
    ok, res = evaluate_existing_herd_feasibility(ledger)
    assert ok is True
    assert res.existing_feed_cash_hold < 600.0


def test_6_non_bootstrap_animals_full_season_horizon():
    """Verify non-bootstrap candidates evaluate standard full-season horizon."""
    ledger = FeedResourceLedger(
        day=0, hour=0, operational_horizon_days=4, observed_cash=2500.0,
        wheat_in_shed=20,
    )
    res = evaluate_incremental_candidate(ledger, "COW", purchase_cost=400.0, is_day0_bootstrap=False)
    assert res.diagnostics.get("is_day0_bootstrap") is False
    assert res.remaining_lifetime_feed_units == 25 # (29 - 0) - 4 = 25 days beyond


def test_7_production_defaults_intact():
    """Verify production defaults remain shadow and none."""
    assert POINT2_FEED_MODE == "shadow"
    assert BOOTSTRAP_LIVESTOCK_ARM == "none"


def test_8_syntax_and_imports():
    """Verify all modules import without syntax or structural errors."""
    import main
    import strategy.macro_planner
    import strategy.herd_planner
    import market.order_builder
    import state.state_tracker
    assert True
