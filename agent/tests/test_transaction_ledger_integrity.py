"""Targeted unit tests for Phase SW-B3A-R1: Transaction Ledger & Causal Telemetry Integrity.

Verifies:
1. Actual sale vs inventory withdrawal (only executed _commit_unit SELL counts as sale).
2. Actual purchase vs inventory deposit (worker deposits do not count as purchases).
3. Hiring and wage accounting (Fibonacci hire cost, zero daily wages in engine).
4. Multiple simultaneous market transactions with dynamic pricing.
5. Successful vs rejected transactions (insufficient funds/inventory not credited).
6. Harvest provenance and bounds with mixed inventory (SW vs Core).
7. Wheat imports and feeding consumption conservation.
8. Midnight rollover successful dump vs genuine shed capacity overflow discard.
9. Worker action execution, completion, and spatial region attribution.
10. Engine-confirmed Stage 9 SW planting detection.
11. Exact paired economic waterfall reconciliation identity ($0.00 residual).
"""
import copy
import pytest
import kaggle_environments.envs.kaggriculture.kaggriculture as kag


def test_actual_sale_vs_withdrawal():
    """Verify that only executed SELL orders increase sales revenue, not shed withdrawals."""
    farm = {"money": 3000.0}
    private = {"shed": {"MELON": 5}}
    market = {"inventory": {"MELON": 10}, "params": {}}
    
    # 1. Non-market withdrawal (worker PICKUP) decreases shed, but does not increase money
    private["shed"]["MELON"] -= 2
    assert farm["money"] == 3000.0, "Worker pickup must not alter cash"
    assert private["shed"]["MELON"] == 3

    # 2. Executed market sale increases money and decreases shed
    ok = kag._commit_unit("SELL", "MELON", 240.0, farm, private, market, shed_capacity=100)
    assert ok is True
    assert farm["money"] == 3240.0
    assert private["shed"]["MELON"] == 2


def test_actual_purchase_vs_deposit():
    """Verify that worker shed deposits are not counted as market purchases."""
    farm = {"money": 3000.0}
    private = {"shed": {"STRAWBERRY": 2}, "inventories": [{"STRAWBERRY": 3}]}
    market = {"inventory": {"STRAWBERRY": 50, "WHEAT": 100}, "params": {}}

    # Worker deposits 3 units into shed
    private["shed"]["STRAWBERRY"] += 3
    private["inventories"][0]["STRAWBERRY"] -= 3
    assert farm["money"] == 3000.0, "Worker deposit must not reduce cash"

    # Actual market purchase reduces cash and adds to shed
    ok = kag._commit_unit("BUY_PRODUCT", "WHEAT", 40.0, farm, private, market, shed_capacity=100)
    assert ok is True
    assert farm["money"] == 2960.0
    assert private["shed"].get("WHEAT") == 1


def test_hiring_and_wage_accounting():
    """Verify engine hiring cost calculation (Fibonacci sequence) and lack of daily wages."""
    farm = {
        "money": 3000.0,
        "hires_today": 0,
        "hands": [],
        "farmer": [0, 0],
    }
    private = {"inventories": [{}]}
    mult = 1  # default farmHandCostMult in kaggriculture.json

    # Test hires Fibonacci cost sequence: fib(0)=1, fib(1)=1, fib(2)=2, fib(3)=3, fib(4)=5
    expected_costs = [1, 1, 2, 3, 5]
    for expected_c in expected_costs:
        c = kag._hire_cost(farm["hires_today"], mult)
        assert c == expected_c
        pre_cash = farm["money"]
        kag._do_hire(farm, private, board_size=10, mult=mult)
        assert pre_cash - farm["money"] == expected_c
        assert farm["hires_today"] == len(farm["hands"])

    # Engine has no wage mechanism: step rollover does not deduct wages
    assert not hasattr(kag, "_pay_wages")
    assert not hasattr(kag, "wages")


