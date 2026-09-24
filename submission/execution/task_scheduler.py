"""Per-turn prioritized task construction + greedy distance assignment.

v5.9: Action-budget allocator with utilization tracking.

Engine facts encoded here:
  - One action per unit per turn; moves and ops are mutually exclusive.
  - HANDS HIRED THIS TURN CANNOT ACT THIS TURN: interpreter applies unit
    actions BEFORE _process_market() (where HIRE appends to farm["hands"]),
    so a just-hired hand's position lookup returns None and its action is
    dropped. Hands first act on turn T+1. Scheduling therefore dispatches to
    currently-observed hands only; new hires join the roster next turn.
  - Seeds bought this turn are likewise only PLANTable next turn (same
    farm-before-market ordering).
  - A plant with consecutive_unwatered == 1 dies at end-of-day unless watered
    TODAY (urgent survival).
  - One-time crops start decaying the day after max_yield_day -> harvest on
    max_yield_day morning at the latest.
  - Animals produce during end-of-day refresh when (day+1 - placed -
    first_yield_day) % interval == 0; feeding must be done BEFORE that refresh,
    and an unfed production day wipes the banked care bonus.
  - fertilizer_available flips True at end-of-day; collect it any time next day.
"""
import math
import copy
from config import (
    ANIMAL_LIST,
    ANIMALS,
    CARE_GEESE,
    CROPS,
    PRODUCTS,
    PRIORITY_BONUS_WATER,
    PRIORITY_BUILD_STRUCTURE,
    PRIORITY_CARE_ANIMAL,
    PRIORITY_DECAY_HARVEST,
    PRIORITY_FEED_STAGING,
    PRIORITY_FERT_COLLECT,
    PRIORITY_FERTILIZE_CROP,
    PRIORITY_PLACE_ANIMAL,
    PRIORITY_PLANT_AND_WATER,
    PRIORITY_PROD_DAY_FEED,
    PRIORITY_STANDARD_HARVEST,
    PRIORITY_PRODUCT_DELIVERY,
    PRIORITY_PRODUCT_DELIVERY_PRESSURE,
    PRIORITY_ENDGAME_PRODUCT_DELIVERY,
    PRIORITY_URGENT_SURVIVAL,
    PRIORITY_WEED_DIG,
    PORT_SW,
    SHED_ACCESS_TILES,
    SHED_CAPACITY,
    SHED_SOFT_CAP,
    TURNS_PER_DAY,
    EFFECTIVE_ACTIONS_PER_UNIT,
    DYNAMIC_ZONAL_ALLOCATION,
    SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED,
    PERSISTENT_WORKER_LOCALITY_ENABLED,
    LOCALITY_ZONE_SWITCH_PENALTY,
    C2_MAX_SPILLOVER_DIST,
    C2_SPILLOVER_PRIORITY_FLOOR,
    C6_CLUSTER_RADIUS,
    C6_CLUSTER_BONUS,
    C6_PRIORITY_BAND,
    C6_TRAVEL_WEIGHT,
    log,
)
try:
    from state.observation_parser import crop_age, in_bonus_window, needs_water_today, turns_until_decay, crop_produces_today
except ImportError:
    from observation_parser import crop_age, in_bonus_window, needs_water_today, turns_until_decay, crop_produces_today
try:
    from execution.pathfinding import bfs_first_step
except ImportError:
    from pathfinding import bfs_first_step


# v5.9: Daily utilization tracking (accumulated across all 24 hours of each day)
_daily_log = {}
_daily_accum = {}
_ACTIVE_MISSIONS = {}
_BLOCKED_TASK_TRACKER = {}

def get_daily_log():
    """Return the utilization log for the current episode."""
    return _daily_log

def get_active_missions():
    """Return copy of currently active sticky missions."""
    return dict(_ACTIVE_MISSIONS)

def reset_sticky_missions():
    """Reset active sticky missions."""
    global _ACTIVE_MISSIONS
    _ACTIVE_MISSIONS = {}

def get_blocked_task_tracker():
    """Return copy of active blocked task tracker."""
    return dict(_BLOCKED_TASK_TRACKER)

def reset_blocked_task_tracker():
    """Reset blocked task tracker."""
    global _BLOCKED_TASK_TRACKER
    _BLOCKED_TASK_TRACKER = {}

# Persistent Worker Locality State (Layer 1: Zone capacity across days, Layer 2: Worker roles within day)
_ZONE_HOME_CAPACITY = {"NW": 1, "NE": 0, "SW": 0}
_WORKER_HOME_STATE = {}           # unit_idx -> home_quadrant
_LOCALITY_DAY = -1               # current day for detecting day boundaries
_LOCALITY_WORKER_METRICS = {}    # unit_idx -> metrics dict for today
_LOCALITY_DAILY_LOG = {}         # day -> aggregated metrics dict
_LOCALITY_RAW_RECORDS = []       # list of per-worker per-day dicts for replay analysis
_LOCALITY_PREV_POS = {}          # unit_idx -> (x, y) for distance tracking
_LOCALITY_LAST_FIELD_QUAD = {}   # unit_idx -> last non-shed field quadrant ("NW", "NE", "SW", "SE")
_LOCALITY_SEASON_SUMMARY = {
    "total_within_day_reassignments": 0,
    "total_ne_sw_home_changes": 0,
    "total_physical_ne_sw_traversals": 0,
    "total_temporary_spillovers": 0,
    "total_emergency_preemptions": 0,
    "total_travel_distance": 0,
    "total_moves": 0,
    "total_ops": 0,
}

def get_worker_home_state():
    """Return copy of currently assigned worker home quadrants."""
    return dict(_WORKER_HOME_STATE)

def get_zone_home_capacity():
    """Return copy of current persistent zone workforce capacity."""
    return dict(_ZONE_HOME_CAPACITY)

def get_locality_telemetry():
    """Return copy of locality telemetry daily log, summary, and state."""
    return {
        "daily_log": copy.deepcopy(_LOCALITY_DAILY_LOG),
        "raw_records": list(_LOCALITY_RAW_RECORDS),
        "summary": dict(_LOCALITY_SEASON_SUMMARY),
        "worker_state": dict(_WORKER_HOME_STATE),
        "zone_capacity": dict(_ZONE_HOME_CAPACITY),
    }

def reset_worker_locality():
    """Reset persistent worker home locality state at start of new episode."""
    global _ZONE_HOME_CAPACITY, _WORKER_HOME_STATE, _LOCALITY_DAY
    global _LOCALITY_WORKER_METRICS, _LOCALITY_DAILY_LOG, _LOCALITY_RAW_RECORDS
    global _LOCALITY_PREV_POS, _LOCALITY_LAST_FIELD_QUAD, _LOCALITY_SEASON_SUMMARY
    _ZONE_HOME_CAPACITY = {"NW": 1, "NE": 0, "SW": 0}
    _WORKER_HOME_STATE = {}
    _LOCALITY_DAY = -1
    _LOCALITY_WORKER_METRICS = {}
    _LOCALITY_DAILY_LOG = {}
    _LOCALITY_RAW_RECORDS = []
    _LOCALITY_PREV_POS = {}
    _LOCALITY_LAST_FIELD_QUAD = {}
    _LOCALITY_SEASON_SUMMARY = {
        "total_within_day_reassignments": 0,
        "total_ne_sw_home_changes": 0,
        "total_physical_ne_sw_traversals": 0,
        "total_temporary_spillovers": 0,
        "total_emergency_preemptions": 0,
        "total_travel_distance": 0,
        "total_moves": 0,
        "total_ops": 0,
    }

_SW_SEASONAL_TRACKER = {
    "first_sw_unlock_day": None,
    "first_sw_active_day": None,
    "daily_active_tiles": {},
    "daily_utilization": {},
    "daily_empty_tiles": {},
    "sw_tasks_created": 0,
    "sw_tasks_assigned": 0,
    "sw_tasks_completed": 0,
    "sw_movement_actions": 0,
    "sw_operation_actions": 0,
}

def get_sw_tile_breakdown(farm):
    """Compute an authoritative, mutually exclusive breakdown of all 25 SW tiles.

    SW is defined as cols 0-4 (x in [0, 4]), rows 5-9 (y in [5, 9]) on the 10x10 board.
    Categories:
      - crops: live plant tiles (is_plant or kind == 'PLANT')
      - animals: live animal tiles (is_animal or kind == 'ANIMAL')
      - structures: empty animal structures (kind in ('PASTURE', 'COOP') and not is_animal)
      - weeds: weed tiles (kind == 'WEED')
      - empty: unlocked unplanted/unbuilt ground (kind == 'EMPTY')
      - active: crops + animals + structures (no double-counting)
      - sw_owned: 'SW' in farm.unlocked (or 'SW' in farm['unlocked_quadrants'])

    When sw_owned is True:
      active + weeds + empty == 25
      utilization = round(active / 25.0, 4)
    When sw_owned is False:
      active = 0
      utilization = None
      empty = None
    """
    if farm is None:
        return {
            "sw_owned": False, "crops": 0, "crops_strawberry": 0, "crops_other": 0,
            "animals": 0, "structures": 0, "weeds": 0, "empty": None,
            "active": 0, "total_tiles": 25, "utilization": None,
        }

    if hasattr(farm, "unlocked"):
        sw_owned = "SW" in farm.unlocked
    elif isinstance(farm, dict):
        sw_owned = "SW" in farm.get("unlocked_quadrants", ["NW"])
    else:
        sw_owned = False

    crops = 0
    crops_strawberry = 0
    crops_other = 0
    animals = 0
    structures = 0
    weeds = 0
    empty = 0

    if hasattr(farm, "iter_tiles") and hasattr(farm, "quadrant_of"):
        for t in farm.iter_tiles():
            if farm.quadrant_of(t.pos) != "SW":
                continue
            is_plant = getattr(t, "is_plant", False) or getattr(t, "kind", "") == "PLANT"
            is_animal = getattr(t, "is_animal", False) or getattr(t, "kind", "") == "ANIMAL"
            kind = getattr(t, "kind", "")

            if is_plant:
                crops += 1
                if getattr(t, "crop", None) == "STRAWBERRY":
                    crops_strawberry += 1
                else:
                    crops_other += 1
            elif is_animal:
                animals += 1
            elif kind in ("PASTURE", "COOP"):
                structures += 1
            elif kind == "WEED":
                weeds += 1
            elif kind == "EMPTY":
                empty += 1
    elif isinstance(farm, dict) and "tiles" in farm:
        raw_tiles = farm["tiles"]
        for r in range(5, min(10, len(raw_tiles))):
            row = raw_tiles[r]
            for c in range(0, min(5, len(row))):
                t = row[c]
                if not isinstance(t, dict):
                    continue
                kind = t.get("kind", "")
                if kind == "PLANT":
                    crops += 1
                    if t.get("crop") == "STRAWBERRY":
                        crops_strawberry += 1
                    else:
                        crops_other += 1
                elif kind == "ANIMAL":
                    animals += 1
                elif kind in ("PASTURE", "COOP"):
                    structures += 1
                elif kind == "WEED":
                    weeds += 1
                elif kind == "EMPTY":
                    empty += 1

    active = crops + animals + structures

    if sw_owned:
        utilization = round(active / 25.0, 4)
    else:
        active = 0
        crops = 0
        crops_strawberry = 0
        crops_other = 0
        animals = 0
        structures = 0
        weeds = 0
        empty = None
        utilization = None

    return {
        "sw_owned": sw_owned,
        "crops": crops,
        "crops_strawberry": crops_strawberry,
        "crops_other": crops_other,
        "animals": animals,
        "structures": structures,
        "weeds": weeds,
        "empty": empty,
        "active": active,
        "total_tiles": 25,
        "utilization": utilization,
    }

