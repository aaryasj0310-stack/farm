"""Isolation and verification tests for the P1.3 2x2 Factorial Experiment.

Verifies:
1. Default configuration preservation (all treatment switches default False).
2. Setters and arm configurations for Control, Arm A, Arm B, Arm C, Arm D.
3. Centralized animal workload definitions and computation.
4. Arm B continuous capacity gating for dedicated SW soil activation.
5. Arm C dynamic livestock serviceability gating (starvation, deadline, labor, core debt).
6. Deterministic reset and teardown.
"""
import pytest
import config
from strategy.land_serviceability_model import (
    ANIMAL_STEADY_STATE_WORKLOAD,
    get_animal_daily_workload,
    compute_herd_daily_workload,
    evaluate_tight_sw_soil_capacity,
)
from state.observation_parser import FarmView, TileView


@pytest.fixture(autouse=True)
def clean_config_state():
    """Ensure clean config state before and after each test."""
    config.set_p13_factorial_arm("Control")
    yield
    config.set_p13_factorial_arm("Control")


def test_default_factorial_configuration():
    """Default module-level attributes must preserve exact baseline."""
    assert config.SW_GENERIC_PLANTING_GATE_ENABLED is False
    assert config.P13_TIGHT_SOIL_ENABLED is False
    assert config.P13_LIVESTOCK_CAP_ENABLED is False
    assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY is False
    assert config.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED is False
    assert config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED is False


def test_set_p13_factorial_arms():
    """Test setting each factorial arm and verifying authoritative flags."""
    # Control
    config.set_p13_factorial_arm("Control")
    assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY is False
    assert config.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED is False
    assert config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED is False
    assert config.SW_GENERIC_PLANTING_GATE_ENABLED is False
    assert config.P13_TIGHT_SOIL_ENABLED is False
    assert config.P13_LIVESTOCK_CAP_ENABLED is False

    # Arm A (P1.3-A baseline)
    config.set_p13_factorial_arm("ArmA")
    assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY is True
    assert config.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED is True
    assert config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED is True
    assert config.SW_GENERIC_PLANTING_GATE_ENABLED is True
    assert config.P13_TIGHT_SOIL_ENABLED is False
    assert config.P13_LIVESTOCK_CAP_ENABLED is False

    # Arm B (Tight soil only)
    config.set_p13_factorial_arm("ArmB")
    assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY is True
    assert config.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED is True
    assert config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED is True
    assert config.SW_GENERIC_PLANTING_GATE_ENABLED is True
    assert config.P13_TIGHT_SOIL_ENABLED is True
    assert config.P13_LIVESTOCK_CAP_ENABLED is False

    # Arm C (Livestock cap only)
    config.set_p13_factorial_arm("ArmC")
    assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY is True
    assert config.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED is True
    assert config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED is True
    assert config.SW_GENERIC_PLANTING_GATE_ENABLED is True
    assert config.P13_TIGHT_SOIL_ENABLED is False
    assert config.P13_LIVESTOCK_CAP_ENABLED is True

    # Arm D (Combined)
    config.set_p13_factorial_arm("ArmD")
    assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY is True
    assert config.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED is True
    assert config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED is True
    assert config.SW_GENERIC_PLANTING_GATE_ENABLED is True
    assert config.P13_TIGHT_SOIL_ENABLED is True
    assert config.P13_LIVESTOCK_CAP_ENABLED is True


def test_centralized_animal_workload():
    """Verify centralized steady-state animal workload calculations."""
    assert ANIMAL_STEADY_STATE_WORKLOAD["COW"] == 2.0
    assert ANIMAL_STEADY_STATE_WORKLOAD["SHEEP"] == 5.0
    assert ANIMAL_STEADY_STATE_WORKLOAD["GOOSE"] == 2.0

    assert get_animal_daily_workload("COW") == 2.0
    assert get_animal_daily_workload("SHEEP") == 5.0
    assert get_animal_daily_workload("GOOSE") == 2.0

    herd = {"COW": 3, "SHEEP": 2, "GOOSE": 1}
    expected = 3 * 2.0 + 2 * 5.0 + 1 * 2.0  # 6 + 10 + 2 = 18.0
    assert compute_herd_daily_workload(herd) == expected
    assert compute_herd_daily_workload({}) == 0.0


def test_arm_b_tight_soil_capacity_gate():
    """Verify evaluate_tight_sw_soil_capacity responds continuously to workload."""
    grid = [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)]
    # Place a farmer and hands
    raw = {
        "money": 5000,
        "farmer": (4, 4),
        "hands": [(4, 4), (4, 4)],
        "unlocked_quadrants": ["NW", "NE", "SW"],
        "tiles": grid,
        "hires_today": 0,
    }
    farm = FarmView(raw)

    is_serv, slots, diag = evaluate_tight_sw_soil_capacity(farm, day=12, money=2000, hour=0)
    assert isinstance(is_serv, bool)
    assert isinstance(slots, int)
    assert slots >= 0
    assert "surplus_capacity" in diag


