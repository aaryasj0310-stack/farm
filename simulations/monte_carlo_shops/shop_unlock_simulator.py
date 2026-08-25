"""Module 1: Simulates the random town shop unlock sequence for one season.

Shops unlock every 3 days (days 3, 6, 9, ..., 24), drawn uniformly at random
WITH REPLACEMENT from the 8-shop table. Unlocking stops after 8 total instances.
"""
import random

import numpy as np


class ShopUnlockSimulator:
    SHOP_TYPES = [
        "BAKERY", "PIZZA_SHOP", "BRUNCH_SPOT", "YARN_STORE",
        "ICE_CREAM_SHOP", "PET_CAFE", "SMOOTHIE_SHOP", "FARMERS_MARKET",
    ]
    UNLOCK_DAYS = [3, 6, 9, 12, 15, 18, 21, 24]
    MAX_INSTANCES = 8

    def simulate_season(self, seed=None):
        """Returns list of (unlock_day, shop_type) for one random season."""
        rng = random.Random(seed)
        draws = [rng.randrange(len(self.SHOP_TYPES)) for _ in range(self.MAX_INSTANCES)]
        return [(self.UNLOCK_DAYS[i], self.SHOP_TYPES[d]) for i, d in enumerate(draws)]

    def simulate_batch_indices(self, rng, n):
        """Vectorized batch: (n, MAX_INSTANCES) int array of shop-type indices.

        Row k holds the shop type drawn at unlock event k (day UNLOCK_DAYS[k]).
        Uses a numpy Generator so batches share one seeded RNG stream.
        """
        return rng.integers(0, len(self.SHOP_TYPES), size=(n, self.MAX_INSTANCES))

    def indices_to_sequence(self, row):
        """Convert one row of indices back to [(unlock_day, shop_type), ...]."""
        return [(self.UNLOCK_DAYS[k], self.SHOP_TYPES[s]) for k, s in enumerate(row)]


if __name__ == "__main__":
    sim = ShopUnlockSimulator()
    print(sim.simulate_season(seed=42))
