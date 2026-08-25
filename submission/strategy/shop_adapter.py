"""Shop-unlock adaptive demand scoring and planting pivots.

v5.8 strategy: Primary crops are MELON (early) and STRAWBERRY (mid-game),
with WHEAT as feed + filler. Shops modulate which crop to prioritize buying.
"""
from config import SHOPS


def demand_boosts(known_shops):
    boost = {}
    for shop in known_shops:
        for product in SHOPS.get(shop, []):
            boost[product] = boost.get(product, 0) + 1
    return boost


def preferred_crop(boosts, day, seeds):
    """Best crop to plant given shop unlocks, calendar, and seed stock."""
    # v5.8 pattern: melon early, strawberry mid, wheat late/filler
    if day <= 13:
        if seeds.get("MELON", 0) > 0:
            return "MELON"
        if seeds.get("STRAWBERRY", 0) > 0:
            return "STRAWBERRY"
    elif day <= 20:
        straw_demand = boosts.get("STRAWBERRY", 0)
        if straw_demand > 0 and seeds.get("STRAWBERRY", 0) > 0:
            return "STRAWBERRY"
        if seeds.get("MELON", 0) > 0:
            return "MELON"
        if seeds.get("STRAWBERRY", 0) > 0:
            return "STRAWBERRY"
    # Fallback: wheat is always useful as feed + sellable
    return "WHEAT"


def react_to_new_shops(ctx, mem, macro):
    """Called each turn: update crop preference from shop unlocks."""
    known = mem.get("known_shops", [])
    boosts = demand_boosts(known)
    new_count = len(known)
    prev = macro.get("shops_seen", 0)
    macro["shops_seen"] = new_count
    macro["demand_boosts"] = boosts
    if new_count > prev:
        macro["shop_event"] = True
    else:
        macro["shop_event"] = False
    return macro
