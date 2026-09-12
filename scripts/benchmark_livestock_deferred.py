"""Comprehensive 50-Pair (100-match) Paired Benchmark: Baseline (7e48337) vs Candidate.

Executes both arms in isolated subprocesses using real repository checkouts:
    Baseline: real worktree at .worktrees/baseline_7e48337 (commit 7e48337)
    Candidate: current working tree (dedc341 + marginal valuation & ranking fixes)
    Both arms run under: historical_candidates_central
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

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORKTREE_DIR = os.path.join(_REPO_ROOT, ".worktrees", "baseline_7e48337")
_BASELINE_AGENT_DIR = os.path.join(_WORKTREE_DIR, "agent")
_CANDIDATE_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
KEY_DAYS = [0, 5, 10, 11, 12, 15, 20, 28]


def run_preflight_sanity_assertions():
    """Verify that baseline and candidate environments behave with literal fidelity."""
    print("Running pre-flight sanity assertions...")
    
    assert os.path.isdir(_BASELINE_AGENT_DIR), f"Baseline worktree missing at {_BASELINE_AGENT_DIR}"
    assert os.path.isdir(_CANDIDATE_AGENT_DIR), f"Candidate agent missing at {_CANDIDATE_AGENT_DIR}"
    
    # 1. Baseline assertions
    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner'
    ))]
    for k in to_delete:
        del sys.modules[k]
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [_BASELINE_AGENT_DIR] + [os.path.join(_BASELINE_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    import main as b_main
    from observation_parser import parse_observation
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast
    from market.order_builder import OrderBuilder
    import config as b_cfg

    # Ensure baseline does NOT have pasture_planner
    try:
        import strategy.pasture_planner
        raise AssertionError("Baseline worktree must not contain strategy.pasture_planner")
    except ImportError:
        pass

    fc = PriceForecast.load()
    planner = MacroPlanner(fc)

    # Baseline Day 0 before SW: max_pastures <= 2
    obs_day0 = {
        'player': 0, 'day': 0, 'hour': 0,
        'farms': [{'money': 5000.0, 'tiles': [[None]*10]*10, 'farmer': [4,4], 'hands': [[4,4]]*4, 'unlocked_quadrants': ['NW'], 'hires_today': 0}]*2,
        'market': {'inventory': {}, 'prices': {}}, 'town': {'unlocked_shops': []},
        'private': {'shed': {'WHEAT': 50}, 'seeds': {}, 'inventories': [{}]}
    }
    ctx0 = parse_observation(obs_day0)
    plan0 = planner.build(ctx0)
    empty_t0 = [(t.x, t.y) for t in ctx0["farm"].iter_tiles() if t.kind == "EMPTY"]
    early_cands = [t for t in empty_t0 if t in b_cfg.EARLY_PASTURE_TILES]
    b_max_p0 = min(len(b_cfg.EARLY_PASTURE_TILES), len(early_cands))
    assert b_max_p0 <= 2, f"Baseline max_pastures before SW must be <= 2, got {b_max_p0}"

    # Baseline Day 10 after SW: global max_pastures <= 9
    obs_day10 = copy.deepcopy(obs_day0)
    obs_day10['day'] = 10
    obs_day10['farms'][0]['unlocked_quadrants'] = ['NW', 'NE', 'SW']
    ctx10 = parse_observation(obs_day10)
    empty_t10 = [(t.x, t.y) for t in ctx10["farm"].iter_tiles() if t.kind == "EMPTY"]
    sw_cands = [t for t in empty_t10 if t in b_cfg.SW_PASTURE_TILES]
    b_max_p10 = min(9, len(sw_cands))
    assert b_max_p10 <= 9, f"Baseline global max_pastures must be <= 9, got {b_max_p10}"

    # Baseline reinvest_livestock before SW must return empty
    ctx_reinvest_base = parse_observation(obs_day0)
    ctx_reinvest_base['hour'] = 5
    ob_base = OrderBuilder()
    base_orders, _ = ob_base.reinvest_livestock(ctx_reinvest_base, {'buy_animal': {'COW': 1}})
    assert len(base_orders) == 0, f"Baseline reinvest before SW must return empty, got {base_orders}"

    # 2. Candidate assertions
    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner'
    ))]
    for k in to_delete:
        del sys.modules[k]
    sys.path = [_CANDIDATE_AGENT_DIR] + [os.path.join(_CANDIDATE_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    import main as c_main
    from observation_parser import parse_observation
    from market.order_builder import OrderBuilder

    # Candidate with empty pasture in NW allows BUY_ANIMAL during hours 2-18 without SW
    obs_cand = copy.deepcopy(obs_day0)
    obs_cand['day'] = 11
    obs_cand['hour'] = 5
    obs_cand['farms'][0]['unlocked_quadrants'] = ['NW', 'NE']
    cand_tiles = [[None for _ in range(10)] for _ in range(10)]
    cand_tiles[3][4] = {'kind': 'PASTURE', 'x': 4, 'y': 3, 'is_animal': False}
    obs_cand['farms'][0]['tiles'] = cand_tiles
    ctx_cand = parse_observation(obs_cand)
    ob_cand = OrderBuilder()
    cand_orders, _ = ob_cand.reinvest_livestock(ctx_cand, {'buy_animal': {'COW': 1}})
    assert len(cand_orders) > 0, "Candidate reinvest must allow BUY_ANIMAL with valid NW pasture"

    print("Sanity assertions passed: baseline and candidate fidelity confirmed.")


def _worker_run_match(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Isolated worker process for running one match."""
    seed = payload["seed"]
    opponent_name = payload["opponent"]
    arm = payload["arm"]  # "baseline" or "candidate"
    
    agent_dir = _BASELINE_AGENT_DIR if arm == "baseline" else _CANDIDATE_AGENT_DIR

    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner'
    ))]
    for k in to_delete:
        del sys.modules[k]

    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    from kaggle_environments import make
    import main as agent_module
    import config as arm_config

    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")

    # Opponent resolution
    if opponent_name in ("random", "pass", "starter"):
        opp = opponent_name
    else:
        try:
            from simulations.experiments.agent_zoo import get_agent
            opp = get_agent(opponent_name)
        except Exception:
            opp = "random"

    KEY_DAYS = [0, 5, 10, 11, 12, 15, 20, 28]
    day_metrics = {
        d: {
            "cows": 0, "sheep": 0, "geese": 0, "total_herd": 0,
            "pastures": 0, "empty_pastures": 0, "dynamic_cap": 0, "feed_cap": 0,
            "effective_cap": 0, "wheat_stock": 0,
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

        # Strict baseline assertion: pastures must never exceed 9
        if arm == "baseline" and p_cnt > 9:
            raise RuntimeError(f"Baseline pasture ceiling violated: {p_cnt} > 9")

        tot_herd = c_cnt + s_cnt + g_cnt
        if tot_herd > stats["peak_herd"]:
            stats["peak_herd"] = tot_herd
            stats["day_peak_herd"] = day

        if hour == 0 and day in KEY_DAYS:
            ctx = agent_module.parse_observation(obs)
            dyn_cap = 0
            feed_cap = 0
            eff_cap = 0
            if agent_module._PLANNER is not None and ctx is not None:
                plan = agent_module._PLANNER.build(ctx)
                if plan and plan.diagnostics:
                    p_diag = plan.diagnostics.get("pasture_diagnostics")
                    if p_diag:
                        dyn_cap = p_diag.get("dynamic_max_pastures", 0)
                        feed_cap = p_diag.get("feed_sustainable_cap", 0)
                        eff_cap = p_diag.get("effective_herd_cap", 0)
                    else:
                        feed_cap = plan.diagnostics.get("sustainable_herd_size", 0)
                        farm_obj = ctx["farm"]
                        empty_t = [(t.x, t.y) for t in farm_obj.iter_tiles() if t.kind == "EMPTY"]
                        sw_unlocked = "SW" in farm_obj.unlocked
                        if sw_unlocked:
                            sw_cands = [t for t in empty_t if t in arm_config.SW_PASTURE_TILES]
                            dyn_cap = min(9, p_cnt + len(sw_cands))
                        else:
                            early_cands = [t for t in empty_t if t in arm_config.EARLY_PASTURE_TILES]
                            dyn_cap = min(len(arm_config.EARLY_PASTURE_TILES), p_cnt + len(early_cands))
                        eff_cap = min(dyn_cap, feed_cap)

            if arm == "baseline":
                if day < 9 and dyn_cap > 2:
                    raise RuntimeError(f"Baseline capacity before SW violated: {dyn_cap} > 2 on Day {day}")
                if dyn_cap > 9:
                    raise RuntimeError(f"Baseline global capacity violated: {dyn_cap} > 9 on Day {day}")

            day_metrics[day] = {
                "cows": c_cnt, "sheep": s_cnt, "geese": g_cnt, "total_herd": tot_herd,
                "pastures": p_cnt, "empty_pastures": ep_cnt, "dynamic_cap": dyn_cap,
                "feed_cap": feed_cap, "effective_cap": eff_cap, "wheat_stock": shed.get("WHEAT", 0),
            }

        return act

    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=False,
    )
    env.run([tracking_agent, opp])
    state = env.state
    p0_reward = state[0].reward or 0.0
    p1_reward = state[1].reward or 0.0

    return {
        "seed": seed,
        "opponent": opponent_name,
        "arm": arm,
        "final_money": float(p0_reward),
        "opponent_money": float(p1_reward),
        "margin": float(p0_reward - p1_reward),
        "win": bool(p0_reward > p1_reward),
        "day_metrics": day_metrics,
        "stats": stats,
    }


def run_paired_benchmark(
    seeds: range = range(101, 126),
    opponents: Tuple[str, ...] = ("random", "starter"),
    workers: int = 4,
) -> Dict[str, Any]:
    """Run 50-pair (100-match) benchmark comparing Baseline (7e48337) and Candidate."""
    run_preflight_sanity_assertions()

    tasks = []
    for s in seeds:
        for opp in opponents:
            tasks.append({"seed": s, "opponent": opp, "arm": "baseline"})
            tasks.append({"seed": s, "opponent": opp, "arm": "candidate"})

    total = len(tasks)
    print(f"\nStarting isolated paired benchmark: {total} matches ({total//2} paired scenarios) on {workers} workers...")
    start_time = time.time()
    results = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_worker_run_match, t): t for t in tasks}
        completed = 0
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            completed += 1
            if completed % 10 == 0 or completed == total:
                elapsed = time.time() - start_time
                pct = completed / total * 100.0
                print(f"Completed {completed}/{total} matches ({pct:.0f}%) in {elapsed:.1f}s")

    print(f"Benchmark finished in {time.time() - start_time:.1f}s.")

    # Group by arm and by scenario pair
    by_arm = {"baseline": [], "candidate": []}
    by_pair = {}  # (seed, opponent) -> {"baseline": ..., "candidate": ...}

    for r in results:
        by_arm[r["arm"]].append(r)
        key = (r["seed"], r["opponent"])
        if key not in by_pair:
            by_pair[key] = {}
        by_pair[key][r["arm"]] = r

    # Compute individual arm summaries
    summaries = {}
    for arm in ("baseline", "candidate"):
        scores = [r["final_money"] for r in by_arm[arm]]
        sorted_s = sorted(scores)
        b10 = sorted_s[:max(1, len(sorted_s)//10)]
        summaries[arm] = {
            "mean": float(np.mean(scores)),
            "median": float(np.median(scores)),
            "std": float(np.std(scores)),
            "min": float(np.min(scores)),
            "max": float(np.max(scores)),
            "bottom_10_mean": float(np.mean(b10)),
        }

    # Compute paired deltas (Candidate - Baseline)
    deltas = []
    wins = 0
    losses = 0
    ties = 0

    opp_breakdown = {}
    for opp in opponents:
        opp_breakdown[opp] = {
            "baseline_scores": [],
            "candidate_scores": [],
            "deltas": [],
            "wins": 0, "losses": 0, "ties": 0,
        }

    for (s, opp), pair_dict in by_pair.items():
        if "baseline" in pair_dict and "candidate" in pair_dict:
            b_m = pair_dict["baseline"]["final_money"]
            c_m = pair_dict["candidate"]["final_money"]
            d = c_m - b_m
            deltas.append(d)
            if d > 0: wins += 1
            elif d < 0: losses += 1
            else: ties += 1

            opp_breakdown[opp]["baseline_scores"].append(b_m)
            opp_breakdown[opp]["candidate_scores"].append(c_m)
            opp_breakdown[opp]["deltas"].append(d)
            if d > 0: opp_breakdown[opp]["wins"] += 1
            elif d < 0: opp_breakdown[opp]["losses"] += 1
            else: opp_breakdown[opp]["ties"] += 1

    sorted_d = sorted(deltas)
    b10_d = sorted_d[:max(1, len(sorted_d)//10)]
    diff_of_medians = summaries["candidate"]["median"] - summaries["baseline"]["median"]
    median_of_deltas = float(np.median(deltas)) if deltas else 0.0

    paired_analysis = {
        "mean_delta": float(np.mean(deltas)) if deltas else 0.0,
        "median_of_paired_deltas": median_of_deltas,
        "difference_of_marginal_medians": diff_of_medians,
        "std_delta": float(np.std(deltas)) if deltas else 0.0,
        "min_delta": float(np.min(deltas)) if deltas else 0.0,
        "max_delta": float(np.max(deltas)) if deltas else 0.0,
        "bottom_10_mean_delta": float(np.mean(b10_d)) if deltas else 0.0,
        "wins": wins,
        "losses": losses,
        "ties": ties,
    }

    # Opponent analysis summary
    opp_summary = {}
    for opp, data in opp_breakdown.items():
        opp_summary[opp] = {
            "baseline_mean": float(np.mean(data["baseline_scores"])) if data["baseline_scores"] else 0.0,
            "candidate_mean": float(np.mean(data["candidate_scores"])) if data["candidate_scores"] else 0.0,
            "paired_mean_delta": float(np.mean(data["deltas"])) if data["deltas"] else 0.0,
            "wins": data["wins"],
            "losses": data["losses"],
            "ties": data["ties"],
        }

    # Aggregate trajectory metrics
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
            dcap = np.mean([r["day_metrics"][d]["dynamic_cap"] for r in runs])
            fcap = np.mean([r["day_metrics"][d]["feed_cap"] for r in runs])
            ecap = np.mean([r["day_metrics"][d]["effective_cap"] for r in runs])
            wstock = np.mean([r["day_metrics"][d]["wheat_stock"] for r in runs])
            traj_summary[arm][d] = {
                "cows": round(float(cows), 2),
                "sheep": round(float(sheep), 2),
                "geese": round(float(geese), 2),
                "total_herd": round(float(herd), 2),
                "pastures": round(float(past), 2),
                "empty_pastures": round(float(epast), 2),
                "dynamic_cap": round(float(dcap), 2),
                "feed_cap": round(float(fcap), 2),
                "effective_cap": round(float(ecap), 2),
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
            "animal_deaths": 0,
        }

    return {
        "summaries": summaries,
        "paired_analysis": paired_analysis,
        "opponents": opp_summary,
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
    json_path = os.path.join(artifacts_dir, "pasture_attribution_ab.json")
    with open(json_path, "w") as f:
        json.dump(res, f, indent=2)

    # Print Report
    s = res["summaries"]
    p = res["paired_analysis"]
    opp = res["opponents"]
    print("\n" + "=" * 90)
    print("        ISOLATED LIVESTOCK BENCHMARK: BASELINE (7e48337) vs CANDIDATE        ")
    print("=" * 90)
    print(f"{'Arm':<20} | {'Mean':>10} | {'Median':>10} | {'Std':>8} | {'Min':>10} | {'Max':>10} | {'B10 Mean':>10}")
    print("-" * 90)
    print(f"{'Baseline (7e48337)':<20} | ${s['baseline']['mean']:>9,.2f} | ${s['baseline']['median']:>9,.2f} | ${s['baseline']['std']:>7,.2f} | ${s['baseline']['min']:>9,.2f} | ${s['baseline']['max']:>9,.2f} | ${s['baseline']['bottom_10_mean']:>9,.2f}")
    print(f"{'Candidate':<20} | ${s['candidate']['mean']:>9,.2f} | ${s['candidate']['median']:>9,.2f} | ${s['candidate']['std']:>7,.2f} | ${s['candidate']['min']:>9,.2f} | ${s['candidate']['max']:>9,.2f} | ${s['candidate']['bottom_10_mean']:>9,.2f}")
    print("-" * 90)
    print(f"Paired Mean Delta:               ${p['mean_delta']:>+,.2f}")
    print(f"Median of Paired Deltas:         ${p['median_of_paired_deltas']:>+,.2f}")
    print(f"Difference of Marginal Medians:  ${p['difference_of_marginal_medians']:>+,.2f}")
    print(f"Paired Delta Std:                ${p['std_delta']:>,.2f}")
    print(f"Paired Delta Range:              Min ${p['min_delta']:>+,.2f} | Max ${p['max_delta']:>+,.2f}")
    print(f"Bottom 10% Mean Delta:           ${p['bottom_10_mean_delta']:>+,.2f}")
    print(f"Win / Loss / Tie:                {p['wins']} / {p['losses']} / {p['ties']} ({p['wins']/len(res['raw_results'])*200:.1f}%)")
    print("\n" + "-" * 90)
    print("OPPONENT BREAKDOWN:")
    for op_name, op_d in opp.items():
        print(f"  vs {op_name:<8}: Baseline ${op_d['baseline_mean']:>9,.2f} | Candidate ${op_d['candidate_mean']:>9,.2f} | Delta ${op_d['paired_mean_delta']:>+9,.2f} | W/L/T: {op_d['wins']}/{op_d['losses']}/{op_d['ties']}")
    print("=" * 90)
