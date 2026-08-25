"""Persistent cross-turn memory and drain ledger tracking."""
from config import PRODUCTS, SHOPS, TURNS_PER_DAY
from .observation_parser import parse_observation

_STATE = {
    "episode": None,
    "prev_inventory": None,
    "prev_shed": None,
    "known_shops": [],
    "town_drain_seen": {},
    "opp_sales_inferred": {},
    "our_units_sold": {},
    "days_seen": set(),
}


def get_state(obs):
    mem = _STATE
    ctx = parse_observation(obs)
    if ctx is None:
        return None, mem

    if mem["episode"] is not None and ctx["day"] < mem["episode"].get("last_day", 0):
        reset_memory(mem)

    mem.setdefault("days_seen", set()).add(ctx["day"])
    mem["episode"] = {"last_day": ctx["day"]}

    _update_drain_ledger(ctx, mem)
    _update_shop_tracker(ctx, mem)
    return ctx, mem


def reset_memory(mem):
    mem["prev_inventory"] = None
    mem["prev_shed"] = None
    mem["known_shops"] = []
    mem["town_drain_seen"] = {}
    mem["opp_sales_inferred"] = {}
    mem["our_units_sold"] = {}
    mem["days_seen"] = set()


def _update_drain_ledger(ctx, mem):
    cur_inv = ctx["inventory"]
    prev_inv = mem.get("prev_inventory")
    if prev_inv is not None:
        expected_drain = dict.fromkeys(PRODUCTS, 0)
        step = ctx["step"]
        if (step - 1) % 4 == 0:
            for shop in mem.get("known_shops", []):
                for p in SHOPS.get(shop, []):
                    mult = 2 if len(SHOPS[shop]) == 1 else 1
                    expected_drain[p] += mult
        if (step - 1) % 24 == 0:
            for p in PRODUCTS:
                if p != "FERTILIZER":
                    expected_drain[p] += 1

        for p in PRODUCTS:
            c = cur_inv.get(p, 10000)
            pv = prev_inv.get(p, 10000)
            actual_diff = c - pv
            exp_loss = expected_drain[p]
            unexplained_add = actual_diff + exp_loss
            our_sold = mem.get("our_units_sold", {}).get(p, 0)
            opp_sold = max(0, unexplained_add - our_sold)
            if opp_sold > 0:
                mem["opp_sales_inferred"][p] = mem.get("opp_sales_inferred", {}).get(p, 0) + opp_sold

    mem["prev_inventory"] = dict(cur_inv)
    mem["our_units_sold"] = {}


def _update_shop_tracker(ctx, mem):
    mem["known_shops"] = list(ctx.get("unlocked_shops", []))
