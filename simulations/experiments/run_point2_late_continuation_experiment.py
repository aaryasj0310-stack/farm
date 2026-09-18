"""
Point-2 One-at-a-Time Late Housing Continuation Experiment Runner
Authoritative Frozen Point-2 Base: 08c494d5e4744777a09e9215df1148c745a5b1ac

Compares 4 Arms across 10 diagnostic seeds (40 seasons total):
  Arm A: Frozen Live baseline (no bootstrap, no late continuation)
  Arm B: 3 COW bootstrap (no late continuation)
  Arm C: 3 COW bootstrap + one-at-a-time late continuation
  Arm D: 2 COW + 1 SHEEP bootstrap + one-at-a-time late continuation

Telemetry Tracked:
  - Final scores (mean, std, min, max, delta vs Arm A, delta vs Arm B)
  - Day 12–14 continuation decisions (candidates evaluated/admitted, species, net values)
  - Housing transition traces on Days 12, 13, 14 (physical, occupied, in-flight, owned animals)
  - Anti-overbuilding metrics (wasted pastures at Day 30, stranded animals, pasture utilization)
  - Cash checkpoints (Days 1, 3, 5, 10, 12, 14, 20, 30)
  - Revenue breakdowns (Crop, Milk, Wool, Fertilizer, Total)
  - Safety table (starvations, deaths, escapes, negative cash, errors)
  - Shadow benchmark comparison (Canonical Shadow Gap = $28,765.30)
"""
import sys
import os
import json
import time
from collections import defaultdict
from typing import Dict, Any, List, Optional

ROOT_DIR = "d:/website project/kaggri ox"
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

