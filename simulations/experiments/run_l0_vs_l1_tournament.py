"""Rigorous L0 vs L1 Paired, Seat-Swapped Tournament.

Compares:
  L0: Unconstrained livestock valuation baseline (ignores opponent livestock commitments).
  L1: Commitment-aware livestock valuation (derives future supply scenarios from visible opponent animals).

Both arms run with OPPONENT_INTELLIGENCE_MODE = "O0_SHADOW" so that behavioral prediction
remains disabled, isolating the livestock valuation mechanism.

Opponents:
  - full_production_agent (balanced mixed strategy)
  - cow_milk_engine (livestock-heavy opponent producing lots of Milk)
  - melon_sniper (crop-heavy, dump-heavy)

Measures:
  - Delta our score
  - Delta opponent score
  - Delta score margin
  - Win rate change
  - 95% paired bootstrap CI
  - Purchase counts by species (COW, SHEEP, GOOSE)
  - Purchase timing (first purchase day, last purchase day)
  - Revenue, feed cost, starvation/deaths
  - Recommendation: promote, revise, or reject
"""

import os
import sys
import time
import json
import argparse
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
    seed: int = 42,
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
    mode = payload["mode"]          # "L0" or "L1"
    seed = payload["seed"]
    opponent_name = payload["opponent_name"]
    seat = payload["seat"]          # 0 (our agent is P0) or 1 (our agent is P1)

    # Clean module cache for deterministic clean state
    to_delete = [k for k in list(sys.modules.keys()) if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'marginal_livestock_valuator',
        'herd_planner'
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

    # Base configuration: O0_SHADOW (no behavioral prediction), ArmA (no SW)
    config.set_sw_experiment_arm("ArmA")
    config.set_opponent_intelligence_mode("O0_SHADOW")
    config.set_livestock_valuation_mode(mode)

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

    # Telemetry extraction: purchases, timing, animals, feed
    animal_purchases = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    purchase_days = []
    wheat_bought = 0
    wheat_spent_cost = 0.0

    for step_data in steps:
        action = step_data[our_idx].get("action")
        if not action or not isinstance(action, dict):
            continue
        market_orders = action.get("market", [])
        obs = step_data[our_idx].get("observation", {})
        day = obs.get("day", 0)

        for order in market_orders:
            if not isinstance(order, (list, tuple)) or len(order) < 2:
                continue
            if order[0] == "BUY_ANIMAL":
                sp = str(order[1]).upper()
                if sp in animal_purchases:
                    animal_purchases[sp] += 1
                    purchase_days.append(day)
            elif order[0] == "BUY_PRODUCT" and order[1] == "WHEAT":
                qty = order[2] if len(order) > 2 else 1
                wheat_bought += qty

    # Final farm animal counts
    final_obs = steps[-1][our_idx].get("observation", {})
    farms = final_obs.get("farms", [])
    our_farm = farms[our_idx] if len(farms) > our_idx else {}
    tiles = our_farm.get("tiles", [])

    final_animals = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
    if isinstance(tiles, list):
        for row in tiles:
            if isinstance(row, list):
                for t in row:
                    if isinstance(t, dict) and "animal" in t:
                        sp = str(t["animal"]).upper()
                        if sp in final_animals:
                            final_animals[sp] += 1

    first_purchase_day = min(purchase_days) if purchase_days else None
    last_purchase_day = max(purchase_days) if purchase_days else None

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
        "animal_purchases": animal_purchases,
        "final_animals": final_animals,
        "purchase_days": purchase_days,
        "first_purchase_day": first_purchase_day,
        "last_purchase_day": last_purchase_day,
        "wheat_bought": wheat_bought,
    }


