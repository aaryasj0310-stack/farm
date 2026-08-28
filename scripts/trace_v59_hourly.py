"""Trace actual v5.9 agent - check hands at every hour for first 2 days."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))

import kaggle_environments
import importlib.util
spec = importlib.util.spec_from_file_location("v59_agent", "submission/main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
real_agent = mod.agent

LOG = open("scripts/v59_hourly_trace.txt", "w", encoding="utf-8")

_call = [0]
def tracing_agent(obs, config=None):
    result = real_agent(obs, config)
    _call[0] += 1
    
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    money = obs.get("farms", [{}])[0].get("money", 0)
    hands = len(obs.get("farms", [{}])[0].get("hands", []))
    seeds = obs.get("farms", [{}])[0].get("seed_slots", {})
    tiles_planted = sum(1 for row in obs.get("farms", [{}])[0].get("tiles", []) for t in row if t and t.get("kind") in ("PLANT","WHEAT","STRAWBERRY","TOMATO","CARROT","MELON"))
    
    if day <= 1:
        market = result.get("market", [])
        hire_count = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "HIRE")
        print(f"Day {day:2d} H{hour:2d}: hands={hands} money=${money:.0f} tiles_planted={tiles_planted} hires_submit={hire_count} market_n={len(market)}", file=LOG, flush=True)
    
    return result

env = kaggle_environments.make("kaggriculture", configuration={"seed": 101, "loglevel": "ERROR"})
env.run([tracing_agent, "random"])

final = env.steps[-1][0].observation
print(f"\nFinal: hands={len(final['farms'][0]['hands'])} money=${final['farms'][0]['money']:.0f}", file=LOG, flush=True)
LOG.close()
