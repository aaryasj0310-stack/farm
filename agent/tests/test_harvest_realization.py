"""Harvest -> worker -> shed -> sale realization regression tests."""
from types import SimpleNamespace

from execution.task_scheduler import build_tasks, assign_tasks
from main import _predict_same_turn_product_deposits
from market.market_brain import MarketBrain
from state.observation_parser import parse_observation
from tests.engine_bridge import get_engine


class MockTile:
    def __init__(
        self, x=0, y=0, kind=None, crop=None, planted_day=0,
        watered_today=True, yield_units=0, consecutive_unwatered=0,
        fertilized_until_day=-1, animal=None, placed_day=0,
        fed_today=True, cared_today=True, consecutive_unfed=0,
        fertilizer_available=False,
    ):
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
        self.placed_day = placed_day
        self.fed_today = fed_today
        self.cared_today = cared_today
        self.consecutive_unfed = consecutive_unfed
        self.fertilizer_available = fertilizer_available

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
    def __init__(self, tiles=(), farmer=(4, 4), hands=(), unlocked=("NW",), money=5000):
        self._grid = [[MockTile(x, y) for x in range(10)] for y in range(10)]
        for t in tiles:
            self._grid[t.y][t.x] = t
        self.farmer = tuple(farmer)
        self.hands = [tuple(h) for h in hands]
        self.unlocked = set(unlocked)
        self.money = money
        self.hires_today = 0

    def iter_tiles(self):
        for row in self._grid:
            for t in row:
                yield t

    def quadrant_of(self, pos):
        x, y = tuple(pos)
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")

    def tile_at(self, pos):
        x, y = tuple(pos)
        return self._grid[y][x]


def macro():
    return SimpleNamespace(
        plant_queue=[],
        build_queue=[],
        build_op="BUILD_PASTURE",
        place_queue=[],
        feeding_enabled=True,
        watering_enabled=True,
    )


def ctx_for(
    *, day=28, hour=10, tiles=(), farmer=(4, 4), hands=(),
    shed=None, inventories=None, unlocked=("NW",),
):
    farm = MockFarm(tiles, farmer=farmer, hands=hands, unlocked=unlocked)
    n_units = 1 + len(hands)
    invs = list(inventories or [{} for _ in range(n_units)])
    while len(invs) < n_units:
        invs.append({})
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    return {
        "farm": farm,
        "private": SimpleNamespace(
            shed=dict(shed or {}),
            seeds={},
            inventories=[dict(i) for i in invs],
        ),
        "market": SimpleNamespace(
            inventory={p: 10000 for p in products},
            prices={"FERTILIZER": 100},
        ),
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
    }


class FakeFC:
    def prob_floor(self, product, day):
        return 0.0

    def expected_price(self, product, day):
        return {
            "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
            "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200,
            "FERTILIZER": 100,
        }.get(product, 50)


def market_ctx(day=29, hour=10, shed=None, workers=None):
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    grid = [[None for _ in range(10)] for _ in range(10)]
    for y in range(10):
        for x in range(10):
            if x >= 5 or y >= 5:
                grid[y][x] = "LOCKED"
    farm = {
        "money": 5000, "tiles": grid, "farmer": [4, 4], "hands": [],
        "unlocked_quadrants": ["NW"], "hires_today": 0,
    }
    obs = {
        "player": 0, "day": day, "hour": hour, "farms": [farm, farm],
        "market": {"inventory": {p: 10000 for p in products}, "prices": {}},
        "town": {"unlocked_shops": []},
        "private": {
            "shed": dict(shed or {}),
            "seeds": {},
            "inventories": [dict(i) for i in (workers or [{}])],
        },
    }
    return parse_observation(obs)


def test_real_engine_harvest_deposit_sell_chain_realizes_cash():
    eng = get_engine()
    farm = eng._new_farm(10, 3000)
    private = eng._new_private()
    market = eng._new_market()

    plant = eng._new_plant("CARROT", 0, 24)
    plant["yield_units"] = 3
    farm["tiles"][2][2] = plant
    farm["farmer"] = [2, 2]

    eng._apply_unit_action(farm, private, 0, ["HARVEST"], 10, 3, 24)
    assert private["inventories"][0]["CARROT"] == 3

    farm["farmer"] = [4, 4]
    eng._apply_unit_action(farm, private, 0, ["PLACE", "CARROT", 3], 10, 3, 24)
    assert private["inventories"][0].get("CARROT", 0) == 0
    assert private["shed"]["CARROT"] == 3

    before = farm["money"]
    for _ in range(3):
        price = eng.market_price("CARROT", market["inventory"]["CARROT"])
        assert eng._commit_unit("SELL", "CARROT", price, farm, private, market)
    assert farm["money"] > before
    assert private["shed"]["CARROT"] == 0


def test_endgame_product_only_inventory_gets_single_drop_mission():
    ctx = ctx_for(day=29, inventories=[{"CARROT": 2, "MELON": 3}])
    tasks = build_tasks(ctx, macro())
    deliveries = [t for t in tasks if t.get("kind") == "deposit_product"]
    assert len(deliveries) == 1
    assert deliveries[0]["op"] == "DROP"
    assert deliveries[0]["meta"]["required_unit"] == 0
    assert deliveries[0]["meta"]["deposit_units"] == 5


def test_mixed_feed_inventory_uses_selective_product_deposit():
    goose = MockTile(
        2, 2, kind="COOP", animal="GOOSE", placed_day=0,
        fed_today=False, consecutive_unfed=1,
    )
    ctx = ctx_for(
        day=29, tiles=[goose],
        inventories=[{"WHEAT": 2, "CARROT": 3}],
    )
    tasks = build_tasks(ctx, macro())
    deliveries = [t for t in tasks if t.get("kind") == "deposit_product"]
    assert deliveries
    assert deliveries[0]["op"] == "PLACE"
    assert deliveries[0]["args"] == ["CARROT", 3]


