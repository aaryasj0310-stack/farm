"""Convergence study: how many Monte Carlo runs are sufficient?

Loads the exact exhaustive reference (population truth) and measures, for
N in {1000, 5000, 10000, 25000, 50000} (R repetitions each), the error of
standard MC estimators against it:

  - max |mean error| over (day, product) cells, and at day 29 in dollars
  - max relative std-dev error
  - max absolute threshold-probability error (percentage points)
  - max total-variation distance between sampled and exact price PMFs

Sufficiency verdict: smallest N whose WORST repetition satisfies all
tolerances. Uses the same ExhaustiveAccumulator on both sides so estimator
definitions are identical.
"""
import argparse
import json
import os
import time

import numpy as np

from exhaustive_enumerator import ExhaustiveAccumulator
from monte_carlo_runner import MonteCarloRunner

NS_DEFAULT = [1000, 5000, 10000, 25000, 50000]
REPS = 5
TOL_MEAN_USD = 0.50          # |mean err| <= $0.50 ...
TOL_MEAN_REL = 0.01          # ... or <= 1% of |exact mean| (per cell, day29 rule uses both)
TOL_THRESH = 0.005           # 0.5 percentage points
TOL_TV = 0.05
MONITOR_DAYS_TV = [15, 25, 29]
MONITOR_DAYS_THR = [15, 20, 25, 29]


def _tv_distance(hist_est, hist_ref, count_est, count_ref):
    """Max TV over products for the monitored days (coarse bins as-is)."""
    worst = 0.0
    pe = hist_est.astype(np.float64) / max(count_est, 1)
    pr = hist_ref.astype(np.float64) / max(count_ref, 1)
    for d in MONITOR_DAYS_TV:
        diff = np.abs(pe[d] - pr[d]).sum(axis=1) * 0.5
        worst = max(worst, float(diff.max()))
    return worst


def evaluate_against_reference(acc_final, ref):
    from town_demand_engine import PRODUCTS
    n = acc_final["count"]
    mean_err_cells = np.abs(acc_final["mean"] - ref["mean"])
    mean_err_max = float(mean_err_cells.max())
    d, p_ = np.unravel_index(int(mean_err_cells.argmax()), mean_err_cells.shape)
    worst_mean_cell = {"day": int(d), "product": PRODUCTS[p_],
                       "err_usd": round(mean_err_max, 3),
                       "exact_mean": round(float(ref["mean"][d, p_]), 2)}
    day29 = mean_err_cells[29]
    rel = day29 / np.maximum(np.abs(ref["mean"][29]), 1e-9)
    ok29 = (day29 <= TOL_MEAN_USD) | (rel <= TOL_MEAN_REL)
    std_rel = float((np.abs(acc_final["std"] - ref["std"])
                     / np.maximum(ref["std"], 1e-9)).max())
    thr_err = 0.0
    worst_thr = None
    grid = ref["grid"]
    est_tail = acc_final["tail_prob"]
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            g = int(min(grid[i, j], acc_final["hist"].shape[-1] - 1))
            # recompute est tail from its own histograms at this grid value
            h = acc_final["hist"][:, i, :]
            tail = h[:, g + 1:].sum(axis=1) / max(n, 1)
            errs = np.abs(tail[MONITOR_DAYS_THR]
                          - ref["tail_prob"][i, j][MONITOR_DAYS_THR])
            k = int(errs.argmax())
            if errs[k] > thr_err:
                thr_err = float(errs[k])
                worst_thr = {"product": PRODUCTS[i],
                             "threshold": int(grid[i, j]),
                             "by_day": MONITOR_DAYS_THR[k],
                             "err_pp": round(thr_err * 100, 3),
                             "exact_p": round(float(
                                 ref["tail_prob"][i, j][MONITOR_DAYS_THR][k]), 4)}
    tv = _tv_distance(acc_final["hist"], ref["hist"], n, int(ref["count"]))
    return {
        "mean_err_max_usd": round(mean_err_max, 4),
        "worst_mean_cell": worst_mean_cell,
        "mean_err_median_usd": round(float(np.median(mean_err_cells)), 4),
        "day29_all_products_ok": bool(ok29.all()),
        "std_rel_err_max": round(std_rel, 5),
        "thresh_err_max_pp": round(thr_err * 100, 4),
        "worst_thresh_cell": worst_thr,
        "tv_max": round(tv, 5),
    }


