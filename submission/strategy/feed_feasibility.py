"""Point 2 — Shared Feed/Herd Feasibility Evaluator (Phase A: Shadow Architecture).

Authoritative reference:
  - architecture/point2_feed_herd_design.md
  - architecture/point2_feed_herd_implementation_plan.md

Design principles:
  1. Existing herd always receives first claim on resources.
  2. Two distinct horizons:
     - 4-day operational horizon: physical wheat & execution timing feasibility.
     - Remaining lifetime horizon: financial replacement funding feasibility.
  3. No speculative credit:
     - Only physically existing in-ground wheat tiles provide production credit.
     - Planned wheat, empty soil, future seeds, and SW targets receive ZERO hard credit.
     - Candidate animal revenue (milk/wool/eggs/fertilizer) receives ZERO hard credit.
     - Unrealized revenue from existing animals receives ZERO hard credit.
  4. Sequential candidate reservation:
     - Candidates are evaluated against the residual resource ledger.
     - Cash and wheat cannot be double-spent across candidates.
  5. Exact same-day market timing:
     - Unit actions execute before market actions.
     - Market wheat bought on Hour H cannot help an action on Hour H; it can only help
       later turns that day (Hours H+1 .. 23).
     - At Hour 23 there are zero subsequent turns, so same-turn market wheat cannot
       rescue today's unmet feed deadline.
  6. Semantic distinction:
     - Placed animals create immediate physical feeding obligations.
     - Owned but unplaced animals do NOT consume wheat today, but create conservative
       future lifetime funding liabilities.
     - Incremental candidate animals are evaluated as unplaced commitments that do NOT
       eat today, but require physical feed starting tomorrow and conservative lifetime funding.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from config import (
        ANIMAL_FEED_CUTOFF_DAY,
        ANIMAL_LIST,
        ANIMALS,
        FEED_OPERATIONAL_HORIZON_DAYS,
        FEED_WHEAT_BUFFER_DAYS,
        SEASON_DAYS,
        SHED_CAPACITY,
        get_point2_feed_mode,
    )
except ImportError:
    ANIMAL_FEED_CUTOFF_DAY = 29
    ANIMAL_LIST = ["COW", "SHEEP", "GOOSE"]
    ANIMALS = {
        "COW": {"cost": 500, "space": 4},
        "SHEEP": {"cost": 250, "space": 4},
        "GOOSE": {"cost": 100, "space": 1},
    }
    FEED_OPERATIONAL_HORIZON_DAYS = 4
    FEED_WHEAT_BUFFER_DAYS = 4
    SEASON_DAYS = 30
    SHED_CAPACITY = 100

    def get_point2_feed_mode() -> str:
        return "shadow"

try:
    from market.price_math import estimate_wheat_buy_price
except ImportError:
    try:
        from price_math import estimate_wheat_buy_price
    except ImportError:
        def estimate_wheat_buy_price(market_or_ctx=None, default_price=25.0) -> float:
            return float(math.ceil(default_price * 1.1))


# ============================================================================
# Core Data Classes
# ============================================================================

@dataclass(frozen=True)
class TimedWheatDelivery:
    """A dated, physically secured wheat arrival."""
    day: int
    units: int
    source: str = "physical_wheat_tile"  # "physical_wheat_tile", "market_purchase"


@dataclass
class FeedExecutionSnapshot:
    """Summarizes current-turn execution and scheduler reality."""
    day: int
    hour: int
    turns_remaining_today: int
    feeds_due_today: int
    feeds_assigned_this_turn: int
    wheat_pickups_assigned_this_turn: int
    worker_wheat: int
    shed_wheat: int
    n_active_units: int
    market_purchase_can_help_today: bool
    execution_confidence: str = "high"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FeedResourceLedger:
    """Shared shadow resource state supporting sequential candidate admission.

    Maintains separate semantic cash holds to prevent double spending.
    """
    day: int
    hour: int
    operational_horizon_days: int
    observed_cash: float

    hard_cash_hold: float = 0.0
    existing_feed_cash_hold: float = 0.0
    strategic_cash_hold: float = 0.0
    candidate_feed_cash_hold: float = 0.0
    candidate_purchase_cash_spent: float = 0.0

    unfed_placed_today: int = 0

    wheat_in_shed: int = 0
    wheat_on_workers: int = 0
    shed_other_units: int = 0
    shed_capacity: int = SHED_CAPACITY

    placed_herd: Dict[str, int] = field(default_factory=dict)
    owned_unplaced_herd: Dict[str, int] = field(default_factory=dict)

    secured_wheat_deliveries: List[TimedWheatDelivery] = field(default_factory=list)
    scheduled_market_purchases: List[Dict[str, Any]] = field(default_factory=list)
    candidate_reservations: List[Dict[str, Any]] = field(default_factory=list)

    execution_snapshot: Optional[FeedExecutionSnapshot] = None
    wheat_price_current: float = 28.0
    lifetime_price_policy: str = "conditional_current_buffered_price"
    unplaced_timing_assumption: str = "future_funding_liability_not_eating_today"

    def clone(self) -> "FeedResourceLedger":
        """Produce an independent deep copy of this ledger."""
        return FeedResourceLedger(
            day=self.day,
            hour=self.hour,
            operational_horizon_days=self.operational_horizon_days,
            observed_cash=self.observed_cash,
            hard_cash_hold=self.hard_cash_hold,
            existing_feed_cash_hold=self.existing_feed_cash_hold,
            strategic_cash_hold=self.strategic_cash_hold,
            candidate_feed_cash_hold=self.candidate_feed_cash_hold,
            candidate_purchase_cash_spent=self.candidate_purchase_cash_spent,
            unfed_placed_today=self.unfed_placed_today,
            wheat_in_shed=self.wheat_in_shed,
            wheat_on_workers=self.wheat_on_workers,
            shed_other_units=self.shed_other_units,
            shed_capacity=self.shed_capacity,
            placed_herd=dict(self.placed_herd),
            owned_unplaced_herd=dict(self.owned_unplaced_herd),
            secured_wheat_deliveries=list(self.secured_wheat_deliveries),
            scheduled_market_purchases=copy.deepcopy(self.scheduled_market_purchases),
            candidate_reservations=copy.deepcopy(self.candidate_reservations),
            execution_snapshot=copy.deepcopy(self.execution_snapshot),
            wheat_price_current=self.wheat_price_current,
            lifetime_price_policy=self.lifetime_price_policy,
            unplaced_timing_assumption=self.unplaced_timing_assumption,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert ledger to a serializable dictionary."""
        return {
            "day": self.day,
            "hour": self.hour,
            "operational_horizon_days": self.operational_horizon_days,
            "observed_cash": self.observed_cash,
            "hard_cash_hold": self.hard_cash_hold,
            "existing_feed_cash_hold": self.existing_feed_cash_hold,
            "strategic_cash_hold": self.strategic_cash_hold,
            "candidate_feed_cash_hold": self.candidate_feed_cash_hold,
            "candidate_purchase_cash_spent": self.candidate_purchase_cash_spent,
            "available_cash_for_candidates": self.available_cash_for_candidates,
            "unfed_placed_today": self.unfed_placed_today,
            "wheat_in_shed": self.wheat_in_shed,
            "wheat_on_workers": self.wheat_on_workers,
            "shed_other_units": self.shed_other_units,
            "shed_capacity": self.shed_capacity,
            "placed_herd": dict(self.placed_herd),
            "owned_unplaced_herd": dict(self.owned_unplaced_herd),
            "wheat_price_current": self.wheat_price_current,
            "lifetime_price_policy": self.lifetime_price_policy,
            "candidate_reservations_count": len(self.candidate_reservations),
            "scheduled_market_purchases_count": len(self.scheduled_market_purchases),
        }

    @property
    def total_placed_animals(self) -> int:
        return sum(self.placed_herd.values())

    @property
    def total_owned_unplaced_animals(self) -> int:
        return sum(self.owned_unplaced_herd.values())

    @property
    def total_owned_animals(self) -> int:
        return self.total_placed_animals + self.total_owned_unplaced_animals

    @property
    def available_cash_for_candidates(self) -> float:
        """Cash available strictly for new candidate purchases and candidate feed reserves."""
        spent_or_held = (
            self.hard_cash_hold
            + self.existing_feed_cash_hold
            + self.strategic_cash_hold
            + self.candidate_purchase_cash_spent
            + self.candidate_feed_cash_hold
        )
        return max(0.0, self.observed_cash - spent_or_held)

    @property
    def current_total_wheat_on_hand(self) -> int:
        return self.wheat_in_shed + self.wheat_on_workers


