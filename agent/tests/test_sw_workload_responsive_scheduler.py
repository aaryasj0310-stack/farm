"""Regression tests for isolated SW P1.1 workload-responsive scheduler.

This arm must change only home-zone allocation.  Purchase logic, SW activation,
crop policy, treasury gates, and production defaults remain unchanged.
"""
import config
from config import (
    EFFECTIVE_ACTIONS_PER_UNIT,
    PORT_SW,
    SW_P1_PURCHASE_COMMITTED_HERD_ONLY,
    get_sw_workload_responsive_scheduler,
    set_sw_workload_responsive_scheduler,
)
from execution import task_scheduler as scheduler
from execution.task_scheduler import (
    assign_tasks,
    compute_workload_aware_home_quadrants,
    get_home_quadrant,
)


class MockTile:
    def __init__(self, x, y, kind="EMPTY"):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.crop = None
        self.animal = None
        self.is_plant = False
        self.is_animal = False
        self.fertilizer_available = False
        self.watered_today = True
        self.consecutive_unwatered = 0
        self.yield_units = 0


class MockFarm:
    def __init__(self, n_hands=12):
        self.unlocked = {"NW", "NE", "SW"}
        self.farmer = (4, 4)
        self.hands = [(4, 4)] * n_hands
        self.money = 10000.0
        self._tiles = {
            (x, y): MockTile(x, y, kind="EMPTY")
            for y in range(10) for x in range(10)
        }

    @staticmethod
    def quadrant_of(pos):
        x, y = pos
        if x < 5 and y < 5:
            return "NW"
        if x >= 5 and y < 5:
            return "NE"
        if x < 5 and y >= 5:
            return "SW"
        return "SE"

    def iter_tiles(self):
        return list(self._tiles.values())

    def tile_at(self, pos):
        return self._tiles.get(tuple(pos))


class MockPrivate:
    def __init__(self, n_units=13):
        self.seeds = {}
        self.shed = {}
        self.inventories = [{} for _ in range(n_units)]


def _positions(n=13):
    return {i: (4, 4) if i < 7 else (7, 2) for i in range(n)}


def _task(target, *, priority=75, op="WATER", kind="water"):
    return {"priority": priority, "op": op, "target": target, "kind": kind, "args": []}


def _homes(tasks, n=13):
    farm = MockFarm(n_hands=n - 1)
    return compute_workload_aware_home_quadrants(
        tasks,
        farm,
        n,
        _positions(n),
        protect_core_discretionary_before_sw=True,
        exclude_shed_logistics_from_sw=True,
    )


def test_flag_defaults_off_and_legacy_rule_w1_is_unchanged():
    assert get_sw_workload_responsive_scheduler() is False
    # 13 total units -> legacy Rule W1 reserves 5 for SW.
    homes = {i: get_home_quadrant(i, 13, {"NW", "NE", "SW"}) for i in range(13)}
    assert sum(q == "SW" for q in homes.values()) == 5


def test_sw_owned_zero_sw_work_gets_zero_sw_workers():
    tasks = (
        [_task((2, 2), priority=75) for _ in range(24)]
        + [_task((7, 2), priority=75) for _ in range(24)]
    )
    homes = _homes(tasks)
    assert sum(q == "SW" for q in homes.values()) == 0
    assert sum(q in ("NW", "NE") for q in homes.values()) == 13


def test_one_sw_task_never_creates_five_worker_squad():
    tasks = (
        [_task((2, 2), priority=75) for _ in range(12)]
        + [_task((7, 2), priority=75) for _ in range(12)]
        + [_task((2, 7), priority=75)]
    )
    homes = _homes(tasks)
    sw = sum(q == "SW" for q in homes.values())
    assert sw == 1


