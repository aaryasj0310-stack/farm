"""Sale proceeds must be investable before the animal purchase deadline."""
from market.order_builder import OrderBuilder
from test_macro_planner import make_ctx
from execution.task_scheduler import assign_tasks


def livestock_ctx(day=11, hour=13, money=8000, unlocked=("NW", "NE", "SW")):
    ctx = make_ctx(day=day, money=money, unlocked=unlocked,
                   shed={"WHEAT": 20},
                   structures=[(0, 5, {"kind": "PASTURE"}),
                               (1, 5, {"kind": "PASTURE"})])
    ctx["hour"] = hour
    return ctx


def test_invests_daytime_proceeds_in_available_livestock_housing():
    intents = {"buy_animal": {"SHEEP": 2}, "buy_wheat": 3,
               "hire": 12, "buy_land": True, "buy_seed": {"MELON": 12}}
    orders, _ = OrderBuilder().reinvest_livestock(livestock_ctx(), intents)
    assert ["BUY_ANIMAL", "SHEEP", 2] in orders
    assert all(o[0] in ("BUY_ANIMAL", "BUY_PRODUCT") for o in orders)


def test_reinvestment_preserves_deadline_land_fund_and_placement_time():
    intents = {"buy_animal": {"SHEEP": 2}}
    for ctx in [livestock_ctx(day=12), livestock_ctx(hour=21),
                livestock_ctx(hour=0), livestock_ctx(unlocked=("NW", "NE")),
                livestock_ctx(money=300)]:
        orders, _ = OrderBuilder().reinvest_livestock(ctx, intents)
        assert not orders


def test_animal_holder_can_deliver_across_zones_with_home_work_pending():
    ctx = livestock_ctx()
    ctx["farm"].farmer = (3, 4)
    ctx["farm"].hands = [(4, 4)] * 12
    ctx["private"].inventories = [{"SHEEP": 1}] + [{} for _ in range(12)]
    tasks = [{"op": "PLACE", "target": (0, 5), "args": ["SHEEP"],
              "kind": "place_animal", "priority": 84}]
    tasks += [{"op": "WATER", "target": (x, 1), "args": [],
               "kind": "water", "priority": 70} for x in range(5)]
    assignments = assign_tasks(tasks, ctx)["assignment"]
    assert assignments[0]["op"] == "PLACE"
    assert assignments[0]["target"] == (0, 5)


def test_finishes_local_animal_service_before_travelling_to_routine_water():
    ctx = livestock_ctx(unlocked=("NW",))
    ctx["farm"].farmer = (3, 4)
    tasks = [
        {"op": "CARE", "target": (3, 4), "args": [], "kind": "care", "priority": 65},
        {"op": "WATER", "target": (0, 0), "args": [], "kind": "water", "priority": 70},
    ]
    assert assign_tasks(tasks, ctx)["actions"][0] == ["CARE"]
    tasks[1]["priority"] = 100
    assert assign_tasks(tasks, ctx)["assignment"][0]["op"] == "WATER"
