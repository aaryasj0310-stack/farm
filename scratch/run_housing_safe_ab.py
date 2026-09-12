"""Strict Single-Variable A/B Experiment: Housing-Safe Selective Late-Cow Strategy.

Compares:
  Arm A (Control): Day 12 Hard Cutoff (C4_LIVESTOCK_CUTOFF_DAY = 12, SELECTIVE_LIVESTOCK_GATE_ENABLED = False)
  Arm B (Experimental): Selective Gate @ $500 with Housing-Safe Restriction (SELECTIVE_LIVESTOCK_GATE_ENABLED = True)

50 Paired Scenarios (seeds 101-125 vs random and starter = 100 matches total).
Both arms run from current branch with identical arbitration (historical_candidates_central).
Tracks all financial, livestock, labor, safety, and stranded-animal metrics.
"""
import os
import sys
import json
import time
import copy
import argparse
import traceback
from typing import Dict, Any, List, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    arm = payload["arm"]
    cutoff_day = payload["cutoff_day"]
    selective_gate = payload.get("selective_gate", False)
    threshold = payload.get("threshold", 500.0)
    seed = payload["seed"]
    opp_name = payload["opponent"]
    match_id = f"m_{arm}_s{seed}_{opp_name}"

    # Setup isolated environment for agent
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    # Clean local module caches
    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    from config import (
        set_livestock_cutoff_day, set_selective_livestock_gate,
        ANIMALS, CROPS
    )
    from observation_parser import parse_observation

    # Configure experimental variables
    set_livestock_cutoff_day(cutoff_day)
    set_selective_livestock_gate(selective_gate, threshold=threshold, max_day=14)

    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")

    # Match-level tracking
    herd_trajectory = {}
    peak_herd = 0
    day_peak_herd_reached = 0

    # Late animal tracking (Day >= 12)
    late_cow_units = []  # each unit: {order_id, day, hour, guaranteed_at_buy, arrived, picked_up, placed, stranded}
    late_sheep_units = []
    late_orders_emitted = []

    prev_shed_cows = 0
    prev_shed_sheep = 0
    prev_inv_cows = 0
    prev_inv_sheep = 0
    prev_tile_cows = set()
    prev_tile_sheep = set()

    safety_metrics = {
        "feed_failures": 0,
        "animal_starvations": 0,
        "animal_deaths": 0,
        "shed_overflows": 0,
    }

    # Revenue & spend tracking
    spend = {
        "HIRES": 0.0, "LAND": 0.0, "SEEDS": 0.0, "FERTILIZER": 0.0,
        "WHEAT": 0.0, "COW": 0.0, "SHEEP": 0.0, "GOOSE": 0.0,
    }
    revenue = {
        "WHEAT": 0.0, "CARROT": 0.0, "TOMATO": 0.0,
        "STRAWBERRY": 0.0, "MELON": 0.0,
        "MILK": 0.0, "WOOL": 0.0, "EGG": 0.0, "FERTILIZER": 0.0,
    }
    units_sold = {k: 0.0 for k in revenue}
    market_prices_seen = {"WOOL": [], "MILK": [], "FERTILIZER": [], "WHEAT": []}

    def tracking_agent(obs, config=None):
        nonlocal peak_herd, day_peak_herd_reached
        nonlocal prev_shed_cows, prev_shed_sheep, prev_inv_cows, prev_inv_sheep, prev_tile_cows, prev_tile_sheep

        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        step = obs.get("step", 0)
        p_id = obs.get("player", 0)
        farm_data = obs.get("farms", [])[p_id]
        priv_data = obs.get("private", {})
        shed = priv_data.get("shed", {})
        inventories = priv_data.get("inventories", [])

        ctx = parse_observation(obs)
        farm = ctx["farm"]

        curr_shed_cows = int(shed.get("COW", 0))
        curr_shed_sheep = int(shed.get("SHEEP", 0))
        curr_inv_cows = sum(int(inv.get("COW", 0)) for inv in inventories)
        curr_inv_sheep = sum(int(inv.get("SHEEP", 0)) for inv in inventories)
        curr_tile_cows = {t.pos for t in farm.iter_tiles() if t.is_animal and t.animal == "COW"}
        curr_tile_sheep = {t.pos for t in farm.iter_tiles() if t.is_animal and t.animal == "SHEEP"}

        # 1. Detect arrivals in shed for late units
        if curr_shed_cows > prev_shed_cows:
            arrivals = curr_shed_cows - prev_shed_cows
            for _ in range(arrivals):
                for u in late_cow_units:
                    if not u["arrived"]:
                        u["arrived"] = True
                        u["arrival_day"] = day
                        u["arrival_hour"] = hour
                        break
        if curr_shed_sheep > prev_shed_sheep:
            arrivals = curr_shed_sheep - prev_shed_sheep
            for _ in range(arrivals):
                for u in late_sheep_units:
                    if not u["arrived"]:
                        u["arrived"] = True
                        u["arrival_day"] = day
                        u["arrival_hour"] = hour
                        break

        # 2. Detect worker pickups
        if curr_inv_cows > prev_inv_cows:
            pickups = curr_inv_cows - prev_inv_cows
            for _ in range(pickups):
                for u in late_cow_units:
                    if u["arrived"] and not u["picked_up"] and not u["placed"]:
                        u["picked_up"] = True
                        u["pickup_day"] = day
                        u["pickup_hour"] = hour
                        break
        if curr_inv_sheep > prev_inv_sheep:
            pickups = curr_inv_sheep - prev_inv_sheep
            for _ in range(pickups):
                for u in late_sheep_units:
                    if u["arrived"] and not u["picked_up"] and not u["placed"]:
                        u["picked_up"] = True
                        u["pickup_day"] = day
                        u["pickup_hour"] = hour
                        break

        # 3. Detect placement onto pastures
        new_cows = curr_tile_cows - prev_tile_cows
        for pos in new_cows:
            for u in late_cow_units:
                if not u["placed"]:
                    u["placed"] = True
                    u["placement_day"] = day
                    u["placement_hour"] = hour
                    u["placement_tile"] = list(pos)
                    break

        new_sheep = curr_tile_sheep - prev_tile_sheep
        for pos in new_sheep:
            for u in late_sheep_units:
                if not u["placed"]:
                    u["placed"] = True
                    u["placement_day"] = day
                    u["placement_hour"] = hour
                    u["placement_tile"] = list(pos)
                    break

        # Update previous counts
        prev_shed_cows = curr_shed_cows
        prev_shed_sheep = curr_shed_sheep
        prev_inv_cows = curr_inv_cows
        prev_inv_sheep = curr_inv_sheep
        prev_tile_cows = set(curr_tile_cows)
        prev_tile_sheep = set(curr_tile_sheep)

        # Track total herd
        curr_herd = sum(1 for t in farm.iter_tiles() if t.is_animal)
        if curr_herd > peak_herd:
            peak_herd = curr_herd
            day_peak_herd_reached = day

        # Check shed overflow
        total_shed = sum(shed.values()) if shed else 0
        if total_shed > 100:
            safety_metrics["shed_overflows"] += 1

        # Check feed failure / starvation at hour 0
        if hour == 0 and day > 0:
            for t in farm.iter_tiles():
                if t.is_animal:
                    if t.consecutive_unfed > 0:
                        if day < 28:
                            safety_metrics["feed_failures_pre28"] = safety_metrics.get("feed_failures_pre28", 0) + 1
                        else:
                            safety_metrics["feed_failures_endgame"] = safety_metrics.get("feed_failures_endgame", 0) + 1
                    if t.consecutive_unfed >= 2:
                        safety_metrics["animal_escapes"] = safety_metrics.get("animal_escapes", 0) + 1

        # Snapshot herd at hour 0
        if hour == 0 and day in (0, 5, 10, 11, 12, 13, 14, 15, 20, 28):
            c_cnt = len(curr_tile_cows)
            s_cnt = len(curr_tile_sheep)
            g_cnt = sum(1 for t in farm.iter_tiles() if t.is_animal and t.animal == "GOOSE")
            herd_trajectory[day] = {
                "day": day,
                "cows": c_cnt,
                "sheep": s_cnt,
                "geese": g_cnt,
                "total_herd": c_cnt + s_cnt + g_cnt,
                "money": float(farm.money),
            }

        # Market prices
        if "market" in obs:
            for item in ("WOOL", "MILK", "FERTILIZER", "WHEAT"):
                if item in obs["market"]:
                    p_info = obs["market"][item]
                    if isinstance(p_info, dict) and "price" in p_info:
                        market_prices_seen[item].append(float(p_info["price"]))

        # Pre-action calculation of guaranteed empty housing
        phys_empty_pastures = sum(
            1 for t in farm.iter_tiles()
            if t.kind == "PASTURE" and not t.is_animal and (
                not hasattr(farm, "unlocked") or not hasattr(farm, "quadrant_of") or farm.quadrant_of(t.pos) in farm.unlocked
            )
        )
        pending_large = (curr_shed_cows + curr_shed_sheep + curr_inv_cows + curr_inv_sheep)
        guaranteed_empty_at_step = max(0, phys_empty_pastures - pending_large)

        # Execute agent
        try:
            act = agent_module.agent(obs, config)
        except Exception as e:
            traceback.print_exc()
            act = {}

        # Inspect market orders emitted
        if isinstance(act, dict) and "market" in act:
            for ord_idx, o in enumerate(act["market"]):
                if isinstance(o, (list, tuple)) and len(o) >= 2:
                    action_type = o[0]
                    target_item = o[1]
                    qty = int(o[2]) if len(o) > 2 else 1

                    if action_type == "BUY_ANIMAL" and day >= 12:
                        late_orders_emitted.append({
                            "day": day, "hour": hour, "animal": target_item, "qty": qty,
                            "guaranteed_empty": guaranteed_empty_at_step,
                        })
                        for u_i in range(qty):
                            u_rec = {
                                "order_id": f"{match_id}_d{day}h{hour}_{target_item}_{u_i}",
                                "animal": target_item,
                                "purchase_day": day,
                                "purchase_hour": hour,
                                "guaranteed_empty_at_buy": guaranteed_empty_at_step,
                                "arrived": False,
                                "picked_up": False,
                                "placed": False,
                                "stranded": False,
                            }
                            if target_item == "COW":
                                late_cow_units.append(u_rec)
                            elif target_item == "SHEEP":
                                late_sheep_units.append(u_rec)

                    elif action_type == "BUY_ANIMAL":
                        cost = qty * ANIMALS.get(target_item, {}).get("cost", 400)
                        if target_item in spend:
                            spend[target_item] += cost
                    elif action_type == "BUY_PRODUCT" and target_item == "WHEAT":
                        spend["WHEAT"] += qty * 25.0
                    elif action_type == "BUY_SEED":
                        cost = qty * CROPS.get(target_item, {}).get("seed", 10)
                        spend["SEEDS"] += cost
                    elif action_type == "SELL_PRODUCT":
                        units_sold[target_item] = units_sold.get(target_item, 0) + qty

        return act

    # Run game in environment
    try:
        env = make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720})
        runner = env.run([tracking_agent, opp_name])
        last_step = runner[-1]
        p0_state = last_step[0]
        p1_state = last_step[1]

        final_money_p0 = float(p0_state.get("reward", 0.0) or 0.0)
        final_money_p1 = float(p1_state.get("reward", 0.0) or 0.0)

        final_obs = p0_state.get("observation", {})
        farms = final_obs.get("farms", [])
        if len(farms) > 0 and final_money_p0 == 0.0:
            final_money_p0 = float(farms[0].get("money", 0.0))
        if len(farms) > 1 and final_money_p1 == 0.0:
            final_money_p1 = float(farms[1].get("money", 0.0))

        priv_final = final_obs.get("private", {})
        final_shed = dict(priv_final.get("shed", {}))
        final_inv = {}
        for inv in priv_final.get("inventories", []):
            for itm, q in inv.items():
                final_inv[itm] = final_inv.get(itm, 0) + q

    except Exception as e:
        print(f"Match error for arm {arm}, seed {seed}, opp {opp_name}: {e}")
        traceback.print_exc()
        final_money_p0 = 0.0
        final_money_p1 = 0.0
        final_shed = {}
        final_inv = {}

    win = bool(final_money_p0 > final_money_p1)
    tie = bool(final_money_p0 == final_money_p1)

    # Classify late units terminal outcomes
    for u in late_cow_units + late_sheep_units:
        if not u["placed"]:
            u["stranded"] = True

    total_late_cows_bought = len(late_cow_units)
    total_late_cows_placed = sum(1 for u in late_cow_units if u["placed"])
    total_late_cows_stranded = sum(1 for u in late_cow_units if u["stranded"])
    late_cows_bought_without_housing = sum(1 for u in late_cow_units if u["guaranteed_empty_at_buy"] <= 0)

    total_late_sheep_bought = len(late_sheep_units)
    total_late_sheep_placed = sum(1 for u in late_sheep_units if u["placed"])
    total_late_sheep_stranded = sum(1 for u in late_sheep_units if u["stranded"])

    avg_prices = {
        k: float(np.mean(v)) if v else 0.0
        for k, v in market_prices_seen.items()
    }

    return {
        "arm": arm,
        "cutoff_day": cutoff_day,
        "selective_gate": selective_gate,
        "threshold": threshold,
        "seed": seed,
        "opponent": opp_name,
        "final_money": final_money_p0,
        "opponent_money": final_money_p1,
        "win": win,
        "tie": tie,
        "peak_herd": peak_herd,
        "day_peak_herd_reached": day_peak_herd_reached,
        "herd_trajectory": herd_trajectory,
        "late_cows_bought": total_late_cows_bought,
        "late_cows_placed": total_late_cows_placed,
        "late_cows_stranded": total_late_cows_stranded,
        "late_cows_bought_without_housing": late_cows_bought_without_housing,
        "late_sheep_bought": total_late_sheep_bought,
        "late_sheep_placed": total_late_sheep_placed,
        "late_sheep_stranded": total_late_sheep_stranded,
        "late_orders_emitted": late_orders_emitted,
        "late_cow_units": late_cow_units,
        "safety_metrics": safety_metrics,
        "avg_prices": avg_prices,
        "final_shed": final_shed,
        "final_inv": final_inv,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seeds", type=int, default=25)
    parser.add_argument("--start-seed", type=int, default=101)
    parser.add_argument("--threshold", type=float, default=500.0)
    args = parser.parse_args()

    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    opponents = ["random", "starter"]

    # Build 50 pairs = 100 matches total
    payloads = []
    for s in seeds:
        for opp in opponents:
            # Arm A: Day 12 Hard Cutoff (Control)
            payloads.append({
                "arm": "A",
                "cutoff_day": 12,
                "selective_gate": False,
                "threshold": 0.0,
                "seed": s,
                "opponent": opp,
            })
            # Arm B: Selective Market-Aware Gate @ threshold with Housing Safety (Experimental)
            payloads.append({
                "arm": "B",
                "cutoff_day": 12,
                "selective_gate": True,
                "threshold": args.threshold,
                "seed": s,
                "opponent": opp,
            })

    print(f"================================================================================")
    print(f"Running Strict Single-Variable A/B Experiment: Housing-Safe Selective Gate")
    print(f"Arm A (Control): Day 12 Hard Cutoff")
    print(f"Arm B (Experimental): Selective Gate @ ${args.threshold} with Housing-Safe Restriction")
    print(f"Total Matches: {len(payloads)} ({len(payloads)//2} paired scenarios)")
    print(f"Workers: {args.workers}, Seeds: {len(seeds)} ({seeds[0]}..{seeds[-1]})")
    print(f"================================================================================")

    t0 = time.time()
    results = []
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_run_single_match, p): p for p in payloads}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == len(payloads):
                elapsed = time.time() - t0
                rate = completed / elapsed
                print(f"[{completed:3d}/{len(payloads)}] matches done ({rate:.1f} m/s, elapsed: {elapsed:.1f}s)")

    out_raw = os.path.join(_REPO_ROOT, "artifacts", "housing_safe_ab_results.json")
    with open(out_raw, "w") as f:
        json.dump(results, f, indent=2)

    # Analyze and compile summary
    arm_a = [r for r in results if r["arm"] == "A"]
    arm_b = [r for r in results if r["arm"] == "B"]

    scores_a = [r["final_money"] for r in arm_a]
    scores_b = [r["final_money"] for r in arm_b]

    # Map by paired scenario (seed, opponent)
    a_by_key = {(r["seed"], r["opponent"]): r for r in arm_a}
    b_by_key = {(r["seed"], r["opponent"]): r for r in arm_b}

    paired_deltas = []
    paired_wins = 0
    paired_losses = 0
    paired_ties = 0

    for key, r_a in a_by_key.items():
        if key in b_by_key:
            r_b = b_by_key[key]
            d = r_b["final_money"] - r_a["final_money"]
            paired_deltas.append(d)
            if d > 0:
                paired_wins += 1
            elif d < 0:
                paired_losses += 1
            else:
                paired_ties += 1

    summary = {
        "total_pairs": len(paired_deltas),
        "total_matches": len(results),
        "scores_arm_a": {
            "mean": float(np.mean(scores_a)),
            "median": float(np.median(scores_a)),
            "std": float(np.std(scores_a)),
            "min": float(np.min(scores_a)),
            "max": float(np.max(scores_a)),
            "p10": float(np.percentile(scores_a, 10)),
            "p25": float(np.percentile(scores_a, 25)),
            "p75": float(np.percentile(scores_a, 75)),
            "p90": float(np.percentile(scores_a, 90)),
        },
        "scores_arm_b": {
            "mean": float(np.mean(scores_b)),
            "median": float(np.median(scores_b)),
            "std": float(np.std(scores_b)),
            "min": float(np.min(scores_b)),
            "max": float(np.max(scores_b)),
            "p10": float(np.percentile(scores_b, 10)),
            "p25": float(np.percentile(scores_b, 25)),
            "p75": float(np.percentile(scores_b, 75)),
            "p90": float(np.percentile(scores_b, 90)),
        },
        "paired_delta": {
            "mean": float(np.mean(paired_deltas)),
            "median": float(np.median(paired_deltas)),
            "std": float(np.std(paired_deltas)),
            "min": float(np.min(paired_deltas)),
            "max": float(np.max(paired_deltas)),
            "p10": float(np.percentile(paired_deltas, 10)),
            "p25": float(np.percentile(paired_deltas, 25)),
            "p75": float(np.percentile(paired_deltas, 75)),
            "p90": float(np.percentile(paired_deltas, 90)),
            "wins": paired_wins,
            "losses": paired_losses,
            "ties": paired_ties,
        },
        "livestock_arm_a": {
            "mean_peak_herd": float(np.mean([r["peak_herd"] for r in arm_a])),
            "median_peak_herd": float(np.median([r["peak_herd"] for r in arm_a])),
            "late_cows_bought": sum(r["late_cows_bought"] for r in arm_a),
            "late_cows_placed": sum(r["late_cows_placed"] for r in arm_a),
            "late_cows_stranded": sum(r["late_cows_stranded"] for r in arm_a),
        },
        "livestock_arm_b": {
            "mean_peak_herd": float(np.mean([r["peak_herd"] for r in arm_b])),
            "median_peak_herd": float(np.median([r["peak_herd"] for r in arm_b])),
            "late_cows_bought": sum(r["late_cows_bought"] for r in arm_b),
            "late_cows_placed": sum(r["late_cows_placed"] for r in arm_b),
            "late_cows_stranded": sum(r["late_cows_stranded"] for r in arm_b),
            "late_cows_bought_without_housing": sum(r["late_cows_bought_without_housing"] for r in arm_b),
            "late_sheep_bought": sum(r["late_sheep_bought"] for r in arm_b),
            "late_sheep_placed": sum(r["late_sheep_placed"] for r in arm_b),
            "late_sheep_stranded": sum(r["late_sheep_stranded"] for r in arm_b),
        },
        "safety_arm_a": {
            "feed_failures_pre28": sum(r["safety_metrics"].get("feed_failures_pre28", 0) for r in arm_a),
            "feed_failures_endgame": sum(r["safety_metrics"].get("feed_failures_endgame", 0) for r in arm_a),
            "animal_escapes": sum(r["safety_metrics"].get("animal_escapes", 0) for r in arm_a),
            "shed_overflows": sum(r["safety_metrics"].get("shed_overflows", 0) for r in arm_a),
        },
        "safety_arm_b": {
            "feed_failures_pre28": sum(r["safety_metrics"].get("feed_failures_pre28", 0) for r in arm_b),
            "feed_failures_endgame": sum(r["safety_metrics"].get("feed_failures_endgame", 0) for r in arm_b),
            "animal_escapes": sum(r["safety_metrics"].get("animal_escapes", 0) for r in arm_b),
            "shed_overflows": sum(r["safety_metrics"].get("shed_overflows", 0) for r in arm_b),
        },
    }

    out_summary = os.path.join(_REPO_ROOT, "artifacts", "housing_safe_ab_summary.json")
    with open(out_summary, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n==================== EXPERIMENT SUMMARY ====================")
    print(f"Arm A (Control):   Mean ${summary['scores_arm_a']['mean']:,.2f} | Median ${summary['scores_arm_a']['median']:,.2f} | P10 ${summary['scores_arm_a']['p10']:,.2f}")
    print(f"Arm B (Selective): Mean ${summary['scores_arm_b']['mean']:,.2f} | Median ${summary['scores_arm_b']['median']:,.2f} | P10 ${summary['scores_arm_b']['p10']:,.2f}")
    print(f"Paired Delta:      Mean ${summary['paired_delta']['mean']:+,.2f} | Median ${summary['paired_delta']['median']:+,.2f}")
    print(f"Paired Record:     {paired_wins} Wins / {paired_losses} Losses / {paired_ties} Ties")
    print(f"Arm A Peak Herd:   {summary['livestock_arm_a']['mean_peak_herd']:.2f}")
    print(f"Arm B Peak Herd:   {summary['livestock_arm_b']['mean_peak_herd']:.2f}")
    print(f"Arm B Late Cows:   {summary['livestock_arm_b']['late_cows_bought']} bought, {summary['livestock_arm_b']['late_cows_placed']} placed, {summary['livestock_arm_b']['late_cows_stranded']} stranded")
    print(f"Arm B Without Hsg: {summary['livestock_arm_b']['late_cows_bought_without_housing']}")
    print(f"Feed Fail (pre-28): Arm A: {summary['safety_arm_a']['feed_failures_pre28']} | Arm B: {summary['safety_arm_b']['feed_failures_pre28']}")
    print(f"Feed Fail (end):   Arm A: {summary['safety_arm_a']['feed_failures_endgame']} | Arm B: {summary['safety_arm_b']['feed_failures_endgame']}")
    print(f"Animal Escapes:    Arm A: {summary['safety_arm_a']['animal_escapes']} | Arm B: {summary['safety_arm_b']['animal_escapes']}")
    print(f"Shed Overflows:    Arm A: {summary['safety_arm_a']['shed_overflows']} | Arm B: {summary['safety_arm_b']['shed_overflows']}")
    print(f"============================================================")


if __name__ == "__main__":
    main()
