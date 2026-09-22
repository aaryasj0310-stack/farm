#!/usr/bin/env python3
"""P3.3-A Physical Locality & Route Compaction Experiment Runner.

Evaluates Promoted Production Baseline (536f1e7..., QUADRANT_HARD_BLOCK={4}, P23=True)
vs P3.3-A Physical Locality (P33_PHYSICAL_LOCALITY_ENABLED=True, P33_PHYSICAL_SWITCH_PENALTY=6).

Evaluation setup:
- 100 matched cases (50 pairs x 2 seats = 200 live games).
- Fresh evaluation seed block: 93,001–93,050.
- Fresh smoke seed block: 92,991–92,995 (strictly isolated from tournament).
- 5 standard opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent.
"""
from collections import defaultdict
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
ARMS = ("Control", "Treatment")
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

# Fresh evaluation seed block: 93,001–93,050
SCENARIOS_EVAL = [
    {
        "pair_id": i + 1,
        "seed": 93001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(50)  # 50 pairs x 2 seats = 100 matched cases (200 games)
]

# Fresh smoke seed block: 92,991–92,995 (completely disjoint from evaluation)
SCENARIOS_SMOKE = [
    {
        "pair_id": i + 1,
        "seed": 92991 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(5)  # 5 pairs x 2 seats = 10 games
]

CROP_SPECS = {
    "WHEAT": {"seed": 10, "price": 25.0, "max_yield": 6, "max_yield_day": 4, "ongoing": False},
    "CARROT": {"seed": 20, "price": 35.0, "max_yield": 4, "max_yield_day": 3, "ongoing": False},
    "TOMATO": {"seed": 50, "price": 60.0, "max_yield": 4, "max_yield_day": 8, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "price": 120.0, "max_yield": 4, "max_yield_day": 10, "ongoing": True},
    "MELON": {"seed": 80, "price": 250.0, "max_yield": 6, "max_yield_day": 12, "ongoing": False},
}


def _git_sha(ref: str) -> str:
    res = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _extract_control_agent(commit_sha: str) -> str:
    out_dir = os.path.join(tempfile.gettempdir(), f"kagg_p33_control_{commit_sha[:8]}")
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


def _snapshot_worktree_agent(temp_dir: str):
    target = os.path.join(temp_dir, "worktree_agent")
    src = os.path.join(ROOT, "agent")
    shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    manifest = []
    for base, _, files in os.walk(target):
        for f in sorted(files):
            if f.endswith(".py"):
                p = os.path.join(base, f)
                manifest.append((os.path.relpath(p, target), os.path.getsize(p)))
    import hashlib
    h = hashlib.sha256(repr(manifest).encode("utf-8")).hexdigest()
    return target, manifest, h


def _configure_arm(cfg, arm: str):
    """Enforce strict 2Q invariants and set P3.3-A physical locality flag."""
    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    elif hasattr(cfg, "QUADRANT_HARD_BLOCK"):
        cfg.QUADRANT_HARD_BLOCK = {4}

    # Reset legacy SW switches and prior rejected treatments
    for attr, val in (
        ("SW_OWNERSHIP_MODE", "production"),
        ("SW_TIMING_PRIOR_ENABLED", False),
        ("SW_ACTIVATION_MODE", "production"),
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
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    if hasattr(cfg, "set_p20_second_melon_tranche_enabled"):
        cfg.set_p20_second_melon_tranche_enabled(False)
    if hasattr(cfg, "set_p21_dynamic_strawberry_allocation_enabled"):
        cfg.set_p21_dynamic_strawberry_allocation_enabled(False)
    if hasattr(cfg, "set_p22a_day28_feed_harmonization_enabled"):
        cfg.set_p22a_day28_feed_harmonization_enabled(False)
    if hasattr(cfg, "set_p23_marginal_wheat_allocation_enabled"):
        cfg.set_p23_marginal_wheat_allocation_enabled(True)
    if hasattr(cfg, "set_p31_state_dependent_harvest_priority_enabled"):
        cfg.set_p31_state_dependent_harvest_priority_enabled(False)
    if hasattr(cfg, "set_p32_state_dependent_care_priority_enabled"):
        cfg.set_p32_state_dependent_care_priority_enabled(False)

    # Set P3.3-A physical locality switch
    expected_p33 = (arm == "Treatment")
    if hasattr(cfg, "set_p33_physical_locality"):
        cfg.set_p33_physical_locality(expected_p33, 6)
    else:
        setattr(cfg, "P33_PHYSICAL_LOCALITY_ENABLED", expected_p33)
        setattr(cfg, "P33_PHYSICAL_SWITCH_PENALTY", 6)

    # Invariants verification
    assert cfg.QUADRANT_HARD_BLOCK == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    assert getattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", False) is True, f"{arm}: P23 must be True"
    actual_p33 = getattr(cfg, "P33_PHYSICAL_LOCALITY_ENABLED", False)
    assert actual_p33 == expected_p33, f"{arm}: P3.3 expected {expected_p33}, got {actual_p33}"


def _get_quadrant(pos):
    x, y = pos
    if x < 5 and y < 5:
        return "NW"
    elif x >= 5 and y < 5:
        return "NE"
    elif x < 5 and y >= 5:
        return "SW"
    else:
        return "SE"


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner"
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
            "movement_turns": 0,
            "idle_turns": 0,
            "cross_quadrant_transitions": 0,
            "productive_actions": 0,
            "water_actions_total": 0,
            "water_by_crop": defaultdict(int),
            "harvest_actions_total": 0,
            "care_actions_completed": 0,
            "feed_actions_completed": 0,
            "missed_watering_eod": 0,
            "missed_feedings_eod": 0,
            "plant_deaths": 0,
            "prev_unit_positions": {},
        }

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            player = int(obs.get("player", task["seat"]))
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}

            # End of Day audit at Hour 23
            if hour == 23:
                tiles_grid = farm.get("tiles", []) or []
                for row in tiles_grid:
                    for t in row or []:
                        if isinstance(t, dict):
                            kind = t.get("kind")
                            if kind == "PLANT":
                                if not t.get("watered_today", False):
                                    telemetry["missed_watering_eod"] += 1
                                if t.get("consecutive_unwatered", 0) >= 1:
                                    telemetry["plant_deaths"] += 1
                            elif t.get("animal") or t.get("is_animal"):
                                if not t.get("fed_today", False):
                                    telemetry["missed_feedings_eod"] += 1

            # Update current unit positions before agent action
            farmer_pos = tuple(farm.get("farmer", [4, 4]))
            hands_list = [tuple(h) for h in (farm.get("hands", []) or [])]
            current_unit_positions = [farmer_pos] + hands_list

            # Check cross-quadrant transitions from previous turn
            prev_positions = telemetry["prev_unit_positions"]
            if prev_positions:
                for u_idx, curr_pos in enumerate(current_unit_positions):
                    if u_idx in prev_positions:
                        prev_pos = prev_positions[u_idx]
                        if prev_pos != curr_pos:
                            if _get_quadrant(prev_pos) != _get_quadrant(curr_pos):
                                telemetry["cross_quadrant_transitions"] += 1

            # Save positions for next turn comparison
            telemetry["prev_unit_positions"] = {u_idx: pos for u_idx, pos in enumerate(current_unit_positions)}

            action = module.agent(obs, configuration) or {}

            # Action classification
            if isinstance(action, dict):
                farmer_act = action.get("farmer", ["PASS"])
                hands_acts = action.get("hands", [])
                all_acts = [farmer_act] + hands_acts

                for u_idx, u_act in enumerate(all_acts):
                    op = u_act[0] if isinstance(u_act, (list, tuple)) and len(u_act) > 0 else "PASS"
                    if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                        telemetry["movement_turns"] += 1
                    elif op == "PASS":
                        telemetry["idle_turns"] += 1
                    elif op in ("WATER", "HARVEST", "CARE", "FEED", "PLANT", "FERTILIZE", "DIG", "COLLECT_FERTILIZER"):
                        telemetry["productive_actions"] += 1
                        if op == "WATER":
                            telemetry["water_actions_total"] += 1
                            # Check crop type at target
                            if len(u_act) >= 3:
                                tx, ty = int(u_act[1]), int(u_act[2])
                                tiles_grid = farm.get("tiles", [])
                                if 0 <= ty < len(tiles_grid) and 0 <= tx < len(tiles_grid[ty]):
                                    t = tiles_grid[ty][tx]
                                    crop_name = t.get("crop", "UNKNOWN") if isinstance(t, dict) else "UNKNOWN"
                                    telemetry["water_by_crop"][crop_name] += 1
                        elif op == "HARVEST":
                            telemetry["harvest_actions_total"] += 1
                        elif op == "CARE":
                            telemetry["care_actions_completed"] += 1
                        elif op == "FEED":
                            telemetry["feed_actions_completed"] += 1

            return action

        opp = get_agent(task["opponent"])
        agents = [tracking, opp] if task["seat"] == 0 else [opp, tracking]
        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": task["seed"]})
        env.run(agents)

        f_raw = env.state[task["seat"]]["observation"]["farms"][task["seat"]]["money"]
        score = float(f_raw)

        return {
            "pair_id": task["pair_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "arm": task["arm"],
            "seat": task["seat"],
            "score": score,
            "movement_turns": telemetry["movement_turns"],
            "idle_turns": telemetry["idle_turns"],
            "cross_quadrant_transitions": telemetry["cross_quadrant_transitions"],
            "productive_actions": telemetry["productive_actions"],
            "water_actions_total": telemetry["water_actions_total"],
            "water_by_crop": dict(telemetry["water_by_crop"]),
            "harvest_actions_total": telemetry["harvest_actions_total"],
            "care_actions_completed": telemetry["care_actions_completed"],
            "feed_actions_completed": telemetry["feed_actions_completed"],
            "missed_watering_eod": telemetry["missed_watering_eod"],
            "missed_feedings_eod": telemetry["missed_feedings_eod"],
            "plant_deaths": telemetry["plant_deaths"],
            "error": None,
        }
    except Exception as e:
        return {
            "pair_id": task["pair_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "arm": task["arm"],
            "seat": task["seat"],
            "score": 0.0,
            "movement_turns": 0,
            "idle_turns": 0,
            "cross_quadrant_transitions": 0,
            "productive_actions": 0,
            "water_actions_total": 0,
            "water_by_crop": {},
            "harvest_actions_total": 0,
            "care_actions_completed": 0,
            "feed_actions_completed": 0,
            "missed_watering_eod": 0,
            "missed_feedings_eod": 0,
            "plant_deaths": 0,
            "error": str(e) + "\n" + traceback.format_exc(),
        }


def main():
    is_smoke = "--smoke" in sys.argv
    scenarios = SCENARIOS_SMOKE if is_smoke else SCENARIOS_EVAL
    mode_name = "SMOKE (Seeds 92,991–92,995)" if is_smoke else "EVALUATION (Seeds 93,001–93,050)"

    print(f"=== Kaggriculture P3.3-A Experiment Runner: {mode_name} ===", flush=True)
    head_sha = _git_sha("HEAD")
    base_sha = _git_sha(BASELINE_SHA)
    print(f"Baseline Commit:  {base_sha} (536f1e7 Promoted P2.3)")
    print(f"Treatment Commit: {head_sha} (Worktree P3.3-A Physical Locality)")

    control_dir = _extract_control_agent(base_sha)
    temp_worktree = tempfile.mkdtemp(prefix="kagg_p33_worktree_")
    worktree_dir, manifest, manifest_hash = _snapshot_worktree_agent(temp_worktree)
    print(f"Control directory:   {control_dir}")
    print(f"Worktree directory:  {worktree_dir}")
    print(f"Worktree SHA256:     {manifest_hash}")

    tasks = []
    for sc in scenarios:
        for seat in (0, 1):
            for arm in ARMS:
                tasks.append({
                    "pair_id": sc["pair_id"],
                    "seed": sc["seed"],
                    "opponent": sc["opponent"],
                    "arm": arm,
                    "seat": seat,
                    "agent_dir": control_dir if arm == "Control" else worktree_dir,
                })

    n_games = len(tasks)
    n_matched = n_games // 2
    print(f"Scheduled {n_games} games ({n_matched} matched cases across {len(scenarios)} scenarios x 2 seats)", flush=True)

    t0 = time.time()
    results = []
    max_workers = min(os.cpu_count() or 4, 8)
    print(f"Launching ProcessPoolExecutor with {max_workers} worker processes...", flush=True)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_one, t): t for t in tasks}
        completed = 0
        for f in as_completed(futures):
            res = f.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == n_games:
                elapsed = time.time() - t0
                rate = completed / max(1.0, elapsed)
                print(f"[{completed}/{n_games}] games completed ({rate:.2f} games/s, elapsed {elapsed:.1f}s)", flush=True)

    try:
        shutil.rmtree(temp_worktree, ignore_errors=True)
    except Exception:
        pass

    # Process and reconcile matched cases
    cases = defaultdict(dict)
    for r in results:
        key = (r["pair_id"], r["seed"], r["opponent"], r["seat"])
        cases[key][r["arm"]] = r

    valid_cases = []
    errors = 0
    for key, arm_dict in cases.items():
        if "Control" in arm_dict and "Treatment" in arm_dict:
            ctrl = arm_dict["Control"]
            trt = arm_dict["Treatment"]
            if ctrl.get("error") or trt.get("error"):
                errors += 1
                continue
            delta_score = trt["score"] - ctrl["score"]
            delta_moves = trt["movement_turns"] - ctrl["movement_turns"]
            delta_idle = trt["idle_turns"] - ctrl["idle_turns"]
            delta_quad_cross = trt["cross_quadrant_transitions"] - ctrl["cross_quadrant_transitions"]
            delta_prod = trt["productive_actions"] - ctrl["productive_actions"]
            delta_water = trt["water_actions_total"] - ctrl["water_actions_total"]
            delta_harvest = trt["harvest_actions_total"] - ctrl["harvest_actions_total"]
            delta_care = trt["care_actions_completed"] - ctrl["care_actions_completed"]
            delta_feed = trt["feed_actions_completed"] - ctrl["feed_actions_completed"]
            delta_unwatered = trt["missed_watering_eod"] - ctrl["missed_watering_eod"]

            valid_cases.append({
                "case_key": list(key),
                "ctrl_score": ctrl["score"],
                "trt_score": trt["score"],
                "delta_score": delta_score,
                "ctrl_moves": ctrl["movement_turns"],
                "trt_moves": trt["movement_turns"],
                "delta_moves": delta_moves,
                "ctrl_idle": ctrl["idle_turns"],
                "trt_idle": trt["idle_turns"],
                "delta_idle": delta_idle,
                "ctrl_cross": ctrl["cross_quadrant_transitions"],
                "trt_cross": trt["cross_quadrant_transitions"],
                "delta_cross": delta_quad_cross,
                "ctrl_prod": ctrl["productive_actions"],
                "trt_prod": trt["productive_actions"],
                "delta_prod": delta_prod,
                "ctrl_water": ctrl["water_actions_total"],
                "trt_water": trt["water_actions_total"],
                "delta_water": delta_water,
                "ctrl_harvest": ctrl["harvest_actions_total"],
                "trt_harvest": trt["harvest_actions_total"],
                "delta_harvest": delta_harvest,
                "ctrl_care": ctrl["care_actions_completed"],
                "trt_care": trt["care_actions_completed"],
                "delta_care": delta_care,
                "ctrl_feed": ctrl["feed_actions_completed"],
                "trt_feed": trt["feed_actions_completed"],
                "delta_feed": delta_feed,
                "ctrl_unwatered": ctrl["missed_watering_eod"],
                "trt_unwatered": trt["missed_watering_eod"],
                "delta_unwatered": delta_unwatered,
            })

    print(f"\nCompleted {len(valid_cases)} valid matched cases (errors: {errors}) in {time.time() - t0:.1f}s")
    if not valid_cases:
        print("ERROR: No valid matched cases!")
        return

    scores_ctrl = [c["ctrl_score"] for c in valid_cases]
    scores_trt = [c["trt_score"] for c in valid_cases]
    deltas = [c["delta_score"] for c in valid_cases]
    moves_elim = [-c["delta_moves"] for c in valid_cases]  # positive when movement reduced
    prod_gained = [c["delta_prod"] for c in valid_cases]

    n = len(deltas)
    mean_ctrl = statistics.mean(scores_ctrl)
    mean_trt = statistics.mean(scores_trt)
    mean_delta = statistics.mean(deltas)
    median_delta = statistics.median(deltas)
    std_delta = statistics.stdev(deltas) if n > 1 else 0.0
    se_delta = std_delta / math.sqrt(n) if n > 1 else 0.0
    ci95 = (mean_delta - 1.96 * se_delta, mean_delta + 1.96 * se_delta)

    t_stat = (mean_delta / se_delta) if se_delta > 0 else 0.0
    # Approximate two-tailed p-value using standard normal approximation for n >= 30
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))

    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    ties = sum(1 for d in deltas if d == 0)

    mean_ctrl_moves = statistics.mean(c["ctrl_moves"] for c in valid_cases)
    mean_trt_moves = statistics.mean(c["trt_moves"] for c in valid_cases)
    mean_delta_moves = statistics.mean(c["delta_moves"] for c in valid_cases)

    mean_ctrl_idle = statistics.mean(c["ctrl_idle"] for c in valid_cases)
    mean_trt_idle = statistics.mean(c["trt_idle"] for c in valid_cases)
    mean_delta_idle = statistics.mean(c["delta_idle"] for c in valid_cases)

    mean_ctrl_cross = statistics.mean(c["ctrl_cross"] for c in valid_cases)
    mean_trt_cross = statistics.mean(c["trt_cross"] for c in valid_cases)
    mean_delta_cross = statistics.mean(c["delta_cross"] for c in valid_cases)

    mean_ctrl_prod = statistics.mean(c["ctrl_prod"] for c in valid_cases)
    mean_trt_prod = statistics.mean(c["trt_prod"] for c in valid_cases)
    mean_delta_prod = statistics.mean(c["delta_prod"] for c in valid_cases)

    mean_ctrl_water = statistics.mean(c["ctrl_water"] for c in valid_cases)
    mean_trt_water = statistics.mean(c["trt_water"] for c in valid_cases)
    mean_delta_water = statistics.mean(c["delta_water"] for c in valid_cases)

    mean_ctrl_unwatered = statistics.mean(c["ctrl_unwatered"] for c in valid_cases)
    mean_trt_unwatered = statistics.mean(c["trt_unwatered"] for c in valid_cases)
    mean_delta_unwatered = statistics.mean(c["delta_unwatered"] for c in valid_cases)

    tot_moves_elim = sum(moves_elim)
    tot_prod_gained = sum(prod_gained)
    tot_score_gained = sum(deltas)

    conv_rate = (tot_prod_gained / tot_moves_elim) if tot_moves_elim != 0 else 0.0
    score_yield = (tot_score_gained / tot_moves_elim) if tot_moves_elim != 0 else 0.0

    print("\n" + "=" * 60)
    print(f"=== P3.3-A TOURNAMENT RESULTS ({n} MATCHED CASES) ===")
    print("=" * 60)
    print(f"Control Baseline Mean:      ${mean_ctrl:,.2f}")
    print(f"Treatment (P3.3-A) Mean:    ${mean_trt:,.2f}")
    print(f"Mean Paired Delta:          ${mean_delta:+,.2f}/game")
    print(f"Median Paired Delta:        ${median_delta:+,.2f}/game")
    print(f"Standard Error:             ${se_delta:,.2f}")
    print(f"95% Confidence Interval:    [${ci95[0]:+,.2f}, ${ci95[1]:+,.2f}]")
    print(f"Paired t-statistic:         t = {t_stat:.4f}, p = {p_val:.4f}")
    print(f"Record (W / L / T):         {wins}W / {losses}L / {ties}T ({wins/n*100:.1f}% win rate)")
    print("-" * 60)
    print("=== TELEMETRY & CAUSAL CHAIN ===")
    print(f"Movement Turns:             Ctrl={mean_ctrl_moves:.1f} | Trt={mean_trt_moves:.1f} | Delta={mean_delta_moves:+.1f}")
    print(f"Idle Turns:                 Ctrl={mean_ctrl_idle:.1f} | Trt={mean_trt_idle:.1f} | Delta={mean_delta_idle:+.1f}")
    print(f"Cross-Quadrant Moves:       Ctrl={mean_ctrl_cross:.1f} | Trt={mean_trt_cross:.1f} | Delta={mean_delta_cross:+.1f}")
    print(f"Productive Actions:         Ctrl={mean_ctrl_prod:.1f} | Trt={mean_trt_prod:.1f} | Delta={mean_delta_prod:+.1f}")
    print(f"Watering Actions:           Ctrl={mean_ctrl_water:.1f} | Trt={mean_trt_water:.1f} | Delta={mean_delta_water:+.1f}")
    print(f"Missed Watering at EOD:     Ctrl={mean_ctrl_unwatered:.1f} | Trt={mean_trt_unwatered:.1f} | Delta={mean_delta_unwatered:+.1f}")
    print("-" * 60)
    print("=== MONETIZATION ACCOUNTING ===")
    print(f"Movement Turns Eliminated:  {-mean_delta_moves:+.1f} turns/game (vs ~857 candidate)")
    print(f"Conversion Rate:            {conv_rate:.4f} productive actions / eliminated turn")
    print(f"Score Yield:                ${score_yield:+.2f} / eliminated turn")
    print("=" * 60)

    out_json = os.path.join(ROOT, "simulations", "experiments", "results", "p33_physical_locality_ab.json" if not is_smoke else "p33_smoke.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    summary_data = {
        "mode": "smoke" if is_smoke else "eval",
        "n_cases": n,
        "mean_ctrl": mean_ctrl,
        "mean_trt": mean_trt,
        "mean_delta": mean_delta,
        "median_delta": median_delta,
        "se_delta": se_delta,
        "ci95": list(ci95),
        "t_stat": t_stat,
        "p_val": p_val,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "telemetry": {
            "ctrl_moves": mean_ctrl_moves,
            "trt_moves": mean_trt_moves,
            "delta_moves": mean_delta_moves,
            "ctrl_idle": mean_ctrl_idle,
            "trt_idle": mean_trt_idle,
            "delta_idle": mean_delta_idle,
            "ctrl_cross": mean_ctrl_cross,
            "trt_cross": mean_trt_cross,
            "delta_cross": mean_delta_cross,
            "ctrl_prod": mean_ctrl_prod,
            "trt_prod": mean_trt_prod,
            "delta_prod": mean_delta_prod,
            "ctrl_water": mean_ctrl_water,
            "trt_water": mean_trt_water,
            "delta_water": mean_delta_water,
            "ctrl_unwatered": mean_ctrl_unwatered,
            "trt_unwatered": mean_trt_unwatered,
            "delta_unwatered": mean_delta_unwatered,
            "conv_rate": conv_rate,
            "score_yield": score_yield,
        },
        "cases": valid_cases,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"Results saved to: {out_json}")


if __name__ == "__main__":
    main()
