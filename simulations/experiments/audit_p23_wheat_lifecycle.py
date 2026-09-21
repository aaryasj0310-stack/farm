#!/usr/bin/env python3
"""P2.3 Wheat Lifecycle Comprehensive Telemetry Audit.

Runs True Production Control (237cf5e..., QUADRANT_HARD_BLOCK={4})
across 20 games (seeds 88001-88020, 5 opponent archetypes, balanced seats)
to measure the exact physical, timing, and economic lifecycle of every wheat unit.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

BASELINE_SHA = "237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e"
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

SCENARIOS = [
    {
        "game_id": i + 1,
        "seed": 88001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
        "seat": i % 2,
    }
    for i in range(20)
]


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


def _configure_control(cfg):
    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    elif hasattr(cfg, "QUADRANT_HARD_BLOCK"):
        cfg.QUADRANT_HARD_BLOCK = {4}

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


def _audit_one(task):
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

        _configure_control(cfg)
        module.reset_agent_state()
        ts.reset_daily_log()

        # Detailed wheat telemetry
        daily_records = [
            {
                "day": d,
                "wheat_seeds_bought": 0,
                "wheat_tiles_planted": 0,
                "wheat_tiles_watered": 0,
                "wheat_tiles_harvested": 0,
                "wheat_units_harvested": 0,
                "wheat_fed_units": 0,
                "wheat_bought_market_units": 0,
                "wheat_bought_market_spend": 0.0,
                "wheat_sold_market_units": 0,
                "wheat_sold_market_revenue": 0.0,
                "animals_alive": 0,
                "animals_unfed_eod": 0,
                "shed_wheat_eod": 0,
                "worker_wheat_eod": 0,
            }
            for d in range(30)
        ]

        wheat_plantings = []
        feed_actions_by_day = defaultdict(int)
        harvest_events = []

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            player = int(obs.get("player", task["seat"]))
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}

            rec = daily_records[day]

            # Count live animals
            animals_count = 0
            unfed_count = 0
            for row in farm.get("tiles", []) or []:
                for t in row or []:
                    if isinstance(t, dict) and (t.get("animal") or t.get("is_animal")):
                        animals_count += 1
                        if not t.get("fed_today", False):
                            unfed_count += 1

            if hour == 23:
                rec["animals_alive"] = animals_count
                rec["animals_unfed_eod"] = unfed_count
                rec["shed_wheat_eod"] = int(farm.get("shed", {}).get("WHEAT", 0) or 0)
                rec["worker_wheat_eod"] = sum(
                    int((inv or {}).get("WHEAT", 0) or 0)
                    for inv in farm.get("inventories", [])
                )

            action = module.agent(obs, configuration) or {}

            # Parse worker actions
            if isinstance(action, dict):
                for u_act in action.get("hands", []) + [action.get("farmer")]:
                    if isinstance(u_act, (list, tuple)) and len(u_act) >= 1:
                        op = u_act[0]
                        if op == "PLANT":
                            # Action format: ["PLANT", crop, x, y] or ["PLANT", crop]
                            c = u_act[1] if len(u_act) >= 2 else ""
                            if c == "WHEAT":
                                rec["wheat_tiles_planted"] += 1
                                pos = (int(u_act[2]), int(u_act[3])) if len(u_act) >= 4 else None
                                wheat_plantings.append({"day": day, "hour": hour, "pos": pos})
                        elif op == "WATER":
                            # Action format: ["WATER", x, y]
                            if len(u_act) >= 3:
                                x, y = int(u_act[1]), int(u_act[2])
                                tiles = farm.get("tiles", [])
                                if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
                                    t = tiles[y][x]
                                    if isinstance(t, dict) and t.get("crop") == "WHEAT":
                                        rec["wheat_tiles_watered"] += 1
                        elif op == "HARVEST":
                            # Action format: ["HARVEST", x, y]
                            if len(u_act) >= 3:
                                x, y = int(u_act[1]), int(u_act[2])
                                tiles = farm.get("tiles", [])
                                if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
                                    t = tiles[y][x]
                                    if isinstance(t, dict) and t.get("crop") == "WHEAT":
                                        rec["wheat_tiles_harvested"] += 1
                                        y_units = int(t.get("yield_units", 6) or 6)
                                        rec["wheat_units_harvested"] += y_units
                                        harvest_events.append({"day": day, "hour": hour, "pos": (x, y), "yield": y_units})
                        elif op == "FEED":
                            rec["wheat_fed_units"] += 1
                            feed_actions_by_day[day] += 1

                # Market transactions
                for ord_item in action.get("market", []):
                    if isinstance(ord_item, (list, tuple)) and len(ord_item) >= 3:
                        op = ord_item[0]
                        prod = ord_item[1]
                        qty = int(ord_item[2])
                        if prod == "WHEAT":
                            if op == "BUY_SEED":
                                rec["wheat_seeds_bought"] += qty
                            elif op == "BUY_PRODUCT":
                                rec["wheat_bought_market_units"] += qty
                                rec["wheat_bought_market_spend"] += qty * 25.0
                            elif op == "SELL":
                                inv_val = float(obs.get("market", {}).get("inventory", {}).get("WHEAT", 10000.0))
                                px = cfg.market_price("WHEAT", inv_val) if hasattr(cfg, "market_price") else 25.0
                                rec["wheat_sold_market_units"] += qty
                                rec["wheat_sold_market_revenue"] += qty * px

            return action

        opp = get_agent(task["opponent"])
        agents = [tracking, opp] if task["seat"] == 0 else [opp, tracking]
        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": task["seed"]})
        env.run(agents)

        f_raw = env.state[task["seat"]]["observation"]["farms"][task["seat"]]["money"]
        score = float(f_raw)

        # Totals across season
        total_planted = sum(r["wheat_tiles_planted"] for r in daily_records)
        total_harvested_tiles = sum(r["wheat_tiles_harvested"] for r in daily_records)
        total_harvested_units = sum(r["wheat_units_harvested"] for r in daily_records)
        total_fed_units = sum(r["wheat_fed_units"] for r in daily_records)
        total_bought_units = sum(r["wheat_bought_market_units"] for r in daily_records)
        total_bought_spend = sum(r["wheat_bought_market_spend"] for r in daily_records)
        total_sold_units = sum(r["wheat_sold_market_units"] for r in daily_records)
        total_sold_revenue = sum(r["wheat_sold_market_revenue"] for r in daily_records)
        unsold_endgame_wheat = daily_records[29]["shed_wheat_eod"] + daily_records[29]["worker_wheat_eod"]

        return {
            "game_id": task["game_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "seat": task["seat"],
            "score": score,
            "total_planted": total_planted,
            "total_harvested_tiles": total_harvested_tiles,
            "total_harvested_units": total_harvested_units,
            "total_fed_units": total_fed_units,
            "total_bought_units": total_bought_units,
            "total_bought_spend": total_bought_spend,
            "total_sold_units": total_sold_units,
            "total_sold_revenue": total_sold_revenue,
            "unsold_endgame_wheat": unsold_endgame_wheat,
            "daily_records": daily_records,
            "wheat_plantings": wheat_plantings,
            "harvest_events": harvest_events,
            "error": None,
        }
    except Exception as e:
        import traceback
        return {
            "game_id": task["game_id"],
            "seed": task["seed"],
            "opponent": task["opponent"],
            "seat": task["seat"],
            "score": 0.0,
            "error": f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
        }


def run_audit(workers=8):
    print(f"Extracting Control baseline {BASELINE_SHA}...", flush=True)
    control_dir = _extract_control_agent(BASELINE_SHA)

    tasks = [
        {
            "game_id": sc["game_id"],
            "seed": sc["seed"],
            "opponent": sc["opponent"],
            "seat": sc["seat"],
            "agent_dir": control_dir,
        }
        for sc in SCENARIOS
    ]

    print(f"Running 20 baseline games with {workers} workers...", flush=True)
    results = []
    start_time = time.time()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_audit_one, t): t for t in tasks}
        completed = 0
        for f in as_completed(futures):
            completed += 1
            res = f.result()
            if res.get("error"):
                print(f"[{completed}/20] Game {res['game_id']} error: {res['error']}", flush=True)
            else:
                results.append(res)
                print(f"[{completed}/20] Game {res['game_id']} (seed {res['seed']}, vs {res['opponent']}): Score=${res['score']:,.2f}, Planted={res['total_planted']}, HarvUnits={res['total_harvested_units']}, FedUnits={res['total_fed_units']}, SoldUnits={res['total_sold_units']}, BoughtUnits={res['total_bought_units']}", flush=True)

    elapsed = time.time() - start_time
    print(f"All 20 audit games finished in {elapsed:.1f}s", flush=True)

    # Compile aggregate physical & economic audit
    scores = [r["score"] for r in results]
    planted = [r["total_planted"] for r in results]
    harv_units = [r["total_harvested_units"] for r in results]
    fed_units = [r["total_fed_units"] for r in results]
    bought_units = [r["total_bought_units"] for r in results]
    bought_spend = [r["total_bought_spend"] for r in results]
    sold_units = [r["total_sold_units"] for r in results]
    sold_rev = [r["total_sold_revenue"] for r in results]
    unsold_units = [r["unsold_endgame_wheat"] for r in results]

    # Reconcile day by day averages
    day_table = []
    for d in range(30):
        d_planted = statistics.mean([r["daily_records"][d]["wheat_tiles_planted"] for r in results])
        d_harv_units = statistics.mean([r["daily_records"][d]["wheat_units_harvested"] for r in results])
        d_fed = statistics.mean([r["daily_records"][d]["wheat_fed_units"] for r in results])
        d_bought = statistics.mean([r["daily_records"][d]["wheat_bought_market_units"] for r in results])
        d_bought_spend = statistics.mean([r["daily_records"][d]["wheat_bought_market_spend"] for r in results])
        d_sold = statistics.mean([r["daily_records"][d]["wheat_sold_market_units"] for r in results])
        d_sold_rev = statistics.mean([r["daily_records"][d]["wheat_sold_market_revenue"] for r in results])
        d_shed = statistics.mean([r["daily_records"][d]["shed_wheat_eod"] for r in results])
        d_worker = statistics.mean([r["daily_records"][d]["worker_wheat_eod"] for r in results])
        d_animals = statistics.mean([r["daily_records"][d]["animals_alive"] for r in results])
        day_table.append({
            "day": d,
            "planted_tiles": d_planted,
            "harvested_units": d_harv_units,
            "fed_units": d_fed,
            "bought_units": d_bought,
            "bought_spend": d_bought_spend,
            "sold_units": d_sold,
            "sold_revenue": d_sold_rev,
            "shed_wheat_eod": d_shed,
            "worker_wheat_eod": d_worker,
            "animals_alive": d_animals,
        })

    cohort_tranches = {
        "Days 0-4 (Phase 1 Cash/Survival)": sum(r["planted_tiles"] for r in day_table if 0 <= r["day"] <= 4),
        "Days 5-8 (Pre-NE/NE Scaling)": sum(r["planted_tiles"] for r in day_table if 5 <= r["day"] <= 8),
        "Days 9-13 (Strawberry Window Replacements)": sum(r["planted_tiles"] for r in day_table if 9 <= r["day"] <= 13),
        "Days 14-19 (Mid-Season Wheat Replants)": sum(r["planted_tiles"] for r in day_table if 14 <= r["day"] <= 19),
        "Days 20-24 (Late Replants, mature Days 25-29)": sum(r["planted_tiles"] for r in day_table if 20 <= r["day"] <= 24),
        "Days 25+ (Terminal Replants, mature too late or Day 30)": sum(r["planted_tiles"] for r in day_table if r["day"] >= 25),
    }

    audit_summary = {
        "sample_games": len(results),
        "mean_score": statistics.mean(scores),
        "mean_planted_tiles": statistics.mean(planted),
        "mean_harvested_units": statistics.mean(harv_units),
        "mean_fed_units": statistics.mean(fed_units),
        "mean_bought_units": statistics.mean(bought_units),
        "mean_bought_spend": statistics.mean(bought_spend),
        "mean_sold_units": statistics.mean(sold_units),
        "mean_sold_revenue": statistics.mean(sold_rev),
        "mean_unsold_endgame_units": statistics.mean(unsold_units),
        "physical_balance_delta": (
            statistics.mean(harv_units) + statistics.mean(bought_units)
            - statistics.mean(fed_units) - statistics.mean(sold_units)
            - statistics.mean(unsold_units)
        ),
        "cohort_tranches": cohort_tranches,
        "day_table": day_table,
    }

    out_json = os.path.join(ROOT, "simulations", "experiments", "results", "p23_wheat_lifecycle_audit.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(audit_summary, f, indent=2)
    print(f"Audit JSON saved to {out_json}", flush=True)

    try:
        shutil.rmtree(control_dir)
    except Exception:
        pass

    return audit_summary


if __name__ == "__main__":
    run_audit(workers=8)
