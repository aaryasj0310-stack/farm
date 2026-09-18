"""
Statistical Analysis of the Point-2 200-Seed Out-of-Sample Production-Bundle Validation.

Computes comprehensive tables and metrics for:
  - Table 6: Aggregate Comparison (Arm S vs Arm C vs Arm D)
  - Section 7: Statistical Comparison Arm C vs Arm S (3C Bundle vs Shadow Baseline)
  - Section 8: Statistical Comparison Arm D vs Arm S (2C1S Bundle vs Shadow Baseline)
  - Section 9: Statistical Comparison Arm D vs Arm C (2C1S Bundle vs 3C Bundle)
  - Section 10: Opponent Archetype Breakdown (5 archetypes, N=40 each)
  - Section 11: Herd & Late-Housing Mechanism Invariant Analysis
  - Section 12: Feed, Wheat & Treasury Mechanics
  - Section 13: Land Expansion & Opportunity Cost Analysis
  - Section 14: Comprehensive Hard Safety Invariants Table
  - Section 15: Production Activation Gate Evaluation
  - Section 16: Composition Interaction Analysis & Strategic Synthesis
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Any, Dict, List, Tuple
import numpy as np
from scipy import stats

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS_PATH = os.path.join(
    ROOT_DIR, "simulations", "experiments", "results", "heldout_production_validation_results.json"
)


def load_results() -> Dict[str, Any]:
    if not os.path.exists(RESULTS_PATH):
        raise FileNotFoundError(f"Results file not found: {RESULTS_PATH}")
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_distribution_stats(vals: List[float]) -> Dict[str, float]:
    arr = np.array(vals, dtype=float)
    n = len(arr)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 0 else 0.0
    median = float(np.median(arr))
    p10 = float(np.percentile(arr, 10))
    p25 = float(np.percentile(arr, 25))
    p75 = float(np.percentile(arr, 75))
    p90 = float(np.percentile(arr, 90))
    min_v = float(np.min(arr))
    max_v = float(np.max(arr))
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "se": se,
        "median": median,
        "p10": p10,
        "p25": p25,
        "p75": p75,
        "p90": p90,
        "min": min_v,
        "max": max_v,
    }


def compute_paired_comparison(vals_a: List[float], vals_b: List[float], name_a: str, name_b: str) -> Dict[str, Any]:
    arr_a = np.array(vals_a, dtype=float)
    arr_b = np.array(vals_b, dtype=float)
    diffs = arr_a - arr_b
    n = len(diffs)

    stats_diff = compute_distribution_stats(diffs.tolist())
    mean_diff = stats_diff["mean"]
    std_diff = stats_diff["std"]
    se_diff = stats_diff["se"]

    # 95% Confidence Interval using t-distribution
    t_crit = stats.t.ppf(0.975, df=n - 1) if n > 1 else 1.96
    ci_lower = mean_diff - t_crit * se_diff
    ci_upper = mean_diff + t_crit * se_diff

    # Paired Student's t-test
    t_res = stats.ttest_rel(arr_a, arr_b)
    t_stat = float(t_res.statistic)
    t_pval = float(t_res.pvalue)

    # Wilcoxon signed-rank test
    # Filter out exact ties for scipy wilcoxon
    non_zero = diffs[diffs != 0]
    if len(non_zero) > 0:
        w_res = stats.wilcoxon(diffs, zero_method="wilcox")
        w_stat = float(w_res.statistic)
        w_pval = float(w_res.pvalue)
    else:
        w_stat = 0.0
        w_pval = 1.0

    wins = int(np.sum(diffs > 0))
    losses = int(np.sum(diffs < 0))
    ties = int(np.sum(diffs == 0))
    win_rate = (wins / n) * 100.0 if n > 0 else 0.0

    return {
        "name_a": name_a,
        "name_b": name_b,
        "n": n,
        "mean_a": float(np.mean(arr_a)),
        "mean_b": float(np.mean(arr_b)),
        "mean_delta": mean_diff,
        "std_delta": std_diff,
        "se_delta": se_diff,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "t_statistic": t_stat,
        "t_pvalue": t_pval,
        "wilcoxon_stat": w_stat,
        "wilcoxon_pvalue": w_pval,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": win_rate,
        "median_delta": stats_diff["median"],
        "p10_delta": stats_diff["p10"],
        "p25_delta": stats_diff["p25"],
        "p75_delta": stats_diff["p75"],
        "p90_delta": stats_diff["p90"],
        "min_delta": stats_diff["min"],
        "max_delta": stats_diff["max"],
    }


def analyze_validation():
    data = load_results()
    results = data["results"]
    n = len(results)
    print(f"Loaded {n} seed results ({n * 3} matches). Manifest SHA256: {data['manifest_sha256']}")

    scores_s = [r["arm_s"]["final_score"] for r in results]
    scores_c = [r["arm_c"]["final_score"] for r in results]
    scores_d = [r["arm_d"]["final_score"] for r in results]

    # 1. Distribution Stats
    stats_s = compute_distribution_stats(scores_s)
    stats_c = compute_distribution_stats(scores_c)
    stats_d = compute_distribution_stats(scores_d)

    # 2. Revenue & Cost Breakdowns
    def get_financials(arm_key: str):
        crop = [r[arm_key]["crop_revenue"] for r in results]
        milk = [r[arm_key]["milk_revenue"] for r in results]
        wool = [r[arm_key]["wool_revenue"] for r in results]
        fert = [r[arm_key]["fertilizer_revenue"] for r in results]
        wheat_sold = [r[arm_key]["wheat_sold_revenue"] for r in results]
        anim_spend = [r[arm_key]["animal_purchase_cost"] for r in results]
        feed_spend = [r[arm_key]["feed_purchase_cost"] for r in results]
        net_livestock = [r[arm_key]["net_livestock_profit"] for r in results]
        wheat_bought = [r[arm_key]["wheat_bought_units"] for r in results]
        feed_consumed = [r[arm_key]["total_feed_consumed"] for r in results]
        day0_cash = [r[arm_key]["day0_cash_deployment"] for r in results]
        min_slack = [r[arm_key]["min_wheat_slack"] for r in results]
        return {
            "crop_rev": float(np.mean(crop)),
            "milk_rev": float(np.mean(milk)),
            "wool_rev": float(np.mean(wool)),
            "fert_rev": float(np.mean(fert)),
            "wheat_sold_rev": float(np.mean(wheat_sold)),
            "animal_spend": float(np.mean(anim_spend)),
            "feed_spend": float(np.mean(feed_spend)),
            "net_livestock": float(np.mean(net_livestock)),
            "wheat_bought": float(np.mean(wheat_bought)),
            "feed_consumed": float(np.mean(feed_consumed)),
            "day0_cash": float(np.mean(day0_cash)),
            "min_slack": float(np.min(min_slack)),
            "mean_min_slack": float(np.mean(min_slack)),
        }

    fin_s = get_financials("arm_s")
    fin_c = get_financials("arm_c")
    fin_d = get_financials("arm_d")

    # 3. Paired Comparisons
    comp_c_vs_s = compute_paired_comparison(scores_c, scores_s, "Arm C (3C Bundle)", "Arm S (Shadow Baseline)")
    comp_d_vs_s = compute_paired_comparison(scores_d, scores_s, "Arm D (2C1S Bundle)", "Arm S (Shadow Baseline)")
    comp_d_vs_c = compute_paired_comparison(scores_d, scores_c, "Arm D (2C1S Bundle)", "Arm C (3C Bundle)")

    # 4. Opponent Breakdown
    opponents = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
    opp_breakdown = {}
    for opp in opponents:
        sub_r = [r for r in results if r["opponent"] == opp]
        sub_s = [r["arm_s"]["final_score"] for r in sub_r]
        sub_c = [r["arm_c"]["final_score"] for r in sub_r]
        sub_d = [r["arm_d"]["final_score"] for r in sub_r]
        opp_breakdown[opp] = {
            "n": len(sub_r),
            "mean_s": float(np.mean(sub_s)),
            "mean_c": float(np.mean(sub_c)),
            "mean_d": float(np.mean(sub_d)),
            "c_vs_s": compute_paired_comparison(sub_c, sub_s, "C", "S"),
            "d_vs_s": compute_paired_comparison(sub_d, sub_s, "D", "S"),
            "d_vs_c": compute_paired_comparison(sub_d, sub_c, "D", "C"),
        }

    # 5. Herd & Late-Housing Continuation Metrics
    def get_herd_housing(arm_key: str):
        day0_admitted = [r[arm_key]["day0_admitted_count"] for r in results]
        max_placed = [r[arm_key]["max_placed_herd"] for r in results]
        max_owned = [r[arm_key]["max_total_owned_herd"] for r in results]
        final_placed = [r[arm_key]["final_placed_herd"] for r in results]
        final_owned = [r[arm_key]["final_total_owned_herd"] for r in results]
        pastures = [r[arm_key]["final_pasture_count"] for r in results]
        unused_past = [r[arm_key]["unused_pastures"] for r in results]
        stranded = [r[arm_key]["stranded_animals"] for r in results]

        cows = [r[arm_key]["final_herd_composition"].get("COW", 0) for r in results]
        sheep = [r[arm_key]["final_herd_composition"].get("SHEEP", 0) for r in results]
        geese = [r[arm_key]["final_herd_composition"].get("GOOSE", 0) for r in results]

        pre_d12 = [r[arm_key]["animals_bought_pre_d12"] for r in results]
        d12 = [r[arm_key]["animals_bought_d12"] for r in results]
        d13 = [r[arm_key]["animals_bought_d13"] for r in results]
        d14 = [r[arm_key]["animals_bought_d14"] for r in results]
        post_d14 = [r[arm_key]["animals_bought_post_d14"] for r in results]

        cont_req = [r[arm_key]["continuation_pasture_requests"] for r in results]
        cont_comp = [r[arm_key]["continuation_pasture_completions"] for r in results]
        cont_buy = [r[arm_key]["continuation_animal_purchases"] for r in results]
        post_d14_builds = [r[arm_key]["continuation_builds_initiated_post_d14"] for r in results]
        max_in_flight = [r[arm_key]["max_simultaneous_in_flight"] for r in results]

        return {
            "day0_admitted_mean": float(np.mean(day0_admitted)),
            "max_placed_mean": float(np.mean(max_placed)),
            "max_owned_mean": float(np.mean(max_owned)),
            "final_placed_mean": float(np.mean(final_placed)),
            "final_owned_mean": float(np.mean(final_owned)),
            "pastures_mean": float(np.mean(pastures)),
            "unused_pastures_total": int(np.sum(unused_past)),
            "unused_pastures_mean": float(np.mean(unused_past)),
            "stranded_animals_total": int(np.sum(stranded)),
            "stranded_animals_mean": float(np.mean(stranded)),
            "cow_mean": float(np.mean(cows)),
            "sheep_mean": float(np.mean(sheep)),
            "goose_mean": float(np.mean(geese)),
            "pre_d12_mean": float(np.mean(pre_d12)),
            "d12_mean": float(np.mean(d12)),
            "d13_mean": float(np.mean(d13)),
            "d14_mean": float(np.mean(d14)),
            "post_d14_mean": float(np.mean(post_d14)),
            "cont_req_total": int(np.sum(cont_req)),
            "cont_req_mean": float(np.mean(cont_req)),
            "cont_comp_total": int(np.sum(cont_comp)),
            "cont_comp_mean": float(np.mean(cont_comp)),
            "cont_buy_total": int(np.sum(cont_buy)),
            "cont_buy_mean": float(np.mean(cont_buy)),
            "post_d14_builds_total": int(np.sum(post_d14_builds)),
            "max_in_flight_max": int(np.max(max_in_flight)),
        }

    herd_s = get_herd_housing("arm_s")
    herd_c = get_herd_housing("arm_c")
    herd_d = get_herd_housing("arm_d")

    # 6. Land Unlock Analysis
    def get_land_stats(arm_key: str):
        ne_steps = []
        sw_steps = []
        for r in results:
            ne = r[arm_key]["ne_unlock_step"]
            if ne is not None:
                ne_steps.append(ne[0] * 24 + ne[1])
            sw = r[arm_key]["sw_unlock_step"]
            if sw is not None:
                sw_steps.append(sw[0] * 24 + sw[1])
        return {
            "ne_count": len(ne_steps),
            "ne_pct": (len(ne_steps) / n) * 100.0,
            "ne_mean_step": float(np.mean(ne_steps)) if ne_steps else None,
            "ne_mean_day": float(np.mean([s / 24.0 for s in ne_steps])) if ne_steps else None,
            "sw_count": len(sw_steps),
            "sw_pct": (len(sw_steps) / n) * 100.0,
            "sw_mean_step": float(np.mean(sw_steps)) if sw_steps else None,
            "sw_mean_day": float(np.mean([s / 24.0 for s in sw_steps])) if sw_steps else None,
        }

    land_s = get_land_stats("arm_s")
    land_c = get_land_stats("arm_c")
    land_d = get_land_stats("arm_d")

    # 7. Cash Progression at checkpoints
    def get_cash_checkpoints(arm_key: str):
        days = [1, 3, 5, 10, 12, 15, 20, 30]
        means = {}
        for d in days:
            vals = [r[arm_key]["cash_checkpoints"].get(str(d), r[arm_key]["cash_checkpoints"].get(d, 0.0)) for r in results]
            means[d] = float(np.mean(vals))
        return means

    cash_s = get_cash_checkpoints("arm_s")
    cash_c = get_cash_checkpoints("arm_c")
    cash_d = get_cash_checkpoints("arm_d")

    # 8. Hard Safety Invariants Table
    def get_safety_metrics(arm_key: str):
        neg_cash = sum(r[arm_key]["negative_cash_events"] for r in results)
        spec_buys = sum(r[arm_key]["speculative_animal_purchases"] for r in results)
        uncomp_buys = sum(r[arm_key]["purchases_into_uncompleted_pasture"] for r in results)
        max_flight = max(r[arm_key]["max_simultaneous_in_flight"] for r in results)
        post_d14_starts = sum(r[arm_key]["continuation_builds_initiated_post_d14"] for r in results)
        post_d14_buys = sum(r[arm_key]["animals_bought_post_d14"] for r in results)
        unused_past = sum(r[arm_key]["unused_pastures"] for r in results)
        escapes = sum(r[arm_key]["escapes"] for r in results)
        feed_shortage = sum(r[arm_key]["feed_shortage_deaths"] for r in results)
        c2c_viol = sum(r[arm_key]["c2c_dependency_violations"] for r in results)
        wheat_viol = sum(r[arm_key]["wheat_sale_reservation_violations"] for r in results)
        fallback_ev = sum(r[arm_key]["unsafe_livestock_fallback_events"] for r in results)
        return {
            "negative_cash_events": neg_cash,
            "speculative_animal_purchases": spec_buys,
            "purchases_into_uncompleted_pasture": uncomp_buys,
            "max_simultaneous_in_flight": max_flight,
            "continuation_builds_initiated_post_d14": post_d14_starts,
            "animals_bought_post_d14": post_d14_buys,
            "unused_pastures": unused_past,
            "escapes": escapes,
            "feed_shortage_deaths": feed_shortage,
            "c2c_dependency_violations": c2c_viol,
            "wheat_sale_reservation_violations": wheat_viol,
            "unsafe_livestock_fallback_events": fallback_ev,
        }

    safety_s = get_safety_metrics("arm_s")
    safety_c = get_safety_metrics("arm_c")
    safety_d = get_safety_metrics("arm_d")

    summary = {
        "manifest_sha256": data["manifest_sha256"],
        "n_seeds": n,
        "n_matches": n * 3,
        "stats": {"arm_s": stats_s, "arm_c": stats_c, "arm_d": stats_d},
        "financials": {"arm_s": fin_s, "arm_c": fin_c, "arm_d": fin_d},
        "paired": {
            "c_vs_s": comp_c_vs_s,
            "d_vs_s": comp_d_vs_s,
            "d_vs_c": comp_d_vs_c,
        },
        "opponents": opp_breakdown,
        "herd_housing": {"arm_s": herd_s, "arm_c": herd_c, "arm_d": herd_d},
        "land": {"arm_s": land_s, "arm_c": land_c, "arm_d": land_d},
        "cash_trajectory": {"arm_s": cash_s, "arm_c": cash_c, "arm_d": cash_d},
        "safety": {"arm_s": safety_s, "arm_c": safety_c, "arm_d": safety_d},
    }

    summary_path = os.path.join(
        ROOT_DIR, "simulations", "experiments", "results", "heldout_production_validation_summary.json"
    )
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print(" SUMMARY PREVIEW")
    print("=" * 80)
    print(f"Arm S Mean: ${stats_s['mean']:,.2f} (Median: ${stats_s['median']:,.2f})")
    print(f"Arm C Mean: ${stats_c['mean']:,.2f} (Median: ${stats_c['median']:,.2f})")
    print(f"Arm D Mean: ${stats_d['mean']:,.2f} (Median: ${stats_d['median']:,.2f})")
    print("-" * 80)
    print(f"Arm C vs Arm S: Δ = ${comp_c_vs_s['mean_delta']:+,.2f} (95% CI: [${comp_c_vs_s['ci_95_lower']:+,.2f}, ${comp_c_vs_s['ci_95_upper']:+,.2f}], W/L/T: {comp_c_vs_s['wins']}/{comp_c_vs_s['losses']}/{comp_c_vs_s['ties']}, p={comp_c_vs_s['t_pvalue']:.4e})")
    print(f"Arm D vs Arm S: Δ = ${comp_d_vs_s['mean_delta']:+,.2f} (95% CI: [${comp_d_vs_s['ci_95_lower']:+,.2f}, ${comp_d_vs_s['ci_95_upper']:+,.2f}], W/L/T: {comp_d_vs_s['wins']}/{comp_d_vs_s['losses']}/{comp_d_vs_s['ties']}, p={comp_d_vs_s['t_pvalue']:.4e})")
    print(f"Arm D vs Arm C: Δ = ${comp_d_vs_c['mean_delta']:+,.2f} (95% CI: [${comp_d_vs_c['ci_95_lower']:+,.2f}, ${comp_d_vs_c['ci_95_upper']:+,.2f}], W/L/T: {comp_d_vs_c['wins']}/{comp_d_vs_c['losses']}/{comp_d_vs_c['ties']}, p={comp_d_vs_c['t_pvalue']:.4e})")
    print("=" * 80)
    return summary


if __name__ == "__main__":
    analyze_validation()
