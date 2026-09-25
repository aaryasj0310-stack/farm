"""Phase M0-C-R1: Revalidation of Corrected Same-Turn Crop Pipeline Gating.

Evaluates 3 arms across the consumed discovery panel (Seeds 97013–97022 x 5 opponents x 2 seats = 100 scenario cells):
- C0: CONTROL (SAME_TURN_CROP_PIPELINE_MODE = "OFF")
- C1: GLOBAL M0-A (SAME_TURN_CROP_PIPELINE_MODE = "GLOBAL")
- C2R1: CORRECTED SELECTIVE (SAME_TURN_CROP_PIPELINE_MODE = "SELECTIVE")

Total: 100 cells x 3 arms = 300 real-engine matches.

Features Authoritative Instrumentation for:
- Animal escapes & feeding state transitions
- Plant deaths to WEED from watering failure
- Midnight shed overflow units discarded
- Capital transactions (HIRE, BUY_LAND, BUY_SEED, BUY_ANIMAL)

Deliverables under simulations/results/phase_m0_c_r1/:
- manifest.json
- matched_results.json
- aggregate_tables.json
- clustered_statistics.json
- gate_decisions.json
- rejection_reason_summary.json
- crop_pipeline_summary.json
- storage_and_overflow.json
- safety_comparison.json
- transaction_timing.json
- losing_pair_forensics.json
- representative_traces.json
- unresolved_limitations.json
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_c_r1")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_SEEDS = list(range(97013, 97023))  # 97013–97022 (Consumed discovery seeds)
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]
ARMS = ["C0", "C1", "C2R1"]


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


def _quadrant_of(x: int, y: int) -> str:
    return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def run_single_arm_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    """Run one single match under specified arm ('C0', 'C1', 'C2R1')."""
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    from kaggle_environments import make
    import config
    from agent.main import (
        agent,
        reset_agent_state,
        get_crop_pipeline_telemetry,
        get_crop_pipeline_shadow_decisions,
        verify_post_turn_pipelines,
    )
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    pipeline_mode = "OFF"
    if arm == "C1":
        pipeline_mode = "GLOBAL"
    elif arm == "C2R1":
        pipeline_mode = "SELECTIVE"

    config.set_same_turn_crop_pipeline_mode(pipeline_mode)
    config.set_midnight_storage_dump_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"

    reset_agent_state()
    reset_sw_tranche_controller()

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    # Telemetry data structures
    worker_stats = {
        "total_worker_turns": 0,
        "emitted_moves": 0,
        "harvest_actions": 0,
        "plant_actions": 0,
        "water_actions": 0,
    }
    storage_stats = {
        "peak_shed_occupancy": 0,
        "shed_turns_ge_90": 0,
        "shed_turns_ge_95": 0,
        "shed_turns_at_capacity": 0,
        "first_turn_ge_90": None,
        "first_turn_ge_95": None,
        "first_turn_at_capacity": None,
        "total_overflow_units_lost": 0,
        "overflow_events": 0,
    }
    capital_stats = {
        "transactions": [],
        "first_land_purchase_step": None,
        "first_hire_step": None,
        "first_animal_purchase_step": None,
        "total_seed_spent": 0.0,
        "total_land_spent": 0.0,
        "total_hire_spent": 0.0,
        "total_animal_spent": 0.0,
    }
    safety_stats = {
        "animal_escapes": 0,
        "days_with_consecutive_unfed_1": 0,
        "production_days_missed_feed": 0,
        "care_bonuses_lost": 0,
        "max_consecutive_unfed": 0,
        "plant_deaths_from_watering_failure": 0,
        "single_skipped_watering_days": 0,
        "critical_watering_rescues": 0,
    }
    tile_empty_turns = 0
    tile_prev_state: Dict[Tuple[int, int], Dict[str, Any]] = {}
    completed_crop_cycles = 0

    trace_summary = []
    step_num = 0

    while not env.done:
        state_pre = env.state[seat]
        obs_pre = state_pre.observation
        farms_pre = obs_pre.farms[seat]
        priv_pre = obs_pre.private

        shed_items = sum(priv_pre.shed.values()) if hasattr(priv_pre, "shed") else 0
        carried_items = sum(sum(inv.values()) for inv in priv_pre.inventories) if hasattr(priv_pre, "inventories") else 0

        if shed_items > storage_stats["peak_shed_occupancy"]:
            storage_stats["peak_shed_occupancy"] = shed_items
        if shed_items >= 90:
            storage_stats["shed_turns_ge_90"] += 1
            if storage_stats["first_turn_ge_90"] is None:
                storage_stats["first_turn_ge_90"] = step_num
        if shed_items >= 95:
            storage_stats["shed_turns_ge_95"] += 1
            if storage_stats["first_turn_ge_95"] is None:
                storage_stats["first_turn_ge_95"] = step_num
        if shed_items >= 100:
            storage_stats["shed_turns_at_capacity"] += 1
            if storage_stats["first_turn_at_capacity"] is None:
                storage_stats["first_turn_at_capacity"] = step_num

        # Check end-of-day overflow discard at midnight (hour 23 -> hour 0 transition)
        if obs_pre.hour == 23:
            room = max(0, 100 - shed_items)
            if carried_items > room:
                overflow = carried_items - room
                storage_stats["total_overflow_units_lost"] += overflow
                storage_stats["overflow_events"] += 1

        # Check safety metrics: animals & plants state transitions
        for r in range(10):
            for c in range(10):
                tile = farms_pre.tiles[r][c]
                q = _quadrant_of(c, r)
                if q in ("NW", "NE"):
                    if tile is None or (not getattr(tile, "is_plant", False) and not getattr(tile, "is_animal", False) and not getattr(tile, "is_building", False)):
                        tile_empty_turns += 1

                prev_t = tile_prev_state.get((r, c))

                # Animal transition check at midnight
                if obs_pre.hour == 0 and prev_t and prev_t.get("is_animal"):
                    # Check if animal disappeared (escaped)
                    is_still_anim = tile is not None and getattr(tile, "is_animal", False)
                    if not is_still_anim and prev_t.get("consecutive_unfed", 0) >= 1 and not prev_t.get("fed_today", False):
                        safety_stats["animal_escapes"] += 1

                # Plant transition check at midnight
                if obs_pre.hour == 0 and prev_t and prev_t.get("is_plant"):
                    # Check if plant became WEED
                    is_weed_now = tile is not None and (getattr(tile, "crop", None) == "WEED" or getattr(tile, "is_weed", False))
                    if is_weed_now and prev_t.get("consecutive_unwatered", 0) >= 1 and not prev_t.get("watered_today", False):
                        safety_stats["plant_deaths_from_watering_failure"] += 1

                # Record animal ongoing metrics
                if tile is not None and getattr(tile, "is_animal", False):
                    unfed = getattr(tile, "consecutive_unfed", 0)
                    if unfed > safety_stats["max_consecutive_unfed"]:
                        safety_stats["max_consecutive_unfed"] = unfed
                    if unfed == 1 and obs_pre.hour == 23 and not getattr(tile, "fed_today", False):
                        safety_stats["days_with_consecutive_unfed_1"] += 1

                # Record plant ongoing metrics
                if tile is not None and getattr(tile, "is_plant", False):
                    unwatered = getattr(tile, "consecutive_unwatered", 0)
                    if unwatered == 1 and obs_pre.hour == 23 and not getattr(tile, "watered_today", False):
                        safety_stats["single_skipped_watering_days"] += 1

        # Track completed crop cycles
        for r in range(10):
            for c in range(10):
                t_curr = farms_pre.tiles[r][c]
                is_plant_curr = t_curr is not None and getattr(t_curr, "is_plant", False)
                prev = tile_prev_state.get((r, c))
                if prev and prev.get("is_plant") and not is_plant_curr:
                    completed_crop_cycles += 1
                tile_prev_state[(r, c)] = {
                    "is_plant": is_plant_curr,
                    "is_animal": t_curr is not None and getattr(t_curr, "is_animal", False),
                    "crop": getattr(t_curr, "crop", None) if t_curr is not None else None,
                    "yield": getattr(t_curr, "yield_units", 0) if t_curr is not None else 0,
                    "consecutive_unfed": getattr(t_curr, "consecutive_unfed", 0) if t_curr is not None else 0,
                    "fed_today": getattr(t_curr, "fed_today", False) if t_curr is not None else False,
                    "consecutive_unwatered": getattr(t_curr, "consecutive_unwatered", 0) if t_curr is not None else 0,
                    "watered_today": getattr(t_curr, "watered_today", False) if t_curr is not None else False,
                }

        # Agent decision
        action = agent(obs_pre, env.configuration)
        try:
            opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_action = opp_agent(env.state[1 - seat].observation)
        actions = [action, opp_action] if seat == 0 else [opp_action, action]

        # Record action statistics
        all_acts = [action.get("farmer", ["PASS"])] + action.get("hands", [])
        worker_stats["total_worker_turns"] += len(all_acts)
        for a in all_acts:
            op = a[0] if isinstance(a, list) and a else str(a)
            if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                worker_stats["emitted_moves"] += 1
            elif op == "HARVEST":
                worker_stats["harvest_actions"] += 1
            elif op == "PLANT":
                worker_stats["plant_actions"] += 1
            elif op == "WATER":
                worker_stats["water_actions"] += 1

        # Trace record
        if step_num in (24, 72, 120, 168, 240, 360, 480, 600, 719):
            animals_now = sum(1 for r in range(10) for c in range(10) if farms_pre.tiles[r][c] is not None and getattr(farms_pre.tiles[r][c], "is_animal", False))
            trace_summary.append({
                "step": step_num,
                "day": obs_pre.day,
                "hour": obs_pre.hour,
                "money": float(farms_pre.money),
                "shed_items": shed_items,
                "carried_items": carried_items,
                "animals": animals_now,
            })

        # Track transactions pre-step vs post-step
        cash_pre = float(farms_pre.money)
        quadrants_pre = set(farms_pre.unlocked_quadrants)
        hands_pre = len(farms_pre.hands)

        env.step(actions)
        step_num += 1

        obs_post = env.state[seat].observation
        farms_post = obs_post.farms[seat]
        cash_post = float(farms_post.money)
        delta_cash = cash_pre - cash_post

        # Detect actual transactions executed
        # Land
        quadrants_post = set(farms_post.unlocked_quadrants)
        if len(quadrants_post) > len(quadrants_pre):
            new_quad = list(quadrants_post - quadrants_pre)[0]
            land_cost = 1000.0 if new_quad == "NE" else 2000.0
            capital_stats["total_land_spent"] += land_cost
            if capital_stats["first_land_purchase_step"] is None:
                capital_stats["first_land_purchase_step"] = step_num
            capital_stats["transactions"].append({
                "step": step_num, "day": obs_pre.day, "type": "BUY_LAND", "quadrant": new_quad, "cost": land_cost
            })

        # Hires
        hands_post = len(farms_post.hands)
        if hands_post > hands_pre:
            hire_cost = max(0.0, delta_cash)
            capital_stats["total_hire_spent"] += hire_cost
            if capital_stats["first_hire_step"] is None:
                capital_stats["first_hire_step"] = step_num
            capital_stats["transactions"].append({
                "step": step_num, "day": obs_pre.day, "type": "HIRE", "cost": hire_cost
            })

        # Market seed/animal orders
        for mo in action.get("market", []):
            if isinstance(mo, list) and len(mo) >= 2:
                cmd = mo[0]
                item = mo[1]
                qty = mo[2] if len(mo) > 2 else 1
                if cmd == "BUY_SEED":
                    seed_cost = 10.0 * qty if item == "WHEAT" else (20.0 * qty if item == "CARROT" else 80.0 * qty)
                    capital_stats["total_seed_spent"] += seed_cost
                elif cmd == "BUY_ANIMAL":
                    anim_cost = 600.0 * qty if item == "COW" else (400.0 * qty if item == "SHEEP" else 200.0 * qty)
                    capital_stats["total_animal_spent"] += anim_cost
                    if capital_stats["first_animal_purchase_step"] is None:
                        capital_stats["first_animal_purchase_step"] = step_num

        verify_post_turn_pipelines(obs_post, player_id=seat)

    p0_reward = env.steps[-1][seat].reward or 0.0
    p0_cash = float(p0_reward)

    pipeline_events = get_crop_pipeline_telemetry()
    shadow_records = get_crop_pipeline_shadow_decisions()

    # Successful pipelines
    success_pipes = [e for e in pipeline_events if e.get("event") == "PIPELINE_EXECUTED_TURN" and e.get("verified_turn_t1")]
    attempted_pipes = [e for e in pipeline_events if e.get("event") == "PIPELINE_EXECUTED_TURN"]

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "arm": arm,
        "final_cash": p0_cash,
        "worker_stats": worker_stats,
        "storage_stats": storage_stats,
        "capital_stats": capital_stats,
        "safety_stats": safety_stats,
        "tile_empty_turns": tile_empty_turns,
        "completed_crop_cycles": completed_crop_cycles,
        "pipeline_attempted_count": len(attempted_pipes),
        "pipeline_success_count": len(success_pipes),
        "shadow_decisions_count": len(shadow_records),
        "shadow_accepted_count": sum(1 for s in shadow_records if s.get("gate_accepted", False)),
        "shadow_rejected_count": sum(1 for s in shadow_records if not s.get("gate_accepted", False)),
        "shadow_decisions": shadow_records,
        "trace_summary": trace_summary,
    }


def compute_distribution(deltas: List[float]) -> Dict[str, Any]:
    if not deltas:
        return {}
    s = sorted(deltas)
    n = len(s)
    mean_val = sum(s) / n
    median_val = s[n // 2] if n % 2 != 0 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    wins = sum(1 for d in s if d > 0)
    ties = sum(1 for d in s if d == 0)
    losses = sum(1 for d in s if d < 0)

    def pctile(p):
        idx = int(round(p * (n - 1)))
        return s[max(0, min(n - 1, idx))]

    return {
        "mean": round(mean_val, 2),
        "median": round(median_val, 2),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate_pct": round(wins / n * 100, 2),
        "p10": round(pctile(0.10), 2),
        "p25": round(pctile(0.25), 2),
        "p50": round(pctile(0.50), 2),
        "p75": round(pctile(0.75), 2),
        "p90": round(pctile(0.90), 2),
        "best": round(s[-1], 2),
        "worst": round(s[0], 2),
        "losses_lt_2500": sum(1 for d in s if d < -2500),
        "losses_lt_5000": sum(1 for d in s if d < -5000),
        "losses_lt_10000": sum(1 for d in s if d < -10000),
    }


def compute_cluster_ci(seed_deltas: Dict[int, List[float]]) -> Dict[str, Any]:
    cluster_means = [sum(v) / len(v) for v in seed_deltas.values() if v]
    K = len(cluster_means)
    if K <= 1:
        return {"mean": 0.0, "ci_95": [0.0, 0.0], "standard_error": 0.0}

    mean_est = sum(cluster_means) / K
    variance = sum((m - mean_est) ** 2 for m in cluster_means) / (K - 1)
    se = math.sqrt(variance / K)
    t_crit = 2.262  # df = 9
    ci_lower = mean_est - t_crit * se
    ci_upper = mean_est + t_crit * se
    return {
        "mean": round(mean_est, 2),
        "standard_error": round(se, 2),
        "ci_95": [round(ci_lower, 2), round(ci_upper, 2)],
        "excludes_zero": bool(ci_lower > 0 or ci_upper < 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Run Phase M0-C-R1 Revalidation")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    git_commit = get_git_commit()
    print("================================================================================")
    print("Kaggriculture Phase M0-C-R1: Corrected Selective Pipeline Revalidation")
    print("================================================================================")
    print(f"Git HEAD: {git_commit}")
    print(f"Consumed Discovery Seeds: {DEFAULT_SEEDS}")
    print(f"Opponents (5): {BENCHMARK_OPPONENTS}")
    print(f"Seats (2): {SEATS}")
    print(f"Arms (3): {ARMS} (C0=Control, C1=Global, C2R1=Corrected Selective)")
    total_cells = len(DEFAULT_SEEDS) * len(BENCHMARK_OPPONENTS) * len(SEATS)
    total_matches = total_cells * len(ARMS)
    print(f"Total Scenario Cells: {total_cells} | Total Matches: {total_matches}")
    print("================================================================================\n")

    t_start = time.time()
    tasks = []
    for s in DEFAULT_SEEDS:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                for arm in ARMS:
                    tasks.append((s, opp, seat, arm))

    match_results = {}
    completed_matches = 0

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        future_map = {
            pool.submit(run_single_arm_match, s, opp, seat, arm): (s, opp, seat, arm)
            for (s, opp, seat, arm) in tasks
        }
        for fut in as_completed(future_map):
            meta = future_map[fut]
            try:
                res = fut.result()
                cell_key = (res["seed"], res["opp_name"], res["seat"])
                if cell_key not in match_results:
                    match_results[cell_key] = {}
                match_results[cell_key][res["arm"]] = res
                completed_matches += 1
                if completed_matches % 30 == 0:
                    print(f"[{completed_matches}/{total_matches}] Completed: Seed {res['seed']} vs {res['opp_name']} Seat {res['seat']} Arm {res['arm']} -> Cash=${res['final_cash']:,.2f}")
            except Exception as exc:
                print(f"[ERROR] Match {meta} failed: {exc}")

    total_duration = time.time() - t_start
    print(f"\nAll {completed_matches} matches executed in {total_duration:.2f}s ({total_duration/60:.2f} min)\n")

    # Match cell aggregation
    matched_cells = []
    global_vs_ctrl_deltas = []
    selective_vs_ctrl_deltas = []
    selective_vs_global_deltas = []

    seed_global_vs_ctrl = {s: [] for s in DEFAULT_SEEDS}
    seed_selective_vs_ctrl = {s: [] for s in DEFAULT_SEEDS}
    seed_selective_vs_global = {s: [] for s in DEFAULT_SEEDS}

    all_shadow_decisions = []
    rejection_reason_counts = {}
    crop_stats = {}

    for (seed, opp, seat), arm_dict in match_results.items():
        if len(arm_dict) == 3:
            c0 = arm_dict["C0"]
            c1 = arm_dict["C1"]
            c2 = arm_dict["C2R1"]

            d_g_vs_c = c1["final_cash"] - c0["final_cash"]
            d_s_vs_c = c2["final_cash"] - c0["final_cash"]
            d_s_vs_g = c2["final_cash"] - c1["final_cash"]

            global_vs_ctrl_deltas.append(d_g_vs_c)
            selective_vs_ctrl_deltas.append(d_s_vs_c)
            selective_vs_global_deltas.append(d_s_vs_g)

            seed_global_vs_ctrl[seed].append(d_g_vs_c)
            seed_selective_vs_ctrl[seed].append(d_s_vs_c)
            seed_selective_vs_global[seed].append(d_s_vs_g)

            for s in c1.get("shadow_decisions", []):
                all_shadow_decisions.append(s)
                c = s.get("old_crop", "UNKNOWN")
                if c not in crop_stats:
                    crop_stats[c] = {"opps": 0, "accepted": 0, "rejected": 0, "executed": 0, "successful": 0}
                crop_stats[c]["opps"] += 1
                if s.get("gate_accepted", False):
                    crop_stats[c]["accepted"] += 1
                else:
                    crop_stats[c]["rejected"] += 1
                    for reason in s.get("rejection_reasons", []):
                        rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1

            matched_cells.append({
                "seed": seed,
                "opp_name": opp,
                "seat": seat,
                "cash": {"C0": c0["final_cash"], "C1": c1["final_cash"], "C2R1": c2["final_cash"]},
                "deltas": {
                    "global_vs_control": d_g_vs_c,
                    "selective_r1_vs_control": d_s_vs_c,
                    "selective_r1_vs_global": d_s_vs_g,
                },
                "cell_details": {
                    "C0": {k: v for k, v in c0.items() if k != "shadow_decisions"},
                    "C1": {k: v for k, v in c1.items() if k != "shadow_decisions"},
                    "C2R1": {k: v for k, v in c2.items() if k != "shadow_decisions"},
                },
            })

    # Distributions
    dist_g_vs_c = compute_distribution(global_vs_ctrl_deltas)
    dist_s_vs_c = compute_distribution(selective_vs_ctrl_deltas)
    dist_s_vs_g = compute_distribution(selective_vs_global_deltas)

    # Clustered CIs
    clustered_g_vs_c = compute_cluster_ci(seed_global_vs_ctrl)
    clustered_s_vs_c = compute_cluster_ci(seed_selective_vs_ctrl)
    clustered_s_vs_g = compute_cluster_ci(seed_selective_vs_global)

    # Seed-level means
    mean_by_seed_g_vs_c = {s: round(sum(seed_global_vs_ctrl[s]) / max(1, len(seed_global_vs_ctrl[s])), 2) for s in DEFAULT_SEEDS}
    mean_by_seed_s_vs_c = {s: round(sum(seed_selective_vs_ctrl[s]) / max(1, len(seed_selective_vs_ctrl[s])), 2) for s in DEFAULT_SEEDS}
    mean_by_seed_s_vs_g = {s: round(sum(seed_selective_vs_global[s]) / max(1, len(seed_selective_vs_global[s])), 2) for s in DEFAULT_SEEDS}

    # Pipeline counts
    total_physical_opps = sum(c["cell_details"]["C1"]["shadow_decisions_count"] for c in matched_cells)
    total_global_pipelines = sum(c["cell_details"]["C1"]["pipeline_success_count"] for c in matched_cells)
    total_selective_pipelines = sum(c["cell_details"]["C2R1"]["pipeline_success_count"] for c in matched_cells)
    selective_acceptance_rate = (total_selective_pipelines / max(1, total_physical_opps)) * 100.0

    # Storage and overflow comparison
    storage_comp = {
        "C0": {
            "peak_shed": max(c["cell_details"]["C0"]["storage_stats"]["peak_shed_occupancy"] for c in matched_cells),
            "turns_ge_90": sum(c["cell_details"]["C0"]["storage_stats"]["shed_turns_ge_90"] for c in matched_cells),
            "turns_ge_95": sum(c["cell_details"]["C0"]["storage_stats"]["shed_turns_ge_95"] for c in matched_cells),
            "turns_at_cap": sum(c["cell_details"]["C0"]["storage_stats"]["shed_turns_at_capacity"] for c in matched_cells),
            "overflow_units_lost": sum(c["cell_details"]["C0"]["storage_stats"]["total_overflow_units_lost"] for c in matched_cells),
        },
        "C1": {
            "peak_shed": max(c["cell_details"]["C1"]["storage_stats"]["peak_shed_occupancy"] for c in matched_cells),
            "turns_ge_90": sum(c["cell_details"]["C1"]["storage_stats"]["shed_turns_ge_90"] for c in matched_cells),
            "turns_ge_95": sum(c["cell_details"]["C1"]["storage_stats"]["shed_turns_ge_95"] for c in matched_cells),
            "turns_at_cap": sum(c["cell_details"]["C1"]["storage_stats"]["shed_turns_at_capacity"] for c in matched_cells),
            "overflow_units_lost": sum(c["cell_details"]["C1"]["storage_stats"]["total_overflow_units_lost"] for c in matched_cells),
        },
        "C2R1": {
            "peak_shed": max(c["cell_details"]["C2R1"]["storage_stats"]["peak_shed_occupancy"] for c in matched_cells),
            "turns_ge_90": sum(c["cell_details"]["C2R1"]["storage_stats"]["shed_turns_ge_90"] for c in matched_cells),
            "turns_ge_95": sum(c["cell_details"]["C2R1"]["storage_stats"]["shed_turns_ge_95"] for c in matched_cells),
            "turns_at_cap": sum(c["cell_details"]["C2R1"]["storage_stats"]["shed_turns_at_capacity"] for c in matched_cells),
            "overflow_units_lost": sum(c["cell_details"]["C2R1"]["storage_stats"]["total_overflow_units_lost"] for c in matched_cells),
        },
    }

    # Safety comparison
    safety_summary = {
        arm: {
            "animal_escapes": sum(c["cell_details"][arm]["safety_stats"]["animal_escapes"] for c in matched_cells),
            "max_consecutive_unfed": max(c["cell_details"][arm]["safety_stats"]["max_consecutive_unfed"] for c in matched_cells),
            "days_with_consecutive_unfed_1": sum(c["cell_details"][arm]["safety_stats"]["days_with_consecutive_unfed_1"] for c in matched_cells),
            "plant_deaths_from_watering_failure": sum(c["cell_details"][arm]["safety_stats"]["plant_deaths_from_watering_failure"] for c in matched_cells),
            "single_skipped_watering_days": sum(c["cell_details"][arm]["safety_stats"]["single_skipped_watering_days"] for c in matched_cells),
        }
        for arm in ("C0", "C1", "C2R1")
    }

    # Capital transactions timing
    capital_summary = {
        arm: {
            "total_land_spent": sum(c["cell_details"][arm]["capital_stats"]["total_land_spent"] for c in matched_cells),
            "total_hire_spent": sum(c["cell_details"][arm]["capital_stats"]["total_hire_spent"] for c in matched_cells),
            "total_seed_spent": sum(c["cell_details"][arm]["capital_stats"]["total_seed_spent"] for c in matched_cells),
            "total_animal_spent": sum(c["cell_details"][arm]["capital_stats"]["total_animal_spent"] for c in matched_cells),
        }
        for arm in ("C0", "C1", "C2R1")
    }

    # Losing pair forensics
    losing_forensics = []
    for c in matched_cells:
        if c["deltas"]["selective_r1_vs_global"] < 0 or c["deltas"]["global_vs_control"] < 0:
            losing_forensics.append({
                "seed": c["seed"],
                "opp_name": c["opp_name"],
                "seat": c["seat"],
                "cash": c["cash"],
                "deltas": c["deltas"],
                "c0_storage": c["cell_details"]["C0"]["storage_stats"],
                "c1_storage": c["cell_details"]["C1"]["storage_stats"],
                "c2r1_storage": c["cell_details"]["C2R1"]["storage_stats"],
                "c1_pipelines": c["cell_details"]["C1"]["pipeline_success_count"],
                "c2r1_pipelines": c["cell_details"]["C2R1"]["pipeline_success_count"],
            })

    # Representative traces
    best_c2_vs_c1 = max(matched_cells, key=lambda c: c["deltas"]["selective_r1_vs_global"])
    worst_c2_vs_c1 = min(matched_cells, key=lambda c: c["deltas"]["selective_r1_vs_global"])
    best_c2_vs_c0 = max(matched_cells, key=lambda c: c["deltas"]["selective_r1_vs_control"])

    rep_traces = {
        "best_selective_rescue_over_global": {
            "seed": best_c2_vs_c1["seed"],
            "opp_name": best_c2_vs_c1["opp_name"],
            "seat": best_c2_vs_c1["seat"],
            "cash": best_c2_vs_c1["cash"],
            "delta_selective_vs_global": best_c2_vs_c1["deltas"]["selective_r1_vs_global"],
            "delta_selective_vs_control": best_c2_vs_c1["deltas"]["selective_r1_vs_control"],
            "c0_trace": best_c2_vs_c1["cell_details"]["C0"]["trace_summary"],
            "c1_trace": best_c2_vs_c1["cell_details"]["C1"]["trace_summary"],
            "c2r1_trace": best_c2_vs_c1["cell_details"]["C2R1"]["trace_summary"],
        },
        "worst_selective_loss_vs_global": {
            "seed": worst_c2_vs_c1["seed"],
            "opp_name": worst_c2_vs_c1["opp_name"],
            "seat": worst_c2_vs_c1["seat"],
            "cash": worst_c2_vs_c1["cash"],
            "delta_selective_vs_global": worst_c2_vs_c1["deltas"]["selective_r1_vs_global"],
            "delta_selective_vs_control": worst_c2_vs_c1["deltas"]["selective_r1_vs_control"],
            "c0_trace": worst_c2_vs_c1["cell_details"]["C0"]["trace_summary"],
            "c1_trace": worst_c2_vs_c1["cell_details"]["C1"]["trace_summary"],
            "c2r1_trace": worst_c2_vs_c1["cell_details"]["C2R1"]["trace_summary"],
        },
        "best_selective_win_vs_control": {
            "seed": best_c2_vs_c0["seed"],
            "opp_name": best_c2_vs_c0["opp_name"],
            "seat": best_c2_vs_c0["seat"],
            "cash": best_c2_vs_c0["cash"],
            "delta_selective_vs_control": best_c2_vs_c0["deltas"]["selective_r1_vs_control"],
            "c0_trace": best_c2_vs_c0["cell_details"]["C0"]["trace_summary"],
            "c2r1_trace": best_c2_vs_c0["cell_details"]["C2R1"]["trace_summary"],
        }
    }

    # Save deliverables
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({
            "phase": "M0-C-R1",
            "git_commit": git_commit,
            "seeds": DEFAULT_SEEDS,
            "opponents": BENCHMARK_OPPONENTS,
            "seats": SEATS,
            "arms": ARMS,
            "sample_size": len(matched_cells),
            "total_matches": completed_matches,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round(total_duration, 2),
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "matched_results.json"), "w") as f:
        json.dump(matched_cells, f, indent=2)

    with open(os.path.join(OUT_DIR, "aggregate_tables.json"), "w") as f:
        json.dump({
            "sample_size": len(matched_cells),
            "distributions": {
                "global_vs_control": dist_g_vs_c,
                "selective_r1_vs_control": dist_s_vs_c,
                "selective_r1_vs_global": dist_s_vs_g,
            },
            "seed_clustered_ci": {
                "global_vs_control": clustered_g_vs_c,
                "selective_r1_vs_control": clustered_s_vs_c,
                "selective_r1_vs_global": clustered_s_vs_g,
            },
            "seed_level_means": {
                "global_vs_control": mean_by_seed_g_vs_c,
                "selective_r1_vs_control": mean_by_seed_s_vs_c,
                "selective_r1_vs_global": mean_by_seed_s_vs_g,
            },
            "arm_mean_cash": {
                "C0": round(sum(c["cash"]["C0"] for c in matched_cells) / len(matched_cells), 2),
                "C1": round(sum(c["cash"]["C1"] for c in matched_cells) / len(matched_cells), 2),
                "C2R1": round(sum(c["cash"]["C2R1"] for c in matched_cells) / len(matched_cells), 2),
            }
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "clustered_statistics.json"), "w") as f:
        json.dump({
            "global_vs_control": clustered_g_vs_c,
            "selective_r1_vs_control": clustered_s_vs_c,
            "selective_r1_vs_global": clustered_s_vs_g,
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "rejection_reason_summary.json"), "w") as f:
        json.dump(rejection_reason_counts, f, indent=2)

    with open(os.path.join(OUT_DIR, "crop_pipeline_summary.json"), "w") as f:
        json.dump({
            "total_physical_opportunities": total_physical_opps,
            "total_global_pipelines": total_global_pipelines,
            "total_selective_r1_pipelines": total_selective_pipelines,
            "selective_r1_acceptance_rate_pct": round(selective_acceptance_rate, 2),
            "throughput_retained_pct": round(total_selective_pipelines / max(1, total_global_pipelines) * 100, 2),
            "aggregate_cash_delta_to_pipeline_ratio": {
                "global": round(dist_g_vs_c.get("mean", 0) / max(0.01, total_global_pipelines / 100), 2),
                "selective_r1": round(dist_s_vs_c.get("mean", 0) / max(0.01, total_selective_pipelines / 100), 2),
            },
            "crop_breakdown": crop_stats,
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "gate_decisions.json"), "w") as f:
        json.dump({
            "total_opportunities": total_physical_opps,
            "crop_breakdown": crop_stats,
            "rejection_reasons": rejection_reason_counts,
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "storage_and_overflow.json"), "w") as f:
        json.dump(storage_comp, f, indent=2)

    with open(os.path.join(OUT_DIR, "safety_comparison.json"), "w") as f:
        json.dump(safety_summary, f, indent=2)

    with open(os.path.join(OUT_DIR, "transaction_timing.json"), "w") as f:
        json.dump(capital_summary, f, indent=2)

    with open(os.path.join(OUT_DIR, "losing_pair_forensics.json"), "w") as f:
        json.dump(losing_forensics, f, indent=2)

    with open(os.path.join(OUT_DIR, "representative_traces.json"), "w") as f:
        json.dump(rep_traces, f, indent=2)

    with open(os.path.join(OUT_DIR, "unresolved_limitations.json"), "w") as f:
        json.dump({
            "unresolved_limitations": [
                "Heuristic gate score uses fixed dollars estimate rather than dynamic recursive counterfactual valuation.",
                "Market timing gate uses static 60% threshold rather than complete town-demand drain schedule.",
                "Storage dump exposure models worst-case midnight auto-dump but does not simulate intra-day DROP optimization.",
                "Sample size of 100 scenario cells leaves confidence intervals with substantial uncertainty around zero."
            ]
        }, f, indent=2)

    print("================================================================================")
    print("PHASE M0-C-R1 REVALIDATION COMPLETE")
    print("================================================================================")
    print(f"GLOBAL vs CONTROL:       Mean = ${dist_g_vs_c.get('mean', 0):+,.2f} | 95% CI: {clustered_g_vs_c['ci_95']} | WinRate: {dist_g_vs_c.get('win_rate_pct', 0)}%")
    print(f"SELECTIVE_R1 vs CONTROL: Mean = ${dist_s_vs_c.get('mean', 0):+,.2f} | 95% CI: {clustered_s_vs_c['ci_95']} | WinRate: {dist_s_vs_c.get('win_rate_pct', 0)}%")
    print(f"SELECTIVE_R1 vs GLOBAL:  Mean = ${dist_s_vs_g.get('mean', 0):+,.2f} | 95% CI: {clustered_s_vs_g['ci_95']} | WinRate: {dist_s_vs_g.get('win_rate_pct', 0)}%")
    print(f"Total Physical Opportunities: {total_physical_opps}")
    print(f"Pipelines Executed: GLOBAL = {total_global_pipelines} | SELECTIVE_R1 = {total_selective_pipelines} (Acceptance: {selective_acceptance_rate:.1f}%)")
    print(f"Deliverables saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
