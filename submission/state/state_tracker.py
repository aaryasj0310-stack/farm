"""Persistent cross-turn memory: episode detection, drain ledger, deadlines."""
from collections import deque, defaultdict
from config import PRODUCTS, SHOPS, TURNS_PER_DAY, PRICE_FLOOR, log
from observation_parser import parse_observation
try:
    from market.price_math import market_price
except ImportError:
    from price_math import market_price

OPP_MONEY_WINDOW = 24  # sliding window of opponent money deltas (turns)
BUYABLE_PRODUCTS = {"WHEAT", "FERTILIZER"}

# Module-level (survives across turns within one process/episode).
_STATE = {
    "episode": None,
    "prev_inventory": None,
    "prev_shed": None,
    "known_shops": [],
    "town_drain_seen": {},       # product -> units inferred drained by town
    "opp_sales_inferred": {},    # product -> units inferred sold by opponent
    "opp_sales_step": {},        # product -> units inferred sold by opponent on latest step
    "opp_sales_history": deque(maxlen=100),  # (step, product, units) step-stamped history
    "opp_market_inference": {},  # product -> latest step inference dict
    "our_units_sold": {},        # product -> total units we sold (cumulative)
    "our_units_sold_last_step": {},  # product -> units sold on immediate previous step
    "our_units_bought": {},      # product -> total units we bought (cumulative)
    "our_units_bought_last_step": {},  # product -> units bought on immediate previous step
    "prev_opp_money": None,      # opponent money on previous turn
    "opp_money_deltas": deque(maxlen=OPP_MONEY_WINDOW),  # recent delta list
    "noop_attempts": 0,
    "invalid_guard": 0,
    "days_seen": set(),
    "bootstrap_cohort_liabilities": 0,
    "late_continuation_in_flight": False,
    "late_continuation_target_pos": None,
    "late_continuation_max_in_flight": 0,
    "forward_only_feed_holds": [],
}


_RESET_HOOKS = []


def register_reset_hook(hook):
    """Register a callback to be called whenever reset_memory executes."""
    if hook not in _RESET_HOOKS:
        _RESET_HOOKS.append(hook)


def get_state(obs):
    """Parse + update persistent state. Returns (ctx, memory)."""
    mem = _STATE
    ctx = parse_observation(obs)
    if ctx is None:
        return None, mem

    marker = (ctx["day"], id(ctx))
    # New-episode detection: day went backwards or new episode started at Day 0
    reset_this_turn = False
    if mem["episode"] is not None and (
        ctx["day"] < mem["episode"].get("last_day", 0)
        or (ctx["day"] == 0 and (ctx.get("hour", 0) == 0 or ctx.get("step", 0) == 0) and bool(mem.get("days_seen")))
    ):
        log("new episode detected; resetting memory")
        reset_memory(mem)
        reset_this_turn = True

    if mem["episode"] is None or ctx["day"] == 0 and not mem["days_seen"]:
        pass
    mem.setdefault("days_seen", set()).add(ctx["day"])
    mem["episode"] = {"last_day": ctx["day"]}

    if not reset_this_turn:
        _update_drain_ledger(ctx, mem)
        _update_opp_money(ctx, mem)
    _update_shop_tracker(ctx, mem)
    return ctx, mem


def reset_memory(mem=None):
    if mem is None:
        mem = _STATE
    mem["episode"] = None
    mem["prev_inventory"] = None
    mem["prev_shed"] = None
    mem["known_shops"] = []
    mem["town_drain_seen"] = {}
    mem["opp_sales_inferred"] = {}
    mem["opp_sales_step"] = {}
    mem["opp_sales_history"] = deque(maxlen=100)
    mem["opp_market_inference"] = {}
    mem["our_units_sold"] = {}
    mem["our_units_sold_last_step"] = {}
    mem["our_units_bought"] = {}
    mem["our_units_bought_last_step"] = {}
    mem["prev_opp_money"] = None
    mem["opp_money_deltas"] = deque(maxlen=OPP_MONEY_WINDOW)
    mem["noop_attempts"] = 0
    mem["invalid_guard"] = 0
    mem["days_seen"] = set()
    mem["bootstrap_cohort_liabilities"] = 0
    mem["late_continuation_in_flight"] = False
    mem["late_continuation_target_pos"] = None
    mem["late_continuation_max_in_flight"] = 0
    mem["forward_only_feed_holds"] = []
    for hook in _RESET_HOOKS:
        try:
            hook()
        except Exception:
            pass


