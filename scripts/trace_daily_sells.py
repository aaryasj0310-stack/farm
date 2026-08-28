"""Check v5.9 sells and money for first 15 days on seed 101."""
import sys, os
sys.path.insert(0, 'submission')
for sub in ('state', 'strategy', 'execution', 'market'):
    sys.path.insert(0, os.path.join('submission', sub))
import kaggle_environments, importlib.util
spec = importlib.util.spec_from_file_location('v59', 'submission/main.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LOG = open("scripts/v59_daily_sells_101.txt", "w", encoding="utf-8")

day_sells = {}
day_money = {}
day_hires = {}

def tracing_agent(obs, config=None):
    result = mod.agent(obs, config)
    hour = obs.get("hour", -1)
    day = obs.get("day", -1)
    money = obs["farms"][0]["money"]
    
    if hour == 0:
        day_money[day] = money
        market = result.get("market", [])
        hire_count = sum(1 for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "HIRE")
        day_hires[day] = hire_count
    
    market = result.get("market", [])
    sells = [o for o in market if isinstance(o, list) and len(o) > 0 and o[0] == "SELL"]
    sell_qty = sum(o[2] for o in sells if len(o) >= 3)
    day_sells[day] = day_sells.get(day, 0) + sell_qty
    
    return result

env = kaggle_environments.make('kaggriculture', configuration={'seed': 101, 'loglevel': 'ERROR'})
env.run([tracing_agent, 'random'])

print(f"{'Day':>4} {'Money@H0':>10} {'Hires':>6} {'Sells':>6}", file=LOG)
print("-" * 30, file=LOG)
for day in range(15):
    m = day_money.get(day, 0)
    h = day_hires.get(day, 0)
    s = day_sells.get(day, 0)
    print(f"{day:4d} ${m:>9,.0f} {h:>6} {s:>6}", file=LOG)

LOG.close()
