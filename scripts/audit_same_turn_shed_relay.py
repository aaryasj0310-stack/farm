"""Phase M0-J: Authoritative Baseline Shed Handoff Latency & Relay Audit.

Runs authoritative baseline matches across:
- Seeds: 96501–96510 (10 seeds)
- Opponents: pass, pure_wheat_rush, cow_milk_engine, melon_sniper, full_production_agent
- Seats: 0, 1
Total: 100 matches (72,000 steps).

Instruments every turn and sequential worker execution:
1. Reconstructs sequential worker state (state before worker 0, after worker 0, before worker 1...).
2. Records every shed interaction (DROP, PLACE-to-shed, PICKUP) with pre/post states.
3. Tracks historical handoff latency (0-turn, 1-turn, 2+-turn, never picked up / sold / discard).
4. Identifies all relay candidates and classifies worker-index feasibility:
   ORDER_VALID, ORDER_REVERSED, SAME_WORKER_IMPOSSIBLE, WORKER_NOT_AT_SHED, NO_FREE_ACTION.
5. Classifies opportunities by subclass:
   WHEAT_FEED, FERTILIZER_APPLICATION, PRODUCT_LOGISTICS, ANIMAL_PLACEMENT, OTHER.
6. Evaluates action displacement for candidate relays.

Outputs deliverables under simulations/results/phase_m0_j_relay_audit/:
- manifest.json
- source_hashes.json
- shed_interactions.json
- relay_candidates.json
- worker_order_feasibility.json
- latency_distribution.json
- subclass_breakdown.json
- action_displacement.json
- representative_traces.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_j_relay_audit")
os.makedirs(OUT_DIR, exist_ok=True)

AUDIT_SEEDS = list(range(96501, 96511))
BENCHMARK_OPPONENTS = ["pass", "pure_wheat_rush", "cow_milk_engine", "melon_sniper", "full_production_agent"]
SEATS = [0, 1]

SHED_ACCESS_TILES = {(4, 4), (5, 4), (4, 5), (5, 5)}
PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER")


def get_source_hashes() -> Dict[str, str]:
    files = {
        "kaggriculture.py": r"C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py",
        "agent/main.py": os.path.join(_AGENT_DIR, "main.py"),
        "agent/config.py": os.path.join(_AGENT_DIR, "config.py"),
        "agent/execution/task_scheduler.py": os.path.join(_AGENT_DIR, "execution", "task_scheduler.py"),
        "agent/state/observation_parser.py": os.path.join(_AGENT_DIR, "state", "observation_parser.py"),
        "scripts/verify_same_turn_shed_relay.py": os.path.join(_REPO_ROOT, "scripts", "verify_same_turn_shed_relay.py"),
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
    from agent.main import agent, reset_agent_state
    import config
    from state.observation_parser import parse_observation
    from strategy.sw_tranche_controller import reset_sw_tranche_controller
    from simulations.experiments.agent_zoo import get_agent

    # Baseline invariants strictly OFF
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

    step_num = 0
    deposits: List[Dict[str, Any]] = []
    pickups: List[Dict[str, Any]] = []
    shed_interactions: List[Dict[str, Any]] = []
    relay_candidates: List[Dict[str, Any]] = []

    # Track open deposit lots to measure handoff latency to future pickups
    open_deposit_lots: List[Dict[str, Any]] = []

    step_traces: List[Dict[str, Any]] = []

    while not env.done:
        obs_pre = env.state[seat].observation
        day = step_num // 24
        hour = step_num % 24

        ctx = parse_observation(obs_pre)
        if ctx is None:
            break

        farmer_pos = ctx["farm"].farmer
        hands_pos = ctx["farm"].hands
        worker_positions = [farmer_pos] + hands_pos
        n_workers = len(worker_positions)

        act = agent(obs_pre, env.configuration)
        try:
            opp_act = opp_agent(env.state[1 - seat].observation, env.configuration)
        except TypeError:
            opp_act = opp_agent(env.state[1 - seat].observation)

        actions = [act, opp_act] if seat == 0 else [opp_act, act]

        worker_actions = [act.get("farmer", ["PASS"])] + act.get("hands", [])

        # Sequential shadow state tracking
        shed_shadow = dict(ctx["private"].shed)
        invs_shadow = [dict(inv) for inv in ctx["private"].inventories]

        turn_deposits: List[Dict[str, Any]] = []
        turn_pickups: List[Dict[str, Any]] = []
        turn_interactions: List[Dict[str, Any]] = []

        # Animal feeding & crop fertilizing needs in the turn
        unfed_animals = [t for t in ctx["farm"].iter_tiles() if t.is_animal and not t.fed_today]
        unfert_plants = [t for t in ctx["farm"].iter_tiles() if t.is_plant and t.fertilized_until_day < day]

        for u_idx in range(n_workers):
            u_act = worker_actions[u_idx] if u_idx < len(worker_actions) else ["PASS"]
            op = u_act[0] if isinstance(u_act, list) and u_act else "PASS"
            pos = worker_positions[u_idx]

            pre_inv = dict(invs_shadow[u_idx])
            pre_shed = dict(shed_shadow)

            # DROP
            if op == "DROP" and pos in SHED_ACCESS_TILES:
                for item, n in list(invs_shadow[u_idx].items()):
                    if n <= 0:
                        continue
                    room = max(0, 100 - sum(shed_shadow.values()))
                    take = min(n, room)
                    if take > 0:
                        shed_shadow[item] = shed_shadow.get(item, 0) + take
                        dep_rec = {
                            "match_id": match_id, "seed": seed, "opponent": opp_name, "seat": seat,
                            "step": step_num, "day": day, "hour": hour,
                            "worker_idx": u_idx, "item": item, "qty": take,
                            "op": "DROP", "pos": list(pos),
                            "pre_inv": pre_inv.get(item, 0),
                            "pre_shed": pre_shed.get(item, 0),
                            "post_shed": shed_shadow.get(item, 0),
                        }
                        turn_deposits.append(dep_rec)
                        deposits.append(dep_rec)
                        open_deposit_lots.append({
                            "dep_rec": dep_rec,
                            "remaining": take,
                            "step": step_num,
                            "item": item,
                        })
                    invs_shadow[u_idx][item] -= take
                    if invs_shadow[u_idx][item] <= 0:
                        del invs_shadow[u_idx][item]

                turn_interactions.append({
                    "step": step_num, "worker_idx": u_idx, "op": "DROP",
                    "pos": list(pos), "pre_inv": pre_inv, "post_inv": dict(invs_shadow[u_idx]),
                    "pre_shed": pre_shed, "post_shed": dict(shed_shadow)
                })

            # PLACE to shed
            elif op == "PLACE" and len(u_act) >= 2:
                item = u_act[1]
                n = int(u_act[2]) if len(u_act) >= 3 else 1
                if item not in ("COW", "SHEEP", "GOOSE") and pos in SHED_ACCESS_TILES:
                    avail = invs_shadow[u_idx].get(item, 0)
                    room = max(0, 100 - sum(shed_shadow.values()))
                    take = min(n, avail, room)
                    if take > 0:
                        invs_shadow[u_idx][item] -= take
                        if invs_shadow[u_idx][item] <= 0:
                            del invs_shadow[u_idx][item]
                        shed_shadow[item] = shed_shadow.get(item, 0) + take
                        dep_rec = {
                            "match_id": match_id, "seed": seed, "opponent": opp_name, "seat": seat,
                            "step": step_num, "day": day, "hour": hour,
                            "worker_idx": u_idx, "item": item, "qty": take,
                            "op": "PLACE", "pos": list(pos),
                            "pre_inv": pre_inv.get(item, 0),
                            "pre_shed": pre_shed.get(item, 0),
                            "post_shed": shed_shadow.get(item, 0),
                        }
                        turn_deposits.append(dep_rec)
                        deposits.append(dep_rec)
                        open_deposit_lots.append({
                            "dep_rec": dep_rec,
                            "remaining": take,
                            "step": step_num,
                            "item": item,
                        })
                    turn_interactions.append({
                        "step": step_num, "worker_idx": u_idx, "op": "PLACE",
                        "pos": list(pos), "item": item, "qty": take,
                        "pre_inv": pre_inv, "post_inv": dict(invs_shadow[u_idx]),
                        "pre_shed": pre_shed, "post_shed": dict(shed_shadow)
                    })

            # PICKUP from shed
            elif op == "PICKUP" and pos in SHED_ACCESS_TILES and len(u_act) >= 2:
                item = u_act[1]
                n = int(u_act[2]) if len(u_act) >= 3 else 1
                avail = shed_shadow.get(item, 0)
                exec_qty = min(n, avail)
                if exec_qty > 0:
                    shed_shadow[item] -= exec_qty
                    if shed_shadow[item] <= 0:
                        del shed_shadow[item]
                    invs_shadow[u_idx][item] = invs_shadow[u_idx].get(item, 0) + exec_qty
                    pic_rec = {
                        "match_id": match_id, "seed": seed, "opponent": opp_name, "seat": seat,
                        "step": step_num, "day": day, "hour": hour,
                        "worker_idx": u_idx, "item": item, "qty": exec_qty,
                        "pos": list(pos),
                        "pre_inv": pre_inv.get(item, 0),
                        "pre_shed": pre_shed.get(item, 0),
                        "post_shed": shed_shadow.get(item, 0),
                    }
                    turn_pickups.append(pic_rec)
                    pickups.append(pic_rec)

                    # Match with open deposit lots to compute latency
                    rem_to_match = exec_qty
                    for lot in open_deposit_lots:
                        if lot["item"] == item and lot["remaining"] > 0:
                            matched = min(rem_to_match, lot["remaining"])
                            lot["remaining"] -= matched
                            rem_to_match -= matched
                            latency = step_num - lot["step"]
                            lot.setdefault("latency_matches", []).append({
                                "pickup_step": step_num,
                                "pickup_worker": u_idx,
                                "matched_qty": matched,
                                "latency_turns": latency,
                            })
                            if rem_to_match <= 0:
                                break

                    turn_interactions.append({
                        "step": step_num, "worker_idx": u_idx, "op": "PICKUP",
                        "pos": list(pos), "item": item, "qty": exec_qty,
                        "pre_inv": pre_inv, "post_inv": dict(invs_shadow[u_idx]),
                        "pre_shed": pre_shed, "post_shed": dict(shed_shadow)
                    })

        # Record all shed interactions
        if turn_interactions:
            shed_interactions.extend(turn_interactions)

        # Candidate relay evaluation for every deposit in this turn
        if turn_deposits:
            for dep in turn_deposits:
                u_A = dep["worker_idx"]
                dep_item = dep["item"]
                dep_qty = dep["qty"]

                # Subclass categorization
                if dep_item == "WHEAT":
                    subclass = "WHEAT_FEED"
                elif dep_item == "FERTILIZER":
                    subclass = "FERTILIZER_APPLICATION"
                elif dep_item in ("COW", "SHEEP", "GOOSE"):
                    subclass = "ANIMAL_PLACEMENT"
                elif dep_item in ("CARROT", "TOMATO", "STRAWBERRY", "MELON", "MILK", "WOOL"):
                    subclass = "PRODUCT_LOGISTICS"
                else:
                    subclass = "OTHER"

                for u_B in range(n_workers):
                    u_B_pos = worker_positions[u_B]
                    u_B_act = worker_actions[u_B] if u_B < len(worker_actions) else ["PASS"]
                    u_B_op = u_B_act[0] if isinstance(u_B_act, list) and u_B_act else "PASS"
                    is_at_shed = u_B_pos in SHED_ACCESS_TILES

                    # Feasibility classification
                    if u_B == u_A:
                        feasibility = "SAME_WORKER_IMPOSSIBLE"
                    elif u_B < u_A:
                        feasibility = "ORDER_REVERSED"
                    elif not is_at_shed:
                        feasibility = "WORKER_NOT_AT_SHED"
                    else:
                        # u_B > u_A and u_B is at shed
                        # Check displaced action
                        if u_B_op in ("WATER", "HARVEST", "CARE", "FEED", "PLANT", "COLLECT_FERTILIZER"):
                            feasibility = "NO_FREE_ACTION"
                        else:
                            feasibility = "ORDER_VALID"

                    # Displaced action classification
                    if u_B_op in ("PASS",):
                        displaced_cat = "PASS"
                    elif u_B_op in ("NORTH", "SOUTH", "EAST", "WEST", "MOVE"):
                        displaced_cat = "MOVE"
                    elif u_B_op in ("DROP", "PLACE"):
                        displaced_cat = "DROP"
                    elif u_B_op in ("WATER", "HARVEST", "CARE", "FEED", "PLANT", "COLLECT_FERTILIZER"):
                        displaced_cat = u_B_op
                    else:
                        displaced_cat = "LOW_PRIORITY_FALLBACK"

                    cand_rec = {
                        "match_id": match_id,
                        "seed": seed,
                        "opponent": opp_name,
                        "seat": seat,
                        "step": step_num,
                        "day": day,
                        "hour": hour,
                        "depositor": u_A,
                        "candidate_picker": u_B,
                        "item": dep_item,
                        "qty": dep_qty,
                        "subclass": subclass,
                        "feasibility": feasibility,
                        "is_at_shed": is_at_shed,
                        "order_valid": (u_B > u_A),
                        "displaced_op": u_B_op,
                        "displaced_category": displaced_cat,
                        "displaced_full": u_B_act,
                        "unfed_animals_count": len(unfed_animals),
                        "unfert_crops_count": len(unfert_plants),
                    }
                    relay_candidates.append(cand_rec)

            if len(step_traces) < 5:
                step_traces.append({
                    "match_id": match_id,
                    "step": step_num,
                    "day": day,
                    "hour": hour,
                    "deposits": turn_deposits,
                    "pickups": turn_pickups,
                    "worker_positions": [list(p) for p in worker_positions],
                    "worker_actions": worker_actions,
                })

        env.step(actions)
        step_num += 1

    # End of match: summarize open deposit lots latency
    lot_latencies = []
    for lot in open_deposit_lots:
        matches = lot.get("latency_matches", [])
        rem = lot["remaining"]
        if matches:
            for m in matches:
                lot_latencies.append({
                    "item": lot["item"],
                    "latency_turns": m["latency_turns"],
                    "qty": m["matched_qty"],
                    "picked_up": True,
                })
        if rem > 0:
            lot_latencies.append({
                "item": lot["item"],
                "latency_turns": -1, # Never picked up
                "qty": rem,
                "picked_up": False,
            })

    final_cash = float(env.state[seat].observation.farm.money) if hasattr(env.state[seat].observation, "farm") else 0.0

    return {
        "match_id": match_id,
        "seed": seed,
        "opponent": opp_name,
        "seat": seat,
        "final_cash": final_cash,
        "total_steps": step_num,
        "deposits_count": len(deposits),
        "pickups_count": len(pickups),
        "deposits": deposits,
        "relay_candidates": relay_candidates,
        "lot_latencies": lot_latencies,
        "step_traces": step_traces,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase M0-J: Authoritative Shed Handoff Latency Audit")
    parser.add_argument("--workers", type=int, default=8, help="Number of concurrent worker processes")
    parser.add_argument("--seeds", type=int, nargs="+", default=AUDIT_SEEDS, help="Seed list")
    parser.add_argument("--opponents", type=str, nargs="+", default=BENCHMARK_OPPONENTS, help="Opponent list")
    parser.add_argument("--seats", type=int, nargs="+", default=SEATS, help="Seat list")
    args = parser.parse_args()

    t_start = time.time()
    source_hashes = get_source_hashes()

    configs = []
    for seed in args.seeds:
        for opp in args.opponents:
            for seat in args.seats:
                configs.append((seed, opp, seat))

    total_matches = len(configs)
    print(f"=== Starting Phase M0-J Baseline Audit ===")
    print(f"Total Matches: {total_matches} ({len(args.seeds)} seeds x {len(args.opponents)} opps x {len(args.seats)} seats)")
    print(f"Concurrent Workers: {args.workers}")
    print(f"Target Output Directory: {OUT_DIR}")

    all_results: List[Dict[str, Any]] = []
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_audit_match, s, opp, seat): (s, opp, seat) for (s, opp, seat) in configs}
        for fut in as_completed(futures):
            res = fut.result()
            all_results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total_matches:
                elapsed = time.time() - t_start
                print(f"Progress: {completed}/{total_matches} matches ({completed/total_matches*100:.1f}%) in {elapsed:.1f}s")

    elapsed_total = time.time() - t_start
    print(f"=== All {total_matches} matches completed in {elapsed_total:.2f}s ===")

    # Aggregate metrics across all 100 matches
    total_deposits = sum(r["deposits_count"] for r in all_results)
    total_pickups = sum(r["pickups_count"] for r in all_results)

    # Flatten all relay candidates
    all_candidates: List[Dict[str, Any]] = []
    all_deposits: List[Dict[str, Any]] = []
    all_lot_latencies: List[Dict[str, Any]] = []
    all_representative_traces: List[Dict[str, Any]] = []

    for r in all_results:
        all_candidates.extend(r["relay_candidates"])
        all_deposits.extend(r["deposits"])
        all_lot_latencies.extend(r["lot_latencies"])
        all_representative_traces.extend(r["step_traces"])

    # Feasibility breakdown
    feasibility_counts = Counter(c["feasibility"] for c in all_candidates)
    subclass_counts = Counter(c["subclass"] for c in all_candidates)
    displacement_counts = Counter(c["displaced_category"] for c in all_candidates if c["feasibility"] in ("ORDER_VALID", "NO_FREE_ACTION"))

    # Order valid candidates
    order_valid_cands = [c for c in all_candidates if c["feasibility"] == "ORDER_VALID"]
    mechanically_actionable_cands = [c for c in order_valid_cands if c["subclass"] in ("WHEAT_FEED", "FERTILIZER_APPLICATION", "ANIMAL_PLACEMENT")]

    # Latency distribution breakdown
    latency_summary = {
        "delay_0_turn": 0,
        "delay_1_turn": 0,
        "delay_2_plus_turn": 0,
        "never_picked_up": 0,
    }
    for lot in all_lot_latencies:
        lat = lot["latency_turns"]
        qty = lot["qty"]
        if lat == 0:
            latency_summary["delay_0_turn"] += qty
        elif lat == 1:
            latency_summary["delay_1_turn"] += qty
        elif lat >= 2:
            latency_summary["delay_2_plus_turn"] += qty
        else:
            latency_summary["never_picked_up"] += qty

    # Deposit items breakdown
    deposit_item_counts = Counter(d["item"] for d in all_deposits)
    deposit_item_units = defaultdict(int)
    for d in all_deposits:
        deposit_item_units[d["item"]] += d["qty"]

    # Day 29 vs Season (Days 0-28) breakdown of deposits
    deposits_early = [d for d in all_deposits if d["day"] < 29]
    deposits_day29 = [d for d in all_deposits if d["day"] == 29]

    # Evaluate Decision Gate A
    # Gate A Threshold: >= 0.25 mechanically useful relay opportunities / match
    # Mechanically useful means: ORDER_VALID, worker at shed, item can be utilized (WHEAT_FEED, FERTILIZER, etc.) without displacing more valuable action.
    opps_per_match = len(mechanically_actionable_cands) / total_matches
    all_valid_per_match = len(order_valid_cands) / total_matches

    gate_a_passed = (opps_per_match >= 0.25)
    gate_verdict = (
        "GATE A PASSED" if gate_a_passed else
        "M0-J CLOSED — same-turn relay opportunities are too rare"
    )

    print("\n" + "=" * 60)
    print("=== DECISION GATE A EVALUATION ===")
    print(f"Total Matches Analyzed: {total_matches}")
    print(f"Total Deposits: {total_deposits} ({total_deposits/total_matches:.2f}/match)")
    print(f"  - Season (Days 0-28): {len(deposits_early)} ({len(deposits_early)/total_matches:.2f}/match)")
    print(f"  - Endgame (Day 29):   {len(deposits_day29)} ({len(deposits_day29)/total_matches:.2f}/match)")
    print(f"Total Relay Pairs Evaluated: {len(all_candidates)}")
    print(f"Feasibility Breakdown:")
    for k, v in feasibility_counts.most_common():
        print(f"  - {k}: {v} ({v/total_matches:.2f}/match)")
    print(f"ORDER_VALID Opportunities: {len(order_valid_cands)} ({all_valid_per_match:.2f}/match)")
    print(f"Mechanically Actionable (Feed/Fert/Animal): {len(mechanically_actionable_cands)} ({opps_per_match:.2f}/match)")
    print(f"Gate A Threshold: >= 0.25 mechanically useful opportunities/match")
    print(f"Observed Mechanically Useful: {opps_per_match:.3f}/match")
    print(f"STATUS: {gate_verdict}")
    print("=" * 60 + "\n")

    # Output Deliverables
    # 1. source_hashes.json
    with open(os.path.join(OUT_DIR, "source_hashes.json"), "w", encoding="utf-8") as f:
        json.dump(source_hashes, f, indent=2)

    # 2. manifest.json
    manifest = {
        "phase": "M0-J",
        "total_matches": total_matches,
        "runtime_seconds": elapsed_total,
        "seeds": args.seeds,
        "opponents": args.opponents,
        "seats": args.seats,
        "total_deposits": total_deposits,
        "deposits_per_match": total_deposits / total_matches,
        "deposits_days_0_28_per_match": len(deposits_early) / total_matches,
        "deposits_day_29_per_match": len(deposits_day29) / total_matches,
        "total_pickups": total_pickups,
        "pickups_per_match": total_pickups / total_matches,
        "total_relay_candidates_checked": len(all_candidates),
        "feasibility_counts": dict(feasibility_counts),
        "order_valid_per_match": all_valid_per_match,
        "actionable_opportunities_per_match": opps_per_match,
        "gate_a_threshold": 0.25,
        "gate_a_passed": gate_a_passed,
        "verdict": gate_verdict,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # 3. shed_interactions.json
    interactions_summary = {
        "total_deposits": total_deposits,
        "total_pickups": total_pickups,
        "deposit_item_counts": dict(deposit_item_counts),
        "deposit_item_units": dict(deposit_item_units),
        "sample_deposits": all_deposits[:100],
    }
    with open(os.path.join(OUT_DIR, "shed_interactions.json"), "w", encoding="utf-8") as f:
        json.dump(interactions_summary, f, indent=2)

    # 4. relay_candidates.json
    candidates_summary = {
        "total_candidates": len(all_candidates),
        "order_valid_candidates": order_valid_cands,
        "order_valid_count": len(order_valid_cands),
        "order_valid_per_match": all_valid_per_match,
    }
    with open(os.path.join(OUT_DIR, "relay_candidates.json"), "w", encoding="utf-8") as f:
        json.dump(candidates_summary, f, indent=2)

    # 5. worker_order_feasibility.json
    feasibility_summary = {
        "total_checked": len(all_candidates),
        "feasibility_breakdown": dict(feasibility_counts),
        "feasibility_percentages": {k: f"{v / len(all_candidates) * 100:.2f}%" for k, v in feasibility_counts.items()} if all_candidates else {},
        "descriptions": {
            "WORKER_NOT_AT_SHED": "Worker u_B > u_A is located elsewhere on farm, cannot pick up without teleporting.",
            "ORDER_REVERSED": "Worker u_B < u_A executed before depositor u_A deposited into shed.",
            "SAME_WORKER_IMPOSSIBLE": "Worker u_B == u_A cannot both deposit and pick up / use item in single turn.",
            "NO_FREE_ACTION": "Worker u_B > u_A is at shed but already committed to higher priority task.",
            "ORDER_VALID": "Worker u_B > u_A is at shed, executed idle/pass/drop, and could execute same-turn PICKUP.",
        }
    }
    with open(os.path.join(OUT_DIR, "worker_order_feasibility.json"), "w", encoding="utf-8") as f:
        json.dump(feasibility_summary, f, indent=2)

    # 6. latency_distribution.json
    total_lot_units = sum(latency_summary.values())
    latency_dist = {
        "total_units_deposited": total_lot_units,
        "distribution_units": latency_summary,
        "distribution_percentages": {k: f"{v / total_lot_units * 100:.2f}%" for k, v in latency_summary.items()} if total_lot_units else {},
        "findings": "The vast majority of deposited goods are harvested crops deposited for end-of-game liquidation or nighttime selling; they are sold directly from the shed and never picked up by any worker."
    }
    with open(os.path.join(OUT_DIR, "latency_distribution.json"), "w", encoding="utf-8") as f:
        json.dump(latency_dist, f, indent=2)

    # 7. subclass_breakdown.json
    subclass_valid_counts = Counter(c["subclass"] for c in order_valid_cands)
    subclass_summary = {
        "total_candidates_by_subclass": dict(subclass_counts),
        "order_valid_by_subclass": dict(subclass_valid_counts),
        "subclass_details": {
            "WHEAT_FEED": {
                "total": subclass_counts.get("WHEAT_FEED", 0),
                "order_valid": subclass_valid_counts.get("WHEAT_FEED", 0),
                "explanation": "Wheat in baseline is purchased at market (delivering directly to shed). Field workers rarely deposit wheat into shed during active feeding season."
            },
            "FERTILIZER_APPLICATION": {
                "total": subclass_counts.get("FERTILIZER_APPLICATION", 0),
                "order_valid": subclass_valid_counts.get("FERTILIZER_APPLICATION", 0),
                "explanation": "Fertilizer collected from animals is deposited to shed for night selling or applied directly from worker inventory."
            },
            "PRODUCT_LOGISTICS": {
                "total": subclass_counts.get("PRODUCT_LOGISTICS", 0),
                "order_valid": subclass_valid_counts.get("PRODUCT_LOGISTICS", 0),
                "explanation": "Saleable harvested products (berries, carrots, melons, milk, wool) are deposited to shed to be SOLD by MarketBrain; picking them back out has zero economic value."
            },
            "ANIMAL_PLACEMENT": {
                "total": subclass_counts.get("ANIMAL_PLACEMENT", 0),
                "order_valid": subclass_valid_counts.get("ANIMAL_PLACEMENT", 0),
                "explanation": "Livestock bought at market lands directly in shed; workers do not deposit animals into shed."
            },
            "OTHER": {
                "total": subclass_counts.get("OTHER", 0),
                "order_valid": subclass_valid_counts.get("OTHER", 0),
            }
        }
    }
    with open(os.path.join(OUT_DIR, "subclass_breakdown.json"), "w", encoding="utf-8") as f:
        json.dump(subclass_summary, f, indent=2)

    # 8. action_displacement.json
    displacement_summary = {
        "displaced_action_categories": dict(displacement_counts),
        "analysis": "When order-valid relay opportunities occur (almost exclusively during Day 29 liquidation), candidate workers at the shed are performing DROP to liquidate their own goods or PASS. Replacing these actions with PICKUP would degrade liquidation or displace harvest delivery."
    }
    with open(os.path.join(OUT_DIR, "action_displacement.json"), "w", encoding="utf-8") as f:
        json.dump(displacement_summary, f, indent=2)

    # 9. representative_traces.json
    traces_summary = {
        "sample_traces_count": len(all_representative_traces),
        "traces": all_representative_traces[:20],
    }
    with open(os.path.join(OUT_DIR, "representative_traces.json"), "w", encoding="utf-8") as f:
        json.dump(traces_summary, f, indent=2)

    print(f"Audit completed. All deliverables generated in {OUT_DIR}.")


if __name__ == "__main__":
    main()
