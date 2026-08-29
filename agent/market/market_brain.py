"""W-market 2/3: Sell-side decision layer.

Consumes live observation + PriceForecast (W1) + price_math (engine-exact
curves) and decides WHICH shed stock to sell, HOW MUCH per product, and WHEN
(sell windows, floor holds, drip slices).

Decision rules (in order):
  1. WINDOW: sells only on hours t % 4 == 1 — the engine's town shops drain
     at step % 4 == 0 and prices refresh right after, so hour≡1 quotes are
     post-drain boosted. Endgame day 29 dumps in every window.
  2. FLOOR HOLD: premium goods quoted at $1 are held while enough season
     remains for town drain to lift them (selling at $1 still books revenue
     but freezes inventory — holding is free upside).
  3. CARRY CHECK: hold a product if E[P | day+horizon] exceeds today's spot
     by more than MIN_CARRY_GAIN AND the shed is not under soft-cap pressure.
  4. DRIP SLICE: quantity = largest slice whose LAST unit still realizes
     >= keep_frac * spot (price_math.inventory_for_price_at_least), clamped
     by shed stock and by wheat reserved for animal feed.
  5. SLOTS: sells take at most SELL_SLOT_SHARE of the order cap; candidates
     ranked by shed-share urgency (round-robin emerges as leaders empty).

Self-competition awareness: drip sizing is computed against LIVE market
inventory, which already includes this farm's earlier same-day sales, so
slices automatically shrink as we move our own curve. The reference E[P|day]
is used only for carry/hold comparisons, never as an average sell price.
"""
from config import (
    CARRY_HORIZON_DAYS,
    DRIP_PRICE_KEEP_FRAC,
    ENDGAME_RISK_DAYS,
    ENDGAME_START_DAY,
    FEED_WHEAT_BUFFER_DAYS,
    FINAL_DUMP_DAYS,
    FLOOR_HOLD_MIN_DAYS_LEFT,
    HOLD_AT_FLOOR_PRODUCTS,
    MAX_MARKET_ORDERS,
    MIN_SLICE_QTY,
    MIN_CARRY_GAIN,
    SELL_HOUR_SET,
    SELL_SLOT_SHARE,
    SHED_SOFT_CAP,
)

from market.price_math import (
    inventory_for_price_at_least,
    market_price,
    total_revenue_estimate,
)

SELLABLE = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY",
            "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")


