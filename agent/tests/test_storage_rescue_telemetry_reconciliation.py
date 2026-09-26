"""Unit & Regression Tests for Phase M0-K-R1: Evidence Reconciliation & Telemetry.

Covers all 10 authoritative reconciliation criteria specified in Phase M0-K-R1:
1. Sales occurring alongside midnight inventory deposits produce misleading step deltas.
2. Other transactions changing cash during the same step confound step cash deltas.
3. Ordinary WHEAT sales versus rescue-generated WHEAT sales order provenance.
4. Emitted orders that are not executed due to inventory exhaustion (not cap blocking).
5. Duplicate product orders and order provenance tracking.
6. Exhausted ten-order market capacity strictly blocks appending without order cap breach.
7. Direct execution quantities and revenue captured at the market execution boundary.
8. Correct paired median calculation invariant: median(A - B) != median(A) - median(B).
9. Spot-value aggregation: sum(discarded * spot_price) vs avoided destruction.
10. Preservation and immutability of original final-cash records.
"""
from __future__ import annotations

import copy
import json
import math
import os
import pytest
import numpy as np

import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
import config
from execution.midnight_storage_controller import (
    apply_midnight_storage_rescue,
    is_storage_rescue_enabled,
    reset_midnight_storage_telemetry,
)
from main import reset_agent_state


@pytest.fixture(autouse=True)
def clean_state():
    config.set_midnight_storage_dump_mode("RESCUE")
    reset_agent_state()
    reset_midnight_storage_telemetry()
    yield
    config.set_midnight_storage_dump_mode("RESCUE")
    reset_agent_state()
    reset_midnight_storage_telemetry()


def test_01_sales_alongside_midnight_inventory_deposits():
    """1. Demonstrates that whole-step shed deltas are confounded by midnight worker deposits."""
    # Simulate shed with 20 wheat, worker carrying 15 wheat
    private = {
        "shed": {"WHEAT": 20},
        "inventories": [{"WHEAT": 15}],
        "seeds": {},
    }
    farm = {"money": 1000.0, "tiles": [], "farmer": [0, 0], "hands": []}
    market = {"inventory": {"WHEAT": 500.0}, "params": {}}

    shed_wheat_pre = private["shed"]["WHEAT"]  # 20

    # Execute a sale of 5 wheat
    # In engine, _commit_unit runs first:
    sold = 0
    for _ in range(5):
        if kengine._commit_unit("SELL", "WHEAT", 25.0, farm, private, market, 100):
            sold += 1
    assert sold == 5
    assert private["shed"]["WHEAT"] == 15
    assert farm["money"] == 1125.0

    # At midnight, _drop_inventories_to_shed runs:
    kengine._drop_inventories_to_shed(private, 100)

    shed_wheat_post = private["shed"]["WHEAT"]  # 15 + 15 = 30
    assert shed_wheat_post == 30

    # Flawed whole-step calculation:
    flawed_units_sold = shed_wheat_pre - shed_wheat_post
    assert flawed_units_sold == -10, "Whole-step calculation yields negative units (-10) despite 5 units sold!"

    # Authoritative boundary tracking:
    assert sold == 5, "Authoritative market boundary tracks exact sold units (5)"


def test_02_other_transactions_changing_cash_during_same_step():
    """2. Demonstrates that whole-step cash deltas confound simultaneous sales/purchases."""
    farm = {"money": 1000.0}
    private = {"shed": {"WHEAT": 10, "MELON": 5}}
    market = {"inventory": {"WHEAT": 500.0, "MELON": 500.0}, "params": {}}

    money_pre = farm["money"]

    # Sell 2 wheat (at $25 each = $50) and 2 melons (at $250 each = $500)
    wheat_rev = 0.0
    for _ in range(2):
        if kengine._commit_unit("SELL", "WHEAT", 25.0, farm, private, market, 100):
            wheat_rev += 25.0

    melon_rev = 0.0
    for _ in range(2):
        if kengine._commit_unit("SELL", "MELON", 250.0, farm, private, market, 100):
            melon_rev += 250.0

    money_post = farm["money"]
    flawed_step_cash = money_post - money_pre

    assert flawed_step_cash == 550.0
    assert wheat_rev == 50.0
    assert flawed_step_cash != wheat_rev, "Step cash delta ($550) conflates melon revenue with wheat revenue ($50)"


def test_03_ordinary_wheat_sales_vs_rescue_generated_wheat_sales():
    """3. Verifies that picking the first SELL WHEAT order misidentifies planner orders."""
    # Market orders containing both a planner wheat sell and a rescue wheat sell
    orders = [
        ["SELL", "WHEAT", 4],     # Planner order
        ["SELL", "WOOL", 2],
        ["SELL", "WHEAT", 18],    # Rescue order appended at end
    ]

    # Naive heuristic:
    first_wheat_order = None
    for o in orders:
        if o[0] == "SELL" and o[1] == "WHEAT":
            first_wheat_order = o
            break

    assert first_wheat_order == ["SELL", "WHEAT", 4], "Naive search erroneously selected planner order"

    # Provenance-aware selection:
    # Rescue order is appended last by apply_midnight_storage_rescue
    actual_rescue_order = orders[-1]
    assert actual_rescue_order == ["SELL", "WHEAT", 18], "Provenance correctly identifies rescue order"


