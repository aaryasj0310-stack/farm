import json
import numpy as np

def main():
    with open('simulations/experiments/land_affordability_ab_results.json', 'r') as f:
        raw = json.load(f)

    # Pair up matches by (seed, opponent)
    pairs = {}
    for r in raw:
        key = (r['seed'], r['opponent'])
        if key not in pairs:
            pairs[key] = {}
        pairs[key][r['arm']] = r

    print(f"Total valid paired scenarios: {len(pairs)}")

    deltas = []
    scores_a = []
    scores_b = []
    wins = 0
    losses = 0
    ties = 0

    ne_buys_a = 0
    ne_buys_b = 0
    sw_buys_a = 0
    sw_buys_b = 0

    ne_days_a = []
    ne_days_b = []
    sw_days_a = []
    sw_days_b = []

    ne_cash_a = []
    ne_cash_b = []
    sw_cash_a = []
    sw_cash_b = []

    prod_ne_a = []
    prod_ne_b = []
    idle_ne_a = []
    idle_ne_b = []

    prod_sw_a = []
    prod_sw_b = []
    idle_sw_a = []
    idle_sw_b = []

    starv_a = 0
    starv_b = 0

    reasons_a = {}
    reasons_b = {}

    improved_pairs = []
    regressed_pairs = []

    for key, p in pairs.items():
        a = p['ArmA_Baseline']
        b = p['ArmB_Candidate']
        
        sa = a['final_score']
        sb = b['final_score']
        delta = sb - sa
        
        scores_a.append(sa)
        scores_b.append(sb)
        deltas.append(delta)
        
        if delta > 1e-6:
            wins += 1
            improved_pairs.append((key, sa, sb, delta))
        elif delta < -1e-6:
            losses += 1
            regressed_pairs.append((key, sa, sb, delta))
        else:
            ties += 1
            
        if a.get('ne_purchased'):
            ne_buys_a += 1
            ne_days_a.append(a['ne_day'])
            if a['ne_cash_after'] is not None: ne_cash_a.append(a['ne_cash_after'])
        if b.get('ne_purchased'):
            ne_buys_b += 1
            ne_days_b.append(b['ne_day'])
            if b['ne_cash_after'] is not None: ne_cash_b.append(b['ne_cash_after'])
            
        if a.get('sw_purchased'):
            sw_buys_a += 1
            sw_days_a.append(a['sw_day'])
            if a['sw_cash_after'] is not None: sw_cash_a.append(a['sw_cash_after'])
        if b.get('sw_purchased'):
            sw_buys_b += 1
            sw_days_b.append(b['sw_day'])
            if b['sw_cash_after'] is not None: sw_cash_b.append(b['sw_cash_after'])

        prod_ne_a.append(a['productive_tile_days_ne'])
        prod_ne_b.append(b['productive_tile_days_ne'])
        idle_ne_a.append(a['idle_tile_days_ne'])
        idle_ne_b.append(b['idle_tile_days_ne'])

        prod_sw_a.append(a['productive_tile_days_sw'])
        prod_sw_b.append(b['productive_tile_days_sw'])
        idle_sw_a.append(a['idle_tile_days_sw'])
        idle_sw_b.append(b['idle_tile_days_sw'])

        starv_a += a['safety_metrics']['animal_starvations']
        starv_b += b['safety_metrics']['animal_starvations']

        for d, diag in a.get('land_diagnostics', {}).items():
            r = diag.get('final_rejection_or_acceptance_reason', 'unknown')
            reasons_a[r] = reasons_a.get(r, 0) + 1

        for d, diag in b.get('land_diagnostics', {}).items():
            r = diag.get('final_rejection_or_acceptance_reason', 'unknown')
            reasons_b[r] = reasons_b.get(r, 0) + 1

    print("======================================================================")
    print("                    A/B BENCHMARK PERFORMANCE REPORT                  ")
    print("======================================================================")
    print(f"Sample:               50 paired deterministic scenarios (seeds 101-125)")
    print(f"                      25 vs starter, 25 vs random (100 matches total)")
    print(f"Arm A Baseline:       Commit 0389470 (Gross feed, coupled animal cost)")
    print(f"Arm B Candidate:      Land Affordability Fix (Time-aware, decoupled)")
    print("----------------------------------------------------------------------")
    print(f"Arm A Mean Score:     ${np.mean(scores_a):,.2f}")
    print(f"Arm B Mean Score:     ${np.mean(scores_b):,.2f}")
    print(f"Mean Score Delta:     ${np.mean(deltas):+,.2f}")
    print(f"Median Delta:         ${np.median(deltas):+,.2f}")
    print(f"Std Delta:            ${np.std(deltas):,.2f}")
    print(f"P10 Delta:            ${np.percentile(deltas, 10):+,.2f}")
    print(f"Max Paired Delta:     ${np.max(deltas):+,.2f}")
    print(f"Min Paired Delta:     ${np.min(deltas):+,.2f}")
    print(f"Paired Record:        {wins} Wins / {losses} Losses / {ties} Ties ({wins/len(pairs)*100:.1f}% win rate)")
    print("----------------------------------------------------------------------")
    print("LAND ACQUISITION METRICS:")
    print(f"  NE Purchase Rate:   Arm A: {ne_buys_a}/50 ({ne_buys_a/50*100:.1f}%) | Arm B: {ne_buys_b}/50 ({ne_buys_b/50*100:.1f}%)")
    if ne_days_a and ne_days_b:
        print(f"  NE Mean Unlock Day: Arm A: {np.mean(ne_days_a):.2f} | Arm B: {np.mean(ne_days_b):.2f}")
    if ne_cash_a and ne_cash_b:
        print(f"  NE Mean Post-Cash:  Arm A: ${np.mean(ne_cash_a):,.2f} | Arm B: ${np.mean(ne_cash_b):,.2f}")

    print(f"  SW Purchase Rate:   Arm A: {sw_buys_a}/50 ({sw_buys_a/50*100:.1f}%) | Arm B: {sw_buys_b}/50 ({sw_buys_b/50*100:.1f}%)")
    if sw_days_b:
        mean_sw_a = f"{np.mean(sw_days_a):.2f}" if sw_days_a else "N/A (0 bought)"
        print(f"  SW Mean Unlock Day: Arm A: {mean_sw_a} | Arm B: {np.mean(sw_days_b):.2f}")
    if sw_cash_b:
        mean_cash_sw_a = f"${np.mean(sw_cash_a):,.2f}" if sw_cash_a else "N/A"
        print(f"  SW Mean Post-Cash:  Arm A: {mean_cash_sw_a} | Arm B: ${np.mean(sw_cash_b):,.2f}")
    print("----------------------------------------------------------------------")
    print("LAND UTILIZATION METRICS (Tile-Days per match):")
    print(f"  NE Productive Days: Arm A: {np.mean(prod_ne_a):.1f} | Arm B: {np.mean(prod_ne_b):.1f}")
    print(f"  NE Idle Days:       Arm A: {np.mean(idle_ne_a):.1f} | Arm B: {np.mean(idle_ne_b):.1f}")
    print(f"  SW Productive Days: Arm A: {np.mean(prod_sw_a):.1f} | Arm B: {np.mean(prod_sw_b):.1f}")
    print(f"  SW Idle Days:       Arm A: {np.mean(idle_sw_a):.1f} | Arm B: {np.mean(idle_sw_b):.1f}")
    print("----------------------------------------------------------------------")
    print("SAFETY METRICS:")
    print(f"  Animal Starvations: Arm A: {starv_a} | Arm B: {starv_b} (Target: 0)")
    print("======================================================================")

    # Sub-breakdown by opponent
    for opp in ["starter", "random"]:
        sub_scores_a = [p['ArmA_Baseline']['final_score'] for k, p in pairs.items() if k[1] == opp]
        sub_scores_b = [p['ArmB_Candidate']['final_score'] for k, p in pairs.items() if k[1] == opp]
        sub_deltas = [b - a for a, b in zip(sub_scores_a, sub_scores_b)]
        sub_w = sum(1 for d in sub_deltas if d > 1e-6)
        sub_l = sum(1 for d in sub_deltas if d < -1e-6)
        sub_t = sum(1 for d in sub_deltas if abs(d) <= 1e-6)
        print(f"Subgroup vs '{opp}': Mean Delta: ${np.mean(sub_deltas):+,.2f} | Record: {sub_w}W / {sub_l}L / {sub_t}T")

if __name__ == '__main__':
    main()
