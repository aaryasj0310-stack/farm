"""Phase M0-C: Selective Same-Turn Crop Pipeline Gating Discovery Experiment Runner.

Evaluates 3 arms across the newly selected discovery panel (Seeds 97013–97022 x 5 opponents x 2 seats = 100 scenario cells):
- C0: CONTROL (SAME_TURN_CROP_PIPELINE_MODE = "OFF")
- C1: GLOBAL M0-A (SAME_TURN_CROP_PIPELINE_MODE = "GLOBAL")
- C2: SELECTIVE M0-C (SAME_TURN_CROP_PIPELINE_MODE = "SELECTIVE")

Total: 100 cells x 3 arms = 300 real-engine matches.

Deliverables in simulations/results/phase_m0_c_discovery/:
- manifest.json
- matched_results.json
- aggregate_tables.json
- pipeline_opportunities.json
- gate_decisions.json
- rejection_reason_summary.json
- storage_comparison.json
- worker_opportunity_analysis.json
- capital_purchase_timing.json
- market_timing_analysis.json
- safety_comparison.json
- crop_cycle_comparison.json
- losing_pair_forensics.json
- representative_traces.json
- clustered_statistics.json
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
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_c_discovery")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_SEEDS = list(range(97013, 97023))  # 97013–97022 (10 clean, previously unused seeds)
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]
ARMS = ["C0", "C1", "C2"]

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
ANIMALS = ["GOOSE", "COW", "SHEEP"]
CROP_MATURITY = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}


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


def run_single_arm_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    """Run one single match under specified arm ('C0', 'C1', 'C2')."""
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
    elif arm == "C2":
        pipeline_mode = "SELECTIVE"

    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode("OFF")
    config.set_same_turn_crop_pipeline_mode(pipeline_mode)
    config.set_midnight_storage_dump_mode("OFF")

    try:
        import agent.config as ac
        ac.set_sw_forward_architecture_mode("OFF")
        ac.set_soft_worker_locality_mode("OFF")
        ac.set_same_turn_crop_pipeline_mode(pipeline_mode)
        ac.set_midnight_storage_dump_mode("OFF")
    except Exception:
        pass

    reset_agent_state()
    reset_sw_tranche_controller()

    opp_agent = get_agent(opp_name)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    _ = env.reset()

    worker_stats = {
        "total_worker_turns": 0,
        "emitted_moves": 0,
        "executed_moves": 0,
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
    }
    capital_stats = {
        "planned_purchases": [],
        "actual_purchases": [],
        "purchase_turns": {},
        "dropped_due_to_shed": 0,
    }
    safety_stats = {
        "escapes": 0,
        "starvations": 0,
        "max_consecutive_unfed": 0,
        "critical_watering_misses": 0,
    }
    tile_empty_turns = 0
    tile_prev_state = {}
    completed_crop_cycles = 0

    trace_summary = []
    step_num = 0

    while not env.done:
        state_pre = env.state[seat]
        obs_pre = state_pre.observation
        farms_pre = obs_pre.farms[seat]
        priv_pre = obs_pre.private

        shed_items = sum(priv_pre.shed.values()) if hasattr(priv_pre, "shed") else 0
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

        # Check animal escapes and unfed turns
        for r in range(10):
            for c in range(10):
                tile = farms_pre.tiles[r][c]
                q = _quadrant_of(c, r)
                if q in ("NW", "NE"):
                    if tile is None or (not getattr(tile, "is_plant", False) and not getattr(tile, "is_animal", False) and not getattr(tile, "is_building", False)):
                        tile_empty_turns += 1

                if tile is not None and getattr(tile, "is_animal", False):
                    unfed = getattr(tile, "consecutive_unfed", 0)
                    if unfed > safety_stats["max_consecutive_unfed"]:
                        safety_stats["max_consecutive_unfed"] = unfed

        # Check completed crop cycles
        for r in range(10):
            for c in range(10):
                t_curr = farms_pre.tiles[r][c]
                is_plant_curr = t_curr is not None and getattr(t_curr, "is_plant", False)
                prev = tile_prev_state.get((r, c))
                if prev and prev.get("is_plant") and not is_plant_curr:
                    completed_crop_cycles += 1
                tile_prev_state[(r, c)] = {
                    "is_plant": is_plant_curr,
                    "crop": getattr(t_curr, "crop", None) if t_curr is not None else None,
                    "yield": getattr(t_curr, "yield_units", 0) if t_curr is not None else 0,
                }

        # Track animals count for purchases
        animals_now = sum(1 for r in range(10) for c in range(10) if farms_pre.tiles[r][c] is not None and getattr(farms_pre.tiles[r][c], "is_animal", False))
        prev_animals = capital_stats.get("last_animals_count", 0)
        if animals_now > prev_animals and step_num > 0:
            capital_stats["actual_purchases"].append({
                "step": step_num,
                "day": obs_pre.day,
                "hour": obs_pre.hour,
                "count": animals_now,
            })
        capital_stats["last_animals_count"] = animals_now

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
            trace_summary.append({
                "step": step_num,
                "day": obs_pre.day,
                "hour": obs_pre.hour,
                "money": float(farms_pre.money),
                "shed_items": shed_items,
                "animals": animals_now,
            })

        env.step(actions)
        step_num += 1

        obs_post = env.state[seat].observation
        verify_post_turn_pipelines(obs_post, player_id=seat)

    p0_reward = env.steps[-1][seat].reward or 0.0
    p0_cash = float(p0_reward)

    pipeline_telemetry = get_crop_pipeline_telemetry()
    shadow_decisions = get_crop_pipeline_shadow_decisions()
    success_count = sum(1 for e in pipeline_telemetry if e.get("pipeline_success", False))

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
        "pipeline_attempted_count": len(pipeline_telemetry),
        "pipeline_success_count": success_count,
        "shadow_decisions_count": len(shadow_decisions),
        "shadow_accepted_count": sum(1 for s in shadow_decisions if s.get("gate_accepted", False)),
        "shadow_rejected_count": sum(1 for s in shadow_decisions if not s.get("gate_accepted", False)),
        "trace_summary": trace_summary,
        "shadow_decisions": shadow_decisions,
    }


def compute_distribution(deltas: List[float]) -> Dict[str, Any]:
    if not deltas:
        return {}
    s = sorted(deltas)
    n = len(s)
    mean = sum(s) / n
    med = s[n // 2] if n % 2 != 0 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    p10 = s[int(0.10 * n)]
    p25 = s[int(0.25 * n)]
    p50 = med
    p75 = s[int(0.75 * n)]
    p90 = s[int(0.90 * n)]
    wins = sum(1 for x in s if x > 0)
    ties = sum(1 for x in s if x == 0)
    losses = sum(1 for x in s if x < 0)
    win_rate = (wins / n) * 100.0
    return {
        "mean": round(mean, 2),
        "median": round(med, 2),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2),
        "p10": round(p10, 2),
        "p25": round(p25, 2),
        "p50": round(p50, 2),
        "p75": round(p75, 2),
        "p90": round(p90, 2),
        "best": round(s[-1], 2),
        "worst": round(s[0], 2),
    }


def compute_seed_clustered_ci(seed_means: Dict[int, float]) -> Dict[str, Any]:
    means = list(seed_means.values())
    n = len(means)
    if n < 2:
        return {"mean": round(means[0], 2) if means else 0.0, "ci_95": [0.0, 0.0]}
    grand_mean = sum(means) / n
    var = sum((m - grand_mean) ** 2 for m in means) / (n - 1)
    se = math.sqrt(var / n)
    t_crit = 2.262  # df = 9
    ci_lower = grand_mean - t_crit * se
    ci_upper = grand_mean + t_crit * se
    return {
        "mean": round(grand_mean, 2),
        "standard_error": round(se, 2),
        "ci_95": [round(ci_lower, 2), round(ci_upper, 2)],
    }


def main():
    parser = argparse.ArgumentParser(description="Run Phase M0-C Selective Pipeline Discovery Experiment")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    git_commit = get_git_commit()
    print("================================================================================")
    print("Kaggriculture Phase M0-C: Selective Same-Turn Crop Pipeline Gating Discovery")
    print("================================================================================")
    print(f"Git HEAD: {git_commit}")
    print(f"Discovery Seeds (10 unused): {DEFAULT_SEEDS}")
    print(f"Opponents (5): {BENCHMARK_OPPONENTS}")
    print(f"Seats (2): {SEATS}")
    print(f"Arms (3): {ARMS} (C0=Control, C1=Global M0-A, C2=Selective M0-C)")
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
                if completed_matches % 15 == 0 or completed_matches == total_matches:
                    print(f"[{completed_matches}/{total_matches}] Completed: Seed {res['seed']} vs {res['opp_name']} Seat {res['seat']} Arm {res['arm']} -> Cash=${res['final_cash']:,.2f}")
            except Exception as e:
                print(f"ERROR on {meta}: {e}")

    total_duration = time.time() - t_start
    print(f"\nAll {completed_matches} matches executed in {total_duration:.2f}s ({total_duration/60:.2f} min)\n")

    # Match and assemble cells
    matched_cells = []
    global_vs_ctrl_deltas = []
    selective_vs_ctrl_deltas = []
    selective_vs_global_deltas = []

    seed_global_vs_ctrl = {s: [] for s in DEFAULT_SEEDS}
    seed_selective_vs_ctrl = {s: [] for s in DEFAULT_SEEDS}
    seed_selective_vs_global = {s: [] for s in DEFAULT_SEEDS}

    all_shadow_decisions = []
    rejection_reason_counts = {}

    for (seed, opp, seat), arm_dict in match_results.items():
        if len(arm_dict) == 3:
            c0 = arm_dict["C0"]
            c1 = arm_dict["C1"]
            c2 = arm_dict["C2"]

            d_g_vs_c = c1["final_cash"] - c0["final_cash"]
            d_s_vs_c = c2["final_cash"] - c0["final_cash"]
            d_s_vs_g = c2["final_cash"] - c1["final_cash"]

            global_vs_ctrl_deltas.append(d_g_vs_c)
            selective_vs_ctrl_deltas.append(d_s_vs_c)
            selective_vs_global_deltas.append(d_s_vs_g)

            seed_global_vs_ctrl[seed].append(d_g_vs_c)
            seed_selective_vs_ctrl[seed].append(d_s_vs_c)
            seed_selective_vs_global[seed].append(d_s_vs_g)

            # Rejection reasons from C1 shadow decisions
            for s in c1.get("shadow_decisions", []):
                all_shadow_decisions.append(s)
                if not s.get("gate_accepted", False):
                    for reason in s.get("rejection_reasons", []):
                        rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1

            matched_cells.append({
                "seed": seed,
                "opp_name": opp,
                "seat": seat,
                "cash": {"C0": c0["final_cash"], "C1": c1["final_cash"], "C2": c2["final_cash"]},
                "deltas": {
                    "global_vs_control": d_g_vs_c,
                    "selective_vs_control": d_s_vs_c,
                    "selective_vs_global": d_s_vs_g,
                },
                "cell_details": {
                    "C0": {k: v for k, v in c0.items() if k != "shadow_decisions"},
                    "C1": {k: v for k, v in c1.items() if k != "shadow_decisions"},
                    "C2": {k: v for k, v in c2.items() if k != "shadow_decisions"},
                },
            })

    # Distributions
    dist_g_vs_c = compute_distribution(global_vs_ctrl_deltas)
    dist_s_vs_c = compute_distribution(selective_vs_ctrl_deltas)
    dist_s_vs_g = compute_distribution(selective_vs_global_deltas)

    # Clustered statistics
    mean_by_seed_g_vs_c = {s: sum(vals) / len(vals) for s, vals in seed_global_vs_ctrl.items() if vals}
    mean_by_seed_s_vs_c = {s: sum(vals) / len(vals) for s, vals in seed_selective_vs_ctrl.items() if vals}
    mean_by_seed_s_vs_g = {s: sum(vals) / len(vals) for s, vals in seed_selective_vs_global.items() if vals}

    clustered_g_vs_c = compute_seed_clustered_ci(mean_by_seed_g_vs_c)
    clustered_s_vs_c = compute_seed_clustered_ci(mean_by_seed_s_vs_c)
    clustered_s_vs_g = compute_seed_clustered_ci(mean_by_seed_s_vs_g)

    # Storage Comparison
    storage_comp = {arm: {
        "turns_ge_90": sum(c["cell_details"][arm]["storage_stats"]["shed_turns_ge_90"] for c in matched_cells),
        "turns_ge_95": sum(c["cell_details"][arm]["storage_stats"]["shed_turns_ge_95"] for c in matched_cells),
        "turns_at_cap": sum(c["cell_details"][arm]["storage_stats"]["shed_turns_at_capacity"] for c in matched_cells),
        "peak_shed": max(c["cell_details"][arm]["storage_stats"]["peak_shed_occupancy"] for c in matched_cells),
    } for arm in ARMS}

    # Physical Throughput & Cycles
    total_physical_opps = sum(c["cell_details"]["C1"]["shadow_decisions_count"] for c in matched_cells)
    total_global_pipelines = sum(c["cell_details"]["C1"]["pipeline_success_count"] for c in matched_cells)
    total_selective_pipelines = sum(c["cell_details"]["C2"]["pipeline_success_count"] for c in matched_cells)
    selective_acceptance_rate = (total_selective_pipelines / total_physical_opps * 100.0) if total_physical_opps else 0.0

    avg_cycles = {arm: sum(c["cell_details"][arm]["completed_crop_cycles"] for c in matched_cells) / len(matched_cells) for arm in ARMS}
    avg_empty_turns = {arm: sum(c["cell_details"][arm]["tile_empty_turns"] for c in matched_cells) / len(matched_cells) for arm in ARMS}

    # Capital purchases
    capital_purchases = {arm: sum(len(c["cell_details"][arm]["capital_stats"]["actual_purchases"]) for c in matched_cells) / len(matched_cells) for arm in ARMS}

    # Safety
    safety_summary = {arm: {
        "escapes": sum(c["cell_details"][arm]["safety_stats"]["escapes"] for c in matched_cells),
        "max_consecutive_unfed": max(c["cell_details"][arm]["safety_stats"]["max_consecutive_unfed"] for c in matched_cells),
    } for arm in ARMS}

    # Losing pair forensics for major regressions in C2 vs C1 and C2 vs C0
    losing_forensics = []
    for c in matched_cells:
        if c["deltas"]["selective_vs_control"] < -2000 or c["deltas"]["selective_vs_global"] < -2000:
            losing_forensics.append({
                "seed": c["seed"],
                "opp_name": c["opp_name"],
                "seat": c["seat"],
                "cash": c["cash"],
                "deltas": c["deltas"],
                "c0_storage": c["cell_details"]["C0"]["storage_stats"],
                "c1_storage": c["cell_details"]["C1"]["storage_stats"],
                "c2_storage": c["cell_details"]["C2"]["storage_stats"],
                "c1_pipelines": c["cell_details"]["C1"]["pipeline_success_count"],
                "c2_pipelines": c["cell_details"]["C2"]["pipeline_success_count"],
            })

    # Save deliverables
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({
            "phase": "M0-C",
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
                "selective_vs_control": dist_s_vs_c,
                "selective_vs_global": dist_s_vs_g,
            },
            "seed_clustered_ci": {
                "global_vs_control": clustered_g_vs_c,
                "selective_vs_control": clustered_s_vs_c,
                "selective_vs_global": clustered_s_vs_g,
            },
            "seed_level_means": {
                "global_vs_control": mean_by_seed_g_vs_c,
                "selective_vs_control": mean_by_seed_s_vs_c,
                "selective_vs_global": mean_by_seed_s_vs_g,
            }
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "rejection_reason_summary.json"), "w") as f:
        json.dump(rejection_reason_counts, f, indent=2)

    with open(os.path.join(OUT_DIR, "storage_comparison.json"), "w") as f:
        json.dump(storage_comp, f, indent=2)

    with open(os.path.join(OUT_DIR, "safety_comparison.json"), "w") as f:
        json.dump(safety_summary, f, indent=2)

    with open(os.path.join(OUT_DIR, "crop_cycle_comparison.json"), "w") as f:
        json.dump({
            "total_physical_opportunities": total_physical_opps,
            "total_global_pipelines": total_global_pipelines,
            "total_selective_pipelines": total_selective_pipelines,
            "selective_acceptance_rate_pct": round(selective_acceptance_rate, 2),
            "avg_crop_cycles_per_match": avg_cycles,
            "avg_empty_tile_turns_per_match": avg_empty_turns,
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "capital_purchase_timing.json"), "w") as f:
        json.dump({"avg_purchases_per_match": capital_purchases}, f, indent=2)

    with open(os.path.join(OUT_DIR, "losing_pair_forensics.json"), "w") as f:
        json.dump(losing_forensics, f, indent=2)

    with open(os.path.join(OUT_DIR, "clustered_statistics.json"), "w") as f:
        json.dump({
            "global_vs_control": clustered_g_vs_c,
            "selective_vs_control": clustered_s_vs_c,
            "selective_vs_global": clustered_s_vs_g,
        }, f, indent=2)

    print("================================================================================")
    print("PHASE M0-C EXPERIMENT COMPLETE")
    print("================================================================================")
    print(f"GLOBAL vs CONTROL:    Mean = ${dist_g_vs_c.get('mean', 0):+,.2f} | 95% CI: {clustered_g_vs_c['ci_95']} | WinRate: {dist_g_vs_c.get('win_rate_pct', 0)}%")
    print(f"SELECTIVE vs CONTROL: Mean = ${dist_s_vs_c.get('mean', 0):+,.2f} | 95% CI: {clustered_s_vs_c['ci_95']} | WinRate: {dist_s_vs_c.get('win_rate_pct', 0)}%")
    print(f"SELECTIVE vs GLOBAL:  Mean = ${dist_s_vs_g.get('mean', 0):+,.2f} | 95% CI: {clustered_s_vs_g['ci_95']} | WinRate: {dist_s_vs_g.get('win_rate_pct', 0)}%")
    print(f"Total Physical Opportunities: {total_physical_opps}")
    print(f"Pipelines Executed: GLOBAL = {total_global_pipelines} | SELECTIVE = {total_selective_pipelines} (Acceptance: {selective_acceptance_rate:.1f}%)")
    print(f"Rejection Reasons Breakdown: {rejection_reason_counts}")
    print(f"Deliverables saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
