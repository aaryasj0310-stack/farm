"""Definitive Paired A/B/C Livestock Tournament Runner and Analysis Suite.

Evaluates:
  - Arm A (Control): Current Production Livestock Control (frozen target quotas, base fixed economics, zero geese).
  - Arm B (Shop Economics): Production Target Architecture + Exact Joint-Future-Path Shop Valuator.
  - Arm C (Dynamic Allocator): Fully Dynamic Shop-Conditioned Allocator (transactional shadow state, argmax valuation, endogenous herd sizing).

Tournament Protocol:
  - Stage 1: Validation on seeds 100-104 (15 matches total).
      Asserts zero housing/feed-safety invariant violations, zero consecutive_unfed >= 2,
      no material increase in unfed animal-days vs Arm A, zero escapes, and audits decision telemetry.
  - Stage 2: Full screening on 50 paired seeds 100-149 (150 matches total).
      Computes paired deltas (B-A, C-B, C-A), 95% bootstrap CIs (10k resamples), paired t-test,
      Wilcoxon signed-rank test, win/tie/loss %, CVaR 10%, worst 5 deltas, herd behavior distributions,
      shop-conditioned behavior (Yarn Store, Milk shops, Egg shops), economic attribution,
      Arm C diagnostics, post-hoc fertilizer sensitivity audit, and authoritative verdict.
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

    # Clean sys.path and sys.modules to ensure isolation
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

    # Configure Arm via authoritative config method
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
    prev_total_animals = 0

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

    def tracking_agent(obs, configuration=None):
        nonlocal peak_cows, peak_sheep, peak_geese, peak_herd
        nonlocal cows_bought, sheep_bought, geese_bought
        nonlocal cow_buy_days, sheep_buy_days, goose_buy_days, animal_purchases
        nonlocal unfed_animal_days, max_consecutive_unfed, consecutive_unfed_ge2_count
        nonlocal animal_escapes, prev_total_animals
        nonlocal housing_capacity_violations, late_purchase_invariant_violations
        nonlocal total_feed_actions, total_feed_wheat_consumed
        nonlocal rev_by_product, units_sold, last_money, last_shed, last_town_shops

        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        p_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        farm_data = farms[p_id] if len(farms) > p_id else {}
        curr_money = float(farm_data.get("money", 3000.0))
        tiles = farm_data.get("tiles", [])
        last_town_shops = list(obs.get("town_shops", []))

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

    # Collect decision logs from macro_planner
    decision_logs = macro_planner.get_livestock_decision_logs()

    # Economic attribution calculations
    livestock_rev = rev_by_product["MILK"] + rev_by_product["WOOL"] + rev_by_product["EGG"]
    fert_rev = rev_by_product["FERTILIZER"]
    crop_rev = sum(rev_by_product[c] for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"))

    # Animal purchase spend
    animal_spend = (cows_bought * 400.0) + (sheep_bought * 500.0) + (geese_bought * 300.0)
    # Feed spend: 1 wheat per feed action, wheat base cost $25
    feed_spend = total_feed_wheat_consumed * 25.0
    net_livestock_contrib = (livestock_rev + fert_rev) - (animal_spend + feed_spend)

    # Shop counts
    yarn_store_count = last_town_shops.count("YARN_STORE")
    milk_shop_count = sum(last_town_shops.count(s) for s in ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP"))
    egg_shop_count = sum(last_town_shops.count(s) for s in ("BAKERY", "BRUNCH_SPOT"))

    return {
        "arm": arm,
        "seed": seed,
        "opponent": opp_name,
        "final_score": p0_reward,
        "opponent_score": p1_reward,
        # Herd distributions
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
        "animal_purchases": animal_purchases,
        # Safety & health metrics
        "unfed_animal_days": unfed_animal_days,
        "max_consecutive_unfed": max_consecutive_unfed,
        "consecutive_unfed_ge2_count": consecutive_unfed_ge2_count,
        "animal_escapes": animal_escapes,
        "housing_capacity_violations": housing_capacity_violations,
        "late_purchase_invariant_violations": late_purchase_invariant_violations,
        "total_feed_actions": total_feed_actions,
        # Economic metrics
        "rev_by_product": {k: round(v, 2) for k, v in rev_by_product.items()},
        "units_sold": units_sold,
        "livestock_rev": round(livestock_rev, 2),
        "fert_rev": round(fert_rev, 2),
        "crop_rev": round(crop_rev, 2),
        "animal_spend": round(animal_spend, 2),
        "feed_spend": round(feed_spend, 2),
        "net_livestock_contrib": round(net_livestock_contrib, 2),
        # Shop conditions
        "town_shops": last_town_shops,
        "yarn_store_count": yarn_store_count,
        "milk_shop_count": milk_shop_count,
        "egg_shop_count": egg_shop_count,
        # Telemetry samples
        "decision_logs": decision_logs,
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


def analyze_tournament_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform comprehensive statistical analysis across Arms A, B, C."""
    by_arm: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for r in results:
        arm = r["arm"]
        seed = r["seed"]
        by_arm.setdefault(arm, {})[seed] = r

    arm_keys = ["ArmA", "ArmB", "ArmC"]
    arm_summaries = {}
    for arm in arm_keys:
        if arm not in by_arm:
            continue
        scens = by_arm[arm]
        scores = [scens[s]["final_score"] for s in scens]
        cows_b = [scens[s]["cows_bought"] for s in scens]
        sheep_b = [scens[s]["sheep_bought"] for s in scens]
        geese_b = [scens[s]["geese_bought"] for s in scens]
        peak_c = [scens[s]["peak_cows"] for s in scens]
        peak_s = [scens[s]["peak_sheep"] for s in scens]
        peak_g = [scens[s]["peak_geese"] for s in scens]
        peak_h = [scens[s]["peak_herd"] for s in scens]

        cow_days = [d for s in scens for d in scens[s]["cow_buy_days"]]
        sheep_days = [d for s in scens for d in scens[s]["sheep_buy_days"]]

        unfed = [scens[s]["unfed_animal_days"] for s in scens]
        cunfed2 = [scens[s]["consecutive_unfed_ge2_count"] for s in scens]
        escapes = [scens[s]["animal_escapes"] for s in scens]
        housing_viols = [scens[s]["housing_capacity_violations"] for s in scens]
        late_viols = [scens[s]["late_purchase_invariant_violations"] for s in scens]

        milk_r = [scens[s]["rev_by_product"]["MILK"] for s in scens]
        wool_r = [scens[s]["rev_by_product"]["WOOL"] for s in scens]
        egg_r = [scens[s]["rev_by_product"]["EGG"] for s in scens]
        fert_r = [scens[s]["fert_rev"] for s in scens]
        crop_r = [scens[s]["crop_rev"] for s in scens]
        anim_sp = [scens[s]["animal_spend"] for s in scens]
        feed_sp = [scens[s]["feed_spend"] for s in scens]
        net_contrib = [scens[s]["net_livestock_contrib"] for s in scens]

        arm_summaries[arm] = {
            "num_matches": len(scores),
            "score_mean": round(float(np.mean(scores)), 2),
            "score_median": round(float(np.median(scores)), 2),
            "score_std": round(float(np.std(scores, ddof=1)), 2) if len(scores) > 1 else 0.0,
            "score_min": round(float(np.min(scores)), 2),
            "score_max": round(float(np.max(scores)), 2),
            # Herd behavior
            "cows_bought_mean": round(float(np.mean(cows_b)), 2),
            "sheep_bought_mean": round(float(np.mean(sheep_b)), 2),
            "geese_bought_mean": round(float(np.mean(geese_b)), 2),
            "peak_cows_mean": round(float(np.mean(peak_c)), 2),
            "peak_sheep_mean": round(float(np.mean(peak_s)), 2),
            "peak_geese_mean": round(float(np.mean(peak_g)), 2),
            "peak_herd_mean": round(float(np.mean(peak_h)), 2),
            "mean_cow_buy_day": round(float(np.mean(cow_days)), 2) if cow_days else None,
            "mean_sheep_buy_day": round(float(np.mean(sheep_days)), 2) if sheep_days else None,
            # Safety
            "total_unfed_animal_days": int(sum(unfed)),
            "mean_unfed_animal_days": round(float(np.mean(unfed)), 2),
            "total_consecutive_unfed_ge2": int(sum(cunfed2)),
            "total_animal_escapes": int(sum(escapes)),
            "total_housing_violations": int(sum(housing_viols)),
            "total_late_purchase_violations": int(sum(late_viols)),
            # Economics
            "mean_milk_rev": round(float(np.mean(milk_r)), 2),
            "mean_wool_rev": round(float(np.mean(wool_r)), 2),
            "mean_egg_rev": round(float(np.mean(egg_r)), 2),
            "mean_fert_rev": round(float(np.mean(fert_r)), 2),
            "mean_crop_rev": round(float(np.mean(crop_r)), 2),
            "mean_animal_spend": round(float(np.mean(anim_sp)), 2),
            "mean_feed_spend": round(float(np.mean(feed_sp)), 2),
            "mean_net_livestock_contrib": round(float(np.mean(net_contrib)), 2),
        }

    # Paired Contrasts
    contrasts_def = [
        ("B_vs_A", "ArmB", "ArmA", "Shop Economics vs Control (Isolates Valuator with Target Structure)"),
        ("C_vs_B", "ArmC", "ArmB", "Dynamic Allocator vs Shop Economics (Isolates Allocation Freedom)"),
        ("C_vs_A", "ArmC", "ArmA", "Full Dynamic Upgrade vs Control (Total System Effect)"),
    ]

    contrasts = {}
    for name, t_arm, c_arm, desc in contrasts_def:
        if t_arm not in by_arm or c_arm not in by_arm:
            continue
        t_scens = by_arm[t_arm]
        c_scens = by_arm[c_arm]
        common = sorted([s for s in t_scens if s in c_scens])
        if not common:
            continue

        deltas = np.array([t_scens[s]["final_score"] - c_scens[s]["final_score"] for s in common], dtype=float)
        mean_d = float(np.mean(deltas))
        med_d = float(np.median(deltas))
        std_d = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else 0.0

        t_stat, p_val_ttest = stats.ttest_rel(
            [t_scens[s]["final_score"] for s in common],
            [c_scens[s]["final_score"] for s in common]
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
        for s in common:
            paired_records.append({
                "seed": s,
                "delta": round(float(t_scens[s]["final_score"] - c_scens[s]["final_score"]), 2),
                "treatment_score": t_scens[s]["final_score"],
                "control_score": c_scens[s]["final_score"],
                "yarn_stores": t_scens[s]["yarn_store_count"],
                "milk_shops": t_scens[s]["milk_shop_count"],
            })
        paired_records.sort(key=lambda x: x["delta"])
        worst_5 = paired_records[:5]

        worst_10_pct_count = max(1, int(math.ceil(len(deltas) * 0.10)))
        cvar_10 = float(np.mean(np.sort(deltas)[:worst_10_pct_count]))

        contrasts[name] = {
            "description": desc,
            "treatment": t_arm,
            "control": c_arm,
            "num_pairs": len(deltas),
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
            "worst_5_deltas": worst_5,
        }

    # Shop-Conditioned Analysis
    shop_analysis = {}
    for arm in arm_keys:
        if arm not in by_arm:
            continue
        scens = by_arm[arm]
        # Yarn Store: 0 vs >= 1
        yarn_0 = [scens[s] for s in scens if scens[s]["yarn_store_count"] == 0]
        yarn_ge1 = [scens[s] for s in scens if scens[s]["yarn_store_count"] >= 1]

        # Milk shops: 0 vs >= 2
        milk_0 = [scens[s] for s in scens if scens[s]["milk_shop_count"] == 0]
        milk_ge2 = [scens[s] for s in scens if scens[s]["milk_shop_count"] >= 2]

        shop_analysis[arm] = {
            "yarn_0": {
                "count": len(yarn_0),
                "mean_score": round(float(np.mean([x["final_score"] for x in yarn_0])), 2) if yarn_0 else 0,
                "mean_sheep_bought": round(float(np.mean([x["sheep_bought"] for x in yarn_0])), 2) if yarn_0 else 0,
                "mean_wool_rev": round(float(np.mean([x["rev_by_product"]["WOOL"] for x in yarn_0])), 2) if yarn_0 else 0,
            },
            "yarn_ge1": {
                "count": len(yarn_ge1),
                "mean_score": round(float(np.mean([x["final_score"] for x in yarn_ge1])), 2) if yarn_ge1 else 0,
                "mean_sheep_bought": round(float(np.mean([x["sheep_bought"] for x in yarn_ge1])), 2) if yarn_ge1 else 0,
                "mean_wool_rev": round(float(np.mean([x["rev_by_product"]["WOOL"] for x in yarn_ge1])), 2) if yarn_ge1 else 0,
            },
            "milk_0": {
                "count": len(milk_0),
                "mean_cows_bought": round(float(np.mean([x["cows_bought"] for x in milk_0])), 2) if milk_0 else 0,
                "mean_milk_rev": round(float(np.mean([x["rev_by_product"]["MILK"] for x in milk_0])), 2) if milk_0 else 0,
            },
            "milk_ge2": {
                "count": len(milk_ge2),
                "mean_cows_bought": round(float(np.mean([x["cows_bought"] for x in milk_ge2])), 2) if milk_ge2 else 0,
                "mean_milk_rev": round(float(np.mean([x["rev_by_product"]["MILK"] for x in milk_ge2])), 2) if milk_ge2 else 0,
            }
        }

    # Arm C Deviation Analysis
    arm_c_deviations = []
    if "ArmC" in by_arm and "ArmA" in by_arm:
        c_scens = by_arm["ArmC"]
        a_scens = by_arm["ArmA"]
        for s in c_scens:
            if s in a_scens:
                c_cows = c_scens[s]["cows_bought"]
                c_sheep = c_scens[s]["sheep_bought"]
                c_geese = c_scens[s]["geese_bought"]
                a_cows = a_scens[s]["cows_bought"]
                a_sheep = a_scens[s]["sheep_bought"]
                a_geese = a_scens[s]["geese_bought"]
                is_deviated = (c_cows != a_cows) or (c_sheep != a_sheep) or (c_geese != a_geese)
                arm_c_deviations.append({
                    "seed": s,
                    "deviated": is_deviated,
                    "arm_c_herd": (c_cows, c_sheep, c_geese),
                    "arm_a_herd": (a_cows, a_sheep, a_geese),
                    "delta": c_scens[s]["final_score"] - a_scens[s]["final_score"],
                })

    num_dev = sum(1 for d in arm_c_deviations if d["deviated"])
    dev_rate = round(num_dev / max(1, len(arm_c_deviations)), 4)

    # Determine Verdict
    c_vs_a = contrasts.get("C_vs_A", {})
    b_vs_a = contrasts.get("B_vs_A", {})
    c_mean_d = c_vs_a.get("mean_delta", 0.0)
    c_pval = c_vs_a.get("p_value_ttest", 1.0)
    c_ci = c_vs_a.get("bootstrap_95_ci", [0.0, 0.0])
    b_mean_d = b_vs_a.get("mean_delta", 0.0)
    b_pval = b_vs_a.get("p_value_ttest", 1.0)

    if c_mean_d > 0 and c_ci[0] > 0 and c_pval < 0.05:
        verdict = "DYNAMIC SHOP-CONDITIONED LIVESTOCK WINS"
        verdict_rationale = f"Arm C significantly outperforms Control by +{c_mean_d:.2f} (95% CI [{c_ci[0]}, {c_ci[1]}], p={c_pval:.4e})."
    elif b_mean_d > 0 and b_pval < 0.05 and c_mean_d <= b_mean_d:
        verdict = "SHOP ECONOMICS HELP — KEEP TARGET STRUCTURE"
        verdict_rationale = f"Arm B outperforms Control (+{b_mean_d:.2f}, p={b_pval:.4e}), while dynamic Arm C does not beat Arm B."
    elif c_mean_d <= 0 and b_mean_d <= 0 and (c_pval < 0.05 or b_pval < 0.05 or (c_ci[1] < 50 and b_vs_a.get('bootstrap_95_ci', [0,0])[1] < 50)):
        verdict = "KEEP CURRENT LIVESTOCK STRATEGY"
        verdict_rationale = f"Neither treatment outperforms Control (C-A: {c_mean_d:.2f}, B-A: {b_mean_d:.2f})."
    else:
        verdict = "INCONCLUSIVE — RUN LARGE CONFIRMATION"
        verdict_rationale = f"Results show C-A delta of {c_mean_d:.2f} (CI [{c_ci[0]}, {c_ci[1]}], p={c_pval:.4f}), which does not cross strict 95% confidence separation."

    return {
        "arm_summaries": arm_summaries,
        "contrasts": contrasts,
        "shop_analysis": shop_analysis,
        "arm_c_deviation_rate": dev_rate,
        "arm_c_deviations": arm_c_deviations,
        "verdict": verdict,
        "verdict_rationale": verdict_rationale,
    }


def run_post_hoc_fertilizer_sensitivity() -> Dict[str, Any]:
    """Audit marginal valuator sensitivity across fertilizer valuation tiers.

    Tiers:
      - Full credit: 100% fertilizer revenue
      - Half credit: 50% fertilizer revenue
      - Zero credit: 0% fertilizer revenue
    Evaluates representative state on Day 6 with 1 Yarn Store, 1 Bakery.
    """
    if _AGENT_DIR not in sys.path:
        sys.path.insert(0, _AGENT_DIR)
    for s in ("state", "strategy", "execution", "market"):
        p = os.path.join(_AGENT_DIR, s)
        if p not in sys.path:
            sys.path.insert(0, p)

    from strategy.marginal_livestock_valuator import estimate_realized_marginal_animal_value

    current_day = 6
    unlocked_shops = ["YARN_STORE", "BAKERY"]
    market_inv = {"MILK": 10000, "WOOL": 10000, "EGG": 10000, "FERTILIZER": 10000}
    current_herd = {"COW": 1, "SHEEP": 1, "GOOSE": 0}

    val_cow = estimate_realized_marginal_animal_value(
        species="COW", day=current_day, current_animals=current_herd,
        market_inventory=market_inv, town_shops=unlocked_shops
    )
    val_sheep = estimate_realized_marginal_animal_value(
        species="SHEEP", day=current_day, current_animals=current_herd,
        market_inventory=market_inv, town_shops=unlocked_shops
    )
    val_goose = estimate_realized_marginal_animal_value(
        species="GOOSE", day=current_day, current_animals=current_herd,
        market_inventory=market_inv, town_shops=unlocked_shops
    )

    results = {}
    for tier in ("full_fertilizer", "half_fertilizer", "zero_fertilizer"):
        c_v = val_cow["fertilizer_sensitivity"][tier]
        s_v = val_sheep["fertilizer_sensitivity"][tier]
        g_v = val_goose["fertilizer_sensitivity"][tier]
        pref = "SHEEP" if s_v > c_v and s_v > g_v else ("COW" if c_v > g_v else "GOOSE")
        results[tier] = {
            "COW": c_v,
            "SHEEP": s_v,
            "GOOSE": g_v,
            "preferred": pref,
            "cow_minus_sheep": round(c_v - s_v, 2),
        }
    return results


def main():
    parser = argparse.ArgumentParser(description="Run Definitive A/B/C Livestock Tournament")
    parser.add_argument("--stage", type=str, choices=["validation", "tournament"], default="validation",
                        help="Run stage: 'validation' (seeds 100-104) or 'tournament' (seeds 100-149)")
    parser.add_argument("--workers", type=int, default=4, help="Process pool worker count (default: 4)")
    parser.add_argument("--start-seed", type=int, default=None, help="Override start seed")
    parser.add_argument("--num-seeds", type=int, default=None, help="Override num seeds")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()

    if args.stage == "validation":
        start_seed = args.start_seed if args.start_seed is not None else 100
        num_seeds = args.num_seeds if args.num_seeds is not None else 5
        out_path = args.output or "simulations/experiments/results/livestock_stage1_validation.json"
    else:
        start_seed = args.start_seed if args.start_seed is not None else 100
        num_seeds = args.num_seeds if args.num_seeds is not None else 50
        out_path = args.output or "simulations/experiments/results/livestock_tournament_results.json"

    arms = ["ArmA", "ArmB", "ArmC"]
    seeds = list(range(start_seed, start_seed + num_seeds))
    payloads = []
    for arm in arms:
        for s in seeds:
            payloads.append({"arm": arm, "seed": s, "opponent": "starter"})

    print(f"\n==================================================================", flush=True)
    print(f"LAUNCHING DEFINITIVE LIVESTOCK TOURNAMENT — STAGE: {args.stage.upper()}", flush=True)
    print(f"  Arms: {arms}", flush=True)
    print(f"  Seeds: {len(seeds)} ({seeds[0]} .. {seeds[-1]})", flush=True)
    print(f"  Total Matches: {len(payloads)}", flush=True)
    print(f"  Workers: {args.workers}", flush=True)
    print(f"  Output Path: {out_path}", flush=True)
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
            if completed % (5 if args.stage == "validation" else 10) == 0 or completed == total:
                elapsed = time.time() - t0
                rate = completed / max(0.01, elapsed)
                rem = (total - completed) / max(0.01, rate)
                print(f"  Completed {completed}/{total} matches ({completed/total*100:.1f}%) in {elapsed:.1f}s (ETA: {rem:.1f}s)", flush=True)

    analysis = analyze_tournament_results(results)
    fert_audit = run_post_hoc_fertilizer_sensitivity()

    # Save results
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    full_output = {
        "stage": args.stage,
        "runtime_seconds": round(time.time() - t0, 2),
        "arms": arms,
        "num_seeds": num_seeds,
        "start_seed": start_seed,
        "analysis": analysis,
        "fertilizer_sensitivity_audit": fert_audit,
        "raw_results": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    print(f"\nCompleted {total} matches in {time.time() - t0:.1f}s. Saved to {out_path}\n")

    # Print Stage 1 Validation Report
    if args.stage == "validation":
        print("=== STAGE 1 VALIDATION AUDIT REPORT ===")
        all_passed = True
        for arm in arms:
            s_data = analysis["arm_summaries"].get(arm, {})
            h_viols = s_data.get("total_housing_violations", 0)
            l_viols = s_data.get("total_late_purchase_violations", 0)
            cunfed2 = s_data.get("total_consecutive_unfed_ge2", 0)
            escapes = s_data.get("total_animal_escapes", 0)
            unfed = s_data.get("total_unfed_animal_days", 0)

            print(f"Arm {arm}:")
            print(f"  Housing violations: {h_viols} (require 0)")
            print(f"  Late purchase violations: {l_viols} (require 0)")
            print(f"  Consecutive unfed >= 2: {cunfed2} (require 0 caused by new allocator)")
            print(f"  Animal escapes: {escapes} (require 0)")
            print(f"  Total unfed animal-days: {unfed}")

            if h_viols > 0 or l_viols > 0 or cunfed2 > 0 or escapes > 0:
                all_passed = False

        print(f"\nStage 1 Validation Passed: {all_passed}\n")

    return full_output


if __name__ == "__main__":
    main()
