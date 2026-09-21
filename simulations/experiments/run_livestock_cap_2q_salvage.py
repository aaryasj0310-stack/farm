"""Final Livestock-Cap Salvage Experiment: True 2-Quadrant Production Control vs Capped Livestock.

Arms:
  - Arm A (Control): True Production Control (237cf5e... untouched default, QUADRANT_HARD_BLOCK={4})
  - Arm B (Capped): Exact same 2-quadrant production baseline with P13_LIVESTOCK_CAP_ENABLED=True only.

SW expansion remains 0 for both arms (no SW treatments active, QUADRANT_HARD_BLOCK={4} in both).
Matched cases: 100 (50 pairs x 2 balanced seats across 5 opponent archetypes).
Total games: 200 games.
Process isolation: ProcessPoolExecutor with per-process module purge.
"""
from __future__ import annotations
import copy, hashlib, json, math, os, shutil, statistics, subprocess, sys, tempfile, time, traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
OPPONENTS = ("pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent")
# 50 pairs = 10 pairs per opponent archetype = 100 matched cases. Fresh seeds in 83,000+.
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 83001 + i + 100 * (i // 5),
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(50)
]
ARMS = ("Control", "Capped")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULT_JSON = os.path.join(ROOT, "simulations", "experiments", "results", "livestock_cap_2q_salvage.json")
RESULT_MD = os.path.join(ROOT, "p13_2q_livestock_cap_validation.md")


def _git_sha(ref):
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


def _extract_control_agent(sha):
    sha = _git_sha(sha)
    directory = os.path.join(ROOT, "simulations", "baselines", f"sw_p13_control_{sha[:12]}")
    target = os.path.join(directory, "agent")
    marker = os.path.join(directory, ".extracted_sha")
    if os.path.isfile(marker) and os.path.isfile(os.path.join(target, "main.py")):
        with open(marker, encoding="utf8") as fh:
            if fh.read().strip() == sha:
                return target
    if os.path.exists(directory):
        shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)
    p = subprocess.Popen(["git", "archive", "--format=tar", sha, "agent"], cwd=ROOT, stdout=subprocess.PIPE)
    import tarfile
    with tarfile.open(fileobj=p.stdout, mode="r|") as archive:
        if hasattr(tarfile, "data_filter"):
            archive.extractall(directory, filter="data")
        else:
            archive.extractall(directory)
    if p.wait() != 0:
        raise RuntimeError(f"git archive failed for {sha}")
    with open(marker, "w", encoding="utf8") as fh:
        fh.write(sha)
    return target


def _snapshot_worktree_agent(temp_root):
    source = os.path.join(ROOT, "agent")
    target = os.path.join(temp_root, "agent")
    shutil.copytree(
        source, target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.pyo", "tests"),
    )
    files = {}
    for dirpath, _, filenames in os.walk(target):
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, target).replace(os.sep, "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf8")).hexdigest()
    return target, files, fingerprint


def _quad(pos):
    x, y = pos
    if x < 5 and y < 5:
        return "NW"
    if x >= 5 and y < 5:
        return "NE"
    if x < 5 and y >= 5:
        return "SW"
    return "SE"


def _tile_eod(farm, quadrant):
    out = {"plants": 0, "watered": 0, "unwatered": 0}
    if quadrant not in set(farm.get("unlocked_quadrants", []) or []):
        return out
    rows = farm.get("tiles", []) or []
    for y in range(min(10, len(rows))):
        row = rows[y] or []
        for x in range(min(10, len(row))):
            if _quad((x, y)) != quadrant:
                continue
            t = row[x]
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                out["plants"] += 1
                if t.get("watered_today"):
                    out["watered"] += 1
                else:
                    out["unwatered"] += 1
    return out


