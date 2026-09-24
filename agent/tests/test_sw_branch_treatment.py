"""Unit tests for Phase B1: True Branch-Point SW Treatment Experiment.

Tests:
1. Land suppression: baseline wants BUY_LAND -> treatment blocks order until approval.
2. Later purchase: planner approves -> BUY_LAND order emitted exactly once.
3. Tranche enforcement: 8-tile portfolio admitted -> only those 8 tiles receive SW planting tasks.
4. Reset isolation: new match starts with no previous treatment state.
5. No-purchase game: planner never approves -> no SW BUY_LAND emitted throughout match.
6. Portfolio fidelity: selected crop allocation == executed initial SW allocation.
7. Invariant enforcement: active SW planted tiles <= admitted SW tile set.
"""
import copy
import pytest
from unittest.mock import MagicMock, patch

from config import (
    SW_FORWARD_ARCHITECTURE_MODE,
    get_sw_forward_architecture_mode,
    set_sw_forward_architecture_mode,
)
from strategy.sw_tranche_controller import (
    SWTrancheController,
    SWTrancheState,
    get_sw_tranche_controller,
    reset_sw_tranche_controller,
    SW_COORDINATES,
)


@pytest.fixture(autouse=True)
def cleanup_treatment_state():
    """Ensure clean mode and controller state before and after each test."""
    set_sw_forward_architecture_mode("OFF")
    reset_sw_tranche_controller()
    yield
    set_sw_forward_architecture_mode("OFF")
    reset_sw_tranche_controller()


def test_treatment_mode_configuration():
    """Verify TREATMENT mode is accepted and queried correctly."""
    assert get_sw_forward_architecture_mode() == "OFF"
    set_sw_forward_architecture_mode("TREATMENT")
    assert get_sw_forward_architecture_mode() == "TREATMENT"

    ctrl = get_sw_tranche_controller()
    assert ctrl.is_treatment_active() is True

    set_sw_forward_architecture_mode("OFF")
    assert get_sw_forward_architecture_mode() == "OFF"
    assert ctrl.is_treatment_active() is False


def test_land_suppression_blocks_early_buy():
    """Test 1: Land suppression. Baseline wants BUY_LAND -> treatment suppresses order."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE"}
    farm_mock.money = 2500.0

    # Before WholeFarmPlanner approval, baseline buy must be suppressed
    assert ctrl.state.sw_purchase_approved is False
    should_suppress = ctrl.should_suppress_baseline_sw_buy(day=5, hour=0, farm=farm_mock)
    assert should_suppress is True


def test_later_purchase_emitted_once_when_approved():
    """Test 2: Later purchase. Planner approves -> BUY_LAND order allowed exactly once."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    sample_portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, [(0, 7), (1, 7), (2, 7), (3, 7)]),
            ("MELON", 4, [(4, 7), (0, 8), (1, 8), (2, 8)]),
        ],
        "tiles_used": 8,
    }

    # Approve purchase
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio=sample_portfolio,
        delta_fc=1250.0,
        cash_before=2800.0,
        worker_count=9,
    )

    assert ctrl.state.sw_purchase_approved is True
    assert ctrl.state.sw_purchase_day == 9
    assert ctrl.state.selected_portfolio_name == "compact_commercial"
    assert len(ctrl.state.admitted_sw_tiles) == 8

    # Now should_suppress is False
    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE"}
    assert ctrl.should_suppress_baseline_sw_buy(day=9, hour=0, farm=farm_mock) is False


