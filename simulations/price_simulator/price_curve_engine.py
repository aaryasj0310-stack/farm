"""Exact market price curves for Kaggriculture plus inverse solvers.

price(inv) = max(1, round(base + sign * amp * f(|inv - I0|)))
  sign = +1 if inv < I0 (scarcity), -1 if inv > I0 (glut)
  amp  = target * base / f(T)

Also provides:
  - inventory_at_price(product, target): exact continuous inverse on both branches
  - price_elasticity(product, inventory): analytic dP/dinv
"""
import math

import numpy as np

I0 = 10000
LN10 = math.log(10.0)

MARKET_PARAMS = {
    "WHEAT":      {"base": 25,  "T": 400, "below_func": "sqrt",  "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base": 35,  "T": 450, "below_func": "hinge", "below_target": 1.00, "above_func": "sqrt",   "above_target": 0.70},
    "TOMATO":     {"base": 60,  "T": 200, "below_func": "hinge", "below_target": 0.40, "above_func": "sqrt",   "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "T": 100, "below_func": "sqrt",  "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "T": 300, "below_func": "log",   "below_target": 0.20, "above_func": "sq",     "above_target": 3.60},
    "EGG":        {"base": 50,  "T": 332, "below_func": "hinge", "below_target": 0.40, "above_func": "log",    "above_target": 0.20},
    "MILK":       {"base": 160, "T": 122, "below_func": "sqrt",  "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "T": 105, "below_func": "log",   "below_target": 0.20, "above_func": "sq",     "above_target": 3.20},
    "FERTILIZER": {"base": 100, "T": 200, "below_func": "linear","below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}

# Ground-truth points from the competition rules table.
KNOWN_PRICE_POINTS = [
    ("WHEAT", I0, 25), ("WHEAT", 9600, 45), ("WHEAT", 10400, 20),
    ("CARROT", 9550, 70), ("CARROT", 10450, 10),
    ("TOMATO", 9800, 84),
    ("STRAWBERRY", 9900, 204), ("STRAWBERRY", 10100, 1),
    ("MELON", 10300, 1), ("EGG", 9668, 70), ("MILK", 10122, 1),
]


def shape_fn(name, x, T=None):
    if name == "linear":
        return x
    if name == "sq":
        return x * x
    if name == "sqrt":
        return math.sqrt(x)
    if name == "log":
        return math.log(1 + x)
    if name == "log10":
        return math.log10(1 + x)
    if name == "hinge":
        assert T is not None and T > 0
        u = x / T
        return u + 8 * max(0, u - 1) ** 2
    raise ValueError(f"Unknown shape: {name}")


def _shape_fn_vec(name, x, T=None):
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
        u = x / T
        return u + 8.0 * np.maximum(0.0, u - 1.0) ** 2
    raise ValueError(f"Unknown shape: {name}")


def amplitude(p, side):
    func = p[f"{side}_func"]
    return p[f"{side}_target"] * p["base"] / shape_fn(func, p["T"], p["T"])


def compute_price(product, inventory):
    """Exact sell price. Floor $1, banker's rounding."""
    p = MARKET_PARAMS[product]
    base, T = p["base"], p["T"]
    diff = abs(inventory - I0)
    if diff == 0:
        return base
    if inventory < I0:
        func, target = p["below_func"], p["below_target"]
        sign = 1
    else:
        func, target = p["above_func"], p["above_target"]
        sign = -1
    amp = target * base / shape_fn(func, T, T)
    return max(1, round(base + sign * amp * shape_fn(func, diff, T)))


def compute_price_vectorized(product, inventories):
    inv = np.asarray(inventories, dtype=np.float64)
    p = MARKET_PARAMS[product]
    base, T = p["base"], p["T"]
    out = np.full(inv.shape, float(base))
    diff = np.abs(inv - I0)
    for side, sel in (("below", inv < I0), ("above", inv > I0)):
        if sel.any():
            func = p[f"{side}_func"]
            amp = amplitude(p, side)
            sign = 1.0 if side == "below" else -1.0
            out[sel] = base + sign * amp * _shape_fn_vec(func, diff[sel], T)
    return np.maximum(1, np.round(out)).astype(np.int64)


def _solve_shape(name, y, T=None):
    """Solve f(x) = y for x >= 0 (y >= 0)."""
    if name == "linear":
        return y
    if name == "sq":
        return math.sqrt(y)
    if name == "sqrt":
        return y * y
    if name == "log":
        return math.expm1(y)
    if name == "log10":
        return 10.0 ** y - 1.0
    if name == "hinge":
        if y <= 1.0:
            return y * T
        # 8u^2 - 15u + (8 - y) = 0, take the above-knee root (continuous at y=1)
        u = (15.0 + math.sqrt(32.0 * y - 31.0)) / 16.0
        return u * T
    raise ValueError(name)


def inventory_at_price(product, target_price):
    """Exact continuous inventory levels that produce `target_price`.

    Returns {"scarcity": float or None, "glut": float or None}.
    None means the target is unreachable on that branch (wrong side of base).
    Prices are floored at $1 by the game, so targets < 1 are clamped to 1.
    Rounding to integer dollars means the true step boundary is within +/-0.5.
    """
    p = MARKET_PARAMS[product]
    base = p["base"]
    target = max(float(target_price), 1.0)
    out = {"scarcity": None, "glut": None}
    if target == base:
        out["scarcity"] = float(I0)
        out["glut"] = float(I0)
        return out
    if target > base:
        amp = amplitude(p, "below")
        y = (target - base) / amp
        out["scarcity"] = float(I0 - _solve_shape(p["below_func"], y, p["T"]))
    else:
        amp = amplitude(p, "above")
        y = (base - target) / amp
        out["glut"] = float(I0 + _solve_shape(p["above_func"], y, p["T"]))
    return out


def shape_derivative(name, x, T=None):
    """Analytic f'(x)."""
    if name == "linear":
        return 1.0
    if name == "sq":
        return 2.0 * x
    if name == "sqrt":
        if x <= 0:
            return math.inf
        return 0.5 / math.sqrt(x)
    if name == "log":
        return 1.0 / (1.0 + x)
    if name == "log10":
        return 1.0 / ((1.0 + x) * LN10)
    if name == "hinge":
        u = x / T
        if u <= 1.0:
            return 1.0 / T
        return (1.0 + 16.0 * (u - 1.0)) / T
    raise ValueError(name)


def price_elasticity(product, inventory):
    """Local dP/dinv (per-unit sensitivity; always <= 0).

    Negative means adding inventory (selling) lowers the spot price.
    At exactly I0 the right-hand (glut-side) derivative is returned.
    """
    p = MARKET_PARAMS[product]
    inv = float(inventory)
    diff = abs(inv - I0)
    if inv < I0:
        return -amplitude(p, "below") * shape_derivative(p["below_func"], diff, p["T"])
    return -amplitude(p, "above") * shape_derivative(p["above_func"], diff, p["T"])
