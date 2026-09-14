"""SW Cell Allocator: Controlled Spatial Allocation for Mixed SW Production Cell.

Allocates LOCATION ONLY for already-justified large livestock housing:
  - Upstream authoritative flow: DynamicHerdPlan -> get_forward_housing_demand() -> needed_new_pastures.
  - Sits strictly between DynamicHerdPlan and physical pasture reservation.
  - Decides ONLY: Should one of the already-justified future pasture slots be physically located in SW?
  - Does NOT determine whether housing should exist.
  - Does NOT increase required_pastures, needed_new_pastures, global herd targets, or animal purchases.
  - Respects SW_CELL_MAX_PASTURES = 1 (at most one pasture relocation in SW).
  - Preserves Day-12 cutoff: zero new structures planned or built on/after Day 12.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple

from config import (
    PORT_SW,
    SHED_ACCESS_TILES,
    SW_PASTURE_TILES,
    C4_LIVESTOCK_CUTOFF_DAY,
)


_SW_CELL_TELEMETRY: Dict[str, Any] = {
    "eligible": False,
    "day_first_eligible": None,
    "reserved": False,
    "allocated_tiles": [],
}


def get_sw_cell_telemetry() -> Dict[str, Any]:
    """Return copy of SW cell allocator telemetry."""
    return dict(_SW_CELL_TELEMETRY)


def reset_sw_cell_telemetry() -> None:
    """Reset SW cell allocator telemetry."""
    global _SW_CELL_TELEMETRY
    _SW_CELL_TELEMETRY = {
        "eligible": False,
        "day_first_eligible": None,
        "reserved": False,
        "allocated_tiles": [],
    }


def allocate_sw_pasture_locations(
    farm: Any,
    day: int,
    needed_slots: int,
    existing_sw_pastures: int,
    reserved_sw_pastures: int,
    empty_tiles: List[Tuple[int, int]],
    reserved_crop_tiles: Optional[Set[Tuple[int, int]]] = None,
    sw_cell_enabled: bool = False,
    max_sw_pastures: int = 1,
) -> Tuple[List[Tuple[int, int]], Dict[str, Any]]:
    """Determine whether already-justified pasture slots should be physically sited in SW.

    Args:
        farm: Farm state object with .unlocked and .quadrant_of().
        day: Current game day (0-29).
        needed_slots: Already-justified net new pastures needed from DynamicHerdPlan.
        existing_sw_pastures: Count of physically built pastures already in SW.
        reserved_sw_pastures: Count of SW pastures already queued in reserved_structure_tiles.
        empty_tiles: List of currently empty tile coordinates.
        reserved_crop_tiles: Tiles currently queued or reserved for planting.
        sw_cell_enabled: Master switch for ArmC-Cell treatment.
        max_sw_pastures: Cap on total SW pastures (default 1).

    Returns:
        (allocated_locations, diagnostics_dict)
    """
    diag = {
        "eligible": False,
        "reason": "",
        "needed_slots": needed_slots,
        "existing_sw_pastures": existing_sw_pastures,
        "reserved_sw_pastures": reserved_sw_pastures,
        "allocated_tiles": [],
    }

    # 1. Eligibility Gates
    if not sw_cell_enabled:
        diag["reason"] = "cell_treatment_disabled"
        return [], diag

    unlocked = getattr(farm, "unlocked", set())
    if "SW" not in unlocked:
        diag["reason"] = "sw_not_unlocked"
        return [], diag

    if day >= C4_LIVESTOCK_CUTOFF_DAY:
        diag["reason"] = "day_12_cutoff_reached"
        return [], diag

    if needed_slots <= 0:
        diag["reason"] = "no_housing_demand"
        return [], diag

    total_sw_pastures = existing_sw_pastures + reserved_sw_pastures
    if total_sw_pastures >= max_sw_pastures:
        diag["reason"] = f"sw_cell_capacity_reached_{total_sw_pastures}>={max_sw_pastures}"
        return [], diag

    allowed_quota = min(needed_slots, max_sw_pastures - total_sw_pastures)
    if allowed_quota <= 0:
        diag["reason"] = "zero_allowed_quota"
        return [], diag

    _SW_CELL_TELEMETRY["eligible"] = True
    if _SW_CELL_TELEMETRY["day_first_eligible"] is None:
        _SW_CELL_TELEMETRY["day_first_eligible"] = day

    # 2. Candidate Selection
    # Candidates must be in SW_PASTURE_TILES, empty, not protected, and not reserved for crops
    protected = set(SHED_ACCESS_TILES) | {PORT_SW}
    crop_reserved = reserved_crop_tiles or set()
    empty_set = set(empty_tiles)

    candidates = []
    for pos in SW_PASTURE_TILES:
        if pos in protected:
            continue
        if pos in crop_reserved:
            continue
        if pos not in empty_set:
            continue
        if farm.quadrant_of(pos) != "SW":
            continue

        # Rank by Manhattan distance to PORT_SW (4, 5) to minimize chore travel
        dist_to_port = abs(pos[0] - PORT_SW[0]) + abs(pos[1] - PORT_SW[1])
        candidates.append((dist_to_port, pos))

    candidates.sort(key=lambda item: (item[0], item[1][1], item[1][0]))

    if not candidates:
        diag["reason"] = "no_valid_empty_sw_pasture_tiles"
        return [], diag

    # 3. Allocate up to allowed quota
    allocated = [pos for _, pos in candidates[:allowed_quota]]
    diag["eligible"] = True
    diag["reason"] = "allocated"
    diag["allocated_tiles"] = allocated

    _SW_CELL_TELEMETRY["eligible"] = True
    if _SW_CELL_TELEMETRY["day_first_eligible"] is None:
        _SW_CELL_TELEMETRY["day_first_eligible"] = day
    if allocated:
        _SW_CELL_TELEMETRY["reserved"] = True
        _SW_CELL_TELEMETRY["allocated_tiles"].extend(allocated)

    return allocated, diag

