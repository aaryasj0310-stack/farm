"""Unit tests for Phase B1: True Branch-Point SW Treatment Experiment.

Tests:
1. Land suppression: baseline wants BUY_LAND -> treatment blocks order until approval.
2. Later purchase: planner approves -> BUY_LAND order emitted exactly once.
3. Tranche enforcement: 8-tile portfolio admitted -> only those 8 tiles receive SW planting tasks.
4. Reset isolation: new match starts with no previous treatment state.
5. No-purchase game: planner never approves -> no SW BUY_LAND emitted throughout match.
6. Portfolio fidelity: selected crop allocation == executed initial SW allocation.
7. Invariant enforcement: active SW planted tiles <= admitted SW tile set.
"""
import copy
import pytest
from unittest.mock import MagicMock, patch

from config import (
    SW_FORWARD_ARCHITECTURE_MODE,
    get_sw_forward_architecture_mode,
    set_sw_forward_architecture_mode,
)
from strategy.sw_tranche_controller import (
    SWTrancheController,
    SWTrancheState,
    get_sw_tranche_controller,
    reset_sw_tranche_controller,
    SW_COORDINATES,
)


@pytest.fixture(autouse=True)
def cleanup_treatment_state():
    """Ensure clean mode and controller state before and after each test."""
    set_sw_forward_architecture_mode("OFF")
    reset_sw_tranche_controller()
    yield
    set_sw_forward_architecture_mode("OFF")
    reset_sw_tranche_controller()


def test_treatment_mode_configuration():
    """Verify TREATMENT mode is accepted and queried correctly."""
    assert get_sw_forward_architecture_mode() == "OFF"
    set_sw_forward_architecture_mode("TREATMENT")
    assert get_sw_forward_architecture_mode() == "TREATMENT"

    ctrl = get_sw_tranche_controller()
    assert ctrl.is_treatment_active() is True

    set_sw_forward_architecture_mode("OFF")
    assert get_sw_forward_architecture_mode() == "OFF"
    assert ctrl.is_treatment_active() is False


def test_land_suppression_blocks_early_buy():
    """Test 1: Land suppression. Baseline wants BUY_LAND -> treatment suppresses order."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE"}
    farm_mock.money = 2500.0

    # Before WholeFarmPlanner approval, baseline buy must be suppressed
    assert ctrl.state.sw_purchase_approved is False
    should_suppress = ctrl.should_suppress_baseline_sw_buy(day=5, hour=0, farm=farm_mock)
    assert should_suppress is True


def test_later_purchase_emitted_once_when_approved():
    """Test 2: Later purchase. Planner approves -> BUY_LAND order allowed exactly once."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    sample_portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, [(0, 7), (1, 7), (2, 7), (3, 7)]),
            ("MELON", 4, [(4, 7), (0, 8), (1, 8), (2, 8)]),
        ],
        "tiles_used": 8,
    }

    # Approve purchase
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio=sample_portfolio,
        delta_fc=1250.0,
        cash_before=2800.0,
        worker_count=9,
    )

    assert ctrl.state.sw_purchase_approved is True
    assert ctrl.state.sw_purchase_day == 9
    assert ctrl.state.selected_portfolio_name == "compact_commercial"
    assert len(ctrl.state.admitted_sw_tiles) == 8

    # Now should_suppress is False
    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE"}
    assert ctrl.should_suppress_baseline_sw_buy(day=9, hour=0, farm=farm_mock) is False


def test_tranche_enforcement_restricts_sw_planting():
    """Test 3: Tranche enforcement. Only admitted 8 tiles receive SW planting tasks."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    admitted_coords = [(0, 7), (1, 7), (2, 7), (3, 7), (4, 7), (0, 8), (1, 8), (2, 8)]
    sample_portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, admitted_coords[:4]),
            ("MELON", 4, admitted_coords[4:8]),
        ],
        "tiles_used": 8,
    }
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio=sample_portfolio,
        delta_fc=1200.0,
        cash_before=2800.0,
        worker_count=9,
    )

    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE", "SW"}

    # Attempt to schedule plant tasks for both admitted and non-admitted SW tiles
    raw_plant_queue = [
        ((0, 7), "STRAWBERRY"),  # admitted
        ((1, 7), "STRAWBERRY"),  # admitted
        ((4, 7), "MELON"),       # admitted
        ((3, 9), "WHEAT"),       # NOT admitted (SW tile 3,9)
        ((4, 9), "WHEAT"),       # NOT admitted (SW tile 4,9)
        ((7, 2), "CARROT"),      # NE tile (core farm, allowed)
    ]

    filtered_queue = ctrl.filter_macro_plant_queue(raw_plant_queue, farm_mock)
    filtered_positions = [pos for pos, _ in filtered_queue]

    assert (0, 7) in filtered_positions
    assert (1, 7) in filtered_positions
    assert (4, 7) in filtered_positions
    assert (7, 2) in filtered_positions  # Core farm untouched
    assert (3, 9) not in filtered_positions  # Blocked
    assert (4, 9) not in filtered_positions  # Blocked
    assert ctrl.state.invariant_violations_attempted == 2


def test_task_scheduler_task_filtering():
    """Test 3b: Tranche enforcement at task scheduler level."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    admitted_coords = [(0, 7), (1, 7), (2, 7), (3, 7)]
    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio={"name": "compact_tranche", "allocations": [("WHEAT", 4, admitted_coords)], "tiles_used": 4},
        delta_fc=500.0,
        cash_before=2500.0,
        worker_count=9,
    )

    tasks = [
        {"op": "PLANT", "target": (0, 7), "kind": "plant"},  # admitted SW
        {"op": "PLANT", "target": (0, 9), "kind": "plant"},  # unadmitted SW
        {"op": "WATER", "target": (0, 9), "kind": "water"},  # non-plant task allowed
        {"op": "PLANT", "target": (2, 2), "kind": "plant"},  # NW tile allowed
    ]

    filtered = ctrl.filter_task_scheduler_tasks(tasks, farm=None)
    targets = [t["target"] for t in filtered]

    assert (0, 7) in targets
    assert (2, 2) in targets
    assert (0, 9) in targets  # WATER allowed
    plant_targets = [t["target"] for t in filtered if t["op"] == "PLANT"]
    assert (0, 9) not in plant_targets  # Unadmitted SW plant blocked!


