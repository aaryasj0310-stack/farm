"""Physics-grounded Land Serviceability and Partial SW Exploitation Model.

Replaces the crude binary labor gate with an authoritative capacity,
workload, travel burden, and economic marginal value model.

Architecture:
  real runtime workforce (planned hands)
          ↓
  empirically calibrated effective capacity (EFFECTIVE_ACTIONS_PER_UNIT = 12)
          ↓
  existing mandatory NW/NE workload (runtime task predicates)
          ↓
  available marginal effective capacity
          ↓
  actual SW zoning (15 soil tiles sorted by shed proximity)
          ↓
  serviceable tile count evaluation (k in {5, 10, 15})
          ↓
  exceptional SW travel overhead + displaced NW/NE opportunity cost
          ↓
  realizable marginal SW profit
          ↓
  buy SW / do not buy SW decision
"""
import math
from typing import Dict, Any, Tuple, List, Optional, Set
from config import (
    EFFECTIVE_ACTIONS_PER_UNIT,
    get_target_hands,
    CROPS,
    ANIMALS,
    TARGET_COWS,
    TARGET_SHEEP,
    PORT_SW,
    SW_SOIL_TILES,
    LAND_PRICES,
    TURNS_PER_DAY,
)
from state.observation_parser import (
    crop_age,
    needs_water_today,
    in_bonus_window,
    turns_until_decay,
)


SW_FORCE_K_TILES: Optional[int] = None
DYNAMIC_ZONAL_ALLOCATION: bool = False
# Helper to read tile fields whether tile is a Tile object or a dict
# ---------------------------------------------------------------------------
def _t_field(t: Any, field: str, default: Any = None) -> Any:
    if isinstance(t, dict):
        return t.get(field, default)
    return getattr(t, field, default)


def _t_pos(t: Any) -> Tuple[int, int]:
    if isinstance(t, dict):
        if "pos" in t:
            return tuple(t["pos"])
        return (t.get("x", 0), t.get("y", 0))
    return tuple(t.pos)


# ---------------------------------------------------------------------------
# Sorted SW soil tiles by Manhattan distance to shed access port (4, 4)
# ---------------------------------------------------------------------------
SHED_POS = (4, 4)

def get_sorted_sw_soil_tiles() -> List[Tuple[int, int]]:
    """Return SW soil tiles sorted ascending by Manhattan distance to shed (4, 4)."""
    return sorted(
        list(SW_SOIL_TILES),
        key=lambda p: abs(p[0] - SHED_POS[0]) + abs(p[1] - SHED_POS[1])
    )


# ---------------------------------------------------------------------------
# 1. Effective Workforce Capacity
# ---------------------------------------------------------------------------
def compute_daily_labor_capacity(day: int, safety_margin: float = 0.15) -> Dict[str, Any]:
    """Compute authoritative daily labor capacity from scheduled workforce.

    Uses EFFECTIVE_ACTIONS_PER_UNIT = 12 from config as the empirical foundation.
    Safety reserve (default 15%) accounts for unexpected weed clearing, clustered harvests,
    and emergency pathing detours.
    """
    planned_hands = get_target_hands(day)
    worker_count = 1 + planned_hands  # Farmer + scheduled hands

    theoretical_ap = worker_count * TURNS_PER_DAY
    raw_effective_actions = worker_count * EFFECTIVE_ACTIONS_PER_UNIT

    safety_reserve_actions = round(raw_effective_actions * safety_margin, 1)
    usable_effective_actions = max(0.0, raw_effective_actions - safety_reserve_actions)

    return {
        "day": day,
        "planned_hands": planned_hands,
        "worker_count": worker_count,
        "theoretical_ap": theoretical_ap,
        "raw_effective_capacity": raw_effective_actions,
        "safety_reserve_actions": safety_reserve_actions,
        "usable_effective_actions": usable_effective_actions,
    }


