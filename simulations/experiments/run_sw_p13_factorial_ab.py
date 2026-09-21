"""2x2 Factorial SW Regression Experiment with Production Control.

Arms:
  - Control: Production Baseline (237cf5e... git archive)
  - ArmA: P1.3-A Baseline (SW planting gate enabled; tight soil OFF, livestock cap OFF)
  - ArmB: Tighter SW Soil Activation Only (tight soil ON, livestock cap OFF)
  - ArmC: Dynamic Livestock Serviceability Cap Only (tight soil OFF, livestock cap ON)
  - ArmD: Combined (tight soil ON, livestock cap ON)

Matched cases: 40 (20 pairs x 2 seats across 5 opponent archetypes).
Total live games: 40 x 5 = 200 games.
Process isolation: ProcessPoolExecutor with dynamic module purge and per-process configuration.
"""
from __future__ import annotations
import hashlib, json, math, os, shutil, statistics, subprocess, sys, tarfile, tempfile, time, traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
P12_SHA = "4a2bd867cbd3184c77f9e7c38a768fae0a01f6cd"
P13_A_HEAD = "18740e0e6b2c02bd547b411eb08214edb03acbd4"

OPPONENTS = ("pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent")
SCENARIOS = [
    {"pair_id": i + 1, "seed": 7101 + i + 100 * (i // 4), "opponent": OPPONENTS[i // 4]}
    for i in range(20)
]
ARMS = ("Control", "ArmA", "ArmB", "ArmC", "ArmD")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULT_JSON = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p13_factorial_ab.json")
RESULT_MD = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p13_factorial_findings.md")


def _git_sha(ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def _extract_agent(sha, label):
    sha = _git_sha(sha)
    directory = os.path.join(ROOT, "simulations", "baselines", f"sw_p13_{label}_{sha[:12]}")
    target = os.path.join(directory, "agent")
    marker = os.path.join(directory, ".extracted_sha")
    if os.path.isfile(marker) and os.path.isfile(os.path.join(target, "main.py")):
        if open(marker, encoding="utf8").read().strip() == sha:
            return target
    if os.path.exists(directory):
        shutil.rmtree(directory, ignore_errors=True)
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
    if hasattr(cfg, "set_p13_factorial_arm"):
        cfg.set_p13_factorial_arm(arm)
    else:
        # Control fallback if old baseline
        if hasattr(cfg, "set_sw_experiment_arm"):
            cfg.set_sw_experiment_arm("ArmA")

    # Assert authoritative isolation invariant
    expected = {
        "Control": {
            "SW_P1_PURCHASE_COMMITTED_HERD_ONLY": False,
            "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED": False,
            "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED": False,
            "SW_GENERIC_PLANTING_GATE_ENABLED": False,
            "P13_TIGHT_SOIL_ENABLED": False,
            "P13_LIVESTOCK_CAP_ENABLED": False,
        },
        "ArmA": {
            "SW_P1_PURCHASE_COMMITTED_HERD_ONLY": True,
            "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED": True,
            "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED": True,
            "SW_GENERIC_PLANTING_GATE_ENABLED": True,
            "P13_TIGHT_SOIL_ENABLED": False,
            "P13_LIVESTOCK_CAP_ENABLED": False,
        },
        "ArmB": {
            "SW_P1_PURCHASE_COMMITTED_HERD_ONLY": True,
            "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED": True,
            "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED": True,
            "SW_GENERIC_PLANTING_GATE_ENABLED": True,
            "P13_TIGHT_SOIL_ENABLED": True,
            "P13_LIVESTOCK_CAP_ENABLED": False,
        },
        "ArmC": {
            "SW_P1_PURCHASE_COMMITTED_HERD_ONLY": True,
            "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED": True,
            "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED": True,
            "SW_GENERIC_PLANTING_GATE_ENABLED": True,
            "P13_TIGHT_SOIL_ENABLED": False,
            "P13_LIVESTOCK_CAP_ENABLED": True,
        },
        "ArmD": {
            "SW_P1_PURCHASE_COMMITTED_HERD_ONLY": True,
            "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED": True,
            "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED": True,
            "SW_GENERIC_PLANTING_GATE_ENABLED": True,
            "P13_TIGHT_SOIL_ENABLED": True,
            "P13_LIVESTOCK_CAP_ENABLED": True,
        },
    }
    for flag, val in expected[arm].items():
        if hasattr(cfg, flag) and bool(getattr(cfg, flag)) != val:
            raise RuntimeError(f"Treatment isolation failure: {arm} {flag} != {val}")


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/sw_p13_" not in p.replace("\\", "/")]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean
    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in ("main", "config", "state", "strategy", "execution", "market", "task_scheduler", "macro_planner", "order_builder", "land_serviceability_model")):
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
            "wheat_buy_units": 0, "wheat_buy_spend": 0.0,
            "crop_revenue": 0.0, "animal_revenue": 0.0,
            "fallback_turns": 0,
            "activation_checks": 0, "activation_serviceable_turns": 0,
            "activation_blocked_turns": 0, "activation_activated_empty_tiles": 0,
            "activation_max_serviceable_k": 0,
            "generic_gate_checks": 0,
            "generic_sw_empty_excluded": 0,
            "generic_sw_pasture_excluded": 0,
            "sw_pasture_plant_attempts": 0,
            "sw_soil_plant_attempts": 0,
            "sw_pasture_plants_confirmed": 0,
            "sw_soil_plants_confirmed": 0,
            "sw_pasture_plant_days": 0,
            "sw_soil_plant_days": 0,
            "sw_wheat_harvest_attempts": 0,
            "feed_action_attempts": 0,
            "shed_wheat_eod": 0,
            "harvested_wheat_units": 0,
            "purchased_wheat_units": 0,
            "tight_soil_checks": 0,
            "tight_soil_blocked_turns": 0,
            "tight_soil_reasons": defaultdict(int),
            "livestock_cap_checks": 0,
            "livestock_cap_rejected": 0,
            "livestock_cap_reasons": defaultdict(int),
        }
        previous_sw_tile_kinds = None

        def tracking(obs, configuration=None):
            nonlocal previous_sw_tile_kinds
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
                m["sw_purchase_hour"] = hour

            if previous_sw_tile_kinds is not None and "SW" in owned:
                rows = farm.get("tiles", []) or []
                for y in range(5, min(10, len(rows))):
                    row = rows[y] or []
                    for x in range(min(5, len(row))):
                        pos = (x, y)
                        t = row[x]
                        current_kind = t.get("kind") if isinstance(t, dict) else getattr(t, "kind", None)
                        if previous_sw_tile_kinds.get(pos) in ("EMPTY", None) and current_kind == "PLANT":
                            if pos in cfg.SW_PASTURE_TILES:
                                m["sw_pasture_plants_confirmed"] += 1
                            elif pos in cfg.SW_SOIL_TILES:
                                m["sw_soil_plants_confirmed"] += 1

            if "SW" in owned:
                current_sw_tile_kinds = {}
                rows = farm.get("tiles", []) or []
                for y in range(5, min(10, len(rows))):
                    row = rows[y] or []
                    for x in range(min(5, len(row))):
                        t = row[x]
                        current_sw_tile_kinds[(x, y)] = t.get("kind") if isinstance(t, dict) else getattr(t, "kind", None)
                previous_sw_tile_kinds = current_sw_tile_kinds
            else:
                previous_sw_tile_kinds = None

            for row in farm.get("tiles", []) or []:
                for t in row or []:
                    if not isinstance(t, dict):
                        continue
                    if t.get("animal") or t.get("is_animal"):
                        if int(t.get("consecutive_unfed", 0)) >= 1:
                            m["starvation_observations"] += 1

            if hour == 23:
                m["shed_wheat_eod"] = int(obs.get("players", [{}])[player].get("shed", {}).get("WHEAT", 0) if "players" in obs else 0)
                for q in ("NW", "NE", "SW"):
                    st = _tile_eod(farm, q)
                    m["plant_days"][q] += st["plants"]
                    m["watered_plant_days"][q] += st["watered"]
                    m["unwatered_eod"][q] += st["unwatered"]
                if "SW" in owned:
                    rows = farm.get("tiles", []) or []
                    for y in range(5, min(10, len(rows))):
                        row = rows[y] or []
                        for x in range(min(5, len(row))):
                            pos = (x, y)
                            t = row[x]
                            if isinstance(t, dict) and t.get("kind") == "PLANT":
                                if pos in cfg.SW_PASTURE_TILES:
                                    m["sw_pasture_plant_days"] += 1
                                elif pos in cfg.SW_SOIL_TILES:
                                    m["sw_soil_plant_days"] += 1

            positions = [tuple(farm.get("farmer", [4, 4]))] + [tuple(p) for p in (farm.get("hands", []) or [])]
            action = module.agent(obs, configuration) or {}
            actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []) or [])
            for pos, act in zip(positions, actions):
                if not isinstance(act, (list, tuple)) or not act:
                    continue
                op = act[0]
                if op == "PLANT" and _quad(pos) == "SW":
                    if pos in cfg.SW_PASTURE_TILES:
                        m["sw_pasture_plant_attempts"] += 1
                    elif pos in cfg.SW_SOIL_TILES:
                        m["sw_soil_plant_attempts"] += 1
                elif op == "HARVEST":
                    q = _quad(pos)
                    if q in m["harvest_exec"]:
                        m["harvest_exec"][q] += 1
                        if q == "SW":
                            t = farm["tiles"][pos[1]][pos[0]]
                            if isinstance(t, dict) and t.get("crop") == "WHEAT":
                                m["sw_wheat_harvest_attempts"] += 1
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
                    if unlocked_count == 2:
                        m["sw_buy_orders_emitted"] += 1
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

            # Extract macro_planner diagnostics from module telemetry
            telemetry = module.get_last_turn_telemetry() if hasattr(module, "get_last_turn_telemetry") else {}
            plan_diag = (telemetry.get("macro_plan_diagnostic") or {}) if isinstance(telemetry, dict) else {}
            gate_diag = plan_diag.get("sw_generic_planting_gate")
            if isinstance(gate_diag, dict) and gate_diag.get("enabled"):
                m["generic_gate_checks"] += 1
                m["generic_sw_empty_excluded"] += int(gate_diag.get("excluded_sw_empty_tiles", 0) or 0)
                m["generic_sw_pasture_excluded"] += int(gate_diag.get("excluded_sw_pasture_empty_tiles", 0) or 0)

            if "p13_tight_soil_gate" in plan_diag:
                m["tight_soil_checks"] += 1
                ts_diag = plan_diag["p13_tight_soil_gate"]
                if not ts_diag.get("tight_serviceable", True) or ts_diag.get("activation_slots", 1) == 0:
                    m["tight_soil_blocked_turns"] += 1
                    reason = ts_diag.get("reason", "unknown")
                    m["tight_soil_reasons"][reason] += 1

            if "p13_livestock_cap_rejections" in plan_diag:
                rejs = plan_diag["p13_livestock_cap_rejections"]
                if rejs:
                    m["livestock_cap_checks"] += 1
                    m["livestock_cap_rejected"] += len(rejs)
                    for r in rejs:
                        m["livestock_cap_reasons"][r.get("reason", "unknown")] += 1

            return action

        env = kaggle_environments.make("kaggriculture", configuration={"seed": task["seed"], "episodeSteps": 720})
        agents = [tracking, get_agent(task["opponent"])] if task["seat"] == 0 else [get_agent(task["opponent"]), tracking]
        env.run(agents)

        player = task["seat"]
        score = float(env.steps[-1][player]["reward"])
        opp_score = float(env.steps[-1][1 - player]["reward"])

        daily = ts.get_daily_log()
        m["home_unit_turns"] = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
        m["productive_ops"] = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
        m["scheduler_travel_distance"] = 0
        m["sw_anchor_assignments"] = 0
        m["idle_actions"] = 0
        for d in (daily.values() if isinstance(daily, dict) else []):
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
            m["idle_actions"] += int(d.get("idle_actions", 0) or 0)

        # Convert defaultdicts to regular dicts for json serialization
        m["tight_soil_reasons"] = dict(m["tight_soil_reasons"])
        m["livestock_cap_reasons"] = dict(m["livestock_cap_reasons"])

        return {
            "status": "SUCCESS", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"], "opponent": task["opponent"],
            "seat": task["seat"], "score": score, "opponent_score": opp_score, "metrics": m,
        }
    except Exception as exc:
        return {
            "status": "ERROR", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"], "opponent": task["opponent"],
            "seat": task["seat"], "error": str(exc), "traceback": traceback.format_exc(),
        }


