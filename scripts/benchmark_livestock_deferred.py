"""Comprehensive 50-Pair (100-match) Paired Benchmark: Baseline (7e48337) vs Candidate (Dynamic Pastures + Deferred Livestock Fix).

Isolates pasture/livestock changes under identical CentralPlanner arbitration:
    Both arms run under: historical_candidates_central
    Baseline: 7e48337 behavior (static SW 9-pasture ceiling + SW tile withholding + SW gate in reinvest_livestock)
    Candidate: dynamic near-shed pasture capacity + deferred livestock fix (hours 2-18)
    Population: seeds 101-125, opponents random + starter (50 paired scenarios = 100 matches)
"""
import os
import sys
import json
import time
import argparse
import copy
from typing import Dict, Any, List, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

# Ensure repository paths
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")

for p in (_REPO_ROOT, _AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)
for sub in ("state", "strategy", "execution", "market"):
    sub_p = os.path.join(_AGENT_DIR, sub)
    if sub_p not in sys.path:
        sys.path.insert(0, sub_p)


def _worker_run_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Isolated worker process for running one match."""
    seed = payload["seed"]
    opponent_name = payload["opponent"]
    arm = payload["arm"]  # "baseline" or "candidate"
    repo_root = payload["repo_root"]
    agent_dir = payload["agent_dir"]

    for p in (repo_root, agent_dir):
        if p not in sys.path:
            sys.path.insert(0, p)
    for sub in ("state", "strategy", "execution", "market"):
        sub_p = os.path.join(agent_dir, sub)
        if sub_p not in sys.path:
            sys.path.insert(0, sub_p)

    from kaggle_environments import make
    import main as agent_module
    import market.order_builder as ob_mod
    import strategy.macro_planner as mp_mod

    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")

    # If baseline, inject 7e48337 behavior into worker process
    if arm == "baseline":
        # 1. Old reinvest_livestock gate: requires "SW" in farm.unlocked
        def baseline_reinvest(self, ctx, intents, max_slots=ob_mod.MAX_MARKET_ORDERS):
            if (ctx["day"] >= ob_mod.C4_LIVESTOCK_CUTOFF_DAY
                    or not 2 <= ctx["hour"] <= 18
                    or "SW" not in ctx["farm"].unlocked
                    or not intents.get("buy_animal")):
                return [], {}
            return self.build(ctx, {
                "buy_animal": intents["buy_animal"],
                "buy_wheat": intents.get("buy_wheat", 0),
                "pending_structures": intents.get("pending_structures", {}),
            }, max_slots=max_slots)
        ob_mod.OrderBuilder.reinvest_livestock = baseline_reinvest

        # 2. Old static pasture evaluation: min(9, SW_PASTURE_TILES)
        SW_PASTURE_TILES = [(1, 8), (1, 9), (2, 7), (2, 8), (2, 9), (3, 7), (3, 8), (4, 7), (4, 8)]
        def baseline_eval_pastures(farm, day, empty_tiles, current_animals, crop_opportunity_val=0.0, crop_name="NONE", cutoff_day=12):
            existing = sum(1 for t in farm.iter_tiles() if t.kind == "PASTURE")
            empty_count = sum(1 for t in farm.iter_tiles() if t.kind in ("COOP", "PASTURE") and not t.is_animal)
            sw_avail = [p for p in SW_PASTURE_TILES if p in empty_tiles]
            dynamic_max = min(len(SW_PASTURE_TILES), 9)
            return {
                "existing_pastures": existing,
                "existing_empty_pastures": empty_count,
                "dynamic_max_pastures": min(9, dynamic_max),
                "positive_candidates": [{"pos": p, "net_value": 100.0} for p in sw_avail],
            }
        import strategy.pasture_planner as pp_mod
        pp_mod.evaluate_pasture_candidates = baseline_eval_pastures

    # Opponent resolution
    if opponent_name in ("random", "pass", "starter"):
        opp = opponent_name
    else:
        try:
            from simulations.experiments.agent_zoo import get_agent
            opp = get_agent(opponent_name)
        except Exception:
            opp = "random"

    # Match tracking
    KEY_DAYS = [0, 5, 10, 11, 12, 15, 20, 28]
    day_metrics = {
        d: {
            "cows": 0, "sheep": 0, "geese": 0, "total_herd": 0,
            "pastures": 0, "empty_pastures": 0, "dynamic_cap": 0, "feed_cap": 0,
            "wheat_stock": 0,
        }
        for d in KEY_DAYS
    }

    stats = {
        "peak_herd": 0,
        "day_peak_herd": 0,
        "animal_purchases_attempted": 0,
        "animal_purchases_executed": 0,
        "animals_placed": 0,
        "animal_purchase_spend": 0.0,
        "wheat_purchase_spend": 0.0,
        "feed_failures": 0,
        "care_actions": 0,
        "feed_actions": 0,
        "fert_collections": 0,
        "milk_sold": 0,
        "wool_sold": 0,
        "fert_sold": 0,
        "fert_revenue": 0.0,
        "livestock_revenue": 0.0,
    }

    def tracking_agent(obs, config=None):
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)

        act = agent_module.agent(obs, config)
        tel = agent_module.get_last_turn_telemetry()

        # Check market orders in action
        m_orders = act.get("market", []) if isinstance(act, dict) else []
        for o in m_orders:
            if not isinstance(o, (list, tuple)) or not o:
                continue
            op = o[0]
            if op == "BUY_ANIMAL" and len(o) >= 3:
                anim, n = o[1], int(o[2])
                stats["animal_purchases_executed"] += n
                cost = 400.0 if anim == "COW" else (500.0 if anim == "SHEEP" else 300.0)
                stats["animal_purchase_spend"] += cost * n
            elif op == "BUY_PRODUCT" and len(o) >= 3 and o[1] == "WHEAT":
                stats["wheat_purchase_spend"] += 25.0 * int(o[2])
            elif op == "SELL" and len(o) >= 3:
                prod, n = o[1], int(o[2])
                if prod == "MILK":
                    stats["milk_sold"] += n
                    stats["livestock_revenue"] += 160.0 * n
                elif prod == "WOOL":
                    stats["wool_sold"] += n
                    stats["livestock_revenue"] += 200.0 * n
                elif prod == "FERTILIZER":
                    stats["fert_sold"] += n
                    stats["fert_revenue"] += 100.0 * n

        # Check purchase proposals in telemetry
        if tel and tel.get("purchase_orders"):
            for o in tel["purchase_orders"]:
                if o and o[0] == "BUY_ANIMAL" and len(o) >= 3:
                    stats["animal_purchases_attempted"] += int(o[2])

        # Check worker actions
        for u_key in ("farmer", "hands"):
            u_acts = act.get(u_key, [])
            if u_key == "farmer":
                u_acts = [u_acts] if u_acts and isinstance(u_acts[0], str) else u_acts
            for act_list in u_acts:
                for a in (act_list if isinstance(act_list, list) else [act_list]):
                    if a == "FEED": stats["feed_actions"] += 1
                    elif a == "CARE": stats["care_actions"] += 1
                    elif a == "COLLECT_FERTILIZER": stats["fert_collections"] += 1
                    elif a == "PLACE": stats["animals_placed"] += 1

        # Check farm state
        p_id = obs.get("player", 0)
        farm = obs.get("farms", [])[p_id]
        priv = obs.get("private", {})
        shed = priv.get("shed", {})
        tiles = farm.get("tiles", [])

        c_cnt, s_cnt, g_cnt, p_cnt, ep_cnt = 0, 0, 0, 0, 0
        for row in tiles:
            for t in row:
                if isinstance(t, dict):
                    if t.get("kind") == "PASTURE":
                        p_cnt += 1
                        if t.get("animal") is None:
                            ep_cnt += 1
                    if t.get("animal") == "COW": c_cnt += 1
                    elif t.get("animal") == "SHEEP": s_cnt += 1
                    elif t.get("animal") == "GOOSE": g_cnt += 1
                    if t.get("is_starving"):
                        stats["feed_failures"] += 1

        tot_herd = c_cnt + s_cnt + g_cnt
        if tot_herd > stats["peak_herd"]:
            stats["peak_herd"] = tot_herd
            stats["day_peak_herd"] = day

        if hour == 0 and day in KEY_DAYS:
            # Capture feed cap and dynamic cap from last macro plan if available
            dyn_cap = 0
            feed_cap = 0
            if tel and tel.get("central_planner_diagnostic"):
                cp_d = tel["central_planner_diagnostic"]
                dyn_cap = cp_d.get("dynamic_pastures", 0)
            
            day_metrics[day] = {
                "cows": c_cnt, "sheep": s_cnt, "geese": g_cnt, "total_herd": tot_herd,
                "pastures": p_cnt, "empty_pastures": ep_cnt, "dynamic_cap": dyn_cap,
                "feed_cap": feed_cap, "wheat_stock": shed.get("WHEAT", 0),
            }

        return act

    env = make(
        "kaggriculture",
        configuration={"seed": seed, "episodeSteps": 720},
        debug=False,
    )
    env.run([tracking_agent, opp])

    final_obs = env.steps[-1][0]["observation"]
    p_id = final_obs.get("player", 0)
    final_money = float(final_obs["farms"][p_id]["money"])
    opp_money = float(final_obs["farms"][1 - p_id]["money"])

    return {
        "seed": seed,
        "opponent": opponent_name,
        "arm": arm,
        "final_money": final_money,
        "opponent_money": opp_money,
        "margin": final_money - opp_money,
        "win": final_money > opp_money,
        "day_metrics": day_metrics,
        "stats": stats,
    }


def run_paired_benchmark(seeds=range(101, 126), opponents=("random", "starter"), workers=4) -> Dict[str, Any]:
    tasks = []
    for seed in seeds:
        for opp in opponents:
            for arm in ("baseline", "candidate"):
                tasks.append({
                    "seed": seed,
                    "opponent": opp,
                    "arm": arm,
                    "repo_root": _REPO_ROOT,
                    "agent_dir": _AGENT_DIR,
                })

    print(f"Starting paired benchmark: {len(tasks)} matches ({len(tasks)//2} paired scenarios) on {workers} workers...")
    t0 = time.time()
    results = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_worker_run_match, t): t for t in tasks}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == len(tasks):
                print(f"Completed {completed}/{len(tasks)} matches ({completed*100//len(tasks)}%) in {time.time()-t0:.1f}s")

    elapsed = time.time() - t0
    print(f"Benchmark finished in {elapsed:.1f}s.")
    return analyze_results(results, list(seeds), list(opponents))


def analyze_results(results: List[Dict[str, Any]], seeds: List[int], opponents: List[str]) -> Dict[str, Any]:
    by_arm = {"baseline": [], "candidate": []}
    by_pair = {}

    for r in results:
        arm = r["arm"]
        by_arm[arm].append(r)
        pair_key = (r["seed"], r["opponent"])
        by_pair.setdefault(pair_key, {})[arm] = r

    # Compute summary stats for baseline and candidate
    summaries = {}
    for arm in ("baseline", "candidate"):
        moneys = [r["final_money"] for r in by_arm[arm]]
        sorted_m = sorted(moneys)
        b10 = sorted_m[:max(1, len(sorted_m)//10)]
        summaries[arm] = {
            "mean": float(np.mean(moneys)),
            "median": float(np.median(moneys)),
            "std": float(np.std(moneys)),
            "min": float(np.min(moneys)),
            "max": float(np.max(moneys)),
            "bottom_10_mean": float(np.mean(b10)),
        }

    # Compute paired deltas (Candidate - Baseline)
    deltas = []
    wins = 0
    losses = 0
    ties = 0

    for pair_key, pair_dict in by_pair.items():
        if "baseline" in pair_dict and "candidate" in pair_dict:
            b_m = pair_dict["baseline"]["final_money"]
            c_m = pair_dict["candidate"]["final_money"]
            d = c_m - b_m
            deltas.append(d)
            if d > 0: wins += 1
            elif d < 0: losses += 1
            else: ties += 1

    sorted_d = sorted(deltas)
    b10_d = sorted_d[:max(1, len(sorted_d)//10)]
    paired_analysis = {
        "mean_delta": float(np.mean(deltas)) if deltas else 0.0,
        "median_delta": float(np.median(deltas)) if deltas else 0.0,
        "std_delta": float(np.std(deltas)) if deltas else 0.0,
        "min_delta": float(np.min(deltas)) if deltas else 0.0,
        "max_delta": float(np.max(deltas)) if deltas else 0.0,
        "bottom_10_mean_delta": float(np.mean(b10_d)) if deltas else 0.0,
        "wins": wins,
        "losses": losses,
        "ties": ties,
    }

    # Aggregate trajectory metrics
    KEY_DAYS = [0, 5, 10, 11, 12, 15, 20, 28]
    traj_summary = {}
    for arm in ("baseline", "candidate"):
        runs = by_arm[arm]
        traj_summary[arm] = {}
        for d in KEY_DAYS:
            cows = np.mean([r["day_metrics"][d]["cows"] for r in runs])
            sheep = np.mean([r["day_metrics"][d]["sheep"] for r in runs])
            geese = np.mean([r["day_metrics"][d]["geese"] for r in runs])
            herd = np.mean([r["day_metrics"][d]["total_herd"] for r in runs])
            past = np.mean([r["day_metrics"][d]["pastures"] for r in runs])
            epast = np.mean([r["day_metrics"][d]["empty_pastures"] for r in runs])
            wstock = np.mean([r["day_metrics"][d]["wheat_stock"] for r in runs])
            traj_summary[arm][d] = {
                "cows": round(float(cows), 2),
                "sheep": round(float(sheep), 2),
                "geese": round(float(geese), 2),
                "total_herd": round(float(herd), 2),
                "pastures": round(float(past), 2),
                "empty_pastures": round(float(epast), 2),
                "wheat_stock": round(float(wstock), 1),
            }

    # Aggregate operational & livestock metrics
    ops_summary = {}
    for arm in ("baseline", "candidate"):
        runs = by_arm[arm]
        ops_summary[arm] = {
            "peak_herd": round(float(np.mean([r["stats"]["peak_herd"] for r in runs])), 2),
            "day_peak_herd": round(float(np.mean([r["stats"]["day_peak_herd"] for r in runs])), 1),
            "purchases_attempted": round(float(np.mean([r["stats"]["animal_purchases_attempted"] for r in runs])), 1),
            "purchases_executed": round(float(np.mean([r["stats"]["animal_purchases_executed"] for r in runs])), 1),
            "animals_placed": round(float(np.mean([r["stats"]["animals_placed"] for r in runs])), 1),
            "animal_spend": round(float(np.mean([r["stats"]["animal_purchase_spend"] for r in runs])), 1),
            "wheat_spend": round(float(np.mean([r["stats"]["wheat_purchase_spend"] for r in runs])), 1),
            "milk_sold": round(float(np.mean([r["stats"]["milk_sold"] for r in runs])), 1),
            "wool_sold": round(float(np.mean([r["stats"]["wool_sold"] for r in runs])), 1),
            "fert_sold": round(float(np.mean([r["stats"]["fert_sold"] for r in runs])), 1),
            "livestock_revenue": round(float(np.mean([r["stats"]["livestock_revenue"] for r in runs])), 1),
            "fert_revenue": round(float(np.mean([r["stats"]["fert_revenue"] for r in runs])), 1),
            "care_actions": round(float(np.mean([r["stats"]["care_actions"] for r in runs])), 1),
            "feed_actions": round(float(np.mean([r["stats"]["feed_actions"] for r in runs])), 1),
            "fert_collections": round(float(np.mean([r["stats"]["fert_collections"] for r in runs])), 1),
            "feed_failures": int(sum(r["stats"]["feed_failures"] for r in runs)),
        }

    return {
        "summaries": summaries,
        "paired_analysis": paired_analysis,
        "trajectories": traj_summary,
        "operational": ops_summary,
        "raw_results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seeds", type=int, default=25)
    parser.add_argument("--start-seed", type=int, default=101)
    args = parser.parse_args()

    seed_range = range(args.start_seed, args.start_seed + args.seeds)
    res = run_paired_benchmark(seeds=seed_range, opponents=("random", "starter"), workers=args.workers)

    # Save artifacts
    artifacts_dir = os.path.join(_REPO_ROOT, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    json_path = os.path.join(artifacts_dir, "pasture_deferred_fix_ab.json")
    with open(json_path, "w") as f:
        json.dump(res, f, indent=2)

    # Print Report
    s = res["summaries"]
    p = res["paired_analysis"]
    print("\n" + "=" * 90)
    print("        ISOLATED LIVESTOCK BENCHMARK: BASELINE (7e48337) vs CANDIDATE        ")
    print("=" * 90)
    print(f"{'Arm':<20} | {'Mean':>10} | {'Median':>10} | {'Std':>8} | {'Min':>10} | {'Max':>10} | {'B10 Mean':>10}")
    print("-" * 90)
    print(f"{'Baseline (7e48337)':<20} | ${s['baseline']['mean']:>9,.2f} | ${s['baseline']['median']:>9,.2f} | ${s['baseline']['std']:>7,.2f} | ${s['baseline']['min']:>9,.2f} | ${s['baseline']['max']:>9,.2f} | ${s['baseline']['bottom_10_mean']:>9,.2f}")
    print(f"{'Candidate (Fix)':<20} | ${s['candidate']['mean']:>9,.2f} | ${s['candidate']['median']:>9,.2f} | ${s['candidate']['std']:>7,.2f} | ${s['candidate']['min']:>9,.2f} | ${s['candidate']['max']:>9,.2f} | ${s['candidate']['bottom_10_mean']:>9,.2f}")
    print("-" * 90)
    print(f"Paired Delta (Candidate - Baseline): Mean ${p['mean_delta']:>+,.2f} | Median ${p['median_delta']:>+,.2f} | B10 Mean ${p['bottom_10_mean_delta']:>+,.2f}")
    print(f"Delta Range: Min ${p['min_delta']:>+,.2f} | Max ${p['max_delta']:>+,.2f}")
    print(f"Win / Loss / Tie: {p['wins']} / {p['losses']} / {p['ties']}")
    print("=" * 90)
