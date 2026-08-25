"""Endgame planning: latest profitable plant/purchase day for every asset.

Hard cutoff: last day an asset can start and still deliver at least one
harvest before the season ends (day index 29).
Economic cutoff: last day starting the asset still yields non-negative net
profit under base prices (accounts for seed/feed capital vs remaining days).
"""
from animal_model import ANIMALS, PRODUCT_BASE, simulate_animal_lifecycle
from crop_model import (
    CROPS,
    OPTIMAL_FERT_DAYS,
    default_harvest_day,
    simulate_crop_lifecycle,
)

SEASON_END = 29   # last day index; harvest on this day is sellable


def crop_hard_cutoff(crop, fertilized=False):
    return SEASON_END - default_harvest_day(crop, fertilized)


def crop_economics_by_day(crop, fertilized=False, price=None):
    """Net profit of a single cycle started on each day (None = no harvest)."""
    info = CROPS[crop]
    p = info["base"] if price is None else price
    fert_days = OPTIMAL_FERT_DAYS[crop] if fertilized else None
    hday = default_harvest_day(crop, fertilized)
    out = {}
    for start in range(SEASON_END + 1):
        if start + hday > SEASON_END:
            out[start] = None
            continue
        res = simulate_crop_lifecycle(crop, fertilized_days=fert_days, price=p)
        apps = len(fert_days or [])
        net = res["gross_revenue"] - info["seed"] - apps * 100
        out[start] = round(net, 2)
    return out


def animal_hard_cutoff(animal):
    return SEASON_END - ANIMALS[animal]["delay"]


def animal_economics_by_day(animal, care_policy="never", product_price=None,
                            wheat_price=25):
    p = PRODUCT_BASE[ANIMALS[animal]["product"]] if product_price is None else product_price
    out = {}
    for start in range(SEASON_END + 1):
        res = simulate_animal_lifecycle(animal, start_day=start,
                                        end_day=SEASON_END + 1,
                                        care_policy=care_policy,
                                        wheat_price=wheat_price,
                                        product_price=p)
        out[start] = {"net": round(res["net_profit"], 2),
                      "product": res["product_harvested"]}
    return out


def build_cutoff_table():
    """Day-by-day allowable planting table + hard/economic cutoffs."""
    table = {}
    for crop in CROPS:
        econ_f = crop_economics_by_day(crop, fertilized=True)
        econ_u = crop_economics_by_day(crop, fertilized=False)
        hard_f = crop_hard_cutoff(crop, fertilized=True)
        hard_u = crop_hard_cutoff(crop, fertilized=False)
        # economic cutoff: latest day whose best-variant single cycle nets >= 0
        econ_cutoff = None
        for d in range(SEASON_END, -1, -1):
            vals = [v for v in (econ_f[d], econ_u[d]) if v is not None]
            if vals and max(vals) >= 0:
                econ_cutoff = d
                break
        info = CROPS[crop]
        first_day = min(info.get("schedule", [info.get("max_yield_day")]))
        first_yield_cutoff = SEASON_END - first_day
        table[crop] = {
            "hard_cutoff_unfertilized": hard_u,
            "hard_cutoff_fertilized": hard_f,
            "first_yield_cutoff": first_yield_cutoff,
            "economic_cutoff_best_variant": econ_cutoff,
            "net_by_start_day_fertilized": econ_f,
            "net_by_start_day_unfertilized": econ_u,
            "allowable_days": list(range(0, hard_f + 1)),
        }
    for animal in ANIMALS:
        econ = animal_economics_by_day(animal)
        prof = [d for d, v in econ.items() if v["net"] >= 0]
        table[animal] = {
            "hard_cutoff": animal_hard_cutoff(animal),
            "economic_cutoff_base_prices": max(prof) if prof else None,
            "net_by_start_day": {d: v["net"] for d, v in econ.items()},
            "allowable_days": list(range(0, animal_hard_cutoff(animal) + 1)),
        }
    return table


if __name__ == "__main__":
    t = build_cutoff_table()
    for asset, v in t.items():
        print(asset, {k: w for k, w in v.items() if "cutoff" in k})
