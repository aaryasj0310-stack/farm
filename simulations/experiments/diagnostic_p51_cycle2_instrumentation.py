#!/usr/bin/env python3
"""Diagnostic script: Instrument P5.0-R's provisional live replay logic.
Traces every transition of T1 tiles on seed 96201 vs pass (seat 0) to identify the EXACT first failed transition for Cycle 2.
"""
from collections import defaultdict
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

clean = [p for p in sys.path if "simulations/baselines/" not in p.replace("\\", "/")]
agent_dir = os.path.join(ROOT, "agent")
sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ("state", "strategy", "execution", "market")] + [ROOT] + clean

import kaggle_environments
from kaggle_environments.envs.kaggriculture import kaggriculture as kg
import main as treat_module
import config as treat_cfg
import execution.task_scheduler as treat_ts
import strategy.macro_planner as treat_mp
import simulations.experiments.audit_p50r_telemetry as apt
import simulations.experiments.analyze_p50r_revalidation as ana
from simulations.experiments.agent_zoo import get_agent

apt._configure_baseline(treat_cfg)
treat_module.reset_agent_state()
treat_ts.reset_daily_log()

t1_active_tiles = {}  # pos -> planted_day
events_log = []

orig_build = treat_mp.MacroPlanner.build

def t1_build(planner_self, ctx, *args, **kwargs):
    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)
    farm = ctx.get("farm")
    priv = ctx.get("private")
    
    # 1. On Days 21-23: Convert surplus wheat in plan to CARROT (Cycle 1)
    plan = orig_build(planner_self, ctx, *args, **kwargs)
    
    if 21 <= day <= 28:
        # Check T1 active tiles status in observation
        for pos_tuple, p_day in list(t1_active_tiles.items()):
            tx, ty = pos_tuple
            t = farm.tiles[ty][tx] if farm else None
            kind = getattr(t, "kind", "NONE")
            crop = getattr(t, "crop", "")
            age = getattr(t, "age", -1)
            events_log.append(f"[D{day} H{hour:02d}] T1 Tile {pos_tuple} (planted D{p_day}): kind={kind}, crop={crop}, age={age}")
            
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
                        events_log.append(f"[D{day} H{hour:02d}] CONVERTED wheat->carrot on {pos}. Active tiles: {list(t1_active_tiles.keys())}")
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
                        events_log.append(f"[D{day} H{hour:02d}] BUY_SEED INTENTS ADJUSTED: {plan.intents['buy_seed']}")

    # 2. On Days 24-26 at Hour 0: Pre-order seeds for Cycle 2 for crops maturing today!
    if 24 <= day <= 26 and hour == 0:
        maturing_today = sum(1 for pos, p_day in t1_active_tiles.items() if p_day + 3 == day)
        events_log.append(f"[D{day} H00] H0 Maturing check: maturing_today={maturing_today}, active={t1_active_tiles}")
        if maturing_today > 0 and hasattr(plan, "intents"):
            plan.intents.setdefault("buy_seed", {})["CARROT"] = plan.intents.setdefault("buy_seed", {}).get("CARROT", 0) + maturing_today
            events_log.append(f"[D{day} H00] Injected {maturing_today} CARROT seeds into buy_seed intents: {plan.intents.get('buy_seed')}")

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
                    in_q = pos_tuple in queued_positions
                    base_q = [c for p, c in plan.plant_queue if tuple(p) == pos_tuple]
                    events_log.append(f"[D{day} H{hour:02d}] T1 Replant check on {pos_tuple}: is_empty={is_empty}, in_queue={in_q}, baseline_queued={base_q}")
                    if is_empty and pos_tuple not in queued_positions:
                        tiles_to_replant.append(pos_tuple)

            for pos_tuple in tiles_to_replant:
                plan.plant_queue.append((pos_tuple, "CARROT"))
                del t1_active_tiles[pos_tuple]
                events_log.append(f"[D{day} H{hour:02d}] QUEUED C2 CARROT on {pos_tuple}")

    return plan

treat_mp.MacroPlanner.build = t1_build

def instrumented_agent(obs, config_env):
    day = obs["day"]
    hour = obs["hour"]
    res = orig_agent(obs, config_env)
    
    if 21 <= day <= 28 and hour in (0, 1, 2, 3, 4):
        my_seat = 0
        priv = obs.get("private", {})
        farm = obs["farms"][0]
        seeds = priv.get("seeds", {})
        events_log.append(f"[D{day} H{hour:02d}] AGENT ACTIONS: market={res.get('market', [])}, seeds={seeds}, money={farm.get('money')}")
    return res

orig_agent = treat_module.agent
opp_agent_treat = get_agent("pass")
env_treat = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 722, "seed": 96201}, info={"seed": 96201})
env_treat.reset()
env_treat.run([instrumented_agent, opp_agent_treat])

print(f"Game finished. Final reward: {env_treat.state[0].reward}")
os.makedirs("simulations/experiments/results", exist_ok=True)
with open("simulations/experiments/results/diagnostic_c2_trace.txt", "w") as f:
    for l in events_log:
        f.write(l + "\n")
print(f"Wrote {len(events_log)} trace events to simulations/experiments/results/diagnostic_c2_trace.txt")
