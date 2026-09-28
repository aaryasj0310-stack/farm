"""
Phase SW-C2: P1 Mission Ownership & Executable Resource Chains
Provides stable obligation-indexed mission ownership, explicit preemption,
transfer tracking, wasted travel accounting, and anti-thrashing mechanisms.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class MissionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    PREEMPTED = "PREEMPTED"
    INVALIDATED = "INVALIDATED"
    TRANSFERRED = "TRANSFERRED"


def compute_task_obligation_id(
    day: int,
    op: str,
    target: Tuple[int, int],
    kind: str = "",
    args: Optional[List[Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a stable, deterministic obligation ID for a scheduled task."""
    if meta and "obligation_id" in meta:
        return str(meta["obligation_id"])

    arg_suffix = ""
    if args:
        arg_suffix = f"_{args[0]}"
    tgt = tuple(target) if target else (-1, -1)
    k_suffix = f"_{kind}" if kind else ""
    meta_suffix = ""
    if meta:
        if "chunk_idx" in meta:
            meta_suffix += f"_chunk_{meta['chunk_idx']}"
        if "required_unit" in meta:
            meta_suffix += f"_unit_{meta['required_unit']}"
    return f"OBL_D{day}_{op}_({tgt[0]},{tgt[1]}){k_suffix}{arg_suffix}{meta_suffix}"


@dataclass
class MissionRecord:
    obligation_id: str
    worker_idx: int
    op: str
    target: Tuple[int, int]
    kind: str = ""
    args: List[Any] = field(default_factory=list)
    priority: float = 0.0
    assigned_step: int = 0
    last_active_step: int = 0
    prev_distance: int = 0
    consecutive_no_progress: int = 0
    steps_active: int = 0
    travel_steps_spent: int = 0
    wasted_travel_steps: int = 0
    status: MissionStatus = MissionStatus.ACTIVE
    preemption_reason: Optional[str] = None
    terminal_reason: Optional[str] = None
    resource_held: Optional[Tuple[str, int]] = None
    transfer_history: List[Dict[str, Any]] = field(default_factory=list)
    task: Dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.status == MissionStatus.ACTIVE


