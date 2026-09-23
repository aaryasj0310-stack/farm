"""Comprehensive Unit Test Suite for SW-First Forward Architecture (Phase A).

Covers:
1. FarmPlan state machine (observation-driven transitions, strict cancellation, reset)
2. ResourceLedger (cash confidence tiers, zero double-reservation, feed causality, 10-order semantics)
3. CohortPlanner (opportunity cost delta, portfolio candidates, price depression)
4. ServiceCertificate (72-hour multi-day horizon, binding bottleneck, structured repair options)
5. Mode decoupling and shadow telemetry
"""
import copy
import pytest

import config
from strategy.farm_plan import (
    FarmPlan, StrategicState, CommitmentStatus, get_farm_plan, reset_farm_plan,
)
from strategy.resource_ledger import (
    ResourceLedger, InflowConfidence, DatedCashLiability, InGroundWheatHarvest,
    DatedFeedLiability,
)
from strategy.cohort_planner import (
    CohortPlanner, CropCohort, OpportunityCostEvaluation,
)
from strategy.service_certificate import (
    ServiceCertificate, ServiceTask, CommitmentTier, CertificateResult,
)
from strategy.whole_farm_planner import (
    WholeFarmPlanner, ShadowSnapshot, get_whole_farm_planner, reset_whole_farm_planner,
)


class MockTile:
    def __init__(
        self,
        x,
        y,
        kind="EMPTY",
        is_plant=False,
        crop=None,
        is_animal=False,
        animal=None,
        fed_today=False,
        age=0,
        planted_day=None,
        yield_units=0,
    ):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_plant = is_plant
        self.crop = crop
        self.is_animal = is_animal
        self.animal = animal
        self.fed_today = fed_today
        self.planted_day = planted_day
        self.yield_units = yield_units
        self.age = age


class MockFarm:
    def __init__(self, money=3000.0, unlocked=None, hands=None, tiles=None, farmer=(4, 4)):
        self.money = money
        self.unlocked = list(unlocked or ["NW", "NE"])
        self.hands = list(hands or [])
        self.farmer = tuple(farmer)
        self._tiles = tiles or [MockTile(x, y) for x in range(10) for y in range(10)]

    def iter_tiles(self):
        return self._tiles


class MockPrivate:
    def __init__(self, shed=None, inventories=None):
        self.shed = dict(shed or {"WHEAT": 20})
        self.inventories = list(inventories or [{}, {}])


# ---------------------------------------------------------------------------
# 1. FarmPlan State Machine Tests
# ---------------------------------------------------------------------------

def test_farm_plan_initial_and_reset():
    """Verify clean initial state and reset behavior."""
    reset_farm_plan()
    fp = get_farm_plan()
    assert fp.state == StrategicState.SW_NOT_COMMITTED
    assert fp.observed_sw_unlocked is False
    assert fp.current_tranche == 0

    # Advance state and reset
    fp.state = StrategicState.SW_RAMPING
    reset_farm_plan()
    assert get_farm_plan().state == StrategicState.SW_NOT_COMMITTED


def test_farm_plan_observation_driven_transitions():
    """Verify transitions occur from observed facts, not mere intents."""
    reset_farm_plan()
    fp = get_farm_plan()

    # Day 2: D0-D3 bootstrap
    ctx = {"day": 2, "hour": 0, "step": 48, "farm": MockFarm(unlocked=["NW", "NE"])}
    fp.update_from_observation(ctx)
    assert fp.state == StrategicState.SW_NOT_COMMITTED

    # Day 5: Enters SW_PREPARING
    ctx = {"day": 5, "hour": 0, "step": 120, "farm": MockFarm(unlocked=["NW", "NE"])}
    fp.update_from_observation(ctx)
    assert fp.state == StrategicState.SW_PREPARING

    # Day 8: Enters SW_READY
    ctx = {"day": 8, "hour": 0, "step": 192, "farm": MockFarm(unlocked=["NW", "NE"])}
    fp.update_from_observation(ctx)
    assert fp.state == StrategicState.SW_READY

    # Engine unlock observed -> SW_PURCHASED
    ctx = {"day": 9, "hour": 1, "step": 217, "farm": MockFarm(unlocked=["NW", "NE", "SW"])}
    fp.update_from_observation(ctx)
    assert fp.state == StrategicState.SW_PURCHASED
    assert fp.observed_sw_unlocked is True

    # 6 SW crops observed -> SW_RAMPING
    sw_tiles = [MockTile(x, y, kind="PLANT", is_plant=True, crop="WHEAT") for x in range(3) for y in range(7, 9)]
    all_tiles = [MockTile(x, y) for x in range(10) for y in range(10)]
    all_tiles[:6] = sw_tiles
    ctx = {"day": 10, "hour": 0, "step": 240, "farm": MockFarm(unlocked=["NW", "NE", "SW"], tiles=all_tiles)}
    fp.update_from_observation(ctx)
    assert fp.state == StrategicState.SW_RAMPING
    assert fp.current_tranche == 1


