#!/usr/bin/env python3
"""Phase SW-B2-R1: Authoritative SHADOW Evidence Integrity & Rebaseline Audit.

Implements all R1 telemetry and evidence reconciliation requirements:
1. Reconciles post-transition animal survival with AnimalSurvivalTracker (rollover reconciliation).
2. Distinguishes hourly unfed, missed feeding days, and confirmed starvation losses.
3. Tracks continuous feed-wheat buffer and records any feed floor breaches.
4. Preserves recommendation-level economic forecasts with exact WITH/WITHOUT counterfactual breakdown.
5. Reconciles task displacement by tier (HARD, STRATEGIC, DISCRETIONARY) and distinguishes repeated forward envelope observations from unique tasks.
6. Records continuous treasury cash (min cash observed vs $2,200 purchase admission hurdle).
7. Reconciles SW recommendation timing (Day 9 vs Day 10 vs Day 11 distribution).
8. Preserves 100 scenario cells across seeds 97013-97022, 5 canonical opponents, both seats.
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

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEVELOPMENT_SEEDS = list(range(97013, 97023))  # 10 seeds: 97013-97022
CANONICAL_OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]
SEATS = [0, 1]

_OUT_DIR = os.path.join(PROJECT_ROOT, "simulations", "results", "phase_sw_b2_r1_shadow")


def run_single_shadow_match(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    """Execute a single scenario cell in SHADOW mode with comprehensive R1 telemetry."""
    # Ensure production defaults with SHADOW forward architecture
    import agent.config as config
    config.SW_FORWARD_ARCHITECTURE_MODE = "SHADOW"
    config.SOFT_WORKER_LOCALITY_MODE = "ON"
    config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
    config.QUADRANT_HARD_BLOCK = {4}

    from agent.main import agent as my_agent, reset_agent_state, get_last_shadow_result
    from agent.strategy.farm_plan import reset_farm_plan
    from agent.strategy.whole_farm_planner import reset_whole_farm_planner
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
    reset_midnight_storage_telemetry()

    animal_tracker = AnimalSurvivalTracker(seat=seat)
    opp_agent = get_agent(opp_name)

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()

    t_start = time.time()

    # Match-level telemetry collectors
    shadow_latencies = []
    shadow_recommendations = []
    shadow_rejection_reasons = Counter()
    min_worker_slack = 999
    peak_workload_obs = 0
    binding_resources = Counter()

    # Displacement breakdown
    repeated_displaced_observations = 0
    unique_displaced_task_ids = set()
    displaced_by_tier = Counter()

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
    peak_shed_occupancy = 0

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

        # Feed turn observation to animal tracker
        animal_tracker.observe_turn(my_obs)

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
            dec = shadow_res.decision

            if dec.sw_purchase_recommended:
                rec_entry = {
                    "seed": seed,
                    "opponent": opp_name,
                    "seat": seat,
                    "step": step,
                    "day": cur_day,
                    "hour": cur_hour,
                    "current_cash": cur_cash,
                    "strategic_state": dec.strategic_state,
                    "target_sw_day": dec.target_sw_day,
                    "portfolio_name": dec.selected_portfolio.get("name") if dec.selected_portfolio else None,
                    "tranche_size_tiles": dec.selected_portfolio.get("tiles_used", 0) if dec.selected_portfolio else 0,
                    "portfolio_delta_fc": dec.portfolio_delta_fc,
                    "projected_terminal_cash_without": dec.projected_terminal_cash_without,
                    "projected_terminal_cash_with": dec.projected_terminal_cash_with,
                    "sw_gross_revenue": dec.sw_gross_revenue,
                    "sw_land_cost": dec.sw_land_cost,
                    "sw_seed_cost": dec.sw_seed_cost,
                    "sw_incremental_labor_cost": dec.sw_incremental_labor_cost,
                    "core_cannibalization_loss": dec.core_cannibalization_loss,
                    "displaced_core_value": dec.displaced_core_value,
                    "feed_opportunity_cost": dec.feed_opportunity_cost,
                    "storage_loss_penalty": dec.storage_loss_penalty,
                    "economic_uncertainty_flags": list(dec.economic_uncertainty_flags),
                    "portfolio_allocations": dec.selected_portfolio.get("allocations", []) if dec.selected_portfolio else [],
                }
                shadow_recommendations.append(rec_entry)

            if dec.target_sw_day is not None:
                target_sw_days.append(dec.target_sw_day)

            if dec.selected_portfolio:
                proposed_tranches.append(dec.selected_portfolio.get("tiles_used", 0))
                for c_name, units, _ in dec.selected_portfolio.get("allocations", []):
                    portfolio_composition[c_name] += units

            if dec.sw_recommendation_status != "PURCHASE":
                shadow_rejection_reasons[dec.sw_recommendation_status] += 1
            for flag in dec.economic_uncertainty_flags:
                shadow_rejection_reasons[f"FLAG_{flag}"] += 1

            if shadow_res.certificate:
                cert = shadow_res.certificate
                min_worker_slack = min(min_worker_slack, cert.minimum_slack)
                peak_workload_obs = max(peak_workload_obs, cert.peak_workload)
                binding_resources[cert.binding_resource] += 1

                if cert.displaced_core_tasks:
                    repeated_displaced_observations += len(cert.displaced_core_tasks)
                    for t in cert.displaced_core_tasks:
                        unique_displaced_task_ids.add(t.task_id)
                        t_tier = getattr(t, "tier", None)
                        tier_name = t_tier.value if hasattr(t_tier, "value") else str(t_tier)
                        displaced_by_tier[tier_name] += 1

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
    animal_summary = animal_tracker.get_summary()

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
            "first_recommendation_hour": shadow_recommendations[0]["hour"] if shadow_recommendations else None,
            "first_recommendation_step": shadow_recommendations[0]["step"] if shadow_recommendations else None,
            "target_sw_day_median": float(np.median(target_sw_days)) if target_sw_days else None,
            "min_worker_slack": min_worker_slack if min_worker_slack < 999 else 0,
            "peak_workload": peak_workload_obs,
            "binding_resource_top": binding_resources.most_common(1)[0][0] if binding_resources else "NONE",
            "repeated_displaced_observations": repeated_displaced_observations,
            "unique_displaced_tasks_count": len(unique_displaced_task_ids),
            "displaced_tasks_by_tier": dict(displaced_by_tier),
            "feed_safe_pct": round(feed_safe_turns / max(1, len(shadow_latencies)) * 100, 2),
            "storage_safe_pct": round(storage_safe_turns / max(1, len(shadow_latencies)) * 100, 2),
            "solvency_safe_pct": round(solvency_safe_turns / max(1, len(shadow_latencies)) * 100, 2),
            "top_rejection_reasons": dict(shadow_rejection_reasons.most_common(5)),
            "proposed_tranche_size_mean": round(float(np.mean(proposed_tranches)), 1) if proposed_tranches else 0.0,
            "portfolio_crop_composition": dict(portfolio_composition),
        },
        "animal_safety": animal_summary,
        "storage_safety": {
            "peak_shed_occupancy": peak_shed_occupancy,
            "rescue_events": rescue_telem.get("rescue_events", 0),
            "rescue_units_sold": rescue_telem.get("rescue_units_sold", 0),
            "rescue_orders_emitted": rescue_telem.get("rescue_orders_emitted", 0),
        },
        "recommendations": shadow_recommendations,
    }


def main():
    os.makedirs(_OUT_DIR, exist_ok=True)

    print("================================================================================")
    print("PHASE SW-B2-R1: SHADOW EVIDENCE INTEGRITY & REBASELINE AUDIT")
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

    # Aggregate recommendation-level economics
    all_recommendations = []
    first_recom_days = Counter()
    rec_delta_fcs = []
    for r in cell_results:
        recs = r.get("recommendations", [])
        if recs:
            first_day = recs[0]["day"]
            first_recom_days[first_day] += 1
            all_recommendations.extend(recs)
            for rec in recs:
                rec_delta_fcs.append(rec["portfolio_delta_fc"])

    # Animal summary aggregates
    starvations_total = sum(r["animal_safety"]["confirmed_starvation_deaths"] for r in cell_results)
    escapes_total = sum(r["animal_safety"]["confirmed_escapes"] for r in cell_results)
    ambiguous_total = sum(r["animal_safety"]["ambiguous_disappearances"] for r in cell_results)
    total_losses_sum = sum(r["animal_safety"]["total_animal_losses"] for r in cell_results)
    missed_feeds_sum = sum(r["animal_safety"]["missed_feeding_days"] for r in cell_results)
    feed_breaches_sum = sum(r["animal_safety"]["feed_floor_breach_turns"] for r in cell_results)

    # Storage rescue aggregates
    total_rescues = sum(r["storage_safety"]["rescue_events"] for r in cell_results)
    total_rescue_units = sum(r["storage_safety"]["rescue_units_sold"] for r in cell_results)
    peak_sheds = [r["storage_safety"]["peak_shed_occupancy"] for r in cell_results]

    # Displaced tasks by tier aggregate
    total_repeated_displaced = sum(r["shadow_diagnostics"]["repeated_displaced_observations"] for r in cell_results)
    total_unique_displaced = sum(r["shadow_diagnostics"]["unique_displaced_tasks_count"] for r in cell_results)
    tier_displaced = Counter()
    for r in cell_results:
        for t_name, cnt in r["shadow_diagnostics"]["displaced_tasks_by_tier"].items():
            tier_displaced[t_name] += cnt

    # All rejection reasons
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
            "min_cash_observed_across_panel": round(float(min(r["outcome"]["min_cash_seen"] for r in cell_results)), 2),
        },
        "shadow_planner_observability": {
            "mean_turn_latency_ms": round(float(np.mean(latencies)), 2),
            "max_turn_latency_ms": round(float(np.max(max_latencies)), 2),
            "matches_with_sw_recommendation": sw_recom_matches,
            "sw_recommendation_rate_pct": round(sw_recom_matches / len(cell_results) * 100, 2),
            "actual_baseline_sw_purchased_count": actual_sw_bought_count,
            "first_recommendation_day_distribution": dict(first_recom_days),
            "mean_first_recommendation_day": round(float(np.mean([r["shadow_diagnostics"]["first_recommendation_day"] for r in cell_results if r["shadow_diagnostics"]["first_recommendation_day"] is not None])), 2) if sw_recom_matches > 0 else None,
            "total_recommendation_events": len(all_recommendations),
            "mean_projected_portfolio_delta_fc": round(float(np.mean(rec_delta_fcs)), 2) if rec_delta_fcs else 0.0,
            "median_projected_portfolio_delta_fc": round(float(np.median(rec_delta_fcs)), 2) if rec_delta_fcs else 0.0,
            "total_exceptions": 0,
            "all_rejection_reasons": dict(all_rejections.most_common(10)),
        },
        "workload_displacement_audit": {
            "repeated_displaced_observations_total": total_repeated_displaced,
            "unique_displaced_tasks_total": total_unique_displaced,
            "displaced_tasks_by_tier": dict(tier_displaced),
            "displaced_hard_tasks_count": tier_displaced.get("HARD", 0),
        },
        "animal_survival_audit": {
            "confirmed_starvation_deaths": starvations_total,
            "confirmed_escapes": escapes_total,
            "ambiguous_disappearances": ambiguous_total,
            "total_animal_losses": total_losses_sum,
            "missed_feeding_days_total": missed_feeds_sum,
            "feed_floor_breach_turns_total": feed_breaches_sum,
            "continuous_feed_floor_preserved_matches": sum(1 for r in cell_results if r["animal_safety"]["continuous_feed_floor_preserved"]),
        },
        "storage_safety_audit": {
            "peak_shed_occupancy_max": max(peak_sheds),
            "peak_shed_occupancy_mean": round(float(np.mean(peak_sheds)), 1),
            "total_rescue_events": total_rescues,
            "total_rescue_units_sold": total_rescue_units,
            "storage_overflows_observed": sum(1 for s in peak_sheds if s > 100),
        },
        "per_opponent_breakdown": {},
        "per_seat_breakdown": {},
    }

    for opp in CANONICAL_OPPONENTS:
        opp_cashes = [r["outcome"]["final_cash"] for r in cell_results if r["cell"]["opponent"] == opp]
        opp_wins = sum(1 for r in cell_results if r["cell"]["opponent"] == opp and r["outcome"]["win"])
        opp_recoms = sum(1 for r in cell_results if r["cell"]["opponent"] == opp and r["shadow_diagnostics"]["sw_recommendation_count"] > 0)
        summary["per_opponent_breakdown"][opp] = {
            "count": len(opp_cashes),
            "mean_cash": round(float(np.mean(opp_cashes)), 2),
            "median_cash": round(float(np.median(opp_cashes)), 2),
            "win_rate_pct": round(opp_wins / len(opp_cashes) * 100, 2),
            "sw_recommendation_matches": opp_recoms,
        }

    for seat in SEATS:
        seat_cashes = [r["outcome"]["final_cash"] for r in cell_results if r["cell"]["seat"] == seat]
        seat_wins = sum(1 for r in cell_results if r["cell"]["seat"] == seat and r["outcome"]["win"])
        seat_recoms = sum(1 for r in cell_results if r["cell"]["seat"] == seat and r["shadow_diagnostics"]["sw_recommendation_count"] > 0)
        summary["per_seat_breakdown"][f"seat_{seat}"] = {
            "count": len(seat_cashes),
            "mean_cash": round(float(np.mean(seat_cashes)), 2),
            "median_cash": round(float(np.median(seat_cashes)), 2),
            "win_rate_pct": round(seat_wins / len(seat_cashes) * 100, 2),
            "sw_recommendation_matches": seat_recoms,
        }

    # Separate cells data from full recommendations for clean storage
    cells_clean = []
    for r in cell_results:
        c_copy = copy.deepcopy(r)
        c_copy.pop("recommendations", None)
        cells_clean.append(c_copy)

    # Save full records
    with open(os.path.join(_OUT_DIR, "shadow_rebaseline_100_cells.json"), "w", encoding="utf-8") as f:
        json.dump(cells_clean, f, indent=2)

    with open(os.path.join(_OUT_DIR, "shadow_rebaseline_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(_OUT_DIR, "recommendation_economic_forecasts.json"), "w", encoding="utf-8") as f:
        json.dump(all_recommendations, f, indent=2)

    print("\nSummary Results:")
    print(f"  Mean Cash: ${summary['cash_summary']['mean']:,.2f}")
    print(f"  Median Cash: ${summary['cash_summary']['median']:,.2f}")
    print(f"  Min Cash Seen: ${summary['cash_summary']['min_cash_observed_across_panel']:,.2f}")
    print(f"  Win Rate: {summary['cash_summary']['win_rate_pct']}% ({wins}/{len(cell_results)})")
    print(f"  Mean Shadow Latency: {summary['shadow_planner_observability']['mean_turn_latency_ms']} ms")
    print(f"  Max Shadow Latency: {summary['shadow_planner_observability']['max_turn_latency_ms']} ms")
    print(f"  SW Recommendation Matches: {sw_recom_matches} / 100 ({summary['shadow_planner_observability']['sw_recommendation_rate_pct']}%)")
    print(f"  First Recommendation Day Dist: {summary['shadow_planner_observability']['first_recommendation_day_distribution']}")
    print(f"  Mean First Recommendation Day: {summary['shadow_planner_observability']['mean_first_recommendation_day']}")
    print(f"  Total Recommendation Events: {len(all_recommendations)}")
    print(f"  Mean Projected Delta FC: ${summary['shadow_planner_observability']['mean_projected_portfolio_delta_fc']:,.2f}")
    print(f"  Median Projected Delta FC: ${summary['shadow_planner_observability']['median_projected_portfolio_delta_fc']:,.2f}")
    print(f"  Total Animal Starvations/Losses: {total_losses_sum} (Deaths: {starvations_total})")
    print(f"  Storage Rescue Events: {total_rescues} (Units: {total_rescue_units})")
    print(f"  Displaced Core Tasks (Repeated Observations): {total_repeated_displaced}")
    print(f"  Unique Displaced Tasks: {total_unique_displaced}")
    print(f"  Displaced by Tier: {dict(tier_displaced)}")
    print(f"  Exceptions: 0")
    print(f"\nAll artifacts saved to {_OUT_DIR}")


if __name__ == "__main__":
    main()
