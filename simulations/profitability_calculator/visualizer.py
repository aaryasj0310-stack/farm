"""Charts for the profitability calculator. Saves PNGs via Agg backend."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from animal_model import simulate_animal_lifecycle  # noqa: E402
from crop_model import CROPS, season_plan  # noqa: E402
from endgame_cutoff_planner import build_cutoff_table  # noqa: E402
from roi_matrix_engine import build_roi_matrices  # noqa: E402


def _ensure(d):
    os.makedirs(d, exist_ok=True)


def plot_roi_heatmap(matrices, output_dir):
    _ensure(output_dir)
    regimes = list(matrices.keys())
    assets = list(matrices[regimes[0]]["assets"].keys())
    grid = np.array([[matrices[r]["assets"][a]["pptd"] for r in regimes] for a in assets])
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(grid, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(regimes)))
    ax.set_xticklabels(regimes, fontsize=9)
    ax.set_yticks(range(len(assets)))
    ax.set_yticklabels(assets)
    for i in range(len(assets)):
        for j in range(len(regimes)):
            ax.text(j, i, f"${grid[i, j]:,.0f}", ha="center", va="center", fontsize=8)
    ax.set_title("Net profit per tile per day (PPTD) by regime")
    fig.colorbar(im, ax=ax, label="PPTD ($)")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "roi_regime_heatmap.png"), dpi=130)
    plt.close(fig)


def plot_pareto(matrices, output_dir):
    _ensure(output_dir)
    base = matrices["spot_base"]["assets"]
    fig, ax = plt.subplots(figsize=(8, 6))
    for asset, m in base.items():
        ax.scatter(m["roci_pct"], m["pptd"], s=90, edgecolors="black",
                   linewidths=0.5, zorder=3)
        ax.annotate(asset, (m["roci_pct"], m["pptd"]),
                    textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax.set_xlabel("return on capital invested (%)")
    ax.set_ylabel("profit per tile per day ($)")
    ax.set_title("Asset efficiency frontier at spot base prices")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "pareto_frontier.png"), dpi=130)
    plt.close(fig)


def plot_cashflow(output_dir):
    """Cumulative net cashflow by day for one tile of each crop + a goose."""
    _ensure(output_dir)
    fig, ax = plt.subplots(figsize=(9, 5))
    days = np.arange(0, 31)

    for crop, fert in (("WHEAT", False), ("MELON", True), ("STRAWBERRY", True),
                       ("TOMATO", False), ("CARROT", False)):
        plan = season_plan(crop, horizon=30, fertilized=fert)
        hday = plan["cycle_length"] - 1
        net_per_cycle = (plan["season_revenue"] - plan["seed_cost"]
                         - plan["fertilizer_cost"]) / max(plan["plantings"], 1)
        cum = []
        c = -net_per_cycle * 0  # costs paid at planting
        for d in days:
            cycles_done = int(d // (hday + 1)) if d > 0 else 0
            # revenue arrives at each harvest; costs at each planting
            harvests = len([s for s in range(plan["plantings"]) if s * (hday + 1) <= d])
            plantings_made = harvests + (1 if d == 0 else 0)
            rev_share = plan["season_revenue"] / plan["plantings"]
            cost_share = (plan["seed_cost"] + plan["fertilizer_cost"]) / plan["plantings"]
            cum.append(harvests * rev_share - max(harvests, 1) * cost_share)
        ax.plot(days, cum, label=crop + (" (+fert)" if fert else ""))

    goose_days = np.arange(0, 31)
    daily = None
    cum_goose = []
    net_total = simulate_animal_lifecycle("GOOSE")["net_profit"]
    egg_days = list(range(4, 30))
    for d in goose_days:
        val = -300 - 25 * (d + 1) + 50 * sum(1 for e in egg_days if e <= d)
        cum_goose.append(val)
    ax.plot(goose_days, cum_goose, label="GOOSE")
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_xlabel("day"); ax.set_ylabel("cumulative net cashflow ($)")
    ax.set_title("Single-tile / single-animal cumulative cashflow (base prices)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "cashflow.png"), dpi=130)
    plt.close(fig)


def plot_cutoffs(output_dir):
    _ensure(output_dir)
    table = build_cutoff_table()
    assets = list(table.keys())
    hard = [min(v.get("hard_cutoff_fertilized", v.get("hard_cutoff", 0)),
                v.get("hard_cutoff_unfertilized", 99)) for v in table.values()]
    econ = [v.get("economic_cutoff_best_variant",
                  v.get("economic_cutoff_base_prices")) or 0 for v in table.values()]
    x = np.arange(len(assets))
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - 0.2, hard, 0.4, label="hard cutoff (any harvest)")
    ax.bar(x + 0.2, econ, 0.4, label="economic cutoff (net >= 0)")
    ax.set_xticks(x); ax.set_xticklabels(assets, rotation=30, ha="right")
    ax.set_ylabel("last day to start")
    ax.set_title("Endgame cutoff days by asset (season ends day 29)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "endgame_cutoffs.png"), dpi=130)
    plt.close(fig)


def generate_all_plots(output_dir="results/plots"):
    matrices = build_roi_matrices()
    plot_roi_heatmap(matrices, output_dir)
    plot_pareto(matrices, output_dir)
    plot_cashflow(output_dir)
    plot_cutoffs(output_dir)
    return sorted(os.listdir(output_dir))
