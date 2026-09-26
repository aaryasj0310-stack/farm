#!/usr/bin/env python3
"""Phase SW-B2-Gate2: LIVE SW Tranche-1 Controlled Canary Experiment.

Executes 20 matched pairs (40 total matches) across 5 canonical opponents,
both seats, on development seeds 97013-97014:
- Control: Canonical production baseline (SW_FORWARD_ARCHITECTURE_MODE = "OFF")
- Treatment: Smallest LIVE SW execution (SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT")
  First 8-tile SW tranche only (compact_commercial: 4 Strawberry + 4 Melon)
  after WholeFarmPlanner approval.

Measures and archives all 12 outcome categories.
"""
import copy
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import kaggle_environments as ke
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if os.path.join(PROJECT_ROOT, "agent") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "agent"))

CANARY_SEEDS = [97013, 97014]  # 2 development seeds
CANONICAL_OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]
SEATS = [0, 1]

_OUT_DIR = os.path.join(PROJECT_ROOT, "simulations", "results", "phase_sw_b2_gate2_canary")


def compute_file_sha256(path: str) -> str:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    return "NOT_FOUND"


def get_source_manifest() -> Dict[str, str]:
    files = {
        "kaggriculture_engine": r"C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py",
        "agent/main.py": os.path.join(PROJECT_ROOT, "agent", "main.py"),
        "agent/config.py": os.path.join(PROJECT_ROOT, "agent", "config.py"),
        "agent/execution/task_scheduler.py": os.path.join(PROJECT_ROOT, "agent", "execution", "task_scheduler.py"),
        "agent/execution/midnight_storage_controller.py": os.path.join(PROJECT_ROOT, "agent", "execution", "midnight_storage_controller.py"),
        "agent/strategy/sw_tranche_controller.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "sw_tranche_controller.py"),
        "agent/strategy/macro_planner.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "macro_planner.py"),
        "agent/strategy/farm_plan.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "farm_plan.py"),
        "agent/strategy/resource_ledger.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "resource_ledger.py"),
        "agent/strategy/service_certificate.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "service_certificate.py"),
        "agent/strategy/cohort_planner.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "cohort_planner.py"),
        "agent/strategy/whole_farm_planner.py": os.path.join(PROJECT_ROOT, "agent", "strategy", "whole_farm_planner.py"),
        "agent/diagnostics/animal_tracker.py": os.path.join(PROJECT_ROOT, "agent", "diagnostics", "animal_tracker.py"),
        "submission/main.py": os.path.join(PROJECT_ROOT, "submission", "main.py"),
        "submission/config.py": os.path.join(PROJECT_ROOT, "submission", "config.py"),
        "submission/strategy/sw_tranche_controller.py": os.path.join(PROJECT_ROOT, "submission", "strategy", "sw_tranche_controller.py"),
        "submission/strategy/macro_planner.py": os.path.join(PROJECT_ROOT, "submission", "strategy", "macro_planner.py"),
        "submission/strategy/farm_plan.py": os.path.join(PROJECT_ROOT, "submission", "strategy", "farm_plan.py"),
    }
    return {k: compute_file_sha256(v) for k, v in files.items()}