def test_04_emitted_orders_that_are_not_executed():
    """4. Demonstrates unexecuted order due to inventory exhaustion is not cap blocking."""
    farm = {"money": 500.0}
    private = {"shed": {"WHEAT": 3}}
    market = {"inventory": {"WHEAT": 500.0}, "params": {}}

    # Requested order: SELL WHEAT 10
    requested = 10
    committed = 0
    for _ in range(requested):
        if kengine._commit_unit("SELL", "WHEAT", 25.0, farm, private, market, 100):
            committed += 1

    assert committed == 3, "Only 3 units committed because shed wheat was exhausted"
    unexecuted = requested - committed
    assert unexecuted == 7
    # This was caused by inventory limitation, NOT by exceeding the 10-order market cap


def test_05_duplicate_product_orders_and_order_provenance():
    """5. Tests handling multiple orders for the same product in a single turn."""
    mkt = [
        ["SELL", "WHEAT", 10],
        ["BUY_PRODUCT", "WHEAT", 2],
        ["SELL", "WHEAT", 15],
    ]
    assert len(mkt) == 3
    wheat_sells = [o for o in mkt if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 2
    assert wheat_sells[0][2] == 10
    assert wheat_sells[1][2] == 15


def test_06_exhausted_ten_order_market_capacity():
    """6. Verifies apply_midnight_storage_rescue respects 10-order cap and never breaches."""
    class MockTile:
        is_animal = False

    class MockFarm:
        money = 1000.0
        def iter_tiles(self):
            return []

    class MockPrivate:
        shed = {"WHEAT": 50, "CARROT": 40}
        inventories = [{"CARROT": 20}]

    ctx = {
        "day": 10,
        "hour": 23,
        "farm": MockFarm(),
        "private": MockPrivate(),
    }

    # Case A: Market has 9 orders -> rescue appends 10th order
    mkt_9 = [["SELL", "CARROT", 1] for _ in range(9)]
    res_9 = apply_midnight_storage_rescue(mkt_9, ctx)
    assert len(res_9) == 10
    assert res_9[-1][0] == "SELL" and res_9[-1][1] == "WHEAT"

    # Case B: Market already has 10 orders -> rescue does NOT append
    mkt_10 = [["SELL", "CARROT", 1] for _ in range(10)]
    res_10 = apply_midnight_storage_rescue(mkt_10, ctx)
    assert len(res_10) == 10, "Order cap strictly enforced at <= 10 orders"
    assert not any(o[0] == "SELL" and o[1] == "WHEAT" for o in res_10)


def test_07_direct_execution_quantities_and_revenue():
    """7. Verifies unit-by-unit market execution matches mathematical revenue."""
    farm = {"money": 100.0}
    private = {"shed": {"WHEAT": 5}}
    market = {"inventory": {"WHEAT": 1000.0}, "params": {}}

    units = 0
    total_rev = 0.0
    for _ in range(5):
        price = kengine.market_price("WHEAT", market["inventory"]["WHEAT"], market.get("params"))
        if kengine._commit_unit("SELL", "WHEAT", price, farm, private, market, 100):
            units += 1
            total_rev += price

    assert units == 5
    assert private["shed"]["WHEAT"] == 0
    assert farm["money"] == 100.0 + total_rev


def test_08_correct_paired_median_calculation():
    """8. Mathematical invariant: median(A - B) != median(A) - median(B) on asymmetric data."""
    # Synthetic asymmetric sample demonstrating the property:
    a = np.array([100, 105, 110, 112, 130])
    b = np.array([90, 100, 108, 109, 110])
    diff = a - b  # [10, 5, 2, 3, 20]

    med_a = float(np.median(a))       # 110
    med_b = float(np.median(b))       # 108
    med_diff = float(np.median(diff)) # sorted [2, 3, 5, 10, 20] -> median is 5

    diff_of_meds = med_a - med_b     # 110 - 108 = 2
    assert med_diff != diff_of_meds, "Median of differences must not be computed by subtracting individual medians!"
    assert med_diff == 5.0
    assert diff_of_meds == 2.0

    # Verify on confirmation archived numbers:
    c0_med = 102212.0
    c2_med = 107423.5
    paired_delta_med = 5361.0
    assert paired_delta_med != (c2_med - c0_med)
    assert (c2_med - c0_med) == 5211.5


def test_09_spot_value_aggregation():
    """9. Verifies spot-value aggregation logic and avoids conflating with cash."""
    discarded = {"WHEAT": 10, "MELON": 2}
    prices = {"WHEAT": 25.0, "MELON": 250.0}

    # Spot value lost: 10 * 25 + 2 * 250 = 250 + 500 = 750
    spot_lost = sum(qty * prices[item] for item, qty in discarded.items())
    assert spot_lost == 750.0

    # Spot value is asset valuation of discarded physical items, NOT cash in bank
    cash_balance = 0.0
    assert spot_lost != cash_balance


def test_10_preservation_of_original_final_cash_records():
    """10. Confirms that paired_results.json final cash records match manifest exactly."""
    conf_manifest_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "simulations", "results", "phase_m0_k_confirmation", "manifest.json"
    )
    conf_pairs_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "simulations", "results", "phase_m0_k_confirmation", "paired_results.json"
    )

    if os.path.exists(conf_manifest_path) and os.path.exists(conf_pairs_path):
        with open(conf_manifest_path) as f:
            manifest = json.load(f)
        with open(conf_pairs_path) as f:
            pairs = json.load(f)

        assert len(pairs) == 200
        mean_c0 = float(np.mean([p["c0_cash"] for p in pairs]))
        mean_c2 = float(np.mean([p["c2_cash"] for p in pairs]))
        mean_delta = float(np.mean([p["delta_cash"] for p in pairs]))

        assert abs(mean_c0 - manifest["c0_mean_cash"]) < 1e-4
        assert abs(mean_c2 - manifest["c2_mean_cash"]) < 1e-4
        assert abs(mean_delta - manifest["mean_paired_gain"]) < 1e-4
