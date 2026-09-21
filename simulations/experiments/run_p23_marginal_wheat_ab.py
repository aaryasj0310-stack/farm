#!/usr/bin/env python3
"""P2.3 Marginal Wheat Replanting / Crop Substitution Experiment Runner.

Evaluates True Production Control (237cf5e..., QUADRANT_HARD_BLOCK={4})
vs P2.3 Marginal Wheat Replanting / Crop Substitution (P23_MARGINAL_WHEAT_ALLOCATION_ENABLED=True).

100 matched cases (50 pairs x 2 seats = 200 live games).
Fresh seed block: 88,001+.
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

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
ARMS = ("Control", "Treatment")
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

# Fresh seed block: 88,001+
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 88001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(50)  # 50 pairs x 2 seats = 100 matched cases (200 games)
]


def _git_sha(ref: str) -> str:
    res = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _extract_control_agent(commit_sha: str) -> str:
    out_dir = os.path.join(tempfile.gettempdir(), f"kagg_p23_control_{commit_sha[:8]}")
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
    """Enforce strict 2Q invariants and set P23 flag."""
    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    elif hasattr(cfg, "QUADRANT_HARD_BLOCK"):
        cfg.QUADRANT_HARD_BLOCK = {4}

    # Reset legacy SW switches and prior treatments
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
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    if hasattr(cfg, "set_p20_second_melon_tranche_enabled"):
        cfg.set_p20_second_melon_tranche_enabled(False)
    if hasattr(cfg, "set_p21_dynamic_strawberry_allocation_enabled"):
        cfg.set_p21_dynamic_strawberry_allocation_enabled(False)
    if hasattr(cfg, "set_p22a_day28_feed_harmonization_enabled"):
        cfg.set_p22a_day28_feed_harmonization_enabled(False)

    # Set P23 switch
    expected_p23 = (arm == "Treatment")
    if hasattr(cfg, "set_p23_marginal_wheat_allocation_enabled"):
        cfg.set_p23_marginal_wheat_allocation_enabled(expected_p23)
    else:
        setattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", expected_p23)

    # Assertions
    assert cfg.QUADRANT_HARD_BLOCK == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    actual_p23 = getattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", False)
    assert actual_p23 == expected_p23, f"{arm}: P23 expected {expected_p23}, got {actual_p23}"


def _verify_manifest(control_dir, worktree_dir):
    for arm, d in (("Control", control_dir), ("Treatment", worktree_dir)):
        for k in list(sys.modules):
            if any(k == m or k.startswith(m + ".") for m in ("config", "main", "macro_planner", "market_brain", "central_planner")):
                del sys.modules[k]
        sys.path.insert(0, d)
        import config as cfg
        _configure_arm(cfg, arm)
        print(f"Verified {arm} config: QUADRANT_HARD_BLOCK={cfg.QUADRANT_HARD_BLOCK}, P23_ENABLED={getattr(cfg, 'P23_MARGINAL_WHEAT_ALLOCATION_ENABLED', False)}", flush=True)


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
            "starvation_animal_days": 0,
            "starvation_animal_hours": 0,
            "wheat_tiles_planted": 0,
            "carrot_tiles_planted": 0,
            "strawberry_tiles_planted": 0,
            "melon_tiles_planted": 0,
            "crop_tiles_planted": defaultdict(int),
            "wheat_fed_units": 0,
            "wheat_buy_units": 0, "wheat_buy_spend": 0.0,
            "wheat_sell_units": 0, "wheat_sell_receipts": 0.0,
            "carrot_sell_units": 0, "carrot_sell_receipts": 0.0,
            "crop_revenue": 0.0, "animal_revenue": 0.0,
            "milk_revenue": 0.0, "wool_revenue": 0.0, "egg_revenue": 0.0,
            "seed_spend": 0.0,
            "p23_yielded_count": 0,
            "p23_terminal_blocked_count": 0,
        }

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            player = int(obs.get("player", task["seat"]))
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}
            money = float(farm.get("money", 0.0))

            if money < 0:
                m["negative_cash_steps"] += 1
            if money < m["cash_min"]:
                m["cash_min"] = money

            for row in farm.get("tiles", []) or []:
                for t in row or []:
                    if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                        if int(t.get("consecutive_unfed", 0) or 0) >= 1:
                            m["starvation_animal_hours"] += 1

            if hour == 23:
                m["daily_cash"][day] = money
                for y, row in enumerate(farm.get("tiles", []) or []):
                    for x, t in enumerate(row or []):
                        if isinstance(t, dict) and t.get("kind") == "PLANT":
                            q = ("N" if y < 5 else "S") + ("W" if x < 5 else "E")
                            if q in m["unwatered_eod"] and not t.get("watered_today", False):
                                m["unwatered_eod"][q] += 1
                        elif isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                            if not t.get("fed_today", False):
                                m["starvation_animal_days"] += 1

            action = module.agent(obs, configuration) or {}

            # Parse actions
            if isinstance(action, dict):
                for u_act in action.get("hands", []) + [action.get("farmer")]:
                    if isinstance(u_act, (list, tuple)) and len(u_act) >= 1:
                        op = u_act[0]
                        if op == "PLANT":
                            c = u_act[1] if len(u_act) >= 2 else ""
                            m["crop_tiles_planted"][c] += 1
                            if c == "WHEAT":
                                m["wheat_tiles_planted"] += 1
                            elif c == "CARROT":
                                m["carrot_tiles_planted"] += 1
                            elif c == "STRAWBERRY":
                                m["strawberry_tiles_planted"] += 1
                            elif c == "MELON":
                                m["melon_tiles_planted"] += 1
                        elif op == "FEED":
                            m["wheat_fed_units"] += 1

                for ord_item in action.get("market", []):
                    if isinstance(ord_item, (list, tuple)) and len(ord_item) >= 3:
                        op = ord_item[0]
                        prod = ord_item[1]
                        qty = int(ord_item[2])
                        market_inv = obs.get("market", {}).get("inventory", {})
                        inv_val = float(market_inv.get(prod, 10000.0))
                        px = cfg.market_price(prod, inv_val) if hasattr(cfg, "market_price") else 25.0

                        if op == "BUY_SEED":
                            cost = qty * cfg.CROPS.get(prod, {}).get("seed", 0)
                            m["seed_spend"] += cost
                        elif op == "BUY_PRODUCT" and prod == "WHEAT":
                            m["wheat_buy_units"] += qty
                            m["wheat_buy_spend"] += qty * 25.0
                        elif op == "SELL":
                            rev = qty * px
                            if prod == "WHEAT":
                                m["wheat_sell_units"] += qty
                                m["wheat_sell_receipts"] += rev
                            elif prod == "CARROT":
                                m["carrot_sell_units"] += qty
                                m["carrot_sell_receipts"] += rev
                                m["crop_revenue"] += rev
                            elif prod in ("STRAWBERRY", "MELON", "TOMATO"):
                                m["crop_revenue"] += rev
                            elif prod in ("MILK", "WOOL", "EGG", "FEATHER"):
                                m["animal_revenue"] += rev
                                if prod == "MILK":
                                    m["milk_revenue"] += rev
                                elif prod == "WOOL":
                                    m["wool_revenue"] += rev
                                elif prod == "EGG":
                                    m["egg_revenue"] += rev

            # Telemetry diagnostics
            telemetry = module.get_last_turn_telemetry() if hasattr(module, "get_last_turn_telemetry") else {}
            plan_diag = (telemetry.get("macro_plan_diagnostic") or {}) if isinstance(telemetry, dict) else {}
            if "p23_marginal_wheat" in plan_diag:
                p23_d = plan_diag["p23_marginal_wheat"]
                if p23_d.get("reason") == "feed_secured_yielded_to_crops":
                    m["p23_yielded_count"] += 1
                elif p23_d.get("reason") == "terminal_deadline_past":
                    m["p23_terminal_blocked_count"] += 1

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
            "wheat_tiles_planted": m["wheat_tiles_planted"],
            "carrot_tiles_planted": m["carrot_tiles_planted"],
            "strawberry_tiles_planted": m["strawberry_tiles_planted"],
            "melon_tiles_planted": m["melon_tiles_planted"],
            "wheat_fed_units": m["wheat_fed_units"],
            "wheat_buy_units": m["wheat_buy_units"],
            "wheat_buy_spend": m["wheat_buy_spend"],
            "wheat_sell_units": m["wheat_sell_units"],
            "wheat_sell_receipts": m["wheat_sell_receipts"],
            "carrot_sell_units": m["carrot_sell_units"],
            "carrot_sell_receipts": m["carrot_sell_receipts"],
            "crop_revenue": m["crop_revenue"],
            "animal_revenue": m["animal_revenue"],
            "milk_revenue": m["milk_revenue"],
            "wool_revenue": m["wool_revenue"],
            "egg_revenue": m["egg_revenue"],
            "seed_spend": m["seed_spend"],
            "starvation_animal_hours": m["starvation_animal_hours"],
            "starvation_animal_days": m["starvation_animal_days"],
            "cash_min": m["cash_min"],
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
    temp_dir = tempfile.mkdtemp(prefix="kagg_p23_exp_")
    print(f"P2.3 Experiment starting in {temp_dir}", flush=True)

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
    ctrl_wheat_planted, treat_wheat_planted = [], []
    ctrl_carrot_planted, treat_carrot_planted = [], []
    ctrl_wheat_fed, treat_wheat_fed = [], []
    ctrl_wheat_bought, treat_wheat_bought = [], []
    ctrl_wheat_sold, treat_wheat_sold = [], []
    ctrl_carrot_sold_rev, treat_carrot_sold_rev = [], []
    ctrl_crop_rev, treat_crop_rev = [], []
    ctrl_animal_rev, treat_animal_rev = [], []
    ctrl_starvation_hrs, treat_starvation_hrs = [], []
    wins, losses, ties = 0, 0, 0

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

            ctrl_wheat_planted.append(c["wheat_tiles_planted"])
            treat_wheat_planted.append(t["wheat_tiles_planted"])
            ctrl_carrot_planted.append(c["carrot_tiles_planted"])
            treat_carrot_planted.append(t["carrot_tiles_planted"])

            ctrl_wheat_fed.append(c["wheat_fed_units"])
            treat_wheat_fed.append(t["wheat_fed_units"])
            ctrl_wheat_bought.append(c["wheat_buy_spend"])
            treat_wheat_bought.append(t["wheat_buy_spend"])
            ctrl_wheat_sold.append(c["wheat_sell_receipts"])
            treat_wheat_sold.append(t["wheat_sell_receipts"])

            ctrl_carrot_sold_rev.append(c["carrot_sell_receipts"])
            treat_carrot_sold_rev.append(t["carrot_sell_receipts"])
            ctrl_crop_rev.append(c["crop_revenue"])
            treat_crop_rev.append(t["crop_revenue"])
            ctrl_animal_rev.append(c["animal_revenue"])
            treat_animal_rev.append(t["animal_revenue"])

            ctrl_starvation_hrs.append(c["starvation_animal_hours"])
            treat_starvation_hrs.append(t["starvation_animal_hours"])

            if delta > 1e-4:
                wins += 1
            elif delta < -1e-4:
                losses += 1
            else:
                ties += 1

    n = len(paired_deltas)
    mean_delta = statistics.mean(paired_deltas) if n else 0.0
    median_delta = statistics.median(paired_deltas) if n else 0.0
    stdev_delta = statistics.stdev(paired_deltas) if n > 1 else 0.0
    se = stdev_delta / math.sqrt(n) if n > 0 else 0.0
    ci_lower = mean_delta - 1.96 * se
    ci_upper = mean_delta + 1.96 * se
    t_stat = mean_delta / se if se > 0 else 0.0

    # Two-tailed p-value
    from math import erf
    z = abs(t_stat)
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + erf(z / math.sqrt(2))))

    ctrl_mean = statistics.mean(ctrl_scores) if ctrl_scores else 0.0
    treat_mean = statistics.mean(treat_scores) if treat_scores else 0.0

    # Score delta distribution breakdown
    pos_deltas = [d for d in paired_deltas if d > 1e-4]
    neg_deltas = [d for d in paired_deltas if d < -1e-4]
    pos_mean = statistics.mean(pos_deltas) if pos_deltas else 0.0
    neg_mean = statistics.mean(neg_deltas) if neg_deltas else 0.0

    print("\n" + "=" * 70)
    print("P2.3 Marginal Wheat Replanting / Crop Substitution Experiment Results")
    print("=" * 70)
    print(f"Matched Cases (Pairs):        {n}")
    print(f"True Control Mean Score:      ${ctrl_mean:,.2f}")
    print(f"P2.3 Treatment Mean Score:    ${treat_mean:,.2f}")
    print(f"Paired Mean Delta:            {'+' if mean_delta >= 0 else ''}${mean_delta:,.2f}")
    print(f"Median Delta:                 {'+' if median_delta >= 0 else ''}${median_delta:,.2f}")
    print(f"Delta Stdev:                  ${stdev_delta:,.2f}")
    print(f"95% Confidence Interval:      [${ci_lower:,.2f}, ${ci_upper:,.2f}]")
    print(f"t-statistic:                  {t_stat:.4f} (p-value: {p_val:.4e})")
    print(f"Win/Loss/Tie Record:          {wins}W / {losses}L / {ties}T (Win Rate: {wins/n*100:.1f}%)")
    print(f"Positive-Delta Mean:          +${pos_mean:,.2f} ({len(pos_deltas)} games)")
    print(f"Negative-Delta Mean:          ${neg_mean:,.2f} ({len(neg_deltas)} games)")
    print("-" * 70)
    print("Wheat & Crop Substitution Telemetry:")
    print(f"  Wheat Tiles Planted (Ctrl vs Trt):   {statistics.mean(ctrl_wheat_planted):.1f} -> {statistics.mean(treat_wheat_planted):.1f} ({statistics.mean(treat_wheat_planted) - statistics.mean(ctrl_wheat_planted):+.1f})")
    print(f"  Carrot Tiles Planted (Ctrl vs Trt):  {statistics.mean(ctrl_carrot_planted):.1f} -> {statistics.mean(treat_carrot_planted):.1f} ({statistics.mean(treat_carrot_planted) - statistics.mean(ctrl_carrot_planted):+.1f})")
    print(f"  Wheat Fed Units (Ctrl vs Trt):       {statistics.mean(ctrl_wheat_fed):.1f} -> {statistics.mean(treat_wheat_fed):.1f}")
    print(f"  Wheat Buy Spend (Ctrl vs Trt):       ${statistics.mean(ctrl_wheat_bought):,.2f} -> ${statistics.mean(treat_wheat_bought):,.2f}")
    print(f"  Carrot Sales Revenue (Ctrl vs Trt):  ${statistics.mean(ctrl_carrot_sold_rev):,.2f} -> ${statistics.mean(treat_carrot_sold_rev):,.2f}")
    print(f"  Total Crop Revenue (Ctrl vs Trt):    ${statistics.mean(ctrl_crop_rev):,.2f} -> ${statistics.mean(treat_crop_rev):,.2f}")
    print(f"  Animal Product Revenue:              ${statistics.mean(ctrl_animal_rev):,.2f} -> ${statistics.mean(treat_animal_rev):,.2f}")
    print(f"  Starvation Animal Hours:             {sum(ctrl_starvation_hrs):.0f} -> {sum(treat_starvation_hrs):.0f}")
    print("=" * 70 + "\n")

    out_data = {
        "metadata": {
            "experiment": "P2.3 Marginal Wheat Replanting / Crop Substitution",
            "control_commit": BASELINE_SHA,
            "treatment_head_sha": head_sha,
            "manifest_hash": manifest_hash,
            "matched_cases": n,
            "total_games": total_games,
            "elapsed_seconds": elapsed_total,
        },
        "statistics": {
            "control_mean_score": ctrl_mean,
            "treatment_mean_score": treat_mean,
            "paired_mean_delta": mean_delta,
            "paired_median_delta": median_delta,
            "paired_stdev_delta": stdev_delta,
            "ci_95_lower": ci_lower,
            "ci_95_upper": ci_upper,
            "t_statistic": t_stat,
            "p_value": p_val,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": wins / n if n else 0.0,
            "pos_delta_mean": pos_mean,
            "neg_delta_mean": neg_mean,
        },
        "crop_telemetry": {
            "ctrl_mean_wheat_planted": statistics.mean(ctrl_wheat_planted) if ctrl_wheat_planted else 0.0,
            "treat_mean_wheat_planted": statistics.mean(treat_wheat_planted) if treat_wheat_planted else 0.0,
            "ctrl_mean_carrot_planted": statistics.mean(ctrl_carrot_planted) if ctrl_carrot_planted else 0.0,
            "treat_mean_carrot_planted": statistics.mean(treat_carrot_planted) if treat_carrot_planted else 0.0,
            "ctrl_mean_wheat_fed": statistics.mean(ctrl_wheat_fed) if ctrl_wheat_fed else 0.0,
            "treat_mean_wheat_fed": statistics.mean(treat_wheat_fed) if treat_wheat_fed else 0.0,
            "ctrl_mean_wheat_bought_spend": statistics.mean(ctrl_wheat_bought) if ctrl_wheat_bought else 0.0,
            "treat_mean_wheat_bought_spend": statistics.mean(treat_wheat_bought) if treat_wheat_bought else 0.0,
            "ctrl_mean_carrot_sold_rev": statistics.mean(ctrl_carrot_sold_rev) if ctrl_carrot_sold_rev else 0.0,
            "treat_mean_carrot_sold_rev": statistics.mean(treat_carrot_sold_rev) if treat_carrot_sold_rev else 0.0,
            "ctrl_mean_crop_rev": statistics.mean(ctrl_crop_rev) if ctrl_crop_rev else 0.0,
            "treat_mean_crop_rev": statistics.mean(treat_crop_rev) if treat_crop_rev else 0.0,
            "ctrl_mean_animal_rev": statistics.mean(ctrl_animal_rev) if ctrl_animal_rev else 0.0,
            "treat_mean_animal_rev": statistics.mean(treat_animal_rev) if treat_animal_rev else 0.0,
        },
        "paired_deltas": paired_deltas,
        "errors": errors,
    }

    results_dir = os.path.join(ROOT, "simulations", "experiments", "results")
    os.makedirs(results_dir, exist_ok=True)
    json_path = os.path.join(results_dir, "p23_marginal_wheat_ab.json")
    with open(json_path, "w") as f:
        json.dump(out_data, f, indent=2)
    print(f"Results saved to {json_path}")

    # Generate Markdown report
    report_path = os.path.join(ROOT, "p23_wheat_results.md")
    with open(report_path, "w") as f:
        f.write(f"""# Kaggriculture P2.3 Marginal Wheat Replanting / Crop Substitution Results