def passes(m):
    return (m["day29_all_products_ok"]
            and m["std_rel_err_max"] <= 0.10      # 10% relative std drift cap
            and m["thresh_err_max_pp"] <= TOL_THRESH * 100
            and m["tv_max"] <= TOL_TV)


def run_convergence(reference="results/exhaustive/town_only_reference.npz",
                    ns=None, reps=REPS, seed_base=42,
                    output_dir="results/convergence", quiet=False):
    ns = ns or NS_DEFAULT
    ref = load_ref(reference)

    rows = []
    for N in ns:
        # CRITICAL: a fresh runner sized to THIS N -- reusing one runner would
        # silently evaluate every N at max(ns).
        runner = MonteCarloRunner(n_simulations=N, seed=seed_base)
        t0 = time.perf_counter()
        reps_metrics = []
        for rep in range(reps):
            rng = np.random.default_rng(seed_base * 1_000_003 + rep * 7919 + N)
            res = runner.run_town_only(rng=rng)
            acc = ExhaustiveAccumulator()
            acc.update(res)
            est = acc.finalize()
            m = evaluate_against_reference(est, ref)
            m["rep"] = rep
            reps_metrics.append(m)
            del res, est
        # worst repetition: failing reps first, then largest mean error
        worst = max(reps_metrics,
                    key=lambda m: (not passes(m), m["mean_err_max_usd"]))
        elapsed = time.perf_counter() - t0
        row = {"N": N, "reps": reps, "elapsed_s": round(elapsed, 2),
               "worst_rep": worst, "sufficient": bool(passes(worst))}
        rows.append(row)
        if not quiet:
            print(f"N={N:>6}: mean_err=${worst['mean_err_max_usd']:.3f} "
                  f"thr_err={worst['thresh_err_max_pp']:.3f}pp "
                  f"tv={worst['tv_max']:.4f} "
                  f"sufficient={row['sufficient']} ({elapsed:.1f}s)")

    sufficient_n = next((r["N"] for r in rows if r["sufficient"]), None)
    report = {
        "reference": reference,
        "ns": ns, "reps_per_n": reps, "seed_base": seed_base,
        "tolerances": {"mean_usd": TOL_MEAN_USD, "mean_rel": TOL_MEAN_REL,
                       "thresh_pp": TOL_THRESH * 100, "tv": TOL_TV},
        "rows": rows,
        "smallest_sufficient_N": sufficient_n,
    }
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "convergence_report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    _plot(rows, os.path.join(output_dir, "convergence_plot.png"))
    if not quiet:
        verdict = (f"N >= {sufficient_n}" if sufficient_n
                   else f"none of {ns} within tolerance")
        print(f"\nSmallest sufficient N: {verdict}")
        print(f"report -> {os.path.join(output_dir, 'convergence_report.json')}")
    return report


def load_ref(path):
    z = np.load(path, allow_pickle=False)
    return {k: z[k] for k in z.files}


def _plot(rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ns = [r["N"] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 5))
    series = [("mean_err_max_usd", "max |mean err| ($)"),
              ("thresh_err_max_pp", "max threshold err (pp)"),
              ("tv_max", "TV distance (x100)")]
    for key, label in series:
        vals = [r["worst_rep"][key] * (100 if key == "tv_max" else 1) for r in rows]
        ax.plot(ns, vals, marker="o", label=label)
    guide = [rows[0]["worst_rep"]["mean_err_max_usd"] *
             (ns[0] / n) ** 0.5 for n in ns]
    ax.plot(ns, guide, ls="--", lw=1, color="gray", label="~1/sqrt(N) guide")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Monte Carlo runs N")
    ax.set_ylabel("worst-rep error vs exhaustive truth")
    ax.set_title("MC convergence vs exhaustive enumeration")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="MC-vs-exhaustive convergence study")
    ap.add_argument("--reference", type=str,
                    default="results/exhaustive/town_only_reference.npz")
    ap.add_argument("--ns", type=str, default=",".join(str(n) for n in NS_DEFAULT))
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--seed-base", type=int, default=42)
    ap.add_argument("--output", type=str, default="results/convergence")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    run_convergence(args.reference, [int(x) for x in args.ns.split(",")],
                    args.reps, args.seed_base, args.output, args.quiet)


if __name__ == "__main__":
    main()
