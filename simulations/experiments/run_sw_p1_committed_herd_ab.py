"""Deterministic 20-pair SW P1 purchase-workload experiment.

The baseline and treatment are independently imported from exact git-archived
agent trees, on matching seeds/opponents. The sole treatment switch is P1.
Economic results are per-farm final scores; fungible market goods cannot
be attributed to SW by shed sale alone.
"""
from __future__ import annotations
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
OPPONENTS = ("pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent")
PAIRS = [
    {"pair_id": i + 1, "seed": 7101 + i + 100 * (i // 4), "opponent": OPPONENTS[i // 4]}
    for i in range(20)
]
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _git_sha(ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=ROOT,
                          check=True, text=True, capture_output=True).stdout.strip()


def _extract_agent(sha, label):
    sha = _git_sha(sha)
    directory = os.path.join(ROOT, "simulations", "baselines", f"sw_p1_{label}_{sha[:12]}")
    target = os.path.join(directory, "agent")
    marker = os.path.join(directory, ".extracted_sha")
    if os.path.isfile(marker) and os.path.isfile(os.path.join(target, "main.py")):
        if open(marker, encoding="utf8").read().strip() == sha:
            return target
    if os.path.isdir(directory):
        shutil.rmtree(directory)
    os.makedirs(directory, exist_ok=True)
    p = subprocess.Popen(["git", "archive", "--format=tar", sha, "agent"],
                         cwd=ROOT, stdout=subprocess.PIPE)
    with tarfile.open(fileobj=p.stdout, mode="r|") as archive:
        if hasattr(tarfile, "data_filter"):
            archive.extractall(directory, filter="data")
        else:
            archive.extractall(directory)
    if p.wait() != 0:
        raise RuntimeError(f"failed git archive for {sha}")
    with open(marker, "w", encoding="utf8") as f:
        f.write(sha)
    return target


def _tile_counts(farm, *, quadrant="SW"):
    metrics = {"owned_tile_turns": 0, "planted_tile_turns": 0,
               "watered_plant_turns": 0, "empty_tile_turns": 0,
               "harvestable_units": 0}
    unlocked = set(farm.get("unlocked_quadrants", []) or [])
    if quadrant not in unlocked:
        return metrics
    metrics["owned_tile_turns"] = 25
    rows = farm.get("tiles", []) or []
    for y in range(10):
        for x in range(10):
            if ("N" if y < 5 else "S") + ("W" if x < 5 else "E") != quadrant:
                continue
            t = rows[y][x] if y < len(rows) and x < len(rows[y]) else None
            if t is None:
                metrics["empty_tile_turns"] += 1
            elif isinstance(t, dict) and t.get("kind") == "PLANT":
                metrics["planted_tile_turns"] += 1
                if t.get("watered_today"):
                    metrics["watered_plant_turns"] += 1
                metrics["harvestable_units"] += max(0, int(t.get("yield_units", 0) or 0))
    return metrics


def _one(task):
    # Worker runs a single arm in a fresh process to avoid persistent-state leakage.
    agent_dir = task["agent_dir"]
    clean_sys_path = [p for p in sys.path if "agent" not in p.lower() and ".worktrees" not in p.lower()]
    sys.path = ([agent_dir]
                + [os.path.join(agent_dir, sub) for sub in ("state", "strategy", "execution", "market")]
                + [ROOT] + clean_sys_path)
    for k in list(sys.modules):
        if any(k == m or k.startswith(m + ".") for m in
               ("main", "config", "state", "strategy", "execution", "market",
                "task_scheduler", "macro_planner", "order_builder")):
            del sys.modules[k]

    try:
        import kaggle_environments
        import main as module
        import config as cfg
        from simulations.experiments.agent_zoo import get_agent

        cfg.POINT2_FEED_MODE = "shadow"
        cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
        cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
        cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"
        cfg.SW_P1_PURCHASE_COMMITTED_HERD_ONLY = task["arm"] == "P1"
        module.reset_agent_state()

        m = {
            "sw_purchase_day": None, "sw_purchase_hour": None,
            "sw_proposed_turns": 0, "sw_selected_turns": 0,
            "sw_buy_orders_emitted": 0, "sw_confirmed": False,
            "sw_gate_reasons": {}, "sw_gate_samples": [],
            "sw_tile_turns": {"owned_tile_turns": 0, "planted_tile_turns": 0,
                              "watered_plant_turns": 0, "empty_tile_turns": 0},
            "nw_tile_turns": {"planted_tile_turns": 0, "watered_plant_turns": 0},
            "ne_tile_turns": {"planted_tile_turns": 0, "watered_plant_turns": 0},
            "starvation_observations": 0, "unwatered_eod_observations": 0,
            "negative_cash_steps": 0, "harvest_attempts_sw": 0,
            "cash_min": float("inf"), "last_cash": None, "fallback_turns": 0,
        }

        def tracking(obs, configuration=None):
            day = int(obs.get("day", 0))
            hour = int(obs.get("hour", 0))
            player = int(obs.get("player", 0))
            farm = obs.get("farms", [])[player]
            owned = set(farm.get("unlocked_quadrants", []) or [])
            cash = float(farm.get("money", 0) or 0)
            m["cash_min"] = min(m["cash_min"], cash)
            m["last_cash"] = cash
            if cash < 0:
                m["negative_cash_steps"] += 1
            if "SW" in owned and m["sw_purchase_day"] is None:
                m["sw_purchase_day"] = day
                m["sw_purchase_hour"] = hour
                m["sw_confirmed"] = True
            if hour == 0 and day > 0:
                for row in farm.get("tiles", []) or []:
                    for t in row or []:
                        if isinstance(t, dict) and t.get("animal") and int(t.get("consecutive_unfed", 0) or 0) > 0:
                            m["starvation_observations"] += 1

            if hour == 23:
                for quad, k in (("SW", "sw_tile_turns"), ("NW", "nw_tile_turns"), ("NE", "ne_tile_turns")):
                    val = _tile_counts(farm, quadrant=quad)
                    for metric in m[k]:
                        m[k][metric] += val[metric]
                for row in farm.get("tiles", []) or []:
                    for t in row or []:
                        if isinstance(t, dict) and t.get("kind") == "PLANT" and not t.get("watered_today"):
                            m["unwatered_eod_observations"] += 1

            # Engine unit actions use pre-movement positions; track attempted SW
            # harvest, not confirmed SW sales (market inventory is fungible).
            positions = [farm.get("farmer", [4, 4])] + list(farm.get("hands", []) or [])
            action = module.agent(obs, configuration) or {}
            if action.get("_emergency_fallback"):
                m["fallback_turns"] += 1
            actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []) or [])
            for pos, act in zip(positions, actions):
                if isinstance(act, (list, tuple)) and act and act[0] == "HARVEST" and pos[0] < 5 and pos[1] >= 5:
                    m["harvest_attempts_sw"] += 1

            telemetry = module.get_last_turn_telemetry() or {}
            if "SW" not in owned and "NE" in owned and day >= 9 and day <= 27:
                if telemetry.get("land_proposed"):
                    m["sw_proposed_turns"] += 1
                if telemetry.get("land_selected"):
                    m["sw_selected_turns"] += 1
                m["sw_buy_orders_emitted"] += sum(
                    1 for o in action.get("market", []) or []
                    if isinstance(o, (tuple, list)) and o and o[0] == "BUY_LAND"
                )
                d = (telemetry.get("macro_plan_diagnostic") or {}).get("land_decision") or {}
                reason = d.get("final_rejection_or_acceptance_reason", "no_gate_diagnostic")
                m["sw_gate_reasons"][reason] = m["sw_gate_reasons"].get(reason, 0) + 1
                if hour in (0, 1) and len(m["sw_gate_samples"]) < 48:
                    keys = (
                        "day", "next_quadrant", "money", "roi", "adjusted_roi",
                        "payback_surplus", "total_required_cash", "labor_serviceability_result",
                        "ne_observed_animals_and_housing", "ne_desired_sheep_target",
                        "ne_reserved_sheep_workload_count", "sw_labor_ne_deficit",
                        "best_k_tiles", "best_k_serviceable", "final_rejection_or_acceptance_reason",
                    )
                    m["sw_gate_samples"].append({"day": day, "hour": hour, **{k: d.get(k) for k in keys}})
            return action

        started = time.time()
        env = kaggle_environments.make("kaggriculture",
                                       configuration={"seed": task["seed"], "episodeSteps": 720}, debug=False)
        steps = env.run([tracking, get_agent(task["opponent"])])
        final = steps[-1]
        score = float(final[0].get("reward", 0) or 0)
        return {
            **{k: task[k] for k in ("arm", "pair_id", "seed", "opponent")},
            "status": "SUCCESS", "score": score,
            "opponent_score": float(final[1].get("reward", 0) or 0),
            "metrics": m, "elapsed_seconds": round(time.time() - started, 2),
            "episode_steps": len(steps),
        }
    except Exception as e:
        traceback.print_exc()
        return {**{k: task[k] for k in ("arm", "pair_id", "seed", "opponent")},
                "status": "ERROR", "error": repr(e)}


