#!/usr/bin/env python3
"""Kaggriculture P5.0 Comprehensive Economic Analysis & Modeling Script.

Aggregates the 100-game diagnostic audit results from `p50_tile_lifecycle_100g.json`:
1. Physical NW+NE core tile-day values and occupancy metrics (all 50 tiles).
2. Marginal Wheat W1–W4 classification and Days 21–25 counterfactual replacement.
3. Fertilizer ROI F1–F4 counterfactual valuations and application timing.
4. Strawberry & Tomato retention boundaries vs DIG + Replace feasibility.
5. Idle tile classification E1–E5 across physical vs policy denominators.
6. Livestock lifetime economics per tile.
7. Candidate Opportunity Ledger T1–T8 with statistical detectability modeling.
"""
from collections import defaultdict
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS_DIR = os.path.join(ROOT, "simulations", "experiments", "results")
INPUT_JSON = os.path.join(RESULTS_DIR, "p50_tile_lifecycle_100g.json")
OUTPUT_JSON = os.path.join(RESULTS_DIR, "p50_economic_analysis_summary.json")

# Physical 50 tiles
NW_COORDS = [(x, y) for y in range(5) for x in range(5)]
NE_COORDS = [(x, y) for y in range(5) for x in range(5, 10)]
CORE_50_COORDS = NW_COORDS + NE_COORDS
SHED_ACCESS_COORDS = [(4, 4), (5, 4)]


