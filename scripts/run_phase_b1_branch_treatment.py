"""Phase B1: True Branch-Point SW Treatment Experiment Runner.

Executes real-engine paired evaluation:
- 20 discovery seeds: 96501-96520
- 5 benchmark opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 seats: 0 and 1
- 200 paired configurations (400 real engine matches total)
- CONTROL: SW_FORWARD_ARCHITECTURE_MODE = "OFF" (baseline early SW)
- TREATMENT: SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT" (delayed purchase + compact tranche)
- Primary metric: Paired Delta = Treatment_FinalCash - Control_FinalCash
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
_RESULTS_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_b1_branch_treatment")

DISCOVERY_SEEDS = list(range(96501, 96521))  # 20 seeds: 96501-96520
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def _clean_json(obj: Any) -> Any:
    """Recursively convert sets/tuples/custom objects to json-friendly types."""
    if isinstance(obj, (set, tuple, list)):
        return [_clean_json(x) for x in obj]
    elif isinstance(obj, dict):
        return {str(k): _clean_json(v) for k, v in obj.items()}
    elif isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    elif hasattr(obj, "__dict__"):
        return _clean_json(obj.__dict__)
    else:
        return str(obj)


def _compute_percentiles(values: List[float]) -> Dict[str, float]:
    """Compute summary percentiles for a list of floats."""
    if not values:
        return {"min": 0.0, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}
    s = sorted(values)
    n = len(s)
    mean_val = float(sum(s)) / n
    variance = sum((x - mean_val) ** 2 for x in s) / n if n > 0 else 0.0
    return {
        "min": round(s[0], 2),
        "p10": round(s[int(0.10 * n)], 2),
        "p25": round(s[int(0.25 * n)], 2),
        "p50": round(s[int(0.50 * n)], 2),
        "p75": round(s[int(0.75 * n)], 2),
        "p90": round(s[min(n - 1, int(0.90 * n))], 2),
        "max": round(s[-1], 2),
        "mean": round(mean_val, 2),
        "std": round(math.sqrt(variance), 2),
    }


def _bootstrap_ci_95(deltas: List[float], n_resamples: int = 10000, seed: int = 42) -> Tuple[float, float]:
    """Calculate 95% bootstrap confidence interval for mean delta."""
    if not deltas:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(deltas)
    means = []
    for _ in range(n_resamples):
        sample = [deltas[rng.randint(0, n - 1)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = round(means[int(0.025 * n_resamples)], 2)
    hi = round(means[int(0.975 * n_resamples)], 2)
    return (lo, hi)


def _worker_run_single_match(
    seed: int,
    opp_name: str,
    seat: int,
    mode: str,
) -> Dict[str, Any]:
    """Run a single 720-turn match under either OFF (Control) or TREATMENT."""
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    from kaggle_environments import make
    import config
    from main import agent, reset_agent_state, get_last_shadow_result
    from strategy.sw_tranche_controller import get_sw_tranche_controller, reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    config.set_sw_forward_architecture_mode(mode)
    reset_agent_state()
    reset_sw_tranche_controller()
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(mode == "TREATMENT")

    opp_agent = get_agent(opp_name)

    sw_purchase_day: Optional[int] = None
    sw_purchase_hour: Optional[int] = None
    sw_unlocked_day: Optional[int] = None
    sw_planted_tiles_max: int = 0
    sw_owned_tiles_max: int = 0
    step_records: List[Dict[str, Any]] = []

    def our_agent_wrapper(obs, conf=None):
        nonlocal sw_purchase_day, sw_purchase_hour, sw_unlocked_day, sw_planted_tiles_max, sw_owned_tiles_max
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)

        act = agent(obs, conf)

        # Check if land buy was emitted this turn
        m_orders = act.get("market", [])
        if any(isinstance(o, (list, tuple)) and len(o) > 0 and o[0] == "BUY_LAND" for o in m_orders):
            # Check if this was SW purchase
            player_id = obs.get("player", 0)
            farms = obs.get("farms", [])
            our_farm = farms[player_id] if len(farms) > player_id else {}
            unlocked = our_farm.get("unlocked_quadrants", ["NW"])
            if len(unlocked) == 2 and "SW" not in unlocked and sw_purchase_day is None:
                sw_purchase_day = day
                sw_purchase_hour = hour

        # Check if SW is unlocked in farm
        player_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        our_farm = farms[player_id] if len(farms) > player_id else {}
        unlocked = our_farm.get("unlocked_quadrants", ["NW"])
        if "SW" in unlocked and sw_unlocked_day is None:
            sw_unlocked_day = day

        # Count SW planted tiles
        tiles = our_farm.get("tiles", [])
        planted_sw = 0
        for y, row in enumerate(tiles):
            for x, t in enumerate(row):
                if x < 5 and y >= 5:
                    if isinstance(t, dict) and (t.get("is_plant") or t.get("kind") == "PLANT"):
                        planted_sw += 1
        if planted_sw > sw_planted_tiles_max:
            sw_planted_tiles_max = planted_sw

        return act

    p0 = our_agent_wrapper if seat == 0 else opp_agent
    p1 = our_agent_wrapper if seat == 1 else opp_agent

    env_error: Optional[str] = None
    try:
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
        env.run([p0, p1])
    except Exception as e:
        env_error = str(e)

    steps = getattr(env, "steps", [])
    if steps and len(steps) > 0:
        final_step = steps[-1]
        r0 = float(final_step[0].get("reward") or 0.0)
        r1 = float(final_step[1].get("reward") or 0.0)
        our_cash = r0 if seat == 0 else r1
        opp_cash = r1 if seat == 0 else r0
    else:
        our_cash = 0.0
        opp_cash = 0.0

    treatment_summary = ctrl.get_summary() if mode == "TREATMENT" else None

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "mode": mode,
        "our_cash": round(our_cash, 2),
        "opp_cash": round(opp_cash, 2),
        "sw_purchase_day": sw_purchase_day,
        "sw_purchase_hour": sw_purchase_hour,
        "sw_unlocked_day": sw_unlocked_day,
        "sw_planted_tiles_max": sw_planted_tiles_max,
        "treatment_summary": treatment_summary,
        "env_error": env_error,
    }


def _run_pair(cfg: Tuple[int, str, int]) -> Dict[str, Any]:
    """Execute matched pair (CONTROL and TREATMENT)."""
    seed, opp_name, seat = cfg
    control_res = _worker_run_single_match(seed, opp_name, seat, mode="OFF")
    treatment_res = _worker_run_single_match(seed, opp_name, seat, mode="TREATMENT")

    paired_delta = round(treatment_res["our_cash"] - control_res["our_cash"], 2)
    t_sum = treatment_res.get("treatment_summary") or {}

    return {
        "seed": seed,
        "opp_name": opp_name,
        "seat": seat,
        "control_cash": control_res["our_cash"],
        "treatment_cash": treatment_res["our_cash"],
        "paired_delta": paired_delta,
        "control_sw_purchase_day": control_res["sw_purchase_day"],
        "treatment_sw_purchase_day": treatment_res["sw_purchase_day"],
        "control_sw_planted_max": control_res["sw_planted_tiles_max"],
        "treatment_sw_planted_max": treatment_res["sw_planted_tiles_max"],
        "treatment_selected_portfolio": t_sum.get("selected_portfolio_name"),
        "treatment_admitted_tiles_count": t_sum.get("admitted_tiles_count", 0),
        "treatment_predicted_delta_fc": t_sum.get("predicted_delta_fc", 0.0),
        "treatment_invariant_violations": t_sum.get("invariant_violations_attempted", 0),
        "treatment_no_purchase_reason": t_sum.get("primary_no_purchase_reason"),
        "checkpoints": t_sum.get("checkpoints", {}),
        "core_safety": t_sum.get("core_safety", {}),
        "sw_crops_sold": t_sum.get("sw_crops_sold", {}),
        "sw_revenue_realized": t_sum.get("sw_revenue_realized", 0.0),
        "sw_seed_cost_realized": t_sum.get("sw_seed_cost_realized", 0.0),
    }


def run_experiment(
    seeds: List[int],
    opponents: List[str],
    seats: List[int],
    max_workers: int = 8,
    is_smoke: bool = False,
) -> Dict[str, Any]:
    """Run full matrix or smoke test."""
    matrix = [(seed, opp, seat) for seed in seeds for opp in opponents for seat in seats]
    total_pairs = len(matrix)
    print(f"\n======================================================================")
    print(f"Phase B1 True Branch Treatment: Starting {'SMOKE' if is_smoke else 'FULL'} Matrix")
    print(f"Seeds ({len(seeds)}): {seeds}")
    print(f"Opponents ({len(opponents)}): {opponents}")
    print(f"Seats ({len(seats)}): {seats}")
    print(f"Total Paired Configurations: {total_pairs} (x2 = {total_pairs * 2} matches)")
    print(f"Max Worker Processes: {max_workers}")
    print(f"======================================================================\n")

    t_start = time.perf_counter()
    paired_results: List[Dict[str, Any]] = []

    if max_workers > 1 and total_pairs > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_cfg = {executor.submit(_run_pair, cfg): cfg for cfg in matrix}
            completed = 0
            for fut in as_completed(future_to_cfg):
                res = fut.result()
                paired_results.append(res)
                completed += 1
                cfg = (res["seed"], res["opp_name"], res["seat"])
                print(f"[{completed:3d}/{total_pairs:3d}] Seed {cfg[0]} vs {cfg[1]:20s} (Seat {cfg[2]}): "
                      f"Ctrl=${res['control_cash']:8.1f} | Treat=${res['treatment_cash']:8.1f} | "
                      f"Delta=${res['paired_delta']:+8.1f} | "
                      f"SW Buy: Ctrl=D{res['control_sw_purchase_day'] or 'None'} Treat=D{res['treatment_sw_purchase_day'] or 'None'} | "
                      f"Tranche={res['treatment_selected_portfolio'] or 'None'}")
    else:
        for idx, cfg in enumerate(matrix):
            res = _run_pair(cfg)
            paired_results.append(res)
            print(f"[{idx+1:3d}/{total_pairs:3d}] Seed {cfg[0]} vs {cfg[1]:20s} (Seat {cfg[2]}): "
                  f"Ctrl=${res['control_cash']:8.1f} | Treat=${res['treatment_cash']:8.1f} | "
                  f"Delta=${res['paired_delta']:+8.1f} | "
                  f"SW Buy: Ctrl=D{res['control_sw_purchase_day'] or 'None'} Treat=D{res['treatment_sw_purchase_day'] or 'None'}")

    dur_s = time.perf_counter() - t_start
    print(f"\nExecution finished in {dur_s:.1f} seconds ({dur_s/60:.2f} minutes).")

    # Aggregate Analysis
    control_cashes = [r["control_cash"] for r in paired_results]
    treatment_cashes = [r["treatment_cash"] for r in paired_results]
    paired_deltas = [r["paired_delta"] for r in paired_results]

    stats_ctrl = _compute_percentiles(control_cashes)
    stats_treat = _compute_percentiles(treatment_cashes)
    stats_delta = _compute_percentiles(paired_deltas)
    ci_95 = _bootstrap_ci_95(paired_deltas, seed=42)

    pos_pairs = sum(1 for d in paired_deltas if d > 0)
    neg_pairs = sum(1 for d in paired_deltas if d < 0)
    tie_pairs = sum(1 for d in paired_deltas if d == 0)

    # Opponent Breakdown
    opp_breakdown = {}
    for opp in opponents:
        opp_pairs = [r for r in paired_results if r["opp_name"] == opp]
        if opp_pairs:
            c_vals = [r["control_cash"] for r in opp_pairs]
            t_vals = [r["treatment_cash"] for r in opp_pairs]
            d_vals = [r["paired_delta"] for r in opp_pairs]
            wins = sum(1 for d in d_vals if d > 0)
            opp_breakdown[opp] = {
                "count": len(opp_pairs),
                "control_mean": round(float(sum(c_vals)) / len(c_vals), 2),
                "treatment_mean": round(float(sum(t_vals)) / len(t_vals), 2),
                "mean_delta": round(float(sum(d_vals)) / len(d_vals), 2),
                "median_delta": round(sorted(d_vals)[len(d_vals) // 2], 2),
                "treatment_wins": wins,
                "win_rate_pct": round(wins / len(opp_pairs) * 100.0, 1),
            }

    # Seat Breakdown
    seat_breakdown = {}
    for seat in seats:
        seat_pairs = [r for r in paired_results if r["seat"] == seat]
        if seat_pairs:
            c_vals = [r["control_cash"] for r in seat_pairs]
            t_vals = [r["treatment_cash"] for r in seat_pairs]
            d_vals = [r["paired_delta"] for r in seat_pairs]
            seat_breakdown[seat] = {
                "count": len(seat_pairs),
                "control_mean": round(float(sum(c_vals)) / len(c_vals), 2),
                "treatment_mean": round(float(sum(t_vals)) / len(t_vals), 2),
                "mean_delta": round(float(sum(d_vals)) / len(d_vals), 2),
                "median_delta": round(sorted(d_vals)[len(d_vals) // 2], 2),
            }

    # Purchase Timing Distribution
    timing_bins = {"never": 0, "D5": 0, "D6": 0, "D7": 0, "D8": 0, "D9": 0, "D10": 0, "D11": 0, "D12+": 0}
    timing_ctrl_bins = {"never": 0, "D5": 0, "D6": 0, "D7": 0, "D8": 0, "D9": 0, "D10": 0, "D11": 0, "D12+": 0}

    for r in paired_results:
        # Treatment timing
        t_day = r["treatment_sw_purchase_day"]
        if t_day is None:
            timing_bins["never"] += 1
        elif t_day == 5:
            timing_bins["D5"] += 1
        elif t_day == 6:
            timing_bins["D6"] += 1
        elif t_day == 7:
            timing_bins["D7"] += 1
        elif t_day == 8:
            timing_bins["D8"] += 1
        elif t_day == 9:
            timing_bins["D9"] += 1
        elif t_day == 10:
            timing_bins["D10"] += 1
        elif t_day == 11:
            timing_bins["D11"] += 1
        else:
            timing_bins["D12+"] += 1

        # Control timing
        c_day = r["control_sw_purchase_day"]
        if c_day is None:
            timing_ctrl_bins["never"] += 1
        elif c_day == 5:
            timing_ctrl_bins["D5"] += 1
        elif c_day == 6:
            timing_ctrl_bins["D6"] += 1
        elif c_day == 7:
            timing_ctrl_bins["D7"] += 1
        elif c_day == 8:
            timing_ctrl_bins["D8"] += 1
        elif c_day == 9:
            timing_ctrl_bins["D9"] += 1
        elif c_day == 10:
            timing_ctrl_bins["D10"] += 1
        elif c_day == 11:
            timing_ctrl_bins["D11"] += 1
        else:
            timing_ctrl_bins["D12+"] += 1

    # First Tranche Distribution
    tranche_dist = {}
    for r in paired_results:
        p_name = r["treatment_selected_portfolio"] or "no_purchase"
        if p_name not in tranche_dist:
            tranche_dist[p_name] = {"count": 0, "deltas": []}
        tranche_dist[p_name]["count"] += 1
        tranche_dist[p_name]["deltas"].append(r["paired_delta"])

    tranche_summary = {}
    for p_name, d in tranche_dist.items():
        tranche_summary[p_name] = {
            "count": d["count"],
            "mean_delta": round(float(sum(d["deltas"])) / len(d["deltas"]), 2),
            "median_delta": round(sorted(d["deltas"])[len(d["deltas"]) // 2], 2),
        }

    # SW Utilization at Checkpoints
    util_by_checkpoint = {}
    for label in ("D+0", "D+1", "D+2", "D+3", "D+5", "D+7"):
        whole_quad_list = []
        tranche_list = []
        for r in paired_results:
            cp = r.get("checkpoints", {}).get(label)
            if cp:
                whole_quad_list.append(cp["whole_quadrant_utilization_pct"])
                tranche_list.append(cp["admitted_tranche_utilization_pct"])
        if whole_quad_list:
            util_by_checkpoint[label] = {
                "count": len(whole_quad_list),
                "mean_whole_quadrant_util_pct": round(float(sum(whole_quad_list)) / len(whole_quad_list), 1),
                "mean_tranche_util_pct": round(float(sum(tranche_list)) / len(tranche_list), 1),
            }

    # No-purchase Cases Analysis
    no_purchase_cases = [r for r in paired_results if r["treatment_sw_purchase_day"] is None]
    no_purchase_summary = {
        "count": len(no_purchase_cases),
        "reasons": {},
        "mean_control_cash": round(float(sum(r["control_cash"] for r in no_purchase_cases)) / len(no_purchase_cases), 2) if no_purchase_cases else 0.0,
        "mean_treatment_cash": round(float(sum(r["treatment_cash"] for r in no_purchase_cases)) / len(no_purchase_cases), 2) if no_purchase_cases else 0.0,
        "mean_paired_delta": round(float(sum(r["paired_delta"] for r in no_purchase_cases)) / len(no_purchase_cases), 2) if no_purchase_cases else 0.0,
    }
    for r in no_purchase_cases:
        reason = r.get("treatment_no_purchase_reason") or "unspecified"
        no_purchase_summary["reasons"][reason] = no_purchase_summary["reasons"].get(reason, 0) + 1

    # Invariant Violations Total
    total_violations = sum(r.get("treatment_invariant_violations", 0) for r in paired_results)

    aggregate_data = {
        "metadata": {
            "is_smoke": is_smoke,
            "seeds": seeds,
            "opponents": opponents,
            "seats": seats,
            "total_pairs": total_pairs,
            "total_matches": total_pairs * 2,
            "execution_duration_seconds": round(dur_s, 2),
            "invariant_violations_total": total_violations,
        },
        "table_a_overall": {
            "control": stats_ctrl,
            "treatment": stats_treat,
            "paired_delta": stats_delta,
        },
        "table_b_paired_outcome": {
            "mean_paired_delta": stats_delta["mean"],
            "median_paired_delta": stats_delta["p50"],
            "std_paired_delta": stats_delta["std"],
            "bootstrap_ci_95": ci_95,
            "positive_pairs": pos_pairs,
            "negative_pairs": neg_pairs,
            "ties": tie_pairs,
            "win_rate_pct": round(pos_pairs / total_pairs * 100.0, 1) if total_pairs > 0 else 0.0,
        },
        "table_c_purchase_timing": {
            "treatment": timing_bins,
            "control": timing_ctrl_bins,
        },
        "table_d_first_tranche": tranche_summary,
        "table_e_opponents": opp_breakdown,
        "table_f_utilization": util_by_checkpoint,
        "seat_breakdown": seat_breakdown,
        "no_purchase_analysis": no_purchase_summary,
    }

    # Save outputs
    os.makedirs(_RESULTS_DIR, exist_ok=True)
    with open(os.path.join(_RESULTS_DIR, "manifest.json"), "w") as f:
        json.dump({
            "seeds": seeds,
            "opponents": opponents,
            "seats": seats,
            "total_pairs": total_pairs,
            "bootstrap_seed": 42,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2)

    with open(os.path.join(_RESULTS_DIR, "paired_results.json"), "w") as f:
        json.dump(paired_results, f, indent=2)

    with open(os.path.join(_RESULTS_DIR, "aggregate_tables.json"), "w") as f:
        json.dump(aggregate_data, f, indent=2)

    with open(os.path.join(_RESULTS_DIR, "purchase_timing.json"), "w") as f:
        json.dump({"treatment": timing_bins, "control": timing_ctrl_bins}, f, indent=2)

    with open(os.path.join(_RESULTS_DIR, "utilization.json"), "w") as f:
        json.dump(util_by_checkpoint, f, indent=2)

    with open(os.path.join(_RESULTS_DIR, "representative_traces.json"), "w") as f:
        # Save a sample of representative traces (first 10 pairs)
        json.dump(paired_results[:10], f, indent=2)

    return aggregate_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Phase B1 SW Branch Treatment Experiment.")
    parser.add_argument("--smoke", action="store_true", help="Run 2-pair smoke test only.")
    parser.add_argument("--full", action="store_true", help="Run full 200-pair matrix.")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel processes.")
    args = parser.parse_args()

    if args.smoke:
        # 2 configurations: seed 96501 vs pass and vs pure_wheat_rush, seat 0
        smoke_seeds = [96501]
        smoke_opps = ["pass", "pure_wheat_rush"]
        smoke_seats = [0]
        results = run_experiment(smoke_seeds, smoke_opps, smoke_seats, max_workers=2, is_smoke=True)
        print("\n=== Smoke Test Summary ===")
        print(f"Mean Paired Delta: ${results['table_b_paired_outcome']['mean_paired_delta']:+.2f}")
        print(f"Positive Pairs: {results['table_b_paired_outcome']['positive_pairs']}/{results['metadata']['total_pairs']}")
        print(f"Invariant Violations: {results['metadata']['invariant_violations_total']}")
    elif args.full:
        results = run_experiment(DISCOVERY_SEEDS, BENCHMARK_OPPONENTS, SEATS, max_workers=args.workers, is_smoke=False)
        print("\n=== Full Matrix Summary ===")
        print(f"Mean Paired Delta: ${results['table_b_paired_outcome']['mean_paired_delta']:+.2f}")
        print(f"Median Paired Delta: ${results['table_b_paired_outcome']['median_paired_delta']:+.2f}")
        print(f"95% Bootstrap CI: {results['table_b_paired_outcome']['bootstrap_ci_95']}")
        print(f"Positive / Negative / Ties: {results['table_b_paired_outcome']['positive_pairs']} / {results['table_b_paired_outcome']['negative_pairs']} / {results['table_b_paired_outcome']['ties']}")
        print(f"Invariant Violations: {results['metadata']['invariant_violations_total']}")
    else:
        print("Specify --smoke or --full.")
