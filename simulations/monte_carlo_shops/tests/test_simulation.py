"""Tests for the Monte Carlo runner: determinism, shapes, sanity of dynamics."""
import numpy as np

from monte_carlo_runner import BASELINE_PRODUCTION, I0, MonteCarloRunner
from shop_unlock_simulator import ShopUnlockSimulator
from town_demand_engine import PRODUCT_INDEX as P_IDX
from town_demand_engine import PRODUCTS


def _runner(n=200):
    return MonteCarloRunner(n_simulations=n, seed=123)


def test_reproducible_with_same_seed():
    r1 = _runner().run_town_only()
    r2 = MonteCarloRunner(n_simulations=200, seed=123).run_town_only()
    assert np.array_equal(r1.draws, r2.draws)
    assert np.array_equal(r1.prices, r2.prices)


def test_shapes():
    res = _runner().run_town_only()
    n = 200
    assert res.draws.shape == (n, 8)
    assert res.daily_demand.shape == (n, 30, len(PRODUCTS))
    assert res.inventory.shape == (n, 30, len(PRODUCTS))
    assert res.prices.shape == (n, 30, len(PRODUCTS))


def test_prices_floored_at_one():
    res = _runner().run_two_players()  # heaviest glut pressure
    assert int(res.prices.min()) >= 1


def test_town_only_inventory_monotone_decreasing():
    res = _runner().run_town_only()
    diffs = np.diff(res.inventory, axis=1)
    assert (diffs <= 1e-4).all(), "town drain must not increase inventory"


def test_player_production_raises_inventory_vs_town_only():
    a = _runner().run_town_only()
    b = _runner().run_single_player()
    assert (b.inventory[:, -1, :] > a.inventory[:, -1, :] + 10).any()


def test_production_pushes_prices_down_at_median():
    a = _runner(n=400).run_town_only()
    b = _runner(n=400).run_single_player()
    i = P_IDX["WHEAT"]
    med_a = np.median(a.prices[:, 29, i])
    med_b = np.median(b.prices[:, 29, i])
    assert med_b <= med_a


def test_batch_draws_approx_uniform():
    rng = np.random.default_rng(0)
    draws = ShopUnlockSimulator().simulate_batch_indices(rng, 40000)
    freq = np.bincount(draws.ravel(), minlength=8) / draws.size
    assert np.all(np.abs(freq - 0.125) < 0.01)


def test_baseline_has_no_fertilizer_production():
    assert BASELINE_PRODUCTION.get("FERTILIZER", 0) == 0


def test_inventory_starting_point_matches_i0_minus_first_day_drain():
    res = _runner(n=50).run_town_only()
    # day 0: no shops yet -> exactly TC drain of 1/product
    expected = I0 - 1.0
    assert np.allclose(res.inventory[:, 0, :-1], expected)   # all but fertilizer
    assert np.allclose(res.inventory[:, 0, -1], float(I0))   # fertilizer untouched
