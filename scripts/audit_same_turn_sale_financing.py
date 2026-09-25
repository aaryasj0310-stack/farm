"""Phase M0-I: Authoritative Same-Turn Sale-Funded Financing Audit.

Runs authoritative baseline matches across:
- Seeds: 96501–96510 (10 seeds)
- Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- Seats: 0, 1
Total: 100 matches.

Instruments every turn:
1. Pre-turn cash and reserve requirements.
2. MacroPlanner / OrderBuilder requested, accepted, trimmed, and rejected purchases.
3. Specific rejection reasons (budget, hire_budget, sw_capital_protected, shed_full, etc.).
4. Selected SELL orders and exact guaranteed same-turn sale proceeds lower bound.
5. Financeable gap and capacity/reserve feasibility checks.

Outputs deliverables under simulations/results/phase_m0_i_financing_audit/:
- manifest.json
- source_hashes.json
- rejected_purchase_inventory.json
- cash_constraint_events.json
- guaranteed_sale_proceeds.json
- financeable_purchases.json
- blocked_reason_breakdown.json
- purchase_type_breakdown.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_i_financing_audit")
os.makedirs(OUT_DIR, exist_ok=True)

AUDIT_SEEDS = list(range(96501, 96511))
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]

CROPS_SPEC = {
    "WHEAT": 10,
    "CARROT": 20,
    "TOMATO": 50,
    "STRAWBERRY": 100,
    "MELON": 80,
}

ANIMALS_SPEC = {
    "GOOSE": 300,
    "COW": 400,
    "SHEEP": 500,
}

LAND_PRICES = [1000, 2000]


def get_source_hashes() -> Dict[str, str]:
    files = {
        "kaggriculture.py": r"C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py",
        "agent/main.py": os.path.join(_AGENT_DIR, "main.py"),
        "agent/config.py": os.path.join(_AGENT_DIR, "config.py"),
        "agent/market/order_builder.py": os.path.join(_AGENT_DIR, "market", "order_builder.py"),
        "agent/market/price_math.py": os.path.join(_AGENT_DIR, "market", "price_math.py"),
        "agent/strategy/central_planner.py": os.path.join(_AGENT_DIR, "strategy", "central_planner.py"),
        "agent/strategy/macro_planner.py": os.path.join(_AGENT_DIR, "strategy", "macro_planner.py"),
    }
    hashes = {}
    for name, path in files.items():
        if os.path.exists(path):
            with open(path, "rb") as f:
                hashes[name] = hashlib.sha256(f.read()).hexdigest()
        else:
            hashes[name] = "NOT_FOUND"
    return hashes


def run_audit_match(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    from agent.main import agent, reset_agent_state, get_last_turn_telemetry
    import config
    from market.order_builder import _fib
    from market.price_math import market_price, estimate_wheat_buy_price
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    # Baseline invariants
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    config.set_midnight_storage_dump_mode("OFF")
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")

    reset_agent_state()
    reset_sw_tranche_controller()

    match_id = f"{seed}_{opp_name}_seat{seat}"
    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    rejected_inventory: List[Dict[str, Any]] = []
    cash_constraint_events: List[Dict[str, Any]] = []
    guaranteed_proceeds_events: List[Dict[str, Any]] = []
    financeable_events: List[Dict[str, Any]] = []

    step_num = 0
    while not env.done:
        obs_pre = env.state[seat].observation
        day = step_num // 24
        hour = step_num % 24

        act = agent(obs_pre, env.configuration)
        try:
            opp_act = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_act = opp_agent(env.state[1 - seat].observation)

        actions = [act, opp_act] if seat == 0 else [opp_act, act]
        env.step(actions)

        telem = get_last_turn_telemetry()
        if telem:
            money_before = float(telem.get("money_before", 0.0))
            p_ledger = telem.get("purchase_ledger") or {}
            budget = float(p_ledger.get("budget", 0.0))
            reserve = float(p_ledger.get("reserve", 50.0))
            market_inv = dict(telem.get("market_inventory_before", {}))
            shed_dict = getattr(obs_pre.private, "shed", {}) if hasattr(obs_pre, "private") else {}
            shed_total = sum(shed_dict.values()) if shed_dict else 0
            scheduled_deposits = dict(telem.get("scheduled_product_deposits", {}) or {})
            market_orders = telem.get("market", [])
            market_slots_used = len(market_orders)

            # Selected SELL orders
            selected_sells = [list(o) for o in market_orders if o[0] == "SELL"]

            # Compute guaranteed sale proceeds lower bound
            simulated_inv = dict(market_inv)
            guaranteed_revenue = 0.0
            sell_details_list = []
            for s_ord in selected_sells:
                prod = s_ord[1]
                req_qty = int(s_ord[2])
                avail_shed = int(shed_dict.get(prod, 0)) + int(scheduled_deposits.get(prod, 0))
                exec_qty = min(req_qty, max(0, avail_shed))
                ord_rev = 0.0
                curr_inv = float(simulated_inv.get(prod, 10000))
                for u in range(exec_qty):
                    px = market_price(prod, curr_inv + u)
                    ord_rev += px
                simulated_inv[prod] = curr_inv + exec_qty
                guaranteed_revenue += ord_rev
                sell_details_list.append({
                    "product": prod,
                    "requested_qty": req_qty,
                    "available_inventory": avail_shed,
                    "guaranteed_units": exec_qty,
                    "guaranteed_revenue": ord_rev,
                })

            if selected_sells:
                guaranteed_proceeds_events.append({
                    "match_id": match_id,
                    "seed": seed,
                    "opponent": opp_name,
                    "seat": seat,
                    "step": step_num,
                    "day": day,
                    "hour": hour,
                    "money_before": money_before,
                    "sell_orders": sell_details_list,
                    "guaranteed_revenue": guaranteed_revenue,
                })

            # Inspect dropped purchases
            dropped_raw = p_ledger.get("dropped", [])
            turn_dropped: List[Dict[str, Any]] = []

            for d in dropped_raw:
                if not isinstance(d, dict):
                    continue
                k = d.get("kind", "unknown")
                r = str(d.get("reason", "unknown"))

                lost_units = 0
                req_units = 0
                aff_units = 0
                cost = 0.0
                crop_or_animal = ""

                if k == "hire_budget":
                    k = "HIRE"
                    r = "hire_budget"
                    req_units = int(d.get("requested", 0))
                    aff_units = int(d.get("affordable", 0))
                    lost_units = int(d.get("lost", req_units - aff_units))
                    start_h = 0
                    if hasattr(obs_pre, "public") and hasattr(obs_pre.public, "farms"):
                        start_h = getattr(obs_pre.public.farms[seat], "hires_today", 0)
                    cost = sum(float(_fib(start_h + aff_units + j)) for j in range(lost_units))
                elif k in ("wheat_protected", "wheat_optional"):
                    req_w = int(p_ledger.get("w_protected_buyable", 0) + p_ledger.get("w_opt_buyable", 0))
                    buy_w = int(p_ledger.get("w_protected_buyable", 0) if k == "wheat_protected" else p_ledger.get("w_opt_buyable", 0))
                    lost_units = max(1, req_w - buy_w) if req_w > buy_w else 1
                    req_units = buy_w + lost_units
                    aff_units = buy_w
                    unit_px = 25.0
                    cost = float(lost_units * unit_px)
                elif k == "land":
                    k = "BUY_LAND"
                    req_units = 1
                    aff_units = 0
                    lost_units = 1
                    unlocked_count = len(telem.get("unlocked_land", ["NW"]))
                    extra_idx = max(0, min(1, unlocked_count - 1))
                    cost = float(LAND_PRICES[extra_idx])
                elif k == "seed":
                    k = "BUY_SEED"
                    crop_or_animal = d.get("crop", "")
                    req_units = int(d.get("requested", 1))
                    aff_units = int(d.get("affordable", 0))
                    lost_units = int(d.get("lost", max(1, req_units - aff_units)))
                    unit_px = CROPS_SPEC.get(crop_or_animal, 50)
                    cost = float(lost_units * unit_px)
                elif k == "animal":
                    k = "BUY_ANIMAL"
                    crop_or_animal = d.get("animal", "")
                    req_units = int(d.get("trimmed_from", 1))
                    aff_units = int(d.get("to", 0))
                    lost_units = int(req_units - aff_units) if req_units > aff_units else 1
                    cost = float(lost_units * ANIMALS_SPEC.get(crop_or_animal, 400))
                else:
                    req_units = 1
                    lost_units = 1
                    cost = 50.0

                item_entry = {
                    "match_id": match_id,
                    "seed": seed,
                    "opponent": opp_name,
                    "seat": seat,
                    "step": step_num,
                    "day": day,
                    "hour": hour,
                    "kind": k,
                    "crop_or_animal": crop_or_animal,
                    "requested": req_units,
                    "affordable": aff_units,
                    "lost": lost_units,
                    "cost": cost,
                    "reason": r,
                    "is_cash_constrained": r in ("budget", "hire_budget", "sw_capital_protected", "no_cash", "insufficient_funds"),
                }
                rejected_inventory.append(item_entry)
                turn_dropped.append(item_entry)

            # Cash-constrained turns
            cash_lost = [it for it in turn_dropped if it["is_cash_constrained"]]
            if cash_lost:
                total_cash_needed = sum(it["cost"] for it in cash_lost)
                ev = {
                    "match_id": match_id,
                    "seed": seed,
                    "opponent": opp_name,
                    "seat": seat,
                    "step": step_num,
                    "day": day,
                    "hour": hour,
                    "money_before": money_before,
                    "budget": budget,
                    "reserve": reserve,
                    "cash_constrained_items": cash_lost,
                    "total_cash_needed": total_cash_needed,
                    "has_same_turn_sells": len(selected_sells) > 0,
                    "guaranteed_sale_proceeds": guaranteed_revenue,
                    "financeable_gap": guaranteed_revenue - total_cash_needed,
                }
                cash_constraint_events.append(ev)

                # If guaranteed sale proceeds exist, evaluate financing feasibility
                if guaranteed_revenue > 0:
                    remaining_financing = guaranteed_revenue
                    financeable_items = []
                    # Evaluate item by item
                    for it in cash_lost:
                        it_cost = it["cost"]
                        it_kind = it["kind"]
                        it_lost = it["lost"]
                        unit_cost = it_cost / max(1, it_lost)

                        # Check market slot headroom
                        slots_headroom = max(0, 10 - market_slots_used)
                        # Check shed headroom taking into account shed freed by sales
                        shed_freed = sum(s["guaranteed_units"] for s in sell_details_list)
                        net_shed_available = max(0, 100 - (shed_total - shed_freed))

                        if remaining_financing >= unit_cost and slots_headroom > 0:
                            units_affordable_by_sales = min(it_lost, int(remaining_financing // unit_cost))
                            if it_kind in ("BUY_PRODUCT WHEAT", "BUY_ANIMAL", "BUY_SEED"):
                                if it_kind in ("BUY_PRODUCT WHEAT", "BUY_ANIMAL"):
                                    units_affordable_by_sales = min(units_affordable_by_sales, net_shed_available)

                            if units_affordable_by_sales > 0:
                                dollars_financed = units_affordable_by_sales * unit_cost
                                remaining_financing -= dollars_financed
                                market_slots_used += 1  # 1 slot for this purchase order
                                financeable_items.append({
                                    "kind": it_kind,
                                    "crop_or_animal": it["crop_or_animal"],
                                    "lost_units": it_lost,
                                    "financed_units": units_affordable_by_sales,
                                    "financed_dollars": dollars_financed,
                                    "fully_financed": units_affordable_by_sales == it_lost,
                                    "slots_headroom_before": slots_headroom,
                                    "net_shed_headroom": net_shed_available,
                                })

                    if financeable_items:
                        financeable_events.append({
                            "match_id": match_id,
                            "seed": seed,
                            "opponent": opp_name,
                            "seat": seat,
                            "step": step_num,
                            "day": day,
                            "hour": hour,
                            "money_before": money_before,
                            "guaranteed_sale_proceeds": guaranteed_revenue,
                            "financeable_items": financeable_items,
                            "total_dollars_financed": sum(fi["financed_dollars"] for fi in financeable_items),
                            "total_units_financed": sum(fi["financed_units"] for fi in financeable_items),
                        })

        step_num += 1

    final_reward = float(env.steps[-1][seat].reward or 0.0)
    opp_reward = float(env.steps[-1][1 - seat].reward or 0.0)

    return {
        "match_id": match_id,
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "final_cash": final_reward,
        "opp_cash": opp_reward,
        "rejected_inventory": rejected_inventory,
        "cash_constraint_events": cash_constraint_events,
        "guaranteed_proceeds_events": guaranteed_proceeds_events,
        "financeable_events": financeable_events,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-I Financing Opportunity Audit")
    parser.add_argument("--workers", type=int, default=10, help="Number of worker processes")
    args = parser.parse_args()

    start_time = time.time()
    print("=== Phase M0-I: Same-Turn Sale-Funded Financing Audit ===")
    print(f"Seeds: {len(AUDIT_SEEDS)} x Opponents: {len(BENCHMARK_OPPONENTS)} x Seats: {len(SEATS)} = {len(AUDIT_SEEDS) * len(BENCHMARK_OPPONENTS) * len(SEATS)} matches")

    tasks = [(s, opp, seat) for s in AUDIT_SEEDS for opp in BENCHMARK_OPPONENTS for seat in SEATS]
    all_results = []
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(run_audit_match, s, opp, seat): (s, opp, seat) for s, opp, seat in tasks}
        for fut in as_completed(future_map):
            res = fut.result()
            all_results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == len(tasks):
                elapsed = time.time() - start_time
                print(f"[{completed}/{len(tasks)}] matches completed ({elapsed:.1f}s)")

    elapsed_total = time.time() - start_time
    print(f"All {len(tasks)} matches finished in {elapsed_total:.1f}s. Aggregating results...")

    # Aggregate deliverables
    all_rejected: List[Dict[str, Any]] = []
    all_cash_constraints: List[Dict[str, Any]] = []
    all_guaranteed_proceeds: List[Dict[str, Any]] = []
    all_financeable: List[Dict[str, Any]] = []

    for r in all_results:
        all_rejected.extend(r["rejected_inventory"])
        all_cash_constraints.extend(r["cash_constraint_events"])
        all_guaranteed_proceeds.extend(r["guaranteed_proceeds_events"])
        all_financeable.extend(r["financeable_events"])

    # 1. blocked_reason_breakdown.json
    reason_counts: Dict[str, int] = {}
    for it in all_rejected:
        r = it["reason"]
        reason_counts[r] = reason_counts.get(r, 0) + 1
    tot_rejected = max(1, len(all_rejected))
    blocked_reason_breakdown = {
        "total_rejected_or_trimmed": len(all_rejected),
        "counts": reason_counts,
        "percentages": {k: round((v / tot_rejected) * 100, 2) for k, v in reason_counts.items()},
    }

    # 2. purchase_type_breakdown.json
    type_stats: Dict[str, Dict[str, Any]] = {}
    purchase_types = ["HIRE", "BUY_PRODUCT WHEAT", "BUY_LAND", "BUY_SEED", "BUY_ANIMAL"]
    for pt in purchase_types:
        type_stats[pt] = {
            "total_blocked_events": 0,
            "cash_blocked_events": 0,
            "cash_blocked_units": 0,
            "cash_blocked_dollars": 0.0,
            "financeable_events": 0,
            "financeable_units": 0,
            "financeable_dollars": 0.0,
        }

    for it in all_rejected:
        pt = it["kind"]
        if pt in type_stats:
            type_stats[pt]["total_blocked_events"] += 1
            if it["is_cash_constrained"]:
                type_stats[pt]["cash_blocked_events"] += 1
                type_stats[pt]["cash_blocked_units"] += it["lost"]
                type_stats[pt]["cash_blocked_dollars"] += it["cost"]

    for fe in all_financeable:
        for fi in fe["financeable_items"]:
            pt = fi["kind"]
            if pt in type_stats:
                type_stats[pt]["financeable_events"] += 1
                type_stats[pt]["financeable_units"] += fi["financed_units"]
                type_stats[pt]["financeable_dollars"] += fi["financed_dollars"]

    n_matches = len(all_results)
    for pt, st in type_stats.items():
        st["mean_cash_blocked_dollars_per_match"] = round(st["cash_blocked_dollars"] / n_matches, 2)
        st["mean_financeable_dollars_per_match"] = round(st["financeable_dollars"] / n_matches, 2)
        st["mean_financeable_units_per_match"] = round(st["financeable_units"] / n_matches, 2)

    total_financeable_dollars = sum(fe["total_dollars_financed"] for fe in all_financeable)
    mean_financeable_dollars_per_match = total_financeable_dollars / n_matches
    financeable_events_per_match = len(all_financeable) / n_matches

    # Decision Gate A evaluation
    gate_a_passed = (financeable_events_per_match >= 0.1) and (mean_financeable_dollars_per_match >= 250.0)
    verdict = (
        "GATE_A_PASSED" if gate_a_passed
        else "M0-I CLOSED — insufficient same-turn financing opportunities"
    )

    # Write deliverables
    # Source hashes
    source_hashes = get_source_hashes()
    with open(os.path.join(OUT_DIR, "source_hashes.json"), "w", encoding="utf-8") as f:
        json.dump(source_hashes, f, indent=2)

    # Manifest
    manifest = {
        "phase": "M0-I",
        "description": "Authoritative Lost Financing Opportunity Audit",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_seconds": round(elapsed_total, 2),
        "seeds": AUDIT_SEEDS,
        "opponents": BENCHMARK_OPPONENTS,
        "seats": SEATS,
        "matches_count": n_matches,
        "total_turns": n_matches * 720,
        "total_financeable_events": len(all_financeable),
        "financeable_events_per_match": round(financeable_events_per_match, 4),
        "total_financeable_dollars": round(total_financeable_dollars, 2),
        "mean_financeable_dollars_per_match": round(mean_financeable_dollars_per_match, 2),
        "gate_a_thresholds": {
            "min_events_per_match": 0.10,
            "min_dollars_per_match": 250.0,
        },
        "gate_a_passed": gate_a_passed,
        "verdict": verdict,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with open(os.path.join(OUT_DIR, "rejected_purchase_inventory.json"), "w", encoding="utf-8") as f:
        json.dump(all_rejected, f, indent=2)

    with open(os.path.join(OUT_DIR, "cash_constraint_events.json"), "w", encoding="utf-8") as f:
        json.dump(all_cash_constraints, f, indent=2)

    with open(os.path.join(OUT_DIR, "guaranteed_sale_proceeds.json"), "w", encoding="utf-8") as f:
        json.dump(all_guaranteed_proceeds, f, indent=2)

    with open(os.path.join(OUT_DIR, "financeable_purchases.json"), "w", encoding="utf-8") as f:
        json.dump(all_financeable, f, indent=2)

    with open(os.path.join(OUT_DIR, "blocked_reason_breakdown.json"), "w", encoding="utf-8") as f:
        json.dump(blocked_reason_breakdown, f, indent=2)

    with open(os.path.join(OUT_DIR, "purchase_type_breakdown.json"), "w", encoding="utf-8") as f:
        json.dump(type_stats, f, indent=2)

    print("\n=== Phase M0-I Audit Summary ===")
    print(f"Total Matches: {n_matches}")
    print(f"Total Rejected/Trimmed Purchases: {len(all_rejected)}")
    print(f"Total Cash-Constrained Turns: {len(all_cash_constraints)} ({len(all_cash_constraints)/n_matches:.2f}/match)")
    print(f"Total Financeable Turns: {len(all_financeable)} ({financeable_events_per_match:.2f}/match)")
    print(f"Total Financeable Capital: ${total_financeable_dollars:,.2f} (${mean_financeable_dollars_per_match:,.2f}/match)")
    print(f"Gate A Threshold: >= 0.10 events/match and >= $250.00/match")
    print(f"Gate A Verdict: {verdict}")
    print(f"Results written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
