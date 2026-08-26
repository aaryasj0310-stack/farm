"""Shop-unlock adaptive demand scoring and planting pivots."""
from config import SHOPS


def demand_boosts(known_shops):
    """Product -> multiplier reflecting current town shop pressure."""
    boost = {}
    for shop in known_shops:
        for product in SHOPS[shop]:
            boost[product] = boost.get(product, 0) + 1
    return boost


def preferred_filler_crop(boosts, day):
    """Best crop to drop into spare tiles given shop unlocks and calendar.

    - PET_CAFE (carrot): carrots are cheap, fast (3d) -> always viable filler.
    - FARMERS_MARKET: carrots again (4 demanded products, carrot cheapest slot).
    - Ice cream / smoothie / brunch strawberry demand only pays if planted
      early enough for two harvest windows; otherwise fall back to carrots.
    """
    carrot_score = boosts.get("CARROT", 0)
    straw_score = boosts.get("STRAWBERRY", 0) * 2   # higher base price upside
    if straw_score > carrot_score and day <= 8:
        return "STRAWBERRY"
    if carrot_score > 0 or day >= 20:
        return "CARROT"
    return "CARROT"                                  # default cash filler


def react_to_new_shops(ctx, mem, macro):
    """Called daily: update macro.filler_crop from newly unlocked shops."""
    known = mem.get("known_shops", [])
    boosts = demand_boosts(known)
    new_count = len(known)
    prev = macro.get("shops_seen", 0)
    macro["shops_seen"] = new_count
    macro["demand_boosts"] = boosts
    if new_count > prev:
        macro["filler_crop"] = preferred_filler_crop(boosts, ctx["day"])
        macro["shop_event"] = True     # triggers a small carrot seed buy burst
    else:
        macro.setdefault("filler_crop", "CARROT")
        macro["shop_event"] = False
    return macro
