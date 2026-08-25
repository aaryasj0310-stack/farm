"""Concurrent interleaved execution, spoilers and TWAP."""
from concurrent_order_simulator import (
    parse_order,
    simulate_concurrent,
    spoiler_attack,
    twap_comparison,
)
from price_curve_engine import I0, MARKET_PARAMS, compute_price


def test_parse_order():
    assert parse_order("sell melon 50") == ("SELL", "MELON", 50)


def test_interleaving_p0_first_each_pair():
    res = simulate_concurrent([["SELL", "MELON", 2]], [["SELL", "MELON", 2]],
                              trace=True)
    seq = [(e["player"], e["inventory_before"]) for e in res["trace"]]
    # each pair adds 2 units total: P0 quotes at even offsets, P1 at odd
    assert seq == [("P0", float(I0)), ("P1", float(I0) + 1),
                   ("P0", float(I0) + 2), ("P1", float(I0) + 3)]


def test_units_match_quantities_and_revenue_positive():
    res = simulate_concurrent([["SELL", "EGG", 30]], [["SELL", "EGG", 10]])
    assert res["p0"]["units"] == 30
    assert res["p1"]["units"] == 10
    assert res["p0"]["revenue"] > 0 and res["p1"]["revenue"] > 0


def test_solo_player_continues_after_other_finishes():
    res = simulate_concurrent([["SELL", "WOOL", 20]], [["SELL", "WOOL", 1]])
    assert res["p0"]["units"] == 20
    assert res["p1"]["units"] == 1


def test_floor_freeze_in_concurrent_execution():
    qty = 3000
    res = simulate_concurrent([[ "SELL", "MELON", qty]], [], trace=True)
    added = res["final_inventories"]["MELON"] - I0
    assert added < qty                      # freeze held some back
    tail = [e for e in res["trace"][-5:]]
    assert all(e["price"] == 1 for e in tail)


def test_expected_revenue_matches_manual_summation():
    qty = 6
    manual = sum(compute_price("MILK", I0 + k) for k in range(qty))
    res = simulate_concurrent([["SELL", "MILK", qty]], [])
    assert res["p0"]["revenue"] == manual


def test_spoiler_reduces_opponent_average():
    atk = spoiler_attack("MELON", opponent_qty=50, my_qty=10)
    assert atk["damage_to_opponent"] > 0
    base_avg = atk["opponent_revenue_alone"] / 50
    spoiled_avg = atk["opponent_revenue_spoiled"] / 50
    assert spoiled_avg < base_avg


def test_twap_beats_dumping_when_town_drains():
    res = twap_comparison("STRAWBERRY", 40, n_slices=4,
                          shops=("ICE_CREAM_SHOP", "SMOOTHIE_SHOP"))
    assert res["drain_per_day"] > 0
    assert res["delta_twap_minus_dump"] > 0
    assert res["recommendation"] == "TWAP"


def test_all_products_executable():
    for prod in MARKET_PARAMS:
        res = simulate_concurrent([["SELL", prod, 5]], [["SELL", prod, 5]])
        assert res["p0"]["units"] == 5 and res["p1"]["units"] == 5