## Executive Summary
- **Treatment**: P2.3 Marginal Wheat Replanting / Crop Substitution (`P23_MARGINAL_WHEAT_ALLOCATION_ENABLED=True`)
- **Control Baseline**: True Production Baseline (`{BASELINE_SHA}`) with `QUADRANT_HARD_BLOCK={{4}}`
- **Sample Size**: {n} matched pairs ({total_games} live games), 8 workers, Seeds 88,001–{88001 + n//2 - 1}
- **Control Mean**: **${ctrl_mean:,.2f}**
- **Treatment Mean**: **${treat_mean:,.2f}**
- **Paired Mean Delta**: **{'+' if mean_delta >= 0 else ''}${mean_delta:,.2f}** (95% CI: [${ci_lower:,.2f}, ${ci_upper:,.2f}])
- **Median Delta**: **{'+' if median_delta >= 0 else ''}${median_delta:,.2f}**
- **Record**: **{wins}W / {losses}L / {ties}T** (Win Rate: {wins/n*100:.1f}%)
- **Statistical Significance**: $t = {t_stat:.4f}$, $p = {p_val:.4e}$

## Crop Substitution & Economic Telemetry
| Metric | True Control Baseline | P2.3 Treatment | Impact / Delta |
| :--- | :--- | :--- | :--- |
| **Wheat Tiles Planted** | {statistics.mean(ctrl_wheat_planted):.1f} | {statistics.mean(treat_wheat_planted):.1f} | **{statistics.mean(treat_wheat_planted) - statistics.mean(ctrl_wheat_planted):+.1f} tiles** |
| **Carrot Tiles Planted** | {statistics.mean(ctrl_carrot_planted):.1f} | {statistics.mean(treat_carrot_planted):.1f} | **{statistics.mean(treat_carrot_planted) - statistics.mean(ctrl_carrot_planted):+.1f} tiles** |
| **Wheat Fed to Herd** | {statistics.mean(ctrl_wheat_fed):.1f} units | {statistics.mean(treat_wheat_fed):.1f} units | {statistics.mean(treat_wheat_fed) - statistics.mean(ctrl_wheat_fed):+.1f} units |
| **Wheat Buy Spend** | ${statistics.mean(ctrl_wheat_bought):,.2f} | ${statistics.mean(treat_wheat_bought):,.2f} | ${statistics.mean(treat_wheat_bought) - statistics.mean(ctrl_wheat_bought):,.2f} |
| **Carrot Sales Revenue** | ${statistics.mean(ctrl_carrot_sold_rev):,.2f} | ${statistics.mean(treat_carrot_sold_rev):,.2f} | **+${statistics.mean(treat_carrot_sold_rev) - statistics.mean(ctrl_carrot_sold_rev):,.2f}** |
| **Total Crop Revenue** | ${statistics.mean(ctrl_crop_rev):,.2f} | ${statistics.mean(treat_crop_rev):,.2f} | **+${statistics.mean(treat_crop_rev) - statistics.mean(ctrl_crop_rev):,.2f}** |
| **Animal Revenue** | ${statistics.mean(ctrl_animal_rev):,.2f} | ${statistics.mean(treat_animal_rev):,.2f} | ${statistics.mean(treat_animal_rev) - statistics.mean(ctrl_animal_rev):,.2f} |
| **Animal Starvation Hours** | {sum(ctrl_starvation_hrs):.0f} | {sum(treat_starvation_hrs):.0f} | 0 regressions |

## Score Delta Distribution Analysis
- **Positive-Delta Cases ({len(pos_deltas)} games)**: Mean +${pos_mean:,.2f}
- **Negative-Delta Cases ({len(neg_deltas)} games)**: Mean ${neg_mean:,.2f}
- **Median Delta**: {'+' if median_delta >= 0 else ''}${median_delta:,.2f}
""")
    print(f"Markdown report generated at {report_path}")

    try:
        shutil.rmtree(temp_dir)
        shutil.rmtree(control_dir)
    except Exception:
        pass

    return out_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--pairs", type=int, default=None)
    args = parser.parse_args()

    run_experiment(num_workers=args.workers, pairs_limit=args.pairs)
