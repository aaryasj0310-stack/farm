"""Isolated SW Quadrant Tournament: Arms A, B, C, and D.

Evaluates:
  - Arm A (Control): Production SW policy (legacy gating & activation).
  - Arm B (Liquidity Discrete): Authoritative early-liquidity gate + discrete activation (isolates timing).
  - Arm C (Dusta Prior Progressive): Early-liquidity gate + soft D8-9 prior + progressive activation.
  - Arm D (Pure Economic Progressive): Pure economic gate (no timing prior) + progressive activation.

Telemetry Captured:
  1. SW purchase timing (day, hour, step)
  2. Pre-buy cash, post-buy cash, post_sw_cash_minus_obligations
  3. Blocking treasury terms and land rejection reasons
  4. Progressive SW occupancy at +6h, +12h, +24h, +48h, +72h
  5. SW productive utilization fraction
  6. Planted unwatered tile-hours and ripe unharvested tile-hours in SW
  7. Herd maintenance debt (feed shortfalls)
  8. Worker movement fraction
  9. Tile rejection counts (NO_LABOR, NO_POSITIVE_CROP, TRAVEL_TOO_HIGH, TREASURY, MANDATORY_NW_NE_DEBT, ACTIVATION_SAFETY_MARGIN)
  10. Product revenues and units sold
  11. Paired deltas, bootstrap 95% CI, p-value, worst 5 deltas, and CVaR
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
    opp_name = payload["opponent"]

    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'land_serviceability_model',
        'marginal_livestock_valuator'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    import state_tracker
    import config

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    if hasattr(agent_module, "reset_daily_telemetry"):
        agent_module.reset_daily_telemetry()
    elif hasattr(agent_module, "reset_daily_log"):
        agent_module.reset_daily_log()

    # Configure Arm via authoritative config method
    config.set_sw_experiment_arm(arm)

    # Tracking variables
    sw_purchased = False
    sw_purchase_day = None
    sw_purchase_hour = None
    sw_purchase_step = None
    pre_buy_cash = None
    post_buy_cash = None
    post_sw_cash_minus_obligations = None
    blocking_treasury_term_at_buy = None
    herd_at_purchase = None

    rejection_history = []
    tile_rejection_counts = {
        "NO_LABOR": 0,
        "NO_POSITIVE_CROP": 0,
        "TRAVEL_TOO_HIGH": 0,
        "TREASURY": 0,
        "MANDATORY_NW_NE_DEBT": 0,
        "ACTIVATION_SAFETY_MARGIN": 0,
    }

    # Hourly tracking for progressive occupancy & utilization
    sw_occupancy_by_step = {}  # step -> active_tiles_count
    sw_occupied_tile_hours = 0
    sw_actions_serviced = 0
    sw_planted_unwatered_hours = 0
    sw_ripe_unharvested_hours = 0

    total_move_actions = 0
    total_productive_actions = 0
    total_idle_actions = 0
    total_feed_actions = 0
    total_care_actions = 0
    total_milk_actions = 0
    total_shear_actions = 0
    feed_shortfalls = 0
    animal_deaths = 0

    peak_cows = 0
    peak_sheep = 0
    peak_herd = 0

    rev_by_product = {
        "MILK": 0.0, "WOOL": 0.0, "FERTILIZER": 0.0, "EGG": 0.0,
        "WHEAT": 0.0, "CARROT": 0.0, "MELON": 0.0, "STRAWBERRY": 0.0, "TOMATO": 0.0
    }
    units_sold = {k: 0 for k in rev_by_product}
    sw_crops_planted = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}

    last_money = 3000.0
    last_shed = {}
    prev_unlocked_quads = ["NW"]

    def tracking_agent(obs, configuration=None):
        nonlocal sw_purchased, sw_purchase_day, sw_purchase_hour, sw_purchase_step
        nonlocal pre_buy_cash, post_buy_cash, post_sw_cash_minus_obligations
        nonlocal blocking_treasury_term_at_buy, herd_at_purchase
        nonlocal rejection_history, tile_rejection_counts
        nonlocal sw_occupancy_by_step, sw_occupied_tile_hours, sw_actions_serviced
        nonlocal sw_planted_unwatered_hours, sw_ripe_unharvested_hours
        nonlocal total_move_actions, total_productive_actions, total_idle_actions
        nonlocal total_feed_actions, total_care_actions, total_milk_actions, total_shear_actions
        nonlocal feed_shortfalls, animal_deaths, peak_cows, peak_sheep, peak_herd
        nonlocal rev_by_product, units_sold, sw_crops_planted, last_money, last_shed, prev_unlocked_quads

        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        p_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        farm_data = farms[p_id] if len(farms) > p_id else {}
        curr_money = float(farm_data.get("money", 3000.0))
        unlocked_quads = farm_data.get("unlocked_quadrants", ["NW"])
        tiles = farm_data.get("tiles", [])

        # Count herd
        cows, sheep, geese = 0, 0, 0
        sw_active_tiles = 0

        for r_idx, row in enumerate(tiles):
            for c_idx, t_dict in enumerate(row):
                if not isinstance(t_dict, dict):
                    continue
                an = t_dict.get("animal")
                if an == "COW":
                    cows += 1
                elif an == "SHEEP":
                    sheep += 1
                elif an == "GOOSE":
                    geese += 1

                if an and t_dict.get("consecutive_unfed", 0) > 0 and hour == 0:
                    feed_shortfalls += 1

                # SW tile analysis: 0 <= c_idx <= 4 and 5 <= r_idx <= 9
                is_sw = (0 <= c_idx <= 4) and (5 <= r_idx <= 9) and not (c_idx == 4 and r_idx == 5)
                if is_sw:
                    is_plant = bool(t_dict.get("plant") or t_dict.get("is_plant") or t_dict.get("kind") == "PLANT")
                    is_animal = bool(an or t_dict.get("kind") in ("PASTURE", "COOP"))
                    if is_plant or is_animal:
                        sw_active_tiles += 1

                    # Unwatered check at hour 23
                    if is_plant and hour == 23 and not t_dict.get("watered_today", False):
                        sw_planted_unwatered_hours += 1

                    # Ripe unharvested check
                    if is_plant and t_dict.get("yield_units", 0) > 0:
                        sw_ripe_unharvested_hours += 1

        herd = cows + sheep + geese
        if herd > peak_herd:
            peak_herd = herd
        if cows > peak_cows:
            peak_cows = cows
        if sheep > peak_sheep:
            peak_sheep = sheep

        # Detect SW unlock
        if "SW" in unlocked_quads and not sw_purchased:
            sw_purchased = True
            sw_purchase_step = step
            sw_purchase_day = day
            sw_purchase_hour = hour
            pre_buy_cash = last_money
            post_buy_cash = curr_money
            herd_at_purchase = herd

            last_telemetry = agent_module.get_last_turn_telemetry()
            if last_telemetry and "macro_plan_diagnostic" in last_telemetry:
                mp_diag = last_telemetry["macro_plan_diagnostic"] or {}
                ld = mp_diag.get("land_decision", {})
                post_sw_cash_minus_obligations = ld.get("post_sw_cash_minus_obligations", post_buy_cash - 300.0)
                blocking_treasury_term_at_buy = ld.get("blocking_treasury_term")

        if sw_purchased:
            sw_occupancy_by_step[step] = sw_active_tiles
            sw_occupied_tile_hours += sw_active_tiles

        # Check for market sales
        priv = obs.get("private", {})
        curr_shed = priv.get("shed", {})
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
        prev_unlocked_quads = list(unlocked_quads)

        # Call agent
        action = agent_module.agent(obs)

        # Process action telemetry
        if isinstance(action, dict):
            all_units = [action.get("farmer", [])] + action.get("hands", [])
            for u in all_units:
                if not u:
                    total_idle_actions += 1
                else:
                    cmd = u[0]
                    if cmd in ("NORTH", "SOUTH", "EAST", "WEST"):
                        total_move_actions += 1
                    elif cmd in ("PASS", "IDLE"):
                        total_idle_actions += 1
                    else:
                        total_productive_actions += 1
                        if cmd == "FEED":
                            total_feed_actions += 1
                        elif cmd == "CARE":
                            total_care_actions += 1
                        elif cmd == "MILK":
                            total_milk_actions += 1
                        elif cmd == "SHEAR":
                            total_shear_actions += 1
                        elif cmd == "PLANT":
                            try:
                                if len(u) >= 4 and isinstance(u[1], int) and isinstance(u[2], int):
                                    px, py, crop_name = u[1], u[2], u[3]
                                elif len(u) >= 3 and isinstance(u[1], (list, tuple)):
                                    px, py = u[1][0], u[1][1]
                                    crop_name = u[2]
                                else:
                                    crop_name = None
                                    px, py = 0, 0

                                if 0 <= px <= 4 and 5 <= py <= 9:
                                    sw_actions_serviced += 1
                                    if crop_name in sw_crops_planted:
                                        sw_crops_planted[crop_name] += 1
                            except Exception:
                                pass

        # Harvest Diagnostics from agent_module telemetry
        last_tel = agent_module.get_last_turn_telemetry()
        if last_tel and "macro_plan_diagnostic" in last_tel:
            mp_diag = last_tel["macro_plan_diagnostic"] or {}
            ld = mp_diag.get("land_decision", {})
            if ld and ld.get("next_quadrant") == 3 and not sw_purchased:
                rejection_history.append({
                    "day": day,
                    "hour": hour,
                    "money": curr_money,
                    "reason": ld.get("final_rejection_or_acceptance_reason"),
                    "blocking_term": ld.get("blocking_treasury_term"),
                    "shortfall": ld.get("shortfall", 0.0),
                })

            # Accumulate progressive activation rejection counts
            counts = mp_diag.get("sw_tile_rejection_counts", {})
            for k_reason, count_val in counts.items():
                if k_reason in tile_rejection_counts:
                    tile_rejection_counts[k_reason] += count_val

        return action

    env = make("kaggriculture", configuration={"episodeSteps": 720}, info={"seed": seed})
    agents = [tracking_agent, opp_name]
    env.run(agents)

    p0_reward = float(env.state[0].reward or 0.0)
    p1_reward = float(env.state[1].reward or 0.0)

    # Compute Progressive Occupancy Checkpoints
    occ_plus_6h = None
    occ_plus_12h = None
    occ_plus_24h = None
    occ_plus_48h = None
    occ_plus_72h = None
    if sw_purchase_step is not None:
        occ_plus_6h = sw_occupancy_by_step.get(sw_purchase_step + 6, sw_occupancy_by_step.get(max(sw_occupancy_by_step.keys()), 0))
        occ_plus_12h = sw_occupancy_by_step.get(sw_purchase_step + 12, sw_occupancy_by_step.get(max(sw_occupancy_by_step.keys()), 0))
        occ_plus_24h = sw_occupancy_by_step.get(sw_purchase_step + 24, sw_occupancy_by_step.get(max(sw_occupancy_by_step.keys()), 0))
        occ_plus_48h = sw_occupancy_by_step.get(sw_purchase_step + 48, sw_occupancy_by_step.get(max(sw_occupancy_by_step.keys()), 0))
        occ_plus_72h = sw_occupancy_by_step.get(sw_purchase_step + 72, sw_occupancy_by_step.get(max(sw_occupancy_by_step.keys()), 0))

    final_occ = sw_occupancy_by_step.get(719, 0) if sw_purchased else 0

    # Unlocked tile hours (24 production tiles in SW)
    sw_unlocked_steps = (720 - sw_purchase_step) if sw_purchase_step is not None else 0
    sw_available_tile_hours = 24 * sw_unlocked_steps
    sw_productive_util_frac = round(sw_occupied_tile_hours / max(1, sw_available_tile_hours), 4) if sw_available_tile_hours > 0 else 0.0

    total_actions = total_move_actions + total_productive_actions + total_idle_actions
    worker_move_frac = round(total_move_actions / max(1, total_actions), 4)

    return {
        "arm": arm,
        "seed": seed,
        "opponent": opp_name,
        "final_score": p0_reward,
        "opponent_score": p1_reward,
        "sw_purchased": sw_purchased,
        "sw_purchase_day": sw_purchase_day,
        "sw_purchase_hour": sw_purchase_hour,
        "sw_purchase_step": sw_purchase_step,
        "pre_buy_cash": round(pre_buy_cash, 2) if pre_buy_cash is not None else None,
        "post_buy_cash": round(post_buy_cash, 2) if post_buy_cash is not None else None,
        "post_sw_cash_minus_obligations": round(post_sw_cash_minus_obligations, 2) if post_sw_cash_minus_obligations is not None else None,
        "blocking_treasury_term_at_buy": blocking_treasury_term_at_buy,
        "herd_at_purchase": herd_at_purchase,
        "rejection_history": rejection_history[-5:] if rejection_history else [],
        "sw_occupancy_plus_6h": occ_plus_6h,
        "sw_occupancy_plus_12h": occ_plus_12h,
        "sw_occupancy_plus_24h": occ_plus_24h,
        "sw_occupancy_plus_48h": occ_plus_48h,
        "sw_occupancy_plus_72h": occ_plus_72h,
        "sw_final_occupancy": final_occ,
        "sw_available_tile_hours": sw_available_tile_hours,
        "sw_occupied_tile_hours": sw_occupied_tile_hours,
        "sw_productive_utilization_fraction": sw_productive_util_frac,
        "sw_actions_serviced": sw_actions_serviced,
        "sw_planted_unwatered_hours": sw_planted_unwatered_hours,
        "sw_ripe_unharvested_hours": sw_ripe_unharvested_hours,
        "tile_rejection_counts": tile_rejection_counts,
        "peak_cows": peak_cows,
        "peak_sheep": peak_sheep,
        "peak_herd": peak_herd,
        "feed_shortfalls": feed_shortfalls,
        "animal_deaths": animal_deaths,
        "total_move_actions": total_move_actions,
        "total_productive_actions": total_productive_actions,
        "total_idle_actions": total_idle_actions,
        "worker_movement_fraction": worker_move_frac,
        "rev_by_product": {k: round(v, 1) for k, v in rev_by_product.items()},
        "units_sold": units_sold,
        "sw_crops_planted": sw_crops_planted,
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


def analyze_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform statistical analysis across arms and paired contrasts."""
    by_arm: Dict[str, Dict[Tuple[int, str], Dict[str, Any]]] = {}
    for r in results:
        arm = r["arm"]
        scenario = (r["seed"], r["opponent"])
        by_arm.setdefault(arm, {})[scenario] = r

    arm_summaries = {}
    for arm, scens in by_arm.items():
        scores = [scens[s]["final_score"] for s in scens]
        sw_buys = [scens[s] for s in scens if scens[s]["sw_purchased"]]
        buy_days = [b["sw_purchase_day"] for b in sw_buys if b["sw_purchase_day"] is not None]
        pre_cash = [b["pre_buy_cash"] for b in sw_buys if b["pre_buy_cash"] is not None]
        post_cash = [b["post_buy_cash"] for b in sw_buys if b["post_buy_cash"] is not None]
        herds = [b["herd_at_purchase"] for b in sw_buys if b["herd_at_purchase"] is not None]
        utils = [scens[s]["sw_productive_utilization_fraction"] for s in scens]
        move_fracs = [scens[s]["worker_movement_fraction"] for s in scens]

        # Occupancy at checkpoints
        occ_6 = [b["sw_occupancy_plus_6h"] for b in sw_buys if b.get("sw_occupancy_plus_6h") is not None]
        occ_12 = [b["sw_occupancy_plus_12h"] for b in sw_buys if b.get("sw_occupancy_plus_12h") is not None]
        occ_24 = [b["sw_occupancy_plus_24h"] for b in sw_buys if b.get("sw_occupancy_plus_24h") is not None]
        occ_48 = [b["sw_occupancy_plus_48h"] for b in sw_buys if b.get("sw_occupancy_plus_48h") is not None]
        occ_72 = [b["sw_occupancy_plus_72h"] for b in sw_buys if b.get("sw_occupancy_plus_72h") is not None]

        # Rejection reason aggregation
        rej_agg = {
            "NO_LABOR": sum(scens[s]["tile_rejection_counts"]["NO_LABOR"] for s in scens),
            "NO_POSITIVE_CROP": sum(scens[s]["tile_rejection_counts"]["NO_POSITIVE_CROP"] for s in scens),
            "TRAVEL_TOO_HIGH": sum(scens[s]["tile_rejection_counts"]["TRAVEL_TOO_HIGH"] for s in scens),
            "TREASURY": sum(scens[s]["tile_rejection_counts"]["TREASURY"] for s in scens),
            "MANDATORY_NW_NE_DEBT": sum(scens[s]["tile_rejection_counts"]["MANDATORY_NW_NE_DEBT"] for s in scens),
            "ACTIVATION_SAFETY_MARGIN": sum(scens[s]["tile_rejection_counts"]["ACTIVATION_SAFETY_MARGIN"] for s in scens),
        }

        # Revenue breakdown aggregation
        rev_agg = {}
        for s in scens:
            for prod, val in scens[s]["rev_by_product"].items():
                rev_agg[prod] = rev_agg.get(prod, 0.0) + val
        mean_rev_by_prod = {k: round(v / len(scens), 1) for k, v in rev_agg.items()}

        arm_summaries[arm] = {
            "num_matches": len(scores),
            "mean_score": round(float(np.mean(scores)), 2),
            "median_score": round(float(np.median(scores)), 2),
            "std_score": round(float(np.std(scores, ddof=1)), 2) if len(scores) > 1 else 0.0,
            "sw_purchase_count": len(sw_buys),
            "sw_purchase_rate": round(len(sw_buys) / len(scores), 3),
            "mean_sw_purchase_day": round(float(np.mean(buy_days)), 2) if buy_days else None,
            "median_sw_purchase_day": round(float(np.median(buy_days)), 2) if buy_days else None,
            "mean_pre_buy_cash": round(float(np.mean(pre_cash)), 2) if pre_cash else None,
            "median_pre_buy_cash": round(float(np.median(pre_cash)), 2) if pre_cash else None,
            "mean_post_buy_cash": round(float(np.mean(post_cash)), 2) if post_cash else None,
            "median_post_buy_cash": round(float(np.median(post_cash)), 2) if post_cash else None,
            "mean_herd_at_purchase": round(float(np.mean(herds)), 2) if herds else None,
            "occupancy_benchmarks": {
                "plus_6h": round(float(np.mean(occ_6)), 2) if occ_6 else None,
                "plus_12h": round(float(np.mean(occ_12)), 2) if occ_12 else None,
                "plus_24h": round(float(np.mean(occ_24)), 2) if occ_24 else None,
                "plus_48h": round(float(np.mean(occ_48)), 2) if occ_48 else None,
                "plus_72h": round(float(np.mean(occ_72)), 2) if occ_72 else None,
            },
            "mean_sw_utilization": round(float(np.mean(utils)), 4),
            "mean_worker_movement_fraction": round(float(np.mean(move_fracs)), 4),
            "total_tile_rejections": rej_agg,
            "mean_revenue_by_product": mean_rev_by_prod,
        }

    # Contrast Analysis
    contrasts_def = [
        ("B_vs_A", "ArmB_Liquidity_Discrete", "ArmA_Control_Frozen", "Ownership Timing Isolation"),
        ("C_vs_B", "ArmC_DustaPrior_Progressive", "ArmB_Liquidity_Discrete", "Progressive Activation Value"),
        ("D_vs_C", "ArmD_PureEcon_Progressive", "ArmC_DustaPrior_Progressive", "Primary Causal Contrast (Pure Econ vs Dusta Prior)"),
        ("C_vs_A", "ArmC_DustaPrior_Progressive", "ArmA_Control_Frozen", "Total System Upgrade (Arm C vs Control)"),
        ("D_vs_A", "ArmD_PureEcon_Progressive", "ArmA_Control_Frozen", "Total System Upgrade (Arm D vs Control)"),
    ]

    contrasts = {}
    for name, t_arm, c_arm, desc in contrasts_def:
        if t_arm not in by_arm or c_arm not in by_arm:
            continue
        t_scens = by_arm[t_arm]
        c_scens = by_arm[c_arm]
        common = [s for s in t_scens if s in c_scens]
        if not common:
            continue

        deltas = np.array([t_scens[s]["final_score"] - c_scens[s]["final_score"] for s in common], dtype=float)
        mean_d = float(np.mean(deltas))
        med_d = float(np.median(deltas))
        std_d = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else 0.0

        t_stat, p_val = stats.ttest_rel(
            [t_scens[s]["final_score"] for s in common],
            [c_scens[s]["final_score"] for s in common]
        )
        ci_lower, ci_upper = compute_bootstrap_ci(deltas, num_resamples=10000, ci=0.95)

        wins = int(np.sum(deltas > 0))
        ties = int(np.sum(deltas == 0))
        losses = int(np.sum(deltas < 0))
        win_rate = round(wins / len(deltas), 4)

        # Distribution percentiles
        p10 = float(np.percentile(deltas, 10))
        p90 = float(np.percentile(deltas, 90))

        # Worst 5 deltas
        paired_records = []
        for s in common:
            paired_records.append({
                "seed": s[0],
                "opponent": s[1],
                "delta": round(float(t_scens[s]["final_score"] - c_scens[s]["final_score"]), 2),
                "treatment_score": t_scens[s]["final_score"],
                "control_score": c_scens[s]["final_score"],
            })
        paired_records.sort(key=lambda x: x["delta"])
        worst_5 = paired_records[:5]

        # CVaR (Conditional Value at Risk): mean of worst 10% deltas
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
            "p_value": float(p_val),
            "t_statistic": float(t_stat),
            "bootstrap_95_ci": [round(ci_lower, 2), round(ci_upper, 2)],
            "win_rate": win_rate,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "p10_delta": round(p10, 2),
            "p90_delta": round(p90, 2),
            "cvar_10": round(cvar_10, 2),
            "worst_5_deltas": worst_5,
        }

    return {
        "arm_summaries": arm_summaries,
        "contrasts": contrasts,
    }