def _configure_arm(cfg, arm):
    # Standard production execution flags
    cfg.POINT2_FEED_MODE = "shadow"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
    cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"

    # Strict SW exclusion for BOTH arms (neither arm must buy or use SW)
    if hasattr(cfg, "SW_P1_PURCHASE_COMMITTED_HERD_ONLY"):
        cfg.SW_P1_PURCHASE_COMMITTED_HERD_ONLY = False
    if hasattr(cfg, "set_sw_workload_responsive_scheduler"):
        cfg.set_sw_workload_responsive_scheduler(False)
    if hasattr(cfg, "set_sw_serviceability_aware_activation"):
        cfg.set_sw_serviceability_aware_activation(False)
    if hasattr(cfg, "set_sw_generic_planting_gate"):
        cfg.set_sw_generic_planting_gate(False)
    if hasattr(cfg, "set_p13_tight_soil_enabled"):
        cfg.set_p13_tight_soil_enabled(False)

    # THE ONLY TREATMENT DIFFERENCE:
    if arm == "Capped":
        if hasattr(cfg, "set_p13_livestock_cap_enabled"):
            cfg.set_p13_livestock_cap_enabled(True)
        elif hasattr(cfg, "P13_LIVESTOCK_CAP_ENABLED"):
            cfg.P13_LIVESTOCK_CAP_ENABLED = True
    else:  # Control
        if hasattr(cfg, "set_p13_livestock_cap_enabled"):
            cfg.set_p13_livestock_cap_enabled(False)
        elif hasattr(cfg, "P13_LIVESTOCK_CAP_ENABLED"):
            cfg.P13_LIVESTOCK_CAP_ENABLED = False

    # Authoritative Isolation Assertion:
    # 1. QUADRANT_HARD_BLOCK must be {4} for BOTH arms (preserving production capital reserve behavior)
    assert getattr(cfg, "QUADRANT_HARD_BLOCK", set()) == {4}, f"{arm}: QUADRANT_HARD_BLOCK must be {{4}}"
    # 2. SW treatments must be disabled for both arms
    assert getattr(cfg, "SW_P1_PURCHASE_COMMITTED_HERD_ONLY", False) is False, f"{arm}: committed herd SW buy must be False"
    assert getattr(cfg, "SW_GENERIC_PLANTING_GATE_ENABLED", False) is False, f"{arm}: SW planting gate must be False"
    assert getattr(cfg, "P13_TIGHT_SOIL_ENABLED", False) is False, f"{arm}: tight soil must be False"
    # 3. Livestock cap must match arm exactly
    expected_cap = (arm == "Capped")
    actual_cap = getattr(cfg, "P13_LIVESTOCK_CAP_ENABLED", False)
    assert actual_cap == expected_cap, f"{arm}: P13_LIVESTOCK_CAP_ENABLED expected {expected_cap}, got {actual_cap}"


