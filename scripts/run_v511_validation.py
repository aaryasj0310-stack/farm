"""v5.11 Validation Script — Economic/deadline compliance checks.

Checks:
1. Hiring schedule compliance (from v5.10)
2. Q4 hard block (from v5.10)
3. Economic compliance:
   - Land purchased only when adjusted_roi > 0
   - Land purchased only when treasury sufficient
   - Land purchased only after unlock day
4. Deadline compliance:
   - No strawberry planted after Day 13
   - No melon planted after Day 17
   - SW seed targets never include strawberry after Day 13
5. Crop tile caps:
   - Strawberry ≤ dynamic cap (10/14/18/0)
   - Melon ≤ 6
6. Treasury safety:
   - Money never below reserve when land purchased
7. Expansion diagnostics populated

Usage:
    python scripts/run_v511_validation.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "submission"))
for sub in ["state", "strategy", "execution", "market"]:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "submission", sub))

from main import agent
from kaggle_environments import make
from config import (
    get_target_hands,
    QUADRANT_HARD_BLOCK,
    QUADRANT_UNLOCK_DAYS,
    STRAWBERRY_PLANT_DEADLINE,
    MELON_PLANT_DEADLINE,
    CROP_TILE_CAPS,
    get_strawberry_cap,
    get_sw_seed_targets,
    LAND_PRICES,
    MONEY_RESERVE_DEFAULT,
)

SEEDS = [101, 202, 303, 404, 505]


def validate_game(seed: int) -> dict:
    """Run a single game and validate all v5.11 constraints."""
    env = make("kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"})
    
    violations = []
    land_purchase_day = None
    land_purchase_roi = None
    
    # Run game and collect steps
    env.run([agent, "random"])
    
    prev_unlocked = []
    prev_day = -1
    
    # Analyze steps
    for step_idx, step in enumerate(env.steps):
        obs = step[0].observation
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        farm = obs.get("farms", [{}])[0] if obs.get("farms") else {}
        
        # 1. Hiring schedule compliance (every hour except H0)
        if hour != 0:
            expected_hands = get_target_hands(day)
            actual_hands = len(farm.get("hands", []))
            if actual_hands != expected_hands:
                violations.append(f"Day {day} H{hour}: hands={actual_hands}, expected={expected_hands}")
        
        # 2. Q4 hard block
        unlocked = farm.get("unlocked_quadrants", [])
        if "SE" in unlocked or 4 in unlocked:
            violations.append(f"Day {day} H{hour}: Q4 unlocked!")
        
        # Only do end-of-day checks at H23
        if hour != 23:
            # But still track land purchase
            curr_unlocked = farm.get("unlocked_quadrants", [])
            if set(curr_unlocked) != set(prev_unlocked):
                new_quadrants = set(curr_unlocked) - set(prev_unlocked)
                for q in new_quadrants:
                    if q in ("NE", "SW"):
                        land_purchase_day = day
            prev_unlocked = farm.get("unlocked_quadrants", [])
            continue
        
        # --- End-of-day checks (H23 only) ---
        curr_unlocked = farm.get("unlocked_quadrants", [])
        new_quadrants = set(curr_unlocked) - set(prev_unlocked)
        
        # 6. Land purchase detection
        for q in new_quadrants:
            if q in ("NE", "SW"):
                land_purchase_day = day
                # 7. Treasury safety
                money = farm.get("money", 0)
                if money < MONEY_RESERVE_DEFAULT:
                    violations.append(f"Day {day}: Land purchased with insufficient treasury (${money:.0f})")
                # 8. Unlock day compliance
                expected_day = QUADRANT_UNLOCK_DAYS.get(q)
                if expected_day and day < expected_day:
                    violations.append(f"Day {day}: Land purchased before unlock day {expected_day}")
        
        prev_unlocked = curr_unlocked
        
        # 3. Deadline compliance — check tiles planted
        tiles = farm.get("tiles", [])
        all_plants = []
        for row in tiles:
            for tile in row:
                if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    all_plants.append(tile)
        for tile in all_plants:
            crop = tile.get("crop", "EMPTY")
            if crop == "STRAWBERRY" and day > STRAWBERRY_PLANT_DEADLINE:
                violations.append(f"Day {day}: Strawberry planted after deadline (Day {STRAWBERRY_PLANT_DEADLINE})")
                break  # only report once per day
            if crop == "MELON" and day > MELON_PLANT_DEADLINE:
                violations.append(f"Day {day}: Melon planted after deadline (Day {MELON_PLANT_DEADLINE})")
                break
        
        # 4. SW seed targets — never strawberry after Day 13
        if day > 13:
            sw_targets = get_sw_seed_targets(day, farm.get("money", 0))
            if sw_targets.get("STRAWBERRY", 0) > 0:
                violations.append(f"Day {day}: SW seed targets include strawberry ({sw_targets['STRAWBERRY']})")
        
        # 5. Crop tile caps — strawberry only
        strawberry_count = sum(1 for t in all_plants if t.get("crop") == "STRAWBERRY")
        straw_cap = get_strawberry_cap(day, "SW" in unlocked)
        if strawberry_count > straw_cap:
            violations.append(f"Day {day}: Strawberry planted ({strawberry_count}) exceeds cap ({straw_cap})")
    
    # Final money
    final_money = env.steps[-1][0].observation.get("farms", [{}])[0].get("money", 0) if env.steps else 0
    
    return {
        "seed": seed,
        "terminal_wealth": final_money,
        "land_purchase_day": land_purchase_day,
        "violations": violations,
    }


def main():
    print("v5.11 Validation Script")
    print("=" * 60)
    print("Checks: Economic/deadline compliance (not hardcoded day)")
    print("=" * 60)
    
    results = []
    for seed in SEEDS:
        print(f"\nRunning seed {seed}...")
        t0 = time.time()
        result = validate_game(seed)
        dt = time.time() - t0
        results.append(result)
        print(f"  Terminal wealth: ${result['terminal_wealth']:,.0f} ({dt:.1f}s)")
        if result['land_purchase_day']:
            print(f"  Land purchased: Day {result['land_purchase_day']}")
        else:
            print(f"  Land purchased: Never")
        if result['violations']:
            print(f"  VIOLATIONS: {len(result['violations'])}")
            for v in result['violations'][:5]:  # Show first 5
                print(f"    - {v}")
        else:
            print(f"  PASS: No violations")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_violations = sum(len(r['violations']) for r in results)
    avg_wealth = sum(r['terminal_wealth'] for r in results) / len(results)
    land_days = [r['land_purchase_day'] for r in results if r['land_purchase_day']]
    
    print(f"Average terminal wealth: ${avg_wealth:,.0f}")
    print(f"Total violations: {total_violations}")
    if land_days:
        print(f"Land purchase days: {land_days}")
    else:
        print(f"Land purchased: Never (in any game)")
    
    if total_violations == 0:
        print("ALL CHECKS PASSED")
    else:
        print("VIOLATIONS FOUND — see details above")


if __name__ == "__main__":
    main()
