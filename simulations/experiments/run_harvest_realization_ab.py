"""Paired A/B: harvest -> worker -> shed -> sale realization repair.

Baseline: production commit before harvest-realization repair.
Candidate: exact HEAD commit running this script.

Both agent trees are extracted from exact SHAs with git archive. The experiment
uses matched seeds/opponents and records score, safety, storage pressure, emitted
harvest/deposit/sell behavior, and end-of-season stranded value.
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
from typing import Any, Dict, List

BASELINE_SHA = "0b5cbcee8473ba74a80e298e7b0745ba639e1db4"
REALIZATION_PRODUCTS = ("CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL")
ALL_SELLABLE = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")

PAIRS = [
    *[{"pair_id": i + 1, "seed": 6101 + i, "opponent": "pass"} for i in range(4)],
    *[{"pair_id": i + 5, "seed": 6201 + i, "opponent": "pure_wheat_rush"} for i in range(4)],
    *[{"pair_id": i + 9, "seed": 6301 + i, "opponent": "cow_milk_engine"} for i in range(4)],
    *[{"pair_id": i + 13, "seed": 6401 + i, "opponent": "melon_sniper"} for i in range(4)],
    *[{"pair_id": i + 17, "seed": 6501 + i, "opponent": "full_production_agent"} for i in range(4)],
]


def resolve_repo_root() -> str:
    cur = os.path.abspath(os.path.dirname(__file__))
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        cur = parent


REPO_ROOT = resolve_repo_root()


def git_sha(ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def extract_agent(sha: str, label: str) -> str:
    exact = git_sha(sha)
    root = os.path.join(REPO_ROOT, "simulations", "baselines", f"{label}_{exact[:12]}")
    agent_dir = os.path.join(root, "agent")
    marker = os.path.join(root, ".extracted_sha")
    if os.path.isfile(marker) and os.path.isfile(os.path.join(agent_dir, "main.py")):
        with open(marker, "r", encoding="utf-8") as fh:
            if fh.read().strip() == exact:
                return agent_dir
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root, exist_ok=True)
    proc = subprocess.Popen(
        ["git", "archive", "--format=tar", exact, "agent"],
        cwd=REPO_ROOT, stdout=subprocess.PIPE,
    )
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(root, filter="data")
        else:
            tar.extractall(root)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"git archive failed for {label} {exact}")
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(exact)
    return agent_dir


def _sum_inv(inv: Dict[str, Any], products=ALL_SELLABLE) -> int:
    return sum(max(0, int(inv.get(p, 0) or 0)) for p in products)


def _farm_tile_yield(farm: Dict[str, Any], products=REALIZATION_PRODUCTS) -> int:
    total = 0
    for row in farm.get("tiles", []) or []:
        for tile in row or []:
            if not isinstance(tile, dict):
                continue
            item = tile.get("crop")
            if item is None and tile.get("animal"):
                # animal product is resolved from engine config in-match only when needed;
                # yield_units still represents stranded saleable output.
                item = "__ANIMAL__"
            if item in products or item == "__ANIMAL__":
                total += max(0, int(tile.get("yield_units", 0) or 0))
    return total


def _run_match(task: Dict[str, Any]) -> Dict[str, Any]:
    arm = task["arm"]
    pair_id = task["pair_id"]
    seed = task["seed"]
    opponent = task["opponent"]
    agent_dir = task["agent_dir"]

    clean = [p for p in sys.path if "agent" not in p.lower() and ".worktrees" not in p.lower()]
    sys.path = [agent_dir] + [
        os.path.join(agent_dir, sub) for sub in ("state", "strategy", "execution", "market")
    ] + [REPO_ROOT] + clean

    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in (
            "main", "config", "strategy", "state", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder",
        )):
            del sys.modules[name]

    try:
        import kaggle_environments
        import main as agent_module
        import config as cfg
        from simulations.experiments.agent_zoo import get_agent

        cfg.POINT2_FEED_MODE = "shadow"
        cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
        cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
        cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"
        agent_module.reset_agent_state()

        metrics = {
            "harvest_actions": 0,
            "scheduled_deposit_units": 0,
            "deposit_execution_actions": 0,
            "sell_order_units": 0,
            "confirmed_sellable_units_est": 0,
            "worker_sellable_eod_pre_action": 0,
            "worker_sellable_day29_h23": 0,
            "tile_yield_day29_h23": 0,
            "negative_cash_steps": 0,
            "starvation_observations": 0,
            "unwatered_eod_observations": 0,
            "ne_purchase_day": None,
            "sw_purchase_day": None,
        }

        def tracking_agent(obs, config=None):
            day = int(obs.get("day", 0))
            hour = int(obs.get("hour", 0))
            player = int(obs.get("player", 0))
            farms = obs.get("farms", []) or []
            farm = farms[player] if player < len(farms) else {}
            private = obs.get("private", {}) or {}
            inventories = private.get("inventories", []) or []
            shed = private.get("shed", {}) or {}

            money = float(farm.get("money", 0.0) or 0.0)
            if money < 0:
                metrics["negative_cash_steps"] += 1

            unlocked = set(farm.get("unlocked_quadrants", farm.get("unlocked", [])) or [])
            if "NE" in unlocked and metrics["ne_purchase_day"] is None:
                metrics["ne_purchase_day"] = day
            if "SW" in unlocked and metrics["sw_purchase_day"] is None:
                metrics["sw_purchase_day"] = day

            if hour == 0 and day > 0:
                for row in farm.get("tiles", []) or []:
                    for tile in row or []:
                        if isinstance(tile, dict) and tile.get("animal") and int(tile.get("consecutive_unfed", 0) or 0) > 0:
                            metrics["starvation_observations"] += 1

            worker_sellable = sum(_sum_inv(inv or {}, REALIZATION_PRODUCTS) for inv in inventories)
            if hour == 23:
                metrics["worker_sellable_eod_pre_action"] += worker_sellable
                for row in farm.get("tiles", []) or []:
                    for tile in row or []:
                        if isinstance(tile, dict) and tile.get("kind") == "PLANT" and not tile.get("watered_today", False):
                            metrics["unwatered_eod_observations"] += 1
            if day == 29 and hour == 23:
                metrics["worker_sellable_day29_h23"] = worker_sellable
                metrics["tile_yield_day29_h23"] = _farm_tile_yield(farm)

            action = agent_module.agent(obs, config) or {}
            telemetry = None
            try:
                telemetry = agent_module.get_last_turn_telemetry()
            except Exception:
                telemetry = None
            scheduled = dict((telemetry or {}).get("scheduled_product_deposits", {}) or {})
            metrics["scheduled_deposit_units"] += sum(max(0, int(v or 0)) for v in scheduled.values())

            unit_actions = [action.get("farmer", ["PASS"])] + list(action.get("hands", []) or [])
            for act in unit_actions:
                if not isinstance(act, (list, tuple)) or not act:
                    continue
                if act[0] == "HARVEST":
                    metrics["harvest_actions"] += 1
                if act[0] in ("PLACE", "DROP") and scheduled:
                    metrics["deposit_execution_actions"] += 1

            # Engine processes unit actions before market orders. For products that
            # cannot be bought from market, current shed + scheduler-confirmed
            # same-turn deposits gives an exact upper bound and normally exact
            # confirmed sell quantity.
            available = {p: int(shed.get(p, 0) or 0) + int(scheduled.get(p, 0) or 0)
                         for p in REALIZATION_PRODUCTS}
            for order in action.get("market", []) or []:
                if not isinstance(order, (list, tuple)) or len(order) < 3:
                    continue
                if order[0] == "SELL" and order[1] in REALIZATION_PRODUCTS:
                    qty = max(0, int(order[2] or 0))
                    metrics["sell_order_units"] += qty
                    confirmed = min(qty, max(0, available.get(order[1], 0)))
                    metrics["confirmed_sellable_units_est"] += confirmed
                    available[order[1]] = max(0, available.get(order[1], 0) - confirmed)
            return action

        env = kaggle_environments.make(
            "kaggriculture", configuration={"seed": seed, "episodeSteps": 720}, debug=False
        )
        opp = get_agent(opponent)
        started = time.time()
        steps = env.run([tracking_agent, opp])
        final = steps[-1]
        p0 = final[0]
        p1 = final[1]
        score = float(p0.get("reward", 0.0) or 0.0)
        opp_score = float(p1.get("reward", 0.0) or 0.0)

        final_obs = p0.get("observation", {}) or {}
        final_private = final_obs.get("private", {}) if isinstance(final_obs, dict) else {}
        final_farms = final_obs.get("farms", []) if isinstance(final_obs, dict) else []
        final_farm = final_farms[0] if final_farms else {}
        final_worker = sum(
            _sum_inv(inv or {}, REALIZATION_PRODUCTS)
            for inv in (final_private.get("inventories", []) or [])
        ) if isinstance(final_private, dict) else 0
        final_shed = sum(
            max(0, int((final_private.get("shed", {}) or {}).get(p, 0) or 0))
            for p in REALIZATION_PRODUCTS
        ) if isinstance(final_private, dict) else 0
        final_tile = _farm_tile_yield(final_farm) if isinstance(final_farm, dict) else 0

        return {
            "status": "SUCCESS",
            "pair_id": pair_id,
            "arm": arm,
            "seed": seed,
            "opponent": opponent,
            "final_score": score,
            "opp_score": opp_score,
            "elapsed_sec": round(time.time() - started, 2),
            "metrics": metrics,
            "final_stranded": {
                "worker_sellable_units": final_worker,
                "shed_sellable_units": final_shed,
                "tile_yield_units": final_tile,
                "total_units": final_worker + final_shed + final_tile,
            },
        }
    except Exception as exc:
        traceback.print_exc()
        return {
            "status": "ERROR", "pair_id": pair_id, "arm": arm,
            "seed": seed, "opponent": opponent, "final_score": 0.0,
            "opp_score": 0.0, "error": repr(exc),
        }


def _sum_metric(rows, arm, key):
    return sum(int(r[arm].get("metrics", {}).get(key, 0) or 0) for r in rows)


def _sum_stranded(rows, arm, key):
    return sum(int(r[arm].get("final_stranded", {}).get(key, 0) or 0) for r in rows)


def run(max_workers: int = 4) -> Dict[str, Any]:
    baseline_exact = git_sha(BASELINE_SHA)
    candidate_exact = git_sha("HEAD")
    baseline_dir = extract_agent(baseline_exact, "harvest_base")
    candidate_dir = extract_agent(candidate_exact, "harvest_candidate")

    import kaggle_environments
    engine_version = getattr(kaggle_environments, "__version__", "unknown")

    tasks = []
    for pair in PAIRS:
        for arm, agent_dir in (("Baseline", baseline_dir), ("Candidate", candidate_dir)):
            tasks.append({**pair, "arm": arm, "agent_dir": agent_dir})

    raw: List[Dict[str, Any]] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_match, t): t for t in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            raw.append(res)
            print(
                f"[{i:02d}/{len(tasks):02d}] {res['arm']:9s} pair={res['pair_id']:02d} "
                f"seed={res['seed']} opp={res['opponent']:<22s} score={res.get('final_score', 0):.0f}"
            )

    by_pair: Dict[int, Dict[str, Any]] = {}
    for result in raw:
        by_pair.setdefault(int(result["pair_id"]), {})[result["arm"]] = result

    paired = []
    for pair in PAIRS:
        arms = by_pair.get(pair["pair_id"], {})
        base = arms.get("Baseline", {})
        cand = arms.get("Candidate", {})
        paired.append({
            "pair_id": pair["pair_id"], "seed": pair["seed"], "opponent": pair["opponent"],
            "Baseline": base, "Candidate": cand,
            "score_delta": float(cand.get("final_score", 0)) - float(base.get("final_score", 0)),
        })

    deltas = [p["score_delta"] for p in paired]
    base_scores = [float(p["Baseline"].get("final_score", 0)) for p in paired]
    cand_scores = [float(p["Candidate"].get("final_score", 0)) for p in paired]
    mean_delta = statistics.mean(deltas)
    median_delta = statistics.median(deltas)
    sd_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
    se = sd_delta / math.sqrt(len(deltas)) if deltas else 0.0
    try:
        from scipy.stats import t as student_t
        crit = float(student_t.ppf(0.975, len(deltas) - 1)) if len(deltas) > 1 else 0.0
    except Exception:
        crit = 2.093 if len(deltas) == 20 else 1.96
    ci = [mean_delta - crit * se, mean_delta + crit * se]

    by_opponent = {}
    for opponent in sorted({p["opponent"] for p in paired}):
        group = [p for p in paired if p["opponent"] == opponent]
        gd = [p["score_delta"] for p in group]
        by_opponent[opponent] = {
            "pairs": len(group),
            "mean_base_score": round(statistics.mean(float(p["Baseline"].get("final_score", 0)) for p in group), 2),
            "mean_candidate_score": round(statistics.mean(float(p["Candidate"].get("final_score", 0)) for p in group), 2),
            "mean_delta": round(statistics.mean(gd), 2),
            "wins": sum(d > 0 for d in gd),
            "ties": sum(d == 0 for d in gd),
            "losses": sum(d < 0 for d in gd),
        }

    aggregate = {
        "pairs": len(paired),
        "mean_base_score": round(statistics.mean(base_scores), 2),
        "mean_candidate_score": round(statistics.mean(cand_scores), 2),
        "mean_paired_delta": round(mean_delta, 2),
        "median_paired_delta": round(median_delta, 2),
        "sample_sd_paired_delta": round(sd_delta, 2),
        "approx_95_ci": [round(ci[0], 2), round(ci[1], 2)],
        "wins": sum(d > 0 for d in deltas),
        "ties": sum(d == 0 for d in deltas),
        "losses": sum(d < 0 for d in deltas),
        "funnel": {
            "baseline_harvest_actions": _sum_metric(paired, "Baseline", "harvest_actions"),
            "candidate_harvest_actions": _sum_metric(paired, "Candidate", "harvest_actions"),
            "baseline_scheduled_deposit_units": _sum_metric(paired, "Baseline", "scheduled_deposit_units"),
            "candidate_scheduled_deposit_units": _sum_metric(paired, "Candidate", "scheduled_deposit_units"),
            "baseline_sell_order_units": _sum_metric(paired, "Baseline", "sell_order_units"),
            "candidate_sell_order_units": _sum_metric(paired, "Candidate", "sell_order_units"),
            "baseline_confirmed_sellable_units_est": _sum_metric(paired, "Baseline", "confirmed_sellable_units_est"),
            "candidate_confirmed_sellable_units_est": _sum_metric(paired, "Candidate", "confirmed_sellable_units_est"),
            "baseline_final_stranded_units": _sum_stranded(paired, "Baseline", "total_units"),
            "candidate_final_stranded_units": _sum_stranded(paired, "Candidate", "total_units"),
            "baseline_worker_eod_pre_action": _sum_metric(paired, "Baseline", "worker_sellable_eod_pre_action"),
            "candidate_worker_eod_pre_action": _sum_metric(paired, "Candidate", "worker_sellable_eod_pre_action"),
        },
        "safety": {
            "baseline_starvation_observations": _sum_metric(paired, "Baseline", "starvation_observations"),
            "candidate_starvation_observations": _sum_metric(paired, "Candidate", "starvation_observations"),
            "baseline_negative_cash_steps": _sum_metric(paired, "Baseline", "negative_cash_steps"),
            "candidate_negative_cash_steps": _sum_metric(paired, "Candidate", "negative_cash_steps"),
            "baseline_unwatered_eod_observations": _sum_metric(paired, "Baseline", "unwatered_eod_observations"),
            "candidate_unwatered_eod_observations": _sum_metric(paired, "Candidate", "unwatered_eod_observations"),
        },
        "elapsed_sec": round(time.time() - started, 2),
    }

    result = {
        "metadata": {
            "experiment": "harvest_realization_20pair_ab",
            "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "baseline_sha": baseline_exact,
            "candidate_sha": candidate_exact,
            "engine_version": engine_version,
            "python_version": sys.version,
            "production_config": {
                "POINT2_FEED_MODE": "shadow",
                "BOOTSTRAP_LIVESTOCK_ARM": "none",
                "ONE_AT_A_TIME_LATE_HOUSING_ENABLED": False,
                "POINT2_PRE_NE_CAPITAL_MODE": "off",
            },
        },
        "aggregate": aggregate,
        "by_opponent": by_opponent,
        "pairs_summary": [
            {
                "pair_id": p["pair_id"], "seed": p["seed"], "opponent": p["opponent"],
                "base_score": p["Baseline"].get("final_score", 0),
                "candidate_score": p["Candidate"].get("final_score", 0),
                "score_delta": p["score_delta"],
                "base_metrics": p["Baseline"].get("metrics", {}),
                "candidate_metrics": p["Candidate"].get("metrics", {}),
                "base_final_stranded": p["Baseline"].get("final_stranded", {}),
                "candidate_final_stranded": p["Candidate"].get("final_stranded", {}),
            }
            for p in paired
        ],
        "raw_results": raw,
    }

    out = os.path.join(
        REPO_ROOT, "simulations", "experiments", "results",
        "harvest_realization_ab_20pair_results.json",
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    print("\nHARVEST REALIZATION A/B AGGREGATE")
    print(json.dumps({"aggregate": aggregate, "by_opponent": by_opponent}, indent=2))
    print(f"Results: {out}")
    return result


if __name__ == "__main__":
    workers = min(4, os.cpu_count() or 4)
    run(max_workers=workers)
