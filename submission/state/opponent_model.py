"""Opponent model: public farm scan + market-ledger inference."""
from config import CROPS
from .observation_parser import crop_age


def opponent_snapshot(ctx, mem):
    opp = ctx.get("opponent_farm")
    if opp is None:
        return {}
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
    inferred = mem.get("opp_sales_inferred", {})
    if not inferred:
        return default
    return max(inferred, key=lambda k: inferred[k])