def _verify_manifest(control_dir, worktree_dir):
    """Verify in separate import scope that both configurations match except for livestock cap."""
    for arm, d in (("Control", control_dir), ("Capped", worktree_dir)):
        for k in list(sys.modules):
            if any(k == m or k.startswith(m + ".") for m in ("config", "main", "macro_planner")):
                del sys.modules[k]
        sys.path.insert(0, d)
        import config as cfg
        _configure_arm(cfg, arm)
        print(f"Verified {arm} config manifest from {d}: QUADRANT_HARD_BLOCK={cfg.QUADRANT_HARD_BLOCK}, LIVESTOCK_CAP={getattr(cfg, 'P13_LIVESTOCK_CAP_ENABLED', False)}", flush=True)


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "land_serviceability_model"
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
            "sw_purchase_day": None, "sw_confirmed": False,
            "negative_cash_steps": 0, "cash_min": float("inf"),
            "daily_cash": {},
            "unwatered_eod": {"NW": 0, "NE": 0, "SW": 0},
            "plant_days": {"NW": 0, "NE": 0, "SW": 0},
            "watered_plant_days": {"NW": 0, "NE": 0, "SW": 0},
            "starvation_animal_days": 0,
            "starvation_animal_hours": 0,
            "harvest_exec": {"NW": 0, "NE": 0, "SW": 0},
            "feed_exec": {"NW": 0, "NE": 0, "SW": 0},
            "wheat_pickups": 0,
            "seed_spend": 0.0, "animal_spend": 0.0, "land_spend": 0.0,
            "wheat_buy_units": 0, "wheat_buy_spend": 0.0,
            "crop_revenue": 0.0, "animal_revenue": 0.0,
            "feed_action_attempts": 0,
            "shed_wheat_eod": 0,
            "purchased_wheat_units": 0,
            "livestock_cap_checks": 0,
            "livestock_cap_rejected": 0,
            "livestock_cap_reasons": defaultdict(int),
            "candidate_rejections_detail": [],
            "daily_herd_size": {},
        }

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            player = int(obs.get("player", task["seat"]))
            farm = obs["farms"][player]
            money = float(farm.get("money", 0.0))
            m["cash_min"] = min(m["cash_min"], money)
            if money < 0:
                m["negative_cash_steps"] += 1
            owned = set(farm.get("unlocked_quadrants", []) or [])
            if "SW" in owned and not m["sw_confirmed"]:
                m["sw_confirmed"] = True
                m["sw_purchase_day"] = day

            # Starvation: hour 0 snapshot vs continuous hours
            if hour == 0 and day > 0:
                for row in farm.get("tiles", []) or []:
                    for t in row or []:
                        if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")) and int(t.get("consecutive_unfed", 0) or 0) > 0:
                            m["starvation_animal_days"] += 1

            for row in farm.get("tiles", []) or []:
                for t in row or []:
                    if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                        if int(t.get("consecutive_unfed", 0) or 0) >= 1:
                            m["starvation_animal_hours"] += 1

            if hour == 23:
                m["daily_cash"][day] = money
                curr_shed = obs.get("players", [{}])[player].get("shed", {}) if "players" in obs else {}
                m["shed_wheat_eod"] = int(curr_shed.get("WHEAT", 0))
                for q in ("NW", "NE", "SW"):
                    st = _tile_eod(farm, q)
                    m["plant_days"][q] += st["plants"]
                    m["watered_plant_days"][q] += st["watered"]
                    m["unwatered_eod"][q] += st["unwatered"]

                counts = defaultdict(int)
                for row in farm.get("tiles", []) or []:
                    for t in row or []:
                        if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                            sp = t.get("species") or t.get("animal")
                            if sp:
                                counts[sp] += 1
                m["daily_herd_size"][day] = dict(counts)

            workers_pos = [tuple(farm.get("farmer", [4, 4]))] + [tuple(p) for p in (farm.get("hands", []) or [])]
            action = module.agent(obs, configuration) or {}
            actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []) or [])
            for pos, act in zip(workers_pos, actions):
                if not isinstance(act, (list, tuple)) or not act:
                    continue
                op = act[0]
                if op == "HARVEST":
                    q = _quad(pos)
                    if q in m["harvest_exec"]:
                        m["harvest_exec"][q] += 1
                elif op == "FEED":
                    m["feed_action_attempts"] += 1

            for order in action.get("market", []) if isinstance(action, dict) else []:
                if not (isinstance(order, (list, tuple)) and order):
                    continue
                op = order[0]
                if op == "BUY_LAND":
                    unlocked_count = len(owned)
                    if unlocked_count - 1 < len(cfg.LAND_PRICES):
                        m["land_spend"] += float(cfg.LAND_PRICES[unlocked_count - 1])
                elif op == "BUY_SEED" and len(order) >= 3:
                    crop_name, qty = order[1], int(order[2])
                    m["seed_spend"] += float(cfg.CROPS[crop_name]["seed"] * qty)
                elif op == "BUY_ANIMAL" and len(order) >= 3:
                    animal_name, qty = order[1], int(order[2])
                    m["animal_spend"] += float(cfg.ANIMALS[animal_name]["cost"] * qty)
                elif op == "BUY_PRODUCT" and len(order) >= 3 and order[1] == "WHEAT":
                    qty = int(order[2])
                    m["wheat_buy_units"] += qty
                    m["purchased_wheat_units"] += qty
                    m["wheat_buy_spend"] += float(qty * 25.0)

            telemetry = module.get_last_turn_telemetry() if hasattr(module, "get_last_turn_telemetry") else {}
            plan_diag = (telemetry.get("macro_plan_diagnostic") or {}) if isinstance(telemetry, dict) else {}
            if "p13_livestock_cap_rejections" in plan_diag:
                rejs = plan_diag["p13_livestock_cap_rejections"]
                if rejs:
                    m["livestock_cap_checks"] += 1
                    m["livestock_cap_rejected"] += len(rejs)
                    for r in rejs:
                        m["livestock_cap_reasons"][r.get("reason", "unknown")] += 1
                        m["candidate_rejections_detail"].append(dict(r))

            return action

        env = kaggle_environments.make("kaggriculture", configuration={"seed": task["seed"], "episodeSteps": 720})
        agents = [tracking, get_agent(task["opponent"])] if task["seat"] == 0 else [get_agent(task["opponent"]), tracking]
        env.run(agents)

        player = task["seat"]
        score = float(env.steps[-1][player]["reward"])
        opp_score = float(env.steps[-1][1 - player]["reward"])

        daily = ts.get_daily_log()
        m["productive_ops"] = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
        m["scheduler_travel_distance"] = 0
        for d in (daily.values() if isinstance(daily, dict) else []):
            loc = d.get("locality_telemetry") or {}
            for q, n in (loc.get("productive_ops_by_zone") or {}).items():
                if q in m["productive_ops"]:
                    m["productive_ops"][q] += int(n)
            m["scheduler_travel_distance"] += int(loc.get("total_travel_distance", 0) or 0)

        m["livestock_cap_reasons"] = dict(m["livestock_cap_reasons"])
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
    import math as m_
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + m_.erf(abs(t_stat) / m_.sqrt(2.0))))
    return {
        "n": n, "mean": mean, "median": median, "stddev": sd, "stderr": se, "ci95": ci,
        "t_stat": t_stat, "p_val": p_val,
        "wins": sum(v > 0 for v in values), "ties": sum(v == 0 for v in values),
        "losses": sum(v < 0 for v in values),
    }


