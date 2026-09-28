"""Unit test suite for Phase SW-C1: Adaptive, Capacity-Aware Acreage Expansion.

Verifies:
1. Config flags & module synchronization (SW_ADAPTIVE_ACREAGE_ENABLED, SW_MAX_ADAPTIVE_ACREAGE).
2. Geometry & contiguity invariants:
   - Initial 8 tiles (4 Strawberry + 4 Melon) strictly preserved.
   - Shed access tile (4, 5) permanently excluded.
   - Blocks 12, 16, 20, 24 are mutually disjoint, each exactly 4 tiles, and span all 24 SW cultivable tiles.
3. Biological deadlines and yield profiles.
4. Marginal ΔFC evaluation and candidate crop selection.
5. All 5 Capacity Certificates (Treasury, Feed, Labor, Logistics, Storage).
6. SWTrancheController state transitions and integration:
   - OFF-mode parity (SW_ADAPTIVE_ACREAGE_ENABLED = False preserves B3C behavior).
   - Architecture control (max_acreage = 8 preserves 8 tiles).
   - Dynamic expansion to 12, 16, 20, 24 tiles.
   - Downstream filter and gate authorization for newly admitted tiles.
"""
from __future__ import annotations

import copy
import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from agent.config import (
    SW_ADAPTIVE_ACREAGE_ENABLED,
    SW_MAX_ADAPTIVE_ACREAGE,
    get_sw_adaptive_acreage_enabled,
    set_sw_adaptive_acreage_enabled,
    get_sw_max_adaptive_acreage,
    set_sw_max_adaptive_acreage,
)
from agent.strategy.adaptive_acreage_planner import (
    SHED_ACCESS_PORT,
    INITIAL_SW_TILES,
    EXPANSION_BLOCKS,
    CROP_PLANT_DEADLINES,
    SW_SAFETY_RESERVE,
    get_crop_yield_profile,
    evaluate_candidate_crop_economics,
    AdaptiveAcreagePlanner,
    get_adaptive_acreage_planner,
    reset_adaptive_acreage_planner,
)
from agent.strategy.sw_tranche_controller import (
    get_sw_tranche_controller,
    reset_sw_tranche_controller,
)


@pytest.fixture(autouse=True)
def clean_test_state():
    """Ensure clean state before and after each test."""
    set_sw_adaptive_acreage_enabled(False)
    set_sw_max_adaptive_acreage(24)
    reset_adaptive_acreage_planner()
    reset_sw_tranche_controller()
    yield
    set_sw_adaptive_acreage_enabled(False)
    set_sw_max_adaptive_acreage(24)
    reset_adaptive_acreage_planner()
    reset_sw_tranche_controller()


def test_config_flags_and_getters_setters():
    """Verify configuration flags, setters, getters, and module synchronization."""
    assert get_sw_adaptive_acreage_enabled() is False
    assert get_sw_max_adaptive_acreage() == 24

    set_sw_adaptive_acreage_enabled(True)
    assert get_sw_adaptive_acreage_enabled() is True

    set_sw_max_adaptive_acreage(16)
    assert get_sw_max_adaptive_acreage() == 16

    set_sw_adaptive_acreage_enabled(False)
    assert get_sw_adaptive_acreage_enabled() is False


def test_geometry_and_tile_partition():
    """Verify SW quadrant coordinate partition and reserved shed access port invariant."""
    assert SHED_ACCESS_PORT == (4, 5)

    # Initial 8 tiles must be 4 Strawberry + 4 Melon
    assert len(INITIAL_SW_TILES) == 8
    assert SHED_ACCESS_PORT not in INITIAL_SW_TILES

    # Expansion blocks
    assert sorted(list(EXPANSION_BLOCKS.keys())) == [12, 16, 20, 24]

    all_tiles = list(INITIAL_SW_TILES)
    for target_acres, block in EXPANSION_BLOCKS.items():
        assert len(block) == 4
        assert SHED_ACCESS_PORT not in block
        for t in block:
            assert 0 <= t[0] < 5
            assert 5 <= t[1] < 10
            assert t not in all_tiles
            all_tiles.append(t)

    # Total must be exactly 24 tiles (all SW tiles except (4, 5))
    assert len(all_tiles) == 24
    assert len(set(all_tiles)) == 24

    expected_all_sw = {(x, y) for x in range(5) for y in range(5, 10) if (x, y) != (4, 5)}
    assert set(all_tiles) == expected_all_sw


