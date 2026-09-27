"""Core-First SW Task Admission Controller (Phase SW-B3B).

Provides a configurable experimental gate (SW_CORE_FIRST_TASK_ADMISSION) to
prevent SW operations from consuming worker execution capacity that is needed
for urgent NW/NE or livestock obligations.

When enabled:
- Evaluates actual current farm execution state and near-term core commitments.
- Protects animal feeding deadlines, core crop watering windows, mature/decaying
  harvests, and essential worker/shed logistics.
- Allows SW work only when core workload is adequately covered with spare capacity.
- Accurately records task proposals, admissions, deferrals, and exact reasons.
- Preserves the 8-tile SW tranche invariant.
- Re-evaluates deferred tasks dynamically on future turns.
"""
from __future__ import annotations

import copy
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# Bidirectional module aliasing for singleton consistency across import styles
_mod_name = __name__
if _mod_name.startswith("agent."):
    _bare_name = _mod_name[6:]
    sys.modules.setdefault(_bare_name, sys.modules[_mod_name])
    _pkg_parts = _bare_name.split(".")
    if len(_pkg_parts) > 1 and _pkg_parts[0] in sys.modules:
        setattr(sys.modules[_pkg_parts[0]], _pkg_parts[1], sys.modules[_mod_name])
else:
    _agent_name = f"agent.{_mod_name}"
    sys.modules.setdefault(_agent_name, sys.modules[_mod_name])
    _pkg_parts = _mod_name.split(".")
    _agent_pkg = f"agent.{_pkg_parts[0]}"
    if "agent" in sys.modules:
        if _agent_pkg not in sys.modules and _pkg_parts[0] in sys.modules:
            sys.modules[_agent_pkg] = sys.modules[_pkg_parts[0]]
        if _agent_pkg in sys.modules:
            setattr(sys.modules[_agent_pkg], _pkg_parts[1], sys.modules[_mod_name])
            setattr(sys.modules["agent"], _pkg_parts[0], sys.modules[_agent_pkg])

logger = logging.getLogger(__name__)

# Shared infrastructure shed access tiles
SHED_ACCESS_TILES: Set[Tuple[int, int]] = {(4, 4), (4, 5), (5, 4)}

# Deferral Reason Constants
REASON_UNAUTHORIZED_SW_TILE = "UNAUTHORIZED_SW_TILE"
REASON_UNASSIGNED_CORE_HARD_TASK = "UNASSIGNED_CORE_HARD_TASK"
REASON_UNASSIGNED_CORE_STANDARD_TASK = "UNASSIGNED_CORE_STANDARD_TASK"
REASON_CORE_WORKER_DEFICIT = "CORE_WORKER_DEFICIT"
REASON_NEAR_TERM_CORE_CAPACITY_DEFICIT = "NEAR_TERM_CORE_CAPACITY_DEFICIT"
REASON_LATE_DAY_TRANSIT_OVERHEAD = "LATE_DAY_TRANSIT_OVERHEAD"
REASON_ADMITTED = "ADMITTED"


