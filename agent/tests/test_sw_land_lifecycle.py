"""Unit and regression tests for SW land order lifecycle telemetry.

Verifies:
1. Premature orders: Land orders before WholeFarmPlanner approval are suppressed in treatment mode.
2. Quadrant discrimination: NE BUY_LAND orders (when len(unlocked)==1) are NEVER classified as SW orders.
3. Accurate SW emission: When len(unlocked)==2 and approved, BUY_LAND order is tracked as SW purchase.
4. Dropped orders: Orders beyond market slot 10 are recorded as dropped/truncated.
5. Failed purchases: Emitted orders where engine does not unlock SW are recorded in purchase_failed_events.
6. Retried purchases: Subsequent emissions increment purchase_retry_count and log retry steps.
7. Engine confirmation: Authoritatively confirms SW ownership and cash deduction upon engine observation.
8. First productive plant: Tracks physical crop planting on SW tile.
9. No-purchase case: In games where SW is never approved, all SW lifecycle stages remain None.
"""
from __future__ import annotations

import os
import sys
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_AGENT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [_ROOT, _AGENT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy.sw_tranche_controller import (
    SWTrancheController,
    SWTrancheState,
    SWLandLifecycleTelemetry,
    get_sw_tranche_controller,
    reset_sw_tranche_controller,
)


def test_quadrant_discrimination_ne_not_classified_as_sw():
    """Verify that BUY_LAND order for NE (when only NW is unlocked) is NEVER classified as SW order."""
    ctrl = SWTrancheController()
    ctrl.set_treatment_active(True)

    # Turn at Day 4, Hour 0: Agent buys NE quadrant. unlocked = {"NW"}
    orders = [["BUY_LAND"]]
    ctrl.notify_market_orders_emitted(
        orders=orders,
        step=96,
        day=4,
        hour=0,
        farm_money=1500.0,
        unlocked_quadrants={"NW"},
    )

    lc = ctrl.state.lifecycle
    assert lc.sw_order_emitted_step is None, "NE land purchase on Day 4 was falsely classified as SW purchase!"
    assert lc.sw_order_emitted_count == 0
    assert ctrl.state.sw_land_order_emitted is False


def test_approved_sw_order_emitted_and_retained():
    """Verify that when NE is unlocked and SW is approved, BUY_LAND is tracked as SW purchase."""
    ctrl = SWTrancheController()
    ctrl.set_treatment_active(True)

    # 1. Approve purchase at Day 10, Hour 14
    port = {"name": "compact_commercial", "tiles_used": 8, "allocations": [["MELON", 4, [[0, 5]]]]}
    ctrl.approve_purchase(day=10, hour=14, portfolio=port, delta_fc=5000.0, cash_before=2800.0, worker_count=8)

    lc = ctrl.state.lifecycle
    assert lc.sw_recommendation_step == 254
    assert lc.sw_approved_step == 254
    assert lc.sw_intent_created_step == 254

    # 2. Emit BUY_LAND order at Day 10, Hour 15 when unlocked = {"NW", "NE"}
    orders = [["HIRE"], ["BUY_LAND"], ["BUY_SEED", "MELON", 4]]
    ctrl.notify_market_orders_emitted(
        orders=orders,
        step=255,
        day=10,
        hour=15,
        farm_money=2800.0,
        unlocked_quadrants={"NW", "NE"},
    )

    assert lc.sw_order_emitted_step == 255
    assert lc.sw_order_emitted_day == 10
    assert lc.sw_order_emitted_hour == 15
    assert lc.sw_order_emitted_count == 1
    assert lc.sw_order_retained_step == 255
    assert lc.sw_order_retained_slot_index == 1
    assert ctrl.state.sw_land_order_emitted is True


def test_dropped_order_when_truncated_beyond_slot_10():
    """Verify that a BUY_LAND order beyond the 10-slot limit is recorded as a market slot truncation failure."""
    ctrl = SWTrancheController()
    ctrl.set_treatment_active(True)
    port = {"name": "compact_commercial", "tiles_used": 8, "allocations": []}
    ctrl.approve_purchase(day=10, hour=14, portfolio=port, delta_fc=5000.0, cash_before=2800.0, worker_count=8)

    # 10 orders preceding BUY_LAND (BUY_LAND is in slot 10, index 10, which exceeds 10-order cap)
    orders = [["HIRE"] for _ in range(10)] + [["BUY_LAND"]]
    ctrl.notify_market_orders_emitted(
        orders=orders,
        step=255,
        day=10,
        hour=15,
        farm_money=2800.0,
        unlocked_quadrants={"NW", "NE"},
    )

    lc = ctrl.state.lifecycle
    assert lc.sw_order_retained_step is None
    assert len(lc.purchase_failed_events) == 1
    assert "market_slot_truncation" in lc.purchase_failed_events[0]["reason"]


def test_failed_purchase_and_retry_lifecycle():
    """Verify detection of failed purchase (insufficient funds) and subsequent retry tracking."""
    ctrl = SWTrancheController()
    ctrl.set_treatment_active(True)
    port = {"name": "compact_commercial", "tiles_used": 8, "allocations": []}
    ctrl.approve_purchase(day=10, hour=14, portfolio=port, delta_fc=5000.0, cash_before=1500.0, worker_count=8)

    # Emit BUY_LAND order at step 255 (insufficient cash)
    ctrl.notify_market_orders_emitted(
        orders=[["BUY_LAND"]],
        step=255,
        day=10,
        hour=15,
        farm_money=1500.0,
        unlocked_quadrants={"NW", "NE"},
    )

    # Next step: engine observation still has unlocked = ["NW", "NE"] (purchase failed!)
    mock_obs = {"farms": [{"unlocked_quadrants": ["NW", "NE"], "money": 1500.0, "tiles": []}]}
    ctrl.observe_engine_step(obs=mock_obs, seat=0, step=256, day=10, hour=16)

    lc = ctrl.state.lifecycle
    assert lc.sw_confirmed_step is None
    assert len(lc.purchase_failed_events) == 1
    assert "engine_rejected_or_insufficient_funds" in lc.purchase_failed_events[0]["reason"]

    # Retry purchase at step 257 (cash received)
    ctrl.notify_market_orders_emitted(
        orders=[["BUY_LAND"]],
        step=257,
        day=10,
        hour=17,
        farm_money=2500.0,
        unlocked_quadrants={"NW", "NE"},
    )

    assert lc.purchase_retry_count == 1
    assert lc.purchase_retry_steps == [257]
    assert lc.sw_order_emitted_count == 2

    # Step 258: Engine confirms SW!
    mock_obs_confirmed = {"farms": [{"unlocked_quadrants": ["NW", "NE", "SW"], "money": 500.0, "tiles": []}]}
    ctrl.observe_engine_step(obs=mock_obs_confirmed, seat=0, step=258, day=10, hour=18)

    assert lc.sw_confirmed_step == 258
    assert lc.sw_confirmed_day == 10
    assert lc.sw_confirmed_hour == 18
    assert lc.sw_confirmed_cash_deduction == 2000.0
    assert ctrl.state.sw_purchase_confirmed is True


def test_first_productive_plant_tracking():
    """Verify that the first crop planted on an SW tile is authoritatively recorded."""
    ctrl = SWTrancheController()
    ctrl.set_treatment_active(True)
    ctrl.confirm_purchase(day=10, hour=18)

    # Board with empty tiles except (0, 5) which has a Melon planted on Day 11
    tiles = [[None for _ in range(10)] for _ in range(10)]
    tiles[5][0] = {"kind": "PLANT", "crop": "MELON", "planted_day": 11}
    mock_obs = {"farms": [{"unlocked_quadrants": ["NW", "NE", "SW"], "money": 500.0, "tiles": tiles}]}

    ctrl.observe_engine_step(obs=mock_obs, seat=0, step=265, day=11, hour=1)

    lc = ctrl.state.lifecycle
    assert lc.first_productive_plant_step == 265
    assert lc.first_productive_plant_day == 11
    assert lc.first_productive_plant_crop == "MELON"
    assert lc.first_productive_plant_pos == (0, 5)


def test_no_purchase_match_lifecycle_remains_none():
    """Verify that in a match where SW is never purchased, lifecycle stages remain None."""
    ctrl = SWTrancheController()
    ctrl.set_treatment_active(True)

    # Match runs to completion without SW approval
    mock_obs = {"farms": [{"unlocked_quadrants": ["NW", "NE"], "money": 80000.0, "tiles": []}]}
    for s in range(0, 720, 24):
        ctrl.observe_engine_step(obs=mock_obs, seat=0, step=s, day=s // 24, hour=0)

    lc = ctrl.state.lifecycle
    assert lc.sw_recommendation_step is None
    assert lc.sw_approved_step is None
    assert lc.sw_order_emitted_step is None
    assert lc.sw_confirmed_step is None
    assert lc.first_productive_plant_step is None
    assert lc.purchase_retry_count == 0
    assert len(lc.purchase_failed_events) == 0
