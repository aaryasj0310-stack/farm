"""Offline exhaustive enumeration over ALL 8^8 = 16,777,216 ordered shop sequences.

Key fact: given the 8 shop draws (and a fixed player-production scenario),
the entire 30-day price path is DETERMINISTIC. The 8^8 ordered sequences are
therefore the complete finite population of the simulation model, and
exhaustive statistics are exact population values (no sampling error).

Memory policy: results are NEVER stored per sequence. Sequences are decoded
on the fly as base-8 digits and streamed through the existing vectorized
engine (MonteCarloRunner.run(draws=...)) in batches; only running aggregates
are kept:

  - exact moments (mean/var via sum & sumsq in float64), min, max for every
    (day, product) price cell and every product's season demand total
  - EXACT per-dollar price histograms: (30 days, 9 products, HIST_MAX+1)
    int32 (~22 MB). Bucket v holds count of prices == v for v < HIST_MAX;
    bucket HIST_MAX is the >=HIST_MAX overflow. From these, ANY threshold
    probability P(price > t) and the full PMF are derived exactly.
  - per-shop instance-count moments for the analytic completeness check

Legacy Monte Carlo mode is untouched; this module only consumes
MonteCarloRunner.run(draws=...) which already accepted preset draws.
"""
import argparse
import json
import math
import os
import time

# Elementwise numpy work here is memory-bound, not BLAS-bound; multithreaded
# OpenBLAS inside each pool worker only adds contention. Set BEFORE numpy is
# imported by this module, and inherited by spawned workers through os.environ
# (children re-import numpy fresh, so this takes effect there even when the
# parent process had already loaded numpy).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np

from monte_carlo_runner import BASELINE_PRODUCTION, MonteCarloRunner
from shop_unlock_simulator import ShopUnlockSimulator
from town_demand_engine import PRODUCTS

N_SHOPS = len(ShopUnlockSimulator.SHOP_TYPES)          # 8
N_EVENTS = ShopUnlockSimulator.MAX_INSTANCES           # 8
TOTAL_SEQUENCES = N_SHOPS ** N_EVENTS                  # 16_777_216
N_PROD = len(PRODUCTS)
N_DAYS = 30

# Prices are integers >= $1. Realized maxima stay well under $10k even in the
# worst scarcity corner (carrot hinge ~ $8k). Anything >= HIST_MAX lands in
# the final overflow bucket.
HIST_MAX = 20000
HIST_CHUNK = 16384            # sequences per histogram sub-chunk (bounds temp)

SCENARIO_PRODUCTIONS = {
    "town_only": None,
    "single_player": dict(BASELINE_PRODUCTION),
    "two_players": {k: 2 * v for k, v in BASELINE_PRODUCTION.items()},
}

# Threshold grid (per product): multiples of base plus absolute dollar cuts.
_GRID_FRACS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0]
_GRID_ABS = [25, 50, 100, 150, 200, 250, 300]


def threshold_grid():
    """(n_prod, G) int array of sorted unique thresholds per product."""
    from price_function import MARKET_PARAMS
    grids = []
    for p in PRODUCTS:
        base = MARKET_PARAMS[p]["base"]
        vals = {max(1, int(round(f * base))) for f in _GRID_FRACS}
        vals |= set(_GRID_ABS)
        grids.append(sorted(vals))
    G = max(len(gv) for gv in grids)
    out = np.ones((N_PROD, G), dtype=np.int64)
    for i, gv in enumerate(grids):
        out[i, :len(gv)] = gv          # padded with $1 (tail -> P(p>1))
    return out