def run(workers=4):
    import kaggle_environments
    baseline_sha = _git_sha(BASELINE_SHA)
    candidate_sha = _git_sha("HEAD")
    base_dir = _extract_agent(baseline_sha, "control")
    p1_dir = _extract_agent(candidate_sha, "treatment")
    tasks = [
        {**p, "arm": arm, "agent_dir": base_dir if arm == "Control" else p1_dir}
        for p in PAIRS for arm in ("Control", "P1")
    ]
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, t): t for t in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            res = future.result()
            results.append(res)
            print(f"[{i:02d}/{len(tasks)}] {res['arm']} pair={res['pair_id']} "
                  f"score={res.get('score', 'ERROR')} opponent={res['opponent']}", flush=True)

    pairs = []
    for pair in PAIRS:
        both = {x["arm"]: x for x in results if x["pair_id"] == pair["pair_id"]}
        control, p1 = both["Control"], both["P1"]
        pairs.append({
            "pair_id": pair["pair_id"], "seed": pair["seed"], "opponent": pair["opponent"],
            "Control": control, "P1": p1,
            "score_delta": p1["score"] - control["score"]
            if control["status"] == p1["status"] == "SUCCESS" else None,
        })
    valid = [p for p in pairs if p["score_delta"] is not None]
    ds = [p["score_delta"] for p in valid]
    mean = statistics.mean(ds) if ds else None
    se = statistics.stdev(ds) / math.sqrt(len(ds)) if len(ds) > 1 else None
    try:
        from scipy.stats import t
        tcrit = float(t.ppf(0.975, len(ds) - 1)) if len(ds) > 1 else None
    except Exception:
        tcrit = 2.093 if len(ds) == 20 else 1.96
    ci = [mean - tcrit * se, mean + tcrit * se] if se is not None else None

    def total(arm, key):
        return sum(int(p[arm]["metrics"].get(key, 0)) for p in valid)

    summary = {
        "requested_pairs": len(pairs), "valid_pairs": len(valid),
        "errors": len(pairs) - len(valid),
        "mean_control": statistics.mean(p["Control"]["score"] for p in valid) if valid else None,
        "mean_p1": statistics.mean(p["P1"]["score"] for p in valid) if valid else None,
        "mean_delta": mean, "median_delta": statistics.median(ds) if ds else None,
        "delta_95_ci": ci,
        "wins": sum(d > 0 for d in ds),
        "ties": sum(d == 0 for d in ds),
        "losses": sum(d < 0 for d in ds),
        "control_confirmed_sw": sum(p["Control"]["metrics"]["sw_confirmed"] for p in valid),
        "p1_confirmed_sw": sum(p["P1"]["metrics"]["sw_confirmed"] for p in valid),
        "control_starvation": total("Control", "starvation_observations"),
        "p1_starvation": total("P1", "starvation_observations"),
        "control_unwatered": total("Control", "unwatered_eod_observations"),
        "p1_unwatered": total("P1", "unwatered_eod_observations"),
        "control_negative_cash": total("Control", "negative_cash_steps"),
        "p1_negative_cash": total("P1", "negative_cash_steps"),
    }
    for key in ("sw_proposed_turns", "sw_selected_turns", "sw_buy_orders_emitted", "harvest_attempts_sw"):
        summary[f"control_{key}"] = total("Control", key)
        summary[f"p1_{key}"] = total("P1", key)
    for key in ("owned_tile_turns", "planted_tile_turns", "watered_plant_turns"):
        for arm in ("Control", "P1"):
            summary[f"{arm.lower()}_sw_{key}"] = sum(
                p[arm]["metrics"]["sw_tile_turns"][key] for p in valid
            )

    report = {
        "metadata": {
            "baseline_sha": baseline_sha, "candidate_sha": candidate_sha,
            "engine_version": getattr(kaggle_environments, "__version__", "unknown"),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "treatment_only": "SW_P1_PURCHASE_COMMITTED_HERD_ONLY=True",
            "seeds_and_opponents": PAIRS,
        },
        "summary": summary, "pairs": pairs,
    }
    path = os.path.join(ROOT, "simulations", "experiments", "results", "sw_p1_committed_herd_20pair.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(summary, indent=2), flush=True)
    if summary["errors"]:
        raise RuntimeError(f"{summary['errors']} matched pairs had an error; see {path}")
    return report


if __name__ == "__main__":
    run(min(4, os.cpu_count() or 4))
