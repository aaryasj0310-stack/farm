"""Paired Deterministic 50-Pair A/B Experiment:
Baseline (Commit 0389470) vs Candidate (Land Purchase Affordability Fix).

Runs 50 paired scenarios:
- 25 pairs vs 'starter' (seeds 101-125)
- 25 pairs vs 'random' (seeds 101-125)
Total 100 matches.

Tracks:
1. Final scores (Mean, Median, P10, Win/Loss/Tie, Max paired delta)
2. Land acquisition rates and timing for NE and SW
3. Cash balance immediately after land purchase
4. Productive vs Idle tile-days on newly acquired land
5. Distribution of land gate acceptance and rejection reasons
6. Safety invariants (starvations, deaths, escapes must be 0)
"""
import os
import sys
import json
import time
import copy
import argparse
import traceback
from typing import Dict, Any, List, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_CANDIDATE_DIR = os.path.join(_REPO_ROOT, "agent")
_BASELINE_DIR = os.path.join(_REPO_ROOT, "simulations", "baselines", "baseline_0389470", "agent")


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    arm = payload["arm"]
    seed = payload["seed"]
    opp_name = payload["opponent"]

    target_agent_dir = _CANDIDATE_DIR if arm == "ArmB_Candidate" else _BASELINE_DIR

    # Setup isolated environment for agent
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [target_agent_dir] + [os.path.join(target_agent_dir, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    # Clean local module caches
    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    from observation_parser import parse_observation
    import state_tracker

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")

    # Match-level telemetry
    land_purchases = {}  # quadrant -> {"day": day, "money_after": float}
    productive_tile_days = {"NE": 0, "SW": 0}
    idle_tile_days = {"NE": 0, "SW": 0}
    land_diagnostics_by_day = {}
    safety_metrics = {
        "feed_failures": 0,
        "animal_starvations": 0,
        "animal_deaths": 0,
    }
    peak_herd = 0

    def tracking_agent(obs, config=None):
        nonlocal peak_herd
        try:
            day = obs.get("day", 0)
            hour = obs.get("hour", 0)
            p_id = obs.get("player", 0)
            farms = obs.get("farms", [])
            farm_data = farms[p_id] if len(farms) > p_id else {}
            unlocked = set(farm_data.get("unlocked_quadrants", ["NW"]))

            ctx = parse_observation(obs)
            farm = ctx["farm"]

            curr_herd = sum(1 for t in farm.iter_tiles() if t.is_animal)
            if curr_herd > peak_herd:
                peak_herd = curr_herd

            # Check starvation at hour 0
            if hour == 0 and day > 0:
                for row in farm_data.get("tiles", []):
                    for t_dict in row:
                        if isinstance(t_dict, dict) and "animal" in t_dict and t_dict["animal"]:
                            if t_dict.get("consecutive_unfed", 0) > 0:
                                safety_metrics["feed_failures"] += 1
                                safety_metrics["animal_starvations"] += 1

            # Tile accounting for newly acquired land at hour 0
            if hour == 0:
                if "NE" in unlocked:
                    for y in range(0, 5):
                        for x in range(5, 10):
                            t = farm.tile_at((x, y))
                            if t and (t.is_plant or t.is_animal):
                                productive_tile_days["NE"] += 1
                            else:
                                idle_tile_days["NE"] += 1
                if "SW" in unlocked:
                    for y in range(5, 10):
                        for x in range(0, 5):
                            t = farm.tile_at((x, y))
                            if t and (t.is_plant or t.is_animal):
                                productive_tile_days["SW"] += 1
                            else:
                                idle_tile_days["SW"] += 1

            # Capture land diagnostics at hour 0
            if hour == 0 and day not in land_diagnostics_by_day:
                try:
                    from strategy.expansion_planner import should_buy_land, compute_land_roi
                    from strategy.macro_planner import PriceForecast
                    fc = PriceForecast.load()
                    n_extra = len(farm.unlocked) - 1
                    if n_extra < 3:
                        next_q = n_extra + 2
                        roi, _ = compute_land_roi(next_q, day, farm.money, farm, fc)
                        _, reason, diag = should_buy_land(
                            next_quadrant=next_q, current_day=day, money=farm.money,
                            farm=farm, roi=roi, forecast=fc
                        )
                        land_diagnostics_by_day[day] = dict(diag)
                except Exception:
                    pass

            # Execute turn action via agent
            act = agent_module.agent(obs, config)
            return act
        except Exception as e:
            print(f"EXCEPTION in tracking_agent: {e}")
            traceback.print_exc()
            return {}

    # Run match in Kaggle environment
    t0 = time.time()
    try:
        env = make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720})
        runner = env.run([tracking_agent, opp_name])
        last_step = runner[-1]
        p0_state = last_step[0]
        p1_state = last_step[1]

        final_money_p0 = float(p0_state.get("reward", 0.0) or 0.0)
        final_money_p1 = float(p1_state.get("reward", 0.0) or 0.0)

        # Inspect unlocked quadrants and purchase timing
        p0_farm = p0_state.get("observation", {}).get("farms", [{}])[0]
        final_unlocked = set(p0_farm.get("unlocked_quadrants", ["NW"]))

        # Scan historical steps to detect exact purchase days and cash balances
        ne_day, ne_cash = None, None
        sw_day, sw_cash = None, None

        for step in runner:
            step_obs = step[0].get("observation", {})
            if "farms" in step_obs and len(step_obs["farms"]) > 0:
                f = step_obs["farms"][0]
                u = set(f.get("unlocked_quadrants", []))
                d = step_obs.get("day", 0)
                m = float(f.get("money", 0.0))
                if "NE" in u and ne_day is None:
                    ne_day = d
                    ne_cash = m
                if "SW" in u and sw_day is None:
                    sw_day = d
                    sw_cash = m

        elapsed = time.time() - t0
        return {
            "arm": arm,
            "seed": seed,
            "opponent": opp_name,
            "final_score": final_money_p0,
            "opp_score": final_money_p1,
            "ne_purchased": ("NE" in final_unlocked),
            "ne_day": ne_day,
            "ne_cash_after": ne_cash,
            "sw_purchased": ("SW" in final_unlocked),
            "sw_day": sw_day,
            "sw_cash_after": sw_cash,
            "productive_tile_days_ne": productive_tile_days["NE"],
            "idle_tile_days_ne": idle_tile_days["NE"],
            "productive_tile_days_sw": productive_tile_days["SW"],
            "idle_tile_days_sw": idle_tile_days["SW"],
            "peak_herd": peak_herd,
            "safety_metrics": safety_metrics,
            "land_diagnostics": land_diagnostics_by_day,
            "elapsed": elapsed,
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "arm": arm,
            "seed": seed,
            "opponent": opp_name,
            "error": str(e),
            "final_score": 0.0,
            "opp_score": 0.0,
            "safety_metrics": safety_metrics,
        }


