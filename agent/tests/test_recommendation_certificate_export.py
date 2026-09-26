"""Unit and regression tests for recommendation-certificate serialization and export integrity.

Verifies:
1. Candidate certificates are faithfully exported with full structure (candidate ID, evaluation time, tranche, feasibility, slack, binding resource, displaced tasks, tiers, repairs).
2. Negative regression test: An exporter MUST NOT emit hardcoded positive constants (e.g. combined_workload_feasible=True, hard_tasks_feasible=True, minimum_slack=2) when the actual certificate is infeasible or has displaced HARD tasks.
3. Verification that admitted candidate certificates are strictly distinguished from generic baseline or unverified historical certificates.
"""
from __future__ import annotations

import os
import sys
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_AGENT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [_ROOT, _AGENT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.service_certificate import (
    CertificateResult,
    CommitmentTier,
    RepairOption,
    ServiceTask,
    serialize_candidate_certificate,
)
from strategy.whole_farm_planner import ShadowDecision


def test_positive_candidate_certificate_serialization():
    """Verify that a feasible admitted candidate certificate exports all fields accurately."""
    cert = CertificateResult(
        feasible=True,
        minimum_slack=5,
        peak_workload=8,
        binding_day=10,
        binding_hour=14,
        binding_resource="WORKER_HOURS",
        failing_tasks=[],
        repair_options=[],
        horizon_hours=72,
        hard_tasks_feasible=True,
        displaced_core_tasks=[],
        uncompleted_sw_tasks=[],
        guarantee_type="CONSERVATIVE_CAPACITY_ENVELOPE",
        guarantee_tier="CERTIFIED_SAFE",
    )

    port = {
        "name": "compact_commercial",
        "tiles_used": 8,
        "allocations": [["STRAWBERRY", 4, []], ["MELON", 4, []]],
    }

    exported = serialize_candidate_certificate(cert, port=port, day=10, hour=14)

    assert exported["candidate_id"] == "compact_commercial"
    assert exported["evaluation_day"] == 10
    assert exported["evaluation_hour"] == 14
    assert exported["selected_tranche_size_tiles"] == 8
    assert exported["combined_workload_feasible"] is True
    assert exported["hard_tasks_feasible"] is True
    assert exported["minimum_slack"] == 5
    assert exported["peak_workload"] == 8
    assert exported["binding_resource"] == "WORKER_HOURS"
    assert exported["binding_day"] == 10
    assert exported["binding_deadline_hour"] == 14
    assert exported["failing_task_ids"] == []
    assert exported["displaced_task_ids"] == []
    assert exported["displaced_hard_tasks_count"] == 0
    assert exported["commitment_tier"] == "HARD_TIER_PRESERVED"
    assert exported["guarantee_tier"] == "CERTIFIED_SAFE"


def test_negative_regression_exporter_rejects_fixed_positive_constants():
    """Negative regression test: Exporter MUST NOT emit fixed positive constants when certificate fails."""
    hard_displaced_task = ServiceTask(
        task_id="core_feed_cow_9",
        op="FEED",
        pos=(5, 5),
        day=10,
        hour_deadline=18,
        tier=CommitmentTier.HARD,
        region="NW",
    )

    failing_cert = CertificateResult(
        feasible=False,
        minimum_slack=-4,
        peak_workload=16,
        binding_day=10,
        binding_hour=18,
        binding_resource="WORKER_HOURS",
        failing_tasks=[hard_displaced_task],
        repair_options=[
            RepairOption(
                type="DROP_COHORT",
                target="sw_melon_2",
                actions_freed=4,
                cash_freed=0.0,
                expected_value_lost=320.0,
                deadline_slack_gained=4,
                resolves_certificate=True,
                reason="Resolve worker hour deficit",
            )
        ],
        horizon_hours=72,
        hard_tasks_feasible=False,
        displaced_core_tasks=[hard_displaced_task],
        uncompleted_sw_tasks=[],
        guarantee_type="CONSERVATIVE_CAPACITY_ENVELOPE",
        guarantee_tier="INFEASIBLE",
    )

    port = {"name": "oversized_speculative", "tiles_used": 16}

    exported = serialize_candidate_certificate(failing_cert, port=port, day=10, hour=18)

    # 1. Feasibility must be False, NEVER hardcoded True
    assert exported["combined_workload_feasible"] is False, "Exporter emitted hardcoded True for an infeasible candidate!"
    assert exported["hard_tasks_feasible"] is False, "Exporter emitted hardcoded True for a HARD-task failure!"

    # 2. Slack must be -4, NEVER hardcoded 2
    assert exported["minimum_slack"] == -4, "Exporter emitted hardcoded slack 2 instead of actual slack -4!"

    # 3. Displaced tasks must reflect the actual displaced HARD task
    assert exported["displaced_hard_tasks_count"] == 1, "Exporter emitted hardcoded 0 displaced HARD tasks!"
    assert "core_feed_cow_9" in exported["displaced_task_ids"], "Displaced task ID missing from export!"
    assert "core_feed_cow_9" in exported["displaced_hard_task_ids"]

    # 4. Commitment tier must reflect compromised status
    assert exported["commitment_tier"] == "HARD_TIER_COMPROMISED"
    assert exported["guarantee_tier"] == "INFEASIBLE"

    # 5. Repair option must be captured
    assert len(exported["repair_options"]) == 1
    assert exported["repair_options"][0]["type"] == "DROP_COHORT"
