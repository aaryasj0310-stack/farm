"""Trace v5.9 money curve on seed 202 to find the crash point."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))

import kaggle_environments
import importlib.util
spec = importlib.util.spec_from_file_location("v59", "submission/main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LOG = open("scripts/v59_money_202.txt", "w", encoding="utf-8")

_call = [0]
def tracing_agent(obs, config=None):
    result = mod.agent(obs, config)
    _call[0] += 1
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    farm = obs["farms"][0]
    money = farm.get("money", 0)
    hands = len(farm.get("hands", []))
    
    if hour == 0:
        market = result.get("market", [])
        hire_count = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "HIRE")
        seed_buys = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "BUY_SEED")
        animal_buys = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "BUY_ANIMAL")
        sells = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "SELL")
        print(f"D{day:2d} H{hour:2d}: money=${money:,.0f} hands={hands} hires={hire_count} seeds={seed_buys} animals={animal_buys} sells={sells}", file=LOG, flush=True)
    
    return result

env = kaggle_environments.make("kaggriculture", configuration={"seed": 202, "loglevel": "ERROR"})
env.run([tracing_agent, "random"])

final = env.steps[-1][0].observation
print(f"\nFinal: hands={len(final['farms'][0]['hands'])} money=${final['farms'][0]['money']:,.0f}", file=LOG, flush=True)
LOG.close()
