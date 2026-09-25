"""Phase M0-F: Controlled Discovery Experiment.

Compares:
- C0 (CONTROL): ANIMAL_SERVICE_ECONOMICS_MODE = "OFF"
- C1 (TREATMENT): ANIMAL_SERVICE_ECONOMICS_MODE = "LIVE"

Matrix:
- 10 Discovery seeds: 97013–97022
- 5 Benchmark opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 Seats: 0 and 1
Total: 100 paired configurations = 200 matches.

Strict Invariants:
- SAME_TURN_DEPOSIT_SELL_MODE = "BASELINE"
- MIDNIGHT_STORAGE_DUMP_MODE = "OFF"
- SAME_TURN_CROP_PIPELINE_MODE = "OFF"
- SOFT_WORKER_LOCALITY_MODE = "OFF"
- SW_FORWARD_ARCHITECTURE_MODE = "OFF"

Outputs in simulations/results/phase_m0_f_discovery/:
- manifest.json
- match_results.json
- paired_deltas.json
- statistical_summary.json
- opponent_breakdown.json
- species_efficiency.json
- worker_redistribution.json
- feed_wheat_freed.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_f_discovery")
os.makedirs(OUT_DIR, exist_ok=True)

DISCOVERY_SEEDS = list(range(97013, 97023))  # 97013–97022 (10 seeds)
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def run_experiment_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    from agent.main import agent, reset_agent_state
    import config
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent
    from strategy.animal_service_economics import (
        reset_animal_service_telemetry,
        get_animal_service_telemetry,
    )

    # Invariants
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    config.set_midnight_storage_dump_mode("OFF")
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF" if arm == "CONTROL" else "LIVE")

    reset_agent_state()
    reset_sw_tranche_controller()
    reset_animal_service_telemetry()

    feed_actions_count = 0
    care_actions_count = 0
    harvest_actions_count = 0
    tend_actions_count = 0

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    step_num = 0
    while not env.done:
        obs_pre = env.state[seat].observation
        day = step_num // 24
        hour = step_num % 24

        act = agent(obs_pre, env.configuration)

        for u in [act.get("farmer")] + act.get("hands", []):
            if u:
                op = u[0]
                if op == "FEED":
                    feed_actions_count += 1
                elif op == "CARE":
                    care_actions_count += 1
                elif op == "HARVEST":
                    harvest_actions_count += 1
                elif op == "TEND":
                    tend_actions_count += 1

        try:
            opp_act = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_act = opp_agent(env.state[1 - seat].observation)

        step_actions = [act, opp_act] if seat == 0 else [opp_act, act]
        env.step(step_actions)
        step_num += 1

    final_reward = float(env.steps[-1][seat].reward or 0.0)
    opp_reward = float(env.steps[-1][1 - seat].reward or 0.0)
    telem = get_animal_service_telemetry()

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "arm": arm,
        "final_cash": final_reward,
        "opp_cash": opp_reward,
        "feed_actions": feed_actions_count,
        "care_actions": care_actions_count,
        "harvest_actions": harvest_actions_count,
        "tend_actions": tend_actions_count,
        "telemetry": {
            "animal_days_evaluated": telem.get("animal_days_evaluated", 0),
            "care_actions_skipped": telem.get("care_actions_skipped", 0),
            "feed_actions_skipped": telem.get("feed_actions_skipped", 0),
            "reasons_care_skipped": telem.get("reasons_care_skipped", {}),
            "reasons_feed_skipped": telem.get("reasons_feed_skipped", {}),
            "species_stats": telem.get("species_stats", {}),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-F Controlled Discovery Experiment")
    parser.add_argument("--workers", type=int, default=10, help="Number of worker processes")
    args = parser.parse_args()

    print("=== Phase M0-F Controlled Discovery Experiment ===")
    print(f"Seeds: {len(DISCOVERY_SEEDS)} x Opponents: {len(BENCHMARK_OPPONENTS)} x Seats: {len(SEATS)} = 100 paired configs (200 matches)")

    pairs = [
        (s, opp, seat)
        for s in DISCOVERY_SEEDS
        for opp in BENCHMARK_OPPONENTS
        for seat in SEATS
    ]

    all_tasks = []
    for s, opp, seat in pairs:
        all_tasks.append((s, opp, seat, "CONTROL"))
        all_tasks.append((s, opp, seat, "TREATMENT"))

    print(f"Total matches to run: {len(all_tasks)}")
    start_time = time.time()
    results: List[Dict[str, Any]] = []
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(run_experiment_match, s, opp, seat, arm): (s, opp, seat, arm) for (s, opp, seat, arm) in all_tasks}
        for fut in as_completed(future_map):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 20 == 0 or completed == len(all_tasks):
                print(f"  [{completed}/{len(all_tasks)}] matches complete ({time.time() - start_time:.1f}s)")

    # Group into paired runs
    paired_dict: Dict[Tuple[int, str, int], Dict[str, Dict[str, Any]]] = {}
    for r in results:
        key = (r["seed"], r["opponent"], r["seat"])
        if key not in paired_dict:
            paired_dict[key] = {}
        paired_dict[key][r["arm"]] = r

    paired_deltas: List[Dict[str, Any]] = []
    cash_deltas = []
    feed_deltas = []
    care_deltas = []
    harvest_deltas = []
    tend_deltas = []

    opp_breakdown: Dict[str, List[float]] = {opp: [] for opp in BENCHMARK_OPPONENTS}
    seat_breakdown: Dict[int, List[float]] = {0: [], 1: []}

    for key, arm_data in paired_dict.items():
        seed, opp, seat = key
        ctrl = arm_data["CONTROL"]
        treat = arm_data["TREATMENT"]

        d_cash = treat["final_cash"] - ctrl["final_cash"]
        d_feed = treat["feed_actions"] - ctrl["feed_actions"]
        d_care = treat["care_actions"] - ctrl["care_actions"]
        d_harvest = treat["harvest_actions"] - ctrl["harvest_actions"]
        d_tend = treat["tend_actions"] - ctrl["tend_actions"]

        cash_deltas.append(d_cash)
        feed_deltas.append(d_feed)
        care_deltas.append(d_care)
        harvest_deltas.append(d_harvest)
        tend_deltas.append(d_tend)

        opp_breakdown[opp].append(d_cash)
        seat_breakdown[seat].append(d_cash)

        paired_deltas.append({
            "seed": seed,
            "opponent": opp,
            "seat": seat,
            "control_cash": ctrl["final_cash"],
            "treatment_cash": treat["final_cash"],
            "cash_delta": d_cash,
            "control_feed": ctrl["feed_actions"],
            "treatment_feed": treat["feed_actions"],
            "feed_delta": d_feed,
            "control_care": ctrl["care_actions"],
            "treatment_care": treat["care_actions"],
            "care_delta": d_care,
            "harvest_delta": d_harvest,
            "tend_delta": d_tend,
            "telemetry_treatment": treat["telemetry"],
        })

    # Statistical Analysis
    cash_arr = np.array(cash_deltas)
    mean_delta = float(np.mean(cash_arr))
    std_delta = float(np.std(cash_arr, ddof=1)) if len(cash_arr) > 1 else 0.0
    sem_delta = float(std_delta / np.sqrt(len(cash_arr))) if len(cash_arr) > 1 else 0.0
    t_stat = float(mean_delta / sem_delta) if sem_delta > 0 else 0.0
    # Approximate 95% CI
    ci_lower = mean_delta - 1.984 * sem_delta
    ci_upper = mean_delta + 1.984 * sem_delta
    wins = int(np.sum(cash_arr > 0))
    ties = int(np.sum(cash_arr == 0))
    losses = int(np.sum(cash_arr < 0))

    ctrl_cash_mean = float(np.mean([r["final_cash"] for r in results if r["arm"] == "CONTROL"]))
    treat_cash_mean = float(np.mean([r["final_cash"] for r in results if r["arm"] == "TREATMENT"]))

    stats_summary = {
        "pairs_count": len(paired_deltas),
        "mean_control_cash": ctrl_cash_mean,
        "mean_treatment_cash": treat_cash_mean,
        "mean_cash_delta": mean_delta,
        "median_cash_delta": float(np.median(cash_arr)),
        "std_delta": std_delta,
        "sem_delta": sem_delta,
        "t_statistic": t_stat,
        "ci_95": [float(ci_lower), float(ci_upper)],
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate": wins / len(paired_deltas),
        "mean_feed_saved_per_match": float(-np.mean(feed_deltas)),
        "mean_care_saved_per_match": float(-np.mean(care_deltas)),
        "mean_harvest_actions_delta": float(np.mean(harvest_deltas)),
        "mean_tend_actions_delta": float(np.mean(tend_deltas)),
    }

    opp_summary = {}
    for opp, deltas in opp_breakdown.items():
        arr = np.array(deltas)
        opp_summary[opp] = {
            "n": len(deltas),
            "mean_delta": float(np.mean(arr)),
            "std_delta": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
            "wins": int(np.sum(arr > 0)),
            "ties": int(np.sum(arr == 0)),
            "losses": int(np.sum(arr < 0)),
        }

    # Species and worker telemetry aggregation
    sp_totals = {sp: {"care_saved": 0, "feed_saved": 0} for sp in ("COW", "SHEEP", "GOOSE")}
    care_reasons = {}
    feed_reasons = {}
    for pd in paired_deltas:
        telem = pd["telemetry_treatment"]
        for sp, sstats in telem.get("species_stats", {}).items():
            if sp in sp_totals:
                sp_totals[sp]["care_saved"] += sstats.get("care_skipped", 0)
                sp_totals[sp]["feed_saved"] += sstats.get("feed_skipped", 0)
        for r, c in telem.get("reasons_care_skipped", {}).items():
            care_reasons[r] = care_reasons.get(r, 0) + c
        for r, c in telem.get("reasons_feed_skipped", {}).items():
            feed_reasons[r] = feed_reasons.get(r, 0) + c

    species_efficiency = {
        "species_breakdown": sp_totals,
        "care_skip_reasons": care_reasons,
    }

    worker_redistribution = {
        "care_actions_saved_total": int(-sum(care_deltas)),
        "care_actions_saved_per_match": float(-np.mean(care_deltas)),
        "feed_actions_saved_total": int(-sum(feed_deltas)),
        "feed_actions_saved_per_match": float(-np.mean(feed_deltas)),
        "harvest_actions_delta_per_match": float(np.mean(harvest_deltas)),
        "tend_actions_delta_per_match": float(np.mean(tend_deltas)),
    }

    feed_wheat_freed = {
        "wheat_feed_units_saved_total": int(-sum(feed_deltas)),
        "wheat_feed_units_saved_per_match": float(-np.mean(feed_deltas)),
        "feed_skip_reasons": feed_reasons,
    }

    manifest = {
        "phase": "M0-F",
        "description": "Controlled Discovery Experiment (100 paired configs, 200 matches)",
        "control_arm": "OFF",
        "treatment_arm": "LIVE",
        "invariants": {
            "SAME_TURN_DEPOSIT_SELL_MODE": "BASELINE",
            "MIDNIGHT_STORAGE_DUMP_MODE": "OFF",
            "SAME_TURN_CROP_PIPELINE_MODE": "OFF",
            "SOFT_WORKER_LOCALITY_MODE": "OFF",
            "SW_FORWARD_ARCHITECTURE_MODE": "OFF",
        },
        "seeds": DISCOVERY_SEEDS,
        "opponents": BENCHMARK_OPPONENTS,
        "seats": SEATS,
    }

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(OUT_DIR, "match_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    with open(os.path.join(OUT_DIR, "paired_deltas.json"), "w", encoding="utf-8") as f:
        json.dump(paired_deltas, f, indent=2)
    with open(os.path.join(OUT_DIR, "statistical_summary.json"), "w", encoding="utf-8") as f:
        json.dump(stats_summary, f, indent=2)
    with open(os.path.join(OUT_DIR, "opponent_breakdown.json"), "w", encoding="utf-8") as f:
        json.dump(opp_summary, f, indent=2)
    with open(os.path.join(OUT_DIR, "species_efficiency.json"), "w", encoding="utf-8") as f:
        json.dump(species_efficiency, f, indent=2)
    with open(os.path.join(OUT_DIR, "worker_redistribution.json"), "w", encoding="utf-8") as f:
        json.dump(worker_redistribution, f, indent=2)
    with open(os.path.join(OUT_DIR, "feed_wheat_freed.json"), "w", encoding="utf-8") as f:
        json.dump(feed_wheat_freed, f, indent=2)

    print("\n=== Experiment Summary ===")
    print(f"Pairs: {stats_summary['pairs_count']}")
    print(f"Mean Control Cash:   ${stats_summary['mean_control_cash']:.2f}")
    print(f"Mean Treatment Cash: ${stats_summary['mean_treatment_cash']:.2f}")
    print(f"Paired Mean Delta:   ${stats_summary['mean_cash_delta']:+.2f} (95% CI: [{ci_lower:.2f}, {ci_upper:.2f}])")
    print(f"T-statistic:         {t_stat:.3f}")
    print(f"W / T / L:           {wins} / {ties} / {losses} ({stats_summary['win_rate']*100:.1f}% win rate)")
    print(f"CARE saved / match:  {stats_summary['mean_care_saved_per_match']:.2f}")
    print(f"FEED saved / match:  {stats_summary['mean_feed_saved_per_match']:.2f}")
    print(f"Results written to {OUT_DIR}")


if __name__ == "__main__":
    main()