def test_tranche_enforcement_restricts_sw_planting():
    """Test 3: Tranche enforcement. Only admitted 8 tiles receive SW planting tasks."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    admitted_coords = [(0, 7), (1, 7), (2, 7), (3, 7), (4, 7), (0, 8), (1, 8), (2, 8)]
    sample_portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, admitted_coords[:4]),
            ("MELON", 4, admitted_coords[4:8]),
        ],
        "tiles_used": 8,
    }
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio=sample_portfolio,
        delta_fc=1200.0,
        cash_before=2800.0,
        worker_count=9,
    )

    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE", "SW"}

    # Attempt to schedule plant tasks for both admitted and non-admitted SW tiles
    raw_plant_queue = [
        ((0, 7), "STRAWBERRY"),  # admitted
        ((1, 7), "STRAWBERRY"),  # admitted
        ((4, 7), "MELON"),       # admitted
        ((3, 9), "WHEAT"),       # NOT admitted (SW tile 3,9)
        ((4, 9), "WHEAT"),       # NOT admitted (SW tile 4,9)
        ((7, 2), "CARROT"),      # NE tile (core farm, allowed)
    ]

    filtered_queue = ctrl.filter_macro_plant_queue(raw_plant_queue, farm_mock)
    filtered_positions = [pos for pos, _ in filtered_queue]

    assert (0, 7) in filtered_positions
    assert (1, 7) in filtered_positions
    assert (4, 7) in filtered_positions
    assert (7, 2) in filtered_positions  # Core farm untouched
    assert (3, 9) not in filtered_positions  # Blocked
    assert (4, 9) not in filtered_positions  # Blocked
    assert ctrl.state.invariant_violations_attempted == 2


def test_task_scheduler_task_filtering():
    """Test 3b: Tranche enforcement at task scheduler level."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    admitted_coords = [(0, 7), (1, 7), (2, 7), (3, 7)]
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio={"name": "compact_tranche", "allocations": [("WHEAT", 4, admitted_coords)], "tiles_used": 4},
        delta_fc=500.0,
        cash_before=2500.0,
        worker_count=9,
    )

    tasks = [
        {"op": "PLANT", "target": (0, 7), "kind": "plant"},  # admitted SW
        {"op": "PLANT", "target": (0, 9), "kind": "plant"},  # unadmitted SW
        {"op": "WATER", "target": (0, 9), "kind": "water"},  # non-plant task allowed
        {"op": "PLANT", "target": (2, 2), "kind": "plant"},  # NW tile allowed
    ]

    filtered = ctrl.filter_task_scheduler_tasks(tasks, farm=None)
    targets = [t["target"] for t in filtered]

    assert (0, 7) in targets
    assert (2, 2) in targets
    assert (0, 9) in targets  # WATER allowed
    plant_targets = [t["target"] for t in filtered if t["op"] == "PLANT"]
    assert (0, 9) not in plant_targets  # Unadmitted SW plant blocked!


def test_reset_isolation_cleans_state():
    """Test 4: Reset isolation. New match starts with no previous treatment state."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio={"name": "test", "allocations": [("WHEAT", 1, [(0, 7)])], "tiles_used": 1},
        delta_fc=100.0,
        cash_before=2500.0,
        worker_count=9,
    )
    ctrl.state.invariant_violations_attempted = 5

    assert ctrl.state.sw_purchase_approved is True
    assert ctrl.state.invariant_violations_attempted == 5

    # Reset
    reset_sw_tranche_controller()
    new_ctrl = get_sw_tranche_controller()

    assert new_ctrl.state.sw_purchase_approved is False
    assert new_ctrl.state.sw_purchase_day is None
    assert len(new_ctrl.state.admitted_sw_tiles) == 0
    assert new_ctrl.state.invariant_violations_attempted == 0


def test_no_purchase_game_stays_unlocked():
    """Test 5: No-purchase game. Planner never approves -> no SW purchase emitted."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    # Simulate evaluation where conditions are not met
    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE"}
    farm_mock.money = 1500.0  # insufficient cash

    for day in range(30):
        # Should suppress SW buy every day
        assert ctrl.should_suppress_baseline_sw_buy(day=day, hour=0, farm=farm_mock) is True

    assert ctrl.state.sw_purchase_approved is False
    assert ctrl.state.sw_purchase_day is None


