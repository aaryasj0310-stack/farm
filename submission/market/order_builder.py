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
    MIN_HANDS_BASE,
    MONEY_RESERVE_DEFAULT,
    WHEAT_BUY_PRICE_BUFFER,
    C4_LIVESTOCK_CUTOFF_DAY,
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
TIER_HIRES = 0
TIER_FEED_WHEAT = 1
TIER_LAND = 2
TIER_SEEDS = 3
TIER_ANIMALS = 4


class OrderBuilder:
    def __init__(self, money_reserve=MONEY_RESERVE_DEFAULT):
        self.reserve = money_reserve

    def reinvest_livestock(self, ctx, intents, max_slots=MAX_MARKET_ORDERS):
        """Invest harvest proceeds while there is still time to place animals.

        Recomputed planner intents count animals in transit and reserve future
        wages. Retain normal affordability, housing and shed checks without
        repeating morning hires.
        """
        if (ctx["day"] >= C4_LIVESTOCK_CUTOFF_DAY
                or not 2 <= ctx["hour"] <= 18
                or not intents.get("buy_animal")):
            return [], {}
        return self.build(ctx, {
            "buy_animal": intents["buy_animal"],
            "buy_wheat": intents.get("buy_wheat", 0),
            "pending_structures": intents.get("pending_structures", {}),
        }, max_slots=max_slots)

    # ------------------------------------------------------------------
    def build(self, ctx, intents, max_slots=MAX_MARKET_ORDERS):
        """intents: MacroPlan.intents dict. Returns (orders, ledger).
        
        Mandatory hire budgeting:
          - Mandatory hires calculate exact hire cost first and reserve that amount.
          - Never let land/seeds/animals/non-survival purchases consume reserved hire money.
          - Survival feed wheat is budgeted before discretionary spending.
          - Discretionary purchases (land, seeds, animals) only draw from remaining discretionary budget.
          - Orders are emitted strictly in priority tier order (hires first, then survival wheat, then land, seeds, animals).
        """
        farm = ctx["farm"]
        money = float(farm.money)
        budget = max(0.0, money - self.reserve)

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}
        wheat_px = market_price("WHEAT", inv.get("WHEAT", 10000))
        remaining_shed_room = max(0, 100 - sum(ctx["private"].shed.values())) if ctx.get("private") and hasattr(ctx["private"], "shed") else 100

        # ---- 1. Mandatory hires: exact cost calculated and reserved first ----
        k = int(intents.get("hire", 0))
        start_hires = getattr(farm, "hires_today", 0)
        hire_cost = 0.0
        affordable_hires = 0
        for i in range(k):
            c = float(_fib(start_hires + i))
            if hire_cost + c <= money:
                hire_cost += c
                affordable_hires += 1
            else:
                break
        mandatory_hire_budget = hire_cost

        # ---- 2. Survival feed wheat: reserved before discretionary spending ----
        available_for_purchases = max(0.0, money - mandatory_hire_budget - self.reserve)
        w_req = int(intents.get("buy_wheat", 0))
        unit_wheat_px = math_ceil(wheat_px * WHEAT_BUY_PRICE_BUFFER)
        w_buyable = 0
        if w_req > 0 and unit_wheat_px > 0:
            w_buyable = min(w_req, int(available_for_purchases // unit_wheat_px), remaining_shed_room)
        survival_feed_budget = float(w_buyable * unit_wheat_px)
        remaining_shed_room = max(0, remaining_shed_room - w_buyable)

        # ---- 3. Discretionary budget: land, seeds, animals ----
        discretionary_budget = max(0.0, available_for_purchases - survival_feed_budget)

        ledger = {
            "budget": round(budget, 2),
            "mandatory_hire_budget": round(mandatory_hire_budget, 2),
            "survival_feed_budget": round(survival_feed_budget, 2),
            "discretionary_budget": round(discretionary_budget, 2),
            "spent_estimate": 0.0,
            "queued": [],
            "dropped": [],
            "orders": [],
        }

        if affordable_hires < k:
            ledger["dropped"].append({
                "kind": "hire_budget",
                "requested": k,
                "affordable": affordable_hires,
            })

        if w_req > w_buyable:
            if w_buyable > 0:
                ledger["dropped"].append({
                    "kind": "wheat",
                    "trimmed_from": w_req,
                    "to": w_buyable,
                })
            else:
                reason = "shed_full" if remaining_shed_room == 0 and int(available_for_purchases // unit_wheat_px) > 0 else "budget"
                ledger["dropped"].append({"kind": "wheat", "reason": reason})

        # Collect tiers
        kept = []
        if affordable_hires > 0:
            kept.append((TIER_HIRES, "hire", {"count": affordable_hires}, mandatory_hire_budget))

        if w_buyable > 0:
            kept.append((TIER_FEED_WHEAT, "wheat", {"n": w_buyable}, survival_feed_budget))

        remaining_discretionary = discretionary_budget

        # Discretionary Tier: Land
        n_extra = len(farm.unlocked) - 1
        if intents.get("buy_land") and n_extra < len(LAND_ORDER):
            land_price = float(LAND_PRICES[n_extra])
            if land_price <= remaining_discretionary + 1e-9:
                kept.append((TIER_LAND, "land", {}, land_price))
                remaining_discretionary -= land_price
            else:
                ledger["dropped"].append({"kind": "land", "reason": "budget"})

        # Discretionary Tier: Seeds
        for crop, n in sorted(intents.get("buy_seed", {}).items()):
            n = int(n)
            if n > 0 and crop in CROPS:
                unit = CROPS[crop]["seed"]
                n_max = int(remaining_discretionary // unit)
                if n_max >= n:
                    kept.append((TIER_SEEDS, "seed", {"crop": crop, "n": n}, float(unit * n)))
                    remaining_discretionary -= unit * n
                elif n_max > 0:
                    kept.append((TIER_SEEDS, "seed", {"crop": crop, "n": n_max}, float(unit * n_max)))
                    remaining_discretionary -= unit * n_max
                    ledger["dropped"].append({
                        "kind": "seed", "crop": crop,
                        "trimmed_from": n, "to": n_max,
                    })
                else:
                    ledger["dropped"].append({"kind": "seed", "crop": crop, "reason": "budget"})

        # Discretionary Tier: Animals
        claimed_structures = {}
        for animal, k_anim in sorted(intents.get("buy_animal", {}).items()):
            k_anim = int(k_anim)
            if k_anim > 0 and animal in ANIMALS:
                struct_type = ANIMALS[animal]["structure"]
                pending_structures = int(intents.get("pending_structures", {}).get(struct_type, 0))
                free_structures = sum(
                    1 for t in farm.iter_tiles()
                    if t.kind == struct_type and not t.is_animal and (
                        not hasattr(farm, "unlocked") or not hasattr(farm, "quadrant_of") or farm.quadrant_of(t.pos) in farm.unlocked
                    )
                ) + pending_structures
                matching_animals = [a for a, info in ANIMALS.items() if info["structure"] == struct_type]
                animals_in_shed = sum(int(ctx["private"].shed.get(a, 0)) for a in matching_animals) if ctx.get("private") else 0
                claimed = claimed_structures.get(struct_type, 0)
                max_buyable = max(0, free_structures - animals_in_shed - claimed)
                room_limited = min(k_anim, max_buyable, remaining_shed_room)
                if room_limited <= 0:
                    ledger["dropped"].append({
                        "kind": "animal",
                        "animal": animal,
                        "reason": "shed_full" if remaining_shed_room <= 0 else "no_empty_structure",
                    })
                    continue

                unit = ANIMALS[animal]["cost"]
                n_max = int(remaining_discretionary // unit)
                actual_buy = min(room_limited, n_max)
                if actual_buy > 0:
                    claimed_structures[struct_type] = claimed + actual_buy
                    remaining_shed_room = max(0, remaining_shed_room - actual_buy)
                    kept.append((TIER_ANIMALS, "animal", {"animal": animal, "n": actual_buy}, float(unit * actual_buy)))
                    remaining_discretionary -= unit * actual_buy
                    if actual_buy < room_limited:
                        ledger["dropped"].append({
                            "kind": "animal", "animal": animal,
                            "trimmed_from": room_limited, "to": actual_buy,
                        })
                else:
                    ledger["dropped"].append({"kind": "animal", "animal": animal, "reason": "budget"})

        # ---- emit engine-format orders, honoring optional max_slots cap -----
        orders = []
        queued = {"hire": 0, "seed": {}, "animal": {}, "wheat": 0, "land": False}
        slots = max_slots

        def take(slot_item):
            nonlocal slots
            if slots is not None:
                if slots <= 0:
                    return False
                slots -= 1
            return True

        spent = mandatory_hire_budget + survival_feed_budget + (discretionary_budget - remaining_discretionary)

        # Determine slot budget for hires at hour 0.
        # If slots is constrained, reserve slots for non-hire items in kept (wheat, land, seeds)
        # so crucial capital expansion and planting orders are not starved by excess hires.
        if slots is not None:
            non_hire_slots_needed = sum(1 for t in kept if t[1] in ("wheat", "land", "seed"))
            max_hire_slots = max(MIN_HANDS_BASE, slots - non_hire_slots_needed)
        else:
            max_hire_slots = None

        for tier, kind, payload, est in sorted(kept, key=lambda t: t[0]):
            if kind == "hire":
                emitted = 0
                while (payload["count"] - emitted > 0 and
                       (slots is None or slots > 0) and
                       (max_hire_slots is None or emitted < max_hire_slots)):
                    orders.append(["HIRE"])
                    if slots is not None:
                        slots -= 1
                    emitted += 1
                queued["hire"] = emitted
                if emitted < payload["count"]:
                    dropped_cnt = payload["count"] - emitted
                    ledger["dropped"].append({
                        "kind": "hire_slots",
                        "count": dropped_cnt,
                        "cost": float(est),
                        "tier": tier,
                    })
            elif kind == "wheat":
                if take(None):
                    orders.append(["BUY_PRODUCT", "WHEAT", int(payload["n"])])
                    queued["wheat"] = int(payload["n"])
                else:
                    ledger["dropped"].append({
                        "kind": "wheat_slots",
                        "n": int(payload["n"]),
                        "cost": float(est),
                        "tier": tier,
                    })
            elif kind == "land":
                next_quadrant = len(farm.unlocked) + 1
                assert next_quadrant != 4, "Quadrant 4 (SE) is permanently hard-blocked and must NEVER be purchased!"
                if take(None):
                    orders.append(["BUY_LAND"])
                    queued["land"] = True
                else:
                    ledger["dropped"].append({
                        "kind": "land_slots",
                        "cost": float(est),
                        "tier": tier,
                    })
            elif kind == "seed":
                if take(None):
                    orders.append(["BUY_SEED", payload["crop"], int(payload["n"])])
                    queued["seed"][payload["crop"]] = int(payload["n"])
                else:
                    ledger["dropped"].append({
                        "kind": "seed_slots",
                        "crop": payload["crop"],
                        "n": int(payload["n"]),
                        "cost": float(est),
                        "tier": tier,
                    })
            elif kind == "animal":
                if take(None):
                    orders.append(["BUY_ANIMAL", payload["animal"], int(payload["n"])])
                    queued["animal"][payload["animal"]] = int(payload["n"])
                else:
                    ledger["dropped"].append({
                        "kind": "animal_slots",
                        "animal": payload["animal"],
                        "n": int(payload["n"]),
                        "cost": float(est),
                        "tier": tier,
                    })

        ledger["queued"] = queued
        ledger["orders"] = [list(o) for o in orders]
        ledger["spent_estimate"] = round(spent, 2)
        ledger["upstream_slots_limited"] = any(d.get("kind", "").endswith("_slots") for d in ledger["dropped"])
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
