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
import copy
from typing import Any, Dict, Optional
from collections import Counter

# Safe path injection for Kaggle execution environment (where __file__ is undefined)
_CWD = os.getcwd()
_OWN_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
_DIR_CANDIDATES = [
    _OWN_DIR,
    os.path.join(_CWD, "agent"),
    "/kaggle_simulations/agent",
    _CWD,
]

for _base in reversed(_DIR_CANDIDATES):
    if _base and os.path.exists(_base):
        if _base in sys.path:
            sys.path.remove(_base)
        sys.path.insert(0, _base)
        for _sub in reversed(("state", "strategy", "execution", "market")):
            _sub_path = os.path.join(_base, _sub)
            if os.path.exists(_sub_path):
                if _sub_path in sys.path:
                    sys.path.remove(_sub_path)
                sys.path.insert(0, _sub_path)

try:
    from observation_parser import parse_observation
except ImportError:
    from state.observation_parser import parse_observation

try:
    from config import (
        QUADRANT_HARD_BLOCK, get_target_hands,
        set_opponent_intelligence_mode, get_opponent_intelligence_mode,
    )
    from strategy.price_forecast import PriceForecast
    from strategy.macro_planner import MacroPlanner
    from strategy.endgame_liquidator import EndgameLiquidator
    from strategy.shop_adapter import demand_boosts
    from strategy.opponent_advisor import build_opponent_advice, OpponentAdvice
    from strategy.central_planner import CentralPlanner, legacy_compose_market
    from execution.task_scheduler import (
        assign_tasks, build_tasks, get_daily_log, reset_daily_log,
        get_sw_tile_breakdown, get_sw_season_summary,
    )
    from execution.pathfinding import bfs_first_step
    from market.order_builder import OrderBuilder
    from market.market_brain import MarketBrain
    from state.state_tracker import get_state, record_our_sale, record_our_buy
    from state.opponent_model import (
        snapshot_opponent_farm, detect_tile_deltas, infer_turn_transactions,
        forecast_opponent_production, get_imminent_harvests,
        summarize_opponent_commitments, update_opponent_shed_estimate,
        compute_opponent_sell_probabilities,
    )
except ImportError:
    from config import (
        QUADRANT_HARD_BLOCK, get_target_hands,
        set_opponent_intelligence_mode, get_opponent_intelligence_mode,
    )
    from price_forecast import PriceForecast
    from macro_planner import MacroPlanner
    from endgame_liquidator import EndgameLiquidator
    from shop_adapter import demand_boosts
    from opponent_advisor import build_opponent_advice, OpponentAdvice
    from central_planner import CentralPlanner, legacy_compose_market
    from task_scheduler import (
        assign_tasks, build_tasks, get_daily_log, reset_daily_log,
        get_sw_tile_breakdown, get_sw_season_summary,
    )
    from pathfinding import bfs_first_step
    from order_builder import OrderBuilder
    from market_brain import MarketBrain
    from state_tracker import get_state, record_our_sale, record_our_buy
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
_CENTRAL_PLANNER = None

# Persistent opponent modeling state (survives across turns within one process)
_prev_opp_snapshot = None
_estimated_shed = None
_OPPONENT_MODEL_DIAGNOSTICS = {
    "failure_count": 0,
    "last_exception_type": None,
    "last_exception_message": None,
    "last_failure_step": None,
    "is_degraded": False,
}


def get_opponent_model_diagnostics():
    """Return a copy of the opponent-model diagnostics."""
    return dict(_OPPONENT_MODEL_DIAGNOSTICS)


def reset_opponent_model_state():
    """Reset module-level opponent-model state across episodes."""
    global _prev_opp_snapshot, _estimated_shed, _OPPONENT_MODEL_DIAGNOSTICS
    _prev_opp_snapshot = None
    _estimated_shed = None
    _OPPONENT_MODEL_DIAGNOSTICS = {
        "failure_count": 0,
        "last_exception_type": None,
        "last_exception_message": None,
        "last_failure_step": None,
        "is_degraded": False,
    }
    try:
        from strategy.shadow_forecast import reset_shadow_forecaster
        reset_shadow_forecaster()
    except Exception:
        pass


def reset_agent_state():
    """Reset module-level singletons and persistent state between matches."""
    global _FC, _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR, _CENTRAL_PLANNER
    _FC = None
    _PLANNER = None
    _BUILDER = None
    _BRAIN = None
    _LIQUIDATOR = None
    _CENTRAL_PLANNER = None
    reset_opponent_model_state()


try:
    from config import ARBITRATION_MODE as _CONFIG_ARBITRATION_MODE
except Exception:
    _CONFIG_ARBITRATION_MODE = "historical_candidates_central"

_RUNTIME_ARBITRATION_MODE: str = str(_CONFIG_ARBITRATION_MODE).strip().lower()