def get_sw_season_summary():
    """Return comprehensive seasonal summary of SW telemetry across the entire episode."""
    tracker = _SW_SEASONAL_TRACKER
    unlock_day = tracker.get("first_sw_unlock_day")
    first_active_day = tracker.get("first_sw_active_day")
    daily_active = dict(tracker.get("daily_active_tiles", {}))
    daily_util = dict(tracker.get("daily_utilization", {}))
    daily_empty = dict(tracker.get("daily_empty_tiles", {}))

    if unlock_day is not None:
        valid_post_unlock_utils = [
            util for d, util in daily_util.items()
            if d >= unlock_day and util is not None
        ]
        avg_util = (
            round(sum(valid_post_unlock_utils) / len(valid_post_unlock_utils), 4)
            if valid_post_unlock_utils else None
        )
    else:
        avg_util = None

    all_valid_utils = [u for u in daily_util.values() if u is not None]
    peak_util = max(all_valid_utils) if all_valid_utils else None

    cum_empty_days = sum(e for e in daily_empty.values() if e is not None) if unlock_day is not None else None

    days_zero_active = sum(
        1 for d, act in daily_active.items()
        if unlock_day is not None and d >= unlock_day and act == 0
    ) if unlock_day is not None else 0

    created = tracker.get("sw_tasks_created", 0)
    assigned = tracker.get("sw_tasks_assigned", 0)
    completed = tracker.get("sw_tasks_completed", 0)
    moves = tracker.get("sw_movement_actions", 0)
    ops = tracker.get("sw_operation_actions", 0)

    asgn_rate = round(assigned / created, 4) if created > 0 else None
    comp_rate = round(completed / assigned, 4) if assigned > 0 else None

    return {
        "sw_owned": (unlock_day is not None),
        "first_sw_unlock_day": unlock_day,
        "first_sw_active_day": first_active_day,
        "daily_active_tiles": daily_active,
        "daily_utilization": daily_util,
        "avg_sw_util_after_unlock": avg_util,
        "peak_sw_util": peak_util,
        "cumulative_sw_empty_tile_days": cum_empty_days,
        "days_sw_owned_zero_active": days_zero_active,
        "sw_tasks_created": created,
        "sw_tasks_assigned": assigned,
        "sw_tasks_completed": completed,
        "sw_movement_actions": moves,
        "sw_operation_actions": ops,
        "sw_assignment_rate": asgn_rate,
        "sw_completion_rate": comp_rate,
    }

def reset_daily_log():
    """Reset utilization log at start of new episode."""
    global _daily_log, _daily_accum, _SW_SEASONAL_TRACKER
    _daily_log = {}
    _daily_accum = {}
    _SW_SEASONAL_TRACKER = {
        "first_sw_unlock_day": None,
        "first_sw_active_day": None,
        "daily_active_tiles": {},
        "daily_utilization": {},
        "daily_empty_tiles": {},
        "sw_tasks_created": 0,
        "sw_tasks_assigned": 0,
        "sw_tasks_completed": 0,
        "sw_movement_actions": 0,
        "sw_operation_actions": 0,
    }
    reset_sticky_missions()
    reset_blocked_task_tracker()
    reset_worker_locality()

def classify_task_action(act, task, farm):
    """Classify action semantically into (category, quadrant)."""
    if not act:
        return "pass", None
    op = act[0]
    if op == "PASS":
        return "pass", None
    if op in ("NORTH", "SOUTH", "EAST", "WEST"):
        return "move", None

    tgt = task.get("target") if task else None
    kind = task.get("kind", "") if task else ""
    args = task.get("args", []) if task else []

    shed_tiles = {(4, 4), (5, 4), (4, 5), (5, 5)}
    if (op in ("PICKUP", "DROP") or kind == "deposit_product"
            or (tgt and tuple(tgt) in shed_tiles and op in ("PICKUP", "DROP"))):
        return "logistics", "CENTRAL"

    tgt_quad = farm.quadrant_of(tgt) if (tgt and hasattr(farm, "quadrant_of")) else "NW"

    if op in ("PLANT", "WATER", "FERTILIZE"):
        return "crop", tgt_quad
    if op == "HARVEST":
        is_anim = "animal" in kind
        if not is_anim and tgt and hasattr(farm, "tile_at"):
            tile = farm.tile_at(tgt)
            if tile and (getattr(tile, "is_animal", False) or getattr(tile, "kind", "") == "ANIMAL"):
                is_anim = True
        return ("livestock" if is_anim else "crop"), tgt_quad
    if op in ("FEED", "CARE", "COLLECT_FERTILIZER"):
        return "livestock", tgt_quad
    if op in ("BUILD_PASTURE", "BUILD_COOP") or (op == "PLACE" and args and args[0] in ANIMALS):
        return "housing", tgt_quad
    if op == "DIG":
        return "maintenance", tgt_quad
    return "other", tgt_quad


