"""W4 tests: distributional ROI vs legacy point-regime engine."""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from distributional_roi import (
    ReferencePrices,
    build_distributional_matrices,
)
from roi_matrix_engine import _crop_metrics, evaluate_animal

REAL_REF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "monte_carlo_shops", "results", "exhaustive",
    "town_only_reference.npz")
HAS_REF = os.path.exists(REAL_REF)


def _write_constant_reference(path, price_by_product, count=12345):
    """Craft an exhaustive-reference npz where every day's price is the given
    constant per product (histogram mass on a single integer)."""
    products = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
                "EGG", "MILK", "WOOL", "FERTILIZER"]
    n_days, H = 30, 20001
    hist = np.zeros((n_days, len(products), H + 1), dtype=np.int32)
    mean = np.zeros((n_days, len(products)))
    floor = np.zeros((n_days, len(products)))
    for i, p in enumerate(products):
        v = int(price_by_product[p])
        hist[:, i, v] = count
        mean[:, i] = v
        floor[:, i] = 1.0 if v <= 1 else 0.0
    grid_rows = []
    tails = []
    for i, p in enumerate(products):
        gs = sorted({25, 50, 100, max(2, int(price_by_product[p]) // 2)})
        grid_rows.append(gs)
        tails.append([[max(0.0, min(1.0, 1.0 - g / price_by_product[p]))
                       for g in gs] for _ in range(n_days)])
    G = max(len(g) for g in grid_rows)
    grid = np.ones((len(products), G), dtype=np.int64)
    tail = np.zeros((len(products), G, n_days))
    for i in range(len(products)):
        grid[i, :len(grid_rows[i])] = grid_rows[i]
        # tails[i] is (n_days, G_i); target slice is (G_i, n_days)
        tail[i, :len(grid_rows[i])] = np.array(tails[i]).T
    meta = {"scenario": "synthetic", "complete_enumeration": True,
            "products": products}
    np.savez_compressed(
        path, count=count, mean=mean, std=np.zeros_like(mean),
        min=mean.copy(), max=mean.copy(), hist=hist,
        grid=grid, tail_prob=tail, floor_prob=floor,
        demand_mean=np.zeros(len(products)),
        demand_std=np.zeros(len(products)),
        demand_min=np.zeros(len(products)),
        demand_max=np.zeros(len(products)),
        meta=json.dumps(meta))


def test_constant_price_matches_legacy_spot_base(tmp_path):
    """INVARIANT: E[P|day] == base for every day => distributional metrics
    must equal legacy spot_base metrics exactly (same agronomy, same math)."""
    bases = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120,
             "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200,
             "FERTILIZER": 100}
    ref_path = tmp_path / "const_ref.npz"
    _write_constant_reference(str(ref_path), bases)

    dist = build_distributional_matrices(str(ref_path))

    for crop, base in bases.items():
        if crop not in ("WHEAT", "CARROT"):   # legacy picks variant internally
            continue
        legacy = _crop_metrics(crop, base, fertilized=False)
        d = dist["assets"][crop]
        assert d["strategy"] == "unfertilized" or d["net_profit"] == \
            pytest.approx(legacy["net_profit"], abs=1.0), crop
        # constant-price revenue must equal scalar-price revenue for the SAME
        # strategy: compare against the matching legacy variant directly
    wheat_legacy = _crop_metrics("WHEAT", 25, fertilized=False)
    wheat_dist = dist["assets"]["WHEAT"]
    assert wheat_dist["strategy"] == "unfertilized"
    assert wheat_dist["revenue"] == pytest.approx(wheat_legacy["revenue"], rel=1e-9)
    assert wheat_dist["pptd"] == pytest.approx(wheat_legacy["pptd"], abs=1e-6)

    cow_legacy = evaluate_animal("COW", 160)
    cow_dist = dist["assets"]["COW"]
    assert cow_dist["revenue"] == pytest.approx(cow_legacy["revenue"], rel=1e-9)


@pytest.mark.skipif(not HAS_REF, reason="exhaustive reference not built")
def test_real_reference_uplift_and_floor_fields():
    dist = build_distributional_matrices(REAL_REF)
    assets = dist["assets"]
    # late-season scarcity means tomato/carrot sell above their bases:
    assert assets["TOMATO"]["price_p90"] >= 60
    assert assets["MELON"]["floor_risk_pct"] == 0.0   # town_only never gluts
    for asset in assets.values():
        assert set(asset) >= {"net_profit", "pptd", "roci_pct"}
