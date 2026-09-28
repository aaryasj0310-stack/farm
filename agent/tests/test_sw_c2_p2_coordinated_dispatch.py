"""
Phase SW-C2: P2 Global Coordinated Regional Dispatch Unit Tests
Validates Stage 1 deadline protection, Stage 2 economic capacity allocation,
dynamic regional budgets with origin core protection, diagonal traversal prohibition,
and deterministic matching behavior.
"""

import copy
import pytest

from agent.config import (
    get_sw_p2_coordinated_dispatch_enabled,
    set_sw_p2_coordinated_dispatch_enabled,
    SHED_ACCESS_TILES,
    PORT_SW,
    PRIORITY_URGENT_SURVIVAL,
    PRIORITY_STANDARD_HARVEST,
    PRIORITY_BONUS_WATER,
    C2_MAX_SPILLOVER_DIST,
)
from agent.execution.coordinated_dispatch_controller import (
    CoordinatedDispatchController,
    get_coordinated_dispatch_controller,
    reset_coordinated_dispatch_controller,
)
from agent.execution.mission_ownership_tracker import (
    MissionOwnershipTracker,
    compute_task_obligation_id,
)


class MockFarm:
    def __init__(self, unlocked=None):
        self.unlocked = set(unlocked or ["NW", "NE", "SW"])
        self.farmer = (4, 4)
        self.hands = [(4, 5)]

    def quadrant_of(self, pos):
        x, y = pos
        if x < 5 and y < 5:
            return "NW"
        elif x >= 5 and y < 5:
            return "NE"
        elif x < 5 and y >= 5:
            return "SW"
        else:
            return "SE"


@pytest.fixture(autouse=True)
def cleanup_p2():
    set_sw_p2_coordinated_dispatch_enabled(False)
    reset_coordinated_dispatch_controller()
    yield
    set_sw_p2_coordinated_dispatch_enabled(False)
    reset_coordinated_dispatch_controller()


def test_default_flag_is_off():
    """Invariant: SW_P2_COORDINATED_DISPATCH_ENABLED must default to False."""
    assert get_sw_p2_coordinated_dispatch_enabled() is False


def test_stage1_deadline_protection():
    """Stage 1: Urgent survival/deadline tasks take precedence over high-reward discretionary work."""
    controller = CoordinatedDispatchController()
    farm = MockFarm()
    ctx = {"farm": farm, "day": 10, "hour": 8, "step": 248}

    # Worker 0 at (2, 2) [NW], Worker 1 at (3, 3) [NW]
    units = [(0, (2, 2)), (1, (3, 3))]
    holders = {"WHEAT": [0, 1]}
    home_quads = {0: "NW", 1: "NW"}
    active_missions = {}
    tracker = MissionOwnershipTracker()

    tasks = [
        # Discretionary high-prio harvest right next to worker 0
        {
            "op": "HARVEST",
            "target": (2, 2),
            "priority": 75.0,
            "kind": "crop_harvest",
            "args": ["CARROT"],
        },
        # Urgent survival feed at (4, 2)
        {
            "op": "FEED",
            "target": (4, 2),
            "priority": float(PRIORITY_URGENT_SURVIVAL + 50),
            "kind": "feed_rescue",
            "args": ["COW"],
        },
    ]

    assignment, busy, remaining = controller.plan_coordinated_dispatch(
        tasks=tasks,
        ctx=ctx,
        units=units,
        holders=holders,
        eligible_fn=lambda t: None,
        home_quads=home_quads,
        active_missions=active_missions,
        tracker=tracker,
    )

    telem = controller.get_telemetry()
    assert telem["stage1_protected_assignments"] == 1
    assert telem["deadlines_protected_count"] == 1

    # Worker 1 (closer to (4, 2)) or Worker 0 must take the survival feed
    feed_worker = [u for u, t in assignment.items() if t["op"] == "FEED"]
    assert len(feed_worker) == 1
    assert feed_worker[0] in (0, 1)


def test_dynamic_regional_budget_origin_protection():
    """Stage 2: NW/NE workers are blocked from crossing to SW if origin has pending tasks."""
    controller = CoordinatedDispatchController()
    farm = MockFarm()
    ctx = {"farm": farm, "day": 12, "hour": 10, "step": 298}

    # Worker 0 at (2, 2) [NW]
    units = [(0, (2, 2))]
    holders = {}
    home_quads = {0: "NW"}
    active_missions = {}
    tracker = MissionOwnershipTracker()

    tasks = [
        # Discretionary SW task
        {
            "op": "WATER",
            "target": (2, 7), # SW
            "priority": 30.0,
            "kind": "sw_water",
        },
        # Pending NW core task
        {
            "op": "WATER",
            "target": (1, 1), # NW
            "priority": 25.0,
            "kind": "core_water",
        },
    ]

    assignment, busy, remaining = controller.plan_coordinated_dispatch(
        tasks=tasks,
        ctx=ctx,
        units=units,
        holders=holders,
        eligible_fn=lambda t: None,
        home_quads=home_quads,
        active_missions=active_missions,
        tracker=tracker,
    )

    telem = controller.get_telemetry()
    assert telem["cross_region_transfers_denied"] >= 1
    # Worker 0 must have been assigned the NW task, NOT the SW task
    assert assignment[0]["target"] == (1, 1)


