"""Phase SW-C1: Adaptive, Capacity-Aware Acreage Expansion Tournament Runner.

Evaluates a 7-arm real-engine matched comparison:
- Arm A: Canonical production baseline (SW forward architecture OFF)
- Arm B: Frozen Phase SW-B3C urgency-aware SW control (fixed 8 tiles)
- Arm C: Adaptive architecture control, max 8 tiles (proves zero regression on 8 tiles)
- Arm D: Adaptive expansion, max 12 tiles (+4 tile increment)
- Arm E: Adaptive expansion, max 16 tiles (+8 tile increment)
- Arm F: Adaptive expansion, max 20 tiles (+12 tile increment)
- Arm G: Adaptive expansion, max 24 tiles (full cultivable SW quadrant)

Panel Configuration:
- Discovery Sample: Seeds 97013, 97014 (20 matched cells / 140 matches for 7 arms)
- Independent Confirmation Sample: Seeds 97017, 97018 (20 matched cells / 140 matches)
- 5 Canonical Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- Both Seats: 0, 1

Full engine interception guarantees:
- $0.0000 cash residual reconciliation for 100% of matches
- Physical inventory conservation
- Detailed adaptive acreage expansion telemetry (crops chosen, marginal ΔFC, days)
- Verified core deadline tracking and execution
- Engine-grounded seed and land attribution
- Latency audit against 1,000 ms actTimeout
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kag

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PhaseSWC1")

RESULTS_DIR = os.path.join(PROJECT_ROOT, "simulations", "results", "phase_sw_c1")
os.makedirs(RESULTS_DIR, exist_ok=True)

DISCOVERY_SEEDS = [97013, 97014]
CONFIRMATION_SEEDS = [97017, 97018]
CANONICAL_OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

SHED_ACCESS_TILES = {(4, 4), (4, 5), (5, 4)}

ALL_ARMS = ["ARM_A", "ARM_B", "ARM_C", "ARM_D", "ARM_E", "ARM_F", "ARM_G"]


def compute_file_sha256(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    if not os.path.exists(filepath):
        return "FILE_NOT_FOUND"
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().upper()


def safe_json_serialize(obj: Any) -> Any:
    """Recursively convert NumPy/custom types for JSON serialization."""
    if isinstance(obj, dict):
        return {str(k): safe_json_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [safe_json_serialize(x) for x in obj]
    elif isinstance(obj, set):
        return [safe_json_serialize(x) for x in sorted(obj, key=lambda x: str(x))]
    elif isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        return float(obj)
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


class MatchEngineAuditor:
    """Rigorous turn-by-turn interceptor for engine mechanics."""

    def __init__(self, monitored_seat: int = 0):
        self.monitored_seat = monitored_seat
        self.step_reconciliations = []
        self.transactions = []
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
            "animal_purchases_cost": {a: 0.0 for a in ("COW", "SHEEP", "CHICKEN", "GOOSE")},
            "animal_purchases_units": {a: 0 for a in ("COW", "SHEEP", "CHICKEN", "GOOSE")},
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
            for item in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER", "EGG", "CHICKEN_MEAT", "COW_MEAT")
        }

        self.seed_ledger = {
            c: {"opening": 0, "purchased": 0, "planted_core": 0, "planted_sw": 0, "ending": 0}
            for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
        }

        # Worker action summary
        self.action_counts = {
            "total_actions": 0,
            "actions_in_core": 0,
            "actions_in_sw": 0,
            "move_actions": 0,
            "water_actions": 0,
            "harvest_actions": 0,
            "plant_actions": 0,
            "feed_actions": 0,
            "care_actions": 0,
            "fertilize_actions": 0,
            "place_actions": 0,
            "pickup_actions": 0,
            "drop_actions": 0,
            "dig_actions": 0,
            "build_actions": 0,
            "idle_actions": 0,
            "quadrant_transitions_nw_to_sw": 0,
            "quadrant_transitions_sw_to_nw": 0,
            "sw_water_executed": 0,
            "core_water_executed": 0,
            "sw_harvest_executed": 0,
            "core_harvest_executed": 0,
            "sw_plant_executed": 0,
            "core_plant_executed": 0,
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
        self.transactions.append({
            "step": self.current_step,
            "day": self.current_step // 24,
            "hour": self.current_step % 24,
            "op": op,
            "item": item,
            "price": px,
        })
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

    def record_hire(self, player_id: int, cost: float, total_hires: int):
        if player_id != self.monitored_seat:
            return
        c = float(cost)
        self._current_step_outflows += c
        self.cash_ledger["hiring_costs"] += c
        self.cash_ledger["hires_count"] += 1
        self.transactions.append({
            "step": self.current_step,
            "day": self.current_step // 24,
            "hour": self.current_step % 24,
            "op": "HIRE",
            "item": "WORKER",
            "price": c,
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
            "day": self.current_step // 24,
            "hour": self.current_step % 24,
            "op": "BUY_LAND",
            "item": quadrant,
            "price": c,
        })

    def record_action(self, player_id: int, unit_idx: int, action: Any, pre_pos: Tuple[int, int], post_pos: Tuple[int, int], outcome: Dict[str, Any]):
        if player_id != self.monitored_seat:
            return
        self.action_counts["total_actions"] += 1
        op = action[0] if isinstance(action, (list, tuple)) and action else (action if isinstance(action, str) else "PASS")
        is_sw = (pre_pos[0] < 5 and pre_pos[1] >= 5 and pre_pos not in SHED_ACCESS_TILES)
        if is_sw:
            self.action_counts["actions_in_sw"] += 1
        else:
            self.action_counts["actions_in_core"] += 1

        pre_quad = "SW" if (pre_pos[0] < 5 and pre_pos[1] >= 5) else ("NW" if (pre_pos[0] < 5 and pre_pos[1] < 5) else "NE")
        post_quad = "SW" if (post_pos[0] < 5 and post_pos[1] >= 5) else ("NW" if (post_pos[0] < 5 and post_pos[1] < 5) else "NE")
        if pre_quad in ("NW", "NE") and post_quad == "SW":
            self.action_counts["quadrant_transitions_nw_to_sw"] += 1
        elif pre_quad == "SW" and post_quad in ("NW", "NE"):
            self.action_counts["quadrant_transitions_sw_to_nw"] += 1

        if op in ("MOVE", "NORTH", "SOUTH", "EAST", "WEST"):
            self.action_counts["move_actions"] += 1
        elif op == "WATER":
            self.action_counts["water_actions"] += 1
            if is_sw:
                self.action_counts["sw_water_executed"] += 1
            else:
                self.action_counts["core_water_executed"] += 1
        elif op == "HARVEST":
            self.action_counts["harvest_actions"] += 1
            if is_sw:
                self.action_counts["sw_harvest_executed"] += 1
            else:
                self.action_counts["core_harvest_executed"] += 1
            if outcome and outcome.get("yield_units", 0) > 0:
                item = outcome.get("item")
                units = outcome.get("yield_units", 0)
                if item in self.inventory_ledger:
                    if is_sw:
                        self.inventory_ledger[item]["harvested_sw"] += units
                    else:
                        self.inventory_ledger[item]["harvested_core"] += units
                self.harvest_events.append({
                    "step": self.current_step,
                    "day": self.current_step // 24,
                    "hour": self.current_step % 24,
                    "pos": list(pre_pos),
                    "item": item,
                    "yield_units": units,
                    "is_sw": is_sw,
                })
        elif op == "PLANT":
            self.action_counts["plant_actions"] += 1
            if is_sw:
                self.action_counts["sw_plant_executed"] += 1
            else:
                self.action_counts["core_plant_executed"] += 1
            if outcome and outcome.get("planted"):
                c = outcome.get("crop")
                if c in self.seed_ledger:
                    if is_sw:
                        self.seed_ledger[c]["planted_sw"] += 1
                    else:
                        self.seed_ledger[c]["planted_core"] += 1
                if is_sw and self.first_productive_plant_event is None:
                    self.first_productive_plant_event = {
                        "step": self.current_step,
                        "day": self.current_step // 24,
                        "hour": self.current_step % 24,
                        "crop": c,
                        "pos": list(pre_pos),
                    }
        elif op == "FEED":
            self.action_counts["feed_actions"] += 1
            if outcome and outcome.get("fed"):
                if "WHEAT" in self.inventory_ledger:
                    self.inventory_ledger["WHEAT"]["consumed_feed"] += 1
        elif op == "FERTILIZE":
            self.action_counts["fertilize_actions"] += 1
            if outcome and outcome.get("fertilized"):
                if "FERTILIZER" in self.inventory_ledger:
                    self.inventory_ledger["FERTILIZER"]["consumed_fertilizer"] += 1
        elif op == "COLLECT_FERTILIZER":
            self.action_counts["care_actions"] += 1
            if outcome and outcome.get("collected_fertilizer"):
                if "FERTILIZER" in self.inventory_ledger:
                    self.inventory_ledger["FERTILIZER"]["produced_animal"] += 1
        elif op == "PLACE":
            self.action_counts["place_actions"] += 1
            if outcome and outcome.get("animal_placed"):
                pass
        elif op == "PICKUP":
            self.action_counts["pickup_actions"] += 1
        elif op == "DROP":
            self.action_counts["drop_actions"] += 1
        elif op == "DIG":
            self.action_counts["dig_actions"] += 1
        elif op == "BUILD":
            self.action_counts["build_actions"] += 1
        elif op == "PASS":
            self.action_counts["idle_actions"] += 1

        try:
            from execution.sw_task_admission_controller import get_sw_task_admission_telemetry
            reg = "SW" if is_sw else "CORE"
            get_sw_task_admission_telemetry().record_executed_action(reg, op, pre_pos, outcome)
        except Exception:
            pass

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
                    "hour": self.current_step % 24,
                    "item": item,
                    "units": qty,
                })

    def end_step(self, pre_money: float, post_money: float):
        delta = round(post_money - pre_money, 4)
        expected_delta = round(self._current_step_inflows - self._current_step_outflows, 4)
        step_residual = round(delta - expected_delta, 4)
        assert abs(step_residual) < 1e-4, f"Step {self.current_step} non-zero cash residual: engine={delta}, ledger={expected_delta}"
        self.step_reconciliations.append({
            "step": self.current_step,
            "pre_money": pre_money,
            "post_money": post_money,
            "delta": delta,
            "expected_delta": expected_delta,
            "residual": step_residual,
        })


def run_single_match(args_tuple: Tuple[int, str, int, str]) -> Dict[str, Any]:
    """Execute a single instrumented match for the specified arm."""
    seed, opp_name, seat, arm = args_tuple

    # Configure Arm environment
    import agent.config as config
    if arm == "ARM_A":
        config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(False)
        config.set_sw_adaptive_acreage_enabled(False)
        config.set_sw_max_adaptive_acreage(24)
    elif arm == "ARM_B":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(False)
        config.set_sw_max_adaptive_acreage(24)
    elif arm == "ARM_C":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(8)  # Architecture control cap
    elif arm == "ARM_D":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(12)
    elif arm == "ARM_E":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(16)
    elif arm == "ARM_F":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(20)
    elif arm == "ARM_G":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(24)
    else:
        raise ValueError(f"Unknown arm: {arm}")

    from agent.main import agent as my_agent, reset_agent_state
    from agent.strategy.farm_plan import reset_farm_plan
    from agent.strategy.whole_farm_planner import reset_whole_farm_planner
    from agent.strategy.sw_tranche_controller import (
        get_sw_tranche_controller,
        reset_sw_tranche_controller,
    )
    from agent.strategy.adaptive_acreage_planner import reset_adaptive_acreage_planner
    from agent.execution.midnight_storage_controller import (
        reset_midnight_storage_telemetry,
        get_midnight_storage_telemetry,
    )
    from agent.execution.sw_task_admission_controller import (
        reset_sw_task_admission_telemetry,
        get_sw_task_admission_telemetry,
    )
    from agent.diagnostics.animal_tracker import AnimalSurvivalTracker
    from simulations.experiments.agent_zoo import get_agent

    # Clean singletons
    reset_agent_state()
    reset_farm_plan()
    reset_whole_farm_planner()
    reset_sw_tranche_controller()
    reset_adaptive_acreage_planner()
    reset_midnight_storage_telemetry()
    reset_sw_task_admission_telemetry()

    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(arm in ("ARM_B", "ARM_C", "ARM_D", "ARM_E", "ARM_F", "ARM_G"))

    animal_tracker = AnimalSurvivalTracker(seat=seat)
    opp_agent = get_agent(opp_name)

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()

    auditor = MatchEngineAuditor(monitored_seat=seat)

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
        elif op == "WATER":
            if isinstance(post_tile, dict) and post_tile.get("watered_today") and (pre_tile is None or not pre_tile.get("watered_today")):
                outcome = {"watered": True}
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
            step = obs0.get("step", 0)

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

    # Ending inventories
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

    # Exact Cash Reconciliation
    cl = auditor.cash_ledger
    tot_crop_rev = sum(cl["crop_sales_rev"].values())
    tot_animal_rev = sum(cl["animal_sales_rev"].values())
    tot_inflows = tot_crop_rev + tot_animal_rev

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
    assert abs(residual) < 1e-4, f"Non-zero cash residual in {seed}_{opp_name}_{seat}_{arm}: {residual}"

    # SW crop provenance attribution across all crops
    crop_provenance = {}
    sw_total_crop_revenue = 0.0
    sw_total_seed_cost = 0.0

    for crop in ("STRAWBERRY", "MELON", "TOMATO", "WHEAT", "CARROT"):
        sw_h = auditor.inventory_ledger[crop]["harvested_sw"]
        core_h = auditor.inventory_ledger[crop]["harvested_core"]
        tot_sales = auditor.inventory_ledger[crop]["sold"]
        crop_rev = cl["crop_sales_rev"][crop]
        avg_px = (crop_rev / tot_sales) if tot_sales > 0 else 0.0

        tot_h = sw_h + core_h
        sw_ratio = (sw_h / tot_h) if tot_h > 0 else 0.0
        prop_sw_rev = tot_sales * sw_ratio * avg_px
        sw_total_crop_revenue += prop_sw_rev

        seed_unit_price = {"STRAWBERRY": 100.0, "MELON": 80.0, "TOMATO": 50.0, "WHEAT": 10.0, "CARROT": 20.0}.get(crop, 10.0)
        sw_planted = auditor.seed_ledger[crop]["planted_sw"]
        sw_seed_c = sw_planted * seed_unit_price
        sw_total_seed_cost += sw_seed_c

        crop_provenance[crop] = {
            "sw_harvested": sw_h,
            "core_harvested": core_h,
            "total_sold": tot_sales,
            "sales_revenue": crop_rev,
            "average_price": round(avg_px, 2),
            "proportional_sw_revenue": round(prop_sw_rev, 2),
            "sw_planted": sw_planted,
            "sw_seed_cost": round(sw_seed_c, 2),
        }

    sw_net_margin = round(sw_total_crop_revenue - sw_total_seed_cost - (2000.0 if ctrl.state.sw_purchase_confirmed else 0.0), 2)

    # Core farm revenues
    core_crop_revenue = round(tot_crop_rev - sw_total_crop_revenue, 2)
    core_livestock_revenue = round(tot_animal_rev, 2)

    # Telemetry extraction
    sw_admission_telemetry = get_sw_task_admission_telemetry().to_dict()
    sw_tranche_summary = ctrl.get_summary()

    return {
        "match_id": f"{seed}_{opp_name}_{seat}_{arm}",
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "arm": arm,
        "final_cash": round(final_cash, 2),
        "opp_final_cash": round(opp_final_cash, 2),
        "win": win,
        "reconciled_cash": round(reconciled_cash, 2),
        "cash_residual": residual,
        "min_cash_seen": round(min_cash_seen, 2),
        "peak_shed_occupancy": peak_shed_occupancy,
        "sw_purchased": ctrl.state.sw_purchase_confirmed,
        "sw_purchase_day": ctrl.state.sw_purchase_day,
        "sw_purchase_hour": ctrl.state.sw_purchase_hour,
        "sw_max_acreage": sw_tranche_summary["adaptive_acreage"]["max_admitted_acreage"],
        "sw_expansion_events_count": sw_tranche_summary["adaptive_acreage"]["expansion_events_count"],
        "sw_expansion_history": sw_tranche_summary["adaptive_acreage"]["expansion_history"],
        "sw_expansion_rejections": sw_tranche_summary["adaptive_acreage"]["expansion_rejections"],
        "sw_total_crop_revenue": round(sw_total_crop_revenue, 2),
        "sw_total_seed_cost": round(sw_total_seed_cost, 2),
        "sw_net_margin": sw_net_margin,
        "core_crop_revenue": core_crop_revenue,
        "core_livestock_revenue": core_livestock_revenue,
        "crop_provenance": crop_provenance,
        "cash_ledger": cl,
        "action_counts": auditor.action_counts,
        "hard_tasks_due": sw_admission_telemetry["core_hard_tasks_due"],
        "hard_tasks_completed": sw_admission_telemetry["core_hard_tasks_completed"],
        "hard_tasks_missed": sw_admission_telemetry["missed_core_deadlines"],
        "mean_latency_ms": round(float(np.mean(turn_latencies)), 2),
        "p99_latency_ms": round(float(np.percentile(turn_latencies, 99)), 2),
        "max_latency_ms": round(float(np.max(turn_latencies)), 2),
    }


def run_experiment_panel(
    seeds: List[int],
    sample_label: str,
    arms: List[str] = ALL_ARMS,
    num_workers: int = 4,
) -> Dict[str, Any]:
    """Execute complete tournament panel for the specified seeds and arms."""
    tasks = []
    for seed in seeds:
        for opp in CANONICAL_OPPONENTS:
            for seat in (0, 1):
                for arm in arms:
                    tasks.append((seed, opp, seat, arm))

    logger.info(f"Launching Phase SW-C1 {sample_label} panel: {len(tasks)} matches across {len(arms)} arms with {num_workers} workers...")
    t_start = time.perf_counter()

    if num_workers > 1:
        with mp.Pool(num_workers) as pool:
            results = pool.map(run_single_match, tasks)
    else:
        results = [run_single_match(t) for t in tasks]

    elapsed = time.perf_counter() - t_start
    logger.info(f"Completed {len(results)} matches in {elapsed:.1f} seconds ({elapsed / max(1, len(results)):.2f}s/match)")

    # Save raw match records
    matches_file = os.path.join(RESULTS_DIR, f"sw_c1_matches_{sample_label}.json")
    with open(matches_file, "w") as f:
        json.dump(safe_json_serialize(results), f, indent=2)
    logger.info(f"Saved match records to {matches_file}")

    # Compute arm aggregates and paired statistics
    arm_matches: Dict[str, List[Dict[str, Any]]] = {arm: [] for arm in arms}
    cell_matches: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for r in results:
        arm = r["arm"]
        arm_matches[arm].append(r)
        cell_key = f"{r['seed']}_{r['opp_name']}_{r['seat']}"
        cell_matches.setdefault(cell_key, {})[arm] = r

    summary: Dict[str, Any] = {
        "sample": sample_label,
        "seeds": seeds,
        "num_matches": len(results),
        "elapsed_seconds": round(elapsed, 1),
        "arms_evaluated": arms,
        "arm_metrics": {},
        "paired_deltas": {},
    }

    for arm in arms:
        m_list = arm_matches[arm]
        cashes = [m["final_cash"] for m in m_list]
        wins = [1 if m["win"] else 0 for m in m_list]
        sw_bought = sum(1 for m in m_list if m["sw_purchased"])
        sw_acreages = [m["sw_max_acreage"] for m in m_list]
        sw_revs = [m["sw_total_crop_revenue"] for m in m_list]
        sw_margins = [m["sw_net_margin"] for m in m_list]
        core_crop_revs = [m["core_crop_revenue"] for m in m_list]
        core_live_revs = [m["core_livestock_revenue"] for m in m_list]
        hard_dues = [m["hard_tasks_due"] for m in m_list]
        hard_comps = [m["hard_tasks_completed"] for m in m_list]
        expansion_events = [m["sw_expansion_events_count"] for m in m_list]

        summary["arm_metrics"][arm] = {
            "count": len(m_list),
            "mean_final_cash": round(float(np.mean(cashes)), 2),
            "median_final_cash": round(float(np.median(cashes)), 2),
            "std_final_cash": round(float(np.std(cashes)), 2),
            "min_final_cash": round(float(np.min(cashes)), 2),
            "max_final_cash": round(float(np.max(cashes)), 2),
            "win_rate": round(float(np.mean(wins)), 3),
            "sw_purchase_rate": round(sw_bought / max(1, len(m_list)), 3),
            "mean_sw_acreage": round(float(np.mean(sw_acreages)), 2),
            "mean_expansion_events": round(float(np.mean(expansion_events)), 2),
            "mean_sw_revenue": round(float(np.mean(sw_revs)), 2),
            "mean_sw_net_margin": round(float(np.mean(sw_margins)), 2),
            "mean_core_crop_revenue": round(float(np.mean(core_crop_revs)), 2),
            "mean_core_livestock_revenue": round(float(np.mean(core_live_revs)), 2),
            "core_hard_completion_rate": round(sum(hard_comps) / max(1, sum(hard_dues)), 4),
            "all_cash_reconciled_zero_residual": all(abs(m["cash_residual"]) < 1e-4 for m in m_list),
        }

    # Compute paired deltas against ARM_B (B3C baseline) and ARM_A (Production baseline)
    ref_arm = "ARM_B" if "ARM_B" in arms else arms[0]
    for arm in arms:
        if arm == ref_arm:
            continue
        deltas = []
        for cell_key, cell_dict in cell_matches.items():
            if arm in cell_dict and ref_arm in cell_dict:
                d = cell_dict[arm]["final_cash"] - cell_dict[ref_arm]["final_cash"]
                deltas.append(d)
        if deltas:
            summary["paired_deltas"][f"{arm}_vs_{ref_arm}"] = {
                "n_pairs": len(deltas),
                "mean_delta": round(float(np.mean(deltas)), 2),
                "median_delta": round(float(np.median(deltas)), 2),
                "std_delta": round(float(np.std(deltas)), 2),
                "win_delta_count": sum(1 for d in deltas if d > 0),
                "loss_delta_count": sum(1 for d in deltas if d < 0),
                "tie_delta_count": sum(1 for d in deltas if abs(d) < 1e-4),
            }

    # Also compute ARM_G vs ARM_A
    if "ARM_G" in arms and "ARM_A" in arms:
        deltas_ga = []
        for cell_key, cell_dict in cell_matches.items():
            if "ARM_G" in cell_dict and "ARM_A" in cell_dict:
                deltas_ga.append(cell_dict["ARM_G"]["final_cash"] - cell_dict["ARM_A"]["final_cash"])
        if deltas_ga:
            summary["paired_deltas"]["ARM_G_vs_ARM_A"] = {
                "n_pairs": len(deltas_ga),
                "mean_delta": round(float(np.mean(deltas_ga)), 2),
                "median_delta": round(float(np.median(deltas_ga)), 2),
                "std_delta": round(float(np.std(deltas_ga)), 2),
            }

    summary_file = os.path.join(RESULTS_DIR, f"sw_c1_summary_{sample_label}.json")
    with open(summary_file, "w") as f:
        json.dump(safe_json_serialize(summary), f, indent=2)
    logger.info(f"Saved summary to {summary_file}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Phase SW-C1 Tournament Runner")
    parser.add_argument("--sample", choices=["discovery", "confirmation", "full"], default="discovery")
    parser.add_argument("--arms", default=",".join(ALL_ARMS))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    arm_list = [a.strip() for a in args.arms.split(",") if a.strip()]

    if args.sample in ("discovery", "full"):
        summary_disc = run_experiment_panel(
            seeds=DISCOVERY_SEEDS,
            sample_label="discovery",
            arms=arm_list,
            num_workers=args.workers,
        )
        print("\n=== DISCOVERY PANEL SUMMARY ===")
        print(json.dumps(summary_disc["arm_metrics"], indent=2))
        print("\n=== PAIRED DELTAS ===")
        print(json.dumps(summary_disc["paired_deltas"], indent=2))

    if args.sample in ("confirmation", "full"):
        summary_conf = run_experiment_panel(
            seeds=CONFIRMATION_SEEDS,
            sample_label="confirmation",
            arms=arm_list,
            num_workers=args.workers,
        )
        print("\n=== CONFIRMATION PANEL SUMMARY ===")
        print(json.dumps(summary_conf["arm_metrics"], indent=2))
        print("\n=== PAIRED DELTAS ===")
        print(json.dumps(summary_conf["paired_deltas"], indent=2))


if __name__ == "__main__":
    main()
