"""W-market 1/3: MacroPlanner intents -> valid engine market orders.

Engine semantics honored (kaggriculture.py):
  - max `maxMarketOrdersPerTurn` (10) orders; extras silently dropped
  - HIRE hires exactly ONE hand per order entry, cost fib(hires_today)
  - BUY_LAND costs LAND_PRICES[len(unlocked)-1]; no-op if locked none left
  - BUY_SEED / BUY_ANIMAL: fixed per-unit cost; animals land in the SHED
    and both obey shedCapacity at commit time
  - BUY_PRODUCT only WHEAT/FERTILIZER; quoted at post-buy inventory so the
    effective price drifts UP while buying -> we budget with a buffer
  - any failed commit aborts that order; ordering the queue by priority
    therefore acts as a graceful degradation mechanism

Budget rule: total estimated spend <= money - reserve. Tiers are filled in
priority order and count-based tiers are clamped to what remains affordable.
"""
import os

from config import (
    ANIMALS,
    CROPS,
    LAND_ORDER,
    LAND_PRICES,
    MAX_MARKET_ORDERS,
    MONEY_RESERVE_DEFAULT,
    WHEAT_BUY_PRICE_BUFFER,
)
from market.price_math import market_price


def _fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def hire_total_cost(k_hands, mult=1):
    """Coins for k hires made today (fib(0)+...+fib(k-1))."""
    return sum(_fib(i) for i in range(k_hands)) * mult


# Priority tiers (lower = executed earlier when order slots / cash run short).
TIER_LAND = 0
TIER_FEED_WHEAT = 1
TIER_SEEDS = 2
TIER_ANIMALS = 3
TIER_HIRES = 4


