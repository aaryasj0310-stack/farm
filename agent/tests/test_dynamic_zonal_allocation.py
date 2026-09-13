"""Unit tests for Phase 2B: Workload-Aware Dynamic Zonal Allocation.

Tests:
1. compute_workload_aware_home_quadrants sizing:
   - Only NW unlocked -> all units to NW
   - NW + NE unlocked -> units sized to mandatory workload
   - SW unlocked with 0 SW tasks -> 0 units to SW (NW/NE protected from starvation)
   - SW unlocked with moderate tasks -> SW sized to demand, NW/NE protected
2. Distance-based worker mapping:
   - Workers already in NE stay in NE
   - Prohibits diagonal jumps (SW <-> NE)
   - Invariant: exactly n_units mapped, all keys [0..n-1] present
3. Serviceability model integration:
   - evaluate_sw_serviceability with DYNAMIC_ZONAL_ALLOCATION = True
"""
import pytest
from unittest.mock import MagicMock
from config import (
    DYNAMIC_ZONAL_ALLOCATION,
    set_dynamic_zonal_allocation,
    EFFECTIVE_ACTIONS_PER_UNIT,
    PORT_SW,
)
from execution.task_scheduler import (
    compute_workload_aware_home_quadrants,
    get_home_quadrant,
)
from strategy.land_serviceability_model import (
    evaluate_sw_serviceability,
    compute_candidate_sw_workload,
)


class MockFarm:
    def __init__(self, unlocked=("NW", "NE", "SW")):
        self.unlocked = set(unlocked)
        self.farmer = (4, 4)
        self.hands = []

    def quadrant_of(self, pos):
        x, y = pos
        if x < 5 and y < 5:
            return "NW"
        elif x >= 5 and y < 5:
            return "NE"
        elif x < 5 and y >= 5:
            return "SW"
        else:
            return "SE"


def test_only_nw_unlocked():
    farm = MockFarm(unlocked=["NW"])
    pos_by_idx = {i: (4, 4) for i in range(10)}
    tasks = [{"op": "WATER", "target": (1, 1), "priority": 75}]
    home_quads = compute_workload_aware_home_quadrants(tasks, farm, 10, pos_by_idx)
    assert len(home_quads) == 10
    assert all(q == "NW" for q in home_quads.values())


def test_sw_unlocked_zero_tasks_protects_nw_ne():
    """Critical test: when SW has 0 tasks, SW must receive 0 workers."""
    farm = MockFarm(unlocked=["NW", "NE", "SW"])
    n_units = 13
    pos_by_idx = {i: (4, 4) if i < 6 else (7, 2) for i in range(n_units)}
    
    # 24 mandatory tasks in NW (needs 2 units) and 36 in NE (needs 3 units)
    tasks = []
    for _ in range(24):
        tasks.append({"op": "WATER", "target": (2, 2), "priority": 75})
    for _ in range(36):
        tasks.append({"op": "WATER", "target": (7, 2), "priority": 75})

    home_quads = compute_workload_aware_home_quadrants(tasks, farm, n_units, pos_by_idx)
    assert len(home_quads) == n_units
    sw_count = sum(1 for q in home_quads.values() if q == "SW")
    assert sw_count == 0, f"Expected 0 workers to SW when SW has 0 tasks, got {sw_count}"
    assert sum(1 for q in home_quads.values() if q in ("NW", "NE")) == n_units


def test_sw_unlocked_proportional_allocation():
    """When SW has 12 tasks (1 unit of work), SW gets 1 worker, not 4 or 5."""
    farm = MockFarm(unlocked=["NW", "NE", "SW"])
    n_units = 13
    pos_by_idx = {i: (4, 4) for i in range(n_units)}

    tasks = []
    # 24 mandatory NW tasks
    for _ in range(24):
        tasks.append({"op": "WATER", "target": (2, 2), "priority": 75})
    # 36 mandatory NE tasks
    for _ in range(36):
        tasks.append({"op": "WATER", "target": (7, 2), "priority": 75})
    # 12 SW tasks
    for _ in range(12):
        tasks.append({"op": "WATER", "target": (2, 7), "priority": 75})

    home_quads = compute_workload_aware_home_quadrants(tasks, farm, n_units, pos_by_idx)
    sw_count = sum(1 for q in home_quads.values() if q == "SW")
    assert sw_count == 1, f"Expected 1 worker to SW for 12 tasks, got {sw_count}"
    assert home_quads[0] in ("NW", "NE", "SW")


def test_spatial_proximity_matching():
    """Workers already standing in NE should be assigned to NE before NW workers."""
    farm = MockFarm(unlocked=["NW", "NE"])
    n_units = 6
    # Units 0, 1, 2 at NW shed (4, 4); Units 3, 4, 5 in NE (7, 2)
    pos_by_idx = {
        0: (4, 4),
        1: (4, 4),
        2: (4, 4),
        3: (7, 2),
        4: (7, 2),
        5: (7, 2),
    }
    # Equal demand: 24 NW, 24 NE
    tasks = [{"op": "WATER", "target": (2, 2), "priority": 75} for _ in range(24)] + \
            [{"op": "WATER", "target": (7, 2), "priority": 75} for _ in range(24)]

    home_quads = compute_workload_aware_home_quadrants(tasks, farm, n_units, pos_by_idx)
    # Units 3, 4, 5 are physically in NE, should get NE
    assert home_quads[3] == "NE"
    assert home_quads[4] == "NE"
    assert home_quads[5] == "NE"
    # Units 0, 1, 2 are in NW, should get NW
    assert home_quads[0] == "NW"
    assert home_quads[1] == "NW"
    assert home_quads[2] == "NW"


def test_no_diagonal_jumps():
    """Worker in SW should not be assigned to NE when alternative NW units exist."""
    farm = MockFarm(unlocked=["NW", "NE", "SW"])
    n_units = 4
    pos_by_idx = {
        0: (4, 4),  # NW
        1: (4, 4),  # NW
        2: (2, 7),  # SW
        3: (7, 2),  # NE
    }
    # Demand requires 1 NE, 2 NW, 1 SW
    tasks = [
        {"op": "WATER", "target": (2, 2), "priority": 75},
        {"op": "WATER", "target": (7, 2), "priority": 75},
        {"op": "WATER", "target": (2, 7), "priority": 75},
    ]
    home_quads = compute_workload_aware_home_quadrants(tasks, farm, n_units, pos_by_idx)
    assert home_quads[2] != "NE", "SW unit 2 should never be assigned to NE diagonally"
    assert home_quads[3] != "SW", "NE unit 3 should never be assigned to SW diagonally"


def test_dynamic_serviceability_evaluation():
    """Verify evaluate_sw_serviceability operates correctly with dynamic allocation."""
    set_dynamic_zonal_allocation(True)
    try:
        farm = MockFarm(unlocked=["NW", "NE"])
        farm.money = 5000.0
        # Mock forecast
        forecast = MagicMock()
        
        # Test evaluation with k=5
        is_serv, best_k, diag = evaluate_sw_serviceability(
            current_day=11, farm=farm, money=5000.0, forecast=forecast, force_k_tiles=5
        )
        assert best_k == 5
        assert diag["expected_nw_ne_opportunity_cost"] == 0.0
        assert diag["net_marginal_profit"] > 0
        assert is_serv is True
    finally:
        set_dynamic_zonal_allocation(False)
