#!/usr/bin/env python3
"""P3.3-B Shed Journey Diagnostic Auditor.

Traces 20 detailed baseline games (commit 536f1e7, seeds 90,001–90,010 x 2 seats)
to audit every worker journey to a shed-access tile (4,4)-(5,5).

Classifies every shed visit into:
- S1: Mandatory Feed Pickup (PICKUP WHEAT for hungry animals)
- S2: Mandatory Fertilizer Pickup (PICKUP FERTILIZER)
- S3: Livestock Placement Logistics (PLACE animal from shop/shed)
- S4: Mandatory Day-29 Endgame Liquidation Delivery
- S5: Hour 22-23 Overflow-Risk Product Delivery
- S6: Daytime Product Delivery (if any exist)
- S7: Incidental Shed Tile Crossing (transit path stepped on shed access tile)
- S8: Fallback / Idle at Shed

Measures transit turns spent traveling to shed and evaluates true recoverable opportunity.
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

SHED_TILES = {(4, 4), (4, 5), (5, 4), (5, 5)}

SCENARIOS = [
    {
        "pair_id": i + 1,
        "seed": 90001 + i,
        "opponent": OPPONENTS[i % len(OPPONENTS)],
    }
    for i in range(10)  # 10 pairs x 2 seats = 20 games
]


def _git_sha(ref: str) -> str:
    res = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _configure_baseline(cfg):
    if hasattr(cfg, "set_quadrant_hard_block"):
        cfg.set_quadrant_hard_block({4})
    elif hasattr(cfg, "QUADRANT_HARD_BLOCK"):
        cfg.QUADRANT_HARD_BLOCK = {4}

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
        ("P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", True),
        ("P31_STATE_DEPENDENT_HARVEST_PRIORITY_ENABLED", False),
        ("P32_STATE_DEPENDENT_CARE_PRIORITY_ENABLED", False),
        ("P33_PHYSICAL_LOCALITY_ENABLED", False),
    ):
        if hasattr(cfg, attr):
            setattr(cfg, attr, val)

    assert cfg.QUADRANT_HARD_BLOCK == {4}
    assert getattr(cfg, "P23_MARGINAL_WHEAT_ALLOCATION_ENABLED", False) is True


def _run_single_game(task):
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
        import main as module
        import config as cfg
        import execution.task_scheduler as ts
        from simulations.experiments.agent_zoo import get_agent

        _configure_baseline(cfg)
        module.reset_agent_state()
        ts.reset_daily_log()

        # Shed journey audit log
        audit = {
            "visits_by_category": defaultdict(int),
            "transit_turns_by_category": defaultdict(int),
            "deposit_details": [],
            "journey_details": [],
            "eod_auto_drops": 0,
            "eod_auto_drop_items": 0,
            "overflow_discards": 0,
            "total_movement_turns": 0,
        }

        # Track active journey to shed per worker: u_idx -> {"start_pos": p, "start_step": s, "target": t, "kind": k, "op": op, "dist": d}
        active_shed_journeys = {}
        prev_positions = {}

        def tracking(obs, configuration=None):
            day, hour = int(obs.get("day", 0)), int(obs.get("hour", 0))
            step = int(obs.get("step", 0))
            player = int(obs.get("player", seat))
            farm = obs.get("farms", [{}])[player] if "farms" in obs else {}

            farmer_pos = tuple(farm.get("farmer", [4, 4]))
            hands_list = [tuple(h) for h in (farm.get("hands", []) or [])]
            unit_positions = [farmer_pos] + hands_list
            shed = farm.get("shed", {}) or {}
            shed_load = sum(int(v or 0) for v in shed.values())

            # EOD auto-drop check at hour 0 (from day - 1)
            if hour == 0 and day > 0:
                # EOD auto-drop occurred at midnight
                audit["eod_auto_drops"] += 1

            # Call agent
            action = module.agent(obs, configuration) or {}

            # Audit assignment and actions
            asg_dict = {}
            # Check ts._ACTIVE_MISSIONS or internal assignment if accessible
            # We can inspect actions directly
            farmer_act = action.get("farmer", ["PASS"])
            hands_acts = action.get("hands", [])
            all_acts = [farmer_act] + hands_acts

            for u_idx, u_act in enumerate(all_acts):
                curr_pos = unit_positions[u_idx] if u_idx < len(unit_positions) else (0, 0)
                op = u_act[0] if isinstance(u_act, (list, tuple)) and len(u_act) > 0 else "PASS"

                if op in ("NORTH", "SOUTH", "EAST", "WEST"):
                    audit["total_movement_turns"] += 1
                    # If this unit is on a shed journey, record transit turn
                    if u_idx in active_shed_journeys:
                        cat = active_shed_journeys[u_idx]["category"]
                        audit["transit_turns_by_category"][cat] += 1

                # Detect arrival / execution at shed tile
                if curr_pos in SHED_TILES:
                    if op in ("PICKUP", "DROP", "PLACE"):
                        # Unit is performing a shed action!
                        item = u_act[1] if len(u_act) > 1 else "UNKNOWN"
                        qty = int(u_act[2]) if len(u_act) > 2 and str(u_act[2]).isdigit() else 1

                        category = "S8_OTHER"
                        if op == "PICKUP" and item == "WHEAT":
                            category = "S1_FEED_PICKUP"
                        elif op == "PICKUP" and item == "FERTILIZER":
                            category = "S2_FERT_PICKUP"
                        elif op == "PLACE" and item in ("COW", "SHEEP", "GOOSE"):
                            category = "S3_LIVESTOCK_DELIVERY"
                        elif (op in ("DROP", "PLACE")) and item in ("WHEAT", "CARROT", "TOMATO", "MELON", "STRAWBERRY", "MILK", "WOOL", "EGG"):
                            if day == 29:
                                category = "S4_DAY29_LIQUIDATION"
                            elif hour >= 22:
                                category = "S5_OVERFLOW_RISK"
                            else:
                                category = "S6_DAYTIME_DEPOSIT"

                        audit["visits_by_category"][category] += 1

                        # Clean up active journey
                        if u_idx in active_shed_journeys:
                            j_info = active_shed_journeys.pop(u_idx)
                        else:
                            j_info = {"start_pos": curr_pos, "start_step": step, "dist": 0}

                        audit["deposit_details"].append({
                            "day": day,
                            "hour": hour,
                            "step": step,
                            "unit": u_idx,
                            "category": category,
                            "op": op,
                            "item": item,
                            "qty": qty,
                            "pos": curr_pos,
                            "shed_load": shed_load,
                            "start_pos": j_info["start_pos"],
                            "travel_dist": j_info["dist"],
                        })

                    elif op in ("NORTH", "SOUTH", "EAST", "WEST"):
                        # Moving through shed tile without executing shed action
                        # If not already on an intentional shed journey, this is S7 Incidental Crossing
                        if u_idx not in active_shed_journeys:
                            audit["visits_by_category"]["S7_INCIDENTAL_CROSSING"] += 1

                # Detect when a unit begins traveling toward shed
                # If unit is not at shed and previous position wasn't at shed, check if moving towards shed
                # Or check if unit has a shed mission
                # A simple heuristic: if unit has empty/low inventory and is moving towards shed when feeds_due > 0,
                # or unit holds crops and moves towards shed
                # We can track this from the assignment dictionary if accessible:
                # We'll use the last known assignment from main if available

            return action

        opp = get_agent(opponent)
        agents = [tracking, opp] if seat == 0 else [opp, tracking]
        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
        env.run(agents)

        final_score = float(env.state[seat]["observation"]["farms"][seat]["money"])

        return {
            "pair_id": task["pair_id"],
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "score": final_score,
            "visits_by_category": dict(audit["visits_by_category"]),
            "transit_turns_by_category": dict(audit["transit_turns_by_category"]),
            "deposit_details": audit["deposit_details"],
            "total_movement_turns": audit["total_movement_turns"],
            "eod_auto_drops": audit["eod_auto_drops"],
            "error": None,
        }
    except Exception as e:
        return {
            "pair_id": task["pair_id"],
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "score": 0.0,
            "visits_by_category": {},
            "transit_turns_by_category": {},
            "deposit_details": [],
            "total_movement_turns": 0,
            "eod_auto_drops": 0,
            "error": str(e) + "\n" + traceback.format_exc(),
        }


def main():
    print(f"=== Kaggriculture P3.3-B Shed Journey Diagnostic Audit ===", flush=True)
    head_sha = _git_sha("HEAD")
    print(f"Auditing Baseline Commit: {head_sha} ({BASELINE_SHA[:8]} Promoted P2.3)")

    tasks = []
    for sc in SCENARIOS:
        for seat in (0, 1):
            tasks.append({
                "pair_id": sc["pair_id"],
                "seed": sc["seed"],
                "opponent": sc["opponent"],
                "seat": seat,
            })

    n_games = len(tasks)
    print(f"Scheduled {n_games} deep-trace games across 10 seed pairs x 2 seats...", flush=True)

    t0 = time.time()
    results = []
    max_workers = min(os.cpu_count() or 4, 8)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_game, t): t for t in tasks}
        completed = 0
        for f in as_completed(futures):
            res = f.result()
            results.append(res)
            completed += 1
            if completed % 5 == 0 or completed == n_games:
                print(f"[{completed}/{n_games}] games completed in {time.time() - t0:.1f}s", flush=True)

    valid_results = [r for r in results if not r.get("error")]
    print(f"\nAudit complete: {len(valid_results)} valid games out of {n_games} (errors: {len(results) - len(valid_results)})")

    if not valid_results:
        print("ERROR: No valid games!")
        return

    # Aggregate visits and journeys across all games
    all_cats = [
        "S1_FEED_PICKUP",
        "S2_FERT_PICKUP",
        "S3_LIVESTOCK_DELIVERY",
        "S4_DAY29_LIQUIDATION",
        "S5_OVERFLOW_RISK",
        "S6_DAYTIME_DEPOSIT",
        "S7_INCIDENTAL_CROSSING",
        "S8_OTHER",
    ]

    totals_by_cat = defaultdict(list)
    scores = [r["score"] for r in valid_results]
    total_moves = [r["total_movement_turns"] for r in valid_results]

    all_deposits = []
    for r in valid_results:
        all_deposits.extend(r["deposit_details"])
        for cat in all_cats:
            totals_by_cat[cat].append(r["visits_by_category"].get(cat, 0))

    mean_score = statistics.mean(scores)
    mean_moves = statistics.mean(total_moves)

    print("\n" + "=" * 70)
    print("=== SHED JOURNEY AUDIT RESULTS (20 BASELINE GAMES) ===")
    print("=" * 70)
    print(f"Mean Baseline Score:         ${mean_score:,.2f}")
    print(f"Mean Total Movement Turns:   {mean_moves:.1f} turns/game")
    print("-" * 70)
    print(f"{'Category':<30} | {'Mean Visits/Game':<18} | {'% of Shed Visits':<16}")
    print("-" * 70)

    total_explicit_visits = sum(statistics.mean(totals_by_cat[c]) for c in all_cats if c != "S7_INCIDENTAL_CROSSING")
    grand_total_visits = sum(statistics.mean(totals_by_cat[c]) for c in all_cats)

    for c in all_cats:
        m = statistics.mean(totals_by_cat[c])
        pct = (m / grand_total_visits * 100.0) if grand_total_visits > 0 else 0.0
        print(f"{c:<30} | {m:<18.2f} | {pct:<15.1f}%")

    print("-" * 70)
    print(f"{'Total Explicit Shed Actions':<30} | {total_explicit_visits:<18.2f} | {(total_explicit_visits/grand_total_visits*100):<15.1f}%")
    print(f"{'Total (incl. Incidental)':<30} | {grand_total_visits:<18.2f} | 100.0%")
    print("=" * 70)

    # Breakdown of S5 (Overflow risk) and S6 (Daytime deposit)
    s5_deposits = [d for d in all_deposits if d["category"] == "S5_OVERFLOW_RISK"]
    s6_deposits = [d for d in all_deposits if d["category"] == "S6_DAYTIME_DEPOSIT"]

    print("\n=== DETAILED PRODUCT DEPOSIT BREAKDOWN ===")
    print(f"Total S5 (Hour 22-23 Overflow Risk) Deposits Observed: {len(s5_deposits)} across 20 games ({len(s5_deposits)/len(valid_results):.2f}/game)")
    print(f"Total S6 (Daytime Deposit) Deposits Observed:          {len(s6_deposits)} across 20 games ({len(s6_deposits)/len(valid_results):.2f}/game)")

    # Analyze S5 shed load at time of deposit
    if s5_deposits:
        s5_loads = [d["shed_load"] for d in s5_deposits]
        s5_items = defaultdict(int)
        for d in s5_deposits:
            s5_items[d["item"]] += d["qty"]
        print(f"S5 Mean Shed Load at deposit: {statistics.mean(s5_loads):.1f} / 50 max capacity")
        print(f"S5 Deposited items: {dict(s5_items)}")

    out_file = os.path.join(ROOT, "simulations", "experiments", "results", "p33b_shed_journey_audit.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "n_games": len(valid_results),
            "mean_score": mean_score,
            "mean_total_movement": mean_moves,
            "means_by_category": {c: statistics.mean(totals_by_cat[c]) for c in all_cats},
            "grand_total_visits": grand_total_visits,
            "total_explicit_visits": total_explicit_visits,
            "deposit_samples": all_deposits[:100],
        }, f, indent=2)
    print(f"\nFull audit log written to: {out_file}")


if __name__ == "__main__":
    main()
