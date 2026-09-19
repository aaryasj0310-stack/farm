"""Regression test suite for land purchase affordability and treasury protection.

Verifies:
  Test A: Existing wheat reduces the feed commitment used by the land gate.
  Test B: A planned Cow/Sheep does not block an otherwise affordable higher-priority land purchase.
  Test C: NE can still be accumulated toward and purchased after missing Day-3-6 shortcut if ROI > 0.
  Test D: SW treasury protection continues after Day 11 while SW remains profitable/serviceable.
  Test E: OrderBuilder still prioritizes survival feed and land ahead of seeds/animals.
  Test F: Existing livestock safety tests remain unchanged and passing.
  Test G: Future wheat timing: wheat maturing late does not offset near-term feed need;
          wheat maturing before the deadline does reduce the commitment.
  Test H: No double reserve: land is affordable with exactly land + seed + mandatory + 1x reserve.
"""
import pytest

from config import (
    LAND_PRICES,
    MONEY_RESERVE_DEFAULT,
    FEED_WHEAT_BUFFER_DAYS,
    LAND_BUY_LAST_DAY,
)
from market.order_builder import OrderBuilder
from strategy.expansion_planner import should_buy_land, compute_land_urgency
from strategy.macro_planner import (
    MacroPlanner,
    compute_unavoidable_feed_shortfall,
)
from test_macro_planner import make_ctx, make_forecast, BASE_PRICES


def test_a_existing_wheat_reduces_feed_commitment():
    """Test A: Existing wheat in shed or inventory reduces feed commitment used by land gate."""
    fc = make_forecast(BASE_PRICES)
    ctx_no_wheat = make_ctx(day=10, money=3000, shed={}, unlocked=("NW", "NE"))
    ctx_no_wheat["farm"].tiles[0][0] = {
        "kind": "PASTURE", "animal": "COW", "is_animal": True,
        "consecutive_unfed": 0, "pos": (0, 0), "x": 0, "y": 0
    }
    ctx_no_wheat["farm"].tiles[0][1] = {
        "kind": "PASTURE", "animal": "COW", "is_animal": True,
        "consecutive_unfed": 0, "pos": (0, 1), "x": 0, "y": 1
    }

    _, _, deficit_no_w, cost_no_w = compute_unavoidable_feed_shortfall(
        ctx_no_wheat["farm"], ctx_no_wheat["private"], day=10, n_animals=2, feed_buffer=4
    )
    assert deficit_no_w == 8
    assert cost_no_w == 200.0

    ctx_with_wheat = make_ctx(day=10, money=3000, shed={"WHEAT": 8}, unlocked=("NW", "NE"))
    ctx_with_wheat["farm"].tiles[0][0] = ctx_no_wheat["farm"].tiles[0][0]
    ctx_with_wheat["farm"].tiles[0][1] = ctx_no_wheat["farm"].tiles[0][1]

    _, _, deficit_w, cost_w = compute_unavoidable_feed_shortfall(
        ctx_with_wheat["farm"], ctx_with_wheat["private"], day=10, n_animals=2, feed_buffer=4
    )
    assert deficit_w == 0
    assert cost_w == 0.0

    ok_no_w, reason_no_w, _ = should_buy_land(
        next_quadrant=3, current_day=10, money=2450, farm=ctx_no_wheat["farm"],
        hire_cost=0, feed_cost=cost_no_w, animal_cost=0, reserve=250, roi=0.5,
        forecast=fc, seeds_owned={"WHEAT": 10}
    )
    assert ok_no_w is False
    assert "short_" in reason_no_w

    ok_w, reason_w, _ = should_buy_land(
        next_quadrant=3, current_day=10, money=2450, farm=ctx_with_wheat["farm"],
        hire_cost=0, feed_cost=cost_w, animal_cost=0, reserve=250, roi=0.5,
        forecast=fc, seeds_owned={"WHEAT": 10}
    )
    assert ok_w is True
    assert reason_w == "treasury_sufficient_roi_positive"


def test_b_planned_animal_does_not_block_land_purchase():
    """Test B: A planned Cow/Sheep does not block an otherwise affordable higher-priority land purchase."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=10, money=2450, shed={"WHEAT": 20}, unlocked=("NW", "NE"))
    ok, reason, diag = should_buy_land(
        next_quadrant=3, current_day=10, money=2450, farm=ctx["farm"],
        hire_cost=0, feed_cost=0, animal_cost=400, reserve=250, roi=0.5,
        forecast=fc, seeds_owned={"WHEAT": 10}
    )
    assert ok is True
    assert reason == "treasury_sufficient_roi_positive"
    assert diag["planned_animal_cost"] == 400.0
    assert diag["true_mandatory_commitment"] == 0.0
    assert diag["total_required_cash"] <= 2450.0


def test_c_ne_accumulated_and_purchased_after_missing_early_shortcut():
    """Test C: NE can still be accumulated toward and purchased after missing Day 3-6 shortcut if ROI > 0."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=7, money=1650, shed={}, unlocked=("NW",))
    ok, reason, diag = should_buy_land(
        next_quadrant=2, current_day=7, money=1650, farm=ctx["farm"],
        hire_cost=0, feed_cost=0, animal_cost=0, reserve=250, roi=0.5,
        forecast=fc
    )
    assert ok is True
    assert reason == "treasury_sufficient_roi_positive"
    assert diag["total_required_cash"] == 1610.0


