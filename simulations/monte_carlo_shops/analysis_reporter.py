"""Module 5: Analysis of Monte Carlo simulation results.

Produces:
  A. Shop unlock distribution statistics
  B. Per-product demand statistics (+ town-center vs shop breakdown)
  C. Price trajectory statistics and threshold crossings
  D. Hinge-trigger probability analysis (carrot / tomato / egg)
  E. Conditional day-3 shop-response strategies
  F. Product ranking / tier list by risk-adjusted ROI
  G. Cross-product price correlation matrices

All economics follow `new rules.md`: seed costs, yield/tile/day, growth times,
animal outputs and daily wheat feeding.
"""
import json
import math
from itertools import combinations

import numpy as np

from monte_carlo_runner import (
    ANIMAL_PRODUCTS,
    ANIMAL_PURCHASE_COST,
    CROPS,
    N_DAYS,
    SEASON_COST_PER_TILE,
    SEASON_FEED_COST,
    SEASON_OUTPUT_PER_ANIMAL,
    SEASON_YIELD_PER_TILE,
    TRADEABLE,
)
from price_function import MARKET_PARAMS
from shop_unlock_simulator import ShopUnlockSimulator
from town_demand_engine import (
    N_DAYS as DAYS_N,
    PRODUCTS,
    SHOP_DEMAND_MATRIX,
    SHOP_DEMANDS,
    SHOP_TYPES,
    TOWN_CENTER_DAILY,
)

P_IDX = {p: i for i, p in enumerate(PRODUCTS)}
SHOP_IDX = {s: i for i, s in enumerate(SHOP_TYPES)}
HINGE_PRODUCTS = ["CARROT", "TOMATO", "EGG"]
HINGE_DRIVERS = {
    "CARROT": ["PET_CAFE", "FARMERS_MARKET"],
    "TOMATO": ["PIZZA_SHOP", "FARMERS_MARKET"],
    "EGG": ["BAKERY", "BRUNCH_SPOT"],
}
CHECKPOINT_DAYS = [5, 10, 15, 20, 25, 29]


