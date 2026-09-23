"""Isolated P1.3-A: generic planting cannot bypass SW serviceability.

The test farm deliberately has NO free NW/NE tiles but has SW pasture space and
a positive global wheat requirement. This exposes the previously hidden bypass:
an ordinary empty farm would satisfy global wheat demand before reaching SW.
"""
import sys

import pytest

import config
import strategy.land_serviceability_model as serviceability
from strategy.macro_planner import MacroPlanner
from test_macro_planner import BASE_PRICES, make_ctx, make_forecast


@pytest.fixture(autouse=True)
def _restore_isolated_flags():
    # ArmA legitimately resets much more than the four P1 flags. Restore the
    # entire touched state after every test so a full-suite run cannot leak a
    # production quadrant hard-block into unrelated SW tests.
    original = {
        name: getattr(config, name)
        for name in (
            "SW_P1_PURCHASE_COMMITTED_HERD_ONLY",
            "SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED",
            "SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED",
            "SW_GENERIC_PLANTING_GATE_ENABLED",
            "SW_OWNERSHIP_MODE",
            "SW_TIMING_PRIOR_ENABLED",
            "SW_ACTIVATION_MODE",
            "STRATEGIC_SW_OWNERSHIP_ENABLED",
            "DYNAMIC_ZONAL_ALLOCATION",
            "DYNAMIC_SW_CROPS_ENABLED",
            "PERSISTENT_WORKER_LOCALITY_ENABLED",
            "SW_CELL_HOUSING_ENABLED",
        )
    }
    original_blocks = config.get_quadrant_hard_block()
    try:
        config.set_sw_workload_responsive_scheduler(True)
        config.set_sw_serviceability_aware_activation(True)
        config.set_sw_generic_planting_gate(True)
        yield
    finally:
        config.set_quadrant_hard_block(original_blocks)
        for name, value in original.items():
            setattr(config, name, value)
        # Restore any mirrored globals changed by the ArmA reset test.
        for mod_name in (
            "strategy.expansion_planner", "agent.strategy.expansion_planner",
            "strategy.macro_planner", "agent.strategy.macro_planner",
            "strategy.land_serviceability_model", "agent.strategy.land_serviceability_model",
            "execution.task_scheduler", "agent.execution.task_scheduler",
            "strategy.pasture_planner", "agent.strategy.pasture_planner",
            "strategy.sw_cell_allocator", "agent.strategy.sw_cell_allocator",
        ):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                for name, value in original.items():
                    if hasattr(mod, name):
                        setattr(mod, name, value)


def _eval(serviceable=False, nominal=15, safe=0):
    return (
        bool(serviceable),
        int(nominal),
        {
            "is_serviceable": bool(serviceable),
            "best_k_tiles": int(nominal),
            "best_k_serviceable": int(safe),
            "serviceability_fraction": safe / nominal if nominal else 0.0,
            "responsive_scheduler_capacity": True,
            "surplus_units_for_sw": 0 if not serviceable else 2,
        },
    )


def _nw_ne_occupied():
    # Real crop objects would introduce competing wheat and animal-care work.
    # Existing WEED tiles are nonempty, unlocked, and cannot be replanted.
    return [
        (x, y, {"kind": "WEED", "pos": (x, y), "x": x, "y": y})
        for y in range(5) for x in range(10)
    ]


def _existing_sw_plants(n):
    return [
        (
            x, y,
            {
                "kind": "PLANT", "crop": "CARROT", "pos": (x, y),
                "x": x, "y": y, "watered_today": True,
                "planted_day": 11, "yield_units": 0,
                "consecutive_unwatered": 0,
            },
        )
        for x, y in list(sorted(config.SW_SOIL_TILES))[:n]
    ]


