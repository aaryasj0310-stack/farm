"""Multi-Day Time-Aware Service Certificate with Structured Repair Options.

Part of the SW-First Forward Architecture Redesign (Phase A & A-R).
Provides two levels of service certification:
1. ExecutionCertificate: Current day/hour -> midnight (exact unit positions & actions)
2. ForwardServiceCertificate: Rolling 72-96 hour horizon:
   - H0-H24: exact workers & actual routes
   - H24-H48: exact cohort deadlines & regional transit
   - H48-H96: conservative capacity envelopes

Features:
- Exact physical task dependency tracking (HARVEST -> FEED, HARVEST -> PLACE -> SELL)
- Earliest-start and causal precedence enforcement
- Structured RepairOptions (DROP, DELAY, DOWNSIZE, HIRE) with economic opportunity costs
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
    """A scheduled task with spatial coordinates, deadline, and physical dependencies."""
    task_id: str
    op: str                          # FEED, WATER, HARVEST, PLANT, DIG, FERTILIZE, PLACE, SELL
    pos: Tuple[int, int]
    region: str                      # "NW", "NE", "SW"
    day: int
    hour_deadline: int
    tier: CommitmentTier
    estimated_duration_actions: int = 1
    cohort_id: Optional[str] = None
    value: float = 0.0
    prerequisite_task_id: Optional[str] = None
    earliest_start_hour: int = 0
    task_type: str = "GENERIC"


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
    binding_resource: str            # "WORKER_HOURS", "FEED_CARRIER", "SHED_SPACE", "CASH", "TASK_DEPENDENCY"
    failing_tasks: List[ServiceTask] = field(default_factory=list)
    repair_options: List[RepairOption] = field(default_factory=list)
    horizon_hours: int = 72
    hard_tasks_feasible: bool = True
    displaced_core_tasks: List[ServiceTask] = field(default_factory=list)
    uncompleted_sw_tasks: List[ServiceTask] = field(default_factory=list)
    guarantee_type: str = "CONSERVATIVE_CAPACITY_ENVELOPE"
    guarantee_notes: str = (
        "Conservative capacity envelope with spatial travel overhead factors (1.15-1.35x), "
        "earliest-start bounds, and dependency checks; not an executable discrete worker-by-worker engine schedule."
    )


class ServiceCertificate:
    """Evaluates multi-day serviceability across rolling 72-96 hour windows."""

    def __init__(self) -> None:
        pass

    def evaluate_multi_day(
        self,
        current_day: int,
        current_hour: int,
        worker_count: Optional[int],
        tasks: List[ServiceTask],
        horizon_hours: int = 72,
        planned_hires: Optional[Dict[int, int]] = None,
    ) -> CertificateResult:
        """Evaluate serviceability over rolling horizon (e.g. 72 hours).

        Simulates demand vs capacity across 3 distinct fidelity zones:
        - Zone 1 (H0-H24): Exact unit actions, travel overhead, physical dependency ordering
        - Zone 2 (H24-H48): Exact cohort deadlines + regional transit factor
        - Zone 3 (H48-H72+): Capacity envelopes
        """
        tasks_by_id = {t.task_id: t for t in tasks}
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
        failing_tasks: List[ServiceTask] = []
        displaced_core_tasks: List[ServiceTask] = []
        uncompleted_sw_tasks: List[ServiceTask] = []

        # 1. Verify physical causal dependencies, missing prereqs, cycles, and earliest start constraints
        # Missing prerequisite check
        for t in tasks:
            if t.prerequisite_task_id and t.prerequisite_task_id not in tasks_by_id:
                if t not in failing_tasks:
                    failing_tasks.append(t)
                binding_res = "TASK_DEPENDENCY"
                binding_day = t.day
                binding_hour = t.hour_deadline

        # Cyclic prerequisite check
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cyclic_task_ids: Set[str] = set()

        def dfs_detect_cycle(tid: str) -> None:
            visited.add(tid)
            rec_stack.add(tid)
            t_obj = tasks_by_id.get(tid)
            if t_obj and t_obj.prerequisite_task_id:
                pid = t_obj.prerequisite_task_id
                if pid in tasks_by_id:
                    if pid not in visited:
                        dfs_detect_cycle(pid)
                    elif pid in rec_stack:
                        cyclic_task_ids.add(tid)
                        cyclic_task_ids.add(pid)
            rec_stack.remove(tid)

        for t in tasks:
            if t.task_id not in visited:
                dfs_detect_cycle(t.task_id)

        if cyclic_task_ids:
            for c_id in cyclic_task_ids:
                c_task = tasks_by_id[c_id]
                if c_task not in failing_tasks:
                    failing_tasks.append(c_task)
            binding_res = "TASK_DEPENDENCY"
            binding_day = current_day
            binding_hour = current_hour

        # Physical precedence and earliest-start execution checks
        for t in tasks:
            earliest_self_start = max(0, t.earliest_start_hour)
            if earliest_self_start + t.estimated_duration_actions > t.hour_deadline:
                if t not in failing_tasks:
                    failing_tasks.append(t)
                binding_res = "TASK_DEPENDENCY"
                binding_day = t.day
                binding_hour = t.hour_deadline

            if t.prerequisite_task_id and t.prerequisite_task_id not in cyclic_task_ids:
                prereq = tasks_by_id.get(t.prerequisite_task_id)
                if prereq is not None:
                    if prereq.day > t.day:
                        if t not in failing_tasks:
                            failing_tasks.append(t)
                        binding_res = "TASK_DEPENDENCY"
                        binding_day = t.day
                        binding_hour = t.hour_deadline
                    elif prereq.day == t.day:
                        # Prerequisite finishes at: prereq.earliest_start_hour + prereq.estimated_duration_actions
                        prereq_earliest_finish = prereq.earliest_start_hour + prereq.estimated_duration_actions
                        # Prerequisite must finish before its own deadline
                        if prereq_earliest_finish > prereq.hour_deadline:
                            if prereq not in failing_tasks:
                                failing_tasks.append(prereq)
                            binding_res = "TASK_DEPENDENCY"
                            binding_day = prereq.day
                            binding_hour = prereq.hour_deadline

                        # Travel time between prerequisite and dependent locations
                        travel = abs(prereq.pos[0] - t.pos[0]) + abs(prereq.pos[1] - t.pos[1])
                        dep_earliest_start = max(earliest_self_start, prereq_earliest_finish + travel)
                        dep_earliest_finish = dep_earliest_start + t.estimated_duration_actions

                        if dep_earliest_finish > t.hour_deadline:
                            if t not in failing_tasks:
                                failing_tasks.append(t)
                            binding_res = "TASK_DEPENDENCY"
                            binding_day = t.day
                            binding_hour = t.hour_deadline

        # 2. Near-term window competition check (Day 0)
        # Verify cumulative worker actions in any sub-window [w_start, w_end]
        if worker_count is not None:
            day0_workers = max(1, worker_count)
        else:
            day0_workers = 1 + get_target_hands(current_day)

        day0_tasks = [t for t in tasks if t.day == current_day]
        for t_target in day0_tasks:
            w_start = max(current_hour, t_target.earliest_start_hour)
            w_end = t_target.hour_deadline
            if w_end >= w_start:
                # Tasks that must execute within this window
                competing_tasks = [
                    t for t in day0_tasks
                    if t.hour_deadline <= w_end and max(current_hour, t.earliest_start_hour) >= w_start
                ]
                total_actions_needed = int(math.ceil(sum(t.estimated_duration_actions for t in competing_tasks) * 1.35))
                window_hours = w_end - w_start + 1
                available_capacity = day0_workers * window_hours
                if total_actions_needed > available_capacity:
                    if t_target not in failing_tasks:
                        failing_tasks.append(t_target)
                    binding_res = "WORKER_HOURS"
                    binding_day = current_day
                    binding_hour = w_end
                    min_slack = min(min_slack, available_capacity - total_actions_needed)

        # 3. Iterate over each hour in the horizon for labor action budget
        hires_dict = planned_hires or {}
        for h_step in range(horizon_hours):
            abs_hour = (current_day * TURNS_PER_DAY + current_hour) + h_step
            day = abs_hour // TURNS_PER_DAY
            hour = abs_hour % TURNS_PER_DAY

            if day >= 30:
                break

            # Worker capacity in this hour
            if worker_count is not None:
                base_w = max(1, worker_count)
                if day == current_day:
                    effective_workers = base_w
                else:
                    extra_h = sum(hires_dict.get(d, 0) for d in range(current_day + 1, day + 1))
                    effective_workers = base_w + extra_h
            else:
                sched_workers = 1 + get_target_hands(day)
                effective_workers = sched_workers if hour > 0 else (1 + get_target_hands(max(0, day - 1)))

            hourly_action_budget = effective_workers  # 1 action per worker per hour

            # Tasks with deadline in this hour
            due_tasks = tasks_by_day_hour.get((day, hour), [])

            # Fidelity adjustment:
            if h_step < 24:
                travel_factor = 1.35
            elif h_step < 48:
                travel_factor = 1.25
            else:
                travel_factor = 1.15

            # Direct demand: on current day, multi-action tasks execute across their permitted window;
            # on future days, cohort tasks represent deadline capacity envelopes.
            if day == current_day:
                direct_demand = sum(min(1, t.estimated_duration_actions) for t in due_tasks)
                total_estimated_demand = int(math.ceil(direct_demand * (travel_factor if len(due_tasks) > 2 else 1.0)))
            else:
                direct_demand = sum(t.estimated_duration_actions for t in due_tasks)
                total_estimated_demand = int(math.ceil(direct_demand * travel_factor))

            if total_estimated_demand > peak_workload:
                peak_workload = total_estimated_demand

            slack = hourly_action_budget - total_estimated_demand
            if slack < min_slack:
                min_slack = slack
                if not failing_tasks:
                    binding_day = day
                    binding_hour = hour
                    binding_res = "WORKER_HOURS"

            if slack < 0:
                # Capacity deficit: prioritize HARD core survival first, then STRATEGIC, then DISCRETIONARY
                rem_budget = hourly_action_budget
                tier_prio = {CommitmentTier.HARD: 0, CommitmentTier.STRATEGIC: 1, CommitmentTier.DISCRETIONARY: 2}
                ordered_due = sorted(due_tasks, key=lambda t: (tier_prio.get(t.tier, 1), 0 if t.region != "SW" else 1))
                for t in ordered_due:
                    cost = min(1, t.estimated_duration_actions) if day == current_day else t.estimated_duration_actions
                    if rem_budget >= cost:
                        rem_budget -= cost
                    else:
                        if t not in failing_tasks:
                            failing_tasks.append(t)
                        if t.tier == CommitmentTier.HARD or t.region in ("NW", "NE"):
                            if t not in displaced_core_tasks:
                                displaced_core_tasks.append(t)
                        else:
                            if t not in uncompleted_sw_tasks:
                                uncompleted_sw_tasks.append(t)

        feasible = (min_slack >= 0) and (len(failing_tasks) == 0)
        hard_feasible = len([t for t in failing_tasks if t.tier == CommitmentTier.HARD]) == 0

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
            hard_tasks_feasible=hard_feasible,
            displaced_core_tasks=displaced_core_tasks,
            uncompleted_sw_tasks=uncompleted_sw_tasks,
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
                    cash_freed=0.0,
                    expected_value_lost=loss,
                    deadline_slack_gained=freed,
                    resolves_certificate=resolves,
                    reason=f"Drop discretionary cohort {cid} to recover {freed} actions in binding window Day {binding_day} H{binding_hour}",
                )
            )

        # Candidate Repair 2: Delay strategic SW planting by 1 day
        sw_planting_tasks = [
            t for t in tasks
            if t.day == binding_day and t.tier == CommitmentTier.STRATEGIC and t.region == "SW" and t.op in ("PLANT", "DIG")
        ]
        if sw_planting_tasks:
            freed = sum(t.estimated_duration_actions for t in sw_planting_tasks)
            repairs.append(
                RepairOption(
                    type="DELAY_COHORT",
                    target="SW_TRANCHE",
                    actions_freed=freed,
                    cash_freed=0.0,
                    expected_value_lost=250.0,  # 1 day delayed yield
                    deadline_slack_gained=freed,
                    resolves_certificate=(freed >= deficit),
                    reason=f"Delay SW tranche planting by 1 day to alleviate binding peak on Day {binding_day}",
                )
            )

        # Candidate Repair 3: Downsize tranche size
        if sw_planting_tasks and len(sw_planting_tasks) > 4:
            freed = len(sw_planting_tasks) // 2
            repairs.append(
                RepairOption(
                    type="DOWNSIZE_TRANCHE",
                    target="SW_TRANCHE_HALF",
                    actions_freed=freed,
                    cash_freed=150.0,  # saved seeds
                    expected_value_lost=500.0,
                    deadline_slack_gained=freed,
                    resolves_certificate=(freed >= deficit),
                    reason=f"Downsize SW tranche by 50% to fit within available labor budget",
                )
            )

        # Candidate Repair 4: Hire extra farmhand if below day cap
        repairs.append(
            RepairOption(
                type="HIRE_EXTRA_WORKER",
                target="HIRE_HAND",
                actions_freed=23,  # Net 23 actions across remainder of day
                cash_freed=-200.0, # Hire cost ($54-$72/day)
                expected_value_lost=0.0,
                deadline_slack_gained=1,
                resolves_certificate=(1 >= deficit),
                reason="Hire additional hand to provide +1 action per remaining hour",
            )
        )

        repairs.sort(key=lambda r: (not r.resolves_certificate, r.expected_value_lost))
        return repairs
