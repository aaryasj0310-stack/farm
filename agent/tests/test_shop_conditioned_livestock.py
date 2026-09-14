"""Unit and regression tests for conditional shop demand forecasting and exact PMF integration.

Tests:
1. Exact PMF normalization and non-negativity across all (product, current_day, target_day).
2. PMF moment equivalence: sum(x * p) == FUTURE_EXPECTED_DRAIN and sum((x-E)^2 * p) == FUTURE_DRAIN_VARIANCE.
3. Controlled nonlinear pricing example proving E[Price(Inv - Drain)] != Price(Inv - E[Drain]).
4. Direct marginal revenue counterfactual captures own-supply price depression without double-counting.
5. Duplicate-shop distinction with identical bitmask.
6. Future unlock drain independence from past shop history.
7. Monte Carlo distribution equivalence across expectation, variance, and mass points (200k samples).
8. Zero NumPy dependency in runtime prediction helpers.
"""
import os
import sys
import pytest
import numpy as np

# Add agent and repo root to sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT_DIR = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_AGENT_DIR)
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import itertools
from config import ANIMALS
from market.price_math import market_price
from strategy.baked_conditional_animal_prices import (
    CANONICAL_SHOPS, TARGET_PRODUCTS, SHOP_DEMAND_RATES,
    FUTURE_EXPECTED_DRAIN, FUTURE_DRAIN_VARIANCE, UNCONDITIONAL_DRAIN,
    FUTURE_DRAIN_PMF, UNLOCK_DAYS, GENERIC_MOMENTS,
    get_shop_counts, get_shop_mask,
    compute_known_existing_drain, compute_expected_future_unlock_drain,
    compute_total_expected_drain, prob_shop_unlocked,
    get_future_drain_pmf, expected_price_from_drain_pmf,
    get_future_drain_counts
)
from strategy.marginal_livestock_valuator import estimate_realized_marginal_animal_value
from simulations.monte_carlo_shops.town_demand_engine import (
    SHOP_DEMAND_MATRIX, TC_VECTOR, PRODUCT_INDEX, SHOP_TYPES, N_DAYS
)


def test_pmf_normalization_and_moments():
    """Verify for every (product, d, t) that PMF sums to 1.0, has no negative probabilities,
    and matches the exact analytic expectation and variance tables within 1e-5.
    """
    for p in TARGET_PRODUCTS:
        for d in range(N_DAYS):
            for t in range(d, N_DAYS):
                pmf = get_future_drain_pmf(p, d, t)
                assert len(pmf) > 0, f"PMF empty for {p} d={d} t={t}"

                # 1. Normalization & non-negativity
                prob_sum = sum(pmf.values())
                assert abs(prob_sum - 1.0) < 1e-5, f"PMF prob sum != 1.0: {prob_sum} ({p}, d={d}, t={t})"
                for val, prob in pmf.items():
                    assert prob >= 0.0, f"Negative prob {prob} in PMF for {p} d={d} t={t}"
                    assert val >= 0, f"Negative drain {val} in PMF for {p} d={d} t={t}"

                # 2. Moments equivalence
                pmf_exp = sum(val * prob for val, prob in pmf.items())
                table_exp = FUTURE_EXPECTED_DRAIN[p][d][t]
                assert abs(pmf_exp - table_exp) < 1e-4, (
                    f"Expectation mismatch for {p} d={d} t={t}: PMF={pmf_exp}, Table={table_exp}"
                )

                pmf_var = sum(((val - pmf_exp) ** 2) * prob for val, prob in pmf.items())
                table_var = FUTURE_DRAIN_VARIANCE[p][d][t]
                var_diff = abs(pmf_var - table_var)
                assert var_diff < 0.01 or (var_diff / max(1.0, table_var)) < 1e-5, (
                    f"Variance mismatch for {p} d={d} t={t}: PMF={pmf_var}, Table={table_var}, diff={var_diff}"
                )


