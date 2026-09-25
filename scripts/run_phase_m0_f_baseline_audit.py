"""Phase M0-F: Authoritative Baseline Animal Servicing Audit.

Runs historical baseline across seeds 96501–96510 x 5 opponents:
Instruments each animal/day lifecycle:
- species, day, production_day?
- fed?, cared?, yield before/after, pending care bank before/after
- wheat consumed, CARE actions used, FEED actions used
- max-held clipping, product collected, spot price
- classification of servicing actions into waste categories

Outputs under simulations/results/phase_m0_f_baseline_audit/:
- manifest.json
- animal_day_ledger.json
- service_action_breakdown.json
- care_bonus_realization.json
- feed_consumption.json
- clipping_analysis.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_f_baseline_audit")
os.makedirs(OUT_DIR, exist_ok=True)

AUDIT_SEEDS = list(range(96501, 96511))  # 96501–96510 (10 seeds)
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]

ANIMALS_SPEC = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}


def run_audit_match(seed: int, opp_name: str, seat: int = 0) -> Dict[str, Any]:
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
    from strategy.animal_service_economics import (
        is_production_day,
        get_future_production_days,
        reset_animal_service_telemetry,
        get_animal_service_telemetry,
    )

    # Invariants for baseline audit:
    # Historical baseline runs (ANIMAL_SERVICE_ECONOMICS_MODE = "SHADOW" so telemetry audits run without modifying actions)
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    config.set_midnight_storage_dump_mode("OFF")
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("SHADOW")

    reset_agent_state()
    reset_sw_tranche_controller()
    reset_animal_service_telemetry()

    animal_ledger: List[Dict[str, Any]] = []
    feed_actions_count = 0
    care_actions_count = 0

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    step_num = 0
    while not env.done:
        obs_pre = env.state[seat].observation
        day = step_num // 24
        hour = step_num % 24

        # Track animal states at hour 0 (start of day)
        if hour == 0 and hasattr(obs_pre, "private") and hasattr(obs_pre.private, "farms"):
            pass

        act = agent(obs_pre, env.configuration)

        # Count unit actions emitted
        for u in [act.get("farmer")] + act.get("hands", []):
            if u:
                op = u[0]
                if op == "FEED":
                    feed_actions_count += 1
                elif op == "CARE":
                    care_actions_count += 1

        try:
            opp_act = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_act = opp_agent(env.state[1 - seat].observation)

        actions = [act, opp_act] if seat == 0 else [opp_act, act]
        env.step(actions)
        step_num += 1

    final_reward = float(env.steps[-1][seat].reward or 0.0)
    opp_reward = float(env.steps[-1][1 - seat].reward or 0.0)
    telem = get_animal_service_telemetry()

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "final_cash": final_reward,
        "opp_cash": opp_reward,
        "feed_actions": feed_actions_count,
        "care_actions": care_actions_count,
        "telemetry": telem,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-F Baseline Servicing Audit")
    parser.add_argument("--workers", type=int, default=10, help="Number of worker processes")
    args = parser.parse_args()

    print("=== Phase M0-F Baseline Animal Servicing Audit ===")
    print(f"Seeds: {len(AUDIT_SEEDS)} seeds x {len(BENCHMARK_OPPONENTS)} opponents = {len(AUDIT_SEEDS) * len(BENCHMARK_OPPONENTS)} matches")

    tasks = [(s, opp) for s in AUDIT_SEEDS for opp in BENCHMARK_OPPONENTS]
    results = []
    start_time = time.time()
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(run_audit_match, s, opp): (s, opp) for s, opp in tasks}
        for fut in as_completed(future_map):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == len(tasks):
                print(f"  [{completed}/{len(tasks)}] matches completed ({time.time() - start_time:.1f}s)")

    # Aggregate telemetry across matches
    tot_evaluated = sum(r["telemetry"].get("animal_days_evaluated", 0) for r in results)
    tot_feed_base = sum(r["feed_actions"] for r in results)
    tot_care_base = sum(r["care_actions"] for r in results)
    tot_feed_skip = sum(r["telemetry"].get("feed_actions_skipped", 0) for r in results)
    tot_care_skip = sum(r["telemetry"].get("care_actions_skipped", 0) for r in results)

    feed_reasons = {}
    care_reasons = {}
    sp_totals = {sp: {"feed": 0, "care": 0, "feed_skip": 0, "care_skip": 0} for sp in ("COW", "SHEEP", "GOOSE")}
    sample_ledger = []

    for r in results:
        t = r["telemetry"]
        for k, v in t.get("reasons_feed_skipped", {}).items():
            feed_reasons[k] = feed_reasons.get(k, 0) + v
        for k, v in t.get("reasons_care_skipped", {}).items():
            care_reasons[k] = care_reasons.get(k, 0) + v
        for sp, stats in t.get("species_stats", {}).items():
            sp_totals[sp]["feed"] += stats.get("feed_baseline", 0)
            sp_totals[sp]["care"] += stats.get("care_baseline", 0)
            sp_totals[sp]["feed_skip"] += stats.get("feed_skipped", 0)
            sp_totals[sp]["care_skip"] += stats.get("care_skipped", 0)
        if len(sample_ledger) < 200:
            sample_ledger.extend(t.get("ledger", [])[:20])

    manifest = {
        "phase": "M0-F",
        "description": "Baseline Animal Servicing Audit across 50 matches (Seeds 96501-96510)",
        "matches_count": len(results),
        "total_animal_days_evaluated": tot_evaluated,
        "mean_final_cash": float(np.mean([r["final_cash"] for r in results])),
    }

    action_breakdown = {
        "total_feed_actions_emitted": tot_feed_base,
        "mean_feed_actions_per_match": tot_feed_base / len(results),
        "total_care_actions_emitted": tot_care_base,
        "mean_care_actions_per_match": tot_care_base / len(results),
        "species_breakdown": sp_totals,
        "care_skip_opportunities": care_reasons,
        "feed_skip_opportunities": feed_reasons,
    }

    care_bonus_realization = {
        "total_care_actions": tot_care_base,
        "estimated_redundant_or_clipped_care": tot_care_skip,
        "redundant_care_percentage": (tot_care_skip / tot_care_base * 100) if tot_care_base > 0 else 0,
        "reasons": care_reasons,
    }

    feed_consumption = {
        "total_feed_actions": tot_feed_base,
        "wheat_consumed_est": tot_feed_base,
        "potentially_safe_wheat_savings": tot_feed_skip,
        "potential_wheat_saving_percentage": (tot_feed_skip / tot_feed_base * 100) if tot_feed_base > 0 else 0,
        "reasons": feed_reasons,
    }

    clipping_analysis = {
        "reasons_care_wasted": care_reasons,
        "primary_waste_classes": [
            "CARE_CLIPS_MAX_HELD",
            "NO_FUTURE_PRODUCTION_EVENT",
            "UNFED_ANIMAL_CANNOT_BANK_CARE",
            "EXISTING_YIELD_AT_MAX_HELD",
        ],
    }

    # Write deliverables
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(OUT_DIR, "animal_day_ledger.json"), "w", encoding="utf-8") as f:
        json.dump(sample_ledger, f, indent=2)
    with open(os.path.join(OUT_DIR, "service_action_breakdown.json"), "w", encoding="utf-8") as f:
        json.dump(action_breakdown, f, indent=2)
    with open(os.path.join(OUT_DIR, "care_bonus_realization.json"), "w", encoding="utf-8") as f:
        json.dump(care_bonus_realization, f, indent=2)
    with open(os.path.join(OUT_DIR, "feed_consumption.json"), "w", encoding="utf-8") as f:
        json.dump(feed_consumption, f, indent=2)
    with open(os.path.join(OUT_DIR, "clipping_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(clipping_analysis, f, indent=2)

    print("\n=== Baseline Audit Results ===")
    print(f"Mean Final Cash: ${manifest['mean_final_cash']:.2f}")
    print(f"Total FEED actions: {tot_feed_base} ({tot_feed_base / len(results):.1f}/match)")
    print(f"Total CARE actions: {tot_care_base} ({tot_care_base / len(results):.1f}/match)")
    print(f"Potentially redundant CARE actions: {tot_care_skip} ({tot_care_skip / tot_care_base * 100:.1f}%)")
    print(f"Potentially safe FEED savings: {tot_feed_skip} wheat ({tot_feed_skip / tot_feed_base * 100:.1f}%)")
    print(f"Deliverables written to {OUT_DIR}")


if __name__ == "__main__":
    main()
