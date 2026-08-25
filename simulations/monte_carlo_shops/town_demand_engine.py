"""Module 2: Total town demand (town center + unlocked shops) per product per day.

Shop demand table matches the game rules exactly. Each shop instance consumes
1 unit of each demanded product every 4 turns (= 6/day); single-product shops
consume 2x (12/day). The town center consumes 1 of every product (excluding
FERTILIZER) once per day, flat for the whole season.
"""
import numpy as np

N_DAYS = 30

PRODUCTS = [
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY",
    "MELON", "EGG", "MILK", "WOOL", "FERTILIZER",
]
PRODUCT_INDEX = {p: i for i, p in enumerate(PRODUCTS)}

SHOP_DEMANDS = {
    "BAKERY":         {"EGG": 6, "WHEAT": 6},
    "PIZZA_SHOP":     {"MILK": 6, "TOMATO": 6, "WHEAT": 6},
    "BRUNCH_SPOT":    {"EGG": 6, "WHEAT": 6, "STRAWBERRY": 6},
    "YARN_STORE":     {"WOOL": 12},   # single-product 2x
    "ICE_CREAM_SHOP": {"STRAWBERRY": 6, "MILK": 6, "WHEAT": 6},
    "PET_CAFE":       {"CARROT": 12}, # single-product 2x
    "SMOOTHIE_SHOP":  {"STRAWBERRY": 6, "MILK": 6},
    "FARMERS_MARKET": {"WHEAT": 6, "CARROT": 6, "TOMATO": 6, "STRAWBERRY": 6},
}

TOWN_CENTER_DAILY = {
    "WHEAT": 1, "CARROT": 1, "TOMATO": 1, "STRAWBERRY": 1,
    "MELON": 1, "EGG": 1, "MILK": 1, "WOOL": 1,
}  # No fertilizer

SHOP_TYPES = list(SHOP_DEMANDS.keys())

# Matrix form for vectorized simulation: (n_shop_types, n_products)
SHOP_DEMAND_MATRIX = np.zeros((len(SHOP_TYPES), len(PRODUCTS)), dtype=np.float32)
for s, demands in SHOP_DEMANDS.items():
    for p, units in demands.items():
        SHOP_DEMAND_MATRIX[SHOP_TYPES.index(s), PRODUCT_INDEX[p]] = units

# Town center daily demand vector: (n_products,)
TC_VECTOR = np.zeros(len(PRODUCTS), dtype=np.float32)
for p, units in TOWN_CENTER_DAILY.items():
    TC_VECTOR[PRODUCT_INDEX[p]] = units


class TownDemandEngine:
    def compute_daily_demand(self, day, unlock_sequence):
        """Total demand on `day`: town center + shops unlocked on or before it.

        Returns {product: total_units_consumed_today} (all 9 products; fertilizer 0).
        """
        totals = {p: 0 for p in PRODUCTS}
        totals.update(TOWN_CENTER_DAILY)  # constant town center demand
        for unlock_day, shop_type in unlock_sequence:
            if unlock_day <= day:
                for product, units in SHOP_DEMANDS[shop_type].items():
                    totals[product] += units
        return totals

    def compute_cumulative_demand(self, unlock_sequence):
        """{product: [cumulative_units_consumed_by_day_0, ..., by_day_29]}."""
        cumulative = {p: [] for p in PRODUCTS}
        running = {p: 0 for p in PRODUCTS}
        for day in range(N_DAYS):
            daily = self.compute_daily_demand(day, unlock_sequence)
            for p in PRODUCTS:
                running[p] += daily[p]
                cumulative[p].append(running[p])
        return cumulative


if __name__ == "__main__":
    engine = TownDemandEngine()
    seq = [(3, "BAKERY"), (6, "PET_CAFE")]
    print("day 2 (TC only):", engine.compute_daily_demand(2, []))
    print("day 3 (bakery): ", engine.compute_daily_demand(3, seq))
    print("day 6 (bakery+pet cafe):", engine.compute_daily_demand(6, seq))
