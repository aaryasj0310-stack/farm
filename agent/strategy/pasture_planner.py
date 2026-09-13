"""Dynamic near-shed pasture capacity planner for Kaggriculture livestock.

Replaces the stale fixed 9-pasture ceiling with dynamic near-shed pasture capacity:
1. Scans empty tiles across unlocked NW, NE, and SW quadrants (SE excluded).
2. Protects SHED_ACCESS_TILES [(4,4), (5,4), (4,5), (5,5)] and PORT_SW (4,5).
3. Ranks candidates outward by Manhattan distance to the central shed.
4. Derives species-specific marginal animal profit sequence (COW, SHEEP) respecting
   C4 cutoff (Day 12), SHEEP_CAP (12), COW_CAP (19), and HERD_CAP (20).
5. Subtracts marginal crop opportunity value (_crop_score * remaining days).
6. Subtracts worker build action opportunity cost ($25) and daily chore logistics penalty.
7. Derives dynamic_max_pastures from economically positive candidates.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple

from config import (
    CROPS,
    EARLY_PASTURE_TILES,
    PORT_SW,
    SHED_ACCESS_TILES,
    SW_PASTURE_TILES,
)
from strategy.animal_planner import (
    COW_CAP,
    HERD_CAP,
    SHEEP_CAP,
    C4_LIVESTOCK_CUTOFF_DAY,
    estimate_species_remaining_profit,
)

# Calibrated action and logistics cost heuristics
BUILD_ACTION_OPPORTUNITY_COST = 25.0
LOGISTICS_CHORE_STEP_COST = 1.0


def distance_to_shed(pos: Tuple[int, int]) -> int:
    """Manhattan distance from pos to the nearest usable central shed access tile."""
    return min(abs(pos[0] - access[0]) + abs(pos[1] - access[1]) for access in SHED_ACCESS_TILES)


def get_marginal_animal_profit_sequence(
    day: int,
    current_animals: Optional[Dict[str, int]],
    n_slots: int,
    cutoff_day: Optional[int] = None,
) -> List[Tuple[float, str]]:
    """Derive an ordered marginal-value sequence for successive pasture slots.

    Greedily assigns each slot to the species with highest remaining profit
    that has not yet reached its species cap (SHEEP_CAP=12, COW_CAP=19).
    Total herd cannot exceed HERD_CAP=20.
    Returns: list of (profit, species_name) for each slot.
    """
    try:
        from config import (
            SELECTIVE_LIVESTOCK_GATE_ENABLED,
            SELECTIVE_LIVESTOCK_GATE_THRESHOLD,
            SELECTIVE_LIVESTOCK_MAX_DAY,
        )
    except ImportError:
        SELECTIVE_LIVESTOCK_GATE_ENABLED = False
        SELECTIVE_LIVESTOCK_GATE_THRESHOLD = 500.0
        SELECTIVE_LIVESTOCK_MAX_DAY = 14

    effective_cutoff = C4_LIVESTOCK_CUTOFF_DAY if cutoff_day is None else int(cutoff_day)
    if day >= effective_cutoff and SELECTIVE_LIVESTOCK_GATE_ENABLED and day <= SELECTIVE_LIVESTOCK_MAX_DAY:
        from strategy.marginal_livestock_valuator import estimate_realized_marginal_animal_value
        eval_c = estimate_realized_marginal_animal_value("COW", day, current_animals or {}, empty_pastures=1)
        eval_s = estimate_realized_marginal_animal_value("SHEEP", day, current_animals or {}, empty_pastures=1)
        c_prof = float(eval_c["net_realized_value"]) if eval_c["net_realized_value"] >= SELECTIVE_LIVESTOCK_GATE_THRESHOLD else 0.0
        s_prof = float(eval_s["net_realized_value"]) if eval_s["net_realized_value"] >= SELECTIVE_LIVESTOCK_GATE_THRESHOLD else 0.0
    else:
        profits = estimate_species_remaining_profit(day, cutoff_day=cutoff_day)
        s_prof = float(profits.get("SHEEP", 0.0))
        c_prof = float(profits.get("COW", 0.0))

    c_cur = int(current_animals.get("COW", 0)) if current_animals else 0
    s_cur = int(current_animals.get("SHEEP", 0)) if current_animals else 0

    slot_profits: List[Tuple[float, str]] = []
    for _ in range(max(0, n_slots)):
        total_herd = c_cur + s_cur
        if total_herd >= HERD_CAP:
            slot_profits.append((0.0, "HERD_CAP_REACHED"))
            continue

        can_sheep = (s_cur < SHEEP_CAP and s_prof > 0.0)
        can_cow = (c_cur < COW_CAP and c_prof > 0.0)

        if can_sheep and can_cow:
            if s_prof >= c_prof:
                slot_profits.append((s_prof, "SHEEP"))
                s_cur += 1
            else:
                slot_profits.append((c_prof, "COW"))
                c_cur += 1
        elif can_sheep:
            slot_profits.append((s_prof, "SHEEP"))
            s_cur += 1
        elif can_cow:
            slot_profits.append((c_prof, "COW"))
            c_cur += 1
        else:
            slot_profits.append((0.0, "NO_PROFITABLE_SPECIES"))

    return slot_profits


def estimate_crop_opportunity_value(
    day: int,
    forecast: Any,
    boosts: Optional[Dict[str, float]] = None,
    committed_counts: Optional[Dict[str, int]] = None,
    crop_score_func: Any = None,
    crop_allowed_func: Any = None,
    n_animals: int = 0,
    opp_advice: Any = None,
) -> Tuple[float, Optional[str]]:
    """Compute best expected remaining-season net coins if tile remains agricultural.

    Uses existing _crop_score() evaluated at own_tiles = committed_counts.get(crop, 0),
    representing the marginal next tile under own-supply pressure.
    Converts per_day return back to remaining-season net: per_day * max(1, 30 - day).
    """
    if boosts is None:
        boosts = {c: 1.0 for c in CROPS}
    if committed_counts is None:
        committed_counts = {}
    best_crop_val = 0.0
    best_crop_name = None
    remaining_days = max(1, 30 - day)

    for crop in CROPS:
        if not crop_allowed_func(crop, day):
            continue
        own_for_this = int(committed_counts.get(crop, 0)) if committed_counts else 0
        per_day, _ = crop_score_func(
            crop,
            day,
            forecast,
            boosts,
            own_tiles=own_for_this,
            feed_wheat_per_day=n_animals,
            n_animals=n_animals,
            opp_advice=opp_advice,
        )
        total_val = max(0.0, float(per_day) * remaining_days)
        if total_val > best_crop_val:
            best_crop_val = total_val
            best_crop_name = crop

    return best_crop_val, best_crop_name


def evaluate_pasture_candidates(
    farm: Any,
    day: int,
    empty_tiles: List[Tuple[int, int]],
    current_animals: Dict[str, int],
    crop_opportunity_val: float,
    crop_name: Optional[str] = None,
    cutoff_day: Optional[int] = None,
    preferred_sw_tiles: Optional[Set[Tuple[int, int]]] = None,
    preferred_early_tiles: Optional[List[Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    """Scan and evaluate all eligible empty tiles for dynamic pasture capacity.

    Pipeline:
    1. Filter empty tiles in unlocked NW, NE, SW (SE strictly excluded).
    2. Exclude SHED_ACCESS_TILES and PORT_SW.
    3. Calculate Manhattan distance to nearest shed access.
    4. Derive species-specific marginal animal profit sequence.
    5. Deduct crop opportunity, build action opportunity cost, and logistics penalty.
    6. Rank positive candidates by distance ascending, then net value descending.
    """
    preferred_sw = preferred_sw_tiles if preferred_sw_tiles is not None else SW_PASTURE_TILES
    preferred_early = preferred_early_tiles if preferred_early_tiles is not None else EARLY_PASTURE_TILES
    protected_positions = set(SHED_ACCESS_TILES) | {PORT_SW}

    existing_pastures = sum(1 for t in farm.iter_tiles() if getattr(t, "kind", None) == "PASTURE")
    existing_empty_pastures = sum(
        1 for t in farm.iter_tiles()
        if getattr(t, "kind", None) == "PASTURE" and not getattr(t, "is_animal", False)
    )

    # 1. Filter valid empty candidate tiles
    raw_cands = []
    for pos in empty_tiles:
        if pos in protected_positions:
            continue
        quad = farm.quadrant_of(pos)
        if quad not in farm.unlocked or quad in ("SE", "SW"):
            continue
        dist = distance_to_shed(pos)
        raw_cands.append({
            "pos": pos,
            "quadrant": quad,
            "distance_to_shed": dist,
            "is_preferred_early": pos in preferred_early,
            "is_preferred_sw": pos in preferred_sw,
        })

    # Sort raw candidates initially by distance ascending to evaluate closest slots first
    raw_cands.sort(key=lambda c: (
        c["distance_to_shed"],
        0 if c["is_preferred_early"] else (1 if c["is_preferred_sw"] else 2),
        c["pos"][1],
        c["pos"][0],
    ))

    # 2. Derive marginal profit sequence for available candidate slots,
    # offsetting by unused existing pasture capacity (geese use coops, not pastures)
    current_large_livestock = (
        int(current_animals.get("COW", 0))
        + int(current_animals.get("SHEEP", 0))
    ) if current_animals else 0

    unused_existing_capacity = max(
        0,
        existing_pastures - current_large_livestock
    )

    full_sequence = get_marginal_animal_profit_sequence(
        day=day,
        current_animals=current_animals,
        n_slots=unused_existing_capacity + len(raw_cands),
        cutoff_day=cutoff_day,
    )
    candidate_sequence = full_sequence[unused_existing_capacity:]

    remaining_production_days = max(0, 29 - day)
    evaluated_candidates = []
    positive_candidates = []

    # 3. Evaluate each slot
    for idx, cand in enumerate(raw_cands):
        marg_profit, species = candidate_sequence[idx] if idx < len(candidate_sequence) else (0.0, "OUT_OF_BOUNDS")
        dist = cand["distance_to_shed"]

        logistics_penalty = float(dist * remaining_production_days * LOGISTICS_CHORE_STEP_COST)
        build_cost = BUILD_ACTION_OPPORTUNITY_COST

        net_val = round(marg_profit - crop_opportunity_val - build_cost - logistics_penalty, 2)
        accepted = (net_val > 0.0 and marg_profit > 0.0)

        reason = "accepted" if accepted else (
            "c4_cutoff" if day >= C4_LIVESTOCK_CUTOFF_DAY else (
                "cap_reached" if marg_profit <= 0.0 else (
                    "crop_opportunity_higher" if marg_profit - crop_opportunity_val <= 0.0 else "logistics_overhead"
                )
            )
        )

        entry = {
            "pos": cand["pos"],
            "quadrant": cand["quadrant"],
            "distance_to_shed": dist,
            "is_preferred_early": cand["is_preferred_early"],
            "is_preferred_sw": cand["is_preferred_sw"],
            "marginal_livestock_value": marg_profit,
            "target_species": species,
            "crop_opportunity_value": crop_opportunity_val,
            "best_crop": crop_name,
            "build_action_cost": build_cost,
            "logistics_penalty": logistics_penalty,
            "net_pasture_value": net_val,
            "accepted": accepted,
            "reason": reason,
        }
        evaluated_candidates.append(entry)
        if accepted:
            positive_candidates.append(entry)

    # 4. Rank positive candidates: economics (-net_val) first, then distance ascending,
    # historical preference as deterministic tie-breaker, then coordinates
    positive_candidates.sort(key=lambda c: (
        -c["net_pasture_value"],
        c["distance_to_shed"],
        0 if c["is_preferred_early"] else (1 if c["is_preferred_sw"] else 2),
        c["pos"][1],
        c["pos"][0],
    ))

    for rank, cand in enumerate(positive_candidates, 1):
        cand["rank"] = rank

    # 5. Compute dynamic pasture capacity
    dynamic_max_pastures = min(HERD_CAP, existing_pastures + len(positive_candidates))

    return {
        "current_large_livestock": current_large_livestock,
        "existing_pastures": existing_pastures,
        "existing_empty_pastures": existing_empty_pastures,
        "unused_existing_pasture_capacity": unused_existing_capacity,
        "first_new_pasture_marginal_slot": (unused_existing_capacity + 1) if candidate_sequence else None,
        "dynamic_candidates_count": len(evaluated_candidates),
        "positive_candidates_count": len(positive_candidates),
        "dynamic_max_pastures": dynamic_max_pastures,
        "positive_candidates": positive_candidates,
        "all_candidates": evaluated_candidates,
    }