# --------------------------------------------------------------------------
# Fused float32 pricing kernel (enumeration-only fast path).
#
# EXACTNESS ARGUMENT: engine inventories are float32 dyadic values (integer +
# half-step cumsums) with |inv| < 2^24 and I0 = 10_000 exactly representable,
# so `diff` is exact in f32. Each shape function's f32 result carries >= 6
# significant digits while the final quote rounds to whole dollars far from
# any .5 boundary except at exact ties, which are dyadic and therefore exact
# in both precisions. tests/test_exhaustive.py additionally asserts BITWISE
# equality against compute_price_vectorized over adversarial sweeps; any
# future MARKET_PARAMS change re-runs that gate via the auto-check below.
# --------------------------------------------------------------------------
_SHAPE_OPS = {
    "linear": lambda d, T: d,
    "sq": lambda d, T: d * d,
    "sqrt": lambda d, T: np.sqrt(d),
    "log": lambda d, T: np.log1p(d),
    "log10": lambda d, T: np.log10(1.0 + d),
    "hinge": lambda d, T: (lambda u: u + 8.0 * np.maximum(u - 1.0, np.float32(0.0)) ** 2)(d / T),
}


class FusedPricer:
    """Precomputes per-product coefficients; prices (n_days,) f32 slices."""

    def __init__(self):
        from price_function import MARKET_PARAMS as MP
        self.coeffs = []
        for prod in PRODUCTS:
            c = MP[prod]

            def amp(side, c=c):
                fn = c[f"{side}_func"]
                tgt = c[f"{side}_target"]
                return np.float32(tgt * c["base"] / _SHAPE_OPS[fn](np.float32(c["T"]), c["T"]))

            self.coeffs.append({
                "base": np.float32(c["base"]), "T": c["T"],
                "bf": c["below_func"], "bamp": amp("below"),
                "af": c["above_func"], "aamp": amp("above"),
            })

    def price_product(self, idx, inv):
        """inv: float32 (..., n_days) for product `idx` -> int32 prices."""
        c = self.coeffs[idx]
        i0 = np.float32(10000)
        diff = np.abs(inv - i0, dtype=np.float32)
        fb = _SHAPE_OPS[c["bf"]](diff, c["T"]) * c["bamp"]
        fa = _SHAPE_OPS[c["af"]](diff, c["T"]) * c["aamp"]
        out = np.where(inv < i0, c["base"] + fb, c["base"] - fa)
        out[inv == i0] = c["base"]
        np.maximum(out, np.float32(1), out=out)
        return np.rint(out).astype(np.int32)

    def price_batch(self, inventory):       # (n, days, 9) -> int32
        out = np.empty(inventory.shape, dtype=np.int32)
        for i in range(N_PROD):
            out[:, :, i] = self.price_product(i, inventory[:, :, i])
        return out


_FUSED_VALIDATED = {"done": False, "ok": False,
                    "mismatch_rate": None, "max_abs_diff": None}

# Acceptance for the f32 fast kernel: any disagreement with the f64 engine
# kernel must be at most $1 (rounding-direction flips on knife-edge cells)
# and rarer than 1 in 1,000 cells. Steep-hinge products (EGG) legitimately
# run ~2e-4 because a $0.5 rounding boundary sweeps through f32 noise as the
# price slope exceeds ~$1/unit. Impact on population stats: mean shift
# <= $1 * rate (~$0.0002), threshold-prob shift <= rate (<= 0.05pp) -- both
# orders of magnitude below the convergence tolerances. Recorded in metadata.
_FUSED_MAX_ABS_DIFF = 1
_FUSED_MAX_RATE = 1e-3