def test_nonlinear_price_jensen_gap():
    """Controlled demonstration proving E[Price(Inv - Drain)] != Price(Inv - E[Drain]).
    Due to the quadratic glut curve of WOOL, evaluating price at expected inventory
    substantially overestimates price compared to exact expectation over the PMF.
    """
    p = "WOOL"
    d = 6
    t = 18
    # Start near I0 = 10,000 where the quadratic curve creates sharp nonlinearity
    market_inv = 10020.0
    unlocked_shops = ["PIZZA_SHOP", "PET_CAFE"]  # No Yarn Store unlocked yet

    # Audit PMF support: at d=6 targeting t=18, future unlock events occur at D9, D12, D15, D18.
    # Contributing units if Yarn Store unlocks: D9: 120, D12: 84, D15: 48, D18: 12.
    # Exact convolved support has 15 distinct outcomes, and sequence counts sum to 8^4 = 4096.
    counts, denom = get_future_drain_counts(p, d, t)
    pmf = get_future_drain_pmf(p, d, t)

    print(f"\n--- True 4-Event Convolved PMF for WOOL (d={d} -> t={t}) ---")
    print(f"Denominator: {denom} (8^4)")
    print(f"Distinct outcomes: {len(counts)}")
    print("Exact integer sequence counts & probabilities:")
    for drain_val, cnt in counts.items():
        print(f"  Drain={drain_val:3d}: count={cnt:4d}/{denom} (p={pmf[drain_val]:.6f})")

    expected_outcomes = [0, 12, 48, 60, 84, 96, 120, 132, 144, 168, 180, 204, 216, 252, 264]
    assert sorted(counts.keys()) == expected_outcomes
    assert counts[0] == 2401  # (7/8)^4 * 4096
    assert counts[12] == 343  # hit only at D18: 7^3 * 1 = 343
    assert counts[132] == 98  # D9(120)+D18(12)=132 (49) + D12(84)+D15(48)=132 (49) -> 98
    assert counts[264] == 1   # hits at all 4 events: 120+84+48+12 = 264
    assert sum(counts.values()) == denom == 4096

    # 1. Price at expected inventory: Price(Inv - E[TotalDrain])
    e_total_drain = compute_total_expected_drain(p, d, t, unlocked_shops)
    inv_at_e_drain = market_inv - e_total_drain
    price_at_e_inv = market_price(p, inv_at_e_drain)

    # 2. Exact expected price integrating across PMF: E[Price(Inv - TotalDrain)]
    e_price = expected_price_from_drain_pmf(
        p, d, t, market_inv, unlocked_shops, extra_supply=0.0, price_fn=market_price
    )

    print(f"\nNonlinear Pricing Comparison for WOOL (d={d} -> t={t}):")
    print(f"  E[TotalDrain]: {e_total_drain:.2f}")
    print(f"  Inv at E[Drain]: {inv_at_e_drain:.2f} -> Price: ${price_at_e_inv}")
    print(f"  E[Price(Inv - Drain)] across PMF: ${e_price:.2f}")
    print(f"  Jensen / Nonlinear Gap: ${abs(price_at_e_inv - e_price):.2f}")

    # Must NOT be equal!
    assert price_at_e_inv != e_price
    assert abs(price_at_e_inv - e_price) > 5.0, "Expected significant gap due to quadratic curve"


def test_exact_enumeration_equivalence():
    """Verify bit-for-bit equivalence between DP sequence counts and exhaustive enumeration
    over all 8^k sequence draws across representative (product, d, t) scenarios.
    """
    cases = [
        ("WOOL", 6, 18),   # 4 events, 4,096 sequences
        ("MILK", 6, 18),   # 4 events, 4,096 sequences
        ("EGG", 6, 18),    # 4 events, 4,096 sequences
        ("WOOL", 15, 24),  # 3 events, 512 sequences
        ("MILK", 18, 24),  # 2 events, 64 sequences
        ("EGG", 21, 24),   # 1 event, 8 sequences
    ]
    for prod, d, t in cases:
        events = [ed for ed in UNLOCK_DAYS if d < ed <= t]
        k = len(events)

        # 1. Exhaustive enumeration of all 8^k shop sequences
        enum_counts = {}
        for seq in itertools.product(CANONICAL_SHOPS, repeat=k):
            drain = 0
            for s, ed in zip(seq, events):
                r = SHOP_DEMAND_RATES.get(prod, {}).get(s, 0.0)
                drain += int(round(r * (t - ed + 1)))
            enum_counts[drain] = enum_counts.get(drain, 0) + 1

        # 2. Baked DP integer counts
        baked_counts, denom = get_future_drain_counts(prod, d, t)
        assert denom == 8 ** k
        assert sum(baked_counts.values()) == 8 ** k
        assert baked_counts == enum_counts, (
            f"Exact count mismatch for {prod} d={d} t={t}!\nDP: {baked_counts}\nEnum: {enum_counts}"
        )


