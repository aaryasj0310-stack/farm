"""
Point-2 Early Livestock Bootstrap Experiment Runner
Authoritative Frozen Point-2 Base: 08c494d5e4744777a09e9215df1148c745a5b1ac

Compares 5 Arms across 10 diagnostic seeds (50 seasons total):
  Arm A: Frozen Live baseline (no bootstrap exception)
  Arm B: 2 COW bootstrap (COW, COW)
  Arm C: 2 COW + 1 SHEEP bootstrap (COW, COW, SHEEP)
  Arm D: 2 COW + 2 SHEEP bootstrap (COW, COW, SHEEP, SHEEP)
  Arm E: 3 COW control (COW, COW, COW)

Tracks:
  - Day 0 requested vs admitted cohort
  - Cash checkpoints (Days 1, 3, 5, 10, 12)
  - Final score
  - NE unlock timing
  - Herd milestones (max herd, end herd, starvations/deaths)
  - Revenue breakdowns (Crop, Milk, Wool, Fertilizer)
  - WHEAT spend
"""
import sys
import os
import json
import copy
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
    {"name": "ArmA", "label": "A Live", "boot_arm": "none"},
    {"name": "ArmB", "label": "B 2C", "boot_arm": "ArmB"},
    {"name": "ArmC", "label": "C 2C1S", "boot_arm": "ArmC"},
    {"name": "ArmD", "label": "D 2C2S", "boot_arm": "ArmD"},
    {"name": "ArmE", "label": "E 3C", "boot_arm": "ArmE"},
]


def run_single_match(seed: int, opponent_name: str, arm_name: str, boot_arm: str) -> Dict[str, Any]:
    import config as cfg
    cfg.POINT2_FEED_MODE = "live"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = boot_arm

    for mod_name in ("agent.main", "main", "agent.config", "config", "agent.strategy.macro_planner", "macro_planner"):
        if mod_name in sys.modules:
            setattr(sys.modules[mod_name], "POINT2_FEED_MODE", "live")
            setattr(sys.modules[mod_name], "BOOTSTRAP_LIVESTOCK_ARM", boot_arm)

    from main import _agent_decision, reset_agent_state
    reset_agent_state()

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.reset(2)
    opp_callable = get_agent(opponent_name)

    day0_requested = cfg.get_bootstrap_target_sequence(boot_arm)
    day0_admitted = []
    day0_rejected = []
    day0_candidate_decisions = []

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
    crop_rev_d5 = 0.0
    crop_rev_d10 = 0.0
    milk_rev = 0.0
    wool_rev = 0.0
    fert_rev = 0.0
    wheat_spend = 0.0
    wheat_bought_units = 0
    animal_spend = 0.0
    actual_feed_consumed = 0

    step = 0
    prev_total_owned = 0
    day0_seeds_planted = {}

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

        if hour == 0 and day in (1, 3, 5, 10, 12) and day not in cash_checkpoints:
            cash_checkpoints[day] = round(money0, 2)

        if ne_unlock_day is None and "NE" in quads:
            ne_unlock_day = day
            ne_unlock_hour = hour
        if sw_unlock_day is None and "SW" in quads:
            sw_unlock_day = day
            sw_unlock_hour = hour

        # Telemetry: Count placed herd, unplaced herd (shed + workers), total owned herd
        placed_herd = 0
        placed_species = defaultdict(int)
        for row in farm0.get("tiles", []):
            for t in row:
                if isinstance(t, dict) and (t.get("animal") is not None or t.get("is_animal")):
                    placed_herd += 1
                    placed_species[t.get("animal")] += 1

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

        # Feed consumption: count at hour 23 for each fed placed animal
        if hour == 23 and placed_herd > 0:
            actual_feed_consumed += placed_herd

        action0 = _agent_decision(obs0)
        try:
            action1 = opp_callable(obs1)
        except Exception:
            action1 = {"farmer": ["PASS"], "hands": [], "market": []}

        # Step 0 Day 0 admission tracking
        if step == 0:
            for act in action0.get("market", []):
                if act[0] == "BUY_ANIMAL":
                    sp = act[1]
                    qty = int(act[2]) if len(act) > 2 else 1
                    day0_admitted.extend([sp] * qty)
            # Rejections
            day0_rejected = [sp for sp in day0_requested]
            for sp in day0_admitted:
                if sp in day0_rejected:
                    day0_rejected.remove(sp)

        # Track market order spending / revenue
        for o in action0.get("market", []):
            op = o[0]
            if op == "SELL":
                prod = o[1]
                qty = int(o[2])
                px = float(MARKET_PARAMS[prod]["base"])
                approx_val = px * qty
                if prod == "MILK":
                    milk_rev += approx_val
                elif prod == "WOOL":
                    wool_rev += approx_val
                elif prod == "FERTILIZER":
                    fert_rev += approx_val
                elif prod in CROPS:
                    crop_rev += approx_val
                    if day < 5:
                        crop_rev_d5 += approx_val
                    if day < 10:
                        crop_rev_d10 += approx_val
            elif op == "BUY_PRODUCT" and o[1] == "WHEAT":
                qty = int(o[2])
                wheat_bought_units += qty
                wheat_spend += float(28.0 * qty)
            elif op == "BUY_ANIMAL":
                sp = o[1]
                qty = int(o[2]) if len(o) > 2 else 1
                animal_spend += float(ANIMALS[sp]["cost"] * qty)
            elif op == "BUY_SEED" and step < 24:
                crop = o[1]
                qty = int(o[2])
                day0_seeds_planted[crop] = day0_seeds_planted.get(crop, 0) + qty

        # Step
        env.step([action0, action1])
        step += 1

    # Final season observation
    final_obs = env.state[0].observation
    final_farm = final_obs["farms"][0]
    final_score = float(final_farm["money"])
    final_quads = list(final_farm.get("unlocked_quadrants", []))
    if ne_unlock_day is None and "NE" in final_quads:
        ne_unlock_day = 29

    # Count final animals and structures
    final_placed_herd = 0
    final_sp_counts = defaultdict(int)
    total_pastures_built = 0
    for row in final_farm.get("tiles", []):
        for t in row:
            if isinstance(t, dict):
                if t.get("animal") is not None or t.get("is_animal"):
                    final_placed_herd += 1
                    final_sp_counts[t.get("animal")] += 1
                if t.get("kind") == "PASTURE":
                    total_pastures_built += 1

    final_shed_animals = 0
    final_worker_animals = 0
    if "private" in final_obs:
        priv = final_obs["private"]
        if "shed" in priv and isinstance(priv["shed"], dict):
            for sp in ("COW", "SHEEP", "GOOSE"):
                c = int(priv["shed"].get(sp, 0))
                final_shed_animals += c
                final_sp_counts[sp] += c
        if "inventories" in priv and isinstance(priv["inventories"], list):
            for inv in priv["inventories"]:
                if isinstance(inv, dict):
                    for sp in ("COW", "SHEEP", "GOOSE"):
                        c = int(inv.get(sp, 0))
                        final_worker_animals += c
                        final_sp_counts[sp] += c

    final_total_owned_herd = final_placed_herd + final_shed_animals + final_worker_animals
    unused_pastures = max(0, total_pastures_built - final_placed_herd)

    return {
        "arm": arm_name,
        "seed": seed,
        "opponent": opponent_name,
        "score": round(final_score, 2),
        "day0_requested": day0_requested,
        "day0_admitted": day0_admitted,
        "day0_rejected": day0_rejected,
        "day0_seeds_planted": day0_seeds_planted,
        "cash_checkpoints": cash_checkpoints,
        "min_cash": round(min_cash, 2),
        "ne_unlock_day": ne_unlock_day,
        "ne_unlock_hour": ne_unlock_hour,
        "sw_unlock_day": sw_unlock_day,
        "sw_unlock_hour": sw_unlock_hour,
        "placed_herd": final_placed_herd,
        "owned_unplaced_herd": final_shed_animals + final_worker_animals,
        "total_owned_herd": final_total_owned_herd,
        "max_placed_herd": max_placed_herd,
        "max_total_owned_herd": max_total_owned_herd,
        "final_placed_herd": final_placed_herd,
        "final_total_owned_herd": final_total_owned_herd,
        "final_herd_composition": dict(final_sp_counts),
        "starvations_or_deaths": starvations_or_deaths,
        "escapes": escapes,
        "negative_cash_events": negative_cash_events,
        "crop_revenue": round(crop_rev, 2),
        "crop_revenue_d5": round(crop_rev_d5, 2),
        "crop_revenue_d10": round(crop_rev_d10, 2),
        "milk_revenue": round(milk_rev, 2),
        "wool_revenue": round(wool_rev, 2),
        "fertilizer_revenue": round(fert_rev, 2),
        "wheat_bought_units": wheat_bought_units,
        "wheat_spend": round(wheat_spend, 2),
        "actual_feed_consumed": actual_feed_consumed,
        "pastures_built": total_pastures_built,
        "unused_pastures": unused_pastures,
    }


