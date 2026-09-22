#!/usr/bin/env python3
import gzip
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
import simulations.experiments.analyze_p50r_revalidation as ana

DATA_PATH = os.path.join(ROOT, "simulations", "experiments", "results", "p50r_telemetry_100g.json.gz")
with gzip.open(DATA_PATH, "rt", encoding="utf-8") as f:
    games = json.load(f)

# Evaluate refined boundary: Days 21-23 only, 2 carrot cycles, conservative feed safe
game_deltas_raw = []
game_deltas_displaced = []
game_deltas_stressed = []
sub_counts = []

for g in games:
    tile_cands = {}
    for snap in g["wheat_decision_snapshots"]:
        d = snap["day"]
        if 21 <= d <= 23:
            ev = ana.analyze_snapshot(snap)
            if ev["classification"] == "RW3_GENUINE_SURPLUS" and ev["c2_fits"] and ev["task_displaced_delta"] > 0:
                t_key = f"{ev['tile'][0]},{ev['tile'][1]}"
                if t_key not in tile_cands or ev["task_displaced_delta"] > tile_cands[t_key]["task_displaced_delta"]:
                    tile_cands[t_key] = ev

    joint = list(tile_cands.values())
    sub_counts.append(len(joint))
    game_deltas_raw.append(sum(ev["raw_delta"] for ev in joint))
    game_deltas_displaced.append(sum(ev["task_displaced_delta"] for ev in joint))
    game_deltas_stressed.append(sum(ev["labor_stressed_delta"] for ev in joint))

n = len(games)
mean_disp = sum(game_deltas_displaced) / n
var_disp = sum((x - mean_disp) ** 2 for x in game_deltas_displaced) / (n - 1)
std_disp = math.sqrt(var_disp)
s_sorted = sorted(game_deltas_displaced)

print("==================================================================")
print("REFINED T1 DECISION BOUNDARY: Days 21-23, Feed-Safe, 2-Cycle Carrots")
print("==================================================================")
print(f"Total Games Evaluated: {n}")
print(f"Mean Substitutions per Game: {sum(sub_counts)/n:.1f} (Median: {sorted(sub_counts)[n//2]})")
print(f"\nShadow Delta (Raw Crop Economic):")
print(f"  Mean: +${sum(game_deltas_raw)/n:.2f}/game (Median: ${sorted(game_deltas_raw)[n//2]:.2f})")
print(f"\nShadow Delta (Task-Displaced / Primary T1):")
print(f"  Mean:   +${mean_disp:.2f}/game")
print(f"  Median: +${s_sorted[n//2]:.2f}/game")
print(f"  Std:     ${std_disp:.2f}")
print(f"  Min/Max: ${min(game_deltas_displaced):.2f} / ${max(game_deltas_displaced):.2f}")
print(f"  P10/P25/P75/P90: ${s_sorted[int(n*0.10)]:.2f} / ${s_sorted[int(n*0.25)]:.2f} / ${s_sorted[int(n*0.75)]:.2f} / ${s_sorted[int(n*0.90)]:.2f}")
print(f"  Games with >$0 Gain: {sum(1 for x in game_deltas_displaced if x > 0)}% (Mean when active: +${sum(x for x in game_deltas_displaced if x > 0)/sum(1 for x in game_deltas_displaced if x > 0):.2f}/game)")
print(f"\nShadow Delta (Labor Stressed Sensitivity):")
print(f"  Mean: +${sum(game_deltas_stressed)/n:.2f}/game (Median: ${sorted(game_deltas_stressed)[n//2]:.2f})")
print("==================================================================")
