"""Point 2 WHEAT-Flow and Churn Diagnostic Runner.

Investigates whether live Point 2 loses score because of:
  H1: Excessive WHEAT turnover / buy-sell-rebuy churn
  H2: WHEAT price inflation from own repeated buying
  H3: Pasture / crop opportunity displacement
  H4: Livestock itself having poor marginal economics

Evaluates 4 arms across 10 paired seeds (40 full seasons):
  S: Shadow Baseline (POINT2_FEED_MODE="shadow", H=False, F=False)
  A: Frozen Live Baseline (POINT2_FEED_MODE="live", H=False, F=False)
  C: Funding Fix Only (POINT2_FEED_MODE="live", H=False, F=True)
  D: Housing + Funding Fix (POINT2_FEED_MODE="live", H=True, F=True)

Seeds: [42, 101, 2024, 7, 999, 1234, 55, 314, 8888, 777]
"""

import copy
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Ensure agent and root directory are in sys.path
root_dir = os.path.abspath(".")
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

agent_dir = os.path.abspath("agent")
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

import config
import kaggle_environments
import kaggle_environments.envs.kaggriculture.kaggriculture as eng

from main import (
    _agent_decision,
    get_central_planner_diagnostics,
    get_last_turn_telemetry,
    reset_agent_state,
)
from simulations.experiments.agent_zoo import get_agent

SEEDS_CONFIG = [
    {"seed": 42, "opponent": "pass"},
    {"seed": 101, "opponent": "pure_wheat_rush"},
    {"seed": 2024, "opponent": "cow_milk_engine"},
    {"seed": 7, "opponent": "melon_sniper"},
    {"seed": 999, "opponent": "full_production_agent"},
    {"seed": 1234, "opponent": "pass"},
    {"seed": 55, "opponent": "pure_wheat_rush"},
    {"seed": 314, "opponent": "cow_milk_engine"},
    {"seed": 8888, "opponent": "melon_sniper"},
    {"seed": 777, "opponent": "full_production_agent"},
]