# ---------------------------------------------------------------------------
# 2. Existing Mandatory NW / NE Workload
# ---------------------------------------------------------------------------
def compute_existing_workload(farm, day: int) -> Dict[str, Any]:
    """Compute existing workload committed on established NW and NE tiles.

    Directly applies the same predicates as task_scheduler.py:
    - Survival watering (consecutive_unwatered >= 1 or newly planted)
    - Bonus / regular watering (in_bonus_window or needs_water_today)
    - Harvests (turns_until_decay <= 4, mature max yield, or accumulated ongoing yield >= 2)
    - Animal care (feeding and product collection)
    """
    nw_ops = 0.0
    ne_ops = 0.0
    survival_water_count = 0
    regular_water_count = 0
    harvest_count = 0
    animal_ops = 0.0

    if hasattr(farm, "iter_tiles") and hasattr(farm, "quadrant_of"):
        for t in farm.iter_tiles():
            pos = _t_pos(t)
            q = farm.quadrant_of(pos)
            if q not in ("NW", "NE"):
                continue

            is_plant = bool(_t_field(t, "is_plant", False) or _t_field(t, "kind") == "PLANT")
            is_animal = bool(_t_field(t, "is_animal", False) or _t_field(t, "kind") == "ANIMAL")

            # Crop workload
            if is_plant:
                crop_name = _t_field(t, "crop")
                cd = CROPS.get(crop_name)
                if cd is None:
                    continue

                try:
                    age = crop_age(t, day)
                except Exception:
                    planted_day = _t_field(t, "planted_day", 0)
                    age = max(0, day - planted_day)

                watered = bool(_t_field(t, "watered_today", False))
                consec_unw = int(_t_field(t, "consecutive_unwatered", 0))
                planted_d = int(_t_field(t, "planted_day", -1))

                # Survival water
                if not watered:
                    if consec_unw >= 1 or planted_d == day:
                        survival_water_count += 1
                        if q == "NW": nw_ops += 1.0
                        else: ne_ops += 1.0
                    else:
                        try:
                            needs_w = needs_water_today(t, day) or in_bonus_window(t, day) or cd.get("ongoing")
                        except Exception:
                            needs_w = (day <= cd.get("max_yield_day", 10))
                        if needs_w:
                            regular_water_count += 1
                            if q == "NW": nw_ops += 1.0
                            else: ne_ops += 1.0

                # Harvests
                try:
                    tud = turns_until_decay(t, day * 24)
                except Exception:
                    tud = None
                yield_units = int(_t_field(t, "yield_units", 0))
                if yield_units > 0:
                    is_urgent_harvest = (tud is not None and tud <= 4) or (age >= cd.get("max_yield_day", 99))
                    is_accum_harvest = cd.get("ongoing", False) and yield_units >= 2
                    if is_urgent_harvest or is_accum_harvest or yield_units >= cd.get("max_yield", 99):
                        harvest_count += 1
                        if q == "NW": nw_ops += 1.0
                        else: ne_ops += 1.0

            # Animal workload
            elif is_animal:
                fed = bool(_t_field(t, "fed_today", False))
                # Feeding: each animal needs 1 feeding per day
                if not fed:
                    animal_ops += 1.0
                    if q == "NW": nw_ops += 1.0
                    else: ne_ops += 1.0
                # Harvest product if ready
                if int(_t_field(t, "yield_units", 0)) > 0:
                    animal_ops += 1.0
                    if q == "NW": nw_ops += 1.0
                    else: ne_ops += 1.0

    total_existing = nw_ops + ne_ops

    return {
        "nw_workload": round(nw_ops, 1),
        "ne_workload": round(ne_ops, 1),
        "total_existing_workload": round(total_existing, 1),
        "survival_water_count": survival_water_count,
        "regular_water_count": regular_water_count,
        "harvest_count": harvest_count,
        "animal_ops": animal_ops,
    }


