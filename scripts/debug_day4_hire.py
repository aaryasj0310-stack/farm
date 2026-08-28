"""Debug: trace macro_planner hire decision on Day 4."""
import sys, os
sys.path.insert(0, 'agent')
for sub in ('state','strategy','execution','market'):
    sys.path.insert(0, os.path.join('agent', sub))

try:
    from config import get_target_hands
    from strategy.baked_economics import MONEY_RESERVE
    from market.order_builder import hire_total_cost
    
    day = 4
    target = get_target_hands(day)
    current = 0  # hands reset daily
    hires = max(0, target - current)
    cost = hire_total_cost(hires)
    money = 300.0
    reserve = MONEY_RESERVE
    budget = money - reserve
    
    print(f"Day {day}: target={target} current={current} hires={hires} cost=${cost:.0f} money=${money:.0f} reserve=${reserve:.0f} budget=${budget:.0f}", flush=True)
    print(f"Budget covers hire? {budget >= cost}", flush=True)
    
    # Also check Day 0
    day = 0
    target = get_target_hands(day)
    hires = max(0, target - current)
    cost = hire_total_cost(hires)
    print(f"\nDay {day}: target={target} hires={hires} cost=${cost:.0f} money=$3000 budget=${3000-reserve:.0f}", flush=True)
    print(f"Budget covers hire? {3000-reserve >= cost}", flush=True)
    
    # Check what the v5.8 agent does for hiring
    print("\n--- v5.8 HIRE_BUDGET_MAX_HANDS ---", flush=True)
    from config import HIRE_BUDGET_MAX_HANDS
    print(f"HIRE_BUDGET_MAX_HANDS = {HIRE_BUDGET_MAX_HANDS}", flush=True)
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
