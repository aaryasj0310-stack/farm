"""Concurrent (interleaved, one-unit-at-a-time) market execution simulator.

Models the Kaggle engine rule: orders from both players are processed
concurrently, one unit at a time — P0's unit executes, then P1's unit,
repeating until both queues drain; a player left alone continues solo.

$1-floor freeze: units sold into a $1 quote pay $1 and never enter inventory.
"""
from price_curve_engine import I0, MARKET_PARAMS, compute_price


def parse_order(text):
    """'SELL MELON 50' -> ('SELL', 'MELON', 50)."""
    parts = text.strip().upper().split()
    if len(parts) != 3 or parts[0] != "SELL":
        raise ValueError(f"only SELL orders supported, got: {text!r}")
    action, product, qty = parts
    if product not in MARKET_PARAMS:
        raise ValueError(f"unknown product {product}")
    return action, product, int(qty)


def _normalize(orders):
    """[['SELL','MELON',30]] or ['SELL MELON 30'] -> [{'product','remaining'}]."""
    queue = []
    for o in orders:
        if isinstance(o, str):
            action, product, qty = parse_order(o)
        else:
            action, product, qty = o[0], o[1], int(o[2])
            if action.upper() != "SELL":
                raise ValueError("only SELL orders supported")
        if qty > 0:
            queue.append({"product": product, "remaining": qty})
    return queue


class _PlayerState:
    def __init__(self, name, orders):
        self.name = name
        self.queue = _normalize(orders)
        self.revenue = 0
        self.units = 0
        self.by_product = {}

    def has_units(self):
        return any(o["remaining"] > 0 for o in self.queue)

    def execute_one(self, inventories, trace):
        for order in self.queue:
            if order["remaining"] <= 0:
                continue
            product = order["product"]
            inv = inventories.get(product, float(I0))
            price = compute_price(product, int(round(inv)))
            self.revenue += price
            self.units += 1
            self.by_product.setdefault(product, {"units": 0, "revenue": 0})
            self.by_product[product]["units"] += 1
            self.by_product[product]["revenue"] += price
            if trace is not None:
                trace.append({"player": self.name, "product": product,
                              "inventory_before": inv, "price": price})
            if price > 1:  # floor freeze: $1 sales don't add inventory
                inventories[product] = inv + 1.0
            order["remaining"] -= 1
            return


def simulate_concurrent(p0_orders, p1_orders=(), initial_inventories=None, trace=False):
    """Interleaved execution. Returns per-player results (+ optional trace)."""
    p0 = _PlayerState("P0", p0_orders)
    p1 = _PlayerState("P1", p1_orders)
    inventories = dict(initial_inventories or {})
    events = [] if trace else None

    while p0.has_units() or p1.has_units():
        p0.execute_one(inventories, events)   # P0's unit first each pair
        p1.execute_one(inventories, events)

    def _summary(p):
        avg = p.revenue / p.units if p.units else 0.0
        return {"player": p.name, "revenue": p.revenue, "units": p.units,
                "avg_price": round(avg, 3), "by_product": p.by_product}

    out = {"p0": _summary(p0), "p1": _summary(p1),
           "final_inventories": inventories}
    if trace:
        out["trace"] = events
    return out


def spoiler_attack(product, opponent_qty, my_qty, initial_inv=None):
    """How much does my small order depress the opponent's large one?

    Baseline: opponent sells alone. Attack: we interleave `my_qty` units.
    """
    start = {} if initial_inv is None else {product: float(initial_inv)}
    base = simulate_concurrent([[ "SELL", product, opponent_qty]], [], dict(start))
    atk = simulate_concurrent([["SELL", product, opponent_qty]],
                              [["SELL", product, my_qty]], dict(start))
    damage = base["p0"]["revenue"] - atk["p0"]["revenue"]
    return {
        "product": product,
        "opponent_qty": opponent_qty,
        "my_qty": my_qty,
        "opponent_revenue_alone": base["p0"]["revenue"],
        "opponent_revenue_spoiled": atk["p0"]["revenue"],
        "damage_to_opponent": damage,
        "my_revenue": atk["p1"]["revenue"],
        "my_avg_price": atk["p1"]["avg_price"],
        "net_for_me_vs_selling_later_zero": damage,
        "verdict": ("spoiler profitable vs holding" if atk["p1"]["revenue"] > 0
                    else "no effect"),
    }


def twap_comparison(product, quantity, n_slices, shops=(), initial_inv=None):
    """Dump all now vs slicing into `n_slices` daily chunks with town drain."""
    from recovery_simulator import daily_drain_rate

    start = I0 if initial_inv is None else float(initial_inv)
    now = simulate_concurrent([["SELL", product, quantity]], [],
                              {product: start})
    dump_rev = now["p0"]["revenue"]

    drain = daily_drain_rate(product, shops)
    inv = start
    per_slice = -(-quantity // n_slices)  # ceil division
    remaining = quantity
    slice_rev = 0
    for _ in range(n_slices):
        inv -= drain  # town drains between slices
        batch = min(per_slice, remaining)
        res = simulate_concurrent([["SELL", product, batch]], [], {product: max(inv, 1.0)})
        slice_rev += res["p0"]["revenue"]
        remaining -= batch
        inv = res["final_inventories"].get(product, inv)

    return {
        "product": product,
        "quantity": quantity,
        "n_slices": n_slices,
        "drain_per_day": drain,
        "dump_now_revenue": dump_rev,
        "twap_revenue": slice_rev,
        "delta_twap_minus_dump": slice_rev - dump_rev,
        "recommendation": ("TWAP" if slice_rev > dump_rev else "DUMP NOW"),
    }