# ---------------------------------------------------------------------------
# 3. Candidate SW Workload & Calibrated Travel Overhead
# ---------------------------------------------------------------------------
def compute_candidate_sw_workload(k_tiles: int, day: int) -> Dict[str, Any]:
    """Compute daily incremental effective workload for k activated SW soil tiles.

    Calibrated from replay telemetry of the known bad experiment:
    - In SW, 1,547 walk actions across 516 completions ≈ 3.0 walk steps / operation.
    - Normal established NW/NE work spends ~1.0 walk step / operation.
    - Exceptional SW travel burden = 3.0 - 1.0 = 2.0 extra walking steps per operation.
    - In effective-action units (where 1 effective action ≈ 2 hourly steps),
      each SW operation requires:
      1.0 base op + 1.0 exceptional transit = 2.0 effective action equivalents.

    Daily operations on k soil tiles:
    - Average ~1.3 daily operations per active crop tile.
    """
    sorted_tiles = get_sorted_sw_soil_tiles()[:k_tiles]
    if not sorted_tiles:
        return {
            "k_tiles": 0,
            "sw_daily_ops": 0.0,
            "sw_travel_burden": 0.0,
            "sw_total_effective_workload": 0.0,
            "avg_dist_to_shed": 0.0,
        }

    avg_dist = sum(abs(p[0] - SHED_POS[0]) + abs(p[1] - SHED_POS[1]) for p in sorted_tiles) / len(sorted_tiles)

    # Base operations per tile per day:
    # 1 watering per day (or ground prep + plant + harvest spread over lifecycle) ≈ 1.3 ops/tile/day
    daily_ops_per_tile = 1.3
    sw_daily_ops = round(k_tiles * daily_ops_per_tile, 1)

    # Exceptional travel burden in effective action equivalents:
    sw_travel_burden = round(sw_daily_ops * (avg_dist / 4.0) * 0.75, 1)

    sw_total_effective_workload = round(sw_daily_ops + sw_travel_burden, 1)

    return {
        "k_tiles": k_tiles,
        "sw_daily_ops": sw_daily_ops,
        "sw_travel_burden": sw_travel_burden,
        "sw_total_effective_workload": sw_total_effective_workload,
        "avg_dist_to_shed": round(avg_dist, 2),
    }