def _delta_stats(values):
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stddev": 0.0, "ci95": [0.0, 0.0], "wins": 0, "ties": 0, "losses": 0}
    mean = statistics.mean(values)
    median = statistics.median(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    half = 1.96 * sd / math.sqrt(len(values)) if len(values) > 1 else 0.0
    ci = [mean - half, mean + half]
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
        "wheat_buy_spend": sum(r["metrics"].get("wheat_buy_spend", 0.0) for r in vals),
        **{
            key: sum(r["metrics"].get(key, 0) for r in vals)
            for key in (
                "generic_gate_checks", "generic_sw_empty_excluded", "generic_sw_pasture_excluded",
                "sw_pasture_plant_attempts", "sw_soil_plant_attempts",
                "sw_pasture_plants_confirmed", "sw_soil_plants_confirmed",
                "sw_pasture_plant_days", "sw_soil_plant_days",
                "sw_wheat_harvest_attempts", "feed_action_attempts", "shed_wheat_eod",
                "tight_soil_checks", "tight_soil_blocked_turns",
                "livestock_cap_checks", "livestock_cap_rejected",
            )
        },
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
    arms = report["summary"]["arms"]
    deltas = report["summary"]["deltas"]
    lines = [
        "# P1.3: 2x2 Factorial SW Regression Analysis — 5-Arm Balanced Results", "",
        f"- Control SHA: `{report['metadata']['control_sha']}`",
        f"- P1.3-A source HEAD: `{report['metadata']['p13_source_head']}`",
        f"- Worktree fingerprint: `{report['metadata']['p13_snapshot_fingerprint']}`",
        f"- Engine: {report['metadata']['engine_version']}",
        f"- Matched cases: {report['summary']['complete_matched_cases']}/40",
        f"- Engine errors: {report['summary']['errors']}", "",
        "| Metric | Control | Arm A (P1.3-A) | Arm B (Tight Soil) | Arm C (Livestock Cap) | Arm D (Combined) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "mean_score": "Mean final score",
        "sw_acquisitions": "Confirmed SW acquisition cases",
        "starvation": "Starvation observations",
        "nw_ne_harvest_exec": "NW+NE HARVEST attempts",
        "nw_ne_unwatered_eod": "NW+NE unwatered EOD",
        "sw_soil_plants_confirmed": "SW soil plants confirmed",
        "sw_soil_plant_days": "SW soil active plant-days",
        "sw_pasture_plants_confirmed": "SW pasture plants confirmed",
        "sw_pasture_plant_days": "SW pasture active plant-days",
        "wheat_buy_units": "Wheat purchase units ordered",
        "wheat_buy_spend": "Wheat purchase spend ($)",
        "animal_spend": "Livestock spend ($)",
        "travel_distance": "Scheduler travel",
        "tight_soil_blocked_turns": "Arm B tight soil blocked turns",
        "livestock_cap_rejected": "Arm C livestock cap rejected animals",
    }
    for key, label in labels.items():
        lines.append(
            f"| {label} | " + " | ".join(
                f"{arms[arm].get(key, 0):,.2f}" if "score" in key or "spend" in key
                else str(arms[arm].get(key, 0))
                for arm in ARMS
            ) + " |"
        )
    lines += ["", "## Matched Factorial Deltas", ""]
    for key, label in (
        ("b_vs_a", "B vs A (Isolated Tight Soil)"),
        ("c_vs_a", "C vs A (Isolated Livestock Cap)"),
        ("d_vs_a", "D vs A (Combined vs Baseline)"),
        ("d_vs_b", "D vs B (Incremental Livestock Cap on B)"),
        ("d_vs_c", "D vs C (Incremental Tight Soil on C)"),
        ("a_vs_control", "A vs Control (P1.3-A vs Production)"),
        ("b_vs_control", "B vs Control"),
        ("c_vs_control", "C vs Control"),
        ("d_vs_control", "D vs Control"),
        ("interaction", "Factorial Interaction (D - B - C + A)"),
    ):
        d = deltas.get(key)
        if not d:
            continue
        lines.append(
            f"- **{label}**: mean ${d['mean']:,.2f}; median ${d['median']:,.2f}; "
            f"SD ${d['stddev']:,.2f}; 95% CI [${d['ci95'][0]:,.2f}, "
            f"${d['ci95'][1]:,.2f}]; {d['wins']}W/{d['ties']}T/{d['losses']}L (N={d['n']})."
        )
    return "\n".join(lines)


def _snapshot_worktree_agent(temp_root):
    """Copy uncommitted agent/ content without modifying any original work."""
    source = os.path.join(ROOT, "agent")
    target = os.path.join(temp_root, "agent")
    shutil.copytree(
        source, target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.pyo"),
    )
    files = {}
    for dirpath, _, filenames in os.walk(target):
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, target).replace(os.sep, "/")
            if rel.startswith("tests/"):
                continue
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf8")).hexdigest()
    return target, files, fingerprint