def test_core_discretionary_backlog_is_protected_before_sw():
    # 24 mandatory core tasks require 2 units in each core zone.
    # 48 discretionary tasks in each core zone require another 4 + 4 units.
    # Only one unit remains for SW even though SW has heavy demand.
    tasks = (
        [_task((2, 2), priority=75) for _ in range(24)]
        + [_task((7, 2), priority=75) for _ in range(24)]
        + [_task((2, 3), priority=65, op="HARVEST", kind="harvest") for _ in range(48)]
        + [_task((7, 3), priority=65, op="HARVEST", kind="harvest") for _ in range(48)]
        + [_task((2, 7), priority=75) for _ in range(48)]
    )
    homes = _homes(tasks)
    assert sum(q == "NW" for q in homes.values()) >= 6
    assert sum(q == "NE" for q in homes.values()) >= 6
    assert sum(q == "SW" for q in homes.values()) <= 1


def test_genuine_surplus_is_available_to_sw():
    tasks = (
        [_task((2, 2), priority=75) for _ in range(12)]
        + [_task((7, 2), priority=75) for _ in range(12)]
        + [_task((2, 7), priority=75) for _ in range(24)]
    )
    homes = _homes(tasks)
    # 1 NW + 1 NE protected, then two workers justified by 24 SW tasks.
    assert sum(q == "SW" for q in homes.values()) == 2


def test_port_sw_shed_pickup_does_not_create_sw_agricultural_demand():
    tasks = [
        {
            "priority": 95,
            "op": "PICKUP",
            "target": PORT_SW,
            "kind": "pickup_wheat",
            "args": ["WHEAT", 3],
        }
    ]
    homes = _homes(tasks)
    assert sum(q == "SW" for q in homes.values()) == 0


def test_port_sw_product_delivery_does_not_create_sw_agricultural_demand():
    tasks = [
        {
            "priority": 98,
            "op": "PLACE",
            "target": PORT_SW,
            "kind": "deposit_product",
            "args": ["CARROT", 4],
        }
    ]
    homes = _homes(tasks)
    assert sum(q == "SW" for q in homes.values()) == 0


def test_assign_tasks_flag_on_does_not_anchor_idle_sw_workers():
    farm = MockFarm(n_hands=12)
    private = MockPrivate(13)
    ctx = {"farm": farm, "private": private, "day": 12, "hour": 2, "step": 290}
    old_p1 = config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY
    try:
        set_sw_workload_responsive_scheduler(True)
        assert scheduler.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED is True
        res = assign_tasks([], ctx)
        assert not any(
            t.get("kind") == "sw_anchor"
            for t in res["assignment"].values()
        )
        # Scheduler toggle must not alter the isolated P1 purchase flag.
        assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY == old_p1
    finally:
        set_sw_workload_responsive_scheduler(False)


def test_flag_off_still_anchors_legacy_sw_squad():
    # Put the legacy SW squad away from PORT_SW so W2 emits anchor missions.
    farm = MockFarm(n_hands=12)
    farm.hands = [(4, 4)] * 7 + [(1, 9)] * 5
    private = MockPrivate(13)
    ctx = {"farm": farm, "private": private, "day": 12, "hour": 2, "step": 290}
    set_sw_workload_responsive_scheduler(False)
    res = assign_tasks([], ctx)
    anchors = [t for t in res["assignment"].values() if t.get("kind") == "sw_anchor"]
    assert len(anchors) == 5


def test_existing_dynamic_allocator_default_order_is_unchanged():
    # The old dynamic allocator remains SW-before-core-discretionary unless
    # the new P1.1 parameters are explicitly requested.
    farm = MockFarm(n_hands=12)
    tasks = (
        [_task((2, 2), priority=75) for _ in range(12)]
        + [_task((7, 2), priority=75) for _ in range(12)]
        + [_task((2, 3), priority=65, op="HARVEST", kind="harvest") for _ in range(48)]
        + [_task((7, 3), priority=65, op="HARVEST", kind="harvest") for _ in range(48)]
        + [_task((2, 7), priority=75) for _ in range(24)]
    )
    legacy = compute_workload_aware_home_quadrants(tasks, farm, 13, _positions(13))
    p11 = compute_workload_aware_home_quadrants(
        tasks, farm, 13, _positions(13),
        protect_core_discretionary_before_sw=True,
        exclude_shed_logistics_from_sw=True,
    )
    assert sum(q == "SW" for q in legacy.values()) >= sum(q == "SW" for q in p11.values())