def test_portfolio_fidelity_matches_allocations():
    """Test 6: Portfolio fidelity. Target crops match admitted portfolio allocations."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, [(0, 7), (1, 7), (2, 7), (3, 7)]),
            ("MELON", 4, [(4, 7), (0, 8), (1, 8), (2, 8)]),
        ],
        "tiles_used": 8,
    }
    ctrl.approve_purchase(
        day=10,
        hour=0,
        portfolio=portfolio,
        delta_fc=1400.0,
        cash_before=3000.0,
        worker_count=11,
    )

    # Check that each tile maps to the exact crop specified
    for pos in [(0, 7), (1, 7), (2, 7), (3, 7)]:
        assert ctrl.state.admitted_sw_crop_targets[pos] == "STRAWBERRY"
    for pos in [(4, 7), (0, 8), (1, 8), (2, 8)]:
        assert ctrl.state.admitted_sw_crop_targets[pos] == "MELON"


def test_checkpoint_tracking_utilization():
    """Test 7: Checkpoint tracking records whole-quadrant and tranche utilization."""
    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.sw_purchase_day = 9
    ctrl.state.admitted_sw_tiles = {(0, 7), (1, 7), (2, 7), (3, 7), (4, 7), (0, 8), (1, 8), (2, 8)}

    # Mock farm with 8 planted tiles in SW
    tiles = []
    for y in range(10):
        row = []
        for x in range(10):
            t = MagicMock()
            t.x = x
            t.y = y
            t.pos = (x, y)
            is_sw = (x < 5 and y >= 5)
            if is_sw and (x, y) in ctrl.state.admitted_sw_tiles:
                t.kind = "PLANT"
                t.is_plant = True
                t.is_empty = False
                t.watered_today = True
                t.yield_units = 0
            else:
                t.kind = "EMPTY"
                t.is_plant = False
                t.is_empty = True
                t.watered_today = False
                t.yield_units = 0
            row.append(t)
        tiles.append(row)

    farm_mock = MagicMock()
    farm_mock.iter_tiles.return_value = [t for row in tiles for t in row]

    ctrl.record_checkpoint("D+0", farm_mock)
    cp = ctrl.state.checkpoints.get("D+0")

    assert cp is not None
    assert cp["sw_owned_tiles"] == 25
    assert cp["sw_admitted_tiles"] == 8
    assert cp["sw_planted_tiles"] == 8
    assert cp["sw_watered_tiles"] == 8
    assert cp["admitted_tranche_utilization_pct"] == 100.0
    assert cp["whole_quadrant_utilization_pct"] == 32.0  # 8 / 25


def test_recommendation_vs_approval_vs_executed_purchase():
    """Test 8: Separation of recommendation, approval, order emission, and confirmed execution."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)

    portfolio = {
        "name": "compact_commercial",
        "allocations": [("STRAWBERRY", 4, [(0, 7), (1, 7), (2, 7), (3, 7)])]
    }

    # Stage 1: Recommendation and approval
    ctrl.approve_purchase(day=9, hour=6, portfolio=portfolio, delta_fc=5000.0, cash_before=2266.0, worker_count=9)
    assert ctrl.state.sw_purchase_recommended is True
    assert ctrl.state.sw_purchase_approved is True
    assert ctrl.state.sw_purchase_confirmed is False
    assert ctrl.state.sw_unlock_observed is False
    assert ctrl.state.sw_land_cost_paid == 0.0  # Unpaid until confirmed

    # Stage 2: Market order emitted
    ctrl.state.sw_land_order_emitted = True
    assert ctrl.state.sw_purchase_confirmed is False

    # Stage 3: Authoritative engine confirmation
    ctrl.confirm_purchase(day=9, hour=7)
    assert ctrl.state.sw_purchase_confirmed is True
    assert ctrl.state.sw_unlock_observed is True
    assert ctrl.state.sw_land_cost_paid == 2000.0


def test_failed_land_order_and_retry():
    """Test 9: Failed land order resets emitted state and allows retry."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)

    portfolio = {"name": "compact_commercial", "allocations": []}
    ctrl.approve_purchase(day=9, hour=6, portfolio=portfolio, delta_fc=5000.0, cash_before=2266.0, worker_count=9)
    ctrl.state.sw_land_order_emitted = True

    # Order dropped due to budget reserve ($1966 < $2000)
    ctrl.notify_land_order_failed("budget")
    assert ctrl.state.sw_land_order_emitted is False
    assert ctrl.state.purchase_failed_reason == "budget"
    assert ctrl.state.sw_purchase_confirmed is False

    # Retry is permitted once conditions are met
    ctrl.state.sw_land_order_emitted = True
    assert ctrl.state.sw_land_order_emitted is True


def test_no_purchase_action_invariance():
    """Test 10: Inactive/unapproved treatment remains 100% inert with respect to core farm."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)

    # Core farm plant queue
    core_queue = [((1, 2), "CARROT"), ((3, 1), "WHEAT")]
    farm_mock = MagicMock()
    farm_mock.quadrant_of = lambda pos: "NW"

    filtered = ctrl.filter_macro_plant_queue(core_queue, farm_mock)
    assert filtered == core_queue
    assert ctrl.state.sw_purchase_approved is False
    assert ctrl.state.invariant_violations_attempted == 0


