"""
Statistical Analysis of Point-2 Paired Arm C vs Arm D Controlled Experiment.

Computes:
  - Aggregate statistics: Mean C, Mean D, Mean D-C Delta, Median Delta, Paired Std, 95% CI
  - Win/Loss/Tie counts and win fraction
  - Revenue decomposition and spend breakdown
  - Checkpoint cash trajectory comparison
  - Opponent conditional breakdown (pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent)
  - Correlation analysis (wool rev, milk rev, crop rev, cash deployment, feed)
  - Safety & Invariant verification across all 200 matches
  - Full per-seed paired table
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS_FILE = os.path.join(ROOT_DIR, "simulations", "experiments", "results", "paired_c_vs_d_results.json")


def mean(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def stdev(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = mean(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def pearson_corr(x: List[float], y: List[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx = mean(x)
    my = mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den = math.sqrt(sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y))
    return num / den if den > 1e-9 else 0.0


def main():
    if not os.path.exists(RESULTS_FILE):
        print(f"Results file not found: {RESULTS_FILE}")
        return

    with open(RESULTS_FILE, "r") as f:
        data = json.load(f)

    n_seeds = len(data)
    print(f"Loaded {n_seeds} paired seeds ({n_seeds * 2} total matches).\n")

    scores_c = [d["arm_c"]["final_score"] for d in data]
    scores_d = [d["arm_d"]["final_score"] for d in data]
    deltas = [d["delta_d_minus_c"] for d in data]

    mean_c = mean(scores_c)
    std_c = stdev(scores_c)
    mean_d = mean(scores_d)
    std_d = stdev(scores_d)

    mean_delta = mean(deltas)
    med_delta = median(deltas)
    std_delta = stdev(deltas)
    se_delta = std_delta / math.sqrt(n_seeds)

    # 95% CI using t-value for n=100 (approx 1.984) or standard normal 1.960
    t_val = 1.984 if n_seeds >= 100 else 2.000
    ci_lower = mean_delta - t_val * se_delta
    ci_upper = mean_delta + t_val * se_delta

    wins_d = sum(1 for d in deltas if d > 0)
    wins_c = sum(1 for d in deltas if d < 0)
    ties = sum(1 for d in deltas if d == 0)
    frac_d = wins_d / n_seeds if n_seeds else 0.0

    min_delta = min(deltas)
    max_delta = max(deltas)

    print("================================================================================")
    print("=== STATISTICAL COMPARISON: ARM C (3 COW + LATE1) vs ARM D (2C1S + LATE1) ===")
    print("================================================================================")
    print(f"Total Paired Seeds: {n_seeds}")
    print(f"Arm C (3C + Late1) Mean Score:   ${mean_c:9,.2f} +/- ${std_c:7,.2f} (Median: ${median(scores_c):7,.2f})")
    print(f"Arm D (2C1S + Late1) Mean Score: ${mean_d:9,.2f} +/- ${std_d:7,.2f} (Median: ${median(scores_d):7,.2f})")
    print(f"\nPaired D - C Delta Statistics:")
    print(f"  Mean Paired Delta:   ${mean_delta:+9,.2f} ({mean_delta / mean_c * 100:+.2f}%)")
    print(f"  Median Paired Delta: ${med_delta:+9,.2f}")
    print(f"  Paired Std Dev:      ${std_delta:9,.2f}")
    print(f"  Paired Std Error:    ${se_delta:9,.2f}")
    print(f"  95% Confidence Interval for Delta: [${ci_lower:+,.2f}, ${ci_upper:+,.2f}]")
    print(f"\nHead-to-Head Record:")
    print(f"  Arm D Wins: {wins_d} ({frac_d * 100:.1f}%)")
    print(f"  Arm C Wins: {wins_c} ({wins_c / n_seeds * 100:.1f}%)")
    print(f"  Ties:       {ties} ({ties / n_seeds * 100:.1f}%)")
    print(f"  Min Delta:  ${min_delta:+9,.2f}")
    print(f"  Max Delta:  ${max_delta:+9,.2f}")

    # Revenue & Spend Decomposition
    print("\n================================================================================")
    print("=== REVENUE & COST DECOMPOSITION (MEANS PER SEASON) ===")
    print("================================================================================")
    crop_c = mean([d["arm_c"]["crop_revenue"] for d in data])
    crop_d = mean([d["arm_d"]["crop_revenue"] for d in data])
    milk_c = mean([d["arm_c"]["milk_revenue"] for d in data])
    milk_d = mean([d["arm_d"]["milk_revenue"] for d in data])
    wool_c = mean([d["arm_c"]["wool_revenue"] for d in data])
    wool_d = mean([d["arm_d"]["wool_revenue"] for d in data])
    fert_c = mean([d["arm_c"]["fertilizer_revenue"] for d in data])
    fert_d = mean([d["arm_d"]["fertilizer_revenue"] for d in data])

    anim_spend_c = mean([d["arm_c"]["animal_purchase_cost"] for d in data])
    anim_spend_d = mean([d["arm_d"]["animal_purchase_cost"] for d in data])
    feed_spend_c = mean([d["arm_c"]["feed_purchase_cost"] for d in data])
    feed_spend_d = mean([d["arm_d"]["feed_purchase_cost"] for d in data])
    feed_units_c = mean([d["arm_c"]["wheat_bought_units"] for d in data])
    feed_units_d = mean([d["arm_d"]["wheat_bought_units"] for d in data])
    total_feed_c = mean([d["arm_c"]["total_feed_consumed"] for d in data])
    total_feed_d = mean([d["arm_d"]["total_feed_consumed"] for d in data])
    day0_dep_c = mean([d["arm_c"]["day0_cash_deployment"] for d in data])
    day0_dep_d = mean([d["arm_d"]["day0_cash_deployment"] for d in data])

    print(f"{'Metric':<28} | {'Arm C (3C+Late1)':<18} | {'Arm D (2C1S+Late1)':<18} | {'Delta (D - C)':<15}")
    print("-" * 84)
    print(f"{'Crop Revenue':<28} | ${crop_c:16,.2f} | ${crop_d:16,.2f} | ${crop_d - crop_c:+13,.2f}")
    print(f"{'Milk Revenue':<28} | ${milk_c:16,.2f} | ${milk_d:16,.2f} | ${milk_d - milk_c:+13,.2f}")
    print(f"{'Wool Revenue':<28} | ${wool_c:16,.2f} | ${wool_d:16,.2f} | ${wool_d - wool_c:+13,.2f}")
    print(f"{'Fertilizer Revenue':<28} | ${fert_c:16,.2f} | ${fert_d:16,.2f} | ${fert_d - fert_c:+13,.2f}")
    print(f"{'Animal Purchase Spend':<28} | ${anim_spend_c:16,.2f} | ${anim_spend_d:16,.2f} | ${anim_spend_d - anim_spend_c:+13,.2f}")
    print(f"{'Feed Wheat Purchase Spend':<28} | ${feed_spend_c:16,.2f} | ${feed_spend_d:16,.2f} | ${feed_spend_d - feed_spend_c:+13,.2f}")
    print(f"{'Feed Wheat Bought Units':<28} | {feed_units_c:16.1f}  | {feed_units_d:16.1f}  | {feed_units_d - feed_units_c:+13.1f}")
    print(f"{'Total Feed Actions Executed':<28} | {total_feed_c:16.1f}  | {total_feed_d:16.1f}  | {total_feed_d - total_feed_c:+13.1f}")
    print(f"{'Day-0 Cash Deployed':<28} | ${day0_dep_c:16,.2f} | ${day0_dep_d:16,.2f} | ${day0_dep_d - day0_dep_c:+13,.2f}")

    # Checkpoint Cash Trajectory
    print("\n================================================================================")
    print("=== CHECKPOINT CASH TRAJECTORY (MEANS PER MILESTONE) ===")
    print("================================================================================")
    checkpoints = [1, 3, 5, 10, 12, 14, 20, 30]
    print(f"{'Day':<6} | {'Arm C Cash':<14} | {'Arm D Cash':<14} | {'Delta (D - C)':<14}")
    print("-" * 54)
    for cp in checkpoints:
        c_cp = mean([d["arm_c"]["cash_checkpoints"].get(str(cp), d["arm_c"]["cash_checkpoints"].get(cp, 0.0)) for d in data])
        d_cp = mean([d["arm_d"]["cash_checkpoints"].get(str(cp), d["arm_d"]["cash_checkpoints"].get(cp, 0.0)) for d in data])
        print(f"Day {cp:<2} | ${c_cp:12,.2f} | ${d_cp:12,.2f} | ${d_cp - c_cp:+12,.2f}")

    # Opponent Conditional Breakdown
    print("\n================================================================================")
    print("=== CONDITIONAL BREAKDOWN BY OPPONENT TYPE ===")
    print("================================================================================")
    opp_groups = defaultdict(list)
    for d in data:
        opp_groups[d["opponent"]].append(d)

    print(f"{'Opponent':<23} | {'N':<3} | {'Arm C Mean':<12} | {'Arm D Mean':<12} | {'Delta (D - C)':<14} | {'D Win Rate':<10}")
    print("-" * 84)
    for opp, entries in sorted(opp_groups.items()):
        n_opp = len(entries)
        m_c = mean([e["arm_c"]["final_score"] for e in entries])
        m_d = mean([e["arm_d"]["final_score"] for e in entries])
        d_del = mean([e["delta_d_minus_c"] for e in entries])
        d_wins = sum(1 for e in entries if e["delta_d_minus_c"] > 0)
        wr = d_wins / n_opp * 100 if n_opp else 0.0
        print(f"{opp:<23} | {n_opp:<3} | ${m_c:10,.2f} | ${m_d:10,.2f} | ${d_del:+12,.2f} | {wr:8.1f}%")

    # Correlation Analysis
    print("\n================================================================================")
    print("=== CORRELATION ANALYSIS: FACTORS DRIVING D - C DELTA ===")
    print("================================================================================")
    wool_rev_d = [d["arm_d"]["wool_revenue"] for d in data]
    milk_rev_d = [d["arm_d"]["milk_revenue"] for d in data]
    crop_rev_d = [d["arm_d"]["crop_revenue"] for d in data]
    feed_spend_d_list = [d["arm_d"]["feed_purchase_cost"] for d in data]
    day0_dep_d_list = [d["arm_d"]["day0_cash_deployment"] for d in data]
    d12_cash_d = [d["arm_d"]["cash_checkpoints"].get("12", d["arm_d"]["cash_checkpoints"].get(12, 0.0)) for d in data]

    print(f"Correlation(Delta, Arm D Wool Revenue):        r = {pearson_corr(deltas, wool_rev_d):+.4f}")
    print(f"Correlation(Delta, Arm D Milk Revenue):        r = {pearson_corr(deltas, milk_rev_d):+.4f}")
    print(f"Correlation(Delta, Arm D Crop Revenue):        r = {pearson_corr(deltas, crop_rev_d):+.4f}")
    print(f"Correlation(Delta, Arm D Feed Wheat Spend):    r = {pearson_corr(deltas, feed_spend_d_list):+.4f}")
    print(f"Correlation(Delta, Arm D Day-0 Cash Deployed): r = {pearson_corr(deltas, day0_dep_d_list):+.4f}")
    print(f"Correlation(Delta, Arm D Day 12 Cash):         r = {pearson_corr(deltas, d12_cash_d):+.4f}")

    # Safety & Invariant Verification
    print("\n================================================================================")
    print("=== SAFETY & INVARIANT VERIFICATION (200 SEASONS TOTAL) ===")
    print("================================================================================")
    wasted_c = sum(d["arm_c"]["wasted_pastures"] for d in data)
    wasted_d = sum(d["arm_d"]["wasted_pastures"] for d in data)
    stranded_c = sum(d["arm_c"]["stranded_animals"] for d in data)
    stranded_d = sum(d["arm_d"]["stranded_animals"] for d in data)
    starve_c = sum(d["arm_c"]["starvations_or_deaths"] for d in data)
    starve_d = sum(d["arm_d"]["starvations_or_deaths"] for d in data)
    escapes_c = sum(d["arm_c"]["escapes"] for d in data)
    escapes_d = sum(d["arm_d"]["escapes"] for d in data)
    neg_cash_c = sum(d["arm_c"]["negative_cash_events"] for d in data)
    neg_cash_d = sum(d["arm_d"]["negative_cash_events"] for d in data)
    post_d14_c = sum(d["arm_c"]["continuation_starts_post_d14"] for d in data)
    post_d14_d = sum(d["arm_d"]["continuation_starts_post_d14"] for d in data)
    min_cash_c = min(d["arm_c"]["min_cash"] for d in data)
    min_cash_d = min(d["arm_d"]["min_cash"] for d in data)

    print(f"Wasted Pastures:                 Arm C = {wasted_c}, Arm D = {wasted_d} (PASS: 0)")
    print(f"Stranded Animals:                Arm C = {stranded_c}, Arm D = {stranded_d} (PASS: 0)")
    print(f"Starvations / Deaths:            Arm C = {starve_c}, Arm D = {starve_d} (PASS: 0)")
    print(f"Animal Escapes:                  Arm C = {escapes_c}, Arm D = {escapes_d} (PASS: 0)")
    print(f"Negative Cash Events:            Arm C = {neg_cash_c}, Arm D = {neg_cash_d} (PASS: 0)")
    print(f"Continuation Starts Post-Day 14: Arm C = {post_d14_c}, Arm D = {post_d14_d} (PASS: 0)")
    print(f"Minimum Bank Balance Observed:   Arm C = ${min_cash_c:.2f}, Arm D = ${min_cash_d:.2f} (PASS: >= $0.00)")

    # Full Per-Seed Paired Table (Top 25 + Bottom 10 sample or full)
    print("\n================================================================================")
    print(f"=== FULL PER-SEED PAIRED TABLE ({n_seeds} SEEDS) ===")
    print("================================================================================")
    print(f"{'Seed':<6} | {'Opponent':<21} | {'Arm C (3C)':<12} | {'Arm D (2C1S)':<12} | {'Delta (D - C)':<14} | {'Winner':<6}")
    print("-" * 80)
    for d in data:
        s = d["seed"]
        opp = d["opponent"]
        c_sc = d["arm_c"]["final_score"]
        d_sc = d["arm_d"]["final_score"]
        delta = d["delta_d_minus_c"]
        win = d["winner"]
        print(f"{s:<6} | {opp:<21} | ${c_sc:10,.0f} | ${d_sc:10,.0f} | ${delta:+12,.0f} | {win:<6}")


if __name__ == "__main__":
    main()
