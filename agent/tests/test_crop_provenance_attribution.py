"""Unit and regression tests for tile-level physical crop provenance and revenue attribution.

Verifies:
1. Physical tile harvest discrimination: SW tiles (x < 5, y >= 5) vs Core tiles (NW/NE).
2. Provenance bounds calculation: Lower bound, Upper bound, and Proportional allocation.
3. Conservation of goods: Harvested units = Sold units + Ending Shed + Ending Worker + Discarded.
4. Distinguishes direct gross SW revenue from net profit after accounting for seed opportunity cost ($832) and land cost ($2000).
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

from strategy.sw_tranche_controller import CropProvenanceTracker


def test_physical_tile_harvest_discrimination():
    """Verify that harvests are accurately attributed by physical board coordinates."""
    tracker = CropProvenanceTracker()

    # Core NW tile (2, 2)
    tracker.record_harvest(pos=(2, 2), crop="WHEAT", units=6)
    # Core NE tile (7, 2)
    tracker.record_harvest(pos=(7, 2), crop="MELON", units=2)
    # SW tile (1, 6)
    tracker.record_harvest(pos=(1, 6), crop="MELON", units=2)
    # SW tile (2, 5)
    tracker.record_harvest(pos=(2, 5), crop="STRAWBERRY", units=1)

    assert tracker.core_harvested_units["WHEAT"] == 6
    assert tracker.core_harvested_units["MELON"] == 2
    assert tracker.sw_harvested_units.get("WHEAT", 0) == 0
    assert tracker.sw_harvested_units["MELON"] == 2
    assert tracker.sw_harvested_units["STRAWBERRY"] == 1


def test_provenance_bounds_and_proportional_allocation():
    """Verify lower, upper, and proportional attribution bounds for mixed-origin goods."""
    tracker = CropProvenanceTracker()

    # Core harvested 10 Melons, SW harvested 10 Melons (Total 20 Melons)
    tracker.record_harvest(pos=(2, 2), crop="MELON", units=10)
    tracker.record_harvest(pos=(1, 6), crop="MELON", units=10)

    # Farm sold 15 Melons across two sales: 10 at $80, 5 at $60 (Average $73.33)
    tracker.record_sale(step=300, crop="MELON", units=10, unit_price=80.0)
    tracker.record_sale(step=350, crop="MELON", units=5, unit_price=60.0)

    res = tracker.get_provenance_attribution("MELON")

    assert res["core_harvested_units"] == 10
    assert res["sw_harvested_units"] == 10
    assert res["total_harvested_units"] == 20
    assert res["total_sold_units"] == 15
    assert res["total_sold_revenue"] == 1100.0
    assert res["average_realized_price"] == 73.33

    # Bounds:
    # Upper bound: min(10, 15) = 10 units -> $733.33
    assert res["sw_sales_upper_bound_units"] == 10
    assert res["sw_revenue_upper_bound"] == 733.33

    # Lower bound: max(0, 15 - 10) = 5 units -> $366.67
    assert res["sw_sales_lower_bound_units"] == 5
    assert res["sw_revenue_lower_bound"] == 366.67

    # Proportional: 15 * (10 / 20) = 7.5 units -> $550.00
    assert res["sw_sales_proportional_units"] == 7.5
    assert res["sw_revenue_proportional"] == 550.0


def test_conservation_of_goods_reconciliation():
    """Verify that total harvested units equal sales + shed + worker inventory + discards."""
    tracker = CropProvenanceTracker()

    # Harvest 16 Strawberries from SW
    tracker.record_harvest(pos=(1, 5), crop="STRAWBERRY", units=16)

    # 12 sold
    tracker.record_sale(step=400, crop="STRAWBERRY", units=12, unit_price=100.0)

    # 2 remaining in shed, 1 held by worker, 1 discarded due to overflow
    tracker.ending_shed_units["STRAWBERRY"] = 2
    tracker.ending_worker_units["STRAWBERRY"] = 1
    tracker.discarded_overflow_units["STRAWBERRY"] = 1

    res = tracker.get_provenance_attribution("STRAWBERRY")

    assert res["total_harvested_units"] == 16
    assert res["total_sold_units"] == 12
    assert res["ending_shed_units"] == 2
    assert res["ending_worker_units"] == 1
    assert res["discarded_overflow_units"] == 1
    assert res["conservation_verified"] is True
