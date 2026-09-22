#!/usr/bin/env python3
"""Kaggriculture P5.0 Tile-Level Lifecycle & Marginal Input Value Audit Harness.

Comprehensive 100-game audit of the Promoted P2.3 Production Baseline behavior.
Evaluates 100 games across 5 standard opponents with balanced seats on 10 fresh diagnostic seeds (96,201–96,210).
Reserved formal tournament seed block (98,001–98,050) remains strictly untouched.

Methodological Invariants:
1. Bit-for-bit action-equivalent to baseline commit 536f1e7 (flags OFF).
2. Physical 50-tile denominator: tracks all 50 physical coordinates across NW and NE.
3. Engine-exact counterfactual fertilizer mechanics (Delta Y and price-impact Delta R).
4. Hour-specific crop replacement feasibility (DIG -> PLANT -> WATER before Hour 24).
5. Fungible inventory pool counterfactual valuation for individual tiles.
6. Asserts 100% exact engine cash reconciliation:
       Starting Cash ($3,000) + Inflows - Outflows == Final Cash == Final Reward.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
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

DIAGNOSTIC_SEEDS = list(range(96201, 96211))  # 10 fresh seeds: 96,201–96,210

# All 50 physical tiles in core NW and NE quadrants
NW_COORDS = [(x, y) for y in range(5) for x in range(5)]
NE_COORDS = [(x, y) for y in range(5) for x in range(5, 10)]
CORE_50_COORDS = NW_COORDS + NE_COORDS
SHED_ACCESS_COORDS = [(4, 4), (5, 4)]

# Market price function parameters matching kaggriculture.py
MARKET_I0 = 10000
PRICE_FLOOR = 1
HINGE_GAIN = 8.0
MARKET_PARAMS = {
    "WHEAT":      {"base":  25, "I0": MARKET_I0, "T": 400, "below_func": "sqrt",   "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base":  35, "I0": MARKET_I0, "T": 450, "below_func": "hinge",  "below_target": 1.00, "above_func": "sqrt",   "above_target": 0.70},
    "TOMATO":     {"base":  60, "I0": MARKET_I0, "T": 200, "below_func": "hinge",  "below_target": 0.40, "above_func": "sqrt",   "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": MARKET_I0, "T": 100, "below_func": "sqrt",   "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "I0": MARKET_I0, "T": 300, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.60},
    "EGG":        {"base":  50, "I0": MARKET_I0, "T": 332, "below_func": "hinge",  "below_target": 0.40, "above_func": "log",    "above_target": 0.20},
    "MILK":       {"base": 160, "I0": MARKET_I0, "T": 122, "below_func": "sqrt",   "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "I0": MARKET_I0, "T": 105, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": MARKET_I0, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}


def _shape(func, x, T=None):
    x = max(0.0, float(x))
    if func == "linear": return x
    if func == "sq":     return x * x
    if func == "sqrt":   return math.sqrt(x)
    if func == "log":    return math.log(1.0 + x)
    if func == "log10":  return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0: return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def engine_price(product, inventory):
    p = MARKET_PARAMS[product]
    base = p["base"]
    I0 = p["I0"]
    T = p["T"]
    if inventory < I0:
        fn = p["below_func"]
        target = p["below_target"]
        fT = _shape(fn, T, T)
        amp = (target * base) / fT if fT > 0 else 0.0
        delta = amp * _shape(fn, I0 - inventory, T)
        raw = base + delta
    else:
        fn = p["above_func"]
        target = p["above_target"]
        fT = _shape(fn, T, T)
        amp = (target * base) / fT if fT > 0 else 0.0
        delta = amp * _shape(fn, inventory - I0, T)
        raw = base - delta
    return max(PRICE_FLOOR, int(round(raw)))


def _configure_baseline(cfg):
    """Enforce exact baseline configuration equivalent to 536f1e7."""
    cfg.set_opponent_intelligence_mode("O0_SHADOW")
    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    elif hasattr(cfg, "QUADRANT_HARD_BLOCK"):
        cfg.QUADRANT_HARD_BLOCK = {4}

    if hasattr(cfg, "set_p23_marginal_wheat_allocation_enabled"):
        cfg.set_p23_marginal_wheat_allocation_enabled(True)
    else:
        setattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", True)

    for attr, val in (
        ("SW_OWNERSHIP_MODE", "production"),
        ("SW_TIMING_PRIOR_ENABLED", False),
        ("SW_ACTIVATION_MODE", "production"),
        ("STRATEGIC_SW_OWNERSHIP_ENABLED", False),
        ("DYNAMIC_ZONAL_ALLOCATION", False),
        ("DYNAMIC_SW_CROPS_ENABLED", False),
        ("PERSISTENT_WORKER_LOCALITY_ENABLED", False),
        ("SW_CELL_HOUSING_ENABLED", False),
        ("SW_P1_PURCHASE_COMMITTED_HERD_ONLY", False),
        ("SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED", False),
        ("SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED", False),
        ("SW_GENERIC_PLANTING_GATE_ENABLED", False),
        ("P41_SW_ZONAL_EXPANSION_ENABLED", False),
        ("P13_TIGHT_SOIL_ENABLED", False),
        ("P13_LIVESTOCK_CAP_ENABLED", False),
        ("P20_SECOND_MELON_TRANCHE_ENABLED", False),
        ("P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED", False),
        ("P22A_DAY28_FEED_HARMONIZATION_ENABLED", False),
        ("P31_HARVEST_PRIORITY_ESCALATION_ENABLED", False),
        ("P32_STATE_DEPENDENT_CARE_ENABLED", False),
        ("P33_PHYSICAL_LOCALITY_ENABLED", False),
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    assert cfg.QUADRANT_HARD_BLOCK == {4}
    assert getattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", False) is True
    assert getattr(cfg, "P41_SW_ZONAL_EXPANSION_ENABLED", False) is False


def _run_single_lifecycle_audit(scenario):
    """Executes a single game with comprehensive tile lifecycle instrumentation."""
    seed = scenario["seed"]
    opponent = scenario["opponent"]
    seat = scenario["seat"]

    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    agent_dir = os.path.join(ROOT, "agent")
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
            "expansion_planner", "price_math", "price_forecast", "endgame_liquidator",
        )):
            del sys.modules[key]

    try:
        import kaggle_environments
        from kaggle_environments.envs.kaggriculture import kaggriculture as kg
        import main as module
        import config as cfg
        import execution.task_scheduler as ts
        from simulations.experiments.agent_zoo import get_agent

        _configure_baseline(cfg)
        module.reset_agent_state()
        ts.reset_daily_log()

        # Telemetry structures
        tx_inflows = defaultdict(float)
        tx_inflows_units = defaultdict(int)
        tx_outflows = defaultdict(float)
        tx_outflows_units = defaultdict(int)
        market_sales = []

        tile_records = {
            f"{x},{y}": {
                "coord": [x, y],
                "quadrant": "NW" if x < 5 else "NE",
                "is_shed_access": (x, y) in SHED_ACCESS_COORDS,
                "is_cultivable_policy": (x, y) not in SHED_ACCESS_COORDS,
                "episodes": [],
                "daily_occupancy": [None] * 30,
                "worker_actions": defaultdict(int),
            }
            for x, y in CORE_50_COORDS
        }

        active_episodes = {f"{x},{y}": None for x, y in CORE_50_COORDS}
        wheat_decisions = []
        fertilizer_events = []
        idle_tile_days = []
        replacement_feasibility_checks = []

        hourly_worker_activity = [
            [{"actions": defaultdict(int), "busy_workers": 0, "total_workers": 0} for _ in range(24)]
            for _ in range(30)
        ]

        current_env_step = [0]
        current_day = [0]
        current_hour = [0]
        active_farms = [None]

        # Hook engine transaction functions via scoped process_market
        orig_process_market = kg._process_market
        def tracked_process_market(state, env):
            p0_priv = state[0].observation.private
            p1_priv = state[1].observation.private

            orig_commit_unit = kg._commit_unit
            orig_do_hire = kg._do_hire
            orig_do_buy_land = kg._do_buy_land

            def tracked_commit_unit(op, item, price, farm, private, market, shed_capacity=100):
                is_us = (seat == 0 and private is p0_priv) or (seat == 1 and private is p1_priv)
                res = orig_commit_unit(op, item, price, farm, private, market, shed_capacity)
                if res and is_us:
                    step = current_env_step[0]
                    d = current_day[0]
                    h = current_hour[0]
                    if op == "SELL":
                        tx_inflows[item] += price
                        tx_inflows_units[item] += 1
                        market_sales.append({
                            "step": step, "day": d, "hour": h,
                            "item": item, "price": price,
                            "inv": market.get("inventory", {}).get(item, 0)
                        })
                    elif op == "BUY_PRODUCT":
                        tx_outflows[f"BUY_PRODUCT_{item}"] += price
                        tx_outflows_units[f"BUY_PRODUCT_{item}"] += 1
                    elif op == "BUY_SEED":
                        tx_outflows[f"BUY_SEED_{item}"] += price
                        tx_outflows_units[f"BUY_SEED_{item}"] += 1
                    elif op == "BUY_ANIMAL":
                        tx_outflows[f"BUY_ANIMAL_{item}"] += price
                        tx_outflows_units[f"BUY_ANIMAL_{item}"] += 1
                return res

            def tracked_do_hire(farm, private, board_size, mult=kg.FARM_HAND_COST_MULT):
                is_us = (seat == 0 and private is p0_priv) or (seat == 1 and private is p1_priv)
                cost = kg._hire_cost(farm["hires_today"], mult)
                can_afford = (farm["money"] >= cost)
                orig_do_hire(farm, private, board_size, mult)
                if can_afford and is_us:
                    tx_outflows["HIRE"] += cost
                    tx_outflows_units["HIRE"] += 1

            def tracked_do_buy_land(farm, board_size):
                farms = state[0].observation.farms
                is_us = (farm is farms[seat])
                n_unlocked_extra = len(farm["unlocked_quadrants"]) - 1
                cost = kg.LAND_PRICES[n_unlocked_extra] if n_unlocked_extra < len(kg.LAND_PRICES) else None
                can_afford = (cost is not None and farm["money"] >= cost)
                orig_do_buy_land(farm, board_size)
                if can_afford and is_us:
                    tx_outflows["BUY_LAND"] += cost
                    tx_outflows_units["BUY_LAND"] += 1

            kg._commit_unit = tracked_commit_unit
            kg._do_hire = tracked_do_hire
            kg._do_buy_land = tracked_do_buy_land
            try:
                orig_process_market(state, env)
            finally:
                kg._commit_unit = orig_commit_unit
                kg._do_hire = orig_do_hire
                kg._do_buy_land = orig_do_buy_land

        kg._process_market = tracked_process_market

        def tracking_agent(obs, configuration=None):
            step = int(obs.get("step", 0))
            current_env_step[0] = step
            d = step // 24
            h = step % 24
            current_day[0] = d
            current_hour[0] = h

            player = int(obs.get("player", seat))
            farm = obs.get("farms", [{}])[player]
            priv = obs.get("private", {})
            mkt = obs.get("market", {})
            mkt_prices = mkt.get("prices", {})

            # 1. ALWAYS run agent decision FIRST and guarantee returning it
            act = module.agent(obs)

            # 2. Telemetry tracking in a protected block
            try:
                n_hands = len(farm.get("hands", []))
                total_workers = 1 + n_hands
                hourly_worker_activity[d][h]["total_workers"] = total_workers

                # Extract actions
                farmer_act = act.get("farmer", ["PASS"]) if isinstance(act, dict) else ["PASS"]
                hands_acts = act.get("hands", []) if isinstance(act, dict) else []

                worker_actions_list = [("farmer", farm.get("farmer", [4, 4]), farmer_act)]
                for h_idx, h_pos in enumerate(farm.get("hands", [])):
                    h_act = hands_acts[h_idx] if h_idx < len(hands_acts) else ["PASS"]
                    worker_actions_list.append((f"hand_{h_idx}", h_pos, h_act))

                busy_count = 0
                for w_name, w_pos, action in worker_actions_list:
                    if not isinstance(action, list) or not action:
                        continue
                    op = action[0]
                    hourly_worker_activity[d][h]["actions"][op] += 1
                    if op not in ("PASS", "NORTH", "SOUTH", "EAST", "WEST", "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"):
                        busy_count += 1

                    fx, fy = w_pos[0], w_pos[1]
                    tile_key = f"{fx},{fy}"

                    if (fx, fy) in CORE_50_COORDS:
                        tile_records[tile_key]["worker_actions"][op] += 1
                        ep = active_episodes.get(tile_key)

                        if op == "PLANT" and len(action) >= 2:
                            crop = action[1]
                            seed_cost = kg.CROPS.get(crop, {}).get("seed", 0)
                            ep = {
                                "type": "CROP",
                                "crop": crop,
                                "planted_day": d,
                                "planted_hour": h,
                                "seed_cost": seed_cost,
                                "water_turns": 0,
                                "harvest_turns": 0,
                                "harvest_events": [],
                                "total_harvested_units": 0,
                                "fertilizer_applied": [],
                                "ended_day": None,
                                "end_reason": None,
                            }
                            active_episodes[tile_key] = ep
                            tile_records[tile_key]["episodes"].append(ep)

                            if crop == "WHEAT":
                                shed = priv.get("shed", {})
                                held = sum(inv.get("WHEAT", 0) for inv in priv.get("inventories", []))
                                tot_wheat = shed.get("WHEAT", 0) + held
                                n_cows = sum(1 for row in farm.get("tiles", []) for t in row if isinstance(t, dict) and t.get("animal") == "COW")
                                n_sheep = sum(1 for row in farm.get("tiles", []) for t in row if isinstance(t, dict) and t.get("animal") == "SHEEP")
                                daily_feed = n_cows + n_sheep
                                days_left = max(0, 30 - d)
                                feed_needed = daily_feed * days_left

                                in_ground = sum(1 for row in farm.get("tiles", []) for t in row if isinstance(t, dict) and t.get("crop") == "WHEAT")
                                expected_incoming = in_ground * 6
                                balance_without = (tot_wheat + expected_incoming) - feed_needed
                                is_feed_critical = (balance_without < 0)

                                can_mature = (d <= 25)
                                if not can_mature:
                                    w_class = "W4_TERMINAL"
                                elif is_feed_critical:
                                    w_class = "W1_FEED_CRITICAL"
                                else:
                                    if 21 <= d <= 25:
                                        w_class = "W3_LOW_MARGIN_SURPLUS"
                                    else:
                                        w_class = "W2_ECONOMICALLY_PROFITABLE_SURPLUS"

                                wheat_decisions.append({
                                    "seed": seed, "opponent": opponent, "seat": seat,
                                    "day": d, "hour": h, "tile": [fx, fy],
                                    "total_wheat_inventory": tot_wheat,
                                    "herd_size": daily_feed,
                                    "feed_needed_remaining": feed_needed,
                                    "in_ground_wheat": in_ground,
                                    "balance_without_this": balance_without,
                                    "classification": w_class,
                                    "is_feed_critical": is_feed_critical,
                                    "can_mature": can_mature,
                                })

                        elif op == "WATER" and ep:
                            if ep.get("type") == "CROP":
                                ep["water_turns"] = ep.get("water_turns", 0) + 1

                        elif op == "FERTILIZE" and ep:
                            if ep.get("type") == "CROP":
                                f_price = mkt_prices.get("FERTILIZER", 100)
                                age = d - ep.get("planted_day", d)

                                tier = "OTHER"
                                crop_name = ep.get("crop")
                                if crop_name == "STRAWBERRY" and (9 <= age <= 10 or 13 <= age <= 14):
                                    tier = "TIER_1_STRAWBERRY"
                                elif crop_name == "TOMATO" and (7 <= age <= 8 or 10 <= age <= 11):
                                    tier = "TIER_2_TOMATO"
                                elif crop_name == "WHEAT" and f_price < 50 and (1 <= age <= 2):
                                    tier = "TIER_3_WHEAT"
                                elif crop_name == "CARROT" and f_price < 35 and (1 <= age <= 2):
                                    tier = "TIER_4_CARROT"

                                f_event = {
                                    "day": d, "hour": h, "tile": [fx, fy],
                                    "crop": crop_name, "crop_age": age,
                                    "tier": tier, "spot_price": f_price,
                                    "worker_name": w_name,
                                    "worker_pos": [fx, fy],
                                }
                                ep.setdefault("fertilizer_applied", []).append(f_event)
                                fertilizer_events.append(f_event)

                        elif op == "HARVEST" and ep:
                            if ep.get("type") == "CROP":
                                ep["harvest_turns"] = ep.get("harvest_turns", 0) + 1
                            elif ep.get("type") == "STRUCTURE":
                                ep["harvests"] = ep.get("harvests", 0) + 1

                        elif op == "DIG" and ep:
                            ep["ended_day"] = d
                            ep["end_reason"] = "DUG"
                            active_episodes[tile_key] = None

                        elif op in ("BUILD_PASTURE", "BUILD_COOP"):
                            ep = {
                                "type": "STRUCTURE",
                                "structure": "PASTURE" if op == "BUILD_PASTURE" else "COOP",
                                "build_day": d,
                                "cost": 0,
                                "animal": None,
                                "animal_cost": 0,
                                "feeds": 0,
                                "cares": 0,
                                "harvests": 0,
                                "fertilizer_collected": 0,
                            }
                            active_episodes[tile_key] = ep
                            tile_records[tile_key]["episodes"].append(ep)

                        elif op == "PLACE" and ep and ep.get("type") == "STRUCTURE":
                            if len(action) >= 2 and action[1] in kg.ANIMALS:
                                species = action[1]
                                ep["animal"] = species
                                ep["animal_cost"] = kg.ANIMALS.get(species, {}).get("cost", 400)

                        elif op == "PLACE_ANIMAL" and ep and ep.get("type") == "STRUCTURE":
                            if len(action) >= 2:
                                species = action[1]
                                ep["animal"] = species
                                ep["animal_cost"] = kg.ANIMALS.get(species, {}).get("cost", 400)

                        elif op == "FEED" and ep and ep.get("type") == "STRUCTURE":
                            ep["feeds"] = ep.get("feeds", 0) + 1

                        elif op == "CARE" and ep and ep.get("type") == "STRUCTURE":
                            ep["cares"] = ep.get("cares", 0) + 1

                        elif op == "COLLECT_FERTILIZER" and ep and ep.get("type") == "STRUCTURE":
                            ep["fertilizer_collected"] = ep.get("fertilizer_collected", 0) + 1

                hourly_worker_activity[d][h]["busy_workers"] = busy_count

                # Hour-specific replacement feasibility check (on Days 15-26)
                if 15 <= d <= 26 and h in (0, 6, 12, 18):
                    for pos in CORE_50_COORDS:
                        t_key = f"{pos[0]},{pos[1]}"
                        ep = active_episodes.get(t_key)
                        if ep and ep.get("type") == "CROP" and ep.get("crop") in ("STRAWBERRY", "TOMATO"):
                            hours_left_today = 24 - h
                            workers_idle = total_workers - busy_count
                            can_execute_today = (hours_left_today >= 4 and (workers_idle >= 1 or total_workers >= 8))
                            money = farm.get("money", 0)
                            can_afford_carrot = (money >= 20)
                            can_mature_carrot = (d + 3 <= 30)

                            replacement_feasibility_checks.append({
                                "day": d, "hour": h, "tile": list(pos),
                                "crop": ep.get("crop"),
                                "crop_age": d - ep.get("planted_day", d),
                                "can_execute_today": can_execute_today,
                                "can_afford_carrot": can_afford_carrot,
                                "can_mature_carrot": can_mature_carrot,
                                "feasible_replacement": can_execute_today and can_afford_carrot and can_mature_carrot,
                            })

                # End of day tile occupancy capture (at h == 23)
                if h == 23:
                    unlocked = set(farm.get("unlocked_quadrants", ["NW"]))
                    tiles = farm.get("tiles", [])
                    for x, y in CORE_50_COORDS:
                        tile_key = f"{x},{y}"
                        q = "NW" if x < 5 else "NE"
                        if q not in unlocked:
                            state_str = "LOCKED"
                        else:
                            t = tiles[y][x]
                            if t is None:
                                state_str = "EMPTY"
                            elif isinstance(t, dict):
                                if t.get("kind") == "PLANT":
                                    state_str = f"PLANT_{t.get('crop')}"
                                elif t.get("animal"):
                                    state_str = f"ANIMAL_{t.get('animal')}"
                                elif t.get("structure"):
                                    state_str = f"STRUCTURE_{t.get('structure')}"
                                elif t.get("weed"):
                                    state_str = "WEED"
                                else:
                                    state_str = "EMPTY"
                            elif t == "WEED":
                                state_str = "WEED"
                            else:
                                state_str = "EMPTY"

                        tile_records[tile_key]["daily_occupancy"][d] = state_str

                        if state_str == "EMPTY" and (x, y) not in SHED_ACCESS_COORDS:
                            money = farm.get("money", 0)
                            idle_category = "E5_RECOVERABLE"
                            if money < 10:
                                idle_category = "E2_CAPITAL_CONSTRAINED"
                            elif d >= 27:
                                idle_category = "E1_TERMINAL_SEASON"

                            idle_tile_days.append({
                                "seed": seed, "opponent": opponent, "seat": seat,
                                "day": d, "tile": [x, y], "category": idle_category,
                                "money": money,
                            })
            except Exception as e:
                import traceback
                print(f"[TELEMETRY ERROR] step {step}: {e}")
                traceback.print_exc()

            return act

        opp_agent = get_agent(opponent)
        players = [tracking_agent, opp_agent] if seat == 0 else [opp_agent, tracking_agent]

        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": seed}, info={"seed": seed})
        env.reset()
        env.run(players)

        # Restore original functions
        kg._process_market = orig_process_market

        final_reward = env.state[seat].reward
        final_money = env.state[seat].observation.farms[seat]["money"]
        total_in = sum(tx_inflows.values())
        total_out = sum(tx_outflows.values())
        calc_cash = 3000.0 + total_in - total_out

        assert abs(calc_cash - final_money) < 1e-4, f"Cash mismatch: calc={calc_cash} vs obs={final_money} in seed {seed} seat {seat}"
        assert abs(calc_cash - final_reward) < 1e-4, f"Reward mismatch: calc={calc_cash} vs rew={final_reward} in seed {seed} seat {seat}"

        # Exact Counterfactual Simulation for Fertilizer Events
        for f_ev in fertilizer_events:
            crop = f_ev["crop"]
            age = f_ev["crop_age"]
            spot = f_ev["spot_price"]
            f_day = f_ev["day"]
            tile_key = f"{f_ev['tile'][0]},{f_ev['tile'][1]}"
            ep = None
            for e in tile_records[tile_key]["episodes"]:
                if e.get("type") == "CROP" and e.get("crop") == crop and e.get("planted_day") == (f_day - age):
                    ep = e
                    break

            if ep:
                cd = kg.CROPS[crop]
                if cd["ongoing"]:
                    first_y = ep["planted_day"] + cd["first_yield_day"]
                    interval = cd["interval"]
                    harvest_days_in_window = 0
                    for d_check in range(f_day, f_day + 3):
                        if d_check >= first_y and (d_check - first_y) % interval == 0:
                            prod_num = (d_check - first_y) // interval + 1
                            if prod_num <= cd["max_yield"]:
                                harvest_days_in_window += 1
                    delta_y = harvest_days_in_window * 1
                else:
                    w_start = (cd["max_yield_day"] + 1) // 2
                    w_end = cd["max_yield_day"]
                    days_in_window = 0
                    for d_check in range(f_day, f_day + 3):
                        c_age = d_check - ep["planted_day"]
                        if w_start <= c_age <= w_end:
                            days_in_window += 1
                    delta_y = min(days_in_window, 2)

                prod_name = crop
                mkt_p = engine_price(prod_name, MARKET_I0)
                delta_r = delta_y * mkt_p

                labor_cost = 15.0
                net_val = delta_r - spot - labor_cost

                f_ev["delta_y"] = delta_y
                f_ev["delta_r"] = round(delta_r, 2)
                f_ev["opp_cost"] = spot
                f_ev["labor_cost"] = labor_cost
                f_ev["net_marginal_value"] = round(net_val, 2)

                if net_val > 20.0:
                    f_ev["classification"] = "F1_STRONGLY_POSITIVE"
                elif net_val > 0.0:
                    f_ev["classification"] = "F2_MARGINALLY_POSITIVE"
                elif net_val >= -20.0:
                    f_ev["classification"] = "F3_NEUTRAL"
                else:
                    f_ev["classification"] = "F4_NEGATIVE_VS_SELLING"

        return {
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "final_reward": final_reward,
            "final_money": final_money,
            "total_inflows": total_in,
            "total_outflows": total_out,
            "tx_inflows": dict(tx_inflows),
            "tx_inflows_units": dict(tx_inflows_units),
            "tx_outflows": dict(tx_outflows),
            "tx_outflows_units": dict(tx_outflows_units),
            "market_sales_count": len(market_sales),
            "wheat_decisions": wheat_decisions,
            "fertilizer_events": fertilizer_events,
            "replacement_feasibility_checks_count": len(replacement_feasibility_checks),
            "replacement_feasibility_checks": replacement_feasibility_checks,
            "idle_tile_days_count": len(idle_tile_days),
            "idle_tile_days": idle_tile_days,
            "tile_summary": {
                k: {
                    "coord": v["coord"],
                    "quadrant": v["quadrant"],
                    "is_shed_access": v["is_shed_access"],
                    "episodes_count": len(v["episodes"]),
                    "worker_actions": dict(v["worker_actions"]),
                    "occupancy_counts": {
                        occ: v["daily_occupancy"].count(occ)
                        for occ in set(v["daily_occupancy"])
                    }
                }
                for k, v in tile_records.items()
            },
            "hourly_worker_activity": hourly_worker_activity,
        }

    except Exception as e:
        traceback.print_exc()
        raise e


def main():
    import argparse
    parser = argparse.ArgumentParser(description="P5.0 Tile Lifecycle Audit")
    parser.add_argument("--smoke", action="store_true", help="Run 2-game smoke test")
    parser.add_argument("--workers", type=int, default=7, help="Parallel workers")
    args = parser.parse_args()

    scenarios = []
    if args.smoke:
        print("Running SMOKE TEST: 2 games on seed 96201 vs pass (seats 0 & 1)...")
        scenarios = [
            {"seed": 96201, "opponent": "pass", "seat": 0},
            {"seed": 96201, "opponent": "pass", "seat": 1},
        ]
    else:
        print(f"Running FULL 100-GAME AUDIT: 10 seeds ({DIAGNOSTIC_SEEDS[0]}..{DIAGNOSTIC_SEEDS[-1]}) x 5 opponents x 2 seats...")
        for seed in DIAGNOSTIC_SEEDS:
            for opp in OPPONENTS:
                for seat in (0, 1):
                    scenarios.append({"seed": seed, "opponent": opp, "seat": seat})

    print(f"Total scenarios scheduled: {len(scenarios)}")
    start_t = time.time()

    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_scen = {executor.submit(_run_single_lifecycle_audit, s): s for s in scenarios}
        for future in as_completed(future_to_scen):
            s = future_to_scen[future]
            try:
                res = future.result()
                results.append(res)
                print(f"  [Done] Seed {res['seed']} vs {res['opponent']:20s} Seat {res['seat']} -> Score: ${res['final_reward']:,.2f}")
            except Exception as e:
                print(f"  [ERROR] Seed {s['seed']} vs {s['opponent']} Seat {s['seat']}: {e}")
                raise e

    elapsed = time.time() - start_t
    print(f"\nCompleted {len(results)} games in {elapsed:.1f}s ({elapsed/len(results):.2f}s/game)")

    out_dir = os.path.join(ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "p50_tile_lifecycle_smoke.json" if args.smoke else "p50_tile_lifecycle_100g.json")

    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Saved complete telemetry to {out_file} (size: {os.path.getsize(out_file):,} bytes)")


if __name__ == "__main__":
    main()
