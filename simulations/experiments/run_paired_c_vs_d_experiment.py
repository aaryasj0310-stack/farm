"""
Point-2 Paired Arm C vs Arm D Controlled Experiment Runner.

Compares:
  Arm C: 3 COW bootstrap + one-at-a-time late housing (boot=ArmE, late_cont=True)
  Arm D: 2 COW + 1 SHEEP bootstrap + one-at-a-time late housing (boot=ArmC, late_cont=True)

Runs 100 paired seeds (200 matches) across 5 benchmark opponents:
  - pass
  - pure_wheat_rush
  - cow_milk_engine
  - melon_sniper
  - full_production_agent
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
AGENT_DIR = os.path.join(ROOT_DIR, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import kaggle_environments
from kaggle_environments.envs.kaggriculture.kaggriculture import (
    ANIMALS, CROPS, MARKET_PARAMS, MARKET_I0
)
from simulations.experiments.agent_zoo import get_agent


OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]

BENCHMARK_SEEDS = [
    {"seed": 42, "opponent": "pass"},
    {"seed": 101, "opponent": "pure_wheat_rush"},
    {"seed": 2024, "opponent": "cow_milk_engine"},
    {"seed": 7, "opponent": "melon_sniper"},
    {"seed": 999, "opponent": "full_production_agent"},
    {"seed": 1234, "opponent": "pass"},
    {"seed": 55, "opponent": "pure_wheat_rush"},
    {"seed": 314, "opponent": "cow_milk_engine"},
    {"seed": 8888, "opponent": "melon_sniper"},
    {"seed": 777, "opponent": "full_production_agent"},
]


def generate_100_paired_seeds() -> List[Dict[str, Any]]:
    seeds = list(BENCHMARK_SEEDS)
    # Generate 90 additional deterministic seeds, cycling opponents evenly (20 each total)
    for i in range(90):
        s_val = 10000 + i * 37 + (i % 7) * 11
        opp = OPPONENTS[i % 5]
        seeds.append({"seed": s_val, "opponent": opp})
    return seeds


def run_match_single_arm(seed: int, opponent_name: str, arm_name: str, boot_arm: str, late_cont: bool) -> Dict[str, Any]:
    import config as cfg
    cfg.POINT2_FEED_MODE = "live"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = boot_arm
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = late_cont

    for mod_name in ("agent.main", "main", "agent.config", "config", "agent.strategy.macro_planner", "macro_planner", "agent.strategy.herd_planner", "herd_planner"):
        if mod_name in sys.modules:
            setattr(sys.modules[mod_name], "POINT2_FEED_MODE", "live")
            setattr(sys.modules[mod_name], "BOOTSTRAP_LIVESTOCK_ARM", boot_arm)
            setattr(sys.modules[mod_name], "ONE_AT_A_TIME_LATE_HOUSING_ENABLED", late_cont)

    from main import _agent_decision, reset_agent_state
    reset_agent_state()

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.reset(2)
    opp_callable = get_agent(opponent_name)

    cash_checkpoints = {}
    min_cash = 3000.0
    negative_cash_events = 0

    max_placed_herd = 0
    max_total_owned_herd = 0
    starvations_or_deaths = 0
    escapes = 0

    crop_rev = 0.0
    milk_rev = 0.0
    wool_rev = 0.0
    fert_rev = 0.0

    wheat_bought_units = 0
    wheat_spend = 0.0
    animal_spend = 0.0
    total_feed_consumed = 0
    day0_cash_deployment = 0.0

    pasture_build_events = []
    animal_buy_events = []
    continuation_starts_post_d14 = 0

    step = 0
    prev_total_owned = 0
    prev_pasture_count = 0

    while not env.done:
        obs0 = env.state[0].observation
        obs1 = env.state[1].observation

        day = obs0.get("day", step // 24)
        hour = obs0.get("hour", step % 24)
        farm0 = obs0["farms"][0]
        money0 = float(farm0["money"])
        min_cash = min(min_cash, money0)
        if money0 < 0:
            negative_cash_events += 1

        if hour == 0 and day in (1, 3, 5, 10, 12, 14, 20) and day not in cash_checkpoints:
            cash_checkpoints[day] = round(money0, 2)

        if step == 23:  # End of Day 0
            day0_cash_deployment = round(3000.0 - money0, 2)

        # Telemetry: Housing and animal counts
        physical_pastures = 0
        occupied_pastures = 0
        placed_herd = 0
        herd_comp = {"COW": 0, "SHEEP": 0, "GOOSE": 0}
        for row in farm0.get("tiles", []):
            for t in row:
                if isinstance(t, dict):
                    if t.get("kind") == "PASTURE" or t.get("structure") == "PASTURE":
                        physical_pastures += 1
                        sp = t.get("animal")
                        if sp is not None or t.get("is_animal"):
                            occupied_pastures += 1
                    if t.get("animal") is not None or t.get("is_animal"):
                        placed_herd += 1
                        sp = t.get("animal", "COW")
                        if sp in herd_comp:
                            herd_comp[sp] += 1

        if physical_pastures > prev_pasture_count and step > 0:
            pasture_build_events.append({"day": day, "hour": hour, "new_total": physical_pastures})
            if day >= 14:
                continuation_starts_post_d14 += 1
            prev_pasture_count = physical_pastures
        elif physical_pastures > prev_pasture_count and step == 0:
            prev_pasture_count = physical_pastures

        shed_animals = 0
        worker_animals = 0
        if "private" in obs0:
            priv = obs0["private"]
            if "shed" in priv and isinstance(priv["shed"], dict):
                for sp in ("COW", "SHEEP", "GOOSE"):
                    shed_animals += int(priv["shed"].get(sp, 0))
            if "inventories" in priv and isinstance(priv["inventories"], list):
                for inv in priv["inventories"]:
                    if isinstance(inv, dict):
                        for sp in ("COW", "SHEEP", "GOOSE"):
                            worker_animals += int(inv.get(sp, 0))

        owned_unplaced_herd = shed_animals + worker_animals
        total_owned_herd = placed_herd + owned_unplaced_herd

        if placed_herd > max_placed_herd:
            max_placed_herd = placed_herd
        if total_owned_herd > max_total_owned_herd:
            max_total_owned_herd = total_owned_herd

        action0 = _agent_decision(obs0)
        try:
            action1 = opp_callable(obs1)
        except Exception:
            action1 = {}

        # Log purchases, sales, feeds
        orders = action0.get("market", []) if isinstance(action0, dict) else []
        market_prices = obs0.get("market", {}).get("prices", {}) if isinstance(obs0.get("market"), dict) else {}
        for o in orders:
            if isinstance(o, (list, tuple)) and len(o) >= 2:
                op = o[0]
                if op == "BUY_ANIMAL":
                    sp = o[1]
                    cnt = int(o[2]) if len(o) > 2 else 1
                    cost = ANIMALS[sp]["cost"] * cnt
                    animal_spend += cost
                    animal_buy_events.append({"day": day, "hour": hour, "species": sp, "count": cnt})
                elif op in ("BUY_PRODUCT", "BUY") and o[1] == "WHEAT":
                    qty = int(o[2]) if len(o) > 2 else 1
                    wheat_bought_units += qty
                    wheat_spend += qty * 25.0
                elif op == "SELL":
                    item = o[1]
                    qty = int(o[2]) if len(o) > 2 else 1
                    item_px = float(market_prices.get(item, 0.0))
                    item_rev = qty * item_px
                    if item in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
                        crop_rev += item_rev
                    elif item == "MILK":
                        milk_rev += item_rev
                    elif item == "WOOL":
                        wool_rev += item_rev
                    elif item == "FERTILIZER":
                        fert_rev += item_rev

        # Track feed actions
        f_op = action0.get("farmer", []) if isinstance(action0, dict) else []
        if isinstance(f_op, (list, tuple)) and len(f_op) > 0 and f_op[0] == "FEED":
            total_feed_consumed += 1
        for h_op in (action0.get("hands", []) if isinstance(action0, dict) else []):
            if isinstance(h_op, (list, tuple)) and len(h_op) > 0 and h_op[0] == "FEED":
                total_feed_consumed += 1

        env.step([action0, action1])
        step += 1

        if step > 1 and total_owned_herd < prev_total_owned:
            starvations_or_deaths += (prev_total_owned - total_owned_herd)

        prev_total_owned = total_owned_herd

    final_money = float(env.state[0].observation["farms"][0]["money"])
    cash_checkpoints[30] = round(final_money, 2)

    # Invariants checks
    wasted_pastures = max(0, physical_pastures - placed_herd)
    stranded_animals = owned_unplaced_herd

    return {
        "arm": arm_name,
        "seed": seed,
        "opponent": opponent_name,
        "final_score": round(final_money, 2),
        "crop_revenue": round(crop_rev, 2),
        "milk_revenue": round(milk_rev, 2),
        "wool_revenue": round(wool_rev, 2),
        "fertilizer_revenue": round(fert_rev, 2),
        "animal_purchase_cost": round(animal_spend, 2),
        "feed_purchase_cost": round(wheat_spend, 2),
        "wheat_bought_units": wheat_bought_units,
        "total_feed_consumed": total_feed_consumed,
        "day0_cash_deployment": day0_cash_deployment,
        "cash_checkpoints": cash_checkpoints,
        "final_herd_composition": herd_comp,
        "final_placed_herd": placed_herd,
        "final_total_owned_herd": total_owned_herd,
        "final_pasture_count": physical_pastures,
        "pasture_build_events": pasture_build_events,
        "animal_buy_events": animal_buy_events,
        "continuation_starts_post_d14": continuation_starts_post_d14,
        "wasted_pastures": wasted_pastures,
        "stranded_animals": stranded_animals,
        "starvations_or_deaths": starvations_or_deaths,
        "escapes": escapes,
        "negative_cash_events": negative_cash_events,
        "min_cash": round(min_cash, 2),
    }


def run_paired_seed_job(seed_entry: Dict[str, Any]) -> Dict[str, Any]:
    seed = seed_entry["seed"]
    opp = seed_entry["opponent"]

    # 1. Run Arm C (3 COW + Late1)
    res_c = run_match_single_arm(seed=seed, opponent_name=opp, arm_name="ArmC", boot_arm="ArmE", late_cont=True)

    # 2. Run Arm D (2 COW + 1 SHEEP + Late1)
    res_d = run_match_single_arm(seed=seed, opponent_name=opp, arm_name="ArmD", boot_arm="ArmC", late_cont=True)

    delta = round(res_d["final_score"] - res_c["final_score"], 2)
    winner = "D" if delta > 0 else ("C" if delta < 0 else "TIE")

    return {
        "seed": seed,
        "opponent": opp,
        "arm_c": res_c,
        "arm_d": res_d,
        "delta_d_minus_c": delta,
        "winner": winner,
    }


def main():
    print("=== Starting 100-Seed Paired Arm C vs Arm D Experiment ===")
    seeds = generate_100_paired_seeds()
    print(f"Total Paired Seeds: {len(seeds)} (200 complete 30-day seasons)")
    print("Opponents: 20 matches each for pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent")

    out_dir = os.path.join(ROOT_DIR, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "paired_c_vs_d_results.json")

    t0 = time.time()
    results = []

    # Parallel execution with 6 workers
    max_workers = min(6, os.cpu_count() or 4)
    print(f"Executing in parallel with {max_workers} worker processes...")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_paired_seed_job, s): s for s in seeds}
        completed_cnt = 0
        for fut in as_completed(futures):
            completed_cnt += 1
            res = fut.result()
            results.append(res)
            s_val = res["seed"]
            opp = res["opponent"]
            sc_c = res["arm_c"]["final_score"]
            sc_d = res["arm_d"]["final_score"]
            del_val = res["delta_d_minus_c"]
            win = res["winner"]
            elapsed = round(time.time() - t0, 1)
            print(f"[{completed_cnt:3d}/{len(seeds)}] Seed {s_val:5d} vs {opp:21s} | C: ${sc_c:7,.0f} | D: ${sc_d:7,.0f} | D-C: ${del_val:+7,.0f} ({win}) | {elapsed}s")

    # Sort results to match original seed order
    results.sort(key=lambda r: seeds.index(next(s for s in seeds if s["seed"] == r["seed"])))

    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    total_time = round(time.time() - t0, 1)
    print(f"\nAll {len(results)} paired seeds (200 matches) completed in {total_time}s!")
    print(f"Raw results written to: {out_file}")


if __name__ == "__main__":
    main()
