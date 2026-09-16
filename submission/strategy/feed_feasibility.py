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
        WHEAT_BUY_PRICE_BUFFER,
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
    WHEAT_BUY_PRICE_BUFFER = 1.10

    def get_point2_feed_mode() -> str:
        return "shadow"

try:
    from market.price_math import estimate_wheat_buy_price, market_price
except ImportError:
    try:
        from price_math import estimate_wheat_buy_price, market_price
    except ImportError:
        def estimate_wheat_buy_price(market_or_ctx=None, default_price=25.0) -> float:
            return float(math.ceil(default_price * 1.1))

        def market_price(item: str, inventory: float) -> float:
            return 25.0


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
    # Phase C2A execution verification & diagnostics
    unfed_placed_today: int = 0
    verified_feed_targets: List[Tuple[int, int]] = field(default_factory=list)
    verified_feed_count: int = 0
    feed_assignments: int = 0
    feed_actions_emitted: int = 0
    actual_place_actions: int = 0
    actual_pickups: int = 0
    actual_drops: int = 0
    post_unit_worker_inventory: int = 0
    post_unit_shed_delta: int = 0
    snapshot_valid: bool = True
    is_live_livestock_safe: bool = True
    live_execution_status: str = "safe"  # "safe" or "feed_execution_unverified"
    live_execution_reason: str = ""
    # Phase C2B post-unit / pre-market state
    post_unit_shed_inventory: Dict[str, int] = field(default_factory=dict)
    post_unit_worker_inventories: List[Dict[str, int]] = field(default_factory=list)
    post_unit_shed_occupancy: int = 0
    post_unit_worker_inventory_total: int = 0
    post_unit_total_storable_inventory: int = 0
    post_unit_empty_pastures: int = 0
    post_unit_empty_coops: int = 0
    post_unit_unplaced_pasture_animals: int = 0
    post_unit_unplaced_coop_animals: int = 0
    post_unit_placed_herd: Dict[str, int] = field(default_factory=dict)
    post_unit_state_verified: bool = True
    post_unit_state_reason: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LiveHousingState:
    """One shared live housing authority tracking residual structure claims."""
    empty_pastures: int
    empty_coops: int
    existing_unplaced_pasture_claims: int = 0
    existing_unplaced_coop_claims: int = 0
    accepted_candidate_pasture_claims: int = 0
    accepted_candidate_coop_claims: int = 0

    def residual_pastures(self) -> int:
        return max(0, self.empty_pastures - self.existing_unplaced_pasture_claims - self.accepted_candidate_pasture_claims)

    def residual_coops(self) -> int:
        return max(0, self.empty_coops - self.existing_unplaced_coop_claims - self.accepted_candidate_coop_claims)

    def can_house(self, species: str) -> bool:
        if species in ("COW", "SHEEP"):
            return self.residual_pastures() > 0
        elif species == "GOOSE":
            return self.residual_coops() > 0
        return False

    def reserve(self, species: str) -> None:
        if species in ("COW", "SHEEP"):
            self.accepted_candidate_pasture_claims += 1
        elif species == "GOOSE":
            self.accepted_candidate_coop_claims += 1

    def clone(self) -> "LiveHousingState":
        s = LiveHousingState(
            empty_pastures=self.empty_pastures,
            empty_coops=self.empty_coops,
            existing_unplaced_pasture_claims=self.existing_unplaced_pasture_claims,
            existing_unplaced_coop_claims=self.existing_unplaced_coop_claims,
            accepted_candidate_pasture_claims=self.accepted_candidate_pasture_claims,
            accepted_candidate_coop_claims=self.accepted_candidate_coop_claims,
        )
        return s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "empty_pastures": self.empty_pastures,
            "empty_coops": self.empty_coops,
            "existing_unplaced_pasture_claims": self.existing_unplaced_pasture_claims,
            "existing_unplaced_coop_claims": self.existing_unplaced_coop_claims,
            "accepted_candidate_pasture_claims": self.accepted_candidate_pasture_claims,
            "accepted_candidate_coop_claims": self.accepted_candidate_coop_claims,
            "residual_pastures": self.residual_pastures(),
            "residual_coops": self.residual_coops(),
        }


def build_live_housing_state(
    execution_snapshot: Optional[FeedExecutionSnapshot] = None,
    farm: Any = None,
    private: Any = None,
    day: int = 0,
) -> LiveHousingState:
    """Build a LiveHousingState instance from verified snapshot or observation."""
    if execution_snapshot is not None:
        return LiveHousingState(
            empty_pastures=int(getattr(execution_snapshot, "post_unit_empty_pastures", 0)),
            empty_coops=int(getattr(execution_snapshot, "post_unit_empty_coops", 0)),
            existing_unplaced_pasture_claims=int(getattr(execution_snapshot, "post_unit_unplaced_pasture_animals", 0)),
            existing_unplaced_coop_claims=int(getattr(execution_snapshot, "post_unit_unplaced_coop_animals", 0)),
        )

    empty_pastures = 0
    empty_coops = 0
    if farm and hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if t is None or t == "LOCKED":
                continue
            is_anim = getattr(t, "is_animal", False) if not isinstance(t, dict) else t.get("is_animal", False)
            if not is_anim:
                k = getattr(t, "kind", "") if not isinstance(t, dict) else t.get("kind", "")
                pos = getattr(t, "pos", None) if not isinstance(t, dict) else t.get("pos")
                if pos and hasattr(farm, "unlocked") and hasattr(farm, "quadrant_of"):
                    if farm.quadrant_of(pos) not in farm.unlocked:
                        continue
                if k == "PASTURE":
                    empty_pastures += 1
                elif k == "COOP":
                    empty_coops += 1

    shed = getattr(private, "shed", {}) if private else {}
    workers = getattr(farm, "workers", []) if farm else []
    unplaced_pasture = int(shed.get("COW", 0)) + int(shed.get("SHEEP", 0))
    unplaced_coop = int(shed.get("GOOSE", 0))
    for w in workers:
        w_inv = getattr(w, "inventory", {}) if not isinstance(w, dict) else w.get("inventory", {})
        if isinstance(w_inv, dict):
            unplaced_pasture += int(w_inv.get("COW", 0)) + int(w_inv.get("SHEEP", 0))
            unplaced_coop += int(w_inv.get("GOOSE", 0))

    return LiveHousingState(
        empty_pastures=empty_pastures,
        empty_coops=empty_coops,
        existing_unplaced_pasture_claims=unplaced_pasture,
        existing_unplaced_coop_claims=unplaced_coop,
    )


WHEAT_CONSUMING_SHOPS = {
    "BAKERY",
    "PIZZA_SHOP",
    "BRUNCH_SPOT",
    "ICE_CREAM_SHOP",
    "FARMERS_MARKET",
}