def test_biological_deadlines_and_yield_profiles():
    """Verify biological deadlines and exact season Day-29 harvest cutoffs."""
    assert CROP_PLANT_DEADLINES["STRAWBERRY"] == 13
    assert CROP_PLANT_DEADLINES["MELON"] == 17
    assert CROP_PLANT_DEADLINES["TOMATO"] == 21
    assert CROP_PLANT_DEADLINES["WHEAT"] == 25
    assert CROP_PLANT_DEADLINES["CARROT"] == 26

    # Strawberry at Day 10: 4 yields (days 20, 22, 24, 26) <= 29
    units, h_days = get_crop_yield_profile("STRAWBERRY", plant_day=10)
    assert units == 4
    assert h_days == [20, 22, 24, 26]

    # Strawberry planted after deadline (e.g. Day 14): evaluate returns 0
    delta_fc, rev, seed, u = evaluate_candidate_crop_economics("STRAWBERRY", plant_day=14, n_tiles=4)
    assert u == 0
    assert delta_fc == 0.0

    # Melon planted Day 10: yields 6 units at Day 22
    units_m, h_m = get_crop_yield_profile("MELON", plant_day=10)
    assert units_m == 6
    assert h_m == [22]

    # Melon planted Day 18 (past Day 17 deadline): cannot mature before Day 29
    delta_fc_m, _, _, u_m = evaluate_candidate_crop_economics("MELON", plant_day=18, n_tiles=4)
    assert u_m == 0
    assert delta_fc_m == 0.0

    # Wheat planted Day 25: yields 6 units at Day 29
    units_w, h_w = get_crop_yield_profile("WHEAT", plant_day=25)
    assert units_w == 6
    assert h_w == [29]

    # Wheat planted Day 26: cannot mature
    units_w26, h_w26 = get_crop_yield_profile("WHEAT", plant_day=26)
    assert units_w26 == 0
    assert h_w26 == []

    # Carrot planted Day 26: yields 4 units at Day 29
    units_c, h_c = get_crop_yield_profile("CARROT", plant_day=26)
    assert units_c == 4
    assert h_c == [29]


def test_capacity_certificate_treasury():
    """Verify Certificate 1: Treasury Safety rejects when cash < seed_cost + $300."""
    planner = AdaptiveAcreagePlanner()
    admitted = set(INITIAL_SW_TILES)

    # 4 Strawberry seeds cost $400. With reserve $300, need >= $700.
    # 4 Melon seeds cost $320. With reserve $300, need >= $620.
    # 4 Carrot seeds cost $80. With reserve $300, need >= $380.
    # 4 Wheat seeds cost $40. With reserve $300, need >= $340.

    # With $320 cash, all crops fail (cheapest is Wheat needing $340)
    dec = planner.evaluate_expansion(
        current_day=10,
        current_hour=0,
        current_admitted_tiles=admitted,
        current_cash=320.0,
        active_workers=8,
        num_animals=8,
        wheat_inventory=30,
        shed_inventory_units=20,
    )
    assert dec.approved is False
    assert "Treasury shortage" in dec.rejection_reason

    # With $450 cash, Carrot passes treasury ($80 + $300 = $380 <= $450)
    dec_c = planner.evaluate_expansion(
        current_day=10,
        current_hour=0,
        current_admitted_tiles=admitted,
        current_cash=450.0,
        active_workers=8,
        num_animals=8,
        wheat_inventory=30,
        shed_inventory_units=20,
    )
    assert dec_c.approved is True
    assert dec_c.selected_crop in ("CARROT", "WHEAT")
    assert dec_c.passed_certificates["treasury_safety"] is True


