"""Check money at Day 8-12 on seed 101."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))
import kaggle_environments, importlib.util
spec = importlib.util.spec_from_file_location('v59', 'submission/main.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
env = kaggle_environments.make('kaggriculture', configuration={'seed': 101, 'loglevel': 'ERROR'})
env.run([mod.agent, 'random'])
for step in env.steps:
    obs = step[0].observation
    day, hour = obs['day'], obs['hour']
    if hour == 0 and 8 <= day <= 12:
        money = obs['farms'][0]['money']
        hands = len(obs['farms'][0]['hands'])
        print(f"Day {day:2d} H0: money=${money:,.0f} hands={hands}")