def test_d_sw_treasury_protection_continues_after_day_11():
    """Test D: SW treasury protection continues across Days 12-14 while SW remains profitable and serviceable."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=12, money=2800, shed={"WHEAT": 10}, unlocked=("NW", "NE"))
    plan = MacroPlanner(fc).build(ctx)

    land_diag = plan.diagnostics.get("land_decision", {})
    assert land_diag.get("day") == 12
    assert land_diag.get("next_quadrant") == 3
    if plan.intents.get("buy_land"):
        assert plan.intents["buy_land"] is True
    else:
        assert land_diag.get("treasury_protection_active") is True


def test_e_order_builder_prioritizes_feed_and_land_over_seeds_and_animals():
    """Test E: OrderBuilder still prioritizes survival feed and land ahead of seeds/animals."""
    ctx = make_ctx(day=10, money=2600, shed={"WHEAT": 5}, unlocked=("NW", "NE"))
    intents = {
        "buy_wheat": 4,
        "buy_land": True,
        "buy_seed": {"MELON": 10},
        "buy_animal": {"COW": 1},
        "pending_structures": {"PASTURE": 1},
    }
    orders, ledger = OrderBuilder().build(ctx, intents)

    order_types = [o[0] for o in orders]
    assert "BUY_LAND" in order_types
    assert any(o[0] == "BUY_PRODUCT" and o[1] == "WHEAT" for o in orders)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(d.get("kind") == "animal" and d.get("reason") == "budget" for d in ledger.get("dropped", []))


def test_f_housing_safe_reinvestment_invariants_pass(monkeypatch):
    """Test F: Existing livestock housing safety invariants remain strictly enforced."""
    import config
    monkeypatch.setattr(config, "SELECTIVE_LIVESTOCK_GATE_ENABLED", True)
    monkeypatch.setattr(config, "SELECTIVE_LIVESTOCK_MAX_DAY", 14)
    ctx = make_ctx(day=13, money=5000, shed={}, unlocked=("NW", "NE"))
    ctx["hour"] = 5
    intents = {
        "buy_animal": {"COW": 1},
        "pending_structures": {"PASTURE": 1},
    }
    # With 0 physical empty pastures on farm, post-cutoff reinvestment must drop animal
    orders, ledger = OrderBuilder().reinvest_livestock(ctx, intents)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert any(d.get("kind") == "animal" and d.get("reason") == "no_empty_structure" for d in ledger.get("dropped", []))


def test_g_future_wheat_timing():
    """Test G: Wheat maturing late does not offset near-term feed need;
    wheat maturing before the deadline does reduce the commitment.
    """
    ctx = make_ctx(day=10, money=2000, shed={}, unlocked=("NW",))
    ctx["farm"].tiles[1][1] = {
        "kind": "PLANT", "crop": "WHEAT", "is_plant": True,
        "planted_day": 9, "pos": (1, 1), "x": 1, "y": 1
    }
    w_hand, req, max_def, cost = compute_unavoidable_feed_shortfall(
        ctx["farm"], ctx["private"], day=10, n_animals=2, feed_buffer=4
    )
    assert max_def == 6
    assert cost == 150.0

    ctx["farm"].tiles[1][1]["planted_day"] = 6
    w_hand, req, max_def2, cost2 = compute_unavoidable_feed_shortfall(
        ctx["farm"], ctx["private"], day=10, n_animals=2, feed_buffer=4
    )
    assert max_def2 == 4
    assert cost2 == 100.0


def test_h_no_double_reserve():
    """Test H: Land is affordable with exactly land + seed_tranche + mandatory + 1x reserve."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=10, money=2400, shed={}, unlocked=("NW", "NE"))
    ok, reason, diag = should_buy_land(
        next_quadrant=3, current_day=10, money=2400, farm=ctx["farm"],
        hire_cost=0, feed_cost=0, animal_cost=0, reserve=250, roi=0.5,
        forecast=fc, seeds_owned={}
    )
    assert ok is True
    assert reason == "treasury_sufficient_roi_positive"
    assert diag["shortfall"] == 0.0
    assert diag["total_required_cash"] == 2400.0