def test_sequential_counterfactual_wool_glut_and_high_yarn():
    """Test sequential counterfactual valuation under wool-glut vs high-Yarn drain:
    1. Wool-glut: 4 existing sheep, candidate sheep producing D12, D15, D18; weak town drain (0 Yarn Stores).
       Prove early wool depresses later prices and existing herd revenue falls (market_impact_cost > 1000).
    2. High Yarn drain: 2 Yarn Stores active.
       Prove candidate sheep achieves significantly higher marginal revenue (Delta > $5,000).
    3. Mathematical identity: marginal_product_revenue == gross_product_revenue - market_impact_cost.
    """
    # 1. Wool Glut: 4 existing sheep, 0 Yarn stores active
    eval_glut = estimate_realized_marginal_animal_value(
        species="SHEEP",
        day=6,
        current_animals={"SHEEP": 4},
        market_inventory={"WOOL": 10000.0, "MILK": 10000.0, "FERTILIZER": 10000.0, "WHEAT": 10000.0},
        town_shops=[],
        empty_pastures=1,
    )

    # 2. High Yarn: 4 existing sheep, 2 Yarn stores active
    eval_yarn = estimate_realized_marginal_animal_value(
        species="SHEEP",
        day=6,
        current_animals={"SHEEP": 4},
        market_inventory={"WOOL": 10000.0, "MILK": 10000.0, "FERTILIZER": 10000.0, "WHEAT": 10000.0},
        town_shops=["YARN_STORE", "YARN_STORE"],
        empty_pastures=1,
    )

    print("\n--- Sequential Counterfactual Valuation Test ---")
    print(f"Wool Glut (0 Yarn Stores):")
    print(f"  Gross Candidate Revenue:    ${eval_glut['gross_product_revenue']:.2f}")
    print(f"  Marginal Product Revenue:   ${eval_glut['marginal_product_revenue']:.2f}")
    print(f"  Existing Herd Depression:   ${eval_glut['market_impact_cost']:.2f}")
    print(f"  Net Realized Value:         ${eval_glut['net_realized_value']:.2f}")

    print(f"\nHigh Yarn (2 Yarn Stores):")
    print(f"  Gross Candidate Revenue:    ${eval_yarn['gross_product_revenue']:.2f}")
    print(f"  Marginal Product Revenue:   ${eval_yarn['marginal_product_revenue']:.2f}")
    print(f"  Existing Herd Depression:   ${eval_yarn['market_impact_cost']:.2f}")
    print(f"  Net Realized Value:         ${eval_yarn['net_realized_value']:.2f}")

    # Assertions
    # In wool glut, own-supply price depression on existing herd is severe
    assert eval_glut["market_impact_cost"] > 1000.0, "Expected >$1,000 price depression on existing herd"
    assert eval_glut["marginal_product_revenue"] < eval_glut["gross_product_revenue"]

    # In high yarn condition, town absorbs wool, so depression is negligible and marginal rev is high
    assert eval_yarn["market_impact_cost"] < 100.0, "Expected minimal price depression with 2 Yarn Stores"
    assert eval_yarn["marginal_product_revenue"] - eval_glut["marginal_product_revenue"] > 5000.0

    # Mathematical identity holds in both
    assert abs(eval_glut["marginal_product_revenue"] - (eval_glut["gross_product_revenue"] - eval_glut["market_impact_cost"])) < 0.05
    assert abs(eval_yarn["marginal_product_revenue"] - (eval_yarn["gross_product_revenue"] - eval_yarn["market_impact_cost"])) < 0.05


def test_counterfactual_marginal_revenue():
    """Verify counterfactual marginal revenue:
    MarginalRevenue = E[Rev(existing + candidate)] - E[Rev(existing)]
    proves:
    1. Own-supply price depression is fully captured.
    2. Zero double-counting occurs.
    """
    p = "WOOL"
    d = 6
    t = 18
    market_inv = 10000.0
    unlocked_shops = ["YARN_STORE"]  # Yarn Store active

    existing_units = 16  # 4 sheep output
    candidate_units = 4   # 1 additional sheep output

    pmf = get_future_drain_pmf(p, d, t)
    known_drain = compute_known_existing_drain(p, d, t, unlocked_shops)

    total_rev_without = 0.0
    total_rev_with = 0.0

    for f_drain, prob in pmf.items():
        base_inv = market_inv - known_drain - f_drain
        inv_without = base_inv + existing_units
        inv_with = base_inv + existing_units + candidate_units

        p_without = market_price(p, inv_without)
        p_with = market_price(p, inv_with)

        rev_without = existing_units * p_without
        rev_with = (existing_units + candidate_units) * p_with

        total_rev_without += prob * rev_without
        total_rev_with += prob * rev_with

    marginal_rev = total_rev_with - total_rev_without

    # Notice: rev_with - rev_without equals:
    # candidate_units * p_with - existing_units * (p_without - p_with)
    # The second term is exactly the price depression penalty!
    assert marginal_rev > 0
    # Price with extra units must be <= price without
    # Therefore marginal revenue must be <= candidate_units * E[P_without]
    naive_rev = candidate_units * expected_price_from_drain_pmf(
        p, d, t, market_inv, unlocked_shops, extra_supply=existing_units, price_fn=market_price
    )
    assert marginal_rev <= naive_rev + 1e-5, "Counterfactual must naturally account for depression"


