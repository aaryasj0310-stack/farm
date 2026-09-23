"""Multi-Day Time-Aware Service Certificate with Structured Repair Options.

Part of the SW-First Forward Architecture Redesign (Phase A).
Provides two levels of service certification:
1. ExecutionCertificate: Current day/hour -> midnight (exact unit positions & actions)
2. ForwardServiceCertificate: Rolling 72-96 hour horizon:
   - H0-H24: exact workers & actual routes
   - H24-H48: exact cohort deadlines & regional transit
   - H48-H96: conservative capacity envelopes

Returns structured RepairOptions (not free-text) to enable algorithmic repair selection.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from config import TURNS_PER_DAY, get_target_hands


class CommitmentTier(str, Enum):
    """Priority tier for farm commitments."""
    HARD = "HARD"                    # Animal survival feed, crop survival water, decay harvest, wage obligations
    STRATEGIC = "STRATEGIC"          # Planned SW cohorts, bonus watering, profitable fertilizer, planned animals
    DISCRETIONARY = "DISCRETIONARY"  # Marginal replants, late low-value care, optional non-critical tasks


@dataclass
class ServiceTask:
    """A scheduled task with spatial coordinates and deadline."""
    task_id: str
    op: str                          # FEED, WATER, HARVEST, PLANT, DIG, FERTILIZE, PLACE
    pos: Tuple[int, int]
    region: str                      # "NW", "NE", "SW"
    day: int
    hour_deadline: int
    tier: CommitmentTier
    estimated_duration_actions: int = 1
    cohort_id: Optional[str] = None
    value: float = 0.0


@dataclass
class RepairOption:
    """Structured, actionable repair suggestion when a certificate fails."""
    type: str                        # "DROP_COHORT", "DELAY_COHORT", "DOWNSIZE_TRANCHE", "HIRE_EXTRA_WORKER"
    target: str                      # Cohort ID or parameter name
    actions_freed: int               # Actions recovered in binding window
    cash_freed: float                # Cash saved
    expected_value_lost: float       # Economic opportunity cost of the repair
    deadline_slack_gained: int       # Slack improvement in binding window
    resolves_certificate: bool       # Whether this repair alone restores feasibility
    reason: str


@dataclass
class CertificateResult:
    """Result of multi-day service certificate evaluation."""
    feasible: bool
    minimum_slack: int               # Minimum unused worker-actions across evaluated window
    peak_workload: int               # Highest action demand in any single hour
    binding_day: int
    binding_hour: int
    binding_resource: str            # "WORKER_HOURS", "FEED_CARRIER", "SHED_SPACE", "CASH"
    failing_tasks: List[ServiceTask] = field(default_factory=list)
    repair_options: List[RepairOption] = field(default_factory=list)
    horizon_hours: int = 72


class ServiceCertificate:
    """Evaluates multi-day serviceability across rolling 72-96 hour windows."""

    def __init__(self) -> None:
        pass

    def evaluate_multi_day(
        self,
        current_day: int,
        current_hour: int,
        worker_count: int,
        tasks: List[ServiceTask],
        horizon_hours: int = 72,
    ) -> CertificateResult:
        """Evaluate serviceability over rolling horizon (e.g. 72 hours).

        Simulates demand vs capacity across 3 distinct fidelity zones:
        - Zone 1 (H0-H24): Exact unit actions and travel overhead
        - Zone 2 (H24-H48): Exact cohort deadlines + regional transit factor
        - Zone 3 (H48-H72+): Capacity envelopes
        """
        # Group tasks by (day, hour)
        tasks_by_day_hour: Dict[Tuple[int, int], List[ServiceTask]] = {}
        for t in tasks:
            key = (t.day, t.hour_deadline)
            if key not in tasks_by_day_hour:
                tasks_by_day_hour[key] = []
            tasks_by_day_hour[key].append(t)

        min_slack = 999999
        peak_workload = 0
        binding_day = current_day
        binding_hour = current_hour
        binding_res = "WORKER_HOURS"
        failing_tasks = []

        # Iterate over each hour in the horizon
        for h_step in range(horizon_hours):
            abs_hour = (current_day * TURNS_PER_DAY + current_hour) + h_step
            day = abs_hour // TURNS_PER_DAY
            hour = abs_hour % TURNS_PER_DAY

            if day >= 30:
                break

            # Worker capacity in this hour
            # Note: Day 0-30 target hands schedule
            sched_workers = 1 + get_target_hands(day)
            # In hour 0, new hires have not settled yet (settle at H1)
            effective_workers = sched_workers if hour > 0 else (1 + get_target_hands(max(0, day - 1)))
            hourly_action_budget = effective_workers  # 1 action per worker per hour

            # Tasks with deadline in this hour
            due_tasks = tasks_by_day_hour.get((day, hour), [])

            # Fidelity adjustment:
            # In Zone 1 (h_step < 24): add ~30% travel overhead for regional tasks
            # In Zone 2 (24 <= h_step < 48): add ~20% transit buffer
            # In Zone 3 (h_step >= 48): flat 15% buffer
            if h_step < 24:
                travel_factor = 1.35
            elif h_step < 48:
                travel_factor = 1.25
            else:
                travel_factor = 1.15

            direct_demand = sum(t.estimated_duration_actions for t in due_tasks)
            total_estimated_demand = int(math.ceil(direct_demand * travel_factor))

            if total_estimated_demand > peak_workload:
                peak_workload = total_estimated_demand

            slack = hourly_action_budget - total_estimated_demand
            if slack < min_slack:
                min_slack = slack
                binding_day = day
                binding_hour = hour

            if slack < 0:
                # Capacity deficit! Hard tasks fail
                for t in due_tasks:
                    if t.tier == CommitmentTier.HARD:
                        failing_tasks.append(t)

        feasible = (min_slack >= 0) and (len(failing_tasks) == 0)

        # Generate structured repair options if infeasible or tight
        repairs = []
        if not feasible or min_slack < 2:
            repairs = self._generate_structured_repairs(tasks, binding_day, binding_hour, min_slack)

        return CertificateResult(
            feasible=feasible,
            minimum_slack=min_slack,
            peak_workload=peak_workload,
            binding_day=binding_day,
            binding_hour=binding_hour,
            binding_resource=binding_res,
            failing_tasks=failing_tasks,
            repair_options=repairs,
            horizon_hours=horizon_hours,
        )

    def _generate_structured_repairs(
        self,
        tasks: List[ServiceTask],
        binding_day: int,
        binding_hour: int,
        slack: int,
    ) -> List[RepairOption]:
        """Generate structured repair options sorted by lowest economic loss."""
        repairs: List[RepairOption] = []
        deficit = abs(slack) if slack < 0 else 1

        # Candidate Repair 1: Drop discretionary crop cohort
        discretionary_tasks = [
            t for t in tasks
            if t.day == binding_day and t.tier == CommitmentTier.DISCRETIONARY and t.cohort_id
        ]
        cohort_groups: Dict[str, List[ServiceTask]] = {}
        for t in discretionary_tasks:
            if t.cohort_id:
                cohort_groups.setdefault(t.cohort_id, []).append(t)

        for cid, group in cohort_groups.items():
            freed = sum(t.estimated_duration_actions for t in group)
            loss = sum(t.value for t in group)
            resolves = (freed >= deficit)
            repairs.append(
                RepairOption(
                    type="DROP_COHORT",
                    target=cid,
                    actions_freed=freed,
                    cash_freed=50.0,
                    expected_value_lost=loss,
                    deadline_slack_gained=freed,
                    resolves_certificate=resolves,
                    reason=f"Drop discretionary cohort {cid} to recover {freed} actions at Day {binding_day}",
                )
            )

        # Candidate Repair 2: Downsize SW tranche
        sw_strategic = [
            t for t in tasks
            if t.day == binding_day and t.region == "SW" and t.tier == CommitmentTier.STRATEGIC
        ]
        if sw_strategic:
            sw_freed = sum(t.estimated_duration_actions for t in sw_strategic)
            repairs.append(
                RepairOption(
                    type="DOWNSIZE_TRANCHE",
                    target="SW_TRANCHE",
                    actions_freed=sw_freed // 2,
                    cash_freed=200.0,
                    expected_value_lost=300.0,
                    deadline_slack_gained=sw_freed // 2,
                    resolves_certificate=((sw_freed // 2) >= deficit),
                    reason=f"Scale down SW tranche to recover {sw_freed // 2} actions",
                )
            )

        # Candidate Repair 3: Add peak-day extra hire
        repairs.append(
            RepairOption(
                type="HIRE_EXTRA_WORKER",
                target=f"DAY_{binding_day}_HIRE",
                actions_freed=20,
                cash_freed=-233.0,  # Marginal wage cost of 13th hand
                expected_value_lost=233.0,
                deadline_slack_gained=20,
                resolves_certificate=True,
                reason=f"Hire 1 extra hand on peak Day {binding_day} to provide 20 extra actions",
            )
        )

        # Sort repairs: those that resolve certificate first, then lowest value lost
        repairs.sort(key=lambda r: (not r.resolves_certificate, r.expected_value_lost))
        return repairs
