"""
Kaggriculture Master Agent — Closed-Loop Adaptive Architecture

Architecture Chain:
  obs -> parse_observation -> PriceForecast (W1) -> MacroPlanner (W2)
      -> TaskScheduler (unit actions)
      + OrderBuilder (purchase orders) + MarketBrain (sell orders) + EndgameLiquidator
      -> Action Dict {"farmer": ..., "hands": ..., "market": ...}

  Phase 6: Opponent Modeling pipeline
      obs -> get_state() -> OpponentModel -> OpponentAdvisor -> MacroPlanner + MarketBrain

Submission Rule Compliance:
  - The last 'def' in this file is the agent entry point: def agent(obs, config=None)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

# Safe path injection for Kaggle execution environment (where __file__ is undefined)
_CWD = os.getcwd()
_DIR_CANDIDATES = [
    "/kaggle_simulations/agent",
    os.path.join(_CWD, "agent"),
    os.path.join(_CWD, "submission"),
    _CWD,
    os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None,
]

for _base in _DIR_CANDIDATES:
    if _base and os.path.exists(_base):
        if _base not in sys.path:
            sys.path.insert(0, _base)
        for _sub in ("state", "strategy", "execution", "market"):
            _sub_path = os.path.join(_base, _sub)
            if os.path.exists(_sub_path) and _sub_path not in sys.path:
                sys.path.insert(0, _sub_path)

try:
    from observation_parser import parse_observation
except ImportError:
    from state.observation_parser import parse_observation

try:
    from config import QUADRANT_HARD_BLOCK
    from strategy.price_forecast import PriceForecast
    from strategy.macro_planner import MacroPlanner
    from strategy.endgame_liquidator import EndgameLiquidator
    from strategy.shop_adapter import demand_boosts
    from strategy.opponent_advisor import build_opponent_advice, OpponentAdvice
    from execution.task_scheduler import assign_tasks, build_tasks, get_daily_log, reset_daily_log
    from market.order_builder import OrderBuilder
    from market.market_brain import MarketBrain
    from state.state_tracker import get_state, record_our_sale
    from state.opponent_model import (
        snapshot_opponent_farm, detect_tile_deltas, infer_turn_transactions,
        forecast_opponent_production, get_imminent_harvests,
        summarize_opponent_commitments, update_opponent_shed_estimate,
        compute_opponent_sell_probabilities,
    )
except ImportError:
    from config import QUADRANT_HARD_BLOCK
    from price_forecast import PriceForecast
    from macro_planner import MacroPlanner
    from endgame_liquidator import EndgameLiquidator
    from shop_adapter import demand_boosts
    from opponent_advisor import build_opponent_advice, OpponentAdvice
    from task_scheduler import assign_tasks, build_tasks, get_daily_log, reset_daily_log
    from order_builder import OrderBuilder
    from market_brain import MarketBrain
    from state_tracker import get_state, record_our_sale
    from opponent_model import (
        snapshot_opponent_farm, detect_tile_deltas, infer_turn_transactions,
        forecast_opponent_production, get_imminent_harvests,
        summarize_opponent_commitments, update_opponent_shed_estimate,
        compute_opponent_sell_probabilities,
    )

PASS_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}

# Singleton / lazy-loaded instances
_FC = None
_PLANNER = None
_BUILDER = None
_BRAIN = None
_LIQUIDATOR = None

# Persistent opponent modeling state (survives across turns within one process)
_prev_opp_snapshot = None
_estimated_shed = None


def _get_components():
    global _FC, _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR
    if _FC is None:
        _FC = PriceForecast.load()
        _PLANNER = MacroPlanner(_FC)
        _BUILDER = OrderBuilder()
        _BRAIN = MarketBrain(_FC)
        _LIQUIDATOR = EndgameLiquidator(_FC, _BRAIN)
    return _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR


def _build_opp_advice(ctx, mem):
    """Build OpponentAdvice from current observation and persistent memory.

    Returns OpponentAdvice (always safe — empty advice on any missing data).
    """
    try:
        opp_farm = ctx.get("opponent_farm")
        if opp_farm is None:
            return OpponentAdvice()

        # Phase 1: snapshot and detect deltas
        global _prev_opp_snapshot, _estimated_shed
        new_snap = snapshot_opponent_farm(opp_farm)
        deltas = detect_tile_deltas(opp_farm, _prev_opp_snapshot)
        _prev_opp_snapshot = new_snap

        # Phase 2: forecast production
        forecast = forecast_opponent_production(opp_farm, ctx["day"])

        # Phase 3: update shed estimate
        opp_animals = sum(1 for t in opp_farm.iter_tiles() if t.is_animal)
        opp_sales = mem.get("opp_sales_inferred", {})
        _estimated_shed = update_opponent_shed_estimate(
            _estimated_shed, deltas, opp_sales,
            opp_animals, ctx["day"], ctx["hour"],
        )

        # Phase 3: sell probabilities
        opp_state_for_probs = {
            "estimated_shed": _estimated_shed,
            "sell_probs": {},
            "opp_sales_inferred": opp_sales,
            "shed_pressure": sum(_estimated_shed.values()) / 100.0,
            "forecast": forecast,
            "commitments": summarize_opponent_commitments(opp_farm),
            "animal_counts": {t.animal: 1 for t in opp_farm.iter_tiles()
                              if t.is_animal},
        }
        sell_probs = compute_opponent_sell_probabilities(
            opp_farm, _estimated_shed, ctx, mem,
        )
        opp_state_for_probs["sell_probs"] = sell_probs

        # Phase 5: build advice
        town_obj = ctx.get("town")
        unlocked_shops = getattr(town_obj, "unlocked_shops", None)
        if unlocked_shops is None and isinstance(town_obj, dict):
            unlocked_shops = town_obj.get("unlocked_shops", [])
        boosts = demand_boosts(unlocked_shops or [])
        advice = build_opponent_advice(
            opp_state_for_probs, ctx, forecast, boosts=boosts,
        )
        return advice
    except Exception:
        # Never let opponent modeling crash the main agent
        return OpponentAdvice()


def _agent_decision(obs: Dict[str, Any]) -> Dict[str, Any]:
    # Phase 6: use get_state for persistent memory + episode detection
    ctx, mem = get_state(obs)
    if ctx is None:
        return dict(PASS_ACTION)

    planner, builder, brain, liquidator = _get_components()

    # v5.9: Reset daily log at start of day 0
    if ctx["day"] == 0 and ctx["hour"] == 0:
        reset_daily_log()

    # Dynamic shop boosts from observed town unlocks
    known_shops = obs.get("town", {}).get("unlocked_shops", [])
    boosts = demand_boosts(known_shops)

    # Phase 6: build opponent advice
    opp_advice = _build_opp_advice(ctx, mem)

    # 1. Macro strategic planning (with opponent supply/counter-pick)
    plan = planner.build(ctx, boosts=boosts, opp_advice=opp_advice)

    # v5.9: Hard guard — NEVER allow quadrant 4 purchase
    if plan.intents.get("buy_land"):
        n_extra = len(ctx["farm"].unlocked) - 1
        next_q = n_extra + 2
        if next_q in QUADRANT_HARD_BLOCK:
            plan.intents["buy_land"] = False  # force block

    # 2. Execution layer: unit tasks and greedy spatial assignment
    tasks = build_tasks(ctx, plan)
    asg = assign_tasks(tasks, ctx)

    # 3. Market layer: purchase intent compilation (morning market at hour 0 + deferred hires at hour 1)
    purchase_orders = []
    if ctx["hour"] == 0:
        purchase_orders, _ledger = builder.build(ctx, plan.intents)
    elif ctx["hour"] == 1:
        # Check if any target hires from today's plan were deferred from Hour 0
        target_h = get_target_hands(ctx["day"])
        hires_so_far = ctx["farm"].hires_today
        hires_needed = max(0, target_h - hires_so_far)
        if hires_needed > 0:
            for _ in range(min(hires_needed, 10)):
                purchase_orders.append(["HIRE"])
        
    if ctx["day"] >= 28:
        sell_orders, _d = liquidator.plan(ctx, opp_advice=opp_advice)
    else:
        sell_orders, _d = brain.sell_orders(ctx, opp_advice=opp_advice)

    market = MarketBrain.compose(
        purchase_orders, sell_orders,
        purchases_first=(ctx["hour"] in (0, 1))
    )

    # Phase 6: record our sales for drain ledger accuracy
    for order in market:
        if order[0] == "SELL":
            record_our_sale(order[1], order[2])

    # 4. Action dict assembly
    n_units = 1 + len(ctx["farm"].hands)
    return {
        "farmer": list(asg["actions"].get(0, ["PASS"])),
        "hands": [list(asg["actions"].get(i, ["PASS"])) for i in range(1, n_units)],
        "market": market,
    }


# ==============================================================================
# KAGGLE ENTRY POINT (LAST 'def')
# ==============================================================================
def agent(obs: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Official competition entry point with top-level fail-safe."""
    try:
        return _agent_decision(obs)
    except Exception:
        return dict(PASS_ACTION)
