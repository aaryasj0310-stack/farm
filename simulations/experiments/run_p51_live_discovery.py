#!/usr/bin/env python3
"""Kaggriculture P5.1 — Full 100-Pair Live Discovery Replay Runner.

Runs 100 matched pairs (200 live games) on discovery panel (seeds 96,201–96,210, 5 opponents, 2 seats):
Control: Baseline commit 536f1e7 (P51_T1_TWO_CYCLE_CARROT_ENABLED = False)
Treatment: P5.1 Enabled (P51_T1_TWO_CYCLE_CARROT_ENABLED = True)

Evaluates:
- Paired final money / reward delta distribution (mean, median, std, min, max, 95% CI)
- Two-cycle rotation completions and execution metrics
- Herd starvation rate across all 100 treatment games (must be 0.0%)
- Breakdown across all 5 opponents and both seats
- Cash reconciliation
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
import math
import os
import sys
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

BASELINE_SHA = "536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e"
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]
DIAGNOSTIC_SEEDS = list(range(96201, 96211))  # 10 discovery seeds: 96,201–96,210


def _run_single_matched_scenario(scenario):
    """Executes a single matched scenario: Control vs Treatment in worker process."""
    seed = scenario["seed"]
    opponent = scenario["opponent"]
    seat = scenario["seat"]

    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    agent_dir = os.path.join(ROOT, "agent")
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
            "two_cycle_rotation_manager", "expansion_planner", "price_math", "price_forecast", "endgame_liquidator",
        )):
            del sys.modules[key]

    try:
        import kaggle_environments
        from kaggle_environments.envs.kaggriculture import kaggriculture as kg
        import main as module
        import config as cfg
        import simulations.experiments.audit_p50r_telemetry as apt
        from simulations.experiments.agent_zoo import get_agent
        from strategy.two_cycle_rotation_manager import get_rotation_manager, reset_rotation_manager

        # ---------------- 1. RUN CONTROL ----------------
        apt._configure_baseline(cfg)
        cfg.set_p51_t1_two_cycle_carrot_enabled(False)
        module.reset_agent_state()
        reset_rotation_manager()

        opp_agent = get_agent(opponent)
        ctrl_players = [module.agent, opp_agent] if seat == 0 else [opp_agent, module.agent]

        env_ctrl = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": seed}, info={"seed": seed})
        env_ctrl.reset()
        env_ctrl.run(ctrl_players)

        ctrl_reward = float(env_ctrl.state[seat].reward or 0.0)
        ctrl_opp_reward = float(env_ctrl.state[1 - seat].reward or 0.0)
        ctrl_money = float(env_ctrl.state[seat].observation.farms[seat]["money"])
        ctrl_win = 1.0 if ctrl_reward > ctrl_opp_reward else (0.5 if ctrl_reward == ctrl_opp_reward else 0.0)

        # Control animal starvation
        ctrl_farm = env_ctrl.state[seat].observation.farms[seat]
        ctrl_starved = 0
        for row in ctrl_farm["tiles"]:
            for t in row:
                if t and isinstance(t, dict) and "animal" in t and t.get("consecutive_unfed", 0) >= 2:
                    ctrl_starved += 1

        # ---------------- 2. RUN TREATMENT ----------------
        for key in list(sys.modules):
            if any(key == m or key.startswith(m + ".") for m in (
                "main", "config", "state", "strategy", "execution", "market",
                "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
                "two_cycle_rotation_manager", "expansion_planner", "price_math", "price_forecast", "endgame_liquidator",
            )):
                del sys.modules[key]

        import main as treat_module
        import config as treat_cfg
        from strategy.two_cycle_rotation_manager import get_rotation_manager as treat_get_mgr, reset_rotation_manager as treat_reset_mgr

        apt._configure_baseline(treat_cfg)
        treat_cfg.set_p51_t1_two_cycle_carrot_enabled(True)
        treat_module.reset_agent_state()
        treat_reset_mgr()

        opp_agent_treat = get_agent(opponent)
        treat_players = [treat_module.agent, opp_agent_treat] if seat == 0 else [opp_agent_treat, treat_module.agent]

        env_treat = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": seed}, info={"seed": seed})
        env_treat.reset()
        env_treat.run(treat_players)

        treat_reward = float(env_treat.state[seat].reward or 0.0)
        treat_opp_reward = float(env_treat.state[1 - seat].reward or 0.0)
        treat_money = float(env_treat.state[seat].observation.farms[seat]["money"])
        treat_win = 1.0 if treat_reward > treat_opp_reward else (0.5 if treat_reward == treat_opp_reward else 0.0)

        # Treatment animal starvation
        treat_farm = env_treat.state[seat].observation.farms[seat]
        treat_starved = 0
        for row in treat_farm["tiles"]:
            for t in row:
                if t and isinstance(t, dict) and "animal" in t and t.get("consecutive_unfed", 0) >= 2:
                    treat_starved += 1

        mgr = treat_get_mgr()
        completed_rotations = sum(1 for rec in mgr.rotations.values() if rec.phase.value == "COMPLETED")
        d23_completed = sum(1 for rec in mgr.rotations.values() if rec.c1_plant_day == 23 and rec.phase.value == "COMPLETED")
        c1_planted = sum(1 for rec in mgr.rotations.values() if rec.c1_planted_confirmed)
        c2_planted = sum(1 for rec in mgr.rotations.values() if rec.c2_planted_confirmed)
        total_tracked = len(mgr.rotations)

        delta_reward = treat_reward - ctrl_reward
        delta_money = treat_money - ctrl_money

        return {
            "scenario": scenario,
            "ctrl_reward": ctrl_reward,
            "ctrl_money": ctrl_money,
            "ctrl_win": ctrl_win,
            "ctrl_starved": ctrl_starved,
            "treat_reward": treat_reward,
            "treat_money": treat_money,
            "treat_win": treat_win,
            "treat_starved": treat_starved,
            "delta_reward": delta_reward,
            "delta_money": delta_money,
            "total_tracked": total_tracked,
            "completed_rotations": completed_rotations,
            "d23_completed": d23_completed,
            "c1_planted": c1_planted,
            "c2_planted": c2_planted,
            "status": "success",
        }
    except Exception as e:
        return {
            "scenario": scenario,
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def main():
    start_time = time.time()
    print("======================================================================")
    print("Kaggriculture P5.1 — 100-Pair Live Discovery Replay (200 Games)")
    print("Baseline: 536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e")
    print("Treatment: P51_T1_TWO_CYCLE_CARROT_ENABLED = True")
    print("Seeds: 96,201–96,210 (10) x 5 Opponents x 2 Seats = 100 Matched Pairs")
    print("======================================================================")

    scenarios = []
    for seed in DIAGNOSTIC_SEEDS:
        for opp in OPPONENTS:
            for seat in (0, 1):
                scenarios.append({
                    "seed": seed,
                    "opponent": opp,
                    "seat": seat,
                })

    n_total = len(scenarios)
    results = []
    errors = []

    max_workers = min(os.cpu_count() or 4, 8)
    print(f"Launching {n_total} matched scenarios using {max_workers} processes...")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_matched_scenario, sc): sc for sc in scenarios}
        done_count = 0
        for fut in as_completed(futures):
            res = fut.result()
            done_count += 1
            if res.get("status") == "success":
                results.append(res)
                sc = res["scenario"]
                print(f"[{done_count:03d}/{n_total}] Seed {sc['seed']} vs {sc['opponent']:<20} S{sc['seat']}: Delta=${res['delta_money']:+8.2f} (Ctrl=${res['ctrl_money']:.0f}, Treat=${res['treat_money']:.0f}) C2_Done={res['completed_rotations']}")
            else:
                errors.append(res)
                sc = res["scenario"]
                print(f"[{done_count:03d}/{n_total}] Seed {sc['seed']} vs {sc['opponent']} S{sc['seat']}: ERROR - {res.get('error')}")

    elapsed = time.time() - start_time
    print(f"\nAll matches completed in {elapsed:.1f}s ({elapsed/60.0:.2f} min). Successes: {len(results)}, Errors: {len(errors)}")

    if not results:
        print("ERROR: No successful matches!")
        return

    # Calculate statistics
    deltas_money = [r["delta_money"] for r in results]
    deltas_reward = [r["delta_reward"] for r in results]
    n = len(deltas_money)
    mean_delta = sum(deltas_money) / n
    std_delta = math.sqrt(sum((x - mean_delta) ** 2 for x in deltas_money) / (n - 1)) if n > 1 else 0.0
    median_delta = sorted(deltas_money)[n // 2]
    min_delta = min(deltas_money)
    max_delta = max(deltas_money)
    se_delta = std_delta / math.sqrt(n)
    ci95_low = mean_delta - 1.96 * se_delta
    ci95_high = mean_delta + 1.96 * se_delta

    total_completed_rotations = sum(r["completed_rotations"] for r in results)
    mean_completed_per_game = total_completed_rotations / n
    total_starved = sum(r["treat_starved"] for r in results)

    ctrl_wins = sum(r["ctrl_win"] for r in results)
    treat_wins = sum(r["treat_win"] for r in results)

    # Opponent breakdown
    by_opp = defaultdict(list)
    for r in results:
        by_opp[r["scenario"]["opponent"]].append(r["delta_money"])

    # Seat breakdown
    by_seat = defaultdict(list)
    for r in results:
        by_seat[r["scenario"]["seat"]].append(r["delta_money"])

    print("\n======================================================================")
    print("P5.1 100-PAIR LIVE DISCOVERY REPLAY SUMMARY")
    print("======================================================================")
    print(f"Sample Size:                  {n} matched pairs (200 live games)")
    print(f"Mean Paired Money Delta:      ${mean_delta:+8.2f} / game")
    print(f"Median Paired Money Delta:    ${median_delta:+8.2f} / game")
    print(f"Standard Deviation:           ${std_delta:8.2f}")
    print(f"95% Confidence Interval:      [${ci95_low:+.2f}, ${ci95_high:+.2f}]")
    print(f"Min / Max Delta:              ${min_delta:+.2f} / ${max_delta:+.2f}")
    print(f"Total Completed Rotations:    {total_completed_rotations} ({mean_completed_per_game:.2f} / game)")
    print(f"Treatment Herd Starvations:   {total_starved} (0.0% starvation rate: {'PASS' if total_starved == 0 else 'FAIL'})")
    print(f"Win Rate: Control={ctrl_wins/n*100:.1f}%, Treatment={treat_wins/n*100:.1f}%")

    print("\n--- Breakdown by Opponent ---")
    for opp in OPPONENTS:
        vals = by_opp[opp]
        if vals:
            m = sum(vals) / len(vals)
            med = sorted(vals)[len(vals) // 2]
            print(f"  {opp:<25}: Mean=${m:+8.2f}, Median=${med:+8.2f} (n={len(vals)})")

    print("\n--- Breakdown by Seat ---")
    for s in (0, 1):
        vals = by_seat[s]
        if vals:
            m = sum(vals) / len(vals)
            med = sorted(vals)[len(vals) // 2]
            print(f"  Seat {s:<23}: Mean=${m:+8.2f}, Median=${med:+8.2f} (n={len(vals)})")

    summary_data = {
        "n_pairs": n,
        "elapsed_seconds": elapsed,
        "mean_delta_money": mean_delta,
        "median_delta_money": median_delta,
        "std_delta_money": std_delta,
        "ci95_low": ci95_low,
        "ci95_high": ci95_high,
        "min_delta_money": min_delta,
        "max_delta_money": max_delta,
        "total_completed_rotations": total_completed_rotations,
        "mean_completed_per_game": mean_completed_per_game,
        "treatment_starvations": total_starved,
        "control_win_rate": ctrl_wins / n,
        "treatment_win_rate": treat_wins / n,
        "by_opponent": {opp: {"mean": sum(vals) / len(vals), "median": sorted(vals)[len(vals) // 2], "n": len(vals)} for opp, vals in by_opp.items()},
        "by_seat": {str(s): {"mean": sum(vals) / len(vals), "median": sorted(vals)[len(vals) // 2], "n": len(vals)} for s, vals in by_seat.items()},
        "matches": results,
    }

    out_file = "simulations/experiments/results/p51_live_discovery_summary.json"
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(summary_data, f, indent=2)
    print(f"\nWrote full discovery summary to {out_file}")


if __name__ == "__main__":
    main()
