#!/usr/bin/env python3
"""Phase SW-B3A-R1: Transaction Ledger & Causal Telemetry Integrity Tournament Runner.

Executes the 20 matched pairs (40 total matches) on development seeds 97013-97014
across all 5 canonical opponents in both seats (0 and 1) with complete engine-grounded
transaction auditing and causal telemetry:
1. Validates exact parity against frozen Gate 2 cash outcomes ($0.00 difference across 40 matches).
2. Intercepts engine execution functions directly (_commit_unit, _do_hire, _do_buy_land,
   _apply_unit_action, _drop_inventories_to_shed) to achieve $0.00 residual in every match ledger.
3. Reconciles physical inventory conservation (Diff = 0) without fictitious adjustments.
4. Generates mathematically closed paired cash waterfalls (0.00 residual across all 20 pairs).
5. Tracks genuine worker actions and regional movement telemetry.
6. Reconciles midnight rollover overflow discards against pre-midnight rescue sales.
7. Validates the complete 9-stage SW land lifecycle, including engine-confirmed productive planting.
8. Audits turn latency profiles against engine limits (actTimeout: 1 = 1,000 ms).
9. Emits all required JSON artifacts into simulations/results/phase_sw_b3a_r1/.
"""
import copy
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kag
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "agent") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "agent"))

CANARY_SEEDS = [97013, 97014]
CANONICAL_OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]
SEATS = [0, 1]

_OUT_DIR = os.path.join(PROJECT_ROOT, "simulations", "results", "phase_sw_b3a_r1")
_GATE2_RESULTS_PATH = os.path.join(
    PROJECT_ROOT, "simulations", "results", "phase_sw_b2_gate2_canary", "live_canary_20_pairs.json"
)

# Seed prices from engine
SEED_PRICES = {
    "WHEAT": 20.0,
    "CARROT": 30.0,
    "TOMATO": 40.0,
    "STRAWBERRY": 60.0,
    "MELON": 80.0,
}

# Animal product base prices
ANIMAL_BASE_PRICES = {
    "COW": 400.0,
    "SHEEP": 300.0,
    "CHICKEN": 200.0,
}


def compute_file_sha256(path: str) -> str:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    return "NOT_FOUND"


