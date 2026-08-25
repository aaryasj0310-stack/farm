"""Marginal revenue, slippage and optimal batch liquidation sizing.

Execution model (per competition rules):
  - The k-th unit sells at price(initial_inv + units_already_added) — the sell
    price is quoted at PRE-sell inventory.
  - $1 floor freeze: a unit sold while the quote is $1 still pays $1 but does
    NOT enter market inventory, so the floor stays responsive.
"""
import math

from price_curve_engine import MARKET_PARAMS, I0, compute_price


def simulate_sale_path(product, initial_inv, quantity):
    """Sell `quantity` units one at a time. Returns full execution detail."""
    inv = float(initial_inv)
    prices = []
    total = 0
    added = 0
    for _ in range(int(quantity)):
        p = compute_price(product, int(round(inv)))
        prices.append(p)
        total += p
        if p > 1:
            inv += 1.0
            added += 1
        # else: floor freeze — unit sold at $1, inventory unchanged
    q = int(quantity)
    return {
        "product": product,
        "initial_inventory": initial_inv,
        "quantity": q,
        "unit_prices": prices,
        "total_revenue": total,
        "avg_realized_price": (total / q) if q else 0.0,
        "final_inventory": inv,
        "units_added_to_market": added,
    }


def marginal_revenue_series(product, initial_inv, quantity):
    """MR(k) for k = 1..quantity: price quoted for the k-th unit."""
    return simulate_sale_path(product, initial_inv, quantity)["unit_prices"]


def total_revenue(product, initial_inv, quantity):
    return simulate_sale_path(product, initial_inv, quantity)["total_revenue"]


def find_optimal_batch_size(product, initial_inv, min_acceptable_price, max_q=1_000_000):
    """Largest Q* whose every unit executes at >= min_acceptable_price.

    Walks unit executions until the quote drops below the threshold.
    """
    threshold = max(1, int(min_acceptable_price))
    inv = float(initial_inv)
    total = 0
    q = 0
    while q < max_q:
        p = compute_price(product, int(round(inv)))
        if p < threshold:
            break
        total += p
        q += 1
        if p > 1:
            inv += 1.0
        else:
            # $1 floor reached (and freeze active): if $1 is acceptable, every
            # remaining unit also pays $1; otherwise stop here.
            if threshold <= 1:
                total += max_q - q
                q = max_q
            break
    return {
        "product": product,
        "initial_inventory": initial_inv,
        "min_acceptable_price": threshold,
        "optimal_quantity": q,
        "total_revenue": total,
        "avg_realized_price": (total / q) if q else 0.0,
        "terminal_quote": compute_price(product, int(round(inv))),
    }


def slippage_table(product, initial_inv, sizes=(1, 5, 10, 20, 50, 100)):
    """Average realized price vs initial spot quote for various dump sizes."""
    spot = compute_price(product, int(initial_inv))
    rows = []
    for size in sizes:
        res = simulate_sale_path(product, initial_inv, size)
        avg = res["avg_realized_price"]
        rows.append({
            "size": size,
            "spot_price": spot,
            "avg_realized_price": round(avg, 2),
            "slippage_pct": round((1 - avg / spot) * 100, 2) if spot > 0 else 0.0,
            "total_revenue": res["total_revenue"],
            "units_frozen_at_floor": size - res["units_added_to_market"],
        })
    return rows


def floor_distance(product):
    """Units that must be ADDED to I0 before the quote hits the $1 floor.

    Analytic: invert the glut curve to the price-$1 crossing. Log-shaped glut
    curves are unbounded but extremely flat — wheat needs ~2.9M units, so a
    naive unit-walk would take millions of iterations.
    """
    from price_curve_engine import inventory_at_price
    level = inventory_at_price(product, 1)["glut"]
    dist = int(math.ceil(level - I0))
    # sanity: the quote must read $1 at (or within one unit past) that point
    assert compute_price(product, I0 + dist) == 1 or compute_price(product, I0 + dist + 1) == 1
    return dist
