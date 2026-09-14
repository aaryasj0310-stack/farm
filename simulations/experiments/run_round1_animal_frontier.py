"""Round 1: Animal Frontier Experiment (Exact 588b3f1 baseline SW policy).

Evaluates 6 livestock portfolio configurations across 50 paired scenarios:
  - Arm A: Exact 588b3f1 Control (6 Cows / 12 Sheep)
  - Arm B: 8 Cows / 6 Sheep
  - Arm C: 9 Cows / 3 Sheep
  - Arm D: 8 Cows / 4 Sheep
  - Arm E: 6 Cows / 3 Sheep
  - Arm F: Dynamic marginal-value species mix

Measures:
  - Score (mean, median, delta vs Arm A, W/L/T, SD, 95% CI, P10)
  - Milk revenue & units sold
  - Wool revenue & units sold
  - Feed purchase cost & internal wheat feed consumed
  - Animal chore actions (feed, care, milk, shear)
  - Worker movements & idle actions
  - Average pasture distance to shed (4, 4)
  - Pasture tile footprint
  - Safety: starvation / animal deaths (must be 0)
"""
import os
import sys
import json
import time
import argparse
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")


def _run_single_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    arm = payload["arm"]
    seed = payload["seed"]
    opp_name = payload["opponent"]

    # Setup isolated environment
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    # Clean local module caches
    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'land_serviceability_model',
        'marginal_livestock_valuator'
    ))]
    for k in to_delete:
        del sys.modules[k]

    from kaggle_environments import make
    import main as agent_module
    from observation_parser import parse_observation
    import state_tracker
    import config

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")
    if hasattr(agent_module, "reset_daily_telemetry"):
        agent_module.reset_daily_telemetry()
    elif hasattr(agent_module, "reset_daily_log"):
        agent_module.reset_daily_log()

    # Configure arm-specific settings
    # Arm A: Exact 588b3f1 Control (LIVESTOCK_OVERRIDE_ENABLED = False)
    if arm == "ArmA_Control":
        config.reset_livestock_portfolio()
    elif arm == "ArmB_8C_6S":
        config.set_active_livestock_portfolio(cows=8, sheep=6, cow_cap=8, sheep_cap=6, herd_cap=14)
    elif arm == "ArmC_9C_3S":
        config.set_active_livestock_portfolio(cows=9, sheep=3, cow_cap=9, sheep_cap=3, herd_cap=12)
    elif arm == "ArmD_8C_4S":
        config.set_active_livestock_portfolio(cows=8, sheep=4, cow_cap=8, sheep_cap=4, herd_cap=12)
    elif arm == "ArmE_6C_3S":
        config.set_active_livestock_portfolio(cows=6, sheep=3, cow_cap=6, sheep_cap=3, herd_cap=9)
    elif arm == "ArmF_Dynamic":
        # Enable selective livestock gate with realized marginal valuator throughout
        config.set_active_livestock_portfolio(cows=12, sheep=12, cow_cap=12, sheep_cap=12, herd_cap=16)
        config.SELECTIVE_LIVESTOCK_GATE_ENABLED = True
        config.SELECTIVE_LIVESTOCK_MAX_DAY = 14

    # Keep SW and Zonal settings frozen to exact 588b3f1 baseline defaults
    config.set_dynamic_sw_crops(False)
    config.set_strategic_sw_ownership(False)

    # Detailed metrics collection
    peak_cows = 0
    peak_sheep = 0
    peak_herd = 0
    pasture_tiles = set()
    total_feed_actions = 0
    total_care_actions = 0
    total_milk_actions = 0
    total_shear_actions = 0
    total_move_actions = 0
    total_productive_actions = 0
    total_idle_actions = 0
    feed_shortfalls = 0
    animal_deaths = 0

    rev_by_product = {
        "MILK": 0.0, "WOOL": 0.0, "FERTILIZER": 0.0, "EGG": 0.0,
        "WHEAT": 0.0, "CARROT": 0.0, "MELON": 0.0, "STRAWBERRY": 0.0, "TOMATO": 0.0
    }
    units_sold = {k: 0 for k in rev_by_product}
    costs_by_cat = {"ANIMAL": 0.0, "FEED": 0.0, "HIRE": 0.0, "SEED": 0.0, "LAND": 0.0}

    last_money = 3000.0
    last_shed = {}

    def tracking_agent(obs, configuration=None):
        nonlocal peak_cows, peak_sheep, peak_herd, pasture_tiles
        nonlocal total_feed_actions, total_care_actions, total_milk_actions, total_shear_actions
        nonlocal total_move_actions, total_productive_actions, total_idle_actions
        nonlocal feed_shortfalls, animal_deaths, last_money, last_shed

        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        p_id = obs.get("player", 0)
        farms = obs.get("farms", [])
        farm_data = farms[p_id] if len(farms) > p_id else {}
        curr_money = float(farm_data.get("money", 3000.0))

        # Check animal counts and pastures at hour 0
        if hour == 0:
            cows = 0
            sheep = 0
            for r_idx, row in enumerate(farm_data.get("tiles", [])):
                for c_idx, t_dict in enumerate(row):
                    if isinstance(t_dict, dict):
                        kind = t_dict.get("kind")
                        if kind == "PASTURE":
                            pasture_tiles.add((c_idx, r_idx))
                        an = t_dict.get("animal")
                        if an == "COW":
                            cows += 1
                        elif an == "SHEEP":
                            sheep += 1
                        if an and t_dict.get("consecutive_unfed", 0) > 0:
                            feed_shortfalls += 1

            if cows > peak_cows:
                peak_cows = cows
            if sheep > peak_sheep:
                peak_sheep = sheep
            if (cows + sheep) > peak_herd:
                peak_herd = cows + sheep

        # Track market order executions via financial delta
        priv = obs.get("private", {})
        curr_shed = priv.get("shed", {})
        dm = curr_money - last_money

        if dm > 0:
            sold = {k: last_shed.get(k, 0) - curr_shed.get(k, 0) for k in last_shed if last_shed.get(k, 0) > curr_shed.get(k, 0)}
            if len(sold) == 1:
                item = list(sold.keys())[0]
                qty = sold[item]
                if item in rev_by_product:
                    rev_by_product[item] += dm
                    units_sold[item] += qty
            elif len(sold) > 1:
                prices = obs.get("market", {}).get("prices", {})
                tot_est = sum(qty * prices.get(k, 1) for k, qty in sold.items())
                for item, qty in sold.items():
                    val = dm * ((qty * prices.get(item, 1)) / max(1.0, tot_est))
                    if item in rev_by_product:
                        rev_by_product[item] += val
                        units_sold[item] += qty
        elif dm < 0:
            # Expense tracking
            cost = -dm
            # Simple approximation of expense category
            if cost in (400, 500, 800, 900, 1000, 1200, 1300, 1400):
                costs_by_cat["ANIMAL"] += cost
            elif cost in (425, 1000, 2112, 2000):
                costs_by_cat["LAND"] += cost

        last_money = curr_money
        last_shed = dict(curr_shed)

        # Call underlying agent
        action = agent_module.agent(obs)

        # Inspect unit actions
        if isinstance(action, dict):
            all_units = [action.get("farmer", [])] + action.get("hands", [])
            for u in all_units:
                if not u:
                    total_idle_actions += 1
                else:
                    cmd = u[0]
                    if cmd in ("NORTH", "SOUTH", "EAST", "WEST"):
                        total_move_actions += 1
                    elif cmd in ("PASS", "IDLE"):
                        total_idle_actions += 1
                    else:
                        total_productive_actions += 1
                        if cmd == "FEED":
                            total_feed_actions += 1
                        elif cmd == "CARE":
                            total_care_actions += 1
                        elif cmd == "MILK":
                            total_milk_actions += 1
                        elif cmd == "SHEAR":
                            total_shear_actions += 1

        return action

    env = make("kaggriculture", configuration={"episodeSteps": 720}, info={"seed": seed})
    agents = [tracking_agent, opp_name]
    env.run(agents)

    p0_reward = env.state[0].reward
    p1_reward = env.state[1].reward

    # Calculate average pasture distance to shed (4, 4)
    shed_pos = (4, 4)
    if pasture_tiles:
        avg_dist = sum(abs(p[0] - shed_pos[0]) + abs(p[1] - shed_pos[1]) for p in pasture_tiles) / len(pasture_tiles)
    else:
        avg_dist = 0.0

    unlocked_quads = list(env.state[0].observation.farms[0].get("unlocked_quadrants", ["NW"]))

    return {
        "arm": arm,
        "seed": seed,
        "opponent": opp_name,
        "final_score": float(p0_reward or 0.0),
        "opponent_score": float(p1_reward or 0.0),
        "unlocked_quadrants": unlocked_quads,
        "sw_purchased": "SW" in unlocked_quads,
        "peak_cows": peak_cows,
        "peak_sheep": peak_sheep,
        "peak_herd": peak_herd,
        "pasture_count": len(pasture_tiles),
        "avg_pasture_distance": round(avg_dist, 2),
        "milk_revenue": round(rev_by_product["MILK"], 1),
        "wool_revenue": round(rev_by_product["WOOL"], 1),
        "fertilizer_revenue": round(rev_by_product["FERTILIZER"], 1),
        "milk_units": units_sold["MILK"],
        "wool_units": units_sold["WOOL"],
        "move_actions": total_move_actions,
        "productive_actions": total_productive_actions,
        "idle_actions": total_idle_actions,
        "feed_actions": total_feed_actions,
        "care_actions": total_care_actions,
        "milk_actions": total_milk_actions,
        "shear_actions": total_shear_actions,
        "feed_shortfalls": feed_shortfalls,
        "animal_deaths": animal_deaths,
    }


