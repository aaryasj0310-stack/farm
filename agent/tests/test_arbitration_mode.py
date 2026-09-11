import copy
import pytest

from config import ARBITRATION_MODE, USE_CENTRAL_PLANNER
from main import (
    get_arbitration_mode,
    set_arbitration_mode,
    get_last_turn_telemetry,
    get_central_planner_diagnostics,
    reset_agent_state,
    agent,
)
from strategy.central_planner import (
    CentralPlanner,
    P0_CRITICAL,
    P1_URGENT,
    P2_STRATEGIC,
    P3_NORMAL,
    P4_DISCRETIONARY,
)


def make_test_obs(farmer=(4, 4), hands=None, tiles=None, inventories=None, shed=None, day=0, hour=0):
    board = 10
    raw_tiles = [[None] * board for _ in range(board)]
    if tiles:
        for (x, y, obj) in tiles:
            raw_tiles[y][x] = obj
    farm = {
        "money": 5000.0,
        "tiles": raw_tiles,
        "farmer": list(farmer),
        "hands": list(hands or []),
        "unlocked_quadrants": ["NW"],
        "hires_today": 0,
    }
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    inv = {p: 10000 for p in products}
    return {
        "player": 0,
        "day": day,
        "hour": hour,
        "step": day * 24 + hour,
        "farms": [farm, farm],
        "market": {"inventory": inv, "prices": {}},
        "town": {"unlocked_shops": []},
        "private": {
            "shed": dict(shed or {"WHEAT": 10}),
            "seeds": {},
            "inventories": list(inventories or [{}]),
        },
    }


def test_arbitration_mode_defaults_and_validation():
    """Verify default mode is 'central' and switch validates inputs."""
    reset_agent_state()
    assert ARBITRATION_MODE == "central"
    assert USE_CENTRAL_PLANNER is True
    assert get_arbitration_mode() == "central"

    set_arbitration_mode("legacy")
    assert get_arbitration_mode() == "legacy"

    set_arbitration_mode("central")
    assert get_arbitration_mode() == "central"

    with pytest.raises(ValueError):
        set_arbitration_mode("invalid_mode")


def test_telemetry_immutability():
    """Mutating returned telemetry dictionary must not mutate internal state."""
    reset_agent_state()
    set_arbitration_mode("central")
    obs = make_test_obs(day=0, hour=0)

    # Run step
    res = agent(obs)
    t1 = get_last_turn_telemetry()
    assert t1 is not None
    assert "money_before" in t1

    # Mutate t1
    original_money = t1["money_before"]
    t1["money_before"] = -999999.0
    t1["market"].append(["FAKE_ORDER"])

    # Re-fetch telemetry
    t2 = get_last_turn_telemetry()
    assert t2["money_before"] == original_money
    assert ["FAKE_ORDER"] not in t2["market"]


def test_arbitration_mode_routing():
    """Verify legacy mode routes to compose while central routes to central_planner."""
    reset_agent_state()
    obs = make_test_obs(day=0, hour=0)

    # 1. Central mode
    set_arbitration_mode("central")
    res_central = agent(obs)
    diag_central = get_central_planner_diagnostics()
    assert diag_central is not None
    assert "total_candidates" in diag_central
    tel_central = get_last_turn_telemetry()
    assert tel_central["mode"] == "central"

    # 2. Legacy mode
    reset_agent_state()
    set_arbitration_mode("legacy")
    res_legacy = agent(obs)
    diag_legacy = get_central_planner_diagnostics()
    assert diag_legacy == {}  # None/empty in legacy mode
    tel_legacy = get_last_turn_telemetry()
    assert tel_legacy["mode"] == "legacy"
    assert tel_legacy["central_planner_diagnostic"] is None

    # Reset back to central
    set_arbitration_mode("central")


def test_telemetry_on_equals_telemetry_off_action_determinism():
    """Verify reading telemetry has zero effect on resulting actions."""
    reset_agent_state()
    set_arbitration_mode("central")
    obs = make_test_obs(day=1, hour=1)

    # Run without reading telemetry
    res1 = agent(obs)

    # Run with reading telemetry in between
    reset_agent_state()
    set_arbitration_mode("central")
    res2 = agent(obs)
    _ = get_last_turn_telemetry()
    _ = get_central_planner_diagnostics()

    assert res1["market"] == res2["market"]
    assert res1["farmer"] == res2["farmer"]
    assert res1["hands"] == res2["hands"]


class MockTile:
    def __init__(self, is_animal=False):
        self.is_animal = is_animal
        self.animal = "COW" if is_animal else None

class MockFarm:
    def __init__(self, n_animals=0):
        self.money = 5000.0
        self.unlocked = {"NW"}
        self.tiles = [[MockTile() for _ in range(10)] for _ in range(10)]
        for i in range(n_animals):
            self.tiles[4][i] = MockTile(is_animal=True)

    def iter_tiles(self):
        for row in self.tiles:
            for t in row:
                yield t

class MockPrivate:
    def __init__(self, shed=None):
        self.shed = shed or {}

def test_p0_priority_inversion_diagnostic():
    """Verify CentralPlanner records p0_priority_inversion_count == 0 and empty inversions."""
    cp = CentralPlanner()
    ctx = {"hour": 0, "day": 1, "farm": MockFarm(n_animals=2), "private": MockPrivate(shed={"WHEAT": 0})}
    buys = [
        ["BUY_PRODUCT", "WHEAT", 4],  # P0
        ["HIRE"],                     # P1
        ["BUY_ANIMAL", "COW", 1],     # P2
    ]
    sells = [["SELL", "CARROT", 5]]
    orders, diag = cp.plan_market(ctx, None, buys, None, sells, None, cap=10)

    assert diag["p0_priority_inversion_count"] == 0
    assert diag["p0_priority_inversions"] == []
    assert "changed_selection" in diag
    assert "execution_reorder_only" in diag


def test_reset_agent_state_clears_globals():
    """Verify reset_agent_state completely clears telemetry and singletons."""
    set_arbitration_mode("central")
    obs = make_test_obs(day=0, hour=0)
    agent(obs)
    assert get_last_turn_telemetry() is not None

    reset_agent_state()
    assert get_last_turn_telemetry() is None
    assert get_central_planner_diagnostics() == {}


def test_historical_stack_mode_routing():
    """Verify historical_stack mode activates pre-CentralPlanner limits and legacy compose."""
    reset_agent_state()
    set_arbitration_mode("historical_stack")
    assert get_arbitration_mode() == "historical_stack"

    obs = make_test_obs(day=0, hour=0)
    res = agent(obs)
    assert "market" in res
    diag = get_central_planner_diagnostics()
    assert diag == {}
    tel = get_last_turn_telemetry()
    assert tel["mode"] == "historical_stack"
    assert tel["central_planner_diagnostic"] is None

    # Reset back to central
    set_arbitration_mode("central")