def test_delivery_never_reserves_more_than_shed_room():
    ctx = ctx_for(
        day=28,
        shed={"MELON": 99},
        inventories=[{"CARROT": 5}],
    )
    tasks = build_tasks(ctx, macro())
    deliveries = [t for t in tasks if t.get("kind") == "deposit_product"]
    assert len(deliveries) == 1
    assert deliveries[0]["op"] == "PLACE"
    assert deliveries[0]["args"] == ["CARROT", 1]


def test_multiple_carriers_get_carrier_bound_delivery_tasks():
    ctx = ctx_for(
        day=29,
        hands=[(4, 4)],
        inventories=[{"CARROT": 2}, {"MELON": 2}],
    )
    tasks = build_tasks(ctx, macro())
    deliveries = [t for t in tasks if t.get("kind") == "deposit_product"]
    assert {t["meta"]["required_unit"] for t in deliveries} == {0, 1}


def test_assign_tasks_keeps_delivery_on_actual_carrier():
    ctx = ctx_for(
        day=29,
        farmer=(0, 0),
        hands=[(4, 4)],
        inventories=[{}, {"CARROT": 3}],
    )
    task = [{
        "priority": 98, "op": "PLACE", "target": (4, 4),
        "args": ["CARROT", 3], "kind": "deposit_product",
        "meta": {"required_unit": 1},
    }]
    asg = assign_tasks(task, ctx)
    assert 1 in asg["assignment"]
    assert asg["assignment"][1]["kind"] == "deposit_product"


def test_urgent_feed_preempts_lower_product_delivery_for_same_worker():
    ctx = ctx_for(
        day=28,
        inventories=[{"WHEAT": 1, "CARROT": 3}],
    )
    tasks = [
        {
            "priority": 105, "op": "FEED", "target": (2, 2), "args": [],
            "kind": "feed_rescue", "meta": {"wheat": 1},
        },
        {
            "priority": 88, "op": "PLACE", "target": (4, 4),
            "args": ["CARROT", 3], "kind": "deposit_product",
            "meta": {"required_unit": 0},
        },
    ]
    asg = assign_tasks(tasks, ctx)
    assert asg["assignment"][0]["op"] == "FEED"


def test_same_turn_deposit_prediction_requires_actual_deposit_action():
    ctx = ctx_for(day=29, inventories=[{"CARROT": 3}])
    task = {
        "priority": 98, "op": "PLACE", "target": (4, 4),
        "args": ["CARROT", 3], "kind": "deposit_product",
        "meta": {"required_unit": 0},
    }
    moving = {"assignment": {0: dict(task)}, "actions": {0: ["WEST"]}}
    assert _predict_same_turn_product_deposits(ctx, moving) == {}

    executing = {"assignment": {0: dict(task)}, "actions": {0: ["PLACE", "CARROT", 3]}}
    assert _predict_same_turn_product_deposits(ctx, executing) == {"CARROT": 3}


def test_same_turn_drop_prediction_handles_multiple_products():
    ctx = ctx_for(day=29, shed={"WHEAT": 95}, inventories=[{"CARROT": 2, "MELON": 3}])
    task = {
        "priority": 98, "op": "DROP", "target": (4, 4),
        "args": [], "kind": "deposit_product",
        "meta": {"required_unit": 0},
    }
    asg = {"assignment": {0: task}, "actions": {0: ["DROP"]}}
    assert _predict_same_turn_product_deposits(ctx, asg) == {"CARROT": 2, "MELON": 3}


def test_market_can_sell_scheduler_confirmed_same_turn_deposit():
    ctx = market_ctx(day=29, hour=10, shed={}, workers=[{"CARROT": 3}])
    ctx["scheduled_product_deposits"] = {"CARROT": 3}
    orders, details = MarketBrain(FakeFC()).sell_orders(ctx)
    assert ["SELL", "CARROT", 3] in orders
    assert details["scheduled_product_deposits"] == {"CARROT": 3}


def test_carried_inventory_contributes_to_shed_pressure():
    ctx = market_ctx(
        day=10, hour=2,
        shed={"CARROT": 60},
        workers=[{"MELON": 10}],
    )
    orders, details = MarketBrain(FakeFC()).sell_orders(ctx)
    assert details["pressure"] is True
    assert details["pending_occupancy"] == 70
    assert orders


def test_full_shed_blocks_deposit_until_sales_create_room():
    ctx = ctx_for(
        day=28,
        shed={"CARROT": 100},
        inventories=[{"MELON": 4}],
    )
    tasks = build_tasks(ctx, macro())
    assert not [t for t in tasks if t.get("kind") == "deposit_product"]


def test_day29_impossible_late_harvest_is_suppressed():
    crop = MockTile(
        0, 0, kind="PLANT", crop="WHEAT", planted_day=25,
        yield_units=4, watered_today=True,
    )
    ctx = ctx_for(day=29, hour=23, tiles=[crop], farmer=(4, 4))
    tasks = build_tasks(ctx, macro())
    assert not [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (0, 0)]


def test_day29_near_shed_harvest_remains_when_realizable():
    crop = MockTile(
        4, 4, kind="PLANT", crop="WHEAT", planted_day=25,
        yield_units=4, watered_today=True,
    )
    ctx = ctx_for(day=29, hour=22, tiles=[crop], farmer=(4, 4))
    tasks = build_tasks(ctx, macro())
    assert [t for t in tasks if t["op"] == "HARVEST" and t["target"] == (4, 4)]
