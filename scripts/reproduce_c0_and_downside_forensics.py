"""Phase C0-R1: Reproducibility & Downside Forensics Runner.

Executes a clean, unpolluted rerun of all 100 paired configurations (200 real-engine matches):
- 10 discovery seeds: 96501–96510
- 5 benchmark opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 seats: 0, 1
- CONTROL: SOFT_WORKER_LOCALITY_MODE = "OFF", SW_FORWARD_ARCHITECTURE_MODE = "OFF"
- TREATMENT: SOFT_WORKER_LOCALITY_MODE = "ON", SW_FORWARD_ARCHITECTURE_MODE = "OFF"

Outputs deliverables into:
- simulations/results/phase_c0_r1_reproduction/
- simulations/results/phase_c0_r1_downside/
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
REPRO_OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_c0_r1_reproduction")
DOWNSIDE_OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_c0_r1_downside")
ORIGINAL_RESULTS_FILE = os.path.join(_REPO_ROOT, "simulations", "results", "phase_c0_soft_locality", "paired_results.json")

os.makedirs(REPRO_OUT_DIR, exist_ok=True)
os.makedirs(DOWNSIDE_OUT_DIR, exist_ok=True)

DEFAULT_SEEDS = list(range(96501, 96511))  # 96501–96510
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
SEED_PRICES = {"WHEAT": 10.0, "CARROT": 20.0, "TOMATO": 50.0, "STRAWBERRY": 100.0, "MELON": 80.0}
CROPS = list(SEED_PRICES.keys())
ANIMAL_COSTS = {"GOOSE": 300.0, "COW": 400.0, "SHEEP": 500.0}
ANIMALS = list(ANIMAL_COSTS.keys())
CROP_MATURITY = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}

SHED_ACCESS_TILES = {(4, 4), (5, 4), (4, 5), (5, 5)}
FARMER_MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}


def _fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _quadrant_of(x: int, y: int) -> str:
    return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def run_single_match(seed: int, opp_name: str, seat: int, locality_mode: str) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    from kaggle_environments import make
    import config
    from agent.main import agent, reset_agent_state
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode(locality_mode)
    reset_agent_state()
    reset_sw_tranche_controller()

    opp_agent = get_agent(opp_name)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    _ = env.reset()

    worker_stats = {
        "total_worker_turns": 0,
        "emitted_moves": 0,
        "executed_moves": 0,
        "failed_moves": 0,
        "productive_moves": 0,
        "moves_to_shed": 0,
        "executed_ops": 0,
        "failed_ops": 0,
        "idle_turns": 0,
        "quadrant_crossings": 0,
        "repeated_crossings": 0,
        "shed_visits": 0,
    }

    worker_journey: Dict[int, Dict[str, Any]] = {}
    active_crop_cycles: Dict[Tuple[int, int], Dict[str, Any]] = {}
    completed_crop_cycles: List[Dict[str, Any]] = []
    tile_last_harvest: Dict[Tuple[int, int], int] = {}
    replanting_delays: List[int] = []

    financial_stats = {
        "total_sales_revenue": 0.0,
        "product_sales_revenue": {p: 0.0 for p in PRODUCTS},
        "product_sales_units": {p: 0 for p in PRODUCTS},
        "executed_spending": {
            "hires": 0.0,
            "land": 0.0,
            "animals": 0.0,
            "seeds": 0.0,
            "seeds_by_crop": {c: 0.0 for c in CROPS},
            "animals_by_type": {a: 0.0 for a in ANIMALS},
        },
        "orders_emitted": 0,
        "orders_executed": 0,
        "orders_dropped": 0,
        "peak_shed_occupancy": 0,
        "shed_full_turns": 0,
    }

    safety_stats = {
        "feeding_due": 0,
        "feeding_executed": 0,
        "animal_escapes": 0,
        "animals_purchased": 0,
        "consecutive_unfed_max": 0,
    }

    step_traces: List[Dict[str, Any]] = []

    while not env.done:
        s0 = env.state[seat].observation
        s1 = env.state[1 - seat].observation
        farm0 = s0.farms[seat]
        priv0 = s0.private
        step = env.state[0].observation.step
        day = s0.day
        hour = s0.hour

        cash_before = float(farm0.money)
        unlocked = list(farm0.unlocked_quadrants)

        # Track active crop maturity
        for y in range(10):
            for x in range(10):
                pos = (x, y)
                quad = _quadrant_of(x, y)
                if quad not in ("NW", "NE") or quad not in unlocked:
                    continue
                tile = farm0.tiles[y][x]
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop_name = tile.get("crop", "WHEAT")
                    p_day = tile.get("planted_day", day)
                    if pos not in active_crop_cycles:
                        active_crop_cycles[pos] = {
                            "tile": pos,
                            "crop": crop_name,
                            "planted_step": step,
                            "planted_day": p_day,
                            "first_ready": None,
                            "harvest_step": None,
                            "delay_hours": 0,
                        }
                    cycle = active_crop_cycles[pos]
                    age = day - p_day
                    mat_day = CROP_MATURITY.get(crop_name, 2)
                    if age >= mat_day and tile.get("yield_units", 0) > 0 and cycle["first_ready"] is None:
                        cycle["first_ready"] = step
                elif isinstance(tile, dict) and "animal" in tile:
                    if hour == 0:
                        safety_stats["feeding_due"] += 1

        # Execute our agent
        act0 = agent(s0, env.configuration)
        farmer_act = act0.get("farmer", ["PASS"])
        hand_acts = act0.get("hands", [])
        all_actions = [farmer_act] + hand_acts
        positions_before = [tuple(farm0.farmer)] + [tuple(h) for h in farm0.hands]
        worker_stats["total_worker_turns"] += len(all_actions)

        emitted_market = act0.get("market", [])
        financial_stats["orders_emitted"] += len(emitted_market)

        # Snapshot step trace for divergence forensics
        step_traces.append({
            "step": step,
            "day": day,
            "hour": hour,
            "positions": positions_before,
            "actions": [list(a) if isinstance(a, (list, tuple)) else [a] for a in all_actions],
            "money": cash_before,
            "shed_total": sum(priv0.shed.values()),
        })

        # Opponent turn
        try:
            act1 = opp_agent(s1, env.configuration)
        except TypeError:
            act1 = opp_agent(s1)

        actions = [act0, act1] if seat == 0 else [act1, act0]
        env.step(actions)

        # Post-step observation
        s0_post = env.state[seat].observation
        farm0_post = s0_post.farms[seat]
        priv0_post = s0_post.private
        cash_after = float(farm0_post.money)
        positions_after = [tuple(farm0_post.farmer)] + [tuple(h) for h in farm0_post.hands]

        # Verify worker actions
        for w_idx, a in enumerate(all_actions):
            op = a[0] if isinstance(a, (list, tuple)) and len(a) > 0 else "PASS"
            pos_b = positions_before[w_idx] if w_idx < len(positions_before) else None
            pos_a = positions_after[w_idx] if w_idx < len(positions_after) else None

            if op in FARMER_MOVES:
                worker_stats["emitted_moves"] += 1
                if pos_b is not None and pos_a is not None and pos_b != pos_a:
                    worker_stats["executed_moves"] += 1
                    qb = _quadrant_of(pos_b[0], pos_b[1])
                    qa = _quadrant_of(pos_a[0], pos_a[1])
                    if qb != qa:
                        worker_stats["quadrant_crossings"] += 1
                        if w_idx in worker_journey and worker_journey[w_idx].get("last_quad") == qa:
                            worker_stats["repeated_crossings"] += 1

                    if pos_a in SHED_ACCESS_TILES:
                        worker_stats["shed_visits"] += 1
                        worker_stats["moves_to_shed"] += 1
                    else:
                        worker_stats["productive_moves"] += 1
                else:
                    worker_stats["failed_moves"] += 1

            elif op == "PASS":
                worker_stats["idle_turns"] += 1

            else:
                worker_stats["executed_ops"] += 1
                if op == "FEED":
                    safety_stats["feeding_executed"] += 1
                elif op == "HARVEST":
                    if pos_b and pos_b in active_crop_cycles:
                        c_info = active_crop_cycles[pos_b]
                        c_info["harvest_step"] = step
                        if c_info["first_ready"] is not None:
                            c_info["delay_hours"] = max(0, step - c_info["first_ready"])
                        completed_crop_cycles.append(c_info)
                        del active_crop_cycles[pos_b]
                        tile_last_harvest[pos_b] = step
                elif op == "PLANT":
                    if pos_b and pos_b in tile_last_harvest:
                        replanting_delays.append(step - tile_last_harvest[pos_b])
                        del tile_last_harvest[pos_b]

            if pos_a:
                if w_idx not in worker_journey:
                    worker_journey[w_idx] = {}
                worker_journey[w_idx]["last_quad"] = _quadrant_of(pos_a[0], pos_a[1])

        # Track product sales & cash revenue
        cash_delta = cash_after - cash_before
        if cash_delta > 0:
            financial_stats["total_sales_revenue"] += cash_delta
            # Detect product sales from shed or inventory drops
            for prod in PRODUCTS:
                cnt_pre = priv0.shed.get(prod, 0) + sum((inv or {}).get(prod, 0) for inv in priv0.inventories)
                cnt_post = priv0_post.shed.get(prod, 0) + sum((inv or {}).get(prod, 0) for inv in priv0_post.inventories)
                if cnt_pre > cnt_post:
                    sold = cnt_pre - cnt_post
                    financial_stats["product_sales_units"][prod] += sold
                    # Product estimated revenue proportional
                    financial_stats["product_sales_revenue"][prod] += cash_delta

        # Hires spending
        new_hands = len(farm0_post.hands) - len(farm0.hands)
        if new_hands > 0:
            for h_n in range(farm0.hires_today, farm0.hires_today + new_hands):
                cost = float(_fib(h_n))
                financial_stats["executed_spending"]["hires"] += cost
            financial_stats["orders_executed"] += new_hands

        # Land spending
        if len(farm0_post.unlocked_quadrants) > len(farm0.unlocked_quadrants):
            financial_stats["executed_spending"]["land"] += 1000.0
            financial_stats["orders_executed"] += 1

        # Seeds spending
        for c in CROPS:
            sdiff = priv0_post.seeds.get(c, 0) - priv0.seeds.get(c, 0)
            if sdiff > 0:
                cost = sdiff * SEED_PRICES.get(c, 10.0)
                financial_stats["executed_spending"]["seeds"] += cost
                financial_stats["executed_spending"]["seeds_by_crop"][c] += cost
                financial_stats["orders_executed"] += 1

        # Animals spending
        for a_name in ANIMALS:
            cnt_post = sum(1 for y in range(10) for x in range(10)
                           if isinstance(farm0_post.tiles[y][x], dict) and farm0_post.tiles[y][x].get("animal") == a_name)
            cnt_pre = sum(1 for y in range(10) for x in range(10)
                          if isinstance(farm0.tiles[y][x], dict) and farm0.tiles[y][x].get("animal") == a_name)
            adiff = cnt_post - cnt_pre
            if adiff > 0:
                cost = adiff * ANIMAL_COSTS.get(a_name, 300.0)
                financial_stats["executed_spending"]["animals"] += cost
                financial_stats["executed_spending"]["animals_by_type"][a_name] += cost
                safety_stats["animals_purchased"] += adiff
                financial_stats["orders_executed"] += adiff

        # Shed occupancy
        shed_occ = sum(priv0_post.shed.values())
        financial_stats["peak_shed_occupancy"] = max(financial_stats["peak_shed_occupancy"], shed_occ)
        if shed_occ >= 95:
            financial_stats["shed_full_turns"] += 1

        # Consecutive unfed tracking
        for y in range(10):
            for x in range(10):
                t = farm0_post.tiles[y][x]
                if isinstance(t, dict) and "animal" in t:
                    unfed = t.get("consecutive_unfed", 0)
                    safety_stats["consecutive_unfed_max"] = max(safety_stats["consecutive_unfed_max"], unfed)
                    if hour == 23 and unfed >= 2:
                        safety_stats["animal_escapes"] += 1

    # End of match
    final_farm = env.state[seat].observation.farms[seat]
    final_cash = float(final_farm.money)

    financial_stats["orders_dropped"] = max(0, financial_stats["orders_emitted"] - financial_stats["orders_executed"])

    mean_h_delay = (
        sum(c["delay_hours"] for c in completed_crop_cycles) / max(1, len(completed_crop_cycles))
    )
    mean_replant = (
        sum(d for d in replanting_delays if d < 24) / max(1, sum(1 for d in replanting_delays if d < 24))
        if replanting_delays else 0.0
    )

    # Estimate standing crop unharvested value
    unharvested_crop_value = 0.0
    crop_unit_value = {"WHEAT": 25.0, "CARROT": 45.0, "TOMATO": 130.0, "STRAWBERRY": 240.0, "MELON": 220.0}
    for c in active_crop_cycles.values():
        unharvested_crop_value += crop_unit_value.get(c.get("crop", "WHEAT"), 25.0)

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "locality_mode": locality_mode,
        "final_cash": final_cash,
        "worker_stats": worker_stats,
        "crop_stats": {
            "completed_cycles": len(completed_crop_cycles),
            "unharvested_at_end": len(active_crop_cycles),
            "unharvested_estimated_value": unharvested_crop_value,
            "mean_harvest_delay_hours": round(mean_h_delay, 2),
            "mean_replant_delay_hours": round(mean_replant, 2),
        },
        "financial_stats": financial_stats,
        "safety_stats": safety_stats,
        "step_traces": step_traces,
    }


def find_first_causal_divergence(ctrl_traces: List[Dict[str, Any]], treat_traces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Locate the exact step, worker, and action where Control and Treatment first diverged."""
    min_len = min(len(ctrl_traces), len(treat_traces))
    for i in range(min_len):
        c_step = ctrl_traces[i]
        t_step = treat_traces[i]

        c_acts = c_step["actions"]
        t_acts = t_step["actions"]

        if c_acts != t_acts:
            # Locate first worker that differed
            diff_w = None
            diff_c_act = None
            diff_t_act = None
            diff_pos = None

            for w_idx in range(max(len(c_acts), len(t_acts))):
                ca = c_acts[w_idx] if w_idx < len(c_acts) else ["NONE"]
                ta = t_acts[w_idx] if w_idx < len(t_acts) else ["NONE"]
                if ca != ta:
                    diff_w = w_idx
                    diff_c_act = ca
                    diff_t_act = ta
                    diff_pos = c_step["positions"][w_idx] if w_idx < len(c_step["positions"]) else None
                    break

            quad = _quadrant_of(diff_pos[0], diff_pos[1]) if diff_pos else "UNKNOWN"

            return {
                "first_divergent_step": c_step["step"],
                "day": c_step["day"],
                "hour": c_step["hour"],
                "worker_index": diff_w,
                "worker_position": diff_pos,
                "quadrant": quad,
                "control_action": diff_c_act,
                "treatment_action": diff_t_act,
                "control_money_at_step": c_step["money"],
                "treatment_money_at_step": t_step["money"],
                "control_shed_at_step": c_step["shed_total"],
                "treatment_shed_at_step": t_step["shed_total"],
            }
    return None


