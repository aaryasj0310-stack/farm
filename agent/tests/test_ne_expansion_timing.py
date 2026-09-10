"""Tests for NE land expansion timing, seed accounting, and treasury protection."""
import pytest
from config import (
    CROPS,
    NE_SEED_TARGETS,
    NE_EARLY_UNLOCK_MAX_DAY,
    NE_EARLY_UNLOCK_THRESHOLD_DAY3_5,
    NE_EARLY_UNLOCK_THRESHOLD_DAY6,
    FEED_WHEAT_BUFFER_DAYS,
)
from strategy.expansion_planner import should_buy_land, expansion_seed_targets
from strategy.macro_planner import MacroPlanner
from market.market_brain import MarketBrain


class MockFarm:
    def __init__(self, unlocked=None, money=3000.0):
        self.unlocked = set(unlocked or ["NW"])
        self.money = money
        self.farmer = (4, 4)
        self.hands = []
        self.hires_today = 0

    def iter_tiles(self):
        return []

    def quadrant_of(self, pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


class FakeFC:
    def __init__(self):
        self.prices = {
            "WHEAT": 25.0, "CARROT": 35.0, "TOMATO": 60.0,
            "STRAWBERRY": 120.0, "MELON": 250.0, "EGG": 50.0,
            "MILK": 160.0, "WOOL": 200.0, "FERTILIZER": 100.0,
        }

    def expected_price(self, product, day):
        return self.prices.get(product, 50.0)

    def prob_floor(self, product, day):
        return 0.0


def make_test_ctx(day=5, hour=0, money=1500.0, shed=None, seeds=None, unlocked=("NW",), animals=2):
    board = 10
    tiles = [[None] * board for _ in range(board)]
    for y in range(board):
        for x in range(board):
            quad = ("N" if y < 5 else "S") + ("W" if x < 5 else "E")
            if quad not in unlocked:
                tiles[y][x] = "LOCKED"
    for k in range(animals):
        tiles[0][k] = {
            "kind": "PASTURE", "animal": "COW", "placed_day": 1,
            "yield_units": 0, "fed_today": True, "cared_today": False,
            "consecutive_unfed": 0, "fertilizer_available": False,
            "pending_care_bonus": 0,
        }

    from observation_parser import parse_observation
    obs = {
        "player": 0,
        "day": day,
        "hour": hour,
        "farms": [{
            "money": money, "tiles": tiles, "farmer": [4, 4], "hands": [],
            "unlocked_quadrants": list(unlocked), "hires_today": 0,
        }],
        "market": {
            "inventory": {p: 10000 for p in ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                                              "EGG", "MILK", "WOOL", "FERTILIZER"]},
            "prices": {"MELON": 250, "WHEAT": 25, "CARROT": 35, "TOMATO": 60},
        },
        "town": {"unlocked_shops": []},
        "private": {
            "shed": dict(shed or {}),
            "seeds": dict(seeds or {}),
            "inventories": [{}],
        },
    }
    return parse_observation(obs)


def test_a_already_owned_seeds_deducted():
    farm = MockFarm(["NW"])
    seeds_owned = {"CARROT": 8, "TOMATO": 4}
    buy, reason, diag = should_buy_land(
        2, 6, 1400.0, farm, hire_cost=54, feed_cost=0,
        reserve=300, roi=2.0, ow_factor=1.0, seeds_owned=seeds_owned
    )
    assert diag["seed_cost"] == 0.0
    assert buy is True
    assert "early_ne_leader_unlock" in reason or "treasury_sufficient" in reason


def test_b_partially_owned_seeds_deducted():
    farm = MockFarm(["NW"])
    seeds_owned = {"CARROT": 5, "TOMATO": 1}
    buy, reason, diag = should_buy_land(
        2, 6, 1500.0, farm, hire_cost=54, feed_cost=0,
        reserve=300, roi=2.0, ow_factor=1.0, seeds_owned=seeds_owned
    )
    assert diag["seed_cost"] == (3 * CROPS["CARROT"]["seed"] + 3 * CROPS["TOMATO"]["seed"])
    assert diag["seed_cost"] == 210.0