class MissionOwnershipTracker:
    """Tracks stable mission ownership per worker and per obligation.
    
    Invariants:
    1. At most one worker owns a specific obligation_id at any given step.
    2. At most one active mission is owned by any worker at any given step.
    3. Preemption records reason and accounts for wasted travel if the mission
       did not complete.
    4. Transfers record old worker, new worker, and travel already spent.
    5. Duplicate pursuit of identical non-parallel obligations is prevented.
    """

    def __init__(self) -> None:
        self._missions_by_obligation: Dict[str, MissionRecord] = {}
        self._missions_by_worker: Dict[int, MissionRecord] = {}
        self._telemetry = {
            "missions_started": 0,
            "missions_completed": 0,
            "missions_preempted": 0,
            "missions_invalidated": 0,
            "missions_transferred": 0,
            "wasted_travel_steps": 0,
            "duplicate_pursuits_blocked": 0,
            "preemptions_by_reason": {},
            "invalidations_by_reason": {},
            "transfers_by_reason": {},
            "fallback_discretionary_blocked": 0,
        }

    def reset(self) -> None:
        self._missions_by_obligation.clear()
        self._missions_by_worker.clear()
        self._telemetry = {
            "missions_started": 0,
            "missions_completed": 0,
            "missions_preempted": 0,
            "missions_invalidated": 0,
            "missions_transferred": 0,
            "wasted_travel_steps": 0,
            "duplicate_pursuits_blocked": 0,
            "preemptions_by_reason": {},
            "invalidations_by_reason": {},
            "transfers_by_reason": {},
            "fallback_discretionary_blocked": 0,
        }

    def get_mission_for_worker(self, worker_idx: int) -> Optional[MissionRecord]:
        m = self._missions_by_worker.get(worker_idx)
        return m if m and m.is_active() else None

    def get_mission_for_obligation(self, obligation_id: str) -> Optional[MissionRecord]:
        m = self._missions_by_obligation.get(obligation_id)
        return m if m and m.is_active() else None

    def is_obligation_owned_by_other(self, obligation_id: str, worker_idx: int) -> bool:
        # Operations that explicitly allow parallel prerequisites (e.g. parallel shed pickups/drops)
        if "_PICKUP_" in obligation_id or "_DROP_" in obligation_id:
            return False
        existing = self.get_mission_for_obligation(obligation_id)
        if existing is None:
            return False
        return existing.worker_idx != worker_idx

    def claim_or_continue_mission(
        self,
        worker_idx: int,
        obligation_id: str,
        task: Dict[str, Any],
        worker_pos: Tuple[int, int],
        step: int,
    ) -> MissionRecord:
        """Assign an obligation to worker_idx, handling transfers and continuation."""
        tgt = tuple(task.get("target") or worker_pos)
        curr_d = abs(worker_pos[0] - tgt[0]) + abs(worker_pos[1] - tgt[1])

        # Check if this worker already has a different active mission
        current_m = self.get_mission_for_worker(worker_idx)
        if current_m and current_m.obligation_id != obligation_id:
            self.preempt_worker_mission(
                worker_idx=worker_idx,
                reason=f"REASSIGNED_TO_{obligation_id}",
                step=step,
            )

        # Check if this obligation is already owned by someone else
        existing_owner_m = self.get_mission_for_obligation(obligation_id)
        if existing_owner_m and existing_owner_m.worker_idx != worker_idx:
            # Transfer ownership
            old_w = existing_owner_m.worker_idx
            self.transfer_mission(
                obligation_id=obligation_id,
                old_worker=old_w,
                new_worker=worker_idx,
                reason="EXPLICIT_DISPATCH_TRANSFER",
                step=step,
            )
            existing_owner_m.task = dict(task)
            existing_owner_m.last_active_step = step
            return existing_owner_m

        # If it's a continuation by the same worker
        if existing_owner_m and existing_owner_m.worker_idx == worker_idx:
            existing_owner_m.task = dict(task)
            existing_owner_m.last_active_step = step
            existing_owner_m.steps_active += 1
            if curr_d < existing_owner_m.prev_distance:
                existing_owner_m.travel_steps_spent += 1
                existing_owner_m.consecutive_no_progress = 0
                existing_owner_m.prev_distance = curr_d
            elif curr_d == existing_owner_m.prev_distance and curr_d > 0:
                existing_owner_m.consecutive_no_progress += 1
            return existing_owner_m

        # Otherwise create a new mission record
        new_record = MissionRecord(
            obligation_id=obligation_id,
            worker_idx=worker_idx,
            op=task.get("op", "PASS"),
            target=tgt,
            kind=task.get("kind", ""),
            args=list(task.get("args") or []),
            priority=float(task.get("priority", 0.0)),
            assigned_step=step,
            last_active_step=step,
            prev_distance=curr_d,
            consecutive_no_progress=0,
            steps_active=1,
            travel_steps_spent=0,
            wasted_travel_steps=0,
            status=MissionStatus.ACTIVE,
            task=dict(task),
        )
        self._missions_by_obligation[obligation_id] = new_record
        self._missions_by_worker[worker_idx] = new_record
        self._telemetry["missions_started"] += 1
        return new_record

    def transfer_mission(
        self,
        obligation_id: str,
        old_worker: int,
        new_worker: int,
        reason: str,
        step: int,
    ) -> Optional[MissionRecord]:
        """Explicit transfer of mission ownership between workers."""
        m = self._missions_by_obligation.get(obligation_id)
        if not m or not m.is_active():
            return None

        m.transfer_history.append({
            "step": step,
            "old_worker": old_worker,
            "new_worker": new_worker,
            "reason": reason,
            "travel_steps_spent_by_old": m.travel_steps_spent,
        })
        m.worker_idx = new_worker
        self._missions_by_worker.pop(old_worker, None)
        self._missions_by_worker[new_worker] = m

        self._telemetry["missions_transferred"] += 1
        self._telemetry["transfers_by_reason"][reason] = (
            self._telemetry["transfers_by_reason"].get(reason, 0) + 1
        )
        return m

    def preempt_worker_mission(
        self,
        worker_idx: int,
        reason: str,
        step: int,
    ) -> Optional[MissionRecord]:
        """Preempt an active mission, recording wasted travel."""
        m = self.get_mission_for_worker(worker_idx)
        if not m or not m.is_active():
            return None

        m.status = MissionStatus.PREEMPTED
        m.preemption_reason = reason
        m.terminal_reason = f"Preempted: {reason} at step {step}"
        # Wasted travel: travel steps spent without reaching completion
        m.wasted_travel_steps += m.travel_steps_spent
        self._telemetry["wasted_travel_steps"] += m.travel_steps_spent
        self._telemetry["missions_preempted"] += 1
        self._telemetry["preemptions_by_reason"][reason] = (
            self._telemetry["preemptions_by_reason"].get(reason, 0) + 1
        )

        self._missions_by_worker.pop(worker_idx, None)
        return m

    def invalidate_mission(
        self,
        obligation_id: str,
        reason: str,
        step: int,
    ) -> Optional[MissionRecord]:
        """Invalidate an active mission (e.g. target no longer needs work, timeout)."""
        m = self._missions_by_obligation.get(obligation_id)
        if not m or not m.is_active():
            return None

        m.status = MissionStatus.INVALIDATED
        m.terminal_reason = f"Invalidated: {reason} at step {step}"
        m.wasted_travel_steps += m.travel_steps_spent
        self._telemetry["wasted_travel_steps"] += m.travel_steps_spent
        self._telemetry["missions_invalidated"] += 1
        self._telemetry["invalidations_by_reason"][reason] = (
            self._telemetry["invalidations_by_reason"].get(reason, 0) + 1
        )

        self._missions_by_worker.pop(m.worker_idx, None)
        return m

    def complete_mission(
        self,
        obligation_id: str,
        step: int,
    ) -> Optional[MissionRecord]:
        """Mark mission completed after successful execution."""
        m = self._missions_by_obligation.get(obligation_id)
        if not m or not m.is_active():
            return None

        m.status = MissionStatus.COMPLETED
        m.terminal_reason = f"Completed at step {step}"
        self._telemetry["missions_completed"] += 1
        self._missions_by_worker.pop(m.worker_idx, None)
        return m

    def handle_midnight_rollover(self, new_day: int) -> None:
        """Handle end-of-day worker expiration."""
        for m in list(self._missions_by_worker.values()):
            if m.is_active():
                m.status = MissionStatus.INVALIDATED
                m.terminal_reason = f"Midnight reset into Day {new_day}"
                m.wasted_travel_steps += m.travel_steps_spent
                self._telemetry["wasted_travel_steps"] += m.travel_steps_spent
        self._missions_by_worker.clear()

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "missions_started": self._telemetry["missions_started"],
            "missions_completed": self._telemetry["missions_completed"],
            "missions_preempted": self._telemetry["missions_preempted"],
            "missions_invalidated": self._telemetry["missions_invalidated"],
            "missions_transferred": self._telemetry["missions_transferred"],
            "wasted_travel_steps": self._telemetry["wasted_travel_steps"],
            "duplicate_pursuits_blocked": self._telemetry["duplicate_pursuits_blocked"],
            "preemptions_by_reason": dict(self._telemetry["preemptions_by_reason"]),
            "invalidations_by_reason": dict(self._telemetry["invalidations_by_reason"]),
            "transfers_by_reason": dict(self._telemetry["transfers_by_reason"]),
            "active_missions_count": sum(1 for m in self._missions_by_worker.values() if m.is_active()),
            "fallback_discretionary_blocked": self._telemetry["fallback_discretionary_blocked"],
        }


# Singleton instance
_MISSION_OWNERSHIP_TRACKER: Optional[MissionOwnershipTracker] = None


def get_mission_ownership_tracker() -> MissionOwnershipTracker:
    global _MISSION_OWNERSHIP_TRACKER
    if _MISSION_OWNERSHIP_TRACKER is None:
        _MISSION_OWNERSHIP_TRACKER = MissionOwnershipTracker()
    return _MISSION_OWNERSHIP_TRACKER


def reset_mission_ownership_tracker() -> None:
    global _MISSION_OWNERSHIP_TRACKER
    if _MISSION_OWNERSHIP_TRACKER is not None:
        _MISSION_OWNERSHIP_TRACKER.reset()
