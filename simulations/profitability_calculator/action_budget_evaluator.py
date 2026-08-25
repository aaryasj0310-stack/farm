"""Action accounting: NPPA (net profit per action) and Fibonacci labor costs.

Assumptions (documented, configurable):
  - Each field action (PLANT/WATER/HARVEST/FEED/CARE/etc.) also costs
    TRAVEL_ACTIONS_PER_FIELD_ACTION movement actions on average.
  - One farmer supplies 24 actions/day; each extra hired hand costs
    fib(n) coins that day (1, 1, 2, 3, 5, 8, ...), n = hires so far today.
"""
MOVES_PER_FIELD_ACTION = 1.0
TURNS_PER_DAY = 24

CROP_ACTION_PLAN = {
    # actions per cycle: plant + water x days + harvest  (+ fert apps)
    "WHEAT": dict(water_days=4),
    "CARROT": dict(water_days=3),
    "MELON": dict(water_days=10),
    "TOMATO": dict(water_days=12),      # planting day .. decay eve
    "STRAWBERRY": dict(water_days=17),
}


def crop_cycle_actions(crop, fertilized=False):
    """Total farmer actions per crop cycle incl. travel amortization."""
    plan = CROP_ACTION_PLAN[crop]
    from crop_model import default_harvest_day
    hday = default_harvest_day(crop, fertilized)
    waters = min(plan["water_days"], max(hday, 0))
    acts = 1 + waters + 1                      # plant + water + harvest
    if fertilized:
        from crop_model import OPTIMAL_FERT_DAYS, FERTILIZER_DURATION
        acts += len(OPTIMAL_FERT_DAYS[crop]) * FERTILIZER_DURATION / 3.0 \
            * 2   # COLLECT_FERTILIZER pickup + FERTILIZE application
    return acts * (1 + MOVES_PER_FIELD_ACTION)


def animal_daily_actions(interval, care=False):
    """Daily action load: FEED + CARE + scheduled HARVEST share."""
    return (1 + (1 if care else 0) + 1.0 / interval) * (1 + MOVES_PER_FIELD_ACTION)


def net_profit_per_action(net_profit, total_actions):
    if total_actions <= 0:
        return 0.0
    return net_profit / total_actions


def fibonacci_hands_cost(n_hands):
    """Cost of hiring `n_hands` hands in one day: fib(1..n) summed."""
    a, b = 1, 1
    total = 0
    for _ in range(n_hands):
        total += a
        a, b = b, a + b
    return total


def labor_scaling(tile_counts=(25, 50, 75, 100), care_animals=0, animals=0):
    """Daily watering-dominated action load -> hands -> Fibonacci labor cost.

    Load model: 1 water-action per planted tile per day + animal daily load,
    all with travel multiplier. Hands needed = ceil(load / 24).
    """
    rows = []
    for tiles in tile_counts:
        load = tiles * (1 + MOVES_PER_FIELD_ACTION) \
            + animals * animal_daily_actions(2, care=care_animals > 0)
        hands = int(-(-load // TURNS_PER_DAY))
        cost = fibonacci_hands_cost(hands)
        rows.append({
            "tiles": tiles,
            "actions_per_day": round(load, 1),
            "hands_needed": hands,
            "daily_labor_cost": cost,
            "cost_per_action": round(cost / load, 3) if load else 0.0,
        })
    return rows
