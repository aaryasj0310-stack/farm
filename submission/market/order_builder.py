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
    SHED_CAPACITY,
)
from market.price_math import market_price, estimate_wheat_buy_price


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
TIER_FEED_WHEAT = 1        # Unavoidable survival feed
TIER_LAND = 2              # Land expansion
TIER_OPTIONAL_WHEAT = 3    # Optional feed buffering (up to 20 days)
TIER_SEEDS = 4             # Seed planting
TIER_ANIMALS = 5           # Livestock purchases


class OrderBuilder:
    def __init__(self, money_reserve=MONEY_RESERVE_DEFAULT):
        self.reserve = money_reserve

    def reinvest_livestock(self, ctx, intents, max_slots=MAX_MARKET_ORDERS):
        """Invest harvest proceeds while there is still time to place animals.

        Recomputed planner intents count animals in transit and reserve future
        wages. Retain normal affordability, housing and shed checks without
        repeating morning hires.
        """
        try:
            from config import get_point2_feed_mode
            _feed_mode = get_point2_feed_mode()
        except Exception:
            _feed_mode = "shadow"

        if _feed_mode == "live":
            # In live mode, delegate to unified C2B sequential candidate authority
            return self.build(ctx, intents, max_slots=max_slots)

        try:
            from config import SELECTIVE_LIVESTOCK_GATE_ENABLED, SELECTIVE_LIVESTOCK_MAX_DAY
        except ImportError:
            SELECTIVE_LIVESTOCK_GATE_ENABLED = False
            SELECTIVE_LIVESTOCK_MAX_DAY = 14

        allow_reinvest = (ctx["day"] < C4_LIVESTOCK_CUTOFF_DAY) or (
            SELECTIVE_LIVESTOCK_GATE_ENABLED and ctx["day"] <= SELECTIVE_LIVESTOCK_MAX_DAY
        )
        if (not allow_reinvest
                or not 2 <= ctx["hour"] <= 18
                or (not intents.get("buy_animal") and not intents.get("buy_animal_sequence"))):
            return [], {}

        try:
            from config import get_point2_feed_mode
            _feed_mode = get_point2_feed_mode()
        except Exception:
            _feed_mode = "shadow"

        if _feed_mode == "live":
            # Delegate directly to build() with unified C2B candidate authority
            return self.build(ctx, {
                "buy_animal": intents.get("buy_animal", {}),
                "buy_animal_sequence": intents.get("buy_animal_sequence", []),
                "buy_wheat": intents.get("buy_wheat", 0),
                "protected_feed_wheat": intents.get("protected_feed_wheat", 0),
                "optional_feed_wheat": intents.get("optional_feed_wheat", 0),
                "pending_structures": {},
                "execution_snapshot": intents.get("execution_snapshot"),
            }, max_slots=max_slots)

        # Post-cutoff selective livestock: strictly require physically built, empty, unreserved housing.
        # Queued/planned structures, positive candidates, or dynamic capacity never authorize purchases.
        if ctx["day"] >= C4_LIVESTOCK_CUTOFF_DAY:
            farm = ctx.get("farm")
            private = ctx.get("private")

            def _pasture_free(t):
                t_kind = t.get("kind") if isinstance(t, dict) else getattr(t, "kind", "")
                t_anim = t.get("is_animal") if isinstance(t, dict) else getattr(t, "is_animal", False)
                if t_kind != "PASTURE" or t_anim:
                    return False
                if hasattr(farm, "unlocked") and hasattr(farm, "quadrant_of"):
                    t_pos = tuple(t.get("pos")) if isinstance(t, dict) else tuple(t.pos)
                    return farm.quadrant_of(t_pos) in farm.unlocked
                return True

            physical_empty_pastures = sum(1 for t in farm.iter_tiles() if _pasture_free(t)) if farm else 0

            shed_large = 0
            carried_large = 0
            if private:
                if hasattr(private, "shed") and isinstance(private.shed, dict):
                    shed_large = sum(int(private.shed.get(a, 0)) for a in ("COW", "SHEEP"))
                if hasattr(private, "inventories") and isinstance(private.inventories, list):
                    for inv in private.inventories:
                        if isinstance(inv, dict):
                            carried_large += sum(int(inv.get(a, 0)) for a in ("COW", "SHEEP"))

            pending_large = shed_large + carried_large
            guaranteed_empty = max(0, physical_empty_pastures - pending_large)

            if guaranteed_empty <= 0:
                money = float(getattr(farm, "money", 0)) if farm else 0.0
                return [], {
                    "budget": max(0.0, money - self.reserve),
                    "queued": [],
                    "dropped": [{"kind": "animal", "reason": "no_empty_structure"}],
                    "orders": [],
                }

            capped_buy_animal = {}
            remaining_guaranteed = guaranteed_empty
            trimmed_animals = []
            for a, count in intents.get("buy_animal", {}).items():
                cnt = int(count)
                if cnt <= 0:
                    continue
                if a in ("COW", "SHEEP"):
                    alloc = min(cnt, remaining_guaranteed)
                    if alloc > 0:
                        capped_buy_animal[a] = alloc
                        remaining_guaranteed -= alloc
                    if alloc < cnt:
                        trimmed_animals.append({"kind": "animal", "animal": a, "trimmed_from": cnt, "to": alloc})
                else:
                    capped_buy_animal[a] = cnt

            if not any(v > 0 for v in capped_buy_animal.values()):
                money = float(getattr(farm, "money", 0)) if farm else 0.0
                return [], {
                    "budget": max(0.0, money - self.reserve),
                    "queued": [],
                    "dropped": [{"kind": "animal", "reason": "no_empty_structure"}],
                    "orders": [],
                }

            orders, ledger = self.build(ctx, {
                "buy_animal": capped_buy_animal,
                "buy_wheat": intents.get("buy_wheat", 0),
                "pending_structures": {},
            }, max_slots=max_slots)

            if isinstance(ledger, dict) and "dropped" in ledger:
                ledger["dropped"].extend(trimmed_animals)
            return orders, ledger

        return self.build(ctx, {
            "buy_animal": intents.get("buy_animal", {}),
            "buy_wheat": intents.get("buy_wheat", 0),
            "pending_structures": intents.get("pending_structures", {}),
        }, max_slots=max_slots)

    def build_intraday(self, ctx, intents, max_slots=MAX_MARKET_ORDERS):
        """Intraday market turn order compilation (hours 2-18).

        Evaluates strictly in authoritative priority tier order:
        1. survival / mandatory debt (survival feed wheat)
        2. committed hires / feed / seeds (incremental seed demand)
        3. safely profitable SW land (BUY_LAND if authorized)
        4. discretionary livestock reinvestment (with SW shadow capital protection)

        Does not repeat morning hires (hire=0).
        """
        try:
            from config import get_point2_feed_mode
            _feed_mode = get_point2_feed_mode()
        except Exception:
            _feed_mode = "shadow"

        if _feed_mode == "live":
            # Shared C2B sequential live livestock authority
            intents_intraday = {
                "hire": 0,
                "buy_wheat": intents.get("buy_wheat", 0),
                "protected_feed_wheat": intents.get("protected_feed_wheat", 0),
                "optional_feed_wheat": intents.get("optional_feed_wheat", 0),
                "buy_land": bool(intents.get("buy_land", False)),
                "buy_seed": {} if (int(ctx.get("day", 0)) == 0) else intents.get("buy_seed", {}),
                "buy_animal": intents.get("buy_animal", {}),
                "buy_animal_sequence": intents.get("buy_animal_sequence", []),
                "pending_structures": intents.get("pending_structures", {}),
                "execution_snapshot": intents.get("execution_snapshot") or (
                    ctx.get("feed_execution_snapshot") if isinstance(ctx, dict) else getattr(ctx, "feed_execution_snapshot", None)
                ),
            }
            return self.build(ctx, intents_intraday, max_slots=max_slots)

        # Determine permitted livestock under housing checks
        capped_animal = intents.get("buy_animal", {})
        if ctx["day"] >= C4_LIVESTOCK_CUTOFF_DAY:
            _anim_orders, _anim_ledger = self.reinvest_livestock(ctx, intents, max_slots=max_slots)
            if _anim_ledger and "queued" in _anim_ledger and isinstance(_anim_ledger["queued"], dict):
                capped_animal = _anim_ledger["queued"].get("animal", {})
            else:
                capped_animal = {}

        intents_intraday = {
            "hire": 0,
            "buy_wheat": intents.get("buy_wheat", 0),
            "protected_feed_wheat": intents.get("protected_feed_wheat", 0),
            "optional_feed_wheat": intents.get("optional_feed_wheat", 0),
            "buy_land": bool(intents.get("buy_land", False)),
            "buy_seed": {} if (int(ctx.get("day", 0)) == 0) else intents.get("buy_seed", {}),
            "buy_animal": capped_animal,
            "pending_structures": intents.get("pending_structures", {}),
            "execution_snapshot": intents.get("execution_snapshot"),
        }
        return self.build(ctx, intents_intraday, max_slots=max_slots)

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
        day = int(ctx.get("day", 0))
        hour = int(ctx.get("hour", 0))
        money = float(farm.money)
        budget = max(0.0, money - self.reserve)

        inv = {p: float(v) for p, v in ctx["market"].inventory.items()}
        wheat_px = market_price("WHEAT", inv.get("WHEAT", 10000))
        unit_wheat_px = estimate_wheat_buy_price(ctx)
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
        if "protected_feed_wheat" in intents:
            w_protected_req = max(0, int(intents["protected_feed_wheat"]))
        else:
            w_protected_req = w_req
        w_optional_req = max(0, w_req - w_protected_req)

        w_protected_buyable = 0
        if w_protected_req > 0 and unit_wheat_px > 0:
            w_protected_buyable = min(w_protected_req, int(available_for_purchases // unit_wheat_px), remaining_shed_room)
        protected_feed_budget = float(w_protected_buyable * unit_wheat_px)
        survival_feed_budget = protected_feed_budget
        remaining_shed_room = max(0, remaining_shed_room - w_protected_buyable)

        # ---- Point 2 Live Treasury Hold & Fresh Live Ledger ----
        try:
            from config import get_point2_feed_mode
            _feed_mode = get_point2_feed_mode()
        except Exception:
            _feed_mode = "shadow"

        is_live_feed_mode = (_feed_mode == "live")
        remaining_existing_feed_hold = 0.0
        live_ledger = None
        existing_herd_feasible = True
        is_safe_exec = True
        live_execution_status = "safe"
        live_execution_reason = ""
        live_failure_reason = None
        snapshot = None

        if is_live_feed_mode:
            try:
                from strategy.feed_feasibility import (
                    build_fresh_live_ledger,
                    compute_remaining_existing_feed_hold,
                    check_live_livestock_execution_safety,
                )
                snapshot = intents.get("execution_snapshot") or (
                    ctx.get("feed_execution_snapshot") if isinstance(ctx, dict) else getattr(ctx, "feed_execution_snapshot", None)
                )
                live_ledger = build_fresh_live_ledger(
                    ctx=ctx,
                    hard_cash_hold=self.reserve + mandatory_hire_budget,
                    strategic_cash_hold=0.0,
                    execution_snapshot=snapshot,
                    market_inventory=inv,
                )
                existing_ok, existing_res, remaining_existing_feed_hold = compute_remaining_existing_feed_hold(
                    ledger=live_ledger,
                    retained_wheat=w_protected_buyable,
                    unit_price=unit_wheat_px,
                )
                existing_herd_feasible = existing_ok
                unfed_placed = live_ledger.unfed_placed_today
                is_safe_exec, exec_status, exec_reason = check_live_livestock_execution_safety(
                    snapshot=snapshot, unfed_placed_today=unfed_placed
                )
                live_execution_status = exec_status
                live_execution_reason = exec_reason
            except Exception as exc:
                live_failure_reason = str(exc)
                existing_herd_feasible = False
                is_safe_exec = False
                live_execution_status = "feed_execution_unverified"
                live_execution_reason = f"Phase-C exception: {exc}"
                remaining_existing_feed_hold = None

        # ---- 3. Discretionary budget: land, optional feed buffer, seeds, animals ----
        if is_live_feed_mode:
            if live_failure_reason is not None:
                # Catastrophic live failure: fail closed for discretionary spending!
                # Unknown hold cannot release cash to land/seeds/animals.
                discretionary_budget = 0.0
            else:
                discretionary_budget = max(0.0, available_for_purchases - protected_feed_budget - (remaining_existing_feed_hold or 0.0))
        else:
            discretionary_budget = max(0.0, available_for_purchases - protected_feed_budget)

        ledger = {
            "budget": round(budget, 2),
            "mandatory_hire_budget": round(mandatory_hire_budget, 2),
            "survival_feed_budget": round(protected_feed_budget, 2),
            "protected_feed_budget": round(protected_feed_budget, 2),
            "optional_feed_budget": 0.0,
            "w_protected_buyable": w_protected_buyable,
            "w_opt_buyable": 0,
            "w_buyable": w_protected_buyable,
            "discretionary_budget": round(discretionary_budget, 2),
            "remaining_existing_feed_hold": round(remaining_existing_feed_hold, 2) if remaining_existing_feed_hold is not None else 0.0,
            "spent_estimate": 0.0,
            "queued": [],
            "dropped": [],
            "orders": [],
        }
        if is_live_feed_mode:
            ledger["point2_live_authority"] = True
            ledger["existing_herd_feasible"] = existing_herd_feasible
            ledger["remaining_existing_feed_hold"] = round(remaining_existing_feed_hold, 2) if remaining_existing_feed_hold is not None else None
            ledger["is_live_livestock_safe"] = is_safe_exec
            ledger["live_execution_status"] = live_execution_status
            ledger["live_execution_reason"] = live_execution_reason
            ledger["live_failure_reason"] = live_failure_reason
            ledger["retained_protected_wheat"] = w_protected_buyable
            ledger["retained_optional_wheat"] = 0
            if snapshot:
                ledger["execution_confidence"] = getattr(snapshot, "execution_confidence", "high")
                ledger["verified_feed_targets"] = list(getattr(snapshot, "verified_feed_targets", []))
                ledger["verified_feed_count"] = getattr(snapshot, "verified_feed_count", len(getattr(snapshot, "verified_feed_targets", [])))

        if affordable_hires < k:
            ledger["dropped"].append({
                "kind": "hire_budget",
                "requested": k,
                "affordable": affordable_hires,
            })

        if w_protected_req > w_protected_buyable:
            if w_protected_buyable > 0:
                ledger["dropped"].append({
                    "kind": "wheat_protected",
                    "trimmed_from": w_protected_req,
                    "to": w_protected_buyable,
                })
            else:
                reason = "shed_full" if remaining_shed_room == 0 and int(available_for_purchases // unit_wheat_px) > 0 else "budget"
                ledger["dropped"].append({"kind": "wheat_protected", "reason": reason})

        # Collect tiers
        kept = []
        if affordable_hires > 0:
            kept.append((TIER_HIRES, "hire", {"count": affordable_hires}, mandatory_hire_budget))

        if w_protected_buyable > 0:
            kept.append((TIER_FEED_WHEAT, "wheat_protected", {"n": w_protected_buyable, "is_protected": True}, protected_feed_budget))

        remaining_discretionary = discretionary_budget

        # Discretionary Tier: Land (protected feed outranks land, but land outranks optional feed buffer)
        n_extra = len(farm.unlocked) - 1
        if intents.get("buy_land") and n_extra < len(LAND_ORDER):
            land_price = float(LAND_PRICES[n_extra])
            if land_price <= remaining_discretionary + 1e-9:
                kept.append((TIER_LAND, "land", {}, land_price))
                remaining_discretionary -= land_price
            else:
                reason = "live_failure" if live_failure_reason is not None else "budget"
                ledger["dropped"].append({"kind": "land", "reason": reason})

        # Discretionary Tier: Optional Feed Wheat (routine buffer)
        w_opt_buyable = 0
        if w_optional_req > 0 and unit_wheat_px > 0:
            w_opt_buyable = min(w_optional_req, int(remaining_discretionary // unit_wheat_px), remaining_shed_room)
        optional_feed_budget = float(w_opt_buyable * unit_wheat_px)
        remaining_shed_room = max(0, remaining_shed_room - w_opt_buyable)
        remaining_discretionary -= optional_feed_budget

        ledger["optional_feed_budget"] = round(optional_feed_budget, 2)
        ledger["w_opt_buyable"] = w_opt_buyable
        ledger["w_buyable"] = w_protected_buyable + w_opt_buyable

        if w_optional_req > w_opt_buyable:
            if w_opt_buyable > 0:
                ledger["dropped"].append({
                    "kind": "wheat_optional",
                    "trimmed_from": w_optional_req,
                    "to": w_opt_buyable,
                })
            else:
                reason = "live_failure" if live_failure_reason is not None else ("shed_full" if remaining_shed_room == 0 and int(remaining_discretionary // unit_wheat_px) > 0 else "budget")
                ledger["dropped"].append({"kind": "wheat_optional", "reason": reason})

        if w_opt_buyable > 0:
            kept.append((TIER_OPTIONAL_WHEAT, "wheat_optional", {"n": w_opt_buyable, "is_protected": False}, optional_feed_budget))

        # Discretionary Tier: Seeds
        try:
            from config import BOOTSTRAP_LIVESTOCK_ARM
        except Exception:
            BOOTSTRAP_LIVESTOCK_ARM = "none"
        is_boot_day0 = bool(day == 0 and hour == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None))

        if is_boot_day0:
            # Stage 2: Inviolable Minimum Crop Floor (4 Melons + 4 Wheat = $360) committed before animals
            min_floor_seeds = {"MELON": 4, "WHEAT": 4}
            for crop, n in sorted(min_floor_seeds.items()):
                unit = CROPS[crop]["seed"]
                kept.append((TIER_SEEDS, "seed", {"crop": crop, "n": n}, float(unit * n)))
                remaining_discretionary -= unit * n
        else:
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
                        reason = "live_failure" if live_failure_reason is not None else "budget"
                        ledger["dropped"].append({"kind": "seed", "crop": crop, "reason": reason})

        # Discretionary Tier: Animals
        # Near-term SW protection: protect SW land capital ($2000) from discretionary animals
        # ONLY when SW is currently affordable or conservatively reachable near-term.
        sw_shadow_reserve = 0.0
        discretionary_livestock_suppressed = False
        try:
            from config import SW_OWNERSHIP_MODE, LAND_BUY_LAST_DAY
            use_experiment_sw = (SW_OWNERSHIP_MODE in ("early_liquidity", "pure_economic"))
        except Exception:
            use_experiment_sw = False
            LAND_BUY_LAST_DAY = 18

        if use_experiment_sw and "SW" not in farm.unlocked and not any(t[1] == "land" for t in kept) and 7 <= ctx.get("day", 0) <= LAND_BUY_LAST_DAY:
            try:
                from strategy.expansion_planner import compute_conservative_inflows_before_hire
                inflows_24h = compute_conservative_inflows_before_hire(farm, ctx.get("private"))
            except Exception:
                inflows_24h = 0.0
            near_term_obligations = mandatory_hire_budget + survival_feed_budget + self.reserve
            if (money + inflows_24h) >= 2000.0 + near_term_obligations:
                sw_shadow_reserve = 2000.0

        can_buy_animals = True
        if is_live_feed_mode:
            # =========================================================================
            # Point 2 Phase C2B — Sequential Live Candidate Authority
            # =========================================================================
            candidate_sequence_requested: List[str] = []
            candidate_sequence_source: str = "none"
            candidate_sequence_accepted: List[str] = []
            candidate_sequence_rejected: List[str] = []
            candidate_decisions: List[Dict[str, Any]] = []

            # Check sequence input
            candidate_sequence_input = intents.get("buy_animal_sequence")
            legacy_buy_animal = intents.get("buy_animal", {})
            has_legacy_animals = any(int(v) > 0 for v in legacy_buy_animal.values()) if isinstance(legacy_buy_animal, dict) else False

            valid_sequence = True
            if candidate_sequence_input is None:
                if has_legacy_animals:
                    valid_sequence = False
                    ledger["dropped"].append({"kind": "animal", "reason": "invalid_candidate_sequence"})
                else:
                    candidate_sequence_requested = []
            elif not isinstance(candidate_sequence_input, list):
                valid_sequence = False
                ledger["dropped"].append({"kind": "animal", "reason": "invalid_candidate_sequence"})
            else:
                candidate_sequence_requested = [str(a) for a in candidate_sequence_input]
                candidate_sequence_source = "macro_sequence" if ctx.get("day", 0) < 12 else "late_selective"

            # Compute remaining market order slots available for animals
            available_animal_order_slots = None
            if max_slots is not None:
                non_hire_prefix_slots = sum(1 for t in kept if t[1] in ("wheat", "wheat_protected", "wheat_optional", "land", "seed"))
                hire_payload_count = sum(t[2]["count"] for t in kept if t[1] == "hire")
                max_hire = max(MIN_HANDS_BASE, max_slots - non_hire_prefix_slots) if hire_payload_count > 0 else 0
                actual_hires = min(hire_payload_count, max_hire, max_slots)
                slots_used_by_prefix = actual_hires + non_hire_prefix_slots
                available_animal_order_slots = max(0, max_slots - slots_used_by_prefix)

            # Global Gates & Execution Check
            can_start_replay = valid_sequence and (len(candidate_sequence_requested) > 0)
            global_rejection_reason = None

            if can_start_replay:
                if live_failure_reason is not None:
                    global_rejection_reason = "live_failure"
                elif not existing_herd_feasible:
                    global_rejection_reason = "existing_herd_infeasible"
                elif not is_safe_exec:
                    global_rejection_reason = "feed_execution_unverified"
                elif snapshot is None:
                    global_rejection_reason = "post_unit_state_unverified"
                elif not getattr(snapshot, "post_unit_state_verified", False):
                    global_rejection_reason = "post_unit_state_unverified"

            accepted_candidates = []
            accepted_species_order = []
            accepted_species_set = set()
            accepted_housing = None
            working_ledger = None
            day = ctx.get("day", 0)
            hour = ctx.get("hour", 0)

            # Build LiveHousingState
            try:
                from strategy.feed_feasibility import (
                    build_live_housing_state,
                    evaluate_incremental_candidate,
                    commit_candidate_reservation,
                    evaluate_existing_herd_feasibility,
                    build_fresh_live_ledger,
                )
                accepted_housing = build_live_housing_state(
                    execution_snapshot=snapshot,
                    farm=farm,
                    private=ctx.get("private"),
                    day=day,
                )
                try:
                    from config import BOOTSTRAP_LIVESTOCK_ARM
                except Exception:
                    BOOTSTRAP_LIVESTOCK_ARM = "none"
                if day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None):
                    pending_structures = intents.get("pending_structures", {})
                    accepted_housing.pending_pastures = int(pending_structures.get("PASTURE", 0))
                    accepted_housing.pending_coops = int(pending_structures.get("COOP", 0))
            except Exception as exc:
                can_start_replay = False
                global_rejection_reason = "live_candidate_exception"
                ledger["dropped"].append({"kind": "animal", "reason": "live_candidate_exception", "error": str(exc)})

            # Post-unit shed occupancy and worker storable inventory
            if snapshot is not None:
                base_shed_occupancy = getattr(snapshot, "post_unit_shed_occupancy", 0)
                worker_rollover_inventory = getattr(snapshot, "post_unit_worker_inventory_total", 0)
            else:
                base_shed_occupancy = 0
                worker_rollover_inventory = 0

            total_retained_wheat = w_protected_buyable + w_opt_buyable

            # Construct working candidate ledger from retained prefix
            if can_start_replay and global_rejection_reason is None:
                try:
                    committed_non_animal_spend = (
                        mandatory_hire_budget
                        + sum(float(t[3]) for t in kept if t[1] == "land")
                        + sum(float(t[3]) for t in kept if t[1] == "seed")
                    )
                    working_ledger = build_fresh_live_ledger(
                        ctx=ctx,
                        hard_cash_hold=self.reserve + committed_non_animal_spend,
                        strategic_cash_hold=sw_shadow_reserve,
                        execution_snapshot=snapshot,
                        market_inventory=inv,
                    )
                    if total_retained_wheat > 0:
                        wheat_cost = float(total_retained_wheat * unit_wheat_px)
                        working_ledger.scheduled_market_purchases.append({
                            "day": working_ledger.day,
                            "units": total_retained_wheat,
                            "cost": wheat_cost,
                            "purpose": "retained_wheat",
                        })
                        working_ledger.observed_cash = max(0.0, working_ledger.observed_cash - wheat_cost)

                    ok_prefix, res_prefix = evaluate_existing_herd_feasibility(working_ledger)
                    if not ok_prefix:
                        global_rejection_reason = "existing_herd_infeasible"
                    else:
                        working_ledger.existing_feed_cash_hold = float(res_prefix.existing_feed_cash_hold)
                except Exception as exc:
                    global_rejection_reason = "live_candidate_exception"
                    ledger["dropped"].append({"kind": "animal", "reason": "live_candidate_exception", "error": str(exc)})

            baseline_operational_min_wheat_slack = (
                float(res_prefix.minimum_wheat_slack)
                if (can_start_replay and global_rejection_reason is None and 'res_prefix' in locals() and ok_prefix and res_prefix and hasattr(res_prefix, "minimum_wheat_slack"))
                else (float(existing_res.minimum_wheat_slack) if ('existing_res' in locals() and existing_res and hasattr(existing_res, "minimum_wheat_slack")) else 0.0)
            )
            current_operational_min_wheat_slack = baseline_operational_min_wheat_slack

            # Evaluate sequence
            if can_start_replay:
                candidate_stage_base_ledger = working_ledger.clone() if working_ledger is not None else None
                candidate_stage_base_housing = accepted_housing.clone() if accepted_housing is not None else None
                slots_left = available_animal_order_slots
                provisional_list = intents.get("provisional_candidates", [])

                # Pre-NE Capital Admission Policy State
                ne_locked = bool("NE" not in farm.unlocked) if (farm and hasattr(farm, "unlocked")) else False
                try:
                    from config import get_point2_pre_ne_capital_mode
                    pre_ne_capital_mode = get_point2_pre_ne_capital_mode()
                except Exception:
                    pre_ne_capital_mode = "off"

                if ne_locked and pre_ne_capital_mode in ("ne_first", "ne_escrow"):
                    if pre_ne_capital_mode == "ne_first":
                        initial_ne_envelope = 0.0
                    else:  # ne_escrow
                        farm_cash = float(farm.money) if (farm and hasattr(farm, "money")) else (
                            float(ctx.get("farm", {}).get("money", 0.0)) if isinstance(ctx.get("farm"), dict) else 0.0
                        )
                        non_livestock_holds = (
                            mandatory_hire_budget
                            + sum(float(t[3]) for t in kept if t[1] == "land")
                            + sum(float(t[3]) for t in kept if t[1] == "seed")
                            + (float(total_retained_wheat * unit_wheat_px) if total_retained_wheat > 0 else 0.0)
                            + float(self.reserve)
                        )
                        ne_land_hold = 1000.0
                        initial_ne_envelope = max(0.0, farm_cash - non_livestock_holds - ne_land_hold)
                else:
                    initial_ne_envelope = float('inf')

                remaining_ne_envelope = initial_ne_envelope

                try:
                    for seq_idx, species in enumerate(candidate_sequence_requested):
                        cand_id = f"live_{day}_{seq_idx}_{species}"
                        if isinstance(provisional_list, list) and seq_idx < len(provisional_list):
                            cand_id = provisional_list[seq_idx].get("candidate_id", cand_id)

                        if global_rejection_reason is not None:
                            candidate_sequence_rejected.append(species)
                            ledger["dropped"].append({"kind": "animal", "animal": species, "reason": global_rejection_reason})
                            candidate_decisions.append({
                                "candidate_id": cand_id,
                                "sequence_index": seq_idx,
                                "species": species,
                                "accepted": False,
                                "rejection_reason": global_rejection_reason,
                                "feed_feasible": False,
                            })
                            continue

                        # Gate 1: Species validity
                        if species not in ANIMALS:
                            candidate_sequence_rejected.append(species)
                            ledger["dropped"].append({"kind": "animal", "animal": species, "reason": "invalid_species"})
                            candidate_decisions.append({
                                "candidate_id": cand_id,
                                "sequence_index": seq_idx,
                                "species": species,
                                "accepted": False,
                                "rejection_reason": "invalid_species",
                                "feed_feasible": False,
                            })
                            continue

                        # Gate 2: Physical Housing
                        housing_before = accepted_housing.to_dict()
                        allow_pending_housing = bool(day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None))
                        if not accepted_housing.can_house(species, allow_pending=allow_pending_housing):
                            h_reason = "post_cutoff_physical_housing_required" if day >= 12 else "no_physical_housing"
                            candidate_sequence_rejected.append(species)
                            ledger["dropped"].append({"kind": "animal", "animal": species, "reason": h_reason})
                            candidate_decisions.append({
                                "candidate_id": cand_id,
                                "sequence_index": seq_idx,
                                "species": species,
                                "accepted": False,
                                "rejection_reason": h_reason,
                                "feed_feasible": True,
                                "housing_before": housing_before,
                                "housing_after": housing_before,
                            })
                            continue

                        # Gate 3: Immediate Shed Capacity
                        current_shed_load = base_shed_occupancy + total_retained_wheat + len(accepted_candidates)
                        shed_room_before = max(0, SHED_CAPACITY - current_shed_load)
                        if current_shed_load + 1 > SHED_CAPACITY:
                            candidate_sequence_rejected.append(species)
                            ledger["dropped"].append({"kind": "animal", "animal": species, "reason": "shed_capacity"})
                            candidate_decisions.append({
                                "candidate_id": cand_id,
                                "sequence_index": seq_idx,
                                "species": species,
                                "accepted": False,
                                "rejection_reason": "shed_capacity",
                                "feed_feasible": True,
                                "housing_before": housing_before,
                                "shed_room_before": shed_room_before,
                                "shed_room_after": shed_room_before,
                            })
                            continue

                        # Gate 4: Hour-23 Rollover Capacity
                        rollover_room_after = None
                        if hour >= 23:
                            total_post_market_and_carried = (current_shed_load + 1) + worker_rollover_inventory
                            rollover_room_after = max(0, SHED_CAPACITY - total_post_market_and_carried)
                            if total_post_market_and_carried > SHED_CAPACITY:
                                candidate_sequence_rejected.append(species)
                                ledger["dropped"].append({"kind": "animal", "animal": species, "reason": "end_of_day_rollover_capacity"})
                                candidate_decisions.append({
                                    "candidate_id": cand_id,
                                    "sequence_index": seq_idx,
                                    "species": species,
                                    "accepted": False,
                                    "rejection_reason": "end_of_day_rollover_capacity",
                                    "feed_feasible": True,
                                    "housing_before": housing_before,
                                    "shed_room_before": shed_room_before,
                                    "rollover_room_after": rollover_room_after,
                                    })
                                continue

                        # Gate 5: Market Order Slots
                        delta_slot = 0 if species in accepted_species_set else 1
                        if slots_left is not None and slots_left < delta_slot:
                            candidate_sequence_rejected.append(species)
                            ledger["dropped"].append({"kind": "animal", "animal": species, "reason": "market_order_slots"})
                            candidate_decisions.append({
                                "candidate_id": cand_id,
                                "sequence_index": seq_idx,
                                "species": species,
                                "accepted": False,
                                "rejection_reason": "market_order_slots",
                                "feed_feasible": True,
                                "housing_before": housing_before,
                                "slot_delta": delta_slot,
                            })
                            continue

                        # Gate 6: Feed & Cash Feasibility
                        purchase_cost = float(ANIMALS[species]["cost"])
                        try:
                            from config import BOOTSTRAP_LIVESTOCK_ARM
                        except Exception:
                            BOOTSTRAP_LIVESTOCK_ARM = "none"
                        is_boot = bool(day == 0 and BOOTSTRAP_LIVESTOCK_ARM not in ("none", "", None))
                        cand_res = evaluate_incremental_candidate(
                            working_ledger,
                            species,
                            purchase_cost=purchase_cost,
                            is_day0_bootstrap=is_boot,
                        )

                        if not cand_res.feasible:
                            f_reason = cand_res.blocking_reason or "feed_infeasible"
                            candidate_sequence_rejected.append(species)
                            ledger["dropped"].append({"kind": "animal", "animal": species, "reason": f_reason})
                            candidate_decisions.append({
                                "candidate_id": cand_id,
                                "sequence_index": seq_idx,
                                "species": species,
                                "accepted": False,
                                "rejection_reason": f_reason,
                                "feed_feasible": False,
                                "feed_blocking_reason": cand_res.blocking_reason,
                                "purchase_cost": purchase_cost,
                                "housing_before": housing_before,
                            })
                            continue

                        # Gate 7: Pre-NE Capital Gate
                        candidate_package_cost = purchase_cost + float(cand_res.candidate_feed_cash_hold)
                        if ne_locked and pre_ne_capital_mode in ("ne_first", "ne_escrow"):
                            if candidate_package_cost > remaining_ne_envelope:
                                candidate_sequence_rejected.append(species)
                                ledger["dropped"].append({"kind": "animal", "animal": species, "reason": "ne_capital_deferred"})
                                candidate_decisions.append({
                                    "candidate_id": cand_id,
                                    "sequence_index": seq_idx,
                                    "species": species,
                                    "accepted": False,
                                    "rejection_reason": "ne_capital_deferred",
                                    "feed_feasible": True,
                                    "purchase_cost": purchase_cost,
                                    "package_cost": candidate_package_cost,
                                    "remaining_ne_envelope": remaining_ne_envelope,
                                    "housing_before": housing_before,
                                })
                                continue
                            else:
                                remaining_ne_envelope -= candidate_package_cost

                        # ALL GATES PASSED -> COMMIT TRANSACTIONALLY
                        cand_deps = []
                        if w_protected_buyable > 0:
                            cand_deps.append("wheat:protected")
                        if w_opt_buyable > 0:
                            cand_deps.append("wheat:optional")

                        commit_candidate_reservation(working_ledger, cand_res, purchase_cost=purchase_cost)
                        accepted_housing.reserve(species)
                        if hasattr(cand_res, "minimum_wheat_slack") and cand_res.minimum_wheat_slack is not None:
                            current_operational_min_wheat_slack = float(cand_res.minimum_wheat_slack)
                        if delta_slot > 0:
                            accepted_species_set.add(species)
                            accepted_species_order.append(species)
                            if slots_left is not None:
                                slots_left -= delta_slot

                        accepted_candidates.append({
                            "candidate_id": cand_id,
                            "species": species,
                            "purchase_cost": purchase_cost,
                            "requires_resource_keys": list(cand_deps),
                        })
                        candidate_sequence_accepted.append(species)

                        diag = cand_res.diagnostics or {}
                        candidate_decisions.append({
                            "candidate_id": cand_id,
                            "sequence_index": seq_idx,
                            "species": species,
                            "accepted": True,
                            "rejection_reason": None,
                            "feed_feasible": True,
                            "feed_blocking_reason": None,
                            "purchase_cost": purchase_cost,
                            "candidate_feed_hold": float(cand_res.candidate_feed_cash_hold),
                            "existing_feed_hold_after": float(working_ledger.existing_feed_cash_hold),
                            "candidate_feed_hold_after": float(working_ledger.candidate_feed_cash_hold),
                            "stress_price_after": float(working_ledger.lifetime_wheat_price),
                            "housing_before": housing_before,
                            "housing_after": accepted_housing.to_dict(),
                            "shed_room_before": shed_room_before,
                            "shed_room_after": max(0, SHED_CAPACITY - (current_shed_load + 1)),
                            "rollover_room_after": rollover_room_after,
                            "slot_delta": delta_slot,
                            "relies_on_retained_protected_wheat": (w_protected_buyable > 0),
                            "relies_on_retained_optional_wheat": (w_opt_buyable > 0),
                            "requires_resource_keys": list(cand_deps),
                        })

                except Exception as exc:
                    # Transactional rollback on unexpected exception: discard all accepted candidates for this turn
                    working_ledger = candidate_stage_base_ledger.clone() if candidate_stage_base_ledger is not None else None
                    accepted_housing = candidate_stage_base_housing.clone() if candidate_stage_base_housing is not None else None
                    accepted_candidates.clear()
                    accepted_species_order.clear()
                    accepted_species_set.clear()
                    candidate_sequence_accepted.clear()
                    slots_left = available_animal_order_slots
                    current_operational_min_wheat_slack = baseline_operational_min_wheat_slack
                    remaining_ne_envelope = initial_ne_envelope
                    for d in candidate_decisions:
                        d["accepted"] = False
                        d["rejection_reason"] = "live_candidate_exception"
                        d["feed_feasible"] = False
                    ledger["dropped"].append({"kind": "animal", "reason": "live_candidate_exception", "error": str(exc)})

            # Consolidated emission into kept (in first-appearance species order)
            for sp_idx, sp in enumerate(accepted_species_order):
                sp_candidates = [c for c in accepted_candidates if c["species"] == sp]
                sp_count = len(sp_candidates)
                if sp_count > 0:
                    cand_ids = [c["candidate_id"] for c in sp_candidates]
                    dep_union = sorted(list(set(k for c in sp_candidates for k in c.get("requires_resource_keys", []))))
                    u_cost = float(ANIMALS[sp]["cost"])
                    total_c = u_cost * sp_count
                    kept.append((
                        TIER_ANIMALS,
                        "animal",
                        {
                            "animal": sp,
                            "n": sp_count,
                            "candidate_ids": cand_ids,
                            "dependency_group": f"animal:{sp}:{sp_idx}",
                            "requires_resource_keys": dep_union,
                        },
                        total_c,
                    ))
                    remaining_discretionary -= total_c

            # Stage 2: For Day 0 bootstrap, allocate remaining discretionary cash to extra crop seeds beyond minimum floor
            if is_boot_day0:
                boot_feed_hold = float(getattr(working_ledger, "candidate_feed_cash_hold", 0.0)) if working_ledger else 0.0
                remaining_discretionary = max(0.0, remaining_discretionary - boot_feed_hold)
                min_floor_seeds = {"MELON": 4, "WHEAT": 4}
                for crop, total_n in sorted(intents.get("buy_seed", {}).items()):
                    extra_n = max(0, int(total_n) - min_floor_seeds.get(crop, 0))
                    if extra_n > 0 and crop in CROPS:
                        unit = CROPS[crop]["seed"]
                        extra_buyable = min(extra_n, int(remaining_discretionary // unit))
                        if extra_buyable > 0:
                            found = False
                            for idx, item in enumerate(kept):
                                if item[1] == "seed" and item[2].get("crop") == crop:
                                    cur_n = item[2]["n"]
                                    new_n = cur_n + extra_buyable
                                    kept[idx] = (TIER_SEEDS, "seed", {"crop": crop, "n": new_n}, float(unit * new_n))
                                    found = True
                                    break
                            if not found:
                                kept.append((TIER_SEEDS, "seed", {"crop": crop, "n": extra_buyable}, float(unit * extra_buyable)))
                            remaining_discretionary -= unit * extra_buyable

            # Feed-sale reservation derivation (C2C)
            res_keys = []
            if w_protected_buyable > 0:
                res_keys.append("wheat:protected")
            if w_opt_buyable > 0:
                res_keys.append("wheat:optional")

            try:
                from strategy.feed_feasibility import derive_feed_sale_reservation
            except Exception:
                try:
                    from feed_feasibility import derive_feed_sale_reservation
                except Exception:
                    derive_feed_sale_reservation = None

            if derive_feed_sale_reservation is not None:
                feed_sale_res = derive_feed_sale_reservation(
                    ledger=working_ledger if working_ledger is not None else live_ledger,
                    operational_min_wheat_slack=current_operational_min_wheat_slack,
                    valid=(live_failure_reason is None and (snapshot is not None and getattr(snapshot, "post_unit_state_verified", False) is True)),
                    day=day,
                    requires_resource_keys=res_keys,
                )
            else:
                feed_sale_res = {
                    "version": "point2_c2c_v1",
                    "valid": False,
                    "sellable_shed_wheat": 0,
                    "requires_resource_keys": res_keys,
                }

            ledger["dependency_contract_version"] = "point2_c2c_v1"
            ledger["feed_sale_reservation"] = feed_sale_res

            # Record Diagnostics
            ledger["live_animal_authority"] = "c2b_sequential"
            ledger["candidate_sequence_requested"] = candidate_sequence_requested
            ledger["candidate_sequence_source"] = candidate_sequence_source
            ledger["candidate_sequence_accepted"] = candidate_sequence_accepted
            ledger["candidate_sequence_rejected"] = candidate_sequence_rejected
            ledger["candidate_decisions"] = candidate_decisions
            ledger["final_existing_feed_hold"] = float(working_ledger.existing_feed_cash_hold) if working_ledger else remaining_existing_feed_hold
            ledger["final_candidate_feed_hold"] = float(working_ledger.candidate_feed_cash_hold) if working_ledger else 0.0
            ledger["final_candidate_purchase_spend"] = float(working_ledger.candidate_purchase_cash_spent) if working_ledger else 0.0
            ledger["final_stress_wheat_price"] = float(working_ledger.lifetime_wheat_price) if working_ledger else 0.0
            ledger["post_unit_state_verified"] = bool(getattr(snapshot, "post_unit_state_verified", False)) if snapshot is not None else False
            ledger["post_unit_state_reason"] = getattr(snapshot, "post_unit_state_reason", "missing_snapshot") if snapshot is not None else "missing_snapshot"
            ledger["post_unit_shed_occupancy"] = base_shed_occupancy
            ledger["post_unit_worker_inventory_total"] = worker_rollover_inventory
            ledger["housing_state_final"] = accepted_housing.to_dict() if accepted_housing else None
            ledger["animal_order_slots_used"] = len(accepted_species_order)
            ledger["live_c2b_diagnostics"] = {
                "candidate_sequence_requested": candidate_sequence_requested,
                "candidate_sequence_source": candidate_sequence_source,
                "candidate_sequence_accepted": candidate_sequence_accepted,
                "candidate_sequence_rejected": candidate_sequence_rejected,
                "candidate_decisions": candidate_decisions,
                "pre_ne_capital_mode": pre_ne_capital_mode if 'pre_ne_capital_mode' in locals() else "off",
                "pre_ne_envelope_initial": initial_ne_envelope if 'initial_ne_envelope' in locals() else None,
                "pre_ne_envelope_remaining": remaining_ne_envelope if 'remaining_ne_envelope' in locals() else None,
                "final_existing_feed_hold": ledger["final_existing_feed_hold"],
                "final_candidate_feed_hold": ledger["final_candidate_feed_hold"],
                "final_candidate_purchase_spend": ledger["final_candidate_purchase_spend"],
                "final_stress_wheat_price": ledger["final_stress_wheat_price"],
                "housing_state_final": ledger["housing_state_final"],
                "animal_order_slots_used": ledger["animal_order_slots_used"],
                "post_unit_state_verified": ledger["post_unit_state_verified"],
                "post_unit_state_reason": ledger["post_unit_state_reason"],
            }
        else:
            can_buy_animals = True
            claimed_structures = {}
            for animal, k_anim in sorted(intents.get("buy_animal", {}).items()):
                k_anim = int(k_anim)
                if k_anim > 0 and animal in ANIMALS:
                    struct_type = ANIMALS[animal]["structure"]
                    pending_structures = int(intents.get("pending_structures", {}).get(struct_type, 0))
                    def _tile_free(t):
                        t_kind = t.get("kind") if isinstance(t, dict) else getattr(t, "kind", "")
                        t_anim = t.get("is_animal") if isinstance(t, dict) else getattr(t, "is_animal", False)
                        if t_kind != struct_type or t_anim:
                            return False
                        if hasattr(farm, "unlocked") and hasattr(farm, "quadrant_of"):
                            t_pos = tuple(t.get("pos")) if isinstance(t, dict) else tuple(t.pos)
                            return farm.quadrant_of(t_pos) in farm.unlocked
                        return True

                    free_structures = sum(1 for t in farm.iter_tiles() if _tile_free(t)) + pending_structures
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
                    animal_discretionary = max(0.0, remaining_discretionary - sw_shadow_reserve)
                    n_max = int(animal_discretionary // unit)
                    actual_buy = min(room_limited, n_max)
                    if actual_buy < room_limited and sw_shadow_reserve > 0:
                        discretionary_livestock_suppressed = True
                    if actual_buy > 0:
                        claimed_structures[struct_type] = claimed + actual_buy
                        remaining_shed_room = max(0, remaining_shed_room - actual_buy)
                        kept.append((TIER_ANIMALS, "animal", {"animal": animal, "n": actual_buy}, float(unit * actual_buy)))
                        remaining_discretionary -= unit * actual_buy
                        if actual_buy < room_limited:
                            ledger["dropped"].append({
                                "kind": "animal", "animal": animal,
                                "trimmed_from": room_limited, "to": actual_buy,
                                "reason": "sw_capital_protected" if sw_shadow_reserve > 0 else "budget",
                            })
                    else:
                        ledger["dropped"].append({
                            "kind": "animal", "animal": animal,
                            "reason": "sw_capital_protected" if (sw_shadow_reserve > 0 and int(remaining_discretionary // unit) > 0) else "budget"
                        })

        ledger["discretionary_livestock_suppressed_for_sw"] = discretionary_livestock_suppressed

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
            non_hire_slots_needed = sum(1 for t in kept if t[1] in ("wheat", "wheat_protected", "wheat_optional", "land", "seed"))
            max_hire_slots = max(MIN_HANDS_BASE, slots - non_hire_slots_needed)
        else:
            max_hire_slots = None

        order_metadata = []
        for tier, kind, payload, est in sorted(kept, key=lambda t: t[0]):
            if kind == "hire":
                emitted = 0
                while (payload["count"] - emitted > 0 and
                       (slots is None or slots > 0) and
                       (max_hire_slots is None or emitted < max_hire_slots)):
                    orders.append(["HIRE"])
                    order_metadata.append({"kind": "hire", "tier": tier, "feed_class": None})
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
            elif kind in ("wheat", "wheat_protected", "wheat_optional"):
                if take(None):
                    feed_class = "protected" if (kind == "wheat_protected" or payload.get("feed_class") == "protected" or payload.get("is_protected", False)) else "optional"
                    is_prot = (feed_class == "protected")
                    sem_kind = "wheat_protected" if is_prot else "wheat_optional"
                    res_key = "wheat:protected" if is_prot else "wheat:optional"
                    order_metadata.append({
                        "kind": sem_kind,
                        "feed_class": feed_class,
                        "is_protected": is_prot,
                        "hard_required": is_prot if is_live_feed_mode else False,
                        "resource_key": res_key if is_live_feed_mode else None,
                        "resource_role": "feed_resource" if is_live_feed_mode else None,
                        "tier": tier,
                        "n": int(payload["n"]),
                    })
                    orders.append(["BUY_PRODUCT", "WHEAT", int(payload["n"])])
                    queued["wheat"] = int(queued.get("wheat", 0)) + int(payload["n"])
                else:
                    ledger["dropped"].append({
                        "kind": f"{kind}_slots",
                        "n": int(payload["n"]),
                        "cost": float(est),
                        "tier": tier,
                    })
            elif kind == "land":
                next_quadrant = len(farm.unlocked) + 1
                assert next_quadrant != 4, "Quadrant 4 (SE) is permanently hard-blocked and must NEVER be purchased!"
                if take(None):
                    orders.append(["BUY_LAND"])
                    order_metadata.append({"kind": "land", "tier": tier, "feed_class": None})
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
                    order_metadata.append({"kind": "seed", "crop": payload["crop"], "tier": tier, "n": int(payload["n"]), "feed_class": None})
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
                    meta_dict = {
                        "kind": "animal",
                        "animal": payload["animal"],
                        "tier": tier,
                        "n": int(payload["n"]),
                        "feed_class": None,
                    }
                    if is_live_feed_mode:
                        meta_dict["candidate_ids"] = list(payload.get("candidate_ids", []))
                        meta_dict["dependency_group"] = payload.get("dependency_group")
                        meta_dict["requires_resource_keys"] = list(payload.get("requires_resource_keys", []))
                    order_metadata.append(meta_dict)
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
        ledger["order_metadata"] = order_metadata
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
