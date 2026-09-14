"""Phase 1: Rigorous O0 vs O1 Paired, Seat-Swapped Tournament.

Compares:
  O0: Opponent intelligence completely disabled (empty OpponentAdvice)
  O1: Current opponent intelligence unchanged (baseline)

Measures:
  - Delta our score
  - Delta opponent score
  - Delta score margin = Delta our - Delta opponent
  - Win rate change
  - Classification: self-profit gain, opponent suppression, or mixed

Opponent profiles:
  - Mixed: full_production_agent
  - Crop-heavy / Dump-heavy: melon_sniper
  - Livestock-heavy: cow_milk_engine
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


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = payload["mode"]          # "O0" or "O1"
    seed = payload["seed"]
    opponent_name = payload["opponent_name"]
    seat = payload["seat"]          # 0 (our agent is P0) or 1 (our agent is P1)

    # Module reload isolation
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

    # Freeze SW out of production for both modes
    config.set_sw_experiment_arm("ArmA")
    config.set_opponent_intelligence_mode(mode)

    opp_callable = get_agent(opponent_name)

    # Seat allocation
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
        "mode": mode,
        "seed": seed,
        "opponent_name": opponent_name,
        "seat": seat,
        "our_score": our_score,
        "opp_score": opp_score,
        "margin": our_score - opp_score,
        "we_won": we_won,
        "is_tie": is_tie,
    }


def run_o0_vs_o1_tournament(
    seeds: List[int],
    opponents: List[str] = ["full_production_agent", "melon_sniper", "cow_milk_engine"],
    max_workers: int = 4,
) -> Dict[str, Any]:
    print(f"=== Starting Phase 1 O0 vs O1 Tournament ===")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Opponents: {opponents} | Seat-swapped: Yes")

    # Build task pairs: for each (opponent, seed, seat), run O0 and O1
    tasks = []
    for opp in opponents:
        for s in seeds:
            for seat in (0, 1):
                tasks.append({"mode": "O1", "seed": s, "opponent_name": opp, "seat": seat})
                tasks.append({"mode": "O0", "seed": s, "opponent_name": opp, "seat": seat})

    total_matches = len(tasks)
    print(f"Total matches to execute: {total_matches}")

    results_map: Dict[Tuple[str, int, int, str], Dict[str, Any]] = {}
    start_time = time.time()
    completed = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_match, t): t for t in tasks}
        for fut in as_completed(futures):
            res = fut.result()
            completed += 1
            key = (res["opponent_name"], res["seed"], res["seat"], res["mode"])
            results_map[key] = res
            if completed % 10 == 0 or completed == total_matches:
                elapsed = time.time() - start_time
                print(f"[{completed}/{total_matches}] matches completed ({elapsed:.1f}s)")

    # Aggregate by opponent profile and overall
    overall_report = {}

    for opp in opponents:
        paired_records = []
        for s in seeds:
            for seat in (0, 1):
                r_o1 = results_map.get((opp, s, seat, "O1"))
                r_o0 = results_map.get((opp, s, seat, "O0"))
                if r_o1 and r_o0:
                    d_our = r_o1["our_score"] - r_o0["our_score"]
                    d_opp = r_o1["opp_score"] - r_o0["opp_score"]
                    d_margin = r_o1["margin"] - r_o0["margin"]
                    paired_records.append({
                        "seed": s, "seat": seat,
                        "o1_our": r_o1["our_score"], "o0_our": r_o0["our_score"], "d_our": d_our,
                        "o1_opp": r_o1["opp_score"], "o0_opp": r_o0["opp_score"], "d_opp": d_opp,
                        "o1_margin": r_o1["margin"], "o0_margin": r_o0["margin"], "d_margin": d_margin,
                        "o1_won": r_o1["we_won"], "o0_won": r_o0["we_won"],
                    })

        n = len(paired_records)
        o1_ours = [r["o1_our"] for r in paired_records]
        o0_ours = [r["o0_our"] for r in paired_records]
        o1_opps = [r["o1_opp"] for r in paired_records]
        o0_opps = [r["o0_opp"] for r in paired_records]
        d_ours = [r["d_our"] for r in paired_records]
        d_opps = [r["d_opp"] for r in paired_records]
        d_margins = [r["d_margin"] for r in paired_records]

        mean_d_our = float(np.mean(d_ours)) if n else 0.0
        median_d_our = float(np.median(d_ours)) if n else 0.0
        mean_d_opp = float(np.mean(d_opps)) if n else 0.0
        median_d_opp = float(np.median(d_opps)) if n else 0.0
        mean_d_margin = float(np.mean(d_margins)) if n else 0.0
        median_d_margin = float(np.median(d_margins)) if n else 0.0

        ci_d_our = compute_bootstrap_ci(d_ours)
        ci_d_margin = compute_bootstrap_ci(d_margins)

        o1_win_rate = sum(1 for r in paired_records if r["o1_won"]) / max(1, n)
        o0_win_rate = sum(1 for r in paired_records if r["o0_won"]) / max(1, n)
        win_rate_delta = o1_win_rate - o0_win_rate

        # Statistical significance
        p_val_our = 1.0
        p_val_margin = 1.0
        if n > 1:
            try:
                _, p_val_our = stats.ttest_rel([r["o1_our"] for r in paired_records], [r["o0_our"] for r in paired_records])
                _, p_val_margin = stats.ttest_rel([r["o1_margin"] for r in paired_records], [r["o0_margin"] for r in paired_records])
            except Exception:
                pass

        # Classification
        if mean_d_our > 0 and mean_d_opp <= 0:
            classification = "self-profit gain + opponent suppression"
        elif mean_d_our > 0 and mean_d_opp > 0:
            classification = "self-profit gain"
        elif mean_d_our <= 0 and mean_d_opp < 0:
            classification = "opponent suppression"
        elif mean_d_our <= 0 and mean_d_opp >= 0:
            classification = "harmful / negative"
        else:
            classification = "neutral"

        overall_report[opp] = {
            "n_matches": n,
            "o1_mean_our_score": float(np.mean(o1_ours)),
            "o0_mean_our_score": float(np.mean(o0_ours)),
            "mean_delta_our": mean_d_our,
            "median_delta_our": median_d_our,
            "bootstrap_ci_delta_our_95": ci_d_our,
            "p_value_our": float(p_val_our),
            "o1_mean_opp_score": float(np.mean(o1_opps)),
            "o0_mean_opp_score": float(np.mean(o0_opps)),
            "mean_delta_opp": mean_d_opp,
            "median_delta_opp": median_d_opp,
            "mean_delta_margin": mean_d_margin,
            "median_delta_margin": median_d_margin,
            "bootstrap_ci_delta_margin_95": ci_d_margin,
            "p_value_margin": float(p_val_margin),
            "o1_win_rate": o1_win_rate,
            "o0_win_rate": o0_win_rate,
            "win_rate_delta": win_rate_delta,
            "classification": classification,
            "paired_records": paired_records,
        }

    out_dir = os.path.join(PROJECT_ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "o0_vs_o1_tournament_report.json")
    with open(out_file, "w") as f:
        json.dump(overall_report, f, indent=2)

    print(f"\n=== O0 vs O1 Tournament Completed ===")
    print(f"Results saved to: {out_file}")
    for opp, rep in overall_report.items():
        print(f"\n--- Opponent: {opp} ({rep['n_matches']} paired matches) ---")
        print(f"  Our Score: O1 = ${rep['o1_mean_our_score']:.1f} vs O0 = ${rep['o0_mean_our_score']:.1f} (Delta: ${rep['mean_delta_our']:+.1f}, p={rep['p_value_our']:.4f})")
        print(f"  Opp Score: O1 = ${rep['o1_mean_opp_score']:.1f} vs O0 = ${rep['o0_mean_opp_score']:.1f} (Delta: ${rep['mean_delta_opp']:+.1f})")
        print(f"  Margin: Delta = ${rep['mean_delta_margin']:+.1f} (CI: [{rep['bootstrap_ci_delta_margin_95'][0]:.1f}, {rep['bootstrap_ci_delta_margin_95'][1]:.1f}])")
        print(f"  Win Rate: O1 = {rep['o1_win_rate']*100:.1f}% vs O0 = {rep['o0_win_rate']*100:.1f}% (Delta: {rep['win_rate_delta']*100:+.1f}%)")
        print(f"  Classification: {rep['classification']}")

    return overall_report


if __name__ == "__main__":
    # Screen across 15 paired seeds (30 matches per archetype = 90 matches total)
    seeds = list(range(100, 115))
    run_o0_vs_o1_tournament(seeds=seeds, max_workers=6)
