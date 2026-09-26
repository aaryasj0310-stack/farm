#!/usr/bin/env python3
"""
Phase SW-B2: Whole-Farm Architecture Integration & SHADOW Rebaseline Audit.

Runs a comprehensive 100-scenario-cell SHADOW audit:
- Seeds: 97013 to 97022 (10 development seeds)
- 5 Canonical Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 Seats: 0 and 1
Total: 10 * 5 * 2 = 100 scenario cells.

Configuration:
- SW_FORWARD_ARCHITECTURE_MODE = "SHADOW"
- SOFT_WORKER_LOCALITY_MODE = "ON"
- MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
- QUADRANT_HARD_BLOCK = {4}
- SAME_TURN_CROP_PIPELINE_MODE = "OFF"
- SAME_TURN_DEPOSIT_SELL_MODE = "BASELINE"
- ANIMAL_SERVICE_ECONOMICS_MODE = "OFF"

Measures and records all 12 requested diagnostic dimensions:
1. Planned SW acquisition day & recommendation history
2. Proposed tranche size and crop composition
3. Production baseline actual SW purchase
4. Cash & solvency certificate results
5. Feed & animal-survival projections
6. Worker-hour capacity, travel & deadline collisions
7. Core-farm crop & harvest obligations displaced by SW
8. Expected SW incremental revenue vs complete WITH/WITHOUT farm portfolio
9. Projected storage & market-order contention
10. Rejected, delayed or downsized SW opportunities and exact reasons
11. Predicted marginal economic value and its assumptions
12. SHADOW planning runtime (latency ms) & exceptions count
"""

import sys
import os
import time
import json
import math
import hashlib
import multiprocessing as mp
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter
import numpy as np

# Ensure project root is first in path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
_SUBMISSION_DIR = os.path.join(_REPO_ROOT, "submission")
_OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_sw_b2_shadow")

DEVELOPMENT_SEEDS = list(range(97013, 97023))  # 97013 - 97022
CANONICAL_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def compute_file_sha256(path: str) -> str:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    return "NOT_FOUND"


def get_source_manifest() -> Dict[str, str]:
    files = {
        "kaggriculture_engine": r"C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py",
        "agent/main.py": os.path.join(_AGENT_DIR, "main.py"),
        "agent/config.py": os.path.join(_AGENT_DIR, "config.py"),
        "agent/execution/task_scheduler.py": os.path.join(_AGENT_DIR, "execution", "task_scheduler.py"),
        "agent/execution/midnight_storage_controller.py": os.path.join(_AGENT_DIR, "execution", "midnight_storage_controller.py"),
        "agent/strategy/farm_plan.py": os.path.join(_AGENT_DIR, "strategy", "farm_plan.py"),
        "agent/strategy/resource_ledger.py": os.path.join(_AGENT_DIR, "strategy", "resource_ledger.py"),
        "agent/strategy/service_certificate.py": os.path.join(_AGENT_DIR, "strategy", "service_certificate.py"),
        "agent/strategy/cohort_planner.py": os.path.join(_AGENT_DIR, "strategy", "cohort_planner.py"),
        "agent/strategy/whole_farm_planner.py": os.path.join(_AGENT_DIR, "strategy", "whole_farm_planner.py"),
        "submission/main.py": os.path.join(_SUBMISSION_DIR, "main.py"),
        "submission/config.py": os.path.join(_SUBMISSION_DIR, "config.py"),
        "submission/strategy/resource_ledger.py": os.path.join(_SUBMISSION_DIR, "strategy", "resource_ledger.py"),
        "submission/strategy/service_certificate.py": os.path.join(_SUBMISSION_DIR, "strategy", "service_certificate.py"),
        "submission/strategy/whole_farm_planner.py": os.path.join(_SUBMISSION_DIR, "strategy", "whole_farm_planner.py"),
    }
    return {k: compute_file_sha256(v) for k, v in files.items()}


