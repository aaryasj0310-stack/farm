#!/usr/bin/env python3
"""Kaggriculture P5.1 — Held-Out Formal Tournament Runner.

Pre-registered evaluation protocol:
- Seeds: 98,001–98,050 (50 seeds, strictly untouched during discovery)
- Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- Matched pairs: 50 seeds x 5 opponents x 2 seats = 250 matched pairs (500 live games)
- Control: Baseline commit 536f1e7 (P51_T1_TWO_CYCLE_CARROT_ENABLED = False)
- Treatment: P5.1 (P51_T1_TWO_CYCLE_CARROT_ENABLED = True)

NOTE: This script is prepared for execution after formal GO approval.
DO NOT run during diagnostic / discovery phases.
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
HELD_OUT_SEEDS = list(range(98001, 98051))  # 50 held-out seeds: 98,001–98,050


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
    print("Kaggriculture P5.1 — Held-Out Formal Tournament (250 Pairs, 500 Games)")
    print("Baseline: 536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e")
    print("Treatment: P51_T1_TWO_CYCLE_CARROT_ENABLED = True")
    print("Seeds: 98,001–98,050 (50) x 5 Opponents x 2 Seats = 250 Matched Pairs")
    print("======================================================================")

    scenarios = []
    for seed in HELD_OUT_SEEDS:
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
        running_cash_delta = 0.0
        running_starvations = 0

        for fut in as_completed(futures):
            res = fut.result()
            done_count += 1
            if res.get("status") == "success":
                results.append(res)
                sc = res["scenario"]
                running_cash_delta += res["delta_money"]
                running_starvations += res["treat_starved"]
                print(f"[{done_count:03d}/{n_total}] Seed {sc['seed']} vs {sc['opponent']:<20} S{sc['seat']}: Delta=${res['delta_money']:+8.2f} (Ctrl=${res['ctrl_money']:.0f}, Treat=${res['treat_money']:.0f}) C2_Done={res['completed_rotations']}")

                # Early stopping safety checks
                if running_starvations > 0:
                    print(f"\n[FATAL ABORT] Treatment animal starvation observed ({running_starvations}). Aborting tournament!")
                    break
                if done_count >= 50 and (running_cash_delta / done_count) < -500.0:
                    print(f"\n[EARLY STOPPING] Cumulative mean delta < -$500/game after {done_count} pairs (${running_cash_delta / done_count:.2f}). Aborting!")
                    break
            else:
                errors.append(res)
                sc = res["scenario"]
                print(f"[{done_count:03d}/{n_total}] Seed {sc['seed']} vs {sc['opponent']} S{sc['seat']}: ERROR - {res.get('error')}")

    elapsed = time.time() - start_time
    print(f"\nCompleted {len(results)} matches in {elapsed:.1f}s ({elapsed/60.0:.2f} min). Errors: {len(errors)}")

    if not results:
        print("ERROR: No successful matches!")
        return

    # Statistical summary
    deltas_money = [r["delta_money"] for r in results]
    deltas_reward = [r["delta_reward"] for r in results]
    n = len(deltas_money)
    mean_delta = sum(deltas_money) / n
    sorted_d = sorted(deltas_money)
    median_delta = sorted_d[n // 2] if n % 2 != 0 else (sorted_d[n // 2 - 1] + sorted_d[n // 2]) / 2.0
    variance = sum((x - mean_delta) ** 2 for x in deltas_money) / (n - 1) if n > 1 else 0.0
    std_delta = math.sqrt(variance)
    se_delta = std_delta / math.sqrt(n) if n > 0 else 0.0
    ci95_lower = mean_delta - 1.96 * se_delta
    ci95_upper = mean_delta + 1.96 * se_delta

    total_c1 = sum(r["c1_planted"] for r in results)
    total_c2 = sum(r["c2_planted"] for r in results)
    total_completed = sum(r["completed_rotations"] for r in results)
    total_d23_completed = sum(r["d23_completed"] for r in results)
    total_starved = sum(r["treat_starved"] for r in results)

    ctrl_wins = sum(r["ctrl_win"] for r in results)
    treat_wins = sum(r["treat_win"] for r in results)

    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "p51_formal_tournament_summary.json")

    summary_data = {
        "n_pairs": n,
        "seeds": "98001-98050",
        "mean_delta_money": mean_delta,
        "median_delta_money": median_delta,
        "std_delta_money": std_delta,
        "ci95_delta_money": [ci95_lower, ci95_upper],
        "ctrl_win_rate": ctrl_wins / n,
        "treat_win_rate": treat_wins / n,
        "total_c1_planted": total_c1,
        "total_c2_planted": total_c2,
        "total_completed": total_completed,
        "total_d23_completed": total_d23_completed,
        "total_starved": total_starved,
        "results": results,
    }

    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2)

    print(f"\nFormal tournament results written to {summary_path}")


if __name__ == "__main__":
    main()
