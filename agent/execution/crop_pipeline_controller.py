"""Kaggriculture Phase M0-A: Same-Turn Crop Pipeline Controller.

Manages detection, qualification, atomic assignment, seed reservation, and telemetry
for the same-turn crop pipeline exploit:
    Worker A: HARVEST
    Worker B: PLANT <crop>
    Worker C: WATER
executed in sequential engine order (u_A < u_B < u_C) in the exact same game turn.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set, Tuple

CROPS_INFO = {
    "WHEAT": {"seed": 10, "max_yield": 3, "max_yield_day": 2, "first_yield_day": 2, "ongoing": False},
    "CARROT": {"seed": 20, "max_yield": 4, "max_yield_day": 2, "first_yield_day": 2, "ongoing": False},
    "TOMATO": {"seed": 50, "max_yield": 4, "max_yield_day": 8, "first_yield_day": 8, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "max_yield": 4, "max_yield_day": 10, "first_yield_day": 10, "ongoing": True},
    "MELON": {"seed": 80, "max_yield": 2, "max_yield_day": 10, "first_yield_day": 10, "ongoing": False},
}

_PIPELINE_TELEMETRY: List[Dict[str, Any]] = []
_PENDING_PIPELINE_VERIFICATIONS: List[Dict[str, Any]] = []


def reset_crop_pipeline_telemetry() -> None:
    """Clear all recorded pipeline telemetry and pending verifications."""
    global _PIPELINE_TELEMETRY, _PENDING_PIPELINE_VERIFICATIONS
    _PIPELINE_TELEMETRY = []
    _PENDING_PIPELINE_VERIFICATIONS = []


def get_crop_pipeline_telemetry() -> List[Dict[str, Any]]:
    """Return immutable snapshot of all recorded pipeline events."""
    return list(_PIPELINE_TELEMETRY)


def is_pipeline_enabled() -> bool:
    try:
        from config import get_same_turn_crop_pipeline_mode
        return get_same_turn_crop_pipeline_mode() == "ON"
    except Exception:
        try:
            from agent.config import get_same_turn_crop_pipeline_mode
            return get_same_turn_crop_pipeline_mode() == "ON"
        except Exception:
            return False


def evaluate_and_assign_pipelines(
    ctx: Dict[str, Any],
    farm: Any,
    pos_by_idx: Dict[int, Tuple[int, int]],
    free_units: Set[int],
    regular_tasks: List[Dict[str, Any]],
    macro: Any,
    reserved_seeds: Dict[str, int],
) -> Tuple[Dict[int, Dict[str, Any]], Set[int], List[Dict[str, Any]]]:
    """Evaluate pipeline candidates and assign co-located ordered workers.

    Returns:
        pipeline_assignments: dict mapping u_idx -> task dict
        newly_busy_units: set of assigned unit indices
        removed_regular_tasks: list of regular tasks superseded by pipeline
    """
    if not is_pipeline_enabled():
        return {}, set(), []

    day = ctx["day"]
    hour = ctx["hour"]
    step = ctx.get("step", day * 24 + hour)
    private = ctx.get("private")
    seeds_owned = dict(private.seeds) if private and hasattr(private, "seeds") else {}

    # Planting cutoff: crops planted after hour 17 cannot be watered before midnight
    if hour > 17:
        return {}, set(), []

    # Map plant_queue for replacement crop lookups
    plant_queue_map = {}
    if macro and hasattr(macro, "plant_queue") and macro.plant_queue:
        for p, c in macro.plant_queue:
            plant_queue_map[tuple(p)] = c

    pipeline_assignments: Dict[int, Dict[str, Any]] = {}
    newly_busy: Set[int] = set()
    removed_tasks: List[Dict[str, Any]] = []

    # Group free units by their current standing position
    units_by_pos: Dict[Tuple[int, int], List[int]] = {}
    for u in sorted(free_units):
        pos = pos_by_idx.get(u)
        if pos is not None:
            units_by_pos.setdefault(pos, []).append(u)

    # Scan candidate tiles
    for t in farm.iter_tiles():
        pos = tuple(t.pos)
        t_quad = farm.quadrant_of(pos) if hasattr(farm, "quadrant_of") else "NW"
        if t_quad not in farm.unlocked:
            continue

        # Condition 1 & 2 & 3: One-time crop, harvestable, HARVEST clears tile
        if not (t.is_plant and t.crop in CROPS_INFO):
            continue
        c_info = CROPS_INFO[t.crop]
        if c_info["ongoing"]:
            continue  # ongoing crops (Tomato, Strawberry) do NOT clear tile on harvest
        if t.yield_units <= 0:
            continue  # not harvestable yet

        age = day - t.planted_day
        if age < c_info["first_yield_day"]:
            continue  # immature

        # Condition 4: Replacement crop selection from macro plan
        replant_crop = plant_queue_map.get(pos, t.crop)
        if replant_crop not in CROPS_INFO:
            replant_crop = t.crop
        rep_info = CROPS_INFO[replant_crop]

        # Condition 9: Economic viability given season remaining
        mat_day = rep_info["max_yield_day"]
        if day + mat_day > 29:
            continue  # crop cannot mature before season ends

        # Condition 5 & 8: Replacement seed owned and reserved
        available_seed = seeds_owned.get(replant_crop, 0) - reserved_seeds.get(replant_crop, 0)
        if available_seed <= 0:
            continue

        # Condition 6 & 7: At least 3 capable units co-located at pos
        co_located = units_by_pos.get(pos, [])
        eligible_cands = [u for u in co_located if u not in newly_busy]
        if len(eligible_cands) < 3:
            continue

        # Sort to strictly enforce engine execution order: u_harvest < u_plant < u_water
        eligible_cands.sort()
        u_harvest = eligible_cands[0]
        u_plant = eligible_cands[1]
        u_water = eligible_cands[2]

        # All 10 conditions satisfied: atomically construct pipeline tasks
        reserved_seeds[replant_crop] = reserved_seeds.get(replant_crop, 0) + 1

        t_harvest = {
            "priority": 95,
            "op": "HARVEST",
            "target": pos,
            "kind": "pipeline_harvest",
            "unit_pos": pos,
            "meta": {"pipeline": True, "role": "HARVEST", "crop": t.crop},
        }
        t_plant = {
            "priority": 95,
            "op": "PLANT",
            "target": pos,
            "args": [replant_crop],
            "kind": "pipeline_plant",
            "unit_pos": pos,
            "meta": {"pipeline": True, "role": "PLANT", "crop": replant_crop, "paired_water": True},
        }
        t_water = {
            "priority": 95,
            "op": "WATER",
            "target": pos,
            "kind": "pipeline_water",
            "unit_pos": pos,
            "meta": {"pipeline": True, "role": "WATER", "crop": replant_crop},
        }

        pipeline_assignments[u_harvest] = t_harvest
        pipeline_assignments[u_plant] = t_plant
        pipeline_assignments[u_water] = t_water

        newly_busy.update([u_harvest, u_plant, u_water])

        # Remove redundant regular tasks targeting this tile
        for rt in list(regular_tasks):
            if tuple(rt.get("target", (-1, -1))) == pos:
                regular_tasks.remove(rt)
                removed_tasks.append(rt)

        # Record pending verification for post-turn telemetry
        event = {
            "step": step,
            "day": day,
            "hour": hour,
            "tile": list(pos),
            "old_crop": t.crop,
            "old_yield": t.yield_units,
            "replacement_crop": replant_crop,
            "harvest_worker": u_harvest,
            "plant_worker": u_plant,
            "water_worker": u_water,
            "worker_positions": [list(pos_by_idx[u]) for u in (u_harvest, u_plant, u_water)],
            "seed_inventory_before": seeds_owned.get(replant_crop, 0),
            "seed_reserved_state": reserved_seeds.get(replant_crop, 0),
            "pipeline_requested": True,
            "harvest_executed": False,
            "plant_executed": False,
            "water_executed": False,
            "replacement_tile_state_after_turn": None,
            "pipeline_success": False,
            "failure_reason": None,
        }
        _PENDING_PIPELINE_VERIFICATIONS.append(event)

    return pipeline_assignments, newly_busy, removed_tasks


def verify_post_turn_pipelines(obs_post: Any, player_id: int = 0) -> None:
    """Verify executed pipeline outcomes from post-turn observation."""
    global _PENDING_PIPELINE_VERIFICATIONS, _PIPELINE_TELEMETRY
    if not _PENDING_PIPELINE_VERIFICATIONS:
        return

    farm_post = obs_post.farms[player_id] if hasattr(obs_post, "farms") else obs_post.get("farms", [{}])[player_id]
    priv_post = obs_post.private if hasattr(obs_post, "private") else obs_post.get("private", {})
    tiles_post = farm_post.tiles if hasattr(farm_post, "tiles") else farm_post.get("tiles", [])
    invs_post = priv_post.inventories if hasattr(priv_post, "inventories") else priv_post.get("inventories", [])

    for ev in _PENDING_PIPELINE_VERIFICATIONS:
        tx, ty = ev["tile"]
        post_tile = tiles_post[ty][tx]
        if hasattr(post_tile, "to_dict"):
            t_dict = post_tile.to_dict()
        elif hasattr(post_tile, "__dict__"):
            t_dict = dict(post_tile.__dict__)
        elif isinstance(post_tile, dict):
            t_dict = dict(post_tile)
        else:
            t_dict = None

        ev["replacement_tile_state_after_turn"] = t_dict

        # Verification 1: Harvest executed (worker inventory received product or tile cleared)
        h_u = ev["harvest_worker"]
        h_inv = invs_post[h_u] if h_u < len(invs_post) else {}
        harvest_ok = (h_inv.get(ev["old_crop"], 0) > 0) or (t_dict is not None and t_dict.get("crop") != ev["old_crop"]) or (t_dict is None)
        ev["harvest_executed"] = harvest_ok

        # Verification 2: Plant executed (tile has new crop)
        plant_ok = (
            isinstance(t_dict, dict)
            and t_dict.get("kind") == "PLANT"
            and t_dict.get("crop") == ev["replacement_crop"]
            and t_dict.get("planted_day") == ev["day"]
        )
        ev["plant_executed"] = plant_ok

        # Verification 3: Water executed (watered_today is True)
        water_ok = (plant_ok and t_dict.get("watered_today") is True)
        ev["water_executed"] = water_ok

        if harvest_ok and plant_ok and water_ok:
            ev["pipeline_success"] = True
            ev["failure_reason"] = None
        else:
            ev["pipeline_success"] = False
            if not harvest_ok:
                ev["failure_reason"] = "HARVEST_NOT_READY"
            elif not plant_ok:
                ev["failure_reason"] = "PLANT_FAILED"
            elif not water_ok:
                ev["failure_reason"] = "WATER_FAILED"

        _PIPELINE_TELEMETRY.append(ev)

    _PENDING_PIPELINE_VERIFICATIONS = []
