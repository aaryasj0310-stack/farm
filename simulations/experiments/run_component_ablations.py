"""Component Ablation Tournament: Arms A0 through A4.

Evaluates isolated intelligence components against O0 baseline across paired,
seat-swapped seeds to determine which signals create genuine value.

Arms:
  A0: O0 baseline (empty OpponentAdvice)
  A1: O0 + directly observed commitments (structures, animals, crops -> counter_pick)
  A2: O0 + high-confidence recent inferred sales (rolling 4-turn market sales -> delay_sell)
  A3: O0 + repaired forward production forecasts (lifecycle schedules -> supply_adjustment)
  A4: O0 + high-confidence inventory bounds (Milk/Wool/Egg bounds -> opp_shed_pressure)

Opponents:
  - full_production_agent (mixed production)
  - melon_sniper (crop-heavy / dump-heavy)
"""

import os
import sys
import time
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
from scipy import stats

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

ARMS = ["A0", "A1", "A2", "A3", "A4"]


def compute_bootstrap_ci(
    data: List[float],
    num_resamples: int = 10000,
    ci: float = 0.95,
    seed: int = 42
) -> Tuple[float, float]:
    """Compute bootstrap percentile confidence interval on the mean of paired deltas."""
    if len(data) == 0:
        return 0.0, 0.0
    rng = np.random.RandomState(seed)
    arr = np.array(data, dtype=float)
    n = len(arr)
    indices = rng.randint(0, n, size=(num_resamples, n))
    resampled_means = np.mean(arr[indices], axis=1)
    lower = float(np.percentile(resampled_means, (1.0 - ci) / 2.0 * 100.0))
    upper = float(np.percentile(resampled_means, (1.0 + ci) / 2.0 * 100.0))
    return lower, upper


