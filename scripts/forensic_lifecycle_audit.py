"""Forensic audit of lifecycle failures across representative traces.

Analyzes candidate evaluations where combined_cert_feasible == True and lifecycle_workload_feasible == False.
"""

import json
import os
import sys

_REPO_ROOT = r"d:\website project\kaggri ox"
traces_path = os.path.join(_REPO_ROOT, "simulations", "results", "gate1_calibrated_panel", "representative_traces.json")
data = json.load(open(traces_path, "r"))

failures = []
total_combined_true = 0

for pair_name, trace in data.items():
    seed = trace["seed"]
    opp = trace["opponent"]
    seat = trace["seat"]
    
    for r in trace["full_step_records"]:
        c_feas = r.get("combined_cert_feasible", False)
        l_feas = r.get("lifecycle_workload_feasible", False)
        if not c_feas:
            continue
        total_combined_true += 1
        if l_feas:
            continue
            
        day = r.get("day", 0)
        hour = r.get("hour", 0)
        peak_shed = r.get("full_lifecycle_peak_shed", 0)
        peak_acts = r.get("full_lifecycle_peak_daily_actions", 0)
        port = r.get("selected_portfolio") or {}
        port_name = port.get("name", "none")
        tiles_used = port.get("tiles_used", 0)
        
        # Categorize
        cat = "OTHER"
        if peak_shed > 100:
            cat = "STORAGE_OVERFLOW"
        elif peak_acts > 48:  # 2 workers * 24 or similar
            cat = "LABOR_OVERFLOW"
            
        failures.append({
            "pair": pair_name,
            "seed": seed,
            "opp": opp,
            "seat": seat,
            "day": day,
            "hour": hour,
            "candidate_name": port_name,
            "tiles": tiles_used,
            "peak_shed": peak_shed,
            "peak_acts": peak_acts,
            "delta_fc": r.get("portfolio_delta_fc", 0.0),
            "status": r.get("sw_recommendation_status"),
            "category": cat,
        })

print(f"Total Combined Cert Feasible turns: {total_combined_true}")
print(f"Total Lifecycle Failures among Combined Feasible: {len(failures)} ({len(failures)/total_combined_true*100:.2f}%)")

cat_counts = {}
for f in failures:
    c = f["category"]
    cat_counts[c] = cat_counts.get(c, 0) + 1

print("\nLifecycle Failure Decomposition:")
print(f"{'Category':<20} | {'Count':<8} | {'Percentage':<10}")
print("-" * 45)
for c, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
    print(f"{c:<20} | {cnt:<8} | {cnt/len(failures)*100:.1f}%")

print("\nEarliest Failures (by day):")
earliest = sorted(failures, key=lambda x: (x["day"], x["hour"]))[:5]
for e in earliest:
    print(f"  Day {e['day']} H{e['hour']}: {e['pair']} | port={e['candidate_name']} ({e['tiles']} tiles) | peak_shed={e['peak_shed']}, peak_acts={e['peak_acts']} | cat={e['category']}")

print("\nLatest Failures (by day):")
latest = sorted(failures, key=lambda x: (-x["day"], -x["hour"]))[:5]
for l in latest:
    print(f"  Day {l['day']} H{l['hour']}: {l['pair']} | port={l['candidate_name']} ({l['tiles']} tiles) | peak_shed={l['peak_shed']}, peak_acts={l['peak_acts']} | cat={l['category']}")