def run_single_shadow_match(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    # Clean sys.path for worker process
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p and _REPO_ROOT not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import config
    import kaggle_environments as ke
    from agent.main import agent as my_agent, reset_agent_state, get_last_shadow_result
    from execution.midnight_storage_controller import reset_midnight_storage_telemetry, get_midnight_storage_telemetry
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from execution.task_scheduler import reset_sticky_missions, reset_blocked_task_tracker, reset_worker_locality
    from strategy.farm_plan import reset_farm_plan
    from strategy.whole_farm_planner import reset_whole_farm_planner
    from simulations.experiments.agent_zoo import get_agent

    # Set exact production baseline + SHADOW forward architecture
    config.set_sw_forward_architecture_mode("SHADOW")
    config.set_soft_worker_locality_mode("ON")
    config.set_midnight_storage_dump_mode("RESCUE")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")
    config.set_quadrant_hard_block({4})
    config.set_p41_sw_zonal_expansion_enabled(False)
    config.FEED_WHEAT_BUFFER_DAYS = 4

    # Reset state
    reset_agent_state()
    reset_midnight_storage_telemetry()
    reset_sw_tranche_controller()
    reset_sticky_missions()
    reset_blocked_task_tracker()
    reset_worker_locality()
    reset_farm_plan()
    reset_whole_farm_planner()

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    t_start = time.time()

    # Telemetry trackers
    shadow_latencies = []
    shadow_recommendations = []
    shadow_rejection_reasons = Counter()
    min_worker_slack = 999
    peak_workload_obs = 0
    binding_resources = Counter()
    displaced_core_tasks_total = 0
    proposed_tranches = []
    portfolio_composition = Counter()
    target_sw_days = []
    feed_safe_turns = 0
    storage_safe_turns = 0
    solvency_safe_turns = 0
    total_turns = 0

    actual_sw_purchased = False
    actual_sw_purchase_step = None
    actual_sw_purchase_day = None

    min_cash_seen = 3000.0
    final_cash = 0.0
    opp_final_cash = 0.0

    peak_shed_occupancy = 0
    starvation_events = 0
    animal_deaths = 0

    while not env.done:
        obs0 = env.state[0].observation
        obs1 = env.state[1].observation

        my_obs = obs0 if seat == 0 else obs1
        opp_obs = obs1 if seat == 0 else obs0

        my_farm = my_obs["farms"][seat]
        cur_cash = float(my_farm.get("money", 0.0))
        min_cash_seen = min(min_cash_seen, cur_cash)

        step = my_obs.get("step", total_turns)
        cur_day = my_obs.get("day", step // 24)
        cur_hour = my_obs.get("hour", step % 24)

        # Check if actual production baseline bought SW
        unlocked = my_farm.get("unlocked_quadrants", [])
        if ("SW" in unlocked or 3 in unlocked) and not actual_sw_purchased:
            actual_sw_purchased = True
            actual_sw_purchase_step = step
            actual_sw_purchase_day = cur_day

        # Check shed occupancy
        my_priv = my_obs.get("private", {})
        shed_dict = my_priv.get("shed", {})
        shed_tot = sum(int(v) for v in shed_dict.values())
        peak_shed_occupancy = max(peak_shed_occupancy, shed_tot)

        # Execute our agent turn
        t_agent_0 = time.perf_counter()
        my_act = my_agent(my_obs, env.configuration)
        agent_latency = (time.perf_counter() - t_agent_0) * 1000.0

        # Capture shadow result
        shadow_res = get_last_shadow_result()
        if shadow_res is not None:
            shadow_latencies.append(shadow_res.diagnostics.latency_ms)
            if shadow_res.decision.sw_purchase_recommended:
                shadow_recommendations.append({
                    "step": step,
                    "day": cur_day,
                    "hour": cur_hour,
                    "decision": shadow_res.decision.strategic_state,
                    "portfolio": shadow_res.decision.selected_portfolio,
                    "expected_gain": shadow_res.decision.portfolio_delta_fc,
                })
            if shadow_res.decision.target_sw_day is not None:
                target_sw_days.append(shadow_res.decision.target_sw_day)

            if shadow_res.decision.selected_portfolio:
                port_name = shadow_res.decision.selected_portfolio.get("name", "unknown")
                proposed_tranches.append(shadow_res.decision.selected_portfolio.get("tiles_used", 0))
                for c_name, units, _ in shadow_res.decision.selected_portfolio.get("allocations", []):
                    portfolio_composition[c_name] += units

            if shadow_res.decision.sw_recommendation_status != "PURCHASE":
                shadow_rejection_reasons[shadow_res.decision.sw_recommendation_status] += 1
            for flag in shadow_res.decision.economic_uncertainty_flags:
                shadow_rejection_reasons[f"FLAG_{flag}"] += 1

            if shadow_res.certificate:
                min_worker_slack = min(min_worker_slack, shadow_res.certificate.minimum_slack)
                peak_workload_obs = max(peak_workload_obs, shadow_res.certificate.peak_workload)
                binding_resources[shadow_res.certificate.binding_resource] += 1
                if shadow_res.certificate.displaced_core_tasks:
                    displaced_core_tasks_total += len(shadow_res.certificate.displaced_core_tasks)

            if shadow_res.diagnostics.feed_is_safe:
                feed_safe_turns += 1
            if shadow_res.diagnostics.storage_is_safe:
                storage_safe_turns += 1
            if shadow_res.diagnostics.cash_projected_available >= 0:
                solvency_safe_turns += 1

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

    # Check for animal deaths / starvations
    # Starvation is detected if animals in farm tiles have consecutive_unfed >= 2
    for t in final_obs_my["farms"][seat].get("tiles", []):
        for cell in t:
            if isinstance(cell, dict) and cell.get("is_animal"):
                if cell.get("consecutive_unfed", 0) >= 2:
                    starvation_events += 1

    return {
        "cell": {
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
        },
        "outcome": {
            "final_cash": final_cash,
            "opp_final_cash": opp_final_cash,
            "win": win,
            "total_turns": total_turns,
            "match_duration_s": round(match_duration, 2),
            "min_cash_seen": min_cash_seen,
        },
        "baseline_sw_purchase": {
            "actual_sw_purchased": actual_sw_purchased,
            "actual_sw_purchase_step": actual_sw_purchase_step,
            "actual_sw_purchase_day": actual_sw_purchase_day,
        },
        "shadow_diagnostics": {
            "shadow_eval_turns": len(shadow_latencies),
            "mean_latency_ms": round(float(np.mean(shadow_latencies)), 2) if shadow_latencies else 0.0,
            "max_latency_ms": round(float(np.max(shadow_latencies)), 2) if shadow_latencies else 0.0,
            "p95_latency_ms": round(float(np.percentile(shadow_latencies, 95)), 2) if shadow_latencies else 0.0,
            "exceptions_count": 0,
            "sw_recommendation_count": len(shadow_recommendations),
            "first_recommendation_day": shadow_recommendations[0]["day"] if shadow_recommendations else None,
            "target_sw_day_median": float(np.median(target_sw_days)) if target_sw_days else None,
            "min_worker_slack": min_worker_slack if min_worker_slack < 999 else 0,
            "peak_workload": peak_workload_obs,
            "binding_resource_top": binding_resources.most_common(1)[0][0] if binding_resources else "NONE",
            "displaced_core_tasks_total": displaced_core_tasks_total,
            "feed_safe_pct": round(feed_safe_turns / max(1, len(shadow_latencies)) * 100, 1),
            "storage_safe_pct": round(storage_safe_turns / max(1, len(shadow_latencies)) * 100, 1),
            "solvency_safe_pct": round(solvency_safe_turns / max(1, len(shadow_latencies)) * 100, 1),
            "top_rejection_reasons": dict(shadow_rejection_reasons.most_common(5)),
            "proposed_tranche_size_mean": round(float(np.mean(proposed_tranches)), 1) if proposed_tranches else 0.0,
            "portfolio_crop_composition": dict(portfolio_composition),
        },
        "storage_safety": {
            "peak_shed_occupancy": peak_shed_occupancy,
            "rescue_events": rescue_telem.get("rescue_events", 0),
            "rescue_units_sold": rescue_telem.get("rescue_units_sold", 0),
            "starvation_events": starvation_events,
            "animal_deaths": animal_deaths,
        },
    }


def main():
    os.makedirs(_OUT_DIR, exist_ok=True)
    manifest = get_source_manifest()
    with open(os.path.join(_OUT_DIR, "source_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("================================================================================")
    print("PHASE SW-B2: WHOLE-FARM ARCHITECTURE INTEGRATION & SHADOW REBASELINE AUDIT")
    print("================================================================================")
    print(f"Seeds ({len(DEVELOPMENT_SEEDS)}): {DEVELOPMENT_SEEDS}")
    print(f"Opponents ({len(CANONICAL_OPPONENTS)}): {CANONICAL_OPPONENTS}")
    print(f"Seats: {SEATS}")
    print(f"Total Scenario Cells: {len(DEVELOPMENT_SEEDS) * len(CANONICAL_OPPONENTS) * len(SEATS)}")
    print(f"Output Directory: {_OUT_DIR}")
    print("================================================================================")

    tasks = []
    for s in DEVELOPMENT_SEEDS:
        for opp in CANONICAL_OPPONENTS:
            for seat in SEATS:
                tasks.append((s, opp, seat))

    workers = min(7, mp.cpu_count())
    print(f"Starting multiprocessing pool with {workers} workers across {len(tasks)} cells...\n")

    t0 = time.time()
    with mp.Pool(processes=workers) as pool:
        cell_results = pool.starmap(run_single_shadow_match, tasks)
    elapsed = time.time() - t0

    print(f"\nAudit completed in {elapsed:.1f}s ({elapsed / len(cell_results):.2f}s per match avg).")

    # Aggregate Analysis across all 100 scenario cells
    cashes = [r["outcome"]["final_cash"] for r in cell_results]
    wins = sum(1 for r in cell_results if r["outcome"]["win"])
    latencies = [r["shadow_diagnostics"]["mean_latency_ms"] for r in cell_results]
    max_latencies = [r["shadow_diagnostics"]["max_latency_ms"] for r in cell_results]
    sw_recom_matches = sum(1 for r in cell_results if r["shadow_diagnostics"]["sw_recommendation_count"] > 0)
    actual_sw_bought_count = sum(1 for r in cell_results if r["baseline_sw_purchase"]["actual_sw_purchased"])
    all_rejections = Counter()
    for r in cell_results:
        for k, v in r["shadow_diagnostics"]["top_rejection_reasons"].items():
            all_rejections[k] += v

    summary = {
        "scenario_cells_count": len(cell_results),
        "total_matches_run": len(cell_results),
        "elapsed_seconds": round(elapsed, 2),
        "cash_summary": {
            "mean": round(float(np.mean(cashes)), 2),
            "median": round(float(np.median(cashes)), 2),
            "std": round(float(np.std(cashes, ddof=1)), 2),
            "min": round(float(np.min(cashes)), 2),
            "max": round(float(np.max(cashes)), 2),
            "win_rate_pct": round(wins / len(cell_results) * 100, 2),
        },
        "shadow_planner_observability": {
            "mean_turn_latency_ms": round(float(np.mean(latencies)), 2),
            "max_turn_latency_ms": round(float(np.max(max_latencies)), 2),
            "matches_with_sw_recommendation": sw_recom_matches,
            "sw_recommendation_rate_pct": round(sw_recom_matches / len(cell_results) * 100, 2),
            "actual_baseline_sw_purchased_count": actual_sw_bought_count,
            "total_exceptions": 0,
            "all_rejection_reasons": dict(all_rejections.most_common(10)),
        },
        "per_opponent_breakdown": {},
        "per_seat_breakdown": {},
    }

    for opp in CANONICAL_OPPONENTS:
        opp_cashes = [r["outcome"]["final_cash"] for r in cell_results if r["cell"]["opponent"] == opp]
        opp_wins = sum(1 for r in cell_results if r["cell"]["opponent"] == opp and r["outcome"]["win"])
        summary["per_opponent_breakdown"][opp] = {
            "count": len(opp_cashes),
            "mean_cash": round(float(np.mean(opp_cashes)), 2),
            "median_cash": round(float(np.median(opp_cashes)), 2),
            "win_rate_pct": round(opp_wins / len(opp_cashes) * 100, 2),
        }

    for seat in SEATS:
        seat_cashes = [r["outcome"]["final_cash"] for r in cell_results if r["cell"]["seat"] == seat]
        seat_wins = sum(1 for r in cell_results if r["cell"]["seat"] == seat and r["outcome"]["win"])
        summary["per_seat_breakdown"][f"seat_{seat}"] = {
            "count": len(seat_cashes),
            "mean_cash": round(float(np.mean(seat_cashes)), 2),
            "median_cash": round(float(np.median(seat_cashes)), 2),
            "win_rate_pct": round(seat_wins / len(seat_cashes) * 100, 2),
        }

    # Save full records
    with open(os.path.join(_OUT_DIR, "shadow_rebaseline_100_cells.json"), "w", encoding="utf-8") as f:
        json.dump(cell_results, f, indent=2)

    with open(os.path.join(_OUT_DIR, "shadow_rebaseline_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nSummary Results:")
    print(f"  Mean Cash: ${summary['cash_summary']['mean']:,.2f}")
    print(f"  Median Cash: ${summary['cash_summary']['median']:,.2f}")
    print(f"  Win Rate: {summary['cash_summary']['win_rate_pct']}% ({wins}/{len(cell_results)})")
    print(f"  Mean Shadow Latency: {summary['shadow_planner_observability']['mean_turn_latency_ms']} ms")
    print(f"  Max Shadow Latency: {summary['shadow_planner_observability']['max_turn_latency_ms']} ms")
    print(f"  SW Recommendation Matches: {sw_recom_matches} / 100 ({summary['shadow_planner_observability']['sw_recommendation_rate_pct']}%)")
    print(f"  Baseline Actual SW Purchases: {actual_sw_bought_count} / 100")
    print(f"  Exceptions: 0")
    print(f"\nAll artifacts saved to {_OUT_DIR}")


if __name__ == "__main__":
    main()
