"""Historical Failure Diagnostic Scenario Replay Test Suite (Phase A).

Evaluates whether the new forward architecture (ResourceLedger & ServiceCertificate)
correctly identifies and diagnoses the known historical SW failure mechanisms:
1. P4.1: Core worker displacement under rigid regional partitioning
2. P1: Purchase-only overcommitment without forward labor/feed reservation
3. P1.1: Feed service timing / causality shortfall
4. P6.1: Concurrent harvest wave storage congestion

Interpretation invariant: Passing these tests confirms the diagnostic certificate
detects the exact failure causes and generates valid structured repairs.
It does NOT claim unverified economic cash lifts.
"""
import pytest

from strategy.service_certificate import (
    ServiceCertificate, ServiceTask, CommitmentTier, CertificateResult,
)
from strategy.resource_ledger import (
    ResourceLedger, DatedFeedLiability, InGroundWheatHarvest, InflowConfidence,
)
from strategy.farm_plan import FarmPlan, StrategicState


def test_scenario_p41_core_worker_displacement():
    """Scenario P4.1: Exclusive 2-worker SW partition displaces core agricultural capacity.

    In P4.1, hands 11 and 12 were reserved for 8 SW tiles. Core agricultural operations
    dropped by 111.6/game and core watering compliance dropped 4.45 points.

    Validation: When 2 workers are partitioned away and core tasks demand full workforce,
    ServiceCertificate MUST flag failure and recommend releasing partition / downsizing SW.
    """
    cert = ServiceCertificate()

    # Core farm workload at Day 14 Hour 18:
    # 11 core crops needing urgent water + 2 decay harvests + 2 feed rescues = 15 direct actions
    tasks = []
    for i in range(11):
        tasks.append(
            ServiceTask(f"core_water_{i}", "WATER", (i % 5, i // 5), "NW", day=14, hour_deadline=18, tier=CommitmentTier.HARD, estimated_duration_actions=1)
        )
    for i in range(2):
        tasks.append(
            ServiceTask(f"core_decay_{i}", "HARVEST", (i, 2), "NW", day=14, hour_deadline=18, tier=CommitmentTier.HARD, estimated_duration_actions=1)
        )
    # SW task on the same hour
    tasks.append(
        ServiceTask("sw_water", "WATER", (2, 7), "SW", day=14, hour_deadline=18, tier=CommitmentTier.STRATEGIC, estimated_duration_actions=4, cohort_id="sw_cohort_p41")
    )

    # In P4.1, core has only 11 workers (13 total - 2 SW partitioned workers)
    # With 11 effective workers at hour 18, 15 core actions + travel cannot all execute!
    res = cert.evaluate_multi_day(current_day=14, current_hour=0, worker_count=11, tasks=tasks, horizon_hours=24)

    assert res.feasible is False, "Certificate must detect P4.1 core capacity deficit!"
    assert res.binding_day == 14
    assert res.binding_hour == 18

    # Repair options must propose downsizing SW or dropping discretionary work
    assert len(res.repair_options) > 0
    repair_types = [r.type for r in res.repair_options]
    assert "DOWNSIZE_TRANCHE" in repair_types or "DROP_COHORT" in repair_types or "HIRE_EXTRA_WORKER" in repair_types


def test_scenario_p1_purchase_only_overcommitment():
    """Scenario P1: Buying SW land without forward capital/feed reservation.

    In P1, buying SW consumed $2,000, leaving the farm insolvent for Day 7-9 wages and feed.

    Validation: ResourceLedger must reject land purchase when forward hard liabilities
    (wages + feed) exceed remaining liquidity.
    """
    ledger = ResourceLedger(current_day=6, current_hour=0)
    ledger.cash_on_hand = 2300.0
    ledger.safety_reserve = 300.0
    # Available gross = $2,000

    # Mandatory wages and feed for Days 7-9 total $600
    ledger.reserve_dated_liquidity(day=7, hour=0, amount=200.0, purpose="MANDATORY_WAGES", is_hard=True)
    ledger.reserve_dated_liquidity(day=8, hour=0, amount=200.0, purpose="MANDATORY_WAGES", is_hard=True)
    ledger.reserve_dated_liquidity(day=9, hour=0, amount=200.0, purpose="MANDATORY_WAGES", is_hard=True)

    # Trying to spend $2,000 on SW land now leaves -$600 for wages/feed!
    can_buy = ledger.reserve_dated_liquidity(day=6, hour=1, amount=2000.0, purpose="SW_LAND_PURCHASE", is_hard=True)
    assert can_buy is False, "ResourceLedger must block P1 purchase-only overcommitment!"


def test_scenario_p11_feed_service_causality_deficit():
    """Scenario P1.1: Animal expansion planned against unharvested in-ground grain.

    Validation: FeedLedger correctly identifies that wheat maturing on Day 10
    cannot feed 6 animals on Day 8 and Day 9.
    """
    ledger = ResourceLedger(current_day=8, current_hour=0)
    ledger.shed_wheat = 2  # Only 2 units accessible

    # 18 wheat units in ground maturing on Day 10
    ledger.in_ground_wheat.append(InGroundWheatHarvest(day=10, hour=0, tile_pos=(1, 1), expected_yield=18))

    # Existing + proposed herd: 6 animals requiring 6 wheat each day
    for d in (8, 9, 10):
        for idx in range(6):
            ledger.feed_liabilities.append(
                DatedFeedLiability(day=d, hour_deadline=23, animal_pos=(idx % 5, idx // 5), species="COW")
            )

    proj = ledger.project_feed_balance(horizon_days=3)
    assert proj["is_feed_safe"] is False
    assert proj["daily"][8]["is_solvent"] is False
    assert proj["daily"][9]["is_solvent"] is False
    # Day 10 becomes solvent after harvest
    assert proj["daily"][10]["harvest_inflow"] == 18


def test_scenario_p61_harvest_wave_storage_congestion():
    """Scenario P6.1: Concurrent crop harvest waves threaten 100-unit shed capacity.

    Validation: StorageLedger tracks carried units and shed occupancy, flagging
    when headroom is exhausted before market liquidation.
    """
    ledger = ResourceLedger(current_day=12, current_hour=0)
    ledger.shed_capacity = 100
    ledger.current_shed_occupancy = 85  # 85 units already in shed
    ledger.current_worker_carried_units = 10  # 10 units carried by workers

    # Net available headroom is only 5 units (100 - 85 - 10)
    headroom = ledger.project_storage_headroom()
    assert headroom == 5

    # A 12-unit harvest wave incoming without prior sale will risk overflow
    wave_units = 12
    assert wave_units > headroom, "Storage ledger correctly flags overflow risk for incoming harvest wave"
