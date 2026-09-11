#!/usr/bin/env python3
"""
Diagnostic-Only Attribution Audit: Architecture A vs Architecture D2.

Compares:
  A  = historical_stack (historical candidate discipline + legacy_compose_market)
  D2 = historical_candidates_central (historical candidate discipline + corrected CentralPlanner)

Population:
  Seeds 101–125 x Opponents [random, starter] = 50 paired scenarios (100 matches).

Strictly diagnostic:
  - Zero changes to strategy constants
  - Zero changes to CentralPlanner logic
  - Zero changes to candidate limits
  - Validates candidate stream equivalence before arbitration
  - Captures turn-by-turn divergences, first divergences, downstream trajectories,
    sell-loss attribution, purchase attribution, hour patterns, and endgame dynamics.
"""

import argparse
import copy
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIR = os.path.join(REPO_ROOT, "agent")
for p in (REPO_ROOT, AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)
for sub in ("state", "strategy", "execution", "market"):
    sub_p = os.path.join(AGENT_DIR, sub)
    if sub_p not in sys.path:
        sys.path.insert(0, sub_p)

from market.price_math import market_price
import config


def get_order_kind(order: List[Any]) -> str:
    """Classify market order into a high-level domain type."""
    if not order:
        return "UNKNOWN"
    cmd = order[0]
    if cmd == "HIRE":
        return "HIRE"
    if cmd == "BUY_LAND":
        return "LAND"
    if cmd == "BUY_ANIMAL":
        return "ANIMAL"
    if cmd == "SELL":
        return "SELL"
    if cmd == "BUY_PRODUCT":
        if len(order) > 1:
            prod = order[1]
            if prod == "WHEAT":
                return "WHEAT"
            if prod == "FERTILIZER":
                return "FERTILIZER"
            return "SEED"
        return "SEED"
    return "OTHER"


def classify_divergent_orders(
    A_orders: List[List[Any]],
    D2_orders: List[List[Any]],
) -> Tuple[str, List[Tuple[Any, ...]], List[Tuple[Any, ...]]]:
    """Classify divergence between A and D2 order selections."""
    A_tuples = [tuple(o) for o in A_orders]
    D2_tuples = [tuple(o) for o in D2_orders]

    cA = Counter(A_tuples)
    cD2 = Counter(D2_tuples)

    if cA == cD2:
        if A_tuples == D2_tuples:
            return "SAME_ACTION_LIST", [], []
        return "execution_reorder_only", [], []

    # Multisets differ
    A_only = list((cA - cD2).elements())
    D2_only = list((cD2 - cA).elements())

    kinds_A = set(get_order_kind(list(o)) for o in A_only)
    kinds_D2 = set(get_order_kind(list(o)) for o in D2_only)

    # Detect primary conflict category
    # Check X_vs_SELL
    if "SELL" in kinds_A and kinds_D2 - {"SELL"}:
        p_kinds = kinds_D2 - {"SELL"}
        for k in ["LAND", "HIRE", "WHEAT", "SEED", "ANIMAL", "FERTILIZER"]:
            if k in p_kinds:
                return f"{k}_vs_SELL", A_only, D2_only
        return "PURCHASE_vs_SELL", A_only, D2_only

    if "SELL" in kinds_D2 and kinds_A - {"SELL"}:
        p_kinds = kinds_A - {"SELL"}
        for k in ["LAND", "HIRE", "WHEAT", "SEED", "ANIMAL", "FERTILIZER"]:
            if k in p_kinds:
                return f"{k}_vs_SELL", A_only, D2_only
        return "PURCHASE_vs_SELL", A_only, D2_only

    # Purchase vs Purchase conflicts
    p_priority = ["LAND", "HIRE", "WHEAT", "SEED", "ANIMAL", "FERTILIZER"]
    all_purchases = (kinds_A | kinds_D2) - {"SELL"}
    if len(all_purchases) >= 2:
        ordered_p = [k for k in p_priority if k in all_purchases]
        if len(ordered_p) >= 2:
            return f"{ordered_p[0]}_vs_{ordered_p[1]}", A_only, D2_only

    if kinds_A <= {"SELL"} and kinds_D2 <= {"SELL"}:
        return "SELL_vs_SELL", A_only, D2_only

    if not (kinds_A & {"SELL"}) and not (kinds_D2 & {"SELL"}):
        return "PURCHASE_vs_PURCHASE", A_only, D2_only

    return "OTHER", A_only, D2_only