@dataclass
class SWTaskAdmissionTelemetry:
    """Rigorous telemetry for Core-First SW Task Admission."""
    sw_tasks_proposed: int = 0
    sw_tasks_admitted: int = 0
    sw_tasks_deferred: int = 0
    sw_candidate_evaluations_proposed: int = 0
    sw_candidate_evaluations_admitted: int = 0
    sw_candidate_evaluations_deferred: int = 0
    deferral_reasons: Dict[str, int] = field(default_factory=dict)

    # Core HARD commitment tracking
    core_hard_tasks_due: int = 0
    core_hard_tasks_completed: int = 0
    missed_core_deadlines: int = 0

    # Regional execution counts
    core_water_executed: int = 0
    sw_water_executed: int = 0
    core_harvest_executed: int = 0
    sw_harvest_executed: int = 0
    core_plant_executed: int = 0
    sw_plant_executed: int = 0

    # SW Productive Tile Utilization: (x, y) -> {planted_steps, water_count, harvest_count}
    sw_tile_utilization: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def record_candidate_evaluation(self, admitted: bool, reason: str) -> None:
        self.sw_candidate_evaluations_proposed += 1
        if admitted:
            self.sw_candidate_evaluations_admitted += 1
        else:
            self.sw_candidate_evaluations_deferred += 1
            self.deferral_reasons[reason] = self.deferral_reasons.get(reason, 0) + 1

    def record_task_deferred(self, reason: str) -> None:
        self.sw_tasks_proposed += 1
        self.sw_tasks_deferred += 1
        self.deferral_reasons[reason] = self.deferral_reasons.get(reason, 0) + 1

    def record_task_admitted(self) -> None:
        self.sw_tasks_proposed += 1
        self.sw_tasks_admitted += 1

    def record_executed_action(self, region: str, op: str, pos: Tuple[int, int], outcome: Optional[Dict[str, Any]] = None) -> None:
        is_sw = (region == "SW")
        if op == "WATER":
            if is_sw:
                self.sw_water_executed += 1
                pos_str = f"({pos[0]},{pos[1]})"
                u = self.sw_tile_utilization.setdefault(pos_str, {"water_count": 0, "harvest_count": 0, "plant_count": 0})
                u["water_count"] += 1
            else:
                self.core_water_executed += 1
        elif op == "HARVEST":
            if is_sw:
                self.sw_harvest_executed += 1
                pos_str = f"({pos[0]},{pos[1]})"
                u = self.sw_tile_utilization.setdefault(pos_str, {"water_count": 0, "harvest_count": 0, "plant_count": 0})
                u["harvest_count"] += 1
            else:
                self.core_harvest_executed += 1
        elif op == "PLANT":
            if is_sw:
                self.sw_plant_executed += 1
                pos_str = f"({pos[0]},{pos[1]})"
                u = self.sw_tile_utilization.setdefault(pos_str, {"water_count": 0, "harvest_count": 0, "plant_count": 0})
                u["plant_count"] += 1
            else:
                self.core_plant_executed += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sw_tasks_proposed": self.sw_tasks_proposed,
            "sw_tasks_admitted": self.sw_tasks_admitted,
            "sw_tasks_deferred": self.sw_tasks_deferred,
            "sw_candidate_evaluations_proposed": self.sw_candidate_evaluations_proposed,
            "sw_candidate_evaluations_admitted": self.sw_candidate_evaluations_admitted,
            "sw_candidate_evaluations_deferred": self.sw_candidate_evaluations_deferred,
            "deferral_reasons": dict(self.deferral_reasons),
            "core_hard_tasks_due": self.core_hard_tasks_due,
            "core_hard_tasks_completed": self.core_hard_tasks_completed,
            "missed_core_deadlines": self.missed_core_deadlines,
            "core_water_executed": self.core_water_executed,
            "sw_water_executed": self.sw_water_executed,
            "core_harvest_executed": self.core_harvest_executed,
            "sw_harvest_executed": self.sw_harvest_executed,
            "core_plant_executed": self.core_plant_executed,
            "sw_plant_executed": self.sw_plant_executed,
            "sw_tile_utilization": copy.deepcopy(self.sw_tile_utilization),
        }


# Singleton Telemetry State
_TELEMETRY = SWTaskAdmissionTelemetry()


def get_sw_task_admission_telemetry() -> SWTaskAdmissionTelemetry:
    """Return active SW task admission telemetry instance."""
    global _TELEMETRY
    return _TELEMETRY


def reset_sw_task_admission_telemetry() -> None:
    """Reset telemetry to initial state."""
    global _TELEMETRY
    _TELEMETRY = SWTaskAdmissionTelemetry()


def is_sw_agricultural_task(task: Dict[str, Any], farm: Any) -> bool:
    """Determine whether task is an SW agricultural operation (excluding shed access)."""
    target = task.get("target")
    if target is None:
        return False
    t_tuple = (int(target[0]), int(target[1]))
    if t_tuple in SHED_ACCESS_TILES:
        return False
    if hasattr(farm, "quadrant_of"):
        return farm.quadrant_of(t_tuple) == "SW"
    return (t_tuple[0] < 5 and t_tuple[1] >= 5)


def is_core_task(task: Dict[str, Any], farm: Any) -> bool:
    """Determine whether task belongs to Core farm (NW/NE) or shared shed logistics."""
    return not is_sw_agricultural_task(task, farm)


