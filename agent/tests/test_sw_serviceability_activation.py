"""Regression tests for isolated SW P1.2 serviceability-aware activation.

P1.2 = P1 purchase correction + P1.1 responsive scheduler + activation gated
by explicit serviceability.  The new flag defaults OFF and must not alter
Control/P1/P1.1 behavior.
"""
import pytest

import config
import strategy.land_serviceability_model as lsm
from strategy.land_serviceability_model import evaluate_sw_serviceability
from strategy.macro_planner import MacroPlanner
from test_macro_planner import BASE_PRICES, make_ctx, make_forecast


@pytest.fixture(autouse=True)
def _reset_sw_p12_flags():
    old_sched = config.SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED
    old_act = config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED
    try:
        config.set_sw_workload_responsive_scheduler(False)
        config.set_sw_serviceability_aware_activation(False)
        yield
    finally:
        config.set_sw_workload_responsive_scheduler(old_sched)
        config.set_sw_serviceability_aware_activation(old_act)


def _sw_plants(plan, farm):
    return [
        (pos, crop)
        for pos, crop in plan.plant_queue
        if farm.quadrant_of(pos) == "SW"
    ]


def _serviceability_diag(*, serviceable, best_k=15, serviceable_k=5):
    return (
        bool(serviceable),
        int(best_k),
        {
            "is_serviceable": bool(serviceable),
            "best_k_tiles": int(best_k),
            "best_k_serviceable": int(serviceable_k),
            "serviceability_fraction": (
                float(serviceable_k) / float(best_k) if best_k else 0.0
            ),
            "responsive_scheduler_capacity": True,
            "surplus_units_for_sw": 2 if serviceable else 0,
            "nw_committed_workload": 24.0,
            "ne_committed_workload": 24.0,
        },
    )


def test_p12_flag_defaults_off():
    assert config.SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED is False
    assert config.get_sw_serviceability_aware_activation() is False


def test_evaluator_default_semantics_unchanged_when_override_not_requested():
    ctx = make_ctx(
        day=12,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
    )
    farm = ctx["farm"]
    default = evaluate_sw_serviceability(
        12, farm, 10000, make_forecast(BASE_PRICES), target_quadrant=3, hour=10
    )
    explicit_legacy = evaluate_sw_serviceability(
        12,
        farm,
        10000,
        make_forecast(BASE_PRICES),
        target_quadrant=3,
        hour=10,
        responsive_scheduler_capacity=False,
    )
    assert default == explicit_legacy
    assert default[2]["responsive_scheduler_capacity"] is False


def test_responsive_capacity_diagnostics_are_explicit_and_use_safety_reserve():
    ctx = make_ctx(
        day=12,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
        wheat_tiles=10,
    )
    farm = ctx["farm"]
    result = evaluate_sw_serviceability(
        12,
        farm,
        10000,
        make_forecast(BASE_PRICES),
        target_quadrant=3,
        hour=10,
        reserve_desired_herd=False,
        responsive_scheduler_capacity=True,
    )
    diag = result[2]
    assert diag["responsive_scheduler_capacity"] is True
    assert isinstance(diag["core_required_units"], int)
    assert diag["core_required_units"] >= 0
    assert isinstance(diag["surplus_units_for_sw"], int)
    assert diag["surplus_units_for_sw"] >= 0


def test_activation_flag_fails_closed_without_responsive_scheduler(monkeypatch):
    ctx = make_ctx(
        day=12,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
    )
    config.set_sw_serviceability_aware_activation(True)
    config.set_sw_workload_responsive_scheduler(False)

    # If the evaluator is called in this state, the fail-closed contract broke.
    monkeypatch.setattr(
        lsm,
        "evaluate_sw_serviceability",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must fail closed")),
    )

    plan = MacroPlanner(make_forecast(BASE_PRICES)).build(ctx)
    assert _sw_plants(plan, ctx["farm"]) == []
    diag = plan.diagnostics["sw_serviceability_activation"]
    assert diag["is_serviceable"] is False
    assert diag["reason"] == "responsive_scheduler_required"


