#!/usr/bin/env python3
"""Kaggriculture P5.1-C — Causal Delta Reconciliation Harness.

Runs 100 matched pairs (200 live games) on the discovery panel:
Seeds 96,201–96,210 (10 seeds) x 5 Opponents x 2 Seats = 100 Matched Pairs.
Control: Baseline commit 536f1e7 (P51_T1_TWO_CYCLE_CARROT_ENABLED = False)
Treatment: P5.1 (P51_T1_TWO_CYCLE_CARROT_ENABLED = True)

Objectives:
1. Exact market/cash transaction interception:
   - Every SELL, BUY_PRODUCT, BUY_SEED, BUY_ANIMAL, HIRE, and BUY_LAND
   - 100% exact cash reconciliation: Starting ($3,000) + Sells - Buys - Hires - Land == Final Cash (0.0 error)
   - Category-by-category Treatment - Control cash flow decomposition reproducing -$1,020.68/game delta
2. Worker-action telemetry:
   - Emitted & executed actions classified across all operations, crops, and livestock species
   - Comparison across full season and Days 21–29 window
3. Crop production lifecycle:
   - Plantings, waterings, fertilizer, harvests, weed deaths, decay losses, unharvested end yield
4. Livestock production lifecycle:
   - Animals placed, fed, cared, production events, harvests, escapes, surviving end count
5. Market-order arbitration:
   - Turns exceeding 10-order cap, slot-cap rejections, products dropped
6. Market price / absorption analysis:
   - Units sold, mean/median prices, revenue per product, market inventory before/after
7. Inventory & shed dynamics:
   - Shed discarded overflow, final shed inventory, final worker inventory
8. Two-cycle rotation metrics (Treatment):
   - C1/C2 plant/water/harvest completion rates
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import gzip
import json
import math
import os
import sys
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

BASELINE_SHA = "536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e"
OPPONENTS = [
    "pass",
    "pure_wheat_rush",
    "cow_milk_engine",
    "melon_sniper",
    "full_production_agent",
]
DIAGNOSTIC_SEEDS = list(range(96201, 96211))  # Seeds 96,201–96,210

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
CROPS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
ANIMALS = ["COW", "SHEEP", "GOOSE"]


def _run_instrumented_game(seed, opponent, seat, enable_p51):
    """Runs a single instrumented simulation game and extracts comprehensive telemetry."""
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    agent_dir = os.path.join(ROOT, "agent")
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
            "two_cycle_rotation_manager", "expansion_planner", "price_math", "price_forecast", "endgame_liquidator",
        )):
            del sys.modules[key]

    import kaggle_environments
    import kaggle_environments.envs.kaggriculture.kaggriculture as kg
    import main as module
    import config as cfg
    import simulations.experiments.audit_p50r_telemetry as apt
    from simulations.experiments.agent_zoo import get_agent
    from strategy.two_cycle_rotation_manager import get_rotation_manager, reset_rotation_manager

    apt._configure_baseline(cfg)
    cfg.set_p51_t1_two_cycle_carrot_enabled(enable_p51)
    module.reset_agent_state()
    reset_rotation_manager()

    opp_agent = get_agent(opponent)
    players = [module.agent, opp_agent] if seat == 0 else [opp_agent, module.agent]

    # Telemetry storage
    cash_ledger = {
        "starting_cash": 3000.0,
        "sells": defaultdict(lambda: {"units": 0, "revenue": 0.0, "prices": []}),
        "buys_product": defaultdict(lambda: {"units": 0, "cost": 0.0, "prices": []}),
        "buys_seed": defaultdict(lambda: {"units": 0, "cost": 0.0, "prices": []}),
        "buys_animal": defaultdict(lambda: {"units": 0, "cost": 0.0, "prices": []}),
        "hires": {"count": 0, "cost": 0.0},
        "land": {"count": 0, "cost": 0.0, "quadrants": []},
    }

    worker_actions = {
        "all_season": defaultdict(int),
        "days_21_29": defaultdict(int),
    }

    crop_lifecycle = {
        c: {
            "planted": 0,
            "watered": 0,
            "fertilized": 0,
            "harvested_events": 0,
            "harvested_units": 0,
            "weed_deaths": 0,
            "decay_lost_units": 0,
            "unharvested_end_units": 0,
        } for c in CROPS
    }

    livestock_lifecycle = {
        a: {
            "placed": 0,
            "fed": 0,
            "cared": 0,
            "production_events": 0,
            "units_produced": 0,
            "harvested_events": 0,
            "harvested_units": 0,
            "escapes": 0,
            "surviving_end": 0,
        } for a in ANIMALS
    }
    fertilizer_events = {"produced": 0, "collected": 0}

    market_arbitration = {
        "turns_with_market_orders": 0,
        "turns_exceeding_10_cap": 0,
        "total_candidate_orders": 0,
        "emitted_orders": 0,
        "slot_cap_dropped_orders": 0,
        "dropped_by_product": defaultdict(int),
    }

    inventory_dynamics = {
        "discarded_overflow": defaultdict(int),
        "final_shed": {},
        "final_worker_inv": {},
        "day29_harvest_units": defaultdict(int),
        "day29_sold_units": defaultdict(int),
    }

    cur_p0_farm = None
    cur_p0_priv = None
    cur_step_info = {"step": 0, "day": 0, "hour": 0}

    # Intercept _process_market for exact per-unit financial transactions and slot cap monitoring
    orig_process_market = kg._process_market
    def tracked_process_market(state, env):
        nonlocal cur_p0_farm, cur_p0_priv
        step = int(state[0].observation.get("step", 0))
        day = step // 24
        hour = step % 24
        cur_step_info["step"] = step
        cur_step_info["day"] = day
        cur_step_info["hour"] = hour

        obs0 = state[0].observation
        cur_p0_farm = obs0.farms[0]
        cur_p0_priv = state[0].observation.private

        # Monitor market orders proposed by our player
        our_action = state[seat].action if isinstance(state[seat].action, dict) else {}
        our_orders = our_action.get("market", []) if isinstance(our_action, dict) else []
        if isinstance(our_orders, list) and len(our_orders) > 0:
            market_arbitration["turns_with_market_orders"] += 1
            market_arbitration["total_candidate_orders"] += len(our_orders)
            market_arbitration["emitted_orders"] += min(len(our_orders), 10)
            if len(our_orders) > 10:
                market_arbitration["turns_exceeding_10_cap"] += 1
                dropped = len(our_orders) - 10
                market_arbitration["slot_cap_dropped_orders"] += dropped
                for order in our_orders[10:]:
                    parts = order.split() if isinstance(order, str) else []
                    item_name = parts[1] if len(parts) > 1 else "UNKNOWN"
                    market_arbitration["dropped_by_product"][item_name] += 1

        orig_commit_unit = kg._commit_unit
        def tracked_commit_unit(op, item, price, farm, private, market, shed_capacity=100):
            ok = orig_commit_unit(op, item, price, farm, private, market, shed_capacity)
            if ok:
                pid = 0 if (private is cur_p0_priv) else 1
                if pid == seat:
                    p = float(price)
                    if op == "SELL":
                        cash_ledger["sells"][item]["units"] += 1
                        cash_ledger["sells"][item]["revenue"] += p
                        cash_ledger["sells"][item]["prices"].append(p)
                        if day == 29:
                            inventory_dynamics["day29_sold_units"][item] += 1
                    elif op == "BUY_PRODUCT":
                        cash_ledger["buys_product"][item]["units"] += 1
                        cash_ledger["buys_product"][item]["cost"] += p
                        cash_ledger["buys_product"][item]["prices"].append(p)
                    elif op == "BUY_SEED":
                        cash_ledger["buys_seed"][item]["units"] += 1
                        cash_ledger["buys_seed"][item]["cost"] += p
                        cash_ledger["buys_seed"][item]["prices"].append(p)
                    elif op == "BUY_ANIMAL":
                        cash_ledger["buys_animal"][item]["units"] += 1
                        cash_ledger["buys_animal"][item]["cost"] += p
                        cash_ledger["buys_animal"][item]["prices"].append(p)
            return ok

        orig_do_hire = kg._do_hire
        def tracked_do_hire(farm, private, board_size, mult=kg.FARM_HAND_COST_MULT):
            cost = kg._hire_cost(farm["hires_today"], mult)
            before_money = farm["money"]
            orig_do_hire(farm, private, board_size, mult)
            if farm["money"] < before_money:
                pid = 0 if (private is cur_p0_priv) else 1
                if pid == seat:
                    cash_ledger["hires"]["count"] += 1
                    cash_ledger["hires"]["cost"] += float(cost)

        orig_do_buy_land = kg._do_buy_land
        def tracked_do_buy_land(farm, board_size):
            before_unlocked = len(farm["unlocked_quadrants"])
            before_money = farm["money"]
            orig_do_buy_land(farm, board_size)
            if len(farm["unlocked_quadrants"]) > before_unlocked:
                pid = 0 if (farm is cur_p0_farm) else 1
                if pid == seat:
                    paid = float(before_money - farm["money"])
                    quadrant = farm["unlocked_quadrants"][-1]
                    cash_ledger["land"]["count"] += 1
                    cash_ledger["land"]["cost"] += paid
                    cash_ledger["land"]["quadrants"].append(quadrant)

        kg._commit_unit = tracked_commit_unit
        kg._do_hire = tracked_do_hire
        kg._do_buy_land = tracked_do_buy_land
        try:
            orig_process_market(state, env)
        finally:
            kg._commit_unit = orig_commit_unit
            kg._do_hire = orig_do_hire
            kg._do_buy_land = orig_do_buy_land

    cur_unit_pid = 1
    cur_anim_pid = 1
    cur_plant_pid = 1
    cur_decay_pid = 1
    cur_drop_pid = 1

    # Intercept _apply_unit_action for worker activities and crop/livestock lifecycle events
    orig_apply_unit = kg._apply_unit_action
    def tracked_apply_unit(farm, private, unit_idx, action, board_size, day, turns_per_day, shed_capacity):
        nonlocal cur_unit_pid
        if unit_idx == 0:
            cur_unit_pid = 1 - cur_unit_pid

        is_us = (cur_unit_pid == seat)
        if is_us and isinstance(action, list) and len(action) > 0:
            op = action[0]
            pos = tuple(farm["farmer"]) if unit_idx == 0 else tuple(farm["hands"][unit_idx - 1])
            fx, fy = pos
            tile = farm["tiles"][fy][fx]
            step = day * turns_per_day + (cur_step_info.get("hour", 0))

            detail = op
            if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                detail = f"MOVE_{op}"
            elif op == "PASS":
                detail = "PASS"
            elif op == "PLANT":
                crop = action[1] if len(action) > 1 else "UNKNOWN"
                detail = f"PLANT_{crop}"
                if tile is None and private["seeds"].get(crop, 0) > 0:
                    crop_lifecycle[crop]["planted"] += 1
            elif op == "WATER":
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop = tile.get("crop", "UNKNOWN")
                    detail = f"WATER_{crop}"
                    if not tile["watered_today"]:
                        crop_lifecycle[crop]["watered"] += 1
            elif op == "HARVEST":
                if isinstance(tile, dict):
                    if tile.get("kind") == "PLANT":
                        crop = tile.get("crop", "UNKNOWN")
                        detail = f"HARVEST_CROP_{crop}"
                        y_units = tile.get("yield_units", 0)
                        if y_units > 0:
                            crop_lifecycle[crop]["harvested_events"] += 1
                            crop_lifecycle[crop]["harvested_units"] += y_units
                            if day == 29:
                                inventory_dynamics["day29_harvest_units"][crop] += y_units
                    elif "animal" in tile:
                        anim = tile.get("animal", "UNKNOWN")
                        detail = f"HARVEST_ANIMAL_{anim}"
                        y_units = tile.get("yield_units", 0)
                        if y_units > 0:
                            livestock_lifecycle[anim]["harvested_events"] += 1
                            livestock_lifecycle[anim]["harvested_units"] += y_units
                            if day == 29:
                                inventory_dynamics["day29_harvest_units"][kg.ANIMALS[anim]["product"]] += y_units
            elif op == "FEED":
                if isinstance(tile, dict) and "animal" in tile:
                    anim = tile.get("animal", "UNKNOWN")
                    detail = f"FEED_{anim}"
                    if not tile["fed_today"]:
                        livestock_lifecycle[anim]["fed"] += 1
            elif op == "CARE":
                if isinstance(tile, dict) and "animal" in tile:
                    anim = tile.get("animal", "UNKNOWN")
                    detail = f"CARE_{anim}"
                    if not tile["cared_today"]:
                        livestock_lifecycle[anim]["cared"] += 1
            elif op == "COLLECT_FERTILIZER":
                detail = "COLLECT_FERTILIZER"
                if isinstance(tile, dict) and "animal" in tile and tile.get("fertilizer_available", False):
                    fertilizer_events["collected"] += 1
            elif op == "FERTILIZE":
                detail = "FERTILIZE"
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop = tile.get("crop", "UNKNOWN")
                    crop_lifecycle[crop]["fertilized"] += 1
            elif op in ("PICKUP", "PLACE", "DROP", "BUILD_PASTURE", "BUILD_COOP", "DIG"):
                detail = op

            worker_actions["all_season"][detail] += 1
            if day >= 21:
                worker_actions["days_21_29"][detail] += 1

        orig_apply_unit(farm, private, unit_idx, action, board_size, day, turns_per_day, shed_capacity)

    # Intercept _daily_refresh_animals for animal escapes and production ticks
    orig_daily_animals = kg._daily_refresh_animals
    def tracked_daily_animals(farm, day):
        nonlocal cur_anim_pid
        cur_anim_pid = 1 - cur_anim_pid
        is_us = (cur_anim_pid == seat)
        if is_us:
            next_day = day + 1
            for row in farm["tiles"]:
                for t in row:
                    if isinstance(t, dict) and "animal" in t:
                        anim = t["animal"]
                        if not t["fed_today"] and t.get("consecutive_unfed", 0) >= 1:
                            livestock_lifecycle[anim]["escapes"] += 1
                        else:
                            a = kg.ANIMALS[anim]
                            days_since_first = next_day - t["placed_day"] - a["first_yield_day"]
                            if days_since_first >= 0 and days_since_first % a["interval"] == 0:
                                base = 1
                                bonus = t.get("pending_care_bonus", 0) if t["fed_today"] else 0
                                livestock_lifecycle[anim]["production_events"] += 1
                                livestock_lifecycle[anim]["units_produced"] += (base + bonus)
                            fertilizer_events["produced"] += 1
        orig_daily_animals(farm, day)

    # Intercept _daily_refresh_plants for weed deaths
    orig_daily_plants = kg._daily_refresh_plants
    def tracked_daily_plants(farm, current_day, turns_per_day):
        nonlocal cur_plant_pid
        cur_plant_pid = 1 - cur_plant_pid
        is_us = (cur_plant_pid == seat)
        if is_us:
            for row in farm["tiles"]:
                for t in row:
                    if isinstance(t, dict) and t.get("kind") == "PLANT":
                        if not t["watered_today"] and t.get("consecutive_unwatered", 0) >= 1:
                            crop_lifecycle[t["crop"]]["weed_deaths"] += 1
        orig_daily_plants(farm, current_day, turns_per_day)

    # Intercept _decay_plants for decay losses
    orig_decay_plants = kg._decay_plants
    def tracked_decay_plants(farm, step):
        nonlocal cur_decay_pid
        cur_decay_pid = 1 - cur_decay_pid
        is_us = (cur_decay_pid == seat)
        if is_us:
            for row in farm["tiles"]:
                for t in row:
                    if isinstance(t, dict) and t.get("kind") == "PLANT":
                        mls = t.get("max_lifespan_step", -1)
                        if mls >= 0 and step >= mls and (step - mls) % 2 == 0:
                            if t.get("yield_units", 0) > 0:
                                crop_lifecycle[t["crop"]]["decay_lost_units"] += 1
        orig_decay_plants(farm, step)

    # Intercept _drop_inventories_to_shed for discarded shed overflows
    orig_drop_shed = kg._drop_inventories_to_shed
    def tracked_drop_shed(private, capacity):
        nonlocal cur_drop_pid
        cur_drop_pid = 1 - cur_drop_pid
        is_us = (cur_drop_pid == seat)
        if is_us:
            current = sum(private["shed"].values())
            room = max(0, capacity - current)
            for inv in private["inventories"]:
                for item, n in inv.items():
                    if n > room:
                        discard = n - room
                        inventory_dynamics["discarded_overflow"][item] += discard
                        room = 0
                    else:
                        room -= n
        orig_drop_shed(private, capacity)

    # Attach all interceptors
    kg._process_market = tracked_process_market
    kg._apply_unit_action = tracked_apply_unit
    kg._daily_refresh_animals = tracked_daily_animals
    kg._daily_refresh_plants = tracked_daily_plants
    kg._decay_plants = tracked_decay_plants
    kg._drop_inventories_to_shed = tracked_drop_shed

    try:
        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": seed}, info={"seed": seed})
        env.reset()
        env.run(players)
    finally:
        kg._process_market = orig_process_market
        kg._apply_unit_action = orig_apply_unit
        kg._daily_refresh_animals = orig_daily_animals
        kg._daily_refresh_plants = orig_daily_plants
        kg._decay_plants = orig_decay_plants
        kg._drop_inventories_to_shed = orig_drop_shed

    our_farm = env.state[seat].observation.farms[seat]
    our_priv = env.state[seat].observation.private
    opp_farm = env.state[1 - seat].observation.farms[1 - seat]

    final_reward = float(env.state[seat].reward or 0.0)
    final_money = float(our_farm["money"])
    opp_reward = float(env.state[1 - seat].reward or 0.0)
    win = 1.0 if final_reward > opp_reward else (0.5 if final_reward == opp_reward else 0.0)

    # Count surviving livestock and unharvested crops at season end
    for row in our_farm["tiles"]:
        for t in row:
            if isinstance(t, dict):
                if "animal" in t:
                    livestock_lifecycle[t["animal"]]["surviving_end"] += 1
                elif t.get("kind") == "PLANT":
                    crop_lifecycle[t["crop"]]["unharvested_end_units"] += t.get("yield_units", 0)

    # Animals placed total
    for a in ANIMALS:
        livestock_lifecycle[a]["placed"] = cash_ledger["buys_animal"][a]["units"]

    # Final shed & worker inventories
    inventory_dynamics["final_shed"] = dict(our_priv.get("shed", {}))
    w_inv = defaultdict(int)
    for inv in our_priv.get("inventories", []):
        for k, v in inv.items():
            w_inv[k] += v
    inventory_dynamics["final_worker_inv"] = dict(w_inv)

    # Cash reconciliation check
    tot_revenue = sum(s["revenue"] for s in cash_ledger["sells"].values())
    tot_seed_cost = sum(b["cost"] for b in cash_ledger["buys_seed"].values())
    tot_feed_cost = cash_ledger["buys_product"]["WHEAT"]["cost"]
    tot_fert_cost = cash_ledger["buys_product"]["FERTILIZER"]["cost"]
    tot_animal_cost = sum(b["cost"] for b in cash_ledger["buys_animal"].values())
    tot_hire_cost = cash_ledger["hires"]["cost"]
    tot_land_cost = cash_ledger["land"]["cost"]

    tot_expenses = tot_seed_cost + tot_feed_cost + tot_fert_cost + tot_animal_cost + tot_hire_cost + tot_land_cost
    reconciled_final = cash_ledger["starting_cash"] + tot_revenue - tot_expenses
    recon_error = reconciled_final - final_money

    # Rotation manager telemetry if enabled
    rotation_summary = {}
    if enable_p51:
        mgr = get_rotation_manager()
        rotation_summary = {
            "total_tracked": len(mgr.rotations),
            "completed": sum(1 for r in mgr.rotations.values() if r.phase.value == "COMPLETED"),
            "d23_completed": sum(1 for r in mgr.rotations.values() if r.c1_plant_day == 23 and r.phase.value == "COMPLETED"),
            "c1_planted": sum(1 for r in mgr.rotations.values() if r.c1_planted_confirmed),
            "c2_planted": sum(1 for r in mgr.rotations.values() if r.c2_planted_confirmed),
            "records": [
                {
                    "pos": list(r.pos),
                    "c1_plant_day": r.c1_plant_day,
                    "c2_plant_day": r.c2_plant_day,
                    "phase": r.phase.value,
                    "c1_watered_d0": r.c1_d0_watered_confirmed,
                    "c2_watered_d0": r.c2_d0_watered_confirmed,
                    "c1_harvested": r.c1_harvested_confirmed,
                    "c2_harvested": r.c2_harvested_confirmed,
                    "failure_reason": r.failure_reason,
                } for r in mgr.rotations.values()
            ]
        }

    return {
        "final_money": final_money,
        "final_reward": final_reward,
        "opp_reward": opp_reward,
        "win": win,
        "cash_ledger": {
            "starting_cash": cash_ledger["starting_cash"],
            "sells": {k: dict(v) for k, v in cash_ledger["sells"].items()},
            "buys_product": {k: dict(v) for k, v in cash_ledger["buys_product"].items()},
            "buys_seed": {k: dict(v) for k, v in cash_ledger["buys_seed"].items()},
            "buys_animal": {k: dict(v) for k, v in cash_ledger["buys_animal"].items()},
            "hires": dict(cash_ledger["hires"]),
            "land": dict(cash_ledger["land"]),
            "reconciled_final": reconciled_final,
            "recon_error": recon_error,
        },
        "worker_actions": {
            "all_season": dict(worker_actions["all_season"]),
            "days_21_29": dict(worker_actions["days_21_29"]),
        },
        "crop_lifecycle": crop_lifecycle,
        "livestock_lifecycle": livestock_lifecycle,
        "fertilizer_events": fertilizer_events,
        "market_arbitration": {
            "turns_with_market_orders": market_arbitration["turns_with_market_orders"],
            "turns_exceeding_10_cap": market_arbitration["turns_exceeding_10_cap"],
            "total_candidate_orders": market_arbitration["total_candidate_orders"],
            "emitted_orders": market_arbitration["emitted_orders"],
            "slot_cap_dropped_orders": market_arbitration["slot_cap_dropped_orders"],
            "dropped_by_product": dict(market_arbitration["dropped_by_product"]),
        },
        "inventory_dynamics": {
            "discarded_overflow": dict(inventory_dynamics["discarded_overflow"]),
            "final_shed": inventory_dynamics["final_shed"],
            "final_worker_inv": inventory_dynamics["final_worker_inv"],
            "day29_harvest_units": dict(inventory_dynamics["day29_harvest_units"]),
            "day29_sold_units": dict(inventory_dynamics["day29_sold_units"]),
        },
        "rotation_summary": rotation_summary,
    }


def _run_matched_reconciliation_pair(scenario):
    """Runs a single matched pair (Control vs Treatment) with full causal instrumentation."""
    seed = scenario["seed"]
    opponent = scenario["opponent"]
    seat = scenario["seat"]

    try:
        ctrl = _run_instrumented_game(seed, opponent, seat, enable_p51=False)
        treat = _run_instrumented_game(seed, opponent, seat, enable_p51=True)

        # Matched cash waterfall computation: Treatment - Control
        c_led = ctrl["cash_ledger"]
        t_led = treat["cash_ledger"]

        delta_money = treat["final_money"] - ctrl["final_money"]
        delta_revenue = {}
        for p in PRODUCTS:
            c_rev = c_led["sells"].get(p, {}).get("revenue", 0.0)
            t_rev = t_led["sells"].get(p, {}).get("revenue", 0.0)
            delta_revenue[p] = t_rev - c_rev

        delta_seed_costs = {}
        for c in CROPS:
            c_cost = c_led["buys_seed"].get(c, {}).get("cost", 0.0)
            t_cost = t_led["buys_seed"].get(c, {}).get("cost", 0.0)
            # Cost increases reduce cash, so cash delta is -(Treatment - Control)
            delta_seed_costs[c] = -(t_cost - c_cost)

        delta_feed_cost = -(t_led["buys_product"].get("WHEAT", {}).get("cost", 0.0) - c_led["buys_product"].get("WHEAT", {}).get("cost", 0.0))
        delta_fert_cost = -(t_led["buys_product"].get("FERTILIZER", {}).get("cost", 0.0) - c_led["buys_product"].get("FERTILIZER", {}).get("cost", 0.0))

        delta_animal_costs = {}
        for a in ANIMALS:
            c_cost = c_led["buys_animal"].get(a, {}).get("cost", 0.0)
            t_cost = t_led["buys_animal"].get(a, {}).get("cost", 0.0)
            delta_animal_costs[a] = -(t_cost - c_cost)

        delta_hires_cost = -(t_led["hires"]["cost"] - c_led["hires"]["cost"])
        delta_land_cost = -(t_led["land"]["cost"] - c_led["land"]["cost"])

        waterfall_sum = (
            sum(delta_revenue.values()) +
            sum(delta_seed_costs.values()) +
            delta_feed_cost +
            delta_fert_cost +
            sum(delta_animal_costs.values()) +
            delta_hires_cost +
            delta_land_cost
        )
        waterfall_discrepancy = waterfall_sum - delta_money

        return {
            "scenario": scenario,
            "status": "success",
            "ctrl": ctrl,
            "treat": treat,
            "delta_money": delta_money,
            "waterfall": {
                "delta_revenue": delta_revenue,
                "delta_seed_costs": delta_seed_costs,
                "delta_feed_cost": delta_feed_cost,
                "delta_fert_cost": delta_fert_cost,
                "delta_animal_costs": delta_animal_costs,
                "delta_hires_cost": delta_hires_cost,
                "delta_land_cost": delta_land_cost,
                "waterfall_sum": waterfall_sum,
                "waterfall_discrepancy": waterfall_discrepancy,
            }
        }
    except Exception as e:
        return {
            "scenario": scenario,
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def main():
    start_time = time.time()
    print("======================================================================")
    print("Kaggriculture P5.1-C — Causal Delta Reconciliation Runner (200 Games)")
    print("Panel: 10 seeds (96,201–96,210) x 5 opponents x 2 seats = 100 matched pairs")
    print("Control: 536f1e7 (P51=False) | Treatment: P5.1 (P51=True)")
    print("======================================================================")

    scenarios = []
    for seed in DIAGNOSTIC_SEEDS:
        for opp in OPPONENTS:
            for seat in (0, 1):
                scenarios.append({
                    "seed": seed,
                    "opponent": opp,
                    "seat": seat,
                })

    n_total = len(scenarios)
    results = []
    errors = []

    max_workers = min(os.cpu_count() or 4, 8)
    print(f"Launching {n_total} matched scenarios using {max_workers} processes...")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_matched_reconciliation_pair, sc): sc for sc in scenarios}
        done_count = 0
        for fut in as_completed(futures):
            res = fut.result()
            done_count += 1
            if res.get("status") == "success":
                results.append(res)
                sc = res["scenario"]
                wf = res["waterfall"]
                print(f"[{done_count:03d}/{n_total}] Seed {sc['seed']} vs {sc['opponent']:<20} S{sc['seat']}: Delta=${res['delta_money']:+8.2f} (WF_Sum=${wf['waterfall_sum']:+8.2f}, Err={wf['waterfall_discrepancy']:.4f})")
            else:
                errors.append(res)
                sc = res["scenario"]
                print(f"[{done_count:03d}/{n_total}] Seed {sc['seed']} vs {sc['opponent']} S{sc['seat']}: ERROR - {res.get('error')}")

    elapsed = time.time() - start_time
    print(f"\nCompleted {len(results)} pairs in {elapsed:.1f}s ({elapsed/60.0:.2f} min). Errors: {len(errors)}")

    if not results:
        print("ERROR: No successful pairs!")
        return

    # Verify Behavior Invariance & Cash Reconciliation across all games
    all_recon_errors = []
    for r in results:
        all_recon_errors.append(abs(r["ctrl"]["cash_ledger"]["recon_error"]))
        all_recon_errors.append(abs(r["treat"]["cash_ledger"]["recon_error"]))
    max_recon_err = max(all_recon_errors)
    print(f"Max single-game cash reconciliation error: {max_recon_err:.6f}")

    deltas_money = [r["delta_money"] for r in results]
    mean_delta = sum(deltas_money) / len(deltas_money)
    print(f"Mean Paired Delta: ${mean_delta:+.2f} (Observed Target: ~-$1020.68)")

    # Aggregate Cash Waterfall
    agg_waterfall = {
        "Carrot Revenue": sum(r["waterfall"]["delta_revenue"]["CARROT"] for r in results) / len(results),
        "Wheat Revenue": sum(r["waterfall"]["delta_revenue"]["WHEAT"] for r in results) / len(results),
        "Milk Revenue": sum(r["waterfall"]["delta_revenue"]["MILK"] for r in results) / len(results),
        "Wool Revenue": sum(r["waterfall"]["delta_revenue"]["WOOL"] for r in results) / len(results),
        "Melon Revenue": sum(r["waterfall"]["delta_revenue"]["MELON"] for r in results) / len(results),
        "Strawberry Revenue": sum(r["waterfall"]["delta_revenue"]["STRAWBERRY"] for r in results) / len(results),
        "Tomato Revenue": sum(r["waterfall"]["delta_revenue"]["TOMATO"] for r in results) / len(results),
        "Egg Revenue": sum(r["waterfall"]["delta_revenue"]["EGG"] for r in results) / len(results),
        "Fertilizer Revenue": sum(r["waterfall"]["delta_revenue"]["FERTILIZER"] for r in results) / len(results),
        "Carrot Seed Cost Delta": sum(r["waterfall"]["delta_seed_costs"]["CARROT"] for r in results) / len(results),
        "Wheat Seed Cost Delta": sum(r["waterfall"]["delta_seed_costs"]["WHEAT"] for r in results) / len(results),
        "Other Seed Cost Delta": sum(sum(r["waterfall"]["delta_seed_costs"][c] for c in ("MELON", "STRAWBERRY", "TOMATO")) for r in results) / len(results),
        "Feed Wheat Purchases": sum(r["waterfall"]["delta_feed_cost"] for r in results) / len(results),
        "Fertilizer Purchases": sum(r["waterfall"]["delta_fert_cost"] for r in results) / len(results),
        "Animal Purchase Costs": sum(sum(r["waterfall"]["delta_animal_costs"].values()) for r in results) / len(results),
        "Hire Costs": sum(r["waterfall"]["delta_hires_cost"] for r in results) / len(results),
        "Land Costs": sum(r["waterfall"]["delta_land_cost"] for r in results) / len(results),
    }

    waterfall_total = sum(agg_waterfall.values())
    print("\n======================================================================")
    print("PRIMARY CAUSAL CASH WATERFALL (TREATMENT − CONTROL MEAN PER GAME)")
    print("======================================================================")
    for cat, val in agg_waterfall.items():
        print(f"  {cat:<26}: ${val:+9.2f}")
    print("----------------------------------------------------------------------")
    print(f"  {'TOTAL WATERFALL':<26}: ${waterfall_total:+9.2f}")
    print(f"  {'OBSERVED MEAN DELTA':<26}: ${mean_delta:+9.2f}")
    print(f"  {'RESIDUAL DISCREPANCY':<26}: ${waterfall_total - mean_delta:+9.4f}")
    print("======================================================================")

    # Save summary and compressed raw results
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "p51c_causal_reconciliation_summary.json")
    raw_path = os.path.join(out_dir, "p51c_raw_matched_pairs.json.gz")

    # Precompute aggregates for easy reporting
    def _agg_dict(keys, getter):
        res = {}
        for k in keys:
            vals = [getter(r, k) for r in results]
            res[k] = sum(vals) / len(vals)
        return res

    all_action_keys = sorted(set(list(results[0]["ctrl"]["worker_actions"]["all_season"].keys()) + list(results[0]["treat"]["worker_actions"]["all_season"].keys())))
    agg_actions_all_season = {
        "ctrl": {k: sum(r["ctrl"]["worker_actions"]["all_season"].get(k, 0) for r in results) / len(results) for k in all_action_keys},
        "treat": {k: sum(r["treat"]["worker_actions"]["all_season"].get(k, 0) for r in results) / len(results) for k in all_action_keys},
    }
    agg_actions_d21_29 = {
        "ctrl": {k: sum(r["ctrl"]["worker_actions"]["days_21_29"].get(k, 0) for r in results) / len(results) for k in all_action_keys},
        "treat": {k: sum(r["treat"]["worker_actions"]["days_21_29"].get(k, 0) for r in results) / len(results) for k in all_action_keys},
    }

    crop_fields = ["planted", "watered", "fertilized", "harvested_events", "harvested_units", "weed_deaths", "decay_lost_units", "unharvested_end_units"]
    agg_crops = {
        c: {
            f: {
                "ctrl": sum(r["ctrl"]["crop_lifecycle"][c].get(f, 0) for r in results) / len(results),
                "treat": sum(r["treat"]["crop_lifecycle"][c].get(f, 0) for r in results) / len(results),
                "delta": (sum(r["treat"]["crop_lifecycle"][c].get(f, 0) for r in results) - sum(r["ctrl"]["crop_lifecycle"][c].get(f, 0) for r in results)) / len(results),
            } for f in crop_fields
        } for c in CROPS
    }

    anim_fields = ["placed", "fed", "cared", "production_events", "units_produced", "harvested_events", "harvested_units", "escapes", "surviving_end"]
    agg_livestock = {
        a: {
            f: {
                "ctrl": sum(r["ctrl"]["livestock_lifecycle"][a].get(f, 0) for r in results) / len(results),
                "treat": sum(r["treat"]["livestock_lifecycle"][a].get(f, 0) for r in results) / len(results),
                "delta": (sum(r["treat"]["livestock_lifecycle"][a].get(f, 0) for r in results) - sum(r["ctrl"]["livestock_lifecycle"][a].get(f, 0) for r in results)) / len(results),
            } for f in anim_fields
        } for a in ANIMALS
    }

    agg_market = {
        p: {
            "ctrl_units": sum(r["ctrl"]["cash_ledger"]["sells"].get(p, {}).get("units", 0) for r in results) / len(results),
            "treat_units": sum(r["treat"]["cash_ledger"]["sells"].get(p, {}).get("units", 0) for r in results) / len(results),
            "delta_units": (sum(r["treat"]["cash_ledger"]["sells"].get(p, {}).get("units", 0) for r in results) - sum(r["ctrl"]["cash_ledger"]["sells"].get(p, {}).get("units", 0) for r in results)) / len(results),
            "ctrl_rev": sum(r["ctrl"]["cash_ledger"]["sells"].get(p, {}).get("revenue", 0.0) for r in results) / len(results),
            "treat_rev": sum(r["treat"]["cash_ledger"]["sells"].get(p, {}).get("revenue", 0.0) for r in results) / len(results),
            "delta_rev": (sum(r["treat"]["cash_ledger"]["sells"].get(p, {}).get("revenue", 0.0) for r in results) - sum(r["ctrl"]["cash_ledger"]["sells"].get(p, {}).get("revenue", 0.0) for r in results)) / len(results),
        } for p in PRODUCTS
    }

    agg_rotations = {
        "completed": sum(r["treat"]["rotation_summary"]["completed"] for r in results),
        "d23_completed": sum(r["treat"]["rotation_summary"]["d23_completed"] for r in results),
        "c1_planted": sum(r["treat"]["rotation_summary"]["c1_planted"] for r in results),
        "c2_planted": sum(r["treat"]["rotation_summary"]["c2_planted"] for r in results),
        "mean_completed_per_game": sum(r["treat"]["rotation_summary"]["completed"] for r in results) / len(results),
    }

    summary_payload = {
        "n_pairs": len(results),
        "mean_delta_money": mean_delta,
        "max_reconciliation_error": max_recon_err,
        "agg_waterfall": agg_waterfall,
        "waterfall_total": waterfall_total,
        "agg_actions_all_season": agg_actions_all_season,
        "agg_actions_d21_29": agg_actions_d21_29,
        "agg_crops": agg_crops,
        "agg_livestock": agg_livestock,
        "agg_market": agg_market,
        "agg_rotations": agg_rotations,
        "results": [
            {
                "scenario": r["scenario"],
                "delta_money": r["delta_money"],
                "waterfall": r["waterfall"],
                "ctrl_final": r["ctrl"]["final_money"],
                "treat_final": r["treat"]["final_money"],
                "ctrl_actions_all_season": r["ctrl"]["worker_actions"]["all_season"],
                "treat_actions_all_season": r["treat"]["worker_actions"]["all_season"],
                "ctrl_actions_d21_29": r["ctrl"]["worker_actions"]["days_21_29"],
                "treat_actions_d21_29": r["treat"]["worker_actions"]["days_21_29"],
                "ctrl_crops": r["ctrl"]["crop_lifecycle"],
                "treat_crops": r["treat"]["crop_lifecycle"],
                "ctrl_livestock": r["ctrl"]["livestock_lifecycle"],
                "treat_livestock": r["treat"]["livestock_lifecycle"],
                "ctrl_market": r["ctrl"]["market_arbitration"],
                "treat_market": r["treat"]["market_arbitration"],
                "ctrl_inventory": r["ctrl"]["inventory_dynamics"],
                "treat_inventory": r["treat"]["inventory_dynamics"],
                "treat_rotation": r["treat"]["rotation_summary"],
            } for r in results
        ]
    }

    with open(summary_path, "w") as f:
        json.dump(summary_payload, f, indent=2)
    print(f"\nWrote reconciliation summary to: {summary_path}")

    # Compress full results
    with gzip.open(raw_path, "wt", encoding="utf-8") as f:
        json.dump(results, f)
    print(f"Wrote compressed raw telemetry to: {raw_path}")


if __name__ == "__main__":
    main()