def evaluate_sw_task_admission(
    ctx: Dict[str, Any],
    worker_idx: int,
    worker_pos: Tuple[int, int],
    task: Dict[str, Any],
    current_assignments: Dict[int, Dict[str, Any]],
    remaining_free_units: List[int],
    all_tasks: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Evaluate whether an SW agricultural task should be admitted to a worker.

    Returns:
        (can_admit: bool, reason: str)
    """
    farm = ctx.get("farm")
    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)
    step = ctx.get("step", day * 24 + hour)

    target = task.get("target")
    if target is None:
        return False, "NO_TARGET"
    t_pos = (int(target[0]), int(target[1]))

    # Gate 1: Check Tranche Invariant (must be in admitted 8-tile SW tranche)
    try:
        from strategy.sw_tranche_controller import get_sw_tranche_controller
        ctrl = get_sw_tranche_controller()
        if ctrl.is_treatment_active() and ctrl.state.sw_purchase_approved:
            if t_pos not in ctrl.state.admitted_sw_tiles:
                return False, REASON_UNAUTHORIZED_SW_TILE
    except Exception:
        pass

    # Gather assigned task targets to identify what has already been covered
    assigned_targets = set()
    for asg_task in current_assignments.values():
        tgt = asg_task.get("target")
        if tgt is not None:
            assigned_targets.add(tuple(tgt))

    # Gate 2: Check Immediate Unassigned Core HARD Tasks
    for t in all_tasks:
        if is_core_task(t, farm):
            tgt = t.get("target")
            if tgt is not None and tuple(tgt) in assigned_targets:
                continue
            prio = t.get("priority", 0)
            kind = t.get("kind", "")
            is_hard = (
                prio >= 100  # PRIORITY_URGENT_SURVIVAL
                or kind in ("feed_rescue", "harvest_decay", "feed_prod", "pickup_wheat")
                or (t.get("op") == "PLACE" and (t.get("args") or [None])[0] in ("COW", "SHEEP", "CHICKEN"))
            )
            if is_hard:
                return False, REASON_UNASSIGNED_CORE_HARD_TASK

    # Gate 3: Check Immediate Unassigned Core STANDARD Tasks
    unassigned_core_standard = []
    for t in all_tasks:
        if is_core_task(t, farm):
            tgt = t.get("target")
            if tgt is not None and tuple(tgt) in assigned_targets:
                continue
            if t.get("op") in ("WATER", "HARVEST", "FEED", "PICKUP"):
                unassigned_core_standard.append(t)

    is_worker_in_core = (worker_pos[0] >= 5 or worker_pos[1] < 5)
    if is_worker_in_core and unassigned_core_standard:
        # Worker is physically in Core while Core standard obligations await workers
        return False, REASON_UNASSIGNED_CORE_STANDARD_TASK

    if not is_worker_in_core and unassigned_core_standard:
        # Worker is in SW: check if Core has enough free workers in Core to take them
        free_core_workers = 0
        if farm:
            for u in remaining_free_units:
                # Approximate position or quadrant
                pos = None
                if u == 0:
                    pos = tuple(farm.farmer)
                elif hasattr(farm, "hands") and u - 1 < len(farm.hands):
                    pos = tuple(farm.hands[u - 1])
                if pos and (pos[0] >= 5 or pos[1] < 5):
                    free_core_workers += 1
        if free_core_workers < len(unassigned_core_standard):
            return False, REASON_CORE_WORKER_DEFICIT

    # Gate 4: Near-Term Core Capacity Horizon Check (Day remaining capacity)
    rem_hours = max(1, 24 - hour)
    macro = ctx.get("plan") or ctx.get("macro")

    # Count remaining core unwatered plants
    core_unwatered = 0
    core_mature_harvest = 0
    if farm and hasattr(farm, "iter_tiles"):
        for tile in farm.iter_tiles():
            pos = tuple(tile.pos)
            is_tile_core = (pos[0] >= 5 or pos[1] < 5)
            if not is_tile_core:
                continue
            if tile.is_plant:
                if not tile.watered_today and pos not in assigned_targets:
                    core_unwatered += 1
                if tile.yield_units > 0 and pos not in assigned_targets:
                    # Check maturity
                    core_mature_harvest += 1

    # Count remaining unfed animals
    core_unfed_animals = 0
    if farm and hasattr(farm, "iter_tiles"):
        for tile in farm.iter_tiles():
            if tile.is_animal:
                pos = tuple(tile.pos)
                if not tile.fed_today and pos not in assigned_targets:
                    core_unfed_animals += 1

    actions_needed = (
        (core_unwatered * 2.0)
        + (core_mature_harvest * 2.0)
        + (core_unfed_animals * 2.5)
    )

    if actions_needed > 0:
        total_workers = 1 + (len(farm.hands) if (farm and hasattr(farm, "hands")) else 0)
        core_workers_available = max(1, total_workers - 1)
        core_capacity_actions = core_workers_available * rem_hours
        required_buffered_capacity = actions_needed * 1.25 + 2.0
        if core_capacity_actions < required_buffered_capacity:
            return False, REASON_NEAR_TERM_CORE_CAPACITY_DEFICIT

    # Gate 5: Late-Day Long-Distance Commute Overhead Protection
    dist_to_sw = abs(worker_pos[0] - t_pos[0]) + abs(worker_pos[1] - t_pos[1])
    if is_worker_in_core and dist_to_sw >= 5 and hour >= 18:
        return False, REASON_LATE_DAY_TRANSIT_OVERHEAD

    return True, REASON_ADMITTED