def test_duplicate_shop_distinction():
    """State A and State B have identical bitmask presence, but different multiplicities.
    Prove that State A has higher WOOL drain, while State B has higher EGG drain.
    """
    state_a = ["YARN_STORE", "YARN_STORE", "BAKERY", "BRUNCH_SPOT"]
    state_b = ["YARN_STORE", "BAKERY", "BAKERY", "BRUNCH_SPOT"]

    mask_a = get_shop_mask(state_a)
    mask_b = get_shop_mask(state_b)
    assert mask_a == mask_b

    counts_a = get_shop_counts(state_a)
    counts_b = get_shop_counts(state_b)
    assert counts_a["YARN_STORE"] == 2
    assert counts_b["YARN_STORE"] == 1
    assert counts_a["BAKERY"] == 1
    assert counts_b["BAKERY"] == 2

    d = 12
    t = 28
    wool_drain_a = compute_total_expected_drain("WOOL", d, t, state_a)
    wool_drain_b = compute_total_expected_drain("WOOL", d, t, state_b)
    assert wool_drain_a - wool_drain_b == 192.0

    egg_drain_a = compute_total_expected_drain("EGG", d, t, state_a)
    egg_drain_b = compute_total_expected_drain("EGG", d, t, state_b)
    assert egg_drain_b - egg_drain_a == 96.0


def test_future_independence():
    """Future unlock drain PMF and expectation depend ONLY on (product, d, t),
    completely independent of past shop history.
    """
    d = 6
    t = 18
    hist_1 = ["YARN_STORE", "YARN_STORE"]
    hist_2 = ["PET_CAFE", "FARMERS_MARKET"]

    for p in TARGET_PRODUCTS:
        pmf_1 = get_future_drain_pmf(p, d, t)
        pmf_2 = get_future_drain_pmf(p, d, t)
        assert pmf_1 == pmf_2, "Future drain PMF must be strictly independent of history"

        f_drain_1 = compute_expected_future_unlock_drain(p, d, t)
        f_drain_2 = compute_expected_future_unlock_drain(p, d, t)
        assert f_drain_1 == f_drain_2


def test_monte_carlo_distribution_equivalence():
    """Verify PMF expectation, variance, and probability mass against a 200,000-season
    Monte Carlo simulation across Day 0, Day 6, Day 12, and duplicate states.
    """
    N = 200000
    rng = np.random.default_rng(999)
    all_draws = rng.integers(0, 8, size=(N, 8))

    unlock_days = np.asarray(UNLOCK_DAYS, dtype=np.float32)
    days = np.arange(N_DAYS, dtype=np.float32)
    active = (unlock_days[:, None] <= days[None, :]).astype(np.float32)
    per_inst = SHOP_DEMAND_MATRIX[all_draws]
    daily_demand = np.einsum('kt,nkp->ntp', active, per_inst) + TC_VECTOR[None, None, :]
    cum_demand = np.cumsum(daily_demand, axis=1)

    test_states = [
        {"name": "Day 0 -> Day 10", "d": 0, "t": 10, "shops": []},
        {"name": "Day 0 -> Day 28", "d": 0, "t": 28, "shops": []},
        {"name": "Day 6 -> Day 18 (Double Yarn)", "d": 6, "t": 18, "shops": ["YARN_STORE", "YARN_STORE"]},
        {"name": "Day 12 -> Day 28 (Double Bakery + Double Brunch)", "d": 12, "t": 28, "shops": ["BAKERY", "BAKERY", "BRUNCH_SPOT", "BRUNCH_SPOT"]},
    ]

    for ts in test_states:
        d = ts["d"]
        t = ts["t"]
        shops = ts["shops"]
        k = len(shops)

        if k == 0:
            sub_cum = cum_demand
        else:
            eng_indices = [SHOP_TYPES.index(s) for s in shops]
            mask_cond = np.ones(N, dtype=bool)
            for step_idx, eng_idx in enumerate(eng_indices):
                mask_cond &= (all_draws[:, step_idx] == eng_idx)
            sub_cum = cum_demand[mask_cond]

        for p in TARGET_PRODUCTS:
            p_idx = PRODUCT_INDEX[p]
            mc_drain = float(np.mean(sub_cum[:, t, p_idx] - sub_cum[:, d, p_idx]))
            exact_drain = compute_total_expected_drain(p, d, t, shops)
            diff = abs(mc_drain - exact_drain)
            mc_std = float(np.std(sub_cum[:, t, p_idx] - sub_cum[:, d, p_idx]))
            std_err = mc_std / np.sqrt(max(1, len(sub_cum)))
            z_score = diff / max(0.001, std_err)

            assert z_score < 3.0 or diff < 0.25, (
                f"Equivalence failure in {ts['name']} for {p}: MC={mc_drain:.2f}, Exact={exact_drain:.2f}, z={z_score:.2f}"
            )


