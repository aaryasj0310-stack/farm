#!/usr/bin/env python3
"""P4.2 Market Revenue Realization & Sell-Timing Ground-Truth Audit Harness.

Design:
- 10 fresh seeds: 96,101–96,110
- 5 standard opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- 2 balanced seats: Seat 0 and Seat 1
- Total: 10 seeds x 5 opponents x 2 seats = 100 baseline live games.
- Lineage: 536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e (Authoritative Control Baseline)
- Engine: kaggle_environments v1.32.7 with per-unit lockstep transaction interception.
"""
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
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
SEEDS = list(range(96101, 96111))  # 10 fresh seeds: 96,101–96,110
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
DRIP_PRODUCTS = ["MELON", "STRAWBERRY", "MILK", "WOOL"]

SCENARIOS = []
pair_id = 0
for seed in SEEDS:
    for opp in OPPONENTS:
        pair_id += 1
        for seat in (0, 1):
            SCENARIOS.append({
                "game_id": len(SCENARIOS) + 1,
                "pair_id": pair_id,
                "seed": seed,
                "opponent": opp,
                "seat": seat,
            })


def _configure_baseline(cfg):
    """Ensure exact authoritative baseline configuration equivalent to 536f1e7."""
    cfg.set_opponent_intelligence_mode("O0_SHADOW")
    for attr, val in (
        ("SW_OWNERSHIP_MODE", "production"),
        ("SW_TIMING_PRIOR_ENABLED", False),
        ("SW_ACTIVATION_MODE", "production"),
        ("SW_SAFETY_RESERVE", 300.0),
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
        ("P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", True),
        ("P31_STATE_DEPENDENT_HARVEST_PRIORITY_ENABLED", False),
        ("P32_STATE_DEPENDENT_CARE_PRIORITY_ENABLED", False),
        ("P33_PHYSICAL_LOCALITY_ENABLED", False),
        ("P41_SW_ZONAL_EXPANSION_ENABLED", False),
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    if hasattr(cfg, "set_p23_marginal_wheat_allocation_enabled"):
        cfg.set_p23_marginal_wheat_allocation_enabled(True)
    if hasattr(cfg, "set_p41_sw_zonal_expansion_enabled"):
        cfg.set_p41_sw_zonal_expansion_enabled(False)


def _run_single_game(scenario):
    agent_dir = os.path.join(ROOT, "agent")
    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
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
        import kaggle_environments.envs.kaggriculture.kaggriculture as kagg
        import main as module
        import config as cfg
        import execution.task_scheduler as ts
        from simulations.experiments.agent_zoo import get_agent

        _configure_baseline(cfg)
        module.reset_agent_state()
        ts.reset_daily_log()

        seed = scenario["seed"]
        seat = scenario["seat"]
        opp_name = scenario["opponent"]

        # Transaction and environmental audit loggers
        game_transactions = []
        town_drain_events = []
        turn_decisions = []
        product_harvest_events = defaultdict(int)
        product_shed_deposits = defaultdict(int)

        current_step_info = {"step": 0, "day": 0, "hour": 0}
        current_committed_units_this_step = []

        # Intercept _process_market to capture exact step and player_id per unit
        orig_process_market = kagg._process_market
        def tracked_process_market(state, env):
            step = int(state[0].observation.get("step", 0))
            p0_priv = state[0].observation.private
            p1_priv = state[1].observation.private

            orig_commit_unit = kagg._commit_unit
            def tracked_commit_unit(op, item, price, farm, private, market, shed_capacity=100):
                ok = orig_commit_unit(op, item, price, farm, private, market, shed_capacity)
                if ok:
                    pid = 0 if (private is p0_priv) else 1
                    is_us = (pid == seat)
                    current_committed_units_this_step.append({
                        "step": step,
                        "op": op,
                        "item": item,
                        "price": int(price),
                        "pid": pid,
                        "is_us": is_us,
                        "market_inv_after": int(market["inventory"].get(item, 10000)),
                    })
                return ok
            kagg._commit_unit = tracked_commit_unit
            try:
                orig_process_market(state, env)
            finally:
                kagg._commit_unit = orig_commit_unit
        kagg._process_market = tracked_process_market

        # Intercept _town_consume
        orig_town_consume = kagg._town_consume
        def tracked_town_consume(env, state, step):
            obs0 = state[0].observation
            inv_before = dict(obs0.market["inventory"])
            orig_town_consume(env, state, step)
            inv_after = dict(obs0.market["inventory"])
            drain_amounts = {p: inv_before.get(p, 0) - inv_after.get(p, 0) for p in PRODUCTS}
            town_drain_events.append({
                "step": step,
                "day": step // 24,
                "hour": step % 24,
                "drain_amounts": drain_amounts,
                "inventory_before": inv_before,
                "inventory_after": inv_after,
            })
        kagg._town_consume = tracked_town_consume

        our_private_ref = None
        last_observed_shed = {}
        last_observed_market_inv = {}

        # Tracking agent wrapper
        def tracking_agent(obs, configuration=None):
            nonlocal our_private_ref, last_observed_shed, last_observed_market_inv
            player = int(obs.get("player", seat))
            step = int(obs.get("step", 0))
            day = int(obs.get("day", 0))
            hour = int(obs.get("hour", 0))
            current_step_info["step"] = step
            current_step_info["day"] = day
            current_step_info["hour"] = hour

            market_obs = obs.get("market", {})
            m_inv = market_obs.get("inventory", {})
            m_prices = market_obs.get("prices", {})

            # Private reference
            priv = obs.get("private", {})
            our_private_ref = priv
            shed = priv.get("shed", {}) if isinstance(priv, dict) else getattr(priv, "shed", {})
            shed_dict = {p: int(shed.get(p, 0)) for p in PRODUCTS}
            worker_invs = priv.get("inventories", []) if isinstance(priv, dict) else getattr(priv, "inventories", [])
            carried_qty = sum(
                int(c) for w in worker_invs for item, c in (w.items() if isinstance(w, dict) else [])
            )
            shed_occupancy = sum(shed_dict.values())
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}
            money = float(farm.get("money", 0.0))

            # Run agent to get action and inspect internal state
            action = module.agent(obs)

            # Extract CentralPlanner and MarketBrain telemetry from module
            cp_diag = getattr(module, "_LAST_CENTRAL_PLANNER_DIAGNOSTIC", None) or {}
            accepted_orders = cp_diag.get("accepted_orders", [])
            rejected_details = cp_diag.get("rejected_details", [])

            # Record turn market intent state
            turn_decisions.append({
                "step": step,
                "day": day,
                "hour": hour,
                "money": money,
                "shed": dict(shed_dict),
                "carried_qty": carried_qty,
                "shed_occupancy": shed_occupancy,
                "market_inv": dict(m_inv),
                "market_prices": dict(m_prices),
                "market_orders_emitted": action.get("market", []),
                "accepted_orders": accepted_orders,
                "rejected_details": rejected_details,
            })

            last_observed_shed = dict(shed_dict)
            last_observed_market_inv = dict(m_inv)
            return action

        opp_agent_fn = get_agent(opp_name)
        players = [tracking_agent, opp_agent_fn] if seat == 0 else [opp_agent_fn, tracking_agent]

        t0 = time.time()
        env = kaggle_environments.make("kaggriculture", configuration={"seed": seed, "episodeSteps": 722}, info={"seed": seed})
        env.reset()

        # Run step by step to associate committed units with turn decisions
        # Note: env.run() executes the full episode
        # After run completes, we match committed units from current_committed_units_this_step with the orders
        env.run(players)
        wall_time = time.time() - t0

        # Post-game telemetry extraction
        final_state = env.state
        our_final_farm = final_state[seat].observation.farms[seat]
        opp_final_farm = final_state[1 - seat].observation.farms[1 - seat]
        our_final_cash = float(our_final_farm.get("money", 0.0))
        opp_final_cash = float(opp_final_farm.get("money", 0.0))
        our_final_shed = dict(final_state[seat].observation.private.get("shed", {}))

        # Reconstruct per-turn transactions:
        # Match each turn decision's market orders with committed units
        # All committed units have `is_us`: True/False
        our_committed_sales = [u for u in current_committed_units_this_step if u["is_us"] and u["op"] == "SELL"]
        opp_committed_sales = [u for u in current_committed_units_this_step if not u["is_us"] and u["op"] == "SELL"]

        # Parse detailed transactions from turn_decisions
        sales_by_product = defaultdict(list)
        total_revenue_by_product = defaultdict(float)
        units_sold_by_product = defaultdict(int)

        # Build clean transaction ledger
        # We step through turn_decisions that had emitted market SELL orders
        unit_cursor = 0
        for td in turn_decisions:
            step = td["step"]
            day = td["day"]
            hour = td["hour"]
            m_orders = td["market_orders_emitted"]
            m_inv_before = td["market_inv"]
            shed_before = td["shed"]

            for slot_idx, order in enumerate(m_orders):
                if not isinstance(order, list) or len(order) < 3 or order[0] != "SELL":
                    continue
                prod = order[1]
                qty_req = int(order[2])
                spot_before = td["market_prices"].get(prod, 0.0)

                # Collect units committed for this order
                order_units_committed = []
                while unit_cursor < len(our_committed_sales):
                    u = our_committed_sales[unit_cursor]
                    if u["step"] == step and u["item"] == prod and len(order_units_committed) < qty_req:
                        order_units_committed.append(u)
                        unit_cursor += 1
                    elif u["step"] < step:
                        unit_cursor += 1
                    else:
                        break

                qty_actually_sold = len(order_units_committed)
                realized_prices = [u["price"] for u in order_units_committed]
                realized_revenue = sum(realized_prices)
                avg_price = (realized_revenue / qty_actually_sold) if qty_actually_sold > 0 else 0.0
                last_unit_price = realized_prices[-1] if realized_prices else spot_before

                # CentralPlanner proposal tracing
                rejection_entry = next((r for r in td["rejected_details"] if r.get("order") == order), None)
                rejection_reason = rejection_entry.get("rejection_reason") if rejection_entry else None

                # Record transaction
                tx = {
                    "seed": seed,
                    "opponent": opp_name,
                    "seat": seat,
                    "step": step,
                    "day": day,
                    "hour": hour,
                    "product": prod,
                    "slot_idx": slot_idx,
                    "qty_requested": qty_req,
                    "qty_actually_sold": qty_actually_sold,
                    "spot_price_before": spot_before,
                    "realized_prices": realized_prices,
                    "realized_revenue": realized_revenue,
                    "avg_realized_price": avg_price,
                    "last_unit_realized_price": last_unit_price,
                    "shed_qty_before": shed_before.get(prod, 0),
                    "market_inv_before": m_inv_before.get(prod, 10000),
                    "market_inv_after": order_units_committed[-1]["market_inv_after"] if order_units_committed else m_inv_before.get(prod, 10000),
                    "rejection_reason": rejection_reason,
                }
                game_transactions.append(tx)
                sales_by_product[prod].append(tx)
                total_revenue_by_product[prod] += realized_revenue
                units_sold_by_product[prod] += qty_actually_sold

        return {
            "game_id": scenario["game_id"],
            "pair_id": scenario["pair_id"],
            "seed": seed,
            "opponent": opp_name,
            "seat": seat,
            "final_cash": our_final_cash,
            "opp_final_cash": opp_final_cash,
            "final_shed": our_final_shed,
            "total_transactions": len(game_transactions),
            "transactions": game_transactions,
            "town_drains": town_drain_events,
            "turn_decisions_count": len(turn_decisions),
            "total_revenue_by_product": dict(total_revenue_by_product),
            "units_sold_by_product": dict(units_sold_by_product),
            "wall_time": wall_time,
            "success": True,
        }
    except Exception as exc:
        tb = traceback.format_exc()
        return {
            "game_id": scenario["game_id"],
            "pair_id": scenario["pair_id"],
            "seed": scenario["seed"],
            "opponent": scenario["opponent"],
            "seat": scenario["seat"],
            "error": str(exc),
            "traceback": tb,
            "success": False,
        }


