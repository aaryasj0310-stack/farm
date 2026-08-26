"""Module 4: Vectorized Monte Carlo simulation engine.

For each simulation:
  1. Draw the 8 shop unlocks (uniform, with replacement).
  2. Per day 0..29: compute town demand, drain market inventory, optionally
     add player production (sold into the market), record prices.

Scenario B/C baseline player production follows the task brief; all ROI /
revenue economics use the real game rules from `new rules.md` (seed costs,
yield/tile/day, growth times, animal feed).

Performance: fully numpy-vectorized over simulations. 10k sims run in ~1s.
"""
from dataclasses import dataclass, field

import numpy as np

from price_function import MARKET_PARAMS, compute_price_vectorized
from shop_unlock_simulator import ShopUnlockSimulator
from town_demand_engine import (
    N_DAYS,
    PRODUCTS,
    SHOP_DEMAND_MATRIX,
    TC_VECTOR,
)

I0 = 10000
N_PRODUCTS = len(PRODUCTS)
P_IDX = {p: i for i, p in enumerate(PRODUCTS)}

# ---------------------------------------------------------------------------
# Production economics — grounded in `new rules.md` (Object Types table).
# ---------------------------------------------------------------------------
# Season-long output per tile over 30 days at optimal watering, NO fertilizer.
# Derived from growth times / yields in the rules:
#   wheat   harvests at ages 4,9,..,29 -> 6 x 4 units = 24 units/season
#   carrot  harvests at ages 3,7,..,27 -> 7 x 3 units = 21 units/season
#   tomato  single planting: yields days 8-11 (4), replant: days 20-23 (4) = 8
#   strawberry  yields days 10,12,14,16 + replant 26,28 = 6
#   melon   cycles of 11 days: 2 harvests x 6 units = 12
SEASON_YIELD_PER_TILE = {
    "WHEAT": 24.0, "CARROT": 21.0, "TOMATO": 8.0,
    "STRAWBERRY": 6.0, "MELON": 12.0,
}
# Animals produce indefinitely once mature (first-yield day from rules):
#   goose eggs days 4..29 = 26; cow milk every 2d from day 8 = 11;
#   sheep wool every 3d from day 6 = 8.
SEASON_OUTPUT_PER_ANIMAL = {"EGG": 26.0, "MILK": 11.0, "WOOL": 8.0}

# Season cost per tile = seed cost x number of plantings in 30 days.
SEASON_COST_PER_TILE = {
    "WHEAT": 6 * 10,    # $60
    "CARROT": 8 * 20,   # $160
    "TOMATO": 2 * 50,   # $100
    "STRAWBERRY": 2 * 100,  # $200
    "MELON": 3 * 80,    # $240
}
ANIMAL_PURCHASE_COST = {"EGG": 300, "MILK": 400, "WOOL": 500}
# ASSUMPTION: each animal eats 1 wheat/day (rules require daily feeding),
# valued at the wheat base market price of $25. Coop/pasture build cost unknown
# in rules -> treated as 0. Fertilizer from animals is free but unmodeled here.
FEED_COST_PER_DAY = 25.0
SEASON_FEED_COST = FEED_COST_PER_DAY * N_DAYS

CROPS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"]
ANIMAL_PRODUCTS = ["EGG", "MILK", "WOOL"]
TRADEABLE = CROPS + ANIMAL_PRODUCTS

# Scenario B baseline (task brief): one competitive player, steady-state sales.
BASELINE_PRODUCTION = {
    "WHEAT": 10, "CARROT": 3, "TOMATO": 2, "STRAWBERRY": 2,
    "MELON": 2, "EGG": 3, "MILK": 2, "WOOL": 2, "FERTILIZER": 0,
}


@dataclass
class ScenarioResult:
    name: str
    n_simulations: int
    production_per_day: dict
    draws: np.ndarray        # (n, 8) shop-type index per unlock event
    daily_demand: np.ndarray  # (n, 30, 9) float32
    inventory: np.ndarray     # (n, 30, 9) float32 — inventory when price is quoted
    prices: np.ndarray        # (n, 30, 9) int32