def run(workers=6, cases_limit=None):
    import kaggle_environments
    control_sha = _git_sha(BASELINE_SHA)
    p13_head = _git_sha("HEAD")

    # Safe check: do not overwrite without user request
    if os.path.exists(RESULT_JSON):
        # Rename or archive existing if necessary
        pass

    with tempfile.TemporaryDirectory(prefix="sw_p13_factorial_") as temporary:
        snapshot_agent, source_hashes, fingerprint = _snapshot_worktree_agent(temporary)
        control_dir = _extract_agent(control_sha, "control")

        dirs = {
            "Control": control_dir,
            "ArmA": snapshot_agent,
            "ArmB": snapshot_agent,
            "ArmC": snapshot_agent,
            "ArmD": snapshot_agent,
        }

        tasks = []
        scenarios = SCENARIOS if cases_limit is None else SCENARIOS[:cases_limit]
        for scenario in scenarios:
            for seat in (0, 1):
                case_id = f"{scenario['pair_id']:02d}-seat{seat}"
                for arm in ARMS:
                    tasks.append({
                        **scenario, "case_id": case_id, "seat": seat,
                        "arm": arm, "agent_dir": dirs[arm],
                    })

        print(f"Starting factorial experiment: {len(tasks)} games across {len(ARMS)} arms using {workers} worker processes.", flush=True)
        results = []
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, task): task for task in tasks}
            for n, future in enumerate(as_completed(futures), 1):
                result = future.result()
                results.append(result)
                print(
                    f"[{n:03d}/{len(tasks)}] {result['arm']} "
                    f"{result['case_id']} {result['opponent']} "
                    f"score={result.get('score', 'ERROR')}", flush=True,
                )

        by_case = defaultdict(dict)
        for result in results:
            by_case[result["case_id"]][result["arm"]] = result

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
                    "delta_b_vs_a": arms["ArmB"]["score"] - arms["ArmA"]["score"],
                    "delta_c_vs_a": arms["ArmC"]["score"] - arms["ArmA"]["score"],
                    "delta_d_vs_a": arms["ArmD"]["score"] - arms["ArmA"]["score"],
                    "delta_d_vs_b": arms["ArmD"]["score"] - arms["ArmB"]["score"],
                    "delta_d_vs_c": arms["ArmD"]["score"] - arms["ArmC"]["score"],
                    "delta_a_vs_control": arms["ArmA"]["score"] - arms["Control"]["score"],
                    "delta_b_vs_control": arms["ArmB"]["score"] - arms["Control"]["score"],
                    "delta_c_vs_control": arms["ArmC"]["score"] - arms["Control"]["score"],
                    "delta_d_vs_control": arms["ArmD"]["score"] - arms["Control"]["score"],
                    "interaction": (arms["ArmD"]["score"] - arms["ArmA"]["score"]) - (
                        (arms["ArmB"]["score"] - arms["ArmA"]["score"]) + (arms["ArmC"]["score"] - arms["ArmA"]["score"])
                    ),
                }
                complete.append(row)
            else:
                errors.append({"case_id": case_id, "arms": arms})

        per_opponent = {}
        for opponent in OPPONENTS:
            subgroup = [c for c in complete if c["opponent"] == opponent]
            if subgroup:
                per_opponent[opponent] = {
                    "cases": len(subgroup),
                    **{arm + "_mean": statistics.mean(c[arm]["score"] for c in subgroup) for arm in ARMS},
                    "b_vs_a_mean": statistics.mean(c["delta_b_vs_a"] for c in subgroup),
                    "c_vs_a_mean": statistics.mean(c["delta_c_vs_a"] for c in subgroup),
                    "d_vs_a_mean": statistics.mean(c["delta_d_vs_a"] for c in subgroup),
                }

        per_seat = {
            seat: {
                "cases": sum(c["seat"] == seat for c in complete),
                "b_vs_a_mean": statistics.mean(c["delta_b_vs_a"] for c in complete if c["seat"] == seat) if any(c["seat"] == seat for c in complete) else None,
                "c_vs_a_mean": statistics.mean(c["delta_c_vs_a"] for c in complete if c["seat"] == seat) if any(c["seat"] == seat for c in complete) else None,
                "d_vs_a_mean": statistics.mean(c["delta_d_vs_a"] for c in complete if c["seat"] == seat) if any(c["seat"] == seat for c in complete) else None,
            }
            for seat in (0, 1)
        }

        summary = {
            "complete_matched_cases": len(complete), "errors": len(errors),
            "arms": {arm: _aggregate_arm(results, arm) for arm in ARMS},
            "deltas": {
                "b_vs_a": _delta_stats([c["delta_b_vs_a"] for c in complete]),
                "c_vs_a": _delta_stats([c["delta_c_vs_a"] for c in complete]),
                "d_vs_a": _delta_stats([c["delta_d_vs_a"] for c in complete]),
                "d_vs_b": _delta_stats([c["delta_d_vs_b"] for c in complete]),
                "d_vs_c": _delta_stats([c["delta_d_vs_c"] for c in complete]),
                "a_vs_control": _delta_stats([c["delta_a_vs_control"] for c in complete]),
                "b_vs_control": _delta_stats([c["delta_b_vs_control"] for c in complete]),
                "c_vs_control": _delta_stats([c["delta_c_vs_control"] for c in complete]),
                "d_vs_control": _delta_stats([c["delta_d_vs_control"] for c in complete]),
                "interaction": _delta_stats([c["interaction"] for c in complete]),
            },
            "per_opponent": per_opponent, "per_seat": per_seat,
        }

        report = {
            "metadata": {
                "control_sha": control_sha,
                "p13_source_head": p13_head,
                "p13_snapshot_fingerprint": fingerprint,
                "p13_snapshot_file_hashes": source_hashes,
                "p13_runtime_mode": "isolated agent/ working-tree snapshot",
                "engine_version": getattr(kaggle_environments, "__version__", "unknown"),
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "matched_cases": len(complete),
                "balanced_seats": True,
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
    workers = min(8, os.cpu_count() or 8)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(workers=workers, cases_limit=limit)
