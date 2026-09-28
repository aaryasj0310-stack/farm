import json
import numpy as np

with open('simulations/results/phase_sw_c1/sw_c1_matches_discovery.json') as f:
    disc = json.load(f)
with open('simulations/results/phase_sw_c1/sw_c1_matches_confirmation.json') as f:
    conf = json.load(f)

all_matches = disc + conf
arms = ['ARM_A', 'ARM_B', 'ARM_C', 'ARM_D', 'ARM_E', 'ARM_F', 'ARM_G']
arm_dict = {a: [] for a in arms}

for m in all_matches:
    arm_dict[m['arm']].append(m)

print("=== DETAILED FINANCIAL WATERFALL (POOLED 40 MATCHES PER ARM) ===")
print(f"{'Category':<32} " + " ".join([f"{a:>12}" for a in arms]))

categories = [
    ("Final Cash", lambda m: m['final_cash']),
    ("Total Crop Rev", lambda m: sum(m['cash_ledger']['crop_sales_rev'].values())),
    ("  Core Crop Rev", lambda m: m['core_crop_revenue']),
    ("  SW Crop Rev", lambda m: m['sw_total_crop_revenue']),
    ("Total Livestock Rev", lambda m: sum(m['cash_ledger']['animal_sales_rev'].values())),
    ("Seed Costs", lambda m: sum(m['cash_ledger']['seed_purchases_cost'].values())),
    ("  SW Seed Costs", lambda m: m['sw_total_seed_cost']),
    ("Animal Purchase Costs", lambda m: sum(m['cash_ledger']['animal_purchases_cost'].values())),
    ("Feed Costs", lambda m: m['cash_ledger']['feed_purchases_cost']),
    ("Fertilizer Costs", lambda m: m['cash_ledger']['fertilizer_purchases_cost']),
    ("Hiring Costs", lambda m: m['cash_ledger']['hiring_costs']),
    ("Wages Paid", lambda m: m['cash_ledger']['wages_paid']),
    ("Land Purchase Costs", lambda m: m['cash_ledger']['land_purchases_cost']),
]

for label, func in categories:
    vals = [f"{np.mean([func(m) for m in arm_dict[a]]):12.2f}" for a in arms]
    print(f"{label:<32} " + " ".join(vals))

print("\n=== LABOR ALLOCATION & ACTION TELEMETRY (MEAN PER MATCH) ===")
labor_metrics = [
    ("Total Actions", lambda m: m['action_counts']['total_actions']),
    ("Actions in Core", lambda m: m['action_counts']['actions_in_core']),
    ("Actions in SW", lambda m: m['action_counts']['actions_in_sw']),
    ("Move Actions", lambda m: m['action_counts']['move_actions']),
    ("Quadrant Crossings NW<->SW", lambda m: m['action_counts']['quadrant_transitions_nw_to_sw'] + m['action_counts']['quadrant_transitions_sw_to_nw']),
    ("Core Water Executed", lambda m: m['action_counts']['core_water_executed']),
    ("SW Water Executed", lambda m: m['action_counts']['sw_water_executed']),
    ("Core Harvest Executed", lambda m: m['action_counts']['core_harvest_executed']),
    ("SW Harvest Executed", lambda m: m['action_counts']['sw_harvest_executed']),
    ("Feed Actions (Livestock)", lambda m: m['action_counts']['feed_actions']),
    ("Care Actions (Livestock)", lambda m: m['action_counts']['care_actions']),
    ("Idle Actions", lambda m: m['action_counts']['idle_actions']),
]

for label, func in labor_metrics:
    vals = [f"{np.mean([func(m) for m in arm_dict[a]]):12.1f}" for a in arms]
    print(f"{label:<32} " + " ".join(vals))