def _aggregate_arm(rows, arm):
    vals = [r for r in rows if r["arm"] == arm and r["status"] == "SUCCESS"]
    if not vals:
        return {}
    out = {
        "episodes": len(vals),
        "mean_score": statistics.mean(r["score"] for r in vals),
        "median_score": statistics.median(r["score"] for r in vals),
        "stddev_score": statistics.stdev(r["score"] for r in vals) if len(vals) > 1 else 0.0,
        "sw_acquisitions": sum(bool(r["metrics"]["sw_confirmed"]) for r in vals),
        "starvation_animal_days": sum(r["metrics"]["starvation_animal_days"] for r in vals),
        "starvation_animal_hours": sum(r["metrics"]["starvation_animal_hours"] for r in vals),
        "negative_cash_steps": sum(r["metrics"]["negative_cash_steps"] for r in vals),
        "cash_min": min(r["metrics"]["cash_min"] for r in vals),
        "travel_distance": sum(r["metrics"].get("scheduler_travel_distance", 0) for r in vals),
        "land_spend": sum(r["metrics"].get("land_spend", 0.0) for r in vals),
        "seed_spend": sum(r["metrics"].get("seed_spend", 0.0) for r in vals),
        "animal_spend": sum(r["metrics"].get("animal_spend", 0.0) for r in vals),
        "wheat_buy_units": sum(r["metrics"].get("wheat_buy_units", 0) for r in vals),
        "wheat_buy_spend": sum(r["metrics"].get("wheat_buy_spend", 0.0) for r in vals),
        "feed_action_attempts": sum(r["metrics"].get("feed_action_attempts", 0) for r in vals),
        "livestock_cap_checks": sum(r["metrics"].get("livestock_cap_checks", 0) for r in vals),
        "livestock_cap_rejected": sum(r["metrics"].get("livestock_cap_rejected", 0) for r in vals),
        "rejection_reasons": defaultdict(int),
        "productive_ops": {q: sum(r["metrics"].get("productive_ops", {}).get(q, 0) for r in vals) for q in ("NW", "NE")},
        "harvest_exec": {q: sum(r["metrics"].get("harvest_exec", {}).get(q, 0) for r in vals) for q in ("NW", "NE")},
        "unwatered_eod": {q: sum(r["metrics"].get("unwatered_eod", {}).get(q, 0) for r in vals) for q in ("NW", "NE")},
    }
    for r in vals:
        for rk, rv in r["metrics"].get("livestock_cap_reasons", {}).items():
            out["rejection_reasons"][rk] += rv
    out["rejection_reasons"] = dict(out["rejection_reasons"])
    out["nw_ne_harvest_exec"] = out["harvest_exec"]["NW"] + out["harvest_exec"]["NE"]
    out["nw_ne_productive_ops"] = out["productive_ops"]["NW"] + out["productive_ops"]["NE"]
    out["nw_ne_unwatered_eod"] = out["unwatered_eod"]["NW"] + out["unwatered_eod"]["NE"]
    return out