# ---------------------------------------------------------------------------
# 4. Comprehensive SW Serviceability & Realizable ROI Evaluation
# ---------------------------------------------------------------------------
def evaluate_sw_serviceability(
    current_day: int,
    farm,
    money: float,
    forecast,
    target_quadrant: int = 3,
    force_k_tiles: Optional[int] = None,
) -> Tuple[bool, int, Dict[str, Any]]:
    """Evaluate whether buying and partially exploiting SW generates positive net marginal EV.

    Evaluates discrete candidate soil tile counts k in {5, 10, 15}.
    Returns:
      (is_serviceable, best_k, diagnostic_dict)
    """
    if target_quadrant != 3:
        return True, 0, {"reason": "not_sw"}

    # 1. Capacity and post-unlock zonal squad partition
    cap = compute_daily_labor_capacity(current_day)
    worker_count = cap["worker_count"]

    try:
        from config import DYNAMIC_ZONAL_ALLOCATION as _cfg_dyn
        use_dynamic = bool(_cfg_dyn)
    except Exception:
        use_dynamic = DYNAMIC_ZONAL_ALLOCATION

    if not use_dynamic and worker_count < 5:
        return False, 0, {"reason": "insufficient_units_for_sw_partition", "worker_count": worker_count}
    elif use_dynamic and worker_count < 2:
        return False, 0, {"reason": "insufficient_units_for_dynamic_sw", "worker_count": worker_count}

    if not use_dynamic:
        # Static Rule W1 partition
        sw_squad = 5 if worker_count >= 13 else 4
        non_sw = max(1, worker_count - sw_squad)
        nw_squad = max(1, non_sw // 2)
        ne_squad = max(1, non_sw - nw_squad)
        nw_cap = round(nw_squad * EFFECTIVE_ACTIONS_PER_UNIT * 0.85, 1)
        ne_cap = round(ne_squad * EFFECTIVE_ACTIONS_PER_UNIT * 0.85, 1)
        sw_cap = round(sw_squad * EFFECTIVE_ACTIONS_PER_UNIT * 0.85, 1)
    else:
        sw_squad = 0
        nw_squad = 0
        ne_squad = 0
        nw_cap = 0.0
        ne_cap = 0.0
        sw_cap = 0.0

    # 2. Existing mandatory NW / NE workload and committed steady-state demand
    workload = compute_existing_workload(farm, current_day)
    nw_wl = workload["nw_workload"]
    ne_wl = workload["ne_workload"]
    existing_wl = workload["total_existing_workload"]

    # Count active crops and pastures/animals across NW and NE
    nw_crops = 0
    ne_crops = 0
    nw_animals = 0
    ne_animals = 0
    if hasattr(farm, "iter_tiles") and hasattr(farm, "quadrant_of"):
        for t in farm.iter_tiles():
            pos = _t_pos(t)
            q = farm.quadrant_of(pos)
            if q == "NW":
                if _t_field(t, "is_plant") or _t_field(t, "kind") == "PLANT":
                    nw_crops += 1
                elif _t_field(t, "is_animal") or _t_field(t, "animal") or _t_field(t, "kind") in ("PASTURE", "COOP"):
                    nw_animals += 1
            elif q == "NE":
                if _t_field(t, "is_plant") or _t_field(t, "kind") == "PLANT":
                    ne_crops += 1
                elif _t_field(t, "is_animal") or _t_field(t, "animal") or _t_field(t, "kind") in ("PASTURE", "COOP"):
                    ne_animals += 1

    # Animals/pastures demand committed daily labor:
    # Each cow/pasture in NW: 2.0 effective actions (feed + adjacent shed transit + milk)
    # Each sheep/pasture in NE: 5.0 effective actions (feed + cross-quadrant NW shed transit + shear)
    # If livestock strategy is active (cows in NW, NE unlocked with active cultivation), project TARGET_SHEEP
    target_sheep = ne_animals
    if nw_animals > 0 and len(getattr(farm, "unlocked", [])) >= 2 and (ne_crops > 0 or ne_animals > 0):
        target_sheep = max(ne_animals, TARGET_SHEEP)

    nw_wl_steady = (nw_crops * 1.3) + (nw_animals * 2.0)
    ne_wl_steady = (ne_crops * 1.3) + (target_sheep * 5.0)

    nw_committed = max(nw_wl, nw_wl_steady)
    ne_committed = max(ne_wl, ne_wl_steady)

    days_remaining = max(0, 29 - current_day)
    days_impact = max(1, min(5, days_remaining))
    land_price = float(LAND_PRICES[1]) if len(LAND_PRICES) > 1 else 2000.0

    if not use_dynamic:
        # Compute zonal deficits under the post-unlock partition
        nw_deficit = max(0.0, nw_committed - nw_cap)
        ne_deficit = max(0.0, ne_committed - ne_cap)
        opportunity_cost_nw_ne = round((nw_deficit * 50.0 + ne_deficit * 100.0) * days_impact, 1)
        sw_labor_cost = round(sw_squad * 30.0 * days_remaining, 1)
        surplus_units = 0
    else:
        # Dynamic units committed to NW and NE
        eff_ap = float(EFFECTIVE_ACTIONS_PER_UNIT)
        nw_mand_units = math.ceil(nw_committed / eff_ap)
        ne_mand_units = math.ceil(ne_committed / eff_ap)
        nw_cap = round(nw_mand_units * eff_ap * 0.85, 1)
        ne_cap = round(ne_mand_units * eff_ap * 0.85, 1)
        nw_deficit = 0.0
        ne_deficit = 0.0
        opportunity_cost_nw_ne = 0.0
        tot_mand = nw_mand_units + ne_mand_units
        surplus_units = max(0, worker_count - tot_mand)
        sw_labor_cost = 0.0

    # 3. Evaluate discrete candidate tile levels
    active_force_k = force_k_tiles if force_k_tiles is not None else SW_FORCE_K_TILES
    try:
        from config import SW_FORCE_K_TILES as _cfg_force_k
        if active_force_k is None and _cfg_force_k is not None:
            active_force_k = _cfg_force_k
    except Exception:
        pass
    candidates = [active_force_k] if active_force_k is not None else [5, 10, 15]
    evaluations = []

    for k in candidates:
        sw_wl = compute_candidate_sw_workload(k, current_day)
        req_actions = sw_wl["sw_total_effective_workload"]

        if not use_dynamic:
            # Serviceability fraction: how much of proposed k tiles SW squad can service
            if req_actions > 0:
                serv_fraction = min(1.0, sw_cap / req_actions)
            else:
                serv_fraction = 1.0
            k_serviceable = math.floor(k * serv_fraction)
            curr_sw_labor_cost = sw_labor_cost
            curr_opp_cost = opportunity_cost_nw_ne
            curr_sw_squad = sw_squad
            curr_sw_cap = sw_cap
        else:
            # Dynamic: allocate units from surplus capacity based on usable action budget
            usable_per_unit = eff_ap * 0.85
            sw_req_units = math.ceil(req_actions / usable_per_unit)
            curr_sw_squad = min(surplus_units, sw_req_units)
            curr_sw_cap = round(curr_sw_squad * usable_per_unit, 1)
            if req_actions > 0:
                serv_fraction = min(1.0, curr_sw_cap / req_actions)
            else:
                serv_fraction = 1.0
            k_serviceable = math.floor(k * serv_fraction)
            curr_sw_labor_cost = round(curr_sw_squad * 30.0 * days_remaining, 1)
            curr_opp_cost = 0.0

        # Economic projection over remaining days:
        # Fast cash crop: Carrot (cycle = 3 days, seed = $20, revenue ≈ 4 * $35 = $140, profit ≈ $120/cycle)
        cycles = max(0, days_remaining // 3)
        nominal_gross_rev = k * cycles * 140.0
        nominal_seed_spend = k * cycles * 20.0

        # Realizable revenue based on fully serviceable tile count
        realizable_gross_rev = k_serviceable * cycles * 140.0
        realizable_seed_spend = k_serviceable * cycles * 20.0

        # Realizable marginal profit after land, dedicated SW labor, and displaced NW/NE opportunity cost
        net_marginal_profit = round(
            realizable_gross_rev - realizable_seed_spend - land_price - curr_sw_labor_cost - curr_opp_cost, 1
        )
        serv_adjusted_roi = round(net_marginal_profit / max(1.0, land_price), 4)
        payback_surplus = round(
            realizable_gross_rev - (land_price + realizable_seed_spend + curr_sw_labor_cost + curr_opp_cost), 1
        )

        evaluations.append({
            "k_tiles": k,
            "k_serviceable": k_serviceable,
            "serviceability_fraction": round(serv_fraction, 3),
            "req_actions": req_actions,
            "sw_travel_burden": sw_wl["sw_travel_burden"],
            "realizable_gross_rev": realizable_gross_rev,
            "realizable_seed_spend": realizable_seed_spend,
            "sw_labor_cost": curr_sw_labor_cost,
            "opportunity_cost_nw_ne": curr_opp_cost,
            "net_marginal_profit": net_marginal_profit,
            "serv_adjusted_roi": serv_adjusted_roi,
            "payback_surplus": payback_surplus,
            "sw_squad": curr_sw_squad,
            "sw_cap": curr_sw_cap,
        })

    # Pick best k: strictly prioritize candidates that do NOT displace NW/NE work
    min_serv_k = 4 if use_dynamic else 5
    min_serv_frac = 0.80 if use_dynamic else 0.85
    zero_displacement = [
        e for e in evaluations
        if e["opportunity_cost_nw_ne"] <= 0.0 and e["serviceability_fraction"] >= min_serv_frac and e["k_serviceable"] >= min_serv_k
    ]

    if zero_displacement:
        zero_displacement.sort(key=lambda x: x["net_marginal_profit"], reverse=True)
        best_eval = zero_displacement[0]
        is_serviceable = (best_eval["net_marginal_profit"] > 0 and best_eval["payback_surplus"] > 0)
    else:
        # None can be serviced without displacing NW/NE work
        evaluations.sort(key=lambda x: x["net_marginal_profit"], reverse=True)
        best_eval = evaluations[0]
        is_serviceable = False

    best_k = best_eval["k_tiles"]

    diag = {
        "day": current_day,
        "planned_hands": cap["planned_hands"],
        "worker_count": cap["worker_count"],
        "theoretical_ap": cap["theoretical_ap"],
        "usable_effective_actions": cap["usable_effective_actions"],
        "sw_squad": best_eval.get("sw_squad", sw_squad),
        "nw_squad": nw_squad,
        "ne_squad": ne_squad,
        "sw_cap": best_eval.get("sw_cap", sw_cap),
        "nw_cap": nw_cap,
        "ne_cap": ne_cap,
        "existing_workload": existing_wl,
        "nw_workload": nw_wl,
        "ne_workload": ne_wl,
        "nw_deficit": round(nw_deficit, 1),
        "ne_deficit": round(ne_deficit, 1),
        "available_marginal_ap": round(max(0.0, sw_cap - best_eval["req_actions"]), 1),
        "best_k_tiles": best_k,
        "best_k_serviceable": best_eval["k_serviceable"],
        "serviceability_fraction": best_eval["serviceability_fraction"],
        "candidate_sw_workload": best_eval["req_actions"],
        "estimated_travel_overhead": best_eval["sw_travel_burden"],
        "sw_labor_cost": sw_labor_cost,
        "net_marginal_profit": best_eval["net_marginal_profit"],
        "serviceability_adjusted_roi": best_eval["serv_adjusted_roi"],
        "payback_surplus": best_eval["payback_surplus"],
        "expected_nw_ne_opportunity_cost": best_eval["opportunity_cost_nw_ne"],
        "is_serviceable": is_serviceable,
        "all_evaluations": evaluations,
    }

    return is_serviceable, best_k, diag
