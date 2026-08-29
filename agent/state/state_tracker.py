"""Persistent cross-turn memory: episode detection, drain ledger, deadlines."""
from collections import deque
from config import PRODUCTS, SHOPS, TURNS_PER_DAY, log
from observation_parser import parse_observation

OPP_MONEY_WINDOW = 24  # sliding window of opponent money deltas (turns)

# Module-level (survives across turns within one process/episode).
_STATE = {
    "episode": None,
    "prev_inventory": None,
    "prev_shed": None,
    "known_shops": [],
    "town_drain_seen": {},       # product -> units inferred drained by town
    "opp_sales_inferred": {},    # product -> units inferred sold by opponent
    "our_units_sold": {},        # product -> total units we sold (cumulative)
    "our_units_sold_last_step": {},  # product -> units sold on immediate previous step
    "prev_opp_money": None,      # opponent money on previous turn
    "opp_money_deltas": deque(maxlen=OPP_MONEY_WINDOW),  # recent delta list
    "noop_attempts": 0,
    "invalid_guard": 0,
    "days_seen": set(),
}


def get_state(obs):
    """Parse + update persistent state. Returns (ctx, memory)."""
    mem = _STATE
    ctx = parse_observation(obs)
    if ctx is None:
        return None, mem

    marker = (ctx["day"], id(ctx))
    # New-episode detection: day went backwards or we saw a future day reset.
    reset_this_turn = False
    if mem["episode"] is not None and ctx["day"] < mem["episode"].get("last_day", 0):
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


def reset_memory(mem):
    mem["prev_inventory"] = None
    mem["prev_shed"] = None
    mem["known_shops"] = []
    mem["town_drain_seen"] = {}
    mem["opp_sales_inferred"] = {}
    mem["our_units_sold"] = {}
    mem["our_units_sold_last_step"] = {}
    mem["prev_opp_money"] = None
    mem["opp_money_deltas"] = deque(maxlen=OPP_MONEY_WINDOW)
    mem["noop_attempts"] = 0
    mem["invalid_guard"] = 0
    mem["days_seen"] = set()


def _update_drain_ledger(ctx, mem):
    """market_net_drain = diff(market_inventory) - expected_town_consumption.

    Everything that is not explained by town consumption must be player
    activity (ours or opponent's) -> attribute to opponent after subtracting
    our own recorded step-level sells/buys.
    """
    inv_now = ctx["market"].inventory
    prev = mem["prev_inventory"]
    if prev is not None:
        shops = mem.get("known_shops", [])
        for item in PRODUCTS:
            delta = inv_now.get(item, 0) - prev.get(item, 0)
            expected_town = _expected_town_consumption(item, shops, ctx["step"])
            # delta = net_player_sales - expected_town
            # net_player_sales = delta + expected_town
            net_player = delta + expected_town
            ours_step = mem.get("our_units_sold_last_step", {}).get(item, 0)
            opp_added = max(0.0, net_player - ours_step)
            if opp_added >= 0.5:
                mem["opp_sales_inferred"][item] = \
                    mem["opp_sales_inferred"].get(item, 0) + opp_added
    mem["prev_inventory"] = dict(inv_now)
    # Clear step-level sales for next turn
    mem["our_units_sold_last_step"] = {}


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


def noop_penalty():
    _STATE["noop_attempts"] += 1


def diagnostics():
    m = _STATE
    deltas = list(m["opp_money_deltas"])
    return {
        "noop_attempts": m["noop_attempts"],
        "our_units_sold": dict(m["our_units_sold"]),
        "opp_sales_inferred": {k: round(v, 1) for k, v in m["opp_sales_inferred"].items()},
        "shops_known": list(m.get("known_shops", [])),
        "prev_opp_money": m["prev_opp_money"],
        "opp_money_deltas": deltas,
        "opp_money_delta_sum": sum(deltas),
    }
