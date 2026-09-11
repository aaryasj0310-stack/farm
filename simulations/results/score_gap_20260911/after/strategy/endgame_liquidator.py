"""W-market 3/3: Endgame liquidation policy.

Orchestrates days >= ENDGAME_START_DAY:
  - classifies every shed product as HOLD-FOR-RECOVERY or DUMP-NOW using the
    validated forecast (E[P|29] uplift vs today, floor probability at 29)
  - emits aggressive sell slices via market_brain (round-robin across
    products so no single glut curve eats the whole order cap)
  - harvesting is left to task_scheduler, which already prioritizes any tile
    with yield_units > 0; this module only guarantees the RESULTING stock
    gets sold before day 30 (unsold inventory is worth zero at scoring)

No crop-specific logic: classification is purely price-distribution driven.
"""
from config import (
    ENDGAME_RISK_DAYS,
    MAX_MARKET_ORDERS,
)

from market.market_brain import MarketBrain


class EndgameLiquidator:
    def __init__(self, forecast, brain=None):
        self.fc = forecast
        self.brain = brain or MarketBrain(forecast)

    # ------------------------------------------------------------------
    def should_liquidate_now(self, product, day):
        """True when waiting for day-29 prices no longer pays.

        Rule: dump if the expected uplift from holding to day 29 is under
        2% OR if there is a material chance the price sits at the $1 floor
        on day 29 (recovery already failed).
        """
        spot_day = min(day, 29)
        e_now = self.fc.expected_price(product, spot_day)
        e_end = self.fc.expected_price(product, 29)
        if e_now <= 0:
            return True
        uplift = e_end / e_now - 1.0
        p_floor_end = self.fc.prob_floor(product, 29)
        return uplift < 0.02 or p_floor_end > 0.30

    # ------------------------------------------------------------------
    def plan(self, ctx, max_slots=MAX_MARKET_ORDERS, opp_advice=None):
        """Aggressive endgame sells for THIS turn.

        Uses MarketBrain in its naturally aggressive endgame mode and then
        tops up: any product with remaining stock that was skipped due to
        drip budgeting gets a follow-up slice on later windows automatically
        (stock shrinks monotonically), so round-robin coverage emerges.
        """
        orders, details = self.brain.sell_orders(ctx, max_slots=max_slots,
                                                 opp_advice=opp_advice)
        details["liquidated_products"] = sorted(
            c["product"] for c in details.get("candidates", []))
        return orders, details

    # ------------------------------------------------------------------
    def harvest_priorities(self, ctx):
        """Tiles whose yield should leave the farm TODAY (scheduler already
        emits HARVEST for these; exposed for tests/visibility)."""
        out = []
        for t in ctx["farm"].iter_tiles():
            if t.is_plant and t.yield_units > 0:
                out.append({"pos": t.pos, "crop": t.crop,
                            "units": t.yield_units})
            elif t.is_animal and t.yield_units > 0:
                out.append({"pos": t.pos, "crop": t.animal,
                            "units": t.yield_units})
        return out