@dataclass
class FeedFeasibilityResult:
    """Diagnostic and decision result from feed feasibility evaluation."""
    feasible: bool
    existing_herd_feasible: bool
    candidate_species: Optional[str] = None

    near_term_feed_units: int = 0
    near_term_market_wheat_required: int = 0

    remaining_lifetime_feed_units: int = 0
    remaining_feed_cash_required: float = 0.0

    existing_feed_cash_hold: float = 0.0
    candidate_feed_cash_hold: float = 0.0

    minimum_wheat_slack: float = 0.0
    minimum_cash_slack: float = 0.0

    blocking_day: Optional[int] = None
    blocking_reason: Optional[str] = None

    scheduled_market_purchases: List[Dict[str, Any]] = field(default_factory=list)
    daily_timeline: List[Dict[str, Any]] = field(default_factory=list)

    price_policy: str = "conditional_current_buffered_price"
    execution_confidence: str = "high"
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# Physical Wheat Harvest Collection
# ============================================================================

def collect_secured_wheat_deliveries(
    farm: Any,
    current_day: int,
    operational_end_day: int,
) -> List[TimedWheatDelivery]:
    """Extract only physically secured wheat production from live in-ground tiles.

    Rules:
      - Conservative harvest day: placed_day + 4.
      - Conservative yield: 6 units if fertilized at or after placement, 4 units otherwise.
      - Bounded by operational horizon: only deliveries arriving on or before
        operational_end_day are included.
      - Zero credit for empty soil, planned wheat, future SW, or seed purchases.
    """
    deliveries: List[TimedWheatDelivery] = []
    if not hasattr(farm, "iter_tiles"):
        return deliveries

    for t in farm.iter_tiles():
        if t is None or t == "LOCKED":
            continue

        is_plant = getattr(t, "is_plant", False) if not isinstance(t, dict) else (t.get("is_plant", False) or t.get("kind") == "PLANT")
        crop = getattr(t, "crop", None) if not isinstance(t, dict) else t.get("crop")

        if not (is_plant and crop == "WHEAT"):
            continue

        placed = getattr(t, "placed_day", None) if not isinstance(t, dict) else t.get("placed_day")
        if placed is None:
            placed = current_day

        h_day = placed + 4
        fert_day = getattr(t, "fertilized_until_day", None) if not isinstance(t, dict) else t.get("fertilized_until_day")
        is_fert = fert_day is not None and fert_day >= placed
        yield_units = 6 if is_fert else 4

        effective_arrival_day = max(current_day, h_day)

        if effective_arrival_day <= operational_end_day:
            deliveries.append(
                TimedWheatDelivery(
                    day=effective_arrival_day,
                    units=yield_units,
                    source="physical_wheat_tile",
                )
            )

    deliveries.sort(key=lambda d: d.day)
    return deliveries


