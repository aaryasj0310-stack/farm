#!/usr/bin/env python3
"""P3.1 State-Dependent Harvest Priority Escalation Experiment Runner.

Evaluates Promoted Production Baseline (536f1e7..., QUADRANT_HARD_BLOCK={4}, P23=True)
vs P3.1 State-Dependent Harvest Priority Escalation (P31_STATE_DEPENDENT_HARVEST_PRIORITY_ENABLED=True).

100 matched cases (50 pairs x 2 seats = 200 live games).
Fresh seed block: 91,001–91,050.
Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent.
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

# Fresh seed block: 91,001+
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 91001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(50)  # 50 pairs x 2 seats = 100 matched cases (200 games)
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
    out_dir = os.path.join(tempfile.gettempdir(), f"kagg_p31_control_{commit_sha[:8]}")
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
    """Enforce strict 2Q invariants and set P3.1 flag."""
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

    # Set P3.1 switch
    expected_p31 = (arm == "Treatment")
    if hasattr(cfg, "set_p31_state_dependent_harvest_priority_enabled"):
        cfg.set_p31_state_dependent_harvest_priority_enabled(expected_p31)
    else:
        setattr(cfg, "P31_STATE_DEPENDENT_HARVEST_PRIORITY_ENABLED", expected_p31)

    # Assertions
    assert cfg.QUADRANT_HARD_BLOCK == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    assert getattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", False) is True, f"{arm}: P23 must be True"
    actual_p31 = getattr(cfg, "P31_STATE_DEPENDENT_HARVEST_PRIORITY_ENABLED", False)
    assert actual_p31 == expected_p31, f"{arm}: P3.1 expected {expected_p31}, got {actual_p31}"


def _verify_manifest(control_dir, worktree_dir):
    for arm, d in (("Control", control_dir), ("Treatment", worktree_dir)):
        for k in list(sys.modules):
            if any(k == m or k.startswith(m + ".") for m in ("config", "main", "macro_planner", "market_brain", "central_planner", "task_scheduler")):
                del sys.modules[k]
        sys.path.insert(0, d)
        import config as cfg
        _configure_arm(cfg, arm)
        print(f"Verified {arm} config: QUADRANT_HARD_BLOCK={cfg.QUADRANT_HARD_BLOCK}, P23={getattr(cfg, 'P23_MARGINAL_WHEAT_ALLOCATION_ENABLED', False)}, P31={getattr(cfg, 'P31_STATE_DEPENDENT_HARVEST_PRIORITY_ENABLED', False)}", flush=True)


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

        m = {
            "negative_cash_steps": 0, "cash_min": float("inf"),
            "daily_cash": {},
            "unwatered_eod": {"NW": 0, "NE": 0},
            "decayed_crop_units": 0,
            "decayed_crop_dollars": 0.0,
            "missed_watering_units": 0,
            "missed_watering_dollars": 0.0,
            "plant_deaths_count": 0,
            "plant_deaths_dollars": 0.0,
            "strawberry_harvest_units": 0,
            "strawberry_revenue": 0.0,
            "wheat_harvest_units": 0,
            "wheat_revenue": 0.0,
            "carrot_harvest_units": 0,
            "carrot_revenue": 0.0,
            "melon_harvest_units": 0,
            "melon_revenue": 0.0,
            "movement_turns": 0,
            "crop_action_turns": 0,
            "animal_action_turns": 0,
            "logistics_turns": 0,
            "idle_turns": 0,
            "starvation_animal_days": 0,
            "starvation_animal_hours": 0,
            "animal_care_missed_count": 0,
            "crop_revenue": 0.0,
            "animal_revenue": 0.0,
        }

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            step = int(obs.get("step", day * 24 + hour))
            player = int(obs.get("player", task["seat"]))
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}
            money = float(farm.get("money", 0.0))
            private = obs.get("private", {})

            if money < 0:
                m["negative_cash_steps"] += 1
            if money < m["cash_min"]:
                m["cash_min"] = money

            for row in farm.get("tiles", []) or []:
                for t in row or []:
                    if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                        if int(t.get("consecutive_unfed", 0) or 0) >= 1:
                            m["starvation_animal_hours"] += 1

            # End of Day audit at Hour 23
            if hour == 23:
                m["daily_cash"][day] = money
                tiles_grid = farm.get("tiles", []) or []
                for y, row in enumerate(tiles_grid):
                    for x, t in enumerate(row or []):
                        if isinstance(t, dict):
                            pos = (x, y)
                            kind = t.get("kind")
                            if kind == "PLANT":
                                q = ("N" if y < 5 else "S") + ("W" if x < 5 else "E")
                                watered = t.get("watered_today", False)
                                if q in m["unwatered_eod"] and not watered:
                                    m["unwatered_eod"][q] += 1
                                crop = t.get("crop")
                                spec = CROP_SPECS.get(crop, {})
                                planted_day = t.get("planted_day", 0)
                                age = day - planted_day
                                consec_unwatered = t.get("consecutive_unwatered", 0)

                                if not watered:
                                    if spec.get("ongoing"):
                                        m["missed_watering_units"] += 1
                                        m["missed_watering_dollars"] += spec.get("price", 120.0)
                                    else:
                                        window_start = (spec.get("max_yield_day", 4) + 1) // 2
                                        if window_start <= age <= spec.get("max_yield_day", 4):
                                            fert = t.get("fertilized_until_day", -1) >= day
                                            bonus = 2 if fert else 1
                                            m["missed_watering_units"] += bonus
                                            m["missed_watering_dollars"] += bonus * spec.get("price", 25.0)

                                    if consec_unwatered >= 1:
                                        m["plant_deaths_count"] += 1
                                        net_loss = (spec.get("max_yield", 4) * spec.get("price", 25.0)) - spec.get("seed", 10)
                                        m["plant_deaths_dollars"] += net_loss

                                # Decay check
                                if not spec.get("ongoing") and age > spec.get("max_yield_day", 4):
                                    yield_u = t.get("yield_units", 0)
                                    if yield_u > 0:
                                        m["decayed_crop_units"] += 1
                                        m["decayed_crop_dollars"] += spec.get("price", 25.0)

                            elif t.get("animal") or t.get("is_animal"):
                                fed = t.get("fed_today", False)
                                cared = t.get("cared_today", False)
                                if not fed:
                                    m["starvation_animal_days"] += 1
                                if not cared and t.get("animal") in ("COW", "SHEEP"):
                                    m["animal_care_missed_count"] += 1

            action = module.agent(obs, configuration) or {}

            # Action accounting
            if isinstance(action, dict):
                hands_list = farm.get("hands", []) or []
                n_active_units = 1 + len(hands_list)
                farmer_act = action.get("farmer", ["PASS"])
                hands_acts = action.get("hands", [])

                for u_idx in range(n_active_units):
                    if u_idx == 0:
                        act = farmer_act
                    else:
                        act = hands_acts[u_idx - 1] if (u_idx - 1) < len(hands_acts) else ["PASS"]
                    op = act[0] if isinstance(act, (list, tuple)) and len(act) > 0 else "PASS"

                    if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                        m["movement_turns"] += 1
                    elif op in ("PLANT", "WATER", "FERTILIZE"):
                        m["crop_action_turns"] += 1
                    elif op == "HARVEST":
                        # Check what is on this tile
                        u_pos = tuple(farm.get("farmer", [4, 4])) if u_idx == 0 else tuple(hands_list[u_idx - 1])
                        tiles_grid = farm.get("tiles", [])
                        tile_at = None
                        if 0 <= u_pos[1] < len(tiles_grid) and 0 <= u_pos[0] < len(tiles_grid[u_pos[1]]):
                            tile_at = tiles_grid[u_pos[1]][u_pos[0]]
                        if isinstance(tile_at, dict):
                            if tile_at.get("kind") == "PLANT":
                                m["crop_action_turns"] += 1
                                crop = tile_at.get("crop")
                                units = tile_at.get("yield_units", 0)
                                if crop == "STRAWBERRY":
                                    m["strawberry_harvest_units"] += units
                                elif crop == "WHEAT":
                                    m["wheat_harvest_units"] += units
                                elif crop == "CARROT":
                                    m["carrot_harvest_units"] += units
                                elif crop == "MELON":
                                    m["melon_harvest_units"] += units
                            else:
                                m["animal_action_turns"] += 1
                        else:
                            m["idle_turns"] += 1
                    elif op in ("FEED", "CARE", "COLLECT_FERTILIZER", "BUILD_COOP", "BUILD_PASTURE"):
                        m["animal_action_turns"] += 1
                    elif op in ("PICKUP", "DROP"):
                        m["logistics_turns"] += 1
                    else:
                        m["idle_turns"] += 1

                for ord_item in action.get("market", []):
                    if isinstance(ord_item, (list, tuple)) and len(ord_item) >= 3:
                        op = ord_item[0]
                        prod = ord_item[1]
                        qty = int(ord_item[2])
                        market_inv = obs.get("market", {}).get("inventory", {})
                        inv_val = float(market_inv.get(prod, 10000.0))
                        px = cfg.market_price(prod, inv_val) if hasattr(cfg, "market_price") else 25.0

                        if op == "SELL":
                            rev = qty * px
                            if prod == "STRAWBERRY":
                                m["strawberry_revenue"] += rev
                                m["crop_revenue"] += rev
                            elif prod == "WHEAT":
                                m["wheat_revenue"] += rev
                                m["crop_revenue"] += rev
                            elif prod == "CARROT":
                                m["carrot_revenue"] += rev
                                m["crop_revenue"] += rev
                            elif prod in ("MELON", "TOMATO"):
                                m["crop_revenue"] += rev
                                if prod == "MELON":
                                    m["melon_revenue"] += rev
                            elif prod in ("MILK", "WOOL", "EGG", "FERTILIZER"):
                                m["animal_revenue"] += rev

            return action

        opp = get_agent(task["opponent"])
        agents = [tracking, opp] if task["seat"] == 0 else [opp, tracking]
        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": task["seed"]})
        env.run(agents)

        f_raw = env.state[task["seat"]]["observation"]["farms"][task["seat"]]["money"]
        score = float(f_raw)

        return {
            "scenario": task["scenario"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "arm": task["arm"],
            "seat": task["seat"],
            "score": score,
            "crop_decay_units": m["decayed_crop_units"],
            "crop_decay_dollars": m["decayed_crop_dollars"],
            "strawberry_harvest_units": m["strawberry_harvest_units"],
            "strawberry_revenue": m["strawberry_revenue"],
            "wheat_harvest_units": m["wheat_harvest_units"],
            "wheat_revenue": m["wheat_revenue"],
            "carrot_harvest_units": m["carrot_harvest_units"],
            "carrot_revenue": m["carrot_revenue"],
            "melon_harvest_units": m["melon_harvest_units"],
            "melon_revenue": m["melon_revenue"],
            "missed_watering_units": m["missed_watering_units"],
            "missed_watering_dollars": m["missed_watering_dollars"],
            "plant_deaths_count": m["plant_deaths_count"],
            "plant_deaths_dollars": m["plant_deaths_dollars"],
            "starvation_animal_hours": m["starvation_animal_hours"],
            "starvation_animal_days": m["starvation_animal_days"],
            "animal_care_missed_count": m["animal_care_missed_count"],
            "movement_turns": m["movement_turns"],
            "crop_action_turns": m["crop_action_turns"],
            "animal_action_turns": m["animal_action_turns"],
            "logistics_turns": m["logistics_turns"],
            "idle_turns": m["idle_turns"],
            "crop_revenue": m["crop_revenue"],
            "animal_revenue": m["animal_revenue"],
            "cash_min": m["cash_min"],
            "negative_cash_steps": m["negative_cash_steps"],
            "error": None,
        }
    except Exception as e:
        return {
            "scenario": task["scenario"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "arm": task["arm"],
            "seat": task["seat"],
            "score": 0.0,
            "error": f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
        }


def run_experiment(num_workers: int = 8, pairs_limit: int = None):
    temp_dir = tempfile.mkdtemp(prefix="kagg_p31_exp_")
    print(f"P3.1 Experiment starting in {temp_dir}", flush=True)

    head_sha = _git_sha("HEAD")
    print(f"Control SHA: {BASELINE_SHA}")
    print(f"Treatment Head SHA: {head_sha}")

    control_dir = _extract_control_agent(BASELINE_SHA)
    worktree_dir, manifest, manifest_hash = _snapshot_worktree_agent(temp_dir)
    print(f"Snapshot worktree: {len(manifest)} files, hash {manifest_hash[:12]}")

    _verify_manifest(control_dir, worktree_dir)

    scenarios = SCENARIOS[:pairs_limit] if pairs_limit else SCENARIOS
    tasks = []
    for sc in scenarios:
        for seat in (0, 1):
            tasks.append({
                "scenario": sc["pair_id"],
                "seed": sc["seed"],
                "opponent": sc["opponent"],
                "seat": seat,
                "arm": "Control",
                "agent_dir": control_dir,
            })
            tasks.append({
                "scenario": sc["pair_id"],
                "seed": sc["seed"],
                "opponent": sc["opponent"],
                "seat": seat,
                "arm": "Treatment",
                "agent_dir": worktree_dir,
            })

    total_games = len(tasks)
    matched_pairs = total_games // 2
    print(f"Running {matched_pairs} matched cases ({total_games} games) with {num_workers} workers...", flush=True)

    results_by_arm = defaultdict(list)
    paired_runs = defaultdict(dict)
    errors = []

    start_time = time.time()
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(_one, t): t for t in tasks}
        completed = 0
        for f in as_completed(futures):
            completed += 1
            res = f.result()
            if res.get("error"):
                errors.append(res)
                print(f"[{completed}/{total_games}] ERROR in {res['arm']} seed {res['seed']}: {res['error']}", flush=True)
            else:
                arm = res["arm"]
                results_by_arm[arm].append(res)
                key = (res["scenario"], res["seed"], res["seat"])
                paired_runs[key][arm] = res
                if completed % 10 == 0 or completed == total_games:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(f"[{completed}/{total_games}] ({rate:.1f} games/s) completed. Arm counts: Control={len(results_by_arm['Control'])}, Treatment={len(results_by_arm['Treatment'])}", flush=True)

    elapsed_total = time.time() - start_time
    print(f"All {completed} games finished in {elapsed_total:.1f}s", flush=True)

    # Statistical Evaluation
    paired_deltas = []
    ctrl_scores, treat_scores = [], []
    ctrl_decay_units, treat_decay_units = [], []
    ctrl_decay_dollars, treat_decay_dollars = [], []
    ctrl_straw_yield, treat_straw_yield = [], []
    ctrl_straw_rev, treat_straw_rev = [], []
    ctrl_missed_water, treat_missed_water = [], []
    wins, losses, ties = 0, 0, 0

    opp_stats = defaultdict(lambda: {"deltas": [], "wins": 0, "losses": 0, "ties": 0})
    seat_stats = defaultdict(lambda: {"deltas": [], "wins": 0, "losses": 0, "ties": 0})

    for key, arm_dict in sorted(paired_runs.items()):
        if "Control" in arm_dict and "Treatment" in arm_dict:
            c = arm_dict["Control"]
            t = arm_dict["Treatment"]
            sc_c = c["score"]
            sc_t = t["score"]
            delta = sc_t - sc_c
            paired_deltas.append(delta)
            ctrl_scores.append(sc_c)
            treat_scores.append(sc_t)

            ctrl_decay_units.append(c["crop_decay_units"])
            treat_decay_units.append(t["crop_decay_units"])
            ctrl_decay_dollars.append(c["crop_decay_dollars"])
            treat_decay_dollars.append(t["crop_decay_dollars"])

            ctrl_straw_yield.append(c["strawberry_harvest_units"])
            treat_straw_yield.append(t["strawberry_harvest_units"])
            ctrl_straw_rev.append(c["strawberry_revenue"])
            treat_straw_rev.append(t["strawberry_revenue"])

            ctrl_missed_water.append(c["missed_watering_units"])
            treat_missed_water.append(t["missed_watering_units"])

            opp = c["opponent"]
            seat = c["seat"]
            opp_stats[opp]["deltas"].append(delta)
            seat_stats[seat]["deltas"].append(delta)

            if delta > 1e-4:
                wins += 1
                opp_stats[opp]["wins"] += 1
                seat_stats[seat]["wins"] += 1
            elif delta < -1e-4:
                losses += 1
                opp_stats[opp]["losses"] += 1
                seat_stats[seat]["losses"] += 1
            else:
                ties += 1
                opp_stats[opp]["ties"] += 1
                seat_stats[seat]["ties"] += 1

    n = len(paired_deltas)
    if n == 0:
        print("ERROR: No matched cases completed successfully!")
        return

    mean_c = statistics.mean(ctrl_scores)
    mean_t = statistics.mean(treat_scores)
    mean_delta = statistics.mean(paired_deltas)
    median_delta = statistics.median(paired_deltas)
    std_delta = statistics.stdev(paired_deltas) if n > 1 else 0.0
    se_delta = std_delta / math.sqrt(n) if n > 1 else 0.0

    # 95% Confidence Interval (t-distribution critical value approx 1.984 for df=99)
    tcrit = 1.984 if n >= 100 else 2.0
    ci_lower = mean_delta - tcrit * se_delta
    ci_upper = mean_delta + tcrit * se_delta
    t_stat = mean_delta / se_delta if se_delta > 0 else 0.0

    # Two-tailed p-value approximation via standard normal / t
    from scipy import stats as sp_stats
    try:
        p_val = float(sp_stats.ttest_1samp(paired_deltas, 0.0).pvalue)
    except Exception:
        # Fallback normal approx
        p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))

    print("\n" + "=" * 78)
    print(f"  P3.1 EXPERIMENT RESULTS: 100 MATCHED CASES ({total_games} GAMES)")
    print("=" * 78)
    print(f"Control Baseline (536f1e7) Mean : ${mean_c:,.2f}")
    print(f"Treatment (P3.1 Escalation) Mean: ${mean_t:,.2f}")
    print(f"Mean Paired Delta                : +${mean_delta:,.2f}/game" if mean_delta >= 0 else f"Mean Paired Delta                : -${abs(mean_delta):,.2f}/game")
    print(f"Median Paired Delta              : +${median_delta:,.2f}/game" if median_delta >= 0 else f"Median Paired Delta              : -${abs(median_delta):,.2f}/game")
    print(f"Std Dev of Paired Delta          : ${std_delta:,.2f}")
    print(f"Standard Error of Delta          : ${se_delta:,.2f}")
    print(f"95% Confidence Interval          : [${ci_lower:,.2f}, ${ci_upper:,.2f}]")
    print(f"Paired t-statistic               : t = {t_stat:.4f} (p = {p_val:.4e})")
    print(f"Record (W / L / T)               : {wins}W / {losses}L / {ties}T ({wins/n*100:.1f}% Win Rate)")

    print("\n--- Physical Mechanism Telemetry ---")
    mean_c_decay = statistics.mean(ctrl_decay_dollars)
    mean_t_decay = statistics.mean(treat_decay_dollars)
    decay_delta = mean_t_decay - mean_c_decay
    print(f"Crop Decay Losses  : Control=${mean_c_decay:,.2f} -> Treatment=${mean_t_decay:,.2f} (Delta: ${decay_delta:,.2f}/game)")

    mean_c_straw = statistics.mean(ctrl_straw_yield)
    mean_t_straw = statistics.mean(treat_straw_yield)
    print(f"Strawberry Yield   : Control={mean_c_straw:.1f} units -> Treatment={mean_t_straw:.1f} units (Delta: +{mean_t_straw - mean_c_straw:.1f} units)")

    mean_c_straw_rev = statistics.mean(ctrl_straw_rev)
    mean_t_straw_rev = statistics.mean(treat_straw_rev)
    print(f"Strawberry Revenue : Control=${mean_c_straw_rev:,.2f} -> Treatment=${mean_t_straw_rev:,.2f} (Delta: +${mean_t_straw_rev - mean_c_straw_rev:,.2f})")

    mean_c_mwater = statistics.mean(ctrl_missed_water)
    mean_t_mwater = statistics.mean(treat_missed_water)
    print(f"Missed Water Bonus : Control={mean_c_mwater:.1f} -> Treatment={mean_t_mwater:.1f} (Delta: {mean_t_mwater - mean_c_mwater:+.1f})")

    print("\n--- Opponent Breakdown ---")
    for opp, odata in sorted(opp_stats.items()):
        odeltas = odata["deltas"]
        m_od = statistics.mean(odeltas) if odeltas else 0.0
        print(f"  {opp:<24}: Mean Delta = {m_od:+8.2f} | {odata['wins']}W / {odata['losses']}L / {odata['ties']}T")

    print("\n--- Seat Breakdown ---")
    for seat, sdata in sorted(seat_stats.items()):
        sdeltas = sdata["deltas"]
        m_sd = statistics.mean(sdeltas) if sdeltas else 0.0
        print(f"  Seat {seat}: Mean Delta = {m_sd:+8.2f} | {sdata['wins']}W / {sdata['losses']}L / {sdata['ties']}T")

    # Output JSON payload
    out_json = os.path.join(ROOT, "simulations", "experiments", "results", "p31_harvest_priority_ab.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    payload = {
        "metadata": {
            "baseline_sha": BASELINE_SHA,
            "head_sha": head_sha,
            "manifest_hash": manifest_hash,
            "total_games": total_games,
            "matched_cases": n,
            "seed_range": [91001, 91050],
            "timestamp": time.time(),
        },
        "summary": {
            "control_mean": mean_c,
            "treatment_mean": mean_t,
            "mean_delta": mean_delta,
            "median_delta": median_delta,
            "ci_95": [ci_lower, ci_upper],
            "t_stat": t_stat,
            "p_value": p_val,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": wins / n if n > 0 else 0.0,
            "decay_delta": decay_delta,
            "strawberry_rev_delta": mean_t_straw_rev - mean_c_straw_rev,
        },
        "opponent_breakdown": {
            opp: {
                "mean_delta": statistics.mean(odata["deltas"]) if odata["deltas"] else 0.0,
                "wins": odata["wins"], "losses": odata["losses"], "ties": odata["ties"]
            }
            for opp, odata in opp_stats.items()
        },
        "seat_breakdown": {
            seat: {
                "mean_delta": statistics.mean(sdata["deltas"]) if sdata["deltas"] else 0.0,
                "wins": sdata["wins"], "losses": sdata["losses"], "ties": sdata["ties"]
            }
            for seat, sdata in seat_stats.items()
        },
        "matched_cases": [
            {
                "scenario": arm_dict["Control"]["scenario"],
                "seed": arm_dict["Control"]["seed"],
                "seat": arm_dict["Control"]["seat"],
                "opponent": arm_dict["Control"]["opponent"],
                "control_score": arm_dict["Control"]["score"],
                "treatment_score": arm_dict["Treatment"]["score"],
                "delta": arm_dict["Treatment"]["score"] - arm_dict["Control"]["score"],
                "control_decay": arm_dict["Control"]["crop_decay_dollars"],
                "treatment_decay": arm_dict["Treatment"]["crop_decay_dollars"],
                "control_strawberry_rev": arm_dict["Control"]["strawberry_revenue"],
                "treatment_strawberry_rev": arm_dict["Treatment"]["strawberry_revenue"],
            }
            for key, arm_dict in sorted(paired_runs.items())
            if "Control" in arm_dict and "Treatment" in arm_dict
        ]
    }
    with open(out_json, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nResults saved to {out_json}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8, help="Parallel worker processes")
    parser.add_argument("--pairs", type=int, default=None, help="Limit number of pairs for test run")
    args = parser.parse_args()
    run_experiment(num_workers=args.workers, pairs_limit=args.pairs)
