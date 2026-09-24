"""Analyze lifecycle failures in calibrated diagnostic panel."""

import json
import os
import sys

_REPO_ROOT = r"d:\website project\kaggri ox"
traces_path = os.path.join(_REPO_ROOT, "simulations", "results", "gate1_calibrated_panel", "representative_traces.json")
data = json.load(open(traces_path, "r"))

total_records = 0
comb_true = 0
comb_true_lc_false = 0
peak_sheds = []
peak_acts = []

records_sample = []

for k, trace in data.items():
    seed = trace["seed"]
    opp = trace["opponent"]
    seat = trace["seat"]
    for r in trace["full_step_records"]:
        total_records += 1
        c_feas = r.get("combined_cert_feasible", False)
        l_feas = r.get("lifecycle_workload_feasible", False)
        if c_feas:
            comb_true += 1
            if not l_feas:
                comb_true_lc_false += 1
                peak_sheds.append(r.get("full_lifecycle_peak_shed", 0))
                peak_acts.append(r.get("full_lifecycle_peak_daily_actions", 0))
                if len(records_sample) < 20:
                    records_sample.append({
                        "pair": k,
                        "seed": seed,
                        "opp": opp,
                        "seat": seat,
                        "day": r["day"],
                        "hour": r["hour"],
                        "peak_shed": r.get("full_lifecycle_peak_shed"),
                        "peak_actions": r.get("full_lifecycle_peak_daily_actions"),
                        "status": r.get("sw_recommendation_status"),
                        "portfolio": r.get("selected_portfolio"),
                        "delta_fc": r.get("portfolio_delta_fc"),
                        "binding": r.get("binding_resource"),
                    })

print(f"Total step records: {total_records}")
print(f"Combined cert feasible == True: {comb_true} ({comb_true/total_records*100:.2f}%)")
print(f"Combined cert True BUT Lifecycle feasible False: {comb_true_lc_false} ({comb_true_lc_false/comb_true*100:.2f}% of combined true)")
print(f"Peak shed distribution in failure: min={min(peak_sheds) if peak_sheds else 0}, max={max(peak_sheds) if peak_sheds else 0}, >100 count={sum(1 for s in peak_sheds if s > 100)}")
print(f"Peak actions distribution in failure: min={min(peak_acts) if peak_acts else 0}, max={max(peak_acts) if peak_acts else 0}")
print("\nSample records:")
for s in records_sample[:10]:
    print(s)
