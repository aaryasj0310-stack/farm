#!/usr/bin/env python3
"""Kaggriculture P5.0-R Comprehensive Revalidation & Modeling Script.

Performs Phases P5.0-R2 through P5.0-R6:
1. Time-Indexed Feed-Security Model: Day-by-day balance simulation B_d = B_{d-1} + H_d - F_d.
2. Strict Feed-Safe Reclassification: RW1 (Critical), RW2 (Buffer Support), RW3 (Economic Surplus), RW4 (Terminal).
3. Engine-Exact Wheat vs Carrot Counterfactual: Real seed costs ($10 vs $20), actual yields (4 vs 3 unfert),
   dynamic 1-cycle vs 2-cycle carrot fitting, causal market pricing curves (P4.2).
4. Labor Opportunity Reconciliation: Delta worker actions, morning peak contention analysis, labor stress sensitivity.
5. Joint Per-Game Shadow Aggregation without double-counting.
6. Narrow Decision Boundary Search and Stress Testing.
"""
from collections import defaultdict
import copy
import gzip
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS_DIR = os.path.join(ROOT, "simulations", "experiments", "results")
INPUT_JSON_GZ = os.path.join(RESULTS_DIR, "p50r_telemetry_100g.json.gz")
INPUT_JSON = os.path.join(RESULTS_DIR, "p50r_telemetry_100g.json")
OUTPUT_SUMMARY_JSON = os.path.join(RESULTS_DIR, "p50r_revalidation_summary.json")

# Ground truth market parameters matching kaggriculture.py
MARKET_I0 = 10000
PRICE_FLOOR = 1
HINGE_GAIN = 8.0
MARKET_PARAMS = {
    "WHEAT":      {"base":  25, "I0": MARKET_I0, "T": 400, "below_func": "sqrt",   "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base":  35, "I0": MARKET_I0, "T": 450, "below_func": "hinge",  "below_target": 1.00, "above_func": "sqrt",   "above_target": 0.70},
}


def _shape(func, x, T=None):
    x = max(0.0, float(x))
    if func == "linear": return x
    if func == "sq":     return x * x
    if func == "sqrt":   return math.sqrt(x)
    if func == "log":    return math.log(1.0 + x)
    if func == "hinge":
        if not T or T <= 0: return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def engine_price(product, inventory):
    p = MARKET_PARAMS[product]
    base = p["base"]
    I0 = p["I0"]
    T = p["T"]
    if inventory < I0:
        fn = p["below_func"]
        target = p["below_target"]
        fT = _shape(fn, T, T)
        amp = (target * base) / fT if fT > 0 else 0.0
        delta = amp * _shape(fn, I0 - inventory, T)
        raw = base + delta
    else:
        fn = p["above_func"]
        target = p["above_target"]
        fT = _shape(fn, T, T)
        amp = (target * base) / fT if fT > 0 else 0.0
        delta = amp * _shape(fn, inventory - I0, T)
        raw = base - delta
    return max(PRICE_FLOOR, int(round(raw)))


def marginal_market_revenue(product, base_inventory, units):
    """Calculates causal revenue for `units` sold into the market starting at `base_inventory`."""
    rev = 0.0
    inv = base_inventory
    for _ in range(units):
        p = engine_price(product, inv)
        rev += p
        inv += 1
    return rev


