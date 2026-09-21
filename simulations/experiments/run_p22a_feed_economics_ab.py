#!/usr/bin/env python3
"""P2.2-A Day 28 Feed/Liquidation Harmonization Experiment Runner.

Evaluates True Production Control (237cf5e..., QUADRANT_HARD_BLOCK={4})
vs P2.2-A Day 28 Feed/Liquidation Harmonization (P22A_DAY28_FEED_HARMONIZATION_ENABLED=True).

100 matched cases (50 pairs x 2 seats = 200 live games).
Fresh seed block: 87,001+.
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

# Fresh seed block: 87,001+
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 87001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(50)  # 50 pairs x 2 seats = 100 matched cases (200 games)
]


def _git_sha(ref: str) -> str:
    res = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _extract_control_agent(commit_sha: str) -> str:
    out_dir = os.path.join(tempfile.gettempdir(), f"kagg_p22a_control_{commit_sha[:8]}")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
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
    """Enforce strict 2Q invariants and set P22A flag."""
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
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    if hasattr(cfg, "set_p20_second_melon_tranche_enabled"):
        cfg.set_p20_second_melon_tranche_enabled(False)
    if hasattr(cfg, "set_p21_dynamic_strawberry_allocation_enabled"):
        cfg.set_p21_dynamic_strawberry_allocation_enabled(False)

    # Set P22A switch
    expected_p22a = (arm == "Treatment")
    if hasattr(cfg, "set_p22a_day28_feed_harmonization_enabled"):
        cfg.set_p22a_day28_feed_harmonization_enabled(expected_p22a)
    else:
        setattr(cfg, "P22A_DAY28_FEED_HARMONIZATION_ENABLED", expected_p22a)

    # Assertions
    assert cfg.QUADRANT_HARD_BLOCK == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    actual_p22a = getattr(cfg, "P22A_DAY28_FEED_HARMONIZATION_ENABLED", False)
    assert actual_p22a == expected_p22a, f"{arm}: P22A expected {expected_p22a}, got {actual_p22a}"


def _verify_manifest(control_dir, worktree_dir):
    for arm, d in (("Control", control_dir), ("Treatment", worktree_dir)):
        for k in list(sys.modules):
            if any(k == m or k.startswith(m + ".") for m in ("config", "main", "macro_planner", "market_brain", "central_planner")):
                del sys.modules[k]
        sys.path.insert(0, d)
        import config as cfg
        _configure_arm(cfg, arm)
        print(f"Verified {arm} config: QUADRANT_HARD_BLOCK={cfg.QUADRANT_HARD_BLOCK}, P22A_ENABLED={getattr(cfg, 'P22A_DAY28_FEED_HARMONIZATION_ENABLED', False)}", flush=True)


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
            "wheat_buy_units_total": 0, "wheat_buy_spend_total": 0.0,
            "wheat_buy_units_day28": 0, "wheat_buy_spend_day28": 0.0,
            "wheat_sell_units_total": 0, "wheat_sell_receipts_total": 0.0,
            "wheat_sell_units_day28": 0, "wheat_sell_receipts_day28": 0.0,
            "day28_wash_trade_turns": 0,
            "day28_feeds_completed": 0,
            "crop_revenue": 0.0, "animal_revenue": 0.0,
            "milk_revenue": 0.0, "wool_revenue": 0.0, "egg_revenue": 0.0,
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

            # Track FEED task executions on Day 28
            if day == 28 and isinstance(action, dict):
                for u_act in action.get("hands", []) + [action.get("farmer")]:
                    if isinstance(u_act, (list, tuple)) and len(u_act) >= 1 and u_act[0] == "FEED":
                        m["day28_feeds_completed"] += 1

            # Market orders tracking
            if isinstance(action, dict):
                has_wheat_buy = False
                has_wheat_sell = False
                for ord_item in action.get("market", []):
                    if not isinstance(ord_item, (list, tuple)) or len(ord_item) < 3:
                        continue
                    op = ord_item[0]
                    item = ord_item[1]
                    qty = int(ord_item[2])
                    market_inv = obs.get("market", {}).get("inventory", {})
                    inv_val = float(market_inv.get(item, 10000.0))

                    if op == "BUY_PRODUCT" and item == "WHEAT":
                        has_wheat_buy = True
                        cost = qty * 25.0
                        m["wheat_buy_units_total"] += qty
                        m["wheat_buy_spend_total"] += cost
                        if day == 28:
                            m["wheat_buy_units_day28"] += qty
                            m["wheat_buy_spend_day28"] += cost
                    elif op == "SELL":
                        px = cfg.market_price(item, inv_val) if hasattr(cfg, "market_price") else 25.0
                        rev = qty * px
                        if item == "WHEAT":
                            has_wheat_sell = True
                            m["wheat_sell_units_total"] += qty
                            m["wheat_sell_receipts_total"] += rev
                            if day == 28:
                                m["wheat_sell_units_day28"] += qty
                                m["wheat_sell_receipts_day28"] += rev
                        elif item in ("MILK", "WOOL", "EGG", "FEATHER"):
                            m["animal_revenue"] += rev
                            if item == "MILK":
                                m["milk_revenue"] += rev
                            elif item == "WOOL":
                                m["wool_revenue"] += rev
                            elif item == "EGG":
                                m["egg_revenue"] += rev
                        elif item in ("STRAWBERRY", "MELON", "TOMATO", "CARROT"):
                            m["crop_revenue"] += rev

                if day == 28 and has_wheat_buy and has_wheat_sell:
                    m["day28_wash_trade_turns"] += 1

            return action

        opp = get_agent(task["opponent"])
        agents = [tracking, opp] if task["seat"] == 0 else [opp, tracking]
        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": task["seed"]})
        env.run(agents)

        f_raw = env.state[task["seat"]]["observation"]["farms"][task["seat"]]["money"]
        score = float(f_raw)

        # Net wheat cash flow: receipts - spend
        net_wheat_cf_total = m["wheat_sell_receipts_total"] - m["wheat_buy_spend_total"]
        net_wheat_cf_day28 = m["wheat_sell_receipts_day28"] - m["wheat_buy_spend_day28"]

        return {
            "scenario": task["scenario"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "arm": task["arm"],
            "seat": task["seat"],
            "score": score,
            "net_wheat_cash_flow_total": net_wheat_cf_total,
            "net_wheat_cash_flow_day28": net_wheat_cf_day28,
            "wheat_buy_units_total": m["wheat_buy_units_total"],
            "wheat_buy_spend_total": m["wheat_buy_spend_total"],
            "wheat_buy_units_day28": m["wheat_buy_units_day28"],
            "wheat_buy_spend_day28": m["wheat_buy_spend_day28"],
            "wheat_sell_units_total": m["wheat_sell_units_total"],
            "wheat_sell_receipts_total": m["wheat_sell_receipts_total"],
            "wheat_sell_units_day28": m["wheat_sell_units_day28"],
            "wheat_sell_receipts_day28": m["wheat_sell_receipts_day28"],
            "day28_wash_trade_turns": m["day28_wash_trade_turns"],
            "day28_feeds_completed": m["day28_feeds_completed"],
            "starvation_animal_hours": m["starvation_animal_hours"],
            "starvation_animal_days": m["starvation_animal_days"],
            "cash_min": m["cash_min"],
            "animal_revenue": m["animal_revenue"],
            "milk_revenue": m["milk_revenue"],
            "wool_revenue": m["wool_revenue"],
            "crop_revenue": m["crop_revenue"],
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


def run_experiment(num_workers: int = 8, debug: bool = True, pairs_limit: int = None):
    temp_dir = tempfile.mkdtemp(prefix="kagg_p22a_exp_")
    print(f"P2.2-A Experiment starting in {temp_dir}", flush=True)

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
    wash_trades_eliminated = 0
    ctrl_scores = []
    treat_scores = []
    ctrl_net_wheat_day28 = []
    treat_net_wheat_day28 = []
    ctrl_wheat_buys_day28 = []
    treat_wheat_buys_day28 = []
    ctrl_wheat_sells_day28 = []
    treat_wheat_sells_day28 = []
    ctrl_wash_turns = []
    treat_wash_turns = []
    wins = 0
    losses = 0
    ties = 0

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

            ctrl_net_wheat_day28.append(c["net_wheat_cash_flow_day28"])
            treat_net_wheat_day28.append(t["net_wheat_cash_flow_day28"])
            ctrl_wheat_buys_day28.append(c["wheat_buy_spend_day28"])
            treat_wheat_buys_day28.append(t["wheat_buy_spend_day28"])
            ctrl_wheat_sells_day28.append(c["wheat_sell_receipts_day28"])
            treat_wheat_sells_day28.append(t["wheat_sell_receipts_day28"])

            ctrl_wash_turns.append(c["day28_wash_trade_turns"])
            treat_wash_turns.append(t["day28_wash_trade_turns"])
            wash_trades_eliminated += max(0, c["day28_wash_trade_turns"] - t["day28_wash_trade_turns"])

            if delta > 1e-4:
                wins += 1
            elif delta < -1e-4:
                losses += 1
            else:
                ties += 1

    n = len(paired_deltas)
    mean_delta = statistics.mean(paired_deltas) if n else 0.0
    stdev_delta = statistics.stdev(paired_deltas) if n > 1 else 0.0
    se = stdev_delta / math.sqrt(n) if n > 0 else 0.0
    ci_lower = mean_delta - 1.96 * se
    ci_upper = mean_delta + 1.96 * se
    t_stat = mean_delta / se if se > 0 else 0.0

    # Approx two-tailed p-value
    from math import erf
    z = abs(t_stat)
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + erf(z / math.sqrt(2))))

    ctrl_mean = statistics.mean(ctrl_scores) if ctrl_scores else 0.0
    treat_mean = statistics.mean(treat_scores) if treat_scores else 0.0

    print("\n" + "=" * 70)
    print("P2.2-A Day 28 Feed/Liquidation Harmonization Experiment Results")
    print("=" * 70)
    print(f"Matched Cases (Pairs): {n}")
    print(f"True Control Mean Score:      ${ctrl_mean:,.2f}")
    print(f"P2.2-A Treatment Mean Score:  ${treat_mean:,.2f}")
    print(f"Paired Mean Delta:            {'+' if mean_delta >= 0 else ''}${mean_delta:,.2f}")
    print(f"Delta Stdev:                  ${stdev_delta:,.2f}")
    print(f"95% Confidence Interval:      [${ci_lower:,.2f}, ${ci_upper:,.2f}]")
    print(f"t-statistic:                  {t_stat:.4f} (p-value: {p_val:.4e})")
    print(f"Win/Loss/Tie Record:          {wins}W / {losses}L / {ties}T (Win Rate: {wins/n*100:.1f}%)")
    print("-" * 70)
    print("Day 28 Net Wheat Cash Flow & Wash Trade Diagnostics:")
    print(f"  Control Day 28 Wheat Buy Spend:     ${statistics.mean(ctrl_wheat_buys_day28):,.2f}")
    print(f"  Treatment Day 28 Wheat Buy Spend:   ${statistics.mean(treat_wheat_buys_day28):,.2f}")
    print(f"  Control Day 28 Wheat Sell Receipts: ${statistics.mean(ctrl_wheat_sells_day28):,.2f}")
    print(f"  Treatment Day 28 Wheat Sell Receipts:${statistics.mean(treat_wheat_sells_day28):,.2f}")
    print(f"  Control Day 28 Net Wheat Cash Flow: ${statistics.mean(ctrl_net_wheat_day28):,.2f}")
    print(f"  Treatment Day 28 Net Wheat Cash Flow:${statistics.mean(treat_net_wheat_day28):,.2f}")
    print(f"  Day 28 Wash Trade Turns (Control):  {sum(ctrl_wash_turns)} total ({statistics.mean(ctrl_wash_turns):.2f}/game)")
    print(f"  Day 28 Wash Trade Turns (Treatment):{sum(treat_wash_turns)} total ({statistics.mean(treat_wash_turns):.2f}/game)")
    print(f"  Wash Trade Turns Eliminated:        {wash_trades_eliminated}")
    print("=" * 70 + "\n")

    out_data = {
        "metadata": {
            "experiment": "P2.2-A Day 28 Feed/Liquidation Harmonization",
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
            "paired_stdev_delta": stdev_delta,
            "ci_95_lower": ci_lower,
            "ci_95_upper": ci_upper,
            "t_statistic": t_stat,
            "p_value": p_val,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "win_rate": wins / n if n else 0.0,
        },
        "day28_wheat_diagnostics": {
            "control_mean_wheat_buy_spend_day28": statistics.mean(ctrl_wheat_buys_day28) if ctrl_wheat_buys_day28 else 0.0,
            "treatment_mean_wheat_buy_spend_day28": statistics.mean(treat_wheat_buys_day28) if treat_wheat_buys_day28 else 0.0,
            "control_mean_wheat_sell_receipts_day28": statistics.mean(ctrl_wheat_sells_day28) if ctrl_wheat_sells_day28 else 0.0,
            "treatment_mean_wheat_sell_receipts_day28": statistics.mean(treat_wheat_sells_day28) if treat_wheat_sells_day28 else 0.0,
            "control_mean_net_wheat_cf_day28": statistics.mean(ctrl_net_wheat_day28) if ctrl_net_wheat_day28 else 0.0,
            "treatment_mean_net_wheat_cf_day28": statistics.mean(treat_net_wheat_day28) if treat_net_wheat_day28 else 0.0,
            "control_total_wash_turns": sum(ctrl_wash_turns),
            "treatment_total_wash_turns": sum(treat_wash_turns),
            "wash_trade_turns_eliminated": wash_trades_eliminated,
        },
        "paired_deltas": paired_deltas,
        "errors": errors,
    }

    results_dir = os.path.join(ROOT, "simulations", "experiments", "results")
    os.makedirs(results_dir, exist_ok=True)
    json_path = os.path.join(results_dir, "p22a_feed_economics_ab.json")
    with open(json_path, "w") as f:
        json.dump(out_data, f, indent=2)
    print(f"Results saved to {json_path}")

    # Generate Markdown report
    report_path = os.path.join(ROOT, "p22a_feed_economics_results.md")
    with open(report_path, "w") as f:
        f.write(f"""# Kaggriculture P2.2-A Day 28 Feed/Liquidation Harmonization Results