def set_arbitration_mode(mode: str) -> None:
    """Set arbitration mode. Intended for benchmarks/tests."""
    global _RUNTIME_ARBITRATION_MODE
    mode_str = str(mode).strip().lower()
    valid_modes = (
        "central",
        "legacy",
        "historical_stack",
        "historical_candidates_central",
        "expanded_central",
        "expanded_legacy",
    )
    if mode_str not in valid_modes:
        raise ValueError(f"Invalid arbitration mode '{mode}'. Must be one of {valid_modes}.")
    _RUNTIME_ARBITRATION_MODE = mode_str


def get_arbitration_mode() -> str:
    """Return the currently active arbitration mode ('central' or 'legacy')."""
    return _RUNTIME_ARBITRATION_MODE


_LAST_CENTRAL_PLANNER_DIAGNOSTIC = None
_LAST_TURN_TELEMETRY: Optional[Dict[str, Any]] = None


def get_central_planner_diagnostics() -> Dict[str, Any]:
    """Return an immutable deep copy of the latest Central Planner diagnostics."""
    if _LAST_CENTRAL_PLANNER_DIAGNOSTIC is None:
        return {}
    return copy.deepcopy(_LAST_CENTRAL_PLANNER_DIAGNOSTIC)


def get_last_turn_telemetry() -> Optional[Dict[str, Any]]:
    """Return an immutable deep copy of the most recent turn's telemetry."""
    if _LAST_TURN_TELEMETRY is None:
        return None
    return copy.deepcopy(_LAST_TURN_TELEMETRY)


def reset_agent_state() -> None:
    """Hard-reset all module singletons and persistent state across episodes."""
    global _FC, _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR, _CENTRAL_PLANNER
    global _LAST_CENTRAL_PLANNER_DIAGNOSTIC, _LAST_TURN_TELEMETRY, _LAST_FALLBACK_DIAGNOSTIC
    _FC = None
    _PLANNER = None
    _BUILDER = None
    _BRAIN = None
    _LIQUIDATOR = None
    _CENTRAL_PLANNER = None
    _LAST_CENTRAL_PLANNER_DIAGNOSTIC = None
    _LAST_TURN_TELEMETRY = None
    _LAST_FALLBACK_DIAGNOSTIC = None
    reset_opponent_model_state()
    try:
        from state.state_tracker import reset_memory
        reset_memory()
    except Exception:
        try:
            from state_tracker import reset_memory
            reset_memory()
        except Exception:
            pass
    try:
        reset_daily_log()
    except Exception:
        pass


try:
    from state.state_tracker import register_reset_hook as _rrh_pkg
    _rrh_pkg(reset_opponent_model_state)
except Exception:
    pass

try:
    from state_tracker import register_reset_hook as _rrh_flat
    _rrh_flat(reset_opponent_model_state)
except Exception:
    pass


def _get_components():
    global _FC, _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR, _CENTRAL_PLANNER
    if _FC is None:
        _FC = PriceForecast.load()
        _PLANNER = MacroPlanner(_FC)
        _BUILDER = OrderBuilder()
        _BRAIN = MarketBrain(_FC)
        _LIQUIDATOR = EndgameLiquidator(_FC, _BRAIN)
        _CENTRAL_PLANNER = CentralPlanner()
    return _PLANNER, _BUILDER, _BRAIN, _LIQUIDATOR, _CENTRAL_PLANNER