def save_json(path, obj):
    def _native(o):
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        raise TypeError(f"not JSON serializable: {type(o)}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=_native)


# ---------------------------------------------------------------------------
# A. Shop unlock distribution
# ---------------------------------------------------------------------------
def unlock_analysis(result):
    draws = result.draws
    n = result.n_simulations
    counts = np.stack([(draws == k).sum(axis=1) for k in range(len(SHOP_TYPES))], axis=1)

    # Theoretical binomial(8, 1/8) references — draws are iid uniform, so the
    # ONLY dependence between per-type counts is the fixed total of 8.
    p = 1.0 / len(SHOP_TYPES)
    p0 = (1 - p) ** 8
    p1 = 8 * p * (1 - p) ** 7
    theo_ge2 = 1 - p0 - p1
    p2 = math.comb(8, 2) * p**2 * (1 - p) ** 6
    theo_ge3 = theo_ge2 - p2

    per_type = {}
    for k, s in enumerate(SHOP_TYPES):
        per_type[s] = {
            "instance_frequency": float(counts[:, k].sum() / (n * 8)),
            "mean_instances_per_season": float(counts[:, k].mean()),
            "std_instances_per_season": float(counts[:, k].std()),
            "p_count_ge_2": float((counts[:, k] >= 2).mean()),
            "p_count_ge_3": float((counts[:, k] >= 3).mean()),
            "p_theoretical_ge_2": theo_ge2,
            "p_theoretical_ge_3": theo_ge3,
        }
    return {
        "note": ("Individual draws are iid uniform(1/8). Per-type seasonal counts "
                 "are only weakly negatively correlated because the total number "
                 "of unlocks is fixed at 8."),
        "first_shop_distribution": {
            SHOP_TYPES[k]: float((draws[:, 0] == k).mean()) for k in range(len(SHOP_TYPES))
        },
        "instance_frequency_overall": float((counts.sum(axis=0) / (n * 8)).mean()),
        "per_type": per_type,
        "count_correlation_matrix": np.corrcoef(counts, rowvar=False),
    }


# ---------------------------------------------------------------------------
# B. Demand statistics
# ---------------------------------------------------------------------------
def demand_statistics(result):
    totals = result.daily_demand.sum(axis=1)  # (n, 9)
    qs = [5, 25, 50, 75, 95]
    perc = np.percentile(totals, qs, axis=0)

    # Expected demand attribution: town center vs each shop type (analytic).
    inst_onehot = (result.draws[:, :, None] == np.arange(len(SHOP_TYPES))[None, None, :])
    M = inst_onehot.astype(np.float64).mean(axis=0)              # (instance, type)
    unlock_days = np.asarray(ShopUnlockSimulator.UNLOCK_DAYS, dtype=np.float64)
    active = (unlock_days[:, None] <= np.arange(DAYS_N)[None, :]).astype(np.float64)
    exp_active_days = np.einsum("ks,kt->st", M, active).sum(axis=1)  # (type,)
    tc_total = np.array([TOWN_CENTER_DAILY.get(p, 0) * DAYS_N for p in PRODUCTS])

    per_product = {}
    for i, prod in enumerate(PRODUCTS):
        shop_total = exp_active_days @ SHOP_DEMAND_MATRIX[:, i]
        grand = tc_total[i] + shop_total
        breakdown = {"TOWN_CENTER": float(tc_total[i] / grand)} if grand > 0 else {}
        for s_idx, s_name in enumerate(SHOP_TYPES):
            share = exp_active_days[s_idx] * SHOP_DEMAND_MATRIX[s_idx, i] / grand if grand else 0.0
            if share > 0:
                breakdown[s_name] = float(share)
        per_product[prod] = {
            "mean_total_demand": float(totals[:, i].mean()),
            "std_total_demand": float(totals[:, i].std()),
            "p5": float(perc[0, i]), "p25": float(perc[1, i]),
            "p50": float(perc[2, i]), "p75": float(perc[3, i]),
            "p95": float(perc[4, i]),
            "max_observed_demand": float(totals[:, i].max()),
            "demand_share_breakdown": breakdown,
        }
    return per_product


def median_daily_demand_matrix(result):
    """(products, days) median daily town demand across simulations."""
    return np.median(result.daily_demand, axis=0).T


# ---------------------------------------------------------------------------
# C. Price statistics
# ---------------------------------------------------------------------------
def price_statistics(result):
    prices = result.prices.astype(np.float64)
    qs = [5, 25, 50, 75, 95]
    perc = np.percentile(prices, qs, axis=0)          # (5, 30, 9)
    mean = prices.mean(axis=0)
    med = perc[2]

    def first_day_above(vec, threshold):
        idx = np.nonzero(vec > threshold)[0]
        return int(idx[0]) if idx.size else None

    per_product = {}
    for i, prod in enumerate(PRODUCTS):
        base = MARKET_PARAMS[prod]["base"]
        per_product[prod] = {
            "base": base,
            "daily_stats": {
                "mean": mean[:, i], "p5": perc[0, :, i], "p25": perc[1, :, i],
                "median": med[:, i], "p75": perc[3, :, i], "p95": perc[4, :, i],
            },
            "day_median_exceeds_1_5x_base": first_day_above(med[:, i], 1.5 * base),
            "day_median_exceeds_2x_base": first_day_above(med[:, i], 2.0 * base),
            "p_price_exceeds_2x_base_anytime": float((prices[:, :, i] > 2 * base).any(axis=1).mean()),
            "p_price_hits_floor_anytime": float((prices[:, :, i] <= 1).any(axis=1).mean()),
        }
    return per_product


# ---------------------------------------------------------------------------
# D. Hinge-trigger analysis
# ---------------------------------------------------------------------------
def _conditional_trig_probs(triggered, c1, c2, name1, name2):
    """Human-readable conditions evaluated against driver-shop instance counts."""
    candidates = [
        (f"{name1} >= 1", c1 >= 1),
        (f"{name2} >= 1", c2 >= 1),
        (f"{name1} >= 2", c1 >= 2),
        (f"{name1}+{name2} total >= 3", (c1 + c2) >= 3),
        (f"{name2} >= 2", c2 >= 2),
        (f"{name1} >= 3", c1 >= 3),
        (f"{name1}+{name2} total >= 4", (c1 + c2) >= 4),
    ]
    out = []
    for label, mask in candidates:
        out.append({"condition": label, "p_trigger_given_condition": float(triggered[mask].mean())})
    return out


def hinge_analysis(result):
    inv = result.inventory
    draws = result.draws
    out = {}
    for prod in HINGE_PRODUCTS:
        params = MARKET_PARAMS[prod]
        knee = params["I0"] - params["T"]
        i = P_IDX[prod]
        below = inv[:, :, i] < knee                      # (n, 30)
        triggered = below.any(axis=1)

        p_by_day = {}
        for d in CHECKPOINT_DAYS:
            p_by_day[f"by_day_{d}"] = float(below[:, : d + 1].any(axis=1).mean())

        cond_price = {}
        for day in (15, 29):
            pr = result.prices[:, day, i].astype(np.float64)
            cond_price[f"day_{day}"] = {
                "median_if_triggered": float(np.median(pr[triggered])) if triggered.any() else None,
                "median_if_not_triggered": float(np.median(pr[~triggered])) if (~triggered).any() else None,
                "mean_if_triggered": float(pr[triggered].mean()) if triggered.any() else None,
            }

        name1, name2 = HINGE_DRIVERS[prod]
        c1 = (draws == SHOP_IDX[name1]).sum(axis=1)
        c2 = (draws == SHOP_IDX[name2]).sum(axis=1)
        cond_table = _conditional_trig_probs(triggered, c1, c2, name1, name2)
        feasible = [c for c in cond_table if c["p_trigger_given_condition"] >= 0.75]
        best_combo = (
            feasible[0]["condition"] if feasible
            else max(cond_table, key=lambda c: c["p_trigger_given_condition"])["condition"]
        )

        out[prod] = {
            "knee_inventory": knee,
            "driver_shops": [name1, name2],
            "p_hinge_triggered_anytime": float(triggered.mean()),
            "p_triggered_by_checkpoint": p_by_day,
            "conditional_prices": cond_price,
            "conditional_trigger_table": cond_table,
            "best_shop_combo": best_combo,
        }
    return out


# ---------------------------------------------------------------------------
# Season profit helpers (rules-based economics)
# ---------------------------------------------------------------------------
def season_profit(product, mean_sale_price):
    """Expected season profit for ONE tile (crop) or ONE animal."""
    if product in SEASON_YIELD_PER_TILE:
        return SEASON_YIELD_PER_TILE[product] * mean_sale_price - SEASON_COST_PER_TILE[product]
    if product in SEASON_OUTPUT_PER_ANIMAL:
        return (SEASON_OUTPUT_PER_ANIMAL[product] * mean_sale_price
                - ANIMAL_PURCHASE_COST[product] - SEASON_FEED_COST)
    return 0.0


def season_risk(product, std_sale_price):
    if product in SEASON_YIELD_PER_TILE:
        return SEASON_YIELD_PER_TILE[product] * std_sale_price
    if product in SEASON_OUTPUT_PER_ANIMAL:
        return SEASON_OUTPUT_PER_ANIMAL[product] * std_sale_price
    return 0.0


# ---------------------------------------------------------------------------
# F. Product ranking / tier list
# ---------------------------------------------------------------------------
def product_ranking(result):
    prices = result.prices
    window = slice(10, 30)  # sale-time window: mid-season onward
    rows = {}
    RISKLESS_SHARPE = 99.99  # no shop consumes this product -> deterministic
                             # demand; zero price variance is a feature, not a tie
    for prod in TRADEABLE:
        i = P_IDX[prod]
        per_sim_mean_price = prices[:, window, i].astype(np.float64).mean(axis=1)
        e_price = float(per_sim_mean_price.mean())
        profit = season_profit(prod, e_price)
        risk = season_risk(prod, float(per_sim_mean_price.std()))
        daily = profit / DAYS_N
        daily_risk = risk / DAYS_N
        if daily_risk > 0:
            sharpe = daily / daily_risk
        else:
            sharpe = RISKLESS_SHARPE
        rows[prod] = {
            "expected_sale_price_window_d10_29": round(e_price, 2),
            "season_profit_per_tile": round(profit, 2),
            "revenue_per_tile_per_day": round(daily, 3),
            "risk_std_revenue_per_tile_per_day": round(daily_risk, 3),
            "sharpe": round(sharpe, 3),
            "demand_side_riskless": daily_risk <= 0,
        }
    order = sorted(rows, key=lambda p_: rows[p_]["sharpe"], reverse=True)
    tiers = {"S": order[:2], "A": order[2:4], "B": order[4:6], "C": order[6:]}
    return {
        "metrics": rows,
        "tier_list": tiers,
        "ranked_by_sharpe": order,
        "note": ("Demand-side risk only (town consumption). Products no shop "
                 "consumes (e.g. MELON) have a deterministic drain path, so zero "
                 "price variance ranks them top here; opponent overproduction "
                 "risk (sq/linear glut curves) is NOT captured for them."),
    }


# ---------------------------------------------------------------------------
# E. Conditional day-3 strategy
# ---------------------------------------------------------------------------
def conditional_day3_analysis(result):
    prices = result.prices
    first = result.draws[:, 0]
    overall_med = np.median(prices.astype(np.float64), axis=0)   # (30, 9)
    win = slice(5, 30)

    def profit_under(med_path, prod):
        return season_profit(prod, float(med_path[win, P_IDX[prod]].mean()))

    all_products = TRADEABLE
    fixed_best = max(all_products, key=lambda pp: profit_under(overall_med, pp))
    fixed_profit = profit_under(overall_med, fixed_best)

    responses = {}
    for s in SHOP_TYPES:
        mask = first == SHOP_IDX[s]
        if mask.sum() < 20:
            continue
        cond_med = np.median(prices[mask].astype(np.float64), axis=0)
        demanded = sorted(SHOP_DEMANDS[s], key=lambda pp: -SEASON_YIELD_PER_TILE.get(
            pp, SEASON_OUTPUT_PER_ANIMAL.get(pp, 0)))
        boosts = {}
        for pp in demanded:
            i = P_IDX[pp]
            base_v = float(overall_med[win, i].mean())
            boosts[pp] = round(float(cond_med[win, i].mean()) / base_v, 3) if base_v > 0 else 1.0
        adaptive_best = max(all_products, key=lambda pp: profit_under(cond_med, pp))
        adaptive_profit = profit_under(cond_med, adaptive_best)
        invest_in = sorted(demanded, key=lambda pp: -(boosts[pp] *
                          SEASON_YIELD_PER_TILE.get(pp, SEASON_OUTPUT_PER_ANIMAL.get(pp, 0))))[:2]
        responses[s] = {
            "p_first_shop": float(mask.mean()),
            "invest_in": invest_in,
            "expected_price_boost": boosts,
            "adaptive_pick": adaptive_best,
            "adaptive_vs_fixed_profit_per_tile": round(adaptive_profit - fixed_profit, 2),
        }

    return {
        "fixed_strategy_pick": fixed_best,
        "fixed_profit_per_tile": round(fixed_profit, 2),
        "responses": responses,
    }


# ---------------------------------------------------------------------------
# Portfolio optimization (choose 3 crops for 25 tiles)
# ---------------------------------------------------------------------------
def portfolio_optimization(result):
    prices_sum = result.prices.astype(np.float64).sum(axis=1)     # (n, 9)
    n = result.n_simulations
    allocations = ([9, 8, 8])
    combos = []
    for combo in combinations(CROPS, 3):
        rev = np.zeros(n)
        cost = 0.0
        for tiles, prod in zip(allocations, combo):
            daily_yield = SEASON_YIELD_PER_TILE[prod] / DAYS_N
            rev += tiles * daily_yield * prices_sum[:, P_IDX[prod]]
            cost += tiles * SEASON_COST_PER_TILE[prod]
        rev -= cost
        combos.append({
            "crops": list(combo),
            "tiles": list(allocations),
            "mean": float(rev.mean()),
            "std": float(rev.std()),
            "sharpe": float(rev.mean() / rev.std()) if rev.std() > 0 else 0.0,
        })

    med_mean = float(np.median([c["mean"] for c in combos]))
    low_risk = min((c for c in combos if c["mean"] >= med_mean), key=lambda c: c["std"])
    high_reward = max(combos, key=lambda c: c["mean"])

    animal_rows = {}
    for prod in ANIMAL_PRODUCTS:
        i = P_IDX[prod]
        rev = (SEASON_OUTPUT_PER_ANIMAL[prod] / DAYS_N) * prices_sum[:, i] \
            - ANIMAL_PURCHASE_COST[prod] - SEASON_FEED_COST
        animal_rows[prod] = {
            "mean_net_per_animal": round(float(rev.mean()), 2),
            "std_net_per_animal": round(float(rev.std()), 2),
            "sharpe": round(float(rev.mean() / rev.std()), 3) if rev.std() > 0 else 0.0,
        }
    low_risk_animal = max(animal_rows, key=lambda p_: animal_rows[p_]["sharpe"])
    high_reward_animal = max(animal_rows, key=lambda p_: animal_rows[p_]["mean_net_per_animal"])

    return {
        "crop_combos": combos,
        "low_risk": low_risk,
        "high_risk_high_reward": high_reward,
        "animal_economics_per_animal": animal_rows,
        "low_risk_animal": low_risk_animal,
        "high_reward_animal": high_reward_animal,
        "assumptions": {
            "farm": "1 starting quadrant = 25 tiles",
            "costs": "seed x plantings; animals: purchase + 1 wheat/day feed at $25",
            "fertilizer": "not used; free animal fertilizer unmodeled",
        },
    }


# ---------------------------------------------------------------------------
# G. Correlation analysis
# ---------------------------------------------------------------------------
def correlation_analysis(result):
    out = {}
    cols = [P_IDX[p_] for p_ in TRADEABLE]
    for day in (15, 25):
        X = result.prices[:, day, cols].astype(np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            C = np.corrcoef(X, rowvar=False)
        # A constant price column (zero variance) yields NaN correlations;
        # replace with 0 so downstream JSON/plots stay valid.
        C = np.nan_to_num(C, nan=0.0)
        np.fill_diagonal(C, 1.0)
        pairs = []
        for a in range(len(TRADEABLE)):
            for b in range(a + 1, len(TRADEABLE)):
                pairs.append((TRADEABLE[a], TRADEABLE[b], float(C[a, b])))
        strongest_pos = max(pairs, key=lambda t: t[2])
        strongest_neg = min(pairs, key=lambda t: t[2])
        out[f"day_{day}"] = {
            "products": TRADEABLE,
            "matrix": C,
            "strongest_positive_pair": strongest_pos,
            "strongest_negative_pair": strongest_neg,
        }
    return out


# ---------------------------------------------------------------------------
# Timing / holding heuristic (key question 6)
# ---------------------------------------------------------------------------
def timing_guidance(result):
    guidance = {}
    med = np.median(result.prices.astype(np.float64), axis=0)  # (30, 9)
    early_x = np.arange(0, 13)
    late_x = np.arange(15, 30)
    for prod in TRADEABLE:
        i = P_IDX[prod]
        early = med[:13, i]
        late = med[15:, i]
        early_slope_pct = float(np.polyfit(early_x, early, 1)[0] / max(early[0], 1e-9))
        late_slope_pct = float(np.polyfit(late_x, late, 1)[0] / max(late.mean(), 1e-9))
        if early_slope_pct > 0.005:
            advice = "HOLD early — prices rise fast while shops ramp up; sell into the peak."
        elif early_slope_pct < -0.005:
            advice = "SELL immediately — prices decay from day 0."
        else:
            advice = "Prices near-flat early; sell steadily, watch shop unlocks for pivots."
        guidance[prod] = {
            "early_slope_pct_per_day": round(early_slope_pct, 5),
            "late_slope_pct_per_day": round(late_slope_pct, 5),
            "advice": advice,
        }
    return guidance


# ---------------------------------------------------------------------------
# Scenario D sweep
# ---------------------------------------------------------------------------
def sweep_level_stats(result):
    """Per-product aggregate stats for ONE production level."""
    prices = result.prices
    per_product = {}
    for prod in TRADEABLE:
        i = P_IDX[prod]
        base = MARKET_PARAMS[prod]["base"]
        per_product[prod] = {
            "median_price_day15": float(np.median(prices[:, 15, i])),
            "median_price_day25": float(np.median(prices[:, 25, i])),
            "p_below_half_base_day25": float((prices[:, 25, i] < 0.5 * base).mean()),
            "p_floor_day25": float((prices[:, 25, i] <= 1).mean()),
        }
    return per_product


def sweep_analysis(sweep_results):
    """sweep_results: {multiplier: ScenarioResult}"""
    return {f"{int(round(m * 100))}%": sweep_level_stats(res)
            for m, res in sorted(sweep_results.items())}


def find_crossing_levels(sweep_levels, key_fn):
    """First production level (ascending %) where key_fn(per_product_stats) is True."""
    for level_name, per_product in sorted(sweep_levels.items(), key=lambda kv: int(kv[0][:-1])):
        hits = [p for p in TRADEABLE if key_fn(per_product[p])]
        if hits:
            return level_name, hits
    return None, []


# ---------------------------------------------------------------------------
# Full summary assembly
# ---------------------------------------------------------------------------
def generate_summary(town_result, single_result, two_result, sweep_levels):
    return {
        "meta": {
            "n_simulations": town_result.n_simulations,
            "products": PRODUCTS,
            "scenarios": ["town_only", "single_player", "two_players"],
        },
        "A_shop_unlock_distribution": unlock_analysis(town_result),
        "B_demand_statistics": demand_statistics(town_result),
        "C_price_statistics": {
            "town_only": price_statistics(town_result),
            "single_player": price_statistics(single_result),
            "two_players": price_statistics(two_result),
        },
        "D_hinge_analysis": hinge_analysis(town_result),
        "E_conditional_day3": conditional_day3_analysis(single_result),
        "F_product_ranking": product_ranking(single_result),
        "G_correlations": correlation_analysis(single_result),
        "D_scenario_sweep": sweep_levels,
        "timing_guidance": timing_guidance(single_result),
    }


def build_strategy_recommendations(summary, single_result):
    ranking = summary["F_product_ranking"]
    hinge = summary["D_hinge_analysis"]
    day3 = summary["E_conditional_day3"]
    port = portfolio_optimization(single_result)

    hinge_alerts = {}
    for prod, h in hinge.items():
        trig_med = h["conditional_prices"]["day_15"]["median_if_triggered"]
        hinge_alerts[prod] = {
            "trigger_probability": h["p_hinge_triggered_anytime"],
            "expected_price_if_triggered": trig_med,
            "best_shop_combo": h["best_shop_combo"],
            "p_by_day_15": h["p_triggered_by_checkpoint"]["by_day_15"],
        }

    day3_responses = {}
    for shop, r in day3["responses"].items():
        day3_responses[shop] = {
            "invest_in": r["invest_in"],
            "expected_price_boost": r["expected_price_boost"],
            "adaptive_pick": r["adaptive_pick"],
            "adaptive_gain_per_tile": r["adaptive_vs_fixed_profit_per_tile"],
        }

    animal_econ = port["animal_economics_per_animal"]

    def _animal_rev(animal_counts):
        rev = 0.0
        for name, count in animal_counts.items():
            prod = {"goose": "EGG", "cow": "MILK", "sheep": "WOOL"}[name]
            rev += animal_econ[prod]["mean_net_per_animal"] * count
        return max(rev, 0.0)

    low_animals = {"goose": 2}
    high_animals = {"goose": 3, "cow": 2, "sheep": 2}

    return {
        "tier_list": ranking["tier_list"],
        "ranking_metrics": ranking["metrics"],
        "day3_shop_responses": day3_responses,
        "hinge_alerts": hinge_alerts,
        "optimal_portfolio": {
            "low_risk": {
                "crops": dict(zip(port["low_risk"]["crops"], port["low_risk"]["tiles"])),
                "animals": low_animals,
                "expected_revenue": round(port["low_risk"]["mean"] + _animal_rev(low_animals), 0),
                "std_dev": round(port["low_risk"]["std"], 0),
            },
            "high_risk_high_reward": {
                "crops": dict(zip(port["high_risk_high_reward"]["crops"],
                                  port["high_risk_high_reward"]["tiles"])),
                "animals": high_animals,
                "expected_revenue": round(port["high_risk_high_reward"]["mean"]
                                          + _animal_rev(high_animals), 0),
                "std_dev": round(port["high_risk_high_reward"]["std"], 0),
            },
            "animal_economics_per_animal": animal_econ,
            "assumptions": port["assumptions"],
        },
        "timing_guidance": summary["timing_guidance"],
    }


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------
def write_price_trajectories_csv(path, scenarios):
    """scenarios: {name: ScenarioResult}"""
    header = "scenario,product,day,mean,p5,p25,median,p75,p95"
    lines = [header]
    for name, res in scenarios.items():
        stats = price_statistics(res)
        for prod in PRODUCTS:
            d = stats[prod]["daily_stats"]
            for day in range(N_DAYS):
                lines.append(
                    f"{name},{prod},{day},{d['mean'][day]:.2f},{d['p5'][day]:.2f},"
                    f"{d['p25'][day]:.2f},{d['median'][day]:.2f},{d['p75'][day]:.2f},{d['p95'][day]:.2f}"
                )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_demand_distributions_csv(path, town_result):
    stats = demand_statistics(town_result)
    header = ("product,mean,std,p5,p25,p50,p75,p95,max,"
              "top_demand_source,top_source_share")
    lines = [header]
    for prod in PRODUCTS:
        s = stats[prod]
        b = s["demand_share_breakdown"]
        top = max(b, key=b.get) if b else "NONE"
        lines.append(
            f"{prod},{s['mean_total_demand']:.1f},{s['std_total_demand']:.1f},"
            f"{s['p5']:.0f},{s['p25']:.0f},{s['p50']:.0f},{s['p75']:.0f},"
            f"{s['p95']:.0f},{s['max_observed_demand']:.0f},{top},{b.get(top, 0):.3f}"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
