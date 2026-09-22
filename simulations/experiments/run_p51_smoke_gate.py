#!/usr/bin/env python3
"""Kaggriculture P5.1 — Strengthened Smoke Gate Runner.

Runs matched Control (baseline 536f1e7) vs Treatment (P5.1 enabled) on seed 96,201.
Validates:
1. At least 5 engine-confirmed, fully completed rotations (Phase COMPLETED).
2. At least one Day 23 -> Day 26 -> Day 29 case completed.
3. Zero missed planting-day waterings on completed rotations.
4. Zero animal starvation events.
5. Positive final live cash delta.
"""
from collections import defaultdict
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
agent_dir = os.path.join(ROOT, "agent")
sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

import kaggle_environments
from kaggle_environments.envs.kaggriculture import kaggriculture as kg
import main as agent_module
import config as agent_cfg
import execution.task_scheduler as ts
import simulations.experiments.audit_p50r_telemetry as apt
from simulations.experiments.agent_zoo import get_agent
from strategy.two_cycle_rotation_manager import get_rotation_manager, reset_rotation_manager, RotationPhase


def run_smoke_match(seed: int, opponent: str, seat: int, enable_p51: bool):
    """Run a single game returning game state, final reward, money, and rotation manager telemetry."""
    # Reset all modules
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
            "two_cycle_rotation_manager", "expansion_planner", "price_math", "price_forecast",
        )):
            del sys.modules[key]

    import main as m_mod
    import config as m_cfg
    from strategy.two_cycle_rotation_manager import get_rotation_manager, reset_rotation_manager

    apt._configure_baseline(m_cfg)
    m_cfg.set_p51_t1_two_cycle_carrot_enabled(enable_p51)
    m_mod.reset_agent_state()
    reset_rotation_manager()

    opp_agent = get_agent(opponent)
    players = [m_mod.agent, opp_agent] if seat == 0 else [opp_agent, m_mod.agent]

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": seed}, info={"seed": seed})
    env.reset()
    env.run(players)

    reward = env.state[seat].reward
    opp_reward = env.state[1 - seat].reward
    money = env.state[seat].observation.farms[seat]["money"]
    mgr = get_rotation_manager()
    rotations_summary = {
        pos: {
            "c1_plant_day": rec.c1_plant_day,
            "c2_plant_day": rec.c2_plant_day,
            "phase": rec.phase.value,
            "c1_planted": rec.c1_planted_confirmed,
            "c1_watered": rec.c1_d0_watered_confirmed,
            "c1_harvested": rec.c1_harvested_confirmed,
            "c2_planted": rec.c2_planted_confirmed,
            "c2_watered": rec.c2_d0_watered_confirmed,
            "c2_harvested": rec.c2_harvested_confirmed,
            "failure_reason": rec.failure_reason,
        }
        for pos, rec in mgr.rotations.items()
    }

    # Animal starvation check
    farm = env.state[seat].observation.farms[seat]
    starved = 0
    # In kaggriculture, if consecutive_unfed >= 2, animal escapes / starves
    for row in farm["tiles"]:
        for t in row:
            if t and isinstance(t, dict) and "animal" in t and t.get("consecutive_unfed", 0) >= 2:
                starved += 1

    return {
        "reward": reward,
        "opp_reward": opp_reward,
        "money": money,
        "starved": starved,
        "rotations": rotations_summary,
    }


def main():
    seed = 96201
    opponent = "pass"
    seat = 0

    print(f"--- 1. RUNNING CONTROL MATCH (Seed {seed}, vs {opponent}, Seat {seat}) ---")
    ctrl = run_smoke_match(seed, opponent, seat, enable_p51=False)
    print(f"Control Finished: Reward={ctrl['reward']}, Money=${ctrl['money']:.2f}, Starved={ctrl['starved']}")

    print(f"\n--- 2. RUNNING TREATMENT MATCH (P5.1 ENABLED) ---")
    treat = run_smoke_match(seed, opponent, seat, enable_p51=True)
    print(f"Treatment Finished: Reward={treat['reward']}, Money=${treat['money']:.2f}, Starved={treat['starved']}")

    delta_reward = treat["reward"] - ctrl["reward"]
    delta_money = treat["money"] - ctrl["money"]
    print(f"\n--- MATCH RESULTS ---")
    print(f"Reward Delta: {delta_reward:+.2f}")
    print(f"Money Delta:  ${delta_money:+.2f}")

    # Inspect rotations
    rots = treat["rotations"]
    print(f"\nTotal Tracked Rotations: {len(rots)}")
    from collections import Counter
    phase_counts = Counter(r["phase"] for r in rots.values())
    print(f"Phase Breakdown: {dict(phase_counts)}")
    for pos, r in rots.items():
        print(f"  Tile {pos}: C1 Plant D{r['c1_plant_day']}, C2 Plant D{r['c2_plant_day']}, Phase={r['phase']}, C1_watered={r['c1_watered']}, C2_watered={r['c2_watered']}, Reason={r['failure_reason']}")

    completed = [pos for pos, r in rots.items() if r["phase"] == "COMPLETED"]
    d23_cases = [pos for pos, r in rots.items() if r["c1_plant_day"] == 23 and r["phase"] == "COMPLETED"]

    print(f"\nCompleted Rotations: {len(completed)}")
    print(f"Day 23 -> 26 -> 29 Completed Cases: {len(d23_cases)} ({d23_cases})")

    missed_d0_water = 0
    for pos in completed:
        r = rots[pos]
        if not r["c1_watered"] or not r["c2_watered"]:
            missed_d0_water += 1

    print(f"Missed Planting-Day Water on Completed Rotations: {missed_d0_water}")

    smoke_passed = (
        len(completed) >= 5 and
        len(d23_cases) >= 1 and
        missed_d0_water == 0 and
        treat["starved"] == 0 and
        delta_money > 0
    )

    print(f"\nSMOKE GATE CRITERIA CHECK:")
    print(f"1. >= 5 completed rotations:             {'PASS' if len(completed) >= 5 else 'FAIL'} ({len(completed)})")
    print(f"2. >= 1 Day 23->26->29 completed case:    {'PASS' if len(d23_cases) >= 1 else 'FAIL'} ({len(d23_cases)})")
    print(f"3. Zero missed planting-day watering:    {'PASS' if missed_d0_water == 0 else 'FAIL'}")
    print(f"4. Zero animal starvation:               {'PASS' if treat['starved'] == 0 else 'FAIL'}")
    print(f"5. Positive final live cash delta:       {'PASS' if delta_money > 0 else 'FAIL'} (${delta_money:+.2f})")
    print(f"\nOVERALL SMOKE GATE VERDICT: {'PASSED' if smoke_passed else 'FAILED'}")

    os.makedirs("simulations/experiments/results", exist_ok=True)
    out_file = "simulations/experiments/results/p51_smoke_results.json"
    str_ctrl = dict(ctrl)
    str_ctrl["rotations"] = {str(k): v for k, v in str_ctrl["rotations"].items()}
    str_treat = dict(treat)
    str_treat["rotations"] = {str(k): v for k, v in str_treat["rotations"].items()}
    with open(out_file, "w") as f:
        json.dump({
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "control": str_ctrl,
            "treatment": str_treat,
            "delta_reward": delta_reward,
            "delta_money": delta_money,
            "completed_count": len(completed),
            "d23_completed_count": len(d23_cases),
            "missed_d0_water": missed_d0_water,
            "smoke_passed": smoke_passed,
        }, f, indent=2)
    print(f"Wrote smoke results to {out_file}")


if __name__ == "__main__":
    main()
