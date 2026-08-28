"""Check v5.9 agent return format."""
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

LOG = open("scripts/v59_format_trace.txt", "w", encoding="utf-8")

_call = [0]
def tracing_agent(obs, config=None):
    result = real_agent(obs, config)
    _call[0] += 1
    
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    
    if day <= 0:
        print(f"Day {day:2d} H{hour:2d} call#{_call[0]}:", file=LOG, flush=True)
        for k, v in result.items():
            if isinstance(v, list):
                print(f"  {k}: len={len(v)} first_3={v[:3]}", file=LOG, flush=True)
            else:
                print(f"  {k}: {v}", file=LOG, flush=True)
    
    return result

env = kaggle_environments.make("kaggriculture", configuration={"seed": 101, "loglevel": "ERROR"})
env.run([tracing_agent, "random"])

final = env.steps[-1][0].observation
print(f"\nTotal calls: {_call[0]}", file=LOG, flush=True)
print(f"Final hands: {len(final['farms'][0]['hands'])} money: ${final['farms'][0]['money']:.0f}", file=LOG, flush=True)
LOG.close()