def run_single_match(seed: int, opp_name: str, seat: int, mode: str) -> Dict[str, Any]:
    """Execute a single scenario cell in either Control (OFF) or Treatment (TREATMENT) mode."""
    import agent.config as config
    config.SW_FORWARD_ARCHITECTURE_MODE = mode
    config.SOFT_WORKER_LOCALITY_MODE = "ON"
    config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
    config.QUADRANT_HARD_BLOCK = {4}

    from agent.main import agent as my_agent, reset_agent_state, get_last_shadow_result
    from agent.strategy.farm_plan import reset_farm_plan
    from agent.strategy.whole_farm_planner import reset_whole_farm_planner
    from agent.strategy.sw_tranche_controller import (
        get_sw_tranche_controller,
        reset_sw_tranche_controller,
    )
    from agent.execution.midnight_storage_controller import (
        reset_midnight_storage_telemetry,
        get_midnight_storage_telemetry,
    )
    from agent.diagnostics.animal_tracker import AnimalSurvivalTracker
    from simulations.experiments.agent_zoo import get_agent

    # Clean state reset
    reset_agent_state()
    reset_farm_plan()
    reset_whole_farm_planner()
    reset_sw_tranche_controller()
    reset_midnight_storage_telemetry()

    ctrl = get_sw_tranche_controller()
    if mode == "TREATMENT":
        ctrl.set_treatment_active(True)
    else:
        ctrl.set_treatment_active(False)

    animal_tracker = AnimalSurvivalTracker(seat=seat)
    opp_agent = get_agent(opp_name)

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()

    t_start = time.time()
    turn_latencies = []
    total_turns = 0
    min_cash_seen = 3000.0
    peak_shed_occupancy = 0

    sw_purchase_emitted_step = None
    sw_purchase_emitted_day = None
    sw_purchase_confirmed_step = None
    sw_purchase_confirmed_day = None

    while not env.done:
        obs0 = env.state[0].observation
        obs1 = env.state[1].observation

        my_obs = obs0 if seat == 0 else obs1
        opp_obs = obs1 if seat == 0 else obs0

        step = my_obs.get("step", total_turns)
        cur_day = step // 24
        cur_hour = step % 24
        cur_cash = float(my_obs["farms"][seat]["money"])
        if cur_cash < min_cash_seen:
            min_cash_seen = cur_cash

        # Track animal survival state
        animal_tracker.observe_turn(my_obs)

        # Track shed capacity
        private = my_obs.get("private", {})
        if not private and "privates" in my_obs:
            private = my_obs["privates"][seat]
        if private and "shed" in private and isinstance(private["shed"], dict):
            shed_sum = sum(int(v) for v in private["shed"].values())
            if shed_sum > peak_shed_occupancy:
                peak_shed_occupancy = shed_sum

        # Check engine SW unlock
        unlocked_quads = set(my_obs["farms"][seat].get("unlocked_quadrants", ["NW"]))
        if "SW" in unlocked_quads and sw_purchase_confirmed_step is None:
            sw_purchase_confirmed_step = step
            sw_purchase_confirmed_day = cur_day

        # Execute agent step with latency tracking
        t_agent_0 = time.perf_counter()
        my_act = my_agent(my_obs, env.configuration)
        t_agent_dur_ms = (time.perf_counter() - t_agent_0) * 1000.0
        turn_latencies.append(t_agent_dur_ms)

        # Track emitted BUY_LAND order
        if my_act and isinstance(my_act, dict):
            market_orders = my_act.get("market", [])
            for order in market_orders:
                if isinstance(order, (list, tuple)) and order and order[0] == "BUY_LAND":
                    if sw_purchase_emitted_step is None:
                        sw_purchase_emitted_step = step
                        sw_purchase_emitted_day = cur_day

        # Execute opponent turn
        try:
            opp_act = opp_agent(opp_obs, env.configuration)
        except TypeError:
            opp_act = opp_agent(opp_obs)

        # Step environment
        actions = [my_act, opp_act] if seat == 0 else [opp_act, my_act]
        env.step(actions)
        total_turns += 1

    # End of match metrics
    final_obs_my = env.state[seat].observation
    final_obs_opp = env.state[1 - seat].observation
    final_cash = float(final_obs_my["farms"][seat]["money"])
    opp_final_cash = float(final_obs_opp["farms"][1 - seat]["money"])
    win = final_cash > opp_final_cash

    rescue_telem = get_midnight_storage_telemetry()
    match_duration = time.time() - t_start
    animal_summary = animal_tracker.get_summary()

    # Capture SW tranche telemetry if treatment
    sw_telem = {}
    if mode == "TREATMENT":
        st = ctrl.state
        sw_telem = {
            "sw_purchase_approved": st.sw_purchase_approved,
            "sw_purchase_day": st.sw_purchase_day,
            "sw_purchase_hour": st.sw_purchase_hour,
            "sw_purchase_confirmed": st.sw_purchase_confirmed,
            "sw_order_emitted_step": sw_purchase_emitted_step,
            "sw_order_emitted_day": sw_purchase_emitted_day,
            "sw_unlock_step": sw_purchase_confirmed_step,
            "sw_unlock_day": sw_purchase_confirmed_day,
            "selected_portfolio_name": st.selected_portfolio_name,
            "predicted_delta_fc": st.predicted_delta_fc,
            "pre_purchase_cash": st.pre_purchase_cash,
            "post_purchase_cash": st.post_purchase_cash,
            "admitted_tiles_count": len(st.admitted_sw_tiles),
            "admitted_tiles": sorted(list(st.admitted_sw_tiles)),
            "sw_crops_planted": dict(st.sw_crops_planted),
            "sw_crops_sold": dict(st.sw_crops_sold),
            "sw_revenue_realized": st.sw_revenue_realized,
            "sw_land_cost_paid": st.sw_land_cost_paid,
            "sw_seed_cost_realized": st.sw_seed_cost_realized,
            "sw_seed_opportunity_cost": st.sw_seed_opportunity_cost,
            "invariant_violations_attempted": st.invariant_violations_attempted,
            "checkpoints": dict(st.checkpoints),
            "core_watered_count": st.core_watered_count,
            "core_harvest_count": st.core_harvest_count,
            "animals_fed_total": st.animals_fed_total,
        }

    return {
        "cell": {
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
            "mode": mode,
        },
        "outcome": {
            "final_cash": final_cash,
            "opp_final_cash": opp_final_cash,
            "win": win,
            "total_turns": total_turns,
            "match_duration_s": round(match_duration, 2),
            "min_cash_seen": min_cash_seen,
            "mean_latency_ms": round(float(np.mean(turn_latencies)), 2) if turn_latencies else 0.0,
            "max_latency_ms": round(float(np.max(turn_latencies)), 2) if turn_latencies else 0.0,
        },
        "animal_safety": animal_summary,
        "storage_safety": {
            "peak_shed_occupancy": peak_shed_occupancy,
            "rescue_events": rescue_telem.get("rescue_events", 0),
            "rescue_units_sold": rescue_telem.get("rescue_units_sold", 0),
        },
        "sw_telemetry": sw_telem,
    }


