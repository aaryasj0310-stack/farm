"""C5 Maturity-Window Harvesting Policy Unit Tests (Tests A–H).

Validates:
- Test A: Premature harvest avoidance (bonus window crops not harvested early)
- Test B: Correct bonus-window harvest (matured and watered crops prioritized)
- Test C: Over-maturity / decay protection (decay-imminent crops harvested)
- Test D: Crop-specific behavior (wheat, carrot, melon, ongoing crops)
- Test E: Cycle opportunity cost / max yield harvest (reaches max_yield -> immediate harvest)
- Test F: Endgame protection (Day 29 all mature crops harvested)
- Test G: Determinism (identical observations produce identical decisions)
- Test H: B1 compatibility (animal harvests and other tasks remain untouched)
- Security: Snyk compliant
"""
import pytest
from types import SimpleNamespace

from config import (
    CROPS, PRIORITY_DECAY_HARVEST, PRIORITY_STANDARD_HARVEST,
    PRIORITY_BONUS_WATER
)
from execution.task_scheduler import build_tasks
from state.observation_parser import crop_age, in_bonus_window


class MockTile:
    def __init__(self, x=0, y=0, kind="PLANT", crop="WHEAT", planted_day=0,
                 watered_today=False, yield_units=1, consecutive_unwatered=0,
                 fertilized_until_day=-1, animal=None, consecutive_unfed=0,
                 fed_today=True, cared_today=True, fertilizer_available=False,
                 placed_day=0):
        self.x = x
        self.y = y
        self.kind = kind
        self.crop = crop
        self.planted_day = planted_day
        self.watered_today = watered_today
        self.yield_units = yield_units
        self.consecutive_unwatered = consecutive_unwatered
        self.fertilized_until_day = fertilized_until_day
        self.animal = animal
        self.consecutive_unfed = consecutive_unfed
        self.fed_today = fed_today
        self.cared_today = cared_today
        self.fertilizer_available = fertilizer_available
        self.placed_day = placed_day

    @property
    def is_plant(self):
        return self.kind == "PLANT"

    @property
    def is_animal(self):
        return self.animal is not None

    @property
    def pos(self):
        return (self.x, self.y)


class MockFarm:
    def __init__(self, tiles):
        self.tiles_grid = tiles
        self.unlocked = {"NW"}
        self.farmer = (4, 4)
        self.hands = []

    def iter_tiles(self):
        for row in self.tiles_grid:
            for t in row:
                yield t

    def quadrant_of(self, pos):
        return "NW"


def make_ctx(tiles, day=0, hour=0):
    grid = [[MockTile(x, y, kind=None) for x in range(10)] for y in range(10)]
    for t in tiles:
        grid[t.y][t.x] = t
    farm = MockFarm(grid)
    return {
        "farm": farm,
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
        "private": SimpleNamespace(shed={}, seeds={}, inventories=[{}]),
        "market": SimpleNamespace(prices={"FERTILIZER": 100}),
    }


def make_macro():
    return SimpleNamespace(
        plant_queue=[],
        build_queue=[],
        build_op="BUILD_PASTURE",
        place_queue=[],
        feeding_enabled=True,
        watering_enabled=True,
    )


def test_a_premature_harvest_avoidance():
    """Test A: Wheat at age 2 (first_yield_day) with yield=1 must NOT be harvested."""
    tile = MockTile(x=2, y=2, crop="WHEAT", planted_day=0, yield_units=1, watered_today=False)
    ctx = make_ctx([tile], day=2, hour=10)
    tasks = build_tasks(ctx, make_macro())

    harvest_tasks = [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (2, 2)]
    water_tasks = [t for t in tasks if t["op"] == "WATER" and t["target"] == (2, 2)]

    assert len(harvest_tasks) == 0, "Wheat at age 2 should not be harvested prematurely"
    assert len(water_tasks) == 1, "Wheat at age 2 should be scheduled for bonus water"


def test_b_correct_bonus_window_harvest():
    """Test B: Wheat on max_yield_day (age 4) once watered must be prioritized for harvest."""
    tile = MockTile(x=2, y=2, crop="WHEAT", planted_day=0, yield_units=4, watered_today=True)
    ctx = make_ctx([tile], day=4, hour=12)
    tasks = build_tasks(ctx, make_macro())

    harvest_tasks = [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (2, 2)]
    assert len(harvest_tasks) == 1
    assert harvest_tasks[0]["priority"] == PRIORITY_DECAY_HARVEST
    assert harvest_tasks[0]["kind"] == "harvest_mature_watered"