def run_l0_vs_l1_tournament(
    seeds: List[int],
    opponents: List[str] = ["full_production_agent", "cow_milk_engine", "melon_sniper"],
    max_workers: int = 4,
) -> Dict[str, Any]:
    print(f"=== Starting L0 vs L1 Paired Tournament ===")
    print(f"Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]}) | Opponents: {opponents} | Seat-swapped: Yes")

    tasks = []
    for opp in opponents:
        for s in seeds:
            for seat in (0, 1):
                tasks.append({"mode": "L1", "seed": s, "opponent_name": opp, "seat": seat})
                tasks.append({"mode": "L0", "seed": s, "opponent_name": opp, "seat": seat})

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

    # Aggregations
    overall_paired = []
    by_opponent_report = {}

    for opp in opponents:
        paired_records = []
        for s in seeds:
            for seat in (0, 1):
                r_l1 = results_map.get((opp, s, seat, "L1"))
                r_l0 = results_map.get((opp, s, seat, "L0"))
                if r_l1 and r_l0:
                    d_our = r_l1["our_score"] - r_l0["our_score"]
                    d_opp = r_l1["opp_score"] - r_l0["opp_score"]
                    d_margin = r_l1["margin"] - r_l0["margin"]
                    rec = {
                        "seed": s,
                        "seat": seat,
                        "l1_our": r_l1["our_score"],
                        "l0_our": r_l0["our_score"],
                        "d_our": d_our,
                        "l1_opp": r_l1["opp_score"],
                        "l0_opp": r_l0["opp_score"],
                        "d_opp": d_opp,
                        "l1_margin": r_l1["margin"],
                        "l0_margin": r_l0["margin"],
                        "d_margin": d_margin,
                        "l1_won": r_l1["we_won"],
                        "l0_won": r_l0["we_won"],
                        "l1_tie": r_l1["is_tie"],
                        "l0_tie": r_l0["is_tie"],
                        "l1_purchases": r_l1["animal_purchases"],
                        "l0_purchases": r_l0["animal_purchases"],
                        "l1_final_animals": r_l1["final_animals"],
                        "l0_final_animals": r_l0["final_animals"],
                        "l1_first_day": r_l1["first_purchase_day"],
                        "l0_first_day": r_l0["first_purchase_day"],
                        "l1_wheat_bought": r_l1["wheat_bought"],
                        "l0_wheat_bought": r_l0["wheat_bought"],
                    }
                    paired_records.append(rec)
                    overall_paired.append(rec)

        n = len(paired_records)
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

        l1_wins = sum(1 for r in paired_records if r["l1_won"])
        l0_wins = sum(1 for r in paired_records if r["l0_won"])
        l1_ties = sum(1 for r in paired_records if r["l1_tie"])
        l0_ties = sum(1 for r in paired_records if r["l0_tie"])
        l1_losses = n - l1_wins - l1_ties
        l0_losses = n - l0_wins - l0_ties

        l1_win_rate = l1_wins / max(1, n)
        l0_win_rate = l0_wins / max(1, n)
        win_rate_delta = l1_win_rate - l0_win_rate

        p_val_our = 1.0
        p_val_margin = 1.0
        if n > 1 and np.std(d_ours) > 0:
            try:
                p_val_our = float(stats.ttest_1samp(d_ours, 0.0).pvalue)
            except Exception:
                pass
        if n > 1 and np.std(d_margins) > 0:
            try:
                p_val_margin = float(stats.ttest_1samp(d_margins, 0.0).pvalue)
            except Exception:
                pass

        # Purchase statistics
        l1_cows = [r["l1_purchases"]["COW"] for r in paired_records]
        l0_cows = [r["l0_purchases"]["COW"] for r in paired_records]
        l1_sheep = [r["l1_purchases"]["SHEEP"] for r in paired_records]
        l0_sheep = [r["l0_purchases"]["SHEEP"] for r in paired_records]
        l1_geese = [r["l1_purchases"]["GOOSE"] for r in paired_records]
        l0_geese = [r["l0_purchases"]["GOOSE"] for r in paired_records]

        by_opponent_report[opp] = {
            "n_pairs": n,
            "l1_mean_score": float(np.mean([r["l1_our"] for r in paired_records])) if n else 0.0,
            "l0_mean_score": float(np.mean([r["l0_our"] for r in paired_records])) if n else 0.0,
            "mean_delta_our": mean_d_our,
            "median_delta_our": median_d_our,
            "ci_95_delta_our": ci_d_our,
            "p_val_delta_our": p_val_our,
            "mean_delta_opp": mean_d_opp,
            "median_delta_opp": median_d_opp,
            "mean_delta_margin": mean_d_margin,
            "median_delta_margin": median_d_margin,
            "ci_95_delta_margin": ci_d_margin,
            "p_val_delta_margin": p_val_margin,
            "l1_record": {"wins": l1_wins, "ties": l1_ties, "losses": l1_losses, "win_rate": l1_win_rate},
            "l0_record": {"wins": l0_wins, "ties": l0_ties, "losses": l0_losses, "win_rate": l0_win_rate},
            "win_rate_delta": win_rate_delta,
            "avg_purchases": {
                "l1": {"COW": float(np.mean(l1_cows)), "SHEEP": float(np.mean(l1_sheep)), "GOOSE": float(np.mean(l1_geese))},
                "l0": {"COW": float(np.mean(l0_cows)), "SHEEP": float(np.mean(l0_sheep)), "GOOSE": float(np.mean(l0_geese))},
                "delta": {
                    "COW": float(np.mean(l1_cows) - np.mean(l0_cows)),
                    "SHEEP": float(np.mean(l1_sheep) - np.mean(l0_sheep)),
                    "GOOSE": float(np.mean(l1_geese) - np.mean(l0_geese)),
                }
            },
            "paired_records": paired_records,
        }

    # Overall summary
    tot_n = len(overall_paired)
    all_d_ours = [r["d_our"] for r in overall_paired]
    all_d_opps = [r["d_opp"] for r in overall_paired]
    all_d_margins = [r["d_margin"] for r in overall_paired]

    tot_mean_d_our = float(np.mean(all_d_ours)) if tot_n else 0.0
    tot_median_d_our = float(np.median(all_d_ours)) if tot_n else 0.0
    tot_ci_our = compute_bootstrap_ci(all_d_ours)
    tot_mean_d_opp = float(np.mean(all_d_opps)) if tot_n else 0.0
    tot_mean_d_margin = float(np.mean(all_d_margins)) if tot_n else 0.0
    tot_median_d_margin = float(np.median(all_d_margins)) if tot_n else 0.0
    tot_ci_margin = compute_bootstrap_ci(all_d_margins)

    tot_l1_wins = sum(1 for r in overall_paired if r["l1_won"])
    tot_l0_wins = sum(1 for r in overall_paired if r["l0_won"])
    tot_l1_ties = sum(1 for r in overall_paired if r["l1_tie"])
    tot_l0_ties = sum(1 for r in overall_paired if r["l0_tie"])
    tot_l1_losses = tot_n - tot_l1_wins - tot_l1_ties
    tot_l0_losses = tot_n - tot_l0_wins - tot_l0_ties

    tot_p_our = 1.0
    tot_p_margin = 1.0
    if tot_n > 1 and np.std(all_d_ours) > 0:
        try:
            tot_p_our = float(stats.ttest_1samp(all_d_ours, 0.0).pvalue)
        except Exception:
            pass
    if tot_n > 1 and np.std(all_d_margins) > 0:
        try:
            tot_p_margin = float(stats.ttest_1samp(all_d_margins, 0.0).pvalue)
        except Exception:
            pass

    overall_report = {
        "seeds": seeds,
        "opponents": opponents,
        "total_pairs": tot_n,
        "mean_delta_our": tot_mean_d_our,
        "median_delta_our": tot_median_d_our,
        "ci_95_delta_our": tot_ci_our,
        "p_val_delta_our": tot_p_our,
        "mean_delta_opp": tot_mean_d_opp,
        "mean_delta_margin": tot_mean_d_margin,
        "median_delta_margin": tot_median_d_margin,
        "ci_95_delta_margin": tot_ci_margin,
        "p_val_delta_margin": tot_p_margin,
        "l1_record": {"wins": tot_l1_wins, "ties": tot_l1_ties, "losses": tot_l1_losses, "win_rate": tot_l1_wins / max(1, tot_n)},
        "l0_record": {"wins": tot_l0_wins, "ties": tot_l0_ties, "losses": tot_l0_losses, "win_rate": tot_l0_wins / max(1, tot_n)},
        "win_rate_delta": (tot_l1_wins - tot_l0_wins) / max(1, tot_n),
        "by_opponent": by_opponent_report,
    }

    # Recommendation
    if tot_ci_margin[0] > 0 and tot_mean_d_margin > 0 and (tot_l1_wins >= tot_l0_wins):
        recommendation = "PROMOTE: L1 produces statistically superior margins without regressions."
    elif tot_ci_margin[1] < 0 or tot_mean_d_our < -500:
        recommendation = "REJECT: L1 causes significant margin/score deterioration."
    elif tot_mean_d_margin >= 0 and abs(tot_mean_d_our) < 500:
        recommendation = "NEUTRAL/MARGINAL: L1 is safe and slightly positive/neutral. Further scenario tuning or keeping as safe default option."
    else:
        recommendation = "REVISE: Mixed outcomes across opponents."
    overall_report["recommendation"] = recommendation

    print("\n" + "=" * 80)
    print("=== FINAL L0 vs L1 TOURNAMENT RESULTS ===")
    print("=" * 80)
    print(f"{'Opponent':<22} | {'Pairs':<5} | {'Mean dOur':<10} | {'95% CI dOur':<20} | {'Mean dMargin':<12} | {'dWinRate':<8}")
    print("-" * 80)
    for opp, rep in by_opponent_report.items():
        print(f"{opp:<22} | {rep['n_pairs']:<5} | ${rep['mean_delta_our']:<9.1f} | [${rep['ci_95_delta_our'][0]:.1f}, ${rep['ci_95_delta_our'][1]:.1f}] | ${rep['mean_delta_margin']:<11.1f} | {rep['win_rate_delta']:>+7.1%}")
    print("-" * 80)
    print(f"{'OVERALL':<22} | {tot_n:<5} | ${tot_mean_d_our:<9.1f} | [${tot_ci_our[0]:.1f}, ${tot_ci_our[1]:.1f}] | ${tot_mean_d_margin:<11.1f} | {overall_report['win_rate_delta']:>+7.1%}")
    print("=" * 80)
    print(f"Recommendation: {recommendation}")

    # Save report
    out_dir = os.path.join(PROJECT_ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "l0_vs_l1_tournament_report.json")
    with open(out_path, "w") as f:
        json.dump(overall_report, f, indent=2)
    print(f"Report saved to: {out_path}")

    return overall_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run L0 vs L1 paired tournament")
    parser.add_argument("--num-seeds", type=int, default=10, help="Number of seeds to run")
    parser.add_argument("--start-seed", type=int, default=100, help="Starting seed")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel worker processes")
    args = parser.parse_args()

    seeds = list(range(args.start_seed, args.start_seed + args.num_seeds))
    run_l0_vs_l1_tournament(seeds=seeds, max_workers=args.workers)
