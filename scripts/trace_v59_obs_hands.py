"""Check hands count at every hour from observation for first 3 days."""
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

LOG = open("scripts/v59_obs_hands.txt", "w", encoding="utf-8")

_call = [0]
def tracing_agent(obs, config=None):
    result = real_agent(obs, config)
    _call[0] += 1
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    farm = obs["farms"][0]
    hands = len(farm.get("hands", []))
    money = farm.get("money", 0)
    seeds = {k:v for k,v in farm.get("seed_slots", {}).items() if v > 0} if isinstance(farm.get("seed_slots"), dict) else {}
    hired_today = farm.get("hires_today", -1)
    
    if day <= 2:
        print(f"D{day:2d} H{hour:2d}: hands={hands} money=${money:.0f} hired_today={hired_today} seeds={seeds}", file=LOG, flush=True)
    
    return result

env = kaggle_environments.make("kaggriculture", configuration={"seed": 101, "loglevel": "ERROR"})
env.run([tracing_agent, "random"])
LOG.close()
