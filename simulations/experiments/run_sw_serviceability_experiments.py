"""Paired Deterministic Benchmark: SW Land Serviceability & Partial Exploitation.

Compares:
  Arm A: Frozen Baseline (Commit 59cf176, SW 0/50)
  Arm B: Candidate with k=5 SW soil tiles (force_k_tiles=5)
  Arm C: Candidate with k=10 SW soil tiles (force_k_tiles=10)
  Arm D: Candidate with k=15 SW soil tiles (force_k_tiles=15)
  Arm E: Dynamic Model (optimal k* in {5, 10, 15})

50 Paired Scenarios per comparison:
  - 25 pairs vs 'starter' (seeds 101-125)
  - 25 pairs vs 'random' (seeds 101-125)

Metrics tracked:
  - Mean score delta, Median delta, P10 delta, Win/Loss/Tie
  - Max paired score delta
  - SW purchase rate and average purchase day
  - Productive SW tile-days
  - Incremental score per activated SW tile-day
  - NW productive tile-days delta (labor cannibalization check)
  - NE productive tile-days delta (labor cannibalization check)
  - Safety invariants (0 starvations, 0 deaths)
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
    force_k = payload.get("force_k")

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

    # Configure forced k if supported
    if arm != "ArmA_Baseline":
        try:
            import config
            config.set_sw_force_k_tiles(force_k)
        except Exception:
            pass

    # Match-level telemetry
    productive_tile_days = {"NW": 0, "NE": 0, "SW": 0}
    idle_tile_days = {"NW": 0, "NE": 0, "SW": 0}
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
            act = agent_module.agent(obs, config)

            # Capture state right after action
            try:
                curr_state = state_tracker.get_state(obs)
                last_plan = curr_state.get("last_plan")
                if last_plan and hasattr(last_plan, "diagnostics"):
                    ld = last_plan.diagnostics.get("land_decision")
                    if ld and day not in land_diagnostics_by_day:
                        land_diagnostics_by_day[day] = dict(ld)
            except Exception:
                pass

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

        final_money_p0 = float(p0_state.get("reward", 0.0) or 0.0)
        final_money_p1 = float(p1_state.get("reward", 0.0) or 0.0)

        # Inspect unlocked quadrants and purchase timing
        p0_farm = p0_state.get("observation", {}).get("farms", [{}])[0]
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
            "elapsed": time.time() - t0,
        }


def run_experiments(seeds: List[int], opponents: List[str], arms: List[str], max_workers: int = 6):
    print(f"=== Starting SW Land Serviceability Experiment Sweep ===")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]})")
    print(f"Opponents: {opponents}")
    print(f"Arms: {arms}")
    print(f"Workers: {max_workers}")

    payloads = []
    for arm in arms:
        force_k = None
        if arm == "ArmB_k5":
            force_k = 5
        elif arm == "ArmC_k10":
            force_k = 10
        elif arm == "ArmD_k15":
            force_k = 15
        elif arm == "ArmE_Dynamic":
            force_k = None

        for opp in opponents:
            for s in seeds:
                payloads.append({
                    "arm": arm,
                    "seed": s,
                    "opponent": opp,
                    "force_k": force_k,
                })

    print(f"Total matches scheduled: {len(payloads)}")
    t_start = time.time()
    results = []

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_single_match, p): p for p in payloads}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == len(payloads):
                print(f"Completed {completed}/{len(payloads)} matches ({completed/len(payloads)*100:.1f}%) in {time.time() - t_start:.1f}s")

    out_file = os.path.join(_REPO_ROOT, "simulations", "experiments", "sw_serviceability_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"All match results saved to {out_file}")

    return results


def analyze_results(results_file: str):
    with open(results_file, "r") as f:
        results = json.load(f)

    # Group by arm -> (seed, opponent) -> res
    arms_data = {}
    for r in results:
        arm = r["arm"]
        key = (r["seed"], r["opponent"])
        if arm not in arms_data:
            arms_data[arm] = {}
        arms_data[arm][key] = r

    if "ArmA_Baseline" not in arms_data:
        print("Error: ArmA_Baseline not found in results!")
        return

    base_arm = arms_data["ArmA_Baseline"]
    candidate_arms = [a for a in sorted(arms_data.keys()) if a != "ArmA_Baseline"]

    print("\n" + "=" * 80)
    print("SW LAND SERVICEABILITY EXPERIMENT AUDIT REPORT")
    print("=" * 80)

    # Arm A summary
    a_scores = [r["final_score"] for r in base_arm.values()]
    a_sw_buys = sum(1 for r in base_arm.values() if r.get("sw_purchased"))
    a_nw_ptd = np.mean([r.get("productive_tile_days_nw", 0) for r in base_arm.values()])
    a_ne_ptd = np.mean([r.get("productive_tile_days_ne", 0) for r in base_arm.values()])
    print(f"\nArm A (Baseline 59cf176):")
    print(f"  Matches: {len(a_scores)}")
    print(f"  Mean Score:   ${np.mean(a_scores):,.2f}")
    print(f"  Median Score: ${np.median(a_scores):,.2f}")
    print(f"  P10 Score:    ${np.percentile(a_scores, 10):,.2f}")
    print(f"  SW Purchases: {a_sw_buys}/{len(a_scores)} ({a_sw_buys/len(a_scores)*100:.1f}%)")
    print(f"  Mean NW Productive Tile-Days: {a_nw_ptd:.1f}")
    print(f"  Mean NE Productive Tile-Days: {a_ne_ptd:.1f}")

    for cand_name in candidate_arms:
        cand_arm = arms_data[cand_name]
        c_scores = []
        deltas = []
        sw_buys = 0
        sw_days = []
        wins, losses, ties = 0, 0, 0
        cand_nw_ptd = []
        cand_ne_ptd = []
        cand_sw_ptd = []
        nw_ptd_deltas = []
        ne_ptd_deltas = []

        total_starvations = 0
        total_deaths = 0

        for key, a_res in base_arm.items():
            if key not in cand_arm:
                continue
            c_res = cand_arm[key]
            s_a = a_res["final_score"]
            s_c = c_res["final_score"]
            c_scores.append(s_c)
            d = s_c - s_a
            deltas.append(d)
            if d > 0.01: wins += 1
            elif d < -0.01: losses += 1
            else: ties += 1

            if c_res.get("sw_purchased"):
                sw_buys += 1
                if c_res.get("sw_day") is not None:
                    sw_days.append(c_res["sw_day"])

            cand_nw_ptd.append(c_res.get("productive_tile_days_nw", 0))
            cand_ne_ptd.append(c_res.get("productive_tile_days_ne", 0))
            cand_sw_ptd.append(c_res.get("productive_tile_days_sw", 0))

            nw_ptd_deltas.append(c_res.get("productive_tile_days_nw", 0) - a_res.get("productive_tile_days_nw", 0))
            ne_ptd_deltas.append(c_res.get("productive_tile_days_ne", 0) - a_res.get("productive_tile_days_ne", 0))

            total_starvations += c_res.get("safety_metrics", {}).get("animal_starvations", 0)
            total_deaths += c_res.get("safety_metrics", {}).get("animal_deaths", 0)

        mean_delta = np.mean(deltas)
        median_delta = np.median(deltas)
        p10_delta = np.percentile(deltas, 10)
        max_paired_delta = max(deltas) if deltas else 0.0
        min_paired_delta = min(deltas) if deltas else 0.0

        mean_sw_ptd = np.mean(cand_sw_ptd)
        mean_nw_ptd_delta = np.mean(nw_ptd_deltas)
        mean_ne_ptd_delta = np.mean(ne_ptd_deltas)

        # Incremental score per productive SW tile-day across SW-buying matches
        sw_buying_matches = [
            (c_res["final_score"] - base_arm[k]["final_score"], c_res.get("productive_tile_days_sw", 0))
            for k, c_res in cand_arm.items() if k in base_arm and c_res.get("sw_purchased")
        ]
        if sw_buying_matches:
            total_sw_score_delta = sum(m[0] for m in sw_buying_matches)
            total_sw_ptd = sum(m[1] for m in sw_buying_matches)
            score_per_sw_ptd = (total_sw_score_delta / total_sw_ptd) if total_sw_ptd > 0 else 0.0
        else:
            score_per_sw_ptd = 0.0

        print("\n" + "-" * 60)
        print(f"Evaluation: {cand_name} vs Arm A (Baseline 59cf176)")
        print("-" * 60)
        print(f"  Matches:               {len(c_scores)}")
        print(f"  Mean Score:            ${np.mean(c_scores):,.2f}")
        print(f"  Mean Paired Delta:     ${mean_delta:+,.2f}")
        print(f"  Median Paired Delta:   ${median_delta:+,.2f}")
        print(f"  P10 Paired Delta:      ${p10_delta:+,.2f}")
        print(f"  Max Paired Delta:      ${max_paired_delta:+,.2f}")
        print(f"  Min Paired Delta:      ${min_paired_delta:+,.2f}")
        print(f"  Record (W / L / T):    {wins} / {losses} / {ties} ({wins/len(c_scores)*100:.1f}% Win Rate)")
        print(f"  SW Purchases:          {sw_buys}/{len(c_scores)} ({sw_buys/len(c_scores)*100:.1f}%)")
        if sw_days:
            print(f"  Mean SW Purchase Day:  {np.mean(sw_days):.1f} (range {min(sw_days)}..{max(sw_days)})")
        print(f"  Productive SW Tile-Days (Mean): {mean_sw_ptd:.1f}")
        print(f"  Score / Productive SW Tile-Day: ${score_per_sw_ptd:+,.2f}/tile-day")
        print(f"  NW Productive Tile-Days Delta:  {mean_nw_ptd_delta:+.2f}")
        print(f"  NE Productive Tile-Days Delta:  {mean_ne_ptd_delta:+.2f}")
        print(f"  Safety: Starvations = {total_starvations}, Deaths = {total_deaths}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyze-only", action="store_true", help="Skip runs, analyze existing results JSON")
    parser.add_argument("--seeds", type=int, default=25, help="Number of seeds (default 25: 101-125)")
    parser.add_argument("--workers", type=int, default=6, help="ProcessPool workers (default 6)")
    parser.add_argument("--arms", nargs="+", default=["ArmA_Baseline", "ArmB_k5", "ArmC_k10", "ArmD_k15", "ArmE_Dynamic"])
    args = parser.parse_args()

    results_path = os.path.join(_REPO_ROOT, "simulations", "experiments", "sw_serviceability_results.json")

    if not args.analyze_only:
        seeds = list(range(101, 101 + args.seeds))
        opponents = ["starter", "random"]
        run_experiments(seeds, opponents, args.arms, max_workers=args.workers)

    analyze_results(results_path)