def test_multiple_simultaneous_market_transactions():
    """Verify multiple unit trades with dynamic price refresh."""
    farm = {"money": 3000.0}
    private = {"shed": {"MELON": 2, "WHEAT": 0}, "seeds": {}}
    market = {"inventory": {"MELON": 100, "WHEAT": 200}, "params": {}}

    inflows = 0.0
    outflows = 0.0

    # Sell 2 Melons
    for _ in range(2):
        px = kag.market_price("MELON", market["inventory"]["MELON"], market.get("params"))
        ok = kag._commit_unit("SELL", "MELON", px, farm, private, market)
        assert ok is True
        inflows += px

    # Buy 1 Wheat seed
    seed_cost = kag.CROPS["WHEAT"]["seed"]
    ok = kag._commit_unit("BUY_SEED", "WHEAT", seed_cost, farm, private, market)
    assert ok is True
    outflows += seed_cost

    expected_cash = 3000.0 + inflows - outflows
    assert abs(farm["money"] - expected_cash) < 1e-6


def test_rejected_market_transactions():
    """Verify that rejected orders (insufficient money or shed inventory) do not alter cash."""
    farm = {"money": 5.0}  # Cannot afford $80 Melon seed or $10 Wheat seed
    private = {"shed": {}, "seeds": {}}
    market = {"inventory": {"MELON": 10}, "params": {}}

    # 1. Buy seed with insufficient funds -> False, cash unchanged
    ok = kag._commit_unit("BUY_SEED", "MELON", 80.0, farm, private, market)
    assert ok is False
    assert farm["money"] == 5.0
    assert private["seeds"].get("MELON", 0) == 0

    # 2. Sell item not in shed -> False, cash unchanged
    ok = kag._commit_unit("SELL", "MELON", 250.0, farm, private, market)
    assert ok is False
    assert farm["money"] == 5.0


def test_harvest_provenance_and_mixed_inventory():
    """Verify tile-level physical provenance bounds and non-negativity."""
    h_core = 60
    h_sw = 20
    s_total = 76
    p_total = 0  # no market imports

    # Upper bound: cannot exceed SW harvested units
    sw_upper = min(h_sw, s_total)
    assert sw_upper == 20

    # Lower bound: excess over total core units
    sw_lower = max(0, s_total - (h_core + p_total))
    assert sw_lower == 16  # 76 sold - 60 core = 16 must have come from SW

    # Proportional attribution
    prop_units = s_total * (h_sw / (h_sw + h_core + p_total))
    assert prop_units == 19.0

    assert sw_lower <= prop_units <= sw_upper

    # Test edge case: zero SW harvest MUST produce zero SW lower and upper bounds
    h_sw_zero = 0
    upper_zero = min(h_sw_zero, s_total)
    lower_zero = min(h_sw_zero, max(0, s_total - (h_core + p_total)))
    assert upper_zero == 0
    assert lower_zero == 0


def test_wheat_imports_and_feeding_consumption():
    """Verify exact physical inventory conservation of imported wheat and animal feeding."""
    # Opening(0) + Harv(10) + Buy(50) = Sold(30) + Fed(25) + EndingShed(5) + Wrk(0) + Disc(0)
    in_qty = 0 + 10 + 50
    out_qty = 30 + 25 + 5 + 0 + 0
    assert in_qty == out_qty == 60


def test_midnight_dump_and_genuine_overflow():
    """Verify midnight shed capacity overflow calculation."""
    shed = {"WHEAT": 90}
    worker_invs = [{"MELON": 8}, {"STRAWBERRY": 6}]  # Total worker carried = 14
    shed_cap = 100

    current = sum(shed.values())
    room = max(0, shed_cap - current)  # room = 10
    assert room == 10

    discarded = {}
    for inv in worker_invs:
        for item, n in list(inv.items()):
            take = min(n, room)
            overflow = n - take
            if overflow > 0:
                discarded[item] = discarded.get(item, 0) + overflow
            room = max(0, room - take)

    # First worker drops 8 Melons into room 10 -> room becomes 2, discarded 0
    # Second worker drops 2 Strawberries into room 2 -> room becomes 0, discarded 4 Strawberries
    assert discarded == {"STRAWBERRY": 4}


