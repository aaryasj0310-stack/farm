"""Regression tests for housing-safe selective livestock reinvestment.

Verifies that post-Day-12 selective livestock orders are strictly bounded by
physically built, empty, unreserved pastures (Cases A through G).
"""
import pytest
from config import C4_LIVESTOCK_CUTOFF_DAY, ANIMALS
import config
from market.order_builder import OrderBuilder
from test_macro_planner import make_ctx


def make_test_ctx(day=12, hour=2, money=8000, unlocked=("NW", "NE"),
                  pastures=None, shed=None, inventories=None):
    if pastures is None:
        pastures = []
    if shed is None:
        shed = {"WHEAT": 50}
    ctx = make_ctx(day=day, money=money, unlocked=unlocked, shed=shed, structures=pastures)
    ctx["hour"] = hour
    if inventories:
        ctx["private"].inventories = inventories
    return ctx


@pytest.fixture(autouse=True)
def enable_selective_gate(monkeypatch):
    """Enable selective livestock gate for testing Day 12+ behavior."""
    monkeypatch.setattr(config, "SELECTIVE_LIVESTOCK_GATE_ENABLED", True)
    monkeypatch.setattr(config, "SELECTIVE_LIVESTOCK_MAX_DAY", 14)


def test_case_a_physical_empty_zero_blocks_reinvestment():
    """Test A: physical empty = 0, ROI/cash/feed ok -> 0 BUY_ANIMAL."""
    builder = OrderBuilder()
    occupied_pasture = [(2, 4, {"kind": "PASTURE", "animal": "COW", "pos": (2, 4), "x": 2, "y": 4})]
    ctx = make_test_ctx(day=12, hour=2, money=8000, pastures=occupied_pasture)
    intents = {"buy_animal": {"COW": 1}, "buy_wheat": 0}

    orders, ledger = builder.reinvest_livestock(ctx, intents)
    assert orders == []
    assert any(d.get("reason") == "no_empty_structure" for d in ledger.get("dropped", []))


def test_case_b_physical_empty_one_caps_request_of_three():
    """Test B: physical empty = 1, requested = 3 -> BUY_ANIMAL qty <= 1."""
    builder = OrderBuilder()
    pastures = [(2, 4, {"kind": "PASTURE", "pos": (2, 4), "x": 2, "y": 4})]
    ctx = make_test_ctx(day=12, hour=2, money=8000, pastures=pastures)
    intents = {"buy_animal": {"COW": 3}, "buy_wheat": 0}

    orders, ledger = builder.reinvest_livestock(ctx, intents)
    cow_orders = [o for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW"]
    total_cows = sum(o[2] for o in cow_orders)
    assert total_cows == 1
    assert any(d.get("kind") == "animal" and d.get("trimmed_from") == 3 for d in ledger.get("dropped", []))


def test_case_c_shed_cow_reserves_pasture():
    """Test C: physical empty = 2, cow in shed = 1 -> buy cap = 1."""
    builder = OrderBuilder()
    pastures = [
        (2, 4, {"kind": "PASTURE", "pos": (2, 4), "x": 2, "y": 4}),
        (3, 4, {"kind": "PASTURE", "pos": (3, 4), "x": 3, "y": 4}),
    ]
    ctx = make_test_ctx(day=12, hour=2, money=8000, pastures=pastures, shed={"WHEAT": 50, "COW": 1})
    intents = {"buy_animal": {"COW": 2}, "buy_wheat": 0}

    orders, ledger = builder.reinvest_livestock(ctx, intents)
    cow_orders = [o for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW"]
    assert sum(o[2] for o in cow_orders) == 1


def test_case_d_carried_cow_reserves_pasture():
    """Test D: physical empty = 2, carried cow = 1 -> buy cap = 1."""
    builder = OrderBuilder()
    pastures = [
        (2, 4, {"kind": "PASTURE", "pos": (2, 4), "x": 2, "y": 4}),
        (3, 4, {"kind": "PASTURE", "pos": (3, 4), "x": 3, "y": 4}),
    ]
    ctx = make_test_ctx(day=12, hour=2, money=8000, pastures=pastures, inventories=[{"COW": 1}])
    intents = {"buy_animal": {"COW": 2}, "buy_wheat": 0}

    orders, ledger = builder.reinvest_livestock(ctx, intents)
    cow_orders = [o for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW"]
    assert sum(o[2] for o in cow_orders) == 1


def test_case_e_queued_pastures_do_not_authorize_buys():
    """Test E: physical empty = 0, queued pasture = 1 -> 0 BUY_ANIMAL."""
    builder = OrderBuilder()
    ctx = make_test_ctx(day=12, hour=2, money=8000, pastures=[])
    intents = {
        "buy_animal": {"COW": 1},
        "pending_structures": {"PASTURE": 2},
        "buy_wheat": 0,
    }

    orders, ledger = builder.reinvest_livestock(ctx, intents)
    assert orders == []


def test_case_f_dynamic_pasture_cap_does_not_authorize_buys():
    """Test F: dynamic pasture cap = 10, physical empty = 0 -> 0 BUY_ANIMAL."""
    builder = OrderBuilder()
    ctx = make_test_ctx(day=13, hour=5, money=8000, pastures=[])
    intents = {"buy_animal": {"SHEEP": 2}, "buy_wheat": 0}

    orders, ledger = builder.reinvest_livestock(ctx, intents)
    assert orders == []


def test_case_g_pre_day12_behavior_unchanged(monkeypatch):
    """Test G: pre-Day-12 behavior unchanged."""
    monkeypatch.setattr(config, "SELECTIVE_LIVESTOCK_GATE_ENABLED", False)
    builder = OrderBuilder()
    pastures = [
        (2, 4, {"kind": "PASTURE", "pos": (2, 4), "x": 2, "y": 4}),
        (3, 4, {"kind": "PASTURE", "pos": (3, 4), "x": 3, "y": 4}),
    ]
    ctx = make_test_ctx(day=11, hour=2, money=8000, pastures=pastures)
    intents = {"buy_animal": {"COW": 2}, "buy_wheat": 0}

    orders, ledger = builder.reinvest_livestock(ctx, intents)
    cow_orders = [o for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW"]
    assert sum(o[2] for o in cow_orders) == 2