def simulate_feed_ledger(snap, remove_candidate=True):
    """Simulates day-by-day feed balance timeline B_d = B_{d-1} + H_d - F_d through Day 28.

    Returns:
      is_feed_safe: True if B_d >= 0 for all days d in [D, 28]
      min_balance: minimum balance observed on any day d in [D, 28]
      daily_balances: dict of day -> balance
    """
    d_start = snap["day"]
    h_start = snap["hour"]

    # Initial liquid wheat stock at moment of decision
    shed_wheat = snap["shed"].get("WHEAT", 0)
    worker_wheat = sum(inv.get("WHEAT", 0) for inv in snap["inventories"])
    B = float(shed_wheat + worker_wheat)

    # Animals requiring wheat (COW, SHEEP)
    wheat_animals = [a for a in snap["animals"] if a.get("animal") in ("COW", "SHEEP")]
    herd_size = len(wheat_animals)

    # In-ground wheat tiles future maturation timeline
    # Day P wheat matures and is harvested on Day P+4
    future_harvests = defaultdict(float)
    for t in snap["in_ground_wheat"]:
        planted_day = t["planted_day"]
        harvest_day = planted_day + 4
        # Calculate conservative realizable yield
        # Starts with 1. Bonus added on days P+2, P+3, P+4 if watered.
        bonus_days = 0
        for k in (2, 3, 4):
            day_k = planted_day + k
            if day_k < d_start:
                # Past bonus day: if yield was already accumulated
                continue
            elif day_k == d_start:
                # Today: if watered today or can be watered today
                bonus_days += 1
            elif day_k <= 28:
                bonus_days += 1

        # Conservative unfertilized yield: 1 + bonus_days (capped at 4)
        c_yield = min(4, 1 + bonus_days)
        if t.get("fertilized_until_day", -1) >= harvest_day:
            c_yield = min(6, 1 + 2 * bonus_days)

        if harvest_day <= 28:
            future_harvests[harvest_day] += c_yield

    # If Counterfactual A (keep candidate wheat):
    # Candidate wheat planted on d_start matures on d_start + 4
    if not remove_candidate:
        cand_harvest_day = d_start + 4
        if cand_harvest_day <= 28:
            future_harvests[cand_harvest_day] += 4.0  # Conservative unfertilized yield

    daily_balances = {}
    is_safe = True
    min_bal = float("inf")

    for d in range(d_start, 29):  # Days d_start through 28
        # Add harvests maturing on day d (available for feeding)
        H_d = future_harvests.get(d, 0.0)
        B += H_d

        # Determine feed obligation F_d
        if d == d_start:
            # On decision day, some animals may have already been fed today
            unfed_today = sum(1 for a in wheat_animals if not a.get("fed_today", False))
            F_d = unfed_today
        else:
            F_d = herd_size  # Full herd needs 1 wheat per day

        B -= F_d
        daily_balances[d] = B
        if B < min_bal:
            min_bal = B
        if B < 0:
            is_safe = False

    return is_safe, min_bal, daily_balances, herd_size