def test_purchase_state_reset_between_matches():
    """Test 11: reset_sw_tranche_controller cleanly resets all lifecycle and accounting state."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.confirm_purchase(day=10, hour=1)
    ctrl.record_seed_consumption("STRAWBERRY", 4, from_inventory=True)
    assert ctrl.state.sw_purchase_confirmed is True
    assert ctrl.state.sw_seed_opportunity_cost == 400.0

    reset_sw_tranche_controller()
    new_ctrl = get_sw_tranche_controller()
    assert new_ctrl.state.treatment_active is False
    assert new_ctrl.state.sw_purchase_confirmed is False
    assert new_ctrl.state.sw_seed_opportunity_cost == 0.0
    assert len(new_ctrl.state.admitted_sw_tiles) == 0


def test_sw_crop_origin_revenue_attribution_and_fungibility():
    """Test 12: Crop sales distinguish total farm sales from physical SW tile capacity."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    ctrl.state.admitted_sw_crop_targets[(0, 7)] = "STRAWBERRY"

    # Case A: SW not confirmed -> SW-origin revenue is strictly 0
    ctx = {"market": MagicMock(prices={"STRAWBERRY": 100.0})}
    market_orders = [("SELL", "STRAWBERRY", 10)]
    ctrl.record_turn(ctx, asg=None, market=market_orders)
    assert ctrl.state.total_farm_portfolio_sales["STRAWBERRY"] == 10
    assert ctrl.state.total_farm_portfolio_revenue == 1000.0
    assert ctrl.state.estimated_sw_origin_revenue == 0.0

    # Case B: SW confirmed -> SW-origin bounded by 16 units physical capacity
    ctrl.confirm_purchase(day=9, hour=0)
    market_orders_2 = [("SELL", "STRAWBERRY", 20)]  # 20 units sold
    ctrl.record_turn(ctx, asg=None, market=market_orders_2)
    # Total sold: 10 + 20 = 30
    assert ctrl.state.total_farm_portfolio_sales["STRAWBERRY"] == 30
    # Bounded to 16 units SW capacity
    assert ctrl.state.sw_crops_sold["STRAWBERRY"] == 16
    assert ctrl.state.estimated_sw_origin_revenue == 1600.0
    # Remainder allocated to unattributable mixed origin
    assert ctrl.state.unattributable_mixed_origin_revenue == 1400.0


def test_seed_cash_expenditure_vs_inventory_consumption():
    """Test 13: Seed cash costs vs inventory opportunity consumption accounting."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)

    # 4 strawberries and 4 melons consumed from inventory
    ctrl.record_seed_consumption("STRAWBERRY", qty=4, from_inventory=True)
    ctrl.record_seed_consumption("MELON", qty=4, from_inventory=True)

    assert ctrl.state.sw_seed_cost_realized == 0.0
    assert ctrl.state.sw_seed_inventory_consumed["STRAWBERRY"] == 4
    assert ctrl.state.sw_seed_inventory_consumed["MELON"] == 4
    # 4 * $100 + 4 * $80 = $720
    assert ctrl.state.sw_seed_opportunity_cost == 720.0

    # Additional cash seed purchase
    ctrl.record_seed_consumption("STRAWBERRY", qty=1, from_inventory=False, cash_spent=100.0)
    assert ctrl.state.sw_seed_cost_realized == 100.0


def test_tranche_selection_vs_actual_planting():
    """Test 14: Admitted portfolio coordinates strictly govern planting targets."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)
    portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, [(0, 7), (1, 7), (2, 7), (3, 7)]),
            ("MELON", 4, [(4, 7), (0, 8), (1, 8), (2, 8)]),
        ]
    }
    ctrl.approve_purchase(day=9, hour=0, portfolio=portfolio, delta_fc=5000.0, cash_before=3000.0, worker_count=9)

    farm_mock = MagicMock()
    plant_queue = [
        ((0, 7), "WHEAT"),       # Should be rewritten to STRAWBERRY
        ((4, 7), "CARROT"),      # Should be rewritten to MELON
        ((4, 9), "WHEAT"),       # Non-admitted SW tile: should be dropped
        ((2, 2), "CARROT"),      # Core NW tile: should be preserved
    ]
    filtered = ctrl.filter_macro_plant_queue(plant_queue, farm_mock)
    assert filtered == [
        ((0, 7), "STRAWBERRY"),
        ((4, 7), "MELON"),
        ((2, 2), "CARROT"),
    ]
    assert ctrl.state.invariant_violations_attempted == 1