def test_farm_plan_strict_cancellation_semantics():
    """Verify cancellation is rejected when options to delay/downsize exist."""
    reset_farm_plan()
    fp = get_farm_plan()
    fp.state = StrategicState.SW_READY

    # Day 9 with good money: CANCEL must be denied
    ctx = {"day": 9, "hour": 0, "farm": MockFarm(money=2500)}
    fp.update_from_observation(ctx)
    can_cancel, _ = fp.evaluate_cancellation_criteria(ctx)
    assert can_cancel is False

    # Day 15 (beyond latest useful day 14): CANCEL allowed
    ctx = {"day": 15, "hour": 0, "farm": MockFarm(money=2500)}
    fp.update_from_observation(ctx)
    can_cancel, reason = fp.evaluate_cancellation_criteria(ctx)
    assert can_cancel is True
    assert "latest useful" in reason


# ---------------------------------------------------------------------------
# 2. ResourceLedger Tests (Multi-Resource, Causality, No Double-Counting)
# ---------------------------------------------------------------------------

def test_resource_ledger_cash_no_double_reservation():
    """Verify cash ledger prevents double-allocating the same dollar."""
    ledger = ResourceLedger(current_day=6, current_hour=0)
    ledger.cash_on_hand = 2500.0
    ledger.safety_reserve = 300.0
    # Available = $2,200

    # Reserve $2,000 for SW Land on Day 8
    ok1 = ledger.reserve_dated_liquidity(day=8, hour=0, amount=2000.0, purpose="SW_LAND", is_hard=True)
    assert ok1 is True

    # Try to simultaneously reserve $500 for animals on Day 7 (only $200 free!)
    ok2 = ledger.reserve_dated_liquidity(day=7, hour=0, amount=500.0, purpose="SHEEP_PURCHASE", is_hard=True)
    assert ok2 is False, "Double-reservation of committed land cash must be rejected!"


def test_resource_ledger_hard_liabilities_cannot_rely_on_speculative_inflows():
    """Verify hard commitments cannot depend on speculative inflows."""
    ledger = ResourceLedger(current_day=5, current_hour=0)
    ledger.cash_on_hand = 500.0
    ledger.safety_reserve = 300.0
    # Current net cash = $200

    # Register $2,000 SPECULATIVE harvest inflow on Day 7
    ledger.register_inflow(day=7, hour=0, amount=2000.0, confidence=InflowConfidence.SPECULATIVE, source="MELON_HARVEST")

    # Hard liability ($1,000 feed/wages) on Day 8 CANNOT rely on speculative harvest
    ok = ledger.reserve_dated_liquidity(day=8, hour=0, amount=1000.0, purpose="MANDATORY_FEED_WAGES", is_hard=True)
    assert ok is False, "Hard liabilities cannot depend on speculative inflows!"

    # But CONSERVATIVE settled inflow allows it
    ledger.register_inflow(day=7, hour=0, amount=1000.0, confidence=InflowConfidence.CONSERVATIVE, source="SHED_INVENTORY_SALE")
    ok2 = ledger.reserve_dated_liquidity(day=8, hour=0, amount=1000.0, purpose="MANDATORY_FEED_WAGES", is_hard=True)
    assert ok2 is True