def main():
    parser = argparse.ArgumentParser(description="Run SW Progressive isolated experiment")
    parser.add_argument("--num-seeds", type=int, default=25, help="Number of seeds (default: 25)")
    parser.add_argument("--start-seed", type=int, default=101, help="Starting seed (default: 101)")
    parser.add_argument("--max-workers", type=int, default=8, help="Parallel workers (default: 8)")
    parser.add_argument("--output", type=str, default="simulations/experiments/results/sw_progressive_experiment_results.json", help="Output path")
    args = parser.parse_args()

    arms = [
        "ArmA_Control_Frozen",
        "ArmB_Liquidity_Discrete",
        "ArmC_DustaPrior_Progressive",
        "ArmD_PureEcon_Progressive",
    ]
    opponents = ["starter", "random"]
    seeds = list(range(args.start_seed, args.start_seed + args.num_seeds))

    payloads = []
    for arm in arms:
        for opp in opponents:
            for s in seeds:
                payloads.append({
                    "arm": arm,
                    "seed": s,
                    "opponent": opp,
                })

    print(f"[EXPERIMENT] Launching SW Progressive Experiment:", flush=True)
    print(f"  Arms: {arms}", flush=True)
    print(f"  Seeds: {len(seeds)} (Seeds {seeds[0]}..{seeds[-1]})", flush=True)
    print(f"  Opponents: {opponents}", flush=True)
    print(f"  Total Matches: {len(payloads)}", flush=True)
    print(f"  Workers: {args.max_workers}", flush=True)

    t0 = time.time()
    results = []
    completed = 0
    total = len(payloads)

    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(_run_single_match, p): p for p in payloads}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total:
                elapsed = time.time() - t0
                rate = completed / elapsed
                rem = (total - completed) / max(0.01, rate)
                print(f"  Completed {completed}/{total} matches ({completed/total*100:.1f}%) in {elapsed:.1f}s (ETA: {rem:.1f}s)", flush=True)

    analysis = analyze_results(results)

    out_data = {
        "metadata": {
            "num_seeds": args.num_seeds,
            "start_seed": args.start_seed,
            "total_matches": len(results),
            "runtime_seconds": round(time.time() - t0, 2),
            "arms": arms,
            "opponents": opponents,
        },
        "analysis": analysis,
        "raw_results": results,
    }

    out_path = os.path.join(_REPO_ROOT, args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)

    print(f"\n[DONE] Experiment finished in {time.time() - t0:.1f}s. Results written to: {out_path}")
    print("\n--- Summary of Arms ---")
    for arm, summary in analysis["arm_summaries"].items():
        print(f"  {arm}:")
        print(f"    Mean Score: {summary['mean_score']} (Median: {summary['median_score']}, Std: {summary['std_score']})")
        print(f"    SW Purchase Count: {summary['sw_purchase_count']}/{summary['num_matches']} (Rate: {summary['sw_purchase_rate']*100:.1f}%)")
        print(f"    Mean SW Day: {summary['mean_sw_purchase_day']} (Median: {summary['median_sw_purchase_day']})")
        print(f"    Mean Pre-Cash: ${summary['mean_pre_buy_cash']} | Post-Cash: ${summary['mean_post_buy_cash']} | Herd: {summary['mean_herd_at_purchase']}")
        print(f"    Progressive Occupancy: +6h={summary['occupancy_benchmarks']['plus_6h']}, +12h={summary['occupancy_benchmarks']['plus_12h']}, +24h={summary['occupancy_benchmarks']['plus_24h']}, +48h={summary['occupancy_benchmarks']['plus_48h']}, +72h={summary['occupancy_benchmarks']['plus_72h']}")
        print(f"    SW Utilization: {summary['mean_sw_utilization']*100:.2f}% | Worker Move Frac: {summary['mean_worker_movement_fraction']*100:.2f}%")

    print("\n--- Paired Contrasts ---")
    for c_name, c_data in analysis["contrasts"].items():
        print(f"  {c_name} ({c_data['description']}):")
        print(f"    Mean Delta: {c_data['mean_delta']:+.2f} | Median: {c_data['median_delta']:+.2f} | Bootstrap 95% CI: [{c_data['bootstrap_95_ci'][0]:+.2f}, {c_data['bootstrap_95_ci'][1]:+.2f}]")
        print(f"    Paired t-test: t={c_data['t_statistic']:.3f}, p={c_data['p_value']:.4e} | Win Rate: {c_data['win_rate']*100:.1f}% ({c_data['wins']}W / {c_data['losses']}L / {c_data['ties']}T)")
        print(f"    P10: {c_data['p10_delta']:+.2f} | P90: {c_data['p90_delta']:+.2f} | CVaR (worst 10%): {c_data['cvar_10']:+.2f}")


if __name__ == "__main__":
    main()
