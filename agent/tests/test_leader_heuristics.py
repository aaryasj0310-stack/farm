import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CROPS, FEED_WHEAT_BUFFER_DAYS, SHED_SOFT_CAP, SHED_RESUME_CAP
from observation_parser import parse_observation
from strategy.macro_planner import MacroPlanner
from strategy.expansion_planner import should_buy_land
from market.market_brain import MarketBrain


class FakeFC:
    def __init__(self):
        self.prices = {
            'WHEAT': 25.0, 'CARROT': 35.0, 'TOMATO': 60.0,
            'STRAWBERRY': 120.0, 'MELON': 250.0, 'EGG': 50.0,
            'MILK': 160.0, 'WOOL': 200.0, 'FERTILIZER': 100.0,
        }

    def expected_price(self, product, day):
        return self.prices.get(product, 50.0)

    def prob_floor(self, product, day):
        return 0.0


def make_ctx(day=0, hour=0, money=3000.0, shed=None, seeds=None, animals=0, unlocked=('NW',)):
    products = ['WHEAT', 'CARROT', 'TOMATO', 'STRAWBERRY', 'MELON',
                'EGG', 'MILK', 'WOOL', 'FERTILIZER']
    inventory = {p: 10000 for p in products}
    board = 10
    tiles = [[None] * board for _ in range(board)]
    for y in range(board):
        for x in range(board):
            quad = 'NW' if (x < 5 and y < 5) else ('NE' if (x >= 5 and y < 5) else ('SW' if (x < 5 and y >= 5) else 'SE'))
            if quad not in unlocked:
                tiles[y][x] = 'LOCKED'
    for k in range(animals):
        tiles[0][k] = {'kind': 'PASTURE', 'animal': 'COW', 'placed_day': 1,
                       'yield_units': 0, 'fed_today': True, 'cared_today': False,
                       'consecutive_unfed': 0, 'fertilizer_available': False,
                       'pending_care_bonus': 0}

    farm = {
        'money': money, 'tiles': tiles, 'farmer': [4, 4], 'hands': [],
        'unlocked_quadrants': list(unlocked), 'hires_today': 0
    }
    obs = {
        'player': 0, 'day': day, 'hour': hour,
        'farms': [farm, farm],
        'market': {'inventory': inventory, 'prices': {}},
        'town': {'unlocked_shops': []},
        'private': {'shed': dict(shed or {}), 'seeds': dict(seeds or {}),
                    'inventories': [{}]}
    }
    return parse_observation(obs)


class MockFarm:
    def __init__(self, unlocked=None):
        self.unlocked = set(unlocked or ['NW'])

    def iter_tiles(self):
        return []


def test_day0_melon_springboard_allocation():
    fc = FakeFC()
    ctx = make_ctx(day=0, hour=0, money=3000.0)
    plan = MacroPlanner(fc).build(ctx)

    melon_plants = [pos for pos, c in plan.plant_queue if c == 'MELON']
    wheat_plants = [pos for pos, c in plan.plant_queue if c == 'WHEAT']

    assert len(melon_plants) == 12, f'Expected 12 melons, got {len(melon_plants)}'
    assert len(wheat_plants) == 8, f'Expected 8 wheat, got {len(wheat_plants)}'
    assert len(plan.plant_queue) == 20
    assert plan.intents['buy_seed'].get('MELON') == 12
    assert plan.intents['buy_seed'].get('WHEAT') == 8


def test_days_1_2_fallow_tiles_preserved():
    fc = FakeFC()
    ctx = make_ctx(day=1, hour=0, money=1950.0)
    plan = MacroPlanner(fc).build(ctx)
    assert len(plan.plant_queue) == 0, 'Expected fallow tiles to remain empty on Day 1'

    ctx2 = make_ctx(day=2, hour=0, money=1930.0)
    plan2 = MacroPlanner(fc).build(ctx2)
    assert len(plan2.plant_queue) == 0, 'Expected fallow tiles to remain empty on Day 2'


def test_early_ne_land_buy_day3_to_5():
    farm = MockFarm(['NW'])
    ok_d2, reason_d2, _ = should_buy_land(2, 2, 1500, farm)
    assert not ok_d2

    ok_d3, reason_d3, _ = should_buy_land(2, 3, 1400, farm)
    assert ok_d3, f'Expected NE unlock on Day 3 with ,400, got reason: {reason_d3}'
    assert reason_d3 == 'early_ne_leader_unlock'

    ok_d4_poor, _, _ = should_buy_land(2, 4, 1300, farm)
    assert not ok_d4_poor

    ok_d5, reason_d5, _ = should_buy_land(2, 5, 1450, farm)
    assert ok_d5


def test_market_brain_emergency_shed_relief():
    brain = MarketBrain(FakeFC())
    ctx = make_ctx(day=10, hour=2, shed={'MELON': 72})
    orders, details = brain.sell_orders(ctx)

    assert details['urgency'] == 1
    assert len(orders) > 0
    total_units_sold = sum(o[2] for o in orders)
    assert total_units_sold == 17
    assert all(o[1] == 'MELON' for o in orders)


def test_market_brain_feed_buffer_strictly_protected():
    brain = MarketBrain(FakeFC())
    ctx = make_ctx(day=6, hour=1, shed={'WHEAT': 10}, animals=2)
    orders, _ = brain.sell_orders(ctx)

    wheat_orders = [o for o in orders if o[1] == 'WHEAT']
    assert len(wheat_orders) == 1
    assert wheat_orders[0][2] == 2, f'Expected exactly 2 wheat sold (10 - 8 reserved), got {wheat_orders[0][2]}'