def _record_turn_utilization(ctx, n_units, actions_taken, assignment=None, turn_blocked=None, turn_sw=None, home_quads=None, pos_by_idx=None):
    """Accumulate hourly utilization and finalize daily log at hour 23."""
    day, hour = ctx["day"], ctx["hour"]
    if day not in _daily_accum:
        _daily_accum[day] = {
            "available": 0,
            "used": 0,
            "idle": 0,
            "moves": 0,
            "completions": 0,
            "urgent_assigned": 0,
            "urgent_completions": 0,
            "quad_attempts": {"NW": 0, "NE": 0, "SW": 0, "SE": 0},
            "quad_completions": {"NW": 0, "NE": 0, "SW": 0, "SE": 0},
            "home_unit_turns": {"NW": 0, "NE": 0, "SW": 0, "SE": 0},
            "sw_tasks_created": 0,
            "sw_anchor_assignments": 0,
            "sw_tasks_assigned": 0,
            "sw_tasks_completed": 0,
            "sw_movement_actions": 0,
            "sw_operation_actions": 0,
            "idle_causes": [],
            "blocked_diagnostics": {
                "blocked_due_inventory": 0,
                "blocked_due_zone": 0,
                "blocked_due_no_carrier": 0,
                "blocked_due_capacity": 0,
                "blocked_task_turns": 0,
                "urgent_blocked_turns": 0,
                "max_blocked_duration": 0,
            },
        }

    used = sum(1 for a in actions_taken.values() if a != ["PASS"])
    avail = n_units
    idle = max(0, avail - used)
    moves = sum(1 for a in actions_taken.values() if a and a[0] in ("NORTH", "SOUTH", "EAST", "WEST"))
    completions = sum(1 for a in actions_taken.values() if a != ["PASS"] and a and a[0] not in ("NORTH", "SOUTH", "EAST", "WEST"))

    _daily_accum[day]["available"] += avail
    _daily_accum[day]["used"] += used
    _daily_accum[day]["idle"] += idle
    _daily_accum[day]["moves"] += moves
    _daily_accum[day]["completions"] += completions
    if idle > 0:
        _daily_accum[day]["idle_causes"].append("no_tasks" if used == 0 else "partial_idle")

    if assignment:
        for u_idx, task in assignment.items():
            act = actions_taken.get(u_idx, ["PASS"])
            is_comp = (act != ["PASS"] and act and act[0] not in ("NORTH", "SOUTH", "EAST", "WEST"))
            prio = task.get("priority", 0)
            is_urgent = (prio >= PRIORITY_URGENT_SURVIVAL or task.get("kind") in ("feed_rescue", "harvest_decay", "feed_prod") or (task.get("op") == "PLACE" and (task.get("args") or [None])[0] in ANIMALS))
            if is_urgent:
                _daily_accum[day]["urgent_assigned"] += 1
                if is_comp:
                    _daily_accum[day]["urgent_completions"] += 1
            tgt = task.get("target")
            if tgt and ctx.get("farm") and hasattr(ctx["farm"], "quadrant_of"):
                q = ctx["farm"].quadrant_of(tgt)
                if q in _daily_accum[day]["quad_attempts"]:
                    _daily_accum[day]["quad_attempts"][q] += 1
                    if is_comp:
                        _daily_accum[day]["quad_completions"][q] += 1

    if home_quads:
        for q in home_quads.values():
            if q in _daily_accum[day]["home_unit_turns"]:
                _daily_accum[day]["home_unit_turns"][q] += 1

    # Turn-by-turn locality telemetry tracking
    global _LOCALITY_WORKER_METRICS, _LOCALITY_DAILY_LOG, _LOCALITY_RAW_RECORDS
    global _LOCALITY_PREV_POS, _LOCALITY_LAST_FIELD_QUAD, _LOCALITY_SEASON_SUMMARY, _LOCALITY_DAY
    if day != _LOCALITY_DAY:
        _LOCALITY_DAY = day
        _LOCALITY_PREV_POS.clear()
        _LOCALITY_LAST_FIELD_QUAD.clear()

    farm = ctx.get("farm")
    shed_tiles = {(4, 4), (5, 4), (4, 5), (5, 5)}
    if home_quads and pos_by_idx and farm and hasattr(farm, "quadrant_of"):
        for u in range(n_units):
            h_q = home_quads.get(u, "NW")
            u_pos = pos_by_idx.get(u, (4, 4))
            phys_q = farm.quadrant_of(u_pos)

            if u not in _LOCALITY_WORKER_METRICS:
                _LOCALITY_WORKER_METRICS[u] = {
                    "unit_idx": u,
                    "day": day,
                    "home_quadrant": h_q,
                    "turns_in_home": 0,
                    "home_changes": 0,
                    "ne_sw_changes": 0,
                    "temporary_spillovers": 0,
                    "quadrants_worked": set(),
                    "moves": 0,
                    "productive_ops": 0,
                    "travel_distance": 0,
                    "productive_by_zone": {"NW": 0, "NE": 0, "SW": 0, "SE": 0},
                    "ops_by_category": {
                        "crop": 0, "livestock": 0, "housing": 0, "logistics": 0, "maintenance": 0, "other": 0
                    },
                    "ops_by_quad_and_type": {
                        q: {"crop": 0, "livestock": 0, "housing": 0, "logistics": 0, "maintenance": 0, "other": 0}
                        for q in ("NW", "NE", "SW", "SE")
                    },
                }
            m = _LOCALITY_WORKER_METRICS[u]
            if phys_q == h_q:
                m["turns_in_home"] += 1

            prev_pos = _LOCALITY_PREV_POS.get(u, u_pos)
            step_d = abs(u_pos[0] - prev_pos[0]) + abs(u_pos[1] - prev_pos[1])
            _LOCALITY_PREV_POS[u] = u_pos
            m["travel_distance"] += step_d
            _LOCALITY_SEASON_SUMMARY["total_travel_distance"] += step_d

            # True field-to-field traversal tracking (excluding shed-adjacent transit & spawn)
            is_on_shed = (u_pos in shed_tiles)
            if not is_on_shed:
                last_field_q = _LOCALITY_LAST_FIELD_QUAD.get(u)
                if last_field_q is not None and last_field_q != phys_q:
                    if (last_field_q == "NE" and phys_q == "SW") or (last_field_q == "SW" and phys_q == "NE"):
                        _LOCALITY_SEASON_SUMMARY["total_physical_ne_sw_traversals"] += 1
                        m["ne_sw_traversals"] = m.get("ne_sw_traversals", 0) + 1
                _LOCALITY_LAST_FIELD_QUAD[u] = phys_q

            act = actions_taken.get(u, ["PASS"])
            if act and act[0] in ("NORTH", "SOUTH", "EAST", "WEST"):
                m["moves"] += 1
                _LOCALITY_SEASON_SUMMARY["total_moves"] += 1
            elif act != ["PASS"] and act:
                m["productive_ops"] += 1
                _LOCALITY_SEASON_SUMMARY["total_ops"] += 1
                task = assignment.get(u, {}) if assignment else {}
                cat, act_quad = classify_task_action(act, task, farm)
                m["ops_by_category"][cat] = m["ops_by_category"].get(cat, 0) + 1
                if act_quad in ("NW", "NE", "SW", "SE"):
                    m["quadrants_worked"].add(act_quad)
                    m["productive_by_zone"][act_quad] = m["productive_by_zone"].get(act_quad, 0) + 1
                    m["ops_by_quad_and_type"][act_quad][cat] = m["ops_by_quad_and_type"][act_quad].get(cat, 0) + 1
                    if act_quad != h_q:
                        m["temporary_spillovers"] += 1
                        _LOCALITY_SEASON_SUMMARY["total_temporary_spillovers"] += 1

    if assignment:
        _daily_accum[day]["sw_anchor_assignments"] += sum(
            1 for task in assignment.values() if task.get("kind") == "sw_anchor"
        )

    if turn_sw:
        _daily_accum[day]["sw_tasks_created"] += turn_sw.get("created", 0)
        _daily_accum[day]["sw_tasks_assigned"] += turn_sw.get("assigned", 0)
        _daily_accum[day]["sw_tasks_completed"] += turn_sw.get("completed", 0)
        _daily_accum[day]["sw_movement_actions"] += turn_sw.get("moves", 0)
        _daily_accum[day]["sw_operation_actions"] += turn_sw.get("ops", 0)
        _SW_SEASONAL_TRACKER["sw_tasks_created"] += turn_sw.get("created", 0)
        _SW_SEASONAL_TRACKER["sw_tasks_assigned"] += turn_sw.get("assigned", 0)
        _SW_SEASONAL_TRACKER["sw_tasks_completed"] += turn_sw.get("completed", 0)
        _SW_SEASONAL_TRACKER["sw_movement_actions"] += turn_sw.get("moves", 0)
        _SW_SEASONAL_TRACKER["sw_operation_actions"] += turn_sw.get("ops", 0)

    if turn_blocked:
        for k, v in turn_blocked.items():
            if k == "max_blocked_duration":
                _daily_accum[day]["blocked_diagnostics"][k] = max(
                    _daily_accum[day]["blocked_diagnostics"].get(k, 0), v
                )
            elif k in _daily_accum[day]["blocked_diagnostics"]:
                _daily_accum[day]["blocked_diagnostics"][k] += v
        
    if hour == 23 or ctx.get("step", 0) % TURNS_PER_DAY == 23:
        tot_avail = _daily_accum[day]["available"]
        tot_used = _daily_accum[day]["used"]
        tot_idle = _daily_accum[day]["idle"]
        tot_moves = _daily_accum[day]["moves"]
        tot_comp = _daily_accum[day]["completions"]
        tot_urg_att = _daily_accum[day]["urgent_assigned"]
        tot_urg_comp = _daily_accum[day]["urgent_completions"]
        q_att = _daily_accum[day]["quad_attempts"]
        q_comp = _daily_accum[day]["quad_completions"]

        shed_cnt = sum(ctx["private"].shed.values()) if ctx.get("private") else 0
        unlocked_cnt = len(ctx["farm"].unlocked) if ctx.get("farm") else 1
        n_hands = len(ctx["farm"].hands) if ctx.get("farm") else 0
        try:
            from market.order_builder import hire_total_cost
            h_cost = hire_total_cost(n_hands)
        except (ImportError, NameError):
            def _f(n):
                a, b = 1, 1
                for _ in range(n):
                    a, b = b, a + b
                return a
            h_cost = sum(_f(i) for i in range(n_hands))

        farm = ctx.get("farm")
        sw_breakdown = get_sw_tile_breakdown(farm)
        sw_owned = sw_breakdown["sw_owned"]
        if sw_owned:
            if _SW_SEASONAL_TRACKER["first_sw_unlock_day"] is None:
                _SW_SEASONAL_TRACKER["first_sw_unlock_day"] = day
            act_tiles = sw_breakdown["active"]
            if act_tiles > 0 and _SW_SEASONAL_TRACKER["first_sw_active_day"] is None:
                _SW_SEASONAL_TRACKER["first_sw_active_day"] = day
            _SW_SEASONAL_TRACKER["daily_active_tiles"][day] = act_tiles
            _SW_SEASONAL_TRACKER["daily_utilization"][day] = sw_breakdown["utilization"]
            _SW_SEASONAL_TRACKER["daily_empty_tiles"][day] = sw_breakdown["empty"]
        else:
            _SW_SEASONAL_TRACKER["daily_active_tiles"][day] = 0
            _SW_SEASONAL_TRACKER["daily_utilization"][day] = None
            _SW_SEASONAL_TRACKER["daily_empty_tiles"][day] = None

        d_created = _daily_accum[day]["sw_tasks_created"]
        d_assigned = _daily_accum[day]["sw_tasks_assigned"]
        d_completed = _daily_accum[day]["sw_tasks_completed"]
        d_moves = _daily_accum[day]["sw_movement_actions"]
        d_ops = _daily_accum[day]["sw_operation_actions"]

        sw_comp_rate = round(d_completed / d_assigned, 4) if d_assigned > 0 else None
        sw_asgn_rate = round(d_assigned / d_created, 4) if d_created > 0 else None

        # Compute and finalize daily locality metrics
        tot_home_changes = sum(m["home_changes"] for m in _LOCALITY_WORKER_METRICS.values())
        tot_turns_in_home = sum(m["turns_in_home"] for m in _LOCALITY_WORKER_METRICS.values())
        tot_worker_turns = max(1, len(_LOCALITY_WORKER_METRICS) * 24)
        pct_in_home = round(tot_turns_in_home / tot_worker_turns, 4)

        workers_both_ne_sw = sum(
            1 for m in _LOCALITY_WORKER_METRICS.values()
            if "NE" in m["quadrants_worked"] and "SW" in m["quadrants_worked"]
        )

        for u_m in _LOCALITY_WORKER_METRICS.values():
            rec = dict(u_m)
            rec["quadrants_worked"] = sorted(list(u_m["quadrants_worked"]))
            _LOCALITY_RAW_RECORDS.append(rec)

        day_locality = {
            "within_day_home_changes_per_worker": round(tot_home_changes / max(1, len(_LOCALITY_WORKER_METRICS)), 4),
            "ne_sw_home_changes": sum(m["ne_sw_changes"] for m in _LOCALITY_WORKER_METRICS.values()),
            "physical_ne_sw_traversals": _LOCALITY_SEASON_SUMMARY["total_physical_ne_sw_traversals"],
            "same_home_retention_pct": round(1.0 - (tot_home_changes / max(1, tot_worker_turns)), 4),
            "workers_both_ne_sw_same_day": workers_both_ne_sw,
            "pct_time_in_home_quadrant": pct_in_home,
            "total_travel_distance": sum(m["travel_distance"] for m in _LOCALITY_WORKER_METRICS.values()),
            "moves_per_productive_op": round(
                sum(m["moves"] for m in _LOCALITY_WORKER_METRICS.values()) /
                max(1, sum(m["productive_ops"] for m in _LOCALITY_WORKER_METRICS.values())), 4
            ),
            "temporary_spillovers": sum(m["temporary_spillovers"] for m in _LOCALITY_WORKER_METRICS.values()),
            "emergency_preemptions": _LOCALITY_SEASON_SUMMARY["total_emergency_preemptions"],
            "productive_ops_by_zone": {
                q: sum(m["productive_by_zone"].get(q, 0) for m in _LOCALITY_WORKER_METRICS.values())
                for q in ("NW", "NE", "SW", "SE")
            },
            "ops_by_category": {
                cat: sum(m.get("ops_by_category", {}).get(cat, 0) for m in _LOCALITY_WORKER_METRICS.values())
                for cat in ("crop", "livestock", "housing", "logistics", "maintenance", "other")
            },
            "ops_by_quad_and_type": {
                q: {cat: sum(m.get("ops_by_quad_and_type", {}).get(q, {}).get(cat, 0) for m in _LOCALITY_WORKER_METRICS.values())
                    for cat in ("crop", "livestock", "housing", "logistics", "maintenance", "other")}
                for q in ("NW", "NE", "SW", "SE")
            },
            "unassigned_task_turns_by_zone": {
                q: sum(info["consecutive_duration"] for info in _BLOCKED_TASK_TRACKER.values() if info.get("quadrant") == q)
                for q in ("NW", "NE", "SW", "SE")
            },
        }
        _LOCALITY_DAILY_LOG[day] = day_locality
        _LOCALITY_WORKER_METRICS = {}
        
        _daily_log[day] = {
            "actions_available": tot_avail,
            "actions_used": tot_used,
            "idle_actions": tot_idle,
            "utilization_pct": round(100.0 * tot_used / max(1, tot_avail), 1),
            "action_utilization": round(tot_used / max(1, tot_avail), 4),
            "completion_rate": round(tot_comp / max(1, tot_used), 4) if tot_used > 0 else 0.0,
            "travel_share": round(tot_moves / max(1, tot_used), 4) if tot_used > 0 else 0.0,
            "urgent_completion_rate": round(tot_urg_comp / max(1, tot_urg_att), 4) if tot_urg_att > 0 else None,
            "quadrant_completion_rates": {
                q: (round(q_comp[q] / max(1, q_att[q]), 4) if q_att[q] > 0 else None)
                for q in ("NW", "NE", "SW", "SE")
            },
            "home_unit_turns": dict(_daily_accum[day]["home_unit_turns"]),
            "shed_occupancy": shed_cnt,
            "quadrant_ownership": unlocked_cnt,
            "daily_hires": n_hands,
            "hire_cost": h_cost,
            "idle_cause": "queue_empty" if tot_idle > 0 else None,
            "blocked_diagnostics": dict(_daily_accum[day]["blocked_diagnostics"]),
            "sw_telemetry": {
                "sw_owned": sw_owned,
                "active_tiles": sw_breakdown["active"],
                "empty_tiles": sw_breakdown["empty"],
                "utilization": sw_breakdown["utilization"],
                "sw_tasks_created": d_created,
                "sw_anchor_assignments": _daily_accum[day]["sw_anchor_assignments"],
                "sw_tasks_assigned": d_assigned,
                "sw_tasks_completed": d_completed,
                "sw_movement_actions": d_moves,
                "sw_operation_actions": d_ops,
                "sw_assignment_rate": sw_asgn_rate,
                "sw_completion_rate": sw_comp_rate,
            },
            "locality_telemetry": day_locality,
        }


def farm_pos_of(ctx):
    return ctx["farm"].farmer


def _accessible_shed_tiles(farm):
    """Shed access points usable for logistics under the scheduler's zone model."""
    unlocked = set(getattr(farm, "unlocked", ()) or ())
    usable = [tuple(p) for p in SHED_ACCESS_TILES
              if not hasattr(farm, "quadrant_of") or farm.quadrant_of(tuple(p)) in unlocked]
    return usable or [tuple(SHED_ACCESS_TILES[0])]


def _nearest_shed_access(farm, pos):
    tiles = _accessible_shed_tiles(farm)
    return min(tiles, key=lambda p: abs(p[0] - pos[0]) + abs(p[1] - pos[1]))


def _endgame_harvest_can_realize(ctx, target):
    """Conservative Day-29 proof that a harvest can still reach shed and sell.

    Unit actions execute before market. Once a carrier reaches shed access, a
    PLACE/DROP deposit can therefore be sold on that same turn by the market
    layer. Earliest realization is: travel-to-target + HARVEST + travel-to-shed
    + deposit/sell turn. If even the closest current worker cannot make Hour 23,
    harvesting only strands value on a worker and is suppressed.
    """
    if ctx.get("day", 0) < 29:
        return True
    hour = int(ctx.get("hour", 0))
    farm = ctx["farm"]
    positions = [tuple(farm.farmer)] + [tuple(h) for h in farm.hands]
    if not positions:
        return False
    target = tuple(target)
    to_target = min(abs(p[0] - target[0]) + abs(p[1] - target[1]) for p in positions)
    shed_target = _nearest_shed_access(farm, target)
    to_shed = abs(target[0] - shed_target[0]) + abs(target[1] - shed_target[1])
    earliest_sale_hour = hour + to_target + to_shed + 1
    return earliest_sale_hour <= 23


def produces_today(tile, day):
    """True if this animal's production fires at END-of-day refresh today."""
    info = ANIMALS.get(tile.animal)
    if info is None:
        return False
    since_first = day + 1 - tile.placed_day - info["first_yield_day"]
    return since_first >= 0 and since_first % info["interval"] == 0


