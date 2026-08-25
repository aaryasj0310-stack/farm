"""Tests for the town demand engine and shop unlock simulator."""
from shop_unlock_simulator import ShopUnlockSimulator
from town_demand_engine import (
    N_DAYS,
    PRODUCTS,
    TOWN_CENTER_DAILY,
    TownDemandEngine,
)

ENGINE = TownDemandEngine()


def test_town_center_only():
    d = ENGINE.compute_daily_demand(2, [])
    for p in PRODUCTS:
        expected = TOWN_CENTER_DAILY.get(p, 0)
        assert d[p] == expected


def test_bakery_unlocks_day3():
    seq = [(3, "BAKERY")]
    day2 = ENGINE.compute_daily_demand(2, seq)
    assert day2["WHEAT"] == 1 and day2["EGG"] == 1  # not yet unlocked
    day3 = ENGINE.compute_daily_demand(3, seq)
    assert day3["WHEAT"] == 7   # 6 shop + 1 town center
    assert day3["EGG"] == 7
    assert day3["CARROT"] == 1  # unaffected


def test_single_product_shops_consume_double():
    pet_cafe = ENGINE.compute_daily_demand(6, [(6, "PET_CAFE")])
    assert pet_cafe["CARROT"] == 13  # 12 + 1 TC
    yarn = ENGINE.compute_daily_demand(9, [(9, "YARN_STORE")])
    assert yarn["WOOL"] == 13        # 12 + 1 TC


def test_farmers_market_demands_four_crops():
    fm = ENGINE.compute_daily_demand(24, [(24, "FARMERS_MARKET")])
    for p in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"):
        assert fm[p] == 7
    assert fm["MELON"] == 1 and fm["EGG"] == 1


def test_multiple_instances_stack():
    seq = [(3, "PET_CAFE"), (6, "PET_CAFE"), (9, "PET_CAFE")]
    d = ENGINE.compute_daily_demand(9, seq)
    assert d["CARROT"] == 37         # 3*12 + 1


def test_cumulative_demand_shape_and_totals():
    seq = [(3, "BAKERY"), (6, "YARN_STORE"), (12, "FARMERS_MARKET")]
    cum = ENGINE.compute_cumulative_demand(seq)
    for p in PRODUCTS:
        assert len(cum[p]) == N_DAYS
        assert all(a <= b for a, b in zip(cum[p], cum[p][1:]))  # monotone
    # verify against manual daily sums
    running = {p: 0 for p in PRODUCTS}
    for day in range(N_DAYS):
        daily = ENGINE.compute_daily_demand(day, seq)
        for p in PRODUCTS:
            running[p] += daily[p]
            assert cum[p][day] == running[p]
    # wheat over 30 days: TC 30 + bakery active days 3-29 (27d)*6 + FM days 12-29 (18d)*6
    assert cum["WHEAT"][-1] == 30 + 27 * 6 + 18 * 6


def test_simulate_season_structure():
    sim = ShopUnlockSimulator()
    seq = sim.simulate_season(seed=7)
    assert len(seq) == 8
    days = [d for d, _ in seq]
    assert days == sim.UNLOCK_DAYS
    for _, shop in seq:
        assert shop in sim.SHOP_TYPES
    # deterministic with seed
    assert sim.simulate_season(seed=7) == seq