def test_unserviceable_sw_queues_no_new_sw_crops(monkeypatch):
    ctx = make_ctx(
        day=12,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
    )
    config.set_sw_workload_responsive_scheduler(True)
    config.set_sw_serviceability_aware_activation(True)

    monkeypatch.setattr(
        lsm,
        "evaluate_sw_serviceability",
        lambda *a, **k: _serviceability_diag(
            serviceable=False, best_k=15, serviceable_k=0
        ),
    )

    plan = MacroPlanner(make_forecast(BASE_PRICES)).build(ctx)
    assert _sw_plants(plan, ctx["farm"]) == []
    diag = plan.diagnostics["sw_serviceability_activation"]
    assert diag["is_serviceable"] is False
    assert diag["activated_empty_tiles"] == 0


def test_serviceable_k_caps_sw_activation_not_nominal_best_k(monkeypatch):
    ctx = make_ctx(
        day=12,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
    )
    config.set_sw_workload_responsive_scheduler(True)
    config.set_sw_serviceability_aware_activation(True)

    seen_kwargs = {}

    def fake_eval(*args, **kwargs):
        seen_kwargs.update(kwargs)
        return _serviceability_diag(
            serviceable=True, best_k=15, serviceable_k=5
        )

    monkeypatch.setattr(lsm, "evaluate_sw_serviceability", fake_eval)

    plan = MacroPlanner(make_forecast(BASE_PRICES)).build(ctx)
    sw = _sw_plants(plan, ctx["farm"])
    assert len(sw) == 5
    assert seen_kwargs["reserve_desired_herd"] is False
    assert seen_kwargs["responsive_scheduler_capacity"] is True
    assert seen_kwargs["activation_context"] is True
    diag = plan.diagnostics["sw_serviceability_activation"]
    assert diag["nominal_best_k"] == 15
    assert diag["serviceable_k"] == 5
    assert diag["activated_empty_tiles"] == 5


def test_activation_context_does_not_recharge_land_cost():
    ctx = make_ctx(
        day=12,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
        wheat_tiles=10,
    )
    farm = ctx["farm"]
    purchase = evaluate_sw_serviceability(
        12,
        farm,
        10000,
        make_forecast(BASE_PRICES),
        target_quadrant=3,
        hour=10,
        reserve_desired_herd=False,
        responsive_scheduler_capacity=True,
        activation_context=False,
    )
    activation = evaluate_sw_serviceability(
        12,
        farm,
        10000,
        make_forecast(BASE_PRICES),
        target_quadrant=3,
        hour=10,
        reserve_desired_herd=False,
        responsive_scheduler_capacity=True,
        activation_context=True,
    )
    assert purchase[2]["land_charge_in_evaluation"] == 2000.0
    assert activation[2]["land_charge_in_evaluation"] == 0.0
    assert activation[2]["activation_context"] is True
    assert activation[2]["net_marginal_profit"] >= purchase[2]["net_marginal_profit"]


def test_flag_off_preserves_legacy_activation_path(monkeypatch):
    ctx = make_ctx(
        day=12,
        money=10000,
        hands=tuple(range(12)),
        unlocked=("NW", "NE", "SW"),
    )
    config.set_sw_workload_responsive_scheduler(True)
    config.set_sw_serviceability_aware_activation(False)

    seen = []

    def fake_eval(*args, **kwargs):
        seen.append(dict(kwargs))
        return _serviceability_diag(
            serviceable=False, best_k=5, serviceable_k=0
        )

    monkeypatch.setattr(lsm, "evaluate_sw_serviceability", fake_eval)

    plan = MacroPlanner(make_forecast(BASE_PRICES)).build(ctx)
    # Legacy behavior intentionally ignores is_serviceable and uses best_k.
    assert len(_sw_plants(plan, ctx["farm"])) == 5
    assert seen
    assert "responsive_scheduler_capacity" not in seen[-1]
    assert "reserve_desired_herd" not in seen[-1]
