"""Phase M0-L-A Pilot: Instrumentation Parity & Side-Effect Validation.

Runs 20 matches (seeds 97013–97014 × 5 benchmark opponents × 2 seats) in:
1. Pure uninstrumented production baseline.
2. Instrumented baseline with CensusSession active.

Verifies:
- Emitted agent actions are bit-for-bit identical across all 720 steps of all 20 matches.
- Final cash is 100% identical.
- Opponent final cash is 100% identical.
- Safety metrics (unfed days, animal escapes) are 100% identical.
- Zero gameplay side effects.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_l_a_pilot")
os.makedirs(OUT_DIR, exist_ok=True)

PILOT_SEEDS = [97013, 97014]
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]


def run_single_pilot_match(seed: int, opp_name: str, seat: int, instrumented: bool) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
    from agent.main import agent, reset_agent_state
    import config
    from execution.midnight_storage_controller import reset_midnight_storage_telemetry
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent
    from simulations.census.engine_instrumentation import CensusSession

    # Frozen production configuration
    config.set_midnight_storage_dump_mode("RESCUE")
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")

    reset_agent_state()
    reset_midnight_storage_telemetry()
    reset_sw_tranche_controller()

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    emitted_actions: List[Dict[str, Any]] = []
    max_consecutive_unfed = 0
    escapes_count = 0

    session = CensusSession(seat) if instrumented else None
    if session:
        session.install_hooks(env)

    try:
        while not env.done:
            obs_pre = env.state[seat].observation
            if session:
                session.attach_env_state(env.state)
                # Capture tile census at hour 0 of each day
                if obs_pre.hour == 0 and hasattr(obs_pre, "farms") and len(obs_pre.farms) > seat:
                    session.capture_tile_census(obs_pre.farms[seat])

            farm_pre = obs_pre.farms[seat]
            for row in farm_pre.tiles:
                for tile in row:
                    if isinstance(tile, dict) and "animal" in tile:
                        unfed = tile.get("consecutive_unfed", 0)
                        if unfed > max_consecutive_unfed:
                            max_consecutive_unfed = unfed
                        if unfed >= 2:
                            escapes_count += 1

            action = agent(obs_pre, env.configuration)
            try:
                opp_action = opp_agent(env.state[1 - seat].observation, env.configuration)
            except TypeError:
                opp_action = opp_agent(env.state[1 - seat].observation)

            emitted_actions.append(copy.deepcopy(action))

            actions = [action, opp_action] if seat == 0 else [opp_action, action]
            env.step(actions)
    finally:
        if session:
            session.remove_hooks()

    final_cash = float(env.state[seat].observation.farms[seat].money)
    opp_final_cash = float(env.state[1 - seat].observation.farms[1 - seat].money)

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "instrumented": instrumented,
        "final_cash": final_cash,
        "opp_final_cash": opp_final_cash,
        "max_consecutive_unfed": max_consecutive_unfed,
        "escapes_count": escapes_count,
        "emitted_actions": emitted_actions,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-L-A Pilot Parity Validation")
    parser.add_argument("--workers", type=int, default=8, help="Parallel worker processes")
    args = parser.parse_args()

    cells = []
    for s in PILOT_SEEDS:
        for opp in BENCHMARK_OPPONENTS:
            for seat in SEATS:
                cells.append((s, opp, seat))

    total_cells = len(cells)
    print(f"=== Starting Phase M0-L-A Instrumentation Pilot Parity Validation ===")
    print(f"Cells: {total_cells} (20 pairs = 40 matches)")
    print(f"Workers: {args.workers}")

    tasks = []
    for s, opp, seat in cells:
        tasks.append((s, opp, seat, False))  # Uninstrumented
        tasks.append((s, opp, seat, True))   # Instrumented

    results: Dict[Tuple[int, str, int, bool], Dict[str, Any]] = {}
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_single_pilot_match, s, opp, seat, inst): (s, opp, seat, inst)
            for (s, opp, seat, inst) in tasks
        }
        for fut in as_completed(futures):
            res = fut.result()
            key = (res["seed"], res["opponent"], res["seat"], res["instrumented"])
            results[key] = res

    elapsed = time.time() - t0
    print(f"All 40 matches finished in {elapsed:.2f}s.")

    # Parity verification
    all_cash_match = True
    all_opp_cash_match = True
    all_safety_match = True
    all_actions_match = True
    mismatches = []

    for s, opp, seat in cells:
        uninst = results[(s, opp, seat, False)]
        inst = results[(s, opp, seat, True)]

        cash_ok = (uninst["final_cash"] == inst["final_cash"])
        opp_cash_ok = (uninst["opp_final_cash"] == inst["opp_final_cash"])
        safety_ok = (
            uninst["max_consecutive_unfed"] == inst["max_consecutive_unfed"] and
            uninst["escapes_count"] == inst["escapes_count"]
        )

        # Check action parity step by step
        actions_ok = (len(uninst["emitted_actions"]) == len(inst["emitted_actions"]))
        if actions_ok:
            for step_idx, (a_un, a_in) in enumerate(zip(uninst["emitted_actions"], inst["emitted_actions"])):
                if a_un != a_in:
                    actions_ok = False
                    mismatches.append(f"Action mismatch at step {step_idx} in cell {s}_{opp}_{seat}")
                    break
        else:
            mismatches.append(f"Step count mismatch in cell {s}_{opp}_{seat}")

        if not cash_ok:
            all_cash_match = False
            mismatches.append(f"Cash mismatch in cell {s}_{opp}_{seat}: {uninst['final_cash']} vs {inst['final_cash']}")
        if not opp_cash_ok:
            all_opp_cash_match = False
            mismatches.append(f"Opponent cash mismatch in cell {s}_{opp}_{seat}")
        if not safety_ok:
            all_safety_match = False
            mismatches.append(f"Safety mismatch in cell {s}_{opp}_{seat}")
        if not actions_ok:
            all_actions_match = False

    parity_passed = all_cash_match and all_opp_cash_match and all_safety_match and all_actions_match

    summary = {
        "total_cells": total_cells,
        "parity_passed": parity_passed,
        "cash_parity": all_cash_match,
        "opp_cash_parity": all_opp_cash_match,
        "safety_parity": all_safety_match,
        "actions_parity": all_actions_match,
        "total_steps_evaluated": total_cells * 720,
        "mismatches": mismatches,
        "duration_seconds": elapsed,
    }

    out_path = os.path.join(OUT_DIR, "pilot_parity_results.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n--- Pilot Parity Results ---")
    print(f"Parity Passed: {parity_passed}")
    print(f"Cash Parity: {all_cash_match}")
    print(f"Opponent Cash Parity: {all_opp_cash_match}")
    print(f"Actions Parity (14,400 steps): {all_actions_match}")
    print(f"Safety Parity: {all_safety_match}")
    print(f"Results written to: {out_path}")

    if not parity_passed:
        print("ERROR: Parity check failed!")
        for m in mismatches:
            print(f"  - {m}")
        sys.exit(1)
    else:
        print("SUCCESS: 100% bitwise parity confirmed! Instrumentation has zero side effects.")


if __name__ == "__main__":
    main()
