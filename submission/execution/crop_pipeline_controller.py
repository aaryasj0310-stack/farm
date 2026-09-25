"""Kaggriculture Phase M0-A / M0-C: Same-Turn Crop Pipeline Controller.

Manages detection, physical qualification, selective economic gating, atomic assignment,
seed reservation, and comprehensive shadow decision telemetry for the same-turn crop pipeline exploit:
    Worker A: HARVEST
    Worker B: PLANT <crop>
    Worker C: WATER
executed in sequential engine order (u_A < u_B < u_C) in the exact same game turn.

Phase M0-C adds selective economic gating to prevent shed congestion, bad market timing,
capital purchase delays, and worker opportunity cost failures.
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

# Rejection Reason Taxonomy (Part I)
REJECTION_SURVIVAL_PRIORITY = "SURVIVAL_PRIORITY"
REJECTION_WORKER_OPPORTUNITY_COST = "WORKER_OPPORTUNITY_COST"
REJECTION_STORAGE_RISK = "STORAGE_RISK"
REJECTION_MARKET_TIMING = "MARKET_TIMING"
REJECTION_LIQUIDITY_CAPITAL_RISK = "LIQUIDITY_CAPITAL_RISK"
REJECTION_SEASON_END_NO_VALUE = "SEASON_END_NO_VALUE"
REJECTION_SEED_CONSTRAINT = "SEED_CONSTRAINT"
REJECTION_UNSUPPORTED_CROP = "UNSUPPORTED_CROP"
REJECTION_INSUFFICIENT_ORDERED_WORKERS = "INSUFFICIENT_ORDERED_WORKERS"
REJECTION_NEGATIVE_NET_VALUE = "NEGATIVE_NET_VALUE"
REJECTION_OTHER = "OTHER"

_PIPELINE_TELEMETRY: List[Dict[str, Any]] = []
_PENDING_PIPELINE_VERIFICATIONS: List[Dict[str, Any]] = []
_SHADOW_DECISIONS: List[Dict[str, Any]] = []
_OPPORTUNITY_COUNTER: int = 0


def reset_crop_pipeline_telemetry() -> None:
    """Clear all recorded pipeline telemetry, pending verifications, and shadow decisions."""
    global _PIPELINE_TELEMETRY, _PENDING_PIPELINE_VERIFICATIONS, _SHADOW_DECISIONS, _OPPORTUNITY_COUNTER
    _PIPELINE_TELEMETRY = []
    _PENDING_PIPELINE_VERIFICATIONS = []
    _SHADOW_DECISIONS = []
    _OPPORTUNITY_COUNTER = 0


def get_crop_pipeline_telemetry() -> List[Dict[str, Any]]:
    """Return immutable snapshot of all recorded pipeline execution events."""
    return list(_PIPELINE_TELEMETRY)


def get_crop_pipeline_shadow_decisions() -> List[Dict[str, Any]]:
    """Return immutable snapshot of all recorded shadow gate decisions."""
    return copy.deepcopy(_SHADOW_DECISIONS)


def get_pipeline_mode() -> str:
    """Return active mode ('OFF', 'GLOBAL', 'SELECTIVE')."""
    try:
        from config import get_same_turn_crop_pipeline_mode
        m = get_same_turn_crop_pipeline_mode()
        return "GLOBAL" if m in ("GLOBAL", "ON") else m
    except Exception:
        try:
            from agent.config import get_same_turn_crop_pipeline_mode
            m = get_same_turn_crop_pipeline_mode()
            return "GLOBAL" if m in ("GLOBAL", "ON") else m
        except Exception:
            return "OFF"


def is_pipeline_enabled() -> bool:
    """Check if pipeline execution is enabled under any non-OFF mode."""
    mode = get_pipeline_mode()
    return mode in ("GLOBAL", "SELECTIVE", "ON")


def evaluate_pipeline_economic_gate(
    ctx: Dict[str, Any],
    farm: Any,
    pos: Tuple[int, int],
    tile: Any,
    replant_crop: str,
    eligible_workers: List[int],
    free_units: Set[int],
    regular_tasks: List[Dict[str, Any]],
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Evaluate whether candidate pipeline satisfies hard safety vetoes and net economic value.

    Returns:
        (accepted, rejection_reasons, gate_metrics)
    """
    reasons: List[str] = []
    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)
    step = ctx.get("step", day * 24 + hour)
    private = ctx.get("private")
    rep_info = CROPS_INFO.get(replant_crop, {})
    mat_day = rep_info.get("max_yield_day", 2)

    # 1. Season-End Waste Veto
    # Crops planted on or after Day 28 cannot mature before match end (Day 29 Hour 23)
    if day + mat_day > 29:
        reasons.append(REJECTION_SEASON_END_NO_VALUE)
    elif replant_crop == "MELON" and day > 19:
        reasons.append(REJECTION_SEASON_END_NO_VALUE)

    # 2. Survival Priority Hard Veto
    # Only veto if an animal is in genuine starvation risk (consecutive_unfed >= 2 or hour >= 18 and >= 1)
    starving_animals = False
    for t_anim in farm.iter_tiles():
        if getattr(t_anim, "is_animal", False):
            unfed = getattr(t_anim, "consecutive_unfed", 0)
            if unfed >= 2 or (unfed >= 1 and hour >= 18):
                starving_animals = True
                break
    if starving_animals:
        reasons.append(REJECTION_SURVIVAL_PRIORITY)

    # Critical watering check (crops at genuine risk of decay, consecutive_unwatered >= 2 or hour >= 18 and >= 1)
    critical_water_needed = False
    for t_plant in farm.iter_tiles():
        if getattr(t_plant, "is_plant", False):
            unwatered = getattr(t_plant, "consecutive_unwatered", 0)
            if (unwatered >= 2 or (unwatered >= 1 and hour >= 18)) and not getattr(t_plant, "watered_today", False):
                critical_water_needed = True
                break
    if critical_water_needed:
        reasons.append(REJECTION_SURVIVAL_PRIORITY)

    # Urgent survival tasks pending in regular queue
    urgent_pending = any(
        rt.get("priority", 0) >= 95 or rt.get("meta", {}).get("urgent", False)
        for rt in regular_tasks
    )
    if urgent_pending:
        reasons.append(REJECTION_SURVIVAL_PRIORITY)

    # 3. Storage Risk Hard Veto
    shed_load = sum(private.shed.values()) if private and hasattr(private, "shed") else 0
    carried_load = (
        sum(sum(inv.values()) for inv in private.inventories)
        if private and hasattr(private, "inventories")
        else 0
    )
    harvest_yield = getattr(tile, "yield_units", 1)
    projected_shed = shed_load + harvest_yield

    # If shed is already at or near critical congestion (>= 92 projected or >= 90 current)
    if projected_shed >= 92 or shed_load >= 90:
        reasons.append(REJECTION_STORAGE_RISK)

    # 4. Liquidity / Capital Risk Hard Veto
    current_cash = getattr(private, "money", 0) if private else 0
    # In days 0–18, if shed is high (>= 85) and cash is tight (< 3000), avoid locking shed capacity
    if day <= 18 and current_cash < 3000 and shed_load >= 85:
        reasons.append(REJECTION_LIQUIDITY_CAPITAL_RISK)

    # 5. Worker Opportunity Cost Hard Veto
    if len(free_units) < 3:
        reasons.append(REJECTION_WORKER_OPPORTUNITY_COST)
    else:
        high_prio_regular = [rt for rt in regular_tasks if rt.get("priority", 0) >= 85]
        if len(high_prio_regular) > max(0, len(free_units) - 3):
            reasons.append(REJECTION_WORKER_OPPORTUNITY_COST)

    # 6. Market Timing / Severe Own-Supply Glut Hard Veto
    crop_in_shed = private.shed.get(tile.crop, 0) if private and hasattr(private, "shed") else 0
    if crop_in_shed >= 50:
        reasons.append(REJECTION_MARKET_TIMING)

    # 7. Net Economic Value Model
    base_benefit = 100.0
    extra_cycle_possible = (29 - day) % mat_day == 0
    extra_cycle_value = 150.0 if extra_cycle_possible else 0.0
    gross_gain = base_benefit + extra_cycle_value

    worker_penalty = 15.0 * max(0, 4 - len(free_units))
    storage_penalty = 10.0 * max(0, projected_shed - 80)
    glut_penalty = 1.5 * max(0, crop_in_shed - 30)
    net_value = gross_gain - worker_penalty - storage_penalty - glut_penalty

    if net_value <= 0:
        reasons.append(REJECTION_NEGATIVE_NET_VALUE)

    accepted = (len(reasons) == 0)
    gate_metrics = {
        "current_shed": shed_load,
        "projected_shed": projected_shed,
        "carried_load": carried_load,
        "current_cash": current_cash,
        "free_worker_count": len(free_units),
        "crop_in_shed": crop_in_shed,
        "extra_cycle_possible": extra_cycle_possible,
        "estimated_net_value": round(net_value, 2),
    }

    return accepted, reasons, gate_metrics


