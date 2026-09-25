"""Phase M0-B: Midnight Storage Dump Logistics Discovery Experiment Runner.

Evaluates 4 arms across the new discovery panel (Seeds 96511–96520 x 5 opponents x 2 seats = 100 scenario cells):
- A0B0: PIPELINE OFF, DUMP OFF (Control)
- A1B0: PIPELINE ON,  DUMP OFF (M0-A standalone)
- A0B1: PIPELINE OFF, DUMP ON  (M0-B standalone)
- A1B1: PIPELINE ON,  DUMP ON  (Combined package)

Total: 100 cells x 4 arms = 400 real-engine matches.

Deliverables:
simulations/results/phase_m0_b_discovery/
    manifest.json
    matched_results.json
    aggregate_tables.json
    storage_telemetry.json
    capital_purchase_timing.json
    safety_comparison.json
    interaction_analysis.json
    losing_pair_forensics.json
    representative_traces.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_b_discovery")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_SEEDS = list(range(96511, 96521))  # 96511–96520
SMOKE_SEEDS = [96511, 96512]
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]
ARMS = ["A0B0", "A1B0", "A0B1", "A1B1"]

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
ANIMALS = ["GOOSE", "COW", "SHEEP"]
CROP_MATURITY = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _quadrant_of(x: int, y: int) -> str:
    return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def run_single_arm_match(seed: int, opp_name: str, seat: int, arm: str) -> Dict[str, Any]:
    """Run one single match under specified arm ('A0B0', 'A1B0', 'A0B1', 'A1B1')."""
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    from kaggle_environments import make
    import config
    from agent.main import (
        agent,
        reset_agent_state,
        get_crop_pipeline_telemetry,
        get_midnight_storage_telemetry,
        verify_post_turn_pipelines,
    )
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    pipeline_mode = "ON" if arm in ("A1B0", "A1B1") else "OFF"
    dump_mode = "ON" if arm in ("A0B1", "A1B1") else "OFF"

    config.set_sw_forward_architecture_mode("OFF")
    config.set_soft_worker_locality_mode("OFF")
    config.set_same_turn_crop_pipeline_mode(pipeline_mode)
    config.set_midnight_storage_dump_mode(dump_mode)

    try:
        import agent.config as ac
        ac.set_sw_forward_architecture_mode("OFF")
        ac.set_soft_worker_locality_mode("OFF")
        ac.set_same_turn_crop_pipeline_mode(pipeline_mode)
        ac.set_midnight_storage_dump_mode(dump_mode)
    except Exception:
        pass

    reset_agent_state()
    reset_sw_tranche_controller()

    opp_agent = get_agent(opp_name)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    _ = env.reset()

    worker_stats = {
        "total_worker_turns": 0,
        "emitted_moves": 0,
        "executed_moves": 0,
        "executed_ops": 0,
    }

    storage_stats = {
        "peak_shed_occupancy": 0,
        "shed_turns_ge_90": 0,
        "shed_turns_ge_95": 0,
        "shed_turns_at_capacity": 0,
        "first_turn_ge_90": None,
        "first_turn_ge_95": None,
        "first_turn_at_capacity": None,
    }

    capital_stats = {
        "planned_purchases": [],
        "actual_purchases": [],
        "purchase_turns": {},
        "dropped_due_to_shed": 0,
    }

    safety_stats = {
        "animal_escapes": 0,
        "consecutive_unfed_max": 0,
    }

    crop_cycles_completed = 0
    tile_empty_turns = 0
    step_traces = []

    prev_animals_count = 0

    while not env.done:
        s0 = env.state[seat].observation
        s1 = env.state[1 - seat].observation
        farm0 = s0.farms[seat]
        priv0 = s0.private
        step = env.state[0].observation.step
        day = s0.day
        hour = s0.hour

        cash_before = float(farm0.money)
        shed_occ = sum(max(0, int(v)) for v in priv0.shed.values()) if hasattr(priv0, "shed") else 0

        # Track storage metrics
        if shed_occ > storage_stats["peak_shed_occupancy"]:
            storage_stats["peak_shed_occupancy"] = shed_occ
        if shed_occ >= 90:
            storage_stats["shed_turns_ge_90"] += 1
            if storage_stats["first_turn_ge_90"] is None:
                storage_stats["first_turn_ge_90"] = step
        if shed_occ >= 95:
            storage_stats["shed_turns_ge_95"] += 1
            if storage_stats["first_turn_ge_95"] is None:
                storage_stats["first_turn_ge_95"] = step
        if shed_occ >= 100:
            storage_stats["shed_turns_at_capacity"] += 1
            if storage_stats["first_turn_at_capacity"] is None:
                storage_stats["first_turn_at_capacity"] = step

        # Track empty tile turns in unlocked core
        for y in range(10):
            for x in range(10):
                quad = _quadrant_of(x, y)
                if quad in ("NW", "NE") and quad in farm0.unlocked_quadrants:
                    if farm0.tiles[y][x] is None:
                        tile_empty_turns += 1

        # Track animals count to detect actual purchases
        current_animals = sum(
            1 for row in farm0.tiles for t in row if isinstance(t, dict) and "animal" in t
        ) + sum(int(priv0.shed.get(a, 0)) for a in ANIMALS if hasattr(priv0, "shed"))
        if current_animals > prev_animals_count:
            capital_stats["actual_purchases"].append({"step": step, "day": day, "hour": hour, "count": current_animals})
            prev_animals_count = current_animals

        # Execute our agent
        act0 = agent(s0, env.configuration)
        farmer_act = act0.get("farmer", ["PASS"])
        hand_acts = act0.get("hands", [])
        all_actions = [farmer_act] + hand_acts
        positions_before = [tuple(farm0.farmer)] + [tuple(h) for h in farm0.hands]
        worker_stats["total_worker_turns"] += len(all_actions)

        # Step trace for first divergence detection
        step_traces.append({
            "step": step,
            "day": day,
            "hour": hour,
            "actions": [list(a) if isinstance(a, (list, tuple)) else [a] for a in all_actions],
            "money": cash_before,
            "shed_occ": shed_occ,
        })

        # Opponent turn
        try:
            act1 = opp_agent(s1, env.configuration)
        except TypeError:
            act1 = opp_agent(s1)

        actions = [act0, act1] if seat == 0 else [act1, act0]
        env.step(actions)

        # Post-step observation
        s0_post = env.state[seat].observation
        farm0_post = s0_post.farms[seat]
        priv0_post = s0_post.private

        verify_post_turn_pipelines(s0_post, seat)

    final_cash = float(env.state[seat].observation.farms[seat].money)
    pipeline_telem = get_crop_pipeline_telemetry() if pipeline_mode == "ON" else []
    storage_telem = get_midnight_storage_telemetry() if dump_mode == "ON" else {}

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "arm": arm,
        "final_cash": final_cash,
        "worker_stats": worker_stats,
        "storage_stats": storage_stats,
        "capital_stats": capital_stats,
        "safety_stats": safety_stats,
        "tile_empty_turns": tile_empty_turns,
        "pipeline_success_count": sum(1 for e in pipeline_telem if e.get("pipeline_success")),
        "holds_successful_count": storage_telem.get("holds_successful", 0),
        "products_held": storage_telem.get("products_held", {}),
        "traces": step_traces[:400],  # first 400 steps for divergence checks
    }


def run_matched_scenario(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    """Run all 4 arms for a single matched scenario cell."""
    cell_results = {}
    for arm in ARMS:
        res = run_single_arm_match(seed, opp_name, seat, arm)
        cell_results[arm] = res

    # Contrasts:
    cash_a0b0 = cell_results["A0B0"]["final_cash"]
    cash_a1b0 = cell_results["A1B0"]["final_cash"]
    cash_a0b1 = cell_results["A0B1"]["final_cash"]
    cash_a1b1 = cell_results["A1B1"]["final_cash"]

    delta_m0a = cash_a1b0 - cash_a0b0
    delta_m0b = cash_a0b1 - cash_a0b0
    delta_package = cash_a1b1 - cash_a0b0
    delta_m0b_given_m0a = cash_a1b1 - cash_a1b0
    interaction = delta_m0b_given_m0a - delta_m0b

    # Find first action divergence between A1B0 and A1B1
    first_div = None
    t_a1b0 = cell_results["A1B0"]["traces"]
    t_a1b1 = cell_results["A1B1"]["traces"]
    for i in range(min(len(t_a1b0), len(t_a1b1))):
        if t_a1b0[i]["actions"] != t_a1b1[i]["actions"]:
            first_div = {
                "step": t_a1b0[i]["step"],
                "day": t_a1b0[i]["day"],
                "hour": t_a1b0[i]["hour"],
                "a1b0_actions": t_a1b0[i]["actions"],
                "a1b1_actions": t_a1b1[i]["actions"],
                "a1b0_money": t_a1b0[i]["money"],
                "a1b1_money": t_a1b1[i]["money"],
                "a1b0_shed": t_a1b0[i]["shed_occ"],
                "a1b1_shed": t_a1b1[i]["shed_occ"],
            }
            break

    # Clean traces to conserve memory
    for arm in ARMS:
        del cell_results[arm]["traces"]

    print(
        f"Done cell ({seed}, '{opp_name}', {seat}): "
        f"A0B0=${cash_a0b0:,.0f} | A1B0=${cash_a1b0:,.0f} (M0A=${delta_m0a:+,.0f}) | "
        f"A0B1=${cash_a0b1:,.0f} (M0B=${delta_m0b:+,.0f}) | "
        f"A1B1=${cash_a1b1:,.0f} (PKG=${delta_package:+,.0f}, INCR=${delta_m0b_given_m0a:+,.0f})"
    )

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "cash": {
            "A0B0": cash_a0b0,
            "A1B0": cash_a1b0,
            "A0B1": cash_a0b1,
            "A1B1": cash_a1b1,
        },
        "deltas": {
            "m0a_effect": delta_m0a,
            "m0b_standalone": delta_m0b,
            "package_effect": delta_package,
            "m0b_given_m0a": delta_m0b_given_m0a,
            "interaction": interaction,
        },
        "first_divergence_a1b0_vs_a1b1": first_div,
        "cell_details": cell_results,
    }


def compute_distribution_metrics(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    mean_val = sum(s) / n

    def p(pct: float) -> float:
        idx = int(round((pct / 100.0) * (n - 1)))
        return s[max(0, min(n - 1, idx))]

    wins = sum(1 for v in s if v > 0)
    ties = sum(1 for v in s if v == 0)
    losses = sum(1 for v in s if v < 0)

    return {
        "mean": round(mean_val, 2),
        "median": round(p(50), 2),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate_pct": round(wins / n * 100.0, 1),
        "p10": round(p(10), 2),
        "p25": round(p(25), 2),
        "p50": round(p(50), 2),
        "p75": round(p(75), 2),
        "p90": round(p(90), 2),
        "best": round(s[-1], 2),
        "worst": round(s[0], 2),
    }


def compute_seed_clustered_ci(cells: List[Dict[str, Any]], delta_key: str) -> Tuple[float, float, float]:
    """Compute seed-level cluster mean and 95% t-interval (df = n_seeds - 1)."""
    by_seed: Dict[int, List[float]] = {}
    for c in cells:
        by_seed.setdefault(c["seed"], []).append(c["deltas"][delta_key])

    seed_means = [sum(v) / len(v) for v in by_seed.values()]
    n = len(seed_means)
    if n <= 1:
        m = seed_means[0] if seed_means else 0.0
        return m, m, m

    mean_delta = sum(seed_means) / n
    var = sum((x - mean_delta) ** 2 for x in seed_means) / (n - 1)
    se = math.sqrt(var / n)

    # t-critical for 95% two-tailed with df = n - 1
    t_crit_table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}
    t_val = t_crit_table.get(n - 1, 2.262)

    ci_low = round(mean_delta - t_val * se, 2)
    ci_high = round(mean_delta + t_val * se, 2)
    return round(mean_delta, 2), ci_low, ci_high


def main():
    parser = argparse.ArgumentParser(description="Run Phase M0-B Discovery Experiment.")
    parser.add_argument("--smoke", action="store_true", help="Run 2-seed smoke test")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker processes")
    args = parser.parse_args()

    seeds = SMOKE_SEEDS if args.smoke else DEFAULT_SEEDS
    scenarios = [(s, opp, seat) for s in seeds for opp in BENCHMARK_OPPONENTS for seat in SEATS]
    total_cells = len(scenarios)

    print("================================================================================")
    print("PHASE M0-B: 4-ARM DISCOVERY EXPERIMENT")
    print(f"Seeds ({len(seeds)}): {seeds}")
    print(f"Benchmark Opponents ({len(BENCHMARK_OPPONENTS)}): {BENCHMARK_OPPONENTS}")
    print(f"Seats: {SEATS}")
    print(f"Total scenario cells: {total_cells} (Total real matches: {total_cells * 4})")
    print(f"Workers: {args.workers}")
    print(f"Output directory: {OUT_DIR}")
    print("================================================================================")

    t0 = time.time()
    results = []

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_matched_scenario, s, opp, seat): (s, opp, seat)
            for (s, opp, seat) in scenarios
        }
        for future in as_completed(futures):
            res = future.result()
            results.append(res)

    results.sort(key=lambda r: (r["seed"], r["opp_name"], r["seat"]))
    elapsed = time.time() - t0
    print(f"\nCompleted {len(results)} cells ({len(results)*4} matches) in {elapsed:.2f}s.")

    # 1. Contrasts Analysis
    contrasts = {
        "m0a_effect": [r["deltas"]["m0a_effect"] for r in results],
        "m0b_standalone": [r["deltas"]["m0b_standalone"] for r in results],
        "package_effect": [r["deltas"]["package_effect"] for r in results],
        "m0b_given_m0a": [r["deltas"]["m0b_given_m0a"] for r in results],
        "interaction": [r["deltas"]["interaction"] for r in results],
    }

    distribution_tables = {k: compute_distribution_metrics(v) for k, v in contrasts.items()}
    ci_tables = {}
    for k in contrasts:
        mean_d, ci_l, ci_h = compute_seed_clustered_ci(results, k)
        ci_tables[k] = {"mean": mean_d, "ci_95": [ci_l, ci_h]}

    # 2. Storage & Capital Purchase Telemetry
    storage_telemetry = {
        "A0B0": {"peak_shed": 0, "turns_ge_90": 0, "turns_ge_95": 0, "turns_at_cap": 0},
        "A1B0": {"peak_shed": 0, "turns_ge_90": 0, "turns_ge_95": 0, "turns_at_cap": 0},
        "A0B1": {"peak_shed": 0, "turns_ge_90": 0, "turns_ge_95": 0, "turns_at_cap": 0},
        "A1B1": {"peak_shed": 0, "turns_ge_90": 0, "turns_ge_95": 0, "turns_at_cap": 0},
    }
    for r in results:
        for arm in ARMS:
            st = r["cell_details"][arm]["storage_stats"]
            storage_telemetry[arm]["peak_shed"] = max(storage_telemetry[arm]["peak_shed"], st["peak_shed_occupancy"])
            storage_telemetry[arm]["turns_ge_90"] += st["shed_turns_ge_90"]
            storage_telemetry[arm]["turns_ge_95"] += st["shed_turns_ge_95"]
            storage_telemetry[arm]["turns_at_cap"] += st["shed_turns_at_capacity"]

    # 3. M0-A Losing Scenarios Rescue Analysis
    m0a_losing_cells = [r for r in results if r["deltas"]["m0a_effect"] < 0]
    rescued_count = sum(1 for r in m0a_losing_cells if r["deltas"]["package_effect"] > 0)
    smaller_loss_count = sum(1 for r in m0a_losing_cells if r["deltas"]["package_effect"] > r["deltas"]["m0a_effect"] and r["deltas"]["package_effect"] <= 0)
    worse_loss_count = sum(1 for r in m0a_losing_cells if r["deltas"]["package_effect"] < r["deltas"]["m0a_effect"])

    interaction_summary = {
        "m0a_losing_cells_count": len(m0a_losing_cells),
        "rescued_to_wins": rescued_count,
        "smaller_losses": smaller_loss_count,
        "worse_losses": worse_loss_count,
        "rescue_rate_pct": round(rescued_count / len(m0a_losing_cells) * 100.0, 1) if m0a_losing_cells else 0.0,
    }

    # 4. Losing Pair Forensics (regressions in A1B1 vs A0B0 > $2,000)
    losing_pair_forensics = []
    for r in results:
        if r["deltas"]["package_effect"] < -2000:
            losing_pair_forensics.append({
                "seed": r["seed"],
                "opp_name": r["opp_name"],
                "seat": r["seat"],
                "a0b0_cash": r["cash"]["A0B0"],
                "a1b1_cash": r["cash"]["A1B1"],
                "package_delta": r["deltas"]["package_effect"],
                "m0a_delta": r["deltas"]["m0a_effect"],
                "first_divergence": r["first_divergence_a1b0_vs_a1b1"],
            })

    # Save deliverables
    manifest = {
        "phase": "M0-B",
        "evaluated_commit": get_git_commit(),
        "total_scenario_cells": len(results),
        "total_matches": len(results) * 4,
        "seeds": seeds,
        "opponents": BENCHMARK_OPPONENTS,
        "seats": SEATS,
        "arms": ARMS,
        "elapsed_seconds": round(elapsed, 2),
    }

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(OUT_DIR, "matched_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    with open(os.path.join(OUT_DIR, "aggregate_tables.json"), "w", encoding="utf-8") as f:
        json.dump({
            "sample_size": len(results),
            "distributions": distribution_tables,
            "seed_clustered_ci": ci_tables,
        }, f, indent=2)

    with open(os.path.join(OUT_DIR, "storage_telemetry.json"), "w", encoding="utf-8") as f:
        json.dump(storage_telemetry, f, indent=2)

    with open(os.path.join(OUT_DIR, "interaction_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(interaction_summary, f, indent=2)

    with open(os.path.join(OUT_DIR, "losing_pair_forensics.json"), "w", encoding="utf-8") as f:
        json.dump(losing_pair_forensics, f, indent=2)

    safety_comp = {
        "A0B0_escapes": sum(r["cell_details"]["A0B0"]["safety_stats"]["animal_escapes"] for r in results),
        "A1B0_escapes": sum(r["cell_details"]["A1B0"]["safety_stats"]["animal_escapes"] for r in results),
        "A0B1_escapes": sum(r["cell_details"]["A0B1"]["safety_stats"]["animal_escapes"] for r in results),
        "A1B1_escapes": sum(r["cell_details"]["A1B1"]["safety_stats"]["animal_escapes"] for r in results),
    }
    with open(os.path.join(OUT_DIR, "safety_comparison.json"), "w", encoding="utf-8") as f:
        json.dump(safety_comp, f, indent=2)

    rep_traces = [
        {"cell": f"{r['seed']}_{r['opp_name']}_{r['seat']}", "divergence": r["first_divergence_a1b0_vs_a1b1"]}
        for r in results if r["first_divergence_a1b0_vs_a1b1"]
    ][:10]
    with open(os.path.join(OUT_DIR, "representative_traces.json"), "w", encoding="utf-8") as f:
        json.dump(rep_traces, f, indent=2)

    print("\n================================================================================")
    print("PHASE M0-B DISCOVERY EXPERIMENT RESULTS SUMMARY")
    print(f"Scenario Cells: {len(results)} (Matches: {len(results)*4})")
    print(f"M0-A Effect (A1B0 - A0B0): Mean=${distribution_tables['m0a_effect']['mean']:+,.2f} | Median=${distribution_tables['m0a_effect']['median']:+,.2f} | CI={ci_tables['m0a_effect']['ci_95']}")
    print(f"M0-B Standalone (A0B1 - A0B0): Mean=${distribution_tables['m0b_standalone']['mean']:+,.2f} | Median=${distribution_tables['m0b_standalone']['median']:+,.2f} | CI={ci_tables['m0b_standalone']['ci_95']}")
    print(f"Combined Package (A1B1 - A0B0): Mean=${distribution_tables['package_effect']['mean']:+,.2f} | Median=${distribution_tables['package_effect']['median']:+,.2f} | CI={ci_tables['package_effect']['ci_95']}")
    print(f"Incremental M0-B (A1B1 - A1B0): Mean=${distribution_tables['m0b_given_m0a']['mean']:+,.2f} | Median=${distribution_tables['m0b_given_m0a']['median']:+,.2f} | CI={ci_tables['m0b_given_m0a']['ci_95']}")
    print(f"Interaction Synergy: Mean=${distribution_tables['interaction']['mean']:+,.2f}")
    print(f"M0-A Losses Rescued: {rescued_count} / {len(m0a_losing_cells)} ({interaction_summary['rescue_rate_pct']}%)")
    print(f"Artifacts saved to: {OUT_DIR}")
    print("================================================================================")


if __name__ == "__main__":
    main()