def _run_single_ablation_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    arm = payload["arm"]            # "A0", "A1", "A2", "A3", "A4"
    seed = payload["seed"]
    opponent_name = payload["opponent_name"]
    seat = payload["seat"]          # 0 (our agent is P0) or 1 (our agent is P1)

    # Clean module cache for isolation
    to_delete = [k for k in list(sys.modules.keys()) if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    import execution.task_scheduler as task_scheduler
    from simulations.experiments.agent_zoo import get_agent

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    task_scheduler.reset_worker_locality()

    # Production baseline invariants
    config.set_sw_experiment_arm("ArmA")
    config.set_opponent_intelligence_mode(arm)

    opp_callable = get_agent(opponent_name)

    if seat == 0:
        players = [agent_module.agent, opp_callable]
        our_idx = 0
        opp_idx = 1
    else:
        players = [opp_callable, agent_module.agent]
        our_idx = 1
        opp_idx = 0

    env = make("kaggriculture", configuration={"randomSeed": seed}, debug=False)
    steps = env.run(players)

    our_score = float(steps[-1][our_idx]["reward"] or 0.0)
    opp_score = float(steps[-1][opp_idx]["reward"] or 0.0)
    we_won = (our_score > opp_score)
    is_tie = (our_score == opp_score)

    return {
        "arm": arm,
        "seed": seed,
        "opponent_name": opponent_name,
        "seat": seat,
        "our_score": our_score,
        "opp_score": opp_score,
        "margin": our_score - opp_score,
        "we_won": we_won,
        "is_tie": is_tie,
    }


def run_ablation_tournament(
    seeds: List[int],
    opponents: List[str] = ["full_production_agent", "melon_sniper"],
    arms: List[str] = ARMS,
    max_workers: int = 8,
) -> Dict[str, Any]:
    print(f"=== Starting Component Ablation Tournament (Arms: {arms}) ===")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Opponents: {opponents} | Seat-swapped: Yes")

    tasks = []
    for opp in opponents:
        for s in seeds:
            for seat in (0, 1):
                for arm in arms:
                    tasks.append({"arm": arm, "seed": s, "opponent_name": opp, "seat": seat})

    total_matches = len(tasks)
    print(f"Total matches to execute: {total_matches}")

    results_map: Dict[Tuple[str, int, int, str], Dict[str, Any]] = {}
    start_time = time.time()
    completed = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_ablation_match, t): t for t in tasks}
        for fut in as_completed(futures):
            res = fut.result()
            completed += 1
            key = (res["opponent_name"], res["seed"], res["seat"], res["arm"])
            results_map[key] = res
            if completed % 20 == 0 or completed == total_matches:
                elapsed = time.time() - start_time
                print(f"[{completed}/{total_matches}] matches completed ({elapsed:.1f}s)")

    # Aggregate paired deltas vs A0 baseline
    report = {
        "metadata": {
            "seeds": seeds,
            "opponents": opponents,
            "arms": arms,
            "total_matches": total_matches,
            "runtime_seconds": time.time() - start_time,
        },
        "opponents": {},
        "macro_summary": {},
    }

    macro_arm_deltas = {arm: [] for arm in arms if arm != "A0"}
    macro_arm_margins = {arm: [] for arm in arms if arm != "A0"}

    for opp in opponents:
        report["opponents"][opp] = {"arms": {}, "arm_comparisons_vs_a0": {}}

        # Raw performance for each arm
        for arm in arms:
            arm_matches = [
                results_map[(opp, s, seat, arm)]
                for s in seeds for seat in (0, 1)
                if (opp, s, seat, arm) in results_map
            ]
            our_scores = [m["our_score"] for m in arm_matches]
            opp_scores = [m["opp_score"] for m in arm_matches]
            margins = [m["margin"] for m in arm_matches]
            wins = sum(1 for m in arm_matches if m["we_won"])
            ties = sum(1 for m in arm_matches if m["is_tie"])
            losses = len(arm_matches) - wins - ties
            n = len(arm_matches)

            report["opponents"][opp]["arms"][arm] = {
                "n_matches": n,
                "mean_our_score": float(np.mean(our_scores)) if n else 0.0,
                "median_our_score": float(np.median(our_scores)) if n else 0.0,
                "mean_opp_score": float(np.mean(opp_scores)) if n else 0.0,
                "mean_margin": float(np.mean(margins)) if n else 0.0,
                "win_rate": wins / max(1, n),
                "record": {"wins": wins, "ties": ties, "losses": losses},
            }

        # Paired comparison vs A0
        for arm in [a for a in arms if a != "A0"]:
            paired_pairs = []
            for s in seeds:
                for seat in (0, 1):
                    r_arm = results_map.get((opp, s, seat, arm))
                    r_a0 = results_map.get((opp, s, seat, "A0"))
                    if r_arm and r_a0:
                        d_our = r_arm["our_score"] - r_a0["our_score"]
                        d_opp = r_arm["opp_score"] - r_a0["opp_score"]
                        d_margin = r_arm["margin"] - r_a0["margin"]
                        paired_pairs.append({
                            "seed": s, "seat": seat,
                            "arm_our": r_arm["our_score"], "a0_our": r_a0["our_score"], "delta_our": d_our,
                            "arm_opp": r_arm["opp_score"], "a0_opp": r_a0["opp_score"], "delta_opp": d_opp,
                            "arm_margin": r_arm["margin"], "a0_margin": r_a0["margin"], "delta_margin": d_margin,
                            "arm_won": r_arm["we_won"], "a0_won": r_a0["we_won"],
                        })

            n = len(paired_pairs)
            d_ours = [p["delta_our"] for p in paired_pairs]
            d_opps = [p["delta_opp"] for p in paired_pairs]
            d_margins = [p["delta_margin"] for p in paired_pairs]

            macro_arm_deltas[arm].extend(d_ours)
            macro_arm_margins[arm].extend(d_margins)

            mean_d_our = float(np.mean(d_ours)) if n else 0.0
            median_d_our = float(np.median(d_ours)) if n else 0.0
            mean_d_opp = float(np.mean(d_opps)) if n else 0.0
            mean_d_margin = float(np.mean(d_margins)) if n else 0.0

            ci_d_our = compute_bootstrap_ci(d_ours)
            ci_d_margin = compute_bootstrap_ci(d_margins)

            arm_wr = sum(1 for p in paired_pairs if p["arm_won"]) / max(1, n)
            a0_wr = sum(1 for p in paired_pairs if p["a0_won"]) / max(1, n)
            wr_delta = arm_wr - a0_wr

            p_val = 1.0
            if n > 1 and len(set(d_ours)) > 1:
                try:
                    _, p_val = stats.ttest_rel([p["arm_our"] for p in paired_pairs], [p["a0_our"] for p in paired_pairs])
                except Exception:
                    pass

            # Outcome classification
            if mean_d_our > 0 and mean_d_opp <= 0:
                verdict = "gainful_suppression"
            elif mean_d_our > 0 and mean_d_opp > 0:
                verdict = "gainful"
            elif mean_d_our <= 0 and mean_d_opp < 0:
                verdict = "costly_suppression"
            elif mean_d_our <= 0 and mean_d_opp >= 0:
                verdict = "harmful"
            else:
                verdict = "neutral"

            report["opponents"][opp]["arm_comparisons_vs_a0"][arm] = {
                "n_paired": n,
                "mean_delta_our": mean_d_our,
                "median_delta_our": median_d_our,
                "ci_95_delta_our": ci_d_our,
                "p_value_our": float(p_val),
                "mean_delta_opp": mean_d_opp,
                "mean_delta_margin": mean_d_margin,
                "ci_95_delta_margin": ci_d_margin,
                "win_rate_delta": wr_delta,
                "verdict": verdict,
                "paired_details": paired_pairs,
            }

    # Macro summary across all opponents
    for arm in [a for a in arms if a != "A0"]:
        all_d_our = macro_arm_deltas[arm]
        all_d_margin = macro_arm_margins[arm]
        n_tot = len(all_d_our)
        report["macro_summary"][arm] = {
            "total_paired_matches": n_tot,
            "mean_delta_our": float(np.mean(all_d_our)) if n_tot else 0.0,
            "median_delta_our": float(np.median(all_d_our)) if n_tot else 0.0,
            "ci_95_delta_our": compute_bootstrap_ci(all_d_our),
            "mean_delta_margin": float(np.mean(all_d_margin)) if n_tot else 0.0,
            "ci_95_delta_margin": compute_bootstrap_ci(all_d_margin),
            "positive_delta_fraction": float(np.mean([x > 0 for x in all_d_our])) if n_tot else 0.0,
        }

    out_dir = os.path.join(PROJECT_ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "component_ablation_report.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*85}")
    print(f"COMPONENT ABLATION TOURNAMENT SUMMARY (VS A0 BASELINE)")
    print(f"{'='*85}")
    print(f"{'Arm':5s} | {'Opponent':22s} | {'Delta Our ($)':15s} | {'95% CI':18s} | {'WinRate Delta':14s} | {'Verdict'}")
    print(f"{'-'*85}")
    for opp in opponents:
        for arm in [a for a in arms if a != "A0"]:
            comp = report["opponents"][opp]["arm_comparisons_vs_a0"][arm]
            ci_str = f"[{comp['ci_95_delta_our'][0]:+.0f}, {comp['ci_95_delta_our'][1]:+.0f}]"
            print(f"{arm:5s} | {opp:22s} | ${comp['mean_delta_our']:+9.1f}     | {ci_str:18s} | {comp['win_rate_delta']*100:+7.1f}%       | {comp['verdict']}")
        print(f"{'-'*85}")

    print("\nMACRO OVERALL IMPACT (ACROSS ALL OPPONENTS):")
    for arm, m_rep in report["macro_summary"].items():
        ci_str = f"[{m_rep['ci_95_delta_our'][0]:+.0f}, {m_rep['ci_95_delta_our'][1]:+.0f}]"
        print(f"  {arm:4s}: Mean Delta Our = ${m_rep['mean_delta_our']:+8.1f} (Median: ${m_rep['median_delta_our']:+8.1f}, CI: {ci_str}), Win/Better Rate: {m_rep['positive_delta_fraction']*100:.1f}%")
    print(f"{'='*85}\nReport saved to: {out_file}")

    return report


if __name__ == "__main__":
    seeds_screening = list(range(100, 110))
    run_ablation_tournament(seeds=seeds_screening, opponents=["full_production_agent", "melon_sniper"])
