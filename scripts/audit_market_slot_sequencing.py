"""Phase M0-H: Authoritative Oracle Market Slot Sequencing Audit.

Audits whether reordering our already-selected SELL orders within their safe slots
against the opponent's actual market queue creates meaningful economic regret.

Runs baseline matches on seeds 96501-96510 x 5 opponents x 2 seats (100 matches).
For each turn with >= 2 SELL orders:
- Evaluates actual ordering revenue.
- Evaluates all valid permutations of our SELL orders against opponent's exact queue.
- Computes actual revenue, oracle best revenue, oracle worst revenue, oracle regret.
- Tracks same-product slot collision dynamics and product-level price damage.

Outputs under simulations/results/phase_m0_h_oracle_audit/:
- manifest.json
- source_hashes.json
- slot_collision_frequency.json
- oracle_slot_regret.json
- oracle_by_product.json
- oracle_by_opponent.json
- oracle_by_day.json
- representative_replays.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_h_oracle_audit")
os.makedirs(OUT_DIR, exist_ok=True)

AUDIT_SEEDS = list(range(96501, 96511))  # 96501–96510 (10 seeds)
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]


def compute_file_sha256(path: str) -> str:
    if not os.path.exists(path):
        return "missing"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_audit_match(seed: int, opp_name: str, seat: int) -> Dict[str, Any]:
    clean_sys_path = [p for p in sys.path if "agent" not in p and ".worktrees" not in p]
    sys.path = [_REPO_ROOT, _AGENT_DIR] + [
        os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")
    ] + clean_sys_path

    import kaggle_environments as ke
    import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
    from agent.main import agent, reset_agent_state
    import config
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    # Baseline Invariants:
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    config.set_midnight_storage_dump_mode("OFF")
    config.set_same_turn_deposit_sell_mode("BASELINE")
    config.set_animal_service_economics_mode("OFF")

    reset_agent_state()
    reset_sw_tranche_controller()

    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    opp_agent = get_agent(opp_name)

    cfg = env.configuration
    turns_per_day = max(1, int(kengine.get(cfg, "turnsPerDay", 24)))
    board_size = int(kengine.get(cfg, "boardSize", 10))
    shed_capacity = int(kengine.get(cfg, "shedCapacity", 100))

    match_turns_evaluated = 0
    match_total_regret = 0.0
    turn_regrets: List[Dict[str, Any]] = []
    collisions_data: List[Dict[str, Any]] = []

    step_num = 0
    while not env.done:
        obs_pre = env.state[seat].observation
        opp_obs_pre = env.state[1 - seat].observation
        day = step_num // turns_per_day
        hour = step_num % turns_per_day

        act = agent(obs_pre, env.configuration)
        try:
            opp_act = opp_agent(opp_obs_pre, env.configuration)
        except TypeError:
            opp_act = opp_agent(opp_obs_pre)

        our_market = list(act.get("market", []))
        opp_market = list(opp_act.get("market", []))

        # Check for SELL orders in our market queue
        sell_indices = [idx for idx, o in enumerate(our_market) if len(o) >= 3 and o[0] == "SELL"]
        sell_orders = [our_market[idx] for idx in sell_indices]

        # Check collisions for all our sell orders
        for s_idx, s_order in zip(sell_indices, sell_orders):
            prod = s_order[1]
            qty = s_order[2]
            opp_sells_of_prod = [
                (o_idx, o) for o_idx, o in enumerate(opp_market)
                if len(o) >= 3 and o[0] == "SELL" and o[1] == prod
            ]
            if not opp_sells_of_prod:
                rel = "NONE"
            else:
                # categorize relative to our slot
                min_opp_slot = min(x[0] for x in opp_sells_of_prod)
                if any(x[0] < s_idx for x in opp_sells_of_prod):
                    rel = "EARLIER"
                elif any(x[0] == s_idx for x in opp_sells_of_prod):
                    rel = "SAME"
                else:
                    rel = "LATER"

            collisions_data.append({
                "product": prod,
                "our_slot": s_idx,
                "quantity": qty,
                "opp_slots": [x[0] for x in opp_sells_of_prod],
                "relation": rel,
                "day": day,
                "hour": hour,
            })

        # Evaluate Oracle Counterfactual Replay if >= 2 SELL orders
        if len(sell_indices) >= 2:
            match_turns_evaluated += 1

            # Check if opponent has any overlapping market item (SELL or BUY_PRODUCT)
            our_sell_items = {o[1] for o in sell_orders}
            opp_market_items = {
                o[1] for o in opp_market
                if len(o) >= 2 and o[0] in ("SELL", "BUY_PRODUCT")
            }
            has_potential_collision = bool(our_sell_items & opp_market_items)

            if not has_potential_collision:
                # By cross-product independence (verified in Test A5), permutations of uncontested
                # products produce mathematically identical revenues. Regret is guaranteed to be 0.
                pass
            else:
                # Prepare pre-market state by executing unit actions
                # (Matches engine interpreter exact sequence)
                actions = [act, opp_act] if seat == 0 else [opp_act, act]
                s_copy = copy.deepcopy(env.state)
                s_copy[0].action = actions[0]
                s_copy[1].action = actions[1]
                obs0 = s_copy[0].observation

                for i, s in enumerate(s_copy):
                    u_act = s.action if isinstance(s.action, dict) else {}
                    farmer_act = u_act.get("farmer", ["PASS"]) if isinstance(u_act, dict) else ["PASS"]
                    hands_acts = u_act.get("hands", []) if isinstance(u_act, dict) else []
                    u_actions = [farmer_act, *hands_acts]
                    p_demand: Dict[str, int] = {}
                    for a in u_actions:
                        if isinstance(a, list) and len(a) >= 2 and a[0] == "PLANT":
                            p_demand[a[1]] = p_demand.get(a[1], 0) + 1
                    s_seeds = s.observation.private.get("seeds", {}) if hasattr(s.observation.private, "get") else {}
                    blocked = {crop for crop, n in p_demand.items() if n > s_seeds.get(crop, 0)}

                    def _allowed(a):
                        if isinstance(a, list) and len(a) >= 2 and a[0] == "PLANT" and a[1] in blocked:
                            return ["PASS"]
                        return a

                    kengine._apply_unit_action(obs0.farms[i], s.observation.private, 0, _allowed(farmer_act),
                                               board_size, day, turns_per_day, shed_capacity)
                    for h_idx, hand_a in enumerate(hands_acts):
                        kengine._apply_unit_action(obs0.farms[i], s.observation.private, h_idx + 1,
                                                   _allowed(hand_a), board_size, day, turns_per_day, shed_capacity)

                # Measure actual baseline revenue
                test_actual = copy.deepcopy(s_copy)
                m_pre = float(test_actual[0].observation.farms[seat]["money"])
                kengine._process_market(test_actual, env)
                actual_rev = float(test_actual[0].observation.farms[seat]["money"]) - m_pre

                # Distinct permutations of SELL orders
                sell_tuples = [tuple(o) for o in sell_orders]
                unique_perms = list(set(itertools.permutations(sell_tuples)))

                best_rev = actual_rev
                worst_rev = actual_rev
                best_perm = sell_orders
                worst_perm = sell_orders

                for perm in unique_perms:
                    cand_market = list(our_market)
                    for pos, o_tup in zip(sell_indices, perm):
                        cand_market[pos] = list(o_tup)

                    test_state = copy.deepcopy(s_copy)
                    if seat == 0:
                        test_state[0].action = {"market": cand_market}
                        test_state[1].action = {"market": opp_market}
                    else:
                        test_state[0].action = {"market": opp_market}
                        test_state[1].action = {"market": cand_market}

                    kengine._process_market(test_state, env)
                    perm_rev = float(test_state[0].observation.farms[seat]["money"]) - m_pre

                    if perm_rev > best_rev:
                        best_rev = perm_rev
                        best_perm = [list(o) for o in perm]
                    if perm_rev < worst_rev:
                        worst_rev = perm_rev
                        worst_perm = [list(o) for o in perm]

                regret = max(0.0, best_rev - actual_rev)
                if regret > 0:
                    match_total_regret += regret
                    affected_prods = list({o[1] for o in sell_orders if o[1] in opp_market_items})
                    turn_regrets.append({
                        "day": day,
                        "hour": hour,
                        "actual_revenue": actual_rev,
                        "best_revenue": best_rev,
                        "worst_revenue": worst_rev,
                        "regret": regret,
                        "our_actual_queue": our_market,
                        "our_best_queue": [
                            best_perm[sell_indices.index(i)] if i in sell_indices else our_market[i]
                            for i in range(len(our_market))
                        ],
                        "opp_queue": opp_market,
                        "affected_products": affected_prods,
                    })



        # Advance real environment
        actions = [act, opp_act] if seat == 0 else [opp_act, act]
        env.step(actions)
        step_num += 1

    final_reward = float(env.steps[-1][seat].reward or 0.0)
    opp_reward = float(env.steps[-1][1 - seat].reward or 0.0)

    return {
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "final_cash": final_reward,
        "opp_cash": opp_reward,
        "turns_evaluated": match_turns_evaluated,
        "total_regret": match_total_regret,
        "turn_regrets": turn_regrets,
        "collisions_data": collisions_data,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-H Authoritative Oracle Audit")
    parser.add_argument("--workers", type=int, default=10, help="Number of worker processes")
    parser.add_argument("--smoke", action="store_true", help="Run quick 2-match smoke test")
    args = parser.parse_args()

    seeds = [96501, 96502] if args.smoke else AUDIT_SEEDS
    opponents = ["pass", "full_production_agent"] if args.smoke else BENCHMARK_OPPONENTS
    seats = [0] if args.smoke else SEATS

    tasks = [(s, opp, seat) for s in seeds for opp in opponents for seat in seats]
    total_matches = len(tasks)

    print(f"=== Phase M0-H Authoritative Oracle Market Slot Sequencing Audit ===")
    print(f"Seeds: {seeds}")
    print(f"Opponents: {opponents}")
    print(f"Seats: {seats}")
    print(f"Total Matches to Run: {total_matches}")
    print(f"Workers: {args.workers}")

    start_time = time.time()
    results: List[Dict[str, Any]] = []
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(run_audit_match, s, opp, seat): (s, opp, seat) for s, opp, seat in tasks}
        for fut in as_completed(future_map):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total_matches:
                print(f"  [{completed}/{total_matches}] matches complete ({time.time() - start_time:.1f}s) - Last match regret: ${res['total_regret']:.2f}")

    elapsed = time.time() - start_time
    print(f"\nAll {total_matches} matches completed in {elapsed:.1f}s.")

    # 1. Source hashes
    git_sha = "unknown"
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT).decode("utf-8").strip()
    except Exception:
        pass

    import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
    engine_path = kengine.__file__

    source_hashes = {
        "git_commit": git_sha,
        "kengine": compute_file_sha256(engine_path),
        "agent_main": compute_file_sha256(os.path.join(_AGENT_DIR, "main.py")),
        "central_planner": compute_file_sha256(os.path.join(_AGENT_DIR, "strategy", "central_planner.py")),
        "market_brain": compute_file_sha256(os.path.join(_AGENT_DIR, "market", "market_brain.py")),
        "order_builder": compute_file_sha256(os.path.join(_AGENT_DIR, "market", "order_builder.py")),
        "verify_market_slot_lockstep": compute_file_sha256(os.path.join(_REPO_ROOT, "scripts", "verify_market_slot_lockstep.py")),
        "audit_market_slot_sequencing": compute_file_sha256(os.path.join(_REPO_ROOT, "scripts", "audit_market_slot_sequencing.py")),
    }
    with open(os.path.join(OUT_DIR, "source_hashes.json"), "w", encoding="utf-8") as f:
        json.dump(source_hashes, f, indent=2)

    # 2. Aggregations
    match_regrets = [r["total_regret"] for r in results]
    mean_regret = float(np.mean(match_regrets)) if match_regrets else 0.0
    median_regret = float(np.median(match_regrets)) if match_regrets else 0.0
    p75_regret = float(np.percentile(match_regrets, 75)) if match_regrets else 0.0
    p90_regret = float(np.percentile(match_regrets, 90)) if match_regrets else 0.0
    p95_regret = float(np.percentile(match_regrets, 95)) if match_regrets else 0.0
    max_regret = float(np.max(match_regrets)) if match_regrets else 0.0

    all_turn_regrets = []
    for r in results:
        for t in r["turn_regrets"]:
            item = dict(t)
            item["seed"] = r["seed"]
            item["opponent"] = r["opponent"]
            item["seat"] = r["seat"]
            all_turn_regrets.append(item)

    turns_gt_0 = len([t for t in all_turn_regrets if t["regret"] > 0])
    turns_gt_25 = len([t for t in all_turn_regrets if t["regret"] > 25])
    turns_gt_50 = len([t for t in all_turn_regrets if t["regret"] > 50])
    turns_gt_100 = len([t for t in all_turn_regrets if t["regret"] > 100])
    turns_gt_250 = len([t for t in all_turn_regrets if t["regret"] > 250])
    turns_gt_500 = len([t for t in all_turn_regrets if t["regret"] > 500])

    tot_turns_evaluated = sum(r["turns_evaluated"] for r in results)
    matches_with_regret = len([r for r in results if r["total_regret"] > 0])

    oracle_slot_regret = {
        "mean_regret_per_match": round(mean_regret, 2),
        "median_regret_per_match": round(median_regret, 2),
        "p50_regret_per_match": round(median_regret, 2),
        "p75_regret_per_match": round(p75_regret, 2),
        "p90_regret_per_match": round(p90_regret, 2),
        "p95_regret_per_match": round(p95_regret, 2),
        "max_regret_per_match": round(max_regret, 2),
        "matches_with_regret": matches_with_regret,
        "total_matches": total_matches,
        "total_turns_with_2plus_sells": tot_turns_evaluated,
        "turns_with_regret_gt_0": turns_gt_0,
        "turns_with_regret_gt_25": turns_gt_25,
        "turns_with_regret_gt_50": turns_gt_50,
        "turns_with_regret_gt_100": turns_gt_100,
        "turns_with_regret_gt_250": turns_gt_250,
        "turns_with_regret_gt_500": turns_gt_500,
        "total_regret_dollars": round(sum(match_regrets), 2),
    }
    with open(os.path.join(OUT_DIR, "oracle_slot_regret.json"), "w", encoding="utf-8") as f:
        json.dump(oracle_slot_regret, f, indent=2)

    # 3. Collision frequency analysis
    all_collisions = [c for r in results for c in r["collisions_data"]]
    tot_sells = len(all_collisions)
    tot_collided = len([c for c in all_collisions if c["relation"] != "NONE"])
    collision_freq_by_prod: Dict[str, Dict[str, Any]] = {}
    for p in PRODUCTS:
        p_items = [c for c in all_collisions if c["product"] == p]
        p_tot = len(p_items)
        p_earlier = len([c for c in p_items if c["relation"] == "EARLIER"])
        p_same = len([c for c in p_items if c["relation"] == "SAME"])
        p_later = len([c for c in p_items if c["relation"] == "LATER"])
        p_none = len([c for c in p_items if c["relation"] == "NONE"])
        collision_freq_by_prod[p] = {
            "total_sells": p_tot,
            "collisions_total": p_tot - p_none,
            "collision_rate": round((p_tot - p_none) / p_tot, 4) if p_tot > 0 else 0.0,
            "earlier_than_us": p_earlier,
            "same_slot": p_same,
            "later_than_us": p_later,
            "uncontested": p_none,
        }

    slot_collision_frequency = {
        "total_sell_orders": tot_sells,
        "total_collided_sells": tot_collided,
        "overall_collision_rate": round(tot_collided / tot_sells, 4) if tot_sells > 0 else 0.0,
        "by_product": collision_freq_by_prod,
    }
    with open(os.path.join(OUT_DIR, "slot_collision_frequency.json"), "w", encoding="utf-8") as f:
        json.dump(slot_collision_frequency, f, indent=2)

    # 4. Oracle regret by product
    by_product: Dict[str, Dict[str, Any]] = {p: {"regret_dollars": 0.0, "turns_count": 0} for p in PRODUCTS}
    for t in all_turn_regrets:
        prods = t["affected_products"]
        # Share regret equally if multiple products in turn
        share = t["regret"] / max(1, len(prods))
        for p in prods:
            if p in by_product:
                by_product[p]["regret_dollars"] += share
                by_product[p]["turns_count"] += 1

    oracle_by_product = {
        p: {
            "regret_dollars": round(by_product[p]["regret_dollars"], 2),
            "turns_count": by_product[p]["turns_count"],
            "mean_loss_per_turn": round(by_product[p]["regret_dollars"] / max(1, by_product[p]["turns_count"]), 2)
        }
        for p in PRODUCTS
    }
    with open(os.path.join(OUT_DIR, "oracle_by_product.json"), "w", encoding="utf-8") as f:
        json.dump(oracle_by_product, f, indent=2)

    # 5. Oracle regret by opponent
    oracle_by_opponent: Dict[str, Any] = {}
    for opp in opponents:
        opp_results = [r for r in results if r["opponent"] == opp]
        opp_regs = [r["total_regret"] for r in opp_results]
        opp_our_cash = [r["final_cash"] for r in opp_results]
        opp_opp_cash = [r["opp_cash"] for r in opp_results]
        oracle_by_opponent[opp] = {
            "matches": len(opp_results),
            "mean_our_cash": round(float(np.mean(opp_our_cash)), 2) if opp_our_cash else 0.0,
            "mean_opp_cash": round(float(np.mean(opp_opp_cash)), 2) if opp_opp_cash else 0.0,
            "mean_regret": round(float(np.mean(opp_regs)), 2) if opp_regs else 0.0,
            "median_regret": round(float(np.median(opp_regs)), 2) if opp_regs else 0.0,
            "p90_regret": round(float(np.percentile(opp_regs, 90)), 2) if opp_regs else 0.0,
            "max_regret": round(float(np.max(opp_regs)), 2) if opp_regs else 0.0,
            "matches_with_regret": len([x for x in opp_regs if x > 0]),
        }
    with open(os.path.join(OUT_DIR, "oracle_by_opponent.json"), "w", encoding="utf-8") as f:
        json.dump(oracle_by_opponent, f, indent=2)

    # 6. Oracle regret by day and hour
    day_regrets: Dict[int, float] = {d: 0.0 for d in range(30)}
    day_turns: Dict[int, int] = {d: 0 for d in range(30)}
    hour_regrets: Dict[int, float] = {h: 0.0 for h in range(24)}
    hour_turns: Dict[int, int] = {h: 0 for h in range(24)}

    for t in all_turn_regrets:
        d = t["day"]
        h = t["hour"]
        reg = t["regret"]
        day_regrets[d] += reg
        day_turns[d] += 1
        hour_regrets[h] += reg
        hour_turns[h] += 1

    oracle_by_day = {
        "by_day": {str(d): {"regret": round(day_regrets[d], 2), "turns": day_turns[d]} for d in range(30)},
        "by_hour": {str(h): {"regret": round(hour_regrets[h], 2), "turns": hour_turns[h]} for h in range(24)},
    }
    with open(os.path.join(OUT_DIR, "oracle_by_day.json"), "w", encoding="utf-8") as f:
        json.dump(oracle_by_day, f, indent=2)

    # 7. Representative replays (top 15 highest regret turns)
    sorted_turns = sorted(all_turn_regrets, key=lambda x: x["regret"], reverse=True)
    top_replays = sorted_turns[:15]
    with open(os.path.join(OUT_DIR, "representative_replays.json"), "w", encoding="utf-8") as f:
        json.dump(top_replays, f, indent=2)

    # 8. Manifest & Decision Gate A check
    gate_a_passed = (mean_regret >= 500.0)
    gate_a_judgment = (250.0 <= mean_regret < 500.0)
    manifest = {
        "phase": "M0-H",
        "description": "Authoritative Oracle Market Slot Sequencing Audit",
        "total_matches": total_matches,
        "seeds": seeds,
        "opponents": opponents,
        "seats": seats,
        "mean_oracle_regret": round(mean_regret, 2),
        "median_oracle_regret": round(median_regret, 2),
        "max_oracle_regret": round(max_regret, 2),
        "gate_a_threshold": 250.0,
        "gate_a_passed": gate_a_passed,
        "gate_a_judgment_needed": gate_a_judgment,
        "decision": "PROCEED_TO_PREDICTOR" if gate_a_passed else ("JUDGMENT_REQUIRED" if gate_a_judgment else "CLOSE_M0_H_INSUFFICIENT_VALUE"),
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n=== Phase M0-H Oracle Audit Results Summary ===")
    print(f"Mean Oracle Slot Regret: ${mean_regret:.2f} / match")
    print(f"Median Oracle Slot Regret: ${median_regret:.2f} / match")
    print(f"P90 Oracle Slot Regret: ${p90_regret:.2f} / match")
    print(f"Max Oracle Slot Regret: ${max_regret:.2f} / match")
    print(f"Matches with Regret > 0: {matches_with_regret}/{total_matches} ({matches_with_regret/total_matches*100:.1f}%)")
    print(f"Turns with Regret > $0: {turns_gt_0} (>$25: {turns_gt_25}, >$50: {turns_gt_50}, >$100: {turns_gt_100})")
    print(f"Overall Collision Rate: {tot_collided}/{tot_sells} ({slot_collision_frequency['overall_collision_rate']*100:.2f}%)")
    print(f"Decision Gate A Status: {manifest['decision']}")


if __name__ == "__main__":
    main()
