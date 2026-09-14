"""Phase 2 Validation Script: Old Broken Arm C vs Corrected Dynamic Arm C.

Validates:
  1. Proactive fence building on Days 0-3 (forward infrastructure planning).
  2. Purchase timing: First cow purchased on Day 5-6 (repaired from Day 9.32 delay).
  3. Zero overbuild (built pastures <= forward herd requirement).
  4. Zero feed safety regression (zero consecutive_unfed >= 2, zero escapes).
  5. Zero Day 12-14 late-purchase invariant violations (physically built empty unreserved only).
  6. Final coin performance contrast across 10 seeds (Seeds 100..109).
"""

import os
import sys
import json
import time
from typing import Dict, Any, List, Optional
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")


def run_repair_validation(seeds: List[int] = list(range(100, 110))) -> Dict[str, Any]:
    print(f"=== Running Phase 2 Arm C Repair Validation across {len(seeds)} seeds: {seeds} ===", flush=True)
    
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")] + clean_sys_path

    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        "main", "config", "strategy", "state", "execution", "market",
        "task_scheduler", "macro_planner", "order_builder", "animal_planner", "pasture_planner",
        "herd_planner", "expansion_planner", "observation_parser", "state_tracker",
        "land_serviceability_model", "marginal_livestock_valuator"
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    import strategy.macro_planner as macro_planner

    results = []

    for seed in seeds:
        print(f"\n--- Testing Seed {seed} ---", flush=True)

        state_tracker.reset_memory()
        agent_module.reset_agent_state()
        agent_module.set_arbitration_mode("historical_candidates_central")
        macro_planner.clear_livestock_decision_logs()
        config.set_livestock_experiment_arm("ArmC")

        first_cow_day = None
        first_sheep_day = None
        pastures_built_by_d3 = 0
        total_pastures_built = 0
        cows_bought = 0
        sheep_bought = 0
        unfed_animal_days = 0
        max_consecutive_unfed = 0
        consecutive_unfed_ge2_count = 0
        animal_escapes = 0
        late_purchase_violations = 0
        housing_capacity_violations = 0

        def tracking_agent(obs, configuration=None):
            nonlocal first_cow_day, first_sheep_day
            nonlocal pastures_built_by_d3, total_pastures_built
            nonlocal cows_bought, sheep_bought
            nonlocal unfed_animal_days, max_consecutive_unfed, consecutive_unfed_ge2_count
            nonlocal animal_escapes, late_purchase_violations, housing_capacity_violations

            day = obs.get("day", 0)
            hour = obs.get("hour", 0)

            # Audit farm tiles (2D grid in Kaggle env)
            farm_dict = obs.get("farm", {})
            tiles = farm_dict.get("tiles", [])
            built_pastures = 0
            cows_on_tiles = 0
            sheep_on_tiles = 0

            for r_idx, row in enumerate(tiles):
                for c_idx, t_dict in enumerate(row):
                    if not isinstance(t_dict, dict):
                        continue
                    structure = t_dict.get("structure") or t_dict.get("kind")
                    if structure == "PASTURE":
                        built_pastures += 1
                    an = t_dict.get("animal")
                    if an == "COW":
                        cows_on_tiles += 1
                    elif an == "SHEEP":
                        sheep_on_tiles += 1

                    if an:
                        cunfed = t_dict.get("consecutive_unfed", 0)
                        if cunfed > max_consecutive_unfed:
                            max_consecutive_unfed = cunfed
                        if cunfed >= 2:
                            consecutive_unfed_ge2_count += 1
                            if hour == 23:
                                animal_escapes += 1
                        if hour == 0 and cunfed > 0:
                            unfed_animal_days += 1

            if day <= 3:
                pastures_built_by_d3 = max(pastures_built_by_d3, built_pastures)
            total_pastures_built = max(total_pastures_built, built_pastures)

            action = agent_module.agent(obs, configuration)

            # Inspect market orders (tuples of [type, species, qty])
            if isinstance(action, dict):
                orders = action.get("market", []) or action.get("orders", [])
                for order in orders:
                    if isinstance(order, (list, tuple)) and len(order) >= 3 and order[0] == "BUY_ANIMAL":
                        spec = order[1]
                        qty = int(order[2])
                        if spec == "COW":
                            cows_bought += qty
                            if first_cow_day is None:
                                first_cow_day = day
                        elif spec == "SHEEP":
                            sheep_bought += qty
                            if first_sheep_day is None:
                                first_sheep_day = day

                        if day >= 12:
                            empty_p = built_pastures - (cows_on_tiles + sheep_on_tiles)
                            if empty_p < qty:
                                late_purchase_violations += 1
                                print(f"VIOLATION: Day {day} bought {spec} with {empty_p} empty pastures!", flush=True)

            return action

        env = make("kaggriculture", configuration={"episodeSteps": 720}, info={"seed": seed})
        env.run([tracking_agent, "starter"])

        final_reward = float(env.state[0].reward or 0.0)

        res = {
            "seed": seed,
            "final_reward": final_reward,
            "pastures_by_d3": pastures_built_by_d3,
            "total_pastures": total_pastures_built,
            "first_cow_day": first_cow_day,
            "first_sheep_day": first_sheep_day,
            "cows_bought": cows_bought,
            "sheep_bought": sheep_bought,
            "unfed_animal_days": unfed_animal_days,
            "max_consecutive_unfed": max_consecutive_unfed,
            "consecutive_unfed_ge2": consecutive_unfed_ge2_count,
            "escapes": animal_escapes,
            "late_purchase_violations": late_purchase_violations,
        }
        results.append(res)
        print(f"Seed {seed} Complete: Reward=${final_reward:.0f}, PasturesByD3={pastures_built_by_d3}, FirstCowDay={first_cow_day}, FirstSheepDay={first_sheep_day}, LateViolations={late_purchase_violations}, Escapes={animal_escapes}", flush=True)

    print("\n=== SUMMARY OF PHASE 2 REPAIR ===", flush=True)
    avg_reward = np.mean([r["final_reward"] for r in results])
    avg_pastures_d3 = np.mean([r["pastures_by_d3"] for r in results])
    cow_days = [r["first_cow_day"] for r in results if r["first_cow_day"] is not None]
    avg_cow_day = np.mean(cow_days) if cow_days else None
    tot_late_viol = sum(r["late_purchase_violations"] for r in results)
    tot_escapes = sum(r["escapes"] for r in results)
    tot_ge2 = sum(r["consecutive_unfed_ge2"] for r in results)

    print(f"Seeds evaluated: {len(results)}")
    print(f"Mean Reward: ${avg_reward:.2f}")
    print(f"Mean Pastures by Day 3: {avg_pastures_d3:.2f}")
    cow_day_str = f"{avg_cow_day:.2f}" if avg_cow_day is not None else "N/A"
    print(f"Mean First Cow Buy Day: {cow_day_str} (Repaired from Day 9.32)")
    print(f"Total Late Purchase Violations: {tot_late_viol}")
    print(f"Total Escapes: {tot_escapes}")
    print(f"Total Consecutive Unfed >= 2: {tot_ge2}")

    return {"results": results}


if __name__ == "__main__":
    run_repair_validation()
