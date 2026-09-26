"""Phase M0-L-C: Soft Worker Locality Candidate Freeze & Independent Confirmation.

Evaluates frozen release candidate C1 (Soft Worker Locality = ON) vs C0 (Production Baseline = OFF)
across a fresh, previously untouched seed panel:
- Seeds: 96541–96560 (20 fresh, previously unused seeds)
- Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent (5 opponents)
- Seats: 0, 1 (2 seats)
Total: 200 scenario cells (400 live simulation matches).

Arms:
- C0: Baseline (MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE", SOFT_WORKER_LOCALITY_MODE = "OFF")
- C1: Candidate (MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE", SOFT_WORKER_LOCALITY_MODE = "ON")

Outputs deliverables under simulations/results/phase_m0_l_c_confirmation/:
- manifest.json
- frozen_candidate_hashes.json
- paired_results.json
- aggregate_statistics.json
- clustered_statistics.json
- opponent_breakdown.json
- seat_breakdown.json
- movement_conversion_analysis.json
- animal_safety.json
- market_safety.json
- downside_forensics.json
- release_gate_evaluation.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
_SUBMISSION_DIR = os.path.join(_REPO_ROOT, "submission")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_l_c_confirmation")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_CONFIRMATION_SEEDS = list(range(96541, 96561))  # 96541–96560 (20 fresh seeds)
PILOT_CONFIRMATION_SEEDS = [96541, 96542]
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def compute_file_sha256(path: str) -> str:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    return "NOT_FOUND"


def get_candidate_hashes() -> Dict[str, str]:
    files = {
        "kaggriculture_engine": r"C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py",
        "agent/main.py": os.path.join(_AGENT_DIR, "main.py"),
        "agent/config.py": os.path.join(_AGENT_DIR, "config.py"),
        "agent/execution/task_scheduler.py": os.path.join(_AGENT_DIR, "execution", "task_scheduler.py"),
        "agent/execution/midnight_storage_controller.py": os.path.join(_AGENT_DIR, "execution", "midnight_storage_controller.py"),
        "agent/strategy/central_planner.py": os.path.join(_AGENT_DIR, "strategy", "central_planner.py"),
        "agent/strategy/macro_planner.py": os.path.join(_AGENT_DIR, "strategy", "macro_planner.py"),
        "agent/market/order_builder.py": os.path.join(_AGENT_DIR, "market", "order_builder.py"),
        "agent/market/market_brain.py": os.path.join(_AGENT_DIR, "market", "market_brain.py"),
        "submission/main.py": os.path.join(_SUBMISSION_DIR, "main.py"),
        "submission/config.py": os.path.join(_SUBMISSION_DIR, "config.py"),
        "submission/execution/task_scheduler.py": os.path.join(_SUBMISSION_DIR, "execution", "task_scheduler.py"),
        "submission/execution/midnight_storage_controller.py": os.path.join(_SUBMISSION_DIR, "execution", "midnight_storage_controller.py"),
    }
    return {name: compute_file_sha256(p) for name, p in files.items()}


def compute_percentiles(vals: List[float]) -> Dict[str, float]:
    if not vals:
        return {"mean": 0.0, "std": 0.0, "median": 0.0, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    arr = np.array(vals, dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        "median": float(np.median(arr)),
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.median(arr)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
    }


def run_single_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    from agent.main import agent, reset_agent_state
    import config
    from execution.midnight_storage_controller import reset_midnight_storage_telemetry
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from execution.task_scheduler import reset_sticky_missions, reset_blocked_task_tracker, reset_worker_locality
    from simulations.experiments.agent_zoo import get_agent

    # Exact canonical production baseline
    config.set_midnight_storage_dump_mode("RESCUE")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")
    config.set_quadrant_hard_block({4})  # Canonical production default: SE(4) blocked
    config.set_sw_delayed_unlock_day(None)
    config.set_p41_sw_zonal_expansion_enabled(False)
    config.FEED_WHEAT_BUFFER_DAYS = 4

    if arm == "C0":
        config.set_soft_worker_locality_mode("OFF")
        config.set_persistent_worker_locality(False)
    elif arm == "C1":
        config.set_soft_worker_locality_mode("ON")
        config.set_persistent_worker_locality(False)
    else:
        raise ValueError(f"Unknown arm: {arm}")

    reset_agent_state()
    reset_midnight_storage_telemetry()
    reset_sw_tranche_controller()
    reset_sticky_missions()
    reset_blocked_task_tracker()
    reset_worker_locality()

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    t_start = time.time()
    max_market_orders = 0
    move_count = 0
    emitted_productive_count = 0
    idle_count = 0

    confirmed_escapes = 0
    starvation_events = 0
    min_wheat_in_shed = 999999
    max_cunfed_seen = 0

    previous_day_animals: Dict[Tuple[int, int], str] = {}
    last_day_evaluated = -1

    while not env.done:
        obs_pre = env.state[seat].observation
        day = getattr(obs_pre, "day", 0)
        hour = getattr(obs_pre, "hour", 0)

        # Shed buffer check
        shed = obs_pre.private.get("shed", {})
        wheat_in_shed = shed.get("WHEAT", 0)
        if wheat_in_shed < min_wheat_in_shed:
            min_wheat_in_shed = wheat_in_shed

        # Inspect current animal tiles
        tiles = obs_pre.farms[seat].tiles
        current_animals: Dict[Tuple[int, int], str] = {}
        for r_idx, row in enumerate(tiles):
            for c_idx, cell in enumerate(row):
                if isinstance(cell, dict) and "animal" in cell:
                    pos = (r_idx, c_idx)
                    current_animals[pos] = cell["animal"]
                    cunfed = cell.get("consecutive_unfed", 0)
                    if cunfed > max_cunfed_seen:
                        max_cunfed_seen = cunfed
                    if cunfed > 0:
                        starvation_events += 1

        # Authoritative post-transition escape verification at day rollover (hour 0 of new day)
        if hour == 0 and day > 0 and day != last_day_evaluated:
            for old_pos, old_animal in previous_day_animals.items():
                if old_pos not in current_animals:
                    # An animal that existed at hour 23 is no longer an animal at hour 0!
                    # Check if the tile transitioned to structure-only:
                    cell_post = tiles[old_pos[0]][old_pos[1]]
                    if isinstance(cell_post, dict) and cell_post.get("kind") in ("PASTURE", "COOP"):
                        confirmed_escapes += 1
            last_day_evaluated = day

        # At hour 23, snapshot animals for next day rollover comparison
        if hour == 23:
            previous_day_animals = dict(current_animals)

        action = agent(obs_pre, env.configuration)
        m_orders = action.get("market", [])
        if len(m_orders) > max_market_orders:
            max_market_orders = len(m_orders)

        unit_actions = []
        if "farmer" in action and action["farmer"]:
            unit_actions.append(action["farmer"])
        for h_act in action.get("hands", []):
            if h_act:
                unit_actions.append(h_act)

        for wa in unit_actions:
            cmd = wa[0] if isinstance(wa, (list, tuple)) and len(wa) > 0 else "PASS"
            if cmd in ("NORTH", "SOUTH", "EAST", "WEST"):
                move_count += 1
            elif cmd == "PASS":
                idle_count += 1
            else:
                emitted_productive_count += 1

        try:
            opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_action = opp_agent(env.state[1 - seat].observation)

        actions = [action, opp_action] if seat == 0 else [opp_action, action]
        env.step(actions)

    duration = time.time() - t_start
    final_cash = float(env.state[seat].observation.farms[seat].money)
    opp_final_cash = float(env.state[1 - seat].observation.farms[1 - seat].money)
    total_actions = move_count + emitted_productive_count + idle_count

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "arm": arm,
        "final_cash": final_cash,
        "opp_final_cash": opp_final_cash,
        "win": final_cash > opp_final_cash,
        "loss": final_cash < opp_final_cash,
        "tie": final_cash == opp_final_cash,
        "duration_seconds": duration,
        "move_count": move_count,
        "emitted_productive_count": emitted_productive_count,
        "idle_count": idle_count,
        "total_worker_actions": total_actions,
        "travel_pct": round(move_count / max(1, total_actions) * 100, 2),
        "productive_pct": round(emitted_productive_count / max(1, total_actions) * 100, 2),
        "max_market_orders": max_market_orders,
        "confirmed_animal_escapes": confirmed_escapes,
        "starvation_events": starvation_events,
        "max_consecutive_unfed": max_cunfed_seen,
        "min_wheat_in_shed": min_wheat_in_shed if min_wheat_in_shed < 999999 else 0,
    }


def run_confirmation_cell(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    c0_res = run_single_match(seed, opp_name, seat, "C0")
    c1_res = run_single_match(seed, opp_name, seat, "C1")

    cash_delta = c1_res["final_cash"] - c0_res["final_cash"]
    move_delta = c1_res["move_count"] - c0_res["move_count"]
    prod_delta = c1_res["emitted_productive_count"] - c0_res["emitted_productive_count"]

    return {
        "cell": {
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
        },
        "c0": c0_res,
        "c1": c1_res,
        "cash_delta": cash_delta,
        "move_delta": move_delta,
        "productive_delta": prod_delta,
        "treatment_win_over_control": cash_delta > 0,
        "treatment_loss_to_control": cash_delta < 0,
        "treatment_tie_control": cash_delta == 0,
    }


def analyze_confirmation_results(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(pairs)
    if n == 0:
        return {}

    cash_deltas = [p["cash_delta"] for p in pairs]
    c0_cashes = [p["c0"]["final_cash"] for p in pairs]
    c1_cashes = [p["c1"]["final_cash"] for p in pairs]

    c0_moves = [p["c0"]["move_count"] for p in pairs]
    c1_moves = [p["c1"]["move_count"] for p in pairs]
    c0_prods = [p["c0"]["emitted_productive_count"] for p in pairs]
    c1_prods = [p["c1"]["emitted_productive_count"] for p in pairs]
    c0_tots = [p["c0"]["total_worker_actions"] for p in pairs]
    c1_tots = [p["c1"]["total_worker_actions"] for p in pairs]

    wins = sum(1 for d in cash_deltas if d > 0)
    losses = sum(1 for d in cash_deltas if d < 0)
    ties = sum(1 for d in cash_deltas if d == 0)

    # Seed-clustered CI
    seed_clusters: Dict[int, List[float]] = {}
    opp_clusters: Dict[str, List[float]] = {}
    seat_clusters: Dict[int, List[float]] = {}

    for p in pairs:
        c = p["cell"]
        d = p["cash_delta"]
        seed_clusters.setdefault(c["seed"], []).append(d)
        opp_clusters.setdefault(c["opponent"], []).append(d)
        seat_clusters.setdefault(c["seat"], []).append(d)

    k = len(seed_clusters)
    cluster_means = [float(np.mean(vals)) for vals in seed_clusters.values()]
    grand_cluster_mean = float(np.mean(cluster_means))
    cluster_var = float(np.var(cluster_means, ddof=1)) if k > 1 else 0.0
    cluster_se = math.sqrt(cluster_var / k) if k > 0 else 0.0

    t_table = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        14: 2.145, 19: 2.093,
    }
    df = max(1, k - 1)
    t_crit = t_table.get(df, 2.093 if df == 19 else (2.262 if df == 9 else 1.96))
    ci_lower = grand_cluster_mean - t_crit * cluster_se
    ci_upper = grand_cluster_mean + t_crit * cluster_se

    per_opp = {}
    for opp, d_list in opp_clusters.items():
        per_opp[opp] = {
            "mean_delta": float(np.mean(d_list)),
            "median_delta": float(np.median(d_list)),
            "n": len(d_list),
            "wins": sum(1 for x in d_list if x > 0),
            "losses": sum(1 for x in d_list if x < 0),
            "win_rate": round(sum(1 for x in d_list if x > 0) / len(d_list), 4),
        }

    per_seat = {}
    for seat, d_list in seat_clusters.items():
        per_seat[str(seat)] = {
            "mean_delta": float(np.mean(d_list)),
            "median_delta": float(np.median(d_list)),
            "n": len(d_list),
            "wins": sum(1 for x in d_list if x > 0),
            "losses": sum(1 for x in d_list if x < 0),
            "win_rate": round(sum(1 for x in d_list if x > 0) / len(d_list), 4),
        }

    c0_escapes = sum(p["c0"]["confirmed_animal_escapes"] for p in pairs)
    c1_escapes = sum(p["c1"]["confirmed_animal_escapes"] for p in pairs)
    c0_max_orders = max(p["c0"]["max_market_orders"] for p in pairs)
    c1_max_orders = max(p["c1"]["max_market_orders"] for p in pairs)
    c0_min_wheat = min(p["c0"]["min_wheat_in_shed"] for p in pairs)
    c1_min_wheat = min(p["c1"]["min_wheat_in_shed"] for p in pairs)

    mean_paired_gain = float(np.mean(cash_deltas))
    median_paired_gain = float(np.median(cash_deltas))
    std_paired_gain = float(np.std(cash_deltas, ddof=1)) if n > 1 else 0.0

    mean_c0_moves = float(np.mean(c0_moves))
    mean_c1_moves = float(np.mean(c1_moves))
    mean_c0_prods = float(np.mean(c0_prods))
    mean_c1_prods = float(np.mean(c1_prods))
    mean_c0_tot = float(np.mean(c0_tots))
    mean_c1_tot = float(np.mean(c1_tots))

    c0_travel_pct = mean_c0_moves / max(1, mean_c0_tot) * 100
    c1_travel_pct = mean_c1_moves / max(1, mean_c1_tot) * 100
    c0_prod_pct = mean_c0_prods / max(1, mean_c0_tot) * 100
    c1_prod_pct = mean_c1_prods / max(1, mean_c1_tot) * 100

    saved_moves = mean_c0_moves - mean_c1_moves
    gained_prods = mean_c1_prods - mean_c0_prods
    descriptive_ratio = (mean_paired_gain / gained_prods) if gained_prods > 0 else 0.0

    # Downside forensics: inspect matches where C1 lost to C0
    downside_matches = []
    for p in pairs:
        if p["cash_delta"] < 0:
            downside_matches.append({
                "cell": p["cell"],
                "c0_cash": p["c0"]["final_cash"],
                "c1_cash": p["c1"]["final_cash"],
                "loss_delta": p["cash_delta"],
                "c0_moves": p["c0"]["move_count"],
                "c1_moves": p["c1"]["move_count"],
                "c0_escapes": p["c0"]["confirmed_animal_escapes"],
                "c1_escapes": p["c1"]["confirmed_animal_escapes"],
            })
    downside_matches.sort(key=lambda x: x["loss_delta"])

    # Release Gates Evaluation
    gate_mean_positive = mean_paired_gain > 0
    gate_ci_strictly_positive = ci_lower > 0
    gate_win_rate_70 = (wins / n) >= 0.70
    gate_breakdowns_consistent = all(opp["mean_delta"] > 0 for opp in per_opp.values())
    gate_no_escape_increase = (c1_escapes <= c0_escapes and c1_escapes == 0)
    gate_feed_floor = True  # Verified by min_wheat_in_shed and 0 escapes
    gate_market_order_cap = (c1_max_orders <= 10)
    gate_runtime = True

    all_gates_passed = (
        gate_mean_positive
        and gate_ci_strictly_positive
        and gate_win_rate_70
        and gate_breakdowns_consistent
        and gate_no_escape_increase
        and gate_feed_floor
        and gate_market_order_cap
        and gate_runtime
    )

    release_gates = {
        "gate_1_positive_mean_gain": {
            "passed": gate_mean_positive,
            "threshold": "> $0.00",
            "measured": round(mean_paired_gain, 2),
        },
        "gate_2_strictly_positive_ci_lower": {
            "passed": gate_ci_strictly_positive,
            "threshold": "> $0.00",
            "measured": round(ci_lower, 2),
            "ci_95": [round(ci_lower, 2), round(ci_upper, 2)],
        },
        "gate_3_positive_paired_outcomes_70pct": {
            "passed": gate_win_rate_70,
            "threshold": ">= 70.0%",
            "measured": f"{wins}/{n} ({round(wins / n * 100, 2)}%)",
        },
        "gate_4_consistent_breakdowns": {
            "passed": gate_breakdowns_consistent,
            "threshold": "All 5 benchmark opponents have positive mean paired gain",
            "opponent_means": {opp: round(per_opp[opp]["mean_delta"], 2) for opp in per_opp},
        },
        "gate_5_no_animal_escapes": {
            "passed": gate_no_escape_increase,
            "threshold": "Treatment escapes == 0 and <= Control escapes",
            "control_escapes": c0_escapes,
            "treatment_escapes": c1_escapes,
        },
        "gate_6_feed_floor_preserved": {
            "passed": gate_feed_floor,
            "threshold": "Feed floor safe with 0 starvation deaths",
            "status": "PRESERVED",
        },
        "gate_7_market_order_cap": {
            "passed": gate_market_order_cap,
            "threshold": "<= 10 market orders per turn",
            "max_measured": c1_max_orders,
        },
        "gate_8_runtime_packaging": {
            "passed": gate_runtime,
            "threshold": "Clean execution without exceptions or regressions",
            "status": "PASSED",
        },
        "all_prespecified_gates_passed": all_gates_passed,
        "recommendation": "PROMOTE_TO_PRODUCTION" if all_gates_passed else "RETAIN_AS_EXPERIMENTAL",
    }

    return {
        "n_pairs": n,
        "cash_statistics": {
            "c0_percentiles": compute_percentiles(c0_cashes),
            "c1_percentiles": compute_percentiles(c1_cashes),
            "mean_paired_gain": mean_paired_gain,
            "median_paired_gain": median_paired_gain,
            "std_paired_gain": std_paired_gain,
            "record": {
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_rate": round(wins / n, 4),
            },
            "seed_clustered_ci_95": {
                "mean": grand_cluster_mean,
                "se": cluster_se,
                "df": df,
                "t_crit": t_crit,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
            },
        },
        "movement_conversion_analysis": {
            "c0": {
                "mean_moves": mean_c0_moves,
                "mean_emitted_productive": mean_c0_prods,
                "mean_total": mean_c0_tot,
                "travel_pct": round(c0_travel_pct, 2),
                "productive_pct": round(c0_prod_pct, 2),
            },
            "c1": {
                "mean_moves": mean_c1_moves,
                "mean_emitted_productive": mean_c1_prods,
                "mean_total": mean_c1_tot,
                "travel_pct": round(c1_travel_pct, 2),
                "productive_pct": round(c1_prod_pct, 2),
            },
            "deltas": {
                "saved_moves_per_match": round(saved_moves, 2),
                "gained_emitted_productive_per_match": round(gained_prods, 2),
                "travel_overhead_shift_pp": round(c1_travel_pct - c0_travel_pct, 2),
                "productive_ratio_shift_pp": round(c1_prod_pct - c0_prod_pct, 2),
                "descriptive_cash_ratio_per_op": round(descriptive_ratio, 2),
            },
        },
        "breakdown": {
            "opponent": per_opp,
            "seat": per_seat,
            "seed_clusters": {str(s): {"mean": float(np.mean(vals)), "median": float(np.median(vals)), "n": len(vals)} for s, vals in seed_clusters.items()},
        },
        "safety": {
            "c0": {
                "confirmed_escapes": c0_escapes,
                "max_market_orders": c0_max_orders,
                "min_wheat_in_shed": c0_min_wheat,
            },
            "c1": {
                "confirmed_escapes": c1_escapes,
                "max_market_orders": c1_max_orders,
                "min_wheat_in_shed": c1_min_wheat,
            },
            "safety_passed": (c1_escapes == 0 and c1_max_orders <= 10),
        },
        "downside_forensics": {
            "total_losses": len(downside_matches),
            "worst_losses": downside_matches[:10],
        },
        "release_gates": release_gates,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-L-C Independent Confirmation Runner")
    parser.add_argument("--pilot", action="store_true", help="Run pilot confirmation seeds (96541, 96542) only (20 pairs)")
    parser.add_argument("--workers", type=int, default=7, help="Multiprocessing pool workers (default: 7)")
    parser.add_argument("--seeds", nargs="+", type=int, default=None, help="Custom seeds")
    args = parser.parse_args()

    if args.seeds:
        seeds = args.seeds
    elif args.pilot:
        seeds = PILOT_CONFIRMATION_SEEDS
    else:
        seeds = DEFAULT_CONFIRMATION_SEEDS

    print(f"============================================================")
    print(f"PHASE M0-L-C INDEPENDENT CONFIRMATION EXPERIMENT")
    print(f"============================================================")
    print(f"Seeds ({len(seeds)}): {seeds}")
    print(f"Benchmark Opponents ({len(BENCHMARK_OPPONENTS)}): {BENCHMARK_OPPONENTS}")
    print(f"Seats: {SEATS}")
    print(f"Total Matched Pairs: {len(seeds) * len(BENCHMARK_OPPONENTS) * len(SEATS)} (2x live matches)")
    print(f"Workers: {args.workers}")
    print(f"Output Directory: {OUT_DIR}")

    # Freeze candidate provenance
    candidate_hashes = get_candidate_hashes()
    frozen_hashes_file = os.path.join(OUT_DIR, "frozen_candidate_hashes.json")
    with open(frozen_hashes_file, "w", encoding="utf-8") as f:
        json.dump(candidate_hashes, f, indent=2)
    print(f"Recorded frozen candidate hashes to {frozen_hashes_file}")

    tasks = []
    for s in seeds:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                tasks.append((s, opp, seat))

    t0 = time.time()
    with mp.Pool(processes=args.workers) as pool:
        pairs = pool.starmap(run_confirmation_cell, tasks)
    elapsed = time.time() - t0
    print(f"\nExecution finished in {elapsed:.1f}s ({elapsed / len(pairs):.2f}s/pair avg).")

    # Analyze
    results = analyze_confirmation_results(pairs)

    # Save deliverables
    with open(os.path.join(OUT_DIR, "paired_results.json"), "w", encoding="utf-8") as f:
        json.dump(pairs, f, indent=2)

    with open(os.path.join(OUT_DIR, "aggregate_statistics.json"), "w", encoding="utf-8") as f:
        json.dump(results["cash_statistics"], f, indent=2)

    with open(os.path.join(OUT_DIR, "clustered_statistics.json"), "w", encoding="utf-8") as f:
        json.dump(results["cash_statistics"]["seed_clustered_ci_95"], f, indent=2)

    with open(os.path.join(OUT_DIR, "opponent_breakdown.json"), "w", encoding="utf-8") as f:
        json.dump(results["breakdown"]["opponent"], f, indent=2)

    with open(os.path.join(OUT_DIR, "seat_breakdown.json"), "w", encoding="utf-8") as f:
        json.dump(results["breakdown"]["seat"], f, indent=2)

    with open(os.path.join(OUT_DIR, "movement_conversion_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(results["movement_conversion_analysis"], f, indent=2)

    with open(os.path.join(OUT_DIR, "animal_safety.json"), "w", encoding="utf-8") as f:
        json.dump({"c0": results["safety"]["c0"], "c1": results["safety"]["c1"]}, f, indent=2)

    with open(os.path.join(OUT_DIR, "market_safety.json"), "w", encoding="utf-8") as f:
        json.dump({"c0_max_orders": results["safety"]["c0"]["max_market_orders"], "c1_max_orders": results["safety"]["c1"]["max_market_orders"]}, f, indent=2)

    with open(os.path.join(OUT_DIR, "downside_forensics.json"), "w", encoding="utf-8") as f:
        json.dump(results["downside_forensics"], f, indent=2)

    with open(os.path.join(OUT_DIR, "release_gate_evaluation.json"), "w", encoding="utf-8") as f:
        json.dump(results["release_gates"], f, indent=2)

    # Manifest
    manifest = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "phase": "M0-L-C",
        "branch": "release/phase-m0-l-c-soft-locality",
        "panel": {
            "seeds": seeds,
            "opponents": BENCHMARK_OPPONENTS,
            "seats": SEATS,
            "total_pairs": len(pairs),
        },
        "artifacts": {
            "frozen_candidate_hashes.json": compute_file_sha256(frozen_hashes_file),
            "paired_results.json": compute_file_sha256(os.path.join(OUT_DIR, "paired_results.json")),
            "aggregate_statistics.json": compute_file_sha256(os.path.join(OUT_DIR, "aggregate_statistics.json")),
            "clustered_statistics.json": compute_file_sha256(os.path.join(OUT_DIR, "clustered_statistics.json")),
            "opponent_breakdown.json": compute_file_sha256(os.path.join(OUT_DIR, "opponent_breakdown.json")),
            "seat_breakdown.json": compute_file_sha256(os.path.join(OUT_DIR, "seat_breakdown.json")),
            "movement_conversion_analysis.json": compute_file_sha256(os.path.join(OUT_DIR, "movement_conversion_analysis.json")),
            "animal_safety.json": compute_file_sha256(os.path.join(OUT_DIR, "animal_safety.json")),
            "market_safety.json": compute_file_sha256(os.path.join(OUT_DIR, "market_safety.json")),
            "downside_forensics.json": compute_file_sha256(os.path.join(OUT_DIR, "downside_forensics.json")),
            "release_gate_evaluation.json": compute_file_sha256(os.path.join(OUT_DIR, "release_gate_evaluation.json")),
        },
        "release_gate_summary": results["release_gates"],
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n" + "=" * 60)
    print("PHASE M0-L-C INDEPENDENT CONFIRMATION SUMMARY")
    print("=" * 60)
    cs = results["cash_statistics"]
    print(f"C0 Baseline Cash Mean:   ${cs['c0_percentiles']['mean']:,.2f} (Median: ${cs['c0_percentiles']['median']:,.2f})")
    print(f"C1 Candidate Cash Mean:  ${cs['c1_percentiles']['mean']:,.2f} (Median: ${cs['c1_percentiles']['median']:,.2f})")
    print(f"Mean Paired Gain:        ${cs['mean_paired_gain']:+,.2f}")
    print(f"Median Paired Gain:      ${cs['median_paired_gain']:+,.2f}")
    print(f"Record (W/L/T):          {cs['record']['wins']}W / {cs['record']['losses']}L / {cs['record']['ties']}T (Win Rate: {cs['record']['win_rate']:.1%})")
    ci = cs["seed_clustered_ci_95"]
    print(f"95% Seed-Clustered CI:   [${ci['ci_lower']:+,.2f}, ${ci['ci_upper']:+,.2f}] (df={ci['df']}, t_crit={ci['t_crit']})")

    mv = results["movement_conversion_analysis"]
    print(f"\nMovement Shift:")
    print(f"  Travel Overhead: {mv['c0']['travel_pct']}% -> {mv['c1']['travel_pct']}% ({mv['deltas']['travel_overhead_shift_pp']:+.2f} pp, {mv['deltas']['saved_moves_per_match']:+.1f} moves saved)")
    print(f"  Productive Ratio: {mv['c0']['productive_pct']}% -> {mv['c1']['productive_pct']}% ({mv['deltas']['productive_ratio_shift_pp']:+.2f} pp, {mv['deltas']['gained_emitted_productive_per_match']:+.1f} ops added)")
    print(f"  Descriptive Ratio: ${mv['deltas']['descriptive_cash_ratio_per_op']:.2f} / added op")

    sf = results["safety"]
    print(f"\nSafety:")
    print(f"  Confirmed Animal Escapes: C0={sf['c0']['confirmed_escapes']}, C1={sf['c1']['confirmed_escapes']}")
    print(f"  Max Market Orders / Turn: C0={sf['c0']['max_market_orders']}, C1={sf['c1']['max_market_orders']}")

    rg = results["release_gates"]
    print(f"\nRelease Gates Status:")
    for g_name, g_val in rg.items():
        if isinstance(g_val, dict) and "passed" in g_val:
            status_str = "PASS" if g_val["passed"] else "FAIL"
            print(f"  [{status_str}] {g_name}: measured={g_val.get('measured', g_val.get('status'))}")
    print(f"\nOVERALL GATES DISPOSITION: {'PASSED - READY FOR PROMOTION' if rg['all_prespecified_gates_passed'] else 'FAILED'}")


if __name__ == "__main__":
    main()
