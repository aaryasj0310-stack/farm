"""Generate comprehensive analysis of the housing-safe selective late-cow experiment."""
import json
import numpy as np

with open("artifacts/housing_safe_ab_results.json") as f:
    results = json.load(f)

with open("artifacts/housing_safe_ab_summary.json") as f:
    summary = json.load(f)

arm_a = [r for r in results if r["arm"] == "A"]
arm_b = [r for r in results if r["arm"] == "B"]

print("================================================================================")
print("              HOUSING-SAFE SELECTIVE LATE-COW EXPERIMENT REPORT                 ")
print("================================================================================")

print("\n--- 1. OVERALL FINANCIAL PERFORMANCE ---")
print(f"{'Metric':<20} | {'Arm A (Control)':<18} | {'Arm B (Selective)':<18} | {'Delta':<18}")
print("-" * 80)
print(f"{'Mean Score':<20} | ${summary['scores_arm_a']['mean']:>17,.2f} | ${summary['scores_arm_b']['mean']:>17,.2f} | ${summary['paired_delta']['mean']:>+17,.2f}")
print(f"{'Median Score':<20} | ${summary['scores_arm_a']['median']:>17,.2f} | ${summary['scores_arm_b']['median']:>17,.2f} | ${summary['paired_delta']['median']:>+17,.2f}")
print(f"{'Std Dev':<20} | ${summary['scores_arm_a']['std']:>17,.2f} | ${summary['scores_arm_b']['std']:>17,.2f} | ${summary['paired_delta']['std']:>17,.2f}")
print(f"{'Min Score':<20} | ${summary['scores_arm_a']['min']:>17,.2f} | ${summary['scores_arm_b']['min']:>17,.2f} | ${summary['paired_delta']['min']:>+17,.2f}")
print(f"{'Max Score':<20} | ${summary['scores_arm_a']['max']:>17,.2f} | ${summary['scores_arm_b']['max']:>17,.2f} | ${summary['paired_delta']['max']:>+17,.2f}")
print(f"{'P10 (Bottom Tail)':<20} | ${summary['scores_arm_a']['p10']:>17,.2f} | ${summary['scores_arm_b']['p10']:>17,.2f} | ${summary['scores_arm_b']['p10'] - summary['scores_arm_a']['p10']:>+17,.2f}")
print(f"{'P25':<20} | ${summary['scores_arm_a']['p25']:>17,.2f} | ${summary['scores_arm_b']['p25']:>17,.2f} | ${summary['scores_arm_b']['p25'] - summary['scores_arm_a']['p25']:>+17,.2f}")
print(f"{'P75':<20} | ${summary['scores_arm_a']['p75']:>17,.2f} | ${summary['scores_arm_b']['p75']:>17,.2f} | ${summary['scores_arm_b']['p75'] - summary['scores_arm_a']['p75']:>+17,.2f}")
print(f"{'P90':<20} | ${summary['scores_arm_a']['p90']:>17,.2f} | ${summary['scores_arm_b']['p90']:>17,.2f} | ${summary['scores_arm_b']['p90'] - summary['scores_arm_a']['p90']:>+17,.2f}")

print("\n--- 2. PAIRED MATCH RECORD ---")
w = summary['paired_delta']['wins']
l = summary['paired_delta']['losses']
t = summary['paired_delta']['ties']
tot = summary['total_pairs']
print(f"Total Paired Scenarios: {tot}")
print(f"Arm B Wins:             {w} ({w/tot*100:.1f}%)")
print(f"Arm B Losses:           {l} ({l/tot*100:.1f}%)")
print(f"Ties:                   {t} ({t/tot*100:.1f}%)")
decisive = w + l
print(f"Win Rate (Decisive):    {w/decisive*100:.1f}% ({w}/{decisive})")

print("\n--- 3. OPPONENT BREAKDOWN ---")
for opp in ("random", "starter"):
    sub_a = [r for r in arm_a if r["opponent"] == opp]
    sub_b = [r for r in arm_b if r["opponent"] == opp]
    scores_a = [r["final_money"] for r in sub_a]
    scores_b = [r["final_money"] for r in sub_b]

    a_dict = {r["seed"]: r["final_money"] for r in sub_a}
    b_dict = {r["seed"]: r["final_money"] for r in sub_b}
    deltas = [b_dict[s] - a_dict[s] for s in a_dict if s in b_dict]
    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    ties = sum(1 for d in deltas if d == 0)

    print(f"Opponent: {opp:<10} | Arm A Mean: ${np.mean(scores_a):>10,.2f} | Arm B Mean: ${np.mean(scores_b):>10,.2f} | Delta Mean: ${np.mean(deltas):>+10,.2f} | Record: {wins}W/{losses}L/{ties}T")

