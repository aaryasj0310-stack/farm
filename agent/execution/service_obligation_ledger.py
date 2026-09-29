"""Authoritative Service Obligation Ledger (Phase SW-C2).

Maintains stable operation-specific identities, prerequisite chains,
lifecycle state machine, and engine-confirmed reconciliation for all
crop, livestock, and logistical commitments across the farm.

Runs in SHADOW mode during initial phases.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from execution.obligation_types import (
    CropCohortLifecycle,
    ObligationLifecycle,
    ObligationTier,
    ServiceObligation,
)

logger = logging.getLogger(__name__)


def compute_quadrant(pos: Tuple[int, int], board_size: int = 10) -> str:
    x, y = pos
    mid = board_size // 2
    if x < mid and y < mid:
        return "NW"
    elif x >= mid and y < mid:
        return "NE"
    elif x < mid and y >= mid:
        return "SW"
    else:
        return "SE"


class ServiceObligationLedger:
    """Central registry and reconciliation engine for farm service obligations."""

    def __init__(self):
        self._obligations: Dict[str, ServiceObligation] = {}
        self._cohorts: Dict[str, Dict[str, Any]] = {}
        self._operation_seq_counters: Dict[str, int] = {}
        self._last_reconciled_step: int = -1
        self._telemetry = {
            "obligations_created": 0,
            "obligations_completed": 0,
            "obligations_expired": 0,
            "obligations_cancelled": 0,
            "false_positives": 0,
            "duplicate_assignments": 0,
        }

    def reset(self) -> None:
        self._obligations.clear()
        self._cohorts.clear()
        self._operation_seq_counters.clear()
        self._last_reconciled_step = -1
        for k in self._telemetry:
            self._telemetry[k] = 0

    def generate_obligation_id(
        self,
        day: int,
        entity_id: str,
        op: str,
    ) -> str:
        key = f"{day}_{entity_id}_{op}"
        seq = self._operation_seq_counters.get(key, 0)
        self._operation_seq_counters[key] = seq + 1
        return f"OBL_{day}_{entity_id}_{op}_{seq}"

    def register_obligation(self, obligation: ServiceObligation) -> str:
        if obligation.obligation_id in self._obligations:
            existing = self._obligations[obligation.obligation_id]
            if existing.lifecycle in (ObligationLifecycle.COMPLETED, ObligationLifecycle.CANCELLED):
                return existing.obligation_id
            # Update attributes if still pending
            existing.deadline_step = obligation.deadline_step
            existing.latest_feasible_start_step = obligation.latest_feasible_start_step
            existing.economic_value = obligation.economic_value
            return existing.obligation_id

        self._obligations[obligation.obligation_id] = obligation
        self._telemetry["obligations_created"] += 1
        return obligation.obligation_id

    def unregister_obligation(self, obligation_id: str) -> bool:
        """Unregister / remove an obligation from the ledger (used for atomic rollback)."""
        if obligation_id in self._obligations:
            del self._obligations[obligation_id]
            self._telemetry["obligations_created"] = max(0, self._telemetry["obligations_created"] - 1)
            return True
        return False

    def get_obligation(self, obligation_id: str) -> Optional[ServiceObligation]:
        return self._obligations.get(obligation_id)

    def get_active_obligations(self) -> List[ServiceObligation]:
        return [o for o in self._obligations.values() if o.is_active()]

    def get_pending_obligations_for_region(self, region: str) -> List[ServiceObligation]:
        return [
            o for o in self._obligations.values()
            if o.region == region and o.lifecycle in (ObligationLifecycle.READY, ObligationLifecycle.PROPOSED)
        ]

    def register_tasks_from_scheduler(
        self,
        tasks: List[Dict[str, Any]],
        ctx: Dict[str, Any],
    ) -> List[str]:
        """Ingest tasks from task_scheduler.build_tasks and normalize to stable obligations."""
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)
        step = ctx.get("step", day * 24 + hour)
        board_size = 10
        registered_ids = []

        for t in tasks:
            op = t.get("op", "PASS")
            if op == "PASS":
                continue
            tgt = tuple(t.get("target") or (4, 4))
            region = compute_quadrant(tgt, board_size)
            kind = t.get("kind", "")
            args = t.get("args") or []
            entity_id = f"pos_{tgt[0]}_{tgt[1]}_{kind}"
            prio = t.get("priority", 50)

            # Determine Tier
            if prio >= 90:
                tier = ObligationTier.HARD
                deadline = day * 24 + 23
            elif prio >= 65:
                tier = ObligationTier.STRATEGIC
                deadline = day * 24 + 23
            else:
                tier = ObligationTier.DISCRETIONARY
                deadline = min(718, day * 24 + 47)

            obl_id = f"OBL_D{day}_{op}_({tgt[0]},{tgt[1]})_{kind}"
            if obl_id in self._obligations:
                registered_ids.append(obl_id)
                continue

            obl = ServiceObligation(
                obligation_id=obl_id,
                entity_id=entity_id,
                op=op,
                target_pos=tgt,
                region=region,
                tier=tier,
                release_step=step,
                deadline_step=deadline,
                latest_feasible_start_step=max(step, deadline - 4),
                economic_value=float(prio),
                lifecycle=ObligationLifecycle.READY,
                metadata={"raw_task": t},
            )
            self.register_obligation(obl)
            registered_ids.append(obl_id)

        return registered_ids

    def link_feeding_chain(
        self,
        animal_pos: Tuple[int, int],
        animal_type: str,
        day: int,
        hour: int,
        shed_has_wheat: bool,
    ) -> Tuple[Optional[str], str]:
        """Link wheat pickup to animal feeding prerequisite chain."""
        feed_id = f"OBL_FEED_D{day}_({animal_pos[0]},{animal_pos[1]})_{animal_type}"
        pickup_id = f"OBL_PICKUP_WHEAT_D{day}_FOR_({animal_pos[0]},{animal_pos[1]})"

        feed_obl = ServiceObligation(
            obligation_id=feed_id,
            entity_id=f"animal_{animal_pos[0]}_{animal_pos[1]}",
            op="FEED",
            target_pos=animal_pos,
            region=compute_quadrant(animal_pos),
            tier=ObligationTier.HARD,
            required_item="WHEAT",
            required_item_qty=1,
            prerequisites=[pickup_id] if shed_has_wheat else [],
            release_step=day * 24,
            deadline_step=day * 24 + 23,
            latest_feasible_start_step=day * 24 + 18,
            expected_duration_steps=1,
            expected_travel_steps=3,
            economic_value=100.0,
            lifecycle=ObligationLifecycle.READY if not shed_has_wheat else ObligationLifecycle.RESERVED,
        )

        pickup_obl = None
        if shed_has_wheat:
            pickup_obl = ServiceObligation(
                obligation_id=pickup_id,
                entity_id="shed_wheat",
                op="PICKUP",
                target_pos=(4, 4),
                region="NW",
                tier=ObligationTier.HARD,
                required_item="WHEAT",
                required_item_qty=1,
                release_step=day * 24,
                deadline_step=day * 24 + 20,
                latest_feasible_start_step=day * 24 + 16,
                expected_duration_steps=1,
                expected_travel_steps=2,
                economic_value=100.0,
                lifecycle=ObligationLifecycle.READY,
            )
            self.register_obligation(pickup_obl)

        self.register_obligation(feed_obl)
        return (pickup_id if pickup_obl else None, feed_id)

    def reconcile_with_observation(
        self,
        current_step: int,
        obs_farm: Dict[str, Any],
        private: Dict[str, Any],
    ) -> Dict[str, int]:
        """Reconcile all obligations against real engine state transition."""
        day = current_step // 24
        hour = current_step % 24
        tiles = obs_farm.get("tiles", [])
        board_size = len(tiles)
        reconciled_counts = {"completed": 0, "expired": 0, "failed": 0}

        for obl in self._obligations.values():
            if obl.is_terminal():
                continue

            # 1. Check completion via state confirmation
            x, y = obl.target_pos
            if 0 <= y < board_size and 0 <= x < board_size:
                tile = tiles[y][x]
                if tile is None:
                    if obl.op == "HARVEST":
                        obl.lifecycle = ObligationLifecycle.COMPLETED
                        obl.completed_step = current_step
                        reconciled_counts["completed"] += 1
                        self._telemetry["obligations_completed"] += 1
                elif isinstance(tile, dict):
                    if obl.op == "FEED" and tile.get("fed_today"):
                        obl.lifecycle = ObligationLifecycle.COMPLETED
                        obl.completed_step = current_step
                        reconciled_counts["completed"] += 1
                        self._telemetry["obligations_completed"] += 1
                    elif obl.op == "CARE" and tile.get("cared_today"):
                        obl.lifecycle = ObligationLifecycle.COMPLETED
                        obl.completed_step = current_step
                        reconciled_counts["completed"] += 1
                        self._telemetry["obligations_completed"] += 1
                    elif obl.op == "WATER" and tile.get("watered_today"):
                        obl.lifecycle = ObligationLifecycle.COMPLETED
                        obl.completed_step = current_step
                        reconciled_counts["completed"] += 1
                        self._telemetry["obligations_completed"] += 1
                    elif obl.op == "HARVEST" and tile.get("yield_units", 0) == 0:
                        obl.lifecycle = ObligationLifecycle.COMPLETED
                        obl.completed_step = current_step
                        reconciled_counts["completed"] += 1
                        self._telemetry["obligations_completed"] += 1
                    elif obl.op == "COLLECT_FERTILIZER" and not tile.get("fertilizer_available", True):
                        obl.lifecycle = ObligationLifecycle.COMPLETED
                        obl.completed_step = current_step
                        reconciled_counts["completed"] += 1
                        self._telemetry["obligations_completed"] += 1

            # 2. Check deadline expiration
            if not obl.is_terminal() and current_step > obl.deadline_step:
                obl.lifecycle = ObligationLifecycle.EXPIRED
                obl.terminal_reason = f"Past deadline_step {obl.deadline_step}"
                reconciled_counts["expired"] += 1
                self._telemetry["obligations_expired"] += 1

        self._last_reconciled_step = current_step
        return reconciled_counts

    def mark_cancelled(self, obligation_id: str, reason: str = "cancelled") -> bool:
        """Mark an obligation as CANCELLED in the ledger."""
        if obligation_id in self._obligations:
            obl = self._obligations[obligation_id]
            if not obl.is_terminal():
                obl.lifecycle = ObligationLifecycle.CANCELLED
                obl.terminal_reason = reason
                self._telemetry["obligations_cancelled"] += 1
                return True
        return False

    def handle_midnight_rollover(self, new_day: int) -> None:
        """Clear worker ownership at midnight while keeping legitimate entity obligations."""
        for obl in self._obligations.values():
            if not obl.is_terminal():
                obl.assigned_worker_id = None
                obl.progress_counter = 0

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            **self._telemetry,
            "total_obligations_tracked": len(self._obligations),
            "active_obligations_count": len(self.get_active_obligations()),
        }


_GLOBAL_OBLIGATION_LEDGER: Optional[ServiceObligationLedger] = None


def get_service_obligation_ledger() -> ServiceObligationLedger:
    global _GLOBAL_OBLIGATION_LEDGER
    if _GLOBAL_OBLIGATION_LEDGER is None:
        _GLOBAL_OBLIGATION_LEDGER = ServiceObligationLedger()
    return _GLOBAL_OBLIGATION_LEDGER


def reset_service_obligation_ledger() -> None:
    global _GLOBAL_OBLIGATION_LEDGER
    if _GLOBAL_OBLIGATION_LEDGER is not None:
        _GLOBAL_OBLIGATION_LEDGER.reset()
