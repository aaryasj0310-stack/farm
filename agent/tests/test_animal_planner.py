"unit tests for animal_planner"

import pytest
from strategy.animal_planner import (
    get_animal_targets,
    HERD_CAP,
    SHEEP_CAP,
    COW_CAP,
)


def test_day_bounds():
    res_0 = get_animal_targets(0, 3000, 10, {})
    assert res_0['GOOSE'] == 0
    res_29 = get_animal_targets(29, 3000, 10, {})
    assert res_29['GOOSE'] == 0

    with pytest.raises(ValueError):
        get_animal_targets(-1, 3000, 10, {})
    res_30 = get_animal_targets(30, 3000, 10, {})
    assert res_30['GOOSE'] == 0


def test_zero_geese_policy():
    for day in (0, 5, 10, 15, 20):
        res = get_animal_targets(day, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 2})
        assert res['GOOSE'] == 0


def test_c4_late_uneconomic_purchase_prevented():
    """Test 2: Late uneconomic animal purchases are strictly prevented on/after cutoff."""
    # On Day 12 (cutoff boundary) and later, planner must not plan new animal purchases
    res_12 = get_animal_targets(12, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=10)
    assert res_12['COW'] == 0
    assert res_12['SHEEP'] == 0
    assert res_12['GOOSE'] == 0

    # On Day 23 (late season), even with excess cash, planner refuses additions
    res_23 = get_animal_targets(23, 10000, 50, {'COW': 2, 'SHEEP': 3, 'GOOSE': 0}, max_pastures=10)
    assert res_23['COW'] == 2
    assert res_23['SHEEP'] == 3
    assert res_23['GOOSE'] == 0

    # Gestation lag boundary: on Day 24, remaining=5 < 6/8, zero yields possible
    res_24 = get_animal_targets(24, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0})
    assert res_24['COW'] == 0
    assert res_24['SHEEP'] == 0


def test_c4_early_economically_justified_purchases_allowed():
    """Test 1: Animal purchases before the cutoff remain possible when economically justified."""
    # Day 10 (prior to Day 12 cutoff), with ample cash, wheat, and pasture capacity
    res_10 = get_animal_targets(10, 10000, 50, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=9)
    assert res_10['SHEEP'] > 0 or res_10['COW'] > 0
    assert res_10['GOOSE'] == 0


def test_c4_cash_reserve_preserved():
    """Test 4: Cash reserve is strictly preserved; cannot purchase without money + feed reserve."""
    # Money only covers animal cost, but not feed buffer
    res_low_cash = get_animal_targets(6, 410, 0, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=4)
    # Cow costs 400 + 3*25=75 feed reserve = 475 needed; 410 is insufficient
    assert res_low_cash['COW'] == 0
    assert res_low_cash['SHEEP'] == 0


def test_c4_no_illegal_orders_and_geese():
    """Test 5: No illegal animal targets (negative counts or geese) are ever generated."""
    for day in range(0, 30):
        res = get_animal_targets(day, 5000, 20, {'COW': 1, 'SHEEP': 2, 'GOOSE': 0}, max_pastures=5)
        assert res['COW'] >= 1
        assert res['SHEEP'] >= 2
        assert res['GOOSE'] == 0
        assert res['COW'] + res['SHEEP'] <= 5


def test_c4_macro_planner_pasture_cutoff():
    """Test 7: MacroPlanner suppresses pasture construction and animal buys post-cutoff."""
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast
    fc = PriceForecast.load()
    # Mock context at Day 13 with empty pasture
    class MockFarm:
        money = 10000.0
        hands = [(3, 3)] * 12
        unlocked = {"NW", "NE", "SW"}
        farmer = (4, 4)
        def iter_tiles(self):
            return []
        def quadrant_of(self, pos):
            return "SW"
    ctx = {
        "day": 13,
        "hour": 0,
        "farm": MockFarm(),
        "private": type("MockPrivate", (), {"shed": {"WHEAT": 50}, "seeds": {}, "inventories": [{}]})(),
        "market": type("MockMarket", (), {"inventory": {}, "prices": {}})(),
        "town": type("MockTown", (), {"unlocked_shops": []})(),
    }
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)
    assert plan.intents.get("buy_animal", {}) == {}
    assert plan.build_queue == []



def test_town_drainage_caps():
    res = get_animal_targets(0, 100000, 500, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=50)
    assert res['SHEEP'] <= SHEEP_CAP
    assert res['COW'] <= COW_CAP
    assert res['SHEEP'] + res['COW'] <= HERD_CAP


def test_spatial_pasture_cap():
    res = get_animal_targets(0, 100000, 500, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0}, max_pastures=4)
    assert res['SHEEP'] + res['COW'] <= 4


def test_feed_buffer_constraint():
    res_no_feed = get_animal_targets(0, 450, 0, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0})
    assert res_no_feed['COW'] == 0
    assert res_no_feed['wool'] == 0 if 'wool' in res_no_feed else True

    res_with_wheat = get_animal_targets(0, 450, 5, {'COW': 0, 'SHEEP': 0, 'GOOSE': 0})
    assert res_with_wheat['COW'] == 1


