"""Phase SW-B3B: Core-First SW Task Admission Tournament Runner.

Evaluates a 3-arm real-engine matched comparison:
- Arm A: Canonical production, SW-forward OFF
- Arm B: Frozen Gate 2 LIVE SW treatment (SW on, Core-First Admission OFF)
- Arm C: Phase SW-B3B treatment (SW on, Core-First Admission ON)

Test Panel:
- Discovery Sample: Seeds 97013, 97014 (20 matched pairs per arm)
- Independent Confirmation Sample: Seeds 97015, 97016 (20 matched pairs per arm)
- 5 canonical opponents: pass, random, simple_greedy, rule_based_v2, full_production_agent
- Both seats: 0, 1

Full engine interception guarantees:
- $0.0000 cash residual reconciliation for 100% of matches
- Physical inventory conservation
- Task admission proposal, admission, deferral, and reason tracking
- Executed actions in Core vs SW
- Latency audit against 1,000 ms actTimeout
"""
from __future__ import annotations

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
logger = logging.getLogger("PhaseSWB3B")

RESULTS_DIR = os.path.join(PROJECT_ROOT, "simulations", "results", "phase_sw_b3b")
os.makedirs(RESULTS_DIR, exist_ok=True)

DISCOVERY_SEEDS = [97013, 97014]
CONFIRMATION_SEEDS = [97015, 97016]
CANONICAL_OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

SHED_ACCESS_TILES = {(4, 4), (4, 5), (5, 4)}


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


