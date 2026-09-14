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
try:
    from config import (
        C4_LIVESTOCK_CUTOFF_DAY,
        SELECTIVE_LIVESTOCK_GATE_ENABLED,
        SELECTIVE_LIVESTOCK_GATE_THRESHOLD,
        SELECTIVE_LIVESTOCK_MAX_DAY,
    )
except ImportError:
    C4_LIVESTOCK_CUTOFF_DAY = 12
    SELECTIVE_LIVESTOCK_GATE_ENABLED = False
    SELECTIVE_LIVESTOCK_GATE_THRESHOLD = 500.0
    SELECTIVE_LIVESTOCK_MAX_DAY = 14

FEED_PRICE = 25        # conservative market replacement cost
FEED_BUFFER_DAYS = 3


def estimate_species_remaining_profit(day, cutoff_day=None):
    """Compute expected remaining-season net profit for each species.

    Enforces C4 cutoff, gestation lag, care bonus, feed cost, and daily fertilizer.
    Returns: {"COW": cow_profit, "SHEEP": sheep_profit, "GOOSE": 0.0}
    """
    day = int(day)
    effective_cutoff = C4_LIVESTOCK_CUTOFF_DAY if cutoff_day is None else int(cutoff_day)
    remaining = max(0, 29 - day)
    if remaining == 0 or day >= effective_cutoff:
        return {"COW": 0.0, "SHEEP": 0.0, "GOOSE": 0.0}

    # Accurate yield formulas with gestation lag and care bonus:
    # COW: first yield at day + 8 (6 milk), then every 2 days (3 milk)
    milk_units = (6 + 3 * ((remaining - 8) // 2)) if remaining >= 8 else 0
    # SHEEP: first yield at day + 6 (6 wool), then every 3 days (4 wool)
    wool_units = (6 + 4 * ((remaining - 6) // 3)) if remaining >= 6 else 0

    if milk_units <= 0:
        cow_profit = 0.0
    else:
        cow_profit = float(160 * milk_units + (100 - FEED_PRICE) * remaining - 400)

    if wool_units <= 0:
        sheep_profit = 0.0
    else:
        sheep_profit = float(200 * wool_units + (100 - FEED_PRICE) * remaining - 500)

    return {
        "COW": max(0.0, cow_profit),
        "SHEEP": max(0.0, sheep_profit),
        "GOOSE": 0.0,
    }


def get_animal_targets(day, money, shed_wheat, current_animals, max_pastures=20,
                       cutoff_day=None, max_sustainable=None,
                       cow_cap=None, sheep_cap=None, herd_cap=None,
                       town_shops=None, market_inventory=None):
    """Compute optimal target counts for COW and SHEEP (GOOSE always 0).

    Stage 8B C4 Policy: Enforces late-game livestock investment cap (cutoff_day=12).
    Purchases on or after cutoff_day fail to amortize capital costs, feed, and care.
    Also enforces economic feasibility: an animal must produce primary product (milk/wool)
    to be considered viable; fertilizer alone cannot cover costs.
    Also enforces feed sustainability: total herd cannot exceed max_sustainable.
    Also enforces authoritative species caps (cow_cap, sheep_cap, herd_cap).

    O(21**2) worst-case, O(1) extra space; no imports, I/O or randomness.
    Recompute after actual purchases; execute additions only when housing and
    care/feed capacity are confirmed. Do not call on unreserved gross cash.
    """
    day = int(day)
    if day < 0:
        raise ValueError(f"day must be >= 0, got {day}")
    c0 = max(0, int(current_animals.get("COW", 0)))
    s0 = max(0, int(current_animals.get("SHEEP", 0)))
    g0 = max(0, int(current_animals.get("GOOSE", 0)))
    result = {"COW": c0, "SHEEP": s0, "GOOSE": 0}
    remaining = max(0, 29 - day)
    herd = c0 + s0 + g0

    # Query runtime getter from config if caps not explicitly passed
    try:
        from config import get_active_livestock_caps
        active_caps = get_active_livestock_caps()
    except Exception:
        active_caps = {"COW": COW_CAP, "SHEEP": SHEEP_CAP, "HERD": HERD_CAP}

    eff_herd_cap = HERD_CAP if herd_cap is None else int(herd_cap)
    eff_herd_cap = min(eff_herd_cap, active_caps.get("HERD", HERD_CAP))
    effective_herd_cap = min(eff_herd_cap, int(max_pastures))
    if max_sustainable is not None:
        effective_herd_cap = min(effective_herd_cap, max(0, int(max_sustainable)))

    eff_cow_cap = COW_CAP if cow_cap is None else int(cow_cap)
    eff_cow_cap = min(eff_cow_cap, active_caps.get("COW", COW_CAP))

    eff_sheep_cap = SHEEP_CAP if sheep_cap is None else int(sheep_cap)
    eff_sheep_cap = min(eff_sheep_cap, active_caps.get("SHEEP", SHEEP_CAP))
    
    # C4: Late-game livestock investment cap
    effective_cutoff = C4_LIVESTOCK_CUTOFF_DAY if cutoff_day is None else int(cutoff_day)
    allow_eval = (day < effective_cutoff) or (SELECTIVE_LIVESTOCK_GATE_ENABLED and day <= SELECTIVE_LIVESTOCK_MAX_DAY)
    if remaining == 0 or herd >= effective_herd_cap or not allow_eval:
        return result

    cash = max(0.0, float(money))
    wheat = max(0, int(shed_wheat))
    
    room = effective_herd_cap - herd
    try:
        from config import LIVESTOCK_EXPERIMENT_ARM
    except ImportError:
        LIVESTOCK_EXPERIMENT_ARM = "ArmA"

    if day >= effective_cutoff and SELECTIVE_LIVESTOCK_GATE_ENABLED:
        from strategy.marginal_livestock_valuator import estimate_realized_marginal_animal_value
        eval_c = estimate_realized_marginal_animal_value(
            "COW", day, current_animals, empty_pastures=room,
            town_shops=town_shops, market_inventory=market_inventory
        )
        eval_s = estimate_realized_marginal_animal_value(
            "SHEEP", day, current_animals, empty_pastures=room,
            town_shops=town_shops, market_inventory=market_inventory
        )
        cow_profit = eval_c["net_realized_value"] if eval_c["net_realized_value"] >= SELECTIVE_LIVESTOCK_GATE_THRESHOLD else 0.0
        sheep_profit = eval_s["net_realized_value"] if eval_s["net_realized_value"] >= SELECTIVE_LIVESTOCK_GATE_THRESHOLD else 0.0
    elif LIVESTOCK_EXPERIMENT_ARM == "ArmB":
        from strategy.marginal_livestock_valuator import estimate_realized_marginal_animal_value
        eval_c = estimate_realized_marginal_animal_value(
            "COW", day, current_animals, empty_pastures=room,
            town_shops=town_shops, market_inventory=market_inventory
        )
        eval_s = estimate_realized_marginal_animal_value(
            "SHEEP", day, current_animals, empty_pastures=room,
            town_shops=town_shops, market_inventory=market_inventory
        )
        cow_profit = eval_c["net_realized_value"] if eval_c["viable"] else 0.0
        sheep_profit = eval_s["net_realized_value"] if eval_s["viable"] else 0.0
    else:
        species_profits = estimate_species_remaining_profit(day, cutoff_day=effective_cutoff)
        cow_profit = species_profits["COW"]
        sheep_profit = species_profits["SHEEP"]

    
    max_c = min(room, max(0, eff_cow_cap - c0)) if cow_profit > 0 else 0
    max_s = min(room, max(0, eff_sheep_cap - s0)) if sheep_profit > 0 else 0
    
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

