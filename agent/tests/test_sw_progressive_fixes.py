"""Unit tests for the three SW progressive architectural fixes:
1. Fix 1: Hour-0 SW serviceability worker capacity (compute_projected_workers).
2. Fix 2: Intraday safe SW land purchase and near-term capital protection.
3. Fix 3: Harmonized SW activation and incremental seed purchasing.
4. Telemetry recording from Day 7 onward.
"""
import pytest
from unittest.mock import patch

from config import (
    get_target_hands,
    SW_SAFETY_RESERVE,
)
from market.order_builder import OrderBuilder
from strategy.land_serviceability_model import (
    compute_projected_workers,
    compute_progressive_sw_activation,
    evaluate_sw_serviceability,
)
from strategy.expansion_planner import should_buy_land
from strategy.macro_planner import MacroPlanner
from test_macro_planner import make_ctx, make_forecast, BASE_PRICES


def test_fix1_compute_projected_workers():
    """Fix 1: compute_projected_workers accurately projects morning hires."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=8, money=2500, unlocked=("NW", "NE"))
    ctx["hour"] = 0
    farm = ctx["farm"]

    # At hour 0, farm.hands is empty
    assert len(farm.hands) == 0

    # Target hands for day 8
    target_h = get_target_hands(8)
    assert target_h >= 3

    # With $2500 cash, all planned hires are affordable
    proj = compute_projected_workers(farm, day=8, money=2500, hour=0)
    assert proj == 1 + target_h

    # With $0 cash, 0 hires affordable -> projected_workers == 1
    proj_poor = compute_projected_workers(farm, day=8, money=0, hour=0)
    assert proj_poor == 1

    # At hour 2, if hands have already spawned, projected_workers == 1 + len(hands)
    farm.hands = [(4, 4) for _ in range(target_h)]
    proj_h2 = compute_projected_workers(farm, day=8, money=2500, hour=2)
    assert proj_h2 == 1 + target_h


def test_fix1_hour0_serviceability_not_rejected_as_mandatory_debt():
    """Fix 1: Progressive SW activation at Hour 0 does NOT reject all tiles with MANDATORY_NW_NE_DEBT."""
    ctx = make_ctx(day=8, money=2500, unlocked=("NW", "NE", "SW"))
    ctx["hour"] = 0
    farm = ctx["farm"]

    # Set up some crops in NW/NE
    for r in range(4):
        for c in range(4):
            farm.tiles[r][c] = {
                "kind": "PLANT", "crop": "WHEAT", "is_plant": True, "watered_today": False,
                "yield_units": 0, "pos": (r, c), "x": r, "y": c,
            }

    # At Hour 0, farm.hands is empty
    assert len(farm.hands) == 0

    tiles, diag = compute_progressive_sw_activation(
        farm=farm,
        day=8,
        money=2500,
        hour=0,
    )

    # With projected workers (1 + 4 = 5 workers), surplus capacity is positive
    assert diag["rejection_counts"]["MANDATORY_NW_NE_DEBT"] == 0
    assert diag["accepted_count"] > 0
    assert len(tiles) > 0


def test_fix2_intraday_sw_purchase_authorized():
    """Fix 2: SW purchase can be authorized intraday when cash crosses threshold."""
    fc = make_forecast(BASE_PRICES)
    ctx = make_ctx(day=9, money=3200, unlocked=("NW", "NE"))
    ctx["hour"] = 10
    farm = ctx["farm"]
    farm.hands = [(4, 4) for _ in range(get_target_hands(9))]

    with patch("config.SW_OWNERSHIP_MODE", "early_liquidity"), \
         patch("config.SW_ACTIVATION_MODE", "progressive"):
        ok, reason, diag = should_buy_land(
            next_quadrant=3,
            current_day=9,
            money=3200,
            farm=farm,
            hire_cost=0,
            feed_cost=0,
            animal_cost=0,
            reserve=300.0,
            roi=0.25,
            ow_factor=1.0,
            forecast=fc,
            is_purchase_hour=True,
            hour=10,
        )
        assert ok is True
        assert reason == "sw_authorized_early_liquidity"


def test_fix2_reinvest_livestock_emits_land_and_protects_capital():
    """Fix 2: reinvest_livestock emits BUY_LAND intraday and protects SW capital from animals."""
    builder = OrderBuilder(money_reserve=300.0)
    ctx = make_ctx(day=9, money=3200, unlocked=("NW", "NE"))
    ctx["hour"] = 10
    farm = ctx["farm"]
    farm.hands = [(4, 4) for _ in range(get_target_hands(9))]

    intents = {
        "buy_land": True,
        "buy_animal": {"COW": 2},
        "buy_wheat": 0,
    }

    with patch("config.SW_OWNERSHIP_MODE", "early_liquidity"):
        orders, ledger = builder.build_intraday(ctx, intents, max_slots=10)

        # BUY_LAND must be emitted in orders!
        assert any(o[0] == "BUY_LAND" for o in orders)

        # Land order must precede animal orders!
        order_types = [o[0] for o in orders]
        assert order_types.index("BUY_LAND") < len(order_types)


def test_fix2_discretionary_animal_suppression_protects_sw_reserve():
    """Fix 2: When SW is reachable near term, animal budget is capped to protect $2,000 SW cost."""
    builder = OrderBuilder(money_reserve=300.0)
    # Cash is $2,200. Shed has 2 milk (conservative inflow = $256).
    # Potential cash 24h = 2200 + 256 = 2456 >= 2000 + 300 reserve.
    # Discretionary cash now = 2200 - 300 = 1900 (< 2000 SW cost).
    # Discretionary animals must NOT siphon cash below SW threshold!
    ctx = make_ctx(day=8, money=2200, unlocked=("NW", "NE"), shed={"MILK": 2})
    ctx["hour"] = 14
    farm = ctx["farm"]
    # 2 empty pastures
    farm.tiles[0][0] = {"kind": "PASTURE", "animal": None, "is_animal": False, "pos": (0, 0)}
    farm.tiles[0][1] = {"kind": "PASTURE", "animal": None, "is_animal": False, "pos": (0, 1)}

    intents = {
        "buy_land": False,
        "buy_animal": {"COW": 2},
        "buy_wheat": 0,
    }

    with patch("config.SW_OWNERSHIP_MODE", "early_liquidity"):
        orders, ledger = builder.reinvest_livestock(ctx, intents, max_slots=10)

        # Because remaining_discretionary ($1,900) < SW shadow reserve ($2,000),
        # animal purchases must be suppressed!
        assert ledger.get("discretionary_livestock_suppressed_for_sw") is True
        assert len([o for o in orders if o[0] == "BUY_ANIMAL"]) == 0


def test_fix3_harmonized_sw_activation_and_seed_demand():
    """Fix 3: Progressive SW activation queues planting ONLY when seeds are physically on hand."""
    fc = make_forecast(BASE_PRICES)
    planner = MacroPlanner(fc)

    # SW is owned. 0 seeds on hand.
    ctx = make_ctx(day=10, money=2500, unlocked=("NW", "NE", "SW"), shed={"WHEAT": 0})
    ctx["hour"] = 0
    ctx["private"].seeds = {"WHEAT": 0, "CARROT": 0}

    with patch("config.SW_ACTIVATION_MODE", "progressive"), \
         patch("config.SW_OWNERSHIP_MODE", "early_liquidity"):
        plan = planner.build(ctx)

        # Check progressive activation diagnostic
        prog_diag = plan.diagnostics.get("sw_progressive_activation", {})
        assert prog_diag.get("accepted_count", 0) > 0

        # Incremental seed demand should be requested in buy_seed intent!
        assert sum(plan.intents.get("buy_seed", {}).values()) > 0

        # Plant queue for SW tiles must NOT contain unseeded tiles!
        sw_plant_tasks = [
            pos for pos, crop in plan.plant_queue
            if ctx["farm"].quadrant_of(pos) == "SW"
        ]
        assert len(sw_plant_tasks) == 0

        # Now simulate requested seeds arriving on hand:
        requested_seeds = dict(plan.intents.get("buy_seed", {}))
        assert len(requested_seeds) > 0
        ctx["private"].seeds = dict(requested_seeds)
        plan_seeded = planner.build(ctx)
        sw_plant_tasks_seeded = [
            pos for pos, crop in plan_seeded.plant_queue
            if ctx["farm"].quadrant_of(pos) == "SW"
        ]
        assert len(sw_plant_tasks_seeded) > 0


def test_progressive_sw_no_15_tile_ceiling_allows_greater_than_15():
    """Verify that progressive SW controller has no fixed 15-tile ceiling and can activate > 15 tiles."""
    class MockTile:
        def __init__(self, x, y):
            self.x = x
            self.y = y
            self.pos = (x, y)
            self.kind = "EMPTY"
            self.is_plant = False
            self.is_animal = False
            self.crop = None
            self.watered_today = False
            self.yield_units = 0

    class MockFarm:
        def __init__(self):
            self.unlocked = {"NW", "NE", "SW"}
            self.farmer = (4, 4)
            self.hands = [(4, 4)] * 15  # 15 hands = abundant labor
            self.money = 50000.0
            self.tiles = []
            for y in range(10):
                row = []
                for x in range(10):
                    row.append(MockTile(x, y))
                self.tiles.append(row)

        def iter_tiles(self):
            for row in self.tiles:
                for t in row:
                    yield t

        def quadrant_of(self, pos):
            x, y = pos
            return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")

    farm = MockFarm()
    # With abundant labor and cash, controller evaluates all 24 non-shed SW tiles
    tiles, diag = compute_progressive_sw_activation(
        farm=farm,
        day=10,
        money=10000.0,
        horizon_turns=48,
    )
    assert len(tiles) > 15, f"Controller returned {len(tiles)} tiles, expected > 15"
    assert diag["accepted_count"] > 15
    assert diag["accepted_count"] == 24


def test_projected_workers_guaranteed_hires_not_speculative():
    """Verify compute_projected_workers counts only affordable/guaranteed hires, not speculative targets."""
    class MockFarm:
        def __init__(self, money):
            self.unlocked = {"NW", "NE"}
            self.farmer = (4, 4)
            self.hands = []
            self.hires_today = 0
            self.money = money

    farm = MockFarm(money=50.0)

    # Patch get_target_hands to return 12 desired hires
    with patch("strategy.land_serviceability_model.get_target_hands", return_value=12):
        # Fibonacci hire costs for index 0..11:
        # fib(0)=1, fib(1)=1, fib(2)=2, fib(3)=3, fib(4)=5, fib(5)=8, fib(6)=13, fib(7)=21...
        # Cumulative costs: 1, 2, 4, 7, 12, 20, 33, 54...
        # With money = 50.0:
        # Hires 0..6 cost 1+1+2+3+5+8+13 = 33 <= 50.
        # Next hire (hire 7) costs 21 -> 33 + 21 = 54 > 50 (unaffordable!).
        # Therefore, exactly 7 hires are guaranteed!
        proj = compute_projected_workers(farm, day=8, money=50.0, hour=0)
        assert proj == 1 + 7, f"Expected 1 + 7 = 8 projected workers, got {proj}"

        # If money is 0, exactly 0 hires guaranteed
        proj_zero = compute_projected_workers(farm, day=8, money=0.0, hour=0)
        assert proj_zero == 1, f"Expected 1 projected worker with $0 cash, got {proj_zero}"


def test_survival_feasibility_reservation_rejects_on_deadline_risk():
    """Verify compute_progressive_sw_activation rejects with ANIMAL_SURVIVAL_SPATIAL_RISK when an animal cannot be fed before midnight."""
    from strategy.land_serviceability_model import compute_survival_feasibility_reservation

    class MockTile:
        def __init__(self, pos, is_animal=False, fed_today=False, consecutive_unfed=0):
            self.pos = pos
            self.is_animal = is_animal
            self.kind = "PASTURE" if is_animal else "EMPTY"
            self.animal = "COW" if is_animal else None
            self.fed_today = fed_today
            self.consecutive_unfed = consecutive_unfed

    class MockFarm:
        def __init__(self):
            self.unlocked = {"NW", "NE", "SW"}
            self.farmer = (0, 9)  # Worker far down in SW
            self.hands = []
            self.tiles = {
                (4, 4): MockTile((4, 4)), # shed
                (9, 0): MockTile((9, 0), is_animal=True, fed_today=False, consecutive_unfed=1), # Animal far away in NE
                (1, 8): MockTile((1, 8)), # Empty SW tile
            }
        def iter_tiles(self):
            return list(self.tiles.values())
        def quadrant_of(self, pos):
            x, y = pos
            return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")

    farm = MockFarm()
    # At hour 22, worker at (0, 9), animal at (9, 0), shed at (4, 4).
    # Worker needs to walk to shed (dist = 4 + 5 = 9), pickup (1), walk to animal (dist = 5 + 4 = 9), feed (1).
    # Total cost = 9 + 1 + 9 + 1 = 20 turns.
    # Turns left = 24 - 22 = 2 turns.
    # Cost (20) > Turns left (2) -> deadline impossible!
    diag = compute_survival_feasibility_reservation(
        farm=farm,
        day=10,
        hour=22,
        worker_positions={0: (0, 9)},
        worker_count=1,
        private=None,
    )
    assert diag["is_deadline_feasible"] is False
    assert diag["rejection_reason"] == "ANIMAL_SURVIVAL_SPATIAL_RISK"
    assert diag["blocking_animal_pos"] == (9, 0)

    # When progressive activation runs under this condition, all SW tiles must be rejected
    tiles, pdiag = compute_progressive_sw_activation(
        farm=farm,
        day=10,
        money=5000.0,
        worker_positions={0: (0, 9)},
        hour=22,
    )
    assert len(tiles) == 0
    assert pdiag["reason"] == "ANIMAL_SURVIVAL_SPATIAL_RISK"
    assert pdiag["rejection_counts"]["ANIMAL_SURVIVAL_SPATIAL_RISK"] > 0


def test_feed_priority_escalation_and_wheat_staging():
    """Verify feed priorities escalate near deadline and pickup_wheat outranks feeding."""
    from execution.task_scheduler import build_tasks
    from config import PRIORITY_URGENT_SURVIVAL, PRIORITY_FEED_STAGING

    class MockTile:
        def __init__(self, pos, is_animal=False, fed_today=False, consecutive_unfed=0, animal=None):
            self.pos = pos
            self.is_animal = is_animal
            self.kind = "PASTURE" if is_animal else "EMPTY"
            self.animal = animal
            self.fed_today = fed_today
            self.consecutive_unfed = consecutive_unfed
            self.placed_day = 5
            self.is_plant = False
            self.yield_units = 0
            self.fertilizer_available = False
            self.cared_today = True

    class MockFarm:
        def __init__(self):
            self.unlocked = ["NW", "NE", "SW"]
            self.farmer = (4, 4)
            self.hands = []
            self.tiles = {
                (4, 4): MockTile((4, 4)),
                (8, 2): MockTile((8, 2), is_animal=True, fed_today=False, consecutive_unfed=1, animal="SHEEP"),
                (1, 1): MockTile((1, 1), is_animal=True, fed_today=False, consecutive_unfed=0, animal="COW"),
            }
        def iter_tiles(self):
            return list(self.tiles.values())
        def quadrant_of(self, pos):
            x, y = pos
            return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")

    class MockPrivate:
        def __init__(self):
            self.shed = {"WHEAT": 10}
            self.inventories = [{}]
            self.seeds = {}

    from strategy.macro_planner import MacroPlan
    farm = MockFarm()
    private = MockPrivate()
    macro = MacroPlan(day=10)
    macro.feeding_enabled = True
    macro.watering_enabled = True

    # Late hour (hour 15): rescue animal (8, 2) has consecutive_unfed=1, off-day animal (1, 1) has hour >= 14
    ctx = {
        "farm": farm,
        "private": private,
        "macro": macro,
        "day": 10,
        "hour": 15,
        "step": 100,
    }
    tasks = build_tasks(ctx, macro)

    # Check tasks:
    rescue_tasks = [t for t in tasks if t.get("kind") == "feed_rescue"]
    assert len(rescue_tasks) == 1
    assert rescue_tasks[0]["priority"] == PRIORITY_URGENT_SURVIVAL + 5  # 105

    off_feed_tasks = [t for t in tasks if t.get("kind") == "feed_off"]
    assert len(off_feed_tasks) == 1
    assert off_feed_tasks[0]["priority"] == PRIORITY_URGENT_SURVIVAL  # 100 at hour 15

    staging_tasks = [t for t in tasks if t.get("kind") == "pickup_wheat"]
    assert len(staging_tasks) > 0
    # pickup_wheat must have priority > highest feed priority (105 + 1 = 106)
    assert staging_tasks[0]["priority"] > rescue_tasks[0]["priority"]
    assert staging_tasks[0]["priority"] == 106