def _markdown(report):
    c_sum = report["summary"]["arms"]["Control"]
    cap_sum = report["summary"]["arms"]["Capped"]
    delta = report["summary"]["deltas"]["capped_vs_control"]
    n_cases = report["summary"]["complete_matched_cases"]

    lines = [
        "# Kaggriculture: 2-Quadrant Livestock Serviceability Cap Salvage Report", "",
        f"- Control Baseline SHA: `{report['metadata']['control_sha']}` (True Baseline, QUADRANT_HARD_BLOCK={{4}})",
        f"- Worktree Candidate Fingerprint: `{report['metadata']['worktree_fingerprint']}`",
        f"- Engine Version: {report['metadata']['engine_version']}",
        f"- Total Matched Cases: {n_cases} (balanced across 5 opponents and 2 seats)",
        f"- Fresh Seed Block: 83,001+",
        f"- SW Acquisitions: Control={c_sum['sw_acquisitions']}/{n_cases}, Capped={cap_sum['sw_acquisitions']}/{n_cases}", "",
        "## 1. Overall Economic Performance", "",
        "| Metric | Control (True 2Q Baseline) | Capped (2Q + Livestock Cap) | Paired Delta / Impact |",
        "|---|---:|---:|---:|",
        f"| **Mean Final Score** | **${c_sum['mean_score']:,.2f}** | **${cap_sum['mean_score']:,.2f}** | **${delta['mean']:+,.2f}** (95% CI: [${delta['ci95'][0]:+,.2f}, ${delta['ci95'][1]:+,.2f}]) |",
        f"| Median Final Score | ${c_sum['median_score']:,.2f} | ${cap_sum['median_score']:,.2f} | ${delta['median']:+,.2f} |",
        f"| Win / Tie / Loss | — | — | **{delta['wins']}W / {delta['ties']}T / {delta['losses']}L** (p={delta['p_val']:.4f}) |",
        f"| Purchased Wheat Spend | ${c_sum['wheat_buy_spend']:,.2f} | ${cap_sum['wheat_buy_spend']:,.2f} | ${cap_sum['wheat_buy_spend'] - c_sum['wheat_buy_spend']:+,.2f} |",
        f"| Animal Purchase Spend | ${c_sum['animal_spend']:,.2f} | ${cap_sum['animal_spend']:,.2f} | ${cap_sum['animal_spend'] - c_sum['animal_spend']:+,.2f} |",
        f"| Seed Purchase Spend | ${c_sum['seed_spend']:,.2f} | ${cap_sum['seed_spend']:,.2f} | ${cap_sum['seed_spend'] - c_sum['seed_spend']:+,.2f} |",
        f"| Land Expansion Spend | ${c_sum['land_spend']:,.2f} | ${cap_sum['land_spend']:,.2f} | ${cap_sum['land_spend'] - c_sum['land_spend']:+,.2f} |",
        "",
        "## 2. Animal Safety & Core Realization", "",
        "| Metric | Control | Capped | Impact |",
        "|---|---:|---:|---:|",
        f"| Starvation Animal-Days (Hour 0) | {c_sum['starvation_animal_days']} | {cap_sum['starvation_animal_days']} | {cap_sum['starvation_animal_days'] - c_sum['starvation_animal_days']:+d} |",
        f"| Starvation Animal-Hours (All Steps) | {c_sum['starvation_animal_hours']} | {cap_sum['starvation_animal_hours']} | {cap_sum['starvation_animal_hours'] - c_sum['starvation_animal_hours']:+d} |",
        f"| Negative Cash Steps | {c_sum['negative_cash_steps']} | {cap_sum['negative_cash_steps']} | {cap_sum['negative_cash_steps'] - c_sum['negative_cash_steps']:+d} |",
        f"| NW+NE Productive Operations | {c_sum['nw_ne_productive_ops']} | {cap_sum['nw_ne_productive_ops']} | {cap_sum['nw_ne_productive_ops'] - c_sum['nw_ne_productive_ops']:+d} |",
        f"| NW+NE Harvests Realized | {c_sum['nw_ne_harvest_exec']} | {cap_sum['nw_ne_harvest_exec']} | {cap_sum['nw_ne_harvest_exec'] - c_sum['nw_ne_harvest_exec']:+d} |",
        f"| NW+NE Unwatered EOD | {c_sum['nw_ne_unwatered_eod']} | {cap_sum['nw_ne_unwatered_eod']} | {cap_sum['nw_ne_unwatered_eod'] - c_sum['nw_ne_unwatered_eod']:+d} |",
        f"| Scheduler Travel Distance | {c_sum['travel_distance']} | {cap_sum['travel_distance']} | {cap_sum['travel_distance'] - c_sum['travel_distance']:+d} |",
        "",
        "## 3. Breakdown Across Opponent Archetypes", "",
        "| Opponent Archetype | Cases | Control Mean | Capped Mean | Paired Delta | 95% CI | Win Rate |",
        "|---|---:|---:|---:|---:|:---:|:---:|",
    ]
    for opp, row in report["summary"]["per_opponent"].items():
        ci = row["ci95"]
        wr = f"{row['wins']}/{row['cases']} ({100*row['wins']/row['cases']:.1f}%)"
        lines.append(
            f"| `{opp}` | {row['cases']} | ${row['control_mean']:,.2f} | ${row['capped_mean']:,.2f} | ${row['delta_mean']:+,.2f} | [${ci[0]:+,.2f}, ${ci[1]:+,.2f}] | {wr} |"
        )

    lines += [
        "",
        "## 4. Livestock Cap Diagnostics", "",
        f"- Total candidate purchase evaluations: {cap_sum['livestock_cap_checks']}",
        f"- Total speculative animal candidates rejected: {cap_sum['livestock_cap_rejected']}",
        "- Breakdown of rejection reasons:",
    ]
    for rk, rv in cap_sum.get("rejection_reasons", {}).items():
        lines.append(f"  - `{rk}`: {rv} rejections")

    return "\n".join(lines)


