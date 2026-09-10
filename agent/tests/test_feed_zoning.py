"""Tests for production-critical FEED bypassing zoning.

Requirements:
- SW production-day animal fed by NW wheat holder when no SW holder exists
- Zoning does not strand production-critical FEED
- Rescue FEED outranks production FEED
- Production FEED does not preempt emergency watering/decay
- Only units holding wheat can receive FEED
"""

import pytest
from config import (
    PRIORITY_URGENT_SURVIVAL,
    PRIORITY_PROD_DAY_FEED,
    PRIORITY_DECAY_HARVEST,
)
from execution.task_scheduler import assign_tasks


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


class MockFarm:
    def __init__(self, unlocked, hands=None, farmer=(2, 2)):
        self.unlocked = set(unlocked)
        self.farmer = farmer
        self.hands = list(hands or [])
        self.money = 5000.0
        self._tiles_dict = {}
        for y in range(10):
            for x in range(10):
                q = self.quadrant_of((x, y))
                kind = "EMPTY" if q in self.unlocked else "LOCKED"
                self._tiles_dict[(x, y)] = MockTile(x, y, kind=kind)

    def quadrant_of(self, pos):
        x, y = pos
        if x < 5 and y < 5:
            return "NW"
        elif x >= 5 and y < 5:
            return "NE"
        elif x < 5 and y >= 5:
            return "SW"
        return "SE"

    def iter_tiles(self):
        return list(self._tiles_dict.values())


class MockPrivate:
    def __init__(self, inventories=None):
        self.seeds = {}
        self.shed = {}
        self.inventories = list(inventories or [{} for _ in range(10)])


def test_sw_production_animal_fed_by_nw_wheat_holder_when_no_sw_holder_exists():
    """SW production animal is fed by NW worker when no SW worker holds wheat."""
    # Farmer (unit 0) in NW holds wheat. Hand (unit 1) in SW has NO wheat.
    farm = MockFarm(["NW", "SW"], hands=[(2, 7)], farmer=(2, 2))
    private = MockPrivate(inventories=[{"WHEAT": 5}, {}])
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 2}

    tasks = [
        # Routine task in NW
        {"priority": 70, "op": "WATER", "target": (1, 1), "kind": "water_routine", "args": []},
        # Production feed in SW
        {"priority": PRIORITY_PROD_DAY_FEED, "op": "FEED", "target": (3, 7),
         "kind": "feed_prod", "args": [], "meta": {"wheat": 1}},
    ]

    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Unit 0 (NW wheat holder) must receive the SW production feed task!
    assert 0 in asg, "NW wheat holder should be assigned"
    assert asg[0]["kind"] == "feed_prod"
    assert asg[0]["target"] == (3, 7)
    # Unit 1 (SW worker without wheat) must NOT receive FEED
    if 1 in asg:
        assert asg[1]["op"] != "FEED"


def test_zoning_does_not_strand_production_critical_feed():
    """NW worker is not blocked from SW feed by home zone task backlog."""
    # Farmer (unit 0) in NW holds wheat.
    farm = MockFarm(["NW", "SW"], hands=[], farmer=(2, 2))
    private = MockPrivate(inventories=[{"WHEAT": 3}])
    ctx = {"farm": farm, "private": private, "day": 12, "hour": 4}

    tasks = [
        # Multiple home zone tasks in NW with priority 75
        {"priority": 75, "op": "WATER", "target": (1, 1), "kind": "water", "args": []},
        {"priority": 75, "op": "WATER", "target": (2, 1), "kind": "water", "args": []},
        # Production feed in SW (priority 85)
        {"priority": PRIORITY_PROD_DAY_FEED, "op": "FEED", "target": (2, 8),
         "kind": "feed_prod", "args": [], "meta": {"wheat": 1}},
    ]

    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    # Even though NW has regular tasks, production feed (85) bypasses zoning
    assert asg[0]["kind"] == "feed_prod"
    assert asg[0]["target"] == (2, 8)


def test_rescue_feed_outranks_production_feed():
    """feed_rescue (priority 99) outranks feed_prod (priority 85) for a single wheat holder."""
    farm = MockFarm(["NW", "SW"], hands=[], farmer=(2, 2))
    private = MockPrivate(inventories=[{"WHEAT": 1}])
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 5}

    tasks = [
        {"priority": PRIORITY_PROD_DAY_FEED, "op": "FEED", "target": (1, 8),
         "kind": "feed_prod", "args": [], "meta": {"wheat": 1}},
        {"priority": PRIORITY_URGENT_SURVIVAL - 1, "op": "FEED", "target": (3, 8),
         "kind": "feed_rescue", "args": [], "meta": {"wheat": 1}},
    ]

    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    assert asg[0]["kind"] == "feed_rescue"
    assert asg[0]["target"] == (3, 8)


def test_production_feed_does_not_preempt_emergency_watering_or_decay():
    """Emergency watering (100) and decay harvest (90) outrank production feed (85)."""
    # 2 workers: one holding wheat, one not
    farm = MockFarm(["NW"], hands=[(2, 3)], farmer=(2, 2))
    private = MockPrivate(inventories=[{"WHEAT": 2}, {}])
    ctx = {"farm": farm, "private": private, "day": 10, "hour": 6}

    tasks = [
        # Emergency watering (prio 100)
        {"priority": PRIORITY_URGENT_SURVIVAL, "op": "WATER", "target": (1, 1),
         "kind": "water_emergency", "args": []},
        # Decay harvest (prio 90)
        {"priority": PRIORITY_DECAY_HARVEST, "op": "HARVEST", "target": (3, 3),
         "kind": "harvest_decay", "args": []},
        # Production feed (prio 85)
        {"priority": PRIORITY_PROD_DAY_FEED, "op": "FEED", "target": (4, 4),
         "kind": "feed_prod", "args": [], "meta": {"wheat": 1}},
    ]

    res = assign_tasks(tasks, ctx)
    asg = res["assignment"]

    assigned_kinds = {asg[u]["kind"] for u in asg}
    # Both higher priority tasks must be assigned before production feed
    assert "water_emergency" in assigned_kinds
    assert "harvest_decay" in assigned_kinds
    assert "feed_prod" not in assigned_kinds  # 2 units took the 2 top priority tasks
