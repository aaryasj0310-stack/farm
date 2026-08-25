"""Town-drain dynamics, price recovery half-life and holding EV.

Drain model (per rules):
  - Town center: 1 unit of every product (except fertilizer) per day, flat.
  - Each unlocked shop instance consumes its demanded products every 4 turns
    = 6/day (single-product shops 2x = 12/day).

Recovery model after dumping Q units at turn 0 (spec formula):
  inv(t) = max(I0, inv(0) + Q_eff - D * t)     [t in days; clamp at I0]
where Q_eff respects the $1-floor freeze by default (units sold into a $1
quote never enter the market inventory).
"""
import math

from marginal_revenue_analyzer import simulate_sale_path
from price_curve_engine import I0, MARKET_PARAMS, compute_price

SHOP_DEMANDS = {
    "BAKERY":         {"EGG": 6, "WHEAT": 6},
    "PIZZA_SHOP":     {"MILK": 6, "TOMATO": 6, "WHEAT": 6},
    "BRUNCH_SPOT":    {"EGG": 6, "WHEAT": 6, "STRAWBERRY": 6},
    "YARN_STORE":     {"WOOL": 12},
    "ICE_CREAM_SHOP": {"STRAWBERRY": 6, "MILK": 6, "WHEAT": 6},
    "PET_CAFE":       {"CARROT": 12},
    "SMOOTHIE_SHOP":  {"STRAWBERRY": 6, "MILK": 6},
    "FARMERS_MARKET": {"WHEAT": 6, "CARROT": 6, "TOMATO": 6, "STRAWBERRY": 6},
}
SHOP_TYPES = list(SHOP_DEMANDS.keys())
TOWN_CENTER_DAILY = {
    "WHEAT": 1, "CARROT": 1, "TOMATO": 1, "STRAWBERRY": 1,
    "MELON": 1, "EGG": 1, "MILK": 1, "WOOL": 1,
}
TURNS_PER_DAY = 24


def daily_drain_rate(product, shops):
    """Units/day drained from `product` by town center + given shop instances."""
    d = TOWN_CENTER_DAILY.get(product, 0)
    for s in shops:
        d += SHOP_DEMANDS[s].get(product, 0)
    return int(d)


def worst_case_shops(product, n):
    """Deterministic 'worst case' shop mix: instances that demand `product`
    first (heaviest drain), then arbitrary fillers."""
    demanding = [s for s in SHOP_TYPES if product in SHOP_DEMANDS[s]]
    others = [s for s in SHOP_TYPES if s not in demanding]
    pool = (demanding * 8 + others)[:n] if n else []
    return pool[:n]


def simulate_recovery(product, dump_size, shops=(), start_inv=None,
                      days=30, respect_floor_rule=True):
    """Price trajectory after dumping `dump_size` units on day 0."""
    base = MARKET_PARAMS[product]["base"]
    inv0 = I0 if start_inv is None else float(start_inv)

    if respect_floor_rule:
        path = simulate_sale_path(product, inv0, dump_size)
        eff = path["units_added_to_market"]
        immediate_revenue = path["total_revenue"]
        inv = path["final_inventory"]
    else:
        eff = float(dump_size)
        immediate_revenue = dump_size * compute_price(product, int(inv0))
        inv = inv0 + eff

    drain = daily_drain_rate(product, shops)
    traj_days, traj_inv, traj_price = [], [], []
    for t in range(days + 1):
        price = compute_price(product, int(round(inv)))
        traj_days.append(t)
        traj_inv.append(inv)
        traj_price.append(price)
        inv = max(float(I0), inv - drain)

    def _days_to(price_threshold):
        for t, p in zip(traj_days, traj_price):
            if p >= price_threshold:
                return t
        return None

    return {
        "product": product,
        "dump_size": dump_size,
        "effective_dump_added": eff,
        "drain_per_day": drain,
        "shops": list(shops),
        "immediate_revenue": immediate_revenue,
        "base_price": base,
        "traj_day": traj_days,
        "traj_inventory": traj_inv,
        "traj_price": traj_price,
        "days_to_50pct_of_base": _days_to(math.ceil(0.5 * base)),
        "days_to_90pct_of_base": _days_to(math.ceil(0.9 * base)),
        "price_after_30_days": traj_price[-1],
    }


def holding_ev(product, quantity, shops=(), drip_days=5, start_inv=None):
    """Sell Q now vs drip-selling over N days alongside town consumption.

    Drip model: each day town drains first, then the player sells an equal
    slice at the post-drain (higher-priced) quote. Assumes the active shop
    set stays constant — extra unlocks would only improve drip pricing.
    """
    inv0 = I0 if start_inv is None else float(start_inv)
    now = simulate_sale_path(product, inv0, quantity)

    drain = daily_drain_rate(product, shops)
    inv = inv0
    rev = 0
    per_day = math.ceil(quantity / drip_days)
    remaining = quantity
    schedule = []
    for day in range(drip_days):
        inv -= drain  # town consumes throughout the day
        batch = min(per_day, remaining)
        res = simulate_sale_path(product, max(inv, 1), batch)
        rev += res["total_revenue"]
        remaining -= batch
        inv = res["final_inventory"]
        schedule.append({"day": day + 1, "sold": batch,
                         "avg_price": round(res["avg_realized_price"], 2)})
    return {
        "product": product,
        "quantity": quantity,
        "drip_days": drip_days,
        "drain_per_day": drain,
        "sell_now_revenue": now["total_revenue"],
        "sell_now_avg": round(now["avg_realized_price"], 2),
        "drip_revenue": rev,
        "drip_avg": round(rev / quantity, 2) if quantity else 0.0,
        "drip_schedule": schedule,
        "delta_drip_minus_now": rev - now["total_revenue"],
        "recommendation": ("DRIP-SELL" if rev > now["total_revenue"] else "SELL NOW"),
    }