def build_tasks(ctx, macro):
    """Construct the prioritized TaskList for this turn."""
    day, hour = ctx["day"], ctx["hour"]
    tasks = []

    def add(priority, op, target=None, args=None, kind="", meta=None):
        tasks.append({"priority": priority, "op": op, "target": target,
                      "args": args or [], "kind": kind, "meta": meta or {}})

    # ---------------- crops ----------------
    water_starved = False
    plants = [t for t in ctx["farm"].iter_tiles() if t.is_plant]
    need_water = []
    for t in plants:
        cd = CROPS.get(t.crop)
        if cd is None:
            continue
        age = crop_age(t, day)
        # C5: Harvest Decision Logic
        if not cd["ongoing"]:
            # One-time crops (Wheat, Carrot, Melon)
            is_max_day = (age >= cd["max_yield_day"])
            is_max_yield = (t.yield_units >= cd["max_yield"])
            tud = turns_until_decay(t, ctx["step"])
            decay_imminent = (tud is not None and tud <= 4) or (age > cd["max_yield_day"]) or (hour >= 20 and is_max_day)
            is_endgame = (day == 29 and age >= cd["first_yield_day"])
            
            if t.yield_units > 0:
                if is_endgame:
                    # Day 29: only create new worker inventory if the fastest current
                    # worker can still harvest, reach shed, deposit, and sell by Hour 23.
                    if _endgame_harvest_can_realize(ctx, t.pos):
                        add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_endgame")
                elif decay_imminent:
                    # Decay imminent: harvest to prevent crop decay
                    add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_decay")
                elif is_max_yield:
                    # Already at absolute max yield cap: harvest immediately frees tile for replanting
                    prio = PRIORITY_DECAY_HARVEST if is_max_day else PRIORITY_STANDARD_HARVEST
                    add(prio, "HARVEST", t.pos, kind="harvest_full")
                elif is_max_day and t.watered_today:
                    # Watered today on max day: collected final bonus yield, harvest before tomorrow's decay
                    add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_mature_watered")
                # When is_max_day and not t.watered_today and hour < 20:
                # Intentionally defer HARVEST so WATER executes first and collects +1 (+2) bonus!
        else:
            # Ongoing crops (Tomato, Strawberry)
            tud = turns_until_decay(t, ctx["step"])
            decay_imminent = (tud is not None and tud <= 24)
            is_endgame = (day >= 28)
            
            if t.yield_units > 0:
                if is_endgame or decay_imminent:
                    if day < 29 or _endgame_harvest_can_realize(ctx, t.pos):
                        add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing_decay")
                elif t.yield_units >= 2:
                    # Efficient harvest of accumulated produce (2+ units per action)
                    add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing_accum")
                elif t.yield_units >= cd["max_yield"]:
                    add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing_cap")

        if not t.watered_today:
            dying_tomorrow = (t.consecutive_unwatered >= 1) or (t.planted_day == day)
            if dying_tomorrow:
                # Mandatory survival watering: ALWAYS eligible at any hour (including Hour 23)
                need_water.append((PRIORITY_URGENT_SURVIVAL, t))
            elif hour < 23 and needs_water_today(t, day):
                # Normal / bonus watering: only eligible before Hour 23 (existing behavior preserved)
                is_newly_planted = (t.planted_day == day)
                if is_newly_planted:
                    prio = PRIORITY_BONUS_WATER + 5  # Urgent paired water for new plants
                elif in_bonus_window(t, day) or cd.get("ongoing"):
                    # Elevate bonus water on max_yield_day so it waters promptly before harvest
                    if not cd.get("ongoing") and age == cd["max_yield_day"]:
                        prio = PRIORITY_BONUS_WATER + 6
                    else:
                        prio = PRIORITY_BONUS_WATER
                else:
                    prio = 30
                if not macro.watering_enabled and day == 28 and in_bonus_window(t, day):
                    harvestable_by_29 = (t.planted_day is not None
                                         and t.planted_day + cd.get("max_yield_day", 99) <= 29)
                    if not harvestable_by_29:
                        continue
                need_water.append((prio, t))

    for prio, t in need_water:
        add(prio, "WATER", t.pos, kind="water")

    # ---------------- fertilizer application (Strawberries, Tomatoes, & Surplus Arbitrage) ----
    fert_in_shed = int(ctx["private"].shed.get("FERTILIZER", 0)) if ctx.get("private") else 0
    fert_held = sum(int(inv.get("FERTILIZER", 0)) for inv in (ctx["private"].inventories if ctx.get("private") else []))
    total_fert = fert_in_shed + fert_held
    
    if total_fert > 0 and hour < 20:
        # Live fertilizer spot price from market
        fert_spot_price = ctx["market"].prices.get("FERTILIZER", 100) if ctx.get("market") else 100
        
        tier1_strawberry = []
        tier2_tomato = []
        tier3_wheat = []
        tier4_carrot = []
        
        for t in plants:
            if t.fertilized_until_day < day:
                age = crop_age(t, day)
                # Tier 1: Strawberry 2-application precision (Ages 9-10 covers 10 & 12; Ages 13-14 covers 14 & 16)
                if t.crop == "STRAWBERRY" and (9 <= age <= 10 or 13 <= age <= 14):
                    tier1_strawberry.append(t.pos)
                # Tier 2: Tomato 2-application precision (Ages 7-8 covers 8, 9, 10; Ages 10-11 covers 11)
                elif t.crop == "TOMATO" and (7 <= age <= 8 or 10 <= age <= 11):
                    tier2_tomato.append(t.pos)
                # Tier 3: Surplus Wheat Arbitrage (applies when market price < $50, window ages 1-2)
                elif fert_spot_price < 50 and t.crop == "WHEAT" and (1 <= age <= 2):
                    tier3_wheat.append(t.pos)
                # Tier 4: Surplus Carrot Arbitrage (applies when market price < $35, window ages 1-2)
                elif fert_spot_price < 35 and t.crop == "CARROT" and (1 <= age <= 2):
                    tier4_carrot.append(t.pos)
                    
        # Prioritize Tier 1 -> Tier 2 -> Tier 3 -> Tier 4
        all_fert_targets = tier1_strawberry + tier2_tomato + tier3_wheat + tier4_carrot
        
        for pos in all_fert_targets[:total_fert]:
            add(PRIORITY_FERTILIZE_CROP, "FERTILIZE", pos, kind="fertilize_crop")
            
        # Stage fertilizer pickup from shed if needed
        needed_pickup = len(all_fert_targets[:total_fert]) - fert_held
        if needed_pickup > 0 and fert_in_shed > 0:
            grab_fert = min(fert_in_shed, needed_pickup)
            farmer_pos = tuple(farm_pos_of(ctx))
            target = min(SHED_ACCESS_TILES,
                         key=lambda tp: abs(tp[0] - farmer_pos[0]) + abs(tp[1] - farmer_pos[1]))
            add(PRIORITY_FEED_STAGING + 1, "PICKUP", tuple(target),
                args=["FERTILIZER", int(grab_fert)], kind="pickup_fertilizer")

    # ---------------- animals ----------------
    feeds_due = 0
    max_feed_prio = 0
    for t in ctx["farm"].iter_tiles():
        if not t.is_animal:
            continue
        feed_now = False
        feed_prio = 0
        if t.consecutive_unfed >= 1 and not t.fed_today and hour < 24:
            # Animal is at risk of escape! Top survival priority (105)
            feed_prio = PRIORITY_URGENT_SURVIVAL + 5
            add(feed_prio, "FEED", t.pos, kind="feed_rescue", meta={"wheat": 1})
            feed_now = True
        elif produces_today(t, day) and not t.fed_today and hour < 24:
            if hour >= 14:
                # Approaching deadline: escalate to urgent survival
                feed_prio = PRIORITY_URGENT_SURVIVAL + 2
            else:
                feed_prio = PRIORITY_PROD_DAY_FEED
            add(feed_prio, "FEED", t.pos, kind="feed_prod", meta={"wheat": 1})
            feed_now = True
        elif not t.fed_today and hour < 24 and macro.feeding_enabled:
            # Off-day feeding: keep animals fed daily to prevent consecutive unfed days
            if hour >= 18:
                feed_prio = PRIORITY_URGENT_SURVIVAL + 1  # 101
            elif hour >= 14:
                feed_prio = PRIORITY_URGENT_SURVIVAL      # 100 (escalates above SW crop care)
            else:
                feed_prio = PRIORITY_CARE_ANIMAL - 5      # 60
            add(feed_prio, "FEED", t.pos, kind="feed_off", meta={"wheat": 1})
            feed_now = True

        if feed_now:
            feeds_due += 1
            if feed_prio > max_feed_prio:
                max_feed_prio = feed_prio

        if t.yield_units > 0:
            if day < 29 or _endgame_harvest_can_realize(ctx, t.pos):
                add(PRIORITY_STANDARD_HARVEST + 5, "HARVEST", t.pos, kind="harvest_animal")
        if t.fertilizer_available:
            add(PRIORITY_FERT_COLLECT, "COLLECT_FERTILIZER", t.pos, kind="fert")
        want_care = macro.feeding_enabled and (CARE_GEESE or t.animal != "GOOSE")
        if want_care and not t.cared_today and hour < 21:
            add(PRIORITY_CARE_ANIMAL, "CARE", t.pos, kind="care")

    # WHEAT STAGING: engine FEED consumes the UNIT's inventory (never the
    # shed), so staged PICKUP tasks must run before any FEED can succeed.
    # Distribute wheat across multiple workers in small chunks (2-3 wheat)
    # so multiple workers can feed animals simultaneously!
    if feeds_due > 0:
        held = sum(int(inv.get("WHEAT", 0)) for inv in ctx["private"].inventories)
        shed_wheat = int(ctx["private"].shed.get("WHEAT", 0))
        needed = min(shed_wheat, max(feeds_due - held, 0))
        if needed > 0:
            staging_prio = max(PRIORITY_FEED_STAGING, max_feed_prio + 1)
            chunk_size = 3
            n_chunks = (needed + chunk_size - 1) // chunk_size
            for c_idx in range(n_chunks):
                take = min(chunk_size, needed - c_idx * chunk_size)
                target = SHED_ACCESS_TILES[c_idx % len(SHED_ACCESS_TILES)]
                add(staging_prio, "PICKUP", tuple(target),
                    args=["WHEAT", int(take)], kind="pickup_wheat")

    # ---------------- harvested-product realization ----------------
    # HARVEST puts goods on the acting worker, while SELL reads only the shed.
    # End-of-day auto-drop is useful but can discard overflow and is too late for
    # final-day liquidation. Create at most one delivery mission per carrier.
    private = ctx.get("private")
    if private is not None:
        inventories = list(getattr(private, "inventories", []) or [])
        shed = getattr(private, "shed", {}) or {}
        shed_load = sum(max(0, int(v)) for v in shed.values())
        room_budget = max(0, SHED_CAPACITY - shed_load)
        carried_sellable_total = sum(
            max(0, int((inv or {}).get(p, 0)))
            for inv in inventories for p in PRODUCTS
        )
        pending_total = shed_load + carried_sellable_total
        unit_positions = [tuple(ctx["farm"].farmer)] + [tuple(h) for h in ctx["farm"].hands]

        for u_idx, inv in enumerate(inventories):
            if u_idx >= len(unit_positions) or room_budget <= 0 or not inv:
                continue

            deliverable = {}
            for item, raw_n in inv.items():
                n = max(0, int(raw_n or 0))
                if n <= 0 or item not in PRODUCTS:
                    continue
                # Do not pull feed wheat away from live FEED obligations.
                if item == "WHEAT" and feeds_due > 0:
                    continue
                # Fertilizer remains an execution resource until endgame.
                if item == "FERTILIZER" and day < 28:
                    continue
                deliverable[item] = n

            if not deliverable:
                continue

            carried_here = sum(deliverable.values())
            # Normal-day worker inventory is intentionally allowed to ride until
            # the engine's free end-of-day auto-drop. Explicit shed travel costs
            # scarce field actions and previously caused watering/feed regressions.
            # Intervene only when value is at risk of EOD overflow, or on Day 29
            # when EOD auto-drop occurs after the final market opportunity.
            overflow_risk = pending_total > SHED_CAPACITY
            should_deliver = (
                day == 29
                or (hour >= 22 and overflow_risk)
            )
            if not should_deliver:
                continue

            if day == 29:
                delivery_prio = PRIORITY_ENDGAME_PRODUCT_DELIVERY
            else:
                delivery_prio = PRIORITY_PRODUCT_DELIVERY_PRESSURE

            target = _nearest_shed_access(ctx["farm"], unit_positions[u_idx])
            at_shed = unit_positions[u_idx] == tuple(target)
            all_positive = {k: int(v) for k, v in inv.items() if int(v or 0) > 0}
            # DROP discards overflow in the engine. Use it only when it will
            # execute now and the full inventory fits in the still-reserved room.
            safe_drop = (
                day >= 28
                and at_shed
                and all(k in deliverable for k in all_positive)
                and sum(all_positive.values()) <= room_budget
            )

            if safe_drop:
                qty = sum(all_positive.values())
                add(
                    delivery_prio, "DROP", target, kind="deposit_product",
                    meta={
                        "required_unit": u_idx,
                        "deposit_items": dict(all_positive),
                        "deposit_units": qty,
                    },
                )
                room_budget -= qty
            else:
                # Selective PLACE-to-shed preserves unrelated feed/animal/fertilizer
                # inventory and never discards overflow. Travelling missions do
                # not reserve future shed room; capacity is re-evaluated each turn.
                item, qty = max(deliverable.items(), key=lambda kv: (kv[1], kv[0]))
                available_room = room_budget if at_shed else max(0, SHED_CAPACITY - shed_load)
                take = min(int(qty), available_room)
                if take > 0:
                    add(
                        delivery_prio, "PLACE", target, args=[item, take],
                        kind="deposit_product",
                        meta={
                            "required_unit": u_idx,
                            "product": item,
                            "deposit_units": take,
                        },
                    )
                    if at_shed:
                        room_budget -= take

    # ---------------- planting queue (seed-conflict-safe) ----------------
    seeds = ctx["private"].seeds
    wanted_plants = list(macro.plant_queue)  # [(pos, crop)]
    # Planting cutoff at hour 17 ensures every newly planted seed can be watered before midnight
    if hour <= 17 and macro.watering_enabled:
        by_crop = {}
        for pos, crop in wanted_plants:
            if seeds.get(crop, 0) > by_crop.get(crop, 0):
                by_crop[crop] = by_crop.get(crop, 0) + 1
                add(PRIORITY_PLANT_AND_WATER, "PLANT", pos, args=[crop],
                    kind="plant", meta={"paired_water": True})
            else:
                continue  # skip this crop's remaining instances, keep processing others

    # ---------------- structures & animals ----------------
    for pos in macro.build_queue[:2]:
        add(PRIORITY_BUILD_STRUCTURE, macro.build_op, pos, kind="build")
    for task in macro.place_queue[:4]:
        add(PRIORITY_PLACE_ANIMAL, task["op"], task.get("target"),
            args=task.get("args", []),
            kind=task.get("kind", "place_animal"))

    # ---------------- weeds ----------------
    blocked = {tuple(p) for p, _ in macro.plant_queue}
    for t in ctx["farm"].iter_tiles():
        if t.kind == "WEED" and ctx["farm"].quadrant_of(t.pos) in ctx["farm"].unlocked and hour < 23:
            prio = PRIORITY_WEED_DIG + 15 if t.pos in blocked else PRIORITY_WEED_DIG
            add(prio, "DIG", t.pos, kind="dig")

    try:
        from strategy.sw_tranche_controller import get_sw_tranche_controller
        _treatment_ctrl = get_sw_tranche_controller()
        if _treatment_ctrl.is_treatment_active():
            tasks = _treatment_ctrl.filter_task_scheduler_tasks(tasks, ctx.get("farm"))
    except Exception:
        pass

    return tasks


