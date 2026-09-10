"""Tests for Issue 2: Safe, survival-capable emergency fallback and failure domain isolation.

Requirements:
- Deterministic planner exception does not create repeated all-unit PASS when urgent watering exists
- Feeds starving animal when holding wheat
- No invalid FEED when wheat only in shed
- Recurring exception allows survival actions across turns
- Market/opponent failure does not suppress unit actions
"""

import pytest
from unittest.mock import patch
from main import agent, _emergency_fallback
from observation_parser import parse_observation


def make_obs(farmer=(4, 4), hands=None, tiles=None, inventories=None, shed=None, day=5, hour=0):
    board = 10
    raw_tiles = [[None] * board for _ in range(board)]
    if tiles:
        for (x, y, obj) in tiles:
            raw_tiles[y][x] = obj
    farm = {
        "money": 1000.0,
        "tiles": raw_tiles,
        "farmer": list(farmer),
        "hands": list(hands or []),
        "unlocked_quadrants": ["NW", "NE", "SW"],
        "hires_today": 0,
    }
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    inv = {p: 10000 for p in products}
    return {
        "player": 0,
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
        "farms": [farm, farm],
        "market": {"inventory": inv, "prices": {}},
        "town": {"unlocked_shops": []},
        "private": {
            "shed": dict(shed or {}),
            "seeds": {},
            "inventories": list(inventories or [{}]),
        },
    }


def test_deterministic_planner_exception_does_not_create_repeated_pass_when_urgent_watering_exists():
    """When planner throws an exception, unit does not PASS if an urgent crop needs water."""
    dying_plant = {
        "kind": "PLANT",
        "crop": "CARROT",
        "consecutive_unwatered": 1,
        "watered_today": False,
        "planted_day": 3,
        "growth": 2,
        "yield_units": 0,
    }
    # Farmer standing right on the dying plant tile (4, 4)
    obs = make_obs(farmer=(4, 4), tiles=[(4, 4, dying_plant)])

    with patch("strategy.macro_planner.MacroPlanner.build", side_effect=RuntimeError("Planner deterministic crash")):
        action = agent(obs)

    # Unit must water the dying plant, not blanket PASS!
    assert action["farmer"] == ["WATER"]


def test_feeds_starving_animal_when_holding_wheat():
    """Unit feeds animal in immediate survival danger when holding wheat."""
    starving_cow = {
        "kind": "PASTURE",
        "animal": "COW",
        "consecutive_unfed": 1,
        "fed_today": False,
        "yield_units": 0,
    }
    # Farmer standing on the cow tile (4, 4), holding 2 WHEAT in inventory
    obs = make_obs(farmer=(4, 4), tiles=[(4, 4, starving_cow)], inventories=[{"WHEAT": 2}])

    with patch("strategy.macro_planner.MacroPlanner.build", side_effect=RuntimeError("Planner crashed")):
        action = agent(obs)

    assert action["farmer"] == ["FEED"]


def test_no_invalid_feed_when_wheat_only_in_shed():
    """When wheat is only in the shed (not in unit inventory), do NOT emit invalid FEED."""
    starving_cow = {
        "kind": "PASTURE",
        "animal": "COW",
        "consecutive_unfed": 1,
        "fed_today": False,
        "yield_units": 0,
    }
    dying_plant = {
        "kind": "PLANT",
        "crop": "TOMATO",
        "consecutive_unwatered": 1,
        "watered_today": False,
        "yield_units": 0,
    }
    # Farmer at (4, 4). Unit inventory has 0 wheat, but shed has 50 wheat.
    # Animal at (4, 4), plant at (4, 3).
    obs = make_obs(
        farmer=(4, 4),
        tiles=[(4, 4, starving_cow), (4, 3, dying_plant)],
        inventories=[{}],
        shed={"WHEAT": 50},
    )

    with patch("strategy.macro_planner.MacroPlanner.build", side_effect=RuntimeError("Planner crashed")):
        action = agent(obs)

    # Unit cannot feed because inventory has no wheat!
    assert action["farmer"] != ["FEED"], "Must NOT emit invalid FEED without wheat in inventory"
    # Unit should instead water the dying plant (takes 1 step NORTH)
    assert action["farmer"] == ["NORTH"]


def test_recurring_exception_allows_survival_actions_across_turns():
    """Across turns under persistent exceptions, unit steps toward dying crop and waters it."""
    dying_plant = {
        "kind": "PLANT",
        "crop": "MELON",
        "consecutive_unwatered": 1,
        "watered_today": False,
        "yield_units": 0,
    }

    with patch("strategy.macro_planner.MacroPlanner.build", side_effect=RuntimeError("Persistent crash")):
        # Turn 1: Farmer at (4, 4), plant at (4, 2) -> step NORTH toward (4, 2)
        obs1 = make_obs(farmer=(4, 4), tiles=[(4, 2, dying_plant)], hour=0)
        action1 = agent(obs1)
        assert action1["farmer"] == ["NORTH"]

        # Turn 2: Farmer moved to (4, 3) -> step NORTH toward (4, 2)
        obs2 = make_obs(farmer=(4, 3), tiles=[(4, 2, dying_plant)], hour=1)
        action2 = agent(obs2)
        assert action2["farmer"] == ["NORTH"]

        # Turn 3: Farmer arrived at (4, 2) -> WATER!
        obs3 = make_obs(farmer=(4, 2), tiles=[(4, 2, dying_plant)], hour=2)
        action3 = agent(obs3)
        assert action3["farmer"] == ["WATER"]


def test_market_and_opponent_failure_does_not_suppress_unit_actions():
    """Failure in opponent modeling or market brain does not crash or suppress unit actions."""
    obs = make_obs(farmer=(4, 4), hour=5)

    with patch("market.market_brain.MarketBrain.sell_orders", side_effect=RuntimeError("Sell brain crash")):
        with patch("strategy.opponent_advisor.build_opponent_advice", side_effect=RuntimeError("Opponent crash")):
            action = agent(obs)

    # Unit actions must still be emitted (not suppressed)
    assert "farmer" in action
    assert isinstance(action["farmer"], list)
    assert len(action["farmer"]) >= 1
    assert action.get("market") == [] or isinstance(action.get("market"), list)
