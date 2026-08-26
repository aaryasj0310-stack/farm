"""W1 tests: PriceForecast against the real exhaustive reference."""
import importlib.util
import math
import os

import pytest

from strategy import price_forecast as pf

REAL_REF = pf.DEFAULT_REFERENCE
HAS_REF = os.path.exists(REAL_REF)

# Anchors independently produced by convergence_study.py against this exact
# reference file (worst-cell diagnostics printed exact means).
ANCHOR_MEANS_D29 = {"CARROT": 75.99, "TOMATO": 150.63}


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference npz not built")
def test_load_real_reference_and_version():
    fc = pf.PriceForecast.from_reference(REAL_REF)
    assert fc.table["complete_enumeration"] is True
    assert fc.table["count"] == 16_777_216
    assert len(fc.products) == 9


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference npz not built")
def test_day0_reflects_first_town_center_tick():
    """Day-0 cell = post-first-TC-tick state: quote(I0 - 1) per product.

    Derived once from the engine formula at inventory = I0 - 1:
      wheat  25 + sqrt(1)*1.0            = 26
      carrot 35 + hinge(1/450)*35        = 35.08 -> 35
      tomato 60 + hinge(1/200)*24        = 60.12 -> 60
      strawb 120 + sqrt(1)*8.4           = 128.4 -> 128
      melon  250 + ln(2)*8.7606          = 256.07 -> 256
      egg    50 + hinge(1/332)*20        = 50.06 -> 50
      milk   160 + sqrt(1)*8.6915        = 168.69 -> 169
      wool   200 + ln(2)*8.5779          = 205.95 -> 206
      fertilizer (no demand)             = 100
    Stable model constants -- if the engine changes them, this SHOULD fail.
    """
    fc = pf.PriceForecast.from_reference(REAL_REF)
    day0 = {"WHEAT": 26, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 128,
            "MELON": 256, "EGG": 50, "MILK": 169, "WOOL": 206,
            "FERTILIZER": 100}
    for prod, expected in day0.items():
        assert fc.expected_price(prod, 0) == pytest.approx(expected), prod
        assert fc.std_price(prod, 0) == pytest.approx(0.0, abs=1e-9), prod


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference npz not built")
def test_convergence_report_anchor_means_d29():
    fc = pf.PriceForecast.from_reference(REAL_REF)
    for prod, expected in ANCHOR_MEANS_D29.items():
        assert fc.expected_price(prod, 29) == pytest.approx(expected, abs=0.01), prod


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference npz not built")
def test_carrot_over_100_by_day15_is_impossible():
    # key_questions.json answered P(carrot>$100 by day15) = 0 in MC;
    # the census must agree EXACTLY on a grid threshold.
    fc = pf.PriceForecast.from_reference(REAL_REF)
    grid = fc.table["grid"]["CARROT"]
    if 100 in grid:
        j = grid.index(100)
        assert fc.table["tail_prob"]["CARROT"][j][15] == 0.0
    assert fc.prob_above("CARROT", 15, 100) == 0.0


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference npz not built")
def test_tails_monotone_nonincreasing_in_threshold():
    fc = pf.PriceForecast.from_reference(REAL_REF)
    for prod in ("WHEAT", "MELON", "EGG"):
        tails = [t[25] for _, t in fc._anchors[prod]]
        assert all(a >= b - 1e-12 for a, b in zip(tails, tails[1:])), prod


def test_interp_and_clamping_on_synthetic_table():
    table = {
        "version": 1, "scenario": "fake", "count": 1000, "days": 3,
        "products": ["FOO", "BAR"],
        "mean": {"FOO": [10.0, 20.0, 30.0], "BAR": [5.0, 5.0, 5.0]},
        "std": {"FOO": [0.0] * 3, "BAR": [0.0] * 3},
        "floor_prob": {"FOO": [0.0] * 3, "BAR": [0.5] * 3},
        "quantiles": {"q50": {"FOO": [10.0, 20.0, 30.0],
                              "BAR": [5.0, 5.0, 5.0]}},
        "grid": {"FOO": [8, 12], "BAR": [4, 6]},
        "tail_prob": {"FOO": [[0.9, 0.5, 0.1], [0.4, 0.2, 0.0]],
                      "BAR": [[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]},
    }
    fc = pf.PriceForecast.from_table(table)
    # grid=8 tail over days = [0.9, 0.5, 0.1]; grid=12 tail = [0.4, 0.2, 0.0]
    assert fc.prob_above("FOO", 1, 8) == pytest.approx(0.5)     # exact anchor
    assert fc.prob_above("FOO", 1, 12) == pytest.approx(0.2)
    assert fc.prob_above("FOO", 1, 10) == pytest.approx(0.35)   # midpoint interp
    assert fc.prob_above("FOO", 1, 0) == pytest.approx(0.5)     # clamp low
    # clamp high returns LAST anchor tail (conservative upper bound), not 0:
    assert fc.prob_above("FOO", 1, 999) == pytest.approx(0.2)
    assert fc.expected_price("FOO", 99) == 30.0                 # day clamp
    assert fc.prob_floor("BAR", 2) == 0.5
    assert fc.quantile("BAR", 0, 0.99) == 5.0


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference npz not built")
def test_baked_table_roundtrip(tmp_path):
    fc = pf.PriceForecast.from_reference(REAL_REF)
    baked_path = str(tmp_path / "baked_price_table.py")
    pf.write_baked_table(fc, baked_path)

    spec = importlib.util.spec_from_file_location("bpt", baked_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    fc2 = pf.PriceForecast.from_table(mod.PRICE_TABLE)
    for prod in ("WHEAT", "CARROT", "TOMATO", "MELON"):
        for day in (0, 7, 15, 29):
            assert fc2.expected_price(prod, day) == fc.expected_price(prod, day)
            assert fc2.prob_floor(prod, day) == pytest.approx(
                fc.prob_floor(prod, day))
            thr = fc.table["grid"][prod][3]
            assert fc2.prob_above(prod, day, thr) == pytest.approx(
                fc.prob_above(prod, day, thr), abs=1e-5)


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference npz not built")
def test_quantile_ordering_on_real_reference():
    fc = pf.PriceForecast.from_reference(REAL_REF)
    for prod in ("WHEAT", "TOMATO"):
        seq = [fc.quantile(prod, 25, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
        assert all(a <= b + 1e-9 for a, b in zip(seq, seq[1:])), prod
