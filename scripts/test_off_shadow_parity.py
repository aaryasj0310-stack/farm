#!/usr/bin/env python3
"""Authoritative OFF vs SHADOW Action-Parity and Live State Invariance Harness.

Phase SW-B2-R1 Verification:
Executes matches in C0 (OFF) and C1 (SHADOW) under real named opponent policies
from the canonical agent zoo across both seats and all 5 canonical opponents.

Verification Criteria:
1. Turn-by-turn emitted actions (farmer, hands, market) must be 100% bit-identical.
2. Turn-by-turn opponent actions must be 100% bit-identical.
3. Post-step engine observations (money, shed) must be 100% bit-identical.
4. Persistent live strategy state (FarmPlan state) must be 100% identical.
5. Final terminal cash must be 100% bit-identical.
6. Zero side effects: SHADOW forward planning must not mutate live planner state.
7. Engine accounting: 719 actionable turns (step 0 through 718) advancing to terminal step 720.
"""
import copy
import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

import kaggle_environments

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def run_single_match(seed: int, opp_name: str, seat: int, arch_mode: str) -> Dict[str, Any]:
    """Execute a single match with full opponent policy execution and turn-by-turn capture."""
    import agent.config as config
    config.SW_FORWARD_ARCHITECTURE_MODE = arch_mode
    config.SOFT_WORKER_LOCALITY_MODE = "ON"
    config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
    config.QUADRANT_HARD_BLOCK = {4}

    from agent.main import agent as my_agent, reset_agent_state
    from agent.strategy.farm_plan import reset_farm_plan, get_farm_plan
    from agent.strategy.whole_farm_planner import reset_whole_farm_planner
    from agent.execution.midnight_storage_controller import reset_midnight_storage_telemetry
    from simulations.experiments.agent_zoo import get_agent

    # Clean state reset
    reset_agent_state()
    reset_farm_plan()
    reset_whole_farm_planner()
    reset_midnight_storage_telemetry()

    opp_agent = get_agent(opp_name)

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"seed": seed, "episodeSteps": 720},
        debug=False,
    )
    env.reset()

    my_actions: List[Dict[str, Any]] = []
    opp_actions: List[Dict[str, Any]] = []
    step_snapshots: List[Dict[str, Any]] = []

    # Episode loop: 719 actionable turns (step 0 to step 718)
    # At step 719, the environment reaches step 720 where env.done == True
    while not env.done:
        step_idx = len(my_actions)
        obs_my = env.state[seat].observation
        obs_opp = env.state[1 - seat].observation

        # Execute our agent
        my_act = my_agent(obs_my, env.configuration)
        my_actions.append(copy.deepcopy(my_act))

        # Execute opponent policy with 1 or 2 parameter support
        try:
            opp_act = opp_agent(obs_opp, env.configuration)
        except TypeError:
            opp_act = opp_agent(obs_opp)
        opp_actions.append(copy.deepcopy(opp_act))

        # Step environment with both real player actions
        actions = [my_act, opp_act] if seat == 0 else [opp_act, my_act]
        env.step(actions)

        # Snapshot post-step observation for invariant verification
        post_obs_my = env.state[seat].observation
        step_snapshots.append({
            "step": step_idx,
            "money": float(post_obs_my["farms"][seat]["money"]),
            "shed": dict(post_obs_my.get("private", {}).get("shed", {})),
        })

    final_obs = env.state[seat].observation
    final_cash = float(final_obs["farms"][seat]["money"])
    final_plan_state = get_farm_plan().state.value

    return {
        "final_cash": final_cash,
        "my_actions": my_actions,
        "opp_actions": opp_actions,
        "step_snapshots": step_snapshots,
        "final_plan_state": final_plan_state,
        "total_action_turns": len(my_actions),
    }