def _build_opp_advice(ctx, mem):
    """Build OpponentAdvice from current observation and persistent memory.

    Returns OpponentAdvice (always safe — empty advice on any missing data).
    """
    try:
        try:
            from config import OPPONENT_INTELLIGENCE_MODE
        except Exception:
            OPPONENT_INTELLIGENCE_MODE = "O1"

        # A0: Zero opponent advice (equivalent to O0)
        if OPPONENT_INTELLIGENCE_MODE in ("O0", "A0"):
            return OpponentAdvice()

        opp_farm = ctx.get("opponent_farm")
        if opp_farm is None:
            return OpponentAdvice()

        # Shadow Forecasting (telemetry only)
        try:
            from config import SHADOW_OPPONENT_FORECAST_ENABLED
            if SHADOW_OPPONENT_FORECAST_ENABLED or OPPONENT_INTELLIGENCE_MODE in ("O0_SHADOW", "O1_SHADOW", "A3", "A4"):
                from strategy.shadow_forecast import get_shadow_forecaster
                get_shadow_forecaster().update(opp_farm, ctx, mem)
        except Exception:
            pass

        # O0_SHADOW: exact O0 behavior for live strategy (empty advice), shadow telemetry ran above
        if OPPONENT_INTELLIGENCE_MODE == "O0_SHADOW":
            return OpponentAdvice()

        # A1: Directly observed commitments only (counter_pick from observed farm tiles/boosts)
        if OPPONENT_INTELLIGENCE_MODE == "A1":
            try:
                town_obj = ctx.get("town")
                unlocked_shops = getattr(town_obj, "unlocked_shops", None) or (town_obj.get("unlocked_shops", []) if isinstance(town_obj, dict) else [])
                boosts = demand_boosts(unlocked_shops or [])
                opp_products = set()
                for t in opp_farm.iter_tiles():
                    if t.is_plant:
                        opp_products.add(t.crop)
                    elif t.is_animal and t.animal in ANIMALS:
                        opp_products.add(ANIMALS[t.animal]["product"])
                counter_pick = [p for p in boosts if p not in opp_products and p in CROPS]
                return OpponentAdvice(counter_pick=counter_pick)
            except Exception:
                return OpponentAdvice()

        # A2: High-confidence recent inferred sales only (rolling 4-turn market sales -> delay_sell)
        if OPPONENT_INTELLIGENCE_MODE == "A2":
            try:
                from strategy.repaired_opponent_advisor import compute_delay_sell_repaired
                priv = ctx.get("private", {})
                our_shed = priv.shed if hasattr(priv, "shed") else (priv.get("shed", {}) if isinstance(priv, dict) else {})
                delayed = compute_delay_sell_repaired(mem, our_shed, ctx, max_steps=4)
                return OpponentAdvice(delay_sell=delayed)
            except Exception:
                return OpponentAdvice()

        # A3: Repaired forward production forecasts only (lifecycle schedules -> supply_adjustment)
        if OPPONENT_INTELLIGENCE_MODE == "A3":
            try:
                from strategy.shadow_forecast import get_shadow_forecaster
                forecaster = get_shadow_forecaster()
                if forecaster.last_step != ctx.get("step", 0):
                    forecaster.update(opp_farm, ctx, mem)
                day = ctx.get("day", 0)
                base_sched = forecaster.last_telemetry.get("production_forecast", {})
                supply_adj = {}
                from strategy.repaired_opponent_advisor import SUPPLY_PROJECTION_DAYS, SUPPLY_ADJUSTMENT_WEIGHT
                horizon = day + SUPPLY_PROJECTION_DAYS
                for prod, sched in base_sched.items():
                    tot = sum(units for d, units in sched.items() if day <= d <= horizon)
                    if tot > 0:
                        supply_adj[prod] = round(tot * SUPPLY_ADJUSTMENT_WEIGHT, 4)
                return OpponentAdvice(supply_adjustment=supply_adj)
            except Exception:
                return OpponentAdvice()

        # A4: High-confidence inventory bounds only (Milk, Wool, Egg bounds where coverage >= 90%)
        if OPPONENT_INTELLIGENCE_MODE == "A4":
            try:
                from strategy.shadow_forecast import get_shadow_forecaster
                forecaster = get_shadow_forecaster()
                if forecaster.last_step != ctx.get("step", 0):
                    forecaster.update(opp_farm, ctx, mem)
                shed_b = forecaster.last_telemetry.get("shed_bounds", {})
                hi_stock_sum = sum(shed_b[p][1] for p in ("MILK", "WOOL", "EGG") if p in shed_b)
                shed_pressure = hi_stock_sum / 50.0
                return OpponentAdvice(opp_shed_pressure=shed_pressure)
            except Exception:
                return OpponentAdvice()

        # If O1R mode active: generate repaired advice
        if OPPONENT_INTELLIGENCE_MODE == "O1R":
            try:
                from strategy.shadow_forecast import get_shadow_forecaster
                from strategy.repaired_opponent_advisor import build_repaired_opponent_advice
                forecaster = get_shadow_forecaster()
                if forecaster.last_step != ctx.get("step", 0):
                    forecaster.update(opp_farm, ctx, mem)

                town_obj = ctx.get("town")
                unlocked_shops = getattr(town_obj, "unlocked_shops", None)
                if unlocked_shops is None and isinstance(town_obj, dict):
                    unlocked_shops = town_obj.get("unlocked_shops", [])
                boosts = demand_boosts(unlocked_shops or [])

                rep_advice = build_repaired_opponent_advice(
                    opp_farm=opp_farm,
                    inventory_tracking=forecaster.last_telemetry,
                    repaired_forecast=forecaster.last_telemetry,
                    ctx=ctx,
                    mem=mem,
                    boosts=boosts,
                )
                return OpponentAdvice(
                    supply_adjustment=rep_advice.supply_adjustment,
                    preempt_sell=rep_advice.preempt_sell,
                    delay_sell=rep_advice.delay_sell,
                    counter_pick=rep_advice.counter_pick,
                    opp_shed_pressure=rep_advice.opp_shed_pressure,
                )
            except Exception:
                pass

        # Phase 1: snapshot and detect deltas
        global _prev_opp_snapshot, _estimated_shed
        new_snap = snapshot_opponent_farm(opp_farm)
        deltas = detect_tile_deltas(opp_farm, _prev_opp_snapshot)
        _prev_opp_snapshot = new_snap

        # Phase 2: forecast production
        forecast = forecast_opponent_production(opp_farm, ctx["day"])

        # Phase 3: update shed estimate
        opp_animals = sum(1 for t in opp_farm.iter_tiles() if t.is_animal)
        opp_sales_step = mem.get("opp_sales_step", {})
        opp_sales = mem.get("opp_sales_inferred", {})
        opp_market_inf = mem.get("opp_market_inference", {})
        _estimated_shed = update_opponent_shed_estimate(
            _estimated_shed, deltas, opp_sales_step,
            opp_animals, ctx["day"], ctx["hour"],
        )

        # Phase 3: sell probabilities
        opp_state_for_probs = {
            "estimated_shed": _estimated_shed,
            "sell_probs": {},
            "opp_sales_inferred": opp_sales,
            "opp_sales_step": opp_sales_step,
            "opp_market_inference": opp_market_inf,
            "shed_pressure": sum(_estimated_shed.values()) / 100.0,
            "forecast": forecast,
            "commitments": summarize_opponent_commitments(opp_farm),
            "animal_counts": dict(Counter(t.animal for t in opp_farm.iter_tiles()
                                          if t.is_animal)),
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
    except Exception as e:
        # Never let opponent modeling crash the main agent
        global _OPPONENT_MODEL_DIAGNOSTICS
        _OPPONENT_MODEL_DIAGNOSTICS["failure_count"] += 1
        _OPPONENT_MODEL_DIAGNOSTICS["last_exception_type"] = type(e).__name__
        _OPPONENT_MODEL_DIAGNOSTICS["last_exception_message"] = str(e)
        _OPPONENT_MODEL_DIAGNOSTICS["last_failure_step"] = ctx.get("step") if isinstance(ctx, dict) else getattr(ctx, "step", None)
        _OPPONENT_MODEL_DIAGNOSTICS["is_degraded"] = True
        return OpponentAdvice()


def _survival_fallback_from_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Survival-capable fallback task generator using parsed context.

    Priority:
      1. Feed animal in immediate survival danger if eligible unit already holds wheat
      2. Water crops that will die today (consecutive_unwatered >= 1 or survival)
      3. Harvest crops at immediate decay risk (turns_until_decay <= 1)
      4. Harvest animal output if safe (yield_units > 0)
      5. Otherwise PASS
    """
    farm = ctx["farm"]
    private = ctx.get("private")
    inventories = private.inventories if private is not None else []

    units = [(0, tuple(farm.farmer))]
    for i, h in enumerate(farm.hands):
        units.append((i + 1, tuple(h)))
    pos_by_idx = dict(units)

    wheat_counts = {
        u: (inventories[u].get("WHEAT", 0) if u < len(inventories) and isinstance(inventories[u], dict) else 0)
        for u, _ in units
    }

    free_units = set(pos_by_idx.keys())
    actions = {u: ["PASS"] for u in free_units}
    assignment = {}

    starving_animals = []
    dying_crops = []
    decaying_crops = []
    harvestable_animals = []

    for t in farm.iter_tiles():
        if t.is_animal:
            if getattr(t, "consecutive_unfed", 0) >= 1 and not getattr(t, "fed_today", False):
                starving_animals.append(t.pos)
            if getattr(t, "yield_units", 0) > 0:
                harvestable_animals.append(t.pos)
        elif getattr(t, "kind", None) == "PLANT":
            if getattr(t, "consecutive_unwatered", 0) >= 1 and not getattr(t, "watered_today", False):
                dying_crops.append(t.pos)
            if getattr(t, "yield_units", 0) > 0 and getattr(t, "turns_until_decay", 99) <= 1:
                decaying_crops.append(t.pos)

    # 1. feed animal in immediate survival danger if eligible unit already holds wheat
    for target in starving_animals:
        if not free_units:
            break
        eligible = [u for u in free_units if wheat_counts.get(u, 0) > 0]
        if not eligible:
            continue
        best_u = min(eligible, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        wheat_counts[best_u] -= 1
        assignment[best_u] = {"op": "FEED", "target": tuple(target), "kind": "feed_rescue"}
        if pos_by_idx[best_u] == tuple(target):
            actions[best_u] = ["FEED"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], tuple(target), 10)
            actions[best_u] = [step] if step else ["PASS"]

    # 2. water crops that will die today
    for target in dying_crops:
        if not free_units:
            break
        best_u = min(free_units, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        assignment[best_u] = {"op": "WATER", "target": tuple(target), "kind": "water_emergency"}
        if pos_by_idx[best_u] == tuple(target):
            actions[best_u] = ["WATER"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], tuple(target), 10)
            actions[best_u] = [step] if step else ["PASS"]

    # 3. harvest crops at immediate decay risk
    for target in decaying_crops:
        if not free_units:
            break
        best_u = min(free_units, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        assignment[best_u] = {"op": "HARVEST", "target": tuple(target), "kind": "harvest_decay"}
        if pos_by_idx[best_u] == tuple(target):
            actions[best_u] = ["HARVEST"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], tuple(target), 10)
            actions[best_u] = [step] if step else ["PASS"]

    # 4. harvest animal output if safe
    for target in harvestable_animals:
        if not free_units:
            break
        best_u = min(free_units, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        assignment[best_u] = {"op": "HARVEST", "target": tuple(target), "kind": "harvest_animal"}
        if pos_by_idx[best_u] == tuple(target):
            actions[best_u] = ["HARVEST"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], tuple(target), 10)
            actions[best_u] = [step] if step else ["PASS"]

    return {"actions": actions, "assignment": assignment}


def _survival_fallback_raw(obs: Dict[str, Any]) -> Dict[str, Any]:
    """Safe fallback operating directly on unparsed observation dictionary."""
    player_id = obs.get("player", 0) if isinstance(obs, dict) else 0
    farms = obs.get("farms", []) if isinstance(obs, dict) else []
    our_farm = (
        farms[player_id]
        if isinstance(farms, list) and len(farms) > player_id and isinstance(farms[player_id], dict)
        else {}
    )
    farmer = tuple(our_farm.get("farmer", [4, 4]))
    hands = [tuple(h) for h in our_farm.get("hands", [])]
    tiles = our_farm.get("tiles", [])

    private = obs.get("private", {}) if isinstance(obs, dict) else {}
    inventories = private.get("inventories", []) if isinstance(private, dict) else []

    units = [(0, farmer)] + [(i + 1, h) for i, h in enumerate(hands)]
    pos_by_idx = dict(units)
    wheat_counts = {
        u: (inventories[u].get("WHEAT", 0) if u < len(inventories) and isinstance(inventories[u], dict) else 0)
        for u, _ in units
    }

    free_units = set(pos_by_idx.keys())
    actions = {u: ["PASS"] for u in free_units}

    starving_animals = []
    dying_crops = []
    decaying_crops = []
    harvestable_animals = []

    if isinstance(tiles, list):
        for y, row in enumerate(tiles):
            if not isinstance(row, list):
                continue
            for x, tile in enumerate(row):
                if not isinstance(tile, dict):
                    continue
                pos = (x, y)
                if "animal" in tile:
                    if tile.get("consecutive_unfed", 0) >= 1 and not tile.get("fed_today", False):
                        starving_animals.append(pos)
                    if tile.get("yield_units", 0) > 0:
                        harvestable_animals.append(pos)
                elif tile.get("kind") == "PLANT" or "crop" in tile:
                    if tile.get("consecutive_unwatered", 0) >= 1 and not tile.get("watered_today", False):
                        dying_crops.append(pos)
                    if tile.get("yield_units", 0) > 0 and tile.get("turns_until_decay", 99) <= 1:
                        decaying_crops.append(pos)

    # 1. feed animal in immediate survival danger if eligible unit already holds wheat
    for target in starving_animals:
        if not free_units:
            break
        eligible = [u for u in free_units if wheat_counts.get(u, 0) > 0]
        if not eligible:
            continue
        best_u = min(eligible, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        wheat_counts[best_u] -= 1
        if pos_by_idx[best_u] == target:
            actions[best_u] = ["FEED"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], target, 10)
            actions[best_u] = [step] if step else ["PASS"]

    # 2. water crops that will die today
    for target in dying_crops:
        if not free_units:
            break
        best_u = min(free_units, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        if pos_by_idx[best_u] == target:
            actions[best_u] = ["WATER"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], target, 10)
            actions[best_u] = [step] if step else ["PASS"]

    # 3. harvest crops at immediate decay risk
    for target in decaying_crops:
        if not free_units:
            break
        best_u = min(free_units, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        if pos_by_idx[best_u] == target:
            actions[best_u] = ["HARVEST"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], target, 10)
            actions[best_u] = [step] if step else ["PASS"]

    # 4. harvest animal output if safe
    for target in harvestable_animals:
        if not free_units:
            break
        best_u = min(free_units, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        free_units.remove(best_u)
        if pos_by_idx[best_u] == target:
            actions[best_u] = ["HARVEST"]
        else:
            step = bfs_first_step(pos_by_idx[best_u], target, 10)
            actions[best_u] = [step] if step else ["PASS"]

    return {
        "farmer": list(actions.get(0, ["PASS"])),
        "hands": [list(actions.get(i + 1, ["PASS"])) for i in range(len(hands))],
        "market": [],
        "_emergency_fallback": True,
    }


def _agent_decision(obs: Dict[str, Any]) -> Dict[str, Any]:
    # Phase 6: use get_state for persistent memory + episode detection
    try:
        ctx, mem = get_state(obs)
    except Exception as exc:
        return _emergency_fallback(obs, exc)

    if ctx is None:
        return _emergency_fallback(obs, RuntimeError("ctx is None"))

    planner, builder, brain, liquidator, central_planner = _get_components()

    # v5.9: Reset daily log and opponent state at start of day 0
    if ctx["day"] == 0 and ctx["hour"] == 0:
        try:
            reset_daily_log()
            reset_opponent_model_state()
        except Exception:
            pass

    # Dynamic shop boosts from observed town unlocks
    known_shops = obs.get("town", {}).get("unlocked_shops", []) if isinstance(obs, dict) else []
    boosts = demand_boosts(known_shops)

    # Phase 6: build opponent advice (domain isolated)
    opp_advice = _build_opp_advice(ctx, mem)

    # 1. Macro strategic planning & 2. Task execution (domain isolated)
    asg = None
    plan = None
    is_strategy_fallback = False
    try:
        plan = planner.build(ctx, boosts=boosts, opp_advice=opp_advice)
        if plan.intents.get("buy_land"):
            n_extra = len(ctx["farm"].unlocked) - 1
            next_q = n_extra + 2
            try:
                from config import get_quadrant_hard_block
                _qhb = get_quadrant_hard_block()
            except Exception:
                _qhb = QUADRANT_HARD_BLOCK
            if next_q in _qhb:
                plan.intents["buy_land"] = False  # force block
        tasks = build_tasks(ctx, plan)
        asg = assign_tasks(tasks, ctx)
    except Exception as exc:
        # Fallback to survival tasks when planner or task scheduler fails
        global _LAST_FALLBACK_DIAGNOSTIC
        import traceback
        tb_str = traceback.format_exc()
        _LAST_FALLBACK_DIAGNOSTIC = {
            "step": ctx.get("step", 0),
            "day": ctx.get("day", 0),
            "hour": ctx.get("hour", 0),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": tb_str,
            "is_fallback": True,
        }
        try:
            from config import DEBUG
            if DEBUG:
                sys.stderr.write(f"[STRATEGY_TASK_FALLBACK] D{ctx['day']} H{ctx['hour']:02d}: {exc}\n")
        except Exception:
            pass
        asg = _survival_fallback_from_ctx(ctx)
        is_strategy_fallback = True

    # 3. Market layer: purchase intent compilation (domain isolated)
    active_mode = get_arbitration_mode()
    is_historical = (active_mode in ("legacy", "historical_stack", "historical_candidates_central"))
    builder_max_slots = 10 if is_historical else None
    sell_max_slots = (10 if ctx["day"] >= 28 else 6) if is_historical else None

    purchase_orders = []
    _ledger = None
    try:
        if ctx["hour"] == 0:
            if plan is not None:
                purchase_orders, _ledger = builder.build(ctx, plan.intents, max_slots=builder_max_slots)
        elif ctx["hour"] == 1:
            target_h = get_target_hands(ctx["day"])
            hires_so_far = ctx["farm"].hires_today
            hires_needed = max(0, target_h - hires_so_far)
            if hires_needed > 0:
                limit = builder_max_slots if builder_max_slots is not None else hires_needed
                for _ in range(min(hires_needed, limit)):
                    purchase_orders.append(["HIRE"])
            if plan is not None and plan.intents.get("buy_land"):
                if builder_max_slots is None or len(purchase_orders) < builder_max_slots:
                    purchase_orders.append(["BUY_LAND"])
        else:
            if plan is not None:
                purchase_orders, _ledger = builder.build_intraday(ctx, plan.intents, max_slots=builder_max_slots)
    except Exception:
        purchase_orders = []
        _ledger = None

    # 4. Market layer: sell-side intent compilation (domain isolated)
    sell_orders = []
    _d = None
    try:
        if ctx["day"] >= 28:
            sell_orders, _d = liquidator.plan(ctx, max_slots=sell_max_slots, opp_advice=opp_advice)
        else:
            sell_orders, _d = brain.sell_orders(ctx, max_slots=sell_max_slots, opp_advice=opp_advice)
    except Exception:
        sell_orders = []
        _d = None

    # 5. Market composition / arbitration
    global _LAST_CENTRAL_PLANNER_DIAGNOSTIC, _LAST_TURN_TELEMETRY
    market = []
    _cp_diag = None

    if active_mode in ("legacy", "historical_stack", "expanded_legacy"):
        try:
            market = legacy_compose_market(
                purchase_orders, sell_orders, ctx, cap=10
            )
        except Exception:
            purchases_first = (ctx["hour"] in (0, 1))
            first, second = ((purchase_orders, sell_orders) if purchases_first
                             else (sell_orders, purchase_orders))
            market = [list(o) for o in (first + second)[:10]]
        _LAST_CENTRAL_PLANNER_DIAGNOSTIC = None
    else:
        try:
            market, _cp_diag = central_planner.plan_market(
                ctx,
                macro_plan=plan,
                purchase_orders=purchase_orders,
                purchase_ledger=_ledger,
                sell_orders=sell_orders,
                sell_details=_d,
                opp_advice=opp_advice,
            )
            _LAST_CENTRAL_PLANNER_DIAGNOSTIC = _cp_diag
        except Exception:
            try:
                market = legacy_compose_market(
                    purchase_orders, sell_orders, ctx, cap=10
                )
            except Exception:
                purchases_first = (ctx["hour"] in (0, 1))
                market = [list(o) for o in ((purchase_orders + sell_orders) if purchases_first else (sell_orders + purchase_orders))[:10]]

    for order in market:
        if order[0] == "SELL":
            try:
                record_our_sale(order[1], order[2])
            except Exception:
                pass
        elif order[0] == "BUY_PRODUCT":
            try:
                record_our_buy(order[1], order[2])
            except Exception:
                pass

    # Pipeline progression tracking for Land and Critical Feed Wheat
    land_proposed = any(o[0] == "BUY_LAND" for o in purchase_orders)
    land_selected = any(o[0] == "BUY_LAND" for o in market)

    animals_count = sum(1 for t in ctx["farm"].iter_tiles() if t.is_animal)
    shed_wheat = ctx["private"].shed.get("WHEAT", 0) if ctx.get("private") else 0
    is_critical_wheat_deficit = (animals_count > 0 and shed_wheat < animals_count)
    critical_wheat_proposed = is_critical_wheat_deficit and any(
        o[0] == "BUY_PRODUCT" and len(o) > 1 and o[1] == "WHEAT" for o in purchase_orders
    )
    critical_wheat_selected = is_critical_wheat_deficit and any(
        o[0] == "BUY_PRODUCT" and len(o) > 1 and o[1] == "WHEAT" for o in market
    )

    farm_ctx = ctx["farm"]
    day_val = ctx.get("day", 0)
    hour_val = ctx.get("hour", 0)
    cash_val = float(farm_ctx.money)
    sw_cost_val = 2000.0

    try:
        from strategy.land_serviceability_model import compute_projected_workers
        projected_workers_val = compute_projected_workers(farm_ctx, day_val, money=cash_val, hour=hour_val)
    except Exception:
        projected_workers_val = 1 + len(farm_ctx.hands)

    sw_bought_this_turn = land_selected and (len(farm_ctx.unlocked) == 2 or ("SW" not in farm_ctx.unlocked and "NE" in farm_ctx.unlocked))
    sw_diag = (plan.diagnostics.get("land_decision", {}) if plan and hasattr(plan, "diagnostics") else {})
    sw_affordable = False
    if sw_diag and sw_diag.get("next_quadrant") == 3:
        sw_affordable = bool(sw_diag.get("post_sw_cash_minus_obligations", -999.0) >= sw_diag.get("reserve", 300.0))
    elif cash_val >= sw_cost_val + 300.0:
        sw_affordable = True

    active_sw_target_tiles = 0
    if plan and hasattr(plan, "diagnostics") and "sw_progressive_activation" in plan.diagnostics:
        active_sw_target_tiles = plan.diagnostics["sw_progressive_activation"].get("total_active_target", 0)

    sw_planted_tiles = 0
    if hasattr(farm_ctx, "iter_tiles") and hasattr(farm_ctx, "quadrant_of"):
        for t in farm_ctx.iter_tiles():
            pos = tuple(t.pos) if hasattr(t, "pos") else (tuple(t.get("pos")) if isinstance(t, dict) and "pos" in t else (0, 0))
            if farm_ctx.quadrant_of(pos) == "SW":
                if getattr(t, "is_plant", False) or (isinstance(t, dict) and (t.get("is_plant") or t.get("plant"))):
                    sw_planted_tiles += 1

    discretionary_livestock_suppressed_for_sw = False
    if _ledger and _ledger.get("discretionary_livestock_suppressed_for_sw"):
        discretionary_livestock_suppressed_for_sw = True

    reason_sw_not_bought = None
    if cash_val >= sw_cost_val and "SW" not in farm_ctx.unlocked and not sw_bought_this_turn:
        reason_sw_not_bought = sw_diag.get("final_rejection_or_acceptance_reason", "not_attempted")

    _LAST_TURN_TELEMETRY = {
        "step": ctx.get("step", 0),
        "day": ctx.get("day", 0),
        "hour": ctx.get("hour", 0),
        "mode": active_mode,
        "money_before": float(ctx["farm"].money),
        "shed_before": sum(ctx["private"].shed.values()) if ctx.get("private") else 0,
        "market_inventory_before": dict(ctx["market"].inventory) if ctx.get("market") else {},
        "unlocked_land": sorted(list(ctx["farm"].unlocked)),
        "animal_count": animals_count,
        "wheat_on_hand": shed_wheat,
        "purchase_orders": [list(o) for o in purchase_orders],
        "purchase_ledger": copy.deepcopy(_ledger) if _ledger else None,
        "sell_orders": [list(o) for o in sell_orders],
        "sell_details": copy.deepcopy(_d) if _d else None,
        "market": [list(o) for o in market],
        "land_proposed": land_proposed,
        "land_selected": land_selected,
        "critical_wheat_proposed": critical_wheat_proposed,
        "critical_wheat_selected": critical_wheat_selected,
        "projected_workers": projected_workers_val,
        "sw_cost": sw_cost_val,
        "sw_affordable": sw_affordable,
        "sw_bought_this_turn": sw_bought_this_turn,
        "active_sw_target_tiles": active_sw_target_tiles,
        "sw_planted_tiles": sw_planted_tiles,
        "discretionary_livestock_suppressed_for_sw": discretionary_livestock_suppressed_for_sw,
        "reason_sw_not_bought": reason_sw_not_bought,
        "sw_telemetry": {
            "day": day_val,
            "hour": hour_val,
            "cash": cash_val,
            "projected_workers": projected_workers_val,
            "sw_cost": sw_cost_val,
            "sw_affordable": sw_affordable,
            "sw_bought_this_turn": sw_bought_this_turn,
            "active_sw_target_tiles": active_sw_target_tiles,
            "sw_planted_tiles": sw_planted_tiles,
            "discretionary_livestock_suppressed_for_sw": discretionary_livestock_suppressed_for_sw,
            "reason_sw_not_bought": reason_sw_not_bought,
        },
        "wheat_telemetry": copy.deepcopy(_cp_diag.get("wheat_telemetry")) if (_cp_diag and "wheat_telemetry" in _cp_diag) else None,
        "sell_telemetry": copy.deepcopy(_cp_diag.get("sell_telemetry")) if (_cp_diag and "sell_telemetry" in _cp_diag) else None,
        "central_planner_diagnostic": copy.deepcopy(_cp_diag) if _cp_diag else None,
        "macro_plan_diagnostic": copy.deepcopy(plan.diagnostics) if plan and hasattr(plan, "diagnostics") else None,
    }

    # 6. Action dict assembly
    n_units = 1 + len(ctx["farm"].hands)
    res = {
        "farmer": list(asg["actions"].get(0, ["PASS"])),
        "hands": [list(asg["actions"].get(i, ["PASS"])) for i in range(1, n_units)],
        "market": market,
    }
    if is_strategy_fallback:
        res["_emergency_fallback"] = True
    return res


_LAST_FALLBACK_DIAGNOSTIC: Optional[Dict[str, Any]] = None


def get_last_fallback_diagnostic() -> Optional[Dict[str, Any]]:
    """Return diagnostic telemetry from the most recent emergency fallback, if any."""
    return _LAST_FALLBACK_DIAGNOSTIC


def _emergency_fallback(obs: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
    """Safe, deterministic emergency fallback returning a survival-capable action."""
    global _LAST_FALLBACK_DIAGNOSTIC
    import traceback
    tb_str = traceback.format_exc()

    day = obs.get("day", 0) if isinstance(obs, dict) else 0
    hour = obs.get("hour", 0) if isinstance(obs, dict) else 0
    step = obs.get("step", 0) if isinstance(obs, dict) else 0

    _LAST_FALLBACK_DIAGNOSTIC = {
        "step": step,
        "day": day,
        "hour": hour,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": tb_str,
        "is_fallback": True,
    }

    try:
        from config import DEBUG
        if DEBUG:
            sys.stderr.write(f"[EMERGENCY_FALLBACK] Step {step} (D{day} H{hour:02d}): {exc}\n{tb_str}\n")
    except Exception:
        pass

    try:
        ctx = parse_observation(obs)
        if ctx is not None:
            asg = _survival_fallback_from_ctx(ctx)
            n_hands = len(ctx["farm"].hands)
            return {
                "farmer": list(asg["actions"].get(0, ["PASS"])),
                "hands": [list(asg["actions"].get(i + 1, ["PASS"])) for i in range(n_hands)],
                "market": [],
                "_emergency_fallback": True,
            }
    except Exception:
        pass

    return _survival_fallback_raw(obs)


def get_daily_telemetry() -> Dict[int, Dict[str, Any]]:
    """Return complete daily telemetry log."""
    return get_daily_log()


def reset_daily_telemetry() -> None:
    """Reset daily telemetry log and seasonal trackers."""
    reset_daily_log()


def get_sw_telemetry() -> Dict[str, Any]:
    """Return seasonal SW telemetry summary."""
    return get_sw_season_summary()


# ==============================================================================
# KAGGLE ENTRY POINT (LAST 'def')
# ==============================================================================
def agent(obs: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Official competition entry point with safe deterministic fallback."""
    global _LAST_FALLBACK_DIAGNOSTIC
    try:
        _LAST_FALLBACK_DIAGNOSTIC = None
        return _agent_decision(obs)
    except Exception as exc:
        return _emergency_fallback(obs, exc)
