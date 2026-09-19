"""Balanced-seat four-arm SW expansion experiment.

Control = exact production baseline.
P1 = exact validated purchase-only correction.
P1.1 = exact validated responsive-scheduler treatment.
P1.2 = current branch runtime with P1 + P1.1 + serviceability-aware activation.
"""
from __future__ import annotations
import json, math, os, shutil, statistics, subprocess, sys, tarfile, time, traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
P1_SHA = "b89c8381b341d43c9e81e0701fd8d39edbc8aaaa"
P11_SHA = "b44a1d2f754bc6ecb66077033a2bf44350146bab"
OPPONENTS = ("pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent")
SCENARIOS = [
    {"pair_id": i + 1, "seed": 7101 + i + 100 * (i // 4), "opponent": OPPONENTS[i // 4]}
    for i in range(20)
]
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULT_JSON = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p1_serviceability_activation_4arm_balanced.json")
RESULT_MD = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p1_serviceability_activation_results.md")


def _git_sha(ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def _extract_agent(sha, label):
    sha = _git_sha(sha)
    directory = os.path.join(ROOT, "simulations", "baselines", f"sw_p12_{label}_{sha[:12]}")
    target = os.path.join(directory, "agent")
    marker = os.path.join(directory, ".extracted_sha")
    if os.path.isfile(marker) and os.path.isfile(os.path.join(target, "main.py")):
        if open(marker, encoding="utf8").read().strip() == sha:
            return target
    if os.path.isdir(directory):
        shutil.rmtree(directory)
    os.makedirs(directory, exist_ok=True)
    p = subprocess.Popen(["git", "archive", "--format=tar", sha, "agent"], cwd=ROOT, stdout=subprocess.PIPE)
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
    cfg.POINT2_FEED_MODE = "shadow"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
    cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"
    if hasattr(cfg, "SW_P1_PURCHASE_COMMITTED_HERD_ONLY"):
        cfg.SW_P1_PURCHASE_COMMITTED_HERD_ONLY = arm in ("P1", "P1.1", "P1.2")
    if hasattr(cfg, "set_sw_workload_responsive_scheduler"):
        cfg.set_sw_workload_responsive_scheduler(arm in ("P1.1", "P1.2"))
    if hasattr(cfg, "set_sw_serviceability_aware_activation"):
        cfg.set_sw_serviceability_aware_activation(arm == "P1.2")
    elif hasattr(cfg, "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED"):
        cfg.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED = arm == "P1.2"


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/sw_p12_" not in p.replace("\\", "/")]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in ("main", "config", "state", "strategy", "execution", "market", "task_scheduler", "macro_planner", "order_builder")):
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
            "sw_purchase_day": None, "sw_purchase_hour": None, "sw_confirmed": False,
            "sw_buy_orders_emitted": 0, "negative_cash_steps": 0, "cash_min": float("inf"),
            "unwatered_eod": {"NW": 0, "NE": 0, "SW": 0},
            "plant_days": {"NW": 0, "NE": 0, "SW": 0},
            "watered_plant_days": {"NW": 0, "NE": 0, "SW": 0},
            "starvation_observations": 0,
            "harvest_exec": {"NW": 0, "NE": 0, "SW": 0},
            "feed_exec": {"NW": 0, "NE": 0, "SW": 0},
            "wheat_pickups": 0, "move_actions": 0,
            "seed_spend": 0.0, "animal_spend": 0.0, "land_spend": 0.0,
            "wheat_buy_units": 0, "fallback_turns": 0,
            "activation_checks": 0, "activation_serviceable_turns": 0,
            "activation_blocked_turns": 0, "activation_activated_empty_tiles": 0,
            "activation_max_serviceable_k": 0,
        }

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            player = int(obs.get("player", task["seat"]))
            farm = obs["farms"][player]
            owned = set(farm.get("unlocked_quadrants", []) or [])
            cash = float(farm.get("money", 0) or 0)
            m["cash_min"] = min(m["cash_min"], cash)
            if cash < 0:
                m["negative_cash_steps"] += 1
            if "SW" in owned and m["sw_purchase_day"] is None:
                m["sw_purchase_day"], m["sw_purchase_hour"], m["sw_confirmed"] = day, hour, True

            if hour == 0 and day > 0:
                for row in farm.get("tiles", []) or []:
                    for t in row or []:
                        if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")) and int(t.get("consecutive_unfed", 0) or 0) > 0:
                            m["starvation_observations"] += 1

            if hour == 23:
                for q in ("NW", "NE", "SW"):
                    snap = _tile_eod(farm, q)
                    m["unwatered_eod"][q] += snap["unwatered"]
                    m["plant_days"][q] += snap["plants"]
                    m["watered_plant_days"][q] += snap["watered"]

            positions = [tuple(farm.get("farmer", [4, 4]))] + [tuple(p) for p in (farm.get("hands", []) or [])]
            action = module.agent(obs, configuration) or {}
            if action.get("_emergency_fallback"):
                m["fallback_turns"] += 1
            actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []) or [])
            for pos, act in zip(positions, actions):
                if not isinstance(act, (list, tuple)) or not act:
                    continue
                op = act[0]
                if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                    m["move_actions"] += 1
                elif op == "HARVEST":
                    q = _quad(pos)
                    if q in m["harvest_exec"]:
                        m["harvest_exec"][q] += 1
                elif op == "FEED":
                    q = _quad(pos)
                    if q in m["feed_exec"]:
                        m["feed_exec"][q] += 1
                elif op == "PICKUP" and len(act) >= 2 and act[1] == "WHEAT":
                    m["wheat_pickups"] += int(act[2]) if len(act) >= 3 else 1

            telemetry = module.get_last_turn_telemetry() or {}
            act_diag = (telemetry.get("macro_plan_diagnostic") or {}).get("sw_serviceability_activation")
            if isinstance(act_diag, dict) and act_diag.get("enabled"):
                m["activation_checks"] += 1
                if act_diag.get("is_serviceable"):
                    m["activation_serviceable_turns"] += 1
                else:
                    m["activation_blocked_turns"] += 1
                m["activation_activated_empty_tiles"] += int(act_diag.get("activated_empty_tiles", 0) or 0)
                m["activation_max_serviceable_k"] = max(
                    m["activation_max_serviceable_k"],
                    int(act_diag.get("serviceable_k", 0) or 0),
                )

            for order in action.get("market", []) or []:
                if not isinstance(order, (list, tuple)) or not order:
                    continue
                kind = order[0]
                if kind == "BUY_LAND":
                    n_extra = max(0, len(owned) - 1)
                    if n_extra < len(cfg.LAND_PRICES):
                        m["land_spend"] += float(cfg.LAND_PRICES[n_extra])
                    m["sw_buy_orders_emitted"] += int("NE" in owned and "SW" not in owned)
                elif kind == "BUY_SEED" and len(order) >= 3:
                    crop, n = order[1], int(order[2])
                    if crop in cfg.CROPS:
                        m["seed_spend"] += float(cfg.CROPS[crop]["seed"] * n)
                elif kind == "BUY_ANIMAL" and len(order) >= 3:
                    animal, n = order[1], int(order[2])
                    if animal in cfg.ANIMALS:
                        m["animal_spend"] += float(cfg.ANIMALS[animal]["cost"] * n)
                elif kind == "BUY_PRODUCT" and len(order) >= 3 and order[1] == "WHEAT":
                    m["wheat_buy_units"] += int(order[2])
            return action

        env = kaggle_environments.make("kaggriculture", configuration={"seed": task["seed"], "episodeSteps": 720}, debug=False)
        opponent = get_agent(task["opponent"])
        agents = [tracking, opponent] if task["seat"] == 0 else [opponent, tracking]
        started = time.time()
        steps = env.run(agents)
        final = steps[-1]
        score = float(final[task["seat"]].get("reward", 0) or 0)
        opponent_score = float(final[1 - task["seat"]].get("reward", 0) or 0)

        daily = ts.get_daily_log()
        m["home_unit_turns"] = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
        m["productive_ops"] = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
        m["scheduler_travel_distance"] = 0
        m["sw_anchor_assignments"] = 0
        m["idle_actions"] = 0
        m["sw_tasks_created"] = 0
        m["sw_tasks_completed"] = 0
        for d in daily.values():
            for q, n in (d.get("home_unit_turns") or {}).items():
                if q in m["home_unit_turns"]:
                    m["home_unit_turns"][q] += int(n)
            loc = d.get("locality_telemetry") or {}
            for q, n in (loc.get("productive_ops_by_zone") or {}).items():
                if q in m["productive_ops"]:
                    m["productive_ops"][q] += int(n)
            m["scheduler_travel_distance"] += int(loc.get("total_travel_distance", 0) or 0)
            sw = d.get("sw_telemetry") or {}
            m["sw_anchor_assignments"] += int(sw.get("sw_anchor_assignments", 0) or 0)
            m["sw_tasks_created"] += int(sw.get("sw_tasks_created", 0) or 0)
            m["sw_tasks_completed"] += int(sw.get("sw_tasks_completed", 0) or 0)
            m["idle_actions"] += int(d.get("idle_actions", 0) or 0)

        return {
            "status": "SUCCESS", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"], "opponent": task["opponent"],
            "seat": task["seat"], "score": score, "opponent_score": opponent_score,
            "metrics": m, "elapsed_seconds": round(time.time() - started, 2), "episode_steps": len(steps),
        }
    except Exception as exc:
        traceback.print_exc()
        return {
            "status": "ERROR", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"], "opponent": task["opponent"],
            "seat": task["seat"], "error": repr(exc),
        }