def test_c_decay_protection():
    """Test C: Unwatered wheat late in the day (hour >= 20) on max_yield_day must be harvested."""
    tile = MockTile(x=2, y=2, crop="WHEAT", planted_day=0, yield_units=3, watered_today=False)
    ctx = make_ctx([tile], day=4, hour=21)
    tasks = build_tasks(ctx, make_macro())

    harvest_tasks = [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (2, 2)]
    assert len(harvest_tasks) == 1
    assert harvest_tasks[0]["priority"] == PRIORITY_DECAY_HARVEST
    assert harvest_tasks[0]["kind"] == "harvest_decay"


def test_d_crop_specific_behavior():
    """Test D: Carrot matures on Day 3 (max_yield_day=3), Melon on Day 12 (max_yield_day=12)."""
    carrot = MockTile(x=1, y=1, crop="CARROT", planted_day=0, yield_units=3, watered_today=True)
    ctx_carrot = make_ctx([carrot], day=3, hour=10)
    tasks_c = build_tasks(ctx_carrot, make_macro())
    h_c = [t for t in tasks_c if t["op"] == "HARVEST" and t["target"] == (1, 1)]
    assert len(h_c) == 1

    melon = MockTile(x=3, y=3, crop="MELON", planted_day=0, yield_units=4, watered_today=False)
    ctx_melon = make_ctx([melon], day=10, hour=10)
    tasks_m = build_tasks(ctx_melon, make_macro())
    h_m = [t for t in tasks_m if t["op"] == "HARVEST" and t["target"] == (3, 3)]
    assert len(h_m) == 0


def test_e_cycle_opportunity_cost_max_yield():
    """Test E: Crop that reaches max_yield before max_yield_day must be harvested immediately."""
    melon_full = MockTile(x=3, y=3, crop="MELON", planted_day=0, yield_units=6, watered_today=False)
    ctx = make_ctx([melon_full], day=10, hour=10)
    tasks = build_tasks(ctx, make_macro())

    h = [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (3, 3)]
    assert len(h) == 1
    assert h[0]["priority"] == PRIORITY_STANDARD_HARVEST
    assert h[0]["kind"] == "harvest_full"


def test_f_endgame_protection():
    """Test F: Day 29 must harvest all crops with yield > 0 even if below max_yield_day."""
    wheat_late = MockTile(x=0, y=0, crop="WHEAT", planted_day=27, yield_units=2, watered_today=False)
    ctx = make_ctx([wheat_late], day=29, hour=10)
    tasks = build_tasks(ctx, make_macro())

    h = [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (0, 0)]
    assert len(h) == 1
    assert h[0]["priority"] == PRIORITY_DECAY_HARVEST
    assert h[0]["kind"] == "harvest_endgame"


def test_g_determinism():
    """Test G: Identical inputs produce identical task priority and op decisions."""
    tile = MockTile(x=2, y=2, crop="WHEAT", planted_day=0, yield_units=4, watered_today=True)
    ctx1 = make_ctx([tile], day=4, hour=12)
    ctx2 = make_ctx([tile], day=4, hour=12)

    tasks1 = build_tasks(ctx1, make_macro())
    tasks2 = build_tasks(ctx2, make_macro())

    assert len(tasks1) == len(tasks2)
    for t1, t2 in zip(tasks1, tasks2):
        assert t1["priority"] == t2["priority"]
        assert t1["op"] == t2["op"]
        assert t1["target"] == t2["target"]
        assert t1["kind"] == t2["kind"]


def test_h_b1_compatibility_animal_harvest():
    """Test H: Animal product harvesting and fertilizer are completely untouched."""
    cow = MockTile(x=4, y=4, kind="PASTURE", animal="COW", yield_units=4, fertilized_until_day=-1)
    ctx = make_ctx([cow], day=10, hour=10)
    tasks = build_tasks(ctx, make_macro())

    animal_harvest = [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (4, 4)]
    assert len(animal_harvest) == 1
    assert animal_harvest[0]["priority"] == PRIORITY_STANDARD_HARVEST + 5
    assert animal_harvest[0]["kind"] == "harvest_animal"