def test_resource_ledger_feed_causality():
    """Strict causality: in-ground wheat maturing on D10 cannot feed animals on D9."""
    ledger = ResourceLedger(current_day=8, current_hour=0)
    ledger.shed_wheat = 2  # 2 units accessible
    ledger.worker_carried_wheat = 0

    # Add 6 wheat maturing on Day 10
    ledger.in_ground_wheat.append(InGroundWheatHarvest(day=10, hour=0, tile_pos=(1, 1), expected_yield=6))

    # Daily feed demand of 4 wheat/day from Day 8 onwards
    for d in (8, 9, 10, 11):
        for _ in range(4):
            ledger.feed_liabilities.append(
                DatedFeedLiability(day=d, hour_deadline=23, animal_pos=(2, 2), species="COW")
            )

    proj = ledger.project_feed_balance(horizon_days=3)
    # Day 8 demand is 4, opening accessible is 2 -> deficit on Day 8
    assert proj["daily"][8]["is_solvent"] is False
    assert proj["is_feed_safe"] is False


def test_resource_ledger_market_order_slot_cap():
    """Verify 10-order market capacity enforces encoded command limits."""
    ledger = ResourceLedger(current_day=5, current_hour=0)

    # 10 HIRE orders take 10 slots
    ok1 = ledger.allocate_market_slots(day=5, hour=0, command_type="HIRE", slots_consumed=10)
    assert ok1 is True
    assert ledger.get_market_slots_remaining(day=5, hour=0) == 0

    # Trying to add BUY_LAND or BUY_PRODUCT on the same turn must be rejected
    ok2 = ledger.allocate_market_slots(day=5, hour=0, command_type="BUY_LAND", slots_consumed=1)
    assert ok2 is False


# ---------------------------------------------------------------------------
# 3. CohortPlanner & Counterfactual Valuation Tests
# ---------------------------------------------------------------------------

def test_cohort_planner_counterfactual_delta():
    """Verify opportunity cost formula: ΔFC = WITH - WITHOUT (no double-deduction)."""
    planner = CohortPlanner()
    tiles = [(0, 7), (1, 7), (2, 7), (3, 7)]  # 4 tiles
    cand = planner.build_candidate_crop_cohort("cand_wheat", "WHEAT", "SW", tiles, plant_day=8)

    # 4 tiles * 6 yield = 24 yield. Under engine-exact curve (total_revenue_estimate):
    # gross = 555.0. Seed cost = 4 * 10 = $40. Net = $515.0
    assert cand.expected_gross_revenue == 555.0
    assert cand.seed_cost == 40.0

    # Displaced core crop generating $200 net
    core_dc = planner.build_candidate_crop_cohort("core_old", "CARROT", "NW", [(0, 1)], plant_day=8)
    core_dc.expected_gross_revenue = 250.0
    core_dc.seed_cost = 50.0

    eval_res = planner.evaluate_opportunity_cost(
        candidate=cand,
        displaced_cohorts=[core_dc],
        market_inventory={"WHEAT": 10000},
        feed_deficit_risk=False,
    )
    # Expected ΔFC = 560 - 200 - cannibalization (~$5) = ~$355 > 0
    assert eval_res.delta_final_cash > 300.0
    assert eval_res.admission_decision == "ADMIT"
    assert eval_res.displaced_core_value == 200.0


# ---------------------------------------------------------------------------
# 4. ServiceCertificate Tests (Multi-Day Horizon & Structured Repairs)
# ---------------------------------------------------------------------------

def test_service_certificate_multi_day_feasible():
    """Verify feasible certificate when capacity exceeds workload across 72h."""
    cert = ServiceCertificate()
    tasks = [
        ServiceTask("t1", "FEED", (4, 4), "NW", day=8, hour_deadline=23, tier=CommitmentTier.HARD, estimated_duration_actions=2),
        ServiceTask("t2", "WATER", (2, 2), "NW", day=8, hour_deadline=18, tier=CommitmentTier.HARD, estimated_duration_actions=3),
        ServiceTask("t3", "FEED", (4, 4), "NW", day=9, hour_deadline=23, tier=CommitmentTier.HARD, estimated_duration_actions=2),
    ]
    res = cert.evaluate_multi_day(current_day=8, current_hour=0, worker_count=9, tasks=tasks, horizon_hours=72)
    assert res.feasible is True
    assert res.minimum_slack > 0
    assert len(res.failing_tasks) == 0


