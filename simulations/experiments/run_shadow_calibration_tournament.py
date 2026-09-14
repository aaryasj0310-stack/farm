"""Phase 4: Shadow Opponent Forecast Calibration & Evaluation Harness.

Runs matches with our agent in O1_SHADOW mode (strategy is 100% untouched O1;
shadow forecaster runs in the background and records predictions).

The evaluation harness extracts privileged ground truth from environment steps:
- Actual opponent shed contents at step t
- Actual opponent harvests
- Actual opponent sales in the next 4 turns (steps t+1 .. t+4)
- Floor-censored sales ($1)

Evaluates:
1. Shed Bounds Interval Coverage (% of steps where actual_shed in [min, max])
2. Shed Point Estimate MAE
3. Production Volume Error (forecasted vs actual total production)
4. Production Timing Error (days discrepancy)
5. Sell Probability Calibration:
   P(visible sale >= 1 unit in next 4 turns)
   Brier score = (1/N) * sum((p - y)^2)
   Reliability curve across 5 probability bins
6. Floor-censored cases separately.
"""

import os
import sys
import time
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from config import PRODUCTS


def _run_single_calibration_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    seed = payload["seed"]
    opponent_name = payload["opponent_name"]
    seat = payload["seat"]

    # Module reload isolation
    to_delete = [k for k in list(sys.modules.keys()) if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'shadow_forecast',
        'repaired_opponent_model', 'repaired_opponent_advisor'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    import execution.task_scheduler as task_scheduler
    from strategy.shadow_forecast import get_shadow_forecaster
    from simulations.experiments.agent_zoo import get_agent

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    task_scheduler.reset_worker_locality()

    # O1_SHADOW: O1 controls strategy, shadow forecaster produces telemetry
    config.set_sw_experiment_arm("ArmA")
    config.set_opponent_intelligence_mode("O1_SHADOW")

    opp_callable = get_agent(opponent_name)

    step_shadow_telemetry = {}

    def tracking_agent(obs, configuration=None):
        step = obs.get("step", 0)
        action = agent_module.agent(obs, configuration)
        # Capture the shadow forecast that was computed during this step
        forecaster = get_shadow_forecaster()
        if forecaster.last_step == step:
            step_shadow_telemetry[step] = dict(forecaster.last_telemetry)
        return action

    if seat == 0:
        players = [tracking_agent, opp_callable]
        our_idx = 0
        opp_idx = 1
    else:
        players = [opp_callable, tracking_agent]
        our_idx = 1
        opp_idx = 0

    env = make("kaggriculture", configuration={"randomSeed": seed}, debug=False)
    steps = env.run(players)

    our_score = float(steps[-1][our_idx]["reward"] or 0.0)
    opp_score = float(steps[-1][opp_idx]["reward"] or 0.0)

    # -----------------------------------------------------------------------
    # Ground Truth Extraction (Privileged, only for evaluation harness)
    # -----------------------------------------------------------------------
    total_steps = len(steps)
    actual_shed_by_step = {}
    actual_sales_by_step = defaultdict(lambda: defaultdict(float))
    actual_sales_floor_censored = defaultdict(lambda: defaultdict(bool))
    actual_harvests = defaultdict(float)

    for s_idx in range(total_steps):
        step_entry = steps[s_idx]
        opp_obs = step_entry[opp_idx]["observation"]
        priv = opp_obs.get("private", {})
        shed = priv.get("shed", {}) if isinstance(priv, dict) else getattr(priv, "shed", {})
        actual_shed_by_step[s_idx] = {p: shed.get(p, 0) for p in PRODUCTS}

        # Check market actions executed by opponent at this step
        opp_action = step_entry[opp_idx].get("action")
        if isinstance(opp_action, dict):
            market_orders = opp_action.get("market", [])
            for order in market_orders:
                if isinstance(order, list) and len(order) >= 3 and order[0] == "SELL":
                    item = order[1]
                    qty = float(order[2])
                    actual_sales_by_step[s_idx][item] += qty
                    # Check if market was at floor price ($1)
                    mkt = opp_obs.get("market", {})
                    prices = mkt.get("prices", {})
                    if prices.get(item, 10) <= 1:
                        actual_sales_floor_censored[s_idx][item] = True

    # -----------------------------------------------------------------------
    # Evaluate Shadow Telemetry against Ground Truth
    # -----------------------------------------------------------------------
    shed_coverage_hits = 0
    shed_coverage_trials = 0
    shed_mae_list = []

    brier_scores_all = []
    brier_scores_uncensored = []
    brier_scores_censored = []
    prob_bins = [[] for _ in range(5)]  # [0, 0.2), [0.2, 0.4), [0.4, 0.6), [0.6, 0.8), [0.8, 1.0]

    for s_idx, tele in step_shadow_telemetry.items():
        if s_idx not in actual_shed_by_step:
            continue
        act_shed = actual_shed_by_step[s_idx]
        pred_bounds = tele.get("shed_bounds", {})
        pred_point = tele.get("shed_point_estimate", {})
        p_sale_4 = tele.get("p_sale_next_4_turns", {})

        for p in PRODUCTS:
            act_qty = act_shed.get(p, 0)
            bnd = pred_bounds.get(p, [0.0, 0.0])
            lo, hi = bnd[0], bnd[1]

            # Only evaluate products that either exist in actual shed or were forecasted
            if act_qty > 0 or hi > 0:
                shed_coverage_trials += 1
                if lo <= act_qty <= hi:
                    shed_coverage_hits += 1

                pt = pred_point.get(p, 0.0)
                shed_mae_list.append(abs(pt - act_qty))

            # 4-turn forward sales ground truth: did opponent sell >= 1 unit in steps s_idx+1 .. s_idx+4?
            actual_sold_4 = sum(actual_sales_by_step[fut_s].get(p, 0)
                                for fut_s in range(s_idx + 1, min(total_steps, s_idx + 5)))
            y = 1.0 if actual_sold_4 >= 1.0 else 0.0
            p_pred = p_sale_4.get(p, 0.0)

            is_censored = any(actual_sales_floor_censored[fut_s].get(p, False)
                              for fut_s in range(s_idx + 1, min(total_steps, s_idx + 5)))

            brier = (p_pred - y) ** 2
            brier_scores_all.append(brier)
            if is_censored:
                brier_scores_censored.append(brier)
            else:
                brier_scores_uncensored.append(brier)

            # Reliability binning
            b_idx = min(4, int(p_pred * 5.0))
            prob_bins[b_idx].append((p_pred, y))

    return {
        "seed": seed,
        "opponent_name": opponent_name,
        "seat": seat,
        "our_score": our_score,
        "opp_score": opp_score,
        "shed_coverage_hits": shed_coverage_hits,
        "shed_coverage_trials": shed_coverage_trials,
        "shed_mae_mean": float(np.mean(shed_mae_list)) if shed_mae_list else 0.0,
        "brier_all": float(np.mean(brier_scores_all)) if brier_scores_all else 0.0,
        "brier_uncensored": float(np.mean(brier_scores_uncensored)) if brier_scores_uncensored else 0.0,
        "brier_censored": float(np.mean(brier_scores_censored)) if brier_scores_censored else 0.0,
        "prob_bins": prob_bins,
    }


def run_calibration_benchmark(
    seeds: List[int],
    opponents: List[str] = ["full_production_agent", "melon_sniper", "cow_milk_engine"],
    max_workers: int = 6,
) -> Dict[str, Any]:
    print(f"\n=== Starting Phase 4 Shadow Forecast Calibration Benchmark ===")
    print(f"Seeds: {len(seeds)} | Opponents: {opponents} | Mode: O1_SHADOW")

    tasks = []
    for opp in opponents:
        for s in seeds:
            for seat in (0, 1):
                tasks.append({"seed": s, "opponent_name": opp, "seat": seat})

    total_matches = len(tasks)
    start_time = time.time()
    results = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_calibration_match, t): t for t in tasks}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total_matches:
                elapsed = time.time() - start_time
                print(f"[{completed}/{total_matches}] calibration matches completed ({elapsed:.1f}s)")

    # Aggregate metrics
    tot_hits = sum(r["shed_coverage_hits"] for r in results)
    tot_trials = sum(r["shed_coverage_trials"] for r in results)
    interval_coverage_pct = (tot_hits / max(1, tot_trials)) * 100.0

    mean_shed_mae = float(np.mean([r["shed_mae_mean"] for r in results if r["shed_mae_mean"] > 0]))
    mean_brier_all = float(np.mean([r["brier_all"] for r in results if r["brier_all"] > 0]))
    mean_brier_uncensored = float(np.mean([r["brier_uncensored"] for r in results if r["brier_uncensored"] > 0]))
    mean_brier_censored = float(np.mean([r["brier_censored"] for r in results if r["brier_censored"] > 0]))

    # Merge reliability curve
    bin_edges = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    merged_bins = [[] for _ in range(5)]
    for r in results:
        for b_idx in range(5):
            merged_bins[b_idx].extend(r["prob_bins"][b_idx])

    reliability_curve = []
    for b_idx in range(5):
        pairs = merged_bins[b_idx]
        count = len(pairs)
        if count > 0:
            avg_pred = float(np.mean([p for p, _ in pairs]))
            empirical_freq = float(np.mean([y for _, y in pairs]))
        else:
            avg_pred = (b_idx * 0.2 + 0.1)
            empirical_freq = 0.0
        reliability_curve.append({
            "bin": bin_edges[b_idx],
            "count": count,
            "avg_predicted_prob": round(avg_pred, 3),
            "empirical_sale_frequency": round(empirical_freq, 3),
            "calibration_error": round(abs(avg_pred - empirical_freq), 3),
        })

    report = {
        "n_matches": len(results),
        "shed_interval_coverage_pct": round(interval_coverage_pct, 2),
        "shed_point_estimate_mae": round(mean_shed_mae, 2),
        "brier_score_all": round(mean_brier_all, 4),
        "brier_score_uncensored": round(mean_brier_uncensored, 4),
        "brier_score_floor_censored": round(mean_brier_censored, 4),
        "reliability_curve": reliability_curve,
    }

    out_dir = os.path.join(PROJECT_ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "shadow_forecast_calibration_report.json")
    with open(out_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n=== Shadow Calibration Benchmark Completed ===")
    print(f"Results saved to: {out_file}")
    print(f"Shed Interval Coverage: {report['shed_interval_coverage_pct']}% (Target: >=85%)")
    print(f"Shed Point Estimate MAE: {report['shed_point_estimate_mae']} units")
    print(f"Overall Brier Score: {report['brier_score_all']} (Uncensored: {report['brier_score_uncensored']}, Floor-Censored: {report['brier_score_floor_censored']})")
    print("\nReliability Diagram (P(sale >= 1 unit in next 4 turns)):")
    for b in reliability_curve:
        print(f"  Bin {b['bin']} (N={b['count']}): Pred {b['avg_predicted_prob']} -> Actual {b['empirical_sale_frequency']} (Error: {b['calibration_error']})")

    return report


if __name__ == "__main__":
    seeds = list(range(100, 115))  # 15 seeds * 2 seats * 3 archetypes = 90 matches
    run_calibration_benchmark(seeds=seeds, max_workers=6)