def _update_drain_ledger(ctx, mem):
    """market_net_drain = diff(market_inventory) - expected_town_consumption.

    Observable equation:
      delta_inventory = (visible_sales) - (buys) - (town_consumption)
      delta_inventory = (our_visible_sales + opp_visible_sales)
                        - (our_buys + opp_buys)
                        - (expected_town)

    Rearranging for unobserved opponent activity:
      residual = delta_inventory + expected_town - our_visible_sales + our_buys
      residual = opp_visible_sales - opp_buys

    Mechanics accounted for:
      1. $1 floor-price sales do NOT increment market inventory (invisible/censored).
      2. BUY_PRODUCT (WHEAT, FERTILIZER) decreases market inventory.
      3. Non-buyable products cannot have opp_buys.
    """
    inv_now = ctx["market"].inventory
    prev = mem["prev_inventory"]
    step_inferences = {}
    step_sales = {}

    if prev is not None:
        shops = mem.get("known_shops", [])
        for item in PRODUCTS:
            prev_inv = prev.get(item, 0)
            cur_inv = inv_now.get(item, 0)
            delta = cur_inv - prev_inv
            expected_town = _expected_town_consumption(item, shops, ctx["step"])
            mem.setdefault("town_drain_seen", {})[item] = \
                mem["town_drain_seen"].get(item, 0) + expected_town

            prev_px = market_price(item, prev_inv)
            cur_px = market_price(item, cur_inv)
            floor_hit = (prev_px <= PRICE_FLOOR) or (cur_px <= PRICE_FLOOR)

            our_sells = mem.get("our_units_sold_last_step", {}).get(item, 0)
            our_buys = mem.get("our_units_bought_last_step", {}).get(item, 0)

            # At or below floor, sales pay $1 and are NOT added to market inventory
            if prev_px <= PRICE_FLOOR:
                our_visible_sells = 0
            else:
                our_visible_sells = our_sells

            residual = delta + expected_town - our_visible_sells + our_buys
            is_buyable = (item in BUYABLE_PRODUCTS)

            if prev_px <= PRICE_FLOOR:
                # Completely floor-censored: sales do not increment inventory.
                # Zero delta does NOT mean opponent sold 0.
                opp_buy_est = max(0.0, -residual) if is_buyable and residual < -0.5 else 0.0
                inf = {
                    "opponent_visible_sales_estimate": 0.0,
                    "opponent_buy_estimate": opp_buy_est,
                    "opponent_sales_lower_bound": 0.0,
                    "opponent_sales_upper_bound": None,
                    "confidence": "low",
                    "censored": True,
                    "visible_sales_est": 0.0,
                    "buy_est": opp_buy_est,
                    "sales_lower_bound": 0.0,
                    "sales_upper_bound": None,
                }
                step_inferences[item] = inf
                step_sales[item] = 0.0

            elif floor_hit and cur_px <= PRICE_FLOOR and residual > 0.5:
                # Reached floor during this step.
                # Residual is a lower bound because further sales may have been censored at $1.
                inf = {
                    "opponent_visible_sales_estimate": residual,
                    "opponent_buy_estimate": 0.0,
                    "opponent_sales_lower_bound": residual,
                    "opponent_sales_upper_bound": None,
                    "confidence": "medium",
                    "censored": True,
                    "visible_sales_est": residual,
                    "buy_est": 0.0,
                    "sales_lower_bound": residual,
                    "sales_upper_bound": None,
                }
                step_inferences[item] = inf
                step_sales[item] = residual
                mem["opp_sales_inferred"][item] = \
                    mem["opp_sales_inferred"].get(item, 0) + residual

            elif not is_buyable:
                # Non-buyable products: opp_buys == 0, so residual = opp_visible_sales
                if residual >= 0.5:
                    inf = {
                        "opponent_visible_sales_estimate": residual,
                        "opponent_buy_estimate": 0.0,
                        "opponent_sales_lower_bound": residual,
                        "opponent_sales_upper_bound": residual,
                        "confidence": "high",
                        "censored": False,
                        "visible_sales_est": residual,
                        "buy_est": 0.0,
                        "sales_lower_bound": residual,
                        "sales_upper_bound": residual,
                    }
                    step_inferences[item] = inf
                    step_sales[item] = residual
                    mem["opp_sales_inferred"][item] = \
                        mem["opp_sales_inferred"].get(item, 0) + residual
                elif residual > -0.5:
                    inf = {
                        "opponent_visible_sales_estimate": 0.0,
                        "opponent_buy_estimate": 0.0,
                        "opponent_sales_lower_bound": 0.0,
                        "opponent_sales_upper_bound": 0.0,
                        "confidence": "high",
                        "censored": False,
                        "visible_sales_est": 0.0,
                        "buy_est": 0.0,
                        "sales_lower_bound": 0.0,
                        "sales_upper_bound": 0.0,
                    }
                    step_inferences[item] = inf
                    step_sales[item] = 0.0
                else:
                    # Negative residual on non-buyable (anomalous drain/noise)
                    inf = {
                        "opponent_visible_sales_estimate": 0.0,
                        "opponent_buy_estimate": 0.0,
                        "opponent_sales_lower_bound": 0.0,
                        "opponent_sales_upper_bound": 0.0,
                        "confidence": "low",
                        "censored": False,
                        "visible_sales_est": 0.0,
                        "buy_est": 0.0,
                        "sales_lower_bound": 0.0,
                        "sales_upper_bound": 0.0,
                    }
                    step_inferences[item] = inf
                    step_sales[item] = 0.0

            else:
                # Buyable product (WHEAT, FERTILIZER) above floor
                if residual < -0.5:
                    # Inventory drop beyond town and our purchases -> opponent purchase!
                    opp_buy_est = -residual
                    inf = {
                        "opponent_visible_sales_estimate": 0.0,
                        "opponent_buy_estimate": opp_buy_est,
                        "opponent_sales_lower_bound": 0.0,
                        "opponent_sales_upper_bound": None,
                        "confidence": "medium",
                        "censored": False,
                        "visible_sales_est": 0.0,
                        "buy_est": opp_buy_est,
                        "sales_lower_bound": 0.0,
                        "sales_upper_bound": None,
                    }
                    step_inferences[item] = inf
                    step_sales[item] = 0.0

                elif residual >= 0.5:
                    # Positive residual -> lower bound on opponent sales
                    inf = {
                        "opponent_visible_sales_estimate": residual,
                        "opponent_buy_estimate": 0.0,
                        "opponent_sales_lower_bound": residual,
                        "opponent_sales_upper_bound": None,
                        "confidence": "medium",
                        "censored": False,
                        "visible_sales_est": residual,
                        "buy_est": 0.0,
                        "sales_lower_bound": residual,
                        "sales_upper_bound": None,
                    }
                    step_inferences[item] = inf
                    step_sales[item] = residual
                    mem["opp_sales_inferred"][item] = \
                        mem["opp_sales_inferred"].get(item, 0) + residual

                else:
                    inf = {
                        "opponent_visible_sales_estimate": 0.0,
                        "opponent_buy_estimate": 0.0,
                        "opponent_sales_lower_bound": 0.0,
                        "opponent_sales_upper_bound": None,
                        "confidence": "medium",
                        "censored": False,
                        "visible_sales_est": 0.0,
                        "buy_est": 0.0,
                        "sales_lower_bound": 0.0,
                        "sales_upper_bound": None,
                    }
                    step_inferences[item] = inf
                    step_sales[item] = 0.0

    mem["opp_market_inference"] = step_inferences
    mem["opp_sales_step"] = step_sales
    cur_step = ctx.get("step", 0) if ctx else 0
    history = mem.setdefault("opp_sales_history", deque(maxlen=100))
    for item, units in step_sales.items():
        if units > 0:
            history.append((cur_step, item, units))
    mem["prev_inventory"] = dict(inv_now)
    # Clear step-level sales and buys for next turn
    mem["our_units_sold_last_step"] = {}
    mem["our_units_bought_last_step"] = {}


