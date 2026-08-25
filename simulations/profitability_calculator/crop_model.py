"""Exact day-by-day crop lifecycle simulation.

Rules modeled (from `new rules.md` + profitability spec):
  - Watering daily required; a fresh seed starts with consecutive_unwatered = 1
    (planting-day miss counts), so planting without watering the same day kills
    it that night.
  - One-time crops gain yield during the bonus window: +1 per watered day
    (+2 while fertilized). Base 1 lands with the first watered window day.
    Yield caps at the crop's max (fertilizer cap).
  - Ongoing crops fire on a fixed schedule: base 1, doubled to 2 when
    fertilized AND watered that day. Lifespan ends after the last scheduled
    yield; decay then removes 1 unit every 2 turns until weed.
  - Fertilizer lasts 3 days from application ($100 per application).
"""
FERTILIZER_COST = 100
FERTILIZER_DURATION = 3

CROPS = {
    "WHEAT":      dict(seed=10, base=25, kind="one_time", max_yield_day=4,
                       window=(2, 4), cap=6),
    "CARROT":     dict(seed=20, base=35, kind="one_time", max_yield_day=3,
                       window=(2, 3), cap=4),
    "MELON":      dict(seed=80, base=250, kind="one_time", max_yield_day=10,
                       window=(6, 12), cap=6),
    "TOMATO":     dict(seed=50, base=60, kind="ongoing",
                       schedule=[8, 9, 10, 11], decay_day=12),
    "STRAWBERRY": dict(seed=100, base=120, kind="ongoing",
                       schedule=[10, 12, 14, 16], decay_day=17),
}

# Optimal fertilizer application day(s) per crop (spans of 3 days).
OPTIMAL_FERT_DAYS = {
    "WHEAT": [2],        # covers whole window -> cap 6 at day 4
    "CARROT": [2],       # -> cap 4 at day 3
    "MELON": [5],        # boosts window days 6-7 -> cap 6 at day 8
    "TOMATO": [8, 11],   # doubles all four scheduled yields -> 8 total
    "STRAWBERRY": [10, 14],
}


def _fert_span(fertilized_days):
    if fertilized_days is None:
        return set()
    if isinstance(fertilized_days, int):
        fertilized_days = [fertilized_days]
    span = set()
    for d in fertilized_days:
        span.update(range(d, d + FERTILIZER_DURATION))
    return span


def default_harvest_day(crop, fertilized=False):
    """Earliest day the crop reaches its (capped) full yield."""
    info = CROPS[crop]
    if info["kind"] == "ongoing":
        return info["schedule"][-1]
    lo, hi = info["window"]
    span = _fert_span(OPTIMAL_FERT_DAYS[crop]) if fertilized else set()
    yield_units = 0
    for age in range(lo, hi + 1):
        bonus = 2 if age in span else 1
        gained = (1 if yield_units == 0 else 0) + bonus   # base 1 lands first
        yield_units = min(info["cap"], yield_units + gained)
        if yield_units >= info["cap"]:
            return age
    return info["max_yield_day"]


def simulate_crop_lifecycle(crop, fertilized_days=None, skip_days=(),
                            harvest_day=None, price=None):
    """Day-by-day lifecycle. Returns totals + trajectory.

    harvest_day=None -> harvest automatically at maturity (earliest day the
    cap is reached; accelerated by fertilizer, e.g. melon day 8 vs 10).
    """
    info = CROPS[crop]
    span = _fert_span(fertilized_days)
    skip = set(skip_days)
    one_time = info["kind"] == "one_time"
    window = info.get("window", (10**6, -1))
    schedule = set(info.get("schedule", []))
    lifespan = (info["max_yield_day"] + 1) if one_time else info["decay_day"]

    yield_units = 0
    trajectory = {}
    consecutive_unwatered = 1   # planting day counts as first missed day
    waterings = 0
    status = "growing"

    def _mature(age):
        """Harvest trigger for automatic (None) harvest_day."""
        if one_time:
            return (age >= window[0] and yield_units >= info["cap"]) \
                or age >= info["max_yield_day"]
        return age >= info["schedule"][-1]

    age = 0
    while True:
        watered = age not in skip
        if watered:
            waterings += 1

        # --- morning/afternoon growth ---
        if one_time:
            if window[0] <= age <= window[1] and watered:
                bonus = 2 if age in span else 1
                gained = (1 if yield_units == 0 else 0) + bonus
                yield_units = min(info["cap"], yield_units + gained)
        else:
            if age in schedule:
                doubled = watered and age in span
                yield_units += 2 if doubled else 1

        trajectory[age] = yield_units

        # --- harvest ---
        if (harvest_day is not None and age >= harvest_day) or \
                (harvest_day is None and _mature(age)):
            status = "harvested"
            break

        # --- end-of-day refresh ---
        consecutive_unwatered = 0 if watered else consecutive_unwatered + 1
        if consecutive_unwatered >= 2:
            status = "died_unwatered"
            break
        # decay after max lifespan (unharvested): -1 unit every 2 days
        if age > lifespan and (age - lifespan) % 2 == 1:
            yield_units = max(0, yield_units - 1)
            trajectory[age] = yield_units
            if yield_units == 0:
                status = "decayed_to_weed"
                break
        age += 1

    apps = len(_fert_span_applications(fertilized_days))
    gross = yield_units * (info["base"] if price is None else price)
    return {
        "crop": crop,
        "total_yield": yield_units,
        "harvest_day": age,
        "status": status,
        "watering_actions": waterings,
        "seed_cost": info["seed"],
        "fertilizer_applications": apps,
        "fertilizer_cost": apps * FERTILIZER_COST,
        "gross_revenue": gross,
        "yield_trajectory": trajectory,
    }


def _fert_span_applications(fertilized_days):
    if fertilized_days is None:
        return []
    if isinstance(fertilized_days, int):
        fertilized_days = [fertilized_days]
    return list(fertilized_days)


def cycle_length(crop, fertilized=False):
    """Days from planting to replanting (harvest next-morning convention)."""
    return default_harvest_day(crop, fertilized) + 1


def season_plan(crop, horizon=30, fertilized=False, price=None):
    """Repeated planting over `horizon` days (day indices 0..horizon-1).

    Replants the day after each harvest. Returns season totals.
    """
    info = CROPS[crop]
    fert_days = OPTIMAL_FERT_DAYS[crop] if fertilized else None
    hday = default_harvest_day(crop, fertilized)
    cyc = hday + 1
    total_yield = 0
    plantings = 0
    watering = 0
    p = info["base"] if price is None else price
    revenue = 0
    start = 0
    while start + hday <= horizon - 1:
        res = simulate_crop_lifecycle(crop, fertilized_days=fert_days, price=p)
        total_yield += res["total_yield"]
        revenue += res["gross_revenue"]
        watering += res["watering_actions"]
        plantings += 1
        start += cyc
    seed_cost = plantings * info["seed"]
    fert_cost = (plantings * len(OPTIMAL_FERT_DAYS[crop]) * FERTILIZER_COST) if fertilized else 0
    return {
        "crop": crop,
        "fertilized": fertilized,
        "plantings": plantings,
        "season_yield": total_yield,
        "season_revenue": revenue,
        "seed_cost": seed_cost,
        "fertilizer_cost": fert_cost,
        "watering_actions": watering,
        "cycle_length": cyc,
    }