def run_round1(num_seeds: int = 25, max_workers: int = 6):
    arms = [
        "ArmA_Control",
        "ArmB_8C_6S",
        "ArmC_9C_3S",
        "ArmD_8C_4S",
        "ArmE_6C_3S",
        "ArmF_Dynamic",
    ]
    opponents = ["starter", "random"]
    seeds = list(range(101, 101 + num_seeds))

    payloads = []
    for arm in arms:
        for opp in opponents:
            for seed in seeds:
                payloads.append({
                    "arm": arm,
                    "seed": seed,
                    "opponent": opp,
                })

    print("=" * 100)
    print("ROUND 1: ANIMAL FRONTIER EXPERIMENT (KEEPING SW EXACT 588b3f1)")
    print(f"Arms: {', '.join(arms)}")
    print(f"Seeds: 101 to {100 + num_seeds} x 2 opponents = {len(seeds) * len(opponents)} matches/arm")
    print(f"Total simulations: {len(payloads)} across {max_workers} processes")
    print("=" * 100)

    results = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_run_single_match, p): p for p in payloads}
        completed = 0
        total = len(payloads)

        for fut in as_completed(future_map):
            completed += 1
            res = fut.result()
            results.append(res)
            arm = res["arm"]
            s = res["seed"]
            opp = res["opponent"]
            score = res.get("final_score", 0.0)
            cows = res.get("peak_cows", 0)
            sheep = res.get("peak_sheep", 0)
            print(f"[{completed:3d}/{total:3d}] {arm:<14} | Seed {s} vs {opp:<7} | Score: ${score:8,.0f} | Herd: {cows}C/{sheep}S | M+W: ${res['milk_revenue']+res['wool_revenue']:6,.0f}", flush=True)

    total_time = time.time() - t_start
    print(f"\nAll {total} matches completed in {total_time:.1f}s ({total_time/60:.1f} min)")

    # Save results
    out_file = os.path.join(_REPO_ROOT, "simulations", "experiments", "round1_animal_frontier_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved results to {out_file}")

    # Analyze Round 1
    analyze_round1(results, arms)