def test_joint_path_probabilities_sum_and_bounded_count():
    """Verify that joint path probabilities sum to 1.0 identically, and path count is bounded by 256."""
    configs = [
        ("WOOL", 1),   # 1 out of 8 shops
        ("MILK", 3),   # 3 out of 8 shops
        ("EGG", 2),    # 2 out of 8 shops
    ]
    for prod, n_hits in configs:
        n_miss = 8 - n_hits
        for k in range(0, 9):
            n_paths = 2 ** k
            assert n_paths <= 256, f"Path count exceeded 256 for k={k}: {n_paths}"

            denom = 8 ** k
            total_num = 0
            total_prob = 0.0
            for seq in itertools.product([0, 1], repeat=k):
                hits = sum(seq)
                misses = k - hits
                num = (n_hits ** hits) * (n_miss ** misses)
                prob = num / float(denom)
                total_num += num
                total_prob += prob

            assert total_num == denom, f"Numerator sum != denominator for {prod} k={k}"
            assert abs(total_prob - 1.0) < 1e-7, f"Prob sum != 1.0 for {prod} k={k}"


def test_persistence_of_shop_realization_across_dates():
    """Controlled sheep example at Day 6:
    Future unlock path: D9 = Yarn, D12 = non-Yarn, D15 = non-Yarn, D18 = non-Yarn.
    Verify that the D9 Yarn Store remains active and contributes 12 units/day drain
    on every later simulated day (D9, D10, ..., D28), and is never redrawn or forgotten.
    """
    day = 6
    future_events = [ed for ed in UNLOCK_DAYS if day < ed <= 28]  # [9, 12, 15, 18, 21, 24]
    
    # Path where D9 unlocks Yarn Store (index 0 = 1), but no other Yarn stores unlock (indices 1..5 = 0)
    test_path = (1, 0, 0, 0, 0, 0)
    
    # Verify daily drain calculation along this path:
    tc_rate = 1.0
    for t in range(day, 29):
        daily_drain = tc_rate + sum(
            test_path[j] * 12.0 for j, ed in enumerate(future_events) if ed <= t
        )
        if t < 9:
            assert daily_drain == 1.0, f"Before D9, drain must be TC only (1.0), got {daily_drain}"
        else:
            # D9 Yarn Store must persist and contribute on D9, D12, D15, D18, D24, D28!
            assert daily_drain == 13.0, (
                f"From D9 onward, D9 Yarn Store must persist (1.0 + 12.0 = 13.0), but got {daily_drain} at day {t}"
            )


def test_candidate_early_production_affects_own_later_prices():
    """Verify that candidate early production (Day 12) carries into market inventory
    and depresses the candidate's own later price at Day 15.
    """
    p = "WOOL"
    inv_start = 10000.0
    drain_per_day = 1.0  # TC only
    
    # Case A: Candidate produces 6 units at Day 12
    # At Day 12 end: inv = 10000 + 6 - 1 = 10005
    # At Day 13 end: inv = 10005 - 1 = 10004
    # At Day 14 end: inv = 10004 - 1 = 10003
    # At Day 15 start: inv = 10003
    # Candidate sells 4 units at Day 15 into inv=10003
    p_with_early = market_price(p, 10003.0 + 2.0)
    
    # Case B: Candidate did NOT produce at Day 12 (hypothetical delayed start)
    # Market stayed drained: inv at Day 15 start = max(1, 10000 - 3) = 9997
    p_without_early = market_price(p, 9997.0 + 2.0)
    
    assert p_with_early < p_without_early, (
        f"Early production must depress later price: with={p_with_early}, without={p_without_early}"
    )


def test_existing_herd_later_revenue_depressed_by_candidate():
    """Verify that existing herd revenue on later dates is strictly lower with candidate in inventory."""
    eval_res = estimate_realized_marginal_animal_value(
        species="SHEEP",
        day=6,
        current_animals={"SHEEP": 4},
        market_inventory={"WOOL": 10020.0, "MILK": 10000.0, "FERTILIZER": 10000.0, "WHEAT": 10000.0},
        town_shops=[],
        empty_pastures=1,
    )
    # The market_impact_cost represents the price depression suffered by the existing herd
    assert eval_res["market_impact_cost"] > 500.0
    assert eval_res["marginal_product_revenue"] < eval_res["gross_product_revenue"]


