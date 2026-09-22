#!/usr/bin/env python3
"""P4.1 Late-Season Isolated SW Zonal Expansion — Instrumented Feasibility Test.

Protocol:
- Seeds: 97,001–97,010 (10 pairs x 2 seats = 20 matched pairs = 40 total games).
- Baseline Lineage: 536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e.
- Opponents: 5 standard archetypes (pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent).
- Treatment: P41_SW_ZONAL_EXPANSION_ENABLED = True (Hybrid mode: 4 Strawberry + 4 Wheat).
- Control: P41_SW_ZONAL_EXPANSION_ENABLED = False.

Instrumented Checks:
1. SW unlocks on Day 14.
2. Two-worker isolation: strictly units 11 & 12 perform SW agricultural tasks; units 0..10 perform 0.
3. Core watering compliance >= 98.0%.
4. Zero animal starvation events.
5. Zero negative cash steps.
6. Score comparison: Control mean, Treatment mean, Delta, 95% CI.
"""
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

BASELINE_SHA = "536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e"
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

# Fresh feasibility seed block: 97,001–97,010
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 97001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(10)  # 10 pairs x 2 seats = 20 matched cases (40 games)
]

SHED_TILES = {(4, 4), (5, 4), (4, 5), (5, 5)}


def _git_sha(ref: str) -> str:
    res = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _extract_control_agent(commit_sha: str) -> str:
    out_dir = os.path.join(tempfile.gettempdir(), f"kagg_p41_control_{commit_sha[:8]}")
    if os.path.exists(out_dir):
        try:
            shutil.rmtree(out_dir)
        except Exception:
            pass
    os.makedirs(out_dir, exist_ok=True)
    tar = subprocess.Popen(["git", "archive", commit_sha, "agent"], cwd=ROOT, stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", out_dir], stdin=tar.stdout, check=True)
    tar.wait()
    agent_dir = os.path.join(out_dir, "agent")
    if not os.path.isdir(agent_dir):
        raise RuntimeError(f"Failed to extract agent/ from {commit_sha}")
    return agent_dir


def _snapshot_worktree_agent(temp_dir: str) -> str:
    target = os.path.join(temp_dir, "worktree_agent")
    src = os.path.join(ROOT, "agent")
    shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    return target


def _configure_arm(cfg, arm: str):
    # Reset all experimental flags to authoritatively frozen baseline invariants
    cfg.set_opponent_intelligence_mode("O0_SHADOW")
    for attr, val in (
        ("SW_OWNERSHIP_MODE", "production"),
        ("SW_TIMING_PRIOR_ENABLED", False),
        ("SW_ACTIVATION_MODE", "production"),
        ("SW_SAFETY_RESERVE", 300.0),
        ("STRATEGIC_SW_OWNERSHIP_ENABLED", False),
        ("DYNAMIC_ZONAL_ALLOCATION", False),
        ("DYNAMIC_SW_CROPS_ENABLED", False),
        ("PERSISTENT_WORKER_LOCALITY_ENABLED", False),
        ("SW_CELL_HOUSING_ENABLED", False),
        ("SW_P1_PURCHASE_COMMITTED_HERD_ONLY", False),
        ("SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED", False),
        ("SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED", False),
        ("SW_GENERIC_PLANTING_GATE_ENABLED", False),
        ("P13_TIGHT_SOIL_ENABLED", False),
        ("P13_LIVESTOCK_CAP_ENABLED", False),
        ("P20_SECOND_MELON_TRANCHE_ENABLED", False),
        ("P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED", False),
        ("P22A_DAY28_FEED_HARMONIZATION_ENABLED", False),
        ("P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", True),
        ("P31_STATE_DEPENDENT_HARVEST_PRIORITY_ENABLED", False),
        ("P32_STATE_DEPENDENT_CARE_PRIORITY_ENABLED", False),
        ("P33_PHYSICAL_LOCALITY_ENABLED", False),
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    if hasattr(cfg, "set_p23_marginal_wheat_allocation_enabled"):
        cfg.set_p23_marginal_wheat_allocation_enabled(True)

    # Set P4.1 Late-Season Isolated SW switch
    expected_p41 = (arm == "Treatment")
    if hasattr(cfg, "set_p41_sw_zonal_expansion_enabled"):
        cfg.set_p41_sw_zonal_expansion_enabled(expected_p41)
    else:
        setattr(cfg, "P41_SW_ZONAL_EXPANSION_ENABLED", expected_p41)

    if hasattr(cfg, "set_p41_sw_crop_mode"):
        cfg.set_p41_sw_crop_mode("hybrid")

    # Invariants verification
    assert cfg.QUADRANT_HARD_BLOCK == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    assert getattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", False) is True, f"{arm}: P23 must be True"


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
            "expansion_planner",
        )):
            del sys.modules[key]

    try:
        import kaggle_environments
        import main as module
        import config as cfg
        import execution.task_scheduler as ts
        from simulations.experiments.agent_zoo import get_agent

        _configure_arm(cfg, task["arm"])
        module.reset_agent_state()
        ts.reset_daily_log()

        telemetry = {
            "sw_unlocked_day": None,
            "sw_agri_actions_by_unit": defaultdict(int),
            "core_agri_actions_by_unit": defaultdict(int),
            "sw_harvest_units": defaultdict(int),
            "core_plants_watered_turns": 0,
            "core_plants_needed_water_turns": 0,
            "core_plant_deaths": 0,
            "missed_feedings_eod": 0,
            "negative_cash_steps": 0,
            "final_cash": 0.0,
        }

        def tracking_agent(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            player = int(obs.get("player", task["seat"]))
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}

            # Check SW unlock day
            unlocked = farm.get("unlocked_quadrants", ["NW"]) or ["NW"]
            if "SW" in unlocked and telemetry["sw_unlocked_day"] is None:
                telemetry["sw_unlocked_day"] = day

            # Cash check
            money = float(farm.get("money", 0.0))
            if money < -1e-6:
                telemetry["negative_cash_steps"] += 1

            # End of day checks at Hour 23
            if hour == 23:
                tiles_grid = farm.get("tiles", []) or []
                for y, row in enumerate(tiles_grid):
                    for x, t in enumerate(row or []):
                        if isinstance(t, dict):
                            is_sw = (x < 5 and y >= 5) and (x, y) not in SHED_TILES
                            is_core = (y < 5) and (x, y) not in SHED_TILES
                            kind = t.get("kind")
                            if kind == "PLANT":
                                if is_core:
                                    telemetry["core_plants_needed_water_turns"] += 1
                                    if t.get("watered_today", False):
                                        telemetry["core_plants_watered_turns"] += 1
                                    if t.get("consecutive_unwatered", 0) >= 1:
                                        telemetry["core_plant_deaths"] += 1
                            elif t.get("animal") or t.get("is_animal"):
                                if not t.get("fed_today", False):
                                    telemetry["missed_feedings_eod"] += 1

            # Call agent decision
            action_dict = module.agent(obs, configuration)

            # Audit unit actions
            # Farmer is unit 0, hands are units 1..N
            farmer_action = action_dict.get("farmer", ["PASS"])
            hands_actions = action_dict.get("hands", [])

            all_unit_actions = [(0, farmer_action, tuple(farm.get("farmer", [4, 4])))]
            for i, h_act in enumerate(hands_actions):
                h_pos = tuple(farm.get("hands", [])[i]) if i < len(farm.get("hands", [])) else (4, 4)
                all_unit_actions.append((i + 1, h_act, h_pos))

            for u_idx, act, pos in all_unit_actions:
                op = act[0] if act else "PASS"
                if op in ("WATER", "PLANT", "TILL", "DIG", "FERTILIZE", "HARVEST"):
                    x, y = pos
                    if (x, y) not in SHED_TILES:
                        if x < 5 and y >= 5:  # SW agricultural tile
                            telemetry["sw_agri_actions_by_unit"][u_idx] += 1
                            if op == "HARVEST":
                                # Track harvests
                                t_obj = farm.get("tiles", [])[y][x] if y < len(farm.get("tiles", [])) and x < len(farm.get("tiles", [])[y]) else {}
                                crop = t_obj.get("crop", "UNKNOWN")
                                y_units = int(t_obj.get("yield_units", 2))
                                telemetry["sw_harvest_units"][crop] += y_units
                        elif y < 5:  # NW / NE core tile
                            telemetry["core_agri_actions_by_unit"][u_idx] += 1

            return action_dict

        opponent_fn = get_agent(task["opponent"])
        env = kaggle_environments.make("kaggriculture", debug=False)
        seed = int(task["seed"])
        env.configuration["seed"] = seed

        agents = [None, None]
        agents[task["seat"]] = tracking_agent
        agents[1 - task["seat"]] = opponent_fn

        env.reset()
        t0 = time.time()
        for step_idx in range(720):
            env.step([agents[0](env.state[0].observation), agents[1](env.state[1].observation)])
            if env.done:
                break
        wall_time = time.time() - t0

        final_obs = env.state[task["seat"]].observation
        my_farm = final_obs["farms"][task["seat"]]
        final_money = float(my_farm.get("money", 0.0))
        telemetry["final_cash"] = final_money

        core_needed = telemetry["core_plants_needed_water_turns"]
        core_watered = telemetry["core_plants_watered_turns"]
        watering_compliance = (core_watered / core_needed * 100.0) if core_needed > 0 else 100.0

        return {
            "pair_id": task["pair_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "seat": task["seat"],
            "arm": task["arm"],
            "final_cash": final_money,
            "wall_time": wall_time,
            "sw_unlocked_day": telemetry["sw_unlocked_day"],
            "sw_agri_actions": dict(telemetry["sw_agri_actions_by_unit"]),
            "core_agri_actions": dict(telemetry["core_agri_actions_by_unit"]),
            "sw_harvest_units": dict(telemetry["sw_harvest_units"]),
            "watering_compliance": round(watering_compliance, 2),
            "core_plant_deaths": telemetry["core_plant_deaths"],
            "missed_feedings": telemetry["missed_feedings_eod"],
            "negative_cash_steps": telemetry["negative_cash_steps"],
            "success": True,
        }
    except Exception as exc:
        return {
            "pair_id": task["pair_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "seat": task["seat"],
            "arm": task["arm"],
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }


def main():
    t_start = time.time()
    print("=" * 80)
    print("Kaggriculture P4.1 Feasibility Test (20 Matched Games)")
    print(f"Authoritative Control Baseline Lineage: {BASELINE_SHA}")
    print("Seed Block: 97,001–97,010 (10 pairs x 2 seats = 20 matched games)")
    print("=" * 80)

    # 1. Setup agents
    temp_dir = tempfile.mkdtemp(prefix="kagg_p41_feasibility_")
    try:
        print("[1/4] Extracting control baseline agent...")
        control_dir = _extract_control_agent(BASELINE_SHA)
        print(f"  Control agent extracted to: {control_dir}")

        print("[2/4] Snapshotting worktree treatment agent...")
        treatment_dir = _snapshot_worktree_agent(temp_dir)
        print(f"  Treatment agent snapshotted to: {treatment_dir}")

        # 2. Build tasks
        tasks = []
        for sc in SCENARIOS:
            for seat in (0, 1):
                tasks.append({
                    "pair_id": sc["pair_id"],
                    "seed": sc["seed"],
                    "opponent": sc["opponent"],
                    "seat": seat,
                    "arm": "Control",
                    "agent_dir": control_dir,
                })
                tasks.append({
                    "pair_id": sc["pair_id"],
                    "seed": sc["seed"],
                    "opponent": sc["opponent"],
                    "seat": seat,
                    "arm": "Treatment",
                    "agent_dir": treatment_dir,
                })

        print(f"[3/4] Launching {len(tasks)} games across ProcessPoolExecutor...")
        results = []
        # Run with max_workers=4 for stability and speed
        max_workers = min(6, os.cpu_count() or 4)
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_one, t) for t in tasks]
            for f in as_completed(futures):
                res = f.result()
                results.append(res)
                arm = res["arm"]
                pair = res["pair_id"]
                seat = res["seat"]
                score = res.get("final_cash", 0.0)
                status = "OK" if res.get("success") else f"FAIL: {res.get('error')}"
                print(f"  [{len(results):2d}/{len(tasks):2d}] Pair {pair:2d} Seat {seat} {arm:9s}: ${score:9.2f} ({status})")

        print("\n[4/4] Analyzing results and verifying feasibility gates...")
        # Pair results by (pair_id, seat)
        paired = defaultdict(dict)
        for r in results:
            if r.get("success"):
                key = (r["pair_id"], r["seat"])
                paired[key][r["arm"]] = r

        complete_pairs = [p for p in paired.values() if "Control" in p and "Treatment" in p]
        print(f"\nSuccessfully matched pairs: {len(complete_pairs)} / 20")

        ctrl_scores = [p["Control"]["final_cash"] for p in complete_pairs]
        treat_scores = [p["Treatment"]["final_cash"] for p in complete_pairs]
        deltas = [t - c for t, c in zip(treat_scores, ctrl_scores)]

        mean_ctrl = statistics.mean(ctrl_scores) if ctrl_scores else 0.0
        mean_treat = statistics.mean(treat_scores) if treat_scores else 0.0
        mean_delta = statistics.mean(deltas) if deltas else 0.0
        stdev_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
        se_delta = stdev_delta / math.sqrt(len(deltas)) if len(deltas) > 1 else 0.0
        t_crit = 2.093  # df=19, 95% CI
        ci_lower = mean_delta - t_crit * se_delta
        ci_upper = mean_delta + t_crit * se_delta

        # Two-worker isolation audit
        treatment_results = [p["Treatment"] for p in complete_pairs]
        sw_unlocked_games = sum(1 for t in treatment_results if t["sw_unlocked_day"] is not None)
        total_sw_agri_actions_core = sum(
            sum(cnt for u, cnt in t["sw_agri_actions"].items() if int(u) not in (11, 12))
            for t in treatment_results
        )
        total_sw_agri_actions_sw = sum(
            sum(cnt for u, cnt in t["sw_agri_actions"].items() if int(u) in (11, 12))
            for t in treatment_results
        )
        total_core_agri_actions_sw = sum(
            sum(cnt for u, cnt in t["core_agri_actions"].items() if int(u) in (11, 12))
            for t in treatment_results
        )

        min_watering_compliance = min(t["watering_compliance"] for t in treatment_results) if treatment_results else 0.0
        mean_watering_compliance = statistics.mean(t["watering_compliance"] for t in treatment_results) if treatment_results else 0.0
        total_starvations = sum(t["missed_feedings"] for t in treatment_results)
        total_negative_cash = sum(t["negative_cash_steps"] for t in treatment_results)

        total_sw_strawberries = sum(t["sw_harvest_units"].get("STRAWBERRY", 0) for t in treatment_results)
        total_sw_wheat = sum(t["sw_harvest_units"].get("WHEAT", 0) for t in treatment_results)

        print("\n" + "=" * 80)
        print("P4.1 FEASIBILITY TEST RESULTS SUMMARY")
        print("=" * 80)
        print(f"Control Mean Score:       ${mean_ctrl:10.2f}")
        print(f"Treatment Mean Score:     ${mean_treat:10.2f}")
        print(f"Mean Paired Delta:        ${mean_delta:+10.2f}")
        print(f"Delta 95% CI:             [${ci_lower:+8.2f}, ${ci_upper:+8.2f}]")
        print(f"Delta Std Dev / SE:       ${stdev_delta:.2f} / ${se_delta:.2f}")
        print("-" * 80)
        print("TELEMETRY & MECHANISM AUDIT:")
        print(f"  SW Unlocked Games:      {sw_unlocked_games} / {len(treatment_results)}")
        print(f"  SW Agri Actions (11,12):{total_sw_agri_actions_sw} turns")
        print(f"  SW Agri Actions (Core): {total_sw_agri_actions_core} turns (MUST BE 0)")
        print(f"  Core Agri Actions (11,12): {total_core_agri_actions_sw} turns")
        print(f"  SW Strawberries Harvested: {total_sw_strawberries} units")
        print(f"  SW Wheat Harvested:        {total_sw_wheat} units")
        print(f"  Core Watering Compliance:  Mean {mean_watering_compliance:.2f}%, Min {min_watering_compliance:.2f}% (>= 98.0%)")
        print(f"  Animal Starvations:        {total_starvations} (MUST BE 0)")
        print(f"  Negative Cash Steps:       {total_negative_cash} (MUST BE 0)")
        print("=" * 80)

        # Save results to JSON
        output_dir = os.path.join(ROOT, "simulations", "experiments", "results")
        os.makedirs(output_dir, exist_ok=True)
        out_file = os.path.join(output_dir, "p41_feasibility_test.json")
        summary_payload = {
            "experiment": "P4.1 Late-Season Isolated SW Zonal Expansion Feasibility Test",
            "control_sha": BASELINE_SHA,
            "seed_block": "97,001-97,010",
            "games_evaluated": len(results),
            "matched_pairs": len(complete_pairs),
            "control_mean": mean_ctrl,
            "treatment_mean": mean_treat,
            "mean_delta": mean_delta,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "sw_unlocked_games": sw_unlocked_games,
            "total_sw_agri_actions_sw": total_sw_agri_actions_sw,
            "total_sw_agri_actions_core": total_sw_agri_actions_core,
            "core_watering_compliance_mean": mean_watering_compliance,
            "core_watering_compliance_min": min_watering_compliance,
            "total_starvations": total_starvations,
            "total_negative_cash": total_negative_cash,
            "sw_strawberries_harvested": total_sw_strawberries,
            "sw_wheat_harvested": total_sw_wheat,
            "raw_results": results,
        }
        with open(out_file, "w") as f:
            json.dump(summary_payload, f, indent=2)
        print(f"\nDetailed telemetry written to: {out_file}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")
        print(f"Total runtime: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
