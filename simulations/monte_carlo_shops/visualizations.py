"""All plotting code. Saves PNGs to <output>/plots/ using the Agg backend."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from analysis_reporter import CHECKPOINT_DAYS, product_ranking  # noqa: E402
from monte_carlo_runner import (  # noqa: E402
    ANIMAL_PURCHASE_COST,
    N_DAYS,
    SEASON_COST_PER_TILE,
    SEASON_FEED_COST,
    SEASON_OUTPUT_PER_ANIMAL,
    SEASON_YIELD_PER_TILE,
    TRADEABLE,
)
from price_function import compute_price, MARKET_PARAMS  # noqa: E402
from town_demand_engine import PRODUCTS, SHOP_DEMAND_MATRIX, SHOP_TYPES, TC_VECTOR  # noqa: E402

P_IDX = {p: i for i, p in enumerate(PRODUCTS)}
TIER_COLORS = {"S": "#d62728", "A": "#ff7f0e", "B": "#1f77b4", "C": "#7f7f7f"}
ANIMAL_OF_NAME = {"goose": "EGG", "cow": "MILK", "sheep": "WOOL"}
ANIMAL_DAILY_RATE = {"goose": 1.0, "cow": 0.5, "sheep": 1.0 / 3.0}


def _ensure(plot_dir):
    os.makedirs(plot_dir, exist_ok=True)


def price_fan_charts(result, plot_dir):
    """Plot 1: per-product price fan chart with p5-p95 and p25-p75 bands."""
    _ensure(plot_dir)
    prices = result.prices.astype(np.float64)
    qs = np.percentile(prices, [5, 25, 50, 75, 95], axis=0)
    days = np.arange(N_DAYS)
    for prod in TRADEABLE:
        i = P_IDX[prod]
        base = MARKET_PARAMS[prod]["base"]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.fill_between(days, qs[0, :, i], qs[4, :, i], alpha=0.18,
                        color="tab:blue", label="p5-p95")
        ax.fill_between(days, qs[1, :, i], qs[3, :, i], alpha=0.38,
                        color="tab:blue", label="p25-p75")
        ax.plot(days, qs[2, :, i], color="tab:blue", lw=2, label="median")
        ax.axhline(base, color="gray", ls="--", lw=1.2, label=f"base ${base}")
        ax.set_title(f"{prod} - price fan chart ({result.n_simulations} sims)")
        ax.set_xlabel("day")
        ax.set_ylabel("price ($)")
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(os.path.join(plot_dir, f"price_fan_{prod.lower()}.png"), dpi=130)
        plt.close(fig)


def demand_heatmap(result, plot_dir):
    """Plot 2: median daily town demand heatmap (products x days)."""
    _ensure(plot_dir)
    med = np.median(result.daily_demand, axis=0).T   # (9 products, 30 days)
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(med, aspect="auto", cmap="YlOrRd", origin="upper")
    ax.set_yticks(range(len(PRODUCTS)))
    ax.set_yticklabels(PRODUCTS)
    ax.set_xticks(range(0, N_DAYS, 3))
    ax.set_xlabel("day")
    ax.set_ylabel("product")
    ax.set_title("Median daily town demand (units/day) - ramps as shops unlock")
    fig.colorbar(im, ax=ax, label="units/day")
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "demand_heatmap.png"), dpi=130)
    plt.close(fig)


def hinge_trigger_probability(hinge_stats, plot_dir):
    """Plot 3: P(hinge triggered by day X) for carrot/tomato/egg."""
    _ensure(plot_dir)
    x = np.arange(len(CHECKPOINT_DAYS))
    width = 0.26
    fig, ax = plt.subplots(figsize=(9, 5))
    for k, prod in enumerate(["CARROT", "TOMATO", "EGG"]):
        probs = [hinge_stats[prod]["p_triggered_by_checkpoint"][f"by_day_{d}"]
                 for d in CHECKPOINT_DAYS]
        ax.bar(x + (k - 1) * width, probs, width, label=prod)
    ax.set_xticks(x)
    ax.set_xticklabels([f"day {d}" for d in CHECKPOINT_DAYS])
    ax.set_ylim(0, 1)
    ax.set_ylabel("P(hinge triggered)")
    ax.set_title("Hinge-trigger probability (market inventory below I0 - T)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "hinge_trigger_probability.png"), dpi=130)
    plt.close(fig)


def product_roi_scatter(single_result, plot_dir):
    """Plot 4: risk vs reward scatter with tier coloring."""
    _ensure(plot_dir)
    ranking = product_ranking(single_result)
    tiers = ranking["tier_list"]
    tier_of = {p: t for t, prods in tiers.items() for p in prods}
    fig, ax = plt.subplots(figsize=(8, 6))
    for prod, m in ranking["metrics"].items():
        ax.scatter(m["risk_std_revenue_per_tile_per_day"],
                   m["revenue_per_tile_per_day"],
                   s=90, c=TIER_COLORS[tier_of.get(prod, "C")],
                   zorder=3, edgecolors="black", linewidths=0.5)
        ax.annotate(prod, (m["risk_std_revenue_per_tile_per_day"],
                           m["revenue_per_tile_per_day"]),
                    textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax.set_xlabel("risk (std dev of revenue $/tile/day)")
    ax.set_ylabel("expected revenue ($/tile/day)")
    ax.set_title("Product efficient frontier (colors = risk-adjusted tier)")
    handles = [plt.Line2D([0], [0], marker="o", ls="", color=TIER_COLORS[t], label=t)
               for t in ["S", "A", "B", "C"]]
    ax.legend(handles=handles)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "product_roi_scatter.png"), dpi=130)
    plt.close(fig)


def shop_combination_impact(plot_dir):
    """Plot 5: deterministic day-20 price impact of adding 1 or 3 instances of
    each shop type (town center always present; no other shops unlocked)."""
    _ensure(plot_dir)
    days_elapsed = 21          # days 0..20 inclusive
    shop_days_active = 18      # shop unlocked day 3 .. day 20 inclusive
    base_inv = 10000 - TC_VECTOR.astype(np.float64) * days_elapsed
    base_price = {
        i: compute_price(prod, int(round(base_inv[i])))
        for i, prod in enumerate(PRODUCTS)
    }

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for j, ax in zip((1, 3), axes):
        ratios = np.ones((len(SHOP_TYPES), len(TRADEABLE)))
        for s in range(len(SHOP_TYPES)):
            for ti, prod in enumerate(TRADEABLE):
                pi = P_IDX[prod]
                inv = base_inv[pi] - j * SHOP_DEMAND_MATRIX[s, pi] * shop_days_active
                ratios[s, ti] = compute_price(prod, int(round(inv))) / max(base_price[pi], 1e-9)
        im = ax.imshow(ratios, cmap="RdYlGn", vmin=0, vmax=2, aspect="auto")
        ax.set_xticks(range(len(TRADEABLE)))
        ax.set_xticklabels(TRADEABLE, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(SHOP_TYPES)))
        ax.set_yticklabels(SHOP_TYPES, fontsize=8)
        for s in range(len(SHOP_TYPES)):
            for ti in range(len(TRADEABLE)):
                ax.text(ti, s, f"{ratios[s, ti]:.2f}", ha="center", va="center", fontsize=7)
        ax.set_title(f"Day-20 price ratio vs baseline - {j} instance(s)")
        fig.colorbar(im, ax=ax, shrink=0.85)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "shop_combination_impact.png"), dpi=130)
    plt.close(fig)


def cumulative_revenue_comparison(single_result, layouts, plot_dir):
    """Plot 6: cumulative net revenue over 30 days for fixed farm layouts.

    layouts: list of (label, crop_tiles dict, animal_counts dict).
    Season costs (seeds x plantings, animal purchase + feed) are subtracted
    up front; sales revenue accumulates daily at simulated prices.
    """
    _ensure(plot_dir)
    prices = single_result.prices.astype(np.float64)
    day_idx = np.arange(1, N_DAYS + 1)
    fig, ax = plt.subplots(figsize=(9, 6))

    for label, crops, animals in layouts:
        rev = np.zeros(prices.shape[:2])          # (n_sims, days)
        cost = 0.0
        for prod, tiles in crops.items():
            rate = SEASON_YIELD_PER_TILE[prod] / N_DAYS
            rev += tiles * rate * prices[:, :, P_IDX[prod]]
            cost += tiles * SEASON_COST_PER_TILE[prod]
        for name, count in animals.items():
            prod = ANIMAL_OF_NAME[name]
            rev += count * ANIMAL_DAILY_RATE[name] * prices[:, :, P_IDX[prod]]
            cost += count * (ANIMAL_PURCHASE_COST[prod] + SEASON_FEED_COST)
        cum = np.cumsum(rev, axis=1) - cost
        med = np.median(cum, axis=0)
        p5 = np.percentile(cum, 5, axis=0)
        p95 = np.percentile(cum, 95, axis=0)
        line, = ax.plot(day_idx, med, lw=2, label=label)
        ax.fill_between(day_idx, p5, p95, alpha=0.15, color=line.get_color())

    ax.axhline(0, color="gray", lw=0.8)
    ax.set_xlabel("day")
    ax.set_ylabel("cumulative net revenue ($)")
    ax.set_title("Cumulative net revenue by farm layout (median, p5-p95 band)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "cumulative_revenue_comparison.png"), dpi=130)
    plt.close(fig)