def _expected_town_consumption(item, shops, step):
    """Town consumption that occurred at the PREVIOUS step boundary.

    Consumption happens during interpreter processing of the previous action;
    between two consecutive agent observations exactly one step elapsed.
    """
    prev_step = step - 1
    if prev_step < 0:
        return 0.0
    total = 0.0
    if prev_step % 4 == 0:
        for shop in shops:
            products = SHOPS[shop]
            mult = 2 if len(products) == 1 else 1
            if item in products:
                total += mult
    if prev_step % TURNS_PER_DAY == 0 and item != "FERTILIZER":
        total += 1
    return total


def _update_shop_tracker(ctx, mem):
    current = list(ctx["town"].unlocked_shops)
    if len(current) > len(mem.get("known_shops", [])):
        mem["known_shops"] = current
        log(f"shops now: {current}")


def _update_opp_money(ctx, mem):
    """Track opponent money deltas in a bounded sliding window."""
    opp = ctx.get("opponent_farm")
    if opp is None:
        return
    cur_money = opp.money
    prev = mem["prev_opp_money"]
    if prev is not None:
        delta = cur_money - prev
        mem["opp_money_deltas"].append(delta)
    mem["prev_opp_money"] = cur_money


def record_our_sale(product, units):
    mem = _STATE
    mem["our_units_sold"][product] = mem["our_units_sold"].get(product, 0) + units
    mem.setdefault("our_units_sold_last_step", {})[product] = \
        mem.get("our_units_sold_last_step", {}).get(product, 0) + units