def run_single_season(
    seed: int,
    opponent_name: str,
    arm_key: str,
    mode: str,
    housing_fix: bool,
    funding_fix: bool,
) -> Dict[str, Any]:
    """Execute a single 720-step season with comprehensive WHEAT flow tracking."""
    # Configure parameters for this run
    config.POINT2_FEED_MODE = mode
    config.POINT2_HOUSING_FIX_ENABLED = housing_fix
    config.POINT2_FUNDING_HORIZON_FIX_ENABLED = funding_fix
    config.FEED_FINANCIAL_HORIZON_DAYS = 8

    reset_agent_state()

    opp_callable = get_agent(opponent_name)
    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.reset(2)

    # State tracking containers
    executed_buys: List[Dict[str, Any]] = []
    executed_sells: List[Dict[str, Any]] = []
    feed_events: List[Dict[str, Any]] = []
    harvest_events: List[Dict[str, Any]] = []
    discard_events: List[Dict[str, Any]] = []
    buffer_decision_records: List[Dict[str, Any]] = []

    # Pasture tracking: (x, y) -> {"built_day": int, "ever_housed": bool}
    pasture_tiles: Dict[Tuple[int, int], Dict[str, Any]] = {}

    # Current step state
    current_p0_priv: Any = None
    step_ctx: Dict[str, Any] = {}

    orig_commit = eng._commit_unit
    orig_action = eng._apply_unit_action
    orig_drop = eng._drop_inventories_to_shed
    orig_interpreter = env.interpreter

    def hook_commit(op, item, price, farm, private, market, shed_capacity=100):
        is_p0 = (private is current_p0_priv)
        pre_shed_w = private["shed"].get("WHEAT", 0) if (private and "shed" in private) else 0
        pre_worker_w = sum(inv.get("WHEAT", 0) for inv in private.get("inventories", [])) if private else 0

        ok = orig_commit(op, item, price, farm, private, market, shed_capacity)

        if is_p0 and ok and item == "WHEAT":
            post_player_w = private["shed"].get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in private.get("inventories", []))
            s_num = step_ctx.get("step", 0)
            cur_day = s_num // 24
            cur_hour = s_num % 24

            if op == "BUY_PRODUCT":
                rec = {
                    "step": s_num,
                    "day": cur_day,
                    "hour": cur_hour,
                    "quantity": 1,
                    "unit_price": float(price),
                    "total_cost": float(price),
                    "resource_key": step_ctx.get("next_buy_resource_key", "unspecified"),
                    "feed_class": step_ctx.get("next_buy_feed_class", "unspecified"),
                    "is_protected": step_ctx.get("next_buy_is_protected", False),
                    "reason": step_ctx.get("next_buy_reason", "normal_buy"),
                    "pre_buy_shed_wheat": pre_shed_w,
                    "pre_buy_worker_wheat": pre_worker_w,
                    "post_buy_player_wheat": post_player_w,
                    "feed_buffer_target": step_ctx.get("buffer_target", 0),
                    "current_herd": step_ctx.get("herd_count", 0),
                    "market_inventory": float(market["inventory"].get("WHEAT", 0)),
                }
                executed_buys.append(rec)
            elif op == "SELL":
                rec = {
                    "step": s_num,
                    "day": cur_day,
                    "hour": cur_hour,
                    "quantity": 1,
                    "unit_sell_price": float(price),
                    "sale_revenue": float(price),
                    "shed_wheat_before_sale": pre_shed_w,
                    "worker_wheat": pre_worker_w,
                    "effective_sellable_shed_wheat": step_ctx.get("effective_sellable", pre_shed_w),
                    "feed_sale_reservation_valid": step_ctx.get("feed_res_valid", True),
                    "feed_sale_reservation_requires_keys": step_ctx.get("feed_res_keys", []),
                    "minimum_operational_wheat_slack": step_ctx.get("min_slack", 0.0),
                    "current_herd": step_ctx.get("herd_count", 0),
                    "market_inventory": float(market["inventory"].get("WHEAT", 0)),
                }
                executed_sells.append(rec)
        return ok

    def hook_action(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity=100):
        is_p0 = (private is current_p0_priv)
        inv = private["inventories"][idx] if (is_p0 and idx < len(private["inventories"])) else None
        before_w = inv.get("WHEAT", 0) if inv is not None else 0

        orig_action(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity)

        if is_p0 and inv is not None:
            after_w = inv.get("WHEAT", 0)
            s_num = step_ctx.get("step", 0)
            if action and action[0] == "FEED" and after_w == before_w - 1:
                feed_events.append({
                    "step": s_num,
                    "day": day,
                    "hour": s_num % 24,
                    "unit_idx": idx,
                    "quantity": 1,
                })
            elif action and action[0] == "HARVEST" and after_w > before_w:
                harvest_events.append({
                    "step": s_num,
                    "day": day,
                    "hour": s_num % 24,
                    "unit_idx": idx,
                    "quantity": after_w - before_w,
                })
            elif action and action[0] == "BUILD_PASTURE":
                pos = eng._farmer_position(farm, idx)
                if pos:
                    t_pos = tuple(pos)
                    if t_pos not in pasture_tiles:
                        pasture_tiles[t_pos] = {"built_day": day, "ever_housed": False}

    def hook_drop(private, capacity):
        is_p0 = (private is current_p0_priv)
        if is_p0:
            before_total = private["shed"].get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in private.get("inventories", []))
            orig_drop(private, capacity)
            after_total = private["shed"].get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in private.get("inventories", []))
            if after_total < before_total:
                s_num = step_ctx.get("step", 0)
                discard_events.append({
                    "step": s_num,
                    "day": s_num // 24,
                    "hour": s_num % 24,
                    "quantity": before_total - after_total,
                })
        else:
            orig_drop(private, capacity)

    def hook_interpreter(state, env_obj):
        nonlocal current_p0_priv
        if state and hasattr(state[0].observation, "private"):
            current_p0_priv = state[0].observation.private
        return orig_interpreter(state, env_obj)

    eng._commit_unit = hook_commit
    eng._apply_unit_action = hook_action
    eng._drop_inventories_to_shed = hook_drop
    env.interpreter = hook_interpreter

    # Starting wheat in player possession
    obs0_init = env.state[0].observation
    init_priv = obs0_init.private
    starting_wheat = init_priv["shed"].get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in init_priv.get("inventories", []))

    market_wheat_inventories: List[float] = []

    try:
        step = 0
        while not env.done:
            obs0 = env.state[0].observation
            obs1 = env.state[1].observation
            day = obs0.get("day", step // 24)
            hour = obs0.get("hour", step % 24)

            # Record market inventory
            m_inv = float(obs0.get("market", {}).get("inventory", {}).get("WHEAT", 10000))
            market_wheat_inventories.append(m_inv)

            # Track existing pastures and check animal presence
            farms = obs0.get("farms", [])
            farm = farms[0] if farms else {}
            board_tiles_2d = farm.get("tiles", [])
            all_tiles = [t for row in board_tiles_2d for t in row if isinstance(t, dict)]
            herd_count = sum(1 for t in all_tiles if t.get("animal") or t.get("is_animal"))

            for y, row in enumerate(board_tiles_2d):
                for x, t in enumerate(row):
                    if isinstance(t, dict) and t.get("kind") == "PASTURE":
                        if (x, y) not in pasture_tiles:
                            pasture_tiles[(x, y)] = {"built_day": day, "ever_housed": False}
                        if t.get("animal") or t.get("is_animal"):
                            pasture_tiles[(x, y)]["ever_housed"] = True

            priv = obs0.private
            wheat_on_hand = priv["shed"].get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in priv.get("inventories", []))

            # Decide agent action
            action0 = _agent_decision(obs0)
            try:
                action1 = opp_callable(obs1)
            except Exception:
                action1 = {"farmer": ["PASS"], "hands": [], "market": []}

            # Gather telemetry from decision
            cp_diag = get_central_planner_diagnostics()
            telem = get_last_turn_telemetry() or {}

            # Prepare step context for hooks
            step_ctx["step"] = step
            step_ctx["herd_count"] = herd_count
            step_ctx["buffer_target"] = herd_count * 4
            step_ctx["effective_sellable"] = cp_diag.get("effective_sellable_shed_wheat", priv["shed"].get("WHEAT", 0))
            step_ctx["min_slack"] = cp_diag.get("minimum_operational_wheat_slack", 0.0)

            feed_sale_res = cp_diag.get("feed_sale_reservation", {})
            step_ctx["feed_res_valid"] = feed_sale_res.get("valid", True) if isinstance(feed_sale_res, dict) else True
            step_ctx["feed_res_keys"] = feed_sale_res.get("requires_resource_keys", []) if isinstance(feed_sale_res, dict) else []

            # Extract proposal metadata for BUY_PRODUCT WHEAT
            accepted_details = cp_diag.get("accepted_details", [])
            wheat_buys_accepted = [
                d for d in accepted_details
                if d.get("order") and len(d["order"]) >= 2 and d["order"][0] == "BUY_PRODUCT" and d["order"][1] == "WHEAT"
            ]
            if wheat_buys_accepted:
                first_wb = wheat_buys_accepted[0]
                meta = first_wb.get("metadata", {})
                step_ctx["next_buy_resource_key"] = meta.get("resource_key", "unspecified")
                step_ctx["next_buy_feed_class"] = meta.get("feed_class", "unspecified")
                step_ctx["next_buy_is_protected"] = meta.get("is_protected", False)
                step_ctx["next_buy_reason"] = first_wb.get("rejection_reason") or "accepted"
            else:
                step_ctx["next_buy_resource_key"] = "unspecified"
                step_ctx["next_buy_feed_class"] = "unspecified"
                step_ctx["next_buy_is_protected"] = False
                step_ctx["next_buy_reason"] = "normal_buy"

            # Buffer behavior snapshot
            wt = cp_diag.get("wheat_telemetry", {})
            opt_req = wt.get("wheat_optional_count", 0)
            opt_sel = 1 if wt.get("wheat_optional_selected") else 0
            prot_req = wt.get("wheat_protected_count", 0)
            prot_sel = 1 if wt.get("wheat_protected_selected") else 0

            # Count wheat sold proposed
            sells_wheat_proposed = sum(
                int(o[2]) for o in action0.get("market", [])
                if len(o) >= 3 and o[0] == "SELL" and o[1] == "WHEAT"
            )

            buffer_decision_records.append({
                "step": step,
                "day": day,
                "hour": hour,
                "herd_size": herd_count,
                "wheat_on_hand": wheat_on_hand,
                "buffer_target_4day": herd_count * 4,
                "optional_wheat_requested": opt_req,
                "optional_wheat_executed": opt_sel,
                "protected_wheat_requested": prot_req,
                "protected_wheat_executed": prot_sel,
                "effective_sellable_wheat": step_ctx["effective_sellable"],
                "proposed_wheat_sold": sells_wheat_proposed,
            })

            # Step simulation
            env.step([action0, action1])
            step += 1

    finally:
        eng._commit_unit = orig_commit
        eng._apply_unit_action = orig_action
        eng._drop_inventories_to_shed = orig_drop
        env.interpreter = orig_interpreter

    # Final season observation & metrics
    final_score = float(env.state[0].reward or 0.0)
    final_obs0 = env.state[0].observation
    final_priv = final_obs0.private
    ending_wheat = final_priv["shed"].get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in final_priv.get("inventories", []))

    total_harvested = sum(e["quantity"] for e in harvest_events)
    total_bought = sum(b["quantity"] for b in executed_buys)
    total_feed = sum(e["quantity"] for e in feed_events)
    total_sold = sum(s["quantity"] for s in executed_sells)
    total_discarded = sum(d["quantity"] for d in discard_events)

    # Physical reconciliation
    reconciled_ending = starting_wheat + total_harvested + total_bought - total_feed - total_sold - total_discarded
    reconciliation_error = reconciled_ending - ending_wheat

    assert reconciliation_error == 0, (
        f"Reconciliation error non-zero! Seed={seed} Arm={arm_key}: "
        f"Start={starting_wheat}, Harvest={total_harvested}, Bought={total_bought}, "
        f"Feed={total_feed}, Sold={total_sold}, Discard={total_discarded}, "
        f"Reconciled={reconciled_ending}, ActualEnding={ending_wheat}, Err={reconciliation_error}"
    )

    # Buy breakdowns
    protected_buys = [b for b in executed_buys if b.get("is_protected") or b.get("feed_class") == "protected" or b.get("resource_key") == "wheat:protected"]
    optional_buys = [b for b in executed_buys if not (b.get("is_protected") or b.get("feed_class") == "protected" or b.get("resource_key") == "wheat:protected")]

    protected_qty = sum(b["quantity"] for b in protected_buys)
    optional_qty = sum(b["quantity"] for b in optional_buys)
    total_wheat_spend = sum(b["total_cost"] for b in executed_buys)
    avg_buy_price = (total_wheat_spend / total_bought) if total_bought > 0 else 0.0
    max_buy_price = max((b["unit_price"] for b in executed_buys), default=0.0)
    min_buy_price = min((b["unit_price"] for b in executed_buys), default=0.0)

    # Sell breakdowns
    total_sale_revenue = sum(s["sale_revenue"] for s in executed_sells)
    avg_sell_price = (total_sale_revenue / total_sold) if total_sold > 0 else 0.0

    # Churn analysis (FIFO lot matching)
    same_day_buy_sell_qty = 0
    within_24h_buy_sell_qty = 0
    same_day_sell_rebuy_qty = 0
    within_24h_sell_rebuy_qty = 0

    for b in executed_buys:
        b_step = b["step"]
        b_day = b["day"]
        for s in executed_sells:
            s_step = s["step"]
            if 0 < s_step - b_step <= 24:
                within_24h_buy_sell_qty += 1
                if s["day"] == b_day:
                    same_day_buy_sell_qty += 1
                break

    for s in executed_sells:
        s_step = s["step"]
        s_day = s["day"]
        for b in executed_buys:
            b_step = b["step"]
            if 0 < b_step - s_step <= 24:
                within_24h_sell_rebuy_qty += 1
                if b["day"] == s_day:
                    same_day_sell_rebuy_qty += 1
                break

    total_churn_units = min(total_bought, total_sold)
    gross_turnover = total_bought + total_sold
    buy_to_feed_ratio = (total_bought / total_feed) if total_feed > 0 else (float("inf") if total_bought > 0 else 0.0)

    # Churn trading loss: buy cost - sale proceeds + rebuy premium
    churn_loss = 0.0
    matched_n = min(len(executed_buys), len(executed_sells))
    for i in range(matched_n):
        b_px = executed_buys[i]["unit_price"]
        s_px = executed_sells[i]["unit_sell_price"]
        loss = max(0.0, b_px - s_px)
        if i < len(executed_buys) - 1:
            next_b_px = executed_buys[i + 1]["unit_price"]
            loss += max(0.0, next_b_px - s_px)
        churn_loss += loss

    # Buffer loop detection
    buffer_loop_units = 0
    for b in optional_buys:
        b_step = b["step"]
        later_sells = [s for s in executed_sells if s["step"] > b_step]
        if later_sells:
            first_sale = later_sells[0]
            later_rebuys = [rb for rb in executed_buys if rb["step"] > first_sale["step"]]
            if later_rebuys:
                buffer_loop_units += 1

    # Pasture displacement metrics
    total_pastures = len(pasture_tiles)
    final_board_tiles = [t for row in final_obs0.get("farms", [{}])[0].get("tiles", []) for t in row if isinstance(t, dict)]
    final_herd = sum(1 for t in final_board_tiles if t.get("animal") or t.get("is_animal"))
    final_pastures_count = sum(1 for t in final_board_tiles if t.get("kind") == "PASTURE")

    unused_pastures = max(0, final_pastures_count - final_herd)
    pastures_never_housed = sum(1 for p_info in pasture_tiles.values() if not p_info["ever_housed"])
    pasture_build_actions = total_pastures

    total_pasture_tile_days = sum(30 - p_info["built_day"] for p_info in pasture_tiles.values())
    crop_opportunity_lost = total_pasture_tile_days * 30.0

    return {
        "seed": seed,
        "opponent": opponent_name,
        "arm": arm_key,
        "mode": mode,
        "final_score": round(final_score, 2),
        "final_herd": final_herd,
        "reconciliation": {
            "starting_wheat": starting_wheat,
            "harvested_wheat": total_harvested,
            "market_wheat_bought": total_bought,
            "actual_feed_consumed": total_feed,
            "wheat_sold": total_sold,
            "discarded_wheat": total_discarded,
            "ending_wheat": ending_wheat,
            "reconciled_ending": reconciled_ending,
            "reconciliation_error": reconciliation_error,
        },
        "market_buys": {
            "total_bought": total_bought,
            "protected_bought": protected_qty,
            "optional_bought": optional_qty,
            "total_spend": round(total_wheat_spend, 2),
            "avg_buy_price": round(avg_buy_price, 2),
            "max_buy_price": round(max_buy_price, 2),
            "min_buy_price": round(min_buy_price, 2),
            "executed_buys_sample": executed_buys[:5],
        },
        "market_sells": {
            "total_sold": total_sold,
            "total_revenue": round(total_sale_revenue, 2),
            "avg_sell_price": round(avg_sell_price, 2),
            "net_wheat_cost": round(total_wheat_spend - total_sale_revenue, 2),
            "executed_sells_sample": executed_sells[:5],
        },
        "churn": {
            "same_day_buy_sell_qty": same_day_buy_sell_qty,
            "within_24h_buy_sell_qty": within_24h_buy_sell_qty,
            "same_day_sell_rebuy_qty": same_day_sell_rebuy_qty,
            "within_24h_sell_rebuy_qty": within_24h_sell_rebuy_qty,
            "total_churn_units": total_churn_units,
            "gross_turnover": gross_turnover,
            "buy_to_feed_ratio": round(buy_to_feed_ratio, 2),
            "churn_trading_loss": round(churn_loss, 2),
            "buffer_loop_units": buffer_loop_units,
        },
        "market_price_impact": {
            "avg_market_inventory": round(sum(market_wheat_inventories) / len(market_wheat_inventories), 1),
            "min_market_inventory": round(min(market_wheat_inventories), 1),
            "final_market_inventory": round(market_wheat_inventories[-1], 1),
        },
        "pasture_displacement": {
            "total_pastures": total_pastures,
            "final_pastures": final_pastures_count,
            "unused_pastures": unused_pastures,
            "pastures_never_housed": pastures_never_housed,
            "build_actions_spent": pasture_build_actions,
            "total_pasture_tile_days": total_pasture_tile_days,
            "crop_opportunity_lost": round(crop_opportunity_lost, 2),
        },
    }


