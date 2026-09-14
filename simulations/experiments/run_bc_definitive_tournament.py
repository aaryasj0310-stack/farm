"""Definitive Paired Tournament: Promoted Arm B vs Corrected Dynamic Arm C (300 Paired Seeds).

Evaluates:
  - Arm B (Promoted Production Baseline): Exact joint-future-path shop-conditioned livestock economics
    under frozen target-oriented quotas and production infrastructure planning.
  - Arm C (Corrected Dynamic Architecture): Decoupled DynamicHerdPlan infrastructure planning with
    turn-by-turn transactional shadow-state marginal livestock valuation.

Features:
  - 300 paired seeds (Seeds 100..399), 600 matches total against standard baseline 'starter'.
  - Full process isolation per match across parallel workers.
  - Housing utilization metrics: occupied_structure_hours / available_structure_hours, average & peak unused.
  - Granular labor action telemetry: crop, animal-care, building, movement actions, livestock labor share.
  - Complete economic attribution: Milk, Wool, Egg, Fertilizer, Crops, Animal Spend, Feed Spend, Housing Capital.
  - Stratifications by:
      * Yarn Store Count: 0, 1, 2+
      * Yarn Unlock Timing: Early (<= D9), Late (>= D12), None
      * Milk Demand Shops: 0-1, 2+
      * Egg Demand Shops: 0, 1+
  - Statistical contrasts (C minus B): Mean/Median paired delta, 10k bootstrap 95% CI, paired t-test,
    Wilcoxon signed-rank, Win/Tie/Loss %, P10, P90, CVaR 10%, worst 10 & best 10 seed causal diagnoses.
  - Concludes with definitive promotion verdict.
"""

