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
    def sell_orders(self, ctx, max_slots=None):
        """Returns (orders, details). orders: [["SELL", prod, qty], ...]."""
        if max_slots is None:
            max_slots = int(MAX_MARKET_ORDERS * SELL_SLOT_SHARE)
        day, hour = ctx["day"], ctx["hour"]
        days_left = 29 - day
        endgame = day >= ENDGAME_START_DAY

        if not self._is_sell_hour(day, hour) and not (endgame and day == 29):
            return [], {"reason": "not_a_sell_window"}

        shed = ctx["private"].shed
        animals = sum(1 for t in ctx["farm"].iter_tiles() if t.is_animal)
        reserved_wheat = animals * FEED_WHEAT_BUFFER_DAYS
        shed_total = sum(shed.get(p, 0) for p in SELLABLE)
        pressure = shed_total >= SHED_SOFT_CAP

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}
        candidates = []
        for prod in SELLABLE:
            stock = int(shed.get(prod, 0))
            if stock <= 0:
                continue
            if prod == "WHEAT":
                stock = max(0, stock - reserved_wheat)
                if stock <= 0:
                    continue
            spot = market_price(prod, inv.get(prod, 10000))
            keep_frac = DRIP_PRICE_KEEP_FRAC.get(prod, 0.95)

            # --- rule: floor hold ------------------------------------
            if spot <= 1 and prod in HOLD_AT_FLOOR_PRODUCTS \
                    and days_left >= FLOOR_HOLD_MIN_DAYS_LEFT and not endgame:
                continue

            # --- rule: carry check -----------------------------------
            horizon_day = min(day + CARRY_HORIZON_DAYS, 29)
            e_future = self.fc.expected_price(prod, horizon_day)
            carry = (e_future / spot - 1.0) if spot > 0 else 0.0
            aggressive = endgame or days_left <= ENDGAME_RISK_DAYS or pressure
            hold_for_recovery = (
                carry > MIN_CARRY_GAIN
                and not pressure
                and days_left > ENDGAME_RISK_DAYS
                and prod not in HOLD_AT_FLOOR_PRODUCTS
            )
            if hold_for_recovery and not aggressive:
                continue

            # --- quantity ---------------------------------------------
            if spot <= 1:
                # Floor freeze: sales here have ZERO market impact, so once
                # aggressive we dump ALL of it (each unit still books $1);
                # outside aggressive mode only a token slice escapes.
                qty = stock if aggressive else MIN_SLICE_QTY
            else:
                eff_keep = keep_frac if not aggressive else min(keep_frac, 0.60)
                q_max = self._drip_budget(prod, inv.get(prod, 10000),
                                          eff_keep, spot)
                if q_max >= MIN_SLICE_QTY:
                    qty = min(stock, q_max)
                elif aggressive:
                    qty = min(stock, 1)
                else:
                    qty = 0
            if qty <= 0:
                continue

            avg_est = total_revenue_estimate(prod, inv.get(prod, 10000),
                                             qty) / qty
            reason = self._reason(prod, spot, carry, aggressive, pressure)
            candidates.append({
                "product": prod, "qty": int(qty), "spot": spot,
                "avg_est": round(avg_est, 2), "reason": reason,
                "urgency": stock / (shed_total or 1),
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
