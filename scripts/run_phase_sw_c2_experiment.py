"""Phase SW-C2: Full Workforce Coordinator & Capacity-Aware Architecture Tournament Runner.

Executes real-engine matched comparisons across all SW-C2 phases:
- ARM_A: Canonical production baseline (SW forward architecture OFF)
- ARM_B: Frozen Phase SW-B3C urgency-aware SW control (fixed 8 tiles)
- ARM_C: Adaptive architecture control, max 8 tiles (proves zero regression on 8 tiles)
- ARM_D: Phase P1 Mission ownership & executable resource chains (fixed 8 tiles)
- ARM_E: Phase P2 Global coordinated regional dispatch (fixed 8 tiles)
- ARM_F: Phase P3 Transactional crop-cycle reservations (fixed 8 tiles)
- ARM_G12: Incremental acreage ladder max 12 tiles
- ARM_G16: Incremental acreage ladder max 16 tiles
- ARM_G20: Incremental acreage ladder max 20 tiles
- ARM_G24: Incremental acreage ladder max 24 tiles

Repairs all SW-C1 diagnostic limitations:
- Exact PLANT engine-confirmed outcome detection & seed lot attribution
- Separate CARE vs COLLECT_FERTILIZER action tracking
- HARD obligation registration, completion, and expiry wiring
- $0.0000 cash residual reconciliation for 100% of matches
- Physical inventory & mass balance conservation
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
logger = logging.getLogger("PhaseSWC2")

DEFAULT_RESULTS_DIR = os.path.join(PROJECT_ROOT, "simulations", "results", "phase_sw_c2")
os.makedirs(DEFAULT_RESULTS_DIR, exist_ok=True)

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

ALL_ARMS = [
    "ARM_A", "ARM_B", "ARM_C",
    "ARM_D", "ARM_E", "ARM_F",
    "ARM_G12", "ARM_G16", "ARM_G20", "ARM_G24",
    "ARM_R2",
]


def compute_file_sha256(filepath: str) -> str:
    if not os.path.exists(filepath):
        return "FILE_NOT_FOUND"
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().upper()


def safe_json_serialize(obj: Any) -> Any:
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


class RepairedMatchEngineAuditor:
    """Repaired turn-by-turn interceptor for engine mechanics & service tracking."""

    def __init__(self, monitored_seat: int = 0):
        self.monitored_seat = monitored_seat
        self.step_reconciliations = []
        self.transactions = []
        self.harvest_events = []
        self.discard_events = []
        self.plant_events = []
        self.current_step = 0

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
            "collect_fertilizer_actions": 0,
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
                self.plant_events.append({
                    "step": self.current_step,
                    "day": self.current_step // 24,
                    "hour": self.current_step % 24,
                    "crop": c,
                    "pos": list(pre_pos),
                    "is_sw": is_sw,
                })
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
        elif op == "CARE":
            self.action_counts["care_actions"] += 1
        elif op == "COLLECT_FERTILIZER":
            self.action_counts["collect_fertilizer_actions"] += 1
            if outcome and outcome.get("collected_fertilizer"):
                if "FERTILIZER" in self.inventory_ledger:
                    self.inventory_ledger["FERTILIZER"]["produced_animal"] += 1
        elif op == "FERTILIZE":
            self.action_counts["fertilize_actions"] += 1
            if outcome and outcome.get("fertilized"):
                if "FERTILIZER" in self.inventory_ledger:
                    self.inventory_ledger["FERTILIZER"]["consumed_fertilizer"] += 1
        elif op == "PLACE":
            self.action_counts["place_actions"] += 1
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
            get_sw_task_admission_telemetry().record_executed_action(reg, op, pre_pos, outcome, step=self.current_step)
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


def configure_arm(arm: str) -> None:
    """Configure runtime flags for the selected experimental arm."""
    import agent.config as config

    # Base settings
    config.SOFT_WORKER_LOCALITY_MODE = "ON"
    config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
    config.QUADRANT_HARD_BLOCK = {4}
    config.set_sw_p1_mission_ownership_enabled(False)
    config.set_sw_p2_coordinated_dispatch_enabled(False)
    config.set_sw_p3_transactional_reservations_enabled(False)
    config.set_sw_r2_dynamic_acquisition_enabled(False)

    if arm == "ARM_A":
        # Canonical production reference
        config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(False)
        config.set_sw_adaptive_acreage_enabled(False)
        config.set_sw_max_adaptive_acreage(24)
        config.set_sw_p1_mission_ownership_enabled(False)
        config.set_sw_p2_coordinated_dispatch_enabled(False)
        config.set_sw_p3_transactional_reservations_enabled(False)
    elif arm == "ARM_B":
        # Frozen B3C 8-tile control
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(False)
        config.set_sw_max_adaptive_acreage(24)
        config.set_sw_p1_mission_ownership_enabled(False)
        config.set_sw_p2_coordinated_dispatch_enabled(False)
        config.set_sw_p3_transactional_reservations_enabled(False)
    elif arm == "ARM_C":
        # Adaptive architecture control capped at 8 tiles
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(8)
        config.set_sw_p1_mission_ownership_enabled(False)
        config.set_sw_p2_coordinated_dispatch_enabled(False)
        config.set_sw_p3_transactional_reservations_enabled(False)
    elif arm == "ARM_D":
        # P1 Mission Ownership & Resource Chains (8 tiles)
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(8)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(False)
        config.set_sw_p3_transactional_reservations_enabled(False)
    elif arm == "ARM_E":
        # P2 Coordinated Dispatch (8 tiles)
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(8)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(True)
        config.set_sw_p3_transactional_reservations_enabled(False)
    elif arm == "ARM_F":
        # P3 Reservations + Coordinated Dispatch (8 tiles)
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(8)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(True)
        config.set_sw_p3_transactional_reservations_enabled(True)
    elif arm == "ARM_G12":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(12)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(True)
        config.set_sw_p3_transactional_reservations_enabled(True)
    elif arm == "ARM_G16":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(16)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(True)
        config.set_sw_p3_transactional_reservations_enabled(True)
    elif arm == "ARM_G20":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(20)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(True)
        config.set_sw_p3_transactional_reservations_enabled(True)
    elif arm == "ARM_G24":
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(24)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(True)
        config.set_sw_p3_transactional_reservations_enabled(True)
    elif arm == "ARM_R2":
        # R2 Early Acquisition + Executable Capacity + Shared Reservations (8 tiles)
        config.SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"
        config.set_sw_core_first_task_admission_enabled(False)
        config.set_sw_urgency_aware_admission_enabled(True)
        config.set_sw_adaptive_acreage_enabled(True)
        config.set_sw_max_adaptive_acreage(8)
        config.set_sw_p1_mission_ownership_enabled(True)
        config.set_sw_p2_coordinated_dispatch_enabled(True)
        config.set_sw_p3_transactional_reservations_enabled(True)
        config.set_sw_r2_dynamic_acquisition_enabled(True)
    else:
        raise ValueError(f"Unknown arm: {arm}")


def run_single_match(args_tuple: Tuple[int, str, int, str]) -> Dict[str, Any]:
    seed, opp_name, seat, arm = args_tuple

    configure_arm(arm)

    from agent.main import agent as my_agent, reset_agent_state
    from agent.strategy.farm_plan import reset_farm_plan
    from agent.strategy.whole_farm_planner import reset_whole_farm_planner
    from agent.strategy.sw_tranche_controller import (
        get_sw_tranche_controller,
        reset_sw_tranche_controller,
    )
    from agent.strategy.adaptive_acreage_planner import reset_adaptive_acreage_planner
    from agent.strategy.crop_cycle_reservation_manager import reset_crop_cycle_reservation_manager
    from agent.execution.midnight_storage_controller import (
        reset_midnight_storage_telemetry,
    )
    from agent.execution.sw_task_admission_controller import (
        reset_sw_task_admission_telemetry,
        get_sw_task_admission_telemetry,
    )
    from agent.execution.service_obligation_ledger import reset_service_obligation_ledger
    from agent.execution.mission_ownership_tracker import reset_mission_ownership_tracker
    from agent.execution.workforce_capacity_forecast import reset_workforce_capacity_forecaster
    from agent.execution.coordinated_dispatch_controller import reset_coordinated_dispatch_controller
    from agent.diagnostics.animal_tracker import AnimalSurvivalTracker
    from simulations.experiments.agent_zoo import get_agent

    # Clean singletons
    reset_agent_state()
    reset_farm_plan()
    reset_whole_farm_planner()
    reset_sw_tranche_controller()
    reset_adaptive_acreage_planner()
    reset_crop_cycle_reservation_manager()
    reset_midnight_storage_telemetry()
    reset_sw_task_admission_telemetry()
    reset_service_obligation_ledger()
    reset_mission_ownership_tracker()
    reset_workforce_capacity_forecaster()
    reset_coordinated_dispatch_controller()

    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(arm != "ARM_A")

    animal_tracker = AnimalSurvivalTracker(seat=seat)
    opp_agent = get_agent(opp_name)

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()

    auditor = RepairedMatchEngineAuditor(monitored_seat=seat)

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
        elif op == "PLANT":
            if pre_tile is None and isinstance(post_tile, dict) and post_tile.get("kind") == "PLANT":
                outcome = {"planted": True, "crop": post_tile.get("crop")}
        elif op == "FEED":
            if isinstance(pre_tile, dict) and not pre_tile.get("fed_today") and isinstance(post_tile, dict) and post_tile.get("fed_today"):
                outcome = {"fed": True}
        elif op == "CARE":
            if isinstance(pre_tile, dict) and not pre_tile.get("cared_today") and isinstance(post_tile, dict) and post_tile.get("cared_today"):
                outcome = {"cared": True}
        elif op == "COLLECT_FERTILIZER":
            if isinstance(pre_tile, dict) and pre_tile.get("fertilizer_available") and isinstance(post_tile, dict) and not post_tile.get("fertilizer_available"):
                outcome = {"collected_fertilizer": True}
        elif op == "FERTILIZE":
            if isinstance(pre_tile, dict) and isinstance(post_tile, dict) and post_tile.get("fertilized_until_day", -1) > pre_tile.get("fertilized_until_day", -1):
                outcome = {"fertilized": True}
        elif op == "PLACE":
            if isinstance(post_tile, dict) and "animal" in post_tile and (pre_tile is None or "animal" not in pre_tile):
                outcome = {"animal_placed": True, "animal": post_tile.get("animal")}

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
        sw_share = (sw_h / tot_h) if tot_h > 0 else 0.0
        sw_rev = round(tot_sales * sw_share * avg_px, 2)
        core_rev = round(crop_rev - sw_rev, 2)
        sw_total_crop_revenue += sw_rev

        seed_unit_px = kag.CROPS[crop]["seed"]
        sw_planted = auditor.seed_ledger[crop]["planted_sw"]
        sw_seed_spend = sw_planted * seed_unit_px
        sw_total_seed_cost += sw_seed_spend

        crop_provenance[crop] = {
            "harvested_core": core_h,
            "harvested_sw": sw_h,
            "total_sold": tot_sales,
            "total_revenue": crop_rev,
            "sw_attributed_revenue": sw_rev,
            "core_attributed_revenue": core_rev,
            "sw_planted": sw_planted,
            "sw_seed_cost": sw_seed_spend,
        }

    core_crop_revenue = round(tot_crop_rev - sw_total_crop_revenue, 2)
    sw_net_crop_margin = round(sw_total_crop_revenue - sw_total_seed_cost, 2)

    admission_telemetry = get_sw_task_admission_telemetry().to_dict()

    sw_expansion_history = []
    sw_expansion_rejections = []
    try:
        from agent.strategy.adaptive_acreage_planner import get_adaptive_acreage_planner
        aap = get_adaptive_acreage_planner()
        sw_expansion_history = aap.expansion_history
        sw_expansion_rejections = aap.rejection_history
    except Exception:
        pass

    return {
        "match_id": f"{seed}_{opp_name}_{seat}_{arm}",
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "arm": arm,
        "final_cash": final_cash,
        "opp_final_cash": opp_final_cash,
        "win": win,
        "reconciled_cash": reconciled_cash,
        "cash_residual": residual,
        "crop_sales_rev": cl["crop_sales_rev"],
        "animal_sales_rev": cl["animal_sales_rev"],
        "total_crop_revenue": tot_crop_rev,
        "total_animal_revenue": tot_animal_rev,
        "core_crop_revenue": core_crop_revenue,
        "sw_total_crop_revenue": sw_total_crop_revenue,
        "sw_total_seed_cost": sw_total_seed_cost,
        "sw_net_crop_margin": sw_net_crop_margin,
        "crop_provenance": crop_provenance,
        "land_purchases_cost": cl["land_purchases_cost"],
        "land_purchases_count": cl["land_purchases_count"],
        "seed_purchases_cost": cl["seed_purchases_cost"],
        "feed_purchases_cost": cl["feed_purchases_cost"],
        "fertilizer_purchases_cost": cl["fertilizer_purchases_cost"],
        "hiring_costs": cl["hiring_costs"],
        "hires_count": cl["hires_count"],
        "action_counts": auditor.action_counts,
        "inventory_ledger": auditor.inventory_ledger,
        "seed_ledger": auditor.seed_ledger,
        "sw_task_admission_telemetry": admission_telemetry,
        "sw_expansion_history": sw_expansion_history,
        "sw_expansion_rejections": sw_expansion_rejections,
        "animal_survival": animal_tracker.get_summary(),
        "min_cash_seen": min_cash_seen,
        "peak_shed_occupancy": peak_shed_occupancy,
        "latency_p95_ms": float(np.percentile(turn_latencies, 95)) if turn_latencies else 0.0,
        "latency_max_ms": float(np.max(turn_latencies)) if turn_latencies else 0.0,
        "latency_mean_ms": float(np.mean(turn_latencies)) if turn_latencies else 0.0,
    }


def run_tournament(
    seeds: List[int],
    opponents: List[str],
    seats: List[int],
    arms: List[str],
    num_workers: int = 4,
    output_dir: str = DEFAULT_RESULTS_DIR,
    tag: str = "tournament",
) -> Dict[str, Any]:
    tasks = []
    for s in seeds:
        for opp in opponents:
            for seat in seats:
                for arm in arms:
                    tasks.append((s, opp, seat, arm))

    logger.info(f"Starting {tag}: {len(tasks)} matches ({len(arms)} arms x {len(seeds)} seeds x {len(opponents)} opps x {len(seats)} seats) with {num_workers} workers...")
    t0 = time.time()

    if num_workers > 1:
        ctx = mp.get_context("spawn")
        with ctx.Pool(num_workers) as pool:
            results = pool.map(run_single_match, tasks)
    else:
        results = [run_single_match(t) for t in tasks]

    elapsed = time.time() - t0
    logger.info(f"Tournament completed in {elapsed:.1f}s")

    # Aggregate summaries
    arm_metrics: Dict[str, Any] = {}
    for arm in arms:
        arm_res = [r for r in results if r["arm"] == arm]
        if not arm_res:
            continue
        cashes = [r["final_cash"] for r in arm_res]
        wins = [r["win"] for r in arm_res]
        sw_buys = [1 if r["land_purchases_count"] > 1 else 0 for r in arm_res]
        sw_revs = [r["sw_total_crop_revenue"] for r in arm_res]
        sw_margins = [r["sw_net_crop_margin"] for r in arm_res]
        core_crop_revs = [r["core_crop_revenue"] for r in arm_res]
        core_animal_revs = [r["total_animal_revenue"] for r in arm_res]

        arm_metrics[arm] = {
            "count": len(cashes),
            "mean_final_cash": float(np.mean(cashes)),
            "median_final_cash": float(np.median(cashes)),
            "std_final_cash": float(np.std(cashes)),
            "min_final_cash": float(np.min(cashes)),
            "max_final_cash": float(np.max(cashes)),
            "win_rate": float(np.mean(wins)),
            "sw_purchase_rate": float(np.mean(sw_buys)),
            "mean_sw_revenue": float(np.mean(sw_revs)),
            "mean_sw_net_margin": float(np.mean(sw_margins)),
            "mean_core_crop_revenue": float(np.mean(core_crop_revs)),
            "mean_core_livestock_revenue": float(np.mean(core_animal_revs)),
            "all_cash_reconciled_zero_residual": int(all(abs(r["cash_residual"]) < 1e-4 for r in arm_res)),
        }

    summary = {
        "tag": tag,
        "seeds": seeds,
        "opponents": opponents,
        "seats": seats,
        "arms_evaluated": arms,
        "num_matches": len(results),
        "elapsed_seconds": elapsed,
        "arm_metrics": arm_metrics,
    }

    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, f"sw_c2_summary_{tag}.json")
    matches_path = os.path.join(output_dir, f"sw_c2_matches_{tag}.json")

    with open(summary_path, "w") as f:
        json.dump(safe_json_serialize(summary), f, indent=2)
    with open(matches_path, "w") as f:
        json.dump(safe_json_serialize(results), f, indent=2)

    logger.info(f"Saved results to {summary_path} and {matches_path}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SW-C2 Tournament")
    parser.add_argument("--arms", nargs="+", default=["ARM_A", "ARM_B", "ARM_C"], choices=ALL_ARMS)
    parser.add_argument("--seeds", nargs="+", type=int, default=DISCOVERY_SEEDS)
    parser.add_argument("--opponents", nargs="+", default=CANONICAL_OPPONENTS)
    parser.add_argument("--seats", nargs="+", type=int, default=[0, 1])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--tag", type=str, default="p0_baseline_reproduction")
    parser.add_argument("--output-dir", type=str, default=DEFAULT_RESULTS_DIR)
    args = parser.parse_args()

    run_tournament(
        seeds=args.seeds,
        opponents=args.opponents,
        seats=args.seats,
        arms=args.arms,
        num_workers=args.workers,
        output_dir=args.output_dir,
        tag=args.tag,
    )