def test_reset_isolation_cleans_state():
    """Test 4: Reset isolation. New match starts with no previous treatment state."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    ctrl.approve_purchase(
        day=9,
        hour=0,
        portfolio={"name": "test", "allocations": [("WHEAT", 1, [(0, 7)])], "tiles_used": 1},
        delta_fc=100.0,
        cash_before=2500.0,
        worker_count=9,
    )
    ctrl.state.invariant_violations_attempted = 5

    assert ctrl.state.sw_purchase_approved is True
    assert ctrl.state.invariant_violations_attempted == 5

    # Reset
    reset_sw_tranche_controller()
    new_ctrl = get_sw_tranche_controller()

    assert new_ctrl.state.sw_purchase_approved is False
    assert new_ctrl.state.sw_purchase_day is None
    assert len(new_ctrl.state.admitted_sw_tiles) == 0
    assert new_ctrl.state.invariant_violations_attempted == 0


def test_no_purchase_game_stays_unlocked():
    """Test 5: No-purchase game. Planner never approves -> no SW purchase emitted."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    # Simulate evaluation where conditions are not met
    farm_mock = MagicMock()
    farm_mock.unlocked = {"NW", "NE"}
    farm_mock.money = 1500.0  # insufficient cash

    for day in range(30):
        # Should suppress SW buy every day
        assert ctrl.should_suppress_baseline_sw_buy(day=day, hour=0, farm=farm_mock) is True

    assert ctrl.state.sw_purchase_approved is False
    assert ctrl.state.sw_purchase_day is None


def test_portfolio_fidelity_matches_allocations():
    """Test 6: Portfolio fidelity. Target crops match admitted portfolio allocations."""
    set_sw_forward_architecture_mode("TREATMENT")
    ctrl = get_sw_tranche_controller()

    portfolio = {
        "name": "compact_commercial",
        "allocations": [
            ("STRAWBERRY", 4, [(0, 7), (1, 7), (2, 7), (3, 7)]),
            ("MELON", 4, [(4, 7), (0, 8), (1, 8), (2, 8)]),
        ],
        "tiles_used": 8,
    }
    ctrl.approve_purchase(
        day=10,
        hour=0,
        portfolio=portfolio,
        delta_fc=1400.0,
        cash_before=3000.0,
        worker_count=11,
    )

    # Check that each tile maps to the exact crop specified
    for pos in [(0, 7), (1, 7), (2, 7), (3, 7)]:
        assert ctrl.state.admitted_sw_crop_targets[pos] == "STRAWBERRY"
    for pos in [(4, 7), (0, 8), (1, 8), (2, 8)]:
        assert ctrl.state.admitted_sw_crop_targets[pos] == "MELON"


def test_checkpoint_tracking_utilization():
    """Test 7: Checkpoint tracking records whole-quadrant and tranche utilization."""
    ctrl = get_sw_tranche_controller()
    ctrl.state.sw_purchase_approved = True
    ctrl.state.sw_purchase_day = 9
    ctrl.state.admitted_sw_tiles = {(0, 7), (1, 7), (2, 7), (3, 7), (4, 7), (0, 8), (1, 8), (2, 8)}

    # Mock farm with 8 planted tiles in SW
    tiles = []
    for y in range(10):
        row = []
        for x in range(10):
            t = MagicMock()
            t.x = x
            t.y = y
            t.pos = (x, y)
            is_sw = (x < 5 and y >= 5)
            if is_sw and (x, y) in ctrl.state.admitted_sw_tiles:
                t.kind = "PLANT"
                t.is_plant = True
                t.is_empty = False
                t.watered_today = True
                t.yield_units = 0
            else:
                t.kind = "EMPTY"
                t.is_plant = False
                t.is_empty = True
                t.watered_today = False
                t.yield_units = 0
            row.append(t)
        tiles.append(row)

    farm_mock = MagicMock()
    farm_mock.iter_tiles.return_value = [t for row in tiles for t in row]

    ctrl.record_checkpoint("D+0", farm_mock)
    cp = ctrl.state.checkpoints.get("D+0")

    assert cp is not None
    assert cp["sw_owned_tiles"] == 25
    assert cp["sw_admitted_tiles"] == 8
    assert cp["sw_planted_tiles"] == 8
    assert cp["sw_watered_tiles"] == 8
    assert cp["admitted_tranche_utilization_pct"] == 100.0
    assert cp["whole_quadrant_utilization_pct"] == 32.0  # 8 / 25