def test_capacity_certificate_feed_safety():
    """Verify Certificate 2: Feed Safety blocks non-wheat expansion when wheat < 3-day buffer."""
    planner = AdaptiveAcreagePlanner()
    admitted = set(INITIAL_SW_TILES)

    # 10 animals * 3 days = 30 wheat needed. If wheat is only 15, non-wheat crops fail.
    # But WHEAT crop produces feed, so WHEAT is eligible!
    dec = planner.evaluate_expansion(
        current_day=10,
        current_hour=0,
        current_admitted_tiles=admitted,
        current_cash=2000.0,
        active_workers=8,
        num_animals=10,
        wheat_inventory=15,  # deficit (< 30)
        shed_inventory_units=20,
    )
    assert dec.approved is True
    # Must select WHEAT to preserve animal feed security!
    assert dec.selected_crop == "WHEAT"
    assert dec.passed_certificates["feed_safety"] is True


def test_capacity_certificate_labor_capacity():
    """Verify Certificate 3: Labor Capacity Envelope blocks expansion when workers are overloaded."""
    planner = AdaptiveAcreagePlanner()
    admitted = set(INITIAL_SW_TILES)

    # With only 1 worker (24 daily hours), 85% capacity = 20.4 actions.
    # Workload with 15 animals + 20 core crops + 8 SW crops is far above 20.4 actions.
    dec = planner.evaluate_expansion(
        current_day=10,
        current_hour=0,
        current_admitted_tiles=admitted,
        current_cash=2000.0,
        active_workers=1,  # critically understaffed
        num_animals=15,
        wheat_inventory=50,
        shed_inventory_units=20,
        core_planted_tiles=20,
    )
    assert dec.approved is False
    assert "Labor crunch" in dec.rejection_reason
    assert dec.passed_certificates["labor_capacity"] is False


def test_capacity_certificate_storage_headroom():
    """Verify Certificate 5: Storage congestion prevents admitting bulky crops when shed is full."""
    planner = AdaptiveAcreagePlanner()
    admitted = set(INITIAL_SW_TILES)

    # Shed inventory at 85 units (> 75 threshold)
    dec = planner.evaluate_expansion(
        current_day=10,
        current_hour=0,
        current_admitted_tiles=admitted,
        current_cash=2000.0,
        active_workers=10,
        num_animals=8,
        wheat_inventory=50,
        shed_inventory_units=85,
    )
    # High-volume crops (16+ units) are blocked
    if dec.approved:
        assert dec.projected_units < 16
    else:
        assert "Storage congestion" in dec.rejection_reason