def verify_pair(seed: int, opp: str, seat: int) -> Tuple[bool, str]:
    """Run OFF and SHADOW and rigorously compare turn-by-turn actions and engine states."""
    t0 = time.time()
    res_off = run_single_match(seed, opp, seat, "OFF")
    t_off = time.time() - t0

    t1 = time.time()
    res_sh = run_single_match(seed, opp, seat, "SHADOW")
    t_sh = time.time() - t1

    # 1. Total turn count check (must be exactly 719 actionable turns)
    if res_off["total_action_turns"] != 719:
        return False, f"Turn count error: expected 719 turns, got {res_off['total_action_turns']} in OFF"
    if res_sh["total_action_turns"] != 719:
        return False, f"Turn count error: expected 719 turns, got {res_sh['total_action_turns']} in SHADOW"

    # 2. Turn-by-turn action comparison
    for step in range(719):
        a_off = res_off["my_actions"][step]
        a_sh = res_sh["my_actions"][step]
        if a_off != a_sh:
            trace = (
                f"ACTION DIVERGENCE at Step {step} (Day {step//24}, Hour {step%24}):\n"
                f"  OFF Action:    {a_off}\n"
                f"  SHADOW Action: {a_sh}\n"
            )
            return False, trace

        # Compare opponent actions
        opp_off = res_off["opp_actions"][step]
        opp_sh = res_sh["opp_actions"][step]
        if opp_off != opp_sh:
            trace = (
                f"OPPONENT ACTION DIVERGENCE at Step {step}:\n"
                f"  OFF Opp Action:    {opp_off}\n"
                f"  SHADOW Opp Action: {opp_sh}\n"
            )
            return False, trace

        # Compare post-step engine snapshots
        snap_off = res_off["step_snapshots"][step]
        snap_sh = res_sh["step_snapshots"][step]
        if snap_off != snap_sh:
            trace = (
                f"ENGINE STATE DIVERGENCE at Step {step}:\n"
                f"  OFF State:    {snap_off}\n"
                f"  SHADOW State: {snap_sh}\n"
            )
            return False, trace

    # 3. Live planner state comparison (must not be mutated by SHADOW)
    if res_off["final_plan_state"] != res_sh["final_plan_state"]:
        return False, f"Live FarmPlan state diverged! OFF={res_off['final_plan_state']} vs SHADOW={res_sh['final_plan_state']}"

    # 4. Final cash comparison
    if res_off["final_cash"] != res_sh["final_cash"]:
        return False, f"Final cash mismatch! OFF=${res_off['final_cash']:.2f} vs SHADOW=${res_sh['final_cash']:.2f}"

    msg = f"Cash = ${res_off['final_cash']:,.2f} | 719/719 turns identical | PlanState = {res_off['final_plan_state']} (OFF: {t_off:.1f}s, SHADOW: {t_sh:.1f}s)"
    return True, msg


def main():
    print("================================================================================")
    print("PHASE SW-B2-R1: CORRECTED OFF vs SHADOW ACTION-PARITY HARNESS")
    print("================================================================================")
    print("Engine Accounting: 719 actionable turns (step 0..718) advancing to terminal step 720.")
    print("Executing real opponent policies from canonical agent zoo across both seats.\n")

    test_panel = [
        (97013, "pass", 0),
        (97014, "pass", 1),
        (97015, "pure_wheat_rush", 0),
        (97016, "pure_wheat_rush", 1),
        (97017, "cow_milk_engine", 0),
        (97018, "cow_milk_engine", 1),
        (97019, "melon_sniper", 0),
        (97020, "melon_sniper", 1),
        (97021, "full_production_agent", 0),
        (97022, "full_production_agent", 1),
    ]

    all_passed = True
    results_log = []

    for i, (seed, opp, seat) in enumerate(test_panel, 1):
        print(f"[{i:02d}/10] Testing Seed {seed} vs {opp:<22} (Seat {seat})... ", end="", flush=True)
        passed, detail = verify_pair(seed, opp, seat)
        if passed:
            print(f"PASSED!  {detail}")
            results_log.append({"test": i, "seed": seed, "opp": opp, "seat": seat, "status": "PASSED", "detail": detail})
        else:
            print(f"FAILED!\n{detail}")
            results_log.append({"test": i, "seed": seed, "opp": opp, "seat": seat, "status": "FAILED", "detail": detail})
            all_passed = False
            break

    print("\n================================================================================")
    if all_passed:
        print("ALL 10 OPPONENT x SEAT PARITY CHECKS PASSED: EXACT 100% BIT-FOR-BIT PARITY!")
        print("Verified: SHADOW forward planning introduces ZERO runtime divergence or state mutation.")
    else:
        print("PARITY FAILURE DETECTED: ACTION DIVERGENCE FOUND.")
        sys.exit(1)
    print("================================================================================")


if __name__ == "__main__":
    main()
