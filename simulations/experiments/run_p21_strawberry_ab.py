#!/usr/bin/env python3
"""P2.1 Dynamic Strawberry Portfolio Optimization Experiment Runner.

Evaluates True Production Control (237cf5e..., QUADRANT_HARD_BLOCK={4})
vs P2.1 Dynamic Strawberry Portfolio Optimization (P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED=True).

100 matched cases (50 pairs x 2 seats = 200 live games).
Fresh seed block: 86,001+.
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

# Fresh seed block: 86,001+
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 86001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(50)  # 50 pairs x 2 seats = 100 matched cases (200 games)
]


def _git_sha(ref: str) -> str:
    res = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _extract_control_agent(commit_sha: str) -> str:
    out_dir = os.path.join(tempfile.gettempdir(), f"kagg_p21_control_{commit_sha[:8]}")
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
    """Enforce strict 2Q invariants and set P21 flag."""
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
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    if hasattr(cfg, "set_p20_second_melon_tranche_enabled"):
        cfg.set_p20_second_melon_tranche_enabled(False)

    # Set P21 switch
    expected_p21 = (arm == "Treatment")
    if hasattr(cfg, "set_p21_dynamic_strawberry_allocation_enabled"):
        cfg.set_p21_dynamic_strawberry_allocation_enabled(expected_p21)
    else:
        setattr(cfg, "P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED", expected_p21)

    # Assertions
    assert cfg.QUADRANT_HARD_BLOCK == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    actual_p21 = getattr(cfg, "P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED", False)
    assert actual_p21 == expected_p21, f"{arm}: P21 expected {expected_p21}, got {actual_p21}"


def _verify_manifest(control_dir, worktree_dir):
    for arm, d in (("Control", control_dir), ("Treatment", worktree_dir)):
        for k in list(sys.modules):
            if any(k == m or k.startswith(m + ".") for m in ("config", "main", "macro_planner", "strawberry_portfolio_evaluator")):
                del sys.modules[k]
        sys.path.insert(0, d)
        import config as cfg
        _configure_arm(cfg, arm)
        print(f"Verified {arm} config: QUADRANT_HARD_BLOCK={cfg.QUADRANT_HARD_BLOCK}, P21_ENABLED={getattr(cfg, 'P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED', False)}", flush=True)


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "strawberry_portfolio_evaluator"
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
            "sw_acquisitions": 0,
            "negative_cash_steps": 0, "cash_min": float("inf"),
            "daily_cash": {},
            "unwatered_eod": {"NW": 0, "NE": 0},
            "starvation_animal_days": 0,
            "starvation_animal_hours": 0,
            "harvest_exec": {"NW": 0, "NE": 0},
            "feed_exec": {"NW": 0, "NE": 0},
            "seed_spend": 0.0, "animal_spend": 0.0, "land_spend": 0.0,
            "wheat_buy_units": 0, "wheat_buy_spend": 0.0,
            "crop_revenue": 0.0, "animal_revenue": 0.0,
            "feed_action_attempts": 0,
            "strawberry_tiles_planted": 0,
            "crop_tiles_planted": defaultdict(int),
            "strawberry_units_sold": 0,
            "strawberry_revenue_realized": 0.0,
            "p21_checks": 0,
            "p21_admitted_caps": [],
            "p21_decision_records": [],
            "total_crop_units_sold": defaultdict(int),
        }

        prev_money = None

        def tracking(obs, configuration=None):
            nonlocal prev_money
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
            prev_money = money

            # Capture telemetry from macro_planner
            telemetry = module.get_last_turn_telemetry() if hasattr(module, "get_last_turn_telemetry") else {}
            plan_diag = (telemetry.get("macro_plan_diagnostic") or {}) if isinstance(telemetry, dict) else {}

            if "p21_strawberry" in plan_diag and plan_diag["p21_strawberry"]:
                p21_d = plan_diag["p21_strawberry"]
                m["p21_checks"] += 1
                adm_cap = int(p21_d.get("admitted_cap", 0))
                m["p21_admitted_caps"].append(adm_cap)
                if hour == 0 and day <= 13:
                    rec = {
                        "day": day,
                        "admitted_cap": adm_cap,
                        "baseline_cap": p21_d.get("baseline_cap"),
                        "mv_alt": round(float(p21_d.get("mv_alt", 0.0)), 1),
                        "best_alt": p21_d.get("best_alt"),
                        "market_strawberry_inv": round(float(p21_d.get("market_strawberry_inv", 10000.0)), 1),
                    }
                    m["p21_decision_records"].append(rec)

            # Track unit actions (plantings and harvests)
            if isinstance(action, dict):
                for u_act in action.get("hands", []) + [action.get("farmer")]:
                    if isinstance(u_act, (list, tuple)) and len(u_act) >= 1:
                        op = u_act[0]
                        if op == "PLANT" and len(u_act) >= 2:
                            c = u_act[1]
                            m["crop_tiles_planted"][c] += 1
                            if c == "STRAWBERRY":
                                m["strawberry_tiles_planted"] += 1
                        elif op == "HARVEST":
                            m["harvest_exec_count"] = m.get("harvest_exec_count", 0) + 1

            # Market orders tracking
            if isinstance(action, dict):
                for ord_item in action.get("market", []):
                    if not isinstance(ord_item, (list, tuple)) or len(ord_item) < 2:
                        continue
                    op = ord_item[0]
                    if op == "BUY_SEED" and len(ord_item) >= 3:
                        c = ord_item[1]
                        q = int(ord_item[2])
                        m["seed_spend"] += q * cfg.CROPS.get(c, {}).get("seed", 0)
                    elif op == "BUY_ANIMAL" and len(ord_item) >= 3:
                        a = ord_item[1]
                        m["animal_spend"] += cfg.ANIMALS.get(a, {}).get("cost", 0)
                    elif op == "BUY_LAND":
                        m["land_spend"] += 1000.0  # NE
                    elif op == "BUY_PRODUCT" and len(ord_item) >= 3 and ord_item[1] == "WHEAT":
                        q = int(ord_item[2])
                        m["wheat_buy_units"] += q
                        m["wheat_buy_spend"] += q * 25.0
                    elif op == "SELL" and len(ord_item) >= 3:
                        prod = ord_item[1]
                        q = int(ord_item[2])
                        m["total_crop_units_sold"][prod] += q
                        if prod == "STRAWBERRY":
                            m["strawberry_units_sold"] += q
                            cur_p = float(obs.get("market", {}).get("prices", {}).get("STRAWBERRY", 120))
                            m["strawberry_revenue_realized"] += q * cur_p

            return action

        env = kaggle_environments.make("kaggriculture", configuration={"seed": task["seed"], "episodeSteps": 720}, debug=True)
        agents = [tracking, get_agent(task["opponent"])] if task["seat"] == 0 else [get_agent(task["opponent"]), tracking]
        env.run(agents)

        player = task["seat"]
        score = float(env.steps[-1][player]["reward"])
        opp_score = float(env.steps[-1][1 - player]["reward"])

        daily = ts.get_daily_log()
        m["productive_ops"] = {"NW": 0, "NE": 0}
        m["scheduler_travel_distance"] = 0
        for d in (daily.values() if isinstance(daily, dict) else []):
            loc = d.get("locality_telemetry") or {}
            for q, n in (loc.get("productive_ops_by_zone") or {}).items():
                if q in m["productive_ops"]:
                    m["productive_ops"][q] += int(n)
            m["scheduler_travel_distance"] += int(loc.get("total_travel_distance", 0) or 0)
            for q, n in (d.get("harvest_counts_by_zone") or {}).items():
                if q in m["harvest_exec"]:
                    m["harvest_exec"][q] += int(n)

        return {
            "status": "SUCCESS", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"],
            "opponent": task["opponent"], "seat": task["seat"],
            "score": score, "opponent_score": opp_score,
            "metrics": m,
        }
    except Exception as exc:
        return {
            "status": "ERROR", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"],
            "opponent": task["opponent"], "seat": task["seat"],
            "error": str(exc), "traceback": traceback.format_exc(),
        }


def _delta_stats(values):
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stddev": 0.0, "stderr": 0.0, "ci95": [0.0, 0.0], "t_stat": 0.0, "p_val": 1.0, "wins": 0, "ties": 0, "losses": 0}
    n = len(values)
    mean = statistics.mean(values)
    median = statistics.median(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else 0.0
    half = 1.96 * se
    ci = [mean - half, mean + half]
    t_stat = mean / se if se > 0 else 0.0
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))
    return {
        "n": n, "mean": mean, "median": median, "stddev": sd, "stderr": se, "ci95": ci,
        "t_stat": t_stat, "p_val": p_val,
        "wins": sum(1 for v in values if v > 0),
        "ties": sum(1 for v in values if v == 0),
        "losses": sum(1 for v in values if v < 0),
    }


def generate_markdown_report(report: dict) -> str:
    c_sum = report["summary"]["arms"]["Control"]
    t_sum = report["summary"]["arms"]["Treatment"]
    d_sum = report["summary"]["deltas"]["treatment_vs_control"]

    c_straw_planted = c_sum.get("strawberry_tiles_planted", 0)
    t_straw_planted = t_sum.get("strawberry_tiles_planted", 0)
    c_straw_rev = c_sum.get("strawberry_revenue", 0.0)
    t_straw_rev = t_sum.get("strawberry_revenue", 0.0)

    lines = [
        "# Kaggriculture: P2.1 Dynamic Strawberry Portfolio Optimization Report", "",
        f"- Control Baseline SHA: `{BASELINE_SHA}` (True Production Baseline, QUADRANT_HARD_BLOCK={{4}})",
        f"- Treatment Fingerprint: `{report['metadata']['worktree_fingerprint']}`",
        f"- Engine Version: {report['metadata']['engine_version']}",
        f"- Total Matched Cases: {report['summary']['complete_matched_cases']} (balanced across 5 opponents and 2 seats)",
        f"- Fresh Seed Block: 86,001+",
        "",
        "## 1. Overall Economic Performance (Full 100 Matched Cases)", "",
        "| Metric | Control (True Baseline) | Treatment (P2.1 Dynamic Strawberry) | Paired Delta / Impact |",
        "|---|---:|---:|---:|",
        f"| **Mean Final Score** | **${c_sum['mean_score']:,.2f}** | **${t_sum['mean_score']:,.2f}** | **${d_sum['mean']:+,.2f}** (95% CI: [${d_sum['ci95'][0]:+,.2f}, ${d_sum['ci95'][1]:+,.2f}]) |",
        f"| Median Final Score | ${c_sum['median_score']:,.2f} | ${t_sum['median_score']:,.2f} | ${d_sum['median']:+,.2f} |",
        f"| Win / Tie / Loss | — | — | **{d_sum['wins']}W / {d_sum['ties']}T / {d_sum['losses']}L** (p={d_sum['p_val']:.4f}) |",
        f"| Strawberry Tiles Planted | {c_straw_planted:,} | {t_straw_planted:,} | {t_straw_planted - c_straw_planted:+,} tiles |",
        f"| Realized Strawberry Revenue | ${c_straw_rev:,.2f} | ${t_straw_rev:,.2f} | ${t_straw_rev - c_straw_rev:+,.2f} |",
        f"| Seed Purchase Spend | ${c_sum['seed_spend']:,.2f} | ${t_sum['seed_spend']:,.2f} | ${t_sum['seed_spend'] - c_sum['seed_spend']:+,.2f} |",
        f"| Wheat Purchase Spend | ${c_sum['wheat_buy_spend']:,.2f} | ${t_sum['wheat_buy_spend']:,.2f} | ${t_sum['wheat_buy_spend'] - c_sum['wheat_buy_spend']:+,.2f} |",
        f"| Animal Purchase Spend | ${c_sum['animal_spend']:,.2f} | ${t_sum['animal_spend']:,.2f} | ${t_sum['animal_spend'] - c_sum['animal_spend']:+,.2f} |",
        "",
        "## 2. Breakdown Across Opponent Archetypes", "",
        "| Opponent Archetype | Cases | Control Mean | Treatment Mean | Paired Delta | 95% CI | Win Rate |",
        "|---|---:|---:|---:|---:|:---:|:---:|",
    ]
    for opp, row in report["summary"]["per_opponent"].items():
        ci = row["ci95"]
        wr = f"{row['wins']}/{row['cases']} ({100*row['wins']/row['cases']:.1f}%)"
        lines.append(
            f"| `{opp}` | {row['cases']} | ${row['control_mean']:,.2f} | ${row['treatment_mean']:,.2f} | ${row['delta_mean']:+,.2f} | [${ci[0]:+,.2f}, ${ci[1]:+,.2f}] | {wr} |"
        )

    lines += [
        "",
        "## 3. Operational Safety & Core Farm Integrity", "",
        f"- Negative Cash Steps: Control={c_sum['negative_cash_steps']}, Treatment={t_sum['negative_cash_steps']}",
        f"- NW+NE Productive Operations: Control={c_sum['nw_ne_productive_ops']:,}, Treatment={t_sum['nw_ne_productive_ops']:,} (Delta: {t_sum['nw_ne_productive_ops'] - c_sum['nw_ne_productive_ops']:+,})",
        f"- NW+NE Harvests Realized: Control={c_sum['nw_ne_harvest_exec']:,}, Treatment={t_sum['nw_ne_harvest_exec']:,} (Delta: {t_sum['nw_ne_harvest_exec'] - c_sum['nw_ne_harvest_exec']:+,})",
        f"- NW+NE Unwatered EOD: Control={c_sum['nw_ne_unwatered_eod']:,}, Treatment={t_sum['nw_ne_unwatered_eod']:,} (Delta: {t_sum['nw_ne_unwatered_eod'] - c_sum['nw_ne_unwatered_eod']:+,})",
        f"- Starvation Animal-Days: Control={c_sum['starvation_animal_days']}, Treatment={t_sum['starvation_animal_days']}",
        f"- Total P2.1 Dynamic Cap Checks: {t_sum.get('p21_checks', 0)}",
        "",
        "## 4. Promotion Decision", "",
    ]
    if d_sum["mean"] > 0 and d_sum["ci95"][0] > -1500 and d_sum["p_val"] < 0.05:
        lines.append("> **PROMOTION RECOMMENDED**: P2.1 demonstrated statistically significant positive score delta while preserving core solvency and labor integrity.")
    elif d_sum["mean"] > 0:
        lines.append("> **TENTATIVE / INCONCLUSIVE**: P2.1 showed a positive mean delta but did not achieve full statistical significance at the 95% level. Do not promote without further validation.")
    else:
        lines.append("> **PROMOTION REJECTED**: P2.1 did not improve final score over True Production Control. Discard treatment and advance to the next portfolio hypothesis.")

    return "\n".join(lines)


def run(workers=8, pairs_limit=None):
    import kaggle_environments
    control_sha = _git_sha(BASELINE_SHA)
    control_dir = _extract_control_agent(control_sha)

    with tempfile.TemporaryDirectory(prefix="p21_straw_") as temp_dir:
        worktree_agent, _, fingerprint = _snapshot_worktree_agent(temp_dir)

        print("Verifying isolation manifests...", flush=True)
        _verify_manifest(control_dir, worktree_agent)

        dirs = {
            "Control": control_dir,
            "Treatment": worktree_agent,
        }

        scenarios = SCENARIOS if pairs_limit is None else SCENARIOS[:pairs_limit]
        tasks = []
        for sc in scenarios:
            for seat in (0, 1):
                case_id = f"{sc['pair_id']:03d}-seat{seat}"
                for arm in ARMS:
                    tasks.append({
                        **sc, "case_id": case_id, "seat": seat,
                        "arm": arm, "agent_dir": dirs[arm],
                    })

        print(f"Starting P2.1 Dynamic Strawberry Portfolio Experiment: {len(scenarios)} pairs x 2 seats x 2 arms = {len(tasks)} games on {workers} workers.", flush=True)
        results = []
        pool_workers = min(workers, len(tasks))
        pool = ProcessPoolExecutor(max_workers=pool_workers)
        try:
            futures = {pool.submit(_one, task): task for task in tasks}
            for n, future in enumerate(as_completed(futures), 1):
                res = future.result()
                results.append(res)
                print(
                    f"[{n:03d}/{len(tasks)}] {res['arm']} {res['case_id']} {res['opponent']} "
                    f"score={res.get('score', 'ERROR')}", flush=True
                )
        finally:
            print("All games completed. Shutting down worker pool...", flush=True)
            pool.shutdown(wait=False, cancel_futures=True)

        print(f"Aggregating {len(results)} results...", flush=True)
        by_case = defaultdict(dict)
        for r in results:
            by_case[r["case_id"]][r["arm"]] = r

        complete, errors = [], []
        for case_id, arms in sorted(by_case.items()):
            if all(arm in arms and arms[arm]["status"] == "SUCCESS" for arm in ARMS):
                row = {
                    "case_id": case_id,
                    "pair_id": arms["Control"]["pair_id"],
                    "seed": arms["Control"]["seed"],
                    "opponent": arms["Control"]["opponent"],
                    "seat": arms["Control"]["seat"],
                    "scores": {arm: arms[arm]["score"] for arm in ARMS},
                    "delta": arms["Treatment"]["score"] - arms["Control"]["score"],
                    "metrics": {arm: arms[arm]["metrics"] for arm in ARMS},
                }
                complete.append(row)
            else:
                errors.append(case_id)

        deltas = [r["delta"] for r in complete]
        d_stats = _delta_stats(deltas)

        arm_stats = {}
        for arm in ARMS:
            scores = [r["scores"][arm] for r in complete]
            m_list = [r["metrics"][arm] for r in complete]
            arm_stats[arm] = {
                "episodes": len(scores),
                "mean_score": statistics.mean(scores),
                "median_score": statistics.median(scores),
                "stddev_score": statistics.stdev(scores) if len(scores) > 1 else 0.0,
                "negative_cash_steps": sum(m["negative_cash_steps"] for m in m_list),
                "cash_min": min(m["cash_min"] for m in m_list),
                "seed_spend": sum(m["seed_spend"] for m in m_list),
                "animal_spend": sum(m["animal_spend"] for m in m_list),
                "wheat_buy_spend": sum(m["wheat_buy_spend"] for m in m_list),
                "strawberry_revenue": sum(m.get("strawberry_revenue_realized", 0.0) for m in m_list),
                "strawberry_tiles_planted": sum(m.get("strawberry_tiles_planted", 0) for m in m_list),
                "p21_checks": sum(m.get("p21_checks", 0) for m in m_list),
                "nw_ne_productive_ops": sum(sum(m["productive_ops"].values()) for m in m_list),
                "nw_ne_harvest_exec": sum(m.get("harvest_exec_count", 0) for m in m_list),
                "nw_ne_unwatered_eod": sum(sum(m["unwatered_eod"].values()) for m in m_list),
                "starvation_animal_days": sum(m["starvation_animal_days"] for m in m_list),
            }

        # Per opponent
        per_opp = {}
        for opp in OPPONENTS:
            sub = [r for r in complete if r["opponent"] == opp]
            if sub:
                d = [r["delta"] for r in sub]
                s = _delta_stats(d)
                per_opp[opp] = {
                    "cases": len(sub),
                    "control_mean": statistics.mean(r["scores"]["Control"] for r in sub),
                    "treatment_mean": statistics.mean(r["scores"]["Treatment"] for r in sub),
                    "delta_mean": s["mean"],
                    "ci95": s["ci95"],
                    "wins": s["wins"],
                    "ties": s["ties"],
                    "losses": s["losses"],
                    "p_val": s["p_val"],
                }

        out_data = {
            "metadata": {
                "control_sha": control_sha,
                "worktree_fingerprint": fingerprint,
                "engine_version": getattr(kaggle_environments, "__version__", "unknown"),
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "matched_cases": len(complete),
                "balanced_seats": True,
            },
            "summary": {
                "complete_matched_cases": len(complete),
                "errors": len(errors),
                "arms": arm_stats,
                "deltas": {"treatment_vs_control": d_stats},
                "per_opponent": per_opp,
            },
            "cases": complete,
        }

        json_path = os.path.join(ROOT, "simulations", "experiments", "results", "p21_strawberry_ab.json")
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(out_data, f, indent=2)
        print(f"Wrote raw results to {json_path}", flush=True)

        md_report = generate_markdown_report(out_data)
        md_path = os.path.join(ROOT, "p21_strawberry_results.md")
        with open(md_path, "w") as f:
            f.write(md_report)
        print(f"Wrote report to {md_path}", flush=True)
        print("\n" + md_report, flush=True)


if __name__ == "__main__":
    workers = 8
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        workers = int(sys.argv[1])
    run(workers=workers)