def main():
    print(f"==================================================================")
    print(f"Starting Kaggriculture P4.2 Market Transaction Telemetry Audit")
    print(f"Sample: 10 seeds x 5 opponents x 2 seats = {len(SCENARIOS)} live baseline games")
    print(f"Seeds: {SEEDS[0]}–{SEEDS[-1]}")
    print(f"Opponents: {OPPONENTS}")
    print(f"Lineage: {BASELINE_SHA}")
    print(f"==================================================================")

    out_file = os.path.join(ROOT, "simulations", "experiments", "results", "p42_transaction_telemetry_100g.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    max_workers = min(10, os.cpu_count() or 4)
    results = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_game, s): s for s in SCENARIOS}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            completed += 1
            results.append(res)
            s = futures[fut]
            if res["success"]:
                print(f"[{completed:3d}/100] Game {res['game_id']:3d} (Seed {res['seed']}, {res['opponent']:18s}, Seat {res['seat']}): "
                      f"Cash=${res['final_cash']:8.1f}, Sales={res['total_transactions']:3d}, Time={res['wall_time']:4.1f}s")
            else:
                print(f"[{completed:3d}/100] Game {s['game_id']:3d} FAILED: {res.get('error')}")

    total_time = time.time() - t_start
    print(f"\nCompleted 100 games in {total_time:.1f}s")

    # Aggregate summaries
    successful = [r for r in results if r.get("success")]
    print(f"Successful runs: {len(successful)} / {len(SCENARIOS)}")
    if not successful:
        print("All games failed! Exiting.")
        return

    mean_cash = statistics.mean(r["final_cash"] for r in successful)
    median_cash = statistics.median(r["final_cash"] for r in successful)
    stdev_cash = statistics.stdev(r["final_cash"] for r in successful) if len(successful) > 1 else 0.0

    print(f"\n--- Baseline Production Performance ---")
    print(f"Mean Final Cash:   ${mean_cash:,.2f}")
    print(f"Median Final Cash: ${median_cash:,.2f}")
    print(f"Standard Dev:      ${stdev_cash:,.2f}")

    # Summary by opponent
    by_opp = defaultdict(list)
    for r in successful:
        by_opp[r["opponent"]].append(r["final_cash"])
    print(f"\n--- Opponent Breakdown ---")
    for opp, vals in by_opp.items():
        print(f"  {opp:22s}: Mean=${statistics.mean(vals):9.2f} (n={len(vals)})")

    # Save to JSON
    summary_data = {
        "experiment": "P4.2 Market Revenue Realization & Sell-Timing Ground-Truth Audit",
        "baseline_sha": BASELINE_SHA,
        "seed_block": f"{SEEDS[0]}–{SEEDS[-1]}",
        "total_games": len(SCENARIOS),
        "successful_games": len(successful),
        "mean_final_cash": mean_cash,
        "median_final_cash": median_cash,
        "stdev_final_cash": stdev_cash,
        "raw_results": results,
    }

    with open(out_file, "w") as f:
        json.dump(summary_data, f, indent=2)
    print(f"\nDetailed telemetry dataset saved to: {out_file}")


if __name__ == "__main__":
    main()