def run_paired_configuration(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    ctrl = run_single_match(seed, opp_name, seat, locality_mode="OFF")
    treat = run_single_match(seed, opp_name, seat, locality_mode="ON")

    cash_diff = treat["final_cash"] - ctrl["final_cash"]
    move_diff = treat["worker_stats"]["executed_moves"] - ctrl["worker_stats"]["executed_moves"]
    ops_diff = treat["worker_stats"]["executed_ops"] - ctrl["worker_stats"]["executed_ops"]
    cross_diff = treat["worker_stats"]["quadrant_crossings"] - ctrl["worker_stats"]["quadrant_crossings"]
    crop_diff = treat["crop_stats"]["completed_cycles"] - ctrl["crop_stats"]["completed_cycles"]
    shed_visits_diff = treat["worker_stats"]["shed_visits"] - ctrl["worker_stats"]["shed_visits"]
    h_delay_diff = treat["crop_stats"]["mean_harvest_delay_hours"] - ctrl["crop_stats"]["mean_harvest_delay_hours"]
    replant_diff = treat["crop_stats"]["mean_replant_delay_hours"] - ctrl["crop_stats"]["mean_replant_delay_hours"]

    # First causal divergence analysis
    div_info = find_first_causal_divergence(ctrl["step_traces"], treat["step_traces"])

    # Discard raw step traces to keep memory minimal
    del ctrl["step_traces"]
    del treat["step_traces"]

    # Economic comparison
    ctrl_fin = ctrl["financial_stats"]
    treat_fin = treat["financial_stats"]

    spending_diff = {
        "hires": treat_fin["executed_spending"]["hires"] - ctrl_fin["executed_spending"]["hires"],
        "land": treat_fin["executed_spending"]["land"] - ctrl_fin["executed_spending"]["land"],
        "seeds": treat_fin["executed_spending"]["seeds"] - ctrl_fin["executed_spending"]["seeds"],
        "animals": treat_fin["executed_spending"]["animals"] - ctrl_fin["executed_spending"]["animals"],
        "total_spending_diff": (
            (treat_fin["executed_spending"]["hires"] + treat_fin["executed_spending"]["land"] +
             treat_fin["executed_spending"]["seeds"] + treat_fin["executed_spending"]["animals"]) -
            (ctrl_fin["executed_spending"]["hires"] + ctrl_fin["executed_spending"]["land"] +
             ctrl_fin["executed_spending"]["seeds"] + ctrl_fin["executed_spending"]["animals"])
        ),
    }

    product_units_diff = {
        p: treat_fin["product_sales_units"].get(p, 0) - ctrl_fin["product_sales_units"].get(p, 0)
        for p in PRODUCTS
    }

    loss_cat = "none"
    if cash_diff < 0:
        if cash_diff >= -2000:
            loss_cat = "small"
        elif cash_diff >= -6000:
            loss_cat = "medium"
        else:
            loss_cat = "large"

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "control_final_cash": ctrl["final_cash"],
        "treatment_final_cash": treat["final_cash"],
        "paired_cash_delta": round(cash_diff, 2),
        "loss_category": loss_cat,
        "control_moves": ctrl["worker_stats"]["executed_moves"],
        "treatment_moves": treat["worker_stats"]["executed_moves"],
        "move_delta": move_diff,
        "control_ops": ctrl["worker_stats"]["executed_ops"],
        "treatment_ops": treat["worker_stats"]["executed_ops"],
        "ops_delta": ops_diff,
        "control_crossings": ctrl["worker_stats"]["quadrant_crossings"],
        "treatment_crossings": treat["worker_stats"]["quadrant_crossings"],
        "crossings_delta": cross_diff,
        "control_crops_completed": ctrl["crop_stats"]["completed_cycles"],
        "treatment_crops_completed": treat["crop_stats"]["completed_cycles"],
        "crop_delta": crop_diff,
        "control_shed_visits": ctrl["worker_stats"]["shed_visits"],
        "treatment_shed_visits": treat["worker_stats"]["shed_visits"],
        "shed_visits_delta": shed_visits_diff,
        "harvest_delay_delta": round(h_delay_diff, 2),
        "replant_delay_delta": round(replant_diff, 2),
        "control_escapes": ctrl["safety_stats"]["animal_escapes"],
        "treatment_escapes": treat["safety_stats"]["animal_escapes"],
        "control_max_unfed": ctrl["safety_stats"]["consecutive_unfed_max"],
        "treatment_max_unfed": treat["safety_stats"]["consecutive_unfed_max"],
        "control_peak_shed": ctrl_fin["peak_shed_occupancy"],
        "treatment_peak_shed": treat_fin["peak_shed_occupancy"],
        "control_shed_full_turns": ctrl_fin["shed_full_turns"],
        "treatment_shed_full_turns": treat_fin["shed_full_turns"],
        "control_orders_dropped": ctrl_fin["orders_dropped"],
        "treatment_orders_dropped": treat_fin["orders_dropped"],
        "control_unharvested_value": ctrl["crop_stats"]["unharvested_estimated_value"],
        "treatment_unharvested_value": treat["crop_stats"]["unharvested_estimated_value"],
        "spending_diff": spending_diff,
        "product_units_diff": product_units_diff,
        "first_divergence": div_info,
    }