def test_service_certificate_detects_collision_and_offers_structured_repairs():
    """Verify detection of multi-day task collision and generation of structured RepairOptions."""
    cert = ServiceCertificate()
    # At Day 9 Hour 20, 20 actions demanded but only 9 workers available!
    tasks = [
        ServiceTask("sw_heavy_water", "WATER", (2, 7), "SW", day=9, hour_deadline=20, tier=CommitmentTier.STRATEGIC, estimated_duration_actions=12),
        ServiceTask("core_decay_harvest", "HARVEST", (1, 1), "NW", day=9, hour_deadline=20, tier=CommitmentTier.HARD, estimated_duration_actions=8),
        ServiceTask("discretionary_late_care", "CARE", (2, 4), "NW", day=9, hour_deadline=20, tier=CommitmentTier.DISCRETIONARY, cohort_id="disc_care_01", estimated_duration_actions=4, value=40.0),
    ]
    res = cert.evaluate_multi_day(current_day=8, current_hour=0, worker_count=9, tasks=tasks, horizon_hours=48)
    assert res.feasible is False
    assert res.binding_day == 9
    assert res.binding_hour == 20
    assert len(res.repair_options) > 0

    # Structured repair options returned
    rep = res.repair_options[0]
    assert hasattr(rep, "actions_freed")
    assert hasattr(rep, "expected_value_lost")
    assert hasattr(rep, "resolves_certificate")


# ---------------------------------------------------------------------------
# 5. Architecture Switch & Decoupled Shadow Mode Tests
# ---------------------------------------------------------------------------

def test_architecture_switch_get_set():
    """Verify SW_FORWARD_ARCHITECTURE_MODE values and getter/setter safety."""
    orig = config.get_sw_forward_architecture_mode()
    try:
        config.set_sw_forward_architecture_mode("OFF")
        assert config.get_sw_forward_architecture_mode() == "OFF"
        assert config.SW_FORWARD_ARCHITECTURE_MODE == "OFF"

        config.set_sw_forward_architecture_mode("SHADOW")
        assert config.get_sw_forward_architecture_mode() == "SHADOW"

        with pytest.raises(ValueError):
            config.set_sw_forward_architecture_mode("INVALID_MODE")
    finally:
        config.set_sw_forward_architecture_mode(orig)


def test_shadow_planner_evaluates_without_mutating_live_state():
    """Verify WholeFarmPlanner evaluates snapshot in complete isolation."""
    from main import agent, reset_agent_state, get_last_shadow_result

    reset_agent_state()
    config.set_sw_forward_architecture_mode("SHADOW")
    try:
        # Create a synthetic observation
        obs = {
            "player": 0,
            "step": 24,
            "day": 1,
            "hour": 0,
            "farms": [
                {
                    "money": 3000,
                    "farmer": [4, 4],
                    "hands": [[4, 4], [4, 4], [4, 4], [4, 4]],
                    "unlocked_quadrants": ["NW", "NE"],
                    "tiles": [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)],
                    "hires_today": 4,
                },
                {
                    "money": 3000,
                    "farmer": [4, 4],
                    "hands": [],
                    "unlocked_quadrants": ["NW"],
                    "tiles": [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)],
                    "hires_today": 0,
                },
            ],
            "market": {"prices": {"WHEAT": 25.0}, "inventory": {"WHEAT": 10000}},
            "town": {"unlocked_shops": []},
            "private": {"shed": {"WHEAT": 20}, "inventories": [{}, {}, {}, {}, {}]},
        }

        # Run agent
        act = agent(obs)
        assert isinstance(act, dict)
        assert "farmer" in act and "market" in act

        # Verify shadow result populated
        shadow_res = get_last_shadow_result()
        assert shadow_res is not None
        assert shadow_res.decision.target_sw_day == 8
        assert shadow_res.diagnostics.latency_ms > 0
    finally:
        config.set_sw_forward_architecture_mode("OFF")
        reset_agent_state()


