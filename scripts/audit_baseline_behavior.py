"""Audit actual baseline trajectory behavior for storage and labor."""

import json
import os

_REPO_ROOT = r"d:\website project\kaggri ox"
traces_path = os.path.join(_REPO_ROOT, "simulations", "results", "gate1_calibrated_panel", "representative_traces.json")
data = json.load(open(traces_path, "r"))

for k, trace in data.items():
    print(f"\n=== Configuration: {k} (Seed {trace['seed']}, Opp {trace['opponent']}, Seat {trace['seat']}) ===")
    max_shed = 0
    max_workers = 0
    shed_by_day = {}
    sales_by_day = {}
    
    # We can inspect the daily telemetry or step records
    for r in trace["full_step_records"]:
        day = r["day"]
        hour = r["hour"]
        # In shadow mode, we can see snapshot money, etc.
        # But let's check max peak shed and actions reported
        ps = r.get("full_lifecycle_peak_shed", 0)
        if ps > max_shed:
            max_shed = ps
    print(f"Max lifecycle peak shed projected by shadow planner: {max_shed}")
