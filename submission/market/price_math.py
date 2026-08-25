"""Pure-python price math mirroring the engine exactly (no numpy)."""
import math
from config import MARKET_I0, MARKET_PARAMS, PRICE_FLOOR


def _shape(func, x, T):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "log10":
        return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + 8.0 * max(0.0, u - 1.0) ** 2
    return x


def amplitude(item, side):
    p = MARKET_PARAMS[item]
    f = p["bf"] if side == "below" else p["af"]
    target = p["bt"] if side == "below" else p["at"]
    return target * p["base"] / _shape(f, p["T"], p["T"])


def market_price(item, inventory):
    p = MARKET_PARAMS[item]
    base, I0, T = p["base"], MARKET_I0, p["T"]
    inv = float(inventory)
    if inv < I0:
        f = p["bf"]
        amp = p["bt"] * base / _shape(f, T, T)
        price = base + amp * _shape(f, I0 - inv, T)
    else:
        f = p["af"]
        amp = p["at"] * base / _shape(f, T, T)
        price = base - amp * _shape(f, inv - I0, T)
    return max(PRICE_FLOOR, int(round(price)))
