#!/usr/bin/env python3
"""
Controlled Paired A/B & Four-Way Benchmark Harness for Kaggriculture Central Planner.

Supports:
  1. Four-Way Architecture Matrix:
     - Architecture A: 'historical_stack' (Historical candidate limits + Legacy compose)
     - Architecture B: 'expanded_legacy'  (Expanded candidate limits + Legacy compose)
     - Architecture C: 'expanded_central' (Expanded candidate limits + CentralPlanner)
     - Architecture D: 'historical_candidates_central' (Historical candidate limits + CentralPlanner)
  2. Pairwise Benchmarks:
     - 'arbitration_only': B vs C
     - 'full_stack': A vs C

Ensures total process isolation across runs, captures fine-grained system and economic metrics,
evaluates capital deployment, cash reserve trajectories, suppressed proposal analysis,
and emits machine-readable CSV and JSON artifacts.
"""

import argparse
import copy
import csv
import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

# Ensure repo root and agent are in sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIR = os.path.join(REPO_ROOT, "agent")
for p in (REPO_ROOT, AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

FIB_WAGES = [10, 10, 20, 30, 50, 80, 130, 210, 340, 550, 890, 1440, 2330, 3770]


def _fib(n: int) -> int:
    if n < len(FIB_WAGES):
        return FIB_WAGES[n]
    a, b = 10, 10
    for _ in range(n):
        a, b = b, a + b
    return a


SEED_COSTS = {"WHEAT": 2, "CARROT": 5, "TOMATO": 10, "STRAWBERRY": 20, "MELON": 50}
ANIMAL_COSTS = {"HEN": 50, "SHEEP": 150, "COW": 300}
LAND_COSTS = [1000, 2000]


def _worker_run_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Worker entry point executed in an isolated spawned process."""
    seed = payload["seed"]
    opponent_name = payload["opponent"]
    architecture = payload.get("architecture") or payload.get("mode")
    episode_steps = payload.get("episode_steps", 720)
    agent_dir = payload["agent_dir"]
    repo_root = payload["repo_root"]

    # Map architecture to runtime mode
    mode_map = {
        "historical_stack": "historical_stack",
        "expanded_legacy": "legacy",
        "expanded_central": "central",
        "historical_candidates_central": "historical_candidates_central",
        "legacy": "legacy",
        "central": "central",
    }
    mode = mode_map.get(architecture, architecture)

    # Inject paths into isolated worker sys.path
    for p in (repo_root, agent_dir):
        if p not in sys.path:
            sys.path.insert(0, p)
    for sub in ("state", "strategy", "execution", "market"):
        sub_p = os.path.join(agent_dir, sub)
        if sub_p not in sys.path:
            sys.path.insert(0, sub_p)

    from kaggle_environments import make
    import main as agent_module
    from market.price_math import market_price

    # Reset any module state and set arbitration mode
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode(mode)

    # Telemetry accumulator
    turn_telemetry_records: List[Dict[str, Any]] = []

    def wrapped_agent(obs, config=None):
        act = agent_module.agent(obs, config)
        tel = agent_module.get_last_turn_telemetry()
        if tel is not None:
            turn_telemetry_records.append(tel)
        return act

    # Resolve opponent
    if opponent_name in ("random", "pass", "starter"):
        opp = opponent_name
    else:
        try:
            from simulations.experiments.agent_zoo import get_agent
            opp = get_agent(opponent_name)
        except Exception:
            opp = "random"

    # Initialize environment
    env = make(
        "kaggriculture",
        configuration={"seed": seed, "episodeSteps": episode_steps},
        debug=False,
    )

    env.run([wrapped_agent, opp])

    final_step = env.steps[-1]
    obs0 = final_step[0].observation
    farm0 = obs0["farms"][0]
    farm1 = obs0["farms"][1]
    private0 = obs0.get("private", {})
    shed0 = private0.get("shed", {})

    final_money = float(farm0.get("money", 0.0))
    opp_final_money = float(farm1.get("money", 0.0))
    margin = final_money - opp_final_money
    win = 1 if final_money > opp_final_money else (0.5 if final_money == opp_final_money else 0)

    # Step-by-step state & capital tracking
    unlocked_quadrants_over_time = []
    ne_unlock_day = None
    sw_unlock_day = None
    feed_failures = 0
    shed_overflow_events = 0
    total_market_orders_executed = 0

    purchase_spend = {
        "hires": 0.0,
        "seeds": 0.0,
        "wheat": 0.0,
        "animals": 0.0,
        "land": 0.0,
        "fertilizer": 0.0,
        "other": 0.0,
    }
    land_purchases = 0
    land_purchase_days: Dict[str, int] = {}
    animal_purchases = 0
    seed_purchases = 0
    critical_wheat_purchases = 0

    cash_history = []
    cash_at_key_days = {f"day_{d}": None for d in [5, 9, 11, 13, 20, 28]}
    hires_today = 0
    last_day = -1

    for step_idx, step_state in enumerate(env.steps):
        s_obs0 = step_state[0].observation
        if not isinstance(s_obs0, dict):
            continue
        s_farms = s_obs0.get("farms", [])
        if not s_farms:
            continue
        s_farm0 = s_farms[0]
        unlocked = set(s_farm0.get("unlocked_quadrants", ["NW"]))
        unlocked_quadrants_over_time.append(unlocked)
        day = int(s_obs0.get("day", 0))
        hour = int(s_obs0.get("hour", 0))
        money = float(s_farm0.get("money", 0.0))
        cash_history.append(money)

        if day != last_day:
            hires_today = 0
            last_day = day

        if hour == 0 and day in (5, 9, 11, 13, 20, 28):
            key = f"day_{day}"
            if cash_at_key_days[key] is None:
                cash_at_key_days[key] = money

        if "NE" in unlocked and ne_unlock_day is None:
            ne_unlock_day = day
        if "SW" in unlocked and sw_unlock_day is None:
            sw_unlock_day = day

        # Feed failure detection
        tiles = s_farm0.get("tiles", [])
        for row in tiles:
            if not isinstance(row, list):
                continue
            for t in row:
                if isinstance(t, dict) and t.get("kind") == "ANIMAL":
                    if t.get("days_unfed", 0) > 0 or t.get("is_starving", False):
                        feed_failures += 1

        # Shed overflow detection
        s_private = s_obs0.get("private", {})
        s_shed = s_private.get("shed", {})
        if sum(s_shed.values()) >= 100:
            shed_overflow_events += 1

        # Track spend from market actions
        s_act = step_state[0].action
        market_orders = s_act.get("market", []) if isinstance(s_act, dict) else []
        total_market_orders_executed += len(market_orders)

        inv = s_obs0.get("market", {}).get("inventory", {})
        unlocked_count = len(unlocked)

        for o in market_orders:
            if not isinstance(o, (list, tuple)) or not o:
                continue
            opcode = o[0]
            if opcode == "HIRE":
                cost = float(_fib(hires_today))
                hires_today += 1
                purchase_spend["hires"] += cost
            elif opcode == "BUY_LAND":
                idx = max(0, unlocked_count - 1)
                cost = float(LAND_COSTS[idx] if idx < len(LAND_COSTS) else 4000)
                purchase_spend["land"] += cost
                land_purchases += 1
                quad_name = ["NE", "SW", "SE"][idx] if idx < 3 else f"Q{idx+1}"
                if quad_name not in land_purchase_days:
                    land_purchase_days[quad_name] = day
            elif opcode == "BUY_SEED" and len(o) >= 3:
                crop = o[1]
                qty = int(o[2])
                cost = float(qty * SEED_COSTS.get(crop, 10))
                purchase_spend["seeds"] += cost
                seed_purchases += qty
            elif opcode == "BUY_ANIMAL" and len(o) >= 3:
                animal = o[1]
                qty = int(o[2])
                cost = float(qty * ANIMAL_COSTS.get(animal, 100))
                purchase_spend["animals"] += cost
                animal_purchases += qty
            elif opcode == "BUY_PRODUCT" and len(o) >= 3:
                prod = o[1]
                qty = int(o[2])
                px = float(market_price(prod, inv.get(prod, 10000.0)))
                cost = float(qty * px)
                if prod == "WHEAT":
                    purchase_spend["wheat"] += cost
                    critical_wheat_purchases += qty
                elif prod == "FERTILIZER":
                    purchase_spend["fertilizer"] += cost
                else:
                    purchase_spend["other"] += cost

    # Fill any unreached key days with final money
    for k in cash_at_key_days:
        if cash_at_key_days[k] is None:
            cash_at_key_days[k] = final_money

    total_purchase_spend = sum(purchase_spend.values())
    capital_efficiency = round(final_money / max(1.0, total_purchase_spend), 4)
    average_cash = round(float(np.mean(cash_history)) if cash_history else 0.0, 2)
    minimum_cash = round(float(np.min(cash_history)) if cash_history else 0.0, 2)

    # Land utilization at end of game
    final_tiles = farm0.get("tiles", [])
    total_unlocked_tiles = len(farm0.get("unlocked_quadrants", ["NW"])) * 25
    utilized_tiles = 0
    animal_count = 0
    crop_counts: Dict[str, int] = {}
    for row in final_tiles:
        if not isinstance(row, list):
            continue
        for t in row:
            if isinstance(t, dict):
                k = t.get("kind")
                if k == "ANIMAL":
                    utilized_tiles += 1
                    animal_count += 1
                elif k == "PLANT":
                    utilized_tiles += 1
                    crop = t.get("crop", "UNKNOWN")
                    crop_counts[crop] = crop_counts.get(crop, 0) + 1
                elif k == "STRUCTURE":
                    utilized_tiles += 1

    quadrant_utilization = utilized_tiles / max(1, total_unlocked_tiles)

    # Endgame unsold inventory
    sellables = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL"]
    endgame_unsold_inventory = sum(shed0.get(p, 0) for p in sellables)

    # Telemetry aggregations
    turns_total = len(turn_telemetry_records)
    turns_with_candidates = 0
    turns_with_slot_pressure = 0
    turns_changed_from_legacy = 0
    changed_selection_turns = 0
    execution_reorder_only_turns = 0
    slot_pressure_changed_selection_turns = 0

    purchase_candidates_total = 0
    sell_candidates_total = 0
    orders_selected_total = 0

    rejections_by_reason: Dict[str, int] = Counter()
    accepted_by_priority: Dict[str, int] = Counter()
    rejected_by_priority: Dict[str, int] = Counter()

    p0_priority_inversion_count = 0
    p0_priority_inversions = []
    fallback_count = 0
    invalid_proposal_count = 0

    land_proposed_count = 0
    land_selected_count = 0
    critical_wheat_proposed_count = 0
    critical_wheat_selected_count = 0

    wheat_P0_count = 0
    wheat_P1_count = 0
    wheat_P2_count = 0
    wheat_selected_count = 0
    wheat_rejected_count = 0
    critical_wheat_rejected_count = 0
    routine_wheat_preempted_sell_count = 0
    total_sell_orders = 0
    total_sell_revenue = 0.0

    # Suppressed proposals tracking (upstream slot caps)
    suppressed_counts: Dict[str, int] = Counter()
    suppressed_proposals: List[Dict[str, Any]] = []

    # Lost opportunity tracking
    lost_opportunities: List[Dict[str, Any]] = []

    for t in turn_telemetry_records:
        # Track executed sells and revenue
        for m in t.get("market", []):
            if len(m) > 0 and m[0] == "SELL":
                total_sell_orders += 1
                prod = m[1] if len(m) > 1 else ""
                qty = int(m[2]) if len(m) > 2 else 0
                px = market_price(prod, t.get("market_inventory_before", {}).get(prod, 10000.0))
                total_sell_revenue += px * qty

        n_p = len(t.get("purchase_orders", []))
        n_s = len(t.get("sell_orders", []))
        c_tot = n_p + n_s
        if c_tot > 0:
            turns_with_candidates += 1
            purchase_candidates_total += n_p
            sell_candidates_total += n_s

        orders_selected_total += len(t.get("market", []))

        if t.get("land_proposed"):
            land_proposed_count += 1
        if t.get("land_selected"):
            land_selected_count += 1

        if t.get("critical_wheat_proposed"):
            critical_wheat_proposed_count += 1
        if t.get("critical_wheat_selected"):
            critical_wheat_selected_count += 1

        # Lost opportunity detection: needed but unfunded
        money_avail = t.get("money_before", 0.0)
        if t.get("land_proposed") and not t.get("land_selected"):
            land_price = 1000.0 if len(t.get("unlocked_land", [])) == 1 else 2000.0
            if money_avail < land_price:
                lost_opportunities.append({
                    "day": t.get("day"),
                    "hour": t.get("hour"),
                    "type": "BUY_LAND",
                    "money_available": money_avail,
                    "money_needed": land_price,
                })
        if t.get("critical_wheat_proposed") and not t.get("critical_wheat_selected"):
            if money_avail < 20.0:
                lost_opportunities.append({
                    "day": t.get("day"),
                    "hour": t.get("hour"),
                    "type": "CRITICAL_WHEAT",
                    "money_available": money_avail,
                    "money_needed": 20.0,
                })

        # Track suppressed proposals from purchase ledger
        ledger = t.get("purchase_ledger")
        if isinstance(ledger, dict):
            for d in ledger.get("dropped", []):
                k = d.get("kind", "")
                if k == "hire_slots":
                    cnt = d.get("count", 1)
                    suppressed_counts["HIRE"] += cnt
                    suppressed_proposals.append({
                        "day": t.get("day"), "hour": t.get("hour"), "type": "HIRE",
                        "qty": cnt, "cost": d.get("cost", 10.0), "tier": d.get("tier", 0),
                    })
                elif k == "seed_slots":
                    cnt = d.get("n", 1)
                    suppressed_counts["BUY_SEED"] += cnt
                    suppressed_proposals.append({
                        "day": t.get("day"), "hour": t.get("hour"), "type": "BUY_SEED",
                        "crop": d.get("crop"), "qty": cnt, "cost": d.get("cost", 0.0), "tier": d.get("tier", 1),
                    })
                elif k == "wheat_slots":
                    cnt = d.get("n", 1)
                    suppressed_counts["BUY_PRODUCT WHEAT"] += cnt
                    suppressed_proposals.append({
                        "day": t.get("day"), "hour": t.get("hour"), "type": "BUY_PRODUCT WHEAT",
                        "qty": cnt, "cost": d.get("cost", 0.0), "tier": d.get("tier", 2),
                    })
                elif k == "animal_slots":
                    cnt = d.get("n", 1)
                    suppressed_counts["BUY_ANIMAL"] += cnt
                    suppressed_proposals.append({
                        "day": t.get("day"), "hour": t.get("hour"), "type": "BUY_ANIMAL",
                        "animal": d.get("animal"), "qty": cnt, "cost": d.get("cost", 0.0), "tier": d.get("tier", 3),
                    })
                elif k == "land_slots":
                    suppressed_counts["BUY_LAND"] += 1
                    suppressed_proposals.append({
                        "day": t.get("day"), "hour": t.get("hour"), "type": "BUY_LAND",
                        "qty": 1, "cost": d.get("cost", 0.0), "tier": d.get("tier", 4),
                    })

        # Track suppressed proposals from sell details
        sd = t.get("sell_details")
        if isinstance(sd, dict):
            for omitted in sd.get("omitted_by_slots", []):
                p = omitted.get("product", "PRODUCT")
                suppressed_counts[f"SELL_{p}"] += 1
                suppressed_proposals.append({
                    "day": t.get("day"), "hour": t.get("hour"), "type": f"SELL_{p}",
                    "qty": omitted.get("available_stock", 0), "urgency": omitted.get("urgency", 0),
                })

        # Diagnostics from Central Planner
        diag = t.get("central_planner_diagnostic")
        if diag:
            if diag.get("fallback_used"):
                fallback_count += 1
            invalid_proposal_count += diag.get("rejection_reasons", {}).get("invalid_order", 0)

            if diag.get("slot_pressure", False):
                turns_with_slot_pressure += 1
                if diag.get("changed_selection", False):
                    slot_pressure_changed_selection_turns += 1

            if diag.get("changed_from_legacy", False):
                turns_changed_from_legacy += 1
            if diag.get("changed_selection", False):
                changed_selection_turns += 1
            if diag.get("execution_reorder_only", False):
                execution_reorder_only_turns += 1

            p0_inv = diag.get("p0_priority_inversions", [])
            if p0_inv:
                p0_priority_inversion_count += len(p0_inv)
                p0_priority_inversions.extend(p0_inv)

            for r, count in diag.get("rejection_reasons", {}).items():
                rejections_by_reason[r] += count
            for p, count in diag.get("accepted_by_priority", {}).items():
                accepted_by_priority[p] += count
            for p, count in diag.get("rejected_by_priority", {}).items():
                rejected_by_priority[p] += count

        wt = t.get("wheat_telemetry") or (diag.get("wheat_telemetry") if diag else None)
        if wt:
            wheat_P0_count += wt.get("wheat_P0_count", 0)
            wheat_P1_count += wt.get("wheat_P1_count", 0)
            wheat_P2_count += wt.get("wheat_P2_count", 0)
            wheat_selected_count += wt.get("wheat_selected_count", 0)
            wheat_rejected_count += wt.get("wheat_rejected_count", 0)
            critical_wheat_rejected_count += wt.get("critical_wheat_rejected_count", 0)
            routine_wheat_preempted_sell_count += wt.get("routine_wheat_preempted_sell_count", 0)

    # Section 15 Benchmark Assertions for Central Planner runs
    if mode in ("central", "historical_candidates_central", "expanded_central"):
        assert all(len(t.get("market", [])) <= 10 for t in turn_telemetry_records), "Market orders exceeded 10"
        assert p0_priority_inversion_count == 0, f"Found {p0_priority_inversion_count} P0 priority inversions"
        assert fallback_count == 0, f"CentralPlanner fallback used {fallback_count} times"
        assert invalid_proposal_count == 0, f"Found {invalid_proposal_count} invalid proposals"
        assert critical_wheat_rejected_count == 0, f"Found {critical_wheat_rejected_count} critical wheat rejections"

    slot_pressure_changed_selection_rate = (
        slot_pressure_changed_selection_turns / max(1, turns_with_slot_pressure)
    )

    return {
        "seed": seed,
        "opponent": opponent_name,
        "architecture": architecture,
        "mode": mode,
        "final_money": final_money,
        "opponent_final_money": opp_final_money,
        "margin": margin,
        "win": win,
        "total_purchase_spend": round(total_purchase_spend, 2),
        "spend_hires": round(purchase_spend["hires"], 2),
        "spend_seeds": round(purchase_spend["seeds"], 2),
        "spend_wheat": round(purchase_spend["wheat"], 2),
        "spend_animals": round(purchase_spend["animals"], 2),
        "spend_land": round(purchase_spend["land"], 2),
        "spend_fertilizer": round(purchase_spend["fertilizer"], 2),
        "average_cash": average_cash,
        "minimum_cash": minimum_cash,
        "cash_day_5": cash_at_key_days["day_5"],
        "cash_day_9": cash_at_key_days["day_9"],
        "cash_day_11": cash_at_key_days["day_11"],
        "cash_day_13": cash_at_key_days["day_13"],
        "cash_day_20": cash_at_key_days["day_20"],
        "cash_day_28": cash_at_key_days["day_28"],
        "capital_efficiency": capital_efficiency,
        "land_purchases": land_purchases,
        "land_purchase_days": land_purchase_days,
        "ne_unlock_day": ne_unlock_day,
        "sw_unlock_day": sw_unlock_day,
        "quadrant_utilization": round(quadrant_utilization, 4),
        "animal_count": animal_count,
        "animal_purchases": animal_purchases,
        "seed_purchases": seed_purchases,
        "critical_wheat_purchases": critical_wheat_purchases,
        "wheat_P0_count": wheat_P0_count,
        "wheat_P1_count": wheat_P1_count,
        "wheat_P2_count": wheat_P2_count,
        "wheat_selected_count": wheat_selected_count,
        "wheat_rejected_count": wheat_rejected_count,
        "critical_wheat_rejected_count": critical_wheat_rejected_count,
        "routine_wheat_preempted_sell_count": routine_wheat_preempted_sell_count,
        "total_sell_orders": total_sell_orders,
        "total_sell_revenue": round(total_sell_revenue, 2),
        "crop_counts": crop_counts,
        "feed_failures": feed_failures,
        "shed_overflow_events": shed_overflow_events,
        "endgame_unsold_inventory": endgame_unsold_inventory,
        "total_market_orders_executed": total_market_orders_executed,
        "turns_total": turns_total,
        "turns_with_candidates": turns_with_candidates,
        "turns_with_slot_pressure": turns_with_slot_pressure,
        "turns_changed_from_legacy": turns_changed_from_legacy,
        "changed_selection_turns": changed_selection_turns,
        "execution_reorder_only_turns": execution_reorder_only_turns,
        "slot_pressure_changed_selection_turns": slot_pressure_changed_selection_turns,
        "slot_pressure_changed_selection_rate": round(slot_pressure_changed_selection_rate, 4),
        "purchase_candidates_total": purchase_candidates_total,
        "sell_candidates_total": sell_candidates_total,
        "orders_selected_total": orders_selected_total,
        "rejections_by_reason": dict(rejections_by_reason),
        "accepted_by_priority": dict(accepted_by_priority),
        "rejected_by_priority": dict(rejected_by_priority),
        "p0_priority_inversion_count": p0_priority_inversion_count,
        "fallback_count": fallback_count,
        "invalid_proposal_count": invalid_proposal_count,
        "land_proposed_count": land_proposed_count,
        "land_selected_count": land_selected_count,
        "critical_wheat_proposed_count": critical_wheat_proposed_count,
        "critical_wheat_selected_count": critical_wheat_selected_count,
        "suppressed_counts": dict(suppressed_counts),
        "suppressed_candidates_total": sum(suppressed_counts.values()),
        "lost_opportunities_count": len(lost_opportunities),
        "lost_opportunities": lost_opportunities,
    }


class CentralPlannerBenchmark:
    def __init__(
        self,
        seeds: List[int],
        opponents: List[str],
        benchmark_type: str = "four_way",
        baseline_mode: str = "legacy",
        max_workers: int = 4,
    ):
        self.seeds = seeds
        self.opponents = opponents
        self.benchmark_type = benchmark_type
        self.baseline_mode = baseline_mode
        self.max_workers = max_workers

    def run(self) -> Dict[str, Any]:
        tasks = []
        if self.benchmark_type == "four_way":
            arch_list = [
                "historical_stack",
                "expanded_legacy",
                "expanded_central",
                "historical_candidates_central",
            ]
            for opp in self.opponents:
                for s in self.seeds:
                    for arch in arch_list:
                        tasks.append({
                            "seed": s, "opponent": opp, "architecture": arch,
                            "mode": arch, "agent_dir": AGENT_DIR, "repo_root": REPO_ROOT
                        })
        elif self.benchmark_type == "wheat_fix":
            arch_list = [
                "historical_stack",
                "historical_candidates_central",
            ]
            for opp in self.opponents:
                for s in self.seeds:
                    for arch in arch_list:
                        tasks.append({
                            "seed": s, "opponent": opp, "architecture": arch,
                            "mode": arch, "agent_dir": AGENT_DIR, "repo_root": REPO_ROOT
                        })
        else:
            for opp in self.opponents:
                for s in self.seeds:
                    tasks.append({
                        "seed": s, "opponent": opp, "architecture": self.baseline_mode,
                        "mode": self.baseline_mode, "agent_dir": AGENT_DIR, "repo_root": REPO_ROOT
                    })
                    tasks.append({
                        "seed": s, "opponent": opp, "architecture": "central",
                        "mode": "central", "agent_dir": AGENT_DIR, "repo_root": REPO_ROOT
                    })

        desc = (
            "Four-Way Matrix (4 architectures)" if self.benchmark_type == "four_way"
            else "Wheat Fix Benchmark (A vs D2)" if self.benchmark_type == "wheat_fix"
            else f"Paired A/B [{self.baseline_mode} vs central]"
        )
        print(f"Starting {desc}: {len(self.seeds)} seeds x {len(self.opponents)} opponents = {len(tasks)} runs...")
        start_time = time.time()

        raw_results = {}
        with ProcessPoolExecutor(max_workers=self.max_workers, mp_context=mp.get_context("spawn")) as executor:
            future_to_payload = {executor.submit(_worker_run_match, p): p for p in tasks}
            completed = 0
            for future in as_completed(future_to_payload):
                completed += 1
                res = future.result()
                key = (res["seed"], res["opponent"], res["architecture"])
                raw_results[key] = res
                print(f"[{completed:03d}/{len(tasks):03d}] Seed {res['seed']:02d} | {res['opponent']:<7} | {res['architecture']:<29} => ${res['final_money']:,.2f}")

        elapsed = time.time() - start_time
        print(f"Benchmark finished in {elapsed:.1f}s.")

        return {
            "elapsed_seconds": round(elapsed, 2),
            "seed_count": len(self.seeds),
            "opponents": self.opponents,
            "benchmark_type": self.benchmark_type,
            "raw_results": raw_results,
        }


def save_four_way_artifacts(raw_results: Dict[Tuple, Dict[str, Any]], csv_path: str, json_path: str, stats: Dict[str, Any]):
    """Save machine-readable CSV and JSON for four-way benchmark."""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    headers = [
        "seed", "opponent", "architecture",
        "final_money", "opponent_final_money", "margin", "win",
        "total_purchase_spend", "spend_hires", "spend_seeds", "spend_wheat",
        "spend_animals", "spend_land", "spend_fertilizer",
        "average_cash", "minimum_cash",
        "cash_day_5", "cash_day_9", "cash_day_11", "cash_day_13", "cash_day_20", "cash_day_28",
        "capital_efficiency",
        "land_purchases", "ne_unlock_day", "sw_unlock_day",
        "animal_purchases", "seed_purchases", "critical_wheat_purchases",
        "feed_failures", "shed_overflow_events", "endgame_unsold_inventory",
        "turns_with_slot_pressure", "diverged_turns", "changed_selection_turns",
        "execution_reorder_only_turns", "p0_inversions", "suppressed_candidates_total",
    ]

    all_rows = []
    for (s, opp, arch), r in sorted(raw_results.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        row = {
            "seed": s,
            "opponent": opp,
            "architecture": arch,
            "final_money": r["final_money"],
            "opponent_final_money": r["opponent_final_money"],
            "margin": r["margin"],
            "win": r["win"],
            "total_purchase_spend": r["total_purchase_spend"],
            "spend_hires": r["spend_hires"],
            "spend_seeds": r["spend_seeds"],
            "spend_wheat": r["spend_wheat"],
            "spend_animals": r["spend_animals"],
            "spend_land": r["spend_land"],
            "spend_fertilizer": r["spend_fertilizer"],
            "average_cash": r["average_cash"],
            "minimum_cash": r["minimum_cash"],
            "cash_day_5": r["cash_day_5"],
            "cash_day_9": r["cash_day_9"],
            "cash_day_11": r["cash_day_11"],
            "cash_day_13": r["cash_day_13"],
            "cash_day_20": r["cash_day_20"],
            "cash_day_28": r["cash_day_28"],
            "capital_efficiency": r["capital_efficiency"],
            "land_purchases": r["land_purchases"],
            "ne_unlock_day": r["ne_unlock_day"],
            "sw_unlock_day": r["sw_unlock_day"],
            "animal_purchases": r["animal_purchases"],
            "seed_purchases": r["seed_purchases"],
            "critical_wheat_purchases": r["critical_wheat_purchases"],
            "feed_failures": r["feed_failures"],
            "shed_overflow_events": r["shed_overflow_events"],
            "endgame_unsold_inventory": r["endgame_unsold_inventory"],
            "turns_with_slot_pressure": r["turns_with_slot_pressure"],
            "diverged_turns": r["turns_changed_from_legacy"],
            "changed_selection_turns": r["changed_selection_turns"],
            "execution_reorder_only_turns": r["execution_reorder_only_turns"],
            "p0_inversions": r["p0_priority_inversion_count"],
            "suppressed_candidates_total": r["suppressed_candidates_total"],
        }
        all_rows.append(row)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    json_data = {
        "summary_statistics": stats["architecture_summaries"],
        "paired_comparisons": stats["paired_comparisons"],
        "capital_deployment": stats["capital_summaries"],
        "overspending_analysis": stats.get("overspending_analysis", {}),
        "suppression_analysis": stats.get("suppression_analysis", {}),
        "all_runs": [
            {k: v for k, v in r.items() if k != "divergence_turns"}
            for r in raw_results.values()
        ],
    }
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2)

    print(f"Artifacts saved:\n  CSV:  {csv_path}\n  JSON: {json_path}")


def compute_four_way_statistics(
    raw_results: Dict[Tuple, Dict[str, Any]],
    seeds: List[int],
    opponents: List[str],
    arch_list: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Compute comprehensive four-way architecture statistics, paired comparisons, and capital audits."""
    if arch_list is None:
        arch_list = [
            "historical_stack",
            "expanded_legacy",
            "expanded_central",
            "historical_candidates_central",
        ]

    arch_summaries = {}
    capital_summaries = {}
    wheat_summaries = {}

    for arch in arch_list:
        scores = [raw_results[(s, opp, arch)]["final_money"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        arr = np.array(scores)
        sorted_arr = np.sort(arr)
        b10_cnt = max(1, int(len(arr) * 0.10))

        arch_summaries[arch] = {
            "mean": round(float(np.mean(arr)), 2),
            "median": round(float(np.median(arr)), 2),
            "std": round(float(np.std(arr)), 2),
            "min": round(float(np.min(arr)), 2),
            "max": round(float(np.max(arr)), 2),
            "p10": round(float(np.percentile(arr, 10)), 2),
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "p90": round(float(np.percentile(arr, 90)), 2),
            "bottom_10_mean": round(float(np.mean(sorted_arr[:b10_cnt])), 2),
        }

        # Capital summaries
        spends = [raw_results[(s, opp, arch)]["total_purchase_spend"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        hire_spends = [raw_results[(s, opp, arch)]["spend_hires"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        seed_spends = [raw_results[(s, opp, arch)]["spend_seeds"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        wheat_spends = [raw_results[(s, opp, arch)]["spend_wheat"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        anim_spends = [raw_results[(s, opp, arch)]["spend_animals"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        land_spends = [raw_results[(s, opp, arch)]["spend_land"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        avg_cash = [raw_results[(s, opp, arch)]["average_cash"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        min_cash = [raw_results[(s, opp, arch)]["minimum_cash"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        effs = [raw_results[(s, opp, arch)]["capital_efficiency"] for s in seeds for opp in opponents if (s, opp, arch) in raw_results]

        capital_summaries[arch] = {
            "mean_total_spend": round(float(np.mean(spends)), 2),
            "mean_spend_hires": round(float(np.mean(hire_spends)), 2),
            "mean_spend_seeds": round(float(np.mean(seed_spends)), 2),
            "mean_spend_wheat": round(float(np.mean(wheat_spends)), 2),
            "mean_spend_animals": round(float(np.mean(anim_spends)), 2),
            "mean_spend_land": round(float(np.mean(land_spends)), 2),
            "mean_average_cash": round(float(np.mean(avg_cash)), 2),
            "mean_minimum_cash": round(float(np.mean(min_cash)), 2),
            "mean_capital_efficiency": round(float(np.mean(effs)), 4),
        }

        # Wheat & sell summaries
        p0_cnts = [raw_results[(s, opp, arch)].get("wheat_P0_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        p1_cnts = [raw_results[(s, opp, arch)].get("wheat_P1_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        p2_cnts = [raw_results[(s, opp, arch)].get("wheat_P2_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        w_sel = [raw_results[(s, opp, arch)].get("wheat_selected_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        w_rej = [raw_results[(s, opp, arch)].get("wheat_rejected_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        w_crit_rej = [raw_results[(s, opp, arch)].get("critical_wheat_rejected_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        w_preempt = [raw_results[(s, opp, arch)].get("routine_wheat_preempted_sell_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        sell_orders = [raw_results[(s, opp, arch)].get("total_sell_orders", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        sell_revs = [raw_results[(s, opp, arch)].get("total_sell_revenue", 0.0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        feed_fails = [raw_results[(s, opp, arch)].get("feed_failures", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]
        p0_invs = [raw_results[(s, opp, arch)].get("p0_priority_inversion_count", 0) for s in seeds for opp in opponents if (s, opp, arch) in raw_results]

        wheat_summaries[arch] = {
            "mean_wheat_P0": round(float(np.mean(p0_cnts)), 2),
            "mean_wheat_P1": round(float(np.mean(p1_cnts)), 2),
            "mean_wheat_P2": round(float(np.mean(p2_cnts)), 2),
            "mean_wheat_selected": round(float(np.mean(w_sel)), 2),
            "mean_wheat_rejected": round(float(np.mean(w_rej)), 2),
            "total_critical_wheat_rejected": int(np.sum(w_crit_rej)),
            "total_routine_wheat_preempted_sells": int(np.sum(w_preempt)),
            "mean_sell_orders": round(float(np.mean(sell_orders)), 2),
            "mean_sell_revenue": round(float(np.mean(sell_revs)), 2),
            "total_feed_failures": int(np.sum(feed_fails)),
            "total_p0_inversions": int(np.sum(p0_invs)),
        }

    # Paired comparisons
    def get_paired_stats(arch_x, arch_y):
        deltas = []
        for s in seeds:
            for opp in opponents:
                rx = raw_results.get((s, opp, arch_x))
                ry = raw_results.get((s, opp, arch_y))
                if rx and ry:
                    deltas.append(rx["final_money"] - ry["final_money"])

        if not deltas:
            return {}

        darr = np.array(deltas)
        sorted_d = np.sort(darr)
        b10_cnt = max(1, int(len(darr) * 0.10))

        return {
            "comparison": f"{arch_x} vs {arch_y}",
            "mean_delta": round(float(np.mean(darr)), 2),
            "median_delta": round(float(np.median(darr)), 2),
            "std_delta": round(float(np.std(darr)), 2),
            "min_delta": round(float(np.min(darr)), 2),
            "max_delta": round(float(np.max(darr)), 2),
            "p10_delta": round(float(np.percentile(darr, 10)), 2),
            "p25_delta": round(float(np.percentile(darr, 25)), 2),
            "p75_delta": round(float(np.percentile(darr, 75)), 2),
            "p90_delta": round(float(np.percentile(darr, 90)), 2),
            "bottom_10_mean_delta": round(float(np.mean(sorted_d[:b10_cnt])), 2),
            "x_wins": int(np.sum(darr > 0)),
            "y_wins": int(np.sum(darr < 0)),
            "ties": int(np.sum(darr == 0)),
        }

    paired_comparisons = {}
    if "historical_candidates_central" in arch_list and "historical_stack" in arch_list:
        paired_comparisons["D_vs_A"] = get_paired_stats("historical_candidates_central", "historical_stack")
    if "historical_candidates_central" in arch_list and "expanded_central" in arch_list:
        paired_comparisons["D_vs_C"] = get_paired_stats("historical_candidates_central", "expanded_central")
    if "expanded_central" in arch_list and "expanded_legacy" in arch_list:
        paired_comparisons["C_vs_B"] = get_paired_stats("expanded_central", "expanded_legacy")

    # Overspending analysis: expanded_central (C) vs historical_candidates_central (D)
    overspending_analysis = {}
    if "expanded_central" in capital_summaries and "historical_candidates_central" in capital_summaries:
        diff_hires = capital_summaries["expanded_central"]["mean_spend_hires"] - capital_summaries["historical_candidates_central"]["mean_spend_hires"]
        diff_seeds = capital_summaries["expanded_central"]["mean_spend_seeds"] - capital_summaries["historical_candidates_central"]["mean_spend_seeds"]
        diff_wheat = capital_summaries["expanded_central"]["mean_spend_wheat"] - capital_summaries["historical_candidates_central"]["mean_spend_wheat"]
        diff_animals = capital_summaries["expanded_central"]["mean_spend_animals"] - capital_summaries["historical_candidates_central"]["mean_spend_animals"]
        diff_land = capital_summaries["expanded_central"]["mean_spend_land"] - capital_summaries["historical_candidates_central"]["mean_spend_land"]
        diff_total = capital_summaries["expanded_central"]["mean_total_spend"] - capital_summaries["historical_candidates_central"]["mean_total_spend"]

        overspending_analysis = {
            "additional_spend_hires": round(diff_hires, 2),
            "additional_spend_seeds": round(diff_seeds, 2),
            "additional_spend_wheat": round(diff_wheat, 2),
            "additional_spend_animals": round(diff_animals, 2),
            "additional_spend_land": round(diff_land, 2),
            "additional_total_spend": round(diff_total, 2),
        }

    # Suppression analysis: historical_candidates_central (D)
    suppression_analysis = {}
    if "historical_candidates_central" in arch_list:
        total_suppressed_proposals = sum(
            raw_results[(s, opp, "historical_candidates_central")]["suppressed_candidates_total"]
            for s in seeds for opp in opponents if (s, opp, "historical_candidates_central") in raw_results
        )
        suppression_analysis = {
            "total_suppressed_proposals_D": total_suppressed_proposals,
            "mean_suppressed_per_match_D": round(total_suppressed_proposals / max(1, len(seeds) * len(opponents)), 2),
        }

    return {
        "architecture_summaries": arch_summaries,
        "capital_summaries": capital_summaries,
        "wheat_summaries": wheat_summaries,
        "paired_comparisons": paired_comparisons,
        "overspending_analysis": overspending_analysis,
        "suppression_analysis": suppression_analysis,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kaggriculture Central Planner Four-Way / Wheat Fix / Paired Benchmark")
    parser.add_argument("--benchmark", type=str, choices=["four_way", "wheat_fix", "arbitration_only", "full_stack"], default="wheat_fix",
                        help="Benchmark type: 'wheat_fix' (A vs D2), 'four_way' (all 4 cells), 'arbitration_only', or 'full_stack'")
    parser.add_argument("--seeds", type=int, default=25, help="Number of seeds to evaluate (default 25)")
    parser.add_argument("--start-seed", type=int, default=101, help="Starting seed number (default 101)")
    parser.add_argument("--opponents", nargs="+", default=["random", "starter"], help="Opponent policies to test")
    parser.add_argument("--workers", type=int, default=min(4, max(1, mp.cpu_count() - 1)), help="Number of parallel workers")
    parser.add_argument("--csv", type=str, default=None, help="Output CSV path")
    parser.add_argument("--json", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()

    seed_list = list(range(args.start_seed, args.start_seed + args.seeds))

    PREVIOUS_D_BASELINE = 68003.82

    if args.benchmark == "wheat_fix":
        csv_path = args.csv or os.path.join(REPO_ROOT, "artifacts", "central_planner_wheat_fix.csv")
        json_path = args.json or os.path.join(REPO_ROOT, "artifacts", "central_planner_wheat_fix.json")

        benchmark = CentralPlannerBenchmark(
            seeds=seed_list,
            opponents=args.opponents,
            benchmark_type="wheat_fix",
            max_workers=args.workers,
        )
        res = benchmark.run()
        stats = compute_four_way_statistics(
            res["raw_results"], seed_list, args.opponents,
            arch_list=["historical_stack", "historical_candidates_central"],
        )
        stats["previous_d_baseline"] = PREVIOUS_D_BASELINE
        save_four_way_artifacts(res["raw_results"], csv_path, json_path, stats)

        arch_sums = stats["architecture_summaries"]
        cap_sums = stats["capital_summaries"]
        wheat_sums = stats["wheat_summaries"]
        pairs = stats["paired_comparisons"]
        p_d_vs_a = pairs.get("D_vs_A", {})

        d2_mean = arch_sums["historical_candidates_central"]["mean"]
        d2_median = arch_sums["historical_candidates_central"]["median"]
        a_mean = arch_sums["historical_stack"]["mean"]
        a_median = arch_sums["historical_stack"]["median"]
        d2_minus_prev_d = d2_mean - PREVIOUS_D_BASELINE

        print("\n=========================================================================================")
        print("                     WHEAT PRIORITY FIX BENCHMARK (A vs D2)                              ")
        print("=========================================================================================")
        print(f"{'Architecture':<32} | {'Mean':>10} | {'Median':>10} | {'Std':>8} | {'Min':>10} | {'Max':>10} | {'B10 Mean':>10}")
        print("-" * 105)
        for arch in ["historical_stack", "historical_candidates_central"]:
            s = arch_sums[arch]
            lbl = "A. historical_stack" if arch == "historical_stack" else "D2. hist_candidates_central"
            print(f"{lbl:<32} | ${s['mean']:>9,.2f} | ${s['median']:>9,.2f} | ${s['std']:>7,.2f} | ${s['min']:>9,.2f} | ${s['max']:>9,.2f} | ${s['bottom_10_mean']:>9,.2f}")
        print("-" * 105)

        print("\n=========================================================================================")
        print("                              DECISION GATE COMPARISONS                                  ")
        print("=========================================================================================")
        print(f"--- Primary Gate: D2 vs A (Historical Candidates + Corrected Central vs Historical Stack) ---")
        print(f"  Mean Delta (D2 - A):      ${p_d_vs_a.get('mean_delta', 0.0):>+10,.2f}")
        print(f"  Median Delta:             ${p_d_vs_a.get('median_delta', 0.0):>+10,.2f}")
        print(f"  Delta Range:              Min ${p_d_vs_a.get('min_delta', 0.0):>+10,.2f} | Max ${p_d_vs_a.get('max_delta', 0.0):>+10,.2f}")
        print(f"  Percentiles:              P10: ${p_d_vs_a.get('p10_delta', 0.0):>+9,.2f} | P25: ${p_d_vs_a.get('p25_delta', 0.0):>+9,.2f} | P75: ${p_d_vs_a.get('p75_delta', 0.0):>+9,.2f} | P90: ${p_d_vs_a.get('p90_delta', 0.0):>+9,.2f}")
        print(f"  Bottom 10% Mean Delta:    ${p_d_vs_a.get('bottom_10_mean_delta', 0.0):>+10,.2f}")
        print(f"  Win / Loss / Tie (D2 vs A): {p_d_vs_a.get('x_wins', 0)} / {p_d_vs_a.get('y_wins', 0)} / {p_d_vs_a.get('ties', 0)}")
        print()
        print(f"--- Improvement Gate: D2 vs Previous D (Effect of Wheat Priority Fix) ---")
        print(f"  Previous D Mean:          ${PREVIOUS_D_BASELINE:>10,.2f}")
        print(f"  Corrected D2 Mean:        ${d2_mean:>10,.2f}")
        print(f"  Lift over Previous D:     ${d2_minus_prev_d:>+10,.2f}")
        print()

        print("=========================================================================================")
        print("                             WHEAT TELEMETRY & FEED SAFETY                               ")
        print("=========================================================================================")
        print(f"{'Architecture':<32} | {'P0':>5} | {'P1':>5} | {'P2':>5} | {'Sel':>5} | {'Rej':>5} | {'CritRej':>7} | {'PreemptSell':>11} | {'FeedFail':>8} | {'P0Inv':>5}")
        print("-" * 110)
        for arch in ["historical_stack", "historical_candidates_central"]:
            w = wheat_sums[arch]
            lbl = "A. historical_stack" if arch == "historical_stack" else "D2. hist_candidates_central"
            print(f"{lbl:<32} | {w['mean_wheat_P0']:>5.1f} | {w['mean_wheat_P1']:>5.1f} | {w['mean_wheat_P2']:>5.1f} | {w['mean_wheat_selected']:>5.1f} | {w['mean_wheat_rejected']:>5.1f} | {w['total_critical_wheat_rejected']:>7d} | {w['total_routine_wheat_preempted_sells']:>11d} | {w['total_feed_failures']:>8d} | {w['total_p0_inversions']:>5d}")
        print("-" * 110)

        print("\n=========================================================================================")
        print("                             CAPITAL & REVENUE REALIZATION                               ")
        print("=========================================================================================")
        print(f"{'Architecture':<32} | {'Total Spend':>11} | {'Wheat Spend':>11} | {'Seed Spend':>10} | {'Sell Orders':>11} | {'Sell Rev':>10} | {'Avg Cash':>9} | {'Eff':>6}")
        print("-" * 115)
        for arch in ["historical_stack", "historical_candidates_central"]:
            c = cap_sums[arch]
            w = wheat_sums[arch]
            lbl = "A. historical_stack" if arch == "historical_stack" else "D2. hist_candidates_central"
            print(f"{lbl:<32} | ${c['mean_total_spend']:>10,.2f} | ${c['mean_spend_wheat']:>10,.2f} | ${c['mean_spend_seeds']:>9,.2f} | {w['mean_sell_orders']:>11.1f} | ${w['mean_sell_revenue']:>9,.2f} | ${c['mean_average_cash']:>8,.2f} | {c['mean_capital_efficiency']:>6.2f}")
        print("-" * 115)
        print()

        print("\n=========================================================================================")
        print("                               KEY PAIRED COMPARISONS                                    ")
        print("=========================================================================================")
        for key, p in [
            ("D2 - A: Historical Candidates + Corrected Central vs Historical Stack", pairs["D_vs_A"]),
        ]:
            print(f"--- {key} ---")
            print(f"  Mean Delta:    ${p['mean_delta']:>+10,.2f} (Median: ${p['median_delta']:>+10,.2f}, Std: ${p['std_delta']:,.2f})")
            print(f"  Delta Range:   Min ${p['min_delta']:>+10,.2f} | Max ${p['max_delta']:>+10,.2f}")
            print(f"  Percentiles:   P10: ${p['p10_delta']:>+9,.2f} | P25: ${p['p25_delta']:>+9,.2f} | P75: ${p['p75_delta']:>+9,.2f} | P90: ${p['p90_delta']:>+9,.2f}")
            print(f"  Bottom 10% Mean: ${p['bottom_10_mean_delta']:>+10,.2f}")
            print(f"  Win / Loss / Tie: {p['x_wins']} / {p['y_wins']} / {p['ties']}")
            print()

        print("=========================================================================================")
        print("                             CAPITAL DEPLOYMENT BREAKDOWN                                ")
        print("=========================================================================================")
        print(f"{'Architecture':<32} | {'Total Spend':>11} | {'Hires':>9} | {'Seeds':>8} | {'Wheat':>8} | {'Animals':>8} | {'Land':>8} | {'Avg Cash':>9} | {'Eff':>6}")
        print("-" * 115)
        for arch in ["historical_stack", "historical_candidates_central"]:
            c = cap_sums[arch]
            lbl = "A. historical_stack" if arch == "historical_stack" else "D2. hist_candidates_central"
            print(f"{lbl:<32} | ${c['mean_total_spend']:>10,.2f} | ${c['mean_spend_hires']:>8,.2f} | ${c['mean_spend_seeds']:>7,.2f} | ${c['mean_spend_wheat']:>7,.2f} | ${c['mean_spend_animals']:>7,.2f} | ${c['mean_spend_land']:>7,.2f} | ${c['mean_average_cash']:>8,.2f} | {c['mean_capital_efficiency']:>6.2f}")
        print("-" * 115)
        print("=========================================================================================\n")

    elif args.benchmark == "four_way":
        csv_path = args.csv or os.path.join(REPO_ROOT, "artifacts", "central_planner_four_way.csv")
        json_path = args.json or os.path.join(REPO_ROOT, "artifacts", "central_planner_four_way.json")

        benchmark = CentralPlannerBenchmark(
            seeds=seed_list,
            opponents=args.opponents,
            benchmark_type="four_way",
            max_workers=args.workers,
        )
        res = benchmark.run()
        stats = compute_four_way_statistics(res["raw_results"], seed_list, args.opponents)
        save_four_way_artifacts(res["raw_results"], csv_path, json_path, stats)

        arch_sums = stats["architecture_summaries"]
        cap_sums = stats["capital_summaries"]
        pairs = stats["paired_comparisons"]
        overspend = stats["overspending_analysis"]

        print("\n=========================================================================================")
        print("                         FOUR-WAY ARCHITECTURE MATRIX SUMMARY                            ")
        print("=========================================================================================")
        print(f"{'Architecture':<32} | {'Mean':>10} | {'Median':>10} | {'Std':>8} | {'Min':>10} | {'Max':>10} | {'B10 Mean':>10}")
        print("-" * 105)
        for arch in ["historical_stack", "expanded_legacy", "expanded_central", "historical_candidates_central"]:
            s = arch_sums[arch]
            print(f"{arch:<32} | ${s['mean']:>9,.2f} | ${s['median']:>9,.2f} | ${s['std']:>7,.2f} | ${s['min']:>9,.2f} | ${s['max']:>9,.2f} | ${s['bottom_10_mean']:>9,.2f}")
        print("-" * 105)

        print("\n=========================================================================================")
        print("                               KEY PAIRED COMPARISONS                                    ")
        print("=========================================================================================")
        for key, p in [
            ("D - A: Historical Candidates + Central vs Historical Stack + Legacy (Primary Decision)", pairs["D_vs_A"]),
            ("D - C: Historical Candidates + Central vs Expanded Candidates + Central (Upstream Discipline)", pairs["D_vs_C"]),
            ("C - B: Expanded Candidates + Central vs Expanded Candidates + Legacy (Pure Arbitration Lift)", pairs["C_vs_B"]),
        ]:
            print(f"--- {key} ---")
            print(f"  Mean Delta:    ${p['mean_delta']:>+10,.2f} (Median: ${p['median_delta']:>+10,.2f}, Std: ${p['std_delta']:,.2f})")
            print(f"  Delta Range:   Min ${p['min_delta']:>+10,.2f} | Max ${p['max_delta']:>+10,.2f}")
            print(f"  Percentiles:   P10: ${p['p10_delta']:>+9,.2f} | P25: ${p['p25_delta']:>+9,.2f} | P75: ${p['p75_delta']:>+9,.2f} | P90: ${p['p90_delta']:>+9,.2f}")
            print(f"  Bottom 10% Mean: ${p['bottom_10_mean_delta']:>+10,.2f}")
            print(f"  Win / Loss / Tie: {p['x_wins']} / {p['y_wins']} / {p['ties']}")
            print()

        print("=========================================================================================")
        print("                             CAPITAL DEPLOYMENT BREAKDOWN                                ")
        print("=========================================================================================")
        print(f"{'Architecture':<32} | {'Total Spend':>11} | {'Hires':>9} | {'Seeds':>8} | {'Wheat':>8} | {'Animals':>8} | {'Land':>8} | {'Avg Cash':>9} | {'Eff':>6}")
        print("-" * 115)
        for arch in ["historical_stack", "expanded_legacy", "expanded_central", "historical_candidates_central"]:
            c = cap_sums[arch]
            print(f"{arch:<32} | ${c['mean_total_spend']:>10,.2f} | ${c['mean_spend_hires']:>8,.2f} | ${c['mean_spend_seeds']:>7,.2f} | ${c['mean_spend_wheat']:>7,.2f} | ${c['mean_spend_animals']:>7,.2f} | ${c['mean_spend_land']:>7,.2f} | ${c['mean_average_cash']:>8,.2f} | {c['mean_capital_efficiency']:>6.2f}")
        print("-" * 115)

        print(f"\nOverspending Analysis (Expanded Central C vs Historical Candidates Central D):")
        print(f"  Additional Hires Spend:   ${overspend['additional_spend_hires']:>+8,.2f}")
        print(f"  Additional Seeds Spend:   ${overspend['additional_spend_seeds']:>+8,.2f}")
        print(f"  Additional Wheat Spend:   ${overspend['additional_spend_wheat']:>+8,.2f}")
        print(f"  Additional Animals Spend: ${overspend['additional_spend_animals']:>+8,.2f}")
        print(f"  Additional Land Spend:    ${overspend['additional_spend_land']:>+8,.2f}")
        print(f"  Total Additional Spend:   ${overspend['additional_total_spend']:>+8,.2f}")
        print("=========================================================================================\n")

    else:
        # Pairwise backward-compatibility mode
        baseline_mode = "legacy" if args.benchmark == "arbitration_only" else "historical_stack"
        csv_path = args.csv or os.path.join(REPO_ROOT, "artifacts", f"central_planner_{args.benchmark}_ab.csv")
        json_path = args.json or os.path.join(REPO_ROOT, "artifacts", f"central_planner_{args.benchmark}_ab.json")

        benchmark = CentralPlannerBenchmark(
            seeds=seed_list,
            opponents=args.opponents,
            benchmark_type=args.benchmark,
            baseline_mode=baseline_mode,
            max_workers=args.workers,
        )
        res = benchmark.run()
        print(f"Pairwise benchmark complete: {len(res['raw_results'])} runs executed.")
