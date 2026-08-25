"""Exact livestock lifecycle simulation: feeding, care banking, fertilizer.

Rules modeled:
  - First production lands after the delay (goose 4d, sheep 6d, cow 8d),
    then repeats every `interval` days, indefinitely.
  - Feeding costs 1 wheat/day; an unfed production day still yields base 1
    but banks nothing (basic needs first).
  - CARE banking: each FED+CARED day that is not a production day banks +1,
    paid out (and reset) on the next fed production day. Goose produces every
    day -> zero off-days -> zero bonus; cow +1/cycle; sheep +2/cycle.
  - Every surviving animal generates 1 fertilizer at end-of-day regardless
    of feed/care. Uncollected fertilizer does not accumulate.
  - Unharvested product accumulates up to max_held.
"""
FERTILIZER_PER_DAY = 1

ANIMALS = {
    "GOOSE": dict(cost=300, structure="COOP", interval=1, delay=4,
                  product="EGG", max_held=4),
    "COW":   dict(cost=400, structure="PASTURE", interval=2, delay=8,
                  product="MILK", max_held=6),
    "SHEEP": dict(cost=500, structure="PASTURE", interval=3, delay=6,
                  product="WOOL", max_held=6),
}

PRODUCT_BASE = {"EGG": 50, "MILK": 160, "WOOL": 200}
FERTILIZER_BASE_PRICE = 100


def production_days(start_day, end_day, interval, delay):
    """Absolute season days on which the animal produces (start..end_day-1)."""
    first = start_day + delay
    return set(range(first, end_day, interval))


def simulate_animal_lifecycle(animal, start_day=0, end_day=30,
                              care_policy="never", feed_daily=True,
                              harvest_daily=True, wheat_price=25,
                              product_price=None, fertilizer_sold=False):
    """Simulate one animal from `start_day` through `end_day - 1`.

    care_policy: 'never' | 'always'
    Returns cumulative products, fertilizer, all costs and net profit.
    """
    info = ANIMALS[animal]
    prod_price = PRODUCT_BASE[info["product"]] if product_price is None else product_price
    prods = production_days(start_day, end_day, info["interval"], info["delay"])

    banked = 0
    pending = 0
    harvested = 0
    fert_collected = 0
    feed_wheat_units = 0
    last_production = None

    for day in range(start_day, end_day):
        is_prod = day in prods
        fed = feed_daily
        cared = care_policy == "always"

        if fed:
            feed_wheat_units += 1

        # --- production tick ---
        if is_prod:
            if fed:
                gain = 1 + banked
                banked = 0
            else:
                gain = 1  # base production even when unfed
            pending = min(info["max_held"], pending + gain)
            last_production = day
            if harvest_daily:
                harvested += pending
                pending = 0
        elif cared and fed and last_production is not None:
            banked += 1   # only off-days BETWEEN productions bank a bonus

        # --- end-of-day fertilizer (regardless of feed/care) ---
        fert_collected += FERTILIZER_PER_DAY

    gross_product = harvested * prod_price
    fert_revenue = fert_collected * FERTILIZER_BASE_PRICE if fertilizer_sold else 0
    feed_cost = feed_wheat_units * wheat_price
    capital = info["cost"]
    net = gross_product + fert_revenue - feed_cost - capital
    return {
        "animal": animal,
        "start_day": start_day,
        "days_owned": end_day - start_day,
        "product": info["product"],
        "productions": len(prods),
        "product_harvested": harvested,
        "pending_unharvested": pending,
        "fertilizer_collected": fert_collected,
        "gross_product_revenue": gross_product,
        "fertilizer_revenue": fert_revenue,
        "feed_wheat_units": feed_wheat_units,
        "feed_cost": feed_cost,
        "purchase_cost": capital,
        "net_profit": net,
    }


def evaluate_fertilizer_use(crop="WHEAT", applications=30, price=None):
    """Option B for animal fertilizer: apply to crops instead of selling.

    Value per application = extra crop yield vs unfertilized lifecycle,
    computed exactly via simulate_crop_lifecycle. Melon instead saves 2 days
    per cycle (reported as tile_days_saved).
    """
    from crop_model import CROPS, OPTIMAL_FERT_DAYS, simulate_crop_lifecycle

    if crop == "MELON":
        fast = simulate_crop_lifecycle("MELON", fertilized_days=[5])
        slow = simulate_crop_lifecycle("MELON")
        return {"crop": "MELON", "tile_days_saved": slow["harvest_day"] - fast["harvest_day"],
                "note": "earlier harvest frees the tile sooner; value = saved days x next-use margin"}
    base_yield = simulate_crop_lifecycle(crop)["total_yield"]
    fert_yield = simulate_crop_lifecycle(crop, fertilized_days=OPTIMAL_FERT_DAYS[crop])["total_yield"]
    extra_per_app = fert_yield - base_yield
    p = CROPS[crop]["base"] if price is None else price
    usable = min(applications, applications)  # each application is independent
    return {
        "crop": crop,
        "extra_units_per_application": extra_per_app,
        "applications": usable,
        "value": extra_per_app * p * usable,
        "sell_alternative_value": applications * FERTILIZER_BASE_PRICE,
    }