class OrderBuilder:
    def __init__(self, money_reserve=MONEY_RESERVE_DEFAULT):
        self.reserve = money_reserve

    # ------------------------------------------------------------------
    def build(self, ctx, intents):
        """intents: MacroPlan.intents dict. Returns (orders, ledger).
        
        v5.9: Hires are NON-NEGOTIABLE. They get first claim on money,
        regardless of budget/reserve. Seeds, animals, land are bought
        only with what remains after hire cost.
        """
        farm = ctx["farm"]
        money = float(farm.money)
        budget = max(0.0, money - self.reserve)

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}
        wheat_px = market_price("WHEAT", inv.get("WHEAT", 10000))
        shed_room = max(0, 100 - sum(ctx["private"].shed.values()))

        ledger = {"budget": round(budget, 2), "queued": [],
                  "dropped": [], "spent_estimate": 0.0}

        # ---- v5.9: Hires get absolute priority (full money) -----------
        tiers = []
        k = int(intents.get("hire", 0))
        hire_cost = 0.0
        if k > 0:
            hire_cost = float(hire_total_cost(k))
            tiers.append((TIER_HIRES, "hire",
                          {"count": k}, hire_cost))

        # ---- Remaining budget after mandatory hires (protecting reserve) ----
        post_hire_budget = max(0.0, budget - hire_cost)

        # ---- tier 1: seeds -------------------------------------------
        for crop, n in sorted(intents.get("buy_seed", {}).items()):
            n = int(n)
            if n > 0 and crop in CROPS:
                unit = CROPS[crop]["seed"]
                tiers.append((TIER_SEEDS, "seed",
                              {"crop": crop, "n": n}, unit * n))

        # ---- tier 2: feed wheat --------------------------------------
        w = int(intents.get("buy_wheat", 0))
        if w > 0:
            est = math_ceil(wheat_px * WHEAT_BUY_PRICE_BUFFER) * w
            tiers.append((TIER_FEED_WHEAT, "wheat", {"n": w}, est))

        # ---- tier 3: animals -----------------------------------------
        for animal, k in sorted(intents.get("buy_animal", {}).items()):
            k = int(k)
            if k > 0 and animal in ANIMALS:
                struct_type = ANIMALS[animal]["structure"]
                free_structures = sum(
                    1 for t in farm.iter_tiles()
                    if t.kind == struct_type and not t.is_animal
                )
                animals_in_shed = int(ctx["private"].shed.get(animal, 0)) if ctx.get("private") else 0
                max_buyable = max(0, free_structures - animals_in_shed)
                room_limited = min(k, max_buyable, shed_room)
                if room_limited <= 0:
                    ledger["dropped"].append({"kind": "animal",
                                              "animal": animal,
                                              "reason": "no_empty_structure" if max_buyable <= 0 else "shed_full"})
                    continue
                unit = ANIMALS[animal]["cost"]
                tiers.append((TIER_ANIMALS, "animal",
                              {"animal": animal, "n": room_limited},
                              unit * room_limited))

        # ---- tier 4: land --------------------------------------------
        n_extra = len(farm.unlocked) - 1
        land_price = None
        if intents.get("buy_land") and n_extra < len(LAND_ORDER):
            land_price = LAND_PRICES[n_extra]
            tiers.append((TIER_LAND, "land", {}, float(land_price)))

        # ---- fill tiers: hires first (non-negotiable), then rest ------
        spent = 0.0
        kept = []
        for tier, kind, payload, est in sorted(tiers, key=lambda t: t[0]):
            if kind == "hire":
                # Hires use full money — always fit
                kept.append((tier, kind, payload, est))
                spent += est
                continue
            # Everything else uses post-hire budget
            remaining = max(0.0, post_hire_budget - (spent - hire_cost))
            if est <= remaining + 1e-9:
                kept.append((tier, kind, payload, est))
                spent += est
                continue
            # partial trim for count-based kinds
            if kind == "seed":
                unit = CROPS[payload["crop"]]["seed"]
                n_max = int(remaining // unit)
                if n_max > 0:
                    kept.append((tier, "seed",
                                 {"crop": payload["crop"], "n": n_max},
                                 unit * n_max))
                    spent += unit * n_max
                    ledger["dropped"].append(
                        {"kind": "seed", "crop": payload["crop"],
                         "trimmed_from": payload["n"], "to": n_max})
                else:
                    ledger["dropped"].append({"kind": "seed",
                                              "crop": payload["crop"],
                                              "reason": "budget"})
            elif kind == "animal":
                unit = ANIMALS[payload["animal"]]["cost"]
                n_max = int(remaining // unit)
                if n_max > 0:
                    kept.append((tier, "animal",
                                 {"animal": payload["animal"], "n": n_max},
                                 unit * n_max))
                    spent += unit * n_max
                    ledger["dropped"].append(
                        {"kind": "animal", "animal": payload["animal"],
                         "trimmed_from": payload["n"], "to": n_max})
                else:
                    ledger["dropped"].append({"kind": "animal",
                                              "animal": payload["animal"],
                                              "reason": "budget"})
            elif kind == "wheat":
                unit_px = math_ceil(wheat_px * WHEAT_BUY_PRICE_BUFFER)
                n_max = int(remaining // unit_px)
                if n_max > 0:
                    kept.append((tier, "wheat", {"n": n_max},
                                 unit_px * n_max))
                    spent += unit_px * n_max
                    ledger["dropped"].append({"kind": "wheat",
                                               "trimmed_from": payload["n"],
                                               "to": n_max})
                else:
                    ledger["dropped"].append({"kind": "wheat",
                                              "reason": "budget"})
            elif kind == "land":
                ledger["dropped"].append({"kind": "land",
                                          "reason": "budget"})

        # ---- emit engine-format orders, honoring the 10-order cap -----
        orders = []
        queued = {"hire": 0, "seed": {}, "animal": {}, "wheat": 0, "land": False}
        slots = MAX_MARKET_ORDERS

        def take(slot_item):
            nonlocal slots
            if slots <= 0:
                return False
            slots -= 1
            return True

        for tier, kind, payload, est in sorted(kept, key=lambda t: t[0]):
            if kind == "hire":
                emitted = 0
                while payload["count"] - emitted > 0 and slots > 0:
                    orders.append(["HIRE"])
                    slots -= 1
                    emitted += 1
                queued["hire"] = emitted
                if emitted < payload["count"]:
                    ledger["dropped"].append({"kind": "hire_slots"})
            elif kind == "seed":
                if take(None):
                    orders.append(["BUY_SEED", payload["crop"],
                                   int(payload["n"])])
                    queued["seed"][payload["crop"]] = int(payload["n"])
                else:
                    ledger["dropped"].append({"kind": "seed_slots",
                                              "crop": payload["crop"]})
            elif kind == "wheat":
                if take(None):
                    orders.append(["BUY_PRODUCT", "WHEAT", int(payload["n"])])
                    queued["wheat"] = int(payload["n"])
                else:
                    ledger["dropped"].append({"kind": "wheat_slots"})
            elif kind == "animal":
                if take(None):
                    orders.append(["BUY_ANIMAL", payload["animal"],
                                   int(payload["n"])])
                    queued["animal"][payload["animal"]] = int(payload["n"])
                else:
                    ledger["dropped"].append({"kind": "animal_slots",
                                              "animal": payload["animal"]})
            elif kind == "land":
                next_quadrant = len(farm.unlocked) + 1
                assert next_quadrant != 4, "Quadrant 4 (SE) is permanently hard-blocked and must NEVER be purchased!"
                if take(None):
                    orders.append(["BUY_LAND"])
                    queued["land"] = True
                else:
                    ledger["dropped"].append({"kind": "land_slots"})

        ledger["queued"] = queued
        ledger["orders"] = [list(o) for o in orders]
        ledger["spent_estimate"] = round(spent, 2)
        return orders, ledger


def math_ceil(x):
    import math
    return int(math.ceil(x))


def land_price_for(unlocked_count):
    """Price of the NEXT quadrant given number of unlocked quadrants."""
    n_extra = unlocked_count - 1
    if n_extra >= len(LAND_ORDER):
        return None
    return LAND_PRICES[n_extra]


if __name__ == "__main__":
    print("module provides OrderBuilder; see tests for usage")