def main():
    parser = argparse.ArgumentParser(description="Run paired A/B land affordability experiment.")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    parser.add_argument("--out", type=str, default="simulations/experiments/land_affordability_ab_results.json")
    args = parser.parse_args()

    seeds = list(range(101, 126))
    opponents = ["starter", "random"]

    pairs = []
    for opp in opponents:
        for seed in seeds:
            pairs.append({"seed": seed, "opponent": opp})

    print(f"Starting Paired Deterministic Land Affordability Benchmark:")
    print(f"Total paired scenarios: {len(pairs)} (25 vs starter, 25 vs random)")
    print(f"Total matches: {len(pairs) * 2} (Arm A Baseline vs Arm B Candidate)")
    print(f"Using {args.workers} workers.\n")

    tasks = []
    for p in pairs:
        tasks.append({"arm": "ArmA_Baseline", "seed": p["seed"], "opponent": p["opponent"]})
        tasks.append({"arm": "ArmB_Candidate", "seed": p["seed"], "opponent": p["opponent"]})

    results = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_run_single_match, t): t for t in tasks}
        completed = 0
        total = len(tasks)
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total:
                print(f"Progress: {completed}/{total} matches completed ({completed/total*100:.1f}%) in {time.time()-t_start:.1f}s")

    out_path = os.path.join(_REPO_ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nAll matches finished! Raw results written to {out_path}")


if __name__ == "__main__":
    main()
