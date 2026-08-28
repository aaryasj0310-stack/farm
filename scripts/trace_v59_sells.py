"""Check sells at ALL hours for first 3 days on seed 505."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))

import kaggle_environments
import importlib.util
spec = importlib.util.spec_from_file_location("v59", "submission/main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LOG = open("scripts/v59_sells_all_hours.txt", "w", encoding="utf-8")

def tracing_agent(obs, config=None):
    result = mod.agent(obs, config)
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    
    market = result.get("market", [])
    sells = [o for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "SELL"]
    sell_qty = sum(o[2] for o in sells if len(o) >= 3)
    
    if day <= 2 and sell_qty > 0:
        farm = obs["farms"][0]
        money = farm.get("money", 0)
        shed = farm.get("shed_slots", {})
        shed_total = sum(v for v in shed.values() if isinstance(v, (int, float)))
        print(f"D{day:2d} H{hour:2d}: SELLS={len(sells)} qty={sell_qty} money=${money:,.0f} shed={shed_total:.0f}", file=LOG, flush=True)
    
    return result

env = kaggle_environments.make("kaggriculture", configuration={"seed": 505, "loglevel": "ERROR"})
env.run([tracing_agent, "random"])

# Count total sells across entire game
total_sells = [0]
def counting_agent(obs, config=None):
    result = mod.agent(obs, config)
    market = result.get("market", [])
    sells = [o for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "SELL"]
    sell_qty = sum(o[2] for o in sells if len(o) >= 3)
    total_sells[0] += sell_qty
    return result

env2 = kaggle_environments.make("kaggriculture", configuration={"seed": 505, "loglevel": "ERROR"})
env2.run([counting_agent, "random"])

print(f"\nTotal game sells: {total_sells[0]} units", file=LOG, flush=True)
print(f"Final money: ${env2.steps[-1][0].observation['farms'][0]['money']:,.0f}", file=LOG, flush=True)
LOG.close()
