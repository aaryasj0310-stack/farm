"""Marginal revenue, floor-freeze, batch sizing and slippage."""
from marginal_revenue_analyzer import (
    find_optimal_batch_size,
    floor_distance,
    marginal_revenue_series,
    simulate_sale_path,
    slippage_table,
    total_revenue,
)
from price_curve_engine import I0, compute_price


def test_tr_at_equilibrium_hand_check():
    # MELON at exactly I0 quotes $250; first 3 units: 250 + 249.99->250? use exact fn
    q3 = total_revenue("MELON", I0, 3)
    p0 = compute_price("MELON", I0)
    p1 = compute_price("MELON", I0 + 1)
    p2 = compute_price("MELON", I0 + 2)
    assert q3 == p0 + p1 + p2
    assert marginal_revenue_series("MELON", I0, 3) == [p0, p1, p2]


def test_floor_freeze_stops_inventory_growth():
    res = simulate_sale_path("MELON", I0, 500)
    assert res["units_added_to_market"] < 500          # some units froze at $1
    assert res["final_inventory"] == I0 + res["units_added_to_market"]
    assert all(p == 1 for p in res["unit_prices"][-10:])   # tail sells at $1
    assert res["total_revenue"] >= res["units_added_to_market"] * 1


def test_avg_price_decreases_with_size():
    avgs = [simulate_sale_path("STRAWBERRY", I0, q)["avg_realized_price"]
            for q in (1, 5, 10, 20)]
    assert all(a > b for a, b in zip(avgs, avgs[1:]))


def test_optimal_batch_respects_threshold_from_i0():
    res = find_optimal_batch_size("WHEAT", I0, 20)
    # wheat glut quote reads exactly $20 at I0+400 (=T); the log curve plus
    # dollar rounding keeps it >= $20 well past that, so Q* must be >= 400.
    assert compute_price("WHEAT", I0 + 400) == 20
    assert res["optimal_quantity"] >= 400
    q = res["optimal_quantity"]
    assert res["total_revenue"] == sum(compute_price("WHEAT", I0 + k) for k in range(q))
    assert compute_price("WHEAT", I0 + q) < 20          # terminal quote breaks threshold


def test_optimal_batch_threshold_above_spot_is_zero():
    res = find_optimal_batch_size("MELON", I0, 251)   # spot is $250
    assert res["optimal_quantity"] == 0


def test_optimal_batch_accepting_one_dollar_hits_cap():
    res = find_optimal_batch_size("WOOL", I0, 1, max_q=100000)
    assert res["optimal_quantity"] == 100000


def test_slippage_table_shape_and_monotonicity():
    rows = slippage_table("MILK", I0, sizes=(1, 5, 10))
    assert [r["size"] for r in rows] == [1, 5, 10]
    assert rows[0]["slippage_pct"] == 0.0
    assert rows[0]["avg_realized_price"] >= rows[1]["avg_realized_price"] >= rows[2]["avg_realized_price"]


def test_premium_goods_have_small_floor_distance_vs_staples():
    d_melon = floor_distance("MELON")
    d_wheat = floor_distance("WHEAT")
    assert d_melon < 200            # brutal sq curve
    assert d_wheat > 10000          # log curve absorbs enormous oversupply
