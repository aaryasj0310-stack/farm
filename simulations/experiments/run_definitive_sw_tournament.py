"""Definitive Corrected Southwest Expansion Tournament (Arms A, B, C, D).

Arms:
  - Arm A: Fresh Production Control (Current strategy with SW expansion disabled/frozen)
  - Arm B: Working SW + Discrete Activation (No progressive activation)
  - Arm C: Working SW + Survival-Aware Progressive Activation (Primary Treatment, no Dusta prior)
  - Arm D: Dusta Prior + Survival-Aware Progressive Activation (Differs from C by Dusta prior only)

Scenarios:
  - 50 paired matches per arm across identical seeds (Seeds 100..149) vs random opponent.
  - Exact final scores, bootstrap 95% CI, paired t-test, Wilcoxon signed-rank test,
    P10/P90, CVaR 10%, worst 5 deltas.
  - Complete SW occupancy, animal safety, labor, and revenue attribution telemetry.
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
    opp_name = payload.get("opponent", "random")

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
    from observation_parser import parse_observation

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    if hasattr(agent_module, "reset_daily_telemetry"):
        agent_module.reset_daily_telemetry()
    elif hasattr(agent_module, "reset_daily_log"):
        agent_module.reset_daily_log()

    # Configure Arm
    config.set_sw_experiment_arm(arm)

    # SW Purchase Telemetry
    sw_purchased = False
    sw_purchase_day = None
    sw_purchase_hour = None
    sw_purchase_step = None
    pre_buy_cash = None
    post_buy_cash = None
    post_buy_safe_headroom = None
    herd_at_purchase = None
    workers_at_purchase = None

    # SW Occupancy & Tile-Hour Tracking
    sw_occupancy_by_step = {}
    sw_crop_tiles_by_crop = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}
    sw_pasture_coop_tiles = 0
    sw_productive_actions = 0
    sw_movement_actions = 0
    sw_planted_unwatered_hours = 0
    sw_ripe_unharvested_hours = 0
    sw_productive_tile_hours = 0
    workers_in_sw_steps = []

    # Animal Safety Telemetry
    daily_unfed_animals = {}
    max_consecutive_unfed_seen = 0
    animals_consec_ge_2 = 0
    escaped_animals = 0
    prev_total_herd = 0
    feed_actions_completed_late = 0
    urgent_survival_preemptions = 0
    survival_assignment_contention = False
    survival_contention_events = []

    # Revenue Attribution Telemetry
    units_sold = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0, "EGG": 0, "MILK": 0, "WOOL": 0, "FERTILIZER": 0}
    rev_by_product = {k: 0.0 for k in units_sold}
    total_seed_cost = 0.0
    total_animal_cost = 0.0
    total_hire_cost = 0.0
    total_purchased_feed_cost = 0.0
    land_cost = 0.0

    # Labor Telemetry by Quadrant (NW, NE, SW, SE)
    quad_workers = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    quad_moves = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    quad_productive = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    quad_steps_count = 0

    last_money = 3000.0
    last_shed = {}

    def tracking_agent(obs, configuration=None):
        nonlocal sw_purchased, sw_purchase_day, sw_purchase_hour, sw_purchase_step
        nonlocal pre_buy_cash, post_buy_cash, post_buy_safe_headroom, herd_at_purchase, workers_at_purchase
        nonlocal sw_occupancy_by_step, sw_crop_tiles_by_crop, sw_pasture_coop_tiles
        nonlocal sw_productive_actions, sw_movement_actions, sw_planted_unwatered_hours
        nonlocal sw_ripe_unharvested_hours, sw_productive_tile_hours, workers_in_sw_steps
        nonlocal daily_unfed_animals, max_consecutive_unfed_seen, animals_consec_ge_2
        nonlocal escaped_animals, prev_total_herd, feed_actions_completed_late
        nonlocal urgent_survival_preemptions, survival_assignment_contention, survival_contention_events
        nonlocal units_sold, rev_by_product, total_seed_cost, total_animal_cost
        nonlocal total_hire_cost, total_purchased_feed_cost, land_cost
        nonlocal quad_workers, quad_moves, quad_productive, quad_steps_count
        nonlocal last_money, last_shed

        action = agent_module.agent(obs, configuration)
        step = obs.get("step", 0)
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        p_id = obs.get("player", 0)

        parsed = parse_observation(obs)
        if parsed is None:
            return action

        farm = parsed["farm"]
        private = parsed["private"]
        curr_money = farm.money

        # Track worker locations
        all_unit_positions = [farm.farmer] + farm.hands
        sw_worker_count = 0
        quad_steps_count += 1
        for upos in all_unit_positions:
            uq = farm.quadrant_of(upos)
            quad_workers[uq] = quad_workers.get(uq, 0) + 1
            if uq == "SW" and upos != (4, 5):
                sw_worker_count += 1
        workers_in_sw_steps.append(sw_worker_count)

        # Track actions
        farmer_act = action.get("farmer", ["PASS"])
        hands_act = action.get("hands", [])
        all_actions = [farmer_act] + hands_act

        for u_idx, act in enumerate(all_actions):
            if not act:
                continue
            act_type = act[0]
            upos = all_unit_positions[u_idx] if u_idx < len(all_unit_positions) else (4, 4)
            uq = farm.quadrant_of(upos)

            if act_type in ("NORTH", "SOUTH", "EAST", "WEST"):
                quad_moves[uq] = quad_moves.get(uq, 0) + 1
                if uq == "SW":
                    sw_movement_actions += 1
            elif act_type not in ("PASS",):
                quad_productive[uq] = quad_productive.get(uq, 0) + 1
                if uq == "SW":
                    sw_productive_actions += 1

            if act_type == "FEED":
                if hour >= 14:
                    feed_actions_completed_late += 1

        # Track market purchases from action
        for m_order in action.get("market", []):
            if not m_order:
                continue
            otype = m_order[0]
            if otype == "BUY_LAND":
                n_unlocked = len(farm.unlocked)
                if n_unlocked == 1:
                    land_cost += 1000.0
                elif n_unlocked == 2:
                    land_cost += 2000.0
            elif otype == "BUY_SEED":
                crop = m_order[1]
                qty = m_order[2]
                price = config.CROPS[crop]["seed"]
                total_seed_cost += price * qty
            elif otype == "BUY_ANIMAL":
                animal = m_order[1]
                price = config.ANIMALS[animal]["cost"]
                total_animal_cost += price
            elif otype == "BUY_PRODUCT":
                prod = m_order[1]
                qty = m_order[2]
                if prod == "WHEAT":
                    m_price = parsed["market"].prices.get("WHEAT", 25)
                    total_purchased_feed_cost += m_price * qty

        # Track hires cost at hour 0
        if hour == 0 and farm.hires_today > 0:
            from config import get_hire_cost
            curr_hands = len(farm.hands)
            for h_idx in range(curr_hands, curr_hands + farm.hires_today):
                total_hire_cost += get_hire_cost(h_idx)

        # Count animals and SW tiles
        placed_animals = 0
        unfed_count = 0
        sw_active_tiles = 0
        unfed_reachabilities = []

        for t in farm.iter_tiles():
            if t.is_animal:
                placed_animals += 1
                consec = t.consecutive_unfed
                if consec > max_consecutive_unfed_seen:
                    max_consecutive_unfed_seen = consec
                if consec >= 2:
                    animals_consec_ge_2 += 1
                if not t.fed_today:
                    unfed_count += 1
                    min_d = min(abs(t.x - up[0]) + abs(t.y - up[1]) for up in all_unit_positions)
                    turns_left = 24 - hour
                    unfed_reachabilities.append(min_d <= turns_left)

            if farm.quadrant_of(t.pos) == "SW" and t.pos != (4, 5):
                is_plant = getattr(t, "is_plant", False) or t.crop is not None
                is_anim = t.is_animal or t.kind in ("PASTURE", "COOP")
                if is_plant or is_anim:
                    sw_active_tiles += 1
                    sw_productive_tile_hours += 1

                if is_plant:
                    if t.crop in sw_crop_tiles_by_crop:
                        sw_crop_tiles_by_crop[t.crop] = max(sw_crop_tiles_by_crop[t.crop], 1)
                    if hour == 23 and not t.watered_today:
                        sw_planted_unwatered_hours += 1
                    if t.yield_units > 0:
                        sw_ripe_unharvested_hours += 1
                elif is_anim:
                    sw_pasture_coop_tiles = max(sw_pasture_coop_tiles, 1)

        held_animals = sum(int(inv.get(a, 0)) for inv in private.inventories for a in ("COW", "SHEEP", "GOOSE"))
        shed_animals = sum(int(private.shed.get(a, 0)) for a in ("COW", "SHEEP", "GOOSE"))
        total_herd = placed_animals + held_animals + shed_animals

        # SW purchase event detection
        if "SW" in farm.unlocked and not sw_purchased:
            sw_purchased = True
            sw_purchase_day = day
            sw_purchase_hour = hour
            sw_purchase_step = step
            pre_buy_cash = last_money
            post_buy_cash = curr_money
            herd_at_purchase = total_herd
            workers_at_purchase = len(all_unit_positions)

            last_tel = agent_module.get_last_turn_telemetry()
            if last_tel and "macro_plan_diagnostic" in last_tel:
                mp_diag = last_tel["macro_plan_diagnostic"] or {}
                ld = mp_diag.get("land_decision", {})
                post_buy_safe_headroom = ld.get("post_sw_cash_minus_obligations", post_buy_cash - 300.0)
            else:
                post_buy_safe_headroom = post_buy_cash - 300.0

        if sw_purchased:
            sw_occupancy_by_step[step] = sw_active_tiles

        # End of day checks
        if hour == 23:
            daily_unfed_animals[day] = unfed_count
            if prev_total_herd > 0 and total_herd < prev_total_herd:
                lost = prev_total_herd - total_herd
                escaped_animals += lost
            prev_total_herd = total_herd

            # Check SURVIVAL_ASSIGNMENT_CONTENTION:
            if unfed_count > 1 and all(unfed_reachabilities):
                survival_assignment_contention = True
                survival_contention_events.append({
                    "day": day,
                    "unfed_count": unfed_count,
                    "worker_count": len(all_unit_positions),
                })

        # Track market sales & revenues
        curr_shed = private.shed
        dm = curr_money - last_money
        if dm > 0:
            sold = {k: last_shed.get(k, 0) - curr_shed.get(k, 0) for k in last_shed if last_shed.get(k, 0) > curr_shed.get(k, 0)}
            if len(sold) == 1:
                item = list(sold.keys())[0]
                qty = sold[item]
                if item in rev_by_product:
                    units_sold[item] += qty
                    rev_by_product[item] += dm
            elif len(sold) > 1:
                base_prices = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
                total_base = sum(base_prices.get(k, 25) * qty for k, qty in sold.items())
                for item, qty in sold.items():
                    if item in rev_by_product:
                        share = (base_prices.get(item, 25) * qty) / max(1.0, total_base)
                        units_sold[item] += qty
                        rev_by_product[item] += dm * share

        last_money = curr_money
        last_shed = dict(curr_shed)
        return action

    env = make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720}, debug=True)
    env.run([tracking_agent, opp_name])
    final_score = float(env.steps[-1][0].observation["farms"][0]["money"])

    # Compute progressive occupancy at benchmarks
    benchmarks = {"plus_6h": 0.0, "plus_12h": 0.0, "plus_24h": 0.0, "plus_48h": 0.0, "plus_72h": 0.0}
    if sw_purchased and sw_purchase_step is not None:
        for offset, key in ((6, "plus_6h"), (12, "plus_12h"), (24, "plus_24h"), (48, "plus_48h"), (72, "plus_72h")):
            target_s = min(719, sw_purchase_step + offset)
            benchmarks[key] = float(sw_occupancy_by_step.get(target_s, 0.0))

    crop_rev = sum(rev_by_product[c] for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"))
    animal_rev = sum(rev_by_product[a] for a in ("MILK", "WOOL", "EGG"))
    fert_rev = rev_by_product.get("FERTILIZER", 0.0)

    avg_workers_in_sw = float(np.mean(workers_in_sw_steps)) if workers_in_sw_steps else 0.0
    peak_workers_in_sw = max(workers_in_sw_steps) if workers_in_sw_steps else 0

    return {
        "arm": arm,
        "seed": seed,
        "opponent": opp_name,
        "final_score": final_score,
        # SW Purchase
        "sw_purchased": sw_purchased,
        "sw_purchase_day": sw_purchase_day,
        "sw_purchase_hour": sw_purchase_hour,
        "sw_purchase_step": sw_purchase_step,
        "pre_buy_cash": pre_buy_cash,
        "post_buy_cash": post_buy_cash,
        "post_buy_safe_headroom": post_buy_safe_headroom,
        "herd_at_purchase": herd_at_purchase,
        "workers_at_purchase": workers_at_purchase,
        # Occupancy Benchmarks
        "occupancy_benchmarks": benchmarks,
        "sw_occupancy_by_step": sw_occupancy_by_step,
        "sw_crop_tiles_by_crop": sw_crop_tiles_by_crop,
        "sw_pasture_coop_tiles": sw_pasture_coop_tiles,
        "avg_workers_in_sw": round(avg_workers_in_sw, 2),
        "peak_workers_in_sw": peak_workers_in_sw,
        "sw_productive_actions": sw_productive_actions,
        "sw_movement_actions": sw_movement_actions,
        "sw_planted_unwatered_hours": sw_planted_unwatered_hours,
        "sw_ripe_unharvested_hours": sw_ripe_unharvested_hours,
        "sw_productive_tile_hours": sw_productive_tile_hours,
        # Animal Safety
        "total_unfed_animal_days": sum(daily_unfed_animals.values()),
        "daily_unfed_animals": daily_unfed_animals,
        "max_consecutive_unfed": max_consecutive_unfed_seen,
        "animals_consec_ge_2": animals_consec_ge_2,
        "escapes": escaped_animals,
        "feed_actions_completed_late": feed_actions_completed_late,
        "urgent_survival_preemptions": urgent_survival_preemptions,
        "survival_assignment_contention": survival_assignment_contention,
        "survival_contention_events": survival_contention_events,
        # Production Units
        "units_sold": units_sold,
        "milk_units": units_sold.get("MILK", 0),
        "wool_units": units_sold.get("WOOL", 0),
        "egg_units": units_sold.get("EGG", 0),
        "fertilizer_collected": units_sold.get("FERTILIZER", 0),
        # Revenues & Costs
        "rev_by_product": rev_by_product,
        "crop_revenue": round(crop_rev, 2),
        "livestock_revenue": round(animal_rev, 2),
        "fertilizer_revenue": round(fert_rev, 2),
        "land_cost": round(land_cost, 2),
        "seed_cost": round(total_seed_cost, 2),
        "animal_purchase_cost": round(total_animal_cost, 2),
        "hire_cost": round(total_hire_cost, 2),
        "purchased_feed_cost": round(total_purchased_feed_cost, 2),
        # Labor
        "quad_workers": quad_workers,
        "quad_moves": quad_moves,
        "quad_productive": quad_productive,
        "quad_steps_count": quad_steps_count,
    }


def analyze_tournament_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform rigorous paired statistical analysis and telemetry synthesis across arms."""
    by_arm: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        by_arm.setdefault(r["arm"], []).append(r)

    arm_summaries = {}
    for arm, arm_res in by_arm.items():
        scores = [r["final_score"] for r in arm_res]
        sw_bought = [r for r in arm_res if r["sw_purchased"]]
        sw_rate = len(sw_bought) / len(arm_res) if arm_res else 0.0

        sw_days = [r["sw_purchase_day"] for r in sw_bought if r["sw_purchase_day"] is not None]
        sw_hours = [r["sw_purchase_hour"] for r in sw_bought if r["sw_purchase_hour"] is not None]
        pre_cash = [r["pre_buy_cash"] for r in sw_bought if r["pre_buy_cash"] is not None]
        post_cash = [r["post_buy_cash"] for r in sw_bought if r["post_buy_cash"] is not None]
        headroom = [r["post_buy_safe_headroom"] for r in sw_bought if r["post_buy_safe_headroom"] is not None]
        herds = [r["herd_at_purchase"] for r in sw_bought if r["herd_at_purchase"] is not None]
        workers = [r["workers_at_purchase"] for r in sw_bought if r["workers_at_purchase"] is not None]

        bench_6 = [r["occupancy_benchmarks"]["plus_6h"] for r in sw_bought]
        bench_12 = [r["occupancy_benchmarks"]["plus_12h"] for r in sw_bought]
        bench_24 = [r["occupancy_benchmarks"]["plus_24h"] for r in sw_bought]
        bench_48 = [r["occupancy_benchmarks"]["plus_48h"] for r in sw_bought]
        bench_72 = [r["occupancy_benchmarks"]["plus_72h"] for r in sw_bought]

        arm_summaries[arm] = {
            "num_matches": len(arm_res),
            "mean_score": round(float(np.mean(scores)), 2),
            "median_score": round(float(np.median(scores)), 2),
            "std_score": round(float(np.std(scores)), 2),
            "min_score": round(float(np.min(scores)), 2),
            "max_score": round(float(np.max(scores)), 2),
            # SW Purchase Stats
            "sw_purchase_rate": round(sw_rate, 4),
            "sw_purchase_count": len(sw_bought),
            "mean_sw_purchase_day": round(float(np.mean(sw_days)), 2) if sw_days else None,
            "median_sw_purchase_day": round(float(np.median(sw_days)), 2) if sw_days else None,
            "mean_sw_purchase_hour": round(float(np.mean(sw_hours)), 2) if sw_hours else None,
            "mean_pre_buy_cash": round(float(np.mean(pre_cash)), 2) if pre_cash else None,
            "median_pre_buy_cash": round(float(np.median(pre_cash)), 2) if pre_cash else None,
            "mean_post_buy_cash": round(float(np.mean(post_cash)), 2) if post_cash else None,
            "median_post_buy_cash": round(float(np.median(post_cash)), 2) if post_cash else None,
            "mean_safe_headroom": round(float(np.mean(headroom)), 2) if headroom else None,
            "mean_herd_at_purchase": round(float(np.mean(herds)), 2) if herds else None,
            "mean_workers_at_purchase": round(float(np.mean(workers)), 2) if workers else None,
            # Occupancy benchmarks
            "occupancy_benchmarks": {
                "plus_6h": round(float(np.mean(bench_6)), 2) if bench_6 else 0.0,
                "plus_12h": round(float(np.mean(bench_12)), 2) if bench_12 else 0.0,
                "plus_24h": round(float(np.mean(bench_24)), 2) if bench_24 else 0.0,
                "plus_48h": round(float(np.mean(bench_48)), 2) if bench_48 else 0.0,
                "plus_72h": round(float(np.mean(bench_72)), 2) if bench_72 else 0.0,
            },
            # SW Utilization
            "mean_sw_productive_actions": round(float(np.mean([r["sw_productive_actions"] for r in arm_res])), 2),
            "mean_sw_movement_actions": round(float(np.mean([r["sw_movement_actions"] for r in arm_res])), 2),
            "mean_sw_planted_unwatered_hours": round(float(np.mean([r["sw_planted_unwatered_hours"] for r in arm_res])), 2),
            "mean_sw_ripe_unharvested_hours": round(float(np.mean([r["sw_ripe_unharvested_hours"] for r in arm_res])), 2),
            "mean_sw_productive_tile_hours": round(float(np.mean([r["sw_productive_tile_hours"] for r in arm_res])), 2),
            "mean_workers_in_sw": round(float(np.mean([r["avg_workers_in_sw"] for r in arm_res])), 2),
            # Animal Safety
            "total_escapes": sum(r["escapes"] for r in arm_res),
            "mean_escapes_per_match": round(float(np.mean([r["escapes"] for r in arm_res])), 4),
            "max_consecutive_unfed_seen": max(r["max_consecutive_unfed"] for r in arm_res),
            "total_animals_consec_ge_2": sum(r["animals_consec_ge_2"] for r in arm_res),
            "mean_unfed_animal_days": round(float(np.mean([r["total_unfed_animal_days"] for r in arm_res])), 2),
            "mean_late_feed_actions": round(float(np.mean([r["feed_actions_completed_late"] for r in arm_res])), 2),
            "total_contention_events": sum(len(r["survival_contention_events"]) for r in arm_res),
            # Production Units & Revenues
            "mean_milk_units": round(float(np.mean([r["milk_units"] for r in arm_res])), 2),
            "mean_wool_units": round(float(np.mean([r["wool_units"] for r in arm_res])), 2),
            "mean_egg_units": round(float(np.mean([r["egg_units"] for r in arm_res])), 2),
            "mean_fert_collected": round(float(np.mean([r["fertilizer_collected"] for r in arm_res])), 2),
            "mean_crop_revenue": round(float(np.mean([r["crop_revenue"] for r in arm_res])), 2),
            "mean_livestock_revenue": round(float(np.mean([r["livestock_revenue"] for r in arm_res])), 2),
            "mean_fertilizer_revenue": round(float(np.mean([r["fertilizer_revenue"] for r in arm_res])), 2),
            # Expenses
            "mean_land_cost": round(float(np.mean([r["land_cost"] for r in arm_res])), 2),
            "mean_seed_cost": round(float(np.mean([r["seed_cost"] for r in arm_res])), 2),
            "mean_animal_cost": round(float(np.mean([r["animal_purchase_cost"] for r in arm_res])), 2),
            "mean_hire_cost": round(float(np.mean([r["hire_cost"] for r in arm_res])), 2),
            "mean_feed_cost": round(float(np.mean([r["purchased_feed_cost"] for r in arm_res])), 2),
        }

    paired_comparisons = [
        ("C_vs_A_Primary", "ArmC_Primary_Progressive", "ArmA_Control_Frozen", "Primary Treatment: Survival Progressive vs No-SW Control"),
        ("B_vs_A", "ArmB_Liquidity_Discrete", "ArmA_Control_Frozen", "Discrete SW vs No-SW Control"),
        ("C_vs_B", "ArmC_Primary_Progressive", "ArmB_Liquidity_Discrete", "Progressive vs Discrete SW"),
        ("D_vs_C", "ArmD_DustaPrior_Progressive", "ArmC_Primary_Progressive", "Dusta Prior vs No-Prior Progressive"),
        ("D_vs_A", "ArmD_DustaPrior_Progressive", "ArmA_Control_Frozen", "Dusta Prior Progressive vs No-SW Control"),
    ]

    contrasts = {}
    for comp_id, t_name, c_name, desc in paired_comparisons:
        if t_name not in by_arm or c_name not in by_arm:
            continue
        t_by_seed = {r["seed"]: r for r in by_arm[t_name]}
        c_by_seed = {r["seed"]: r for r in by_arm[c_name]}
        common_seeds = sorted(set(t_by_seed.keys()) & set(c_by_seed.keys()))

        if not common_seeds:
            continue

        deltas = np.array([t_by_seed[s]["final_score"] - c_by_seed[s]["final_score"] for s in common_seeds])
        mean_d = float(np.mean(deltas))
        med_d = float(np.median(deltas))
        std_d = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else 0.0

        t_stat, p_val = stats.ttest_1samp(deltas, 0.0) if len(deltas) > 1 else (0.0, 1.0)

        try:
            nonzero_deltas = deltas[deltas != 0]
            if len(nonzero_deltas) > 0:
                w_stat, w_pval = stats.wilcoxon(deltas)
            else:
                w_stat, w_pval = 0.0, 1.0
        except Exception:
            w_stat, w_pval = 0.0, 1.0

        np.random.seed(42)
        n_boot = 10000
        boot_means = np.empty(n_boot)
        for b in range(n_boot):
            boot_means[b] = np.mean(np.random.choice(deltas, size=len(deltas), replace=True))
        ci_lower = float(np.percentile(boot_means, 2.5))
        ci_upper = float(np.percentile(boot_means, 97.5))

        wins = int(np.sum(deltas > 0))
        ties = int(np.sum(deltas == 0))
        losses = int(np.sum(deltas < 0))
        win_pct = round(wins / len(deltas) * 100.0, 1)
        tie_pct = round(ties / len(deltas) * 100.0, 1)
        loss_pct = round(losses / len(deltas) * 100.0, 1)

        p10 = float(np.percentile(deltas, 10))
        p90 = float(np.percentile(deltas, 90))

        paired_records = []
        for s in common_seeds:
            d_val = round(float(t_by_seed[s]["final_score"] - c_by_seed[s]["final_score"]), 1)
            paired_records.append({
                "seed": s,
                "delta": d_val,
                "treatment_score": round(t_by_seed[s]["final_score"], 1),
                "control_score": round(c_by_seed[s]["final_score"], 1),
                "treatment_sw_bought": t_by_seed[s]["sw_purchased"],
            })
        paired_records.sort(key=lambda x: x["delta"])
        worst_5 = paired_records[:5]

        n_worst = max(1, int(math.ceil(len(deltas) * 0.10)))
        cvar_10 = float(np.mean(np.sort(deltas)[:n_worst]))

        contrasts[comp_id] = {
            "description": desc,
            "treatment": t_name,
            "control": c_name,
            "num_pairs": len(deltas),
            "mean_delta": round(mean_d, 2),
            "median_delta": round(med_d, 2),
            "std_delta": round(std_d, 2),
            "bootstrap_95_ci": [round(ci_lower, 2), round(ci_upper, 2)],
            "t_statistic": round(float(t_stat), 4),
            "p_value": float(p_val),
            "wilcoxon_statistic": round(float(w_stat), 4),
            "wilcoxon_p_value": float(w_pval),
            "win_percentage": win_pct,
            "tie_percentage": tie_pct,
            "loss_percentage": loss_pct,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "p10_delta": round(p10, 2),
            "p90_delta": round(p90, 2),
            "cvar_10": round(cvar_10, 2),
            "worst_5_outcomes": worst_5,
        }

    return {
        "arm_summaries": arm_summaries,
        "contrasts": contrasts,
    }


