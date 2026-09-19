"""Unit tests for Point-2 Pre-NE Capital Admission Policy.

Tests verify:
1. Default configuration: POINT2_PRE_NE_CAPITAL_MODE == "off" in both agent and submission.
2. Mode "ne_first": While NE is locked, 0 livestock candidates admitted, 0 preparatory structures.
3. Mode "ne_escrow": Protects $1,000 NE land fund, admits candidates within sequential envelope, defers excess.
4. Physical NE unlock: When NE is unlocked, normal evaluation resumes without replay of missed Day-0 sequence.
5. OrderBuilder Gate 7: OrderBuilder independently enforces pre-NE limit during final C2B replay (rejection_reason = "ne_capital_deferred").
6. Serialization & Diagnostics: DynamicHerdPlan pre_ne_diagnostics serialize cleanly.
"""

import sys
import pytest
from unittest.mock import MagicMock
import agent.config
import submission.config
from agent.config import get_point2_pre_ne_capital_mode, POINT2_PRE_NE_CAPITAL_MODE
from submission.config import get_point2_pre_ne_capital_mode as sub_get_point2_pre_ne_capital_mode, POINT2_PRE_NE_CAPITAL_MODE as SUB_POINT2_PRE_NE_CAPITAL_MODE
from agent.strategy.herd_planner import (
    generate_dynamic_herd_plan,
    DynamicHerdPlan,
    get_forward_housing_demand,
)
from agent.market.order_builder import OrderBuilder


def _patch_config_attr(monkeypatch, attr, value):
    monkeypatch.setattr(agent.config, attr, value)
    if "config" in sys.modules:
        monkeypatch.setattr(sys.modules["config"], attr, value, raising=False)


def test_pre_ne_policy_off_default():
    """Verify production default is 'off' in both agent and submission configs."""
    assert POINT2_PRE_NE_CAPITAL_MODE == "off"
    assert get_point2_pre_ne_capital_mode() == "off"
    assert SUB_POINT2_PRE_NE_CAPITAL_MODE == "off"
    assert sub_get_point2_pre_ne_capital_mode() == "off"


