"""Opponent model: public farm scan + market-ledger inference."""
from observation_parser import crop_age
from config import CROPS


def opponent_snapshot(ctx, mem):
    """Summarize the opponent's public state each turn."""
    opp = ctx["opponent_farm"]
    if opp is None:
        return {}
    ripe_melons = 0
    ripe_crops = {}
    for t in opp.iter_tiles():
        if t.is_plant:
            cd = CROPS.get(t.crop)
            if cd is None:
                continue
            age = crop_age(t, ctx["day"])
            if not cd["ongoing"] and age >= cd["max_yield_day"]:
                ripe_crops[t.crop] = ripe_crops.get(t.crop, 0) + t.yield_units
    animals = sum(1 for t in opp.iter_tiles() if t.is_animal)
    return {
        "money": opp.money,
        "ripe_units": ripe_crops,
        "animals": animals,
        "hands": len(opp.hands),
        "unlocked": sorted(opp.unlocked),
    }


def opponent_primary_product(mem, default="MELON"):
    """Product the opponent most likely holds for sale (from ledger inference).

    Positive `opp_sales_inferred` means they have been NET ADDING inventory,
    i.e. dumping that product. Spoiler against their biggest dump channel.
    """
    inferred = mem.get("opp_sales_inferred", {})
    if not inferred:
        return default
    return max(inferred, key=lambda k: inferred[k])