def to_serializable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            (f"{k[0]},{k[1]}" if isinstance(k, tuple) else str(k)): to_serializable(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, (list, tuple, set)):
        return [to_serializable(x) for x in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def get_source_manifest() -> Dict[str, str]:
    files = {
        "kaggriculture_engine": r"C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py",
        "agent/main.py": os.path.join(PROJECT_ROOT, "agent", "main.py"),
        "agent/config.py": os.path.join(PROJECT_ROOT, "agent", "config.py"),
        "agent/execution/task_scheduler.py": os.path.join(PROJECT_ROOT, "agent", "execution", "task_scheduler.py"),
        "agent/execution/midnight_storage_controller.py": os.path.join(PROJECT_ROOT, "agent", "execution", "midnight_storage_controller.py"),
        "agent/strategy/sw_tranche_controller.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "sw_tranche_controller.py"),
        "agent/strategy/macro_planner.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "macro_planner.py"),
        "agent/strategy/farm_plan.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "farm_plan.py"),
        "agent/strategy/resource_ledger.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "resource_ledger.py"),
        "agent/strategy/service_certificate.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "service_certificate.py"),
        "agent/strategy/cohort_planner.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "cohort_planner.py"),
        "agent/strategy/whole_farm_planner.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "whole_farm_planner.py"),
        "agent/diagnostics/animal_tracker.py": os.path.join(PROJECT_ROOT, "agent", "diagnostics", "animal_tracker.py"),
        "submission/main.py": os.path.join(PROJECT_ROOT, "submission", "main.py"),
        "submission/config.py": os.path.join(PROJECT_ROOT, "submission", "config.py"),
        "submission/strategy/sw_tranche_controller.py": os.path.join(PROJECT_ROOT, "submission", "strategy", "sw_tranche_controller.py"),
        "submission/strategy/macro_planner.py": os.path.join(PROJECT_ROOT, "submission", "strategy", "macro_planner.py"),
        "submission/strategy/farm_plan.py": os.path.join(PROJECT_ROOT, "submission", "strategy", "farm_plan.py"),
        "dist/submission.zip": os.path.join(PROJECT_ROOT, "dist", "submission.zip"),
    }
    return {k: compute_file_sha256(v) for k, v in files.items()}


class MatchEngineAuditor:
    """Rigorous turn-by-turn interceptor for engine mechanics."""

    def __init__(self, monitored_seat: int = 0):
        self.monitored_seat = monitored_seat
        self.step_reconciliations = []
        self.transactions = []
        self.worker_actions = []
        self.harvest_events = []
        self.discard_events = []
        self.current_step = 0

        # Exact cash ledger
        self.cash_ledger = {
            "starting_cash": 3000.0,
            "crop_sales_rev": {c: 0.0 for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "crop_sales_units": {c: 0 for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "animal_sales_rev": {p: 0.0 for p in ("MILK", "WOOL", "FERTILIZER", "EGG", "CHICKEN_MEAT", "COW_MEAT")},
            "animal_sales_units": {p: 0 for p in ("MILK", "WOOL", "FERTILIZER", "EGG", "CHICKEN_MEAT", "COW_MEAT")},
            "land_purchases_cost": 0.0,
            "land_purchases_count": 0,
            "seed_purchases_cost": {c: 0.0 for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "seed_purchases_units": {c: 0 for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "animal_purchases_cost": {a: 0.0 for a in ("COW", "SHEEP", "CHICKEN")},
            "animal_purchases_units": {a: 0 for a in ("COW", "SHEEP", "CHICKEN")},
            "feed_purchases_cost": 0.0,
            "feed_purchases_units": 0,
            "fertilizer_purchases_cost": 0.0,
            "fertilizer_purchases_units": 0,
            "hiring_costs": 0.0,
            "hires_count": 0,
            "wages_paid": 0.0,
        }

        # Inventory conservation ledger
        self.inventory_ledger = {
            item: {
                "opening": 0,
                "harvested_core": 0,
                "harvested_sw": 0,
                "purchased": 0,
                "produced_animal": 0,
                "sold": 0,
                "consumed_feed": 0,
                "consumed_fertilizer": 0,
                "consumed_animal_place": 0,
                "discarded_overflow": 0,
                "ending_shed": 0,
                "ending_worker": 0,
            }
            for item in (
                "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "MILK", "WOOL", "FERTILIZER", "EGG", "COW", "SHEEP", "CHICKEN"
            )
        }

        # Seed ledger
        self.seed_ledger = {
            c: {
                "opening": 0,
                "purchased": 0,
                "planted_core": 0,
                "planted_sw": 0,
                "ending": 0,
            }
            for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
        }

        # Worker action counts
        self.worker_telemetry = {
            "total_actions": 0,
            "harvest_actions": 0,
            "water_actions": 0,
            "plant_actions": 0,
            "feed_actions": 0,
            "care_actions": 0,
            "fertilize_actions": 0,
            "move_actions": 0,
            "place_actions": 0,
            "pickup_actions": 0,
            "drop_actions": 0,
            "dig_actions": 0,
            "build_actions": 0,
            "idle_actions": 0,
            "quadrant_transitions_nw_to_sw": 0,
            "quadrant_transitions_sw_to_nw": 0,
            "actions_in_sw": 0,
            "actions_in_core": 0,
        }

        self.first_productive_plant_event = None
        self._current_step_inflows = 0.0
        self._current_step_outflows = 0.0

    def start_step(self, step: int):
        self.current_step = step
        self._current_step_inflows = 0.0
        self._current_step_outflows = 0.0

    def record_commit(self, player_id: int, op: str, item: str, price: float):
        if player_id != self.monitored_seat:
            return
        px = float(price)
        tx = {
            "step": self.current_step,
            "player": player_id,
            "op": op,
            "item": item,
            "price": px,
        }
        self.transactions.append(tx)
        if op == "SELL":
            self._current_step_inflows += px
            if item in self.cash_ledger["crop_sales_rev"]:
                self.cash_ledger["crop_sales_rev"][item] += px
                self.cash_ledger["crop_sales_units"][item] += 1
            else:
                self.cash_ledger["animal_sales_rev"][item] = self.cash_ledger["animal_sales_rev"].get(item, 0.0) + px
                self.cash_ledger["animal_sales_units"][item] = self.cash_ledger["animal_sales_units"].get(item, 0) + 1
            if item in self.inventory_ledger:
                self.inventory_ledger[item]["sold"] += 1

        elif op == "BUY_PRODUCT":
            self._current_step_outflows += px
            if item == "WHEAT":
                self.cash_ledger["feed_purchases_cost"] += px
                self.cash_ledger["feed_purchases_units"] += 1
            elif item == "FERTILIZER":
                self.cash_ledger["fertilizer_purchases_cost"] += px
                self.cash_ledger["fertilizer_purchases_units"] += 1
            if item in self.inventory_ledger:
                self.inventory_ledger[item]["purchased"] += 1

        elif op == "BUY_SEED":
            self._current_step_outflows += px
            if item in self.cash_ledger["seed_purchases_cost"]:
                self.cash_ledger["seed_purchases_cost"][item] += px
                self.cash_ledger["seed_purchases_units"][item] += 1
            if item in self.seed_ledger:
                self.seed_ledger[item]["purchased"] += 1

        elif op == "BUY_ANIMAL":
            self._current_step_outflows += px
            if item in self.cash_ledger["animal_purchases_cost"]:
                self.cash_ledger["animal_purchases_cost"][item] += px
                self.cash_ledger["animal_purchases_units"][item] += 1
            if item in self.inventory_ledger:
                self.inventory_ledger[item]["purchased"] += 1

    def record_hire(self, player_id: int, cost: float, hires_today: int):
        if player_id != self.monitored_seat:
            return
        c = float(cost)
        self._current_step_outflows += c
        self.cash_ledger["hiring_costs"] += c
        self.cash_ledger["hires_count"] += 1
        self.transactions.append({
            "step": self.current_step,
            "player": player_id,
            "op": "HIRE",
            "cost": c,
            "hires_today": hires_today,
        })

    def record_land(self, player_id: int, cost: float, quadrant: str):
        if player_id != self.monitored_seat:
            return
        c = float(cost)
        self._current_step_outflows += c
        self.cash_ledger["land_purchases_cost"] += c
        self.cash_ledger["land_purchases_count"] += 1
        self.transactions.append({
            "step": self.current_step,
            "player": player_id,
            "op": "BUY_LAND",
            "cost": c,
            "quadrant": quadrant,
        })

    def record_action(self, player_id: int, unit_idx: int, action: Any, pre_pos: Tuple[int, int], post_pos: Tuple[int, int], outcome: Dict[str, Any]):
        if player_id != self.monitored_seat:
            return
        op = action[0] if isinstance(action, (list, tuple)) and action else "PASS"
        self.worker_telemetry["total_actions"] += 1

        is_sw = (pre_pos[0] < 5 and pre_pos[1] >= 5)
        if is_sw:
            self.worker_telemetry["actions_in_sw"] += 1
        else:
            self.worker_telemetry["actions_in_core"] += 1

        was_sw = (pre_pos[0] < 5 and pre_pos[1] >= 5)
        is_sw_now = (post_pos[0] < 5 and post_pos[1] >= 5)
        if not was_sw and is_sw_now:
            self.worker_telemetry["quadrant_transitions_nw_to_sw"] += 1
        elif was_sw and not is_sw_now:
            self.worker_telemetry["quadrant_transitions_sw_to_nw"] += 1

        if op in kag.FARMER_MOVES:
            self.worker_telemetry["move_actions"] += 1
        elif op == "WATER":
            self.worker_telemetry["water_actions"] += 1
        elif op == "PLANT":
            self.worker_telemetry["plant_actions"] += 1
            if outcome.get("planted"):
                crop = action[1]
                if is_sw:
                    self.seed_ledger[crop]["planted_sw"] += 1
                    if self.first_productive_plant_event is None:
                        self.first_productive_plant_event = {
                            "step": self.current_step,
                            "day": self.current_step // 24,
                            "hour": self.current_step % 24,
                            "crop": crop,
                            "pos": list(pre_pos),
                        }
                else:
                    self.seed_ledger[crop]["planted_core"] += 1
        elif op == "HARVEST":
            self.worker_telemetry["harvest_actions"] += 1
            if outcome.get("yield_units", 0) > 0:
                item = outcome["item"]
                units = outcome["yield_units"]
                if item in ("MILK", "WOOL", "EGG"):
                    self.inventory_ledger[item]["produced_animal"] += units
                else:
                    if is_sw:
                        self.inventory_ledger[item]["harvested_sw"] += units
                    else:
                        self.inventory_ledger[item]["harvested_core"] += units
                self.harvest_events.append({
                    "step": self.current_step,
                    "pos": list(pre_pos),
                    "item": item,
                    "units": units,
                    "is_sw": is_sw,
                })
        elif op == "FEED":
            self.worker_telemetry["feed_actions"] += 1
            if outcome.get("fed"):
                self.inventory_ledger["WHEAT"]["consumed_feed"] += 1
        elif op == "CARE":
            self.worker_telemetry["care_actions"] += 1
        elif op == "FERTILIZE":
            self.worker_telemetry["fertilize_actions"] += 1
            if outcome.get("fertilized"):
                self.inventory_ledger["FERTILIZER"]["consumed_fertilizer"] += 1
        elif op == "COLLECT_FERTILIZER":
            if outcome.get("collected_fertilizer"):
                self.inventory_ledger["FERTILIZER"]["produced_animal"] += 1
        elif op == "PLACE":
            self.worker_telemetry["place_actions"] += 1
            if outcome.get("animal_placed"):
                anim = action[1]
                if anim in self.inventory_ledger:
                    self.inventory_ledger[anim]["consumed_animal_place"] += 1
        elif op == "PICKUP":
            self.worker_telemetry["pickup_actions"] += 1
        elif op == "DROP":
            self.worker_telemetry["drop_actions"] += 1
        elif op == "DIG":
            self.worker_telemetry["dig_actions"] += 1
        elif op in ("BUILD_COOP", "BUILD_PASTURE"):
            self.worker_telemetry["build_actions"] += 1
        elif op == "PASS":
            self.worker_telemetry["idle_actions"] += 1

    def record_drop_to_shed(self, player_id: int, discarded_dict: Dict[str, int]):
        if player_id != self.monitored_seat:
            return
        for item, qty in discarded_dict.items():
            if qty > 0:
                if item in self.inventory_ledger:
                    self.inventory_ledger[item]["discarded_overflow"] += qty
                self.discard_events.append({
                    "step": self.current_step,
                    "day": self.current_step // 24,
                    "item": item,
                    "units": qty,
                })

    def end_step(self, pre_cash: float, post_cash: float):
        expected_cash = pre_cash + self._current_step_inflows - self._current_step_outflows
        diff = round(post_cash - expected_cash, 4)
        self.step_reconciliations.append({
            "step": self.current_step,
            "pre_cash": pre_cash,
            "post_cash": post_cash,
            "inflows": self._current_step_inflows,
            "outflows": self._current_step_outflows,
            "diff": diff,
            "reconciled": abs(diff) < 0.0001,
        })


def run_single_audited_match(seed: int, opp_name: str, seat: int, mode: str) -> Dict[str, Any]:
    """Execute a single match with full engine interception and causal auditing."""
    import agent.config as config
    config.SW_FORWARD_ARCHITECTURE_MODE = mode
    config.SOFT_WORKER_LOCALITY_MODE = "ON"
    config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
    config.QUADRANT_HARD_BLOCK = {4}

    from agent.main import agent as my_agent, reset_agent_state
    from agent.strategy.farm_plan import reset_farm_plan
    from agent.strategy.whole_farm_planner import reset_whole_farm_planner
    from agent.strategy.sw_tranche_controller import (
        get_sw_tranche_controller,
        reset_sw_tranche_controller,
    )
    from agent.execution.midnight_storage_controller import (
        reset_midnight_storage_telemetry,
        get_midnight_storage_telemetry,
    )
    from agent.diagnostics.animal_tracker import AnimalSurvivalTracker
    from simulations.experiments.agent_zoo import get_agent

    # Clean singleton states
    reset_agent_state()
    reset_farm_plan()
    reset_whole_farm_planner()
    reset_sw_tranche_controller()
    reset_midnight_storage_telemetry()

    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(mode == "TREATMENT")

    animal_tracker = AnimalSurvivalTracker(seat=seat)
    opp_agent = get_agent(opp_name)

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()

    auditor = MatchEngineAuditor(monitored_seat=seat)

    # Intercept engine globals inside env.interpreter
    orig_interp = env.interpreter
    g = orig_interp.__globals__
    orig_commit = g["_commit_unit"]
    orig_hire = g["_do_hire"]
    orig_land = g["_do_buy_land"]
    orig_unit_action = g["_apply_unit_action"]
    orig_drop_shed = g["_drop_inventories_to_shed"]
    orig_pm = g["_process_market"]

    current_state = [None]

    def audited_interpreter(state, env_obj):
        current_state[0] = state
        return orig_interp(state, env_obj)

    env.interpreter = audited_interpreter

    def audited_pm(state, env_obj):
        p0_priv = state[0].observation.private
        p1_priv = state[1].observation.private

        def audited_commit(op, item, price, farm, private, market, shed_capacity=100):
            p_id = 0 if private is p0_priv else (1 if private is p1_priv else -1)
            ok = orig_commit(op, item, price, farm, private, market, shed_capacity)
            if ok:
                auditor.record_commit(p_id, op, item, price)
            return ok

        def audited_hire(farm, private, board_size, mult=1):
            p_id = 0 if private is p0_priv else (1 if private is p1_priv else -1)
            pre_m = farm["money"]
            orig_hire(farm, private, board_size, mult)
            post_m = farm["money"]
            if post_m != pre_m:
                auditor.record_hire(p_id, pre_m - post_m, farm["hires_today"])

        def audited_land(farm, board_size):
            p_id = 0 if farm is state[0].observation.farms[0] else (1 if farm is state[0].observation.farms[1] else -1)
            pre_m = farm["money"]
            orig_land(farm, board_size)
            post_m = farm["money"]
            if post_m != pre_m:
                auditor.record_land(p_id, pre_m - post_m, farm["unlocked_quadrants"][-1])

        g["_commit_unit"] = audited_commit
        g["_do_hire"] = audited_hire
        g["_do_buy_land"] = audited_land
        try:
            orig_pm(state, env_obj)
        finally:
            g["_commit_unit"] = orig_commit
            g["_do_hire"] = orig_hire
            g["_do_buy_land"] = orig_land

    def audited_unit_action(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity=100):
        p0_priv = current_state[0][0].observation.private if current_state[0] else None
        p_id = 0 if private is p0_priv else 1
        pre_pos = tuple(farm["farmer"]) if idx == 0 else tuple(farm["hands"][idx - 1])
        pre_tile = copy.deepcopy(farm["tiles"][pre_pos[1]][pre_pos[0]]) if pre_pos[1] < len(farm["tiles"]) and pre_pos[0] < len(farm["tiles"][pre_pos[1]]) else None

        orig_unit_action(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity)

        post_pos = tuple(farm["farmer"]) if idx == 0 else tuple(farm["hands"][idx - 1])
        post_tile = copy.deepcopy(farm["tiles"][pre_pos[1]][pre_pos[0]]) if pre_pos[1] < len(farm["tiles"]) and pre_pos[0] < len(farm["tiles"][pre_pos[1]]) else None

        outcome = {}
        op = action[0] if isinstance(action, (list, tuple)) and action else "PASS"
        if op == "HARVEST":
            if isinstance(pre_tile, dict) and pre_tile.get("yield_units", 0) > 0:
                if pre_tile.get("kind") == "PLANT":
                    outcome = {"item": pre_tile["crop"], "yield_units": pre_tile["yield_units"]}
                elif "animal" in pre_tile:
                    outcome = {"item": kag.ANIMALS[pre_tile["animal"]]["product"], "yield_units": pre_tile["yield_units"]}
        elif op == "PLANT":
            if pre_tile is None and isinstance(post_tile, dict) and post_tile.get("kind") == "PLANT":
                outcome = {"planted": True, "crop": action[1]}
        elif op == "FEED":
            if isinstance(pre_tile, dict) and not pre_tile.get("fed_today") and isinstance(post_tile, dict) and post_tile.get("fed_today"):
                outcome = {"fed": True}
        elif op == "FERTILIZE":
            if isinstance(pre_tile, dict) and isinstance(post_tile, dict) and post_tile.get("fertilized_until_day", -1) > pre_tile.get("fertilized_until_day", -1):
                outcome = {"fertilized": True}
        elif op == "COLLECT_FERTILIZER":
            if isinstance(pre_tile, dict) and pre_tile.get("fertilizer_available") and isinstance(post_tile, dict) and not post_tile.get("fertilizer_available"):
                outcome = {"collected_fertilizer": True}
        elif op == "PLACE":
            if isinstance(post_tile, dict) and "animal" in post_tile and (pre_tile is None or "animal" not in pre_tile):
                outcome = {"animal_placed": True}

        auditor.record_action(p_id, idx, action, pre_pos, post_pos, outcome)

    def audited_drop_shed(private, capacity=100):
        p0_priv = current_state[0][0].observation.private if current_state[0] else None
        p_id = 0 if private is p0_priv else 1
        shed = private["shed"]
        current = sum(v for k, v in shed.items())
        room = max(0, capacity - current)
        discarded = {}
        for inv in private["inventories"]:
            for item, n in list(inv.items()):
                if n <= 0:
                    continue
                take = min(n, room)
                overflow = n - take
                if overflow > 0:
                    discarded[item] = discarded.get(item, 0) + overflow
                room = max(0, room - take)
        auditor.record_drop_to_shed(p_id, discarded)
        orig_drop_shed(private, capacity)

    g["_process_market"] = audited_pm
    g["_apply_unit_action"] = audited_unit_action
    g["_drop_inventories_to_shed"] = audited_drop_shed

    # Opening inventory
    priv_init = env.state[seat].observation.private
    for c, n in priv_init.get("seeds", {}).items():
        if c in auditor.seed_ledger:
            auditor.seed_ledger[c]["opening"] = n
    for item, n in priv_init.get("shed", {}).items():
        if item in auditor.inventory_ledger:
            auditor.inventory_ledger[item]["opening"] = n

    turn_latencies = []
    min_cash_seen = 3000.0
    peak_shed_occupancy = 0

    try:
        while not env.done:
            obs0 = env.state[0].observation
            obs1 = env.state[1].observation
            my_obs = obs0 if seat == 0 else obs1
            opp_obs = obs1 if seat == 0 else obs0
            step = my_obs.get("step", 0)

            cur_cash = float(my_obs["farms"][seat]["money"])
            if cur_cash < min_cash_seen:
                min_cash_seen = cur_cash

            animal_tracker.observe_turn(my_obs)

            priv_curr = my_obs.get("private", {})
            shed_cur = priv_curr.get("shed", {})
            shed_sum = sum(int(v) for v in shed_cur.values())
            if shed_sum > peak_shed_occupancy:
                peak_shed_occupancy = shed_sum

            pre_cash = cur_cash
            auditor.start_step(step)

            t_start = time.perf_counter()
            my_act = my_agent(my_obs, env.configuration)
            t_ms = (time.perf_counter() - t_start) * 1000.0
            turn_latencies.append(t_ms)

            try:
                opp_act = opp_agent(opp_obs, env.configuration)
            except TypeError:
                opp_act = opp_agent(opp_obs)

            actions = [my_act, opp_act] if seat == 0 else [opp_act, my_act]
            env.step(actions)

            post_cash = float(env.state[seat].observation["farms"][seat]["money"])
            auditor.end_step(pre_cash, post_cash)
    finally:
        # Restore original engine functions
        kag._commit_unit = orig_commit
        kag._do_hire = orig_hire
        kag._do_buy_land = orig_land
        kag._apply_unit_action = orig_unit_action
        kag._drop_inventories_to_shed = orig_drop_shed
        g["_process_market"] = orig_pm
        g["_apply_unit_action"] = orig_unit_action
        g["_drop_inventories_to_shed"] = orig_drop_shed

    final_obs_my = env.state[seat].observation
    final_obs_opp = env.state[1 - seat].observation
    final_cash = float(final_obs_my["farms"][seat]["money"])
    opp_final_cash = float(final_obs_opp["farms"][1 - seat]["money"])
    win = final_cash > opp_final_cash

    # Populate ending inventory counts
    priv_end = final_obs_my.private
    for item, n in priv_end.get("shed", {}).items():
        if item in auditor.inventory_ledger:
            auditor.inventory_ledger[item]["ending_shed"] = n
    for inv in priv_end.get("inventories", []):
        for item, n in inv.items():
            if item in auditor.inventory_ledger:
                auditor.inventory_ledger[item]["ending_worker"] += n
    for c, n in priv_end.get("seeds", {}).items():
        if c in auditor.seed_ledger:
            auditor.seed_ledger[c]["ending"] = n

    # Reconcile full cash accounting identity
    cl = auditor.cash_ledger
    tot_crop_sales = sum(cl["crop_sales_rev"].values())
    tot_animal_sales = sum(cl["animal_sales_rev"].values())
    tot_inflows = tot_crop_sales + tot_animal_sales
    tot_seed_costs = sum(cl["seed_purchases_cost"].values())
    tot_animal_costs = sum(cl["animal_purchases_cost"].values())
    tot_outflows = (
        cl["land_purchases_cost"]
        + tot_seed_costs
        + tot_animal_costs
        + cl["feed_purchases_cost"]
        + cl["fertilizer_purchases_cost"]
        + cl["hiring_costs"]
        + cl["wages_paid"]
    )
    reconciled_cash = round(cl["starting_cash"] + tot_inflows - tot_outflows, 4)
    residual = round(final_cash - reconciled_cash, 4)
    assert abs(residual) < 1e-4, f"Non-zero cash residual in {seed}_{opp_name}_{seat}_{mode}: {residual}"

    # Reconcile physical inventory conservation:
    # Opening + Harvested + Purchased + Produced = Sold + Consumed + Discarded + Ending
    inventory_conservation = {}
    for item, row in auditor.inventory_ledger.items():
        in_qty = row["opening"] + row["harvested_core"] + row["harvested_sw"] + row["purchased"] + row["produced_animal"]
        out_qty = (
            row["sold"]
            + row["consumed_feed"]
            + row["consumed_fertilizer"]
            + row["consumed_animal_place"]
            + row["discarded_overflow"]
            + row["ending_shed"]
            + row["ending_worker"]
        )
        diff = in_qty - out_qty
        assert diff == 0, f"Inventory conservation violated for {item} in {seed}_{opp_name}_{seat}_{mode}: In={in_qty} Out={out_qty} Diff={diff}"
        inventory_conservation[item] = {
            "in_total": in_qty,
            "out_total": out_qty,
            "diff": diff,
            "breakdown": row,
        }

    # Reconcile seed conservation:
    # Opening + Purchased = Planted_Core + Planted_SW + Ending
    seed_conservation = {}
    for crop, row in auditor.seed_ledger.items():
        in_seeds = row["opening"] + row["purchased"]
        out_seeds = row["planted_core"] + row["planted_sw"] + row["ending"]
        s_diff = in_seeds - out_seeds
        assert s_diff == 0, f"Seed conservation violated for {crop} in {seed}_{opp_name}_{seat}_{mode}: In={in_seeds} Out={out_seeds} Diff={s_diff}"
        seed_conservation[crop] = {
            "in_seeds": in_seeds,
            "out_seeds": out_seeds,
            "diff": s_diff,
            "breakdown": row,
        }

    animal_summary = animal_tracker.get_summary()
    rescue_telem = get_midnight_storage_telemetry()
    unreconciled_steps = [s for s in auditor.step_reconciliations if not s["reconciled"]]

    # SW tranche controller lifecycle
    lifecycle_dict = ctrl.state.lifecycle.to_dict() if mode == "TREATMENT" else {}
    if mode == "TREATMENT" and auditor.first_productive_plant_event:
        ev = auditor.first_productive_plant_event
        lifecycle_dict["stage_9_planted"] = {
            "step": ev["step"],
            "day": ev["day"],
            "hour": ev["hour"],
            "crop": ev["crop"],
            "pos": ev["pos"],
        }
    elif mode == "TREATMENT":
        lifecycle_dict["stage_9_planted"] = None

    return {
        "cell": {
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
            "mode": mode,
        },
        "outcome": {
            "final_cash": final_cash,
            "opp_final_cash": opp_final_cash,
            "win": win,
            "total_turns": len(auditor.step_reconciliations),
            "min_cash_seen": min_cash_seen,
            "mean_latency_ms": round(float(np.mean(turn_latencies)), 2) if turn_latencies else 0.0,
            "p95_latency_ms": round(float(np.percentile(turn_latencies, 95)), 2) if turn_latencies else 0.0,
            "p99_latency_ms": round(float(np.percentile(turn_latencies, 99)), 2) if turn_latencies else 0.0,
            "max_latency_ms": round(float(np.max(turn_latencies)), 2) if turn_latencies else 0.0,
            "act_timeout_ms": 1000.0,
            "latency_compliant": (max(turn_latencies) < 1000.0) if turn_latencies else True,
        },
        "cash_ledger": cl,
        "cash_reconciliation": {
            "starting_cash": cl["starting_cash"],
            "total_inflows": tot_inflows,
            "total_outflows": tot_outflows,
            "reconciled_cash": reconciled_cash,
            "final_cash": final_cash,
            "residual": residual,
            "zero_residual_verified": abs(residual) < 1e-4,
            "unreconciled_step_count": len(unreconciled_steps),
        },
        "inventory_conservation": inventory_conservation,
        "seed_conservation": seed_conservation,
        "worker_telemetry": auditor.worker_telemetry,
        "storage_safety": {
            "peak_shed_occupancy": peak_shed_occupancy,
            "rescue_events": rescue_telem.get("rescue_events", 0),
            "rescue_units_sold": rescue_telem.get("rescue_units_sold", 0),
            "genuine_overflow_discard_events": len(auditor.discard_events),
            "genuine_overflow_units_discarded": sum(e["units"] for e in auditor.discard_events),
            "discard_events": auditor.discard_events,
        },
        "animal_safety": animal_summary,
        "sw_lifecycle": lifecycle_dict,
        "first_productive_plant_event": auditor.first_productive_plant_event,
    }


def run_paired_audited_cell(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    """Execute matched pair (Control vs Treatment) with full causal decomposition."""
    pair_id = f"s{seed}_{opp_name}_seat{seat}"
    print(f"Starting matched pair: {pair_id}...")

    ctrl_res = run_single_audited_match(seed, opp_name, seat, mode="CONTROL")
    treat_res = run_single_audited_match(seed, opp_name, seat, mode="TREATMENT")

    c_cash = ctrl_res["outcome"]["final_cash"]
    t_cash = treat_res["outcome"]["final_cash"]
    paired_delta = round(t_cash - c_cash, 2)

    c_led = ctrl_res["cash_ledger"]
    t_led = treat_res["cash_ledger"]

    # 1. SW Crop Revenue & Core Crop Revenue Decomposition
    # Allocate Treatment crop sales proportionally based on harvested units (SW vs Core)
    sw_crop_rev = 0.0
    treat_core_crop_rev = 0.0
    sw_crop_breakdown = {}
    core_crop_delta_by_crop = {}

    for crop in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
        t_rev = t_led["crop_sales_rev"][crop]
        c_rev = c_led["crop_sales_rev"][crop]
        h_sw = treat_res["inventory_conservation"][crop]["breakdown"]["harvested_sw"]
        h_core = treat_res["inventory_conservation"][crop]["breakdown"]["harvested_core"]
        h_tot = h_sw + h_core

        if h_tot > 0 and h_sw > 0:
            sw_rev_c = t_rev * (h_sw / h_tot)
        else:
            sw_rev_c = 0.0
        core_rev_t_c = t_rev - sw_rev_c

        sw_crop_rev += sw_rev_c
        treat_core_crop_rev += core_rev_t_c
        sw_crop_breakdown[crop] = {
            "harvested_sw": h_sw,
            "harvested_core": h_core,
            "treatment_revenue": t_rev,
            "sw_attributed_revenue": round(sw_rev_c, 2),
            "core_attributed_revenue": round(core_rev_t_c, 2),
        }
        core_crop_delta_by_crop[crop] = round(core_rev_t_c - c_rev, 2)

    core_crop_revenue_delta = round(treat_core_crop_rev - sum(c_led["crop_sales_rev"].values()), 2)
    sw_crop_rev = round(sw_crop_rev, 2)

    # 2. SW Direct Expenditures
    sw_land_cost = t_led["land_purchases_cost"] - c_led["land_purchases_cost"]
    # SW seed cost from seeds planted in SW
    sw_seed_cost = 0.0
    for crop, p_info in treat_res["seed_conservation"].items():
        planted_sw = p_info["breakdown"]["planted_sw"]
        sw_seed_cost += planted_sw * SEED_PRICES.get(crop, 0.0)

    # Core seed cost delta
    treat_core_seed_cost = sum(t_led["seed_purchases_cost"].values()) - sw_seed_cost
    ctrl_seed_cost = sum(c_led["seed_purchases_cost"].values())
    core_seed_cost_delta = round(treat_core_seed_cost - ctrl_seed_cost, 2)

    # 3. Animal Revenue & Expense Deltas
    treat_animal_rev = sum(t_led["animal_sales_rev"].values())
    ctrl_animal_rev = sum(c_led["animal_sales_rev"].values())
    animal_rev_delta = round(treat_animal_rev - ctrl_animal_rev, 2)

    delta_feed_costs = round(t_led["feed_purchases_cost"] - c_led["feed_purchases_cost"], 2)
    delta_fertilizer_costs = round(t_led["fertilizer_purchases_cost"] - c_led["fertilizer_purchases_cost"], 2)
    delta_animal_purchases = round(
        sum(t_led["animal_purchases_cost"].values()) - sum(c_led["animal_purchases_cost"].values()), 2
    )

    # 4. Labor Deltas
    delta_hiring_costs = round(t_led["hiring_costs"] - c_led["hiring_costs"], 2)
    delta_wages_paid = round(t_led["wages_paid"] - c_led["wages_paid"], 2)

    # 5. SW Net Margin
    sw_net_margin = round(sw_crop_rev - sw_land_cost - sw_seed_cost, 2)

    # 6. Mathematically Closed Paired Cash Waterfall:
    # Delta Cash = SW Net + Core Crop Rev Delta - Core Seed Cost Delta + Animal Rev Delta
    #              - Feed Delta - Fert Delta - Animal Purchase Delta - Hiring Delta - Wages Delta
    accounted_delta = round(
        sw_net_margin
        + core_crop_revenue_delta
        - core_seed_cost_delta
        + animal_rev_delta
        - delta_feed_costs
        - delta_fertilizer_costs
        - delta_animal_purchases
        - delta_hiring_costs
        - delta_wages_paid,
        2,
    )
    waterfall_residual = round(paired_delta - accounted_delta, 2)
    assert abs(waterfall_residual) < 0.05, f"Waterfall residual in {pair_id}: {waterfall_residual}"

    print(f"Completed {pair_id}: C=${c_cash:.0f} T=${t_cash:.0f} Delta=${paired_delta:+.0f} | Waterfall Res: ${waterfall_residual:.2f}")

    return {
        "pair_id": pair_id,
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "control_cash": c_cash,
        "treatment_cash": t_cash,
        "paired_delta": paired_delta,
        "control_win": ctrl_res["outcome"]["win"],
        "treatment_win": treat_res["outcome"]["win"],
        "sw_purchased": t_led["land_purchases_count"] > 0,
        "cash_waterfall": {
            "observed_paired_delta": paired_delta,
            "sw_crop_revenue": sw_crop_rev,
            "sw_land_cost": sw_land_cost,
            "sw_seed_cost": sw_seed_cost,
            "sw_net_margin": sw_net_margin,
            "core_crop_revenue_delta": core_crop_revenue_delta,
            "core_crop_delta_by_crop": core_crop_delta_by_crop,
            "core_seed_cost_delta": core_seed_cost_delta,
            "animal_revenue_delta": animal_rev_delta,
            "feed_expenditure_delta": delta_feed_costs,
            "fertilizer_expenditure_delta": delta_fertilizer_costs,
            "animal_purchase_delta": delta_animal_purchases,
            "labor_hiring_delta": delta_hiring_costs,
            "labor_wages_delta": delta_wages_paid,
            "accounted_delta": accounted_delta,
            "waterfall_residual": waterfall_residual,
            "zero_residual_verified": abs(waterfall_residual) < 0.05,
        },
        "sw_lifecycle_stages": treat_res["sw_lifecycle"],
        "inventory_conservation": {
            "control": ctrl_res["inventory_conservation"],
            "treatment": treat_res["inventory_conservation"],
        },
        "worker_telemetry_comparison": {
            "control": ctrl_res["worker_telemetry"],
            "treatment": treat_res["worker_telemetry"],
        },
        "storage_discard_comparison": {
            "control": ctrl_res["storage_safety"],
            "treatment": treat_res["storage_safety"],
        },
        "latency_audit": {
            "control_max_latency_ms": ctrl_res["outcome"]["max_latency_ms"],
            "treatment_max_latency_ms": treat_res["outcome"]["max_latency_ms"],
            "treatment_mean_latency_ms": treat_res["outcome"]["mean_latency_ms"],
            "treatment_p95_latency_ms": treat_res["outcome"]["p95_latency_ms"],
            "treatment_p99_latency_ms": treat_res["outcome"]["p99_latency_ms"],
            "act_timeout_ms": 1000.0,
            "compliant": treat_res["outcome"]["latency_compliant"] and ctrl_res["outcome"]["latency_compliant"],
        },
        "control_full": ctrl_res,
        "treatment_full": treat_res,
    }


def main():
    print("================================================================================")
    print("PHASE SW-B3A-R1: TRANSACTION LEDGER & CAUSAL TELEMETRY INTEGRITY TOURNAMENT")
    print("================================================================================")
    os.makedirs(_OUT_DIR, exist_ok=True)

    tasks = []
    for s in CANARY_SEEDS:
        for opp in CANONICAL_OPPONENTS:
            for seat in SEATS:
                tasks.append((s, opp, seat))

    workers = min(7, mp.cpu_count())
    print(f"Executing 20 matched pairs (40 matches) across {workers} parallel processes...\n")

    t0 = time.time()
    with mp.Pool(processes=workers) as pool:
        paired_results = pool.starmap(run_paired_audited_cell, tasks)
    elapsed = time.time() - t0

    print(f"\nTournament complete in {elapsed:.1f}s ({elapsed / len(paired_results):.2f}s per pair avg).")

    # 1. Parity Check Against Gate 2
    parity_records = []
    all_parity_matched = True
    if os.path.exists(_GATE2_RESULTS_PATH):
        with open(_GATE2_RESULTS_PATH, "r", encoding="utf-8") as f:
            gate2_data = {p["pair_id"]: p for p in json.load(f)}

        for p in paired_results:
            pid = p["pair_id"]
            if pid in gate2_data:
                g2_c = gate2_data[pid]["control_cash"]
                g2_t = gate2_data[pid]["treatment_cash"]
                c_diff = abs(p["control_cash"] - g2_c)
                t_diff = abs(p["treatment_cash"] - g2_t)
                is_match = (c_diff < 1e-4 and t_diff < 1e-4)
                if not is_match:
                    all_parity_matched = False
                parity_records.append({
                    "pair_id": pid,
                    "control_cash": p["control_cash"],
                    "gate2_control_cash": g2_c,
                    "control_diff": round(c_diff, 4),
                    "treatment_cash": p["treatment_cash"],
                    "gate2_treatment_cash": g2_t,
                    "treatment_diff": round(t_diff, 4),
                    "exact_parity": is_match,
                })
        print(f"\n>>> Gate 2 Parity Verification: {'100% EXACT PARITY (40/40 MATCHES)' if all_parity_matched else 'PARITY MISMATCH!'} <<<")
    else:
        print(f"\nWarning: Gate 2 reference file not found at {_GATE2_RESULTS_PATH}")

    # 2. Descriptive Panel Statistics (Seed 97013, Seed 97014, Pooled)
    s97013_pairs = [p for p in paired_results if p["seed"] == 97013]
    s97014_pairs = [p for p in paired_results if p["seed"] == 97014]

    s97013_deltas = [p["paired_delta"] for p in s97013_pairs]
    s97014_deltas = [p["paired_delta"] for p in s97014_pairs]
    all_deltas = [p["paired_delta"] for p in paired_results]

    ctrl_cashes = [p["control_cash"] for p in paired_results]
    treat_cashes = [p["treatment_cash"] for p in paired_results]

    stats_summary = {
        "sample_structure": "Panel of 20 pairs across 2 independent seed clusters (10 pairs per seed). Descriptive only; small sample precludes asymptotic clustered hypothesis testing.",
        "pooled": {
            "pairs": len(paired_results),
            "control_mean_cash": round(float(np.mean(ctrl_cashes)), 2),
            "treatment_mean_cash": round(float(np.mean(treat_cashes)), 2),
            "mean_paired_delta": round(float(np.mean(all_deltas)), 2),
            "median_paired_delta": round(float(np.median(all_deltas)), 2),
            "std_paired_delta": round(float(np.std(all_deltas, ddof=1)), 2),
            "min_paired_delta": round(float(np.min(all_deltas)), 2),
            "max_paired_delta": round(float(np.max(all_deltas)), 2),
            "record": f"{sum(1 for d in all_deltas if d > 0)}W / {sum(1 for d in all_deltas if d < 0)}L / {sum(1 for d in all_deltas if d == 0)}T",
            "purchasing_pairs": sum(1 for p in paired_results if p["sw_purchased"]),
            "purchasing_mean_delta": round(float(np.mean([p["paired_delta"] for p in paired_results if p["sw_purchased"]])), 2),
        },
        "seed_97013": {
            "pairs": len(s97013_pairs),
            "control_mean_cash": round(float(np.mean([p["control_cash"] for p in s97013_pairs])), 2),
            "treatment_mean_cash": round(float(np.mean([p["treatment_cash"] for p in s97013_pairs])), 2),
            "mean_paired_delta": round(float(np.mean(s97013_deltas)), 2),
            "median_paired_delta": round(float(np.median(s97013_deltas)), 2),
            "std_paired_delta": round(float(np.std(s97013_deltas, ddof=1)), 2),
            "record": f"{sum(1 for d in s97013_deltas if d > 0)}W / {sum(1 for d in s97013_deltas if d < 0)}L / {sum(1 for d in s97013_deltas if d == 0)}T",
        },
        "seed_97014": {
            "pairs": len(s97014_pairs),
            "control_mean_cash": round(float(np.mean([p["control_cash"] for p in s97014_pairs])), 2),
            "treatment_mean_cash": round(float(np.mean([p["treatment_cash"] for p in s97014_pairs])), 2),
            "mean_paired_delta": round(float(np.mean(s97014_deltas)), 2),
            "median_paired_delta": round(float(np.median(s97014_deltas)), 2),
            "std_paired_delta": round(float(np.std(s97014_deltas, ddof=1)), 2),
            "record": f"{sum(1 for d in s97014_deltas if d > 0)}W / {sum(1 for d in s97014_deltas if d < 0)}L / {sum(1 for d in s97014_deltas if d == 0)}T",
        },
    }

    # 3. Compile Deliverable Artifacts
    # Artifact 1: transaction_ledgers_40_matches.json
    all_transaction_ledgers = []
    for p in paired_results:
        all_transaction_ledgers.append({
            "match_id": f"{p['pair_id']}_control",
            "pair_id": p["pair_id"],
            "seed": p["seed"],
            "opponent": p["opponent"],
            "seat": p["seat"],
            "mode": "CONTROL",
            "cash_ledger": p["control_full"]["cash_ledger"],
            "cash_reconciliation": p["control_full"]["cash_reconciliation"],
        })
        all_transaction_ledgers.append({
            "match_id": f"{p['pair_id']}_treatment",
            "pair_id": p["pair_id"],
            "seed": p["seed"],
            "opponent": p["opponent"],
            "seat": p["seat"],
            "mode": "TREATMENT",
            "cash_ledger": p["treatment_full"]["cash_ledger"],
            "cash_reconciliation": p["treatment_full"]["cash_reconciliation"],
        })

    # Artifact 2: paired_waterfalls_20_pairs.json
    all_paired_waterfalls = []
    for p in paired_results:
        all_paired_waterfalls.append({
            "pair_id": p["pair_id"],
            "seed": p["seed"],
            "opponent": p["opponent"],
            "seat": p["seat"],
            "control_cash": p["control_cash"],
            "treatment_cash": p["treatment_cash"],
            "paired_delta": p["paired_delta"],
            "sw_purchased": p["sw_purchased"],
            "cash_waterfall": p["cash_waterfall"],
        })

    # Artifact 3: inventory_conservation_records.json
    all_inventory_records = []
    for p in paired_results:
        all_inventory_records.append({
            "pair_id": p["pair_id"],
            "control_crop_conservation": p["control_full"]["inventory_conservation"],
            "control_seed_conservation": p["control_full"]["seed_conservation"],
            "treatment_crop_conservation": p["treatment_full"]["inventory_conservation"],
            "treatment_seed_conservation": p["treatment_full"]["seed_conservation"],
        })

    # Artifact 4: worker_action_telemetry.json
    all_worker_telemetry = []
    for p in paired_results:
        all_worker_telemetry.append({
            "pair_id": p["pair_id"],
            "opponent": p["opponent"],
            "seat": p["seat"],
            "control": p["worker_telemetry_comparison"]["control"],
            "treatment": p["worker_telemetry_comparison"]["treatment"],
        })

    # Artifact 5: storage_discard_reconciliation.json
    all_storage_records = []
    for p in paired_results:
        all_storage_records.append({
            "pair_id": p["pair_id"],
            "control": p["storage_discard_comparison"]["control"],
            "treatment": p["storage_discard_comparison"]["treatment"],
        })

    # Artifact 6: sw_lifecycle_9stages.json
    all_sw_lifecycles = []
    for p in paired_results:
        all_sw_lifecycles.append({
            "pair_id": p["pair_id"],
            "sw_purchased": p["sw_purchased"],
            "lifecycle_stages": p["sw_lifecycle_stages"],
            "first_productive_plant_event": p["treatment_full"]["first_productive_plant_event"],
        })

    # Artifact 7: summary_report_data.json
    summary_report_data = {
        "phase": "SW-B3A-R1",
        "description": "Transaction Ledger & Causal Telemetry Integrity Tournament",
        "stats": stats_summary,
        "parity_audit": parity_records,
        "waterfalls_summary": {
            "mean_sw_net_margin": round(float(np.mean([p["cash_waterfall"]["sw_net_margin"] for p in paired_results])), 2),
            "mean_core_crop_delta": round(float(np.mean([p["cash_waterfall"]["core_crop_revenue_delta"] for p in paired_results])), 2),
            "mean_animal_rev_delta": round(float(np.mean([p["cash_waterfall"]["animal_revenue_delta"] for p in paired_results])), 2),
            "mean_feed_cost_delta": round(float(np.mean([p["cash_waterfall"]["feed_expenditure_delta"] for p in paired_results])), 2),
            "mean_hiring_cost_delta": round(float(np.mean([p["cash_waterfall"]["labor_hiring_delta"] for p in paired_results])), 2),
            "all_waterfalls_zero_residual": all(p["cash_waterfall"]["zero_residual_verified"] for p in paired_results),
        },
        "latency_audit_summary": {
            "act_timeout_ms": 1000.0,
            "all_matches_compliant": all(p["latency_audit"]["compliant"] for p in paired_results),
            "treatment_p95_latency_ms": round(float(np.mean([p["latency_audit"]["treatment_p95_latency_ms"] for p in paired_results])), 2),
            "treatment_max_latency_ms": round(float(np.max([p["latency_audit"]["treatment_max_latency_ms"] for p in paired_results])), 2),
        },
    }

    # Artifact 8: source_manifest.json
    source_manifest = get_source_manifest()

    # Save all 8 artifacts
    with open(os.path.join(_OUT_DIR, "transaction_ledgers_40_matches.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(all_transaction_ledgers), f, indent=2)

    with open(os.path.join(_OUT_DIR, "paired_waterfalls_20_pairs.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(all_paired_waterfalls), f, indent=2)

    with open(os.path.join(_OUT_DIR, "inventory_conservation_records.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(all_inventory_records), f, indent=2)

    with open(os.path.join(_OUT_DIR, "worker_action_telemetry.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(all_worker_telemetry), f, indent=2)

    with open(os.path.join(_OUT_DIR, "storage_discard_reconciliation.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(all_storage_records), f, indent=2)

    with open(os.path.join(_OUT_DIR, "sw_lifecycle_9stages.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(all_sw_lifecycles), f, indent=2)

    with open(os.path.join(_OUT_DIR, "summary_report_data.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(summary_report_data), f, indent=2)

    with open(os.path.join(_OUT_DIR, "source_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(to_serializable(source_manifest), f, indent=2)

    print(f"\nAll 8 JSON artifacts successfully emitted to {_OUT_DIR}.")
    print("\nSummary Statistics:")
    print(f"  Control Mean Cash   : ${stats_summary['pooled']['control_mean_cash']:,.2f}")
    print(f"  Treatment Mean Cash : ${stats_summary['pooled']['treatment_mean_cash']:,.2f}")
    print(f"  Mean Paired Delta   : ${stats_summary['pooled']['mean_paired_delta']:+,.2f}")
    print(f"  Record              : {stats_summary['pooled']['record']}")
    print(f"  All 40 Ledgers $0.00: True")
    print(f"  All 20 Waterfalls $0.00: {summary_report_data['waterfalls_summary']['all_waterfalls_zero_residual']}")
    print(f"  All Inventories Diff=0: True")


if __name__ == "__main__":
    main()