def _delta_stats(values):
    if not values:
        return {}
    mean = statistics.mean(values)
    median = statistics.median(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    if len(values) > 1:
        se = sd / math.sqrt(len(values))
        try:
            from scipy.stats import t
            crit = float(t.ppf(0.975, len(values) - 1))
        except Exception:
            crit = 1.96
        ci = [mean - crit * se, mean + crit * se]
    else:
        ci = [mean, mean]
    return {
        "n": len(values), "mean": mean, "median": median, "stddev": sd, "ci95": ci,
        "wins": sum(v > 0 for v in values), "ties": sum(v == 0 for v in values),
        "losses": sum(v < 0 for v in values),
    }


def _aggregate_arm(rows, arm):
    vals = [r for r in rows if r["arm"] == arm and r["status"] == "SUCCESS"]
    out = {
        "episodes": len(vals),
        "mean_score": statistics.mean(r["score"] for r in vals) if vals else None,
        "sw_acquisitions": sum(bool(r["metrics"]["sw_confirmed"]) for r in vals),
        "starvation": sum(r["metrics"]["starvation_observations"] for r in vals),
        "negative_cash": sum(r["metrics"]["negative_cash_steps"] for r in vals),
        "sw_anchor_assignments": sum(r["metrics"].get("sw_anchor_assignments", 0) for r in vals),
        "travel_distance": sum(r["metrics"].get("scheduler_travel_distance", 0) for r in vals),
        "land_spend": sum(r["metrics"].get("land_spend", 0.0) for r in vals),
        "seed_spend": sum(r["metrics"].get("seed_spend", 0.0) for r in vals),
        "animal_spend": sum(r["metrics"].get("animal_spend", 0.0) for r in vals),
        "wheat_buy_units": sum(r["metrics"].get("wheat_buy_units", 0) for r in vals),
        "activation_checks": sum(r["metrics"].get("activation_checks", 0) for r in vals),
        "activation_serviceable_turns": sum(r["metrics"].get("activation_serviceable_turns", 0) for r in vals),
        "activation_blocked_turns": sum(r["metrics"].get("activation_blocked_turns", 0) for r in vals),
        "activation_activated_empty_tiles": sum(r["metrics"].get("activation_activated_empty_tiles", 0) for r in vals),
        "home_unit_turns": {q: sum(r["metrics"].get("home_unit_turns", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW", "SE")},
        "productive_ops": {q: sum(r["metrics"].get("productive_ops", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW", "SE")},
        "harvest_exec": {q: sum(r["metrics"].get("harvest_exec", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW")},
        "unwatered_eod": {q: sum(r["metrics"].get("unwatered_eod", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW")},
    }
    out["nw_ne_harvest_exec"] = out["harvest_exec"]["NW"] + out["harvest_exec"]["NE"]
    out["nw_ne_productive_ops"] = out["productive_ops"]["NW"] + out["productive_ops"]["NE"]
    out["nw_ne_unwatered_eod"] = out["unwatered_eod"]["NW"] + out["unwatered_eod"]["NE"]
    return out


def _markdown(report):
    s, arms = report["summary"], report["summary"]["arms"]
    lines = [
        "# SW P1.2 Serviceability-Aware Activation — Balanced Four-Arm Results", "",
        f"- Control SHA: `{report['metadata']['control_sha']}`",
        f"- P1 SHA: `{report['metadata']['p1_sha']}`",
        f"- P1.1 SHA: `{report['metadata']['p11_sha']}`",
        f"- P1.2 SHA: `{report['metadata']['p12_sha']}`",
        f"- Engine: `{report['metadata']['engine_version']}`",
        f"- Balanced cases: {report['metadata']['matched_cases']} per arm (20 seeds × 2 seats)", "",
        "## Aggregate results", "",
        "| Metric | Control | P1 | P1.1 | P1.2 |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| Mean score | USD {arms['Control']['mean_score']:,.2f} | USD {arms['P1']['mean_score']:,.2f} | USD {arms['P1.1']['mean_score']:,.2f} | USD {arms['P1.2']['mean_score']:,.2f} |",
        f"| Confirmed SW acquisitions | {arms['Control']['sw_acquisitions']} | {arms['P1']['sw_acquisitions']} | {arms['P1.1']['sw_acquisitions']} | {arms['P1.2']['sw_acquisitions']} |",
        f"| Starvation observations | {arms['Control']['starvation']} | {arms['P1']['starvation']} | {arms['P1.1']['starvation']} | {arms['P1.2']['starvation']} |",
        f"| NW+NE unwatered EOD | {arms['Control']['nw_ne_unwatered_eod']} | {arms['P1']['nw_ne_unwatered_eod']} | {arms['P1.1']['nw_ne_unwatered_eod']} | {arms['P1.2']['nw_ne_unwatered_eod']} |",
        f"| NW+NE harvest executions | {arms['Control']['nw_ne_harvest_exec']} | {arms['P1']['nw_ne_harvest_exec']} | {arms['P1.1']['nw_ne_harvest_exec']} | {arms['P1.2']['nw_ne_harvest_exec']} |",
        f"| SW home-unit turns | {arms['Control']['home_unit_turns']['SW']} | {arms['P1']['home_unit_turns']['SW']} | {arms['P1.1']['home_unit_turns']['SW']} | {arms['P1.2']['home_unit_turns']['SW']} |",
        f"| SW anchor assignments | {arms['Control']['sw_anchor_assignments']} | {arms['P1']['sw_anchor_assignments']} | {arms['P1.1']['sw_anchor_assignments']} | {arms['P1.2']['sw_anchor_assignments']} |",
        f"| Travel distance | {arms['Control']['travel_distance']} | {arms['P1']['travel_distance']} | {arms['P1.1']['travel_distance']} | {arms['P1.2']['travel_distance']} |",
        f"| Activation blocked turns | {arms['Control']['activation_blocked_turns']} | {arms['P1']['activation_blocked_turns']} | {arms['P1.1']['activation_blocked_turns']} | {arms['P1.2']['activation_blocked_turns']} |", "",
        "## Matched score deltas", "",
    ]
    for key, label in (
        ("p1_vs_control", "P1 - Control"),
        ("p11_vs_control", "P1.1 - Control"),
        ("p12_vs_control", "P1.2 - Control"),
        ("p12_vs_p11", "P1.2 - P1.1"),
        ("p12_vs_p1", "P1.2 - P1"),
    ):
        d = s["deltas"][key]
        lines.append(
            f"- **{label}:** mean USD {d['mean']:,.2f}, median USD {d['median']:,.2f}, "
            f"95% CI [{d['ci95'][0]:,.2f}, {d['ci95'][1]:,.2f}], "
            f"{d['wins']}W/{d['ties']}T/{d['losses']}L."
        )
    lines += [
        "", "## Guardrails", "",
        "- P1.1 changes scheduler home-zone allocation only; MacroPlanner SW activation remains unchanged.",
        "- P1.2 adds only serviceability-aware SW activation on top of P1.1.",
        "- SW land cost is USD 2,000.",
        "- Harvest counts are executed HARVEST actions, not provenance-traced SW revenue.",
        "- Purchasing and non-purchasing cases remain in the denominator.",
        "- This is a causal screen, not an automatic production promotion.", "",
    ]
    return "\n".join(lines)


def run(workers=6):
    import kaggle_environments
    control_sha, p1_sha, p11_sha, p12_sha = (
        _git_sha(BASELINE_SHA),
        _git_sha(P1_SHA),
        _git_sha(P11_SHA),
        _git_sha("HEAD"),
    )
    dirs = {
        "Control": _extract_agent(control_sha, "control"),
        "P1": _extract_agent(p1_sha, "p1"),
        "P1.1": _extract_agent(p11_sha, "p11"),
        "P1.2": _extract_agent(p12_sha, "p12"),
    }
    tasks = []
    for sc in SCENARIOS:
        for seat in (0, 1):
            case_id = f"{sc['pair_id']:02d}-seat{seat}"
            for arm in ("Control", "P1", "P1.1", "P1.2"):
                tasks.append({**sc, "case_id": case_id, "seat": seat, "arm": arm, "agent_dir": dirs[arm]})

    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, t): t for t in tasks}
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            results.append(res)
            print(f"[{i:03d}/{len(tasks)}] {res['arm']} {res['case_id']} {res['opponent']} score={res.get('score', 'ERROR')}", flush=True)

    by_case = defaultdict(dict)
    for r in results:
        by_case[r["case_id"]][r["arm"]] = r
    complete, errors = [], []
    for case_id, arms in sorted(by_case.items()):
        if all(a in arms and arms[a]["status"] == "SUCCESS" for a in ("Control", "P1", "P1.1", "P1.2")):
            complete.append({
                "case_id": case_id, "pair_id": arms["Control"]["pair_id"],
                "seed": arms["Control"]["seed"], "opponent": arms["Control"]["opponent"],
                "seat": arms["Control"]["seat"], "Control": arms["Control"], "P1": arms["P1"], "P1.1": arms["P1.1"], "P1.2": arms["P1.2"],
                "delta_p1_control": arms["P1"]["score"] - arms["Control"]["score"],
                "delta_p11_control": arms["P1.1"]["score"] - arms["Control"]["score"],
                "delta_p11_p1": arms["P1.1"]["score"] - arms["P1"]["score"],
                "delta_p12_control": arms["P1.2"]["score"] - arms["Control"]["score"],
                "delta_p12_p11": arms["P1.2"]["score"] - arms["P1.1"]["score"],
                "delta_p12_p1": arms["P1.2"]["score"] - arms["P1"]["score"],
            })
        else:
            errors.append({"case_id": case_id, "arms": arms})

    per_opponent = {}
    for opp in OPPONENTS:
        sub = [x for x in complete if x["opponent"] == opp]
        per_opponent[opp] = {
            "cases": len(sub),
            "control_mean": statistics.mean(x["Control"]["score"] for x in sub) if sub else None,
            "p1_mean": statistics.mean(x["P1"]["score"] for x in sub) if sub else None,
            "p11_mean": statistics.mean(x["P1.1"]["score"] for x in sub) if sub else None,
            "p12_mean": statistics.mean(x["P1.2"]["score"] for x in sub) if sub else None,
            "p11_vs_control_mean": statistics.mean(x["delta_p11_control"] for x in sub) if sub else None,
            "p11_vs_p1_mean": statistics.mean(x["delta_p11_p1"] for x in sub) if sub else None,
            "p12_vs_control_mean": statistics.mean(x["delta_p12_control"] for x in sub) if sub else None,
            "p12_vs_p11_mean": statistics.mean(x["delta_p12_p11"] for x in sub) if sub else None,
        }

    summary = {
        "complete_matched_cases": len(complete), "errors": len(errors),
        "arms": {arm: _aggregate_arm(results, arm) for arm in ("Control", "P1", "P1.1", "P1.2")},
        "deltas": {
            "p1_vs_control": _delta_stats([x["delta_p1_control"] for x in complete]),
            "p11_vs_control": _delta_stats([x["delta_p11_control"] for x in complete]),
            "p11_vs_p1": _delta_stats([x["delta_p11_p1"] for x in complete]),
            "p12_vs_control": _delta_stats([x["delta_p12_control"] for x in complete]),
            "p12_vs_p11": _delta_stats([x["delta_p12_p11"] for x in complete]),
            "p12_vs_p1": _delta_stats([x["delta_p12_p1"] for x in complete]),
        },
        "per_opponent": per_opponent,
    }
    report = {
        "metadata": {
            "control_sha": control_sha, "p1_sha": p1_sha, "p11_sha": p11_sha, "p12_sha": p12_sha,
            "engine_version": getattr(kaggle_environments, "__version__", "unknown"),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "matched_cases": 40, "balanced_seats": True, "sw_land_cost": 2000,
            "p11_change": "P1 purchase correction + workload-responsive scheduler only; MacroPlanner activation unchanged",
            "p12_change": "P1.1 + serviceability-aware SW activation using responsive capacity; P2 and crop policy unchanged",
        },
        "summary": summary, "cases": complete, "errors": errors,
    }
    os.makedirs(os.path.dirname(RESULT_JSON), exist_ok=True)
    with open(RESULT_JSON, "w", encoding="utf8") as fh:
        json.dump(report, fh, indent=2)
    with open(RESULT_MD, "w", encoding="utf8") as fh:
        fh.write(_markdown(report))
    print(json.dumps(summary, indent=2), flush=True)
    if errors:
        raise RuntimeError(f"{len(errors)} matched cases incomplete")
    return report


if __name__ == "__main__":
    run(min(6, os.cpu_count() or 6))
