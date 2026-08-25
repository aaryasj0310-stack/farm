"""Ground-truth price validation + inverse solver + elasticity."""
import math

import numpy as np
import pytest

from price_curve_engine import (
    I0,
    KNOWN_PRICE_POINTS,
    MARKET_PARAMS,
    compute_price,
    compute_price_vectorized,
    inventory_at_price,
    price_elasticity,
    shape_fn,
)


def test_ten_ground_truth_price_points():
    for product, inv, expected in KNOWN_PRICE_POINTS:
        assert compute_price(product, inv) == expected, (product, inv)


def test_rules_table_reference_points():
    # P(I0+T), P(I0+2T) columns from the rules table
    assert compute_price("WHEAT", 10800) == 19
    assert compute_price("CARROT", 10450) == 10
    assert compute_price("CARROT", 10900) == 1
    assert compute_price("TOMATO", 10200) == 24
    assert compute_price("TOMATO", 10400) == 9
    assert compute_price("MELON", 10300) == 1
    assert compute_price("EGG", 10332) == 40
    assert compute_price("FERTILIZER", 10200) == 60


def test_shape_function_edges():
    assert shape_fn("hinge", 0, T=100) == 0.0
    assert shape_fn("hinge", 100, T=100) == 1.0
    assert math.isclose(shape_fn("log", 0), 0.0)
    assert math.isclose(shape_fn("sqrt", 400), 20.0)


def test_vectorized_matches_scalar():
    sweep = np.arange(8000, 12001, 97)
    for prod in MARKET_PARAMS:
        scalar = [compute_price(prod, i) for i in sweep]
        vec = compute_price_vectorized(prod, sweep).tolist()
        assert scalar == vec, prod


@pytest.mark.parametrize("prod", list(MARKET_PARAMS.keys()))
def test_inverse_solver_round_trip(prod):
    base = MARKET_PARAMS[prod]["base"]
    targets = [base * f for f in (0.05, 0.25, 0.5, 0.75, 1.5, 2.0, 3.0)]
    targets += [base - 3, base + 7]
    for target in targets:
        inv = inventory_at_price(prod, round(target))
        for branch, level in inv.items():
            if level is None or not (1 <= round(target)):
                continue
            # integer-quantizing the inventory perturbs the price by up to
            # |dP/dinv| dollars; allow exactly that much slack.
            tol = max(1, math.ceil(abs(price_elasticity(prod, level))))
            got = compute_price(prod, int(round(level)))
            assert abs(got - round(max(target, 1))) <= tol, (prod, branch, target, got, level)


def test_inverse_branch_selection():
    inv = inventory_at_price("WHEAT", 45)
    assert inv["scarcity"] is not None and inv["glut"] is None      # 45 > base 25
    assert math.isclose(inv["scarcity"], 9600, abs_tol=1e-6)
    inv = inventory_at_price("WHEAT", 20)
    assert inv["glut"] is not None and inv["scarcity"] is None
    assert math.isclose(inv["glut"], 10400, abs_tol=1e-6)
    inv = inventory_at_price("WOOL", 240)
    assert math.isclose(inv["scarcity"], 10000 - 105, abs_tol=1e-6)  # hinge-free: log at T


def test_hinge_inverse_continuity_at_knee():
    # carrot below knee y=1 must give x=T exactly
    inv = inventory_at_price("CARROT", 70)
    assert math.isclose(inv["scarcity"], 9550, abs_tol=1e-6)


def test_elasticity_negative_and_finite_away_from_i0():
    for prod in MARKET_PARAMS:
        e_above = price_elasticity(prod, I0 + 10)
        e_below = price_elasticity(prod, I0 - 10)
        assert e_above <= 0 and e_below < 0, prod
        assert math.isfinite(e_above)
    # strawberry scarcity side is sqrt: slope at 1 unit below equilibrium is steep
    # amp_b = 0.70*120/sqrt(100) = 8.4; f'(1) = 0.5 -> -4.2 $/unit
    assert price_elasticity("STRAWBERRY", I0 - 1) == pytest.approx(-4.2)


def test_floor_is_one_everywhere():
    # premium goods crash to the floor within tens of units
    for prod in ("STRAWBERRY", "MELON", "MILK", "WOOL"):
        assert compute_price(prod, I0 + 500000) == 1
    # log-glut staples are unbounded and flat: even 10M units barely dents wheat
    assert compute_price("WHEAT", I0 + 10_000_000) > 1
    # analytic floor distances exist but are astronomic (~e^(base-delta)/amp)
    # and the function self-verifies them for every product
    from marginal_revenue_analyzer import floor_distance
    from price_curve_engine import inventory_at_price
    assert floor_distance("MELON") < 500
    wheat_dist = inventory_at_price("WHEAT", 1)["glut"] - I0
    assert wheat_dist > 10**12          # trillions of units -> never in practice