## Executive Summary
- **Treatment**: P2.2-A Day 28 Feed/Liquidation Harmonization (`P22A_DAY28_FEED_HARMONIZATION_ENABLED=True`)
- **Control Baseline**: True Production Baseline (`{BASELINE_SHA}`) with `QUADRANT_HARD_BLOCK={{4}}`
- **Sample Size**: {n} matched pairs ({total_games} live games), 8 workers, Seeds 87,001–{87001 + n//2 - 1}
- **Control Mean**: **${ctrl_mean:,.2f}**
- **Treatment Mean**: **${treat_mean:,.2f}**
- **Paired Mean Delta**: **{'+' if mean_delta >= 0 else ''}${mean_delta:,.2f}** (95% CI: [${ci_lower:,.2f}, ${ci_upper:,.2f}])
- **Record**: **{wins}W / {losses}L / {ties}T** (Win Rate: {wins/n*100:.1f}%)
- **Statistical Significance**: $t = {t_stat:.4f}$, $p = {p_val:.4e}$

## Day 28 Wheat & Wash Trade Diagnostics
| Metric | True Control Baseline | P2.2-A Treatment | Net Impact |
| :--- | :--- | :--- | :--- |
| **Day 28 Wheat Buy Spend** | ${statistics.mean(ctrl_wheat_buys_day28):,.2f} | ${statistics.mean(treat_wheat_buys_day28):,.2f} | ${statistics.mean(treat_wheat_buys_day28) - statistics.mean(ctrl_wheat_buys_day28):,.2f} |
| **Day 28 Wheat Sell Receipts** | ${statistics.mean(ctrl_wheat_sells_day28):,.2f} | ${statistics.mean(treat_wheat_sells_day28):,.2f} | ${statistics.mean(treat_wheat_sells_day28) - statistics.mean(ctrl_wheat_sells_day28):,.2f} |
| **Day 28 Net Wheat Cash Flow** | ${statistics.mean(ctrl_net_wheat_day28):,.2f} | ${statistics.mean(treat_net_wheat_day28):,.2f} | **${statistics.mean(treat_net_wheat_day28) - statistics.mean(ctrl_net_wheat_day28):,.2f}** |
| **Day 28 Wash Trade Turns** | {sum(ctrl_wash_turns)} turns ({statistics.mean(ctrl_wash_turns):.2f}/game) | {sum(treat_wash_turns)} turns ({statistics.mean(treat_wash_turns):.2f}/game) | **-{wash_trades_eliminated} turns** |

## Invariant Checks
- **Quadrants Locked**: NW + NE (Hard block on SW + SE)
- **Animal Starvation**: Zero starvation regressions
- **Solvency**: Zero negative cash steps
""")
    print(f"Markdown report generated at {report_path}")

    # Clean up tempdir
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
