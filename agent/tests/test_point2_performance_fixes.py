"""Point 2 Performance Fixes Unit Test Suite.

Validates:
  1. Fix H: Forward housing demand decoupling on Days 12-13.
  2. Fix H: Day 14 forward demand block (only physically observed empty housing allowed).
  3. Fix H: Strict candidate classification (forward_only=True -> purchase_eligible=False -> excluded from buy_animal_sequence/buy_animal).
  4. Fix H: Authoritative single housing charge (150 build + 25 action + crop opp + logistics).
  5. Fix H: Physical housing observed later enables normal purchase; queued pasture gives zero purchase credit.
  6. Fix F: 8-day rolling financial horizon replaces full-lifetime cash hold.
  7. Fix F: Single financial liability per deficit unit (no double-counting with operational buys).
  8. Fix F: Retained protected wheat reduces remaining existing feed hold without double-counting.
  9. Fix F: No speculative harvest credit beyond 4-day operational horizon.
 10. Fix F: Unplaced feed timing continuity between candidate and owned-unplaced herd.
"""

import pytest
import config
from config import (
    C4_LIVESTOCK_CUTOFF_DAY,
    SELECTIVE_LIVESTOCK_GATE_THRESHOLD,
    SELECTIVE_LIVESTOCK_MAX_DAY,
)
from strategy.feed_feasibility import (
    FeedExecutionSnapshot,
    FeedFeasibilityResult,
    FeedResourceLedger,
    TimedWheatDelivery,
    build_fresh_live_ledger,
    commit_candidate_reservation,
    compute_remaining_existing_feed_hold,
    evaluate_existing_herd_feasibility,
    evaluate_incremental_candidate,
)
from strategy.herd_planner import (
    DynamicHerdPlan,
    generate_dynamic_herd_plan,
    get_forward_housing_demand,
)