def main():
    parser = argparse.ArgumentParser(description="Definitive SW Expansion Tournament")
    parser.add_argument("--num-seeds", type=int, default=50, help="Number of seeds per arm (default: 50)")
    parser.add_argument("--start-seed", type=int, default=100, help="Starting seed (default: 100)")
    parser.add_argument("--max-workers", type=int, default=8, help="Number of parallel worker processes (default: 8)")
    parser.add_argument("--output", type=str, default="simulations/experiments/results/definitive_sw_tournament_results.json")
    args = parser.parse_args()

    arms = [
        "ArmA_Control_Frozen",
        "ArmB_Liquidity_Discrete",
        "ArmC_Primary_Progressive",
        "ArmD_DustaPrior_Progressive",
    ]
    seeds = list(range(args.start_seed, args.start_seed + args.num_seeds))

    payloads = []
    for s in seeds:
        for arm in arms:
            payloads.append({
                "arm": arm,
                "seed": s,
                "opponent": "random",
            })

    print(f"================================================================================")
    print(f"        DEFINITIVE SOUTHWEST EXPANSION TOURNAMENT (STAGE 1: 50 PAIRED)          ")
    print(f"================================================================================")
    print(f"  Arms: {arms}")
    print(f"  Seeds: {len(seeds)} (Seeds {seeds[0]}..{seeds[-1]})")
    print(f"  Total Matches: {len(payloads)}")
    print(f"  Parallel Workers: {args.max_workers}")
    print(f"================================================================================\n", flush=True)

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
                print(f"  [{completed}/{total}] {completed/total*100:5.1f}% | Elapsed: {elapsed:5.1f}s | Rate: {rate:4.1f} match/s | ETA: {rem:5.1f}s", flush=True)

    print(f"\nAnalyzing tournament results across {len(results)} matches...", flush=True)
    analysis = analyze_tournament_results(results)

    out_data = {
        "metadata": {
            "num_seeds": args.num_seeds,
            "start_seed": args.start_seed,
            "total_matches": len(results),
            "runtime_seconds": round(time.time() - t0, 2),
            "arms": arms,
        },
        "analysis": analysis,
        "raw_results": results,
    }

    out_path = os.path.join(_REPO_ROOT, args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)

    print(f"Results successfully saved to: {out_path}\n")

    print("==================================================================================")
    print("                               ARM SCORE SUMMARIES                                ")
    print("==================================================================================")
    print(f"{'Arm':<28} | {'Mean':<10} | {'Median':<10} | {'Std':<8} | {'SW Buy':<8} | {'Escapes':<8}")
    print("-" * 82)
    for arm, s in analysis["arm_summaries"].items():
        sw_str = f"{s['sw_purchase_count']}/{s['num_matches']}"
        print(f"{arm:<28} | ${s['mean_score']:<9.1f} | ${s['median_score']:<9.1f} | ${s['std_score']:<7.1f} | {sw_str:<8} | {s['total_escapes']:<8}")
    print("==================================================================================\n")

    print("==================================================================================")
    print("                                PAIRED CONTRASTS                                  ")
    print("==================================================================================")
    print(f"{'Contrast':<18} | {'Mean Delta':<11} | {'Median Delta':<12} | {'95% Bootstrap CI':<20} | {'p-val':<8} | {'Win %':<6}")
    print("-" * 84)
    for cid, c in analysis["contrasts"].items():
        ci_str = f"[{c['bootstrap_95_ci'][0]:+.1f}, {c['bootstrap_95_ci'][1]:+.1f}]"
        print(f"{cid:<18} | ${c['mean_delta']:<10.1f} | ${c['median_delta']:<11.1f} | {ci_str:<20} | {c['p_value']:<8.4f} | {c['win_percentage']:<5.1f}%")
    print("==================================================================================\n")


if __name__ == "__main__":
    main()
