"""Fresh Held-Out Production Validation: True Production Control vs Arm C Candidate.

Matched evaluation on 200 cases (100 fresh pairs x 2 balanced seats across 5 opponents)
comparing:
  - Control: True Production Baseline (237cf5e... with QUADRANT_HARD_BLOCK={4} default)
  - Candidate: Frozen Arm C Candidate (P1.3-A Planting Gate + Dynamic Livestock Serviceability Cap)

Zero overlap with prior experiment seeds.
ProcessPoolExecutor isolation with fresh module loads and state purging.
"""
from __future__ import annotations
import copy, hashlib, json, math, os, shutil, statistics, subprocess, sys, tempfile, time, traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
CANDIDATE_FROZEN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "baselines", "candidate_p13_c_frozen", "agent")
)

OPPONENTS = ("pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent")
# 100 pairs = 20 pairs per opponent archetype. Fresh seed block in 81,000+.
SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 81001 + i + 100 * (i // 5),
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(100)
]
ARMS = ("Control", "Candidate")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULT_JSON = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p13_heldout_validation.json")
RESULT_MD = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p13_heldout_validation.md")


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

    if arm == "Candidate":
        if hasattr(cfg, "set_p13_factorial_arm"):
            cfg.set_p13_factorial_arm("ArmC")
        else:
            # Candidate frozen defaults
            if hasattr(cfg, "SW_GENERIC_PLANTING_GATE_ENABLED"):
                cfg.SW_GENERIC_PLANTING_GATE_ENABLED = True
            if hasattr(cfg, "P13_LIVESTOCK_CAP_ENABLED"):
                cfg.P13_LIVESTOCK_CAP_ENABLED = True
            if hasattr(cfg, "P13_TIGHT_SOIL_ENABLED"):
                cfg.P13_TIGHT_SOIL_ENABLED = False
            if hasattr(cfg, "SW_P1_PURCHASE_COMMITTED_HERD_ONLY"):
                cfg.SW_P1_PURCHASE_COMMITTED_HERD_ONLY = True
            if hasattr(cfg, "set_sw_workload_responsive_scheduler"):
                cfg.set_sw_workload_responsive_scheduler(True)
            if hasattr(cfg, "set_sw_serviceability_aware_activation"):
                cfg.set_sw_serviceability_aware_activation(True)

        # Candidate Invariant Assertions
        assert getattr(cfg, "SW_GENERIC_PLANTING_GATE_ENABLED", False) is True, "Candidate must have planting gate ON"
        assert getattr(cfg, "P13_LIVESTOCK_CAP_ENABLED", False) is True, "Candidate must have livestock cap ON"
        assert getattr(cfg, "P13_TIGHT_SOIL_ENABLED", True) is False, "Candidate must have tight soil OFF"
        assert getattr(cfg, "QUADRANT_HARD_BLOCK", set()) == {4}, "Candidate must have QUADRANT_HARD_BLOCK == {4}"

    elif arm == "Control":
        # CRITICAL: Do NOT call set_sw_experiment_arm("ArmA")!
        # True Control must preserve its production default QUADRANT_HARD_BLOCK == {4}.
        assert getattr(cfg, "QUADRANT_HARD_BLOCK", set()) == {4}, "Control must have baseline QUADRANT_HARD_BLOCK == {4}"
        assert getattr(cfg, "SW_GENERIC_PLANTING_GATE_ENABLED", False) is False, "Control must have planting gate OFF"
        assert getattr(cfg, "P13_LIVESTOCK_CAP_ENABLED", False) is False, "Control must have livestock cap OFF"


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
            "sw_purchase_day": None, "sw_purchase_hour": None, "sw_confirmed": False,
            "sw_buy_orders_emitted": 0, "negative_cash_steps": 0, "cash_min": float("inf"),
            "daily_cash": {},
            "unwatered_eod": {"NW": 0, "NE": 0, "SW": 0},
            "plant_days": {"NW": 0, "NE": 0, "SW": 0},
            "watered_plant_days": {"NW": 0, "NE": 0, "SW": 0},
            "starvation_animal_days": 0,
            "starvation_animal_hours": 0,
            "harvest_exec": {"NW": 0, "NE": 0, "SW": 0},
            "feed_exec": {"NW": 0, "NE": 0, "SW": 0},
            "wheat_pickups": 0, "move_actions": 0,
            "seed_spend": 0.0, "animal_spend": 0.0, "land_spend": 0.0,
            "wheat_buy_units": 0, "wheat_buy_spend": 0.0,
            "crop_revenue": 0.0, "animal_revenue": 0.0,
            "units_sold": defaultdict(int),
            "rev_by_product": defaultdict(float),
            "fallback_turns": 0,
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
            "sw_crop_mix": defaultdict(int),
            "sw_worker_turns": 0,
            "feed_action_attempts": 0,
            "shed_wheat_eod": 0,
            "harvested_wheat_units": 0,
            "purchased_wheat_units": 0,
            "livestock_cap_checks": 0,
            "livestock_cap_rejected": 0,
            "livestock_cap_reasons": defaultdict(int),
            "candidate_rejections_detail": [],
            "daily_herd_size": {},
        }
        previous_sw_tile_kinds = None
        last_money = None
        last_shed = None

        def tracking(obs, configuration=None):
            nonlocal previous_sw_tile_kinds, last_money, last_shed
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

            # Count workers in SW
            workers_pos = [tuple(farm.get("farmer", [4, 4]))] + [tuple(p) for p in (farm.get("hands", []) or [])]
            for wp in workers_pos:
                if _quad(wp) == "SW":
                    m["sw_worker_turns"] += 1

            # Starvation audit:
            # 1. animal-days: at hour 0
            if hour == 0 and day > 0:
                for row in farm.get("tiles", []) or []:
                    for t in row or []:
                        if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")) and int(t.get("consecutive_unfed", 0) or 0) > 0:
                            m["starvation_animal_days"] += 1

            # 2. animal-hours: continuous across every hour
            for row in farm.get("tiles", []) or []:
                for t in row or []:
                    if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                        if int(t.get("consecutive_unfed", 0) or 0) >= 1:
                            m["starvation_animal_hours"] += 1

            # Track SW plant confirmations
            if previous_sw_tile_kinds is not None and "SW" in owned:
                rows = farm.get("tiles", []) or []
                for y in range(5, min(10, len(rows))):
                    row = rows[y] or []
                    for x in range(min(5, len(row))):
                        pos = (x, y)
                        t = row[x]
                        current_kind = t.get("kind") if isinstance(t, dict) else getattr(t, "kind", None)
                        if previous_sw_tile_kinds.get(pos) in ("EMPTY", None) and current_kind == "PLANT":
                            c_type = t.get("crop") if isinstance(t, dict) else getattr(t, "crop", "WHEAT")
                            m["sw_crop_mix"][c_type] += 1
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

            # EOD tracking
            if hour == 23:
                m["daily_cash"][day] = money
                curr_shed = obs.get("players", [{}])[player].get("shed", {}) if "players" in obs else {}
                m["shed_wheat_eod"] = int(curr_shed.get("WHEAT", 0))
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

                # Herd size snapshot
                counts = defaultdict(int)
                for row in farm.get("tiles", []) or []:
                    for t in row or []:
                        if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                            sp = t.get("species") or t.get("animal")
                            if sp:
                                counts[sp] += 1
                m["daily_herd_size"][day] = dict(counts)

            # Revenue tracking from market sales
            curr_shed = obs.get("players", [{}])[player].get("shed", {}) if "players" in obs else {}
            if last_money is not None and last_shed is not None:
                dm = money - last_money
                if dm > 0:
                    sold = {}
                    for item, count in last_shed.items():
                        diff = count - int(curr_shed.get(item, 0))
                        if diff > 0:
                            sold[item] = diff
                    if len(sold) == 1:
                        item = list(sold.keys())[0]
                        m["units_sold"][item] += sold[item]
                        m["rev_by_product"][item] += dm
                    elif len(sold) > 1:
                        base_prices = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
                        total_base = sum(base_prices.get(k, 25) * qty for k, qty in sold.items())
                        for item, qty in sold.items():
                            share = (base_prices.get(item, 25) * qty) / max(1.0, total_base)
                            m["units_sold"][item] += qty
                            m["rev_by_product"][item] += dm * share

            last_money = money
            last_shed = dict(curr_shed)

            # Agent decision
            action = module.agent(obs, configuration) or {}
            actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []) or [])
            for pos, act in zip(workers_pos, actions):
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

            # Telemetry diagnostics
            telemetry = module.get_last_turn_telemetry() if hasattr(module, "get_last_turn_telemetry") else {}
            plan_diag = (telemetry.get("macro_plan_diagnostic") or {}) if isinstance(telemetry, dict) else {}
            gate_diag = plan_diag.get("sw_generic_planting_gate")
            if isinstance(gate_diag, dict) and gate_diag.get("enabled"):
                m["generic_gate_checks"] += 1
                m["generic_sw_empty_excluded"] += int(gate_diag.get("excluded_sw_empty_tiles", 0) or 0)
                m["generic_sw_pasture_excluded"] += int(gate_diag.get("excluded_sw_pasture_empty_tiles", 0) or 0)

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

        # Compute realized revenues
        m["crop_revenue"] = sum(m["rev_by_product"][c] for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"))
        m["animal_revenue"] = sum(m["rev_by_product"][a] for a in ("MILK", "WOOL", "EGG"))

        # Convert dicts
        m["units_sold"] = dict(m["units_sold"])
        m["rev_by_product"] = dict(m["rev_by_product"])
        m["sw_crop_mix"] = dict(m["sw_crop_mix"])
        m["livestock_cap_reasons"] = dict(m["livestock_cap_reasons"])

        return {
            "status": "SUCCESS", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"],
            "opponent": task["opponent"], "seat": task["seat"],
            "score": score, "opponent_score": opp_score,
            "metrics": m,
        }
    except Exception as exc:
        tb = traceback.format_exc()
        return {
            "status": "ERROR", "arm": task["arm"], "pair_id": task["pair_id"],
            "case_id": task["case_id"], "seed": task["seed"],
            "opponent": task["opponent"], "seat": task["seat"],
            "error": str(exc), "traceback": tb,
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
    # Two-tailed p-value approximation via normal distribution if n >= 30
    import math as m_
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + m_.erf(abs(t_stat) / m_.sqrt(2.0))))
    wins = sum(v > 0 for v in values)
    ties = sum(v == 0 for v in values)
    losses = sum(v < 0 for v in values)
    return {
        "n": n, "mean": mean, "median": median, "stddev": sd, "stderr": se, "ci95": ci,
        "t_stat": t_stat, "p_val": p_val, "wins": wins, "ties": ties, "losses": losses,
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
        "crop_revenue": sum(r["metrics"].get("crop_revenue", 0.0) for r in vals),
        "animal_revenue": sum(r["metrics"].get("animal_revenue", 0.0) for r in vals),
        "sw_soil_plants_confirmed": sum(r["metrics"].get("sw_soil_plants_confirmed", 0) for r in vals),
        "sw_soil_plant_days": sum(r["metrics"].get("sw_soil_plant_days", 0) for r in vals),
        "sw_pasture_plants_confirmed": sum(r["metrics"].get("sw_pasture_plants_confirmed", 0) for r in vals),
        "sw_pasture_plant_days": sum(r["metrics"].get("sw_pasture_plant_days", 0) for r in vals),
        "sw_wheat_harvest_attempts": sum(r["metrics"].get("sw_wheat_harvest_attempts", 0) for r in vals),
        "sw_worker_turns": sum(r["metrics"].get("sw_worker_turns", 0) for r in vals),
        "feed_action_attempts": sum(r["metrics"].get("feed_action_attempts", 0) for r in vals),
        "livestock_cap_checks": sum(r["metrics"].get("livestock_cap_checks", 0) for r in vals),
        "livestock_cap_rejected": sum(r["metrics"].get("livestock_cap_rejected", 0) for r in vals),
        "rejection_reasons": defaultdict(int),
        "home_unit_turns": {q: sum(r["metrics"].get("home_unit_turns", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW", "SE")},
        "productive_ops": {q: sum(r["metrics"].get("productive_ops", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW", "SE")},
        "harvest_exec": {q: sum(r["metrics"].get("harvest_exec", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW")},
        "unwatered_eod": {q: sum(r["metrics"].get("unwatered_eod", {}).get(q, 0) for r in vals) for q in ("NW", "NE", "SW")},
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
    cand_sum = report["summary"]["arms"]["Candidate"]
    delta = report["summary"]["deltas"]["candidate_vs_control"]
    n_cases = report["summary"]["complete_matched_cases"]

    lines = [
        "# Kaggriculture: Fresh Held-Out Production Validation Report", "",
        f"- Control SHA: `{report['metadata']['control_sha']}` (True Baseline, QUADRANT_HARD_BLOCK={{4}})",
        f"- Candidate Snapshot Fingerprint: `{report['metadata']['candidate_fingerprint']}`",
        f"- Engine Version: {report['metadata']['engine_version']}",
        f"- Total Matched Cases: {n_cases} (balanced across 5 opponents and 2 seats)",
        f"- Fresh Seed Block: 81,001+",
        f"- Errors: {report['summary']['errors']}", "",
        "## 1. Overall Economic Comparison", "",
        "| Metric | Control (True Baseline) | Candidate (P1.3-C) | Paired Delta / Impact |",
        "|---|---:|---:|---:|",
        f"| **Mean Final Score** | **${c_sum['mean_score']:,.2f}** | **${cand_sum['mean_score']:,.2f}** | **${delta['mean']:+,.2f}** (95% CI: [${delta['ci95'][0]:+,.2f}, ${delta['ci95'][1]:+,.2f}]) |",
        f"| Median Final Score | ${c_sum['median_score']:,.2f} | ${cand_sum['median_score']:,.2f} | ${delta['median']:+,.2f} |",
        f"| Win / Tie / Loss | — | — | **{delta['wins']}W / {delta['ties']}T / {delta['losses']}L** (p={delta['p_val']:.4f}) |",
        f"| Confirmed SW Acquisitions | {c_sum['sw_acquisitions']} / {n_cases} | {cand_sum['sw_acquisitions']} / {n_cases} | {cand_sum['sw_acquisitions'] - c_sum['sw_acquisitions']:+d} cases |",
        f"| Realized Crop Revenue | ${c_sum['crop_revenue']:,.2f} | ${cand_sum['crop_revenue']:,.2f} | ${cand_sum['crop_revenue'] - c_sum['crop_revenue']:+,.2f} |",
        f"| Realized Animal Revenue | ${c_sum['animal_revenue']:,.2f} | ${cand_sum['animal_revenue']:,.2f} | ${cand_sum['animal_revenue'] - c_sum['animal_revenue']:+,.2f} |",
        f"| Purchased Wheat Spend | ${c_sum['wheat_buy_spend']:,.2f} | ${cand_sum['wheat_buy_spend']:,.2f} | ${cand_sum['wheat_buy_spend'] - c_sum['wheat_buy_spend']:+,.2f} |",
        f"| Animal Purchase Spend | ${c_sum['animal_spend']:,.2f} | ${cand_sum['animal_spend']:,.2f} | ${cand_sum['animal_spend'] - c_sum['animal_spend']:+,.2f} |",
        f"| Land Expansion Spend | ${c_sum['land_spend']:,.2f} | ${cand_sum['land_spend']:,.2f} | ${cand_sum['land_spend'] - c_sum['land_spend']:+,.2f} |",
        f"| Seed Purchase Spend | ${c_sum['seed_spend']:,.2f} | ${cand_sum['seed_spend']:,.2f} | ${cand_sum['seed_spend'] - c_sum['seed_spend']:+,.2f} |",
        "",
        "## 2. Animal Safety & Workload Realization", "",
        "| Safety / Operational Metric | Control | Candidate (P1.3-C) | Difference |",
        "|---|---:|---:|---:|",
        f"| Starvation Animal-Days (Hour 0) | {c_sum['starvation_animal_days']} | {cand_sum['starvation_animal_days']} | {cand_sum['starvation_animal_days'] - c_sum['starvation_animal_days']:+d} |",
        f"| Starvation Animal-Hours (All Steps) | {c_sum['starvation_animal_hours']} | {cand_sum['starvation_animal_hours']} | {cand_sum['starvation_animal_hours'] - c_sum['starvation_animal_hours']:+d} |",
        f"| Negative Cash Steps | {c_sum['negative_cash_steps']} | {cand_sum['negative_cash_steps']} | {cand_sum['negative_cash_steps'] - c_sum['negative_cash_steps']:+d} |",
        f"| NW+NE Productive Operations | {c_sum['nw_ne_productive_ops']} | {cand_sum['nw_ne_productive_ops']} | {cand_sum['nw_ne_productive_ops'] - c_sum['nw_ne_productive_ops']:+d} |",
        f"| NW+NE Harvests Executed | {c_sum['nw_ne_harvest_exec']} | {cand_sum['nw_ne_harvest_exec']} | {cand_sum['nw_ne_harvest_exec'] - c_sum['nw_ne_harvest_exec']:+d} |",
        f"| NW+NE Unwatered EOD | {c_sum['nw_ne_unwatered_eod']} | {cand_sum['nw_ne_unwatered_eod']} | {cand_sum['nw_ne_unwatered_eod'] - c_sum['nw_ne_unwatered_eod']:+d} |",
        f"| Scheduler Travel Distance | {c_sum['travel_distance']} | {cand_sum['travel_distance']} | {cand_sum['travel_distance'] - c_sum['travel_distance']:+d} |",
        f"| SW Worker Turns | {c_sum['sw_worker_turns']} | {cand_sum['sw_worker_turns']} | {cand_sum['sw_worker_turns'] - c_sum['sw_worker_turns']:+d} |",
        "",
        "## 3. Performance Across Opponent Archetypes", "",
        "| Opponent Archetype | Cases | Control Mean | Candidate Mean | Paired Delta | 95% CI | Win Rate |",
        "|---|---:|---:|---:|---:|:---:|:---:|",
    ]
    for opp, row in report["summary"]["per_opponent"].items():
        ci = row["ci95"]
        wr = f"{row['wins']}/{row['cases']} ({100*row['wins']/row['cases']:.1f}%)"
        lines.append(
            f"| `{opp}` | {row['cases']} | ${row['control_mean']:,.2f} | ${row['candidate_mean']:,.2f} | ${row['delta_mean']:+,.2f} | [${ci[0]:+,.2f}, ${ci[1]:+,.2f}] | {wr} |"
        )

    lines += [
        "",
        "## 4. Livestock Serviceability Cap Diagnostics", "",
        f"- Total candidate purchase evaluations: {cand_sum['livestock_cap_checks']}",
        f"- Total speculative animal candidates rejected: {cand_sum['livestock_cap_rejected']}",
        "- Breakdown of rejection reasons:",
    ]
    for rk, rv in cand_sum.get("rejection_reasons", {}).items():
        lines.append(f"  - `{rk}`: {rv} rejections")

    return "\n".join(lines)


def run(workers=8, pairs_limit=None):
    import kaggle_environments
    control_sha = _git_sha(BASELINE_SHA)
    control_dir = _extract_control_agent(control_sha)
    candidate_dir = CANDIDATE_FROZEN_DIR

    with open(os.path.join(os.path.dirname(CANDIDATE_FROZEN_DIR), ".snapshot_fingerprint")) as fh:
        cand_fingerprint = fh.read().strip()

    dirs = {
        "Control": control_dir,
        "Candidate": candidate_dir,
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

    print(f"Starting Fresh Held-Out Validation: {len(scenarios)} pairs x 2 seats x 2 arms = {len(tasks)} games on {workers} workers.", flush=True)
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
                "delta": arms["Candidate"]["score"] - arms["Control"]["score"],
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
                "candidate_mean": statistics.mean(c["Candidate"]["score"] for c in sub),
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
            "candidate_vs_control": _delta_stats([c["delta"] for c in complete]),
        },
        "per_opponent": per_opponent,
        "per_seat": per_seat,
    }

    report = {
        "metadata": {
            "control_sha": control_sha,
            "candidate_fingerprint": cand_fingerprint,
            "candidate_snapshot_dir": candidate_dir,
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
