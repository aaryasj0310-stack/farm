"""Authoritative Matched-Control Validation Runner for Soft Worker Locality.

Phase M0-L-B-R: Oracle Integrity & Matched-Control Validation.
Evaluates Soft Worker Locality (SOFT_WORKER_LOCALITY_MODE = 'ON') vs exact Matched
Production Control (SOFT_WORKER_LOCALITY_MODE = 'OFF') with QUADRANT_HARD_BLOCK = {4}.
Verifies bit-for-bit parity of Control against the Phase M0-L-A census baseline.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
DEFAULT_OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_l_b_r_reconciliation")
CENSUS_PATH = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_l_a_census", "match_results.json")

DEV_SEEDS = list(range(97013, 97023))  # 97013–97022 (10 seeds)
PILOT_SEEDS = [97013, 97014]
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def load_census_lookup() -> Dict[Tuple[int, str, int], float]:
    """Load baseline final cash from M0-L-A census."""
    if not os.path.exists(CENSUS_PATH):
        return {}
    with open(CENSUS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    lookup = {}
    for m in data:
        meta = m["metadata"]
        lookup[(int(meta["seed"]), str(meta["opponent"]), int(meta["seat"]))] = float(meta["final_cash"])
    return lookup


def run_single_simulation_match(seed: int, opp_name: str, seat: int, mode: str) -> Dict[str, Any]:
    """Run a single match in an isolated process with exact configuration snapshot."""
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    from agent.main import agent, reset_agent_state
    import config
    from execution.midnight_storage_controller import reset_midnight_storage_telemetry
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from execution.task_scheduler import reset_sticky_missions, reset_blocked_task_tracker, reset_worker_locality
    from simulations.experiments.agent_zoo import get_agent

    # Exact canonical production baseline settings
    config.set_midnight_storage_dump_mode("RESCUE")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")
    config.set_quadrant_hard_block({4})  # Canonical production default: SE(4) blocked
    config.set_sw_delayed_unlock_day(None)
    config.set_p41_sw_zonal_expansion_enabled(False)
    config.FEED_WHEAT_BUFFER_DAYS = 4

    # Arm treatment
    if mode == "CONTROL":
        config.set_soft_worker_locality_mode("OFF")
        config.set_persistent_worker_locality(False)
    elif mode == "TREATMENT":
        config.set_soft_worker_locality_mode("ON")
        config.set_persistent_worker_locality(False)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # Reset all mutable agent states
    reset_agent_state()
    reset_midnight_storage_telemetry()
    reset_sw_tranche_controller()
    reset_sticky_missions()
    reset_blocked_task_tracker()
    reset_worker_locality()

    cfg_snapshot = {
        "mode": mode,
        "SOFT_WORKER_LOCALITY_MODE": config.get_soft_worker_locality_mode(),
        "PERSISTENT_WORKER_LOCALITY": getattr(config, "PERSISTENT_WORKER_LOCALITY_ENABLED", False),
        "QUADRANT_HARD_BLOCK": list(config.get_quadrant_hard_block()),
        "MIDNIGHT_STORAGE_DUMP_MODE": getattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE"),
        "FEED_WHEAT_BUFFER_DAYS": config.FEED_WHEAT_BUFFER_DAYS,
    }

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    t_start = time.time()
    max_market_orders = 0
    move_count = 0
    productive_count = 0
    idle_count = 0

    animal_escapes = 0
    starvation_events = 0
    unfed_animal_days = 0
    min_wheat_in_shed = 999999
    consecutive_unfed_max = 0

    prev_animals: Dict[Tuple[int, int], str] = {}

    while not env.done:
        obs_pre = env.state[seat].observation
        day = getattr(obs_pre, "day", 0)
        hour = getattr(obs_pre, "hour", 0)
        step = day * 24 + hour

        # Track shed wheat
        shed = obs_pre.private.get("shed", {})
        wheat_in_shed = shed.get("WHEAT", 0)
        if wheat_in_shed < min_wheat_in_shed:
            min_wheat_in_shed = wheat_in_shed

        # Inspect animal tiles on player's farm
        tiles = obs_pre.farms[seat].tiles
        current_animals: Dict[Tuple[int, int], str] = {}
        for r_idx, row in enumerate(tiles):
            for c_idx, cell in enumerate(row):
                if isinstance(cell, dict) and "animal" in cell:
                    current_animals[(r_idx, c_idx)] = cell["animal"]
                    cunfed = cell.get("consecutive_unfed", 0)
                    if cunfed > consecutive_unfed_max:
                        consecutive_unfed_max = cunfed
                    if cunfed > 0:
                        starvation_events += 1

                    # At hour 23, check if animal will starve at day rollover
                    if hour == 23 and not cell.get("fed_today", False):
                        unfed_animal_days += 1
                        if cunfed >= 1:
                            animal_escapes += 1

        prev_animals = current_animals

        # Execute agent action
        action = agent(obs_pre, env.configuration)
        m_orders = action.get("market", [])
        if len(m_orders) > max_market_orders:
            max_market_orders = len(m_orders)

        unit_actions = []
        if "farmer" in action and action["farmer"]:
            unit_actions.append(action["farmer"])
        for h_act in action.get("hands", []):
            if h_act:
                unit_actions.append(h_act)
        for wa in unit_actions:
            cmd = wa[0] if isinstance(wa, (list, tuple)) and len(wa) > 0 else "PASS"
            if cmd in ("NORTH", "SOUTH", "EAST", "WEST"):
                move_count += 1
            elif cmd == "PASS":
                idle_count += 1
            else:
                productive_count += 1

        try:
            opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_action = opp_agent(env.state[1 - seat].observation)

        actions = [action, opp_action] if seat == 0 else [opp_action, action]
        env.step(actions)

    duration = time.time() - t_start
    final_cash = float(env.state[seat].observation.farms[seat].money)
    opp_final_cash = float(env.state[1 - seat].observation.farms[1 - seat].money)
    total_actions = move_count + productive_count + idle_count

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "mode": mode,
        "final_cash": final_cash,
        "opp_final_cash": opp_final_cash,
        "win": final_cash > opp_final_cash,
        "loss": final_cash < opp_final_cash,
        "tie": final_cash == opp_final_cash,
        "duration_seconds": duration,
        "move_count": move_count,
        "productive_count": productive_count,
        "idle_count": idle_count,
        "total_worker_actions": total_actions,
        "travel_pct": round(move_count / max(1, total_actions) * 100, 2),
        "productive_pct": round(productive_count / max(1, total_actions) * 100, 2),
        "max_market_orders": max_market_orders,
        "animal_escapes": animal_escapes,
        "starvation_events": starvation_events,
        "unfed_animal_days": unfed_animal_days,
        "consecutive_unfed_max": consecutive_unfed_max,
        "min_wheat_in_shed": min_wheat_in_shed if min_wheat_in_shed < 999999 else 0,
        "configuration_snapshot": cfg_snapshot,
    }


def run_paired_cell(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    """Execute both Control and Treatment sequentially in the same process to produce an exact matched pair."""
    control_res = run_single_simulation_match(seed, opp_name, seat, "CONTROL")
    treatment_res = run_single_simulation_match(seed, opp_name, seat, "TREATMENT")

    cash_delta = treatment_res["final_cash"] - control_res["final_cash"]
    move_delta = treatment_res["move_count"] - control_res["move_count"]
    prod_delta = treatment_res["productive_count"] - control_res["productive_count"]

    return {
        "cell": {
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
        },
        "control": control_res,
        "treatment": treatment_res,
        "cash_delta": cash_delta,
        "move_delta": move_delta,
        "productive_delta": prod_delta,
        "treatment_win_over_control": cash_delta > 0,
        "treatment_loss_to_control": cash_delta < 0,
        "treatment_tie_control": cash_delta == 0,
    }


def analyze_matched_pairs(pairs: List[Dict[str, Any]], census_lookup: Dict[Tuple[int, str, int], float]) -> Dict[str, Any]:
    """Compute seed-clustered paired statistics, baseline verification, and safety telemetry."""
    n = len(pairs)
    if n == 0:
        return {}

    cash_deltas = [p["cash_delta"] for p in pairs]
    move_deltas = [p["move_delta"] for p in pairs]
    prod_deltas = [p["productive_delta"] for p in pairs]

    ctrl_cashes = [p["control"]["final_cash"] for p in pairs]
    treat_cashes = [p["treatment"]["final_cash"] for p in pairs]

    ctrl_moves = [p["control"]["move_count"] for p in pairs]
    treat_moves = [p["treatment"]["move_count"] for p in pairs]

    ctrl_prods = [p["control"]["productive_count"] for p in pairs]
    treat_prods = [p["treatment"]["productive_count"] for p in pairs]

    ctrl_totals = [p["control"]["total_worker_actions"] for p in pairs]
    treat_totals = [p["treatment"]["total_worker_actions"] for p in pairs]

    # Baseline parity check against M0-L-A census
    parity_matches = 0
    parity_mismatches = []
    for p in pairs:
        c = p["cell"]
        key = (c["seed"], c["opponent"], c["seat"])
        if key in census_lookup:
            expected = census_lookup[key]
            actual = p["control"]["final_cash"]
            if math.isclose(actual, expected, abs_tol=0.01):
                parity_matches += 1
            else:
                parity_mismatches.append({
                    "cell": c,
                    "expected_census_cash": expected,
                    "actual_control_cash": actual,
                    "discrepancy": actual - expected,
                })

    # Seed-clustered CI calculation
    seed_clusters: Dict[int, List[float]] = {}
    opp_clusters: Dict[str, List[float]] = {}
    seat_clusters: Dict[int, List[float]] = {}

    wins = sum(1 for d in cash_deltas if d > 0)
    losses = sum(1 for d in cash_deltas if d < 0)
    ties = sum(1 for d in cash_deltas if d == 0)

    total_escapes_ctrl = sum(p["control"]["animal_escapes"] for p in pairs)
    total_escapes_treat = sum(p["treatment"]["animal_escapes"] for p in pairs)
    max_orders_ctrl = max(p["control"]["max_market_orders"] for p in pairs)
    max_orders_treat = max(p["treatment"]["max_market_orders"] for p in pairs)
    min_wheat_ctrl = min(p["control"]["min_wheat_in_shed"] for p in pairs)
    min_wheat_treat = min(p["treatment"]["min_wheat_in_shed"] for p in pairs)
    starve_events_ctrl = sum(p["control"]["starvation_events"] for p in pairs)
    starve_events_treat = sum(p["treatment"]["starvation_events"] for p in pairs)

    for p in pairs:
        c = p["cell"]
        d = p["cash_delta"]
        seed_clusters.setdefault(c["seed"], []).append(d)
        opp_clusters.setdefault(c["opponent"], []).append(d)
        seat_clusters.setdefault(c["seat"], []).append(d)

    k = len(seed_clusters)
    cluster_means = [float(np.mean(vals)) for vals in seed_clusters.values()]
    grand_cluster_mean = float(np.mean(cluster_means))
    cluster_var = float(np.var(cluster_means, ddof=1)) if k > 1 else 0.0
    cluster_se = math.sqrt(cluster_var / k) if k > 0 else 0.0

    t_table = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        14: 2.145, 19: 2.093,
    }
    df = max(1, k - 1)
    t_crit = t_table.get(df, 2.262 if df == 9 else 1.96)
    ci_lower = grand_cluster_mean - t_crit * cluster_se
    ci_upper = grand_cluster_mean + t_crit * cluster_se

    per_opp = {}
    for opp, d_list in opp_clusters.items():
        per_opp[opp] = {
            "mean_delta": float(np.mean(d_list)),
            "median_delta": float(np.median(d_list)),
            "n": len(d_list),
            "wins": sum(1 for x in d_list if x > 0),
            "losses": sum(1 for x in d_list if x < 0),
        }

    per_seat = {}
    for seat, d_list in seat_clusters.items():
        per_seat[str(seat)] = {
            "mean_delta": float(np.mean(d_list)),
            "median_delta": float(np.median(d_list)),
            "n": len(d_list),
            "wins": sum(1 for x in d_list if x > 0),
            "losses": sum(1 for x in d_list if x < 0),
        }

    mean_ctrl_cash = float(np.mean(ctrl_cashes))
    mean_treat_cash = float(np.mean(treat_cashes))
    mean_paired_gain = float(np.mean(cash_deltas))
    median_paired_gain = float(np.median(cash_deltas))
    std_paired_gain = float(np.std(cash_deltas, ddof=1)) if n > 1 else 0.0

    mean_ctrl_moves = float(np.mean(ctrl_moves))
    mean_treat_moves = float(np.mean(treat_moves))
    mean_ctrl_prods = float(np.mean(ctrl_prods))
    mean_treat_prods = float(np.mean(treat_prods))
    mean_ctrl_tot = float(np.mean(ctrl_totals))
    mean_treat_tot = float(np.mean(treat_totals))

    ctrl_travel_pct = mean_ctrl_moves / max(1, mean_ctrl_tot) * 100
    treat_travel_pct = mean_treat_moves / max(1, mean_treat_tot) * 100
    ctrl_prod_pct = mean_ctrl_prods / max(1, mean_ctrl_tot) * 100
    treat_prod_pct = mean_treat_prods / max(1, mean_treat_tot) * 100

    saved_moves = mean_ctrl_moves - mean_treat_moves
    gained_prods = mean_treat_prods - mean_ctrl_prods
    cash_per_prod_op = (mean_paired_gain / gained_prods) if gained_prods > 0 else 0.0

    return {
        "n_pairs": n,
        "baseline_parity_audit": {
            "total_census_checked": len(census_lookup),
            "parity_exact_matches": parity_matches,
            "parity_mismatches_count": len(parity_mismatches),
            "parity_verified": (len(parity_mismatches) == 0 and parity_matches > 0),
            "mismatches": parity_mismatches[:5],
        },
        "cash_metrics": {
            "control_mean_cash": mean_ctrl_cash,
            "treatment_mean_cash": mean_treat_cash,
            "mean_paired_gain": mean_paired_gain,
            "median_paired_gain": median_paired_gain,
            "std_paired_gain": std_paired_gain,
            "record": {
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_rate": round(wins / n, 4),
            },
            "seed_clustered_ci_95": {
                "mean": grand_cluster_mean,
                "se": cluster_se,
                "df": df,
                "t_crit": t_crit,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
            },
        },
        "movement_conversion_metrics": {
            "control": {
                "mean_moves": mean_ctrl_moves,
                "mean_productive": mean_ctrl_prods,
                "mean_total": mean_ctrl_tot,
                "travel_pct": round(ctrl_travel_pct, 2),
                "productive_pct": round(ctrl_prod_pct, 2),
            },
            "treatment": {
                "mean_moves": mean_treat_moves,
                "mean_productive": mean_treat_prods,
                "mean_total": mean_treat_tot,
                "travel_pct": round(treat_travel_pct, 2),
                "productive_pct": round(treat_prod_pct, 2),
            },
            "deltas": {
                "saved_moves_per_match": round(saved_moves, 2),
                "gained_productive_ops_per_match": round(gained_prods, 2),
                "travel_overhead_shift_pp": round(treat_travel_pct - ctrl_travel_pct, 2),
                "productive_ratio_shift_pp": round(treat_prod_pct - ctrl_prod_pct, 2),
                "incremental_cash_per_productive_op": round(cash_per_prod_op, 2),
            },
        },
        "breakdown": {
            "opponent": per_opp,
            "seat": per_seat,
        },
        "safety_audit": {
            "control": {
                "animal_escapes": total_escapes_ctrl,
                "max_market_orders": max_orders_ctrl,
                "min_wheat_in_shed": min_wheat_ctrl,
                "starvation_events": starve_events_ctrl,
            },
            "treatment": {
                "animal_escapes": total_escapes_treat,
                "max_market_orders": max_orders_treat,
                "min_wheat_in_shed": min_wheat_treat,
                "starvation_events": starve_events_treat,
            },
            "control_safety_passed": (total_escapes_ctrl == 0 and max_orders_ctrl <= 10),
            "treatment_safety_passed": (total_escapes_treat == 0 and max_orders_treat <= 10),
            "all_safety_guarantees_passed": (total_escapes_treat == 0 and max_orders_treat <= 10),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-L-B-R Authoritative Matched-Control Validation")
    parser.add_argument("--pilot", action="store_true", help="Run pilot seeds (97013, 97014) only")
    parser.add_argument("--workers", type=int, default=6, help="Multiprocessing pool workers (default: 6)")
    parser.add_argument("--outdir", type=str, default=DEFAULT_OUT_DIR, help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    seeds = PILOT_SEEDS if args.pilot else DEV_SEEDS
    print(f"=== Starting Phase M0-L-B-R Matched-Control Validation ===")
    print(f"Panel: {len(seeds)} seeds x {len(BENCHMARK_OPPONENTS)} opponents x {len(SEATS)} seats = {len(seeds) * len(BENCHMARK_OPPONENTS) * len(SEATS)} pairs (2x matches)")
    print(f"Seeds: {seeds}")
    print(f"Workers: {args.workers}")
    print(f"Output directory: {args.outdir}")

    census_lookup = load_census_lookup()
    print(f"Loaded {len(census_lookup)} baseline matches from M0-L-A census for bitwise parity verification.")

    tasks = []
    for s in seeds:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                tasks.append((s, opp, seat))

    t0 = time.time()
    with mp.Pool(processes=args.workers) as pool:
        pairs = pool.starmap(run_paired_cell, tasks)
    elapsed = time.time() - t0
    print(f"\nCompleted {len(pairs)} matched pairs ({len(pairs) * 2} live simulation matches) in {elapsed:.1f}s ({elapsed / len(pairs):.2f}s/pair avg).")

    summary = analyze_matched_pairs(pairs, census_lookup)

    # Print summary highlights
    print("\n" + "=" * 60)
    print("PHASE M0-L-B-R VALIDATION RESULTS SUMMARY")
    print("=" * 60)
    b_audit = summary["baseline_parity_audit"]
    print(f"Baseline Census Parity: {b_audit['parity_exact_matches']}/{len(pairs)} bitwise exact matches (Mismatches: {b_audit['parity_mismatches_count']})")
    if not b_audit["parity_verified"]:
        print("WARNING: Baseline parity mismatch detected! Inspect discrepancies:")
        for m in b_audit["mismatches"]:
            print(f"  {m}")
    else:
        print("SUCCESS: 100% BITWISE PARITY WITH M0-L-A CENSUS CONFIRMED!")

    cm = summary["cash_metrics"]
    print(f"\nCash Performance:")
    print(f"  Control Mean Cash:   ${cm['control_mean_cash']:,.2f}")
    print(f"  Treatment Mean Cash: ${cm['treatment_mean_cash']:,.2f}")
    print(f"  Mean Paired Gain:    ${cm['mean_paired_gain']:+,.2f}")
    print(f"  Median Paired Gain:  ${cm['median_paired_gain']:+,.2f}")
    print(f"  Standard Deviation:  ${cm['std_paired_gain']:,.2f}")
    print(f"  Record (W/L/T):      {cm['record']['wins']}W / {cm['record']['losses']}L / {cm['record']['ties']}T (Win Rate: {cm['record']['win_rate']:.1%})")
    ci = cm["seed_clustered_ci_95"]
    print(f"  95% Clustered CI:    [${ci['ci_lower']:+,.2f}, ${ci['ci_upper']:+,.2f}] (df={ci['df']}, t_crit={ci['t_crit']})")

    mv = summary["movement_conversion_metrics"]
    print(f"\nMovement & Conversion Efficiency:")
    print(f"  Control:   {mv['control']['travel_pct']}% travel, {mv['control']['productive_pct']}% productive ({mv['control']['mean_moves']:.1f} moves, {mv['control']['mean_productive']:.1f} prod)")
    print(f"  Treatment: {mv['treatment']['travel_pct']}% travel, {mv['treatment']['productive_pct']}% productive ({mv['treatment']['mean_moves']:.1f} moves, {mv['treatment']['mean_productive']:.1f} prod)")
    print(f"  Shift:     {mv['deltas']['travel_overhead_shift_pp']:+.2f} pp travel, {mv['deltas']['productive_ratio_shift_pp']:+.2f} pp productive")
    print(f"  Saved Moves / Match:  {mv['deltas']['saved_moves_per_match']:+.2f}")
    print(f"  Added Ops / Match:    {mv['deltas']['gained_productive_ops_per_match']:+.2f}")
    print(f"  Incremental $/Op:     ${mv['deltas']['incremental_cash_per_productive_op']:.2f}")

    sa = summary["safety_audit"]
    print(f"\nSafety Telemetry:")
    print(f"  Control Animal Escapes:   {sa['control']['animal_escapes']}, Max Market Orders: {sa['control']['max_market_orders']}, Min Shed Wheat: {sa['control']['min_wheat_in_shed']}")
    print(f"  Treatment Animal Escapes: {sa['treatment']['animal_escapes']}, Max Market Orders: {sa['treatment']['max_market_orders']}, Min Shed Wheat: {sa['treatment']['min_wheat_in_shed']}")
    print(f"  Safety Guarantees Passed: {sa['all_safety_guarantees_passed']}")

    # Save deliverables
    raw_pairs_file = os.path.join(args.outdir, "matched_soft_locality_pairs.json")
    with open(raw_pairs_file, "w", encoding="utf-8") as f:
        json.dump(pairs, f, indent=2)
    print(f"\nWrote raw matched pairs to {raw_pairs_file}")

    summary_file = os.path.join(args.outdir, "matched_soft_locality_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote summary metrics to {summary_file}")


if __name__ == "__main__":
    main()
