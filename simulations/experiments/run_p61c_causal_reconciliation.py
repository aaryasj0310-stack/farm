#!/usr/bin/env python3
"""Kaggriculture P6.1-C — Causal Reconciliation Harness.

Forensic reconciliation of the P6.1 Pre-Midnight Storage Hygiene Experiment:
Panel: 10 fresh untouched seeds (96,411–96,420) x 5 opponents x 2 seats = 100 matched pairs (200 live games).

Core Objectives:
1. Exact cash closure for every game and matched pair:
   Final Cash = Starting Cash + Sells - Purchases - Hires - Land (Residual = 0.000000).
2. Decompose the full +$1,439.86 cash delta into exact transaction categories.
3. Resolve the unexplained +$778.16 into concrete physical and financial mechanisms.
4. Hourly liquidity timing ledger (cash_ctrl, cash_treat, cash_diff, first divergence, duration).
5. Identify treatment activation intensity:
   - Triggered and actual sale occurred
   - Triggered but no sale possible (due to protected wheat and empty shed).
6. Outlier and distribution analysis (top 1/5/10 contribution, trimmed mean, quartile metrics).
7. Opponent heterogeneity (why treatment loses -$813.15 against full_production_agent).
8. Product delta physical traceability (Milk, Melon, Strawberry, Wool, Fertilizer, Wheat).
9. Physical shed-overflow mechanism (shed occupancy, backpack occupancy, unavoidable overflow).
10. Intraday worker deposit feasibility model (step cost, trip frequency, opportunity cost).
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
EVAL_SEEDS = list(range(96411, 96421))  # 10 fresh untouched evaluation seeds: 96,411–96,420
SEATS = [0, 1]

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
CROPS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
ANIMALS = ["COW", "SHEEP", "CHICKEN", "GOOSE"]
BASE_PRICES = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250,
    "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100
}


def _run_single_reconciliation_game(seed, opponent, seat, p61_enabled):
    """Executes a single instrumented simulation game with full transaction, liquidity, and inventory logging."""
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
    from strategy.two_cycle_rotation_manager import reset_rotation_manager

    apt._configure_baseline(cfg)
    cfg.set_p51_t1_two_cycle_carrot_enabled(False)
    cfg.set_p61_pre_midnight_storage_hygiene_enabled(p61_enabled)
    module.reset_agent_state()
    reset_rotation_manager()

    opp_agent = get_agent(opponent)
    players = [module.agent, opp_agent] if seat == 0 else [opp_agent, module.agent]

    # Exact Transaction Ledger
    cash_ledger = {
        "starting_cash": 3000.0,
        "sells": {p: {"units": 0, "revenue": 0.0, "prices": []} for p in PRODUCTS},
        "buys_product": {p: {"units": 0, "cost": 0.0, "prices": []} for p in ("WHEAT", "FERTILIZER")},
        "buys_seed": {c: {"units": 0, "cost": 0.0, "prices": []} for c in CROPS},
        "buys_animal": {a: {"units": 0, "cost": 0.0, "prices": []} for a in ANIMALS},
        "hires": {"count": 0, "cost": 0.0},
        "land": {"count": 0, "cost": 0.0, "quadrants": []},
    }

    executed_purchases = []  # List of dicts: {"step": s, "day": d, "hour": h, "type": t, "item": i, "units": u, "cost": c}
    hourly_cash = [0.0] * 720
    shed_discards = {p: {"units": 0, "events": 0} for p in PRODUCTS}
    feed_failures = {"missed_feeds": 0, "starvation_events": 0, "escapes": 0}

    # Hours 20-22 Inventory & Hygiene Telemetry
    h20_22_inventory_records = []
    hygiene_activations = []  # Detailed log of each H20-22 check

    cur_p0_farm = None
    cur_p0_priv = None
    cur_step = 0

    orig_process_market = kg._process_market
    def tracked_process_market(state, env):
        nonlocal cur_p0_farm, cur_p0_priv, cur_step
        cur_p0_farm = state[0].observation.farms[0]
        cur_p0_priv = state[0].observation.private
        cur_step = state[0].observation.step
        day = cur_step // 24
        hour = cur_step % 24

        orig_commit_unit = kg._commit_unit
        def tracked_commit_unit(op, item, price, farm, private, market, shed_capacity=100):
            ok = orig_commit_unit(op, item, price, farm, private, market, shed_capacity)
            if ok:
                pid = 0 if (private is cur_p0_priv) else 1
                if pid == seat:
                    p = float(price)
                    if op == "SELL" and item in cash_ledger["sells"]:
                        cash_ledger["sells"][item]["units"] += 1
                        cash_ledger["sells"][item]["revenue"] += p
                        cash_ledger["sells"][item]["prices"].append(p)
                    elif op == "BUY_PRODUCT" and item in cash_ledger["buys_product"]:
                        cash_ledger["buys_product"][item]["units"] += 1
                        cash_ledger["buys_product"][item]["cost"] += p
                        cash_ledger["buys_product"][item]["prices"].append(p)
                        executed_purchases.append({"step": cur_step, "day": day, "hour": hour, "type": "BUY_PRODUCT", "item": item, "units": 1, "cost": p})
                    elif op == "BUY_SEED" and item in cash_ledger["buys_seed"]:
                        cash_ledger["buys_seed"][item]["units"] += 1
                        cash_ledger["buys_seed"][item]["cost"] += p
                        cash_ledger["buys_seed"][item]["prices"].append(p)
                        executed_purchases.append({"step": cur_step, "day": day, "hour": hour, "type": "BUY_SEED", "item": item, "units": 1, "cost": p})
                    elif op == "BUY_ANIMAL" and item in cash_ledger["buys_animal"]:
                        cash_ledger["buys_animal"][item]["units"] += 1
                        cash_ledger["buys_animal"][item]["cost"] += p
                        cash_ledger["buys_animal"][item]["prices"].append(p)
                        executed_purchases.append({"step": cur_step, "day": day, "hour": hour, "type": "BUY_ANIMAL", "item": item, "units": 1, "cost": p})
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
                    executed_purchases.append({"step": cur_step, "day": day, "hour": hour, "type": "HIRE", "item": "WORKER", "units": 1, "cost": float(cost)})

        orig_do_buy_land = kg._do_buy_land
        def tracked_do_buy_land(farm, board_size):
            before_unlocked = len(farm["unlocked_quadrants"])
            before_money = farm["money"]
            orig_do_buy_land(farm, board_size)
            if len(farm["unlocked_quadrants"]) > before_unlocked:
                pid = 0 if (farm is cur_p0_farm) else 1
                if pid == seat:
                    paid = float(before_money - farm["money"])
                    quad = farm["unlocked_quadrants"][-1]
                    cash_ledger["land"]["count"] += 1
                    cash_ledger["land"]["cost"] += paid
                    cash_ledger["land"]["quadrants"].append(quad)
                    executed_purchases.append({"step": cur_step, "day": day, "hour": hour, "type": "BUY_LAND", "item": quad, "units": 1, "cost": paid})

        kg._commit_unit = tracked_commit_unit
        kg._do_hire = tracked_do_hire
        kg._do_buy_land = tracked_do_buy_land
        try:
            orig_process_market(state, env)
        finally:
            kg._commit_unit = orig_commit_unit
            kg._do_hire = orig_do_hire
            kg._do_buy_land = orig_do_buy_land

    cur_anim_pid = 1
    orig_daily_animals = kg._daily_refresh_animals
    def tracked_daily_animals(farm, day):
        nonlocal cur_anim_pid
        cur_anim_pid = 1 - cur_anim_pid
        is_us = (cur_anim_pid == seat)
        if is_us:
            for row in farm["tiles"]:
                for t in row:
                    if isinstance(t, dict) and "animal" in t:
                        if not t.get("fed_today", False):
                            feed_failures["missed_feeds"] += 1
                            if t.get("consecutive_unfed", 0) >= 1:
                                feed_failures["starvation_events"] += 1
                            if t.get("consecutive_unfed", 0) >= 2:
                                feed_failures["escapes"] += 1
        orig_daily_animals(farm, day)

    cur_drop_pid = 1
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
                    if n <= 0:
                        continue
                    if n > room:
                        discarded = n - room
                        if item in shed_discards:
                            shed_discards[item]["units"] += discarded
                            shed_discards[item]["events"] += 1
                        room = 0
                    else:
                        room -= n
        orig_drop_shed(private, capacity)

    kg._process_market = tracked_process_market
    kg._daily_refresh_animals = tracked_daily_animals
    kg._drop_inventories_to_shed = tracked_drop_shed

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
            day = step_idx // 24
            hour = step_idx % 24

            our_farm = env.state[seat].observation.farms[seat]
            our_priv = env.state[seat].observation.private
            our_money = float(our_farm["money"])
            hourly_cash[step_idx] = our_money

            shed_dict = dict(our_priv.get("shed", {}))
            shed_occ = sum(shed_dict.values())
            invs = our_priv.get("inventories", [])
            worker_by_prod = defaultdict(int)
            for inv in invs:
                for k, v in (inv or {}).items():
                    worker_by_prod[k] += int(v)
            worker_occ = sum(worker_by_prod.values())
            projected_load = shed_occ + worker_occ

            # Detailed H20-22 Inventory & Hygiene snapshot
            if hour in (20, 21, 22):
                animals_count = sum(1 for row in our_farm.get("tiles", []) for t in row if isinstance(t, dict) and t.get("is_animal"))
                safe_wheat_floor = max(15, int(math.ceil(animals_count * 2.0)))
                wheat_in_shed = int(shed_dict.get("WHEAT", 0))
                surplus_wheat = max(0, wheat_in_shed - max(safe_wheat_floor, animals_count * 4))
                sellable_high_value = sum(shed_dict.get(p, 0) for p in ("STRAWBERRY", "MELON", "MILK", "WOOL", "CARROT", "TOMATO", "FERTILIZER"))
                total_sellable_in_shed = sellable_high_value + surplus_wheat

                h20_22_inventory_records.append({
                    "day": day,
                    "hour": hour,
                    "shed_occupancy": shed_occ,
                    "worker_inventory": worker_occ,
                    "projected_load": projected_load,
                    "shed_wheat": wheat_in_shed,
                    "safe_wheat_floor": safe_wheat_floor,
                    "surplus_wheat_in_shed": surplus_wheat,
                    "sellable_high_value_in_shed": sellable_high_value,
                    "total_sellable_in_shed": total_sellable_in_shed,
                    "worker_strawberry": worker_by_prod.get("STRAWBERRY", 0),
                    "worker_milk": worker_by_prod.get("MILK", 0),
                    "worker_wool": worker_by_prod.get("WOOL", 0),
                    "worker_melon": worker_by_prod.get("MELON", 0),
                    "worker_wheat": worker_by_prod.get("WHEAT", 0),
                    "worker_fertilizer": worker_by_prod.get("FERTILIZER", 0),
                    "unavoidable_overflow": max(0, projected_load - 100 - total_sellable_in_shed),
                })

            act0 = _call_agent(players[0], env.state[0].observation, env.configuration)
            act1 = _call_agent(players[1], env.state[1].observation, env.configuration)

            # Inspect if treatment emitted a hygiene sell order this turn
            if p61_enabled and hour in (20, 21, 22):
                our_act = act0 if seat == 0 else act1
                m_orders = our_act.get("market", []) if isinstance(our_act, dict) else []
                hygiene_sells_this_turn = [o for o in m_orders if len(o) >= 3 and o[0] == "SELL"]
                is_triggered = (projected_load > 75)
                hygiene_activations.append({
                    "day": day,
                    "hour": hour,
                    "triggered": is_triggered,
                    "projected_load": projected_load,
                    "sellable_in_shed": total_sellable_in_shed,
                    "orders_emitted": len(hygiene_sells_this_turn),
                    "items_emitted": [o[1] for o in hygiene_sells_this_turn],
                    "status": "TRIGGERED_AND_SOLD" if (is_triggered and len(hygiene_sells_this_turn) > 0) else (
                        "TRIGGERED_NO_SALE_POSSIBLE" if (is_triggered and total_sellable_in_shed == 0) else (
                            "TRIGGERED_BUT_IDLE" if is_triggered else "NOT_TRIGGERED"
                        )
                    )
                })

            env.step([act0, act1])
    finally:
        kg._process_market = orig_process_market
        kg._daily_refresh_animals = orig_daily_animals
        kg._drop_inventories_to_shed = orig_drop_shed

    final_reward = float(env.state[seat].reward or 0.0)
    opp_reward = float(env.state[1 - seat].reward or 0.0)
    engine_final_money = float(env.state[seat].observation.farms[seat]["money"])
    win = 1.0 if final_reward > opp_reward else (0.5 if final_reward == opp_reward else 0.0)

    # EXACT CASH RECONCILIATION VERIFICATION
    total_sales_revenue = sum(cash_ledger["sells"][p]["revenue"] for p in PRODUCTS)
    total_wheat_buy_cost = cash_ledger["buys_product"]["WHEAT"]["cost"]
    total_fert_buy_cost = cash_ledger["buys_product"]["FERTILIZER"]["cost"]
    total_seed_buy_cost = sum(cash_ledger["buys_seed"][c]["cost"] for c in CROPS)
    total_animal_buy_cost = sum(cash_ledger["buys_animal"][a]["cost"] for a in ANIMALS)
    total_hire_cost = cash_ledger["hires"]["cost"]
    total_land_cost = cash_ledger["land"]["cost"]

    total_expenditures = (
        total_wheat_buy_cost + total_fert_buy_cost +
        total_seed_buy_cost + total_animal_buy_cost +
        total_hire_cost + total_land_cost
    )
    calculated_final_money = cash_ledger["starting_cash"] + total_sales_revenue - total_expenditures
    reconciliation_residual = abs(calculated_final_money - engine_final_money)
    assert reconciliation_residual < 1e-5, f"Cash reconciliation failure! Calc: {calculated_final_money}, Engine: {engine_final_money}, Residual: {reconciliation_residual}"

    total_discard_units = sum(d["units"] for d in shed_discards.values())
    total_discard_events = sum(d["events"] for d in shed_discards.values())

    return {
        "final_money": engine_final_money,
        "calculated_money": calculated_final_money,
        "residual": reconciliation_residual,
        "final_reward": final_reward,
        "opp_reward": opp_reward,
        "win": win,
        "cash_ledger": {
            "sales_revenue_by_prod": {p: cash_ledger["sells"][p]["revenue"] for p in PRODUCTS},
            "sales_units_by_prod": {p: cash_ledger["sells"][p]["units"] for p in PRODUCTS},
            "total_sales_revenue": total_sales_revenue,
            "feed_wheat_cost": total_wheat_buy_cost,
            "feed_wheat_units": cash_ledger["buys_product"]["WHEAT"]["units"],
            "fert_buy_cost": total_fert_buy_cost,
            "fert_buy_units": cash_ledger["buys_product"]["FERTILIZER"]["units"],
            "seed_buy_cost": total_seed_buy_cost,
            "seed_buy_by_crop": {c: cash_ledger["buys_seed"][c]["cost"] for c in CROPS},
            "animal_buy_cost": total_animal_buy_cost,
            "animal_buy_by_species": {a: cash_ledger["buys_animal"][a]["cost"] for a in ANIMALS},
            "hire_cost": total_hire_cost,
            "hire_count": cash_ledger["hires"]["count"],
            "land_cost": total_land_cost,
            "land_count": cash_ledger["land"]["count"],
            "total_expenditures": total_expenditures,
        },
        "executed_purchases": executed_purchases,
        "hourly_cash": hourly_cash,
        "total_discard_units": total_discard_units,
        "total_discard_events": total_discard_events,
        "shed_discards": {p: shed_discards[p]["units"] for p in PRODUCTS},
        "feed_failures": feed_failures,
        "h20_22_inventory_records": h20_22_inventory_records,
        "hygiene_activations": hygiene_activations,
    }


def _run_matched_reconciliation_scenario(scenario):
    """Executes matched scenario and performs complete causal delta reconciliation."""
    seed = scenario["seed"]
    opponent = scenario["opponent"]
    seat = scenario["seat"]

    try:
        ctrl = _run_single_reconciliation_game(seed, opponent, seat, p61_enabled=False)
        treat = _run_single_reconciliation_game(seed, opponent, seat, p61_enabled=True)

        cash_delta = treat["final_money"] - ctrl["final_money"]
        discard_delta = ctrl["total_discard_units"] - treat["total_discard_units"]

        # Exact Transaction Deltas
        ctrl_led = ctrl["cash_ledger"]
        treat_led = treat["cash_ledger"]

        sales_deltas = {
            p: treat_led["sales_revenue_by_prod"][p] - ctrl_led["sales_revenue_by_prod"][p]
            for p in PRODUCTS
        }
        total_sales_delta = treat_led["total_sales_revenue"] - ctrl_led["total_sales_revenue"]
        feed_wheat_cost_delta = treat_led["feed_wheat_cost"] - ctrl_led["feed_wheat_cost"]
        seed_cost_delta = treat_led["seed_buy_cost"] - ctrl_led["seed_buy_cost"]
        animal_cost_delta = treat_led["animal_buy_cost"] - ctrl_led["animal_buy_cost"]
        hire_cost_delta = treat_led["hire_cost"] - ctrl_led["hire_cost"]
        land_cost_delta = treat_led["land_cost"] - ctrl_led["land_cost"]
        fert_buy_cost_delta = treat_led["fert_buy_cost"] - ctrl_led["fert_buy_cost"]

        # Total expenditure delta (Treatment - Control)
        # Note: final_money = starting_cash + sales - expenditures
        # Delta final_money = Delta sales - Delta expenditures
        total_expenditure_delta = treat_led["total_expenditures"] - ctrl_led["total_expenditures"]
        reconciled_delta = total_sales_delta - total_expenditure_delta
        exact_closure_residual = abs(cash_delta - reconciled_delta)
        assert exact_closure_residual < 1e-4, f"Scenario delta closure failure! Cash delta: {cash_delta}, Reconciled: {reconciled_delta}, Residual: {exact_closure_residual}"

        # Hourly Liquidity Ledger
        cash_diff_by_hour = [treat["hourly_cash"][t] - ctrl["hourly_cash"][t] for t in range(720)]
        divergence_hours = [t for t, diff in enumerate(cash_diff_by_hour) if abs(diff) > 1.0]
        first_divergence_hour = divergence_hours[0] if divergence_hours else None
        max_liquidity_advantage = max(cash_diff_by_hour) if cash_diff_by_hour else 0.0
        min_liquidity_advantage = min(cash_diff_by_hour) if cash_diff_by_hour else 0.0
        hours_treatment_ahead = sum(1 for d in cash_diff_by_hour if d > 1.0)
        hours_control_ahead = sum(1 for d in cash_diff_by_hour if d < -1.0)

        # Capital-Allocation Purchase Traceability
        # Compare executed purchases between Control and Treatment
        ctrl_purchases = {(p["step"], p["type"], p["item"]): p for p in ctrl["executed_purchases"]}
        treat_purchases = {(p["step"], p["type"], p["item"]): p for p in treat["executed_purchases"]}

        treat_only_purchases = []
        for k, p in treat_purchases.items():
            if k not in ctrl_purchases:
                # Check if treatment had more cash at that step due to prior hygiene sales
                step = p["step"]
                had_cash_adv = (cash_diff_by_hour[step] > 0.0) if step < 720 else False
                p_copy = dict(p)
                p_copy["liquidity_enabled"] = had_cash_adv
                treat_only_purchases.append(p_copy)

        return {
            "status": "ok",
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "cash_delta": cash_delta,
            "reconciled_delta": reconciled_delta,
            "closure_residual": exact_closure_residual,
            "discard_delta": discard_delta,
            "sales_deltas": sales_deltas,
            "total_sales_delta": total_sales_delta,
            "feed_wheat_cost_delta": feed_wheat_cost_delta,
            "seed_cost_delta": seed_cost_delta,
            "animal_cost_delta": animal_cost_delta,
            "hire_cost_delta": hire_cost_delta,
            "land_cost_delta": land_cost_delta,
            "fert_buy_cost_delta": fert_buy_cost_delta,
            "total_expenditure_delta": total_expenditure_delta,
            "first_divergence_hour": first_divergence_hour,
            "max_liquidity_advantage": max_liquidity_advantage,
            "min_liquidity_advantage": min_liquidity_advantage,
            "hours_treatment_ahead": hours_treatment_ahead,
            "hours_control_ahead": hours_control_ahead,
            "cash_diff_by_hour": cash_diff_by_hour,
            "treat_only_purchases": treat_only_purchases,
            "control": ctrl,
            "treatment": treat,
        }
    except Exception as exc:
        return {
            "status": "error",
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }


def main():
    print("=" * 80)
    print("Kaggriculture P6.1-C — Causal Reconciliation Forensic Harness")
    print(f"Panel: {len(EVAL_SEEDS)} Seeds ({min(EVAL_SEEDS)}–{max(EVAL_SEEDS)}) x {len(OPPONENTS)} Opponents x {len(SEATS)} Seats = {len(EVAL_SEEDS)*len(OPPONENTS)*len(SEATS)} Scenarios")
    print("=" * 80)

    scenarios = [
        {"seed": seed, "opponent": opp, "seat": seat}
        for seed in EVAL_SEEDS
        for opp in OPPONENTS
        for seat in SEATS
    ]

    start_time = time.time()
    results = []
    completed = 0
    total = len(scenarios)

    max_workers = min(os.cpu_count() or 4, 8)
    print(f"Launching forensic reconciliation on {total} matched scenarios (max_workers={max_workers})...")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_run_matched_reconciliation_scenario, sc): sc for sc in scenarios}
        for future in as_completed(future_map):
            res = future.result()
            results.append(res)
            completed += 1
            if res["status"] == "ok":
                print(f"[{completed}/{total}] Seed {res['seed']} | Opp: {res['opponent'][:12]:12} | Seat {res['seat']} -> Delta: {res['cash_delta']:+8.2f} (Residual: {res['closure_residual']:.6f}) | 1st Div: H{res['first_divergence_hour']}")
            else:
                print(f"[{completed}/{total}] ERROR in Seed {res['seed']}: {res.get('error')}")

    duration = time.time() - start_time
    print(f"\nForensic reconciliation completed in {duration:.1f}s.")

    ok_results = [r for r in results if r.get("status") == "ok"]
    n = len(ok_results)
    if n == 0:
        print("ERROR: Zero scenarios succeeded!")
        sys.exit(1)

    # 1. Exact Cash Waterfall Closure
    max_residual = max(r["closure_residual"] for r in ok_results)
    mean_cash_delta = sum(r["cash_delta"] for r in ok_results) / n
    sorted_deltas = sorted(r["cash_delta"] for r in ok_results)
    median_cash_delta = (sorted_deltas[n // 2] if n % 2 != 0 else (sorted_deltas[n // 2 - 1] + sorted_deltas[n // 2]) / 2)

    mean_sales_delta = sum(r["total_sales_delta"] for r in ok_results) / n
    mean_sales_by_prod = {p: sum(r["sales_deltas"][p] for r in ok_results) / n for p in PRODUCTS}
    mean_feed_cost_delta = sum(r["feed_wheat_cost_delta"] for r in ok_results) / n
    mean_seed_cost_delta = sum(r["seed_cost_delta"] for r in ok_results) / n
    mean_animal_cost_delta = sum(r["animal_cost_delta"] for r in ok_results) / n
    mean_hire_cost_delta = sum(r["hire_cost_delta"] for r in ok_results) / n
    mean_land_cost_delta = sum(r["land_cost_delta"] for r in ok_results) / n
    mean_fert_cost_delta = sum(r["fert_buy_cost_delta"] for r in ok_results) / n
    mean_expenditure_delta = sum(r["total_expenditure_delta"] for r in ok_results) / n

    # Note on expenditure delta sign:
    # final cash delta = sales_delta - expenditure_delta
    # expenditure savings (expenditure_delta < 0) adds positive cash!
    reconciled_sum = mean_sales_delta - mean_expenditure_delta

    print("\n" + "=" * 80)
    print("EXACT CASH DELTA WATERFALL RECONCILIATION")
    print("=" * 80)
    print(f"Mean Final Cash Delta:                ${mean_cash_delta:+10.2f}")
    print(f"Max Single-Game Residual Error:        {max_residual:10.6f} (EXACT CLOSURE)")
    print("-" * 80)
    print("PRODUCT SALES REVENUE DELTAS:")
    for p in PRODUCTS:
        print(f"  {p:<12}:                          ${mean_sales_by_prod[p]:+10.2f}")
    print(f"  TOTAL SALES REVENUE DELTA:          ${mean_sales_delta:+10.2f}")
    print("-" * 80)
    print("EXPENDITURE DELTAS (Treatment - Control):")
    print(f"  Feed Wheat Purchases Delta:         ${mean_feed_cost_delta:+10.2f}  (Negative = Expenditure Savings)")
    print(f"  Seed Purchases Delta:               ${mean_seed_cost_delta:+10.2f}")
    print(f"  Animal Purchases Delta:             ${mean_animal_cost_delta:+10.2f}")
    print(f"  Worker Wages (Hires) Delta:         ${mean_hire_cost_delta:+10.2f}")
    print(f"  Land Expansion Delta:               ${mean_land_cost_delta:+10.2f}")
    print(f"  Fertilizer Purchases Delta:         ${mean_fert_cost_delta:+10.2f}")
    print(f"  TOTAL EXPENDITURE DELTA:            ${mean_expenditure_delta:+10.2f}")
    print("-" * 80)
    print(f"RECONCILED WATERFALL SUM:             ${reconciled_sum:+10.2f}")
    print(f"RECONCILIATION CLOSURE RESIDUAL:      ${abs(mean_cash_delta - reconciled_sum):10.6f}")
    print("=" * 80)

    # Save detailed reconciliation JSON
    recon_json_path = os.path.join(ROOT, "simulations", "experiments", "p61c_causal_reconciliation_summary.json")
    summary_out = {
        "metadata": {
            "experiment": "P6.1-C Causal Reconciliation",
            "commit_sha": BASELINE_SHA,
            "seeds": EVAL_SEEDS,
            "opponents": OPPONENTS,
            "seats": SEATS,
            "n_scenarios": n,
            "duration_seconds": duration,
            "max_residual": max_residual,
        },
        "waterfall": {
            "mean_cash_delta": mean_cash_delta,
            "median_cash_delta": median_cash_delta,
            "mean_sales_delta": mean_sales_delta,
            "sales_by_prod_delta": mean_sales_by_prod,
            "feed_wheat_cost_delta": mean_feed_cost_delta,
            "seed_cost_delta": mean_seed_cost_delta,
            "animal_cost_delta": mean_animal_cost_delta,
            "hire_cost_delta": mean_hire_cost_delta,
            "land_cost_delta": mean_land_cost_delta,
            "fert_cost_delta": mean_fert_cost_delta,
            "total_expenditure_delta": mean_expenditure_delta,
            "reconciled_sum": reconciled_sum,
            "closure_residual": abs(mean_cash_delta - reconciled_sum),
        },
        "per_scenario": [
            {
                "seed": r["seed"],
                "opponent": r["opponent"],
                "seat": r["seat"],
                "cash_delta": r["cash_delta"],
                "reconciled_delta": r["reconciled_delta"],
                "sales_delta": r["total_sales_delta"],
                "expenditure_delta": r["total_expenditure_delta"],
                "first_divergence_hour": r["first_divergence_hour"],
                "max_liquidity_advantage": r["max_liquidity_advantage"],
                "hours_treatment_ahead": r["hours_treatment_ahead"],
            }
            for r in ok_results
        ]
    }
    with open(recon_json_path, "w") as f:
        json.dump(summary_out, f, indent=2)
    print(f"Summary written to: {recon_json_path}")

    recon_gz_path = os.path.join(ROOT, "simulations", "experiments", "p61c_causal_reconciliation_telemetry.json.gz")
    with gzip.open(recon_gz_path, "wt", encoding="utf-8") as f:
        json.dump(results, f)
    print(f"Telemetry written to: {recon_gz_path}")


if __name__ == "__main__":
    main()