def run_paired_cell(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    """Execute matched pair: Control (OFF) vs Treatment (TREATMENT)."""
    # 1. Run Control
    ctrl_res = run_single_match(seed, opp_name, seat, mode="OFF")
    # 2. Run Treatment
    treat_res = run_single_match(seed, opp_name, seat, mode="TREATMENT")

    c_cash = ctrl_res["outcome"]["final_cash"]
    t_cash = treat_res["outcome"]["final_cash"]
    delta_cash = t_cash - c_cash

    return {
        "pair_id": f"s{seed}_{opp_name}_seat{seat}",
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "control_cash": c_cash,
        "treatment_cash": t_cash,
        "paired_delta": delta_cash,
        "control_win": ctrl_res["outcome"]["win"],
        "treatment_win": treat_res["outcome"]["win"],
        "control": ctrl_res,
        "treatment": treat_res,
    }


def main():
    print("================================================================================")
    print("PHASE SW-B2-GATE2: CONTROLLED LIVE TRANCHE-1 CANARY EXPERIMENT")
    print("================================================================================")
    os.makedirs(_OUT_DIR, exist_ok=True)

    print(f"Seeds: {CANARY_SEEDS}")
    print(f"Opponents: {CANONICAL_OPPONENTS}")
    print(f"Seats: {SEATS}")
    print(f"Total Matched Pairs: {len(CANARY_SEEDS) * len(CANONICAL_OPPONENTS) * len(SEATS)}")
    print(f"Output Directory: {_OUT_DIR}")
    print("================================================================================")

    tasks = []
    for s in CANARY_SEEDS:
        for opp in CANONICAL_OPPONENTS:
            for seat in SEATS:
                tasks.append((s, opp, seat))

    workers = min(7, mp.cpu_count())
    print(f"Starting multiprocessing pool with {workers} workers across {len(tasks)} pairs (40 matches)...\n")

    t0 = time.time()
    with mp.Pool(processes=workers) as pool:
        paired_results = pool.starmap(run_paired_cell, tasks)
    elapsed = time.time() - t0

    print(f"\nTournament completed in {elapsed:.1f}s ({elapsed / len(paired_results):.2f}s per pair avg).")

    # Aggregate Analysis
    c_cashes = [p["control_cash"] for p in paired_results]
    t_cashes = [p["treatment_cash"] for p in paired_results]
    deltas = [p["paired_delta"] for p in paired_results]

    c_wins = sum(1 for p in paired_results if p["control_win"])
    t_wins = sum(1 for p in paired_results if p["treatment_win"])
    pairwise_wins = sum(1 for d in deltas if d > 0)
    pairwise_losses = sum(1 for d in deltas if d < 0)
    pairwise_ties = sum(1 for d in deltas if d == 0)

    # 95% Confidence Interval for paired deltas (cluster by seed)
    mean_delta = float(np.mean(deltas))
    median_delta = float(np.median(deltas))
    std_delta = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else 0.0
    se_delta = std_delta / np.sqrt(len(deltas)) if len(deltas) > 1 else 0.0
    ci_95_low = mean_delta - 1.96 * se_delta
    ci_95_high = mean_delta + 1.96 * se_delta

    # Animal Safety in Treatment
    t_starvations = sum(p["treatment"]["animal_safety"]["confirmed_starvation_deaths"] for p in paired_results)
    t_escapes = sum(p["treatment"]["animal_safety"]["confirmed_escapes"] for p in paired_results)
    t_ambiguous = sum(p["treatment"]["animal_safety"]["ambiguous_disappearances"] for p in paired_results)
    t_losses = sum(p["treatment"]["animal_safety"]["total_animal_losses"] for p in paired_results)
    t_missed_feeds = sum(p["treatment"]["animal_safety"]["missed_feeding_days"] for p in paired_results)

    # Storage in Treatment
    t_rescues = sum(p["treatment"]["storage_safety"]["rescue_events"] for p in paired_results)
    t_rescue_units = sum(p["treatment"]["storage_safety"]["rescue_units_sold"] for p in paired_results)
    t_peak_sheds = [p["treatment"]["storage_safety"]["peak_shed_occupancy"] for p in paired_results]

    # Latency in Treatment
    t_mean_lats = [p["treatment"]["outcome"]["mean_latency_ms"] for p in paired_results]
    t_max_lats = [p["treatment"]["outcome"]["max_latency_ms"] for p in paired_results]

    # SW Execution summary in Treatment
    sw_approved_count = sum(1 for p in paired_results if p["treatment"]["sw_telemetry"].get("sw_purchase_approved"))
    sw_confirmed_count = sum(1 for p in paired_results if p["treatment"]["sw_telemetry"].get("sw_purchase_confirmed"))
    sw_revenues = [p["treatment"]["sw_telemetry"].get("sw_revenue_realized", 0.0) for p in paired_results]
    sw_costs_paid = [p["treatment"]["sw_telemetry"].get("sw_land_cost_paid", 0.0) for p in paired_results]
    sw_seed_cash = [p["treatment"]["sw_telemetry"].get("sw_seed_cost_realized", 0.0) for p in paired_results]
    sw_seed_opp = [p["treatment"]["sw_telemetry"].get("sw_seed_opportunity_cost", 0.0) for p in paired_results]

    # Per opponent breakdown
    opp_breakdown = {}
    for opp in CANONICAL_OPPONENTS:
        opp_pairs = [p for p in paired_results if p["opponent"] == opp]
        opp_deltas = [p["paired_delta"] for p in opp_pairs]
        opp_c_cash = [p["control_cash"] for p in opp_pairs]
        opp_t_cash = [p["treatment_cash"] for p in opp_pairs]
        opp_breakdown[opp] = {
            "pairs": len(opp_pairs),
            "control_mean_cash": round(float(np.mean(opp_c_cash)), 2),
            "treatment_mean_cash": round(float(np.mean(opp_t_cash)), 2),
            "mean_paired_gain": round(float(np.mean(opp_deltas)), 2),
            "median_paired_gain": round(float(np.median(opp_deltas)), 2),
            "wins": sum(1 for d in opp_deltas if d > 0),
            "losses": sum(1 for d in opp_deltas if d < 0),
        }

    # Summary dictionary
    summary = {
        "tournament": "Phase SW-B2-Gate2 LIVE Tranche-1 Canary",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_pairs_run": len(paired_results),
        "total_matches_run": len(paired_results) * 2,
        "elapsed_seconds": round(elapsed, 2),
        "economic_performance": {
            "control_mean_cash": round(float(np.mean(c_cashes)), 2),
            "control_median_cash": round(float(np.median(c_cashes)), 2),
            "treatment_mean_cash": round(float(np.mean(t_cashes)), 2),
            "treatment_median_cash": round(float(np.median(t_cashes)), 2),
            "mean_paired_gain": round(mean_delta, 2),
            "median_paired_gain": round(median_delta, 2),
            "std_paired_gain": round(std_delta, 2),
            "ci_95_pct": [round(ci_95_low, 2), round(ci_95_high, 2)],
            "pairwise_record": f"{pairwise_wins}W / {pairwise_losses}L / {pairwise_ties}T",
            "treatment_win_rate_vs_game": round(t_wins / len(paired_results) * 100, 2),
            "control_win_rate_vs_game": round(c_wins / len(paired_results) * 100, 2),
            "treatment_min_cash": round(float(np.min(t_cashes)), 2),
            "control_min_cash": round(float(np.min(c_cashes)), 2),
        },
        "sw_execution_telemetry": {
            "approved_purchases": sw_approved_count,
            "confirmed_purchases": sw_confirmed_count,
            "mean_realized_sw_revenue": round(float(np.mean(sw_revenues)), 2),
            "mean_land_cost_paid": round(float(np.mean(sw_costs_paid)), 2),
            "mean_seed_cash_cost": round(float(np.mean(sw_seed_cash)), 2),
            "mean_seed_opportunity_cost": round(float(np.mean(sw_seed_opp)), 2),
            "mean_net_sw_direct_profit": round(float(np.mean(sw_revenues) - np.mean(sw_costs_paid) - np.mean(sw_seed_cash)), 2),
        },
        "per_opponent_breakdown": opp_breakdown,
        "animal_safety_audit": {
            "treatment_confirmed_starvations": t_starvations,
            "treatment_confirmed_escapes": t_escapes,
            "treatment_total_losses": t_losses,
            "treatment_missed_feeding_days": t_missed_feeds,
            "status": "ZERO_STARVATIONS_VERIFIED" if t_losses == 0 else "SAFETY_BREACH",
        },
        "storage_safety_audit": {
            "treatment_total_rescues": t_rescues,
            "treatment_total_rescue_units": t_rescue_units,
            "treatment_peak_shed_occupancy_max": max(t_peak_sheds),
            "treatment_peak_shed_occupancy_mean": round(float(np.mean(t_peak_sheds)), 1),
            "status": "ZERO_OVERFLOWS_VERIFIED" if max(t_peak_sheds) <= 100 else "OVERFLOW_DETECTED",
        },
        "latency_audit": {
            "treatment_mean_latency_ms": round(float(np.mean(t_mean_lats)), 2),
            "treatment_max_latency_ms": round(float(np.max(t_max_lats)), 2),
            "status": "PASS" if max(t_max_lats) < 1000 else "LATENCY_SPIKE",
        },
    }

    # Save output artifacts
    with open(os.path.join(_OUT_DIR, "live_canary_20_pairs.json"), "w", encoding="utf-8") as f:
        json.dump(paired_results, f, indent=2)

    with open(os.path.join(_OUT_DIR, "live_canary_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    source_manifest = get_source_manifest()
    with open(os.path.join(_OUT_DIR, "source_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(source_manifest, f, indent=2)

    print("\nCanary Tournament Results:")
    print(f"  Control Mean Cash:   ${summary['economic_performance']['control_mean_cash']:,.2f}")
    print(f"  Treatment Mean Cash: ${summary['economic_performance']['treatment_mean_cash']:,.2f}")
    print(f"  Mean Paired Gain:    +${summary['economic_performance']['mean_paired_gain']:,.2f} (Median: +${summary['economic_performance']['median_paired_gain']:,.2f})")
    print(f"  95% CI:              [+${summary['economic_performance']['ci_95_pct'][0]:,.2f}, +${summary['economic_performance']['ci_95_pct'][1]:,.2f}]")
    print(f"  Pairwise Record:     {summary['economic_performance']['pairwise_record']}")
    print(f"  SW Unlocked:         {sw_confirmed_count} / {len(paired_results)}")
    print(f"  Mean Realized SW Rev:${summary['sw_execution_telemetry']['mean_realized_sw_revenue']:,.2f}")
    print(f"  Net Direct SW Profit:${summary['sw_execution_telemetry']['mean_net_sw_direct_profit']:,.2f}")
    print(f"  Animal Starvations:  {t_starvations} (Losses: {t_losses})")
    print(f"  Storage Rescues:     {t_rescues} (Units: {t_rescue_units})")
    print(f"  Max Shed Occupancy:  {max(t_peak_sheds)}/100")
    print(f"  Treatment Latency:   {summary['latency_audit']['treatment_mean_latency_ms']} ms avg, {summary['latency_audit']['treatment_max_latency_ms']} ms max")
    print(f"\nAll artifacts saved to {_OUT_DIR}")


if __name__ == "__main__":
    main()
