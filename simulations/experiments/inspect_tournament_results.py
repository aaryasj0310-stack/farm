import json

with open('simulations/experiments/results/livestock_tournament_results.json', encoding='utf-8') as f:
    d = json.load(f)

a = d['analysis']
print('=== ARM SUMMARIES ===')
for arm, s in a['arm_summaries'].items():
    print(f"{arm} -> Mean: {s['score_mean']}, Med: {s['score_median']}, Std: {s['score_std']}, Min: {s['score_min']}, Max: {s['score_max']}")
    print(f"  Cows: {s['cows_bought_mean']}, Sheep: {s['sheep_bought_mean']}, Geese: {s['geese_bought_mean']}, Peak Herd: {s['peak_herd_mean']}")
    print(f"  Cow buy day: {s.get('mean_cow_buy_day')}, Sheep buy day: {s.get('mean_sheep_buy_day')}")
    print(f"  Milk Rev: {s['mean_milk_rev']}, Wool Rev: {s['mean_wool_rev']}, Fert Rev: {s['mean_fert_rev']}, Crop Rev: {s['mean_crop_rev']}")
    print(f"  Animal Spend: {s['mean_animal_spend']}, Feed Spend: {s['mean_feed_spend']}, Net Livestock Contrib: {s['mean_net_livestock_contrib']}")
    print(f"  Unfed Days: {s['total_unfed_animal_days']}, Mean Unfed: {s['mean_unfed_animal_days']}, CUnfed>=2: {s['total_consecutive_unfed_ge2']}, Escapes: {s['total_animal_escapes']}, Late Viols: {s['total_late_purchase_violations']}")

print('\n=== CONTRASTS ===')
for name, c in a['contrasts'].items():
    print(f"{name} ({c['description']}):")
    print(f"  Mean Delta: {c['mean_delta']}, Med Delta: {c['median_delta']}, Std: {c['std_delta']}")
    print(f"  95% Bootstrap CI: [{c['bootstrap_95_ci'][0]}, {c['bootstrap_95_ci'][1]}]")
    print(f"  t-stat: {c['t_statistic']}, p-val (ttest): {c['p_value_ttest']:.6f}")
    print(f"  Wilcoxon w: {c['w_statistic']}, p-val (wilcoxon): {c['p_value_wilcoxon']:.6f}")
    print(f"  Win Rate: {c['win_rate']*100:.1f}% (Wins: {c['wins']}, Ties: {c['ties']}, Losses: {c['losses']})")
    print(f"  P10 Delta: {c['p10_delta']}, P90 Delta: {c['p90_delta']}, CVaR 10%: {c['cvar_10']}")
    print("  Worst 5 deltas:")
    for w in c['worst_5_deltas']:
        print(f"    Seed {w['seed']}: Delta={w['delta']} (T={w['treatment_score']}, C={w['control_score']}, Yarn={w['yarn_stores']}, MilkShops={w['milk_shops']})")

print('\n=== SHOP-CONDITIONED BEHAVIOR ===')
for arm, s_dict in a['shop_analysis'].items():
    print(f"{arm}:")
    y0 = s_dict['yarn_0']
    y1 = s_dict['yarn_ge1']
    print(f"  Yarn Store == 0 (N={y0['count']}): Score={y0['mean_score']}, Sheep={y0['mean_sheep_bought']}, WoolRev={y0['mean_wool_rev']}")
    print(f"  Yarn Store >= 1 (N={y1['count']}): Score={y1['mean_score']}, Sheep={y1['mean_sheep_bought']}, WoolRev={y1['mean_wool_rev']}")
    m0 = s_dict['milk_0']
    m2 = s_dict['milk_ge2']
    print(f"  Milk Shops == 0 (N={m0['count']}): Cows={m0['mean_cows_bought']}, MilkRev={m0['mean_milk_rev']}")
    print(f"  Milk Shops >= 2 (N={m2['count']}): Cows={m2['mean_cows_bought']}, MilkRev={m2['mean_milk_rev']}")

print('\n=== ARM C DEVIATIONS ===')
print(f"Arm C Deviation Rate vs Arm A: {a['arm_c_deviation_rate']*100:.1f}%")
deviated_seeds = [d for d in a['arm_c_deviations'] if d['deviated']]
print(f"Total deviated matches: {len(deviated_seeds)} / {len(a['arm_c_deviations'])}")
print("Sample deviations:")
for d_item in deviated_seeds[:8]:
    print(f"  Seed {d_item['seed']}: Arm C Herd (C,S,G)={d_item['arm_c_herd']} vs Arm A={d_item['arm_a_herd']}, Delta={d_item['delta']:.2f}")

print('\n=== FERTILIZER SENSITIVITY AUDIT ===')
fert = d.get('fertilizer_sensitivity_audit', {})
for tier, res in fert.items():
    print(f"  {tier}: COW={res['COW']}, SHEEP={res['SHEEP']}, GOOSE={res['GOOSE']}, Preferred={res['preferred']}, Cow-Sheep={res['cow_minus_sheep']}")

print('\n=== VERDICT ===')
print(f"Verdict: {a['verdict']}")
print(f"Rationale: {a['verdict_rationale']}")
