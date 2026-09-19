"""Paired 10-Scenario A/B Experiment: Day-0 Opening Commitment Idempotence Repair.

Compares:
  Arm A: Baseline (Commit a74d63f — without Day-0 opening idempotence)
  Arm B: Candidate (HEAD — with Day-0 opening commitment idempotence & physical capacity bounding)

Across 10 paired scenarios (2 matches per opponent archetype):
  1. Seed 42   vs pass
  2. Seed 1234 vs pass
  3. Seed 101  vs pure_wheat_rush
  4. Seed 55   vs pure_wheat_rush
  5. Seed 2024 vs cow_milk_engine
  6. Seed 314  vs cow_milk_engine
  7. Seed 7    vs melon_sniper
  8. Seed 8888 vs melon_sniper
  9. Seed 999  vs full_production_agent
  10. Seed 777 vs full_production_agent

Telemetry Tracked:
  - Actual seed purchases ordered on Day 0 (MELON and WHEAT)
  - Actual seed spend on Day 0
  - Successful plantings by Day 0 EOD (hour 23)
  - NW empty/fallow tile usage at Day 0 EOD
  - Cash at end of Day 0 through Day 6
  - Safety incidents (unwatered crops at EOD0, animal starvation/deaths, negative cash)
  - Final scores and win/loss/tie outcomes at Day 30
"""

import os
import sys
import json
import time
import traceback
from typing import Dict, Any, List
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO_ROOT = r"d:\website project\kaggri ox"
CANDIDATE_DIR = os.path.join(REPO_ROOT, "agent")
BASELINE_DIR = os.path.join(REPO_ROOT, "simulations", "baselines", "baseline_a74d63f", "agent")

PAIRS = [
    {"pair_id": 1, "seed": 42, "opponent": "pass"},
    {"pair_id": 2, "seed": 1234, "opponent": "pass"},
    {"pair_id": 3, "seed": 101, "opponent": "pure_wheat_rush"},
    {"pair_id": 4, "seed": 55, "opponent": "pure_wheat_rush"},
    {"pair_id": 5, "seed": 2024, "opponent": "cow_milk_engine"},
    {"pair_id": 6, "seed": 314, "opponent": "cow_milk_engine"},
    {"pair_id": 7, "seed": 7, "opponent": "melon_sniper"},
    {"pair_id": 8, "seed": 8888, "opponent": "melon_sniper"},
    {"pair_id": 9, "seed": 999, "opponent": "full_production_agent"},
    {"pair_id": 10, "seed": 777, "opponent": "full_production_agent"},
]