# ---------------------------------------------------------------------------
# 6. Phase A-R Correctness Hardening Tests
# ---------------------------------------------------------------------------

def test_wheat_actual_age_from_planted_day():
    """Correction A: In-ground wheat uses authoritative planted_day and crop_age."""
    farm = MockFarm()
    # Wheat planted on Day 4
    farm._tiles[0] = MockTile(0, 0, kind="PLANT", is_plant=True, crop="WHEAT", planted_day=4, yield_units=2)
    # Wheat planted on Day 5
    farm._tiles[1] = MockTile(1, 0, kind="PLANT", is_plant=True, crop="WHEAT", planted_day=5, yield_units=1)

    ledger = ResourceLedger(current_day=6, current_hour=0)
    ctx = {"day": 6, "hour": 0, "farm": farm, "private": MockPrivate(shed={"WHEAT": 0})}
    ledger.update_from_observation(ctx)

    assert len(ledger.in_ground_wheat) == 2
    w0 = ledger.in_ground_wheat[0]
    w1 = ledger.in_ground_wheat[1]

    # Tile 0: planted day 4, age on day 6 is 2 -> earliest harvest is Day 6 (today!)
    assert w0.planted_day == 4
    assert w0.current_age == 2
    assert w0.earliest_harvest_day == 6
    assert w0.is_harvestable_now is True
    assert w0.max_maturity_day == 8

    # Tile 1: planted day 5, age on day 6 is 1 -> earliest harvest is Day 7 (tomorrow)
    assert w1.planted_day == 5
    assert w1.current_age == 1
    assert w1.earliest_harvest_day == 7
    assert w1.is_harvestable_now is False


def test_same_day_feasible_harvest_to_feed():
    """Correction A: Harvestable wheat can reach an animal before H23."""
    farm = MockFarm(hands=[(4, 4)])
    # Wheat harvestable today on (4, 3)
    wheat = MockTile(4, 3, kind="PLANT", is_plant=True, crop="WHEAT", planted_day=4, yield_units=2)
    farm._tiles[0] = wheat

    ledger = ResourceLedger(current_day=6, current_hour=2)
    ctx = {"day": 6, "hour": 2, "farm": farm, "private": MockPrivate(shed={"WHEAT": 0})}
    ledger.update_from_observation(ctx)

    wheat_harvest = ledger.in_ground_wheat[0]
    animal_pos = (5, 3)

    # Worker at (4, 4) -> (4, 3) is 1 move + 1 harvest + 1 move to (5, 3) + 1 feed = 4 actions
    # Completion at H2 + 4 = H6 <= 23 -> Feasible!
    feasible, completion, diag = ledger.evaluate_same_day_harvest_feed_feasibility(
        wheat_harvest, animal_pos, current_hour=2
    )
    assert feasible is True
    assert completion <= 23


def test_same_day_infeasible_harvest_to_feed():
    """Correction A: Same-day wheat that cannot reach an animal before H23 is rejected."""
    farm = MockFarm(hands=[(9, 9)], farmer=(9, 9))
    # Wheat at (0, 0), animal at (9, 9), but current hour is 20
    wheat = MockTile(0, 0, kind="PLANT", is_plant=True, crop="WHEAT", planted_day=4, yield_units=2)
    farm._tiles[0] = wheat

    ledger = ResourceLedger(current_day=6, current_hour=20)
    ctx = {"day": 6, "hour": 20, "farm": farm, "private": MockPrivate(shed={"WHEAT": 0})}
    ledger.update_from_observation(ctx)

    wheat_harvest = ledger.in_ground_wheat[0]
    animal_pos = (9, 9)

    # Distance (9,9) to (0,0) is 18 + 1 harvest + 18 back to (9,9) + 1 feed = 38 actions
    # Completion at H20 + 38 = H58 > 23 -> Infeasible!
    feasible, completion, diag = ledger.evaluate_same_day_harvest_feed_feasibility(
        wheat_harvest, animal_pos, current_hour=20
    )
    assert feasible is False
    assert completion > 23


