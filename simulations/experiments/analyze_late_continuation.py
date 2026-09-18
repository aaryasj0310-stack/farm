import json
import numpy as np
from collections import defaultdict

with open("simulations/experiments/results/point2_late_continuation_results.json") as f:
    data = json.load(f)

by_arm = defaultdict(list)
for r in data:
    by_arm[r["arm"]].append(r)

print("=== STATISTICAL SUMMARY ACROSS 4 ARMS (10 SEEDS EACH) ===")
arm_stats = {}
for arm, results in by_arm.items():
    scores = [r["final_score"] for r in results]
    mean = np.mean(scores)
    std = np.std(scores)
    med = np.median(scores)
    min_s = np.min(scores)
    max_s = np.max(scores)
    end_herds = [r["end_total_owned_herd"] for r in results]
    max_herds = [r["max_total_owned_herd"] for r in results]
    end_pastures = [r["end_physical_pastures"] for r in results]
    wasted = [r["wasted_pastures"] for r in results]
    starv = sum(r["starvations_or_deaths"] for r in results)
    neg_cash = sum(r["negative_cash_events"] for r in results)
    crop_rev = np.mean([r["crop_rev"] for r in results])
    milk_rev = np.mean([r["milk_rev"] for r in results])
    wool_rev = np.mean([r["wool_rev"] for r in results])
    fert_rev = np.mean([r["fert_rev"] for r in results])
    
    arm_stats[arm] = {
        "mean": mean, "std": std, "median": med, "min": min_s, "max": max_s,
        "mean_herd": np.mean(end_herds), "mean_max_herd": np.mean(max_herds),
        "mean_pastures": np.mean(end_pastures), "mean_wasted": np.mean(wasted),
        "starvations": starv, "neg_cash": neg_cash,
        "crop_rev": crop_rev, "milk_rev": milk_rev, "wool_rev": wool_rev, "fert_rev": fert_rev,
        "scores": scores,
    }
    print(f"\nArm {arm}:")
    print(f"  Mean Score: ${mean:,.2f} +/- ${std:,.2f} (Median: ${med:,.2f}, Min: ${min_s:,.2f}, Max: ${max_s:,.2f})")
    print(f"  Herd (End): {np.mean(end_herds):.1f} (Max: {np.mean(max_herds):.1f}) | Pastures: {np.mean(end_pastures):.1f} | Wasted Pastures: {np.mean(wasted):.1f}")
    print(f"  Revenues: Crop=${crop_rev:,.0f} | Milk=${milk_rev:,.0f} | Wool=${wool_rev:,.0f} | Fert=${fert_rev:,.0f}")
    print(f"  Safety: Starvations={starv} | Negative Cash Events={neg_cash}")

# Comparisons
mean_a = arm_stats["ArmA"]["mean"]
mean_b = arm_stats["ArmB"]["mean"]
mean_c = arm_stats["ArmC"]["mean"]
mean_d = arm_stats["ArmD"]["mean"]

print("\n=== PAIRWISE DELTAS ===")
print(f"Arm B vs Arm A (3C Boot vs Live):               +${mean_b - mean_a:,.2f} ({((mean_b - mean_a)/mean_a)*100:+.2f}%)")
print(f"Arm C vs Arm A (3C+Late1 vs Live):              +${mean_c - mean_a:,.2f} ({((mean_c - mean_a)/mean_a)*100:+.2f}%)")
print(f"Arm C vs Arm B (Late1 continuation effect):     +${mean_c - mean_b:,.2f} ({((mean_c - mean_b)/mean_b)*100:+.2f}%)")
print(f"Arm D vs Arm A (2C1S+Late1 vs Live):            +${mean_d - mean_a:,.2f} ({((mean_d - mean_a)/mean_a)*100:+.2f}%)")
print(f"Arm D vs Arm C (2C1S+Late1 vs 3C+Late1):        +${mean_d - mean_c:,.2f} ({((mean_d - mean_c)/mean_c)*100:+.2f}%)")

# Canonical Shadow Gap Comparison
canonical_shadow_mean = 95855.50
canonical_live_mean = 67090.20
canonical_gap = canonical_shadow_mean - canonical_live_mean
print(f"\nCanonical Shadow Gap: ${canonical_gap:,.2f} ($95,855.50 - $67,090.20)")
print(f"Arm B closed: ${mean_b - canonical_live_mean:,.2f} ({((mean_b - canonical_live_mean)/canonical_gap)*100:.2f}%)")
print(f"Arm C closed: ${mean_c - canonical_live_mean:,.2f} ({((mean_c - canonical_live_mean)/canonical_gap)*100:.2f}%)")

# Per seed comparison
print("\n=== PER SEED SCORES ===")
print(f"{'Seed':<6} | {'Arm A (Live)':<14} | {'Arm B (3C)':<14} | {'Arm C (3C+Late1)':<16} | {'Arm D (2C1S+Late1)':<16} | {'C - B Delta':<12}")
print("-" * 88)
for i in range(10):
    seed = by_arm["ArmA"][i]["seed"]
    sa = by_arm["ArmA"][i]["final_score"]
    sb = by_arm["ArmB"][i]["final_score"]
    sc = by_arm["ArmC"][i]["final_score"]
    sd = by_arm["ArmD"][i]["final_score"]
    print(f"{seed:<6d} | ${sa:<13,.0f} | ${sb:<13,.0f} | ${sc:<15,.0f} | ${sd:<17,.0f} | ${sc - sb:<+11,.0f}")

# Housing transition traces for Arm C
print("\n=== HOUSING TRANSITION TRACES (ARM C) ===")
for r in by_arm["ArmC"]:
    print(f"Seed {r['seed']:<5d}: D12-14 Traces: {r['housing_traces']} | Pasture Events: {r['pasture_build_events']} | Animal Buys: {r['animal_buy_events']}")

# Cash Checkpoints
print("\n=== MEAN CASH CHECKPOINTS ===")
for arm in ("ArmA", "ArmB", "ArmC", "ArmD"):
    cp_means = {}
    for day in (1, 3, 5, 10, 12, 14, 20, 30):
        vals = [r["cash_checkpoints"].get(day, r["cash_checkpoints"].get(str(day), 0.0)) for r in by_arm[arm]]
        cp_means[day] = np.mean(vals)
    print(f"{arm}: " + " | ".join(f"D{d}: ${cp_means[d]:,.0f}" for d in (1, 3, 5, 10, 12, 14, 20, 30)))
