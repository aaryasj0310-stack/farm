#!/usr/bin/env python3
"""
Controlled Paired A/B Benchmark Harness for Kaggriculture Central Planner.

Compares:
  Mode A: 'legacy'  (MarketBrain.compose)
  Mode B: 'central' (Phase 3 CentralPlanner)

Across identical seeds, identical opponents, and identical environment configurations.
Ensures total process isolation across runs, captures fine-grained system and economic metrics,
evaluates land/feed/shed/endgame attribution chains, and emits machine-readable CSV/JSON.
"""

import argparse
import copy
import csv
import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# Ensure repo root and agent are in sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIR = os.path.join(REPO_ROOT, "agent")
for p in (REPO_ROOT, AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _worker_run_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Worker entry point executed in an isolated spawned process."""
    seed = payload["seed"]
    opponent_name = payload["opponent"]
    mode = payload["mode"]
    episode_steps = payload.get("episode_steps", 720)
    agent_dir = payload["agent_dir"]
    repo_root = payload["repo_root"]

    # Inject paths into isolated worker sys.path
    for p in (repo_root, agent_dir):
        if p not in sys.path:
            sys.path.insert(0, p)
    for sub in ("state", "strategy", "execution", "market"):
        sub_p = os.path.join(agent_dir, sub)
        if sub_p not in sys.path:
            sys.path.insert(0, sub_p)

    from kaggle_environments import make
    import main as agent_module

    # Reset any module state and set arbitration mode
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode(mode)

    # Telemetry accumulator
    turn_telemetry_records: List[Dict[str, Any]] = []

    def wrapped_agent(obs, config=None):
        act = agent_module.agent(obs, config)
        tel = agent_module.get_last_turn_telemetry()
        if tel is not None:
            turn_telemetry_records.append(tel)
        return act

    # Resolve opponent
    if opponent_name in ("random", "pass", "starter"):
        opp = opponent_name
    else:
        try:
            from simulations.experiments.agent_zoo import get_agent
            opp = get_agent(opponent_name)
        except Exception:
            opp = "random"

    # Initialize environment
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
    shed0 = private0.get("shed", {})

    final_money = float(farm0.get("money", 0.0))
    opp_final_money = float(farm1.get("money", 0.0))
    margin = final_money - opp_final_money
    win = 1 if final_money > opp_final_money else (0.5 if final_money == opp_final_money else 0)

    # Step-by-step state tracking
    unlocked_quadrants_over_time = []
    ne_unlock_day = None
    sw_unlock_day = None
    feed_failures = 0
    shed_overflow_events = 0
    total_market_orders_executed = 0

    for step_idx, step_state in enumerate(env.steps):
        s_obs0 = step_state[0].observation
        if not isinstance(s_obs0, dict):
            continue
        s_farms = s_obs0.get("farms", [])
        if not s_farms:
            continue
        s_farm0 = s_farms[0]
        unlocked = set(s_farm0.get("unlocked_quadrants", ["NW"]))
        unlocked_quadrants_over_time.append(unlocked)
        day = s_obs0.get("day", 0)

        if "NE" in unlocked and ne_unlock_day is None:
            ne_unlock_day = day
        if "SW" in unlocked and sw_unlock_day is None:
            sw_unlock_day = day

        # Feed failure detection: animal present but health degraded or starving
        tiles = s_farm0.get("tiles", [])
        for row in tiles:
            if not isinstance(row, list):
                continue
            for t in row:
                if isinstance(t, dict) and t.get("kind") == "ANIMAL":
                    # If animal not fed today and days_unfed > 0
                    if t.get("days_unfed", 0) > 0 or t.get("is_starving", False):
                        feed_failures += 1

        # Shed overflow detection: shed total at or exceeding 100 capacity
        s_private = s_obs0.get("private", {})
        s_shed = s_private.get("shed", {})
        if sum(s_shed.values()) >= 100:
            shed_overflow_events += 1

        s_act = step_state[0].action
        if isinstance(s_act, dict):
            total_market_orders_executed += len(s_act.get("market", []))

    # Land utilization at end of game
    final_tiles = farm0.get("tiles", [])
    total_unlocked_tiles = len(farm0.get("unlocked_quadrants", ["NW"])) * 25
    utilized_tiles = 0
    animal_count = 0
    crop_counts: Dict[str, int] = {}
    for row in final_tiles:
        if not isinstance(row, list):
            continue
        for t in row:
            if isinstance(t, dict):
                k = t.get("kind")
                if k == "ANIMAL":
                    utilized_tiles += 1
                    animal_count += 1
                elif k == "PLANT":
                    utilized_tiles += 1
                    crop = t.get("crop", "UNKNOWN")
                    crop_counts[crop] = crop_counts.get(crop, 0) + 1
                elif k == "STRUCTURE":
                    utilized_tiles += 1

    quadrant_utilization = utilized_tiles / max(1, total_unlocked_tiles)

    # Endgame unsold inventory (sellable items in shed at step 720)
    sellables = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL"]
    endgame_unsold_inventory = sum(shed0.get(p, 0) for p in sellables)

    # Telemetry aggregations
    turns_total = len(turn_telemetry_records)
    turns_with_candidates = 0
    turns_with_slot_pressure = 0
    turns_changed_from_legacy = 0
    changed_selection_turns = 0
    execution_reorder_only_turns = 0
    slot_pressure_changed_selection_turns = 0

    purchase_candidates_total = 0
    sell_candidates_total = 0
    orders_selected_total = 0

    rejections_by_reason: Dict[str, int] = Counter()
    accepted_by_priority: Dict[str, int] = Counter()
    rejected_by_priority: Dict[str, int] = Counter()

    p0_priority_inversion_count = 0
    p0_priority_inversions = []

    land_proposed_count = 0
    land_selected_count = 0
    critical_wheat_proposed_count = 0
    critical_wheat_selected_count = 0

    divergence_turns = []

    for t in turn_telemetry_records:
        n_buys = len(t["purchase_orders"])
        n_sells = len(t["sell_orders"])
        cand_count = n_buys + n_sells
        if cand_count > 0:
            turns_with_candidates += 1
        if cand_count > 10:
            turns_with_slot_pressure += 1

        purchase_candidates_total += n_buys
        sell_candidates_total += n_sells
        orders_selected_total += len(t["market"])

        if t.get("land_proposed"):
            land_proposed_count += 1
        if t.get("land_selected"):
            land_selected_count += 1
        if t.get("critical_wheat_proposed"):
            critical_wheat_proposed_count += 1
        if t.get("critical_wheat_selected"):
            critical_wheat_selected_count += 1

        diag = t.get("central_planner_diagnostic")
        if diag:
            p0_inv = diag.get("p0_priority_inversions", [])
            if p0_inv:
                p0_priority_inversion_count += len(p0_inv)
                p0_priority_inversions.extend(p0_inv)

            if diag.get("changed_from_legacy"):
                turns_changed_from_legacy += 1
                if diag.get("changed_selection"):
                    changed_selection_turns += 1
                    if cand_count > 10:
                        slot_pressure_changed_selection_turns += 1
                elif diag.get("execution_reorder_only"):
                    execution_reorder_only_turns += 1

                # Record divergence summary
                divergence_turns.append({
                    "step": t["step"],
                    "day": t["day"],
                    "hour": t["hour"],
                    "money_before": t["money_before"],
                    "shed_before": t["shed_before"],
                    "purchase_candidates": t["purchase_orders"],
                    "sell_candidates": t["sell_orders"],
                    "central_orders": t["market"],
                    "legacy_orders": diag.get("legacy_orders", []),
                    "changed_selection": diag.get("changed_selection", False),
                    "execution_reorder_only": diag.get("execution_reorder_only", False),
                    "change_reasons": diag.get("change_reasons", []),
                })

            for r, count in diag.get("rejection_reasons", {}).items():
                rejections_by_reason[r] += count
            for p, count in diag.get("accepted_by_priority", {}).items():
                accepted_by_priority[p] += count
            for p, count in diag.get("rejected_by_priority", {}).items():
                rejected_by_priority[p] += count

    slot_pressure_changed_selection_rate = (
        slot_pressure_changed_selection_turns / max(1, turns_with_slot_pressure)
    )

    return {
        "seed": seed,
        "opponent": opponent_name,
        "mode": mode,
        "final_money": final_money,
        "opponent_final_money": opp_final_money,
        "margin": margin,
        "win": win,
        "ne_unlock_day": ne_unlock_day,
        "sw_unlock_day": sw_unlock_day,
        "quadrant_utilization": round(quadrant_utilization, 4),
        "animal_count": animal_count,
        "crop_counts": crop_counts,
        "feed_failures": feed_failures,
        "shed_overflow_events": shed_overflow_events,
        "endgame_unsold_inventory": endgame_unsold_inventory,
        "total_market_orders_executed": total_market_orders_executed,
        "turns_total": turns_total,
        "turns_with_candidates": turns_with_candidates,
        "turns_with_slot_pressure": turns_with_slot_pressure,
        "turns_changed_from_legacy": turns_changed_from_legacy,
        "changed_selection_turns": changed_selection_turns,
        "execution_reorder_only_turns": execution_reorder_only_turns,
        "slot_pressure_changed_selection_turns": slot_pressure_changed_selection_turns,
        "slot_pressure_changed_selection_rate": round(slot_pressure_changed_selection_rate, 4),
        "purchase_candidates_total": purchase_candidates_total,
        "sell_candidates_total": sell_candidates_total,
        "orders_selected_total": orders_selected_total,
        "rejections_by_reason": dict(rejections_by_reason),
        "accepted_by_priority": dict(accepted_by_priority),
        "rejected_by_priority": dict(rejected_by_priority),
        "p0_priority_inversion_count": p0_priority_inversion_count,
        "p0_priority_inversions": p0_priority_inversions,
        "land_proposed_count": land_proposed_count,
        "land_selected_count": land_selected_count,
        "critical_wheat_proposed_count": critical_wheat_proposed_count,
        "critical_wheat_selected_count": critical_wheat_selected_count,
        "divergence_turns": divergence_turns,
    }


class CentralPlannerBenchmark:
    def __init__(self, seeds: List[int], opponents: List[str], baseline_mode: str = "legacy", max_workers: int = 4):
        self.seeds = seeds
        self.opponents = opponents
        self.baseline_mode = baseline_mode
        self.max_workers = max_workers

    def run(self) -> Dict[str, Any]:
        tasks = []
        for opp in self.opponents:
            for s in self.seeds:
                # Pair: Run A (baseline) and Run B (central)
                tasks.append({
                    "seed": s, "opponent": opp, "mode": self.baseline_mode,
                    "agent_dir": AGENT_DIR, "repo_root": REPO_ROOT
                })
                tasks.append({
                    "seed": s, "opponent": opp, "mode": "central",
                    "agent_dir": AGENT_DIR, "repo_root": REPO_ROOT
                })

        print(f"Starting Paired A/B Benchmark [{self.baseline_mode} vs central]: {len(self.seeds)} seeds x {len(self.opponents)} opponents = {len(tasks)} runs...")
        start_time = time.time()

        raw_results = {}
        with ProcessPoolExecutor(max_workers=self.max_workers, mp_context=mp.get_context("spawn")) as executor:
            future_to_payload = {executor.submit(_worker_run_match, p): p for p in tasks}
            completed = 0
            for future in as_completed(future_to_payload):
                completed += 1
                res = future.result()
                key = (res["seed"], res["opponent"], res["mode"])
                raw_results[key] = res
                print(f"[{completed:02d}/{len(tasks):02d}] Seed {res['seed']:02d} | {res['opponent']} | {res['mode']:<16} => ${res['final_money']:,.2f}")

        elapsed = time.time() - start_time
        print(f"Benchmark finished in {elapsed:.1f}s.")

        # Pair analysis
        pairs = []
        for opp in self.opponents:
            for s in self.seeds:
                leg = raw_results.get((s, opp, self.baseline_mode))
                cen = raw_results.get((s, opp, "central"))
                if leg and cen:
                    delta = cen["final_money"] - leg["final_money"]
                    pairs.append({
                        "seed": s,
                        "opponent": opp,
                        "legacy_final_money": leg["final_money"],
                        "central_final_money": cen["final_money"],
                        "delta": delta,
                        "legacy_margin": leg["margin"],
                        "central_margin": cen["margin"],
                        "legacy_sw_day": leg["sw_unlock_day"],
                        "central_sw_day": cen["sw_unlock_day"],
                        "legacy_feed_failures": leg["feed_failures"],
                        "central_feed_failures": cen["feed_failures"],
                        "legacy_unsold_endgame": leg["endgame_unsold_inventory"],
                        "central_unsold_endgame": cen["endgame_unsold_inventory"],
                        "central_changed_turns": cen["turns_changed_from_legacy"],
                        "central_changed_selection_turns": cen["changed_selection_turns"],
                        "central_reorder_only_turns": cen["execution_reorder_only_turns"],
                        "central_slot_pressure_turns": cen["turns_with_slot_pressure"],
                        "central_slot_pressure_selection_rate": cen["slot_pressure_changed_selection_rate"],
                        "central_p0_inversion_count": cen["p0_priority_inversion_count"],
                        "legacy_run": leg,
                        "central_run": cen,
                    })

        return {
            "elapsed_seconds": round(elapsed, 2),
            "seed_count": len(self.seeds),
            "opponents": self.opponents,
            "pairs": pairs,
        }


def save_benchmark_artifacts(data: Dict[str, Any], csv_path: str, json_path: str):
    """Save machine-readable CSV and JSON summaries."""
    pairs = data["pairs"]
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    # 1. Write CSV
    headers = [
        "seed", "opponent",
        "legacy_final_money", "central_final_money", "delta",
        "legacy_sw_day", "central_sw_day",
        "legacy_feed_failures", "central_feed_failures",
        "legacy_unsold_endgame", "central_unsold_endgame",
        "central_changed_turns", "central_changed_selection_turns",
        "central_reorder_only_turns", "central_slot_pressure_turns",
        "central_slot_pressure_selection_rate", "central_p0_inversion_count",
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for p in pairs:
            writer.writerow(p)

    # 2. Write JSON
    # Strip non-serializable details for compact JSON
    json_summary = {
        "elapsed_seconds": data["elapsed_seconds"],
        "seed_count": data["seed_count"],
        "opponents": data["opponents"],
        "pairs": [
            {k: v for k, v in p.items() if k not in ("legacy_run", "central_run")}
            for p in pairs
        ],
        "detailed_runs": {
            f"{p['seed']}_{p['opponent']}": {
                "legacy": p["legacy_run"],
                "central": p["central_run"],
            }
            for p in pairs
        }
    }
    with open(json_path, "w") as f:
        json.dump(json_summary, f, indent=2)

    print(f"Artifacts saved:\n  CSV:  {csv_path}\n  JSON: {json_path}")


def compute_statistics(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute comprehensive paired statistical summary."""
    import numpy as np

    if not pairs:
        return {}

    deltas = np.array([p["delta"] for p in pairs])
    leg_money = np.array([p["legacy_final_money"] for p in pairs])
    cen_money = np.array([p["central_final_money"] for p in pairs])

    central_wins = int(np.sum(deltas > 0))
    legacy_wins = int(np.sum(deltas < 0))
    ties = int(np.sum(deltas == 0))

    sorted_deltas = np.sort(deltas)
    p10 = float(np.percentile(deltas, 10))
    p25 = float(np.percentile(deltas, 25))
    p50 = float(np.percentile(deltas, 50))
    p75 = float(np.percentile(deltas, 75))
    p90 = float(np.percentile(deltas, 90))

    bottom_10_pct_count = max(1, int(len(deltas) * 0.10))
    bottom_10_mean = float(np.mean(sorted_deltas[:bottom_10_pct_count]))

    # Worst 5 seeds
    pairs_by_delta = sorted(pairs, key=lambda p: p["delta"])
    worst_5 = [
        {"seed": p["seed"], "opponent": p["opponent"], "delta": p["delta"],
         "legacy": p["legacy_final_money"], "central": p["central_final_money"]}
        for p in pairs_by_delta[:5]
    ]

    # Best 5 seeds
    best_5 = [
        {"seed": p["seed"], "opponent": p["opponent"], "delta": p["delta"],
         "legacy": p["legacy_final_money"], "central": p["central_final_money"]}
        for p in pairs_by_delta[-5:][::-1]
    ]

    # Aggregates across central runs
    total_turns = sum(p["central_run"]["turns_total"] for p in pairs)
    total_slot_pressure_turns = sum(p["central_run"]["turns_with_slot_pressure"] for p in pairs)
    total_changed_turns = sum(p["central_run"]["turns_changed_from_legacy"] for p in pairs)
    total_changed_selection = sum(p["central_run"]["changed_selection_turns"] for p in pairs)
    total_reorder_only = sum(p["central_run"]["execution_reorder_only_turns"] for p in pairs)
    total_p0_inversions = sum(p["central_run"]["p0_priority_inversion_count"] for p in pairs)

    # Land & feed aggregates
    legacy_feed_total = sum(p["legacy_feed_failures"] for p in pairs)
    central_feed_total = sum(p["central_feed_failures"] for p in pairs)

    legacy_unsold_total = sum(p["legacy_unsold_endgame"] for p in pairs)
    central_unsold_total = sum(p["central_unsold_endgame"] for p in pairs)

    return {
        "n_pairs": len(pairs),
        "mean_legacy": round(float(np.mean(leg_money)), 2),
        "median_legacy": round(float(np.median(leg_money)), 2),
        "std_legacy": round(float(np.std(leg_money)), 2),
        "min_legacy": round(float(np.min(leg_money)), 2),
        "max_legacy": round(float(np.max(leg_money)), 2),
        "mean_central": round(float(np.mean(cen_money)), 2),
        "median_central": round(float(np.median(cen_money)), 2),
        "std_central": round(float(np.std(cen_money)), 2),
        "min_central": round(float(np.min(cen_money)), 2),
        "max_central": round(float(np.max(cen_money)), 2),
        "mean_delta": round(float(np.mean(deltas)), 2),
        "median_delta": round(p50, 2),
        "std_delta": round(float(np.std(deltas)), 2),
        "p10_delta": round(p10, 2),
        "p25_delta": round(p25, 2),
        "p75_delta": round(p75, 2),
        "p90_delta": round(p90, 2),
        "bottom_10_mean_delta": round(bottom_10_mean, 2),
        "central_wins": central_wins,
        "legacy_wins": legacy_wins,
        "ties": ties,
        "worst_5": worst_5,
        "best_5": best_5,
        "total_turns": total_turns,
        "slot_pressure_turns": total_slot_pressure_turns,
        "slot_pressure_rate": round(total_slot_pressure_turns / max(1, total_turns), 4),
        "changed_turns": total_changed_turns,
        "changed_turns_rate": round(total_changed_turns / max(1, total_turns), 4),
        "changed_selection_turns": total_changed_selection,
        "execution_reorder_only_turns": total_reorder_only,
        "slot_pressure_changed_selection_rate": round(
            sum(p["central_run"]["slot_pressure_changed_selection_turns"] for p in pairs)
            / max(1, total_slot_pressure_turns),
            4,
        ),
        "total_p0_inversions": total_p0_inversions,
        "legacy_feed_failures": legacy_feed_total,
        "central_feed_failures": central_feed_total,
        "legacy_unsold_inventory": legacy_unsold_total,
        "central_unsold_inventory": central_unsold_total,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kaggriculture Central Planner A/B Benchmark")
    parser.add_argument("--benchmark", type=str, choices=["arbitration_only", "full_stack"], default="arbitration_only",
                        help="Benchmark type: 'arbitration_only' (legacy compose vs central) or 'full_stack' (historical limits+legacy vs central)")
    parser.add_argument("--seeds", type=int, default=25, help="Number of seeds to evaluate (default 25)")
    parser.add_argument("--start-seed", type=int, default=101, help="Starting seed number (default 101)")
    parser.add_argument("--opponents", nargs="+", default=["random", "starter"], help="Opponent policies to test")
    parser.add_argument("--workers", type=int, default=min(4, max(1, mp.cpu_count() - 1)), help="Number of parallel workers")
    parser.add_argument("--csv", type=str, default=None, help="Output CSV path")
    parser.add_argument("--json", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()

    baseline_mode = "legacy" if args.benchmark == "arbitration_only" else "historical_stack"
    default_csv_name = "central_planner_ab.csv" if args.benchmark == "arbitration_only" else "central_planner_full_stack_ab.csv"
    default_json_name = "central_planner_ab.json" if args.benchmark == "arbitration_only" else "central_planner_full_stack_ab.json"
    csv_path = args.csv or os.path.join(REPO_ROOT, "artifacts", default_csv_name)
    json_path = args.json or os.path.join(REPO_ROOT, "artifacts", default_json_name)

    seed_list = list(range(args.start_seed, args.start_seed + args.seeds))
    benchmark = CentralPlannerBenchmark(
        seeds=seed_list,
        opponents=args.opponents,
        baseline_mode=baseline_mode,
        max_workers=args.workers,
    )
    results = benchmark.run()
    save_benchmark_artifacts(results, csv_path, json_path)

    stats = compute_statistics(results["pairs"])
    print("\n======================================================================")
    print("                      A/B BENCHMARK SUMMARY                           ")
    print("======================================================================")
    print(f"Paired Matches Evaluated: {stats['n_pairs']} ({len(seed_list)} seeds x {len(args.opponents)} opponents)")
    print(f"Central Better: {stats['central_wins']} | Legacy Better: {stats['legacy_wins']} | Ties: {stats['ties']}")
    print(f"Mean Legacy Money:   ${stats['mean_legacy']:,.2f} (Median: ${stats['median_legacy']:,.2f})")
    print(f"Mean Central Money:  ${stats['mean_central']:,.2f} (Median: ${stats['median_central']:,.2f})")
    print(f"Mean Paired Delta:   ${stats['mean_delta']:+,.2f} (Median: ${stats['median_delta']:+,.2f})")
    print(f"Delta Percentiles:   P10: ${stats['p10_delta']:+,.2f} | P25: ${stats['p25_delta']:+,.2f} | P75: ${stats['p75_delta']:+,.2f} | P90: ${stats['p90_delta']:+,.2f}")
    print(f"Bottom 10% Mean:     ${stats['bottom_10_mean_delta']:+,.2f}")
    print(f"Slot Pressure Turns: {stats['slot_pressure_turns']} / {stats['total_turns']} ({stats['slot_pressure_rate']*100:.1f}%)")
    print(f"Diverged Turns:      {stats['changed_turns']} (Selection: {stats['changed_selection_turns']}, Reorder: {stats['execution_reorder_only_turns']})")
    print(f"Slot Pressure Change Rate: {stats['slot_pressure_changed_selection_rate']*100:.1f}%")
    print(f"P0 Inversions:       {stats['total_p0_inversions']}")
    print(f"Feed Failures:       Legacy {stats['legacy_feed_failures']} vs Central {stats['central_feed_failures']}")
    print(f"Unsold Endgame Inv:  Legacy {stats['legacy_unsold_inventory']} vs Central {stats['central_unsold_inventory']}")
    print("======================================================================\n")