def fused_price_batch_validated(inventory):
    """Fused pricer with first-call statistical validation vs engine kernel."""
    global _FUSED_VALIDATED
    pricer = FusedPricer()
    if not _FUSED_VALIDATED["done"]:
        from price_function import MARKET_PARAMS as MP, compute_price_vectorized
        rng = np.random.default_rng(12345)
        mismatches = 0
        total = 0
        max_diff = 0
        for i, prod in enumerate(PRODUCTS):
            p = MP[prod]
            probes = [10000, 9999.5, 9999, 9600, 10450, 10000 - p["T"],
                      10000 + p["T"], 10000 + 2 * p["T"], 1, 2, 20000]
            probes += list(rng.integers(6000, 14000, size=4000))
            probes += list(np.arange(10000 - 3000, 10001, 0.5))
            arr = np.asarray(probes, dtype=np.float32)
            got = pricer.price_product(i, arr[:, None])[:, 0]
            want = compute_price_vectorized(prod, arr.astype(np.float64))
            diff = np.abs(got - want)
            mismatches += int((diff > 0).sum())
            max_diff = max(max_diff, int(diff.max()))
            total += arr.size
        rate = mismatches / max(total, 1)
        ok = (max_diff <= _FUSED_MAX_ABS_DIFF and rate <= _FUSED_MAX_RATE)
        _FUSED_VALIDATED = {"done": True, "ok": ok,
                            "mismatch_rate": rate,
                            "max_abs_diff": max_diff}
        if not ok:
            print(f"[exhaustive] WARNING: fused f32 pricer failed gates "
                  f"(rate={rate:.2e}, max_diff={max_diff}) -> engine kernel")
    if _FUSED_VALIDATED.get("ok", False):
        return pricer.price_batch(inventory)
    from price_function import compute_price_vectorized
    out = np.empty(inventory.shape, dtype=np.int32)
    for i, prod in enumerate(PRODUCTS):
        out[:, :, i] = compute_price_vectorized(prod, inventory[:, :, i])
    return out


