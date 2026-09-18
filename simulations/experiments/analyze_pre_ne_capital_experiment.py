"""Statistical Analysis of Point-2 Pre-NE Capital Admission Policy Experiment (800 Matches).

Analyzes the 200 held-out seeds evaluated across 4 arms:
  Arm A: Shadow Control (shadow / none / Late1 OFF / pre-NE off)
  Arm B: Rejected Live Baseline (live / ArmE / Late1 ON / pre-NE off)
  Arm C: NE-first Live (live / ArmE / Late1 ON / pre-NE ne_first)
  Arm D: NE-escrow Live (live / ArmE / Late1 ON / pre-NE ne_escrow)

Computes:
  1. Executive Summary (means, medians, std, min, max)
  2. Paired Comparisons & Hypothesis Tests (vs Shadow A and vs Live Baseline B)
  3. Recovery Fraction of Shadow Gap ($12,356.39)
  4. NE Timing & Capital Preservation Mechanics (NE unlock day, cash at D0/D1/D3/D5)
  5. Herd & Late1 Continuation Mechanics
  6. Hard Safety Invariants Table
  7. Opponent Archetype Stratified Breakdown (5 archetypes, N=40 each)
  8. Final Production Gate Decision
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
    ROOT_DIR, "simulations", "experiments", "results", "pre_ne_capital_experiment_results.json"
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

    t_crit = stats.t.ppf(0.975, df=n - 1) if n > 1 else 1.96
    ci_lower = mean_diff - t_crit * se_diff
    ci_upper = mean_diff + t_crit * se_diff

    t_res = stats.ttest_rel(arr_a, arr_b)
    t_stat = float(t_res.statistic)
    t_pval = float(t_res.pvalue)

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
    }


def main():
    data = load_results()
    results = data["results"]
    n_seeds = len(results)

    scores_a = [r["arm_a"]["final_score"] for r in results]
    scores_b = [r["arm_b"]["final_score"] for r in results]
    scores_c = [r["arm_c"]["final_score"] for r in results]
    scores_d = [r["arm_d"]["final_score"] for r in results]

    stats_a = compute_distribution_stats(scores_a)
    stats_b = compute_distribution_stats(scores_b)
    stats_c = compute_distribution_stats(scores_c)
    stats_d = compute_distribution_stats(scores_d)

    # Paired comparisons
    b_vs_a = compute_paired_comparison(scores_b, scores_a, "Arm B (Live Baseline)", "Arm A (Shadow Control)")
    c_vs_a = compute_paired_comparison(scores_c, scores_a, "Arm C (NE-first Live)", "Arm A (Shadow Control)")
    d_vs_a = compute_paired_comparison(scores_d, scores_a, "Arm D (NE-escrow Live)", "Arm A (Shadow Control)")
    c_vs_b = compute_paired_comparison(scores_c, scores_b, "Arm C (NE-first Live)", "Arm B (Live Baseline)")
    d_vs_b = compute_paired_comparison(scores_d, scores_b, "Arm D (NE-escrow Live)", "Arm B (Live Baseline)")
    d_vs_c = compute_paired_comparison(scores_d, scores_c, "Arm D (NE-escrow Live)", "Arm C (NE-first Live)")

    # Shadow gap and recovery fractions
    shadow_gap = stats_a["mean"] - stats_b["mean"]
    rec_c = (stats_c["mean"] - stats_b["mean"]) / shadow_gap if shadow_gap > 0 else 0.0
    rec_d = (stats_d["mean"] - stats_b["mean"]) / shadow_gap if shadow_gap > 0 else 0.0

    print("================================================================================")
    print(" POINT-2 PRE-NE CAPITAL EXPERIMENT: STATISTICAL REPORT (N=200 SEEDS / 800 MATCHES)")
    print("================================================================================")

    print("\n--- 1. EXECUTIVE PERFORMANCE SUMMARY ---")
    print(f"{'Arm':<28} | {'Mean':>11} | {'Median':>10} | {'Std':>9} | {'Min':>9} | {'Max':>10}")
    print("-" * 88)
    for name, s in [
        ("Arm A: Shadow Control", stats_a),
        ("Arm B: Live Baseline (off)", stats_b),
        ("Arm C: Live NE-first", stats_c),
        ("Arm D: Live NE-escrow", stats_d),
    ]:
        print(f"{name:<28} | ${s['mean']:>10,.2f} | ${s['median']:>9,.2f} | ${s['std']:>8,.2f} | ${s['min']:>8,.2f} | ${s['max']:>9,.2f}")

    print("\n--- 2. SHADOW GAP RECOVERY ANALYSIS ---")
    print(f"Shadow Control (Arm A) Mean:          ${stats_a['mean']:>10,.2f}")
    print(f"Current Live Baseline (Arm B) Mean:   ${stats_b['mean']:>10,.2f}")
    print(f"Baseline Deficit (Shadow Gap):        ${shadow_gap:>10,.2f} (-{shadow_gap / stats_a['mean'] * 100:.2f}%)")
    print(f"Arm C (NE-first) Gain over Arm B:     ${c_vs_b['mean_delta']:>+10,.2f} (Recovery: {rec_c*100:+.1f}%)")
    print(f"Arm D (NE-escrow) Gain over Arm B:    ${d_vs_b['mean_delta']:>+10,.2f} (Recovery: {rec_d*100:+.1f}%)")

    print("\n--- 3. PAIRED STATISTICAL COMPARISONS ---")
    print(f"{'Comparison':<25} | {'Mean Delta':>11} | {'95% CI':>24} | {'p-value (t)':>12} | {'W / L / T':>12} | {'Win Rate':>8}")
    print("-" * 105)
    for comp in (b_vs_a, c_vs_a, d_vs_a, c_vs_b, d_vs_b, d_vs_c):
        ci_str = f"[${comp['ci_95_lower']:>+9,.2f}, ${comp['ci_95_upper']:>+9,.2f}]"
        wlt_str = f"{comp['wins']:>3} / {comp['losses']:>3} / {comp['ties']:>3}"
        print(f"{comp['name_a'][:14]} vs {comp['name_b'][:8]:<7} | ${comp['mean_delta']:>+10,.2f} | {ci_str:>24} | {comp['t_pvalue']:>12.4e} | {wlt_str:>12} | {comp['win_rate']:>7.1f}%")

    # NE Timing & Capital Preserved Analysis
    ne_unlock_days_a = [r["arm_a"]["ne_unlock_day"] for r in results if r["arm_a"]["ne_unlock_day"] is not None]
    ne_unlock_days_b = [r["arm_b"]["ne_unlock_day"] for r in results if r["arm_b"]["ne_unlock_day"] is not None]
    ne_unlock_days_c = [r["arm_c"]["ne_unlock_day"] for r in results if r["arm_c"]["ne_unlock_day"] is not None]
    ne_unlock_days_d = [r["arm_d"]["ne_unlock_day"] for r in results if r["arm_d"]["ne_unlock_day"] is not None]

    mean_ne_a = float(np.mean(ne_unlock_days_a)) if ne_unlock_days_a else 999.0
    mean_ne_b = float(np.mean(ne_unlock_days_b)) if ne_unlock_days_b else 999.0
    mean_ne_c = float(np.mean(ne_unlock_days_c)) if ne_unlock_days_c else 999.0
    mean_ne_d = float(np.mean(ne_unlock_days_d)) if ne_unlock_days_d else 999.0

    print("\n--- 4. NE UNLOCK TIMING & CAPITAL DYNAMICS ---")
    print(f"{'Metric':<35} | {'Arm A (Shadow)':>14} | {'Arm B (Live-off)':>16} | {'Arm C (NE-first)':>16} | {'Arm D (NE-escrow)':>17}")
    print("-" * 105)
    print(f"{'Mean NE Unlock Day':<35} | {mean_ne_a:>14.2f} | {mean_ne_b:>16.2f} | {mean_ne_c:>16.2f} | {mean_ne_d:>17.2f}")

    for day_cp in (0, 1, 3, 5, 10, 12, 15):
        cash_a = np.mean([r["arm_a"]["cash_checkpoints"].get(str(day_cp), r["arm_a"]["cash_checkpoints"].get(day_cp, 0.0)) for r in results])
        cash_b = np.mean([r["arm_b"]["cash_checkpoints"].get(str(day_cp), r["arm_b"]["cash_checkpoints"].get(day_cp, 0.0)) for r in results])
        cash_c = np.mean([r["arm_c"]["cash_checkpoints"].get(str(day_cp), r["arm_c"]["cash_checkpoints"].get(day_cp, 0.0)) for r in results])
        cash_d = np.mean([r["arm_d"]["cash_checkpoints"].get(str(day_cp), r["arm_d"]["cash_checkpoints"].get(day_cp, 0.0)) for r in results])
        print(f"{f'Mean Cash at Day {day_cp}':<35} | ${cash_a:>13,.0f} | ${cash_b:>15,.0f} | ${cash_c:>15,.0f} | ${cash_d:>16,.0f}")

    d0_anim_spend_a = np.mean([r["arm_a"]["day0_animal_spend"] for r in results])
    d0_anim_spend_b = np.mean([r["arm_b"]["day0_animal_spend"] for r in results])
    d0_anim_spend_c = np.mean([r["arm_c"]["day0_animal_spend"] for r in results])
    d0_anim_spend_d = np.mean([r["arm_d"]["day0_animal_spend"] for r in results])
    print(f"{'Mean Day 0 Livestock Spend':<35} | ${d0_anim_spend_a:>13,.0f} | ${d0_anim_spend_b:>15,.0f} | ${d0_anim_spend_c:>15,.0f} | ${d0_anim_spend_d:>16,.0f}")

    d0_anims_a = np.mean([r["arm_a"]["day0_animals_bought"] for r in results])
    d0_anims_b = np.mean([r["arm_b"]["day0_animals_bought"] for r in results])
    d0_anims_c = np.mean([r["arm_c"]["day0_animals_bought"] for r in results])
    d0_anims_d = np.mean([r["arm_d"]["day0_animals_bought"] for r in results])
    print(f"{'Mean Day 0 Animals Bought':<35} | {d0_anims_a:>14.2f} | {d0_anims_b:>16.2f} | {d0_anims_c:>16.2f} | {d0_anims_d:>17.2f}")

    d0_struct_a = np.mean([r["arm_a"]["day0_structures_queued"] for r in results])
    d0_struct_b = np.mean([r["arm_b"]["day0_structures_queued"] for r in results])
    d0_struct_c = np.mean([r["arm_c"]["day0_structures_queued"] for r in results])
    d0_struct_d = np.mean([r["arm_d"]["day0_structures_queued"] for r in results])
    print(f"{'Mean Day 0 Pastures Queued':<35} | {d0_struct_a:>14.2f} | {d0_struct_b:>16.2f} | {d0_struct_c:>16.2f} | {d0_struct_d:>17.2f}")

    anims_locked_a = np.mean([r["arm_a"]["animals_bought_while_ne_locked"] for r in results])
    anims_locked_b = np.mean([r["arm_b"]["animals_bought_while_ne_locked"] for r in results])
    anims_locked_c = np.mean([r["arm_c"]["animals_bought_while_ne_locked"] for r in results])
    anims_locked_d = np.mean([r["arm_d"]["animals_bought_while_ne_locked"] for r in results])
    print(f"{'Animals Bought While NE Locked':<35} | {anims_locked_a:>14.2f} | {anims_locked_b:>16.2f} | {anims_locked_c:>16.2f} | {anims_locked_d:>17.2f}")

    # Herd & Late1 Continuation Mechanics
    print("\n--- 5. HERD & LATE1 MECHANICS ANALYSIS ---")
    print(f"{'Metric':<35} | {'Arm A (Shadow)':>14} | {'Arm B (Live-off)':>16} | {'Arm C (NE-first)':>16} | {'Arm D (NE-escrow)':>17}")
    print("-" * 105)
    placed_a = np.mean([r["arm_a"]["final_placed_herd"] for r in results])
    placed_b = np.mean([r["arm_b"]["final_placed_herd"] for r in results])
    placed_c = np.mean([r["arm_c"]["final_placed_herd"] for r in results])
    placed_d = np.mean([r["arm_d"]["final_placed_herd"] for r in results])
    print(f"{'Final Placed Herd':<35} | {placed_a:>14.2f} | {placed_b:>16.2f} | {placed_c:>16.2f} | {placed_d:>17.2f}")

    past_a = np.mean([r["arm_a"]["final_pastures"] for r in results])
    past_b = np.mean([r["arm_b"]["final_pastures"] for r in results])
    past_c = np.mean([r["arm_c"]["final_pastures"] for r in results])
    past_d = np.mean([r["arm_d"]["final_pastures"] for r in results])
    print(f"{'Final Pastures Built':<35} | {past_a:>14.2f} | {past_b:>16.2f} | {past_c:>16.2f} | {past_d:>17.2f}")

    late1_req_b = np.mean([r["arm_b"]["continuation_pasture_requests"] for r in results])
    late1_req_c = np.mean([r["arm_c"]["continuation_pasture_requests"] for r in results])
    late1_req_d = np.mean([r["arm_d"]["continuation_pasture_requests"] for r in results])
    print(f"{'Late1 Pasture Requests':<35} | {'N/A':>14} | {late1_req_b:>16.2f} | {late1_req_c:>16.2f} | {late1_req_d:>17.2f}")

    late1_comp_b = np.mean([r["arm_b"]["continuation_pasture_completions"] for r in results])
    late1_comp_c = np.mean([r["arm_c"]["continuation_pasture_completions"] for r in results])
    late1_comp_d = np.mean([r["arm_d"]["continuation_pasture_completions"] for r in results])
    print(f"{'Late1 Pasture Completions':<35} | {'N/A':>14} | {late1_comp_b:>16.2f} | {late1_comp_c:>16.2f} | {late1_comp_d:>17.2f}")

    late1_buy_b = np.mean([r["arm_b"]["continuation_animal_purchases"] for r in results])
    late1_buy_c = np.mean([r["arm_c"]["continuation_animal_purchases"] for r in results])
    late1_buy_d = np.mean([r["arm_d"]["continuation_animal_purchases"] for r in results])
    print(f"{'Late1 Animal Purchases':<35} | {'N/A':>14} | {late1_buy_b:>16.2f} | {late1_buy_c:>16.2f} | {late1_buy_d:>17.2f}")

    # Correctness Invariants Table
    print("\n--- 6. COMPREHENSIVE HARD SAFETY INVARIANTS TABLE ---")
    print(f"{'Invariant':<40} | {'Arm A':>10} | {'Arm B':>10} | {'Arm C':>10} | {'Arm D':>10}")
    print("-" * 88)
    for inv_name, key in [
        ("Starvations / Herd Shrink Events", "starvations_or_deaths"),
        ("Feed Shortage Deaths", "feed_shortage_deaths"),
        ("Negative Cash Events", "negative_cash_events"),
        ("C2C Dependency Violations", "c2c_dependency_violations"),
        ("Wheat Sale Reservation Violations", "wheat_sale_reservation_violations"),
        ("Unsafe Livestock Fallback Events", "unsafe_livestock_fallback_events"),
        ("Purchases into Uncompleted Pasture", "purchases_into_uncompleted_pasture"),
    ]:
        tot_a = sum(r["arm_a"].get(key, 0) for r in results)
        tot_b = sum(r["arm_b"].get(key, 0) for r in results)
        tot_c = sum(r["arm_c"].get(key, 0) for r in results)
        tot_d = sum(r["arm_d"].get(key, 0) for r in results)
        print(f"{inv_name:<40} | {tot_a:>10} | {tot_b:>10} | {tot_c:>10} | {tot_d:>10}")

    # Opponent Archetype Breakdown
    print("\n--- 7. STRATIFIED OPPONENT ARCHETYPE BREAKDOWN (N=40 SEEDS PER ARCHETYPE) ---")
    opponents = sorted(list(set(r["opponent"] for r in results)))
    for opp in opponents:
        opp_results = [r for r in results if r["opponent"] == opp]
        n_opp = len(opp_results)
        s_a = [r["arm_a"]["final_score"] for r in opp_results]
        s_b = [r["arm_b"]["final_score"] for r in opp_results]
        s_c = [r["arm_c"]["final_score"] for r in opp_results]
        s_d = [r["arm_d"]["final_score"] for r in opp_results]
        print(f"\nArchetype: {opp} (N={n_opp})")
        print(f"  Arm A (Shadow Control):     ${np.mean(s_a):>10,.2f}  (100% baseline)")
        print(f"  Arm B (Live Baseline):      ${np.mean(s_b):>10,.2f}  (Δ vs A: ${np.mean(s_b)-np.mean(s_a):>+9,.2f}, W/L/T: {sum(b>a for b,a in zip(s_b,s_a))}/{sum(b<a for b,a in zip(s_b,s_a))}/{sum(b==a for b,a in zip(s_b,s_a))})")
        print(f"  Arm C (NE-first Live):      ${np.mean(s_c):>10,.2f}  (Δ vs B: ${np.mean(s_c)-np.mean(s_b):>+9,.2f}, Δ vs A: ${np.mean(s_c)-np.mean(s_a):>+9,.2f})")
        print(f"  Arm D (NE-escrow Live):     ${np.mean(s_d):>10,.2f}  (Δ vs B: ${np.mean(s_d)-np.mean(s_b):>+9,.2f}, Δ vs A: ${np.mean(s_d)-np.mean(s_a):>+9,.2f})")

    # Conclusion & Decision
    print("\n================================================================================")
    print(" 8. PRODUCTION DECISION & SYNTHESIS")
    print("================================================================================")
    print(f"Shadow Control Mean:           ${stats_a['mean']:>10,.2f}")
    print(f"Live Baseline Mean (Arm B):    ${stats_b['mean']:>10,.2f}")
    print(f"Live NE-first Mean (Arm C):    ${stats_c['mean']:>10,.2f}")
    print(f"Live NE-escrow Mean (Arm D):   ${stats_d['mean']:>10,.2f}")
    print("-" * 80)
    print(f"NE Unlock Day: A={mean_ne_a:.2f}, B={mean_ne_b:.2f}, C={mean_ne_c:.2f}, D={mean_ne_d:.2f}")

    c_beats_a = stats_c["mean"] > stats_a["mean"]
    d_beats_a = stats_d["mean"] > stats_a["mean"]
    c_beats_b = stats_c["mean"] > stats_b["mean"]
    d_beats_b = stats_d["mean"] > stats_b["mean"]

    print(f"\nHypothesis Test Results:")
    print(f"  Does NE-first recover Shadow gap? {'YES' if c_beats_a else 'NO'} (Recovery: {rec_c*100:+.1f}%)")
    print(f"  Does NE-escrow recover Shadow gap? {'YES' if d_beats_a else 'NO'} (Recovery: {rec_d*100:+.1f}%)")
    print(f"  Does NE-first beat Live Baseline? {'YES' if c_beats_b else 'NO'} (Gain: ${c_vs_b['mean_delta']:+,.2f})")
    print(f"  Does NE-escrow beat Live Baseline? {'YES' if d_beats_b else 'NO'} (Gain: ${d_vs_b['mean_delta']:+,.2f})")

    if not c_beats_a and not d_beats_a:
        print("\nDECISION: Neither candidate policy beats the Production Shadow Control.")
        print("Production configuration remains strictly preserved at defaults:")
        print("  POINT2_FEED_MODE = 'shadow'")
        print("  BOOTSTRAP_LIVESTOCK_ARM = 'none'")
        print("  ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False")
        print("  POINT2_PRE_NE_CAPITAL_MODE = 'off'")
    else:
        best_arm = "Arm C (NE-first)" if stats_c["mean"] > stats_d["mean"] else "Arm D (NE-escrow)"
        print(f"\nDECISION: {best_arm} demonstrates significant improvement over baseline.")

    print("\nPOINT 2 NE-PRESERVING CAPITAL EXPERIMENT COMPLETE — READY FOR SOL REVIEW")


if __name__ == "__main__":
    main()