print("\n--- 4. HOUSING & EXECUTION AUDIT (CRITICAL INVARIANTS) ---")
print(f"Arm B Late Cows Purchased:                 {summary['livestock_arm_b']['late_cows_bought']}")
print(f"Arm B Late Cows Placed on Pastures:        {summary['livestock_arm_b']['late_cows_placed']}")
print(f"Arm B Late Cows Stranded:                  {summary['livestock_arm_b']['late_cows_stranded']}")
print(f"Arm B Purchased WITHOUT Guaranteed Housing:{summary['livestock_arm_b']['late_cows_bought_without_housing']}")
print(f"Arm B Late Sheep Purchased:                {summary['livestock_arm_b']['late_sheep_bought']}")
print(f"Arm B Late Sheep Placed on Pastures:       {summary['livestock_arm_b']['late_sheep_placed']}")
print(f"Arm B Late Sheep Stranded:                 {summary['livestock_arm_b']['late_sheep_stranded']}")

print("\n--- 5. HERD EXPANSION TRAJECTORY ---")
print(f"{'Day':<6} | {'Arm A Mean Herd':<18} | {'Arm B Mean Herd':<18} | {'Herd Difference':<18}")
print("-" * 65)
for day in (0, 5, 10, 11, 12, 13, 14, 15, 20, 28):
    herds_a = [r['herd_trajectory'].get(str(day), {}).get('total_herd', 0) for r in arm_a]
    herds_b = [r['herd_trajectory'].get(str(day), {}).get('total_herd', 0) for r in arm_b]
    diff = np.mean(herds_b) - np.mean(herds_a)
    print(f"Day {day:<2d} | {np.mean(herds_a):>18.2f} | {np.mean(herds_b):>18.2f} | {diff:>+18.2f}")

print(f"\nPeak Herd: Arm A = {summary['livestock_arm_a']['mean_peak_herd']:.2f} | Arm B = {summary['livestock_arm_b']['mean_peak_herd']:.2f} (+{summary['livestock_arm_b']['mean_peak_herd'] - summary['livestock_arm_a']['mean_peak_herd']:.2f})")

print("\n--- 6. SAFETY & RISK METRICS ---")
print(f"Pre-Day 28 Feed Failures: Arm A = {summary['safety_arm_a']['feed_failures_pre28']} | Arm B = {summary['safety_arm_b']['feed_failures_pre28']}")
print(f"Endgame Feed Failures:    Arm A = {summary['safety_arm_a']['feed_failures_endgame']} | Arm B = {summary['safety_arm_b']['feed_failures_endgame']}")
print(f"Animal Escapes / Deaths:  Arm A = {summary['safety_arm_a']['animal_escapes']} | Arm B = {summary['safety_arm_b']['animal_escapes']}")
print(f"Shed Overflows:           Arm A = {summary['safety_arm_a']['shed_overflows']} | Arm B = {summary['safety_arm_b']['shed_overflows']}")

print("\n--- 7. PRODUCTION PROMOTION CRITERIA EVALUATION ---")
c1 = summary['paired_delta']['mean'] > 0
c2 = summary['paired_delta']['median'] > 0
c3 = w > l
c4 = (summary['scores_arm_b']['p10'] - summary['scores_arm_a']['p10']) >= 0
c5 = summary['safety_arm_b']['animal_escapes'] == 0
c6 = summary['livestock_arm_b']['late_cows_stranded'] == 0
c7 = summary['livestock_arm_b']['late_cows_bought_without_housing'] == 0

print(f"1. Paired Mean Delta > 0:               {c1} (${summary['paired_delta']['mean']:+,.2f})")
print(f"2. Paired Median Delta > 0:             {c2} (${summary['paired_delta']['median']:+,.2f})")
print(f"3. Majority Paired Wins:                {c3} ({w} Wins vs {l} Losses)")
print(f"4. Bottom Tail (P10) Not Degraded:      {c4} (${summary['scores_arm_b']['p10'] - summary['scores_arm_a']['p10']:+,.2f})")
print(f"5. Zero Animal Escapes/Deaths:          {c5} ({summary['safety_arm_b']['animal_escapes']} escapes)")
print(f"6. Zero Stranded Animals:               {c6} ({summary['livestock_arm_b']['late_cows_stranded']} stranded)")
print(f"7. Zero Buys Without Housing:           {c7} ({summary['livestock_arm_b']['late_cows_bought_without_housing']} buys)")

all_passed = all([c1, c2, c3, c4, c5, c6, c7])
print("-" * 80)
print(f"OVERALL PROMOTION RECOMMENDATION: {'APPROVED FOR PRODUCTION' if all_passed else 'REJECTED'}")
print("================================================================================")