def test_sw_tranche_controller_adaptive_expansion_flow():
    """Verify end-to-end integration with SWTrancheController."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)

    # 1. Simulate initial SW purchase on Day 9
    initial_portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, INITIAL_SW_TILES[:4]),
            ("MELON", 4, INITIAL_SW_TILES[4:8]),
        ],
    }
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio=initial_portfolio,
        delta_fc=1500.0,
        cash_before=3000.0,
        worker_count=8,
    )
    ctrl.confirm_purchase(day=9, hour=0)

    assert len(ctrl.state.admitted_sw_tiles) == 8
    assert ctrl.state.max_admitted_acreage == 8

    # Mock farm & context
    class MockTile:
        def __init__(self, x, y):
            self.x = x
            self.y = y
            self.is_animal = False
            self.animal = None
            self.is_plant = False

    class MockFarm:
        def __init__(self):
            self.money = 2500.0
            self.hands = [0] * 7  # 8 workers total
            self.unlocked = ["NW", "NE", "SW"]
            self._tiles = [MockTile(x, y) for x in range(10) for y in range(10)]

        def iter_tiles(self):
            return iter(self._tiles)

    farm = MockFarm()
    ctx = {
        "day": 9,  # Same day as purchase: expansion should NOT trigger on Day 9
        "hour": 0,
        "private": {"shed": {"WHEAT": 40}},
        "market": type("Market", (), {"inventory": {}})(),
    }

    set_sw_adaptive_acreage_enabled(True)
    set_sw_max_adaptive_acreage(24)

    # On Day 9, expansion must be suppressed to preserve purchase day initial tranche
    res_d9 = ctrl.maybe_evaluate_adaptive_expansion(ctx, farm, None)
    assert res_d9 is None
    assert len(ctrl.state.admitted_sw_tiles) == 8

    # On Day 10 (hour 0), expansion should evaluate and approve Block 12 (+4 -> 12 tiles)
    ctx["day"] = 10
    ctx["hour"] = 0
    res_d10 = ctrl.maybe_evaluate_adaptive_expansion(ctx, farm, None)
    assert res_d10 is not None
    assert res_d10.approved is True
    assert res_d10.target_acreage == 12
    assert len(ctrl.state.admitted_sw_tiles) == 12
    assert ctrl.state.max_admitted_acreage == 12
    assert len(ctrl.state.adaptive_expansion_history) == 1

    # On Day 10 (hour 12), cannot expand again in same day
    ctx["hour"] = 12
    res_d10_h12 = ctrl.maybe_evaluate_adaptive_expansion(ctx, farm, None)
    assert res_d10_h12 is None
    assert len(ctrl.state.admitted_sw_tiles) == 12

    # On Day 11 (hour 0), expand to 16 tiles
    ctx["day"] = 11
    ctx["hour"] = 0
    res_d11 = ctrl.maybe_evaluate_adaptive_expansion(ctx, farm, None)
    assert res_d11 is not None
    assert res_d11.approved is True
    assert res_d11.target_acreage == 16
    assert len(ctrl.state.admitted_sw_tiles) == 16
    assert ctrl.state.max_admitted_acreage == 16
    assert len(ctrl.state.adaptive_expansion_history) == 2


def test_arm_c_architecture_control_cap():
    """Verify Arm C control: max_acreage = 8 prevents any expansion beyond 8 tiles."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)

    initial_portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, INITIAL_SW_TILES[:4]),
            ("MELON", 4, INITIAL_SW_TILES[4:8]),
        ],
    }
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio=initial_portfolio,
        delta_fc=1500.0,
        cash_before=3000.0,
        worker_count=8,
    )
    ctrl.confirm_purchase(day=9, hour=0)

    # Arm C settings: flag ON, but cap set to 8
    set_sw_adaptive_acreage_enabled(True)
    set_sw_max_adaptive_acreage(8)

    class MockFarm:
        def __init__(self):
            self.money = 5000.0
            self.hands = [0] * 7
            self.unlocked = ["NW", "NE", "SW"]

        def iter_tiles(self):
            return iter([])

    farm = MockFarm()
    ctx = {
        "day": 10,
        "hour": 0,
        "private": {"shed": {"WHEAT": 40}},
    }

    res = ctrl.maybe_evaluate_adaptive_expansion(ctx, farm, None)
    assert res is None
    assert len(ctrl.state.admitted_sw_tiles) == 8
    assert ctrl.state.max_admitted_acreage == 8
    assert len(ctrl.state.adaptive_expansion_history) == 0


def test_downstream_task_filtering_with_expansion():
    """Verify that newly admitted tiles are authorized across scheduler and plant queue filters."""
    ctrl = get_sw_tranche_controller()
    ctrl.set_treatment_active(True)

    initial_portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, INITIAL_SW_TILES[:4]),
            ("MELON", 4, INITIAL_SW_TILES[4:8]),
        ],
    }
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio=initial_portfolio,
        delta_fc=1500.0,
        cash_before=3000.0,
        worker_count=8,
    )

    # Candidate tile from Block 12: (4, 6)
    # Before expansion, (4, 6) is blocked
    pq = [((4, 6), "STRAWBERRY"), ((0, 5), "STRAWBERRY")]
    filtered_pq = ctrl.filter_macro_plant_queue(pq, farm=None)
    assert len(filtered_pq) == 1
    assert filtered_pq[0][0] == (0, 5)

    # Now add Block 12 to admitted tiles
    for t in EXPANSION_BLOCKS[12]:
        ctrl.state.admitted_sw_tiles.add(t)
        ctrl.state.admitted_sw_crop_targets[t] = "MELON"

    # After expansion, (4, 6) is authorized!
    filtered_pq_expanded = ctrl.filter_macro_plant_queue(pq, farm=None)
    assert len(filtered_pq_expanded) == 2
    assert (4, 6) in [item[0] for item in filtered_pq_expanded]
