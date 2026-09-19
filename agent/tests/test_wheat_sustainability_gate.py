"""Regression tests for Wheat Sustainability Livestock Constraint.

Verifies:
1. Economic model desiring animals is clamped by projected feed capacity.
2. Purchases satisfy projected_feed_supply >= projected_feed_demand.
3. No ungrounded early-game exception exists.
4. Telemetry diagnostics accurately report projected wheat supply, demand,
   sustainable herd size, requested herd size, and final feed-capped herd size.
"""
import pytest
import config

from strategy.animal_planner import get_animal_targets
from strategy.macro_planner import (
    MacroPlanner,
    compute_authoritative_feed_capacity,
)
from strategy.price_forecast import PriceForecast
from observation_parser import parse_observation
from state.state_tracker import reset_memory


class FakeFC:
    def __init__(self):
        pass

    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        return 50.0


def _make_farm_ctx(day=6, money=10000.0, shed_wheat=0, planted_wheat_tiles=0, pastures=4):
    board = 10
    tiles = [[None] * board for _ in range(board)]
    for y in range(board):
        for x in range(board):
            if x >= 5 or y >= 5:
                tiles[y][x] = "LOCKED"
            else:
                tiles[y][x] = {"kind": "EMPTY", "pos": (x, y)}

    # Place empty pastures
    for p in range(pastures):
        tiles[p][0] = {"kind": "PASTURE", "pos": (0, p), "animal": None, "is_animal": False}

    # Place planted wheat tiles
    for w in range(planted_wheat_tiles):
        tiles[w][1] = {
            "kind": "PLANT", "pos": (1, w), "crop": "WHEAT", "is_plant": True,
            "planted_day": day, "fertilized_until_day": -1, "max_yield": 4,
        }

    farm = {
        "money": money, "tiles": tiles, "farmer": [4, 4],
        "hands": [[0, 1], [0, 2], [0, 3]], "unlocked": ["NW"]
    }
    private = {
        "shed": {"WHEAT": shed_wheat},
        "inventories": [{}],
        "seeds": {},
    }
    market = {"inventory": {p: 10000 for p in ("WHEAT", "COW", "SHEEP")}}
    town = {"shops": {}}
    obs = {"day": day, "hour": 0, "farms": [farm, farm], "private": private,
           "market": market, "town": town, "step": day * 24}
    return parse_observation(obs)


def test_insufficient_wheat_capacity_blocks_animal_expansion():
    """When the economic model has cash and empty pastures for 4 sheep/cows,
    but zero wheat on hand and zero planted wheat, sustainable herd is strictly limited.
    """
    reset_memory()
    # Day 6, $10,000 cash, 4 empty pastures, but 0 shed wheat and 0 planted wheat
    # Feeding days left = 29 - 6 = 23 days.
    # Discretionary cash could buy emergency wheat, but sustainable herd is strictly
    # bounded by projected_feed_supply // feeding_days_left.
    ctx = _make_farm_ctx(day=6, money=10000.0, shed_wheat=0, planted_wheat_tiles=0, pastures=4)

    planner = MacroPlanner(FakeFC())
    plan = planner.build(ctx)

    diag = plan.diagnostics
    assert "projected_wheat_supply" in diag
    assert "projected_wheat_demand" in diag
    assert "sustainable_herd_size" in diag
    assert "requested_herd_size" in diag
    assert "final_feed_capped_herd_size" in diag

    # The final feed-capped herd size must never exceed sustainable herd size
    assert diag["final_feed_capped_herd_size"] <= diag["sustainable_herd_size"]
    # And feed supply must satisfy demand
    assert diag["projected_wheat_supply"] >= diag["projected_wheat_demand"]


def test_get_animal_targets_clamped_by_max_sustainable():
    """get_animal_targets directly restricts herd when max_sustainable is small."""
    # Day 6, $10,000 cash, room for 6 animals, but max_sustainable = 2
    targets = get_animal_targets(
        day=6,
        money=10000.0,
        shed_wheat=10,
        current_animals={"COW": 0, "SHEEP": 0, "GOOSE": 0},
        max_pastures=6,
        max_sustainable=2,
    )
    total_target = sum(targets.values())
    assert total_target <= 2, f"Expected total target <= 2, got {total_target}"


def test_direct_feed_capacity_calculation():
    """compute_authoritative_feed_capacity accounts for shed wheat and planted harvests."""
    ctx = _make_farm_ctx(day=10, money=1000.0, shed_wheat=40, planted_wheat_tiles=3, pastures=2)
    farm = ctx["farm"]
    private = ctx["private"]

    info = compute_authoritative_feed_capacity(farm, private, day=10, season_end=28)
    # Remaining feeding days: 28 - 10 + 1 = 19
    assert info["feeding_days_left"] == 19
    assert info["wheat_on_hand"] == 40
    # 3 planted wheat tiles maturing at day 10 + 4 = 14 <= 28, yield 4 each = 12
    assert info["planted_yield"] == 12
    # Base supply >= 40 + 12 = 52
    assert info["projected_wheat_supply"] >= 52
    assert info["sustainable_herd_size"] == info["projected_wheat_supply"] // 19


def test_no_early_game_unfunded_exception(monkeypatch):
    """On Day 1, an agent with 0 wheat and insufficient cash cannot buy animals."""
    monkeypatch.setattr(config, "LIVESTOCK_EXPERIMENT_ARM", "ArmA")
    reset_memory()
    # Day 1, barely any money, 0 wheat
    ctx = _make_farm_ctx(day=1, money=100.0, shed_wheat=0, planted_wheat_tiles=0, pastures=2)
    planner = MacroPlanner(FakeFC())
    plan = planner.build(ctx)

    # Cannot buy any animals
    assert plan.intents.get("buy_animal", {}) == {} or sum(plan.intents.get("buy_animal", {}).values()) == 0
    assert plan.diagnostics["final_feed_capped_herd_size"] == 0
