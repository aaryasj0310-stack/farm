"""Urgency-Aware SW Task Admission Controller (Phase SW-B3C).

Provides configurable experimental gates for SW Task Admission:
- SW_URGENCY_AWARE_ADMISSION (Phase SW-B3C Treatment, Arm D):
  Evaluates 3-tier task hierarchy (Tier 0 Survival/HARD, Tier 1 Deadline-Sensitive,
  Tier 2 Routine/Postponable). Preserves core survival obligations while enabling
  bounded, commitment-aware SW agricultural operations and preventing ping-pong
  mission cancellation during travel.
- SW_CORE_FIRST_TASK_ADMISSION (Phase SW-B3B Baseline, Arm C):
  Original strict core-first admission policy.
- When both are False:
  Admission is completely bypassed (original Gate 2 LIVE SW, Arm B).
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
REASON_INSUFFICIENT_HORIZON_FOR_COMMITMENT = "INSUFFICIENT_HORIZON_FOR_COMMITMENT"
REASON_ADMITTED = "ADMITTED"


@dataclass
class HardObligationRecord:
    task_id: str
    op: str
    pos: Tuple[int, int]
    entity: str
    day: int
    hour: int
    deadline_step: int
    assigned_worker: Optional[int] = None
    emitted: bool = False
    completed_step: Optional[int] = None
    status: str = "PENDING"  # PENDING, COMPLETED, MISSED, INVALIDATED, SUPERSEDED
    terminal_reason: Optional[str] = None


@dataclass
class SWTaskLifecycleRecord:
    task_id: str
    step: int
    day: int
    hour: int
    op: str
    pos: Tuple[int, int]
    item: Optional[str] = None
    priority: float = 0.0
    disposition: Optional[str] = None  # "REJECTED_BY_GATE", "SELECTED_AND_ASSIGNED", "ELIGIBLE_UNSELECTED"
    reason: Optional[str] = None
    executed: bool = False
    completed_step: Optional[int] = None


@dataclass
class SWTaskAdmissionTelemetry:
    """Rigorous telemetry for SW Task Admission (Core-First & Urgency-Aware)."""

    # Unique task proposals & outcomes
    sw_tasks_proposed: int = 0
    sw_tasks_admitted: int = 0
    sw_tasks_deferred: int = 0
    sw_tasks_eligible_unselected: int = 0
    task_deferral_reasons: Dict[str, int] = field(default_factory=dict)
    sw_lifecycle_records: Dict[str, SWTaskLifecycleRecord] = field(default_factory=dict)

    # Candidate-level evaluations & outcomes
    sw_candidate_evaluations_proposed: int = 0
    sw_candidate_evaluations_admitted: int = 0
    sw_candidate_evaluations_deferred: int = 0
    candidate_deferral_reasons: Dict[str, int] = field(default_factory=dict)

    # Core HARD commitment & deadline tracking
    hard_obligations: Dict[str, HardObligationRecord] = field(default_factory=dict)
    core_hard_tasks_due: int = 0
    core_hard_tasks_completed: int = 0
    missed_core_deadlines: int = 0
    core_hard_tasks_invalidated: int = 0
    core_hard_tasks_superseded: int = 0
    hard_tasks_by_op: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        "WATER": {"due": 0, "completed": 0, "missed": 0, "invalidated": 0, "superseded": 0},
        "FEED": {"due": 0, "completed": 0, "missed": 0, "invalidated": 0, "superseded": 0},
        "HARVEST": {"due": 0, "completed": 0, "missed": 0, "invalidated": 0, "superseded": 0},
        "OTHER": {"due": 0, "completed": 0, "missed": 0, "invalidated": 0, "superseded": 0},
    })

    # Commands emitted (before engine step)
    core_commands_emitted: int = 0
    sw_commands_emitted: int = 0
    attempted_harvest_sw: int = 0
    attempted_water_sw: int = 0
    attempted_plant_sw: int = 0
    attempted_feed_sw: int = 0
    attempted_harvest_core: int = 0
    attempted_water_core: int = 0
    attempted_plant_core: int = 0
    attempted_feed_core: int = 0

    # Actions executed (engine-confirmed)
    core_actions_executed: int = 0
    sw_actions_executed: int = 0
    core_water_executed: int = 0
    sw_water_executed: int = 0
    core_harvest_executed: int = 0
    sw_harvest_executed: int = 0
    core_plant_executed: int = 0
    sw_plant_executed: int = 0
    core_feed_executed: int = 0
    sw_feed_executed: int = 0
    sw_weed_executed: int = 0
    harvested_crop_units_sw: Dict[str, int] = field(default_factory=lambda: {
        "WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0
    })

    # SW Productive Tile Utilization: (x, y) -> {water_count, harvest_count, plant_count}
    sw_tile_utilization: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def record_sw_task_lifecycle_start(
        self,
        task_id: str,
        step: int,
        day: int,
        hour: int,
        op: str,
        pos: Tuple[int, int],
        item: Optional[str] = None,
        priority: float = 0.0,
    ) -> None:
        if task_id not in self.sw_lifecycle_records:
            self.sw_tasks_proposed += 1
            self.sw_lifecycle_records[task_id] = SWTaskLifecycleRecord(
                task_id=task_id,
                step=step,
                day=day,
                hour=hour,
                op=op,
                pos=pos,
                item=item,
                priority=priority,
            )

    def record_sw_task_disposition(
        self,
        task_id: str,
        disposition: str,
        reason: Optional[str] = None,
    ) -> None:
        if task_id in self.sw_lifecycle_records:
            rec = self.sw_lifecycle_records[task_id]
            if rec.disposition == "SELECTED_AND_ASSIGNED":
                return
            rec.disposition = disposition
            rec.reason = reason
        else:
            self.sw_tasks_proposed += 1
            rec = SWTaskLifecycleRecord(
                task_id=task_id,
                step=0,
                day=0,
                hour=0,
                op="",
                pos=(0, 0),
                disposition=disposition,
                reason=reason,
            )
            self.sw_lifecycle_records[task_id] = rec

        if disposition == "SELECTED_AND_ASSIGNED":
            self.sw_tasks_admitted += 1
        elif disposition == "REJECTED_BY_GATE":
            self.sw_tasks_deferred += 1
            if reason:
                self.task_deferral_reasons[reason] = self.task_deferral_reasons.get(reason, 0) + 1
        elif disposition == "ELIGIBLE_UNSELECTED":
            self.sw_tasks_eligible_unselected += 1

    def record_task_proposed(self) -> None:
        self.sw_tasks_proposed += 1

    def record_task_admitted(self) -> None:
        self.sw_tasks_admitted += 1

    def record_task_deferred(self, reason: str) -> None:
        self.sw_tasks_deferred += 1
        self.task_deferral_reasons[reason] = self.task_deferral_reasons.get(reason, 0) + 1

    def record_candidate_evaluation(self, admitted: bool, reason: str) -> None:
        self.sw_candidate_evaluations_proposed += 1
        if admitted:
            self.sw_candidate_evaluations_admitted += 1
        else:
            self.sw_candidate_evaluations_deferred += 1
            self.candidate_deferral_reasons[reason] = self.candidate_deferral_reasons.get(reason, 0) + 1

    def register_core_hard_obligation(
        self,
        task_id: str,
        op: str,
        pos: Tuple[int, int],
        entity: str,
        day: int,
        hour: int,
        deadline_step: int,
    ) -> bool:
        if task_id in self.hard_obligations:
            return False
        rec = HardObligationRecord(
            task_id=task_id,
            op=op,
            pos=pos,
            entity=entity,
            day=day,
            hour=hour,
            deadline_step=deadline_step,
            status="PENDING",
        )
        self.hard_obligations[task_id] = rec
        self.core_hard_tasks_due += 1
        cat = op if op in self.hard_tasks_by_op else "OTHER"
        self.hard_tasks_by_op[cat]["due"] += 1
        return True

    def record_hard_obligation_assigned(self, task_id: str, worker_id: int) -> None:
        if task_id in self.hard_obligations:
            self.hard_obligations[task_id].assigned_worker = worker_id

    def record_hard_obligation_emitted(self, task_id: str) -> None:
        if task_id in self.hard_obligations:
            self.hard_obligations[task_id].emitted = True

    def record_hard_obligation_executed(
        self,
        op: str,
        pos: Tuple[int, int],
        step: int,
        outcome: Optional[Dict[str, Any]] = None,
    ) -> None:
        pos_tuple = (int(pos[0]), int(pos[1]))
        for rec in self.hard_obligations.values():
            if rec.status == "PENDING" and rec.op == op and (int(rec.pos[0]), int(rec.pos[1])) == pos_tuple:
                if step <= rec.deadline_step:
                    confirmed = True
                    if outcome is not None:
                        if op == "FEED":
                            confirmed = bool(outcome.get("fed", False))
                        elif op == "WATER":
                            confirmed = bool(outcome.get("watered", False))
                        elif op == "HARVEST":
                            confirmed = (outcome.get("yield_units", 0) > 0)
                    if confirmed:
                        rec.status = "COMPLETED"
                        rec.completed_step = step
                        self.core_hard_tasks_completed += 1
                        cat = op if op in self.hard_tasks_by_op else "OTHER"
                        self.hard_tasks_by_op[cat]["completed"] += 1
                        break

    def invalidate_hard_obligation_at_pos(self, op: str, pos: Tuple[int, int], reason: str = "") -> None:
        pos_tuple = (int(pos[0]), int(pos[1]))
        for rec in self.hard_obligations.values():
            if rec.status == "PENDING" and rec.op == op and (int(rec.pos[0]), int(rec.pos[1])) == pos_tuple:
                rec.status = "INVALIDATED"
                rec.terminal_reason = reason
                self.core_hard_tasks_invalidated += 1
                cat = op if op in self.hard_tasks_by_op else "OTHER"
                if "invalidated" in self.hard_tasks_by_op[cat]:
                    self.hard_tasks_by_op[cat]["invalidated"] += 1
                break

    def supersede_hard_obligation_at_pos(self, op: str, pos: Tuple[int, int], reason: str = "") -> None:
        pos_tuple = (int(pos[0]), int(pos[1]))
        for rec in self.hard_obligations.values():
            if rec.status == "PENDING" and rec.op == op and (int(rec.pos[0]), int(rec.pos[1])) == pos_tuple:
                rec.status = "SUPERSEDED"
                rec.terminal_reason = reason
                self.core_hard_tasks_superseded += 1
                cat = op if op in self.hard_tasks_by_op else "OTHER"
                if "superseded" in self.hard_tasks_by_op[cat]:
                    self.hard_tasks_by_op[cat]["superseded"] += 1
                break

    def reconcile_hard_deadlines(self, current_step: int) -> None:
        for rec in self.hard_obligations.values():
            if rec.status == "PENDING" and current_step > rec.deadline_step:
                rec.status = "MISSED"
                self.missed_core_deadlines += 1
                cat = rec.op if rec.op in self.hard_tasks_by_op else "OTHER"
                self.hard_tasks_by_op[cat]["missed"] += 1

    def record_core_hard_task_due(self, count: int = 1) -> None:
        self.core_hard_tasks_due += count

    def record_core_hard_task_completed(self, count: int = 1) -> None:
        self.core_hard_tasks_completed += count

    def record_missed_core_deadline(self, count: int = 1) -> None:
        self.missed_core_deadlines += count

    def record_command_emitted(self, region: str, op: Optional[str] = None) -> None:
        if region == "SW":
            self.sw_commands_emitted += 1
            if op == "HARVEST":
                self.attempted_harvest_sw += 1
            elif op == "WATER":
                self.attempted_water_sw += 1
            elif op == "PLANT":
                self.attempted_plant_sw += 1
            elif op == "FEED":
                self.attempted_feed_sw += 1
        else:
            self.core_commands_emitted += 1
            if op == "HARVEST":
                self.attempted_harvest_core += 1
            elif op == "WATER":
                self.attempted_water_core += 1
            elif op == "PLANT":
                self.attempted_plant_core += 1
            elif op == "FEED":
                self.attempted_feed_core += 1

    def record_executed_action(
        self,
        region: str,
        op: str,
        pos: Tuple[int, int],
        outcome: Optional[Dict[str, Any]] = None,
    ) -> None:
        is_sw = (region == "SW")
        if is_sw:
            self.sw_actions_executed += 1
        else:
            self.core_actions_executed += 1

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
                if outcome and outcome.get("yield_units", 0) > 0:
                    item = outcome.get("item")
                    units = outcome.get("yield_units", 0)
                    if item in self.harvested_crop_units_sw:
                        self.harvested_crop_units_sw[item] += units
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
        elif op == "FEED":
            if is_sw:
                self.sw_feed_executed += 1
            else:
                self.core_feed_executed += 1
        elif op in ("DIG", "WEED"):
            if is_sw:
                self.sw_weed_executed += 1

    def to_dict(self) -> Dict[str, Any]:
        self.reconcile_hard_deadlines(current_step=720)

        if self.sw_lifecycle_records:
            prop = len(self.sw_lifecycle_records)
            admit = sum(1 for rec in self.sw_lifecycle_records.values() if rec.disposition == "SELECTED_AND_ASSIGNED")
            defer = sum(1 for rec in self.sw_lifecycle_records.values() if rec.disposition == "REJECTED_BY_GATE")
            unsel = sum(1 for rec in self.sw_lifecycle_records.values() if rec.disposition == "ELIGIBLE_UNSELECTED")
            unres = sum(1 for rec in self.sw_lifecycle_records.values() if rec.disposition is None or rec.disposition not in ("SELECTED_AND_ASSIGNED", "REJECTED_BY_GATE", "ELIGIBLE_UNSELECTED"))
            deferral_reasons = {}
            for rec in self.sw_lifecycle_records.values():
                if rec.disposition == "REJECTED_BY_GATE" and rec.reason:
                    deferral_reasons[rec.reason] = deferral_reasons.get(rec.reason, 0) + 1
        else:
            prop = self.sw_tasks_proposed
            admit = self.sw_tasks_admitted
            defer = self.sw_tasks_deferred
            unsel = self.sw_tasks_eligible_unselected
            unres = max(0, prop - (admit + defer + unsel))
            deferral_reasons = dict(self.task_deferral_reasons)

        return {
            "sw_tasks_proposed": prop,
            "sw_tasks_admitted": admit,
            "sw_tasks_deferred": defer,
            "sw_tasks_eligible_unselected": unsel,
            "sw_tasks_unresolved": unres,
            "task_deferral_reasons": deferral_reasons,
            "deferral_reasons": deferral_reasons,  # Backward compatibility
            "sw_candidate_evaluations_proposed": self.sw_candidate_evaluations_proposed,
            "sw_candidate_evaluations_admitted": self.sw_candidate_evaluations_admitted,
            "sw_candidate_evaluations_deferred": self.sw_candidate_evaluations_deferred,
            "candidate_deferral_reasons": dict(self.candidate_deferral_reasons),
            "core_hard_tasks_due": self.core_hard_tasks_due,
            "core_hard_tasks_completed": self.core_hard_tasks_completed,
            "missed_core_deadlines": self.missed_core_deadlines,
            "hard_tasks_by_op": {k: dict(v) for k, v in self.hard_tasks_by_op.items()},
            "core_commands_emitted": self.core_commands_emitted,
            "sw_commands_emitted": self.sw_commands_emitted,
            "core_actions_executed": self.core_actions_executed,
            "sw_actions_executed": self.sw_actions_executed,
            "core_water_executed": self.core_water_executed,
            "sw_water_executed": self.sw_water_executed,
            "core_harvest_executed": self.core_harvest_executed,
            "sw_harvest_executed": self.sw_harvest_executed,
            "core_plant_executed": self.core_plant_executed,
            "sw_plant_executed": self.sw_plant_executed,
            "core_feed_executed": self.core_feed_executed,
            "sw_feed_executed": self.sw_feed_executed,
            "core_hard_tasks_invalidated": self.core_hard_tasks_invalidated,
            "core_hard_tasks_superseded": self.core_hard_tasks_superseded,
            "attempted_harvest_sw": self.attempted_harvest_sw,
            "attempted_water_sw": self.attempted_water_sw,
            "attempted_plant_sw": self.attempted_plant_sw,
            "attempted_feed_sw": self.attempted_feed_sw,
            "attempted_harvest_core": self.attempted_harvest_core,
            "attempted_water_core": self.attempted_water_core,
            "attempted_plant_core": self.attempted_plant_core,
            "attempted_feed_core": self.attempted_feed_core,
            "executed_harvest_sw": self.sw_harvest_executed,
            "harvested_crop_units_sw": dict(self.harvested_crop_units_sw),
            "sw_weed_executed": self.sw_weed_executed,
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


def is_core_hard_task(task: Dict[str, Any], farm: Any, hour: int = 0) -> bool:
    """Determine whether a task represents a Tier 0 survival/hard core obligation."""
    if not is_core_task(task, farm):
        return False
    prio = task.get("priority", 0)
    kind = task.get("kind", "")
    op = task.get("op", "")
    args = task.get("args") or [None]

    # Priority >= 100 is always PRIORITY_URGENT_SURVIVAL
    if prio >= 100:
        return True

    # Critical survival kinds
    if kind in ("feed_rescue", "harvest_decay"):
        return True

    # Placing livestock immediately upon delivery
    if op == "PLACE" and args[0] in ("COW", "SHEEP", "CHICKEN", "GOOSE"):
        return True

    # Animal feeding late in the day (hour >= 18) before starvation / escape
    if op == "FEED" and hour >= 18:
        return True

    # Crop watering when crop is in drought danger (days_without_water >= 1)
    if op == "WATER" and task.get("days_without_water", 0) >= 1:
        return True

    return False


def evaluate_sw_task_admission(
    ctx: Dict[str, Any],
    worker_idx: int,
    worker_pos: Tuple[int, int],
    task: Dict[str, Any],
    current_assignments: Dict[int, Dict[str, Any]],
    remaining_free_units: List[int],
    all_tasks: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Evaluate whether an SW agricultural task should be admitted to a worker candidate.

    Returns:
        (can_admit: bool, reason: str)
    """
    try:
        from config import (
            get_sw_core_first_task_admission_enabled,
            get_sw_urgency_aware_admission_enabled,
        )
        urgency_aware = get_sw_urgency_aware_admission_enabled()
        strict_core_first = get_sw_core_first_task_admission_enabled()
    except Exception:
        urgency_aware = False
        strict_core_first = False

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
        if ctrl.state.sw_purchase_approved:
            if ctrl.state.admitted_sw_tiles and t_pos not in ctrl.state.admitted_sw_tiles:
                return False, REASON_UNAUTHORIZED_SW_TILE
    except Exception:
        pass

    # Gather assigned task targets to identify what has already been covered
    assigned_targets = set()
    for asg_task in current_assignments.values():
        tgt = asg_task.get("target")
        if tgt is not None:
            assigned_targets.add(tuple(tgt))

    # Helper: count available core workers
    total_workers = 1 + (len(farm.hands) if (farm and hasattr(farm, "hands")) else 0)
    free_core_workers = 0
    if farm:
        for u in remaining_free_units:
            pos = None
            if u == 0:
                pos = tuple(farm.farmer)
            elif hasattr(farm, "hands") and u - 1 < len(farm.hands):
                pos = tuple(farm.hands[u - 1])
            if pos and (pos[0] >= 5 or pos[1] < 5):
                free_core_workers += 1

    is_worker_in_core = (worker_pos[0] >= 5 or worker_pos[1] < 5)

    if urgency_aware:
        # ====================================================================
        # Phase SW-B3C Urgency-Aware Admission Policy (Arm D)
        # ====================================================================

        # Tier 0 Check: Survival / HARD core obligations
        unassigned_hard_core = []
        for t in all_tasks:
            if is_core_hard_task(t, farm, hour=hour):
                tgt = t.get("target")
                if tgt is not None and tuple(tgt) in assigned_targets:
                    continue
                unassigned_hard_core.append(t)

        if unassigned_hard_core:
            # If worker is in Core, must reserve it if Core workers are needed for Tier 0
            if is_worker_in_core and free_core_workers <= len(unassigned_hard_core):
                return False, REASON_UNASSIGNED_CORE_HARD_TASK
            # If worker is in SW, recall only if Core literally cannot cover Tier 0
            if not is_worker_in_core and (total_workers - 1) < len(unassigned_hard_core):
                return False, REASON_UNASSIGNED_CORE_HARD_TASK

        # Tier 1 & Tier 2: Commitment Horizon & Near-Term Capacity Feasibility
        rem_hours = max(1, 24 - hour)
        dist_to_sw = abs(worker_pos[0] - t_pos[0]) + abs(worker_pos[1] - t_pos[1])
        expected_cost = dist_to_sw + 1  # travel + 1 execution step

        # Horizon check: cannot commit if worker cannot reach and finish before night
        if is_worker_in_core and expected_cost >= rem_hours:
            return False, REASON_INSUFFICIENT_HORIZON_FOR_COMMITMENT

        # Near-Term Core Workload Horizon Check
        # Count remaining unserviced core items
        core_unwatered = 0
        core_mature_harvest = 0
        core_unfed_animals = 0

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
                        core_mature_harvest += 1
                elif tile.is_animal:
                    if not tile.fed_today and pos not in assigned_targets:
                        core_unfed_animals += 1

        actions_needed = (
            (core_unwatered * 1.5)
            + (core_mature_harvest * 1.5)
            + (core_unfed_animals * 2.0)
        )

        if actions_needed > 0:
            core_workers_available = max(1, total_workers - 1)
            core_capacity_actions = core_workers_available * rem_hours
            required_buffered_capacity = actions_needed * 1.15 + 1.0
            if core_capacity_actions < required_buffered_capacity:
                return False, REASON_NEAR_TERM_CORE_CAPACITY_DEFICIT

        # Late-Day Commute Overhead Protection
        if is_worker_in_core and dist_to_sw >= 5 and hour >= 18:
            return False, REASON_LATE_DAY_TRANSIT_OVERHEAD

        return True, REASON_ADMITTED

    else:
        # ====================================================================
        # Phase SW-B3B Strict Core-First Admission Policy (Arm C Reproduction)
        # ====================================================================

        # Gate 2: Check Immediate Unassigned Core HARD Tasks
        for t in all_tasks:
            if is_core_task(t, farm):
                tgt = t.get("target")
                if tgt is not None and tuple(tgt) in assigned_targets:
                    continue
                prio = t.get("priority", 0)
                kind = t.get("kind", "")
                is_hard = (
                    prio >= 100
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

        if is_worker_in_core and unassigned_core_standard:
            return False, REASON_UNASSIGNED_CORE_STANDARD_TASK

        if not is_worker_in_core and unassigned_core_standard:
            if free_core_workers < len(unassigned_core_standard):
                return False, REASON_CORE_WORKER_DEFICIT

        # Gate 4: Near-Term Core Capacity Horizon Check
        rem_hours = max(1, 24 - hour)
        core_unwatered = 0
        core_mature_harvest = 0
        core_unfed_animals = 0
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
                        core_mature_harvest += 1
                elif tile.is_animal:
                    if not tile.fed_today and pos not in assigned_targets:
                        core_unfed_animals += 1

        actions_needed = (
            (core_unwatered * 2.0)
            + (core_mature_harvest * 2.0)
            + (core_unfed_animals * 2.5)
        )
        if actions_needed > 0:
            core_workers_available = max(1, total_workers - 1)
            core_capacity_actions = core_workers_available * rem_hours
            required_buffered_capacity = actions_needed * 1.25 + 2.0
            if core_capacity_actions < required_buffered_capacity:
                return False, REASON_NEAR_TERM_CORE_CAPACITY_DEFICIT

        # Gate 5: Late-Day Commute Overhead Protection
        dist_to_sw = abs(worker_pos[0] - t_pos[0]) + abs(worker_pos[1] - t_pos[1])
        if is_worker_in_core and dist_to_sw >= 5 and hour >= 18:
            return False, REASON_LATE_DAY_TRANSIT_OVERHEAD

        return True, REASON_ADMITTED


def evaluate_active_sw_mission_continuation(
    ctx: Dict[str, Any],
    worker_idx: int,
    worker_pos: Tuple[int, int],
    mission: Dict[str, Any],
    current_assignments: Dict[int, Dict[str, Any]],
    remaining_free_units: List[int],
    all_tasks: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Evaluate whether an ongoing SW active mission should continue or be preempted.

    In Urgency-Aware mode (Arm D):
    - Continuity is strictly preserved unless an urgent Tier 0 Survival emergency arises
      and Core lacks sufficient workers to handle it.
    - Eliminates ping-pong travel cancellation that crippled Arm C.

    In Strict Core-First mode (Arm C):
    - Uses original evaluate_sw_task_admission check for exact reproduction.
    """
    try:
        from config import (
            get_sw_core_first_task_admission_enabled,
            get_sw_urgency_aware_admission_enabled,
        )
        urgency_aware = get_sw_urgency_aware_admission_enabled()
        strict_core_first = get_sw_core_first_task_admission_enabled()
    except Exception:
        urgency_aware = False
        strict_core_first = False

    if not urgency_aware and not strict_core_first:
        # Admission OFF -> continue active mission
        return True, REASON_ADMITTED

    farm = ctx.get("farm")
    hour = ctx.get("hour", 0)
    task = mission.get("task", {})
    target = mission.get("target")
    if target is None:
        return False, "NO_TARGET"

    if urgency_aware:
        # Check if target is still valid
        t_pos = (int(target[0]), int(target[1]))
        if farm and hasattr(farm, "tile"):
            tile = farm.tile(t_pos)
            op = mission.get("op")
            if op == "WATER" and (tile is None or not getattr(tile, "is_plant", False) or getattr(tile, "watered_today", False)):
                return False, "TARGET_NO_LONGER_NEEDS_WATER"
            if op == "HARVEST" and (tile is None or getattr(tile, "yield_units", 0) <= 0):
                return False, "TARGET_NO_LONGER_HARVESTABLE"

        # Check for urgent Tier 0 Survival emergencies
        assigned_targets = set()
        for asg_task in current_assignments.values():
            tgt = asg_task.get("target")
            if tgt is not None:
                assigned_targets.add(tuple(tgt))

        unassigned_hard_core = []
        for t in all_tasks:
            if is_core_hard_task(t, farm, hour=hour):
                tgt = t.get("target")
                if tgt is not None and tuple(tgt) in assigned_targets:
                    continue
                unassigned_hard_core.append(t)

        if unassigned_hard_core:
            # Count free workers in core
            free_core_workers = 0
            if farm:
                for u in remaining_free_units:
                    pos = None
                    if u == 0:
                        pos = tuple(farm.farmer)
                    elif hasattr(farm, "hands") and u - 1 < len(farm.hands):
                        pos = tuple(farm.hands[u - 1])
                    if pos and (pos[0] >= 5 or pos[1] < 5):
                        free_core_workers += 1

            if free_core_workers < len(unassigned_hard_core):
                # Core literally has a worker deficit for a life-or-death emergency: preempt!
                return False, REASON_UNASSIGNED_CORE_HARD_TASK

        # Routine tasks in core DO NOT preempt an in-flight SW mission
        return True, REASON_ADMITTED

    else:
        # Strict core first: re-evaluate full admission
        return evaluate_sw_task_admission(
            ctx=ctx,
            worker_idx=worker_idx,
            worker_pos=worker_pos,
            task=task,
            current_assignments=current_assignments,
            remaining_free_units=remaining_free_units,
            all_tasks=all_tasks,
        )
