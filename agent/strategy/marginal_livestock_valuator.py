"""Market-aware marginal livestock valuation using sequential counterfactual inventory simulation.

Calculates the true realized marginal net value of adding one specific additional
animal (COW, SHEEP, or GOOSE) on day D, accounting for:
- Exact engine yield timing (gestation lag, intervals, care bonus)
- Sequential market inventory simulation with-candidate vs without-candidate:
  Inv(t+1) = max(1, Inv(t) + Supply(t) - Drain(t))
  so earlier unsold production depresses later batch prices
- Whole-farm counterfactual marginal product revenue:
  DeltaRev = Rev_with - Rev_without
  which naturally captures own-supply price depression on the existing herd
  with zero double-counting and zero separate heuristic penalty subtractions
- Authoritative live market pricing for feed (WHEAT) and fertilizer (FERTILIZER)
- Pasture / housing opportunity cost
- Exact conditional distribution over remaining future town shop unlocks
"""
from typing import Dict, Any, List, Optional
import itertools

from config import MARKET_I0, ANIMALS
try:
    from market.price_math import market_price
except ImportError:
    from price_math import market_price

try:
    from strategy.baked_conditional_animal_prices import (
        UNLOCK_DAYS, TC_DEMAND, SHOP_DEMAND_RATES
    )
except ImportError:
    from baked_conditional_animal_prices import (
        UNLOCK_DAYS, TC_DEMAND, SHOP_DEMAND_RATES
    )


try:
    from strategy.price_forecast import PriceForecast
    _PRICE_FORECAST = PriceForecast.load()
except Exception:
    _PRICE_FORECAST = None