def get_home_quadrant(u_idx, n_units, unlocked):
    """Stage 8B Phase 1E: C2 Adaptive Zonal Dispatch.
    
    Deterministic home quadrant mapping:
    - If SW unlocked and n_units >= 5:
      Rule W1 partitions the last 4 or 5 hands into SW squad.
      Remaining non-SW hands are split evenly between NW and NE squads.
    - If NE unlocked:
      Units are split evenly between NW and NE squads.
    - If only NW unlocked:
      All units belong to NW squad.
    """
    try:
        from config import get_p41_sw_zonal_expansion_enabled, P41_SW_DEDICATED_WORKER_INDICES
        p41_enabled = bool(get_p41_sw_zonal_expansion_enabled())
    except Exception:
        p41_enabled = False
        P41_SW_DEDICATED_WORKER_INDICES = (11, 12)

    if p41_enabled and "SW" in unlocked:
        # P4.1 Strict 2-Worker Zonal Allocation:
        # Only dedicated workers (11, 12) belong to the SW squad.
        if u_idx in P41_SW_DEDICATED_WORKER_INDICES:
            return "SW"
        # Units not in dedicated SW squad remain strictly partitioned between NW and NE
        non_sw_units = [u for u in range(n_units) if u not in P41_SW_DEDICATED_WORKER_INDICES]
        if u_idx in non_sw_units:
            idx_in_non_sw = non_sw_units.index(u_idx)
            half = max(1, len(non_sw_units) // 2)
            return "NW" if idx_in_non_sw < half else "NE"
        return "NW"

    if "SW" in unlocked and n_units >= 5:
        sw_squad_size = 5 if n_units >= 13 else 4
        sw_start = n_units - sw_squad_size
        if u_idx >= sw_start:
            return "SW"
        non_sw = sw_start
        half = max(1, non_sw // 2)
        return "NW" if u_idx < half else "NE"
    elif "NE" in unlocked:
        half = max(1, n_units // 2)
        return "NW" if u_idx < half else "NE"
def compute_workload_aware_home_quadrants(
    tasks,
    farm,
    n_units,
    pos_by_idx,
    ctx=None,
    protect_core_discretionary_before_sw=False,
    exclude_shed_logistics_from_sw=False,
):
    """Stage 8B Phase 2B: Workload-aware dynamic zonal allocation.
    
    Dynamically sizes zonal squads based on live task demand and priority classes:
    1. Mandatory tasks (prio >= 70): urgent survival, feeding, decay harvest, plant+water, etc.
    2. Discretionary tasks (prio < 70): animal care, standard harvest, bonus water, dig, fertilize.
    3. Required units per zone: u_mand(Z) = ceil(demand_mand(Z) / EFFECTIVE_ACTIONS_PER_UNIT).
    4. First guarantee required units for NW and NE mandatory tasks: u_NW_mand + u_NE_mand.
    5. By default, if surplus units remain, allocate up to required units to SW,
       then distribute remaining surplus to NW/NE discretionary tasks.
    6. The isolated P1.1 scheduler mode can instead protect NW/NE discretionary
       capacity first, then allocate only true surplus to SW. In that mode,
       shed logistics at SHED_ACCESS_TILES do not create SW agricultural demand.
    7. Map specific worker IDs u_idx to quadrants based on minimum transit distance from current positions.
    When PERSISTENT_WORKER_LOCALITY_ENABLED is active:
    - Layer 1: Zone capacity across days. Asymmetric capacity hysteresis preserves justified
      SW capacity across intra-day task lulls when supporting productive assets (crops/animals) exist.
      Capacity shrinks slowly on day boundaries or when assets disappear.
    - Layer 2: Worker home roles within day. Units retain persistent home quadrants with
      switch penalty hysteresis, preventing intra-day bouncing.
    """
    if n_units <= 0:
        return {}

    unlocked = getattr(farm, "unlocked", ["NW"])
    if "SW" not in unlocked and "NE" not in unlocked:
        return {u: "NW" for u in range(n_units)}

    global _ZONE_HOME_CAPACITY, _WORKER_HOME_STATE, _LOCALITY_DAY

    # Check active productive assets in SW
    has_sw_assets = False
    if "SW" in unlocked:
        try:
            sw_breakdown = get_sw_tile_breakdown(farm)
            has_sw_assets = bool(
                sw_breakdown.get("active", 0) > 0
                or sw_breakdown.get("crops", 0) > 0
                or sw_breakdown.get("animals", 0) > 0
                or sw_breakdown.get("structures", 0) > 0
            )
        except Exception:
            if hasattr(farm, "iter_tiles") and hasattr(farm, "quadrant_of"):
                for t in farm.iter_tiles():
                    if farm.quadrant_of(t.pos) == "SW":
                        if getattr(t, "is_plant", False) or getattr(t, "is_animal", False) or getattr(t, "kind", "") in ("PASTURE", "COOP"):
                            has_sw_assets = True
                            break

    curr_day = ctx.get("day", 0) if (ctx and isinstance(ctx, dict)) else 0
    curr_hour = ctx.get("hour", 0) if (ctx and isinstance(ctx, dict)) else 0

    if PERSISTENT_WORKER_LOCALITY_ENABLED:
        if curr_day != _LOCALITY_DAY:
            _LOCALITY_DAY = curr_day
            # Day boundary: if SW productive assets disappeared, allow SW capacity to reset to 0
            if not has_sw_assets:
                _ZONE_HOME_CAPACITY["SW"] = 0
            # Reset worker roles mapping for the new day's hands roster
            _WORKER_HOME_STATE = {}

    # 1. Live task demand by zone and priority class
    demand_mand = {"NW": 0.0, "NE": 0.0, "SW": 0.0}
    demand_disc = {"NW": 0.0, "NE": 0.0, "SW": 0.0}

    for t in tasks:
        tgt = t.get("target") or tuple(farm.farmer)
        q = farm.quadrant_of(tgt) if hasattr(farm, "quadrant_of") else "NW"
        is_shed_logistics = (
            tgt in SHED_ACCESS_TILES
            and (
                t.get("op") in ("PICKUP", "DROP")
                or t.get("kind") in ("pickup_wheat", "deposit_product")
            )
        )
        if exclude_shed_logistics_from_sw and is_shed_logistics:
            # Shed access is shared infrastructure, not SW agricultural demand.
            q = "NW"
        elif t.get("op") == "PICKUP" and tgt in SHED_ACCESS_TILES:
            # Preserve legacy dynamic-allocation behavior outside P1.1.
            q = "SW" if tgt == PORT_SW else "NW"
        if q not in unlocked:
            continue
        prio = t.get("priority", 0)
        is_mand = (
            prio >= 70
            or t.get("kind") in ("feed_rescue", "feed_prod", "harvest_decay")
            or (t.get("op") == "PLACE" and (t.get("args") or [None])[0] in ANIMALS)
        )
        if is_mand:
            demand_mand[q] = demand_mand.get(q, 0.0) + 1.0
        else:
            demand_disc[q] = demand_disc.get(q, 0.0) + 1.0

    eff_ap = float(EFFECTIVE_ACTIONS_PER_UNIT)
    u_mand = {q: math.ceil(demand_mand[q] / eff_ap) for q in ("NW", "NE", "SW")}
    u_disc = {q: math.ceil(demand_disc[q] / eff_ap) for q in ("NW", "NE", "SW")}

    alloc = {"NW": 0, "NE": 0, "SW": 0}

    # First guarantee NW and NE mandatory tasks
    nw_mand = u_mand["NW"]
    ne_mand = u_mand["NE"] if "NE" in unlocked else 0

    if nw_mand + ne_mand >= n_units:
        # Constrained capacity: strictly prioritize NW and NE mandatory tasks
        if n_units <= 2:
            alloc["NW"] = 1
            alloc["NE"] = max(0, n_units - 1)
        else:
            tot = max(1.0, nw_mand + ne_mand)
            alloc["NW"] = max(1, min(n_units - 1, round(n_units * (nw_mand / tot))))
            alloc["NE"] = n_units - alloc["NW"]
        alloc["SW"] = 0
        surplus = 0
    else:
        alloc["NW"] = nw_mand
        alloc["NE"] = ne_mand
        surplus = n_units - (alloc["NW"] + alloc["NE"])

    def _allocate_core_discretionary():
        nonlocal surplus
        if surplus > 0:
            nw_disc = u_disc["NW"]
            give_nw = min(surplus, nw_disc)
            alloc["NW"] += give_nw
            surplus -= give_nw
        if surplus > 0 and "NE" in unlocked:
            ne_disc = u_disc["NE"]
            give_ne = min(surplus, ne_disc)
            alloc["NE"] += give_ne
            surplus -= give_ne

    # P1.1 protects useful NW/NE work before SW. Legacy dynamic allocation
    # retains its historical SW-before-discretionary order when the flag is off.
    if protect_core_discretionary_before_sw:
        _allocate_core_discretionary()

    # Allocate SW only from capacity that remains after the selected core policy.
    if "SW" in unlocked and surplus > 0:
        sw_total_demand = demand_mand["SW"] + demand_disc["SW"]
        sw_req = math.ceil(sw_total_demand / eff_ap)
        if PERSISTENT_WORKER_LOCALITY_ENABLED:
            if has_sw_assets:
                sw_target = max(sw_req, _ZONE_HOME_CAPACITY.get("SW", 0))
            else:
                sw_target = sw_req
            alloc_sw = min(surplus, sw_target)
        else:
            alloc_sw = min(surplus, sw_req)
        alloc["SW"] = alloc_sw
        surplus -= alloc_sw

    if not protect_core_discretionary_before_sw:
        _allocate_core_discretionary()

    # Leftover surplus: distribute between NW and NE
    while surplus > 0:
        if alloc["NW"] <= alloc["NE"]:
            alloc["NW"] += 1
        elif "NE" in unlocked:
            alloc["NE"] += 1
        else:
            alloc["NW"] += 1
        surplus -= 1

    # Ensure NW has at least 1 unit
    if alloc["NW"] == 0 and n_units > 0:
        alloc["NW"] = 1
        max_q = max(("NE", "SW"), key=lambda q: alloc[q])
        if alloc[max_q] > 0:
            alloc[max_q] -= 1

    # Exact total invariant
    diff = n_units - sum(alloc.values())
    alloc["NW"] += diff

    if PERSISTENT_WORKER_LOCALITY_ENABLED:
        _ZONE_HOME_CAPACITY["NW"] = alloc["NW"]
        _ZONE_HOME_CAPACITY["NE"] = alloc["NE"]
        _ZONE_HOME_CAPACITY["SW"] = alloc["SW"]

    # Map worker IDs u_idx to quadrants based on minimum transit distance
    zone_hubs = {
        "NW": (4, 4),
        "NE": (5, 2),
        "SW": PORT_SW,
    }

    slots = []
    for q in ("NW", "NE", "SW"):
        slots.extend([q] * alloc[q])

    cost_matrix = []
    for u in range(n_units):
        u_pos = pos_by_idx.get(u, (4, 4))
        u_curr_q = farm.quadrant_of(u_pos) if hasattr(farm, "quadrant_of") else "NW"
        u_prev_home = _WORKER_HOME_STATE.get(u) if PERSISTENT_WORKER_LOCALITY_ENABLED else None
        row = []
        for target_q in slots:
            dist = abs(u_pos[0] - zone_hubs[target_q][0]) + abs(u_pos[1] - zone_hubs[target_q][1])
            is_diag = (u_curr_q == "SW" and target_q == "NE") or (u_curr_q == "NE" and target_q == "SW")
            if PERSISTENT_WORKER_LOCALITY_ENABLED and u_prev_home:
                is_diag = is_diag or (u_prev_home == "SW" and target_q == "NE") or (u_prev_home == "NE" and target_q == "SW")

            if is_diag:
                cost = 1000 + dist
            elif PERSISTENT_WORKER_LOCALITY_ENABLED:
                # Retain persistent home with hysteresis
                if u_prev_home == target_q:
                    cost = dist  # no switch penalty
                else:
                    cost = dist + (LOCALITY_ZONE_SWITCH_PENALTY if u_prev_home is not None else 0)
            else:
                if u_curr_q == target_q:
                    cost = 0
                else:
                    cost = dist
            row.append(cost)
        cost_matrix.append(row)

    home_quads = {}
    try:
        from scipy.optimize import linear_sum_assignment
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        for u, s in zip(row_ind, col_ind):
            home_quads[u] = slots[s]
    except Exception:
        pairs = []
        for u in range(n_units):
            for s in range(len(slots)):
                pairs.append((cost_matrix[u][s], u, s))
        pairs.sort(key=lambda x: x[0])
        used_u = set()
        used_s = set()
        for cost, u, s in pairs:
            if u not in used_u and s not in used_s:
                used_u.add(u)
                used_s.add(s)
                home_quads[u] = slots[s]
        for u in range(n_units):
            if u not in home_quads:
                home_quads[u] = "NW"

    if PERSISTENT_WORKER_LOCALITY_ENABLED:
        for u in range(n_units):
            new_h = home_quads.get(u, "NW")
            old_h = _WORKER_HOME_STATE.get(u)
            if old_h is not None and old_h != new_h:
                _record_home_switch(u, old_h, new_h, curr_day, curr_hour)
            _WORKER_HOME_STATE[u] = new_h

    return home_quads

def _record_home_switch(u, old_h, new_h, day, hour):
    global _LOCALITY_SEASON_SUMMARY, _LOCALITY_WORKER_METRICS
    _LOCALITY_SEASON_SUMMARY["total_within_day_reassignments"] += 1
    if (old_h == "SW" and new_h == "NE") or (old_h == "NE" and new_h == "SW"):
        _LOCALITY_SEASON_SUMMARY["total_ne_sw_home_changes"] += 1
    if u in _LOCALITY_WORKER_METRICS:
        _LOCALITY_WORKER_METRICS[u]["home_changes"] += 1
        if (old_h == "SW" and new_h == "NE") or (old_h == "NE" and new_h == "SW"):
            _LOCALITY_WORKER_METRICS[u]["ne_sw_changes"] += 1


def _is_mission_valid(mission, u_idx, ctx, pos_by_idx, holders, tasks=None):
    """Check if a previously assigned mission is still active and valid."""
    farm = ctx.get("farm")
    if farm is None:
        return False
    op = mission["op"]
    target = mission.get("target")
    if target is None:
        return False
    target = tuple(target)

    t_quad = farm.quadrant_of(target)
    if t_quad not in farm.unlocked and op != "PICKUP":
        return False

    # Generous upper cap as absolute deadlock/pathing failure guard
    if mission.get("mission_age", mission.get("steps_active", 0)) > 40:
        return False

    # Progress-aware timeout: if stuck without progress for 4 consecutive turns
    if mission.get("consecutive_no_progress", 0) >= 4:
        return False

    if tasks is not None:
        matching_tasks = [
            t for t in tasks
            if t.get("op") == op
            and tuple(t.get("target") or (-1, -1)) == target
            and (
                t.get("kind") != "deposit_product"
                or int((t.get("meta") or {}).get("required_unit", -1)) == int(u_idx)
            )
        ]
        if not matching_tasks:
            # Product deposits are capacity-sensitive. If the current turn no
            # longer emits the delivery (e.g. shed filled), cancel the old
            # sticky mission instead of walking toward a stale/impossible PLACE.
            if mission.get("kind") == "deposit_product":
                return False
            # Keep livestock delivery sticky until PLACE succeeds or is invalidated.
            if op == "PLACE":
                item = (mission.get("args") or [None])[0]
                if item and u_idx in holders.get(item, []):
                    # Target tile must still be unlocked and empty
                    pass
                else:
                    return False
            else:
                return False
        elif mission.get("kind") == "deposit_product":
            # Refresh capacity-sensitive quantity/metadata from this turn's
            # newly generated delivery task while preserving travel progress.
            fresh = matching_tasks[0]
            mission["task"] = dict(fresh)
            mission["args"] = list(fresh.get("args") or [])
            mission["priority"] = fresh.get("priority", mission.get("priority", 0))
            mission["kind"] = fresh.get("kind", "deposit_product")

    if op == "FEED":
        if u_idx not in holders.get("WHEAT", []):
            return False
    elif op == "FERTILIZE":
        if u_idx not in holders.get("FERTILIZER", []):
            return False
    elif op == "PLACE":
        item = (mission.get("args") or [None])[0]
        if item and u_idx not in holders.get(item, []):
            return False

    tile = None
    if hasattr(farm, "tile_at"):
        tile = farm.tile_at(target)
    elif hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if tuple(t.pos) == target:
                tile = t
                break

    if tile is not None:
        if op == "WATER":
            if not getattr(tile, "is_plant", False) or getattr(tile, "watered_today", False) or getattr(tile, "consecutive_unwatered", 0) >= 2:
                return False
        elif op == "FEED":
            if not getattr(tile, "is_animal", False) or getattr(tile, "fed_today", False):
                return False
        elif op == "HARVEST":
            if getattr(tile, "yield_units", 0) <= 0:
                return False
        elif op == "FERTILIZE":
            if getattr(tile, "fertilized_until_day", -1) >= ctx.get("day", 0):
                return False
        elif op == "DIG":
            if getattr(tile, "kind", "") != "WEED":
                return False
        elif op == "PLACE":
            # Product deposits use PLACE-at-shed and are valid regardless of
            # the farm tile occupying that shed-access coordinate.
            if mission.get("kind") != "deposit_product" and getattr(tile, "is_animal", False):
                return False

    return True


def assign_tasks(tasks, ctx, extra_units=()):
    """C2 Adaptive Zonal Dispatch + Greedy closest-unit assignment.
    
    Stage 8B Phase 1E:
    - Prioritizes home-zone workers for tasks in their preferred quadrant.
    - Permits controlled cross-zone spillover only when the home zone is underutilized.
    - Enforces travel distance threshold and prohibits diagonal jumps (SW <-> NE).
    - Preserves Rule W1/W2 SW squad partitioning, PORT_SW anchors, and shortest path routing.
    - Tracks daily utilization and logs idle actions.
    - Sticky multi-turn mission ownership preserves workers on travel routes.
    """
    farm = ctx["farm"]
    units = [(0, tuple(farm.farmer))]
    for i, h in enumerate(farm.hands):
        units.append((i + 1, tuple(h)))
    for idx, pos in extra_units:
        units.append((idx, tuple(pos)))
    pos_by_idx = dict(units)
    n_units = len(units)

    try:
        from config import get_soft_worker_locality_mode
        soft_locality_on = (get_soft_worker_locality_mode() == "ON")
    except Exception:
        soft_locality_on = False

    # Holder map for PLACE tasks: engine PLACE requires the ACTING unit to
    # hold the animal, so dispatch must prefer/require holding units.
    holders = {}
    private = ctx.get("private")
    if private is not None:
        for u_idx, inv in enumerate(private.inventories):
            for item, cnt in (inv or {}).items():
                if cnt > 0:
                    holders.setdefault(item, []).append(u_idx)

    def _eligible(task):
        """Units that could execute this task this turn without a no-op."""
        required_unit = (task.get("meta") or {}).get("required_unit")
        if required_unit is not None:
            try:
                return {int(required_unit)}
            except (TypeError, ValueError):
                return set()
        base_set = None
        if task["op"] == "PLACE" and task.get("args"):
            item = task["args"][0]
            if item in ANIMALS or task.get("kind") == "deposit_product":
                base_set = set(holders.get(item, []))   # empty => defer, don't no-op
        elif task["op"] == "FERTILIZE":
            base_set = set(holders.get("FERTILIZER", []))
        elif task["op"] == "FEED":
            base_set = set(holders.get("WHEAT", []))

        try:
            from config import get_p41_sw_zonal_expansion_enabled, P41_SW_DEDICATED_WORKER_INDICES
            p41_enabled = bool(get_p41_sw_zonal_expansion_enabled())
        except Exception:
            p41_enabled = False
            P41_SW_DEDICATED_WORKER_INDICES = (11, 12)

        if p41_enabled and "SW" in farm.unlocked:
            target = task.get("target")
            if target is not None:
                t_tuple = tuple(target)
                t_quad = farm.quadrant_of(t_tuple)
                prio = task.get("priority", 0)
                is_urgent = prio >= PRIORITY_URGENT_SURVIVAL or task.get("kind") in ("feed_rescue", "harvest_decay")

                # Discretionary SW agricultural tasks: strictly restricted to dedicated workers (11, 12)
                if t_quad == "SW" and t_tuple not in SHED_ACCESS_TILES:
                    if task.get("op") in ("WATER", "PLANT", "TILL", "DIG", "FERTILIZE", "HARVEST"):
                        sw_allowed = {u for u in P41_SW_DEDICATED_WORKER_INDICES if u < n_units}
                        if base_set is not None:
                            return base_set.intersection(sw_allowed)
                        return sw_allowed

                # Discretionary Core agricultural tasks: non-SW workers only (prevent 11, 12 from being pulled into NW/NE)
                elif t_quad in ("NW", "NE") and t_tuple not in SHED_ACCESS_TILES and not is_urgent:
                    if task.get("op") in ("WATER", "PLANT", "TILL", "DIG", "FERTILIZE", "HARVEST"):
                        core_allowed = {u for u in range(n_units) if u not in P41_SW_DEDICATED_WORKER_INDICES}
                        if base_set is not None:
                            return base_set.intersection(core_allowed)
                        return core_allowed

        return base_set

    # Stage 8B Phase 1E / 2B: Adaptive Zonal Dispatch (Dynamic or Rule W1 static fallback)
    try:
        from config import STRATEGIC_SW_OWNERSHIP_ENABLED
        strategic_sw = STRATEGIC_SW_OWNERSHIP_ENABLED
    except Exception:
        strategic_sw = False

    if SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED:
        home_quads = compute_workload_aware_home_quadrants(
            tasks,
            farm,
            n_units,
            pos_by_idx,
            ctx=ctx,
            protect_core_discretionary_before_sw=True,
            exclude_shed_logistics_from_sw=True,
        )
    elif DYNAMIC_ZONAL_ALLOCATION or strategic_sw:
        home_quads = compute_workload_aware_home_quadrants(tasks, farm, n_units, pos_by_idx, ctx=ctx)
    else:
        home_quads = {u_idx: get_home_quadrant(u_idx, n_units, farm.unlocked) for u_idx in range(n_units)}
    sw_units = {u_idx for u_idx, q in home_quads.items() if q == "SW"}

    # Stage 8B Phase 1F: Separate urgent tasks from regular tasks
    urgent_tasks = []
    regular_tasks = []

    for t in tasks:
        tgt = t.get("target") or tuple(farm.farmer)
        t_quad = farm.quadrant_of(tgt)
        if t["op"] not in ("PICKUP", "PASS") and t_quad not in farm.unlocked:
            continue
        prio = t.get("priority", 0)
        # Livestock belongs to its carrier until PLACE completes. A carrier's
        # home-zone backlog must not strand purchased animals indefinitely.
        # Production-day feeding (feed_prod) is globally dispatchable to prevent
        # stranding animals when the only wheat holder is in another quadrant.
        is_delivery = t["op"] == "PLACE" and (t.get("args") or [None])[0] in ANIMALS
        is_product_delivery = (
            t.get("kind") == "deposit_product"
            and prio >= PRIORITY_PRODUCT_DELIVERY_PRESSURE
        )
        is_prod_feed = t.get("kind") == "feed_prod"
        is_urgent = (prio >= PRIORITY_URGENT_SURVIVAL or is_delivery
                     or is_product_delivery or is_prod_feed
                     or t.get("kind") in ("feed_rescue", "harvest_decay", "pickup_wheat"))
        if is_urgent:
            urgent_tasks.append(t)
        else:
            regular_tasks.append(t)

    busy = set()
    assignment = {}          # unit_idx -> task
    deferred_place = []

    # Step 0: Validate active sticky missions
    global _ACTIVE_MISSIONS
    for u, m in list(_ACTIVE_MISSIONS.items()):
        if u >= n_units:
            del _ACTIVE_MISSIONS[u]
            continue
        curr_pos = pos_by_idx[u]
        tgt = m.get("target") or curr_pos
        curr_d = abs(curr_pos[0] - tgt[0]) + abs(curr_pos[1] - tgt[1])
        prev_d = m.get("prev_distance", curr_d)
        m["mission_age"] = m.get("mission_age", 0) + 1
        m["steps_active"] = m.get("steps_active", 0) + 1
        if curr_d < prev_d:
            m["consecutive_no_progress"] = 0
            m["prev_distance"] = curr_d
        else:
            m["consecutive_no_progress"] = m.get("consecutive_no_progress", 0) + 1

        if not _is_mission_valid(m, u, ctx, pos_by_idx, holders, tasks=tasks):
            del _ACTIVE_MISSIONS[u]

    # 1. Tier 1: Urgent survival tasks dispatched immediately to closest capable worker
    for task in sorted(urgent_tasks, key=lambda t: -t.get("priority", 0)):
        eligible = _eligible(task)
        free_units = [u[0] for u in units if u[0] not in busy]
        if eligible is not None:
            free_units = [u for u in free_units if u in eligible]
        if not free_units:
            continue
        target = task.get("target") or tuple(farm.farmer)
        # Prefer free units without an active mission
        non_mission = [u for u in free_units if u not in _ACTIVE_MISSIONS]
        pool = non_mission if non_mission else free_units
        best = min(pool, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        if best in _ACTIVE_MISSIONS:
            del _ACTIVE_MISSIONS[best]  # Preempted by urgent survival task!
        busy.add(best)
        task["unit_pos"] = pos_by_idx[best]
        assignment[best] = task

        # Keep livestock delivery sticky until PLACE succeeds or is invalidated
        if (task.get("op") == "PLACE" and
            task.get("args") and task["args"][0] in ANIMALS and
            pos_by_idx[best] != tuple(task.get("target", (-1, -1)))):
            tgt_pos = task.get("target") or pos_by_idx[best]
            init_d = abs(pos_by_idx[best][0] - tgt_pos[0]) + abs(pos_by_idx[best][1] - tgt_pos[1])
            _ACTIVE_MISSIONS[best] = {
                "task": dict(task),
                "target": task.get("target"),
                "op": task["op"],
                "kind": task.get("kind", ""),
                "args": task.get("args", []),
                "priority": task.get("priority", 0),
                "prev_distance": init_d,
                "consecutive_no_progress": 0,
                "mission_age": 0,
                "steps_active": 0,
            }

    # 1b. Re-assign surviving active missions to their sticky workers
    for u in list(_ACTIVE_MISSIONS.keys()):
        if u not in busy:
            m = _ACTIVE_MISSIONS[u]
            m_task = dict(m["task"])
            m_task["unit_pos"] = pos_by_idx[u]
            assignment[u] = m_task
            busy.add(u)
            for rt in list(regular_tasks):
                if rt.get("op") == m["op"] and tuple(rt.get("target", (-1, -1))) == tuple(m["target"]):
                    regular_tasks.remove(rt)
                    break

    # 2. Tier 2: Regular tasks with C2 Zonal Hierarchy + C6 Clustered Dispatch
    tasks_by_quad = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    for t in regular_tasks:
        tgt = t.get("target") or tuple(farm.farmer)
        q = farm.quadrant_of(tgt)
        tasks_by_quad[q] = tasks_by_quad.get(q, 0) + 1
    unassigned_home_tasks = dict(tasks_by_quad)

    remaining_tasks = list(regular_tasks)

    while remaining_tasks and len(busy) < len(units):
        free_units = [u[0] for u in units if u[0] not in busy]
        if not free_units:
            break

        max_prio = max(t.get("priority", 0) for t in remaining_tasks)
        band_tasks = [t for t in remaining_tasks if t.get("priority", 0) >= max_prio - C6_PRIORITY_BAND]

        best_match = None  # (score, d, target, u, task, target_quad)

        for task in band_tasks:
            eligible = _eligible(task)
            if eligible is not None and not eligible:
                deferred_place.append(task)
                continue
            cands = [u for u in free_units if eligible is None or u in eligible]
            if not cands:
                continue
            target = task.get("target") or tuple(farm.farmer)
            target_quad = farm.quadrant_of(target)
            prio = task.get("priority", 0)

            if not soft_locality_on:
                # C2 Zonal Eligibility (Baseline)
                home_cands = [u for u in cands if home_quads[u] == target_quad]
                if home_cands:
                    eval_cands = [(u, False) for u in home_cands]
                else:
                    eval_cands = []
                    for u in cands:
                        u_home = home_quads[u]
                        free_in_home = sum(1 for fu in free_units if home_quads[fu] == u_home)
                        rem_tasks_home = unassigned_home_tasks.get(u_home, 0)
                        if rem_tasks_home < free_in_home:
                            if not ((u_home == "SW" and target_quad == "NE") or (u_home == "NE" and target_quad == "SW")):
                                d = abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1])
                                if d <= C2_MAX_SPILLOVER_DIST and prio >= C2_SPILLOVER_PRIORITY_FLOOR:
                                    eval_cands.append((u, True))

                for u, is_spillover in eval_cands:
                    d = abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1])
                    cluster_bonus = 0
                    if d <= C6_CLUSTER_RADIUS:
                        cluster_bonus += C6_CLUSTER_BONUS
                    if d == 0:
                        cluster_bonus += C6_CLUSTER_BONUS
                    spill_penalty = 10 if is_spillover else 0
                    effective_score = -prio + spill_penalty + C6_TRAVEL_WEIGHT * (d - cluster_bonus)

                    match_key = (effective_score, d, target, u)
                    if best_match is None or match_key < best_match[0]:
                        best_match = (match_key, u, task, target_quad)
            else:
                # Soft, Workload-Aware Worker Locality (Phase C0 Treatment)
                is_urgent = (
                    prio >= PRIORITY_URGENT_SURVIVAL
                    or task.get("kind") in ("feed_rescue", "harvest_decay", "feed_prod", "pickup_wheat")
                    or (task.get("op") == "PLACE" and (task.get("args") or [None])[0] in ANIMALS)
                )

                free_in_target = sum(1 for fu in free_units if farm.quadrant_of(pos_by_idx[fu]) == target_quad)
                rem_target_tasks = unassigned_home_tasks.get(target_quad, 0)
                target_needs_assistance = (rem_target_tasks > free_in_target)

                for u in cands:
                    u_pos = pos_by_idx[u]
                    u_phys_quad = farm.quadrant_of(u_pos)

                    is_local = (u_phys_quad == target_quad) or (target in SHED_ACCESS_TILES)
                    if is_local:
                        locality_penalty = 0.0
                    else:
                        rem_local_tasks = unassigned_home_tasks.get(u_phys_quad, 0)
                        if is_urgent or rem_local_tasks <= 0:
                            locality_penalty = 0.0
                        elif target_needs_assistance:
                            locality_penalty = 3.0
                        else:
                            locality_penalty = 10.0

                    continuity_bonus = 0.0
                    if u in _ACTIVE_MISSIONS:
                        m = _ACTIVE_MISSIONS[u]
                        if tuple(m.get("target", (-1, -1))) == tuple(target) and m.get("op") == task.get("op"):
                            continuity_bonus = 6.0

                    d = abs(u_pos[0] - target[0]) + abs(u_pos[1] - target[1])
                    cluster_bonus = 0
                    if d <= C6_CLUSTER_RADIUS:
                        cluster_bonus += C6_CLUSTER_BONUS
                    if d == 0:
                        cluster_bonus += C6_CLUSTER_BONUS

                    effective_score = -prio + locality_penalty - continuity_bonus + C6_TRAVEL_WEIGHT * (d - cluster_bonus)

                    match_key = (effective_score, d, target, u)
                    if best_match is None or match_key < best_match[0]:
                        best_match = (match_key, u, task, target_quad)

        if best_match is None:
            for t in band_tasks:
                remaining_tasks.remove(t)
            continue

        _, chosen_u, chosen_task, t_quad = best_match
        busy.add(chosen_u)
        remaining_tasks.remove(chosen_task)
        if t_quad in unassigned_home_tasks:
            unassigned_home_tasks[t_quad] = max(0, unassigned_home_tasks[t_quad] - 1)

        # Rule W2: SW squad hands anchor shed PICKUP at PORT_SW
        if chosen_u in sw_units and chosen_task.get("op") == "PICKUP" and chosen_task.get("target") in SHED_ACCESS_TILES:
            chosen_task["target"] = PORT_SW

        chosen_task["unit_pos"] = pos_by_idx[chosen_u]
        assignment[chosen_u] = chosen_task

        # Record sticky mission if task requires multi-turn travel
        if (chosen_task.get("op") != "PASS" and
            chosen_task.get("kind") not in ("sw_anchor", "fallback_fert", "fallback_water", "fallback_dig") and
            pos_by_idx[chosen_u] != tuple(chosen_task.get("target", (-1, -1)))):
            tgt_pos = chosen_task.get("target") or pos_by_idx[chosen_u]
            init_d = abs(pos_by_idx[chosen_u][0] - tgt_pos[0]) + abs(pos_by_idx[chosen_u][1] - tgt_pos[1])
            _ACTIVE_MISSIONS[chosen_u] = {
                "task": dict(chosen_task),
                "target": chosen_task.get("target"),
                "op": chosen_task["op"],
                "kind": chosen_task.get("kind", ""),
                "args": chosen_task.get("args", []),
                "priority": chosen_task.get("priority", 0),
                "prev_distance": init_d,
                "consecutive_no_progress": 0,
                "mission_age": 0,
                "steps_active": 0,
            }

    # Blocked-task diagnostics: detect tasks blocked before assigning fallback idle work
    turn_blocked_diagnostics = {
        "blocked_due_inventory": 0,
        "blocked_due_zone": 0,
        "blocked_due_no_carrier": 0,
        "blocked_due_capacity": 0,
        "blocked_task_turns": 0,
        "urgent_blocked_turns": 0,
        "max_blocked_duration": 0,
    }
    unassigned_urgent = [t for t in urgent_tasks if t not in assignment.values()]
    unassigned_regular = list(remaining_tasks)
    free_units_count = len(units) - len(busy)

    global _BLOCKED_TASK_TRACKER
    current_turn_blocked_keys = set()
    step = ctx.get("step", 0)

    for t in unassigned_urgent + unassigned_regular:
        op = t.get("op")
        tgt = tuple(t.get("target") or farm.farmer)
        t_quad = farm.quadrant_of(tgt)
        args = tuple(t.get("args") or ())
        prio = t.get("priority", 0)
        kind = t.get("kind", "")

        reason = "zone"
        if op == "PLACE" and args and args[0] in ANIMALS and not holders.get(args[0]):
            reason = "no_carrier"
            turn_blocked_diagnostics["blocked_due_no_carrier"] += 1
        elif kind == "deposit_product" and args and not holders.get(args[0]):
            reason = "inventory"
            turn_blocked_diagnostics["blocked_due_inventory"] += 1
        elif op == "FEED" and not holders.get("WHEAT"):
            reason = "inventory"
            turn_blocked_diagnostics["blocked_due_inventory"] += 1
        elif op == "FERTILIZE" and not holders.get("FERTILIZER"):
            reason = "inventory"
            turn_blocked_diagnostics["blocked_due_inventory"] += 1
        elif t_quad not in farm.unlocked:
            reason = "zone"
            turn_blocked_diagnostics["blocked_due_zone"] += 1
        elif free_units_count == 0:
            reason = "capacity"
            turn_blocked_diagnostics["blocked_due_capacity"] += 1
        else:
            reason = "zone"
            turn_blocked_diagnostics["blocked_due_zone"] += 1

        is_urgent = (
            prio >= PRIORITY_URGENT_SURVIVAL or
            kind in ("feed_rescue", "feed_prod", "harvest_decay") or
            (kind == "deposit_product" and prio >= PRIORITY_PRODUCT_DELIVERY_PRESSURE) or
            (op == "WATER" and (prio >= 80 or t.get("meta", {}).get("urgent", False))) or
            (op == "PLACE" and args and args[0] in ANIMALS)
        )

        task_key = (op, tgt, args)
        current_turn_blocked_keys.add(task_key)

        if task_key not in _BLOCKED_TASK_TRACKER:
            _BLOCKED_TASK_TRACKER[task_key] = {
                "first_blocked_step": step,
                "consecutive_duration": 1,
                "max_blocked_duration": 1,
                "reason": reason,
                "kind": kind,
                "priority": prio,
                "quadrant": t_quad,
                "is_urgent": is_urgent,
            }
        else:
            info = _BLOCKED_TASK_TRACKER[task_key]
            info["consecutive_duration"] += 1
            info["max_blocked_duration"] = max(info["max_blocked_duration"], info["consecutive_duration"])
            info["reason"] = reason
            info["priority"] = max(info["priority"], prio)
            if is_urgent:
                info["is_urgent"] = True

    # Auto-clear tasks that were completed, assigned, or disappeared
    for k in list(_BLOCKED_TASK_TRACKER.keys()):
        if k not in current_turn_blocked_keys:
            del _BLOCKED_TASK_TRACKER[k]

    turn_blocked_diagnostics["blocked_task_turns"] = sum(
        info["consecutive_duration"] for info in _BLOCKED_TASK_TRACKER.values()
    )
    turn_blocked_diagnostics["max_blocked_duration"] = max(
        (info["consecutive_duration"] for info in _BLOCKED_TASK_TRACKER.values()),
        default=0
    )
    turn_blocked_diagnostics["urgent_blocked_turns"] = sum(
        info["consecutive_duration"]
        for info in _BLOCKED_TASK_TRACKER.values()
        if info.get("is_urgent")
    )

    # v5.9: Fallback assignment for idle units to guarantee zero wasted actions
    # Default fallback priority: COLLECT_FERTILIZER -> WATER_MATURE/UNWATERED -> DIG_WEED
    unassigned_units = [idx for idx, _ in units if idx not in busy]
    if unassigned_units:
        targeted_positions = {tuple(t["target"]) for t in assignment.values() if t.get("target")}

        def _pick_best_unit(cands, target_pos):
            return min(cands, key=lambda u: abs(pos_by_idx[u][0] - target_pos[0]) + abs(pos_by_idx[u][1] - target_pos[1]))

        # 1. Fallback: collect any available fertilizer (prefer local home zone)
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_animal and t.fertilizer_available and tuple(t.pos) not in targeted_positions:
                t_quad = farm.quadrant_of(t.pos)
                pref = [u for u in unassigned_units if (farm.quadrant_of(pos_by_idx[u]) if soft_locality_on else home_quads[u]) == t_quad]
                cands = pref if pref else [u for u in unassigned_units if not ((home_quads[u] == "SW" and t_quad == "NE") or (home_quads[u] == "NE" and t_quad == "SW"))]
                if not cands: cands = unassigned_units
                best_u = _pick_best_unit(cands, t.pos)
                unassigned_units.remove(best_u)
                busy.add(best_u)
                assignment[best_u] = {"priority": 10, "op": "COLLECT_FERTILIZER", "target": tuple(t.pos),
                                      "args": [], "kind": "fallback_fert", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                targeted_positions.add(tuple(t.pos))

        # 2. Fallback: water any mature or unwatered crop (prefer local home zone)
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_plant and not t.watered_today and tuple(t.pos) not in targeted_positions:
                t_quad = farm.quadrant_of(t.pos)
                pref = [u for u in unassigned_units if (farm.quadrant_of(pos_by_idx[u]) if soft_locality_on else home_quads[u]) == t_quad]
                cands = pref if pref else [u for u in unassigned_units if not ((home_quads[u] == "SW" and t_quad == "NE") or (home_quads[u] == "NE" and t_quad == "SW"))]
                if not cands: cands = unassigned_units
                best_u = _pick_best_unit(cands, t.pos)
                unassigned_units.remove(best_u)
                busy.add(best_u)
                assignment[best_u] = {"priority": 10, "op": "WATER", "target": tuple(t.pos),
                                      "args": [], "kind": "fallback_water", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                targeted_positions.add(tuple(t.pos))

        # 3. Fallback: dig any weed on unlocked land (prefer local home zone)
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.kind == "WEED" and farm.quadrant_of(t.pos) in farm.unlocked and tuple(t.pos) not in targeted_positions:
                t_quad = farm.quadrant_of(t.pos)
                pref = [u for u in unassigned_units if (farm.quadrant_of(pos_by_idx[u]) if soft_locality_on else home_quads[u]) == t_quad]
                cands = pref if pref else [u for u in unassigned_units if not ((home_quads[u] == "SW" and t_quad == "NE") or (home_quads[u] == "NE" and t_quad == "SW"))]
                if not cands: cands = unassigned_units
                best_u = _pick_best_unit(cands, t.pos)
                unassigned_units.remove(best_u)
                busy.add(best_u)
                assignment[best_u] = {"priority": 5, "op": "DIG", "target": tuple(t.pos),
                                      "args": [], "kind": "fallback_dig", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                targeted_positions.add(tuple(t.pos))

        # Rule W2 anchor: Send remaining idle SW squad hands to PORT_SW
        if sw_units:
            for u in list(unassigned_units):
                if u in sw_units:
                    pos = pos_by_idx[u]
                    if pos != PORT_SW:
                        task = {"priority": 1, "op": "PASS", "target": PORT_SW,
                                 "args": [], "kind": "sw_anchor", "meta": {}, "unit_pos": pos}
                        assignment[u] = task
                        busy.add(u)
                        unassigned_units.remove(u)

    actions = {idx: ["PASS"] for idx in range(len(units))}
    for idx, task in assignment.items():
        actions[idx] = emit(task)

    turn_sw_tasks_created = 0
    if farm and hasattr(farm, "quadrant_of"):
        for t in tasks:
            tgt = t.get("target")
            if tgt and farm.quadrant_of(tgt) == "SW":
                turn_sw_tasks_created += 1

    turn_sw_tasks_assigned = 0
    turn_sw_tasks_completed = 0
    turn_sw_moves = 0
    turn_sw_ops = 0
    if farm and hasattr(farm, "quadrant_of"):
        for u_idx, task in assignment.items():
            tgt = task.get("target")
            if tgt and farm.quadrant_of(tgt) == "SW":
                turn_sw_tasks_assigned += 1
                act = actions.get(u_idx, ["PASS"])
                if act and act[0] in ("NORTH", "SOUTH", "EAST", "WEST"):
                    turn_sw_moves += 1
                elif act != ["PASS"] and act:
                    turn_sw_ops += 1
                    turn_sw_tasks_completed += 1

    turn_sw_telemetry = {
        "created": turn_sw_tasks_created,
        "assigned": turn_sw_tasks_assigned,
        "completed": turn_sw_tasks_completed,
        "moves": turn_sw_moves,
        "ops": turn_sw_ops,
    }

    # v5.9: Track utilization across all 24 hours of the day
    _record_turn_utilization(
        ctx, len(units), actions,
        assignment=assignment,
        turn_blocked=turn_blocked_diagnostics,
        turn_sw=turn_sw_telemetry,
        home_quads=home_quads,
        pos_by_idx=pos_by_idx,
    )

    # Bookkeeping: PLANT intents count as seed reservations whether or not the
    # unit is standing on the tile yet (seeds are consumed only on execution,
    # but the atomic all-or-nothing rule counts REQUESTS this turn).
    plant_intents = {}
    watered_now, harvested, fed_animals = [], [], []
    executed_plants = {}
    for task in assignment.values():
        if task["op"] == "PLANT":
            crop = task["args"][0] if task.get("args") else None
            if crop:
                plant_intents[crop] = plant_intents.get(crop, 0) + 1
                if task["unit_pos"] == tuple(task["target"]):
                    executed_plants[crop] = executed_plants.get(crop, 0) + 1
        elif task["op"] == "WATER":
            watered_now.append(task["target"])
        elif task["op"] == "HARVEST":
            harvested.append(task["target"])
        elif task["op"] == "FEED":
            fed_animals.append(task["target"])
    return {
        "actions": actions,
        "assignment": assignment,
        "plant_intents": plant_intents,
        "executed_plants": executed_plants,
        "watered_now": watered_now,
        "harvested": harvested,
        "fed": fed_animals,
        "deferred_place": [(t.get("args") or [None])[0] for t in deferred_place],
        "blocked_diagnostics": turn_blocked_diagnostics,
    }


def emit(task):
    """Move toward target or execute op when standing on it."""
    op = task["op"]
    target = task.get("target")
    pos = tuple(task.get("unit_pos", (4, 4)))

    if target is not None and pos != tuple(target):
        move = bfs_first_step(pos, tuple(target))
        if move is not None:
            return [move]
        # already adjacent-but-unreachable case shouldn't happen on open grid

    if op == "PICKUP":
        return ["PICKUP", *task.get("args", [])]
    if op == "PLACE":
        return ["PLACE", *task.get("args", [])]
    if task.get("args"):
        return [op, *task["args"]]
    return [op]


def estimate_daily_load(ctx):
    """Travel-aware daily action-count load estimation.

    Incorporates:
      - Base service load (watering, feeding, caring, fertilizing, harvesting, planting)
      - Spatial dispersion across unlocked quadrants
      - Quadrant transitions and diagonal penalties
      - Shed transit overhead for pickups and drop-offs
      - SW quadrant distance burden (long-distance transit from (4,4))
    """
    farm = ctx.get("farm")
    if farm is None or not hasattr(farm, "iter_tiles"):
        return 0
    day = ctx.get("day", 0)
    private = ctx.get("private")

    base_load = 0
    active_quads = set()
    sw_tile_count = 0

    # 1. Base tile load + spatial distribution
    for t in farm.iter_tiles():
        q = farm.quadrant_of(t.pos)
        if q not in farm.unlocked:
            continue
        if t.is_plant:
            active_quads.add(q)
            if q == "SW":
                sw_tile_count += 1
            base_load += 1 if not getattr(t, "watered_today", False) else 0
            if getattr(t, "yield_units", 0) > 0:
                base_load += 1
        elif t.is_animal:
            active_quads.add(q)
            if q == "SW":
                sw_tile_count += 1
            base_load += 1 if not getattr(t, "fed_today", False) else 0
            if getattr(t, "fertilizer_available", False):
                base_load += 1
            if not getattr(t, "cared_today", False):
                base_load += 1
            info = ANIMALS.get(t.animal)
            if info and getattr(t, "placed_day", None) is not None:
                if (day + 1 - t.placed_day - info["first_yield_day"]) % info["interval"] == 0:
                    base_load += 1

    # Empty unlocked tiles ready for planting
    seed_units = sum(private.seeds.values()) if private and hasattr(private, "seeds") else 0
    empty_unlocked = sum(
        1 for t in farm.iter_tiles()
        if t.kind == "EMPTY" and farm.quadrant_of(t.pos) in farm.unlocked
    )
    plants_to_do = min(seed_units, empty_unlocked)
    base_load += plants_to_do

    # 2. Shed trips overhead (pickups of feed, fertilizer, or placing animals)
    shed_trips = 0
    if private and hasattr(private, "shed"):
        shed = private.shed
        shed_animals = sum(int(shed.get(a, 0)) for a in ANIMAL_LIST)
        shed_trips += shed_animals * 3
        if int(shed.get("WHEAT", 0)) > 0:
            shed_trips += 3
        if int(shed.get("FERTILIZER", 0)) > 0:
            shed_trips += 3

    # 3. Spatial dispersion & quadrant transitions
    dispersion_burden = 0
    if len(active_quads) > 1:
        dispersion_burden = (len(active_quads) - 1) * 4
        if "SW" in active_quads and "NE" in active_quads:
            dispersion_burden += 4

    # 4. SW distance burden: one-time quadrant setup + clustered intra-quadrant dispersion
    # Clustered tiles do not incur round-trip overhead per tile; dispersion within SW is sub-linear.
    sw_burden = (6 + min(8, sw_tile_count // 3)) if sw_tile_count > 0 else 0

    return base_load + shed_trips + dispersion_burden + sw_burden