def _ctx(*, core_filled=True, existing_sw=0, extra_structures=(), day=12):
    structures = (
        (_nw_ne_occupied() if core_filled else [])
        + _existing_sw_plants(existing_sw)
        + list(extra_structures)
    )
    return make_ctx(
        day=day,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
        seeds={"WHEAT": 80, "CARROT": 80},
        structures=structures,
    )


def _new_sw(plan, farm):
    return [
        (tuple(pos), crop)
        for pos, crop in plan.plant_queue
        if farm.quadrant_of(pos) == "SW"
    ]


def _build(ctx):
    return MacroPlanner(make_forecast(BASE_PRICES)).build(ctx)


def test_generic_wheat_demand_is_real_and_gate_blocks_sw_pasture(monkeypatch):
    """A: OFF exposes the old bypass; ON prevents it under identical demand."""
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=False, nominal=15, safe=0),
    )
    config.set_sw_generic_planting_gate(False)
    legacy = _ctx()
    old_plan = _build(legacy)
    old_pasture = [
        pos for pos, crop in _new_sw(old_plan, legacy["farm"])
        if pos in config.SW_PASTURE_TILES and crop == "WHEAT"
    ]
    assert old_pasture, "test setup must demonstrate the generic-wheat bypass"

    config.set_sw_generic_planting_gate(True)
    gated = _ctx()
    plan = _build(gated)
    assert not [pos for pos, crop in _new_sw(plan, gated["farm"])
                if pos in config.SW_PASTURE_TILES]
    assert _new_sw(plan, gated["farm"]) == []
    diag = plan.diagnostics["sw_generic_planting_gate"]
    assert diag["enabled"] is True
    assert diag["excluded_sw_pasture_empty_tiles"] > 0


def test_serviceable_dedicated_sw_soil_still_activates(monkeypatch):
    """B: SW soil planting is still authorized through the dedicated controller."""
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=True, nominal=15, safe=5),
    )
    ctx = _ctx(core_filled=False)
    plan = _build(ctx)
    planted = _new_sw(plan, ctx["farm"])
    assert len(planted) == 5
    assert all(pos in config.SW_SOIL_TILES for pos, _ in planted)
    assert all(pos not in config.SW_PASTURE_TILES for pos, _ in planted)
    assert plan.diagnostics["sw_serviceability_activation"]["activated_empty_tiles"] == 5


def test_unserviceable_activation_blocks_all_sw_with_positive_wheat_demand(monkeypatch):
    """C: an unserviceable gate must not be bypassed by generic wheat."""
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=False, nominal=15, safe=0),
    )
    ctx = _ctx()
    plan = _build(ctx)
    assert _new_sw(plan, ctx["farm"]) == []
    assert plan.diagnostics["sw_serviceability_activation"]["is_serviceable"] is False
    assert plan.diagnostics["sw_generic_planting_gate"]["excluded_sw_pasture_empty_tiles"] > 0


@pytest.mark.parametrize("occupied", [3, 5])
def test_existing_sw_footprint_is_counted_against_serviceable_cap(monkeypatch, occupied):
    """D: existing crops count against the entire SW activation footprint."""
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=True, nominal=15, safe=5),
    )
    ctx = _ctx(existing_sw=occupied)
    plan = _build(ctx)
    planted = _new_sw(plan, ctx["farm"])
    assert len(planted) == 5 - occupied
    assert all(pos in config.SW_SOIL_TILES for pos, _ in planted)
    assert plan.diagnostics["sw_serviceability_activation"]["existing_sw_plants"] == occupied
    assert len(planted) + occupied <= 5


