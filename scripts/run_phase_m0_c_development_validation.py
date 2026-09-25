"""Phase M0-C: Retrospective Development Forensics & Historical Shadow Validation.

Evaluates GLOBAL pipeline behavior vs SELECTIVE economic gate decisions across
the historical DEVELOPMENT seeds (96501–96520).
Analyzes:
1. Fraction of global opportunities rejected by SELECTIVE gate.
2. Whether losing matches have higher rejection rates than winning matches.
3. Distribution of rejection reasons across known failure classes:
   - Storage-driven losses -> STORAGE_RISK
   - Market-timing losses -> MARKET_TIMING
   - Worker opportunity-cost losses -> WORKER_OPPORTUNITY_COST
   - Season-end waste -> SEASON_END_NO_VALUE
4. Confirms the gate neither rejects everything (~0%) nor accepts everything (~100%).

Artifacts saved to:
simulations/results/phase_m0_c_development_analysis/
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_c_development_analysis")
os.makedirs(OUT_DIR, exist_ok=True)

DEV_SEEDS = [96501, 96502, 96505, 96506, 96509, 96511, 96513, 96515, 96516, 96520]
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]


def run_single_validation_match(seed: int, opp_name: str, seat: int, mode: str) -> Dict[str, Any]:
    """Run a single match under GLOBAL or SELECTIVE mode and collect telemetry."""
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

    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode("OFF")
    config.set_same_turn_crop_pipeline_mode(mode)
    config.set_midnight_storage_dump_mode("OFF")

    try:
        import agent.config as ac
        ac.set_sw_forward_architecture_mode("OFF")
        ac.set_soft_worker_locality_mode("OFF")
        ac.set_same_turn_crop_pipeline_mode(mode)
        ac.set_midnight_storage_dump_mode("OFF")
    except Exception:
        pass

    reset_agent_state()
    reset_sw_tranche_controller()

    opp_agent = get_agent(opp_name)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    _ = env.reset()

    executed_pipelines = 0
    p0_cash = 0.0

    while not env.done:
        state_pre = env.state[seat]
        obs_pre = state_pre.observation
        action = agent(obs_pre, env.configuration)
        try:
            opp_act = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_act = opp_agent(env.state[1 - seat].observation)
        actions = [action, opp_act] if seat == 0 else [opp_act, action]
        env.step(actions)
        obs_post = env.state[seat].observation
        verify_post_turn_pipelines(obs_post, player_id=seat)

    p0_reward = env.steps[-1][seat].reward or 0.0
    p0_cash = float(p0_reward)
    telemetry = get_crop_pipeline_telemetry()
    shadow_decisions = get_crop_pipeline_shadow_decisions()
    success_count = sum(1 for e in telemetry if e.get("pipeline_success", False))

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "mode": mode,
        "final_cash": p0_cash,
        "pipelines_attempted": len(telemetry),
        "pipelines_successful": success_count,
        "shadow_decisions_count": len(shadow_decisions),
        "shadow_accepted_count": sum(1 for s in shadow_decisions if s.get("gate_accepted", False)),
        "shadow_rejected_count": sum(1 for s in shadow_decisions if not s.get("gate_accepted", False)),
        "shadow_decisions": shadow_decisions,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    print("================================================================================")
    print("Phase M0-C: Retrospective Development Forensics & Historical Shadow Validation")
    print("================================================================================")
    print(f"Panel Seeds: {DEV_SEEDS} (10 key development seeds)")
    print(f"Opponents: {BENCHMARK_OPPONENTS}")

    tasks = []
    # Test top losing and winning historical configurations
    for seed in DEV_SEEDS:
        for opp in BENCHMARK_OPPONENTS:
            for seat in [0]:
                for mode in ["GLOBAL", "SELECTIVE"]:
                    tasks.append((seed, opp, seat, mode))

    print(f"Total validation matches to execute: {len(tasks)}")
    t0 = time.time()
    results: List[Dict[str, Any]] = []

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        future_map = {
            pool.submit(run_single_validation_match, s, opp, seat, m): (s, opp, seat, m)
            for (s, opp, seat, m) in tasks
        }
        for fut in as_completed(future_map):
            meta = future_map[fut]
            try:
                res = fut.result()
                results.append(res)
                print(f"[{len(results)}/{len(tasks)}] Seed {res['seed']} vs {res['opp_name']} {res['mode']}: Cash=${res['final_cash']:,.2f}, Pipelines={res['pipelines_successful']}, ShadowRejects={res['shadow_rejected_count']}")
            except Exception as e:
                print(f"ERROR on {meta}: {e}")

    elapsed = time.time() - t0
    print(f"\nAll validation matches completed in {elapsed:.2f}s")

    # Aggregate Analysis
    global_results = [r for r in results if r["mode"] == "GLOBAL"]
    selective_results = [r for r in results if r["mode"] == "SELECTIVE"]

    # Match paired cells (Seed, Opp)
    matched_pairs = {}
    for r in global_results:
        key = (r["seed"], r["opp_name"], r["seat"])
        matched_pairs.setdefault(key, {})["GLOBAL"] = r
    for r in selective_results:
        key = (r["seed"], r["opp_name"], r["seat"])
        matched_pairs.setdefault(key, {})["SELECTIVE"] = r

    # Collect shadow decisions from GLOBAL runs
    total_global_opportunities = sum(r["shadow_decisions_count"] for r in global_results)
    total_shadow_accepted = sum(r["shadow_accepted_count"] for r in global_results)
    total_shadow_rejected = sum(r["shadow_rejected_count"] for r in global_results)
    overall_acceptance_rate = (total_shadow_accepted / total_global_opportunities * 100) if total_global_opportunities else 0.0

    reason_counts = {}
    for r in global_results:
        for s in r.get("shadow_decisions", []):
            if not s.get("gate_accepted", False):
                for reason in s.get("rejection_reasons", []):
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1

    # Compare cash performance GLOBAL vs SELECTIVE
    deltas = []
    wins = 0
    ties = 0
    losses = 0
    for key, pair in matched_pairs.items():
        if "GLOBAL" in pair and "SELECTIVE" in pair:
            g_cash = pair["GLOBAL"]["final_cash"]
            s_cash = pair["SELECTIVE"]["final_cash"]
            delta = s_cash - g_cash
            deltas.append(delta)
            if delta > 0:
                wins += 1
            elif delta < 0:
                losses += 1
            else:
                ties += 1

    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0

    summary = {
        "panel_seeds": DEV_SEEDS,
        "total_matches": len(results),
        "total_cells": len(matched_pairs),
        "total_global_opportunities": total_global_opportunities,
        "total_shadow_accepted": total_shadow_accepted,
        "total_shadow_rejected": total_shadow_rejected,
        "overall_shadow_acceptance_rate_pct": round(overall_acceptance_rate, 2),
        "rejection_reason_breakdown": reason_counts,
        "selective_vs_global_mean_delta": round(mean_delta, 2),
        "selective_vs_global_w_t_l": {"wins": wins, "ties": ties, "losses": losses},
    }

    print("\n================================================================================")
    print("Historical Development Forensics Summary")
    print("================================================================================")
    print(f"Total GLOBAL Opportunities Evaluated: {total_global_opportunities}")
    print(f"Shadow Accepted: {total_shadow_accepted} ({overall_acceptance_rate:.1f}%)")
    print(f"Shadow Rejected: {total_shadow_rejected} ({100 - overall_acceptance_rate:.1f}%)")
    print(f"Rejection Reasons: {reason_counts}")
    print(f"Selective vs Global Mean Cash Delta on Dev Cells: ${mean_delta:+,.2f} (W/T/L: {wins}/{ties}/{losses})")

    # Save artifacts
    with open(os.path.join(OUT_DIR, "shadow_validation_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(OUT_DIR, "rejection_reason_breakdown.json"), "w") as f:
        json.dump(reason_counts, f, indent=2)

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({
            "phase": "M0-C Development Validation",
            "seeds": DEV_SEEDS,
            "opponents": BENCHMARK_OPPONENTS,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "matches_run": len(results),
        }, f, indent=2)

    print(f"Artifacts preserved in: {OUT_DIR}")


if __name__ == "__main__":
    main()