# ============================================================================
# Execution Snapshot Construction
# ============================================================================

def build_feed_execution_snapshot(
    ctx: Any,
    tasks: Any = None,
    assignment: Any = None,
) -> FeedExecutionSnapshot:
    """Summarizes current-turn execution state and scheduler reality.

    Accepts either the full scheduler output dict or the assignment subdict.
    Accurately reflects engine timing:
      - Unit actions occur BEFORE market orders are processed.
      - Wheat bought on Hour H cannot help actions already executed on Hour H.
      - It can only potentially help later turns that day (Hours H+1 .. 23).
      - At Hour 23, turns_remaining_today == 1 (the current turn), meaning zero
        subsequent unit-action turns exist today; same-turn market wheat cannot
        rescue today's unmet feed deadline.
    """
    day = int(ctx.get("day", 0)) if isinstance(ctx, dict) else int(getattr(ctx, "day", 0))
    hour = int(ctx.get("hour", 0)) if isinstance(ctx, dict) else int(getattr(ctx, "hour", 0))
    turns_remaining = max(0, 24 - hour)

    farm = ctx["farm"] if isinstance(ctx, dict) else getattr(ctx, "farm", None)
    private = ctx.get("private") if isinstance(ctx, dict) else getattr(ctx, "private", None)

    shed_wheat = 0
    worker_wheat = 0
    if private is not None:
        if hasattr(private, "shed") and isinstance(private.shed, dict):
            shed_wheat = int(private.shed.get("WHEAT", 0))
        elif isinstance(private, dict) and "shed" in private:
            shed_wheat = int(private["shed"].get("WHEAT", 0))

        inventories = getattr(private, "inventories", None) or (private.get("inventories") if isinstance(private, dict) else None)
        if inventories and isinstance(inventories, list):
            for inv in inventories:
                if isinstance(inv, dict):
                    worker_wheat += int(inv.get("WHEAT", 0))

    n_active_units = 1
    if farm is not None:
        hands = getattr(farm, "hands", None) or (farm.get("hands") if isinstance(farm, dict) else None)
        if hands and hasattr(hands, "__len__"):
            n_active_units += len(hands)

    asg_map = {}
    if assignment is not None:
        if isinstance(assignment, dict):
            if "assignment" in assignment and isinstance(assignment["assignment"], dict):
                asg_map = assignment["assignment"]
            else:
                asg_map = assignment

    feeds_assigned = 0
    wheat_pickups_assigned = 0
    for task in asg_map.values():
        if not isinstance(task, dict):
            continue
        op = task.get("op")
        kind = task.get("kind", "")
        args = task.get("args") or []

        if op == "FEED" or kind.startswith("feed"):
            feeds_assigned += 1
        elif op == "PICKUP":
            if (args and args[0] == "WHEAT") or "wheat" in kind:
                wheat_pickups_assigned += 1

    feeds_due_today = 0
    if tasks and isinstance(tasks, list):
        for t in tasks:
            if isinstance(t, dict):
                if t.get("op") == "FEED" or str(t.get("kind", "")).startswith("feed"):
                    feeds_due_today += 1
    else:
        if farm and hasattr(farm, "iter_tiles"):
            for t in farm.iter_tiles():
                if t and getattr(t, "is_animal", False):
                    if not getattr(t, "fed_today", False):
                        feeds_due_today += 1

    market_purchase_can_help_today = (hour < 23)

    confidence = "high"
    if tasks is None and assignment is None:
        confidence = "guarded"
    elif hour >= 23 and feeds_due_today > feeds_assigned:
        confidence = "conditional"
    elif hour >= 22 and feeds_due_today > (feeds_assigned + worker_wheat):
        confidence = "guarded"
    elif hour >= 20 and feeds_due_today > (feeds_assigned + worker_wheat):
        confidence = "guarded"

    return FeedExecutionSnapshot(
        day=day,
        hour=hour,
        turns_remaining_today=turns_remaining,
        feeds_due_today=feeds_due_today,
        feeds_assigned_this_turn=feeds_assigned,
        wheat_pickups_assigned_this_turn=wheat_pickups_assigned,
        worker_wheat=worker_wheat,
        shed_wheat=shed_wheat,
        n_active_units=n_active_units,
        market_purchase_can_help_today=market_purchase_can_help_today,
        execution_confidence=confidence,
    )


