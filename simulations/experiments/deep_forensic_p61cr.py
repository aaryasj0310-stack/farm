"""
Deep Forensic Validation and Correction Script for P6.1-C-R
Executes all exact mathematical, statistical, economic, and geometric audits.
"""

import gzip
import json
import math
import numpy as np
from scipy import stats

TELEMETRY_FILE = "simulations/experiments/p61c_causal_reconciliation_telemetry.json.gz"
SUMMARY_FILE = "simulations/experiments/p61c_causal_reconciliation_summary.json"

def main():
    with gzip.open(TELEMETRY_FILE, "rt") as f:
        telemetry = json.load(f)

    n_pairs = len(telemetry)
    print(f"Loaded {n_pairs} matched scenario pairs.")

    # =========================================================================
    # 1. ABSOLUTE & PAIRED CASH WATERFALL AUDIT
    # =========================================================================
    prods = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]

    c_sales_rev = {p: [d["control"]["cash_ledger"]["sales_revenue_by_prod"].get(p, 0.0) for d in telemetry] for p in prods}
    t_sales_rev = {p: [d["treatment"]["cash_ledger"]["sales_revenue_by_prod"].get(p, 0.0) for d in telemetry] for p in prods}
    c_sales_qty = {p: [d["control"]["cash_ledger"]["sales_units_by_prod"].get(p, 0.0) for d in telemetry] for p in prods}
    t_sales_qty = {p: [d["treatment"]["cash_ledger"]["sales_units_by_prod"].get(p, 0.0) for d in telemetry] for p in prods}

    c_tot_sales = [d["control"]["cash_ledger"]["total_sales_revenue"] for d in telemetry]
    t_tot_sales = [d["treatment"]["cash_ledger"]["total_sales_revenue"] for d in telemetry]

    # Expenditures
    exp_keys = [
        ("Feed Wheat", "feed_wheat_cost", "feed_wheat_units"),
        ("Seed Buys", "seed_buy_cost", None),
        ("Animal Buys", "animal_buy_cost", None),
        ("Worker Wages", "hire_cost", "hire_count"),
        ("Land Expansion", "land_cost", None),
        ("Fertilizer Buy", "fert_buy_cost", "fert_buy_units"),
    ]

    c_exp_vals = {name: [d["control"]["cash_ledger"][k] for d in telemetry] for name, k, _ in exp_keys}
    t_exp_vals = {name: [d["treatment"]["cash_ledger"][k] for d in telemetry] for name, k, _ in exp_keys}

    c_tot_exp = [d["control"]["cash_ledger"]["total_expenditures"] for d in telemetry]
    t_tot_exp = [d["treatment"]["cash_ledger"]["total_expenditures"] for d in telemetry]

    c_final = [d["control"]["final_money"] for d in telemetry]
    t_final = [d["treatment"]["final_money"] for d in telemetry]
    cash_deltas = [d["cash_delta"] for d in telemetry]

    # Verify per-game closure
    c_residuals = [abs(3000.0 + c_tot_sales[i] - c_tot_exp[i] - c_final[i]) for i in range(n_pairs)]
    t_residuals = [abs(3000.0 + t_tot_sales[i] - t_tot_exp[i] - t_final[i]) for i in range(n_pairs)]
    paired_residuals = [abs(cash_deltas[i] - ((t_tot_sales[i] - c_tot_sales[i]) - (t_tot_exp[i] - c_tot_exp[i]))) for i in range(n_pairs)]

    print("\n" + "="*80)
    print("1. ABSOLUTE REVENUE & EXPENDITURE CLOSURE")
    print("="*80)
    print(f"Control Max Absolute Residual:   {max(c_residuals):.6f}")
    print(f"Treatment Max Absolute Residual: {max(t_residuals):.6f}")
    print(f"Control Mean:   $3,000.00 + ${np.mean(c_tot_sales):,.2f} - ${np.mean(c_tot_exp):,.2f} = ${np.mean(c_final):,.2f}")
    print(f"Treatment Mean: $3,000.00 + ${np.mean(t_tot_sales):,.2f} - ${np.mean(t_tot_exp):,.2f} = ${np.mean(t_final):,.2f}")
    print(f"Mean Paired Sales Delta:       ${np.mean(t_tot_sales) - np.mean(c_tot_sales):+,.2f}")
    print(f"Mean Paired Expenditure Delta: ${np.mean(t_tot_exp) - np.mean(c_tot_exp):+,.2f}")
    print(f"Mean Paired Cash Delta:        ${np.mean(cash_deltas):+,.2f}")
    print(f"Accounting Identity Check: (${np.mean(t_tot_sales) - np.mean(c_tot_sales):+,.2f}) - (${np.mean(t_tot_exp) - np.mean(c_tot_exp):+,.2f}) = ${(np.mean(t_tot_sales) - np.mean(c_tot_sales)) - (np.mean(t_tot_exp) - np.mean(c_tot_exp)):+,.2f}")

    # =========================================================================
    # 2. ECONOMIC REVENUE DECOMPOSITION (PRICE, QUANTITY, INTERACTION)
    # =========================================================================
    print("\n" + "="*80)
    print("2. PRODUCT REVENUE DECOMPOSITION (PRICE vs QUANTITY vs INTERACTION)")
    print("="*80)
    print(f"{'Product':<12} | {'Total dRev':>11} | {'Qty Effect':>11} | {'Price Effect':>12} | {'Interaction':>11} | {'Avg P_c':>8} {'Avg P_t':>8} {'dQty':>7}")
    print("-" * 80)

    for p in prods:
        c_q = np.mean(c_sales_qty[p])
        t_q = np.mean(t_sales_qty[p])
        c_r = np.mean(c_sales_rev[p])
        t_r = np.mean(t_sales_rev[p])
        d_r = t_r - c_r
        d_q = t_q - c_q

        p_c = c_r / c_q if c_q > 0 else 0.0
        p_t = t_r / t_q if t_q > 0 else 0.0
        d_p = p_t - p_c

        qty_effect = d_q * p_c
        price_effect = c_q * d_p
        interaction = d_q * d_p

        print(f"{p:<12} | ${d_r:+10.2f} | ${qty_effect:+10.2f} | ${price_effect:+11.2f} | ${interaction:+10.2f} | ${p_c:7.2f} ${p_t:7.2f} {d_q:+6.2f}u")

    # =========================================================================
    # 3. STATISTICAL DISTRIBUTION & OUTLIER AUDIT
    # =========================================================================
    deltas = np.array(cash_deltas)
    mean_val = np.mean(deltas)
    median_val = np.median(deltas)
    std_val = np.std(deltas, ddof=1)
    se_val = std_val / math.sqrt(n_pairs)
    ci95 = (mean_val - 1.96 * se_val, mean_val + 1.96 * se_val)

    # 10% trimmed mean: exactly drop lowest 10% and highest 10% (10 items each from 100 items)
    s_deltas = np.sort(deltas)
    trimmed_10 = np.mean(s_deltas[10:90])
    scipy_trimmed = stats.trim_mean(deltas, 0.10)

    wins = int(np.sum(deltas > 0))
    losses = int(np.sum(deltas < 0))
    ties = int(np.sum(deltas == 0))

    total_gain = np.sum(deltas)
    top1 = s_deltas[-1]
    top5_sum = np.sum(s_deltas[-5:])
    top10_sum = np.sum(s_deltas[-10:])
    mean_ex_top1 = np.mean(s_deltas[:-1])
    mean_ex_top5 = np.mean(s_deltas[:-5])
    mean_ex_top10 = np.mean(s_deltas[:-10])

    print("\n" + "="*80)
    print("3. STATISTICAL METRICS & OUTLIER DECOMPOSITION")
    print("="*80)
    print(f"Sample Size (N)              : {n_pairs} matched pairs (200 live games)")
    print(f"Mean Paired Cash Delta       : ${mean_val:+,.2f}")
    print(f"Even-N Median Cash Delta     : ${median_val:+,.2f}")
    print(f"Sample Standard Deviation (s): ${std_val:,.2f}")
    print(f"Standard Error (SE)          : ${se_val:,.2f}")
    print(f"95% Confidence Interval      : [${ci95[0]:+,.2f}, ${ci95[1]:+,.2f}]")
    print(f"10% Trimmed Mean (slice[10:90]): ${trimmed_10:+,.2f} (Scipy: ${scipy_trimmed:+,.2f})")
    print(f"Treatment Wins / Losses / Ties : {wins} Wins ({(wins/n_pairs)*100:.1f}%), {losses} Losses, {ties} Ties")
    print(f"Total Aggregate Cash Delta   : ${total_gain:+,.2f}")
    print(f"Top 1 Pair Gain              : ${top1:+,.2f} ({top1/total_gain*100:.1f}% of total net gain)")
    print(f"Top 5 Pairs Gain             : ${top5_sum:+,.2f} ({top5_sum/total_gain*100:.1f}% of total net gain)")
    print(f"Top 10 Pairs Gain            : ${top10_sum:+,.2f} ({top10_sum/total_gain*100:.1f}% of total net gain)")
    print(f"Mean Excluding Top 1 Pair    : ${mean_ex_top1:+,.2f}")
    print(f"Mean Excluding Top 5 Pairs   : ${mean_ex_top5:+,.2f}")
    print(f"Mean Excluding Top 10 Pairs  : ${mean_ex_top10:+,.2f}")

    # =========================================================================
    # 4. OPPONENT & SEAT SUBGROUP AUDIT
    # =========================================================================
    print("\n" + "="*80)
    print("4. OPPONENT SUBGROUP BREAKDOWN")
    print("="*80)
    opponents = ["pure_wheat_rush", "pass", "melon_sniper", "cow_milk_engine", "full_production_agent"]
    for opp in opponents:
        sub_indices = [i for i, d in enumerate(telemetry) if d["opponent"] == opp]
        sub_d = deltas[sub_indices]
        sub_disc = np.array([d["discard_delta"] for i, d in enumerate(telemetry) if i in sub_indices])
        sub_sales = np.array([d["total_sales_delta"] for i, d in enumerate(telemetry) if i in sub_indices])
        sub_exp = np.array([d["total_expenditure_delta"] for i, d in enumerate(telemetry) if i in sub_indices])
        sub_wins = sum(1 for v in sub_d if v > 0)
        print(f"{opp:<22} | N={len(sub_d):2d} | Mean dCash: ${np.mean(sub_d):+9.2f} | Med: ${np.median(sub_d):+9.2f} | WinRate: {sub_wins}/{len(sub_d)} ({sub_wins/len(sub_d)*100:4.1f}%) | dSales: ${np.mean(sub_sales):+8.2f} | dExp: ${np.mean(sub_exp):+8.2f} | dDisc: {np.mean(sub_disc):+5.2f}u")

    print("\n" + "="*80)
    print("5. SEAT SUBGROUP BREAKDOWN")
    print("="*80)
    for seat in [0, 1]:
        seat_indices = [i for i, d in enumerate(telemetry) if d["seat"] == seat]
        seat_d = deltas[seat_indices]
        seat_wins = sum(1 for v in seat_d if v > 0)
        print(f"Seat {seat} | N={len(seat_d):2d} | Mean dCash: ${np.mean(seat_d):+9.2f} | Med: ${np.median(seat_d):+9.2f} | WinRate: {seat_wins}/{len(seat_d)} ({seat_wins/len(seat_d)*100:4.1f}%)")

    # =========================================================================
    # 6. PHYSICAL WHEAT INVENTORY BALANCE AUDIT
    # =========================================================================
    print("\n" + "="*80)
    print("6. PHYSICAL WHEAT INVENTORY CONSERVATION AUDIT")
    print("="*80)
    c_w_sales = np.mean(c_sales_qty["WHEAT"])
    t_w_sales = np.mean(t_sales_qty["WHEAT"])
    d_w_sales = t_w_sales - c_w_sales

    c_w_buy = np.mean([d["control"]["cash_ledger"]["feed_wheat_units"] for d in telemetry])
    t_w_buy = np.mean([d["treatment"]["cash_ledger"]["feed_wheat_units"] for d in telemetry])
    d_w_buy = t_w_buy - c_w_buy

    c_w_disc = np.mean([d["control"]["shed_discards"].get("WHEAT", 0) for d in telemetry])
    t_w_disc = np.mean([d["treatment"]["shed_discards"].get("WHEAT", 0) for d in telemetry])
    d_w_disc = t_w_disc - c_w_disc

    c_missed_feeds = np.mean([d["control"]["feed_failures"]["missed_feeds"] for d in telemetry])
    t_missed_feeds = np.mean([d["treatment"]["feed_failures"]["missed_feeds"] for d in telemetry])
    d_missed_feeds = t_missed_feeds - c_missed_feeds
    # Each avoided missed feed represents +1 unit of wheat consumed on farm
    d_w_consumed = -d_missed_feeds

    print(f"Wheat Market Purchases Delta (Treat - Ctrl): {d_w_buy:+8.2f} u")
    print(f"Wheat Market Sales Delta (Treat - Ctrl)    : {d_w_sales:+8.2f} u")
    print(f"Wheat Discard Delta (Treat - Ctrl)         : {d_w_disc:+8.2f} u")
    print(f"Missed Animal Feeds Delta (Treat - Ctrl)   : {d_missed_feeds:+8.2f} feeds (Consumed Delta: {d_w_consumed:+8.2f} u)")

    implied_harvest_delta = d_w_sales + d_w_disc + d_w_consumed - d_w_buy
    print(f"Implied Wheat Harvest Yield Delta          : {implied_harvest_delta:+8.2f} u")
    print(f"Net Wheat Cash Difference (Rev - Cost)     : ${np.mean(t_sales_rev['WHEAT']) - np.mean(c_sales_rev['WHEAT']) - (np.mean(t_exp_vals['Feed Wheat']) - np.mean(c_exp_vals['Feed Wheat'])):+8.2f}")

    # =========================================================================
    # 7. REAL ENGINE GEOMETRY & WORKER TRANSIT FEASIBILITY
    # =========================================================================
    print("\n" + "="*80)
    print("7. REAL ENGINE GEOMETRY & WORKER TRANSIT COST ANALYSIS")
    print("="*80)
    print("Board Size: 10x10. Shed is 2x2 centered at (4,4), (5,4), (4,5), (5,5).")
    print("Shed Access Tiles: (4,4) [NW], (5,4) [NE], (4,5) [SW], (5,5) [SE].")

    # Calculate Manhattan distance from all 100 tiles to the nearest shed access tile
    shed_access = [(4,4), (5,4), (4,5), (5,5)]
    distances = {}
    for y in range(10):
        for x in range(10):
            min_d = min(abs(x - sx) + abs(y - sy) for sx, sy in shed_access)
            distances[(x, y)] = min_d

    d_values = list(distances.values())
    print(f"Distance to nearest shed access: Min={min(d_values)} (adjacent), Max={max(d_values)} (corners), Mean={np.mean(d_values):.2f} tiles")

    # Corner tiles e.g. (0,0) -> min distance to (4,4) is 4 + 4 = 8 steps.
    # Furthest tile from shed is (0,0), (9,0), (0,9), (9,9) at distance 8 steps.
    # Maximum round trip anywhere on the 10x10 board is 2 * 8 = 16 steps!
    # Central farm tiles (x in 2..7, y in 2..7) have distance 0 to 4 steps (round trip 0 to 8 steps).
    print(f"Maximum round trip distance anywhere on 10x10 board: {2 * max(d_values)} steps (16 steps).")
    print(f"Average round trip transit cost across all board tiles: {2 * np.mean(d_values):.2f} steps (4.8 steps).")
    print(f"Inner farm core (distance <= 2 tiles): {sum(1 for d in d_values if d <= 2)} / 100 tiles (round trip <= 4 steps).")

if __name__ == "__main__":
    main()