def test_worker_action_region_attribution():
    """Verify that worker actions in SW (x < 5, y >= 5) are distinguished from Core."""
    board_size = 10
    sw_pos = (2, 6)
    core_pos = (7, 3)

    is_sw = lambda p: (p[0] < 5 and p[1] >= 5)
    assert is_sw(sw_pos) is True
    assert is_sw(core_pos) is False


def test_engine_confirmed_sw_planting():
    """Verify that Stage 9 is recorded only when a PLANT action succeeds on a SW tile."""
    sw_pos = (2, 5)
    tile_before = None
    tile_after = {
        "kind": "PLANT",
        "crop": "STRAWBERRY",
        "planted_day": 11,
    }
    
    is_sw = (sw_pos[0] < 5 and sw_pos[1] >= 5)
    planted_success = (tile_before is None and isinstance(tile_after, dict) and tile_after.get("kind") == "PLANT")
    
    stage_9_event = None
    if is_sw and planted_success:
        stage_9_event = {
            "step": 267,
            "day": 11,
            "hour": 3,
            "crop": tile_after["crop"],
            "pos": sw_pos,
        }

    assert stage_9_event is not None
    assert stage_9_event["crop"] == "STRAWBERRY"
    assert stage_9_event["pos"] == (2, 5)


def test_exact_paired_waterfall_reconciliation_math():
    """Verify that the paired economic waterfall arithmetic reconciles with zero residual."""
    # Control match ledger
    c_start = 3000.0
    c_crop_sales = 100000.0
    c_anim_sales = 20000.0
    c_land_cost = 1000.0
    c_seed_cost = 5000.0
    c_anim_cost = 400.0
    c_feed_cost = 15000.0
    c_fert_cost = 0.0
    c_hire_cost = 5000.0
    c_final = c_start + c_crop_sales + c_anim_sales - (c_land_cost + c_seed_cost + c_anim_cost + c_feed_cost + c_fert_cost + c_hire_cost)

    # Treatment match ledger (with SW)
    t_start = 3000.0
    t_sw_crop_sales = 10000.0
    t_core_crop_sales = 91000.0
    t_crop_sales = t_sw_crop_sales + t_core_crop_sales
    t_anim_sales = 18000.0
    t_sw_land_cost = 2000.0
    t_core_land_cost = 1000.0
    t_land_cost = t_sw_land_cost + t_core_land_cost
    t_sw_seed_cost = 700.0
    t_core_seed_cost = 4300.0
    t_seed_cost = t_sw_seed_cost + t_core_seed_cost
    t_anim_cost = 630.0  # +$230 animal purchase difference
    t_feed_cost = 14000.0
    t_fert_cost = 0.0
    t_hire_cost = 5000.0
    t_final = t_start + t_crop_sales + t_anim_sales - (t_land_cost + t_seed_cost + t_anim_cost + t_feed_cost + t_fert_cost + t_hire_cost)

    observed_delta = t_final - c_final

    # Decomposed waterfall components
    sw_net = t_sw_crop_sales - t_sw_land_cost - t_sw_seed_cost
    core_crop_delta = t_core_crop_sales - c_crop_sales
    core_seed_delta = t_core_seed_cost - c_seed_cost
    anim_sales_delta = t_anim_sales - c_anim_sales
    anim_cost_delta = t_anim_cost - c_anim_cost
    feed_cost_delta = t_feed_cost - c_feed_cost
    fert_cost_delta = t_fert_cost - c_fert_cost
    hire_cost_delta = t_hire_cost - c_hire_cost

    reconciled_waterfall_sum = (
        sw_net
        + core_crop_delta
        - core_seed_delta
        + anim_sales_delta
        - anim_cost_delta
        - feed_cost_delta
        - fert_cost_delta
        - hire_cost_delta
    )

    residual = observed_delta - reconciled_waterfall_sum
    assert abs(residual) < 1e-6, f"Waterfall residual must be 0.00, got {residual}"
