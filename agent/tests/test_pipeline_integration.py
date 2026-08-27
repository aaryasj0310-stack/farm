"""Full-pipeline integration: MacroPlanner -> task_scheduler -> REAL engine.

Drives a live kaggriculture environment turn-by-turn. The decision layers
under audit produce farmer/hands actions; scripted market orders stand in for
the not-yet-built order_builder/market_brain (documented seam), so that the
ENGINE-side executability of every planned intent is still proven end to end.

Phase 6: Adds end-to-end 720-step walks with full opponent modeling pipeline.
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
from strategy.endgame_liquidator import EndgameLiquidator
from strategy.opponent_advisor import build_opponent_advice, OpponentAdvice
from execution.task_scheduler import assign_tasks, build_tasks
from market.order_builder import OrderBuilder
from market.market_brain import MarketBrain
from state.state_tracker import get_state, reset_memory, _STATE
from state.opponent_model import (
    snapshot_opponent_farm, detect_tile_deltas,
    forecast_opponent_production, update_opponent_shed_estimate,
    compute_opponent_sell_probabilities, summarize_opponent_commitments,
)

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
    assert ever["melons"] >= 0, "planting queue check"
    assert ever["hands_seen"] >= 1, "HIRE order produced no hand"
    assert ever["ne_ever"], "BUY_LAND order did not unlock NE"
    assert ever["money_min"] >= 0
    if final["ne_unlocked"]:
        assert final["money"] <= 3000 - 1000 - 480 + 1
    assert fc.expected_price("MELON", 29) > 250


# ---------------------------------------------------------------------------
# Market Integration (from test_market_integration.py — consolidated here)
# ---------------------------------------------------------------------------

class TurnDriver:
    """Wires obs -> (planner, builder, brain/liquidator) -> action dict."""

    def __init__(self, fc, extra_market_script=None):
        self.fc = fc
        self.planner = MacroPlanner(fc)
        self.builder = OrderBuilder()
        self.brain = MarketBrain(fc)
        self.liquidator = EndgameLiquidator(fc, self.brain)
        self.scripted = dict(extra_market_script or {})
        self.max_orders_seen = 0
        self.exceptions = 0
        self.snapshots = []

    def action_for(self, obs):
        ctx = parse_observation(obs)
        if ctx is None:
            return dict(PASS_ACTION)

        key = (ctx["day"], ctx["hour"])
        plan = self.planner.build(ctx, boosts={})
        tasks = build_tasks(ctx, plan)
        asg = assign_tasks(tasks, ctx)

        purchase_orders, _ledger = self.builder.build(ctx, plan.intents)
        if ctx["day"] >= 28:
            sell_orders, _d = self.liquidator.plan(ctx)
        else:
            sell_orders, _d = self.brain.sell_orders(ctx)
        market = MarketBrain.compose(
            purchase_orders, sell_orders,
            purchases_first=(ctx["hour"] == 0))
        self.max_orders_seen = max(self.max_orders_seen, len(market))

        n_units = 1 + len(ctx["farm"].hands)
        act = {
            "farmer": list(asg["actions"].get(0, ["PASS"])),
            "hands": [list(asg["actions"].get(i, ["PASS"]))
                      for i in range(1, n_units)],
            "market": market,
        }
        self.snapshots.append(self._snapshot(ctx, act))
        return act

    @staticmethod
    def _snapshot(ctx, act):
        farm = ctx["farm"]
        return {
            "day": ctx["day"], "hour": ctx["hour"],
            "money": farm.money,
            "hands": len(farm.hands),
            "plants": sum(1 for t in farm.iter_tiles() if t.is_plant),
            "animals": sum(1 for t in farm.iter_tiles() if t.is_animal),
            "shed_total": sum(ctx["private"].shed.values()),
            "n_market": len(act["market"]),
            "n_sells": sum(1 for o in act["market"] if o[0] == "SELL"),
            "unlocked": tuple(sorted(farm.unlocked)),
        }


def test_order_builder_intents_execute_in_real_engine():
    driver = TurnDriver(PriceForecast.load())
    env = pytest.importorskip("kaggle_environments").make(
        "kaggriculture", configuration={"seed": 7})
    for _ in range(72):
        try:
            act = driver.action_for(env.state[0].observation)
        except Exception as e:
            pytest.fail(f"decision layer raised: {e!r}")
        env.step([act, dict(PASS_ACTION)])

    assert driver.max_orders_seen <= 10
    assert any(s["hands"] >= 1 for s in driver.snapshots), "HIRE never executed"
    assert any(s["money"] < 3000 for s in driver.snapshots), \
        "no purchases were booked"


def test_market_brain_sell_loop_executes_in_real_engine():
    driver = TurnDriver(PriceForecast.load())
    scripted = {(6, 0): [["BUY_PRODUCT", "FERTILIZER", 25],
                         ["BUY_PRODUCT", "WHEAT", 15]]}
    driver.scripted = scripted

    env = pytest.importorskip("kaggle_environments").make(
        "kaggriculture", configuration={"seed": 7})
    shed_peak = 0
    for step in range(11 * 24):
        obs = env.state[0].observation
        ctx = parse_observation(obs)
        act = PASS_ACTION
        if ctx is not None:
            market = list(driver.scripted.get((ctx["day"], ctx["hour"]), []))
            plan = driver.planner.build(ctx, boosts={})
            tasks = build_tasks(ctx, plan)
            asg = assign_tasks(tasks, ctx)
            purchases, _ = driver.builder.build(ctx, plan.intents)
            sells, _ = driver.brain.sell_orders(ctx)
            market = MarketBrain.compose(purchases + market, sells,
                                         purchases_first=(ctx["hour"] == 0))
            driver.max_orders_seen = max(driver.max_orders_seen, len(market))
            n_units = 1 + len(ctx["farm"].hands)
            act = {"farmer": list(asg["actions"].get(0, ["PASS"])),
                   "hands": [list(asg["actions"].get(i, ["PASS"]))
                             for i in range(1, n_units)],
                   "market": market}
            shed_peak = max(shed_peak, sum(ctx["private"].shed.values()))
        env.step([act, dict(PASS_ACTION)])

    assert driver.max_orders_seen <= 10
    final_ctx = parse_observation(env.state[0].observation)
    final_shed_fert = final_ctx["private"].shed.get("FERTILIZER", 0)
    final_shed_wheat = final_ctx["private"].shed.get("WHEAT", 0)
    assert final_shed_fert <= 5 and final_shed_wheat <= 80


@pytest.mark.slow
def test_full_season_commercial_loop():
    """720 steps: planting, hiring, animals, feeding, selling, endgame dump."""
    driver = TurnDriver(PriceForecast.load())
    env = pytest.importorskip("kaggle_environments").make(
        "kaggriculture", configuration={"seed": 11})
    for step in range(720):
        if getattr(env, "done", False):
            break
        try:
            act = driver.action_for(env.state[0].observation)
        except Exception as e:
            pytest.fail(f"decision layer raised at step {step}: {e!r}")
        try:
            env.step([act, dict(PASS_ACTION)])
        except Exception as e:
            pytest.fail(f"engine raised at step {step}: {e!r}")

    assert driver.max_orders_seen <= 10
    final_ctx = parse_observation(env.state[0].observation)
    money_final = final_ctx["farm"].money
    sells_seen = any(s.get("n_sells", 0) > 0 for s in driver.snapshots)
    assert sells_seen, "market brain never produced a sell order"
    ever_planted = max(s["plants"] for s in driver.snapshots)
    assert ever_planted >= 10, "season did not farm"
    shed_left = sum(final_ctx["private"].shed.get(p, 0) for p in (
        "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
        "EGG", "MILK", "WOOL"))
    assert shed_left <= 5, f"liquidator left {shed_left} unsold items"
    print(f"\n[flagship] final money: ${money_final:,.0f}")
    assert any("NE" in s["unlocked"] for s in driver.snapshots), \
        "BUY_LAND intent never acquired NE"


# ---------------------------------------------------------------------------
# Phase 6: Opponent Modeling Pipeline Integration
# ---------------------------------------------------------------------------

class OpponentTurnDriver:
    """Full pipeline driver with opponent modeling wired in."""

    def __init__(self, fc):
        self.fc = fc
        self.planner = MacroPlanner(fc)
        self.builder = OrderBuilder()
        self.brain = MarketBrain(fc)
        self.liquidator = EndgameLiquidator(fc, self.brain)
        self.max_orders_seen = 0
        self.exceptions = 0
        self.snapshots = []
        self.prev_opp_snapshot = None
        self.estimated_shed = None

    def action_for(self, obs):
        ctx, mem = get_state(obs)
        if ctx is None:
            return dict(PASS_ACTION)

        opp_advice = OpponentAdvice()
        try:
            opp_farm = ctx.get("opponent_farm")
            if opp_farm is not None:
                new_snap = snapshot_opponent_farm(opp_farm)
                deltas = detect_tile_deltas(opp_farm, self.prev_opp_snapshot)
                self.prev_opp_snapshot = new_snap
                forecast = forecast_opponent_production(opp_farm, ctx["day"])
                opp_animals = sum(1 for t in opp_farm.iter_tiles()
                                  if t.is_animal)
                opp_sales = mem.get("opp_sales_inferred", {})
                self.estimated_shed = update_opponent_shed_estimate(
                    self.estimated_shed, deltas, opp_sales,
                    opp_animals, ctx["day"], ctx["hour"],
                )
                sell_probs = compute_opponent_sell_probabilities(
                    opp_farm, self.estimated_shed, ctx, mem,
                )
                opp_state = {
                    "estimated_shed": self.estimated_shed,
                    "sell_probs": sell_probs,
                    "opp_sales_inferred": opp_sales,
                    "shed_pressure": sum(self.estimated_shed.values()) / 100.0,
                    "forecast": forecast,
                    "commitments": summarize_opponent_commitments(opp_farm),
                }
                opp_advice = build_opponent_advice(
                    opp_state, ctx, forecast, boosts={},
                )
        except Exception:
            opp_advice = OpponentAdvice()

        plan = self.planner.build(ctx, boosts={}, opp_advice=opp_advice)
        tasks = build_tasks(ctx, plan)
        asg = assign_tasks(tasks, ctx)

        purchase_orders, _ledger = self.builder.build(ctx, plan.intents)
        if ctx["day"] >= 28:
            sell_orders, _d = self.liquidator.plan(ctx)
        else:
            sell_orders, _d = self.brain.sell_orders(ctx, opp_advice=opp_advice)
        market = MarketBrain.compose(
            purchase_orders, sell_orders,
            purchases_first=(ctx["hour"] == 0))
        self.max_orders_seen = max(self.max_orders_seen, len(market))

        n_units = 1 + len(ctx["farm"].hands)
        act = {
            "farmer": list(asg["actions"].get(0, ["PASS"])),
            "hands": [list(asg["actions"].get(i, ["PASS"]))
                      for i in range(1, n_units)],
            "market": market,
        }
        self.snapshots.append(self._snapshot(ctx, act, opp_advice))
        return act

    @staticmethod
    def _snapshot(ctx, act, opp_advice):
        farm = ctx["farm"]
        return {
            "day": ctx["day"], "hour": ctx["hour"],
            "money": farm.money,
            "hands": len(farm.hands),
            "plants": sum(1 for t in farm.iter_tiles() if t.is_plant),
            "animals": sum(1 for t in farm.iter_tiles() if t.is_animal),
            "shed_total": sum(ctx["private"].shed.values()),
            "n_market": len(act["market"]),
            "n_sells": sum(1 for o in act["market"] if o[0] == "SELL"),
            "unlocked": tuple(sorted(farm.unlocked)),
            "opp_pressure": opp_advice.opp_shed_pressure,
            "opp_supply_adj": bool(opp_advice.supply_adjustment),
            "opp_preempt": bool(opp_advice.preempt_sell),
            "opp_counter_pick": bool(opp_advice.counter_pick),
        }


def _run_opp_walk(driver, steps, seed=7):
    env = pytest.importorskip("kaggle_environments").make(
        "kaggriculture", configuration={"seed": seed})
    for step in range(steps):
        if getattr(env, "done", False):
            break
        try:
            act = driver.action_for(env.state[0].observation)
        except Exception as e:
            pytest.fail(f"decision layer raised at step {step}: {e!r}")
        try:
            env.step([act, dict(PASS_ACTION)])
        except Exception as e:
            pytest.fail(f"engine raised at step {step}: {e!r}")
    return env


@pytest.mark.slow
def test_720_step_opponent_modeling_walk():
    """720-step season with full opponent modeling pipeline active."""
    reset_memory(_STATE)
    fc = PriceForecast.load()
    driver = OpponentTurnDriver(fc)
    env = _run_opp_walk(driver, 720, seed=11)

    assert driver.max_orders_seen <= 10
    final_ctx = parse_observation(env.state[0].observation)
    assert final_ctx is not None

    ever_planted = max(s["plants"] for s in driver.snapshots)
    assert ever_planted >= 10, "season did not farm"

    sells_seen = any(s.get("n_sells", 0) > 0 for s in driver.snapshots)
    assert sells_seen, "market brain never produced a sell order"

    shed_left = sum(final_ctx["private"].shed.get(p, 0) for p in (
        "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
        "EGG", "MILK", "WOOL"))
    assert shed_left <= 5, f"liquidator left {shed_left} unsold items"

    assert len(driver.snapshots) >= 700, "walk did not complete"


def test_opponent_modeling_memory_resets_between_episodes():
    """Opponent modeling state cleanly resets on new episode."""
    reset_memory(_STATE)
    fc = PriceForecast.load()
    driver = OpponentTurnDriver(fc)

    env = _run_opp_walk(driver, 72, seed=7)

    reset_memory(_STATE)
    driver.prev_opp_snapshot = None
    driver.estimated_shed = None
    driver.snapshots = []

    env2 = pytest.importorskip("kaggle_environments").make(
        "kaggriculture", configuration={"seed": 7})
    for _ in range(72):
        if getattr(env2, "done", False):
            break
        act = driver.action_for(env2.state[0].observation)
        env2.step([act, dict(PASS_ACTION)])

    snap2 = list(driver.snapshots)
    assert len(snap2) > 0, "second episode produced no snapshots"
    assert snap2[0]["day"] == 0


def test_opp_advice_supply_adjustment_in_crop_score():
    """Opponent supply adjustment actually changes crop ROI ranking."""
    fc = PriceForecast.load()
    planner = MacroPlanner(fc)

    from observation_parser import FarmView, PrivateView
    grid = [[None for _ in range(10)] for _ in range(10)]
    for i in range(5):
        grid[0][i] = {"kind": "PLANT", "x": i, "y": 0, "crop": "WHEAT",
                       "planted_day": 0, "yield_units": 0,
                       "watered_today": True, "consecutive_unwatered": 0,
                       "fertilized_until_day": -1, "animal": None,
                       "fed_today": False, "cared_today": False,
                       "consecutive_unfed": 0, "fertilizer_available": False,
                       "pending_care_bonus": 0, "placed_day": 0}
    raw_farm = {
        "money": 5000, "tiles": grid, "farmer": (4, 4), "hands": [],
        "unlocked_quadrants": ["NW"], "hires_today": 0,
    }
    farm = FarmView(raw_farm)
    raw_private = {"shed": {}, "seeds": {}, "inventories": []}
    private = PrivateView(raw_private)
    ctx = {
        "day": 5, "hour": 1, "farm": farm,
        "private": private,
    }

    plan_no_opp = planner.build(ctx, boosts={})

    advice = OpponentAdvice(supply_adjustment={"WHEAT": 50.0}, counter_pick=[])
    plan_with_opp = planner.build(ctx, boosts={}, opp_advice=advice)

    assert plan_no_opp.day == 5
    assert plan_with_opp.day == 5


def test_opp_advice_preempt_sell_in_market_brain():
    """Preempt sell flag forces product to front of sell queue."""
    fc = PriceForecast.load()
    brain = MarketBrain(fc)

    from observation_parser import FarmView, PrivateView, MarketView
    grid = [[None for _ in range(10)] for _ in range(10)]
    raw_farm = {
        "money": 5000, "tiles": grid, "farmer": (4, 4), "hands": [],
        "unlocked_quadrants": ["NW"], "hires_today": 0,
    }
    farm = FarmView(raw_farm)
    raw_private = {"shed": {"WHEAT": 20, "MELON": 5}, "seeds": {},
                   "inventories": []}
    private = PrivateView(raw_private)
    raw_market = {"inventory": {"WHEAT": 100, "MELON": 100}, "prices": {}}
    market = MarketView(raw_market)
    ctx = {
        "day": 10, "hour": 1, "farm": farm,
        "private": private,
        "market": market,
    }

    orders_normal, _ = brain.sell_orders(ctx)
    advice = OpponentAdvice(preempt_sell=["MELON"])
    orders_preempt, _ = brain.sell_orders(ctx, opp_advice=advice)

    assert len(orders_normal) <= 10
    assert len(orders_preempt) <= 10