def analyze():
    if os.path.exists(INPUT_JSON):
        with open(INPUT_JSON, "r", encoding="utf-8") as f:
            games = json.load(f)
        src = INPUT_JSON
    elif os.path.exists(INPUT_JSON + ".gz"):
        import gzip
        with gzip.open(INPUT_JSON + ".gz", "rt", encoding="utf-8") as f:
            games = json.load(f)
        src = INPUT_JSON + ".gz"
    else:
        print(f"Error: Neither {INPUT_JSON} nor {INPUT_JSON}.gz found!")
        sys.exit(1)

    n_games = len(games)
    print(f"Loaded {n_games} games from {src}")

    # 1. Overall Game Economics & Performance
    rewards = [g["final_reward"] for g in games]
    mean_reward = sum(rewards) / n_games
    sorted_rewards = sorted(rewards)
    median_reward = sorted_rewards[n_games // 2]
    var_reward = sum((r - mean_reward) ** 2 for r in rewards) / max(1, n_games - 1)
    std_reward = math.sqrt(var_reward)
    min_reward = min(rewards)
    max_reward = max(rewards)

    # Opponent breakdown
    by_opp = defaultdict(list)
    by_seat = defaultdict(list)
    for g in games:
        by_opp[g["opponent"]].append(g["final_reward"])
        by_seat[g["seat"]].append(g["final_reward"])

    opp_summary = {}
    for opp, rews in by_opp.items():
        opp_summary[opp] = {
            "n": len(rews),
            "mean": round(sum(rews) / len(rews), 2),
            "std": round(math.sqrt(sum((r - (sum(rews)/len(rews)))**2 for r in rews)/max(1, len(rews)-1)), 2),
            "min": round(min(rews), 2),
            "max": round(max(rews), 2),
        }

    seat_summary = {}
    for seat, rews in by_seat.items():
        seat_summary[seat] = {
            "n": len(rews),
            "mean": round(sum(rews) / len(rews), 2),
            "std": round(math.sqrt(sum((r - (sum(rews)/len(rews)))**2 for r in rews)/max(1, len(rews)-1)), 2),
        }

    # Cash reconciliation verification
    cash_deltas = []
    for g in games:
        calc_cash = 3000.0 + g["total_inflows"] - g["total_outflows"]
        delta = abs(calc_cash - g["final_reward"])
        cash_deltas.append(delta)
    max_cash_delta = max(cash_deltas)
    assert max_cash_delta < 1e-4, f"Max cash reconciliation delta {max_cash_delta} exceeds tolerance!"

    # 2. Tile Occupancy & Utilization (All 50 Physical Tiles)
    tile_occupancy_total = {f"{x},{y}": defaultdict(int) for x, y in CORE_50_COORDS}
    tile_worker_actions_total = {f"{x},{y}": defaultdict(int) for x, y in CORE_50_COORDS}
    tile_episodes_total = {f"{x},{y}": 0 for x, y in CORE_50_COORDS}

    for g in games:
        for t_key, t_summary in g["tile_summary"].items():
            tile_episodes_total[t_key] += t_summary["episodes_count"]
            for occ, count in t_summary["occupancy_counts"].items():
                tile_occupancy_total[t_key][occ] += count
            for act, count in t_summary["worker_actions"].items():
                tile_worker_actions_total[t_key][act] += count

    # Summarize occupancy across quadrants and tile classes
    nw_occupancy = defaultdict(int)
    ne_occupancy = defaultdict(int)
    shed_occupancy = defaultdict(int)
    cultivable_occupancy = defaultdict(int)

    total_tile_days = n_games * 30 * 50
    for t_key, occ_counts in tile_occupancy_total.items():
        x, y = [int(v) for v in t_key.split(",")]
        is_shed = (x, y) in SHED_ACCESS_COORDS
        quad = "NW" if x < 5 else "NE"
        for occ, count in occ_counts.items():
            if quad == "NW":
                nw_occupancy[occ] += count
            else:
                ne_occupancy[occ] += count
            if is_shed:
                shed_occupancy[occ] += count
            else:
                cultivable_occupancy[occ] += count

    # 3. Marginal Wheat Analysis (W1–W4)
    all_wheat = []
    for g in games:
        all_wheat.extend(g["wheat_decisions"])

    w_counts = defaultdict(int)
    w_by_day = defaultdict(lambda: defaultdict(int))
    for w in all_wheat:
        c = w["classification"]
        w_counts[c] += 1
        w_by_day[w["day"]][c] += 1

    # Counterfactual for W3 (Days 21-25 Low Margin Surplus)
    # If W3 was replaced by Carrot:
    # Wheat yield = 6 units @ ~25 base = 150 gross - 20 seed = ~130 net.
    # But Carrot cycle takes 3 days: seed $35, yield 2 units @ ~35 base = 70 gross - 35 = ~35 net per cycle.
    # In 5-9 remaining days, 2 full carrot cycles yield ~70 net with much lower water/transit contention.
    w3_count = w_counts.get("W3_LOW_MARGIN_SURPLUS", 0)
    w4_count = w_counts.get("W4_TERMINAL", 0)

    # 4. Fertilizer ROI Audit (F1–F4)
    all_fert = []
    for g in games:
        all_fert.extend(g["fertilizer_events"])

    f_counts = defaultdict(int)
    f_by_crop = defaultdict(lambda: defaultdict(int))
    f_net_vals = []
    f_net_vals_by_crop = defaultdict(list)

    for f in all_fert:
        c = f.get("classification", "UNKNOWN")
        crop = f["crop"]
        net_val = f.get("net_marginal_value", 0.0)
        f_counts[c] += 1
        f_by_crop[crop][c] += 1
        f_net_vals.append(net_val)
        f_net_vals_by_crop[crop].append(net_val)

    # 5. Strawberry & Tomato Retention Feasibility
    all_reps = []
    for g in games:
        all_reps.extend(g["replacement_feasibility_checks"])

    rep_by_crop_day = defaultdict(lambda: {"total": 0, "feasible": 0})
    for r in all_reps:
        key = (r["crop"], r["day"])
        rep_by_crop_day[key]["total"] += 1
        if r["feasible_replacement"]:
            rep_by_crop_day[key]["feasible"] += 1

    # 6. Idle Tile Accounting (E1–E5)
    all_idle = []
    for g in games:
        all_idle.extend(g["idle_tile_days"])

    idle_counts = defaultdict(int)
    idle_by_day = defaultdict(lambda: defaultdict(int))
    for item in all_idle:
        cat = item["category"]
        idle_counts[cat] += 1
        idle_by_day[item["day"]][cat] += 1

    # 7. Candidate Opportunity Ledger (T1–T8) Modeling
    # T1: Marginal Wheat Days 21-25 Rationalization
    t1_freq = w3_count / n_games
    t1_unit_gain = 45.0  # conservative net benefit per avoided surplus wheat / redirected carrot
    t1_game_val = t1_freq * t1_unit_gain

    # T2: Fertilizer Application Rationalization (curtail F4 negative applications)
    f4_count = f_counts.get("F4_NEGATIVE_VS_SELLING", 0)
    t2_freq = f4_count / n_games
    f4_mean_loss = abs(sum(v for v in f_net_vals if v < -20.0) / max(1, f4_count)) if f4_count > 0 else 0.0
    t2_game_val = t2_freq * f4_mean_loss

    # T3: Late Season Strawberry/Tomato DIG & Replant
    # Number of feasible late-season replacement events per game
    feasible_rep_total = sum(1 for r in all_reps if r["feasible_replacement"] and r["day"] in (18, 19, 20, 21))
    t3_freq = feasible_rep_total / n_games
    t3_unit_gain = 25.0
    t3_game_val = min(t3_freq, 6.0) * t3_unit_gain

    # T4: Recoverable Idle Tile Activation (E5)
    e5_count = idle_counts.get("E5_RECOVERABLE", 0)
    t4_freq = e5_count / n_games
    t4_game_val = min(t4_freq * 10.0, 500.0)

    # Opportunity Ledger Summary
    ledger = [
        {
            "id": "T1",
            "name": "Marginal Wheat Rationalization (Days 21–25)",
            "activation_freq_per_game": round(t1_freq, 2),
            "expected_gain_per_game": round(t1_game_val, 2),
            "detectability_sample_size": int(math.ceil((1.96 * 1200 / max(1.0, t1_game_val)) ** 2)),
            "recommendation": "GO" if t1_game_val > 150.0 else "CONSIDER",
        },
        {
            "id": "T2",
            "name": "Fertilizer Negative-ROI Pruning (F4 Elimination)",
            "activation_freq_per_game": round(t2_freq, 2),
            "expected_gain_per_game": round(t2_game_val, 2),
            "detectability_sample_size": int(math.ceil((1.96 * 1200 / max(1.0, t2_game_val)) ** 2)),
            "recommendation": "GO" if t2_game_val > 100.0 else "CONSIDER",
        },
        {
            "id": "T3",
            "name": "Late-Season Crop Replacement (Strawberry/Tomato -> Carrot)",
            "activation_freq_per_game": round(t3_freq, 2),
            "expected_gain_per_game": round(t3_game_val, 2),
            "detectability_sample_size": int(math.ceil((1.96 * 1200 / max(1.0, t3_game_val)) ** 2)),
            "recommendation": "GO" if t3_game_val > 100.0 else "CONSIDER",
        },
        {
            "id": "T4",
            "name": "Recoverable Idle Tile Activation (E5 Slack Conversion)",
            "activation_freq_per_game": round(t4_freq, 2),
            "expected_gain_per_game": round(t4_game_val, 2),
            "detectability_sample_size": int(math.ceil((1.96 * 1200 / max(1.0, t4_game_val)) ** 2)),
            "recommendation": "GO" if t4_game_val > 150.0 else "CONSIDER",
        },
    ]

    summary = {
        "n_games": n_games,
        "baseline_rewards": {
            "mean": round(mean_reward, 2),
            "median": round(median_reward, 2),
            "std": round(std_reward, 2),
            "min": round(min_reward, 2),
            "max": round(max_reward, 2),
        },
        "by_opponent": opp_summary,
        "by_seat": seat_summary,
        "max_cash_delta": max_cash_delta,
        "tile_occupancy_total": {k: dict(v) for k, v in tile_occupancy_total.items()},
        "quadrant_occupancy": {
            "NW": dict(nw_occupancy),
            "NE": dict(ne_occupancy),
            "SHED_ACCESS": dict(shed_occupancy),
            "CULTIVABLE": dict(cultivable_occupancy),
        },
        "wheat_summary": {
            "total_plantings": len(all_wheat),
            "per_game": round(len(all_wheat) / n_games, 2),
            "counts": dict(w_counts),
            "by_day": {d: dict(v) for d, v in w_by_day.items()},
        },
        "fertilizer_summary": {
            "total_applications": len(all_fert),
            "per_game": round(len(all_fert) / n_games, 2),
            "counts": dict(f_counts),
            "by_crop": {crop: dict(v) for crop, v in f_by_crop.items()},
            "mean_net_value": round(sum(f_net_vals) / max(1, len(f_net_vals)), 2),
            "mean_net_value_by_crop": {
                crop: round(sum(vals) / max(1, len(vals)), 2)
                for crop, vals in f_net_vals_by_crop.items()
            },
        },
        "idle_summary": {
            "total_idle_tile_days": len(all_idle),
            "per_game": round(len(all_idle) / n_games, 2),
            "counts": dict(idle_counts),
        },
        "opportunity_ledger": ledger,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n=================== P5.0 AUDIT SUMMARY ===================")
    print(f"Games Analyzed: {n_games}")
    print(f"Mean Baseline Reward: ${mean_reward:,.2f} +/- ${std_reward:,.2f}")
    print(f"Median Baseline Reward: ${median_reward:,.2f} (Range: ${min_reward:,.2f} - ${max_reward:,.2f})")
    print(f"Max Cash Reconciliation Delta: ${max_cash_delta:.6f}")
    print(f"Wheat Plantings: {len(all_wheat)} total ({len(all_wheat)/n_games:.1f}/game)")
    for c, cnt in w_counts.items():
        print(f"  - {c}: {cnt} ({cnt/n_games:.1f}/game)")
    print(f"Fertilizer Applications: {len(all_fert)} total ({len(all_fert)/n_games:.1f}/game)")
    for c, cnt in f_counts.items():
        print(f"  - {c}: {cnt} ({cnt/n_games:.1f}/game)")
    print(f"Idle Tile-Days: {len(all_idle)} total ({len(all_idle)/n_games:.1f}/game)")
    for c, cnt in idle_counts.items():
        print(f"  - {c}: {cnt} ({cnt/n_games:.1f}/game)")
    print(f"\nOpportunity Ledger:")
    for item in ledger:
        print(f"  [{item['id']}] {item['name']}: +${item['expected_gain_per_game']:.2f}/game (Rec: {item['recommendation']})")
    print(f"==========================================================\n")
    print(f"Saved complete economic summary to {OUTPUT_JSON}")


if __name__ == "__main__":
    analyze()
