"""Visualizations for Kaggriculture Tournaments and A/B Experiments."""

import os
from typing import Dict, Any, List
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Headless mode for server / CLI execution
import matplotlib.pyplot as plt


def plot_winrate_matrix(pair_matrix: Dict[str, Any], agent_names: List[str], output_path: str):
    """Plots a heatmap matrix of pairwise win rates."""
    n = len(agent_names)
    matrix = np.zeros((n, n))
    
    for i, a1 in enumerate(agent_names):
        for j, a2 in enumerate(agent_names):
            if i == j:
                matrix[i, j] = 0.5
            else:
                key1 = f"{a1}_vs_{a2}"
                key2 = f"{a2}_vs_{a1}"
                if key1 in pair_matrix:
                    matrix[i, j] = pair_matrix[key1]["win_rate_a"]
                elif key2 in pair_matrix:
                    matrix[i, j] = pair_matrix[key2]["win_rate_b"]

    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0.0, vmax=1.0)
    
    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    ax.set_xticklabels(agent_names, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(agent_names, fontsize=9)
    
    for i in range(n):
        for j in range(n):
            text = f"{matrix[i, j]:.2f}" if i != j else "-"
            ax.text(j, i, text, ha="center", va="center", color="black", fontsize=9, fontweight="bold")

    ax.set_title("Kaggriculture Agent Pairwise Win Rate Matrix", fontsize=12, fontweight="bold", pad=12)
    fig.colorbar(im, ax=ax, label="Row Agent Win Rate vs Column Agent")
    plt.tight_layout()
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path)
    plt.close(fig)


def plot_score_distributions(rankings: List[Dict[str, Any]], output_path: str):
    """Plots score distributions and error bars across ranked agents."""
    agents = [r["agent"] for r in rankings]
    means = [r["mean_score"] for r in rankings]
    stds = [r["std_score"] for r in rankings]
    win_rates = [r["win_rate"] * 100 for r in rankings]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), dpi=150)

    # 1. Mean Score Bar Chart with std error bars
    colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(agents)))
    bars = ax1.bar(agents, means, yerr=stds, capsize=5, color=colors, edgecolor="black", alpha=0.85)
    ax1.set_title("Average Score ($) across Tournament", fontsize=11, fontweight="bold")
    ax1.set_ylabel("Coins ($)")
    ax1.set_xticklabels(agents, rotation=45, ha="right", fontsize=9)
    ax1.grid(axis="y", linestyle="--", alpha=0.4)
    
    for bar, mean in zip(bars, means):
        ax1.text(bar.get_x() + bar.get_width()/2., mean / 2, f"${mean:.0f}", ha="center", va="center", color="white", fontweight="bold")

    # 2. Win Rate Bar Chart
    ax2.bar(agents, win_rates, color="royalblue", edgecolor="black", alpha=0.85)
    ax2.set_title("Overall Tournament Win Rate (%)", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Win Rate (%)")
    ax2.set_ylim(0, 105)
    ax2.set_xticklabels(agents, rotation=45, ha="right", fontsize=9)
    ax2.grid(axis="y", linestyle="--", alpha=0.4)
    
    for i, wr in enumerate(win_rates):
        ax2.text(i, wr + 2, f"{wr:.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path)
    plt.close(fig)


def plot_ab_comparison(exp_report: Dict[str, Any], output_path: str):
    """Plots A/B test score comparison with confidence intervals."""
    agent_a = exp_report["agent_a"]
    agent_b = exp_report["agent_b"]
    mean_a = exp_report["mean_score_a"]
    mean_b = exp_report["mean_score_b"]
    std_a = exp_report["std_score_a"]
    std_b = exp_report["std_score_b"]

    fig, ax = plt.subplots(figsize=(7, 5), dpi=150)
    bars = ax.bar([agent_a, agent_b], [mean_a, mean_b], yerr=[std_a, std_b], capsize=6, color=["#2ca02c", "#d62728"], edgecolor="black", alpha=0.85)
    
    ax.set_title(f"A/B Test: {exp_report['title']}\nVerdict: {exp_report['verdict']} (+{exp_report['percent_lift']}%)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Final Coins ($)")
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    for bar, val in zip(bars, [mean_a, mean_b]):
        ax.text(bar.get_x() + bar.get_width()/2., val / 2, f"${val:.0f}", ha="center", va="center", color="white", fontweight="bold", fontsize=10)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path)
    plt.close(fig)
