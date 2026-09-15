"""Centralized Market Arbitration Layer — Phase 3.

Cross-engine market arbitrator coordinating purchase and sell orders under the
engine's shared per-turn cap (MAX_MARKET_ORDERS = 10).

Phase 3 Architecture:
  Upstream engines generate full useful proposal sets; CentralPlanner arbitrates.
  - Deterministic proposal identity (proposal_id: "purchase:i", "sell:i")
  - Lightweight structural proposal validator (fails closed per candidate)
  - Hard conflict resolution (feed starvation wheat buy vs wheat sell)
  - Day 29 non-payoff purchase blocking
  - Accidental duplicate land purchase filtering
  - Global priority-dominated ranking (P0_CRITICAL .. P4_DISCRETIONARY)
  - Explicit selection freeze and multiset-verified execution sequencing
  - Authoritative shed capacity & incoming purchase load awareness
  - Strict preservation of OrderBuilder atomic purchase ordering
  - Candidate starvation and upstream truncation diagnostics
  - Guaranteed fallback to legacy compose on any unexpected exception
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import (
    ANIMALS,
    CROPS,
    ENDGAME_START_DAY,
    FEED_WHEAT_BUFFER_DAYS,
    LAND_BUY_LAST_DAY,
    MAX_MARKET_ORDERS,
    PRODUCTS,
    SELL_HOUR_SET,
    SHED_CAPACITY,
    SHED_SOFT_CAP,
)

try:
    from market.market_brain import MarketBrain
except ImportError:
    try:
        from market_brain import MarketBrain
    except ImportError:
        MarketBrain = None  # type: ignore


# Deterministic priority hierarchy (lower int = higher priority)
P0_CRITICAL = 0
P1_URGENT = 1
P2_STRATEGIC = 2
P3_NORMAL = 3
P4_DISCRETIONARY = 4

PRIORITY_NAMES: Dict[int, str] = {
    P0_CRITICAL: "P0_CRITICAL",
    P1_URGENT: "P1_URGENT",
    P2_STRATEGIC: "P2_STRATEGIC",
    P3_NORMAL: "P3_NORMAL",
    P4_DISCRETIONARY: "P4_DISCRETIONARY",
}

# Hard capacity threshold: 4-unit headroom below SHED_CAPACITY (100 - 4 = 96).
# Multi-unit batch harvests (cow milk 4-6, sheep wool 4-6, melon/wheat 4-6)
# will overflow and permanently destroy inventory if shed occupancy >= 96.
# True P0 capacity emergency is strictly reserved for shed_total >= HARD_CAPACITY_THRESHOLD.
HARD_CAPACITY_HEADROOM = 4
HARD_CAPACITY_THRESHOLD = SHED_CAPACITY - HARD_CAPACITY_HEADROOM  # 96


# ----------------------------------------------------------------------
# Authoritative Historical Legacy Composition Helper
# ----------------------------------------------------------------------
def legacy_compose_market(
    purchase_orders: Optional[List[List[Any]]],
    sell_orders: Optional[List[List[Any]]],
    ctx: Any,
    cap: int = MAX_MARKET_ORDERS,
) -> List[List[Any]]:
    """Authoritative historical legacy market composition.

    Historical rule:
      Hour 0 and Hour 1: purchases first, then sells
      Hour 2+: sells first, then purchases
      Enforces cap without reordering within queues or dropping based on priority.
    """
    hour = 0
    if ctx is not None:
        if isinstance(ctx, dict):
            hour = int(ctx.get("hour", 0))
        else:
            hour = int(getattr(ctx, "hour", 0))

    purchases_first = (hour in (0, 1))
    buys = [list(o[:3]) if (isinstance(o, (list, tuple)) and len(o) > 3) else list(o) for o in (purchase_orders or [])]
    sells = [list(o[:3]) if (isinstance(o, (list, tuple)) and len(o) > 3) else list(o) for o in (sell_orders or [])]

    if MarketBrain is not None:
        return MarketBrain.compose(
            buys,
            sells,
            cap=cap,
            purchases_first=purchases_first,
        )

    first, second = (buys, sells) if purchases_first else (sells, buys)
    out = [list(o) for o in first][:cap]
    out += [list(o) for o in second][:cap - len(out)]
    return out



@dataclass
class ProposalCandidate:
    proposal_id: str  # e.g. "purchase:0", "sell:1"
    order: List[Any]
    source: str  # "purchase" or "sell"
    kind: str  # "hire", "feed_wheat", "seed", "land", "animal", "fertilizer", "sell", "other", "invalid"
    priority_class: int  # 0..4
    urgency: float  # float score for secondary tiebreak
    original_index: int  # order within original proposal stream
    selection_rank: Optional[int] = None
    execution_index: Optional[int] = None
    rejection_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CentralPlanner:
    """Stateless market arbitrator coordinating purchase and sell orders."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Context inspection helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_hour(ctx: Any) -> int:
        if ctx is None:
            return 0
        if isinstance(ctx, dict):
            return int(ctx.get("hour", 0))
        return int(getattr(ctx, "hour", 0))

    @staticmethod
    def _get_day(ctx: Any) -> int:
        if ctx is None:
            return 0
        if isinstance(ctx, dict):
            return int(ctx.get("day", 0))
        return int(getattr(ctx, "day", 0))

    @staticmethod
    def _get_existing_animals_count(ctx: Any) -> int:
        if ctx is None:
            return 0
        farm = ctx.get("farm") if isinstance(ctx, dict) else getattr(ctx, "farm", None)
        if farm is None:
            return 0
        if hasattr(farm, "iter_tiles"):
            return sum(1 for t in farm.iter_tiles() if getattr(t, "is_animal", False))
        if isinstance(farm, dict) and "tiles" in farm:
            return sum(1 for t in farm["tiles"] if t.get("is_animal"))
        if hasattr(farm, "animals"):
            return len(farm.animals)
        return 0

    @staticmethod
    def _get_wheat_in_shed(ctx: Any) -> int:
        if ctx is None:
            return 0
        private = ctx.get("private") if isinstance(ctx, dict) else getattr(ctx, "private", None)
        if private is None:
            return 0
        shed = private.get("shed", {}) if isinstance(private, dict) else getattr(private, "shed", {})
        if isinstance(shed, dict):
            return int(shed.get("WHEAT", 0))
        return 0

    @staticmethod
    def _get_shed_total(ctx: Any) -> int:
        if ctx is None:
            return 0
        private = ctx.get("private") if isinstance(ctx, dict) else getattr(ctx, "private", None)
        if private is None:
            return 0
        shed = private.get("shed", {}) if isinstance(private, dict) else getattr(private, "shed", {})
        if isinstance(shed, dict):
            return sum(int(v) for v in shed.values())
        return 0

    @staticmethod
    def _get_seeds_on_hand(ctx: Any, crop: str) -> int:
        if ctx is None:
            return 0
        private = ctx.get("private") if isinstance(ctx, dict) else getattr(ctx, "private", None)
        if private is None:
            return 0
        seeds = private.get("seeds", {}) if isinstance(private, dict) else getattr(private, "seeds", {})
        if isinstance(seeds, dict):
            return int(seeds.get(crop, 0))
        return 0

    # ------------------------------------------------------------------
    # Lightweight structural proposal validator
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_proposal(order: Any) -> Tuple[bool, Optional[str]]:
        """Lightweight structural proposal validator.

        Fails closed per candidate for malformed proposals without crashing the planner.
        Validates:
          - order is a non-empty list
          - known opcode
          - correct arguments count
          - positive integer quantities where applicable
          - known product / animal identifiers where applicable
        """
        if not isinstance(order, (list, tuple)) or len(order) == 0:
            return False, "malformed_order_structure"
        op = order[0]
        if not isinstance(op, str):
            return False, "invalid_opcode_type"

        if op == "HIRE":
            if len(order) != 1:
                return False, "hire_exact_shape_violation"
            return True, None

        elif op == "BUY_LAND":
            if len(order) != 1:
                return False, "buy_land_exact_shape_violation"
            return True, None

        elif op == "BUY_SEED":
            if len(order) != 3:
                return False, "buy_seed_exact_shape_violation"
            crop, qty = order[1], order[2]
            if not isinstance(crop, str) or crop not in CROPS:
                return False, "unknown_crop"
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                return False, "invalid_seed_qty"
            return True, None

        elif op == "BUY_ANIMAL":
            if len(order) != 3:
                return False, "buy_animal_exact_shape_violation"
            animal, qty = order[1], order[2]
            if not isinstance(animal, str) or animal not in ANIMALS:
                return False, "unknown_animal"
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                return False, "invalid_animal_qty"
            return True, None

        elif op == "BUY_PRODUCT":
            if len(order) not in (3, 4):
                return False, "buy_product_exact_shape_violation"
            product, qty = order[1], order[2]
            if product not in ("WHEAT", "FERTILIZER"):
                return False, "unsupported_buy_product"
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                return False, "invalid_product_qty"
            return True, None

        elif op == "SELL":
            if len(order) != 3:
                return False, "sell_exact_shape_violation"
            product, qty = order[1], order[2]
            if not isinstance(product, str) or product not in PRODUCTS:
                return False, "unknown_sell_product"
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
                return False, "invalid_sell_qty"
            return True, None

        return False, f"unknown_opcode_{op}"

    # ------------------------------------------------------------------
    # Proposal Classification
    # ------------------------------------------------------------------
    def _classify_purchase(
        self,
        order: List[Any],
        idx: int,
        ctx: Any,
        macro_plan: Any,
        purchase_ledger: Any,
        purchases: Optional[List[List[Any]]] = None,
    ) -> ProposalCandidate:
        order_copy = list(order)
        op = order_copy[0] if order_copy else "UNKNOWN"
        hour = self._get_hour(ctx)
        day = self._get_day(ctx)
        proposal_id = f"purchase:{idx}"

        if op == "HIRE":
            if hour == 0:
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="hire",
                    priority_class=P1_URGENT,
                    urgency=1.0,
                    original_index=idx,
                )
            else:
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="hire",
                    priority_class=P2_STRATEGIC,
                    urgency=0.5,
                    original_index=idx,
                )

        if op == "BUY_PRODUCT":
            prod = order_copy[1] if len(order_copy) > 1 else ""
            if prod == "WHEAT":
                qty = int(order_copy[2]) if len(order_copy) > 2 else 0
                n_animals = self._get_existing_animals_count(ctx)
                wheat_have = self._get_wheat_in_shed(ctx)

                # Check authoritative feed_risk from macro_plan diagnostics if available
                feed_risk = {}
                if macro_plan and hasattr(macro_plan, "diagnostics") and isinstance(macro_plan.diagnostics, dict):
                    feed_risk = macro_plan.diagnostics.get("feed_risk", {})

                macro_buy_wheat_intent = 0
                if macro_plan and hasattr(macro_plan, "intents") and isinstance(macro_plan.intents, dict):
                    macro_buy_wheat_intent = int(macro_plan.intents.get("buy_wheat", 0))

                # Extract explicit semantic identity (Single Source of Truth)
                explicit_meta = {}
                if len(order_copy) > 3:
                    raw_m = order_copy[3]
                    if isinstance(raw_m, dict):
                        explicit_meta = dict(raw_m)
                    elif isinstance(raw_m, str):
                        explicit_meta = {"kind": raw_m, "feed_class": "protected" if "protect" in raw_m else "optional"}
                    elif isinstance(raw_m, bool):
                        explicit_meta = {"is_protected": raw_m, "feed_class": "protected" if raw_m else "optional"}

                if not explicit_meta and isinstance(purchase_ledger, dict):
                    om_list = purchase_ledger.get("order_metadata", [])
                    if isinstance(om_list, list) and idx < len(om_list) and isinstance(om_list[idx], dict):
                        explicit_meta = dict(om_list[idx])

                is_protected = None
                if "feed_class" in explicit_meta:
                    is_protected = (explicit_meta["feed_class"] == "protected")
                elif "is_protected" in explicit_meta:
                    is_protected = bool(explicit_meta["is_protected"])
                elif "kind" in explicit_meta:
                    if explicit_meta["kind"] == "wheat_protected":
                        is_protected = True
                    elif explicit_meta["kind"] == "wheat_optional":
                        is_protected = False

                # Backwards-compatible fallback only if NO explicit metadata exists
                if is_protected is None:
                    if isinstance(purchase_ledger, dict):
                        w_opt = int(purchase_ledger.get("w_opt_buyable", 0))
                        w_prot = int(purchase_ledger.get("w_protected_buyable", 0))
                        if w_prot > 0 and w_opt > 0:
                            wheat_stream = purchases if purchases is not None else []
                            wheat_positions = [
                                j for j, p in enumerate(wheat_stream)
                                if isinstance(p, (list, tuple)) and len(p) >= 2 and p[0] == "BUY_PRODUCT" and p[1] == "WHEAT"
                            ]
                            if idx in wheat_positions:
                                is_protected = (wheat_positions.index(idx) == 0)
                            else:
                                is_protected = True
                        elif w_opt > 0 and w_prot == 0:
                            is_protected = False
                        else:
                            is_protected = True
                    else:
                        is_protected = True

                immediate_shortage = feed_risk.get("immediate_shortage")
                if immediate_shortage is None:
                    immediate_shortage = (n_animals > 0 and wheat_have < n_animals)

                near_term_shortage = feed_risk.get("near_term_shortage")
                if near_term_shortage is None:
                    feed_days_covered = (wheat_have // n_animals) if n_animals > 0 else 999
                    near_term_shortage = (n_animals > 0 and not immediate_shortage and feed_days_covered < 2)

                if not is_protected:
                    # OPTIONAL WHEAT: routine feed buffer -> always P2_STRATEGIC
                    prio = P2_STRATEGIC
                    urg = 0.5
                    reason = "routine_feed_buffer"
                else:
                    # PROTECTED WHEAT: survival / unavoidable feed -> P0 or P1 when applicable
                    if immediate_shortage:
                        prio = P0_CRITICAL
                        urg = 2.0
                        reason = "immediate_starvation_risk"
                    elif near_term_shortage:
                        prio = P1_URGENT
                        urg = 1.0
                        reason = "near_term_feed_danger"
                    else:
                        prio = P2_STRATEGIC
                        urg = 0.5
                        reason = "routine_feed_buffer" if macro_buy_wheat_intent > 0 else "routine_wheat_purchase"

                projected_supply = feed_risk.get(
                    "projected_wheat_supply",
                    macro_plan.diagnostics.get("projected_wheat_supply") if (macro_plan and hasattr(macro_plan, "diagnostics")) else None,
                )

                feed_class_str = "protected" if is_protected else "optional"
                sem_kind = "wheat_protected" if is_protected else "wheat_optional"
                meta = {
                    "feed_class": feed_class_str,
                    "is_protected": is_protected,
                    "wheat_priority": prio,
                    "wheat_priority_reason": reason,
                    "animals": n_animals,
                    "shed_wheat": wheat_have,
                    "projected_feed_supply": projected_supply,
                    "projected_feed_deficit": feed_risk.get("projected_deficit", None),
                    "near_term_feed_risk": near_term_shortage,
                    "immediate_starvation_risk": immediate_shortage,
                    "macro_buy_wheat_intent": macro_buy_wheat_intent,
                }

                clean_order = [order_copy[0], order_copy[1], order_copy[2]]
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=clean_order,
                    source="purchase",
                    kind="feed_wheat",
                    priority_class=prio,
                    urgency=urg,
                    original_index=idx,
                    metadata=meta,
                )
            elif prod == "FERTILIZER":
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="fertilizer",
                    priority_class=P3_NORMAL,
                    urgency=0.0,
                    original_index=idx,
                )
            else:
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="product",
                    priority_class=P3_NORMAL,
                    urgency=0.0,
                    original_index=idx,
                )

        if op == "BUY_SEED":
            crop = order_copy[1] if len(order_copy) > 1 else ""
            planned_today = 0
            if macro_plan and hasattr(macro_plan, "plant_queue") and macro_plan.plant_queue:
                planned_today = sum(1 for pos, c in macro_plan.plant_queue if c == crop)

            seeds_on_hand = self._get_seeds_on_hand(ctx, crop)
            needed_today = max(0, planned_today - seeds_on_hand)

            if needed_today > 0:
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="seed",
                    priority_class=P1_URGENT,
                    urgency=1.0,
                    original_index=idx,
                )
            else:
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="seed",
                    priority_class=P2_STRATEGIC,
                    urgency=0.5,
                    original_index=idx,
                )

        if op == "BUY_LAND":
            sw_urgency = 0.0
            if macro_plan and hasattr(macro_plan, "diagnostics") and isinstance(macro_plan.diagnostics, dict):
                sw_urgency = float(macro_plan.diagnostics.get("sw_urgency", 0.0))

            if sw_urgency >= 0.8 or day >= LAND_BUY_LAST_DAY - 2:
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="land",
                    priority_class=P1_URGENT,
                    urgency=1.0,
                    original_index=idx,
                )
            else:
                return ProposalCandidate(
                    proposal_id=proposal_id,
                    order=order_copy,
                    source="purchase",
                    kind="land",
                    priority_class=P2_STRATEGIC,
                    urgency=0.5,
                    original_index=idx,
                )

        if op == "BUY_ANIMAL":
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="purchase",
                kind="animal",
                priority_class=P2_STRATEGIC,
                urgency=0.5,
                original_index=idx,
            )

        return ProposalCandidate(
            proposal_id=proposal_id,
            order=order_copy,
            source="purchase",
            kind="purchase_other",
            priority_class=P3_NORMAL,
            urgency=0.0,
            original_index=idx,
        )

    def _classify_sell(
        self,
        order: List[Any],
        idx: int,
        ctx: Any,
        sell_details: Any,
        opp_advice: Any,
    ) -> ProposalCandidate:
        order_copy = list(order)
        prod = order_copy[1] if len(order_copy) > 1 else ""
        day = self._get_day(ctx)
        hour = self._get_hour(ctx)
        proposal_id = f"sell:{idx}"

        shed_total = self._get_shed_total(ctx)

        # 1. Day 29 final liquidation (unsold inventory worth $0)
        is_day_29 = (day >= 29) or (
            isinstance(sell_details, dict) and sell_details.get("reason") in ("final_day", "day29_liquidation")
        )
        if is_day_29:
            meta = {
                "sell_pressure_class": "day29",
                "shed_total": shed_total,
                "shed_capacity": SHED_CAPACITY,
                "soft_cap": SHED_SOFT_CAP,
                "hard_threshold": HARD_CAPACITY_THRESHOLD,
                "priority_class": P0_CRITICAL,
                "priority_reason": "day29_final_liquidation",
            }
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="sell",
                kind="sell",
                priority_class=P0_CRITICAL,
                urgency=2.0,
                original_index=idx,
                metadata=meta,
            )

        # 2. Midnight hard-guard (hour >= 22 and high shed total)
        is_midnight_guard = isinstance(sell_details, dict) and (
            sell_details.get("urgency") == 2 or sell_details.get("reason") == "midnight_guard"
        )
        if is_midnight_guard:
            meta = {
                "sell_pressure_class": "midnight_hard_guard",
                "shed_total": shed_total,
                "shed_capacity": SHED_CAPACITY,
                "soft_cap": SHED_SOFT_CAP,
                "hard_threshold": HARD_CAPACITY_THRESHOLD,
                "priority_class": P0_CRITICAL,
                "priority_reason": "midnight_hard_guard",
            }
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="sell",
                kind="sell",
                priority_class=P0_CRITICAL,
                urgency=2.0,
                original_index=idx,
                metadata=meta,
            )

        # 3. True near-certain shed capacity emergency (P0_CRITICAL)
        # Narrowly reserved for physical capacity overflow risk (shed >= 96)
        # or explicit overflow reason from upstream engine when near capacity (>= 90).
        is_hard_capacity_emergency = (shed_total >= HARD_CAPACITY_THRESHOLD) or (
            isinstance(sell_details, dict) and sell_details.get("reason") == "overflow" and shed_total >= (HARD_CAPACITY_THRESHOLD - 6)
        )
        if is_hard_capacity_emergency:
            meta = {
                "sell_pressure_class": "hard_capacity_emergency",
                "shed_total": shed_total,
                "shed_capacity": SHED_CAPACITY,
                "soft_cap": SHED_SOFT_CAP,
                "hard_threshold": HARD_CAPACITY_THRESHOLD,
                "priority_class": P0_CRITICAL,
                "priority_reason": "hard_capacity_emergency",
            }
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="sell",
                kind="sell",
                priority_class=P0_CRITICAL,
                urgency=2.0,
                original_index=idx,
                metadata=meta,
            )

        # 4. Endgame liquidation before final day (e.g. Day 28)
        is_endgame = (day >= ENDGAME_START_DAY) or (
            isinstance(sell_details, dict) and (
                sell_details.get("endgame") is True or sell_details.get("reason") == "endgame_dump"
            )
        )
        if is_endgame:
            meta = {
                "sell_pressure_class": "endgame",
                "shed_total": shed_total,
                "shed_capacity": SHED_CAPACITY,
                "soft_cap": SHED_SOFT_CAP,
                "hard_threshold": HARD_CAPACITY_THRESHOLD,
                "priority_class": P1_URGENT,
                "priority_reason": "endgame_dump",
            }
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="sell",
                kind="sell",
                priority_class=P1_URGENT,
                urgency=1.0,
                original_index=idx,
                metadata=meta,
            )

        # 5. Opponent preemptive sell
        is_preempt = False
        if isinstance(sell_details, dict) and isinstance(sell_details.get("candidates"), list):
            for c in sell_details["candidates"]:
                if isinstance(c, dict) and c.get("product") == prod:
                    if c.get("urgency") == 0.99:
                        is_preempt = True
                        break
        if not is_preempt and opp_advice is not None:
            preempt_list = getattr(opp_advice, "preempt_sell", [])
            if prod in preempt_list:
                is_preempt = True

        if is_preempt:
            meta = {
                "sell_pressure_class": "opponent_preempt",
                "shed_total": shed_total,
                "shed_capacity": SHED_CAPACITY,
                "soft_cap": SHED_SOFT_CAP,
                "hard_threshold": HARD_CAPACITY_THRESHOLD,
                "priority_class": P1_URGENT,
                "priority_reason": "opponent_preempt",
            }
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="sell",
                kind="sell",
                priority_class=P1_URGENT,
                urgency=1.0,
                original_index=idx,
                metadata=meta,
            )

        # 6. Ordinary shed soft-cap relief (shed_total >= SHED_SOFT_CAP, but < HARD_CAPACITY_THRESHOLD)
        # Classified as P2_STRATEGIC (urgency = 0.60):
        # On Hour 0, P1 morning HIRE (urgency 1.0) and P1 planting-dependent BUY_SEED (urgency 1.0)
        # strictly take precedence. Soft-cap relief sales execute on Hour 1 or subsequent sell windows.
        is_soft_cap_relief = (shed_total >= SHED_SOFT_CAP) or (
            isinstance(sell_details, dict) and (
                sell_details.get("pressure") is True or sell_details.get("reason") in ("shed_pressure", "overflow")
            )
        )
        if is_soft_cap_relief:
            meta = {
                "sell_pressure_class": "soft_cap_relief",
                "shed_total": shed_total,
                "shed_capacity": SHED_CAPACITY,
                "soft_cap": SHED_SOFT_CAP,
                "hard_threshold": HARD_CAPACITY_THRESHOLD,
                "priority_class": P2_STRATEGIC,
                "priority_reason": "soft_cap_relief",
            }
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="sell",
                kind="sell",
                priority_class=P2_STRATEGIC,
                urgency=0.60,
                original_index=idx,
                metadata=meta,
            )

        # 7. Normal scheduled sell window
        cand_urgency_score = 0.0
        if isinstance(sell_details, dict) and isinstance(sell_details.get("candidates"), list):
            for c in sell_details["candidates"]:
                if isinstance(c, dict) and c.get("product") == prod:
                    cand_urgency_score = float(c.get("urgency", 0.0))
                    break

        is_normal_window = (hour in SELL_HOUR_SET) or (
            isinstance(sell_details, dict) and sell_details.get("urgency") == 0
        )
        if is_normal_window:
            meta = {
                "sell_pressure_class": "normal_window",
                "shed_total": shed_total,
                "shed_capacity": SHED_CAPACITY,
                "soft_cap": SHED_SOFT_CAP,
                "hard_threshold": HARD_CAPACITY_THRESHOLD,
                "priority_class": P2_STRATEGIC,
                "priority_reason": "normal_window",
            }
            return ProposalCandidate(
                proposal_id=proposal_id,
                order=order_copy,
                source="sell",
                kind="sell",
                priority_class=P2_STRATEGIC,
                urgency=min(0.49, cand_urgency_score * 0.1),
                original_index=idx,
                metadata=meta,
            )

        # 8. Discretionary off-window sell
        meta = {
            "sell_pressure_class": "discretionary",
            "shed_total": shed_total,
            "shed_capacity": SHED_CAPACITY,
            "soft_cap": SHED_SOFT_CAP,
            "hard_threshold": HARD_CAPACITY_THRESHOLD,
            "priority_class": P4_DISCRETIONARY,
            "priority_reason": "discretionary_off_window",
        }
        return ProposalCandidate(
            proposal_id=proposal_id,
            order=order_copy,
            source="sell",
            kind="sell",
            priority_class=P4_DISCRETIONARY,
            urgency=0.0,
            original_index=idx,
            metadata=meta,
        )

    # ------------------------------------------------------------------
    # Core Arbitration Entrypoint
    # ------------------------------------------------------------------
    def plan_market(
        self,
        ctx: Any,
        macro_plan: Any = None,
        purchase_orders: Optional[List[List[Any]]] = None,
        purchase_ledger: Any = None,
        sell_orders: Optional[List[List[Any]]] = None,
        sell_details: Any = None,
        cap: int = MAX_MARKET_ORDERS,
        opp_advice: Any = None,
    ) -> Tuple[List[List[Any]], Dict[str, Any]]:
        """Arbitrate market orders between purchase and sell queues under per-turn cap.

        Phase 3 Pipeline:
          1. Validate and Normalize proposals (with deterministic proposal_ids)
          2. Early Filter (invalid orders fail closed per candidate, deduplicate land, Day 29 block)
          3. Resolve hard conflicts (starvation feed wheat buy vs wheat sell)
          4. Assign P0..P4 priority classes & urgency
          5. Rank globally (priority class strictly dominates)
          6. Select <= cap and freeze selected set
          7. Safely sequence selected orders (shed capacity, emergency, Day 29, atomic purchase order)
          8. Enforce mathematical invariants & compile diagnostics
        """
        purchases = [list(o) for o in (purchase_orders or [])]
        sells = [list(o) for o in (sell_orders or [])]

        # Semantic splitting: If a single combined wheat order arrives while protected feed is strictly less than order qty,
        # split into protected and optional proposals so optional buffer is never promoted to P0/P1.
        w_prot = 0
        if isinstance(purchase_ledger, dict):
            w_prot = int(purchase_ledger.get("w_protected_buyable", 0))
        if w_prot == 0 and macro_plan and hasattr(macro_plan, "diagnostics") and isinstance(macro_plan.diagnostics, dict):
            w_prot = int(macro_plan.diagnostics.get("feed_risk", {}).get("protected_feed_wheat", 0))

        if w_prot > 0:
            wheat_orders = [o for o in purchases if isinstance(o, (list, tuple)) and len(o) >= 3 and o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"]
            if len(wheat_orders) == 1 and wheat_orders[0][2] > w_prot:
                idx = purchases.index(wheat_orders[0])
                total_n = wheat_orders[0][2]
                purchases[idx] = ["BUY_PRODUCT", "WHEAT", w_prot, {"kind": "wheat_protected", "feed_class": "protected", "is_protected": True, "n": w_prot}]
                purchases.insert(idx + 1, ["BUY_PRODUCT", "WHEAT", total_n - w_prot, {"kind": "wheat_optional", "feed_class": "optional", "is_protected": False, "n": total_n - w_prot}])
                if isinstance(purchase_ledger, dict):
                    purchase_ledger = dict(purchase_ledger)
                    purchase_ledger["w_protected_buyable"] = w_prot
                    purchase_ledger["w_opt_buyable"] = total_n - w_prot
                    if "order_metadata" in purchase_ledger and isinstance(purchase_ledger["order_metadata"], list):
                        om_list = list(purchase_ledger["order_metadata"])
                        if idx < len(om_list):
                            om_list[idx] = {"kind": "wheat_protected", "feed_class": "protected", "is_protected": True, "n": w_prot}
                            om_list.insert(idx + 1, {"kind": "wheat_optional", "feed_class": "optional", "is_protected": False, "n": total_n - w_prot})
                            purchase_ledger["order_metadata"] = om_list
        hour = self._get_hour(ctx)
        day = self._get_day(ctx)
        effective_cap = max(0, cap)
        purchases_first = (hour in (0, 1))

        try:
            final_orders, diag = self._plan_market_core(
                ctx=ctx,
                macro_plan=macro_plan,
                purchases=purchases,
                purchase_ledger=purchase_ledger,
                sells=sells,
                sell_details=sell_details,
                cap=effective_cap,
                opp_advice=opp_advice,
                hour=hour,
                day=day,
                purchases_first=purchases_first,
            )
            # Post-arbitration consolidation: consolidate multiple accepted wheat buy orders into one
            wheat_buys = [o for o in final_orders if isinstance(o, (list, tuple)) and len(o) >= 3 and o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"]
            if len(wheat_buys) > 1:
                total_wheat = sum(int(o[2]) for o in wheat_buys)
                consolidated = []
                replaced = False
                for o in final_orders:
                    if isinstance(o, (list, tuple)) and len(o) >= 3 and o[0] == "BUY_PRODUCT" and o[1] == "WHEAT":
                        if not replaced:
                            consolidated.append(["BUY_PRODUCT", "WHEAT", total_wheat])
                            replaced = True
                    else:
                        consolidated.append(o)
                final_orders = consolidated
            return final_orders, diag
        except Exception as exc:
            # Resilient fallback: ensure turn never default-fails on unexpected error
            fallback_orders = legacy_compose_market(purchases, sells, ctx, cap=effective_cap)
            ordered_candidates = (purchases + sells) if (hour in (0, 1)) else (sells + purchases)
            rejected_orders = ordered_candidates[len(fallback_orders):]
            total_candidates = len(purchases) + len(sells)

            rejected_details = [
                {
                    "proposal_id": f"fallback_rejected:{idx}",
                    "order": list(o),
                    "rejection_reason": "fallback_slot_cap",
                }
                for idx, o in enumerate(rejected_orders)
            ]

            fallback_diag = {
                "error": str(exc),
                "planner_error": str(exc),
                "fallback_used": True,
                "fallback_reason": "central_planner_exception",
                "total_candidates": total_candidates,
                "accepted_orders": [list(o) for o in fallback_orders],
                "rejected_orders": [list(o) for o in rejected_orders],
                "rejected_details": rejected_details,
                "rejection_reasons": {"fallback_slot_cap": len(rejected_orders)} if rejected_orders else {},
                "changed_from_legacy": False,
                "selection_changed_from_legacy": False,
                "execution_order_only_changed": False,
                "changed_selection": False,
                "execution_reorder_only": False,
            }
            assert len(fallback_diag["accepted_orders"]) + len(fallback_diag["rejected_orders"]) == total_candidates
            return fallback_orders, fallback_diag

    def _plan_market_core(
        self,
        ctx: Any,
        macro_plan: Any,
        purchases: List[List[Any]],
        purchase_ledger: Any,
        sells: List[List[Any]],
        sell_details: Any,
        cap: int,
        opp_advice: Any,
        hour: int,
        day: int,
        purchases_first: bool,
    ) -> Tuple[List[List[Any]], Dict[str, Any]]:
        total_candidates = len(purchases) + len(sells)
        all_rejected: List[ProposalCandidate] = []

        # Step 1: Lightweight structural validation & candidate classification
        purchase_candidates: List[ProposalCandidate] = []
        for i, o in enumerate(purchases):
            is_valid, err = self._validate_proposal(o)
            if not is_valid:
                c = ProposalCandidate(
                    proposal_id=f"purchase:{i}",
                    order=list(o) if isinstance(o, (list, tuple)) else [o],
                    source="purchase",
                    kind="invalid",
                    priority_class=P4_DISCRETIONARY,
                    urgency=0.0,
                    original_index=i,
                    rejection_reason="invalid_order",
                    metadata={"validation_error": err},
                )
                all_rejected.append(c)
            else:
                c = self._classify_purchase(o, i, ctx, macro_plan, purchase_ledger, purchases=purchases)
                purchase_candidates.append(c)

        sell_candidates: List[ProposalCandidate] = []
        for i, o in enumerate(sells):
            is_valid, err = self._validate_proposal(o)
            if not is_valid:
                c = ProposalCandidate(
                    proposal_id=f"sell:{i}",
                    order=list(o) if isinstance(o, (list, tuple)) else [o],
                    source="sell",
                    kind="invalid",
                    priority_class=P4_DISCRETIONARY,
                    urgency=0.0,
                    original_index=i,
                    rejection_reason="invalid_order",
                    metadata={"validation_error": err},
                )
                all_rejected.append(c)
            else:
                c = self._classify_sell(o, i, ctx, sell_details, opp_advice)
                sell_candidates.append(c)

        # Step 2: Early Validation & Filtering
        # 2a. Accidental Duplicate Land Protection (only BUY_LAND is deduplicated)
        filtered_purchases: List[ProposalCandidate] = []
        seen_buy_land = False
        for c in purchase_candidates:
            if c.kind == "land":
                if seen_buy_land:
                    c.rejection_reason = "duplicate"
                    all_rejected.append(c)
                    continue
                seen_buy_land = True
            filtered_purchases.append(c)

        # 2b. Day 29 Non-Payoff Purchase Block
        active_purchases: List[ProposalCandidate] = []
        if day >= 29:
            for c in filtered_purchases:
                op = c.order[0] if c.order else ""
                prod = c.order[1] if len(c.order) > 1 else ""
                if op in ("BUY_SEED", "BUY_LAND", "BUY_ANIMAL") or (op == "BUY_PRODUCT" and prod == "FERTILIZER"):
                    c.rejection_reason = "endgame_purchase_block"
                    all_rejected.append(c)
                else:
                    active_purchases.append(c)
        else:
            active_purchases = filtered_purchases

        # 2c. Hard Conflict Resolution: Critical Feed Wheat Buy vs Sell Wheat
        has_critical_wheat_buy = any(
            c.kind in ("feed_wheat", "wheat_protected") and c.priority_class == P0_CRITICAL
            for c in active_purchases
        )
        active_sells: List[ProposalCandidate] = []
        for c in sell_candidates:
            prod = c.order[1] if len(c.order) > 1 else ""
            if prod == "WHEAT" and has_critical_wheat_buy:
                c.rejection_reason = "conflict_with_feed_requirement"
                all_rejected.append(c)
            else:
                active_sells.append(c)

        # Step 4: Rank Globally
        def ranking_key(c: ProposalCandidate) -> Tuple[int, int, float, int]:
            if purchases_first:
                source_tiebreak = 0 if c.source == "purchase" else 1
            else:
                source_tiebreak = 0 if c.source == "sell" else 1

            return (
                c.priority_class,
                source_tiebreak,
                -c.urgency,
                c.original_index,
            )

        active_candidates = active_purchases + active_sells
        ranked_candidates = sorted(active_candidates, key=ranking_key)

        # Step 5: Select <= cap
        selected_candidates = ranked_candidates[:cap]
        excess_candidates = ranked_candidates[cap:]

        for rank, c in enumerate(selected_candidates):
            c.selection_rank = rank

        for excess_rank, c in enumerate(excess_candidates):
            c.selection_rank = cap + excess_rank
            c.rejection_reason = "slot_cap"
            all_rejected.append(c)

        # Step 6: Explicitly Freeze Selected Set
        frozen_selected: List[ProposalCandidate] = list(selected_candidates)

        # Step 7: Reorder Selected Set for Safe Execution
        # Calculate incoming shed load from selected purchases
        incoming_shed_units = 0
        for c in frozen_selected:
            if c.source == "purchase":
                op = c.order[0] if c.order else ""
                if op == "BUY_ANIMAL":
                    incoming_shed_units += int(c.order[2]) if len(c.order) > 2 else 1
                elif op == "BUY_PRODUCT":
                    prod = c.order[1] if len(c.order) > 1 else ""
                    if prod in ("WHEAT", "FERTILIZER"):
                        incoming_shed_units += int(c.order[2]) if len(c.order) > 2 else 1

        freed_shed_units = 0
        for c in frozen_selected:
            if c.source == "sell":
                op = c.order[0] if c.order else ""
                if op == "SELL":
                    freed_shed_units += int(c.order[2]) if len(c.order) > 2 else 1

        current_shed = self._get_shed_total(ctx)
        shed_overflow_risk = (current_shed + incoming_shed_units > SHED_CAPACITY) and (freed_shed_units > 0)

        shed_pressure = False
        if isinstance(sell_details, dict):
            shed_pressure = bool(sell_details.get("pressure") or sell_details.get("urgency") == 2)
        if not shed_pressure:
            shed_pressure = (current_shed >= SHED_SOFT_CAP)

        sells_first = shed_pressure or (day >= 29) or shed_overflow_risk

        # Subsets with OrderBuilder purchase relative ordering preserved
        selected_sells = [c for c in frozen_selected if c.source == "sell"]
        # Retain OrderBuilder's upstream purchase order (stable sort by original_index)
        selected_purchases = sorted([c for c in frozen_selected if c.source == "purchase"], key=lambda c: c.original_index)

        if sells_first:
            execution_candidates = selected_sells + selected_purchases
        elif purchases_first:
            execution_candidates = selected_purchases + selected_sells
        else:
            execution_candidates = selected_sells + selected_purchases

        for exec_idx, c in enumerate(execution_candidates):
            c.execution_index = exec_idx

        # Invariant 1: exact payload preservation
        final_orders = [list(c.order) for c in execution_candidates]
        assert all(final_orders[i] == execution_candidates[i].order for i in range(len(final_orders)))

        # Invariant 2: proposal IDs exact conservation (no proposal lost or invented during execution reordering)
        assert sorted(c.proposal_id for c in execution_candidates) == sorted(c.proposal_id for c in frozen_selected)

        # Invariant 3: multiset payload equality (never collapses repeated orders like ["HIRE"], ["HIRE"])
        assert Counter(tuple(o) for o in final_orders) == Counter(tuple(c.order) for c in frozen_selected)

        # Invariant 4: total conservation
        assert len(final_orders) + len(all_rejected) == total_candidates

        # Invariant 5: unique proposal ID accounting
        all_accounted_ids = [c.proposal_id for c in execution_candidates] + [c.proposal_id for c in all_rejected]
        assert len(all_accounted_ids) == len(set(all_accounted_ids)) == total_candidates

        # Step 8: Telemetry & Diagnostics
        legacy_orders = legacy_compose_market(purchases, sells, ctx, cap=cap)

        changed_from_legacy = (final_orders != legacy_orders)

        # Compute structured change_reasons
        change_reasons: List[str] = []
        if any(c.rejection_reason == "conflict_with_feed_requirement" for c in all_rejected):
            change_reasons.append("conflict_resolution")
        if any(c.rejection_reason == "endgame_purchase_block" for c in all_rejected):
            change_reasons.append("endgame_block")
        if any(c.rejection_reason == "duplicate" for c in all_rejected):
            change_reasons.append("duplicate_filter")
        if any(c.rejection_reason == "invalid_order" for c in all_rejected):
            change_reasons.append("invalid_order_filter")

        legacy_counter = Counter(tuple(o) for o in legacy_orders)
        final_counter = Counter(tuple(o) for o in final_orders)
        if legacy_counter != final_counter:
            p0_p1_present = any(c.priority_class in (P0_CRITICAL, P1_URGENT) for c in execution_candidates)
            if p0_p1_present:
                change_reasons.append("priority_override")
            else:
                change_reasons.append("slot_reallocation")
        elif final_orders != legacy_orders:
            change_reasons.append("execution_reorder")

        # Upstream truncation detection
        purchase_truncation = bool(purchase_ledger.get("upstream_slots_limited")) if isinstance(purchase_ledger, dict) else False
        sell_truncation = bool(sell_details.get("upstream_truncation")) if isinstance(sell_details, dict) else False
        upstream_truncation_detected = purchase_truncation or sell_truncation

        accepted_by_priority = {name: 0 for name in PRIORITY_NAMES.values()}
        for c in execution_candidates:
            accepted_by_priority[PRIORITY_NAMES[c.priority_class]] += 1

        rejected_by_priority = {name: 0 for name in PRIORITY_NAMES.values()}
        for c in all_rejected:
            rejected_by_priority[PRIORITY_NAMES[c.priority_class]] += 1

        rejection_reasons = dict(Counter(c.rejection_reason for c in all_rejected if c.rejection_reason))

        accepted_details = [
            {
                "proposal_id": c.proposal_id,
                "order": list(c.order),
                "source": c.source,
                "kind": c.kind,
                "priority_class": c.priority_class,
                "urgency": c.urgency,
                "selection_rank": c.selection_rank,
                "execution_index": c.execution_index,
                "metadata": dict(c.metadata),
            }
            for c in execution_candidates
        ]

        rejected_details = [
            {
                "proposal_id": c.proposal_id,
                "order": list(c.order),
                "source": c.source,
                "kind": c.kind,
                "priority_class": c.priority_class,
                "urgency": c.urgency,
                "selection_rank": c.selection_rank,
                "rejection_reason": c.rejection_reason,
                "metadata": dict(c.metadata),
            }
            for c in all_rejected
        ]

        order_sources = [
            {"proposal_id": c.proposal_id, "order": list(c.order), "source": c.source}
            for c in (purchase_candidates + sell_candidates)
        ]
        accepted_sources = [c.source for c in execution_candidates]
        rejected_sources = [c.source for c in all_rejected]

        # Distinguish changed selection vs execution reorder only
        legacy_multiset = Counter(tuple(o) for o in legacy_orders)
        final_multiset = Counter(tuple(o) for o in final_orders)
        changed_selection = (legacy_multiset != final_multiset)
        execution_reorder_only = (not changed_selection) and (final_orders != legacy_orders)

        # Check for P0 priority inversions: P0 rejected with slot_cap while lower priority accepted
        p0_inversions = []
        accepted_lower = [c for c in execution_candidates if c.priority_class > P0_CRITICAL]
        for c in all_rejected:
            if c.priority_class == P0_CRITICAL and c.rejection_reason == "slot_cap":
                for acc in accepted_lower:
                    p0_inversions.append({
                        "rejected_p0": c.proposal_id,
                        "rejected_order": list(c.order),
                        "accepted_lower": acc.proposal_id,
                        "accepted_order": list(acc.order),
                        "accepted_priority": acc.priority_class,
                    })

        # Wheat-specific telemetry compilation
        all_proposals = execution_candidates + all_rejected
        wheat_proposals = [c for c in all_proposals if c.kind in ("feed_wheat", "wheat_protected", "wheat_optional")]
        wheat_P0_count = sum(1 for c in wheat_proposals if c.priority_class == P0_CRITICAL)
        wheat_P1_count = sum(1 for c in wheat_proposals if c.priority_class == P1_URGENT)
        wheat_P2_count = sum(1 for c in wheat_proposals if c.priority_class == P2_STRATEGIC)
        wheat_selected_count = sum(1 for c in execution_candidates if c.kind in ("feed_wheat", "wheat_protected", "wheat_optional"))
        wheat_rejected_count = sum(1 for c in all_rejected if c.kind in ("feed_wheat", "wheat_protected", "wheat_optional"))
        critical_wheat_rejected_count = sum(1 for c in all_rejected if c.kind in ("feed_wheat", "wheat_protected", "wheat_optional") and c.priority_class == P0_CRITICAL)
        wheat_protected_count = sum(1 for c in wheat_proposals if c.metadata.get("feed_class") == "protected")
        wheat_optional_count = sum(1 for c in wheat_proposals if c.metadata.get("feed_class") == "optional")

        # Check if routine wheat preempted any sells
        has_routine_wheat_accepted = any(c.kind in ("feed_wheat", "wheat_protected", "wheat_optional") and c.priority_class >= P2_STRATEGIC for c in execution_candidates)
        sells_rejected_by_cap = sum(1 for c in all_rejected if c.source == "sell" and c.rejection_reason == "slot_cap")
        routine_wheat_preempted_sell_count = sells_rejected_by_cap if has_routine_wheat_accepted else 0

        wheat_telemetry = {
            "wheat_P0_count": wheat_P0_count,
            "wheat_P1_count": wheat_P1_count,
            "wheat_P2_count": wheat_P2_count,
            "wheat_protected_count": wheat_protected_count,
            "wheat_optional_count": wheat_optional_count,
            "wheat_selected_count": wheat_selected_count,
            "wheat_rejected_count": wheat_rejected_count,
            "critical_wheat_rejected_count": critical_wheat_rejected_count,
            "routine_wheat_preempted_sell_count": routine_wheat_preempted_sell_count,
            "proposals": [
                {
                    "proposal_id": c.proposal_id,
                    "order": list(c.order),
                    "priority_class": c.priority_class,
                    "selected": (c in execution_candidates),
                    "rejection_reason": c.rejection_reason,
                    **c.metadata,
                }
                for c in wheat_proposals
            ],
        }

        # Sell pressure telemetry compilation
        sell_proposals = [c for c in all_proposals if c.source == "sell"]
        sell_telemetry = {
            "soft_cap_sell_P0_count": sum(1 for c in sell_proposals if c.metadata.get("sell_pressure_class") == "soft_cap_relief" and c.priority_class == P0_CRITICAL),
            "soft_cap_sell_P2_count": sum(1 for c in sell_proposals if c.metadata.get("sell_pressure_class") == "soft_cap_relief" and c.priority_class == P2_STRATEGIC),
            "hard_capacity_sell_P0_count": sum(1 for c in sell_proposals if c.metadata.get("sell_pressure_class") == "hard_capacity_emergency"),
            "midnight_sell_P0_count": sum(1 for c in sell_proposals if c.metadata.get("sell_pressure_class") == "midnight_hard_guard"),
            "day29_sell_P0_count": sum(1 for c in sell_proposals if c.metadata.get("sell_pressure_class") == "day29"),
            "total_sell_proposals": len(sell_proposals),
            "sells_selected_count": sum(1 for c in execution_candidates if c.source == "sell"),
            "sells_rejected_count": sum(1 for c in all_rejected if c.source == "sell"),
        }

        diagnostics: Dict[str, Any] = {
            "total_candidates": total_candidates,
            "purchase_candidates": len(purchases),
            "sell_candidates": len(sells),
            "final_selected": len(final_orders),
            "wheat_telemetry": wheat_telemetry,
            "sell_telemetry": sell_telemetry,
            "slot_pressure": (total_candidates > cap),
            "upstream_truncation_detected": upstream_truncation_detected,
            "accepted_orders": [list(o) for o in final_orders],
            "rejected_orders": [list(c.order) for c in all_rejected],
            "accepted_by_priority": accepted_by_priority,
            "rejected_by_priority": rejected_by_priority,
            "rejection_reasons": rejection_reasons,
            "order_sources": order_sources,
            "accepted_sources": accepted_sources,
            "rejected_sources": rejected_sources,
            "accepted_details": accepted_details,
            "rejected_details": rejected_details,
            "slots_used": len(final_orders),
            "slots_available": cap,
            "purchases_first": purchases_first,
            "first_priority": "purchase" if purchases_first else "sell",
            "legacy_orders": [list(o) for o in legacy_orders],
            "changed_from_legacy": changed_from_legacy,
            "changed_selection": changed_selection,
            "selection_changed_from_legacy": changed_selection,
            "execution_reorder_only": execution_reorder_only,
            "execution_order_only_changed": execution_reorder_only,
            "change_reasons": change_reasons,
            "p0_priority_inversion_count": len(p0_inversions),
            "p0_priority_inversions": p0_inversions,
            "emergency_execution": sells_first,
            "shed_overflow_risk": shed_overflow_risk,
        }

        return final_orders, diagnostics