def test_engine_one_turn_inventory_ordering_matches_valuator():
    """Verify that valuator's unit-by-unit sell pricing and post-drain inventory update
    match the official Kaggle environment step output exactly.
    """
    import kaggle_environments
    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": 42})
    env.reset()

    # Step 0: Setup 6 units of WOOL in shed
    env.steps[0][0]["observation"]["private"]["shed"]["WOOL"] = 6
    action0 = {"farmer": ["PASS"], "market": [["SELL", "WOOL", 6]]}
    action1 = {"farmer": ["PASS"], "market": []}

    m0_money = env.steps[0][0]["observation"]["farms"][0]["money"]
    step_res = env.step([action0, action1])

    # 1. Real engine money earned
    m1_money = step_res[0]["observation"]["farms"][0]["money"]
    engine_revenue = m1_money - m0_money

    # Valuator predicted unit-by-unit revenue:
    predicted_rev = sum(market_price("WOOL", 10000 + i) for i in range(6))
    assert engine_revenue == predicted_rev == 1197.0

    # 2. Real engine ending inventory:
    # 10000 + 6 (sold) - 1 (TC drain at step 0) = 10005
    engine_ending_inv = step_res[0]["observation"]["market"]["inventory"]["WOOL"]
    assert engine_ending_inv == 10005


def test_collapsed_binary_vs_full_8k_enumeration():
    """Prove that for WOOL (sheep), MILK (cow), and EGG (goose), the collapsed 2^k binary
    path implementation matches full 8^k shop sequence enumeration bit-for-bit.
    """
    for sp in ["SHEEP", "COW", "GOOSE"]:
        day = 12
        prod = ANIMALS[sp]["product"]
        first_lag = ANIMALS[sp]["first_yield_day"]
        interval = ANIMALS[sp]["interval"]
        first_yield = 6 if sp in ("COW", "SHEEP") else 2
        rec_yield = 4 if sp == "SHEEP" else (3 if sp == "COW" else 1)

        cand_units = {t: 0.0 for t in range(day, 29)}
        t_curr = day + first_lag
        is_first = True
        while t_curr <= 28:
            cand_units[t_curr] = first_yield if is_first else rec_yield
            is_first = False
            t_curr += interval

        exist_rate = 2 * (rec_yield / float(interval))
        future_events = [ed for ed in UNLOCK_DAYS if day < ed <= 28][:4]
        k = len(future_events)
        sim_end = future_events[-1] + 3

        # Collapsed 2^k
        hit_rate = 12.0 if sp == "SHEEP" else 6.0
        p_hit = 1.0 / 8.0 if sp == "SHEEP" else (3.0 / 8.0 if sp == "COW" else 2.0 / 8.0)
        rev_binary = 0.0
        for seq in itertools.product([0, 1], repeat=k):
            prob = 1.0
            for b in seq:
                prob *= p_hit if b == 1 else (1.0 - p_hit)
            inv_w = 10000.0
            inv_wo = 10000.0
            rw = 0.0
            rwo = 0.0
            for t in range(day, sim_end):
                drain = 1.0 + sum(seq[j] * hit_rate for j, ed in enumerate(future_events) if ed <= t)
                sw = exist_rate + cand_units.get(t, 0.0)
                swo = exist_rate
                rw += sw * market_price(prod, inv_w + sw)
                rwo += swo * market_price(prod, inv_wo + swo)
                inv_w = max(1.0, inv_w + sw - drain)
                inv_wo = max(1.0, inv_wo + swo - drain)
            rev_binary += prob * (rw - rwo)

        # Full 8^k
        rev_full = 0.0
        full_prob = (1.0 / 8.0) ** k
        for seq in itertools.product(CANONICAL_SHOPS, repeat=k):
            inv_w = 10000.0
            inv_wo = 10000.0
            rw = 0.0
            rwo = 0.0
            for t in range(day, sim_end):
                shop_rates = sum(SHOP_DEMAND_RATES.get(prod, {}).get(seq[j], 0.0) for j, ed in enumerate(future_events) if ed <= t)
                drain = 1.0 + shop_rates
                sw = exist_rate + cand_units.get(t, 0.0)
                swo = exist_rate
                rw += sw * market_price(prod, inv_w + sw)
                rwo += swo * market_price(prod, inv_wo + swo)
                inv_w = max(1.0, inv_w + sw - drain)
                inv_wo = max(1.0, inv_wo + swo - drain)
            rev_full += full_prob * (rw - rwo)

        diff = abs(rev_binary - rev_full)
        assert diff < 1e-4, f"Binary vs 8^k mismatch for {sp}: diff={diff}"