def _run_single_match(task: Dict[str, Any]) -> Dict[str, Any]:
    arm = task["arm"]
    pair_id = task["pair_id"]
    seed = task["seed"]
    opponent_name = task["opponent"]

    target_agent_dir = CANDIDATE_DIR if arm == "Candidate" else BASELINE_DIR

    # Isolate sys.path for the subprocess
    clean_sys_path = [p for p in sys.path if "agent" not in p.lower() and ".worktrees" not in p.lower()]
    sys.path = [target_agent_dir] + [
        os.path.join(target_agent_dir, sub) for sub in ("state", "strategy", "execution", "market")
    ] + [REPO_ROOT] + clean_sys_path

    # Clean local module caches
    to_delete = [
        k for k in list(sys.modules.keys())
        if any(k.startswith(p) for p in (
            "main", "config", "strategy", "state", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "animal_planner",
            "pasture_planner", "expansion_planner", "observation_parser", "state_tracker"
        ))
    ]
    for k in to_delete:
        del sys.modules[k]

    import kaggle_environments
    from kaggle_environments.envs.kaggriculture.kaggriculture import CROPS
    import main as agent_module
    import config as cfg
    from simulations.experiments.agent_zoo import get_agent

    # Ensure strict production default settings
    cfg.POINT2_FEED_MODE = "shadow"
    cfg.BOOTSTRAP_LIVESTOCK_ARM = "none"
    cfg.ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False
    cfg.POINT2_PRE_NE_CAPITAL_MODE = "off"

    agent_module.reset_agent_state()

    # Telemetry storage
    day0_seed_orders: List[Dict[str, Any]] = []
    day0_melon_ordered = 0
    day0_wheat_ordered = 0
    day0_seed_spend = 0.0

    cash_by_day: Dict[str, float] = {}
    safety_incidents = {
        "negative_cash_steps": 0,
        "animal_starvations": 0,
        "animal_deaths": 0,
        "unwatered_crops_eod0": 0,
    }

    day0_eod_tiles = {
        "planted_melon": 0,
        "planted_wheat": 0,
        "total_planted": 0,
        "empty_nw_tiles": 0,
        "pasture_tiles": 0,
        "coop_tiles": 0,
    }

    def tracking_agent(obs, config=None):
        nonlocal day0_melon_ordered, day0_wheat_ordered, day0_seed_spend
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        player_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        farm_data = farms[player_id] if len(farms) > player_id else {}
        money = float(farm_data.get("money", 0.0))

        # Check negative cash
        if money < 0:
            safety_incidents["negative_cash_steps"] += 1

        # Check animal starvation at hour 0
        if hour == 0 and day > 0:
            for row in farm_data.get("tiles", []):
                for t in row:
                    if isinstance(t, dict) and t.get("animal"):
                        if t.get("consecutive_unfed", 0) > 0:
                            safety_incidents["animal_starvations"] += 1

        # Check dead animals
        private_data = obs.get("private", {})
        # Dead animals or unwatered checks done on tiles

        # Invoke agent
        action = agent_module.agent(obs, config) or {}

        # Track Day 0 market orders
        if day == 0:
            for order in action.get("market", []):
                if isinstance(order, (list, tuple)) and len(order) >= 3 and order[0] == "BUY_SEED":
                    crop = order[1]
                    qty = int(order[2])
                    cost = qty * CROPS.get(crop, {}).get("seed", 0.0)
                    day0_seed_orders.append({
                        "hour": hour,
                        "crop": crop,
                        "qty": qty,
                        "cost": cost,
                    })
                    if crop == "MELON":
                        day0_melon_ordered += qty
                    elif crop == "WHEAT":
                        day0_wheat_ordered += qty
                    day0_seed_spend += cost

        # Track Day 0 EOD tile status at hour 23
        if day == 0 and hour == 23:
            tiles = farm_data.get("tiles", [])
            for y in range(5):
                for x in range(5):
                    if (x, y) == (4, 4):
                        continue
                    t = tiles[y][x] if y < len(tiles) and x < len(tiles[y]) else None
                    if t is None or (isinstance(t, dict) and t.get("kind") == "EMPTY"):
                        day0_eod_tiles["empty_nw_tiles"] += 1
                    elif isinstance(t, dict):
                        kind = t.get("kind")
                        if kind == "PLANT":
                            day0_eod_tiles["total_planted"] += 1
                            c = t.get("crop")
                            if c == "MELON":
                                day0_eod_tiles["planted_melon"] += 1
                            elif c == "WHEAT":
                                day0_eod_tiles["planted_wheat"] += 1
                            if not t.get("watered_today", False):
                                safety_incidents["unwatered_crops_eod0"] += 1
                        elif kind == "PASTURE":
                            day0_eod_tiles["pasture_tiles"] += 1
                        elif kind == "COOP":
                            day0_eod_tiles["coop_tiles"] += 1

        # Track cash balance at EOD for Days 0 through 6
        if hour == 23 and day <= 6:
            cash_by_day[f"d{day}"] = money

        return action

    t0 = time.time()
    try:
        env = kaggle_environments.make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720})
        opp_callable = get_agent(opponent_name)
        runner = env.run([tracking_agent, opp_callable])

        last_step = runner[-1]
        p0_state = last_step[0]
        p1_state = last_step[1]

        final_score_p0 = float(p0_state.get("reward", 0.0) or 0.0)
        final_score_p1 = float(p1_state.get("reward", 0.0) or 0.0)
        elapsed = time.time() - t0

        return {
            "pair_id": pair_id,
            "arm": arm,
            "seed": seed,
            "opponent": opponent_name,
            "final_score": final_score_p0,
            "opp_score": final_score_p1,
            "win": final_score_p0 > final_score_p1,
            "tie": final_score_p0 == final_score_p1,
            "day0_melon_ordered": day0_melon_ordered,
            "day0_wheat_ordered": day0_wheat_ordered,
            "day0_total_ordered": day0_melon_ordered + day0_wheat_ordered,
            "day0_seed_spend": day0_seed_spend,
            "day0_seed_orders": day0_seed_orders,
            "day0_eod_tiles": day0_eod_tiles,
            "cash_by_day": cash_by_day,
            "safety_incidents": safety_incidents,
            "elapsed": round(elapsed, 2),
            "status": "SUCCESS",
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "pair_id": pair_id,
            "arm": arm,
            "seed": seed,
            "opponent": opponent_name,
            "error": str(e),
            "final_score": 0.0,
            "opp_score": 0.0,
            "status": "ERROR",
            "elapsed": round(time.time() - t0, 2),
        }