def test_future_wheat_cannot_feed_early():
    """Correction A: Wheat maturing in the future provides 0 accessible units today."""
    farm = MockFarm()
    # Wheat planted today on Day 6 (matures Day 10)
    farm._tiles[0] = MockTile(0, 0, kind="PLANT", is_plant=True, crop="WHEAT", planted_day=6, yield_units=1)

    ledger = ResourceLedger(current_day=6, current_hour=0)
    ctx = {"day": 6, "hour": 0, "farm": farm, "private": MockPrivate(shed={"WHEAT": 5})}
    ledger.update_from_observation(ctx)

    # Accessible today is ONLY the 5 in shed, not the in-ground future wheat
    acc_today = ledger.get_projected_accessible_wheat(day=6, hour=23)
    assert acc_today == 5

    # Day 7 also has only 5 (no harvest yet)
    acc_day7 = ledger.get_projected_accessible_wheat(day=7, hour=23)
    assert acc_day7 == 5


def test_worker_level_product_inventory_tracking():
    """Correction B: Track worker-level backpack inventories and shed distances."""
    farm = MockFarm(farmer=(4, 4), hands=[(0, 0), (8, 8)])
    private = MockPrivate(
        shed={"WHEAT": 10},
        inventories=[
            {"WHEAT": 2},            # Worker 0 (farmer at 4,4)
            {"STRAWBERRY": 5},       # Worker 1 (at 0,0)
            {"MILK": 3, "WOOL": 1},  # Worker 2 (at 8,8)
        ]
    )

    ledger = ResourceLedger(current_day=10, current_hour=0)
    ctx = {"day": 10, "hour": 0, "farm": farm, "private": private}
    ledger.update_from_observation(ctx)

    assert len(ledger.workers) == 3
    w0 = ledger.workers[0]
    w1 = ledger.workers[1]
    w2 = ledger.workers[2]

    assert w0.worker_id == 0
    assert w0.distance_to_shed == 0  # (4,4) is adjacent to shed
    assert w0.inventory.get("WHEAT") == 2

    assert w1.worker_id == 1
    assert w1.pos == (0, 0)
    assert w1.distance_to_shed == 8  # Manhattan dist to (4,4)
    assert w1.inventory.get("STRAWBERRY") == 5

    assert w2.worker_id == 2
    assert w2.carried_total == 4
    assert w2.distance_to_shed == 6  # Manhattan dist (8,8) to (5,5) = 3+3=6


def test_product_cannot_be_sold_from_backpack_before_deposit():
    """Correction B: Market SELL cannot liquidate goods still in a worker's backpack."""
    ledger = ResourceLedger(current_day=12, current_hour=10)
    ledger.shed_capacity = 100
    ledger.current_shed_occupancy = 0
    ledger.goods_in_shed = {}

    from strategy.resource_ledger import WorkerStorageState
    # Worker carries 10 strawberry, but is at (0, 0) (distance 8 to shed, earliest deposit H18)
    w = WorkerStorageState(
        worker_id=1, pos=(0, 0), inventory={"STRAWBERRY": 10}, carried_total=10,
        distance_to_shed=8, earliest_deposit_hour=18
    )
    ledger.workers = [w]
    ledger.current_worker_carried_units = 10

    # Planned sale at H12 (before deposit at H18) cannot sell backpack goods!
    timeline = ledger.project_storage_timeline(horizon_hours=14, planned_sales=[{"hour": 12, "quantity": 10}])
    # At H12, shed occupancy is still 0 (cannot sell from backpack!)
    assert timeline["timeline"][12]["shed_occupancy"] == 0


def test_successful_place_then_sell_chain():
    """Correction B: Successful deposit into shed allows subsequent market sale."""
    ledger = ResourceLedger(current_day=12, current_hour=10)
    ledger.shed_capacity = 100
    ledger.current_shed_occupancy = 10
    ledger.goods_in_shed = {"WHEAT": 10}

    from strategy.resource_ledger import WorkerStorageState
    # Worker at (4, 3) (distance 1 to shed, deposits at H11)
    w = WorkerStorageState(
        worker_id=1, pos=(4, 3), inventory={"STRAWBERRY": 20}, carried_total=20,
        distance_to_shed=1, earliest_deposit_hour=11
    )
    ledger.workers = [w]
    ledger.current_worker_carried_units = 20

    # Planned sale of 20 units at H14 (after deposit at H11)
    timeline = ledger.project_storage_timeline(horizon_hours=14, planned_sales=[{"hour": 14, "quantity": 20}])
    # At H11, shed occupancy becomes 10 + 20 = 30
    assert timeline["timeline"][11]["shed_occupancy"] == 30
    # At H14, shed occupancy drops back to 30 - 20 = 10
    assert timeline["timeline"][14]["shed_occupancy"] == 10
    assert timeline["is_storage_safe"] is True