# ============================================================================
# Ledger Builder
# ============================================================================

def build_feed_resource_ledger(
    ctx: Any,
    current_herd: Any = None,
    hard_cash_hold: float = 0.0,
    strategic_cash_hold: float = 0.0,
    execution_snapshot: Optional[FeedExecutionSnapshot] = None,
    horizon_days: int = FEED_OPERATIONAL_HORIZON_DAYS,
) -> FeedResourceLedger:
    """Constructs the initial FeedResourceLedger from observation state.

    Semantics:
      - placed_herd: animals physically on farm tiles (immediate feeding obligations).
      - owned_unplaced_herd: animals in shed or worker inventory (already paid commitments,
        creating conservative future lifetime funding liabilities).
      - unfed_placed_today: actual count of placed animals not yet fed today.
    """
    day = int(ctx.get("day", 0)) if isinstance(ctx, dict) else int(getattr(ctx, "day", 0))
    hour = int(ctx.get("hour", 0)) if isinstance(ctx, dict) else int(getattr(ctx, "hour", 0))

    if execution_snapshot is None:
        try:
            execution_snapshot = build_feed_execution_snapshot(ctx)
        except Exception:
            execution_snapshot = None

    farm = ctx["farm"] if isinstance(ctx, dict) else getattr(ctx, "farm", None)
    private = ctx.get("private") if isinstance(ctx, dict) else getattr(ctx, "private", None)

    money = float(farm.money) if (farm and hasattr(farm, "money")) else (
        float(farm.get("money", 0.0)) if isinstance(farm, dict) else 0.0
    )

    shed = {}
    inventories = []
    if private is not None:
        if hasattr(private, "shed") and isinstance(private.shed, dict):
            shed = private.shed
        elif isinstance(private, dict) and "shed" in private:
            shed = private["shed"]

        invs = getattr(private, "inventories", None) or (private.get("inventories") if isinstance(private, dict) else None)
        if invs and isinstance(invs, list):
            inventories = invs

    wheat_in_shed = int(shed.get("WHEAT", 0))
    wheat_on_workers = sum(int(inv.get("WHEAT", 0)) for inv in inventories if isinstance(inv, dict))
    shed_other_units = sum(int(v) for k, v in shed.items() if k != "WHEAT")

    placed_herd: Dict[str, int] = {a: 0 for a in ANIMAL_LIST}
    owned_unplaced_herd: Dict[str, int] = {a: 0 for a in ANIMAL_LIST}
    unfed_placed_today = 0

    if current_herd is not None and isinstance(current_herd, dict):
        if "placed" in current_herd and isinstance(current_herd["placed"], dict):
            for a in ANIMAL_LIST:
                placed_herd[a] = int(current_herd["placed"].get(a, 0))
        else:
            for a in ANIMAL_LIST:
                placed_herd[a] = int(current_herd.get(a, 0))

        if "unplaced" in current_herd and isinstance(current_herd["unplaced"], dict):
            for a in ANIMAL_LIST:
                owned_unplaced_herd[a] = int(current_herd["unplaced"].get(a, 0))

        if "unfed_placed_today" in current_herd:
            unfed_placed_today = int(current_herd["unfed_placed_today"])
        elif farm and hasattr(farm, "iter_tiles"):
            for t in farm.iter_tiles():
                if t is None or t == "LOCKED":
                    continue
                is_anim = getattr(t, "is_animal", False) if not isinstance(t, dict) else t.get("is_animal", False)
                if is_anim:
                    fed = getattr(t, "fed_today", False) if not isinstance(t, dict) else t.get("fed_today", False)
                    if not fed:
                        unfed_placed_today += 1
        else:
            unfed_placed_today = sum(placed_herd.values())
    else:
        if farm and hasattr(farm, "iter_tiles"):
            for t in farm.iter_tiles():
                if t is None or t == "LOCKED":
                    continue
                is_anim = getattr(t, "is_animal", False) if not isinstance(t, dict) else t.get("is_animal", False)
                if is_anim:
                    species = getattr(t, "animal", None) if not isinstance(t, dict) else t.get("animal")
                    if species in placed_herd:
                        placed_herd[species] += 1
                    fed = getattr(t, "fed_today", False) if not isinstance(t, dict) else t.get("fed_today", False)
                    if not fed:
                        unfed_placed_today += 1
        elif execution_snapshot is not None:
            unfed_placed_today = execution_snapshot.feeds_due_today

        for a in ANIMAL_LIST:
            owned_unplaced_herd[a] += int(shed.get(a, 0))
            for inv in inventories:
                if isinstance(inv, dict):
                    owned_unplaced_herd[a] += int(inv.get(a, 0))

    operational_end_day = min(SEASON_DAYS - 1, day + horizon_days - 1)
    secured_deliveries = collect_secured_wheat_deliveries(farm, day, operational_end_day)

    wheat_price = estimate_wheat_buy_price(ctx)

    return FeedResourceLedger(
        day=day,
        hour=hour,
        operational_horizon_days=horizon_days,
        observed_cash=money,
        hard_cash_hold=float(hard_cash_hold),
        existing_feed_cash_hold=0.0,
        strategic_cash_hold=float(strategic_cash_hold),
        candidate_feed_cash_hold=0.0,
        candidate_purchase_cash_spent=0.0,
        unfed_placed_today=unfed_placed_today,
        wheat_in_shed=wheat_in_shed,
        wheat_on_workers=wheat_on_workers,
        shed_other_units=shed_other_units,
        shed_capacity=SHED_CAPACITY,
        placed_herd=placed_herd,
        owned_unplaced_herd=owned_unplaced_herd,
        secured_wheat_deliveries=secured_deliveries,
        scheduled_market_purchases=[],
        candidate_reservations=[],
        execution_snapshot=execution_snapshot,
        wheat_price_current=wheat_price,
        lifetime_price_policy="conditional_current_buffered_price",
        unplaced_timing_assumption="future_funding_liability_not_eating_today",
    )