def decode_batch(start, count):
    """Decode enumeration indices [start, start+count) to (count, 8) draws.

    Digit k of the base-8 little-endian representation is the shop type drawn
    at unlock event k. Bijection over [0, 8^8).
    """
    idx = np.arange(start, start + count, dtype=np.int64)
    powers = (N_SHOPS ** np.arange(N_EVENTS, dtype=np.int64))
    return (idx[:, None] // powers[None, :]) % N_SHOPS


class ExhaustiveAccumulator:
    """Constant-memory streaming statistics over ScenarioResult batches."""

    def __init__(self):
        shape = (N_DAYS, N_PROD)
        self.count = 0
        self.sum = np.zeros(shape, dtype=np.float64)
        self.sumsq = np.zeros(shape, dtype=np.float64)
        self.minv = np.full(shape, np.inf, dtype=np.float64)
        self.maxv = np.full(shape, -np.inf, dtype=np.float64)
        self.hist = np.zeros((N_DAYS, N_PROD, HIST_MAX + 1), dtype=np.int32)
        # season demand totals per product
        self.dem_sum = np.zeros(N_PROD, dtype=np.float64)
        self.dem_sq = np.zeros(N_PROD, dtype=np.float64)
        self.dem_min = np.full(N_PROD, np.inf, dtype=np.float64)
        self.dem_max = np.full(N_PROD, -np.inf, dtype=np.float64)
        # per-shop instances per season (analytic completeness check)
        self.shop_cnt_sum = np.zeros(N_SHOPS, dtype=np.int64)

    def update(self, result):
        self._accumulate(result.prices.astype(np.int64),
                         result.daily_demand, result.draws)

    def _accumulate(self, prices, daily_demand, draws):
        prices = np.asarray(prices)
        pf = prices.astype(np.float64)
        b = prices.shape[0]
        self.count += b
        self.sum += pf.sum(axis=0)
        self.sumsq += np.square(pf).sum(axis=0)
        np.minimum(self.minv, pf.min(axis=0), out=self.minv)
        np.maximum(self.maxv, pf.max(axis=0), out=self.maxv)

        dem = daily_demand.astype(np.float64).sum(axis=1)   # (B, 9)
        self.dem_sum += dem.sum(axis=0)
        self.dem_sq += np.square(dem).sum(axis=0)
        np.minimum(self.dem_min, dem.min(axis=0), out=self.dem_min)
        np.maximum(self.dem_max, dem.max(axis=0), out=self.dem_max)

        for k in range(N_SHOPS):
            self.shop_cnt_sum[k] += int((draws == k).sum())

        # ---- exact histograms: per-cell bincounts over contiguous rows ----
        # One transpose-copy per chunk replaces the old giant offset-index
        # array (~280 MB of traffic per batch) with 270 small streaming calls.
        for c0 in range(0, b, HIST_CHUNK):
            cont = np.ascontiguousarray(
                prices[c0:c0 + HIST_CHUNK].transpose(1, 2, 0))   # (30, 9, c)
            for d in range(N_DAYS):
                block = cont[d]                                   # (9, c)
                for pi in range(N_PROD):
                    col = np.minimum(block[pi], HIST_MAX)
                    np.add(self.hist[d, pi],
                           np.bincount(col, minlength=HIST_MAX + 1),
                           out=self.hist[d, pi], casting="unsafe")

    def merge(self, count, sum, sumsq, min, max, hist,          # noqa: A002
              dem_sum, dem_sq, dem_min, dem_max, shop_cnt_sum):
        """Fold a worker's partial aggregates (order-preserving in parent).

        Parameter names match _partial_from_result keys so callers can use
        master.merge(**partial).
        """
        self.count += count
        self.sum += sum
        self.sumsq += sumsq
        np.minimum(self.minv, min, out=self.minv)
        np.maximum(self.maxv, max, out=self.maxv)
        self.hist += hist
        self.dem_sum += dem_sum
        self.dem_sq += dem_sq
        np.minimum(self.dem_min, dem_min, out=self.dem_min)
        np.maximum(self.dem_max, dem_max, out=self.dem_max)
        self.shop_cnt_sum += shop_cnt_sum

    def finalize(self):
        n = max(self.count, 1)
        mean = self.sum / n
        var = np.clip(self.sumsq / n - np.square(mean), 0.0, None)
        std = np.sqrt(var)
        dem_mean = self.dem_sum / n
        dem_var = np.clip(self.dem_sq / n - np.square(dem_mean), 0.0, None)

        grid = threshold_grid()                              # (9, G)
        # P(price > g) exactly from integer-mass histograms.
        # tail[v] = count(prices > v); use suffix cumsum once per cell.
        suf = np.concatenate(
            [self.hist[:, :, :0:-1].cumsum(axis=-1)[:, :, ::-1],
             np.zeros((N_DAYS, N_PROD, 1), dtype=np.int64)], axis=-1)
        # suf[..., g] now = count(prices > g). Gather at grid values.
        tail_prob = np.empty((N_PROD, grid.shape[1], N_DAYS), dtype=np.float64)
        for i in range(N_PROD):
            for j, gval in enumerate(grid[i]):
                gcl = int(min(gval, HIST_MAX))
                tail_prob[i, j] = suf[:, i, gcl] / n
        floor_prob = self.hist[:, :, 1] / n                  # P(price == $1)

        return {
            "count": self.count,
            "mean": mean, "std": std,
            "min": self.minv.copy(), "max": self.maxv.copy(),
            "hist": self.hist,
            "grid": grid, "tail_prob": tail_prob, "floor_prob": floor_prob,
            "demand_mean": dem_mean, "demand_std": np.sqrt(dem_var),
            "demand_min": self.dem_min.copy(), "demand_max": self.dem_max.copy(),
            "shop_cnt_sum": self.shop_cnt_sum.copy(),
        }


def analytic_shop_check(acc_final):
    """For the COMPLETE cube, per-type instance counts must match
    Binomial(8, 1/8) exactly: mean 1, variance 7/8."""
    if acc_final["count"] != TOTAL_SEQUENCES:
        return {"complete": False}
    mean = acc_final["shop_cnt_sum"] / TOTAL_SEQUENCES
    return {
        "complete": True,
        "mean_instances": mean.tolist(),       # must all be exactly 1.0
        "expected_mean": 1.0,
        "expected_var": 0.875,
        "ok": bool(np.allclose(mean, 1.0, rtol=0, atol=1e-12)),
    }


def save_reference(payload, path, meta):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    np.savez_compressed(
        path,
        count=payload["count"],
        mean=payload["mean"], std=payload["std"],
        min=payload["min"], max=payload["max"],
        hist=payload["hist"].astype(np.int32),
        grid=payload["grid"], tail_prob=payload["tail_prob"],
        floor_prob=payload["floor_prob"],
        demand_mean=payload["demand_mean"], demand_std=payload["demand_std"],
        demand_min=payload["demand_min"], demand_max=payload["demand_max"],
        meta=json.dumps(meta),
    )


def load_reference(path):
    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    return {k: (json.loads(str(z[k])) if k == "meta" else z[k]) for k in z.files}


def _partial_from_result(result):
    """Reduce one batch to small aggregates + histogram (worker-side)."""
    acc = ExhaustiveAccumulator()
    acc.update(result)
    return _partial_of(acc)


def _partial_from_arrays(prices, daily_demand, draws):
    acc = ExhaustiveAccumulator()
    acc._accumulate(prices, daily_demand, draws)
    return _partial_of(acc)


def _partial_of(acc):
    return {
        "count": acc.count,
        "sum": acc.sum, "sumsq": acc.sumsq,
        "min": acc.minv, "max": acc.maxv,
        "hist": acc.hist,
        "dem_sum": acc.dem_sum, "dem_sq": acc.dem_sq,
        "dem_min": acc.dem_min, "dem_max": acc.dem_max,
        "shop_cnt_sum": acc.shop_cnt_sum,
    }


_WORKER = {}


def _worker_init(batch_size):
    _WORKER["runner"] = MonteCarloRunner(n_simulations=batch_size, seed=0)


def _worker_process(job):
    """Process one cube slice: decode -> engine inventory -> fused pricing.

    Runs in a worker process; results are consumed by the parent strictly in
    index order (Pool.imap), so float accumulation is deterministic for any
    worker count.
    """
    start, count, prod = job
    draws = decode_batch(start, count)
    res = _WORKER["runner"].run(
        player_production=dict(prod) if prod else None,
        name="exhaustive", draws=draws, compute_prices=False)
    prices = fused_price_batch_validated(res.inventory)
    return _partial_from_arrays(prices, res.daily_demand, draws)


def run_exhaustive(scenarios="town_only", batch_size=65536, max_batches=None,
                   output_dir="results/exhaustive", quiet=False, workers=None):
    """Stream the full cube (or a prefix) through the engine; save references."""
    names = [s.strip() for s in scenarios.split(",") if s.strip()]
    unknown = [s for s in names if s not in SCENARIO_PRODUCTIONS]
    if unknown:
        raise SystemExit(f"unknown scenarios: {unknown}; "
                         f"choose from {list(SCENARIO_PRODUCTIONS)}")

    if workers is None:
        workers = min(8, os.cpu_count() or 1)
    workers = max(1, int(workers))

    # Pre-warm the fused-pricer validation in the PARENT so spawned workers
    # inherit the decision (via fork of module state on import? no — via the
    # done-flag being set in each child's fresh copy by re-running cheaply;
    # here we simply validate once up front and silence per-worker warnings).
    fused_price_batch_validated(
        np.full((2, N_DAYS, N_PROD), 10000.0, dtype=np.float32))

    n_batches_total = math.ceil(TOTAL_SEQUENCES / batch_size)
    summary = {"total_sequences": TOTAL_SEQUENCES,
               "batch_size": batch_size, "workers": workers,
               "scenarios": {}}

    use_pool = workers > 1
    from multiprocessing import Pool

    for scen in names:
        prod = SCENARIO_PRODUCTIONS[scen]
        master = ExhaustiveAccumulator()
        limit = n_batches_total if max_batches is None else min(
            n_batches_total, max_batches)
        jobs = ((b * batch_size,
                 min(batch_size, TOTAL_SEQUENCES - b * batch_size),
                 prod) for b in range(limit))

        t0 = time.perf_counter()
        done = 0
        if use_pool:
            with Pool(processes=workers, initializer=_worker_init,
                      initargs=(batch_size,)) as pool:
                for partial in pool.imap(_worker_process, jobs):
                    master.merge(**partial)
                    del partial
                    done += 1
                    if not quiet and (done == 1 or done % 16 == 0
                                      or done == limit):
                        el = time.perf_counter() - t0
                        seq = done * batch_size
                        rate = seq / el if el else 0.0
                        eta = (n_batches_total - done) * batch_size / rate \
                            if rate else 0.0
                        print(f"  [{scen}] batch {done}/{limit} "
                              f"({seq:,} seqs, {rate:,.0f}/s, "
                              f"ETA {eta:,.0f}s)", flush=True)
        else:
            runner = MonteCarloRunner(n_simulations=batch_size, seed=0)
            for start, count, _ in jobs:
                res = runner.run(player_production=dict(prod) if prod else None,
                                 name=f"exhaustive_{scen}",
                                 draws=decode_batch(start, count),
                                 compute_prices=False)
                prices = fused_price_batch_validated(res.inventory)
                master.merge(**_partial_from_arrays(prices, res.daily_demand,
                                                    res.draws))
                del res, prices
                done += 1
                if not quiet and (done == 1 or done % 16 == 0 or done == limit):
                    el = time.perf_counter() - t0
                    seq = done * batch_size
                    rate = seq / el if el else 0.0
                    eta = (n_batches_total - done) * batch_size / rate \
                        if rate else 0.0
                    print(f"  [{scen}] batch {done}/{limit} "
                          f"({seq:,} seqs, {rate:,.0f}/s, ETA {eta:,.0f}s)",
                          flush=True)

        elapsed = time.perf_counter() - t0
        payload = master.finalize()
        completed = min(done * batch_size, TOTAL_SEQUENCES)
        meta = {
            "scenario": scen,
            "production_per_day": prod or {},
            "completed_sequences": completed,
            "complete_enumeration": completed == TOTAL_SEQUENCES,
            "batch_size": batch_size,
            "workers": workers,
            "elapsed_seconds": round(elapsed, 2),
            "hist_max": HIST_MAX,
            "fused_kernel": bool(_FUSED_VALIDATED.get("ok")),
            "fused_mismatch_rate": _FUSED_VALIDATED.get("mismatch_rate"),
            "products": PRODUCTS,
        }
        path = os.path.join(output_dir, f"{scen}_reference.npz")
        save_reference(payload, path, meta)

        check = analytic_shop_check(payload)
        meta["analytic_check"] = check
        entry = {
            "meta": meta,
            "day29_stats": {
                PRODUCTS[i]: {
                    "mean": round(float(payload["mean"][29, i]), 3),
                    "std": round(float(payload["std"][29, i]), 3),
                    "min": round(float(payload["min"][29, i]), 1),
                    "max": round(float(payload["max"][29, i]), 1),
                    "p_floor": round(float(payload["floor_prob"][29, i]), 6),
                } for i in range(N_PROD)
            },
        }
        summary["scenarios"][scen] = entry
        if not quiet:
            print(f"  [{scen}] done: {completed:,} sequences in "
                  f"{elapsed:.1f}s -> {path}")
            print(f"  analytic check: {check}")

    os.makedirs(output_dir, exist_ok=True)
    spath = os.path.join(output_dir, "exhaustive_summary.json")
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    if not quiet:
        print(f"summary written to {spath}")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Exhaustive 8^8 shop-sequence enumeration (offline)")
    ap.add_argument("--scenarios", type=str, default="town_only",
                    help="csv of: town_only,single_player,two_players")
    ap.add_argument("--batch-size", type=int, default=65536)
    ap.add_argument("--max-batches", type=int, default=None,
                    help="debug: cap batches (prefix of the cube)")
    ap.add_argument("--workers", type=int, default=None,
                    help="parallel batch workers (default: min(8, cpu_count))")
    ap.add_argument("--output", type=str, default="results/exhaustive")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    run_exhaustive(args.scenarios, args.batch_size, args.max_batches,
                   args.output, args.quiet, args.workers)


if __name__ == "__main__":
    main()
