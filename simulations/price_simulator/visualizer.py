"""Plots for the price simulator. Saves PNGs via the Agg backend."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from concurrent_order_simulator import simulate_concurrent  # noqa: E402
from marginal_revenue_analyzer import (  # noqa: E402
    floor_distance,
    slippage_table,
)
from price_curve_engine import I0, MARKET_PARAMS, compute_price_vectorized  # noqa: E402
from recovery_simulator import simulate_recovery  # noqa: E402


def _ensure(d):
    os.makedirs(d, exist_ok=True)


def plot_price_curves(output_dir):
    _ensure(output_dir)
    x = np.arange(0, 1201)          # inventory offset from I0
    fig, axes = plt.subplots(3, 3, figsize=(14, 10), sharex=True)
    for ax, (prod, p) in zip(axes.ravel(), MARKET_PARAMS.items()):
        offset = np.concatenate([-x[::-1], x[1:]])
        price = np.concatenate([compute_price_vectorized(prod, I0 - x[::-1]),
                                compute_price_vectorized(prod, I0 + x[1:])])
        ax.plot(offset, price, lw=1.6)
        ax.axhline(p["base"], color="gray", ls="--", lw=0.8)
        ax.axvline(0, color="gray", ls=":", lw=0.8)
        ax.set_title(f"{prod} (base ${p['base']}, T={p['T']})", fontsize=10)
        ax.set_xlabel("inventory offset from I0")
        ax.set_ylabel("price ($)")
    fig.suptitle("Kaggriculture price curves - scarcity (left) vs glut (right)")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "price_curves.png"), dpi=130)
    plt.close(fig)


def plot_marginal_revenue(product, output_dir, quantity=200):
    from marginal_revenue_analyzer import simulate_sale_path
    _ensure(output_dir)
    res = simulate_sale_path(product, I0, quantity)
    ks = np.arange(1, len(res["unit_prices"]) + 1)
    tr = np.cumsum(res["unit_prices"])
    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.plot(ks, res["unit_prices"], lw=1.8, color="tab:red", label="marginal price")
    ax1.set_xlabel("unit sold"); ax1.set_ylabel("marginal price ($)", color="tab:red")
    ax2 = ax1.twinx()
    ax2.plot(ks, tr, lw=1.8, color="tab:blue", label="total revenue")
    ax2.set_ylabel("total revenue ($)", color="tab:blue")
    ax1.set_title(f"{product}: liquidating {quantity} units from I0 "
                  f"(avg ${res['avg_realized_price']:.2f})")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, f"marginal_revenue_{product.lower()}.png"), dpi=130)
    plt.close(fig)


def plot_slippage(output_dir):
    _ensure(output_dir)
    prods = list(MARKET_PARAMS.keys())
    sizes = [1, 5, 10, 20, 50, 100]
    fig, ax = plt.subplots(figsize=(11, 5))
    width = 0.09
    for i, prod in enumerate(prods):
        rows = slippage_table(prod, I0, sizes)
        ax.bar(np.arange(len(sizes)) + (i - 4) * width,
               [r["slippage_pct"] for r in rows], width, label=prod)
    ax.set_xticks(range(len(sizes)))
    ax.set_xticklabels([f"Q={s}" for s in sizes])
    ax.set_ylabel("slippage vs spot (%)")
    ax.set_title("Slippage when dumping into an equilibrium market (I0)")
    ax.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "slippage.png"), dpi=130)
    plt.close(fig)


def plot_recovery(output_dir, scenarios=None):
    """scenarios: list of (product, dump_size, shops)."""
    _ensure(output_dir)
    if scenarios is None:
        scenarios = [
            ("MELON", 40, ("YARN_STORE", "PET_CAFE")),
            ("STRAWBERRY", 40, ("ICE_CREAM_SHOP", "SMOOTHIE_SHOP")),
            ("WOOL", 30, ("YARN_STORE",)),
            ("WHEAT", 200, ("BAKERY", "PIZZA_SHOP")),
        ]
    fig, ax = plt.subplots(figsize=(9, 5))
    for product, q, shops in scenarios:
        res = simulate_recovery(product, q, shops=shops, days=14)
        base = res["base_price"]
        norm = [p / base for p in res["traj_price"]]
        ax.plot(res["traj_day"], norm,
                marker="o", ms=3,
                label=f"{product} dump {q} ({len(shops)} shops)")
    ax.axhline(1.0, color="gray", ls="--", lw=1, label="base price")
    ax.set_xlabel("days after dump"); ax.set_ylabel("price / base")
    ax.set_title("Price recovery via town drain (dump at day 0)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "recovery_curves.png"), dpi=130)
    plt.close(fig)


def plot_pvp(p0_order="SELL MELON 50", p1_order="SELL MELON 10",
             output_dir="results/plots"):
    _ensure(output_dir)
    res = simulate_concurrent([p0_order], [p1_order], trace=True)
    prices_p0 = [e["price"] for e in res["trace"] if e["player"] == "P0"]
    prices_p1 = [e["price"] for e in res["trace"] if e["player"] == "P1"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(range(1, len(prices_p0) + 1), prices_p0, marker=".", label="P0 per-unit price")
    ax.step(range(1, len(prices_p1) + 1), prices_p1, where="mid", label="P1 per-unit price")
    ax.set_xlabel("that player's n-th unit executed")
    ax.set_ylabel("executed price ($)")
    ax.set_title(f"Interleaved execution: {p0_order!r} vs {p1_order!r}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "pvp_execution.png"), dpi=130)
    plt.close(fig)


def generate_all_plots(output_dir):
    plot_price_curves(output_dir)
    for prod in ("MELON", "STRAWBERRY", "WOOL", "WHEAT"):
        plot_marginal_revenue(prod, output_dir)
    plot_slippage(output_dir)
    plot_recovery(output_dir)
    plot_pvp(output_dir=output_dir)
    return sorted(os.listdir(output_dir))
