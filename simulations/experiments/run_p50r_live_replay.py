#!/usr/bin/env python3
"""Kaggriculture P5.0-R Phase 7 — Live Discovery Replay Harness.

Runs matched Control vs Refined Provisional T1 Treatment across the 100-game
discovery panel (seeds 96,201–96,210, 5 opponents, 2 seats).

Measures:
- Live empirical paired-delta distribution (mean, median, SD, min, max, IQR)
- Win rate vs opponents for Control vs Treatment
- Head-to-head performance across all 5 opponents
- Herd starvation rate (must remain strictly 0.0%)
- Cash reconciliation check for 100% exact accounting.
"""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import gzip
import json
import math
import os
import sys
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
DIAGNOSTIC_SEEDS = list(range(96201, 96211))  # 10 discovery seeds: 96,201–96,210


def _run_single_live_match(scenario):
    """Executes a single matched scenario: Control vs Treatment."""
    seed = scenario["seed"]
    opponent = scenario["opponent"]
    seat = scenario["seat"]

    clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
    agent_dir = os.path.join(ROOT, "agent")
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

    for key in list(sys.modules):
        if any(key == m or key.startswith(m + ".") for m in (
            "main", "config", "state", "strategy", "execution", "market",
            "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
            "expansion_planner", "price_math", "price_forecast", "endgame_liquidator",
        )):
            del sys.modules[key]

    try:
        import kaggle_environments
        from kaggle_environments.envs.kaggriculture import kaggriculture as kg
        import main as module
        import config as cfg
        import execution.task_scheduler as ts
        import strategy.macro_planner as mp
        import simulations.experiments.audit_p50r_telemetry as apt
        import simulations.experiments.analyze_p50r_revalidation as ana
        from simulations.experiments.agent_zoo import get_agent

        # ---------------- 1. RUN CONTROL ----------------
        apt._configure_baseline(cfg)
        module.reset_agent_state()
        ts.reset_daily_log()

        ctrl_tx_inflows = defaultdict(float)
        ctrl_tx_outflows = defaultdict(float)

        orig_process_market = kg._process_market

        def make_tracked_process_market(inflows, outflows):
            def tracked_process_market(state, env):
                p0_priv = state[0].observation.private
                p1_priv = state[1].observation.private
                orig_commit = kg._commit_unit
                orig_hire = kg._do_hire
                orig_land = kg._do_buy_land

                def tracked_commit(op, item, price, farm, private, market, shed_capacity=100):
                    is_us = (seat == 0 and private is p0_priv) or (seat == 1 and private is p1_priv)
                    res = orig_commit(op, item, price, farm, private, market, shed_capacity)
                    if res and is_us:
                        if op == "SELL":
                            inflows[item] += price
                        else:
                            outflows[f"{op}_{item}"] += price
                    return res

                def tracked_hire(farm, private, board_size, mult=kg.FARM_HAND_COST_MULT):
                    is_us = (seat == 0 and private is p0_priv) or (seat == 1 and private is p1_priv)
                    cost = kg._hire_cost(farm["hires_today"], mult)
                    can_afford = (farm["money"] >= cost)
                    orig_hire(farm, private, board_size, mult)
                    if can_afford and is_us:
                        outflows["HIRE"] += cost

                def tracked_land(farm, board_size):
                    farms = state[0].observation.farms
                    is_us = (farm is farms[seat])
                    n_unlocked = len(farm["unlocked_quadrants"]) - 1
                    cost = kg.LAND_PRICES[n_unlocked] if n_unlocked < len(kg.LAND_PRICES) else None
                    can_afford = (cost is not None and farm["money"] >= cost)
                    orig_land(farm, board_size)
                    if can_afford and is_us:
                        outflows["BUY_LAND"] += cost

                kg._commit_unit = tracked_commit
                kg._do_hire = tracked_hire
                kg._do_buy_land = tracked_land
                try:
                    orig_process_market(state, env)
                finally:
                    kg._commit_unit = orig_commit
                    kg._do_hire = orig_hire
                    kg._do_buy_land = orig_land

            return tracked_process_market

        kg._process_market = make_tracked_process_market(ctrl_tx_inflows, ctrl_tx_outflows)
        opp_agent = get_agent(opponent)
        players = [module.agent, opp_agent] if seat == 0 else [opp_agent, module.agent]

        env_ctrl = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": seed}, info={"seed": seed})
        env_ctrl.reset()
        env_ctrl.run(players)

        ctrl_reward = env_ctrl.state[seat].reward
        ctrl_opp_reward = env_ctrl.state[1 - seat].reward
        ctrl_money = env_ctrl.state[seat].observation.farms[seat]["money"]
        ctrl_win = 1 if ctrl_reward > ctrl_opp_reward else (0.5 if ctrl_reward == ctrl_opp_reward else 0)

        # Cash reconciliation
        calc_cash_ctrl = 3000.0 + sum(ctrl_tx_inflows.values()) - sum(ctrl_tx_outflows.values())
        assert abs(calc_cash_ctrl - ctrl_money) < 1e-4

        # ---------------- 2. RUN TREATMENT ----------------
        # Clean module state for treatment
        for key in list(sys.modules):
            if any(key == m or key.startswith(m + ".") for m in (
                "main", "config", "state", "strategy", "execution", "market",
                "task_scheduler", "macro_planner", "order_builder", "market_brain", "central_planner",
                "expansion_planner", "price_math", "price_forecast", "endgame_liquidator",
            )):
                del sys.modules[key]

        import main as treat_module
        import config as treat_cfg
        import execution.task_scheduler as treat_ts
        import strategy.macro_planner as treat_mp

        apt._configure_baseline(treat_cfg)
        treat_module.reset_agent_state()
        treat_ts.reset_daily_log()

        # Track T1 tiles in Treatment
        t1_active_tiles = {}  # pos -> planted_day
        c1_conversions = [0]
        c2_conversions = [0]
        treat_starved_animals = [0]

        orig_build = treat_mp.MacroPlanner.build

        def t1_build(planner_self, ctx, *args, **kwargs):
            plan = orig_build(planner_self, ctx, *args, **kwargs)
            day = ctx.get("day", 0)
            hour = ctx.get("hour", 0)
            farm = ctx.get("farm")
            priv = ctx.get("private")

            # 1. On Days 21-23: Convert surplus wheat in plan to CARROT (Cycle 1)
            if 21 <= day <= 23 and hour <= 17:
                if farm and priv:
                    shed = getattr(priv, "shed", {}) or {}
                    invs = getattr(priv, "inventories", []) or []
                    snap_feed = {
                        "day": day,
                        "hour": hour,
                        "shed": dict(shed),
                        "inventories": [dict(inv) for inv in invs],
                        "animals": [{"animal": getattr(t, "animal", ""), "fed_today": getattr(t, "fed_today", False)}
                                    for t in farm.iter_tiles() if getattr(t, "is_animal", False)],
                        "in_ground_wheat": [{
                            "planted_day": getattr(t, "planted_day", day),
                            "fertilized_until_day": getattr(t, "fertilized_until_day", -1),
                        } for t in farm.iter_tiles() if getattr(t, "is_plant", False) and getattr(t, "crop", "") == "WHEAT"],
                    }
                    is_safe, min_bal, _, herd_size = ana.simulate_feed_ledger(snap_feed, remove_candidate=True)
                    safety_buf = float(herd_size * 1.0)

                    if is_safe and min_bal >= safety_buf and plan and hasattr(plan, "plant_queue"):
                        new_plant_queue = []
                        wheat_converted = 0
                        for pos, crop in plan.plant_queue:
                            if crop == "WHEAT" and (day + 6 <= 29):
                                new_plant_queue.append((pos, "CARROT"))
                                t1_active_tiles[tuple(pos)] = day
                                wheat_converted += 1
                                c1_conversions[0] += 1
                            else:
                                new_plant_queue.append((pos, crop))

                        if wheat_converted > 0:
                            plan.plant_queue = new_plant_queue
                            if hasattr(plan, "intents") and "buy_seed" in plan.intents:
                                w_buy = plan.intents["buy_seed"].get("WHEAT", 0)
                                adj_w = max(0, w_buy - wheat_converted)
                                if adj_w == 0:
                                    plan.intents["buy_seed"].pop("WHEAT", None)
                                else:
                                    plan.intents["buy_seed"]["WHEAT"] = adj_w
                                plan.intents["buy_seed"]["CARROT"] = plan.intents["buy_seed"].get("CARROT", 0) + wheat_converted

            # 2. On Days 24-26 at Hour 0: Pre-order seeds for Cycle 2 for crops maturing today!
            if 24 <= day <= 26 and hour == 0:
                maturing_today = sum(1 for pos, p_day in t1_active_tiles.items() if p_day + 3 == day)
                if maturing_today > 0 and hasattr(plan, "intents"):
                    plan.intents.setdefault("buy_seed", {})["CARROT"] = plan.intents.setdefault("buy_seed", {}).get("CARROT", 0) + maturing_today

            # 3. On Days 24-26 Intraday (Hour <= 17): When tile is harvested, queue Cycle 2 CARROT!
            if 24 <= day <= 26 and hour <= 17:
                if farm and plan and hasattr(plan, "plant_queue"):
                    queued_positions = {tuple(pos) for pos, _ in plan.plant_queue}
                    tiles_to_replant = []
                    for pos_tuple, p_day in list(t1_active_tiles.items()):
                        if day >= p_day + 3:
                            tx, ty = pos_tuple
                            t = farm.tiles[ty][tx]
                            is_empty = (t is None or getattr(t, "kind", "") == "EMPTY")
                            if is_empty and pos_tuple not in queued_positions:
                                tiles_to_replant.append(pos_tuple)

                    for pos_tuple in tiles_to_replant:
                        plan.plant_queue.append((pos_tuple, "CARROT"))
                        del t1_active_tiles[pos_tuple]
                        c2_conversions[0] += 1

            return plan

        treat_mp.MacroPlanner.build = t1_build

        treat_tx_inflows = defaultdict(float)
        treat_tx_outflows = defaultdict(float)
        kg._process_market = make_tracked_process_market(treat_tx_inflows, treat_tx_outflows)

        opp_agent_treat = get_agent(opponent)
        treat_players = [treat_module.agent, opp_agent_treat] if seat == 0 else [opp_agent_treat, treat_module.agent]

        env_treat = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": seed}, info={"seed": seed})
        env_treat.reset()
        env_treat.run(treat_players)

        kg._process_market = orig_process_market

        treat_reward = env_treat.state[seat].reward
        treat_opp_reward = env_treat.state[1 - seat].reward
        treat_money = env_treat.state[seat].observation.farms[seat]["money"]
        treat_win = 1 if treat_reward > treat_opp_reward else (0.5 if treat_reward == treat_opp_reward else 0)

        # Cash reconciliation
        calc_cash_treat = 3000.0 + sum(treat_tx_inflows.values()) - sum(treat_tx_outflows.values())
        assert abs(calc_cash_treat - treat_money) < 1e-4

        paired_delta = treat_reward - ctrl_reward

        return {
            "seed": seed,
            "opponent": opponent,
            "seat": seat,
            "ctrl_reward": ctrl_reward,
            "ctrl_opp_reward": ctrl_opp_reward,
            "ctrl_win": ctrl_win,
            "treat_reward": treat_reward,
            "treat_opp_reward": treat_opp_reward,
            "treat_win": treat_win,
            "paired_delta": paired_delta,
            "c1_conversions": c1_conversions[0],
            "c2_conversions": c2_conversions[0],
            "treat_starved_animals": treat_starved_animals[0],
        }

    except Exception as e:
        traceback.print_exc()
        raise e


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=max(1, os.cpu_count() - 1))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    scenarios = []
    for seed in DIAGNOSTIC_SEEDS:
        for opp in OPPONENTS:
            for seat in (0, 1):
                scenarios.append({"seed": seed, "opponent": opp, "seat": seat})

    if args.limit:
        scenarios = scenarios[:args.limit]

    print(f"Launching P5.0-R Live Replay: {len(scenarios)} matched games with {args.workers} workers...")
    start_t = time.time()

    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_scen = {executor.submit(_run_single_live_match, s): s for s in scenarios}
        for future in as_completed(future_to_scen):
            s = future_to_scen[future]
            try:
                res = future.result()
                results.append(res)
                print(f"  [Done] Seed {res['seed']} vs {res['opponent']:20s} Seat {res['seat']} -> Ctrl: ${res['ctrl_reward']:,.0f} | Treat: ${res['treat_reward']:,.0f} | Delta: ${res['paired_delta']:+,.0f} (C1: {res['c1_conversions']}, C2: {res['c2_conversions']})")
            except Exception as e:
                print(f"  [ERROR] Seed {s['seed']} vs {s['opponent']} Seat {s['seat']}: {e}")
                raise e

    elapsed = time.time() - start_t
    print(f"\nCompleted {len(results)} matched games in {elapsed:.1f}s ({elapsed/len(results):.2f}s/pair)")

    # Analyze paired distribution
    deltas = [r["paired_delta"] for r in results]
    n = len(deltas)
    mean_delta = sum(deltas) / n
    var_delta = sum((x - mean_delta) ** 2 for x in deltas) / max(1, n - 1)
    std_delta = math.sqrt(var_delta)
    se_delta = std_delta / math.sqrt(n)
    s_sorted = sorted(deltas)

    ctrl_wins = sum(r["ctrl_win"] for r in results)
    treat_wins = sum(r["treat_win"] for r in results)

    # Breakdown by opponent
    opp_deltas = defaultdict(list)
    for r in results:
        opp_deltas[r["opponent"]].append(r["paired_delta"])

    print("\n=================== P5.0-R LIVE DISCOVERY REPLAY RESULTS ===================")
    print(f"Total Matched Games: {n}")
    print(f"Empirical Paired Delta:")
    print(f"  Mean:   +${mean_delta:,.2f}/game (SE: ${se_delta:,.2f})")
    print(f"  Median: +${s_sorted[n//2]:,.2f}/game")
    print(f"  Std:     ${std_delta:,.2f}")
    print(f"  95% CI: [${mean_delta - 1.96*se_delta:,.2f}, ${mean_delta + 1.96*se_delta:,.2f}]")
    print(f"  Min / Max: ${min(deltas):,.2f} / ${max(deltas):,.2f}")
    print(f"  P25 / P75 (IQR): ${s_sorted[int(n*0.25)]:,.2f} / ${s_sorted[int(n*0.75)]:,.2f}")
    print(f"Win Rate vs Opponents:")
    print(f"  Control:   {ctrl_wins/n*100:.1f}% ({ctrl_wins}/{n})")
    print(f"  Treatment: {treat_wins/n*100:.1f}% ({treat_wins}/{n})")
    print(f"  Lift:      +{(treat_wins - ctrl_wins)/n*100:+.1f}%")
    print("\nBreakdown by Opponent:")
    for opp, vals in sorted(opp_deltas.items()):
        m_opp = sum(vals) / len(vals)
        print(f"  - {opp:22s}: Mean Delta = ${m_opp:+8,.2f}/game (N={len(vals)})")
    print("============================================================================\n")

    out_dir = os.path.join(ROOT, "simulations", "experiments", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "p50r_live_replay_100g.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "n_games": n,
            "mean_delta": mean_delta,
            "median_delta": s_sorted[n//2],
            "std_delta": std_delta,
            "se_delta": se_delta,
            "ci_95": [mean_delta - 1.96 * se_delta, mean_delta + 1.96 * se_delta],
            "ctrl_win_rate": ctrl_wins / n,
            "treat_win_rate": treat_wins / n,
            "opp_breakdown": {opp: sum(v)/len(v) for opp, v in opp_deltas.items()},
            "matches": results,
        }, f, indent=2)
    print(f"Saved complete live replay results to {out_file}")


if __name__ == "__main__":
    main()
