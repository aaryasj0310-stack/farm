"""Reproducer for the rejected candidate; run against the archived after package."""
import pytest

from execution.task_scheduler import assign_tasks, reset_daily_log, get_active_missions
from test_clustered_dispatch import MockFarm, MockPrivate


@pytest.fixture(autouse=True)
def reset_dispatch():
    reset_daily_log()
    yield
    reset_daily_log()


def task(op, target, priority, kind):
    return {"op": op, "target": target, "priority": priority, "kind": kind, "args": []}


def plant(farm, pos):
    tile = farm._tiles_dict[pos]
    tile.is_plant = True
    tile.kind = "PLANT"
    tile.watered_today = False


def test_urgent_water_uses_closest_worker_even_with_another_mission():
    farm = MockFarm(["NW"], hands=[(0, 0)], farmer=(4, 3))
    plant(farm, (4, 4))
    plant(farm, (3, 3))
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 21}
    routine = task("WATER", (4, 4), 70, "water")
    assign_tasks([routine], ctx)
    assert 0 in get_active_missions()
    farm.farmer = (3, 3)
    ctx["hour"] = 22
    result = assign_tasks([routine, task("WATER", (3, 3), 100, "water")], ctx)
    assert result["actions"][0] == ["WATER"]


@pytest.mark.parametrize("owner_closer", [True, False])
def test_promoted_urgent_task_has_only_one_worker(owner_closer):
    farm = MockFarm(["NW"], hands=[(0, 0)], farmer=(4, 2))
    plant(farm, (4, 4))
    ctx = {"farm": farm, "private": MockPrivate(), "day": 5, "hour": 21}
    assign_tasks([task("WATER", (4, 4), 70, "water")], ctx)
    assert 0 in get_active_missions()
    farm.farmer = (4, 3)
    if not owner_closer:
        farm.hands = [(4, 4)]
    ctx["hour"] = 22
    result = assign_tasks([task("WATER", (4, 4), 100, "water")], ctx)
    assigned = [u for u, t in result["assignment"].items()
                if t["op"] == "WATER" and t["target"] == (4, 4)]
    assert assigned == ([0] if owner_closer else [1])
