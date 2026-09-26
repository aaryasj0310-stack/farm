"""Unit tests for candidate-specific workload feasibility and certification integrity.

Verifies:
1. Candidate SW expansion plans that respect labor constraints are certified as feasible with zero displaced core tasks.
2. Negative test: When candidate workload threatens HARD-tier obligations (e.g., animal feeding),
   `CertificateResult.feasible` is False and `hard_feasible` is False, guaranteeing the candidate is rejected.
3. Negative test: When candidate tasks have causal dependency cycles, certification fails immediately.
4. Admitted candidates strictly preserve 100% of HARD-tier tasks without dropping core farm operations.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_AGENT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [_ROOT, _AGENT]:
    if p not in sys.path:
        sys.path.insert(0, p)

import agent.main
from strategy.service_certificate import (
    ServiceCertificate, ServiceTask, CommitmentTier, CertificateResult
)
from strategy.whole_farm_planner import WholeFarmPlanner, ShadowSnapshot, get_whole_farm_planner


def test_feasible_candidate_preserves_hard_tier():
    """Verify that a feasible workload plan with adequate labor certifies cleanly."""
    evaluator = ServiceCertificate()
    
    # Core tasks: 2 animals to feed (HARD tier) on Day 8
    feed_task_1 = ServiceTask(
        task_id="core_feed_cow_1",
        op="FEED",
        pos=(5, 5),
        day=8,
        hour_deadline=18,
        estimated_duration_actions=1,
        tier=CommitmentTier.HARD,
        region="NW",
    )
    feed_task_2 = ServiceTask(
        task_id="core_feed_sheep_1",
        op="FEED",
        pos=(5, 6),
        day=8,
        hour_deadline=18,
        estimated_duration_actions=1,
        tier=CommitmentTier.HARD,
        region="NW",
    )
    
    # Candidate SW task: 1 SW tilling task (STRATEGIC tier)
    sw_task = ServiceTask(
        task_id="sw_till_3_0",
        op="TILL",
        pos=(0, 20),
        day=8,
        hour_deadline=20,
        estimated_duration_actions=1,
        tier=CommitmentTier.STRATEGIC,
        region="SW",
    )
    
    # With 4 workers on Day 8, hourly budget is 4 actions per hour.
    cert = evaluator.evaluate_multi_day(
        current_day=8,
        current_hour=0,
        worker_count=4,
        tasks=[feed_task_1, feed_task_2, sw_task],
        horizon_hours=24,
    )
    
    assert cert.feasible is True
    assert cert.hard_tasks_feasible is True
    assert len(cert.displaced_core_tasks) == 0
    assert cert.guarantee_tier in ("CERTIFIED_SAFE", "TIGHT_BUT_SERVICEABLE")


def test_negative_workload_labor_deficit_threatens_hard_tier():
    """Negative test: When total workload exceeds labor budget and starves HARD tasks, cert fails."""
    evaluator = ServiceCertificate()
    
    # 3 HARD animal feed tasks all due at Day 8, Hour 18
    hard_tasks = [
        ServiceTask(
            task_id=f"core_feed_{i}",
            op="FEED",
            pos=(5, 5 + i),
            day=8,
            hour_deadline=18,
            estimated_duration_actions=1,
            tier=CommitmentTier.HARD,
            region="NW",
        )
        for i in range(3)
    ]
    
    # 2 SW tasks also demanding labor at the same hour
    sw_tasks = [
        ServiceTask(
            task_id=f"sw_heavy_{i}",
            op="HARVEST",
            pos=(1, 20 + i),
            day=8,
            hour_deadline=18,
            estimated_duration_actions=1,
            tier=CommitmentTier.STRATEGIC,
            region="SW",
        )
        for i in range(2)
    ]
    
    # Only 1 worker available (capacity = 1 action per hour). Total demand = 5 actions > 1 worker.
    cert = evaluator.evaluate_multi_day(
        current_day=8,
        current_hour=18,
        worker_count=1,
        tasks=hard_tasks + sw_tasks,
        horizon_hours=1,
    )
    
    assert cert.feasible is False, "Overloaded hour must not be feasible"
    assert cert.hard_tasks_feasible is False, "Deficit must drop HARD tasks when capacity = 1 and demand = 5"
    assert len(cert.failing_tasks) > 0
    assert len(cert.displaced_core_tasks) > 0
    assert cert.guarantee_tier == "INFEASIBLE"


def test_negative_cyclic_prerequisites_fails_certification():
    """Negative test: Causal dependency cycles must fail certification immediately."""
    evaluator = ServiceCertificate()
    
    task_a = ServiceTask(
        task_id="task_a",
        op="WATER",
        pos=(0, 20),
        day=8,
        hour_deadline=12,
        estimated_duration_actions=1,
        prerequisite_task_id="task_b",
        tier=CommitmentTier.STRATEGIC,
        region="SW",
    )
    task_b = ServiceTask(
        task_id="task_b",
        op="TILL",
        pos=(0, 20),
        day=8,
        hour_deadline=12,
        estimated_duration_actions=1,
        prerequisite_task_id="task_a",
        tier=CommitmentTier.STRATEGIC,
        region="SW",
    )
    
    cert = evaluator.evaluate_multi_day(
        current_day=8,
        current_hour=0,
        worker_count=5,
        tasks=[task_a, task_b],
        horizon_hours=24,
    )
    
    assert cert.feasible is False
    assert cert.binding_resource == "TASK_DEPENDENCY"
    assert any(t.task_id in ("task_a", "task_b") for t in cert.failing_tasks)


def test_negative_missing_prerequisite_fails_certification():
    """Negative test: Missing prerequisite must fail certification immediately."""
    evaluator = ServiceCertificate()
    
    task = ServiceTask(
        task_id="task_child",
        op="PLANT",
        pos=(0, 20),
        day=8,
        hour_deadline=12,
        estimated_duration_actions=1,
        prerequisite_task_id="task_parent_nonexistent",
        tier=CommitmentTier.STRATEGIC,
        region="SW",
    )
    
    cert = evaluator.evaluate_multi_day(
        current_day=8,
        current_hour=0,
        worker_count=5,
        tasks=[task],
        horizon_hours=24,
    )
    
    assert cert.feasible is False
    assert cert.binding_resource == "TASK_DEPENDENCY"
    assert any(t.task_id == "task_child" for t in cert.failing_tasks)