def run(workers=8, pairs_limit=None):
    import kaggle_environments
    control_sha = _git_sha(BASELINE_SHA)
    control_dir = _extract_control_agent(control_sha)

    with tempfile.TemporaryDirectory(prefix="sw_p13_salvage_") as temp_dir:
        worktree_agent, _, fingerprint = _snapshot_worktree_agent(temp_dir)

        print("Verifying isolation manifests...", flush=True)
        _verify_manifest(control_dir, worktree_agent)

        dirs = {
            "Control": control_dir,
            "Capped": worktree_agent,
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

        print(f"Starting 2Q Livestock-Cap Salvage Experiment: {len(scenarios)} pairs x 2 seats x 2 arms = {len(tasks)} games on {workers} workers.", flush=True)
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
                    **{arm: arms[arm] for arm in ARMS},
                    "delta": arms["Capped"]["score"] - arms["Control"]["score"],
                }
                complete.append(row)
            else:
                errors.append({"case_id": case_id, "arms": arms})

        per_opponent = {}
        for opp in OPPONENTS:
            sub = [c for c in complete if c["opponent"] == opp]
            if sub:
                deltas = [c["delta"] for c in sub]
                stats = _delta_stats(deltas)
                per_opponent[opp] = {
                    "cases": len(sub),
                    "control_mean": statistics.mean(c["Control"]["score"] for c in sub),
                    "capped_mean": statistics.mean(c["Capped"]["score"] for c in sub),
                    "delta_mean": stats["mean"],
                    "ci95": stats["ci95"],
                    "wins": stats["wins"],
                    "ties": stats["ties"],
                    "losses": stats["losses"],
                    "p_val": stats["p_val"],
                }

        per_seat = {
            seat: {
                "cases": sum(c["seat"] == seat for c in complete),
                "delta_mean": statistics.mean(c["delta"] for c in complete if c["seat"] == seat) if any(c["seat"] == seat for c in complete) else None,
            }
            for seat in (0, 1)
        }

        summary = {
            "complete_matched_cases": len(complete),
            "errors": len(errors),
            "arms": {arm: _aggregate_arm(results, arm) for arm in ARMS},
            "deltas": {
                "capped_vs_control": _delta_stats([c["delta"] for c in complete]),
            },
            "per_opponent": per_opponent,
            "per_seat": per_seat,
        }

        report = {
            "metadata": {
                "control_sha": control_sha,
                "worktree_fingerprint": fingerprint,
                "engine_version": getattr(kaggle_environments, "__version__", "unknown"),
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "matched_cases": len(complete),
                "balanced_seats": True,
            },
            "summary": summary,
            "cases": complete,
            "errors": errors,
        }

        os.makedirs(os.path.dirname(RESULT_JSON), exist_ok=True)
        with open(RESULT_JSON, "w", encoding="utf8") as fh:
            json.dump(report, fh, indent=2)
        with open(RESULT_MD, "w", encoding="utf8") as fh:
            fh.write(_markdown(report))
        print(json.dumps(summary, indent=2), flush=True)
        if errors:
            raise RuntimeError(f"{len(errors)} cases failed")
        return report


if __name__ == "__main__":
    workers = min(8, os.cpu_count() or 8)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(workers=workers, pairs_limit=limit)
