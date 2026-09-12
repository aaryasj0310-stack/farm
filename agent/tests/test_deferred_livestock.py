"""Regression test suite for deferred livestock reinvestment (Section 13 Cases A-G)."""
import pytest
from config import C4_LIVESTOCK_CUTOFF_DAY, ANIMALS
from market.order_builder import OrderBuilder
from test_macro_planner import make_ctx


def make_deferred_ctx(day=11, hour=2, money=8000, unlocked=("NW", "NE"),
                      pastures=None, shed=None, inventories=None):
    if pastures is None:
        pastures = [(2, 4, {"kind": "PASTURE"}), (3, 4, {"kind": "PASTURE"})]
    if shed is None:
        shed = {"WHEAT": 30}
    ctx = make_ctx(day=day, money=money, unlocked=unlocked, shed=shed, structures=pastures)
    ctx["hour"] = hour
    if inventories:
        ctx["private"].inventories = inventories
    return ctx


def test_case_a_hour0_drop_recovers_in_daytime():
    """Test A: Animal order crowded out at Hour 0 can be purchased during Hours 2-18."""
    builder = OrderBuilder()
    
    ctx_h0 = make_deferred_ctx(day=11, hour=0, money=8000)
    intents_h0 = {
        "hire": 10,
        "buy_seed": {"MELON": 5},
        "buy_animal": {"SHEEP": 2},
    }
    orders_h0, ledger_h0 = builder.build(ctx_h0, intents_h0, max_slots=10)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders_h0)
    assert any(d.get("kind") == "animal_slots" for d in ledger_h0["dropped"])
    
    ctx_h2 = make_deferred_ctx(day=11, hour=2, money=7000)
    intents_h2 = {
        "buy_animal": {"SHEEP": 2},
        "buy_wheat": 0,
        "pending_structures": {},
    }
    orders_h2, ledger_h2 = builder.reinvest_livestock(ctx_h2, intents_h2, max_slots=10)
    assert ["BUY_ANIMAL", "SHEEP", 2] in orders_h2
    assert not ledger_h2.get("dropped")


def test_case_b_reinvestment_respects_cutoff():
    """Test B: Day 11 allowed, Day 12 blocked under C4 policy."""
    builder = OrderBuilder()
    intents = {"buy_animal": {"COW": 1}}
    
    ctx_d11 = make_deferred_ctx(day=11, hour=5)
    orders_d11, _ = builder.reinvest_livestock(ctx_d11, intents)
    assert any(o[0] == "BUY_ANIMAL" for o in orders_d11)
    
    ctx_d12 = make_deferred_ctx(day=C4_LIVESTOCK_CUTOFF_DAY, hour=5)
    orders_d12, _ = builder.reinvest_livestock(ctx_d12, intents)
    assert orders_d12 == []


def test_case_c_sees_newly_built_empty_pastures():
    """Test C: Reinvestment sees newly built empty pastures on NW/NE."""
    builder = OrderBuilder()
    pastures = [
        (2, 4, {"kind": "PASTURE"}),
        (3, 4, {"kind": "PASTURE"}),
        (5, 3, {"kind": "PASTURE"}),
    ]
    ctx = make_deferred_ctx(day=11, hour=6, pastures=pastures, unlocked=("NW", "NE"))
    intents = {"buy_animal": {"SHEEP": 3}}
    orders, _ = builder.reinvest_livestock(ctx, intents)
    assert ["BUY_ANIMAL", "SHEEP", 3] in orders


def test_case_d_feed_cap_remains_binding():
    """Test D: Feed cap remains binding — MacroPlanner clamps buy_animal to sustainable herd."""
    from strategy.macro_planner import MacroPlanner
    from test_macro_planner import make_forecast, BASE_PRICES
    fc = make_forecast(BASE_PRICES)
    planner = MacroPlanner(fc)
    ctx = make_deferred_ctx(day=11, hour=2, money=9000, shed={"WHEAT": 0})
    plan = planner.build(ctx)
    requested = sum(plan.intents.get("buy_animal", {}).values())
    assert requested <= plan.diagnostics.get("feed_risk", {}).get("sustainable_herd_size", 20)


def test_case_e_cash_remains_binding():
    """Test E: Animal purchases cannot violate treasury reserves."""
    builder = OrderBuilder(money_reserve=200)
    ctx = make_deferred_ctx(day=11, hour=3, money=450)
    intents = {"buy_animal": {"COW": 1}}
    orders, ledger = builder.reinvest_livestock(ctx, intents)
    assert orders == []
    assert any(d.get("reason") == "budget" for d in ledger["dropped"])


def test_case_f_critical_morning_commitments_protected():
    """Test F: Hour 0 Hires, Seeds, and Wheat always precede animals."""
    builder = OrderBuilder()
    ctx = make_deferred_ctx(day=11, hour=0, money=4000)
    intents = {
        "hire": 8,
        "buy_wheat": 10,
        "buy_seed": {"WHEAT": 10},
        "buy_animal": {"COW": 2},
    }
    orders, _ = builder.build(ctx, intents, max_slots=10)
    hire_indices = [i for i, o in enumerate(orders) if o[0] == "HIRE"]
    wheat_indices = [i for i, o in enumerate(orders) if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"]
    animal_indices = [i for i, o in enumerate(orders) if o[0] == "BUY_ANIMAL"]
    
    assert hire_indices, "Hires must be present"
    assert wheat_indices, "Survival wheat must be present"
    for h in hire_indices:
        for a in animal_indices:
            assert h < a, "Hire must precede Buy Animal"


def test_case_g_no_duplicate_animal_purchases_when_in_transit():
    """Test G: Recomputed intents and builder account for animals already in shed or inventory."""
    builder = OrderBuilder()
    pastures = [(2, 4, {"kind": "PASTURE"}), (3, 4, {"kind": "PASTURE"})]
    ctx = make_deferred_ctx(day=11, hour=5, pastures=pastures, shed={"WHEAT": 30, "COW": 1})
    intents = {"buy_animal": {"COW": 2}}
    orders, ledger = builder.reinvest_livestock(ctx, intents)
    cow_orders = [o for o in orders if o[0] == "BUY_ANIMAL" and o[1] == "COW"]
    assert sum(o[2] for o in cow_orders) == 1
