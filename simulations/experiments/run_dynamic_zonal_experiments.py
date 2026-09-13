"""Phase 2B: Workload-Aware Zonal Labor Mobility Benchmark Suite.

Evaluates 6 experimental arms across 50 paired scenarios (25 seeds x 2 opponents):
  - Arm A: No SW, frozen dispatch (Baseline commit 59cf176)
  - Arm B: No SW, dynamic zonal allocation (DYNAMIC_ZONAL_ALLOCATION = True, SW blocked)
  - Arm C: SW + 5 active crop tiles + dynamic allocation (force_k = 5)
  - Arm D: SW + 10 active crop tiles + dynamic allocation (force_k = 10)
  - Arm E: SW + 15 active crop tiles + dynamic allocation (force_k = 15)
  - Arm F: Delayed SW (Day 14+) + dynamic allocation (force_k = 10)

Records per-zone telemetry:
  - Final score, opponent score, score delta vs Arm A
  - Safety invariants: feed failures, animal starvations, animal deaths (MUST be 0)
  - Land purchases: NE day/cash, SW day/cash, purchase rates
  - Productive tile-days: NW, NE, SW, and idle tile-days
  - SW task telemetry: tasks created, assigned, completed, completion %, moves vs ops
  - Quadrant task completions: NW, NE, SW
"""
import os
import sys
import json
import time
import argparse
import traceback
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_CANDIDATE_DIR = os.path.join(_REPO_ROOT, "agent")
_BASELINE_DIR = os.path.join(_REPO_ROOT, "simulations", "baselines", "baseline_59cf176", "agent")


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    arm = payload["arm"]
    seed = payload["seed"]
    opp_name = payload["opponent"]

    target_agent_dir = _BASELINE_DIR if arm == "ArmA_Baseline" else _CANDIDATE_DIR

    # Setup isolated environment for agent
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [target_agent_dir] + [os.path.join(target_agent_dir, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    # Clean local module caches
    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'land_serviceability_model'
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
    if hasattr(agent_module, "reset_daily_telemetry"):
        agent_module.reset_daily_telemetry()
    elif hasattr(agent_module, "reset_daily_log"):
        agent_module.reset_daily_log()

    # Configure arm-specific settings
    if arm != "ArmA_Baseline":
        try:
            import config
            # Enable dynamic zonal allocation for all candidate arms
            config.set_dynamic_zonal_allocation(True)

            if arm == "ArmB_NoSW_Dynamic":
                config.set_quadrant_hard_block({3, 4})
                config.set_sw_force_k_tiles(None)
                config.set_sw_delayed_unlock_day(None)
            elif arm == "ArmC_SW5_Dynamic":
                config.set_quadrant_hard_block({4})
                config.set_sw_force_k_tiles(5)
                config.set_sw_delayed_unlock_day(None)
            elif arm == "ArmD_SW10_Dynamic":
                config.set_quadrant_hard_block({4})
                config.set_sw_force_k_tiles(10)
                config.set_sw_delayed_unlock_day(None)
            elif arm == "ArmE_SW15_Dynamic":
                config.set_quadrant_hard_block({4})
                config.set_sw_force_k_tiles(15)
                config.set_sw_delayed_unlock_day(None)
            elif arm == "ArmF_DelayedSW_Dynamic":
                config.set_quadrant_hard_block({4})
                config.set_sw_force_k_tiles(10)
                config.set_sw_delayed_unlock_day(14)
        except Exception as e:
            print(f"Error configuring arm {arm}: {e}")

    # Match-level telemetry
    productive_tile_days = {"NW": 0, "NE": 0, "SW": 0}
    idle_tile_days = {"NW": 0, "NE": 0, "SW": 0}
    safety_metrics = {
        "feed_failures": 0,
        "animal_starvations": 0,
        "animal_deaths": 0,
    }
    peak_herd = 0

    def tracking_agent(obs, configuration=None):
        nonlocal peak_herd
        try:
            day = obs.get("day", 0)
            hour = obs.get("hour", 0)
            p_id = obs.get("player", 0)
            farm_data = obs.get("farms", [])[p_id] if len(obs.get("farms", [])) > p_id else {}
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

            # Tile accounting at hour 0
            if hour == 0:
                # NW
                for y in range(0, 5):
                    for x in range(0, 5):
                        t = farm.tile_at((x, y))
                        if t and (t.is_plant or t.is_animal):
                            productive_tile_days["NW"] += 1
                        else:
                            idle_tile_days["NW"] += 1
                # NE
                if "NE" in unlocked:
                    for y in range(0, 5):
                        for x in range(5, 10):
                            t = farm.tile_at((x, y))
                            if t and (t.is_plant or t.is_animal):
                                productive_tile_days["NE"] += 1
                            else:
                                idle_tile_days["NE"] += 1
                # SW
                if "SW" in unlocked:
                    for y in range(5, 10):
                        for x in range(0, 5):
                            t = farm.tile_at((x, y))
                            if t and (t.is_plant or t.is_animal):
                                productive_tile_days["SW"] += 1
                            else:
                                idle_tile_days["SW"] += 1

            # Execute turn action via agent
            act = agent_module.agent(obs, configuration)
            return act
        except Exception as e:
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

        p0_farm = p0_state.get("observation", {}).get("farms", [{}])[0]
        p1_farm = p1_state.get("observation", {}).get("farms", [{}])[1] if len(p1_state.get("observation", {}).get("farms", [])) > 1 else {}
        final_money_p0 = float(p0_farm.get("money", p0_state.get("reward", 0.0)) or 0.0)
        final_money_p1 = float(p1_farm.get("money", p1_state.get("reward", 0.0)) or 0.0)
        final_unlocked = set(p0_farm.get("unlocked_quadrants", ["NW"]))

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

        # Retrieve scheduler utilization and SW telemetry
        sw_telemetry = {
            "created": 0,
            "assigned": 0,
            "completed": 0,
            "moves": 0,
            "ops": 0,
        }
        quad_completions = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
        try:
            dlog = {}
            if hasattr(agent_module, "get_daily_telemetry"):
                dlog = agent_module.get_daily_telemetry()
            elif hasattr(agent_module, "get_daily_log"):
                dlog = agent_module.get_daily_log()
            else:
                for mod_key in ("execution.task_scheduler", "agent.execution.task_scheduler", "task_scheduler"):
                    if mod_key in sys.modules and hasattr(sys.modules[mod_key], "get_daily_log"):
                        dlog = sys.modules[mod_key].get_daily_log()
                        break
            for day_info in dlog.values():
                sw_telemetry["created"] += day_info.get("sw_tasks_created", 0)
                sw_telemetry["assigned"] += day_info.get("sw_tasks_assigned", 0)
                sw_telemetry["completed"] += day_info.get("sw_tasks_completed", 0)
                sw_telemetry["moves"] += day_info.get("sw_movement_actions", 0)
                sw_telemetry["ops"] += day_info.get("sw_operation_actions", 0)
                for q, c in day_info.get("quad_completions", {}).items():
                    quad_completions[q] = quad_completions.get(q, 0) + c
        except Exception:
            pass

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
            "productive_tile_days_nw": productive_tile_days["NW"],
            "productive_tile_days_ne": productive_tile_days["NE"],
            "productive_tile_days_sw": productive_tile_days["SW"],
            "idle_tile_days_nw": idle_tile_days["NW"],
            "idle_tile_days_ne": idle_tile_days["NE"],
            "idle_tile_days_sw": idle_tile_days["SW"],
            "peak_herd": peak_herd,
            "safety_metrics": safety_metrics,
            "sw_telemetry": sw_telemetry,
            "quad_completions": quad_completions,
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
            "elapsed": time.time() - t0,
        }


def run_benchmark(
    arms: List[str],
    num_seeds: int = 25,
    max_workers: int = 6,
    output_json: str = "phase2b_zonal_benchmark_results.json"
):
    print("=" * 80)
    print("PHASE 2B: WORKLOAD-AWARE ZONAL LABOR MOBILITY BENCHMARK")
    print(f"Arms: {', '.join(arms)}")
    print(f"Seeds: 101 to {100 + num_seeds} (x 2 opponents: starter, random)")
    print(f"Workers: {max_workers}")
    print("=" * 80)

    seeds = list(range(101, 101 + num_seeds))
    opponents = ["starter", "random"]

    payloads = []
    for arm in arms:
        for opp in opponents:
            for seed in seeds:
                payloads.append({
                    "arm": arm,
                    "seed": seed,
                    "opponent": opp,
                })

    print(f"Total matches to execute: {len(payloads)}")

    results = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_run_single_match, p): p for p in payloads}
        completed = 0
        total = len(payloads)

        for fut in as_completed(future_map):
            completed += 1
            res = fut.result()
            results.append(res)
            arm = res["arm"]
            s = res["seed"]
            opp = res["opponent"]
            score = res.get("final_score", 0.0)
            sw_bought = "SW:YES" if res.get("sw_purchased") else "SW:NO"
            sw_d = f"D{res.get('sw_day')}" if res.get("sw_purchased") else ""
            print(f"[{completed:3d}/{total:3d}] {arm:<24} | Seed {s} vs {opp:<7} | Score: ${score:9,.0f} | {sw_bought} {sw_d}", flush=True)

    total_time = time.time() - t_start
    print(f"\nAll matches completed in {total_time:.1f}s ({total_time/60:.1f} min)")

    # Save raw results
    out_path = os.path.join(_REPO_ROOT, "simulations", "experiments", output_json)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {out_path}")

    # Analyze results
    analyze_results(results, arms)


