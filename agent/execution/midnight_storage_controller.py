"""Phase M0-B: Midnight Storage Dump Logistics Controller.

Manages safe, controlled temporary worker inventory buffering during late-day hours
(hours 18–23) to relieve shed congestion, eliminate unproductive travel turns to the shed,
and guarantee safe midnight rollover into shed storage without silent overflow discard.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set, Tuple

CROPS_BUFFERABLE = {"WHEAT", "CARROT", "MELON", "TOMATO", "STRAWBERRY"}
MAX_SAFE_SHED_HEADROOM = 95  # 5 slot safety buffer below engine's 100 cap

_TELEMETRY: Dict[str, Any] = {
    "opportunities_detected": 0,
    "holds_attempted": 0,
    "holds_successful": 0,
    "products_held": {c: 0 for c in CROPS_BUFFERABLE},
    "worker_turns_spent_holding": 0,
    "automatic_midnight_dumps": 0,
    "manual_early_releases": 0,
    "failed_dumps": 0,
    "capacity_blocked_dumps": 0,
    "products_lost": 0,
    "shed_turns_ge_90": 0,
    "shed_turns_ge_95": 0,
    "shed_turns_at_capacity": 0,
    "peak_shed_occupancy": 0,
    "rescue_events": 0,
    "rescue_units_sold": 0,
    "rescue_orders_emitted": 0,
    "rescue_products_sold": {},
    "events": [],
}


def reset_midnight_storage_telemetry() -> None:
    """Clear all recorded midnight storage telemetry."""
    global _TELEMETRY
    _TELEMETRY = {
        "opportunities_detected": 0,
        "holds_attempted": 0,
        "holds_successful": 0,
        "products_held": {c: 0 for c in CROPS_BUFFERABLE},
        "worker_turns_spent_holding": 0,
        "automatic_midnight_dumps": 0,
        "manual_early_releases": 0,
        "failed_dumps": 0,
        "capacity_blocked_dumps": 0,
        "products_lost": 0,
        "shed_turns_ge_90": 0,
        "shed_turns_ge_95": 0,
        "shed_turns_at_capacity": 0,
        "peak_shed_occupancy": 0,
        "rescue_events": 0,
        "rescue_units_sold": 0,
        "rescue_orders_emitted": 0,
        "rescue_products_sold": {},
        "events": [],
    }


def get_midnight_storage_telemetry() -> Dict[str, Any]:
    """Return immutable snapshot of all recorded midnight storage telemetry."""
    return copy.deepcopy(_TELEMETRY)


def get_midnight_mode() -> str:
    try:
        from config import get_midnight_storage_dump_mode
        return get_midnight_storage_dump_mode()
    except Exception:
        try:
            from agent.config import get_midnight_storage_dump_mode
            return get_midnight_storage_dump_mode()
        except Exception:
            return "OFF"


def is_midnight_storage_dump_enabled() -> bool:
    return get_midnight_mode() in ("ON", "BUFFER", "RESCUE")


def is_storage_rescue_enabled() -> bool:
    return get_midnight_mode() == "RESCUE"


def record_rescue_sale(prod: str, qty: int) -> None:
    """Record an emergency storage rescue sale order."""
    global _TELEMETRY
    _TELEMETRY["rescue_events"] += 1
    _TELEMETRY["rescue_units_sold"] += qty
    _TELEMETRY["rescue_orders_emitted"] += 1
    _TELEMETRY.setdefault("rescue_products_sold", {})[prod] = _TELEMETRY.setdefault("rescue_products_sold", {}).get(prod, 0) + qty


def should_buffer_worker_inventory(
    ctx: Dict[str, Any],
    u_idx: int,
    inv: Dict[str, int],
    deliverable: Dict[str, int],
    shed_load: int,
    carried_total: int,
    feeds_due: int = 0,
) -> bool:
    """Evaluate whether worker u_idx should defer product deposit and ride until midnight.

    Safety & Eligibility gates:
    1. Feature flag ON, BUFFER, or RESCUE.
    2. Late-day timing: hour >= 18 (or >= 20 for RESCUE) and day < 29.
    3. Product safety: only standard crops, no animal products, no animals, no fertilizer,
       and no wheat if feeding is due today.
    4. Headroom guarantee: shed_load + carried_total <= MAX_SAFE_SHED_HEADROOM (95).
    5. Congestion benefit: shed_load >= 70 OR worker distance to nearest shed access >= 2.
    """
    if not is_midnight_storage_dump_enabled():
        return False

    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)

    # In Phase M0-D RESCUE mode: worker delivery mechanics operate normally without artificial hold delays.
    # Midnight overflow rescue is executed via proactive Hour 23 shed relief in MarketBrain.
    if is_storage_rescue_enabled():
        return False

    # Gate 1: Non-endgame late-day only
    if day >= 29 or hour < 18:
        return False

    # Gate 2: Safe product selection
    for item, qty in deliverable.items():
        if qty <= 0:
            continue
        if item not in CROPS_BUFFERABLE:
            return False
        if item == "WHEAT" and feeds_due > 0:
            return False

    items_to_hold = sum(deliverable.values())
    if items_to_hold <= 0:
        return False

    _TELEMETRY["opportunities_detected"] += 1

    # Gate 3: Strict Headroom Guarantee (must not exceed 95 at midnight)
    total_projected_at_midnight = shed_load + carried_total
    if total_projected_at_midnight > MAX_SAFE_SHED_HEADROOM:
        _TELEMETRY["capacity_blocked_dumps"] += 1
        return False

    # Gate 4: Congestion or Travel Efficiency Benefit
    farm = ctx.get("farm")
    unit_positions = [tuple(farm.farmer)] + [tuple(h) for h in farm.hands] if farm else []
    worker_pos = unit_positions[u_idx] if u_idx < len(unit_positions) else None

    is_congested = (shed_load >= 70)
    travel_cost_high = False
    if worker_pos:
        shed_tiles = {(4, 4), (5, 4), (4, 5), (5, 5)}
        min_dist = min(abs(worker_pos[0] - sx) + abs(worker_pos[1] - sy) for sx, sy in shed_tiles)
        if min_dist >= 2:
            travel_cost_high = True

    if not (is_congested or travel_cost_high):
        return False

    # Eligible: Record hold telemetry
    _TELEMETRY["holds_attempted"] += 1
    _TELEMETRY["holds_successful"] += 1
    _TELEMETRY["worker_turns_spent_holding"] += 1
    for item, qty in deliverable.items():
        _TELEMETRY["products_held"][item] = _TELEMETRY["products_held"].get(item, 0) + qty

    event = {
        "step": ctx.get("step", day * 24 + hour),
        "day": day,
        "hour": hour,
        "worker_idx": u_idx,
        "worker_pos": list(worker_pos) if worker_pos else None,
        "deliverable": dict(deliverable),
        "shed_load": shed_load,
        "carried_total": carried_total,
        "projected_at_midnight": total_projected_at_midnight,
    }
    _TELEMETRY["events"].append(event)
    return True


def record_step_telemetry(shed_occupancy: int, is_midnight_step: bool = False, dumped_qty: int = 0) -> None:
    """Record turn-by-turn storage occupancy metrics."""
    global _TELEMETRY
    if shed_occupancy >= 90:
        _TELEMETRY["shed_turns_ge_90"] += 1
    if shed_occupancy >= 95:
        _TELEMETRY["shed_turns_ge_95"] += 1
    if shed_occupancy >= 100:
        _TELEMETRY["shed_turns_at_capacity"] += 1
    if shed_occupancy > _TELEMETRY["peak_shed_occupancy"]:
        _TELEMETRY["peak_shed_occupancy"] = shed_occupancy
    if is_midnight_step and dumped_qty > 0:
        _TELEMETRY["automatic_midnight_dumps"] += 1


def apply_midnight_storage_rescue(market: List[List[Any]], ctx: Dict[str, Any]) -> List[List[Any]]:
    """Phase M0-D: Proactive marginal Hour 23 shed relief to prevent midnight overflow discard.

    Only active when MIDNIGHT_STORAGE_DUMP_MODE == 'RESCUE', at Hour 23, Day < 29.
    Checks projected midnight load (shed + carried). If > 98:
      Sells only the marginal excess (projected - 98) from available shed wheat
      beyond the 2-day safe feed reserve (max(10, animals * 2)).
    Consumes at most 1 market order slot within the 10-order cap.
    """
    if not is_storage_rescue_enabled():
        return market

    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)
    if day >= 29 or hour != 23:
        return market

    # Shared maximum of 10 market commands per turn
    if len(market) >= 10:
        return market

    private = ctx.get("private")
    farm = ctx.get("farm")
    if not private or not farm or not hasattr(private, "shed") or not hasattr(private, "inventories"):
        return market

    shed = private.shed
    inventories = private.inventories
    shed_c = sum(shed.values())
    carried_c = sum(sum(i.values()) for i in inventories)
    projected = shed_c + carried_c

    if projected <= 98:
        return market

    needed = projected - 98
    w_stock = shed.get("WHEAT", 0)
    already_selling_w = sum(int(order[2]) for order in market if len(order) >= 3 and order[0] == "SELL" and order[1] == "WHEAT")
    available_w = max(0, w_stock - already_selling_w)

    anim_cnt = sum(1 for t in farm.iter_tiles() if getattr(t, "is_animal", False))
    safe_w = max(10, anim_cnt * 2)
    can_sell_w = max(0, available_w - safe_w)

    sell_qty = min(can_sell_w, needed)
    if sell_qty > 0 and len(market) < 10:
        market.append(["SELL", "WHEAT", int(sell_qty)])
        record_rescue_sale("WHEAT", int(sell_qty))

    return market

