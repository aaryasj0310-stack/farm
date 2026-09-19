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


def _fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def compute_projected_workers(farm, day: int, money: Optional[float] = None, hour: int = 0) -> int:
    """Compute projected available workers accounting for guaranteed incoming morning hires.

    projected_workers = 1 + current_hands + guaranteed_incoming_hands
    where guaranteed_incoming_hands:
    - are part of the actual current-day hire plan (get_target_hands(day))
    - are affordable under current cash and authoritative hire pricing (Fibonacci)
    - are guaranteed to be emitted on the morning market turn (top priority Tier 0, capped by 10 slots)
    - will exist for the relevant SW workload horizon
    """
    if farm is not None and hasattr(farm, "hands"):
        h = farm.hands
        current_hands = len(h) if isinstance(h, (list, tuple)) else 0
    else:
        current_hands = 0

    if money is None:
        raw_m = getattr(farm, "money", 0.0) if farm is not None else 0.0
        try:
            money = float(raw_m)
        except Exception:
            money = 0.0

    guaranteed_incoming_hands = 0
    if hour <= 1:
        raw_hires = getattr(farm, "hires_today", 0) if farm is not None else 0
        try:
            hires_today = int(raw_hires)
        except Exception:
            hires_today = 0

        target_hands = get_target_hands(day)
        hires_needed = max(0, target_hands - max(hires_today, current_hands))

        accum_cost = 0.0
        for i in range(min(hires_needed, 10)):
            hire_idx = hires_today + i
            cost = float(_fib(hire_idx))
            if accum_cost + cost <= money:
                accum_cost += cost
                guaranteed_incoming_hands += 1
            else:
                break

    return 1 + current_hands + guaranteed_incoming_hands