def compute_worst_case_remaining_town_wheat_drain(
    day: int,
    hour: int,
    active_shops: Optional[List[str]] = None,
) -> int:
    """Project engine-exact worst-case town WHEAT consumption for remaining season.

    Engine rules:
      - Active shops consume WHEAT every 4 steps (step % 4 == 0).
      - Town center consumes 1 WHEAT every 24 steps (step % 24 == 0).
      - Shop unlock occurs at end of day: (s + 1) % 24 == 0, if ((s // 24) + 1) % 3 == 0,
        up to 8 total unlock events across the season.
      - If active_shops is passed: known wheat-consuming shops are used; future unlocks
        are pessimistically assumed to be wheat-consuming shops.
      - If active_shops is None: unlocks up to current day are assumed to have been wheat shops,
        ensuring monotonic non-increasing drain across all 720 steps.
    """
    current_step = day * 24 + hour
    if current_step >= 720:
        return 0

    if active_shops is not None:
        known_wheat_shops = sum(1 for s in active_shops if s in WHEAT_CONSUMING_SHOPS)
        total_unlocked = len(active_shops)
    else:
        total_unlocked = min(8, day // 3)
        known_wheat_shops = total_unlocked

    active_wheat_shops = known_wheat_shops
    total_drain = 0

    for s in range(current_step, 720):
        if s % 4 == 0:
            total_drain += active_wheat_shops
        if s % 24 == 0:
            total_drain += 1
        if (s + 1) % 24 == 0:
            d = s // 24
            if (d + 1) % 3 == 0 and total_unlocked < 8:
                total_unlocked += 1
                active_wheat_shops += 1

    return total_drain


def compute_observed_opponent_feed_liability(
    opponent_farm: Any,
    day: int,
) -> int:
    """Calculate remaining lifetime feeding liability of observed opponent animals.

    Placed animals on the opponent's farm consume 1 wheat per day through Day 28.
    """
    placed_count = 0
    if opponent_farm is not None:
        if hasattr(opponent_farm, "iter_tiles"):
            for t in opponent_farm.iter_tiles():
                if t is not None and getattr(t, "is_animal", False):
                    placed_count += 1
        elif isinstance(opponent_farm, dict) and "tiles" in opponent_farm:
            tiles = opponent_farm.get("tiles")
            if isinstance(tiles, list):
                for row_or_tile in tiles:
                    if isinstance(row_or_tile, list):
                        for t in row_or_tile:
                            if isinstance(t, dict) and (t.get("is_animal") or t.get("kind") in ("COW", "SHEEP", "GOOSE")):
                                placed_count += 1
                    elif isinstance(row_or_tile, dict) and (row_or_tile.get("is_animal") or row_or_tile.get("kind") in ("COW", "SHEEP", "GOOSE")):
                        placed_count += 1
        elif hasattr(opponent_farm, "animals"):
            placed_count = len(opponent_farm.animals)
        elif isinstance(opponent_farm, dict) and "animals" in opponent_farm:
            placed_count = len(opponent_farm["animals"])

    remaining_feed_days = max(0, 29 - day)
    return placed_count * remaining_feed_days


def compute_engine_stress_wheat_price(
    current_market_wheat_inventory: float,
    worst_case_town_drain: int,
    our_committed_future_market_feed_requirement: int,
    opponent_feed_liability: int,
    executable_buffered_price: float,
) -> Tuple[float, Dict[str, Any]]:
    """Derive lifetime stress wheat price under engine_stress_bound_v1.

    No lower clamp on stressed_wheat_inventory (negative inventory produces valid scarcity pricing).
    """
    opponent_allowance = max(opponent_feed_liability, our_committed_future_market_feed_requirement)
    stressed_wheat_inventory = (
        float(current_market_wheat_inventory)
        - float(worst_case_town_drain)
        - float(our_committed_future_market_feed_requirement)
        - float(opponent_allowance)
    )
    stress_raw_price = market_price("WHEAT", stressed_wheat_inventory)
    stress_buffered_price = float(math.ceil(stress_raw_price * WHEAT_BUY_PRICE_BUFFER))
    lifetime_wheat_price = max(float(executable_buffered_price), stress_buffered_price)

    diagnostics = {
        "current_market_wheat_inventory": float(current_market_wheat_inventory),
        "worst_case_town_drain": int(worst_case_town_drain),
        "our_committed_future_market_feed_requirement": int(our_committed_future_market_feed_requirement),
        "opponent_feed_liability": int(opponent_feed_liability),
        "opponent_allowance": int(opponent_allowance),
        "stressed_wheat_inventory": float(stressed_wheat_inventory),
        "stress_raw_price": float(stress_raw_price),
        "stress_buffered_price": float(stress_buffered_price),
        "executable_buffered_price": float(executable_buffered_price),
        "lifetime_wheat_price": float(lifetime_wheat_price),
        "policy": "engine_stress_bound_v1",
    }
    return lifetime_wheat_price, diagnostics


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
    candidate_storage_slots_reserved: int = 0

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

    wheat_market_inventory: float = 10000.0
    town_wheat_drain: int = 0
    opponent_feed_liability: int = 0
    lifetime_wheat_price: float = 28.0
    stressed_wheat_inventory: float = 10000.0
    stress_raw_price: float = 25.0
    stress_buffered_price: float = 28.0

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
            candidate_storage_slots_reserved=self.candidate_storage_slots_reserved,
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
            wheat_market_inventory=self.wheat_market_inventory,
            town_wheat_drain=self.town_wheat_drain,
            opponent_feed_liability=self.opponent_feed_liability,
            lifetime_wheat_price=self.lifetime_wheat_price,
            stressed_wheat_inventory=self.stressed_wheat_inventory,
            stress_raw_price=self.stress_raw_price,
            stress_buffered_price=self.stress_buffered_price,
        )

    def get_feed_hold_diagnostics(self) -> Dict[str, float]:
        """Expose structured feed hold diagnostics separating existing herd hold from candidate holds."""
        return {
            "existing_feed_cash_hold": float(self.existing_feed_cash_hold),
            "candidate_feed_cash_hold": float(self.candidate_feed_cash_hold),
            "remaining_existing_feed_hold": float(self.existing_feed_cash_hold),
            "candidate_feed_holds_total": float(self.candidate_feed_cash_hold),
        }

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
            "remaining_existing_feed_hold": self.existing_feed_cash_hold,
            "candidate_feed_holds_total": self.candidate_feed_cash_hold,
            "feed_hold_diagnostics": self.get_feed_hold_diagnostics(),
            "candidate_purchase_cash_spent": self.candidate_purchase_cash_spent,
            "candidate_storage_slots_reserved": self.candidate_storage_slots_reserved,
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
            "wheat_market_inventory": self.wheat_market_inventory,
            "town_wheat_drain": self.town_wheat_drain,
            "opponent_feed_liability": self.opponent_feed_liability,
            "lifetime_wheat_price": self.lifetime_wheat_price,
            "stressed_wheat_inventory": self.stressed_wheat_inventory,
            "stress_raw_price": self.stress_raw_price,
            "stress_buffered_price": self.stress_buffered_price,
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
    actions: Any = None,
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
      - Moving toward an animal emits movement (not FEED) and is not certified feeding.
    """
    day = int(ctx.get("day", 0)) if isinstance(ctx, dict) else int(getattr(ctx, "day", 0))
    hour = int(ctx.get("hour", 0)) if isinstance(ctx, dict) else int(getattr(ctx, "hour", 0))
    turns_remaining = max(0, 24 - hour)

    farm = ctx.get("farm") if isinstance(ctx, dict) else getattr(ctx, "farm", None)
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

    if assignment is None and isinstance(ctx, dict):
        assignment = ctx.get("assignment")
    if actions is None and isinstance(ctx, dict):
        actions = ctx.get("actions")
    if tasks is None and isinstance(ctx, dict):
        tasks = ctx.get("tasks")

    # Unpack assignment and actions
    asg_map = {}
    actions_map = {}
    if assignment is not None:
        if isinstance(assignment, dict):
            if "assignment" in assignment and isinstance(assignment["assignment"], dict):
                asg_map = assignment["assignment"]
            else:
                asg_map = assignment
            if actions is None and "actions" in assignment and isinstance(assignment["actions"], dict):
                actions_map = assignment["actions"]

    if actions is not None:
        if isinstance(actions, dict):
            actions_map = actions
        elif isinstance(actions, (list, tuple)):
            actions_map = {i: act for i, act in enumerate(actions)}

    feeds_assigned = 0
    wheat_pickups_assigned = 0
    for task in asg_map.values():
        if not isinstance(task, dict):
            continue
        op = task.get("op")
        kind = task.get("kind", "")
        args = task.get("args") or []

        if op == "FEED" or (isinstance(kind, str) and kind.startswith("feed")):
            feeds_assigned += 1
        elif op == "PICKUP":
            if (args and args[0] == "WHEAT") or ("wheat" in kind if isinstance(kind, str) else False):
                wheat_pickups_assigned += 1

    # Extract actions telemetry
    feed_actions_emitted = 0
    actual_place_actions = 0
    actual_pickups = 0
    actual_drops = 0
    for act in actions_map.values():
        if not act or not isinstance(act, (list, tuple)):
            continue
        op_act = act[0] if len(act) > 0 else "PASS"
        if op_act == "FEED":
            feed_actions_emitted += 1
        elif op_act == "PLACE":
            actual_place_actions += 1
        elif op_act == "PICKUP":
            actual_pickups += 1
        elif op_act == "DROP":
            actual_drops += 1

    # Find unfed placed animals and their target positions
    unfed_placed_positions: List[Tuple[int, int]] = []
    if farm is not None and hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if t is not None and getattr(t, "is_animal", False):
                if not getattr(t, "fed_today", False):
                    p = getattr(t, "pos", None)
                    if p is not None:
                        unfed_placed_positions.append(tuple(p))
    elif farm is not None and isinstance(farm, dict) and "tiles" in farm:
        tiles = farm.get("tiles")
        if isinstance(tiles, list):
            for row in tiles:
                if isinstance(row, list):
                    for t in row:
                        if isinstance(t, dict) and (t.get("is_animal") or t.get("kind") in ("COW", "SHEEP", "GOOSE")):
                            if not t.get("fed_today", False):
                                unfed_placed_positions.append(tuple(t.get("pos", (0, 0))))

    feeds_due_today = len(unfed_placed_positions)
    if feeds_due_today == 0 and tasks and isinstance(tasks, list):
        for t in tasks:
            if isinstance(t, dict):
                if t.get("op") == "FEED" or str(t.get("kind", "")).startswith("feed"):
                    feeds_due_today += 1
                    tgt = t.get("target")
                    if tgt is not None:
                        unfed_placed_positions.append(tuple(tgt))

    unfed_placed_today = feeds_due_today

    # Verify feeds: exact-target matching only, distinct units
    verified_feed_targets: List[Tuple[int, int]] = []
    targets_remaining = list(unfed_placed_positions)
    for u_idx, act in actions_map.items():
        if act and isinstance(act, (list, tuple)) and len(act) > 0 and act[0] == "FEED":
            u_task = asg_map.get(u_idx) if isinstance(asg_map, dict) else None
            tgt = None
            if isinstance(u_task, dict) and (u_task.get("op") == "FEED" or u_task.get("task") == "FEED" or str(u_task.get("kind", "")).startswith("feed")) and u_task.get("target") is not None:
                tgt = tuple(u_task["target"])
            if tgt is not None and tgt in targets_remaining:
                targets_remaining.remove(tgt)
                verified_feed_targets.append(tgt)

    verified_feed_count = len(verified_feed_targets)
    market_purchase_can_help_today = (hour < 23)

    confidence = "high"
    if tasks is None and assignment is None and actions is None:
        confidence = "guarded"
    elif hour >= 23 and (unfed_placed_today > verified_feed_count if actions_map else feeds_due_today > feeds_assigned):
        confidence = "conditional"
    elif hour >= 22 and (unfed_placed_today > (verified_feed_count + worker_wheat) if actions_map else feeds_due_today > (feeds_assigned + worker_wheat)):
        confidence = "guarded"
    elif hour >= 20 and (unfed_placed_today > (verified_feed_count + worker_wheat) if actions_map else feeds_due_today > (feeds_assigned + worker_wheat)):
        confidence = "guarded"
    elif unfed_placed_today > 0 and actions_map and verified_feed_count < unfed_placed_today:
        confidence = "guarded"

    # Derive live execution status and safety
    if unfed_placed_today > 0:
        if hour >= 23 and verified_feed_count < unfed_placed_today:
            is_live_livestock_safe = False
            live_execution_status = "feed_execution_unverified"
            live_execution_reason = "Hour 23 unresolved feed cannot be rescued by market wheat"
        elif confidence != "high":
            is_live_livestock_safe = False
            live_execution_status = "feed_execution_unverified"
            live_execution_reason = f"Execution confidence is {confidence}"
        elif verified_feed_count < unfed_placed_today:
            is_live_livestock_safe = False
            live_execution_status = "feed_execution_unverified"
            live_execution_reason = f"Verified feed count {verified_feed_count} < unfed placed {unfed_placed_today}"
        else:
            is_live_livestock_safe = True
            live_execution_status = "safe"
            live_execution_reason = "All unfed placed animals have verified FEED actions"
    else:
        # All placed animals already fed today
        is_live_livestock_safe = True
        live_execution_status = "safe"
        live_execution_reason = "All placed animals already fed today"

    # -------------------------------------------------------------
    # Post-Unit State Simulation (Phase C2B)
    # -------------------------------------------------------------
    post_unit_shed: Dict[str, int] = {}
    if private is not None:
        if hasattr(private, "shed") and isinstance(private.shed, dict):
            post_unit_shed = {str(k): int(v) for k, v in private.shed.items()}
        elif isinstance(private, dict) and "shed" in private and isinstance(private["shed"], dict):
            post_unit_shed = {str(k): int(v) for k, v in private["shed"].items()}

    post_unit_workers: List[Dict[str, int]] = []
    if private is not None:
        raw_invs = getattr(private, "inventories", None) or (private.get("inventories") if isinstance(private, dict) else None)
        if raw_invs and isinstance(raw_invs, list):
            for inv in raw_invs:
                if isinstance(inv, dict):
                    post_unit_workers.append({str(k): int(v) for k, v in inv.items()})
                else:
                    post_unit_workers.append({})
    if (not post_unit_workers or all(len(inv) == 0 for inv in post_unit_workers)) and farm and hasattr(farm, "workers"):
        post_unit_workers = []
        for w in farm.workers:
            w_inv = getattr(w, "inventory", None) or (w.get("inventory") if isinstance(w, dict) else {})
            if isinstance(w_inv, dict):
                post_unit_workers.append({str(k): int(v) for k, v in w_inv.items()})
            else:
                post_unit_workers.append({})
    while len(post_unit_workers) < n_active_units:
        post_unit_workers.append({})

    # Observed structures & placed animals
    empty_pastures = 0
    empty_coops = 0
    sim_placed_herd = {a: 0 for a in ("COW", "SHEEP", "GOOSE")}
    if farm is not None and hasattr(farm, "iter_tiles"):
        for t in farm.iter_tiles():
            if t is None or t == "LOCKED":
                continue
            is_anim = getattr(t, "is_animal", False)
            k = getattr(t, "kind", "")
            if is_anim:
                species = getattr(t, "animal", None)
                if species in sim_placed_herd:
                    sim_placed_herd[species] += 1
            elif k == "PASTURE":
                pos = getattr(t, "pos", None)
                if pos and hasattr(farm, "unlocked") and hasattr(farm, "quadrant_of"):
                    if farm.quadrant_of(pos) in farm.unlocked:
                        empty_pastures += 1
                else:
                    empty_pastures += 1
            elif k == "COOP":
                pos = getattr(t, "pos", None)
                if pos and hasattr(farm, "unlocked") and hasattr(farm, "quadrant_of"):
                    if farm.quadrant_of(pos) in farm.unlocked:
                        empty_coops += 1
                else:
                    empty_coops += 1
    elif farm is not None and isinstance(farm, dict) and "tiles" in farm:
        tiles = farm.get("tiles")
        if isinstance(tiles, list):
            for row in tiles:
                if isinstance(row, list):
                    for t in row:
                        if isinstance(t, dict):
                            is_anim = t.get("is_animal", False)
                            k = t.get("kind", "")
                            if is_anim:
                                sp = t.get("animal", "")
                                if sp in sim_placed_herd:
                                    sim_placed_herd[sp] += 1
                            elif k == "PASTURE":
                                empty_pastures += 1
                            elif k == "COOP":
                                empty_coops += 1

    post_unit_verified = True
    post_unit_reason = "ok"

    for u_idx, act in actions_map.items():
        if not act or not isinstance(act, (list, tuple)):
            continue
        op_act = act[0]
        u_task = asg_map.get(u_idx) if isinstance(asg_map, dict) else None
        task_args = u_task.get("args", []) if isinstance(u_task, dict) else []
        act_args = act[1:] if len(act) > 1 else task_args
        u_inv = post_unit_workers[u_idx] if u_idx < len(post_unit_workers) else None

        if op_act == "FEED":
            tgt = tuple(u_task.get("target")) if (isinstance(u_task, dict) and u_task.get("target") is not None) else None
            if tgt in verified_feed_targets:
                if u_inv is not None and u_inv.get("WHEAT", 0) > 0:
                    u_inv["WHEAT"] -= 1

        elif op_act == "PLACE":
            animal_to_place = None
            if act_args and act_args[0] in ("COW", "SHEEP", "GOOSE"):
                animal_to_place = act_args[0]
            elif task_args and task_args[0] in ("COW", "SHEEP", "GOOSE"):
                animal_to_place = task_args[0]
            elif u_inv:
                for a in ("COW", "SHEEP", "GOOSE"):
                    if u_inv.get(a, 0) > 0:
                        animal_to_place = a
                        break

            if animal_to_place:
                if u_inv and u_inv.get(animal_to_place, 0) > 0:
                    u_inv[animal_to_place] -= 1
                sim_placed_herd[animal_to_place] = sim_placed_herd.get(animal_to_place, 0) + 1
                struct = ANIMALS[animal_to_place]["structure"] if animal_to_place in ANIMALS else "PASTURE"
                if struct == "PASTURE":
                    empty_pastures = max(0, empty_pastures - 1)
                elif struct == "COOP":
                    empty_coops = max(0, empty_coops - 1)

        elif op_act == "BUILD_PASTURE":
            if day < 12:
                empty_pastures += 1

        elif op_act == "BUILD_COOP":
            if day < 12:
                empty_coops += 1

        elif op_act == "PICKUP":
            item = act_args[0] if act_args else (task_args[0] if task_args else None)
            qty = int(act_args[1]) if len(act_args) > 1 else (int(task_args[1]) if len(task_args) > 1 else 1)
            if item:
                post_unit_shed[item] = max(0, post_unit_shed.get(item, 0) - qty)
                if u_inv is not None:
                    u_inv[item] = u_inv.get(item, 0) + qty

        elif op_act == "DROP":
            item = act_args[0] if act_args else (task_args[0] if task_args else None)
            qty = int(act_args[1]) if len(act_args) > 1 else (int(task_args[1]) if len(task_args) > 1 else 1)
            if item and u_inv is not None:
                u_inv[item] = max(0, u_inv.get(item, 0) - qty)
                post_unit_shed[item] = post_unit_shed.get(item, 0) + qty

        elif op_act == "FERTILIZE":
            if u_inv is not None and u_inv.get("FERTILIZER", 0) > 0:
                u_inv["FERTILIZER"] -= 1

        elif op_act == "COLLECT_FERTILIZER":
            if u_inv is not None:
                u_inv["FERTILIZER"] = u_inv.get("FERTILIZER", 0) + 1

        elif op_act == "HARVEST":
            crop = act_args[0] if act_args else (task_args[0] if task_args else None)
            if crop and u_inv is not None:
                u_inv[crop] = u_inv.get(crop, 0) + 1

    post_unit_shed_occupancy = sum(qty for qty in post_unit_shed.values() if qty > 0)
    post_unit_worker_inventory_total = sum(sum(qty for qty in inv.values() if qty > 0) for inv in post_unit_workers)
    post_unit_total_storable_inventory = post_unit_shed_occupancy + post_unit_worker_inventory_total

    unplaced_cow_sheep = (
        post_unit_shed.get("COW", 0) + post_unit_shed.get("SHEEP", 0) +
        sum(inv.get("COW", 0) + inv.get("SHEEP", 0) for inv in post_unit_workers)
    )
    unplaced_goose = (
        post_unit_shed.get("GOOSE", 0) +
        sum(inv.get("GOOSE", 0) for inv in post_unit_workers)
    )

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
        unfed_placed_today=unfed_placed_today,
        verified_feed_targets=verified_feed_targets,
        verified_feed_count=verified_feed_count,
        feed_assignments=feeds_assigned,
        feed_actions_emitted=feed_actions_emitted,
        actual_place_actions=actual_place_actions,
        actual_pickups=actual_pickups,
        actual_drops=actual_drops,
        is_live_livestock_safe=is_live_livestock_safe,
        live_execution_status=live_execution_status,
        live_execution_reason=live_execution_reason,
        post_unit_shed_inventory=post_unit_shed,
        post_unit_worker_inventories=post_unit_workers,
        post_unit_shed_occupancy=post_unit_shed_occupancy,
        post_unit_worker_inventory_total=post_unit_worker_inventory_total,
        post_unit_total_storable_inventory=post_unit_total_storable_inventory,
        post_unit_empty_pastures=empty_pastures,
        post_unit_empty_coops=empty_coops,
        post_unit_unplaced_pasture_animals=unplaced_cow_sheep,
        post_unit_unplaced_coop_animals=unplaced_goose,
        post_unit_placed_herd=sim_placed_herd,
        post_unit_state_verified=post_unit_verified,
        post_unit_state_reason=post_unit_reason,
    )


def check_live_livestock_execution_safety(
    snapshot: Optional[FeedExecutionSnapshot],
    unfed_placed_today: int = 0,
) -> Tuple[bool, str, str]:
    """Evaluate live execution safety rule for live BUY_ANIMAL authority.

    Returns:
      (is_safe, live_execution_status, live_execution_reason)
    """
    if unfed_placed_today > 0:
        if snapshot is None:
            return False, "feed_execution_unverified", "Missing execution snapshot with unfed placed animals"
        if not snapshot.is_live_livestock_safe:
            return False, snapshot.live_execution_status, snapshot.live_execution_reason
        if snapshot.execution_confidence != "high":
            return False, "feed_execution_unverified", f"Execution confidence is {snapshot.execution_confidence}"
        if snapshot.verified_feed_count < unfed_placed_today:
            return False, "feed_execution_unverified", f"Verified feed count {snapshot.verified_feed_count} < unfed placed {unfed_placed_today}"
    return True, "safe", "Herd feed execution verified or already fed"


def build_fresh_live_ledger(
    ctx: Any,
    hard_cash_hold: float = 0.0,
    strategic_cash_hold: float = 0.0,
    execution_snapshot: Optional[FeedExecutionSnapshot] = None,
    market_inventory: Optional[Dict[str, float]] = None,
    town_shops: Optional[List[str]] = None,
    opponent_farm: Any = None,
) -> FeedResourceLedger:
    """Constructs a fresh FeedResourceLedger for live market authorization.

    In live mode:
      - Lifetime pricing uses engine_stress_bound_v1.
      - Current wheat price uses estimate_wheat_buy_price(ctx).
      - Attaches the verified FeedExecutionSnapshot.
      - Built purely from observed state; does NOT import Macro candidate reservations.
    """
    return build_feed_resource_ledger(
        ctx=ctx,
        current_herd=None,  # Purely observed from ctx
        hard_cash_hold=hard_cash_hold,
        strategic_cash_hold=strategic_cash_hold,
        execution_snapshot=execution_snapshot,
        lifetime_price_policy="engine_stress_bound_v1",
        market_inventory=market_inventory,
        town_shops=town_shops,
        opponent_farm=opponent_farm,
    )


def compute_remaining_existing_feed_hold(
    ledger: FeedResourceLedger,
    retained_wheat: int = 0,
    unit_price: float = 0.0,
) -> Tuple[bool, FeedFeasibilityResult, float]:
    """Compute existing-herd feasibility and remaining future feed cash hold.

    When retained_wheat > 0 is scheduled/retained on the current turn:
      - The physical wheat is added to trial ledger scheduled purchases on day.
      - Cash available for future feed is reduced by the current turn spending (retained_wheat * unit_price).
      - Future feed liability is recomputed on the remaining deficit.
      - Anti-double-counting invariant preserved:
        retained_spending + remaining_existing_feed_hold reflects the total required feed budget.
    """
    trial_ledger = ledger.clone()
    if retained_wheat > 0:
        cost = float(retained_wheat * unit_price)
        trial_ledger.scheduled_market_purchases.append({
            "day": trial_ledger.day,
            "units": retained_wheat,
            "cost": cost,
            "purpose": "retained_protected_wheat",
        })
        trial_ledger.observed_cash = max(0.0, trial_ledger.observed_cash - cost)

    ok, res = evaluate_existing_herd_feasibility(trial_ledger)
    remaining_hold = float(res.existing_feed_cash_hold) if hasattr(res, "existing_feed_cash_hold") else 0.0
    return ok, res, remaining_hold


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
    lifetime_price_policy: str = "conditional_current_buffered_price",
    market_inventory: Optional[Dict[str, float]] = None,
    town_shops: Optional[List[str]] = None,
    opponent_farm: Any = None,
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

    placed_herd: Dict[str, int] = {a: 0 for a in ANIMAL_LIST}
    owned_unplaced_herd: Dict[str, int] = {a: 0 for a in ANIMAL_LIST}
    unfed_placed_today = 0

    if current_herd is None and execution_snapshot is not None and getattr(execution_snapshot, "post_unit_shed_inventory", None):
        wheat_in_shed = int(execution_snapshot.post_unit_shed_inventory.get("WHEAT", 0))
        wheat_on_workers = sum(int(inv.get("WHEAT", 0)) for inv in execution_snapshot.post_unit_worker_inventories if isinstance(inv, dict))
        shed_other_units = sum(int(v) for k, v in execution_snapshot.post_unit_shed_inventory.items() if k != "WHEAT")
        for a in ANIMAL_LIST:
            placed_herd[a] = int(execution_snapshot.post_unit_placed_herd.get(a, 0))
            owned_unplaced_herd[a] = int(execution_snapshot.post_unit_shed_inventory.get(a, 0)) + sum(int(inv.get(a, 0)) for inv in execution_snapshot.post_unit_worker_inventories if isinstance(inv, dict))
        unfed_placed_today = max(0, execution_snapshot.unfed_placed_today - execution_snapshot.verified_feed_count)
    else:
        wheat_in_shed = int(shed.get("WHEAT", 0))
        wheat_on_workers = sum(int(inv.get("WHEAT", 0)) for inv in inventories if isinstance(inv, dict))
        shed_other_units = sum(int(v) for k, v in shed.items() if k != "WHEAT")

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

    if market_inventory is None and ctx is not None:
        m = ctx.get("market") if isinstance(ctx, dict) else getattr(ctx, "market", None)
        if m is not None:
            if isinstance(m, dict):
                market_inventory = m.get("inventory")
            elif hasattr(m, "inventory"):
                market_inventory = m.inventory

    if town_shops is None and ctx is not None:
        if isinstance(ctx, dict):
            town_shops = ctx.get("town_shops")
        else:
            town_shops = getattr(ctx, "town_shops", None)

    if opponent_farm is None and ctx is not None:
        if isinstance(ctx, dict):
            opponent_farm = ctx.get("opponent_farm")
        else:
            opponent_farm = getattr(ctx, "opponent_farm", None)

    wheat_market_inv = float(market_inventory.get("WHEAT", 10000.0)) if market_inventory else 10000.0
    town_drain = compute_worst_case_remaining_town_wheat_drain(day, hour, town_shops)
    opp_liability = compute_observed_opponent_feed_liability(opponent_farm, day)

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
        candidate_storage_slots_reserved=0,
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
        lifetime_price_policy=lifetime_price_policy,
        unplaced_timing_assumption="future_funding_liability_not_eating_today",
        wheat_market_inventory=wheat_market_inv,
        town_wheat_drain=town_drain,
        opponent_feed_liability=opp_liability,
        lifetime_wheat_price=wheat_price,
        stressed_wheat_inventory=wheat_market_inv,
        stress_raw_price=25.0,
        stress_buffered_price=wheat_price,
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

    existing_scheduled_by_day: Dict[int, int] = {}
    for buy in ledger.scheduled_market_purchases:
        if str(buy.get("purpose", "")).startswith("candidate_"):
            continue
        b_day = buy.get("day")
        if b_day is not None:
            existing_scheduled_by_day[b_day] = existing_scheduled_by_day.get(b_day, 0) + int(buy.get("units", 0))

    for target_day in operational_days:
        new_deliveries = sum(d.units for d in ledger.secured_wheat_deliveries if d.day == target_day)
        cumulative_physical_deliveries += new_deliveries

        new_scheduled = existing_scheduled_by_day.get(target_day, 0)

        if target_day == day:
            needed_day = ledger.unfed_placed_today
            # Engine timing: unit actions occur BEFORE market actions.
            # If same-day market purchases cannot help today before the feeding deadline,
            # new_scheduled arriving today gives ZERO credit toward today's feed obligation.
            market_usable_for_needed = new_scheduled if can_help_today else 0
        else:
            needed_day = n_placed
            market_usable_for_needed = new_scheduled

        cumulative_needed += needed_day

        available_before_buy = (
            ledger.current_total_wheat_on_hand
            + cumulative_physical_deliveries
            + cumulative_market_purchased
            + market_usable_for_needed
        )
        deficit = max(0, cumulative_needed - available_before_buy)

        shed_feed_consumed_prior = max(0, feed_consumed_prior - ledger.wheat_on_workers)
        prior_shed_wheat = max(0, ledger.wheat_in_shed + cumulative_market_purchased_prior - shed_feed_consumed_prior)
        current_shed_load = ledger.shed_other_units + ledger.candidate_storage_slots_reserved + prior_shed_wheat

        total_arriving_today = new_scheduled + deficit
        if current_shed_load + total_arriving_today > ledger.shed_capacity:
            blocking_reason = "shed_capacity"
            blocking_day = target_day
            break

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

            scheduled_buys.append({
                "day": target_day,
                "units": deficit,
                "cost": purchase_cost,
                "purpose": "existing_herd_operational",
            })
            cumulative_market_purchased += deficit
            current_cash -= purchase_cost

        feed_consumed_prior += needed_day
        # After today's feed deadline is resolved, same-day scheduled wheat enters inventory
        # and can count for following days.
        cumulative_market_purchased += new_scheduled
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
            price_policy=ledger.lifetime_price_policy,
            execution_confidence=exec_conf,
        )
        return False, res

    last_op_day = operational_days[-1] if operational_days else day - 1
    remaining_feeding_days_beyond = max(0, ANIMAL_FEED_CUTOFF_DAY - (last_op_day + 1))

    placed_lifetime_units = n_placed * remaining_feeding_days_beyond
    total_feeding_days_from_today = max(0, ANIMAL_FEED_CUTOFF_DAY - day)
    unplaced_lifetime_units = n_unplaced * total_feeding_days_from_today
    total_remaining_lifetime_units = placed_lifetime_units + unplaced_lifetime_units

    if ledger.lifetime_price_policy == "engine_stress_bound_v1":
        existing_future_market_req = cumulative_market_purchased + total_remaining_lifetime_units
        stress_price, stress_diag = compute_engine_stress_wheat_price(
            current_market_wheat_inventory=ledger.wheat_market_inventory,
            worst_case_town_drain=ledger.town_wheat_drain,
            our_committed_future_market_feed_requirement=existing_future_market_req,
            opponent_feed_liability=ledger.opponent_feed_liability,
            executable_buffered_price=ledger.wheat_price_current,
        )
        lifetime_wheat_price = stress_price
        ledger.lifetime_wheat_price = stress_price
        ledger.stressed_wheat_inventory = stress_diag["stressed_wheat_inventory"]
        ledger.stress_raw_price = stress_diag["stress_raw_price"]
        ledger.stress_buffered_price = stress_diag["stress_buffered_price"]
    else:
        lifetime_wheat_price = ledger.wheat_price_current
        ledger.lifetime_wheat_price = ledger.wheat_price_current
        stress_diag = {}

    placed_lifetime_cost = float(placed_lifetime_units * lifetime_wheat_price)
    unplaced_lifetime_cost = float(unplaced_lifetime_units * lifetime_wheat_price)
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
            price_policy=ledger.lifetime_price_policy,
            execution_confidence=exec_conf,
            diagnostics={
                "near_term_market_cost": near_term_market_wheat_cost,
                "placed_lifetime_cost": placed_lifetime_cost,
                "unplaced_lifetime_cost": unplaced_lifetime_cost,
                "unplaced_timing_assumption": ledger.unplaced_timing_assumption,
                "lifetime_wheat_price": lifetime_wheat_price,
                "stress_diagnostics": stress_diag,
            },
        )
        ledger.existing_feed_cash_hold = float(total_existing_feed_cash_required)
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
        price_policy=ledger.lifetime_price_policy,
        execution_confidence=exec_conf,
        diagnostics={
            "near_term_market_cost": near_term_market_wheat_cost,
            "placed_lifetime_cost": placed_lifetime_cost,
            "unplaced_lifetime_cost": unplaced_lifetime_cost,
            "unplaced_timing_assumption": ledger.unplaced_timing_assumption,
            "lifetime_wheat_price": lifetime_wheat_price,
            "stress_diagnostics": stress_diag,
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

    # Pure candidate evaluation: operate strictly on working clone without mutating caller's ledger
    working = ledger.clone()
    existing_ok, existing_res = evaluate_existing_herd_feasibility(working)
    working.existing_feed_cash_hold = float(existing_res.existing_feed_cash_hold)

    exec_conf = working.execution_snapshot.execution_confidence if working.execution_snapshot is not None else "guarded"
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

    available_candidate_cash = working.available_cash_for_candidates
    if purchase_cost > available_candidate_cash:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=True,
            candidate_species=candidate_species,
            blocking_day=working.day,
            blocking_reason="insufficient_cash",
            minimum_cash_slack=available_candidate_cash - purchase_cost,
            existing_feed_cash_hold=existing_res.existing_feed_cash_hold,
            candidate_feed_cash_hold=0.0,
            execution_confidence=exec_conf,
        )

    # Prospective candidate storage accounting:
    # A newly purchased animal conservatively occupies 1 storage slot in the shed upon acquisition.
    # We do NOT mutate the caller's ledger; we reserve this prospective slot on working.
    prospective_candidate_storage_slots = working.candidate_storage_slots_reserved + 1

    # Immediate shed capacity check for prospective candidate animal:
    initial_shed_load = working.shed_other_units + working.wheat_in_shed + prospective_candidate_storage_slots
    if initial_shed_load > working.shed_capacity:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=True,
            candidate_species=candidate_species,
            blocking_day=working.day,
            blocking_reason="shed_capacity",
            minimum_cash_slack=available_candidate_cash - purchase_cost,
            existing_feed_cash_hold=existing_res.existing_feed_cash_hold,
            candidate_feed_cash_hold=0.0,
            execution_confidence=exec_conf,
        )

    day = working.day
    hour = working.hour
    horizon = working.operational_horizon_days
    operational_days = [d for d in range(day, day + horizon) if d < ANIMAL_FEED_CUTOFF_DAY]

    can_help_today = True
    if working.execution_snapshot is not None:
        can_help_today = working.execution_snapshot.market_purchase_can_help_today
    elif hour >= 23:
        can_help_today = False

    # Collect scheduled market purchases from baseline herd and prior committed candidates
    existing_scheduled_units_by_day: Dict[int, int] = {}
    for buy in existing_res.scheduled_market_purchases:
        b_day = buy["day"]
        existing_scheduled_units_by_day[b_day] = existing_scheduled_units_by_day.get(b_day, 0) + buy["units"]
    for buy in working.scheduled_market_purchases:
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
    cumulative_existing_market_prior = 0
    cumulative_cand_market_prior = 0

    for target_day in operational_days:
        new_deliveries = sum(d.units for d in working.secured_wheat_deliveries if d.day == target_day)
        cumulative_deliveries += new_deliveries

        # Prefix timing: market purchases scheduled for target_day
        new_existing_market_wheat = existing_scheduled_units_by_day.get(target_day, 0)

        # Day-by-day feed requirements:
        # Today: unfed placed animals need feed; candidate and prior candidates do NOT eat today (unplaced).
        # Future days: baseline placed herd + prior committed candidates + current candidate eat 1 each.
        if target_day == day:
            needed_day = working.unfed_placed_today
            # Engine timing: unit actions occur BEFORE market actions.
            # If same-day market purchases cannot help today before the feeding deadline,
            # new_existing_market_wheat arriving today gives ZERO credit toward today's feed obligation.
            market_usable_for_needed = new_existing_market_wheat if can_help_today else 0
        else:
            needed_day = working.total_placed_animals + len(working.candidate_reservations) + 1
            market_usable_for_needed = new_existing_market_wheat

        cumulative_needed += needed_day

        available_before_cand_buy = (
            working.current_total_wheat_on_hand
            + cumulative_deliveries
            + cumulative_market_purchased
            + market_usable_for_needed
        )
        deficit = max(0, cumulative_needed - available_before_cand_buy)

        # Shed capacity check on target_day at acquisition:
        # Must account for:
        # 1. Non-wheat items + prospective candidate animal storage slots (+1 for currently evaluated candidate)
        # 2. Wheat in shed before today's arrivals (initial wheat + market wheat arrived BEFORE target_day - feed consumed from shed BEFORE target_day)
        # 3. All market wheat arriving on target_day (previously committed arriving today + candidate's deficit)
        shed_feed_consumed_prior = max(0, feed_consumed_prior - working.wheat_on_workers)
        market_arrived_prior = cumulative_existing_market_prior + cumulative_cand_market_prior
        prior_shed_wheat = max(0, working.wheat_in_shed + market_arrived_prior - shed_feed_consumed_prior)
        base_shed_load = working.shed_other_units + prospective_candidate_storage_slots + prior_shed_wheat

        total_arriving_today = new_existing_market_wheat + deficit
        if base_shed_load + total_arriving_today > working.shed_capacity:
            blocking_reason = "shed_capacity"
            blocking_day = target_day
            break

        if deficit > 0:
            if target_day == day and not can_help_today:
                blocking_reason = "late_hour_purchase"
                blocking_day = day
                break

            buy_cost = float(deficit * working.wheat_price_current)
            if buy_cost > running_candidate_cash:
                blocking_reason = "insufficient_cash"
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
        # After today's feed deadline is resolved, same-day scheduled wheat enters inventory
        # and can count for following days.
        cumulative_market_purchased += new_existing_market_wheat
        cumulative_existing_market_prior += new_existing_market_wheat
        cumulative_cand_market_prior = cand_cumulative_market_purchased

        slack = (
            working.current_total_wheat_on_hand
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
    cand_near_term_market_units = cand_cumulative_market_purchased
    cand_near_term_market_cost = sum(b["cost"] for b in cand_scheduled_buys)

    existing_near_term_market_units = existing_res.near_term_market_wheat_required
    existing_near_term_market_cost = sum(b["cost"] for b in existing_res.scheduled_market_purchases)
    existing_lifetime_units = existing_res.remaining_lifetime_feed_units

    prior_near_term_market_units = sum(r.get("near_term_market_wheat_required", 0) for r in working.candidate_reservations)
    prior_near_term_market_cost = sum(
        sum(b.get("cost", 0.0) for b in r.get("scheduled_market_purchases", []))
        for r in working.candidate_reservations
    )
    prior_lifetime_units = sum(r.get("remaining_lifetime_feed_units", 0) for r in working.candidate_reservations)

    combined_future_market_req = (
        existing_near_term_market_units + existing_lifetime_units
        + prior_near_term_market_units + prior_lifetime_units
        + cand_near_term_market_units + cand_lifetime_units
    )

    if working.lifetime_price_policy == "engine_stress_bound_v1":
        new_stress_price, stress_diag = compute_engine_stress_wheat_price(
            current_market_wheat_inventory=working.wheat_market_inventory,
            worst_case_town_drain=working.town_wheat_drain,
            our_committed_future_market_feed_requirement=combined_future_market_req,
            opponent_feed_liability=working.opponent_feed_liability,
            executable_buffered_price=working.wheat_price_current,
        )
    else:
        new_stress_price = working.wheat_price_current
        stress_diag = {}

    new_required_existing_hold = existing_near_term_market_cost + existing_lifetime_units * new_stress_price
    new_required_committed_candidate_hold = prior_near_term_market_cost + prior_lifetime_units * new_stress_price
    new_candidate_own_hold = cand_near_term_market_cost + cand_lifetime_units * new_stress_price

    delta_existing = max(0.0, new_required_existing_hold - working.existing_feed_cash_hold)
    delta_prior = max(0.0, new_required_committed_candidate_hold - working.candidate_feed_cash_hold)
    delta_total_feed = delta_existing + delta_prior + new_candidate_own_hold

    cand_near_term_feed_units = sum(1 for d in operational_days if d > day)

    if purchase_cost + delta_total_feed > available_candidate_cash:
        return FeedFeasibilityResult(
            feasible=False,
            existing_herd_feasible=True,
            candidate_species=candidate_species,
            blocking_day=last_op_day + 1,
            blocking_reason="insufficient_cash",
            near_term_feed_units=cand_near_term_feed_units,
            near_term_market_wheat_required=cand_cumulative_market_purchased,
            remaining_lifetime_feed_units=cand_lifetime_units,
            remaining_feed_cash_required=cand_lifetime_units * new_stress_price,
            existing_feed_cash_hold=new_required_existing_hold,
            candidate_feed_cash_hold=new_required_committed_candidate_hold + new_candidate_own_hold,
            minimum_wheat_slack=min_wheat_slack,
            minimum_cash_slack=available_candidate_cash - (purchase_cost + delta_total_feed),
            scheduled_market_purchases=cand_scheduled_buys,
            daily_timeline=daily_timeline,
            price_policy=working.lifetime_price_policy,
            execution_confidence=exec_conf,
            diagnostics={
                "purchase_cost": purchase_cost,
                "cand_near_term_market_cost": cand_near_term_market_cost,
                "cand_lifetime_cost": cand_lifetime_units * new_stress_price,
                "new_required_existing_hold": new_required_existing_hold,
                "new_required_committed_candidate_hold": new_required_committed_candidate_hold,
                "new_candidate_own_hold": new_candidate_own_hold,
                "delta_existing": delta_existing,
                "delta_prior": delta_prior,
                "delta_total_feed": delta_total_feed,
                "new_stress_price": new_stress_price,
                "stress_diagnostics": stress_diag,
            },
        )

    min_cash_slack = available_candidate_cash - (purchase_cost + delta_total_feed)

    return FeedFeasibilityResult(
        feasible=True,
        existing_herd_feasible=True,
        candidate_species=candidate_species,
        near_term_feed_units=cand_near_term_feed_units,
        near_term_market_wheat_required=cand_cumulative_market_purchased,
        remaining_lifetime_feed_units=cand_lifetime_units,
        remaining_feed_cash_required=cand_lifetime_units * new_stress_price,
        existing_feed_cash_hold=new_required_existing_hold,
        candidate_feed_cash_hold=new_required_committed_candidate_hold + new_candidate_own_hold,
        minimum_wheat_slack=min_wheat_slack,
        minimum_cash_slack=min_cash_slack,
        scheduled_market_purchases=cand_scheduled_buys,
        daily_timeline=daily_timeline,
        price_policy=working.lifetime_price_policy,
        execution_confidence=exec_conf,
        diagnostics={
            "purchase_cost": purchase_cost,
            "cand_near_term_market_cost": cand_near_term_market_cost,
            "cand_lifetime_cost": cand_lifetime_units * new_stress_price,
            "new_required_existing_hold": new_required_existing_hold,
            "new_required_committed_candidate_hold": new_required_committed_candidate_hold,
            "new_candidate_own_hold": new_candidate_own_hold,
            "delta_existing": delta_existing,
            "delta_prior": delta_prior,
            "delta_total_feed": delta_total_feed,
            "new_stress_price": new_stress_price,
            "stress_diagnostics": stress_diag,
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
      - Accurately reprices existing and candidate holds under engine_stress_bound_v1.
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

    diag = result.diagnostics or {}
    if "new_required_existing_hold" in diag:
        ledger.existing_feed_cash_hold = float(diag["new_required_existing_hold"])
    if "new_candidate_own_hold" in diag and "new_required_committed_candidate_hold" in diag:
        ledger.candidate_feed_cash_hold = float(diag["new_required_committed_candidate_hold"] + diag["new_candidate_own_hold"])
    else:
        ledger.candidate_feed_cash_hold += float(result.candidate_feed_cash_hold)

    if "stress_diagnostics" in diag and diag["stress_diagnostics"]:
        s_diag = diag["stress_diagnostics"]
        ledger.stressed_wheat_inventory = float(s_diag.get("stressed_wheat_inventory", ledger.stressed_wheat_inventory))
        ledger.stress_raw_price = float(s_diag.get("stress_raw_price", ledger.stress_raw_price))
        ledger.stress_buffered_price = float(s_diag.get("stress_buffered_price", ledger.stress_buffered_price))
        ledger.lifetime_wheat_price = float(s_diag.get("lifetime_wheat_price", ledger.lifetime_wheat_price))
    elif "new_stress_price" in diag:
        ledger.lifetime_wheat_price = float(diag["new_stress_price"])

    ledger.candidate_purchase_cash_spent += float(purchase_cost)
    ledger.candidate_storage_slots_reserved += 1
    ledger.scheduled_market_purchases.extend(result.scheduled_market_purchases)

    reservation_record = {
        "species": candidate_species,
        "purchase_cost": purchase_cost,
        "candidate_feed_cash_hold": diag.get("new_candidate_own_hold", result.candidate_feed_cash_hold),
        "candidate_storage_slots_reserved": 1,
        "near_term_market_wheat_required": result.near_term_market_wheat_required,
        "remaining_lifetime_feed_units": result.remaining_lifetime_feed_units,
        "scheduled_market_purchases": copy.deepcopy(result.scheduled_market_purchases),
    }
    ledger.candidate_reservations.append(reservation_record)