def _run_single_match(
    seed: int,
    opponent_name: str,
    mode: str,
    episode_steps: int = 720,
) -> Dict[str, Any]:
    """Run an isolated match with turn-by-turn telemetry collection."""
    from kaggle_environments import make
    import main as agent_module

    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode(mode)

    turn_telemetry: List[Dict[str, Any]] = []

    def wrapped_agent(obs, config=None):
        act = agent_module.agent(obs, config)
        tel = agent_module.get_last_turn_telemetry()
        if tel is not None:
            # Augment with current spot prices
            market_inv = tel.get("market_inventory_before", {})
            spot_prices = {}
            for prod in ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]:
                inv = market_inv.get(prod, 10000)
                spot_prices[prod] = market_price(prod, inv)
            tel["spot_prices"] = spot_prices
            turn_telemetry.append(tel)
        return act

    opp = opponent_name

    env = make(
        "kaggriculture",
        configuration={"seed": seed, "episodeSteps": episode_steps},
        debug=False,
    )
    env.run([wrapped_agent, opp])

    final_step = env.steps[-1]
    obs0 = final_step[0].observation
    farm0 = obs0["farms"][0]
    farm1 = obs0["farms"][1]
    private0 = obs0.get("private", {})

    final_money = float(farm0.get("money", 0.0))
    opp_final_money = float(farm1.get("money", 0.0))

    # Track land unlock days, spend, and crops
    ne_unlock_day = None
    sw_unlock_day = None
    total_sell_orders = 0
    total_sell_revenue = 0.0
    total_wheat_spend = 0.0
    total_seed_spend = 0.0
    total_hires_spend = 0.0
    hires_by_day: Dict[int, int] = defaultdict(int)

    for tel in turn_telemetry:
        day = tel.get("day", 0)
        unlocked = tel.get("unlocked_land", [])
        if "NE" in unlocked and ne_unlock_day is None:
            ne_unlock_day = day
        if "SW" in unlocked and sw_unlock_day is None:
            sw_unlock_day = day

        for o in tel.get("market", []):
            cmd = o[0]
            if cmd == "SELL":
                total_sell_orders += 1
                prod = o[1]
                qty = o[2]
                price = tel.get("spot_prices", {}).get(prod, 0.0)
                total_sell_revenue += qty * price
            elif cmd == "BUY_PRODUCT":
                prod = o[1]
                qty = o[2]
                price = tel.get("spot_prices", {}).get(prod, 0.0)
                if prod == "WHEAT":
                    total_wheat_spend += qty * price
                else:
                    total_seed_spend += qty * price
            elif cmd == "HIRE":
                hires_by_day[day] += 1
                total_hires_spend += 10.0

    return {
        "seed": seed,
        "opponent": opponent_name,
        "mode": mode,
        "final_money": final_money,
        "opp_final_money": opp_final_money,
        "margin": final_money - opp_final_money,
        "ne_unlock_day": ne_unlock_day,
        "sw_unlock_day": sw_unlock_day,
        "total_sell_orders": total_sell_orders,
        "total_sell_revenue": total_sell_revenue,
        "total_wheat_spend": total_wheat_spend,
        "total_seed_spend": total_seed_spend,
        "total_hires_spend": total_hires_spend,
        "hires_by_day": dict(hires_by_day),
        "shed_end": dict(private0.get("shed", {})),
        "telemetry": turn_telemetry,
    }