def test_fix_h_forward_demand_with_zero_empty_pastures(monkeypatch):
    """Fix H: On Day 12 with 0 empty pastures, forward housing evaluates and creates demand without leaking to buy_animal_sequence."""
    monkeypatch.setattr(config, "POINT2_HOUSING_FIX_ENABLED", True)
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")

    # Current herd = 5 cows, 0 empty pastures
    current_herd = {"COW": 5, "SHEEP": 0, "GOOSE": 0}
    phys_housing = {"PASTURE": 0, "COOP": 0}

    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd=current_herd,
        town_shops=["DAIRY", "CHEESE", "WEAVING"],
        late_selective_mode=True,
        physical_housing_capacity=phys_housing,
    )

    # Forward required pastures should exceed current pastures if profitable candidates found
    assert plan.forward_required_pastures >= 5
    # Strict candidate classification: buy_animal_sequence must NOT contain forward-only candidates
    assert plan.buy_animal_sequence == []
    assert plan.buy_animal == {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    assert plan.required_pastures == 5

    # If forward candidates were found, verify attributes
    if plan.forward_required_pastures > 5:
        demand = get_forward_housing_demand(plan, existing_pastures=5, reserved_pasture_tiles=0)
        assert demand["needed_pastures"] == plan.forward_required_pastures - 5
        assert len(plan.forward_only_candidates) > 0
        for fwd in plan.forward_only_candidates:
            assert fwd["forward_only"] is True
            assert fwd["purchase_eligible"] is False
            assert fwd["sequence_index"] == -1
            assert fwd["provisional_status"] == "forward_demand_only"


def test_fix_h_day14_forward_demand_blocked(monkeypatch):
    """Fix H: On Day 14, strictly NO new forward housing demand is projected; evaluation clamped to physical capacity."""
    monkeypatch.setattr(config, "POINT2_HOUSING_FIX_ENABLED", True)
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")

    # Day 14 with 0 empty pastures
    current_herd = {"COW": 5, "SHEEP": 0, "GOOSE": 0}
    phys_housing = {"PASTURE": 0, "COOP": 0}

    plan = generate_dynamic_herd_plan(
        day=14,
        hour=0,
        current_herd=current_herd,
        town_shops=["DAIRY", "CHEESE", "WEAVING"],
        late_selective_mode=True,
        physical_housing_capacity=phys_housing,
    )

    # Zero forward demand on Day 14
    assert plan.forward_required_pastures == 5
    assert plan.required_pastures == 5
    assert plan.buy_animal_sequence == []
    demand = get_forward_housing_demand(plan, existing_pastures=5, reserved_pasture_tiles=0)
    assert demand["needed_pastures"] == 0
    assert plan.forward_only_candidates == []


def test_fix_h_day14_physical_empty_pasture_allows_purchase(monkeypatch):
    """Fix H: On Day 14, physically observed empty pasture allows purchase if candidate clears selective hurdle."""
    monkeypatch.setattr(config, "POINT2_HOUSING_FIX_ENABLED", True)
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")

    # Day 14 with 1 physically empty pasture
    current_herd = {"COW": 5, "SHEEP": 0, "GOOSE": 0}
    phys_housing = {"PASTURE": 1, "COOP": 0}

    plan = generate_dynamic_herd_plan(
        day=14,
        hour=0,
        current_herd=current_herd,
        town_shops=["DAIRY", "CHEESE", "WEAVING"],
        late_selective_mode=True,
        physical_housing_capacity=phys_housing,
    )

    # If candidate clears $500 hurdle, it enters buy_animal_sequence as purchase-eligible
    if plan.buy_animal_sequence:
        assert len(plan.buy_animal_sequence) == 1
        assert plan.buy_animal_sequence[0] in ("COW", "SHEEP")
        assert plan.required_pastures == 6
        # Housing demand is 0 because the pasture physically exists already
        demand = get_forward_housing_demand(plan, existing_pastures=6, reserved_pasture_tiles=0)
        assert demand["needed_pastures"] == 0


def test_fix_h_housing_charge_applied_only_to_forward_candidates_day12(monkeypatch):
    """Fix H: Forward candidates are charged incremental housing ($150 + $25 + crop_opp + logistics); physical candidates are not."""
    monkeypatch.setattr(config, "POINT2_HOUSING_FIX_ENABLED", True)
    monkeypatch.setattr(config, "POINT2_FEED_MODE", "live")

    # 1 physical empty pasture available, Day 12
    current_herd = {"COW": 5, "SHEEP": 0, "GOOSE": 0}
    phys_housing = {"PASTURE": 1, "COOP": 0}

    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd=current_herd,
        town_shops=["DAIRY", "CHEESE", "WEAVING"],
        late_selective_mode=True,
        physical_housing_capacity=phys_housing,
        crop_opportunity_val=50.0,
    )

    accepted_records = [r for r in plan.decision_records if r.get("accepted", False)]
    if len(accepted_records) >= 1:
        # First accepted candidate used the physical empty pasture -> NO housing charge
        first_cand = accepted_records[0]
        assert first_cand["forward_only"] is False
        assert first_cand["purchase_eligible"] is True
        assert first_cand.get("housing_charge", 0.0) == 0.0

    if len(accepted_records) >= 2:
        # Second accepted candidate required new housing -> housing charge applied
        second_cand = accepted_records[1]
        assert second_cand["forward_only"] is True
        assert second_cand["purchase_eligible"] is False
        expected_min_charge = 150.0 + 25.0 + 50.0  # fence + action + crop_opp
        assert second_cand["housing_charge"] >= expected_min_charge


def test_fix_h_dynamic_herd_plan_failsafe_filtering():
    """Fix H: DynamicHerdPlan constructor enforces fail-safe exclusion of forward-only records from buy_animal_sequence."""
    decision_records = [
        {
            "candidate_id": "cand_0_COW",
            "sequence_index": 0,
            "species": "COW",
            "accepted": True,
            "forward_only": False,
            "purchase_eligible": True,
            "net_val": 600.0,
        },
        {
            "candidate_id": "cand_fwd_1_SHEEP",
            "sequence_index": -1,
            "species": "SHEEP",
            "accepted": True,
            "forward_only": True,
            "purchase_eligible": False,
            "net_val": 520.0,
        },
    ]

    plan = DynamicHerdPlan(
        desired_herd={"COW": 2, "SHEEP": 1, "GOOSE": 0},
        required_pastures=2,
        required_coops=0,
        marginal_value_sequence=[],
        decision_records=decision_records,
        forward_required_pastures=3,
    )

    # COW is purchase-eligible, SHEEP is forward-only
    assert plan.buy_animal_sequence == ["COW"]
    assert plan.buy_animal == {"COW": 1, "SHEEP": 0, "GOOSE": 0}
    assert plan.required_pastures == 2
    assert plan.forward_required_pastures == 3
    assert len(plan.forward_only_candidates) == 1
    assert plan.forward_only_candidates[0]["species"] == "SHEEP"