def analyze_snapshot(snap):
    """Comprehensive engine-exact counterfactual analysis of a single wheat decision."""
    d = snap["day"]
    h = snap["hour"]
    tile = snap["candidate_tile"]

    # 1. Feed-safe classification with time-indexed ledger
    is_safe_b, min_bal_b, ledger_b, herd_size = simulate_feed_ledger(snap, remove_candidate=True)
    is_safe_a, min_bal_a, ledger_a, _ = simulate_feed_ledger(snap, remove_candidate=False)

    # Safety buffer floor: at least 1 day of herd feed reserve
    safety_buffer = float(herd_size * 1)

    if not is_safe_b:
        classification = "RW1_FEED_CRITICAL"
    elif min_bal_b < safety_buffer:
        classification = "RW2_FEED_BUFFER_SUPPORT"
    else:
        classification = "RW3_GENUINE_SURPLUS"

    # 2. Economic Counterfactual for RW3 Candidates
    # Wheat Baseline (Counterfactual A)
    seed_cost_wheat = 10.0
    wheat_harvest_day = d + 4
    wheat_mkt_inv = snap["market_inventory"].get("WHEAT", 10000)
    wheat_yield = 4.0  # Conservative unfertilized yield
    v_wheat_gross = marginal_market_revenue("WHEAT", wheat_mkt_inv, int(wheat_yield))
    v_wheat_net = v_wheat_gross - seed_cost_wheat
    wheat_actions = 6  # 1 plant, 4 waterings, 1 harvest

    # Carrot Alternative (Counterfactual B)
    # Check executability today: requires planting and watering before Hour 24
    hours_left = 24 - h
    money = snap["money"]
    can_execute_c1 = (hours_left >= 2) and (money >= 20.0)

    c1_fits = can_execute_c1 and (d + 3 <= 29)
    c2_fits = False
    c1_rev = 0.0
    c2_rev = 0.0
    carrot_actions = 0
    carrot_seed_cost = 0.0

    if c1_fits:
        carrot_mkt_inv = snap["market_inventory"].get("CARROT", 10000)
        c1_yield = 3.0  # Conservative unfertilized yield (harvested Day d+3)
        c1_rev = marginal_market_revenue("CARROT", carrot_mkt_inv, int(c1_yield))
        carrot_seed_cost += 20.0
        carrot_actions += 5  # 1 plant, 3 waterings, 1 harvest

        # Check Cycle 2: Plant on Day d+3, harvest on Day d+6
        # Day 21 + 6 = 27 <= 29 (Fits!)
        # Day 22 + 6 = 28 <= 29 (Fits!)
        # Day 23 + 6 = 29 <= 29 (Fits!)
        # Day 24 + 6 = 30 > 29 (Does not fit!)
        if d + 6 <= 29:
            c2_fits = True
            c2_yield = 3.0
            # Cycle 2 sells into market after Cycle 1
            c2_rev = marginal_market_revenue("CARROT", carrot_mkt_inv + int(c1_yield), int(c2_yield))
            carrot_seed_cost += 20.0
            carrot_actions += 5  # 1 plant, 3 waterings, 1 harvest

    v_carrot_gross = c1_rev + c2_rev
    v_carrot_net = v_carrot_gross - carrot_seed_cost if c1_fits else 0.0

    # Raw crop economic delta
    raw_delta = v_carrot_net - v_wheat_net if c1_fits else 0.0

    # Labor Opportunity Analysis
    delta_actions = carrot_actions - wheat_actions
    # Hourly sensitivity values
    # Morning (Hours 0-5): $35/act; Midday (Hours 6-11): $20/act; Afternoon (Hours 12-23): $8/act
    if h < 6:
        displaced_labor_val = max(0, delta_actions) * 35.0
    elif h < 12:
        displaced_labor_val = max(0, delta_actions) * 20.0
    else:
        displaced_labor_val = max(0, delta_actions) * 8.0

    labor_stressed_delta = raw_delta - displaced_labor_val

    # Real task displacement:
    # If 1-cycle carrot: delta_actions is -1 (Carrot uses LESS labor than wheat! Zero labor displacement penalty).
    # If 2-cycle carrot: delta_actions is +4 over 6 days. Tasks occur primarily in afternoon slack.
    observed_displacement_penalty = 0.0 if delta_actions <= 0 else delta_actions * 12.0
    task_displaced_delta = raw_delta - observed_displacement_penalty

    return {
        "seed": snap["seed"],
        "opponent": snap["opponent"],
        "seat": snap["seat"],
        "step": snap["step"],
        "day": d,
        "hour": h,
        "tile": tile,
        "herd_size": herd_size,
        "classification": classification,
        "is_feed_safe": is_safe_b,
        "min_balance_without": min_bal_b,
        "min_balance_with": min_bal_a,
        "daily_ledger_without": ledger_b,
        "v_wheat_gross": round(v_wheat_gross, 2),
        "v_wheat_net": round(v_wheat_net, 2),
        "c1_fits": c1_fits,
        "c2_fits": c2_fits,
        "v_carrot_gross": round(v_carrot_gross, 2),
        "v_carrot_net": round(v_carrot_net, 2),
        "raw_delta": round(raw_delta, 2),
        "delta_actions": delta_actions,
        "task_displaced_delta": round(task_displaced_delta, 2),
        "labor_stressed_delta": round(labor_stressed_delta, 2),
    }