# ============================================================================
# Existing Herd Feasibility Evaluator
# ============================================================================

def evaluate_existing_herd_feasibility(
    ledger: FeedResourceLedger,
) -> Tuple[bool, FeedFeasibilityResult]:
    """Evaluate baseline feasibility of the existing herd.

    Existing animals receive absolute first claim on all physical wheat and cash.
    If the existing herd cannot be safely sustained, expansion is blocked completely.

    Enforces:
      - 4-day operational prefix-timed physical feed feasibility for placed animals.
      - Scheduled minimum market wheat purchases when prefix deficit appears.
      - Shed storage capacity checks at acquisition time.
      - Remaining-lifetime feed funding for all owned animals (placed + unplaced).
      - Strict engine timing: market wheat bought at Hour 23 cannot rescue today.
    """
    day = ledger.day
    hour = ledger.hour
    horizon = ledger.operational_horizon_days

    n_placed = ledger.total_placed_animals
    n_unplaced = ledger.total_owned_unplaced_animals
    total_owned = n_placed + n_unplaced

    exec_conf = ledger.execution_snapshot.execution_confidence if ledger.execution_snapshot is not None else "guarded"

    if total_owned == 0:
        res = FeedFeasibilityResult(
            feasible=True,
            existing_herd_feasible=True,
            minimum_wheat_slack=float(ledger.current_total_wheat_on_hand),
            minimum_cash_slack=ledger.observed_cash - ledger.hard_cash_hold - ledger.strategic_cash_hold,
            execution_confidence=exec_conf,
            diagnostics={"note": "no_animals_owned"},
        )
        return True, res

    operational_days = [d for d in range(day, day + horizon) if d < ANIMAL_FEED_CUTOFF_DAY]

    scheduled_buys: List[Dict[str, Any]] = []
    daily_timeline: List[Dict[str, Any]] = []

    cumulative_needed = 0
    cumulative_physical_deliveries = 0
    cumulative_market_purchased = 0

    min_wheat_slack = float("inf")
    blocking_reason: Optional[str] = None
    blocking_day: Optional[int] = None

    cash_available_for_existing_feed = max(
        0.0, ledger.observed_cash - ledger.hard_cash_hold - ledger.strategic_cash_hold
    )
    current_cash = cash_available_for_existing_feed

    can_help_today = True
    if ledger.execution_snapshot is not None:
        can_help_today = ledger.execution_snapshot.market_purchase_can_help_today
    elif hour >= 23:
        can_help_today = False

    feed_consumed_prior = 0
    cumulative_market_purchased_prior = 0

    for target_day in operational_days:
        new_deliveries = sum(d.units for d in ledger.secured_wheat_deliveries if d.day == target_day)
        cumulative_physical_deliveries += new_deliveries

        if target_day == day:
            needed_day = ledger.unfed_placed_today
        else:
            needed_day = n_placed
        cumulative_needed += needed_day

        available_before_buy = (
            ledger.current_total_wheat_on_hand
            + cumulative_physical_deliveries
            + cumulative_market_purchased
        )
        deficit = max(0, cumulative_needed - available_before_buy)

        if deficit > 0:
            if target_day == day and not can_help_today:
                blocking_reason = "late_hour_purchase"
                blocking_day = day
                break

            purchase_cost = float(deficit * ledger.wheat_price_current)
            if purchase_cost > current_cash:
                blocking_reason = "insufficient_cash"
                blocking_day = target_day
                break

            shed_feed_consumed_prior = max(0, feed_consumed_prior - ledger.wheat_on_workers)
            prior_shed_wheat = max(0, ledger.wheat_in_shed + cumulative_market_purchased_prior - shed_feed_consumed_prior)
            current_shed_load = ledger.shed_other_units + prior_shed_wheat

            if current_shed_load + deficit > ledger.shed_capacity:
                blocking_reason = "shed_capacity"
                blocking_day = target_day
                break

            scheduled_buys.append({
                "day": target_day,
                "units": deficit,
                "cost": purchase_cost,
                "purpose": "existing_herd_operational",
            })
            cumulative_market_purchased += deficit
            current_cash -= purchase_cost

        feed_consumed_prior += needed_day
        cumulative_market_purchased_prior = cumulative_market_purchased

        slack = (
            ledger.current_total_wheat_on_hand
            + cumulative_physical_deliveries
            + cumulative_market_purchased
            - cumulative_needed
        )
        min_wheat_slack = min(min_wheat_slack, slack)

        daily_timeline.append({
            "day": target_day,
            "needed": needed_day,
            "deliveries": new_deliveries,
            "market_purchased": deficit,
            "slack": slack,
        })

    if blocking_reason is not None:
        res = FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=False,
            blocking_day=blocking_day,
            blocking_reason=blocking_reason,
            minimum_wheat_slack=min_wheat_slack if min_wheat_slack != float("inf") else 0.0,
            minimum_cash_slack=current_cash,
            scheduled_market_purchases=scheduled_buys,
            daily_timeline=daily_timeline,
            execution_confidence=exec_conf,
        )
        return False, res

    last_op_day = operational_days[-1] if operational_days else day - 1
    remaining_feeding_days_beyond = max(0, ANIMAL_FEED_CUTOFF_DAY - (last_op_day + 1))

    placed_lifetime_units = n_placed * remaining_feeding_days_beyond
    placed_lifetime_cost = float(placed_lifetime_units * ledger.wheat_price_current)

    total_feeding_days_from_today = max(0, ANIMAL_FEED_CUTOFF_DAY - day)
    unplaced_lifetime_units = n_unplaced * total_feeding_days_from_today
    unplaced_lifetime_cost = float(unplaced_lifetime_units * ledger.wheat_price_current)

    total_remaining_lifetime_units = placed_lifetime_units + unplaced_lifetime_units
    total_remaining_lifetime_cost = placed_lifetime_cost + unplaced_lifetime_cost

    near_term_market_wheat_cost = sum(b["cost"] for b in scheduled_buys)
    total_existing_feed_cash_required = near_term_market_wheat_cost + total_remaining_lifetime_cost

    if total_existing_feed_cash_required > cash_available_for_existing_feed:
        res = FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=False,
            blocking_day=last_op_day + 1,
            blocking_reason="insufficient_cash",
            near_term_feed_units=cumulative_needed,
            near_term_market_wheat_required=cumulative_market_purchased,
            remaining_lifetime_feed_units=total_remaining_lifetime_units,
            remaining_feed_cash_required=total_remaining_lifetime_cost,
            existing_feed_cash_hold=total_existing_feed_cash_required,
            minimum_wheat_slack=min_wheat_slack,
            minimum_cash_slack=cash_available_for_existing_feed - total_existing_feed_cash_required,
            scheduled_market_purchases=scheduled_buys,
            daily_timeline=daily_timeline,
            execution_confidence=exec_conf,
        )
        return False, res

    min_cash_slack = cash_available_for_existing_feed - total_existing_feed_cash_required

    res = FeedFeasibilityResult(
        feasible=True,
        existing_herd_feasible=True,
        near_term_feed_units=cumulative_needed,
        near_term_market_wheat_required=cumulative_market_purchased,
        remaining_lifetime_feed_units=total_remaining_lifetime_units,
        remaining_feed_cash_required=total_remaining_lifetime_cost,
        existing_feed_cash_hold=total_existing_feed_cash_required,
        candidate_feed_cash_hold=0.0,
        minimum_wheat_slack=min_wheat_slack,
        minimum_cash_slack=min_cash_slack,
        scheduled_market_purchases=scheduled_buys,
        daily_timeline=daily_timeline,
        execution_confidence=exec_conf,
        diagnostics={
            "near_term_market_cost": near_term_market_wheat_cost,
            "placed_lifetime_cost": placed_lifetime_cost,
            "unplaced_lifetime_cost": unplaced_lifetime_cost,
            "unplaced_timing_assumption": ledger.unplaced_timing_assumption,
        },
    )
    ledger.existing_feed_cash_hold = float(total_existing_feed_cash_required)
    return True, res


