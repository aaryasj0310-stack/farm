"""Phase 4: Descriptive Shadow Opponent Forecasting & Calibration System.

PURELY SHADOW-ONLY: Does NOT alter MacroPlanner, MarketBrain, CentralPlanner,
or any strategic execution.

Exposes descriptive forecasts for:
1. Opponent production volume & timing (by product & day, low/base/high)
2. Collection timing (field harvest window)
3. Delivery timing (worker carry -> shed deposit window)
4. Shed inventory bounds [min, max]
5. Sale timing (next sell window hour % 4 == 1) and sale volume
6. Explicit calibrated sale probability: P(visible sale >= 1 unit in next 4 turns)
"""

from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional
from config import PRODUCTS, CROPS, ANIMALS
from state.repaired_opponent_model import (
    snapshot_farm,
    detect_tile_deltas_repaired,
    forecast_opponent_production_repaired,
    RepairedOpponentInventoryTracker,
)
from strategy.repaired_opponent_advisor import (
    build_repaired_opponent_advice,
    compute_sell_probabilities_repaired,
)


import os
import json
from state.state_tracker import _expected_town_consumption
from strategy.repaired_opponent_advisor import (
    _get_empirical_behavior_tables,
    _get_phase,
    _get_ripe_bin,
    _get_shed_bin,
    _get_price_bin,
)