def _worker_run_pair(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute paired match (A and D2) for one (seed, opponent) in an isolated process."""
    seed = payload["seed"]
    opponent_name = payload["opponent"]
    episode_steps = payload.get("episode_steps", 720)

    # 1. Run Architecture A
    res_A = _run_single_match(seed, opponent_name, "historical_stack", episode_steps)

    # 2. Run Architecture D2
    res_D2 = _run_single_match(seed, opponent_name, "historical_candidates_central", episode_steps)

    tel_A = res_A["telemetry"]
    tel_D2 = res_D2["telemetry"]

    # Assert candidate streams match up to the first divergence
    n_steps = min(len(tel_A), len(tel_D2))
    first_selection_divergence: Optional[Dict[str, Any]] = None
    first_divergence_over_500: Optional[Dict[str, Any]] = None
    candidate_stream_valid = True
    divergent_turns: List[Dict[str, Any]] = []

    for step in range(n_steps):
        tA = tel_A[step]
        tD2 = tel_D2[step]

        day = tA.get("day", 0)
        hour = tA.get("hour", 0)

        p_cand_A = tA.get("purchase_orders", [])
        p_cand_D2 = tD2.get("purchase_orders", [])
        s_cand_A = tA.get("sell_orders", [])
        s_cand_D2 = tD2.get("sell_orders", [])

        orders_A = tA.get("market", [])
        orders_D2 = tD2.get("market", [])

        category, A_only, D2_only = classify_divergent_orders(orders_A, orders_D2)

        # Before any selection divergence, check candidate equality
        if first_selection_divergence is None:
            if [tuple(o) for o in p_cand_A] != [tuple(o) for o in p_cand_D2] or \
               [tuple(o) for o in s_cand_A] != [tuple(o) for o in s_cand_D2]:
                candidate_stream_valid = False

        if category != "SAME_ACTION_LIST":
            # Downstream money tracking
            m1_A = tel_A[step+1]["money_before"] if step + 1 < len(tel_A) else res_A["final_money"]
            m1_D2 = tel_D2[step+1]["money_before"] if step + 1 < len(tel_D2) else res_D2["final_money"]
            m6_A = tel_A[step+6]["money_before"] if step + 6 < len(tel_A) else res_A["final_money"]
            m6_D2 = tel_D2[step+6]["money_before"] if step + 6 < len(tel_D2) else res_D2["final_money"]
            m24_A = tel_A[step+24]["money_before"] if step + 24 < len(tel_A) else res_A["final_money"]
            m24_D2 = tel_D2[step+24]["money_before"] if step + 24 < len(tel_D2) else res_D2["final_money"]

            div_info = {
                "step": step,
                "day": day,
                "hour": hour,
                "category": category,
                "orders_A": [list(o) for o in orders_A],
                "orders_D2": [list(o) for o in orders_D2],
                "A_only": [list(o) for o in A_only],
                "D2_only": [list(o) for o in D2_only],
                "money_before_A": tA.get("money_before", 0.0),
                "money_before_D2": tD2.get("money_before", 0.0),
                "money_after_1_A": m1_A,
                "money_after_1_D2": m1_D2,
                "money_after_6_A": m6_A,
                "money_after_6_D2": m6_D2,
                "money_after_24_A": m24_A,
                "money_after_24_D2": m24_D2,
                "shed_before_A": tA.get("shed_before", 0),
                "shed_before_D2": tD2.get("shed_before", 0),
                "spot_prices": tA.get("spot_prices", {}),
                "is_selection_divergence": (category != "execution_reorder_only"),
            }
            divergent_turns.append(div_info)

            if category != "execution_reorder_only" and first_selection_divergence is None:
                first_selection_divergence = copy.deepcopy(div_info)

            # Estimate order value difference
            est_val = 0.0
            for o in A_only:
                cmd = o[0]
                if cmd == "SELL":
                    est_val += o[2] * tA.get("spot_prices", {}).get(o[1], 25.0)
                elif cmd == "BUY_PRODUCT":
                    est_val += o[2] * tA.get("spot_prices", {}).get(o[1], 25.0)
                elif cmd == "BUY_LAND":
                    est_val += 1000.0
            if est_val >= 500.0 and first_divergence_over_500 is None and category != "execution_reorder_only":
                first_divergence_over_500 = copy.deepcopy(div_info)

    # Clean telemetry from return payload to conserve IPC memory
    del res_A["telemetry"]
    del res_D2["telemetry"]

    money_delta = res_D2["final_money"] - res_A["final_money"]
    d2_won = (money_delta > 0)

    return {
        "seed": seed,
        "opponent": opponent_name,
        "final_money_A": res_A["final_money"],
        "final_money_D2": res_D2["final_money"],
        "delta": money_delta,
        "d2_won": d2_won,
        "candidate_stream_valid": candidate_stream_valid,
        "first_selection_divergence": first_selection_divergence,
        "first_divergence_over_500": first_divergence_over_500,
        "divergent_turns": divergent_turns,
        "summary_A": res_A,
        "summary_D2": res_D2,
    }


def run_attribution_audit(
    seeds: List[int],
    opponents: List[str],
    workers: int = 4,
    episode_steps: int = 720,
) -> Dict[str, Any]:
    """Run the 50-pair attribution audit and compute full statistical breakdowns."""
    payloads = [
        {"seed": s, "opponent": opp, "episode_steps": episode_steps}
        for s in seeds
        for opp in opponents
    ]

    total_pairs = len(payloads)
    print(f"Running Attribution Audit across {total_pairs} paired scenarios using {workers} workers...")
    start_time = time.time()

    pair_results: List[Dict[str, Any]] = []
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        future_map = {pool.submit(_worker_run_pair, p): p for p in payloads}
        completed = 0
        for f in as_completed(future_map):
            completed += 1
            res = f.result()
            pair_results.append(res)
            print(
                f"[{completed:02d}/{total_pairs:02d}] Seed {res['seed']} | {res['opponent']:7s} | "
                f"A: ${res['final_money_A']:,.0f} | D2: ${res['final_money_D2']:,.0f} | "
                f"Delta: ${res['delta']:+,.0f}"
            )

    elapsed = time.time() - start_time
    print(f"Audit completed in {elapsed:.1f}s.\n")

    # 1. Aggregate Score Statistics
    deltas = [r["delta"] for r in pair_results]
    a_scores = [r["final_money_A"] for r in pair_results]
    d2_scores = [r["final_money_D2"] for r in pair_results]

    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    ties = sum(1 for d in deltas if d == 0)

    # 2. Divergence Categories Tracking
    cat_counts_total: Counter = Counter()
    cat_counts_losses: Counter = Counter()
    cat_counts_wins: Counter = Counter()
    cat_scenarios: Dict[str, Set[Tuple[int, str]]] = defaultdict(set)
    cat_deltas: Dict[str, List[float]] = defaultdict(list)

    # Hour bands
    hour_band_counts: Counter = Counter()
    hour_band_deltas: Dict[str, List[float]] = defaultdict(list)

    # Total divergence turns
    total_divergent_turns = 0
    total_selection_divergent_turns = 0
    total_reorder_only_turns = 0

    # Sell loss attribution: sales in A but not D2
    sell_loss_by_product: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "total_orders": 0,
            "total_qty": 0,
            "total_est_rev": 0.0,
            "sale_delayed_but_recovered": 0,
            "sale_delayed_lower_price": 0,
            "sale_never_executed": 0,
            "sale_delayed_higher_price": 0,
        }
    )

    # Purchase displacement attribution: purchases in D2 but not A
    purchase_disp_by_type: Counter = Counter()

    for r in pair_results:
        key = (r["seed"], r["opponent"])
        delta = r["delta"]
        is_loss = (delta < 0)

        for div in r["divergent_turns"]:
            cat = div["category"]
            step = div["step"]
            hour = div["hour"]
            day = div["day"]

            total_divergent_turns += 1
            if cat == "execution_reorder_only":
                total_reorder_only_turns += 1
            else:
                total_selection_divergent_turns += 1

            cat_counts_total[cat] += 1
            cat_scenarios[cat].add(key)
            cat_deltas[cat].append(delta)

            if is_loss:
                cat_counts_losses[cat] += 1
            else:
                cat_counts_wins[cat] += 1

            # Hour band
            if hour == 0:
                h_band = "Hour 0"
            elif hour == 1:
                h_band = "Hour 1"
            elif hour in (5, 9, 13, 17, 21):
                h_band = "Sell Window (5,9,13,17,21)"
            elif day >= 28:
                h_band = "Endgame (Day 28-29)"
            else:
                h_band = "Other Hours"

            hour_band_counts[h_band] += 1
            hour_band_deltas[h_band].append(delta)

            # Sells present in A but not D2
            for o in div["A_only"]:
                if o[0] == "SELL":
                    prod = o[1]
                    qty = o[2]
                    price = div["spot_prices"].get(prod, 25.0)
                    rev = qty * price
                    stat = sell_loss_by_product[prod]
                    stat["total_orders"] += 1
                    stat["total_qty"] += qty
                    stat["total_est_rev"] += rev
                    stat["sale_delayed_but_recovered"] += 1

            # Purchases present in D2 but not A
            for o in div["D2_only"]:
                k = get_order_kind(list(o))
                if k != "SELL":
                    purchase_disp_by_type[k] += 1

    # 3. Land Timing Comparison
    land_ne_deltas = []
    land_sw_deltas = []
    for r in pair_results:
        ne_A = r["summary_A"]["ne_unlock_day"]
        ne_D2 = r["summary_D2"]["ne_unlock_day"]
        sw_A = r["summary_A"]["sw_unlock_day"]
        sw_D2 = r["summary_D2"]["sw_unlock_day"]
        if ne_A is not None and ne_D2 is not None:
            land_ne_deltas.append(ne_D2 - ne_A)
        if sw_A is not None and sw_D2 is not None:
            land_sw_deltas.append(sw_D2 - sw_A)

    # 4. Hires Timing Comparison
    hires_diffs = []
    for r in pair_results:
        hA = sum(r["summary_A"]["hires_by_day"].values())
        hD2 = sum(r["summary_D2"]["hires_by_day"].values())
        hires_diffs.append(hD2 - hA)

    # 5. First Divergence Analysis
    first_div_categories = Counter()
    first_div_500_categories = Counter()
    for r in pair_results:
        if r["first_selection_divergence"]:
            first_div_categories[r["first_selection_divergence"]["category"]] += 1
        if r["first_divergence_over_500"]:
            first_div_500_categories[r["first_divergence_over_500"]["category"]] += 1

    audit_summary = {
        "total_pairs": total_pairs,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "mean_A": float(np.mean(a_scores)),
        "mean_D2": float(np.mean(d2_scores)),
        "mean_delta": float(np.mean(deltas)),
        "median_delta": float(np.median(deltas)),
        "std_delta": float(np.std(deltas)),
        "min_delta": float(np.min(deltas)),
        "max_delta": float(np.max(deltas)),
        "p10_delta": float(np.percentile(deltas, 10)),
        "p25_delta": float(np.percentile(deltas, 25)),
        "p75_delta": float(np.percentile(deltas, 75)),
        "p90_delta": float(np.percentile(deltas, 90)),
        "total_divergent_turns": total_divergent_turns,
        "total_selection_divergent_turns": total_selection_divergent_turns,
        "total_reorder_only_turns": total_reorder_only_turns,
        "cat_counts_total": dict(cat_counts_total),
        "cat_counts_losses": dict(cat_counts_losses),
        "cat_counts_wins": dict(cat_counts_wins),
        "hour_band_counts": dict(hour_band_counts),
        "first_div_categories": dict(first_div_categories),
        "first_div_500_categories": dict(first_div_500_categories),
        "sell_loss_by_product": dict(sell_loss_by_product),
        "purchase_disp_by_type": dict(purchase_disp_by_type),
        "land_ne_deltas": land_ne_deltas,
        "land_sw_deltas": land_sw_deltas,
        "hires_diffs": hires_diffs,
        "pair_results": pair_results,
    }

    return audit_summary


def save_artifacts(audit: Dict[str, Any], out_csv: str, out_json: str) -> None:
    """Save machine-readable audit artifacts."""
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    os.makedirs(os.path.dirname(out_json), exist_ok=True)

    # 1. JSON Export
    with open(out_json, "w") as f:
        json.dump(audit, f, indent=2)
    print(f"Saved JSON artifact: {out_json}")

    # 2. CSV Export of Per-Scenario Summaries
    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seed", "opponent", "final_money_A", "final_money_D2", "delta",
            "d2_won", "candidate_stream_valid", "first_div_day", "first_div_hour",
            "first_div_category", "ne_day_A", "ne_day_D2", "sw_day_A", "sw_day_D2",
            "sell_rev_A", "sell_rev_D2", "wheat_spend_A", "wheat_spend_D2"
        ])
        for r in audit["pair_results"]:
            fd = r.get("first_selection_divergence") or {}
            writer.writerow([
                r["seed"],
                r["opponent"],
                f"{r['final_money_A']:.2f}",
                f"{r['final_money_D2']:.2f}",
                f"{r['delta']:.2f}",
                r["d2_won"],
                r["candidate_stream_valid"],
                fd.get("day", ""),
                fd.get("hour", ""),
                fd.get("category", "NONE"),
                r["summary_A"].get("ne_unlock_day", ""),
                r["summary_D2"].get("ne_unlock_day", ""),
                r["summary_A"].get("sw_unlock_day", ""),
                r["summary_D2"].get("sw_unlock_day", ""),
                f"{r['summary_A'].get('total_sell_revenue', 0.0):.2f}",
                f"{r['summary_D2'].get('total_sell_revenue', 0.0):.2f}",
                f"{r['summary_A'].get('total_wheat_spend', 0.0):.2f}",
                f"{r['summary_D2'].get('total_wheat_spend', 0.0):.2f}",
            ])
    print(f"Saved CSV artifact: {out_csv}")


def print_audit_report(audit: Dict[str, Any]) -> None:
    """Print human-readable audit diagnostics."""
    print("=" * 85)
    print("          ATTRIBUTION AUDIT: ARCHITECTURE A vs ARCHITECTURE D2           ")
    print("=" * 85)
    print(f"Paired Matches Evaluated: {audit['total_pairs']}")
    print(f"Architecture A Mean:      ${audit['mean_A']:,.2f}")
    print(f"Architecture D2 Mean:     ${audit['mean_D2']:,.2f}")
    print(f"Mean Delta (D2 - A):      ${audit['mean_delta']:+,.2f}")
    print(f"Median Delta:             ${audit['median_delta']:+,.2f}")
    print(f"Delta Range:              Min ${audit['min_delta']:+,.2f} | Max ${audit['max_delta']:+,.2f}")
    print(f"P10 / P25 / P75 / P90:    ${audit['p10_delta']:+,.2f} / ${audit['p25_delta']:+,.2f} / ${audit['p75_delta']:+,.2f} / ${audit['p90_delta']:+,.2f}")
    print(f"Win / Loss / Tie:         {audit['wins']} Wins / {audit['losses']} Losses / {audit['ties']} Ties")
    print("-" * 85)
    print(f"Total Divergent Turns:           {audit['total_divergent_turns']}")
    print(f"Selection Divergent Turns:       {audit['total_selection_divergent_turns']}")
    print(f"Execution Reorder Only Turns:    {audit['total_reorder_only_turns']}")
    print("-" * 85)
    print("\n--- DIVERGENCE CATEGORIES BY FREQUENCY & OUTCOME ---")
    print(f"{'Category':<25} | {'Total':<6} | {'In Losses':<10} | {'In Wins':<8} | {'Loss Ratio':<10}")
    print("-" * 65)
    for cat, total in Counter(audit["cat_counts_total"]).most_common():
        n_loss = audit["cat_counts_losses"].get(cat, 0)
        n_win = audit["cat_counts_wins"].get(cat, 0)
        ratio = (n_loss / total * 100.0) if total > 0 else 0.0
        print(f"{cat:<25} | {total:<6} | {n_loss:<10} | {n_win:<8} | {ratio:>8.1f}%")

    print("\n--- FIRST SELECTION DIVERGENCE PER EPISODE ---")
    print(f"{'Category':<25} | {'Episodes':<8}")
    print("-" * 35)
    for cat, count in Counter(audit["first_div_categories"]).most_common():
        print(f"{cat:<25} | {count:<8}")

    print("\n--- FIRST DIVERGENCE > $500 PER EPISODE ---")
    print(f"{'Category':<25} | {'Episodes':<8}")
    print("-" * 35)
    for cat, count in Counter(audit["first_div_500_categories"]).most_common():
        print(f"{cat:<25} | {count:<8}")

    print("\n--- HOUR BAND DISTRIBUTION ---")
    print(f"{'Hour Band':<30} | {'Divergences':<12}")
    print("-" * 45)
    for band, count in Counter(audit["hour_band_counts"]).most_common():
        print(f"{band:<30} | {count:<12}")

    print("\n--- SELL LOSS ATTRIBUTION (Sales present in A but omitted in D2) ---")
    print(f"{'Product':<15} | {'Orders':<8} | {'Quantity':<10} | {'Est. Revenue':<14}")
    print("-" * 55)
    for prod, stat in audit["sell_loss_by_product"].items():
        print(f"{prod:<15} | {stat['total_orders']:<8} | {stat['total_qty']:<10} | ${stat['total_est_rev']:<12,.2f}")

    print("\n--- PURCHASES SELECTED BY D2 INSTEAD OF A's ORDERS ---")
    print(f"{'Purchase Type':<20} | {'Count':<8}")
    print("-" * 30)
    for k, count in Counter(audit["purchase_disp_by_type"]).most_common():
        print(f"{k:<20} | {count:<8}")

    print("=" * 85)


def main():
    parser = argparse.ArgumentParser(description="Attribution Audit comparing Architecture A vs D2.")
    parser.add_argument("--seeds", type=int, default=25, help="Number of seeds (default: 25)")
    parser.add_argument("--start-seed", type=int, default=101, help="Starting seed (default: 101)")
    parser.add_argument("--opponents", nargs="+", default=["random", "starter"], help="Opponent list")
    parser.add_argument("--workers", type=int, default=4, help="Number of workers (default: 4)")
    parser.add_argument("--episode-steps", type=int, default=720, help="Episode steps (default: 720)")
    parser.add_argument(
        "--out-csv",
        type=str,
        default=os.path.join(REPO_ROOT, "artifacts", "central_planner_A_vs_D2_attribution.csv"),
    )
    parser.add_argument(
        "--out-json",
        type=str,
        default=os.path.join(REPO_ROOT, "artifacts", "central_planner_A_vs_D2_attribution.json"),
    )
    args = parser.parse_args()

    seed_list = list(range(args.start_seed, args.start_seed + args.seeds))
    audit = run_attribution_audit(
        seeds=seed_list,
        opponents=args.opponents,
        workers=args.workers,
        episode_steps=args.episode_steps,
    )

    save_artifacts(audit, args.out_csv, args.out_json)
    print_audit_report(audit)


if __name__ == "__main__":
    main()