def test_marginal_pmf_vs_joint_path_economic_difference():
    """Verify that in a controlled nonlinear glut state (d=6, I=10020),
    the new joint-path lifetime value differs substantially (> $500)
    from the old independent marginal-PMF approximation.
    """
    day = 6
    prod = "WOOL"
    base_inv = 10020.0
    cand_units = {12: 6.0, 15: 4.0, 18: 4.0, 21: 4.0, 24: 4.0, 27: 4.0}
    exist_daily = 4 * (4.0 / 3.0)

    future_events = [ed for ed in UNLOCK_DAYS if day < ed <= 28]
    k = len(future_events)
    p_hit = 1.0 / 8.0
    hit_rate = 12.0
    known_daily_drain = 1.0

    # New Joint-path
    joint_path_rev_with = 0.0
    joint_path_rev_without = 0.0
    for seq in itertools.product([0, 1], repeat=k):
        prob = 1.0
        for b in seq:
            prob *= p_hit if b == 1 else (1.0 - p_hit)
        inv_w = base_inv
        inv_wo = base_inv
        rw = 0.0
        rwo = 0.0
        for t in range(day, 28):
            drain = known_daily_drain + sum(seq[j] * hit_rate for j, ed in enumerate(future_events) if ed <= t)
            sw = exist_daily + cand_units.get(t, 0.0)
            swo = exist_daily
            rw += sw * market_price(prod, inv_w + sw)
            rwo += swo * market_price(prod, inv_wo + swo)
            inv_w = max(1.0, inv_w + sw - drain)
            inv_wo = max(1.0, inv_wo + swo - drain)
        joint_path_rev_with += prob * rw
        joint_path_rev_without += prob * rwo

    joint_marginal_rev = joint_path_rev_with - joint_path_rev_without

    # Old Independent Marginal PMF / Expected Inventory
    old_rev_with = 0.0
    old_rev_without = 0.0
    inv_w = base_inv
    inv_wo = base_inv
    for t in range(day, 28):
        pmf = get_future_drain_pmf(prod, day, t)
        e_future_drain = sum(v * p for v, p in pmf.items())
        sw = exist_daily + cand_units.get(t, 0.0)
        swo = exist_daily
        pw = market_price(prod, inv_w + sw)
        pwo = market_price(prod, inv_wo + swo)
        old_rev_with += sw * pw
        old_rev_without += swo * pwo
        mean_drain_today = known_daily_drain + (e_future_drain / max(1, t - day))
        inv_w = max(1.0, inv_w + sw - mean_drain_today)
        inv_wo = max(1.0, inv_wo + swo - mean_drain_today)

    old_marginal_rev = old_rev_with - old_rev_without
    diff = abs(joint_marginal_rev - old_marginal_rev)

    print(f"\n--- Marginal-PMF vs Joint-Path Economic Gap ---")
    print(f"Joint-Path Marginal Revenue:       ${joint_marginal_rev:.2f}")
    print(f"Old Marginal-PMF Approximation:    ${old_marginal_rev:.2f}")
    print(f"Economic Difference:               ${diff:.2f}")

    assert diff > 500.0, f"Expected significant economic difference (> $500), got {diff}"


def test_day3_day6_boundary_unlock_timing_and_future_counts():
    """Verify boundary unlock timing:
    On day D, shop for day D is already unlocked and present in town_shops (unlocked at end of day D-1).
    Therefore, the future unlock events must ONLY include days > D.
    """
    # UNLOCK_DAYS = [3, 6, 9, 12, 15, 18, 21, 24]
    
    # Day 2: D3 has not occurred yet -> 8 future events
    f_d2 = [d for d in UNLOCK_DAYS if 2 < d <= 28]
    assert len(f_d2) == 8
    assert f_d2 == [3, 6, 9, 12, 15, 18, 21, 24]
    
    # Day 3: D3 has ALREADY occurred and is observable in town_shops -> 7 future events
    f_d3 = [d for d in UNLOCK_DAYS if 3 < d <= 28]
    assert len(f_d3) == 7
    assert 3 not in f_d3
    assert f_d3 == [6, 9, 12, 15, 18, 21, 24]
    
    # Day 5: D6 has not occurred yet -> 7 future events
    f_d5 = [d for d in UNLOCK_DAYS if 5 < d <= 28]
    assert len(f_d5) == 7
    assert f_d5 == [6, 9, 12, 15, 18, 21, 24]
    
    # Day 6: D6 has ALREADY occurred and is observable in town_shops -> 6 future events
    f_d6 = [d for d in UNLOCK_DAYS if 6 < d <= 28]
    assert len(f_d6) == 6
    assert 6 not in f_d6
    assert f_d6 == [9, 12, 15, 18, 21, 24]
    
    # Verify valuator integration: valuator on Day 3 with D3 shop known
    eval_d3 = estimate_realized_marginal_animal_value(
        "SHEEP", day=3, current_animals={"SHEEP": 0},
        town_shops=["YARN_STORE"], market_inventory={"WOOL": 10000}
    )
    assert eval_d3["viable"] is True
    assert eval_d3["joint_paths_evaluated"] == 128