# ============================================================================
# Incremental Candidate Feasibility Evaluator
# ============================================================================

def evaluate_incremental_candidate(
    ledger: FeedResourceLedger,
    candidate_species: str,
    purchase_cost: Optional[float] = None,
) -> FeedFeasibilityResult:
    """Evaluate whether one incremental candidate animal is resource-feasible.

    Rules:
      - Always clones the ledger: candidate testing NEVER mutates the caller's ledger.
      - Existing herd must be baseline feasible; if not, fails immediately.
      - Candidate purchase cost is tested against available candidate cash.
      - Candidate's near-term (4-day) physical feed requirement is evaluated.
      - Candidate does NOT consume wheat today (target_day == day), because it is
        an unplaced purchase commitment rather than a placed tile animal.
      - Candidate creates physical feed requirement starting tomorrow (target_day > day).
      - Candidate's remaining-lifetime feed funding is evaluated conservatively.
      - Candidate-generated revenue (milk/wool/egg/fertilizer) contributes ZERO credit.
      - Unrealized output of existing animals contributes ZERO credit.
    """
    if candidate_species not in ANIMALS:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=False,
            candidate_species=candidate_species,
            blocking_reason="invalid_species",
            execution_confidence=ledger.execution_snapshot.execution_confidence if ledger.execution_snapshot else "guarded",
        )

    existing_ok, existing_res = evaluate_existing_herd_feasibility(ledger)
    exec_conf = ledger.execution_snapshot.execution_confidence if ledger.execution_snapshot is not None else "guarded"
    if not existing_ok:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=False,
            candidate_species=candidate_species,
            blocking_reason="baseline_existing_herd_infeasible",
            execution_confidence=exec_conf,
            diagnostics={"existing_herd_result": existing_res.to_dict()},
        )

    if purchase_cost is None:
        purchase_cost = float(ANIMALS[candidate_species]["cost"])

    available_candidate_cash = ledger.available_cash_for_candidates
    if purchase_cost > available_candidate_cash:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=True,
            candidate_species=candidate_species,
            blocking_day=ledger.day,
            blocking_reason="insufficient_cash",
            minimum_cash_slack=available_candidate_cash - purchase_cost,
            existing_feed_cash_hold=existing_res.existing_feed_cash_hold,
            candidate_feed_cash_hold=0.0,
            execution_confidence=exec_conf,
        )

    shadow = ledger.clone()
    # Candidate does NOT enter shadow.placed_herd today! (Semantic distinction)

    day = shadow.day
    hour = shadow.hour
    horizon = shadow.operational_horizon_days
    operational_days = [d for d in range(day, day + horizon) if d < ANIMAL_FEED_CUTOFF_DAY]

    can_help_today = True
    if shadow.execution_snapshot is not None:
        can_help_today = shadow.execution_snapshot.market_purchase_can_help_today
    elif hour >= 23:
        can_help_today = False

    # Collect scheduled market purchases from baseline herd and prior committed candidates
    existing_scheduled_units_by_day: Dict[int, int] = {}
    for buy in existing_res.scheduled_market_purchases:
        b_day = buy["day"]
        existing_scheduled_units_by_day[b_day] = existing_scheduled_units_by_day.get(b_day, 0) + buy["units"]
    for buy in shadow.scheduled_market_purchases:
        b_day = buy["day"]
        existing_scheduled_units_by_day[b_day] = existing_scheduled_units_by_day.get(b_day, 0) + buy["units"]

    cand_scheduled_buys: List[Dict[str, Any]] = []
    daily_timeline: List[Dict[str, Any]] = []

    cumulative_needed = 0
    cumulative_deliveries = 0
    cumulative_market_purchased = 0
    cand_cumulative_market_purchased = 0

    min_wheat_slack = float("inf")
    blocking_reason: Optional[str] = None
    blocking_day: Optional[int] = None

    cash_after_purchase = available_candidate_cash - purchase_cost
    running_candidate_cash = cash_after_purchase

    feed_consumed_prior = 0
    cumulative_market_purchased_prior = 0

    for target_day in operational_days:
        new_deliveries = sum(d.units for d in shadow.secured_wheat_deliveries if d.day == target_day)
        cumulative_deliveries += new_deliveries

        # Prefix timing: only market purchases scheduled for target_day
        new_existing_market_wheat = existing_scheduled_units_by_day.get(target_day, 0)
        cumulative_market_purchased += new_existing_market_wheat

        # Day-by-day feed requirements:
        # Today: unfed placed animals need feed; candidate and prior candidates do NOT eat today (unplaced).
        # Future days: baseline placed herd + prior committed candidates + current candidate eat 1 each.
        if target_day == day:
            needed_day = shadow.unfed_placed_today
        else:
            needed_day = shadow.total_placed_animals + len(shadow.candidate_reservations) + 1

        cumulative_needed += needed_day

        available_before_cand_buy = (
            shadow.current_total_wheat_on_hand
            + cumulative_deliveries
            + cumulative_market_purchased
        )
        deficit = max(0, cumulative_needed - available_before_cand_buy)

        if deficit > 0:
            if target_day == day and not can_help_today:
                blocking_reason = "late_hour_purchase"
                blocking_day = day
                break

            buy_cost = float(deficit * shadow.wheat_price_current)
            if buy_cost > running_candidate_cash:
                blocking_reason = "insufficient_cash"
                blocking_day = target_day
                break

            # Shed capacity check at acquisition time on target_day:
            shed_feed_consumed_prior = max(0, feed_consumed_prior - shadow.wheat_on_workers)
            prior_shed_wheat = max(0, shadow.wheat_in_shed + cumulative_market_purchased_prior - shed_feed_consumed_prior)
            current_shed_load = shadow.shed_other_units + prior_shed_wheat

            if current_shed_load + deficit > shadow.shed_capacity:
                blocking_reason = "shed_capacity"
                blocking_day = target_day
                break

            cand_scheduled_buys.append({
                "day": target_day,
                "units": deficit,
                "cost": buy_cost,
                "purpose": f"candidate_{candidate_species}_operational",
            })
            cumulative_market_purchased += deficit
            cand_cumulative_market_purchased += deficit
            running_candidate_cash -= buy_cost

        feed_consumed_prior += needed_day
        cumulative_market_purchased_prior = cumulative_market_purchased

        slack = (
            shadow.current_total_wheat_on_hand
            + cumulative_deliveries
            + cumulative_market_purchased
            - cumulative_needed
        )
        min_wheat_slack = min(min_wheat_slack, slack)

        daily_timeline.append({
            "day": target_day,
            "needed": needed_day,
            "deliveries": new_deliveries,
            "cand_market_purchased": deficit,
            "slack": slack,
        })

    if blocking_reason is not None:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=True,
            candidate_species=candidate_species,
            blocking_day=blocking_day,
            blocking_reason=blocking_reason,
            minimum_wheat_slack=min_wheat_slack if min_wheat_slack != float("inf") else 0.0,
            minimum_cash_slack=running_candidate_cash,
            existing_feed_cash_hold=existing_res.existing_feed_cash_hold,
            candidate_feed_cash_hold=0.0,
            scheduled_market_purchases=cand_scheduled_buys,
            daily_timeline=daily_timeline,
            execution_confidence=exec_conf,
        )

    # Lifetime feeding beyond operational horizon for candidate
    last_op_day = operational_days[-1] if operational_days else day - 1
    cand_lifetime_days_beyond = max(0, ANIMAL_FEED_CUTOFF_DAY - (last_op_day + 1))
    cand_lifetime_units = cand_lifetime_days_beyond * 1
    cand_lifetime_cost = float(cand_lifetime_units * shadow.wheat_price_current)

    cand_near_term_market_cost = sum(b["cost"] for b in cand_scheduled_buys)
    total_cand_feed_cash_required = cand_near_term_market_cost + cand_lifetime_cost

    cand_near_term_feed_units = sum(1 for d in operational_days if d > day)

    if total_cand_feed_cash_required > cash_after_purchase:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=True,
            candidate_species=candidate_species,
            blocking_day=last_op_day + 1,
            blocking_reason="insufficient_cash",
            near_term_feed_units=cand_near_term_feed_units,
            near_term_market_wheat_required=cand_cumulative_market_purchased,
            remaining_lifetime_feed_units=cand_lifetime_units,
            remaining_feed_cash_required=cand_lifetime_cost,
            existing_feed_cash_hold=existing_res.existing_feed_cash_hold,
            candidate_feed_cash_hold=total_cand_feed_cash_required,
            minimum_wheat_slack=min_wheat_slack,
            minimum_cash_slack=cash_after_purchase - total_cand_feed_cash_required,
            scheduled_market_purchases=cand_scheduled_buys,
            daily_timeline=daily_timeline,
            execution_confidence=exec_conf,
        )

    min_cash_slack = cash_after_purchase - total_cand_feed_cash_required

    return FeedFeasibilityResult(
        feasible=True,
        existing_herd_feasible=True,
        candidate_species=candidate_species,
        near_term_feed_units=cand_near_term_feed_units,
        near_term_market_wheat_required=cand_cumulative_market_purchased,
        remaining_lifetime_feed_units=cand_lifetime_units,
        remaining_feed_cash_required=cand_lifetime_cost,
        existing_feed_cash_hold=existing_res.existing_feed_cash_hold,
        candidate_feed_cash_hold=total_cand_feed_cash_required,
        minimum_wheat_slack=min_wheat_slack,
        minimum_cash_slack=min_cash_slack,
        scheduled_market_purchases=cand_scheduled_buys,
        daily_timeline=daily_timeline,
        execution_confidence=exec_conf,
        diagnostics={
            "purchase_cost": purchase_cost,
            "cand_near_term_market_cost": cand_near_term_market_cost,
            "cand_lifetime_cost": cand_lifetime_cost,
        },
    )