def test_midnight_auto_drop_overflow_discard():
    """Correction B: Midnight auto-drop of carried inventory exceeding shed capacity causes discard."""
    ledger = ResourceLedger(current_day=12, current_hour=20)
    ledger.shed_capacity = 100
    ledger.current_shed_occupancy = 95
    ledger.goods_in_shed = {"WHEAT": 95}

    from strategy.resource_ledger import WorkerStorageState
    # Worker far away carrying 15 melon (cannot deposit before midnight)
    w = WorkerStorageState(
        worker_id=2, pos=(0, 9), inventory={"MELON": 15}, carried_total=15,
        distance_to_shed=9, earliest_deposit_hour=29
    )
    ledger.workers = [w]
    ledger.current_worker_carried_units = 15

    timeline = ledger.project_storage_timeline(horizon_hours=4, planned_sales=[])
    # 95 + 15 = 110 -> 10 discarded
    assert timeline["is_storage_safe"] is False
    assert timeline["expected_overflow"] == 10
    assert timeline["discarded_products"].get("MELON", 0) == 10
    assert 2 in timeline["overflow_workers"]


def test_no_overflow_when_prior_sale_creates_headroom():
    """Correction B: Prior market sale from shed creates headroom, avoiding midnight discard."""
    ledger = ResourceLedger(current_day=12, current_hour=18)
    ledger.shed_capacity = 100
    ledger.current_shed_occupancy = 95
    ledger.goods_in_shed = {"WHEAT": 95}

    from strategy.resource_ledger import WorkerStorageState
    # Worker arrives at shed at H19 with 10 units
    w = WorkerStorageState(
        worker_id=1, pos=(4, 3), inventory={"STRAWBERRY": 10}, carried_total=10,
        distance_to_shed=1, earliest_deposit_hour=19
    )
    ledger.workers = [w]
    ledger.current_worker_carried_units = 10

    # Market sells 25 units from shed at H20
    timeline = ledger.project_storage_timeline(horizon_hours=6, planned_sales=[{"hour": 20, "quantity": 25}])
    # Shed starts 95, deposits 5 (capped at 100), sells 25 -> drops to 75 -> no midnight overflow!
    assert timeline["is_storage_safe"] is True
    assert timeline["expected_overflow"] == 0


def test_market_10_slots_per_turn_not_per_day():
    """Correction 1 / Section 14: Market cap is maximum 10 commands per turn (day, hour)."""
    ledger = ResourceLedger(current_day=5, current_hour=0)

    # 10 orders at Hour 0: ALLOWED
    ok1 = ledger.allocate_market_slots(day=5, hour=0, command_type="SELL", slots_consumed=10)
    assert ok1 is True
    assert ledger.get_market_slots_remaining(day=5, hour=0) == 0

    # 11th order at Hour 0: REJECTED
    ok_excess = ledger.allocate_market_slots(day=5, hour=0, command_type="SELL", slots_consumed=1)
    assert ok_excess is False

    # 10 independent orders at Hour 1 on same day: ALLOWED!
    ok2 = ledger.allocate_market_slots(day=5, hour=1, command_type="BUY_LAND", slots_consumed=10)
    assert ok2 is True
    assert ledger.get_market_slots_remaining(day=5, hour=1) == 0


def test_engine_exact_melon_price_depression():
    """Correction C: Engine-exact non-linear quadratic price depression for MELON."""
    from market.price_math import market_price, total_revenue_estimate
    cp = CohortPlanner()

    # MELON base = 250, T = 300, quadratic after-base
    spot_px = market_price("MELON", 10000)
    assert spot_px == 250

    # Dumping 24 units of MELON sequentially
    nominal_rev = 24 * spot_px
    realized_rev = total_revenue_estimate("MELON", 10000, 24)
    loss = cp.estimate_price_depression_loss("MELON", 24, 10000)

    assert nominal_rev > realized_rev
    assert loss == round(nominal_rev - realized_rev, 2)
    assert loss > 0.0


