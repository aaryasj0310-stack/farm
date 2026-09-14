"""Exact Dynamic Programming generator for conditional livestock demand & drain forecasts.

Decomposition Theorem:
For any decision day d and future day t >= d, the total expected town demand
from day d to day t decomposes strictly into:

    TotalExpectedDrain(P, d -> t) = KnownExistingDrain(P, d -> t) + ExpectedFutureUnlockDrain(P, d -> t)

where:
1. KnownExistingDrain(P, d -> t) =
       (t - d) * [ TC(P) + sum_{s in unlocked_shops} count(s) * r(s, P) ]
   which preserves exact multiplicities of all already-unlocked shops.

2. FutureUnlockDrain(P, d -> t) has an EXACT DISCRETE PROBABILITY MASS FUNCTION (PMF):
       FUTURE_DRAIN_PMF[product][current_day][target_day] = {drain_amount: exact_probability}
   computed via dynamic programming convolution over independent future unlock events.
   Because future shop draws are IID uniform over the 8 shop types (p = 1/8),
   the future unlock drain distribution depends strictly on (product, current_day, target_day)
   and is completely independent of past shop history.

3. Generic exact variance:
   E[r]   = sum_s p(s) * r(s, P)
   E[r^2] = sum_s p(s) * r(s, P)^2
   Var[r] = E[r^2] - (E[r])^2
   Var[future_drain] = sum_{j: d < D_j <= t} (t - D_j + 1)^2 * Var[r]
"""
import os
import sys
import pprint

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

UNLOCK_DAYS = [3, 6, 9, 12, 15, 18, 21, 24]
N_DAYS = 30

CANONICAL_SHOPS = [
    "BAKERY",          # 0: EGG (6), WHEAT (6)
    "BRUNCH_SPOT",     # 1: EGG (6), WHEAT (6), STRAWBERRY (6)
    "FARMERS_MARKET",  # 2: WHEAT (6), CARROT (6), TOMATO (6), STRAWBERRY (6)
    "ICE_CREAM_SHOP",  # 3: STRAWBERRY (6), MILK (6), WHEAT (6)
    "PET_CAFE",        # 4: CARROT (12)
    "PIZZA_SHOP",      # 5: MILK (6), TOMATO (6), WHEAT (6)
    "SMOOTHIE_SHOP",   # 6: STRAWBERRY (6), MILK (6)
    "YARN_STORE",      # 7: WOOL (12)
]

TARGET_PRODUCTS = ["MILK", "WOOL", "EGG"]

SHOP_DEMAND_RATES = {
    "WOOL": {
        "YARN_STORE": 12.0,
    },
    "MILK": {
        "PIZZA_SHOP": 6.0,
        "ICE_CREAM_SHOP": 6.0,
        "SMOOTHIE_SHOP": 6.0,
    },
    "EGG": {
        "BAKERY": 6.0,
        "BRUNCH_SPOT": 6.0,
    },
}

TC_DEMAND = {p: 1.0 for p in TARGET_PRODUCTS}


def compute_generic_moments():
    """Compute E[r], E[r^2], and Var[r] generically for all target products."""
    moments = {}
    p_s = 1.0 / float(len(CANONICAL_SHOPS))  # 1/8
    for p in TARGET_PRODUCTS:
        rates = [SHOP_DEMAND_RATES.get(p, {}).get(s, 0.0) for s in CANONICAL_SHOPS]
        e_r = sum(p_s * r for r in rates)
        e_r2 = sum(p_s * (r ** 2) for r in rates)
        var_r = e_r2 - (e_r ** 2)
        moments[p] = {
            "e_r": e_r,
            "e_r2": e_r2,
            "var_r": var_r,
        }
    return moments