# ---------------------------------------------------------------------------
# 1. Effective Workforce Capacity
# ---------------------------------------------------------------------------
def compute_daily_labor_capacity(
    day: int,
    safety_margin: float = 0.15,
    farm: Any = None,
    money: Optional[float] = None,
    hour: int = 0,
) -> Dict[str, Any]:
    """Compute authoritative daily labor capacity from scheduled workforce.

    Uses EFFECTIVE_ACTIONS_PER_UNIT = 12 from config as the empirical foundation.
    Safety reserve (default 15%) accounts for unexpected weed clearing, clustered harvests,
    and emergency pathing detours.
    """
    planned_hands = get_target_hands(day)
    if farm is not None:
        worker_count = compute_projected_workers(farm, day, money=money, hour=hour)
    else:
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
def compute_existing_workload(farm: Any, day: int, include_animal_feeding: bool = True) -> Dict[str, Any]:
    """Compute existing workload committed on established NW and NE tiles.

    Directly applies the same predicates as task_scheduler.py:
    - Survival watering (consecutive_unwatered >= 1 or newly planted)
    - Bonus / regular watering (in_bonus_window or needs_water_today)
    - Harvests (turns_until_decay <= 4, mature max yield, or accumulated ongoing yield >= 2)
    - Animal care (feeding and product collection)

    When include_animal_feeding is False, animal feeding is omitted so that
    survival_reserved_ap can handle all feeding and wheat staging without double-counting.
    """
    nw_ops = 0.0
    ne_ops = 0.0
    survival_water_count = 0
    regular_water_count = 0
    harvest_count = 0
    animal_ops = 0.0

    if farm is None or not hasattr(farm, "iter_tiles"):
        return {
            "nw_workload": 0.0,
            "ne_workload": 0.0,
            "total_existing_workload": 0.0,
            "survival_water_count": 0,
            "regular_water_count": 0,
            "harvest_count": 0,
            "animal_ops": 0.0,
        }

    for t in farm.iter_tiles():
        pos = _t_pos(t)
        q = farm.quadrant_of(pos) if hasattr(farm, "quadrant_of") else "NW"
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
            if not fed and include_animal_feeding:
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
# 2b. Spatial Animal Survival-Feasibility Reservation
# ---------------------------------------------------------------------------
def compute_survival_feasibility_reservation(
    farm: Any,
    day: int,
    hour: int = 0,
    worker_positions: Optional[Dict[int, Tuple[int, int]]] = None,
    worker_count: int = 1,
    private: Any = None,
    horizon_days: float = 2.0,
) -> Dict[str, Any]:
    """Calculate the minimum worker-action budget required to guarantee all survival-critical animal tasks.

    Includes:
    - current animal position
    - eligible feeding position / structure tile
    - nearest feasible worker
    - worker current position
    - Manhattan travel cost
    - pickup/staging cost if wheat must be collected
    - FEED execution cost
    - remaining turns before end-of-day

    Checks spatial deadline feasibility: can at least one worker physically reach and execute
    each survival task before midnight (hour = 24)?
    """
    if farm is None or not hasattr(farm, "iter_tiles"):
        return {
            "survival_reserved_ap": 0.0,
            "is_deadline_feasible": True,
            "rejection_reason": None,
            "blocking_animal_pos": None,
            "unfed_count": 0,
            "total_animals": 0,
            "min_slack_turns": 24,
            "details": {},
        }

    from config import SHED_ACCESS_TILES
    shed_tiles = list(SHED_ACCESS_TILES) if SHED_ACCESS_TILES else [(4, 4), (5, 4), (4, 5), (5, 5)]

    # Collect all live animals and identify which require feed today
    all_live_animals = []
    unfed_animals = []
    for t in farm.iter_tiles():
        is_animal = bool(_t_field(t, "is_animal", False) or _t_field(t, "kind") == "ANIMAL")
        is_structure = _t_field(t, "kind") in ("PASTURE", "COOP")
        if is_animal or (is_structure and _t_field(t, "animal")):
            all_live_animals.append(t)
            if not bool(_t_field(t, "fed_today", False)):
                unfed_animals.append(t)

    total_animals = len(all_live_animals)
    unfed_count = len(unfed_animals)

    if total_animals == 0:
        return {
            "survival_reserved_ap": 0.0,
            "is_deadline_feasible": True,
            "rejection_reason": None,
            "blocking_animal_pos": None,
            "unfed_count": 0,
            "total_animals": 0,
            "min_slack_turns": 24,
            "details": {},
        }

    # Ensure worker positions is complete up to worker_count
    w_positions = dict(worker_positions) if worker_positions else {}
    if 0 not in w_positions:
        w_positions[0] = tuple(getattr(farm, "farmer", (4, 4)))
    if hasattr(farm, "hands"):
        for i, h in enumerate(farm.hands):
            if (i + 1) not in w_positions:
                w_positions[i + 1] = tuple(h)
    for extra_idx in range(len(w_positions), worker_count):
        w_positions[extra_idx] = SHED_POS  # Real spawn location for incoming morning hands

    # Check which workers currently hold wheat in their personal inventory
    workers_with_wheat = set()
    if private is not None:
        invs = getattr(private, "inventories", None) or (private.get("inventories") if isinstance(private, dict) else None)
        if invs:
            for u in range(len(w_positions)):
                if u < len(invs):
                    inv = invs[u]
                    w_amt = inv.get("WHEAT", 0) if isinstance(inv, dict) else getattr(inv, "wheat", 0)
                    if int(w_amt) > 0:
                        workers_with_wheat.add(u)

    turns_left = max(0, 24 - hour)
    is_deadline_feasible = True
    blocking_animal_pos = None
    min_slack_turns = turns_left
    per_animal_details = {}

    for a in unfed_animals:
        a_pos = _t_pos(a)
        consec_unfed = int(_t_field(a, "consecutive_unfed", 0))

        # Find minimum turn cost for any worker to feed this animal
        best_cost = 999
        best_w = None

        for u, w_pos in w_positions.items():
            if u in workers_with_wheat:
                # Worker already holds wheat -> direct travel to animal + FEED
                transit = abs(w_pos[0] - a_pos[0]) + abs(w_pos[1] - a_pos[1])
                cost = transit + 1
            else:
                # Worker must visit shed, PICKUP wheat, walk to animal, FEED
                to_shed = min(abs(w_pos[0] - s[0]) + abs(w_pos[1] - s[1]) for s in shed_tiles)
                shed_to_a = min(abs(s[0] - a_pos[0]) + abs(s[1] - a_pos[1]) for s in shed_tiles)
                cost = to_shed + 1 + shed_to_a + 1

            if cost < best_cost:
                best_cost = cost
                best_w = u

        slack = turns_left - best_cost
        if slack < min_slack_turns:
            min_slack_turns = slack

        per_animal_details[a_pos] = {
            "best_worker": best_w,
            "cost": best_cost,
            "slack": slack,
            "consecutive_unfed": consec_unfed,
        }

        # Spatial deadline feasibility check:
        # If animal cannot be reached and fed before midnight by ANY worker:
        if best_cost > turns_left:
            is_deadline_feasible = False
            blocking_animal_pos = a_pos

    # Calculate survival AP reservation
    # 1. Today's feeding actions + travel + pickup staging
    if unfed_count > 0:
        pickup_batches = math.ceil(unfed_count / 3.0)
        avg_shed_dist = sum(
            min(abs(w[0] - s[0]) + abs(w[1] - s[1]) for s in shed_tiles)
            for w in w_positions.values()
        ) / max(1, len(w_positions))
        avg_pasture_dist = sum(
            min(abs(s[0] - _t_pos(a)[0]) + abs(s[1] - _t_pos(a)[1]) for s in shed_tiles)
            for a in unfed_animals
        ) / unfed_count

        feed_turns_today = (
            unfed_count * 1.0
            + (unfed_count - 1) * 1.0
            + pickup_batches * (avg_shed_dist + 1.0 + avg_pasture_dist)
        )
    else:
        feed_turns_today = 0.0

    # 2. Tomorrow's feeding actions over horizon for all live animals
    if total_animals > 0 and horizon_days > 1.0:
        t_batches = math.ceil(total_animals / 3.0)
        feed_turns_tomorrow = (
            total_animals * 1.0
            + (total_animals - 1) * 1.0
            + t_batches * 5.0
        ) * (horizon_days - 1.0)
    else:
        feed_turns_tomorrow = 0.0

    survival_reserved_ap = round((feed_turns_today + feed_turns_tomorrow) / 2.0, 1)

    rejection_reason = None
    if not is_deadline_feasible:
        rejection_reason = "ANIMAL_SURVIVAL_SPATIAL_RISK"

    return {
        "survival_reserved_ap": survival_reserved_ap,
        "is_deadline_feasible": is_deadline_feasible,
        "rejection_reason": rejection_reason,
        "blocking_animal_pos": blocking_animal_pos,
        "unfed_count": unfed_count,
        "total_animals": total_animals,
        "min_slack_turns": min_slack_turns,
        "details": per_animal_details,
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
    sorted_tiles = get_sorted_sw_soil_tiles()
    if k_tiles > len(sorted_tiles):
        all_sw = sorted(
            [(x, y) for x in range(5) for y in range(5, 10) if (x, y) != (4, 5)],
            key=lambda p: abs(p[0] - SHED_POS[0]) + abs(p[1] - SHED_POS[1])
        )
        sorted_tiles = all_sw[:k_tiles]
    else:
        sorted_tiles = sorted_tiles[:k_tiles]

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
    hour: int = 0,
    allow_hypothetical: bool = False,
    reserve_desired_herd: bool = True,
    responsive_scheduler_capacity: bool = False,
) -> Tuple[bool, int, Dict[str, Any]]:
    """Evaluate whether buying and partially exploiting SW generates positive net marginal EV.

    Evaluates discrete candidate soil tile counts k in {5, 10, 15}.
    Returns:
      (is_serviceable, best_k, diagnostic_dict)
    """
    if target_quadrant != 3:
        return True, 0, {"reason": "not_sw"}

    # 1. Capacity and post-unlock zonal squad partition
    cap = compute_daily_labor_capacity(current_day, farm=farm, money=money, hour=hour)
    worker_count = cap["worker_count"]

    try:
        from config import DYNAMIC_ZONAL_ALLOCATION as _cfg_dyn, STRATEGIC_SW_OWNERSHIP_ENABLED as _cfg_strat
        use_strat_sw = bool(_cfg_strat)
        use_dynamic = bool(_cfg_dyn) or use_strat_sw or bool(responsive_scheduler_capacity)
    except Exception:
        use_dynamic = DYNAMIC_ZONAL_ALLOCATION
        use_strat_sw = False

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
    # If livestock strategy is active (cows in NW, NE unlocked with active cultivation), project active target sheep
    try:
        from config import get_active_livestock_targets
        _, _, active_target_sheep = get_active_livestock_targets()
    except Exception:
        active_target_sheep = TARGET_SHEEP

    # P1 isolates the SW PURCHASE decision from aspirational livestock targets.
    # Preserve the observed livestock + built-housing count conservatively:
    # only the extra desired-but-not-yet-committed herd projection is removable.
    # Default True reproduces the existing activation/feed caller semantics.
    target_sheep = ne_animals
    if reserve_desired_herd:
        if not use_strat_sw:
            if nw_animals > 0 and len(getattr(farm, "unlocked", [])) >= 2 and (ne_crops > 0 or ne_animals > 0):
                target_sheep = max(ne_animals, active_target_sheep)
        else:
            target_sheep = min(ne_animals + 1, active_target_sheep)

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
        # Dynamic units committed to NW and NE.
        # P1.2 uses the responsive scheduler's surplus-capacity idea while
        # preserving the serviceability model's 15% safety reserve. This
        # override is opt-in and therefore does not change existing dynamic
        # allocation, purchase-gate, activation, or feed callers.
        eff_ap = float(EFFECTIVE_ACTIONS_PER_UNIT)
        usable_per_unit = eff_ap * 0.85
        if responsive_scheduler_capacity:
            nw_mand_units = math.ceil(nw_committed / usable_per_unit) if nw_committed > 0 else 0
            ne_mand_units = math.ceil(ne_committed / usable_per_unit) if ne_committed > 0 else 0
        else:
            nw_mand_units = math.ceil(nw_committed / eff_ap)
            ne_mand_units = math.ceil(ne_committed / eff_ap)
        nw_cap = round(nw_mand_units * usable_per_unit, 1)
        ne_cap = round(ne_mand_units * usable_per_unit, 1)
        nw_deficit = max(0.0, nw_committed - nw_cap)
        ne_deficit = max(0.0, ne_committed - ne_cap)
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
    if active_force_k is not None:
        candidates = [active_force_k]
    elif use_strat_sw:
        candidates = [0, 3, 5, 8, 10, 15, 18, 21, 24]
    else:
        candidates = [5, 10, 15, 18, 21, 24]
    evaluations = []

    for k in candidates:
        if k == 0:
            evaluations.append({
                "k_tiles": 0,
                "k_serviceable": 0,
                "serviceability_fraction": 1.0,
                "req_actions": 0.0,
                "sw_travel_burden": 0.0,
                "realizable_gross_rev": 0.0,
                "realizable_seed_spend": 0.0,
                "sw_labor_cost": 0.0,
                "opportunity_cost_nw_ne": 0.0,
                "net_marginal_profit": -land_price,
                "serv_adjusted_roi": -1.0,
                "payback_surplus": 0.0,
                "sw_squad": 0,
                "sw_cap": 0.0,
            })
            continue

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
        try:
            from config import DYNAMIC_SW_CROPS_ENABLED
            use_dyn_crops = bool(DYNAMIC_SW_CROPS_ENABLED)
        except Exception:
            use_dyn_crops = False

        if use_dyn_crops and (forecast is None or not hasattr(forecast, "expected_price")):
            try:
                from strategy.price_forecast import PriceForecast
                forecast = PriceForecast.load()
            except Exception:
                pass

        if not use_dyn_crops or forecast is None or not hasattr(forecast, "expected_price"):
            # Baseline fast cash crop: Carrot (cycle = 3 days, seed = $20, revenue ≈ 4 * $35 = $140, profit ≈ $120/cycle)
            cycles = max(0, days_remaining // 3)
            nominal_gross_rev = k * cycles * 140.0
            nominal_seed_spend = k * cycles * 20.0

            # Realizable revenue based on fully serviceable tile count
            realizable_gross_rev = k_serviceable * cycles * 140.0
            realizable_seed_spend = k_serviceable * cycles * 20.0
        else:
            # Dynamic Authoritative Crop Scoring using _crop_score()
            try:
                from strategy.macro_planner import _crop_score, _crop_allowed_today
                from strategy.baked_economics import CROP_ECONOMICS
            except ImportError:
                from macro_planner import _crop_score, _crop_allowed_today
                from baked_economics import CROP_ECONOMICS

            n_animals = nw_animals + target_sheep
            wheat_have = 0
            if farm is not None and hasattr(farm, "inventory"):
                inv = getattr(farm, "inventory")
                if isinstance(inv, dict):
                    inv_w = inv.get("WHEAT", 0)
                    wheat_have = inv_w.get("count", 0) if isinstance(inv_w, dict) else int(inv_w)

            days_left = max(1, 29 - current_day + 1)
            feed_need = n_animals * days_left
            unavoidable_shortfall = max(0, feed_need - wheat_have)

            best_crop_gross = 0.0
            best_crop_spend = 0.0
            best_crop_net = -1e9

            candidate_crops = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
            for crop in candidate_crops:
                if not _crop_allowed_today(crop, current_day):
                    continue
                per_day, details = _crop_score(
                    crop=crop,
                    day=current_day,
                    forecast=forecast,
                    boosts={},
                    own_tiles=nw_crops + ne_crops,
                    feed_wheat_per_day=n_animals,
                    n_animals=n_animals,
                )
                if per_day <= -1e8:
                    continue

                eff_prices = details.get("eff_prices", {})
                num_harvests = len(eff_prices)
                cd = CROPS[crop]
                econ = CROP_ECONOMICS[crop]
                fert_apps = econ.get("apps", 0)
                fert_cost = 25.0
                c_cycles = num_harvests if not cd["ongoing"] else (1 if num_harvests > 0 else 0)
                c_spend = c_cycles * (cd["seed"] + fert_apps * fert_cost)
                c_net_base = per_day * max(1, 30 - current_day)
                c_gross = c_net_base + c_spend

                if crop == "WHEAT":
                    wheat_yield = 4 * c_cycles
                    feed_units = min(wheat_yield, unavoidable_shortfall)
                    sale_units = max(0, wheat_yield - feed_units)
                    feed_val = feed_units * 30.0
                    eff_p = list(eff_prices.values())
                    sale_price = eff_p[0] if eff_p else 25.0
                    sale_val = sale_units * sale_price
                    c_gross = feed_val + sale_val
                    c_spend = c_cycles * cd["seed"]
                    c_net_base = c_gross - c_spend

                if c_net_base > best_crop_net:
                    best_crop_net = c_net_base
                    best_crop_gross = c_gross
                    best_crop_spend = c_spend

            nominal_gross_rev = round(k * best_crop_gross, 1)
            nominal_seed_spend = round(k * best_crop_spend, 1)
            realizable_gross_rev = round(k_serviceable * best_crop_gross, 1)
            realizable_seed_spend = round(k_serviceable * best_crop_spend, 1)

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
    min_serv_k = 0 if use_strat_sw else (2 if use_dynamic else 5)
    min_serv_frac = 0.70 if use_strat_sw else (0.80 if use_dynamic else 0.85)
    zero_displacement = [
        e for e in evaluations
        if e["opportunity_cost_nw_ne"] <= 0.0 and e["serviceability_fraction"] >= min_serv_frac and e["k_serviceable"] >= min_serv_k
    ]

    if zero_displacement:
        zero_displacement.sort(key=lambda x: x["net_marginal_profit"], reverse=True)
        best_eval = zero_displacement[0]
        if best_eval["net_marginal_profit"] > 0 and best_eval["payback_surplus"] > 0:
            is_serviceable = True
        elif use_strat_sw:
            is_serviceable = True
        else:
            is_serviceable = False
    else:
        # None can be serviced without displacing NW/NE work
        evaluations.sort(key=lambda x: x["net_marginal_profit"], reverse=True)
        best_eval = evaluations[0]
        is_serviceable = False

    best_k = best_eval["k_tiles"]

    try:
        from config import SW_ACTIVATION_MODE as _cfg_act_mode
    except Exception:
        _cfg_act_mode = "production"

    if _cfg_act_mode == "progressive":
        # Check progressive activation directly on candidate SW empty tiles
        prog_tiles, pdiag = compute_progressive_sw_activation(
            farm=farm,
            day=current_day,
            money=money,
            hour=hour,
            allow_hypothetical=True,
        )
        if len(prog_tiles) >= 2:
            is_serviceable = True
            best_k = max(best_k, len(prog_tiles))

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
        "ne_observed_animals_and_housing": ne_animals,
        "ne_desired_sheep_target": active_target_sheep,
        "ne_reserved_sheep_workload_count": target_sheep,
        "nw_committed_workload": nw_committed,
        "ne_committed_workload": ne_committed,
        "reserve_desired_herd": bool(reserve_desired_herd),
        "responsive_scheduler_capacity": bool(responsive_scheduler_capacity),
        "core_required_units": int(
            (math.ceil(nw_committed / (float(EFFECTIVE_ACTIONS_PER_UNIT) * 0.85)) if responsive_scheduler_capacity and nw_committed > 0 else 0)
            + (math.ceil(ne_committed / (float(EFFECTIVE_ACTIONS_PER_UNIT) * 0.85)) if responsive_scheduler_capacity and ne_committed > 0 else 0)
        ) if responsive_scheduler_capacity else None,
        "surplus_units_for_sw": int(surplus_units) if use_dynamic else 0,
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


# ---------------------------------------------------------------------------
# 5. Progressive Workload-Aware SW Activation Controller
# ---------------------------------------------------------------------------

def compute_progressive_sw_activation(
    farm,
    day: int,
    money: float,
    worker_positions: Optional[Dict[int, Tuple[int, int]]] = None,
    crop_eval_func = None,
    horizon_turns: int = 48,
    safety_margin_fraction: float = 0.15,
    hour: int = 0,
    allow_hypothetical: bool = False,
    private: Any = None,
    seeds_owned: Optional[Dict[str, int]] = None,
) -> Tuple[List[Tuple[int, int]], Dict[str, Any]]:
    """Determine the number of additional SW tiles to activate dynamically.

    Evaluates candidate activation over a short workload horizon (24–72 turns):
      IncrementalDemand(crop, tile) = Plant + Water_{0..H} + Harvest_{0..H} + ExpectedTravel
    Only activates while:
      MandatoryDemand_{NW+NE} + CommittedDemand_{SW} + SurvivalReservedAP + IncrementalDemand <= AvailableCapacity - SafetyMargin

    Rejection reasons logged per tile:
      - NO_LABOR
      - NO_POSITIVE_CROP
      - TRAVEL_TOO_HIGH
      - TREASURY
      - MANDATORY_NW_NE_DEBT
      - ACTIVATION_SAFETY_MARGIN
      - ANIMAL_SURVIVAL_SPATIAL_RISK
    """
    if hasattr(farm, "unlocked") and "SW" not in farm.unlocked and not allow_hypothetical:
        return [], {"reason": "sw_not_unlocked", "accepted_count": 0, "rejections": {}}

    # 1. Identify all currently eligible empty SW production tiles (grid-driven, no artificial ceilings)
    empty_sw_tiles = []
    existing_active_sw_plants = 0
    existing_active_sw_animals = 0
    sw_plant_daily_water = 0
    sw_plant_harvests = 0

    if hasattr(farm, "iter_tiles") and hasattr(farm, "quadrant_of"):
        for t in farm.iter_tiles():
            pos = _t_pos(t)
            if farm.quadrant_of(pos) != "SW":
                continue
            if pos == PORT_SW:
                continue

            is_plant = bool(_t_field(t, "is_plant", False) or _t_field(t, "kind") == "PLANT")
            is_animal = bool(_t_field(t, "is_animal", False) or _t_field(t, "kind") == "ANIMAL")
            is_structure = _t_field(t, "kind") in ("PASTURE", "COOP", "SHED")
            is_empty = _t_field(t, "kind") == "EMPTY" and not is_plant and not is_animal and not is_structure

            if is_empty:
                empty_sw_tiles.append(pos)
            elif is_plant:
                existing_active_sw_plants += 1
                if not bool(_t_field(t, "watered_today", False)):
                    sw_plant_daily_water += 1
                if int(_t_field(t, "yield_units", 0)) > 0:
                    sw_plant_harvests += 1
            elif is_animal or is_structure:
                existing_active_sw_animals += 1

    # Sort empty SW tiles by proximity to shed (4, 4)
    eligible_tiles = sorted(
        empty_sw_tiles,
        key=lambda p: abs(p[0] - SHED_POS[0]) + abs(p[1] - SHED_POS[1])
    )

    existing_active_sw = existing_active_sw_plants + existing_active_sw_animals
    horizon_days = max(1.0, float(horizon_turns) / 24.0)

    # Worker positions for spatial travel delta & survival reservation
    w_positions = dict(worker_positions) if worker_positions else {}
    if 0 not in w_positions:
        w_positions[0] = tuple(getattr(farm, "farmer", (4, 4)))
    if hasattr(farm, "hands"):
        for i, h in enumerate(farm.hands):
            if (i + 1) not in w_positions:
                w_positions[i + 1] = tuple(h)

    # 3. Available labor capacity over horizon using projected workers (Fix 1)
    worker_count = compute_projected_workers(farm, day, money=money, hour=hour)
    for extra_idx in range(len(w_positions), worker_count):
        w_positions[extra_idx] = SHED_POS

    raw_capacity = round(worker_count * EFFECTIVE_ACTIONS_PER_UNIT * horizon_days, 1)
    safety_margin = round(raw_capacity * safety_margin_fraction, 1)
    usable_capacity = max(0.0, raw_capacity - safety_margin)

    # 3b. Spatial Animal Survival-Feasibility Reservation
    survival_diag = compute_survival_feasibility_reservation(
        farm=farm,
        day=day,
        hour=hour,
        worker_positions=w_positions,
        worker_count=worker_count,
        private=private,
        horizon_days=horizon_days,
    )
    survival_reserved_ap = survival_diag["survival_reserved_ap"]

    # 2. Existing mandatory NW / NE workload (strictly omitting animal feeding to avoid double-counting)
    workload = compute_existing_workload(farm, day, include_animal_feeding=False)
    nw_wl = workload["nw_workload"]
    ne_wl = workload["ne_workload"]
    mandatory_nw_ne = round((nw_wl + ne_wl) * horizon_days, 1)

    # Committed SW maintenance over horizon (daily watering + mature harvests)
    committed_sw_wl = round(
        (existing_active_sw_plants * horizon_days + sw_plant_harvests + existing_active_sw_animals * horizon_days),
        1
    )

    # Surplus effective actions available for new SW activation
    surplus_capacity = round(usable_capacity - survival_reserved_ap - mandatory_nw_ne - committed_sw_wl, 1)

    # 4. Progressive activation evaluation per eligible empty tile
    accepted_tiles: List[Tuple[int, int]] = []
    rejections: Dict[Tuple[int, int], str] = {}
    rejection_counts: Dict[str, int] = {
        "NO_LABOR": 0,
        "NO_POSITIVE_CROP": 0,
        "TRAVEL_TOO_HIGH": 0,
        "TREASURY": 0,
        "MANDATORY_NW_NE_DEBT": 0,
        "ACTIVATION_SAFETY_MARGIN": 0,
        "ANIMAL_SURVIVAL_SPATIAL_RISK": 0,
    }

    # Spatial deadline risk check: If any animal cannot be reached and fed before midnight:
    if not survival_diag["is_deadline_feasible"]:
        for p in eligible_tiles:
            rejections[p] = "ANIMAL_SURVIVAL_SPATIAL_RISK"
            rejection_counts["ANIMAL_SURVIVAL_SPATIAL_RISK"] += 1
        return [], {
            "eligible_count": len(eligible_tiles),
            "accepted_count": 0,
            "current_executable_k": 0,
            "existing_active_sw": existing_active_sw,
            "total_active_target": existing_active_sw,
            "surplus_capacity": surplus_capacity,
            "survival_reserved_ap": survival_reserved_ap,
            "survival_diag": survival_diag,
            "reason": "ANIMAL_SURVIVAL_SPATIAL_RISK",
            "rejections": rejections,
            "rejection_counts": rejection_counts,
        }

    # Insufficient surplus capacity check:
    if surplus_capacity <= 0:
        rej_code = "ANIMAL_SURVIVAL_SPATIAL_RISK" if (survival_reserved_ap > 0 and (usable_capacity - mandatory_nw_ne - committed_sw_wl > 0)) else "MANDATORY_NW_NE_DEBT"
        for p in eligible_tiles:
            rejections[p] = rej_code
            rejection_counts[rej_code] += 1
        return [], {
            "eligible_count": len(eligible_tiles),
            "accepted_count": 0,
            "current_executable_k": 0,
            "existing_active_sw": existing_active_sw,
            "total_active_target": existing_active_sw,
            "surplus_capacity": surplus_capacity,
            "survival_reserved_ap": survival_reserved_ap,
            "survival_diag": survival_diag,
            "reason": rej_code,
            "rejections": rejections,
            "rejection_counts": rejection_counts,
        }

    # Usable owned seed ledger: initialized from passed working seeds, farm.seeds, or private.seeds
    if seeds_owned is None:
        if hasattr(farm, "seeds") and isinstance(farm.seeds, dict):
            seeds_owned = farm.seeds
        elif hasattr(farm, "private") and hasattr(farm.private, "seeds") and isinstance(farm.private.seeds, dict):
            seeds_owned = farm.private.seeds
        elif private is not None and hasattr(private, "seeds") and isinstance(private.seeds, dict):
            seeds_owned = private.seeds

    usable_seeds = {k: int(v) for k, v in (seeds_owned or {}).items()}

    running_surplus = surplus_capacity
    # Money passed is already spendable discretionary cash (do not double-deduct SW_SAFETY_RESERVE)
    running_seed_money = max(0.0, float(money))

    for tile_pos in eligible_tiles:
        # A. Authoritative crop evaluation (Single Source of Truth)
        best_crop = "WHEAT"
        crop_ev = 0.0
        seed_cost = 10.0
        if crop_eval_func is not None:
            try:
                best_crop, crop_ev, seed_cost = crop_eval_func(tile_pos, day)
            except Exception:
                best_crop = "WHEAT"
                crop_ev = 0.0
                seed_cost = 10.0
        else:
            try:
                from strategy.macro_planner import evaluate_dynamic_sw_crop_choice
                best_crop, crop_ev = evaluate_dynamic_sw_crop_choice(
                    day=day,
                    wheat_have=0,
                    n_animals=0,
                    forecast=getattr(farm, "forecast", None),
                    boosts={},
                    committed_counts={},
                    return_ev=True,
                )
                seed_cost = CROPS.get(best_crop, {}).get("seed", 10.0) if best_crop else 10.0
            except Exception:
                crop_ev = 0.0
            if crop_ev <= 0 and day <= 25:
                # Real conservative fallback for wheat on Day <= 25:
                # 4 units * $25 base price - $10 seed - SW labor penalty (~2 actions * $1 * days_left)
                days_left = max(1, 30 - day)
                labor_pen = 2.0 * days_left
                est_ev = 4.0 * 25.0 - 10.0 - labor_pen
                if est_ev > 0:
                    best_crop = "WHEAT"
                    crop_ev = est_ev
                    seed_cost = 10.0

        if crop_ev <= 0 or best_crop is None:
            rejections[tile_pos] = "NO_POSITIVE_CROP"
            rejection_counts["NO_POSITIVE_CROP"] += 1
            continue

        # B. Treasury check for seed cost, crediting owned seed inventory
        have_seed = usable_seeds.get(best_crop, 0)
        if have_seed > 0:
            cash_for_seed = 0.0
        else:
            cash_for_seed = seed_cost

        if running_seed_money < cash_for_seed:
            rejections[tile_pos] = "TREASURY"
            rejection_counts["TREASURY"] += 1
            continue

        # C. Spatial travel overhead using actual worker positions
        min_worker_dist = min(
            abs(w_pos[0] - tile_pos[0]) + abs(w_pos[1] - tile_pos[1])
            for w_pos in w_positions.values()
        )
        travel_overhead = round(min_worker_dist / 3.0, 2)
        if travel_overhead > 4.5:
            rejections[tile_pos] = "TRAVEL_TOO_HIGH"
            rejection_counts["TRAVEL_TOO_HIGH"] += 1
            continue

        # D. Workload over horizon:
        # Plant (1.0) + Same-day water (1.0) + Daily watering over horizon + Harvest if due
        watering_ops = 1.0 + max(0.0, horizon_days - 1.0) * 1.0
        cd = CROPS.get(best_crop, {})
        matures_in = cd.get("first_yield_day", cd.get("max_yield_day", 4))
        harvest_ops = 1.0 if matures_in <= horizon_days else 0.0

        incremental_demand = round(1.0 + watering_ops + harvest_ops + travel_overhead, 2)

        # E. Capacity check
        if incremental_demand > running_surplus:
            if running_surplus < 1.5:
                rejections[tile_pos] = "NO_LABOR"
                rejection_counts["NO_LABOR"] += 1
            else:
                rejections[tile_pos] = "ACTIVATION_SAFETY_MARGIN"
                rejection_counts["ACTIVATION_SAFETY_MARGIN"] += 1
            continue

        # Tile accepted!
        accepted_tiles.append(tile_pos)
        running_surplus -= incremental_demand
        if have_seed > 0:
            usable_seeds[best_crop] = have_seed - 1
        else:
            running_seed_money -= cash_for_seed

    diag = {
        "eligible_count": len(eligible_tiles),
        "accepted_count": len(accepted_tiles),
        "current_executable_k": len(accepted_tiles),
        "existing_active_sw": existing_active_sw,
        "total_active_target": existing_active_sw + len(accepted_tiles),
        "surplus_capacity": surplus_capacity,
        "remaining_surplus": round(running_surplus, 1),
        "rejections": rejections,
        "rejection_counts": rejection_counts,
    }
    return accepted_tiles, diag

