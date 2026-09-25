"""Phase M0-E: Same-Turn Deposit-to-Market Exploit Controller.

Provides authoritative accounting and control for predicting deterministic same-turn shed
deposits and enabling immediate same-turn market sales.

Supported modes:
- OFF: Production baseline. Pre-turn shed inventory only.
- SHADOW: Runs deposit prediction and shadow market checks, logs telemetry, but executes baseline orders.
- LIVE: Adds deterministic same-turn deposited inventory to sell-eligible inventory while preserving all
  existing economic policies, priorities, and 10-order engine limits.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Set, Tuple

PRODUCTS = [
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
    "EGG", "MILK", "WOOL", "FERTILIZER"
]
ANIMALS = ["GOOSE", "COW", "SHEEP"]
SHED_ACCESS_TILES = {(4, 4), (5, 4), (4, 5), (5, 5)}
SHED_CAPACITY = 100

_TELEMETRY: Dict[str, Any] = {
    "opportunities_detected": 0,
    "predictions_made": 0,
    "predictions_accurate": 0,
    "predictions_mismatch": 0,
    "total_predicted_units": 0,
    "total_actual_units": 0,
    "false_positives": 0,
    "false_negatives": 0,
    "same_turn_sales_enabled": 0,
    "same_turn_units_sold": 0,
    "same_turn_revenue": 0.0,
    "products_sold": {p: 0 for p in PRODUCTS},
    "products_revenue": {p: 0.0 for p in PRODUCTS},
    "actual_products_deposited": {p: 0 for p in PRODUCTS},
    "latency_avoided_turns": [],
    "cash_accelerated_events": [],
    "shadow_events": [],
    "events": [],
}


def reset_same_turn_deposit_telemetry() -> None:
    """Clear all recorded telemetry and shadow events."""
    global _TELEMETRY
    _TELEMETRY = {
        "opportunities_detected": 0,
        "predictions_made": 0,
        "predictions_accurate": 0,
        "predictions_mismatch": 0,
        "total_predicted_units": 0,
        "total_actual_units": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "same_turn_sales_enabled": 0,
        "same_turn_units_sold": 0,
        "same_turn_revenue": 0.0,
        "products_sold": {p: 0 for p in PRODUCTS},
        "products_revenue": {p: 0.0 for p in PRODUCTS},
        "actual_products_deposited": {p: 0 for p in PRODUCTS},
        "latency_avoided_turns": [],
        "cash_accelerated_events": [],
        "shadow_events": [],
        "events": [],
    }


def get_same_turn_deposit_telemetry() -> Dict[str, Any]:
    """Return immutable snapshot of all recorded telemetry."""
    res = copy.deepcopy(_TELEMETRY)
    # Expose standard aliases for experiment and reporting scripts
    res["deposit_units_predicted"] = res.get("total_predicted_units", 0)
    res["same_turn_deposit_opportunities"] = res.get("opportunities_detected", 0)
    res["deposit_units_actual"] = res.get("total_actual_units", 0)
    res["deposit_products_actual"] = dict(res.get("actual_products_deposited", {}))
    res["same_turn_products_sold"] = dict(res.get("products_sold", {}))
    res["same_turn_revenue_by_product"] = dict(res.get("products_revenue", {}))
    res["cash_acceleration_est"] = float(res.get("same_turn_revenue", 0.0))
    res["same_turn_sales_events"] = res.get("same_turn_sales_enabled", 0)
    return res


def get_same_turn_deposit_sell_mode() -> str:
    try:
        from config import get_same_turn_deposit_sell_mode as _cfg_mode
        return _cfg_mode()
    except Exception:
        try:
            from agent.config import get_same_turn_deposit_sell_mode as _cfg_mode
            return _cfg_mode()
        except Exception:
            return "BASELINE"


def is_same_turn_deposit_sell_enabled() -> bool:
    return get_same_turn_deposit_sell_mode() in ("BASELINE", "LIVE", "SHADOW")


def is_shadow_mode() -> bool:
    return get_same_turn_deposit_sell_mode() == "SHADOW"


def is_shed_adjacent(pos: Any) -> bool:
    """True iff coordinates are adjacent to the central 2x2 shed."""
    if not pos:
        return False
    try:
        return (int(pos[0]), int(pos[1])) in SHED_ACCESS_TILES
    except (TypeError, ValueError, IndexError):
        return False


def predict_same_turn_deposits(
    ctx: Dict[str, Any],
    asg: Dict[str, Any],
    shed_capacity: int = SHED_CAPACITY,
) -> Dict[str, int]:
    """Deterministically predict shed inflow before market order execution.

    The engine applies farmer/hand actions first in sequential unit order:
      1. Farmer (idx 0)
      2. Hands (idx 1..n)
    and then executes market orders.

    Only an emitted DROP or PLACE-to-shed action while physically standing on
    a shed-access tile deposits goods. Overflow is bounded by remaining shed capacity
    and DROP overflow is permanently deleted by the engine.

    Returns:
        Dict mapping product names to predicted integer quantities entering the shed.
    """
    if not isinstance(asg, dict):
        return {}

    actions = asg.get("actions", {}) or {}
    private = ctx.get("private") if isinstance(ctx, dict) else None
    farm = ctx.get("farm") if isinstance(ctx, dict) else None
    if private is None or farm is None:
        return {}

    inventories = list(getattr(private, "inventories", []) or [])
    shed = getattr(private, "shed", {}) or {}
    current_shed_load = sum(max(0, int(v)) for v in shed.values())
    room = max(0, shed_capacity - current_shed_load)
    deposits: Dict[str, int] = {}

    hands_list = list(getattr(farm, "hands", []) or [])
    n_workers = 1 + len(hands_list)

    for u_idx in range(n_workers):
        if room <= 0:
            break

        # Check action
        act = actions.get(u_idx, actions.get(str(u_idx)))
        if not act or not isinstance(act, (list, tuple)) or not act:
            continue

        op = act[0]
        if op not in ("DROP", "PLACE"):
            continue

        # Check worker position
        if u_idx == 0:
            pos = getattr(farm, "farmer", None)
        else:
            h_idx = u_idx - 1
            pos = hands_list[h_idx] if h_idx < len(hands_list) else None

        if not is_shed_adjacent(pos):
            continue

        if u_idx >= len(inventories):
            continue
        inv = inventories[u_idx] or {}

        if op == "DROP":
            for item, raw_qty in list(inv.items()):
                if room <= 0:
                    break
                if item not in PRODUCTS:
                    continue
                qty = max(0, int(raw_qty or 0))
                if qty <= 0:
                    continue
                take = min(qty, room)
                if take > 0:
                    deposits[item] = deposits.get(item, 0) + take
                    room -= take

        elif op == "PLACE":
            if len(act) < 2:
                continue
            item = act[1]
            if item in ANIMALS:
                # Animal placement onto structures does not deposit into shed
                continue
            if item not in PRODUCTS:
                continue
            try:
                requested = int(act[2]) if len(act) >= 3 else 1
            except (TypeError, ValueError):
                requested = 0
            if requested <= 0:
                continue
            available_qty = max(0, int(inv.get(item, 0)))
            take = min(requested, available_qty, room)
            if take > 0:
                deposits[item] = deposits.get(item, 0) + take
                room -= take

    if deposits:
        _TELEMETRY["opportunities_detected"] += 1
        _TELEMETRY["predictions_made"] += 1
        _TELEMETRY["total_predicted_units"] += sum(deposits.values())

    return deposits


def record_post_step_reconciliation(
    predicted: Dict[str, int],
    actual_shed_pre: Dict[str, int],
    actual_shed_post: Dict[str, int],
    sold_units: Dict[str, int],
    step: int,
    day: int,
    hour: int,
) -> None:
    """Compare predicted deposit against actual net physical inflow.

    actual_deposit = shed_post - shed_pre + sold_from_shed
    """
    global _TELEMETRY
    all_prods = set(predicted.keys()) | set(actual_shed_pre.keys()) | set(actual_shed_post.keys())

    is_exact = True
    for p in all_prods:
        pred_p = predicted.get(p, 0)
        # Net inflow into shed this step
        inflow = max(0, actual_shed_post.get(p, 0) - actual_shed_pre.get(p, 0) + sold_units.get(p, 0))
        if inflow > 0:
            _TELEMETRY["total_actual_units"] += inflow
            if "actual_products_deposited" not in _TELEMETRY:
                _TELEMETRY["actual_products_deposited"] = {pr: 0 for pr in PRODUCTS}
            _TELEMETRY["actual_products_deposited"][p] = _TELEMETRY["actual_products_deposited"].get(p, 0) + inflow
        if pred_p != inflow:
            is_exact = False
            if pred_p > inflow:
                _TELEMETRY["false_positives"] += (pred_p - inflow)
            else:
                _TELEMETRY["false_negatives"] += (inflow - pred_p)

    if is_exact:
        _TELEMETRY["predictions_accurate"] += 1
    else:
        _TELEMETRY["predictions_mismatch"] += 1


def record_same_turn_sale(
    prod: str,
    units: int,
    price: float,
    step: int,
    day: int,
    hour: int,
    latency_avoided: int = 4,
) -> None:
    """Record an executed same-turn deposit sell event."""
    global _TELEMETRY
    revenue = units * price
    _TELEMETRY["same_turn_sales_enabled"] += 1
    _TELEMETRY["same_turn_units_sold"] += units
    _TELEMETRY["same_turn_revenue"] += revenue
    _TELEMETRY["products_sold"][prod] = _TELEMETRY["products_sold"].get(prod, 0) + units
    _TELEMETRY["products_revenue"][prod] = _TELEMETRY["products_revenue"].get(prod, 0.0) + revenue
    _TELEMETRY["latency_avoided_turns"].append(latency_avoided)
    _TELEMETRY["cash_accelerated_events"].append({
        "step": step,
        "day": day,
        "hour": hour,
        "product": prod,
        "units": units,
        "price": price,
        "revenue": revenue,
        "latency_avoided": latency_avoided,
    })


def record_shadow_event(
    step: int,
    day: int,
    hour: int,
    product: str,
    shed_pre: int,
    predicted_deposit: int,
    incremental_sellable: int,
    spot_price: float,
    market_inv: float,
    urgency: int,
    would_execute: bool,
    reason: str,
) -> None:
    """Record a shadow evaluation event when running in SHADOW mode."""
    global _TELEMETRY
    _TELEMETRY["shadow_events"].append({
        "step": step,
        "day": day,
        "hour": hour,
        "product": product,
        "shed_pre": shed_pre,
        "predicted_deposit": predicted_deposit,
        "incremental_sellable": incremental_sellable,
        "spot_price": spot_price,
        "market_inv": market_inv,
        "urgency": urgency,
        "would_execute": would_execute,
        "reason": reason,
    })