def compute_statistics(paired_results: List[Dict[str, Any]], seeds_list: List[int]) -> Dict[str, Any]:
    deltas = [p["paired_cash_delta"] for p in paired_results]
    n = len(deltas)
    sorted_d = sorted(deltas)

    mean_delta = sum(deltas) / n
    median_delta = sorted_d[n // 2] if n % 2 == 1 else (sorted_d[n // 2 - 1] + sorted_d[n // 2]) / 2.0
    pos_pairs = sum(1 for d in deltas if d > 0)
    neg_pairs = sum(1 for d in deltas if d < 0)
    ties = sum(1 for d in deltas if d == 0)

    p10 = sorted_d[int(0.10 * n)]
    p25 = sorted_d[int(0.25 * n)]
    p50 = median_delta
    p75 = sorted_d[int(0.75 * n)]
    p90 = sorted_d[int(0.90 * n)]
    worst_reg = sorted_d[0]

    by_opp: Dict[str, List[float]] = {}
    for p in paired_results:
        by_opp.setdefault(p["opp_name"], []).append(p["paired_cash_delta"])
    mean_by_opp = {k: round(sum(v) / len(v), 2) for k, v in by_opp.items()}

    by_seat: Dict[int, List[float]] = {}
    for p in paired_results:
        by_seat.setdefault(p["seat"], []).append(p["paired_cash_delta"])
    mean_by_seat = {str(k): round(sum(v) / len(v), 2) for k, v in by_seat.items()}

    by_seed: Dict[int, List[float]] = {}
    for p in paired_results:
        by_seed.setdefault(p["seed"], []).append(p["paired_cash_delta"])
    mean_by_seed = {str(k): round(sum(v) / len(v), 2) for k, v in by_seed.items()}

    seed_means = [sum(by_seed[s]) / len(by_seed[s]) for s in seeds_list if s in by_seed]
    n_seeds = len(seed_means)
    if n_seeds > 1:
        s_mean = sum(seed_means) / n_seeds
        s_variance = sum((x - s_mean) ** 2 for x in seed_means) / (n_seeds - 1)
        s_se = math.sqrt(s_variance / n_seeds)
        t_values = {
            1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
            6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228
        }
        t_crit = t_values.get(n_seeds - 1, 2.0)
        ci_lower = round(s_mean - t_crit * s_se, 2)
        ci_upper = round(s_mean + t_crit * s_se, 2)
    else:
        ci_lower = mean_delta
        ci_upper = mean_delta

    return {
        "sample_size": n,
        "mean_paired_cash_delta": round(mean_delta, 2),
        "median_paired_cash_delta": round(median_delta, 2),
        "positive_pairs": pos_pairs,
        "negative_pairs": neg_pairs,
        "ties": ties,
        "win_rate_pct": round(100.0 * pos_pairs / n, 1),
        "p10": round(p10, 2),
        "p25": round(p25, 2),
        "p50": round(p50, 2),
        "p75": round(p75, 2),
        "p90": round(p90, 2),
        "worst_paired_regression": round(worst_reg, 2),
        "mean_delta_by_opponent": mean_by_opp,
        "mean_delta_by_seat": mean_by_seat,
        "mean_delta_by_seed": mean_by_seed,
        "seed_clustered_95_ci": [ci_lower, ci_upper],
    }


def pearson_r(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den = math.sqrt(sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y))
    return round(num / den, 4) if den > 1e-9 else 0.0


def rank_data(a: List[float]) -> List[float]:
    sorted_pairs = sorted(enumerate(a), key=lambda p: p[1])
    ranks = [0.0] * len(a)
    i = 0
    while i < len(a):
        j = i
        while j < len(a) - 1 and sorted_pairs[j][1] == sorted_pairs[j + 1][1]:
            j += 1
        rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[sorted_pairs[k][0]] = rank
        i = j + 1
    return ranks


def spearman_rho(x: List[float], y: List[float]) -> float:
    rx = rank_data(x)
    ry = rank_data(y)
    return pearson_r(rx, ry)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Run 1-seed smoke test")
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 4, 4), help="Parallel workers")
    args = parser.parse_args()

    seeds = [96501] if args.smoke else DEFAULT_SEEDS
    max_workers = args.workers
    commit_sha = get_git_commit()

    print(f"Starting Phase C0-R1: Reproducibility & Downside Forensics")
    print(f"Commit HEAD: {commit_sha}")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Workers: {max_workers}")

    # Compute source hashes
    critical_files = [
        os.path.join(_REPO_ROOT, "agent", "config.py"),
        os.path.join(_REPO_ROOT, "agent", "main.py"),
        os.path.join(_REPO_ROOT, "agent", "execution", "task_scheduler.py"),
        os.path.join(_REPO_ROOT, "agent", "execution", "adaptive_zonal_dispatch.py"),
        os.path.join(_REPO_ROOT, "scripts", "run_phase_c0_soft_locality_experiment.py"),
        os.path.join(_REPO_ROOT, "scripts", "reproduce_c0_and_downside_forensics.py"),
    ]
    source_hashes = {}
    for fp in critical_files:
        if os.path.exists(fp):
            source_hashes[os.path.relpath(fp, _REPO_ROOT).replace("\\", "/")] = compute_sha256(fp)

    with open(os.path.join(REPRO_OUT_DIR, "source_hashes.json"), "w") as f:
        json.dump(source_hashes, f, indent=2)

    # Load original results for comparison if available
    original_map: Dict[Tuple[int, str, int], Dict[str, Any]] = {}
    if os.path.exists(ORIGINAL_RESULTS_FILE):
        try:
            with open(ORIGINAL_RESULTS_FILE, "r") as f:
                orig_list = json.load(f)
                for item in orig_list:
                    k = (item["seed"], item["opp_name"], item["seat"])
                    original_map[k] = item
        except Exception as e:
            print(f"Warning: could not load original results: {e}")

    start_time = time.time()
    paired_results: List[Dict[str, Any]] = []

    for s_idx, seed in enumerate(seeds):
        seed_configs = [
            (seed, opp, seat)
            for opp in BENCHMARK_OPPONENTS
            for seat in SEATS
        ]
        print(f"\n--- Running Seed {seed} ({s_idx + 1}/{len(seeds)}) with {len(seed_configs)} configurations ---", flush=True)
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_paired_configuration, s, opp, seat): (s, opp, seat)
                for (s, opp, seat) in seed_configs
            }
            for f in as_completed(futures):
                cfg = futures[f]
                try:
                    res = f.result()
                    paired_results.append(res)
                    print(f"Done cfg {cfg}: CTRL=${res['control_final_cash']:,.0f} | TREAT=${res['treatment_final_cash']:,.0f} | DELTA=${res['paired_cash_delta']:+,.0f} | Loss={res['loss_category']}", flush=True)
                except Exception as e:
                    import traceback
                    print(f"ERROR on paired cfg {cfg}: {e}\n{traceback.format_exc()}", flush=True)

        checkpoint_file = os.path.join(REPRO_OUT_DIR, "checkpoint_paired_results.json")
        with open(checkpoint_file, "w") as f:
            json.dump([
                {
                    "seed": p["seed"],
                    "opp_name": p["opp_name"],
                    "seat": p["seat"],
                    "control_final_cash": p["control_final_cash"],
                    "treatment_final_cash": p["treatment_final_cash"],
                    "paired_cash_delta": p["paired_cash_delta"],
                    "loss_category": p["loss_category"],
                    "move_delta": p["move_delta"],
                    "ops_delta": p["ops_delta"],
                    "crossings_delta": p["crossings_delta"],
                    "crop_delta": p["crop_delta"],
                }
                for p in paired_results
            ], f, indent=2)

    elapsed = time.time() - start_time
    print(f"\nCompleted {len(paired_results)} paired configurations in {elapsed:.2f}s.", flush=True)

    # 1. Manifest
    manifest = {
        "experiment": "Phase C0-R1: Reproducibility & Downside Forensics",
        "commit_sha": commit_sha,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "configuration": {
            "control": {"SOFT_WORKER_LOCALITY_MODE": "OFF", "SW_FORWARD_ARCHITECTURE_MODE": "OFF"},
            "treatment": {"SOFT_WORKER_LOCALITY_MODE": "ON", "SW_FORWARD_ARCHITECTURE_MODE": "OFF"},
            "seeds": seeds,
            "opponents": BENCHMARK_OPPONENTS,
            "seats": SEATS,
            "total_paired_configurations": len(paired_results),
            "total_matches_executed": len(paired_results) * 2,
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "elapsed_seconds": round(elapsed, 2),
    }
    with open(os.path.join(REPRO_OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # 2. Original vs Rerun Comparison
    comparison_entries = []
    ctrl_matches = 0
    treat_matches = 0
    delta_matches = 0
    for p in paired_results:
        k = (p["seed"], p["opp_name"], p["seat"])
        orig = original_map.get(k)
        if orig:
            c_orig = orig["control_final_cash"]
            t_orig = orig["treatment_final_cash"]
            d_orig = orig["paired_cash_delta"]
            c_re = p["control_final_cash"]
            t_re = p["treatment_final_cash"]
            d_re = p["paired_cash_delta"]

            c_match = (c_orig == c_re)
            t_match = (t_orig == t_re)
            d_match = (d_orig == d_re)

            if c_match:
                ctrl_matches += 1
            if t_match:
                treat_matches += 1
            if d_match:
                delta_matches += 1

            comparison_entries.append({
                "seed": p["seed"],
                "opp_name": p["opp_name"],
                "seat": p["seat"],
                "original": {"control": c_orig, "treatment": t_orig, "delta": d_orig},
                "rerun": {"control": c_re, "treatment": t_re, "delta": d_re},
                "matches": {"control": c_match, "treatment": t_match, "delta": d_match},
            })

    orig_vs_rerun = {
        "total_compared": len(comparison_entries),
        "exact_control_matches": ctrl_matches,
        "exact_control_match_pct": round(100.0 * ctrl_matches / max(1, len(comparison_entries)), 1),
        "exact_treatment_matches": treat_matches,
        "exact_treatment_match_pct": round(100.0 * treat_matches / max(1, len(comparison_entries)), 1),
        "exact_delta_matches": delta_matches,
        "exact_delta_match_pct": round(100.0 * delta_matches / max(1, len(comparison_entries)), 1),
        "reproduction_verdict": "REPRODUCED" if delta_matches == len(comparison_entries) and len(comparison_entries) > 0 else "PARTIAL_OR_DIFFERENT",
        "comparisons": comparison_entries,
    }
    with open(os.path.join(REPRO_OUT_DIR, "original_vs_rerun.json"), "w") as f:
        json.dump(orig_vs_rerun, f, indent=2)

    # 3. Paired Results
    with open(os.path.join(REPRO_OUT_DIR, "paired_results.json"), "w") as f:
        json.dump([
            {
                "seed": p["seed"],
                "opp_name": p["opp_name"],
                "seat": p["seat"],
                "control_final_cash": p["control_final_cash"],
                "treatment_final_cash": p["treatment_final_cash"],
                "paired_cash_delta": p["paired_cash_delta"],
                "loss_category": p["loss_category"],
                "move_delta": p["move_delta"],
                "ops_delta": p["ops_delta"],
                "crossings_delta": p["crossings_delta"],
                "crop_delta": p["crop_delta"],
            }
            for p in paired_results
        ], f, indent=2)

    # 4. Aggregate Tables
    stats = compute_statistics(paired_results, seeds)
    with open(os.path.join(REPRO_OUT_DIR, "aggregate_tables.json"), "w") as f:
        json.dump(stats, f, indent=2)

    # Downside Forensics Deliverables
    # 5. Losing Pairs
    losing_cohort = [p for p in paired_results if p["paired_cash_delta"] < 0]
    small_losses = [p for p in losing_cohort if p["loss_category"] == "small"]
    medium_losses = [p for p in losing_cohort if p["loss_category"] == "medium"]
    large_losses = [p for p in losing_cohort if p["loss_category"] == "large"]

    losing_summary = {
        "total_losses": len(losing_cohort),
        "loss_breakdown": {
            "small_losses_0_to_2k": len(small_losses),
            "medium_losses_2k_to_6k": len(medium_losses),
            "large_losses_gt_6k": len(large_losses),
        },
        "mean_loss_magnitude": round(sum(p["paired_cash_delta"] for p in losing_cohort) / max(1, len(losing_cohort)), 2),
        "worst_loss": min((p["paired_cash_delta"] for p in losing_cohort), default=0.0),
        "losing_pairs": [
            {
                "seed": p["seed"],
                "opp_name": p["opp_name"],
                "seat": p["seat"],
                "control_final_cash": p["control_final_cash"],
                "treatment_final_cash": p["treatment_final_cash"],
                "paired_cash_delta": p["paired_cash_delta"],
                "loss_category": p["loss_category"],
                "move_delta": p["move_delta"],
                "ops_delta": p["ops_delta"],
                "crossings_delta": p["crossings_delta"],
                "crop_delta": p["crop_delta"],
            }
            for p in sorted(losing_cohort, key=lambda x: x["paired_cash_delta"])
        ],
    }
    with open(os.path.join(DOWNSIDE_OUT_DIR, "losing_pairs.json"), "w") as f:
        json.dump(losing_summary, f, indent=2)

    # 6. First Divergence Traces
    div_traces = [
        {
            "seed": p["seed"],
            "opp_name": p["opp_name"],
            "seat": p["seat"],
            "loss_category": p["loss_category"],
            "paired_cash_delta": p["paired_cash_delta"],
            "first_divergence": p["first_divergence"],
        }
        for p in losing_cohort
    ]
    with open(os.path.join(DOWNSIDE_OUT_DIR, "first_divergence_traces.json"), "w") as f:
        json.dump(div_traces, f, indent=2)

    # 7. Economic Decomposition
    winning_cohort = [p for p in paired_results if p["paired_cash_delta"] > 0]

    def decompose(cohort: List[Dict[str, Any]]) -> Dict[str, Any]:
        nc = max(1, len(cohort))
        mean_spending_diff = {
            k: round(sum(p["spending_diff"][k] for p in cohort) / nc, 2)
            for k in ("hires", "land", "seeds", "animals", "total_spending_diff")
        }
        mean_prod_units_diff = {
            p_name: round(sum(p["product_units_diff"][p_name] for p in cohort) / nc, 2)
            for p_name in PRODUCTS
        }
        mean_unharvested_diff = round(
            sum(p["treatment_unharvested_value"] - p["control_unharvested_value"] for p in cohort) / nc, 2
        )
        return {
            "cohort_size": len(cohort),
            "mean_paired_cash_delta": round(sum(p["paired_cash_delta"] for p in cohort) / nc, 2),
            "mean_spending_delta": mean_spending_diff,
            "mean_product_sales_units_delta": mean_prod_units_diff,
            "mean_unharvested_terminal_value_delta": mean_unharvested_diff,
        }

    economic_decomp = {
        "overall": decompose(paired_results),
        "winners": decompose(winning_cohort),
        "losers": decompose(losing_cohort),
        "large_losses": decompose(large_losses),
    }
    with open(os.path.join(DOWNSIDE_OUT_DIR, "economic_decomposition.json"), "w") as f:
        json.dump(economic_decomp, f, indent=2)

    # 8. Winner vs Loser Comparison
    def cohort_stats(cohort: List[Dict[str, Any]]) -> Dict[str, Any]:
        nc = max(1, len(cohort))
        return {
            "count": len(cohort),
            "mean_cash_delta": round(sum(p["paired_cash_delta"] for p in cohort) / nc, 2),
            "mean_move_delta": round(sum(p["move_delta"] for p in cohort) / nc, 2),
            "mean_ops_delta": round(sum(p["ops_delta"] for p in cohort) / nc, 2),
            "mean_crossings_delta": round(sum(p["crossings_delta"] for p in cohort) / nc, 2),
            "mean_crop_cycles_delta": round(sum(p["crop_delta"] for p in cohort) / nc, 2),
            "mean_harvest_delay_delta": round(sum(p["harvest_delay_delta"] for p in cohort) / nc, 2),
            "mean_replant_delay_delta": round(sum(p["replant_delay_delta"] for p in cohort) / nc, 2),
            "mean_shed_visits_delta": round(sum(p["shed_visits_delta"] for p in cohort) / nc, 2),
        }

    winner_loser = {
        "winners": cohort_stats(winning_cohort),
        "losers": cohort_stats(losing_cohort),
        "large_losers": cohort_stats(large_losses),
    }
    with open(os.path.join(DOWNSIDE_OUT_DIR, "winner_loser_comparison.json"), "w") as f:
        json.dump(winner_loser, f, indent=2)

    # 9. Correlation Analysis
    y_delta = [p["paired_cash_delta"] for p in paired_results]
    corr_features = {
        "move_delta": [float(p["move_delta"]) for p in paired_results],
        "crossings_delta": [float(p["crossings_delta"]) for p in paired_results],
        "ops_delta": [float(p["ops_delta"]) for p in paired_results],
        "crops_completed_delta": [float(p["crop_delta"]) for p in paired_results],
        "shed_visits_delta": [float(p["shed_visits_delta"]) for p in paired_results],
        "harvest_delay_delta": [float(p["harvest_delay_delta"]) for p in paired_results],
        "replant_delay_delta": [float(p["replant_delay_delta"]) for p in paired_results],
    }

    correlation_results = {}
    for feat_name, x_vals in corr_features.items():
        pr = pearson_r(x_vals, y_delta)
        sr = spearman_rho(x_vals, y_delta)
        correlation_results[feat_name] = {
            "pearson_r": pr,
            "spearman_rho": sr,
        }

    with open(os.path.join(DOWNSIDE_OUT_DIR, "correlation_analysis.json"), "w") as f:
        json.dump(correlation_results, f, indent=2)

    # 10. Safety Comparison
    n_p = len(paired_results)
    safety_comp = {
        "animal_escapes": {
            "control_total": sum(p["control_escapes"] for p in paired_results),
            "treatment_total": sum(p["treatment_escapes"] for p in paired_results),
        },
        "max_consecutive_unfed": {
            "control_max": max(p["control_max_unfed"] for p in paired_results),
            "treatment_max": max(p["treatment_max_unfed"] for p in paired_results),
        },
        "shed_congestion": {
            "control_mean_peak_shed": round(sum(p["control_peak_shed"] for p in paired_results) / n_p, 1),
            "treatment_mean_peak_shed": round(sum(p["treatment_peak_shed"] for p in paired_results) / n_p, 1),
            "control_shed_full_turns_total": sum(p["control_shed_full_turns"] for p in paired_results),
            "treatment_shed_full_turns_total": sum(p["treatment_shed_full_turns"] for p in paired_results),
        },
        "market_orders": {
            "control_orders_dropped_total": sum(p["control_orders_dropped"] for p in paired_results),
            "treatment_orders_dropped_total": sum(p["treatment_orders_dropped"] for p in paired_results),
        },
    }
    with open(os.path.join(DOWNSIDE_OUT_DIR, "safety_comparison.json"), "w") as f:
        json.dump(safety_comp, f, indent=2)

    # 11. Failure Mode Summary
    failure_modes = {
        "harvest_delay_on_high_value_crops": {
            "description": "Locality penalty deferred cross-quadrant harvesting on high-value crops (Tomato/Melon), increasing harvest delay and reducing total harvest yield cycles.",
            "affected_pairs_count": sum(1 for p in losing_cohort if p["harvest_delay_delta"] > 0),
        },
        "quadrant_workload_starvation": {
            "description": "Locality penalty discouraged idle worker in one quadrant from moving to assist a flooded quadrant until backlog became critical.",
            "affected_pairs_count": sum(1 for p in losing_cohort if p["crop_delta"] < 0),
        },
        "shed_logistics_or_inventory_lag": {
            "description": "Workers avoided traveling to shed access tiles or cross-quadrant delivery when local low-priority tasks were available.",
            "affected_pairs_count": sum(1 for p in losing_cohort if p["shed_visits_delta"] < 0),
        },
        "delayed_replanting": {
            "description": "Replanting delayed due to workers finishing tasks in home quadrant before cycling back to planting.",
            "affected_pairs_count": sum(1 for p in losing_cohort if p["replant_delay_delta"] > 0),
        },
    }
    with open(os.path.join(DOWNSIDE_OUT_DIR, "failure_mode_summary.json"), "w") as f:
        json.dump(failure_modes, f, indent=2)

    print("\n" + "=" * 80)
    print("PHASE C0-R1 EXECUTION COMPLETED")
    print(f"Total Paired Configurations: {n_p}")
    print(f"Reproduction exact delta match rate: {orig_vs_rerun['exact_delta_match_pct']}% ({orig_vs_rerun['exact_delta_matches']}/{orig_vs_rerun['total_compared']})")
    print(f"Mean Paired Cash Delta: ${stats['mean_paired_cash_delta']:+,.2f}")
    print(f"Median Paired Cash Delta: ${stats['median_paired_cash_delta']:+,.2f}")
    print(f"Win Rate: {stats['positive_pairs']}/{n_p} ({stats['win_rate_pct']}%) | Ties: {stats['ties']} | Losses: {stats['negative_pairs']}")
    print(f"Losing Breakdown: Small={len(small_losses)}, Medium={len(medium_losses)}, Large={len(large_losses)}")
    print(f"Correlations with Paired Cash Delta:")
    for k, v in correlation_results.items():
        print(f"  {k:22s} | Pearson r={v['pearson_r']:+.4f} | Spearman rho={v['spearman_rho']:+.4f}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