# ============================================================================
# Sequential Candidate Reservation
# ============================================================================

def commit_candidate_reservation(
    ledger: FeedResourceLedger,
    candidate_species_or_result: Any,
    result: Optional[FeedFeasibilityResult] = None,
    purchase_cost: Optional[float] = None,
) -> None:
    """Commit an admitted candidate animal's reservations into the ledger.

    Mutates the ledger so the next candidate evaluates against residual resources:
      - Does NOT add species to placed_herd (avoids double-counting and same-day feed requirement).
      - Tracks candidate in candidate_reservations.
      - Deducts purchase cost from candidate purchasing power.
      - Reserves candidate feed cash hold in candidate_feed_cash_hold.
      - Appends scheduled market purchases.
    """
    if isinstance(candidate_species_or_result, FeedFeasibilityResult):
        result = candidate_species_or_result
        candidate_species = result.candidate_species or "UNKNOWN"
    else:
        candidate_species = str(candidate_species_or_result)

    if result is None:
        raise ValueError("FeedFeasibilityResult must be provided to commit_candidate_reservation")

    if purchase_cost is None:
        purchase_cost = float(ANIMALS.get(candidate_species, {}).get("cost", 0.0))

    # Distinct semantic holds: committed candidate feed liability belongs to candidate_feed_cash_hold
    ledger.candidate_purchase_cash_spent += float(purchase_cost)
    ledger.candidate_feed_cash_hold += float(result.candidate_feed_cash_hold)
    ledger.scheduled_market_purchases.extend(result.scheduled_market_purchases)

    reservation_record = {
        "species": candidate_species,
        "purchase_cost": purchase_cost,
        "candidate_feed_cash_hold": result.candidate_feed_cash_hold,
        "near_term_market_wheat_required": result.near_term_market_wheat_required,
        "remaining_lifetime_feed_units": result.remaining_lifetime_feed_units,
        "scheduled_market_purchases": copy.deepcopy(result.scheduled_market_purchases),
    }
    ledger.candidate_reservations.append(reservation_record)