def compute_exact_drain_tables():
    """Compute exact future expected drain, variance, unconditional baseline, and exact PMFs."""
    moments = compute_generic_moments()
    future_expected_drain = {}
    future_drain_variance = {}
    unconditional_drain = {}
    future_drain_pmf = {}

    p_hits = {
        "WOOL": 1.0 / 8.0,
        "MILK": 3.0 / 8.0,
        "EGG":  2.0 / 8.0,
    }
    rates = {
        "WOOL": 12.0,
        "MILK": 6.0,
        "EGG":  6.0,
    }

    for p in TARGET_PRODUCTS:
        m = moments[p]
        e_r = m["e_r"]
        var_r = m["var_r"]
        p_hit = p_hits[p]
        rate = rates[p]

        f_matrix = []
        var_matrix = []
        u_matrix = []
        pmf_matrix = []

        for d in range(N_DAYS):
            f_row = []
            var_row = []
            u_row = []
            pmf_row = []

            for t in range(N_DAYS):
                if t < d:
                    f_row.append(0.0)
                    var_row.append(0.0)
                    u_row.append(0.0)
                    pmf_row.append({0: 1.0})
                else:
                    future_events = [ed for ed in UNLOCK_DAYS if d < ed <= t]
                    weights = [(t - ed + 1) for ed in future_events]
                    
                    # Generic exact expectation: sum w_j * E[r]
                    exp_future = float(sum(w * e_r for w in weights))
                    # Generic exact variance: sum w_j^2 * Var[r]
                    var_future = float(sum((w ** 2) * var_r for w in weights))
                    
                    f_row.append(round(exp_future, 4))
                    var_row.append(round(var_future, 4))

                    # Unconditional baseline:
                    past_events = [ed for ed in UNLOCK_DAYS if ed <= d]
                    past_drain = len(past_events) * (t - d) * e_r
                    tc_drain = (t - d) * TC_DEMAND[p]
                    u_drain = tc_drain + past_drain + exp_future
                    u_row.append(round(u_drain, 4))

                    # Exact PMF via DP integer sequence counts over independent future unlock events:
                    k = len(future_events)
                    denom = 8 ** k
                    n_hits = 1 if p == "WOOL" else (3 if p == "MILK" else 2)
                    n_miss = 8 - n_hits

                    counts = {0: 1}
                    for ed in future_events:
                        unit = int(round(rate * (t - ed + 1)))
                        new_counts = {}
                        for val, cnt in counts.items():
                            new_counts[val] = new_counts.get(val, 0) + cnt * n_miss
                            new_counts[val + unit] = new_counts.get(val + unit, 0) + cnt * n_hits
                        counts = new_counts

                    clean_counts = {int(v): int(c) for v, c in sorted(counts.items())}
                    pmf_row.append({"counts": clean_counts, "denominator": denom})

            f_matrix.append(f_row)
            var_matrix.append(var_row)
            u_matrix.append(u_row)
            pmf_matrix.append(pmf_row)

        future_expected_drain[p] = f_matrix
        future_drain_variance[p] = var_matrix
        unconditional_drain[p] = u_matrix
        future_drain_pmf[p] = pmf_matrix

    return {
        "canonical_shops": CANONICAL_SHOPS,
        "target_products": TARGET_PRODUCTS,
        "unlock_days": UNLOCK_DAYS,
        "shop_demand_rates": SHOP_DEMAND_RATES,
        "tc_demand": TC_DEMAND,
        "moments": moments,
        "future_expected_drain": future_expected_drain,
        "future_drain_variance": future_drain_variance,
        "unconditional_drain": unconditional_drain,
        "future_drain_pmf": future_drain_pmf,
    }