def estimate_realized_marginal_animal_value(
    species: str,
    day: int,
    current_animals: Dict[str, int],
    market_inventory: Optional[Dict[str, float]] = None,
    empty_pastures: int = 0,
    crop_opportunity_val: float = 0.0,
    wheat_available_per_animal: float = 20.0,
    town_shops: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Calculate the realized marginal net value of adding ONE additional animal on `day`.

    Simulates day-by-day inventory from day `day` to 28 for with-candidate and without-candidate
    branches under one consistent joint future shop-unlock path:
        I(t+1) = max(1, I(t) + Supply(t) - Drain(t))
    and accumulates counterfactual revenue:
        DeltaRev = Rev_with - Rev_without
    """
    sp = str(species).upper()
    if sp not in ("COW", "SHEEP", "GOOSE"):
        return {
            "species": sp, "day": day, "viable": False,
            "net_realized_value": -9999.0, "reason": "unsupported_species"
        }

    day = int(day)
    rem_days = max(0, 29 - day)
    if rem_days <= 0 or day >= 28:
        return {
            "species": sp, "day": day, "viable": False,
            "net_realized_value": -9999.0, "reason": "season_ended"
        }

    cost = float(ANIMALS[sp]["cost"])
    prod_item = ANIMALS[sp]["product"]
    current_count = int(current_animals.get(sp, 0)) if current_animals else 0

    # 1. Exact Production Schedule and Yields (with authoritative engine care bonus)
    first_lag = int(ANIMALS[sp]["first_yield_day"])
    interval = int(ANIMALS[sp]["interval"])
    first_yield = 6 if sp in ("COW", "SHEEP") else 2
    recurring_yield = 4 if sp == "SHEEP" else (3 if sp == "COW" else 1)

    production_events = []
    prod_day = day + first_lag
    cand_units = {t: 0.0 for t in range(day, 29)}
    while prod_day <= 28:
        units = first_yield if prod_day == (day + first_lag) else recurring_yield
        production_events.append((prod_day, units))
        cand_units[prod_day] = float(units)
        prod_day += interval

    # Feed cost: Authoritative incremental replacement cost via PriceForecast or live spot
    feed_days = max(0, 29 - day)
    wheat_inv = market_inventory.get("WHEAT", MARKET_I0) if market_inventory else MARKET_I0
    if _PRICE_FORECAST is not None:
        feed_cost = sum(_PRICE_FORECAST.expected_price("WHEAT", t) for t in range(day, 29))
        feed_cost_model = "PriceForecast_expected_spot_replacement"
    else:
        wheat_price = float(market_price("WHEAT", wheat_inv))
        feed_cost = feed_days * wheat_price
        feed_cost_model = "live_market_spot_fallback"

    if not production_events:
        return {
            "species": sp, "day": day, "viable": False,
            "net_realized_value": -cost - feed_cost,
            "gross_product_revenue": 0.0,
            "gross_fertilizer_revenue": 0.0,
            "feed_cost": round(feed_cost, 2),
            "feed_cost_model": feed_cost_model,
            "purchase_cost": cost,
            "pasture_opportunity_cost": 0.0,
            "market_impact_cost": 0.0,
            "marginal_product_revenue": 0.0,
            "liquidation_discount": 0.0,
            "production_events": [],
            "reason": "insufficient_time_for_maturity",
        }

    # 2. Sequential Joint-Path Counterfactual Market Simulation
    exist_rate = current_count * (float(recurring_yield) / float(interval))
    base_inv = float(market_inventory.get(prod_item, MARKET_I0)) if market_inventory else float(MARKET_I0)

    known_daily_drain = TC_DEMAND.get(prod_item, 1.0) + sum(
        SHOP_DEMAND_RATES.get(prod_item, {}).get(s, 0.0) for s in (town_shops or [])
    )

    future_events = [ed for ed in UNLOCK_DAYS if day < ed <= 28]
    k = len(future_events)
    hit_rate = 12.0 if sp == "SHEEP" else 6.0
    n_hits = 1 if sp == "SHEEP" else (3 if sp == "COW" else 2)
    n_miss = 8 - n_hits
    denom = 8 ** k

    total_delta_rev = 0.0
    total_cand_rev = 0.0

    # Enumerate all 2^k joint future shop paths (at most 256 paths)
    for seq in itertools.product([0, 1], repeat=k):
        # Exact integer probability representation
        hits = sum(seq)
        misses = k - hits
        path_num = (n_hits ** hits) * (n_miss ** misses)
        prob = path_num / float(denom)

        inv_without = base_inv
        inv_with = base_inv
        rev_without = 0.0
        rev_with = 0.0
        cand_rev = 0.0

        for t in range(day, 29):
            # Same future unlock path applies consistently across every day
            drain = known_daily_drain + sum(
                seq[j] * hit_rate for j, ed in enumerate(future_events) if ed <= t
            )

            s_without = exist_rate
            s_with = exist_rate + cand_units[t]

            # Engine order of operations:
            # 1. Selling: Units enter market at beginning-of-day inventory
            p_without = float(market_price(prod_item, inv_without + s_without / 2.0)) if s_without > 0 else 0.0
            p_with = float(market_price(prod_item, inv_with + s_with / 2.0)) if s_with > 0 else 0.0

            rev_without += s_without * p_without
            rev_with += s_with * p_with
            cand_rev += cand_units[t] * p_with

            # 2. Town consumption: subtracts drain from post-sale inventory
            inv_without = max(1.0, inv_without + s_without - drain)
            inv_with = max(1.0, inv_with + s_with - drain)

        total_delta_rev += prob * (rev_with - rev_without)
        total_cand_rev += prob * cand_rev

    market_impact_cost = max(0.0, total_cand_rev - total_delta_rev)

    # 3. Fertilizer Contribution & Sensitivity Audit
    fert_days = max(0, 28 - day) if sp in ("COW", "SHEEP") else 0
    fert_inv = market_inventory.get("FERTILIZER", MARKET_I0) if market_inventory else MARKET_I0
    # Simulate own fertilizer supply on market price curve
    gross_fert_rev = sum(
        float(market_price("FERTILIZER", fert_inv + i)) for i in range(fert_days)
    )

    # 4. Housing / Pasture Opportunity Cost
    pasture_opp_cost = 0.0
    if empty_pastures <= 0:
        pasture_opp_cost = 200.0 + max(0.0, float(crop_opportunity_val))

    # 5. Net Realized Value
    net_realized_val = (
        total_delta_rev
        + gross_fert_rev
        - cost
        - feed_cost
        - pasture_opp_cost
    )

    fertilizer_sensitivity = {
        "full_fertilizer": round(net_realized_val, 2),
        "half_fertilizer": round(net_realized_val - 0.5 * gross_fert_rev, 2),
        "zero_fertilizer": round(net_realized_val - gross_fert_rev, 2),
    }

    return {
        "species": sp,
        "day": day,
        "viable": bool(net_realized_val > 0),
        "net_realized_value": round(net_realized_val, 2),
        "marginal_product_revenue": round(total_delta_rev, 2),
        "gross_product_revenue": round(total_cand_rev, 2),
        "gross_fertilizer_revenue": round(gross_fert_rev, 2),
        "fertilizer_sensitivity": fertilizer_sensitivity,
        "feed_cost": round(feed_cost, 2),
        "feed_cost_model": feed_cost_model,
        "purchase_cost": cost,
        "pasture_opportunity_cost": round(pasture_opp_cost, 2),
        "market_impact_cost": round(market_impact_cost, 2),
        "liquidation_discount": 0.0,
        "production_events": production_events,
        "total_units_produced": sum(u for _, u in production_events),
        "joint_paths_evaluated": 2 ** k,
        "break_even": bool(net_realized_val > 0),
    }
