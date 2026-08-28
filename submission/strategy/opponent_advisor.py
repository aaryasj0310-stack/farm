"""Pillar 5: Actionable Opponent Responses — Tactical Advisor.

Translates raw opponent observations into structured guidance that
MacroPlanner and MarketBrain can consume:

  - supply_adjustment: per-product extra future supply (opp production * weight)
    so MacroPlanner's _crop_score penalises crowded commodities.
  - preempt_sell: products to sell immediately before opponent dumps.
  - delay_sell: products to hold because opponent just crashed the price.
  - counter_pick: shop-demanded products opponent is completely ignoring.
  - opp_shed_pressure: overall opponent shed pressure (0.0 to 1.0).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from config import PRODUCTS, SHOPS


# ---------------------------------------------------------------------------
# Advice dataclass
# ---------------------------------------------------------------------------

@dataclass
class OpponentAdvice:
    """Structured guidance produced by build_opponent_advice."""
    supply_adjustment: Dict[str, float] = field(default_factory=dict)
    preempt_sell: List[str] = field(default_factory=list)
    delay_sell: List[str] = field(default_factory=list)
    counter_pick: List[str] = field(default_factory=list)
    opp_shed_pressure: float = 0.0

    def to_dict(self):
        return {
            "supply_adjustment": dict(self.supply_adjustment),
            "preempt_sell": list(self.preempt_sell),
            "delay_sell": list(self.delay_sell),
            "counter_pick": list(self.counter_pick),
            "opp_shed_pressure": round(
                max(0.0, min(1.0, self.opp_shed_pressure)), 4,
            ),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPLY_ADJUSTMENT_WEIGHT = 0.50     # opp projected units * weight
SUPPLY_PROJECTION_DAYS = 12         # forward projection horizon
PREEMPT_SELL_THRESHOLD = 0.65       # opp sell probability >= this triggers
DELAY_PRICE_DEPRESSION_PCT = 0.80   # price below 80 % of expected = depressed
DELAY_RECENT_TURNS = 3              # look back N turns for recent dumps
COUNTER_PICK_DEMAND_MIN = 0.01      # minimum town demand signal (boost > 0)


# ---------------------------------------------------------------------------
# Core advisor
# ---------------------------------------------------------------------------

def build_opponent_advice(opp_state, ctx, forecast, boosts=None):
    """Translate opponent observations into actionable OpponentAdvice.

    Args:
      opp_state: dict with keys:
        - estimated_shed: dict {product: count}
        - sell_probs: dict {product: probability}  [0.0, 1.0]
        - opp_sales_inferred: dict {product: cumulative_inferred_units}
        - shed_pressure: float  [0.0, 1.0]
        - forecast: dict {product: {day: units}} from forecast_opponent_production
      ctx: parsed observation dict with 'farm', 'private', 'day', 'hour', etc.
      forecast: dict {product: {day: units}} from forecast_opponent_production
        (if not in opp_state, this is used as the primary forecast source).
      boosts: dict {product: float} optional town demand / shop boosts.
        Keyed by product; values > 0 indicate active town demand.

    Returns:
      OpponentAdvice with all fields populated.
    """
    advice = OpponentAdvice()

    estimated_shed = opp_state.get("estimated_shed", {})
    sell_probs = opp_state.get("sell_probs", {})
    opp_sales = opp_state.get("opp_sales_inferred", {})
    shed_pressure = opp_state.get("shed_pressure", 0.0)
    fc = forecast or opp_state.get("forecast", {})
    # Handle ctx["private"] as either dict or object with .shed attribute
    if ctx and "private" in ctx:
        priv = ctx["private"]
        our_shed = priv.shed if hasattr(priv, "shed") else (priv.get("shed", {}) if isinstance(priv, dict) else {})
    else:
        our_shed = {}
    day = ctx.get("day", 0) if ctx else 0

    # ---- 5a. Anti-Glut Supply Adjustment --------------------------------
    advice.supply_adjustment = _compute_supply_adjustment(fc, day)

    # ---- 5b. Pre-emptive Rush Selling -----------------------------------
    advice.preempt_sell = _compute_preempt_sell(sell_probs, our_shed)

    # ---- 5c. Sell Delay / Post-Crash Hold -------------------------------
    advice.delay_sell = _compute_delay_sell(
        opp_sales, our_shed, fc, day, ctx,
    )

    # ---- 5d. Counter-Pick Monopoly Detection ----------------------------
    advice.counter_pick = _compute_counter_pick(boosts, opp_state)

    # ---- 5e. Shed Pressure Pass-Through ---------------------------------
    advice.opp_shed_pressure = float(max(0.0, min(1.0, shed_pressure)))

    return advice


# ---------------------------------------------------------------------------
# Sub-computations
# ---------------------------------------------------------------------------

def _compute_supply_adjustment(forecast, current_day):
    """Project opponent production over next SUPPLY_PROJECTION_DAYS."""
    adj = {}
    if not forecast:
        return adj
    horizon = current_day + SUPPLY_PROJECTION_DAYS
    for product, schedule in forecast.items():
        total = 0.0
        for d, units in schedule.items():
            if current_day <= d <= horizon:
                total += units
        if total > 0:
            adj[product] = round(total * SUPPLY_ADJUSTMENT_WEIGHT, 4)
    return adj


def _compute_preempt_sell(sell_probs, our_shed):
    """Flag products we hold where opponent sell prob >= threshold."""
    result = []
    if not sell_probs:
        return result
    for product, prob in sorted(sell_probs.items(),
                                key=lambda kv: -kv[1]):
        if prob < PREEMPT_SELL_THRESHOLD:
            continue
        if our_shed.get(product, 0) <= 0:
            continue
        result.append(product)
    return result


def _compute_delay_sell(opp_sales, our_shed, forecast, current_day, ctx):
    """Flag products opponent recently dumped causing depressed prices."""
    result = []
    if not opp_sales or not our_shed:
        return result

    for product, cum_units in opp_sales.items():
        if cum_units <= 0:
            continue
        if our_shed.get(product, 0) <= 0:
            continue

        # Compute expected price from forecast to check depression
        expected = 0.0
        if product in forecast:
            # Use nearest forecast day
            best_day = min(forecast[product].keys(),
                           key=lambda d: abs(d - current_day),
                           default=None)
            if best_day is not None:
                expected = forecast[product][best_day]

        # Get current spot price from market inventory
        market_obj = ctx.get("market") if ctx else None
        if isinstance(market_obj, dict):
            inv = market_obj.get("inventory", market_obj)
        else:
            inv = getattr(market_obj, "inventory", {}) if market_obj else {}
        current_inv = inv.get(product, 10000)

        # Import market_price at function scope to avoid circular import issues
        from market.price_math import market_price
        spot = market_price(product, current_inv)

        # Check if price is depressed relative to expected
        if expected > 0 and spot < expected * DELAY_PRICE_DEPRESSION_PCT:
            result.append(product)

    return result


def _compute_counter_pick(boosts, opp_state):
    """Find shop-demanded products opponent completely ignores."""
    result = []
    if not boosts:
        return result

    # Get opponent commitment summary — check crop and animal counts
    opp_commitments = opp_state.get("commitments", {})
    crop_tiles = opp_commitments.get("crop_tiles", {})
    animal_counts = opp_state.get("animal_counts", {})

    # Collect all products opponent is producing
    opp_products = set()
    for product, count in crop_tiles.items():
        if count > 0:
            opp_products.add(product)
    for animal, count in animal_counts.items():
        if count > 0:
            # Map animal to its product
            animal_product_map = {
                "GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL",
            }
            if animal in animal_product_map:
                opp_products.add(animal_product_map[animal])

    # Find products with demand but zero opponent commitment
    for product, demand in boosts.items():
        if demand > COUNTER_PICK_DEMAND_MIN and product not in opp_products:
            result.append(product)

    return sorted(result)