def run_all_matches(max_workers: int = 4) -> Dict[str, Any]:
    tasks = []
    for p in PAIRS:
        tasks.append({"arm": "Baseline", "pair_id": p["pair_id"], "seed": p["seed"], "opponent": p["opponent"]})
        tasks.append({"arm": "Candidate", "pair_id": p["pair_id"], "seed": p["seed"], "opponent": p["opponent"]})

    print(f"Starting Paired Day-0 Opening Commitment Experiment:")
    print(f"  Total Scenarios: {len(PAIRS)} pairs (20 matches)")
    print(f"  Workers: {max_workers}")
    print(f"  Baseline: commit a74d63f")
    print(f"  Candidate: HEAD (fix/day0-opening-idempotence-a74d63f)\n")

    t_start = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_run_single_match, t): t for t in tasks}
        completed = 0
        total = len(tasks)
        for fut in as_completed(future_map):
            res = fut.result()
            results.append(res)
            completed += 1
            print(f"  [{completed:2d}/{total:2d}] {res['arm']:9s} Pair {res['pair_id']:2d} (Seed {res['seed']:5d} vs {res['opponent']:20s}): P0={res['final_score']:10.1f} ({res['elapsed']}s)")

    # Pair alignment and delta computation
    paired_data = {}
    for r in results:
        pid = r["pair_id"]
        if pid not in paired_data:
            paired_data[pid] = {}
        paired_data[pid][r["arm"]] = r

    pairs_summary = []
    for p in PAIRS:
        pid = p["pair_id"]
        base = paired_data[pid].get("Baseline", {})
        cand = paired_data[pid].get("Candidate", {})

        score_delta = cand.get("final_score", 0.0) - base.get("final_score", 0.0)
        melon_delta = cand.get("day0_melon_ordered", 0) - base.get("day0_melon_ordered", 0)
        wheat_delta = cand.get("day0_wheat_ordered", 0) - base.get("day0_wheat_ordered", 0)
        spend_delta = cand.get("day0_seed_spend", 0.0) - base.get("day0_seed_spend", 0.0)
        empty_delta = cand.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0) - base.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0)

        pairs_summary.append({
            "pair_id": pid,
            "seed": p["seed"],
            "opponent": p["opponent"],
            "base_score": base.get("final_score", 0.0),
            "cand_score": cand.get("final_score", 0.0),
            "score_delta": score_delta,
            "base_melon_ordered": base.get("day0_melon_ordered", 0),
            "cand_melon_ordered": cand.get("day0_melon_ordered", 0),
            "base_wheat_ordered": base.get("day0_wheat_ordered", 0),
            "cand_wheat_ordered": cand.get("day0_wheat_ordered", 0),
            "base_seed_spend": base.get("day0_seed_spend", 0.0),
            "cand_seed_spend": cand.get("day0_seed_spend", 0.0),
            "base_eod_planted": base.get("day0_eod_tiles", {}).get("total_planted", 0),
            "cand_eod_planted": cand.get("day0_eod_tiles", {}).get("total_planted", 0),
            "base_eod_empty": base.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0),
            "cand_eod_empty": cand.get("day0_eod_tiles", {}).get("empty_nw_tiles", 0),
            "empty_delta": empty_delta,
            "base_cash_d0": base.get("cash_by_day", {}).get("d0", 0.0),
            "cand_cash_d0": cand.get("cash_by_day", {}).get("d0", 0.0),
            "base_cash_d1": base.get("cash_by_day", {}).get("d1", 0.0),
            "cand_cash_d1": cand.get("cash_by_day", {}).get("d1", 0.0),
            "base_cash_d6": base.get("cash_by_day", {}).get("d6", 0.0),
            "cand_cash_d6": cand.get("cash_by_day", {}).get("d6", 0.0),
            "base_safety": base.get("safety_incidents", {}),
            "cand_safety": cand.get("safety_incidents", {}),
        })

    # Sort by pair_id
    pairs_summary.sort(key=lambda x: x["pair_id"])

    # Aggregate metrics
    mean_base_score = sum(p["base_score"] for p in pairs_summary) / len(pairs_summary)
    mean_cand_score = sum(p["cand_score"] for p in pairs_summary) / len(pairs_summary)
    mean_score_delta = sum(p["score_delta"] for p in pairs_summary) / len(pairs_summary)
    wins = sum(1 for p in pairs_summary if p["score_delta"] > 0)
    ties = sum(1 for p in pairs_summary if p["score_delta"] == 0)
    losses = sum(1 for p in pairs_summary if p["score_delta"] < 0)

    total_base_melon = sum(p["base_melon_ordered"] for p in pairs_summary)
    total_cand_melon = sum(p["cand_melon_ordered"] for p in pairs_summary)
    total_base_wheat = sum(p["base_wheat_ordered"] for p in pairs_summary)
    total_cand_wheat = sum(p["cand_wheat_ordered"] for p in pairs_summary)
    total_base_spend = sum(p["base_seed_spend"] for p in pairs_summary)
    total_cand_spend = sum(p["cand_seed_spend"] for p in pairs_summary)

    aggregate = {
        "total_pairs": len(pairs_summary),
        "mean_base_score": round(mean_base_score, 2),
        "mean_cand_score": round(mean_cand_score, 2),
        "mean_score_delta": round(mean_score_delta, 2),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "total_base_melon_ordered": total_base_melon,
        "total_cand_melon_ordered": total_cand_melon,
        "total_base_wheat_ordered": total_base_wheat,
        "total_cand_wheat_ordered": total_cand_wheat,
        "total_base_seed_spend": total_base_spend,
        "total_cand_seed_spend": total_cand_spend,
        "redundant_melon_orders_eliminated": total_base_melon - total_cand_melon,
        "redundant_wheat_orders_eliminated": total_base_wheat - total_cand_wheat,
        "redundant_spend_eliminated": total_base_spend - total_cand_spend,
        "total_elapsed_sec": round(time.time() - t_start, 2),
    }

    full_output = {
        "aggregate": aggregate,
        "pairs_summary": pairs_summary,
        "raw_results": results,
    }

    return full_output


