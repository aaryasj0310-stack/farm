"""Tests for exhaustive enumeration: decoder bijection, accumulator exactness,
chunk paths, reference save/load, and a hermetic end-to-end mini-run."""
import json
import os

import numpy as np
import pytest

from exhaustive_enumerator import (
    HIST_MAX,
    N_DAYS,
    N_PROD,
    ExhaustiveAccumulator,
    analytic_shop_check,
    decode_batch,
    load_reference,
    save_reference,
)
from monte_carlo_runner import ScenarioResult


def _fake_result(draws, seed=0):
    """Deterministic ScenarioResult: pure function of draws (split-safe)."""
    n = draws.shape[0]
    base = draws.sum(axis=1, dtype=np.int64)[:, None, None]      # (n,1,1)
    adder = (np.arange(N_DAYS * N_PROD, dtype=np.int64)
             .reshape(1, N_DAYS, N_PROD) % 7)
    prices = np.clip(1 + base * 3 + adder, 1, HIST_MAX).astype(np.int32)
    demand = np.full((n, N_DAYS, N_PROD), 2.0, dtype=np.float32)
    demand[:, 0, 0] = 5.0
    return ScenarioResult(
        name="fake", n_simulations=n, production_per_day={},
        draws=draws,
        daily_demand=demand,
        inventory=np.zeros((n, N_DAYS, N_PROD), dtype=np.float32),
        prices=prices,
    )


# ---------------------------------------------------------------- decoder ---

def test_decode_batch_roundtrip_bijection():
    for idx in (0, 1, 7, 8, 63, 64, 123456, 16_777_215):
        row = decode_batch(idx, 1)[0]
        reencoded = int(sum(int(d) * 8 ** k for k, d in enumerate(row)))
        assert reencoded == idx


def test_decode_batch_uniform_subset():
    # first 4096 indices vary only the low 4 digits -> each combo appears once
    draws = decode_batch(0, 4096)
    assert draws.shape == (4096, 8)
    assert all((draws[:, k] >= 8).sum() == 0 for k in range(8))
    combos = {tuple(row[:4]) for row in draws}
    assert len(combos) == 4096                    # all distinct
    high = draws[:, 4:]
    assert (high == 0).all()                      # high digits untouched


# ------------------------------------------------------------ accumulator ---

def _naive_stats(results):
    prices = np.concatenate([r.prices.astype(np.int64) for r in results])
    dem = np.concatenate([r.daily_demand.sum(axis=1) for r in results])
    return prices, dem.astype(np.float64)


def test_accumulator_matches_naive_reference():
    draws = decode_batch(5000, 300)
    results = [_fake_result(draws[:200]), _fake_result(draws[200:])]

    acc = ExhaustiveAccumulator()
    for r in results:
        acc.update(r)
    got = acc.finalize()

    prices, dem = _naive_stats(results)
    n = prices.shape[0]
    mean = prices.astype(np.float64).mean(axis=0)
    var = prices.astype(np.float64).var(axis=0)
    assert np.allclose(got["mean"], mean)
    assert np.allclose(got["std"], np.sqrt(var))
    assert np.allclose(got["min"], prices.min(axis=0))
    assert np.allclose(got["max"], prices.max(axis=0))

    # histogram reproduces exact integer PMF and floor probability
    p0 = prices[:, 10, 3]
    counts = np.bincount(p0, minlength=HIST_MAX + 1)
    assert np.allclose(got["hist"][10, 3], counts)
    assert pytest.approx(got["floor_prob"][10, 3]) == float((p0 == 1).mean())

    # threshold tail P(p > g) exact at an arbitrary grid value
    g = int(got["grid"][3, 5])
    assert pytest.approx(got["tail_prob"][3, 5][10], abs=1e-12) == \
        float((prices[:, 10, 3] > g).mean())

    # season demand totals
    assert np.allclose(got["demand_mean"], dem.mean(axis=0))
    assert np.allclose(got["demand_std"], dem.std(axis=0))
    assert np.allclose(got["demand_min"], dem.min(axis=0))
    assert np.allclose(got["demand_max"], dem.max(axis=0))


def test_accumulator_chunk_paths_agree():
    draws = decode_batch(99, 257)   # not a multiple of HIST_CHUNK
    single = ExhaustiveAccumulator()
    single.update(_fake_result(draws))
    a = single.finalize()

    two = ExhaustiveAccumulator()
    two.update(_fake_result(draws[:100]))
    two.update(_fake_result(draws[100:]))
    b = two.finalize()

    assert np.array_equal(a["hist"], b["hist"])
    assert np.allclose(a["mean"], b["mean"])
    assert np.allclose(a["std"], b["std"])


