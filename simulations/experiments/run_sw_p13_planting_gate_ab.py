"""Balanced-seat three-arm P1.3-A experiment (no strategy changes).

Control and P1.2 are immutable, exact historical git archives.
P1.3-A is an isolated snapshot of the current agent/ WORKTREE (not git
archive HEAD), so uncommitted local treatments remain testable and no commit
or push is required. Never overwrite historical result files.
"""
from __future__ import annotations
import hashlib, json, math, os, shutil, statistics, subprocess, sys, tarfile, tempfile, time, traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
P12_SHA = "4a2bd867cbd3184c77f9e7c38a768fae0a01f6cd"
OPPONENTS = ("pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent")
SCENARIOS = [
    {"pair_id": i + 1, "seed": 7101 + i + 100 * (i // 4), "opponent": OPPONENTS[i // 4]}
    for i in range(20)
]
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULT_JSON = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p13_planting_gate_ab.json")
RESULT_MD = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p13_planting_gate_findings.md")


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
        raise RuntimeError(f"Refusing to overwrite existing baseline snapshot: {directory}")
    os.makedirs(directory, exist_ok=False)
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
    # Keep historical shared setup identical to the prior balanced experiment.
    cfg.POINT2_FEED_MODE = "shadow"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
    cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"
    if hasattr(cfg, "SW_P1_PURCHASE_COMMITTED_HERD_ONLY"):
        cfg.SW_P1_PURCHASE_COMMITTED_HERD_ONLY = arm in ("P1.2", "P1.3-A")
    if hasattr(cfg, "set_sw_workload_responsive_scheduler"):
        cfg.set_sw_workload_responsive_scheduler(arm in ("P1.2", "P1.3-A"))
    if hasattr(cfg, "set_sw_serviceability_aware_activation"):
        cfg.set_sw_serviceability_aware_activation(arm in ("P1.2", "P1.3-A"))
    if arm == "P1.3-A":
        if not hasattr(cfg, "set_sw_generic_planting_gate"):
            raise RuntimeError("P1.3-A snapshot is missing the new planting gate")
        cfg.set_sw_generic_planting_gate(True)
    elif hasattr(cfg, "set_sw_generic_planting_gate"):
        cfg.set_sw_generic_planting_gate(False)

    expected = {
        "SW_P1_PURCHASE_COMMITTED_HERD_ONLY": arm != "Control",
        "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED": arm != "Control",
        "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED": arm != "Control",
        "SW_GENERIC_PLANTING_GATE_ENABLED": arm == "P1.3-A",
    }
    for flag, value in expected.items():
        if hasattr(cfg, flag) and bool(getattr(cfg, flag)) != value:
            raise RuntimeError(f"Treatment isolation failure: {arm} {flag} != {value}")
    if arm == "P1.3-A" and not all(hasattr(cfg, flag) for flag in expected):
        raise RuntimeError("P1.3-A snapshot does not have all four treatment switches")


def _one(task):
    agent_dir = task["agent_dir"]
    clean = [p for p in sys.path if "simulations/baselines/sw_p13_" not in p.replace("\\", "/")]
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
        }
        previous_sw_tile_kinds = None

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

            if "SW" in owned:
                tiles = farm.get("tiles", []) or []
                current_sw_tile_kinds = {}
                for y in range(5, min(10, len(tiles))):
                    for x in range(min(5, len(tiles[y] or []))):
                        t = tiles[y][x]
                        kind = t.get("kind") if isinstance(t, dict) else t
                        current_sw_tile_kinds[(x, y)] = kind
                        if (previous_sw_tile_kinds is not None
                                and previous_sw_tile_kinds.get((x, y)) == "EMPTY"
                                and kind == "PLANT"):
                            region = "pasture" if (x, y) in cfg.SW_PASTURE_TILES else "soil"
                            m[f"sw_{region}_plants_confirmed"] += 1
                previous_sw_tile_kinds = current_sw_tile_kinds

            if hour == 23:
                for q in ("NW", "NE", "SW"):
                    snap = _tile_eod(farm, q)
                    m["unwatered_eod"][q] += snap["unwatered"]
                    m["plant_days"][q] += snap["plants"]
                    m["watered_plant_days"][q] += snap["watered"]
                if "SW" in owned:
                    for y in range(5, min(10, len(farm.get("tiles", [])))):
                        for x in range(min(5, len(farm["tiles"][y] or []))):
                            t = farm["tiles"][y][x]
                            if isinstance(t, dict) and t.get("kind") == "PLANT":
                                region = "pasture" if (x, y) in cfg.SW_PASTURE_TILES else "soil"
                                m[f"sw_{region}_plant_days"] += 1
                m["shed_wheat_eod"] += int((obs.get("private") or {}).get("shed", {}).get("WHEAT", 0) or 0)

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
                elif op == "PLANT" and _quad(pos) == "SW":
                    region = "pasture" if pos in cfg.SW_PASTURE_TILES else "soil"
                    m[f"sw_{region}_plant_attempts"] += 1
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

            gate_diag = (telemetry.get("macro_plan_diagnostic") or {}).get("sw_generic_planting_gate")
            if isinstance(gate_diag, dict) and gate_diag.get("enabled"):
                m["generic_gate_checks"] += 1
                m["generic_sw_empty_excluded"] += int(gate_diag.get("excluded_sw_empty_tiles", 0) or 0)
                m["generic_sw_pasture_excluded"] += int(
                    gate_diag.get("excluded_sw_pasture_empty_tiles", 0) or 0
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
        **{
            key: sum(r["metrics"].get(key, 0) for r in vals)
            for key in (
                "generic_gate_checks", "generic_sw_empty_excluded", "generic_sw_pasture_excluded",
                "sw_pasture_plant_attempts", "sw_soil_plant_attempts",
                "sw_pasture_plants_confirmed", "sw_soil_plants_confirmed",
                "sw_pasture_plant_days", "sw_soil_plant_days",
                "sw_wheat_harvest_attempts", "feed_action_attempts", "shed_wheat_eod",
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
        "# P1.3-A: Isolated SW Generic Planting Gate — Balanced Three-Arm Results", "",
        f"- Control SHA: `{report['metadata']['control_sha']}`",
        f"- P1.2 SHA: `{report['metadata']['p12_sha']}`",
        f"- P1.3-A source HEAD: `{report['metadata']['p13_source_head']}`",
        f"- P1.3-A worktree fingerprint: `{report['metadata']['p13_snapshot_fingerprint']}`",
        f"- Engine: {report['metadata']['engine_version']}",
        f"- Matched cases: {report['summary']['complete_matched_cases']}/40",
        f"- Engine errors: {report['summary']['errors']}", "",
        "| Metric | Control | P1.2 | P1.3-A |",
        "|---|---:|---:|---:|",
    ]
    labels = {
        "mean_score": "Mean final score",
        "sw_acquisitions": "Confirmed SW acquisition cases",
        "starvation": "Starvation observations",
        "nw_ne_harvest_exec": "NW+NE HARVEST attempts",
        "nw_ne_unwatered_eod": "NW+NE unwatered EOD",
        "sw_pasture_plants_confirmed": "SW pasture plants confirmed from next observation",
        "sw_pasture_plant_days": "SW pasture active plant-days",
        "sw_soil_plant_days": "SW soil active plant-days",
        "sw_wheat_harvest_attempts": "SW wheat HARVEST attempts",
        "wheat_buy_units": "Wheat purchase units ordered",
        "travel_distance": "Scheduler travel",
        "sw_anchor_assignments": "SW idle anchor assignments",
        "generic_gate_checks": "Generic SW gate checks",
    }
    for key, label in labels.items():
        lines.append(
            f"| {label} | " + " | ".join(
                f"{arms[arm].get(key, 0):,.2f}" if key == "mean_score"
                else str(arms[arm].get(key, 0))
                for arm in ("Control", "P1.2", "P1.3-A")
            ) + " |"
        )
    lines += ["", "## Matched scores", ""]
    for key in ("p13_vs_p12", "p13_vs_control", "p12_vs_control"):
        d = deltas[key]
        lines.append(
            f"- {key}: mean ${d['mean']:,.2f}; median ${d['median']:,.2f}; "
            f"SD ${d['stddev']:,.2f}; 95% CI [${d['ci95'][0]:,.2f}, "
            f"${d['ci95'][1]:,.2f}]; {d['wins']}W/{d['ties']}T/{d['losses']}L (N={d['n']})."
        )
    lines += [
        "", "## Interpretation guardrails", "",
        "- Only the generic SW planting gate differs between P1.2 and P1.3-A.",
        "- Harvest/plant action counters are attempts; confirmed planting is measured from next observations.",
        "- Excluded generic SW empty tiles are repeated decision opportunities, not unique successful plantings.",
        "- All non-purchasing cases remain in the paired denominator.",
        "- Do not merge on the basis of this screen alone.", "",
    ]
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
    cfgpath = os.path.join(target, "config.py")
    with open(cfgpath, encoding="utf8") as fh:
        content = fh.read()
    if "SW_GENERIC_PLANTING_GATE_ENABLED = False" not in content:
        raise RuntimeError("Snapshot does not contain the default-off P1.3-A gate")
    with open(os.path.join(target, "strategy", "macro_planner.py"), encoding="utf8") as fh:
        if 'plan.diagnostics["sw_generic_planting_gate"]' not in fh.read():
            raise RuntimeError("Snapshot does not contain the P1.3-A planting restriction")
    fingerprint = hashlib.sha256(
        json.dumps(files, sort_keys=True).encode("utf8")
    ).hexdigest()
    return target, files, fingerprint


def run(workers=6):
    import kaggle_environments
    control_sha = _git_sha(BASELINE_SHA)
    p12_sha = _git_sha(P12_SHA)
    p13_head = _git_sha("HEAD")

    # Existing experimental JSON/Markdown must never be silently overwritten.
    for dest in (RESULT_JSON, RESULT_MD):
        if os.path.exists(dest):
            raise RuntimeError(f"Existing results must be preserved before rerun: {dest}")

    with tempfile.TemporaryDirectory(prefix="sw_p13_worktree_") as temporary:
        p13_agent, source_hashes, fingerprint = _snapshot_worktree_agent(temporary)
        dirs = {
            "Control": _extract_agent(control_sha, "control"),
            "P1.2": _extract_agent(p12_sha, "p12"),
            "P1.3-A": p13_agent,
        }
        tasks = []
        for scenario in SCENARIOS:
            for seat in (0, 1):
                case_id = f"{scenario['pair_id']:02d}-seat{seat}"
                for arm in ("Control", "P1.2", "P1.3-A"):
                    tasks.append({
                        **scenario, "case_id": case_id, "seat": seat,
                        "arm": arm, "agent_dir": dirs[arm],
                    })

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
            if all(
                arm in arms and arms[arm]["status"] == "SUCCESS"
                for arm in ("Control", "P1.2", "P1.3-A")
            ):
                complete.append({
                    "case_id": case_id, "pair_id": arms["Control"]["pair_id"],
                    "seed": arms["Control"]["seed"],
                    "opponent": arms["Control"]["opponent"],
                    "seat": arms["Control"]["seat"],
                    **{arm: arms[arm] for arm in ("Control", "P1.2", "P1.3-A")},
                    "delta_p13_p12": arms["P1.3-A"]["score"] - arms["P1.2"]["score"],
                    "delta_p13_control": arms["P1.3-A"]["score"] - arms["Control"]["score"],
                    "delta_p12_control": arms["P1.2"]["score"] - arms["Control"]["score"],
                })
            else:
                errors.append({"case_id": case_id, "arms": arms})

        per_opponent = {}
        for opponent in OPPONENTS:
            subgroup = [c for c in complete if c["opponent"] == opponent]
            per_opponent[opponent] = {
                "cases": len(subgroup),
                **{
                    arm + "_mean": statistics.mean(c[arm]["score"] for c in subgroup)
                    if subgroup else None
                    for arm in ("Control", "P1.2", "P1.3-A")
                },
                "p13_vs_p12_mean": statistics.mean(c["delta_p13_p12"] for c in subgroup)
                if subgroup else None,
            }
        per_seat = {
            seat: {
                "cases": sum(c["seat"] == seat for c in complete),
                "p13_vs_p12_mean": statistics.mean(
                    c["delta_p13_p12"] for c in complete if c["seat"] == seat
                ) if any(c["seat"] == seat for c in complete) else None,
            }
            for seat in (0, 1)
        }
        summary = {
            "complete_matched_cases": len(complete), "errors": len(errors),
            "arms": {arm: _aggregate_arm(results, arm)
                     for arm in ("Control", "P1.2", "P1.3-A")},
            "deltas": {
                "p13_vs_p12": _delta_stats([c["delta_p13_p12"] for c in complete]),
                "p13_vs_control": _delta_stats([c["delta_p13_control"] for c in complete]),
                "p12_vs_control": _delta_stats([c["delta_p12_control"] for c in complete]),
            },
            "per_opponent": per_opponent, "per_seat": per_seat,
        }
        report = {
            "metadata": {
                "control_sha": control_sha,
                "p12_sha": p12_sha,
                "p13_source_head": p13_head,
                "p13_snapshot_fingerprint": fingerprint,
                "p13_snapshot_file_hashes": source_hashes,
                "p13_runtime_mode": "isolated agent/ working-tree snapshot",
                "engine_version": getattr(kaggle_environments, "__version__", "unknown"),
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "matched_cases": 40, "balanced_seats": True,
                "treatment_flags": {
                    "Control": [False, False, False, False],
                    "P1.2": [True, True, True, False],
                    "P1.3-A": [True, True, True, True],
                },
            },
            "summary": summary, "cases": complete, "errors": errors,
        }
        os.makedirs(os.path.dirname(RESULT_JSON), exist_ok=True)
        with open(RESULT_JSON, "x", encoding="utf8") as fh:
            json.dump(report, fh, indent=2)
        with open(RESULT_MD, "x", encoding="utf8") as fh:
            fh.write(_markdown(report))
        print(json.dumps(summary, indent=2), flush=True)
        if errors:
            raise RuntimeError(f"{len(errors)} matched cases incomplete")
        return report


if __name__ == "__main__":
    run(min(6, os.cpu_count() or 6))
