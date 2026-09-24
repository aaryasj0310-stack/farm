"""Sample and manually audit representative failures from Gate 1 traces."""

import json
import os
import sys

_REPO_ROOT = r"d:\website project\kaggri ox"
_TRACES_PATH = os.path.join(_REPO_ROOT, "simulations", "results", "gate1_shadow_audit", "representative_traces.json")
_RESULTS_PATH = os.path.join(_REPO_ROOT, "simulations", "results", "gate1_shadow_audit", "results.json")

with open(_TRACES_PATH, "r") as f:
    traces = json.load(f)

with open(_RESULTS_PATH, "r") as f:
    results = json.load(f)

# Extract records across traces
all_records = []
for trace_name, trace_data in traces.items():
    pid = trace_data["pair_id"]
    opp = trace_data["opponent"]
    seat = trace_data["seat"]
    seed = trace_data["seed"]
    for r in trace_data["full_step_records"]:
        r["pair_id"] = pid
        r["opponent"] = opp
        r["seat"] = seat
        r["seed"] = seed
        all_records.append(r)

# Filter for core_only_cert_feasible == False
core_infeasible = [r for r in all_records if not r.get("core_only_cert_feasible", True)]
print(f"Total records: {len(all_records)}, Core infeasible records: {len(core_infeasible)}")

# 1. 10 largest negative-slack failures
sorted_by_neg_slack = sorted(core_infeasible, key=lambda r: r.get("cert_min_slack", 0))
largest_neg = sorted_by_neg_slack[:10]

# 2. 10 failures with slack just below zero (-1, -2, -3)
near_zero = [r for r in core_infeasible if -5 <= r.get("cert_min_slack", 0) < 0][:10]

# 3. 10 early-game failures (Day 0 - 3)
early_game = [r for r in core_infeasible if r["day"] <= 3][:10]

# 4. 10 mid-game failures (Day 4 - 8)
mid_game = [r for r in core_infeasible if 4 <= r["day"] <= 8][:10]

# 5. Strongly positive delta_fc but vetoed (delta_fc >= 3000, status in DELAY/DOWNSIZE/REJECT)
strong_delta_vetoed = [r for r in core_infeasible if r.get("portfolio_delta_fc", 0) >= 3000][:10]

# 6. Downsized recommendations
downsized = [r for r in core_infeasible if r.get("sw_recommendation_status") == "DOWNSIZE"][:10]

print("\n--- SAMPLE 1: LARGEST NEGATIVE SLACK ---")
for r in largest_neg:
    print(f"Pair {r['pair_id']} Seed {r['seed']} D{r['day']} H{r['hour']:02d} | slack={r.get('cert_min_slack')} | bind_res={r['binding_resource']} | status={r['sw_recommendation_status']}")

print("\n--- SAMPLE 2: SLACK JUST BELOW ZERO (-1 to -5) ---")
for r in near_zero:
    print(f"Pair {r['pair_id']} Seed {r['seed']} D{r['day']} H{r['hour']:02d} | slack={r.get('cert_min_slack')} | bind_res={r['binding_resource']} | status={r['sw_recommendation_status']}")

print("\n--- SAMPLE 3: EARLY-GAME (D0-D3) ---")
for r in early_game:
    print(f"Pair {r['pair_id']} Seed {r['seed']} D{r['day']} H{r['hour']:02d} | slack={r.get('cert_min_slack')} | bind_res={r['binding_resource']} | status={r['sw_recommendation_status']}")

print("\n--- SAMPLE 4: MID-GAME (D4-D8, PRE/POST SW PURCHASE) ---")
for r in mid_game:
    print(f"Pair {r['pair_id']} Seed {r['seed']} D{r['day']} H{r['hour']:02d} | slack={r.get('cert_min_slack')} | delta_fc={r.get('portfolio_delta_fc')} | status={r['sw_recommendation_status']}")

print("\n--- SAMPLE 5: HIGH DELTA_FC VETOED ---")
for r in strong_delta_vetoed:
    print(f"Pair {r['pair_id']} Seed {r['seed']} D{r['day']} H{r['hour']:02d} | delta_fc=${r.get('portfolio_delta_fc'):,.1f} | slack={r.get('cert_min_slack')} | status={r['sw_recommendation_status']}")

print("\n--- SAMPLE 6: DOWNSIZED ---")
for r in downsized:
    print(f"Pair {r['pair_id']} Seed {r['seed']} D{r['day']} H{r['hour']:02d} | delta_fc=${r.get('portfolio_delta_fc'):,.1f} | slack={r.get('cert_min_slack')} | status={r['sw_recommendation_status']}")
