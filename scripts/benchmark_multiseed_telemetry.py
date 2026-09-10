"""Multi-seed Regression Benchmark with Comprehensive Operational Telemetry.

Runs multi-seed evaluation tracking:
- score, score variance, min, max
- strategy/emergency fallbacks
- invalid / no-op actions
- crop deaths
- missed feeds
- animal deaths
- urgent misses
- travel share
- completion rate
- SW utilization and quadrant completion rates
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
from collections import Counter
import kaggle_environments


def _load_agent(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def fmt_val(val, is_pct=False):
    """Format metric value, displaying None as N/A."""
    if val is None:
        return "N/A"
    if is_pct:
        return f"{val * 100:.1f}%"
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


def run_benchmark_match(candidate_path: str, opponent_path: str | None, seed: int, seat: int = 0):
    mod_cand = _load_agent(candidate_path, f"cand_{seed}_{seat}")
    mod_opp = _load_agent(opponent_path, f"opp_{seed}_{seat}") if opponent_path else None

    # Reset telemetry state before match
    reset_fn = getattr(mod_cand, "reset_daily_log", None) or getattr(mod_cand, "reset_daily_telemetry", None)
    if reset_fn:
        reset_fn()

    fallbacks = []
    crop_deaths = 0
    animal_deaths = 0
    missed_feeds = 0
    prev_animal_count = 0

    def player_act(obs, config, mod, player_idx):
        nonlocal prev_animal_count, animal_deaths, missed_feeds
        if mod is None:
            return {"farmer": ["PASS"], "hands": [], "market": []}
        try:
            act = mod.agent(obs, config)
            diag = getattr(mod, "get_last_fallback_diagnostic", lambda: None)()
            if diag:
                fallbacks.append(diag)
            # Track animal deaths and missed feeds on day end
            if player_idx == seat and obs.get("hour") == 23:
                farm = obs["farms"][player_idx]
                curr_animals = sum(
                    1 for row in farm["tiles"] for t in row
                    if isinstance(t, dict) and t.get("kind") == "ANIMAL"
                )
                if curr_animals < prev_animal_count:
                    animal_deaths += (prev_animal_count - curr_animals)
                prev_animal_count = curr_animals
                for row in farm["tiles"]:
                    for t in row:
                        if isinstance(t, dict) and t.get("kind") == "ANIMAL":
                            if not t.get("fed_today", False):
                                missed_feeds += 1
            return act
        except Exception as exc:
            fallbacks.append({"step": obs.get("step", 0), "exc": str(exc)})
            return {"farmer": ["PASS"], "hands": [], "market": []}

    env = kaggle_environments.make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720})
    env.reset(2)

    step = 0
    while not env.done and step < 720:
        obs0 = copy.deepcopy(env.state[0].observation)
        obs1 = copy.deepcopy(env.state[1].observation)

        if seat == 0:
            act0 = player_act(obs0, env.configuration, mod_cand, 0)
            act1 = player_act(obs1, env.configuration, mod_opp, 1)
        else:
            act0 = player_act(obs0, env.configuration, mod_opp, 0)
            act1 = player_act(obs1, env.configuration, mod_cand, 1)

        env.step([act0, act1])
        step += 1

    cand_obs = env.state[seat].observation
    opp_obs = env.state[1 - seat].observation

    cand_score = float(cand_obs["farms"][seat]["money"])
    opp_score = float(opp_obs["farms"][1 - seat]["money"])

    # Extract telemetry from daily log
    get_log_fn = getattr(mod_cand, "get_daily_log", None) or getattr(mod_cand, "get_daily_telemetry", lambda: {})
    daily_log = get_log_fn()
    travel_shares = [d.get("travel_share", 0.0) for d in daily_log.values()]
    completion_rates = [d.get("completion_rate", 0.0) for d in daily_log.values()]

    # Extract seasonal SW telemetry
    get_sw_fn = getattr(mod_cand, "get_sw_season_summary", None) or getattr(mod_cand, "get_sw_telemetry", lambda: {})
    sw_season = get_sw_fn()

    # Extract SW tile breakdown using authoritative helper (or fallback with exact 10x10 coordinates)
    farm_raw = cand_obs["farms"][seat]
    if hasattr(mod_cand, "get_sw_tile_breakdown"):
        sw_breakdown = mod_cand.get_sw_tile_breakdown(farm_raw)
    else:
        raw_tiles = farm_raw.get("tiles", [])
        sw_owned = "SW" in farm_raw.get("unlocked_quadrants", ["NW"])
        act = 0
        empty = 0
        if sw_owned:
            for r in range(5, min(10, len(raw_tiles))):
                for c in range(0, min(5, len(raw_tiles[r]))):
                    t = raw_tiles[r][c]
                    if isinstance(t, dict):
                        k = t.get("kind")
                        if k in ("PLANT", "ANIMAL", "PASTURE", "COOP"):
                            act += 1
                        elif k == "EMPTY":
                            empty += 1
        sw_breakdown = {
            "sw_owned": sw_owned,
            "active": act,
            "utilization": round(act / 25.0, 4) if sw_owned else None,
            "empty": empty if sw_owned else None,
        }

    # Count crop deaths from tile observation
    final_tiles = [
        t for row in cand_obs["farms"][seat]["tiles"] for t in row
        if isinstance(t, dict)
    ]
    dead_crops = sum(1 for t in final_tiles if t.get("kind") == "DEAD_PLANT")

    sw_owned = sw_season.get("sw_owned", sw_breakdown.get("sw_owned", False))
    sw_unlock_day = sw_season.get("first_sw_unlock_day")
    sw_active_final = sw_breakdown.get("active", 0)
    sw_avg_util = sw_season.get("avg_sw_util_after_unlock")
    sw_peak_util = sw_season.get("peak_sw_util")
    sw_tasks_created = sw_season.get("sw_tasks_created", 0)
    sw_tasks_assigned = sw_season.get("sw_tasks_assigned", 0)
    sw_tasks_completed = sw_season.get("sw_tasks_completed", 0)
    sw_comp_rate = sw_season.get("sw_completion_rate")
    sw_empty_tile_days = sw_season.get("cumulative_sw_empty_tile_days")

    return {
        "seed": seed,
        "seat": seat,
        "candidate_score": cand_score,
        "opponent_score": opp_score,
        "margin": cand_score - opp_score,
        "fallbacks": len(fallbacks),
        "crop_deaths": dead_crops,
        "animal_deaths": animal_deaths,
        "missed_feeds": missed_feeds,
        "mean_travel_share": round(sum(travel_shares) / max(1, len(travel_shares)), 4),
        "mean_completion_rate": round(sum(completion_rates) / max(1, len(completion_rates)), 4),
        "sw_owned": sw_owned,
        "first_sw_unlock_day": sw_unlock_day,
        "final_sw_active_tiles": sw_active_final,
        "avg_sw_util_after_unlock": sw_avg_util,
        "peak_sw_util": sw_peak_util,
        "sw_tasks_created": sw_tasks_created,
        "sw_tasks_assigned": sw_tasks_assigned,
        "sw_tasks_completed": sw_tasks_completed,
        "sw_completion_rate": sw_comp_rate,
        "cumulative_sw_empty_tile_days": sw_empty_tile_days,
        "unlocked_quadrants": cand_obs["farms"][seat].get("unlocked_quadrants", []),
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-seed Regression Benchmark")
    parser.add_argument("--candidate", default="dist/submission.py")
    parser.add_argument("--baseline", default="dist/submission.py")
    parser.add_argument("--opponent", choices=["pass", "baseline"], default="pass")
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 101, 202, 303, 404])
    parser.add_argument("--output", default="benchmark_telemetry_results.json")
    args = parser.parse_args()

    opp_path = None if args.opponent == "pass" else args.baseline
    print(f"Running multi-seed telemetry benchmark: candidate={args.candidate}, opponent={args.opponent}, seeds={args.seeds}")

    results = []
    for s in args.seeds:
        print(f"  Evaluating seed {s}...", flush=True)
        res = run_benchmark_match(args.candidate, opp_path, s, seat=0)
        results.append(res)
        print(
            f"    Seed {s}: Score=${res['candidate_score']:,.2f} | Margin=+${res['margin']:,.2f} | Fallbacks={res['fallbacks']} | "
            f"Travel={res['mean_travel_share']*100:.1f}% | Comp={res['mean_completion_rate']*100:.1f}% | "
            f"SW_Owned={'Yes' if res['sw_owned'] else 'No'} | "
            f"SW_Unlock={fmt_val(res['first_sw_unlock_day'])} | "
            f"SW_Tiles={res['final_sw_active_tiles']} | "
            f"SW_Avg_Util={fmt_val(res['avg_sw_util_after_unlock'], is_pct=True)} | "
            f"SW_Comp={fmt_val(res['sw_completion_rate'], is_pct=True)} | "
            f"SW_Tasks={res['sw_tasks_created']}/{res['sw_tasks_assigned']}/{res['sw_tasks_completed']} | "
            f"SW_Empty_Days={fmt_val(res['cumulative_sw_empty_tile_days'])}"
        )

    scores = [r["candidate_score"] for r in results]
    mean_score = sum(scores) / len(scores)
    variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
    std_dev = math.sqrt(variance)

    valid_sw_comps = [r["sw_completion_rate"] for r in results if r["sw_completion_rate"] is not None]
    avg_sw_comp = round(sum(valid_sw_comps) / len(valid_sw_comps), 4) if valid_sw_comps else None

    valid_sw_utils = [r["avg_sw_util_after_unlock"] for r in results if r["avg_sw_util_after_unlock"] is not None]
    avg_sw_util = round(sum(valid_sw_utils) / len(valid_sw_utils), 4) if valid_sw_utils else None

    summary = {
        "candidate": args.candidate,
        "opponent": args.opponent,
        "n_matches": len(results),
        "seeds": args.seeds,
        "mean_score": round(mean_score, 2),
        "std_dev": round(std_dev, 2),
        "min_score": min(scores),
        "max_score": max(scores),
        "total_fallbacks": sum(r["fallbacks"] for r in results),
        "total_crop_deaths": sum(r["crop_deaths"] for r in results),
        "total_animal_deaths": sum(r["animal_deaths"] for r in results),
        "total_missed_feeds": sum(r["missed_feeds"] for r in results),
        "avg_travel_share": round(sum(r["mean_travel_share"] for r in results) / len(results), 4),
        "avg_completion_rate": round(sum(r["mean_completion_rate"] for r in results) / len(results), 4),
        "avg_sw_completion_rate": avg_sw_comp,
        "avg_sw_utilization": avg_sw_util,
        "total_sw_tasks_created": sum(r["sw_tasks_created"] for r in results),
        "total_sw_tasks_assigned": sum(r["sw_tasks_assigned"] for r in results),
        "total_sw_tasks_completed": sum(r["sw_tasks_completed"] for r in results),
        "matches": results,
    }

    out_file = Path(args.output)
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nBenchmark Complete! Summary saved to {args.output}")
    print(f"Mean Score: ${mean_score:,.2f} (+/- ${std_dev:,.2f})")
    print(f"Min: ${min(scores):,.2f} | Max: ${max(scores):,.2f}")
    print(f"Total Fallbacks: {summary['total_fallbacks']}")
    print(f"Total Animal Deaths: {summary['total_animal_deaths']}")
    print(f"Total Missed Feeds: {summary['total_missed_feeds']}")
    print(f"Avg Travel Share: {summary['avg_travel_share']*100:.1f}%")
    print(f"Avg Completion Rate: {summary['avg_completion_rate']*100:.1f}%")
    print(f"Avg SW Completion Rate: {fmt_val(summary['avg_sw_completion_rate'], is_pct=True)}")
    print(f"Avg SW Utilization: {fmt_val(summary['avg_sw_utilization'], is_pct=True)}")


if __name__ == "__main__":
    main()
