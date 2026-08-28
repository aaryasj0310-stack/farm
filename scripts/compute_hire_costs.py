"""Compute total hire costs for v5.9 vs v5.8 across all 5 seeds."""
import sys, os
sys.path.insert(0, 'agent')
for sub in ('state','strategy','execution','market'):
    sys.path.insert(0, os.path.join('agent', sub))

from config import get_target_hands
from market.order_builder import hire_total_cost

# Compute daily hire cost for v5.9 schedule
total_59 = 0
print("v5.9 daily hire costs:")
for day in range(30):
    target = get_target_hands(day)
    cost = hire_total_cost(target)
    total_59 += cost
    if target > 0:
        print(f"  Day {day:2d}: {target:2d} hands = ${cost:.0f}")
print(f"  TOTAL: ${total_59:.0f}")

# v5.8 dynamic: 4 hands days 0-5, then dynamically up to 7
# Based on actual trace data: 4 hands every day
total_58 = 0
print("\nv5.8 hire costs (estimated 4 hands/day):")
for day in range(30):
    # v5.8 uses HIRE_BUDGET_MAX_HANDS=7 but actual hiring varies
    # From trace: 4 hands days 0-3, then 0 hands days 4+ (budget exhausted)
    if day <= 3:
        cost = hire_total_cost(4)
        total_58 += cost
        print(f"  Day {day:2d}:  4 hands = ${cost:.0f}")
    else:
        pass  # 0 hands
print(f"  TOTAL: ${total_58:.0f}")

print(f"\nDifference: ${total_59 - total_58:.0f}")
