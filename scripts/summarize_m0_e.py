import json

def load(name):
    with open(f'simulations/results/phase_m0_e_discovery/{name}', 'r') as f:
        return json.load(f)

agg = load('aggregate_tables.json')
clust = load('clustered_statistics.json')
opps = load('deposit_opportunities.json')
sales = load('same_turn_sales.json')
prods = load('product_breakdown.json')
timing = load('cash_timing.json')
stor = load('storage_comparison.json')
mkt = load('market_impact.json')
safe = load('safety_comparison.json')
forensics = load('losing_pair_forensics.json')

print('--- AGGREGATE TABLES ---')
print('C0 cash:', agg['c0_cash_summary'])
print('C1 cash:', agg['c1_cash_summary'])
print('Delta cash:', agg['delta_cash_summary'])
print('Record:', agg['record'])
print('\nBy Opponent:')
for k, v in agg['by_opponent'].items():
    print(f"  {k}: mean_delta={v['mean_delta']:+.2f}, median={v['median_delta']:+.2f} ({v['wins']}W - {v['losses']}L)")
print('\nBy Seat:')
for k, v in agg['by_seat'].items():
    print(f"  {k}: mean_delta={v['mean_delta']:+.2f}, median={v['median_delta']:+.2f} ({v['wins']}W - {v['losses']}L)")

print('\n--- CLUSTERED STATS ---')
c_cash = clust['delta_cash_clustered']
print(f"Mean: {c_cash['mean']:+.2f}, Median: {c_cash['median']:+.2f}, SE: {c_cash['se_clustered']:.2f}")
print(f"95% CI: [{c_cash['ci_95_lower']:+.2f}, {c_cash['ci_95_upper']:+.2f}], Excludes zero: {c_cash['excludes_zero']}")
print("Cluster means per seed:")
for s, m in c_cash['cluster_means'].items():
    print(f"  Seed {s}: {m:+.2f}")

print('\n--- DEPOSIT OPPORTUNITIES & ACCURACY ---')
print(opps)

print('\n--- SAME TURN SALES ---')
print(f"Events: {sales['total_same_turn_sales_events']}, Units: {sales['total_same_turn_units_sold']}, Rev: ${sales['total_same_turn_revenue']:.2f}")

print('\n--- PRODUCTS BREAKDOWN ---')
for p, d in sorted(prods['products'].items()):
    print(f"  {p:12s}: deposited={d['deposited_units']:4d}, sold={d['same_turn_sold_units']:4d}, rev=${d['same_turn_revenue']:10.2f}, rate={d['realization_rate']*100:.1f}%")

print('\n--- STORAGE COMPARISON ---')
print(f"C0 Peak: {stor['c0_peak_shed_occupancy']['mean']:.2f}, C1 Peak: {stor['c1_peak_shed_occupancy']['mean']:.2f}")
print(f"C0 Shed >=90 turns: {stor['c0_turns_shed_ge_90']['mean']:.2f}, C1 Shed >=90 turns: {stor['c1_turns_shed_ge_90']['mean']:.2f}")
print('C0 Discard:', stor['c0_midnight_discards'])
print('C1 Discard:', stor['c1_midnight_discards'])

print('\n--- MARKET IMPACT ---')
print(f"C0 orders emitted: {mkt['c0_orders_emitted']['mean']:.2f}, C1 orders emitted: {mkt['c1_orders_emitted']['mean']:.2f}")
print(f"C0 capped turns total: {mkt['total_capped_turns_c0']}, C1 capped turns total: {mkt['total_capped_turns_c1']}")

print('\n--- SAFETY ---')
print(safe)

print('\n--- LOSING PAIRS (delta < -2000) ---')
print('Count:', forensics['count_delta_lt_2000'])
for inv in forensics['investigations']:
    print(' ', inv)