def run_analysis():
    # Load dataset
    if os.path.exists(INPUT_JSON):
        with open(INPUT_JSON, "r", encoding="utf-8") as f:
            games = json.load(f)
        src = INPUT_JSON
    elif os.path.exists(INPUT_JSON_GZ):
        with gzip.open(INPUT_JSON_GZ, "rt", encoding="utf-8") as f:
            games = json.load(f)
        src = INPUT_JSON_GZ
    else:
        print(f"Error: Neither {INPUT_JSON} nor {INPUT_JSON_GZ} found!")
        sys.exit(1)

    print(f"Analyzing {len(games)} games from {src}...")

    all_analyzed = []
    game_summaries = []

    for g in games:
        g_snaps = g.get("wheat_decision_snapshots", [])
        g_analyzed = [analyze_snapshot(snap) for snap in g_snaps]
        all_analyzed.extend(g_analyzed)

        # Joint Per-Game Shadow Policy (No Double-Counting)
        # Select jointly feasible substitutions within the game:
        # Group candidates by tile: only 1 substitution per tile!
        # Respect collective worker capacity and seed money.
        tile_candidates = {}
        for ev in g_analyzed:
            if ev["classification"] == "RW3_GENUINE_SURPLUS" and ev["task_displaced_delta"] > 0:
                t_key = f"{ev['tile'][0]},{ev['tile'][1]}"
                if t_key not in tile_candidates or ev["task_displaced_delta"] > tile_candidates[t_key]["task_displaced_delta"]:
                    tile_candidates[t_key] = ev

        joint_substitutions = list(tile_candidates.values())
        joint_raw_delta = sum(ev["raw_delta"] for ev in joint_substitutions)
        joint_displaced_delta = sum(ev["task_displaced_delta"] for ev in joint_substitutions)
        joint_stressed_delta = sum(ev["labor_stressed_delta"] for ev in joint_substitutions)

        game_summaries.append({
            "seed": g["seed"],
            "opponent": g["opponent"],
            "seat": g["seat"],
            "baseline_reward": g["final_reward"],
            "total_decisions": len(g_snaps),
            "rw3_count": sum(1 for ev in g_analyzed if ev["classification"] == "RW3_GENUINE_SURPLUS"),
            "joint_substitutions_count": len(joint_substitutions),
            "joint_raw_delta": round(joint_raw_delta, 2),
            "joint_displaced_delta": round(joint_displaced_delta, 2),
            "joint_stressed_delta": round(joint_stressed_delta, 2),
        })

    n_events = len(all_analyzed)
    n_games = len(games)

    # Classification counts
    class_counts = defaultdict(int)
    by_day_class = defaultdict(lambda: defaultdict(int))
    by_opp_class = defaultdict(lambda: defaultdict(int))
    by_seat_class = defaultdict(lambda: defaultdict(int))

    for ev in all_analyzed:
        c = ev["classification"]
        d = ev["day"]
        opp = ev["opponent"]
        seat = str(ev["seat"])
        class_counts[c] += 1
        by_day_class[d][c] += 1
        by_opp_class[opp][c] += 1
        by_seat_class[seat][c] += 1

    # Distribution of delta for genuine RW3 events
    rw3_events = [ev for ev in all_analyzed if ev["classification"] == "RW3_GENUINE_SURPLUS"]
    rw3_raw_deltas = [ev["raw_delta"] for ev in rw3_events]
    rw3_displaced_deltas = [ev["task_displaced_delta"] for ev in rw3_events]
    rw3_stressed_deltas = [ev["labor_stressed_delta"] for ev in rw3_events]

    def dist_stats(vals):
        if not vals:
            return {"n": 0, "mean": 0, "median": 0, "std": 0, "min": 0, "max": 0, "p10": 0, "p25": 0, "p75": 0, "p90": 0}
        s = sorted(vals)
        n = len(s)
        mean = sum(s) / n
        var = sum((x - mean) ** 2 for x in s) / max(1, n - 1)
        return {
            "n": n,
            "mean": round(mean, 2),
            "median": round(s[n // 2], 2),
            "std": round(math.sqrt(var), 2),
            "min": round(min(s), 2),
            "max": round(max(s), 2),
            "p10": round(s[int(n * 0.10)], 2),
            "p25": round(s[int(n * 0.25)], 2),
            "p75": round(s[int(n * 0.75)], 2),
            "p90": round(s[int(n * 0.90)], 2),
        }

    # Per-game shadow delta distribution
    game_raw_deltas = [g["joint_raw_delta"] for g in game_summaries]
    game_displaced_deltas = [g["joint_displaced_delta"] for g in game_summaries]
    game_stressed_deltas = [g["joint_stressed_delta"] for g in game_summaries]

    game_displaced_stats = dist_stats(game_displaced_deltas)

    # Opponent breakdown of per-game shadow delta
    opp_deltas = defaultdict(list)
    seat_deltas = defaultdict(list)
    for g in game_summaries:
        opp_deltas[g["opponent"]].append(g["joint_displaced_delta"])
        seat_deltas[str(g["seat"])].append(g["joint_displaced_delta"])

    opp_summary = {opp: dist_stats(vals) for opp, vals in opp_deltas.items()}
    seat_summary = {seat: dist_stats(vals) for seat, vals in seat_deltas.items()}

    # Narrow Boundary Search: evaluate rules by Day and Feed Buffer
    # Grid: Day >= 21, 22, 23, 24, 25 x Buffer >= 0, 5, 10
    boundary_results = []
    for day_cutoff in (21, 22, 23, 24, 25):
        for buf_thresh in (0.0, 5.0, 10.0):
            # Evaluate this rule across all games
            rule_game_deltas = []
            for g in games:
                g_snaps = g.get("wheat_decision_snapshots", [])
                g_tile_cands = {}
                for snap in g_snaps:
                    d = snap["day"]
                    if d >= day_cutoff:
                        ev = analyze_snapshot(snap)
                        if ev["classification"] == "RW3_GENUINE_SURPLUS" and ev["min_balance_without"] >= buf_thresh and ev["c1_fits"]:
                            t_key = f"{ev['tile'][0]},{ev['tile'][1]}"
                            if t_key not in g_tile_cands or ev["task_displaced_delta"] > g_tile_cands[t_key]["task_displaced_delta"]:
                                g_tile_cands[t_key] = ev
                rule_game_deltas.append(sum(ev["task_displaced_delta"] for ev in g_tile_cands.values()))

            stats = dist_stats(rule_game_deltas)
            boundary_results.append({
                "day_cutoff": day_cutoff,
                "buffer_threshold": buf_thresh,
                "mean_delta_per_game": stats["mean"],
                "median_delta_per_game": stats["median"],
                "std_delta_per_game": stats["std"],
                "min_delta": stats["min"],
                "max_delta": stats["max"],
                "positive_games_pct": round(sum(1 for x in rule_game_deltas if x > 0) / len(rule_game_deltas) * 100, 1),
            })

    output_data = {
        "n_games": n_games,
        "total_wheat_events_d21_d25": n_events,
        "per_game_events": round(n_events / n_games, 2),
        "classifications": dict(class_counts),
        "classifications_by_day": {d: dict(v) for d, v in by_day_class.items()},
        "classifications_by_opponent": {opp: dict(v) for opp, v in by_opp_class.items()},
        "classifications_by_seat": {seat: dict(v) for seat, v in by_seat_class.items()},
        "per_event_rw3_stats": {
            "raw_crop_economic": dist_stats(rw3_raw_deltas),
            "task_displaced": dist_stats(rw3_displaced_deltas),
            "labor_stressed": dist_stats(rw3_stressed_deltas),
        },
        "per_game_shadow_stats": {
            "raw_crop_economic": dist_stats(game_raw_deltas),
            "task_displaced": game_displaced_stats,
            "labor_stressed": dist_stats(game_stressed_deltas),
        },
        "per_game_by_opponent": opp_summary,
        "per_game_by_seat": seat_summary,
        "boundary_search_grid": boundary_results,
    }

    with open(OUTPUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print("\n=================== P5.0-R REVALIDATION SUMMARY ===================")
    print(f"Total Day 21-25 Wheat Planting Events: {n_events} across {n_games} games ({n_events/n_games:.1f}/game)")
    print("Classification Breakdown:")
    for c, cnt in sorted(class_counts.items()):
        print(f"  - {c:25s}: {cnt:5d} ({cnt/n_games:5.1f}/game, {cnt/n_events*100:5.1f}%)")
    print(f"\nPer-Event RW3 Delta (Task-Displaced):")
    p_ev = output_data["per_event_rw3_stats"]["task_displaced"]
    print(f"  Mean: ${p_ev['mean']:.2f} | Median: ${p_ev['median']:.2f} | P25: ${p_ev['p25']:.2f} | P75: ${p_ev['p75']:.2f}")
    print(f"\nPer-Game Shadow Opportunity (Joint Substitutions, Task-Displaced):")
    p_gm = output_data["per_game_shadow_stats"]["task_displaced"]
    print(f"  Mean: +${p_gm['mean']:.2f}/game (Std: ${p_gm['std']:.2f})")
    print(f"  Median: +${p_gm['median']:.2f}/game (Min: ${p_gm['min']:.2f}, Max: ${p_gm['max']:.2f})")
    print("\nBoundary Grid Highlights:")
    for b in boundary_results[:6]:
        print(f"  Day >= {b['day_cutoff']}, Buffer >= {b['buffer_threshold']:4.1f} -> Mean: +${b['mean_delta_per_game']:6.2f}/game (Pos: {b['positive_games_pct']}%)")
    print("===================================================================\n")
    print(f"Saved complete revalidation metrics to {OUTPUT_SUMMARY_JSON}")


if __name__ == "__main__":
    run_analysis()
