import json

data = json.load(open('simulations/experiments/results/l0_vs_l1_tournament_report.json'))

for opp, info in data['by_opponent'].items():
    print(f"\n==================== {opp} ====================")
    print(f"L1 Mean: ${info['l1_mean_score']:.1f} | L0 Mean: ${info['l0_mean_score']:.1f}")
    print(f"Mean dOur: ${info['mean_delta_our']:.1f} | Median dOur: ${info['median_delta_our']:.1f}")
    print(f"95% CI dOur: [${info['ci_95_delta_our'][0]:.1f}, ${info['ci_95_delta_our'][1]:.1f}]")
    print(f"Mean dMargin: ${info['mean_delta_margin']:.1f} | Median dMargin: ${info['median_delta_margin']:.1f}")
    print(f"Win Rate: L1={info['l1_record']['win_rate']:.1%}, L0={info['l0_record']['win_rate']:.1%}")
    print(f"Purchases L1: {info['avg_purchases']['l1']}")
    print(f"Purchases L0: {info['avg_purchases']['l0']}")
    print(f"Delta Purchases: {info['avg_purchases']['delta']}")

    # Details on individual pairs
    recs = info['paired_records']
    diff_count = 0
    for r in recs:
        if abs(r['d_our']) > 100:
            diff_count += 1
            print(f"  Seed {r['seed']} Seat {r['seat']}: dOur={r['d_our']:+.0f}, dMargin={r['d_margin']:+.0f} | L1:{r['l1_purchases']} vs L0:{r['l0_purchases']} | Wheat L1:{r['l1_wheat_bought']} L0:{r['l0_wheat_bought']}")
    print(f"Pairs with divergence: {diff_count}/{len(recs)}")
