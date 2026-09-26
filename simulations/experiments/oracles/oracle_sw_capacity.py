"""Oracle 1: SW Productive Capacity Counterfactual Experiment.

Evaluates whether unlocking and activating Quadrant 3 (SW) at feasible seasonal timings
(Day 10, Day 14, Day 18, and Point 4.1 Zonal Acreage Expansion) generates net positive
terminal cash after accounting for land purchase ($2,000), seed costs, watering labor,
worker movement overhead, and potential diversion of capital/labor away from NW/NE.
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


def run_sw_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    from agent.main import agent, reset_agent_state
    import config
    from execution.midnight_storage_controller import reset_midnight_storage_telemetry
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    # Reset base configuration to production baseline
    config.set_midnight_storage_dump_mode("RESCUE")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")

    # Configure Arm
    if arm == "ArmA_Control":
        config.set_quadrant_hard_block({3, 4})
        config.set_sw_delayed_unlock_day(None)
        config.set_p41_sw_zonal_expansion_enabled(False)
    elif arm == "Arm1B_Unlock_D10":
        config.set_quadrant_hard_block({4})
        config.set_sw_delayed_unlock_day(10)
        config.set_p41_sw_zonal_expansion_enabled(False)
    elif arm == "Arm1C_Unlock_D14":
        config.set_quadrant_hard_block({4})
        config.set_sw_delayed_unlock_day(14)
        config.set_p41_sw_zonal_expansion_enabled(False)
    elif arm == "Arm1D_Unlock_D18":
        config.set_quadrant_hard_block({4})
        config.set_sw_delayed_unlock_day(18)
        config.set_p41_sw_zonal_expansion_enabled(False)
    elif arm == "Arm1E_P41_Zonal":
        config.set_quadrant_hard_block({4})
        config.set_p41_sw_zonal_expansion_enabled(True)
        config.set_p41_sw_crop_mode("hybrid")
    else:
        raise ValueError(f"Unknown arm: {arm}")

    reset_agent_state()
    reset_midnight_storage_telemetry()
    reset_sw_tranche_controller()

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    t_start = time.time()
    max_market_orders = 0
    sw_purchased = False
    sw_purchase_day = None

    while not env.done:
        obs_pre = env.state[seat].observation
        if hasattr(obs_pre, "farms") and len(obs_pre.farms) > seat:
            farm = obs_pre.farms[seat]
            unlocked = getattr(farm, "unlocked_quadrants", [])
            if "SW" in unlocked and not sw_purchased:
                sw_purchased = True
                sw_purchase_day = obs_pre.day

        action = agent(obs_pre, env.configuration)
        m_orders = action.get("market", [])
        if len(m_orders) > max_market_orders:
            max_market_orders = len(m_orders)

        try:
            opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_action = opp_agent(env.state[1 - seat].observation)

        actions = [action, opp_action] if seat == 0 else [opp_action, action]
        env.step(actions)

    duration = time.time() - t_start
    final_cash = float(env.state[seat].observation.farms[seat].money)
    opp_final_cash = float(env.state[1 - seat].observation.farms[1 - seat].money)

    # Check animal escapes: in kaggriculture, if animals escape or starve, penalties occur
    # Can check env.state[seat].reward or logs
    escapes = 0

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
        "sw_purchased": sw_purchased,
        "sw_purchase_day": sw_purchase_day,
        "max_market_orders": max_market_orders,
        "animal_escapes": escapes,
    }


def evaluate_sw_arm(arm: str, seeds: List[int], opponents: List[str], seats: List[int], workers: int = 8) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    baseline_lookup = load_baseline_lookup()
    tasks = []
    for s in seeds:
        for opp in opponents:
            for seat in seats:
                tasks.append((s, opp, seat, arm))

    from simulations.experiments.oracles.oracle_common import run_parallel_matches
    results = run_parallel_matches(run_sw_match, tasks, workers=workers)

    stats = compute_paired_statistics(results, baseline_lookup)
    sw_bought_count = sum(1 for r in results if r["sw_purchased"])
    stats["sw_purchased_count"] = sw_bought_count
    stats["sw_purchase_rate"] = sw_bought_count / len(results) if results else 0.0
    return stats, results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Oracle 1: SW Productive Capacity")
    parser.add_argument("--pilot", action="store_true", help="Run pilot seeds (97013, 97014) only")
    parser.add_argument("--arms", nargs="+", default=["Arm1B_Unlock_D10", "Arm1C_Unlock_D14", "Arm1D_Unlock_D18", "Arm1E_P41_Zonal"])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    seeds = PILOT_SEEDS if args.pilot else DEV_SEEDS
    print(f"Oracle 1 evaluation on seeds: {seeds}")

    summary_deliverable = {}
    for arm in args.arms:
        stats, raw_results = evaluate_sw_arm(arm, seeds, BENCHMARK_OPPONENTS, SEATS, workers=args.workers)
        summary_deliverable[arm] = stats
        print(f"\n--- Results for {arm} ---")
        print(f"Mean Paired Gain: ${stats.get('mean_paired_gain', 0):+,.2f}")
        print(f"Median Paired Gain: ${stats.get('median_paired_gain', 0):+,.2f}")
        print(f"Record: {stats.get('record', {})}")
        print(f"SW Purchase Rate: {stats.get('sw_purchase_rate', 0):.1%}")
        ci = stats.get('seed_clustered_ci_95', {})
        print(f"95% CI: [${ci.get('ci_lower', 0):+,.2f}, ${ci.get('ci_upper', 0):+,.2f}]")

    out_file = os.path.join(OUT_DIR, "oracle_1_sw_capacity_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary_deliverable, f, indent=2)
    print(f"\nWrote Oracle 1 results to {out_file}")