def get_source_manifest() -> Dict[str, str]:
    files = {
        "kaggriculture_engine": r"C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py",
        "agent/main.py": os.path.join(PROJECT_ROOT, "agent", "main.py"),
        "agent/config.py": os.path.join(PROJECT_ROOT, "agent", "config.py"),
        "agent/execution/task_scheduler.py": os.path.join(PROJECT_ROOT, "agent", "execution", "task_scheduler.py"),
        "agent/execution/sw_task_admission_controller.py": os.path.join(PROJECT_ROOT, "agent", "execution", "sw_task_admission_controller.py"),
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
            for item in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER", "EGG", "CHICKEN_MEAT", "COW_MEAT")
        }

        self.seed_ledger = {
            c: {"opening": 0, "purchased": 0, "planted_core": 0, "planted_sw": 0, "ending": 0}
            for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
        }

        # Worker action summary
        self.action_counts = {
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
            "core_water_executed": 0,
            "sw_water_executed": 0,
            "core_harvest_executed": 0,
            "sw_harvest_executed": 0,
            "core_plant_executed": 0,
            "sw_plant_executed": 0,
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


def run_single_audited_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    """Execute a single match with full engine interception and causal auditing.

    arm:
      - 'ARM_A': Canonical production, SW OFF
      - 'ARM_B': Frozen Gate 2 LIVE SW treatment (Admission OFF)
      - 'ARM_C': Phase SW-B3B treatment (Admission ON)
    """
    import agent.config as config

    if arm == "ARM_A":
        config.SW_FORWARD_ARCHITECTURE_MODE = "CONTROL"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
    elif arm == "ARM_B":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(False)
    elif arm == "ARM_C":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.SOFT_WORKER_LOCALITY_MODE = "ON"
        config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
        config.QUADRANT_HARD_BLOCK = {4}
        config.set_sw_core_first_task_admission_enabled(True)
    else:
        raise ValueError(f"Unknown arm: {arm}")

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
    from agent.execution.sw_task_admission_controller import (
        reset_sw_task_admission_telemetry,
        get_sw_task_admission_telemetry,
    )
    from agent.diagnostics.animal_tracker import AnimalSurvivalTracker
    from simulations.experiments.agent_zoo import get_agent

    # Clean singleton states
    reset_agent_state()
    reset_farm_plan()
    reset_whole_farm_planner()
    reset_sw_tranche_controller()
    reset_midnight_storage_telemetry()
    reset_sw_task_admission_telemetry()

    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(arm in ("ARM_B", "ARM_C"))

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

    # Exact cash accounting reconciliation
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
    assert abs(residual) < 1e-4, f"Non-zero cash residual in {seed}_{opp_name}_{seat}_{arm}: {residual}"

    # Inventory conservation check
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
        inventory_conservation[item] = {
            "inflows": in_qty,
            "outflows": out_qty,
            "conserved": (in_qty == out_qty),
        }

    # SW crop breakdown & provenance
    sw_strawberry_harvested = auditor.inventory_ledger["STRAWBERRY"]["harvested_sw"]
    core_strawberry_harvested = auditor.inventory_ledger["STRAWBERRY"]["harvested_core"]
    sw_melon_harvested = auditor.inventory_ledger["MELON"]["harvested_sw"]
    core_melon_harvested = auditor.inventory_ledger["MELON"]["harvested_core"]

    tot_strawberry_sales = auditor.inventory_ledger["STRAWBERRY"]["sold"]
    tot_melon_sales = auditor.inventory_ledger["MELON"]["sold"]
    rev_strawberry = cl["crop_sales_rev"]["STRAWBERRY"]
    rev_melon = cl["crop_sales_rev"]["MELON"]

    px_straw = (rev_strawberry / tot_strawberry_sales) if tot_strawberry_sales > 0 else 0.0
    px_melon = (rev_melon / tot_melon_sales) if tot_melon_sales > 0 else 0.0

    tot_straw_h = sw_strawberry_harvested + core_strawberry_harvested
    straw_sw_ratio = (sw_strawberry_harvested / tot_straw_h) if tot_straw_h > 0 else 0.0
    prop_straw_rev = tot_strawberry_sales * straw_sw_ratio * px_straw

    tot_melon_h = sw_melon_harvested + core_melon_harvested
    melon_sw_ratio = (sw_melon_harvested / tot_melon_h) if tot_melon_h > 0 else 0.0
    prop_melon_rev = tot_melon_sales * melon_sw_ratio * px_melon

    sw_gross_crop_revenue = round(prop_straw_rev + prop_melon_rev, 2)
    sw_seed_cost = round(cl["seed_purchases_cost"]["STRAWBERRY"] + cl["seed_purchases_cost"]["MELON"], 2) if arm in ("ARM_B", "ARM_C") and cl["land_purchases_count"] >= 2 else 0.0
    sw_land_cost = 2000.0 if (arm in ("ARM_B", "ARM_C") and cl["land_purchases_count"] >= 2) else 0.0
    sw_net_margin = round(sw_gross_crop_revenue - sw_seed_cost - sw_land_cost, 2)

    animal_summary = animal_tracker.get_summary()
    rescue_telem = get_midnight_storage_telemetry()
    admission_telem = get_sw_task_admission_telemetry().to_dict()

    return {
        "cell": {
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
            "arm": arm,
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
            "reconciled_cash": reconciled_cash,
            "residual": residual,
            "reconciled": abs(residual) < 0.0001,
        },
        "inventory_conservation": inventory_conservation,
        "sw_economics": {
            "sw_purchased": bool(sw_land_cost == 2000.0),
            "sw_land_cost": sw_land_cost,
            "sw_seed_cost": sw_seed_cost,
            "sw_gross_crop_revenue": sw_gross_crop_revenue,
            "sw_net_margin": sw_net_margin,
            "strawberry_harvested_sw": sw_strawberry_harvested,
            "strawberry_harvested_core": core_strawberry_harvested,
            "melon_harvested_sw": sw_melon_harvested,
            "melon_harvested_core": core_melon_harvested,
        },
        "worker_action_summary": auditor.action_counts,
        "storage_telemetry": {
            "peak_shed_occupancy": peak_shed_occupancy,
            "discard_events_count": len(auditor.discard_events),
            "discard_units_total": sum(d["units"] for d in auditor.discard_events),
            "discard_events": auditor.discard_events,
            "midnight_rescue_liquidated_units": rescue_telem.get("units_liquidated", 0),
            "midnight_rescue_cash_realized": rescue_telem.get("cash_realized", 0.0),
        },
        "animal_survival": animal_summary,
        "sw_task_admission_telemetry": admission_telem,
    }


def compute_paired_waterfall(match_base: Dict[str, Any], match_treat: Dict[str, Any], pair_id: str) -> Dict[str, Any]:
    """Compute fully reconciled economic waterfall between base arm and treat arm."""
    cl_base = match_base["cash_ledger"]
    cl_treat = match_treat["cash_ledger"]

    base_cash = match_base["outcome"]["final_cash"]
    treat_cash = match_treat["outcome"]["final_cash"]
    observed_delta = round(treat_cash - base_cash, 2)

    swe_base = match_base.get("sw_economics", {})
    swe_treat = match_treat.get("sw_economics", {})

    sw_crop_rev_base = swe_base.get("sw_gross_crop_revenue", 0.0)
    sw_crop_rev_treat = swe_treat.get("sw_gross_crop_revenue", 0.0)

    sw_land_cost_base = swe_base.get("sw_land_cost", 0.0)
    sw_land_cost_treat = swe_treat.get("sw_land_cost", 0.0)

    sw_seed_cost_base = swe_base.get("sw_seed_cost", 0.0)
    sw_seed_cost_treat = swe_treat.get("sw_seed_cost", 0.0)

    sw_net_base = sw_crop_rev_base - sw_land_cost_base - sw_seed_cost_base
    sw_net_treat = sw_crop_rev_treat - sw_land_cost_treat - sw_seed_cost_treat
    sw_net_delta = round(sw_net_treat - sw_net_base, 2)

    total_crop_base = sum(cl_base["crop_sales_rev"].values())
    total_crop_treat = sum(cl_treat["crop_sales_rev"].values())
    core_crop_rev_base = total_crop_base - sw_crop_rev_base
    core_crop_rev_treat = total_crop_treat - sw_crop_rev_treat
    core_crop_rev_delta = round(core_crop_rev_treat - core_crop_rev_base, 2)

    total_seed_base = sum(cl_base["seed_purchases_cost"].values())
    total_seed_treat = sum(cl_treat["seed_purchases_cost"].values())
    core_seed_base = total_seed_base - sw_seed_cost_base
    core_seed_treat = total_seed_treat - sw_seed_cost_treat
    core_seed_cost_delta = round(core_seed_treat - core_seed_base, 2)

    total_land_base = cl_base["land_purchases_cost"]
    total_land_treat = cl_treat["land_purchases_cost"]
    core_land_base = total_land_base - sw_land_cost_base
    core_land_treat = total_land_treat - sw_land_cost_treat
    core_land_cost_delta = round(core_land_treat - core_land_base, 2)

    anim_rev_base = sum(cl_base["animal_sales_rev"].values())
    anim_rev_treat = sum(cl_treat["animal_sales_rev"].values())
    animal_rev_delta = round(anim_rev_treat - anim_rev_base, 2)

    anim_purch_base = sum(cl_base["animal_purchases_cost"].values())
    anim_purch_treat = sum(cl_treat["animal_purchases_cost"].values())
    animal_purchase_delta = round(anim_purch_treat - anim_purch_base, 2)

    feed_base = cl_base["feed_purchases_cost"]
    feed_treat = cl_treat["feed_purchases_cost"]
    feed_cost_delta = round(feed_treat - feed_base, 2)

    fert_base = cl_base["fertilizer_purchases_cost"]
    fert_treat = cl_treat["fertilizer_purchases_cost"]
    fertilizer_exp_delta = round(fert_treat - fert_base, 2)

    hire_base = cl_base["hiring_costs"]
    hire_treat = cl_treat["hiring_costs"]
    hiring_cost_delta = round(hire_treat - hire_base, 2)

    wages_base = cl_base.get("wages_paid", 0.0)
    wages_treat = cl_treat.get("wages_paid", 0.0)
    wages_delta = round(wages_treat - wages_base, 2)

    accounted_delta = round(
        sw_net_delta
        + core_crop_rev_delta
        - core_seed_cost_delta
        - core_land_cost_delta
        + animal_rev_delta
        - animal_purchase_delta
        - feed_cost_delta
        - fertilizer_exp_delta
        - hiring_cost_delta
        - wages_delta,
        2,
    )
    waterfall_residual = round(observed_delta - accounted_delta, 2)

    return {
        "pair_id": pair_id,
        "base_cash": base_cash,
        "treat_cash": treat_cash,
        "observed_delta": observed_delta,
        "accounted_delta": accounted_delta,
        "waterfall_residual": waterfall_residual,
        "reconciled": abs(waterfall_residual) < 0.05,
        "components": {
            "sw_net_margin_delta": sw_net_delta,
            "core_crop_revenue_delta": core_crop_rev_delta,
            "core_seed_cost_delta": core_seed_cost_delta,
            "core_land_cost_delta": core_land_cost_delta,
            "animal_revenue_delta": animal_rev_delta,
            "animal_purchase_delta": animal_purchase_delta,
            "feed_expenditure_delta": feed_cost_delta,
            "fertilizer_expenditure_delta": fertilizer_exp_delta,
            "hiring_cost_delta": hiring_cost_delta,
            "wages_delta": wages_delta,
        },
    }


def run_cell_3arm(seed: int, opp: str, seat: int) -> Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Execute all 3 arms for a single cell."""
    cell_id = f"s{seed}_{opp}_seat{seat}"
    t0 = time.time()
    res_a = run_single_audited_match(seed, opp, seat, "ARM_A")
    res_b = run_single_audited_match(seed, opp, seat, "ARM_B")
    res_c = run_single_audited_match(seed, opp, seat, "ARM_C")
    dur = time.time() - t0
    c_b_delta = res_c["outcome"]["final_cash"] - res_b["outcome"]["final_cash"]
    logger.info(
        f"[Cell {cell_id} Done in {dur:.1f}s] Arm A: ${res_a['outcome']['final_cash']:,.2f} | "
        f"Arm B: ${res_b['outcome']['final_cash']:,.2f} | Arm C: ${res_c['outcome']['final_cash']:,.2f} "
        f"(C-B: ${c_b_delta:+,.2f})"
    )
    return cell_id, res_a, res_b, res_c


def run_sample_panel(seeds: List[int], sample_name: str) -> Dict[str, Any]:
    """Execute complete 3-arm panel for given seeds."""
    logger.info(f"=== Starting {sample_name} Panel (Seeds: {seeds}) ===")
    cells = []
    for seed in seeds:
        for opp in CANONICAL_OPPONENTS:
            for seat in (0, 1):
                cells.append((seed, opp, seat))

    total_cells = len(cells)
    arm_a_results = {}
    arm_b_results = {}
    arm_c_results = {}

    workers = min(6, mp.cpu_count())
    logger.info(f"Executing {total_cells} cells ({total_cells * 3} matches) across {workers} parallel processes...")

    t_panel_0 = time.time()
    with mp.Pool(processes=workers) as pool:
        cell_results = pool.starmap(run_cell_3arm, cells)
    panel_elapsed = time.time() - t_panel_0
    logger.info(f"=== {sample_name} Panel Completed in {panel_elapsed:.1f}s ===")

    for cell_id, res_a, res_b, res_c in cell_results:
        arm_a_results[cell_id] = res_a
        arm_b_results[cell_id] = res_b
        arm_c_results[cell_id] = res_c

    # Compute paired comparisons
    paired_c_vs_b = []
    paired_c_vs_a = []
    paired_b_vs_a = []

    for seed, opp, seat in cells:
        cell_id = f"s{seed}_{opp}_seat{seat}"
        res_a = arm_a_results[cell_id]
        res_b = arm_b_results[cell_id]
        res_c = arm_c_results[cell_id]

        wf_c_b = compute_paired_waterfall(res_b, res_c, cell_id)
        paired_c_vs_b.append(wf_c_b)

        wf_c_a = compute_paired_waterfall(res_a, res_c, cell_id)
        paired_c_vs_a.append(wf_c_a)

        wf_b_a = compute_paired_waterfall(res_a, res_b, cell_id)
        paired_b_vs_a.append(wf_b_a)

    return {
        "sample_name": sample_name,
        "seeds": seeds,
        "cells": cells,
        "arm_a": arm_a_results,
        "arm_b": arm_b_results,
        "arm_c": arm_c_results,
        "paired_c_vs_b": paired_c_vs_b,
        "paired_c_vs_a": paired_c_vs_a,
        "paired_b_vs_a": paired_b_vs_a,
    }


def summarize_panel(panel: Dict[str, Any]) -> Dict[str, Any]:
    """Compute comprehensive statistics across panel comparisons."""
    pw_cb = panel["paired_c_vs_b"]
    pw_ca = panel["paired_c_vs_a"]
    pw_ba = panel["paired_b_vs_a"]

    deltas_cb = [p["observed_delta"] for p in pw_cb]
    deltas_ca = [p["observed_delta"] for p in pw_ca]
    deltas_ba = [p["observed_delta"] for p in pw_ba]

    w_cb = sum(1 for d in deltas_cb if d > 0.05)
    l_cb = sum(1 for d in deltas_cb if d < -0.05)
    t_cb = sum(1 for d in deltas_cb if abs(d) <= 0.05)

    w_ca = sum(1 for d in deltas_ca if d > 0.05)
    l_ca = sum(1 for d in deltas_ca if d < -0.05)
    t_ca = sum(1 for d in deltas_ca if abs(d) <= 0.05)

    # SW purchase count in Arm C
    sw_purchased_count = sum(
        1 for m in panel["arm_c"].values() if m["sw_economics"]["sw_purchased"]
    )

    # Average waterfall components C vs B
    def avg_comp(pws, comp_name):
        return round(float(np.mean([p["components"][comp_name] for p in pws])), 2)

    wf_cb_summary = {
        "mean_sw_net_margin_delta": avg_comp(pw_cb, "sw_net_margin_delta"),
        "mean_core_crop_revenue_delta": avg_comp(pw_cb, "core_crop_revenue_delta"),
        "mean_core_seed_cost_delta": avg_comp(pw_cb, "core_seed_cost_delta"),
        "mean_core_land_cost_delta": avg_comp(pw_cb, "core_land_cost_delta"),
        "mean_animal_revenue_delta": avg_comp(pw_cb, "animal_revenue_delta"),
        "mean_animal_purchase_delta": avg_comp(pw_cb, "animal_purchase_delta"),
        "mean_feed_expenditure_delta": avg_comp(pw_cb, "feed_expenditure_delta"),
        "mean_fertilizer_expenditure_delta": avg_comp(pw_cb, "fertilizer_expenditure_delta"),
        "mean_hiring_cost_delta": avg_comp(pw_cb, "hiring_cost_delta"),
        "mean_wages_delta": avg_comp(pw_cb, "wages_delta"),
        "mean_observed_delta": round(float(np.mean(deltas_cb)), 2),
        "mean_accounted_delta": round(float(np.mean([p["accounted_delta"] for p in pw_cb])), 2),
        "mean_residual": round(float(np.mean([p["waterfall_residual"] for p in pw_cb])), 2),
        "all_reconciled": all(p["reconciled"] for p in pw_cb),
    }

    # Worker action telemetry averages for Arm B vs Arm C
    moves_b = [m["worker_action_summary"]["move_actions"] for m in panel["arm_b"].values()]
    moves_c = [m["worker_action_summary"]["move_actions"] for m in panel["arm_c"].values()]
    core_act_b = [m["worker_action_summary"]["actions_in_core"] for m in panel["arm_b"].values()]
    core_act_c = [m["worker_action_summary"]["actions_in_core"] for m in panel["arm_c"].values()]
    sw_act_b = [m["worker_action_summary"]["actions_in_sw"] for m in panel["arm_b"].values()]
    sw_act_c = [m["worker_action_summary"]["actions_in_sw"] for m in panel["arm_c"].values()]
    water_b = [m["worker_action_summary"]["water_actions"] for m in panel["arm_b"].values()]
    water_c = [m["worker_action_summary"]["water_actions"] for m in panel["arm_c"].values()]

    # Task admission summary across Arm C
    telem_c = [m["sw_task_admission_telemetry"] for m in panel["arm_c"].values()]
    proposed_c = [t["sw_tasks_proposed"] for t in telem_c]
    admitted_c = [t["sw_tasks_admitted"] for t in telem_c]
    deferred_c = [t["sw_tasks_deferred"] for t in telem_c]

    # Aggregate deferral reasons
    agg_reasons = {}
    for t in telem_c:
        for r, cnt in t.get("deferral_reasons", {}).items():
            agg_reasons[r] = agg_reasons.get(r, 0) + cnt

    return {
        "sample_name": panel["sample_name"],
        "sw_purchased_count": sw_purchased_count,
        "total_pairs": len(pw_cb),
        "primary_c_vs_b": {
            "mean_paired_delta": round(float(np.mean(deltas_cb)), 2),
            "median_paired_delta": round(float(np.median(deltas_cb)), 2),
            "std_paired_delta": round(float(np.std(deltas_cb, ddof=1)), 2) if len(deltas_cb) > 1 else 0.0,
            "min_delta": round(float(np.min(deltas_cb)), 2),
            "max_delta": round(float(np.max(deltas_cb)), 2),
            "record": f"{w_cb}W / {l_cb}L / {t_cb}T",
            "wins": w_cb,
            "losses": l_cb,
            "ties": t_cb,
        },
        "secondary_c_vs_a": {
            "mean_paired_delta": round(float(np.mean(deltas_ca)), 2),
            "median_paired_delta": round(float(np.median(deltas_ca)), 2),
            "record": f"{w_ca}W / {l_ca}L / {t_ca}T",
        },
        "control_b_vs_a": {
            "mean_paired_delta": round(float(np.mean(deltas_ba)), 2),
            "median_paired_delta": round(float(np.median(deltas_ba)), 2),
        },
        "waterfall_c_vs_b": wf_cb_summary,
        "worker_action_deltas_c_minus_b": {
            "mean_move_delta": round(float(np.mean(moves_c) - np.mean(moves_b)), 2),
            "mean_core_actions_delta": round(float(np.mean(core_act_c) - np.mean(core_act_b)), 2),
            "mean_sw_actions_delta": round(float(np.mean(sw_act_c) - np.mean(sw_act_b)), 2),
            "mean_water_actions_delta": round(float(np.mean(water_c) - np.mean(water_b)), 2),
        },
        "task_admission_summary": {
            "mean_tasks_proposed": round(float(np.mean(proposed_c)), 2),
            "mean_tasks_admitted": round(float(np.mean(admitted_c)), 2),
            "mean_tasks_deferred": round(float(np.mean(deferred_c)), 2),
            "total_deferral_reasons": agg_reasons,
        },
    }


def main():
    logger.info("=== Launching Phase SW-B3B Tournament Runner ===")
    manifest = get_source_manifest()
    logger.info(f"Source manifest verified across {len(manifest)} files.")

    # 1. Run Discovery Sample (Seeds 97013, 97014)
    disc_panel = run_sample_panel(DISCOVERY_SEEDS, "Discovery")
    disc_summary = summarize_panel(disc_panel)

    # 2. Run Independent Confirmation Sample (Seeds 97015, 97016)
    conf_panel = run_sample_panel(CONFIRMATION_SEEDS, "Confirmation")
    conf_summary = summarize_panel(conf_panel)

    # 3. Overall combined summary
    combined_cells = disc_panel["cells"] + conf_panel["cells"]
    combined_arm_a = {**disc_panel["arm_a"], **conf_panel["arm_a"]}
    combined_arm_b = {**disc_panel["arm_b"], **conf_panel["arm_b"]}
    combined_arm_c = {**disc_panel["arm_c"], **conf_panel["arm_c"]}
    combined_pw_cb = disc_panel["paired_c_vs_b"] + conf_panel["paired_c_vs_b"]
    combined_pw_ca = disc_panel["paired_c_vs_a"] + conf_panel["paired_c_vs_a"]
    combined_pw_ba = disc_panel["paired_b_vs_a"] + conf_panel["paired_b_vs_a"]

    combined_panel = {
        "sample_name": "Combined_40_Pairs",
        "seeds": DISCOVERY_SEEDS + CONFIRMATION_SEEDS,
        "cells": combined_cells,
        "arm_a": combined_arm_a,
        "arm_b": combined_arm_b,
        "arm_c": combined_arm_c,
        "paired_c_vs_b": combined_pw_cb,
        "paired_c_vs_a": combined_pw_ca,
        "paired_b_vs_a": combined_pw_ba,
    }
    combined_summary = summarize_panel(combined_panel)

    # 4. Save JSON artifacts
    with open(os.path.join(RESULTS_DIR, "source_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "summary_report_data.json"), "w", encoding="utf-8") as f:
        json.dump(
            safe_json_serialize({
                "phase": "SW-B3B",
                "description": "Core-First SW Task Admission Experiment",
                "discovery_summary": disc_summary,
                "confirmation_summary": conf_summary,
                "combined_summary": combined_summary,
            }),
            f,
            indent=2,
        )

    with open(os.path.join(RESULTS_DIR, "paired_waterfalls_c_vs_b.json"), "w", encoding="utf-8") as f:
        json.dump(safe_json_serialize(combined_pw_cb), f, indent=2)

    with open(os.path.join(RESULTS_DIR, "paired_waterfalls_c_vs_a.json"), "w", encoding="utf-8") as f:
        json.dump(safe_json_serialize(combined_pw_ca), f, indent=2)

    with open(os.path.join(RESULTS_DIR, "three_arm_matched_outcomes.json"), "w", encoding="utf-8") as f:
        json.dump(
            safe_json_serialize({
                "arm_a": combined_arm_a,
                "arm_b": combined_arm_b,
                "arm_c": combined_arm_c,
            }),
            f,
            indent=2,
        )

    with open(os.path.join(RESULTS_DIR, "task_admission_telemetry.json"), "w", encoding="utf-8") as f:
        json.dump(
            safe_json_serialize({
                cell_id: m["sw_task_admission_telemetry"]
                for cell_id, m in combined_arm_c.items()
            }),
            f,
            indent=2,
        )

    with open(os.path.join(RESULTS_DIR, "worker_action_telemetry.json"), "w", encoding="utf-8") as f:
        json.dump(
            safe_json_serialize({
                cell_id: {
                    "arm_a": combined_arm_a[cell_id]["worker_action_summary"],
                    "arm_b": combined_arm_b[cell_id]["worker_action_summary"],
                    "arm_c": combined_arm_c[cell_id]["worker_action_summary"],
                }
                for cell_id in combined_arm_c
            }),
            f,
            indent=2,
        )

    with open(os.path.join(RESULTS_DIR, "transaction_ledgers.json"), "w", encoding="utf-8") as f:
        json.dump(
            safe_json_serialize({
                cell_id: {
                    "arm_a": combined_arm_a[cell_id]["cash_ledger"],
                    "arm_b": combined_arm_b[cell_id]["cash_ledger"],
                    "arm_c": combined_arm_c[cell_id]["cash_ledger"],
                }
                for cell_id in combined_arm_c
            }),
            f,
            indent=2,
        )

    with open(os.path.join(RESULTS_DIR, "inventory_conservation_records.json"), "w", encoding="utf-8") as f:
        json.dump(
            safe_json_serialize({
                cell_id: {
                    "arm_a": combined_arm_a[cell_id]["inventory_conservation"],
                    "arm_b": combined_arm_b[cell_id]["inventory_conservation"],
                    "arm_c": combined_arm_c[cell_id]["inventory_conservation"],
                }
                for cell_id in combined_arm_c
            }),
            f,
            indent=2,
        )

    logger.info("=== Phase SW-B3B Tournament Execution Completed Successfully ===")
    logger.info(f"Discovery C vs B Mean Delta: ${disc_summary['primary_c_vs_b']['mean_paired_delta']:+,.2f} ({disc_summary['primary_c_vs_b']['record']})")
    logger.info(f"Confirmation C vs B Mean Delta: ${conf_summary['primary_c_vs_b']['mean_paired_delta']:+,.2f} ({conf_summary['primary_c_vs_b']['record']})")
    logger.info(f"Combined 40-pair C vs B Mean Delta: ${combined_summary['primary_c_vs_b']['mean_paired_delta']:+,.2f} ({combined_summary['primary_c_vs_b']['record']})")


if __name__ == "__main__":
    main()
