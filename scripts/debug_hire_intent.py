"""Debug: trace v5.9 agent's hire intent."""
import sys, os
sys.path.insert(0, 'agent')
for sub in ('state','strategy','execution','market'):
    sys.path.insert(0, os.path.join('agent', sub))

import kaggle_environments
from price_forecast import PriceForecast
from macro_planner import MacroPlanner
from order_builder import OrderBuilder
from task_scheduler import build_tasks, assign_tasks
from state_tracker import get_state

fc = PriceForecast.load()
planner = MacroPlanner(fc)
builder = OrderBuilder()

_debug = [0]
LOG = open("scripts/hire_debug.txt", "w", encoding="utf-8")

def debug_agent(obs, config=None):
    ctx, mem = get_state(obs)
    if ctx is None:
        return {"farmer": ["PASS"], "hands": [], "market": []}
    
    _debug[0] += 1
    day = ctx["day"]
    hour = ctx["hour"]
    
    if hour == 0:
        plan = planner.build(ctx, boosts={})
        hire_intent = plan.intents.get("hire", 0)
        print(f"Day {day:2d} Hour 0: hire_intent={hire_intent} hands_now={len(ctx['farm'].hands)} money=${ctx['farm'].money:.0f}", file=LOG, flush=True)
        
        # Build orders to see what happens
        orders, ledger = builder.build(ctx, plan.intents)
        print(f"  Orders: {orders[:5]}", file=LOG, flush=True)
        print(f"  Ledger dropped: {ledger.get('dropped', [])[:3]}", file=LOG, flush=True)
    
    return {"farmer": ["PASS"], "hands": [], "market": []}

env = kaggle_environments.make("kaggriculture", configuration={"seed": 101, "loglevel": "ERROR"})
env.run([debug_agent, "random"])
print(f"Total calls: {_debug[0]}", file=LOG, flush=True)
LOG.close()
