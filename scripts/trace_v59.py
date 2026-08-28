"""Trace actual v5.9 submission agent's market orders."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))

import kaggle_environments

LOG = open("scripts/v59_market_trace.txt", "w", encoding="utf-8")

# Load the actual agent
import importlib.util
spec = importlib.util.spec_from_file_location("v59_agent", "submission/main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
real_agent = mod.agent

_call = [0]
def tracing_agent(obs, config=None):
    result = real_agent(obs, config)
    _call[0] += 1
    
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    money = obs.get("farms", [{}])[0].get("money", 0)
    hands = len(obs.get("farms", [{}])[0].get("hands", []))
    
    if hour == 0:
        market = result.get("market", [])
        hire_count = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "HIRE")
        print(f"Day {day:2d} H0: money=${money:.0f} hands={hands} market_orders={len(market)} hires={hire_count}", file=LOG, flush=True)
        if market:
            print(f"  market: {market[:6]}", file=LOG, flush=True)
    
    return result

env = kaggle_environments.make("kaggriculture", configuration={"seed": 101, "loglevel": "ERROR"})
env.run([tracing_agent, "random"])

# Check final
final = env.steps[-1][0].observation
print(f"\nFinal: hands={len(final['farms'][0]['hands'])} money=${final['farms'][0]['money']:.0f}", file=LOG, flush=True)
print(f"Calls: {_call[0]}", file=LOG, flush=True)
LOG.close()
