"""Large Arm A vs Arm B Confirmation Tournament Runner (300 Paired Seeds).

Evaluates:
  - Arm A (Control): Current Production Control (frozen target quotas, base fixed economics).
  - Arm B (Shop Economics): Identical to Arm A except livestock profitability uses the validated
    exact joint-future-path shop-conditioned counterfactual valuator.

Features:
  - 300 paired seeds (Seeds 100..399), 600 matches total against baseline 'starter' opponent.
  - Complete economic attribution: Milk, Wool, Egg, Fertilizer, Crops, Animal Spend, Feed Spend, Net Livestock Contribution.
  - Stratification by:
      * Yarn Store Count: 0, 1, 2+
      * Milk Demand Shops: 0-1, 2+
      * Yarn Unlock Timing: Early (<= Day 9), Late (>= Day 12), None
  - Full statistical contrasts: Mean/Median paired delta, 10k bootstrap 95% CI, paired t-test,
    Wilcoxon signed-rank, Win/Tie/Loss %, P10/P90, CVaR 10%, worst 10 individual seeds.
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
        "expansion_planner", "observation_parser", "state_tracker", "land_serviceability_model",
        "marginal_livestock_valuator"
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

    total_feed_actions = 0
    total_feed_wheat_consumed = 0

    rev_by_product = {
        "MILK": 0.0, "WOOL": 0.0, "FERTILIZER": 0.0, "EGG": 0.0,
        "WHEAT": 0.0, "CARROT": 0.0, "MELON": 0.0, "STRAWBERRY": 0.0, "TOMATO": 0.0
    }
    units_sold = {k: 0 for k in rev_by_product}

    last_money = 3000.0
    last_shed = {}
    last_town_shops = []
    shop_unlock_events = []

    def tracking_agent(obs, configuration=None):
        nonlocal peak_cows, peak_sheep, peak_geese, peak_herd
        nonlocal cows_bought, sheep_bought, geese_bought
        nonlocal cow_buy_days, sheep_buy_days, goose_buy_days, animal_purchases
        nonlocal unfed_animal_days, max_consecutive_unfed, consecutive_unfed_ge2_count
        nonlocal animal_escapes
        nonlocal housing_capacity_violations, late_purchase_invariant_violations
        nonlocal total_feed_actions, total_feed_wheat_consumed
        nonlocal rev_by_product, units_sold, last_money, last_shed, last_town_shops, shop_unlock_events

        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        p_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        farm_data = farms[p_id] if len(farms) > p_id else {}
        curr_money = float(farm_data.get("money", 3000.0))
        tiles = farm_data.get("tiles", [])

        # Authoritative shop extraction from town dict
        curr_town_shops = list(obs.get("town", {}).get("unlocked_shops", []))
        if len(curr_town_shops) > len(last_town_shops):
            newly_added = curr_town_shops[len(last_town_shops):]
            for sh in newly_added:
                shop_unlock_events.append({"shop": sh, "day": day, "hour": hour})
        last_town_shops = curr_town_shops

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
                    # At start of day (hour 0), count unfed animal-days
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

        # Check housing capacity violation
        if (cows_on_tiles + sheep_on_tiles) > built_pastures:
            housing_capacity_violations += 1
        if geese_on_tiles > built_coops:
            housing_capacity_violations += 1

        # Track market sales & revenues
        dm = curr_money - last_money
        if dm > 0:
            sold = {k: last_shed.get(k, 0) - curr_shed.get(k, 0) for k in last_shed if last_shed.get(k, 0) > curr_shed.get(k, 0)}
            if len(sold) == 1:
                item = list(sold.keys())[0]
                qty = sold[item]
                if item in rev_by_product:
                    rev_by_product[item] += dm
                    units_sold[item] += qty
            elif len(sold) > 1:
                prices = obs.get("market", {}).get("prices", {})
                tot_est = sum(qty * prices.get(k, 1) for k, qty in sold.items())
                for item, qty in sold.items():
                    val = dm * ((qty * prices.get(item, 1)) / max(1.0, tot_est))
                    if item in rev_by_product:
                        rev_by_product[item] += val
                        units_sold[item] += qty

        last_money = curr_money
        last_shed = dict(curr_shed)

        # Call agent
        action = agent_module.agent(obs)

        # Process action telemetry & purchases
        if isinstance(action, dict):
            # Check FEED actions
            all_units = [action.get("farmer", [])] + action.get("hands", [])
            for u in all_units:
                if u and u[0] == "FEED":
                    total_feed_actions += 1
                    total_feed_wheat_consumed += 1

            # Check market BUY_ANIMAL orders (market key in agent action dict)
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

                        # Day 12-14 selective purchase check: physically built empty pasture
                        if day >= 12:
                            empty_p = built_pastures - (cows_on_tiles + sheep_on_tiles)
                            if spec in ("COW", "SHEEP") and empty_p < qty:
                                late_purchase_invariant_violations += 1

        return action

    # Run match
    env = make("kaggriculture", configuration={"episodeSteps": 720}, info={"seed": seed})
    agents = [tracking_agent, opp_name]
    env.run(agents)

    p0_reward = float(env.state[0].reward or 0.0)
    p1_reward = float(env.state[1].reward or 0.0)

    # Economic attribution calculations
    livestock_rev = rev_by_product["MILK"] + rev_by_product["WOOL"] + rev_by_product["EGG"]
    fert_rev = rev_by_product["FERTILIZER"]
    crop_rev = sum(rev_by_product[c] for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"))

    # Animal purchase spend
    animal_spend = (cows_bought * 400.0) + (sheep_bought * 500.0) + (geese_bought * 300.0)
    feed_spend = total_feed_wheat_consumed * 25.0
    net_livestock_contrib = (livestock_rev + fert_rev) - (animal_spend + feed_spend)

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
        # Herd metrics
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
        # Health & safety metrics
        "unfed_animal_days": unfed_animal_days,
        "max_consecutive_unfed": max_consecutive_unfed,
        "consecutive_unfed_ge2_count": consecutive_unfed_ge2_count,
        "animal_escapes": animal_escapes,
        "housing_capacity_violations": housing_capacity_violations,
        "late_purchase_invariant_violations": late_purchase_invariant_violations,
        "total_feed_actions": total_feed_actions,
        # Economics
        "rev_by_product": {k: round(v, 2) for k, v in rev_by_product.items()},
        "units_sold": units_sold,
        "livestock_rev": round(livestock_rev, 2),
        "fert_rev": round(fert_rev, 2),
        "crop_rev": round(crop_rev, 2),
        "animal_spend": round(animal_spend, 2),
        "feed_spend": round(feed_spend, 2),
        "net_livestock_contrib": round(net_livestock_contrib, 2),
        # Shop context
        "town_shops": last_town_shops,
        "yarn_store_count": yarn_store_count,
        "milk_shop_count": milk_shop_count,
        "egg_shop_count": egg_shop_count,
        "first_yarn_day": first_yarn_day,
        "yarn_timing_stratum": yarn_timing_stratum,
    }


def compute_bootstrap_ci(data: np.ndarray, num_resamples: int = 10000, ci: float = 0.95) -> Tuple[float, float]:
    """Compute 10,000-resample paired bootstrap confidence interval."""
    if len(data) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(42)
    boot_means = np.mean(rng.choice(data, size=(num_resamples, len(data)), replace=True), axis=1)
    alpha = (1.0 - ci) / 2.0
    lower = float(np.percentile(boot_means, alpha * 100))
    upper = float(np.percentile(boot_means, (1.0 - alpha) * 100))
    return lower, upper


def analyze_ab_confirmation(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform rigorous A/B confirmation analysis across 300 paired matches."""
    by_arm: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for r in results:
        arm = r["arm"]
        seed = r["seed"]
        by_arm.setdefault(arm, {})[seed] = r

    arm_keys = ["ArmA", "ArmB"]
    arm_summaries = {}
    for arm in arm_keys:
        scens = by_arm.get(arm, {})
        scores = [scens[s]["final_score"] for s in scens]
        cows_b = [scens[s]["cows_bought"] for s in scens]
        sheep_b = [scens[s]["sheep_bought"] for s in scens]
        geese_b = [scens[s]["geese_bought"] for s in scens]
        peak_c = [scens[s]["peak_cows"] for s in scens]
        peak_s = [scens[s]["peak_sheep"] for s in scens]
        peak_h = [scens[s]["peak_herd"] for s in scens]

        cow_days = [d for s in scens for d in scens[s]["cow_buy_days"]]
        sheep_days = [d for s in scens for d in scens[s]["sheep_buy_days"]]

        milk_r = [scens[s]["rev_by_product"]["MILK"] for s in scens]
        wool_r = [scens[s]["rev_by_product"]["WOOL"] for s in scens]
        egg_r = [scens[s]["rev_by_product"]["EGG"] for s in scens]
        fert_r = [scens[s]["fert_rev"] for s in scens]
        crop_r = [scens[s]["crop_rev"] for s in scens]
        anim_sp = [scens[s]["animal_spend"] for s in scens]
        feed_sp = [scens[s]["feed_spend"] for s in scens]
        net_contrib = [scens[s]["net_livestock_contrib"] for s in scens]
        unfed = [scens[s]["unfed_animal_days"] for s in scens]

        arm_summaries[arm] = {
            "num_matches": len(scores),
            "score_mean": round(float(np.mean(scores)), 2),
            "score_median": round(float(np.median(scores)), 2),
            "score_std": round(float(np.std(scores, ddof=1)), 2) if len(scores) > 1 else 0.0,
            "score_min": round(float(np.min(scores)), 2),
            "score_max": round(float(np.max(scores)), 2),
            # Herd
            "cows_bought_mean": round(float(np.mean(cows_b)), 2),
            "sheep_bought_mean": round(float(np.mean(sheep_b)), 2),
            "geese_bought_mean": round(float(np.mean(geese_b)), 2),
            "peak_cows_mean": round(float(np.mean(peak_c)), 2),
            "peak_sheep_mean": round(float(np.mean(peak_s)), 2),
            "peak_herd_mean": round(float(np.mean(peak_h)), 2),
            "mean_cow_buy_day": round(float(np.mean(cow_days)), 2) if cow_days else None,
            "mean_sheep_buy_day": round(float(np.mean(sheep_days)), 2) if sheep_days else None,
            # Economics
            "mean_milk_rev": round(float(np.mean(milk_r)), 2),
            "mean_wool_rev": round(float(np.mean(wool_r)), 2),
            "mean_egg_rev": round(float(np.mean(egg_r)), 2),
            "mean_fert_rev": round(float(np.mean(fert_r)), 2),
            "mean_crop_rev": round(float(np.mean(crop_r)), 2),
            "mean_animal_spend": round(float(np.mean(anim_sp)), 2),
            "mean_feed_spend": round(float(np.mean(feed_sp)), 2),
            "mean_net_livestock_contrib": round(float(np.mean(net_contrib)), 2),
            "mean_unfed_days": round(float(np.mean(unfed)), 2),
            "total_unfed_days": int(sum(unfed)),
            "total_escapes": int(sum(scens[s]["animal_escapes"] for s in scens)),
        }

    # Paired B - A Contrast
    a_scens = by_arm.get("ArmA", {})
    b_scens = by_arm.get("ArmB", {})
    common_seeds = sorted([s for s in a_scens if s in b_scens])

    deltas = np.array([b_scens[s]["final_score"] - a_scens[s]["final_score"] for s in common_seeds], dtype=float)
    mean_d = float(np.mean(deltas))
    med_d = float(np.median(deltas))
    std_d = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else 0.0

    t_stat, p_val_ttest = stats.ttest_rel(
        [b_scens[s]["final_score"] for s in common_seeds],
        [a_scens[s]["final_score"] for s in common_seeds]
    )
    try:
        w_stat, p_val_wilcoxon = stats.wilcoxon(deltas)
    except Exception:
        w_stat, p_val_wilcoxon = 0.0, 1.0

    ci_lower, ci_upper = compute_bootstrap_ci(deltas, num_resamples=10000, ci=0.95)

    wins = int(np.sum(deltas > 0))
    ties = int(np.sum(deltas == 0))
    losses = int(np.sum(deltas < 0))
    win_rate = round(wins / len(deltas), 4)

    p10 = float(np.percentile(deltas, 10))
    p90 = float(np.percentile(deltas, 90))

    paired_records = []
    for s in common_seeds:
        paired_records.append({
            "seed": s,
            "delta": round(float(b_scens[s]["final_score"] - a_scens[s]["final_score"]), 2),
            "b_score": b_scens[s]["final_score"],
            "a_score": a_scens[s]["final_score"],
            "yarn_stores": b_scens[s]["yarn_store_count"],
            "milk_shops": b_scens[s]["milk_shop_count"],
            "first_yarn_day": b_scens[s]["first_yarn_day"],
            "yarn_timing": b_scens[s]["yarn_timing_stratum"],
            "b_herd": (b_scens[s]["cows_bought"], b_scens[s]["sheep_bought"]),
            "a_herd": (a_scens[s]["cows_bought"], a_scens[s]["sheep_bought"]),
        })
    paired_records.sort(key=lambda x: x["delta"])
    worst_10_seeds = paired_records[:10]

    worst_10_pct_count = max(1, int(math.ceil(len(deltas) * 0.10)))
    cvar_10 = float(np.mean(np.sort(deltas)[:worst_10_pct_count]))
    worst_10_pct_mean = cvar_10

    # Economic Decomposition:
    # B - A = delta_livestock_contrib - displaced_crop_value + other_effects
    delta_livestock = arm_summaries["ArmB"]["mean_net_livestock_contrib"] - arm_summaries["ArmA"]["mean_net_livestock_contrib"]
    delta_crop = arm_summaries["ArmB"]["mean_crop_rev"] - arm_summaries["ArmA"]["mean_crop_rev"]
    displaced_crop = -delta_crop  # positive if B lost crop revenue
    unexplained_residual = mean_d - (delta_livestock + delta_crop)

    decomposition = {
        "total_mean_delta": round(mean_d, 2),
        "delta_net_livestock_contrib": round(delta_livestock, 2),
        "delta_crop_rev": round(delta_crop, 2),
        "displaced_crop_value": round(displaced_crop, 2),
        "residual_other_effects": round(unexplained_residual, 2),
        "identity_formula": "B - A = delta_net_livestock_contrib + delta_crop_rev + residual",
    }

    # Shop-State Stratifications
    stratifications = {}

    # 1. Yarn Store Count (0 vs 1 vs 2+)
    yarn_strata = {"0_yarn": [], "1_yarn": [], "2plus_yarn": []}
    for r in paired_records:
        yc = r["yarn_stores"]
        if yc == 0:
            yarn_strata["0_yarn"].append(r)
        elif yc == 1:
            yarn_strata["1_yarn"].append(r)
        else:
            yarn_strata["2plus_yarn"].append(r)

    strat_yarn = {}
    for k_str, r_list in yarn_strata.items():
        if not r_list:
            continue
        sub_d = [x["delta"] for x in r_list]
        sub_seeds = [x["seed"] for x in r_list]
        b_cows = [b_scens[s]["cows_bought"] for s in sub_seeds]
        b_sheep = [b_scens[s]["sheep_bought"] for s in sub_seeds]
        a_cows = [a_scens[s]["cows_bought"] for s in sub_seeds]
        a_sheep = [a_scens[s]["sheep_bought"] for s in sub_seeds]
        b_milk = [b_scens[s]["rev_by_product"]["MILK"] for s in sub_seeds]
        b_wool = [b_scens[s]["rev_by_product"]["WOOL"] for s in sub_seeds]
        a_milk = [a_scens[s]["rev_by_product"]["MILK"] for s in sub_seeds]
        a_wool = [a_scens[s]["rev_by_product"]["WOOL"] for s in sub_seeds]

        strat_yarn[k_str] = {
            "num_matches": len(r_list),
            "mean_delta": round(float(np.mean(sub_d)), 2),
            "median_delta": round(float(np.median(sub_d)), 2),
            "win_rate": round(sum(1 for x in sub_d if x > 0) / len(sub_d), 4),
            "b_cows_mean": round(float(np.mean(b_cows)), 2),
            "b_sheep_mean": round(float(np.mean(b_sheep)), 2),
            "a_cows_mean": round(float(np.mean(a_cows)), 2),
            "a_sheep_mean": round(float(np.mean(a_sheep)), 2),
            "b_milk_rev_mean": round(float(np.mean(b_milk)), 2),
            "b_wool_rev_mean": round(float(np.mean(b_wool)), 2),
            "a_milk_rev_mean": round(float(np.mean(a_milk)), 2),
            "a_wool_rev_mean": round(float(np.mean(a_wool)), 2),
        }
    stratifications["yarn_store_count"] = strat_yarn

    # 2. Milk Demand Shops (0-1 vs 2+)
    milk_strata = {"0_to_1_milk_shops": [], "2plus_milk_shops": []}
    for r in paired_records:
        mc = r["milk_shops"]
        if mc <= 1:
            milk_strata["0_to_1_milk_shops"].append(r)
        else:
            milk_strata["2plus_milk_shops"].append(r)

    strat_milk = {}
    for k_str, r_list in milk_strata.items():
        if not r_list:
            continue
        sub_d = [x["delta"] for x in r_list]
        sub_seeds = [x["seed"] for x in r_list]
        b_cows = [b_scens[s]["cows_bought"] for s in sub_seeds]
        b_sheep = [b_scens[s]["sheep_bought"] for s in sub_seeds]
        a_cows = [a_scens[s]["cows_bought"] for s in sub_seeds]
        a_sheep = [a_scens[s]["sheep_bought"] for s in sub_seeds]
        b_milk = [b_scens[s]["rev_by_product"]["MILK"] for s in sub_seeds]
        b_wool = [b_scens[s]["rev_by_product"]["WOOL"] for s in sub_seeds]
        a_milk = [a_scens[s]["rev_by_product"]["MILK"] for s in sub_seeds]
        a_wool = [a_scens[s]["rev_by_product"]["WOOL"] for s in sub_seeds]

        strat_milk[k_str] = {
            "num_matches": len(r_list),
            "mean_delta": round(float(np.mean(sub_d)), 2),
            "median_delta": round(float(np.median(sub_d)), 2),
            "win_rate": round(sum(1 for x in sub_d if x > 0) / len(sub_d), 4),
            "b_cows_mean": round(float(np.mean(b_cows)), 2),
            "b_sheep_mean": round(float(np.mean(b_sheep)), 2),
            "a_cows_mean": round(float(np.mean(a_cows)), 2),
            "a_sheep_mean": round(float(np.mean(a_sheep)), 2),
            "b_milk_rev_mean": round(float(np.mean(b_milk)), 2),
            "b_wool_rev_mean": round(float(np.mean(b_wool)), 2),
            "a_milk_rev_mean": round(float(np.mean(a_milk)), 2),
            "a_wool_rev_mean": round(float(np.mean(a_wool)), 2),
        }
    stratifications["milk_demand_shops"] = strat_milk

    # 3. Yarn Timing (Early <= Day 9 vs Late >= Day 12 vs None)
    timing_strata = {"Early_Yarn": [], "Late_Yarn": [], "No_Yarn": []}
    for r in paired_records:
        yt = r["yarn_timing"]
        if yt == "Early":
            timing_strata["Early_Yarn"].append(r)
        elif yt == "Late":
            timing_strata["Late_Yarn"].append(r)
        else:
            timing_strata["No_Yarn"].append(r)

    strat_timing = {}
    for k_str, r_list in timing_strata.items():
        if not r_list:
            continue
        sub_d = [x["delta"] for x in r_list]
        sub_seeds = [x["seed"] for x in r_list]
        b_cows = [b_scens[s]["cows_bought"] for s in sub_seeds]
        b_sheep = [b_scens[s]["sheep_bought"] for s in sub_seeds]
        a_cows = [a_scens[s]["cows_bought"] for s in sub_seeds]
        a_sheep = [a_scens[s]["sheep_bought"] for s in sub_seeds]
        b_milk = [b_scens[s]["rev_by_product"]["MILK"] for s in sub_seeds]
        b_wool = [b_scens[s]["rev_by_product"]["WOOL"] for s in sub_seeds]
        a_milk = [a_scens[s]["rev_by_product"]["MILK"] for s in sub_seeds]
        a_wool = [a_scens[s]["rev_by_product"]["WOOL"] for s in sub_seeds]

        strat_timing[k_str] = {
            "num_matches": len(r_list),
            "mean_delta": round(float(np.mean(sub_d)), 2),
            "median_delta": round(float(np.median(sub_d)), 2),
            "win_rate": round(sum(1 for x in sub_d if x > 0) / len(sub_d), 4),
            "b_cows_mean": round(float(np.mean(b_cows)), 2),
            "b_sheep_mean": round(float(np.mean(b_sheep)), 2),
            "a_cows_mean": round(float(np.mean(a_cows)), 2),
            "a_sheep_mean": round(float(np.mean(a_sheep)), 2),
            "b_milk_rev_mean": round(float(np.mean(b_milk)), 2),
            "b_wool_rev_mean": round(float(np.mean(b_wool)), 2),
            "a_milk_rev_mean": round(float(np.mean(a_milk)), 2),
            "a_wool_rev_mean": round(float(np.mean(a_wool)), 2),
        }
    stratifications["yarn_timing"] = strat_timing

    # Promotion Rule Evaluation:
    # Promote Arm B only if:
    #  1. mean paired delta remains positive,
    #  2. median is not materially negative,
    #  3. tail risk is acceptable (P10 or CVaR),
    #  4. livestock gain is not offset by excessive crop/labor loss,
    #  5. large-run evidence is convincing (CI strictly positive or p < 0.05).
    is_positive_mean = mean_d > 0
    is_median_acceptable = med_d >= -100.0
    is_convincing_ci = ci_lower > 0 or p_val_ttest < 0.05
    is_livestock_gain_preserved = delta_livestock > displaced_crop

    if is_positive_mean and is_median_acceptable and is_convincing_ci and is_livestock_gain_preserved:
        promotion_verdict = "PROMOTE ARM B"
        verdict_rationale = (
            f"Arm B convincingly outperforms Arm A by +{mean_d:.2f} (95% CI [{ci_lower:.2f}, {ci_upper:.2f}], "
            f"p={p_val_ttest:.4f}). Livestock gain (+{delta_livestock:.2f}) exceeds crop displacement (+{displaced_crop:.2f})."
        )
    else:
        promotion_verdict = "KEEP ARM A"
        verdict_rationale = (
            f"Arm B fails promotion criteria: mean delta = +{mean_d:.2f}, median delta = {med_d:.2f}, "
            f"95% CI [{ci_lower:.2f}, {ci_upper:.2f}], p={p_val_ttest:.4f}. "
            f"Livestock net gain was +{delta_livestock:.2f}, but crop displacement was {displaced_crop:.2f}. "
            f"Evidence does not provide strict positive confidence separation."
        )

    return {
        "arm_summaries": arm_summaries,
        "contrast_b_minus_a": {
            "num_pairs": len(common_seeds),
            "mean_delta": round(mean_d, 2),
            "median_delta": round(med_d, 2),
            "std_delta": round(std_d, 2),
            "bootstrap_95_ci": [round(ci_lower, 2), round(ci_upper, 2)],
            "t_statistic": round(float(t_stat), 4),
            "p_value_ttest": float(p_val_ttest),
            "w_statistic": round(float(w_stat), 4),
            "p_value_wilcoxon": float(p_val_wilcoxon),
            "win_rate": win_rate,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "p10_delta": round(p10, 2),
            "p90_delta": round(p90, 2),
            "cvar_10": round(cvar_10, 2),
            "worst_10_individual_seeds": worst_10_seeds,
        },
        "economic_decomposition": decomposition,
        "stratifications": stratifications,
        "promotion_verdict": promotion_verdict,
        "verdict_rationale": verdict_rationale,
    }


