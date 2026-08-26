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
    """Engine-exact sell quote."""
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


def _solve_shape(func, y, T):
    """Solve _shape(func, x) == y for x >= 0 (y >= 0)."""
    if func == "linear":
        return y
    if func == "sq":
        return math.sqrt(y)
    if func == "sqrt":
        return y * y
    if func == "log":
        return math.expm1(y)
    if func == "log10":
        return 10.0 ** y - 1.0
    if func == "hinge":
        if y <= 1.0:
            return y * T
        u = (15.0 + math.sqrt(32.0 * y - 31.0)) / 16.0
        return u * T
    raise ValueError(func)


def inventory_for_price_at_least(item, min_price):
    """Max units that can be ADDED above I0 while the quote stays >= min_price.

    Returns the glut-side crossing inventory; (level - I0) is the dump budget.
    """
    p = MARKET_PARAMS[item]
    target = max(float(min_price), PRICE_FLOOR + 1)  # strictly above floor
    if target >= p["base"]:
        return float(MARKET_I0)
    y = (p["base"] - target) / amplitude(item, "above")
    return MARKET_I0 + _solve_shape(p["af"], y, p["T"])


def drip_batch_size(item, current_inventory, keep_frac):
    """Largest Q whose LAST unit still quotes >= keep_frac * spot.

    Uses a coarse-to-fine search on the continuous inverse; cheap and exact
    enough for slicing decisions.
    """
    spot = market_price(item, current_inventory)
    threshold = max(2, int(spot * keep_frac))
    limit = inventory_for_price_at_least(item, threshold)
    budget = int(limit - current_inventory)
    return max(0, budget), spot


def total_revenue_estimate(item, start_inventory, quantity):
    """TR of dumping `quantity` units one-at-a-time from start_inventory.

    Respects the $1-floor freeze: units sold at $1 don't shift inventory.
    """
    inv = float(start_inventory)
    total = 0
    for _ in range(int(quantity)):
        px = market_price(item, inv)
        total += px
        if px > PRICE_FLOOR:
            inv += 1.0
    return total


def optimal_dump_quantity(item, start_inventory, min_acceptable):
    """Q* before the marginal quote drops below min_acceptable."""
    inv = float(start_inventory)
    q = 0
    while True:
        px = market_price(item, inv)
        if px < min_acceptable:
            return q
        q += 1
        if px > PRICE_FLOOR:
            inv += 1.0
        else:  # at floor the quote never recovers by adding more
            return q
