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
import math
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
    SHED_CAPACITY,
    MELON_SEASON_SALE_CAP,
)

try:
    from market.price_math import (
        inventory_at_price,
        inventory_for_price_at_least,
        market_price,
        safe_drip_budget,
        total_revenue_estimate,
    )
except ImportError:
    from price_math import (
        inventory_at_price,
        inventory_for_price_at_least,
        market_price,
        safe_drip_budget,
        total_revenue_estimate,
    )

DRIP_PROTECTED_PRODUCTS = ("MELON", "WOOL", "MILK", "STRAWBERRY")

SELLABLE = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY",
            "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")


def _get_season_units_sold(product):
    try:
        from state.state_tracker import get_our_units_sold
        return get_our_units_sold(product)
    except Exception:
        try:
            from state_tracker import get_our_units_sold
            return get_our_units_sold(product)
        except Exception:
            return 0


class MarketBrain:
    def __init__(self, forecast):
        self.fc = forecast

    # ------------------------------------------------------------------
    def _build_melon_diagnostics(self, ctx, melon_market_inv, shed, season_melons_sold,
                                 melon_sold_this_turn, is_floor_exception,
                                 melon_turn_drip_budget, melon_hold_reason_override=None,
                                 delay_set=None):
        melon_spot = market_price("MELON", melon_market_inv)
        melon_shed_inv = int(shed.get("MELON", 0))
        melon_cap_remaining = max(0, MELON_SEASON_SALE_CAP - season_melons_sold)
        safe_qty = melon_turn_drip_budget if not is_floor_exception else melon_shed_inv

        if melon_hold_reason_override is not None:
            hold_reason = melon_hold_reason_override
        elif melon_sold_this_turn > 0:
            hold_reason = None
        elif melon_spot <= 1 and not is_floor_exception:
            hold_reason = "floor_price_hold"
        elif melon_shed_inv <= 0:
            hold_reason = "no_shed_inventory"
        elif melon_cap_remaining <= 0:
            hold_reason = "season_cap_reached"
        elif safe_qty <= 0 and not is_floor_exception:
            hold_reason = "marginal_price_drop"
        elif delay_set and "MELON" in delay_set and not is_floor_exception:
            hold_reason = "opp_advice_delay"
        else:
            hold_reason = "held"

        return {
            "melon_spot": melon_spot,
            "melon_market_inventory": melon_market_inv,
            "melon_shed_inventory": melon_shed_inv,
            "melon_safe_quantity": safe_qty,
            "melon_sell_quantity": melon_sold_this_turn,
            "melon_units_sold_this_season": season_melons_sold,
            "melon_sale_cap_remaining": melon_cap_remaining,
            "melon_hold_reason": hold_reason,
        }

    # ------------------------------------------------------------------
    def sell_orders(self, ctx, max_slots=None, opp_advice=None):
        """Returns (orders, details). orders: [["SELL", prod, qty], ...].

        v5.12 Leader-calibrated sell policy with MELON marginal drip selling:
          Two-tier shed relief:
            - Midnight hard-guard (hour >= 22 and shed_total > 88): urgency 2, dump inventory
            - Emergency relief (shed_total >= SHED_SOFT_CAP (65)): urgency 1, override 4h window,
              sell until shed <= SHED_RESUME_CAP (55)
            - Normal mode (hour in SELL_HOUR_SET): urgency 0, post-drain sell windows
          Order budget:
            - Decrement order_budget -= 1 per order slice (MAX_MARKET_ORDERS = 10 is order count)
          Feed protection:
            - Reserved wheat = animals * FEED_WHEAT_BUFFER_DAYS strictly protected from sale
          Melon quadratic cliff & marginal drip protection:
            - Cumulative season melons sold capped at MELON_SEASON_SALE_CAP (150)
            - Normal & shed-relief sales strictly bounded by marginal price keep-fraction (0.90)
            - Floor price ($1) held in normal & shed-relief mode; liquidated only in endgame or urgency 2
        """
        # In Phase 3: max_slots=None allows full candidate exposure to CentralPlanner
        order_budget = max_slots
        day = ctx["day"]
        hour = ctx["hour"]

        days_left = 29 - day
        endgame = day >= ENDGAME_START_DAY

        shed = ctx["private"].shed
        private = ctx.get("private")
        scheduled_deposits = dict(ctx.get("scheduled_product_deposits", {}) or {})
        worker_inventories = list(getattr(private, "inventories", None) or []) if private else []
        carried_worker_inventory = sum(
            max(0, int(qty))
            for inv_row in worker_inventories
            for qty in (inv_row or {}).values()
        )
        held_animals = sum(
            cnt for inv in (getattr(private, "inventories", None) or [])
            for item, cnt in (inv or {}).items() if item in ("COW", "SHEEP", "GOOSE", "CHICKEN")
        ) if private else 0
        shed_animals = sum(
            int(shed.get(item, 0))
            for item in ("COW", "SHEEP", "GOOSE", "CHICKEN")
        ) if (shed and hasattr(shed, "get")) else 0
        animals = sum(1 for t in ctx["farm"].iter_tiles() if t.is_animal) + held_animals + shed_animals
        try:
            from config import get_p22a_day28_feed_harmonization_enabled
            p22a_enabled = bool(get_p22a_day28_feed_harmonization_enabled())
        except Exception:
            p22a_enabled = False

        if p22a_enabled:
            if day == 28:
                unfed_animals = sum(
                    1 for t in ctx["farm"].iter_tiles()
                    if t.is_animal and not getattr(t, "fed_today", False)
                )
                carried_wheat = sum(
                    int((inv_row or {}).get("WHEAT", 0))
                    for inv_row in worker_inventories
                )
                reserved_wheat = max(0, unfed_animals - carried_wheat)
            elif day >= 29:
                reserved_wheat = 0
            else:
                reserved_wheat = animals * FEED_WHEAT_BUFFER_DAYS
        else:
            reserved_wheat = 0 if endgame else animals * FEED_WHEAT_BUFFER_DAYS
        shed_total = sum(shed.get(p, 0) for p in SELLABLE)
        shed_occupancy = sum(max(0, int(v)) for v in shed.values())
        pending_occupancy = shed_occupancy + carried_worker_inventory
        # Preserve the production sell policy unless worker rollover would
        # actually overflow the shed. Carried goods auto-drop for free at EOD;
        # treating every carried unit as soft-cap pressure caused premature
        # liquidation and unnecessary logistics work.
        shed_pressure = shed_total >= SHED_SOFT_CAP
        rollover_overflow = pending_occupancy > SHED_CAPACITY
        pressure = shed_pressure or rollover_overflow

        try:
            from config import get_p61_pre_midnight_storage_hygiene_enabled
            p61_enabled = bool(get_p61_pre_midnight_storage_hygiene_enabled())
        except Exception:
            p61_enabled = False

        try:
            from execution.midnight_storage_controller import is_midnight_storage_dump_enabled
            m0b_enabled = is_midnight_storage_dump_enabled()
        except Exception:
            try:
                from agent.execution.midnight_storage_controller import is_midnight_storage_dump_enabled
                m0b_enabled = is_midnight_storage_dump_enabled()
            except Exception:
                m0b_enabled = False

        p61_hygiene_active = False
        p61_needed_relief = 0
        if (p61_enabled and (hour in (20, 21, 22))) or (m0b_enabled and (hour in (18, 19, 20, 21, 22))):
            projected_midnight_load = pending_occupancy
            target_load = 75
            if projected_midnight_load > target_load:
                p61_hygiene_active = True
                p61_needed_relief = max(0, projected_midnight_load - target_load)

        # Two-tier urgency:
        # 2 = midnight hard-guard, 1 = emergency relief, 0 = normal post-drain window
        if hour >= 22 and (shed_total > 88 or rollover_overflow):
            urgency = 2
        elif pressure or p61_hygiene_active:
            urgency = 1
        elif (hour in SELL_HOUR_SET) or endgame:
            urgency = 0
        else:
            urgency = -1

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}

        # Extract opp_advice sets for fast lookup
        preempt_set = set(opp_advice.preempt_sell) if opp_advice else set()
        delay_set = set(opp_advice.delay_sell) if opp_advice else set()

        # Product spot prices & price protection initialization
        spot_init_map = {p: market_price(p, inv.get(p, 10000.0)) for p in SELLABLE}
        melon_market_inv_init = float(inv.get("MELON", 10000.0))
        melon_spot_init = spot_init_map["MELON"]
        season_melons_sold = _get_season_units_sold("MELON")
        melon_cap_remaining = max(0, MELON_SEASON_SALE_CAP - season_melons_sold)
        is_floor_exception = endgame or (urgency == 2)

        keep_frac = DRIP_PRICE_KEEP_FRAC.get("MELON", 0.90)
        if melon_spot_init <= 1 and not is_floor_exception:
            melon_turn_drip_budget = 0
        else:
            melon_turn_drip_budget = self._drip_budget("MELON", melon_market_inv_init, keep_frac, melon_spot_init)

        # Hour 0 purchases block sells in normal mode (unless endgame, emergency relief, or midnight guard)
        if hour == 0 and not endgame and not pressure and not (hour >= 22 and shed_total > 88):
            diag = self._build_melon_diagnostics(ctx, melon_market_inv_init, shed, season_melons_sold, 0,
                                                 is_floor_exception, melon_turn_drip_budget,
                                                 melon_hold_reason_override="hour0_purchases",
                                                 delay_set=delay_set)
            return [], {
                "reason": "hour0_purchases",
                "pressure": pressure,
                "pending_occupancy": pending_occupancy,
                "scheduled_product_deposits": dict(scheduled_deposits),
                "melon_diagnostics": diag,
                **diag,
            }

        if urgency < 0:
            diag = self._build_melon_diagnostics(ctx, melon_market_inv_init, shed, season_melons_sold, 0,
                                                 is_floor_exception, melon_turn_drip_budget,
                                                 melon_hold_reason_override="waiting_for_sell_window",
                                                 delay_set=delay_set)
            return [], {
                "reason": "waiting_for_sell_window",
                "pressure": pressure,
                "pending_occupancy": pending_occupancy,
                "scheduled_product_deposits": dict(scheduled_deposits),
                "melon_diagnostics": diag,
                **diag,
            }

        # Spec batch sizes per phase
        if day <= 5:
            batch_target = 15  # sell 10-20 units
        elif day <= 8:
            batch_target = 7   # sell 5-10 units
        else:
            batch_target = 4   # sell 3-5 units

        try:
            from execution.same_turn_deposit_controller import (
                get_same_turn_deposit_sell_mode,
                record_same_turn_sale,
                record_shadow_event,
            )
        except Exception:
            try:
                from agent.execution.same_turn_deposit_controller import (
                    get_same_turn_deposit_sell_mode,
                    record_same_turn_sale,
                    record_shadow_event,
                )
            except Exception:
                get_same_turn_deposit_sell_mode = lambda: "OFF"
                record_same_turn_sale = None
                record_shadow_event = None

        m0e_mode = get_same_turn_deposit_sell_mode()

        # Available stock per product respecting reserves, caps, and floor-hold rules
        available_stock = {}
        deposit_stock = {}
        for prod in SELLABLE:
            if prod in delay_set and not endgame and urgency < 2:
                continue
            shed_pre_prod = int(shed.get(prod, 0))
            pred_dep_prod = int(scheduled_deposits.get(prod, 0))

            if m0e_mode == "LIVE":
                stock = shed_pre_prod + pred_dep_prod
            else:
                stock = shed_pre_prod

            # Shadow mode telemetry check
            if m0e_mode == "SHADOW" and pred_dep_prod > 0 and record_shadow_event is not None:
                shadow_stock = shed_pre_prod + pred_dep_prod
                res_w = (max(reserved_wheat, max(15, int(math.ceil(animals * 2.0)))) if p61_hygiene_active else reserved_wheat) if prod == "WHEAT" else 0
                shadow_net = max(0, shadow_stock - res_w)
                baseline_net = max(0, shed_pre_prod - res_w)
                spot_p = spot_init_map.get(prod, market_price(prod, inv.get(prod, 10000.0)))
                would_ex = (urgency >= 0) and (not (prod in HOLD_AT_FLOOR_PRODUCTS and not is_floor_exception and spot_p <= 1))
                reason = "eligible_in_sell_window" if would_ex else ("off_window" if urgency < 0 else "floor_hold")
                record_shadow_event(
                    step=ctx.get("step", day * 24 + hour),
                    day=day,
                    hour=hour,
                    product=prod,
                    shed_pre=shed_pre_prod,
                    predicted_deposit=pred_dep_prod,
                    incremental_sellable=max(0, shadow_net - baseline_net),
                    spot_price=float(spot_p),
                    market_inv=float(inv.get(prod, 10000.0)),
                    urgency=urgency,
                    would_execute=would_ex,
                    reason=reason,
                )

            if stock <= 0:
                continue
            if prod == "WHEAT":
                if p61_hygiene_active:
                    safe_wheat_floor = max(15, int(math.ceil(animals * 2.0)))
                    wheat_reserve = max(reserved_wheat, safe_wheat_floor)
                    stock = max(0, stock - wheat_reserve)
                else:
                    stock = max(0, stock - reserved_wheat)
            elif prod == "FERTILIZER" and not endgame and urgency < 2:
                if p61_hygiene_active:
                    fert_needed = sum(1 for t in ctx["farm"].iter_tiles()
                                      if getattr(t, "is_plant", False) and getattr(t, "crop", None) in ("STRAWBERRY", "TOMATO", "MELON")
                                      and getattr(t, "fertilized_until_day", -1) <= day)
                    fert_reserve = min(2, fert_needed)
                elif hour <= 18:
                    fert_needed = sum(1 for t in ctx["farm"].iter_tiles()
                                      if t.is_plant and t.crop in ("STRAWBERRY", "TOMATO", "MELON")
                                      and t.fertilized_until_day < day)
                    fert_reserve = min(2, fert_needed)
                else:
                    fert_reserve = 0
                stock = max(0, stock - fert_reserve)
            elif prod in HOLD_AT_FLOOR_PRODUCTS and not is_floor_exception and spot_init_map.get(prod, 10) <= 1:
                stock = 0  # Hold $1 fragile products at price floor in normal and shed relief modes
            elif prod == "MELON" and urgency < 2 and not endgame:
                stock = min(stock, melon_cap_remaining)

            if stock > 0:
                available_stock[prod] = stock
                if m0e_mode == "LIVE":
                    deposit_stock[prod] = pred_dep_prod

        if not available_stock:
            diag = self._build_melon_diagnostics(ctx, melon_market_inv_init, shed, season_melons_sold, 0,
                                                 is_floor_exception, melon_turn_drip_budget,
                                                 delay_set=delay_set)
            return [], {"reason": "no_available_stock", "pressure": pressure,
                        "is_p61_hygiene": p61_hygiene_active,
                        "p61_needed_relief": p61_needed_relief,
                        "melon_diagnostics": diag, **diag}

        # Order budget in order slots (engine cap is 10 orders per turn; None = unlimited)
        if order_budget is not None and (urgency >= 1 or endgame):
            order_budget = max(order_budget, MAX_MARKET_ORDERS)

        # Slicing target for emergency relief
        if urgency == 1:
            if shed_pressure:
                to_shed = max(0, shed_total - SHED_RESUME_CAP)
            else:
                # Only free the space required to make the EOD worker rollover fit.
                to_shed = max(0, pending_occupancy - SHED_CAPACITY)
            if p61_hygiene_active:
                to_shed = max(to_shed, min(shed_total, p61_needed_relief))
        else:
            to_shed = shed_total

        # Candidate product ordering
        # In emergency mode (when not endgame), follow liquidation priority: WHEAT -> CARROT -> TOMATO -> EGG -> MILK -> WOOL -> STRAWBERRY -> MELON -> FERTILIZER
        LIQUIDATION_PRIORITY = ("WHEAT", "CARROT", "TOMATO", "EGG", "MILK", "WOOL", "STRAWBERRY", "MELON", "FERTILIZER")
        P61_LIQUIDATION_PRIORITY = (
            "FERTILIZER",
            "STRAWBERRY",
            "WOOL",
            "MILK",
            "MELON",
            "CARROT",
            "TOMATO",
            "EGG",
            "WHEAT",
        )

        candidates = []
        for prod in SELLABLE:
            if prod not in available_stock:
                continue
            st = available_stock[prod]
            spot = spot_init_map.get(prod, market_price(prod, inv.get(prod, 10000)))
            urgency_score = st / (shed_total or 1)
            if spot <= 1:
                if prod in HOLD_AT_FLOOR_PRODUCTS and not is_floor_exception:
                    urgency_score = 0.0  # Do not elevate urgency for fragile goods at floor
                else:
                    urgency_score = 0.95
            if prod in preempt_set:
                urgency_score = 0.99
            candidates.append({"product": prod, "spot": spot, "urgency": urgency_score, "stock": st})

        if p61_hygiene_active:
            prio_map = {p: i for i, p in enumerate(P61_LIQUIDATION_PRIORITY)}
            candidates.sort(key=lambda c: (0 if c["product"] in preempt_set else 1, prio_map.get(c["product"], 99)))
        elif urgency >= 1 and not endgame:
            prio_map = {p: i for i, p in enumerate(LIQUIDATION_PRIORITY)}
            candidates.sort(key=lambda c: (0 if c["product"] in preempt_set else 1, prio_map.get(c["product"], 99)))
        else:
            candidates.sort(key=lambda c: -c["urgency"])

        orders = []
        melon_sold_this_turn = 0
        truncated_by_slots = False
        omitted_by_slots = []

        for c in candidates:
            if order_budget is not None and order_budget <= 0:
                truncated_by_slots = True
                if available_stock.get(c["product"], 0) > 0:
                    omitted_by_slots.append({
                        "product": c["product"],
                        "urgency": c["urgency"],
                        "available_stock": available_stock.get(c["product"], 0),
                    })
                continue
            if not endgame and urgency == 1 and to_shed <= 0:
                break
            prod = c["product"]
            st = available_stock[prod]
            if st <= 0:
                continue

            bt = batch_target

            if prod in DRIP_PROTECTED_PRODUCTS and not is_floor_exception:
                keep_f = DRIP_PRICE_KEEP_FRAC.get(prod, 0.90)
                spot_i = spot_init_map.get(prod, market_price(prod, inv.get(prod, 10000.0)))
                thresh = max(2, int(spot_i * keep_f))
                safe_qty = self._safe_drip_qty(prod, inv.get(prod, 10000.0), thresh)
                if prod == "MELON":
                    safe_qty = min(safe_qty, max(0, melon_cap_remaining - melon_sold_this_turn))
                if safe_qty <= 0:
                    continue
                if urgency == 1:
                    slice_qty = min(st, bt if bt > 10 else 10, to_shed, safe_qty)
                else:
                    slice_qty = min(st, bt, safe_qty)
            else:
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
            inv[prod] = inv.get(prod, 10000.0) + slice_qty
            if prod == "MELON":
                melon_sold_this_turn += slice_qty
            if urgency == 1:
                to_shed -= slice_qty
            if order_budget is not None:
                order_budget -= 1

            # In emergency mode, allow multiple slices of the overflowing product if to_shed remains
            if not endgame and urgency == 1 and to_shed > 0 and (order_budget is None or order_budget > 0) and available_stock[prod] > 0:
                while (order_budget is None or order_budget > 0) and to_shed > 0 and available_stock[prod] > 0:
                    if prod in DRIP_PROTECTED_PRODUCTS and not is_floor_exception:
                        keep_f = DRIP_PRICE_KEEP_FRAC.get(prod, 0.90)
                        spot_i = spot_init_map.get(prod, market_price(prod, inv.get(prod, 10000.0)))
                        thresh = max(2, int(spot_i * keep_f))
                        safe_qty = self._safe_drip_qty(prod, inv.get(prod, 10000.0), thresh)
                        if prod == "MELON":
                            safe_qty = min(safe_qty, max(0, melon_cap_remaining - melon_sold_this_turn))
                        if safe_qty <= 0:
                            break
                        extra_qty = min(available_stock[prod], bt if bt > 10 else 10, to_shed, safe_qty)
                    else:
                        extra_qty = min(available_stock[prod], bt if bt > 10 else 10, to_shed)
                    if extra_qty <= 0:
                        break
                    orders.append(["SELL", prod, int(extra_qty)])
                    available_stock[prod] -= extra_qty
                    inv[prod] = inv.get(prod, 10000.0) + extra_qty
                    if prod == "MELON":
                        melon_sold_this_turn += extra_qty
                    to_shed -= extra_qty
                    if order_budget is not None:
                        order_budget -= 1

        diag = self._build_melon_diagnostics(ctx, melon_market_inv_init, shed, season_melons_sold, melon_sold_this_turn,
                                             is_floor_exception, melon_turn_drip_budget,
                                             delay_set=delay_set)

        # Telemetry tracking for LIVE mode same-turn sales
        if m0e_mode == "LIVE" and record_same_turn_sale is not None:
            sold_by_prod = {}
            for o in orders:
                if len(o) >= 3 and o[0] == "SELL":
                    sold_by_prod[o[1]] = sold_by_prod.get(o[1], 0) + int(o[2])
            for prod, total_sold in sold_by_prod.items():
                dep_qty = deposit_stock.get(prod, 0)
                if dep_qty > 0:
                    shed_pre_q = int(shed.get(prod, 0))
                    res_w = (max(reserved_wheat, max(15, int(math.ceil(animals * 2.0)))) if p61_hygiene_active else reserved_wheat) if prod == "WHEAT" else 0
                    net_pre = max(0, shed_pre_q - res_w)
                    from_deposit = min(max(0, total_sold - net_pre), dep_qty)
                    if from_deposit > 0:
                        px = spot_init_map.get(prod, market_price(prod, inv.get(prod, 10000.0)))
                        record_same_turn_sale(
                            prod=prod,
                            units=from_deposit,
                            price=float(px),
                            step=ctx.get("step", day * 24 + hour),
                            day=day,
                            hour=hour,
                        )

        return orders, {"candidates": candidates, "days_left": days_left,
                        "endgame": endgame, "pressure": pressure, "urgency": urgency,
                        "shed_occupancy": shed_occupancy,
                        "carried_worker_inventory": carried_worker_inventory,
                        "pending_occupancy": pending_occupancy,
                        "scheduled_product_deposits": dict(scheduled_deposits),
                        "upstream_truncation": truncated_by_slots,
                        "omitted_by_slots": omitted_by_slots,
                        "max_slots": max_slots,
                        "is_p61_hygiene": p61_hygiene_active,
                        "p61_needed_relief": p61_needed_relief,
                        "melon_diagnostics": diag, **diag}

    # ------------------------------------------------------------------
    def _safe_drip_qty(self, prod, current_inv, threshold):
        """Calculate max units Q that can be added to current_inv such that
        market_price(prod, current_inv + Q) >= threshold.
        """
        if threshold <= 1:
            return 999999
        limit = inventory_at_price(prod, threshold)
        budget = max(0, int(limit - float(current_inv)))
        while budget > 0 and market_price(prod, current_inv + budget) < threshold:
            budget -= 1
        while market_price(prod, current_inv + budget + 1) >= threshold:
            budget += 1
        return max(0, budget)

    def _drip_budget(self, prod, current_inv, keep_frac, spot):
        threshold = max(2, int(spot * keep_frac))
        return self._safe_drip_qty(prod, current_inv, threshold)

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