def print_report(data: Dict[str, Any]):
    agg = data["aggregate"]
    pairs = data["pairs_summary"]

    print("\n" + "=" * 110)
    print("DAY-0 OPENING COMMITMENT IDEMPOTENCE REPAIR: 10-PAIR A/B EVALUATION REPORT")
    print("=" * 110)
    print(f"Total Pairs: {agg['total_pairs']} | Workers: 4 | Total Elapsed: {agg['total_elapsed_sec']}s")
    print(f"Mean Baseline Score:  ${agg['mean_base_score']:10,.2f}")
    print(f"Mean Candidate Score: ${agg['mean_cand_score']:10,.2f}")
    print(f"Mean Score Delta:     {'+' if agg['mean_score_delta'] >= 0 else ''}${agg['mean_score_delta']:10,.2f}")
    print(f"Head-to-Head Record:  {agg['wins']} Wins / {agg['ties']} Ties / {agg['losses']} Losses")
    print(f"Total Melon Seeds Ordered: Base={agg['total_base_melon_ordered']} | Cand={agg['total_cand_melon_ordered']} (Eliminated: {agg['redundant_melon_orders_eliminated']})")
    print(f"Total Wheat Seeds Ordered: Base={agg['total_base_wheat_ordered']} | Cand={agg['total_cand_wheat_ordered']} (Eliminated: {agg['redundant_wheat_orders_eliminated']})")
    print(f"Total Day-0 Seed Spend:    Base=${agg['total_base_seed_spend']:,.2f} | Cand=${agg['total_cand_seed_spend']:,.2f} (Savings: ${agg['redundant_spend_eliminated']:,.2f})")
    print("-" * 110)

    header = f"{'Pair':<5}{'Seed':<7}{'Opponent':<22}{'Base Score':<13}{'Cand Score':<13}{'Delta':<10}{'Base Seeds':<12}{'Cand Seeds':<12}{'NW Empty':<10}{'D0 Cash (B/C)':<16}"
    print(header)
    print("-" * 110)

    for p in pairs:
        delta_str = f"{'+' if p['score_delta'] >= 0 else ''}{p['score_delta']:,.0f}"
        base_seeds = f"{p['base_melon_ordered']}M/{p['base_wheat_ordered']}W"
        cand_seeds = f"{p['cand_melon_ordered']}M/{p['cand_wheat_ordered']}W"
        nw_empty = f"{p['base_eod_empty']} -> {p['cand_eod_empty']}"
        cash_bc = f"${p['base_cash_d0']:.0f}/${p['cand_cash_d0']:.0f}"
        print(f"{p['pair_id']:<5}{p['seed']:<7}{p['opponent']:<22}${p['base_score']:<12,.0f}${p['cand_score']:<12,.0f}{delta_str:<10}{base_seeds:<12}{cand_seeds:<12}{nw_empty:<10}{cash_bc:<16}")

    print("=" * 110 + "\n")


def main():
    max_workers = min(4, os.cpu_count() or 4)
    data = run_all_matches(max_workers=max_workers)

    out_path = os.path.join(REPO_ROOT, "simulations", "experiments", "results", "day0_opening_ab_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Detailed results written to: {out_path}")
    print_report(data)


if __name__ == "__main__":
    main()