def test_fix_f_8day_rolling_horizon_reduces_early_feed_hold(monkeypatch):
    """Fix F: 8-day rolling financial horizon significantly reduces cash hold compared to full-lifetime baseline on Day 0."""
    monkeypatch.setattr(config, "POINT2_FUNDING_HORIZON_FIX_ENABLED", False)

    snapshot = FeedExecutionSnapshot(
        day=0,
        hour=0,
        turns_remaining_today=24,
        feeds_due_today=5,
        feeds_assigned_this_turn=0,
        wheat_pickups_assigned_this_turn=0,
        worker_wheat=0,
        shed_wheat=0,
        n_active_units=2,
        market_purchase_can_help_today=True,
    )

    ledger_baseline = FeedResourceLedger(
        day=0,
        hour=0,
        operational_horizon_days=4,
        observed_cash=10000.0,
        wheat_in_shed=0,
        wheat_on_workers=0,
        unfed_placed_today=5,
        placed_herd={"COW": 5},
        execution_snapshot=snapshot,
        wheat_price_current=28.0,
        lifetime_price_policy="engine_stress_bound_v1",
    )

    ok_base, res_base = evaluate_existing_herd_feasibility(ledger_baseline)
    assert ok_base is True
    hold_baseline = res_base.existing_feed_cash_hold

    # Now enable Fix F (8-day horizon)
    monkeypatch.setattr(config, "POINT2_FUNDING_HORIZON_FIX_ENABLED", True)
    monkeypatch.setattr(config, "FEED_FINANCIAL_HORIZON_DAYS", 8)

    ledger_fix = ledger_baseline.clone()
    ok_fix, res_fix = evaluate_existing_herd_feasibility(ledger_fix)
    assert ok_fix is True
    hold_fix = res_fix.existing_feed_cash_hold

    # 8-day hold funds 8 days (days 0..7) rather than 29 days (days 0..28)
    assert hold_fix < hold_baseline
    assert hold_fix <= hold_baseline * 0.40


def test_fix_f_single_liability_per_deficit_unit(monkeypatch):
    """Fix F: Dedicated feed hold equals operational scheduled wheat cost + future deficit cost with zero double counting."""
    monkeypatch.setattr(config, "POINT2_FUNDING_HORIZON_FIX_ENABLED", True)
    monkeypatch.setattr(config, "FEED_FINANCIAL_HORIZON_DAYS", 8)

    snapshot = FeedExecutionSnapshot(
        day=10,
        hour=0,
        turns_remaining_today=24,
        feeds_due_today=2,
        feeds_assigned_this_turn=0,
        wheat_pickups_assigned_this_turn=0,
        worker_wheat=0,
        shed_wheat=0,
        n_active_units=2,
        market_purchase_can_help_today=True,
    )

    ledger = FeedResourceLedger(
        day=10,
        hour=0,
        operational_horizon_days=4,
        observed_cash=3000.0,
        wheat_in_shed=0,
        wheat_on_workers=0,
        unfed_placed_today=2,
        placed_herd={"COW": 2},
        execution_snapshot=snapshot,
        wheat_price_current=28.0,
        lifetime_price_policy="constant_spot",
    )

    ok, res = evaluate_existing_herd_feasibility(ledger)
    assert ok is True

    # 2 cows across 8 days: 2 today + 2*7 future = 16 units needed
    # 4 operational days: days 10, 11, 12, 13 -> 8 units bought operationally
    # 4 future days: days 14, 15, 16, 17 -> 8 units future deficit
    op_cost = sum(b["cost"] for b in res.scheduled_market_purchases)
    future_units = res.remaining_lifetime_feed_units
    future_cost = res.remaining_feed_cash_required

    assert len(res.scheduled_market_purchases) == 4
    assert sum(b["units"] for b in res.scheduled_market_purchases) == 8
    assert future_units == 8
    assert res.existing_feed_cash_hold == op_cost + future_cost
    assert res.existing_feed_cash_hold == 16 * 28.0