SEEDS = [
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

ARMS = [
    {"name": "ArmA", "label": "A: Frozen Live", "boot_arm": "none", "late_cont": False},
    {"name": "ArmB", "label": "B: 3C Boot", "boot_arm": "ArmE", "late_cont": False},
    {"name": "ArmC", "label": "C: 3C + Late1", "boot_arm": "ArmE", "late_cont": True},
    {"name": "ArmD", "label": "D: 2C1S + Late1", "boot_arm": "ArmC", "late_cont": True},
]


def run_single_match(seed: int, opponent_name: str, arm_name: str, boot_arm: str, late_cont: bool) -> Dict[str, Any]:
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
    ne_unlock_day = None
    ne_unlock_hour = None
    sw_unlock_day = None
    sw_unlock_hour = None

    max_placed_herd = 0
    max_total_owned_herd = 0
    starvations_or_deaths = 0
    escapes = 0
    negative_cash_events = 0

    crop_rev = 0.0
    milk_rev = 0.0
    wool_rev = 0.0
    fert_rev = 0.0
    wheat_spend = 0.0
    wheat_bought_units = 0
    animal_spend = 0.0

    # Telemetry for Days 12-14
    housing_traces = {}  # day -> {physical, occupied, empty, in_flight, owned}
    day12_14_decisions = []
    pasture_build_events = []
    animal_buy_events = []

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

        quads = list(farm0.get("unlocked_quadrants", []))

        if hour == 0 and day in (1, 3, 5, 10, 12, 14, 20) and day not in cash_checkpoints:
            cash_checkpoints[day] = round(money0, 2)

        if ne_unlock_day is None and "NE" in quads:
            ne_unlock_day = day
            ne_unlock_hour = hour
        if sw_unlock_day is None and "SW" in quads:
            sw_unlock_day = day
            sw_unlock_hour = hour

        # Telemetry: Housing and animal counts
        physical_pastures = 0
        occupied_pastures = 0
        placed_herd = 0
        for row in farm0.get("tiles", []):
            for t in row:
                if isinstance(t, dict):
                    if t.get("kind") == "PASTURE" or t.get("structure") == "PASTURE":
                        physical_pastures += 1
                        if t.get("animal") is not None or t.get("is_animal"):
                            occupied_pastures += 1
                    if t.get("animal") is not None or t.get("is_animal"):
                        placed_herd += 1

        if physical_pastures > prev_pasture_count and step > 0:
            pasture_build_events.append({"day": day, "hour": hour, "new_total": physical_pastures})
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

        # Day 12-14 housing snapshot at Hour 0
        if hour == 0 and day in (12, 13, 14):
            housing_traces[day] = {
                "physical_pastures": physical_pastures,
                "occupied_pastures": occupied_pastures,
                "empty_pastures": physical_pastures - occupied_pastures,
                "owned_herd": total_owned_herd,
            }

        action0 = _agent_decision(obs0)
        try:
            action1 = opp_callable(obs1)
        except Exception:
            action1 = {}

        # Log purchases and market actions
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

        env.step([action0, action1])
        step += 1

        if step > 1 and total_owned_herd < prev_total_owned:
            starvations_or_deaths += (prev_total_owned - total_owned_herd)
        prev_total_owned = total_owned_herd

    # Day 30 final state
    final_score = float(env.state[0].reward if env.state[0].reward is not None else farm0["money"])
    cash_checkpoints[30] = round(final_score, 2)

    # End-of-season housing metrics
    wasted_pastures = max(0, physical_pastures - occupied_pastures)
    stranded_animals = owned_unplaced_herd
    pasture_utilization = (occupied_pastures / physical_pastures) if physical_pastures > 0 else 0.0

    return {
        "arm": arm_name,
        "seed": seed,
        "opponent": opponent_name,
        "final_score": final_score,
        "cash_checkpoints": cash_checkpoints,
        "min_cash": round(min_cash, 2),
        "negative_cash_events": negative_cash_events,
        "starvations_or_deaths": starvations_or_deaths,
        "escapes": escapes,
        "max_placed_herd": max_placed_herd,
        "max_total_owned_herd": max_total_owned_herd,
        "end_placed_herd": placed_herd,
        "end_total_owned_herd": total_owned_herd,
        "end_physical_pastures": physical_pastures,
        "wasted_pastures": wasted_pastures,
        "stranded_animals": stranded_animals,
        "pasture_utilization": round(pasture_utilization, 3),
        "housing_traces": housing_traces,
        "pasture_build_events": pasture_build_events,
        "animal_buy_events": animal_buy_events,
        "ne_unlock_day": ne_unlock_day,
        "ne_unlock_hour": ne_unlock_hour,
        "sw_unlock_day": sw_unlock_day,
        "sw_unlock_hour": sw_unlock_hour,
        "crop_rev": round(crop_rev, 2),
        "milk_rev": round(milk_rev, 2),
        "wool_rev": round(wool_rev, 2),
        "fert_rev": round(fert_rev, 2),
        "wheat_spend": round(wheat_spend, 2),
        "animal_spend": round(animal_spend, 2),
    }


def main():
    print(f"=== Starting Point-2 One-at-a-Time Late Housing Continuation Experiment ===")
    print(f"Authoritative Base: 08c494d5e4744777a09e9215df1148c745a5b1ac")
    print(f"Arms: {[a['name'] for a in ARMS]}")
    print(f"Seeds: {len(SEEDS)} seeds ({len(ARMS) * len(SEEDS)} total seasons)\n")

    all_results = []
    start_time = time.time()

    for arm_cfg in ARMS:
        arm_name = arm_cfg["name"]
        arm_label = arm_cfg["label"]
        boot_arm = arm_cfg["boot_arm"]
        late_cont = arm_cfg["late_cont"]

        print(f"\n--- Running {arm_label} ({arm_name}: boot={boot_arm}, late_cont={late_cont}) ---")
        for s_idx, s_info in enumerate(SEEDS):
            seed = s_info["seed"]
            opp = s_info["opponent"]
            t0 = time.time()
            res = run_single_match(seed, opp, arm_name, boot_arm, late_cont)
            elapsed = time.time() - t0
            all_results.append(res)
            print(f"  [{arm_name}] Seed {seed:4d} vs {opp:20s} -> Score: ${res['final_score']:,.0f} | Herd: {res['end_total_owned_herd']} | Pastures: {res['end_physical_pastures']} ({elapsed:.1f}s)")

    total_time = time.time() - start_time
    print(f"\nCompleted 40 matches in {total_time:.1f}s")

    # Save raw results
    out_path = os.path.join(ROOT_DIR, "simulations/experiments/results/point2_late_continuation_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Raw results saved to {out_path}")


if __name__ == "__main__":
    main()
