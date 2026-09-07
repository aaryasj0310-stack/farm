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