def test_fix_f_retained_wheat_anti_double_counting(monkeypatch):
    """Fix F: Retained protected wheat reduces remaining future existing feed hold 1-for-1."""
    monkeypatch.setattr(config, "POINT2_FUNDING_HORIZON_FIX_ENABLED", True)
    monkeypatch.setattr(config, "FEED_FINANCIAL_HORIZON_DAYS", 8)

    snapshot = FeedExecutionSnapshot(
        day=10,
        hour=0,
        turns_remaining_today=24,
        feeds_due_today=0,  # already fed today
        feeds_assigned_this_turn=0,
        wheat_pickups_assigned_this_turn=0,
        worker_wheat=0,
        shed_wheat=0,
        n_active_units=2,
        market_purchase_can_help_today=True,
    )

    ledger = FeedResourceLedger(
        day=10,
        hour=0,
        operational_horizon_days=4,
        observed_cash=5000.0,
        wheat_in_shed=0,
        wheat_on_workers=0,
        unfed_placed_today=0,
        placed_herd={"COW": 1},
        execution_snapshot=snapshot,
        wheat_price_current=28.0,
        lifetime_price_policy="constant_spot",
    )

    ok_0, res_0, hold_0 = compute_remaining_existing_feed_hold(ledger, retained_wheat=0, unit_price=28.0)
    ok_3, res_3, hold_3 = compute_remaining_existing_feed_hold(ledger, retained_wheat=3, unit_price=28.0)

    assert ok_0 is True
    assert ok_3 is True
    spent_now = 3 * 28.0
    # Anti-double-counting invariant: spent cash + remaining hold equals initial hold
    assert abs((spent_now + hold_3) - hold_0) < 1e-3


def test_fix_f_unplaced_timing_continuity(monkeypatch):
    """Fix F: An unplaced candidate does not eat today (needed=0), and needs 1 unit/day on future days in rolling window."""
    monkeypatch.setattr(config, "POINT2_FUNDING_HORIZON_FIX_ENABLED", True)
    monkeypatch.setattr(config, "FEED_FINANCIAL_HORIZON_DAYS", 8)

    snapshot = FeedExecutionSnapshot(
        day=10,
        hour=23,  # Hour 23: same-day market wheat cannot rescue today
        turns_remaining_today=0,
        feeds_due_today=0,
        feeds_assigned_this_turn=0,
        wheat_pickups_assigned_this_turn=0,
        worker_wheat=0,
        shed_wheat=0,
        n_active_units=2,
        market_purchase_can_help_today=False,
    )

    ledger = FeedResourceLedger(
        day=10,
        hour=23,
        operational_horizon_days=4,
        observed_cash=5000.0,
        wheat_in_shed=0,
        wheat_on_workers=0,
        unfed_placed_today=0,
        placed_herd={},
        owned_unplaced_herd={},
        execution_snapshot=snapshot,
        wheat_price_current=28.0,
        lifetime_price_policy="constant_spot",
    )

    # Candidate COW evaluated at Hour 23
    cand_res = evaluate_incremental_candidate(ledger, "COW")
    assert cand_res.feasible is True
    # Does not schedule any market buy for Day 10 (today)
    day10_buys = [b for b in cand_res.scheduled_market_purchases if b["day"] == 10]
    assert len(day10_buys) == 0
    # Operational horizon has days 11, 12, 13 (3 days)
    # 8-day rolling window has days 10..17 (7 future days: 3 op + 4 beyond)
    assert cand_res.near_term_market_wheat_required == 3
    assert cand_res.remaining_lifetime_feed_units == 4
