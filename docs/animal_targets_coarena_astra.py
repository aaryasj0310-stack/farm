"""Kaggriculture livestock targets: bounded, market-aware purchase heuristic.

Corrected engine rules & mechanics:
* day is 0..29 (Season is 30 days total). Remaining production days R = 29 - day.
* Gestation / first yield lag: COW takes 8 days, SHEEP takes 6 days.
* Care bonus: Daily CARE accumulates pending care bonus. COW yields 6 milk on first cycle
  and 3 milk on subsequent 2-day cycles. SHEEP yields 6 wool on first cycle and 4 wool on
  subsequent 3-day cycles (capped by max_held = 6).
* Daily fertilizer ($100 base) drops every day starting day + 1. Net fertilizer profit = (100 - FEED_PRICE) * R.
* Zero Geese policy: Geese yield low-margin eggs and consume farm capacity. GOOSE target is always 0.
* Town drainage limits: SHEEP_CAP = 12 (13/day town wool drain), COW_CAP = 19 (19/day town milk drain),
  HERD_CAP = 20 (20/day fertilizer drain).
* Spatial pasture capacity: bounded by max_pastures.
"""

HERD_CAP = 20          # fertilizer clearance, not the 75-tile physical maximum
SHEEP_CAP = 12         # 3-4 wool / 3 days: <= 12-13/day town wool drain
COW_CAP = 19           # 2-3 milk / 2 days: <= 19 milk/day town drain
FEED_PRICE = 25        # conservative market replacement cost
FEED_BUFFER_DAYS = 3


def get_animal_targets(day, money, shed_wheat, current_animals, max_pastures=20):
    """Choose the highest modeled incremental terminal profit affordable now.

    O(21**2) worst-case, O(1) extra space; no imports, I/O or randomness.
    Recompute after actual purchases; execute additions only when housing and
    care/feed capacity are confirmed. Do not call on unreserved gross cash.
    """
    day = int(day)
    if not 0 <= day <= 29:
        raise ValueError(f"day must be in 0..29, got {day}")
    c0 = max(0, int(current_animals.get("COW", 0)))
    s0 = max(0, int(current_animals.get("SHEEP", 0)))
    g0 = max(0, int(current_animals.get("GOOSE", 0)))
    result = {"COW": c0, "SHEEP": s0, "GOOSE": 0}
    remaining = 29 - day
    herd = c0 + s0 + g0
    effective_herd_cap = min(HERD_CAP, int(max_pastures))
    if remaining == 0 or herd >= effective_herd_cap:
        return result

    cash = max(0.0, float(money))
    wheat = max(0, int(shed_wheat))
    
    # Accurate yield formulas with gestation lag and care bonus:
    # COW: first yield at day + 8 (6 milk), then every 2 days (3 milk)
    milk_units = (6 + 3 * ((remaining - 8) // 2)) if remaining >= 8 else 0
    # SHEEP: first yield at day + 6 (6 wool), then every 3 days (4 wool)
    wool_units = (6 + 4 * ((remaining - 6) // 3)) if remaining >= 6 else 0
    
    cow_profit = 160 * milk_units + (100 - FEED_PRICE) * remaining - 400
    sheep_profit = 200 * wool_units + (100 - FEED_PRICE) * remaining - 500
    
    room = effective_herd_cap - herd
    max_c = min(room, max(0, COW_CAP - c0)) if cow_profit > 0 else 0
    max_s = min(room, max(0, SHEEP_CAP - s0)) if sheep_profit > 0 else 0
    
    best_profit = 0
    best_spend = 0
    for add_s in range(max_s + 1):
        for add_c in range(min(max_c, room - add_s) + 1):
            purchase_cost = 500 * add_s + 400 * add_c
            feed_reserve = FEED_PRICE * max(
                0, min(FEED_BUFFER_DAYS, remaining) * (herd + add_s + add_c) - wheat
            )
            if purchase_cost + feed_reserve > cash:
                continue
            profit = add_s * sheep_profit + add_c * cow_profit
            if profit > best_profit or (profit == best_profit and purchase_cost < best_spend):
                best_profit = profit
                best_spend = purchase_cost
                result = {"COW": c0 + add_c, "SHEEP": s0 + add_s, "GOOSE": 0}
    return result