def test_existing_sw_pasture_and_animal_are_not_changed(monkeypatch):
    """E: blocking new planting does not erase existing buildings/animals."""
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=False, nominal=15, safe=0),
    )
    pasture_pos = (0, 5)
    animal_pos = (1, 5)
    structures = [
        (*pasture_pos, {"kind": "PASTURE", "pos": pasture_pos}),
        (*animal_pos, {
            "kind": "PASTURE", "animal": "COW", "pos": animal_pos,
            "fed_today": True, "yield_units": 0, "consecutive_unfed": 0,
        }),
    ]
    ctx = _ctx(extra_structures=structures)
    farm = ctx["farm"]
    before = [
        (farm.tile_at(p).kind, farm.tile_at(p).animal)
        for p in (pasture_pos, animal_pos)
    ]
    plan = _build(ctx)
    assert not _new_sw(plan, farm)
    assert [
        (farm.tile_at(p).kind, farm.tile_at(p).animal)
        for p in (pasture_pos, animal_pos)
    ] == before
    assert all(pos not in (pasture_pos, animal_pos) for pos, _ in plan.plant_queue)


def test_nw_ne_planting_remains_safe_and_can_be_reallocated(monkeypatch):
    """F: core planting stays on unlocked, genuinely empty tiles."""
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=False, nominal=15, safe=0),
    )
    ctx_off = _ctx(core_filled=False)
    config.set_sw_generic_planting_gate(False)
    off_plan = _build(ctx_off)
    config.set_sw_generic_planting_gate(True)
    ctx_on = _ctx(core_filled=False)
    on_plan = _build(ctx_on)
    farm = ctx_on["farm"]
    core = [(pos, crop) for pos, crop in on_plan.plant_queue
            if farm.quadrant_of(pos) in ("NW", "NE")]
    assert core, "core planting must remain executable"
    assert all(farm.quadrant_of(pos) in farm.unlocked for pos, _ in core)
    assert all(farm.tile_at(pos).kind == "EMPTY" for pos, _ in core)
    assert not _new_sw(on_plan, farm)
    # In this observation core tiles are plentiful, so enabling the new gate
    # must not deprive them of previously available planting work.
    assert core == [(pos, crop) for pos, crop in off_plan.plant_queue
                    if ctx_off["farm"].quadrant_of(pos) in ("NW", "NE")]


def test_flag_off_preserves_original_p12_generic_planting_path(monkeypatch):
    """G: negative-control flag alone must reproduce the P1.2 bypass."""
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=False, nominal=15, safe=0),
    )
    config.set_sw_generic_planting_gate(False)
    ctx = _ctx()
    plan = _build(ctx)
    assert any(
        pos in config.SW_PASTURE_TILES and crop == "WHEAT"
        for pos, crop in _new_sw(plan, ctx["farm"])
    )
    assert "sw_generic_planting_gate" not in plan.diagnostics


def test_arma_resets_generic_gate_and_loaded_macro_module():
    """H: production ArmA removes P1.3-A treatment state."""
    import strategy.macro_planner as mp
    orig_blocks = config.get_quadrant_hard_block()
    orig_arm = getattr(config, "SW_EXPERIMENT_ARM", "ArmA")
    try:
        config.set_sw_generic_planting_gate(True)
        assert config.SW_GENERIC_PLANTING_GATE_ENABLED is True
        assert mp.SW_GENERIC_PLANTING_GATE_ENABLED is True
        config.set_sw_experiment_arm("ArmA")
        assert config.SW_GENERIC_PLANTING_GATE_ENABLED is False
        assert mp.SW_GENERIC_PLANTING_GATE_ENABLED is False
        assert config.get_sw_generic_planting_gate() is False
    finally:
        config.set_sw_experiment_arm(orig_arm)
        config.set_quadrant_hard_block(orig_blocks)


def test_high_global_wheat_target_cannot_refill_occupied_sw_soil_or_pasture(monkeypatch):
    monkeypatch.setattr(
        serviceability, "evaluate_sw_serviceability",
        lambda *a, **kw: _eval(serviceable=True, nominal=24, safe=5),
    )
    ctx = _ctx(day=15, existing_sw=5)
    plan = _build(ctx)
    assert not _new_sw(plan, ctx["farm"])
    assert plan.diagnostics["sw_generic_planting_gate"]["excluded_sw_pasture_empty_tiles"] > 0