def test_pre_ne_ne_first_blocks_all_candidates_while_ne_locked(monkeypatch):
    """When ne_first is active and NE is locked, 0 candidates admitted and 0 structures requested."""
    _patch_config_attr(monkeypatch, "BOOTSTRAP_LIVESTOCK_ARM", "ArmE")

    # Day 0 bootstrap under ne_first
    plan = generate_dynamic_herd_plan(
        day=0,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops={"MILK": {"price": 160.0}, "WOOL": {"price": 200.0}},
        market_inventory={"MILK": 0, "WOOL": 0, "WHEAT": 50},
        feed_ledger=None,
        pre_ne_capital_mode="ne_first",
        ne_locked=True,
    )

    assert plan.desired_herd == {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    assert plan.required_pastures == 0
    assert len(plan.buy_animal_sequence) == 0
    assert plan.pre_ne_diagnostics["mode"] == "ne_first"
    assert plan.pre_ne_diagnostics["ne_locked"] is True
    assert plan.pre_ne_diagnostics["envelope_before"] == 0.0

    # Ensure deferred decision record logged
    assert len(plan.decision_records) > 0
    first_dec = plan.decision_records[0]
    assert first_dec["accepted"] is False
    assert first_dec["reason"] == "ne_capital_deferred"

    housing = get_forward_housing_demand(plan, existing_pastures=0, reserved_pasture_tiles=0)
    assert housing["needed_pastures"] == 0


def test_pre_ne_ne_escrow_bounds_candidate_admission(monkeypatch):
    """When ne_escrow is active and NE is locked, candidates are admitted only up to the envelope."""
    _patch_config_attr(monkeypatch, "BOOTSTRAP_LIVESTOCK_ARM", "ArmE")

    # ArmE target sequence is [COW, COW, COW].
    # COW purchase cost = $400.
    # Set envelope to $500: Candidate 1 ($400) fits ($100 left), Candidate 2 ($400) does not.
    plan = generate_dynamic_herd_plan(
        day=0,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops={"MILK": {"price": 160.0}, "WOOL": {"price": 200.0}},
        market_inventory={"MILK": 0, "WOOL": 0, "WHEAT": 50},
        feed_ledger=None,
        pre_ne_capital_mode="ne_escrow",
        ne_locked=True,
        pre_ne_livestock_envelope=500.0,
    )

    assert plan.desired_herd["COW"] == 1
    assert plan.desired_herd["SHEEP"] == 0
    assert plan.required_pastures == 1
    assert plan.buy_animal_sequence == ["COW"]
    assert plan.pre_ne_diagnostics["mode"] == "ne_escrow"
    assert plan.pre_ne_diagnostics["envelope_before"] == 500.0
    assert plan.pre_ne_diagnostics["envelope_remaining"] == 100.0

    # Verify decision records
    accepted_recs = [d for d in plan.decision_records if d["accepted"]]
    rejected_recs = [d for d in plan.decision_records if not d["accepted"]]
    assert len(accepted_recs) == 1
    assert accepted_recs[0]["species"] == "COW"
    assert len(rejected_recs) >= 1
    assert rejected_recs[0]["reason"] == "ne_capital_deferred"

    housing = get_forward_housing_demand(plan, existing_pastures=0, reserved_pasture_tiles=0)
    assert housing["needed_pastures"] == 1


def test_pre_ne_physical_ne_unlock_resumes_normal_evaluation(monkeypatch):
    """When ne_locked is False, pre-NE limits do NOT constrain candidate admission."""
    _patch_config_attr(monkeypatch, "BOOTSTRAP_LIVESTOCK_ARM", "ArmE")

    plan = generate_dynamic_herd_plan(
        day=0,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops={"MILK": {"price": 160.0}, "WOOL": {"price": 200.0}},
        market_inventory={"MILK": 0, "WOOL": 0, "WHEAT": 50},
        feed_ledger=None,
        pre_ne_capital_mode="ne_first",
        ne_locked=False,
    )

    # ArmE has 3 Cows
    assert plan.desired_herd["COW"] == 3
    assert plan.required_pastures == 3
    assert len(plan.buy_animal_sequence) == 3
    assert plan.pre_ne_diagnostics["ne_locked"] is False


def test_order_builder_gate7_enforces_pre_ne_deferral(monkeypatch):
    """OrderBuilder independently enforces Gate 7 Pre-NE Capital Gate."""
    _patch_config_attr(monkeypatch, "POINT2_FEED_MODE", "live")
    _patch_config_attr(monkeypatch, "BOOTSTRAP_LIVESTOCK_ARM", "ArmE")
    _patch_config_attr(monkeypatch, "POINT2_PRE_NE_CAPITAL_MODE", "ne_first")

    ob = OrderBuilder(money_reserve=50.0)

    from agent.tests.test_c2c_arbitration import make_ctx, MockSnapshot

    snap = MockSnapshot(
        post_unit_state_verified=True,
        post_unit_shed_inventory={"WHEAT": 50},
        post_unit_shed_occupancy=0,
        post_unit_worker_inventory_total=0,
    )
    snap.market_purchase_can_help_today = True
    ctx = make_ctx(day=0, hour=0, money=2000, shed_wheat=50, snapshot=snap)
    ctx["farm"].unlocked = ["NW"]

    # Macro planner intents proposes 2 cows
    intents = {
        "hire": 0,
        "buy_land": False,
        "buy_seed": {},
        "buy_animal": {"COW": 2},
        "buy_animal_sequence": ["COW", "COW"],
        "buy_wheat": 0,
        "pending_structures": {"PASTURE": 2},
        "execution_snapshot": snap,
    }

    orders, ledger = ob.build(ctx, intents)

    # Animals must be dropped due to Gate 7 under ne_first
    animal_orders = [o for o in orders if len(o) > 0 and o[0] == "BUY_ANIMAL"]
    assert len(animal_orders) == 0

    dropped_animals = [d for d in ledger.get("dropped", []) if d.get("kind") == "animal"]
    assert len(dropped_animals) == 2
    assert all(d.get("reason") == "ne_capital_deferred" for d in dropped_animals)

    decisions = ledger["live_c2b_diagnostics"]["candidate_decisions"]
    assert len(decisions) == 2
    assert all(d["rejection_reason"] == "ne_capital_deferred" for d in decisions)


def test_pre_ne_diagnostics_serialization():
    """Test DynamicHerdPlan to_dict serialization includes pre_ne_diagnostics."""
    plan = DynamicHerdPlan(
        desired_herd={"COW": 1, "SHEEP": 0, "GOOSE": 0},
        required_pastures=1,
        required_coops=0,
        marginal_value_sequence=["test"],
        decision_records=[],
        pre_ne_diagnostics={
            "mode": "ne_escrow",
            "ne_locked": True,
            "envelope_before": 600.0,
            "envelope_remaining": 150.0,
            "candidates": [{"species": "COW", "admitted": True}],
        },
    )

    d = plan.to_dict()
    assert "pre_ne_diagnostics" in d
    assert d["pre_ne_diagnostics"]["mode"] == "ne_escrow"
    assert d["pre_ne_diagnostics"]["envelope_remaining"] == 150.0


def test_pre_ne_animal_pricing_authoritative(monkeypatch):
    """Verify authoritative costs: COW $400, SHEEP $500, GOOSE $300 (not stale hardcoded values)."""
    _patch_config_attr(monkeypatch, "BOOTSTRAP_LIVESTOCK_ARM", "ArmC")  # ArmC is [COW, COW, SHEEP]

    # Test SHEEP candidate with envelope = $450
    # COW 1 ($400) admitted -> envelope left = $50.
    # COW 2 ($400) deferred.
    # Now test single SHEEP candidate: with envelope = $450, a $500 sheep must be deferred (would pass if $250!)
    plan = generate_dynamic_herd_plan(
        day=0,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops={"MILK": {"price": 160.0}, "WOOL": {"price": 200.0}},
        market_inventory={"MILK": 0, "WOOL": 0, "WHEAT": 50},
        feed_ledger=None,
        pre_ne_capital_mode="ne_escrow",
        ne_locked=True,
        pre_ne_livestock_envelope=450.0,
    )
    # Cow 1 is $400 <= 450 -> admitted. Cow 2 is $400 > 50 -> deferred.
    assert plan.desired_herd["COW"] == 1
    # Verify candidate 1 cost was 400
    assert plan.pre_ne_diagnostics["candidates"][0]["package_cost"] == 400.0

    # Direct test with custom target where first animal is SHEEP
    _patch_config_attr(monkeypatch, "get_bootstrap_target_sequence", lambda arm: ["SHEEP"])
    plan_sheep = generate_dynamic_herd_plan(
        day=0,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops={"MILK": {"price": 160.0}, "WOOL": {"price": 200.0}},
        market_inventory={"MILK": 0, "WOOL": 0, "WHEAT": 50},
        feed_ledger=None,
        pre_ne_capital_mode="ne_escrow",
        ne_locked=True,
        pre_ne_livestock_envelope=450.0,
    )
    assert plan_sheep.desired_herd["SHEEP"] == 0
    assert plan_sheep.pre_ne_diagnostics["candidates"][0]["admitted"] is False
    assert plan_sheep.pre_ne_diagnostics["candidates"][0]["package_cost"] == 500.0

    # If envelope is 550, SHEEP ($500) passes
    plan_sheep_admit = generate_dynamic_herd_plan(
        day=0,
        hour=0,
        current_herd={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        town_shops={"MILK": {"price": 160.0}, "WOOL": {"price": 200.0}},
        market_inventory={"MILK": 0, "WOOL": 0, "WHEAT": 50},
        feed_ledger=None,
        pre_ne_capital_mode="ne_escrow",
        ne_locked=True,
        pre_ne_livestock_envelope=550.0,
    )
    assert plan_sheep_admit.desired_herd["SHEEP"] == 1
    assert plan_sheep_admit.pre_ne_diagnostics["candidates"][0]["admitted"] is True
    assert plan_sheep_admit.pre_ne_diagnostics["candidates"][0]["package_cost"] == 500.0
    assert plan_sheep_admit.pre_ne_diagnostics["envelope_remaining"] == 50.0
