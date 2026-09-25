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
        "events": [],
    }


def get_midnight_storage_telemetry() -> Dict[str, Any]:
    """Return immutable snapshot of all recorded midnight storage telemetry."""
    return copy.deepcopy(_TELEMETRY)


def is_midnight_storage_dump_enabled() -> bool:
    try:
        from config import get_midnight_storage_dump_mode
        return get_midnight_storage_dump_mode() == "ON"
    except Exception:
        try:
            from agent.config import get_midnight_storage_dump_mode
            return get_midnight_storage_dump_mode() == "ON"
        except Exception:
            return False


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
    1. Feature flag ON.
    2. Late-day timing: hour >= 18 and day < 29.
    3. Product safety: only standard crops, no animal products, no animals, no fertilizer,
       and no wheat if feeding is due today.
    4. Headroom guarantee: shed_load + carried_total <= MAX_SAFE_SHED_HEADROOM (95).
    5. Congestion benefit: shed_load >= 70 OR worker distance to nearest shed access >= 2.
    """
    if not is_midnight_storage_dump_enabled():
        return False

    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)

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
