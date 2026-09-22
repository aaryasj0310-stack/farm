"""
Analyze P6.1-C Causal Reconciliation Output
Reads p61c_causal_reconciliation_summary.json and p61c_causal_reconciliation_telemetry.json.gz
Computes all statistical breakdowns, waterfall ledgers, timing curves, opponent tables, and mechanism diagnostics.
"""

import os
import json
import gzip
import numpy as np

SUMMARY_FILE = "simulations/experiments/p61c_causal_reconciliation_summary.json"
TELEMETRY_FILE = "simulations/experiments/p61c_causal_reconciliation_telemetry.json.gz"

def main():
    if not os.path.exists(SUMMARY_FILE):
        print(f"Summary file not found: {SUMMARY_FILE}")
        return

    print("Loading summary...")
    with open(SUMMARY_FILE, "r") as f:
        summary = json.load(f)

    print("Loading telemetry...")
    with gzip.open(TELEMETRY_FILE, "rt") as f:
        telemetry = json.load(f)

    n_pairs = len(telemetry)
    print(f"Loaded {n_pairs} scenario pairs.")

    ctrl_final_cash = []
    treat_final_cash = []
    deltas = []
    residuals = []

    products = ["CARROT", "TOMATO", "MELON", "STRAWBERRY", "EGG", "MILK", "WOOL", "FERTILIZER", "WHEAT"]

    # Inflows (Sales)
    ctrl_sales_rev = {p: [] for p in products}
    treat_sales_rev = {p: [] for p in products}
    ctrl_sales_qty = {p: [] for p in products}
    treat_sales_qty = {p: [] for p in products}

    # Expenditures
    ctrl_feed_spent = []
    treat_feed_spent = []
    ctrl_seed_spent = []
    treat_seed_spent = []
    ctrl_anim_spent = []
    treat_anim_spent = []
    ctrl_hire_spent = []
    treat_hire_spent = []
    ctrl_land_spent = []
    treat_land_spent = []
    ctrl_fert_spent = []
    treat_fert_spent = []

    ctrl_discards = []
    treat_discards = []

    pair_records = []

    for item in telemetry:
        c = item['control']
        t = item['treatment']
        seed = item['seed']
        opp = item['opponent']
        seat = item['seat']

        d_cash = item['cash_delta']
        deltas.append(d_cash)
        ctrl_final_cash.append(c['final_money'])
        treat_final_cash.append(t['final_money'])
        residuals.append(item['closure_residual'])

        ctrl_discards.append(c['total_discard_units'])
        treat_discards.append(t['total_discard_units'])

        c_led = c['cash_ledger']
        t_led = t['cash_ledger']

        for p in products:
            ctrl_sales_rev[p].append(c_led['sales_revenue_by_prod'].get(p, 0.0))
            treat_sales_rev[p].append(t_led['sales_revenue_by_prod'].get(p, 0.0))
            ctrl_sales_qty[p].append(c_led['sales_units_by_prod'].get(p, 0.0))
            treat_sales_qty[p].append(t_led['sales_units_by_prod'].get(p, 0.0))

        ctrl_feed_spent.append(c_led['feed_wheat_cost'])
        treat_feed_spent.append(t_led['feed_wheat_cost'])

        ctrl_seed_spent.append(c_led['seed_buy_cost'])
        treat_seed_spent.append(t_led['seed_buy_cost'])

        ctrl_anim_spent.append(c_led['animal_buy_cost'])
        treat_anim_spent.append(t_led['animal_buy_cost'])

        ctrl_hire_spent.append(c_led['hire_cost'])
        treat_hire_spent.append(t_led['hire_cost'])

        ctrl_land_spent.append(c_led['land_cost'])
        treat_land_spent.append(t_led['land_cost'])

        ctrl_fert_spent.append(c_led['fert_buy_cost'])
        treat_fert_spent.append(t_led['fert_buy_cost'])

        pair_records.append({
            'scenario': f"s{seed}_{opp}_seat{seat}",
            'opponent': opp,
            'seed': seed,
            'seat': seat,
            'd_cash': d_cash,
            'c_cash': c['final_money'],
            't_cash': t['final_money'],
            'd_discard': item['discard_delta'],
            'c_discard': c['total_discard_units'],
            't_discard': t['total_discard_units'],
            'd_sales': item['total_sales_delta'],
            'd_exp': item['total_expenditure_delta'],
            'early_pur_count': len(item.get('treat_only_purchases', [])),
            'first_div': item['first_divergence_hour'],
            'max_adv': item['max_liquidity_advantage'],
            'hours_t_ahead': item['hours_treatment_ahead'],
        })

    deltas = np.array(deltas)
    mean_delta = np.mean(deltas)
    median_delta = np.median(deltas)
    lower_p = np.percentile(deltas, 10)
    upper_p = np.percentile(deltas, 90)
    trimmed_deltas = deltas[(deltas >= lower_p) & (deltas <= upper_p)]
    trimmed_mean = np.mean(trimmed_deltas)

    print("="*70)
    print("SUMMARY METRICS")
    print("="*70)
    print(f"Total scenario pairs: {n_pairs}")
    print(f"Max Cash Reconciliation Residual: {max(residuals):.6f}")
    print(f"Control Mean Cash:   ${np.mean(ctrl_final_cash):,.2f}")
    print(f"Treatment Mean Cash: ${np.mean(treat_final_cash):,.2f}")
    print(f"Mean Cash Delta:     ${mean_delta:+,.2f}")
    print(f"Median Cash Delta:   ${median_delta:+,.2f}")
    print(f"10% Trimmed Mean:    ${trimmed_mean:+,.2f}")
    print(f"Control Mean Discards:   {np.mean(ctrl_discards):.2f} units")
    print(f"Treatment Mean Discards: {np.mean(treat_discards):.2f} units")
    print(f"Mean Discard Delta:      {np.mean(treat_discards) - np.mean(ctrl_discards):+.2f} units ({(np.mean(treat_discards)-np.mean(ctrl_discards))/np.mean(ctrl_discards)*100:+.2f}%)")

    wins = np.sum(deltas > 0)
    losses = np.sum(deltas < 0)
    ties = np.sum(deltas == 0)
    print(f"Treatment Wins: {wins}/{n_pairs} ({wins/n_pairs*100:.1f}%), Losses: {losses}, Ties: {ties}")

    print("\n" + "="*70)
    print("EXACT CASH WATERFALL RECONCILIATION (Per-Game Mean)")
    print("="*70)
    print("--- INFLOWS (SALES REVENUE) ---")
    tot_ctrl_rev = 0.0
    tot_treat_rev = 0.0
    for p in products:
        c_r = np.mean(ctrl_sales_rev[p])
        t_r = np.mean(treat_sales_rev[p])
        d_r = t_r - c_r
        c_q = np.mean(ctrl_sales_qty[p])
        t_q = np.mean(treat_sales_qty[p])
        d_q = t_q - c_q
        tot_ctrl_rev += c_r
        tot_treat_rev += t_r
        print(f"  {p:<12}: Ctrl ${c_r:9.2f} ({c_q:5.2f}u) | Treat ${t_r:9.2f} ({t_q:5.2f}u) | Delta ${d_r:+9.2f} ({d_q:+5.2f}u)")
    d_tot_rev = tot_treat_rev - tot_ctrl_rev
    print(f"TOTAL REVENUE DELTA: ${d_tot_rev:+,.2f}")

    print("\n--- OUTFLOWS (EXPENDITURES) ---")
    tot_ctrl_exp = 0.0
    tot_treat_exp = 0.0

    exp_cats = [
        ("Feed Wheat", ctrl_feed_spent, treat_feed_spent),
        ("Seed Purchases", ctrl_seed_spent, treat_seed_spent),
        ("Animal Purchases", ctrl_anim_spent, treat_anim_spent),
        ("Worker Wages", ctrl_hire_spent, treat_hire_spent),
        ("Land Expansion", ctrl_land_spent, treat_land_spent),
        ("Fertilizer Buy", ctrl_fert_spent, treat_fert_spent),
    ]

    for name, c_list, t_list in exp_cats:
        c_m = np.mean(c_list)
        t_m = np.mean(t_list)
        d_m = t_m - c_m
        tot_ctrl_exp += c_m
        tot_treat_exp += t_m
        print(f"  {name:<16}: Ctrl ${c_m:9.2f} | Treat ${t_m:9.2f} | Delta ${d_m:+9.2f} (Savings: ${-d_m:+9.2f})")

    d_tot_exp = tot_treat_exp - tot_ctrl_exp
    print(f"TOTAL EXPENDITURE DELTA: ${d_tot_exp:+,.2f} (Total Savings: ${-d_tot_exp:+,.2f})")

    net_delta = d_tot_rev - d_tot_exp
    print(f"\nNET CASH DELTA (Rev Delta - Exp Delta): ${net_delta:+,.2f}")
    print(f"ACTUAL MEAN CASH DELTA               : ${mean_delta:+,.2f}")
    print(f"EXACT ACCOUNTING DISCREPANCY          : ${net_delta - mean_delta:.6f}")

    print("\n" + "="*70)
    print("OUTLIER DECOMPOSITION")
    print("="*70)
    sorted_pairs = sorted(pair_records, key=lambda x: x['d_cash'], reverse=True)
    total_gain = np.sum(deltas)
    print(f"Total aggregate cash delta across 100 pairs: ${total_gain:+,.2f}")
    top1 = sorted_pairs[0]
    top5_sum = sum(x['d_cash'] for x in sorted_pairs[:5])
    top10_sum = sum(x['d_cash'] for x in sorted_pairs[:10])
    bot5_sum = sum(x['d_cash'] for x in sorted_pairs[-5:])
    print(f"Top 1 pair : {top1['scenario']} delta=${top1['d_cash']:+,.2f} ({top1['d_cash']/total_gain*100:.1f}% of total gain)")
    print(f"Top 5 pairs: sum=${top5_sum:+,.2f} ({top5_sum/total_gain*100:.1f}% of total gain)")
    print(f"Top 10 pairs: sum=${top10_sum:+,.2f} ({top10_sum/total_gain*100:.1f}% of total gain)")
    print(f"Bottom 5 pairs: sum=${bot5_sum:+,.2f} ({bot5_sum/total_gain*100:.1f}% of total gain)")

    print("\nTop 5 pairs detail:")
    for i, p in enumerate(sorted_pairs[:5], 1):
        print(f"  #{i}: {p['scenario']} dCash=${p['d_cash']:+,.2f}, dDisc={p['d_discard']:+.1f}, dSales=${p['d_sales']:+,.2f}, dExp=${p['d_exp']:+,.2f}")

    print("\nBottom 5 pairs detail:")
    for i, p in enumerate(sorted_pairs[-5:], 1):
        print(f"  #{i}: {p['scenario']} dCash=${p['d_cash']:+,.2f}, dDisc={p['d_discard']:+.1f}, dSales=${p['d_sales']:+,.2f}, dExp=${p['d_exp']:+,.2f}")

    print("\n" + "="*70)
    print("OPPONENT HETEROGENEITY")
    print("="*70)
    opponents = ['pure_wheat_rush', 'pass', 'melon_sniper', 'cow_milk_engine', 'full_production_agent']
    for opp in opponents:
        sub = [p for p in pair_records if p['opponent'] == opp]
        sub_d = [p['d_cash'] for p in sub]
        sub_disc = [p['d_discard'] for p in sub]
        sub_sales = [p['d_sales'] for p in sub]
        sub_exp = [p['d_exp'] for p in sub]
        sub_wins = sum(1 for p in sub if p['d_cash'] > 0)
        print(f"Opponent: {opp:<22} | Pairs: {len(sub)} | Mean dCash: ${np.mean(sub_d):+9.2f} | Med: ${np.median(sub_d):+9.2f} | WinRate: {sub_wins}/{len(sub)} ({sub_wins/len(sub)*100:4.1f}%) | dSales: ${np.mean(sub_sales):+8.2f} | dExp: ${np.mean(sub_exp):+8.2f} | dDisc: {np.mean(sub_disc):+5.2f}")

    print("\n" + "="*70)
    print("FULL PRODUCTION AGENT DEEP DIVE")
    print("="*70)
    fpa_pairs = [p for p in pair_records if p['opponent'] == 'full_production_agent']
    print(f"Full Production Agent: {len(fpa_pairs)} pairs")
    for p in fpa_pairs:
        print(f"  {p['scenario']}: dCash=${p['d_cash']:+9.2f} | dSales=${p['d_sales']:+9.2f} | dExp=${p['d_exp']:+9.2f} | dDisc={p['d_discard']:+5.1f}")

    print("\n" + "="*70)
    print("HOURLY LIQUIDITY TIMING TRAJECTORY")
    print("="*70)
    all_ctrl_trajectories = np.array([item['control']['hourly_cash'] for item in telemetry])
    all_treat_trajectories = np.array([item['treatment']['hourly_cash'] for item in telemetry])
    diff_matrix = all_treat_trajectories - all_ctrl_trajectories
    mean_diff = np.mean(diff_matrix, axis=0)

    # First divergence
    first_div_hours = [p['first_div'] for p in pair_records if p['first_div'] is not None]
    print(f"First divergence hour across pairs: min={min(first_div_hours)}, max={max(first_div_hours)}, mean={np.mean(first_div_hours):.1f}")
    max_hour = int(np.argmax(mean_diff))
    print(f"Peak mean liquidity advantage: Hour {max_hour} (Day {max_hour//24}, Hour {max_hour%24}) at ${mean_diff[max_hour]:+,.2f}")
    print(f"Final hour (719) mean advantage: ${mean_diff[719]:+,.2f}")

    print("\nMean cash difference at day ends (Hour 23 of each day):")
    for d in range(30):
        h = d * 24 + 23
        print(f"  Day {d:2d} (h={h:3d}): ${mean_diff[h]:+8.2f}")

    print("\n" + "="*70)
    print("H20-22 SHED VS BACKPACK INVENTORY ANALYSIS")
    print("="*70)
    c_shed_occ = []
    c_bp_occ = []
    c_bp_prod = {p: [] for p in products}
    c_shed_wheat = []
    c_shed_fert = []

    t_shed_occ = []
    t_bp_occ = []
    t_bp_prod = {p: [] for p in products}
    t_shed_wheat = []
    t_shed_fert = []

    for item in telemetry:
        for snap in item['control']['h20_22_inventory_records']:
            c_shed_occ.append(snap['shed_occupancy'])
            c_bp_occ.append(snap['worker_inventory'])
            c_shed_wheat.append(snap['shed_wheat'])
            c_bp_prod['STRAWBERRY'].append(snap.get('worker_strawberry', 0))
            c_bp_prod['MILK'].append(snap.get('worker_milk', 0))
            c_bp_prod['WOOL'].append(snap.get('worker_wool', 0))
            c_bp_prod['MELON'].append(snap.get('worker_melon', 0))
            c_bp_prod['WHEAT'].append(snap.get('worker_wheat', 0))
            c_bp_prod['FERTILIZER'].append(snap.get('worker_fertilizer', 0))

        for snap in item['treatment']['h20_22_inventory_records']:
            t_shed_occ.append(snap['shed_occupancy'])
            t_bp_occ.append(snap['worker_inventory'])
            t_shed_wheat.append(snap['shed_wheat'])
            t_bp_prod['STRAWBERRY'].append(snap.get('worker_strawberry', 0))
            t_bp_prod['MILK'].append(snap.get('worker_milk', 0))
            t_bp_prod['WOOL'].append(snap.get('worker_wool', 0))
            t_bp_prod['MELON'].append(snap.get('worker_melon', 0))
            t_bp_prod['WHEAT'].append(snap.get('worker_wheat', 0))
            t_bp_prod['FERTILIZER'].append(snap.get('worker_fertilizer', 0))

    print(f"Control H20-22 Mean Shed Occupancy:     {np.mean(c_shed_occ):.2f} units (Wheat={np.mean(c_shed_wheat):.2f})")
    print(f"Control H20-22 Mean Backpack Occupancy: {np.mean(c_bp_occ):.2f} units")
    print("Control Backpack Produce Breakdown at H20-22:")
    for p in ['STRAWBERRY', 'MILK', 'WOOL', 'MELON', 'WHEAT', 'FERTILIZER']:
        m = np.mean(c_bp_prod[p])
        print(f"  {p:<12}: {m:5.2f} units")

    print(f"\nTreatment H20-22 Mean Shed Occupancy:     {np.mean(t_shed_occ):.2f} units (Wheat={np.mean(t_shed_wheat):.2f})")
    print(f"Treatment H20-22 Mean Backpack Occupancy: {np.mean(t_bp_occ):.2f} units")
    print("Treatment Backpack Produce Breakdown at H20-22:")
    for p in ['STRAWBERRY', 'MILK', 'WOOL', 'MELON', 'WHEAT', 'FERTILIZER']:
        m = np.mean(t_bp_prod[p])
        print(f"  {p:<12}: {m:5.2f} units")

    # Discard types breakdown
    print("\nShed Discards by Product (Mean Units Discarded per Game):")
    for p in products:
        c_d = np.mean([item['control']['shed_discards'].get(p, 0) for item in telemetry])
        t_d = np.mean([item['treatment']['shed_discards'].get(p, 0) for item in telemetry])
        if c_d > 0.01 or t_d > 0.01:
            print(f"  {p:<12}: Ctrl {c_d:5.2f} u | Treat {t_d:5.2f} u | Delta {t_d-c_d:+5.2f} u")

    # Feed failures
    print("\nFeed Failures Comparison:")
    c_miss = np.mean([item['control']['feed_failures']['missed_feeds'] for item in telemetry])
    t_miss = np.mean([item['treatment']['feed_failures']['missed_feeds'] for item in telemetry])
    c_starv = np.mean([item['control']['feed_failures']['starvation_events'] for item in telemetry])
    t_starv = np.mean([item['treatment']['feed_failures']['starvation_events'] for item in telemetry])
    c_esc = np.mean([item['control']['feed_failures']['escapes'] for item in telemetry])
    t_esc = np.mean([item['treatment']['feed_failures']['escapes'] for item in telemetry])
    print(f"  Missed Feeds: Ctrl {c_miss:.2f} | Treat {t_miss:.2f}")
    print(f"  Starvations : Ctrl {c_starv:.2f} | Treat {t_starv:.2f}")
    print(f"  Escapes     : Ctrl {c_esc:.2f} | Treat {t_esc:.2f}")

    # Hygiene activation breakdown
    t_trig_sold = sum(
        1 for item in telemetry for a in item['treatment']['hygiene_activations'] if a['status'] == 'TRIGGERED_AND_SOLD'
    )
    t_trig_nosale = sum(
        1 for item in telemetry for a in item['treatment']['hygiene_activations'] if a['status'] == 'TRIGGERED_BUT_IDLE'
    )
    t_not_trig = sum(
        1 for item in telemetry for a in item['treatment']['hygiene_activations'] if a['status'] == 'NOT_TRIGGERED'
    )
    print(f"\nHygiene Activations across 100 treatment games (9,000 total 1h windows H20-22):")
    print(f"  Triggered & Sold:      {t_trig_sold:5d} ({t_trig_sold/len(telemetry):.2f}/game, {t_trig_sold/9000*100:.1f}%)")
    print(f"  Triggered But Idle:    {t_trig_nosale:5d} ({t_trig_nosale/len(telemetry):.2f}/game, {t_trig_nosale/9000*100:.1f}%)")
    print(f"  Not Triggered:         {t_not_trig:5d} ({t_not_trig/len(telemetry):.2f}/game, {t_not_trig/9000*100:.1f}%)")

    print("\n" + "="*70)
    print("CAPITAL ALLOCATION / PURCHASE ENABLEMENT")
    print("="*70)
    all_treat_only = []
    for item in telemetry:
        for p in item.get('treat_only_purchases', []):
            all_treat_only.append((item['seed'], item['opponent'], item['seat'], p))
    print(f"Total Treatment-Only Purchases: {len(all_treat_only)}")
    type_counts = {}
    enabled_counts = {}
    for seed, opp, seat, p in all_treat_only:
        pt = f"{p['type']}_{p.get('item', '')}"
        type_counts[pt] = type_counts.get(pt, 0) + 1
        if p.get('liquidity_enabled', False):
            enabled_counts[pt] = enabled_counts.get(pt, 0) + 1
    for pt in sorted(type_counts.keys()):
        print(f"  {pt:<22}: {type_counts[pt]:4d} total ({enabled_counts.get(pt, 0):4d} liquidity-enabled)")

    print("\n" + "="*70)
    print("ANALYSIS COMPLETE")
    print("="*70)

if __name__ == '__main__':
    main()
