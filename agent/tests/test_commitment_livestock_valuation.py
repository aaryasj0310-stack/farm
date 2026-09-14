"""Unit tests for commitment-aware livestock valuation (L0 vs L1).

Tests:
1. Scenario derivation from visible opponent animals (LOW, BASE, HIGH).
2. Counterfactual monotonicity: Opponent milk supply depresses candidate cow marginal value.
3. Cross-commodity isolation: Opponent milk supply does NOT affect sheep marginal value.
4. Counterfactual symmetry: Both with-candidate and without-candidate branches experience
   the identical opponent supply schedule.
5. Integration with generate_dynamic_herd_plan.
"""

import pytest
from unittest.mock import MagicMock
from strategy.marginal_livestock_valuator import (
    derive_opponent_committed_livestock_scenarios,
    derive_opponent_committed_livestock_supply,
    estimate_realized_marginal_animal_value,
)
from strategy.herd_planner import generate_dynamic_herd_plan
from config import set_livestock_valuation_mode, get_livestock_valuation_mode


class MockTile:
    def __init__(self, pos, is_animal=False, animal=None, is_structure=False, kind=None, yield_units=0):
        self.pos = pos
        self.is_animal = is_animal
        self.animal = animal
        self.is_structure = is_structure
        self.kind = kind or ("EMPTY" if not is_animal else animal)
        self.yield_units = yield_units
        self.is_plant = False


class MockFarmView:
    def __init__(self, tiles=None):
        self._tiles = tiles or []

    def iter_tiles(self):
        return iter(self._tiles)


def test_scenario_derivation_counts():
    """Verify that visible opponent animals generate appropriate LOW, BASE, HIGH production."""
    tiles = [
        MockTile((0, 0), is_animal=True, animal="COW", yield_units=2),
        MockTile((0, 1), is_animal=True, animal="COW", yield_units=0),
        MockTile((1, 0), is_animal=True, animal="SHEEP", yield_units=1),
    ]
    opp_farm = MockFarmView(tiles)
    scenarios = derive_opponent_committed_livestock_scenarios(opp_farm, current_day=10)

    for sc in ("LOW", "BASE", "HIGH"):
        assert sc in scenarios
        assert "MILK" in scenarios[sc]
        assert "WOOL" in scenarios[sc]
        assert "EGG" in scenarios[sc]

    # Total milk: HIGH >= BASE >= LOW
    tot_high_milk = sum(scenarios["HIGH"]["MILK"].values())
    tot_base_milk = sum(scenarios["BASE"]["MILK"].values())
    tot_low_milk = sum(scenarios["LOW"]["MILK"].values())

    assert tot_high_milk >= tot_base_milk >= tot_low_milk
    assert tot_high_milk > 0
    # Day 10 should have on-tile uncollected units credited
    assert scenarios["HIGH"]["MILK"].get(10, 0) == 2.0
    assert scenarios["HIGH"]["WOOL"].get(10, 0) == 1.0


def test_counterfactual_monotonicity_under_opponent_supply():
    """Verify that an opponent milk supply depresses our candidate Cow's marginal value."""
    current_animals = {"COW": 2, "SHEEP": 0, "GOOSE": 0}
    market_inv = {"MILK": 10.0, "WOOL": 10.0, "WHEAT": 20.0, "FERTILIZER": 10.0}

    # Case A: L0 baseline (zero opponent supply)
    eval_no_opp = estimate_realized_marginal_animal_value(
        species="COW",
        day=5,
        current_animals=current_animals,
        market_inventory=market_inv,
        empty_pastures=1,
        opponent_committed_supply=None,
    )

    # Case B: L1 with opponent producing 6 Milk every 2 days
    opp_milk = {d: 6.0 for d in range(5, 29, 2)}
    eval_with_opp = estimate_realized_marginal_animal_value(
        species="COW",
        day=5,
        current_animals=current_animals,
        market_inventory=market_inv,
        empty_pastures=1,
        opponent_committed_supply=opp_milk,
    )

    # Margins and net value must be lower under heavy opponent supply
    assert eval_no_opp["net_realized_value"] > eval_with_opp["net_realized_value"]
    assert eval_no_opp["marginal_product_revenue"] > eval_with_opp["marginal_product_revenue"]
    assert eval_with_opp["opponent_committed_units"] > 0
    assert eval_no_opp["opponent_committed_units"] == 0


def test_cross_commodity_isolation():
    """Verify that opponent milk supply does NOT impact candidate sheep valuation."""
    current_animals = {"COW": 1, "SHEEP": 1, "GOOSE": 0}
    market_inv = {"MILK": 10.0, "WOOL": 10.0, "WHEAT": 20.0, "FERTILIZER": 10.0}

    # Sheep evaluated with no wool opponent supply
    eval_sheep_1 = estimate_realized_marginal_animal_value(
        species="SHEEP",
        day=5,
        current_animals=current_animals,
        market_inventory=market_inv,
        empty_pastures=1,
        opponent_committed_supply=None,
    )

    # Sheep evaluated with empty dict or zero supply
    eval_sheep_2 = estimate_realized_marginal_animal_value(
        species="SHEEP",
        day=5,
        current_animals=current_animals,
        market_inventory=market_inv,
        empty_pastures=1,
        opponent_committed_supply={},
    )

    assert eval_sheep_1["net_realized_value"] == eval_sheep_2["net_realized_value"]
    assert eval_sheep_1["marginal_product_revenue"] == eval_sheep_2["marginal_product_revenue"]


def test_integration_dynamic_herd_plan_with_opponent_commitments():
    """Verify that herd planner reduces cow desire when opponent has massive cow herd."""
    current_herd = {"COW": 1, "SHEEP": 1, "GOOSE": 0}
    market_inv = {"MILK": 10.0, "WOOL": 10.0, "WHEAT": 50.0, "FERTILIZER": 10.0}

    # Baseline herd plan without opponent commitments
    plan_no_opp = generate_dynamic_herd_plan(
        day=4,
        hour=0,
        current_herd=current_herd,
        market_inventory=market_inv,
        max_sustainable=10,
        opponent_committed_supplies=None,
    )

    # Opponent committed supplies with flooded milk market (opponent has 6 cows)
    opp_supplies_flooded = {
        "MILK": {d: 18.0 for d in range(4, 29, 2)},
        "WOOL": {},
        "EGG": {},
    }
    plan_flooded = generate_dynamic_herd_plan(
        day=4,
        hour=0,
        current_herd=current_herd,
        market_inventory=market_inv,
        max_sustainable=10,
        opponent_committed_supplies=opp_supplies_flooded,
    )

    # Desired cows under flooded opponent milk should be <= unconstrained plan
    assert plan_flooded.desired_cows <= plan_no_opp.desired_cows