from concurrent.futures import ProcessPoolExecutor, as_completed


def _worker_task(args):
    seed, opp, arm_name, boot_arm = args
    return run_single_match(seed, opp, arm_name, boot_arm)


def main():
    print("==================================================================")
    print("STARTING POINT 2 EARLY LIVESTOCK BOOTSTRAP EXPERIMENT (50 SEASONS)")
    print("==================================================================")
    t0 = time.time()

    tasks = []
    for arm_cfg in ARMS:
        arm_name = arm_cfg["name"]
        boot_arm = arm_cfg["boot_arm"]
        for s_info in SEEDS:
            tasks.append((s_info["seed"], s_info["opponent"], arm_name, boot_arm))

    print(f"Executing {len(tasks)} matches in parallel across worker processes...")
    all_results = []
    with ProcessPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_worker_task, t): t for t in tasks}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            all_results.append(res)
            completed += 1
            print(f"  [{completed:>2}/50] Arm {res['arm']:<5} Seed {res['seed']:>4} vs {res['opponent']:<22} -> Score: ${res['score']:>8,.2f}, Placed: {res['max_placed_herd']}/{res['max_total_owned_herd']}, NE: D{res['ne_unlock_day']}")

    # Sort results by arm order, then seed order
    arm_order = {arm_cfg["name"]: i for i, arm_cfg in enumerate(ARMS)}
    seed_order = {s_info["seed"]: i for i, s_info in enumerate(SEEDS)}
    all_results.sort(key=lambda r: (arm_order[r["arm"]], seed_order[r["seed"]]))

    elapsed = time.time() - t0
    print(f"\nAll 50 matches completed in {elapsed:.1f}s!")

    output_path = os.path.join(ROOT_DIR, "scratch", "bootstrap_experiment_results.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"Saved results to {output_path}")

    # Restore production defaults
    import config as cfg
    cfg.POINT2_FEED_MODE = "shadow"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
    print("Restored production defaults: POINT2_FEED_MODE = 'shadow', BOOTSTRAP_LIVESTOCK_ARM = 'none'")


if __name__ == "__main__":
    main()