def evaluate_and_assign_pipelines(
    ctx: Dict[str, Any],
    farm: Any,
    pos_by_idx: Dict[int, Tuple[int, int]],
    free_units: Set[int],
    regular_tasks: List[Dict[str, Any]],
    macro: Any,
    reserved_seeds: Dict[str, int],
) -> Tuple[Dict[int, Dict[str, Any]], Set[int], List[Dict[str, Any]]]:
    """Evaluate pipeline candidates, apply economic gating, and assign co-located ordered workers.

    Returns:
        pipeline_assignments: dict mapping u_idx -> task dict
        newly_busy_units: set of assigned unit indices
        removed_regular_tasks: list of regular tasks superseded by pipeline
    """
    global _OPPORTUNITY_COUNTER
    if not is_pipeline_enabled():
        return {}, set(), []

    mode = get_pipeline_mode()

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

        # Condition 1 & 2 & 3: Plant check and ongoing crop exclusion
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

        # Condition 5 & 8: Replacement seed owned and reserved
        available_seed = seeds_owned.get(replant_crop, 0) - reserved_seeds.get(replant_crop, 0)
        if available_seed <= 0:
            continue

        # Condition 6 & 7: Check co-located workers
        co_located = units_by_pos.get(pos, [])
        eligible_cands = [u for u in co_located if u not in newly_busy]
        if len(eligible_cands) < 3:
            continue

        eligible_cands.sort()

        # True physical candidate opportunity identified
        _OPPORTUNITY_COUNTER += 1
        opp_id = _OPPORTUNITY_COUNTER

        # Evaluate Selective Economic Gate
        gate_accepted, rejection_reasons, gate_metrics = evaluate_pipeline_economic_gate(
            ctx, farm, pos, t, replant_crop, eligible_cands, free_units, regular_tasks
        )

        # Record Shadow Decision Telemetry (Part H & I)
        shadow_record = {
            "opportunity_id": opp_id,
            "step": step,
            "day": day,
            "hour": hour,
            "tile": list(pos),
            "old_crop": t.crop,
            "old_yield": t.yield_units,
            "replacement_crop": replant_crop,
            "physical_eligible": True,
            "mode": mode,
            "gate_accepted": gate_accepted,
            "rejection_reasons": rejection_reasons,
            "metrics": gate_metrics,
            "decision": "EXECUTE" if (mode == "GLOBAL") or (mode == "SELECTIVE" and gate_accepted) else "REJECT",
        }
        _SHADOW_DECISIONS.append(shadow_record)

        # In SELECTIVE mode: gate MUST accept
        if mode == "SELECTIVE" and not gate_accepted:
            continue

        # Strictly enforce engine execution order: u_harvest < u_plant < u_water
        u_harvest = eligible_cands[0]
        u_plant = eligible_cands[1]
        u_water = eligible_cands[2]

        # Atomically construct pipeline tasks
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
            "opportunity_id": opp_id,
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
