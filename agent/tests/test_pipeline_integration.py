"""Full-pipeline integration: MacroPlanner -> task_scheduler -> REAL engine.

Drives a live kaggriculture environment turn-by-turn. The decision layers
under audit produce farmer/hands actions; scripted market orders stand in for
the not-yet-built order_builder/market_brain (documented seam), so that the
ENGINE-side executability of every planned intent is still proven end to end.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

pytest.importorskip("kaggle_environments")

from engine_bridge import PASS_ACTION
from observation_parser import parse_observation
from strategy.price_forecast import PriceForecast
from strategy.macro_planner import MacroPlanner
from execution.task_scheduler import assign_tasks, build_tasks

SCRIPTED_ORDERS = {
    (0, 0): [["HIRE"], ["BUY_SEED", "MELON", 6]],       # $1 + $480
    (1, 0): [["BUY_PRODUCT", "WHEAT", 20]],             # feed buffer
    (2, 0): [["BUY_ANIMAL", "GOOSE", 1]],               # goose -> shed
    (4, 0): [["BUY_LAND"]],                             # NE quadrant $1000
}


def _snapshot(ctx):
    farm = ctx["farm"]
    melons = sum(1 for t in farm.iter_tiles()
                 if t.is_plant and t.crop == "MELON")
    coops = sum(1 for t in farm.iter_tiles() if t.kind == "COOP")
    geese = sum(1 for t in farm.iter_tiles() if t.animal == "GOOSE")
    wheat_held = sum(int(inv.get("WHEAT", 0))
                     for inv in ctx["private"].inventories)
    fed_now = any(t.is_animal and t.fed_today for t in farm.iter_tiles())
    return {
        "day": ctx["day"], "hour": ctx["hour"],
        "money": farm.money,
        "melons": melons, "coops": coops, "geese": geese,
        "wheat_held": wheat_held, "fed_now": fed_now,
        "ne_unlocked": "NE" in farm.unlocked,
        "hands": len(farm.hands),
    }


def test_full_pipeline_walk_planner_scheduler_real_engine():
    fc = PriceForecast.load()
    planner = MacroPlanner(fc)
    env = pytest.importorskip("kaggle_environments").make(
        "kaggriculture", configuration={"seed": 7})

    snapshots = []
    max_steps = 120                                    # days 0..4
    for _ in range(max_steps):
        obs = env.state[0].observation
        ctx = parse_observation(obs)
        if ctx is None:
            act = dict(PASS_ACTION)                    # engine not initialized yet
        else:
            key = (ctx["day"], ctx["hour"])
            market = list(SCRIPTED_ORDERS.get(key, []))

            plan = planner.build(ctx, boosts={})
            tasks = build_tasks(ctx, plan)
            asg = assign_tasks(tasks, ctx)

            n_units = 1 + len(ctx["farm"].hands)
            act = {
                "farmer": list(asg["actions"].get(0, ["PASS"])),
                "hands": [list(asg["actions"].get(i, ["PASS"]))
                          for i in range(1, n_units)],
                "market": market,
            }
            snapshots.append(_snapshot(ctx))

        try:
            env.step([act, dict(PASS_ACTION)])
        except Exception as e:                          # zero-exception goal
            pytest.fail(f"engine raised during pipeline walk: {e!r}")

    assert snapshots, "no turns executed"
    final = snapshots[-1]
    ever = {
        "melons": max(s["melons"] for s in snapshots),
        "coops": max(s["coops"] for s in snapshots),
        "geese": max(s["geese"] for s in snapshots),
        "wheat_held": max(s["wheat_held"] for s in snapshots),
        "fed_seen": any(s["fed_now"] for s in snapshots),
        "hands_seen": max(s["hands"] for s in snapshots),
        "ne_ever": any(s["ne_unlocked"] for s in snapshots),
        "money_min": min(s["money"] for s in snapshots),
    }

    # --- decision -> execution proof points ---------------------------------
    assert ever["melons"] >= 1, "planting queue never materialized a plant"
    assert ever["coops"] >= 1, "animal expansion never built a coop"
    assert ever["wheat_held"] >= 1, "feed-staging PICKUP never provisioned wheat"
    assert ever["fed_seen"] or ever["geese"] >= 1, \
        "goose chain (build/place/feed) made no progress"
    assert ever["hands_seen"] >= 1, "HIRE order produced no hand"
    assert ever["ne_ever"], "BUY_LAND order did not unlock NE"

    # money sanity: never negative, and land purchase consumed capital
    assert ever["money_min"] >= 0
    if final["ne_unlocked"]:
        assert final["money"] <= 3000 - 1000 - 480 + 1   # rough ledger check

    # day-cell semantics spot-check via W1 (independent of this walk)
    assert fc.expected_price("MELON", 29) > 250          # scarcity drift up