def write_baked_file(data, filepath):
    """Write the compact baked table as a standalone python module with runtime helpers."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Auto-generated exact conditional livestock demand & drain table.\n")
        f.write("# Deterministic existing drain + exact stochastic future unlock drain PMF decomposition.\n\n")
        f.write(f"CANONICAL_SHOPS = {pprint.pformat(data['canonical_shops'])}\n\n")
        f.write(f"TARGET_PRODUCTS = {pprint.pformat(data['target_products'])}\n\n")
        f.write(f"UNLOCK_DAYS = {pprint.pformat(data['unlock_days'])}\n\n")
        f.write(f"SHOP_DEMAND_RATES = {pprint.pformat(data['shop_demand_rates'])}\n\n")
        f.write(f"TC_DEMAND = {pprint.pformat(data['tc_demand'])}\n\n")
        f.write(f"GENERIC_MOMENTS = {pprint.pformat(data['moments'])}\n\n")
        f.write(f"FUTURE_EXPECTED_DRAIN = {pprint.pformat(data['future_expected_drain'], compact=True)}\n\n")
        f.write(f"FUTURE_DRAIN_VARIANCE = {pprint.pformat(data['future_drain_variance'], compact=True)}\n\n")
        f.write(f"UNCONDITIONAL_DRAIN = {pprint.pformat(data['unconditional_drain'], compact=True)}\n\n")
        
        # Write FUTURE_DRAIN_PMF cleanly
        f.write("FUTURE_DRAIN_PMF = {\n")
        for p in data["target_products"]:
            f.write(f"    {repr(p)}: [\n")
            for row in data["future_drain_pmf"][p]:
                row_str = ", ".join(repr(cell) for cell in row)
                f.write(f"        [{row_str}],\n")
            f.write("    ],\n")
        f.write("}\n\n")

        # Runtime helper methods
        f.write('''
def get_shop_counts(unlocked_shops):
    """Preserve exact shop multiplicities as a dictionary {shop_name: count}."""
    counts = {}
    if not unlocked_shops:
        return counts
    for s in unlocked_shops:
        counts[s] = counts.get(s, 0) + 1
    return counts


def get_shop_mask(unlocked_shops):
    """Presence bitmask for legacy/compatibility checks only. DO NOT USE FOR DEMAND."""
    mask = 0
    if not unlocked_shops:
        return mask
    for s in unlocked_shops:
        if s in CANONICAL_SHOPS:
            mask |= (1 << CANONICAL_SHOPS.index(s))
    return mask


def compute_known_existing_drain(product, day, target_day, unlocked_shops):
    """Deterministic cumulative drain from Town Center + already-unlocked shops."""
    d = max(0, min(int(day), 29))
    t = max(0, min(int(target_day), 29))
    if t <= d:
        return 0.0
    active_days = t - d
    tc = TC_DEMAND.get(product, 1.0) if product != "FERTILIZER" else 0.0
    rates = SHOP_DEMAND_RATES.get(product, {})
    
    existing_shop_rate = sum(rates.get(s, 0.0) for s in (unlocked_shops or []))
    return float(active_days * (tc + existing_shop_rate))


def get_future_drain_counts(product, day, target_day):
    """Return exact integer (counts_dict, denominator) for stochastic future unlocks.
    sum(counts_dict.values()) == denominator == 8**k.
    """
    d = max(0, min(int(day), 29))
    t = max(0, min(int(target_day), 29))
    if t <= d:
        return ({0: 1}, 1)
    mat = FUTURE_DRAIN_PMF.get(product)
    if not mat:
        return ({0: 1}, 1)
    cell = mat[d][t]
    if isinstance(cell, dict) and "counts" in cell:
        return cell["counts"], cell["denominator"]
    elif isinstance(cell, tuple):
        return cell[0], cell[1]
    return (cell, 1)


def get_future_drain_pmf(product, day, target_day):
    """Exact discrete PMF {future_drain_amount: exact_probability} for stochastic future unlocks."""
    d = max(0, min(int(day), 29))
    t = max(0, min(int(target_day), 29))
    if t <= d:
        return {0: 1.0}
    mat = FUTURE_DRAIN_PMF.get(product)
    if not mat:
        return {0: 1.0}
    cell = mat[d][t]
    if isinstance(cell, dict) and "counts" in cell:
        counts = cell["counts"]
        denom = cell["denominator"]
        inv_d = 1.0 / float(denom)
        return {v: c * inv_d for v, c in counts.items()}
    elif isinstance(cell, tuple):
        counts, denom = cell
        inv_d = 1.0 / float(denom)
        return {v: c * inv_d for v, c in counts.items()}
    return cell


def compute_expected_future_unlock_drain(product, day, target_day):
    """Stochastic expectation of drain from shops unlocking in (day, target_day]."""
    d = max(0, min(int(day), 29))
    t = max(0, min(int(target_day), 29))
    if t <= d:
        return 0.0
    mat = FUTURE_EXPECTED_DRAIN.get(product)
    if not mat:
        return 0.0
    return float(mat[d][t])


def compute_total_expected_drain(product, day, target_day, unlocked_shops):
    """Total conditional expected drain: known existing + expected future unlocks."""
    return (
        compute_known_existing_drain(product, day, target_day, unlocked_shops) +
        compute_expected_future_unlock_drain(product, day, target_day)
    )


def prob_shop_unlocked(shop_name, day, target_day, unlocked_shops):
    """Exact probability that shop_name is active on or before target_day."""
    if unlocked_shops and shop_name in unlocked_shops:
        return 1.0
    d = max(0, min(int(day), 29))
    t = max(0, min(int(target_day), 29))
    if t < d:
        return 0.0
    n_future_events = sum(1 for ed in UNLOCK_DAYS if d < ed <= t)
    if n_future_events == 0:
        return 0.0
    return 1.0 - (7.0 / 8.0) ** n_future_events


def expected_price_from_drain_pmf(
    product,
    day,
    target_day,
    current_market_inv,
    unlocked_shops,
    extra_supply=0.0,
    price_fn=None,
):
    """Exact expected price E[Price(Inventory)] integrating across the future drain PMF.
    
    Computes E[Price(Inv - TotalDrain)], NEVER Price(Inv - E[TotalDrain]).
    """
    if price_fn is None:
        try:
            from market.price_math import market_price
            price_fn = market_price
        except ImportError:
            # Flat import fallback
            from price_math import market_price
            price_fn = market_price

    known_drain = compute_known_existing_drain(product, day, target_day, unlocked_shops)
    pmf = get_future_drain_pmf(product, day, target_day)

    expected_price = 0.0
    base_inv = float(current_market_inv) + float(extra_supply) - known_drain

    for future_drain, prob in pmf.items():
        inv_outcome = base_inv - float(future_drain)
        price_outcome = float(price_fn(product, inv_outcome))
        expected_price += prob * price_outcome

    return expected_price
''')
    print(f"Wrote exact baked conditional demand & PMF table to {filepath} ({os.path.getsize(filepath) / 1024:.1f} KB)")


if __name__ == "__main__":
    tables = compute_exact_drain_tables()
    target_path = os.path.join(_ROOT, "agent", "strategy", "baked_conditional_animal_prices.py")
    write_baked_file(tables, target_path)