def test_merge_path_matches_direct_update():
    """Worker merge() must reproduce direct accumulation bit-for-bit."""
    from exhaustive_enumerator import _partial_from_result
    draws = decode_batch(7, 500)
    r1, r2 = _fake_result(draws[:313]), _fake_result(draws[313:])

    direct = ExhaustiveAccumulator()
    direct.update(r1)
    direct.update(r2)
    a = direct.finalize()

    merged = ExhaustiveAccumulator()
    merged.merge(**_partial_from_result(r1))
    merged.merge(**_partial_from_result(r2))
    b = merged.finalize()

    assert merged.count == direct.count
    assert np.array_equal(a["hist"], b["hist"])
    assert np.array_equal(a["mean"], b["mean"])        # exact float equality
    assert np.allclose(a["std"], b["std"])
    assert np.allclose(a["demand_mean"], b["demand_mean"])
    assert np.array_equal(a["shop_cnt_sum"], b["shop_cnt_sum"])


# ------------------------------------------------- fused pricer parity ----

def test_fused_pricer_matches_engine():
    """F32 fast kernel vs f64 engine kernel.

    Rules-table anchor prices (calibrated to land exactly on integers at
    diff = T) must match BITWISE. On random sweeps, disagreements may only be
    $1 rounding-direction flips on knife-edge cells and rarer than 1e-6.
    """
    from exhaustive_enumerator import FusedPricer
    from price_function import MARKET_PARAMS, compute_price_vectorized
    from town_demand_engine import PRODUCTS
    pricer = FusedPricer()
    rng = np.random.default_rng(777)
    for i, prod in enumerate(PRODUCTS):
        p = MARKET_PARAMS[prod]
        # anchors: rules table P(I0), P(I0-T), P(I0+T), P(I0+2T) + floor
        anchors = np.asarray([10000.0, 10000 - p["T"], 10000 + p["T"],
                              10000 + 2 * p["T"], 10100.0], dtype=np.float32)
        got_a = pricer.price_product(i, anchors[:, None])[:, 0]
        want_a = compute_price_vectorized(prod, anchors.astype(np.float64))
        assert np.array_equal(got_a, want_a), (prod, "anchor mismatch")

        probes = list(rng.integers(6000, 14000, size=4000))
        probes += list(rng.integers(10000, 13000, size=1500))
        arr = np.asarray(probes, dtype=np.float32)
        got = pricer.price_product(i, arr[:, None])[:, 0]
        want = compute_price_vectorized(prod, arr.astype(np.float64))
        diff = np.abs(got - want)
        assert int(diff.max()) <= 1, (prod, "diff > $1")
        assert (diff > 0).mean() <= 2e-3, (prod, "mismatch rate too high")


# ------------------------------------------------------- analytic + I/O ----

def test_analytic_check_flags_incomplete():
    payload = {"count": 100, "shop_cnt_sum": np.arange(8)}
    check = analytic_shop_check(payload)
    assert check["complete"] is False


def test_save_load_roundtrip(tmp_path):
    acc = ExhaustiveAccumulator()
    acc.update(_fake_result(decode_batch(0, 64)))
    payload = acc.finalize()
    path = tmp_path / "ref.npz"
    meta = {"scenario": "town_only", "complete_enumeration": False}
    save_reference(payload, str(path), meta)

    loaded = load_reference(str(path))
    assert loaded["meta"]["scenario"] == "town_only"
    assert np.array_equal(loaded["hist"], payload["hist"].astype(np.int32))
    assert np.allclose(loaded["mean"], payload["mean"])
    assert np.allclose(loaded["tail_prob"], payload["tail_prob"], atol=1e-6)


def test_end_to_end_mini_enumeration(tmp_path, monkeypatch):
    """Hermetic pipeline: patched runner over a tiny prefix of the cube."""
    from exhaustive_enumerator import run_exhaustive

    class FakeRunner:
        def __init__(self, n_simulations, seed):
            self.n_simulations = n_simulations

        def run(self, player_production=None, name="", draws=None,
                compute_prices=True):
            return _fake_result(draws)

    import exhaustive_enumerator as ee
    monkeypatch.setattr(ee, "MonteCarloRunner", FakeRunner)

    out = tmp_path / "exhaustive"
    summary = run_exhaustive("town_only", batch_size=128, max_batches=3,
                             output_dir=str(out), quiet=True, workers=1)
    scen = summary["scenarios"]["town_only"]
    assert scen["meta"]["completed_sequences"] == 384
    assert scen["meta"]["complete_enumeration"] is False

    ref = load_reference(str(out / "town_only_reference.npz"))
    assert int(ref["count"]) == 384
    assert os.path.exists(out / "exhaustive_summary.json")