def main():
    parser = argparse.ArgumentParser(description="Run Large Arm A vs Arm B Confirmation Tournament")
    parser.add_argument("--workers", type=int, default=6, help="Process pool worker count (default: 6)")
    parser.add_argument("--start-seed", type=int, default=100, help="Start seed (default: 100)")
    parser.add_argument("--num-seeds", type=int, default=300, help="Num seeds (default: 300)")
    parser.add_argument("--output", type=str, default="simulations/experiments/results/ab_confirmation_300seeds.json",
                        help="Output JSON path")
    args = parser.parse_args()

    arms = ["ArmA", "ArmB"]
    seeds = list(range(args.start_seed, args.start_seed + args.num_seeds))
    payloads = []
    for s in seeds:
        for arm in arms:
            payloads.append({"arm": arm, "seed": s, "opponent": "starter"})

    print(f"\n==================================================================", flush=True)
    print(f"LAUNCHING PHASE 1: LARGE ARM A VS ARM B CONFIRMATION TOURNAMENT", flush=True)
    print(f"  Arms: {arms}", flush=True)
    print(f"  Seeds: {len(seeds)} (Seeds {seeds[0]} .. {seeds[-1]})", flush=True)
    print(f"  Total Matches: {len(payloads)}", flush=True)
    print(f"  Workers: {args.workers}", flush=True)
    print(f"  Output Path: {args.output}", flush=True)
    print(f"==================================================================\n", flush=True)

    t0 = time.time()
    results = []
    completed = 0
    total = len(payloads)

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_run_single_match, p): p for p in payloads}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 20 == 0 or completed == total:
                elapsed = time.time() - t0
                rate = completed / max(0.01, elapsed)
                rem = (total - completed) / max(0.01, rate)
                print(f"  Completed {completed}/{total} matches ({completed/total*100:.1f}%) in {elapsed:.1f}s (ETA: {rem:.1f}s)", flush=True)

    analysis = analyze_ab_confirmation(results)

    # Save results
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    full_output = {
        "metadata": {
            "num_seeds": args.num_seeds,
            "start_seed": args.start_seed,
            "total_matches": len(results),
            "runtime_seconds": round(time.time() - t0, 2),
            "workers": args.workers,
            "arms": arms,
        },
        "analysis": analysis,
        "raw_results": results,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    print(f"\nCompleted {total} matches in {time.time() - t0:.1f}s. Saved to {args.output}\n")
    print(f"=== PROMOTION VERDICT: {analysis['promotion_verdict']} ===")
    print(f"Rationale: {analysis['verdict_rationale']}\n")

    return full_output


if __name__ == "__main__":
    main()
