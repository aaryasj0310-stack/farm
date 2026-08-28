"""Compare v5.9 vs v5.8 on seed 303 - per-day money diff."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))
sys.path.insert(0, 'submission_v5_8')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission_v5_8', sub))

import kaggle_environments
import importlib.util

LOG = open("scripts/v59_perday_303.txt", "w", encoding="utf-8")

# Load v5.9 agent
spec9 = importlib.util.spec_from_file_location("v59", "submission/main.py")
mod9 = importlib.util.module_from_spec(spec9)
spec9.loader.exec_module(mod9)

# Load v5.8 agent
spec8 = importlib.util.spec_from_file_location("v58", "submission_v5_8/main.py")
mod8 = importlib.util.module_from_spec(spec8)
spec8.loader.exec_module(mod8)

def run_with_trace(agent_fn, label):
    env = kaggle_environments.make("kaggriculture", configuration={"seed": 303, "loglevel": "ERROR"})
    env.run([agent_fn, "random"])
    
    # Extract per-day money at hour 0
    day_money = {}
    for step in env.steps:
        obs = step[0].observation
        day = obs["day"]
        hour = obs["hour"]
        money = obs["farms"][0]["money"]
        hands = len(obs["farms"][0]["hands"])
        if hour == 0 and day not in day_money:
            day_money[day] = (money, hands)
    
    return day_money

print("Running v5.9...", file=LOG, flush=True)
v59 = run_with_trace(mod9.agent, "v5.9")
print("Running v5.8...", file=LOG, flush=True)
v58 = run_with_trace(mod8.agent, "v5.8")

print(f"\n{'Day':>4} {'v5.9$':>10} {'v5.9 hands':>10} {'v5.8$':>10} {'v5.8 hands':>10} {'Delta':>10}", file=LOG, flush=True)
print("-" * 60, file=LOG, flush=True)
for day in range(30):
    m9, h9 = v59.get(day, (0, 0))
    m8, h8 = v58.get(day, (0, 0))
    d = m9 - m8
    print(f"{day:4d} ${m9:>9,.0f} {h9:>10} ${m8:>9,.0f} {h8:>10} ${d:>+9,.0f}", file=LOG, flush=True)

LOG.close()