class ShadowOpponentForecaster:
    """Manages shadow predictions and emits telemetry for calibration."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.inventory_tracker = RepairedOpponentInventoryTracker()
        self.prev_snapshot = None
        self.prev_market_inv = None
        self.prev_opp_money = None
        self.last_step = -1
        self.last_forecast = {}
        self.last_inventory = {}
        self.last_telemetry = {}
        self.ripe_since = {}  # (x, y) -> step

    def update(
        self,
        opp_farm,
        ctx: Dict[str, Any],
        mem: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update shadow model and produce descriptive forward forecasts."""
        if opp_farm is None:
            return {}

        step = ctx.get("step", 0)
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)
        phase = _get_phase(day)

        # 1. Snapshot and delta detection
        new_snap = snapshot_farm(opp_farm)
        deltas = detect_tile_deltas_repaired(opp_farm, self.prev_snapshot)
        self.prev_snapshot = new_snap

        # 2. Confirmed sales from state_tracker market ledger
        confirmed_sells = mem.get("opp_sales_step", {})

        # 3. Market Purchase & Drain Inference (WHEAT / FERTILIZER)
        market_now = ctx.get("market", {})
        inv_now = market_now.get("inventory", {}) if isinstance(market_now, dict) else getattr(market_now, "inventory", {})
        prices_now = market_now.get("prices", {}) if isinstance(market_now, dict) else getattr(market_now, "prices", {})
        opp_money_now = float(getattr(opp_farm, "money", 0.0))

        inferred_buys = {}
        if self.prev_market_inv is not None and self.prev_opp_money is not None:
            delta_money = opp_money_now - self.prev_opp_money
            town_obj = ctx.get("town", {})
            unlocked_shops = town_obj.get("unlocked_shops", []) if isinstance(town_obj, dict) else getattr(town_obj, "unlocked_shops", [])

            for p in ("WHEAT", "FERTILIZER"):
                prev_i = self.prev_market_inv.get(p, 10000.0)
                curr_i = inv_now.get(p, 10000.0)
                delta_inv = curr_i - prev_i
                town_drain = _expected_town_consumption(p, unlocked_shops, step)
                our_net = float(mem.get("our_units_sold_last_step", {}).get(p, 0.0)) - float(mem.get("our_units_bought_last_step", {}).get(p, 0.0))

                residual = delta_inv - our_net + town_drain
                if residual < -0.5:
                    u_bought = max(1.0, float(int(-residual)))
                    unit_price = prices_now.get(p, 25.0)
                    exp_cost = u_bought * unit_price

                    # Corroborate with opponent cash expenditure
                    if delta_money <= -0.7 * exp_cost:
                        conf = "high"
                    elif delta_money < 0:
                        conf = "medium"
                    else:
                        conf = "low"  # could be offset by contemporaneous sales

                    inferred_buys[p] = {
                        "lower": u_bought,
                        "upper": u_bought + 1.0,
                        "confidence": conf,
                    }

        self.prev_market_inv = dict(inv_now) if inv_now else None
        self.prev_opp_money = opp_money_now

        opp_animals = sum(1 for t in opp_farm.iter_tiles() if t.is_animal)

        # 4. Principled inventory bounds tracking
        inv_tracking = self.inventory_tracker.update(
            deltas=deltas,
            confirmed_sells=confirmed_sells,
            confirmed_buys=None,
            n_animals=opp_animals,
            day=day,
            hour=hour,
            inferred_buys=inferred_buys,
        )

        # 5. Repaired forward production forecast
        prod_forecast = forecast_opponent_production_repaired(
            opp_farm=opp_farm,
            current_day=day,
            current_hour=hour,
        )

        # 6. Empirical Collection & Delivery Timing Forecasts
        tables = _get_empirical_behavior_tables()
        coll_hazard_table = tables.get("collection_hazard_table", {})
        manual_deposit_prob = tables.get("behavioral_manual_deposit_rate", 0.3137)

        # Update ripe tracking for active tiles
        for t in opp_farm.iter_tiles():
            pos = (t.x, t.y)
            y_u = getattr(t, "yield_units", 0)
            if y_u > 0 and pos not in self.ripe_since:
                self.ripe_since[pos] = step
            elif y_u == 0 and pos in self.ripe_since:
                del self.ripe_since[pos]

        collection_forecast = {}
        delivery_forecast = {}
        hours_to_eod = 24 - hour
        guaranteed_eod_step = step + hours_to_eod

        # Check worker proximity to shed
        farmer_pos = getattr(opp_farm, "farmer", (4, 4))
        hands_pos = getattr(opp_farm, "hands", [])
        worker_on_shed = any(tuple(pos) in [(4, 4), (4, 5), (5, 4), (5, 5)] for pos in [farmer_pos] + list(hands_pos))

        for prod in PRODUCTS:
            field_units = prod_forecast["imminent_field_stock"].get(prod, 0)
            carried_bounds = inv_tracking["carried_bounds"].get(prod, [0.0, 0.0])

            if field_units > 0:
                # Find maximum elapsed ripe turns for tiles of this product
                max_turns_ripe = 0
                for t in opp_farm.iter_tiles():
                    pos = (t.x, t.y)
                    t_prod = getattr(t, "crop", None) or (ANIMALS.get(getattr(t, "animal", ""), {}).get("product"))
                    if t_prod == prod and pos in self.ripe_since:
                        max_turns_ripe = max(max_turns_ripe, step - self.ripe_since[pos])

                r_bin = _get_ripe_bin(max_turns_ripe)
                hazard = coll_hazard_table.get(prod, {}).get(phase, {}).get(r_bin, 0.02)
                p_coll_4 = min(0.95, 1.0 - (1.0 - hazard) ** 4)
                expected_delay = min(48, int(round(1.0 / max(0.01, hazard))))

                collection_forecast[prod] = {
                    "ripe_units": field_units,
                    "turns_since_ripe": max_turns_ripe,
                    "hazard_next_turn": round(hazard, 4),
                    "p_collection_next_4_turns": round(p_coll_4, 4),
                    "expected_collection_step": step + expected_delay,
                }

            if carried_bounds[1] > 0:
                # Separate deterministic EOD drop from behavioral manual deposit
                delivery_forecast[prod] = {
                    "carried_bounds": carried_bounds,
                    "guaranteed_eod_delivery_step": guaranteed_eod_step,
                    "p_intraday_manual_deposit": round(manual_deposit_prob, 4) if worker_on_shed else 0.05,
                    "expected_delivery_step": (step + 2) if (worker_on_shed and manual_deposit_prob > 0.5) else guaranteed_eod_step,
                }

        # 7. Calibrated Sale Timing & Volume Forecasts
        p_sale_by_horizon = {}
        for h in (1, 4, 8, 24):
            _, p_h = compute_sell_probabilities_repaired(
                opp_farm=opp_farm,
                inventory_tracking=inv_tracking,
                ctx=ctx,
                horizon=h,
            )
            p_sale_by_horizon[h] = p_h

        sell_scores = {p: round(min(1.0, float(p_sale_by_horizon[4].get(p, 0.0)) * 1.25), 4) for p in PRODUCTS}
        p_sale_4_turns = p_sale_by_horizon[4]

        next_sell_hour = ((hour // 4) * 4 + 1)
        if next_sell_hour <= hour:
            next_sell_hour += 4
        next_sell_step = step + (next_sell_hour - hour)

        sale_volume_forecast = {}
        for prod in PRODUCTS:
            hi_shed = inv_tracking["shed_bounds"].get(prod, [0.0, 0.0])[1]
            if hi_shed > 0:
                sale_volume_forecast[prod] = {
                    "min_sale_units": 1 if hi_shed >= 1 else 0,
                    "expected_sale_units": min(float(hi_shed), 4.0),
                    "max_sale_units": min(float(hi_shed), 10.0),
                }

        # 8. Product-Specific Quality & Confidence Metadata
        # Evaluated against rigorous promotion criteria
        confidence_metadata = {}
        for p in PRODUCTS:
            shed_b = inv_tracking["shed_bounds"].get(p, [0.0, 0.0])
            s_width = shed_b[1] - shed_b[0]

            # Assess production signal
            prod_tier = "high" if p in CROPS or p in ("MILK", "WOOL", "EGG") else "low"

            # Assess inventory bounds signal
            if p in ("MILK", "WOOL", "EGG", "MELON"):
                inv_tier = "high"
                gate = "ready_for_experiments"
            elif p in ("STRAWBERRY", "CARROT", "TOMATO"):
                inv_tier = "medium"
                gate = "shadow_only"
            else:  # WHEAT, FERTILIZER
                inv_tier = "low" if p in inferred_buys else "unreliable"
                gate = "shadow_only" if p in inferred_buys else "rejected"

            confidence_metadata[p] = {
                "production": {"tier": prod_tier, "basis": "engine_lifecycle_schedule"},
                "field_inventory": {"tier": "high", "basis": "observable_yield_tiles"},
                "carried_inventory": {"tier": "medium", "basis": "harvest_delta_accumulation"},
                "shed_inventory": {
                    "tier": inv_tier,
                    "interval_width": round(s_width, 1),
                    "basis": "bounds_tracking" + ("_with_purchase_inference" if p in inferred_buys else ""),
                },
                "collection_timing": {"tier": "medium", "basis": "empirical_survival_hazard"},
                "delivery_timing": {"tier": "high", "basis": "deterministic_eod_auto_deposit"},
                "sale_timing": {"tier": "medium", "basis": "empirical_conditional_hazard"},
                "sale_volume": {"tier": "medium", "basis": "shed_bounds_proportional"},
                "market_purchase_inference": {
                    "tier": inferred_buys.get(p, {}).get("confidence", "none"),
                    "basis": "market_residual_and_cash_delta",
                },
                "promotion_gate_status": gate,
            }

        telemetry = {
            "step": step,
            "day": day,
            "hour": hour,
            "phase": phase,
            "production_forecast": prod_forecast["base_schedule"],
            "production_scenarios": prod_forecast["schedules"],
            "imminent_field_stock": prod_forecast["imminent_field_stock"],
            "collection_forecast": collection_forecast,
            "delivery_forecast": delivery_forecast,
            "shed_bounds": inv_tracking["shed_bounds"],
            "carried_bounds": inv_tracking["carried_bounds"],
            "shed_point_estimate": inv_tracking["shed_point_estimate"],
            "inferred_buys": inv_tracking.get("inferred_buys", {}),
            "next_sell_step": next_sell_step,
            "sale_volume_forecast": sale_volume_forecast,
            "sell_intent_scores": sell_scores,
            "p_sale_next_4_turns": p_sale_4_turns,
            "p_sale_by_horizon": p_sale_by_horizon,
            "confidence_metadata": confidence_metadata,
        }

        self.last_step = step
        self.last_telemetry = telemetry
        return telemetry


# Singleton shadow forecaster instance
_SHADOW_FORECASTER = ShadowOpponentForecaster()


def get_shadow_forecaster() -> ShadowOpponentForecaster:
    return _SHADOW_FORECASTER


def reset_shadow_forecaster():
    global _SHADOW_FORECASTER
    _SHADOW_FORECASTER.reset()