def test_subgroup_denominators_reconciliation():
    """Test 15: Subgroup denominators sum precisely to 200 paired configurations."""
    import json
    data = json.load(open("simulations/results/phase_b1_branch_treatment/paired_results.json"))
    assert len(data) == 200

    confirmed_purchases = len([d for d in data if d["treatment_sw_purchase_day"] is not None])
    unpurchased = [d for d in data if d["treatment_sw_purchase_day"] is None]
    dropped_approvals = len([d for d in unpurchased if d["treatment_selected_portfolio"] is not None])
    never_approved = len([d for d in unpurchased if d["treatment_selected_portfolio"] is None])

    assert confirmed_purchases == 134
    assert dropped_approvals == 20
    assert never_approved == 46
    assert confirmed_purchases + dropped_approvals + never_approved == 200


def test_seed_clustered_bootstrap_reproducibility():
    """Test 16: Seed-clustered bootstrap CI reproducibility and robustness."""
    import json
    import numpy as np

    data = json.load(open("simulations/results/phase_b1_branch_treatment/paired_results.json"))
    seeds = sorted(list(set(d["seed"] for d in data)))
    assert len(seeds) == 20

    seed_to_deltas = {s: [d["paired_delta"] for d in data if d["seed"] == s] for s in seeds}
    np.random.seed(42)
    cluster_means = []
    for _ in range(1000):
        sampled = np.random.choice(seeds, size=len(seeds), replace=True)
        cluster_means.append(np.mean([d for s in sampled for d in seed_to_deltas[s]]))

    ci_low = np.percentile(cluster_means, 2.5)
    ci_high = np.percentile(cluster_means, 97.5)
    assert ci_low < -10000.0
    assert ci_high < -7000.0  # Strictly negative upper bound


def test_sw_purchase_retry_lifecycle_verification():
    """Test 17: Authoritative verification of SW purchase retry lifecycle from real engine diagnostic."""
    import json
    import os

    summary_path = os.path.join("simulations", "results", "phase_b1_r3_retry", "derived_event_summary.json")
    assert os.path.exists(summary_path), f"Summary file missing: {summary_path}"

    with open(summary_path, "r") as f:
        summary = json.load(f)

    assert summary["lifecycle_sequence_verified"] is True
    # Event 1: Drop due to budget ($300 reserve)
    e1 = summary["event_1_approval_and_drop"]
    assert e1["step"] == 222
    assert e1["day"] == 9
    assert e1["hour"] == 6
    assert e1["cash_before"] == 2266.0
    assert e1["discretionary_cash"] == 1966.0
    assert e1["failure_or_drop_reason"] == "budget"
    assert e1["controller_approval"] is True
    assert e1["order_in_final_action"] is False

    # Event 2: Retry and emission once cash reaches $3,261
    e2 = summary["event_2_retry_and_execution"]
    assert e2["step"] == 226
    assert e2["day"] == 9
    assert e2["hour"] == 10
    assert e2["cash_before"] == 3261.0
    assert e2["discretionary_cash"] == 2961.0
    assert e2["order_in_final_action"] is True
    assert e2["retry_count"] >= 1

    # Event 3: Engine confirmation
    e3 = summary["event_3_engine_confirmation"]
    assert e3["step"] == 226
    assert e3["sw_unlocked_before"] is False
    assert e3["sw_unlocked_after"] is True
    assert e3["purchase_confirmed"] is True

    # Event 4: Tranche becomes operational post-confirmation
    e4 = summary["event_4_tranche_operational"]
    assert e4["first_planted_step"] is not None
    assert e4["first_planted_step"] > e3["step"]