import os
import sys
import json
import time
import math
import copy
import argparse
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from scipy import stats

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    arm = payload["arm"]
    seed = payload["seed"]
    opp_name = payload.get("opponent", "starter")

    # Clean sys.path and sys.modules to ensure pure process isolation
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")] + clean_sys_path

    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        "main", "config", "strategy", "state", "execution", "market",
        "task_scheduler", "macro_planner", "order_builder", "animal_planner", "pasture_planner",
        "herd_planner", "expansion_planner", "observation_parser", "state_tracker",
        "land_serviceability_model", "marginal_livestock_valuator"
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config
    import strategy.macro_planner as macro_planner

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    macro_planner.clear_livestock_decision_logs()

    # Authoritative arm configuration
    config.set_livestock_experiment_arm(arm)

    # Tracking variables
    peak_cows = 0
    peak_sheep = 0
    peak_geese = 0
    peak_herd = 0

    cows_bought = 0
    sheep_bought = 0
    geese_bought = 0
    cow_buy_days = []
    sheep_buy_days = []
    goose_buy_days = []
    animal_purchases = []

    unfed_animal_days = 0
    max_consecutive_unfed = 0
    consecutive_unfed_ge2_count = 0
    animal_escapes = 0

    housing_capacity_violations = 0
    late_purchase_invariant_violations = 0

    # Housing utilization telemetry
    total_built_pasture_hours = 0
    occupied_pasture_hours = 0
    total_built_coop_hours = 0
    occupied_coop_hours = 0
    daily_unused_pastures = []
    daily_built_pastures = []
    peak_unused_pastures = 0

    # Labor telemetry
    labor_actions = {
        "crop_water": 0, "crop_harvest": 0, "crop_plant": 0, "crop_till": 0,
        "animal_feed": 0, "animal_collect": 0, "build_structure": 0, "movement": 0, "idle_other": 0
    }

    # Revenue and Market Telemetry
    rev_by_product = {
        "MILK": 0.0, "WOOL": 0.0, "FERTILIZER": 0.0, "EGG": 0.0,
        "WHEAT": 0.0, "CARROT": 0.0, "MELON": 0.0, "STRAWBERRY": 0.0, "TOMATO": 0.0
    }
    units_sold = {k: 0 for k in rev_by_product}

    last_money = 3000.0
    last_shed = {}
    last_town_shops = []
    shop_unlock_events = []

    # Arm C daily telemetry
    arm_c_daily_telemetry = []

    def tracking_agent(obs, configuration=None):
        nonlocal peak_cows, peak_sheep, peak_geese, peak_herd
        nonlocal cows_bought, sheep_bought, geese_bought
        nonlocal cow_buy_days, sheep_buy_days, goose_buy_days, animal_purchases
        nonlocal unfed_animal_days, max_consecutive_unfed, consecutive_unfed_ge2_count
        nonlocal animal_escapes, housing_capacity_violations, late_purchase_invariant_violations
        nonlocal total_built_pasture_hours, occupied_pasture_hours, total_built_coop_hours, occupied_coop_hours
        nonlocal daily_unused_pastures, daily_built_pastures, peak_unused_pastures
        nonlocal last_money, last_shed, last_town_shops, shop_unlock_events

        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        farm = obs.get("farm", {})
        curr_money = farm.get("money", 0.0)
        tiles = farm.get("tiles", [])

        # Detect town shop unlocks
        town = obs.get("town", {})
        curr_shops = town.get("unlocked_shops", [])
        if len(curr_shops) > len(last_town_shops):
            new_shops = curr_shops[len(last_town_shops):]
            for s in new_shops:
                shop_unlock_events.append({"day": day, "hour": hour, "shop": s})
            last_town_shops = list(curr_shops)

        # Count animals & structures on tiles
        cows_on_tiles = 0
        sheep_on_tiles = 0
        geese_on_tiles = 0
        built_pastures = 0
        built_coops = 0

        for r_idx, row in enumerate(tiles):
            for c_idx, t_dict in enumerate(row):
                if not isinstance(t_dict, dict):
                    continue
                structure = t_dict.get("structure") or t_dict.get("kind")
                if structure == "PASTURE":
                    built_pastures += 1
                elif structure == "COOP":
                    built_coops += 1

                an = t_dict.get("animal")
                if an == "COW":
                    cows_on_tiles += 1
                elif an == "SHEEP":
                    sheep_on_tiles += 1
                elif an == "GOOSE":
                    geese_on_tiles += 1

                if an:
                    cunfed = t_dict.get("consecutive_unfed", 0)
                    if cunfed > max_consecutive_unfed:
                        max_consecutive_unfed = cunfed
                    if cunfed >= 2:
                        consecutive_unfed_ge2_count += 1
                        if hour == 23:
                            animal_escapes += 1
                    if hour == 0 and cunfed > 0:
                        unfed_animal_days += 1

        # Check shed animals
        priv = obs.get("private", {})
        curr_shed = priv.get("shed", {})
        cows_in_shed = curr_shed.get("COW", 0)
        sheep_in_shed = curr_shed.get("SHEEP", 0)
        geese_in_shed = curr_shed.get("GOOSE", 0)

        tot_cows = cows_on_tiles + cows_in_shed
        tot_sheep = sheep_on_tiles + sheep_in_shed
        tot_geese = geese_on_tiles + geese_in_shed
        tot_herd = tot_cows + tot_sheep + tot_geese

        if tot_cows > peak_cows:
            peak_cows = tot_cows
        if tot_sheep > peak_sheep:
            peak_sheep = tot_sheep
        if tot_geese > peak_geese:
            peak_geese = tot_geese
        if tot_herd > peak_herd:
            peak_herd = tot_herd

        # Structure utilization tracking
        total_built_pasture_hours += built_pastures
        occupied_p = cows_on_tiles + sheep_on_tiles
        occupied_pasture_hours += min(built_pastures, occupied_p)

        total_built_coop_hours += built_coops
        occupied_coop_hours += min(built_coops, geese_on_tiles)

        unused_p = max(0, built_pastures - occupied_p)
        if unused_p > peak_unused_pastures:
            peak_unused_pastures = unused_p

        if hour == 0:
            daily_unused_pastures.append(unused_p)
            daily_built_pastures.append(built_pastures)

        # Invariant checks
        if occupied_p > built_pastures:
            housing_capacity_violations += 1

        # Revenue tracking from market sells
        market_obs = obs.get("market", {})
        market_prices = market_obs.get("prices", {})
        for prod in rev_by_product:
            shed_prev = last_shed.get(prod, 0)
            shed_curr = curr_shed.get(prod, 0)
            if shed_curr < shed_prev and curr_money > last_money:
                units = shed_prev - shed_curr
                approx_price = market_prices.get(prod, 0.0)
                if approx_price > 0:
                    delta_cash = curr_money - last_money
                    rev = min(delta_cash, units * approx_price * 1.5)
                    rev_by_product[prod] += max(0.0, rev)
                    units_sold[prod] += units

        last_money = curr_money
        last_shed = dict(curr_shed)

        # Call agent
        action = agent_module.agent(obs, configuration)

        # Track labor and orders
        if isinstance(action, dict):
            all_units = [action.get("farmer", [])] + action.get("hands", [])
            for u in all_units:
                if not u:
                    labor_actions["idle_other"] += 1
                    continue
                act_type = u[0]
                if act_type == "WATER":
                    labor_actions["crop_water"] += 1
                elif act_type == "HARVEST":
                    labor_actions["crop_harvest"] += 1
                elif act_type == "PLANT":
                    labor_actions["crop_plant"] += 1
                elif act_type == "TILL":
                    labor_actions["crop_till"] += 1
                elif act_type == "FEED":
                    labor_actions["animal_feed"] += 1
                elif act_type in ("MILK", "SHEAR", "COLLECT"):
                    labor_actions["animal_collect"] += 1
                elif act_type == "BUILD":
                    labor_actions["build_structure"] += 1
                elif act_type == "MOVE":
                    labor_actions["movement"] += 1
                else:
                    labor_actions["idle_other"] += 1

            # Check market BUY_ANIMAL orders
            orders = action.get("market", []) or action.get("orders", [])
            for order in orders:
                if isinstance(order, (list, tuple)) and len(order) >= 3 and order[0] == "BUY_ANIMAL":
                    spec = order[1]
                    qty = int(order[2])
                    if qty > 0:
                        animal_purchases.append({
                            "day": day,
                            "hour": hour,
                            "species": spec,
                            "qty": qty,
                            "cash": curr_money,
                        })
                        if spec == "COW":
                            cows_bought += qty
                            for _ in range(qty):
                                cow_buy_days.append(day)
                        elif spec == "SHEEP":
                            sheep_bought += qty
                            for _ in range(qty):
                                sheep_buy_days.append(day)
                        elif spec == "GOOSE":
                            geese_bought += qty
                            for _ in range(qty):
                                goose_buy_days.append(day)

                        # Day 12-14 selective purchase invariant check: physically built empty unreserved pasture
                        if day >= 12:
                            empty_p = built_pastures - (cows_on_tiles + sheep_on_tiles)
                            if spec in ("COW", "SHEEP") and empty_p < qty:
                                late_purchase_invariant_violations += 1

        return action

    # Run match
    env = make("kaggriculture", configuration={"episodeSteps": 720, "runTimeout": 999999}, info={"seed": seed})
    agents = [tracking_agent, opp_name]
    env.run(agents)

    p0_reward = float(env.state[0].reward or 0.0)
    p1_reward = float(env.state[1].reward or 0.0)

    # Economic attribution calculations
    livestock_rev = rev_by_product["MILK"] + rev_by_product["WOOL"] + rev_by_product["EGG"]
    fert_rev = rev_by_product["FERTILIZER"]
    crop_rev = sum(rev_by_product[c] for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"))

    animal_spend = (cows_bought * 400.0) + (sheep_bought * 500.0) + (geese_bought * 300.0)
    feed_spend = labor_actions["animal_feed"] * 25.0
    final_built_pastures = daily_built_pastures[-1] if daily_built_pastures else 0
    housing_cost = final_built_pastures * 100.0
    net_livestock_contrib = (livestock_rev + fert_rev) - (animal_spend + feed_spend + housing_cost)

    # Housing utilization calculations
    pasture_utilization = (occupied_pasture_hours / total_built_pasture_hours) if total_built_pasture_hours > 0 else 1.0
    coop_utilization = (occupied_coop_hours / total_built_coop_hours) if total_built_coop_hours > 0 else 1.0
    tot_built_hours = total_built_pasture_hours + total_built_coop_hours
    tot_occ_hours = occupied_pasture_hours + occupied_coop_hours
    total_housing_utilization = (tot_occ_hours / tot_built_hours) if tot_built_hours > 0 else 1.0

    avg_unused_p = float(np.mean(daily_unused_pastures)) if daily_unused_pastures else 0.0
    final_herd = peak_cows + peak_sheep
    stranded_pastures = max(0, final_built_pastures - final_herd)

    # Labor calculations
    tot_labor = sum(labor_actions.values())
    livestock_labor = labor_actions["animal_feed"] + labor_actions["animal_collect"] + labor_actions["build_structure"]
    livestock_labor_share = (livestock_labor / tot_labor) if tot_labor > 0 else 0.0
    crop_labor = labor_actions["crop_water"] + labor_actions["crop_harvest"] + labor_actions["crop_plant"] + labor_actions["crop_till"]

    # Shop counts and timing
    yarn_store_count = last_town_shops.count("YARN_STORE")
    milk_shop_count = sum(last_town_shops.count(s) for s in ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP"))
    egg_shop_count = sum(last_town_shops.count(s) for s in ("BAKERY", "BRUNCH_SPOT"))

    first_yarn_day = None
    for ev in shop_unlock_events:
        if ev["shop"] == "YARN_STORE":
            first_yarn_day = ev["day"]
            break

    if yarn_store_count == 0:
        yarn_timing_stratum = "None"
    elif first_yarn_day is not None and first_yarn_day <= 9:
        yarn_timing_stratum = "Early"
    else:
        yarn_timing_stratum = "Late"

    return {
        "arm": arm,
        "seed": seed,
        "opponent": opp_name,
        "final_score": p0_reward,
        "opponent_score": p1_reward,
        "peak_cows": peak_cows,
        "peak_sheep": peak_sheep,
        "peak_geese": peak_geese,
        "peak_herd": peak_herd,
        "cows_bought": cows_bought,
        "sheep_bought": sheep_bought,
        "geese_bought": geese_bought,
        "cow_buy_days": cow_buy_days,
        "sheep_buy_days": sheep_buy_days,
        "goose_buy_days": goose_buy_days,
        "first_cow_day": min(cow_buy_days) if cow_buy_days else None,
        "first_sheep_day": min(sheep_buy_days) if sheep_buy_days else None,
        "mean_cow_day": float(np.mean(cow_buy_days)) if cow_buy_days else None,
        "mean_sheep_day": float(np.mean(sheep_buy_days)) if sheep_buy_days else None,
        "last_cow_day": max(cow_buy_days) if cow_buy_days else None,
        "last_sheep_day": max(sheep_buy_days) if sheep_buy_days else None,
        "unfed_animal_days": unfed_animal_days,
        "max_consecutive_unfed": max_consecutive_unfed,
        "consecutive_unfed_ge2_count": consecutive_unfed_ge2_count,
        "animal_escapes": animal_escapes,
        "housing_capacity_violations": housing_capacity_violations,
        "late_purchase_invariant_violations": late_purchase_invariant_violations,
        "housing_utilization": {
            "pasture_utilization": round(pasture_utilization, 4),
            "coop_utilization": round(coop_utilization, 4),
            "total_housing_utilization": round(total_housing_utilization, 4),
            "avg_unused_pastures": round(avg_unused_p, 2),
            "peak_unused_pastures": peak_unused_pastures,
            "final_built_pastures": final_built_pastures,
            "stranded_pastures": stranded_pastures,
        },
        "labor_telemetry": {
            "total_actions": tot_labor,
            "crop_actions": crop_labor,
            "animal_feed_actions": labor_actions["animal_feed"],
            "animal_collect_actions": labor_actions["animal_collect"],
            "build_actions": labor_actions["build_structure"],
            "movement_actions": labor_actions["movement"],
            "livestock_labor_share": round(livestock_labor_share, 4),
        },
        "economics": {
            "milk_rev": round(rev_by_product["MILK"], 2),
            "milk_units": units_sold["MILK"],
            "wool_rev": round(rev_by_product["WOOL"], 2),
            "wool_units": units_sold["WOOL"],
            "egg_rev": round(rev_by_product["EGG"], 2),
            "egg_units": units_sold["EGG"],
            "fert_rev": round(fert_rev, 2),
            "crop_rev": round(crop_rev, 2),
            "animal_spend": animal_spend,
            "feed_spend": feed_spend,
            "housing_cost": housing_cost,
            "net_livestock_contrib": round(net_livestock_contrib, 2),
        },
        "shop_state": {
            "unlocked_shops": last_town_shops,
            "yarn_stores": yarn_store_count,
            "milk_shops": milk_shop_count,
            "egg_shops": egg_shop_count,
            "first_yarn_day": first_yarn_day,
            "yarn_timing": yarn_timing_stratum,
        },
    }


def run_tournament(num_seeds: int = 300, start_seed: int = 100, workers: int = 6, output_path: Optional[str] = None):
    print("=" * 80)
    print(f"=== DEFINITIVE PAIRED TOURNAMENT: PROMOTED ARM B VS CORRECTED DYNAMIC ARM C ===")
    print(f"=== {num_seeds} Paired Seeds (Seeds {start_seed}..{start_seed + num_seeds - 1}) | 600 Total Matches | {workers} Workers ===")
    print("=" * 80, flush=True)

    seeds = list(range(start_seed, start_seed + num_seeds))
    payloads = []
    for s in seeds:
        payloads.append({"arm": "ArmB", "seed": s, "opponent": "starter"})
        payloads.append({"arm": "ArmC", "seed": s, "opponent": "starter"})

    total_matches = len(payloads)
    out_file = output_path or os.path.join(_REPO_ROOT, "simulations", "experiments", "results", "bc_definitive_tournament_300seeds.json")
    checkpoint_file = out_file.replace(".json", "_checkpoint.json")

    results_by_arm_seed: Dict[Tuple[str, int], Dict[str, Any]] = {}
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r") as f:
                saved = json.load(f)
                for item in saved:
                    results_by_arm_seed[(item["arm"], item["seed"])] = item
            print(f"Resumed from checkpoint: {len(results_by_arm_seed)}/{total_matches} matches already completed.", flush=True)
        except Exception as e:
            print(f"Warning: could not read checkpoint: {e}", flush=True)

    def save_checkpoint():
        tmp = checkpoint_file + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(list(results_by_arm_seed.values()), f)
            if os.path.exists(checkpoint_file):
                os.replace(tmp, checkpoint_file)
            else:
                os.rename(tmp, checkpoint_file)
        except Exception as e:
            print(f"Warning: failed to save checkpoint: {e}", flush=True)

    uncompleted_payloads = [p for p in payloads if (p["arm"], p["seed"]) not in results_by_arm_seed]
    completed_matches = len(results_by_arm_seed)
    print(f"Matches to run: {len(uncompleted_payloads)} (Already done: {completed_matches})", flush=True)

    start_time = time.time()

    if uncompleted_payloads:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_run_single_match, p): p for p in uncompleted_payloads}
            for f in as_completed(future_map):
                completed_matches += 1
                res = f.result()
                results_by_arm_seed[(res["arm"], res["seed"])] = res

                if completed_matches % 10 == 0 or completed_matches == total_matches:
                    save_checkpoint()
                    elapsed = time.time() - start_time
                    pct = (completed_matches / total_matches) * 100.0
                    matches_run = completed_matches - (len(payloads) - len(uncompleted_payloads))
                    rate = matches_run / elapsed if elapsed > 0 else 0
                    rem = total_matches - completed_matches
                    eta = (rem / rate) if rate > 0 else 0
                    print(f"  Completed {completed_matches}/{total_matches} matches ({pct:.1f}%) in {elapsed:.1f}s (ETA: {eta:.1f}s)", flush=True)

    total_runtime = time.time() - start_time
    print(f"\nCompleted all {total_matches} matches in {total_runtime:.1f}s.", flush=True)

    # Comprehensive Analysis
    arm_b_results = [results_by_arm_seed[("ArmB", s)] for s in seeds]
    arm_c_results = [results_by_arm_seed[("ArmC", s)] for s in seeds]

    # Paired deltas (C minus B)
    deltas = [arm_c_results[i]["final_score"] - arm_b_results[i]["final_score"] for i in range(len(seeds))]
    deltas_arr = np.array(deltas)

    mean_delta = float(np.mean(deltas_arr))
    median_delta = float(np.median(deltas_arr))
    std_delta = float(np.std(deltas_arr, ddof=1))
    p10_delta = float(np.percentile(deltas_arr, 10))
    p90_delta = float(np.percentile(deltas_arr, 90))

    # Worst 10% CVaR
    worst_10pct_threshold = np.percentile(deltas_arr, 10)
    cvar_10 = float(np.mean(deltas_arr[deltas_arr <= worst_10pct_threshold]))

    # 10k Bootstrap CI
    rng = np.random.default_rng(12345)
    boot_indices = rng.integers(0, len(deltas_arr), size=(10000, len(deltas_arr)))
    boot_means = np.mean(deltas_arr[boot_indices], axis=1)
    ci_lower = float(np.percentile(boot_means, 2.5))
    ci_upper = float(np.percentile(boot_means, 97.5))

    # Significance tests
    t_stat, p_val_ttest = stats.ttest_1samp(deltas_arr, 0.0)
    w_stat, p_val_wilcoxon = stats.wilcoxon(deltas_arr, alternative="two-sided")

    # Win / Tie / Loss
    wins = int(np.sum(deltas_arr > 0))
    ties = int(np.sum(deltas_arr == 0))
    losses = int(np.sum(deltas_arr < 0))
    win_rate = wins / len(seeds)

    # Attribution decomposition: C - B
    # Livestock net contribution delta
    c_net_ls = [r["economics"]["net_livestock_contrib"] for r in arm_c_results]
    b_net_ls = [r["economics"]["net_livestock_contrib"] for r in arm_b_results]
    delta_net_ls = float(np.mean(c_net_ls) - np.mean(b_net_ls))

    c_crop_rev = [r["economics"]["crop_rev"] for r in arm_c_results]
    b_crop_rev = [r["economics"]["crop_rev"] for r in arm_b_results]
    delta_crop_rev = float(np.mean(c_crop_rev) - np.mean(b_crop_rev))

    delta_livestock_rev = float(np.mean([r["economics"]["milk_rev"] + r["economics"]["wool_rev"] + r["economics"]["egg_rev"] for r in arm_c_results]) -
                               np.mean([r["economics"]["milk_rev"] + r["economics"]["wool_rev"] + r["economics"]["egg_rev"] for r in arm_b_results]))
    delta_fert_rev = float(np.mean([r["economics"]["fert_rev"] for r in arm_c_results]) - np.mean([r["economics"]["fert_rev"] for r in arm_b_results]))
    delta_feed_spend = float(np.mean([r["economics"]["feed_spend"] for r in arm_c_results]) - np.mean([r["economics"]["feed_spend"] for r in arm_b_results]))
    delta_animal_spend = float(np.mean([r["economics"]["animal_spend"] for r in arm_c_results]) - np.mean([r["economics"]["animal_spend"] for r in arm_b_results]))
    delta_housing_cost = float(np.mean([r["economics"]["housing_cost"] for r in arm_c_results]) - np.mean([r["economics"]["housing_cost"] for r in arm_b_results]))

    residual = mean_delta - (delta_net_ls + delta_crop_rev)

    # Housing utilization summaries
    b_pasture_util = float(np.mean([r["housing_utilization"]["pasture_utilization"] for r in arm_b_results]))
    c_pasture_util = float(np.mean([r["housing_utilization"]["pasture_utilization"] for r in arm_c_results]))
    b_avg_unused_p = float(np.mean([r["housing_utilization"]["avg_unused_pastures"] for r in arm_b_results]))
    c_avg_unused_p = float(np.mean([r["housing_utilization"]["avg_unused_pastures"] for r in arm_c_results]))
    b_peak_unused_p = float(np.mean([r["housing_utilization"]["peak_unused_pastures"] for r in arm_b_results]))
    c_peak_unused_p = float(np.mean([r["housing_utilization"]["peak_unused_pastures"] for r in arm_c_results]))
    b_stranded_p = float(np.mean([r["housing_utilization"]["stranded_pastures"] for r in arm_b_results]))
    c_stranded_p = float(np.mean([r["housing_utilization"]["stranded_pastures"] for r in arm_c_results]))

    # Labor telemetry summaries
    b_ls_labor_share = float(np.mean([r["labor_telemetry"]["livestock_labor_share"] for r in arm_b_results]))
    c_ls_labor_share = float(np.mean([r["labor_telemetry"]["livestock_labor_share"] for r in arm_c_results]))
    b_crop_actions = float(np.mean([r["labor_telemetry"]["crop_actions"] for r in arm_b_results]))
    c_crop_actions = float(np.mean([r["labor_telemetry"]["crop_actions"] for r in arm_c_results]))

    # Stratifications
    strat_yarn = {"0_yarn": [], "1_yarn": [], "2plus_yarn": []}
    strat_timing = {"Early_Yarn": [], "Late_Yarn": [], "No_Yarn": []}
    strat_milk = {"0_to_1_milk_shops": [], "2plus_milk_shops": []}
    strat_egg = {"0_egg_shops": [], "1plus_egg_shops": []}

    for i, s in enumerate(seeds):
        res_b = arm_b_results[i]
        res_c = arm_c_results[i]
        d = deltas[i]
        sh = res_b["shop_state"]

        yc = sh["yarn_stores"]
        if yc == 0:
            strat_yarn["0_yarn"].append(d)
        elif yc == 1:
            strat_yarn["1_yarn"].append(d)
        else:
            strat_yarn["2plus_yarn"].append(d)

        yt = sh["yarn_timing"]
        if yt == "Early":
            strat_timing["Early_Yarn"].append(d)
        elif yt == "Late":
            strat_timing["Late_Yarn"].append(d)
        else:
            strat_timing["No_Yarn"].append(d)

        mc = sh["milk_shops"]
        if mc <= 1:
            strat_milk["0_to_1_milk_shops"].append(d)
        else:
            strat_milk["2plus_milk_shops"].append(d)

        ec = sh["egg_shops"]
        if ec == 0:
            strat_egg["0_egg_shops"].append(d)
        else:
            strat_egg["1plus_egg_shops"].append(d)

    def _summarize_strat(name, vals):
        if not vals:
            return {"count": 0, "mean_delta": 0.0, "win_rate": 0.0}
        arr = np.array(vals)
        return {
            "count": len(vals),
            "mean_delta": round(float(np.mean(arr)), 2),
            "median_delta": round(float(np.median(arr)), 2),
            "win_rate": round(float(np.sum(arr > 0) / len(arr)), 4),
        }

    strat_summary = {
        "yarn_count": {k: _summarize_strat(k, v) for k, v in strat_yarn.items()},
        "yarn_timing": {k: _summarize_strat(k, v) for k, v in strat_timing.items()},
        "milk_shops": {k: _summarize_strat(k, v) for k, v in strat_milk.items()},
        "egg_shops": {k: _summarize_strat(k, v) for k, v in strat_egg.items()},
    }

    # Best 10 and Worst 10 Seeds
    seed_delta_records = []
    for i, s in enumerate(seeds):
        seed_delta_records.append({
            "seed": s,
            "delta": deltas[i],
            "c_score": arm_c_results[i]["final_score"],
            "b_score": arm_b_results[i]["final_score"],
            "c_cows": arm_c_results[i]["cows_bought"],
            "c_sheep": arm_c_results[i]["sheep_bought"],
            "b_cows": arm_b_results[i]["cows_bought"],
            "b_sheep": arm_b_results[i]["sheep_bought"],
            "yarn_stores": arm_b_results[i]["shop_state"]["yarn_stores"],
            "milk_shops": arm_b_results[i]["shop_state"]["milk_shops"],
            "yarn_timing": arm_b_results[i]["shop_state"]["yarn_timing"],
            "c_unused_p": arm_c_results[i]["housing_utilization"]["avg_unused_pastures"],
            "b_unused_p": arm_b_results[i]["housing_utilization"]["avg_unused_pastures"],
        })

    seed_delta_records.sort(key=lambda x: x["delta"])
    worst_10_seeds = seed_delta_records[:10]
    best_10_seeds = seed_delta_records[-10:][::-1]

    # Promotion Decision Logic
    promote_c = False
    decision = "KEEP ARM B"
    rationale = ""

    if (mean_delta > 0 and
        ci_lower > 0 and
        median_delta >= -500.0 and
        p_val_ttest < 0.05 and
        c_pasture_util >= 0.70 and
        sum(r["late_purchase_invariant_violations"] for r in arm_c_results) == 0 and
        sum(r["animal_escapes"] for r in arm_c_results) == 0):
        decision = "PROMOTE CORRECTED ARM C"
        rationale = f"Corrected Arm C decisively outperforms Arm B by +${mean_delta:.2f} (95% CI [{ci_lower:.2f}, {ci_upper:.2f}], p={p_val_ttest:.4f}). Housing utilization is healthy ({c_pasture_util*100:.1f}%) and all safety invariants passed with zero violations."
    elif mean_delta > 0 and ci_lower <= 0 and p_val_ttest >= 0.05:
        decision = "INCONCLUSIVE — RUN ADDITIONAL CONFIRMATION"
        rationale = f"Mean delta is positive (+${mean_delta:.2f}) but 95% CI [{ci_lower:.2f}, {ci_upper:.2f}] includes zero and p={p_val_ttest:.4f} is not statistically significant."
    else:
        decision = "KEEP ARM B"
        rationale = f"Arm B maintains superiority or equivalence (Delta: {mean_delta:.2f}, p={p_val_ttest:.4f}). Arm C does not provide statistically significant whole-game improvements."

    summary = {
        "metadata": {
            "num_seeds": num_seeds,
            "start_seed": start_seed,
            "total_matches": total_matches,
            "runtime_seconds": round(total_runtime, 2),
            "workers": workers,
            "arms": ["ArmB", "ArmC"],
        },
        "contrast_c_minus_b": {
            "mean_delta": round(mean_delta, 2),
            "median_delta": round(median_delta, 2),
            "std_delta": round(std_delta, 2),
            "bootstrap_95_ci": [round(ci_lower, 2), round(ci_upper, 2)],
            "t_statistic": round(float(t_stat), 3),
            "p_value_ttest": float(p_val_ttest),
            "w_statistic": round(float(w_stat), 1),
            "p_value_wilcoxon": float(p_val_wilcoxon),
            "win_rate": round(win_rate, 4),
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "p10_delta": round(p10_delta, 2),
            "p90_delta": round(p90_delta, 2),
            "cvar_10": round(cvar_10, 2),
        },
        "economic_decomposition": {
            "total_mean_delta": round(mean_delta, 2),
            "delta_net_livestock_contrib": round(delta_net_ls, 2),
            "delta_livestock_rev": round(delta_livestock_rev, 2),
            "delta_fert_rev": round(delta_fert_rev, 2),
            "delta_feed_spend": round(delta_feed_spend, 2),
            "delta_animal_spend": round(delta_animal_spend, 2),
            "delta_housing_cost": round(delta_housing_cost, 2),
            "delta_crop_rev": round(delta_crop_rev, 2),
            "residual_other_effects": round(residual, 2),
            "formula": "C - B = delta_net_livestock_contrib + delta_crop_rev + residual",
        },
        "housing_efficiency": {
            "b_pasture_utilization": round(b_pasture_util, 4),
            "c_pasture_utilization": round(c_pasture_util, 4),
            "b_avg_unused_pastures": round(b_avg_unused_p, 2),
            "c_avg_unused_pastures": round(c_avg_unused_p, 2),
            "b_peak_unused_pastures": round(b_peak_unused_p, 2),
            "c_peak_unused_pastures": round(c_peak_unused_p, 2),
            "b_stranded_pastures": round(b_stranded_p, 2),
            "c_stranded_pastures": round(c_stranded_p, 2),
        },
        "labor_telemetry": {
            "b_livestock_labor_share": round(b_ls_labor_share, 4),
            "c_livestock_labor_share": round(c_ls_labor_share, 4),
            "b_crop_actions": round(b_crop_actions, 1),
            "c_crop_actions": round(c_crop_actions, 1),
        },
        "safety": {
            "b_violations": sum(r["late_purchase_invariant_violations"] for r in arm_b_results),
            "c_violations": sum(r["late_purchase_invariant_violations"] for r in arm_c_results),
            "b_escapes": sum(r["animal_escapes"] for r in arm_b_results),
            "c_escapes": sum(r["animal_escapes"] for r in arm_c_results),
            "b_mean_unfed_days": round(float(np.mean([r["unfed_animal_days"] for r in arm_b_results])), 2),
            "c_mean_unfed_days": round(float(np.mean([r["unfed_animal_days"] for r in arm_c_results])), 2),
        },
        "stratifications": strat_summary,
        "worst_10_seeds": worst_10_seeds,
        "best_10_seeds": best_10_seeds,
        "arm_b_summary": {
            "mean_score": round(float(np.mean([r["final_score"] for r in arm_b_results])), 2),
            "median_score": round(float(np.median([r["final_score"] for r in arm_b_results])), 2),
            "std_score": round(float(np.std([r["final_score"] for r in arm_b_results])), 2),
            "mean_cows": round(float(np.mean([r["cows_bought"] for r in arm_b_results])), 2),
            "mean_sheep": round(float(np.mean([r["sheep_bought"] for r in arm_b_results])), 2),
            "mean_milk_rev": round(float(np.mean([r["economics"]["milk_rev"] for r in arm_b_results])), 2),
            "mean_wool_rev": round(float(np.mean([r["economics"]["wool_rev"] for r in arm_b_results])), 2),
            "mean_crop_rev": round(float(np.mean([r["economics"]["crop_rev"] for r in arm_b_results])), 2),
        },
        "arm_c_summary": {
            "mean_score": round(float(np.mean([r["final_score"] for r in arm_c_results])), 2),
            "median_score": round(float(np.median([r["final_score"] for r in arm_c_results])), 2),
            "std_score": round(float(np.std([r["final_score"] for r in arm_c_results])), 2),
            "mean_cows": round(float(np.mean([r["cows_bought"] for r in arm_c_results])), 2),
            "mean_sheep": round(float(np.mean([r["sheep_bought"] for r in arm_c_results])), 2),
            "mean_milk_rev": round(float(np.mean([r["economics"]["milk_rev"] for r in arm_c_results])), 2),
            "mean_wool_rev": round(float(np.mean([r["economics"]["wool_rev"] for r in arm_c_results])), 2),
            "mean_crop_rev": round(float(np.mean([r["economics"]["crop_rev"] for r in arm_c_results])), 2),
        },
        "decision": decision,
        "rationale": rationale,
    }

    out_file = output_path or os.path.join(_REPO_ROOT, "simulations", "experiments", "results", "bc_definitive_tournament_300seeds.json")
    with open(out_file, "w") as f:
        json.dump({"summary": summary, "raw_b": arm_b_results, "raw_c": arm_c_results}, f, indent=2)

    print("\n" + "=" * 80)
    print(f"=== TOURNAMENT COMPLETED IN {total_runtime:.1f}s ===")
    print(f"Mean Score: Arm B = ${summary['arm_b_summary']['mean_score']:.2f} | Arm C = ${summary['arm_c_summary']['mean_score']:.2f}")
    print(f"Mean Delta (C - B): ${mean_delta:.2f} (95% CI [{ci_lower:.2f}, {ci_upper:.2f}])")
    print(f"Paired t-test: t={t_stat:.3f}, p={p_val_ttest:.5f} | Wilcoxon: W={w_stat:.1f}, p={p_val_wilcoxon:.5f}")
    print(f"Win/Tie/Loss: {wins} Wins / {ties} Ties / {losses} Losses ({win_rate*100:.1f}% Win Rate)")
    print(f"Housing Utilization: Arm B = {b_pasture_util*100:.1f}% | Arm C = {c_pasture_util*100:.1f}%")
    print(f"Stranded Pastures: Arm B = {b_stranded_p:.2f} | Arm C = {c_stranded_p:.2f}")
    print(f"Safety Violations: Arm B = {summary['safety']['b_violations']} | Arm C = {summary['safety']['c_violations']}")
    print(f"Escapes: Arm B = {summary['safety']['b_escapes']} | Arm C = {summary['safety']['c_escapes']}")
    print(f"\nDECISION: {decision}")
    print(f"Rationale: {rationale}")
    print("=" * 80)
    print(f"Full results saved to {out_file}", flush=True)

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Definitive Arm B vs Corrected Arm C Tournament")
    parser.add_argument("--num-seeds", type=int, default=300, help="Number of paired seeds (default: 300)")
    parser.add_argument("--start-seed", type=int, default=100, help="Starting seed number (default: 100)")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent worker processes (default: 6)")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()

    run_tournament(num_seeds=args.num_seeds, start_seed=args.start_seed, workers=args.workers, output_path=args.output)