def run_full_diagnostic():
    """Run all 4 arms across 10 seeds and compile the diagnostic dataset."""
    arms = {
        "S": {"name": "Shadow Baseline", "mode": "shadow", "housing_fix": False, "funding_fix": False},
        "A": {"name": "Frozen Live Baseline", "mode": "live", "housing_fix": False, "funding_fix": False},
        "C": {"name": "Funding Fix Only", "mode": "live", "housing_fix": False, "funding_fix": True},
        "D": {"name": "Housing + Funding", "mode": "live", "housing_fix": True, "funding_fix": True},
    }

    results: Dict[str, Any] = {}
    t_start_all = time.time()

    for arm_key, arm_cfg in arms.items():
        print(f"\n{'='*75}\nExecuting Arm {arm_key}: {arm_cfg['name']} (mode={arm_cfg['mode']}, H={arm_cfg['housing_fix']}, F={arm_cfg['funding_fix']})\n{'='*75}", flush=True)
        arm_seasons = []
        t_arm_start = time.time()

        for s_idx, cfg in enumerate(SEEDS_CONFIG):
            seed = cfg["seed"]
            opp = cfg["opponent"]
            t0 = time.time()
            res = run_single_season(
                seed=seed,
                opponent_name=opp,
                arm_key=arm_key,
                mode=arm_cfg["mode"],
                housing_fix=arm_cfg["housing_fix"],
                funding_fix=arm_cfg["funding_fix"],
            )
            elap = time.time() - t0
            arm_seasons.append(res)
            rec = res["reconciliation"]
            buys = res["market_buys"]
            sells = res["market_sells"]
            ch = res["churn"]
            print(
                f"[{arm_key}] Seed {seed:5d} vs {opp:20s} -> Score: ${res['final_score']:9.2f} | "
                f"Herd: {res['final_herd']} | Feed: {rec['actual_feed_consumed']} | "
                f"Buy: {buys['total_bought']} (${buys['total_spend']:.0f}) | "
                f"Sell: {sells['total_sold']} (${sells['total_revenue']:.0f}) | "
                f"NetCost: ${sells['net_wheat_cost']:.0f} | "
                f"Churn24h: {ch['within_24h_buy_sell_qty']} | "
                f"ReconErr: {rec['reconciliation_error']} | ({elap:.1f}s)",
                flush=True,
            )

        mean_score = sum(s["final_score"] for s in arm_seasons) / len(arm_seasons)
        arm_elap = time.time() - t_arm_start
        print(f"--> Arm {arm_key} Mean Score: ${mean_score:9.2f} (took {arm_elap:.1f}s)", flush=True)

        results[arm_key] = {
            "config": arm_cfg,
            "mean_score": round(mean_score, 2),
            "seasons": arm_seasons,
        }

    total_time = time.time() - t_start_all
    print(f"\n{'='*75}\nAll 4 arms finished in {total_time:.1f}s\n{'='*75}", flush=True)

    scratch_dir = r"C:\Users\rohit\.gemini\antigravity\brain\2ddd798a-883a-4634-9aac-3c2eaaa51ef3\scratch"
    out_file = os.path.join(scratch_dir, "point2_wheat_flow_diagnostic_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved results to {out_file}")

    return results


if __name__ == "__main__":
    run_full_diagnostic()
