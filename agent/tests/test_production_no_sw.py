"""Unit test verifying that production defaults strictly freeze SW and SE out of production.

Verifies:
1. QUADRANT_HARD_BLOCK is {3, 4} by default.
2. should_buy_land rejects quadrant 3 as 'hard_blocked' even with infinite treasury.
3. MacroPlanner never emits buy_land for quadrant 3 under production defaults.
4. Main agent step never generates BUY_LAND market order for quadrant 3 under production defaults.
5. All experimental SW feature flags are False by default.
"""

import pytest
from unittest.mock import MagicMock
import config
from strategy.expansion_planner import should_buy_land
from strategy.macro_planner import MacroPlanner
from price_forecast import PriceForecast
from main import agent, reset_agent_state


class MockTile:
    def __init__(self, x, y, kind="EMPTY"):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_plant = False
        self.is_animal = False
        self.crop = None
        self.animal = None
        self.watered_today = False
        self.consecutive_unwatered = 0
        self.fed_today = False
        self.yield_units = 0


class MockFarm:
    def __init__(self, unlocked=("NW", "NE"), hands=(), farmer=(4, 4), money=50000.0):
        self.unlocked = set(unlocked)
        self.farmer = farmer
        self.hands = list(hands)
        self.money = money
        self.hires_today = 0
        self._tiles = {}
        for y in range(10):
            for x in range(10):
                q = self.quadrant_of((x, y))
                kind = "EMPTY" if q in self.unlocked else "LOCKED"
                self._tiles[(x, y)] = MockTile(x, y, kind=kind)

    def set_tile(self, pos, tile):
        self._tiles[pos] = tile

    def tile_at(self, pos):
        return self._tiles.get(pos)

    def quadrant_of(self, pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")

    def iter_tiles(self):
        return list(self._tiles.values())


@pytest.fixture(autouse=True)
def ensure_production_defaults():
    config.set_sw_experiment_arm("ArmA")
    yield
    config.set_sw_experiment_arm("ArmA")


def test_production_default_hard_block_is_3_and_4():
    """Verify production baseline hard-blocks quadrants 3 (SW) and 4 (SE)."""
    qhb = config.get_quadrant_hard_block()
    assert 3 in qhb, "Quadrant 3 (SW) must be hard-blocked by default in production"
    assert 4 in qhb, "Quadrant 4 (SE) must be hard-blocked by default in production"
    assert 1 not in qhb, "Quadrant 1 (NW) must be enabled"
    assert 2 not in qhb, "Quadrant 2 (NE) must be enabled"


def test_production_flags_disabled_by_default():
    """Verify all experimental SW flags are disabled in production baseline."""
    assert config.SW_CELL_HOUSING_ENABLED is False
    assert config.PERSISTENT_WORKER_LOCALITY_ENABLED is False
    assert config.DYNAMIC_SW_CROPS_ENABLED is False
    assert config.STRATEGIC_SW_OWNERSHIP_ENABLED is False
    assert config.SW_ACTIVATION_MODE == "production"
    assert config.SW_OWNERSHIP_MODE == "production"


def test_should_buy_land_rejects_sw_under_production_baseline():
    """Even with $50,000 in cash on Day 9, should_buy_land strictly rejects SW as hard_blocked."""
    farm = MockFarm(unlocked=("NW", "NE"), money=50000.0)
    buy, reason, diag = should_buy_land(
        next_quadrant=3,
        current_day=9,
        money=50000.0,
        farm=farm,
        hire_cost=0.0,
        feed_cost=0.0,
        animal_cost=0.0,
        reserve=300.0,
        roi=10.0,
        ow_factor=1.0,
    )
    assert buy is False
    assert reason == "hard_blocked"


def test_macro_planner_never_emits_sw_buy_land():
    """MacroPlanner must force-block buy_land when next_quadrant is 3."""
    fc = PriceForecast.load()
    planner = MacroPlanner(fc)

    farm = MockFarm(unlocked=("NW", "NE"), money=50000.0)
    private = MagicMock()
    private.shed = {}
    private.inventories = [{}]
    private.seeds = {}

    ctx = {
        "farm": farm,
        "private": private,
        "town": {"unlocked_shops": []},
        "day": 9,
        "hour": 0,
        "step": 216,
        "money": 50000.0,
    }

    plan = planner.build(ctx)
    assert plan.intents.get("buy_land") is False, "MacroPlanner must not emit buy_land for quadrant 3"


def test_agent_decision_never_generates_sw_buy_land_order():
    """Live agent decision must never produce a BUY_LAND order when farm already has NW and NE."""
    reset_agent_state()

    # Create observation where NW and NE are unlocked, money is $50,000, hour is 1 (land buying hour)
    obs = {
        "player": 0,
        "step": 217,
        "day": 9,
        "hour": 1,
        "farms": [
            {
                "money": 50000.0,
                "farmer": [4, 4],
                "hands": [[4, 4] for _ in range(6)],
                "unlocked_quadrants": ["NW", "NE"],
                "hires_today": 6,
                "tiles": [["EMPTY" for _ in range(10)] for _ in range(10)],
            },
            {
                "money": 5000.0,
                "farmer": [4, 4],
                "hands": [],
                "unlocked_quadrants": ["NW"],
                "hires_today": 0,
                "tiles": [["EMPTY" for _ in range(10)] for _ in range(10)],
            }
        ],
        "private": {
            "shed": {},
            "inventories": [{} for _ in range(7)],
            "seeds": {},
        },
        "market": {
            "inventory": {"WHEAT": 10000},
            "prices": {"WHEAT": 25},
        },
        "town": {
            "unlocked_shops": [],
        }
    }

    action = agent(obs)
    market_orders = action.get("market", [])
    buy_land_orders = [o for o in market_orders if o and o[0] == "BUY_LAND"]
    assert len(buy_land_orders) == 0, f"Production agent must NEVER issue BUY_LAND for SW: {buy_land_orders}"