def test_engine_exact_strawberry_price_depression():
    """Correction C: Engine-exact linear price depression for STRAWBERRY."""
    from market.price_math import market_price, total_revenue_estimate
    cp = CohortPlanner()

    spot_px = market_price("STRAWBERRY", 10000)
    assert spot_px == 120

    # Dumping 40 units of STRAWBERRY with T = 100
    nominal_rev = 40 * spot_px
    realized_rev = total_revenue_estimate("STRAWBERRY", 10000, 40)
    loss = cp.estimate_price_depression_loss("STRAWBERRY", 40, 10000)

    assert nominal_rev > realized_rev
    assert loss == round(nominal_rev - realized_rev, 2)
    assert loss > 0.0


def test_with_without_trajectory_does_not_double_subtract_cannibalization():
    """Correction C: Realized sequential revenue embeds own-supply impact without double-counting."""
    cp = CohortPlanner()
    tiles = [(0, 7), (1, 7), (2, 7), (3, 7)]
    candidate = cp.build_candidate_crop_cohort("cand_strawberry", "STRAWBERRY", "SW", tiles, plant_day=8)

    eval_res = cp.evaluate_opportunity_cost(
        candidate=candidate,
        displaced_cohorts=[],
        market_inventory={"STRAWBERRY": 10000},
        feed_deficit_risk=False,
    )

    # Expected gross revenue is already the realized sequential revenue
    cand_margin = eval_res.expected_gross_revenue - eval_res.seed_or_purchase_cost
    # ΔFC = cand_margin - displaced - feed - wages
    expected_delta_fc = cand_margin - eval_res.displaced_core_value - eval_res.feed_opportunity_cost - eval_res.incremental_wage_cost
    assert abs(eval_res.delta_final_cash - expected_delta_fc) < 1e-4

    # market_cannibalization_loss is reported as a diagnostic metric without being subtracted again
    assert eval_res.market_cannibalization_loss >= 0.0
    assert eval_res.delta_final_cash != (expected_delta_fc - eval_res.market_cannibalization_loss) or eval_res.market_cannibalization_loss == 0.0


def test_service_certificate_dependency_enforcement():
    """Section 18: Physical dependencies (e.g. HARVEST before FEED) are strictly enforced."""
    sc = ServiceCertificate()

    # Task 1: HARVEST wheat at H10 (takes 2 actions -> finishes H12)
    t_harvest = ServiceTask(
        task_id="t_harvest",
        op="HARVEST",
        pos=(4, 3),
        region="NW",
        day=5,
        hour_deadline=10,
        tier=CommitmentTier.HARD,
        estimated_duration_actions=2,
    )

    # Task 2: FEED animal at H11, but depends on t_harvest finishing! (Infeasible ordering)
    t_feed_invalid = ServiceTask(
        task_id="t_feed",
        op="FEED",
        pos=(5, 3),
        region="NW",
        day=5,
        hour_deadline=11,  # Prereq finishes at 10 + 2 = 12 > 11!
        tier=CommitmentTier.HARD,
        prerequisite_task_id="t_harvest",
    )

    res_invalid = sc.evaluate_multi_day(5, 0, 2, [t_harvest, t_feed_invalid])
    assert res_invalid.feasible is False
    assert res_invalid.binding_resource == "TASK_DEPENDENCY"
    assert any(t.task_id == "t_feed" for t in res_invalid.failing_tasks)

    # Valid ordering: FEED deadline at H14 (after H12 completion)
    t_feed_valid = ServiceTask(
        task_id="t_feed",
        op="FEED",
        pos=(5, 3),
        region="NW",
        day=5,
        hour_deadline=14,
        tier=CommitmentTier.HARD,
        prerequisite_task_id="t_harvest",
    )

    res_valid = sc.evaluate_multi_day(5, 0, 4, [t_harvest, t_feed_valid])
    assert res_valid.feasible is True

