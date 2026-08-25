"""Exact Kaggriculture market price function.

Implements the price curve from the game rules:

    price(inv) = base + sign * amp * f(|inv - I0|)
    sign = +1 if inv < I0 (scarcity), -1 if inv > I0 (glut)
    amp  = target * base / f(T)

Floored at $1, rounded to the nearest dollar (Python banker's rounding).
Also provides a vectorized numpy version with identical semantics.
"""
import math

import numpy as np


def shape_fn(name, x, T=None):
    """Evaluate shape function f(x). For 'hinge', T is required."""
    if name == "linear":
        return x
    elif name == "sq":
        return x * x
    elif name == "sqrt":
        return math.sqrt(x)
    elif name == "log":
        return math.log(1 + x)
    elif name == "log10":
        return math.log10(1 + x)
    elif name == "hinge":
        assert T is not None and T > 0
        u = x / T
        return u + 8 * max(0, u - 1) ** 2
    else:
        raise ValueError(f"Unknown shape: {name}")


def _shape_fn_vec(name, x, T=None):
    """Vectorized shape function over a numpy array."""
    x = np.asarray(x, dtype=np.float64)
    if name == "linear":
        return x
    if name == "sq":
        return x * x
    if name == "sqrt":
        return np.sqrt(x)
    if name == "log":
        return np.log1p(x)
    if name == "log10":
        return np.log10(1.0 + x)
    if name == "hinge":
        assert T is not None and T > 0
        u = x / T
        return u + 8.0 * np.maximum(0.0, u - 1.0) ** 2
    raise ValueError(f"Unknown shape: {name}")


MARKET_PARAMS = {
    "WHEAT":      {"base": 25,  "I0": 10000, "T": 400, "below_func": "sqrt",  "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base": 35,  "I0": 10000, "T": 450, "below_func": "hinge", "below_target": 1.00, "above_func": "sqrt",   "above_target": 0.70},
    "TOMATO":     {"base": 60,  "I0": 10000, "T": 200, "below_func": "hinge", "below_target": 0.40, "above_func": "sqrt",   "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "below_func": "sqrt",  "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "I0": 10000, "T": 300, "below_func": "log",   "below_target": 0.20, "above_func": "sq",     "above_target": 3.60},
    "EGG":        {"base": 50,  "I0": 10000, "T": 332, "below_func": "hinge", "below_target": 0.40, "above_func": "log",    "above_target": 0.20},
    "MILK":       {"base": 160, "I0": 10000, "T": 122, "below_func": "sqrt",  "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "I0": 10000, "T": 105, "below_func": "log",   "below_target": 0.20, "above_func": "sq",     "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": 10000, "T": 200, "below_func": "linear","below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}

# Known price points from the rules table (P(I0-T), P(I0+T), P(I0+2T) columns).
KNOWN_PRICE_POINTS = [
    ("WHEAT", 10000, 25),
    ("WHEAT", 9600, 45),    # P(I0-T)
    ("WHEAT", 10400, 20),   # P(I0+T)
    ("CARROT", 9550, 70),
    ("CARROT", 10450, 10),
    ("STRAWBERRY", 9900, 204),
    ("STRAWBERRY", 10100, 1),
    ("MELON", 10300, 1),
    ("MILK", 10122, 1),
    ("EGG", 9668, 70),
]


def compute_price(resource, inventory):
    """Market sell price for 'resource' at the given inventory level.

    Floor is $1. Rounded to nearest integer (banker's rounding).
    """
    p = MARKET_PARAMS[resource]
    base, I0, T = p["base"], p["I0"], p["T"]
    diff = abs(inventory - I0)
    if diff == 0:
        return base

    if inventory < I0:  # scarcity
        func, target = p["below_func"], p["below_target"]
    else:  # glut
        func, target = p["above_func"], p["above_target"]

    f_T = shape_fn(func, T, T)  # f(T) for amplitude normalization
    amp = target * base / f_T
    f_x = shape_fn(func, diff, T)

    sign = 1 if inventory < I0 else -1
    price = base + sign * amp * f_x
    return max(1, round(price))


def compute_price_vectorized(resource, inventories):
    """Vectorized compute_price over a numpy array of inventory levels.

    Matches the scalar implementation exactly for all practical inputs.
    Returns int64 array, floored at $1.
    """
    inv = np.asarray(inventories, dtype=np.float64)
    p = MARKET_PARAMS[resource]
    base, I0, T = p["base"], p["I0"], p["T"]
    out = np.full(inv.shape, float(base))
    scarce = inv < I0
    glut = inv > I0
    diff = np.abs(inv - I0)
    sides = (
        (scarce, p["below_func"], p["below_target"], 1.0),
        (glut, p["above_func"], p["above_target"], -1.0),
    )
    for sel, func, target, sign in sides:
        if sel.any():
            f_T = shape_fn(func, T, T)
            amp = target * base / f_T
            out[sel] = base + sign * amp * _shape_fn_vec(func, diff[sel], T)
    return np.maximum(1, np.round(out)).astype(np.int64)


def validate_known_points(verbose=True):
    """Validate against the known price points. Returns (all_ok, results).

    Each result row: (resource, inventory, expected, got, ok)
    """
    results = []
    all_ok = True
    for resource, inv, expected in KNOWN_PRICE_POINTS:
        got = compute_price(resource, inv)
        ok = got == expected
        all_ok &= ok
        results.append((resource, inv, expected, got, ok))
        if verbose:
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {resource} @ {inv}: expected ${expected}, got ${got}")
    # Cross-check vectorized vs scalar on the same points plus a sweep.
    sweep = list(range(8000, 12001, 37))
    for resource in MARKET_PARAMS:
        scalar = [compute_price(resource, i) for i in sweep]
        vector = compute_price_vectorized(resource, np.array(sweep)).tolist()
        if scalar != vector:
            all_ok = False
            if verbose:
                print(f"  [FAIL] vectorized mismatch for {resource}")
        else:
            if verbose:
                print(f"  [PASS] vectorized matches scalar for {resource}")
    return all_ok, results


if __name__ == "__main__":
    ok, _ = validate_known_points()
    raise SystemExit(0 if ok else 1)