def get_our_units_sold(product=None):
    """Return total cumulative units sold for a product, or a copy of all products."""
    if product is not None:
        return _STATE.get("our_units_sold", {}).get(product, 0)
    return dict(_STATE.get("our_units_sold", {}))


def record_our_buy(product, units):
    mem = _STATE
    mem["our_units_bought"][product] = mem["our_units_bought"].get(product, 0) + units
    mem.setdefault("our_units_bought_last_step", {})[product] = \
        mem.get("our_units_bought_last_step", {}).get(product, 0) + units


def get_our_units_bought(product=None):
    """Return total cumulative units bought for a product, or a copy of all products."""
    if product is not None:
        return _STATE.get("our_units_bought", {}).get(product, 0)
    return dict(_STATE.get("our_units_bought", {}))


def get_opp_market_inference(product=None):
    """Return latest step opponent market activity inference dict."""
    if product is not None:
        return _STATE.get("opp_market_inference", {}).get(product, {})
    return dict(_STATE.get("opp_market_inference", {}))


def noop_penalty():
    _STATE["noop_attempts"] += 1


def diagnostics():
    m = _STATE
    deltas = list(m["opp_money_deltas"])
    return {
        "noop_attempts": m["noop_attempts"],
        "our_units_sold": dict(m["our_units_sold"]),
        "our_units_bought": dict(m.get("our_units_bought", {})),
        "opp_sales_inferred": {k: round(v, 1) for k, v in m["opp_sales_inferred"].items()},
        "opp_market_inference": dict(m.get("opp_market_inference", {})),
        "shops_known": list(m.get("known_shops", [])),
        "prev_opp_money": m["prev_opp_money"],
        "opp_money_deltas": deltas,
        "opp_money_delta_sum": sum(deltas),
    }


def get_recent_opp_sales(mem, max_steps=4, current_step=None):
    """Return dict {product: units} sold by opponent within the last max_steps turns."""
    res = defaultdict(float)
    history = mem.get("opp_sales_history", []) if mem else []
    if not history:
        return dict(res)
    if current_step is None:
        current_step = max((s for s, _, _ in history), default=0)
    cutoff = current_step - max_steps
    for step, item, qty in history:
        if step > cutoff and qty > 0:
            res[item] += qty
    return dict(res)
