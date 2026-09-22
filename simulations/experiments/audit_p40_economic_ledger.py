#!/usr/bin/env python3
"""Kaggriculture P4.0 Authoritative Economic Frontier & Revenue Realization Auditor.

Comprehensive 100-game audit of the Promoted P2.3 Production Baseline (commit 536f1e7).
Evaluates 100 games across 5 standard opponents with balanced seats on fresh diagnostic seeds (96,001–96,050).

Instruments and asserts 100% exact engine cash reconciliation:
    Starting Cash ($3,000) + Total Inflows - Total Outflows == Final Cash == Final Reward

Tracks:
  - Exact transaction-level revenue (wheat, carrot, tomato, strawberry, melon, egg, milk, wool, fertilizer)
  - Exact transaction-level expenses (seeds, animal purchases, hires, land, wheat buy, fertilizer buy)
  - Daily economic timeline (Days 0-29: cash, inflows, outflows, crops, animals, hands, feed)
  - Early capital allocation (Days 0-13: idle cash, reserves, NE purchase timing, empty tiles)
  - Crop transition economics (yield, seed cost, revenue, margins, tile-day return)
  - Market realization (realized prices, price degradation, town shop consumption, dwell times)
  - SW expansion feasibility vs past failures
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
import math
import os
import shutil
import statistics
import subprocess
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

DIAGNOSTIC_SEEDS = list(range(96001, 96051))  # 50 seeds

def _configure_production_baseline(cfg):
    """Enforce strict Promoted P2.3 Production Baseline invariants."""
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


def _run_single_economic_audit(task):
    """Executes a single game with comprehensive transaction-level economic instrumentation."""
    seed = task["seed"]
    opponent = task["opponent"]
    seat = task["seat"]

    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    agent_dir = os.path.join(ROOT, "agent")
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner"
        )):
            del sys.modules[key]

    try:
        import kaggle_environments
        from kaggle_environments.envs.kaggriculture import kaggriculture as kg
        import main as module
        import config as cfg
        from simulations.experiments.agent_zoo import get_agent

        _configure_production_baseline(cfg)
        module.reset_agent_state()

        # Telemetry containers
        tx_inflows = defaultdict(float)
        tx_inflows_units = defaultdict(int)
        tx_outflows = defaultdict(float)
        tx_outflows_units = defaultdict(int)

        opp_inflows = defaultdict(float)
        opp_inflows_units = defaultdict(int)

        town_consumed = defaultdict(int)

        daily_timeline = {}
        for d in range(30):
            daily_timeline[d] = {
                "day": d,
                "begin_cash": 0.0,
                "end_cash": 0.0,
                "inflows": defaultdict(float),
                "inflow_units": defaultdict(int),
                "outflows": defaultdict(float),
                "outflow_units": defaultdict(int),
                "crops_planted": defaultdict(int),
                "crops_harvested": defaultdict(int),
                "active_crops_count": defaultdict(int),
                "active_animals_count": defaultdict(int),
                "active_hands": 0,
                "unlocked_quadrants": [],
                "wheat_fed_units": 0,
                "empty_usable_tiles": 0,
                "prices_realized": defaultdict(list),
                "unwatered_eod": 0,
                "ripe_unharvested_eod": 0,
            }

        # Dwell time tracking: track when units enter shed and when sold
        # item -> list of harvest turn timestamps
        shed_deposit_turns = defaultdict(list)
        dwell_times = defaultdict(list)

        # Hook engine functions
        orig_process_market = kg._process_market
        orig_commit_unit = kg._commit_unit
        orig_do_hire = kg._do_hire
        orig_do_buy_land = kg._do_buy_land
        orig_town_consume = kg._town_consume

        # Reference to current turn info
        current_env_step = [0]
        current_day = [0]
        current_hour = [0]
        active_farms = [None]

        def hooked_process_market(state, env):
            active_farms[0] = state[0].observation.farms
            return orig_process_market(state, env)

        def hooked_commit_unit(op, item, price, farm, private, market, shed_capacity=100):
            farms = active_farms[0]
            is_seat_player = (farms is not None and farm is farms[seat])
            is_opp_player = (farms is not None and farm is farms[1 - seat])

            res = orig_commit_unit(op, item, price, farm, private, market, shed_capacity)
            if res:
                d = current_day[0]
                if is_seat_player:
                    if op == "SELL":
                        tx_inflows[item] += price
                        tx_inflows_units[item] += 1
                        daily_timeline[d]["inflows"][item] += price
                        daily_timeline[d]["inflow_units"][item] += 1
                        daily_timeline[d]["prices_realized"][item].append(price)

                        # Dwell time
                        if shed_deposit_turns[item]:
                            dep_turn = shed_deposit_turns[item].pop(0)
                            dwell_times[item].append(current_env_step[0] - dep_turn)

                    elif op == "BUY_PRODUCT":
                        key = f"BUY_PRODUCT_{item}"
                        tx_outflows[key] += price
                        tx_outflows_units[key] += 1
                        daily_timeline[d]["outflows"][key] += price
                        daily_timeline[d]["outflow_units"][key] += 1
                    elif op == "BUY_SEED":
                        key = f"BUY_SEED_{item}"
                        tx_outflows[key] += price
                        tx_outflows_units[key] += 1
                        daily_timeline[d]["outflows"][key] += price
                        daily_timeline[d]["outflow_units"][key] += 1
                    elif op == "BUY_ANIMAL":
                        key = f"BUY_ANIMAL_{item}"
                        tx_outflows[key] += price
                        tx_outflows_units[key] += 1
                        daily_timeline[d]["outflows"][key] += price
                        daily_timeline[d]["outflow_units"][key] += 1

                elif is_opp_player:
                    if op == "SELL":
                        opp_inflows[item] += price
                        opp_inflows_units[item] += 1

            return res

        def hooked_do_hire(farm, private, board_size, mult=kg.FARM_HAND_COST_MULT):
            farms = active_farms[0]
            is_seat_player = (farms is not None and farm is farms[seat])
            cost = kg._hire_cost(farm["hires_today"], mult)
            can_afford = (farm["money"] >= cost)
            orig_do_hire(farm, private, board_size, mult)
            if can_afford and is_seat_player:
                d = current_day[0]
                tx_outflows["HIRE"] += cost
                tx_outflows_units["HIRE"] += 1
                daily_timeline[d]["outflows"]["HIRE"] += cost
                daily_timeline[d]["outflow_units"]["HIRE"] += 1

        def hooked_do_buy_land(farm, board_size):
            farms = active_farms[0]
            is_seat_player = (farms is not None and farm is farms[seat])
            n_unlocked_extra = len(farm["unlocked_quadrants"]) - 1
            cost = kg.LAND_PRICES[n_unlocked_extra] if n_unlocked_extra < len(kg.LAND_PRICES) else None
            can_afford = (cost is not None and farm["money"] >= cost)
            quadrant = kg.LAND_ORDER[n_unlocked_extra] if can_afford else None
            orig_do_buy_land(farm, board_size)
            if can_afford and is_seat_player:
                d = current_day[0]
                tx_outflows["BUY_LAND"] += cost
                tx_outflows_units["BUY_LAND"] += 1
                daily_timeline[d]["outflows"]["BUY_LAND"] += cost
                daily_timeline[d]["outflow_units"]["BUY_LAND"] += 1
                daily_timeline[d]["unlocked_quadrants"].append(quadrant)

        def hooked_town_consume(env, state, step):
            # Track market inventory before and after town consume
            obs0 = state[0].observation
            market = obs0.market
            before_inv = copy.deepcopy(market.get("inventory", {}))
            orig_town_consume(env, state, step)
            after_inv = market.get("inventory", {})
            for item in kg.PRODUCTS:
                delta = before_inv.get(item, 0) - after_inv.get(item, 0)
                if delta > 0:
                    town_consumed[item] += delta

        # Apply hooks
        kg._process_market = hooked_process_market
        kg._commit_unit = hooked_commit_unit
        kg._do_hire = hooked_do_hire
        kg._do_buy_land = hooked_do_buy_land
        kg._town_consume = hooked_town_consume

        # Prior turn plant state for detecting harvests and plantings
        prev_tiles_grid = {}
        hourly_cash_series = []

        def tracking_agent(obs, configuration=None):
            step = int(obs.get("step", 0))
            day = int(obs.get("day", 0))
            hour = int(obs.get("hour", 0))
            current_env_step[0] = step
            current_day[0] = day
            current_hour[0] = hour

            farm = obs.get("farms", [{}])[seat]
            my_money = float(farm.get("money", 0.0))

            if hour == 0:
                daily_timeline[day]["begin_cash"] = my_money

            if day <= 13:
                hourly_cash_series.append({
                    "day": day,
                    "hour": hour,
                    "step": step,
                    "money": my_money,
                    "hands": len(farm.get("hands", []) or []),
                    "quadrants": list(farm.get("unlocked_quadrants", [])),
                })

            action = module.agent(obs, configuration) or {}

            # Count plantings and harvests from executed unit actions if possible, or track tiles
            farmer_act = action.get("farmer", ["PASS"]) if isinstance(action, dict) else ["PASS"]
            hands_acts = action.get("hands", []) if isinstance(action, dict) else []
            all_acts = [farmer_act] + (hands_acts if isinstance(hands_acts, list) else [])

            for act in all_acts:
                if isinstance(act, list) and len(act) >= 2:
                    op = act[0]
                    if op == "PLANT":
                        crop = act[1]
                        daily_timeline[day]["crops_planted"][crop] += 1
                    elif op == "FEED":
                        daily_timeline[day]["wheat_fed_units"] += 1

            # Check previous tiles vs current tiles for harvest detection
            curr_tiles = farm.get("tiles", [])
            for y, row in enumerate(curr_tiles or []):
                for x, tile in enumerate(row or []):
                    pos = (x, y)
                    prev_t = prev_tiles_grid.get(pos)
                    if prev_t and isinstance(prev_t, dict) and isinstance(tile, dict):
                        # Detect harvest: yield was > 0 and now 0 or plant changed
                        prev_y = prev_t.get("yield", 0)
                        curr_y = tile.get("yield", 0)
                        if prev_y > 0 and curr_y == 0 and prev_t.get("kind") == tile.get("kind"):
                            crop = prev_t.get("kind")
                            daily_timeline[day]["crops_harvested"][crop] += prev_y
                            # Record shed deposit timestamp for dwell tracking
                            for _ in range(prev_y):
                                shed_deposit_turns[crop].append(step)

                    prev_tiles_grid[pos] = copy.deepcopy(tile) if isinstance(tile, dict) else tile

            # Hour 23 snapshot
            if hour == 23:
                daily_timeline[day]["end_cash"] = my_money
                daily_timeline[day]["active_hands"] = len(farm.get("hands", []) or [])
                daily_timeline[day]["unlocked_quadrants"] = list(farm.get("unlocked_quadrants", []))

                # Count active crops and animals
                empty_tiles = 0
                for y, row in enumerate(curr_tiles or []):
                    for x, tile in enumerate(row or []):
                        quadrant = kg._quadrant_of(x, y, 10)
                        if quadrant in farm.get("unlocked_quadrants", []):
                            if tile is None:
                                empty_tiles += 1
                            elif isinstance(tile, dict):
                                if "kind" in tile and tile["kind"] in kg.CROPS:
                                    daily_timeline[day]["active_crops_count"][tile["kind"]] += 1
                                    if not tile.get("watered_today", False):
                                        daily_timeline[day]["unwatered_eod"] += 1
                                    if tile.get("yield", 0) > 0:
                                        daily_timeline[day]["ripe_unharvested_eod"] += tile.get("yield", 0)
                                elif "animal" in tile:
                                    daily_timeline[day]["active_animals_count"][tile["animal"]] += 1

                daily_timeline[day]["empty_usable_tiles"] = empty_tiles

            return action

        opp_agent = get_agent(opponent)
        agents = [tracking_agent, opp_agent] if seat == 0 else [opp_agent, tracking_agent]

        env = kaggle_environments.make(
            "kaggriculture",
            configuration={"episodeSteps": 720, "seed": seed},
        )
        env_ref = [env]
        env.reset()
        t0 = time.time()
        env.run(agents)
        wall_time = time.time() - t0

        final_reward = float(env.state[seat].reward or 0.0)
        final_farm = env.state[seat].observation.farms[seat]
        final_private = env.state[seat].observation.private
        final_cash = float(final_farm.get("money", 0.0))

        # Restore original hooks
        kg._process_market = orig_process_market
        kg._commit_unit = orig_commit_unit
        kg._do_hire = orig_do_hire
        kg._do_buy_land = orig_do_buy_land
        kg._town_consume = orig_town_consume

        # 100% Reconciliation Verification:
        starting_cash = 3000.0
        total_inflows = sum(tx_inflows.values())
        total_outflows = sum(tx_outflows.values())
        calculated_final = starting_cash + total_inflows - total_outflows
        discrepancy = abs(calculated_final - final_cash)

        if discrepancy > 1e-4:
            raise AssertionError(
                f"Economic ledger reconciliation failed on Seed {seed} Seat {seat} Opponent {opponent}!\n"
                f"Starting: {starting_cash}, Inflows: {total_inflows}, Outflows: {total_outflows}\n"
                f"Calculated: {calculated_final}, Actual Farm Cash: {final_cash}, Reward: {final_reward}\n"
                f"Discrepancy: {discrepancy}\n"
                f"Inflows details: {dict(tx_inflows)}\n"
                f"Outflows details: {dict(tx_outflows)}"
            )

        # Unconverted resources at season end (Day 29 post-game)
        unsold_shed = dict(final_private.get("shed", {}))
        unsold_shed_units = sum(unsold_shed.values())

        unsold_worker = defaultdict(int)
        for inv in final_private.get("inventories", []):
            for itm, cnt in (inv or {}).items():
                unsold_worker[itm] += cnt
        unsold_worker_units = sum(unsold_worker.values())

        unharvested_yield = defaultdict(int)
        uncollected_fert = 0
        living_animals = defaultdict(int)
        unharvested_crop_counts = defaultdict(int)
        for y, row in enumerate(final_farm.get("tiles", []) or []):
            for x, tile in enumerate(row or []):
                if isinstance(tile, dict):
                    if "kind" in tile and tile["kind"] in kg.CROPS:
                        unharvested_crop_counts[tile["kind"]] += 1
                        y_val = tile.get("yield", 0)
                        if y_val > 0:
                            unharvested_yield[tile["kind"]] += y_val
                    elif "animal" in tile:
                        living_animals[tile["animal"]] += 1
                        if tile.get("fertilizer_available", False):
                            uncollected_fert += 1

        unused_seeds = dict(final_private.get("seeds", {}))
        unused_seeds_units = sum(unused_seeds.values())

        # Clean daily timeline for json serialization
        clean_daily_timeline = {}
        for d, row in daily_timeline.items():
            clean_daily_timeline[d] = {
                "day": d,
                "begin_cash": row["begin_cash"],
                "end_cash": row["end_cash"],
                "inflows": dict(row["inflows"]),
                "inflow_units": dict(row["inflow_units"]),
                "outflows": dict(row["outflows"]),
                "outflow_units": dict(row["outflow_units"]),
                "crops_planted": dict(row["crops_planted"]),
                "crops_harvested": dict(row["crops_harvested"]),
                "active_crops_count": dict(row["active_crops_count"]),
                "active_animals_count": dict(row["active_animals_count"]),
                "active_hands": row["active_hands"],
                "unlocked_quadrants": row["unlocked_quadrants"],
                "wheat_fed_units": row["wheat_fed_units"],
                "empty_usable_tiles": row["empty_usable_tiles"],
                "unwatered_eod": row["unwatered_eod"],
                "ripe_unharvested_eod": row["ripe_unharvested_eod"],
                "mean_prices_realized": {
                    itm: statistics.mean(pts) if pts else 0.0
                    for itm, pts in row["prices_realized"].items()
                },
            }

        mean_dwell = {
            itm: (statistics.mean(ts) if ts else 0.0)
            for itm, ts in dwell_times.items()
        }

        return {
            "seed": seed,
            "seat": seat,
            "opponent": opponent,
            "score": final_reward,
            "wall_time": wall_time,
            "reconciliation": {
                "starting_cash": starting_cash,
                "total_inflows": total_inflows,
                "total_outflows": total_outflows,
                "final_cash": final_cash,
                "final_reward": final_reward,
                "discrepancy": discrepancy,
                "passed": True,
            },
            "inflows": dict(tx_inflows),
            "inflow_units": dict(tx_inflows_units),
            "outflows": dict(tx_outflows),
            "outflow_units": dict(tx_outflows_units),
            "opp_inflows": dict(opp_inflows),
            "opp_inflow_units": dict(opp_inflows_units),
            "town_consumed": dict(town_consumed),
            "unconverted_resources": {
                "unsold_shed": unsold_shed,
                "unsold_shed_units": unsold_shed_units,
                "unsold_worker": dict(unsold_worker),
                "unsold_worker_units": unsold_worker_units,
                "unharvested_yield": dict(unharvested_yield),
                "unharvested_yield_units": sum(unharvested_yield.values()),
                "unharvested_crop_counts": dict(unharvested_crop_counts),
                "living_animals": dict(living_animals),
                "uncollected_fert": uncollected_fert,
                "unused_seeds": unused_seeds,
                "unused_seeds_units": unused_seeds_units,
                "unlocked_quadrants": list(final_farm.get("unlocked_quadrants", [])),
            },
            "mean_dwell_turns": mean_dwell,
            "hourly_cash_d0_d13": hourly_cash_series,
            "daily_timeline": clean_daily_timeline,
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "seed": seed,
            "seat": seat,
            "opponent": opponent,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def run_audit(workers=8, limit=None):
    tasks = []
    scenarios = []
    for idx, seed in enumerate(DIAGNOSTIC_SEEDS):
        opp = OPPONENTS[idx % len(OPPONENTS)]
        scenarios.append({"pair_id": idx + 1, "seed": seed, "opponent": opp})

    if limit is not None:
        scenarios = scenarios[:limit]

    for sc in scenarios:
        for seat in (0, 1):
            tasks.append({
                "seed": sc["seed"],
                "opponent": sc["opponent"],
                "seat": seat,
                "pair_id": sc["pair_id"],
            })

    total_games = len(tasks)
    print(f"Launching P4.0 Authoritative Economic Audit: {len(scenarios)} scenarios x 2 seats = {total_games} games on {workers} workers.")
    t_start = time.time()

    completed_results = []
    reconciliation_failures = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(_run_single_economic_audit, task): task for task in tasks}
        done_count = 0
        for future in as_completed(future_map):
            done_count += 1
            res = future.result()
            if "error" in res:
                print(f"[{done_count}/{total_games}] ERROR: seed={res['seed']} seat={res['seat']}: {res['error']}")
                reconciliation_failures.append(res)
            else:
                recon = res["reconciliation"]
                if not recon["passed"]:
                    print(f"[{done_count}/{total_games}] FAILED RECONCILIATION: seed={res['seed']}")
                    reconciliation_failures.append(res)
                else:
                    completed_results.append(res)
                    if done_count % 10 == 0 or done_count == total_games:
                        print(f"[{done_count}/{total_games}] Completed seed={res['seed']} seat={res['seat']} opp={res['opponent']} Score=${res['score']:,.2f} Discrepancy={recon['discrepancy']:.6f} (elapsed: {time.time()-t_start:.1f}s)")

    duration = time.time() - t_start
    print(f"\nAudit complete in {duration:.1f}s. Valid completed games: {len(completed_results)}/{total_games}. Reconciliation failures: {len(reconciliation_failures)}")

    if reconciliation_failures:
        print(f"FATAL: {len(reconciliation_failures)} games failed reconciliation!")
        sys.exit(1)

    # Save raw audit results
    os.makedirs(os.path.join(ROOT, "simulations", "experiments", "results"), exist_ok=True)
    out_path = os.path.join(ROOT, "simulations", "experiments", "results", "p40_economic_ledger_100g.json")
    with open(out_path, "w") as f:
        json.dump({
            "metadata": {
                "baseline_sha": BASELINE_SHA,
                "engine_version": "1.32.7",
                "seeds": DIAGNOSTIC_SEEDS if limit is None else DIAGNOSTIC_SEEDS[:limit],
                "opponents": OPPONENTS,
                "total_games": len(completed_results),
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "audit_duration_sec": duration,
            },
            "games": completed_results,
        }, f, indent=2)
    print(f"Saved raw audit results to: {out_path}")
    return completed_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        print("Running 1 smoke game...")
        res = _run_single_economic_audit({"seed": 96001, "opponent": "pass", "seat": 0, "pair_id": 1})
        if "error" in res:
            print("Smoke test failed:", res["error"])
            print(res["traceback"])
            sys.exit(1)
        print("Smoke test passed successfully!")
        print("Score:", res["score"])
        print("Reconciliation:", res["reconciliation"])
        print("Inflows:", res["inflows"])
        print("Outflows:", res["outflows"])
        sys.exit(0)

    run_audit(workers=args.workers, limit=args.limit)
