"""Validate the exact price function against the known price-point table."""
from price_function import (
    KNOWN_PRICE_POINTS,
    MARKET_PARAMS,
    compute_price,
    compute_price_vectorized,
    shape_fn,
    validate_known_points,
)


def test_known_price_points():
    ok, _ = validate_known_points(verbose=False)
    assert ok


def test_each_known_point_individually():
    for resource, inv, expected in KNOWN_PRICE_POINTS:
        assert compute_price(resource, inv) == expected, (resource, inv, expected, compute_price(resource, inv))


def test_shape_functions():
    assert shape_fn("linear", 5.0) == 5.0
    assert shape_fn("sq", 3.0) == 9.0
    assert shape_fn("sqrt", 400.0) == 20.0
    assert shape_fn("log", 0) == 0.0            # f(0) = 0
    assert shape_fn("log10", 0) == 0.0
    assert abs(shape_fn("log", math_e := 2.718281828459045 - 1) - 1.0) < 1e-9
    # hinge: f(0)=0, f(T)=1 by construction, quadratic explosion above knee
    assert shape_fn("hinge", 0, T=100) == 0.0
    assert shape_fn("hinge", 100, T=100) == 1.0
    assert abs(shape_fn("hinge", 200, T=100) - 10.0) < 1e-9   # u=2 -> 2 + 8*1


def test_floor_at_one_dollar():
    assert compute_price("STRAWBERRY", 10100) == 1
    assert compute_price("MELON", 10300) == 1
    assert compute_price("MILK", 10122) == 1
    assert compute_price("MELON", 20000) >= 1


def test_base_price_at_i0():
    for resource, p in MARKET_PARAMS.items():
        assert compute_price(resource, p["I0"]) == p["base"]


def test_scarcity_monotone_and_glut_monotone():
    # The full curve is monotonically NON-INCREASING in inventory:
    # falling toward base from the scarcity side, then below it on the glut side.
    wheat = [compute_price("WHEAT", i) for i in range(8000, 12001, 250)]
    assert all(a >= b for a, b in zip(wheat, wheat[1:])), "price must never rise with inventory"
    assert wheat[len(wheat) // 2] == 25  # exactly at I0 -> base


def test_vectorized_matches_scalar():
    sweep = list(range(8000, 12001, 111))
    for resource in MARKET_PARAMS:
        scalar = [compute_price(resource, i) for i in sweep]
        vector = compute_price_vectorized(resource, np_array(sweep)).tolist()
        assert scalar == vector, resource


def np_array(xs):
    import numpy as np
    return np.array(xs)
