#!/usr/bin/env python3
"""
Deep-dive analysis script for CentralPlanner attribution audit data.
Reads artifacts/central_planner_A_vs_D2_attribution.json and generates detailed statistical tables.
"""

import json
import os
import sys
from collections import Counter, defaultdict
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(REPO_ROOT, "artifacts", "central_planner_A_vs_D2_attribution.json")

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

pairs = data["pair_results"]
total_pairs = len(pairs)
total_turns = total_pairs * 720

print(f"Loaded {total_pairs} paired scenarios ({total_turns} total turns).")

# 1. Selection & Execution Divergence
sel_turns = data["total_selection_divergent_turns"]
reorder_turns = data["total_reorder_only_turns"]
tot_div = data["total_divergent_turns"]

print("\n=== 1. DIVERGENCE RATES ===")
print(f"Total Evaluated Turns:           {total_turns}")
print(f"Total Divergent Turns:           {tot_div} ({tot_div/total_turns*100:.2f}%)")
print(f"Selection Divergent Turns:       {sel_turns} ({sel_turns/total_turns*100:.2f}%)")
print(f"Execution Reorder Only Turns:    {reorder_turns} ({reorder_turns/total_turns*100:.2f}%)")

# 2. Score Summary
mean_A = data["mean_A"]
mean_D2 = data["mean_D2"]
mean_delta = data["mean_delta"]
med_delta = data["median_delta"]
wins = data["wins"]
losses = data["losses"]
ties = data["ties"]

print("\n=== 2. MATCH PERFORMANCE ===")
print(f"Architecture A Mean:      ${mean_A:,.2f}")
print(f"Architecture D2 Mean:     ${mean_D2:,.2f}")
print(f"Mean Delta (D2 - A):      ${mean_delta:+,.2f}")
print(f"Median Delta:             ${med_delta:+,.2f}")
print(f"Win/Loss/Tie:             {wins} Wins / {losses} Losses / {ties} Ties ({wins/total_pairs*100:.1f}% win rate)")

# 3. Category Breakdown & Concentration in Losses vs Wins
print("\n=== 3. DIVERGENCE CATEGORIES: FREQUENCY & LOSS CONCENTRATION ===")
print(f"{'Category':<24} | {'Total':<6} | {'In Losses':<10} | {'In Wins':<8} | {'Loss Share':<10} | {'Mean Delta':<12}")
print("-" * 75)

cat_deltas = defaultdict(list)
for r in pairs:
    d = r["delta"]
    for div in r["divergent_turns"]:
        cat_deltas[div["category"]].append(d)

for cat, total in Counter(data["cat_counts_total"]).most_common():
    n_loss = data["cat_counts_losses"].get(cat, 0)
    n_win = data["cat_counts_wins"].get(cat, 0)
    share = (n_loss / total * 100.0) if total > 0 else 0.0
    m_delta = np.mean(cat_deltas[cat]) if cat_deltas[cat] else 0.0
    print(f"{cat:<24} | {total:<6} | {n_loss:<10} | {n_win:<8} | {share:>9.1f}% | ${m_delta:>+10,.2f}")

# 4. First Divergence Analysis
print("\n=== 4. FIRST SELECTION DIVERGENCE PER EPISODE ===")
print(f"{'Category':<24} | {'Episodes':<8} | {'Losses':<8} | {'Wins':<8} | {'Loss Share':<10}")
print("-" * 65)
first_div_cats = Counter()
first_div_losses = Counter()
first_div_wins = Counter()
for r in pairs:
    fd = r.get("first_selection_divergence")
    if fd:
        c = fd["category"]
        first_div_cats[c] += 1
        if r["delta"] < 0:
            first_div_losses[c] += 1
        else:
            first_div_wins[c] += 1

for cat, cnt in first_div_cats.most_common():
    n_loss = first_div_losses.get(cat, 0)
    n_win = first_div_wins.get(cat, 0)
    share = (n_loss / cnt * 100.0) if cnt > 0 else 0.0
    print(f"{cat:<24} | {cnt:<8} | {n_loss:<8} | {n_win:<8} | {share:>9.1f}%")

# 5. Land Timing Audit
ne_deltas = data.get("land_ne_deltas", [])
sw_deltas = data.get("land_sw_deltas", [])
print("\n=== 5. LAND TIMING AUDIT ===")
print(f"NE Unlock Day Delta (D2 - A): Mean {np.mean(ne_deltas):+.2f} days | Exact Matches: {sum(1 for d in ne_deltas if d == 0)} / {len(ne_deltas)}")
print(f"SW Unlock Day Delta (D2 - A): Mean {np.mean(sw_deltas):+.2f} days | Exact Matches: {sum(1 for d in sw_deltas if d == 0)} / {len(sw_deltas)}")

# 6. Hires Audit
hires_diffs = data.get("hires_diffs", [])
print("\n=== 6. HIRES AUDIT ===")
print(f"Total Hires Difference (D2 - A): Mean {np.mean(hires_diffs):+.2f} | Exact Matches: {sum(1 for d in hires_diffs if d == 0)} / {len(hires_diffs)}")

# 7. Sells & Revenue Loss
print("\n=== 7. SELL LOSS ATTRIBUTION (Sales in A but omitted in D2) ===")
print(f"{'Product':<14} | {'Orders':<8} | {'Quantity':<10} | {'Est. Revenue':<14}")
print("-" * 52)
for prod, s in data["sell_loss_by_product"].items():
    print(f"{prod:<14} | {s['total_orders']:<8} | {s['total_qty']:<10} | ${s['total_est_rev']:<12,.2f}")

# 8. Hour Band Distribution
print("\n=== 8. HOUR BAND DISTRIBUTION ===")
print(f"{'Hour Band':<30} | {'Divergences':<12} | {'Percentage':<10}")
print("-" * 56)
for band, cnt in Counter(data["hour_band_counts"]).most_common():
    print(f"{band:<30} | {cnt:<12} | {cnt/tot_div*100:>8.1f}%")
