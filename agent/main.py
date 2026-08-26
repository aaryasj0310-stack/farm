"""
🌾 Kaggriculture Master Agent — Closed-Loop Adaptive Architecture

Architecture Chain:
  obs -> parse_observation -> PriceForecast (W1) -> MacroPlanner (W2)
      -> TaskScheduler (unit actions)
      + OrderBuilder (purchase orders) + MarketBrain (sell orders) + EndgameLiquidator
      -> Action Dict {"farmer": ..., "hands": ..., "market": ...}

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
    os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None,
    os.path.join(_CWD, "agent"),
    os.path.join(_CWD, "submission"),
    _CWD,
]
_PKG_DIR = next((p for p in _DIR_CANDIDATES if p and os.path.exists(os.path.join(p, "config.py"))), _CWD)

if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)
for _sub in ("state", "strategy", "execution", "market"):
    _sub_path = os.path.join(_PKG_DIR, _sub)
    if os.path.exists(_sub_path) and _sub_path not in sys.path:
        sys.path.insert(0, _sub_path)

from observation_parser import parse_observation
from strategy.price_forecast import PriceForecast
from strategy.macro_planner import MacroPlanner
from strategy.endgame_liquidator import EndgameLiquidator
from strategy.shop_adapter import demand_boosts
from execution.task_scheduler import assign_tasks, build_tasks
from market.order_builder import OrderBuilder
from market.market_brain import MarketBrain

PASS_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}

# Singleton / lazy-loaded instances
_FC = None
_PLANNER = None
_BUILDER = None
_BRAIN = None
_LIQUIDATOR = None


def _get_components():
    global _FC, _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR
    if _FC is None:
        _FC = PriceForecast.load()
        _PLANNER = MacroPlanner(_FC)
        _BUILDER = OrderBuilder()
        _BRAIN = MarketBrain(_FC)
        _LIQUIDATOR = EndgameLiquidator(_FC, _BRAIN)
    return _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR


def _agent_decision(obs: Dict[str, Any]) -> Dict[str, Any]:
    ctx = parse_observation(obs)
    if ctx is None:
        return dict(PASS_ACTION)

    planner, builder, brain, liquidator = _get_components()

    # Dynamic shop boosts from observed town unlocks
    known_shops = obs.get("town", {}).get("unlocked_shops", [])
    boosts = demand_boosts(known_shops)

    # 1. Macro strategic planning
    plan = planner.build(ctx, boosts=boosts)

    # 2. Execution layer: unit tasks and greedy spatial assignment
    tasks = build_tasks(ctx, plan)
    asg = assign_tasks(tasks, ctx)

    # 3. Market layer: purchase intent compilation and dynamic sell/liquidate orders
    purchase_orders, _ledger = builder.build(ctx, plan.intents)
    if ctx["day"] >= 28:
        sell_orders, _d = liquidator.plan(ctx)
    else:
        sell_orders, _d = brain.sell_orders(ctx)

    market = MarketBrain.compose(
        purchase_orders, sell_orders,
        purchases_first=(ctx["hour"] == 0)
    )

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
    """Official competition entry point."""
    return _agent_decision(obs)
