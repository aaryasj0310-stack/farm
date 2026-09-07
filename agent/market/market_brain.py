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
    SHED_RESUME_CAP,
    MELON_SEASON_SALE_CAP,
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

        v5.12 Leader-calibrated sell policy:
          Two-tier shed relief:
            - Midnight hard-guard (hour >= 22 and shed_total > 88): urgency 2, dump inventory
            - Emergency relief (shed_total >= SHED_SOFT_CAP (65)): urgency 1, override 4h window,
              sell until shed <= SHED_RESUME_CAP (55)
            - Normal mode (hour in SELL_HOUR_SET): urgency 0, post-drain sell windows
          Order budget:
            - Decrement order_budget -= 1 per order slice (MAX_MARKET_ORDERS = 10 is order count)
          Feed protection:
            - Reserved wheat = animals * FEED_WHEAT_BUFFER_DAYS strictly protected from sale
          Melon quadratic cliff protection:
            - Cumulative season melons sold capped at MELON_SEASON_SALE_CAP (150)
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

        # Hour 0 purchases block sells in normal mode (unless endgame, emergency relief, or midnight guard)
        if hour == 0 and not endgame and not pressure and not (hour >= 22 and shed_total > 88):
            return [], {"reason": "hour0_purchases"}

        # Two-tier urgency:
        # 2 = midnight hard-guard, 1 = emergency relief, 0 = normal post-drain window
        if hour >= 22 and shed_total > 88:
            urgency = 2
        elif pressure:
            urgency = 1
        elif (hour in SELL_HOUR_SET) or endgame:
            urgency = 0
        else:
            return [], {"reason": "waiting_for_sell_window"}

        # Phase 6: extract opp_advice sets for fast lookup
        preempt_set = set(opp_advice.preempt_sell) if opp_advice else set()
        delay_set = set(opp_advice.delay_sell) if opp_advice else set()

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}

        # Spec batch sizes per phase
        if day <= 5:
            batch_target = 15  # sell 10-20 units
        elif day <= 8:
            batch_target = 7   # sell 5-10 units
        else:
            batch_target = 4   # sell 3-5 units

        # Available stock per product respecting reserves & caps
        available_stock = {}
        for prod in SELLABLE:
            if prod in delay_set and not endgame and urgency < 2:
                continue
            stock = int(shed.get(prod, 0))
            if stock <= 0:
                continue
            if prod == "WHEAT":
                stock = max(0, stock - reserved_wheat)
            elif prod == "FERTILIZER" and not endgame and urgency < 2:
                if hour <= 18:
                    fert_needed = sum(1 for t in ctx["farm"].iter_tiles()
                                      if t.is_plant and t.crop in ("STRAWBERRY", "TOMATO", "MELON")
                                      and t.fertilized_until_day < day)
                    fert_reserve = min(2, fert_needed)
                else:
                    fert_reserve = 0
                stock = max(0, stock - fert_reserve)
            elif prod == "MELON" and urgency < 2:
                season_melons_sold = 0
                try:
                    from state.state_tracker import get_state
                    season_melons_sold = get_state().get("our_units_sold", {}).get("MELON", 0)
                except Exception:
                    try:
                        from state_tracker import get_state
                        season_melons_sold = get_state().get("our_units_sold", {}).get("MELON", 0)
                    except Exception:
                        pass
                melon_budget = max(0, MELON_SEASON_SALE_CAP - season_melons_sold)
                stock = min(stock, melon_budget)

            if stock > 0:
                available_stock[prod] = stock

        if not available_stock:
            return [], {"reason": "no_available_stock", "pressure": pressure}

        # Order budget in order slots (engine cap is 10 orders per turn)
        order_budget = MAX_MARKET_ORDERS if (urgency >= 1 or endgame) else max_slots

        # Slicing target for emergency relief
        to_shed = max(0, shed_total - SHED_RESUME_CAP) if urgency == 1 else shed_total

        # Candidate product ordering
        # In emergency mode (when not endgame), follow liquidation priority: WHEAT -> CARROT -> TOMATO -> EGG -> MILK -> WOOL -> STRAWBERRY -> MELON -> FERTILIZER
        LIQUIDATION_PRIORITY = ("WHEAT", "CARROT", "TOMATO", "EGG", "MILK", "WOOL", "STRAWBERRY", "MELON", "FERTILIZER")

        candidates = []
        for prod in SELLABLE:
            if prod not in available_stock:
                continue
            st = available_stock[prod]
            spot = market_price(prod, inv.get(prod, 10000))
            urgency_score = st / (shed_total or 1)
            if spot <= 1:
                urgency_score = 0.95
            if prod in preempt_set:
                urgency_score = 0.99
            candidates.append({"product": prod, "spot": spot, "urgency": urgency_score, "stock": st})

        if urgency >= 1 and not endgame:
            prio_map = {p: i for i, p in enumerate(LIQUIDATION_PRIORITY)}
            candidates.sort(key=lambda c: (0 if c["product"] in preempt_set else 1, prio_map.get(c["product"], 99)))
        else:
            candidates.sort(key=lambda c: -c["urgency"])

        orders = []
        for c in candidates:
            if order_budget <= 0:
                break
            if not endgame and urgency == 1 and to_shed <= 0:
                break
            prod = c["product"]
            st = available_stock[prod]
            if st <= 0:
                continue

            bt = batch_target

            if endgame or days_left <= 2 or urgency == 2 or prod == "FERTILIZER":
                slice_qty = min(st, 20)
            elif urgency == 1:
                slice_qty = min(st, bt if bt > 10 else 10, to_shed)
            else:
                slice_qty = min(st, bt)

            if slice_qty <= 0:
                continue

            orders.append(["SELL", prod, int(slice_qty)])
            available_stock[prod] -= slice_qty
            if urgency == 1:
                to_shed -= slice_qty
            order_budget -= 1

            # In emergency mode, allow multiple slices of the overflowing product if to_shed remains
            if not endgame and urgency == 1 and to_shed > 0 and order_budget > 0 and available_stock[prod] > 0:
                while order_budget > 0 and to_shed > 0 and available_stock[prod] > 0:
                    extra_qty = min(available_stock[prod], bt if bt > 10 else 10, to_shed)
                    if extra_qty <= 0:
                        break
                    orders.append(["SELL", prod, int(extra_qty)])
                    available_stock[prod] -= extra_qty
                    to_shed -= extra_qty
                    order_budget -= 1

        return orders, {"candidates": candidates, "days_left": days_left,
                        "endgame": endgame, "pressure": pressure, "urgency": urgency}

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
