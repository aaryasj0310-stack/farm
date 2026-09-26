"""Common utilities, statistical evaluators, and base runner for M0-L-B Oracles.
"""
from __future__ import annotations

import copy
import json
import math
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
BASELINE_RESULTS_PATH = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_l_a_census", "match_results.json")

DEV_SEEDS = list(range(97013, 97023))  # 97013–97022 (10 seeds)
PILOT_SEEDS = [97013, 97014]
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def load_baseline_lookup() -> Dict[Tuple[int, str, int], Dict[str, Any]]:
    """Load the 100 baseline matches from Phase M0-L-A census keyed by (seed, opponent, seat)."""
    with open(BASELINE_RESULTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    lookup = {}
    for m in data:
        meta = m["metadata"]
        key = (int(meta["seed"]), str(meta["opponent"]), int(meta["seat"]))
        lookup[key] = m
    return lookup


def run_parallel_matches(runner_fn: Callable, tasks: List[Tuple], workers: int = 8) -> List[Dict[str, Any]]:
    """Execute match tasks in parallel using multiprocessing.Pool (robust on Windows)."""
    t0 = time.time()
    n = len(tasks)
    print(f"Launching {n} matches with {workers} worker processes...")
    with mp.Pool(processes=workers) as pool:
        results = pool.starmap(runner_fn, tasks)
    elapsed = time.time() - t0
    print(f"Finished {len(results)} matches in {elapsed:.1f}s ({elapsed / max(1, len(results)):.2f}s/match avg).")
    return results


def compute_paired_statistics(
    treatment_matches: List[Dict[str, Any]],
    baseline_lookup: Dict[Tuple[int, str, int], Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute seed-clustered paired statistics, opponent breakdowns, and safety audits."""
    deltas = []
    treatment_cashes = []
    baseline_cashes = []
    seed_clusters: Dict[int, List[float]] = {}
    opp_deltas: Dict[str, List[float]] = {}
    seat_deltas: Dict[int, List[float]] = {}
    wins = 0
    losses = 0
    ties = 0

    total_escapes = 0
    max_orders_seen = 0

    for tm in treatment_matches:
        meta = tm["metadata"]
        key = (int(meta["seed"]), str(meta["opponent"]), int(meta["seat"]))
        bm = baseline_lookup.get(key)
        if bm is None:
            continue

        t_cash = float(meta["final_cash"])
        b_cash = float(bm["metadata"]["final_cash"])
        diff = t_cash - b_cash

        treatment_cashes.append(t_cash)
        baseline_cashes.append(b_cash)
        deltas.append(diff)

        seed = key[0]
        opp = key[1]
        seat = key[2]

        seed_clusters.setdefault(seed, []).append(diff)
        opp_deltas.setdefault(opp, []).append(diff)
        seat_deltas.setdefault(seat, []).append(diff)

        if diff > 0:
            wins += 1
        elif diff < 0:
            losses += 1
        else:
            ties += 1

        total_escapes += tm.get("animal_escapes", 0)
        max_orders_seen = max(max_orders_seen, tm.get("max_market_orders", 0))

    if not deltas:
        return {"n": 0}

    arr_deltas = np.array(deltas, dtype=float)
    mean_diff = float(np.mean(arr_deltas))
    median_diff = float(np.median(arr_deltas))
    std_diff = float(np.std(arr_deltas, ddof=1)) if len(deltas) > 1 else 0.0

    # Seed-clustered CI (t-distribution with k-1 d.o.f.)
    cluster_means = {s: float(np.mean(v)) for s, v in seed_clusters.items()}
    c_means_list = list(cluster_means.values())
    k = len(c_means_list)
    grand_cluster_mean = float(np.mean(c_means_list))
    cluster_var = float(np.var(c_means_list, ddof=1)) if k > 1 else 0.0
    cluster_se = math.sqrt(cluster_var / k) if k > 0 else 0.0

    # Student-t critical value table for df = 1 to 20 at 95%
    t_table = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        19: 2.093,
    }
    df = max(1, k - 1)
    t_crit = t_table.get(df, 2.262 if df == 9 else 1.96)
    ci_lower = grand_cluster_mean - t_crit * cluster_se
    ci_upper = grand_cluster_mean + t_crit * cluster_se

    per_opp = {}
    for opp, d_list in opp_deltas.items():
        per_opp[opp] = {
            "mean_delta": float(np.mean(d_list)),
            "median_delta": float(np.median(d_list)),
            "n": len(d_list),
        }

    per_seat = {}
    for seat, d_list in seat_deltas.items():
        per_seat[str(seat)] = {
            "mean_delta": float(np.mean(d_list)),
            "median_delta": float(np.median(d_list)),
            "n": len(d_list),
        }

    return {
        "n_matches": len(deltas),
        "treatment_mean_cash": float(np.mean(treatment_cashes)),
        "baseline_mean_cash": float(np.mean(baseline_cashes)),
        "mean_paired_gain": mean_diff,
        "median_paired_gain": median_diff,
        "std_paired_gain": std_diff,
        "record": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": round(wins / len(deltas), 4),
        },
        "seed_clustered_ci_95": {
            "mean": grand_cluster_mean,
            "se": cluster_se,
            "df": df,
            "t_crit": t_crit,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
        },
        "opponent_breakdown": per_opp,
        "seat_breakdown": per_seat,
        "safety_audit": {
            "total_animal_escapes": total_escapes,
            "max_market_orders_turn": max_orders_seen,
            "passed_safety": (total_escapes == 0 and max_orders_seen <= 10),
        },
    }