def make_test_ctx(day=0, money=3000.0, unlocked=("NW",), shed=None):
    from state.observation_parser import parse_observation
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    half = 5
    quads = {("N", "W"): "NW", ("N", "E"): "NE",
             ("S", "W"): "SW", ("S", "E"): "SE"}
    for y in range(board):
        for x in range(board):
            q = quads[("N" if y < half else "S", "W" if x < half else "E")]
            if q not in unlocked:
                tiles[y][x] = "LOCKED"
    farm = {
        "money": money,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4]] * 4,
        "unlocked_quadrants": list(unlocked),
        "hires_today": 0,
    }
    obs = {
        "player": 0, "day": day, "hour": 0,
        "farms": [farm, farm],
        "market": {"inventory": {"WHEAT": 10000}, "prices": {"WHEAT": 25}},
        "town": {"unlocked_shops": []},
        "private": {"shed": dict(shed or {}), "seeds": {}, "inventories": [{}]},
    }
    return parse_observation(obs)


def test_early_pasture_planned_before_sw():
    """Test 1: Early pasture can be planned before SW expansion."""
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast
    from config import EARLY_PASTURE_TILES
    
    fc = PriceForecast.load()
    ctx = make_test_ctx(day=0, money=3000.0, unlocked=("NW",))
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)
    assert plan.build_op == "BUILD_PASTURE"
    assert len(plan.build_queue) > 0
    assert all(pos in EARLY_PASTURE_TILES for pos in plan.build_queue)


def test_circular_dependency_broken_animal_buy_order_emitted():
    """Test 2: Circular dependency broken: animal buy order emitted when pasture is being built."""
    from market.order_builder import OrderBuilder
    class MockTile:
        def __init__(self, x, y):
            self.pos = (x, y); self.kind = None; self.is_animal = False
    class MockFarm:
        money = 3000.0; hands = [(4, 4)] * 4; unlocked = {"NW"}; farmer = (4, 4)
        def iter_tiles(self):
            return [MockTile(x, y) for x in range(5) for y in range(5)]
    ctx = {
        "day": 0, "hour": 0, "farm": MockFarm(),
        "private": type("MockPrivate", (), {"shed": {}, "seeds": {}, "inventories": [{}]})(),
        "market": type("MockMarket", (), {"inventory": {"WHEAT": 10000}, "prices": {"WHEAT": 25}})(),
        "town": type("MockTown", (), {"unlocked_shops": []})(),
    }
    intents = {
        "hire": 0,
        "buy_animal": {"COW": 2},
        "pending_structures": {"PASTURE": 2},
    }
    builder = OrderBuilder()
    orders, ledger = builder.build(ctx, intents)
    animal_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
    assert len(animal_orders) > 0
    assert animal_orders[0][1] == "COW"
    assert animal_orders[0][2] == 2


def test_c4_cutoff_strictly_preserved():
    """Test 3: C4 cutoff strictly preserved: 0 new animals on/after Day 12."""
    for d in (12, 13, 20, 28):
        res = get_animal_targets(d, 50000, 100, {"COW": 1, "SHEEP": 1, "GOOSE": 0}, max_pastures=10)
        assert res["COW"] == 1
        assert res["SHEEP"] == 1
        assert res["GOOSE"] == 0


def test_feed_safety_invariant():
    """Test 4: Feed safety invariant: animal not bought if feed buffer cannot be maintained."""
    # Cash only enough for animal but not for feed reserve
    res_unsafe = get_animal_targets(0, 420, 0, {"COW": 0, "SHEEP": 0, "GOOSE": 0}, max_pastures=2)
    assert res_unsafe["COW"] == 0
    assert res_unsafe["SHEEP"] == 0


def test_no_displacement_of_day0_melon_tiles():
    """Test 5: No displacement of Day 0 melon tiles."""
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast
    fc = PriceForecast.load()
    ctx = make_test_ctx(day=0, money=3000.0, unlocked=("NW",))
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)
    melons_planned = sum(1 for pos, crop in plan.plant_queue if crop == "MELON")
    assert melons_planned == 12, f"Expected 12 melons, got {melons_planned}"
    # Verify pasture tiles and melon tiles are disjoint
    build_set = set(plan.build_queue)
    plant_set = {pos for pos, _ in plan.plant_queue}
    assert not (build_set & plant_set), "Pasture and plant tiles must be disjoint"


def test_preservation_of_ne_land_purchase_fund():
    """Test 6: Preservation of NE land purchase fund ($1,000 reserve on Days 3–5)."""
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast
    fc = PriceForecast.load()
    ctx = make_test_ctx(day=3, money=1200.0, unlocked=("NW",), shed={"WHEAT": 10})
    planner = MacroPlanner(fc)
    plan = planner.build(ctx)
    assert plan.intents.get("buy_animal", {}) == {}