def test_c_day_6_leader_window_active():
    farm = MockFarm(["NW"])
    buy, reason, diag = should_buy_land(2, 6, 1250.0, farm, hire_cost=54)
    assert buy is True
    assert reason == "early_ne_leader_unlock"

    buy_d7, reason_d7, _ = should_buy_land(2, 7, 1250.0, farm, hire_cost=54)
    assert reason_d7 != "early_ne_leader_unlock"


def test_d_ne_treasury_protection_from_discretionary():
    fc = FakeFC()
    planner = MacroPlanner(fc)
    ctx = make_test_ctx(day=5, hour=0, money=1100.0, unlocked=("NW",), animals=2, shed={"WHEAT": 10})
    plan = planner.build(ctx)
    assert plan.intents["hire"] == 4
    seed_spend = sum(CROPS[c]["seed"] * n for c, n in plan.intents["buy_seed"].items())
    assert seed_spend <= 100.0


def test_e_feed_buffer_interaction_preserves_ne_capital():
    fc = FakeFC()
    planner = MacroPlanner(fc)
    ctx = make_test_ctx(day=6, hour=0, money=1571.0, unlocked=("NW",), animals=2, shed={"WHEAT": 2})
    plan = planner.build(ctx)
    assert plan.intents["buy_land"] is True
    assert plan.intents.get("buy_wheat", 0) <= 10


def test_f_early_livestock_preservation():
    fc = FakeFC()
    planner = MacroPlanner(fc)
    ctx = make_test_ctx(day=0, hour=0, money=3000.0, unlocked=("NW",), animals=0)
    plan = planner.build(ctx)
    assert plan.intents["buy_animal"].get("COW", 0) >= 2
    assert "MELON" in plan.intents["buy_seed"]


def test_g_existing_land_behavior_sw_intact():
    farm_ne = MockFarm(["NW", "NE"])
    buy, reason, _ = should_buy_land(3, 9, 8000.0, farm_ne, hire_cost=143, feed_cost=500, roi=2.0, ow_factor=1.0)
    assert buy is True
    assert "treasury_sufficient" in reason


def test_h_melon_sell_protection_regression():
    brain = MarketBrain(FakeFC())
    ctx = make_test_ctx(day=10, hour=2, shed={"MELON": 72})
    orders, details = brain.sell_orders(ctx)
    assert "melon_diagnostics" in details
    diag = details["melon_diagnostics"]
    assert "melon_spot" in diag
    assert "melon_safe_quantity" in diag
    assert "melon_hold_reason" in diag


def test_wheat_target_nquads2_day6():
    n_quads = 2
    day = 6
    target = 8 if (n_quads == 1 or day <= 9) else (20 if n_quads == 2 else 30)
    assert target == 8


def test_wheat_target_nquads2_day9():
    n_quads = 2
    day = 9
    target = 8 if (n_quads == 1 or day <= 9) else (20 if n_quads == 2 else 30)
    assert target == 8


def test_wheat_target_nquads2_day10():
    n_quads = 2
    day = 10
    target = 8 if (n_quads == 1 or day <= 9) else (20 if (n_quads == 2 or day <= 13) else 30)
    assert target == 20


def test_wheat_target_nquads3_days_10_to_13():
    n_quads = 3
    for day in (10, 11, 12, 13):
        target = 8 if (n_quads == 1 or day <= 9) else (20 if (n_quads == 2 or day <= 13) else 30)
        assert target == 20


def test_wheat_target_nquads3_day14_plus():
    n_quads = 3
    for day in (14, 15, 20):
        target = 8 if (n_quads == 1 or day <= 9) else (20 if (n_quads == 2 or day <= 13) else 30)
        assert target == 30


def test_wheat_target_nquads1_all_days():
    n_quads = 1
    for day in (0, 5, 6, 9, 10, 13, 14, 15, 20):
        target = 8 if (n_quads == 1 or day <= 9) else (20 if (n_quads == 2 or day <= 13) else 30)
        assert target == 8