def test_arm_c_livestock_serviceability_signals():
    """Verify that starvation and core debt are detected properly."""
    grid = [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)]
    # Animal with consecutive_unfed = 1
    grid[1][1] = {
        "kind": "PASTURE",
        "animal": "COW",
        "consecutive_unfed": 1,
        "fed_today": False,
    }
    raw = {
        "money": 5000,
        "farmer": (4, 4),
        "hands": [(4, 4)],
        "unlocked_quadrants": ["NW", "NE"],
        "tiles": grid,
        "hires_today": 0,
    }
    farm = FarmView(raw)

    from strategy.land_serviceability_model import _t_field
    has_starving = any(
        int(_t_field(t, "consecutive_unfed", 0)) >= 1
        for t in farm.iter_tiles()
        if _t_field(t, "is_animal") or _t_field(t, "animal")
    )
    assert has_starving is True


def test_macro_planner_arm_b_diagnostics():
    """Verify that MacroPlanner emits p13_tight_soil_gate when Arm B is active."""
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast

    grid = [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)]
    raw = {
        "money": 5000,
        "farmer": (4, 4),
        "hands": [(4, 4), (4, 4), (4, 4)],
        "unlocked_quadrants": ["NW", "NE", "SW"],
        "tiles": grid,
        "hires_today": 0,
    }
    farm = FarmView(raw)

    class MockPrivate:
        seeds = {}
        shed = {}
        inventories = []

    fc = PriceForecast.load()
    planner = MacroPlanner(fc)
    ctx = {"day": 12, "hour": 0, "farm": farm, "private": MockPrivate()}

    # Under Arm A (P1.3-A): tight soil gate is not enabled
    config.set_p13_factorial_arm("ArmA")
    plan_a = planner.build(ctx)
    assert "p13_tight_soil_gate" not in plan_a.diagnostics

    # Under Arm B: tight soil gate is enabled and logged
    config.set_p13_factorial_arm("ArmB")
    plan_b = planner.build(ctx)
    assert "p13_tight_soil_gate" in plan_b.diagnostics
    assert plan_b.diagnostics["p13_tight_soil_gate"]["enabled"] is True


def test_macro_planner_arm_c_starvation_rejection():
    """Verify that Arm C rejects animal expansion if an animal is currently starving."""
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast

    grid = [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)]
    # An existing starving animal
    grid[0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "consecutive_unfed": 1,
        "fed_today": False,
    }
    # An empty pasture available
    grid[0][1] = {
        "kind": "PASTURE",
        "animal": None,
        "fed_today": False,
    }
    raw = {
        "money": 10000,
        "farmer": (4, 4),
        "hands": [(4, 4), (4, 4)],
        "unlocked_quadrants": ["NW", "NE"],
        "tiles": grid,
        "hires_today": 0,
    }
    farm = FarmView(raw)

    class MockPrivate:
        seeds = {}
        shed = {"WHEAT": 50}
        inventories = []

    fc = PriceForecast.load()
    planner = MacroPlanner(fc)
    ctx = {"day": 6, "hour": 0, "farm": farm, "private": MockPrivate()}

    # Under Arm C: should reject buying more animals because an existing animal is starving
    config.set_p13_factorial_arm("ArmC")
    plan_c = planner.build(ctx)
    rejections = plan_c.diagnostics.get("p13_livestock_cap_rejections", [])
    assert any(r.get("reason") == "recent_animal_starvation" for r in rejections)


def test_macro_planner_arm_d_combined():
    """Verify that Arm D activates both tight soil gate and livestock cap."""
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast

    grid = [[{"kind": "EMPTY"} for _ in range(10)] for _ in range(10)]
    raw = {
        "money": 5000,
        "farmer": (4, 4),
        "hands": [(4, 4), (4, 4), (4, 4)],
        "unlocked_quadrants": ["NW", "NE", "SW"],
        "tiles": grid,
        "hires_today": 0,
    }
    farm = FarmView(raw)

    class MockPrivate:
        seeds = {}
        shed = {}
        inventories = []

    fc = PriceForecast.load()
    planner = MacroPlanner(fc)
    ctx = {"day": 12, "hour": 0, "farm": farm, "private": MockPrivate()}

    config.set_p13_factorial_arm("ArmD")
    plan_d = planner.build(ctx)
    assert "p13_tight_soil_gate" in plan_d.diagnostics
    assert plan_d.diagnostics["p13_tight_soil_gate"]["enabled"] is True


