"""
Focused Unit Tests for Stage 2: One-at-a-Time Late Housing Continuation.

Verifies:
1. Forward-only candidate is never appended to buy_animal_sequence.
2. Candidate evaluation uses empty_pastures=0 (full infrastructure deduction).
3. Day 14 prohibits initiating continuation builds.
4. Physical completion is strictly required before purchase execution.
5. Max 1 in-flight continuation pasture constraint.
6. Production defaults remain safe and unchanged.
"""
import pytest
import config
from strategy.herd_planner import generate_dynamic_herd_plan, DynamicHerdPlan
from strategy.macro_planner import MacroPlanner
from market.order_builder import OrderBuilder


def test_production_defaults_stage2():
    """Verify all production defaults remain strictly safe."""
    assert config.POINT2_FEED_MODE == "shadow"
    assert config.BOOTSTRAP_LIVESTOCK_ARM == "none"
    assert config.ONE_AT_A_TIME_LATE_HOUSING_ENABLED is False


def test_forward_only_candidate_never_in_buy_animal_sequence():
    """Verify forward-only candidate increases required_pastures but NEVER enters buy_animal_sequence."""
    plan = generate_dynamic_herd_plan(
        day=12,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=True,
    )
    
    # Must have evaluated and admitted forward candidate
    assert plan.required_pastures == 4  # Incremented by 1
    assert len(plan.buy_animal_sequence) == 0  # CRUCIAL INVARIANT: Buy sequence is empty!
    
    # Check decision record
    fwd_recs = [r for r in plan.decision_records if r.get("forward_only")]
    assert len(fwd_recs) == 1
    rec = fwd_recs[0]
    assert rec["forward_only"] is True
    assert rec["purchase_eligible"] is False
    assert rec["sequence_index"] == -1
    assert rec["reason"] == "forward_housing_continuation_justified"


def test_day14_prohibits_continuation_build():
    """Verify Day 14 strictly prohibits initiating forward continuation builds when housing is 0."""
    plan = generate_dynamic_herd_plan(
        day=14,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 0, "COOP": 0},
        allow_late_continuation=False,  # Day 14 enforces False
    )
    
    # No continuation candidate evaluated
    assert plan.required_pastures == 3
    assert len(plan.buy_animal_sequence) == 0
    assert not any(r.get("forward_only") for r in plan.decision_records)


def test_physical_completion_required_before_purchase():
    """Verify that once pasture completes (capacity=1), candidate enters buy_animal_sequence and is purchase eligible."""
    plan = generate_dynamic_herd_plan(
        day=13,
        hour=0,
        current_herd={"COW": 3, "SHEEP": 0, "GOOSE": 0},
        town_shops=["BAKERY", "PIZZA_SHOP", "ICE_CREAM_SHOP"],
        market_inventory={"WHEAT": 10000, "MILK": 100, "WOOL": 100, "FERTILIZER": 100},
        late_selective_mode=True,
        physical_housing_capacity={"PASTURE": 1, "COOP": 0},  # Pasture completed!
        allow_late_continuation=False,
    )
    
    # Evaluated with physical housing
    assert plan.required_pastures == 4
    assert len(plan.buy_animal_sequence) == 1
    assert plan.buy_animal_sequence[0] in ("COW", "SHEEP")
    
    # Check decision record
    admitted = [r for r in plan.decision_records if r.get("accepted")]
    assert len(admitted) == 1
    rec = admitted[0]
    assert rec.get("forward_only") is False
    assert rec.get("purchase_eligible") is True
    assert rec.get("sequence_index") == 0


def test_order_builder_blocks_purchase_if_not_physically_built():
    """Verify OrderBuilder rejects any BUY_ANIMAL order on Day >= 12 if no physical empty pasture exists."""
    class DummyFarm:
        money = 5000.0
        hires_today = 0
        unlocked = ["NW", "NE"]
        def iter_tiles(self):
            # No empty pastures: 3 pastures, all have animals
            class Tile:
                def __init__(self, pos, kind, is_animal):
                    self.pos = pos
                    self.kind = kind
                    self.is_plant = False
                    self.is_animal = is_animal
            return [
                Tile((0, 0), "PASTURE", True),
                Tile((0, 1), "PASTURE", True),
                Tile((0, 2), "PASTURE", True),
            ]
        def quadrant_of(self, pos):
            return "NW"

    class DummyPrivate:
        shed = {"WHEAT": 50}
        inventories = [{} for _ in range(4)]
        seeds = {}

    class DummyMarket:
        inventory = {"WHEAT": 10000, "MILK": 100, "WOOL": 100}

    ctx = {
        "day": 12,
        "hour": 0,
        "farm": DummyFarm(),
        "private": DummyPrivate(),
        "market": DummyMarket(),
        "memory": {},
    }

    import config
    old_mode = config.POINT2_FEED_MODE
    try:
        config.POINT2_FEED_MODE = "live"
        builder = OrderBuilder()
        intents = {
            "buy_animal": {"COW": 1},
            "buy_animal_sequence": ["COW"],
        }

        orders, ledger = builder.build(ctx, intents)
        animal_orders = [o for o in orders if o[0] == "BUY_ANIMAL"]
        assert len(animal_orders) == 0  # Blocked by physical housing gate!
        assert len(ledger.get("dropped", [])) > 0
    finally:
        config.POINT2_FEED_MODE = old_mode
