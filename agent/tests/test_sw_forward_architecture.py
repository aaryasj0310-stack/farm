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
    def __init__(self, x, y, kind="EMPTY", is_plant=False, crop=None, is_animal=False, animal=None, fed_today=False, age=0):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.is_plant = is_plant
        self.crop = crop
        self.is_animal = is_animal
        self.animal = animal
        self.fed_today = fed_today
        self.age = age


class MockFarm:
    def __init__(self, money=3000.0, unlocked=None, hands=None, tiles=None):
        self.money = money
        self.unlocked = list(unlocked or ["NW", "NE"])
        self.hands = list(hands or [])
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

    # 4 tiles * 6 yield * $25 = $600 gross. Seed cost = 4 * 10 = $40. Net = $560
    assert cand.expected_gross_revenue == 600.0
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