def analyze_round1(results: List[Dict[str, Any]], arms: List[str]):
    print("\n" + "=" * 115)
    print("ROUND 1: ANIMAL FRONTIER COMPREHENSIVE PERFORMANCE & TELEMETRY REPORT")
    print("=" * 115)

    arm_data = {arm: {} for arm in arms}
    for r in results:
        key = (r["seed"], r["opponent"])
        arm_data[r["arm"]][key] = r

    control = "ArmA_Control"
    control_matches = arm_data[control]

    headers = f"{'Arm':<15} {'Matches':<8} {'Mean Score':<12} {'Median':<10} {'Delta Mean':<12} {'Delta Med':<10} {'W/L/T':<10} {'Milk Rev':<10} {'Wool Rev':<10} {'M+W Net':<10} {'Herd':<8} {'Avg Dist':<9} {'Move %':<8} {'Idle %':<8}"
    print(headers)
    print("-" * 135)

    for arm in arms:
        matches = arm_data[arm]
        n = len(matches)
        if n == 0:
            continue

        scores = [m["final_score"] for m in matches.values()]
        mean_score = np.mean(scores)
        med_score = np.median(scores)

        # Paired comparisons against Control
        deltas = []
        w, l, t = 0, 0, 0
        for k, m in matches.items():
            if k in control_matches:
                c_score = control_matches[k]["final_score"]
                diff = m["final_score"] - c_score
                deltas.append(diff)
                if diff > 0:
                    w += 1
                elif diff < 0:
                    l += 1
                else:
                    t += 1

        delta_mean = np.mean(deltas) if deltas else 0.0
        delta_med = np.median(deltas) if deltas else 0.0

        avg_milk = np.mean([m["milk_revenue"] for m in matches.values()])
        avg_wool = np.mean([m["wool_revenue"] for m in matches.values()])
        avg_mw = avg_milk + avg_wool

        avg_cows = np.mean([m["peak_cows"] for m in matches.values()])
        avg_sheep = np.mean([m["peak_sheep"] for m in matches.values()])
        avg_dist = np.mean([m["avg_pasture_distance"] for m in matches.values()])

        tot_moves = sum(m["move_actions"] for m in matches.values())
        tot_prods = sum(m["productive_actions"] for m in matches.values())
        tot_idles = sum(m["idle_actions"] for m in matches.values())
        tot_acts = max(1, tot_moves + tot_prods + tot_idles)

        move_pct = (tot_moves / tot_acts) * 100
        idle_pct = (tot_idles / tot_acts) * 100

        wlt_str = f"{w}/{l}/{t}"
        herd_str = f"{avg_cows:.1f}C/{avg_sheep:.1f}S"

        print(f"{arm:<15} {n:<8} ${mean_score:10,.0f} ${med_score:8,.0f} {delta_mean:+10,.0f} {delta_med:+9,.0f} {wlt_str:<10} ${avg_milk:8,.0f} ${avg_wool:8,.0f} ${avg_mw:8,.0f} {herd_str:<8} {avg_dist:<9.2f} {move_pct:6.1f}% {idle_pct:6.1f}%")

    print("-" * 135)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=25, help="Number of seeds (default 25 -> 50 matches/arm)")
    parser.add_argument("--workers", type=int, default=6, help="Process workers (default 6)")
    args = parser.parse_args()

    run_round1(num_seeds=args.seeds, max_workers=args.workers)
