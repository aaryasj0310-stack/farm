"""Main entry point / CLI for the Monte Carlo town-shop simulation.

Usage:
    python run_simulation.py --simulations 10000 --scenarios all --output results/
    python run_simulation.py --simulations 1000 --scenarios town_only --output results/quick_test/
"""
import argparse
import os
import time

import numpy as np

import analysis_reporter as ar
import visualizations as viz
from monte_carlo_runner import BASELINE_PRODUCTION, MonteCarloRunner, TRADEABLE
from price_function import validate_known_points
from shop_unlock_simulator import ShopUnlockSimulator
from town_demand_engine import PRODUCT_INDEX as P_IDX
from town_demand_engine import PRODUCTS


def parse_args():
    ap = argparse.ArgumentParser(description="Kaggriculture town-shop Monte Carlo simulation")
    ap.add_argument("--simulations", type=int, default=10000)
    ap.add_argument("--scenarios", type=str, default="all",
                    choices=["all", "town_only", "single_player", "two_players", "sweep"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=str, default="results")
    ap.add_argument("--no-plots", action="store_true")
    return ap.parse_args()


def run_sweep(runner):
    """Scenario D, one level at a time to keep peak memory low."""
    levels = {}
    multipliers = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
    rng = np.random.default_rng(runner.seed + 1)
    draws = ShopUnlockSimulator().simulate_batch_indices(rng, runner.n_simulations)
    for m in multipliers:
        prod = {k: m * v for k, v in BASELINE_PRODUCTION.items()}
        res = runner.run(prod, f"sweep_{int(m*100)}pct", rng=rng, draws=draws)
        levels[f"{int(round(m * 100))}%"] = ar.sweep_level_stats(res)
        del res
        print(f"  sweep level {int(m*100)}% done")
    return levels


def answer_key_questions(town_res, single_res, summary, recs, sweep_levels):
    prices = single_res.prices
    answers = {}

    # Q1: P(carrot > $100 by day 15)
    carrot = prices[:, :16, P_IDX["CARROT"]]
    answers["Q1_carrot_over_100_by_day15"] = {
        "p_anytime_through_day_15": float((carrot > 100).any(axis=1).mean()),
        "p_on_day_15": float((prices[:, 15, P_IDX["CARROT"]] > 100).mean()),
    }

    # Q2: Pet Cafe first unlock response
    answers["Q2_pet_cafe_day3_response"] = summary["E_conditional_day3"]["responses"].get("PET_CAFE")

    # Q3: goose income over 20 days (days 4..23; 1 egg/day; feed $25/day;
    # purchase $300 amortized over a 30-day season)
    window = slice(4, 24)
    gross = prices[:, window, P_IDX["EGG"]].astype(np.float64).sum(axis=1)
    net = gross - 25.0 * 20 - 300.0 * (20 / 30)
    answers["Q3_goose_20day_net_income"] = {
        "median": float(np.median(net)), "p5": float(np.percentile(net, 5)),
        "p95": float(np.percentile(net, 95)), "assumptions": "1 egg/day from day 4; feed $25/day; goose $300 amortized",
    }

    # Q4: portfolio
    port = recs["optimal_portfolio"]
    answers["Q4_optimal_portfolio"] = {
        "low_risk": port["low_risk"],
        "high_risk_high_reward": port["high_risk_high_reward"],
    }

    # Q5: wheat glut threshold — first production level where the day-25
    # median price hits half of base or the floor becomes likely.
    q5 = None
    for level in sorted(sweep_levels, key=lambda s: int(s[:-1])):
        w = sweep_levels[level]["WHEAT"]
        if w["p_floor_day25"] >= 0.5 or w["median_price_day25"] <= 12:
            q5 = {"level": level, **w}
            break
    answers["Q5_wheat_unprofitable_level"] = q5 or "not reached within 0-200% baseline"

    # Q6: timing for premium goods (above_target > 1 => glut crashes them)
    answers["Q6_timing_premium_goods"] = {
        p: summary["timing_guidance"][p] for p in ("STRAWBERRY", "MELON", "MILK", "WOOL")
        if p in summary["timing_guidance"]
    }
    return answers


def main():
    args = parse_args()
    t_start = time.perf_counter()

    print("Step 1: validating price function against known points...")
    ok, _ = validate_known_points(verbose=False)
    if not ok:
        print("PRICE VALIDATION FAILED - aborting.")
        raise SystemExit(1)
    print("  all known price points pass.")

    plot_dir = os.path.join(args.output, "plots")
    os.makedirs(plot_dir, exist_ok=True)

    runner = MonteCarloRunner(n_simulations=args.simulations, seed=args.seed)
    rng = np.random.default_rng(args.seed)
    draws = ShopUnlockSimulator().simulate_batch_indices(rng, runner.n_simulations)

    want_all = args.scenarios == "all"
    town_res = single_res = two_res = None
    sweep_levels = {}

    if want_all or args.scenarios == "town_only":
        print(f"Step 2: scenario A (town-only drain), n={args.simulations}...")
        town_res = runner.run_town_only(rng=rng, draws=draws)
    if want_all or args.scenarios == "single_player":
        print("Step 3: scenario B (single competitive player)...")
        single_res = runner.run(dict(BASELINE_PRODUCTION), "single_player", rng=rng, draws=draws)
    if want_all or args.scenarios == "two_players":
        print("Step 4: scenario C (two competitive players)...")
        prod = {k: 2 * v for k, v in BASELINE_PRODUCTION.items()}
        two_res = runner.run(prod, "two_players", rng=rng, draws=draws)
    if want_all or args.scenarios == "sweep":
        print("Step 5: scenario D (production sweep 0-200%)...")
        sweep_levels = run_sweep(runner)

    if town_res is None:
        print("No scenario produced results (choose --scenarios all).")
        raise SystemExit(1)

    print("Step 6: analysis + outputs...")
    if single_res is None:
        single_res = town_res
    if two_res is None:
        two_res = single_res

    summary = ar.generate_summary(town_res, single_res, two_res, sweep_levels)
    recs = ar.build_strategy_recommendations(summary, single_res)

    ar.save_json(os.path.join(args.output, "summary_stats.json"), summary)
    ar.save_json(os.path.join(args.output, "strategy_recommendations.json"), recs)

    scenarios_for_csv = {r.name: r for r in (town_res, single_res, two_res)}
    ar.write_price_trajectories_csv(
        os.path.join(args.output, "price_trajectories.csv"), scenarios_for_csv)
    ar.write_demand_distributions_csv(
        os.path.join(args.output, "demand_distributions.csv"), town_res)

    if not args.no_plots:
        print("Step 7: rendering plots...")
        viz.price_fan_charts(town_res, plot_dir)
        viz.demand_heatmap(town_res, plot_dir)
        viz.hinge_trigger_probability(summary["D_hinge_analysis"], plot_dir)
        viz.product_roi_scatter(single_res, plot_dir)
        viz.shop_combination_impact(plot_dir)

        port = recs["optimal_portfolio"]
        mixed_crops = port["low_risk"]["crops"]
        layouts = [
            ("All-Wheat (25 tiles)", {"WHEAT": 25}, {}),
            ("All-Carrot (25 tiles)", {"CARROT": 25}, {}),
            ("Mixed optimal", dict(mixed_crops), {"goose": 2}),
            ("Animal-focused", {"WHEAT": 5}, {"goose": 3, "cow": 2, "sheep": 2}),
        ]
        viz.cumulative_revenue_comparison(single_res, layouts, plot_dir)

    answers = answer_key_questions(town_res, single_res, summary, recs, sweep_levels)
    ar.save_json(os.path.join(args.output, "key_questions.json"), answers)

    elapsed = time.perf_counter() - t_start
    print(f"\nDone in {elapsed:.1f}s. Outputs written to {os.path.abspath(args.output)}")
    print("\n=== KEY QUESTION ANSWERS ===")
    for k, v in answers.items():
        print(f"\n{k}:")
        if isinstance(v, dict):
            for kk, vv in v.items():
                print(f"  {kk}: {vv}")
        else:
            print(f"  {v}")


if __name__ == "__main__":
    main()
