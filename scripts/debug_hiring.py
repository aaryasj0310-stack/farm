"""Debug: trace hiring flow in v5.9."""
import sys, os
sys.path.insert(0, 'agent')
for sub in ('state','strategy','execution','market'):
    sys.path.insert(0, os.path.join('agent', sub))

import kaggle_environments
from config import get_target_hands, DAY_TO_HANDS

PASS_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}

_debug_log = []

def debug_agent(obs, config=None):
    from state_tracker import get_state
    ctx, mem = get_state(obs)
    if ctx is None:
        return dict(PASS_ACTION)
    
    day = ctx["day"]
    hour = ctx["hour"]
    hands_now = len(ctx["farm"].hands)
    target = get_target_hands(day)
    money = ctx["farm"].money
    
    if hour == 0 or hour == 23:
        _debug_log.append(f"Day {day:2d} Hour {hour:2d}: hands={hands_now} target={target} money=${money:.0f}")
    
    return dict(PASS_ACTION)

# Run with seed 101
env = kaggle_environments.make("kaggriculture", configuration={"seed": 101, "loglevel": "ERROR"})
env.run([debug_agent, "random"])

print("Hiring debug log:")
for line in _debug_log:
    print(f"  {line}")

# Check final state
final_obs = env.steps[-1][0].observation
print(f"\nFinal: hands={len(final_obs['farms'][0]['hands'])} unlocked={final_obs['farms'][0]['unlocked_quadrants']}")
