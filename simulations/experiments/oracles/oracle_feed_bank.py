"""Oracle 4: On-Farm Wheat Feed Bank Counterfactual Experiment.

Evaluates whether dedicating on-farm wheat to a persistent livestock feed bank
(retaining harvested wheat in the shed rather than selling to market and rebuying)
and/or expanding on-farm wheat acreage improves net terminal cash after accounting
for land opportunity cost, lost melon/strawberry revenue, and feed security.
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


def run_feed_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
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
    config.set_quadrant_hard_block({3, 4})
    config.set_sw_delayed_unlock_day(None)
    config.set_p41_sw_zonal_expansion_enabled(False)

    # Configure Arm
    if arm == "Arm4A_Control":
        config.FEED_WHEAT_BUFFER_DAYS = 4
        config.PHASE1_WHEAT_TILES = 8
    elif arm == "Arm4B_Buffer_8Days":
        config.FEED_WHEAT_BUFFER_DAYS = 8
        config.PHASE1_WHEAT_TILES = 8
    elif arm == "Arm4C_Buffer_14Days":
        config.FEED_WHEAT_BUFFER_DAYS = 14
        config.PHASE1_WHEAT_TILES = 8
    elif arm == "Arm4D_Expanded_Acreage_12T":
        config.FEED_WHEAT_BUFFER_DAYS = 8
        config.PHASE1_WHEAT_TILES = 12
    else:
        raise ValueError(f"Unknown arm: {arm}")

    # Synchronize modules
    for mod_name in (
        "agent.market.market_brain", "market.market_brain", "market_brain",
        "agent.strategy.macro_planner", "strategy.macro_planner", "macro_planner",
        "agent.strategy.central_planner", "strategy.central_planner", "central_planner",
        "agent.strategy.expansion_planner", "strategy.expansion_planner", "expansion_planner",
    ):
        if mod_name in sys.modules:
            try:
                mod = sys.modules[mod_name]
                if hasattr(mod, "FEED_WHEAT_BUFFER_DAYS"):
                    setattr(mod, "FEED_WHEAT_BUFFER_DAYS", config.FEED_WHEAT_BUFFER_DAYS)
                if hasattr(mod, "PHASE1_WHEAT_TILES"):
                    setattr(mod, "PHASE1_WHEAT_TILES", config.PHASE1_WHEAT_TILES)
            except Exception:
                pass

    reset_agent_state()
    reset_midnight_storage_telemetry()
    reset_sw_tranche_controller()

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    t_start = time.time()
    max_market_orders = 0
    wheat_bought_qty = 0
    wheat_bought_spend = 0.0

    while not env.done:
        obs_pre = env.state[seat].observation
        action = agent(obs_pre, env.configuration)
        m_orders = action.get("market", [])
        if len(m_orders) > max_market_orders:
            max_market_orders = len(m_orders)

        for mo in m_orders:
            if len(mo) >= 3 and mo[0] == "BUY_PRODUCT" and mo[1] == "WHEAT":
                qty = int(mo[2])
                wheat_bought_qty += qty

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
        "wheat_bought_qty": wheat_bought_qty,
        "max_market_orders": max_market_orders,
        "animal_escapes": 0,
    }


def evaluate_feed_arm(arm: str, seeds: List[int], opponents: List[str], seats: List[int], workers: int = 8) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    baseline_lookup = load_baseline_lookup()
    tasks = []
    for s in seeds:
        for opp in opponents:
            for seat in seats:
                tasks.append((s, opp, seat, arm))

    from simulations.experiments.oracles.oracle_common import run_parallel_matches
    results = run_parallel_matches(run_feed_match, tasks, workers=workers)

    stats = compute_paired_statistics(results, baseline_lookup)
    avg_bought = float(np.mean([r["wheat_bought_qty"] for r in results])) if results else 0.0
    stats["wheat_metrics"] = {
        "mean_wheat_bought_qty": avg_bought,
    }
    return stats, results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Oracle 4: On-Farm Wheat Feed Bank")
    parser.add_argument("--pilot", action="store_true", help="Run pilot seeds (97013, 97014) only")
    parser.add_argument("--arms", nargs="+", default=["Arm4B_Buffer_8Days", "Arm4C_Buffer_14Days", "Arm4D_Expanded_Acreage_12T"])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    seeds = PILOT_SEEDS if args.pilot else DEV_SEEDS
    print(f"Oracle 4 evaluation on seeds: {seeds}")

    summary_deliverable = {}
    for arm in args.arms:
        stats, raw_results = evaluate_feed_arm(arm, seeds, BENCHMARK_OPPONENTS, SEATS, workers=args.workers)
        summary_deliverable[arm] = stats
        print(f"\n--- Results for {arm} ---")
        print(f"Mean Paired Gain: ${stats.get('mean_paired_gain', 0):+,.2f}")
        print(f"Median Paired Gain: ${stats.get('median_paired_gain', 0):+,.2f}")
        print(f"Record: {stats.get('record', {})}")
        wm = stats.get('wheat_metrics', {})
        print(f"Mean Wheat Bought: {wm.get('mean_wheat_bought_qty'):.1f} units")
        ci = stats.get('seed_clustered_ci_95', {})
        print(f"95% CI: [${ci.get('ci_lower', 0):+,.2f}, ${ci.get('ci_upper', 0):+,.2f}]")

    out_file = os.path.join(OUT_DIR, "oracle_4_feed_bank_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary_deliverable, f, indent=2)
    print(f"\nWrote Oracle 4 results to {out_file}")
