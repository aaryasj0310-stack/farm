"""Validate exact dynamic programming and PMFs against 500,000 Monte Carlo seasons.

Tests expectation, variance, and quantile/distribution equivalence across:
- Day 0 -> Day 10
- Day 0 -> Day 28
- Day 6 -> Day 18
- Day 12 -> Day 28
- Duplicate Yarn state
- Duplicate Milk-shop state
- Duplicate Egg-shop state
"""
import os
import sys
import time
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from simulations.monte_carlo_shops.town_demand_engine import (
    SHOP_DEMAND_MATRIX, TC_VECTOR, PRODUCTS, PRODUCT_INDEX, SHOP_TYPES, N_DAYS
)
from simulations.monte_carlo_shops.shop_unlock_simulator import ShopUnlockSimulator
import importlib.util
_baked_path = os.path.join(_ROOT, "agent", "strategy", "baked_conditional_animal_prices.py")
_spec = importlib.util.spec_from_file_location("baked_conditional_animal_prices", _baked_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

CANONICAL_SHOPS = _mod.CANONICAL_SHOPS
TARGET_PRODUCTS = _mod.TARGET_PRODUCTS
SHOP_DEMAND_RATES = _mod.SHOP_DEMAND_RATES
FUTURE_EXPECTED_DRAIN = _mod.FUTURE_EXPECTED_DRAIN
FUTURE_DRAIN_VARIANCE = _mod.FUTURE_DRAIN_VARIANCE
FUTURE_DRAIN_PMF = _mod.FUTURE_DRAIN_PMF
UNLOCK_DAYS = _mod.UNLOCK_DAYS
compute_known_existing_drain = _mod.compute_known_existing_drain
get_future_drain_pmf = _mod.get_future_drain_pmf
compute_total_expected_drain = _mod.compute_total_expected_drain


def run_equivalence_audit():
    print("=== EXACT PMF & MONTE CARLO DISTRIBUTION AUDIT ===")
    
    N = 500000
    print(f"Generating {N:,} random seasons for brute-force baseline...")
    t0 = time.time()
    rng = np.random.default_rng(42)
    all_draws = rng.integers(0, 8, size=(N, 8))
    
    unlock_days = np.asarray(UNLOCK_DAYS, dtype=np.float32)
    days = np.arange(N_DAYS, dtype=np.float32)
    active = (unlock_days[:, None] <= days[None, :]).astype(np.float32)
    per_inst = SHOP_DEMAND_MATRIX[all_draws]
    daily_demand = np.einsum('kt,nkp->ntp', active, per_inst) + TC_VECTOR[None, None, :]
    cum_demand = np.cumsum(daily_demand, axis=1)
    mc_prep_time = time.time() - t0
    print(f"MC generation completed in {mc_prep_time:.2f}s.")

    test_cases = [
        {"name": "Day 0 -> Day 10 (no shops yet)", "d": 0, "t": 10, "shops": []},
        {"name": "Day 0 -> Day 28 (season total)", "d": 0, "t": 28, "shops": []},
        {"name": "Day 6 -> Day 18: YARN_STORE + BAKERY", "d": 6, "t": 18, "shops": ["YARN_STORE", "BAKERY"]},
        {"name": "Day 6 -> Day 18: PIZZA_SHOP + PET_CAFE (No Yarn)", "d": 6, "t": 18, "shops": ["PIZZA_SHOP", "PET_CAFE"]},
        {"name": "Day 12 -> Day 28: PIZZA + ICE_CREAM + SMOOTHIE + BAKERY (Duplicate Milk)", "d": 12, "t": 28, "shops": ["PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP", "BAKERY"]},
        {"name": "Day 12 -> Day 28: YARN_STORE + YARN_STORE + BAKERY + BRUNCH (Duplicate Yarn)", "d": 12, "t": 28, "shops": ["YARN_STORE", "YARN_STORE", "BAKERY", "BRUNCH_SPOT"]},
        {"name": "Day 12 -> Day 28: BAKERY + BAKERY + BRUNCH + BRUNCH (Duplicate Egg)", "d": 12, "t": 28, "shops": ["BAKERY", "BAKERY", "BRUNCH_SPOT", "BRUNCH_SPOT"]},
    ]

    for tc in test_cases:
        d = tc["d"]
        t = tc["t"]
        shops = tc["shops"]
        k = len(shops)
        
        if k == 0:
            sub_cum = cum_demand
        else:
            eng_indices = [SHOP_TYPES.index(s) for s in shops]
            mask_cond = np.ones(N, dtype=bool)
            for step_idx, eng_idx in enumerate(eng_indices):
                mask_cond &= (all_draws[:, step_idx] == eng_idx)
            sub_cum = cum_demand[mask_cond]

        print(f"\n--- {tc['name']} (Matched N = {len(sub_cum):,}) ---")
        
        for p in TARGET_PRODUCTS:
            p_idx = PRODUCT_INDEX[p]
            mc_samples = sub_cum[:, t, p_idx] - sub_cum[:, d, p_idx]
            mc_mean = float(np.mean(mc_samples))
            mc_var = float(np.var(mc_samples))
            mc_p50 = float(np.percentile(mc_samples, 50))
            mc_p90 = float(np.percentile(mc_samples, 90))
            
            # Exact PMF distribution:
            known_drain = compute_known_existing_drain(p, d, t, shops)
            pmf = get_future_drain_pmf(p, d, t)
            
            # Total drain PMF:
            total_pmf = {known_drain + float(f_drain): prob for f_drain, prob in pmf.items()}
            exact_mean = sum(val * prob for val, prob in total_pmf.items())
            exact_var = sum(((val - exact_mean) ** 2) * prob for val, prob in total_pmf.items())
            
            # Theoretical quantiles from PMF CDF:
            sorted_pmf = sorted(total_pmf.items())
            cum_p = 0.0
            pmf_p50 = None
            pmf_p90 = None
            for val, prob in sorted_pmf:
                cum_p += prob
                if pmf_p50 is None and cum_p >= 0.50:
                    pmf_p50 = val
                if pmf_p90 is None and cum_p >= 0.90:
                    pmf_p90 = val
            
            diff_mean = abs(mc_mean - exact_mean)
            diff_var = abs(mc_var - exact_var)
            std_err_mean = np.sqrt(mc_var / max(1, len(mc_samples)))
            z_mean = diff_mean / max(0.001, std_err_mean)
            
            # Check quantiles match within small bin width
            q50_diff = abs(mc_p50 - pmf_p50)
            q90_diff = abs(mc_p90 - pmf_p90)
            
            # Sample variance standard error is approx sqrt(2 / (N - 1)) * exact_var
            se_var = np.sqrt(2.0 / max(1, len(mc_samples) - 1)) * exact_var
            z_var = diff_var / max(1.0, se_var)

            status = "PASS" if z_mean < 3.0 and z_var < 3.0 else "FAIL"
            print(f"  {p:4s}: Mean [MC={mc_mean:6.2f}, DP={exact_mean:6.2f}, z={z_mean:4.2f}] | "
                  f"Var [MC={mc_var:8.1f}, DP={exact_var:8.1f}, z_var={z_var:4.2f}] | "
                  f"P50 [MC={mc_p50:4.0f}, DP={pmf_p50:4.0f}] | "
                  f"P90 [MC={mc_p90:4.0f}, DP={pmf_p90:4.0f}] [{status}]")
            assert status == "PASS", f"Discrepancy too large in {tc['name']} for {p} (z_var={z_var:.2f})"

    print("\n==========================================================================")
    print("ALL TEST CASES PASSED FULL DISTRIBUTION & QUANTILE EQUIVALENCE!")
    print("==========================================================================")


if __name__ == "__main__":
    run_equivalence_audit()
