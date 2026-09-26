"""Unit tests for Phase SW-B2-R1: Storage Rescue Counterexamples.

Verifies the 8 mandatory counterexamples reconciling ResourceLedger.project_storage_timeline()
and midnight_storage_controller.apply_midnight_storage_rescue() with production mechanics:
1. Shed congestion with enough wheat and available order slot.
2. Congestion with insufficient surplus wheat.
3. Ten existing market commands, leaving no rescue slot.
4. Non-wheat sales that must not reduce wheat inventory.
5. Day 29 when the rescue controller is disabled.
6. Wheat needed for animal feeding.
7. Worker-held inventory entering the shed at midnight.
8. Storage overflow that cannot actually be prevented.
"""
import copy
import os
import sys
import pytest
from unittest.mock import MagicMock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_AGENT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [_ROOT, _AGENT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.strategy.resource_ledger import ResourceLedger, WorkerStorageState, DatedFeedLiability
from agent.execution.midnight_storage_controller import (
    apply_midnight_storage_rescue,
    reset_midnight_storage_telemetry,
    get_midnight_storage_telemetry,
)


def _build_ledger(
    day: int = 15,
    hour: int = 20,
    shed_occ: int = 80,
    shed_wheat: int = 25,
    carried_units: int = 25,
    anim_count: int = 2,
    mode: str = "RESCUE",
) -> ResourceLedger:
    ledger = ResourceLedger()
    ledger.day = day
    ledger.hour = hour
    ledger.current_shed_occupancy = shed_occ
    ledger.shed_wheat = shed_wheat
    ledger.shed_capacity = 100

    # Add workers with carried inventory
    w = WorkerStorageState(
        worker_id=1,
        pos=(4, 5),
        inventory={"WHEAT": carried_units} if carried_units > 0 else {},
        carried_total=carried_units,
        distance_to_shed=1,
        earliest_deposit_hour=24,  # will not deposit before midnight rollover
    )
    ledger.workers = [w]

    # Add animal feed liabilities
    ledger.feed_liabilities = [
        DatedFeedLiability(day=day, hour_deadline=23, animal_pos=(2, 2 + i), species="COW", amount=1)
        for i in range(anim_count)
    ]
    return ledger


# ---------------------------------------------------------------------------
# Counterexample 1: Shed congestion with enough wheat and available order slot
# ---------------------------------------------------------------------------
def test_counterexample_1_congestion_with_enough_wheat_and_available_slot(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    # shed = 85 (wheat=30), carried = 20 -> projected = 105 (>98), needed = 7
    # animals = 2 -> safe_w = max(10, 4) = 10. can_sell_w = 30 - 10 = 20 >= 7.
    ledger = _build_ledger(day=15, hour=20, shed_occ=85, shed_wheat=30, carried_units=20, anim_count=2)
    res = ledger.project_storage_timeline(horizon_hours=4, planned_sales=[])

    assert res["rescue_relief_units"] == 7
    assert res["expected_overflow"] == 0
    assert res["is_storage_safe"] is True
    assert res["final_projected_shed"] == 98
    assert res["inventory_conserved"] is True


# ---------------------------------------------------------------------------
# Counterexample 2: Congestion with insufficient surplus wheat
# ---------------------------------------------------------------------------
def test_counterexample_2_congestion_with_insufficient_surplus_wheat(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    # shed = 90 (wheat=13), carried = 15 -> projected = 105 (>98), needed = 7
    # animals = 2 -> safe_w = 10. can_sell_w = 13 - 10 = 3 < 7.
    ledger = _build_ledger(day=15, hour=20, shed_occ=90, shed_wheat=13, carried_units=15, anim_count=2)
    res = ledger.project_storage_timeline(horizon_hours=4, planned_sales=[])

    # Can only sell 3 units of wheat without breaching safe_w
    assert res["rescue_relief_units"] == 3
    # Post-rescue projected = 105 - 3 = 102. Capacity is 100.
    assert res["expected_overflow"] == 2
    assert res["is_storage_safe"] is False
    assert res["final_projected_shed"] == 100
    assert res["inventory_conserved"] is True


# ---------------------------------------------------------------------------
# Counterexample 3: Ten existing market commands, leaving no rescue slot
# ---------------------------------------------------------------------------
def test_counterexample_3_market_slots_full_prevents_rescue(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    ledger = _build_ledger(day=15, hour=20, shed_occ=85, shed_wheat=30, carried_units=20, anim_count=2)
    # 10 non-sale market orders (e.g. BUY_PRODUCT / HIRE) already scheduled for hour 23
    orders_h23 = [{"hour": 23, "product": "HIRE", "quantity": 0} for _ in range(10)]
    res = ledger.project_storage_timeline(horizon_hours=4, planned_sales=orders_h23)

    # Cannot emit rescue order because all 10 market slots are exhausted
    assert res["rescue_relief_units"] == 0
    # Potential midnight shed is 85 + 20 = 105 > 100 -> overflow of 5 units!
    assert res["expected_overflow"] == 5
    assert res["is_storage_safe"] is False

    # Also test in direct execution controller
    reset_midnight_storage_telemetry()
    mock_private = MagicMock()
    mock_private.shed = {"WHEAT": 30}
    mock_private.inventories = [{"WHEAT": 20}]
    mock_farm = MagicMock()
    mock_farm.iter_tiles.return_value = []
    ctx = {"day": 15, "hour": 23, "private": mock_private, "farm": mock_farm}

    full_market = [["SELL", "CARROT", 1] for _ in range(10)]
    mkt_out = apply_midnight_storage_rescue(full_market, ctx)
    assert len(mkt_out) == 10
    assert get_midnight_storage_telemetry()["rescue_events"] == 0


# ---------------------------------------------------------------------------
# Counterexample 4: Non-wheat sales that must not reduce wheat inventory
# ---------------------------------------------------------------------------
def test_counterexample_4_non_wheat_sales_do_not_reduce_wheat_stock(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    # Shed has 85 items total, 25 wheat, 60 melons. Carried = 20 melons.
    ledger = _build_ledger(day=15, hour=18, shed_occ=85, shed_wheat=25, carried_units=20, anim_count=2)
    # Planned sale of 15 MELONS at hour 19
    planned_sales = [{"hour": 19, "product": "MELON", "quantity": 15}]
    res = ledger.project_storage_timeline(horizon_hours=6, planned_sales=planned_sales)

    # After 15 melons sold: shed_occ = 70. carried = 20. projected = 90 <= 98.
    # No rescue needed because melon sales already cleared sufficient headroom!
    assert res["rescue_relief_units"] == 0
    assert res["expected_overflow"] == 0
    assert res["is_storage_safe"] is True


# ---------------------------------------------------------------------------
# Counterexample 5: Day 29 when the rescue controller is disabled
# ---------------------------------------------------------------------------
def test_counterexample_5_day29_rescue_disabled(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    # On Day 29, rescue must be strictly disabled
    ledger = _build_ledger(day=29, hour=20, shed_occ=85, shed_wheat=30, carried_units=20, anim_count=2)
    res = ledger.project_storage_timeline(horizon_hours=4, planned_sales=[])

    assert res["rescue_relief_units"] == 0

    # Also test in direct execution controller
    reset_midnight_storage_telemetry()
    mock_private = MagicMock()
    mock_private.shed = {"WHEAT": 30}
    mock_private.inventories = [{"WHEAT": 20}]
    mock_farm = MagicMock()
    mock_farm.iter_tiles.return_value = []
    ctx = {"day": 29, "hour": 23, "private": mock_private, "farm": mock_farm}

    mkt_out = apply_midnight_storage_rescue([], ctx)
    assert len(mkt_out) == 0
    assert get_midnight_storage_telemetry()["rescue_events"] == 0


# ---------------------------------------------------------------------------
# Counterexample 6: Wheat needed for animal feeding
# ---------------------------------------------------------------------------
def test_counterexample_6_wheat_needed_for_animal_feeding(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    # 6 animals -> safe_w = max(10, 6 * 2) = 12.
    # shed_wheat = 11 <= 12 -> can_sell_w = 0.
    ledger = _build_ledger(day=15, hour=20, shed_occ=85, shed_wheat=11, carried_units=20, anim_count=6)
    res = ledger.project_storage_timeline(horizon_hours=4, planned_sales=[])

    # Zero wheat can be sold because all of it is protected for animal survival
    assert res["rescue_relief_units"] == 0
    assert res["is_storage_safe"] is False


# ---------------------------------------------------------------------------
# Counterexample 7: Worker-held inventory entering the shed at midnight
# ---------------------------------------------------------------------------
def test_counterexample_7_worker_held_inventory_entering_at_midnight(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    # Shed has only 50 items (wheat=30). No congestion at hour 20 (50/100).
    # But workers hold 52 units in backpacks!
    # Projected at midnight = 50 + 52 = 102 > 98. Needed = 4.
    ledger = _build_ledger(day=15, hour=20, shed_occ=50, shed_wheat=30, carried_units=52, anim_count=2)
    res = ledger.project_storage_timeline(horizon_hours=4, planned_sales=[])

    # Proactive rescue sells 4 wheat to ensure total shed load after midnight deposit <= 98
    assert res["rescue_relief_units"] == 4
    assert res["expected_overflow"] == 0
    assert res["is_storage_safe"] is True
    assert res["final_projected_shed"] == 98


# ---------------------------------------------------------------------------
# Counterexample 8: Storage overflow that cannot actually be prevented
# ---------------------------------------------------------------------------
def test_counterexample_8_unpreventable_storage_overflow(monkeypatch):
    import agent.config as config
    monkeypatch.setattr(config, "MIDNIGHT_STORAGE_DUMP_MODE", "RESCUE")

    # Shed has 95 MELONS and 0 WHEAT. Workers hold 15 MELONS.
    # Projected = 110 > 98. But shed_wheat = 0!
    ledger = _build_ledger(day=15, hour=20, shed_occ=95, shed_wheat=0, carried_units=15, anim_count=2)
    res = ledger.project_storage_timeline(horizon_hours=4, planned_sales=[])

    assert res["rescue_relief_units"] == 0
    assert res["expected_overflow"] == 10
    assert res["is_storage_safe"] is False
    assert len(res["overflow_workers"]) > 0
    assert res["inventory_conserved"] is True