def test_dynamic_regional_budget_authorized_when_origin_clear():
    """Stage 2: NW worker is authorized to cross to SW when origin has no pending work."""
    controller = CoordinatedDispatchController()
    farm = MockFarm()
    ctx = {"farm": farm, "day": 12, "hour": 10, "step": 298}

    # Worker 0 at (2, 4) [NW border]
    units = [(0, (2, 4))]
    holders = {}
    home_quads = {0: "NW"}
    active_missions = {}
    tracker = MissionOwnershipTracker()

    tasks = [
        # Discretionary SW task only, no NW tasks
        {
            "op": "WATER",
            "target": (2, 6), # SW
            "priority": 30.0,
            "kind": "sw_water",
        },
    ]

    assignment, busy, remaining = controller.plan_coordinated_dispatch(
        tasks=tasks,
        ctx=ctx,
        units=units,
        holders=holders,
        eligible_fn=lambda t: None,
        home_quads=home_quads,
        active_missions=active_missions,
        tracker=tracker,
    )

    telem = controller.get_telemetry()
    assert telem["cross_region_transfers_authorized"] == 1
    assert assignment[0]["target"] == (2, 6)


def test_diagonal_traversal_prohibition():
    """Workers in NE cannot be dispatched to SW field tiles across diagonal."""
    controller = CoordinatedDispatchController()
    farm = MockFarm()
    ctx = {"farm": farm, "day": 15, "hour": 9, "step": 369}

    # Worker 0 at (8, 2) [NE]
    units = [(0, (8, 2))]
    holders = {}
    home_quads = {0: "NE"}
    active_missions = {}
    tracker = MissionOwnershipTracker()

    tasks = [
        {
            "op": "WATER",
            "target": (1, 8), # SW field tile (diagonal)
            "priority": 40.0,
            "kind": "sw_water",
        },
    ]

    assignment, busy, remaining = controller.plan_coordinated_dispatch(
        tasks=tasks,
        ctx=ctx,
        units=units,
        holders=holders,
        eligible_fn=lambda t: None,
        home_quads=home_quads,
        active_missions=active_missions,
        tracker=tracker,
    )

    # Diagonal traversal prohibited: worker 0 must NOT be assigned to (1, 8)
    assert 0 not in assignment
    assert len(remaining) == 1


def test_rule_w2_port_sw_anchoring():
    """SW squad workers picking up from shed anchor their target at PORT_SW."""
    controller = CoordinatedDispatchController()
    farm = MockFarm()
    ctx = {"farm": farm, "day": 5, "hour": 6, "step": 126}

    # Worker 0 belongs to SW squad
    units = [(0, (4, 6))]
    holders = {}
    home_quads = {0: "SW"}
    active_missions = {}
    tracker = MissionOwnershipTracker()

    tasks = [
        {
            "op": "PICKUP",
            "target": (4, 4), # Shed access tile
            "priority": 50.0,
            "kind": "pickup_seed",
            "args": ["CARROT"],
        }
    ]

    assignment, busy, remaining = controller.plan_coordinated_dispatch(
        tasks=tasks,
        ctx=ctx,
        units=units,
        holders=holders,
        eligible_fn=lambda t: None,
        home_quads=home_quads,
        active_missions=active_missions,
        tracker=tracker,
    )

    assert 0 in assignment
    # Target should be anchored to PORT_SW (Rule W2)
    assert assignment[0]["target"] == PORT_SW


def test_stage1_preempts_different_stage2_mission():
    """Stage 1 urgent task preempts a worker's existing Stage 2 mission."""
    controller = CoordinatedDispatchController()
    farm = MockFarm()
    ctx = {"farm": farm, "day": 10, "hour": 14, "step": 254}

    # Worker 0 currently traveling on a low-prio watering task in NW
    units = [(0, (1, 1))]
    holders = {"WHEAT": [0]}
    home_quads = {0: "NW"}
    active_missions = {
        0: {
            "task": {"op": "WATER", "target": (1, 3), "priority": 20.0},
            "target": (1, 3),
            "op": "WATER",
            "priority": 20.0,
        }
    }
    tracker = MissionOwnershipTracker()
    obl_old = compute_task_obligation_id(10, "WATER", (1, 3), "", None)
    tracker.claim_or_continue_mission(0, obl_old, active_missions[0]["task"], (1, 1), 253)

    tasks = [
        # Emergency feed
        {
            "op": "FEED",
            "target": (1, 1),
            "priority": float(PRIORITY_URGENT_SURVIVAL + 40),
            "kind": "feed_rescue",
            "args": ["COW"],
        }
    ]

    assignment, busy, remaining = controller.plan_coordinated_dispatch(
        tasks=tasks,
        ctx=ctx,
        units=units,
        holders=holders,
        eligible_fn=lambda t: None,
        home_quads=home_quads,
        active_missions=active_missions,
        tracker=tracker,
    )

    # Worker 0 must be assigned the emergency feed
    assert assignment[0]["op"] == "FEED"
    # Old mission must have been preempted
    tracker_telem = tracker.get_telemetry()
    assert tracker_telem["missions_preempted"] == 1
    assert tracker_telem["preemptions_by_reason"].get("STAGE1_DEADLINE_PREEMPTION", 0) == 1
