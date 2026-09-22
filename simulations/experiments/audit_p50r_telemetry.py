#!/usr/bin/env python3
"""Kaggriculture P5.0-R Upgraded Telemetry Harness.

Runs the 100-game discovery panel (seeds 96,201–96,210, 5 opponents, 2 seats) against
authoritative baseline behavior (flag-OFF identical to 536f1e7).

Captures complete, state-exact decision snapshots for every Day 21-25 wheat planting event:
- day, hour, step
- money, shed inventory, all worker inventories
- worker positions (farmer + hands)
- all placed animals (species, coord, fed_today, consecutive_unfed, yield_units)
- all in-ground wheat tiles (coord, planted_day, crop_age, watered_today, consecutive_unwatered, yield_units, fertilized_until_day, max_lifespan_step)
- market inventory and prices
- assigned tasks / worker actions
- 100% exact cash reconciliation check: $3000 + Inflows - Outflows == Final Cash == Final Reward.
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
DIAGNOSTIC_SEEDS = list(range(96201, 96211))  # 10 fresh discovery seeds: 96,201–96,210

# All 50 physical tiles in core NW and NE quadrants
NW_COORDS = [(x, y) for y in range(5) for x in range(5)]
NE_COORDS = [(x, y) for y in range(5) for x in range(5, 10)]
CORE_50_COORDS = NW_COORDS + NE_COORDS
SHED_ACCESS_COORDS = [(4, 4), (5, 4)]


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


def _run_single_p50r_game(scenario):
    """Executes a single game with state-exact Day 21-25 decision snapshot capture."""
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

        # Telemetry cash structures
        tx_inflows = defaultdict(float)
        tx_inflows_units = defaultdict(int)
        tx_outflows = defaultdict(float)
        tx_outflows_units = defaultdict(int)

        # Full state snapshots for every Day 21-25 wheat planting decision
        wheat_decision_snapshots = []

        current_env_step = [0]
        current_day = [0]
        current_hour = [0]

        # Hook engine market transactions
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
                    if op == "SELL":
                        tx_inflows[item] += price
                        tx_inflows_units[item] += 1
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

            # 1. ALWAYS run agent decision FIRST
            act = module.agent(obs)

            # 2. Telemetry tracking
            try:
                farmer_act = act.get("farmer", ["PASS"]) if isinstance(act, dict) else ["PASS"]
                hands_acts = act.get("hands", []) if isinstance(act, dict) else []

                worker_actions_list = [("farmer", farm.get("farmer", [4, 4]), farmer_act)]
                for h_idx, h_pos in enumerate(farm.get("hands", [])):
                    h_act = hands_acts[h_idx] if h_idx < len(hands_acts) else ["PASS"]
                    worker_actions_list.append((f"hand_{h_idx}", h_pos, h_act))

                # Check for WHEAT planting on Days 21-25
                if 21 <= d <= 25:
                    for w_name, w_pos, action in worker_actions_list:
                        if not isinstance(action, list) or len(action) < 2:
                            continue
                        op = action[0]
                        crop = action[1]
                        if op == "PLANT" and crop == "WHEAT":
                            # CAPTURE FULL STATE-EXACT DECISION SNAPSHOT
                            fx, fy = w_pos[0], w_pos[1]

                            # 1. In-ground wheat tiles
                            in_ground_wheat = []
                            tiles_grid = farm.get("tiles", [])
                            for ty in range(len(tiles_grid)):
                                for tx in range(len(tiles_grid[ty])):
                                    t = tiles_grid[ty][tx]
                                    if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop") == "WHEAT":
                                        in_ground_wheat.append({
                                            "coord": [tx, ty],
                                            "planted_day": t.get("planted_day"),
                                            "crop_age": d - t.get("planted_day", d),
                                            "consecutive_unwatered": t.get("consecutive_unwatered", 0),
                                            "watered_today": t.get("watered_today", False),
                                            "fertilized_until_day": t.get("fertilized_until_day", -1),
                                            "yield_units": t.get("yield_units", 1),
                                            "max_lifespan_step": t.get("max_lifespan_step", -1),
                                        })

                            # 2. All placed animals
                            animals_present = []
                            for ty in range(len(tiles_grid)):
                                for tx in range(len(tiles_grid[ty])):
                                    t = tiles_grid[ty][tx]
                                    if isinstance(t, dict) and t.get("animal"):
                                        animals_present.append({
                                            "coord": [tx, ty],
                                            "animal": t.get("animal"),
                                            "placed_day": t.get("placed_day"),
                                            "consecutive_unfed": t.get("consecutive_unfed", 0),
                                            "fed_today": t.get("fed_today", False),
                                            "cared_today": t.get("cared_today", False),
                                            "yield_units": t.get("yield_units", 0),
                                            "pending_care_bonus": t.get("pending_care_bonus", 0),
                                        })

                            # 3. Market queues / orders emitted this turn
                            mkt_orders = act.get("market", {}) if isinstance(act, dict) else {}

                            # 4. Inventories & money
                            money = farm.get("money", 0)
                            shed = dict(priv.get("shed", {}))
                            seeds = dict(priv.get("seeds", {}))
                            inventories = [dict(inv) for inv in priv.get("inventories", [])]

                            # 5. Worker positions
                            worker_positions = {
                                "farmer": list(farm.get("farmer", [4, 4])),
                                "hands": [list(pos) for pos in farm.get("hands", [])],
                            }

                            snapshot = {
                                "seed": seed,
                                "opponent": opponent,
                                "seat": seat,
                                "step": step,
                                "day": d,
                                "hour": h,
                                "worker_name": w_name,
                                "candidate_tile": [fx, fy],
                                "money": money,
                                "shed": shed,
                                "seeds": seeds,
                                "inventories": inventories,
                                "worker_positions": worker_positions,
                                "animals": animals_present,
                                "in_ground_wheat": in_ground_wheat,
                                "market_inventory": dict(mkt.get("inventory", {})),
                                "market_prices": dict(mkt.get("prices", {})),
                                "market_orders_emitted": mkt_orders,
                            }
                            wheat_decision_snapshots.append(snapshot)

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

        kg._process_market = orig_process_market

        final_reward = env.state[seat].reward
        final_money = env.state[seat].observation.farms[seat]["money"]
        total_in = sum(tx_inflows.values())
        total_out = sum(tx_outflows.values())
        calc_cash = 3000.0 + total_in - total_out

        assert abs(calc_cash - final_money) < 1e-4, f"Cash mismatch: calc={calc_cash} vs obs={final_money}"
        assert abs(calc_cash - final_reward) < 1e-4, f"Reward mismatch: calc={calc_cash} vs rew={final_reward}"

        return {
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "final_reward": final_reward,
            "final_money": final_money,
            "total_inflows": total_in,
            "total_outflows": total_out,
            "wheat_decision_snapshots": wheat_decision_snapshots,
        }

    except Exception as e:
        traceback.print_exc()
        raise e


def main():
    import argparse
    parser = argparse.ArgumentParser(description="P5.0-R Upgraded Telemetry Harness")
    parser.add_argument("--workers", type=int, default=7, help="Parallel workers")
    args = parser.parse_args()

    scenarios = []
    for seed in DIAGNOSTIC_SEEDS:
        for opp in OPPONENTS:
            for seat in (0, 1):
                scenarios.append({"seed": seed, "opponent": opp, "seat": seat})

    print(f"Launching P5.0-R Telemetry Run: {len(scenarios)} games across 10 fresh seeds ({DIAGNOSTIC_SEEDS[0]}..{DIAGNOSTIC_SEEDS[-1]})...")
    start_t = time.time()

    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_scen = {executor.submit(_run_single_p50r_game, s): s for s in scenarios}
        for future in as_completed(future_to_scen):
            s = future_to_scen[future]
            try:
                res = future.result()
                results.append(res)
                print(f"  [Done] Seed {res['seed']} vs {res['opponent']:20s} Seat {res['seat']} -> Score: ${res['final_reward']:,.2f} | Snapshots: {len(res['wheat_decision_snapshots'])}")
            except Exception as e:
                print(f"  [ERROR] Seed {s['seed']} vs {s['opponent']} Seat {s['seat']}: {e}")
                raise e

    elapsed = time.time() - start_t
    print(f"\nCompleted {len(results)} games in {elapsed:.1f}s ({elapsed/len(results):.2f}s/game)")

    out_dir = os.path.join(ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_json_gz = os.path.join(out_dir, "p50r_telemetry_100g.json.gz")
    out_json = os.path.join(out_dir, "p50r_telemetry_100g.json")

    # Save gzipped and uncompressed
    json_bytes = json.dumps(results, indent=2).encode("utf-8")
    with open(out_json, "wb") as f:
        f.write(json_bytes)
    with gzip.open(out_json_gz, "wb") as f:
        f.write(json_bytes)

    print(f"Saved complete P5.0-R decision snapshots to:")
    print(f"  Uncompressed: {out_json} ({len(json_bytes):,} bytes)")
    print(f"  Compressed:   {out_json_gz} ({os.path.getsize(out_json_gz):,} bytes)")


if __name__ == "__main__":
    main()
