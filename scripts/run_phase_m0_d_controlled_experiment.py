"""Phase M0-D: Controlled Discovery Experiment for Authoritative Storage Rescue.

Evaluates 2 arms across the consumed discovery panel:
Seeds 97013–97022 x 5 opponents x 2 seats = 100 scenario cells (200 matches).
- C0: CONTROL (MIDNIGHT_STORAGE_DUMP_MODE = "OFF")
- C2: RESCUE  (MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE")

Features Authoritative Ground-Truth Instrumentation for:
- Carried worker inventory at midnight before drop
- Deposited units entering shed
- Discarded units destroyed by engine
- Item-by-item discard breakdown and spot valuation
- Exact conservation check: carried == deposited + discarded
- Rescue execution telemetry (rescue_events, rescue_units_sold, etc.)
- Cluster-robust standard errors & 95% CIs clustered by seed (10 clusters)
- Unified percentiles (median == p50)
- Decision Gates B and C evaluation

Deliverables under simulations/results/phase_m0_d_storage_rescue/:
- manifest.json
- matched_results.json
- aggregate_tables.json
- clustered_statistics.json
- storage_and_overflow.json
- decision_gates.json
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_d_storage_rescue")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_SEEDS = list(range(97013, 97023))  # 97013–97022 (Consumed discovery seeds)
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]
ARMS = ["C0", "C2"]

PRODUCT_BASE_PRICES = {
    "WHEAT": 25.0,
    "CARROT": 35.0,
    "TOMATO": 60.0,
    "STRAWBERRY": 120.0,
    "MELON": 250.0,
    "EGG": 50.0,
    "MILK": 160.0,
    "WOOL": 200.0,
    "FERTILIZER": 100.0,
}


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


def compute_unified_percentiles(vals: List[float]) -> Dict[str, float]:
    if not vals:
        return {"mean": 0.0, "std": 0.0, "median": 0.0, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    arr = np.array(vals, dtype=float)
    med = float(np.median(arr))
    p50 = float(np.percentile(arr, 50))
    assert math.isclose(med, p50, rel_tol=1e-7), f"Percentile mismatch: med={med} vs p50={p50}"
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        "median": med,
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "p50": p50,
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
    }


def compute_clustered_stats(pairs: List[Dict[str, Any]], metric_fn) -> Dict[str, Any]:
    """Compute cluster-robust standard errors and 95% CIs clustered by seed."""
    if not pairs:
        return {}
    seed_clusters: Dict[int, List[float]] = {}
    all_diffs: List[float] = []

    for p in pairs:
        d = float(metric_fn(p))
        s = p["seed"]
        seed_clusters.setdefault(s, []).append(d)
        all_diffs.append(d)

    cluster_means = [float(np.mean(vals)) for vals in seed_clusters.values()]
    G = len(cluster_means)  # number of clusters
    overall_mean = float(np.mean(all_diffs))

    if G > 1:
        s_bar = float(np.std(cluster_means, ddof=1))
        se_clustered = s_bar / math.sqrt(G)
        # t-distribution critical values for df = G - 1
        t_crit_map = {9: 2.262157, 10: 2.228139, 19: 2.093024}
        t_crit = t_crit_map.get(G - 1, 2.262)
        ci_lower = overall_mean - t_crit * se_clustered
        ci_upper = overall_mean + t_crit * se_clustered
    else:
        se_clustered = 0.0
        ci_lower = overall_mean
        ci_upper = overall_mean

    stats = compute_unified_percentiles(all_diffs)
    stats.update({
        "cluster_count": G,
        "cluster_means": {s: float(np.mean(vals)) for s, vals in sorted(seed_clusters.items())},
        "se_clustered": se_clustered,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
    })
    return stats


def run_single_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
    from agent.main import agent, reset_agent_state
    import config
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent
    from execution.midnight_storage_controller import get_midnight_storage_telemetry

    # Configure modes
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"

    if arm == "C0":
        config.set_midnight_storage_dump_mode("OFF")
    elif arm == "C2":
        config.set_midnight_storage_dump_mode("RESCUE")
    else:
        raise ValueError(f"Unknown arm: {arm}")

    reset_agent_state()
    reset_sw_tranche_controller()

    daily_events: List[Dict[str, Any]] = []
    call_count = [0]
    orig_drop = kengine._drop_inventories_to_shed

    def instrumented_drop(private, capacity):
        p_id = call_count[0] % 2
        day = call_count[0] // 2
        call_count[0] += 1

        if p_id == seat:
            carried = {}
            for inv in private["inventories"]:
                for k, v in inv.items():
                    if v > 0:
                        carried[k] = carried.get(k, 0) + v
            shed_pre = dict(private["shed"])
            orig_drop(private, capacity)
            shed_post = dict(private["shed"])

            dep = {}
            for k in set(shed_pre.keys()).union(shed_post.keys()):
                d = shed_post.get(k, 0) - shed_pre.get(k, 0)
                if d > 0:
                    dep[k] = d

            disc = {}
            for k, v in carried.items():
                diff = v - dep.get(k, 0)
                if diff > 0:
                    disc[k] = diff

            c_tot = sum(carried.values())
            d_tot = sum(dep.values())
            x_tot = sum(disc.values())
            assert c_tot == d_tot + x_tot, f"Conservation violation: {c_tot} != {d_tot} + {x_tot}"

            daily_events.append({
                "day": day,
                "carried": carried,
                "shed_pre": shed_pre,
                "shed_post": shed_post,
                "deposited": dep,
                "discarded": disc,
                "carried_total": c_tot,
                "deposited_total": d_tot,
                "discarded_total": x_tot,
            })
        else:
            orig_drop(private, capacity)

    kengine._drop_inventories_to_shed = instrumented_drop

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    storage_stats = {
        "peak_shed_occupancy": 0,
        "shed_turns_ge_90": 0,
        "shed_turns_ge_95": 0,
        "shed_turns_at_capacity": 0,
    }

    step_num = 0
    try:
        while not env.done:
            obs_pre = env.state[seat].observation
            priv_pre = obs_pre.private
            shed_items = sum(priv_pre.shed.values()) if hasattr(priv_pre, "shed") else 0

            if shed_items > storage_stats["peak_shed_occupancy"]:
                storage_stats["peak_shed_occupancy"] = shed_items
            if shed_items >= 90:
                storage_stats["shed_turns_ge_90"] += 1
            if shed_items >= 95:
                storage_stats["shed_turns_ge_95"] += 1
            if shed_items >= 100:
                storage_stats["shed_turns_at_capacity"] += 1

            action = agent(obs_pre, env.configuration)
            try:
                opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
            except TypeError:
                opp_action = opp_agent(env.state[1 - seat].observation)

            actions = [action, opp_action] if seat == 0 else [opp_action, action]
            env.step(actions)
            step_num += 1
    finally:
        kengine._drop_inventories_to_shed = orig_drop

    final_reward = env.steps[-1][seat].reward or 0.0
    opp_reward = env.steps[-1][1 - seat].reward or 0.0
    final_cash = float(final_reward)
    opp_cash = float(opp_reward)

    tot_carried = sum(e["carried_total"] for e in daily_events)
    tot_deposited = sum(e["deposited_total"] for e in daily_events)
    tot_discarded = sum(e["discarded_total"] for e in daily_events)
    assert tot_carried == tot_deposited + tot_discarded

    discarded_by_item: Dict[str, int] = {}
    spot_value_lost = 0.0
    for e in daily_events:
        for k, v in e["discarded"].items():
            discarded_by_item[k] = discarded_by_item.get(k, 0) + v
            spot_value_lost += v * PRODUCT_BASE_PRICES.get(k, 25.0)

    overflow_days = [e["day"] for e in daily_events if e["discarded_total"] > 0]
    telem = get_midnight_storage_telemetry()

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "arm": arm,
        "final_cash": final_cash,
        "opp_cash": opp_cash,
        "total_carried_units": tot_carried,
        "total_deposited_units": tot_deposited,
        "total_discarded_units": tot_discarded,
        "discarded_by_item": discarded_by_item,
        "spot_value_lost": spot_value_lost,
        "overflow_days_count": len(overflow_days),
        "overflow_days": overflow_days,
        "storage_stats": storage_stats,
        "rescue_events": telem.get("rescue_events", 0),
        "rescue_units_sold": telem.get("rescue_units_sold", 0),
        "rescue_orders_emitted": telem.get("rescue_orders_emitted", 0),
        "rescue_products_sold": telem.get("rescue_products_sold", {}),
        "conservation_verified": True,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-D Controlled Experiment")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel worker processes")
    args = parser.parse_args()

    git_commit = get_git_commit()
    print(f"=== Phase M0-D Controlled Storage Rescue Experiment ===")
    print(f"Git commit: {git_commit}")
    print(f"Discovery panel: {len(DEFAULT_SEEDS)} seeds x {len(BENCHMARK_OPPONENTS)} opps x {len(SEATS)} seats = 100 pairs (200 matches)")
    print(f"Workers: {args.workers}")

    # Build tasks: 100 cells x 2 arms = 200 match runs
    match_tasks = []
    for seed in DEFAULT_SEEDS:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                for arm in ARMS:
                    match_tasks.append((seed, opp, seat, arm))

    raw_results: Dict[Tuple[int, str, int, str], Dict[str, Any]] = {}
    start_time = time.time()
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(run_single_match, seed, opp, seat, arm): (seed, opp, seat, arm)
            for (seed, opp, seat, arm) in match_tasks
        }

        for future in as_completed(future_map):
            task_key = future_map[future]
            try:
                res = future.result()
                raw_results[task_key] = res
                completed += 1
                if completed % 10 == 0 or completed == len(match_tasks):
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(f"[{completed:3d}/{len(match_tasks)}] matches completed ({rate:.1f} matches/sec)")
            except Exception as e:
                print(f"Error on match {task_key}: {e}")
                raise

    # Assemble matched pairs
    matched_pairs: List[Dict[str, Any]] = []
    for seed in DEFAULT_SEEDS:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                r_c0 = raw_results[(seed, opp, seat, "C0")]
                r_c2 = raw_results[(seed, opp, seat, "C2")]

                cash_c0 = r_c0["final_cash"]
                cash_c2 = r_c2["final_cash"]
                delta_cash = cash_c2 - cash_c0

                disc_c0 = r_c0["total_discarded_units"]
                disc_c2 = r_c2["total_discarded_units"]
                delta_disc = disc_c2 - disc_c0
                disc_reduction_units = disc_c0 - disc_c2
                disc_reduction_pct = (disc_reduction_units / disc_c0 * 100.0) if disc_c0 > 0 else 0.0

                val_lost_c0 = r_c0["spot_value_lost"]
                val_lost_c2 = r_c2["spot_value_lost"]
                val_preserved = val_lost_c0 - val_lost_c2

                h2h_res = "WIN" if cash_c2 > cash_c0 else ("LOSS" if cash_c2 < cash_c0 else "TIE")
                opp_c0_res = "WIN" if cash_c0 > r_c0["opp_cash"] else ("LOSS" if cash_c0 < r_c0["opp_cash"] else "TIE")
                opp_c2_res = "WIN" if cash_c2 > r_c2["opp_cash"] else ("LOSS" if cash_c2 < r_c2["opp_cash"] else "TIE")

                pair = {
                    "seed": seed,
                    "opponent": opp,
                    "seat": seat,
                    "c0": r_c0,
                    "c2": r_c2,
                    "delta_cash": delta_cash,
                    "delta_discarded": delta_disc,
                    "discard_reduction_units": disc_reduction_units,
                    "discard_reduction_pct": disc_reduction_pct,
                    "spot_value_preserved": val_preserved,
                    "h2h_vs_c0": h2h_res,
                    "opp_outcome_c0": opp_c0_res,
                    "opp_outcome_c2": opp_c2_res,
                }
                matched_pairs.append(pair)

    # 1. Matched Results File
    matched_results_path = os.path.join(OUT_DIR, "matched_results.json")
    with open(matched_results_path, "w", encoding="utf-8") as f:
        json.dump(matched_pairs, f, indent=2)

    # 2. Clustered Statistics
    cash_stats = compute_clustered_stats(matched_pairs, lambda p: p["delta_cash"])
    disc_reduction_stats = compute_clustered_stats(matched_pairs, lambda p: p["discard_reduction_units"])
    val_preserved_stats = compute_clustered_stats(matched_pairs, lambda p: p["spot_value_preserved"])

    # W/T/L counts
    c2_wins = sum(1 for p in matched_pairs if p["h2h_vs_c0"] == "WIN")
    c2_ties = sum(1 for p in matched_pairs if p["h2h_vs_c0"] == "TIE")
    c2_losses = sum(1 for p in matched_pairs if p["h2h_vs_c0"] == "LOSS")

    clustered_statistics = {
        "meta": {
            "git_commit": git_commit,
            "panel": "Seeds 97013–97022 x 5 opps x 2 seats = 100 pairs",
            "clusters": 10,
        },
        "paired_cash_delta": cash_stats,
        "discard_reduction_units": disc_reduction_stats,
        "spot_value_preserved": val_preserved_stats,
        "head_to_head_vs_c0": {
            "wins": c2_wins,
            "ties": c2_ties,
            "losses": c2_losses,
            "win_rate": c2_wins / len(matched_pairs),
        },
    }
    clustered_path = os.path.join(OUT_DIR, "clustered_statistics.json")
    with open(clustered_path, "w", encoding="utf-8") as f:
        json.dump(clustered_statistics, f, indent=2)

    # 3. Aggregate Tables (Overall, by Opponent, by Seat)
    by_opp: Dict[str, List[Dict[str, Any]]] = {}
    by_seat: Dict[int, List[Dict[str, Any]]] = {}
    for p in matched_pairs:
        by_opp.setdefault(p["opponent"], []).append(p)
        by_seat.setdefault(p["seat"], []).append(p)

    opp_tables = {}
    for opp, opp_pairs in by_opp.items():
        opp_tables[opp] = {
            "n_pairs": len(opp_pairs),
            "cash_delta": compute_unified_percentiles([p["delta_cash"] for p in opp_pairs]),
            "discard_reduction": compute_unified_percentiles([p["discard_reduction_units"] for p in opp_pairs]),
            "spot_value_preserved": compute_unified_percentiles([p["spot_value_preserved"] for p in opp_pairs]),
            "w_t_l": {
                "wins": sum(1 for p in opp_pairs if p["h2h_vs_c0"] == "WIN"),
                "ties": sum(1 for p in opp_pairs if p["h2h_vs_c0"] == "TIE"),
                "losses": sum(1 for p in opp_pairs if p["h2h_vs_c0"] == "LOSS"),
            },
        }

    seat_tables = {}
    for seat, seat_pairs in by_seat.items():
        seat_tables[f"seat_{seat}"] = {
            "n_pairs": len(seat_pairs),
            "cash_delta": compute_unified_percentiles([p["delta_cash"] for p in seat_pairs]),
            "discard_reduction": compute_unified_percentiles([p["discard_reduction_units"] for p in seat_pairs]),
            "spot_value_preserved": compute_unified_percentiles([p["spot_value_preserved"] for p in seat_pairs]),
            "w_t_l": {
                "wins": sum(1 for p in seat_pairs if p["h2h_vs_c0"] == "WIN"),
                "ties": sum(1 for p in seat_pairs if p["h2h_vs_c0"] == "TIE"),
                "losses": sum(1 for p in seat_pairs if p["h2h_vs_c0"] == "LOSS"),
            },
        }

    aggregate_tables = {
        "overall": {
            "n_pairs": len(matched_pairs),
            "cash_c0": compute_unified_percentiles([p["c0"]["final_cash"] for p in matched_pairs]),
            "cash_c2": compute_unified_percentiles([p["c2"]["final_cash"] for p in matched_pairs]),
            "cash_delta": compute_unified_percentiles([p["delta_cash"] for p in matched_pairs]),
            "discarded_c0": compute_unified_percentiles([p["c0"]["total_discarded_units"] for p in matched_pairs]),
            "discarded_c2": compute_unified_percentiles([p["c2"]["total_discarded_units"] for p in matched_pairs]),
            "discard_reduction": compute_unified_percentiles([p["discard_reduction_units"] for p in matched_pairs]),
            "spot_value_preserved": compute_unified_percentiles([p["spot_value_preserved"] for p in matched_pairs]),
        },
        "by_opponent": opp_tables,
        "by_seat": seat_tables,
    }
    agg_path = os.path.join(OUT_DIR, "aggregate_tables.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(aggregate_tables, f, indent=2)

    # 4. Storage & Overflow File
    c0_discard_items: Dict[str, int] = {}
    c2_discard_items: Dict[str, int] = {}
    c2_rescue_products: Dict[str, int] = {}

    for p in matched_pairs:
        for k, v in p["c0"]["discarded_by_item"].items():
            c0_discard_items[k] = c0_discard_items.get(k, 0) + v
        for k, v in p["c2"]["discarded_by_item"].items():
            c2_discard_items[k] = c2_discard_items.get(k, 0) + v
        for k, v in p["c2"]["rescue_products_sold"].items():
            c2_rescue_products[k] = c2_rescue_products.get(k, 0) + v

    tot_c0_discard = sum(p["c0"]["total_discarded_units"] for p in matched_pairs)
    tot_c2_discard = sum(p["c2"]["total_discarded_units"] for p in matched_pairs)
    overall_reduction_pct = ((tot_c0_discard - tot_c2_discard) / tot_c0_discard * 100.0) if tot_c0_discard > 0 else 0.0

    storage_and_overflow = {
        "total_c0_discarded_units": tot_c0_discard,
        "total_c2_discarded_units": tot_c2_discard,
        "overall_discard_reduction_units": tot_c0_discard - tot_c2_discard,
        "overall_discard_reduction_pct": overall_reduction_pct,
        "c0_discard_by_item": c0_discard_items,
        "c2_discard_by_item": c2_discard_items,
        "c2_rescue_products_sold_total": c2_rescue_products,
        "mean_rescue_events_per_match": float(np.mean([p["c2"]["rescue_events"] for p in matched_pairs])),
        "mean_rescue_units_sold_per_match": float(np.mean([p["c2"]["rescue_units_sold"] for p in matched_pairs])),
        "mean_c0_spot_value_lost": float(np.mean([p["c0"]["spot_value_lost"] for p in matched_pairs])),
        "mean_c2_spot_value_lost": float(np.mean([p["c2"]["spot_value_lost"] for p in matched_pairs])),
        "mean_spot_value_preserved": float(np.mean([p["spot_value_preserved"] for p in matched_pairs])),
    }
    storage_path = os.path.join(OUT_DIR, "storage_and_overflow.json")
    with open(storage_path, "w", encoding="utf-8") as f:
        json.dump(storage_and_overflow, f, indent=2)

    # 5. Decision Gates B and C
    gate_b_passed = (overall_reduction_pct >= 50.0) and (storage_and_overflow["mean_spot_value_preserved"] >= 1000.0)
    gate_c_passed = (cash_stats["mean"] > 0) and (cash_stats["median"] > 0)

    decision_gates = {
        "gate_b_storage_preservation": {
            "required_discard_reduction_pct": 50.0,
            "observed_discard_reduction_pct": overall_reduction_pct,
            "required_spot_value_preserved": 1000.0,
            "observed_spot_value_preserved": storage_and_overflow["mean_spot_value_preserved"],
            "passed": gate_b_passed,
        },
        "gate_c_financial_viability": {
            "required_mean_cash_delta": "> 0",
            "observed_mean_cash_delta": cash_stats["mean"],
            "required_median_cash_delta": "> 0",
            "observed_median_cash_delta": cash_stats["median"],
            "ci_95": [cash_stats["ci_95_lower"], cash_stats["ci_95_upper"]],
            "win_rate": clustered_statistics["head_to_head_vs_c0"]["win_rate"],
            "passed": gate_c_passed,
        },
        "overall_recommendation": "PROCEED" if (gate_b_passed and gate_c_passed) else "HOLD",
    }
    gates_path = os.path.join(OUT_DIR, "decision_gates.json")
    with open(gates_path, "w", encoding="utf-8") as f:
        json.dump(decision_gates, f, indent=2)

    # 6. Manifest
    manifest = {
        "git_commit": git_commit,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "discovery_panel": {
            "seeds": DEFAULT_SEEDS,
            "opponents": BENCHMARK_OPPONENTS,
            "seats": SEATS,
            "arms": ARMS,
            "total_matches": len(match_tasks),
            "matched_pairs": len(matched_pairs),
        },
        "deliverables": [
            "manifest.json",
            "matched_results.json",
            "aggregate_tables.json",
            "clustered_statistics.json",
            "storage_and_overflow.json",
            "decision_gates.json",
        ],
    }
    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n=== Phase M0-D Discovery Results Summary ===")
    print(f"Mean Paired Cash Delta:  +${cash_stats['mean']:,.2f}")
    print(f"Median Paired Cash Delta:+${cash_stats['median']:,.2f}")
    print(f"95% Clustered CI:        [+${cash_stats['ci_95_lower']:,.2f}, +${cash_stats['ci_95_upper']:,.2f}]")
    print(f"H2H vs C0 (W/T/L):       {c2_wins} / {c2_ties} / {c2_losses} ({c2_wins/len(matched_pairs)*100:.1f}% win rate)")
    print(f"Total Discard C0:        {tot_c0_discard} units")
    print(f"Total Discard C2:        {tot_c2_discard} units")
    print(f"Discard Reduction:       {overall_reduction_pct:.1f}%")
    print(f"Spot Value Preserved:    +${storage_and_overflow['mean_spot_value_preserved']:,.2f} / match")
    print(f"Gate B: {'PASSED' if gate_b_passed else 'FAILED'}")
    print(f"Gate C: {'PASSED' if gate_c_passed else 'FAILED'}")
    print(f"Overall Recommendation:  {decision_gates['overall_recommendation']}")


if __name__ == "__main__":
    main()