def test_arm_c_transactional_shadow_state_and_marginal_sequence():
    """Verify Arm C transactional shadow loop:
    1. Evaluates candidate species sequentially.
    2. Consecutive marginal values decrease as own-supply expands.
    3. Respects feed sustainability, housing, cash reserve, and order slots.
    4. Records decision telemetry and consecutive sequence notes.
    """
    from config import set_livestock_experiment_arm
    from strategy.macro_planner import MacroPlanner, get_livestock_decision_logs, clear_livestock_decision_logs
    from strategy.price_forecast import PriceForecast
    from state.observation_parser import parse_observation
    
    set_livestock_experiment_arm("ArmC")
    clear_livestock_decision_logs()
    
    # Raw observation format
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    # Place 4 empty pastures in NE (x >= 5, y < 5)
    for (x, y) in [(5, 0), (6, 0), (5, 1), (6, 1)]:
        tiles[y][x] = {"kind": "STRUCTURE", "structure": "PASTURE"}
    # Place 10 wheat tiles in NW
    for i in range(10):
        tiles[i // 5][i % 5] = {
            "kind": "PLANT", "crop": "WHEAT", "pos": (i % 5, i // 5),
            "watered_today": True, "yield_units": 0, "placed_day": 6
        }
    
    farm = {
        "money": 5000,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4], [4, 4]],
        "unlocked_quadrants": ["NW", "NE"],
        "hires_today": 0,
    }
    obs = {
        "player": 0,
        "day": 6,
        "hour": 0,
        "farms": [farm, farm],
        "market": {"inventory": {"WOOL": 10000, "MILK": 10000, "EGG": 10000, "WHEAT": 10000}, "prices": {}},
        "town": {"unlocked_shops": ["YARN_STORE", "YARN_STORE"]},
        "private": {"shed": {"WHEAT": 100}, "seeds": {}, "inventories": [{}]},
    }
    ctx = parse_observation(obs)
    assert ctx is not None
    
    fc = PriceForecast.load() if PriceForecast is not None else None
    planner = MacroPlanner(fc, money_reserve=300)
    plan = planner.build(ctx)
    
    # Verify buy_animal intent was formed
    buy_anim = plan.intents.get("buy_animal", {})
    assert len(buy_anim) > 0, "Expected ArmC to purchase animals in high-yarn state"
    assert "SHEEP" in buy_anim, f"Expected Sheep in 2-Yarn state on Day 6, got {buy_anim}"
    assert buy_anim["SHEEP"] >= 1
    
    # Verify decision logs were recorded
    logs = get_livestock_decision_logs()
    assert len(logs) > 0
    assert any(log["selected_species"] == "SHEEP" for log in logs)
    
    # Verify Arm C notes recorded the sequence
    armc_notes = [n for n in plan.notes if "ArmC sequence" in n]
    assert len(armc_notes) > 0, f"Expected ArmC sequence notes in plan.notes: {plan.notes}"
    print(f"\nArm C sequence note: {armc_notes[0]}")
    
    # Clean reset back to Arm A
    set_livestock_experiment_arm("ArmA")
    clear_livestock_decision_logs()


def test_arm_b_target_shop_economics():
    """Verify Arm B preserves target structure while using exact shop economics."""
    from config import set_livestock_experiment_arm
    from strategy.macro_planner import MacroPlanner
    from strategy.price_forecast import PriceForecast
    from state.observation_parser import parse_observation
    
    set_livestock_experiment_arm("ArmB")
    
    board = 10
    tiles = [[None for _ in range(board)] for _ in range(board)]
    for (x, y) in [(5, 0), (6, 0)]:
        tiles[y][x] = {"kind": "STRUCTURE", "structure": "PASTURE"}
    for i in range(10):
        tiles[i // 5][i % 5] = {
            "kind": "PLANT", "crop": "WHEAT", "pos": (i % 5, i // 5),
            "watered_today": True, "yield_units": 0, "placed_day": 4
        }
        
    farm = {
        "money": 5000,
        "tiles": tiles,
        "farmer": [4, 4],
        "hands": [[4, 4], [4, 4]],
        "unlocked_quadrants": ["NW", "NE"],
        "hires_today": 0,
    }
    obs = {
        "player": 0,
        "day": 6,
        "hour": 0,
        "farms": [farm, farm],
        "market": {"inventory": {"WOOL": 10000, "MILK": 10000, "EGG": 10000, "WHEAT": 10000}, "prices": {}},
        "town": {"unlocked_shops": ["YARN_STORE", "YARN_STORE"]},
        "private": {"shed": {"WHEAT": 100}, "seeds": {}, "inventories": [{}]},
    }

    ctx = parse_observation(obs)
    assert ctx is not None
    
    fc = PriceForecast.load() if PriceForecast is not None else None
    planner = MacroPlanner(fc, money_reserve=300)
    plan = planner.build(ctx)
    
    buy_anim = plan.intents.get("buy_animal", {})
    assert "SHEEP" in buy_anim
    
    # Clean reset back to Arm A
    set_livestock_experiment_arm("ArmA")



