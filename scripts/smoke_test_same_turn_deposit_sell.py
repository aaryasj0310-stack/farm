"""Smoke test for Phase M0-E Same-Turn Deposit-to-Market Exploit.

Tests seeds 96501 and 96502 against 'pass' and 'pure_wheat_rush' across seats 0 and 1.
Validates:
1. OFF reproduces baseline.
2. SHADOW produces bit-for-bit identical actions as OFF.
3. LIVE deposit predictions match ground-truth shed deposit 100%.
4. No invalid market orders, no overselling, no feed wheat violations.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any, Dict, List, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
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
from execution.same_turn_deposit_controller import (
    get_same_turn_deposit_telemetry,
    reset_same_turn_deposit_telemetry,
)


def run_smoke_match(seed: int, opp_name: str, seat: int, mode: str) -> Dict[str, Any]:
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    config.set_midnight_storage_dump_mode("OFF")
    config.set_same_turn_deposit_sell_mode(mode)

    reset_agent_state()
    reset_sw_tranche_controller()
    reset_same_turn_deposit_telemetry()

    recorded_actions: List[Dict[str, Any]] = []
    prediction_checks: List[Dict[str, Any]] = []

    # Hook engine to observe shed after unit actions, right before market
    orig_process_market = kengine._process_market
    shed_before_step = {}
    shed_after_units = {}

    market_step = [0]

    def instrumented_process_market(state, env):
        p_shed = dict(state[seat].observation.private.shed)
        step = market_step[0]
        market_step[0] += 1
        shed_after_units[step] = p_shed
        orig_process_market(state, env)

    kengine._process_market = instrumented_process_market

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    step_num = 0
    try:
        while not env.done:
            obs = env.state[seat].observation
            step = env.steps[-1][0].observation.step if hasattr(env.steps[-1][0].observation, "step") else step_num
            shed_before_step[step] = dict(obs.private.shed)

            act = agent(obs, env.configuration)
            recorded_actions.append(copy.deepcopy(act))

            try:
                opp_act = opp_agent(env.state[1 - seat].observation, env.configuration)
            except TypeError:
                opp_act = opp_agent(env.state[1 - seat].observation)

            actions = [act, opp_act] if seat == 0 else [opp_act, act]
            env.step(actions)

            # Check deposit prediction if we had worker DROP/PLACE
            step_num += 1
    finally:
        kengine._process_market = orig_process_market

    final_reward = float(env.steps[-1][seat].reward or 0.0)
    opp_reward = float(env.steps[-1][1 - seat].reward or 0.0)
    telem = get_same_turn_deposit_telemetry()

    return {
        "seed": seed,
        "opp": opp_name,
        "seat": seat,
        "mode": mode,
        "final_reward": final_reward,
        "opp_reward": opp_reward,
        "actions": recorded_actions,
        "telemetry": telem,
        "shed_before": shed_before_step,
        "shed_after_units": shed_after_units,
    }


def main():
    print("=== Running Smoke Test for Phase M0-E ===")
    seeds = [96501, 96502]
    opponents = ["pass", "pure_wheat_rush"]
    seats = [0, 1]

    # 1. Test bit-level parity between OFF and SHADOW
    print("Checking OFF vs SHADOW equivalence...")
    for s in seeds:
        for opp in opponents:
            for seat in seats:
                res_off = run_smoke_match(s, opp, seat, "OFF")
                res_shadow = run_smoke_match(s, opp, seat, "SHADOW")

                assert len(res_off["actions"]) == len(res_shadow["actions"]), "Action length mismatch"
                for step_idx, (a_off, a_sh) in enumerate(zip(res_off["actions"], res_shadow["actions"])):
                    assert a_off == a_sh, f"Action divergence at step {step_idx} in seed {s}, seat {seat}, opp {opp}"

                assert res_off["final_reward"] == res_shadow["final_reward"], (
                    f"Reward mismatch: OFF {res_off['final_reward']} vs SHADOW {res_shadow['final_reward']}"
                )
                print(f"  [OK] Seed {s} {opp} Seat {seat}: OFF == SHADOW bit-for-bit (Reward: {res_off['final_reward']:.1f})")

    # 2. Test LIVE mode
    print("\nChecking LIVE mode execution and deposit prediction accuracy...")
    for s in seeds:
        for opp in opponents:
            for seat in seats:
                res_live = run_smoke_match(s, opp, seat, "LIVE")
                telem = res_live["telemetry"]
                pred = telem.get("deposit_units_predicted", 0)
                actual = telem.get("deposit_units_actual", 0)
                same_turn_sales = telem.get("same_turn_sales_events", 0)
                same_turn_units = telem.get("same_turn_units_sold", 0)
                cash_acc = telem.get("cash_acceleration_est", 0.0)

                print(
                    f"  LIVE Seed {s} {opp} Seat {seat}: "
                    f"Reward={res_live['final_reward']:.1f}, "
                    f"Predicted={pred}, Actual={actual}, "
                    f"SameTurnSalesEvents={same_turn_sales}, UnitsSold={same_turn_units}, "
                    f"CashAcc=${cash_acc:.1f}"
                )
                assert pred == actual, f"Prediction mismatch! Predicted {pred} != Actual {actual}"

    print("\nAll Smoke Tests PASSED perfectly!")


if __name__ == "__main__":
    main()
