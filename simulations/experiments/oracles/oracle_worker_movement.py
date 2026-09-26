"""Oracle 2: Worker Movement Reduction & Locality Counterfactual Experiment.

Evaluates how much of the observed 64.5% movement overhead is economically recoverable:
- Arm 2B: Realistic Soft Worker Locality (SOFT_WORKER_LOCALITY_MODE = "ON")
- Arm 2C: Persistent Worker Locality (PERSISTENT_WORKER_LOCALITY_ENABLED = True)
- Arm 2D: Theoretical Zero-Commute Upper Bound Ceiling (Empirical & Capacity Model)
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_l_b_oracles")
os.makedirs(OUT_DIR, exist_ok=True)

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from simulations.experiments.oracles.oracle_common import (
    DEV_SEEDS,
    PILOT_SEEDS,
    BENCHMARK_OPPONENTS,
    SEATS,
    load_baseline_lookup,
    compute_paired_statistics,
)


def run_movement_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
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

    # Reset base configuration to production baseline
    config.set_midnight_storage_dump_mode("RESCUE")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")
    config.set_quadrant_hard_block({3, 4})
    config.set_sw_delayed_unlock_day(None)
    config.set_p41_sw_zonal_expansion_enabled(False)

    # Configure Arm
    if arm == "Arm2A_Control":
        config.set_soft_worker_locality_mode("OFF")
        config.set_persistent_worker_locality(False)
    elif arm == "Arm2B_Soft_Locality":
        config.set_soft_worker_locality_mode("ON")
        config.set_persistent_worker_locality(False)
    elif arm == "Arm2C_Persistent_Locality":
        config.set_soft_worker_locality_mode("OFF")
        config.set_persistent_worker_locality(True)
    elif arm == "Arm2D_Combined_Locality":
        config.set_soft_worker_locality_mode("ON")
        config.set_persistent_worker_locality(True)
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
    productive_count = 0
    idle_count = 0

    while not env.done:
        obs_pre = env.state[seat].observation
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
                productive_count += 1

        try:
            opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_action = opp_agent(env.state[1 - seat].observation)

        actions = [action, opp_action] if seat == 0 else [opp_action, action]
        env.step(actions)

    duration = time.time() - t_start
    final_cash = float(env.state[seat].observation.farms[seat].money)
    opp_final_cash = float(env.state[1 - seat].observation.farms[1 - seat].money)

    return {
        "metadata": {
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
            "final_cash": final_cash,
            "opp_final_cash": opp_final_cash,
            "win": final_cash > opp_final_cash,
            "loss": final_cash < opp_final_cash,
            "tie": final_cash == opp_final_cash,
            "duration_seconds": duration,
        },
        "arm": arm,
        "move_count": move_count,
        "productive_count": productive_count,
        "idle_count": idle_count,
        "total_worker_actions": move_count + productive_count + idle_count,
        "max_market_orders": max_market_orders,
        "animal_escapes": 0,
    }


def evaluate_movement_arm(arm: str, seeds: List[int], opponents: List[str], seats: List[int], workers: int = 8) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    baseline_lookup = load_baseline_lookup()
    tasks = []
    for s in seeds:
        for opp in opponents:
            for seat in seats:
                tasks.append((s, opp, seat, arm))

    from simulations.experiments.oracles.oracle_common import run_parallel_matches
    results = run_parallel_matches(run_movement_match, tasks, workers=workers)

    stats = compute_paired_statistics(results, baseline_lookup)
    avg_moves = float(np.mean([r["move_count"] for r in results])) if results else 0.0
    avg_prod = float(np.mean([r["productive_count"] for r in results])) if results else 0.0
    avg_tot = float(np.mean([r["total_worker_actions"] for r in results])) if results else 0.0
    stats["movement_metrics"] = {
        "mean_move_count": avg_moves,
        "mean_productive_count": avg_prod,
        "mean_total_actions": avg_tot,
        "travel_pct": round(avg_moves / max(1, avg_tot) * 100, 2),
        "productive_pct": round(avg_prod / max(1, avg_tot) * 100, 2),
    }
    return stats, results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Oracle 2: Worker Movement Reduction")
    parser.add_argument("--pilot", action="store_true", help="Run pilot seeds (97013, 97014) only")
    parser.add_argument("--arms", nargs="+", default=["Arm2B_Soft_Locality", "Arm2C_Persistent_Locality", "Arm2D_Combined_Locality"])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    seeds = PILOT_SEEDS if args.pilot else DEV_SEEDS
    print(f"Oracle 2 evaluation on seeds: {seeds}")

    summary_deliverable = {}
    for arm in args.arms:
        stats, raw_results = evaluate_movement_arm(arm, seeds, BENCHMARK_OPPONENTS, SEATS, workers=args.workers)
        summary_deliverable[arm] = stats
        print(f"\n--- Results for {arm} ---")
        print(f"Mean Paired Gain: ${stats.get('mean_paired_gain', 0):+,.2f}")
        print(f"Median Paired Gain: ${stats.get('median_paired_gain', 0):+,.2f}")
        print(f"Record: {stats.get('record', {})}")
        mm = stats.get('movement_metrics', {})
        print(f"Movement: {mm.get('travel_pct')}% travel, {mm.get('productive_pct')}% productive")
        ci = stats.get('seed_clustered_ci_95', {})
        print(f"95% CI: [${ci.get('ci_lower', 0):+,.2f}, ${ci.get('ci_upper', 0):+,.2f}]")

    out_file = os.path.join(OUT_DIR, "oracle_2_worker_movement_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary_deliverable, f, indent=2)
    print(f"\nWrote Oracle 2 results to {out_file}")
