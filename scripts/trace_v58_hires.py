"""Trace v5.8 agent's actual hire behavior across all 5 seeds."""
import sys, os
sys.path.insert(0, 'submission_v5_8')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission_v5_8', sub))

import kaggle_environments
import importlib.util
spec = importlib.util.spec_from_file_location("v58", "submission_v5_8/main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SEEDS = [101, 202, 303, 404, 505]

for seed in SEEDS:
    env = kaggle_environments.make("kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"})
    env.run([mod.agent, "random"])
    
    total_hires = 0
    total_hire_cost = 0
    for step in env.steps:
        obs = step[0].observation
        action = step[0].action
        if isinstance(action, dict):
            market = action.get("market", [])
            hires = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "HIRE")
            total_hires += hires
    
    final = env.steps[-1][0].observation
    print(f"Seed {seed}: {total_hires} total hires, final ${final['farms'][0]['money']:,.0f}")