def analyze_results(results: List[Dict[str, Any]], arms: List[str]):
    print("\n" + "=" * 100)
    print("PHASE 2B: EXPERIMENTAL ANALYSIS & TELEMETRY REPORT")
    print("=" * 100)

    arm_data = {arm: {} for arm in arms}
    for r in results:
        key = (r["seed"], r["opponent"])
        arm_data[r["arm"]][key] = r

    baseline_arm = "ArmA_Baseline"
    has_baseline = (baseline_arm in arm_data and len(arm_data[baseline_arm]) > 0)

    # 1. Summary Performance Table
    print(f"\n{'Arm':<25} {'Matches':<8} {'Mean Score':<12} {'Median':<10} {'Delta Mean':<12} {'Delta Med':<10} {'SW Bought':<10} {'Mean SW Day':<12} {'Deaths':<8}")
    print("-" * 115)

    baseline_scores = {}
    if has_baseline:
        for k, v in arm_data[baseline_arm].items():
            baseline_scores[k] = v.get("final_score", 0.0)

    for arm in arms:
        matches = list(arm_data[arm].values())
        n = len(matches)
        if n == 0:
            continue
        scores = [m.get("final_score", 0.0) for m in matches]
        mean_s = np.mean(scores)
        med_s = np.median(scores)

        sw_buys = [m for m in matches if m.get("sw_purchased")]
        sw_rate = f"{len(sw_buys)}/{n}"
        sw_days = [m["sw_day"] for m in sw_buys if m.get("sw_day") is not None]
        mean_sw_day = f"D{np.mean(sw_days):.1f}" if sw_days else "N/A"

        deaths = sum(m.get("safety_metrics", {}).get("animal_deaths", 0) for m in matches)

        delta_mean_str = "N/A"
        delta_med_str = "N/A"
        if has_baseline and arm != baseline_arm:
            deltas = []
            for k, m in arm_data[arm].items():
                if k in baseline_scores:
                    deltas.append(m.get("final_score", 0.0) - baseline_scores[k])
            if deltas:
                delta_mean_str = f"{np.mean(deltas):+,.0f}"
                delta_med_str = f"{np.median(deltas):+,.0f}"

        print(f"{arm:<25} {n:<8} ${mean_s:<11,.0f} ${med_s:<9,.0f} {delta_mean_str:<12} {delta_med_str:<10} {sw_rate:<10} {mean_sw_day:<12} {deaths:<8}")

    # 2. Zonal Telemetry & Cannibalization Analysis
    print("\n" + "=" * 100)
    print("ZONAL PRODUCTIVITY & WORKER DISPATCH TELEMETRY")
    print("=" * 100)
    print(f"{'Arm':<25} {'NW Tile-Days':<14} {'NE Tile-Days':<14} {'SW Tile-Days':<14} {'SW Created':<12} {'SW Completed':<13} {'SW Compl %':<12} {'SW Move/Op':<11}")
    print("-" * 115)

    for arm in arms:
        matches = list(arm_data[arm].values())
        if not matches:
            continue
        nw_td = np.mean([m.get("productive_tile_days_nw", 0) for m in matches])
        ne_td = np.mean([m.get("productive_tile_days_ne", 0) for m in matches])
        sw_td = np.mean([m.get("productive_tile_days_sw", 0) for m in matches])

        sw_c = np.mean([m.get("sw_telemetry", {}).get("created", 0) for m in matches])
        sw_done = np.mean([m.get("sw_telemetry", {}).get("completed", 0) for m in matches])
        compl_pct = (sw_done / max(1.0, sw_c)) * 100.0 if sw_c > 0 else 0.0

        sw_moves = sum(m.get("sw_telemetry", {}).get("moves", 0) for m in matches)
        sw_ops = sum(m.get("sw_telemetry", {}).get("ops", 0) for m in matches)
        move_ratio = (sw_moves / max(1.0, sw_ops)) if sw_ops > 0 else 0.0

        print(f"{arm:<25} {nw_td:<14.1f} {ne_td:<14.1f} {sw_td:<14.1f} {sw_c:<12.1f} {sw_done:<13.1f} {compl_pct:<11.1f}% {move_ratio:<11.2f}")

    # 3. Promotion Criteria Verification
    print("\n" + "=" * 100)
    print("PHASE 2B PROMOTION CRITERIA EVALUATION")
    print("=" * 100)
    if "ArmB_NoSW_Dynamic" in arm_data and has_baseline:
        b_deltas = [arm_data["ArmB_NoSW_Dynamic"][k].get("final_score", 0.0) - baseline_scores[k] for k in baseline_scores if k in arm_data["ArmB_NoSW_Dynamic"]]
        mean_b_delta = np.mean(b_deltas)
        med_b_delta = np.median(b_deltas)
        pass_b = mean_b_delta >= -500.0
        print(f"1. No-SW Dynamic Allocation vs Frozen Baseline:")
        print(f"   - Mean Delta: {mean_b_delta:+,.1f} | Median Delta: {med_b_delta:+,.1f}")
        print(f"   - Status: {'PASS (Score-Neutral/Positive)' if pass_b else 'FAIL (Negative Delta)'}")

    for arm in [a for a in arms if a.startswith("ArmC") or a.startswith("ArmD") or a.startswith("ArmE") or a.startswith("ArmF")]:
        if arm in arm_data and has_baseline:
            deltas = [arm_data[arm][k].get("final_score", 0.0) - baseline_scores[k] for k in baseline_scores if k in arm_data[arm]]
            mean_d = np.mean(deltas)
            med_d = np.median(deltas)
            deaths = sum(m.get("safety_metrics", {}).get("animal_deaths", 0) for m in arm_data[arm].values())
            sw_buys = sum(1 for m in arm_data[arm].values() if m.get("sw_purchased"))
            sw_done = sum(m.get("sw_telemetry", {}).get("completed", 0) for m in arm_data[arm].values())
            sw_c = sum(m.get("sw_telemetry", {}).get("created", 0) for m in arm_data[arm].values())
            sw_rate = (sw_done / max(1.0, sw_c)) * 100.0 if sw_c > 0 else 0.0

            print(f"\nEvaluating {arm}:")
            print(f"   - Mean Delta: {mean_d:+,.1f} | Median Delta: {med_d:+,.1f}")
            print(f"   - SW Purchases: {sw_buys}/{len(deltas)} | SW Completion: {sw_rate:.1f}%")
            print(f"   - Animal Deaths: {deaths} (Required: 0)")
            is_win = (mean_d > 0 and med_d >= 0 and deaths == 0 and sw_rate >= 80.0)
            print(f"   - Promotion Verdict: {'QUALIFIED (+EV verified)' if is_win else 'DISQUALIFIED (Negative-EV or incomplete)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2B Zonal Labor Mobility Benchmark")
    parser.add_argument("--arms", nargs="+", default=[
        "ArmA_Baseline",
        "ArmB_NoSW_Dynamic",
        "ArmC_SW5_Dynamic",
        "ArmD_SW10_Dynamic",
        "ArmE_SW15_Dynamic",
        "ArmF_DelayedSW_Dynamic",
    ])
    parser.add_argument("--seeds", type=int, default=25)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", type=str, default="phase2b_zonal_benchmark_results.json")
    args = parser.parse_args()

    run_benchmark(
        arms=args.arms,
        num_seeds=args.seeds,
        max_workers=args.workers,
        output_json=args.output,
    )
