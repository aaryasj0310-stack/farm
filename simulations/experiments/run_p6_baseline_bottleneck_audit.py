#!/usr/bin/env python3
"""Kaggriculture P6 — Baseline System Bottleneck Audit Harness.

Runs 100 baseline simulation games on the untouched discovery panel:
Seeds 96,401–96,410 (10 seeds) x 5 Opponents x 2 Seats = 100 Baseline Games.
Baseline: Production baseline commit 536f1e7 (P51_T1_TWO_CYCLE_CARROT_ENABLED = False).

Objectives:
Measure six major constraint families in the un-optimized production baseline:
1. Worker execution and transit:
   - Full classification of every worker turn (crop, livestock, logistics, move, pass, blocked)
   - Distance traveled, quadrant traversals, repetitive routes (shed<->crops, shed<->animals, etc.)
   - Necessary vs avoidable movement; idle capacity and missed work
2. Livestock execution loss:
   - Actual milk/wool yield vs maximum mechanically achievable yield under the SAME herd/placement
   - Missed feed/care opportunities and resulting lost production valuation
   - Product left unharvested on animals vs harvested vs sold
3. Physical wheat / feed liquidity:
   - Hourly shed wheat, carried wheat, planted wheat, and animal feed demand
   - Intraday grain stockouts blocking feed tasks before market settlement
   - Sell-then-buy coordination failures and emergency feed purchases
4. Shed / storage losses:
   - Hourly shed occupancy profile, peak crowding, and end-of-day discards by product
   - Economic valuation (contemporaneous realized price vs strict lower bound)
5. Market realization efficiency:
   - Full product funnels: Produced -> Harvested -> Deposited -> Sold -> Final Cash
6. Tile / crop productive efficiency:
   - Tile-day utilization: productively planted, empty available, structures, unserviceable
   - Crop yield efficiency (actual yield vs maximum theoretical yield)
7. Time-of-day congestion map:
   - 30 Days x 24 Hours congestion matrix of worker activities, shed state, and grain liquidity
8. Recoverable-value ledger:
   - Mutually exclusive loss decomposition with strict epistemic classifications
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
DIAGNOSTIC_SEEDS = list(range(96401, 96411))  # 10 fresh untouched discovery seeds: 96,401–96,410

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
CROPS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
ANIMALS = ["COW", "SHEEP", "CHICKEN"]
SHED_ACCESS_COORDS = {(4, 4), (5, 4), (4, 5), (5, 5)}


def _run_p6_game(seed, opponent, seat):
    """Runs a single instrumented baseline simulation game and extracts comprehensive P6 telemetry."""
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
    import execution.task_scheduler as ts
    import simulations.experiments.audit_p50r_telemetry as apt
    from simulations.experiments.agent_zoo import get_agent
    from strategy.two_cycle_rotation_manager import reset_rotation_manager

    apt._configure_baseline(cfg)
    cfg.set_p51_t1_two_cycle_carrot_enabled(False)
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

    # 1. Worker Execution and Transit
    worker_turn_records = []
    worker_action_counts = defaultdict(int)
    worker_movement_by_worker = defaultdict(int)
    worker_movement_by_quadrant = defaultdict(int)
    worker_movement_by_route = defaultdict(int)       # e.g. "NW->NW", "NW->NE", "NE->NW", "NW->SW", etc.
    worker_movement_by_func_route = defaultdict(int)  # e.g. "shed_to_crop", "crop_to_crop", "shed_to_cow", etc.
    worker_idle_pass_counts = defaultdict(int)

    # 2. Livestock Detailed Tracking
    placed_animals = {} # (x, y) -> dict of animal stats
    livestock_summary = {
        a: {
            "placed_count": 0,
            "feed_events": 0,
            "missed_feed_opportunities": 0,
            "care_events": 0,
            "missed_care_opportunities": 0,
            "production_intervals": 0,
            "units_produced": 0,
            "mechanically_max_units": 0,
            "harvested_events": 0,
            "harvested_units": 0,
            "uncollected_end_units": 0,
            "escapes": 0,
        } for a in ANIMALS
    }
    fertilizer_summary = {
        "produced": 0,
        "collected": 0,
        "discarded": 0,
        "sold": 0,
    }

    # 3. Wheat & Feed Liquidity Tracking
    hourly_wheat_liquidity = []
    grain_stockout_events = []
    wheat_sales_log = []   # (day, hour, units, price)
    wheat_purchases_log = [] # (day, hour, units, cost)

    # 4. Shed & Storage Losses
    hourly_shed_occupancy = []
    shed_discards = defaultdict(lambda: {"units": 0, "events": []})

    # 5. Market Realization Funnel
    market_funnel = {
        p: {
            "produced": 0,
            "harvested": 0,
            "discarded": 0,
            "sold": 0,
            "revenue": 0.0,
            "final_unharvested": 0,
            "final_shed": 0,
            "final_worker": 0,
        } for p in PRODUCTS
    }

    # 6. Tile / Crop Productive Efficiency
    tile_days_summary = {
        "unlocked_tile_days": 0,
        "productively_planted_tile_days": 0,
        "mature_waiting_harvest_tile_days": 0,
        "structure_tile_days": 0,
        "shed_tile_days": 0,
        "empty_available_tile_days": 0,
        "unserviceable_empty_tile_days": 0,
    }
    crop_lifecycle_p6 = {
        c: {
            "planted": 0,
            "watered": 0,
            "fertilized": 0,
            "harvested_events": 0,
            "harvested_units": 0,
            "expected_max_units": 0,
            "weed_deaths": 0,
            "decay_lost_units": 0,
            "unharvested_end_units": 0,
        } for c in CROPS
    }

    # 7. Time-of-Day Congestion Map (30 Days x 24 Hours)
    # Cell format: {"crop": int, "livestock": int, "harvest": int, "move": int, "logistics": int, "pass": int, "blocked": int, "shed_units": int, "wheat_units": int, "stockouts": int}
    congestion_map = [[{
        "crop": 0,
        "livestock": 0,
        "harvest": 0,
        "move": 0,
        "logistics": 0,
        "pass": 0,
        "blocked": 0,
        "shed_units": 0,
        "wheat_units": 0,
        "stockouts": 0,
    } for _ in range(24)] for _ in range(30)]

    # Tracking helper state
    last_agent_turn_data = {}
    cur_p0_farm = None
    cur_p0_priv = None

    def _quadrant_of(pos):
        x, y = pos
        if x < 5 and y < 5:
            return "NW"
        elif x >= 5 and y < 5:
            return "NE"
        elif x < 5 and y >= 5:
            return "SW"
        else:
            return "SE"

    # Intercept assign_tasks from task_scheduler to capture planner intent and assignments
    orig_assign_tasks = ts.assign_tasks
    def tracked_assign_tasks(tasks, ctx, extra_units=()):
        asg = orig_assign_tasks(tasks, ctx, extra_units)
        # Store for the current turn
        nonlocal last_agent_turn_data
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)
        farm = ctx["farm"]
        last_agent_turn_data = {
            "day": day,
            "hour": hour,
            "tasks": tasks,
            "asg": asg,
            "farmer_pos": tuple(farm.farmer),
            "hands_pos": [tuple(h) for h in farm.hands],
            "shed_wheat": ctx["private"].shed.get("WHEAT", 0) if ctx.get("private") else 0,
            "carried_wheat": sum((inv or {}).get("WHEAT", 0) for inv in (ctx["private"].inventories if ctx.get("private") else [])),
            "shed_occupancy": sum(ctx["private"].shed.values()) if ctx.get("private") else 0,
        }
        return asg
    ts.assign_tasks = tracked_assign_tasks

    # Intercept kaggriculture engine functions
    orig_process_market = kg._process_market
    def tracked_process_market(state, env):
        nonlocal cur_p0_farm, cur_p0_priv
        cur_p0_farm = state[0].observation.farms[0]
        cur_p0_priv = state[0].observation.private

        step = state[0].observation.step
        day = step // 24
        hour = step % 24

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
                        market_funnel[item]["sold"] += 1
                        market_funnel[item]["revenue"] += p
                        if item == "WHEAT":
                            wheat_sales_log.append((day, hour, 1, p))
                    elif op == "BUY_PRODUCT":
                        cash_ledger["buys_product"][item]["units"] += 1
                        cash_ledger["buys_product"][item]["cost"] += p
                        cash_ledger["buys_product"][item]["prices"].append(p)
                        if item == "WHEAT":
                            wheat_purchases_log.append((day, hour, 1, p))
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
            hour = last_agent_turn_data.get("hour", 0)

            # Classify worker turn
            assigned_task = None
            asg_map = last_agent_turn_data.get("asg", {}).get("assignment", {}) if last_agent_turn_data else {}
            if unit_idx in asg_map:
                assigned_task = asg_map[unit_idx]

            category = "IDLE"
            detail = op
            target_pos = assigned_task.get("target") if assigned_task else None
            task_op = assigned_task.get("op") if assigned_task else None
            dist_to_target = (abs(fx - target_pos[0]) + abs(fy - target_pos[1])) if target_pos else 0

            if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                category = "MOVE"
                detail = f"MOVE_{op}"
                worker_movement_by_worker[unit_idx] += 1
                curr_quad = _quadrant_of(pos)
                worker_movement_by_quadrant[curr_quad] += 1
                if target_pos:
                    dest_quad = _quadrant_of(target_pos)
                    route_key = f"{curr_quad}->{dest_quad}"
                    worker_movement_by_route[route_key] += 1
                    
                    # Functional route
                    if pos in SHED_ACCESS_COORDS:
                        func_key = f"shed_to_{task_op.lower()}"
                    elif tuple(target_pos) in SHED_ACCESS_COORDS:
                        func_key = f"{task_op.lower()}_to_shed"
                    else:
                        func_key = f"{task_op.lower()}_to_{task_op.lower()}"
                    worker_movement_by_func_route[func_key] += 1
                congestion_map[day][hour]["move"] += 1

            elif op == "PASS":
                category = "IDLE"
                worker_idle_pass_counts[unit_idx] += 1
                congestion_map[day][hour]["pass"] += 1

            elif op == "PLANT":
                crop = action[1] if len(action) > 1 else "UNKNOWN"
                category = "PRODUCTIVE_CROP"
                detail = f"PLANT_{crop}"
                if tile is None and private["seeds"].get(crop, 0) > 0:
                    crop_lifecycle_p6[crop]["planted"] += 1
                congestion_map[day][hour]["crop"] += 1

            elif op == "WATER":
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop = tile.get("crop", "UNKNOWN")
                    category = "PRODUCTIVE_CROP"
                    detail = f"WATER_{crop}"
                    if not tile["watered_today"]:
                        crop_lifecycle_p6[crop]["watered"] += 1
                congestion_map[day][hour]["crop"] += 1

            elif op == "HARVEST":
                if isinstance(tile, dict):
                    if tile.get("kind") == "PLANT":
                        crop = tile.get("crop", "UNKNOWN")
                        category = "PRODUCTIVE_CROP"
                        detail = f"HARVEST_CROP_{crop}"
                        y_units = tile.get("yield_units", 0)
                        if y_units > 0:
                            crop_lifecycle_p6[crop]["harvested_events"] += 1
                            crop_lifecycle_p6[crop]["harvested_units"] += y_units
                            market_funnel[crop]["harvested"] += y_units
                    elif "animal" in tile:
                        anim = tile.get("animal", "UNKNOWN")
                        prod = kg.ANIMALS[anim]["product"]
                        category = "PRODUCTIVE_LIVESTOCK"
                        detail = f"HARVEST_ANIMAL_{anim}"
                        y_units = tile.get("yield_units", 0)
                        if y_units > 0:
                            livestock_summary[anim]["harvested_events"] += 1
                            livestock_summary[anim]["harvested_units"] += y_units
                            market_funnel[prod]["harvested"] += y_units
                congestion_map[day][hour]["harvest"] += 1

            elif op == "FEED":
                if isinstance(tile, dict) and "animal" in tile:
                    anim = tile.get("animal", "UNKNOWN")
                    category = "PRODUCTIVE_LIVESTOCK"
                    detail = f"FEED_{anim}"
                    if not tile["fed_today"]:
                        livestock_summary[anim]["feed_events"] += 1
                congestion_map[day][hour]["livestock"] += 1

            elif op == "CARE":
                if isinstance(tile, dict) and "animal" in tile:
                    anim = tile.get("animal", "UNKNOWN")
                    category = "PRODUCTIVE_LIVESTOCK"
                    detail = f"CARE_{anim}"
                    if not tile["cared_today"]:
                        livestock_summary[anim]["care_events"] += 1
                congestion_map[day][hour]["livestock"] += 1

            elif op == "COLLECT_FERTILIZER":
                category = "PRODUCTIVE_LIVESTOCK"
                detail = "COLLECT_FERTILIZER"
                if isinstance(tile, dict) and "animal" in tile and tile.get("fertilizer_available", False):
                    fertilizer_summary["collected"] += 1
                    market_funnel["FERTILIZER"]["harvested"] += 1
                congestion_map[day][hour]["livestock"] += 1

            elif op == "FERTILIZE":
                category = "PRODUCTIVE_CROP"
                detail = "FERTILIZE"
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop = tile.get("crop", "UNKNOWN")
                    crop_lifecycle_p6[crop]["fertilized"] += 1
                congestion_map[day][hour]["crop"] += 1

            elif op in ("PICKUP", "PLACE", "DROP", "BUILD_PASTURE", "BUILD_COOP", "DIG"):
                category = "LOGISTICS"
                detail = op
                congestion_map[day][hour]["logistics"] += 1

            worker_action_counts[detail] += 1

        orig_apply_unit(farm, private, unit_idx, action, board_size, day, turns_per_day, shed_capacity)

    # Intercept _daily_refresh_animals for livestock lifecycle and maximum mechanical potential
    orig_daily_animals = kg._daily_refresh_animals
    def tracked_daily_animals(farm, day):
        nonlocal cur_anim_pid
        cur_anim_pid = 1 - cur_anim_pid
        is_us = (cur_anim_pid == seat)
        if is_us:
            next_day = day + 1
            for row_idx, row in enumerate(farm["tiles"]):
                for col_idx, t in enumerate(row):
                    if isinstance(t, dict) and "animal" in t:
                        anim = t["animal"]
                        pos = (col_idx, row_idx)
                        if pos not in placed_animals:
                            placed_animals[pos] = {
                                "animal": anim,
                                "placed_day": t["placed_day"],
                                "pos": pos,
                            }
                            livestock_summary[anim]["placed_count"] += 1

                        a_cfg = kg.ANIMALS[anim]
                        days_since_first = next_day - t["placed_day"] - a_cfg["first_yield_day"]

                        # Check missed feed / care
                        if not t["fed_today"]:
                            livestock_summary[anim]["missed_feed_opportunities"] += 1
                        if not t["cared_today"]:
                            livestock_summary[anim]["missed_care_opportunities"] += 1

                        if not t["fed_today"] and t.get("consecutive_unfed", 0) >= 1:
                            livestock_summary[anim]["escapes"] += 1
                        else:
                            # Production tick check
                            if days_since_first >= 0 and days_since_first % a_cfg["interval"] == 0:
                                livestock_summary[anim]["production_intervals"] += 1
                                # Mechanically max yield achievable = 1 base + max care bonus (interval - 1 cares)
                                max_care = a_cfg["interval"] - 1
                                livestock_summary[anim]["mechanically_max_units"] += (1 + max_care)

                                base = 1
                                bonus = t.get("pending_care_bonus", 0) if t["fed_today"] else 0
                                actual_yield = (base + bonus) if t["fed_today"] else 0
                                livestock_summary[anim]["units_produced"] += actual_yield
                                market_funnel[a_cfg["product"]]["produced"] += actual_yield

                            fertilizer_summary["produced"] += 1
                            market_funnel["FERTILIZER"]["produced"] += 1

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
                            crop_lifecycle_p6[t["crop"]]["weed_deaths"] += 1
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
                                crop_lifecycle_p6[t["crop"]]["decay_lost_units"] += 1
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
            day = last_agent_turn_data.get("day", 0)
            for inv in private["inventories"]:
                for item, n in inv.items():
                    if n > room:
                        discarded = n - room
                        shed_discards[item]["units"] += discarded
                        shed_discards[item]["events"].append({"day": day, "units": discarded})
                        if item in market_funnel:
                            market_funnel[item]["discarded"] += discarded
                        room = 0
                    else:
                        room -= n
        orig_drop_shed(private, capacity)

    # Track tile-days at end of each day
    orig_end_of_day = kg._end_of_day
    def tracked_end_of_day(state, env, day):
        obs0 = state[0].observation
        our_farm = obs0.farms[seat]
        unlocked_quads = our_farm.get("unlocked_quadrants", ["NW"])
        n_unlocked_tiles = len(unlocked_quads) * 25
        tile_days_summary["unlocked_tile_days"] += n_unlocked_tiles

        for y in range(10):
            for x in range(10):
                q = _quadrant_of((x, y))
                if q in unlocked_quads:
                    t = our_farm["tiles"][y][x]
                    if isinstance(t, dict):
                        if t.get("kind") == "PLANT":
                            if t.get("yield_units", 0) > 0:
                                tile_days_summary["mature_waiting_harvest_tile_days"] += 1
                            else:
                                tile_days_summary["productively_planted_tile_days"] += 1
                        elif "animal" in t or t.get("structure") in ("PASTURE", "COOP"):
                            tile_days_summary["structure_tile_days"] += 1
                    elif t is None:
                        tile_days_summary["empty_available_tile_days"] += 1

        orig_end_of_day(state, env, day)

    # Hourly snapshot tracker for wheat liquidity and shed state
    def _snapshot_hourly_state(env, state):
        day = state[0].observation.day
        hour = state[0].observation.hour
        if day >= 30:
            return
        our_priv = state[seat].observation.private
        our_farm = state[0].observation.farms[seat]

        shed_w = our_priv.get("shed", {}).get("WHEAT", 0)
        carried_w = sum((inv or {}).get("WHEAT", 0) for inv in our_priv.get("inventories", []))
        total_shed = sum(our_priv.get("shed", {}).values())

        # Count unfed animals today
        unfed_count = 0
        planted_w = 0
        for row in our_farm.get("tiles", []):
            for t in row:
                if isinstance(t, dict):
                    if "animal" in t and not t.get("fed_today", False):
                        unfed_count += 1
                    if t.get("kind") == "PLANT" and t.get("crop") == "WHEAT":
                        planted_w += 1

        hourly_shed_occupancy.append({
            "day": day,
            "hour": hour,
            "total_shed": total_shed,
            "shed_wheat": shed_w,
            "carried_wheat": carried_w,
            "unfed_animals": unfed_count,
            "planted_wheat": planted_w,
        })
        congestion_map[day][hour]["shed_units"] = total_shed
        congestion_map[day][hour]["wheat_units"] = shed_w

        # Check stockout condition: unfed animal exists, worker carries no wheat, shed has 0 wheat
        if unfed_count > 0 and (shed_w + carried_w) == 0:
            grain_stockout_events.append({
                "day": day,
                "hour": hour,
                "unfed_animals": unfed_count,
            })
            congestion_map[day][hour]["stockouts"] += 1

    kg._process_market = tracked_process_market
    kg._apply_unit_action = tracked_apply_unit
    kg._daily_refresh_animals = tracked_daily_animals
    kg._daily_refresh_plants = tracked_daily_plants
    kg._decay_plants = tracked_decay_plants
    kg._drop_inventories_to_shed = tracked_drop_shed
    kg._end_of_day = tracked_end_of_day

    def _call_agent(agent_fn, obs, config):
        try:
            return agent_fn(obs, config)
        except TypeError:
            return agent_fn(obs)

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    try:
        env.reset()
        for step_idx in range(720):
            if env.done:
                break
            _snapshot_hourly_state(env, env.state)
            act0 = _call_agent(players[0], env.state[0].observation, env.configuration)
            act1 = _call_agent(players[1], env.state[1].observation, env.configuration)
            env.step([act0, act1])
    finally:
        kg._process_market = orig_process_market
        kg._apply_unit_action = orig_apply_unit
        kg._daily_refresh_animals = orig_daily_animals
        kg._daily_refresh_plants = orig_daily_plants
        kg._decay_plants = orig_decay_plants
        kg._drop_inventories_to_shed = orig_drop_shed
        kg._end_of_day = orig_end_of_day
        ts.assign_tasks = orig_assign_tasks

    # Capture final state
    final_obs = env.state[0].observation
    final_farm = final_obs.farms[seat]
    final_priv = env.state[seat].observation.private
    final_money = float(final_farm["money"])

    # Final shed and worker inventory
    final_shed = dict(final_priv.get("shed", {}))
    final_worker_inv = [dict(inv) for inv in final_priv.get("inventories", [])]
    for p in PRODUCTS:
        market_funnel[p]["final_shed"] = final_shed.get(p, 0)
        market_funnel[p]["final_worker"] = sum((inv or {}).get(p, 0) for inv in final_worker_inv)

    # Final uncollected produce on plants and animals
    for row in final_farm.get("tiles", []):
        for t in row:
            if isinstance(t, dict):
                if t.get("kind") == "PLANT":
                    crop = t.get("crop")
                    y = t.get("yield_units", 0)
                    if crop in crop_lifecycle_p6:
                        crop_lifecycle_p6[crop]["unharvested_end_units"] += y
                    if crop in market_funnel:
                        market_funnel[crop]["final_unharvested"] += y
                elif "animal" in t:
                    anim = t.get("animal")
                    prod = kg.ANIMALS[anim]["product"]
                    y = t.get("yield_units", 0)
                    if anim in livestock_summary:
                        livestock_summary[anim]["uncollected_end_units"] += y
                    if prod in market_funnel:
                        market_funnel[prod]["final_unharvested"] += y

    # Exact Cash Reconciliation check
    tot_sells = sum(v["revenue"] for v in cash_ledger["sells"].values())
    tot_buys_prod = sum(v["cost"] for v in cash_ledger["buys_product"].values())
    tot_buys_seed = sum(v["cost"] for v in cash_ledger["buys_seed"].values())
    tot_buys_anim = sum(v["cost"] for v in cash_ledger["buys_animal"].values())
    tot_hires = cash_ledger["hires"]["cost"]
    tot_land = cash_ledger["land"]["cost"]

    recon_cash = 3000.0 + tot_sells - tot_buys_prod - tot_buys_seed - tot_buys_anim - tot_hires - tot_land
    recon_error = abs(recon_cash - final_money)

    def _to_plain_dict(obj):
        if isinstance(obj, (defaultdict, dict)):
            return {k: _to_plain_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_to_plain_dict(v) for v in obj]
        elif isinstance(obj, tuple):
            return tuple(_to_plain_dict(v) for v in obj)
        return obj

    raw_res = {
        "scenario": {"seed": seed, "opponent": opponent, "seat": seat},
        "final_money": final_money,
        "cash_ledger": cash_ledger,
        "recon_error": recon_error,
        "worker_action_counts": worker_action_counts,
        "worker_movement_by_worker": worker_movement_by_worker,
        "worker_movement_by_quadrant": worker_movement_by_quadrant,
        "worker_movement_by_route": worker_movement_by_route,
        "worker_movement_by_func_route": worker_movement_by_func_route,
        "worker_idle_pass_counts": worker_idle_pass_counts,
        "livestock_summary": livestock_summary,
        "fertilizer_summary": fertilizer_summary,
        "grain_stockout_events": grain_stockout_events,
        "wheat_sales_log": wheat_sales_log,
        "wheat_purchases_log": wheat_purchases_log,
        "shed_discards": {k: {"units": v["units"], "count": len(v["events"])} for k, v in shed_discards.items()},
        "market_funnel": market_funnel,
        "tile_days_summary": tile_days_summary,
        "crop_lifecycle": crop_lifecycle_p6,
        "congestion_map": congestion_map,
    }
    return _to_plain_dict(raw_res)


def main():
    print("======================================================================")
    print("Kaggriculture P6 Baseline System Bottleneck Audit")
    print(f"Panel: {len(DIAGNOSTIC_SEEDS)} Seeds ({DIAGNOSTIC_SEEDS[0]}–{DIAGNOSTIC_SEEDS[-1]}) x {len(OPPONENTS)} Opponents x 2 Seats = {len(DIAGNOSTIC_SEEDS)*len(OPPONENTS)*2} Games")
    print(f"Baseline Commit: {BASELINE_SHA}")
    print("======================================================================")

    scenarios = []
    for seed in DIAGNOSTIC_SEEDS:
        for opp in OPPONENTS:
            for seat in [0, 1]:
                scenarios.append({"seed": seed, "opponent": opp, "seat": seat})

    max_workers = min(os.cpu_count() or 4, 8)
    print(f"Running {len(scenarios)} games across {max_workers} worker processes...\n")
    start_time = time.time()
    results = []
    errors = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_p6_game, sc["seed"], sc["opponent"], sc["seat"]): sc for sc in scenarios}
        done_count = 0
        for fut in as_completed(futures):
            sc = futures[fut]
            done_count += 1
            try:
                res = fut.result()
                results.append(res)
                print(f"[{done_count:03d}/{len(scenarios)}] Seed {sc['seed']} vs {sc['opponent']:<20} S{sc['seat']}: Final Cash=${res['final_money']:9.2f} (Recon Err={res['recon_error']:.6f})")
            except Exception as e:
                errors.append({"scenario": sc, "error": str(e), "traceback": traceback.format_exc()})
                print(f"[{done_count:03d}/{len(scenarios)}] Seed {sc['seed']} vs {sc['opponent']:<20} S{sc['seat']}: ERROR - {e}")

    elapsed = time.time() - start_time
    print(f"\nCompleted {len(results)} games in {elapsed:.1f}s ({elapsed/60.0:.2f} min). Errors: {len(errors)}")

    if not results:
        print("ERROR: No games succeeded!")
        return

    # Verify Cash Accounting Closure across all baseline games
    max_recon_err = max(r["recon_error"] for r in results)
    mean_cash = sum(r["final_money"] for r in results) / len(results)
    print(f"Max single-game cash reconciliation error: {max_recon_err:.6f}")
    print(f"Mean Baseline Final Cash: ${mean_cash:.2f}")

    # Save compressed raw telemetry first to ensure raw data is always preserved
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    raw_path = os.path.join(out_dir, "p6_raw_baseline_telemetry.json.gz")
    with gzip.open(raw_path, "wt", encoding="utf-8") as f:
        json.dump(results, f)
    print(f"Wrote compressed raw telemetry to: {raw_path}")

    # Compute Comprehensive Aggregate Summary
    agg_summary = _aggregate_results(results)

    summary_path = os.path.join(out_dir, "p6_baseline_bottleneck_summary.json")
    with open(summary_path, "w") as f:
        json.dump(agg_summary, f, indent=2)
    print(f"\nWrote structured baseline audit summary to: {summary_path}")


def _aggregate_results(results):
    N = len(results)
    if N == 0:
        return {}

    cash_values = [r["final_money"] for r in results]
    cash_values_sorted = sorted(cash_values)
    mean_cash = sum(cash_values) / N
    median_cash = (cash_values_sorted[N//2 - 1] + cash_values_sorted[N//2]) / 2.0 if N % 2 == 0 else cash_values_sorted[N//2]
    min_cash = cash_values_sorted[0]
    max_cash = cash_values_sorted[-1]
    recon_errors = [r["recon_error"] for r in results]
    max_recon_error = max(recon_errors)

    by_opponent = defaultdict(list)
    by_seat = defaultdict(list)
    for r in results:
        sc = r["scenario"]
        by_opponent[sc["opponent"]].append(r["final_money"])
        by_seat[sc["seat"]].append(r["final_money"])

    opp_summary = {opp: {"mean": sum(vals)/len(vals), "min": min(vals), "max": max(vals), "n": len(vals)} for opp, vals in by_opponent.items()}
    seat_summary = {seat: {"mean": sum(vals)/len(vals), "n": len(vals)} for seat, vals in by_seat.items()}

    agg_worker_actions = defaultdict(int)
    agg_movement_by_worker = defaultdict(int)
    agg_movement_by_quad = defaultdict(int)
    agg_movement_by_route = defaultdict(int)
    agg_movement_by_func_route = defaultdict(int)
    agg_idle_pass = defaultdict(int)

    for r in results:
        for act, cnt in r["worker_action_counts"].items():
            agg_worker_actions[act] += cnt
        for w, cnt in r["worker_movement_by_worker"].items():
            agg_movement_by_worker[w] += cnt
        for q, cnt in r["worker_movement_by_quadrant"].items():
            agg_movement_by_quad[q] += cnt
        for rt, cnt in r["worker_movement_by_route"].items():
            agg_movement_by_route[rt] += cnt
        for fr, cnt in r["worker_movement_by_func_route"].items():
            agg_movement_by_func_route[fr] += cnt
        for w, cnt in r["worker_idle_pass_counts"].items():
            agg_idle_pass[w] += cnt

    total_worker_actions = sum(agg_worker_actions.values())
    total_moves = sum(cnt for act, cnt in agg_worker_actions.items() if act.startswith("MOVE_"))
    total_work = total_worker_actions - total_moves - agg_worker_actions.get("PASS", 0)

    transit_summary = {
        "total_actions_per_game": total_worker_actions / N,
        "moves_per_game": total_moves / N,
        "work_per_game": total_work / N,
        "pass_per_game": agg_worker_actions.get("PASS", 0) / N,
        "pct_moves": (total_moves / total_worker_actions * 100) if total_worker_actions else 0,
        "pct_work": (total_work / total_worker_actions * 100) if total_worker_actions else 0,
        "pct_pass": (agg_worker_actions.get("PASS", 0) / total_worker_actions * 100) if total_worker_actions else 0,
        "actions_by_type_per_game": {k: v / N for k, v in sorted(agg_worker_actions.items())},
        "movement_by_worker_per_game": {w: cnt / N for w, cnt in sorted(agg_movement_by_worker.items())},
        "movement_by_quadrant_per_game": {k: v / N for k, v in sorted(agg_movement_by_quad.items())},
        "movement_by_route_per_game": {k: v / N for k, v in sorted(agg_movement_by_route.items(), key=lambda x: -x[1])},
        "functional_route_per_game": {k: v / N for k, v in sorted(agg_movement_by_func_route.items(), key=lambda x: -x[1])},
        "idle_pass_by_worker_per_game": {k: v / N for k, v in sorted(agg_idle_pass.items())},
    }

    livestock_agg = {}
    for anim in ["COW", "SHEEP", "CHICKEN"]:
        tot_placed = sum(r["livestock_summary"][anim]["placed_count"] for r in results)
        tot_mech_max = sum(r["livestock_summary"][anim]["mechanically_max_units"] for r in results)
        tot_produced = sum(r["livestock_summary"][anim]["units_produced"] for r in results)
        tot_harvested = sum(r["livestock_summary"][anim]["harvested_units"] for r in results)
        tot_uncollected = sum(r["livestock_summary"][anim]["uncollected_end_units"] for r in results)
        tot_missed_care = sum(r["livestock_summary"][anim]["missed_care_opportunities"] for r in results)
        tot_escapes = sum(r["livestock_summary"][anim]["escapes"] for r in results)
        tot_fed = sum(r["livestock_summary"][anim]["feed_events"] for r in results)
        tot_cared = sum(r["livestock_summary"][anim]["care_events"] for r in results)

        livestock_agg[anim] = {
            "placed_per_game": tot_placed / N,
            "mechanically_max_yield_per_game": tot_mech_max / N,
            "actual_produced_per_game": tot_produced / N,
            "harvested_units_per_game": tot_harvested / N,
            "uncollected_end_per_game": tot_uncollected / N,
            "yield_gap_units_per_game": (tot_mech_max - tot_produced) / N,
            "yield_efficiency_pct": (tot_produced / tot_mech_max * 100) if tot_mech_max else 100.0,
            "harvest_efficiency_pct": (tot_harvested / tot_produced * 100) if tot_produced else 100.0,
            "fed_count_per_game": tot_fed / N,
            "cared_count_per_game": tot_cared / N,
            "missed_care_per_game": tot_missed_care / N,
            "escapes_per_game": tot_escapes / N,
        }

    tot_stockout_hours = sum(len(r["grain_stockout_events"]) for r in results)
    games_with_stockout = sum(1 for r in results if len(r["grain_stockout_events"]) > 0)
    wheat_sales_units = sum(r["cash_ledger"]["sells"]["WHEAT"]["units"] for r in results)
    wheat_sales_rev = sum(r["cash_ledger"]["sells"]["WHEAT"]["revenue"] for r in results)
    wheat_buys_units = sum(r["cash_ledger"]["buys_product"]["WHEAT"]["units"] for r in results)
    wheat_buys_cost = sum(r["cash_ledger"]["buys_product"]["WHEAT"]["cost"] for r in results)

    wheat_liquidity_summary = {
        "stockout_hours_per_game": tot_stockout_hours / N,
        "games_with_stockouts": games_with_stockout,
        "pct_games_with_stockout": (games_with_stockout / N * 100),
        "wheat_sold_units_per_game": wheat_sales_units / N,
        "wheat_sold_revenue_per_game": wheat_sales_rev / N,
        "mean_wheat_sale_price": (wheat_sales_rev / wheat_sales_units) if wheat_sales_units else 0,
        "wheat_bought_units_per_game": wheat_buys_units / N,
        "wheat_bought_cost_per_game": wheat_buys_cost / N,
        "mean_wheat_buy_price": (wheat_buys_cost / wheat_buys_units) if wheat_buys_units else 0,
    }

    discard_agg = defaultdict(int)
    discard_events_agg = defaultdict(int)
    for r in results:
        for item, d in r["shed_discards"].items():
            discard_agg[item] += d.get("units", 0)
            discard_events_agg[item] += d.get("count", 0)

    shed_discard_summary = {
        item: {
            "units_per_game": discard_agg[item] / N,
            "events_per_game": discard_events_agg[item] / N,
        } for item in sorted(discard_agg.keys())
    }

    market_funnel_agg = {}
    for prod in ["WHEAT", "MILK", "WOOL", "EGG", "CARROT", "MELON", "STRAWBERRY", "TOMATO", "FERTILIZER"]:
        produced = sum(r["market_funnel"][prod]["produced"] for r in results)
        harvested = sum(r["market_funnel"][prod]["harvested"] for r in results)
        sold = sum(r["market_funnel"][prod]["sold"] for r in results)
        revenue = sum(r["market_funnel"][prod]["revenue"] for r in results)
        discarded = sum(r["market_funnel"][prod]["discarded"] for r in results)
        final_shed = sum(r["market_funnel"][prod]["final_shed"] for r in results)
        final_worker = sum(r["market_funnel"][prod]["final_worker"] for r in results)
        final_unharv = sum(r["market_funnel"][prod]["final_unharvested"] for r in results)

        market_funnel_agg[prod] = {
            "produced_per_game": produced / N,
            "harvested_per_game": harvested / N,
            "sold_per_game": sold / N,
            "revenue_per_game": revenue / N,
            "mean_realized_price": (revenue / sold) if sold else 0,
            "discarded_per_game": discarded / N,
            "final_shed_per_game": final_shed / N,
            "final_worker_per_game": final_worker / N,
            "final_unharvested_per_game": final_unharv / N,
            "realization_pct": (sold / produced * 100) if produced else 0,
        }

    tot_unlocked_td = sum(r["tile_days_summary"]["unlocked_tile_days"] for r in results)
    tot_prod_td = sum(r["tile_days_summary"]["productively_planted_tile_days"] for r in results)
    tot_mature_td = sum(r["tile_days_summary"]["mature_waiting_harvest_tile_days"] for r in results)
    tot_struct_td = sum(r["tile_days_summary"]["structure_tile_days"] for r in results)
    tot_empty_td = sum(r["tile_days_summary"]["empty_available_tile_days"] for r in results)

    tile_summary = {
        "unlocked_tile_days_per_game": tot_unlocked_td / N,
        "productively_planted_tile_days_per_game": tot_prod_td / N,
        "mature_waiting_harvest_tile_days_per_game": tot_mature_td / N,
        "structure_tile_days_per_game": tot_struct_td / N,
        "empty_available_tile_days_per_game": tot_empty_td / N,
        "pct_productively_planted": (tot_prod_td / tot_unlocked_td * 100) if tot_unlocked_td else 0,
        "pct_mature_waiting": (tot_mature_td / tot_unlocked_td * 100) if tot_unlocked_td else 0,
        "pct_structure": (tot_struct_td / tot_unlocked_td * 100) if tot_unlocked_td else 0,
        "pct_empty_available": (tot_empty_td / tot_unlocked_td * 100) if tot_unlocked_td else 0,
    }

    agg_congestion_map = []
    for d in range(30):
        day_row = []
        for h in range(24):
            moves_sum = sum(r["congestion_map"][d][h]["move"] for r in results)
            crop_sum = sum(r["congestion_map"][d][h]["crop"] for r in results)
            livestock_sum = sum(r["congestion_map"][d][h]["livestock"] for r in results)
            harvest_sum = sum(r["congestion_map"][d][h]["harvest"] for r in results)
            logistics_sum = sum(r["congestion_map"][d][h]["logistics"] for r in results)
            pass_sum = sum(r["congestion_map"][d][h]["pass"] for r in results)
            blocked_sum = sum(r["congestion_map"][d][h]["blocked"] for r in results)
            shed_sum = sum(r["congestion_map"][d][h]["shed_units"] for r in results)
            wheat_sum = sum(r["congestion_map"][d][h]["wheat_units"] for r in results)
            stockout_sum = sum(r["congestion_map"][d][h]["stockouts"] for r in results)

            work_sum = crop_sum + livestock_sum + harvest_sum + logistics_sum
            total_actions_sum = work_sum + moves_sum + pass_sum + blocked_sum

            day_row.append({
                "day": d,
                "hour": h,
                "mean_workers": total_actions_sum / N,
                "mean_moves": moves_sum / N,
                "mean_work": work_sum / N,
                "mean_crop": crop_sum / N,
                "mean_livestock": livestock_sum / N,
                "mean_harvest": harvest_sum / N,
                "mean_logistics": logistics_sum / N,
                "mean_pass": pass_sum / N,
                "mean_blocked": blocked_sum / N,
                "mean_shed_units": shed_sum / N,
                "mean_wheat_units": wheat_sum / N,
                "stockout_games": stockout_sum,
            })
        agg_congestion_map.append(day_row)

    per_game = []
    for r in results:
        sc = r["scenario"]
        per_game.append({
            "seed": sc["seed"],
            "opponent": sc["opponent"],
            "seat": sc["seat"],
            "final_money": r["final_money"],
            "recon_error": r["recon_error"],
        })

    return {
        "n_games": N,
        "mean_final_cash": mean_cash,
        "median_final_cash": median_cash,
        "min_final_cash": min_cash,
        "max_final_cash": max_cash,
        "max_reconciliation_error": max_recon_error,
        "opp_summary": opp_summary,
        "seat_summary": seat_summary,
        "transit_summary": transit_summary,
        "livestock_summary": livestock_agg,
        "wheat_liquidity_summary": wheat_liquidity_summary,
        "shed_discard_summary": shed_discard_summary,
        "market_funnel_summary": market_funnel_agg,
        "tile_utilization_summary": tile_summary,
        "congestion_map": agg_congestion_map,
        "per_game": per_game,
    }


if __name__ == "__main__":
    main()