class MonteCarloRunner:
    def __init__(self, n_simulations=10000, seed=42):
        self.n_simulations = n_simulations
        self.seed = seed
        self._sim = ShopUnlockSimulator()

    def _production_vector(self, player_production):
        prod = {p: 0 for p in PRODUCTS}
        if player_production:
            for k, v in player_production.items():
                prod[k] = float(v)
        return np.array([prod[p] for p in PRODUCTS], dtype=np.float64)

    def run(self, player_production=None, name="scenario", rng=None, draws=None,
            compute_prices=True):
        """Run n_simulations seasons. `draws` may be passed to reuse the same
        unlock sequences across runs (common random numbers).

        compute_prices=False skips the per-product price evaluation and
        returns prices=None (used by the exhaustive enumerator, which prices
        batches with its own validated fused kernel).
        """
        rng = rng if rng is not None else np.random.default_rng(self.seed)
        n = self.n_simulations
        if draws is None:
            draws = self._sim.simulate_batch_indices(rng, n)

        unlock_days = np.asarray(ShopUnlockSimulator.UNLOCK_DAYS, dtype=np.float32)
        days = np.arange(N_DAYS, dtype=np.float32)
        active = (unlock_days[:, None] <= days[None, :]).astype(np.float32)  # (8 inst, 30 d)

        per_instance = SHOP_DEMAND_MATRIX[draws]                              # (n, 8, 9)
        daily_demand = np.einsum("kt,nkp->ntp", active, per_instance, optimize=True)
        daily_demand += TC_VECTOR[None, None, :]
        cum_demand = np.cumsum(daily_demand, axis=1, dtype=np.float32)

        prod_vec = self._production_vector(player_production).astype(np.float32)
        # constant daily rate -> cumulative at day t = rate * (t + 1)
        cum_prod = prod_vec[None, None, :] * np.arange(1, N_DAYS + 1, dtype=np.float32)[:, None]
        inventory = (I0 - cum_demand + cum_prod).astype(np.float32)

        if not compute_prices:
            return ScenarioResult(
                name=name, n_simulations=int(draws.shape[0]),
                production_per_day=dict(zip(PRODUCTS, prod_vec.tolist())),
                draws=draws, daily_demand=daily_demand,
                inventory=inventory, prices=None)

        prices = np.empty(draws.shape[:1] + (N_DAYS, N_PRODUCTS), dtype=np.int32)
        for i, product in enumerate(PRODUCTS):
            prices[:, :, i] = compute_price_vectorized(product, inventory[:, :, i])

        return ScenarioResult(
            name=name,
            n_simulations=n,
            production_per_day=dict(zip(PRODUCTS, prod_vec.tolist())),
            draws=draws,
            daily_demand=daily_demand,
            inventory=inventory,
            prices=prices,
        )

    def run_town_only(self, rng=None, draws=None):
        return self.run(None, "town_only", rng=rng, draws=draws)

    def run_single_player(self, rng=None, draws=None):
        return self.run(dict(BASELINE_PRODUCTION), "single_player", rng=rng, draws=draws)

    def run_two_players(self, rng=None, draws=None):
        prod = {k: 2 * v for k, v in BASELINE_PRODUCTION.items()}
        return self.run(prod, "two_players", rng=rng, draws=draws)


def sweep_production(runner, multipliers=(0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)):
    """Scenario D: vary production 0%..200% of baseline with shared RNG draws."""
    rng = np.random.default_rng(runner.seed)
    draws = ShopUnlockSimulator().simulate_batch_indices(rng, runner.n_simulations)
    results = {}
    for m in multipliers:
        prod = {k: m * v for k, v in BASELINE_PRODUCTION.items()}
        results[m] = runner.run(prod, f"sweep_{int(m*100)}pct", rng=rng, draws=draws)
    return results


if __name__ == "__main__":
    import time
    runner = MonteCarloRunner(n_simulations=10000, seed=42)
    t0 = time.perf_counter()
    a = runner.run_town_only()
    t1 = time.perf_counter()
    print(f"town_only 10k sims: {t1 - t0:.2f}s")
    print("median day-15 prices:", {p: int(np.median(a.prices[:, 15, P_IDX[p]])) for p in TRADEABLE})
