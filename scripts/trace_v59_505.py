"""Trace v5.9 money curve on seed 505."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))

import kaggle_environments
import importlib.util
spec = importlib.util.spec_from_file_location("v59", "submission/main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LOG = open("scripts/v59_money_505.txt", "w", encoding="utf-8")

def tracing_agent(obs, config=None):
    result = mod.agent(obs, config)
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    farm = obs["farms"][0]
    money = farm.get("money", 0)
    hands = len(farm.get("hands", []))
    shed = farm.get("shed_slots", {})
    shed_total = sum(v for v in shed.values() if isinstance(v, (int, float)))
    
    if hour == 0:
        market = result.get("market", [])
        hire_count = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "HIRE")
        sells = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "SELL")
        sell_qty = sum(o[2] for o in market if isinstance(o, list) and len(o) >= 3 and o[0] == "SELL")
        seeds_buy = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "BUY_SEED")
        animals_buy = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "BUY_ANIMAL")
        print(f"D{day:2d} H{hour:2d}: money=${money:,.0f} hands={hands} hires={hire_count} sells={sells}({sell_qty}) seeds={seeds_buy} animals={animals_buy} shed={shed_total:.0f}", file=LOG, flush=True)
    
    return result

env = kaggle_environments.make("kaggriculture", configuration={"seed": 505, "loglevel": "ERROR"})
env.run([tracing_agent, "random"])

final = env.steps[-1][0].observation
print(f"\nFinal: hands={len(final['farms'][0]['hands'])} money=${final['farms'][0]['money']:,.0f}", file=LOG, flush=True)
LOG.close()
