"""Market-aware marginal livestock valuation.

Calculates the true realized marginal net value of adding one specific additional
animal (COW or SHEEP) on day D, accounting for:
- Exact engine yield timing (gestation lag, intervals, care bonus)
- Market price response curve (including own-supply price depression on existing herd output)
- Town shop drain and market inventory saturation
- Pasture crop opportunity cost (if new pasture construction is required)
- Authoritative remaining feed procurement cost
- Late-season liquidation discount / unsold inventory risk
"""
from typing import Dict, Any, List, Optional
import math

from config import (
    MARKET_I0, MARKET_PARAMS, PRICE_FLOOR,
    ANIMALS, CROPS
)
from market.price_math import market_price


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

    Returns a comprehensive breakdown of revenue, costs, penalties, and net realized value.
    """
    sp = str(species).upper()
    if sp not in ("COW", "SHEEP"):
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

    cost = ANIMALS[sp]["cost"]
    prod_item = ANIMALS[sp]["product"]  # MILK or WOOL
    current_count = current_animals.get(sp, 0)
    total_herd = sum(current_animals.values())

    # 1. Exact Production Schedule and Yields
    # In engine:
    # COW: first_yield_day = 8, interval = 2, first yield = 6, recurring = 3
    # SHEEP: first_yield_day = 6, interval = 3, first yield = 6, recurring = 4
    first_lag = ANIMALS[sp]["first_yield_day"]
    interval = ANIMALS[sp]["interval"]
    first_yield = 6
    recurring_yield = 4 if sp == "SHEEP" else 3

    production_events = []
    prod_day = day + first_lag
    while prod_day <= 28:
        units = first_yield if prod_day == (day + first_lag) else recurring_yield
        production_events.append((prod_day, units))
        prod_day += interval

    if not production_events:
        # Cannot complete even 1 production cycle before liquidation
        return {
            "species": sp, "day": day, "viable": False,
            "net_realized_value": -cost,
            "gross_product_revenue": 0.0,
            "gross_fertilizer_revenue": 0.0,
            "feed_cost": rem_days * 25.0,
            "purchase_cost": cost,
            "pasture_opportunity_cost": 0.0,
            "market_impact_cost": 0.0,
            "liquidation_discount": 0.0,
            "production_events": [],
            "reason": "insufficient_time_for_maturity",
        }

    # 2. Market-Aware Pricing with Own-Supply Effect
    # Baseline market inventory
    base_inv = float(market_inventory.get(prod_item, MARKET_I0)) if market_inventory else float(MARKET_I0)
    
    # Estimate daily town consumption of this product
    # Base town drain: ~3-5 units per day depending on shop roll
    daily_town_drain = 4.0 if sp == "SHEEP" else 5.0

    total_gross_product_rev = 0.0
    total_market_impact_penalty = 0.0
    total_liquidation_discount = 0.0

    # For each production batch, project market inventory and own-supply impact
    for p_day, new_units in production_events:
        days_from_now = p_day - day
        # Estimate how much output existing herd will produce between now and p_day
        # Existing sheep produce ~4/3 = 1.33 units/day each; cows ~3/2 = 1.5 units/day each
        existing_daily_rate = (1.33 if sp == "SHEEP" else 1.5) * current_count
        projected_existing_flow = existing_daily_rate * days_from_now
        projected_drain = daily_town_drain * days_from_now

        # Inventory in market when existing batch sells
        inv_without = max(MARKET_I0 - 50, base_inv + projected_existing_flow - projected_drain)
        inv_with = inv_without + new_units

        # Prices with and without the marginal animal
        price_without = market_price(prod_item, inv_without)
        price_with = market_price(prod_item, inv_with)

        # Revenue from new animal's units at depressed price
        batch_revenue = new_units * price_with

        # Own-supply price depression penalty on existing herd's output on that same day:
        # Existing herd output on this production day is roughly existing_daily_rate * interval
        existing_batch_units = existing_daily_rate * interval
        depression_penalty = existing_batch_units * max(0, price_without - price_with)

        # Liquidation discount on final day (Day 28):
        # Product arriving on Day 28 has very few market hours before turn 719.
        # Often only partially drained by town shops before game end.
        liq_disc = 0.0
        if p_day >= 28:
            liq_disc = batch_revenue * 0.40  # 40% discount for end-of-game market saturation

        total_gross_product_rev += batch_revenue
        total_market_impact_penalty += depression_penalty
        total_liquidation_discount += liq_disc

    # Net realized product revenue after market impact and liquidation risk
    net_product_rev = total_gross_product_rev - total_market_impact_penalty - total_liquidation_discount

    # 3. Fertilizer Contribution
    # 1 fertilizer per day after placement (day + 1 through day 28)
    fert_days = max(0, 28 - (day + 1))
    fert_price = 100.0  # base fertilizer price
    if market_inventory:
        fert_inv = market_inventory.get("FERTILIZER", MARKET_I0)
        fert_price = float(market_price("FERTILIZER", fert_inv))
    gross_fert_rev = fert_days * fert_price

    # 4. Feed Cost
    # 1 bushel of wheat per day through day 28
    feed_cost = rem_days * 25.0

    # 5. Pasture Opportunity Cost
    # If an empty pasture is already built, cost is 0.
    # Otherwise, converting a soil tile forfeits that tile's crop revenue.
    pasture_opp_cost = 0.0
    if empty_pastures <= 0:
        pasture_opp_cost = max(0.0, crop_opportunity_val)

    # 6. Salvage Value
    salvage_value = 100.0  # animals sell for 100 at Day 28 liquidation

    # Total Net Realized Value
    net_realized_value = (
        net_product_rev
        + gross_fert_rev
        + salvage_value
        - feed_cost
        - cost
        - pasture_opp_cost
    )

    return {
        "species": sp,
        "day": day,
        "viable": bool(net_realized_value > 0),
        "gross_product_revenue": round(total_gross_product_rev, 1),
        "gross_fertilizer_revenue": round(gross_fert_rev, 1),
        "salvage_value": salvage_value,
        "feed_cost": round(feed_cost, 1),
        "purchase_cost": cost,
        "pasture_opportunity_cost": round(pasture_opp_cost, 1),
        "market_impact_cost": round(total_market_impact_penalty, 1),
        "liquidation_discount": round(total_liquidation_discount, 1),
        "net_realized_value": round(net_realized_value, 1),
        "production_events": production_events,
        "total_units_produced": sum(u for _, u in production_events),
    }