class MarketBrain:
    def __init__(self, forecast):
        self.fc = forecast

    # ------------------------------------------------------------------
    def sell_orders(self, ctx, max_slots=None, opp_advice=None):
        """Returns (orders, details). orders: [["SELL", prod, qty], ...].

        v5.9: Sell every hour (not just t%4==1) to fund mandatory hires.
        Batch sizes follow spec:
          Days 0-5:  10-20 units per product
          Days 6-8:  5-10 units
          Days 9+:   3-5 units
        Carry/floor holds are relaxed — cash flow > price optimization.
        """
        if max_slots is None:
            max_slots = int(MAX_MARKET_ORDERS * SELL_SLOT_SHARE)
        day, hour = ctx["day"], ctx["hour"]
        days_left = 29 - day
        endgame = day >= ENDGAME_START_DAY

        shed = ctx["private"].shed
        animals = sum(1 for t in ctx["farm"].iter_tiles() if t.is_animal)
        reserved_wheat = 0 if endgame else animals * FEED_WHEAT_BUFFER_DAYS
        shed_total = sum(shed.get(p, 0) for p in SELLABLE)
        pressure = shed_total >= SHED_SOFT_CAP

        # v5.9: Sell every hour (cash flow for hires) except hour 0 (purchases)
        if hour == 0 and not endgame:
            return [], {"reason": "hour0_purchases"}

        # Phase 6: extract opp_advice sets for fast lookup
        preempt_set = set(opp_advice.preempt_sell) if opp_advice else set()
        delay_set = set(opp_advice.delay_sell) if opp_advice else set()

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}
        candidates = []
        
        # v5.9: Spec batch sizes per phase
        if day <= 5:
            batch_target = 15  # sell 10-20 units
        elif day <= 8:
            batch_target = 7   # sell 5-10 units
        else:
            batch_target = 4   # sell 3-5 units
        
        for prod in SELLABLE:
            if prod in delay_set and not endgame:
                continue
            stock = int(shed.get(prod, 0))
            if stock <= 0:
                continue
            if prod == "WHEAT":
                stock = max(0, stock - reserved_wheat)
                if stock <= 0:
                    continue
            elif prod == "FERTILIZER" and not endgame:
                # Reserve fertilizer needed for crops during daytime application hours (max 2 per day)
                if hour <= 18:
                    fert_needed = sum(1 for t in ctx["farm"].iter_tiles()
                                      if t.is_plant and t.crop in ("STRAWBERRY", "TOMATO", "MELON")
                                      and t.fertilized_until_day < day)
                    fert_reserve = min(2, fert_needed)
                else:
                    fert_reserve = 0
                stock = max(0, stock - fert_reserve)
                if stock <= 0:
                    continue
            spot = market_price(prod, inv.get(prod, 10000))
            
            # v5.9: Never hold at floor — sell everything for cash flow
            if spot <= 1:
                qty = stock if endgame else min(stock, batch_target)
                if qty > 0:
                    candidates.append({
                        "product": prod, "qty": int(qty), "spot": spot,
                        "avg_est": spot, "reason": "floor_sell",
                        "urgency": 0.5,
                    })
                continue

            # v5.9: In endgame/aggressive mode or for surplus fertilizer, dump stock; otherwise sell at spec batch size
            aggressive = endgame or days_left <= ENDGAME_RISK_DAYS or pressure
            qty = stock if (endgame or days_left <= 2 or prod == "FERTILIZER") else min(stock, batch_target)
            
            if qty <= 0:
                continue

            avg_est = total_revenue_estimate(prod, inv.get(prod, 10000),
                                             qty) / qty
            reason = "spec_batch_sell"
            urgency = stock / (shed_total or 1)

            # --- Phase 6: preempt sell urgency boost ----------------
            if prod in preempt_set:
                urgency = max(urgency, 0.99)
                reason = "preempt_dump"

            candidates.append({
                "product": prod, "qty": int(qty), "spot": spot,
                "avg_est": round(avg_est, 2), "reason": reason,
                "urgency": urgency,
            })

        candidates.sort(key=lambda c: -c["urgency"])
        chosen = candidates[:max_slots]
        orders = [["SELL", c["product"], c["qty"]] for c in chosen]
        return orders, {"candidates": candidates, "days_left": days_left,
                        "endgame": endgame, "pressure": pressure}

    # ------------------------------------------------------------------
    def _drip_budget(self, prod, current_inv, keep_frac, spot):
        threshold = max(2, int(spot * keep_frac))
        limit = inventory_for_price_at_least(prod, threshold)
        budget = int(limit - float(current_inv))
        return max(0, budget)

    def _is_sell_hour(self, day, hour):
        return hour in SELL_HOUR_SET

    def _reason(self, prod, spot, carry, aggressive, pressure):
        if aggressive:
            return "endgame_dump" if spot <= 1 else "aggressive_slice"
        if pressure:
            return "shed_pressure"
        return "carry_fail" if carry <= MIN_CARRY_GAIN else "carry_hold"

    # ------------------------------------------------------------------
    @staticmethod
    def compose(purchase_orders, sell_orders, cap=MAX_MARKET_ORDERS,
                purchases_first=False):
        """Merge purchase + sell queues under the engine's per-turn cap.

        Default priority: SELLS first (they book revenue and free shed space;
        missing a buy costs one turn, but overflowing the shed destroys
        goods). Pass purchases_first=True for the hour-0 hire/seed block.
        """
        first, second = ((purchase_orders, sell_orders) if purchases_first
                         else (sell_orders, purchase_orders))
        out = [list(o) for o in first][:cap]
        out += [list(o) for o in second][:cap - len(out)]
        return out
